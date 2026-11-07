"""GridLab-S2: Multi-room grid world for S2 multi-timescale experiments.

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2 (r2.1 pose-BFS).
"""

from __future__ import annotations

import collections
from dataclasses import dataclass
import hashlib
import json
import random
from typing import Any, Sequence

SIZE = 25
VIEW_SIZE = 7
VIEW_RADIUS = 3

# Terrain types
FREE = 0
WALL = 1
PILLAR = 2
UNSEEN = -1

OPAQUE = {WALL, PILLAR}

# Headings: 0=NORTH, 1=EAST, 2=SOUTH, 3=WEST
NORTH = 0
EAST = 1
SOUTH = 2
WEST = 3

DELTA: dict[int, tuple[int, int]] = {
    NORTH: (0, -1),
    EAST: (1, 0),
    SOUTH: (0, 1),
    WEST: (-1, 0),
}

# Actions: 0=FORWARD, 1=TURN_LEFT, 2=TURN_RIGHT, 3=WAIT
ACTION_FORWARD = 0
ACTION_TURN_LEFT = 1
ACTION_TURN_RIGHT = 2
ACTION_WAIT = 3
ACTIONS = (ACTION_FORWARD, ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT)
# Path-planning actions exclude WAIT (r2.1 pose BFS)
PATH_ACTIONS = (ACTION_FORWARD, ACTION_TURN_LEFT, ACTION_TURN_RIGHT)

LONG_GOAL_MIN_DIST = 40
SHORT_GOAL_MAX_DIST = 10
WORLD_REJECTION_RATE_THRESHOLD = 0.30
WORLD_REDRAW_MAX = 5
LONG_PAIRS_PER_WORLD = 6

# Mutation sentinel (P115-M6): must stay False in production — no silent distance fallback.
_ALLOW_LONG_DISTANCE_FALLBACK = False


@dataclass(frozen=True)
class Layout:
    seed: int
    terrain: list[list[int]]  # 25x25 grid, integers
    rooms: list[tuple[int, int, int, int]]  # 9 rooms: (min_x, min_y, max_x, max_y)
    doors: list[tuple[int, int]]
    pillars: list[tuple[int, int]]
    layout_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "size": SIZE,
            "terrain": self.terrain,
            "rooms": [list(r) for r in self.rooms],
            "doors": sorted([list(d) for d in self.doors]),
            "pillars": sorted([list(p) for p in self.pillars]),
            "layout_sha256": self.layout_sha256,
        }


@dataclass(frozen=True)
class State:
    x: int
    y: int
    heading: int
    wall_bumps: int = 0


def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:
    """算法参照 GridLab-v1 的 line_of_sight（ainerzero.environments 中的 GridLab-v1 模块）。"""
    if ax == bx and ay == by:
        return True
    n = max(abs(bx - ax), abs(by - ay))
    for i in range(1, n):
        fx = ax + (bx - ax) * i / n
        fy = ay + (by - ay) * i / n
        cells = {
            (int(fx + 0.5 - 1e-9), int(fy + 0.5 - 1e-9)),
            (int(fx + 0.5), int(fy + 0.5)),
        }
        if all(
            not (0 <= cx < SIZE and 0 <= cy < SIZE) or terrain[cy][cx] in OPAQUE
            for cx, cy in cells
        ):
            return False
    return True


