"""E1 Network Arms: Arm 2 (PureNet), Arm 3 (PriorResidual), and Arm 6 (IdentifyResidual).

Specification & Pre-registration references:
- reports/V9-P48/E1_IMPLEMENTATION_PLAN.md (E1-A2)
- reports/V9-P48/PREREG_DRAFT.md §2 (Arms table)
- reports/frontier-integration-20261027/DESIGN_CORE.md §2 item 7 (Orthogonal projection)
- reports/V9-P69 (Task card)
- ainerzero.V9.P79 (Residual training targets mathematical consistency)

Features:
1. Arm 2 (PureNetArm): MLX MLP predicting state increment (pos, vel) autoregressively
   from the recent K frames of state history:
       ②: y = s_{t+1} - s_t
2. Arm 3 (PriorResidualArm): Advances state via prior.DEFAULT_BIASED_PRIOR, then adds
   state correction predicted by MLX residual network:
       ③: y = s_{t+1} - F_prior(s_t; phi_0, statics)
3. Arm 6 (IdentifyResidualArm): Identifies phi from prefix (or uses injected identifier),
   advances state via prior, projects residual onto the orthogonal complement of the
   column space of dF_prior / d_phi (using jacobian.compute_orthogonal_projection_basis
   with SVD relative tolerance 1e-6 * sigma_max), and returns count of truncated directions.
   Also supports project=False as a diagnostic variant:
       ⑥: y = P_perp(phi_hat) * (s_{t+1} - F_prior(s_t; phi_hat, statics))
4. predict() and training_target() strictly share the scene-level physical prior step
   _prior_scene_step, guaranteeing exact mathematical consistency across multi-body
   interactions, inter-body collisions, actual bounding radii, and ground contact.
5. Identical parameter counts across Arms 2, 3, and 6.
6. Deterministic bitwise initialization under identical seeds, with parameter SHA256.
7. Operates strictly on MLX CPU device without unapproved external training.
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
# Output:  64 * 6 + 6   = 390
# Total: 1600 + 4160 + 390 = 6150 parameters (strictly frozen)
REGISTERED_PARAMETER_COUNT: int = 6150
DEFAULT_LEARNING_RATE: float = 1e-3

# Type alias for Arm 6 parameter identification function
IdentificationFn = Callable[[np.ndarray, StaticEnvironment], PhysicalParameters]


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
# Shared Scene-level Prior Step (Guarantees predict / training_target parity)
# =========================================================================

def _prior_scene_step(
    states_by_body: Mapping[str, np.ndarray | Sequence[float]],
    radii_by_body: Mapping[str, float] | None,
    params_by_body: Mapping[str, PhysicalParameters] | None,
    env: StaticEnvironment,
    *,
    compute_jacobians: bool = False,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray] | None]:
    """Advance multi-body scene by 1 frame under physical prior, optionally computing Jacobians.

    Guarantees strict mathematical consistency between predict() and training_target():
    1. Multi-body interaction: all bodies are simulated together in the scene.
    2. Actual radii: uses each body's actual bounding sphere radius (no hardcoded 0.1).
    3. Actual parameters: uses per-body parameters (phi_0 for Arm 3, identified phi_hat for Arm 6).
    """
    body_names = sorted(list(states_by_body.keys()))
    bodies: list[ActiveBody] = []
    for name in body_names:
        s = np.asarray(states_by_body[name], dtype=np.float64)
        pos = s[0:3].copy()
        vel = s[3:6].copy() if len(s) >= 6 else np.zeros(3, dtype=np.float64)
        ori = s[6:10].copy() if len(s) >= 10 else np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        ang = s[10:13].copy() if len(s) >= 13 else np.zeros(3, dtype=np.float64)

        r = float(radii_by_body[name]) if (radii_by_body is not None and name in radii_by_body) else 0.1
        if params_by_body is not None and name in params_by_body:
            p = params_by_body[name].copy()
        else:
            p = DEFAULT_BIASED_PRIOR.copy()

        bodies.append(
            ActiveBody(
                name=name,
                radius=r,
                params=p,
                position=pos,
                velocity=vel,
                orientation=ori,
                angular_velocity=ang,
            )
        )

    jacobians: dict[str, np.ndarray] | None = None
    if compute_jacobians:
        jacobians = {}
        for idx, b in enumerate(bodies):
            jac_dict = compute_prior_jacobian(
                bodies,
                env,
                num_frames=1,
                body_index=idx,
            )
            cols = [jac_dict[p][1, 0:6] for p in PARAM_NAMES]
            jacobians[b.name] = np.column_stack(cols)

    # Advance scene by 1 frame
    simulate_frame(bodies, env)

    next_states: dict[str, np.ndarray] = {}
    for b in bodies:
        next_states[b.name] = np.concatenate([
            b.position,
            b.velocity,
            b.orientation,
            b.angular_velocity,
        ])

    return next_states, jacobians


# =========================================================================
# Common Base Network Architecture
# =========================================================================

class ResidualMLP(nn.Module):
    """2-layer MLP with ReLU activations, outputting 6D state delta [dx, dy, dz, dvx, dvy, dvz]."""

    def __init__(
        self,
        in_dim: int = DEFAULT_INPUT_DIM,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        out_dim: int = DEFAULT_OUTPUT_DIM,
    ) -> None:
        super().__init__()
        self.fc1 = nn.Linear(in_dim, hidden_dim)
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.out = nn.Linear(hidden_dim, out_dim)

    def __call__(self, x: mx.array) -> mx.array:
        h1 = nn.relu(self.fc1(x))
        h2 = nn.relu(self.fc2(h1))
        return self.out(h2)


class BaseNetArm:
    """Base class providing initialization, MLX training step, serialization, and prefix prep."""

    def __init__(
        self,
        *,
        seed: int = DEFAULT_SEED,
        in_dim: int = DEFAULT_INPUT_DIM,
        hidden_dim: int = DEFAULT_HIDDEN_DIM,
        out_dim: int = DEFAULT_OUTPUT_DIM,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        history_k: int = HISTORY_K,
        radii: Mapping[str, float] | None = None,
    ) -> None:
        self.seed = int(seed)
        self.in_dim = int(in_dim)
        self.hidden_dim = int(hidden_dim)
        self.out_dim = int(out_dim)
        self.learning_rate = float(learning_rate)
        self.history_k = int(history_k)
        self.radii: dict[str, float] = dict(radii or {})

        # Deterministic MLX PRNG seeding
        mx.random.seed(self.seed)

        self.net = ResidualMLP(
            in_dim=self.in_dim,
            hidden_dim=self.hidden_dim,
            out_dim=self.out_dim,
        )
        self.optimizer = optim.Adam(learning_rate=self.learning_rate)

    def num_parameters(self) -> int:
        """Count total trainable parameters."""
        return count_parameters(self.net)

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

        inputs = mx.array(x_in, dtype=mx.float32)
        targets = mx.array(y_tar, dtype=mx.float32)

        def loss_fn(model, x, y):
            pred = model(x)
            return mx.mean((pred - y) ** 2)

        loss_and_grad_fn = nn.value_and_grad(self.net, loss_fn)
        loss_val, grads = loss_and_grad_fn(self.net, inputs, targets)

        self.optimizer.update(self.net, grads)
        mx.eval(self.net.parameters(), self.optimizer.state)

        return {"loss": float(loss_val)}

    def _prepare_prefix(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        radii: Mapping[str, float] | None = None,
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
        active_radii = dict(radii or getattr(self, "radii", {}))

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

            r = float(active_radii.get(name, 0.1))

            b = ActiveBody(
                name=name,
                radius=r,
                params=DEFAULT_BIASED_PRIOR.copy(),
                position=pos,
                velocity=vel,
                orientation=ori,
                angular_velocity=ang,
            )
            bodies.append(b)

        return clean_dict, bodies, env, is_array_input

    def _extract_history_window(self, states_list: list[np.ndarray]) -> np.ndarray:
        """Extract flat history vector of the last K frames of (pos, vel)."""
        K = self.history_k
        if len(states_list) < K:
            # Pad with earliest state if prefix is short
            first = states_list[0]
            padded = [first] * (K - len(states_list)) + states_list
        else:
            padded = states_list[-K:]
        # Extract first 6 dims (pos, vel)
        window = [s[0:6] for s in padded]
        return np.concatenate(window, axis=0)  # (K * 6,)

    def _extract_state_vector(self, state: Any) -> np.ndarray:
        """Helper to extract a single 13D or 6D state vector from window/array."""
        arr = np.asarray(state, dtype=np.float64)
        if arr.ndim == 1:
            return arr
        elif arr.ndim >= 2:
            return arr[-1]
        raise ValueError(f"Unsupported state shape: {arr.shape}")


# =========================================================================
# Arm 2: Pure MLX Dynamics Network (PureNetArm)
# =========================================================================

class PureNetArm(BaseNetArm):
    """Arm 2: Pure MLX MLP dynamics network.

    Takes the past K frames of body states [pos, vel] and predicts next-frame state
    delta autoregressively:
        ②: y = s_{t+1} - s_t
    """

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
        *,
        radii: Mapping[str, float] | None = None,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env, radii=radii)

        trajectories: dict[str, np.ndarray] = {
            b.name: np.zeros((n_future + 1, 13), dtype=np.float64) for b in bodies
        }

        # Initialize history from clean_dict
        history_map: dict[str, list[np.ndarray]] = {}
        for b in bodies:
            raw_arr = clean_dict[b.name]
            states = [np.concatenate([row[0:3], row[3:6] if len(row) >= 6 else np.zeros(3)]) for row in raw_arr]
            history_map[b.name] = states

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

                curr_state = np.concatenate([b.position, b.velocity])
                history_map[b.name].append(curr_state)

                trajectories[b.name][step, 0:3] = b.position
                trajectories[b.name][step, 3:6] = b.velocity
                trajectories[b.name][step, 6:10] = b.orientation
                trajectories[b.name][step, 10:13] = b.angular_velocity

        if is_array:
            return trajectories["body_0"]
        return trajectories

    def scene_training_targets(
        self,
        scene_states: Mapping[str, Any],
        next_scene_states: Mapping[str, Any],
        static_env: StaticEnvironment | None = None,
        *,
        radii_by_body: Mapping[str, float] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> dict[str, np.ndarray]:
        """Compute training targets for all bodies in the scene for Arm 2: y = s_{t+1} - s_t."""
        targets: dict[str, np.ndarray] = {}
        for name in scene_states:
            s_t = self._extract_state_vector(scene_states[name])
            s_next = np.asarray(next_scene_states[name], dtype=np.float64)
            targets[name] = np.asarray(s_next[:6] - s_t[:6], dtype=np.float32)
        return targets

    def training_target(
        self,
        state_window: Any,
        next_state: Any,
        static_env: StaticEnvironment | None = None,
        prefix_for_identification: Any = None,
        *,
        body_name: str = "body_0",
        radii_by_body: Mapping[str, float] | None = None,
        scene_states: Mapping[str, Any] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> np.ndarray:
        """Compute training target for Arm 2 (PureNetArm): y = s_{t+1} - s_t."""
        s_t = self._extract_state_vector(state_window)
        s_next = np.asarray(next_state, dtype=np.float64)
        target = s_next[:6] - s_t[:6]
        return np.asarray(target, dtype=np.float32)


# =========================================================================
# Arm 3: Prior + MLX Residual Network (PriorResidualArm)
# =========================================================================

class PriorResidualArm(BaseNetArm):
    """Arm 3: Biased physical prior F_prior + MLX residual network.

    Takes the past K frames of body states [pos, vel] and predicts a state correction
    added to the 1-step prior dynamics prediction:
        ③: y = s_{t+1} - F_prior(s_t; phi_0, statics)
    """

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
        *,
        radii: Mapping[str, float] | None = None,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env, radii=radii)
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
            curr_states = {
                b.name: np.concatenate([b.position, b.velocity, b.orientation, b.angular_velocity])
                for b in bodies
            }
            radii_map = {b.name: b.radius for b in bodies}
            params_map = {b.name: b.params for b in bodies}

            # 1. Biased physical prior step via shared _prior_scene_step
            next_prior_states, _ = _prior_scene_step(
                curr_states,
                radii_by_body=radii_map,
                params_by_body=params_map,
                env=env,
                compute_jacobians=False,
            )

            for b in bodies:
                prior_s = next_prior_states[b.name]
                b.position = prior_s[0:3].copy()
                b.velocity = prior_s[3:6].copy()
                b.orientation = prior_s[6:10].copy()
                b.angular_velocity = prior_s[10:13].copy()

            # 2. Residual network prediction and correction
            for b in bodies:
                hist_vec = self._extract_history_window(history_map[b.name])
                x_in = mx.array(hist_vec[None, :])
                corr_s = self.net(x_in)[0]
                mx.eval(corr_s)
                corr_np = np.asarray(corr_s, dtype=np.float64)

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

    def scene_training_targets(
        self,
        scene_states: Mapping[str, Any],
        next_scene_states: Mapping[str, Any],
        static_env: StaticEnvironment | None = None,
        *,
        radii_by_body: Mapping[str, float] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> dict[str, np.ndarray]:
        """Compute training targets for all bodies in the scene for Arm 3:

        y = s_{t+1} - F_prior(s_t; phi_0, statics)
        """
        env = static_env if static_env is not None else StaticEnvironment()
        clean_scene = {name: self._extract_state_vector(scene_states[name]) for name in scene_states}
        params_map = {name: DEFAULT_BIASED_PRIOR.copy() for name in clean_scene}

        next_prior_states, _ = _prior_scene_step(
            clean_scene,
            radii_by_body=radii_by_body,
            params_by_body=params_map,
            env=env,
            compute_jacobians=False,
        )

        targets: dict[str, np.ndarray] = {}
        for name in clean_scene:
            s_next = np.asarray(next_scene_states[name], dtype=np.float64)
            f_prior = next_prior_states[name]
            targets[name] = np.asarray(s_next[:6] - f_prior[:6], dtype=np.float32)
        return targets

    def training_target(
        self,
        state_window: Any,
        next_state: Any,
        static_env: StaticEnvironment | None = None,
        prefix_for_identification: Any = None,
        *,
        body_name: str = "body_0",
        radii_by_body: Mapping[str, float] | None = None,
        scene_states: Mapping[str, Any] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> np.ndarray:
        """Compute training target for Arm 3 (PriorResidualArm):

        Mathematical definition (一级裁定):
            ③: y = s_{t+1} - F_prior(s_t; phi_0, statics)
        """
        s_t = self._extract_state_vector(state_window)
        if scene_states is not None:
            full_scene = dict(scene_states)
            if body_name not in full_scene:
                full_scene[body_name] = s_t
        else:
            full_scene = {body_name: s_t}

        next_scene = {body_name: next_state}
        for k in full_scene:
            if k not in next_scene:
                next_scene[k] = full_scene[k]

        targets = self.scene_training_targets(
            full_scene,
            next_scene,
            static_env=static_env,
            radii_by_body=radii_by_body,
            params_by_body=params_by_body,
        )
        return targets[body_name]


# =========================================================================
# Arm 6: Online Identified Prior + Orthogonal Projected Residual (IdentifyResidualArm)
# =========================================================================

class IdentifyResidualArm(BaseNetArm):
    """Arm 6: Identified prior + MLX residual projected onto orthogonal complement of dF_prior/d_phi.

    Specifications (DESIGN_CORE §2 item 7 & PREREG_DRAFT §2):
    1. Identifies physical parameters phi_hat on observed prefix (or uses injected identifier_fn).
    2. Autoregressively advances physical prior with identified parameters phi_hat.
    3. Projects MLX residual network output onto ker(dF_prior/d_phi)^T:
           ⑥: y = P_perp(phi_hat) * (s_{t+1} - F_prior(s_t; phi_hat, statics))
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
        learning_rate: float = DEFAULT_LEARNING_RATE,
        history_k: int = HISTORY_K,
        radii: Mapping[str, float] | None = None,
    ) -> None:
        super().__init__(
            seed=seed,
            in_dim=in_dim,
            hidden_dim=hidden_dim,
            out_dim=out_dim,
            learning_rate=learning_rate,
            history_k=history_k,
            radii=radii,
        )
        self.identifier_fn = identifier_fn
        self.project = bool(project)
        self.svd_rel_tol = float(svd_rel_tol)

        # Telemetry / diagnostic records from the most recent predict rollout
        self.last_truncated_counts: list[int] = []
        self.last_applied_corrections: list[np.ndarray] = []
        self.last_jacobians: list[np.ndarray] = []

    def project_residual(
        self,
        residual: np.ndarray,
        jacobian_matrix: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        """Project residual vector onto the orthogonal complement of the column space of Jacobian.

        Parameters:
            residual: (6,) raw network output [dx, dy, dz, dvx, dvy, dvz].
            jacobian_matrix: (6, 5) sensitivities d(pos, vel) / d(param).

        Returns:
            projected_residual: (6,) vector in ker(J^T).
            truncated_count: number of truncated singular directions.
        """
        return project_onto_orthogonal_complement(
            residual, jacobian_matrix, rel_svd_tol=self.svd_rel_tol
        )

    def _apply_correction(
        self,
        raw_corr: np.ndarray,
        jacobian_matrix: np.ndarray,
    ) -> tuple[np.ndarray, int]:
        """Apply residual projection onto orthogonal complement of Jacobian (or bypass if project=False).

        Shared between predict() and training_target() to guarantee mathematical consistency.
        """
        if self.project:
            return self.project_residual(raw_corr, jacobian_matrix)
        return raw_corr, 0

    def predict(
        self,
        observed_prefix: Any,
        static_env: StaticEnvironment | None,
        n_future: int,
        *,
        radii: Mapping[str, float] | None = None,
        return_info: bool = False,
    ) -> Any:
        clean_dict, bodies, env, is_array = self._prepare_prefix(observed_prefix, static_env, radii=radii)

        self.last_truncated_counts = []
        self.last_applied_corrections = []
        self.last_jacobians = []

        # Parameter identification on observed prefix
        for b in bodies:
            if self.identifier_fn is not None:
                # Online parameter identification from trajectory prefix (pos, vel)
                prefix_states = clean_dict[b.name][:, 0:6]
                identified_params = self.identifier_fn(prefix_states, env)
                b.params = identified_params.copy()
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
            curr_states = {
                b.name: np.concatenate([b.position, b.velocity, b.orientation, b.angular_velocity])
                for b in bodies
            }
            radii_map = {b.name: b.radius for b in bodies}
            params_map = {b.name: b.params for b in bodies}

            # 1. Advance physical prior and compute Jacobians via shared _prior_scene_step
            next_prior_states, jacobians = _prior_scene_step(
                curr_states,
                radii_by_body=radii_map,
                params_by_body=params_map,
                env=env,
                compute_jacobians=True,
            )

            for b in bodies:
                prior_s = next_prior_states[b.name]
                b.position = prior_s[0:3].copy()
                b.velocity = prior_s[3:6].copy()
                b.orientation = prior_s[6:10].copy()
                b.angular_velocity = prior_s[10:13].copy()

            # 2. Residual network prediction & projection
            for b in bodies:
                hist_vec = self._extract_history_window(history_map[b.name])
                x_in = mx.array(hist_vec[None, :])
                corr_s = self.net(x_in)[0]
                mx.eval(corr_s)
                raw_corr = np.asarray(corr_s, dtype=np.float64)

                J_matrix = jacobians[b.name]
                proj_corr, num_trunc = self._apply_correction(raw_corr, J_matrix)
                self.last_truncated_counts.append(num_trunc)
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

    def scene_training_targets(
        self,
        scene_states: Mapping[str, Any],
        next_scene_states: Mapping[str, Any],
        static_env: StaticEnvironment | None = None,
        *,
        radii_by_body: Mapping[str, float] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> dict[str, np.ndarray]:
        """Compute training targets for all bodies in the scene for Arm 6:

        y = P_perp(phi_hat) * (s_{t+1} - F_prior(s_t; phi_hat, statics))
        """
        env = static_env if static_env is not None else StaticEnvironment()
        clean_scene = {name: self._extract_state_vector(scene_states[name]) for name in scene_states}
        params_map = dict(params_by_body or {})
        for name in clean_scene:
            if name not in params_map:
                params_map[name] = DEFAULT_BIASED_PRIOR.copy()

        next_prior_states, jacobians = _prior_scene_step(
            clean_scene,
            radii_by_body=radii_by_body,
            params_by_body=params_map,
            env=env,
            compute_jacobians=True,
        )

        targets: dict[str, np.ndarray] = {}
        for name in clean_scene:
            s_next = np.asarray(next_scene_states[name], dtype=np.float64)
            f_prior = next_prior_states[name]
            raw_diff = s_next[:6] - f_prior[:6]
            J_matrix = jacobians[name]
            proj_target, _ = self._apply_correction(raw_diff, J_matrix)
            targets[name] = np.asarray(proj_target, dtype=np.float32)

        return targets

    def training_target(
        self,
        state_window: Any,
        next_state: Any,
        static_env: StaticEnvironment | None = None,
        prefix_for_identification: Any = None,
        *,
        body_name: str = "body_0",
        radii_by_body: Mapping[str, float] | None = None,
        scene_states: Mapping[str, Any] | None = None,
        params_by_body: Mapping[str, PhysicalParameters] | None = None,
    ) -> np.ndarray:
        """Compute training target for Arm 6 (IdentifyResidualArm).

        Mathematical definition (一级裁定):
            ⑥: y = P_perp(phi_hat) * (s_{t+1} - F_prior(s_t; phi_hat, statics))

        where:
            - F_prior: prior.rollout/simulate_frame from s_t for 1 frame,
              extracting position and velocity (consistent with student side).
            - phi_hat: identified by identifier_fn on prefix_for_identification
              (cached per episode) or DEFAULT_BIASED_PRIOR.
            - P_perp: orthogonal projection onto the orthogonal complement of
              dF_prior / d_phi, using the identical function and parameters as predict().
        """
        s_t = self._extract_state_vector(state_window)
        env = static_env if static_env is not None else StaticEnvironment()

        if scene_states is not None:
            full_scene = dict(scene_states)
            if body_name not in full_scene:
                full_scene[body_name] = s_t
        else:
            full_scene = {body_name: s_t}

        next_scene = {body_name: next_state}
        for k in full_scene:
            if k not in next_scene:
                next_scene[k] = full_scene[k]

        params_map = dict(params_by_body or {})
        if body_name not in params_map:
            if isinstance(prefix_for_identification, PhysicalParameters):
                params_map[body_name] = prefix_for_identification.copy()
            elif self.identifier_fn is not None and prefix_for_identification is not None:
                params_map[body_name] = self.identifier_fn(prefix_for_identification, env)
            else:
                params_map[body_name] = DEFAULT_BIASED_PRIOR.copy()

        targets = self.scene_training_targets(
            full_scene,
            next_scene,
            static_env=env,
            radii_by_body=radii_by_body,
            params_by_body=params_map,
        )
        return targets[body_name]
