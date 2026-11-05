"""2D particle toy mechanics worlds, integrators, and §8.6 observation/truth separation.

Implements:
- Gravity, linear & quadratic drag, Coulomb friction, linear/cubic spring, and 1/r altered-law gravity.
- Four core world families:
  * P_family: parameter discrepancy only (g, c_lin, k_spring randomized)
  * S_family: structural missing mechanism (quadratic drag or Coulomb friction missing from prior)
  * N_family: numerical integration discrepancy (coarse Euler step vs RK4/half-step)
  * altered_law_family: altered physical law (1/r central attraction or cubic spring)
- Additional route test contexts for ABSTAIN, OUT_OF_DOMAIN, COVARIANCE_INCONSISTENT (4a),
  SUFFICIENT (4b), and UNIDENTIFIABLE (6).
- Strict §8.6 boundary: ObservationContext contains zero ground-truth labels, world truth IDs, or true_phi.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Sequence

import numpy as np

from .registration import CMFLRegistration, RouteCode

DEFAULT_PHI = np.array([9.81, 0.25, 1.20], dtype=float)  # (g, c_lin, k_spring)
DEFAULT_SCALE = np.array([2.0, 0.20, 0.50], dtype=float)
COULOMB_V_EPS = 0.05
INV_R_SOFTENING = 0.25


def prior_acceleration(state: np.ndarray, action: np.ndarray, phi: np.ndarray) -> np.ndarray:
    """Continuous-time acceleration a(s, u; phi) for prior mechanics phi = (g, c_lin, k_spring)."""
    x, y, vx, vy = state[..., 0], state[..., 1], state[..., 2], state[..., 3]
    ux, uy = action[..., 0], action[..., 1]
    g, c_lin, k_spring = float(phi[0]), float(phi[1]), float(phi[2])
    ax = -c_lin * vx - k_spring * x + ux
    ay = -g - c_lin * vy - k_spring * y + uy
    return np.stack([ax, ay], axis=-1)


def structural_acceleration(
    state: np.ndarray,
    mechanism: str = "none",
    coeff: float = 0.0,
) -> np.ndarray:
    """Additional structural or altered-law acceleration term."""
    x, y, vx, vy = state[..., 0], state[..., 1], state[..., 2], state[..., 3]
    if mechanism == "none" or coeff == 0.0:
        return np.zeros_like(state[..., :2])
    if mechanism == "quadratic_drag":
        speed = np.hypot(vx, vy)
        return np.stack([-coeff * speed * vx, -coeff * speed * vy], axis=-1)
    if mechanism == "coulomb_friction":
        speed = np.hypot(vx, vy)
        unit_v = np.stack([vx, vy], axis=-1) / np.maximum(speed[..., None], 1e-8)
        return -coeff * np.tanh(speed / COULOMB_V_EPS)[..., None] * unit_v
    if mechanism == "altered_inv_r_gravity":
        r = np.hypot(x, y)
        denom = np.maximum(r * (r + INV_R_SOFTENING), 1e-6)
        return np.stack([-coeff * x / denom, -coeff * y / denom], axis=-1)
    if mechanism == "cubic_spring":
        r2 = x * x + y * y
        return np.stack([-coeff * r2 * x, -coeff * r2 * y], axis=-1)
    raise ValueError(f"unknown structural mechanism: {mechanism!r}")


def rhs_dynamics(
    state: np.ndarray,
    action: np.ndarray,
    phi: np.ndarray,
    *,
    mechanism: str = "none",
    coeff: float = 0.0,
    residual_accel_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
) -> np.ndarray:
    """Continuous-time state derivative ds/dt = [vx, vy, ax, ay]."""
    vel = state[..., 2:4]
    acc = prior_acceleration(state, action, phi) + structural_acceleration(state, mechanism, coeff)
    if residual_accel_fn is not None:
        acc = acc + residual_accel_fn(state, action)
    return np.concatenate([vel, acc], axis=-1)


def integrate_one_step(
    state: np.ndarray,
    action: np.ndarray,
    dt: float,
    phi: np.ndarray,
    *,
    integrator: str = "rk4",
    mechanism: str = "none",
    coeff: float = 0.0,
    residual_accel_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
) -> np.ndarray:
    """Single step numerical integration F_m(dt)(s, u; phi)."""
    s = np.asarray(state, dtype=float)
    u = np.asarray(action, dtype=float)
    if integrator == "euler":
        k1 = rhs_dynamics(s, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        return s + dt * k1
    if integrator == "rk2":
        k1 = rhs_dynamics(s, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        k2 = rhs_dynamics(s + 0.5 * dt * k1, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        return s + dt * k2
    if integrator == "rk4":
        k1 = rhs_dynamics(s, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        k2 = rhs_dynamics(s + 0.5 * dt * k1, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        k3 = rhs_dynamics(s + 0.5 * dt * k2, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        k4 = rhs_dynamics(s + dt * k3, u, phi, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn)
        return s + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
    raise ValueError(f"unsupported integrator: {integrator!r}")


def integrate_half_step_twice(
    state: np.ndarray,
    action: np.ndarray,
    dt: float,
    phi: np.ndarray,
    *,
    integrator: str = "rk4",
    mechanism: str = "none",
    coeff: float = 0.0,
    residual_accel_fn: Callable[[np.ndarray, np.ndarray], np.ndarray] | None = None,
) -> np.ndarray:
    """Step-halving composition F_m(dt/2 o dt/2) for NUMERICAL discrepancy check."""
    half = 0.5 * dt
    mid = integrate_one_step(
        state, action, half, phi, integrator=integrator, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn
    )
    return integrate_one_step(
        mid, action, half, phi, integrator=integrator, mechanism=mechanism, coeff=coeff, residual_accel_fn=residual_accel_fn
    )


def step_sensitivity_jacobian(
    state: np.ndarray,
    action: np.ndarray,
    dt: float,
    phi: np.ndarray,
    *,
    integrator: str = "rk4",
    eps: float = 1e-6,
) -> np.ndarray:
    """Single-step parameter sensitivity Jacobian dF_prior(s, u, dt; phi)/dphi of shape (W, 4, 3) or (4, 3)."""
    s = np.asarray(state, dtype=float)
    u = np.asarray(action, dtype=float)
    p = len(phi)
    out_shape = s.shape + (p,)
    jac = np.zeros(out_shape, dtype=float)
    for j in range(p):
        dp = np.zeros(p, dtype=float)
        dp[j] = eps
        f_plus = integrate_one_step(s, u, dt, phi + dp, integrator=integrator)
        f_minus = integrate_one_step(s, u, dt, phi - dp, integrator=integrator)
        jac[..., j] = (f_plus - f_minus) / (2.0 * eps)
    return jac


def k_step_propagated_sensitivity(
    initial_state: np.ndarray,
    actions: np.ndarray,
    dt: float,
    phi: np.ndarray,
    *,
    integrator: str = "rk4",
    eps: float = 1e-6,
) -> np.ndarray:
    """k-step propagated sensitivity S_k^phi = ds_{t+k}/dphi along open-loop rollout (ADR-0014 §2 D2-7 S1).

    Returns array of shape (W, 4, 3) for steps k = 1..W.
    """
    w = len(actions)
    p = len(phi)
    sens = np.zeros((w, 4, p), dtype=float)
    for j in range(p):
        dp = np.zeros(p, dtype=float)
        dp[j] = eps
        s_plus = np.array(initial_state, dtype=float, copy=True)
        s_minus = np.array(initial_state, dtype=float, copy=True)
        for k in range(w):
            s_plus = integrate_one_step(s_plus, actions[k], dt, phi + dp, integrator=integrator)
            s_minus = integrate_one_step(s_minus, actions[k], dt, phi - dp, integrator=integrator)
            sens[k, :, j] = (s_plus - s_minus) / (2.0 * eps)
    return sens


# ---------------------------------------------------------------------------
# Strict §8.6 Separation: ObservationContext vs Sealed GroundTruthMeta
# ---------------------------------------------------------------------------

FORBIDDEN_OBSERVATION_FIELDS = frozenset(
    {
        "true_route",
        "true_phi",
        "true_mechanism",
        "true_coeff",
        "sim_truth",
        "event_v1",
        "eval_channel",
    }
)


@dataclass(frozen=True)
class ObservationContext:
    """Learning-side observation window c = (belief_subgraph, W) obeying ADR-0014 §2 D1 / §8.6.

    Contains ONLY learner-visible quantities; never carries ground-truth labels or true parameters.
    """

    context_id: str
    world_instance_id: str
    t_start: int
    object_keys: tuple[str, ...]
    dt: float
    integrator: str
    states: np.ndarray  # shape (W, 4)
    next_states: np.ndarray  # shape (W, 4)
    actions: np.ndarray  # shape (W, 2)
    innovation_cov: np.ndarray  # shape (4, 4) or (W, 4, 4)
    requested_variables: tuple[str, ...] = ("x", "y", "vx", "vy", "ux", "uy")
    competing_model_probs: tuple[float, ...] = (1.0,)
    in_slow_domain: bool = True

    def __post_init__(self) -> None:
        s = np.array(self.states, dtype=float, copy=True)
        ns = np.array(self.next_states, dtype=float, copy=True)
        a = np.array(self.actions, dtype=float, copy=True)
        cov = np.array(self.innovation_cov, dtype=float, copy=True)
        if s.ndim != 2 or s.shape[1] != 4 or ns.shape != s.shape:
            raise ValueError("states and next_states must have shape (W, 4)")
        if a.ndim != 2 or a.shape != (s.shape[0], 2):
            raise ValueError("actions must have shape (W, 2)")
        if cov.shape not in ((4, 4), (s.shape[0], 4, 4)):
            raise ValueError("innovation_cov must have shape (4, 4) or (W, 4, 4)")
        s.setflags(write=False)
        ns.setflags(write=False)
        a.setflags(write=False)
        cov.setflags(write=False)
        object.__setattr__(self, "states", s)
        object.__setattr__(self, "next_states", ns)
        object.__setattr__(self, "actions", a)
        object.__setattr__(self, "innovation_cov", cov)


@dataclass(frozen=True)
class GroundTruthMeta:
    """Evaluation-only ground-truth metadata (sealed from MSG, identification, and promotion gate)."""

    context_id: str
    world_instance_id: str
    family: str
    true_route: RouteCode
    true_phi: np.ndarray
    true_mechanism: str
    true_coeff: float
    notes: str = ""


def simulate_window(
    *,
    context_id: str,
    world_instance_id: str,
    t_start: int,
    W: int,
    dt: float,
    true_integrator: str,
    model_integrator: str,
    true_phi: np.ndarray,
    true_mechanism: str,
    true_coeff: float,
    noise_std: float,
    reported_cov_scale: float,
    rng: np.random.Generator,
    init_state: np.ndarray | None = None,
    actions: np.ndarray | None = None,
    object_keys: tuple[str, ...] = ("obj_particle_0",),
    requested_variables: tuple[str, ...] = ("x", "y", "vx", "vy", "ux", "uy"),
    competing_model_probs: tuple[float, ...] = (1.0,),
    in_slow_domain: bool = True,
) -> ObservationContext:
    """Simulate a W-step trajectory window and package only learner-visible observations."""
    if init_state is None:
        init_state = np.array(
            [
                rng.uniform(-2.5, 2.5),
                rng.uniform(-2.5, 2.5),
                rng.uniform(-3.5, 3.5),
                rng.uniform(-3.5, 3.5),
            ],
            dtype=float,
        )
    if actions is None:
        actions = rng.uniform(-3.0, 3.0, size=(W, 2))
    states = np.zeros((W, 4), dtype=float)
    next_states = np.zeros((W, 4), dtype=float)
    cur = np.array(init_state, dtype=float, copy=True)
    for k in range(W):
        states[k] = cur
        clean_next = integrate_one_step(
            cur,
            actions[k],
            dt,
            true_phi,
            integrator=true_integrator,
            mechanism=true_mechanism,
            coeff=true_coeff,
        )
        noise = rng.normal(0.0, noise_std, size=4)
        obs_next = clean_next + noise
        next_states[k] = obs_next
        cur = clean_next
    cov = np.eye(4, dtype=float) * ((noise_std ** 2) * reported_cov_scale)
    return ObservationContext(
        context_id=context_id,
        world_instance_id=world_instance_id,
        t_start=t_start,
        object_keys=object_keys,
        dt=dt,
        integrator=model_integrator,
        states=states,
        next_states=next_states,
        actions=actions,
        innovation_cov=cov,
        requested_variables=requested_variables,
        competing_model_probs=competing_model_probs,
        in_slow_domain=in_slow_domain,
    )


def build_benchmark_suite(
    registration: CMFLRegistration,
    *,
    n_per_route: int = 8,
    seed: int = 20261028,
) -> tuple[list[ObservationContext], list[GroundTruthMeta]]:
    """Build a balanced 8-route benchmark suite (64 contexts by default) across all CMFL route categories.

    Returns (contexts, ground_truth_metas) strictly separated per §8.6.
    """
    rng = np.random.default_rng(seed)
    W = registration.W
    contexts: list[ObservationContext] = []
    metas: list[GroundTruthMeta] = []
    noise_std = 0.004

    # 1. ABSTAIN: action or state exceeds D_permit (or requests forbidden variable)
    for i in range(n_per_route):
        cid = f"ctx_abstain_{i:02d}"
        wid = f"world_abstain_{i:02d}"
        actions = rng.uniform(-2.0, 2.0, size=(W, 2))
        actions[0, 0] = registration.d_permit.action_limit * 1.35  # exceeds D_permit action bound
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
            actions=actions,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="D_permit_violation",
                true_route=RouteCode.ABSTAIN,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism="none",
                true_coeff=0.0,
                notes="Action exceeds D_permit bound; when D_permit is removed, falls through to SUFFICIENT",
            )
        )

    # 2. OUT_OF_DOMAIN: inside D_permit physical limit, but outside SLOW D_valid envelope
    for i in range(n_per_route):
        cid = f"ctx_ood_{i:02d}"
        wid = f"world_ood_{i:02d}"
        init_state = np.array([9.5, -9.0, 8.0, -7.5], dtype=float)
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
            init_state=init_state,
            in_slow_domain=False,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="OOD_envelope",
                true_route=RouteCode.OUT_OF_DOMAIN,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 3. NUMERICAL (N_family): true world integrated with RK4, learner uses coarse Euler at dt=0.08
    for i in range(n_per_route):
        cid = f"ctx_num_{i:02d}"
        wid = f"world_num_{i:02d}"
        init_state = np.array([2.5, -2.0, 4.0, 3.5], dtype=float)
        actions = 3.0 * np.sin(np.linspace(0.0, 3.0, W))[:, None] * np.array([[1.0, -0.8]])
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.08,
            true_integrator="rk4",
            model_integrator="euler",
            true_phi=DEFAULT_PHI,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=0.0005,
            reported_cov_scale=1.0,
            rng=rng,
            init_state=init_state,
            actions=actions,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="N_family",
                true_route=RouteCode.NUMERICAL,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 4a. COVARIANCE_INCONSISTENT: innovation covariance S_k inflated by 10x -> NIS in lower tail < chi2(alpha_s/2)
    for i in range(n_per_route):
        cid = f"ctx_cov_inconsistent_{i:02d}"
        wid = f"world_cov_{i:02d}"
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=12.0,  # inflated S_k
            rng=rng,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="Cov_inconsistent",
                true_route=RouteCode.COVARIANCE_INCONSISTENT,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 4b. SUFFICIENT: true_phi == prior_phi, well-calibrated S_k, RK4 dt=0.01
    for i in range(n_per_route):
        cid = f"ctx_sufficient_{i:02d}"
        wid = f"world_suff_{i:02d}"
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="Sufficient_baseline",
                true_route=RouteCode.SUFFICIENT,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 5. PARAMETRIC (P_family): true_phi shifted from prior_phi, well-excited trajectory so lambda_min(I_phi) >= tau_id
    for i in range(n_per_route):
        cid = f"ctx_parametric_{i:02d}"
        wid = f"world_param_{i:02d}"
        delta_phi = np.array(
            [
                rng.uniform(0.8, 1.8) * (1 if i % 2 == 0 else -1),
                rng.uniform(0.15, 0.35),
                rng.uniform(0.35, 0.75) * (-1 if i % 2 == 0 else 1),
            ],
            dtype=float,
        )
        true_phi = DEFAULT_PHI + delta_phi
        init_state = np.array([2.0, -1.8, 3.0, -2.5], dtype=float)
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.02,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=true_phi,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
            init_state=init_state,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="P_family",
                true_route=RouteCode.PARAMETRIC,
                true_phi=true_phi,
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 6. UNIDENTIFIABLE: residual discrepancy present, but trajectory stays near origin (x~0, y~0) or competing models
    # have high posterior entropy H(p(m|D)) > tau_H so lambda_min(I_phi) < tau_id or H > tau_H
    for i in range(n_per_route):
        cid = f"ctx_unidentifiable_{i:02d}"
        wid = f"world_unid_{i:02d}"
        true_phi = DEFAULT_PHI + np.array([1.5, 0.0, 0.0], dtype=float)
        # Keep x, y, vx, vy near 0 by opposing gravity with uy = g_true so k_spring and c_lin are unexcited
        init_state = np.array([0.0, 0.0, 0.0, 0.0], dtype=float)
        actions = np.zeros((W, 2), dtype=float)
        actions[:, 1] = true_phi[0]
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.01,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=true_phi,
            true_mechanism="none",
            true_coeff=0.0,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
            init_state=init_state,
            actions=actions,
            competing_model_probs=(0.50, 0.50),  # entropy ln(2) = 0.6931 > tau_H = 0.65
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family="Unidentifiable_probe",
                true_route=RouteCode.UNIDENTIFIABLE,
                true_phi=true_phi,
                true_mechanism="none",
                true_coeff=0.0,
            )
        )

    # 7. STRUCTURAL (S_family & altered_law_family): missing quadratic drag or 1/r altered-law gravity across >= K independent worlds
    for i in range(n_per_route):
        cid = f"ctx_structural_{i:02d}"
        wid = f"world_struct_{i:02d}"
        is_altered = i >= (n_per_route // 2)
        mech = "altered_inv_r_gravity" if is_altered else "quadratic_drag"
        coeff = 6.5 if is_altered else 0.45
        fam = "altered_law_family" if is_altered else "S_family"
        init_state = np.array([1.8, -1.6, 3.8, -3.2], dtype=float)
        ctx = simulate_window(
            context_id=cid,
            world_instance_id=wid,
            t_start=0,
            W=W,
            dt=0.02,
            true_integrator="rk4",
            model_integrator="rk4",
            true_phi=DEFAULT_PHI,
            true_mechanism=mech,
            true_coeff=coeff,
            noise_std=noise_std,
            reported_cov_scale=1.0,
            rng=rng,
            init_state=init_state,
        )
        contexts.append(ctx)
        metas.append(
            GroundTruthMeta(
                context_id=cid,
                world_instance_id=wid,
                family=fam,
                true_route=RouteCode.STRUCTURAL,
                true_phi=DEFAULT_PHI.copy(),
                true_mechanism=mech,
                true_coeff=coeff,
            )
        )

    return contexts, metas
