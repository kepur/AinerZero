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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


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
    ledger: dict[str, str] = {}
    if ledger_path.exists():
        for line in ledger_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                rec = json.loads(line)
                ledger[rec["file"]] = rec["sha256"]
    return ledger


def load_item(
    index: ClipIndex,
    i: int,
    *,
    teachers: str | Path | dict[str, str | Path] | None = None,
    appearance_suffix: str = "",
) -> dict[str, Any]:
    """读取指定索引 i 处的切片数据与标签。

    返回字典包含：
    - patches: tubelet_patches 转换后的 float32 [8, 14, 14, 1536]
    - r1_logd, r1_sky, r1_obj: 来自 labels_YY.npz
    - r2, r3: 网格占据标签 [12, 7]
    - disk_groups: 圆盘属性字典列表
    - ordering_pairs: 前后次序对字典列表
    - vjepa (若提供了 teachers): fp16 [1568, 1024]
    - da2 (若提供了 teachers): fp16 [8, 56, 56]
    """
    w, c = index[i]
    wdir = index.world_dirs[w]

    # 1. 加载 clip
    suffix = f"_{appearance_suffix}" if appearance_suffix else ""
    clip_file = wdir / f"clip_{c:02d}{suffix}.npy"
    if not clip_file.exists():
        # 若未找到带特定 appearance 的，降级尝试无 suffix 的主文件
        clip_file = wdir / f"clip_{c:02d}.npy"
    if not clip_file.exists():
        raise FileNotFoundError(f"Clip file not found: {clip_file}")

    clip_raw = np.load(clip_file)  # uint8 [16, 224, 224, 3]
    patches = tubelet_patches(clip_raw)  # float32 [8, 14, 14, 1536]

    # 2. 加载标签
    labels_file = wdir / f"labels_{c:02d}.npz"
    if not labels_file.exists():
        raise FileNotFoundError(f"Labels file not found: {labels_file}")

    npz = np.load(labels_file, allow_pickle=True)
    r1_logd = npz["r1_logd"]
    r1_sky = npz["r1_sky"]
    r1_obj = npz["r1_obj"]
    r2 = npz["r2"]
    r3 = npz["r3"]
    disk_groups = json.loads(str(npz["disk_groups_json"]))
    ordering_pairs = json.loads(str(npz["ordering_pairs_json"]))

    item: dict[str, Any] = {
        "world": w,
        "clip": c,
        "patches": patches,
        "r1_logd": r1_logd,
        "r1_sky": r1_sky,
        "r1_obj": r1_obj,
        "r2": r2,
        "r3": r3,
        "disk_groups": disk_groups,
        "ordering_pairs": ordering_pairs,
    }

    # 3. 若指定了 teachers，加载教师特征并校验 progress 账本 SHA
    if teachers is not None:
        item.update(load_teacher(index, i, teachers))

    return item


def load_teacher(
    index: ClipIndex,
    i: int,
    teachers: str | Path | dict[str, str | Path],
    *,
    teacher_types: Sequence[str] = ("vjepa", "da2"),
) -> dict[str, np.ndarray]:
    """仅读取指定索引 i 处的教师特征，核对 progress.jsonl 账本中的 SHA256。"""
    w, c = index[i]
    if isinstance(teachers, (str, Path)):
        vjepa_dir = Path(teachers)
        da2_dir = Path(teachers)
    else:
        vjepa_dir = Path(teachers.get("vjepa", teachers.get("vjepa_dir", ".")))
        da2_dir = Path(teachers.get("da2", teachers.get("da2_dir", ".")))

    res: dict[str, np.ndarray] = {}

    if "vjepa" in teacher_types:
        vjepa_rel = f"world_{w:04d}/clip_{c:02d}.vjepa.npy"
        vjepa_file = vjepa_dir / vjepa_rel
        if not vjepa_file.exists():
            raise FileNotFoundError(f"V-JEPA feature not found: {vjepa_file}")

        vjepa_ledger = _load_progress_ledger(vjepa_dir)
        if vjepa_rel in vjepa_ledger:
            got_sha = _sha256_file(vjepa_file)
            if got_sha != vjepa_ledger[vjepa_rel]:
                raise RuntimeError(
                    f"V-JEPA feature {vjepa_file} SHA mismatch: got {got_sha} != ledger {vjepa_ledger[vjepa_rel]}"
                )
        res["vjepa"] = np.load(vjepa_file)

    if "da2" in teacher_types:
        da2_rel = f"world_{w:04d}/da2_{c:02d}.da2.npy"
        da2_file = da2_dir / da2_rel
        if not da2_file.exists():
            raise FileNotFoundError(f"DA2 feature not found: {da2_file}")

        da2_ledger = _load_progress_ledger(da2_dir)
        if da2_rel in da2_ledger:
            got_sha = _sha256_file(da2_file)
            if got_sha != da2_ledger[da2_rel]:
                raise RuntimeError(
                    f"DA2 feature {da2_file} SHA mismatch: got {got_sha} != ledger {da2_ledger[da2_rel]}"
                )
        res["da2"] = np.load(da2_file)

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
