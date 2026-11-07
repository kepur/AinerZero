"""Unit and contract tests for GridLab-S2 world module (r2.1).

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2.
"""

from __future__ import annotations

import collections
from pathlib import Path
import random
import site
import subprocess
import sys

import pytest

from src.ainerzero.v9.experiments.s2.world import (
    SIZE,
    FREE,
    WALL,
    PILLAR,
    UNSEEN,
    NORTH,
    EAST,
    SOUTH,
    WEST,
    ACTION_FORWARD,
    ACTION_WAIT,
    LONG_GOAL_MIN_DIST,
    Layout,
    State,
    make_layout,
    step,
    student_obs,
    truth,
    sample_goal,
    sample_start_goal_pair,
    compute_ego_view,
    compute_bfs_distances,
    compute_pose_bfs_distances,
    is_goal_ambiguous,
    is_success,
    is_success_strict,
    world_rejection_requires_redraw,
    prepare_world_with_long_pairs,
    _ALLOW_LONG_DISTANCE_FALLBACK,
)


def test_determinism_layout():
    """Deterministic generation: same seed yields bitwise identical layout, different seed differs."""
    l1 = make_layout(42)
    l2 = make_layout(42)
    l3 = make_layout(43)

    assert l1.layout_sha256 == l2.layout_sha256
    assert l1.terrain == l2.terrain
    assert l1.doors == l2.doors
    assert l1.pillars == l2.pillars

    assert l1.layout_sha256 != l3.layout_sha256
    assert l1.terrain != l3.terrain


def test_connectivity_and_doorways():
    """Every adjacent room pair has 1-2 open doors; entire floor is fully connected."""
    for seed in (7, 10, 20, 30):
        layout = make_layout(seed)

        assert len(layout.rooms) == 9
        assert 12 <= len(layout.doors) <= 24

        free_cells = [
            (x, y)
            for y in range(SIZE)
            for x in range(SIZE)
            if layout.terrain[y][x] == FREE
        ]
        start = free_cells[0]
        queue = collections.deque([start])
        visited = {start}
        while queue:
            cx, cy = queue.popleft()
            for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                nx, ny = cx + dx, cy + dy
                if 0 <= nx < SIZE and 0 <= ny < SIZE and layout.terrain[ny][nx] == FREE:
                    if (nx, ny) not in visited:
                        visited.add((nx, ny))
                        queue.append((nx, ny))

        assert len(visited) == len(free_cells), "All floor cells must be mutually connected"


def test_line_of_sight_closed_form():
    """Three hand-crafted closed-form line-of-sight & rotation cases."""
    layout = make_layout(100)
    view_n = compute_ego_view(layout, 1, 1, NORTH)
    assert view_n[2][3] == WALL
    assert view_n[1][3] == UNSEEN
    assert view_n[0][3] == UNSEEN

    test_terrain = [[FREE for _ in range(SIZE)] for _ in range(SIZE)]
    test_terrain[9][10] = PILLAR
    test_layout = Layout(
        seed=0,
        terrain=test_terrain,
        rooms=[],
        doors=[],
        pillars=[(10, 9)],
        layout_sha256="test",
    )
    view_pillar = compute_ego_view(test_layout, 10, 10, NORTH)
    assert view_pillar[2][3] == PILLAR
    assert view_pillar[1][3] == UNSEEN
    assert view_pillar[0][3] == UNSEEN

    view_east = compute_ego_view(test_layout, 10, 10, EAST)
    assert view_east[3][2] == PILLAR
    assert view_east[3][1] == UNSEEN

    view_west = compute_ego_view(test_layout, 10, 10, WEST)
    assert view_west[3][4] == PILLAR
    assert view_west[3][5] == UNSEEN


