"""S4 phase 1 evaluation module: partitions, per-world records, aggregation, gates and the
descriptive measures. CPU only (hand-made process models and synthetic records)."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NS = "test-s4-analysis"


@pytest.fixture(scope="module")
def ep():
    return W.generate_episode(NS, 0, 6)


# --- partitions ----------------------------------------------------------------------------------
def test_partitions() -> None:
    assert A.NAMESPACES == {"train": "s4p1-train", "probe": "s4p1-probe", "final": "s4p1-final"}
    assert set(A.NAMESPACES.values()).isdisjoint({"s4x-explore", "s4x-rv1110"})
    assert W.REGISTERED == {A.NAMESPACES["final"]}
    n = [A.train_disks("s4p1-train", w) for w in range(400)]
    assert set(n) == {4, 5, 6, 7, 8} and all(50 <= n.count(k) <= 110 for k in range(4, 9))
    ids = A.eval_world_ids(A.SIZES["final"])
    assert len(ids) == 300 and ids[0] == ("main", 0, 6) and ids[199] == ("main", 199, 6) and ids[200] == ("extrap", 1000, 10)
    assert len({(k, w) for k, w, _ in ids}) == 300
    assert A.SIZES == {"probe": (50, 25), "final": (200, 100)}


def test_variants_and_cells() -> None:
    base = F.FilterConfig()
    assert A.variant_config("base") == base
    q = A.variant_config("q4")
    assert (q.q_pos, q.q_vel) == (base.q_pos * 4, base.q_vel * 4)
    q = A.variant_config("q0.25")
    assert (q.q_pos, q.q_vel) == pytest.approx((base.q_pos / 4, base.q_vel / 4))
    g = A.variant_config("gate-tight")
    assert (g.gate_base, g.gate_grow) == (0.4, 1.0)
    with pytest.raises(ValueError):
        A.variant_config("q")  # noqa
    cells = A.plan_cells(["L-ind", "L-int"])
    keys = [c.key for c in cells]
    assert len(keys) == len(set(keys))
    assert {c.arm for c in cells if c.variant != "base"} == {"E-B", "E-P", "L-int", "S-P"}
    assert all({c.seed for c in cells if c.arm == a and c.variant == v} == {1, 2, 3} for a in ("E-B", "L-int") for v in A.variants())
    assert A.filter_seed("ns", 3, 1, "base") != A.filter_seed("ns", 3, 2, "base") != A.filter_seed("ns", 3, 1, "q4")


# --- records ------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def record(ep):
    cells = [A.Cell(a, s) for a in ("E-CV", "E-B", "E-P", "S-P") for s in A.SEEDS]
    models = {"E-CV": Mo.constant_velocity, "E-B": Mo.bounce, "E-P": Mo.true_physics}
    return A.world_record(ep, "main", NS, cells, models)


def test_world_record(ep, record) -> None:
    ev = W.reappearances(ep)
    assert record["events"] == [[e["k"], e["a"], e["b"], int(e["collision"])] for e in ev]
    assert set(record["dyn"]) == {"E-B", "E-P"} and record["dyn"]["E-P"]["coll"] == 0.0
    assert record["dyn"]["E-B"]["n_coll"] == record["dyn"]["E-P"]["n_coll"] > 0
    for key, r in record["reid"].items():
        assert len(r) == len(ev) and set(r) <= {0, 1}
    # the record replays: the same cell gives the same ids
    c = A.Cell("E-B", 2)
    ids, _ = A.track_cell(ep, c, Mo.bounce, NS)
    assert A.ids_digest(ids) == record["ids_sha256"][c.key]
    # the cell's filter seed is the registered derivation
    direct, _ = F.track([s.detections for s in ep.steps], ep.pillars, Mo.bounce, np.random.default_rng(A.filter_seed(NS, 0, 2, "base")))
    assert A.ids_digest(direct) == record["ids_sha256"][c.key]
    sp, _ = F.track_truth_diagnostic(ep, Mo.true_physics, np.random.default_rng(A.filter_seed(NS, 0, 3, "base")))
    assert A.ids_digest(sp) == record["ids_sha256"][A.Cell("S-P", 3).key]


def test_missing_model_is_an_error(ep) -> None:
    with pytest.raises(KeyError):
        A.world_record(ep, "main", NS, [A.Cell("L-int", 1)], {"E-B": Mo.bounce})


def test_learned_cells_use_their_own_seed_model(ep) -> None:
    seen = []

    def make(tag):
        def m(P, V, pil):
            seen.append(tag)
            return Mo.bounce(P, V, pil)
        return m

    models = {"E-B": Mo.bounce, "L-x#1": make(1), "L-x#2": make(2)}
    A.world_record(W.generate_episode(NS, 1, 4, steps=30), "main", NS, [A.Cell("L-x", 2)], models)
    # dynamics run every learned model; tracking cell L-x#2 runs only model 2
    n_dyn_1 = seen.count(1)
    assert seen.count(2) > n_dyn_1


# --- aggregation and gates -------------------------------------------------------------------------
def _synthetic(n_worlds, acc, dyn, *, events_per_world=10, coll_share=0.5, seed=0):
    """Records with given per-arm accuracy (on every event) and dynamics sums per disk-step."""
    rng = np.random.default_rng(seed)
    out = []
    for w in range(n_worlds):
        n_coll = int(events_per_world * coll_share)
        events = [[0, 0, 2, 1]] * n_coll + [[0, 0, 2, 0]] * (events_per_world - n_coll)
        r = {"events": events, "reid": {}, "dyn": {}, "idf1": {}, "n_tracks": {}}
        for arm, a in acc.items():
            for s in A.SEEDS:
                for v in A.variants():
                    r["reid"][A.Cell(arm, s, v).key] = list((rng.random(events_per_world) < a).astype(int))
                    r["idf1"][A.Cell(arm, s, v).key] = a
                    r["n_tracks"][A.Cell(arm, s, v).key] = 7
        for arm, (coll, graze) in dyn.items():
            names = [f"{arm}#{s}" for s in A.SEEDS] if arm.startswith("L-") else [arm]
            for name in names:
                r["dyn"][name] = {"coll": coll * 20 * (1 + 0.05 * rng.normal()), "n_coll": 20, "graze": graze * 30, "n_graze": 30}
        out.append(r)
    return out


def test_seed_average_per_event() -> None:
    r = {"events": [[0, 0, 2, 1], [1, 0, 2, 1], [2, 0, 2, 0]],
         "reid": {A.Cell("X", 1).key: [1, 0, 1], A.Cell("X", 2).key: [1, 1, 0], A.Cell("X", 3).key: [0, 0, 0]}}
    assert A.acc_sums([r], "X")[0] == pytest.approx(2 / 3 + 1 / 3)
    assert A.acc_sums([r], "X", collision=False)[0] == pytest.approx(2 / 3 + 1 / 3 + 1 / 3)
    assert A.n_events([r])[0] == 2 and A.n_events([r], collision=False)[0] == 3


GOOD_ACC = {"E-CV": 0.2, "E-B": 0.4, "E-P": 0.8, "S-P": 0.85, "L-int": 0.75, "L-ind": 0.42}
GOOD_DYN = {"E-B": (1.0, 0.0), "E-P": (0.0, 0.0), "L-int": (0.1, 0.03), "L-ind": (0.98, 0.05)}


def _evaluate(main, extrap, **kw):
    args = dict(n_main=len(main), labels_ok=True, student_ok=True, replay_ok=True) | kw
    return A.evaluate(main, extrap, **args)


def test_gates_pass_on_a_good_synthetic_result(monkeypatch) -> None:
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, events_per_world=int(261 / 40 * 2), coll_share=0.5)
    extrap = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    monkeypatch.setattr(Me, "BOOT_N", 500)
    r = _evaluate(main, extrap)
    assert r["valid"], r["legality"]
    assert all(g["passed"] for g in r["gates"].values()), {k: v["passed"] for k, v in r["gates"].items()}
    assert r["negative_control"]["passed"]
    assert r["gates"]["HD"]["D"]["value"] == pytest.approx(0.9, abs=0.02)


def test_each_gate_can_fail() -> None:
    extrap = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    base = dict(events_per_world=13, coll_share=0.5)
    cases = {
        "HD": ({}, {"L-int": (0.25, 0.03)}),          # D 0.75
        "HF": ({}, {"L-int": (0.1, 0.13)}),           # graze ratio 0.13
        "H1": ({"L-int": 0.55}, {}),                  # C 0.375
        "H2": ({"L-int": 0.75, "L-ind": 0.72}, {}),   # diff 0.03
    }
    for gate, (acc, dyn) in cases.items():
        main = _synthetic(40, GOOD_ACC | acc, GOOD_DYN | dyn, **base)
        r = _evaluate(main, extrap)
        assert not r["gates"][gate]["passed"], gate
        assert r["gates"]["HD-x"]["passed"] and r["gates"]["H3"]["passed"]
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    r = _evaluate(main, _synthetic(20, GOOD_ACC | {"L-int": 0.5}, GOOD_DYN | {"L-int": (0.35, 0.03)}, seed=1))
    assert not r["gates"]["HD-x"]["passed"] and not r["gates"]["H3"]["passed"] and r["gates"]["HD"]["passed"]


def _set_reid(recs, arm, per_world):
    """Give ``arm`` the same correctness on every event of a world, for all seeds (base variant)."""
    for r, x in zip(recs, per_world):
        for sd in A.SEEDS:
            r["reid"][A.Cell(arm, sd).key] = [int(x)] * len(r["events"])


def _set_dyn(recs, arm, field, per_world):
    for r, x in zip(recs, per_world):
        for sd in A.SEEDS:
            r["dyn"][f"{arm}#{sd}"][field] = float(x)


def test_interval_bounds_and_side_conditions_bind() -> None:
    """Each gate also fails when only its interval bound or its side condition fails: the point
    value is on the passing side and a few heavy worlds make the interval wide."""
    base = dict(events_per_world=13, coll_share=0.5)
    good_x = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    heavy40 = np.arange(40) % 10 == 0                       # 4 heavy worlds of 40

    # HD: D about 0.8 from 36 worlds at 0.05 and 4 worlds at 1.5 per disk-step
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    _set_dyn(main, "L-int", "coll", np.where(heavy40, 1.5, 0.05) * 20)
    g = _evaluate(main, good_x)["gates"]["HD"]
    assert g["D"]["value"] >= 0.8 and g["D"]["ci_low"] <= 0.7 and not g["passed"]

    # HF: ratio about 0.09, all of it in 4 worlds
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    _set_dyn(main, "L-int", "graze", np.where(heavy40, 27.0, 0.0))
    r = _evaluate(main, good_x)
    g = r["gates"]["HF"]
    assert r["valid"] and g["ratio"]["value"] <= 0.10 and g["ratio"]["ci_high"] > 0.15 and not g["passed"]
    assert r["gates"]["HD"]["passed"]

    # HD-x: D is fine on the extrapolation worlds, the grazing error is not
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    r = _evaluate(main, _synthetic(20, GOOD_ACC, GOOD_DYN | {"L-int": (0.1, 0.2)}, seed=1))
    g = r["gates"]["HD-x"]
    assert g["D"]["value"] >= 0.7 and g["D"]["ci_low"] > 0.6 and g["ratio"]["value"] > 0.15 and not g["passed"]
    assert r["gates"]["H3"]["passed"] and r["gates"]["HD"]["passed"]
    # ... and the other way round: 2 heavy worlds of 20 keep D above 0.7 with a low bound under 0.6
    ext = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    _set_dyn(ext, "L-int", "coll", np.where(np.arange(20) % 10 == 0, 2.4, 0.05) * 20)
    g = _evaluate(main, ext)["gates"]["HD-x"]
    assert g["D"]["value"] >= 0.7 and g["D"]["ci_low"] <= 0.6 and g["ratio"]["value"] <= 0.15 and not g["passed"]

    # H1 and H2: L-int right in 25 worlds and wrong in 15, L-ind the other way round in 22 / 18
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    _set_reid(main, "L-int", np.arange(40) < 25)
    r = _evaluate(main, good_x)
    g = r["gates"]["H1"]
    assert r["valid"] and g["C"]["value"] >= 0.5 and g["C"]["ci_low"] <= 0.25 and not g["passed"]
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    _set_reid(main, "L-int", np.arange(40) < 22)
    _set_reid(main, "L-ind", np.arange(40) >= 22)
    r = _evaluate(main, good_x)
    g = r["gates"]["H2"]
    assert r["valid"] and g["diff"]["value"] >= 0.05 and g["diff"]["ci_low"] <= 0.0 and not g["passed"]

    # H3: the same on the extrapolation worlds
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, **base)
    ext = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    _set_reid(ext, "L-int", np.arange(20) < 12)
    g = _evaluate(main, ext)["gates"]["H3"]
    assert g["C"]["value"] >= 0.4 and g["C"]["ci_low"] <= 0.2 and not g["passed"]


def test_dynamics_average_the_three_seed_models() -> None:
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, events_per_world=13)
    for r in main:
        for sd, x in zip(A.SEEDS, (0.0, 6.0, 6.0)):
            r["dyn"][f"L-int#{sd}"]["coll"] = x
            r["dyn"][f"L-int#{sd}"]["graze"] = x / 2
    eb = sum(r["dyn"]["E-B"]["coll"] for r in main)
    assert A.D_of(main, "L-int", m=1)["value"] == pytest.approx(1 - 40 * 4.0 / eb)
    assert A.HF_of(main, "L-int", m=1)["value"] == pytest.approx((40 * 2.0 / (40 * 30)) / (eb / (40 * 20)))


def test_negative_control_voids_HD_and_H1() -> None:
    main = _synthetic(40, GOOD_ACC | {"L-ind": 0.7}, GOOD_DYN, events_per_world=13)
    r = _evaluate(main, _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1))
    assert not r["negative_control"]["passed"]
    assert not r["gates"]["HD"]["passed"] and not r["gates"]["H1"]["passed"] and r["gates"]["HD"]["void"]
    assert r["gates"]["HF"]["passed"]
    main = _synthetic(40, GOOD_ACC, GOOD_DYN | {"L-ind": (0.4, 0.05)}, events_per_world=13)
    assert not _evaluate(main, _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1))["negative_control"]["passed"]


def test_legality_voids_everything() -> None:
    main = _synthetic(40, GOOD_ACC, GOOD_DYN, events_per_world=13)
    extrap = _synthetic(20, GOOD_ACC, GOOD_DYN, seed=1)
    for kw in ({"labels_ok": False}, {"student_ok": False}, {"replay_ok": False}):
        r = _evaluate(main, extrap, **kw)
        assert not r["valid"] and not any(g["passed"] for g in r["gates"].values())
    floor = _synthetic(40, GOOD_ACC | {"E-CV": 0.45}, GOOD_DYN, events_per_world=13)
    assert not _evaluate(floor, extrap)["legality"]["floor"]["passed"]
    few = _synthetic(40, GOOD_ACC, GOOD_DYN, events_per_world=8)      # 160 collision events, expected 261
    assert not _evaluate(few, extrap)["legality"]["samples"]["passed"]
    many = _synthetic(40, GOOD_ACC, GOOD_DYN, events_per_world=18)    # 360
    assert not _evaluate(many, extrap)["legality"]["samples"]["passed"]
    thin = copy.deepcopy(main)
    for r in thin:
        r["dyn"]["E-B"]["n_coll"] = 10                                 # 400 < 0.75 * 552
    assert not _evaluate(thin, extrap)["legality"]["samples"]["passed"]


def test_thresholds_are_registered() -> None:
    assert A.THRESHOLDS["HD"] == {"D": 0.8, "D_low": 0.7} and A.THRESHOLDS["HF"] == {"ratio": 0.10, "ratio_high": 0.15}
    assert A.THRESHOLDS["HD-x"] == {"D": 0.7, "D_low": 0.6, "ratio": 0.15}
    assert A.THRESHOLDS["H1"] == {"C": 0.5, "C_low": 0.25} and A.THRESHOLDS["H3"] == {"C": 0.4, "C_low": 0.2}
    assert A.THRESHOLDS["H2"] == {"diff": 0.05, "diff_low": 0.0}
    assert A.THRESHOLDS["negative_control"] == {"D_low_below": 0.5, "C_low_below": 0.25}
    assert (A.EXPECTED_COLL_EVENTS_PER_40, A.EXPECTED_COLL_DISK_STEPS_PER_40, A.SAMPLE_BAND, A.DYN_FLOOR) == (261, 552, 0.25, 0.75)
    assert A.N_COMPARISONS == 7 and A.SEEDS == (1, 2, 3)


# --- descriptive measures -----------------------------------------------------------------------
def test_cv_contact_baseline() -> None:
    R2 = 2 * W.RADIUS
    head_on = A.cv_contact_pairs(np.array([[0.0, 0.0], [R2 + 0.05, 0.0]]), np.array([[0.5, 0.0], [-0.5, 0.0]]))
    assert head_on == {(0, 1)}                           # touches after 0.05 s
    far = A.cv_contact_pairs(np.array([[0.0, 0.0], [R2 + 0.2, 0.0]]), np.array([[0.5, 0.0], [-0.5, 0.0]]))
    assert far == set()                                  # 0.2 s away
    apart = A.cv_contact_pairs(np.array([[0.0, 0.0], [R2 - 0.01, 0.0]]), np.array([[-0.5, 0.0], [0.5, 0.0]]))
    assert apart == set()                                # overlapping but separating
    closing = A.cv_contact_pairs(np.array([[0.0, 0.0], [R2 - 0.01, 0.0]]), np.array([[0.5, 0.0], [-0.5, 0.0]]))
    assert closing == {(0, 1)}
    miss = A.cv_contact_pairs(np.array([[0.0, 0.0], [R2 + 0.05, 1.0]]), np.array([[0.5, 0.0], [-0.5, 0.0]]))
    assert miss == set()


def test_contact_counts_with_a_perfect_head(ep) -> None:
    def oracle(P, V, pil):
        _, _, c = W.physics(P, V, pil, log=True)
        n = P.shape[1]
        lg = -np.ones((1, n, n))
        for kind, i, j in c:
            if kind == "disk":
                lg[0, i, j] = lg[0, j, i] = 1
        return lg
    c = A.contact_counts(ep, oracle)
    assert c["head"]["fp"] == c["head"]["fn"] == 0 and c["head"]["tp"] > 0 and A.f1(c["head"]) == 1.0
    assert c["cv"]["tp"] > 0 and A.f1(c["cv"]) is not None
    assert A.f1({"tp": 0, "fp": 0, "fn": 0}) is None


def test_kstep_sums(ep) -> None:
    p = A.kstep_sums(ep, Mo.true_physics)
    assert set(p) == {"1", "5", "10", "30"} and all(v[0] == pytest.approx(0, abs=1e-9) for v in p.values())
    assert p["1"][1] == len(range(0, 300 - 30, 10))
    cv = A.kstep_sums(ep, Mo.constant_velocity)
    assert cv["1"][0] < cv["5"][0] < cv["30"][0]


def test_perturbed_dynamics(ep) -> None:
    def perturb(pos, vel, rng, *, exact):
        return pos + rng.normal(0, 0.05, pos.shape), vel + rng.normal(0, 0.2, vel.shape)
    r = A.perturbed_dyn_sums(ep, {"E-P": Mo.true_physics, "E-B": Mo.bounce}, perturb, np.random.default_rng(0))
    assert r["E-P"]["coll"] == 0 and r["E-B"]["coll"] > 0 and r["E-P"]["n_coll"] == r["E-B"]["n_coll"] > 0


def _mean_var(sig_p, sig_v):
    def f(P, V, pil):
        p, v = Mo.true_physics(P, V, pil)
        return p, v, np.full_like(p, sig_p ** 2), np.full_like(v, sig_v ** 2)
    return f


def test_calibration_rows_and_references(ep) -> None:
    rows = A.calib_rows(ep, _mean_var(0.05, 0.3), np.random.default_rng(1))
    n = 299 * 6
    assert len(rows["kind"]) == n and rows["err"].shape == (n, 2) and rows["var"].shape == (n, 2)
    assert set(np.unique(rows["kind"])) == {0, 1, 2}
    ref = A.fit_references(rows)
    cg = rows["kind"] <= 1
    assert ref["constant"] == pytest.approx(float((rows["err"][cg] ** 2).mean()))
    assert ref["oracle"][1] == pytest.approx(float((rows["err"][~cg] ** 2).mean()))
    assert len(ref["bins"]) == len(A.CALIB_BINS) - 1
    cal = A.calibration(rows, ref)
    assert set(cal) == {"collision", "graze", "free", "collision+graze"}
    assert cal["collision"]["n"] + cal["graze"]["n"] + cal["free"]["n"] == n
    # fitted on these rows, the oracle is the best of the references on collision+graze
    cgv = cal["collision+graze"]
    assert cgv["oracle"]["nll"] <= cgv["constant"]["nll"] + 1e-9
    # a variance matching the free-step error covers about 90% of free steps
    free_sd = float(np.sqrt((rows["err"][rows["kind"] == 2] ** 2).mean()))
    rows2 = A.calib_rows(ep, _mean_var(0.05, free_sd), np.random.default_rng(1))
    assert 0.8 < A.calibration(rows2, ref)["free"]["L-int-s"]["cov90"] < 0.97


def test_filter_hook_reads_and_does_not_change_tracking(ep) -> None:
    dets = [s.detections for s in ep.steps]
    a, na = F.track(dets, ep.pillars, Mo.true_physics, np.random.default_rng(4))
    hook = A.FilterCalibration(ep)
    b, nb = F.track(dets, ep.pillars, Mo.true_physics, np.random.default_rng(4), on_predict=hook)
    assert A.ids_digest(a) == A.ids_digest(b) and na == nb
    s = hook.sums()
    assert s["n"] > 500 and 0.5 < s["inside"] / s["n"] <= 1.0

    def vandal(t, P, V, assign, last):
        P[:] = 0.0
        assign.clear()
        last[:] = [0] * len(last)
    c, _ = F.track(dets, ep.pillars, Mo.true_physics, np.random.default_rng(4), on_predict=vandal)
    assert A.ids_digest(c) == A.ids_digest(a)
