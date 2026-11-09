"""Contracts for S3 phase 2 replay helpers and gates. Pure NumPy, synthetic events."""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import analysis as P1
from ainerzero.v9.experiments.s3 import analysis_p2 as G
from ainerzero.v9.experiments.s3 import batching as B
from ainerzero.v9.experiments.s3 import data as D
from ainerzero.v9.experiments.s3 import replay as RP
from ainerzero.v9.experiments.s3 import spec

SEEDS = (1, 2, 3)
N_EP, EV = 60, 6


def _prepared(n_events=5, offset=0, t0=20):
    q = np.arange(n_events, dtype=np.int32) * 7 + t0
    return B.PreparedEpisode(
        obs=np.zeros((360, spec.OBS_DIM), dtype=np.float32),
        query_t=q,
        top1=q - 5,
        oracle=q - 9,
        shuffled=q + 40,
        candidates=np.zeros((n_events, 12), dtype=np.int32),
        cand_feats=np.zeros((n_events, 12, 3), dtype=np.float32),
        cand_mask=np.ones((n_events, 12), dtype=bool),
        answer=np.arange(n_events, dtype=np.int32) % 8 + 1 + offset,
        swapped=np.ones(n_events, dtype=bool),
        bucket=np.full(n_events, 3, dtype=np.int32),
    )


def test_buffer_is_deterministic_without_repeats_and_nested() -> None:
    a = RP.buffer_indices(1600, 64, 11)
    assert np.array_equal(a, RP.buffer_indices(1600, 64, 11))
    assert len(set(a.tolist())) == 64
    assert np.array_equal(a[:16], RP.buffer_indices(1600, 16, 11))
    assert np.array_equal(RP.buffer_indices(1600, 256, 11)[:64], a)
    assert not np.array_equal(a, RP.buffer_indices(1600, 64, 12))


@pytest.mark.parametrize("cap", [0, -1, 1601])
def test_buffer_capacity_must_fit(cap) -> None:
    with pytest.raises(ValueError):
        RP.buffer_indices(1600, cap, 1)


def test_permuted_answers_keep_the_multiset_and_every_other_field() -> None:
    buf = [_prepared(5), _prepared(7, offset=1)]
    out = RP.permute_answers(buf, 3)
    before = np.concatenate([p.answer for p in buf])
    after = np.concatenate([p.answer for p in out])
    assert np.array_equal(np.sort(before), np.sort(after))
    assert not np.array_equal(before, after)
    assert [len(p.answer) for p in out] == [5, 7]
    for old, new in zip(buf, out):
        for f in dataclasses.fields(B.PreparedEpisode):
            if f.name != "answer":
                assert np.array_equal(getattr(old, f.name), getattr(new, f.name)), f.name


def test_permuting_is_deterministic_and_refuses_an_empty_buffer() -> None:
    buf = [_prepared(20)]
    assert np.array_equal(RP.permute_answers(buf, 3)[0].answer, RP.permute_answers(buf, 3)[0].answer)
    with pytest.raises(ValueError):
        RP.permute_answers([], 3)


def test_past_only_shuffle_stays_before_the_gap_and_changes_only_that_field() -> None:
    p = _prepared(40, t0=5)
    out = RP.past_only_shuffle(p, 9)
    assert (out.shuffled >= 0).all() and (out.shuffled <= p.query_t - RP.MIN_GAP).all()
    assert (out.shuffled[1:] != p.top1[1:]).mean() > 0.8
    for f in dataclasses.fields(B.PreparedEpisode):
        if f.name != "shuffled":
            assert np.array_equal(getattr(p, f.name), getattr(out, f.name)), f.name
    assert np.array_equal(out.shuffled, RP.past_only_shuffle(p, 9).shuffled)


def test_past_only_shuffle_uses_the_whole_past() -> None:
    p = _prepared(1, t0=300)
    drawn = {int(RP.past_only_shuffle(p, s).shuffled[0]) for s in range(600)}
    assert min(drawn) < 30 and max(drawn) > 265 and max(drawn) <= 295


