#!/usr/bin/env python3
"""Check 1: Geometry correctness of render.py vs independent analytic solutions.

Independent analytic formulation:
- Coordinate system: Arena [0, 10] x [0, 10]. Agent (x0, y0, heading).
- Pin-hole model:
    W = 224, H = 224, FOV = 90 deg.
    f_analytic = (W / 2) / tan(45 deg) = 112.0
- Column c in [0, W-1]:
    col_offset = c + 0.5 - W/2
    ray_angle = heading - arctan(col_offset / f)
    ray_dir = (cos(ray_angle), sin(ray_angle))
    cos_off = cos(ray_angle - heading) = cos(arctan(col_offset / f))
- Orthogonal depth z vs ray distance t:
    z = t * cos_off
"""
import sys
import math
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
EXPLORE = ROOT / "reports" / "V9-S5-DESIGN" / "tier1-explore"
sys.path.insert(0, str(EXPLORE))
import render as R

def run_checks():
    results = {}
    
    # 1.1 Agent in arena center (5, 5), heading = 0 (facing +x).
    # The east wall is at x = 10. The ray along optical axis (heading = 0) travels (10 - x0) = 5.0.
    agent = (5.0, 5.0, 0.0)
    img, depth, ids = R.render(agent, [], [], width=224, height=224, return_ids=True, texture=False)
    
    # Center columns: index 111 (col = -0.5) and index 112 (col = +0.5).
    # Optical axis is at col = 0 (between 111 and 112).
    # For a planar wall at x = 10 perpendicular to heading:
    # Any column c hitting the east wall has ray direction dx = cos(ang).
    # Ray distance t = (10 - x0) / dx.
    # Orthogonal depth z = t * cos(ang - heading) = ((10 - x0) / cos(ang)) * cos(ang) = 10 - x0 = 5.0.
    # Check middle columns:
    mid_depth_111 = depth[112, 111]
    mid_depth_112 = depth[112, 112]
    expected_wall_z = 10.0 - 5.0
    results["center_wall_depth_col111"] = float(mid_depth_111)
    results["center_wall_depth_col112"] = float(mid_depth_112)
    results["center_wall_expected"] = expected_wall_z
    diff_wall = max(abs(mid_depth_111 - expected_wall_z), abs(mid_depth_112 - expected_wall_z))
    results["center_wall_max_error"] = float(diff_wall)
    assert diff_wall < 1e-5, f"Center wall depth error {diff_wall} >= 1e-5"

    # 1.2 Floor depth analytic formula:
    # Camera height CAM_H = 0.5. Horizon is at row = 0 (center of image, between 111 and 112).
    # For row r in [112..223], row_offset = r + 0.5 - H/2.
    # Analytic depth: z_floor(r) = f * CAM_H / row_offset = 112.0 * 0.5 / (r + 0.5 - 112).
    f_expected = 112.0
    cam_h = 0.5
    floor_diffs = []
    # Test rows 115, 130, 160, 200, 223 (columns where wall does not occlude, but wall occludes floor when z_wall < z_floor)
    # Notice wall at x=10 has z=5.0. Floor reaches z=5.0 when:
    # 5.0 = 112 * 0.5 / row_offset => row_offset = 56 / 5 = 11.2 => r = 112 + 11.2 = 123.2.
    # So for r >= 124, floor is in front of wall (z_floor <= 5.0) and should be visible!
    for r in range(125, 224):
        row_offset = r + 0.5 - 112.0
        analytic_z = f_expected * cam_h / row_offset
        # Check center columns
        measured_z = depth[r, 112]
        measured_id = ids[r, 112]
        assert measured_id == -1, f"Expected floor (id -1) at row {r}, got {measured_id}"
        floor_diffs.append(abs(measured_z - analytic_z))
    results["floor_max_abs_error"] = float(max(floor_diffs))
    assert max(floor_diffs) < 1e-5, f"Floor depth error {max(floor_diffs)} >= 1e-5"

    # 1.3 Pillar / Disk top and bottom row analytic pinhole calculation:
    # Place a single pillar at (8.0, 5.0), radius 0.5 (dx = 3.0 along optical axis).
    # Front-most surface of pillar is at x = 8.0 - 0.5 = 7.5.
    # Depth z = 7.5 - 5.0 = 2.5.
    # Pillar height = 2.0, CAM_H = 0.5.
    # Top relative to camera = 2.0 - 0.5 = +1.5 (above camera).
    # Bottom relative to camera = 0.0 - 0.5 = -0.5 (below camera).
    # Analytic image row offsets (positive downward):
    # top_offset = -f * (h - CAM_H) / z = -112.0 * 1.5 / 2.5 = -67.2.
    # bottom_offset = +f * CAM_H / z = 112.0 * 0.5 / 2.5 = +22.4.
    # In row index (row = offset + 112 - 0.5):
    # top_row_idx = -67.2 + 111.5 = 44.3 => first integer row index >= 44.3 is 45.
    # bottom_row_idx = 22.4 + 111.5 = 133.9 => last integer row index <= 133.9 is 133.
    pillar_pos = [(8.0, 5.0, 0.5)]
    img_p, depth_p, ids_p = R.render(agent, [], pillar_pos, width=224, height=224, return_ids=True, texture=False)
    # Check center column 112 where ray is along optical axis:
    pillar_col = ids_p[:, 112]
    pillar_rows = np.where(pillar_col == 1)[0]
    results["pillar_rendered_top_row"] = int(pillar_rows.min())
    results["pillar_rendered_bottom_row"] = int(pillar_rows.max())
    results["pillar_expected_top_row"] = 45
    results["pillar_expected_bottom_row"] = 133
    assert pillar_rows.min() == 45, f"Pillar top row {pillar_rows.min()} != 45"
    assert pillar_rows.max() == 133, f"Pillar bottom row {pillar_rows.max()} != 133"

    # 1.4 Occlusion test: Disk placed strictly behind pillar
    # Pillar at (7.0, 5.0), r = 0.5. Disk at (9.0, 5.0), r = 0.3.
    # The pillar completely occludes the disk along the optical axis (and angularly covers it since 0.5/2.0 > 0.3/4.0).
    disk_pos = [(9.0, 5.0)]
    pillar_occ = [(7.0, 5.0, 0.5)]
    _, _, ids_occ = R.render(agent, disk_pos, pillar_occ, width=224, height=224, return_ids=True, texture=False)
    disk_pixels = np.count_nonzero(ids_occ == 100)
    results["occluded_disk_pixel_count"] = int(disk_pixels)
    assert disk_pixels == 0, f"Occluded disk should have 0 pixels, got {disk_pixels}"

    # 1.5 Left / right orientation:
    # Agent at (5.0, 5.0), heading = 0 (+x).
    # Left of agent is +y direction.
    # Place disk at (8.0, 6.0) (to the left of agent).
    disk_left = [(8.0, 6.0)]
    _, _, ids_lr = R.render(agent, disk_left, [], width=224, height=224, return_ids=True, texture=False)
    disk_cols = np.where(ids_lr == 100)[1]
    assert len(disk_cols) > 0, "Disk left not rendered"
    results["left_disk_col_min"] = int(disk_cols.min())
    results["left_disk_col_max"] = int(disk_cols.max())
    results["left_disk_col_mean"] = float(disk_cols.mean())
    # All columns must be in the left half of the image (< 112)
    assert disk_cols.max() < 112, f"Left disk appeared on right side: max col {disk_cols.max()} >= 112"

    # 1.6 Depth is orthogonal depth z, NOT Euclidean ray distance t.
    # Check along the east wall at x = 10.
    # Across ALL columns hitting the east wall (where dx > 0 and tx < ty):
    # For col c in [50..174], ray hits east wall.
    # Ray distance t(c) = (10 - x0) / cos(theta) = 5.0 / cos(theta).
    # If depth were ray distance t, depth at col 50 (theta ≈ -29 deg) would be 5.0 / cos(29 deg) ≈ 5.72.
    # But orthogonal depth z = t * cos(theta) = 5.0.
    wall_cols = range(60, 165)
    wall_depths = [depth[111, c] for c in wall_cols]
    results["east_wall_depth_min"] = float(min(wall_depths))
    results["east_wall_depth_max"] = float(max(wall_depths))
    results["east_wall_depth_mean"] = float(np.mean(wall_depths))
    max_wall_variation = max(wall_depths) - min(wall_depths)
    results["east_wall_depth_variation"] = float(max_wall_variation)
    assert max_wall_variation < 1e-5, f"Orthogonal depth varies across wall columns: {max_wall_variation}"

    return results

if __name__ == "__main__":
    res = run_checks()
    import json
    print(json.dumps(res, indent=2))
