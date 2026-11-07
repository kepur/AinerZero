"""S2 evaluation framework: planning episode execution, perturbation, irregular dt, and budgeting.

Pure CPU, NumPy / standard library only. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §2, §4, §5.
"""

from __future__ import annotations

from dataclasses import dataclass
import inspect
import random
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s2.data import K_VALUES, K_WEIGHTS, sample_k
from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded, ForwardCounter
from ainerzero.v9.experiments.s2.world import (
    ACTIONS,
    ACTION_FORWARD,
    ACTION_TURN_LEFT,
    ACTION_TURN_RIGHT,
    ACTION_WAIT,
    DELTA,
    PATH_ACTIONS,
    Layout,
    State,
    compute_ego_view,
    compute_pose_bfs_distances,
    is_success,
    is_success_strict,
    step,
    student_obs,
    truth,
)

__all__ = [
    "EpisodeResult",
    "run_episode",
    "make_oracle_planner",
    "make_random_planner",
]


@dataclass(frozen=True)
class EpisodeResult:
    """Outcome and telemetry of a single evaluated planning episode."""

    success: bool
    strict_success: bool
    steps_used: int
    obs_steps_used: int
    bfs_distance: int
    max_steps: int
    wall_time: float
    decision_counts: list[dict[str, Any]]
    total_forwards: int
    k_history: list[int]
    actions_taken: list[int]
    trajectory: list[dict[str, Any]]
    perturb_applied: bool
    info: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "strict_success": self.strict_success,
            "steps_used": self.steps_used,
            "obs_steps_used": self.obs_steps_used,
            "bfs_distance": self.bfs_distance,
            "max_steps": self.max_steps,
            "wall_time": self.wall_time,
            "decision_counts": self.decision_counts,
            "total_forwards": self.total_forwards,
            "k_history": self.k_history,
            "actions_taken": self.actions_taken,
            "perturb_applied": self.perturb_applied,
            "info": self.info,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]


def _to_state(spec_item: Any) -> State:
    """Convert dict, State, or tuple to State."""
    if isinstance(spec_item, State):
        return spec_item
    if isinstance(spec_item, Mapping):
        return State(
            x=int(spec_item["x"]),
            y=int(spec_item["y"]),
            heading=int(spec_item.get("heading", 0)),
        )
    if isinstance(spec_item, (tuple, list)):
        if len(spec_item) == 2:
            return State(x=int(spec_item[0]), y=int(spec_item[1]), heading=0)
        if len(spec_item) == 3:
            return State(
                x=int(spec_item[0]), y=int(spec_item[1]), heading=int(spec_item[2])
            )
    raise ValueError(f"Cannot convert {spec_item!r} to State")


def _extract_actions(plan_res: Any) -> list[int]:
    """Extract a list of integer action codes from various plan_fn return types."""
    if hasattr(plan_res, "actions"):
        raw = plan_res.actions
    else:
        raw = plan_res

    if isinstance(raw, (int, np.integer)):
        return [int(raw)]

    if isinstance(raw, (list, tuple)):
        out = []
        for a in raw:
            if isinstance(a, (int, np.integer)):
                out.append(int(a))
            elif isinstance(a, (list, tuple, np.ndarray)):
                arr = np.asarray(a).reshape(-1)
                out.append(int(arr[0]))
            else:
                out.append(int(a))
        return out

    if isinstance(raw, np.ndarray):
        arr = raw.reshape(-1)
        return [int(a) for a in arr]

    raise TypeError(f"Unrecognized plan_res action format: {type(plan_res)}")


def _call_plan_fn(
    plan_fn: Callable[..., Any],
    *,
    obs: dict[str, Any],
    goal_obs: dict[str, Any],
    k: int,
    counter: ForwardCounter | None,
    rng: np.random.Generator,
    state: State,
    layout: Layout,
) -> Any:
    """Call plan_fn with signature inspection and graceful fallback."""
    sig = inspect.signature(plan_fn)
    params = sig.parameters
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())

    kwargs: dict[str, Any] = {}
    if "obs" in params or has_varkw:
        kwargs["obs"] = obs
    if "goal_obs" in params or has_varkw:
        kwargs["goal_obs"] = goal_obs
    if "k" in params or has_varkw:
        kwargs["k"] = k
    if "dt" in params or has_varkw:
        kwargs["dt"] = k
    if "counter" in params or has_varkw:
        kwargs["counter"] = counter
    if "rng" in params or has_varkw:
        kwargs["rng"] = rng
    if "state" in params or has_varkw:
        kwargs["state"] = state
    if "truth_state" in params or has_varkw:
        kwargs["truth_state"] = truth(state)
    if "layout" in params or has_varkw:
        kwargs["layout"] = layout

    try:
        return plan_fn(**kwargs)
    except TypeError:
        # Fallback to positional invocation
        return plan_fn(obs, goal_obs)


