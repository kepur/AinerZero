"""Mechanism Sufficiency Gate (MSG) with 8 routes, greedy independent-context counting, and M8 audit.

Implements ADR-0014 r3 §2 D1 (M4/M5/M8/M9/N1) and §3 C7-ii (MSGRouteRecord).
Strictly reads only learner-visible ObservationContext, ParamBelief, and frozen CMFLRegistration.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np

from .identification import (
    compute_innovations_and_nis,
    dimensionless_fisher_information,
    identify_parameters_bayesian,
    posterior_model_entropy,
)
from .registration import (
    CMFLRegistration,
    MSGRouteRecord,
    ParamBelief,
    ParamBeliefStore,
    ROUTE_PRIORITY,
    RouteCode,
    chi2_ppf,
)
from .toy_worlds import (
    FORBIDDEN_OBSERVATION_FIELDS,
    GroundTruthMeta,
    ObservationContext,
    integrate_half_step_twice,
    integrate_one_step,
)


def are_contexts_independent(
    c1: ObservationContext,
    c2: ObservationContext,
    tau_decorr: int,
) -> bool:
    """Decidable independent-context predicate (ADR-0014 §2 D1 M5):
    Independent iff (i) world_instance_id differs, OR
    (ii) in the same world, |t1 - t2| >= tau_decorr and object_keys are disjoint.
    """
    if c1.world_instance_id != c2.world_instance_id:
        return True
    time_gap = abs(int(c1.t_start) - int(c2.t_start))
    disjoint_objects = set(c1.object_keys).isdisjoint(c2.object_keys)
    return bool(time_gap >= tau_decorr and disjoint_objects)


def greedy_independent_context_set(
    contexts: Sequence[ObservationContext],
    tau_decorr: int,
) -> list[ObservationContext]:
    """Deterministic greedy independent-set algorithm (ADR-0014 §2 D1 M5 + N1).

    Sorts candidate contexts in ascending lexicographical order by
    (world_instance_id, t_start, context_id), scans from front to back,
    and includes a context iff it is independent of all already-selected contexts.
    """
    ordered = sorted(
        contexts,
        key=lambda c: (str(c.world_instance_id), int(c.t_start), str(c.context_id)),
    )
    selected: list[ObservationContext] = []
    for ctx in ordered:
        if all(are_contexts_independent(ctx, prev, tau_decorr) for prev in selected):
            selected.append(ctx)
    return selected


def nis_acceptance_bounds(alpha_s: float, dof: int) -> tuple[float, float]:
    """Two-sided chi-square NIS acceptance interval [q_low, q_high] used by MSG rows 4a/4b."""
    return chi2_ppf(0.5 * alpha_s, dof), chi2_ppf(1.0 - 0.5 * alpha_s, dof)


def is_covariance_inconsistent(
    context: ObservationContext,
    prior_belief: ParamBelief,
    registration: CMFLRegistration,
) -> bool:
    """MSG row 4a criterion (lower-tail NIS), independent of the D_permit / D_valid rows."""
    _, nis, dof = compute_innovations_and_nis(context, prior_belief.mean)
    q_low, _ = nis_acceptance_bounds(registration.alpha_s, dof)
    return bool(nis < q_low)


def strip_covariance_inconsistent_windows(
    contexts: Sequence[ObservationContext],
    prior_belief: ParamBelief,
    registration: CMFLRegistration,
) -> tuple[list[ObservationContext], int]:
    """N4: deterministically drop 4a windows to form C_clean; returns (C_clean, n_removed)."""
    clean = [c for c in contexts if not is_covariance_inconsistent(c, prior_belief, registration)]
    return clean, len(contexts) - len(clean)


@dataclass(frozen=True)
class DomainEnvelope:
    """Covariate bounding envelope for D_valid(m) (ADR-0014 §2 D1 row 2 & §2 D3-4)."""

    state_min: np.ndarray  # (4,)
    state_max: np.ndarray  # (4,)
    action_min: np.ndarray  # (2,)
    action_max: np.ndarray  # (2,)

    @classmethod
    def from_contexts(cls, contexts: Sequence[ObservationContext]) -> "DomainEnvelope":
        """Axis-aligned covariate hull of the given windows (states, next_states and actions)."""
        if not contexts:
            raise ValueError("cannot build a D_valid envelope from zero contexts")
        states = np.concatenate([np.concatenate([c.states, c.next_states], axis=0) for c in contexts], axis=0)
        actions = np.concatenate([c.actions for c in contexts], axis=0)
        return cls(
            state_min=np.min(states, axis=0),
            state_max=np.max(states, axis=0),
            action_min=np.min(actions, axis=0),
            action_max=np.max(actions, axis=0),
        )

    @classmethod
    def symmetric_box(cls, *, position_limit: float, speed_limit: float, action_limit: float) -> "DomainEnvelope":
        """Frozen box |p| <= position_limit, |v| <= speed_limit, |u| <= action_limit."""
        lim = np.array([position_limit, position_limit, speed_limit, speed_limit], dtype=float)
        act = np.array([action_limit, action_limit], dtype=float)
        return cls(state_min=-lim, state_max=lim, action_min=-act, action_max=act)

    def contains(self, context: ObservationContext) -> bool:
        # r2: decided from learner-visible covariates only; no caller-supplied domain label.
        both = np.concatenate([context.states, context.next_states], axis=0)
        s_ok = bool(
            np.all(both >= self.state_min - 1e-9)
            and np.all(both <= self.state_max + 1e-9)
        )
        a_ok = bool(
            np.all(context.actions >= self.action_min - 1e-9)
            and np.all(context.actions <= self.action_max + 1e-9)
        )
        return s_ok and a_ok


# Frozen D_valid box of the SLOW toy mechanism used by the CMFL benchmark (r2).  It is declared with
# the generator spec, not fitted to benchmark windows: |p| <= 8, |v| <= 12, |u| <= 12 (the D_permit
# action limit).  D_valid is a strict subset of D_permit (|p| <= 15, |v| <= 20, |u| <= 12).
TOY_SLOW_D_VALID_LIMITS: dict[str, float] = {"position_limit": 8.0, "speed_limit": 12.0, "action_limit": 12.0}


def toy_slow_d_valid_envelope() -> DomainEnvelope:
    return DomainEnvelope.symmetric_box(**TOY_SLOW_D_VALID_LIMITS)


class MechanismSufficiencyGate:
    """8-route Mechanism Sufficiency Gate (ADR-0014 §2 D1).

    Orthogonal to UpdateScheduler: MSG decides how to explain prediction residuals.
    """

    def __init__(
        self,
        registration: CMFLRegistration,
        *,
        domain_envelope: DomainEnvelope | None = None,
        belief_store: ParamBeliefStore | None = None,
        disable_d_permit: bool = False,
    ) -> None:
        self.registration = registration
        self.domain_envelope = domain_envelope
        self.belief_store = belief_store if belief_store is not None else ParamBeliefStore()
        self.disable_d_permit = bool(disable_d_permit)
        self._reg_sha = registration.registration_sha()
        self._structural_failure_pool: list[ObservationContext] = []
        self._route_history: list[MSGRouteRecord] = []

    @property
    def route_history(self) -> tuple[MSGRouteRecord, ...]:
        return tuple(self._route_history)

    @property
    def structural_independent_contexts(self) -> list[ObservationContext]:
        return greedy_independent_context_set(
            self._structural_failure_pool,
            self.registration.tau_decorr,
        )

    @property
    def mid_discovery_triggered(self) -> bool:
        return len(self.structural_independent_contexts) >= self.registration.K

    def _assert_information_boundary(self, context: ObservationContext) -> None:
        """Verify §8.6 learning-side information boundary: no ground-truth attributes leaked."""
        leaked = set(dir(context)) & FORBIDDEN_OBSERVATION_FIELDS
        if leaked:
            raise ValueError(f"§8.6 information boundary violation: forbidden fields in context: {sorted(leaked)}")

    def _check_d_permit(self, context: ObservationContext) -> str | None:
        if self.disable_d_permit:
            return None
        dp = self.registration.d_permit
        allowed = set(dp.allowed_variables)
        disallowed = [v for v in context.requested_variables if v not in allowed]
        if disallowed:
            return f"requested variable(s) {disallowed} outside D_permit whitelist"
        max_pos = float(np.max(np.abs(context.states[:, :2])))
        if max_pos > dp.position_limit:
            return f"position max |p|={max_pos:.3f} exceeds D_permit limit {dp.position_limit:.3f}"
        max_vel = float(np.max(np.abs(context.states[:, 2:4])))
        if max_vel > dp.speed_limit:
            return f"speed max |v|={max_vel:.3f} exceeds D_permit limit {dp.speed_limit:.3f}"
        max_act = float(np.max(np.abs(context.actions)))
        if max_act > dp.action_limit:
            return f"action max |u|={max_act:.3f} exceeds D_permit limit {dp.action_limit:.3f}"
        return None

    def _check_in_domain(self, context: ObservationContext) -> str | None:
        if self.domain_envelope is None:
            # Fail closed: without a frozen D_valid envelope no window can be certified in-domain.
            return "no frozen D_valid envelope declared for the SLOW mechanism; fail-closed"
        if not self.domain_envelope.contains(context):
            return "covariates (state/action) fall outside the frozen D_valid bounding envelope"
        return None

    def route(
        self,
        context: ObservationContext,
        prior_belief: ParamBelief,
        *,
        scope_id: str = "default",
    ) -> MSGRouteRecord:
        """Evaluate context through the 8-route decision waterfall (first match stops)."""
        self._assert_information_boundary(context)
        residuals, nis_full, dof_full = compute_innovations_and_nis(context, prior_belief.mean)

        # 1. ABSTAIN (D_permit boundary check)
        abstain_reason = self._check_d_permit(context)
        if abstain_reason is not None:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.ABSTAIN,
                reason=abstain_reason,
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # 2. OUT_OF_DOMAIN (D_valid envelope check)
        ood_reason = self._check_in_domain(context)
        if ood_reason is not None:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.OUT_OF_DOMAIN,
                reason=ood_reason,
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # 3. NUMERICAL (step-halving discrepancy check: ||F(dt) - F(dt/2 o dt/2)|| >= kappa ||r||)
        f_dt = integrate_one_step(
            context.states,
            context.actions,
            context.dt,
            prior_belief.mean,
            integrator=context.integrator,
        )
        f_half = integrate_half_step_twice(
            context.states,
            context.actions,
            context.dt,
            prior_belief.mean,
            integrator=context.integrator,
        )
        eps_num = float(np.linalg.norm(f_dt - f_half))
        norm_r = max(float(np.linalg.norm(residuals)), 1e-12)
        if eps_num >= self.registration.kappa * norm_r:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.NUMERICAL,
                reason=(
                    f"step-halving error eps_num={eps_num:.5f} >= kappa*||r||="
                    f"{self.registration.kappa * norm_r:.5f} (integrator={context.integrator}, dt={context.dt})"
                ),
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # 4a & 4b. Chi-square two-sided NIS interval check
        alpha_s = self.registration.alpha_s
        q_low, q_high = nis_acceptance_bounds(alpha_s, dof_full)
        if nis_full < q_low:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.COVARIANCE_INCONSISTENT,
                reason=(
                    f"lower-tail NIS={nis_full:.2f} < chi2({dof_full}, {0.5*alpha_s:.4f})={q_low:.2f}; "
                    "innovation covariance S_k systematically inflated; do not learn or enter D_valid"
                ),
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        if nis_full <= q_high:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.SUFFICIENT,
                reason=f"NIS={nis_full:.2f} within [{q_low:.2f}, {q_high:.2f}] (dof={dof_full}); cache & solve",
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # Upper-tail residual discrepancy detected (nis_full > q_high).
        # Check parameter/model identifiability before declaring PARAMETRIC vs UNIDENTIFIABLE vs STRUCTURAL.
        _, lam_min = dimensionless_fisher_information(
            context, prior_belief.mean, prior_belief.dimensionless_scale
        )
        h_model = posterior_model_entropy(context.competing_model_probs)
        if lam_min < self.registration.tau_id or h_model > self.registration.tau_H:
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.UNIDENTIFIABLE,
                reason=(
                    f"identifiability check failed: lambda_min(I_phi)={lam_min:.3f} "
                    f"(tau_id={self.registration.tau_id:.3f}), H(p(m|D))={h_model:.3f} "
                    f"(tau_H={self.registration.tau_H:.3f}); screen competing mechanisms & select EIG probe"
                ),
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # 5. PARAMETRIC: fit p(phi|D) on first half of window, test on holdout second half (ADR-0014 §2 D1 row 5)
        w = context.states.shape[0]
        split = w // 2
        fit_idx = np.arange(0, split)
        hold_idx = np.arange(split, w)
        updated_half = identify_parameters_bayesian(context, prior_belief, fit_indices=fit_idx)
        _, nis_hold, dof_hold = compute_innovations_and_nis(
            context, updated_half.mean, indices=hold_idx, param_cov=updated_half.cov
        )
        q_hold_low = chi2_ppf(0.5 * alpha_s, dof_hold)
        q_hold_high = chi2_ppf(1.0 - 0.5 * alpha_s, dof_hold)

        if nis_hold < q_hold_low:
            # Row 5 parenthetical: if holdout falls into 4a lower tail, route to COVARIANCE_INCONSISTENT
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.COVARIANCE_INCONSISTENT,
                reason=(
                    f"post-parametric holdout NIS={nis_hold:.2f} < lower bound {q_hold_low:.2f} "
                    f"(dof={dof_hold}); turn to COVARIANCE_INCONSISTENT"
                ),
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        if nis_hold <= q_hold_high:
            full_posterior = identify_parameters_bayesian(context, prior_belief)
            self.belief_store.put(scope_id, full_posterior)
            rec = MSGRouteRecord(
                context_id=context.context_id,
                t_ticks=context.t_start,
                route_code=RouteCode.PARAMETRIC,
                reason=(
                    f"online parameter update passed holdout NIS={nis_hold:.2f} in "
                    f"[{q_hold_low:.2f}, {q_hold_high:.2f}] (dof={dof_hold}); updated ParamBeliefStore[{scope_id!r}]"
                ),
                nis_stat=nis_full,
                dof=dof_full,
                registration_sha=self._reg_sha,
            )
            self._route_history.append(rec)
            return rec

        # 7. STRUCTURAL: holdout NIS still exceeds upper tail after parameter identification
        self._structural_failure_pool.append(context)
        indep_set = self.structural_independent_contexts
        k_count = len(indep_set)
        triggered = k_count >= self.registration.K
        rec = MSGRouteRecord(
            context_id=context.context_id,
            t_ticks=context.t_start,
            route_code=RouteCode.STRUCTURAL,
            reason=(
                f"post-parametric holdout NIS={nis_hold:.2f} > {q_hold_high:.2f}; "
                f"greedy independent failures |I_indep|={k_count}/{self.registration.K} "
                f"(MID discovery triggered={triggered})"
            ),
            nis_stat=nis_full,
            dof=dof_full,
            registration_sha=self._reg_sha,
        )
        self._route_history.append(rec)
        return rec

    def save_routes_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "registration_id": self.registration.registration_id,
            "registration_sha": self._reg_sha,
            "disable_d_permit": self.disable_d_permit,
            "total_routed": len(self._route_history),
            "mid_discovery_triggered": self.mid_discovery_triggered,
            "independent_structural_count": len(self.structural_independent_contexts),
            "routes": [r.to_dict() for r in self._route_history],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Evaluation-Side Confusion Matrix & §8.6 Counterfactual Invariance Check
# ---------------------------------------------------------------------------

def evaluate_msg_confusion_matrix(
    records: Sequence[MSGRouteRecord],
    metas: Sequence[GroundTruthMeta],
) -> dict[str, Any]:
    """Compute 8x8 MSG confusion matrix (evaluation-only; never fed back into model)."""
    if len(records) != len(metas):
        raise ValueError("records and metas length mismatch")
    labels = [rc.value for rc in ROUTE_PRIORITY]
    idx_map = {name: i for i, name in enumerate(labels)}
    mat = np.zeros((len(labels), len(labels)), dtype=int)
    per_class_correct: dict[str, int] = {name: 0 for name in labels}
    per_class_total: dict[str, int] = {name: 0 for name in labels}

    meta_by_id = {m.context_id: m for m in metas}
    for rec in records:
        m = meta_by_id[rec.context_id]
        t_name = m.true_route.value
        p_name = rec.route_code.value
        mat[idx_map[t_name], idx_map[p_name]] += 1
        per_class_total[t_name] += 1
        if t_name == p_name:
            per_class_correct[t_name] += 1

    total = len(records)
    correct = int(np.trace(mat))
    return {
        "labels": labels,
        "matrix": mat.tolist(),
        "total": total,
        "correct": correct,
        "accuracy": float(correct / total) if total > 0 else 0.0,
        "per_class_recall": {
            name: (float(per_class_correct[name] / per_class_total[name]) if per_class_total[name] > 0 else 0.0)
            for name in labels
        },
        "predicted_counts": {
            labels[j]: int(np.sum(mat[:, j])) for j in range(len(labels))
        },
    }


def verify_same_observation_different_future(
    registration: CMFLRegistration,
    context: ObservationContext,
    prior_belief: ParamBelief,
    *,
    domain_envelope: DomainEnvelope | None = None,
) -> dict[str, Any]:
    """§8.6 counterfactual test (ADR-0014 §2 D1):
    Two worlds with identical observations up to window W (differing only in post-W future or
    sealed world instance truth) must produce identical route_code, reason, and nis_stat.
    """
    gate_a = MechanismSufficiencyGate(registration, domain_envelope=domain_envelope)
    gate_b = MechanismSufficiencyGate(registration, domain_envelope=domain_envelope)
    ctx_a = ObservationContext(
        context_id=context.context_id,
        world_instance_id="world_clone_alpha",
        t_start=context.t_start,
        object_keys=context.object_keys,
        dt=context.dt,
        integrator=context.integrator,
        states=context.states.copy(),
        next_states=context.next_states.copy(),
        actions=context.actions.copy(),
        innovation_cov=context.innovation_cov.copy(),
        requested_variables=context.requested_variables,
        competing_model_probs=context.competing_model_probs,
        env_family=context.env_family,
    )
    ctx_b = ObservationContext(
        context_id=context.context_id,
        world_instance_id="world_clone_beta",
        t_start=context.t_start,
        object_keys=context.object_keys,
        dt=context.dt,
        integrator=context.integrator,
        states=context.states.copy(),
        next_states=context.next_states.copy(),
        actions=context.actions.copy(),
        innovation_cov=context.innovation_cov.copy(),
        requested_variables=context.requested_variables,
        competing_model_probs=context.competing_model_probs,
        env_family=context.env_family,
    )
    rec_a = gate_a.route(ctx_a, prior_belief)
    rec_b = gate_b.route(ctx_b, prior_belief)
    identical = (
        rec_a.route_code == rec_b.route_code
        and rec_a.reason == rec_b.reason
        and abs(rec_a.nis_stat - rec_b.nis_stat) < 1e-15
    )
    return {
        "identical": identical,
        "route_a": rec_a.route_code.value,
        "route_b": rec_b.route_code.value,
        "reason_a": rec_a.reason,
        "reason_b": rec_b.reason,
    }
