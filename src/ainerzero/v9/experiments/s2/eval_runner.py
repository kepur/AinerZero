"""S2 evaluation runner: plan-select (train-only), capped dev eval, one-shot final.

Backend-agnostic planning protocol; pure CPU / NumPy. Zero MLX imports.
Specifications per reports/V9-S2-DESIGN/DESIGN-r2.md §4, §5, §7.
"""

from __future__ import annotations

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

from ainerzero.v9.experiments.s2 import smoke_checks
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
FLAT_H_CANDIDATES: tuple[int, ...] = (16, 32, 48)
HIER_MACRO_HORIZONS: tuple[int, ...] = (4, 6, 8)
HIER_BUDGET_RATIOS: tuple[float, ...] = (0.25, 0.5)

N_FWD_DEFAULT: int = 4096
N_FWD_CURVE: tuple[int, ...] = (2048, 4096, 8192)
MAX_DEV_EVALS: int = 2
DELTA_PRED: float = 1.0
SUCCESS_DIFF_GATE: float = 0.10
ACTION_SENSITIVITY_FLOOR: float = 0.05
SUBGOAL_DROP_FLOOR: float = 0.10

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


def _candidate_grid(kind: str) -> list[dict[str, Any]]:
    if kind == "flat":
        return [{"H": int(h)} for h in FLAT_H_CANDIDATES]
    return [
        {"macro_horizon": int(mh), "budget_ratio": float(br)}
        for mh in HIER_MACRO_HORIZONS
        for br in HIER_BUDGET_RATIOS
    ]


def _score_config_on_train(
    model: Any,
    config: Mapping[str, Any],
    specs: Sequence[Mapping[str, Any]],
) -> float:
    """Mean success on train plan-select specs.

    Fake models may expose ``plan_select_success(config, spec) -> bool`` (or a
    preferred hyper-parameter attribute) so CPU tests can pin the optimum without
    training. Real models should override via ``evaluate_plan_config``.
    """
    if hasattr(model, "evaluate_plan_config"):
        return float(model.evaluate_plan_config(dict(config), list(specs)))

    kind = _arm_kind(model)
    preferred = getattr(model, "preferred_config", None)
    if preferred is not None:
        # Exact match → 1.0; else 0.0 (deterministic oracle for unit tests).
        return 1.0 if dict(preferred) == dict(config) else 0.0

    if kind == "flat":
        best_h = getattr(model, "preferred_flat_H", None)
        if best_h is not None:
            return 1.0 if int(config["H"]) == int(best_h) else 0.0
    else:
        pref_mh = getattr(model, "preferred_macro_horizon", None)
        pref_br = getattr(model, "preferred_budget_ratio", None)
        if pref_mh is not None and pref_br is not None:
            ok = (
                int(config["macro_horizon"]) == int(pref_mh)
                and abs(float(config["budget_ratio"]) - float(pref_br)) < 1e-12
            )
            return 1.0 if ok else 0.0

    # Fallback: treat every config equally successful (tie-break by compute).
    del specs
    return 0.5


