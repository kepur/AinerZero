"""S2 smoke mode sanity and preflight check runner (ainerzero.V9.P148 / P154).

Specification & rules:
- Design document: reports/V9-S2-DESIGN/DESIGN-r2.md §5, §6, Appendix B (r2.3).
- Total wall-clock budget <= 20 min (1200 s).
- Steps:
  1. Native self-check: parameter counts match param_count closed-form; forward shapes match spec;
     SIGReg MLX matches NumPy core_math.
  2. Timing: measure single-step train time for each arm (A, B, C) under registered batch configuration,
     compute steps = floor(1200 s * 0.8 / single_step_time), and take the minimum across all arms.
  3. Short training sanity (smoke_checks.short_train_sanity):
     - S=200 steps on small smoke partition (4 worlds x 4 episodes).
     - Asserts finite loss, loss decrease, and SIGReg stability for Arm B/C.
     - Reports action_sensitivity for all arms.
  4. Task feasibility circuit breaker (smoke_checks.oracle_feasibility_with_s2_planner):
     - Uses true world dynamics with s2/planner.flat_cem_plan, N_fwd=4096, L=3*min_dist.
     - 12 smoke long goal specs across the smoke partition.
     - If success rate < 0.05, circuit breaker triggers and smoke fails.
     - _default_oracle_mpc results recorded as control comparison.
  5. Seed disjointness: smoke partition and seeds must NOT overlap with train, dev, or final partitions.
  6. Zero constant defaults: missing any real measurement fails closed with status=failed, passed=False.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import random
import time
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import data, param_count, smoke_checks, spec, train_runner, world

# Constants from spec
SMOKE_TIME_BUDGET_SECONDS: float = float(spec.BUDGET_SMOKE_MAX_SECONDS)  # 1200 s
SMOKE_CIRCUIT_BREAKER_THRESHOLD: float = float(spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD)  # 0.05
SMOKE_ACTION_SENSITIVITY_THRESHOLD: float = 0.05
SMOKE_SUBGOAL_SHUFFLE_DROP_THRESHOLD: float = 0.10
SMOKE_SHORT_TRAIN_STEPS: int = spec.SMOKE_SHORT_TRAIN_STEPS
SMOKE_SEED_NAMESPACE: str = "smoke_seed_ns"
FORBIDDEN_PARTITIONS: frozenset[str] = frozenset({"train", "dev", "final", "sealed_final"})


def check_smoke_seed_namespace(seed_namespace: str) -> None:
    """Enforce that smoke data seed namespace does not overlap with train, dev, or final partitions."""
    norm = str(seed_namespace).strip().lower()
    for forbidden in FORBIDDEN_PARTITIONS:
        if forbidden in norm:
            raise ValueError(
                f"Smoke seed namespace {seed_namespace!r} must not overlap with {forbidden!r}"
            )


def compute_training_steps(
    step_times_by_arm: Mapping[str, float],
    budget_seconds: float = float(spec.TRAIN_STEP_TIME_BUDGET_SECONDS),
    efficiency: float = float(spec.TRAIN_STEP_EFFICIENCY_FACTOR),
) -> dict[str, Any]:
    """Compute recommended training steps per arm and take the minimum across arms.

    Formula per Appendix A: steps = floor(1200 s * 0.8 / single_step_time).
    Three arms take the minimum to ensure all fit within the per-slot budget.
    """
    if not step_times_by_arm:
        raise ValueError("step_times_by_arm must not be empty")

    per_arm_steps: dict[str, int] = {}
    for arm_id, t_step in step_times_by_arm.items():
        if t_step <= 0.0 or not math.isfinite(t_step):
            raise ValueError(f"Invalid step time for {arm_id}: {t_step}")
        steps = int(math.floor(budget_seconds * efficiency / t_step))
        per_arm_steps[arm_id] = max(1, steps)

    shared_steps = min(per_arm_steps.values())

    return {
        "per_arm_step_times": {k: float(v) for k, v in step_times_by_arm.items()},
        "per_arm_steps": per_arm_steps,
        "shared_train_steps": shared_steps,
        "budget_seconds": budget_seconds,
        "efficiency_factor": efficiency,
    }


def check_smoke_preconditions(
    metrics: Mapping[str, Any],
    circuit_breaker_threshold: float = SMOKE_CIRCUIT_BREAKER_THRESHOLD,
    action_sensitivity_threshold: float = SMOKE_ACTION_SENSITIVITY_THRESHOLD,
    subgoal_shuffle_drop_threshold: float = SMOKE_SUBGOAL_SHUFFLE_DROP_THRESHOLD,
) -> dict[str, Any]:
    """Evaluate precondition checks on short-training / smoke results (legacy helper)."""
    reasons: list[str] = []

    # 1. SIGReg decreased
    delta_sigreg = float(metrics.get("delta_sigreg", 0.0))
    sigreg_ok = delta_sigreg < 0.0
    if not sigreg_ok:
        reasons.append(f"SIGReg did not decrease: delta_sigreg={delta_sigreg:.6f} >= 0")

    # 2. Action sensitivity
    act_sens = float(metrics.get("action_sensitivity", 0.0))
    sens_ok = act_sens >= action_sensitivity_threshold
    if not sens_ok:
        reasons.append(
            f"Action sensitivity below threshold: {act_sens:.4f} < {action_sensitivity_threshold}"
        )

    # 3. Subgoal shuffle negative control (Arm C)
    shuffle_drop = float(metrics.get("subgoal_shuffle_drop", 0.0))
    shuffle_ok = shuffle_drop >= subgoal_shuffle_drop_threshold
    if not shuffle_ok:
        reasons.append(
            f"Subgoal shuffle drop below threshold: {shuffle_drop:.4f} < {subgoal_shuffle_drop_threshold}"
        )

    # 4. Circuit breaker: if all arms have long-goal success rate < threshold
    success_rates = metrics.get("long_goal_success_rates", {})
    circuit_breaker = False
    if success_rates:
        all_below = all(float(sr) < circuit_breaker_threshold for sr in success_rates.values())
        if all_below:
            circuit_breaker = True
            reasons.append(
                f"Circuit breaker triggered: all arms long-goal success rates < {circuit_breaker_threshold} "
                f"({success_rates})"
            )

    passed = (len(reasons) == 0) and not circuit_breaker

    return {
        "passed": passed,
        "circuit_breaker": circuit_breaker,
        "reasons": reasons,
        "sigreg_decreased": sigreg_ok,
        "action_sensitive": sens_ok,
        "subgoal_shuffle_effective": shuffle_ok,
        "metrics_evaluated": dict(metrics),
    }


def check_native_param_counts(arms_by_id: Mapping[str, Any]) -> dict[str, bool]:
    """Assert param counts match closed-form formulas."""
    expected = {
        "arm_a": param_count.count_arm_a_closed_form(),
        "arm_b": param_count.count_arm_b_closed_form(),
        "arm_c": param_count.count_arm_c_closed_form(),
    }
    results = {}
    for arm_id, exp_count in expected.items():
        if arm_id in arms_by_id:
            arm = arms_by_id[arm_id]
            actual = arm.n_params() if hasattr(arm, "n_params") else getattr(arm, "param_count", None)
            results[arm_id] = (actual == exp_count)
    return results


def measure_planning_episode_times(
    arms_by_id: Mapping[str, Any],
    layout_specs: Sequence[Any],
    n_fwd: int = int(spec.N_FWD),
    n_episodes_per_arm: int = 2,
    clock: Callable[[], float] | None = None,
) -> dict[str, dict[str, Any]]:
    """Measure planning episode wall-clock time on smoke long goal specs (W4 / DESIGN-r2 D6).

    For each arm (A, B, C):
    - Uses default smoke planning config (spec.SMOKE_PLAN_CHOICE).
    - Runs n_episodes_per_arm episodes with learned_planning.make_plan_fn and eval.run_episode.
    - m = spec.PLAN_REPLAN_EVERY_OBS_STEPS (1).
    - Measures wall-clock time per episode, takes median per arm.
    """
    from ainerzero.v9.experiments.s2 import eval as s2_eval, learned_planning
    from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter

    if not arms_by_id:
        raise ValueError("arms_by_id must not be empty")
    if not layout_specs:
        raise ValueError("layout_specs must not be empty")

    timer = clock or time.perf_counter
    results: dict[str, dict[str, Any]] = {}

    for arm_id in ("arm_a", "arm_b", "arm_c"):
        if arm_id not in arms_by_id:
            raise ValueError(f"Missing arm instance for {arm_id}")
        arm = arms_by_id[arm_id]
        kind = learned_planning.arm_kind_of(arm_id)
        plan_choice = spec.SMOKE_PLAN_CHOICE[kind]
        plan_fn = learned_planning.make_plan_fn(arm, arm_id, plan_choice, n_fwd)

        ep_times: list[float] = []
        for ep_idx in range(min(n_episodes_per_arm, len(layout_specs))):
            item = layout_specs[ep_idx]
            if isinstance(item, tuple) and len(item) == 2:
                layout, spec_data = item
            elif isinstance(item, Mapping):
                layout = item.get("layout")
                spec_data = item.get("spec") or item
            else:
                raise TypeError(f"Invalid layout_spec item: {type(item)}")

            counter = ForwardCounter(budget=n_fwd)
            t_start = timer()
            s2_eval.run_episode(
                layout=layout,
                spec=spec_data,
                plan_fn=plan_fn,
                counter=counter,
                rng=42 + ep_idx,
                m=int(spec.PLAN_REPLAN_EVERY_OBS_STEPS),
                catch_budget_exceeded=True,
            )
            t_dur = timer() - t_start
            ep_times.append(float(t_dur))

        med_t = float(np.median(ep_times)) if ep_times else 0.0
        results[arm_id] = {
            "median_seconds": med_t,
            "episode_times": ep_times,
            "n_episodes": len(ep_times),
        }

    return results


def check_smoke_budget(
    timing_res: Mapping[str, Any] | None,
    step_times: Mapping[str, float] | None,
    plan_episode_times: Mapping[str, Any] | None = None,
    budget_ceiling_seconds: float = float(spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS),
    other_ceilings_seconds: float | None = None,
) -> dict[str, Any]:
    """Compute budget extrapolation analysis from real measured numbers (W4 / DESIGN-r2 D6).

    Extrapolates wall-clock time across all lifecycle phases:
    1. Data generation: P133 coefficient * registered episodes (TRAIN_N_WORLDS * TRAIN_EPISODES_PER_WORLD).
    2. Training: 3 seeds * 3 arms (9 cells) * min(1200 s, shared_train_steps * step_time[arm]).
    3. Plan-select: grid_size[arm] * 50 episodes * episode_time[arm].
    4. Post-train gates: 64 states action sensitivity + 100 episodes * episode_time['arm_c'].
    5. Dev evaluation: 300 * 3 arms * 3 seeds * (1 + N_fwd curve ratio) + regular_dt + short_goals.
    6. Final evaluation: 300 * 3 arms * 3 seeds * episode_time.
    7. Smoke: BUDGET_SMOKE_MAX_SECONDS (1200 s).

    Fails if total estimated seconds exceeds 10h ceiling or any component exceeds its registered ceiling.
    Zero fabricated constants: missing real step_times or plan_episode_times fails immediately.
    """
    reasons: list[str] = []

    if step_times is None:
        reasons.append("Budget analysis failed: step_times is None")
    if timing_res is None or "shared_train_steps" not in timing_res:
        reasons.append("Budget analysis failed: timing_res or shared_train_steps is missing")
    if plan_episode_times is None:
        reasons.append("Budget analysis failed: plan_episode_times is None")

    if reasons:
        return {
            "budget_10h_ceiling_seconds": budget_ceiling_seconds,
            "total_estimated_seconds": None,
            "sufficient": False,
            "passed": False,
            "reasons": reasons,
            "breakdown": None,
        }

    # Extract per-arm plan episode times
    t_plan_by_arm: dict[str, float] = {}
    for arm_id in ("arm_a", "arm_b", "arm_c"):
        val = plan_episode_times.get(arm_id)
        if val is None:
            reasons.append(f"Budget analysis failed: missing plan_episode_times for {arm_id}")
            continue
        if isinstance(val, (int, float)):
            t = float(val)
        elif isinstance(val, Mapping) and "median_seconds" in val:
            t = float(val["median_seconds"])
        elif isinstance(val, Sequence):
            t = float(np.median(val))
        else:
            try:
                t = float(val)
            except (TypeError, ValueError):
                reasons.append(f"Invalid plan_episode_times for {arm_id}: {val}")
                continue
        if t <= 0.0 or not math.isfinite(t):
            reasons.append(f"Non-positive or non-finite plan_episode_times for {arm_id}: {t}")
            continue
        t_plan_by_arm[arm_id] = t

    # Extract step times
    t_step_by_arm: dict[str, float] = {}
    for arm_id in ("arm_a", "arm_b", "arm_c"):
        val = step_times.get(arm_id)
        if val is None:
            reasons.append(f"Budget analysis failed: missing step_times for {arm_id}")
            continue
        t = float(val)
        if t <= 0.0 or not math.isfinite(t):
            reasons.append(f"Non-positive or non-finite step_times for {arm_id}: {t}")
            continue
        t_step_by_arm[arm_id] = t

    if reasons:
        return {
            "budget_10h_ceiling_seconds": budget_ceiling_seconds,
            "total_estimated_seconds": None,
            "sufficient": False,
            "passed": False,
            "reasons": reasons,
            "breakdown": None,
        }

    shared_steps = int(timing_res["shared_train_steps"])

    # 1. Data generation
    data_episodes = int(spec.TRAIN_N_WORLDS) * int(spec.TRAIN_EPISODES_PER_WORLD)
    data_coeff = float(spec.DATA_ESTIMATED_SECONDS_PER_EPISODE)
    est_data = float(data_episodes * data_coeff)
    ceil_data = float(spec.BUDGET_DATA_MAX_SECONDS)
    exceeded_data = est_data > ceil_data
    if exceeded_data:
        reasons.append(
            f"Data generation estimated time {est_data:.1f}s exceeds ceiling {ceil_data:.1f}s by {est_data - ceil_data:.1f}s"
        )

    # 2. Training
    per_arm_train: dict[str, float] = {}
    for arm_id in ("arm_a", "arm_b", "arm_c"):
        slot_sec = min(float(spec.BUDGET_TRAIN_PER_SLOT_SECONDS), shared_steps * t_step_by_arm[arm_id])
        per_arm_train[arm_id] = 3.0 * slot_sec
    est_train = float(sum(per_arm_train.values()))
    ceil_train = float(spec.BUDGET_TRAIN_MAIN_TOTAL_SECONDS)
    exceeded_train = est_train > ceil_train
    if exceeded_train:
        reasons.append(
            f"Training estimated time {est_train:.1f}s exceeds ceiling {ceil_train:.1f}s by {est_train - ceil_train:.1f}s"
        )

    # 3. Plan-select
    grid_sizes = {
        "arm_a": len(spec.FLAT_H_CANDIDATES),
        "arm_b": len(spec.FLAT_H_CANDIDATES),
        "arm_c": len(spec.HIERARCHICAL_HORIZON_CANDIDATES) * len(spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES),
    }
    n_select_episodes = int(spec.HYPERPARAM_SELECTION_MAX_EPISODES)
    per_arm_plan_select = {
        arm_id: float(grid_sizes[arm_id] * n_select_episodes * t_plan_by_arm[arm_id])
        for arm_id in ("arm_a", "arm_b", "arm_c")
    }
    est_plan_select = float(sum(per_arm_plan_select.values()))
    ceil_plan_select = float(spec.BUDGET_HYPERPARAM_SELECTION_SECONDS)
    exceeded_plan_select = est_plan_select > ceil_plan_select
    if exceeded_plan_select:
        reasons.append(
            f"Plan-select hyperparameter selection estimated time {est_plan_select:.1f}s exceeds ceiling {ceil_plan_select:.1f}s by {est_plan_select - ceil_plan_select:.1f}s"
        )

    # 4. Post-train gates: 64 states + 100 episodes on Arm C
    est_post_train_gates = float(100.0 * t_plan_by_arm["arm_c"])

    # 5. Dev evaluation: 300 * 3 arms * 3 seeds * (1 + 2.5) + (regular_dt + short_goals) * 3 arms * 3 seeds
    # Curve tiers from spec, relative to the primary N_fwd (the primary tier is counted once) — W9.
    n_primary = float(spec.N_FWD)
    curve_multiplier = 1.0 + sum(float(lv) / n_primary for lv in spec.N_FWD_DEV_LEVELS if int(lv) != int(spec.N_FWD))
    n_seeds = float(len(spec.TRAINING_SEEDS))
    regular_dt_eps = int(spec.REGULAR_DT_SUBSET_EPISODES)
    short_goal_eps = 100  # no registered spec constant for the dev short-goal subset size (W9 report notes it)
    per_arm_dev = {
        arm_id: float(
            (float(spec.DEV_LONG_GOAL_EPISODES) * n_seeds * curve_multiplier + (regular_dt_eps + short_goal_eps) * n_seeds)
            * t_plan_by_arm[arm_id]
        )
        for arm_id in ("arm_a", "arm_b", "arm_c")
    }
    est_dev = float(sum(per_arm_dev.values()))
    ceil_dev = float(spec.BUDGET_DEV_EVAL_SECONDS)
    exceeded_dev = est_dev > ceil_dev
    if exceeded_dev:
        reasons.append(
            f"Dev evaluation estimated time {est_dev:.1f}s exceeds ceiling {ceil_dev:.1f}s by {est_dev - ceil_dev:.1f}s"
        )

    # 6. Final evaluation: 300 * 3 arms * 3 seeds
    per_arm_final = {
        arm_id: float(float(spec.FINAL_LONG_GOAL_EPISODES) * float(len(spec.TRAINING_SEEDS)) * t_plan_by_arm[arm_id])
        for arm_id in ("arm_a", "arm_b", "arm_c")
    }
    est_final = float(sum(per_arm_final.values()))
    ceil_final = float(spec.BUDGET_FINAL_EVAL_SECONDS)
    exceeded_final = est_final > ceil_final
    if exceeded_final:
        reasons.append(
            f"Final evaluation estimated time {est_final:.1f}s exceeds ceiling {ceil_final:.1f}s by {est_final - ceil_final:.1f}s"
        )

    # 7. Smoke budget
    est_smoke = float(spec.BUDGET_SMOKE_MAX_SECONDS)

    # Total actual wallclock seconds
    total_estimated = float(
        est_smoke + est_data + est_train + est_plan_select + est_post_train_gates + est_dev + est_final
    )
    exceeded_total = total_estimated > budget_ceiling_seconds
    if exceeded_total:
        reasons.append(
            f"Estimated total wall-clock {total_estimated:.1f}s exceeds ceiling {budget_ceiling_seconds:.1f}s by {total_estimated - budget_ceiling_seconds:.1f}s"
        )

    sufficient = (len(reasons) == 0)

    breakdown = {
        "smoke": {
            "formula": "BUDGET_SMOKE_MAX_SECONDS",
            "estimated_seconds": est_smoke,
            "ceiling_seconds": est_smoke,
            "exceeded": False,
        },
        "data": {
            "formula": f"{data_episodes} episodes * {data_coeff} s/ep",
            "estimated_seconds": est_data,
            "ceiling_seconds": ceil_data,
            "exceeded": exceeded_data,
        },
        "train": {
            "formula": "3 seeds * sum_{arm in (A,B,C)} min(1200, shared_train_steps * step_time[arm])",
            "estimated_seconds": est_train,
            "ceiling_seconds": ceil_train,
            "per_arm_seconds": per_arm_train,
            "shared_train_steps": shared_steps,
            "exceeded": exceeded_train,
        },
        "plan_select": {
            "formula": "sum_{arm} (grid_size[arm] * 50 * episode_plan_time[arm])",
            "estimated_seconds": est_plan_select,
            "ceiling_seconds": ceil_plan_select,
            "per_arm_seconds": per_arm_plan_select,
            "grid_sizes": grid_sizes,
            "exceeded": exceeded_plan_select,
        },
        "post_train_gates": {
            "formula": "100 episodes * episode_plan_time['arm_c']",
            "estimated_seconds": est_post_train_gates,
            "ceiling_seconds": None,
            "exceeded": False,
        },
        "dev": {
            "formula": "sum_{arm} (DEV_LONG_GOAL_EPISODES * n_seeds * (1 + sum_{tier != N_FWD} tier/N_FWD) + (regular_dt + short_goal) * n_seeds) * episode_plan_time[arm]",
            "estimated_seconds": est_dev,
            "ceiling_seconds": ceil_dev,
            "per_arm_seconds": per_arm_dev,
            "exceeded": exceeded_dev,
        },
        "final": {
            "formula": "sum_{arm} 300 episodes * 3 seeds * episode_plan_time[arm]",
            "estimated_seconds": est_final,
            "ceiling_seconds": ceil_final,
            "per_arm_seconds": per_arm_final,
            "exceeded": exceeded_final,
        },
        "total": {
            "estimated_seconds": total_estimated,
            "ceiling_seconds": budget_ceiling_seconds,
            "exceeded": exceeded_total,
        },
    }

    return {
        "budget_10h_ceiling_seconds": budget_ceiling_seconds,
        "estimated_train_total_seconds": est_train,
        "total_estimated_seconds": total_estimated,
        "sufficient": sufficient,
        "passed": sufficient,
        "reasons": reasons,
        "breakdown": breakdown,
    }


def make_smoke_timing_batch(
    batch_size: int = spec.BATCH_SIZE,
    seq_len: int = spec.H_TRAIN + 1,
    seed: int = 42,
) -> dict[str, Any]:
    """Generate registered batch shape (32, H_train+1, ...) for smoke step timing measurement."""
    return train_runner.make_dummy_batch(batch_size=batch_size, seq_len=seq_len, seed=seed)


def generate_smoke_partition(
    output_root: str | Path,
    seed_namespace: str = SMOKE_SEED_NAMESPACE,
) -> tuple[Path, list[dict[str, np.ndarray]], list[dict[str, Any]]]:
    """Generate smoke partition under output_root/datasets/smoke (ainerzero.V9.P154).

    Produces:
    - 4 worlds x 4 episodes generated by data.generate_partition.
    - 12 long goal episode specs (3 per world x 4 worlds).
    - Assembled length-17 training batches for short_train_sanity.

    Returns:
        (smoke_dir, batches, layout_specs)
    """
    check_smoke_seed_namespace(seed_namespace)
    out_dir = Path(output_root).resolve()
    datasets_dir = out_dir / "datasets"
    datasets_dir.mkdir(parents=True, exist_ok=True)
    smoke_dir = datasets_dir / "smoke"

    n_worlds = spec.SMOKE_N_WORLDS
    episodes_per_world = spec.SMOKE_EPISODES_PER_WORLD
    total_short_steps = spec.SMOKE_SHORT_TRAIN_STEPS

    # 1. Generate small smoke partition if not already present
    if not (smoke_dir / "manifest.json").is_file():
        data.generate_partition(
            partition="smoke",
            n_worlds=n_worlds,
            episodes_per_world=episodes_per_world,
            output_root=datasets_dir,
            seed_namespace=seed_namespace,
        )

    # 2. Generate 12 long goal episode specs (3 per world across the 4 worlds)
    layout_specs: list[dict[str, Any]] = []
    goal_specs_all: list[dict[str, Any]] = []

    for w_idx in range(n_worlds):
        w_dir = smoke_dir / f"world_{w_idx:04d}"
        w_seed = data._get_derived_seed(seed_namespace, "smoke", "world", w_idx)
        prep_rng = random.Random(data._get_derived_seed(seed_namespace, "smoke", "prep", w_idx))
        layout, pairs, _ = world.prepare_world_with_long_pairs(
            w_seed,
            prep_rng,
            n_long_pairs=3,
            enforce_rejection_redraw=True,
        )
        for p_idx, pair in enumerate(pairs[:3]):
            spec_item = {
                "episode_index": len(layout_specs),
                "world_index": w_idx,
                "pair_index": p_idx,
                "kind": "long",
                "start": pair["start"],
                "goal": pair["goal"],
                "bfs_distance": int(pair.get("bfs_distance", pair.get("distance", 40))),
            }
            goal_specs_all.append(spec_item)
            layout_specs.append({"layout": layout, "spec": spec_item})

    specs_file = smoke_dir / "goal_episode_specs.json"
    specs_file.write_text(
        json.dumps(goal_specs_all, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    # 3. Extract length-17 observation windows from smoke episodes using train_runner
    windows: list[dict[str, np.ndarray]] = []
    for ep_file in sorted(smoke_dir.rglob("episode_*.json")):
        wins = train_runner._load_episode_sequences(ep_file)
        if wins:
            windows.extend(wins)

    # Assemble batches of size BATCH_SIZE (32) for total_short_steps (200)
    batches: list[dict[str, np.ndarray]] = []
    n_w = len(windows)
    B = spec.BATCH_SIZE
    if n_w == 0:
        raise ValueError(f"No valid windows extracted from smoke partition at {smoke_dir}")

    for step_i in range(total_short_steps):
        idxs = [(step_i * B + b) % n_w for b in range(B)]
        batch_obs = np.stack([windows[i][spec.BATCH_OBSERVATIONS_KEY] for i in idxs], axis=0)
        batch_act = np.stack([windows[i][spec.BATCH_ACTIONS_KEY] for i in idxs], axis=0)
        batch_dt = np.stack([windows[i][spec.BATCH_DTS_KEY] for i in idxs], axis=0)
        batches.append(train_runner.make_batch(batch_obs, batch_act, batch_dt))

    return smoke_dir, batches, layout_specs


def mlx_sigreg_alignment(Z_test: np.ndarray) -> float:
    """MLX boundary of the smoke native self-check: SIGReg computed with MLX (lazy MLX import)."""
    import mlx.core as mx

    from ainerzero.v9.experiments.s2 import arms_mlx

    val = arms_mlx.compute_sigreg_mlx(mx.array(Z_test))
    return float(val.item() if hasattr(val, "item") else val)


def measure_real_smoke(
    output_root: Path,
    repo_root: Path | None = None,
    seed_namespace: str = SMOKE_SEED_NAMESPACE,
    clock: Callable[[], float] | None = None,
    **kwargs: Any,
) -> tuple[
    dict[str, Any] | None,
    dict[str, float] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    dict[str, Any] | None,
    list[str],
]:
    """Execute real smoke measurements using MLX arms and smoke_checks on smoke partition (P154).

    Returns:
        (arms_by_id, step_times, step_3_res, step_4_res, default_oracle_res, reasons)
    """
    reasons: list[str] = []
    try:
        from ainerzero.v9.experiments.s2 import adapters_mlx, core_math
    except Exception as e:
        reasons.append(f"Real smoke measurement failed to import MLX dependencies: {e}")
        return None, None, None, None, None, reasons

    try:
        # Step 0: Generate small smoke partition
        smoke_dir, batches, layout_specs = generate_smoke_partition(
            output_root=output_root,
            seed_namespace=seed_namespace,
        )

        # (a) Native self-check: build three real MLX arms
        arms_by_id = {
            "arm_a": adapters_mlx.make_mlx_arm("arm_a"),
            "arm_b": adapters_mlx.make_mlx_arm("arm_b"),
            "arm_c": adapters_mlx.make_mlx_arm("arm_c"),
        }
        for arm in arms_by_id.values():
            arm.init(seed=42)

        # Check forward shapes
        dummy_obs = np.zeros(spec.OBS_DIM, dtype=np.float32)
        za = arms_by_id["arm_a"].encode(dummy_obs)
        zb = arms_by_id["arm_b"].encode(dummy_obs)
        zc = arms_by_id["arm_c"].encode(dummy_obs)
        z2c = arms_by_id["arm_c"].encode_l2(zc)
        if za.shape not in ((spec.ARM_DIMS["arm_a"]["e1_output"],), (spec.ARM_DIMS["arm_a"]["latent_dim"],)):
            reasons.append(f"Arm A encode shape mismatch: {za.shape}")
        if zb.shape != (spec.ARM_DIMS["arm_b"]["e1_output"],):
            reasons.append(f"Arm B encode shape mismatch: {zb.shape}")
        if zc.shape != (spec.ARM_DIMS["arm_c"]["e1_output"],):
            reasons.append(f"Arm C encode shape mismatch: {zc.shape}")
        if z2c.shape != (spec.ARM_DIMS["arm_c"]["z2_dim"],):
            reasons.append(f"Arm C encode_l2 shape mismatch: {z2c.shape}")

        # Check SIGReg alignment
        np_rng = np.random.RandomState(42)
        Z_test = np_rng.randn(32, 16).astype(np.float32)
        sigreg_np = core_math.compute_sigreg_numpy(Z_test)
        sigreg_mlx = mlx_sigreg_alignment(Z_test)
        if abs(sigreg_np - sigreg_mlx) > 1e-4:
            reasons.append(f"SIGReg MLX vs NumPy alignment mismatch: {sigreg_np:.6f} vs {sigreg_mlx:.6f}")

        # (b) Dummy batch for step timing: registered batch shape (32, H_train+1, ...)
        dummy_batch = make_smoke_timing_batch()

        # Measure timing per arm for K=20 steps with 1 warmup step
        step_times: dict[str, float] = {}
        K_MEASURE = 20
        for arm_id, arm in arms_by_id.items():
            arm.train_step(dummy_batch)
            t_s = (clock or time.time)()
            for _ in range(K_MEASURE):
                arm.train_step(dummy_batch)
            t_dur = (clock or time.time)() - t_s
            step_times[arm_id] = max(1e-4, t_dur / K_MEASURE)

        # (b2) Measure planning episode timing per arm on 2 long-goal smoke episodes (W4 / DESIGN-r2 D6)
        plan_episode_times = measure_planning_episode_times(
            arms_by_id=arms_by_id,
            layout_specs=layout_specs,
            n_fwd=spec.N_FWD,
            n_episodes_per_arm=2,
            clock=clock,
        )

        # (c) Step 3: Short-training sanity on smoke batches
        step_3_res: dict[str, Any] = {"arms": {}, "passed": True}
        S_steps = spec.SMOKE_SHORT_TRAIN_STEPS

        for arm_id, arm in arms_by_id.items():
            # Define SIGReg probe for B and C
            probe_fn = None
            if arm_id in ("arm_b", "arm_c"):
                def probe_fn(m_arm: Any = arm) -> float:
                    z = m_arm.latents(batches[0]["observations"][:16])
                    if z.ndim > 2:
                        z = z.reshape(-1, z.shape[-1])
                    return float(core_math.compute_sigreg_numpy(z))

            arm_sanity = smoke_checks.short_train_sanity(
                arm=arm,
                batches=batches,
                S=S_steps,
                sigreg_probe=probe_fn,
            )

            # Compute action sensitivity
            states_sample = arm.latents(batches[0]["observations"][:16, 0])
            act_sens = smoke_checks.action_sensitivity(
                predict_fn=arm.predict_l1,
                states=states_sample,
            )
            arm_sanity["action_sensitivity"] = act_sens
            step_3_res["arms"][arm_id] = arm_sanity

            if not arm_sanity["passed"]:
                step_3_res["passed"] = False
                reasons.append(f"Step 3 short-train sanity failed for {arm_id}: {arm_sanity.get('reasons', [])}")

        # (d) Step 4: Oracle task feasibility circuit breaker
        step_4_res = smoke_checks.oracle_feasibility_with_s2_planner(
            layout_specs=layout_specs,
            n_fwd=spec.N_FWD,
            rng=42,
            threshold=spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD,
        )
        if step_4_res.get("fuse_triggered", False) or not step_4_res.get("passed", False):
            reasons.append(
                f"Step 4 oracle feasibility circuit breaker triggered: success_rate={step_4_res.get('success_rate', 0.0):.4f} "
                f"< threshold={step_4_res.get('threshold', 0.05)}"
            )

        # Control comparison with default MPC
        default_oracle_res = smoke_checks.oracle_feasibility(
            layout_specs=layout_specs,
            n_fwd=spec.N_FWD,
            rng=42,
            threshold=spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD,
        )

        return arms_by_id, step_times, plan_episode_times, step_3_res, step_4_res, default_oracle_res, reasons
    except Exception as e:
        reasons.append(f"Real smoke measurement execution error: {e}")
        return None, None, None, None, None, None, reasons


def run_smoke(
    output_root: str | Path,
    ledger: Any = None,
    run_id: str | None = None,
    *,
    seed_namespace: str = SMOKE_SEED_NAMESPACE,
    step_times: Mapping[str, float] | None = None,
    preconditions_metrics: Mapping[str, Any] | None = None,
    arms_by_id: Mapping[str, Any] | None = None,
    plan_episode_times: Mapping[str, Any] | None = None,
    clock: Callable[[], float] | None = None,
    execute_real: bool = False,
    budget_ceiling_seconds: float | None = None,
    other_ceilings_seconds: float | None = None,
    repo_root: str | Path | None = None,
    layout_specs: Sequence[Any] | None = None,
    batches: Sequence[Any] | None = None,
    step_3_short_train: Mapping[str, Any] | None = None,
    step_4_feasibility: Mapping[str, Any] | None = None,
    oracle_planner_override: Callable[..., Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Execute S2 smoke sanity check under the 20 min hard budget (P154)."""
    t0 = (clock or time.time)()
    out_dir = Path(output_root).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    reasons: list[str] = []

    # 1. Enforce seed namespace disjointness
    check_smoke_seed_namespace(seed_namespace)

    default_oracle_comparison: dict[str, Any] | None = None

    # 2. If real execution requested, measure real MLX arms and smoke checks
    if execute_real and (arms_by_id is None or step_times is None or plan_episode_times is None):
        real_arms, real_times, real_plans, real_s3, real_s4, real_oracle_ctrl, real_errs = measure_real_smoke(
            output_root=out_dir,
            repo_root=Path(repo_root) if repo_root else None,
            seed_namespace=seed_namespace,
            clock=clock,
            **kwargs,
        )
        if arms_by_id is None and real_arms is not None:
            arms_by_id = real_arms
        if step_times is None and real_times is not None:
            step_times = real_times
        if plan_episode_times is None and real_plans is not None:
            plan_episode_times = real_plans
        if step_3_short_train is None and real_s3 is not None:
            step_3_short_train = real_s3
        if step_4_feasibility is None and real_s4 is not None:
            step_4_feasibility = real_s4
        if default_oracle_comparison is None and real_oracle_ctrl is not None:
            default_oracle_comparison = real_oracle_ctrl
        reasons.extend(real_errs)
        if step_3_short_train is None and real_s3 is not None:
            step_3_short_train = real_s3
        if step_4_feasibility is None and real_s4 is not None:
            step_4_feasibility = real_s4
        if default_oracle_comparison is None and real_oracle_ctrl is not None:
            default_oracle_comparison = real_oracle_ctrl
        reasons.extend(real_errs)

    # 3. Check for missing measurements (fail-closed, NO constant fallbacks)
    param_results: dict[str, bool] = {}
    if arms_by_id is None:
        reasons.append("Missing native arm instances: arms_by_id is None")
    else:
        param_results = check_native_param_counts(arms_by_id)
        if not param_results or not all(param_results.values()):
            reasons.append(f"Param count verification failed: {param_results}")

    # 4. Timing & training steps calculation
    timing_res: dict[str, Any] | None = None
    if step_times is None:
        reasons.append("Missing single-step timing measurements: step_times is None")
    else:
        try:
            timing_res = compute_training_steps(step_times)
        except Exception as e:
            reasons.append(f"Failed to compute training steps: {e}")

    # 5. Data partition generation (lazy for simulated/fake runs if needed)
    smoke_dir = out_dir / "datasets" / "smoke"
    if (batches is None or layout_specs is None) and arms_by_id is not None:
        try:
            smoke_dir, auto_batches, auto_layout_specs = generate_smoke_partition(
                output_root=out_dir,
                seed_namespace=seed_namespace,
            )
            if batches is None:
                batches = auto_batches
            if layout_specs is None:
                layout_specs = auto_layout_specs
        except Exception as exc:
            reasons.append(f"Failed to generate smoke partition: {exc}")

    # 6. Step 3: Short-training sanity
    step_3_res: dict[str, Any] = {}
    if step_3_short_train is not None:
        step_3_res = dict(step_3_short_train)
        if not step_3_res.get("passed", False):
            reasons.append(f"Step 3 short-train sanity failed: {step_3_res.get('reasons', [])}")
    elif arms_by_id is not None and batches is not None:
        step_3_res = {"arms": {}, "passed": True}
        S_steps = spec.SMOKE_SHORT_TRAIN_STEPS

        for arm_id, arm in arms_by_id.items():
            probe_fn = getattr(arm, "evaluate_sigreg", None)
            arm_sanity = smoke_checks.short_train_sanity(
                arm=arm,
                batches=batches,
                S=S_steps,
                sigreg_probe=probe_fn,
            )

            # Report action_sensitivity if predict_l1 available
            act_sens = None
            if hasattr(arm, "predict_l1") and callable(arm.predict_l1):
                try:
                    sample_states = [np.ones(16, dtype=np.float64)]
                    if hasattr(arm, "latents") and callable(arm.latents):
                        sample_states = arm.latents(batches[0]["observations"][:8, 0])
                    act_sens = smoke_checks.action_sensitivity(
                        predict_fn=arm.predict_l1,
                        states=sample_states,
                    )
                except Exception:
                    act_sens = 0.0
            arm_sanity["action_sensitivity"] = act_sens
            step_3_res["arms"][arm_id] = arm_sanity

            if not arm_sanity.get("passed", False):
                step_3_res["passed"] = False
                reasons.append(f"Step 3 short-train sanity failed for {arm_id}: {arm_sanity.get('reasons', [])}")
    else:
        step_3_res = {"status": "missing_inputs", "passed": False}
        reasons.append("Missing precondition evaluation metrics: preconditions_metrics is None")
        reasons.append("Step 3 short-training sanity missing inputs")

    # 7. Step 4: Oracle task feasibility circuit breaker
    step_4_res: dict[str, Any] = {}
    if step_4_feasibility is not None:
        step_4_res = dict(step_4_feasibility)
        if step_4_res.get("fuse_triggered", False) or not step_4_res.get("passed", False):
            reasons.append(
                f"Step 4 oracle feasibility circuit breaker triggered: success_rate={step_4_res.get('success_rate', 0.0):.4f} "
                f"< threshold={step_4_res.get('threshold', 0.05)}"
            )
    elif layout_specs is not None:
        planner_to_use = oracle_planner_override or smoke_checks.oracle_feasibility_with_s2_planner
        step_4_res = planner_to_use(
            layout_specs=layout_specs,
            n_fwd=spec.N_FWD,
            threshold=spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD,
        )
        if step_4_res.get("fuse_triggered", False) or not step_4_res.get("passed", False):
            reasons.append(
                f"Step 4 oracle feasibility circuit breaker triggered: success_rate={step_4_res.get('success_rate', 0.0):.4f} "
                f"< threshold={step_4_res.get('threshold', 0.05)}"
            )

        # Control comparison
        try:
            default_oracle_comparison = smoke_checks.oracle_feasibility(
                layout_specs=layout_specs,
                n_fwd=spec.N_FWD,
                threshold=spec.SMOKE_CIRCUIT_BREAKER_THRESHOLD,
            )
        except Exception:
            default_oracle_comparison = None
    else:
        step_4_res = {"status": "missing_inputs", "passed": False, "fuse_triggered": True}
        reasons.append("Step 4 oracle feasibility missing layout_specs inputs")

    # 7b. Planning episode timing measurement (W4 / DESIGN-r2 D6)
    if plan_episode_times is None and arms_by_id is not None and layout_specs is not None:
        can_plan = all(
            callable(getattr(arm, "encode", None)) and callable(getattr(arm, "predict_l1", None))
            for arm in arms_by_id.values()
        )
        if can_plan:
            try:
                plan_episode_times = measure_planning_episode_times(
                    arms_by_id=arms_by_id,
                    layout_specs=layout_specs,
                    n_fwd=spec.N_FWD,
                    n_episodes_per_arm=2,
                    clock=clock,
                )
            except Exception as e:
                reasons.append(f"Failed to measure planning episode times: {e}")

    if plan_episode_times is None:
        reasons.append("Missing planning episode timing measurements: plan_episode_times is None")

    # 8. Budget analysis
    ceiling_sec = (
        float(spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS)
        if budget_ceiling_seconds is None
        else float(budget_ceiling_seconds)
    )
    budget_analysis = check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=plan_episode_times,
        budget_ceiling_seconds=ceiling_sec,
        other_ceilings_seconds=other_ceilings_seconds,
    )
    if not budget_analysis["sufficient"]:
        reasons.extend(budget_analysis["reasons"])

    # Determine overall pass
    passed = (len(reasons) == 0)
    elapsed = (clock or time.time)() - t0

    report = {
        "mode": "smoke",
        "passed": passed,
        "status": "completed" if passed else "failed",
        "reasons": reasons,
        "elapsed_seconds": elapsed,
        "seed_namespace": seed_namespace,
        "param_checks": param_results,
        "timing_and_steps": timing_res,
        "planning_timing": plan_episode_times,
        "step_3_short_train": step_3_res,
        "step_4_feasibility": step_4_res,
        "step_4_default_oracle_comparison": default_oracle_comparison,
        "budget_analysis": budget_analysis,
    }

    report_path = out_dir / "smoke_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report
