"""S4 phase 1: Hungarian assignment, the ensemble Kalman tracker, hand models and metrics. CPU only."""

from __future__ import annotations

import hashlib
import itertools
import json

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4.assign import hungarian

NS = "test-s4-filter"


# --- assignment ----------------------------------------------------------------------------------
@pytest.mark.parametrize("shape", [(1, 1), (3, 3), (2, 5), (5, 2), (6, 6)])
def test_hungarian_is_optimal(shape) -> None:
    rng = np.random.default_rng(sum(shape))
    for _ in range(20):
        C = rng.random(shape) * 10
        got = hungarian(C)
        nr, nc = shape
        assert len(got) == min(nr, nc) and len({r for r, _ in got}) == len(got) and len({c for _, c in got}) == len(got)
        if nr <= nc:
            opt = min(sum(C[r, p[r]] for r in range(nr)) for p in itertools.permutations(range(nc), nr))
        else:
            opt = min(sum(C[p[c], c] for c in range(nc)) for p in itertools.permutations(range(nr), nc))
        assert sum(C[r, c] for r, c in got) == pytest.approx(opt)


def test_hungarian_edge_cases() -> None:
    assert hungarian(np.zeros((0, 3))) == [] and hungarian(np.zeros((2, 0))) == []
    with pytest.raises(ValueError):
        hungarian(np.array([[np.inf]]))
    assert hungarian(np.array([[0.0, 0.0], [0.0, 0.0]])) in ([(0, 0), (1, 1)], [(0, 1), (1, 0)])


# --- hand models ------------------------------------------------------------------------------
def test_hand_models() -> None:
    ep = W.generate_episode(NS, 0, 6, steps=1)
    s = ep.steps[0]
    P, V = s.positions[None], s.velocities[None]
    p, v = Mo.constant_velocity(P, V, ep.pillars)
    assert np.array_equal(p, P + V * W.DT) and np.array_equal(v, V)
    assert all(np.array_equal(a, b) for a, b in zip(Mo.bounce(P, V, ep.pillars), W.physics(P, V, ep.pillars, disks=False)[:2]))
    assert all(np.array_equal(a, b) for a, b in zip(Mo.true_physics(P, V, ep.pillars), W.physics(P, V, ep.pillars)[:2]))
    assert set(Mo.HAND_MODELS) == {"E-CV", "E-B", "E-P"}


# --- tracker ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def ep():
    return W.generate_episode(NS, 1, 6)


def _digest(ids):
    return hashlib.sha256(json.dumps([np.asarray(i).tolist() for i in ids]).encode()).hexdigest()


def test_tracker_reads_only_detections_and_is_seeded(ep) -> None:
    dets = [s.detections for s in ep.steps]
    a, na = F.track(dets, ep.pillars, Mo.true_physics, np.random.default_rng(5))
    b, nb = F.track([d.copy() for d in dets], ep.pillars, Mo.true_physics, np.random.default_rng(5))
    assert _digest(a) == _digest(b) and na == nb
    assert [len(i) for i in a] == [len(d) for d in dets]
    c, _ = F.track(dets, ep.pillars, Mo.true_physics, np.random.default_rng(6))
    assert _digest(c) != _digest(a)


def test_tracker_uses_the_registered_configuration() -> None:
    cfg = F.FilterConfig()
    assert (cfg.members, cfg.q_pos, cfg.q_vel, cfg.obs_sigma, cfg.gate_base, cfg.gate_grow, cfg.speed) == (32, 0.01, 0.05, 0.05, 0.6, 1.5, (0.6, 1.4))


def test_identity_of_a_lone_visible_disk_is_kept() -> None:
    """One disk, always detected: one track the whole way."""
    p = np.array([5.0, 5.0]); v = np.array([0.5, 0.2])
    dets = []
    for _ in range(50):
        dets.append(p[None].copy())
        p = p + v * W.DT
    ids, n = F.track(dets, (), Mo.constant_velocity, np.random.default_rng(0))
    assert n == 1 and all(i.tolist() == [0] for i in ids)


def test_gate_grows_with_time_since_assignment() -> None:
    """A detection 2.0 away is refused right after the track was seen and accepted after 2 s hidden."""
    cfg = F.FilterConfig()
    P = np.zeros((32, 1, 2))
    z = np.array([[2.0, 0.0]])
    assert F._associate(P, z, [10], 11, cfg) == {}
    assert F._associate(P, z, [10], 30, cfg) == {0: 0}


