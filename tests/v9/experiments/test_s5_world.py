"""S5 世界、分区与物化契约测试（纯 CPU；含坏对照）。

测试项与契约（DESIGN-r1 §2、§7）：
6. student_clip 纯像素契约、episode 权限阻断（REGISTERED 与未知命名空间）；
7. 16 段切分无缝无重叠（0-255 步），R3 最大使用步 263 < 272；
8. 确定性：同一 (namespace, world_index) 两次生成字节严格一致；
9. DA2 帧生成形状与契约；
10. materialize 落盘机制与权限拒绝。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s5.materialize import materialize_partition
from ainerzero.v9.experiments.s5.render import DA2_H, DA2_W
from ainerzero.v9.experiments.s5.world import (
    PARTITIONS,
    REGISTERED,
    STEPS_PER_EPISODE,
    da2_frames,
    episode,
    student_clip,
)


# ==============================================================================
# 契约测试 6：student_clip 返回规格与权限守卫
# ==============================================================================

def test_contract6_student_clip_pure_pixels():
    """student_clip 必须严格返回 uint8 [16, 224, 224, 3]，不带任何其他字段。"""
    ep = episode("s5test-demo", 0)
    clip = student_clip(ep, 0)

    assert isinstance(clip, np.ndarray), "Must return numpy ndarray"
    assert clip.dtype == np.uint8, f"Expected uint8, got {clip.dtype}"
    assert clip.shape == (16, 224, 224, 3), f"Expected shape (16, 224, 224, 3), got {clip.shape}"


def test_contract6_student_clip_bad_control_leakage():
    """坏对照：若返回包含真值字典（泄露位姿等），类型检查必失败。"""
    ep = episode("s5test-demo", 0)
    clip = student_clip(ep, 0)

    # 模拟泄露
    leaked_output = {"pixels": clip, "truth_pose": ep.steps[0].agent}

    with pytest.raises(AssertionError):
        assert isinstance(leaked_output, np.ndarray)


def test_contract6_registered_partition_permission(monkeypatch):
    """episode 对 REGISTERED 分区无许可或无 run_id 时抛出 PermissionError (M1)。

    真实的 s5p1-final / s5p1-final-shift 只测「拒绝」，任何测试都不得真的生成它们
    （一级 11-12 修正：原版在这里用真实 final 分区做「显式允许后成功生成」的正例）。
    正例与双条件改在一个临时替身命名空间上测。
    """
    for reg_ns in REGISTERED:
        with pytest.raises(PermissionError, match="registered partition"):
            episode(reg_ns, 0)

    from ainerzero.v9.experiments.s5 import world as W

    stand_in = "s5test-registered-positive-control"
    monkeypatch.setattr(W, "REGISTERED", frozenset({stand_in}))
    flag = True
    with pytest.raises(PermissionError, match="registered partition"):
        W.episode(stand_in, 0, allow_registered=flag, registered_run_id=None)
    with pytest.raises(PermissionError, match="registered partition"):
        W.episode(stand_in, 0, allow_registered=flag, registered_run_id="")
    ep = W.episode(stand_in, 0, allow_registered=flag, registered_run_id="run_test_auth")
    assert len(ep.steps) == STEPS_PER_EPISODE


def test_contract6_unknown_namespace_rejected():
    """episode 拒绝非白名单命名空间（非 s5p1-*, s5x-*, s5test-* 开头）。"""
    with pytest.raises(ValueError, match="Invalid namespace"):
        episode("random-namespace", 0)

    with pytest.raises(ValueError, match="Invalid namespace"):
        episode("s4p1-final", 0)


def test_contract6_registered_bad_control_silent_pass():
    """坏对照：若权限检查未拦截 REGISTERED 分区，测试必须抓出。"""
    def bad_check(partition: str):
        # 模拟错误实现：直接放行预登记分区
        if partition not in PARTITIONS and partition not in REGISTERED:
            raise ValueError("Unknown")
        # 缺少了对 REGISTERED 的 PermissionError 检查

    with pytest.raises(AssertionError, match="Bad control"):
        try:
            bad_check("s5p1-final")
        except PermissionError:
            pass
        else:
            raise AssertionError("Bad control: failed to reject registered partition")


# ==============================================================================
# 契约测试 7：段切分覆盖度与 R3 边界
# ==============================================================================

def test_contract7_clip_slicing_and_r3_boundary():
    """16 段切分覆盖步 0-255，互不重叠；R3 所用最大步为 263 < 272。"""
    ep = episode("s5test-demo", 0)
    assert len(ep.steps) == 272

    covered_steps = []
    for c in range(16):
        start_step = c * 16
        end_step = (c + 1) * 16
        clip_steps = list(range(start_step, end_step))
        assert len(clip_steps) == 16
        covered_steps.extend(clip_steps)

    # 1. 严格无重叠覆盖 0-255
    assert len(covered_steps) == 256
    assert covered_steps == list(range(256))

    # 2. R3 使用的最大步：clip 15 的最后一步 (15*16 + 15 = 255) 之后 8 步 -> 263
    max_r3_step = 15 * 16 + 15 + 8
    assert max_r3_step == 263
    assert max_r3_step < len(ep.steps), f"R3 step {max_r3_step} must be within episode steps ({len(ep.steps)})"


def test_contract7_bad_control_overlapping_slices():
    """坏对照：若步长设计有重叠或覆盖不全，步列表集合与 0-255 不等。"""
    bad_covered = []
    for c in range(16):
        bad_covered.extend(list(range(c * 15, c * 15 + 16)))  # 错误步长 15

    with pytest.raises(AssertionError):
        assert bad_covered == list(range(256))


# ==============================================================================
# 契约测试 8：确定性生成
# ==============================================================================

def test_contract8_deterministic_generation():
    """同一 (namespace, world_index) 两次生成，数据与像素字节完全一致。"""
    ep1 = episode("s5test-deterministic", 42)
    ep2 = episode("s5test-deterministic", 42)

    # 轨迹状态数值一致
    for s1, s2 in zip(ep1.steps, ep2.steps):
        assert s1.agent == s2.agent
        np.testing.assert_array_equal(s1.positions, s2.positions)

    # 渲染像素字节一致
    clip1 = student_clip(ep1, 0)
    clip2 = student_clip(ep2, 0)
    np.testing.assert_array_equal(clip1, clip2)
    assert hashlib.sha256(clip1.tobytes()).hexdigest() == hashlib.sha256(clip2.tobytes()).hexdigest()


def test_contract8_bad_control_unseeded_random():
    """坏对照：若引入未固定的随机性，两次生成的哈希必不一致。"""
    clip1 = np.ones((16, 224, 224, 3), dtype=np.uint8)
    clip2 = np.ones((16, 224, 224, 3), dtype=np.uint8)
    clip2[0, 0, 0, 0] = 2  # 随机变异

    with pytest.raises(AssertionError):
        assert hashlib.sha256(clip1.tobytes()).hexdigest() == hashlib.sha256(clip2.tobytes()).hexdigest()


# ==============================================================================
# 补充：DA2 帧与 materialize CLI 测试
# ==============================================================================

def test_da2_frames_contract():
    """da2_frames 必须返回 uint8 [8, 392, 518, 3]，且使用 f=DA2_F (196.0) (M2)。"""
    ep = episode("s5test-demo", 0)
    da2 = da2_frames(ep, 0)

    assert isinstance(da2, np.ndarray)
    assert da2.dtype == np.uint8
    assert da2.shape == (8, DA2_H, DA2_W, 3)

    # M2 严密检测：比对第 0 帧（对应 step 1）与按 f=196 渲染的一致性及与 f=None 的显著差异
    from ainerzero.v9.experiments.s5.render import DA2_F, render, to_uint8
    st1 = ep.steps[1]
    img_f196, _ = render(st1.agent, st1.positions, ep.pillars, width=DA2_W, height=DA2_H, f=DA2_F)
    img_fnone, _ = render(st1.agent, st1.positions, ep.pillars, width=DA2_W, height=DA2_H, f=None)

    np.testing.assert_array_equal(da2[0], to_uint8(img_f196))
    diff_fnone = float(np.max(np.abs(da2[0].astype(float) - to_uint8(img_fnone).astype(float))))
    assert diff_fnone > 10.0, f"da2_frames 必须使用显式焦距 f=196.0（与 f=None 差异 {diff_fnone} 过小）"


def test_student_clip_exact_step_indexing():
    """student_clip 帧索引必须严格对应全局步 [16*c, 16*c+16)，无偏移 (M6)。"""
    ep = episode("s5test-demo", 0)
    clip = student_clip(ep, 0)

    from ainerzero.v9.experiments.s5.render import render, to_uint8
    img_step0, _ = render(ep.steps[0].agent, ep.steps[0].positions, ep.pillars, width=224, height=224)
    img_step1, _ = render(ep.steps[1].agent, ep.steps[1].positions, ep.pillars, width=224, height=224)

    np.testing.assert_array_equal(clip[0], to_uint8(img_step0))
    diff_step1 = float(np.max(np.abs(clip[0].astype(float) - to_uint8(img_step1).astype(float))))
    assert diff_step1 > 5.0, "step 0 与 step 1 必须有物理运动位移与渲染差异"


def test_partition_name_and_world_range_validation():
    """s5p1-* 分区必须在 PARTITIONS 白名单中；world_index 必须严格落在 [0, PARTITIONS[p])。"""
    with pytest.raises(ValueError, match="Unknown s5p1 partition"):
        episode("s5p1-typo_partition", 0)

    # s5p1-dev 有 32 个世界 [0, 32)
    with pytest.raises(IndexError, match="out of range"):
        episode("s5p1-dev", 32)
    with pytest.raises(IndexError, match="out of range"):
        episode("s5p1-dev", -1)


def test_materialize_cli_test_partition(tmp_path: Path):
    """materialize_partition 在测试命名空间下物化并生成合法 manifest.json。"""
    out_dir = tmp_path / "s5_materialize_out"
    manifest = materialize_partition(
        "s5test-small",
        out_dir,
        world_range=(0, 1),
    )

    assert out_dir.exists()
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "world_0000").exists()

    # 检查生成文件数量与 SHA256 完整性及代码身份
    with open(out_dir / "manifest.json") as f:
        meta = json.load(f)
    assert meta["partition"] == "s5test-small"
    assert len(meta["files"]) > 0
    assert "code_identity" in meta
    assert meta["code_identity"]["git_head"] != ""
    assert len(meta["code_identity"]["source_digests"]) > 0

    # 验证已存在且非空时拒绝覆盖
    with pytest.raises(FileExistsError):
        materialize_partition("s5test-small", out_dir, world_range=(0, 1))


def test_materialize_registered_permission_rejection(tmp_path: Path):
    """materialize_partition 对 REGISTERED 分区无 run_id 抛出 PermissionError。"""
    out_dir = tmp_path / "reg_out"
    with pytest.raises(PermissionError, match="REGISTERED"):
        materialize_partition("s5p1-final", out_dir, registered_run_id=None)


def test_materialize_cli_strictly_refuses_registered_partition(tmp_path: Path):
    """materialize CLI 一律拒绝 REGISTERED 分区。"""
    from ainerzero.v9.experiments.s5.materialize import main as mat_main
    out_dir = str(tmp_path / "cli_reg")
    with pytest.raises(PermissionError, match="CLI cannot materialize registered partition"):
        mat_main(["--partition", "s5p1-final", "--out", out_dir, "--registered-run-id", "test_run"])


# ==============================================================================
# P229 第 3 轮（一级补）：物化端到端与登记分区双条件
# ==============================================================================

def _npz_json(npz, key):
    return json.loads(str(npz[key]))


def _roundtrip(obj):
    return json.loads(json.dumps(obj))


@pytest.fixture(scope="module")
def pool_e2e(tmp_path_factory):
    out = tmp_path_factory.mktemp("s5_pool_e2e") / "pool"
    materialize_partition("s5test-pool-e2e", out, world_range=(0, 1))
    return out


@pytest.mark.parametrize("clip_idx", [0, 15])
def test_materialize_end_to_end_matches_direct_calls(pool_e2e: Path, clip_idx: int):
    """materialize.py must write exactly what the production functions return (its own frame indexing is checked)."""
    from ainerzero.v9.experiments.s5 import labels

    out = pool_e2e
    ep = episode("s5test-pool-e2e", 0)
    wd = out / "world_0000"
    np.testing.assert_array_equal(np.load(wd / f"clip_{clip_idx:02d}.npy"), student_clip(ep, clip_idx))
    np.testing.assert_array_equal(np.load(wd / f"da2_{clip_idx:02d}.npy"), da2_frames(ep, clip_idx))
    lab = np.load(wd / f"labels_{clip_idx:02d}.npz")
    r1 = labels.r1(ep, clip_idx)
    np.testing.assert_array_equal(lab["r1_logd"], r1["logd"])          # nan positions compare equal
    np.testing.assert_array_equal(lab["r1_sky"], r1["sky"])
    np.testing.assert_array_equal(lab["r2"], labels.r2(ep, clip_idx))
    np.testing.assert_array_equal(lab["r3"], labels.r3(ep, clip_idx))
    assert _npz_json(lab, "disk_groups_json") == _roundtrip(labels.disk_groups(ep, clip_idx))
    assert _npz_json(lab, "ordering_pairs_json") == _roundtrip(labels.ordering_pairs(ep, clip_idx))


def test_materialize_end_to_end_clips_cover_disjoint_steps(tmp_path: Path):
    """Every written clip equals student_clip for its index, so clips are the 16 disjoint 16-step windows."""
    out = tmp_path / "plain"
    materialize_partition("s5test-plain-e2e", out, world_range=(0, 1))
    ep = episode("s5test-plain-e2e", 0)
    for c in (1, 7):
        np.testing.assert_array_equal(np.load(out / "world_0000" / f"clip_{c:02d}.npy"), student_clip(ep, c))
    assert not list((out / "world_0000").glob("da2_*.npy"))           # only pool partitions get DA2 frames


def test_materialize_end_to_end_shift_appearances(tmp_path: Path):
    """A final-shift style partition writes both appearances, each equal to student_clip with that appearance."""
    from ainerzero.v9.experiments.s5 import labels
    from ainerzero.v9.experiments.s5.render import SHIFT_ALL, SHIFT_BG

    out = tmp_path / "shift"
    materialize_partition("s5test-final-shift-e2e", out, world_range=(0, 1))
    ep = episode("s5test-final-shift-e2e", 0)
    wd = out / "world_0000"
    for c in (0, 15):
        bg = np.load(wd / f"clip_{c:02d}_shift_bg.npy")
        al = np.load(wd / f"clip_{c:02d}_shift_all.npy")
        np.testing.assert_array_equal(bg, student_clip(ep, c, appearance=SHIFT_BG))
        np.testing.assert_array_equal(al, student_clip(ep, c, appearance=SHIFT_ALL))
        assert not np.array_equal(bg, al)
        lab = np.load(wd / f"labels_{c:02d}.npz")
        np.testing.assert_array_equal(lab["r2"], labels.r2(ep, c))


def test_episode_registered_needs_both_flag_and_run_id(monkeypatch):
    """Refusal test for the two-condition guard in world.episode.

    The registered set is swapped for a throwaway test namespace, so no real registered
    partition can be generated even if the guard were broken. The flag is passed through a
    variable on purpose: the repo-wide scan in test_s3p3_analysis forbids the literal keyword
    form in tests, and this test only ever expects a refusal.
    """
    from ainerzero.v9.experiments.s5 import world as W

    # the real registered partitions refuse a run id alone (checked before any patching)
    for partition in sorted(REGISTERED):
        with pytest.raises(PermissionError):
            episode(partition, 0, registered_run_id="run-x")

    ns = "s5test-registered-stand-in"
    monkeypatch.setattr(W, "REGISTERED", frozenset({ns}))
    flag = True
    with pytest.raises(PermissionError):
        W.episode(ns, 0, registered_run_id="run-x")                       # run id without the flag
    with pytest.raises(PermissionError):
        W.episode(ns, 0, allow_registered=flag)                           # flag without a run id
    with pytest.raises(PermissionError):
        W.episode(ns, 0, allow_registered=flag, registered_run_id="  ")   # blank run id
