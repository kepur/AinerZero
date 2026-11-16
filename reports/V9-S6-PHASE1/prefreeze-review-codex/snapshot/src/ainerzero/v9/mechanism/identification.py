"""Online parameter identification, Fisher information, EIG, and sensitivity orthogonal projection.

Pure NumPy implementation of ADR-0014 r3 §2 D1 (rows 4a/4b/5/6), §2 D2-7 (S1/S5), and §2 D4 (S2).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .registration import DPermitSpec, ParamBelief
from .toy_worlds import (
    ObservationContext,
    integrate_one_step,
    k_step_propagated_sensitivity,
    step_sensitivity_jacobian,
)


def _step_cov_inv(innovation_cov: np.ndarray, k: int) -> np.ndarray:
    cov_k = innovation_cov if innovation_cov.ndim == 2 else innovation_cov[k]
    return np.linalg.inv(cov_k)


def compute_innovations_and_nis(
    context: ObservationContext,
    phi: np.ndarray,
    *,
    indices: Sequence[int] | np.ndarray | None = None,
    param_cov: np.ndarray | None = None,
) -> tuple[np.ndarray, float, int]:
    """Compute step innovations r_k = s_{k+1}^{obs} - F_prior(s_k, u_k, dt; phi) and NIS statistic.

    When param_cov is provided (e.g., holdout validation after online parameter update), uses the
    posterior predictive innovation covariance S_k + J_k @ param_cov @ J_k^T.
    Returns (residuals_on_indices, nis_stat, dof).
    """
    w = context.states.shape[0]
    idx = np.arange(w) if indices is None else np.asarray(indices, dtype=int)
    states = context.states[idx]
    next_states = context.next_states[idx]
    actions = context.actions[idx]
    pred = integrate_one_step(states, actions, context.dt, phi, integrator=context.integrator)
    residuals = next_states - pred
    jac = (
        step_sensitivity_jacobian(states, actions, context.dt, phi, integrator=context.integrator)
        if param_cov is not None
        else None
    )
    nis = 0.0
    for local_i, k in enumerate(idx):
        cov_k = context.innovation_cov if context.innovation_cov.ndim == 2 else context.innovation_cov[int(k)]
        if jac is not None and param_cov is not None:
            j_k = jac[local_i]
            cov_k = cov_k + j_k @ param_cov @ j_k.T
        s_inv = np.linalg.inv(cov_k)
        r_k = residuals[local_i]
        nis += float(r_k @ s_inv @ r_k)
    dof = int(len(idx) * context.states.shape[1])
    return residuals, float(nis), dof


def dimensionless_fisher_information(
    context: ObservationContext,
    phi: np.ndarray,
    dimensionless_scale: np.ndarray,
    *,
    indices: Sequence[int] | np.ndarray | None = None,
) -> tuple[np.ndarray, float]:
    """Compute dimensionless Fisher Information Matrix I_{phi_tilde} and its minimum eigenvalue.

    I_{phi_tilde} = diag(scale) * (sum_{k} J_k^T S_k^{-1} J_k) * diag(scale)  (ADR-0014 §2 D1-6).
    """
    w = context.states.shape[0]
    idx = np.arange(w) if indices is None else np.asarray(indices, dtype=int)
    jac = step_sensitivity_jacobian(
        context.states[idx],
        context.actions[idx],
        context.dt,
        phi,
        integrator=context.integrator,
    )
    p = len(phi)
    fim = np.zeros((p, p), dtype=float)
    for local_i, k in enumerate(idx):
        s_inv = _step_cov_inv(context.innovation_cov, int(k))
        j_k = jac[local_i]
        fim += j_k.T @ s_inv @ j_k
    scale_mat = np.diag(np.asarray(dimensionless_scale, dtype=float))
    fim_dimless = scale_mat @ fim @ scale_mat
    fim_dimless = 0.5 * (fim_dimless + fim_dimless.T)
    lam_min = float(np.linalg.eigvalsh(fim_dimless)[0])
    return fim_dimless, lam_min


def posterior_model_entropy(probs: Sequence[float] | np.ndarray) -> float:
    """Shannon entropy H(p(m|D)) = -sum_i p_i ln(p_i) for competing mechanisms."""
    p = np.asarray(probs, dtype=float)
    if p.size == 0 or np.any(p < 0.0):
        raise ValueError("competing model probabilities must be non-negative and non-empty")
    total = float(np.sum(p))
    if total <= 0.0:
        raise ValueError("sum of competing model probabilities must be positive")
    p = p / total
    mask = p > 1e-15
    return float(-np.sum(p[mask] * np.log(p[mask])))


def identify_parameters_bayesian(
    context: ObservationContext,
    prior_belief: ParamBelief,
    *,
    fit_indices: Sequence[int] | np.ndarray | None = None,
    max_iter: int = 4,
) -> ParamBelief:
    """Iterated Bayesian Gauss-Newton / MAP parameter update with exact linearized posterior covariance.

    Updates p(phi | D) on fit_indices (defaults to full window) without neural networks.
    """
    w = context.states.shape[0]
    idx = np.arange(w) if fit_indices is None else np.asarray(fit_indices, dtype=int)
    phi_0 = prior_belief.mean.copy()
    prec_0 = np.linalg.inv(prior_belief.cov)
    phi_est = phi_0.copy()

    states = context.states[idx]
    next_states = context.next_states[idx]
    actions = context.actions[idx]

    post_cov = prior_belief.cov.copy()
    for _ in range(max_iter):
        pred = integrate_one_step(states, actions, context.dt, phi_est, integrator=context.integrator)
        res = next_states - pred
        jac = step_sensitivity_jacobian(states, actions, context.dt, phi_est, integrator=context.integrator)
        info = prec_0.copy()
        grad = prec_0 @ (phi_0 - phi_est)
        for local_i, k in enumerate(idx):
            s_inv = _step_cov_inv(context.innovation_cov, int(k))
            j_k = jac[local_i]
            info += j_k.T @ s_inv @ j_k
            grad += j_k.T @ s_inv @ res[local_i]
        info = 0.5 * (info + info.T)
        post_cov = np.linalg.inv(info)
        post_cov = 0.5 * (post_cov + post_cov.T)
        delta = post_cov @ grad
        phi_est = phi_est + delta
        if float(np.linalg.norm(delta)) < 1e-10:
            break

    return ParamBelief(
        mean=phi_est,
        cov=post_cov,
        dimensionless_scale=prior_belief.dimensionless_scale,
        updated_at_ticks=int(context.t_start + len(idx)),
        param_names=prior_belief.param_names,
    )


# ---------------------------------------------------------------------------
# Expected Information Gain (EIG_phi) and Probe Selection (ADR-0014 §2 D4)
# ---------------------------------------------------------------------------

def gaussian_eig_phi(
    state: np.ndarray,
    action: np.ndarray,
    dt: float,
    belief: ParamBelief,
    innovation_cov: np.ndarray,
    *,
    integrator: str = "rk4",
) -> float:
    """Analytical linear-Gaussian Expected Information Gain:
    EIG_phi(a) = 0.5 * log det(I + S^{-1} J(s, a) Sigma_phi J(s, a)^T)  (ADR-0014 §2 D4).
    """
    s = np.asarray(state, dtype=float).reshape(1, 4)
    u = np.asarray(action, dtype=float).reshape(1, 2)
    j = step_sensitivity_jacobian(s, u, dt, belief.mean, integrator=integrator)[0]  # (4, p)
    cov_s = innovation_cov if innovation_cov.ndim == 2 else innovation_cov[0]
    s_inv = np.linalg.inv(cov_s)
    mat = np.eye(4, dtype=float) + s_inv @ (j @ belief.cov @ j.T)
    sign, logdet = np.linalg.slogdet(mat)
    if sign <= 0:
        raise ValueError("EIG covariance matrix must have positive determinant")
    return float(0.5 * logdet)


def nested_mc_eig_phi(
    state: np.ndarray,
    action: np.ndarray,
    dt: float,
    belief: ParamBelief,
    innovation_cov: np.ndarray,
    *,
    M_out: int,
    M_in: int,
    rng: np.random.Generator,
    integrator: str = "rk4",
) -> float:
    """Nested Monte Carlo estimator for EIG_phi(a) with registered (M_in, M_out) (ADR-0014 §2 D4).

    Note: Due to Jensen's inequality on -log((1/M_in) sum_j p(y | phi_j)), finite M_in
    produces an upward bias relative to the exact marginal log-likelihood.
    """
    if M_out < 2 or M_in < 2:
        raise ValueError("M_out and M_in must be >= 2")
    s = np.asarray(state, dtype=float).reshape(1, 4)
    u = np.asarray(action, dtype=float).reshape(1, 2)
    cov_s = innovation_cov if innovation_cov.ndim == 2 else innovation_cov[0]
    s_inv = np.linalg.inv(cov_s)
    d = 4
    _, logdet_s = np.linalg.slogdet(cov_s)
    log_norm_const = -0.5 * (d * np.log(2.0 * np.pi) + logdet_s)

    phi_outer = rng.multivariate_normal(belief.mean, belief.cov, size=M_out)
    mean_outer = np.zeros((M_out, 4), dtype=float)
    for i in range(M_out):
        mean_outer[i] = integrate_one_step(s[0], u[0], dt, phi_outer[i], integrator=integrator)

    noise = rng.multivariate_normal(np.zeros(4), cov_s, size=M_out)
    y_samples = mean_outer + noise

    # Conditional log likelihood log p(y_i | phi_outer_i)
    log_p_cond = np.zeros(M_out, dtype=float)
    for i in range(M_out):
        diff = y_samples[i] - mean_outer[i]
        log_p_cond[i] = log_norm_const - 0.5 * float(diff @ s_inv @ diff)

    # Inner MC marginal likelihood estimate for each outer sample
    log_p_marg = np.zeros(M_out, dtype=float)
    for i in range(M_out):
        phi_inner = rng.multivariate_normal(belief.mean, belief.cov, size=M_in)
        log_likes = np.zeros(M_in, dtype=float)
        for j in range(M_in):
            mu_ij = integrate_one_step(s[0], u[0], dt, phi_inner[j], integrator=integrator)
            diff = y_samples[i] - mu_ij
            log_likes[j] = log_norm_const - 0.5 * float(diff @ s_inv @ diff)
        max_ll = float(np.max(log_likes))
        log_p_marg[i] = max_ll + float(np.log(np.mean(np.exp(log_likes - max_ll))))

    return float(np.mean(log_p_cond - log_p_marg))


@dataclass(frozen=True)
class ProbeSelectionResult:
    """Result of MechBench-order competing mechanism screening and EIG probe selection."""

    selected_action: np.ndarray
    selected_eig: float
    distinguishable_observables: tuple[int, ...]
    candidate_eigs: tuple[float, ...]


def screen_and_select_probe(
    state: np.ndarray,
    candidate_actions: Sequence[np.ndarray] | np.ndarray,
    dt: float,
    belief: ParamBelief,
    innovation_cov: np.ndarray,
    d_permit: DPermitSpec,
    *,
    integrator: str = "rk4",
) -> ProbeSelectionResult:
    """MechBench order (ADR-0014 §2 D1-6 & D4):
    1. Screen observables where parameter perturbations produce distinguishable state differences.
    2. Filter candidate actions to those strictly inside D_permit.
    3. Select a* = argmax_{a in D_permit} EIG_phi(a).
    """
    s = np.asarray(state, dtype=float)
    if np.max(np.abs(s[:2])) > d_permit.position_limit or np.max(np.abs(s[2:4])) > d_permit.speed_limit:
        raise ValueError("current state violates D_permit; cannot select active probe")

    valid_actions: list[np.ndarray] = []
    for a in candidate_actions:
        arr = np.asarray(a, dtype=float)
        if arr.shape == (2,) and float(np.max(np.abs(arr))) <= d_permit.action_limit:
            valid_actions.append(arr)
    if not valid_actions:
        raise ValueError("no candidate actions within D_permit bounds")

    # 1. Screen observables across valid actions using Jacobian column norms
    obs_sensitivity = np.zeros(4, dtype=float)
    for a in valid_actions:
        j = step_sensitivity_jacobian(s.reshape(1, 4), a.reshape(1, 2), dt, belief.mean, integrator=integrator)[0]
        obs_sensitivity += np.linalg.norm(j @ np.diag(belief.dimensionless_scale), axis=1)
    distinguishable = tuple(int(i) for i in range(4) if obs_sensitivity[i] > 1e-6)

    # 2. Compute EIG_phi(a) for each valid action
    eigs = [
        gaussian_eig_phi(s, a, dt, belief, innovation_cov, integrator=integrator)
        for a in valid_actions
    ]
    best_idx = int(np.argmax(eigs))
    return ProbeSelectionResult(
        selected_action=valid_actions[best_idx].copy(),
        selected_eig=float(eigs[best_idx]),
        distinguishable_observables=distinguishable,
        candidate_eigs=tuple(float(v) for v in eigs),
    )


# ---------------------------------------------------------------------------
# Sensitivity Subspace Orthogonal Projection (ADR-0014 §2 D2-7, S1/S5)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrthogonalProjectionResult:
    """Result of projecting residual r onto the orthogonal complement of sensitivity subspace."""

    mode: str  # "single_step" or "k_step"
    raw_residuals: np.ndarray  # (W, 4)
    projected_residuals: np.ndarray  # (W, 4), orthogonal to span(G)
    absorbed_component: np.ndarray  # (W, 4), component in span(G) absorbed into phi_l2
    phi_l2_projected: np.ndarray  # (p,), L2-projected parameter phi_hat
    max_abs_inner_product: float  # max_j |<r_perp, q_j>| (should be < 1e-12)


def project_residual_orthogonal_to_sensitivity(
    context: ObservationContext,
    phi: np.ndarray,
    *,
    mode: str = "single_step",
) -> OrthogonalProjectionResult:
    """Hard-project residuals onto the orthogonal complement of dF_prior/dphi (or S_k^phi).

    Implements ADR-0014 §2 D2-7 (MOS-discrepancy 2610.09261 hard projection + S1 two-tier sensitivity):
    - mode == "single_step": uses step-wise dF_prior(s_k, u_k)/dphi
    - mode == "k_step": uses k-step propagated sensitivity S_k^phi = ds_{t+k}/dphi
    By definition, the component of the true discrepancy along span(G) is absorbed into
    the L2-projected parameter phi_l2_projected.
    """
    residuals, _, _ = compute_innovations_and_nis(context, phi)
    w, d = residuals.shape
    p = len(phi)
    if mode == "single_step":
        sens = step_sensitivity_jacobian(
            context.states, context.actions, context.dt, phi, integrator=context.integrator
        )
    elif mode == "k_step":
        sens = k_step_propagated_sensitivity(
            context.states[0], context.actions, context.dt, phi, integrator=context.integrator
        )
    else:
        raise ValueError(f"unsupported sensitivity mode: {mode!r}; expected 'single_step' or 'k_step'")

    g_mat = sens.reshape(w * d, p)  # (W*d, p)
    r_vec = residuals.reshape(w * d)

    # Orthonormal basis Q of col(G) via SVD with rank threshold
    u_svd, s_svd, _ = np.linalg.svd(g_mat, full_matrices=False)
    rank = int(np.sum(s_svd > 1e-12 * max(1.0, float(s_svd[0]))))
    q_basis = u_svd[:, :rank]  # (W*d, rank)

    absorbed_vec = q_basis @ (q_basis.T @ r_vec)
    r_perp_vec = r_vec - absorbed_vec

    # L2 projected parameter shift delta_phi = G^+ r_vec
    delta_phi, _, _, _ = np.linalg.lstsq(g_mat, r_vec, rcond=None)
    phi_l2 = np.asarray(phi, dtype=float) + delta_phi

    max_ip = float(np.max(np.abs(q_basis.T @ r_perp_vec))) if rank > 0 else 0.0
    return OrthogonalProjectionResult(
        mode=mode,
        raw_residuals=residuals,
        projected_residuals=r_perp_vec.reshape(w, d),
        absorbed_component=absorbed_vec.reshape(w, d),
        phi_l2_projected=phi_l2,
        max_abs_inner_product=max_ip,
    )
