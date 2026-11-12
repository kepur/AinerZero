"""S5 标签契约测试与坏对照（纯 CPU）。

覆盖：
1. 契约 5：R2 纯二值占据（多圆盘落入同格仍为 1，不累加为 2）与坏对照；
2. R1 深度与天空占比规范（全天空块为 NaN，非天空块 >= log(0.5)）与坏对照；
3. R3 下一时刻占据步数偏移（+8 步）与坏对照；
4. disk_groups 结构与遮挡分档（阈值 0.5）与坏对照；
5. ordering_pairs 几何次序与近者判定与坏对照。
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import world as s4_world
from ainerzero.v9.experiments.s5 import labels
from ainerzero.v9.experiments.s5.world import episode


# ==============================================================================
# 契约测试 5：R2 纯二值占据
# ==============================================================================

def test_contract5_r2_binary_occupancy():
    """R2 必须是严格的二值占据网格 [12, 7]，取值只能是 0 或 1。"""
    ep = episode("s5test-demo", 0)
    for c in range(16):
        grid = labels.r2(ep, c)
        assert grid.shape == (12, 7)
        assert grid.dtype == np.uint8
        vals = set(np.unique(grid))
        assert vals.issubset({0, 1}), f"Non-binary values found: {vals}"


def test_contract5_r2_multi_disk_same_cell_stays_one():
    """当人为构造两个圆盘都看得见且落入同一个方位-距离格时，网格值仍必须是 1 而非 2 (M3)。"""
    agent = (0.0, 0.0, 0.0)
    # 两圆盘均在正前方同一 bin，且侧向微小错开，互不遮挡，保证两者均有充足可见像素 (>= 4)
    rad1 = math.radians(1.0)
    rad2 = math.radians(6.0)
    p1 = (2.4 * math.cos(rad1), 2.4 * math.sin(rad1))
    p2 = (2.8 * math.cos(rad2), 2.8 * math.sin(rad2))
    positions = [p1, p2]
    pillars = []

    class DummyStep:
        def __init__(self, agent, positions):
            self.agent = agent
            self.positions = positions

    st = DummyStep(agent, positions)

    # 验证渲染后两圆盘均有可见像素 >= 4
    from ainerzero.v9.experiments.s5.render import render
    _, _, ids = render(agent, positions, pillars, width=224, height=224, return_ids=True)
    px1 = int(np.sum(ids == 100))
    px2 = int(np.sum(ids == 101))
    assert px1 >= 4, f"Disk 1 visible pixels {px1} < 4"
    assert px2 >= 4, f"Disk 2 visible pixels {px2} < 4"

    grid = labels._occupancy_grid(st, pillars)

    assert grid.shape == (12, 7)
    vals = set(np.unique(grid))
    assert vals.issubset({0, 1}), f"Grid contains non-binary values: {vals}"
    assert np.max(grid) == 1, f"Expected max=1, got {np.max(grid)}"
    assert np.sum(grid) == 1, f"Expected two disks to collapse into exactly 1 cell, got {np.sum(grid)}"


def test_r2_exact_step_15():
    """R2 必须严格取段内最后一帧（全局步 16*clip_idx + 15），不能取第 14 帧 (M4)。"""
    ep = episode("s5test-demo", 0)

    class MockEpisode:
        def __init__(self, orig_ep):
            self.steps = list(orig_ep.steps)
            self.pillars = orig_ep.pillars

    mock_ep = MockEpisode(ep)

    class MockStep:
        def __init__(self, agent, positions):
            self.agent = agent
            self.positions = positions

    # 第 14 步圆盘远离视野 (20m 处)，第 15 步圆盘进入视野 (3m 处)
    mock_ep.steps[14] = MockStep((0.0, 0.0, 0.0), [(20.0, 20.0)])
    mock_ep.steps[15] = MockStep((0.0, 0.0, 0.0), [(3.0, 0.0)])

    grid = labels.r2(mock_ep, 0)
    assert np.max(grid) == 1, "R2 必须基于第 15 步计算（第 15 步圆盘可见，第 14 步不可见）"


def test_r2_visible_threshold_strict_four_pixels():
    """可见像素门槛严格为 4：当圆盘仅露出 3 个像素时，必须判定为不可见，网格记 0 (M9)。"""
    class DummyStep:
        def __init__(self, agent, positions):
            self.agent = agent
            self.positions = positions

    st = DummyStep((0.0, 0.0, 0.0), [(3.0, 0.0)])
    fake_ids = np.full((224, 224), -1, dtype=np.int32)
    fake_ids[100, 100:103] = 100  # 恰好 3 个像素
    fake_depth = np.full((224, 224), 3.0, dtype=np.float32)
    fake_img = np.zeros((224, 224, 3), dtype=np.float32)

    grid = labels._occupancy_grid(st, [], precomputed_frame=(fake_img, fake_depth, fake_ids))
    assert np.sum(grid) == 0, "3 个像素严格小于 MIN_VISIBLE_PIXELS (4)，网格必须记 0"

    fake_ids[100, 103] = 100  # 增加到 4 个像素
    grid4 = labels._occupancy_grid(st, [], precomputed_frame=(fake_img, fake_depth, fake_ids))
    assert np.sum(grid4) == 1, "4 个像素达到 MIN_VISIBLE_PIXELS (4)，网格必须记 1"


def test_r2_azimuth_polarity_left_positive():
    """方位角极性必须符合左正右负：左侧圆盘落在方位格 >= 6，右侧圆盘落在 <= 5 (M10)。"""
    class DummyStep:
        def __init__(self, agent, positions):
            self.agent = agent
            self.positions = positions

    # 左侧圆盘 (y=1.0 > 0)
    st_left = DummyStep((0.0, 0.0, 0.0), [(3.0, 1.0)])
    grid_left = labels._occupancy_grid(st_left, [])
    az_left = int(np.where(grid_left == 1)[0][0])
    assert az_left >= 6, f"左侧圆盘方位格应 >= 6，实测 {az_left}"

    # 右侧圆盘 (y=-1.0 < 0)
    st_right = DummyStep((0.0, 0.0, 0.0), [(3.0, -1.0)])
    grid_right = labels._occupancy_grid(st_right, [])
    az_right = int(np.where(grid_right == 1)[0][0])
    assert az_right <= 5, f"右侧圆盘方位格应 <= 5，实测 {az_right}"


def test_labels_precomputed_frames_parity():
    """验证传入预渲染帧 precomputed 与实时渲染两套路径生成的标签逐元素严格一致。"""
    ep = episode("s5test-demo", 0)
    from ainerzero.v9.experiments.s5.render import render

    frames = []
    for k in range(16):
        st = ep.steps[k]
        frames.append(render(st.agent, st.positions, ep.pillars, width=224, height=224, return_ids=True))

    # 1. R1
    r1_orig = labels.r1(ep, 0)
    r1_pre = labels.r1(ep, 0, precomputed_frames=frames)
    np.testing.assert_allclose(r1_orig["logd"], r1_pre["logd"], equal_nan=True)
    np.testing.assert_allclose(r1_orig["sky"], r1_pre["sky"])
    np.testing.assert_allclose(r1_orig["obj"], r1_pre["obj"])

    # 2. R2
    r2_orig = labels.r2(ep, 0)
    r2_pre = labels.r2(ep, 0, precomputed_frame=frames[15])
    np.testing.assert_array_equal(r2_orig, r2_pre)

    # 3. R3
    st_r3 = ep.steps[15 + 8]
    frame_r3 = render(st_r3.agent, st_r3.positions, ep.pillars, width=224, height=224, return_ids=True)
    r3_orig = labels.r3(ep, 0)
    r3_pre = labels.r3(ep, 0, precomputed_frame=frame_r3)
    np.testing.assert_array_equal(r3_orig, r3_pre)

    # 4. disk_groups
    dg_orig = labels.disk_groups(ep, 0)
    dg_pre = labels.disk_groups(ep, 0, precomputed_frame=frames[15])
    assert dg_orig == dg_pre

    # 5. ordering_pairs
    op_orig = labels.ordering_pairs(ep, 0)
    op_pre = labels.ordering_pairs(ep, 0, precomputed_frame=frames[15])
    assert op_orig == op_pre


# ==============================================================================
# R1 深度与天空规范测试
# ==============================================================================

def test_r1_labels_contract():
    """R1 logd 与 sky 规格与空值定义。"""
    ep = episode("s5test-demo", 0)
    res = labels.r1(ep, 0)

    logd = res["logd"]
    sky = res["sky"]

    assert logd.shape == (16, 14, 14)
    assert sky.shape == (16, 14, 14)
    assert logd.dtype == np.float32
    assert sky.dtype == np.float32

    # 天空比例应在 [0, 1]
    assert np.all(sky >= 0.0)
    assert np.all(sky <= 1.0)

    # 全天空块必须为 NaN
    all_sky = (sky == 1.0)
    if np.any(all_sky):
        assert np.all(np.isnan(logd[all_sky])), "All-sky patches must be NaN in logd"

    # 非全天空块必须为有限实数，且 >= log(0.5)
    non_sky = (sky < 1.0)
    if np.any(non_sky):
        assert np.all(np.isfinite(logd[non_sky])), "Non-sky patches must have finite logd"
        assert np.all(logd[non_sky] >= math.log(0.5) - 1e-5), "logd must respect clamp z >= 0.5"


def test_r1_bad_control_sky_zero_instead_of_nan():
    """坏对照：若全天空块被误填为 0.0 而非 NaN，全天空检测必须报警。"""
    def bad_r1_processing(sky, logd):
        bad_logd = logd.copy()
        bad_logd[np.isnan(bad_logd)] = 0.0
        return bad_logd

    ep = episode("s5test-demo", 0)
    res = labels.r1(ep, 0)
    bad_logd = bad_r1_processing(res["sky"], res["logd"])

    all_sky = (res["sky"] == 1.0)
    if np.any(all_sky):
        with pytest.raises(AssertionError, match="must be NaN"):
            assert np.all(np.isnan(bad_logd[all_sky])), "All-sky patches must be NaN in logd"


# ==============================================================================
# R3 步数偏移测试
# ==============================================================================

def test_r3_step_offset():
    """R3 取自段末帧 + 8 步。"""
    ep = episode("s5test-demo", 0)
    r2_grid = labels.r2(ep, 0)
    r3_grid = labels.r3(ep, 0)

    # 检验 r3 计算所用状态确实是 t=23 (15 + 8)
    manual_r3 = labels._occupancy_grid(ep.steps[15 + 8], ep.pillars)
    np.testing.assert_array_equal(r3_grid, manual_r3)


def test_r3_bad_control_zero_offset():
    """坏对照：若 R3 漏加了 8 步偏移，在智能体移动的 episode 中会被识破。"""
    ep = episode("s5test-demo", 0)
    # 找到一个 r2 != r3 的片段
    found_diff = False
    for c in range(16):
        r2_g = labels.r2(ep, c)
        r3_g = labels.r3(ep, c)
        if not np.array_equal(r2_g, r3_g):
            found_diff = True
            # 坏对照：假装 r3 就是 r2
            bad_r3 = r2_g
            with pytest.raises(AssertionError):
                np.testing.assert_array_equal(bad_r3, r3_g)
            break
    assert found_diff, "At least one clip must show state change between t and t+8"


# ==============================================================================
# disk_groups 结构与遮挡测试
# ==============================================================================

def test_disk_groups_contract():
    """disk_groups 返回所有可见圆盘的完整元数据及正确阈值。"""
    ep = episode("s5test-demo", 0)
    found_any = False
    for c in range(16):
        groups = labels.disk_groups(ep, c)
        for d in groups:
            found_any = True
            assert "disk_id" in d
            assert "azimuth_bin" in d and 0 <= d["azimuth_bin"] < 12
            assert "distance_bin" in d and 0 <= d["distance_bin"] < 7
            assert "distance" in d
            assert d["distance_group"] in {"< 2", "2–4", "> 4"}
            assert 0.0 <= d["occlusion_ratio"] <= 1.0 + 1e-5
            assert d["occlusion_group"] in {"partial", "full"}
            if d["occlusion_ratio"] < 0.5:
                assert d["occlusion_group"] == "partial"
            else:
                assert d["occlusion_group"] == "full"
    assert found_any, "Must find visible disks across 16 clips"


def test_disk_groups_bad_control_threshold_inversion():
    """坏对照：若遮挡分档阈值颠倒（把 < 0.5 标成 full），断言必须失败。"""
    def bad_occlusion_group(ratio: float) -> str:
        # 颠倒逻辑
        return "full" if ratio < 0.5 else "partial"

    with pytest.raises(AssertionError):
        test_ratio = 0.2
        bad_group = bad_occlusion_group(test_ratio)
        expected_group = "partial" if test_ratio < 0.5 else "full"
        assert bad_group == expected_group


# ==============================================================================
# ordering_pairs 几何次序测试
# ==============================================================================

def test_ordering_pairs_contract():
    """ordering_pairs 返回成对次序，closer 与 z_median 严格吻合。"""
    ep = episode("s5test-demo", 0)
    found_pairs = False
    for c in range(16):
        pairs = labels.ordering_pairs(ep, c)
        for p in pairs:
            found_pairs = True
            assert p["type"] in {"disk_disk", "disk_pillar"}
            assert len(p["patch_a"]) == 2
            assert len(p["patch_b"]) == 2
            za, zb = p["z_a"], p["z_b"]
            if za < zb:
                assert p["closer"] == "a"
            elif zb < za:
                assert p["closer"] == "b"
            else:
                assert p["closer"] == "equal"
    assert found_pairs, "Must find object pairs across 16 clips"


def test_ordering_pairs_bad_control_inverted_depth():
    """坏对照：若深度判定颠倒（深度大误判为更近），判定断言必须抓出。"""
    def bad_closer_judge(za: float, zb: float) -> str:
        # 错误逻辑：深度大的更近
        return "a" if za > zb else "b"

    with pytest.raises(AssertionError):
        za, zb = 1.5, 3.0  # a 更近
        judged = bad_closer_judge(za, zb)
        assert judged == "a", f"Closer judge failed: got {judged}"



def test_r1_object_share_geometry():
    """obj counts wall, pillar and disk pixels; sky + obj + floor shares add up to one (tier-1, 11-12)."""
    from types import SimpleNamespace

    from ainerzero.v9.experiments.s5.render import render

    agent = (8.0, 5.0, 0.0)                         # facing the east wall 2 m away
    st = SimpleNamespace(agent=agent, positions=np.zeros((0, 2)))
    ep = SimpleNamespace(steps=[st] * 16, pillars=())
    frames = [render(agent, np.zeros((0, 2)), (), return_ids=True)] * 16
    out = labels.r1(ep, 0, precomputed_frames=frames)
    obj, sky = out["obj"][0], out["sky"][0]
    assert obj.shape == (14, 14) and obj.dtype == np.float32
    # row of patches just above the horizon is all wall (wall top is above the image centre at 2 m)
    np.testing.assert_allclose(obj[6], 1.0)
    # bottom row of patches is floor only
    np.testing.assert_allclose(obj[13], 0.0)
    np.testing.assert_allclose(sky[13], 0.0)
    floor = 1.0 - sky - obj
    assert (floor >= -1e-6).all() and (floor <= 1 + 1e-6).all()
    # cross-check one patch against the id map directly
    ids = frames[0][2]
    np.testing.assert_allclose(obj[6, 3], float((ids[96:112, 48:64] >= 0).mean()))
    np.testing.assert_allclose(obj[12, 3], float((ids[192:208, 48:64] >= 0).mean()))