def test_learned_variance_replaces_the_registered_noise() -> None:
    P = np.full((32, 2, 2), 5.0); V = np.zeros((32, 2, 2))
    zero = lambda P, V, pil: (P, V, np.zeros_like(P), np.zeros_like(V))
    p, v = F._predict(P, V, zero, (), F.FilterConfig(), np.random.default_rng(0))
    assert np.array_equal(p, P) and np.array_equal(v, V)
    p, _ = F._predict(P, V, lambda P, V, pil: (P, V), (), F.FilterConfig(), np.random.default_rng(0))
    assert 0.005 < np.std(p - P) < 0.02


def test_truth_diagnostic_beats_the_estimate(ep) -> None:
    est, _ = F.track([s.detections for s in ep.steps], ep.pillars, Mo.true_physics, np.random.default_rng(1))
    sp, _ = F.track_truth_diagnostic(ep, Mo.true_physics, np.random.default_rng(1))
    a = np.mean([e["correct"] for e in Me.reid(ep, est)])
    b = np.mean([e["correct"] for e in Me.reid(ep, sp)])
    assert b >= a - 0.05


def test_exploration_accuracies_are_pinned() -> None:
    """Re-identification counts on s4x-explore worlds 0-5 with the exploration filter seeds."""
    import hashlib as _h

    acc = {}
    for name, key in (("E-B", "B"), ("E-P", "P")):
        rows = []
        for w in range(6):
            e = W.generate_episode("s4x-explore", w, 6)
            seed = int(_h.sha256(f"s4x-explore:filter:{w}:{key}".encode()).hexdigest()[:16], 16) & 0x7FFFFFFF
            ids, _ = F.track([s.detections for s in e.steps], e.pillars, Mo.HAND_MODELS[name], np.random.default_rng(seed))
            rows += [x["correct"] for x in Me.reid(e, ids)]
        acc[name] = (sum(rows), len(rows))
    # 6 exploration worlds; the module equals tier1-explore/explore2.py track for track (checked 2026-11-10)
    assert acc == {"E-B": (144, 186), "E-P": (149, 186)}


# --- metrics -------------------------------------------------------------------------------------
def test_reid_and_idf1_with_perfect_and_broken_ids(ep) -> None:
    perfect = [s.truth_ids.copy() for s in ep.steps]
    r = Me.reid(ep, perfect)
    assert r and all(x["correct"] == 1 for x in r)
    assert Me.idf1(ep, perfect) == 1.0
    fresh = []  # a new id for every detection
    c = 0
    for s in ep.steps:
        fresh.append(np.arange(c, c + len(s.truth_ids)))
        c += len(s.truth_ids)
    assert all(x["correct"] == 0 for x in Me.reid(ep, fresh))
    assert Me.idf1(ep, fresh) < 0.05
    half = [s.truth_ids.copy() if s.t < 150 else (s.truth_ids + 100) for s in ep.steps]  # identities restart midway
    assert 0.3 < Me.idf1(ep, half) < 0.7


def test_dynamics_errors_definitions(ep) -> None:
    p = Me.dynamics_errors(ep, Mo.true_physics)
    b = Me.dynamics_errors(ep, Mo.bounce)
    assert p["coll"] and p["graze"] and max(p["coll"] + p["graze"]) == 0.0
    assert len(b["coll"]) == len(p["coll"]) and np.mean(b["coll"]) > 0.3 and max(b["graze"]) == 0.0
    n_coll = sum(len({i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}) for s in ep.steps[:-1])
    assert len(p["coll"]) == n_coll


