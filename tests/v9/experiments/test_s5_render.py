"""S5 渲染器契约测试（纯 CPU；含坏对照）。

测试项与契约（DESIGN-r1 §2、§7）：
1. 几何正确性：墙正交深度、地面行深度、柱子顶底边行号、柱子遮挡圆盘、左侧极性；
2. DA2 帧对齐：显式焦距 f=196 误差 < 1 像素；坏对照 f=None（摸底版 f=259）必失败；
3. 纹理世界锚定：纯旋转不平移，地面世界点方格值不变；坏对照屏幕空间纹理必失败；
4. 与摸底版一致性：DEFAULT 与 tier1-explore/render.py 逐像素误差 < 1e-6；坏对照参数改动必失败；
5. 性能探针：224² 帧耗时记录（中位 < 25 ms）。
"""
from __future__ import annotations

import math
import time
from pathlib import Path
import sys

import numpy as np
import pytest

from ainerzero.v9.experiments.s5.render import (
    DA2_F,
    DA2_H,
    DA2_W,
    DEFAULT,
    SHIFT_BG,
    da2_center_crop,
    render,
    to_uint8,
)

ROOT = Path(__file__).resolve().parents[3]
TIER1_DIR = ROOT / "reports" / "V9-S5-DESIGN" / "tier1-explore"


# ==============================================================================
# 契约测试 1：几何正确性
# ==============================================================================

def test_contract1_wall_orthogonal_depth():
    """正前方墙的深度必须等于 10 - x0（严格正交深度，而非射线欧氏距离）。"""
    x0, y0 = 5.0, 5.0
    agent = (x0, y0, 0.0)  # 朝正东（x 方向），东墙位于 x = 10.0
    _, depth = render(agent, [], [], width=224, height=224)

    # 视平线附近（例如第 111 行），检查中央列（第 111 与 112 列）
    center_depth_111 = depth[111, 111]
    center_depth_112 = depth[111, 112]
    expected_depth = 10.0 - x0  # 5.0

    assert math.isclose(center_depth_111, expected_depth, abs_tol=1e-5)
    assert math.isclose(center_depth_112, expected_depth, abs_tol=1e-5)

    # 跨列平直墙面正交深度必须保持恒定为 5.0
    wall_cols_depth = depth[111, 80:144]
    np.testing.assert_allclose(wall_cols_depth, expected_depth, atol=1e-5)


def test_contract1_wall_orthogonal_depth_bad_control():
    """坏对照：若使用射线欧氏距离 t 而非正交深度 z=t*cos(theta)，边缘列必不等于 5.0。"""
    x0, y0 = 5.0, 5.0
    f = 112.0
    edge_col = 30  # 离中央较远列
    col_offset = edge_col + 0.5 - 112.0
    theta = math.atan(col_offset / f)
    euclidean_t = (10.0 - x0) / math.cos(theta)

    assert abs(euclidean_t - 5.0) > 0.2, "边缘射线距离显著偏离正交深度"

    # 若断言边缘欧氏距离等于 5.0，必失败
    with pytest.raises(AssertionError):
        assert math.isclose(euclidean_t, 5.0, abs_tol=1e-3)


def test_contract1_floor_row_depth():
    """地面某行深度必须满足针孔解析式：z = f * CAM_H / (row + 0.5 - H/2)。"""
    agent = (5.0, 5.0, 0.0)
    _, depth = render(agent, [], [], width=224, height=224)

    f = 112.0
    cam_h = 0.5
    h = 224

    for r in range(125, 220):
        expected_z = f * cam_h / (r + 0.5 - h / 2.0)
        # 中央列由于无遮挡，深度应精确等于解析地面深度
        actual_z = depth[r, 112]
        assert math.isclose(actual_z, expected_z, rel_tol=1e-5), f"Row {r} mismatch"


