"""S4 phase 2 evaluation: calibration hooks, aggregation over seeds and worlds, the gates, the
negative control and the legality gates, on synthetic records. Pure NumPy."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W


# --- registered constants ---------------------------------------------------------------------------
def test_registered_constants() -> None:
    assert P2.NAMESPACES == {"probe": "s4p2-probe", "final": "s4p2-final"}
    assert P2.SIZES == {"probe": (50, 25), "final": (200, 100)}
    assert P2.NAMESPACES["final"] in W.REGISTERED and P2.NAMESPACES["probe"] not in W.REGISTERED
    assert P2.BOOT_SEED == 20261111 and P2.N_COMPARISONS == 11
    assert P2.GATES == {"L-int-g": 0.5, "L-int-g3": 0.3, "L-int-g7": 0.7, "L-int-geo": "geo", "L-ind-geo": "geo"}
    assert P2.THRESHOLDS["GN"] == {"diff": -0.01, "diff_low": -0.03}
    assert P2.THRESHOLDS["GA"] == {"diff": 0.03, "diff_low": 0.0}
    assert P2.THRESHOLDS["GC"] == {"C": 0.75, "C_low": 0.5}
    assert P2.THRESHOLDS["GK1"] == {"all": (0.87, 0.93), "all_interval": (0.85, 0.95), "collision": 0.85, "collision_low": 0.80}
    assert P2.THRESHOLDS["GK2"] == {"non_collision": 0.85, "non_collision_low": 0.80, "collision": 0.75, "collision_low": 0.65}
    assert P2.THRESHOLDS["GD"] == {"D": 0.8, "D_low": 0.7, "ratio": 0.10, "ratio_high": 0.15}
    assert P2.THRESHOLDS["GX"] == {"diff": 0.03, "diff_low": 0.0, "C": 0.6, "C_low": 0.4}


# --- hooks -------------------------------------------------------------------------------------------
def _ens(center, sigma, m=64, seed=0):
    return np.random.default_rng(seed).normal(0, sigma, (m, 2)) + np.asarray(center, float)


def test_reappearance_uses_the_track_held_at_a_and_the_ensemble_at_b() -> None:
    steps = [SimpleNamespace(truth_ids=np.array([0, 1]), positions=np.array([[1.0, 1.0], [5.0, 5.0]])),
             SimpleNamespace(truth_ids=np.array([1]), positions=np.array([[1.5, 1.0], [5.0, 5.0]])),
             SimpleNamespace(truth_ids=np.array([1, 0]), positions=np.array([[2.0, 1.0], [5.0, 5.0]]))]
    ep = SimpleNamespace(steps=steps)
    ids = [np.array([3, 7]), np.array([7]), np.array([7, 9])]      # disk 0: track 3 at a=0, new track 9 at b=2
    snap = np.zeros((64, 10, 2))
    snap[:, 3] = _ens([2.0, 1.0], 0.1)                              # track 3 predicts the truth well
    snap[:, 9] = _ens([8.0, 8.0], 0.1)                              # track 9 (the one used at b) is far away
    ev = [{"k": 0, "a": 0, "b": 2}]
    assert P2.reappearance_inside(ep, ids, ev, {2: snap}) == [1]
    snap[:, 3] = _ens([3.5, 1.0], 0.1)
    assert P2.reappearance_inside(ep, ids, ev, {2: snap}) == [0]


def test_one_step_rows_classify_by_the_contact_in_the_previous_step() -> None:
    steps = [SimpleNamespace(truth_ids=np.array([0, 1]), positions=np.array([[1.0, 1.0], [1.6, 1.0]]), contacts=(("disk", 0, 1),)),
             SimpleNamespace(truth_ids=np.array([1, 0]), positions=np.array([[0.9, 1.0], [1.7, 1.0]]), contacts=())]
    ep = SimpleNamespace(steps=steps)
    hook = P2.Calibration(ep, want=[1])
    P = np.zeros((64, 3, 2))
    P[:, 0] = _ens([0.9, 1.0], 0.05)        # track 0 holds disk 0: inside
    P[:, 1] = _ens([3.0, 3.0], 0.05)        # track 1 holds disk 1: outside
    P[:, 2] = _ens([0.0, 0.0], 0.05)
    hook(0, P, P, {}, [])
    hook(1, P, P, {1: 0, 0: 1, }, [0, 0, -5])
    assert hook.one["collision"] == [2, 1] and hook.one["other"] == [0, 0]
    assert np.array_equal(hook.snaps[1], P)
    hook2 = P2.Calibration(ep, want=[])
    hook2(1, P, P, {1: 0, 0: 2}, [0, 0, -5])                  # track 2 was not assigned at t-1: no row
    assert hook2.one["collision"] == [1, 1]


def test_hook_does_not_change_tracking() -> None:
    ep = W.generate_episode("test-s4p2-hook", 0, 5, steps=80)
    ev = W.reappearances(ep)
    rng = lambda: np.random.default_rng(5)
    a, _ = F.track(A.student_detections(ep), ep.pillars, Mo.true_physics, rng())
    cell = P2.track_cell(ep, Mo.true_physics, "test-s4p2-hook", 1, ev)
    b, _ = F.track(A.student_detections(ep), ep.pillars, Mo.true_physics, np.random.default_rng(P2.filter_seed("test-s4p2-hook", 0, 1)))
    assert cell["ids_sha256"] == P2.ids_digest(b)
    assert len(cell["reappear"]) == len(ev) == len(cell["correct"])
    assert sum(cell["one_step"]["collision"]) + sum(cell["one_step"]["other"]) > 0
    assert a is not None


# --- synthetic records -------------------------------------------------------------------------------
BASE = {  # arm -> (p correct on collision events, on non-collision events, one-step cov all, one-step cov collision, reappear cov non, coll)
    "E-CV": (0.30, 0.60, 0.65, 0.40, 0.50, 0.30),
    "E-B": (0.42, 0.87, 0.83, 0.58, 0.86, 0.46),
    "E-P": (0.67, 0.89, 0.90, 0.88, 0.91, 0.83),
    "L-int": (0.60, 0.82, 0.74, 0.69, 0.60, 0.54),
    "L-int-g": (0.66, 0.89, 0.90, 0.88, 0.91, 0.83),
    "L-int-g3": (0.66, 0.89, 0.90, 0.88, 0.91, 0.83),
    "L-int-g7": (0.66, 0.89, 0.90, 0.88, 0.91, 0.83),
    "L-int-geo": (0.66, 0.89, 0.90, 0.88, 0.91, 0.83),
    "L-ind-geo": (0.44, 0.87, 0.83, 0.59, 0.86, 0.46),
}


def records(n=200, kind="main", spec=None, seed=0, n_events=30, coll_share=0.22, dyn=None):
    spec = dict(BASE, **(spec or {}))
    rng = np.random.default_rng(seed)
    dyn = dyn or {"L-int-g": (0.15, 0.03), "L-ind-geo": (1.0, 0.0), "L-int": (0.13, 0.07)}   # (coll error / E-B, graze ratio)
    dyn = {"L-int-g3": (0.15, 0.03), "L-int-g7": (0.16, 0.02), "L-int-geo": (0.15, 0.0)} | dyn
    out = []
    for w in range(n):
        coll = rng.random(n_events) < coll_share
        ev = [[0, 0, 5, int(c), int(g)] for c, g in zip(coll, rng.integers(0, 80, n_events))]
        cells = {}
        for arm, (pc, pn, k1, k1c, k2n, k2c) in spec.items():
            for s in P2.SEEDS:
                p = np.where(coll, pc, pn)
                q = np.where(coll, k2c, k2n)
                rows_c, rows_o = 40, 400
                cells[P2.cell_key(arm, s)] = {
                    "correct": (rng.random(n_events) < p).astype(int).tolist(),
                    "reappear": (rng.random(n_events) < q).astype(int).tolist(),
                    "one_step": {"collision": [rows_c, int(rng.binomial(rows_c, k1c))],
                                 "other": [rows_o, int(rng.binomial(rows_o, (k1 * (rows_c + rows_o) - k1c * rows_c) / rows_o))]},
                    "idf1": 0.7, "n_tracks": 7, "gate": [2, 100]}
        eb_coll, n_coll = 1.0 * 14, 14
        d = {"E-B": {"coll": eb_coll, "n_coll": n_coll, "graze": 0.0, "n_graze": 100}}
        for name, (ratio, hf) in dyn.items():
            for s in P2.SEEDS:
                d[f"{name}#{s}"] = {"coll": eb_coll * ratio * (1 + 0.05 * rng.normal()), "n_coll": n_coll,
                                    "graze": hf * 100 * (eb_coll / n_coll) * (1 + 0.05 * rng.normal()), "n_graze": 100}
        out.append({"kind": kind, "world": w, "events": ev, "cells": cells, "dyn": d})
    return out


def _eval(main=None, extrap=None, **kw):
    main = records() if main is None else main
    extrap = records(100, "extrap", seed=1, coll_share=0.38) if extrap is None else extrap
    args = dict(n_main=len(main), n_extrap=len(extrap), labels_ok=True, student_ok=True, replay_ok=True, weights_ok=True)
    args.update(kw)
    return P2.evaluate(main, extrap, **args)


@pytest.fixture(scope="module")
def good():
    return _eval()


def test_a_gated_model_like_the_exploration_passes_every_gate(good) -> None:
    assert good["valid"], good["legality"]
    assert good["negative_control"]["passed"]
    assert {k: v["passed"] for k, v in good["gates"].items()} == {k: True for k in ("GN", "GA", "GC", "GK1", "GK2", "GD", "GX")}


def test_bonferroni_is_eleven_comparisons(good) -> None:
    c = good["gates"]["GC"]["C"]
    assert c["bonf_low"] < c["ci_low"] < c["value"] < c["ci_high"] < c["bonf_high"]
    alt = P2.C_of(records(), "L-int-g", m=11)
    assert alt == c


def test_phase1_like_model_fails_the_non_collision_gate() -> None:
    r = _eval(records(spec={"L-int-g": BASE["L-int"]}))
    g = r["gates"]
    assert not g["GN"]["passed"] and not g["GA"]["passed"] and not g["GK1"]["passed"] and not g["GK2"]["passed"]
    assert g["GN"]["diff"]["value"] < -0.03


def test_always_closed_gate_is_eb_and_fails() -> None:
    r = _eval(records(spec={"L-int-g": BASE["E-B"]}, dyn={"L-int-g": (1.0, 0.0), "L-ind-geo": (1.0, 0.0), "L-int": (0.13, 0.07)}))
    g = r["gates"]
    assert g["GN"]["passed"]                       # not worse than E-B on non-collision events, trivially
    assert not g["GA"]["passed"] and not g["GC"]["passed"] and not g["GK1"]["passed"] and not g["GK2"]["passed"] and not g["GD"]["passed"]


def test_overconfident_or_overdispersed_one_step_coverage_fails() -> None:
    for cov in ((0.96, 0.96, 0.91, 0.83), (0.90, 0.80, 0.91, 0.83)):
        spec = {"L-int-g": (0.66, 0.89, cov[0], cov[1], cov[2], cov[3])}
        assert not _eval(records(spec=spec))["gates"]["GK1"]["passed"]


def test_collision_reappearance_coverage_below_threshold_fails() -> None:
    spec = {"L-int-g": (0.66, 0.89, 0.90, 0.88, 0.91, 0.66)}
    g = _eval(records(spec=spec))["gates"]
    assert not g["GK2"]["passed"] and g["GK1"]["passed"]


def test_negative_control_failure_voids_the_tracking_gates() -> None:
    r = _eval(records(spec={"L-ind-geo": BASE["L-int-g"]}))
    assert not r["negative_control"]["passed"]
    for k in ("GA", "GC", "GX"):
        assert not r["gates"][k]["passed"] and r["gates"][k]["void"] == "negative control failed"
    assert r["gates"]["GN"]["passed"]


def test_legality_failure_voids_everything(good) -> None:
    for kw in ({"labels_ok": False}, {"student_ok": False}, {"replay_ok": False}, {"weights_ok": False}):
        r = _eval(**kw)
        assert not r["valid"] and not any(g["passed"] for g in r["gates"].values())
    r = _eval(main=records()[:199], n_main=200)
    assert not r["legality"]["complete"]["passed"] and not r["valid"]


def test_floor_and_samples() -> None:
    r = _eval(records(spec={"E-CV": BASE["E-P"]}))           # E-CV above E-B on collision events
    assert not r["legality"]["floor"]["passed"] and not r["valid"]
    r = _eval(records(coll_share=0.05))
    assert not r["legality"]["samples"]["passed"]


def test_undefined_C_fails_the_gate() -> None:
    r = _eval(records(spec={"E-P": BASE["E-B"]}))
    assert not r["gates"]["GC"]["passed"]


def test_seed_averaging_per_event() -> None:
    recs = records(3, n_events=5)
    arm = "L-int-g"
    want = []
    for r in recs:
        per = np.mean([r["cells"][P2.cell_key(arm, s)]["correct"] for s in P2.SEEDS], axis=0)
        m = np.array([e[3] == 0 for e in r["events"]])
        want.append(per[m].sum())
    assert np.allclose(P2.event_sums(recs, arm, "non_collision"), want)
    ins, n = P2.one_step_sums(recs, arm, "collision")
    assert np.array_equal(n, [3 * 40.0] * 3)
    ins_all, n_all = P2.one_step_sums(recs, arm, "all")
    assert np.array_equal(n_all, [3 * 440.0] * 3) and (ins_all >= ins).all()


def test_descriptive_summary_runs_on_both_partitions() -> None:
    d = P2.summarize_descriptive(records(20), records(10, "extrap", seed=3), P2.HAND + P2.LEARNED)
    assert set(d["main"]) == set(P2.HAND + P2.LEARNED)
    assert d["main"]["L-int-g"]["gate_share"] == pytest.approx(0.02)
    assert set(d["main"]["L-int-g"]["reappear_by_gap"]) == {"0-10", "10-25", "25-50", "50-inf"}
    assert set(d["dynamics"]["main"]) == {"L-int", *P2.GATES}
