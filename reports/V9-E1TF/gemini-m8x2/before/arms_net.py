"""E1 Network Arms: Arm 2 (PureNet), Arm 3 (PriorResidual), and Arm 6 (IdentifyResidual).

Specification & Pre-registration references:
- reports/V9-P48/E1_IMPLEMENTATION_PLAN.md (E1-A2)
- reports/V9-P48/PREREG_DRAFT.md §2 (Arms table)
- reports/frontier-integration-20261027/DESIGN_CORE.md §2 item 7 (Orthogonal projection)
- reports/V9-P69 (Task card)

Features:
1. Arm 2 (PureNetArm): MLX MLP predicting state increment (pos, vel) autoregressively
   from the recent K frames of state history.
2. Arm 3 (PriorResidualArm): Advances state via prior.DEFAULT_BIASED_PRIOR, then adds
   state correction predicted by MLX residual network.
3. Arm 6 (IdentifyResidualArm): Identifies phi from prefix (or uses injected identifier),
   advances state via prior, projects residual onto the orthogonal complement of the
   column space of dF_prior / d_phi (using jacobian.compute_orthogonal_projection_basis
   with SVD relative tolerance 1e-6 * sigma_max), and returns count of truncated directions.
   Also supports project=False as a diagnostic variant.
4. Identical parameter counts across Arms 2, 3, and 6.
5. Deterministic bitwise initialization under identical seeds, with parameter SHA256.
6. Operates strictly on MLX CPU device without unapproved external training.
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import mlx.utils
import numpy as np

from .jacobian import (
    DEFAULT_SVD_REL_TOL,
    PARAM_NAMES,
    compute_orthogonal_projection_basis,
    compute_prior_jacobian,
)
from .prior import (
    DEFAULT_BIASED_PRIOR,
    ActiveBody,
    PhysicalParameters,
    StaticEnvironment,
    simulate_frame,
)

# Ensure CPU default device for MLX execution
mx.set_default_device(mx.cpu)

# --- Module Constants ---
HISTORY_K: int = 4
STATE_DIM_PER_BODY: int = 6  # [x, y, z, vx, vy, vz]
DEFAULT_NUM_BODIES: int = 1
DEFAULT_INPUT_DIM: int = HISTORY_K * STATE_DIM_PER_BODY * DEFAULT_NUM_BODIES  # 24
DEFAULT_HIDDEN_DIM: int = 64
DEFAULT_NUM_LAYERS: int = 2
DEFAULT_OUTPUT_DIM: int = STATE_DIM_PER_BODY * DEFAULT_NUM_BODIES  # 6
DEFAULT_SEED: int = 42

# Layer 1: 24 * 64 + 64 = 1600
# Layer 2: 64 * 64 + 64 = 4160
# Layer 3: 64 * 6 + 6 = 390
# Total: 1600 + 4160 + 390 = 6150
REGISTERED_PARAMETER_COUNT: int = 6150

IdentificationFn = Callable[[Any, StaticEnvironment], PhysicalParameters]


# =========================================================================
# Utilities & Projections
# =========================================================================

def count_parameters(model_or_arm: Any) -> int:
    """Count total trainable parameters in an MLX module or NetArm."""
    if hasattr(model_or_arm, "net"):
        net = model_or_arm.net
    else:
        net = model_or_arm
    leaves = mlx.utils.tree_flatten(net.parameters())
    return sum(int(arr.size) for _, arr in leaves)


def compute_parameter_sha256(model_or_arm: Any) -> str:
    """Compute deterministic SHA256 digest over model weights."""
    if hasattr(model_or_arm, "net"):
        net = model_or_arm.net
    else:
        net = model_or_arm
    leaves = mlx.utils.tree_flatten(net.parameters())
    h = hashlib.sha256()
    for path, arr in sorted(leaves, key=lambda x: x[0]):
        h.update(path.encode("utf-8"))
        h.update(bytes(arr))
    return h.hexdigest()


def project_onto_orthogonal_complement(
    residual: np.ndarray,
    jacobian_matrix: np.ndarray,
    *,
    rel_svd_tol: float = DEFAULT_SVD_REL_TOL,
) -> tuple[np.ndarray, int]:
    """Project residual vector onto the orthogonal complement of the column space of Jacobian.

    Parameters:
        residual: 1D array of shape (M,) or 2D array of shape (B, M).
        jacobian_matrix: 2D array of shape (M, P).
        rel_svd_tol: SVD singular value cutoff relative to sigma_max.

    Returns:
        tuple (residual_perp, num_truncated):
            residual_perp: projected residual orthogonal to the Jacobian basis.
            num_truncated: number of singular value directions truncated due to cutoff.
    """
    if jacobian_matrix.ndim != 2:
        raise ValueError(f"jacobian_matrix must be 2D, got shape {jacobian_matrix.shape}")

    u_basis, s_keep = compute_orthogonal_projection_basis(
        jacobian_matrix, rel_svd_tol=rel_svd_tol
    )

    num_params = jacobian_matrix.shape[1]
    num_kept = u_basis.shape[1]
    num_truncated = int(num_params - num_kept)

    if num_kept == 0:
        # All directions truncated; residual remains unchanged
        return np.array(residual, copy=True), num_truncated

    # Orthogonal projection: r_perp = r - U_basis @ (U_basis.T @ r)
    is_1d = residual.ndim == 1
    r_arr = residual if not is_1d else residual[:, None]

    proj_coeffs = u_basis.T @ r_arr  # (num_kept, B)
    parallel_component = u_basis @ proj_coeffs  # (M, B)
    perp_arr = r_arr - parallel_component

    if is_1d:
        return perp_arr.squeeze(-1), num_truncated
    return perp_arr, num_truncated


# =========================================================================
# Neural Network Backbone (MLX MLP)
# =========================================================================

class DynamicsMLP(nn.Module):
    """3-layer MLP predicting state deltas or residual corrections."""

    def __init__(
        self,
        in_dim: int = DEFAULT_INPUT_DIM,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        out_dim: int = DEFAULT_OUTPUT_DIM,
    ) -> None:
        super().__init__()
        self.in_dim = in_dim
        self.hidden_dim = hidden_dim
        self.out_dim = out_dim
        self.fc1 = nn.Linear(in_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.fc3 = nn.Linear(hidden_dim, out_dim)

    def __call__(self, x: mx.array) -> mx.array:
        x = nn.relu(self.fc1(x))
        x = nn.relu(self.fc2(x))
        return self.fc3(x)


# =========================================================================
# Base Network Arm
# =========================================================================

class BaseNetArm:
    """Base class for MLX dynamics and residual network arms."""

    def __init__(
        self,
        *,
        seed: int = DEFAULT_SEED,
        in_dim: int = DEFAULT_INPUT_DIM,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        out_dim: int = DEFAULT_OUTPUT_DIM,
        learning_rate: float = 1e-3,
        history_k: int = HISTORY_K,
    ) -> None:
        self.seed = seed
        self.in_dim = in_dim
        self.hidden_dim = hidden_dim
        self.out_dim = out_dim
        self.learning_rate = learning_rate
        self.history_k = history_k

        # Seed MLX deterministically before module instantiation
        mx.random.seed(seed)
        self.net = DynamicsMLP(in_dim=in_dim, hidden_dim=hidden_dim, out_dim=out_dim)
        self.optimizer = optim.Adam(learning_rate=learning_rate)

        # Value and grad function for training
        self._loss_and_grad = nn.value_and_grad(self.net, self._compute_loss)

    @staticmethod
    def _compute_loss(model: DynamicsMLP, x: mx.array, y: mx.array) -> mx.array:
        preds = model(x)
        return mx.mean((preds - y) ** 2)

    def count_parameters(self) -> int:
        """Return total trainable parameter count."""
        return count_parameters(self.net)

    def parameter_sha256(self) -> str:
        """Compute SHA256 digest of network weights."""
        return compute_parameter_sha256(self.net)

    def save(self, path: str | Path) -> None:
        """Save model parameters to path."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.net.save_weights(str(p))

    def load(self, path: str | Path) -> None:
        """Load model parameters from path."""
        self.net.load_weights(str(path))

    def train_step(self, batch: Any) -> dict[str, float]:
        """Perform a single deterministic optimization step on CPU.

        Parameters:
            batch: tuple (inputs, targets) or dict with "inputs" and "targets".

        Returns:
            dict containing "loss" float.
        """
        if isinstance(batch, (tuple, list)):
            x_in, y_tar = batch[0], batch[1]
        elif isinstance(batch, dict):
            x_in = batch.get("inputs", batch.get("x"))
            y_tar = batch.get("targets", batch.get("y"))
        else:
            raise TypeError(f"Unsupported batch type: {type(batch)}")

        if not isinstance(x_in, mx.array):
            x_in = mx.array(np.asarray(x_in, dtype=np.float32))
        if not isinstance(y_tar, mx.array):
            y_tar = mx.array(np.asarray(y_tar, dtype=np.float32))

        loss, grads = self._loss_and_grad(self.net, x_in, y_tar)
        self.optimizer.update(self.net, grads)
        mx.eval(self.net.parameters(), self.optimizer.state)

        return {"loss": float(loss.item())}

    def _prepare_prefix(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
    ) -> tuple[dict[str, np.ndarray], list[ActiveBody], StaticEnvironment, bool]:
        """Parse observed prefix, isolating only prefix frames and rejecting trailing NaNs."""
        env = static_env if static_env is not None else StaticEnvironment()

        if isinstance(observed_prefix, dict):
            is_array_input = False
            raw_dict = observed_prefix
        elif isinstance(observed_prefix, np.ndarray):
            is_array_input = True
            raw_dict = {"body_0": observed_prefix}
        else:
            raise TypeError(f"Unsupported observed_prefix type: {type(observed_prefix)}")

        clean_dict: dict[str, np.ndarray] = {}
        bodies: list[ActiveBody] = []

        for name, arr in raw_dict.items():
            arr_np = np.asarray(arr, dtype=np.float64)
            # Find the first row containing NaN to strictly isolate the observed prefix
            if np.isnan(arr_np).any():
                nan_mask = np.isnan(arr_np).any(axis=-1)
                nan_indices = np.where(nan_mask)[0]
                if len(nan_indices) > 0:
                    prefix_end = int(nan_indices[0])
                    arr_np = arr_np[:prefix_end]

            if len(arr_np) == 0:
                raise ValueError(f"Observed prefix for {name} contains no valid finite frames")

            clean_dict[name] = arr_np

            # Extract initial physical state from the last valid frame in the prefix
            last_frame = arr_np[-1]
            pos = last_frame[0:3].copy()
            vel = last_frame[3:6].copy() if arr_np.shape[-1] >= 6 else np.zeros(3, dtype=np.float64)
            ori = last_frame[6:10].copy() if arr_np.shape[-1] >= 10 else np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
            ang = last_frame[10:13].copy() if arr_np.shape[-1] >= 13 else np.zeros(3, dtype=np.float64)

            b = ActiveBody(
                name=name,
                radius=0.1,
                params=DEFAULT_BIASED_PRIOR.copy(),
                position=pos,
                velocity=vel,
                orientation=ori,
                angular_velocity=ang,
            )
            bodies.append(b)

        return clean_dict, bodies, env, is_array_input

    def _extract_history_window(self, traj_history: list[np.ndarray]) -> np.ndarray:
        """Extract flat history vector of length K * 6 from the end of traj_history."""
        # Each entry in traj_history is a state array of shape (6,)
        if len(traj_history) < self.history_k:
            # Pad with the earliest available frame
            pad_count = self.history_k - len(traj_history)
            padded = [traj_history[0]] * pad_count + traj_history
        else:
            padded = traj_history[-self.history_k:]

        return np.concatenate(padded, axis=0).astype(np.float32)