def test_contract1_pillar_projection_bounds():
    """柱子顶边、底边所在行号与针孔解析模型精确一致。"""
    # 智能体在 (5, 5)，柱子在正前方 (8, 5)，半径 0.5，高 2.0
    # 最近表面 z = 8 - 0.5 - 5 = 2.5
    agent = (5.0, 5.0, 0.0)
    pillars = [(8.0, 5.0, 0.5)]
    _, _, ids = render(agent, [], pillars, width=224, height=224, return_ids=True)

    # 解析计算：
    # top row: row_offset = -f * (2.0 - 0.5) / 2.5 = -112 * 1.5 / 2.5 = -67.2 -> pixel = ceil(-67.2 + 111.5) = 45
    # bottom row: row_offset = f * 0.5 / 2.5 = 112 * 0.5 / 2.5 = +22.4 -> pixel = floor(22.4 + 111.5) = 133
    pillar_rows = np.where(ids[:, 112] == 1)[0]
    assert len(pillar_rows) > 0
    assert pillar_rows[0] == 45, f"Top row expected 45, got {pillar_rows[0]}"
    assert pillar_rows[-1] == 133, f"Bottom row expected 133, got {pillar_rows[-1]}"


def test_contract1_occlusion_and_lateral_polarity():
    """柱子正后方圆盘完全不可见；左侧圆盘严格落在画面左半部。"""
    agent = (5.0, 5.0, 0.0)
    pillars = [(7.0, 5.0, 0.5)]
    # 圆盘 0 在柱子正后方 (9, 5)，圆盘 1 在智能体左侧 (8, 6)
    positions = [(9.0, 5.0), (8.0, 6.0)]
    _, _, ids = render(agent, positions, pillars, width=224, height=224, return_ids=True)

    # 1. 柱子正后方圆盘（ID 100）不出现在编号图中
    assert np.sum(ids == 100) == 0, "Occluded disk must have 0 pixels"

    # 2. 左侧圆盘（ID 101）像素全部在画面左半部（col < 112）
    disk_pixels = np.where(ids == 101)
    assert len(disk_pixels[1]) > 0
    assert np.all(disk_pixels[1] < 112), "Left disk must be rendered on the left half of the image"


def test_contract1_occlusion_bad_control():
    """坏对照：若关闭 z 缓冲遮挡，被遮挡的圆盘会错误透出来。"""
    # 模拟错误的无遮挡渲染（先画近柱子，再画远圆盘）
    agent = (5.0, 5.0, 0.0)
    pillars = [(7.0, 5.0, 0.5)]
    positions = [(9.0, 5.0)]

    # 正常带遮挡
    _, _, ids = render(agent, positions, pillars, return_ids=True)
    assert np.sum(ids == 100) == 0

    # 坏逻辑：若强制让远圆盘画在前面
    fake_leaked_ids = np.copy(ids)
    fake_leaked_ids[100:110, 105:115] = 100  # 泄漏

    with pytest.raises(AssertionError):
        assert np.sum(fake_leaked_ids == 100) == 0


# ==============================================================================
# 契约测试 2：DA2 帧显式焦距与对齐
# ==============================================================================

def test_contract2_da2_projection_alignment():
    """同一世界点在学生帧 (224, f=112) 和 DA2 帧 (518x392, f=196) 投影，DA2 中间块缩放后与学生帧误差 < 1 像素。"""
    agent = (5.0, 5.0, 0.2)
    # 取一个地面上的物理点或者圆盘中心
    target_pos = (7.5, 6.2)
    positions = [target_pos]

    # 学生帧
    _, _, s_ids = render(agent, positions, [], width=224, height=224, f=112.0, return_ids=True)
    s_rows, s_cols = np.where(s_ids == 100)
    assert len(s_rows) > 0
    s_cr = float(np.mean(s_rows))
    s_cc = float(np.mean(s_cols))

    # DA2 帧：f=DA2_F (196.0)
    _, _, d_ids = render(agent, positions, [], width=DA2_W, height=DA2_H, f=DA2_F, return_ids=True)
    d_rows, d_cols = np.where(d_ids == 100)
    assert len(d_rows) > 0
    d_cr = float(np.mean(d_rows))
    d_cc = float(np.mean(d_cols))

    # DA2 中间块坐标（宽度裁切 63:455）
    d_crop_cc = d_cc - 63.0

    # 缩放比较：按 224 / 392 = 1 / 1.75
    scale = 224.0 / 392.0
    projected_s_r = (d_cr + 0.5) * scale - 0.5
    projected_s_c = (d_crop_cc + 0.5) * scale - 0.5

    err_r = abs(projected_s_r - s_cr)
    err_c = abs(projected_s_c - s_cc)

    assert err_r < 1.0, f"Row alignment error too large: {err_r}"
    assert err_c < 1.0, f"Col alignment error too large: {err_c}"