def test_no_coordinate_leakage():
    """Verify that student_obs strictly leaks zero coordinates and identical surroundings match."""
    layout = make_layout(123)
    state1 = State(x=2, y=2, heading=NORTH)
    obs = student_obs(layout, state1, last_action=ACTION_WAIT, dt=1)

    forbidden_terms = ("x", "y", "pos", "coord", "position", "location")
    for key in obs.keys():
        for term in forbidden_terms:
            assert term not in key.lower(), f"Forbidden coordinate term found in key: '{key}'"

    synth_terrain = [[FREE for _ in range(SIZE)] for _ in range(SIZE)]
    for bx, by in ((5, 5), (15, 15)):
        synth_terrain[by - 1][bx] = WALL
        synth_terrain[by + 1][bx] = WALL
        synth_terrain[by][bx - 1] = WALL
        synth_terrain[by][bx + 1] = WALL

    synth_layout = Layout(
        seed=1,
        terrain=synth_terrain,
        rooms=[],
        doors=[],
        pillars=[],
        layout_sha256="synth",
    )
    obs_a = student_obs(synth_layout, State(x=5, y=5, heading=NORTH), last_action=ACTION_FORWARD, dt=2)
    obs_b = student_obs(synth_layout, State(x=15, y=15, heading=NORTH), last_action=ACTION_FORWARD, dt=2)

    assert obs_a == obs_b, "Two states with identical ego-view and state must produce identical student_obs"


def test_k_repeat_and_wall_bumps():
    """k=3 forward is equivalent to 3x k=1; wall bumps increment correctly."""
    layout = make_layout(200)
    free_cells = [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if layout.terrain[y][x] == FREE
    ]
    start = free_cells[0]
    s_init = State(x=start[0], y=start[1], heading=NORTH)

    s_1a = step(layout, s_init, ACTION_FORWARD, k=1)
    s_1b = step(layout, s_1a, ACTION_FORWARD, k=1)
    s_1c = step(layout, s_1b, ACTION_FORWARD, k=1)
    s_3 = step(layout, s_init, ACTION_FORWARD, k=3)

    assert s_1c.x == s_3.x
    assert s_1c.y == s_3.y
    assert s_1c.heading == s_3.heading
    assert s_1c.wall_bumps == s_3.wall_bumps

    s_wall = State(x=1, y=1, heading=NORTH, wall_bumps=0)
    s_bumped = step(layout, s_wall, ACTION_FORWARD, k=3)
    assert s_bumped.x == 1
    assert s_bumped.y == 1
    assert s_bumped.wall_bumps == 3


def test_goal_sampling_and_ambiguity_rejection():
    """Long goal pose-BFS >= 40, short <= 10; ambiguous goal must be rejected."""
    layout = make_layout(300)
    rng = random.Random(42)

    start = State(x=1, y=1, heading=NORTH)
    goal_long, obs_long, stats_long = sample_goal(layout, start, rng, kind="long")
    assert stats_long["bfs_distance"] >= LONG_GOAL_MIN_DIST
    assert stats_long["fallback_used"] is False
    assert "view" in obs_long

    goal_short, obs_short, stats_short = sample_goal(layout, start, rng, kind="short")
    assert 0 < stats_short["bfs_distance"] <= 10

    empty_terrain = [[FREE for _ in range(SIZE)] for _ in range(SIZE)]
    empty_layout = Layout(
        seed=999,
        terrain=empty_terrain,
        rooms=[],
        doors=[],
        pillars=[],
        layout_sha256="empty",
    )
    assert is_goal_ambiguous(empty_layout, 10, 10, NORTH) is True

    with pytest.raises(RuntimeError, match="Failed to find an unambiguous goal"):
        sample_goal(empty_layout, (10, 10, NORTH), rng, kind="short", max_attempts=5)