def test_past_only_shuffle_refuses_an_event_without_a_past() -> None:
    with pytest.raises(ValueError):
        RP.past_only_shuffle(_prepared(1, t0=3), 1)


def test_new_namespaces_are_disjoint_from_phase_one() -> None:
    seeds = lambda ns: {D.derive_seed(ns, tag + "world", w) for tag in ("", "f2-") for w in range(450)}
    p2 = [seeds(ns) for ns in G.NAMESPACES.values()]
    p1 = set().union(*(seeds(ns) for ns in spec.REGISTERED_NAMESPACES))
    for s in p2:
        assert not s & p1
    assert sum(len(s) for s in p2) == len(set().union(*p2))
    assert len(set(G.NAMESPACES.values())) == 4


def test_long_bucket_code_matches_batching() -> None:
    assert G.LONG == B.BUCKET_CODE[spec.BUCKET_LONG]


def test_registered_constants() -> None:
    assert (G.CHANCE, G.FLOOR, G.UPPER_MIN, G.UNSWAPPED_MIN) == (P1.CHANCE, P1.FLOOR, P1.UPPER_MIN, P1.UNSWAPPED_MIN)
    assert (G.H1_MIN_DELTA, G.H2_MIN_DELTA, G.H2B_MIN_DELTA, G.H3_MARGIN) == (0.10, 0.05, 0.03, 0.05)
    assert (G.INTERFERENCE_MIN, G.CONTENT_MIN) == (0.10, 0.10)
    assert (G.MIN_EVENTS_PER_SEED, G.MIN_EPISODES_PER_SEED) == (200, 50)
    assert G.CAPACITIES == (16, 64, 256)


def _events(acc, acc8=None, swapped_acc=None):
    """Long-gap events, ``acc`` correct on swapped events and ``swapped_acc`` on unswapped."""
    n = N_EP * EV
    ep = np.repeat(np.arange(N_EP), EV)
    swapped = (np.arange(n) % EV) < 4
    bucket = np.full(n, G.LONG)
    rank = np.arange(n) % 100
    make = lambda p: rank < round(100 * p)
    correct = make(acc)
    other = make(acc if swapped_acc is None else swapped_acc)
    correct = np.where(swapped, correct, other)
    c8 = make(acc if acc8 is None else acc8)
    c8 = np.where(swapped, c8, other)
    return {"correct": correct, "correct_8": c8, "pred": correct.astype(int), "swapped": swapped, "bucket": bucket, "ep": ep, "query_t": np.arange(n) % EV + 100, "answer": np.arange(n) % 8 + 1}


def _world(over=None):
    """A run where everything passes; ``over`` maps (cond, phase) to replacement events."""
    base = {
        ("A0", "F1"): _events(0.0, swapped_acc=1.0),
        ("O", "F1"): _events(1.0),
        ("N", "F1"): _events(0.05),
        ("A1", "F1"): _events(0.2),
        ("A3S", "F1"): _events(0.70),
    }
    a2f1, a3f1 = _events(0.85, swapped_acc=0.9), _events(0.92, swapped_acc=0.95)
    for mem, f1, f2 in (("A2", a2f1, _events(0.85)), ("A3H", a3f1, _events(0.88))):
        base[f"{mem}-C0", "F1"] = f1
        base[f"{mem}-C0", "F1_after"] = _events(0.1, acc8=0.5)
        base[f"{mem}-C0", "F2"] = f2
        for cap in G.CAPACITIES:
            base[f"{mem}-R{cap}", "F1"] = f1
            base[f"{mem}-R{cap}", "F1_after"] = f1
            base[f"{mem}-R{cap}", "F2"] = f2
    base["A2-CN", "F1"] = a2f1
    base["A2-CN", "F1_after"] = _events(0.1, acc8=0.2)
    base.update(over or {})
    return {(c, s, ph): r for (c, ph), r in base.items() for s in SEEDS}


def _eval(per=None, **kw):
    return G.evaluate(_world() if per is None else per, SEEDS, capacity=64, **kw)


