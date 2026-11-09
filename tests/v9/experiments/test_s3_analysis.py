"""S3 phase 1 statistics: bootstrap unit, gates, fail-closed behaviour."""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import analysis as G


def test_point_delta_is_exact_difference() -> None:
    ep = np.array([0, 0, 1, 1])
    a = np.array([1, 1, 1, 0], dtype=bool)
    b = np.array([0, 0, 1, 0], dtype=bool)
    r = G.paired_bootstrap_delta(ep, a, b, resamples=200)
    assert r["delta"] == pytest.approx(0.5)
    assert r["n_episodes"] == 2 and r["n_events"] == 4


def test_identical_arms_have_zero_interval() -> None:
    ep = np.arange(50).repeat(4)
    c = np.random.default_rng(0).random(200) < 0.5
    r = G.paired_bootstrap_delta(ep, c, c, resamples=500)
    assert r["delta"] == 0.0 and r["ci_low"] == 0.0 and r["ci_high"] == 0.0


def test_interval_widens_when_resampling_episodes_not_events() -> None:
    """Events inside an episode are perfectly correlated here: episode is the unit."""
    rng = np.random.default_rng(1)
    n_ep = 40
    ep = np.arange(n_ep).repeat(10)
    a = np.repeat(rng.random(n_ep) < 0.6, 10)
    b = np.zeros_like(a)
    r = G.paired_bootstrap_delta(ep, a, b, resamples=2000)
    width = r["ci_high"] - r["ci_low"]
    event_level_se = np.sqrt(a.mean() * (1 - a.mean()) / len(a))
    assert width > 3.92 * event_level_se * 2


def test_difference_gate_needs_both_size_and_interval() -> None:
    assert G.difference_gate({"delta": 0.2, "ci_low": 0.01}, 0.10)
    assert not G.difference_gate({"delta": 0.2, "ci_low": -0.01}, 0.10)
    assert not G.difference_gate({"delta": 0.05, "ci_low": 0.01}, 0.10)


def test_legality_fails_each_way() -> None:
    p = {"A0": 0.1, "O": 0.95, "N": 0.1}
    u = {"A2": 0.9, "A3": 0.9}
    assert all(G.legality(p, u, ("A2", "A3")).values())
    assert not G.legality({**p, "A0": 0.2}, u, ())["floor_A0"]
    assert not G.legality({**p, "O": 0.5}, u, ())["upper_O"]
    assert not G.legality({**p, "N": 0.2}, u, ())["negative_N"]
    assert not G.legality(p, {**u, "A3": 0.5}, ("A2", "A3"))["unswapped_A3"]


def test_empty_data_raises_instead_of_passing() -> None:
    with pytest.raises(ValueError):
        G.paired_bootstrap_delta(np.array([], dtype=int), np.array([], dtype=bool), np.array([], dtype=bool))
    with pytest.raises(ValueError):
        G.accuracy(np.array([True]), np.array([False]))


def test_missing_arm_raises() -> None:
    with pytest.raises(KeyError):
        G.legality({"A0": 0.1, "O": 0.95}, {}, ())
