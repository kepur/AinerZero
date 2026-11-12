"""S5 读出头与评测标签生成模块（纯 CPU）。

所有标签只给读出头训练和评测使用，绝不进入学生端输入。
- R1 深度：非天空块对数深度 log(max(z, 0.5)) 与天空占比；
- R2 圆盘占据图：段末帧自我中心极坐标网格 [12 方位, 7 距离] 0/1 占据；
- R3 下一时刻占据图：段末帧 8 步后的网格占据；
- disk_groups：圆盘遮挡比与距离分档；
- ordering_pairs：圆盘-圆盘与圆盘-柱子两两前后次序真值。
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from ainerzero.v9.experiments.s4 import world as s4_world
from ainerzero.v9.experiments.s5.render import render

PATCH_SIZE: int = 16
GRID_H: int = 14
GRID_W: int = 14

MIN_VISIBLE_PIXELS: int = 4
FOV_HALF: float = math.pi / 4.0      # 45°
AZIMUTH_BINS: int = 12
DISTANCE_BINS: int = 7
DIST_MIN: float = 0.5
DIST_MAX: float = 7.0

LOG_D_MIN: float = math.log(DIST_MIN)
LOG_D_MAX: float = math.log(DIST_MAX)


def _compute_azimuth_bin(rel_angle: float) -> int:
    """计算方位格 [0, 12)。方位范围 [-45°, 45°]，正方位是画面左侧。"""
    bin_w = (2.0 * FOV_HALF) / AZIMUTH_BINS
    raw_bin = int(math.floor((rel_angle - (-FOV_HALF)) / bin_w))
    return int(np.clip(raw_bin, 0, AZIMUTH_BINS - 1))


def _compute_distance_bin(dist: float) -> int | None:
    """计算距离格 [0, 7)。距离 < 0.5 归第 0 格，> 7.0 的返回 None（不计）。"""
    if dist > DIST_MAX:
        return None
    if dist <= DIST_MIN:
        return 0
    raw_bin = int(math.floor(DISTANCE_BINS * (math.log(dist) - LOG_D_MIN) / (LOG_D_MAX - LOG_D_MIN)))
    return int(np.clip(raw_bin, 0, DISTANCE_BINS - 1))


def r1(
    ep: s4_world.Episode,
    clip_idx: int,
    *,
    precomputed_frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None,
) -> dict[str, np.ndarray]:
    """生成 R1 深度标签：logd [16, 14, 14] float32 与 sky [16, 14, 14] float32。

    - logd：每个 16×16 块里非天空像素的平均 log(max(z, 0.5))；全天空记 nan。
    - sky：每个 16×16 块里天空像素占比。
    - 若传入 precomputed_frames（16 帧渲染元组列表），直接复用避免重渲。
    """
    if not (0 <= clip_idx < 16):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, 16)")

    base_t = clip_idx * 16
    logd_arr = np.full((16, GRID_H, GRID_W), np.nan, dtype=np.float32)
    sky_arr = np.zeros((16, GRID_H, GRID_W), dtype=np.float32)

    for k in range(16):
        if precomputed_frames is not None:
            _, depth, ids = precomputed_frames[k]
        else:
            st = ep.steps[base_t + k]
            _, depth, ids = render(
                st.agent, st.positions, ep.pillars, width=224, height=224, return_ids=True
            )

        for r in range(GRID_H):
            r_start, r_end = r * PATCH_SIZE, (r + 1) * PATCH_SIZE
            for c in range(GRID_W):
                c_start, c_end = c * PATCH_SIZE, (c + 1) * PATCH_SIZE
                p_depth = depth[r_start:r_end, c_start:c_end]
                p_ids = ids[r_start:r_end, c_start:c_end]

                sky_mask = (p_ids == -2) | (~np.isfinite(p_depth))
                sky_count = int(np.sum(sky_mask))
                sky_arr[k, r, c] = sky_count / (PATCH_SIZE * PATCH_SIZE)

                non_sky_mask = ~sky_mask
                if np.any(non_sky_mask):
                    valid_z = np.maximum(p_depth[non_sky_mask], 0.5)
                    logd_arr[k, r, c] = float(np.mean(np.log(valid_z)))

    return {"logd": logd_arr, "sky": sky_arr}


def _occupancy_grid(
    st: Any,
    pillars: Any,
    *,
    precomputed_frame: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """在给定步骤计算圆盘占据网格 [12, 7] uint8。若传入 precomputed_frame 则直接复用。"""
    if precomputed_frame is not None:
        _, depth, ids = precomputed_frame
    else:
        _, depth, ids = render(
            st.agent, st.positions, pillars, width=224, height=224, return_ids=True
        )
    x0, y0, heading = float(st.agent[0]), float(st.agent[1]), float(st.agent[2])
    grid = np.zeros((AZIMUTH_BINS, DISTANCE_BINS), dtype=np.uint8)

    for i, p in enumerate(st.positions):
        disk_oid = 100 + i
        visible_px = int(np.sum(ids == disk_oid))
        if visible_px < MIN_VISIBLE_PIXELS:
            continue

        px, py = float(p[0]), float(p[1])
        dist = math.hypot(px - x0, py - y0)
        d_bin = _compute_distance_bin(dist)
        if d_bin is None:
            continue

        ang = math.atan2(py - y0, px - x0)
        rel_ang = (ang - heading + math.pi) % (2.0 * math.pi) - math.pi
        az_bin = _compute_azimuth_bin(rel_ang)

        grid[az_bin, d_bin] = 1

    return grid


def r2(
    ep: s4_world.Episode,
    clip_idx: int,
    *,
    precomputed_frame: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """生成 R2 圆盘占据图 [12, 7] uint8，取段内最后一帧（全局步 16*clip_idx + 15）。"""
    if not (0 <= clip_idx < 16):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, 16)")
    t = clip_idx * 16 + 15
    return _occupancy_grid(ep.steps[t], ep.pillars, precomputed_frame=precomputed_frame)


def r3(
    ep: s4_world.Episode,
    clip_idx: int,
    *,
    precomputed_frame: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> np.ndarray:
    """生成 R3 下一时刻占据图 [12, 7] uint8，取段末帧后 8 步（全局步 16*clip_idx + 15 + 8）。"""
    if not (0 <= clip_idx < 16):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, 16)")
    t = clip_idx * 16 + 15 + 8
    return _occupancy_grid(ep.steps[t], ep.pillars, precomputed_frame=precomputed_frame)


def disk_groups(
    ep: s4_world.Episode,
    clip_idx: int,
    *,
    precomputed_frame: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> list[dict[str, Any]]:
    """最后一帧每个看得见的圆盘的属性：方位格、距离格、距离组、遮挡比、遮挡组。"""
    if not (0 <= clip_idx < 16):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, 16)")
    t = clip_idx * 16 + 15
    st = ep.steps[t]
    x0, y0, heading = float(st.agent[0]), float(st.agent[1]), float(st.agent[2])

    if precomputed_frame is not None:
        _, depth, ids = precomputed_frame
    else:
        _, depth, ids = render(
            st.agent, st.positions, ep.pillars, width=224, height=224, return_ids=True
        )

    out = []
    for i, p in enumerate(st.positions):
        disk_oid = 100 + i
        visible_px = int(np.sum(ids == disk_oid))
        if visible_px < MIN_VISIBLE_PIXELS:
            continue

        px, py = float(p[0]), float(p[1])
        dist = math.hypot(px - x0, py - y0)
        d_bin = _compute_distance_bin(dist)
        if d_bin is None:
            continue

        ang = math.atan2(py - y0, px - x0)
        rel_ang = (ang - heading + math.pi) % (2.0 * math.pi) - math.pi
        az_bin = _compute_azimuth_bin(rel_ang)

        if dist < 2.0:
            dist_group = "< 2"
        elif dist <= 4.0:
            dist_group = "2–4"
        else:
            dist_group = "> 4"

        # 单独渲染该圆盘计算无遮挡像素数
        _, _, single_ids = render(
            st.agent, [p], [], width=224, height=224, return_ids=True
        )
        unoccluded_px = int(np.sum(single_ids == 100))
        occ_ratio = float(visible_px / unoccluded_px) if unoccluded_px > 0 else 0.0
        occ_group = "partial" if occ_ratio < 0.5 else "full"

        out.append(
            {
                "disk_id": i,
                "azimuth_bin": az_bin,
                "distance_bin": d_bin,
                "distance": float(dist),
                "distance_group": dist_group,
                "occlusion_ratio": float(occ_ratio),
                "occlusion_group": occ_group,
                "visible_pixels": visible_px,
                "unoccluded_pixels": unoccluded_px,
            }
        )

    return out


def ordering_pairs(
    ep: s4_world.Episode,
    clip_idx: int,
    *,
    precomputed_frame: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
) -> list[dict[str, Any]]:
    """最后一帧里看得见的「圆盘对圆盘」「圆盘对柱子」两两组合及真值前后次序。"""
    if not (0 <= clip_idx < 16):
        raise IndexError(f"clip_idx {clip_idx} out of range [0, 16)")
    t = clip_idx * 16 + 15
    st = ep.steps[t]

    if precomputed_frame is not None:
        _, depth, ids = precomputed_frame
    else:
        _, depth, ids = render(
            st.agent, st.positions, ep.pillars, width=224, height=224, return_ids=True
        )

    objects: list[dict[str, Any]] = []

    # 圆盘
    for i in range(len(st.positions)):
        oid = 100 + i
        mask = (ids == oid)
        if int(np.sum(mask)) >= MIN_VISIBLE_PIXELS:
            rows, cols = np.where(mask)
            r_c = float(np.mean(rows))
            c_c = float(np.mean(cols))
            patch = (
                int(np.clip(r_c // PATCH_SIZE, 0, GRID_H - 1)),
                int(np.clip(c_c // PATCH_SIZE, 0, GRID_W - 1)),
            )
            z_med = float(np.median(depth[mask]))
            objects.append(
                {
                    "type": "disk",
                    "id": oid,
                    "disk_index": i,
                    "patch": patch,
                    "z_median": z_med,
                }
            )

    # 柱子
    for k in range(len(ep.pillars)):
        oid = 1 + k
        mask = (ids == oid)
        if int(np.sum(mask)) >= MIN_VISIBLE_PIXELS:
            rows, cols = np.where(mask)
            r_c = float(np.mean(rows))
            c_c = float(np.mean(cols))
            patch = (
                int(np.clip(r_c // PATCH_SIZE, 0, GRID_H - 1)),
                int(np.clip(c_c // PATCH_SIZE, 0, GRID_W - 1)),
            )
            z_med = float(np.median(depth[mask]))
            objects.append(
                {
                    "type": "pillar",
                    "id": oid,
                    "pillar_index": k,
                    "patch": patch,
                    "z_median": z_med,
                }
            )

    pairs: list[dict[str, Any]] = []

    # 1. 圆盘对圆盘
    disks = [o for o in objects if o["type"] == "disk"]
    for i in range(len(disks)):
        for j in range(i + 1, len(disks)):
            a, b = disks[i], disks[j]
            closer = "a" if a["z_median"] < b["z_median"] else ("b" if b["z_median"] < a["z_median"] else "equal")
            pairs.append(
                {
                    "type": "disk_disk",
                    "id_a": a["id"],
                    "id_b": b["id"],
                    "patch_a": a["patch"],
                    "patch_b": b["patch"],
                    "z_a": a["z_median"],
                    "z_b": b["z_median"],
                    "closer": closer,
                }
            )

    # 2. 圆盘对柱子
    pillars = [o for o in objects if o["type"] == "pillar"]
    for a in disks:
        for b in pillars:
            closer = "a" if a["z_median"] < b["z_median"] else ("b" if b["z_median"] < a["z_median"] else "equal")
            pairs.append(
                {
                    "type": "disk_pillar",
                    "id_a": a["id"],
                    "id_b": b["id"],
                    "patch_a": a["patch"],
                    "patch_b": b["patch"],
                    "z_a": a["z_median"],
                    "z_b": b["z_median"],
                    "closer": closer,
                }
            )

    return pairs