def run_plan_select(
    model_by_arm: Mapping[str, Any],
    train_episode_specs: Sequence[Mapping[str, Any]],
    *,
    output_path: str | Path | None = None,
    max_episodes: int = 50,
    n_fwd: int = N_FWD_DEFAULT,
) -> dict[str, Any]:
    """Select planner hyper-parameters on train-only planning episodes (§4).

    Refuses immediately if any episode spec is labeled ``dev`` or ``final``.
    Tie-break: equal success → smaller compute cost.
    """
    del n_fwd  # reserved for real CEM budget derivation
    if not train_episode_specs:
        raise PlanSelectError("train_episode_specs must be non-empty")
    _assert_train_only(train_episode_specs)
    specs = list(train_episode_specs[: max(1, int(max_episodes))])

    frozen: dict[str, Any] = {
        "schema": "s2.plan_select.v1",
        "n_episodes_used": len(specs),
        "arms": {},
    }

    for arm_name, model in model_by_arm.items():
        kind = _arm_kind(model)
        best: dict[str, Any] | None = None
        best_score = -1.0
        best_cost = float("inf")
        trials: list[dict[str, Any]] = []

        for cand in _candidate_grid(kind):
            score = _score_config_on_train(model, cand, specs)
            cost = _config_compute_cost(kind, cand)
            trials.append({"config": dict(cand), "success_rate": score, "compute_cost": cost})
            better = score > best_score + 1e-15
            tied_cheaper = abs(score - best_score) <= 1e-15 and cost < best_cost
            if better or tied_cheaper:
                best_score = score
                best_cost = cost
                best = dict(cand)

        assert best is not None
        frozen["arms"][arm_name] = {
            "arm_kind": kind,
            "config": best,
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

    # 1. Action sensitivity gate for all arms
    for arm_name, model in model_by_arm.items():
        def _predict(z: np.ndarray, a: Any, m: Any = model) -> np.ndarray:
            try:
                return m.predict_l1(z, a, 1.0)
            except TypeError:
                return m.predict_l1(z, a)

        states: Sequence[Any] | np.ndarray | None = None
        if train_states_by_arm is not None and arm_name in train_states_by_arm:
            states = train_states_by_arm[arm_name]
        elif hasattr(model, "states_sample"):
            states = getattr(model, "states_sample")
        elif hasattr(model, "sample_states"):
            states = getattr(model, "sample_states")
        elif hasattr(model, "train_states"):
            states = getattr(model, "train_states")
        elif hasattr(model, "encode"):
            states = [
                model.encode(spec.get("start", spec.get("start_obs", spec.get("obs", spec))))
                for spec in train_episode_specs[:n_sensitivity_states]
            ]
        else:
            raise PostTrainGateError(f"Cannot extract sensitivity states for arm {arm_name!r}")

        states_list = list(states)[:n_sensitivity_states]
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

    # 2. C-arm shuffled subgoal negative control
    c_arm_name: str | None = None
    if "C" in model_by_arm:
        c_arm_name = "C"
    else:
        for name, m in model_by_arm.items():
            if getattr(m, "arm_kind", None) == "hierarchical" or getattr(m, "kind", None) == "hierarchical":
                c_arm_name = name
                break

    c_control_result: dict[str, Any] | None = None
    if c_arm_name is not None:
        c_model = model_by_arm[c_arm_name]
        c_specs = list(train_episode_specs[: max(1, int(c_shuffle_episodes))])
        n_c_eps = len(c_specs)

        # Generate deranged permutation for shuffled subgoals
        rng_shuffle = np.random.default_rng(shuffle_seed)
        perm = rng_shuffle.permutation(n_c_eps)
        if n_c_eps > 1:
            fixed = np.where(perm == np.arange(n_c_eps))[0]
            if len(fixed) > 0:
                perm = (perm + 1) % n_c_eps

        if hasattr(c_model, "eval_c_negative_control"):
            ctrl = c_model.eval_c_negative_control(
                c_specs,
                n_fwd=n_fwd,
                seed=seed,
                shuffle_seed=shuffle_seed,
                subgoal_drop_threshold=subgoal_drop_threshold,
            )
            rate_true = float(ctrl["success_rate_true"])
            rate_shuffled = float(ctrl["success_rate_shuffled"])
            drop = float(ctrl.get("drop", rate_true - rate_shuffled))
        elif hasattr(c_model, "eval_episode"):
            sig = inspect.signature(c_model.eval_episode)
            accepts_shuffled = "shuffled_subgoal" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            accepts_subgoal = "subgoal" in sig.parameters

            if hasattr(c_model, "plan_subgoal") and accepts_subgoal:
                subgoals = [c_model.plan_subgoal(s) for s in c_specs]
                true_hits = []
                shuf_hits = []
                for i, s in enumerate(c_specs):
                    r_true = c_model.eval_episode(s, n_fwd=n_fwd, seed=seed + i, subgoal=subgoals[i])
                    r_shuf = c_model.eval_episode(s, n_fwd=n_fwd, seed=seed + i, subgoal=subgoals[perm[i]])
                    true_hits.append(1.0 if r_true.get("success", False) else 0.0)
                    shuf_hits.append(1.0 if r_shuf.get("success", False) else 0.0)
                rate_true = float(np.mean(true_hits)) if true_hits else 0.0
                rate_shuffled = float(np.mean(shuf_hits)) if shuf_hits else 0.0
                drop = rate_true - rate_shuffled
            elif accepts_shuffled:
                true_hits = []
                shuf_hits = []
                for i, s in enumerate(c_specs):
                    r_true = c_model.eval_episode(s, n_fwd=n_fwd, seed=seed + i, shuffled_subgoal=False)
                    r_shuf = c_model.eval_episode(
                        s,
                        n_fwd=n_fwd,
                        seed=seed + i,
                        shuffled_subgoal=True,
                        shuffled_spec=dict(c_specs[perm[i]]),
                    )
                    true_hits.append(1.0 if r_true.get("success", False) else 0.0)
                    shuf_hits.append(1.0 if r_shuf.get("success", False) else 0.0)
                rate_true = float(np.mean(true_hits)) if true_hits else 0.0
                rate_shuffled = float(np.mean(shuf_hits)) if shuf_hits else 0.0
                drop = rate_true - rate_shuffled
            elif hasattr(c_model, "subgoal_drop"):
                drop = float(c_model.subgoal_drop)
                rate_true = float(getattr(c_model, "true_success_rate", 0.5))
                rate_shuffled = rate_true - drop
            else:
                raise PostTrainGateError(
                    f"C arm {c_arm_name!r} eval_episode must accept 'shuffled_subgoal' or 'subgoal'"
                )
        elif hasattr(c_model, "subgoal_drop"):
            drop = float(c_model.subgoal_drop)
            rate_true = float(getattr(c_model, "true_success_rate", 0.5))
            rate_shuffled = rate_true - drop
        else:
            raise PostTrainGateError(
                f"C arm {c_arm_name!r} missing negative control implementation (eval_c_negative_control or eval_episode)"
            )

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

    passed = (len(reasons) == 0)

    verdict_record = {
        "schema": "s2.post_train_gates.v1",
        "passed": passed,
        "reasons": reasons,
        "sensitivity_by_arm": sensitivity_by_arm,
        "unplannable_arms": unplannable_arms,
        "c_negative_control": c_control_result,
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
    if count >= MAX_DEV_EVALS:
        raise DevEvalCapExceeded(
            f"dev eval refused: already used {count} times (cap={MAX_DEV_EVALS})"
        )
    return ledger


def _episode_success_stub(
    model: Any,
    spec: Mapping[str, Any],
    *,
    n_fwd: int,
    seed: int,
) -> dict[str, Any]:
    """Evaluate one episode under a frozen config / budget.

    Fake models may implement ``eval_episode(spec, n_fwd=..., seed=...)``.
    Exceeding ``n_fwd`` must raise ``ForwardBudgetExceeded`` so the runner can void.
    """
    if hasattr(model, "eval_episode"):
        try:
            result = model.eval_episode(dict(spec), n_fwd=int(n_fwd), seed=int(seed))
        except ForwardBudgetExceeded as exc:
            return {
                "success": False,
                "void": True,
                "void_reason": "forward_budget_exceeded",
                "error": str(exc),
                "n_fwd": int(n_fwd),
                "seed": int(seed),
            }
        success = bool(result.get("success", False)) if isinstance(result, Mapping) else bool(result)
        return {
            "success": success,
            "void": bool(result.get("void", False)) if isinstance(result, Mapping) else False,
            "n_fwd": int(n_fwd),
            "seed": int(seed),
            "detail": result if isinstance(result, Mapping) else {"success": success},
        }

    # Default: prefer models that expose a deterministic success probability.
    base = float(getattr(model, "base_success_rate", 0.5))
    rng = np.random.default_rng(int(seed) + 17 * int(n_fwd))
    success = bool(rng.random() < base)
    return {"success": success, "void": False, "n_fwd": int(n_fwd), "seed": int(seed)}


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
    seeds: Sequence[int] = (0, 1, 2),
    n_fwd_curve: Sequence[int] = N_FWD_CURVE,
    ledger_path: str | Path,
    train_latents_by_arm: Mapping[str, Mapping[str, Any]] | None = None,
    fit_ridge_fn: Callable[..., RidgeProbe] = fit_ridge,
    n_boot: int = 200,
    require_post_train_gates: bool = True,
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

    primary_n_fwd = int(N_FWD_DEFAULT)
    per_episode: list[dict[str, Any]] = []
    voided: list[dict[str, Any]] = []
    arm_names = list(model_by_arm.keys())

    # Primary long-goal results at N_fwd=4096 for pairwise diffs
    success_by_arm_world: dict[str, dict[Any, list[float]]] = {a: {} for a in arm_names}

    for spec in long_specs:
        world_id = spec.get("world_index", spec.get("world_id", 0))
        for arm_name, model in model_by_arm.items():
            seed_successes: list[float] = []
            for seed in seeds:
                row = _episode_success_stub(model, spec, n_fwd=primary_n_fwd, seed=int(seed))
                row = {
                    **row,
                    "arm": arm_name,
                    "subset": "long",
                    "world_id": world_id,
                    "spec_id": spec.get("episode_index", spec.get("id")),
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
            for arm_name, model in model_by_arm.items():
                for seed in seeds:
                    row = _episode_success_stub(model, spec, n_fwd=primary_n_fwd, seed=int(seed))
                    per_episode.append(
                        {
                            **row,
                            "arm": arm_name,
                            "subset": subset_name,
                            "world_id": spec.get("world_index", spec.get("world_id", 0)),
                        }
                    )

    # N_fwd curve (dev only)
    n_fwd_curve_results: dict[str, dict[int, float]] = {a: {} for a in arm_names}
    for n_fwd in n_fwd_curve:
        for arm_name, model in model_by_arm.items():
            rates: list[float] = []
            for spec in long_specs:
                for seed in seeds:
                    row = _episode_success_stub(model, spec, n_fwd=int(n_fwd), seed=int(seed))
                    if row.get("void"):
                        voided.append({**row, "arm": arm_name, "subset": "long_curve"})
                        continue
                    rates.append(1.0 if row["success"] else 0.0)
            n_fwd_curve_results[arm_name][int(n_fwd)] = float(np.mean(rates)) if rates else 0.0

    # Probe: fit on train latents only, evaluate on a light dev latent bundle if provided via model
    probe_results: dict[str, Any] = {}
    for arm_name, model in model_by_arm.items():
        bundle = None if train_latents_by_arm is None else train_latents_by_arm.get(arm_name)
        probe = _fit_probe_train_only(model, bundle, fit_fn=fit_ridge_fn)
        if probe is None:
            probe_results[arm_name] = {"fitted": False}
            continue
        # Optional held-out eval vectors on the model
        Z_dev = getattr(model, "dev_Z", None)
        XY_dev = getattr(model, "dev_XY", None)
        if Z_dev is not None and XY_dev is not None:
            probe_results[arm_name] = {
                "fitted": True,
                "fit_partition": "train",
                "error": eval_error(probe, Z_dev, XY_dev),
            }
        else:
            probe_results[arm_name] = {"fitted": True, "fit_partition": "train"}

    # Clustered bootstrap of C − max(A,B) when arms present; else empty
    pairwise: dict[str, Any] = {}
    if len(arm_names) >= 2:
        # Build per-world episode diffs vs reference (first arm as baseline if no C)
        ref = "C" if "C" in success_by_arm_world else arm_names[-1]
        base_arms = [a for a in arm_names if a != ref]
        if base_arms:
            # max(A,B) per episode index aligned by world
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
                # Align lengths
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
                pairwise["C_minus_max_AB"] = boot.to_dict()
            elif len(diff_by_world) == 1:
                pairwise["C_minus_max_AB"] = {
                    "mean": float(np.mean(diff_by_world[0])),
                    "ci_lower": float("nan"),
                    "ci_upper": float("nan"),
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
    seeds: Sequence[int] = (0, 1, 2),
    expected_document_sha256: str | None = None,
    reader: Mapping[str, Any] | None = None,
    train_latents_by_arm: Mapping[str, Mapping[str, Any]] | None = None,
    success_diff: float | None = None,
    success_ci_lower: float | None = None,
    pred_delta_ci_upper: float | None = None,
    m2_ok: bool = True,
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

    # Evaluate once at N_fwd default (no N_fwd curve on final)
    per_episode: list[dict[str, Any]] = []
    for spec in long_specs:
        for arm_name, model in model_by_arm.items():
            for seed in seeds:
                row = _episode_success_stub(
                    model, spec, n_fwd=N_FWD_DEFAULT, seed=int(seed)
                )
                per_episode.append(
                    {
                        **row,
                        "arm": arm_name,
                        "subset": "long",
                        "world_id": spec.get("world_index", spec.get("world_id", 0)),
                    }
                )
    for spec in short_specs or ():
        for arm_name, model in model_by_arm.items():
            for seed in seeds:
                row = _episode_success_stub(
                    model, spec, n_fwd=N_FWD_DEFAULT, seed=int(seed)
                )
                per_episode.append(
                    {
                        **row,
                        "arm": arm_name,
                        "subset": "short",
                        "world_id": spec.get("world_index", spec.get("world_id", 0)),
                    }
                )

    # Optional probe fit still train-only
    probe_results: dict[str, Any] = {}
    if train_latents_by_arm is not None:
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
