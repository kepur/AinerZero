"""S3 phase 3: world sequences (persist.py) and the promotion store (promotion.py). CPU only."""

from __future__ import annotations

import hashlib
import json
import random

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import cues, persist as PS, promotion as PR, spec
from ainerzero.v9.experiments.s3.store import EpisodicRecord

NS = "test-s3p3-world"


@pytest.fixture(scope="module")
def seq():
    return PS.generate_sequence(NS, 0)


@pytest.fixture(scope="module")
def recs(seq):
    return PS.records_of(seq)


# --- persist ------------------------------------------------------------------------
def _fingerprint(s):
    doc = [
        [list(c) for c in s.persistent],
        sorted(map(list, s.relocated)),
        [
            [
                sorted([list(k), v] for k, v in ep.regime.items()),
                sorted([list(k), v] for k, v in ep.decoy.items()),
                sorted(map(list, ep.volatile)),
                [[st["truth"]["x"], st["truth"]["y"], st["action"]] for st in ep.raw["steps"]],
                ep.raw["events"],
            ]
            for ep in s.episodes
        ],
    ]
    return hashlib.sha256(json.dumps(doc, sort_keys=True).encode()).hexdigest()


@pytest.mark.parametrize(
    "w,digest",
    [
        (0, "1d870e5816416cd6250e6acfbd03abd4dc56b3cd24dfb8fdf97201cc761e8f1d"),
        (1, "cc79a2fdf1157bb4eec7704fb27275e4aaa05c0949d517fbe17a0e58eceb2c4e"),
        (2, "ff59805785fbe722b7153e3f82ef138fb1a91253e4c76f9bb63fe3d8734ff175"),
    ],
)
def test_module_rebuilds_the_exploration_worlds(w, digest) -> None:
    """Digests computed from tier1-explore/explore.py on 2026-11-10 (identical for the module)."""
    assert _fingerprint(PS.generate_sequence("s3p3x-explore", w)) == digest


def test_generation_is_deterministic(seq) -> None:
    assert _fingerprint(PS.generate_sequence(NS, 0)) == _fingerprint(seq)


