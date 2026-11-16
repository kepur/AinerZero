"""GridLab-S3 World Environment and Navigation.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §2.
Pure CPU, NumPy / standard library only. Zero MLX imports.

Reuses authoritative primitives from ainerzero.v9.experiments.s2.world:
make_layout, step, compute_ego_view, State, and world constants.
"""

from __future__ import annotations

import collections
import random
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s2.world import (
    ACTION_FORWARD,
    ACTION_TURN_LEFT,
    ACTION_TURN_RIGHT,
    ACTION_WAIT,
    ACTIONS,
    DELTA,
    EAST,
    FREE,
    Layout,
    NORTH,
    PATH_ACTIONS,
    PILLAR,
    SIZE,
    SOUTH,
    State,
    UNSEEN,
    VIEW_RADIUS as S2_VIEW_RADIUS,
    VIEW_SIZE as S2_VIEW_SIZE,
    WALL,
    WEST,
    compute_ego_view,
    make_layout,
    step,
)
from ainerzero.v9.experiments.s3 import spec


def get_connected_free_cells(layout: Layout) -> list[tuple[int, int]]:
    """Return all cells in the largest connected component of FREE cells."""
    free = [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if layout.terrain[y][x] == FREE
    ]
    seen: set[tuple[int, int]] = set()
    best_component: list[tuple[int, int]] = []

    for c in free:
        if c in seen:
            continue
        q = [c]
        seen.add(c)
        comp = [c]
        while q:
            x, y = q.pop()
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                n = (x + dx, y + dy)
                if (
                    0 <= n[0] < SIZE
                    and 0 <= n[1] < SIZE
                    and layout.terrain[n[1]][n[0]] == FREE
                    and n not in seen
                ):
                    seen.add(n)
                    q.append(n)
                    comp.append(n)
        if len(comp) > len(best_component):
            best_component = comp

    return sorted(best_component)


def compute_reverse_bfs_distances(
    layout: Layout,
    goal: tuple[int, int],
) -> dict[tuple[int, int, int], int]:
    """Reverse multi-source BFS from target cell (any heading).

    dist[(x, y, heading)] is the minimum number of actions needed to reach
    (goal[0], goal[1], any_heading) from (x, y, heading).
    """
    gx, gy = goal
    dist: dict[tuple[int, int, int], int] = {}
    q: collections.deque[tuple[int, int, int]] = collections.deque()

    # All 4 orientations at the goal cell have distance 0
    for h in range(4):
        dist[(gx, gy, h)] = 0
        q.append((gx, gy, h))

    while q:
        x, y, h = q.popleft()
        d = dist[(x, y, h)]

        # Predecessor via TURN_LEFT: previous heading was (h + 1) % 4
        prev_h_left = (h + 1) % 4
        if (x, y, prev_h_left) not in dist:
            dist[(x, y, prev_h_left)] = d + 1
            q.append((x, y, prev_h_left))

        # Predecessor via TURN_RIGHT: previous heading was (h - 1) % 4
        prev_h_right = (h - 1) % 4
        if (x, y, prev_h_right) not in dist:
            dist[(x, y, prev_h_right)] = d + 1
            q.append((x, y, prev_h_right))

        # Predecessor via FORWARD: previous position was (x - dx, y - dy) with heading h
        dx, dy = DELTA[h]
        px, py = x - dx, y - dy
        if (
            0 <= px < SIZE
            and 0 <= py < SIZE
            and layout.terrain[py][px] == FREE
            and (px, py, h) not in dist
        ):
            dist[(px, py, h)] = d + 1
            q.append((px, py, h))

    return dist


def step_to_goal(
    layout: Layout,
    state: State,
    dist: dict[tuple[int, int, int], int],
) -> int:
    """Choose action in PATH_ACTIONS minimizing distance in reverse BFS field."""
    best_action = ACTION_WAIT
    best_dist = dist.get((state.x, state.y, state.heading), 10**9)

    for a in PATH_ACTIONS:
        nxt = step(layout, state, a, k=1)
        d = dist.get((nxt.x, nxt.y, nxt.heading), 10**9)
        if d < best_dist:
            best_dist = d
            best_action = a

    return best_action


def step_with_slip(
    layout: Layout,
    state: State,
    action: int,
    p_slip: float,
    rng: random.Random,
) -> tuple[State, bool, bool]:
    """Execute action with potential silent slip on FORWARD.

    Returns:
        (new_state, slipped, bumped)
        where slipped is True if FORWARD silently failed (agent stayed in place,
        did not bump, not notified).
    """
    if action == ACTION_FORWARD and rng.random() < p_slip:
        # Silent slip: action fails, agent does not move, no bump increment
        return state, True, False

    prev_bumps = state.wall_bumps
    new_state = step(layout, state, action, k=1)
    bumped = new_state.wall_bumps > prev_bumps
    return new_state, False, bumped


