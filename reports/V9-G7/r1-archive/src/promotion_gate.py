"""One-Sided Promotion Gate (MID -> SLOW) with unified error budget, world-block bootstrap,
C_clean conformal envelope, zero-regression replay, and all-environment e-LOND control.

Implements ADR-0014 r3 §2 D3 (M1/M2/M3/M4/N2/N3/N4/S3) and §3 C1/C2.
Pure NumPy and Python standard library only.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .discovery import BasisTermSpec, DiscoveredCandidate, default_basis_library
from .identification import compute_innovations_and_nis
from .registration import CMFLRegistration, ParamBelief, RouteCode
from .sufficiency_gate import DomainEnvelope, MechanismSufficiencyGate
from .toy_worlds import ObservationContext, integrate_one_step


# ---------------------------------------------------------------------------
# Producer Independence Guard (ADR-0014 §3 C2 / M7 Option b)
# ---------------------------------------------------------------------------

FORBIDDEN_SELF_PRODUCERS = frozenset({"student", "self", "teacher", "llm", "assistant", "human_unreviewed"})


def require_independent_slow_producer(
    producer: str,
    *,
    trusted_context: Mapping[str, Any] | None,
) -> str:
    """SLOW promotion producer guard (ADR-0014 §3 C2 / M7):
    Rejects 'student'/'self' and requires a bound trusted_context with matching verified_producer.
    """
    if not isinstance(producer, str) or not producer.strip():
        raise ValueError("producer must be a non-empty string")
    norm = producer.strip().lower()
    if norm in FORBIDDEN_SELF_PRODUCERS:
        raise ValueError(f"producer {producer!r} is forbidden from issuing SLOW promotion evidence (C2/M7)")
    if not isinstance(trusted_context, Mapping) or trusted_context.get("verified_producer") != producer:
        raise ValueError("SLOW promotion requires trusted_context binding matching producer (C2/M7)")
    if not trusted_context.get("isolated_evaluator", False):
        raise ValueError("trusted_context must confirm isolated_evaluator=True")
    return producer


# ---------------------------------------------------------------------------
# Conformal Applicability Domain D_valid with 4a Exclusion & FPCA (D3-4, N4, S3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConformalDomainCertificate:
    """Calibrated applicability domain D_valid certificate (ADR-0014 §2 D3-4)."""

    certificate_valid: bool
    n_cal_raw: int
    n_cal_clean: int
    n_removed_4a: int
    order_stat_k: int
    alpha_dom: float
    residual_quantile: float
    fpca_coeff_quantiles: tuple[float, ...]
    fpca_basis_data_id: str
    calibration_data_id: str
    exchangeability_ratio: float
    envelope: DomainEnvelope | None
    reason: str


def calibrate_conformal_domain(
    discovery_contexts: Sequence[ObservationContext],
    calibration_contexts: Sequence[ObservationContext],
    prior_belief: ParamBelief,
    registration: CMFLRegistration,
    *,
    residual_accel_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
    discovery_data_id: str = "D_discovery",
    calibration_data_id: str = "C_calibration",
) -> ConformalDomainCertificate:
    """Calibrate D_valid = (D u C_clean) covariate envelope n C_clean residual quantile (ADR-0014 §2 D3-4).

    Enforces:
    - S3: FPCA basis is estimated strictly on discovery_contexts (D) and frozen before touching C.
    - N4: Deterministic exclusion of 4a COVARIANCE_INCONSISTENT windows from C to form C_clean.
    - Finite-sample order statistic k = ceil((1 - alpha_dom) * (n_cal + 1)); if n_cal < n_min or
      k > n_cal, certificate is empty and promotion is rejected.
    """
    if discovery_data_id == calibration_data_id:
        raise ValueError("discovery_data_id and calibration_data_id must be disjoint")

    # 1. Estimate FPCA basis strictly on discovery set D (S3)
    d_curves: list[np.ndarray] = []
    for ctx in discovery_contexts:
        pred = integrate_one_step(
            ctx.states,
            ctx.actions,
            ctx.dt,
            prior_belief.mean,
            integrator=ctx.integrator,
            residual_accel_fn=residual_accel_fn,
        )
        step_err = np.linalg.norm(ctx.next_states - pred, axis=-1)  # (W,)
        d_curves.append(step_err)
    d_mat = np.asarray(d_curves, dtype=float)  # (N_D, W)
    d_mean = np.mean(d_mat, axis=0, keepdims=True)
    _, _, vt = np.linalg.svd(d_mat - d_mean, full_matrices=False)
    r_rank = min(registration.r_fpca, vt.shape[0])
    fpca_basis = vt[:r_rank].T  # (W, r_rank), frozen on D!

    # 2. Run frozen MSG on C and deterministically remove 4a COVARIANCE_INCONSISTENT windows (N4)
    msg = MechanismSufficiencyGate(registration)
    c_clean: list[ObservationContext] = []
    removed_4a = 0
    for ctx in calibration_contexts:
        rec = msg.route(ctx, prior_belief)
        if rec.route_code == RouteCode.COVARIANCE_INCONSISTENT:
            removed_4a += 1
        else:
            c_clean.append(ctx)

    n_raw = len(calibration_contexts)
    n_cal = len(c_clean)
    k_ord = int(math.ceil((1.0 - registration.alpha_dom) * (n_cal + 1)))

    if n_cal < registration.n_cal_min or k_ord > n_cal or n_cal == 0:
        return ConformalDomainCertificate(
            certificate_valid=False,
            n_cal_raw=n_raw,
            n_cal_clean=n_cal,
            n_removed_4a=removed_4a,
            order_stat_k=k_ord,
            alpha_dom=registration.alpha_dom,
            residual_quantile=float("inf"),
            fpca_coeff_quantiles=(),
            fpca_basis_data_id=discovery_data_id,
            calibration_data_id=calibration_data_id,
            exchangeability_ratio=float("inf"),
            envelope=None,
            reason=(
                f"empty conformal certificate: n_cal={n_cal} (min={registration.n_cal_min}), "
                f"k={k_ord} > n_cal={n_cal} after removing {removed_4a} 4a windows"
            ),
        )

    # 3. Compute residual scores and FPCA coefficients on C_clean
    c_scores = np.zeros(n_cal, dtype=float)
    c_fpca_coeffs = np.zeros((n_cal, r_rank), dtype=float)
    first_half_means: list[float] = []
    second_half_means: list[float] = []

    for i, ctx in enumerate(c_clean):
        pred = integrate_one_step(
            ctx.states,
            ctx.actions,
            ctx.dt,
            prior_belief.mean,
            integrator=ctx.integrator,
            residual_accel_fn=residual_accel_fn,
        )
        step_err = np.linalg.norm(ctx.next_states - pred, axis=-1)
        c_scores[i] = float(np.max(step_err))
        c_fpca_coeffs[i] = np.abs((step_err - d_mean[0]) @ fpca_basis)
        half = len(step_err) // 2
        first_half_means.append(float(np.mean(step_err[:half])))
        second_half_means.append(float(np.mean(step_err[half:])))

    sorted_scores = np.sort(c_scores)
    q_res = float(sorted_scores[k_ord - 1])
    fpca_quants = tuple(float(np.sort(c_fpca_coeffs[:, r])[k_ord - 1]) for r in range(r_rank))

    m1 = max(float(np.mean(first_half_means)), 1e-12)
    m2 = max(float(np.mean(second_half_means)), 1e-12)
    exch_ratio = max(m1 / m2, m2 / m1)

    # Covariate envelope over D u C_clean
    all_states = np.concatenate([c.states for c in list(discovery_contexts) + c_clean], axis=0)
    all_actions = np.concatenate([c.actions for c in list(discovery_contexts) + c_clean], axis=0)
    envelope = DomainEnvelope(
        state_min=np.min(all_states, axis=0),
        state_max=np.max(all_states, axis=0),
        action_min=np.min(all_actions, axis=0),
        action_max=np.max(all_actions, axis=0),
    )

    return ConformalDomainCertificate(
        certificate_valid=True,
        n_cal_raw=n_raw,
        n_cal_clean=n_cal,
        n_removed_4a=removed_4a,
        order_stat_k=k_ord,
        alpha_dom=registration.alpha_dom,
        residual_quantile=q_res,
        fpca_coeff_quantiles=fpca_quants,
        fpca_basis_data_id=discovery_data_id,
        calibration_data_id=calibration_data_id,
        exchangeability_ratio=float(exch_ratio),
        envelope=envelope,
        reason="ok",
    )


# ---------------------------------------------------------------------------
# FactTest Order-Statistic Threshold Calibration on Null Candidates (D3-8, M3)
# ---------------------------------------------------------------------------

def calibrate_facttest_threshold(
    null_candidate_scores: Sequence[float] | np.ndarray,
    tau_cal: float,
    delta_cal: float,
) -> tuple[float, int]:
    """Invert OSVerify Appendix B.4 order-statistic threshold with known invalid candidates as null (ADR-0014 §2 D3-8).

    Given scores s_1 <= s_2 <= ... <= s_n of known invalid/degenerate null candidates (where larger
    score means more likely to pass), selects the smallest order statistic index k such that
    P(Binomial(n, 1 - tau_cal) >= k) <= delta_cal, so the probability that more than tau_cal fraction
    of invalid candidates exceed threshold s_(k) is <= delta_cal.
    """
    scores = np.sort(np.asarray(null_candidate_scores, dtype=float))
    n = len(scores)
    if n < 1:
        raise ValueError("null_candidate_scores must be non-empty")
    p_pass = 1.0 - tau_cal
    for k in range(1, n + 1):
        # Upper tail P(Bin(n, p_pass) >= k) = sum_{j=k}^n C(n, j) p^j (1-p)^{n-j}
        tail_prob = 0.0
        for j in range(k, n + 1):
            tail_prob += math.comb(n, j) * (p_pass ** j) * ((1.0 - p_pass) ** (n - j))
        if tail_prob <= delta_cal:
            return float(scores[k - 1]), k
    return float(scores[-1] + 1e-6), n + 1


# ---------------------------------------------------------------------------
# World-Block Paired Bootstrap, All-Environment E_pers, and e-LOND Gate (D3)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PromotionDecision:
    """Complete decision record for a single MID -> SLOW promotion test step t."""

    step_t: int
    candidate_id: str
    test_id: str
    admitted: bool
    alpha_t: float
    alpha_per_candidate: float
    n_candidates_submitted: int
    n_world_blocks: int
    bootstrap_mean_delta: float
    bootstrap_upper_bound: float
    delta_gain_threshold: float
    superiority_passed: bool
    old_capability_passed: bool
    zero_regression_passed: bool
    reproducibility_filter_passed: bool
    conformal_certificate_valid: bool
    e_pers: float
    e_by_family: Mapping[str, float]
    e_lond_passed: bool
    binomial_audit_upper_bound: float
    producer: str
    rejection_reasons: tuple[str, ...]


class OneSidedPromotionGate:
    """Stateful MID -> SLOW promotion gate with e-LOND sequence control and N3 re-test accounting."""

    def __init__(
        self,
        registration: CMFLRegistration,
        *,
        library: Sequence[BasisTermSpec] | None = None,
    ) -> None:
        self.registration = registration
        lib = default_basis_library() if library is None else tuple(library)
        self.library_map: dict[str, BasisTermSpec] = {t.name: t for t in lib}
        self._step_t: int = 0
        self._num_promoted_R: int = 0
        self._used_test_data_ids: set[str] = set()
        self._candidate_attempts: dict[str, int] = {}
        self._ledger: list[PromotionDecision] = []

    @property
    def step_t(self) -> int:
        return self._step_t

    @property
    def num_promoted_R(self) -> int:
        return self._num_promoted_R

    @property
    def ledger(self) -> tuple[PromotionDecision, ...]:
        return tuple(self._ledger)

    def current_alpha_t(self, step_index_1based: int) -> float:
        """Compute e-LOND budget alpha_t = alpha_seq * gamma_t * (R_{t-1} + 1) (ADR-0014 §2 D3)."""
        sched = self.registration.gamma_schedule
        if step_index_1based <= len(sched):
            gamma_t = sched[step_index_1based - 1]
        else:
            gamma_t = 6.0 / ((math.pi * step_index_1based) ** 2)
        return float(self.registration.alpha_seq * gamma_t * (self._num_promoted_R + 1))

    def _world_block_errors(
        self,
        test_contexts: Sequence[ObservationContext],
        prior_belief: ParamBelief,
        candidate: DiscoveredCandidate,
    ) -> tuple[dict[str, float], dict[str, float], dict[str, str], bool]:
        """Aggregate MSE per independent world_instance_id block (ADR-0014 §2 D3-1 & M2-ii).

        Also checks D3-6 reproducibility & step-halving numerical stability filter.
        """
        res_fn = lambda s, u: candidate.predict_residual_accel(s, self.library_map)
        base_errs: dict[str, list[float]] = {}
        cand_errs: dict[str, list[float]] = {}
        world_family_map: dict[str, str] = {}
        stable_ok = True

        for ctx in test_contexts:
            wid = ctx.world_instance_id
            pred_base = integrate_one_step(
                ctx.states, ctx.actions, ctx.dt, prior_belief.mean, integrator=ctx.integrator
            )
            pred_cand_1 = integrate_one_step(
                ctx.states,
                ctx.actions,
                ctx.dt,
                prior_belief.mean,
                integrator=ctx.integrator,
                residual_accel_fn=res_fn,
            )
            pred_cand_2 = integrate_one_step(
                ctx.states,
                ctx.actions,
                ctx.dt,
                prior_belief.mean,
                integrator=ctx.integrator,
                residual_accel_fn=res_fn,
            )
            # Reproducibility filter (100% deterministic match) + step-halving check (D3-6)
            if not np.allclose(pred_cand_1, pred_cand_2, atol=0.0, rtol=0.0):
                stable_ok = False
            half_mid = integrate_one_step(
                ctx.states,
                ctx.actions,
                0.5 * ctx.dt,
                prior_belief.mean,
                integrator=ctx.integrator,
                residual_accel_fn=res_fn,
            )
            pred_half = integrate_one_step(
                half_mid,
                ctx.actions,
                0.5 * ctx.dt,
                prior_belief.mean,
                integrator=ctx.integrator,
                residual_accel_fn=res_fn,
            )
            r_cand = ctx.next_states - pred_cand_1
            if float(np.linalg.norm(pred_cand_1 - pred_half)) >= self.registration.kappa * max(
                float(np.linalg.norm(r_cand)), 1e-12
            ):
                stable_ok = False

            e0 = float(np.mean(((ctx.next_states - pred_base) / ctx.dt) ** 2))
            e1 = float(np.mean(((ctx.next_states - pred_cand_1) / ctx.dt) ** 2))
            base_errs.setdefault(wid, []).append(e0)
            cand_errs.setdefault(wid, []).append(e1)
            # Infer declared environment family prefix from context_id or world_instance_id if tagged
            fam = self.registration.env_families[0]
            for f_name in self.registration.env_families:
                if f_name.lower() in wid.lower() or f_name.lower() in ctx.context_id.lower():
                    fam = f_name
                    break
            world_family_map[wid] = fam

        base_block = {w: float(np.mean(v)) for w, v in base_errs.items()}
        cand_block = {w: float(np.mean(v)) for w, v in cand_errs.items()}
        return base_block, cand_block, world_family_map, stable_ok

    def evaluate_and_promote(
        self,
        candidate: DiscoveredCandidate,
        prior_belief: ParamBelief,
        *,
        discovery_contexts: Sequence[ObservationContext],
        calibration_contexts: Sequence[ObservationContext],
        test_contexts: Sequence[ObservationContext],
        discovery_data_id: str,
        calibration_data_id: str,
        test_data_id: str,
        test_id: str,
        producer: str,
        trusted_context: Mapping[str, Any],
        old_benchmark_contexts: Sequence[ObservationContext] | None = None,
        old_loss_epsilon: float = 1e-4,
    ) -> PromotionDecision:
        """Execute one-sided promotion test at step t (ADR-0014 §2 D3)."""
        # 1. Enforce producer independence (C2 / M7)
        require_independent_slow_producer(producer, trusted_context=trusted_context)

        # 2. Enforce disjoint data identities (D, C, T)
        if len({discovery_data_id, calibration_data_id, test_data_id}) != 3:
            raise ValueError("D, C, and T data identities must be strictly pairwise disjoint (D3)")
        d_worlds = {c.world_instance_id for c in discovery_contexts}
        c_worlds = {c.world_instance_id for c in calibration_contexts}
        t_worlds = {c.world_instance_id for c in test_contexts}
        if (d_worlds & c_worlds) or (d_worlds & t_worlds) or (c_worlds & t_worlds):
            raise ValueError("world_instance_id sets of D, C, and T must be strictly disjoint")

        # 3. Enforce N3 re-test accounting rule: T_{t'} must be disjoint from all previous test sets T_1..T_{t'-1}
        if test_data_id in self._used_test_data_ids:
            raise ValueError(
                f"re-test accounting violation (N3): test_data_id {test_data_id!r} was already opened in an earlier step"
            )
        self._used_test_data_ids.add(test_data_id)

        # Increment sequence step t
        self._step_t += 1
        t = self._step_t
        alpha_t = self.current_alpha_t(t)

        # Track total attempts N (including any re-tests) against N_max
        prev_attempts = self._candidate_attempts.get(candidate.discovery_data_id, 0)
        n_total_attempts = max(int(candidate.total_candidates_attempted), prev_attempts + 1)
        self._candidate_attempts[candidate.discovery_data_id] = n_total_attempts

        n_sub = max(1, n_total_attempts)
        alpha_per_cand = alpha_t / n_sub
        reasons: list[str] = []

        if n_total_attempts > self.registration.N_max:
            reasons.append(f"candidate attempts N={n_total_attempts} exceeds frozen N_max={self.registration.N_max}")

        if len(candidate.active_terms) == 0:
            reasons.append("candidate has 0 active terms (empty discovery)")

        # 4. Calibrate D_valid conformal certificate on C_clean (removing 4a windows per N4)
        res_fn = lambda s, u: candidate.predict_residual_accel(s, self.library_map)
        cert = calibrate_conformal_domain(
            discovery_contexts,
            calibration_contexts,
            prior_belief,
            self.registration,
            residual_accel_fn=res_fn,
            discovery_data_id=discovery_data_id,
            calibration_data_id=calibration_data_id,
        )
        if not cert.certificate_valid:
            reasons.append(cert.reason)

        # 5. World-level block evaluation on T (M2-ii)
        base_block, cand_block, world_fam, stable_ok = self._world_block_errors(
            test_contexts, prior_belief, candidate
        )
        world_ids = sorted(base_block.keys())
        n_worlds = len(world_ids)
        if n_worlds < self.registration.n_min:
            reasons.append(f"world block count n={n_worlds} < n_min={self.registration.n_min}")
        if not stable_ok:
            reasons.append("failed D3-6 reproducibility / step-halving stability filter")

        deltas = np.array([cand_block[w] - base_block[w] for w in world_ids], dtype=float)
        mean_delta = float(np.mean(deltas))

        # Paired bootstrap over world blocks at level 1 - alpha_t / (2N) (D3-1 & M3)
        rng = np.random.default_rng(self.registration.rng_seed + t)
        boot_idx = rng.integers(0, n_worlds, size=(self.registration.B_boot, n_worlds))
        boot_means = np.mean(deltas[boot_idx], axis=1)
        conf_level = max(0.50, 1.0 - alpha_t / (2.0 * n_sub))
        u_bound = float(np.quantile(boot_means, conf_level))
        sup_passed = bool(u_bound < -self.registration.delta_gain)
        if not sup_passed:
            reasons.append(
                f"paired world-block bootstrap upper bound U={u_bound:.6f} >= -delta_gain={-self.registration.delta_gain:.6f}"
            )

        # D3-5 Per-instance zero regression on T (0 violations hard gate)
        zero_reg_passed = bool(np.all(deltas <= 1e-9))
        if not zero_reg_passed:
            n_viol = int(np.sum(deltas > 1e-9))
            reasons.append(f"per-instance zero-regression gate failed: {n_viol}/{n_worlds} worlds regressed")

        # D3-2 Old-capability retention (Eq. 6: L_old <= L_baseline + epsilon)
        old_passed = True
        if old_benchmark_contexts:
            old_base, old_cand, _, _ = self._world_block_errors(
                old_benchmark_contexts, prior_belief, candidate
            )
            old_deltas = np.array([old_cand[w] - old_base[w] for w in sorted(old_base.keys())], dtype=float)
            if float(np.max(old_deltas)) > old_loss_epsilon:
                old_passed = False
                reasons.append(f"Eq. 6 old-capability retention failed: max delta={float(np.max(old_deltas)):.6f}")

        # D3-3 All-environment world-block e-process E_pers = min_e E^e + e-LOND check (M2)
        e_by_fam: dict[str, float] = {}
        lam_grid = self.registration.lambda_grid
        for fam in self.registration.env_families:
            fam_worlds = [w for w in world_ids if world_fam.get(w) == fam]
            if not fam_worlds:
                # If test set isn't partitioned by family tags, evaluate across all world blocks
                fam_worlds = world_ids
            wealth_by_lam = np.ones(len(lam_grid), dtype=float)
            for w in fam_worlds:
                # Bounded world-block improvement score z_w in [-1, 1]; under null (cand worse than base + margin), z_w <= 0
                raw_gain = (base_block[w] - cand_block[w]) - self.registration.delta_gain
                scale = max(base_block[w], self.registration.delta_gain, 1e-6)
                z_w = float(np.clip(raw_gain / scale, -1.0, 1.0))
                for k_i, lam in enumerate(lam_grid):
                    wealth_by_lam[k_i] *= max(0.0, 1.0 + lam * z_w)
            e_by_fam[fam] = float(np.mean(wealth_by_lam))

        e_pers = float(min(e_by_fam.values()))
        e_lond_passed = bool(e_pers >= (1.0 / max(alpha_per_cand, 1e-15)) or sup_passed)
        # Note (ADR-0014 §2 D3 Table row 1 / N2): supports both e-process path (E_pers >= 1/alpha_t)
        # and fixed-sample bootstrap p-value path (<= alpha_t via sup_passed + old_passed) as distinct constructions.

        # D3-6 Exact binomial audit 95% upper bound on 0 failures: 1 - alpha_audit^{1/n}
        audit_ub = float(1.0 - (self.registration.alpha_audit ** (1.0 / max(n_worlds, 1))))

        admitted = (
            len(reasons) == 0
            and sup_passed
            and old_passed
            and zero_reg_passed
            and stable_ok
            and cert.certificate_valid
        )
        if admitted:
            self._num_promoted_R += 1

        decision = PromotionDecision(
            step_t=t,
            candidate_id=candidate.candidate_id,
            test_id=test_id,
            admitted=admitted,
            alpha_t=alpha_t,
            alpha_per_candidate=alpha_per_cand,
            n_candidates_submitted=n_sub,
            n_world_blocks=n_worlds,
            bootstrap_mean_delta=mean_delta,
            bootstrap_upper_bound=u_bound,
            delta_gain_threshold=self.registration.delta_gain,
            superiority_passed=sup_passed,
            old_capability_passed=old_passed,
            zero_regression_passed=zero_reg_passed,
            reproducibility_filter_passed=stable_ok,
            conformal_certificate_valid=cert.certificate_valid,
            e_pers=e_pers,
            e_by_family=e_by_fam,
            e_lond_passed=e_lond_passed,
            binomial_audit_upper_bound=audit_ub,
            producer=producer,
            rejection_reasons=tuple(reasons),
        )
        self._ledger.append(decision)
        return decision


def simulate_elond_dev_only_vs_all_env(
    registration: CMFLRegistration,
    *,
    n_steps: int = 24,
    seed: int = 20261028,
    blocks_per_family: int = 60,
) -> dict[str, Any]:
    """Demonstrate ADR-0014 §2 D3-3 M2 warning:
    When non-persistent (single-environment overfit) candidates are fed into dev-only e-LOND,
    persistent-target FDR is severely inflated, whereas feeding all-environment intersection-union
    E_pers = min_e E^e controls persistent FDR <= alpha_seq.
    """
    rng = np.random.default_rng(seed)
    lam_grid = registration.lambda_grid
    sched = registration.gamma_schedule

    r_dev = 0
    false_dev = 0
    r_pers = 0
    false_pers = 0

    for t in range(1, n_steps + 1):
        gamma_t = sched[t - 1] if t <= len(sched) else 6.0 / ((math.pi * t) ** 2)
        is_truly_persistent = (t % 4 == 0)  # 25% truly persistent across all 3 families; 75% overfit only env 0

        e_vals: list[float] = []
        for env_idx in range(len(registration.env_families)):
            wealth = np.ones(len(lam_grid), dtype=float)
            # 每个环境族的世界级 block 数。必须足够多：e-LOND 在第 t 步要求 e ≥ 1/(α·γ_t·(R+1))，γ_t 随 t 快速衰减，
            # block 太少（原先 12）时任何候选——包括真正跨环境成立的——都到不了门槛，dev-only 的 FDP 会是 0/max(0,1)=0，
            # 演示就空了（"没人被准入"不等于"FDR 受控"）。同时返回准入数，调用方必须看到分母不是 0。
            for _ in range(blocks_per_family):
                if is_truly_persistent or env_idx == 0:
                    z = float(np.clip(rng.normal(0.55, 0.20), -1.0, 1.0))
                else:
                    # Fails on held-out environment families 1 and 2
                    z = float(np.clip(rng.normal(-0.45, 0.20), -1.0, 1.0))
                for k_i, lam in enumerate(lam_grid):
                    wealth[k_i] *= max(0.0, 1.0 + lam * z)
            e_vals.append(float(np.mean(wealth)))

        e_dev_only = e_vals[0]
        e_pers = min(e_vals)

        alpha_dev = registration.alpha_seq * gamma_t * (r_dev + 1)
        if e_dev_only >= 1.0 / max(alpha_dev, 1e-15):
            r_dev += 1
            if not is_truly_persistent:
                false_dev += 1

        alpha_pers = registration.alpha_seq * gamma_t * (r_pers + 1)
        if e_pers >= 1.0 / max(alpha_pers, 1e-15):
            r_pers += 1
            if not is_truly_persistent:
                false_pers += 1

    return {
        "n_steps": n_steps,
        "blocks_per_family": blocks_per_family,
        "dev_only_admitted": r_dev,
        "dev_only_false_persistent": false_dev,
        "dev_only_persistent_fdp": float(false_dev / max(r_dev, 1)),
        "all_env_admitted": r_pers,
        "all_env_false_persistent": false_pers,
        "all_env_persistent_fdp": float(false_pers / max(r_pers, 1)),
    }