def test_long_goals_no_fallback_multi_start():
    """r2.1: many random starts — accepted long goals all ≥40; impossible starts raise (no fallback)."""
    assert _ALLOW_LONG_DISTANCE_FALLBACK is False

    layout = make_layout(777)
    rng = random.Random(123)
    free_cells = [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if layout.terrain[y][x] == FREE
    ]

    ge40 = 0
    lt40 = 0
    for _ in range(25):
        sx, sy = rng.choice(free_cells)
        sh = rng.randrange(4)
        start = State(x=sx, y=sy, heading=sh)
        distances = compute_pose_bfs_distances(layout, start)
        max_d = max(distances.values())
        if max_d < LONG_GOAL_MIN_DIST:
            lt40 += 1
            with pytest.raises(RuntimeError, match="no fallback"):
                sample_goal(layout, start, rng, kind="long", max_attempts=20)
        else:
            try:
                goal, _, stats = sample_goal(layout, start, rng, kind="long")
            except RuntimeError as exc:
                # Ambiguity exhaustion is allowed; distance fallback is not.
                assert "unambiguous" in str(exc)
                continue
            ge40 += 1
            assert stats["bfs_distance"] >= LONG_GOAL_MIN_DIST
            assert stats["fallback_used"] is False
            assert distances[(goal.x, goal.y, goal.heading)] == stats["bfs_distance"]

    # Joint pairs also respect the floor.
    for _ in range(8):
        start, goal, _, stats = sample_start_goal_pair(layout, rng, kind="long")
        d = compute_pose_bfs_distances(layout, start)[(goal.x, goal.y, goal.heading)]
        assert d >= LONG_GOAL_MIN_DIST
        assert stats["bfs_distance"] == d

    assert ge40 >= 1
    assert lt40 >= 1  # ensures the raise/no-fallback branch is exercised


def test_is_success_rules():
    """is_success ignores heading; strict requires heading; budget is 3×BFS."""
    goal = State(x=5, y=5, heading=EAST)
    pose_ok = {"x": 5, "y": 5, "heading": NORTH}
    pose_bad = {"x": 4, "y": 5, "heading": EAST}
    assert is_success(pose_ok, goal, steps_used=30, bfs_dist=10) is True
    assert is_success(pose_bad, goal, steps_used=1, bfs_dist=10) is False
    assert is_success(pose_ok, goal, steps_used=31, bfs_dist=10) is False
    assert is_success_strict(pose_ok, goal, steps_used=30, bfs_dist=10) is False
    assert is_success_strict({"x": 5, "y": 5, "heading": EAST}, goal, 30, 10) is True


def test_world_rejection_redraw_gate():
    """Rejection-rate gate triggers above 30%; prepare_world records redraw budget."""
    assert world_rejection_requires_redraw(0.30) is False
    assert world_rejection_requires_redraw(0.301) is True
    assert world_rejection_requires_redraw(0.99, enforce=False) is False

    layout, pairs, summary = prepare_world_with_long_pairs(501, random.Random(7), n_long_pairs=6)
    assert len(pairs) == 6
    for pair in pairs:
        assert pair["bfs_distance"] >= LONG_GOAL_MIN_DIST
    assert "world_redraws" in summary
    assert summary["rejection_rate"] <= 0.30 + 1e-12


def test_pure_cpu_no_mlx_import():
    """Isolated subprocess check: importing s2 world does NOT import MLX."""
    user_site = site.getusersitepackages()
    code = (
        "import sys, site; "
        f"site.addsitedir({repr(user_site)}); "
        "sys.path.insert(0, 'src'); sys.path.insert(0, '.'); "
        "from ainerzero.v9.experiments.s2 import world; "
        "assert 'mlx' not in sys.modules; "
        "assert 'mlx.core' not in sys.modules; "
        "print('OK')"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Import check failed: {proc.stderr}"
    assert "OK" in proc.stdout


def test_no_gridlab_module_imported():
    """Isolated subprocess check: importing s2 world and data does NOT load gridlab into sys.modules."""
    repo_root = Path(__file__).resolve().parents[3]
    venv_python = repo_root / ".venv" / "bin" / "python"
    py_exec = str(venv_python) if venv_python.exists() else sys.executable
    code = (
        "import sys, site\n"
        f"site.addsitedir({repr(site.getusersitepackages())})\n"
        "sys.path.insert(0, 'src')\n"
        "sys.path.insert(0, '.')\n"
        "from ainerzero.v9.experiments.s2 import world, data\n"
        "loaded_gridlab = [m for m in sys.modules if 'gridlab' in m.lower()]\n"
        "assert not loaded_gridlab, f'GridLab modules imported: {loaded_gridlab}'\n"
        "print('NO_GRIDLAB_OK')\n"
    )
    proc = subprocess.run(
        [py_exec, "-I", "-c", code],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
    )
    assert proc.returncode == 0, f"Subprocess failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "NO_GRIDLAB_OK" in proc.stdout

