"""S5 数据索引与批处理读取模块（纯 CPU / NumPy）。

包含：
- ClipIndex: 分区切片索引管理，支持按世界号嵌套抽分子集 (subset_by_worlds)；
- load_item: 读取单段数据、计算 tubelet patches、加载真值标签与可选教师特征，带 SHA256 账本校验；
- batches: 确定性随机批次生成器，丢弃不足一批的尾部样本。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator, Sequence

import numpy as np

from ainerzero.v9.experiments.s5.tokens import tubelet_patches


DEFAULT_CACHE_MAX_BYTES = 48 * (1024 ** 3)  # 48 GiB 默认上限

# 进程级教师文件 SHA 核对缓存：每个进程每个文件只核对一次
_VERIFIED_TEACHER_SHAS: dict[str, str] = {}
_LEDGER_CACHE: dict[tuple[str, int, int], dict[str, str]] = {}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


class ItemCache:
    """进程内数据与教师特征缓存（带字节上限）。

    缓存内容：
    - uint8 原始段数组 (clip_raw)
    - 标签数组与元数据字典 (r1_logd, r1_sky, r1_obj, r2, r3, disk_groups, ordering_pairs)
    - 教师特征数组 (vjepa, da2, fp16)
    tubelet_patches 每次从 uint8 原始段现算，不入缓存。
    超过 max_bytes 上限时不再缓存新条目，但照常读取返回，不报错。
    """

    def __init__(self, max_bytes: int = DEFAULT_CACHE_MAX_BYTES) -> None:
        self.max_bytes = int(max_bytes)
        self.used_bytes = 0
        self._items: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        if key in self._items:
            self.hits += 1
            return self._items[key]
        self.misses += 1
        return None

    def put(self, key: str, value: Any, nbytes: int) -> bool:
        nbytes = int(nbytes)
        if key in self._items:
            return True
        if nbytes < 0 or self.used_bytes + nbytes > self.max_bytes:
            return False
        self._items[key] = value
        self.used_bytes += nbytes
        return True

    def clear(self) -> None:
        self._items.clear()
        self.used_bytes = 0
        self.hits = 0
        self.misses = 0

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, key: str) -> bool:
        return key in self._items



class ClipIndex:
    """分区数据切片索引。管理可用 (world, clip) 列表。"""

    def __init__(
        self,
        partition_dir: str | Path,
        worlds: Sequence[int] | None = None,
        clips: Sequence[int] | None = None,
    ):
        self.partition_dir = Path(partition_dir)
        if not self.partition_dir.exists():
            raise FileNotFoundError(f"Partition directory {self.partition_dir} not found")

        # 扫描所有可用的 world_XXXX 目录
        all_w_dirs = sorted(
            [p for p in self.partition_dir.iterdir() if p.is_dir() and p.name.startswith("world_")]
        )
        avail_worlds: dict[int, Path] = {}
        for p in all_w_dirs:
            try:
                w_num = int(p.name.split("_")[1])
                avail_worlds[w_num] = p
            except (IndexError, ValueError):
                continue

        # 过滤 world
        if worlds is not None:
            w_set = set(worlds)
            selected_worlds = [w for w in sorted(avail_worlds.keys()) if w in w_set]
        else:
            selected_worlds = sorted(avail_worlds.keys())

        self.worlds = selected_worlds
        self.world_dirs = {w: avail_worlds[w] for w in selected_worlds}

        # 扫描并组装 (world, clip) 列表
        items: list[tuple[int, int]] = []
        c_set = set(clips) if clips is not None else None

        for w in selected_worlds:
            wdir = self.world_dirs[w]
            # 扫描 clip_XX.npy 或 clip_XX_*.npy
            clip_files = sorted(wdir.glob("clip_[0-9][0-9]*.npy"))
            seen_clips = set()
            for cf in clip_files:
                name = cf.name
                # clip_00.npy 或 clip_00_shift_bg.npy
                try:
                    c_num = int(name.split("_")[1].split(".")[0])
                    if c_num not in seen_clips:
                        if c_set is None or c_num in c_set:
                            seen_clips.add(c_num)
                except (IndexError, ValueError):
                    continue

            for c in sorted(seen_clips):
                items.append((w, c))

        self.items = items

    def __len__(self) -> int:
        return len(self.items)

    def __getitem__(self, idx: int) -> tuple[int, int]:
        return self.items[idx]

    def subset_by_worlds(self, n: int, seed: int) -> ClipIndex:
        """从当前可用世界中抽取 n 个世界，采用嵌套抽法：

        同一 seed 下，n 较小的子集世界列表严格是 n 较大子集世界列表的前缀。
        例如 L=64(4个世界) 严格包含在 L=512(32个世界) 中，后者严格包含在 L=2048(128个世界) 中。
        """
        if n > len(self.worlds):
            raise ValueError(f"Requested {n} worlds, but only {len(self.worlds)} available")

        # 使用固定 seed 生成世界列表的确定性全排列
        rng = np.random.default_rng(seed)
        shuffled = rng.permutation(self.worlds).tolist()
        chosen_worlds = sorted(shuffled[:n])

        # 返回仅包含抽中世界的新 ClipIndex
        return ClipIndex(self.partition_dir, worlds=chosen_worlds)


def _load_progress_ledger(teachers_dir: Path) -> dict[str, str]:
    ledger_path = teachers_dir / "progress.jsonl"
    if not ledger_path.exists():
        return {}
    st = ledger_path.stat()
    cache_key = (str(ledger_path.resolve()), st.st_mtime_ns, st.st_size)
    if cache_key in _LEDGER_CACHE:
        return _LEDGER_CACHE[cache_key]
    ledger: dict[str, str] = {}
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            ledger[rec["file"]] = rec["sha256"]
    _LEDGER_CACHE[cache_key] = ledger
    return ledger


def _verify_teacher_file_once(file_path: Path, expected_sha: str, label: str) -> None:
    """每个进程每个教师文件只算一次 SHA256；首次读入前若被改动照常报错。"""
    key = str(file_path.resolve())
    if _VERIFIED_TEACHER_SHAS.get(key) == expected_sha:
        return
    got_sha = _sha256_file(file_path)
    if got_sha != expected_sha:
        raise RuntimeError(
            f"{label} feature {file_path} SHA mismatch: got {got_sha} != ledger {expected_sha}"
        )
    _VERIFIED_TEACHER_SHAS[key] = got_sha


def load_item(
    index: ClipIndex,
    i: int,
    *,
    teachers: str | Path | dict[str, str | Path] | None = None,
    appearance_suffix: str = "",
    cache: ItemCache | None = None,
) -> dict[str, Any]:
    """读取指定索引 i 处的切片数据与标签。

    返回字典包含：
    - patches: tubelet_patches 转换后的 float32 [8, 14, 14, 1536]（每次从 uint8 原始段现算）
    - r1_logd, r1_sky, r1_obj: 来自 labels_YY.npz
    - r2, r3: 网格占据标签 [12, 7]
    - disk_groups: 圆盘属性字典列表
    - ordering_pairs: 前后次序对字典列表
    - vjepa (若提供了 teachers): fp16 [1568, 1024]
    - da2 (若提供了 teachers): fp16 [8, 56, 56]
    """
    w, c = index[i]
    wdir = index.world_dirs[w]

    # 1. 加载 clip（缓存 uint8 原始段，patches 每次现算）
    suffix = f"_{appearance_suffix}" if appearance_suffix else ""
    clip_file = wdir / f"clip_{c:02d}{suffix}.npy"
    if not clip_file.exists():
        # 若未找到带特定 appearance 的，降级尝试无 suffix 的主文件
        clip_file = wdir / f"clip_{c:02d}.npy"

    clip_key = f"clip:{clip_file.resolve()}"
    clip_raw = cache.get(clip_key) if cache is not None else None
    if clip_raw is None:
        if not clip_file.exists():
            raise FileNotFoundError(f"Clip file not found: {clip_file}")
        clip_raw = np.load(clip_file)  # uint8 [16, 224, 224, 3]
        if cache is not None:
            cache.put(clip_key, clip_raw, int(clip_raw.nbytes))

    patches = tubelet_patches(clip_raw)  # float32 [8, 14, 14, 1536]

    # 2. 加载标签（缓存标签数组与字典）
    labels_file = wdir / f"labels_{c:02d}.npz"
    labels_key = f"labels:{labels_file.resolve()}"
    cached_labels = cache.get(labels_key) if cache is not None else None
    if cached_labels is None:
        if not labels_file.exists():
            raise FileNotFoundError(f"Labels file not found: {labels_file}")
        with np.load(labels_file, allow_pickle=True) as npz:
            r1_logd = npz["r1_logd"]
            r1_sky = npz["r1_sky"]
            r1_obj = npz["r1_obj"]
            r2 = npz["r2"]
            r3 = npz["r3"]
            disk_groups = json.loads(str(npz["disk_groups_json"]))
            ordering_pairs = json.loads(str(npz["ordering_pairs_json"]))
        cached_labels = {
            "r1_logd": r1_logd,
            "r1_sky": r1_sky,
            "r1_obj": r1_obj,
            "r2": r2,
            "r3": r3,
            "disk_groups": disk_groups,
            "ordering_pairs": ordering_pairs,
        }
        if cache is not None:
            lbl_bytes = int(
                r1_logd.nbytes + r1_sky.nbytes + r1_obj.nbytes + r2.nbytes + r3.nbytes
            )
            cache.put(labels_key, cached_labels, lbl_bytes)

    item: dict[str, Any] = {
        "world": w,
        "clip": c,
        "patches": patches,
        "r1_logd": cached_labels["r1_logd"],
        "r1_sky": cached_labels["r1_sky"],
        "r1_obj": cached_labels["r1_obj"],
        "r2": cached_labels["r2"],
        "r3": cached_labels["r3"],
        "disk_groups": cached_labels["disk_groups"],
        "ordering_pairs": cached_labels["ordering_pairs"],
    }

    # 3. 若指定了 teachers，加载教师特征并校验 progress 账本 SHA
    if teachers is not None:
        item.update(load_teacher(index, i, teachers, cache=cache))

    return item


def load_teacher(
    index: ClipIndex,
    i: int,
    teachers: str | Path | dict[str, str | Path],
    *,
    teacher_types: Sequence[str] | None = None,
    cache: ItemCache | None = None,
) -> dict[str, np.ndarray]:
    """仅读取指定索引 i 处的教师特征，核对 progress.jsonl 账本中的 SHA256（每进程每文件一次）。"""
    w, c = index[i]
    if isinstance(teachers, (str, Path)):
        vjepa_dir = Path(teachers)
        da2_dir = Path(teachers)
        active_types = tuple(teacher_types) if teacher_types is not None else ("vjepa", "da2")
    else:
        vjepa_dir = Path(teachers.get("vjepa", teachers.get("vjepa_dir", ".")))
        da2_dir = Path(teachers.get("da2", teachers.get("da2_dir", ".")))
        if teacher_types is not None:
            active_types = tuple(teacher_types)
        else:
            active_types = tuple(
                t for t in ("vjepa", "da2") if t in teachers or f"{t}_dir" in teachers
            ) or ("vjepa", "da2")

    res: dict[str, np.ndarray] = {}

    if "vjepa" in active_types:
        vjepa_rel = f"world_{w:04d}/clip_{c:02d}.vjepa.npy"
        vjepa_file = vjepa_dir / vjepa_rel
        vjepa_key = f"vjepa:{vjepa_file.resolve()}"
        vjepa_arr = cache.get(vjepa_key) if cache is not None else None
        if vjepa_arr is None:
            if not vjepa_file.exists():
                raise FileNotFoundError(f"V-JEPA feature not found: {vjepa_file}")

            vjepa_ledger = _load_progress_ledger(vjepa_dir)
            if vjepa_rel in vjepa_ledger:
                _verify_teacher_file_once(vjepa_file, vjepa_ledger[vjepa_rel], "V-JEPA")
            vjepa_arr = np.load(vjepa_file)
            if cache is not None:
                cache.put(vjepa_key, vjepa_arr, int(vjepa_arr.nbytes))
        res["vjepa"] = vjepa_arr

    if "da2" in active_types:
        da2_rel = f"world_{w:04d}/da2_{c:02d}.da2.npy"
        da2_file = da2_dir / da2_rel
        da2_key = f"da2:{da2_file.resolve()}"
        da2_arr = cache.get(da2_key) if cache is not None else None
        if da2_arr is None:
            if not da2_file.exists():
                raise FileNotFoundError(f"DA2 feature not found: {da2_file}")

            da2_ledger = _load_progress_ledger(da2_dir)
            if da2_rel in da2_ledger:
                _verify_teacher_file_once(da2_file, da2_ledger[da2_rel], "DA2")
            da2_arr = np.load(da2_file)
            if cache is not None:
                cache.put(da2_key, da2_arr, int(da2_arr.nbytes))
        res["da2"] = da2_arr

    return res


def batches(index: ClipIndex, batch_size: int, seed: int, epoch: int) -> Iterator[list[int]]:
    """确定性随机生成批次下标列表。最后不足 batch_size 的部分直接丢弃。"""
    n_items = len(index)
    if n_items < batch_size:
        return

    # 使用 (seed, epoch) 确定性打乱
    ss = np.random.SeedSequence([seed, epoch])
    rng = np.random.default_rng(ss)
    perm = rng.permutation(n_items)

    n_batches = n_items // batch_size
    for b in range(n_batches):
        yield perm[b * batch_size : (b + 1) * batch_size].tolist()
