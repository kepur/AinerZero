"""Test reverse multi-source BFS pathfinding reachability.

Requirement:
No exploration noise, >= 30 worlds x 5 long goals, reachability must be 100%.
"""

from __future__ import annotations

import random

import pytest

from ainerzero.v9.experiments.s2.world import (
    Layout,
    State,
    make_layout,
    step,
)
from ainerzero.v9.experiments.s3.world import (
    compute_reverse_bfs_distances,
    get_connected_free_cells,
    step_to_goal,
)


def test_reverse_bfs_reachability_100_percent() -> None:
    """Assert reverse BFS achieves 100% reachability across >= 30 worlds x 5 long goals."""
    n_worlds = 35
    goals_per_world = 5
    max_steps = 300

    total_attempts = 0
    successful_arrivals = 0

    for w_idx in range(n_worlds):
        seed = 4000 + w_idx
        layout = make_layout(seed)
        connected = get_connected_free_cells(layout)
        rng = random.Random(seed * 31 + 7)

        for _ in range(goals_per_world):
            start = rng.choice(connected)
            # Filter for long goals (Manhattan distance >= 15)
            long_goals = [
                c for c in connected
                if (abs(c[0] - start[0]) + abs(c[1] - start[1])) >= 15
            ]
            assert long_goals, f"No long goals found for start {start} in world {seed}"
            goal = rng.choice(long_goals)

            s = State(x=start[0], y=start[1], heading=rng.choice([0, 1, 2, 3]))
            dist_field = compute_reverse_bfs_distances(layout, goal)

            step_count = 0
            while (s.x, s.y) != goal and step_count < max_steps:
                action = step_to_goal(layout, s, dist_field)
                s = step(layout, s, action, k=1)
                step_count += 1

            total_attempts += 1
            if (s.x, s.y) == goal:
                successful_arrivals += 1

    reachability = successful_arrivals / total_attempts
    assert reachability == 1.0, (
        f"Pathfinding reachability failed: {successful_arrivals}/{total_attempts} "
        f"({reachability * 100:.2f}%), required 100%"
    )
