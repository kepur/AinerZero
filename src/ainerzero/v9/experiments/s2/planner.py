"""S2 shared planners (NumPy reference): flat CEM and hierarchical CEM.

Model-agnostic: planners accept callables only
(``encode``, ``predict_l1``, ``predict_l2``, ``encode_l2``). No MLX, no
training. All sampling uses an explicit ``numpy.random.Generator``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter

__all__ = [
    "FlatCEMConfig",
    "HierCEMConfig",
    "PlanResult",
    "flat_cem_plan",
    "hierarchical_cem_plan",
    "rollout_l1",
    "squared_distance",
]


ArrayFn = Callable[..., np.ndarray]


def squared_distance(a: np.ndarray, b: np.ndarray) -> float:
    diff = np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64)
    return float(np.sum(diff * diff))


def rollout_l1(
    predict_l1: ArrayFn,
    z0: np.ndarray,
    actions: np.ndarray,
    dts: np.ndarray | None = None,
) -> np.ndarray:
    """Roll ``predict_l1`` over a raw action sequence; return terminal latent."""
    z = np.asarray(z0, dtype=np.float64)
    actions = np.asarray(actions, dtype=np.float64)
    if actions.ndim == 1:
        actions = actions.reshape(-1, 1)
    horizon = actions.shape[0]
    if dts is None:
        dts = np.ones(horizon, dtype=np.float64)
    else:
        dts = np.asarray(dts, dtype=np.float64).reshape(-1)
        if dts.shape[0] != horizon:
            raise ValueError("dts length must match action horizon")
    for t in range(horizon):
        z = predict_l1(z, actions[t], float(dts[t]))
    return z


def _elite_count(pop_size: int, elite_frac: float) -> int:
    n = max(1, int(np.ceil(pop_size * elite_frac)))
    return min(n, pop_size)


def _sample_actions(
    rng: np.random.Generator,
    mean: np.ndarray,
    std: np.ndarray,
    low: np.ndarray,
    high: np.ndarray,
    pop_size: int,
) -> np.ndarray:
    """Sample ``pop_size`` continuous action sequences shaped ``(pop, H, dim)``."""
    noise = rng.standard_normal(size=(pop_size, *mean.shape))
    samples = mean[None, ...] + std[None, ...] * noise
    return np.clip(samples, low, high)


def _sample_categorical(
    rng: np.random.Generator,
    probs: np.ndarray,
    pop_size: int,
) -> np.ndarray:
    """Sample discrete action indices; return shape ``(pop, H, 1)``."""
    horizon, n_cat = probs.shape
    out = np.empty((pop_size, horizon, 1), dtype=np.float64)
    for t in range(horizon):
        out[:, t, 0] = rng.choice(n_cat, size=pop_size, p=probs[t])
    return out


def _update_categorical_probs(elites: np.ndarray, n_cat: int) -> np.ndarray:
    """Frequency-based categorical update from elite index sequences."""
    horizon = elites.shape[1]
    probs = np.full((horizon, n_cat), 1e-3, dtype=np.float64)
    idx = np.asarray(elites[..., 0], dtype=np.int64)
    for t in range(horizon):
        counts = np.bincount(idx[:, t], minlength=n_cat).astype(np.float64)
        probs[t] = counts + 1e-3
        probs[t] /= probs[t].sum()
    return probs


def _pick_modal_first_elite(pop: np.ndarray, costs: np.ndarray, elite_idx: np.ndarray) -> int:
    """Among minimum-cost elites, return index whose first action is the mode."""
    min_c = float(np.min(costs[elite_idx]))
    tied = [int(ei) for ei in elite_idx if costs[ei] <= min_c + 1e-12]
    firsts = [tuple(np.asarray(pop[ei][0]).reshape(-1).tolist()) for ei in tied]
    mode_first = max(set(firsts), key=firsts.count)
    return next(ei for ei, f in zip(tied, firsts) if f == mode_first)


@dataclass(frozen=True)
class FlatCEMConfig:
    horizon: int
    n_iters: int
    pop_size: int
    elite_frac: float
    action_dim: int
    action_low: float | Sequence[float] = -1.0
    action_high: float | Sequence[float] = 1.0
    n_exec: int = 1
    init_std: float = 1.0
    # When set, CEM samples categorical indices in ``{0..n_categories-1}``
    # stored as shape ``(H, 1)``; ``action_dim`` should be 1.
    n_categories: int | None = None


@dataclass(frozen=True)
class HierCEMConfig:
    """Hierarchical CEM with a registered (fixed) forward-budget split.

    ``upper_budget`` + ``lower_budget`` must equal the shared ``N_fwd`` used to
    construct the ``ForwardCounter``. Shares are not adjusted per episode.
    """

    # Upper (macro) CEM
    macro_horizon: int
    upper_iters: int
    upper_pop: int
    upper_elite_frac: float
    macro_dim: int
    # Lower (raw) CEM over s2 steps
    s2: int
    lower_iters: int
    lower_pop: int
    lower_elite_frac: float
    action_dim: int
    # Optional bounds / std / registered budget split
    macro_low: float | Sequence[float] = -1.0
    macro_high: float | Sequence[float] = 1.0
    upper_init_std: float = 1.0
    action_low: float | Sequence[float] = -1.0
    action_high: float | Sequence[float] = 1.0
    lower_init_std: float = 1.0
    upper_budget: int = 0
    lower_budget: int = 0
    n_exec: int = 1
    n_categories: int | None = None
    n_macro_categories: int | None = None


@dataclass(frozen=True)
class PlanResult:
    actions: np.ndarray
    counts: Mapping[str, Any]
    info: Mapping[str, Any]


def _as_bounds(value: float | Sequence[float], dim: int, horizon: int) -> np.ndarray:
    arr = np.asarray(value, dtype=np.float64)
    if arr.ndim == 0:
        return np.full((horizon, dim), float(arr), dtype=np.float64)
    if arr.shape == (dim,):
        return np.broadcast_to(arr, (horizon, dim)).copy()
    if arr.shape == (horizon, dim):
        return arr.astype(np.float64, copy=True)
    raise ValueError(f"bound shape {arr.shape} incompatible with ({horizon}, {dim})")


def flat_cem_plan(
    *,
    encode: ArrayFn,
    predict_l1: ArrayFn,
    obs: np.ndarray,
    goal_obs: np.ndarray,
    config: FlatCEMConfig,
    rng: np.random.Generator,
    counter: ForwardCounter,
    dts: np.ndarray | None = None,
    cost_fn: Callable[[np.ndarray, np.ndarray], float] | None = None,
) -> PlanResult:
    """Optimize a raw action sequence of length ``H`` with CEM.

    Cost = squared distance between terminal latent and goal encoding by default,
    or custom cost_fn(z_T, goal_obs) when provided (e.g. Arm A observation space matching).
    Only the first ``n_exec`` actions are intended for execution before replan;
    the full elite mean sequence is still returned for inspection.
    """
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be an explicit numpy.random.Generator")

    start_total = counter.total
    z0 = encode(obs)
    if cost_fn is None:
        z_goal = counter.goal_embedding(goal_obs, encode)
    else:
        z_goal = None

    discrete = config.n_categories is not None
    if discrete:
        n_cat = int(config.n_categories)
        probs = np.full((config.horizon, n_cat), 1.0 / n_cat, dtype=np.float64)
        best_seq = np.zeros((config.horizon, 1), dtype=np.float64)
    else:
        low = _as_bounds(config.action_low, config.action_dim, config.horizon)
        high = _as_bounds(config.action_high, config.action_dim, config.horizon)
        mean = 0.5 * (low + high)
        std = np.full_like(mean, float(config.init_std))
        best_seq = mean.copy()

    best_cost = float("inf")
    elite_costs: list[float] = []

    for _ in range(config.n_iters):
        if discrete:
            pop = _sample_categorical(rng, probs, config.pop_size)
        else:
            pop = _sample_actions(rng, mean, std, low, high, config.pop_size)
        costs = np.empty(config.pop_size, dtype=np.float64)
        for i in range(config.pop_size):
            z_T = rollout_l1(predict_l1, z0, pop[i], dts)
            if cost_fn is None:
                costs[i] = squared_distance(z_T, z_goal)
            else:
                costs[i] = cost_fn(z_T, goal_obs)
        n_elite = _elite_count(config.pop_size, config.elite_frac)
        elite_idx = np.argpartition(costs, n_elite - 1)[:n_elite]
        elites = pop[elite_idx]
        elite_costs = [float(c) for c in costs[elite_idx]]
        if discrete:
            probs = _update_categorical_probs(elites, n_cat)
        else:
            mean = elites.mean(axis=0)
            std = elites.std(axis=0) + 1e-6
        best_i = _pick_modal_first_elite(pop, costs, elite_idx)
        if costs[best_i] < best_cost:
            best_cost = float(costs[best_i])
            best_seq = pop[best_i].copy()

    n_exec = max(1, min(config.n_exec, config.horizon))
    exec_actions = best_seq[:n_exec].copy()
    snap = counter.snapshot()
    info = {
        "best_cost": best_cost,
        "elite_costs": elite_costs,
        "n_exec": n_exec,
        "forwards_this_decision": int(counter.total - start_total),
        "full_sequence": best_seq,
        "discrete": discrete,
    }
    return PlanResult(actions=exec_actions, counts=snap, info=info)


def _rollout_l2(
    predict_l2: ArrayFn,
    z0: np.ndarray,
    macros: np.ndarray,
    dts: np.ndarray | None = None,
) -> np.ndarray:
    z = np.asarray(z0, dtype=np.float64)
    macros = np.asarray(macros, dtype=np.float64)
    if macros.ndim == 1:
        macros = macros.reshape(-1, 1)
    horizon = macros.shape[0]
    if dts is None:
        dts = np.ones(horizon, dtype=np.float64)
    else:
        dts = np.asarray(dts, dtype=np.float64).reshape(-1)
    for t in range(horizon):
        z = predict_l2(z, macros[t], float(dts[t]))
    return z


def hierarchical_cem_plan(
    *,
    encode: ArrayFn,
    predict_l1: ArrayFn,
    predict_l2: ArrayFn,
    encode_l2: ArrayFn,
    obs: np.ndarray,
    goal_obs: np.ndarray,
    config: HierCEMConfig,
    rng: np.random.Generator,
    counter: ForwardCounter,
    z2_current: np.ndarray | None = None,
    macro_dts: np.ndarray | None = None,
    raw_dts: np.ndarray | None = None,
) -> PlanResult:
    """Two-level CEM with a shared ``ForwardCounter`` / ``N_fwd``.

    Upper: plan a macro sequence toward the goal encoding → subgoal ``z2_hat``.
    Lower: plan ``s2`` raw actions with cost
    ``||encode_l2(z1_{t+s2}) - z2_subgoal||^2``.

    Budget split (``upper_budget``, ``lower_budget``) is a registered parameter
    and is enforced by nested counters that share the parent charge path; the
    parent ``counter`` remains the single source of truth for ``N_fwd``.
    """
    if not isinstance(rng, np.random.Generator):
        raise TypeError("rng must be an explicit numpy.random.Generator")
    if config.upper_budget < 0 or config.lower_budget < 0:
        raise ValueError("budget shares must be >= 0")
    if counter.budget is not None:
        expected = config.upper_budget + config.lower_budget
        # Encoding of obs/goal is charged to the shared budget outside the split
        # bookkeeping; split values constrain CEM bodies only when both > 0.
        if expected > 0 and expected > counter.budget:
            raise ValueError(
                f"upper_budget+lower_budget ({expected}) exceeds N_fwd ({counter.budget})"
            )

    start_total = counter.total
    z1_0 = encode(obs)
    z1_goal = counter.goal_embedding(goal_obs, encode)
    if z2_current is None:
        z2_0 = encode_l2(z1_0)
    else:
        z2_0 = np.asarray(z2_current, dtype=np.float64)
    z2_goal = encode_l2(z1_goal)

    # ---- Upper CEM (macro → goal encoding in L2) ---------------------------
    upper_start = counter.total
    upper_discrete = config.n_macro_categories is not None
    if upper_discrete:
        n_macro_cat = int(config.n_macro_categories)
        probs_m = np.full(
            (config.macro_horizon, n_macro_cat), 1.0 / n_macro_cat, dtype=np.float64
        )
        best_macros = np.zeros((config.macro_horizon, 1), dtype=np.float64)
    else:
        low_m = _as_bounds(config.macro_low, config.macro_dim, config.macro_horizon)
        high_m = _as_bounds(config.macro_high, config.macro_dim, config.macro_horizon)
        mean_m = 0.5 * (low_m + high_m)
        std_m = np.full_like(mean_m, float(config.upper_init_std))
        best_macros = mean_m.copy()
    best_upper_cost = float("inf")

    for _ in range(config.upper_iters):
        if config.upper_budget > 0 and (counter.total - upper_start) >= config.upper_budget:
            break
        if upper_discrete:
            pop = _sample_categorical(rng, probs_m, config.upper_pop)
        else:
            pop = _sample_actions(rng, mean_m, std_m, low_m, high_m, config.upper_pop)
        costs = np.full(config.upper_pop, np.inf, dtype=np.float64)
        stopped = False
        for i in range(config.upper_pop):
            if config.upper_budget > 0 and (counter.total - upper_start) >= config.upper_budget:
                stopped = True
                break
            z2_T = _rollout_l2(predict_l2, z2_0, pop[i], macro_dts)
            costs[i] = squared_distance(z2_T, z2_goal)
        finite = np.isfinite(costs)
        if not np.any(finite):
            break
        work_costs = np.where(finite, costs, np.inf)
        n_elite = _elite_count(config.upper_pop, config.upper_elite_frac)
        n_elite = max(1, min(n_elite, config.upper_pop))
        elite_idx = np.argpartition(work_costs, n_elite - 1)[:n_elite]
        elites = pop[elite_idx]
        if upper_discrete:
            probs_m = _update_categorical_probs(elites, n_macro_cat)
        else:
            mean_m = elites.mean(axis=0)
            std_m = elites.std(axis=0) + 1e-6
        best_i = _pick_modal_first_elite(pop, work_costs, elite_idx)
        if work_costs[best_i] < best_upper_cost:
            best_upper_cost = float(work_costs[best_i])
            best_macros = pop[best_i].copy()
        if stopped:
            break

    # Subgoal ẑ^{(2)}: first macro step from the upper plan.
    z2_subgoal = predict_l2(
        z2_0, best_macros[0], float(1.0 if macro_dts is None else macro_dts[0])
    )

    # ---- Lower CEM (raw actions → match E₂(z1) to subgoal) -----------------
    lower_start = counter.total
    lower_discrete = config.n_categories is not None
    if lower_discrete:
        n_cat = int(config.n_categories)
        probs_a = np.full((config.s2, n_cat), 1.0 / n_cat, dtype=np.float64)
        best_raw = np.zeros((config.s2, 1), dtype=np.float64)
    else:
        low_a = _as_bounds(config.action_low, config.action_dim, config.s2)
        high_a = _as_bounds(config.action_high, config.action_dim, config.s2)
        mean_a = 0.5 * (low_a + high_a)
        std_a = np.full_like(mean_a, float(config.lower_init_std))
        best_raw = mean_a.copy()
    best_lower_cost = float("inf")
    lower_costs_last: list[float] = []

    for _ in range(config.lower_iters):
        if config.lower_budget > 0 and (counter.total - lower_start) >= config.lower_budget:
            break
        if lower_discrete:
            pop = _sample_categorical(rng, probs_a, config.lower_pop)
        else:
            pop = _sample_actions(rng, mean_a, std_a, low_a, high_a, config.lower_pop)
        costs = np.full(config.lower_pop, np.inf, dtype=np.float64)
        stopped = False
        for i in range(config.lower_pop):
            if config.lower_budget > 0 and (counter.total - lower_start) >= config.lower_budget:
                stopped = True
                break
            z1_T = rollout_l1(predict_l1, z1_0, pop[i], raw_dts)
            # Cost MUST go through E₂ / encode_l2 (DESIGN §4).
            z2_pred = encode_l2(z1_T)
            costs[i] = squared_distance(z2_pred, z2_subgoal)
        finite = np.isfinite(costs)
        if not np.any(finite):
            break
        work_costs = np.where(finite, costs, np.inf)
        n_elite = _elite_count(config.lower_pop, config.lower_elite_frac)
        n_elite = max(1, min(n_elite, config.lower_pop))
        elite_idx = np.argpartition(work_costs, n_elite - 1)[:n_elite]
        elites = pop[elite_idx]
        lower_costs_last = [float(c) for c in work_costs[elite_idx]]
        if lower_discrete:
            probs_a = _update_categorical_probs(elites, n_cat)
        else:
            mean_a = elites.mean(axis=0)
            std_a = elites.std(axis=0) + 1e-6
        best_i = _pick_modal_first_elite(pop, work_costs, elite_idx)
        if work_costs[best_i] < best_lower_cost:
            best_lower_cost = float(work_costs[best_i])
            best_raw = pop[best_i].copy()
        if stopped:
            break
    n_exec = max(1, min(config.n_exec, config.s2))
    exec_actions = best_raw[:n_exec].copy()
    snap = counter.snapshot()
    info = {
        "best_upper_cost": best_upper_cost,
        "best_lower_cost": best_lower_cost,
        "lower_elite_costs": lower_costs_last,
        "z2_subgoal": z2_subgoal,
        "macros": best_macros,
        "n_exec": n_exec,
        "upper_forwards": int(lower_start - upper_start),
        "lower_forwards": int(counter.total - lower_start),
        "forwards_this_decision": int(counter.total - start_total),
        "upper_budget": config.upper_budget,
        "lower_budget": config.lower_budget,
        "full_raw_sequence": best_raw,
    }
    return PlanResult(actions=exec_actions, counts=snap, info=info)