def test_a_clean_run_is_valid_and_passes() -> None:
    r = _eval()
    assert r["valid"] and all(r["legality"].values())
    assert r["h1"]["pass"] and r["h2"]["pass"] and r["h2b"]["pass"]
    assert r["h3_prime"]["pass"] and r["h3_prime"]["valid"]


def test_gate_directions() -> None:
    r = _eval()
    per = _world()
    primary = lambda c: float(per[c, 1, "F1"]["correct"][G.primary_mask(per[c, 1, "F1"])].mean())
    assert r["h1"]["delta"] == pytest.approx(primary("A2-C0") - primary("A1"), abs=1e-9) and r["h1"]["delta"] > 0
    assert r["h2"]["delta"] == pytest.approx(primary("A3H-C0") - primary("A2-C0"), abs=1e-9) and r["h2"]["delta"] > 0
    assert r["h2b"]["delta"] == pytest.approx(primary("A3H-C0") - primary("A3S"), abs=1e-9) and r["h2b"]["delta"] > 0
    assert r["h3_prime"]["retention"]["delta"] == pytest.approx(0.0, abs=1e-9)


def test_h2_fails_when_learned_retrieval_only_ties() -> None:
    assert not _eval(_world({("A3H-C0", "F1"): _events(0.86, swapped_acc=0.95)}))["h2"]["pass"]


@pytest.mark.parametrize("cond_phase,value", [(("A0", "F1"), 0.3), (("O", "F1"), 0.8), (("N", "F1"), 0.3)])
def test_legality_fails_each_way(cond_phase, value) -> None:
    r = _eval(_world({cond_phase: _events(value, swapped_acc=1.0)}))
    assert not r["valid"]


def test_unswapped_gate_reads_unswapped_events() -> None:
    bad = _events(0.85, swapped_acc=0.5)
    per = _world({(c, "F1"): bad for c in G.DETERMINISM_GROUPS[0]})
    r = _eval(per)
    assert not r["legality"]["unswapped_A2"]


def test_retention_is_judged_on_the_upper_bound_not_the_point() -> None:
    """A small mean drop concentrated in a few episodes has a wide interval."""
    after = _events(0.85, swapped_acc=0.9)
    for k in ("correct", "correct_8"):
        after[k] = after[k].copy()
        after[k][np.isin(after["ep"], [0, 1, 2])] = False
    r = _eval(_world({("A2-R64", "F1_after"): after}))
    h = r["h3_prime"]
    assert h["retention"]["delta"] <= G.H3_MARGIN < h["retention"]["ci_high"]
    assert not h["gates"]["retention"] and not h["pass"]


def test_large_drop_fails_retention() -> None:
    assert not _eval(_world({("A2-R64", "F1_after"): _events(0.6)}))["h3_prime"]["pass"]


def test_plasticity_cost_fails_h3() -> None:
    h = _eval(_world({("A2-R64", "F2"): _events(0.6)}))["h3_prime"]
    assert h["gates"]["retention"] and not h["gates"]["plasticity"] and not h["pass"]


def test_interference_is_read_on_the_8_class_readout() -> None:
    """The 16-class drop is huge here; only the 8-class drop is small, so H3' must be void."""
    per = _world({("A2-C0", "F1_after"): _events(0.1, acc8=0.82)})
    h = _eval(per)["h3_prime"]
    assert h["interference_8class"]["delta"] < G.INTERFERENCE_MIN
    assert not h["valid"] and not h["pass"]


def test_content_control_is_read_on_the_8_class_readout() -> None:
    """A control that only loses the 16-class readout has not shown content matters."""
    per = _world({("A2-CN", "F1_after"): _events(0.1, acc8=0.82)})
    h = _eval(per)["h3_prime"]
    assert h["content_8class"]["delta"] < G.CONTENT_MIN
    assert not h["valid"] and not h["pass"]