@pytest.mark.parametrize("name", sorted(PS.REGISTERED))
def test_registered_partitions_are_refused_before_anything_is_generated(name, monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("generated a registered partition")

    monkeypatch.setattr(PS, "make_layout", boom)
    monkeypatch.setattr(PS, "derive_seed", boom)
    with pytest.raises(PermissionError):
        PS.generate_sequence(name, 0)


def test_registered_names_are_the_dev_and_final_partitions() -> None:
    from ainerzero.v9.experiments.s3 import analysis_p3 as A

    assert PS.REGISTERED == {A.NAMESPACES["dev"], A.NAMESPACES["final"]}


def test_content_layer_rules(seq) -> None:
    assert len(seq.persistent) == PS.N_PERSISTENT and len(seq.episodes) == PS.N_EPISODES
    for c in seq.persistent:
        assert seq.before[c] in spec.F1_TOKENS and seq.after[c] in spec.F1_TOKENS
        assert (seq.after[c] != seq.before[c]) == (c in seq.relocated)
    for ep in seq.episodes:
        assert ep.regime == (seq.after if ep.index >= PS.RELOCATION_EPISODE else seq.before)
        assert not set(ep.volatile) & set(seq.persistent) and len(ep.volatile) == PS.N_VOLATILE
        content = ep.raw["content_state"]
        cells = {tuple(map(int, k.split(","))): v for k, v in content["initial_tokens"].items()}
        swaps = {tuple(map(int, k.split(","))): v for k, v in content["swap_times"].items()}
        for c in seq.persistent:
            assert swaps[c] == PS.NEVER
            assert (cells[c] != ep.regime[c]) == ep.decoy[c]
        for c in ep.volatile:
            lo, hi = PS.SWAP_WINDOW
            assert lo <= swaps[c] <= hi and cells[c] in spec.F1_TOKENS


def test_decoy_and_relocation_rates_over_many_worlds() -> None:
    decoys, total, relocated = 0, 0, 0
    for w in range(30):
        s = PS.generate_sequence(NS + "-rates", w, n_episodes=3)
        relocated += len(s.relocated)
        for ep in s.episodes:
            decoys += sum(ep.decoy.values())
            total += len(ep.decoy)
    assert 0.2 < decoys / total < 0.4
    assert 0.3 < relocated / (30 * PS.N_PERSISTENT) < 0.7


def test_persistent_cells_show_one_token_all_episode(seq) -> None:
    seen = 0
    for ep in seq.episodes:
        shown = {}
        for st in ep.raw["steps"]:
            cell = (st["truth"]["x"], st["truth"]["y"])
            if cell in seq.persistent:
                seen += 1
                assert shown.setdefault(cell, st["truth"]["cell_token"]) == st["truth"]["cell_token"]
                assert (st["truth"]["cell_token"] != ep.regime[cell]) == ep.decoy[cell]
    assert seen > 0


def test_separated_cells_respects_spacing_and_bans() -> None:
    cells = [(x, y) for x in range(20) for y in range(20)]
    banned = [(0, 0), (10, 10)]
    got = PS.separated_cells(cells, 6, random.Random(1), banned=banned)
    assert len(got) == 6 and not set(got) & set(banned)
    for i, a in enumerate(got):
        for b in list(got[i + 1 :]) + banned:
            assert abs(a[0] - b[0]) + abs(a[1] - b[1]) >= PS.MIN_CELL_DIST


def test_separated_cells_falls_back_when_spacing_cannot_be_met() -> None:
    cells = [(0, 0), (0, 1), (1, 0)]
    assert sorted(PS.separated_cells(cells, 3, random.Random(0))) == sorted(cells)
    with pytest.raises(RuntimeError):
        PS.separated_cells(cells, 4, random.Random(0))


def test_records_follow_the_frozen_parser(seq, recs) -> None:
    n = sum(len(ep.raw["steps"]) for ep in seq.episodes)
    assert len(recs.ep) == n and recs.start[0] == 0
    for e, ep in enumerate(seq.episodes):
        s0 = recs.start[e]
        steps = ep.raw["steps"]
        assert (recs.ep[s0 : s0 + len(steps)] == e).all()
        assert recs.t[s0 : s0 + len(steps)].tolist() == list(range(len(steps)))
        for i in (0, len(steps) // 2, len(steps) - 1):
            st = steps[i]
            assert recs.token[s0 + i] == st["truth"]["cell_token"]
            assert tuple(recs.xy[s0 + i]) == (float(st["est_pose"][0]), float(st["est_pose"][1]))
            assert tuple(recs.truth_cell[s0 + i]) == (st["truth"]["x"], st["truth"]["y"])
    assert (recs.gtime(np.arange(len(recs.ep))) == recs.ep * spec.T + recs.t).all()


def test_first_arrivals_are_the_first_truth_visits(seq) -> None:
    for e in (1, 7):
        steps = seq.episodes[e].raw["steps"]
        got = dict(PS.first_arrivals(seq, e))
        for c in seq.persistent:
            visits = [s["t"] for s in steps if (s["truth"]["x"], s["truth"]["y"]) == c]
            assert got.get(c) == (visits[0] if visits else None)


# --- promotion: the rule -------------------------------------------------------------
A_, B_, C_ = 1, 2, 3


@pytest.mark.parametrize(
    "votes,slow,rollback,expected",
    [
        ([], None, True, None),
        ([A_], None, True, None),
        ([A_, B_], None, True, None),
        ([A_, A_], None, True, A_),
        ([A_, B_, A_], None, True, A_),
        ([A_, B_, A_, B_], None, True, B_),        # tie on votes -> most recent
        ([A_, B_, B_, A_, A_], None, True, A_),     # more votes wins
        ([A_, A_, B_], A_, True, A_),               # one contrary vote is not enough
        ([A_, A_, B_, B_], A_, True, B_),           # two after the last A -> replaced
        ([A_, A_, B_, C_, B_], A_, True, B_),       # a decoy in between does not reset
        ([A_, A_, B_, A_, B_], A_, True, A_),       # A seen again resets the count
        ([A_, A_, B_, B_], A_, False, A_),          # no rollback
        ([A_, A_, B_, B_, C_, C_], A_, True, C_),   # B and C both twice after A -> most recent
    ],
)
def test_rule_r2(votes, slow, rollback, expected) -> None:
    assert PR.r2_update(votes, slow, rollback=rollback) == expected


def test_rule_needs_two_votes() -> None:
    assert PR.MIN_VOTES == 2


# --- promotion: places ---------------------------------------------------------------
def _rec(xy, ter):
    return EpisodicRecord(t=0, est_pose=(float(xy[0]), float(xy[1]), 0), world_terrain=np.array(ter, dtype=np.int8).reshape(3, 3), observed_token=0)


def test_vectorised_score_is_the_frozen_hand_cue() -> None:
    rng = np.random.default_rng(0)
    q_xy, q_ter = rng.integers(0, 25, 2).astype(float), rng.integers(0, 4, 9)
    axy, ater = rng.integers(0, 25, (50, 2)).astype(float), rng.integers(0, 4, (50, 9))
    ater[:5] = q_ter
    score, ok = PR.place_scores(axy, ater, q_xy, q_ter)
    q = _rec(q_xy, q_ter)
    for i in range(50):
        r = _rec(axy[i], ater[i])
        d, sim = cues.compute_pose_distance(q, r), cues.compute_view_similarity(q, r)
        assert score[i] == pytest.approx(cues.compute_combined_score(d, sim, PR.LAM), abs=1e-12)
        assert ok[i] == (d <= PR.D_MAX and sim >= PR.SIM_MIN)


def test_match_thresholds_and_ties() -> None:
    ter = np.zeros(9, dtype=np.int8)
    other = ter.copy()
    other[0] = 1
    axy = np.array([[5.0, 0.0], [0.0, 5.0], [0.0, 5.5], [0.0, 0.0]])
    ater = np.stack([ter, ter, ter, other])
    assert PR.best_match(axy, ater, np.zeros(2), ter) == 0  # d=5 accepted, tie -> lowest index
    assert PR.best_match(axy[2:], ater[2:], np.zeros(2), ter) is None  # d=5.5 and different terrain refused
    assert PR.best_match(axy[:0], ater[:0], np.zeros(2), ter) is None


def test_dwell_starts() -> None:
    xy = np.array([[0, 0], [0, 0], [0, 0], [1, 0], [1, 0], [1, 0], [1, 0], [2, 0]], dtype=float)
    tok = np.array([3, 3, 5, 0, 4, 0, 4, 4])
    assert PR.dwell_starts(xy, tok) == [0, 2, 4, 6, 7]


# --- promotion: the store ------------------------------------------------------------
TER = np.zeros(9, dtype=np.int8)


def _obs(*places):
    """places: (x, token) on a line with identical terrain."""
    xy = np.array([[float(x), 0.0] for x, _ in places]).reshape(-1, 2)
    ter = np.stack([TER] * len(places)) if places else np.zeros((0, 9), dtype=np.int8)
    tok = np.array([k for _, k in places], dtype=np.int32)
    return xy, ter, tok


def test_store_promotes_after_two_episodes_and_logs_versions() -> None:
    s = PR.PromotionStore(rollback=True)
    assert s.absorb(0, *_obs((0, A_))) is False
    assert s.answer(np.zeros(2), TER) == (None, None)
    assert s.absorb(1, *_obs((1, A_))) is True  # same place within D_MAX
    assert s.answer(np.zeros(2), TER) == (0, A_)
    assert len(s.versions) == 2 and PR.verify_chain(s.versions) == []
    assert s.absorb(2, *_obs((0, A_))) is False and len(s.versions) == 2


def test_one_vote_per_episode_most_common_then_first() -> None:
    s = PR.PromotionStore(rollback=True)
    s.absorb(0, *_obs((0, B_), (0, A_), (0, A_)))
    s.absorb(1, *_obs((0, B_), (0, A_)))
    assert s.items[0].votes == [(0, A_), (1, B_)]
    assert len(s.items) == 1


def test_episodes_must_be_absorbed_in_order() -> None:
    s = PR.PromotionStore(rollback=True)
    with pytest.raises(ValueError):
        s.absorb(1, *_obs((0, A_)))


def test_rollback_replaces_and_no_rollback_keeps() -> None:
    eps = [[(0, A_)], [(0, A_)], [(0, B_)], [(0, B_)]]
    for rollback, expected in ((True, B_), (False, A_)):
        s = PR.PromotionStore(rollback=rollback)
        for e, places in enumerate(eps):
            s.absorb(e, *_obs(*places))
        assert s.answer(np.zeros(2), TER)[1] == expected
    assert len(PR.PromotionStore(rollback=True).versions) == 1


def test_observations_within_reach_join_an_item() -> None:
    s = PR.PromotionStore(rollback=True)
    s.absorb(0, *_obs((4, A_)))
    s.absorb(1, *_obs((0, A_), (10, C_)))  # x=0 is 4 from the item at 4; x=10 is 6 away
    assert len(s.items) == 2 and s.items[0].votes == [(0, A_), (1, A_)]


def test_queries_prefer_promoted_items_over_closer_unpromoted_ones() -> None:
    s = PR.PromotionStore(rollback=True)
    s.absorb(0, *_obs((5, A_)))
    s.absorb(1, *_obs((5, A_), (11, B_)))  # the item at 11 is 6 from the one at 5: separate
    assert s.items[0].slow == A_ and s.items[1].slow is None
    assert s.match(np.array([10.0, 0.0]), TER, slow_only=False) == 1
    assert s.answer(np.array([10.0, 0.0]), TER) == (0, A_)


def test_snapshot_answers_match_the_store() -> None:
    rng = np.random.default_rng(3)
    s = PR.PromotionStore(rollback=True)
    for e in range(8):
        places = [(int(x), int(k)) for x, k in zip(rng.integers(0, 40, 6), rng.integers(1, 4, 6))]
        s.absorb(e, *_obs(*places))
        snap = json.loads(json.dumps(s.snapshot()))
        for x in range(-3, 44):
            q = np.array([float(x), 0.0])
            assert PR.answer_from_snapshot(snap, q, TER) == s.answer(q, TER)[1]
    assert snap["hash"] == s.head and snap == json.loads(json.dumps(s.versions[-1]))


def test_restore_and_replay_reproduces_the_chain() -> None:
    rng = np.random.default_rng(4)
    eps = [[(int(x), int(k)) for x, k in zip(rng.integers(0, 30, 5), rng.integers(1, 4, 5))] for _ in range(9)]
    s = PR.PromotionStore(rollback=True)
    states = []
    for e, places in enumerate(eps):
        s.absorb(e, *_obs(*places))
        states.append(json.loads(json.dumps(s.state())))
    for k in range(len(eps) - 1):
        r = PR.PromotionStore.restore(states[k])
        for e in range(k + 1, len(eps)):
            r.absorb(e, *_obs(*eps[e]))
        assert r.state() == s.state()


def test_tampered_version_log_is_detected() -> None:
    s = PR.PromotionStore(rollback=True)
    for e, x in enumerate([0, 0, 0]):
        s.absorb(e, *_obs((x, A_)))
    v = json.loads(json.dumps(s.versions))
    assert PR.verify_chain(v) == []
    for path in (("items", 0, 1), ("items", 0, 2, 0), ("items", 0, 3, 4), ("items", 0, 4, 0, 1), ("episode",), ("parent",)):
        t = json.loads(json.dumps(s.versions))
        target = t[1]
        for k in path[:-1]:
            target = target[k]
        target[path[-1]] = 99 if path[-1] != "parent" else "x"
        assert PR.verify_chain(t), path


def test_version_hash_commits_to_parent_episode_and_content() -> None:
    item = [0, A_, [1.0, 2.0], [0] * 9, [[0, A_], [1, A_]]]
    base = PR.version_hash("p", 3, [item])
    assert PR.version_hash("q", 3, [item]) != base
    assert PR.version_hash(None, 3, [item]) != base
    assert PR.version_hash("p", 4, [item]) != base
    for i, v in ((1, B_), (2, [1.0, 3.0]), (3, [1] + [0] * 8), (4, [[0, A_], [2, A_]])):
        changed = list(item)
        changed[i] = v
        assert PR.version_hash("p", 3, [changed]) != base, i
    assert PR.version_hash("p", 3, [list(item)]) == base


def test_versions_carry_anchors_terrain_and_promotion_evidence() -> None:
    s = PR.PromotionStore(rollback=True)
    s.absorb(0, *_obs((0, A_)))
    s.absorb(1, *_obs((1, A_)))
    v = s.versions[-1]
    assert v["episode"] == 1 and v["parent"] == s.versions[0]["hash"]
    assert v["items"] == [[0, A_, [0.0, 0.0], [0] * 9, [[0, A_], [1, A_]]]]
    s.absorb(2, *_obs((0, A_)))
    assert len(s.versions) == 2 and s.versions[-1]["items"][0][4] == [[0, A_], [1, A_]]  # evidence as at promotion


def test_mode_vote_and_ties() -> None:
    assert PR.mode_vote([A_, B_, B_]) == B_
    assert PR.mode_vote([A_, B_, A_, B_]) == B_  # tie -> most recent
    assert PR.mode_vote([C_]) == C_


def test_tie_and_member_diagnostics_do_not_change_matching() -> None:
    ter = np.zeros(9, dtype=np.int8)
    axy = np.array([[2.0, 0.0], [0.0, 2.0], [0.0, 4.0]])
    assert PR.best_match_tied(axy, np.stack([ter] * 3), np.zeros(2), ter) == (0, True)
    assert PR.best_match_tied(axy[1:], np.stack([ter] * 2), np.zeros(2), ter) == (0, False)
    s = PR.PromotionStore(rollback=True)
    s.absorb(0, *_obs((0, A_), (0, B_)), tags=["a", "b"])
    s.absorb(1, *_obs((1, A_), (1, B_)), tags=["c", "d"])
    assert s.items[0].members == ["a", "b", "c", "d"] and s.items[0].tag == "a"
    assert s.diag["votes"] == 2 and s.diag["vote_ties"] == 2 and s.diag["writes_matched"] == 3


def test_truth_keyed_store_uses_the_same_rule() -> None:
    t = PR.TruthKeyedStore(rollback=True)
    for k in (A_, A_, B_, B_):
        t.absorb([(1, 1), (1, 1)], [k, k])
    assert t.votes[(1, 1)] == [A_, A_, B_, B_]
    assert t.answer((1, 1)) == B_ and t.answer((2, 2)) is None
    m = PR.TruthKeyedStore(rollback=True)
    m.absorb([(3, 3)] * 3, [B_, A_, A_])  # most common, as the estimated-pose store votes
    m.absorb([(3, 3)] * 2, [C_, A_])      # tie -> first observed
    assert m.votes[(3, 3)] == [A_, C_]


def test_promotion_writes_no_parameters() -> None:
    import ainerzero.v9.experiments.s3.promotion as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "mlx" not in src and "torch" not in src
