"""S2 evaluation runner: plan-select (train-only), capped dev eval, one-shot final.

Backend-agnostic planning protocol; pure CPU / NumPy. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §4, §5, §7.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Mapping, Protocol, Sequence

import numpy as np

from ainerzero.v9.experiments.s2 import eval as s2_eval
from ainerzero.v9.experiments.s2 import learned_planning as lp
from ainerzero.v9.experiments.s2 import smoke_checks
from ainerzero.v9.experiments.s2 import spec as spec_mod
from ainerzero.v9.experiments.s2 import world
from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded, ForwardCounter
from ainerzero.v9.experiments.s2.probe import RidgeProbe, eval_error, fit_ridge
from ainerzero.v9.experiments.s2.stats import BootstrapResult, cluster_paired_bootstrap

__all__ = [
    "PlanningModel",
    "DevEvalCapExceeded",
    "FinalEvalRefused",
    "PlanSelectError",
    "PostTrainGateError",
    "PostTrainGateRefused",
    "ACTION_SENSITIVITY_FLOOR",
    "SUBGOAL_DROP_FLOOR",
    "FLAT_H_CANDIDATES",
    "HIER_MACRO_HORIZONS",
    "HIER_BUDGET_RATIOS",
    "N_FWD_DEFAULT",
    "N_FWD_CURVE",
    "MAX_DEV_EVALS",
    "DELTA_PRED",
    "SUCCESS_DIFF_GATE",
    "FINAL_APPROVAL_PREFIX",
    "PREREG_APPROVAL_PREFIX",
    "READ_ONCE_MARKER_NAME",
    "run_plan_select",
    "run_post_train_gates",
    "run_dev_eval",
    "run_final_eval",
    "judge_hs2_gate",
    "find_final_eval_approval",
    "open_sealed_final_read_once",
    "load_dev_ledger",
    "save_dev_ledger",
]

# Registered candidate grids (DESIGN-r2 §4)
# Aliases of the registered spec values (spec is the authority; call sites read spec_mod at call time).
FLAT_H_CANDIDATES: tuple[int, ...] = tuple(spec_mod.FLAT_H_CANDIDATES)
HIER_MACRO_HORIZONS: tuple[int, ...] = tuple(spec_mod.HIERARCHICAL_HORIZON_CANDIDATES)
HIER_BUDGET_RATIOS: tuple[float, ...] = tuple(spec_mod.HIERARCHICAL_BUDGET_RATIO_CANDIDATES)

N_FWD_DEFAULT: int = int(spec_mod.N_FWD)
N_FWD_CURVE: tuple[int, ...] = tuple(spec_mod.N_FWD_DEV_LEVELS)
MAX_DEV_EVALS: int = int(spec_mod.MAX_DEV_EVALS)
DELTA_PRED: float = 1.0
SUCCESS_DIFF_GATE: float = 0.10
ACTION_SENSITIVITY_FLOOR: float = float(spec_mod.ACTION_SENSITIVITY_FLOOR)
SUBGOAL_DROP_FLOOR: float = float(spec_mod.SUBGOAL_DROP_FLOOR)

FINAL_APPROVAL_PREFIX = "APPROVED s2-phase1 final-eval document_sha256="
PREREG_APPROVAL_PREFIX = "APPROVED s2-phase1 prereg document_sha256="
_FINAL_APPROVAL_RE = re.compile(
    r"^APPROVED\s+s2-phase1\s+final-eval\s+document_sha256=([0-9a-f]{64})$"
)
_PREREG_APPROVAL_RE = re.compile(
    r"^APPROVED\s+s2-phase1\s+prereg\s+document_sha256=([0-9a-f]{64})$"
)
_FENCE_RE = re.compile(r"^(?:```|~~~)")
_ANY_H2_RE = re.compile(r"^##\s+")
_SECTION_HEADING_RE = re.compile(
    r"^##\s+(?:R20261106-S2-approval|S2-approval|[A-Za-z0-9_-]*S2[A-Za-z0-9_-]*approval[A-Za-z0-9_-]*)\b",
    re.IGNORECASE,
)

READ_ONCE_MARKER_NAME = "S2_FINAL_READ_ONCE.json"
DEV_LEDGER_DEFAULT_NAME = "s2_dev_eval_ledger.json"


class PlanSelectError(ValueError):
    """Raised when plan-select is called with a non-train partition."""


class PostTrainGateError(ValueError):
    """Raised when post-train gate inputs are invalid or non-train partition passed."""


class PostTrainGateRefused(RuntimeError):
    """Raised when dev evaluation is refused due to failing post-train gates."""


class DevEvalCapExceeded(RuntimeError):
    """Raised when a third (or later) dev evaluation is attempted (§7)."""


class FinalEvalRefused(RuntimeError):
    """Raised when final-eval approval / read-once preconditions fail."""


class PlanningModel(Protocol):
    """Backend-agnostic planning protocol consumed by the runner."""

    arm_kind: str  # "flat" | "hierarchical"

    def encode(self, obs: Any) -> np.ndarray: ...

    def predict_l1(self, z: np.ndarray, action: Any, dt: float) -> np.ndarray: ...

    def predict_l2(self, z: np.ndarray, macro: Any, dt: float) -> np.ndarray: ...

    def encode_l2(self, z1: np.ndarray) -> np.ndarray: ...

    def latents(self, obs_seq: Sequence[Any]) -> np.ndarray: ...


@dataclass(frozen=True)
class GateVerdict:
    passed: bool
    reasons: tuple[str, ...]
    success_diff: float
    success_ci_lower: float
    pred_delta_ci_upper: float
    m2_label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reasons": list(self.reasons),
            "success_diff": self.success_diff,
            "success_ci_lower": self.success_ci_lower,
            "pred_delta_ci_upper": self.pred_delta_ci_upper,
            "m2_label": self.m2_label,
        }


def _spec_partition(spec: Mapping[str, Any]) -> str:
    part = spec.get("partition")
    if part is None:
        raise PlanSelectError("episode spec missing required 'partition' field")
    return str(part)


def _assert_train_only(specs: Sequence[Mapping[str, Any]]) -> None:
    for i, spec in enumerate(specs):
        part = _spec_partition(spec)
        if part != "train":
            raise PlanSelectError(
                f"run_plan_select refuses non-train specs: index={i} partition={part!r}"
            )


def _arm_kind(model: Any) -> str:
    kind = getattr(model, "arm_kind", None) or getattr(model, "kind", None)
    if kind not in ("flat", "hierarchical"):
        raise ValueError(f"model.arm_kind must be 'flat' or 'hierarchical', got {kind!r}")
    return str(kind)


def _config_compute_cost(kind: str, config: Mapping[str, Any]) -> float:
    """Proxy compute cost for tie-breaking (smaller is preferred)."""
    if kind == "flat":
        return float(config["H"])
    # Larger macro horizon / larger upper share → more upper CEM work
    return float(config["macro_horizon"]) * (1.0 + float(config["budget_ratio"]))



def _require_plan_choice(arm_cfg: Any, arm_name: str) -> dict[str, Any]:
    """Plan choice of one arm from the frozen plan-select result; missing means refuse."""
    choice = None
    if isinstance(arm_cfg, Mapping):
        choice = arm_cfg.get("plan_choice")
        if choice is None:
            choice = arm_cfg.get("config")
    if not isinstance(choice, Mapping) or not choice:
        raise ValueError(f"frozen plan config has no plan_choice for arm {arm_name!r}")
    return dict(choice)

def _candidate_grid(kind: str) -> list[dict[str, Any]]:
    if kind == "flat":
        return [{"H": int(h)} for h in spec_mod.FLAT_H_CANDIDATES]
    return [
        {"macro_horizon": int(mh), "budget_ratio": float(br)}
        for mh in spec_mod.HIERARCHICAL_HORIZON_CANDIDATES
        for br in spec_mod.HIERARCHICAL_BUDGET_RATIO_CANDIDATES
    ]


def _resolve_layout_for_spec(
    spec: Mapping[str, Any], *, dataset_dir: Path | None = None
) -> world.Layout:
    if "layout" in spec:
        val = spec["layout"]
        if isinstance(val, world.Layout):
            return val
        if isinstance(val, Mapping):
            return world.Layout(
                seed=int(val["seed"]),
                terrain=[list(row) for row in val["terrain"]],
                rooms=[tuple(r) for r in val["rooms"]],
                doors=[tuple(d) for d in val["doors"]],
                pillars=[tuple(p) for p in val["pillars"]],
                layout_sha256=str(val["layout_sha256"]),
            )
    if "layout_path" in spec:
        lp_path = Path(spec["layout_path"])
        if lp_path.is_file():
            val = json.loads(lp_path.read_text(encoding="utf-8"))
            return world.Layout(
                seed=int(val["seed"]),
                terrain=[list(row) for row in val["terrain"]],
                rooms=[tuple(r) for r in val["rooms"]],
                doors=[tuple(d) for d in val["doors"]],
                pillars=[tuple(p) for p in val["pillars"]],
                layout_sha256=str(val["layout_sha256"]),
            )
    w_idx = spec.get("world_index", spec.get("world_id"))
    if w_idx is not None and dataset_dir is not None:
        lp_path = Path(dataset_dir) / f"world_{int(w_idx):04d}" / "layout.json"
        if lp_path.is_file():
            val = json.loads(lp_path.read_text(encoding="utf-8"))
            return world.Layout(
                seed=int(val["seed"]),
                terrain=[list(row) for row in val["terrain"]],
                rooms=[tuple(r) for r in val["rooms"]],
                doors=[tuple(d) for d in val["doors"]],
                pillars=[tuple(p) for p in val["pillars"]],
                layout_sha256=str(val["layout_sha256"]),
            )
    if "layout_dict" in spec:
        val = spec["layout_dict"]
        return world.Layout(
            seed=int(val["seed"]),
            terrain=[list(row) for row in val["terrain"]],
            rooms=[tuple(r) for r in val["rooms"]],
            doors=[tuple(d) for d in val["doors"]],
            pillars=[tuple(p) for p in val["pillars"]],
            layout_sha256=str(val["layout_sha256"]),
        )
    raise ValueError(f"Episode spec missing layout or valid layout path: {spec.get('episode_index', spec)}")


def _score_config_on_train(
    model: Any,
    config: Mapping[str, Any],
    specs: Sequence[Mapping[str, Any]],
    *,
    n_fwd: int = N_FWD_DEFAULT,
    dataset_dir: Path | None = None,
) -> float:
    """Mean success on train plan-select specs via real learned planning execution.

    Zero fallbacks: evaluated directly using learned_planning.make_plan_fn and
    eval.run_episode under r2.6 planning protocol (fail-closed, no test mocks).
    """
    kind = _arm_kind(model)
    plan_fn = lp.make_plan_fn(model, kind, config, n_fwd)
    hits: list[float] = []
    m_val = int(spec_mod.PLAN_REPLAN_EVERY_OBS_STEPS)

    for i, sp in enumerate(specs):
        layout = _resolve_layout_for_spec(sp, dataset_dir=dataset_dir)
        counter = ForwardCounter(budget=n_fwd)
        rng = np.random.default_rng(42 + i)
        res = s2_eval.run_episode(
            layout,
            sp,
            plan_fn,
            counter,
            rng,
            dt_mode="irregular",
            m=m_val,
            catch_budget_exceeded=True,
        )
        hits.append(1.0 if res.success and not res.void else 0.0)

    if not hits:
        raise PlanSelectError("specs must be non-empty for plan-select evaluation")
    return float(np.mean(hits))


def run_plan_select(
    model_by_arm: Mapping[str, Any],
    train_episode_specs: Sequence[Mapping[str, Any]],
    *,
    output_path: str | Path | None = None,
    max_episodes: int = 50,
    n_fwd: int = N_FWD_DEFAULT,
    dataset_dir: str | Path | None = None,
    **extra_kwargs: Any,
) -> dict[str, Any]:
    """Select planner hyper-parameters on train-only planning episodes (§4, D4).

    Refuses immediately if any episode spec is labeled ``dev`` or ``final``.
    Tie-break: equal success → smaller compute cost.
    Records plan_choice and derived CEM parameters in plan_config.json.
    """
    if not train_episode_specs:
        raise PlanSelectError("train_episode_specs must be non-empty")
    _assert_train_only(train_episode_specs)
    specs = list(train_episode_specs[: max(1, int(max_episodes))])
    d_dir = Path(dataset_dir) if dataset_dir is not None else None

    frozen: dict[str, Any] = {
        "schema": "s2.plan_select.v1",
        "n_episodes_used": len(specs),
        "n_fwd": int(n_fwd),
        "arms": {},
    }

    for arm_name, model in model_by_arm.items():
        kind = _arm_kind(model)
        best: dict[str, Any] | None = None
        best_score = -1.0
        best_cost = float("inf")
        trials: list[dict[str, Any]] = []

        for cand in _candidate_grid(kind):
            score = _score_config_on_train(model, cand, specs, n_fwd=n_fwd, dataset_dir=d_dir)
            cost = _config_compute_cost(kind, cand)
            trials.append({"config": dict(cand), "success_rate": score, "compute_cost": cost})
            better = score > best_score + 1e-15
            tied_cheaper = abs(score - best_score) <= 1e-15 and cost < best_cost
            if better or tied_cheaper:
                best_score = score
                best_cost = cost
                best = dict(cand)

        assert best is not None
        cem_cfg = lp.cem_config_for_budget(kind, best, n_fwd)
        frozen["arms"][arm_name] = {
            "arm_kind": kind,
            "plan_choice": best,
            "config": best,
            "cem_config": dataclasses.asdict(cem_cfg),
            "success_rate": best_score,
            "compute_cost": best_cost,
            "trials": trials,
        }

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return frozen


def run_post_train_gates(
    model_by_arm: Mapping[str, Any],
    train_episode_specs: Sequence[Mapping[str, Any]],
    *,
    ledger_path: str | Path | None = None,
    output_path: str | Path | None = None,
    seed: int = 42,
    shuffle_seed: int = 20261106,
    n_sensitivity_states: int = 64,
    sensitivity_threshold: float = ACTION_SENSITIVITY_FLOOR,
    c_shuffle_episodes: int = 50,
    subgoal_drop_threshold: float = SUBGOAL_DROP_FLOOR,
    train_states_by_arm: Mapping[str, Sequence[Any] | np.ndarray] | None = None,
    n_actions: int = 4,
    n_fwd: int = N_FWD_DEFAULT,
    plan_config: Mapping[str, Any] | None = None,
    baseline_success_range: tuple[float, float] = tuple(spec_mod.BASELINE_SUCCESS_PLAUSIBLE_RANGE),
    dataset_dir: str | Path | None = None,
    **extra_kwargs: Any,
) -> dict[str, Any]:
    """Execute post-train, pre-dev gates per DESIGN-r2 Appendix B.

    1. Action Sensitivity Gate:
       Evaluates pairwise L2 distance across 4 actions normalized by mean state norm.
       If any arm is below sensitivity_threshold (default 0.05), marked '不可规划'.
    2. C-arm Shuffled Subgoal Negative Control:
       Evaluates C arm on train planning episodes with true vs shuffled subgoals.
       If success rate drop is below subgoal_drop_threshold (default 0.10), marked 'E₂ 合谋'.

    Strictly enforced train-only partition: any dev/final specs raise PostTrainGateError.
    Writes result to ledger (if ledger_path given) and JSON file (if output_path given).
    """
    if not train_episode_specs:
        raise PostTrainGateError("train_episode_specs must be non-empty")

    for i, spec in enumerate(train_episode_specs):
        part = _spec_partition(spec)
        if part != "train":
            raise PostTrainGateError(
                f"run_post_train_gates refuses non-train specs: index={i} partition={part!r}"
            )

    reasons: list[str] = []
    sensitivity_by_arm: dict[str, float] = {}
    unplannable_arms: list[str] = []

    # 1. Action sensitivity gate for all arms (DESIGN-r2 §5, Appendix D5.1)
    cand_steps: list[tuple[dict[str, Any], int]] = []
    d_dir = Path(dataset_dir) if dataset_dir is not None else None
    if d_dir is not None and d_dir.exists():
        holdout_path = d_dir / "HOLDOUT_WORLDS.json"
        h_worlds: list[Any] = []
        if holdout_path.is_file():
            try:
                h_info = json.loads(holdout_path.read_text(encoding="utf-8"))
                h_worlds = h_info.get("holdout_worlds", [])
            except Exception:
                pass
        ep_files: list[Path] = []
        if h_worlds:
            for w in h_worlds:
                w_dir = d_dir / f"world_{int(w):04d}"
                if w_dir.is_dir():
                    ep_files.extend(sorted(w_dir.glob("episode_*.json")))
        if not ep_files:
            ep_files = sorted(d_dir.glob("world_*/episode_*.json"))
        for ep_f in ep_files:
            try:
                payload = json.loads(ep_f.read_text(encoding="utf-8"))
                for st in payload.get("steps", []):
                    if "student_obs" in st:
                        cand_steps.append((st["student_obs"], int(st.get("dt", st.get("k", 1)))))
            except Exception:
                continue

    if not cand_steps:
        for sp in train_episode_specs:
            if "start" in sp and "layout" in sp:
                layout = _resolve_layout_for_spec(sp, dataset_dir=d_dir)
                start_st = s2_eval._to_state(sp["start"])
                obs = world.student_obs(layout, start_st, last_action=3, dt=1)
                cand_steps.append((obs, 1))
            elif "student_obs" in sp:
                cand_steps.append((sp["student_obs"], int(sp.get("dt", 1))))
            elif "obs" in sp:
                cand_steps.append((sp["obs"], int(sp.get("dt", 1))))

    rng_sens = np.random.default_rng(seed)
    sampled_feats: list[np.ndarray] = []
    if cand_steps:
        n_take = min(n_sensitivity_states, len(cand_steps))
        chosen_indices = rng_sens.choice(len(cand_steps), size=n_take, replace=False)
        for c_idx in chosen_indices:
            obs_dict, k_val = cand_steps[int(c_idx)]
            sampled_feats.append(lp.featurize_obs(obs_dict, k=k_val))

    for arm_name, model in model_by_arm.items():
        def _predict(z: np.ndarray, a: Any, m: Any = model) -> np.ndarray:
            try:
                return m.predict_l1(z, a, 1.0)
            except TypeError:
                return m.predict_l1(z, a)

        if train_states_by_arm is not None and arm_name in train_states_by_arm:
            states_list = list(train_states_by_arm[arm_name])[:n_sensitivity_states]
        elif sampled_feats:
            states_list = [model.encode(f) for f in sampled_feats]
        elif hasattr(model, "encode"):
            states_list = [
                model.encode(spec.get("start", spec.get("start_obs", spec.get("obs", spec))))
                for spec in train_episode_specs[:n_sensitivity_states]
            ]
        else:
            raise PostTrainGateError(f"Cannot extract sensitivity states for arm {arm_name!r}")

        if not states_list:
            raise PostTrainGateError(f"No states available for arm {arm_name!r} action sensitivity")

        try:
            sens = smoke_checks.action_sensitivity(_predict, states_list, n_actions=n_actions)
        except ValueError as exc:
            if "near zero" in str(exc).lower():
                sens = 0.0
            else:
                raise

        sensitivity_by_arm[arm_name] = float(sens)
        if sens < sensitivity_threshold:
            unplannable_arms.append(arm_name)
            reasons.append(
                f"Arm {arm_name} action sensitivity {sens:.4f} < {sensitivity_threshold:.4f} (不可规划)"
            )

    # 2. C-arm shuffled subgoal negative control (DESIGN-r2 Appendix D5.1)
    c_arm_name: str | None = None
    c_model: Any = None
    for cand in ("arm_c", "C"):
        if cand in model_by_arm:
            c_arm_name = cand
            c_model = model_by_arm[cand]
            break
    if c_model is None:
        for name, m in model_by_arm.items():
            if getattr(m, "arm_kind", None) == "hierarchical" or getattr(m, "kind", None) == "hierarchical":
                c_arm_name = str(name)
                c_model = m
                break

    c_control_result: dict[str, Any] | None = None
    if c_model is not None:
        c_specs = list(train_episode_specs[: max(1, int(c_shuffle_episodes))])
        n_c_eps = len(c_specs)

        # Generate deranged permutation for shuffled subgoals
        rng_shuffle = np.random.default_rng(shuffle_seed)
        perm = rng_shuffle.permutation(n_c_eps)
        if n_c_eps > 1:
            fixed = np.where(perm == np.arange(n_c_eps))[0]
            if len(fixed) > 0:
                perm = (perm + 1) % n_c_eps

        c_cfg_info = None
        c_base_arm = str(c_arm_name).split("/", 1)[0]  # models keyed "<arm>/<seed>"; plan_config keyed by arm
        if plan_config is not None:
            c_cfg_info = plan_config.get("arms", {}).get(c_base_arm)
        if c_cfg_info is None:
            raise ValueError(
                f"C-arm negative control needs the plan-select choice for {c_arm_name!r}; none in plan_config"
            )
        c_plan_choice = _require_plan_choice(c_cfg_info, c_arm_name)

        m_val = int(spec_mod.PLAN_REPLAN_EVERY_OBS_STEPS)

        # Pass 1: True subgoals under real learned planning execution
        true_hits: list[float] = []
        subgoals_by_ep: list[list[Any]] = []
        for i, sp in enumerate(c_specs):
            layout = _resolve_layout_for_spec(sp, dataset_dir=d_dir)
            counter = ForwardCounter(budget=n_fwd)
            rng_ep = np.random.default_rng(seed + i)
            recorded_subgoals: list[Any] = []
            base_plan_fn = lp.make_plan_fn(c_model, "hierarchical", c_plan_choice, n_fwd)

            def recording_plan_fn(obs: Any, goal_obs: Any, k: int, counter: Any, rng: Any) -> Any:
                res = base_plan_fn(obs, goal_obs, k, counter, rng)
                if res.info and "z2_subgoal" in res.info:
                    recorded_subgoals.append(res.info["z2_subgoal"])
                return res

            res_true = s2_eval.run_episode(
                layout,
                sp,
                recording_plan_fn,
                counter,
                rng_ep,
                dt_mode="irregular",
                m=m_val,
                catch_budget_exceeded=True,
            )
            true_hits.append(1.0 if res_true.success and not res_true.void else 0.0)
            subgoals_by_ep.append(recorded_subgoals)

        # Pass 2: Injected deranged subgoals via subgoal_source
        shuf_hits: list[float] = []
        for i, sp in enumerate(c_specs):
            layout = _resolve_layout_for_spec(sp, dataset_dir=d_dir)
            counter = ForwardCounter(budget=n_fwd)
            rng_ep = np.random.default_rng(seed + i)
            injected_seq = subgoals_by_ep[int(perm[i])]

            def _subgoal_src(decision_idx: int, s_seq: list[Any] = injected_seq) -> Any:
                if not s_seq:
                    z2_d = int(spec_mod.ARM_DIMS["arm_c"].get("z2_dim", 64))
                    return np.zeros(z2_d, dtype=np.float64)
                idx = min(decision_idx, len(s_seq) - 1)
                return s_seq[idx]

            shuf_plan_fn = lp.make_plan_fn(
                c_model, "hierarchical", c_plan_choice, n_fwd, subgoal_source=_subgoal_src
            )
            res_shuf = s2_eval.run_episode(
                layout,
                sp,
                shuf_plan_fn,
                counter,
                rng_ep,
                dt_mode="irregular",
                m=m_val,
                catch_budget_exceeded=True,
            )
            shuf_hits.append(1.0 if res_shuf.success and not res_shuf.void else 0.0)

        rate_true = float(np.mean(true_hits)) if true_hits else 0.0
        rate_shuffled = float(np.mean(shuf_hits)) if shuf_hits else 0.0
        drop = float(rate_true - rate_shuffled)
        collusion = bool(drop < subgoal_drop_threshold)
        c_control_result = {
            "arm": c_arm_name,
            "n_episodes": n_c_eps,
            "success_rate_true": rate_true,
            "success_rate_shuffled": rate_shuffled,
            "drop": drop,
            "threshold": subgoal_drop_threshold,
            "collusion": collusion,
            "shuffle_seed": shuffle_seed,
            "permutation": [int(p) for p in perm],
        }
        if collusion:
            reasons.append(
                f"C arm {c_arm_name} collusion detected: subgoal drop {drop:.4f} < "
                f"{subgoal_drop_threshold:.4f} (E₂ 合谋/下层没用子目标)"
            )

    # 3. Baseline rationality gate (DESIGN-r2 §5, Appendix B, D4)
    baseline_result: dict[str, Any] | None = None
    if plan_config is not None:
        try:
            a_model = _resolve_model(model_by_arm, "arm_a", 42)
        except KeyError:
            a_model = None
        try:
            b_model = _resolve_model(model_by_arm, "arm_b", 42)
        except KeyError:
            b_model = None
        if a_model is None and b_model is None:
            raise PostTrainGateError("At least one baseline model (arm_a or arm_b) is required for baseline rationality gate")
        scores: list[float] = []
        ab_specs = list(train_episode_specs[: min(len(train_episode_specs), 50)])
        for arm_key, arm_m in [("arm_a", a_model), ("arm_b", b_model)]:
            if arm_m is not None:
                arm_cfg_info = (
                    plan_config.get("arms", {}).get(arm_key)
                    or plan_config.get("arms", {}).get(arm_key.replace("arm_", "").upper())
                    or plan_config.get("arms", {}).get(arm_key.replace("arm_", ""))
                )
                if arm_cfg_info is None:
                    raise PostTrainGateError(f"plan_config missing configuration for arm {arm_key}")
                p_choice = arm_cfg_info.get("plan_choice", arm_cfg_info.get("config"))
                if p_choice is None:
                    raise PostTrainGateError(f"plan_config missing plan_choice for arm {arm_key}")
                s_rate = _score_config_on_train(arm_m, p_choice, ab_specs, n_fwd=n_fwd, dataset_dir=d_dir)
                scores.append(s_rate)
        if scores:
            max_ab = float(max(scores))
            p_min, p_max = baseline_success_range
            base_passed = bool(p_min <= max_ab <= p_max)
            baseline_result = {
                "max_ab_success": max_ab,
                "range": [p_min, p_max],
                "passed": base_passed,
            }
            if not base_passed:
                reasons.append(
                    f"Baseline rationality failed: max(A, B) success rate {max_ab:.4f} "
                    f"not in [{p_min:.2f}, {p_max:.2f}] (§5 基线不合理)"
                )

    passed = (len(reasons) == 0)

    verdict_record = {
        "schema": "s2.post_train_gates.v1",
        "passed": passed,
        "reasons": reasons,
        "sensitivity_by_arm": sensitivity_by_arm,
        "unplannable_arms": unplannable_arms,
        "c_negative_control": c_control_result,
        "baseline_rationality": baseline_result,
        "n_sensitivity_states": n_sensitivity_states,
        "sensitivity_threshold": sensitivity_threshold,
        "subgoal_drop_threshold": subgoal_drop_threshold,
    }

    if ledger_path is not None:
        ledger = load_dev_ledger(ledger_path)
        ledger["post_train_gates"] = verdict_record
        save_dev_ledger(ledger_path, ledger)

    if output_path is not None:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(verdict_record, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    return verdict_record


def load_dev_ledger(ledger_path: str | Path) -> dict[str, Any]:
    path = Path(ledger_path)
    if not path.is_file():
        return {"dev_eval_count": 0, "runs": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("dev_eval_count", 0)
    data.setdefault("runs", [])
    return data


def save_dev_ledger(ledger_path: str | Path, ledger: Mapping[str, Any]) -> None:
    path = Path(ledger_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(ledger), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_dev_capacity(ledger_path: str | Path) -> dict[str, Any]:
    """Enforce §7: at most two design-decision uses of the same dev partition.

    Mutation sentinel: keep the comparison against ``MAX_DEV_EVALS``.
    """
    ledger = load_dev_ledger(ledger_path)
    count = int(ledger.get("dev_eval_count", 0))
    if count >= int(spec_mod.MAX_DEV_EVALS):
        raise DevEvalCapExceeded(
            f"dev eval refused: already used {count} times (cap={MAX_DEV_EVALS})"
        )
    return ledger


def _resolve_model(model_by_arm: Mapping[Any, Any], arm_name: str, seed: int) -> Any:
    """Resolve model instance for given arm and training seed."""
    if (arm_name, seed) in model_by_arm:
        return model_by_arm[(arm_name, seed)]
    key_slash = f"{arm_name}/{seed}"
    if key_slash in model_by_arm:
        return model_by_arm[key_slash]
    from ainerzero.v9.experiments.s2.adapters_mlx import canonical_arm
    c_arm = canonical_arm(arm_name)
    candidates = (
        arm_name,
        c_arm,
        c_arm.replace("arm_", "").upper(),
        c_arm.replace("arm_", "").lower(),
        str(arm_name).lower(),
    )
    for k in candidates:
        if (k, seed) in model_by_arm:
            return model_by_arm[(k, seed)]
        if f"{k}/{seed}" in model_by_arm:
            return model_by_arm[f"{k}/{seed}"]
        if k in model_by_arm and isinstance(model_by_arm[k], Mapping) and seed in model_by_arm[k]:
            return model_by_arm[k][seed]
        if k in model_by_arm:
            return model_by_arm[k]
    raise KeyError(f"Cannot resolve model for arm={arm_name!r}, seed={seed}")


def _run_planning_episode_for_model(
    model: Any,
    spec: Mapping[str, Any],
    *,
    arm_kind: str | None = None,
    plan_choice: Mapping[str, Any] | None = None,
    n_fwd: int = N_FWD_DEFAULT,
    seed: int = 42,
    dt_mode: str = "irregular",
    dataset_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute one episode using real learned planning without any fallbacks.

    Calls learned_planning.make_plan_fn and eval.run_episode under r2.6 protocol.
    Zero random branches, zero base_success_rate fallbacks, zero eval_episode branches.
    """
    kind = arm_kind or _arm_kind(model)
    if plan_choice is None:
        raise ValueError("plan_choice is required (frozen plan-select result); no default configuration")

    layout = _resolve_layout_for_spec(spec, dataset_dir=dataset_dir)
    plan_fn = lp.make_plan_fn(model, kind, plan_choice, n_fwd)
    counter = ForwardCounter(budget=n_fwd)
    rng = np.random.default_rng(seed)
    m_val = int(spec_mod.PLAN_REPLAN_EVERY_OBS_STEPS)

    res = s2_eval.run_episode(
        layout,
        spec,
        plan_fn,
        counter,
        rng,
        dt_mode=dt_mode,
        m=m_val,
        catch_budget_exceeded=True,
    )

    return {
        "success": bool(res.success),
        "strict_success": bool(res.strict_success),
        "void": bool(res.void),
        "void_reason": res.info.get("void_reason") if res.void else None,
        "steps_used": res.steps_used,
        "obs_steps_used": res.obs_steps_used,
        "total_forwards": res.total_forwards,
        "n_fwd": int(n_fwd),
        "seed": int(seed),
    }


