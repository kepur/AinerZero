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