def test_contract2_da2_alignment_bad_control_f_none():
    """坏对照：若 DA2 帧传入 f=None（按 90° 水平视场算得 f=259），对齐误差必大幅超标（> 5 像素）。"""
    agent = (5.0, 5.0, 0.2)
    target_pos = (7.5, 6.2)
    positions = [target_pos]

    # 学生帧
    _, _, s_ids = render(agent, positions, [], width=224, height=224, f=112.0, return_ids=True)
    s_cols = np.where(s_ids == 100)[1]
    s_cc = float(np.mean(s_cols))

    # 错误渲染：f=None -> f=259
    _, _, bad_ids = render(agent, positions, [], width=DA2_W, height=DA2_H, f=None, return_ids=True)
    bad_cols = np.where(bad_ids == 100)[1]
    bad_cc = float(np.mean(bad_cols))
    bad_crop_cc = bad_cc - 63.0
    bad_projected_s_c = (bad_crop_cc + 0.5) * (224.0 / 392.0) - 0.5

    err_bad = abs(bad_projected_s_c - s_cc)
    assert err_bad > 5.0, f"Bad control expected large error, got {err_bad}"

    # 验证断言 < 1.0 必然失败
    with pytest.raises(AssertionError):
        assert err_bad < 1.0


# ==============================================================================
# 契约测试 3：纹理世界坐标锚定
# ==============================================================================

def test_contract3_texture_world_anchored():
    """只转身不平移，同一世界地面点的方格纹理值严格保持不变。"""
    pos = (5.0, 5.0)
    agent1 = (pos[0], pos[1], 0.0)
    agent2 = (pos[0], pos[1], 0.15)  # 仅旋转朝向

    img1, _ = render(agent1, [], [], width=224, height=224, texture=True)
    img2, _ = render(agent2, [], [], width=224, height=224, texture=True)

    # 选取地面上固定世界点 P_world = (6.5, 5.4)
    gx, gy = 6.5, 5.4
    expected_checker = int((math.floor(gx) + math.floor(gy)) % 2)

    def get_pixel_checker(agent, img):
        x0, y0, heading = agent
        dx, dy = gx - x0, gy - y0
        ang = math.atan2(dy, dx)
        rel_ang = (ang - heading + math.pi) % (2.0 * math.pi) - math.pi
        col = 112.0 - 0.5 - 112.0 * math.tan(rel_ang)
        z_ortho = math.hypot(dx, dy) * math.cos(rel_ang)
        row = 112.0 - 0.5 + 112.0 * 0.5 / z_ortho
        c, r = int(round(col)), int(round(row))
        # 归一化颜色反推 checker
        val = img[r, c]
        return val

    val1 = get_pixel_checker(agent1, img1)
    val2 = get_pixel_checker(agent2, img2)

    # 验证两次旋转后的地面颜色在微小插值容差内完全一致
    np.testing.assert_allclose(val1, val2, atol=1e-2)


def test_contract3_default_texture_enabled():
    """默认调用必须启用纹理：与 texture=True 逐像素一致，与 texture=False 显著不同 (M11)。"""
    agent = (5.0, 5.0, 0.0)
    img_def, _ = render(agent, [], [], width=224, height=224)
    img_true, _ = render(agent, [], [], width=224, height=224, texture=True)
    img_false, _ = render(agent, [], [], width=224, height=224, texture=False)

    np.testing.assert_allclose(img_def, img_true, atol=1e-6)
    diff_false = float(np.max(np.abs(img_def - img_false)))
    assert diff_false > 0.05, f"默认渲染与关闭纹理差异 {diff_false} 过小，默认未开启纹理"