def update_odometry(
    est_pose: tuple[float, float, int],
    action: int,
    bumped: bool,
) -> tuple[float, float, int]:
    """Update estimated pose based only on issued action and proprioceptive bump.

    If the agent slips, it issued FORWARD and did not bump, so it accumulates
    odometry drift as specified in §2.
    """
    ex, ey, eh = est_pose

    if action == ACTION_TURN_LEFT:
        eh = (eh - 1) % 4
    elif action == ACTION_TURN_RIGHT:
        eh = (eh + 1) % 4
    elif action == ACTION_FORWARD and not bumped:
        dx, dy = DELTA[eh]
        ex += float(dx)
        ey += float(dy)

    return ex, ey, eh


def _ego_to_world_coords(
    ax: int,
    ay: int,
    heading: int,
    r: int,
    c: int,
) -> tuple[int, int]:
    """Convert ego view cell (r, c) to world coordinates (wx, wy).

    Ego view coordinates: r in 0..6 (ahead is 0..2, behind is 4..6),
    c in 0..6 (left is 0..2, right is 4..6). Center is (3, 3).
    """
    dv = S2_VIEW_RADIUS - r  # longitudinal (+ ahead, - behind)
    du = c - S2_VIEW_RADIUS  # lateral (- left, + right)

    if heading == NORTH:
        return ax + du, ay - dv
    if heading == EAST:
        return ax + dv, ay + du
    if heading == SOUTH:
        return ax - du, ay + dv
    if heading == WEST:
        return ax - dv, ay - du
    raise ValueError(f"Invalid heading: {heading}")


def compute_student_obs(
    layout: Layout,
    state: State,
    last_action: int,
    bumped: bool,
    content_at_step: dict[tuple[int, int], int],
) -> np.ndarray:
    """Compute 198-dimensional student observation vector per DESIGN-r2 §2.

    Components:
    - 3x3 ego view cropped from 7x7 center (rows 2..4, cols 2..4):
      Each cell has:
        - 4-dim one-hot terrain (FREE, WALL, PILLAR, UNSEEN)
        - 17-dim one-hot token (0=NONE, 1..16)
      Total: 9 * 21 = 189 dims.
    - Heading one-hot: 4 dims.
    - Last action one-hot: 4 dims.
    - Wall bump: 1 dim (1.0 if bumped in last step, else 0.0).
    Total: 189 + 4 + 4 + 1 = 198 dims.

    Strictly no absolute coordinates (x, y), ground truth pose, or token swap flags.
    """
    full_ego = compute_ego_view(layout, state.x, state.y, state.heading)

    # Center 3x3 crop from 7x7 (center is r=3, c=3)
    # Rows 2, 3, 4; Columns 2, 3, 4
    view_feats: list[float] = []

    for r in (2, 3, 4):
        for c in (2, 3, 4):
            t_val = full_ego[r][c]

            # 4 terrain one-hot: FREE=0, WALL=1, PILLAR=2, UNSEEN=-1
            # Map UNSEEN (-1) to index 3
            terrain_one_hot = [0.0, 0.0, 0.0, 0.0]
            if t_val == FREE:
                terrain_one_hot[0] = 1.0
            elif t_val == WALL:
                terrain_one_hot[1] = 1.0
            elif t_val == PILLAR:
                terrain_one_hot[2] = 1.0
            else:
                terrain_one_hot[3] = 1.0  # UNSEEN or out-of-bounds

            # 17 token one-hot (0=NONE, 1..16)
            token_one_hot = [0.0] * spec.NUM_TOKEN_CLASSES
            if t_val == UNSEEN:
                # Occluded cell cannot be inspected for token
                token_one_hot[spec.NONE_TOKEN] = 1.0
            else:
                wx, wy = _ego_to_world_coords(state.x, state.y, state.heading, r, c)
                tok = content_at_step.get((wx, wy), spec.NONE_TOKEN)
                if 0 <= tok < spec.NUM_TOKEN_CLASSES:
                    token_one_hot[tok] = 1.0
                else:
                    token_one_hot[spec.NONE_TOKEN] = 1.0

            view_feats.extend(terrain_one_hot)
            view_feats.extend(token_one_hot)

    # Heading one-hot (4 dims)
    heading_one_hot = [0.0] * spec.NUM_HEADINGS
    if 0 <= state.heading < spec.NUM_HEADINGS:
        heading_one_hot[state.heading] = 1.0

    # Last action one-hot (4 dims)
    action_one_hot = [0.0] * spec.NUM_ACTIONS
    if 0 <= last_action < spec.NUM_ACTIONS:
        action_one_hot[last_action] = 1.0

    # Bump proprioception (1 dim)
    bump_feat = [1.0 if bumped else 0.0]

    obs = np.array(
        view_feats + heading_one_hot + action_one_hot + bump_feat,
        dtype=np.float32,
    )
    assert obs.shape == (spec.OBS_DIM,), f"Observation dim mismatch: expected {spec.OBS_DIM}, got {obs.shape}"
    return obs
