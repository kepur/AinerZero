"""S5 数据索引与读取模块纯 CPU 契约测试。

测试覆盖：
1. ClipIndex 的排序顺序；subset_by_worlds 嵌套前缀性质；L=64、512、2048 对应的世界数；
2. load_item 的 patches 等于 tubelet_patches(student_clip(...))；标签与 npz 逐项一致；
3. 篡改教师特征文件后读取抛出 RuntimeError；
4. batches 的确定性；不同 epoch 顺序不同；丢弃不足一批的尾部部分。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s5 import data as D
from ainerzero.v9.experiments.s5.materialize import materialize_partition
from ainerzero.v9.experiments.s5.tokens import tubelet_patches
from ainerzero.v9.experiments.s5.world import student_clip


@pytest.fixture(scope="module")
def fixture_partition(tmp_path_factory) -> Path:
    """物化一个极小的 s5test-data 分区作为测试夹具（2 个世界，每个世界 16 段）。"""
    root = tmp_path_factory.mktemp("data_fixture")
    part_dir = root / "part"
    materialize_partition("s5test-data", part_dir, world_range=(0, 2))

    # 生成假教师特征与 progress.jsonl
    teachers_dir = root / "teachers"
    teachers_dir.mkdir(parents=True)
    ledger_lines = []

    for w in range(2):
        wdir = teachers_dir / f"world_{w:04d}"
        wdir.mkdir(parents=True)
        for c in range(16):
            # V-JEPA: [1568, 1024] fp16
            v_file = wdir / f"clip_{c:02d}.vjepa.npy"
            v_data = np.full((1568, 1024), float(w * 16 + c), dtype=np.float16)
            np.save(v_file, v_data)
            v_rel = f"world_{w:04d}/clip_{c:02d}.vjepa.npy"
            v_sha = D._sha256_file(v_file)
            ledger_lines.append(json.dumps({"file": v_rel, "sha256": v_sha, "seconds": 0.01, "at": 1000.0}))

            # DA2: [8, 56, 56] fp16
            d_file = wdir / f"da2_{c:02d}.da2.npy"
            d_data = np.full((8, 56, 56), float(w * 16 + c), dtype=np.float16)
            np.save(d_file, d_data)
            d_rel = f"world_{w:04d}/da2_{c:02d}.da2.npy"
            d_sha = D._sha256_file(d_file)
            ledger_lines.append(json.dumps({"file": d_rel, "sha256": d_sha, "seconds": 0.01, "at": 1000.0}))

    (teachers_dir / "progress.jsonl").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    return root


def test_clip_index_ordering_and_nested_subsets(tmp_path):
    # 构造含 130 个世界虚拟目录验证嵌套子集性质
    mock_part = tmp_path / "mock_part"
    mock_part.mkdir()
    for w in range(130):
        wdir = mock_part / f"world_{w:04d}"
        wdir.mkdir()
        for c in range(16):
            (wdir / f"clip_{c:02d}.npy").write_bytes(b"dummy")

    idx = D.ClipIndex(mock_part)
    assert len(idx) == 130 * 16
    assert idx.worlds == list(range(130))

    # 验证排序顺序：(world, clip)
    for i in range(len(idx) - 1):
        w1, c1 = idx[i]
        w2, c2 = idx[i + 1]
        assert (w1 < w2) or (w1 == w2 and c1 < c2)

    # 嵌套抽法验证：同一 seed 下，L=64(4世界) 是 L=512(32世界) 的前缀，后者是 L=2048(128世界) 的前缀
    sub_4 = idx.subset_by_worlds(4, seed=42)
    sub_32 = idx.subset_by_worlds(32, seed=42)
    sub_128 = idx.subset_by_worlds(128, seed=42)

    assert len(sub_4) == 4 * 16 == 64
    assert len(sub_32) == 32 * 16 == 512
    assert len(sub_128) == 128 * 16 == 2048

    # 抽中的无序世界必须保持嵌套包含关系
    rng = np.random.default_rng(42)
    shuffled_130 = rng.permutation(range(130)).tolist()

    assert set(sub_4.worlds) == set(shuffled_130[:4])
    assert set(sub_32.worlds) == set(shuffled_130[:32])
    assert set(sub_128.worlds) == set(shuffled_130[:128])
    assert set(sub_4.worlds).issubset(set(sub_32.worlds))
    assert set(sub_32.worlds).issubset(set(sub_128.worlds))


def test_load_item_patches_and_labels_parity(fixture_partition):
    part_dir = fixture_partition / "part"
    teachers_dir = fixture_partition / "teachers"
    idx = D.ClipIndex(part_dir)

    item = D.load_item(idx, 0, teachers=teachers_dir)
    assert item["world"] == 0 and item["clip"] == 0
    assert item["patches"].shape == (8, 14, 14, 1536)
    assert item["patches"].dtype == np.float32

    # 验证与 student_clip + tubelet_patches 直接调用的逐元素一致性
    from ainerzero.v9.experiments.s5.world import episode
    ep = episode("s5test-data", 0)
    raw_clip = student_clip(ep, 0)
    expected_patches = tubelet_patches(raw_clip)
    np.testing.assert_allclose(item["patches"], expected_patches, rtol=1e-5)

    # 验证标签与 disk labels 文件的逐项一致
    npz = np.load(part_dir / "world_0000" / "labels_00.npz")
    np.testing.assert_array_equal(item["r2"], npz["r2"])
    np.testing.assert_array_equal(item["r3"], npz["r3"])
    np.testing.assert_array_equal(item["r1_logd"], npz["r1_logd"])

    # 验证教师特征维度
    assert item["vjepa"].shape == (1568, 1024) and item["vjepa"].dtype == np.float16
    assert item["da2"].shape == (8, 56, 56) and item["da2"].dtype == np.float16


def test_tampered_teacher_output_raises_runtime_error(fixture_partition, tmp_path):
    # 复制一个教师目录并篡改其中一个文件的字节
    import shutil
    bad_teachers = tmp_path / "bad_teachers"
    shutil.copytree(fixture_partition / "teachers", bad_teachers)

    target_file = bad_teachers / "world_0000" / "clip_00.vjepa.npy"
    raw = bytearray(target_file.read_bytes())
    raw[-1] ^= 0xFF
    target_file.write_bytes(bytes(raw))

    idx = D.ClipIndex(fixture_partition / "part")
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        D.load_item(idx, 0, teachers=bad_teachers)


def test_batches_determinism_and_tail_drop(fixture_partition):
    part_dir = fixture_partition / "part"
    idx = D.ClipIndex(part_dir)  # 2 * 16 = 32 items

    # 1. 确定性测试：同一 (seed, epoch) 返回完全相同的批次
    b1 = list(D.batches(idx, batch_size=6, seed=123, epoch=0))
    b2 = list(D.batches(idx, batch_size=6, seed=123, epoch=0))
    assert b1 == b2

    # 2. 不同 epoch 顺序不同
    b_epoch1 = list(D.batches(idx, batch_size=6, seed=123, epoch=1))
    assert b1 != b_epoch1

    # 3. 尾部不足一批丢弃：32 项，batch_size=6 -> 5 批共 30 项，余 2 项丢弃
    assert len(b1) == 5
    for batch in b1:
        assert len(batch) == 6
    flattened = [item for batch in b1 for item in batch]
    assert len(flattened) == 30
    assert len(set(flattened)) == 30  # 无重复


def test_load_teacher_only_reads_teacher_features(fixture_partition):
    idx = D.ClipIndex(fixture_partition / "part")
    teachers = fixture_partition / "teachers"

    # 1. load_teacher 只读教师，不读学生 clip 与 labels
    t_both = D.load_teacher(idx, 0, teachers)
    assert set(t_both.keys()) == {"vjepa", "da2"}
    assert t_both["vjepa"].shape == (1568, 1024)
    assert t_both["da2"].shape == (8, 56, 56)

    # 2. 支持单独按类型读取
    t_vjepa = D.load_teacher(idx, 0, teachers, teacher_types=("vjepa",))
    assert list(t_vjepa.keys()) == ["vjepa"]

    t_da2 = D.load_teacher(idx, 0, teachers, teacher_types=("da2",))
    assert list(t_da2.keys()) == ["da2"]


# ------------------------------------------------------------------------------------------------
# P239：子集嵌套与确定性、ItemCache 进程内缓存、教师 SHA 单次核对、字节上限与坏对照
# ------------------------------------------------------------------------------------------------
LIVE_REPO = Path(__file__).resolve().parents[3]
REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
DATA_SRC = LIVE_REPO / "src/ainerzero/v9/experiments/s5/data.py"


@pytest.fixture(autouse=True)
def _reset_sha_cache():
    D._VERIFIED_TEACHER_SHAS.clear()
    D._LEDGER_CACHE.clear()


def test_lab_subset_nesting_and_determinism_with_frozen_seed(tmp_path):
    mock_lab = tmp_path / "mock_lab"
    mock_lab.mkdir()
    for w in range(128):
        wdir = mock_lab / f"world_{w:04d}"
        wdir.mkdir()
        for c in range(16):
            (wdir / f"clip_{c:02d}.npy").write_bytes(b"dummy")

    idx = D.ClipIndex(mock_lab)
    seed = 20261112
    sub_64 = idx.subset_by_worlds(4, seed=seed)
    sub_512 = idx.subset_by_worlds(32, seed=seed)
    sub_2048 = idx.subset_by_worlds(128, seed=seed)

    assert len(sub_64.worlds) == 4 and len(sub_64) == 64
    assert len(sub_512.worlds) == 32 and len(sub_512) == 512
    assert len(sub_2048.worlds) == 128 and len(sub_2048) == 2048

    # L=64 的世界严格是 L=512 世界的子集，L=512 的世界严格是 L=2048 世界的子集
    assert set(sub_64.worlds).issubset(set(sub_512.worlds))
    assert set(sub_512.worlds).issubset(set(sub_2048.worlds))

    # 同一种子两次结果完全相同
    sub_64_again = idx.subset_by_worlds(4, seed=seed)
    sub_512_again = idx.subset_by_worlds(32, seed=seed)
    assert sub_64.worlds == sub_64_again.worlds
    assert sub_64.items == sub_64_again.items
    assert sub_512.worlds == sub_512_again.worlds
    assert sub_512.items == sub_512_again.items


def test_item_cache_second_read_does_not_call_np_load_and_matches_uncached(fixture_partition, monkeypatch):
    idx = D.ClipIndex(fixture_partition / "part")
    teachers = fixture_partition / "teachers"

    # 先取不带缓存的参考结果
    uncached = D.load_item(idx, 0, teachers=teachers, cache=None)
    D._VERIFIED_TEACHER_SHAS.clear()

    load_calls = []
    real_np_load = D.np.load

    def counting_np_load(file, *args, **kwargs):
        load_calls.append(str(file))
        return real_np_load(file, *args, **kwargs)

    monkeypatch.setattr(D.np, "load", counting_np_load)

    cache = D.ItemCache()
    assert cache.max_bytes == D.DEFAULT_CACHE_MAX_BYTES == 48 * (1024 ** 3)

    # 第一次读取：读取 clip_00.npy、labels_00.npz、clip_00.vjepa.npy、da2_00.da2.npy 共 4 次 np.load
    first = D.load_item(idx, 0, teachers=teachers, cache=cache)
    assert len(load_calls) == 4
    assert cache.used_bytes > 0

    # 第二次读取同一段：不再触发任何 np.load 文件读取
    second = D.load_item(idx, 0, teachers=teachers, cache=cache)
    assert len(load_calls) == 4, f"Second load_item should not call np.load, got {len(load_calls)}"

    # load_teacher 再次读取同一段：也不触发任何 np.load
    t_second = D.load_teacher(idx, 0, teachers, cache=cache)
    assert len(load_calls) == 4, f"Second load_teacher should not call np.load, got {len(load_calls)}"

    # 缓存结果与不缓存结果逐元素严格一致
    for key in ("patches", "r1_logd", "r1_sky", "r1_obj", "r2", "r3", "vjepa", "da2"):
        np.testing.assert_array_equal(first[key], uncached[key], err_msg=f"first vs uncached: {key}")
        np.testing.assert_array_equal(second[key], uncached[key], err_msg=f"second vs uncached: {key}")
    np.testing.assert_array_equal(t_second["vjepa"], uncached["vjepa"])
    np.testing.assert_array_equal(t_second["da2"], uncached["da2"])
    assert second["disk_groups"] == uncached["disk_groups"]
    assert second["ordering_pairs"] == uncached["ordering_pairs"]


def test_teacher_sha_computed_at_most_once_per_file_in_process(fixture_partition, monkeypatch):
    idx = D.ClipIndex(fixture_partition / "part")
    teachers = fixture_partition / "teachers"

    sha_calls: dict[str, int] = {}
    real_sha = D._sha256_file

    def counting_sha(path: Path) -> str:
        key = str(Path(path).resolve())
        sha_calls[key] = sha_calls.get(key, 0) + 1
        return real_sha(path)

    monkeypatch.setattr(D, "_sha256_file", counting_sha)

    # 即使不缓存数组（cache=None 或 max_bytes=0）或跨多个 ItemCache，每个教师文件的 SHA 在进程内也只算一次
    cache1 = D.ItemCache(max_bytes=0)
    cache2 = D.ItemCache()
    for _ in range(3):
        D.load_teacher(idx, 0, teachers, cache=cache1)
        D.load_teacher(idx, 0, teachers, cache=cache2)
        D.load_item(idx, 0, teachers=teachers, cache=None)

    assert len(sha_calls) == 2  # clip_00.vjepa.npy 与 da2_00.da2.npy
    assert all(count == 1 for count in sha_calls.values()), f"Expected 1 SHA call per file, got {sha_calls}"


def test_item_cache_exceeding_max_bytes_reads_normally_without_error(fixture_partition):
    idx = D.ClipIndex(fixture_partition / "part")
    teachers = fixture_partition / "teachers"

    uncached_0 = D.load_item(idx, 0, teachers=teachers, cache=None)
    uncached_1 = D.load_item(idx, 1, teachers=teachers, cache=None)

    # 设定只能装下 1 个 uint8 clip（约 2.4MB）而装不下 V-JEPA 特征（约 3.2MB）或第 2 段的上限
    clip_bytes = 16 * 224 * 224 * 3  # 2,408,448 bytes
    small_cache = D.ItemCache(max_bytes=clip_bytes + 4096)

    got_0 = D.load_item(idx, 0, teachers=teachers, cache=small_cache)
    got_1 = D.load_item(idx, 1, teachers=teachers, cache=small_cache)
    got_0_again = D.load_item(idx, 0, teachers=teachers, cache=small_cache)

    assert small_cache.used_bytes <= small_cache.max_bytes
    for key in ("patches", "r1_logd", "r1_sky", "r1_obj", "r2", "r3", "vjepa", "da2"):
        np.testing.assert_array_equal(got_0[key], uncached_0[key])
        np.testing.assert_array_equal(got_1[key], uncached_1[key])
        np.testing.assert_array_equal(got_0_again[key], uncached_0[key])


def test_tampered_teacher_before_first_read_raises_with_cache(fixture_partition, tmp_path):
    import shutil
    bad_teachers = tmp_path / "bad_teachers_cached"
    shutil.copytree(fixture_partition / "teachers", bad_teachers)

    # 篡改第 0 段 V-JEPA 与第 1 段 DA2
    v_file = bad_teachers / "world_0000" / "clip_00.vjepa.npy"
    raw_v = bytearray(v_file.read_bytes())
    raw_v[-1] ^= 0xFF
    v_file.write_bytes(bytes(raw_v))

    d_file = bad_teachers / "world_0000" / "da2_01.da2.npy"
    raw_d = bytearray(d_file.read_bytes())
    raw_d[-1] ^= 0xFF
    d_file.write_bytes(bytes(raw_d))

    idx = D.ClipIndex(fixture_partition / "part")
    cache = D.ItemCache()
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        D.load_item(idx, 0, teachers=bad_teachers, cache=cache)
    with pytest.raises(RuntimeError, match="SHA mismatch"):
        D.load_teacher(idx, 1, bad_teachers, cache=cache)


def _run_mutated_data_check(tmp_path: Path, old: str, new: str, check_body: str) -> None:
    import subprocess
    import sys

    assert tmp_path.resolve() not in (LIVE_REPO, REAL_REPO)
    src_text = DATA_SRC.read_text(encoding="utf-8")
    assert src_text.count(old) == 1, f"Expected 1 occurrence of {old!r}"
    mut_file = tmp_path / "data_mut.py"
    mut_file.write_text(src_text.replace(old, new, 1), encoding="utf-8")

    script = tmp_path / "run_check.py"
    script.write_text(
        "import importlib.util, sys\n"
        "from pathlib import Path\n"
        f"sys.path.insert(0, {str(LIVE_REPO / 'src')!r})\n"
        "spec = importlib.util.spec_from_file_location('data_mut', Path('data_mut.py'))\n"
        "D = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(D)\n"
        + check_body,
        encoding="utf-8",
    )
    ran = subprocess.run([sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True)
    assert ran.returncode != 0, "Mutation should have been caught!\n" + ran.stdout + ran.stderr


def test_subset_nesting_mutation_is_rejected(tmp_path):
    # 坏对照：把 subset_by_worlds 的种子改为依赖 n (seed + n)，破坏嵌套关系
    _run_mutated_data_check(
        tmp_path,
        "rng = np.random.default_rng(seed)",
        "rng = np.random.default_rng(seed + n)",
        "mock = Path('mock')\n"
        "for w in range(128):\n"
        "    d = mock / f'world_{w:04d}'\n"
        "    d.mkdir(parents=True)\n"
        "    (d / 'clip_00.npy').write_bytes(b'x')\n"
        "idx = D.ClipIndex(mock)\n"
        "s4 = idx.subset_by_worlds(4, seed=20261112)\n"
        "s32 = idx.subset_by_worlds(32, seed=20261112)\n"
        "assert set(s4.worlds).issubset(set(s32.worlds))\n",
    )


def test_cache_disabled_mutation_is_rejected(fixture_partition, tmp_path):
    # 坏对照：把 ItemCache.get 改成恒返回 None，第二次读取仍触发 np.load
    _run_mutated_data_check(
        tmp_path,
        "        if key in self._items:\n            self.hits += 1\n            return self._items[key]",
        "        if False:\n            return None",
        f"idx = D.ClipIndex(Path({str(fixture_partition / 'part')!r}))\n"
        f"teachers = Path({str(fixture_partition / 'teachers')!r})\n"
        "calls = []\n"
        "real_load = D.np.load\n"
        "D.np.load = lambda f, *a, **kw: (calls.append(str(f)), real_load(f, *a, **kw))[1]\n"
        "cache = D.ItemCache()\n"
        "D.load_item(idx, 0, teachers=teachers, cache=cache)\n"
        "n1 = len(calls)\n"
        "D.load_item(idx, 0, teachers=teachers, cache=cache)\n"
        "assert len(calls) == n1\n",
    )


def test_teacher_sha_every_time_mutation_is_rejected(fixture_partition, tmp_path):
    # 坏对照：去掉 _VERIFIED_TEACHER_SHAS[key] = got_sha，导致每次都重算 SHA
    _run_mutated_data_check(
        tmp_path,
        "    _VERIFIED_TEACHER_SHAS[key] = got_sha",
        "    pass",
        f"idx = D.ClipIndex(Path({str(fixture_partition / 'part')!r}))\n"
        f"teachers = Path({str(fixture_partition / 'teachers')!r})\n"
        "calls = []\n"
        "real_sha = D._sha256_file\n"
        "D._sha256_file = lambda p: (calls.append(str(p)), real_sha(p))[1]\n"
        "D.load_teacher(idx, 0, teachers, cache=None)\n"
        "D.load_teacher(idx, 0, teachers, cache=None)\n"
        "assert len(calls) == 2\n",
    )


def test_teacher_sha_skip_verification_mutation_is_rejected(fixture_partition, tmp_path):
    # 坏对照：把 _verify_teacher_file_once 改成直接 return，篡改文件不再报错
    _run_mutated_data_check(
        tmp_path,
        "    if got_sha != expected_sha:\n        raise RuntimeError(",
        "    if False:\n        raise RuntimeError(",
        "import shutil\n"
        f"bad = Path('bad_t'); shutil.copytree(Path({str(fixture_partition / 'teachers')!r}), bad)\n"
        "vf = bad / 'world_0000' / 'clip_00.vjepa.npy'\n"
        "raw = bytearray(vf.read_bytes()); raw[-1] ^= 0xFF; vf.write_bytes(bytes(raw))\n"
        f"idx = D.ClipIndex(Path({str(fixture_partition / 'part')!r}))\n"
        "try:\n"
        "    D.load_item(idx, 0, teachers=bad, cache=D.ItemCache())\n"
        "except RuntimeError:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
    )


# ------------------------------------------------------------------------------------------------
# P241：RLT keep/run_len 随 ItemCache 缓存（键含 tau）
# ------------------------------------------------------------------------------------------------
def test_rlt_keep_cached_by_clip_and_tau(fixture_partition, monkeypatch):
    """同一段同一 tau 第二次读取不再重算 keep；tau 不同或段不同则重新计算。"""
    from ainerzero.v9.experiments.s5 import tokens as tok_mod

    idx = D.ClipIndex(fixture_partition / "part")
    cache = D.ItemCache()

    calls: list[float] = []
    real_fast = tok_mod.rlt_keep_fast

    def counting_rlt_keep_fast(patches, tau):
        calls.append(float(tau))
        return real_fast(patches, tau)

    monkeypatch.setattr(tok_mod, "rlt_keep_fast", counting_rlt_keep_fast)
    monkeypatch.setattr(D, "rlt_keep_fast", counting_rlt_keep_fast)

    # 1. 不传 tau 时不计算 keep
    item_no_tau = D.load_item(idx, 0, cache=cache)
    assert "keep" not in item_no_tau and "run_len" not in item_no_tau
    assert len(calls) == 0

    # 2. 首次读取段 0, tau=0.02 -> 计算 1 次
    item_0_a = D.load_item(idx, 0, tau=0.02, cache=cache)
    assert len(calls) == 1 and calls[-1] == 0.02
    k_ref_002, rl_ref_002 = tok_mod.rlt_keep(item_0_a["patches"], 0.02)
    np.testing.assert_array_equal(item_0_a["keep"], k_ref_002)
    np.testing.assert_array_equal(item_0_a["run_len"], rl_ref_002)

    # 3. 再次读取同一段 0, 同一 tau=0.02 -> 命中缓存，不再计算
    item_0_b = D.load_item(idx, 0, tau=0.02, cache=cache)
    assert len(calls) == 1, f"Same clip and same tau should not recompute keep, got {len(calls)} calls"
    np.testing.assert_array_equal(item_0_b["keep"], item_0_a["keep"])
    np.testing.assert_array_equal(item_0_b["run_len"], item_0_a["run_len"])

    # 4. 同一段 0, 不同 tau=0.1 -> 必须重新计算
    item_0_tau01 = D.load_item(idx, 0, tau=0.1, cache=cache)
    assert len(calls) == 2 and calls[-1] == 0.1
    k_ref_01, rl_ref_01 = tok_mod.rlt_keep(item_0_tau01["patches"], 0.1)
    np.testing.assert_array_equal(item_0_tau01["keep"], k_ref_01)
    np.testing.assert_array_equal(item_0_tau01["run_len"], rl_ref_01)
    assert not np.array_equal(item_0_tau01["keep"], item_0_a["keep"])

    # 5. 再次读取同一段 0, tau=0.1 或 tau=0.02 -> 两者都已在缓存中，不再计算
    D.load_item(idx, 0, tau=0.1, cache=cache)
    D.load_item(idx, 0, tau=0.02, cache=cache)
    assert len(calls) == 2

    # 6. 不同段 1, tau=0.02 -> 重新计算
    D.load_item(idx, 1, tau=0.02, cache=cache)
    assert len(calls) == 3 and calls[-1] == 0.02