def make_layout(seed: int, *, max_attempts: int = 100, enforce_connected: bool = True) -> Layout:
    """Generate a 25x25 3x3 multi-room layout with doors, pillars, and BFS connectivity check.

    Connectivity redraw rule: if the FREE subgraph is not fully connected, retry with
    rng seeded by ``seed + attempt * 10007`` up to ``max_attempts`` times, then raise.
    """
    for attempt in range(max_attempts):
        rng = random.Random(seed + attempt * 10007)
        terrain = [[WALL for _ in range(SIZE)] for _ in range(SIZE)]

        room_bounds_1d = [(1, 7), (9, 15), (17, 23)]
        rooms: list[tuple[int, int, int, int]] = []
        for ry in range(3):
            for rx in range(3):
                min_x, max_x = room_bounds_1d[rx]
                min_y, max_y = room_bounds_1d[ry]
                rooms.append((min_x, min_y, max_x, max_y))
                for y in range(min_y, max_y + 1):
                    for x in range(min_x, max_x + 1):
                        terrain[y][x] = FREE

        doors: list[tuple[int, int]] = []

        # Horizontal adjacencies (separating vertical walls at col 8 and 16)
        for ry in range(3):
            min_y, max_y = room_bounds_1d[ry]
            for sep_x in (8, 16):
                n_doors = rng.choice([1, 2])
                y_choices = rng.sample(list(range(min_y, max_y + 1)), n_doors)
                for dy in y_choices:
                    terrain[dy][sep_x] = FREE
                    doors.append((sep_x, dy))

        # Vertical adjacencies (separating horizontal walls at row 8 and 16)
        for rx in range(3):
            min_x, max_x = room_bounds_1d[rx]
            for sep_y in (8, 16):
                n_doors = rng.choice([1, 2])
                x_choices = rng.sample(list(range(min_x, max_x + 1)), n_doors)
                for dx in x_choices:
                    terrain[sep_y][dx] = FREE
                    doors.append((dx, sep_y))

        # In each room, place 0-3 pillars inside interior
        pillars: list[tuple[int, int]] = []
        for min_x, min_y, max_x, max_y in rooms:
            n_pillars = rng.choice([0, 1, 2, 3])
            interior_cells = [
                (x, y)
                for y in range(min_y, max_y + 1)
                for x in range(min_x, max_x + 1)
            ]
            if n_pillars > 0:
                chosen = rng.sample(interior_cells, n_pillars)
                for px, py in chosen:
                    terrain[py][px] = PILLAR
                    pillars.append((px, py))

        if enforce_connected:
            free_cells = [
                (x, y)
                for y in range(SIZE)
                for x in range(SIZE)
                if terrain[y][x] == FREE
            ]
            if not free_cells:
                continue

            start_cell = free_cells[0]
            queue = collections.deque([start_cell])
            visited = {start_cell}
            while queue:
                cx, cy = queue.popleft()
                for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < SIZE and 0 <= ny < SIZE and terrain[ny][nx] == FREE:
                        if (nx, ny) not in visited:
                            visited.add((nx, ny))
                            queue.append((nx, ny))

            if len(visited) != len(free_cells):
                continue

        raw_dict = {
            "seed": seed,
            "size": SIZE,
            "terrain": terrain,
            "doors": sorted(doors),
            "pillars": sorted(pillars),
        }
        raw_canonical = json.dumps(raw_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
        layout_sha256 = hashlib.sha256(raw_canonical).hexdigest()

        return Layout(
            seed=seed,
            terrain=terrain,
            rooms=rooms,
            doors=doors,
            pillars=pillars,
            layout_sha256=layout_sha256,
        )

    raise RuntimeError(
        f"make_layout failed to generate a connected layout within {max_attempts} attempts for seed {seed}"
    )


def step(layout: Layout, state: State, action: int, k: int = 1) -> State:
    """Step pure function. Repeats action k times. Wall bump increments counter."""
    cur_x, cur_y, cur_h = state.x, state.y, state.heading
    bumps = state.wall_bumps

    for _ in range(k):
        if action == ACTION_FORWARD:
            dx, dy = DELTA[cur_h]
            nx, ny = cur_x + dx, cur_y + dy
            if 0 <= nx < SIZE and 0 <= ny < SIZE and layout.terrain[ny][nx] == FREE:
                cur_x, cur_y = nx, ny
            else:
                bumps += 1
        elif action == ACTION_TURN_LEFT:
            cur_h = (cur_h - 1) % 4
        elif action == ACTION_TURN_RIGHT:
            cur_h = (cur_h + 1) % 4
        elif action == ACTION_WAIT:
            pass
        else:
            raise ValueError(f"Unknown action: {action}")

    return State(x=cur_x, y=cur_y, heading=cur_h, wall_bumps=bumps)


def compute_ego_view(
    layout: Layout,
    ax: int,
    ay: int,
    heading: int,
    *,
    force_all_visible: bool = False,
) -> list[list[int]]:
    """Compute 7x7 egocentric view rotated by heading.

    Center is (3, 3) representing the agent.
    Ahead is upwards (row 0 to 2), behind is downwards (row 4 to 6).
    Left is columns 0 to 2, right is columns 4 to 6.
    """
    view = [[UNSEEN for _ in range(VIEW_SIZE)] for _ in range(VIEW_SIZE)]

    for r in range(VIEW_SIZE):
        dv = VIEW_RADIUS - r  # longitudinal (+ ahead, - behind)
        for c in range(VIEW_SIZE):
            du = c - VIEW_RADIUS  # lateral (- left, + right)

            if heading == NORTH:
                wx = ax + du
                wy = ay - dv
            elif heading == EAST:
                wx = ax + dv
                wy = ay + du
            elif heading == SOUTH:
                wx = ax - du
                wy = ay + dv
            elif heading == WEST:
                wx = ax - dv
                wy = ay - du
            else:
                raise ValueError(f"Invalid heading: {heading}")

            if not (0 <= wx < SIZE and 0 <= wy < SIZE):
                if force_all_visible or line_of_sight(layout.terrain, ax, ay, wx, wy):
                    view[r][c] = WALL
                else:
                    view[r][c] = UNSEEN
            else:
                if force_all_visible or line_of_sight(layout.terrain, ax, ay, wx, wy):
                    view[r][c] = layout.terrain[wy][wx]
                else:
                    view[r][c] = UNSEEN

    return view


def student_obs(
    layout: Layout,
    state: State,
    last_action: int,
    dt: int,
    *,
    force_all_visible: bool = False,
    leak_coordinates: bool = False,
) -> dict[str, Any]:
    """Student observation: strictly no absolute coordinates."""
    view = compute_ego_view(
        layout,
        state.x,
        state.y,
        state.heading,
        force_all_visible=force_all_visible,
    )
    heading_one_hot = [1 if i == state.heading else 0 for i in range(4)]
    action_one_hot = [1 if i == last_action else 0 for i in range(4)]

    obs: dict[str, Any] = {
        "view": view,
        "heading": heading_one_hot,
        "last_action": action_one_hot,
        "dt": dt,
    }
    if leak_coordinates:
        # Used for mutation test P115-M1
        obs["x"] = state.x
        obs["y"] = state.y
    return obs


def truth(state: State) -> dict[str, Any]:
    """Evaluation / teacher side ground truth pose."""
    return {
        "x": state.x,
        "y": state.y,
        "heading": state.heading,
        "wall_bumps": state.wall_bumps,
    }


def _as_state(start: tuple[int, ...] | State) -> State:
    if isinstance(start, State):
        return start
    if len(start) == 2:
        return State(x=int(start[0]), y=int(start[1]), heading=NORTH)
    if len(start) == 3:
        return State(x=int(start[0]), y=int(start[1]), heading=int(start[2]))
    raise ValueError(f"Unsupported start specification: {start!r}")


def _pose_key(state: State) -> tuple[int, int, int]:
    return (state.x, state.y, state.heading)


def compute_bfs_distances(layout: Layout, start_x: int, start_y: int) -> dict[tuple[int, int], int]:
    """Cell-graph BFS (floor adjacency). Kept for connectivity / legacy helpers."""
    distances: dict[tuple[int, int], int] = {(start_x, start_y): 0}
    queue = collections.deque([(start_x, start_y)])
    while queue:
        cx, cy = queue.popleft()
        d = distances[(cx, cy)]
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < SIZE and 0 <= ny < SIZE and layout.terrain[ny][nx] == FREE:
                if (nx, ny) not in distances:
                    distances[(nx, ny)] = d + 1
                    queue.append((nx, ny))
    return distances


def compute_pose_bfs_distances(
    layout: Layout,
    start: tuple[int, ...] | State,
) -> dict[tuple[int, int, int], int]:
    """r2.1: shortest path on the pose graph (x, y, heading) using FORWARD/LEFT/RIGHT.

    Distance is counted in action steps (turns cost 1). WAIT is excluded.
    """
    start_state = _as_state(start)
    if layout.terrain[start_state.y][start_state.x] != FREE:
        raise ValueError(f"Start pose not on FREE cell: {_pose_key(start_state)}")

    start_key = _pose_key(start_state)
    distances: dict[tuple[int, int, int], int] = {start_key: 0}
    queue: collections.deque[tuple[int, int, int]] = collections.deque([start_key])
    while queue:
        x, y, h = queue.popleft()
        d = distances[(x, y, h)]
        base = State(x=x, y=y, heading=h)
        for action in PATH_ACTIONS:
            nxt = step(layout, base, action, k=1)
            key = _pose_key(nxt)
            if key not in distances:
                distances[key] = d + 1
                queue.append(key)
    return distances


_CACHE_VIEWS: dict[
    str, tuple[dict[tuple[int, int, int], tuple[tuple[int, ...], ...]], collections.Counter]
] = {}


def get_layout_view_counts(
    layout: Layout,
) -> tuple[dict[tuple[int, int, int], tuple[tuple[int, ...], ...]], collections.Counter]:
    """Precompute and index all ego-views across all floor poses in layout."""
    cache_key = layout.layout_sha256
    if cache_key in _CACHE_VIEWS:
        return _CACHE_VIEWS[cache_key]

    all_poses = [
        (x, y, h)
        for y in range(SIZE)
        for x in range(SIZE)
        if layout.terrain[y][x] == FREE
        for h in range(4)
    ]
    pose_views: dict[tuple[int, int, int], tuple[tuple[int, ...], ...]] = {}
    for x, y, h in all_poses:
        v = tuple(tuple(row) for row in compute_ego_view(layout, x, y, h))
        pose_views[(x, y, h)] = v

    counts = collections.Counter(pose_views.values())
    res = (pose_views, counts)
    _CACHE_VIEWS[cache_key] = res
    return res


def is_goal_ambiguous(
    layout: Layout,
    gx: int,
    gy: int,
    gheading: int,
    all_free_poses: list[tuple[int, int, int]] | None = None,
) -> bool:
    """True if there is another pose in the world that produces the exact same 7x7 view."""
    del all_free_poses  # API compatibility; full-layout index is authoritative
    views, counts = get_layout_view_counts(layout)
    v = views.get((gx, gy, gheading))
    if v is None:
        v = tuple(tuple(row) for row in compute_ego_view(layout, gx, gy, gheading))
    return counts[v] > 1


def world_rejection_requires_redraw(
    rejection_rate: float,
    *,
    threshold: float = WORLD_REJECTION_RATE_THRESHOLD,
    enforce: bool = True,
) -> bool:
    """r2: redraw the whole world when per-world ambiguity rejection rate exceeds threshold."""
    if not enforce:
        return False
    return rejection_rate > threshold


def is_success(
    truth_pose: dict[str, Any] | State,
    goal: dict[str, Any] | State,
    steps_used: int,
    bfs_dist: int,
) -> bool:
    """Arrive at goal cell within 3× pose-BFS steps; heading not required."""
    if isinstance(truth_pose, State):
        tx, ty = truth_pose.x, truth_pose.y
    else:
        tx, ty = int(truth_pose["x"]), int(truth_pose["y"])
    if isinstance(goal, State):
        gx, gy = goal.x, goal.y
    else:
        gx, gy = int(goal["x"]), int(goal["y"])
    if tx != gx or ty != gy:
        return False
    return steps_used <= 3 * int(bfs_dist)


def is_success_strict(
    truth_pose: dict[str, Any] | State,
    goal: dict[str, Any] | State,
    steps_used: int,
    bfs_dist: int,
) -> bool:
    """Strict success: cell + heading, still within 3× pose-BFS steps."""
    if not is_success(truth_pose, goal, steps_used, bfs_dist):
        return False
    if isinstance(truth_pose, State):
        th = truth_pose.heading
    else:
        th = int(truth_pose["heading"])
    if isinstance(goal, State):
        gh = goal.heading
    else:
        gh = int(goal["heading"])
    return th == gh


def sample_goal(
    layout: Layout,
    start: tuple[int, ...] | State,
    rng: random.Random,
    kind: str = "long",
    *,
    enforce_unambiguous: bool = True,
    max_attempts: int = 500,
) -> tuple[State, dict[str, Any], dict[str, Any]]:
    """Sample a goal pose relative to a fixed start.

    Distance uses r2.1 pose-BFS (action steps). **No distance fallback**: if no
    candidate poses satisfy the distance band, raises RuntimeError.
    """
    start_state = _as_state(start)
    distances = compute_pose_bfs_distances(layout, start_state)
    views, counts = get_layout_view_counts(layout)

    if kind == "long":
        candidate_poses = [pose for pose, d in distances.items() if d >= LONG_GOAL_MIN_DIST]
        if not candidate_poses:
            if _ALLOW_LONG_DISTANCE_FALLBACK:
                # Intentionally dead in production; mutation P115-M6 re-enables this path.
                positive = [(pose, d) for pose, d in distances.items() if d > 0]
                if positive:
                    max_d_u = max(d for _, d in positive)
                    candidate_poses = [
                        pose for pose, d in positive if d >= max(max_d_u - 4, 1)
                    ]
            if not candidate_poses:
                raise RuntimeError(
                    f"No long-goal pose with pose-BFS >= {LONG_GOAL_MIN_DIST} "
                    f"from start {_pose_key(start_state)}; no fallback permitted"
                )
    elif kind == "short":
        candidate_poses = [
            pose for pose, d in distances.items() if 0 < d <= SHORT_GOAL_MAX_DIST
        ]
        if not candidate_poses:
            raise RuntimeError(
                f"No short-goal pose with 0 < pose-BFS <= {SHORT_GOAL_MAX_DIST} "
                f"from start {_pose_key(start_state)}"
            )
    else:
        raise ValueError(f"Unknown goal kind: {kind} (must be 'long' or 'short')")

    attempts = 0
    rejections = 0

    while attempts < max_attempts:
        attempts += 1
        gx, gy, gh = rng.choice(candidate_poses)

        v = views.get((gx, gy, gh))
        if v is None:
            v = tuple(tuple(row) for row in compute_ego_view(layout, gx, gy, gh))

        if enforce_unambiguous:
            if counts[v] > 1:
                rejections += 1
                continue

        goal_state = State(x=gx, y=gy, heading=gh)
        goal_obs = {
            "view": [list(row) for row in v],
            "heading": [1 if i == gh else 0 for i in range(4)],
        }
        stats = {
            "kind": kind,
            "bfs_distance": distances[(gx, gy, gh)],
            "distance_metric": "pose_action_bfs",
            "attempts": attempts,
            "rejections": rejections,
            "rejection_rate": rejections / attempts if attempts > 0 else 0.0,
            "fallback_used": False,
        }
        return goal_state, goal_obs, stats

    raise RuntimeError(
        f"Failed to find an unambiguous goal after {max_attempts} attempts (kind={kind})"
    )


def sample_start_goal_pair(
    layout: Layout,
    rng: random.Random,
    kind: str = "long",
    *,
    enforce_unambiguous: bool = True,
    max_pair_attempts: int = 200,
) -> tuple[State, State, dict[str, Any], dict[str, Any]]:
    """r2.1 joint (start, goal) draw. Raises if no qualifying unambiguous pair exists."""
    free_cells = [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if layout.terrain[y][x] == FREE
    ]
    if not free_cells:
        raise RuntimeError("Layout has no FREE cells")

    total_rejections = 0
    total_attempts = 0

    for _ in range(max_pair_attempts):
        sx, sy = rng.choice(free_cells)
        sh = rng.choice([NORTH, EAST, SOUTH, WEST])
        start = State(x=sx, y=sy, heading=sh)
        try:
            goal, goal_obs, stats = sample_goal(
                layout,
                start,
                rng,
                kind=kind,
                enforce_unambiguous=enforce_unambiguous,
                max_attempts=80,
            )
        except RuntimeError:
            continue
        total_rejections += int(stats["rejections"])
        total_attempts += int(stats["attempts"])
        pair_stats = {
            **stats,
            "pair_rejections": total_rejections,
            "pair_attempts": total_attempts,
            "rejection_rate": (total_rejections / total_attempts) if total_attempts else 0.0,
        }
        return start, goal, goal_obs, pair_stats

    raise RuntimeError(
        f"Failed to jointly sample an unambiguous {kind} (start, goal) pair "
        f"after {max_pair_attempts} start draws"
    )


def prepare_world_with_long_pairs(
    seed: int,
    rng: random.Random,
    *,
    n_long_pairs: int = LONG_PAIRS_PER_WORLD,
    max_world_redraws: int = WORLD_REDRAW_MAX,
    rejection_threshold: float = WORLD_REJECTION_RATE_THRESHOLD,
    enforce_rejection_redraw: bool = True,
) -> tuple[Layout, list[dict[str, Any]], dict[str, Any]]:
    """Build a layout that admits ``n_long_pairs`` unambiguous long pairs.

    Shares the redraw budget between (a) failure to collect enough pairs and
    (b) per-world ambiguity rejection_rate > threshold (r2).
    """
    world_redraws = 0
    last_error = "no attempt"

    for attempt in range(max_world_redraws):
        layout_seed = seed + attempt * 10007
        layout = make_layout(layout_seed)
        pairs: list[dict[str, Any]] = []
        rej_sum = 0
        att_sum = 0
        failed = False

        for _ in range(n_long_pairs):
            try:
                start, goal, goal_obs, stats = sample_start_goal_pair(
                    layout, rng, kind="long"
                )
            except RuntimeError as exc:
                last_error = str(exc)
                failed = True
                break
            rej_sum += int(stats["rejections"])
            att_sum += int(stats["attempts"])
            pairs.append(
                {
                    "start": truth(start),
                    "goal": truth(goal),
                    "goal_obs": goal_obs,
                    "bfs_distance": stats["bfs_distance"],
                }
            )

        if failed or len(pairs) < n_long_pairs:
            world_redraws += 1
            continue

        rejection_rate = (rej_sum / att_sum) if att_sum else 0.0
        if world_rejection_requires_redraw(
            rejection_rate,
            threshold=rejection_threshold,
            enforce=enforce_rejection_redraw,
        ):
            world_redraws += 1
            last_error = f"rejection_rate {rejection_rate:.3f} > {rejection_threshold}"
            continue

        summary = {
            "layout_seed": layout_seed,
            "world_redraws": world_redraws,
            "rejection_rate": rejection_rate,
            "rejection_attempts": att_sum,
            "rejection_count": rej_sum,
            "n_long_pairs": len(pairs),
        }
        return layout, pairs, summary

    raise RuntimeError(
        f"prepare_world_with_long_pairs failed after {max_world_redraws} redraws "
        f"(seed={seed}): {last_error}"
    )