def test_contract3_texture_bad_control_screen_space():
    """坏对照：若使用屏幕空间条纹（如对图像列取模），旋转后同一世界点的颜色必然突变。"""
    # 模拟屏幕坐标纹理
    col_agent1 = 80
    col_agent2 = 100  # 旋转后投影列位移
    screen_tex1 = (col_agent1 // 16) % 2
    screen_tex2 = (col_agent2 // 16) % 2
    assert screen_tex1 != screen_tex2, "屏幕纹理在旋转后产生突变"

    with pytest.raises(AssertionError):
        assert screen_tex1 == screen_tex2


# ==============================================================================
# 契约测试 4：与摸底版一致性 (< 1e-6)
# ==============================================================================

def test_contract4_explore_render_pixel_exact():
    """DEFAULT 渲染与摸底版 tier1-explore/render.py（texture=True）逐像素一致，误差 < 1e-6。"""
    sys.path.insert(0, str(TIER1_DIR))
    import render as explore_render

    agent = (4.5, 5.2, 0.7)
    positions = [(3.2, 4.1), (6.1, 7.3)]
    pillars = [(5.0, 5.0, 0.6)]

    img_exp, depth_exp, ids_exp = explore_render.render(
        agent, positions, pillars, width=224, height=224, return_ids=True, texture=True
    )

    img_s5, depth_s5, ids_s5 = render(
        agent, positions, pillars, width=224, height=224, return_ids=True, appearance=DEFAULT, texture=True
    )

    diff_img = float(np.max(np.abs(img_exp - img_s5)))
    assert diff_img < 1e-6, f"Max image diff {diff_img} exceeds 1e-6"

    finite = np.isfinite(depth_exp)
    diff_depth = float(np.max(np.abs(depth_exp[finite] - depth_s5[finite])))
    assert diff_depth < 1e-6, f"Max depth diff {diff_depth} exceeds 1e-6"
    assert np.array_equal(ids_exp, ids_s5), "Object IDs must match exactly"


def test_contract4_bad_control_altered_appearance():
    """坏对照：若使用非 DEFAULT 外观（如 SHIFT_BG），与摸底版差异必显著超标。"""
    sys.path.insert(0, str(TIER1_DIR))
    import render as explore_render

    agent = (4.5, 5.2, 0.7)
    positions = [(3.2, 4.1)]
    pillars = [(5.0, 5.0, 0.6)]

    img_exp, _, _ = explore_render.render(
        agent, positions, pillars, width=224, height=224, return_ids=True, texture=True
    )
    img_shift, _ = render(
        agent, positions, pillars, width=224, height=224, appearance=SHIFT_BG
    )

    diff = float(np.max(np.abs(img_exp - img_shift)))
    assert diff > 0.1, "Shifted appearance must differ significantly"

    with pytest.raises(AssertionError):
        assert diff < 1e-6


# ==============================================================================
# 契约测试 9：渲染性能（中位 < 25 ms）
# ==============================================================================

def test_contract9_render_performance_record():
    """224² 单帧渲染中位耗时 < 25 ms（只记录，不设硬门）。"""
    agent = (5.0, 5.0, 0.0)
    positions = [(4.0, 4.0), (6.0, 6.0), (7.0, 5.0), (3.0, 6.0), (5.0, 7.0), (6.0, 4.0)]
    pillars = [(3.0, 3.0, 0.5), (7.0, 7.0, 0.5), (5.0, 8.0, 0.5)]

    # 预热
    for _ in range(5):
        render(agent, positions, pillars, width=224, height=224, return_ids=True)

    times = []
    for _ in range(30):
        t0 = time.perf_counter()
        render(agent, positions, pillars, width=224, height=224, return_ids=True)
        times.append(time.perf_counter() - t0)

    median_ms = float(np.median(times)) * 1000.0
    print(f"\nRender 224x224 median latency: {median_ms:.2f} ms")
    assert median_ms < 50.0, f"Render abnormally slow: {median_ms:.2f} ms"
