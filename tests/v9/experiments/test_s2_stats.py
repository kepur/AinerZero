"""Tests for S2 statistical framework (clustered paired bootstrap and power).

Pure CPU, NumPy only.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s2.stats import (
    cluster_paired_bootstrap,
    power_estimate,
    unclustered_paired_bootstrap,
)

FROZEN_ICC_WIDTH_RATIO_MIN = 1.35


def test_single_world_raises_value_error() -> None:
    """Assertion: at least 2 worlds required; does not silently degrade to 1-world unclustered."""
    with pytest.raises(ValueError, match="at least 2 worlds"):
        cluster_paired_bootstrap([[0.1, 0.2, 0.15]])

    with pytest.raises(ValueError, match="at least 2 worlds"):
        cluster_paired_bootstrap(np.array([[0.1, 0.2, 0.15]]))


def test_cluster_bootstrap_coverage_no_cluster_effect() -> None:
    """Coverage of 95% CI across 200 repetitions falls within [0.90, 0.99] when ICC=0."""
    rng = np.random.default_rng(20261106)
    true_diff = 0.10
    n_worlds = 12
    m_per_world = 6
    n_reps = 200
    n_boot = 500

    covered_count = 0

    for rep in range(n_reps):
        rep_rng = np.random.default_rng(int(rng.integers(0, 2**31 - 1)))
        # No cluster effect (ICC=0): independent Gaussian noise across all episodes
        diffs = true_diff + rep_rng.normal(0.0, 0.20, size=(n_worlds, m_per_world))
        res = cluster_paired_bootstrap(diffs, n_boot=n_boot, rng=rep_rng)
        if res.ci_lower <= true_diff <= res.ci_upper:
            covered_count += 1

    coverage = covered_count / n_reps
    assert 0.90 <= coverage <= 0.99, (
        f"Bootstrap coverage {coverage:.3f} outside expected [0.90, 0.99] for 95% nominal CI"
    )


def test_cluster_bootstrap_width_with_strong_cluster_effect() -> None:
    """When ICC=0.5, clustered CI width is significantly wider than unclustered CI width.

    A priori frozen lower bound: FROZEN_ICC_WIDTH_RATIO_MIN = 1.35.
    Catches mutation P122-M1 (unclustered bootstrap in cluster_paired_bootstrap).
    """
    rng = np.random.default_rng(42)
    n_worlds = 25
    m_per_world = 8
    true_diff = 0.10
    icc = 0.50

    # Cluster-level variance sigma_u^2 = 0.5, episode-level variance sigma_e^2 = 0.5
    u = rng.normal(0.0, np.sqrt(icc), size=(n_worlds, 1))
    e = rng.normal(0.0, np.sqrt(1.0 - icc), size=(n_worlds, m_per_world))
    diffs = true_diff + u + e

    clustered = cluster_paired_bootstrap(diffs, n_boot=3000, rng=rng)
    unclustered = unclustered_paired_bootstrap(diffs, n_boot=3000, rng=rng)

    ratio = clustered.ci_width / unclustered.ci_width
    assert ratio >= FROZEN_ICC_WIDTH_RATIO_MIN, (
        f"Clustered CI width {clustered.ci_width:.4f} vs unclustered {unclustered.ci_width:.4f}: "
        f"ratio {ratio:.4f} < frozen threshold {FROZEN_ICC_WIDTH_RATIO_MIN}"
    )


def test_power_estimate_runs_and_returns_reasonable_power() -> None:
    """Power estimate runs simulation without error and produces probability in [0, 1]."""
    rng = np.random.default_rng(12345)
    power = power_estimate(
        effect=0.15,
        p_base=0.30,
        icc=0.10,
        n_worlds=10,
        m_per_world=5,
        n_sim=30,
        n_boot=200,
        rng=rng,
    )
    assert 0.0 <= power <= 1.0
    # With positive effect 0.15 and reasonable sample size, power should be strictly positive
    assert power > 0.0
