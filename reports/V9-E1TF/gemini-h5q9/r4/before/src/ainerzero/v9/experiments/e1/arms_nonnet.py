"""E1 Non-Neural Physics Arms (CPU / pure NumPy).

Covers:
- ① PriorArm: Biased physical prior rollout (DEFAULT_BIASED_PRIOR).
- ④ TrueParamArm: True parameters rollout (diagnostic upper bound only, diagnostic_only = True).
- ⑤ IdentifyArm: Online physical parameter identification (Levenberg-Marquardt with bounds & prior).
- ⑦ SymbolicResidualArm: Parameter identification + STLSQ discovery of residual acceleration terms.

Specification & Preregistration:
- reports/V9-P48/E1_IMPLEMENTATION_PLAN.md item E1-A1.
- PREREG_DRAFT r3 §2 (arm table).
- Zero MLX / zero training, strictly pure NumPy / CPU.
- Unified interface: predict(observed_prefix, static_env, n_future) -> ArmPrediction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.e1.jacobian import PARAM_NAMES, compute_prior_jacobian
from ainerzero.v9.experiments.e1.prior import (
    BOUNCE_VELOCITY_THRESHOLD,
    DEFAULT_BIASED_PRIOR,
    DEFAULT_SUBSTEPS,
    GRAVITY_ACCEL,
    SUBSTEP_DT,
    ActiveBody,
    PhysicalParameters,
    StaticEnvironment,
    apply_surface_impulse,
    integrate_quaternion,
    resolve_sphere_box_collision,
    rollout,
)
from ainerzero.v9.mechanism.discovery import BasisTermSpec, WeakFormSTLSQ, default_basis_library

# --- Module Constants ---
MAX_IDENTIFY_ITERATIONS: int = 25
CONVERGENCE_TOL: float = 1e-4
FISHER_MIN_EIGVAL_THRESHOLD: float = 1e-3
PROMOTE_MIN_GAIN: float = 0.10
DEFAULT_STLSQ_THRESHOLD: float = 0.05
DEFAULT_SPLIT_RATIO: float = 0.67

# E0 Hidden Parameter Bounds (AnimeWorldZero/python/animeworld/e0/hidden_params.py:18-24)
PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "friction": (0.05, 0.95),
    "restitution": (0.0, 0.90),
    "mass": (0.2, 5.0),
    "linear_damping": (0.0, 0.25),
    "angular_damping": (0.0, 0.25),
}

# Diagonal prior standard deviations (half of each parameter's allowable range)
PRIOR_PARAM_STDS: dict[str, float] = {
    p: 0.5 * (PARAM_BOUNDS[p][1] - PARAM_BOUNDS[p][0]) for p in PARAM_NAMES
}


# =========================================================================
# 0. Result Container & Basis Library
# =========================================================================

class ArmPrediction(dict):
    """Unified container for Arm predictions and identification/discovery metadata.

    Accessible as:
    - dict mapping body name to trajectory array of shape (n_future, 6) or (n_future, 13)
      containing [x, y, z, vx, vy, vz, ...].
    - properties:
      .positions: dict[str, np.ndarray] of shape (n_future, 3)
      .velocities: dict[str, np.ndarray] of shape (n_future, 3)
      .trajectories: dict[str, np.ndarray] of shape (n_future, 13)
      .full_trajectories: dict[str, np.ndarray] of shape (n_future + 1, 13)
      .identifiable: bool
      .promoted: bool | None
      .posterior_covariance: dict[str, np.ndarray] | None
      .identified_params: dict[str, PhysicalParameters] | None
    - dict keys also include 'identifiable', 'promoted', 'posterior_covariance', 'identified_params'.
    """

    def __init__(
        self,
        trajectories: dict[str, np.ndarray],
        *,
        full_trajectories: dict[str, np.ndarray] | None = None,
        identifiable: bool = True,
        promoted: bool | None = None,
        identified_params: dict[str, PhysicalParameters] | None = None,
        posterior_covariance: dict[str, np.ndarray] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self._trajectories = trajectories
        self._full_trajectories = full_trajectories or trajectories
        self.identifiable = bool(identifiable)
        self.promoted = promoted
        self.identified_params = identified_params or {}
        self.posterior_covariance = posterior_covariance or {}
        self.extra = extra or {}

        # Populate dict with object trajectories and metadata keys
        for k, v in self._trajectories.items():
            self[k] = v
        self["identifiable"] = self.identifiable
        if self.promoted is not None:
            self["promoted"] = self.promoted
        if self.identified_params:
            self["identified_params"] = self.identified_params
        if self.posterior_covariance:
            self["posterior_covariance"] = self.posterior_covariance

    @property
    def trajectories(self) -> dict[str, np.ndarray]:
        return self._trajectories

    @property
    def full_trajectories(self) -> dict[str, np.ndarray]:
        return self._full_trajectories

    @property
    def positions(self) -> dict[str, np.ndarray]:
        return {k: v[:, 0:3] for k, v in self._trajectories.items()}

    @property
    def velocities(self) -> dict[str, np.ndarray]:
        return {k: v[:, 3:6] for k, v in self._trajectories.items()}


def default_e1_basis_library() -> tuple[BasisTermSpec, ...]:
    """Candidate basis library for 3D body residual acceleration discovery.

    Includes:
    - quadratic_drag: a = -c * |v| * v (dissipative, sign-normalized)
    - linear_drag: a = -c * v (dissipative, sign-normalized)
    """
    def _eval_quad(s: np.ndarray) -> np.ndarray:
        v = s[..., 3:6] if s.shape[-1] >= 6 else s
        speed = np.linalg.norm(v, axis=-1, keepdims=True)
        return -speed * v

    def _eval_lin(s: np.ndarray) -> np.ndarray:
        v = s[..., 3:6] if s.shape[-1] >= 6 else s
        return -v

    return (
        BasisTermSpec(
            name="quadratic_drag",
            units="L/T^2",
            is_dissipative=True,
            eval_accel=_eval_quad,
        ),
        BasisTermSpec(
            name="linear_drag",
            units="L/T^2",
            is_dissipative=True,
            eval_accel=_eval_lin,
        ),
    )


# =========================================================================
# 1. Prefix Extraction & Rollout Wrapper with External Acceleration
# =========================================================================

def extract_prefix_records(
    observed_prefix: Any,
    radii: Mapping[str, float] | None = None,
    default_radius: float = 0.5,
) -> tuple[dict[str, np.ndarray], int]:
    """Extract clean per-body prefix trajectories, guaranteeing isolation from future frames.

    If an array contains NaNs (e.g. padding in future frames), slicing strictly truncates
    before the first NaN frame, ensuring no future data is read or leaked.
    """
    cleaned: dict[str, np.ndarray] = {}
    radii_map = dict(radii or {})

    if isinstance(observed_prefix, dict):
        for name, data in observed_prefix.items():
            if name in ("identifiable", "promoted", "identified_params", "posterior_covariance"):
                continue
            if isinstance(data, np.ndarray):
                arr = np.asarray(data, dtype=np.float64)
            elif isinstance(data, dict):
                # Extract position, velocity, orientation, angular_velocity
                pos = np.asarray(data["position"], dtype=np.float64)
                vel = np.asarray(data["velocity"], dtype=np.float64)
                t_len = pos.shape[0]
                ori = np.asarray(
                    data.get("orientation", np.tile([1.0, 0.0, 0.0, 0.0], (t_len, 1))),
                    dtype=np.float64,
                )
                ang = np.asarray(
                    data.get("angular_velocity", np.tile([0.0, 0.0, 0.0], (t_len, 1))),
                    dtype=np.float64,
                )
                arr = np.concatenate([pos, vel, ori, ang], axis=-1)
            else:
                continue

            # Detect first NaN frame to ensure prefix isolation
            nan_mask = np.isnan(arr).any(axis=tuple(range(1, arr.ndim)))
            if np.any(nan_mask):
                first_nan = int(np.argmax(nan_mask))
                arr = arr[:first_nan]

            cleaned[str(name)] = arr

    if not cleaned:
        raise ValueError("observed_prefix contained no valid object trajectories")

    prefix_len = min(len(arr) for arr in cleaned.values())
    trimmed = {k: v[:prefix_len] for k, v in cleaned.items()}
    return trimmed, prefix_len


def make_active_body_from_state(
    name: str,
    state_13: np.ndarray,
    params: PhysicalParameters,
    radius: float = 0.5,
) -> ActiveBody:
    """Create an ActiveBody from a 13-dim state row [x,y,z, vx,vy,vz, qw,qx,qy,qz, wx,wy,wz]."""
    pos = np.array(state_13[0:3], dtype=np.float64, copy=True)
    vel = np.array(state_13[3:6], dtype=np.float64, copy=True)
    if len(state_13) >= 10:
        ori = np.array(state_13[6:10], dtype=np.float64, copy=True)
    else:
        ori = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
    if len(state_13) >= 13:
        ang = np.array(state_13[10:13], dtype=np.float64, copy=True)
    else:
        ang = np.zeros(3, dtype=np.float64)

    return ActiveBody(
        name=name,
        radius=float(radius),
        params=params.copy(),
        position=pos,
        velocity=vel,
        orientation=ori,
        angular_velocity=ang,
    )


# Single source of truth: rollout with optional extra_accel_fn is in prior.py
rollout_with_accel = rollout


# =========================================================================
# 2. Arm ①: PriorArm
# =========================================================================

class PriorArm:
    """Arm ①: Biased Physical Prior Rollout (rollout with DEFAULT_BIASED_PRIOR).

    Starting strictly from the last frame of the observed prefix, rolls out future frames
    using the registered biased prior parameters without parameter identification.
    """

    def __init__(
        self,
        radii: Mapping[str, float] | None = None,
        default_radius: float = 0.5,
    ) -> None:
        self.radii = dict(radii or {})
        self.default_radius = float(default_radius)

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment,
        n_future: int,
    ) -> ArmPrediction:
        """Predict future n_future frames positions and velocities using biased prior."""
        clean_prefix, prefix_len = extract_prefix_records(
            observed_prefix, self.radii, self.default_radius
        )
        bodies = [
            make_active_body_from_state(
                name=name,
                state_13=traj[prefix_len - 1],
                params=DEFAULT_BIASED_PRIOR.copy(),
                radius=self.radii.get(name, self.default_radius),
            )
            for name, traj in clean_prefix.items()
        ]

        full_rollout = rollout(bodies, static_env, num_frames=n_future)
        future_trajectories = {name: arr[1:n_future + 1] for name, arr in full_rollout.items()}

        return ArmPrediction(
            trajectories=future_trajectories,
            full_trajectories=full_rollout,
            identifiable=True,
            identified_params={b.name: DEFAULT_BIASED_PRIOR.copy() for b in bodies},
        )


# =========================================================================
# 3. Arm ④: TrueParamArm
# =========================================================================

class TrueParamArm:
    """Arm ④: True Parameters Rollout (Diagnostic Upper Bound Only).

    只作上界诊断，只允许评测侧构造。
    Uses the exact true physical parameters φ* to establish the empirical upper bound
    under the prior dynamics structure.
    """

    diagnostic_only: bool = True

    def __init__(
        self,
        true_params: PhysicalParameters | Mapping[str, PhysicalParameters] | Sequence[float],
        radii: Mapping[str, float] | None = None,
        default_radius: float = 0.5,
    ) -> None:
        self.radii = dict(radii or {})
        self.default_radius = float(default_radius)
        if isinstance(true_params, PhysicalParameters):
            self.param_map = {"default": true_params.copy()}
        elif isinstance(true_params, (list, tuple, np.ndarray)):
            self.param_map = {"default": PhysicalParameters.from_array(true_params)}
        elif isinstance(true_params, Mapping):
            self.param_map = {k: v.copy() for k, v in true_params.items()}
        else:
            raise TypeError(f"Unsupported true_params type: {type(true_params)}")

    def _get_params(self, name: str) -> PhysicalParameters:
        if name in self.param_map:
            return self.param_map[name].copy()
        if "default" in self.param_map:
            return self.param_map["default"].copy()
        first = next(iter(self.param_map.values()))
        return first.copy()

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment,
        n_future: int,
    ) -> ArmPrediction:
        """Predict future n_future frames positions and velocities using ground-truth φ*."""
        clean_prefix, prefix_len = extract_prefix_records(
            observed_prefix, self.radii, self.default_radius
        )
        bodies = [
            make_active_body_from_state(
                name=name,
                state_13=traj[prefix_len - 1],
                params=self._get_params(name),
                radius=self.radii.get(name, self.default_radius),
            )
            for name, traj in clean_prefix.items()
        ]

        full_rollout = rollout(bodies, static_env, num_frames=n_future)
        future_trajectories = {name: arr[1:n_future + 1] for name, arr in full_rollout.items()}

        return ArmPrediction(
            trajectories=future_trajectories,
            full_trajectories=full_rollout,
            identifiable=True,
            identified_params={b.name: self._get_params(b.name) for b in bodies},
        )


# =========================================================================
# 4. Arm ⑤: IdentifyArm (Online Parameter Identification)
# =========================================================================

class IdentifyArm:
    """Arm ⑤: Online Physical Parameter Identification on Observed Prefix.

    Optimizes physical parameters φ on the observed prefix via bounded Levenberg-Marquardt.
    Features:
    - Central difference Jacobian from jacobian.py.
    - Regularization with Gaussian prior N(φ̂₀, Σ₀) where std = range / 2.
    - Box bounds strictly enforced per E0 parameter definitions.
    - Fisher information condition check: falls back to φ̂₀ with identifiable=False
      if min eigenvalue of Fisher information is below FISHER_MIN_EIGVAL_THRESHOLD.
    - Returns posterior covariance approximation (J^T W J + Σ₀⁻¹)⁻¹.
    """

    def __init__(
        self,
        target_params: Sequence[str] = ("friction", "restitution"),
        radii: Mapping[str, float] | None = None,
        default_radius: float = 0.5,
        max_iterations: int = MAX_IDENTIFY_ITERATIONS,
        tol: float = CONVERGENCE_TOL,
        fisher_min_eigval_threshold: float = FISHER_MIN_EIGVAL_THRESHOLD,
        w_pos: float = 1e4,
        w_vel: float = 400.0,
    ) -> None:
        self.target_params = tuple(target_params)
        self.radii = dict(radii or {})
        self.default_radius = float(default_radius)
        self.max_iterations = int(max_iterations)
        self.tol = float(tol)
        self.fisher_threshold = float(fisher_min_eigval_threshold)
        self.w_pos = float(w_pos)
        self.w_vel = float(w_vel)

        # Index mapping
        self.param_indices = [PARAM_NAMES.index(p) for p in self.target_params]

        # Prior mean and covariance
        phi0_arr = DEFAULT_BIASED_PRIOR.to_array()
        self.phi0 = np.array([phi0_arr[i] for i in self.param_indices], dtype=np.float64)
        stds = np.array([PRIOR_PARAM_STDS[p] for p in self.target_params], dtype=np.float64)
        self.sigma0_diag = stds ** 2
        self.inv_sigma0 = np.diag(1.0 / self.sigma0_diag)

        # Box bounds
        self.lower_bounds = np.array([PARAM_BOUNDS[p][0] for p in self.target_params], dtype=np.float64)
        self.upper_bounds = np.array([PARAM_BOUNDS[p][1] for p in self.target_params], dtype=np.float64)

    def identify_body(
        self,
        body_name: str,
        prefix_traj: np.ndarray,
        static_env: StaticEnvironment,
        radius: float,
    ) -> tuple[PhysicalParameters, np.ndarray, bool]:
        """Identify physical parameters for a single body on its observed prefix."""
        t_obs = prefix_traj.shape[0]

        # Check for insufficient information / short prefix
        if t_obs < 4:
            return DEFAULT_BIASED_PRIOR.copy(), np.diag(self.sigma0_diag), False

        obs_pos = prefix_traj[:, 0:3]
        obs_vel = prefix_traj[:, 3:6]

        # Initial body state at t=0
        body_init = make_active_body_from_state(
            name=body_name,
            state_13=prefix_traj[0],
            params=DEFAULT_BIASED_PRIOR.copy(),
            radius=radius,
        )

        num_frames = t_obs - 1
        phi = self.phi0.copy()

        # Check initial Fisher information
        jac_dict = compute_prior_jacobian(
            [body_init], static_env, num_frames=num_frames, param_indices=self.param_indices
        )

        j_cols = []
        for p_name in self.target_params:
            j_p = jac_dict[p_name]  # (t_obs, 13)
            jp_pos = j_p[1:, 0:3].flatten()
            jp_vel = j_p[1:, 3:6].flatten()
            j_col = np.concatenate([np.sqrt(self.w_pos) * jp_pos, np.sqrt(self.w_vel) * jp_vel])
            j_cols.append(j_col)

        J_init = np.stack(j_cols, axis=-1)
        F_init = J_init.T @ J_init
        min_eig_init = float(np.min(np.linalg.eigvalsh(F_init)))

        if min_eig_init < self.fisher_threshold:
            # Information deficient: fall back to prior mean
            post_cov = np.linalg.inv(F_init + self.inv_sigma0)
            return DEFAULT_BIASED_PRIOR.copy(), post_cov, False

        # Levenberg-Marquardt optimization
        lam = 1e-2
        current_params = DEFAULT_BIASED_PRIOR.copy()
        post_cov = np.linalg.inv(F_init + self.inv_sigma0)

        for it in range(self.max_iterations):
            # Rollout with current phi
            param_arr = current_params.to_array()
            for local_i, global_i in enumerate(self.param_indices):
                param_arr[global_i] = phi[local_i]
            current_params = PhysicalParameters.from_array(param_arr)

            b_eval = make_active_body_from_state(
                name=body_name, state_13=prefix_traj[0], params=current_params, radius=radius
            )
            sim_traj = rollout([b_eval], static_env, num_frames=num_frames)[body_name]

            r_pos = (sim_traj[1:, 0:3] - obs_pos[1:]).flatten()
            r_vel = (sim_traj[1:, 3:6] - obs_vel[1:]).flatten()

            cost_data = 0.5 * (self.w_pos * np.sum(r_pos ** 2) + self.w_vel * np.sum(r_vel ** 2))
            diff_phi = phi - self.phi0
            cost_prior = 0.5 * float(diff_phi @ self.inv_sigma0 @ diff_phi)
            cost = cost_data + cost_prior

            # Compute Jacobian
            jac_dict = compute_prior_jacobian(
                [b_eval], static_env, num_frames=num_frames, param_indices=self.param_indices
            )
            j_cols = []
            for p_name in self.target_params:
                j_p = jac_dict[p_name]
                jp_pos = j_p[1:, 0:3].flatten()
                jp_vel = j_p[1:, 3:6].flatten()
                j_col = np.concatenate([np.sqrt(self.w_pos) * jp_pos, np.sqrt(self.w_vel) * jp_vel])
                j_cols.append(j_col)

            J = np.stack(j_cols, axis=-1)
            r_w = np.concatenate([np.sqrt(self.w_pos) * r_pos, np.sqrt(self.w_vel) * r_vel])

            F = J.T @ J
            H = F + self.inv_sigma0
            g = J.T @ r_w + self.inv_sigma0 @ diff_phi

            # LM step with Levenberg damping
            diag_H = np.maximum(np.diag(np.diag(H)), 1e-6 * np.eye(len(phi)))
            try:
                step = -np.linalg.solve(H + lam * diag_H, g)
            except np.linalg.LinAlgError:
                break

            phi_cand = phi + step
            phi_cand = np.clip(phi_cand, self.lower_bounds, self.upper_bounds)

            # Evaluate candidate cost
            cand_arr = param_arr.copy()
            for local_i, global_i in enumerate(self.param_indices):
                cand_arr[global_i] = phi_cand[local_i]
            cand_params = PhysicalParameters.from_array(cand_arr)

            b_cand = make_active_body_from_state(
                name=body_name, state_13=prefix_traj[0], params=cand_params, radius=radius
            )
            cand_traj = rollout([b_cand], static_env, num_frames=num_frames)[body_name]
            r_cand_pos = (cand_traj[1:, 0:3] - obs_pos[1:]).flatten()
            r_cand_vel = (cand_traj[1:, 3:6] - obs_vel[1:]).flatten()
            cand_diff_phi = phi_cand - self.phi0
            cand_cost = 0.5 * (
                self.w_pos * np.sum(r_cand_pos ** 2) + self.w_vel * np.sum(r_cand_vel ** 2)
            ) + 0.5 * float(cand_diff_phi @ self.inv_sigma0 @ cand_diff_phi)

            if cand_cost < cost:
                phi = phi_cand
                lam = max(lam / 3.0, 1e-7)
                post_cov = np.linalg.inv(F + self.inv_sigma0)
                if np.linalg.norm(step) < self.tol or abs(cost - cand_cost) < self.tol:
                    break
            else:
                lam = min(lam * 3.0, 1e5)

        # Build final PhysicalParameters
        final_arr = DEFAULT_BIASED_PRIOR.to_array()
        for local_i, global_i in enumerate(self.param_indices):
            final_arr[global_i] = phi[local_i]
        final_params = PhysicalParameters.from_array(final_arr)

        return final_params, post_cov, True

    def identify(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment,
    ) -> tuple[dict[str, PhysicalParameters], dict[str, np.ndarray], bool]:
        """Run identification across all bodies in the observed prefix."""
        clean_prefix, _ = extract_prefix_records(
            observed_prefix, self.radii, self.default_radius
        )
        params_out: dict[str, PhysicalParameters] = {}
        covs_out: dict[str, np.ndarray] = {}
        all_identifiable = True

        for name, traj in clean_prefix.items():
            rad = self.radii.get(name, self.default_radius)
            p_ident, cov, ident_ok = self.identify_body(name, traj, static_env, rad)
            params_out[name] = p_ident
            covs_out[name] = cov
            if not ident_ok:
                all_identifiable = False

        return params_out, covs_out, all_identifiable

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment,
        n_future: int,
    ) -> ArmPrediction:
        """Identify parameters on prefix, then roll out future frames."""
        clean_prefix, prefix_len = extract_prefix_records(
            observed_prefix, self.radii, self.default_radius
        )
        params_out, covs_out, all_identifiable = self.identify(clean_prefix, static_env)

        bodies = [
            make_active_body_from_state(
                name=name,
                state_13=traj[prefix_len - 1],
                params=params_out[name],
                radius=self.radii.get(name, self.default_radius),
            )
            for name, traj in clean_prefix.items()
        ]

        full_rollout = rollout(bodies, static_env, num_frames=n_future)
        future_trajectories = {name: arr[1:n_future + 1] for name, arr in full_rollout.items()}

        return ArmPrediction(
            trajectories=future_trajectories,
            full_trajectories=full_rollout,
            identifiable=all_identifiable,
            identified_params=params_out,
            posterior_covariance=covs_out,
        )


# =========================================================================
# 5. Arm ⑦: SymbolicResidualArm (STLSQ Residual Acceleration)
# =========================================================================

class SymbolicResidualArm:
    """Arm ⑦: STLSQ Symbolic Residual Acceleration on Prefix + Rollout.

    Pipeline:
    1. Runs Arm ⑤ to identify background physical parameters φ̂.
    2. Computes velocity-differenced acceleration residuals on the prefix:
       a_res[t] = (v_obs[t+1] - v_obs[t]) / dt - a_prior(s_obs[t]; φ̂).
    3. Fits candidate symbolic acceleration terms using STLSQ (from mechanism.discovery).
    4. Evaluates fitted terms on the validation segment of the prefix.
       If validation error reduction >= PROMOTE_MIN_GAIN, promotes the symbolic terms
       (promoted = True) and attaches them during rollout.
       Otherwise falls back to Arm ⑤ behavior (promoted = False).
    """

    def __init__(
        self,
        target_params: Sequence[str] = ("friction", "restitution"),
        basis_library: Sequence[BasisTermSpec] | None = None,
        stlsq_threshold: float = DEFAULT_STLSQ_THRESHOLD,
        promote_min_gain: float = PROMOTE_MIN_GAIN,
        split_ratio: float = DEFAULT_SPLIT_RATIO,
        radii: Mapping[str, float] | None = None,
        default_radius: float = 0.5,
    ) -> None:
        self.arm5 = IdentifyArm(
            target_params=target_params,
            radii=radii,
            default_radius=default_radius,
        )
        self.library = tuple(basis_library) if basis_library is not None else default_e1_basis_library()
        self.stlsq_threshold = float(stlsq_threshold)
        self.promote_min_gain = float(promote_min_gain)
        self.split_ratio = float(split_ratio)
        self.radii = dict(radii or {})
        self.default_radius = float(default_radius)

    def _fit_stlsq(
        self,
        velocities: np.ndarray,  # (T, 3)
        residual_accels: np.ndarray,  # (T, 3)
    ) -> tuple[tuple[str, ...], np.ndarray]:
        """Perform sequential thresholded least squares with sign positivity constraints."""
        m = len(self.library)
        t_len = velocities.shape[0]
        if t_len == 0 or m == 0:
            return (), np.zeros(0, dtype=np.float64)

        # Evaluate basis acceleration vectors
        # Each basis term evaluates state (or velocity) -> accel (T, 3)
        W_list = []
        for term in self.library:
            acc = term.eval_accel(velocities)  # (T, 3)
            W_list.append(acc.flatten())

        W = np.stack(W_list, axis=-1)  # (T*3, M)
        y = residual_accels.flatten()  # (T*3,)

        active_mask = np.ones(m, dtype=bool)
        coeffs = np.zeros(m, dtype=np.float64)
        col_norms = np.maximum(np.linalg.norm(W, axis=0), 1e-12)
        y_norm = max(float(np.linalg.norm(y)), 1e-12)

        # STLSQ loop
        for _ in range(m + 1):
            if not np.any(active_mask):
                break
            sub_w = W[:, active_mask]
            gram = sub_w.T @ sub_w + 1e-8 * np.eye(sub_w.shape[1])
            sub_c = np.linalg.solve(gram, sub_w.T @ y)

            new_mask = active_mask.copy()
            active_indices = np.where(active_mask)[0]
            for local_j, global_j in enumerate(active_indices):
                norm_contrib = float(sub_c[local_j] * col_norms[global_j] / y_norm)
                # Physical dissipative drag mechanisms have positive coefficient in sign-normalized basis
                if sub_c[local_j] <= 0.0 or norm_contrib < self.stlsq_threshold:
                    new_mask[global_j] = False

            coeffs[:] = 0.0
            if np.any(new_mask):
                sub_w2 = W[:, new_mask]
                gram2 = sub_w2.T @ sub_w2 + 1e-8 * np.eye(sub_w2.shape[1])
                coeffs[new_mask] = np.linalg.solve(gram2, sub_w2.T @ y)

            if np.array_equal(new_mask, active_mask):
                break
            active_mask = new_mask

        active_terms = tuple(self.library[i].name for i in np.where(active_mask)[0])
        active_coeffs = coeffs[active_mask]
        return active_terms, active_coeffs

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment,
        n_future: int,
    ) -> ArmPrediction:
        """Run Arm ⑤, fit STLSQ residual on split prefix, validate promotion, and rollout."""
        clean_prefix, prefix_len = extract_prefix_records(
            observed_prefix, self.radii, self.default_radius
        )

        # 1. Background identification via Arm ⑤
        identified_params, covs, all_identifiable = self.arm5.identify(clean_prefix, static_env)

        # Temporal split on prefix
        t_split = max(2, int(math.floor(prefix_len * self.split_ratio)))
        dt_frame = 1.0 / 60.0

        # 2. Extract train segment residuals across all active bodies (frames 0 to t_split)
        t_train_frames = t_split
        vel_list = []
        res_list = []

        for name, traj in clean_prefix.items():
            rad = self.radii.get(name, self.default_radius)
            p_hat = identified_params[name]
            train_obs = traj[:t_split + 1]
            obs_vel = train_obs[:, 3:6]
            a_obs = (obs_vel[1:] - obs_vel[:-1]) / dt_frame

            a_prior = np.zeros_like(a_obs)
            for t in range(t_train_frames):
                b_step = make_active_body_from_state(
                    name=name, state_13=train_obs[t], params=p_hat, radius=rad
                )
                sim_1 = rollout([b_step], static_env, num_frames=1)[name]
                v_sim_1 = sim_1[1, 3:6]
                a_prior[t] = (v_sim_1 - train_obs[t, 3:6]) / dt_frame

            a_res = a_obs - a_prior
            vel_mid = 0.5 * (obs_vel[1:] + obs_vel[:-1])
            vel_list.append(vel_mid)
            res_list.append(a_res)

        all_vel = np.concatenate(vel_list, axis=0)
        all_res = np.concatenate(res_list, axis=0)

        # 3. Fit STLSQ on train segment across all active bodies
        active_terms, active_coeffs = self._fit_stlsq(all_vel, all_res)

        # Construct candidate extra acceleration function
        def extra_accel_cb(b: ActiveBody) -> np.ndarray:
            acc = np.zeros(3, dtype=np.float64)
            for term_name, coeff in zip(active_terms, active_coeffs):
                for term in self.library:
                    if term.name == term_name:
                        acc = acc + float(coeff) * term.eval_accel(b.velocity)
            return acc

        # 4. Validation segment testing (frames t_split to prefix_len - 1) across all active bodies
        val_len = prefix_len - 1 - t_split
        promoted = False
        gain = 0.0

        if active_terms and val_len >= 3:
            # Multi-body simulation on validation segment under Arm ⑤
            b_val_5 = [
                make_active_body_from_state(
                    name=name,
                    state_13=clean_prefix[name][t_split],
                    params=identified_params[name],
                    radius=self.radii.get(name, self.default_radius),
                )
                for name in clean_prefix.keys()
            ]
            val_sim_5 = rollout(b_val_5, static_env, num_frames=val_len)

            # Multi-body simulation on validation segment under candidate Arm ⑦
            b_val_7 = [
                make_active_body_from_state(
                    name=name,
                    state_13=clean_prefix[name][t_split],
                    params=identified_params[name],
                    radius=self.radii.get(name, self.default_radius),
                )
                for name in clean_prefix.keys()
            ]
            val_sim_7 = rollout(b_val_7, static_env, num_frames=val_len, extra_accel_fn=extra_accel_cb)

            err_5_list = []
            err_7_list = []
            for name, traj in clean_prefix.items():
                true_val_pos = traj[t_split + 1:, 0:3]
                err_5_list.append(float(np.mean(np.linalg.norm(val_sim_5[name][1:, 0:3] - true_val_pos, axis=-1))))
                err_7_list.append(float(np.mean(np.linalg.norm(val_sim_7[name][1:, 0:3] - true_val_pos, axis=-1))))

            err_5 = float(np.mean(err_5_list))
            err_7 = float(np.mean(err_7_list))

            denom = max(err_5, 1e-9)
            gain = (err_5 - err_7) / denom
            if gain >= self.promote_min_gain:
                promoted = True

        # When val_len < 3 or active_terms is empty, promoted remains False (no sample-in fallback).

        # 5. Future rollout from the last frame of the observed prefix
        bodies = [
            make_active_body_from_state(
                name=name,
                state_13=clean_prefix[name][prefix_len - 1],
                params=identified_params[name],
                radius=self.radii.get(name, self.default_radius),
            )
            for name in clean_prefix.keys()
        ]

        if promoted:
            future_fn = extra_accel_cb
        else:
            future_fn = None

        full_rollout = rollout(
            bodies, static_env, num_frames=n_future, extra_accel_fn=future_fn
        )
        future_trajectories = {name: arr[1:n_future + 1] for name, arr in full_rollout.items()}

        extra_meta = {
            "active_terms": active_terms,
            "coefficients": active_coeffs,
            "promotion_gain": gain,
        }

        return ArmPrediction(
            trajectories=future_trajectories,
            full_trajectories=full_rollout,
            identifiable=all_identifiable,
            promoted=promoted,
            identified_params=identified_params,
            posterior_covariance=covs,
            extra=extra_meta,
        )