# =========================================================================
# Arm 2: Pure MLX Dynamics Network (PureNetArm)
# =========================================================================

class PureNetArm(BaseNetArm):
    """Arm 2: Pure MLX MLP dynamics network.

    Takes the past K frames of body states [pos, vel] and predicts next-frame state
    delta autoregressively.
    """

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env)

        trajectories: dict[str, np.ndarray] = {
            b.name: np.zeros((n_future + 1, 13), dtype=np.float64) for b in bodies
        }

        # Initialize history from clean_dict
        history_map: dict[str, list[np.ndarray]] = {}
        for b in bodies:
            raw_arr = clean_dict[b.name]
            # State vector is [pos, vel] (6,)
            states = [np.concatenate([row[0:3], row[3:6] if len(row) >= 6 else np.zeros(3)]) for row in raw_arr]
            history_map[b.name] = states

            # Record frame 0
            trajectories[b.name][0, 0:3] = b.position
            trajectories[b.name][0, 3:6] = b.velocity
            trajectories[b.name][0, 6:10] = b.orientation
            trajectories[b.name][0, 10:13] = b.angular_velocity

        # Autoregressive rollout for n_future steps
        for step in range(1, n_future + 1):
            for b in bodies:
                hist_vec = self._extract_history_window(history_map[b.name])
                x_in = mx.array(hist_vec[None, :])
                delta_s = self.net(x_in)[0]
                mx.eval(delta_s)
                delta_np = np.asarray(delta_s, dtype=np.float64)

                # Update position and velocity
                b.position += delta_np[0:3]
                b.velocity += delta_np[3:6]

                # Update history
                curr_state = np.concatenate([b.position, b.velocity])
                history_map[b.name].append(curr_state)

                # Record frame
                trajectories[b.name][step, 0:3] = b.position
                trajectories[b.name][step, 3:6] = b.velocity
                trajectories[b.name][step, 6:10] = b.orientation
                trajectories[b.name][step, 10:13] = b.angular_velocity

        if is_array:
            return trajectories["body_0"]
        return trajectories


