"""r6 probe_graph regression tests (CPU only, no MLX import).

The r5 direct CPU probe (S1-metric-map-direct-probe.json) found
``runtime.MlxBackend.probe_graph`` raising ``TypeError: cannot unpack
non-iterable numpy.int64`` on any non-empty metric map: the cell remap used
the flat cell index as an ``(r, c)`` pair.  These tests exercise the *real*
backend method (it is pure numpy and never imports MLX) with duck-typed
memory objects, covering the empty graph, a single cell, adjacent and
non-adjacent cells, pose rotation and the topology arm, plus the exact
audited 2x2 occupied-block input.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import runtime

GRID = 8
EXTENT_M = 6.5
CELL_M = 2.0 * EXTENT_M / GRID
CHANNELS = 3


class _MetricMapMemory:
    """Duck-typed ``arms.MetricMapMemory`` (numpy only; no MLX)."""

    def __init__(self, occupied: dict[tuple[int, int], np.ndarray], *, grid: int = GRID):
        self.grid = int(grid)
        self.extent_m = EXTENT_M
        self.cell_m = 2.0 * EXTENT_M / self.grid
        self.map = np.zeros((1, self.grid * self.grid, CHANNELS), dtype=np.float32)
        for (row, col), value in occupied.items():
            self.map[0, row * self.grid + col] = value


class _TopologyMemory:
    """Duck-typed ``arms.TopologyMemory`` (numpy only; no MLX)."""

    def __init__(self, *, count: int, edges: list[tuple[int, int]], mutual: bool = True):
        self.filled = np.asarray([count], dtype=np.int32)
        self.nodes = np.arange(1, count + 1, dtype=np.float32)[None, :, None].repeat(4, axis=2)
        self.node_pose = np.zeros((1, count, 3), dtype=np.float32)
        self.node_pose[0, :, 0] = np.arange(count, dtype=np.float32)
        self.node_pose[0, :, 1] = np.arange(count, dtype=np.float32) * 0.5
        self.node_pose[0, :, 2] = np.arange(count, dtype=np.float32) * 0.25
        matrix = np.zeros((1, count, count), dtype=np.float32)
        for i, j in edges:
            matrix[0, i, j] = 1.0
            if mutual:
                matrix[0, j, i] = 1.0
        self.edges = matrix
        self.match_threshold = 0.9

    def adjacency(self) -> np.ndarray:
        return (self.edges > 0).astype(np.float32)


def _probe(memory, pose=None):
    return runtime.MlxBackend().probe_graph(None, memory, pose=pose)


def _cell_value(marker: float) -> np.ndarray:
    row = np.zeros(CHANNELS, dtype=np.float32)
    row[0] = marker
    return row


# --- empty / single ---------------------------------------------------------
def test_probe_graph_none_memory_is_empty():
    graph = _probe(None)
    assert graph["nodes"].shape == (0, 1)
    assert graph["positions"].shape == (0, 2)
    assert graph["edges"] == set()


def test_probe_graph_empty_metric_map_is_empty():
    graph = _probe(_MetricMapMemory({}))
    assert graph["nodes"].shape == (0, CHANNELS)
    assert graph["positions"].shape == (0, 2)
    assert graph["edges"] == set()


def test_probe_graph_single_cell_has_no_edges():
    graph = _probe(_MetricMapMemory({(3, 3): _cell_value(1.0)}))
    assert graph["nodes"].shape == (1, CHANNELS)
    assert graph["positions"].shape == (1, 2)
    assert graph["edges"] == set()
    expected = np.asarray(
        [(3 - (GRID - 1) / 2.0) * CELL_M, (3 - (GRID - 1) / 2.0) * CELL_M]
    )
    assert graph["positions"][0] == pytest.approx(expected)


def test_probe_graph_empty_topology_graph_is_empty():
    graph = _probe(_TopologyMemory(count=0, edges=[]))
    # Pre-existing empty-topology shape: nodes carry no place dimension.
    assert graph["nodes"].shape == (0, 1)
    assert graph["positions"].shape == (0, 2)
    assert graph["edges"] == set()


# --- adjacency --------------------------------------------------------------
def test_probe_graph_horizontally_adjacent_cells_share_an_edge():
    graph = _probe(
        _MetricMapMemory({(3, 3): _cell_value(1.0), (3, 4): _cell_value(2.0)})
    )
    assert graph["nodes"].shape == (2, CHANNELS)
    assert graph["edges"] == {(0, 1)}
    distance = float(np.linalg.norm(graph["positions"][0] - graph["positions"][1]))
    assert distance == pytest.approx(CELL_M)


def test_probe_graph_vertically_adjacent_cells_share_an_edge():
    graph = _probe(
        _MetricMapMemory({(3, 3): _cell_value(1.0), (4, 3): _cell_value(2.0)})
    )
    assert graph["edges"] == {(0, 1)}
    distance = float(np.linalg.norm(graph["positions"][0] - graph["positions"][1]))
    assert distance == pytest.approx(CELL_M)


def test_probe_graph_diagonal_cells_are_not_adjacent():
    graph = _probe(
        _MetricMapMemory({(3, 3): _cell_value(1.0), (4, 4): _cell_value(2.0)})
    )
    assert graph["nodes"].shape == (2, CHANNELS)
    assert graph["edges"] == set()


def test_probe_graph_far_cells_are_not_adjacent():
    graph = _probe(
        _MetricMapMemory({(0, 0): _cell_value(1.0), (7, 7): _cell_value(2.0)})
    )
    assert graph["edges"] == set()


def test_probe_graph_audited_2x2_block_matches_the_manual_adjacency():
    """The exact input of the r5 direct probe: an occupied 2x2 block."""
    occupied = {
        (3, 3): _cell_value(1.0),
        (3, 4): _cell_value(2.0),
        (4, 3): _cell_value(3.0),
        (4, 4): _cell_value(4.0),
    }
    graph = _probe(_MetricMapMemory(occupied))
    assert graph["nodes"].shape == (4, CHANNELS)
    # flat-index order: (3,3)=27, (3,4)=28, (4,3)=35, (4,4)=36
    assert graph["edges"] == {(0, 1), (0, 2), (1, 3), (2, 3)}
    for i, j in graph["edges"]:
        assert 0 <= i < len(graph["nodes"]) and 0 <= j < len(graph["nodes"])
        distance = float(np.linalg.norm(graph["positions"][i] - graph["positions"][j]))
        assert distance == pytest.approx(CELL_M)


def test_probe_graph_nodes_follow_the_occupied_cell_values():
    graph = _probe(
        _MetricMapMemory({(2, 5): _cell_value(7.0), (2, 6): _cell_value(9.0)})
    )
    assert [float(row[0]) for row in graph["nodes"]] == [7.0, 9.0]


# --- pose rotation ----------------------------------------------------------
def test_probe_graph_rotates_positions_into_the_episode_frame():
    occupied = {(3, 3): _cell_value(1.0), (3, 4): _cell_value(2.0)}
    pose = np.asarray([1.0, 0.0, 2.0, 90.0], dtype=np.float64)
    graph = _probe(_MetricMapMemory(occupied), pose=pose)
    yaw = np.deg2rad(90.0)
    cos, sin = np.cos(yaw), np.sin(yaw)
    for index, (row, col) in enumerate([(3, 3), (3, 4)]):
        local_x = (col - (GRID - 1) / 2.0) * CELL_M
        local_z = (row - (GRID - 1) / 2.0) * CELL_M
        expected = np.asarray(
            [1.0 + cos * local_x + sin * local_z, 2.0 - sin * local_x + cos * local_z]
        )
        assert graph["positions"][index] == pytest.approx(expected)
    assert graph["edges"] == {(0, 1)}


def test_probe_graph_zero_pose_keeps_local_positions():
    graph = _probe(_MetricMapMemory({(3, 3): _cell_value(1.0)}), pose=np.zeros(4))
    # A zero anchor with zero yaw is the identity: the local cell centre.
    assert graph["positions"][0] == pytest.approx(
        np.asarray(
            [
                (3 - (GRID - 1) / 2.0) * CELL_M,
                (3 - (GRID - 1) / 2.0) * CELL_M,
            ]
        )
    )


# --- topology arm -----------------------------------------------------------
def test_probe_graph_topology_arm_uses_mutual_adjacency_only():
    memory = _TopologyMemory(count=3, edges=[(0, 1)])
    graph = _probe(memory)
    assert graph["nodes"].shape == (3, 4)
    assert graph["positions"].shape == (3, 2)
    assert graph["edges"] == {(0, 1)}
    assert graph["threshold"] == pytest.approx(0.9)
    assert graph["positions"][0] == pytest.approx([0.0, 0.0])
    assert graph["positions"][2] == pytest.approx([2.0, 1.0])


def test_probe_graph_topology_arm_ignores_one_directional_edges():
    memory = _TopologyMemory(count=2, edges=[(0, 1)], mutual=False)
    graph = _probe(memory)
    assert graph["edges"] == set()


def test_probe_graph_topology_and_metric_arms_agree_on_the_contract():
    topology = _probe(_TopologyMemory(count=2, edges=[(0, 1)]))
    metric = _probe(_MetricMapMemory({(3, 3): _cell_value(1.0), (3, 4): _cell_value(2.0)}))
    for graph in (topology, metric):
        assert set(graph) == {"nodes", "positions", "edges", "threshold"}
        assert graph["positions"].shape[1] == 2
        assert graph["positions"].shape[0] == graph["nodes"].shape[0]
        for i, j in graph["edges"]:
            assert i < j  # each adjacency is reported once, smaller ordinal first


def test_probe_graph_accepts_a_graph_wrapper_dict():
    memory = {"graph": _MetricMapMemory({(3, 3): _cell_value(1.0), (3, 4): _cell_value(2.0)})}
    graph = _probe(memory)
    assert graph["nodes"].shape == (2, CHANNELS)
    assert graph["edges"] == {(0, 1)}


def test_probe_graph_does_not_import_mlx():
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from ainerzero.v9.experiments.s1 import runtime\n"
        "class M:\n"
        "    grid=8; extent_m=6.5; cell_m=1.625\n"
        "    import numpy as np\n"
        "    map=np.zeros((1,64,3),dtype=np.float32)\n"
        "    map[0,27]=1.0; map[0,28]=1.0\n"
        "graph=runtime.MlxBackend().probe_graph(None, M())\n"
        "assert graph['edges']=={(0,1)}, graph['edges']\n"
        "assert not any(name.split('.')[0]=='mlx' for name in sys.modules)\n"
        "print('ok')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr
    assert "ok" in result.stdout