def test_content_control_failure_voids_only_h3() -> None:
    per = _world({("A2-CN", "F1_after"): _events(0.85, swapped_acc=0.9)})
    r = _eval(per)
    assert not r["h3_prime"]["valid"] and not r["h3_prime"]["pass"]
    assert r["valid"] and r["h1"]["pass"] and r["h2"]["pass"] and r["h2b"]["pass"]


def test_non_inferiority_fails_on_nan() -> None:
    assert not G.non_inferior({"ci_high": float("nan")}, 0.05)
    assert G.non_inferior({"ci_high": 0.05}, 0.05)
    assert not G.non_inferior({"ci_high": 0.0500001}, 0.05)


@pytest.mark.parametrize("group", [0, 1])
def test_determinism_gate_catches_a_changed_f1_stage(group) -> None:
    changed = dict(_events(0.85, swapped_acc=0.9))
    changed["pred"] = changed["pred"].copy()
    changed["pred"][0] += 1
    cond = G.DETERMINISM_GROUPS[group][-1]
    per = _world()
    per[cond, 2, "F1"] = changed
    r = _eval(per)
    assert not r["valid"] and not r["legality"][("determinism_A2", "determinism_A3H")[group]]


def test_determinism_groups_exclude_differently_trained_conditions() -> None:
    names = set().union(*G.DETERMINISM_GROUPS)
    assert "A3S" not in names and not any(n.endswith("-J") for n in names)


def test_minimum_sample_is_per_seed() -> None:
    per = _world()
    r = dict(per["A2-C0", 2, "F1"])
    keep = r["ep"] < 30
    small = {k: v[keep] for k, v in r.items()}
    per["A2-C0", 2, "F1"] = small
    with pytest.raises((ValueError, KeyError)):
        G.paired(per, ("A2-C0", "F1"), ("A1", "F1"), SEEDS)
    assert not G.enough_samples(per, "A2-C0", "F1", SEEDS)
    assert G.enough_samples(per, "A1", "F1", SEEDS)


def test_misaligned_events_raise() -> None:
    per = _world()
    r = dict(per["A1", 1, "F1"])
    r["ep"] = r["ep"][::-1].copy()
    per["A1", 1, "F1"] = r
    with pytest.raises(ValueError, match="align"):
        G.paired(per, ("A2-C0", "F1"), ("A1", "F1"), SEEDS)


def test_empty_primary_data_raises() -> None:
    r = _events(0.5)
    r["swapped"] = np.zeros_like(r["swapped"])
    per = _world({("A0", "F1"): r})
    with pytest.raises(ValueError):
        G.legality(per, SEEDS)


def test_a1_is_optional_for_the_probe_stage() -> None:
    per = {k: v for k, v in _world().items() if k[0] != "A1"}
    r = G.evaluate(per, SEEDS, capacity=64, has_a1=False)
    assert "h1" not in r and "A1" not in r["accuracy_F1"]


def test_capacity_selection_takes_the_smallest_that_passes() -> None:
    ok = {"ci_high": 0.03}
    bad = {"ci_high": 0.07}
    curve = lambda a, b, c: {"A2-R16": {"drop": a, "plasticity_cost": ok}, "A2-R64": {"drop": b, "plasticity_cost": ok}, "A2-R256": {"drop": c, "plasticity_cost": ok}}
    assert G.select_capacity(curve(ok, ok, ok)) == 16
    assert G.select_capacity(curve(bad, ok, ok)) == 64
    assert G.select_capacity(curve(bad, bad, ok)) == 256
    assert G.select_capacity(curve(bad, bad, bad)) is None
    c = curve(ok, ok, ok)
    c["A2-R16"]["plasticity_cost"] = bad
    assert G.select_capacity(c) == 64


def test_capacity_curves_cover_both_memories() -> None:
    r = _eval()
    assert set(r["capacity_A2"]) == {"A2-R16", "A2-R64", "A2-R256"}
    assert set(r["capacity_A3H"]) == {"A3H-R16", "A3H-R64", "A3H-R256"}