# =========================================================================
# Arm 3: Prior + MLX Residual Network (PriorResidualArm)
# =========================================================================

class PriorResidualArm(BaseNetArm):
    """Arm 3: Biased physical prior F_prior + MLX residual network.

    At each frame, advances state via prior.simulate_frame (with DEFAULT_BIASED_PRIOR)
    and adds the predicted state correction.
    """

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env)

        for b in bodies:
            b.params = DEFAULT_BIASED_PRIOR.copy()

        trajectories: dict[str, np.ndarray] = {
            b.name: np.zeros((n_future + 1, 13), dtype=np.float64) for b in bodies
        }

        # Initialize history
        history_map: dict[str, list[np.ndarray]] = {}
        for b in bodies:
            raw_arr = clean_dict[b.name]
            states = [np.concatenate([row[0:3], row[3:6] if len(row) >= 6 else np.zeros(3)]) for row in raw_arr]
            history_map[b.name] = states

            trajectories[b.name][0, 0:3] = b.position
            trajectories[b.name][0, 3:6] = b.velocity
            trajectories[b.name][0, 6:10] = b.orientation
            trajectories[b.name][0, 10:13] = b.angular_velocity

        for step in range(1, n_future + 1):
            # 1. Biased physical prior step
            simulate_frame(bodies, env)

            # 2. Residual network prediction and correction
            for b in bodies:
                hist_vec = self._extract_history_window(history_map[b.name])
                x_in = mx.array(hist_vec[None, :])
                corr_s = self.net(x_in)[0]
                mx.eval(corr_s)
                corr_np = np.asarray(corr_s, dtype=np.float64)

                # Add residual correction
                b.position += corr_np[0:3]
                b.velocity += corr_np[3:6]

                curr_state = np.concatenate([b.position, b.velocity])
                history_map[b.name].append(curr_state)

                trajectories[b.name][step, 0:3] = b.position
                trajectories[b.name][step, 3:6] = b.velocity
                trajectories[b.name][step, 6:10] = b.orientation
                trajectories[b.name][step, 10:13] = b.angular_velocity

        if is_array:
            return trajectories["body_0"]
        return trajectories


