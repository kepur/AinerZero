"""Learned-model planning for S2 Phase 1 (DESIGN-r2 appendix D3 / D3.1).

Authority:
- planners: ``planner.flat_cem_plan`` / ``planner.hierarchical_cem_plan``;
- closed loop: ``eval.run_episode`` (this module only builds its ``plan_fn``);
- counting: ``fwd_counter.ForwardCounter``;
- CEM parameters: ``cem_config_for_budget`` (D3.1) is the single place that
  derives population / iterations from ``N_fwd``.

Truth isolation: ``plan_fn`` takes only the student observation, the goal
observation, the announced ``k``, the counter and the rng. It never receives or
forwards world state, layout, goal state or episode spec, and never sets
attributes on the model.

Observation features follow the training data convention: the ``dt`` slot of an
observation is the ``k`` announced for the step about to be executed
(``data.py``), so ``plan_fn`` featurizes ``obs`` with ``dt = k``. The goal
observation is featurized with ``last_action = GOAL_FEATURE_LAST_ACTION`` and
``dt = GOAL_FEATURE_DT`` (episode-start convention).
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping

import numpy as np

from ainerzero.v9.experiments.s2 import planner, spec
from ainerzero.v9.experiments.s2.fwd_counter import ForwardCounter

FLAT_KINDS = ("arm_a", "arm_b", "a", "b", "flat")
HIER_KINDS = ("arm_c", "arm_d", "c", "d", "hierarchical")


def arm_kind_of(arm: str) -> str:
    """Map an arm id to ``"flat"`` or ``"hierarchical"``; unknown ids raise."""
    norm = str(arm).strip().lower()
    if norm in FLAT_KINDS:
        return "flat"
    if norm in HIER_KINDS:
        return "hierarchical"
    raise ValueError(f"unknown arm kind {arm!r}")


def expected_k(distribution: Mapping[int, float] | None = None) -> float:
    """E[k] from the registered k distribution (spec.K_DISTRIBUTION)."""
    dist = spec.K_DISTRIBUTION if distribution is None else distribution
    total = float(sum(dist.values()))
    if not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"k distribution must sum to 1, got {total}")
    return float(sum(int(k) * float(p) for k, p in dist.items()))


def _require_pop(name: str, pop: int) -> int:
    if pop < int(spec.CEM_MIN_POP):
        raise ValueError(
            f"{name} population {pop} < CEM_MIN_POP={spec.CEM_MIN_POP}: N_fwd too small for this plan choice"
        )
    return int(pop)


def cem_config_for_budget(
    arm_kind: str,
    plan_choice: Mapping[str, Any],
    n_fwd: int,
) -> planner.FlatCEMConfig | planner.HierCEMConfig:
    """Derive the CEM configuration from a plan choice and N_fwd (DESIGN-r2 D3.1)."""
    if plan_choice is None:
        raise ValueError("plan_choice is required (no default plan configuration)")
    kind = arm_kind_of(arm_kind)
    n_fwd = int(n_fwd)
    usable = n_fwd - int(spec.CEM_ENCODE_RESERVE)
    if usable <= 0:
        raise ValueError(f"N_fwd={n_fwd} leaves no budget after encode reserve {spec.CEM_ENCODE_RESERVE}")
    n_iters = int(spec.CEM_N_ITERS)
    elite = float(spec.CEM_ELITE_FRAC)
    n_exec = int(spec.PLAN_REPLAN_EVERY_OBS_STEPS)
    n_cat = int(spec.ACTION_DIM)

    if kind == "flat":
        if set(plan_choice) != {"H"}:
            raise ValueError(f"flat plan_choice must be exactly {{'H'}}, got {sorted(plan_choice)}")
        h = int(plan_choice["H"])
        if h not in tuple(spec.FLAT_H_CANDIDATES):
            raise ValueError(f"H={h} not in registered FLAT_H_CANDIDATES {spec.FLAT_H_CANDIDATES}")
        pop = _require_pop("flat", usable // (n_iters * h))
        return planner.FlatCEMConfig(
            horizon=h,
            n_iters=n_iters,
            pop_size=pop,
            elite_frac=elite,
            action_dim=1,
            n_exec=n_exec,
            n_categories=n_cat,
        )

    if set(plan_choice) != {"macro_horizon", "budget_ratio"}:
        raise ValueError(
            "hierarchical plan_choice must be exactly {'macro_horizon', 'budget_ratio'}, "
            f"got {sorted(plan_choice)}"
        )
    m = int(plan_choice["macro_horizon"])
    rho = float(plan_choice["budget_ratio"])
    if m not in tuple(spec.HIERARCHICAL_HORIZON_CANDIDATES):
        raise ValueError(f"macro_horizon={m} not in {spec.HIERARCHICAL_HORIZON_CANDIDATES}")
    if not any(math.isclose(rho, c) for c in spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES):
        raise ValueError(f"budget_ratio={rho} not in {spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES}")
    s2 = int(spec.S2_MACRO_STEPS)
    upper_budget = int(math.floor(rho * usable))
    lower_budget = usable - upper_budget
    upper_pop = _require_pop("upper", upper_budget // (n_iters * m))
    lower_pop = _require_pop("lower", lower_budget // (n_iters * (s2 + 1)))
    return planner.HierCEMConfig(
        macro_horizon=m,
        upper_iters=n_iters,
        upper_pop=upper_pop,
        upper_elite_frac=elite,
        macro_dim=int(spec.MACRO_ACTION_DIM),
        s2=s2,
        lower_iters=n_iters,
        lower_pop=lower_pop,
        lower_elite_frac=elite,
        action_dim=1,
        macro_low=-1.0,
        macro_high=1.0,
        upper_budget=upper_budget,
        lower_budget=lower_budget,
        n_exec=n_exec,
        n_categories=n_cat,
        n_macro_categories=None,
    )


def denormalize_macro(u: np.ndarray) -> np.ndarray:
    """Map CEM macro sample(s) in [-1, 1]^7 to (dx, dy, dpsi, histogram[4])."""
    arr = np.clip(np.asarray(u, dtype=np.float64), -1.0, 1.0)
    macro_dim = int(spec.MACRO_ACTION_DIM)
    scale = float(spec.MACRO_DXY_SCALE)
    if arr.ndim == 1:
        if arr.shape[0] != macro_dim:
            raise ValueError(f"macro sample dim {arr.shape[0]} != MACRO_ACTION_DIM {macro_dim}")
        out = np.empty_like(arr)
        out[0] = arr[0] * scale
        out[1] = arr[1] * scale
        out[2] = arr[2] * math.pi
        hist = (arr[3:] + 1.0) / 2.0
        s = float(hist.sum())
        out[3:] = hist / s if s > 0 else np.full(hist.shape, 1.0 / hist.shape[0])
        return out
    elif arr.ndim == 2:
        if arr.shape[1] != macro_dim:
            raise ValueError(f"macro sample dim {arr.shape[1]} != MACRO_ACTION_DIM {macro_dim}")
        out = np.empty_like(arr)
        out[:, 0] = arr[:, 0] * scale
        out[:, 1] = arr[:, 1] * scale
        out[:, 2] = arr[:, 2] * math.pi
        hist = (arr[:, 3:] + 1.0) / 2.0
        s = hist.sum(axis=-1, keepdims=True)
        out[:, 3:] = np.where(s > 0, hist / np.maximum(s, 1e-12), 1.0 / hist.shape[1])
        return out
    else:
        raise ValueError(f"unsupported macro sample shape {arr.shape}")


def featurize_obs(obs: Mapping[str, Any], k: int) -> np.ndarray:
    """Student observation -> OBS_DIM vector with the announced k in the dt slot."""
    from ainerzero.v9.experiments.s2.train_runner import flatten_student_obs

    feat = dict(obs)
    feat["dt"] = int(k)
    return flatten_student_obs(feat)


def featurize_goal(goal_obs: Mapping[str, Any]) -> np.ndarray:
    """Goal observation -> OBS_DIM vector (episode-start convention, D3.1)."""
    from ainerzero.v9.experiments.s2.train_runner import flatten_student_obs

    n_act = int(spec.ACTION_DIM)
    feat = {
        "view": goal_obs["view"],
        "heading": goal_obs["heading"],
        "last_action": [1 if i == int(spec.GOAL_FEATURE_LAST_ACTION) else 0 for i in range(n_act)],
        "dt": int(spec.GOAL_FEATURE_DT),
    }
    return flatten_student_obs(feat)


def _dts(first_k: int, length: int, per_step: float) -> np.ndarray:
    out = np.full(int(length), float(per_step), dtype=np.float64)
    out[0] = float(first_k)
    return out


def make_plan_fn(
    model: Any,
    arm_kind: str,
    plan_choice: Mapping[str, Any],
    n_fwd: int,
) -> Callable[..., planner.PlanResult]:
    """Build the ``plan_fn`` that ``eval.run_episode`` calls at each decision.

    The returned callable accepts exactly ``obs, goal_obs, k, counter, rng``;
    ``run_episode`` inspects the signature and therefore never passes truth.
    ``counter`` must be the episode's ``ForwardCounter`` (budget set to N_fwd).
    """
    kind = arm_kind_of(arm_kind)
    config = cem_config_for_budget(arm_kind, plan_choice, n_fwd)
    n_fwd = int(n_fwd)
    e_k = expected_k()
    for name in ("encode", "predict_l1"):
        if not callable(getattr(model, name, None)):
            raise AttributeError(f"model lacks required planning method {name!r}")
    if kind == "hierarchical":
        for name in ("encode_l2", "predict_l2"):
            if not callable(getattr(model, name, None)):
                raise AttributeError(f"hierarchical model lacks required method {name!r}")
    # The episode counter is the only one charged; an adapter carrying its own
    # counter would double count, and plan_fn never mutates the model to fix it.
    if getattr(model, "counter", None) is not None:
        raise ValueError("model must be built with counter=None; plan_fn charges the episode counter")

    def plan_fn(
        obs: Mapping[str, Any],
        goal_obs: Mapping[str, Any],
        k: int,
        counter: ForwardCounter,
        rng: np.random.Generator,
    ) -> planner.PlanResult:
        if not isinstance(rng, np.random.Generator):
            raise TypeError("rng must be a numpy Generator supplied by the caller")
        if not isinstance(counter, ForwardCounter):
            raise TypeError("counter must be the episode ForwardCounter")
        if counter.budget != n_fwd:
            raise ValueError(f"counter budget {counter.budget} != N_fwd {n_fwd}")

        enc = counter.wrap("encode", model.encode)
        p1 = counter.wrap("predict_l1", model.predict_l1)
        x_obs = featurize_obs(obs, k)
        x_goal = featurize_goal(goal_obs)

        if kind == "flat":
            dts = np.full(config.horizon, float(spec.PLAN_FUTURE_DT_L1), dtype=np.float64)
            dts[0] = float(k)
            return planner.flat_cem_plan(
                encode=enc,
                predict_l1=p1,
                obs=x_obs,
                goal_obs=x_goal,
                config=config,
                rng=rng,
                counter=counter,
                dts=dts,
                cost_mode=spec.PLAN_COST_TRAJECTORY_SUM,
            )

        enc2 = counter.wrap("encode_l2", model.encode_l2)
        raw_p2 = model.predict_l2

        def _p2(z2: np.ndarray, u: np.ndarray, dt2: float = 1.0) -> np.ndarray:
            return raw_p2(z2, denormalize_macro(u), dt2)

        p2 = counter.wrap("predict_l2", _p2)
        s2 = int(config.s2)
        macro_dts = np.full(config.macro_horizon, float(spec.PLAN_FUTURE_DT_L2), dtype=np.float64)
        macro_dts[0] = float(k) + float(round((s2 - 1) * e_k))
        raw_dts = np.full(s2, float(spec.PLAN_FUTURE_DT_L1), dtype=np.float64)
        raw_dts[0] = float(k)
        return planner.hierarchical_cem_plan(
            encode=enc,
            predict_l1=p1,
            predict_l2=p2,
            encode_l2=enc2,
            obs=x_obs,
            goal_obs=x_goal,
            config=config,
            rng=rng,
            counter=counter,
            macro_dts=macro_dts,
            raw_dts=raw_dts,
        )

    return plan_fn
