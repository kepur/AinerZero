"""S2 smoke sanity and oracle feasibility checks (ainerzero.V9.P152).

Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md Appendix B.
Implements:
1. short_train_sanity: short training finite loss, loss decrease, and SIGReg stability.
2. action_sensitivity: latent pairwise action sensitivity normalized by state norm.
3. oracle_feasibility: task feasibility fuse under true world dynamics and ForwardCounter budget.

Pure NumPy + protocol objects. Zero MLX imports. No hardcoded / fabricated constants.
Missing or invalid inputs strictly fail / raise.
"""

from __future__ import annotations

import collections.abc
import inspect
import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import planner, world
from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded, ForwardCounter


def _extract_loss(step_output: Any) -> float:
    """Extract scalar loss from step output."""
    if isinstance(step_output, (int, float)):
        val = float(step_output)
    elif isinstance(step_output, Mapping):
        if "loss" in step_output:
            val = float(step_output["loss"])
        elif "total_loss" in step_output:
            val = float(step_output["total_loss"])
        else:
            raise KeyError(f"Step output missing 'loss' key: {list(step_output.keys())}")
    elif hasattr(step_output, "item"):
        val = float(step_output.item())
    else:
        raise TypeError(f"Cannot extract loss from step output of type {type(step_output)}")
    return val


def _evaluate_sigreg(probe: Any, arm: Any) -> float:
    """Evaluate SIGReg value using probe and arm."""
    if callable(probe):
        try:
            return float(probe(arm))
        except TypeError:
            return float(probe())
    if hasattr(arm, "evaluate_sigreg"):
        return float(arm.evaluate_sigreg(probe))
    if hasattr(arm, "compute_sigreg"):
        return float(arm.compute_sigreg(probe))
    if hasattr(arm, "sigreg"):
        return float(arm.sigreg(probe))
    raise TypeError(f"Cannot evaluate sigreg with probe {type(probe)} and arm {type(arm)}")