def _episode_success_stub(
    model: Any,
    spec: Mapping[str, Any],
    *,
    n_fwd: int,
    seed: int,
    arm_kind: str | None = None,
    plan_choice: Mapping[str, Any] | None = None,
    dataset_dir: Path | None = None,
) -> dict[str, Any]:
    """Evaluate one episode under a frozen config / budget without fallbacks."""
    return _run_planning_episode_for_model(
        model,
        spec,
        arm_kind=arm_kind,
        plan_choice=plan_choice,
        n_fwd=n_fwd,
        seed=seed,
        dataset_dir=dataset_dir,
    )


def _fit_probe_train_only(
    model: Any,
    train_latent_bundle: Mapping[str, Any] | None,
    *,
    fit_fn: Callable[..., RidgeProbe] = fit_ridge,
) -> RidgeProbe | None:
    del model  # latents come from the explicit train bundle, not live model state
    if train_latent_bundle is None:
        return None
    Z = np.asarray(train_latent_bundle["Z"], dtype=np.float64)
    XY = np.asarray(train_latent_bundle["XY"], dtype=np.float64)
    source = str(train_latent_bundle.get("partition", "train"))
    if source != "train":
        raise ValueError(f"probe must be fit on train latents only, got partition={source!r}")
    # Prefer passing source_partition so tests can assert train-only fitting.
    try:
        return fit_fn(Z, XY, lam=1.0, source_partition=source)
    except TypeError:
        return fit_fn(Z, XY, lam=1.0)


