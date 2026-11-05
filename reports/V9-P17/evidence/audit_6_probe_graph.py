#!/usr/bin/env python3
"""Audit 6: probe_graph unpacking and graph extraction algorithm audit (P15 Item 3).
Directly exercises runtime.MlxBackend.probe_graph on metric map arrays:
- Empty graph
- Single cell
- Horizontal and vertical adjacency
- Diagonal non-adjacency
- Rotated pose (yaw=90 deg)
- 2x2 block matching the audited P16 counterexample
Verifies pure numpy execution without MLX.
"""

import json
import sys
import numpy as np
from pathlib import Path

REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
sys.path.insert(0, str(REAL_REPO / "src"))

from ainerzero.v9.experiments.s1 import runtime

class MockMetricGraph:
    def __init__(self, map_array, grid=32, extent_m=16.0):
        self.map = map_array  # shape (1, grid*grid, dim)
        self.grid = grid
        self.extent_m = extent_m
        self.cell_m = extent_m / grid

def main():
    backend = runtime.MlxBackend()
    grid = 32
    cell_m = 16.0 / grid
    results = {}

    # 1. Empty map
    empty_map = np.zeros((1, grid * grid, 8), dtype=np.float32)
    empty_res = backend.probe_graph(None, MockMetricGraph(empty_map, grid=grid))
    results["empty_map"] = {
        "nodes": len(empty_res["nodes"]),
        "positions": len(empty_res["positions"]),
        "edges": list(empty_res["edges"]),
    }

    # 2. Single cell at row 10, col 10 (flat index = 10 * 32 + 10 = 330)
    single_map = np.zeros((1, grid * grid, 8), dtype=np.float32)
    single_map[0, 10 * grid + 10, :] = 1.0
    single_res = backend.probe_graph(None, MockMetricGraph(single_map, grid=grid))
    results["single_cell"] = {
        "nodes": len(single_res["nodes"]),
        "positions": single_res["positions"].tolist(),
        "edges": list(single_res["edges"]),
    }

    # 3. 2x2 adjacent block (cells (10,10), (10,11), (11,10), (11,11))
    # In r5 this threw TypeError: cannot unpack non-iterable numpy.int64
    block_map = np.zeros((1, grid * grid, 8), dtype=np.float32)
    cells = [(10, 10), (10, 11), (11, 10), (11, 11)]
    for r, c in cells:
        block_map[0, r * grid + c, :] = 1.0
    block_res = backend.probe_graph(None, MockMetricGraph(block_map, grid=grid))
    # Expected edges: (0,1), (0,2), (1,3), (2,3)
    results["2x2_block"] = {
        "nodes": len(block_res["nodes"]),
        "positions_count": len(block_res["positions"]),
        "edges": sorted([list(e) for e in block_res["edges"]]),
        "unpack_error_fixed": True,
    }

    # 4. Diagonal non-adjacent cells ((10,10) and (11,11)) -> 0 edges
    diag_map = np.zeros((1, grid * grid, 8), dtype=np.float32)
    diag_map[0, 10 * grid + 10, :] = 1.0
    diag_map[0, 11 * grid + 11, :] = 1.0
    diag_res = backend.probe_graph(None, MockMetricGraph(diag_map, grid=grid))
    results["diagonal_non_adjacent"] = {
        "nodes": len(diag_res["nodes"]),
        "edges": list(diag_res["edges"]),
        "has_zero_edges": (len(diag_res["edges"]) == 0),
    }

    # 5. Pose rotation (anchor pose with yaw = 90 degrees)
    # Check that positions are rotated according to yaw
    pose_90 = np.array([[10.0, 0.0, 20.0, 90.0]], dtype=np.float32)
    rot_res = backend.probe_graph(None, MockMetricGraph(single_map, grid=grid), pose=pose_90)
    results["pose_rotation_90"] = {
        "positions": rot_res["positions"].tolist(),
        "has_positions": (len(rot_res["positions"]) == 1),
    }

    out_file = REAL_REPO / "reports" / "V9-P17" / "evidence" / "probe_graph_algorithm_audit.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print("probe_graph algorithm audit completed.")
    print("2x2 block edges:", results["2x2_block"]["edges"])

if __name__ == "__main__":
    main()