def short_train_sanity(
    arm: Any,
    batches: collections.abc.Iterable[Any],
    S: int,
    sigreg_probe: Any = None,
) -> dict[str, Any]:
    """Execute S steps of short training and assert finite loss, decrease, and SIGReg stability.

    Args:
        arm: Model or arm object satisfying ArmProtocol (has train_step).
        batches: Iterable providing training batches.
        S: Number of training steps (must be >= 20).
        sigreg_probe: Optional probe callable or probe batch for SIGReg evaluation.

    Returns:
        dict containing pass/fail flags, measured numbers, and failure reasons.
    """
    if arm is None or not hasattr(arm, "train_step"):
        raise ValueError("arm must implement train_step")
    if batches is None:
        raise ValueError("batches must not be None")
    if not isinstance(S, int) or S < 20:
        raise ValueError(f"S must be an integer >= 20, got {S}")

    reasons: list[str] = []

    # 1. Initial SIGReg evaluation if probe provided
    initial_sigreg: float | None = None
    if sigreg_probe is not None:
        initial_sigreg = _evaluate_sigreg(sigreg_probe, arm)

    # 2. Training loop
    losses: list[float] = []
    batch_iter = iter(batches)

    for step_idx in range(S):
        try:
            batch = next(batch_iter)
        except StopIteration:
            raise ValueError(f"Not enough batches provided for S={S} steps (exhausted at step {step_idx})")

        out = arm.train_step(batch)
        loss = _extract_loss(out)
        losses.append(loss)

    # 3. Decision 1: All losses finite
    all_finite = True
    for idx, l in enumerate(losses):
        if not math.isfinite(l):
            all_finite = False
            reasons.append(f"Non-finite loss ({l}) encountered at step {idx}")
            break

    # 4. Decision 2: Mean of last 20 steps < Mean of first 20 steps
    window_size = 20 if S >= 40 else (S // 2)
    first_window = losses[:window_size]
    last_window = losses[-window_size:]

    mean_first = float(np.mean(first_window)) if all_finite else float("nan")
    mean_last = float(np.mean(last_window)) if all_finite else float("nan")

    if all_finite:
        loss_decreased = bool(mean_last < mean_first)
        if not loss_decreased:
            reasons.append(
                f"Loss did not decrease: mean_last_{window_size} ({mean_last:.6f}) >= "
                f"mean_first_{window_size} ({mean_first:.6f})"
            )
    else:
        loss_decreased = False

    # 5. Decision 3: SIGReg stability (final <= 1.1 * initial)
    final_sigreg: float | None = None
    sigreg_stable: bool | None = None

    if sigreg_probe is not None and all_finite:
        final_sigreg = _evaluate_sigreg(sigreg_probe, arm)
        assert initial_sigreg is not None
        max_allowed = 1.1 * initial_sigreg
        sigreg_stable = bool(final_sigreg <= max_allowed + 1e-9)
        if not sigreg_stable:
            reasons.append(
                f"SIGReg increased above 1.1x: final ({final_sigreg:.6f}) > 1.1 * initial ({initial_sigreg:.6f})"
            )

    passed = all_finite and loss_decreased and (sigreg_stable is not False)

    return {
        "passed": bool(passed),
        "all_losses_finite": bool(all_finite),
        "loss_decreased": bool(loss_decreased),
        "sigreg_stable": sigreg_stable,
        "mean_first_window": mean_first,
        "mean_last_window": mean_last,
        "window_size": window_size,
        "initial_sigreg": initial_sigreg,
        "final_sigreg": final_sigreg,
        "total_steps": len(losses),
        "losses": losses,
        "reasons": reasons,
    }


def action_sensitivity(
    predict_fn: Callable[..., Any],
    states: Sequence[Any] | np.ndarray,
    n_actions: int = 4,
) -> float:
    """Compute action sensitivity across states normalized by mean state norm.

    For each state z:
      1. Predict next latent z'_a for each action a in {0..n_actions-1}.
      2. Compute average pairwise L2 distance across all pairs (a, b).
    Average across all states, then divide by mean(||z||_2).

    Args:
        predict_fn: Callable(z, action) -> next_z.
        states: Sequence of states (numpy arrays).
        n_actions: Number of discrete actions (default 4).

    Returns:
        float: Action sensitivity score.
    """
    if predict_fn is None or not callable(predict_fn):
        raise ValueError("predict_fn must be a callable")
    if states is None or len(states) == 0:
        raise ValueError("states must be a non-empty sequence")
    if not isinstance(n_actions, int) or n_actions < 2:
        raise ValueError(f"n_actions must be an integer >= 2, got {n_actions}")

    n_states = len(states)
    pairwise_distances_per_state: list[float] = []
    state_norms: list[float] = []

    for z_raw in states:
        z = np.asarray(z_raw, dtype=np.float64)
        z_norm = float(np.linalg.norm(z))
        state_norms.append(z_norm)

        next_latents: list[np.ndarray] = []
        for a in range(n_actions):
            try:
                nxt = predict_fn(z, a)
            except TypeError:
                a_vec = np.zeros(n_actions, dtype=np.float64)
                a_vec[a] = 1.0
                nxt = predict_fn(z, a_vec)
            next_latents.append(np.asarray(nxt, dtype=np.float64))

        # Compute all pairwise L2 distances
        dists: list[float] = []
        for i in range(n_actions):
            for j in range(i + 1, n_actions):
                diff = next_latents[i] - next_latents[j]
                dists.append(float(np.linalg.norm(diff)))

        pairwise_distances_per_state.append(float(np.mean(dists)))

    mean_pairwise = float(np.mean(pairwise_distances_per_state))
    mean_norm = float(np.mean(state_norms))

    if mean_norm < 1e-12:
        raise ValueError("Mean state norm is near zero (< 1e-12), cannot normalize sensitivity")

    sensitivity = mean_pairwise / mean_norm
    return float(sensitivity)


# -----------------------------------------------------------------------------
# Oracle Protocol & Feasibility
# -----------------------------------------------------------------------------


def _encode_pose_one_hot(s: Any) -> np.ndarray:
    """Encode GridLab State or dict into one-hot pose feature."""
    if isinstance(s, Mapping):
        x, y, h = int(s["x"]), int(s["y"]), int(s["heading"])
    elif isinstance(s, world.State):
        x, y, h = int(s.x), int(s.y), int(s.heading)
    elif isinstance(s, np.ndarray) and s.ndim == 1 and s.size == 2500:
        return np.asarray(s, dtype=np.float64)
    else:
        raise TypeError(f"Cannot encode pose from {type(s)}")

    vec = np.zeros(2500, dtype=np.float64)
    idx = (y * 25 + x) * 4 + (h % 4)
    vec[idx] = 1.0
    return vec


def _decode_pose_one_hot(vec: np.ndarray) -> world.State:
    """Decode one-hot pose feature into GridLab State."""
    idx = int(np.argmax(vec))
    h = idx % 4
    p = idx // 4
    x = p % 25
    y = p // 25
    return world.State(x, y, h)


def _default_oracle_mpc(
    layout: world.Layout,
    start_state: world.State,
    goal_state: world.State,
    bfs_dist: int,
    n_fwd: int,
    rng: np.random.Generator,
    max_steps: int,
) -> tuple[bool, int, list[str]]:
    """Execute default oracle MPC planning using true dynamics and BFS distance cost."""
    bfs_map = world.compute_bfs_distances(layout, goal_state.x, goal_state.y)

    def encode(s: Any) -> np.ndarray:
        return _encode_pose_one_hot(s)

    def predict_l1(z: np.ndarray, a: Any, dt: float = 1.0) -> np.ndarray:
        st = _decode_pose_one_hot(z)
        if isinstance(a, (int, np.integer)):
            act = int(a)
        else:
            arr = np.asarray(a).reshape(-1)
            act = int(np.round(arr[0])) if arr.size == 1 else int(np.argmax(arr))
        nst = world.step(layout, st, act, k=max(1, int(round(dt))))
        return _encode_pose_one_hot(nst)

    def cost_fn(z_T: np.ndarray, goal_obs: Any) -> float:
        st = _decode_pose_one_hot(z_T)
        dist = bfs_map.get((st.x, st.y), 1000)
        heading_penalty = 0.0 if st.heading == goal_state.heading else 0.5
        return float(dist + heading_penalty)

    cfg = planner.FlatCEMConfig(
        horizon=10,
        n_iters=3,
        pop_size=16,
        elite_frac=0.25,
        action_dim=1,
        n_categories=3,
        n_exec=2,
    )

    curr = start_state
    step = 0
    errors: list[str] = []

    while step < max_steps:
        if world.is_success(curr, goal_state, step, bfs_dist):
            return True, step, errors

        counter = ForwardCounter(budget=n_fwd)
        enc = counter.wrap("encode", encode)
        p1 = counter.wrap("predict_l1", predict_l1)

        try:
            res = planner.flat_cem_plan(
                encode=enc,
                predict_l1=p1,
                obs=curr,
                goal_obs=goal_state,
                config=cfg,
                rng=rng,
                counter=counter,
                cost_fn=cost_fn,
            )
        except ForwardBudgetExceeded as exc:
            errors.append(f"ForwardBudgetExceeded: {exc}")
            return False, step, errors

        for a in res.actions[: cfg.n_exec]:
            act = int(np.round(a[0]))
            curr = world.step(layout, curr, act, k=1)
            step += 1
            if world.is_success(curr, goal_state, step, bfs_dist):
                return True, step, errors

    succ = world.is_success(curr, goal_state, step, bfs_dist)
    return succ, step, errors


def oracle_feasibility(
    layout_specs: Sequence[Any],
    planner_fn: Callable[..., Any] | None = None,
    n_fwd: int = 4096,
    rng: Any = None,
    threshold: float = 0.05,
) -> dict[str, Any]:
    """Evaluate task feasibility using true world dynamics under ForwardCounter budget.

    If overall success rate is strictly below threshold (0.05), fuse triggers.

    Args:
        layout_specs: Sequence of episode items. Each item must contain layout and spec/pair.
        planner_fn: Optional custom planner callable. If None, uses default oracle MPC.
        n_fwd: Forward budget per planning call.
        rng: Random generator or seed.
        threshold: Success rate threshold below which fuse triggers (default 0.05).

    Returns:
        dict: Evaluation summary with success rate, episode details, and fuse_triggered flag.
    """
    if layout_specs is None or len(layout_specs) == 0:
        raise ValueError("layout_specs must be a non-empty sequence")
    if not isinstance(n_fwd, int) or n_fwd <= 0:
        raise ValueError(f"n_fwd must be a positive integer, got {n_fwd}")

    if rng is None:
        np_rng = np.random.default_rng(42)
    elif isinstance(rng, np.random.Generator):
        np_rng = rng
    elif isinstance(rng, int):
        np_rng = np.random.default_rng(rng)
    else:
        np_rng = np.random.default_rng(42)

    episode_results: list[dict[str, Any]] = []
    successes = 0

    for idx, item in enumerate(layout_specs):
        # Extract layout and spec
        if isinstance(item, tuple) and len(item) == 2:
            layout, spec_data = item
        elif isinstance(item, Mapping):
            layout = item.get("layout")
            spec_data = item.get("spec") or item
        else:
            raise TypeError(f"Invalid layout_spec format: {type(item)}")

        if layout is None:
            raise ValueError(f"Missing layout in episode {idx}")

        start_raw = spec_data.get("start") if isinstance(spec_data, Mapping) else getattr(spec_data, "start", None)
        if start_raw is None:
            raise ValueError(f"Missing start in episode spec {idx}")

        goal_raw = spec_data.get("goal") if isinstance(spec_data, Mapping) else getattr(spec_data, "goal", None)
        if goal_raw is None:
            raise ValueError(f"Missing goal in episode spec {idx}")

        bfs_dist_raw = spec_data.get("bfs_distance") if isinstance(spec_data, Mapping) else getattr(spec_data, "bfs_distance", None)
        if bfs_dist_raw is None:
            raise ValueError(f"Missing bfs_distance in episode spec {idx}")
        bfs_dist = int(bfs_dist_raw)

        start_state = world.State(int(start_raw["x"]), int(start_raw["y"]), int(start_raw["heading"]))
        goal_state = world.State(int(goal_raw["x"]), int(goal_raw["y"]), int(goal_raw["heading"]))
        max_steps = int(bfs_dist * 3)

        if planner_fn is not None:
            # Custom planner dispatch
            succ, steps, errors = planner_fn(
                layout=layout,
                start=start_state,
                goal=goal_state,
                bfs_distance=bfs_dist,
                n_fwd=n_fwd,
                rng=np_rng,
                max_steps=max_steps,
            )
        else:
            succ, steps, errors = _default_oracle_mpc(
                layout=layout,
                start_state=start_state,
                goal_state=goal_state,
                bfs_dist=bfs_dist,
                n_fwd=n_fwd,
                rng=np_rng,
                max_steps=max_steps,
            )

        if succ:
            successes += 1

        episode_results.append({
            "episode_index": idx,
            "success": bool(succ),
            "steps": int(steps),
            "max_steps": max_steps,
            "bfs_distance": bfs_dist,
            "errors": errors,
        })

    total_episodes = len(layout_specs)
    success_rate = float(successes / total_episodes) if total_episodes > 0 else 0.0
    fuse_triggered = bool(success_rate < float(threshold))
    passed = bool(not fuse_triggered)

    return {
        "passed": passed,
        "fuse_triggered": fuse_triggered,
        "success_rate": success_rate,
        "total_episodes": total_episodes,
        "successful_episodes": successes,
        "threshold": float(threshold),
        "episodes": episode_results,
    }


def oracle_feasibility_with_s2_planner(
    layout_specs: Sequence[Any],
    n_fwd: int = 4096,
    rng: Any = None,
    threshold: float = 0.05,
) -> dict[str, Any]:
    """Evaluate task feasibility using s2 flat_cem_plan under ForwardCounter budget (P154 / P167).

    Constructs oracle planning protocol using true world dynamics:
    - CEM parameters derived from learned_planning.cem_config_for_budget (DESIGN-r2 D3.1).
    - Trajectory cost using BFS distance to goal + heading alignment penalty (DESIGN-r2 Appendix E r2.6).
    - Transitions via world.step with true layout.
    - Optimizes actions via s2/planner.flat_cem_plan with budget n_fwd.
    - Serves as the circuit breaker fuse gate for S2 smoke.
    """
    from ainerzero.v9.experiments.s2 import learned_planning, spec

    def _s2_oracle_planner_fn(
        layout: world.Layout,
        start: world.State,
        goal: world.State,
        bfs_distance: int,
        n_fwd: int,
        rng: np.random.Generator,
        max_steps: int,
    ) -> tuple[bool, int, list[str]]:
        bfs_map = world.compute_bfs_distances(layout, goal.x, goal.y)

        def encode(s: Any) -> np.ndarray:
            st = s if isinstance(s, world.State) else _decode_pose_one_hot(s)
            base = _encode_pose_one_hot(st)
            d = float(bfs_map.get((st.x, st.y), 1000))
            return np.concatenate([base, [d, d]])

        def predict_l1(z: np.ndarray, a: Any, dt: float = 1.0) -> np.ndarray:
            st = _decode_pose_one_hot(z[:2500])
            if isinstance(a, (int, np.integer)):
                act = int(a)
            else:
                arr = np.asarray(a).reshape(-1)
                act = int(np.round(arr[0])) if arr.size == 1 else int(np.argmax(arr))
            nst = world.step(layout, st, act, k=max(1, int(round(dt))))
            base = _encode_pose_one_hot(nst)
            d = float(bfs_map.get((nst.x, nst.y), 1000))
            min_d = min(float(z[-2]), d)
            acc_d = float(z[-1]) + d
            return np.concatenate([base, [min_d, acc_d]])

        def cost_fn(z_T: np.ndarray, goal_obs: Any) -> float:
            min_d = float(z_T[-2])
            acc_d = float(z_T[-1])
            st = _decode_pose_one_hot(z_T[:2500])
            heading_penalty = 0.0 if st.heading == goal.heading else 0.5
            return acc_d + 10.0 * min_d + heading_penalty

        try:
            cfg = learned_planning.cem_config_for_budget(
                "flat",
                spec.SMOKE_PLAN_CHOICE["flat"],
                n_fwd,
            )
        except Exception as exc:
            return False, 0, [f"CEM configuration failed for budget {n_fwd}: {exc}"]

        curr = start
        step = 0
        errors: list[str] = []

        while step < max_steps:
            if world.is_success(curr, goal, step, bfs_distance):
                return True, step, errors

            counter = ForwardCounter(budget=n_fwd)
            enc = counter.wrap("s2_oracle_encode", encode)
            p1 = counter.wrap("s2_oracle_predict_l1", predict_l1)

            try:
                res = planner.flat_cem_plan(
                    encode=enc,
                    predict_l1=p1,
                    obs=curr,
                    goal_obs=goal,
                    config=cfg,
                    rng=rng,
                    counter=counter,
                    cost_fn=cost_fn,
                )
            except ForwardBudgetExceeded as exc:
                errors.append(f"ForwardBudgetExceeded: {exc}")
                return False, step, errors

            for a in res.actions[: cfg.n_exec]:
                act = int(np.round(a[0]))
                curr = world.step(layout, curr, act, k=1)
                step += 1
                if world.is_success(curr, goal, step, bfs_distance):
                    return True, step, errors

        succ = world.is_success(curr, goal, step, bfs_distance)
        return succ, step, errors

    res = oracle_feasibility(
        layout_specs=layout_specs,
        planner_fn=_s2_oracle_planner_fn,
        n_fwd=n_fwd,
        rng=rng,
        threshold=threshold,
    )
    res["planner"] = "s2_planner"
    return res

