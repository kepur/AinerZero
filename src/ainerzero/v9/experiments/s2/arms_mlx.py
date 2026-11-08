"""S2 three-arm MLX implementations and losses (ainerzero.V9.P128).

Implements:
1. Arm A (FlatRSSMArm): Shared E1 + GRU + Gaussian prior/posterior heads + observation decoder.
2. Arm B (FlatJEPAArm): Shared E1 + residual predictor P1 + IDM head.
3. Arm C (HierarchicalHJEPAArm): Layer 1 (B structure) + Layer 2 (E2 + P2 + IDM2).
4. MLX versions of mathematical losses matching core_math.py:
   - SIGReg (Epps-Pulley normality statistic over random unit projections on S^{D-1})
   - Continuous Gaussian negative log-likelihood with fixed variance
   - Soft-target categorical cross-entropy for action histograms
   - Composite IDM loss
   - Autoregressive latent rollout loss
   - Arm A observation reconstruction + KL divergence with free bits = 1.0
5. Model-agnostic planning callables (encode, predict_l1, encode_l2, predict_l2, planning_cost)
   compatible with s2/planner.py.
6. count_params(model): recursively counts parameters matching s2/param_count.py formulas.

Architectural dimensions are strictly retrieved from s2.spec.ARM_DIMS with no hardcoded
integer layer widths in Linear or GRU constructors.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Mapping, Sequence

import mlx.core as mx
import mlx.nn as nn
import numpy as np

from ainerzero.v9.experiments.s2 import param_count, spec


# ==============================================================================
# 1. Custom Recurrent & Encoder Cells
# ==============================================================================


class GRUCell(nn.Module):
    """One-step GRU cell matching MLX repository convention and param_count formula.

    Parameter layout:
    - Wx: (3 * hidden_size, input_size)
    - Wh: (3 * hidden_size, hidden_size)
    - b:  (3 * hidden_size,) if bias
    - bhn: (hidden_size,) if bias
    Total parameters = 3 * hidden_size * (input_size + hidden_size) + 4 * hidden_size
    """

    def __init__(self, input_size: int, hidden_size: int, bias: bool = True):
        super().__init__()
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.use_bias = bias

        bound_x = math.sqrt(6.0 / (input_size + 3 * hidden_size))
        bound_h = math.sqrt(6.0 / (4 * hidden_size))
        self.Wx = mx.random.uniform(-bound_x, bound_x, (3 * hidden_size, input_size))
        self.Wh = mx.random.uniform(-bound_h, bound_h, (3 * hidden_size, hidden_size))
        if bias:
            self.b = mx.zeros((3 * hidden_size,))
            self.bhn = mx.zeros((hidden_size,))

    def __call__(self, x: mx.array, h: mx.array) -> mx.array:
        """Advance GRU state by one step: (x, h) -> h_next."""
        if self.use_bias:
            wx = mx.addmm(self.b, x, self.Wx.T)
        else:
            wx = x @ self.Wx.T
        wh = h @ self.Wh.T

        xr, xg, xn = mx.split(wx, 3, axis=-1)
        hr, hg, hn = mx.split(wh, 3, axis=-1)

        reset = mx.sigmoid(xr + hr)
        gate = mx.sigmoid(xg + hg)

        if self.use_bias:
            candidate = mx.tanh(xn + reset * (hn + self.bhn))
        else:
            candidate = mx.tanh(xn + reset * hn)

        return (1.0 - gate) * candidate + gate * h


class SharedE1Encoder(nn.Module):
    """Shared E1 encoder: 205 -> 256 -> 128 (GELU)."""

    def __init__(self, dims: Mapping[str, Any]):
        super().__init__()
        e1_in = dims["e1_input"]
        e1_h = dims["e1_hidden"]
        e1_out = dims["e1_output"]
        self.fc1 = nn.Linear(e1_in, e1_h)
        self.fc2 = nn.Linear(e1_h, e1_out)

    def __call__(self, x: mx.array) -> mx.array:
        return self.fc2(nn.gelu(self.fc1(x)))


# ==============================================================================
# 2. Three Model Arms (A, B, C)
# ==============================================================================


class FlatRSSMArm(nn.Module):
    """Arm A: flat RSSM with GRU deterministic state and Gaussian latent."""

    def __init__(self, dims: Mapping[str, Any] | None = None):
        super().__init__()
        cfg = dims if dims is not None else spec.ARM_DIMS["arm_a"]
        self.dims = cfg

        e1_in = cfg["e1_input"]
        gru_in = cfg["gru_input"]
        gru_h = cfg["gru_hidden"]
        prior_h = cfg["prior_hidden"]
        post_h = cfg["posterior_hidden"]
        dec_h = cfg["decoder_hidden"]
        z_dim = cfg["latent_dim"]
        e1_out = cfg["e1_output"]

        post_in = gru_h + e1_out
        dec_in = gru_h + z_dim
        head_out = 2 * z_dim

        self.e1 = SharedE1Encoder(cfg)
        self.gru = GRUCell(gru_in, gru_h, bias=True)

        # Prior head p(z|h): h -> prior_hidden -> 2 * z_dim (mean, std)
        self.prior_fc1 = nn.Linear(gru_h, prior_h)
        self.prior_fc2 = nn.Linear(prior_h, head_out)

        # Posterior head q(z|h, E1(o)): [h, E1] -> post_hidden -> 2 * z_dim
        self.post_fc1 = nn.Linear(post_in, post_h)
        self.post_fc2 = nn.Linear(post_h, head_out)

        # Decoder: [h, z] -> dec_hidden -> e1_in
        self.dec_fc1 = nn.Linear(dec_in, dec_h)
        self.dec_fc2 = nn.Linear(dec_h, e1_in)

    def encode(self, obs: mx.array | np.ndarray) -> mx.array:
        """Encode raw observation to E1 feature representation."""
        x = mx.array(obs, dtype=mx.float32) if isinstance(obs, np.ndarray) else obs
        return self.e1(x)

    def prior(self, h: mx.array) -> tuple[mx.array, mx.array]:
        """Compute prior Gaussian parameters (mean, log_std) from deterministic h."""
        out = self.prior_fc2(nn.gelu(self.prior_fc1(h)))
        mean, log_std = mx.split(out, 2, axis=-1)
        return mean, log_std

    def posterior(self, h: mx.array, e1_feat: mx.array) -> tuple[mx.array, mx.array]:
        """Compute posterior Gaussian parameters (mean, log_std) from h and E1."""
        cat_in = mx.concatenate([h, e1_feat], axis=-1)
        out = self.post_fc2(nn.gelu(self.post_fc1(cat_in)))
        mean, log_std = mx.split(out, 2, axis=-1)
        return mean, log_std

    def decode(self, h: mx.array, z: mx.array) -> mx.array:
        """Decode deterministic state h and latent state z back to observation space."""
        cat_in = mx.concatenate([h, z], axis=-1)
        return self.dec_fc2(nn.gelu(self.dec_fc1(cat_in)))

    def predict_l1(
        self,
        z: np.ndarray | mx.array,
        a: np.ndarray | mx.array,
        dt: float | np.ndarray | mx.array = 1.0,
    ) -> np.ndarray:
        """Planning callable: advances deterministic state and samples/prior-projects z."""
        z_arr = mx.array(z, dtype=mx.float32) if isinstance(z, np.ndarray) else z
        a_arr = mx.array(a, dtype=mx.float32) if isinstance(a, np.ndarray) else a
        if a_arr.ndim == 0 or (a_arr.ndim == 1 and a_arr.shape[0] == 1):
            # Convert categorical action index to 4-dim one-hot if scalar
            idx = int(a_arr.item()) if a_arr.ndim == 0 else int(a_arr[0].item())
            a_onehot = mx.zeros((spec.ACTION_DIM,), dtype=mx.float32)
            a_onehot[idx] = 1.0
            a_arr = a_onehot
        dt_arr = mx.array([float(dt)], dtype=mx.float32) if not isinstance(dt, mx.array) else dt

        # Initial h zeros if not tracked externally
        h_init = mx.zeros((self.dims["gru_hidden"],), dtype=mx.float32)
        gru_in = mx.concatenate([z_arr, a_arr, dt_arr], axis=-1)
        h_next = self.gru(gru_in, h_init)
        mean, _ = self.prior(h_next)
        return np.asarray(mean, dtype=np.float64)

    def planning_cost(
        self,
        z_or_obs: np.ndarray | mx.array,
        goal_obs: np.ndarray | mx.array,
    ) -> float:
        """Observation-space planning cost: cross entropy against goal observation.

        Accepts either an observation vector (205-dim) or a latent vector (32-dim).
        When given a latent vector, decodes to observation space using decode(h0, z).
        """
        arr = mx.array(z_or_obs, dtype=mx.float32) if isinstance(z_or_obs, np.ndarray) else z_or_obs
        if arr.shape[-1] != spec.OBS_DIM:
            h0 = mx.zeros((self.dims["gru_hidden"],), dtype=mx.float32)
            dec = self.decode(h0, arr)
        else:
            dec = arr
        goal = mx.array(goal_obs, dtype=mx.float32) if isinstance(goal_obs, np.ndarray) else goal
        # Soft cross entropy on first 196 terrain dims + MSE on coordinates
        terrain_pred = dec[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
        terrain_goal = goal[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
        cost_terrain = soft_cross_entropy_mlx(terrain_pred, terrain_goal)
        cost_rem = mx.mean((dec[spec.TERRAIN_ONE_HOT_DIM:] - goal[spec.TERRAIN_ONE_HOT_DIM:]) ** 2)
        return float((cost_terrain + cost_rem).item())


class FlatJEPAArm(nn.Module):
    """Arm B: flat JEPA (LeWM style) with shared E1, residual predictor P1, and IDM."""

    def __init__(self, dims: Mapping[str, Any] | None = None):
        super().__init__()
        cfg = dims if dims is not None else spec.ARM_DIMS["arm_b"]
        self.dims = cfg

        p1_in = cfg["p1_input"]
        p1_h1 = cfg["p1_hidden_1"]
        p1_h2 = cfg["p1_hidden_2"]
        p1_out = cfg["p1_output"]
        idm_in = cfg["idm_input"]
        idm_h = cfg["idm_hidden"]
        idm_out = cfg["idm_output"]

        self.e1 = SharedE1Encoder(cfg)

        # Residual predictor P1: [z(128), a(4), dt(1)] -> 320 -> 320 -> 128
        self.p1_fc1 = nn.Linear(p1_in, p1_h1)
        self.p1_fc2 = nn.Linear(p1_h1, p1_h2)
        self.p1_fc3 = nn.Linear(p1_h2, p1_out)

        # IDM: [z_t, z_{t+1}] -> idm_hidden -> 4
        self.idm_fc1 = nn.Linear(idm_in, idm_h)
        self.idm_fc2 = nn.Linear(idm_h, idm_out)

    def encode(self, obs: mx.array | np.ndarray) -> mx.array:
        """Encode raw observation to 128-dim latent space."""
        x = mx.array(obs, dtype=mx.float32) if isinstance(obs, np.ndarray) else obs
        return self.e1(x)

    def predict_l1_step(self, z: mx.array, a: mx.array, dt: mx.array) -> mx.array:
        """One-step residual prediction in latent space: z_{t+1} = z_t + P1(z_t, a_t, dt)."""
        x = mx.concatenate([z, a, dt], axis=-1)
        h = nn.gelu(self.p1_fc1(x))
        h = nn.gelu(self.p1_fc2(h))
        delta = self.p1_fc3(h)
        return z + delta

    def predict_idm(self, z_curr: mx.array, z_next: mx.array) -> mx.array:
        """Inverse dynamics prediction: [z_t, z_{t+1}] -> action logits."""
        x = mx.concatenate([z_curr, z_next], axis=-1)
        h = nn.gelu(self.idm_fc1(x))
        return self.idm_fc2(h)

    def predict_l1(
        self,
        z: np.ndarray | mx.array,
        a: np.ndarray | mx.array,
        dt: float | np.ndarray | mx.array = 1.0,
    ) -> np.ndarray:
        """Planner-compatible callable for flat CEM rollout."""
        z_arr = mx.array(z, dtype=mx.float32) if isinstance(z, np.ndarray) else z
        a_arr = mx.array(a, dtype=mx.float32) if isinstance(a, np.ndarray) else a
        if a_arr.ndim == 0 or (a_arr.ndim == 1 and a_arr.shape[0] == 1):
            idx = int(a_arr.item()) if a_arr.ndim == 0 else int(a_arr[0].item())
            a_onehot = mx.zeros((spec.ACTION_DIM,), dtype=mx.float32)
            a_onehot[idx] = 1.0
            a_arr = a_onehot
        dt_arr = mx.array([float(dt)], dtype=mx.float32) if not isinstance(dt, mx.array) else dt
        z_next = self.predict_l1_step(z_arr, a_arr, dt_arr)
        return np.asarray(z_next, dtype=np.float64)


class HierarchicalHJEPAArm(nn.Module):
    """Arm C: Two-layer hierarchical H-JEPA style model."""

    def __init__(self, dims: Mapping[str, Any] | None = None):
        super().__init__()
        cfg = dims if dims is not None else spec.ARM_DIMS["arm_c"]
        self.dims = cfg

        # Layer 1 (Arm B structure, 256 hidden width)
        p1_in = cfg["p1_input"]
        p1_h1 = cfg["p1_hidden_1"]
        p1_h2 = cfg["p1_hidden_2"]
        p1_out = cfg["p1_output"]
        idm_in = cfg["idm_input"]
        idm_h = cfg["idm_hidden"]
        idm_out = cfg["idm_output"]

        self.e1 = SharedE1Encoder(cfg)
        self.p1_fc1 = nn.Linear(p1_in, p1_h1)
        self.p1_fc2 = nn.Linear(p1_h1, p1_h2)
        self.p1_fc3 = nn.Linear(p1_h2, p1_out)
        self.idm_fc1 = nn.Linear(idm_in, idm_h)
        self.idm_fc2 = nn.Linear(idm_h, idm_out)

        # Layer 2 (macro dynamics across s2 steps)
        e2_in = cfg["e2_input"]
        e2_h = cfg["e2_hidden"]
        z2_dim = cfg["z2_dim"]
        p2_in = cfg["p2_input"]
        p2_h = cfg["p2_hidden"]
        p2_out = cfg["p2_output"]
        idm2_in = cfg["idm2_input"]
        idm2_h = cfg["idm2_hidden"]
        idm2_out = cfg["idm2_output"]

        self.e2_fc1 = nn.Linear(e2_in, e2_h)
        self.e2_fc2 = nn.Linear(e2_h, z2_dim)

        self.p2_fc1 = nn.Linear(p2_in, p2_h)
        self.p2_fc2 = nn.Linear(p2_h, p2_out)

        self.idm2_fc1 = nn.Linear(idm2_in, idm2_h)
        self.idm2_fc2 = nn.Linear(idm2_h, idm2_out)

    def encode(self, obs: mx.array | np.ndarray) -> mx.array:
        """Encode raw observation to Layer 1 representation z1 (128-dim)."""
        x = mx.array(obs, dtype=mx.float32) if isinstance(obs, np.ndarray) else obs
        return self.e1(x)

    def encode_l2(self, z1: mx.array | np.ndarray) -> mx.array:
        """Encode Layer 1 latent z1 to Layer 2 macro latent z2 (64-dim)."""
        x = mx.array(z1, dtype=mx.float32) if isinstance(z1, np.ndarray) else z1
        return self.e2_fc2(nn.gelu(self.e2_fc1(x)))

    def predict_l1_step(self, z1: mx.array, a: mx.array, dt: mx.array) -> mx.array:
        """One-step Layer 1 residual forward prediction."""
        x = mx.concatenate([z1, a, dt], axis=-1)
        h = nn.gelu(self.p1_fc1(x))
        h = nn.gelu(self.p1_fc2(h))
        delta = self.p1_fc3(h)
        return z1 + delta

    def predict_l2_step(self, z2: mx.array, macro_a: mx.array, dt2: mx.array) -> mx.array:
        """One-macro-step Layer 2 residual forward prediction."""
        x = mx.concatenate([z2, macro_a, dt2], axis=-1)
        delta = self.p2_fc2(nn.gelu(self.p2_fc1(x)))
        return z2 + delta

    def predict_idm1(self, z1_curr: mx.array, z1_next: mx.array) -> mx.array:
        """Layer 1 IDM prediction."""
        x = mx.concatenate([z1_curr, z1_next], axis=-1)
        return self.idm_fc2(nn.gelu(self.idm_fc1(x)))

    def predict_idm2(self, z2_curr: mx.array, z2_next: mx.array) -> mx.array:
        """Layer 2 macro IDM prediction."""
        x = mx.concatenate([z2_curr, z2_next], axis=-1)
        return self.idm2_fc2(nn.gelu(self.idm2_fc1(x)))

    def predict_l1(
        self,
        z: np.ndarray | mx.array,
        a: np.ndarray | mx.array,
        dt: float | np.ndarray | mx.array = 1.0,
    ) -> np.ndarray:
        """Planner-compatible callable for Layer 1 CEM rollout."""
        z_arr = mx.array(z, dtype=mx.float32) if isinstance(z, np.ndarray) else z
        a_arr = mx.array(a, dtype=mx.float32) if isinstance(a, np.ndarray) else a
        if a_arr.ndim == 0 or (a_arr.ndim == 1 and a_arr.shape[0] == 1):
            idx = int(a_arr.item()) if a_arr.ndim == 0 else int(a_arr[0].item())
            a_onehot = mx.zeros((spec.ACTION_DIM,), dtype=mx.float32)
            a_onehot[idx] = 1.0
            a_arr = a_onehot
        dt_arr = mx.array([float(dt)], dtype=mx.float32) if not isinstance(dt, mx.array) else dt
        z_next = self.predict_l1_step(z_arr, a_arr, dt_arr)
        return np.asarray(z_next, dtype=np.float64)

    def predict_l2(
        self,
        z2: np.ndarray | mx.array,
        macro_a: np.ndarray | mx.array,
        macro_dt: float | np.ndarray | mx.array = 1.0,
    ) -> np.ndarray:
        """Planner-compatible callable for Layer 2 macro CEM rollout."""
        z2_arr = mx.array(z2, dtype=mx.float32) if isinstance(z2, np.ndarray) else z2
        ma_arr = mx.array(macro_a, dtype=mx.float32) if isinstance(macro_a, np.ndarray) else macro_a
        dt_arr = (
            mx.array([float(macro_dt)], dtype=mx.float32)
            if not isinstance(macro_dt, mx.array)
            else macro_dt
        )
        z2_next = self.predict_l2_step(z2_arr, ma_arr, dt_arr)
        return np.asarray(z2_next, dtype=np.float64)


# ==============================================================================
# 3. Mathematical Losses (MLX implementation aligned with P111 core_math)
# ==============================================================================


def sigreg_mlx(
    Z: mx.array,
    directions: mx.array,
    n_knots: int = 17,
    t_min: float = 0.2,
    t_max: float = 4.0,
) -> mx.array:
    """Compute SIGReg regularizer in MLX matching core_math.sigreg exactly.

    Z: (N, D) representation matrix.
    directions: (M, D) unit projection vectors on S^{D-1}.
    """
    X = Z @ directions.T  # (N, M)

    knots_np = np.linspace(t_min, t_max, n_knots, dtype=np.float32)
    dt = (t_max - t_min) / (n_knots - 1)
    trapz = np.full(n_knots, dt, dtype=np.float32)
    trapz[0] *= 0.5
    trapz[-1] *= 0.5

    phi_0_np = np.exp(-0.5 * (knots_np**2))
    w_t_np = np.exp(-0.5 * (knots_np**2))
    quad_weights_np = trapz * w_t_np

    knots = mx.array(knots_np)
    phi_0 = mx.array(phi_0_np)
    quad_weights = mx.array(quad_weights_np)

    # t_X: (K, N, M)
    t_X = knots[:, None, None] * X[None, :, :]
    mean_cos = mx.mean(mx.cos(t_X), axis=1)  # (K, M)
    mean_sin = mx.mean(mx.sin(t_X), axis=1)  # (K, M)

    diff_cos = mean_cos - phi_0[:, None]
    sq_diff = (diff_cos**2) + (mean_sin**2)

    t_stat = mx.sum(quad_weights[:, None] * sq_diff, axis=0)  # (M,)
    return mx.mean(t_stat)


def compute_sigreg_mlx(
    Z: mx.array,
    n_directions: int = 16,
    rng: Any = 42,
) -> mx.array:
    """Compute SIGReg on MLX array using matched random unit projections."""
    from ainerzero.v9.experiments.s2 import core_math

    D = Z.shape[-1]
    dirs = core_math.generate_sigreg_directions(n_directions, D, rng=rng)
    return sigreg_mlx(Z, mx.array(dirs))


def continuous_gaussian_nll_mlx(
    pred: mx.array,
    target: mx.array,
    variance: float = 1.0,
) -> mx.array:
    """Gaussian negative log-likelihood with fixed variance in MLX."""
    target = mx.stop_gradient(target)
    sq_err = (pred - target) ** 2
    c = math.log(2.0 * math.pi * variance)
    return mx.mean(0.5 * (sq_err / variance + c))


def soft_cross_entropy_mlx(
    logits: mx.array,
    target_hist: mx.array,
) -> mx.array:
    """Soft-target cross-entropy from logits in MLX."""
    target_hist = mx.stop_gradient(target_hist)
    log_p = nn.log_softmax(logits, axis=-1)
    loss_per_item = -mx.sum(target_hist * log_p, axis=-1)
    return mx.mean(loss_per_item)


def idm_loss_mlx(
    logits: mx.array,
    target_actions: mx.array,
) -> mx.array:
    """Raw action IDM loss (Arm B and Arm C Layer 1) with explicit stop_gradient."""
    target_actions = mx.stop_gradient(target_actions)
    return soft_cross_entropy_mlx(logits, target_actions)


def idm2_loss_mlx(
    pred_7d: mx.array,
    target_7d: mx.array,
    variance: float = 1.0,
    weight_cat: float = 1.0,
) -> mx.array:
    """Composite Layer 2 IDM loss (continuous 3-dim NLL + soft cross-entropy 4-dim)."""
    target_7d = mx.stop_gradient(target_7d)
    l_cont = continuous_gaussian_nll_mlx(pred_7d[..., :3], target_7d[..., :3], variance=variance)
    l_cat = soft_cross_entropy_mlx(pred_7d[..., 3:], target_7d[..., 3:])
    return l_cont + weight_cat * l_cat


def multistep_latent_rollout_loss_mlx(
    arm_b_or_c_layer1: FlatJEPAArm | HierarchicalHJEPAArm,
    z0: mx.array,
    actions_onehot: mx.array,
    dts: mx.array,
    targets_z: mx.array,
) -> mx.array:
    """Compute H-step autoregressive rollout MSE loss in latent space."""
    H = actions_onehot.shape[0]
    z_curr = z0
    step_losses = []

    for t in range(H):
        a_t = actions_onehot[t]
        dt_t = dts[t : t + 1] if dts.ndim == 1 else dts[t]
        target_t = targets_z[t]
        z_next = arm_b_or_c_layer1.predict_l1_step(z_curr, a_t, dt_t)
        err = mx.mean((z_next - target_t) ** 2)
        step_losses.append(err)
        z_curr = z_next

    return mx.mean(mx.stack(step_losses))


def arm_a_loss_mlx(
    arm_a: FlatRSSMArm,
    obs_seq: mx.array,
    actions_onehot: mx.array,
    dts: mx.array,
) -> mx.array:
    """Compute Arm A total loss: observation reconstruction + KL (free bits 1.0) + latent overshooting."""
    if dts.ndim != 1:
        raise ValueError(f"arm_a_loss_mlx requires 1-D dts array of shape (L,), got {dts.shape}")
    T = obs_seq.shape[0]
    e1_feats = arm_a.encode(obs_seq)
    h_curr = mx.zeros((arm_a.dims["gru_hidden"],), dtype=mx.float32)

    recon_losses = []
    kl_losses = []
    overshoot_losses = []
    h_train_bound = int(spec.H_TRAIN)

    for t in range(T - 1):
        z_post_mean, z_post_logstd = arm_a.posterior(h_curr, e1_feats[t])
        # Reparameterization trick
        eps = mx.random.normal(z_post_mean.shape)
        z_sample = z_post_mean + mx.exp(z_post_logstd) * eps

        # Advance deterministic state
        gru_in = mx.concatenate([z_sample, actions_onehot[t], dts[t : t + 1]], axis=-1)
        h_next = arm_a.gru(gru_in, h_curr)

        # Prior at next step
        z_prior_mean, z_prior_logstd = arm_a.prior(h_next)
        z_next_post_mean, z_next_post_logstd = arm_a.posterior(h_next, e1_feats[t + 1])

        # Analytical KL divergence between diagonal Gaussians
        # KL(q || p) = sum(log(std_p / std_q) + (std_q^2 + (mu_q - mu_p)^2)/(2 * std_p^2) - 0.5)
        var_q = mx.exp(2.0 * z_next_post_logstd)
        var_p = mx.exp(2.0 * z_prior_logstd)
        kl_dim = (
            (z_prior_logstd - z_next_post_logstd)
            + (var_q + (z_next_post_mean - z_prior_mean) ** 2) / (2.0 * var_p)
            - 0.5
        )
        kl = mx.sum(kl_dim, axis=-1)
        kl_losses.append(kl)

        # Reconstruct observation at t+1 (one-step)
        obs_rec = arm_a.decode(h_next, z_next_post_mean)
        target_obs = obs_seq[t + 1]
        terrain_rec = obs_rec[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
        terrain_tgt = target_obs[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
        l_terrain = soft_cross_entropy_mlx(terrain_rec, terrain_tgt)
        l_coord = mx.mean((obs_rec[spec.TERRAIN_ONE_HOT_DIM:] - target_obs[spec.TERRAIN_ONE_HOT_DIM:]) ** 2)
        recon_losses.append(l_terrain + l_coord)

        # Latent overshooting: roll out using the prior p(z_{t+tau} | h_{t+tau}) for H_train steps
        h_roll = h_curr
        z_roll = z_sample
        max_overshoot_steps = min(h_train_bound, T - 1 - t)
        for tau in range(1, max_overshoot_steps + 1):
            tau_idx = t + tau
            act_idx = tau_idx - 1
            gru_in_roll = mx.concatenate([z_roll, actions_onehot[act_idx], dts[act_idx : act_idx + 1]], axis=-1)
            h_roll = arm_a.gru(gru_in_roll, h_roll)
            z_prior_roll, _ = arm_a.prior(h_roll)
            obs_rec_roll = arm_a.decode(h_roll, z_prior_roll)
            target_obs_roll = obs_seq[tau_idx]
            terrain_rec_roll = obs_rec_roll[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
            terrain_tgt_roll = target_obs_roll[:spec.TERRAIN_ONE_HOT_DIM].reshape(-1, spec.NUM_TERRAIN_CLASSES)
            l_t_roll = soft_cross_entropy_mlx(terrain_rec_roll, terrain_tgt_roll)
            l_c_roll = mx.mean((obs_rec_roll[spec.TERRAIN_ONE_HOT_DIM:] - target_obs_roll[spec.TERRAIN_ONE_HOT_DIM:]) ** 2)
            overshoot_losses.append(l_t_roll + l_c_roll)
            z_roll = z_prior_roll

        h_curr = h_next

    mean_recon = mx.mean(mx.stack(recon_losses))
    mean_kl = mx.mean(mx.stack(kl_losses))
    # Enforce free bits = 1.0 nat
    free_bits = float(spec.ARM_A_FREE_BITS)
    kl_penalized = mx.maximum(mean_kl, free_bits)

    if overshoot_losses:
        mean_overshoot = mx.mean(mx.stack(overshoot_losses))
    else:
        mean_overshoot = mx.array(0.0)

    # Weights: 1.0 for one-step reconstruction, 1.0 for overshooting (Appendix A)
    return mean_recon + kl_penalized + mean_overshoot


def make_arm_a_cost_fn(
    arm: FlatRSSMArm,
    counter: Any = None,
) -> Callable[[np.ndarray, np.ndarray], float]:
    """Arm A planning cost adapter compatible with flat_cem_plan(cost_fn=...).

    Evaluates candidate latent z_T against goal observation in observation space.
    If counter is provided, decoder forward calls are charged to counter.
    """
    def cost_fn(z_T: np.ndarray, goal_obs: np.ndarray) -> float:
        if counter is not None and hasattr(counter, "charge"):
            counter.charge("decode", 1)
        return arm.planning_cost(z_T, goal_obs)

    return cost_fn


# ==============================================================================
# 4. Parameter Counter
# ==============================================================================


def count_params(model: nn.Module) -> int:
    """Recursively sum size of all parameters in an MLX module.

    Must strictly equal param_count.py formulas for all three arms.
    """
    total = 0

    def _walk(obj: Any) -> None:
        nonlocal total
        if hasattr(obj, "size") and isinstance(obj.size, int):
            total += obj.size
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                _walk(v)
        elif isinstance(obj, nn.Module):
            _walk(obj.parameters())

    _walk(model)
    return total
