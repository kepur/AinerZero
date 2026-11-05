"""Central difference Jacobian of the biased physical prior (CPU / NumPy).

Specification (reports/V9-P48/E1_IMPLEMENTATION_PLAN.md item 3):
- Central difference: dF_prior / d_phi.
- Each parameter is perturbed with +delta and -delta with relative step 1e-3.
- Parameter order: (friction, restitution, mass, linear_damping, angular_damping).
- SVD truncation at relative 1e-6 * sigma_max for orthogonal projection in Arm 6.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .prior import (
    DEFAULT_SUBSTEPS,
    GRAVITY_ACCEL,
    SUBSTEP_DT,
    ActiveBody,
    PhysicalParameters,
    StaticEnvironment,
    rollout,
)

PARAM_NAMES: tuple[str, ...] = (
    "friction",
    "restitution",
    "mass",
    "linear_damping",
    "angular_damping",
)
DEFAULT_REL_STEP: float = 1e-3
DEFAULT_SVD_REL_TOL: float = 1e-6


def compute_prior_jacobian(
    bodies: Sequence[ActiveBody],
    env: StaticEnvironment,
    num_frames: int,
    *,
    body_index: int = 0,
    param_indices: Sequence[int] = (0, 1, 2, 3, 4),
    rel_step: float = DEFAULT_REL_STEP,
    min_step: float = 1e-6,
    substeps: int = DEFAULT_SUBSTEPS,
    dt: float = SUBSTEP_DT,
    g: float = GRAVITY_ACCEL,
) -> dict[str, np.ndarray]:
    """Compute central difference Jacobian of rollout trajectories w.r.t physical parameters.

    Returns:
        dict mapping each parameter name to an array of shape (num_frames + 1, 13)
        representing d(state_t) / d(param), where state_t is
        [x, y, z, vx, vy, vz, qw, qx, qy, qz, wx, wy, wz].
    """
    target_body = bodies[body_index]
    orig_params = target_body.params.copy()
    param_arr = orig_params.to_array()

    jacobian: dict[str, np.ndarray] = {}

    for p_idx in param_indices:
        p_name = PARAM_NAMES[p_idx]
        val = param_arr[p_idx]
        step = max(abs(val) * rel_step, min_step)

        # Perturbation +
        params_plus = orig_params.copy()
        arr_plus = param_arr.copy()
        arr_plus[p_idx] = val + step
        params_plus = PhysicalParameters.from_array(arr_plus)

        bodies_plus = [b.copy() for b in bodies]
        bodies_plus[body_index].params = params_plus
        traj_plus = rollout(bodies_plus, env, num_frames=num_frames, substeps=substeps, dt=dt, g=g)

        # Perturbation -
        params_minus = orig_params.copy()
        arr_minus = param_arr.copy()
        arr_minus[p_idx] = max(val - step, 0.0)
        actual_step = (val + step) - arr_minus[p_idx]
        params_minus = PhysicalParameters.from_array(arr_minus)

        bodies_minus = [b.copy() for b in bodies]
        bodies_minus[body_index].params = params_minus
        traj_minus = rollout(bodies_minus, env, num_frames=num_frames, substeps=substeps, dt=dt, g=g)

        # Central difference
        state_plus = traj_plus[target_body.name]  # (T+1, 6)
        state_minus = traj_minus[target_body.name]  # (T+1, 6)

        d_state = (state_plus - state_minus) / actual_step
        jacobian[p_name] = d_state

    return jacobian


def compute_orthogonal_projection_basis(
    jacobian_matrix: np.ndarray,
    *,
    rel_svd_tol: float = DEFAULT_SVD_REL_TOL,
) -> tuple[np.ndarray, np.ndarray]:
    """Compute orthogonal projection basis from prior Jacobian via truncated SVD.

    Parameters:
        jacobian_matrix: 2D array of shape (M, P) where M is trajectory observation dim
            and P is parameter count.
        rel_svd_tol: singular value cutoff relative to sigma_max (default 1e-6).

    Returns:
        tuple (U_basis, singular_values):
            U_basis: orthogonal columns spanning the range of the prior Jacobian.
            singular_values: non-zero singular values.
    """
    if jacobian_matrix.ndim != 2:
        raise ValueError(f"jacobian_matrix must be 2D, got shape {jacobian_matrix.shape}")

    u, s, vh = np.linalg.svd(jacobian_matrix, full_matrices=False)
    if len(s) == 0:
        return np.zeros((jacobian_matrix.shape[0], 0)), np.array([])

    s_max = float(np.max(s))
    threshold = s_max * rel_svd_tol
    keep = s > threshold

    u_basis = u[:, keep]
    s_keep = s[keep]

    return u_basis, s_keep