def run_episode(
    layout: Layout,
    spec: Mapping[str, Any],
    plan_fn: Callable[..., Any],
    counter: ForwardCounter | None,
    rng: Any,
    dt_mode: str = "irregular",
    m: int = 4,
    *,
    max_steps: int | None = None,
) -> EpisodeResult:
    """Execute a single evaluated planning episode.

    Args:
        layout: GridLab-S2 layout instance.
        spec: Episode specification containing start, goal, bfs_distance, perturb flag.
        plan_fn: Planner callable invoked at decision steps.
        counter: ForwardCounter instance for tracking/budgeting network evaluations.
        rng: Random generator or seed (int, np.random.Generator, or random.Random).
        dt_mode: "irregular" (k drawn from {1:0.5, 2:0.3, 3:0.2}) or "regular" (k ≡ 1).
        m: Number of observation steps executed per planning decision (default 4).
        max_steps: Maximum primitive action steps allowed (default L = 3 * bfs_distance).

    Returns:
        EpisodeResult containing success status, step counts, forward counters, and telemetry.
    """
    if dt_mode not in ("irregular", "regular"):
        raise ValueError(f"dt_mode must be 'irregular' or 'regular', got {dt_mode!r}")
    if m < 1:
        raise ValueError(f"m must be >= 1, got {m}")

    # Initialize ForwardCounter for this episode
    if counter is not None:
        counter.begin_episode()

    t0 = time.perf_counter()

    # Parse state and goal
    start_state = _to_state(spec["start"])
    goal_state = _to_state(spec["goal"])
    bfs_distance = int(spec["bfs_distance"])
    limit_steps = max_steps if max_steps is not None else (3 * bfs_distance)

    # Goal observation
    if "goal_obs" in spec and spec["goal_obs"] is not None:
        goal_obs = dict(spec["goal_obs"])
    else:
        v = compute_ego_view(layout, goal_state.x, goal_state.y, goal_state.heading)
        goal_obs = {
            "view": v,
            "heading": [1 if i == goal_state.heading else 0 for i in range(4)],
        }

    # Perturbation spec (dev/final 1/3 long goals)
    perturb = bool(spec.get("perturb", False))
    perturb_spec = spec.get("perturb_spec") or {}
    perturb_at_step = int(perturb_spec.get("at_step", 20))
    n_perturb_actions = int(perturb_spec.get("n_random_actions", 5))

    # Initialize independent RNG streams
    if isinstance(rng, (int, np.integer)):
        seed_val = int(rng)
        env_rng = random.Random(seed_val)
        plan_rng = np.random.default_rng(seed_val)
        perturb_rng = random.Random(seed_val + 99991)
    elif isinstance(rng, np.random.Generator):
        seed_val = int(rng.integers(0, 2**31 - 1))
        env_rng = random.Random(seed_val)
        plan_rng = rng
        perturb_rng = random.Random(seed_val + 99991)
    elif isinstance(rng, random.Random):
        seed_val = rng.randint(0, 2**31 - 1)
        env_rng = rng
        plan_rng = np.random.default_rng(seed_val)
        perturb_rng = random.Random(seed_val + 99991)
    else:
        raise TypeError(f"Unsupported rng type: {type(rng)}")

    state = start_state
    steps_used = 0
    obs_steps_used = 0
    last_action = ACTION_WAIT
    last_dt = 1
    perturbed = False

    decision_counts: list[dict[str, Any]] = []
    actions_taken: list[int] = []
    k_history: list[int] = []
    trajectory: list[dict[str, Any]] = [truth(state)]

    # Initial check: already at goal?
    if state.x == goal_state.x and state.y == goal_state.y:
        wall_time = time.perf_counter() - t0
        succ = is_success(truth(state), goal_state, steps_used, bfs_distance)
        succ_strict = is_success_strict(truth(state), goal_state, steps_used, bfs_distance)
        return EpisodeResult(
            success=succ,
            strict_success=succ_strict,
            steps_used=steps_used,
            obs_steps_used=obs_steps_used,
            bfs_distance=bfs_distance,
            max_steps=limit_steps,
            wall_time=wall_time,
            decision_counts=decision_counts,
            total_forwards=0,
            k_history=k_history,
            actions_taken=actions_taken,
            trajectory=trajectory,
            perturb_applied=perturbed,
            info={"initial_at_goal": True},
        )

    # Main episode loop
    while steps_used < limit_steps:
        # Pre-sample k for the first observation step of this decision
        if dt_mode == "regular":
            k_next = 1
        else:
            k_next = sample_k(env_rng)

        obs = student_obs(layout, state, last_action=last_action, dt=last_dt)

        # Reset per-decision counter before planning
        if counter is not None:
            counter.reset()

        plan_res = _call_plan_fn(
            plan_fn,
            obs=obs,
            goal_obs=goal_obs,
            k=k_next,
            counter=counter,
            rng=plan_rng,
            state=state,
            layout=layout,
        )

        if counter is not None:
            decision_counts.append(counter.snapshot())

        actions = _extract_actions(plan_res)

        # Execute up to m observation steps for this decision
        for step_i in range(m):
            if steps_used >= limit_steps:
                break

            if step_i == 0:
                k = k_next
            else:
                if dt_mode == "regular":
                    k = 1
                else:
                    k = sample_k(env_rng)

            k_history.append(k)
            action = actions[step_i] if step_i < len(actions) else ACTION_WAIT

            # Execute action for k primitive steps
            goal_reached_in_k = False
            for _ in range(k):
                state = step(layout, state, action, k=1)
                steps_used += 1
                actions_taken.append(action)
                trajectory.append(truth(state))

                if state.x == goal_state.x and state.y == goal_state.y:
                    goal_reached_in_k = True
                    break

                # Perturbation check: exactly at step 20
                if perturb and not perturbed and steps_used == perturb_at_step:
                    perturbed = True
                    for _ in range(n_perturb_actions):
                        rand_a = perturb_rng.choice(ACTIONS)
                        state = step(layout, state, rand_a, k=1)
                        steps_used += 1
                        actions_taken.append(rand_a)
                        trajectory.append(truth(state))
                        if state.x == goal_state.x and state.y == goal_state.y:
                            goal_reached_in_k = True
                            break
                    # Immediate replanning triggered by perturbation
                    break

            last_action = action
            last_dt = k
            obs_steps_used += 1

            if goal_reached_in_k:
                break

            # If perturbation occurred during this observation step, break decision to replan
            if perturbed and steps_used >= perturb_at_step and (steps_used - n_perturb_actions <= perturb_at_step):
                break

        # Check if agent reached goal cell
        if state.x == goal_state.x and state.y == goal_state.y:
            break

    wall_time = time.perf_counter() - t0
    succ = is_success(truth(state), goal_state, steps_used, bfs_distance)
    succ_strict = is_success_strict(truth(state), goal_state, steps_used, bfs_distance)
    total_fwd = sum(int(d.get("total", 0)) for d in decision_counts)

    return EpisodeResult(
        success=succ,
        strict_success=succ_strict,
        steps_used=steps_used,
        obs_steps_used=obs_steps_used,
        bfs_distance=bfs_distance,
        max_steps=limit_steps,
        wall_time=wall_time,
        decision_counts=decision_counts,
        total_forwards=total_fwd,
        k_history=k_history,
        actions_taken=actions_taken,
        trajectory=trajectory,
        perturb_applied=perturbed,
        info={
            "final_state": truth(state),
            "target_state": truth(goal_state),
            "wall_bumps": state.wall_bumps,
        },
    )


