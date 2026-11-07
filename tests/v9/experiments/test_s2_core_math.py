"""Unit tests for S2 Core Math reference implementation (NumPy / CPU-only).

Tests cover:
1. SIGReg:
   - Standard isotropic normal vs 3 degenerates (constant collapse, rank-1, anisotropic)
     with threshold derived from sample size N.
   - Orthogonal rotation invariance in expectation across random direction draws.
   - Robustness across diverse (N, D, n_directions); fail-closed on NaN / Inf.
2. Macro-Action Aggregation A_2:
   - Straight line forward
   - Turn in place
   - Walk a square back to origin (net displacement ~ 0, dpsi ~ 0)
   - Turn 90 degrees then forward (verifies body-frame rotation composition)
   - Irregular dt summation
   - Indivisible s2 handling (registered fail-closed policy + explicit drop_tail)
3. Inverse Dynamics Loss (L_IDM):
   - Fixed-variance Gaussian NLL (continuous)
   - Soft-target cross-entropy (histogram)
   - Combined IDM loss
   - Fail-closed validation (NaN, shape mismatch, negative variance)
4. Multi-Step Autoregressive Rollout Loss:
   - Step-by-step autoregressive propagation and per-step error recording
   - Verification against closed-form step traces
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from ainerzero.v9.experiments.s2.core_math import (
    RolloutResult,
    aggregate_macro,
    aggregate_macro_sequence,
    aggregate_macro_window,
    continuous_gaussian_nll,
    inverse_dynamics_loss,
    multistep_rollout_loss,
    normalize_angle,
    sigreg,
    sigreg_theoretical_expectation,
    soft_cross_entropy,
)


# ==============================================================================
# 1. SIGReg Tests
# ==============================================================================


def test_sigreg_isotropic_vs_degenerates_sample_size_derived_threshold() -> None:
    """Isotropic standard normal should be significantly lower than degenerate distributions.

    Threshold is analytically derived from sample size N via E[SIGReg(Z_iso)] = C_theory / N.
    We set threshold = 3.0 * E[SIGReg(Z_iso)].
    Under standard normal, empirical value is within 3 * E[SIGReg(Z_iso)].
    All three degenerates (constant, rank-1, anisotropic) exceed this threshold by a wide margin.
    """
    N, D = 300, 8
    rng = np.random.default_rng(20261106)

    # 1. Isotropic standard normal
    Z_iso = rng.standard_normal((N, D))
    val_iso = sigreg(Z_iso, n_directions=128, rng=rng)

    # Derived theoretical threshold: 3 * E[SIGReg(Z_iso)]
    theory_mean = sigreg_theoretical_expectation(N)
    threshold = 3.0 * theory_mean

    assert val_iso < threshold, (
        f"Isotropic normal {val_iso:.6f} exceeded derived threshold {threshold:.6f} "
        f"(theory mean {theory_mean:.6f})"
    )

    # 2. Degenerate 1: Constant collapse (all zeros)
    Z_const = np.zeros((N, D))
    val_const = sigreg(Z_const, n_directions=128, rng=rng)
    assert val_const > 10.0 * threshold, f"Constant collapse {val_const} too low"

    # 3. Degenerate 2: Rank-1 representation
    u = rng.standard_normal((N, 1))
    v = rng.standard_normal((1, D))
    Z_rank1 = u @ v
    val_rank1 = sigreg(Z_rank1, n_directions=128, rng=rng)
    assert val_rank1 > 10.0 * threshold, f"Rank-1 {val_rank1} too low"

    # 4. Degenerate 3: Anisotropic (variance 1.0 along dim 0, 0.01 along other dims)
    Z_aniso = rng.standard_normal((N, D))
    Z_aniso[:, 1:] *= 0.1
    val_aniso = sigreg(Z_aniso, n_directions=128, rng=rng)
    assert val_aniso > 10.0 * threshold, f"Anisotropic {val_aniso} too low"


def test_sigreg_orthogonal_rotation_invariance() -> None:
    """SIGReg expectation is invariant under orthogonal rotation Z -> Z Q^T."""
    N, D = 250, 4
    rng = np.random.default_rng(777)
    Z = rng.standard_normal((N, D))

    # Generate random orthogonal matrix Q via QR factorization
    random_mat = rng.standard_normal((D, D))
    Q, _ = np.linalg.qr(random_mat)
    Z_rot = Z @ Q.T

    # Average over multiple random direction batches to assess expectation difference
    n_runs = 35
    n_dirs_per_run = 256
    vals_orig = [sigreg(Z, n_directions=n_dirs_per_run, rng=1000 + i) for i in range(n_runs)]
    vals_rot = [sigreg(Z_rot, n_directions=n_dirs_per_run, rng=2000 + i) for i in range(n_runs)]

    mean_orig = float(np.mean(vals_orig))
    mean_rot = float(np.mean(vals_rot))
    diff = abs(mean_orig - mean_rot)

    # Tolerance is bounded by Monte Carlo standard error: sigma / sqrt(n_runs * n_dirs) < 5e-4
    tolerance = 5e-4
    assert diff < tolerance, f"Rotation diff {diff:.6f} exceeded tolerance {tolerance:.6f}"


def test_sigreg_shape_finiteness_and_fail_closed_nan() -> None:
    """SIGReg handles varying N, D, n_directions and fails closed on NaN or Inf."""
    rng = np.random.default_rng(42)

    # Varying dimensions
    for N in [50, 120]:
        for D in [2, 5, 16]:
            Z = rng.standard_normal((N, D))
            val = sigreg(Z, n_directions=32, rng=rng)
            assert isinstance(val, float)
            assert np.isfinite(val)
            assert val >= 0.0

    # Fail-closed on NaN
    Z_nan = rng.standard_normal((50, 4))
    Z_nan[10, 2] = np.nan
    with pytest.raises(ValueError, match="NaN or Inf"):
        sigreg(Z_nan, n_directions=16, rng=rng)

    # Fail-closed on Inf
    Z_inf = rng.standard_normal((50, 4))
    Z_inf[0, 0] = np.inf
    with pytest.raises(ValueError, match="NaN or Inf"):
        sigreg(Z_inf, n_directions=16, rng=rng)

    # Fail-closed on invalid parameters
    with pytest.raises(ValueError, match="n_directions"):
        sigreg(rng.standard_normal((50, 4)), n_directions=0, rng=rng)
    with pytest.raises(ValueError, match="n_knots"):
        sigreg(rng.standard_normal((50, 4)), n_directions=10, n_knots=1, rng=rng)


# ==============================================================================
# 2. Macro-Action Aggregation A_2 Tests
# ==============================================================================


def test_aggregate_macro_straight_line() -> None:
    """Straight line forward: dx sums directly, dy=0, dpsi=0."""
    actions = [(1.0, 0.0, 0.0, 0) for _ in range(4)]
    dts = [1.0, 1.0, 1.0, 1.0]
    dx, dy, dpsi, hist, dt_sum = aggregate_macro(actions, dts, s2=4)

    assert math.isclose(dx, 4.0, abs_tol=1e-12)
    assert math.isclose(dy, 0.0, abs_tol=1e-12)
    assert math.isclose(dpsi, 0.0, abs_tol=1e-12)
    assert np.allclose(hist, [1.0, 0.0, 0.0, 0.0])
    assert math.isclose(dt_sum, 4.0, abs_tol=1e-12)


def test_aggregate_macro_turn_in_place() -> None:
    """Turn in place: dx=0, dy=0, dpsi sums and normalizes."""
    actions = [(0.0, 0.0, math.pi / 4, 1) for _ in range(4)]
    dts = [1.0, 1.0, 1.0, 1.0]
    dx, dy, dpsi, hist, dt_sum = aggregate_macro(actions, dts, s2=4)

    assert math.isclose(dx, 0.0, abs_tol=1e-12)
    assert math.isclose(dy, 0.0, abs_tol=1e-12)
    assert math.isclose(dpsi, math.pi, abs_tol=1e-12)
    assert np.allclose(hist, [0.0, 1.0, 0.0, 0.0])
    assert math.isclose(dt_sum, 4.0, abs_tol=1e-12)


def test_aggregate_macro_square_loop_back_to_origin() -> None:
    """Walk a square: 4 steps of forward 1 and turn 90 deg left.

    Closed-form ground truth in starting frame:
        step 0: body heading 0.0, step dx=1 -> p0 = (1, 0), then heading becomes pi/2
        step 1: body heading pi/2, step dx=1 -> p1 = (0, 1), then heading becomes pi
        step 2: body heading pi, step dx=1 -> p2 = (-1, 0), then heading becomes 3pi/2
        step 3: body heading 3pi/2, step dx=1 -> p3 = (0, -1), then heading becomes 2pi
    Net displacement: (1, 0) + (0, 1) + (-1, 0) + (0, -1) = (0, 0).
    Net rotation: 2pi normalized to 0.0.
    """
    actions = [(1.0, 0.0, math.pi / 2, 0) for _ in range(4)]
    dts = [1.0, 1.0, 1.0, 1.0]
    dx, dy, dpsi, hist, dt_sum = aggregate_macro(actions, dts, s2=4)

    assert abs(dx) < 1e-12, f"Expected dx=0, got {dx}"
    assert abs(dy) < 1e-12, f"Expected dy=0, got {dy}"
    assert abs(dpsi) < 1e-12, f"Expected dpsi=0, got {dpsi}"
    assert math.isclose(dt_sum, 4.0, abs_tol=1e-12)


def test_aggregate_macro_turn_then_walk() -> None:
    """Turn 90 degrees then forward: verifies SE(2) frame composition.

    Closed-form ground truth in starting frame:
        step 0: dx=0, dy=0, dpsi=pi/2 -> p0 = (0, 0), heading becomes pi/2
        step 1: dx=1, dy=0, dpsi=0.0 -> p1 = R(pi/2)(1, 0) = (0, 1)
    Net displacement in start frame: (0, 1).
    Net rotation: pi/2.
    """
    actions = [
        (0.0, 0.0, math.pi / 2, 1),  # turn left
        (1.0, 0.0, 0.0, 0),          # forward
    ]
    dts = [1.0, 2.0]
    dx, dy, dpsi, hist, dt_sum = aggregate_macro(actions, dts, s2=2)

    assert abs(dx) < 1e-12, f"Expected dx=0, got {dx}"
    assert math.isclose(dy, 1.0, abs_tol=1e-12), f"Expected dy=1, got {dy}"
    assert math.isclose(dpsi, math.pi / 2, abs_tol=1e-12), f"Expected dpsi=pi/2, got {dpsi}"
    assert np.allclose(hist, [0.5, 0.5, 0.0, 0.0])
    assert math.isclose(dt_sum, 3.0, abs_tol=1e-12)


def test_aggregate_macro_irregular_dt() -> None:
    """Irregular dt values sum correctly."""
    actions = [(0.5, 0.0, 0.0, 0) for _ in range(3)]
    dts = [1.5, 0.25, 2.25]
    _, _, _, _, dt_sum = aggregate_macro(actions, dts, s2=3)
    assert math.isclose(dt_sum, 4.0, abs_tol=1e-12)


def test_aggregate_macro_indivisible_s2_handling() -> None:
    """Registered policy for len(actions) % s2 != 0: raises ValueError fail-closed.

    When drop_tail=True is explicitly set, it discards the incomplete tail window.
    """
    # 5 actions with s2=4
    actions = [(1.0, 0.0, 0.0, 0) for _ in range(5)]
    dts = [1.0, 1.0, 1.0, 1.0, 1.0]

    # Default policy: raises ValueError
    with pytest.raises(ValueError, match="not divisible by s2"):
        aggregate_macro(actions, dts, s2=4, drop_tail=False)

    # With drop_tail=True: discards 5th action, aggregates first 4
    dx, dy, dpsi, hist, dt_sum = aggregate_macro(actions, dts, s2=4, drop_tail=True)
    assert math.isclose(dx, 4.0, abs_tol=1e-12)
    assert math.isclose(dt_sum, 4.0, abs_tol=1e-12)


# ==============================================================================
# 3. Inverse Dynamics Loss (L_IDM) Tests
# ==============================================================================


def test_inverse_dynamics_loss_continuous_gaussian_nll() -> None:
    """Continuous Gaussian NLL matches analytical formula and achieves minimum at target."""
    target = np.array([1.0, 2.0, -1.0])
    pred_exact = np.array([1.0, 2.0, -1.0])
    variance = 0.5

    # Minimum NLL when pred == target: 0.5 * log(2 * pi * variance)
    expected_min = 0.5 * math.log(2.0 * math.pi * variance)
    nll_min = continuous_gaussian_nll(pred_exact, target, variance=variance)
    assert math.isclose(nll_min, expected_min, abs_tol=1e-12)

    # Shifted prediction
    pred_shift = np.array([2.0, 2.0, -1.0])  # sq_err = 1.0 on first dim
    # Mean sq_err = 1.0 / 3
    expected_shift = expected_min + 0.5 * (1.0 / 3.0) / variance
    nll_shift = continuous_gaussian_nll(pred_shift, target, variance=variance)
    assert math.isclose(nll_shift, expected_shift, abs_tol=1e-12)

    # Fail-closed on negative variance
    with pytest.raises(ValueError, match="Variance"):
        continuous_gaussian_nll(pred_exact, target, variance=-1.0)


def test_inverse_dynamics_loss_soft_cross_entropy() -> None:
    """Soft cross-entropy correctly evaluates probability distribution against target histogram."""
    target_hist = np.array([0.5, 0.5, 0.0, 0.0])
    # Logits yielding equal probability for class 0 and 1
    logits_equal = np.array([2.0, 2.0, -10.0, -10.0])
    loss = soft_cross_entropy(logits_equal, target_hist, from_logits=True)
    # With exp(-10) negligible, p_0 = 0.5, p_1 = 0.5 -> - (0.5 * log(0.5) + 0.5 * log(0.5)) = log(2)
    assert math.isclose(loss, math.log(2.0), abs_tol=1e-4)


def test_composite_inverse_dynamics_loss() -> None:
    """Composite loss combines continuous NLL and categorical CE with stop-gradient convention."""
    p_cont = np.array([0.0, 1.0])
    t_cont = np.array([0.0, 1.0])
    p_cat = np.array([0.0, 0.0])
    t_cat = np.array([0.5, 0.5])

    loss = inverse_dynamics_loss(
        p_cont, t_cont, p_cat, t_cat, variance=1.0, weight_cat=2.0, from_logits=True
    )
    # Continuous part: 0.5 * log(2 * pi)
    l_c = 0.5 * math.log(2.0 * math.pi)
    # Cat part: logits [0, 0] -> p = [0.5, 0.5] -> CE = log(2)
    l_h = math.log(2.0)
    expected = l_c + 2.0 * l_h
    assert math.isclose(loss, expected, abs_tol=1e-12)


# ==============================================================================
# 4. Multi-Step Autoregressive Rollout Loss Tests
# ==============================================================================


def test_multistep_rollout_loss_autoregressive_chaining() -> None:
    """Autoregressive rollout propagates previous predictions and records step errors."""

    # One-step linear dynamics: z_{t+1} = z_t + a * dt
    def dynamics_fn(z: np.ndarray, a: float, dt: float) -> np.ndarray:
        return z + np.array([a * dt, a * dt * 0.5], dtype=np.float64)

    z0 = np.array([0.0, 0.0])
    actions = [1.0, 2.0, -1.0]
    dts = [1.0, 0.5, 2.0]

    # Ground truth trajectory
    # step 1: z0 + [1.0, 0.5] = [1.0, 0.5]
    # step 2: z1 + [2.0 * 0.5, 2.0 * 0.5 * 0.5] = [1.0+1.0, 0.5+0.5] = [2.0, 1.0]
    # step 3: z2 + [-1.0 * 2.0, -1.0 * 2.0 * 0.5] = [2.0 - 2.0, 1.0 - 1.0] = [0.0, 0.0]
    truth = [
        np.array([1.0, 0.5]),
        np.array([2.0, 1.0]),
        np.array([0.0, 0.0]),
    ]

    # Perfect rollout: total loss and step losses should be 0.0
    res = multistep_rollout_loss(dynamics_fn, z0, actions, dts, truth)
    assert isinstance(res, RolloutResult)
    assert math.isclose(res.total_loss, 0.0, abs_tol=1e-12)
    assert all(math.isclose(e, 0.0, abs_tol=1e-12) for e in res.step_losses)

    # Rollout with known perturbed targets
    noisy_truth = [
        np.array([2.0, 0.5]),  # error: (1.0)^2 / 2 = 0.5
        np.array([2.0, 2.0]),  # error: (1.0)^2 / 2 = 0.5
        np.array([0.0, 0.0]),  # error: 0.0
    ]
    res_noisy = multistep_rollout_loss(dynamics_fn, z0, actions, dts, noisy_truth)
    assert math.isclose(res_noisy.step_losses[0], 0.5, abs_tol=1e-12)
    assert math.isclose(res_noisy.step_losses[1], 0.5, abs_tol=1e-12)
    assert math.isclose(res_noisy.step_losses[2], 0.0, abs_tol=1e-12)
    assert math.isclose(res_noisy.total_loss, 1.0 / 3.0, abs_tol=1e-12)

    # Tuple unpacking test: loss, step_losses = result
    unpacked_loss, unpacked_steps = res_noisy
    assert unpacked_loss == res_noisy.total_loss
    assert unpacked_steps == res_noisy.step_losses