# =========================================================================
# Arm 6: Online Identified Prior + Orthogonal Projected Residual (IdentifyResidualArm)
# =========================================================================

class IdentifyResidualArm(BaseNetArm):
    """Arm 6: Identified prior + MLX residual projected onto orthogonal complement of dF_prior/d_phi.

    Specifications (DESIGN_CORE §2 item 7 & PREREG_DRAFT §2):
    - Phi is identified on the observed prefix (injected identifier_fn or fixed prior).
    - Residual correction is projected onto the orthogonal complement of the subspace
      spanned by dF_prior / d_phi using truncated SVD (cutoff relative to 1e-6 * sigma_max).
    - Truncated directions count is recorded.
    - Also provides project=False diagnostic variant.
    """

    def __init__(
        self,
        *,
        identifier_fn: IdentificationFn | None = None,
        project: bool = True,
        svd_rel_tol: float = DEFAULT_SVD_REL_TOL,
        seed: int = DEFAULT_SEED,
        in_dim: int = DEFAULT_INPUT_DIM,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        out_dim: int = DEFAULT_OUTPUT_DIM,
        learning_rate: float = 1e-3,
        history_k: int = HISTORY_K,
    ) -> None:
        super().__init__(
            seed=seed,
            in_dim=in_dim,
            hidden_dim=hidden_dim,
            out_dim=out_dim,
            learning_rate=learning_rate,
            history_k=history_k,
        )
        self.identifier_fn = identifier_fn
        self.project = project
        self.svd_rel_tol = svd_rel_tol
        self.last_truncated_counts: list[int] = []
        self.last_applied_corrections: list[np.ndarray] = []
        self.last_jacobians: list[np.ndarray] = []

    def project_residual(
        self,
        residual: np.ndarray,
        jacobian_matrix: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        """Project residual onto orthogonal complement of jacobian_matrix."""
        return project_onto_orthogonal_complement(
            residual, jacobian_matrix, rel_svd_tol=self.svd_rel_tol
        )

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
        *,
        return_info: bool = False,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env)

        self.last_truncated_counts = []
        self.last_applied_corrections = []
        self.last_jacobians = []

        # Parameter identification on observed prefix
        for b in bodies:
            if self.identifier_fn is not None:
                identified_phi = self.identifier_fn(clean_dict[b.name], env)
                b.params = identified_phi.copy()
            else:
                b.params = DEFAULT_BIASED_PRIOR.copy()

        trajectories: dict[str, np.ndarray] = {
            b.name: np.zeros((n_future + 1, 13), dtype=np.float64) for b in bodies
        }

        # Initialize history
        history_map: dict[str, list[np.ndarray]] = {}
        for b in bodies:
            raw_arr = clean_dict[b.name]
            states = [np.concatenate([row[0:3], row[3:6] if len(row) >= 6 else np.zeros(3)]) for row in raw_arr]
            history_map[b.name] = states

            trajectories[b.name][0, 0:3] = b.position
            trajectories[b.name][0, 3:6] = b.velocity
            trajectories[b.name][0, 6:10] = b.orientation
            trajectories[b.name][0, 10:13] = b.angular_velocity

        for step in range(1, n_future + 1):
            # Compute 1-step Jacobian at current state for each body
            jacobians: dict[str, np.ndarray] = {}
            for idx, b in enumerate(bodies):
                # Compute central difference sensitivity for 1 step
                jac_dict = compute_prior_jacobian(
                    bodies,
                    env,
                    num_frames=1,
                    body_index=idx,
                )
                # Stack parameter columns: d(pos, vel) / d(param) at frame 1
                cols = [jac_dict[p][1, 0:6] for p in PARAM_NAMES]
                jacobians[b.name] = np.column_stack(cols)  # (6, 5)

            # 1. Advance physical prior
            simulate_frame(bodies, env)

            # 2. Residual network prediction & projection
            for b in bodies:
                hist_vec = self._extract_history_window(history_map[b.name])
                x_in = mx.array(hist_vec[None, :])
                corr_s = self.net(x_in)[0]
                mx.eval(corr_s)
                raw_corr = np.asarray(corr_s, dtype=np.float64)

                J_matrix = jacobians[b.name]
                if self.project:
                    proj_corr, num_trunc = self.project_residual(raw_corr, J_matrix)
                    self.last_truncated_counts.append(num_trunc)
                else:
                    proj_corr = raw_corr
                    self.last_truncated_counts.append(0)

                self.last_applied_corrections.append(proj_corr)
                self.last_jacobians.append(J_matrix)

                # Add projected correction
                b.position += proj_corr[0:3]
                b.velocity += proj_corr[3:6]

                curr_state = np.concatenate([b.position, b.velocity])
                history_map[b.name].append(curr_state)

                trajectories[b.name][step, 0:3] = b.position
                trajectories[b.name][step, 3:6] = b.velocity
                trajectories[b.name][step, 6:10] = b.orientation
                trajectories[b.name][step, 10:13] = b.angular_velocity

        res = trajectories["body_0"] if is_array else trajectories
        if return_info:
            return res, {
                "truncated_counts": self.last_truncated_counts,
                "applied_corrections": self.last_applied_corrections,
                "jacobians": self.last_jacobians,
            }
        return res