def test_bootstrap_ratios() -> None:
    rng = np.random.default_rng(0)
    xb = rng.random(50) * 2; bb = rng.random(50) * 10 + 5
    r = Me.bootstrap(Me.stat_D, {"x_coll": xb, "b_coll": bb})
    assert r["value"] == pytest.approx(1 - xb.sum() / bb.sum())
    assert r["ci_low"] < r["value"] < r["ci_high"] and r["bonf_low"] <= r["ci_low"] and r["n_worlds"] == 50
    assert Me.bootstrap(Me.stat_D, {"x_coll": xb, "b_coll": bb}) == r
    assert Me.bootstrap(Me.stat_D, {"x_coll": xb, "b_coll": bb}, m=10)["bonf_low"] < r["bonf_low"]
    c = Me.bootstrap(Me.stat_C, {"x": np.full(40, 6.0), "b": np.full(40, 4.0), "p": np.full(40, 8.0)})
    assert c["value"] == pytest.approx(0.5)
    hf = Me.bootstrap(Me.stat_HF, {"x_graze": np.full(10, 1.0), "n_graze": np.full(10, 10.0), "b_coll": np.full(10, 5.0), "n_coll": np.full(10, 5.0)})
    assert hf["value"] == pytest.approx(0.1)
    assert Me.bootstrap(Me.stat_diff, {"x": np.ones(5), "y": np.zeros(5), "n": np.full(5, 2.0)})["value"] == pytest.approx(0.5)
    assert Me.bootstrap(Me.stat_D, {"x_coll": np.zeros(0), "b_coll": np.zeros(0)})["value"] is None
    undefined = Me.bootstrap(Me.stat_C, {"x": np.ones(5), "b": np.ones(5), "p": np.ones(5)})
    assert undefined["value"] is None and undefined["ci_low"] is None and undefined["n_worlds"] == 5
    # one world carries the whole denominator: about a third of the resamples are 0/0. Dropping them
    # would give the interval [0.5, 0.5]; the point value stays, the interval is withheld.
    one = np.array([1.0, 0, 0, 0, 0])
    partial = Me.bootstrap(Me.stat_C, {"x": one, "b": np.zeros(5), "p": 2 * one}, n_boot=2000)
    assert partial["value"] == pytest.approx(0.5) and 0 < partial["n_boot_finite"] < 2000
    assert partial["ci_low"] is partial["ci_high"] is partial["bonf_low"] is partial["bonf_high"] is None
    assert r["n_boot_finite"] == Me.BOOT_N


def test_metrics_constants() -> None:
    assert (Me.GRAZE_MARGIN, Me.BOOT_N, Me.BOOT_SEED, Me.LEVEL) == (0.3, 10_000, 20261110, 0.95)


def test_collision_and_graze_sets_recomputed_independently(ep) -> None:
    """A model that stops every disk: the error of a disk is its true next speed, so the lists
    name exactly the collision disks and the grazing disks (end-of-step distance)."""
    stop = lambda P, V, pil: (P, np.zeros_like(V))
    got = Me.dynamics_errors(ep, stop)
    coll, graze = [], []
    for s, nxt in zip(ep.steps[:-1], ep.steps[1:]):
        c = set()
        for kind, i, j in s.contacts:
            if kind == "disk":
                c |= {i, j}
        g = set()
        for i in range(ep.n_disks):
            for j in range(ep.n_disks):
                if i != j and np.hypot(*(nxt.positions[i] - nxt.positions[j])) < 2 * W.RADIUS + 0.3:
                    g.add(i)
        g -= c
        coll += [float(np.hypot(*nxt.velocities[i])) for i in sorted(c)]
        graze += [float(np.hypot(*nxt.velocities[i])) for i in sorted(g)]
    assert got["coll"] == pytest.approx(coll) and got["graze"] == pytest.approx(graze)
    assert len(graze) > 10


def test_bootstrap_interval_recomputed() -> None:
    rng = np.random.default_rng(1)
    x = rng.random(30); b = rng.random(30) + 1
    r = Me.bootstrap(Me.stat_D, {"x_coll": x, "b_coll": b}, n_boot=500, seed=11, m=4)
    draws = np.random.default_rng(11).integers(0, 30, size=(500, 30))
    boot = 1 - x[draws].sum(1) / b[draws].sum(1)
    assert r["ci_low"] == pytest.approx(np.quantile(boot, 0.025)) and r["ci_high"] == pytest.approx(np.quantile(boot, 0.975))
    assert r["bonf_low"] == pytest.approx(np.quantile(boot, 0.025 / 4)) and r["bonf_high"] == pytest.approx(np.quantile(boot, 1 - 0.025 / 4))


def test_a_resample_with_a_non_positive_denominator_gives_no_interval() -> None:
    """C's denominator acc(E-P) - acc(E-B) can change sign in a resample while the ratio stays finite."""
    rng = np.random.default_rng(3)
    b = rng.random(30) * 5
    p = b + np.where(np.arange(30) < 3, 2.0, -0.05)        # E-P ahead only in three worlds
    x = b + 0.5
    assert p.sum() > b.sum()                                  # the point value is defined
    r = Me.bootstrap(Me.stat_C, {"x": x, "b": b, "p": p})
    assert r["value"] is not None and r["ci_low"] is None and r["n_boot_finite"] < Me.BOOT_N
    assert np.isnan(Me.stat_C(x=1.0, b=2.0, p=2.0)) and np.isnan(Me.stat_C(x=1.0, b=2.0, p=1.5))
    assert np.isnan(Me.stat_D(x_coll=1.0, b_coll=0.0)) and np.isnan(Me.stat_HF(x_graze=1.0, n_graze=0.0, b_coll=1.0, n_coll=1.0))
    assert float(Me.stat_C(x=3.0, b=2.0, p=4.0)) == pytest.approx(0.5)
