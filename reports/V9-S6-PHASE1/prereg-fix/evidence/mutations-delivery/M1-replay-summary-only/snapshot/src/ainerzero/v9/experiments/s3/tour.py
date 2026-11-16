"""GridLab-S3 Tour Exploration Generator.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §2.
Pure CPU, NumPy / standard library only. Zero MLX imports.
"""

from __future__ import annotations

import collections
import random
from typing import Any

import numpy as np

from ainerzero.v9.experiments.s2.world import (
    ACTION_WAIT,
    ACTIONS,
    Layout,
    State,
)
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.content import ContentState
from ainerzero.v9.experiments.s3.world import (
    compute_reverse_bfs_distances,
    compute_student_obs,
    get_connected_free_cells,
    step_to_goal,
    step_with_slip,
    update_odometry,
)


def extract_readout_events(
    steps_or_positions: list[dict[str, Any]] | list[tuple[int, int]],
    content_state: ContentState,
) -> list[dict[str, Any]]:
    """Extract return/readout events from step records or trajectory.

    A readout event occurs whenever the agent returns to a content cell
    (including passing through / 路过) after having visited it previously and
    subsequently left it.

    Ensures all extracted events strictly satisfy 0 <= t < len(steps_or_positions)
    and 0 <= prev_visit_t < t.
    """
    if not steps_or_positions:
        return []

    if isinstance(steps_or_positions[0], dict):
        positions = [
            (int(st["truth"]["x"]), int(st["truth"]["y"]))
            for st in steps_or_positions
        ]
    else:
        positions = list(steps_or_positions)

    n_steps = len(positions)
    content_set = set(content_state.content_cells)
    events: list[dict[str, Any]] = []

    # Map from cell to list of all steps the agent was standing on that cell
    cell_steps: dict[tuple[int, int], list[int]] = collections.defaultdict(list)
    cell_steps[positions[0]].append(0)

    for t in range(1, n_steps):
        c = positions[t]
        prev_c = positions[t - 1]

        # Return event triggers on arrival at a content cell from a different cell
        if c in content_set and c != prev_c:
            hist = cell_steps[c]
            if hist:
                prev_visit_t = hist[-1]
                assert 0 <= prev_visit_t < t < n_steps, (
                    f"Invariant violation: prev_visit_t={prev_visit_t}, t={t}, n_steps={n_steps}"
                )
                lag = t - prev_visit_t
                bk = spec.get_bucket(lag)

                tok_now = content_state.get_token(c, t)
                tok_prev = content_state.get_token(c, prev_visit_t)
                swapped = (tok_now != tok_prev)

                events.append(
                    {
                        "t": t,
                        "cell": list(c),
                        "prev_visit_t": prev_visit_t,
                        "lag": lag,
                        "bucket": bk,
                        "swapped": swapped,
                        "answer": tok_prev,
                    }
                )

        cell_steps[c].append(t)

    return events


def run_tour(
    layout: Layout,
    content_state: ContentState,
    rng: random.Random,
    *,
    t_max: int = spec.T,
    p_slip: float = spec.P_SLIP,
    noise: float = spec.NOISE,
) -> dict[str, Any]:
    """Execute tour exploration for one episode.

    Navigation follows reverse multi-source BFS with exploration noise.
    Scheduled returns to content targets take priority over unvisited targets.
    """
    targets = list(content_state.content_cells)
    all_connected = get_connected_free_cells(layout)

    # Initial state at first content cell with random heading
    start_cell = targets[0]
    start_heading = rng.choice([0, 1, 2, 3])
    s = State(x=start_cell[0], y=start_cell[1], heading=start_heading, wall_bumps=0)
    est_pose = (float(s.x), float(s.y), s.heading)

    queue = list(targets[1:])
    due: list[tuple[int, tuple[int, int]]] = []
    visited: dict[tuple[int, int], list[int]] = collections.defaultdict(list)

    steps_data: list[dict[str, Any]] = []

    t = 0
    last_action = ACTION_WAIT
    bumped = False

    while t < t_max:
        # Determine current navigation goal
        due.sort()
        if due and due[0][0] <= t:
            _, goal = due.pop(0)
        elif queue:
            goal = queue.pop(0)
        elif visited:
            goal = rng.choice(list(visited))
        else:
            goal = rng.choice(all_connected)

        dist_field = compute_reverse_bfs_distances(layout, goal)
        guard = 0

        while t < t_max and (s.x, s.y) != goal and guard < 200:
            guard += 1

            # Compute observation at step t BEFORE executing action
            content_map = content_state.get_token_map_at_step(t)
            obs = compute_student_obs(layout, s, last_action, bumped, content_map)

            # Choose action: exploration noise vs reverse BFS shortest path
            if rng.random() < noise:
                action = rng.choice(ACTIONS)
            else:
                action = step_to_goal(layout, s, dist_field)

            # Execute action with silent slip
            next_s, slipped, bumped = step_with_slip(layout, s, action, p_slip, rng)

            # Record step (t is in [0, t_max - 1])
            steps_data.append(
                {
                    "t": t,
                    "obs": obs,
                    "action": action,
                    "est_pose": list(est_pose),
                    "truth": {
                        "x": s.x,
                        "y": s.y,
                        "heading": s.heading,
                        "wall_bumps": s.wall_bumps,
                        "slipped": slipped,
                        "bumped": bumped,
                        "cell_token": content_state.get_token((s.x, s.y), t),
                    },
                }
            )

            # Update odometry for next step
            est_pose = update_odometry(est_pose, action, bumped)

            # Step environment
            s = next_s
            last_action = action
            t += 1

        # Check if goal reached
        if (s.x, s.y) == goal:
            visited[goal].append(t)
            # Schedule up to 2 return visits
            if len(visited[goal]) <= 2:
                name, a_, b_ = rng.choice(spec.BUCKETS)
                due_step = t + rng.randint(a_, min(b_, 160))
                due.append((due_step, goal))

    # Trajectory positions strictly corresponding to the steps in steps_data (length == len(steps_data))
    trajectory_positions = [
        (int(st["truth"]["x"]), int(st["truth"]["y"])) for st in steps_data
    ]
    # Extract events strictly within valid step bounds [0, len(steps_data) - 1]
    events = extract_readout_events(steps_data, content_state)

    return {
        "t_max": t_max,
        "steps_count": len(steps_data),
        "steps": steps_data,
        "trajectory_positions": trajectory_positions,
        "events": events,
        "content_state": content_state.to_dict(),
        "layout_sha256": layout.layout_sha256,
    }