def make_oracle_planner(
    layout: Layout,
    goal: Any,
    m: int = 4,
) -> Callable[..., list[int]]:
    """Construct an oracle planner using exact pose-BFS on the ground-truth map.

    Returns a callable plan_fn(obs, goal_obs, state=...) that returns m actions.
    """
    import collections

    goal_state = _to_state(goal)
    goal_key = (goal_state.x, goal_state.y, goal_state.heading)

    def oracle_plan(
        obs: dict[str, Any],
        goal_obs: dict[str, Any],
        state: State | None = None,
        **kwargs: Any,
    ) -> list[int]:
        if state is None:
            raise ValueError("oracle_planner requires ground-truth state")

        start_key = (state.x, state.y, state.heading)
        if start_key == goal_key or (state.x == goal_state.x and state.y == goal_state.y):
            return [ACTION_WAIT] * m

        queue = collections.deque([start_key])
        parent: dict[tuple[int, int, int], tuple[tuple[int, int, int], int] | tuple[None, int]] = {
            start_key: (None, -1)
        }
        target_found: tuple[int, int, int] | None = None

        while queue:
            x, y, h = queue.popleft()
            if x == goal_state.x and y == goal_state.y and h == goal_state.heading:
                target_found = (x, y, h)
                break
            base = State(x=x, y=y, heading=h)
            for a in PATH_ACTIONS:
                nxt = step(layout, base, a, k=1)
                nxt_key = (nxt.x, nxt.y, nxt.heading)
                if nxt_key not in parent:
                    parent[nxt_key] = ((x, y, h), a)
                    queue.append(nxt_key)

        if target_found is None:
            for x, y, h in parent:
                if x == goal_state.x and y == goal_state.y:
                    target_found = (x, y, h)
                    break

        if target_found is None:
            return [ACTION_WAIT] * m

        # Reconstruct path
        curr = target_found
        actions: list[int] = []
        while curr != start_key:
            prev, a = parent[curr]
            assert prev is not None
            actions.append(a)
            curr = prev
        actions.reverse()

        if len(actions) < m:
            actions = actions + [ACTION_WAIT] * (m - len(actions))
        return actions[:m]

    return oracle_plan


def make_random_planner(
    m: int = 4,
    rng: np.random.Generator | int | None = None,
) -> Callable[..., list[int]]:
    """Construct a uniform random planner for baseline / negative comparisons."""
    if rng is None:
        np_rng = np.random.default_rng()
    elif isinstance(rng, (int, np.integer)):
        np_rng = np.random.default_rng(int(rng))
    elif isinstance(rng, np.random.Generator):
        np_rng = rng
    else:
        raise TypeError("rng must be an int, np.random.Generator, or None")

    def random_plan(obs: dict[str, Any], goal_obs: dict[str, Any], **kwargs: Any) -> list[int]:
        return [int(a) for a in np_rng.choice(list(ACTIONS), size=m)]

    return random_plan