def test_balanced_accuracy_weights_classes_equally() -> None:
    correct = np.array([True, True, True, False])
    answer = np.array([1, 1, 1, 2])
    assert G.balanced_accuracy(correct, answer) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        G.balanced_accuracy(np.array([], dtype=bool), np.array([], dtype=int))


def test_bucket_table_splits_by_gap_and_swap() -> None:
    r = {
        "correct": np.array([True, False, True, True]),
        "correct_8": np.array([True, True, True, True]),
        "swapped": np.array([True, True, False, True]),
        "bucket": np.array([1, 1, 1, 3]),
    }
    t = G.bucket_table(r)
    assert t["short/swapped"] == {"n": 2, "acc": 0.5, "acc_8": 1.0}
    assert t["short/unswapped"]["n"] == 1 and t["long/swapped"]["n"] == 1
    assert "mid/swapped" not in t


def test_permuted_answers_cross_episodes_and_depend_on_the_seed() -> None:
    a, b = _prepared(40), _prepared(40)
    b = dataclasses.replace(b, answer=b.answer + 100)
    out = RP.permute_answers([a, b], 3)
    assert (out[0].answer > 100).any() and (out[1].answer < 100).any()
    other = RP.permute_answers([a, b], 4)
    assert not np.array_equal(out[0].answer, other[0].answer)


def test_past_only_shuffle_depends_on_the_seed() -> None:
    p = _prepared(30, t0=100)
    assert not np.array_equal(RP.past_only_shuffle(p, 1).shuffled, RP.past_only_shuffle(p, 2).shuffled)


def test_primary_events_are_long_gap_only() -> None:
    r = {"bucket": np.array([1, 2, 3, 3]), "swapped": np.array([True, True, True, False])}
    assert G.primary_mask(r).tolist() == [False, False, True, False]
    assert G.unswapped_mask(r).tolist() == [False, False, False, True]


def test_retention_is_judged_on_the_16_class_readout() -> None:
    """A loss visible only with all 16 classes open must still fail retention."""
    h = _eval(_world({("A2-R64", "F1_after"): _events(0.1, acc8=0.85, swapped_acc=0.9)}))["h3_prime"]
    assert not h["gates"]["retention"]


def test_h3_uses_the_requested_capacity() -> None:
    per = _world({("A2-R64", "F1_after"): _events(0.6)})
    assert G.evaluate(per, SEEDS, capacity=16)["h3_prime"]["pass"]
    r = G.evaluate(per, SEEDS, capacity=64)["h3_prime"]
    assert r["capacity"] == 64 and not r["pass"]


def _bump(r, n):
    """Turn one wrong primary event correct in each of ``n`` different episodes."""
    out = dict(r)
    out["correct"] = r["correct"].copy()
    wrong = np.where(G.primary_mask(r) & ~r["correct"])[0]
    _, first = np.unique(r["ep"][wrong], return_index=True)
    assert len(first) >= n
    out["correct"][wrong[first[:n]]] = True
    return out


def test_h2_needs_the_size_not_only_a_positive_interval() -> None:
    a2 = _events(0.85, swapped_acc=0.9)
    h = _eval(_world({("A2-C0", "F1"): a2, ("A3H-C0", "F1"): _bump(a2, 5)}))["h2"]
    assert 0 < h["ci_low"] and h["delta"] < G.H2_MIN_DELTA and not h["pass"]


def test_h2b_needs_the_size_not_only_a_positive_interval() -> None:
    soft = _events(0.90, swapped_acc=0.95)
    h = _eval(_world({("A3S", "F1"): soft, ("A3H-C0", "F1"): _bump(soft, 5)}))["h2b"]
    assert 0 < h["ci_low"] and h["delta"] < G.H2B_MIN_DELTA and not h["pass"]


def test_h1_needs_the_size_not_only_a_positive_interval() -> None:
    per = _world({("A1", "F1"): _events(0.80, swapped_acc=0.9)})
    h = _eval(per)["h1"]
    assert 0 < h["ci_low"] and h["delta"] < G.H1_MIN_DELTA and not h["pass"]


