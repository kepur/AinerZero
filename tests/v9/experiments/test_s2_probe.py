"""Tests for S2 linear probe protocol (closed-form ridge regression).

Pure CPU, NumPy only.
"""

from __future__ import annotations

import inspect
import numpy as np
import pytest

from ainerzero.v9.experiments.s2.probe import (
    RidgeProbe,
    eval_error,
    fit_ridge,
    summarize_step_errors,
)

FROZEN_RECOVERY_ERROR_MAX = 0.35  # Grid cells max mean error on noisy recovery


def test_ridge_lambda_default_is_one() -> None:
    """λ default is strictly 1.0 per DESIGN-r2.md §5.

    Catches mutation P122-M4 (λ default mutated to 0.1).
    """
    sig = inspect.signature(fit_ridge)
    lam_param = sig.parameters["lam"]
    assert lam_param.default == 1.0, f"Expected default lam=1.0, got {lam_param.default}"

    # Verify fitted probe records lam=1.0 when called with default
    Z = np.ones((5, 4))
    XY = np.ones((5, 2))
    probe = fit_ridge(Z, XY)
    assert probe.lam == 1.0


def test_ridge_recovers_known_linear_mapping_with_noise() -> None:
    """Probe recovers true linear mapping (A @ Z + b) within frozen tolerance."""
    rng = np.random.default_rng(20261106)
    N = 1000
    D = 16
    target_dim = 2

    # Known ground truth mapping
    true_W = rng.normal(0.0, 1.0, size=(D, target_dim))
    true_b = np.array([12.5, 12.5], dtype=np.float64)

    # Random latent features Z
    Z_train = rng.normal(0.0, 1.0, size=(N, D))
    noise = rng.normal(0.0, 0.05, size=(N, target_dim))
    XY_train = Z_train @ true_W + true_b + noise

    # Fit probe with frozen lam=1.0
    probe = fit_ridge(Z_train, XY_train, lam=1.0, fit_intercept=True)

    # Test on unseen evaluation set
    N_test = 200
    Z_test = rng.normal(0.0, 1.0, size=(N_test, D))
    XY_test_clean = Z_test @ true_W + true_b

    metrics = eval_error(probe, Z_test, XY_test_clean)
    assert metrics["mean"] <= FROZEN_RECOVERY_ERROR_MAX, (
        f"Mean recovery error {metrics['mean']:.4f} exceeds frozen threshold {FROZEN_RECOVERY_ERROR_MAX}"
    )


def test_summarize_step_errors() -> None:
    """Auxiliary function correctly computes error across specified observation steps."""
    rng = np.random.default_rng(999)
    D = 8
    W = rng.normal(0.0, 0.5, size=(D, 2))
    b = np.array([5.0, 5.0])
    probe = RidgeProbe(weights=W, bias=b, lam=1.0, fit_intercept=True)

    n_episodes = 5
    T = 65
    latents = rng.normal(0.0, 1.0, size=(n_episodes, T, D))
    coords = np.zeros((n_episodes, T, 2))
    for ep in range(n_episodes):
        coords[ep] = latents[ep] @ W + b

    step_results = summarize_step_errors(probe, latents, coords, steps=(1, 5, 10, 30, 60))
    for s in (1, 5, 10, 30, 60):
        assert s in step_results
        # Under exact alignment, error should be virtually 0
        assert step_results[s] < 1e-10