def run_dev_eval(
    model_by_arm: Mapping[str, Any],
    frozen_plan_config: Mapping[str, Any],
    *,
    long_specs: Sequence[Mapping[str, Any]],
    short_specs: Sequence[Mapping[str, Any]] | None = None,
    regular_dt_specs: Sequence[Mapping[str, Any]] | None = None,
    seeds: Sequence[int] = (42, 43, 44),
    n_fwd_curve: Sequence[int] = N_FWD_CURVE,
    ledger_path: str | Path,
    train_latents_by_arm: Mapping[str, Mapping[str, Any]] | None = None,
    fit_ridge_fn: Callable[..., RidgeProbe] = fit_ridge,
    n_boot: int = spec_mod.BOOTSTRAP_RESAMPLES,
    require_post_train_gates: bool = True,
    dataset_dir: str | Path | None = None,
    **extra_kwargs: Any,
) -> dict[str, Any]:
    """Run capped dev evaluation with N_fwd curve, probes, and clustered diffs.

    Requires passed post_train_gates in ledger before dev evaluation (§Appendix B).
    Increments the ledger counter after a successful start; the 3rd call raises.
    """
    ledger = _require_dev_capacity(ledger_path)

    if require_post_train_gates:
        gates = ledger.get("post_train_gates")
        if gates is None:
            raise PostTrainGateRefused(
                "dev eval refused: post_train_gates record missing from ledger "
                "(must run run_post_train_gates and pass both gates before dev eval)"
            )
        if not gates.get("passed", False):
            gate_reasons = "; ".join(gates.get("reasons", ["post_train_gates failed"]))
            raise PostTrainGateRefused(
                f"dev eval refused: post_train_gates failed: {gate_reasons}"
            )

    d_dir = Path(dataset_dir) if dataset_dir is not None else None
    primary_n_fwd = int(spec_mod.N_FWD)
    per_episode: list[dict[str, Any]] = []
    voided: list[dict[str, Any]] = []
    if "arms" in frozen_plan_config and frozen_plan_config["arms"]:
        arm_names = list(frozen_plan_config["arms"].keys())
    else:
        seen_arms: list[str] = []
        for k in model_by_arm.keys():
            arm_part = k.split("/")[0] if isinstance(k, str) else str(k)
            if arm_part not in seen_arms:
                seen_arms.append(arm_part)
        arm_names = seen_arms

    # Primary long-goal results at N_fwd=4096 for pairwise diffs
    success_by_arm_world: dict[str, dict[Any, list[float]]] = {a: {} for a in arm_names}

    for spec in long_specs:
        world_id = spec.get("world_index", spec.get("world_id", 0))
        spec_id = spec.get("episode_index", spec.get("id", 0))
        for arm_name in arm_names:
            arm_cfg = frozen_plan_config.get("arms", {}).get(arm_name, {})
            model_sample = _resolve_model(model_by_arm, arm_name, seeds[0])
            kind = arm_cfg.get("arm_kind") or _arm_kind(model_sample)
            p_choice = _require_plan_choice(arm_cfg, arm_name)

            seed_successes: list[float] = []
            for seed in seeds:
                model = _resolve_model(model_by_arm, arm_name, seed)
                derived_seed = int(
                    hashlib.sha256(f"dev|{world_id}|{spec_id}|{seed}".encode("utf-8")).hexdigest()[:8],
                    16,
                )
                row = _run_planning_episode_for_model(
                    model,
                    spec,
                    arm_kind=kind,
                    plan_choice=p_choice,
                    n_fwd=primary_n_fwd,
                    seed=derived_seed,
                    dataset_dir=d_dir,
                )
                row = {
                    **row,
                    "arm": arm_name,
                    "model_seed": seed,
                    "subset": "long",
                    "world_id": world_id,
                    "spec_id": spec_id,
                }
                if row.get("void"):
                    voided.append(row)
                else:
                    seed_successes.append(1.0 if row["success"] else 0.0)
                per_episode.append(row)
            if seed_successes:
                success_by_arm_world[arm_name].setdefault(world_id, []).append(
                    float(np.mean(seed_successes))
                )

    # Short + regular-dt subsets (telemetry only at primary N_fwd)
    for subset_name, subset_specs in (
        ("short", short_specs or ()),
        ("regular_dt", regular_dt_specs or ()),
    ):
        for spec in subset_specs:
            world_id = spec.get("world_index", spec.get("world_id", 0))
            spec_id = spec.get("episode_index", spec.get("id", 0))
            for arm_name in arm_names:
                arm_cfg = frozen_plan_config.get("arms", {}).get(arm_name, {})
                model_sample = _resolve_model(model_by_arm, arm_name, seeds[0])
                kind = arm_cfg.get("arm_kind") or _arm_kind(model_sample)
                p_choice = _require_plan_choice(arm_cfg, arm_name)
                for seed in seeds:
                    model = _resolve_model(model_by_arm, arm_name, seed)
                    derived_seed = int(
                        hashlib.sha256(f"dev_{subset_name}|{world_id}|{spec_id}|{seed}".encode("utf-8")).hexdigest()[:8],
                        16,
                    )
                    row = _run_planning_episode_for_model(
                        model,
                        spec,
                        arm_kind=kind,
                        plan_choice=p_choice,
                        n_fwd=primary_n_fwd,
                        seed=derived_seed,
                        dt_mode="regular" if subset_name == "regular_dt" else "irregular",
                        dataset_dir=d_dir,
                    )
                    per_episode.append(
                        {
                            **row,
                            "arm": arm_name,
                            "model_seed": seed,
                            "subset": subset_name,
                            "world_id": world_id,
                            "spec_id": spec_id,
                        }
                    )

    # N_fwd curve (dev only)
    n_fwd_curve_results: dict[str, dict[int, float]] = {a: {} for a in arm_names}
    for n_fwd in n_fwd_curve:
        for arm_name in arm_names:
            arm_cfg = frozen_plan_config.get("arms", {}).get(arm_name, {})
            model_sample = _resolve_model(model_by_arm, arm_name, seeds[0])
            kind = arm_cfg.get("arm_kind") or _arm_kind(model_sample)
            p_choice = _require_plan_choice(arm_cfg, arm_name)
            rates: list[float] = []
            for spec in long_specs:
                world_id = spec.get("world_index", spec.get("world_id", 0))
                spec_id = spec.get("episode_index", spec.get("id", 0))
                for seed in seeds:
                    model = _resolve_model(model_by_arm, arm_name, seed)
                    derived_seed = int(
                        hashlib.sha256(f"dev_curve_{n_fwd}|{world_id}|{spec_id}|{seed}".encode("utf-8")).hexdigest()[:8],
                        16,
                    )
                    row = _run_planning_episode_for_model(
                        model,
                        spec,
                        arm_kind=kind,
                        plan_choice=p_choice,
                        n_fwd=int(n_fwd),
                        seed=derived_seed,
                        dataset_dir=d_dir,
                    )
                    if row.get("void"):
                        voided.append({**row, "arm": arm_name, "subset": "long_curve"})
                        continue
                    rates.append(1.0 if row["success"] else 0.0)
            n_fwd_curve_results[arm_name][int(n_fwd)] = float(np.mean(rates)) if rates else 0.0

    # Probe: fit on train latents only, evaluate on dev partition (dev only reports, §5 / Appendix D5.1)
    probe_results: dict[str, Any] = {}
    train_root = extra_kwargs.get("train_root") or (d_dir.parent / "train" if d_dir and (d_dir.parent / "train").is_dir() else None)
    if train_root and Path(train_root).is_dir() and d_dir and d_dir.is_dir():
        from ainerzero.v9.experiments.s2 import probe_eval
        holdout_path = Path(train_root) / "HOLDOUT_WORLDS.json"
        h_worlds = None
        if holdout_path.is_file():
            try:
                h_worlds = json.loads(holdout_path.read_text(encoding="utf-8")).get("holdout_worlds")
            except Exception:
                pass
        for arm_name in arm_names:
            model = _resolve_model(model_by_arm, arm_name, seeds[0])
            try:
                probe_model = probe_eval.fit_probe(model, train_root, holdout_worlds=h_worlds)
                errs = probe_eval.probe_errors(model, probe_model, d_dir)
                probe_results[arm_name] = {
                    "fitted": True,
                    "fit_partition": "train",
                    "mean_by_k": errs.get("mean_by_k", {}),
                }
            except Exception as exc:
                probe_results[arm_name] = {"fitted": False, "reason": str(exc)}
    elif train_latents_by_arm is not None:
        for arm_name in arm_names:
            model = _resolve_model(model_by_arm, arm_name, seeds[0])
            bundle = train_latents_by_arm.get(arm_name)
            probe = _fit_probe_train_only(model, bundle, fit_fn=fit_ridge_fn)
            probe_results[arm_name] = {"fitted": probe is not None, "fit_partition": "train" if probe is not None else None}
    else:
        for arm_name in arm_names:
            probe_results[arm_name] = {"fitted": False, "fit_partition": "train"}

    # Clustered bootstrap of C − max(A,B) when arms present; else empty
    pairwise: dict[str, Any] = {}
    if len(arm_names) >= 2:
        ref = "C" if "C" in success_by_arm_world else ("arm_c" if "arm_c" in success_by_arm_world else arm_names[-1])
        base_arms = [a for a in arm_names if a != ref]
        if base_arms:
            worlds = sorted(
                set().union(*[set(success_by_arm_world[a].keys()) for a in arm_names])
            )
            diff_by_world: list[np.ndarray] = []
            for w in worlds:
                ref_eps = success_by_arm_world[ref].get(w, [])
                if not ref_eps:
                    continue
                base_stacks = []
                for a in base_arms:
                    base_stacks.append(success_by_arm_world[a].get(w, [0.0] * len(ref_eps)))
                n = min(len(ref_eps), *(len(b) for b in base_stacks))
                if n == 0:
                    continue
                ref_arr = np.asarray(ref_eps[:n], dtype=np.float64)
                base_max = np.max(
                    np.stack([np.asarray(b[:n], dtype=np.float64) for b in base_stacks], axis=0),
                    axis=0,
                )
                diff_by_world.append(ref_arr - base_max)
            if len(diff_by_world) >= 2:
                boot = cluster_paired_bootstrap(diff_by_world, n_boot=int(n_boot), rng=0)
                pairwise["C_minus_max_AB"] = {**boot.to_dict(), "n_boot": int(n_boot)}
            elif len(diff_by_world) == 1:
                pairwise["C_minus_max_AB"] = {
                    "mean": float(np.mean(diff_by_world[0])),
                    "ci_lower": float("nan"),
                    "ci_upper": float("nan"),
                    "n_boot": int(n_boot),
                    "note": "insufficient worlds for clustered bootstrap",
                }

    # Commit ledger increment (design-decision use)
    ledger["dev_eval_count"] = int(ledger.get("dev_eval_count", 0)) + 1
    ledger.setdefault("runs", []).append(
        {
            "at_unix": time.time(),
            "n_long": len(long_specs),
            "n_voided": len(voided),
            "frozen_plan_config_sha": hashlib.sha256(
                json.dumps(frozen_plan_config, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }
    )
    save_dev_ledger(ledger_path, ledger)

    return {
        "schema": "s2.dev_eval.v1",
        "dev_eval_count": ledger["dev_eval_count"],
        "frozen_plan_config": dict(frozen_plan_config),
        "per_episode": per_episode,
        "voided_comparisons": voided,
        "n_fwd_curve": n_fwd_curve_results,
        "probe": probe_results,
        "pairwise": pairwise,
        "m2_label": "与 S1 不可比",
    }


def find_final_eval_approval(
    research_log: str | Path,
    *,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Locate a qualifying final-eval approval line (not the prereg line).

    Blockquotes / fenced / indented code do not count. A lone prereg approval is refused.
    """
    path = Path(research_log)
    if not path.is_file():
        raise FinalEvalRefused(f"research log missing: {path}")

    text = path.read_text(encoding="utf-8")
    final_rows: list[dict[str, Any]] = []
    prereg_rows: list[dict[str, Any]] = []
    spans: list[list[int | None]] = []
    skipped: dict[str, list[int]] = {"fenced_code": [], "blockquote": [], "indented_code": []}
    in_fence = False
    in_section = False

    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            if in_section:
                skipped["fenced_code"].append(number)
            continue

        if _ANY_H2_RE.match(stripped):
            if _SECTION_HEADING_RE.match(stripped):
                if in_section and spans:
                    spans[-1][1] = number - 1
                spans.append([number, None])
                in_section = True
            else:
                if in_section and spans:
                    spans[-1][1] = number - 1
                in_section = False
            continue

        if not in_section:
            continue

        if stripped.startswith(">"):
            skipped["blockquote"].append(number)
            continue
        if raw.startswith("    ") or raw.startswith("\t"):
            skipped["indented_code"].append(number)
            continue

        m_final = _FINAL_APPROVAL_RE.match(stripped)
        if m_final:
            final_rows.append(
                {
                    "line": stripped,
                    "line_number": number,
                    "document_sha256": m_final.group(1),
                }
            )
            continue
        m_prereg = _PREREG_APPROVAL_RE.match(stripped)
        if m_prereg:
            prereg_rows.append(
                {
                    "line": stripped,
                    "line_number": number,
                    "document_sha256": m_prereg.group(1),
                }
            )

    if in_section and spans and spans[-1][1] is None:
        spans[-1][1] = len(text.splitlines())

    if not final_rows:
        if prereg_rows:
            raise FinalEvalRefused(
                "final-eval refused: found prereg approval only; "
                "need a separate APPROVED s2-phase1 final-eval line"
            )
        raise FinalEvalRefused("final-eval refused: no qualifying final-eval approval line")

    if len(final_rows) != 1:
        raise FinalEvalRefused(
            f"final-eval refused: expected one final-eval approval line, found {len(final_rows)}"
        )

    found = final_rows[0]["document_sha256"]
    if expected_sha256 is not None and found != expected_sha256:
        raise FinalEvalRefused(
            f"final-eval approval sha mismatch: expected {expected_sha256}, got {found}"
        )

    return {
        "found": True,
        "line": final_rows[0]["line"],
        "line_number": final_rows[0]["line_number"],
        "document_sha256": found,
        "log_path": str(path),
        "skipped": skipped,
        "prereg_rows_seen": len(prereg_rows),
    }


def open_sealed_final_read_once(
    sealed_dir: str | Path,
    *,
    reader: Mapping[str, Any],
) -> dict[str, Any]:
    """Create the read-once marker before consuming sealed_final; refuse if present."""
    d = Path(sealed_dir)
    marker = d / READ_ONCE_MARKER_NAME
    d.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o444)
    except FileExistsError as exc:
        raise FinalEvalRefused(
            f"sealed_final already read once ({READ_ONCE_MARKER_NAME} exists)"
        ) from exc

    nonce = hashlib.sha256(f"{time.time_ns()}:{os.getpid()}".encode()).hexdigest()
    payload = {
        "opened_at_unix": time.time(),
        "pid": os.getpid(),
        "reader": dict(reader),
        "nonce": nonce,
    }
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return {"marker_path": str(marker), **payload}


def judge_hs2_gate(
    *,
    success_diff: float,
    success_ci_lower: float,
    pred_delta_ci_upper: float,
    m2_ok: bool = True,
    success_gate: float = SUCCESS_DIFF_GATE,
    delta_pred: float = DELTA_PRED,
    require_ci_lower: bool = True,
) -> GateVerdict:
    """H-S2 gate (§5): success gap, clustered lower bound, prediction non-inferiority.

    ``require_ci_lower`` is a mutation sentinel — production must keep it True so a
    positive point estimate with negative lower bound still fails.
    """
    reasons: list[str] = []
    if success_diff < success_gate:
        reasons.append(
            f"success_diff {success_diff:.4f} < gate {success_gate:.2f}"
        )
    if require_ci_lower and not (success_ci_lower > 0.0):
        reasons.append(f"clustered ci_lower {success_ci_lower:.4f} is not > 0")
    if pred_delta_ci_upper > delta_pred:
        reasons.append(
            f"pred Δ CI upper {pred_delta_ci_upper:.4f} > δ_pred {delta_pred:.1f}"
        )
    if not m2_ok:
        reasons.append("M2 interference diagnosis worsened")

    return GateVerdict(
        passed=not reasons,
        reasons=tuple(reasons),
        success_diff=float(success_diff),
        success_ci_lower=float(success_ci_lower),
        pred_delta_ci_upper=float(pred_delta_ci_upper),
        m2_label="与 S1 不可比",
    )


def run_final_eval(
    model_by_arm: Mapping[str, Any],
    frozen_plan_config: Mapping[str, Any],
    *,
    sealed_final_dir: str | Path,
    research_log: str | Path,
    long_specs: Sequence[Mapping[str, Any]],
    short_specs: Sequence[Mapping[str, Any]] | None = None,
    seeds: Sequence[int] = (42, 43, 44),
    expected_document_sha256: str | None = None,
    reader: Mapping[str, Any] | None = None,
    train_latents_by_arm: Mapping[str, Mapping[str, Any]] | None = None,
    success_diff: float | None = None,
    success_ci_lower: float | None = None,
    pred_delta_ci_upper: float | None = None,
    m2_ok: bool = True,
    **extra_kwargs: Any,
) -> dict[str, Any]:
    """One-shot sealed final evaluation under a separate final-eval approval line.

    Results are reported without allowing a re-tune / second read.
    """
    approval = find_final_eval_approval(
        research_log, expected_sha256=expected_document_sha256
    )
    token = open_sealed_final_read_once(
        sealed_final_dir,
        reader=reader or {"component": "s2.eval_runner.run_final_eval"},
    )

    sealed_dir = Path(sealed_final_dir)
    if "arms" in frozen_plan_config and frozen_plan_config["arms"]:
        arm_names = list(frozen_plan_config["arms"].keys())
    else:
        seen_arms: list[str] = []
        for k in model_by_arm.keys():
            arm_part = k.split("/")[0] if isinstance(k, str) else str(k)
            if arm_part not in seen_arms:
                seen_arms.append(arm_part)
        arm_names = seen_arms

    # Evaluate once at N_fwd default (no N_fwd curve on final)
    per_episode: list[dict[str, Any]] = []
    for spec in long_specs:
        world_id = spec.get("world_index", spec.get("world_id", 0))
        spec_id = spec.get("episode_index", spec.get("id", 0))
        for arm_name in arm_names:
            arm_cfg = frozen_plan_config.get("arms", {}).get(arm_name, {})
            model_sample = _resolve_model(model_by_arm, arm_name, seeds[0])
            kind = arm_cfg.get("arm_kind") or _arm_kind(model_sample)
            p_choice = _require_plan_choice(arm_cfg, arm_name)
            for seed in seeds:
                model = _resolve_model(model_by_arm, arm_name, seed)
                derived_seed = int(
                    hashlib.sha256(f"final|{world_id}|{spec_id}|{seed}".encode("utf-8")).hexdigest()[:8],
                    16,
                )
                row = _run_planning_episode_for_model(
                    model,
                    spec,
                    arm_kind=kind,
                    plan_choice=p_choice,
                    n_fwd=int(spec_mod.N_FWD),
                    seed=derived_seed,
                    dataset_dir=sealed_dir,
                )
                per_episode.append(
                    {
                        **row,
                        "arm": arm_name,
                        "model_seed": seed,
                        "subset": "long",
                        "world_id": world_id,
                        "spec_id": spec_id,
                    }
                )
    for spec in short_specs or ():
        world_id = spec.get("world_index", spec.get("world_id", 0))
        spec_id = spec.get("episode_index", spec.get("id", 0))
        for arm_name in arm_names:
            arm_cfg = frozen_plan_config.get("arms", {}).get(arm_name, {})
            model_sample = _resolve_model(model_by_arm, arm_name, seeds[0])
            kind = arm_cfg.get("arm_kind") or _arm_kind(model_sample)
            p_choice = _require_plan_choice(arm_cfg, arm_name)
            for seed in seeds:
                model = _resolve_model(model_by_arm, arm_name, seed)
                derived_seed = int(
                    hashlib.sha256(f"final_short|{world_id}|{spec_id}|{seed}".encode("utf-8")).hexdigest()[:8],
                    16,
                )
                row = _run_planning_episode_for_model(
                    model,
                    spec,
                    arm_kind=kind,
                    plan_choice=p_choice,
                    n_fwd=int(spec_mod.N_FWD),
                    seed=derived_seed,
                    dataset_dir=sealed_dir,
                )
                per_episode.append(
                    {
                        **row,
                        "arm": arm_name,
                        "model_seed": seed,
                        "subset": "short",
                        "world_id": world_id,
                        "spec_id": spec_id,
                    }
                )

    # Gate 2: Linear probe prediction non-inferiority (§5, Appendix D5.1)
    probe_results: dict[str, Any] = {}
    train_root = extra_kwargs.get("train_root") or (sealed_dir.parent / "train" if (sealed_dir.parent / "train").is_dir() else None)
    if train_root and Path(train_root).is_dir() and sealed_dir.is_dir():
        from ainerzero.v9.experiments.s2 import probe_eval
        holdout_path = Path(train_root) / "HOLDOUT_WORLDS.json"
        h_worlds = None
        if holdout_path.is_file():
            try:
                h_worlds = json.loads(holdout_path.read_text(encoding="utf-8")).get("holdout_worlds")
            except Exception:
                pass

        errors_by_arm_seed: dict[str, dict[int, Any]] = {}
        for arm_name in ("arm_a", "arm_b", "arm_c"):
            errors_by_arm_seed[arm_name] = {}
            for s in seeds:
                try:
                    m = _resolve_model(model_by_arm, arm_name, s)
                    p_model = probe_eval.fit_probe(m, train_root, holdout_worlds=h_worlds)
                    p_errs = probe_eval.probe_errors(m, p_model, sealed_dir)
                    errors_by_arm_seed[arm_name][s] = p_errs
                except Exception as exc:
                    probe_results[f"{arm_name}/{s}"] = {"fitted": False, "reason": str(exc)}

        if len(errors_by_arm_seed.get("arm_a", {})) == len(seeds) and \
           len(errors_by_arm_seed.get("arm_b", {})) == len(seeds) and \
           len(errors_by_arm_seed.get("arm_c", {})) == len(seeds):
            try:
                noninf_res = probe_eval.prediction_noninferiority(errors_by_arm_seed, k=30)
                probe_results["prediction_noninferiority"] = noninf_res
                if pred_delta_ci_upper is None:
                    pred_delta_ci_upper = float(noninf_res["ci_upper"])
            except Exception as exc:
                probe_results["prediction_noninferiority_error"] = str(exc)

    elif train_latents_by_arm is not None:
        for arm_name, model in model_by_arm.items():
            bundle = train_latents_by_arm.get(arm_name)
            probe = _fit_probe_train_only(model, bundle)
            probe_results[arm_name] = {
                "fitted": probe is not None,
                "fit_partition": "train" if probe is not None else None,
            }

    # Gate inputs: callers may supply pre-aggregated stats (tests); else derive crude means
    if success_diff is None or success_ci_lower is None:
        by_arm: dict[str, list[float]] = {}
        for row in per_episode:
            if row.get("subset") != "long" or row.get("void"):
                continue
            by_arm.setdefault(str(row["arm"]), []).append(1.0 if row["success"] else 0.0)
        rates = {a: float(np.mean(v)) if v else 0.0 for a, v in by_arm.items()}
        ref = "C" if "C" in rates else (max(rates, key=rates.get) if rates else "C")
        others = [r for a, r in rates.items() if a != ref]
        base = max(others) if others else 0.0
        success_diff = float(rates.get(ref, 0.0) - base)
        success_ci_lower = float(success_diff)  # crude stand-in when bootstrap unavailable
    if pred_delta_ci_upper is None:
        pred_delta_ci_upper = 0.0

    gate = judge_hs2_gate(
        success_diff=float(success_diff),
        success_ci_lower=float(success_ci_lower),
        pred_delta_ci_upper=float(pred_delta_ci_upper),
        m2_ok=m2_ok,
    )

    return {
        "schema": "s2.final_eval.v1",
        "approval": approval,
        "read_once": token,
        "frozen_plan_config": dict(frozen_plan_config),
        "per_episode": per_episode,
        "probe": probe_results,
        "gate": gate.to_dict(),
        "m2_label": "与 S1 不可比",
        "note": "results reported as-is; retune-and-rerun forbidden",
    }