def _thin(r, keep):
    return {k: v[keep] for k, v in r.items()}


def _sized(n_ep, per_ep):
    n = n_ep * per_ep
    return {"correct": np.ones(n, bool), "swapped": np.ones(n, bool), "bucket": np.full(n, G.LONG), "ep": np.repeat(np.arange(n_ep), per_ep)}


@pytest.mark.parametrize("n_ep,per_ep,ok", [(50, 4, True), (49, 8, False), (60, 3, False)])
def test_minimum_sample_counts_events_and_episodes_separately(n_ep, per_ep, ok) -> None:
    r = _sized(n_ep, per_ep)
    assert G.enough_samples({("c", s, "F1"): r for s in SEEDS}, "c", "F1", SEEDS) is ok


def test_minimum_sample_gate_covers_the_f2_events() -> None:
    per = _world()
    r = per["A2-C0", 1, "F2"]
    per["A2-C0", 1, "F2"] = _thin(r, r["ep"] < 10)
    legal = G.legality(per, SEEDS)
    assert legal["min_sample_F1"] and not legal["min_sample_F2"]


def test_unswapped_gate_covers_the_learned_arm() -> None:
    bad = _events(0.85, swapped_acc=0.5)
    per = _world({(c, "F1"): bad for c in G.DETERMINISM_GROUPS[1]})
    legal = G.legality(per, SEEDS)
    assert legal["unswapped_A2"] and not legal["unswapped_A3H"]


@pytest.mark.parametrize("field", ["query_t", "answer", "bucket", "swapped"])
def test_paired_events_must_agree_on_every_identity_field(field) -> None:
    per = _world()
    r = dict(per["A1", 1, "F1"])
    r[field] = r[field].copy()
    r[field][0] = {"query_t": r[field][0] + 1, "answer": r[field][0] + 1, "bucket": 1, "swapped": not r[field][0]}[field]
    per["A1", 1, "F1"] = r
    with pytest.raises(ValueError, match="align"):
        G.paired(per, ("A2-C0", "F1"), ("A1", "F1"), SEEDS)


def test_claims_require_a_valid_run() -> None:
    assert all(_eval()["claims"].values())
    r = _eval(_world({("O", "F1"): _events(0.5)}))
    assert not r["valid"] and r["h1"]["pass"] and not any(r["claims"].values())


def test_claim_h3_requires_its_own_validity() -> None:
    r = _eval(_world({("A2-CN", "F1_after"): _events(0.85, swapped_acc=0.9)}))
    assert r["valid"] and not r["claims"]["h3_prime"] and r["claims"]["h2"]


def test_invalidated_clears_every_claim_and_records_why() -> None:
    r = G.invalidated(_eval(), "changed")
    assert r["valid"] is False and r["invalid_reason"] == "changed" and not any(r["claims"].values())


def test_replay_is_compared_with_the_content_control() -> None:
    d = _eval()["h3_prime"]["replay_minus_cn_8class"]
    assert d["delta"] > 0.5


def test_capacity_curve_reports_the_16_class_drop_separately() -> None:
    per = _world({("A2-R64", "F1_after"): _events(0.1, acc8=0.85, swapped_acc=0.9)})
    row = G.capacity_curve(per, SEEDS, "A2")["A2-R64"]
    assert row["drop"]["delta"] > 0.5 and abs(row["drop_8class"]["delta"]) < 0.05


def test_replay_minus_control_is_read_on_the_8_class_readout() -> None:
    per = _world({("A2-R64", "F1_after"): _events(0.1, acc8=0.85, swapped_acc=0.9)})
    assert _eval(per)["h3_prime"]["replay_minus_cn_8class"]["delta"] > 0.5


def test_dev_and_final_use_the_namespaces_registered_after_the_retired_ones() -> None:
    assert G.NAMESPACES["dev"] == "s3p2b-dev" and G.NAMESPACES["final"] == "s3p2b-final"
    assert G.NAMESPACES["train"] == "s3p2-train" and G.NAMESPACES["probe"] == "s3p2-probe"
