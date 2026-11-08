"""S2 Core Math reference implementation (NumPy only, CPU-only).

Mathematical components:
1. SIGReg (Sketched Isotropic Gaussian Regularizer):
   Based on LeJEPA paper (arXiv:2511.08544, Balestriero & LeCun 2025), Section 3.2.
   Epps-Pulley normality test statistic (Epps & Pulley, 1983) applied over random
   1D Cramér-Wold unit projections on S^{D-1}.
   NOTE: Written strictly from mathematical descriptions; the LeJEPA repository
   (CC BY-NC 4.0) was NOT opened, inspected, or referenced in implementation.

2. Inverse Dynamics Loss (L_IDM):
   Continuous action components: fixed-variance Gaussian negative log-likelihood.
   Categorical histogram components: soft-target cross-entropy.
   Convention per ARCHITECTURE_V9 §4 Eq. 4: targets are treated as stop-gradient constants sg(a).

3. Macro-Action Aggregation A_2:
   Rigorous SE(2) composition of local body-frame displacements across s2 steps:
   p = \\sum_i R(\\psi_i - \\psi_t) d_i
   dpsi normalized to (-pi, pi].
   dt_sum is exact sum of non-uniform dts.
   Registered policy for length not divisible by s2: raises ValueError (fail-closed)
   unless drop_tail=True is explicitly specified.

4. Multi-Step Autoregressive Rollout Loss:
   Simulates H-step autoregressive rollout f(z_{t-1}, a, dt) against ground-truth
   targets and returns per-step loss trace and aggregate loss.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np


# ==============================================================================
# 1. SIGReg (Sketched Isotropic Gaussian Regularizer)
# ==============================================================================


def sigreg_theoretical_expectation(
    n_samples: int,
    n_knots: int = 17,
    t_min: float = 0.2,
    t_max: float = 4.0,
) -> float:
    """Theoretical expectation of SIGReg for standard isotropic normal N(0, I_D).

    For any unit vector a in S^{D-1}, if Z ~ N(0, I_D), then X = Z @ a ~ N(0, 1).
    For each knot t_k:
        E[cos(t_k X)] = exp(-t_k^2 / 2) = phi_0(t_k)
        E[sin(t_k X)] = 0
        Var(cos(t_k X)) + Var(sin(t_k X)) = 1 - exp(-t_k^2)
        E[|phi_N(t_k) - phi_0(t_k)|^2] = (1 - exp(-t_k^2)) / N
    Therefore:
        E[SIGReg(Z)] = (1 / N) * \\sum_k W_k * (1 - exp(-t_k^2))
    where W_k = omega_k * exp(-t_k^2 / 2) with trapezoidal quadrature weights omega_k.
    """
    if n_samples < 1:
        raise ValueError(f"n_samples must be >= 1, got {n_samples}")
    if n_knots < 2:
        raise ValueError(f"n_knots must be >= 2, got {n_knots}")

    knots = np.linspace(t_min, t_max, n_knots, dtype=np.float64)
    dt = (t_max - t_min) / (n_knots - 1)
    trapz_weights = np.full(n_knots, dt, dtype=np.float64)
    trapz_weights[0] *= 0.5
    trapz_weights[-1] *= 0.5

    gaussian_window = np.exp(-0.5 * (knots**2))
    quad_weights = trapz_weights * gaussian_window

    c_theory = np.sum(quad_weights * (1.0 - np.exp(-(knots**2))))
    return float(c_theory / n_samples)


def generate_sigreg_directions(
    n_directions: int,
    dim: int,
    rng: np.random.Generator | np.random.RandomState | int | None = 42,
) -> np.ndarray:
    """Generate unit projection directions uniformly sampled on S^{dim-1} (shared by NumPy and MLX)."""
    if rng is None:
        random_gen = np.random.default_rng()
    elif isinstance(rng, (int, np.integer)):
        random_gen = np.random.default_rng(int(rng))
    elif isinstance(rng, (np.random.Generator, np.random.RandomState)):
        random_gen = rng
    else:
        raise TypeError(f"Unsupported rng type: {type(rng)}")

    if isinstance(random_gen, np.random.Generator):
        raw_dirs = random_gen.standard_normal((n_directions, dim)).astype(np.float32)
    else:
        raw_dirs = random_gen.randn(n_directions, dim).astype(np.float32)

    norms = np.linalg.norm(raw_dirs, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (raw_dirs / norms).astype(np.float32)


def sigreg(
    Z: np.ndarray | Sequence[Any],
    n_directions: int,
    rng: np.random.Generator | np.random.RandomState | int | None = None,
    n_knots: int = 17,
    t_min: float = 0.2,
    t_max: float = 4.0,
) -> float:
    """Compute SIGReg (Sketched Isotropic Gaussian Regularizer) per LeJEPA §3.2.

    Parameters
    ----------
    Z : array-like of shape (N, D)
        Representations batch.
    n_directions : int
        Number of random projection slices sampled uniformly on S^{D-1}.
    rng : np.random.Generator, np.random.RandomState, int, or None
        Random generator for reproducible direction sampling.
    n_knots : int, default=17
        Number of quadrature knots in [t_min, t_max].
    t_min : float, default=0.2
        Lower integration limit in frequency space.
    t_max : float, default=4.0
        Upper integration limit in frequency space.

    Returns
    -------
    float
        Average Epps-Pulley test statistic across sampled directions.
    """
    Z_arr = np.asarray(Z, dtype=np.float64)
    if Z_arr.ndim != 2:
        raise ValueError(f"Z must be 2D array of shape (N, D), got shape {Z_arr.shape}")
    N, D = Z_arr.shape
    if N < 1 or D < 1:
        raise ValueError(f"Z dimensions must be positive, got N={N}, D={D}")
    if not np.all(np.isfinite(Z_arr)):
        raise ValueError("Z contains NaN or Inf (fail-closed)")
    if n_directions < 1:
        raise ValueError(f"n_directions must be >= 1, got {n_directions}")
    if n_knots < 2:
        raise ValueError(f"n_knots must be >= 2, got {n_knots}")
    if t_min >= t_max:
        raise ValueError(f"t_min ({t_min}) must be < t_max ({t_max})")

    # Sample n_directions on S^{D-1} using shared direction generator
    dirs = generate_sigreg_directions(n_directions, D, rng=rng)

    # 1D projected embeddings: X shape (N, M)
    X = Z_arr @ dirs.T  # (N, M)

    # Quadrature knots and weights
    knots = np.linspace(t_min, t_max, n_knots, dtype=np.float64)  # (K,)
    dt = (t_max - t_min) / (n_knots - 1)
    trapz_weights = np.full(n_knots, dt, dtype=np.float64)
    trapz_weights[0] *= 0.5
    trapz_weights[-1] *= 0.5

    # Target characteristic function for standard normal N(0, 1): phi_0(t) = exp(-0.5 * t^2)
    phi_0 = np.exp(-0.5 * (knots**2))  # (K,)
    # Gaussian kernel weight w(t) = exp(-0.5 * t^2)
    w_t = np.exp(-0.5 * (knots**2))
    quad_weights = trapz_weights * w_t  # (K,)

    # Compute empirical characteristic function over projected data
    # knots shape (K, 1, 1), X shape (1, N, M) -> t_X shape (K, N, M)
    t_X = knots[:, None, None] * X[None, :, :]
    mean_cos = np.mean(np.cos(t_X), axis=1)  # (K, M)
    mean_sin = np.mean(np.sin(t_X), axis=1)  # (K, M)

    # Squared discrepancy |phi_N(t) - phi_0(t)|^2
    diff_cos = mean_cos - phi_0[:, None]  # (K, M)
    sq_diff = (diff_cos**2) + (mean_sin**2)  # (K, M)

    # Weighted integral over knots for each direction: (M,)
    t_stat = np.sum(quad_weights[:, None] * sq_diff, axis=0)

    # Average over all random unit directions
    return float(np.mean(t_stat))


def compute_sigreg_numpy(
    Z: np.ndarray | Sequence[Any],
    n_directions: int = 16,
    rng: np.random.Generator | np.random.RandomState | int | None = 42,
) -> float:
    """Convenience alias for sigreg on NumPy arrays."""
    return float(sigreg(Z, n_directions=n_directions, rng=rng))


# ==============================================================================
# 2. Inverse Dynamics Loss (L_IDM)
# ==============================================================================


def continuous_gaussian_nll(
    pred: np.ndarray | Sequence[Any],
    target: np.ndarray | Sequence[Any],
    variance: float | np.ndarray = 1.0,
    reduction: str = "mean",
) -> float:
    """Compute Gaussian negative log-likelihood with fixed variance.

    Convention: target is treated as a stop-gradient constant sg(a).
    Formula:
        NLL = 0.5 * ((pred - target)^2 / variance + log(2 * pi * variance))
    """
    pred_arr = np.asarray(pred, dtype=np.float64)
    target_arr = np.asarray(target, dtype=np.float64)
    if pred_arr.shape != target_arr.shape:
        raise ValueError(
            f"Shape mismatch: pred {pred_arr.shape} vs target {target_arr.shape}"
        )
    if not np.all(np.isfinite(pred_arr)) or not np.all(np.isfinite(target_arr)):
        raise ValueError("Inputs contain NaN or Inf")

    var_arr = np.asarray(variance, dtype=np.float64)
    if np.any(var_arr <= 0.0):
        raise ValueError(f"Variance must be strictly positive, got {variance}")

    sq_err = (pred_arr - target_arr) ** 2
    nll = 0.5 * (sq_err / var_arr + np.log(2.0 * math.pi * var_arr))

    if reduction == "mean":
        return float(np.mean(nll))
    elif reduction == "sum":
        return float(np.sum(nll))
    elif reduction == "none":
        return float(np.squeeze(nll))
    else:
        raise ValueError(f"Unknown reduction: {reduction}")


def soft_cross_entropy(
    pred: np.ndarray | Sequence[Any],
    target_hist: np.ndarray | Sequence[Any],
    from_logits: bool = True,
    eps: float = 1e-12,
    reduction: str = "mean",
) -> float:
    """Compute soft-target cross entropy for categorical action histograms.

    Convention: target_hist is treated as a stop-gradient constant sg(a).
    Formula:
        loss = - \\sum_c target_c * log(p_c)
    """
    pred_arr = np.asarray(pred, dtype=np.float64)
    target_arr = np.asarray(target_hist, dtype=np.float64)
    if pred_arr.shape != target_arr.shape:
        raise ValueError(
            f"Shape mismatch: pred {pred_arr.shape} vs target {target_arr.shape}"
        )
    if not np.all(np.isfinite(pred_arr)) or not np.all(np.isfinite(target_arr)):
        raise ValueError("Inputs contain NaN or Inf")
    if np.any(target_arr < 0.0):
        raise ValueError("target_hist must have non-negative entries")

    if from_logits:
        # Numerically stable log_softmax: l_c - logsumexp(l)
        max_logits = np.max(pred_arr, axis=-1, keepdims=True)
        shifted = pred_arr - max_logits
        logsumexp = max_logits + np.log(np.sum(np.exp(shifted), axis=-1, keepdims=True))
        log_p = pred_arr - logsumexp
    else:
        p = np.clip(pred_arr, eps, 1.0)
        p = p / np.sum(p, axis=-1, keepdims=True)
        log_p = np.log(p)

    loss_per_item = -np.sum(target_arr * log_p, axis=-1)
    if reduction == "mean":
        return float(np.mean(loss_per_item))
    elif reduction == "sum":
        return float(np.sum(loss_per_item))
    elif reduction == "none":
        return float(np.squeeze(loss_per_item))
    else:
        raise ValueError(f"Unknown reduction: {reduction}")


def inverse_dynamics_loss(
    pred_cont: np.ndarray | Sequence[Any],
    target_cont: np.ndarray | Sequence[Any],
    pred_cat: np.ndarray | Sequence[Any],
    target_cat: np.ndarray | Sequence[Any],
    variance: float | np.ndarray = 1.0,
    weight_cat: float = 1.0,
    from_logits: bool = True,
) -> float:
    """Composite inverse dynamics loss per ARCHITECTURE_V9 §4 Eq. 4.

    Targets (target_cont, target_cat) are treated as stop-gradient constants sg(a).
    Combines Gaussian continuous negative log-likelihood with soft categorical cross entropy.
    """
    l_cont = continuous_gaussian_nll(pred_cont, target_cont, variance=variance)
    l_cat = soft_cross_entropy(pred_cat, target_cat, from_logits=from_logits)
    return float(l_cont + weight_cat * l_cat)


# ==============================================================================
# 3. Macro-Action Aggregation A_2 (SE(2) Composition)
# ==============================================================================


def normalize_angle(theta: float | np.ndarray) -> float | np.ndarray:
    """Normalize angle to (-pi, pi]."""
    # (theta + pi) % (2 * pi) - pi
    # Guard against float rounding placing pi into -pi
    res = (np.asarray(theta, dtype=np.float64) + math.pi) % (2.0 * math.pi) - math.pi
    # In Python/NumPy, modulo of negative can touch -pi; ensure strict (-pi, pi]
    if isinstance(res, np.ndarray):
        res = np.where(res <= -math.pi, math.pi, res)
    else:
        if res <= -math.pi:
            res = math.pi
    return res


def actions_to_tuples(actions: np.ndarray | Sequence[Any]) -> list[tuple[float, float, float, int]]:
    """Convert one-hot actions or action indices into (dx, dy, dpsi, cat) tuples."""
    tuples = []
    for a in actions:
        if isinstance(a, (int, np.integer)):
            cat = int(a)
        elif isinstance(a, (list, tuple, np.ndarray)):
            arr = np.asarray(a)
            if arr.ndim == 1 and arr.shape[0] == 4 and np.all((arr == 0) | (arr == 1)) and np.isclose(np.sum(arr), 1.0):
                cat = int(np.argmax(arr))
            elif len(a) >= 4:
                tuples.append((float(a[0]), float(a[1]), float(a[2]), int(a[3])))
                continue
            else:
                cat = int(arr.item())
        else:
            raise TypeError(f"Unsupported action type: {type(a)}")

        if cat == 0:
            tuples.append((1.0, 0.0, 0.0, 0))
        elif cat == 1:
            tuples.append((0.0, 0.0, math.pi / 2, 1))
        elif cat == 2:
            tuples.append((0.0, 0.0, -math.pi / 2, 2))
        elif cat == 3:
            tuples.append((0.0, 0.0, 0.0, 3))
        else:
            raise ValueError(f"Action category {cat} out of range [0, 3]")
    return tuples


def aggregate_macro_window(
    actions: Sequence[Any] | np.ndarray,
    dts: Sequence[float | int] | np.ndarray,
    n_categories: int = 4,
) -> tuple[float, float, float, np.ndarray, float]:
    """Aggregate a single window of actions using exact SE(2) composition.

    Parameters
    ----------
    actions : sequence of actions
        Each action must provide (dx, dy, dpsi, cat_id).
    dts : sequence of float
        Time step durations.
    n_categories : int, default=4
        Total number of discrete action categories for histogram.

    Returns
    -------
    dx : float
        Net displacement x in initial body frame t.
    dy : float
        Net displacement y in initial body frame t.
    dpsi : float
        Net rotation normalized to (-pi, pi].
    hist : np.ndarray of shape (n_categories,)
        Normalized category histogram (sums to 1.0).
    dt_sum : float
        Total duration.
    """
    n_steps = len(actions)
    if n_steps == 0:
        raise ValueError("Cannot aggregate empty actions window")
    if len(dts) != n_steps:
        raise ValueError(f"dts length ({len(dts)}) must match actions length ({n_steps})")

    # Extract components
    dx_list: list[float] = []
    dy_list: list[float] = []
    dpsi_list: list[float] = []
    cat_list: list[int] = []

    for a in actions:
        if isinstance(a, (int, np.integer)):
            cat = int(a)
            if cat == 0:
                dx_list.append(1.0); dy_list.append(0.0); dpsi_list.append(0.0); cat_list.append(0)
            elif cat == 1:
                dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(math.pi / 2); cat_list.append(1)
            elif cat == 2:
                dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(-math.pi / 2); cat_list.append(2)
            elif cat == 3:
                dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(0.0); cat_list.append(3)
            else:
                raise ValueError(f"Action category {cat} out of range [0, 3]")
        elif isinstance(a, (list, tuple, np.ndarray)):
            arr = np.asarray(a)
            if arr.ndim == 1 and arr.shape[0] == 4 and np.all((arr == 0) | (arr == 1)) and np.isclose(np.sum(arr), 1.0):
                cat = int(np.argmax(arr))
                if cat == 0:
                    dx_list.append(1.0); dy_list.append(0.0); dpsi_list.append(0.0); cat_list.append(0)
                elif cat == 1:
                    dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(math.pi / 2); cat_list.append(1)
                elif cat == 2:
                    dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(-math.pi / 2); cat_list.append(2)
                elif cat == 3:
                    dx_list.append(0.0); dy_list.append(0.0); dpsi_list.append(0.0); cat_list.append(3)
                else:
                    raise ValueError(f"Action category {cat} out of range [0, 3]")
            else:
                if len(a) < 4:
                    raise ValueError(f"Action tuple must have >= 4 elements (dx, dy, dpsi, cat), got {a}")
                dx_list.append(float(a[0]))
                dy_list.append(float(a[1]))
                dpsi_list.append(float(a[2]))
                cat_list.append(int(a[3]))
        elif isinstance(a, dict):
            dx_list.append(float(a.get("dx", a.get("d_x", 0.0))))
            dy_list.append(float(a.get("dy", a.get("d_y", 0.0))))
            dpsi_list.append(float(a.get("dpsi", a.get("d_psi", 0.0))))
            cat_list.append(int(a.get("cat", a.get("category", a.get("cat_id", 0)))))
        else:
            raise TypeError(f"Unsupported action representation: {type(a)}")

    # SE(2) composition:
    # Let initial body frame heading at start of window be psi_0 = 0.
    # At step i (i >= 0), heading before step i is psi_i = sum_{j=0}^{i-1} dpsi_j (psi_0 = 0).
    # Step displacement (dx_i, dy_i) is in body frame at start of step i.
    # Transformed to window start frame:
    # [p_x] = [cos(psi_i)  -sin(psi_i)] [dx_i]
    # [p_y]   [sin(psi_i)   cos(psi_i)] [dy_i]
    total_x = 0.0
    total_y = 0.0
    current_psi = 0.0

    for i in range(n_steps):
        cos_p = math.cos(current_psi)
        sin_p = math.sin(current_psi)
        d_x = dx_list[i]
        d_y = dy_list[i]

        total_x += cos_p * d_x - sin_p * d_y
        total_y += sin_p * d_x + cos_p * d_y

        current_psi += dpsi_list[i]

    # Total heading change normalized to (-pi, pi]
    dpsi_norm = float(normalize_angle(current_psi))

    # Normalized action histogram
    hist = np.zeros(n_categories, dtype=np.float64)
    for c in cat_list:
        if 0 <= c < n_categories:
            hist[c] += 1.0
        else:
            raise ValueError(f"Category id {c} out of range [0, {n_categories - 1}]")
    hist /= float(n_steps)

    dt_sum = float(sum(dts))
    return float(total_x), float(total_y), dpsi_norm, hist, dt_sum


def aggregate_macro_sequence(
    actions: Sequence[Any] | np.ndarray,
    dts: Sequence[float | int] | np.ndarray,
    s2: int,
    n_categories: int = 4,
    drop_tail: bool = False,
) -> list[tuple[float, float, float, np.ndarray, float]]:
    """Aggregate a sequence of actions into successive s2-length macro actions."""
    if s2 <= 0:
        raise ValueError(f"s2 must be strictly positive, got {s2}")
    n_total = len(actions)
    if len(dts) != n_total:
        raise ValueError(f"dts length ({len(dts)}) must match actions length ({n_total})")

    remainder = n_total % s2
    if remainder != 0:
        if not drop_tail:
            raise ValueError(
                f"Number of actions ({n_total}) is not divisible by s2 ({s2}). "
                f"Registered policy fails closed unless drop_tail=True is explicitly set."
            )
        valid_len = n_total - remainder
    else:
        valid_len = n_total

    results = []
    for start in range(0, valid_len, s2):
        window_actions = actions[start : start + s2]
        window_dts = dts[start : start + s2]
        res = aggregate_macro_window(window_actions, window_dts, n_categories=n_categories)
        results.append(res)
    return results


def aggregate_macro(
    actions: Sequence[Any] | np.ndarray,
    dts: Sequence[float | int] | np.ndarray,
    s2: int,
    n_categories: int = 4,
    drop_tail: bool = False,
) -> tuple[float | np.ndarray, float | np.ndarray, float | np.ndarray, np.ndarray, float | np.ndarray]:
    """Aggregate raw actions into macro action A_2 per ARCHITECTURE_V9 §4 Eq. 3.

    Interface: aggregate_macro(actions, dts, s2) -> (dx, dy, dpsi, hist, dt_sum)
    - If len(actions) == s2: returns a single 5-tuple of (dx, dy, dpsi, hist, dt_sum).
    - If len(actions) % s2 != 0:
        Registered policy: raises ValueError (fail-closed) by default;
        if drop_tail=True is set, truncates the tail remainder.
    - If len(actions) > s2 and divisible:
        returns batched 5-tuple where dx, dy, dpsi, dt_sum are 1D arrays of length K,
        and hist is 2D array of shape (K, n_categories).
    """
    seq = aggregate_macro_sequence(
        actions, dts, s2=s2, n_categories=n_categories, drop_tail=drop_tail
    )
    if len(seq) == 0:
        raise ValueError("No complete macro windows after aggregation")
    if len(seq) == 1:
        return seq[0]

    # Batched return
    dx_arr = np.array([item[0] for item in seq], dtype=np.float64)
    dy_arr = np.array([item[1] for item in seq], dtype=np.float64)
    dpsi_arr = np.array([item[2] for item in seq], dtype=np.float64)
    hist_arr = np.stack([item[3] for item in seq], axis=0)
    dt_arr = np.array([item[4] for item in seq], dtype=np.float64)
    return dx_arr, dy_arr, dpsi_arr, hist_arr, dt_arr


# ==============================================================================
# 4. Multi-Step Autoregressive Rollout Loss
# ==============================================================================


@dataclass(frozen=True)
class RolloutResult:
    """Result of multi-step autoregressive rollout evaluation."""

    total_loss: float
    step_losses: list[float]
    predictions: np.ndarray

    def __iter__(self):
        # Support tuple unpacking: loss, step_losses = result
        yield self.total_loss
        yield self.step_losses


def multistep_rollout_loss(
    f: Callable[[np.ndarray, Any, float], np.ndarray],
    z0: np.ndarray | Sequence[Any],
    actions: Sequence[Any] | np.ndarray,
    dts: Sequence[float | int] | np.ndarray,
    targets: Sequence[Any] | np.ndarray,
    loss_fn: Callable[[np.ndarray, np.ndarray], float] | None = None,
) -> RolloutResult:
    """Compute H-step autoregressive rollout loss against ground-truth targets.

    Parameters
    ----------
    f : callable (z_{h-1}, a_{h-1}, dt_{h-1}) -> z_h
        One-step forward dynamics prediction function.
    z0 : array-like of shape (D,) or (B, D)
        Initial latent representation at t=0.
    actions : sequence of length H
        Action sequence for steps 0 to H-1.
    dts : sequence of length H
        Time duration sequence for steps 0 to H-1.
    targets : sequence or array of length H
        Ground truth latent states for steps 1 to H.
    loss_fn : callable (pred_z, target_z) -> float, optional
        Custom loss function. Defaults to mean squared error (MSE).

    Returns
    -------
    RolloutResult
        Named container with total_loss, per-step losses list, and predictions array.
    """
    H = len(actions)
    if H == 0:
        raise ValueError("actions sequence cannot be empty")
    if len(dts) != H:
        raise ValueError(f"dts length ({len(dts)}) must match actions length ({H})")
    if len(targets) != H:
        raise ValueError(f"targets length ({len(targets)}) must match actions length ({H})")

    if loss_fn is None:

        def default_mse(p: np.ndarray, t: np.ndarray) -> float:
            return float(np.mean((p - t) ** 2))

        step_loss_calc = default_mse
    else:
        step_loss_calc = loss_fn

    z_curr = np.asarray(z0, dtype=np.float64)
    pred_list: list[np.ndarray] = []
    step_losses: list[float] = []

    for h in range(H):
        a_h = actions[h]
        dt_h = float(dts[h])
        target_h = np.asarray(targets[h], dtype=np.float64)

        z_next = f(z_curr, a_h, dt_h)
        z_next_arr = np.asarray(z_next, dtype=np.float64)
        if not np.all(np.isfinite(z_next_arr)):
            raise ValueError(f"Non-finite prediction encountered at rollout step {h}")

        err = float(step_loss_calc(z_next_arr, target_h))
        step_losses.append(err)
        pred_list.append(z_next_arr)

        # Autoregressive chaining: predicted state becomes next input
        z_curr = z_next_arr

    total_loss = float(np.mean(step_losses))
    preds_arr = np.stack(pred_list, axis=0)

    return RolloutResult(
        total_loss=total_loss,
        step_losses=step_losses,
        predictions=preds_arr,
    )
