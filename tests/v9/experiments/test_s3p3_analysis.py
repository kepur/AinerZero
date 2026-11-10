"""S3 phase 3 analysis: events, policies, bootstrap, gates and legality. CPU only."""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import analysis_p3 as A
from ainerzero.v9.experiments.s3 import data as D
from ainerzero.v9.experiments.s3 import persist as PS
from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.cues import rank_candidates
from ainerzero.v9.experiments.s3.store import EpisodicStore

NS = "test-s3p3-analysis"
REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def world():
    seq = PS.generate_sequence(NS, 1)
    cols, log = A.analyse_world(seq)
    return seq, PS.records_of(seq), A.to_arrays(cols), log


# --- events and policies on a real world ----------------------------------------------
def test_queries_are_first_arrivals_from_episode_one(world) -> None:
    seq, R, ev, _ = world
    q = ev["kind"] == A.KIND_QUERY
    assert (ev["episode"][q] >= 1).all()
    want = sorted((e, t) for e in range(1, len(seq.episodes)) for _, t in PS.first_arrivals(seq, e))
    assert sorted(zip(ev["episode"][q].tolist(), ev["t"][q].tolist())) == want
    for i in np.flatnonzero(q):
        e = int(ev["episode"][i])
        cell = tuple(R.truth_cell[R.start[e] + ev["t"][i]])
        assert ev["answer"][i] == seq.episodes[e].regime[cell]
        assert ev["decoy"][i] == seq.episodes[e].decoy[cell]
        assert ev["relocated"][i] == int(e >= PS.RELOCATION_EPISODE and cell in seq.relocated)


def test_fast_events_are_long_swapped_readouts(world) -> None:
    seq, _, ev, _ = world
    f = ev["kind"] == A.KIND_FAST
    want = sorted((e, x["t"]) for e, ep in enumerate(seq.episodes) for x in ep.raw["events"] if x["bucket"] == spec.BUCKET_LONG and x["swapped"])
    assert sorted(zip(ev["episode"][f].tolist(), ev["t"][f].tolist())) == want and want


def test_copy_is_the_shown_token_and_answers_match_labels(world) -> None:
    _, _, ev, _ = world
    q = ev["kind"] == A.KIND_QUERY
    assert (ev["pred_C"][q] == ev["shown"][q]).all()
    assert ((ev["shown"][q] != ev["answer"][q]) == (ev["decoy"][q] == 1)).all()


def test_fast_route_equals_the_frozen_phase_2_retrieval(world) -> None:
    seq, R, ev, _ = world
    f = np.flatnonzero(ev["kind"] == A.KIND_FAST)
    for i in f[:: max(1, len(f) // 15)]:
        e, t = int(ev["episode"][i]), int(ev["t"][i])
        store = EpisodicStore()
        for s in seq.episodes[e].raw["steps"]:
            store.add_step(s)
        top = rank_candidates(store, t, mode="both", lam=A.LAM, gap=A.GAP)[0][0]
        g = A.top1(R, A.fast_pool(R, e, t), R.start[e] + t)
        assert g == R.start[e] + top.t
        assert ev["pred_G"][i] == ev["pred_C"][i] == top.observed_token


def test_pools() -> None:
    seq = PS.generate_sequence(NS, 2, n_episodes=3)
    R = PS.records_of(seq)
    f = A.fast_pool(R, 2, 40)
    assert (R.ep[f] == 2).all() and R.t[f].max() == 40 - A.GAP and len(f) == 40 - A.GAP + 1
    assert len(A.fast_pool(R, 2, 3)) == 0
    u = A.unified_pool(R, 2, 40)
    assert set(u.tolist()) == set(range(R.start[2])) | set(f.tolist())


def test_unified_pool_prefers_the_current_episode_only_on_ties(world) -> None:
    _, R, _, _ = world
    qi = R.start[3] + 100
    a, b = R.start[1] + 100, R.start[3] + 50
    tied = PS.Records(R.ep, R.t, R.xy.copy(), R.terrain.copy(), R.token, R.truth_cell, R.start)
    tied.xy[[a, b]] = tied.xy[qi]
    tied.terrain[[a, b]] = tied.terrain[qi]
    assert A.top1(tied, np.array([a, b]), qi) == b
    tied.xy[b] = tied.xy[qi] + np.array([1.0, 0.0])
    assert A.top1(tied, np.array([a, b]), qi) == a  # a closer record from an earlier episode wins


def test_latest_match_takes_the_latest_by_global_time(world) -> None:
    _, R, _, _ = world
    qi = R.start[4] + 10
    c = R.start[1] + 5, R.start[3] + 2, R.start[2] + 300
    fake = PS.Records(R.ep, R.t, R.xy.copy(), R.terrain.copy(), R.token.copy(), R.truth_cell, R.start)
    for k, i in enumerate(c):
        fake.xy[i], fake.terrain[i], fake.token[i] = fake.xy[qi], fake.terrain[qi], k + 1
    assert A.latest_match(fake, np.array(c), qi) == 2
    assert A.latest_match(fake, np.array([], dtype=np.int64), qi) is None


def test_memory_answers_use_only_earlier_episodes(world) -> None:
    """L and G must not see the episode being queried (no look-ahead, no current-episode writes)."""
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, ev, _ = world
    ends = list(R.start[1:]) + [len(R.ep)]
    obs = [np.array([R.start[e] + i for i in PR.dwell_starts(R.xy[R.start[e] : ends[e]], R.token[R.start[e] : ends[e]])], dtype=np.int64) for e in range(len(seq.episodes))]
    store = PR.PromotionStore(rollback=True)
    q = ev["kind"] == A.KIND_QUERY
    for e in range(len(seq.episodes)):
        past = np.concatenate([np.zeros(0, dtype=np.int64)] + obs[:e])
        for i in np.flatnonzero(q & (ev["episode"] == e)):
            qi = R.start[e] + int(ev["t"][i])
            latest = A.latest_match(R, past, qi)
            assert ev["pred_L"][i] == (ev["shown"][i] if latest is None else latest)
            slow = store.answer(R.xy[qi], R.terrain[qi])[1]
            assert ev["pred_G"][i] == (ev["pred_L"][i] if slow is None else slow)
        store.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]])


def test_world_log_checks_pass_and_are_complete(world) -> None:
    seq, _, ev, log = world
    ch = log["checks"]
    assert ch["chain"] == [] and ch["snapshot_mismatch"] == [] and ch["replay_mismatch"] == []
    assert ch["n_queries"] == int((ev["kind"] == A.KIND_QUERY).sum()) > 0
    assert ch["n_checkpoints"] == len(seq.episodes)
    hashes = {v["hash"] for v in log["versions"]}
    assert all(q["version"] in hashes for q in log["queries"])
    assert len(log["observations"]) == sum(1 for _ in log["observations"]) > 0
    json.dumps(log)


def test_reproducibility_check_catches_a_stale_answer(world) -> None:
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, _, log = world
    queries = [dict(q) for q in log["queries"]]
    hit = next(i for i, q in enumerate(queries) if q["slow"] is not None)
    queries[hit]["slow"] = (queries[hit]["slow"] % 8) + 1
    s = PR.PromotionStore(rollback=True)
    s.versions = log["versions"]
    ch = A.reproducibility_checks(s, [], [], R, queries)
    assert ch["snapshot_mismatch"] == [queries[hit]["episode"]]


def test_reproducibility_check_catches_hidden_state(monkeypatch) -> None:
    """A store whose replay depends on something outside its state must fail the replay check."""
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq = PS.generate_sequence(NS, 3, n_episodes=6)
    calls = {"n": 0}
    original = PR.r2_update

    def leaky(votes, slow, *, rollback):
        calls["n"] += 1
        return original(votes, slow, rollback=rollback) if calls["n"] < 40 else slow

    monkeypatch.setattr(PR, "r2_update", leaky)
    _, log = A.analyse_world(seq)
    assert log["checks"]["replay_mismatch"]


def test_labels_carry_the_period_and_first_arrival(world) -> None:
    seq, _, ev, _ = world
    q = ev["kind"] == A.KIND_QUERY
    assert (ev["first_ok"][q] == 1).all()
    for i in np.flatnonzero(q):
        e = int(ev["episode"][i])
        cells = [c for c, t in PS.first_arrivals(seq, e) if t == ev["t"][i]]
        assert any(ev["tok_before"][i] == seq.before[c] and ev["tok_after"][i] == seq.after[c] for c in cells)


def test_first_ok_catches_a_wrong_query_step(monkeypatch) -> None:
    seq = PS.generate_sequence(NS, 5, n_episodes=5)
    real = PS.first_arrivals

    def last_visit(s, e):
        out = []
        for c, _ in real(s, e):
            visits = [st["t"] for st in s.episodes[e].raw["steps"] if (st["truth"]["x"], st["truth"]["y"]) == c]
            out.append((c, visits[-1]))
        return out

    monkeypatch.setattr(PS, "first_arrivals", last_visit)
    ev = A.to_arrays(A.analyse_world(seq, full=False)[0])
    q = ev["kind"] == A.KIND_QUERY
    assert (ev["first_ok"][q] == 0).any()


# --- the control arms ----------------------------------------------------------------
def test_alpha_penalises_earlier_episodes(world) -> None:
    _, R, _, _ = world
    qi = R.start[3] + 100
    a, b = R.start[1] + 100, R.start[3] + 50
    fake = PS.Records(R.ep, R.t, R.xy.copy(), R.terrain.copy(), R.token, R.truth_cell, R.start)
    fake.xy[a] = fake.xy[qi]
    fake.terrain[[a, b]] = fake.terrain[qi]
    fake.xy[b] = fake.xy[qi] + np.array([1.5, 0.0])
    idx = np.array([a, b])
    assert A.top1(fake, idx, qi) == a
    assert A.top1(fake, idx, qi, alpha=0.5) == a  # 2 episodes back costs 1.0 < 1.5
    assert A.top1(fake, idx, qi, alpha=1.0) == b  # costs 2.0 > 1.5
    assert A.ALPHAS == {"U0": 0.0, "U05": 0.5, "U1": 1.0, "U2": 2.0}


def test_eligible_only_respects_the_place_gate(world) -> None:
    _, R, _, _ = world
    qi = R.start[2] + 80
    fake = PS.Records(R.ep, R.t, R.xy.copy(), R.terrain.copy(), R.token, R.truth_cell, R.start)
    a = R.start[2] + 10
    fake.xy[a] = fake.xy[qi] + np.array([6.0, 0.0])
    fake.terrain[a] = fake.terrain[qi]
    assert A.top1(fake, np.array([a]), qi) == a
    assert A.top1(fake, np.array([a]), qi, eligible_only=True) is None


def test_offsets_shift_each_episode_by_a_constant(world) -> None:
    seq, R, _, _ = world
    for k in A.OFFSETS:
        S = A.shifted(R, seq, k)
        assert (S.terrain == R.terrain).all() and (S.token == R.token).all()
        shifts = set()
        for e in range(len(seq.episodes)):
            d = S.xy[R.ep == e] - R.xy[R.ep == e]
            assert (d == d[0]).all() and (np.abs(d[0]) <= k).all()
            shifts.add(tuple(d[0]))
        assert len(shifts) > 1
        assert (A.shifted(R, seq, k).xy == S.xy).all()


def test_offsets_follow_the_registered_seed(world) -> None:
    import random as _random

    seq, R, _, _ = world
    for k in A.OFFSETS:
        S = A.shifted(R, seq, k)
        for e in range(len(seq.episodes)):
            rng = _random.Random(D.derive_seed(seq.namespace, "offset", seq.world_index, e, k))
            want = (rng.randint(-k, k), rng.randint(-k, k))
            got = S.xy[R.start[e]] - R.xy[R.start[e]]
            assert tuple(got) == want, (k, e)


def test_offset_zero_within_episode_retrieval_is_unchanged() -> None:
    seq = PS.generate_sequence(NS, 4, n_episodes=4)
    a, _ = A.analyse_world(seq, full=False)
    b, _ = A.analyse_world(seq, offset=3, full=False)
    a, b = A.to_arrays(a), A.to_arrays(b)
    f = a["kind"] == A.KIND_FAST
    assert (a["pred_C"][f] == b["pred_C"][f]).all() and (a["pred_G"][f] == b["pred_G"][f]).all()


def test_token_permutation_is_a_fixed_bijection(world) -> None:
    seq = world[0]
    p = A.token_permutation(seq)
    assert sorted(p) == sorted(p.values()) == list(spec.F1_TOKENS)
    assert p == A.token_permutation(seq) and p != A.token_permutation(PS.generate_sequence(NS, 2, n_episodes=1))


def test_control_arm_definitions(world) -> None:
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, ev, _ = world
    perm = A.token_permutation(seq)
    q = ev["kind"] == A.KIND_QUERY
    assert (ev["pred_GP"][q] == np.array([perm[int(g)] for g in ev["pred_G"][q]])).all()
    ends = list(R.start[1:]) + [len(R.ep)]
    obs = [np.array([R.start[e] + i for i in PR.dwell_starts(R.xy[R.start[e] : ends[e]], R.token[R.start[e] : ends[e]])], dtype=np.int64) for e in range(len(seq.episodes))]
    G = PR.PromotionStore(rollback=True)
    for e in range(len(seq.episodes)):
        for i in np.flatnonzero(q & (ev["episode"] == e)):
            qi = R.start[e] + int(ev["t"][i])
            j = G.match(R.xy[qi], R.terrain[qi], slow_only=False)
            want = ev["pred_L"][i] if j is None else PR.mode_vote([k for _, k in G.items[j].votes])
            assert ev["pred_MODE"][i] == want
            f = A.top1(R, A.fast_pool(R, e, int(ev["t"][i])), qi, eligible_only=True)
            assert ev["pred_SR"][i] == (ev["pred_G"][i] if f is None else R.token[f])
            assert ev["sr_fast"][i] == int(f is not None)
        G.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]])
    f = ev["kind"] == A.KIND_FAST
    for i in np.flatnonzero(f)[::7]:
        e, t = int(ev["episode"][i]), int(ev["t"][i])
        qi = R.start[e] + t
        for name, alpha in A.ALPHAS.items():
            u = A.top1(R, A.unified_pool(R, e, t), qi, alpha=alpha)
            assert ev[f"pred_{name}"][i] == R.token[u]
        assert ev["u0_past"][i] == int(R.ep[A.top1(R, A.unified_pool(R, e, t), qi)] < e)


def _dwell_obs(R, n_ep):
    from ainerzero.v9.experiments.s3 import promotion as PR

    ends = list(R.start[1:]) + [len(R.ep)]
    return [np.array([R.start[e] + i for i in PR.dwell_starts(R.xy[R.start[e] : ends[e]], R.token[R.start[e] : ends[e]])], dtype=np.int64) for e in range(n_ep)]


def test_no_rollback_truth_keyed_and_fast_routing_arms(world) -> None:
    """Independent versions of G-NR, LT, GT (truth-keyed, sequential R2) and the FAST side of G-SR."""
    import collections
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, ev, _ = world
    obs = _dwell_obs(R, len(seq.episodes))
    G = PR.PromotionStore(rollback=True)
    NR = PR.PromotionStore(rollback=False)
    votes, slow = collections.defaultdict(list), {}
    q = ev["kind"] == A.KIND_QUERY
    f = ev["kind"] == A.KIND_FAST
    checked = collections.Counter()
    for e in range(len(seq.episodes)):
        past = np.concatenate([np.zeros(0, dtype=np.int64)] + obs[:e])
        for i in np.flatnonzero((q | f) & (ev["episode"] == e)):
            qi = R.start[e] + int(ev["t"][i])
            if q[i]:
                tok = NR.answer(R.xy[qi], R.terrain[qi])[1]
                assert ev["pred_GNR"][i] == (ev["pred_L"][i] if tok is None else tok)
                cell = tuple(int(v) for v in R.truth_cell[qi])
                at = [j for j in past if tuple(int(v) for v in R.truth_cell[j]) == cell]
                lt = int(R.token[max(at, key=lambda j: (R.ep[j], R.t[j]))]) if at else int(ev["shown"][i])
                assert ev["pred_LT"][i] == lt
                assert ev["pred_GT"][i] == (lt if slow.get(cell) is None else slow[cell])
                checked["query"] += 1
            else:
                eligible = A.top1(R, A.fast_pool(R, e, int(ev["t"][i])), qi, eligible_only=True)
                if eligible is not None:
                    want = R.token[eligible]
                else:
                    tok = G.answer(R.xy[qi], R.terrain[qi])[1]
                    lm = A.latest_match(R, past, qi)
                    want = tok if tok is not None else (lm if lm is not None else R.token[qi])
                    checked["fast_fallback"] += 1
                assert ev["pred_SR"][i] == want and ev["sr_fast"][i] == int(eligible is not None)
                checked["fast"] += 1
        for st in (G, NR):
            st.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]])
        per = collections.defaultdict(collections.Counter)
        for j in obs[e]:
            per[tuple(int(v) for v in R.truth_cell[j])][int(R.token[j])] += 1
        for cell, cnt in per.items():
            votes[cell].append(cnt.most_common(1)[0][0])
            slow[cell] = PR.r2_update(votes[cell], slow.get(cell), rollback=True)
    assert checked["query"] > 0 and checked["fast"] > 0


def test_lt_falls_back_to_the_shown_token_not_to_l() -> None:
    """When the true cell was never observed before, LT copies the current view even if L matched elsewhere.

    Such queries are rare (1 in 30 worlds of 12 episodes); world 9 of this stand-in namespace has one."""
    seq = PS.generate_sequence(NS + "-lt", 9)
    R = PS.records_of(seq)
    ev = A.to_arrays(A.analyse_world(seq, full=False)[0])
    obs = _dwell_obs(R, len(seq.episodes))
    discriminating = 0
    for i in np.flatnonzero(ev["kind"] == A.KIND_QUERY):
        e = int(ev["episode"][i])
        qi = R.start[e] + int(ev["t"][i])
        past = np.concatenate([np.zeros(0, dtype=np.int64)] + obs[:e])
        if not any((R.truth_cell[j] == R.truth_cell[qi]).all() for j in past):
            assert ev["pred_LT"][i] == ev["shown"][i]
            discriminating += int(ev["pred_L"][i] != ev["shown"][i])
    assert discriminating == 1


def test_item_counts_and_rates_match_independent_counts(world) -> None:
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, ev, log = world
    obs = _dwell_obs(R, len(seq.episodes))
    G = PR.PromotionStore(rollback=True)
    for e in range(len(seq.episodes)):
        G.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]], tags=obs[e].tolist())
    cell = lambda j: tuple(int(v) for v in R.truth_cell[j])
    mixed = sum(1 for it in G.items if len({cell(m) for m in it.members}) >= 2)
    slow_cells = [cell(it.tag) for it in G.items if it.slow is not None]
    several = sum(1 for c in seq.persistent if slow_cells.count(c) >= 2)
    off = sum(1 for c in slow_cells if c not in seq.persistent)
    d = log["items"]
    assert (d["mixed_items"], d["persistent_with_several_slow"], d["slow_off_persistent"], d["slow"]) == (mixed, several, off, len(slow_cells))
    assert d["items"] == len(G.items) and d["versions"] == len(G.versions) - 1
    k2 = {"passed": True, "worlds": 1, "queries": int((ev["kind"] == A.KIND_QUERY).sum())}
    k2b = dict(k2, fast_events=int((ev["kind"] == A.KIND_FAST).sum()))
    diag = A.evaluate(ev, [log], stage=None, n_worlds=1, external=k2, external_gen=k2b)["diagnostics"]
    q = ev["kind"] == A.KIND_QUERY
    hit = q & (ev["g_slow"] == 1)
    assert diag["D8_query_tie_rate"] == pytest.approx(ev["query_tie"][hit].mean())
    assert diag["D8_slow_hit_rate"] == pytest.approx(ev["g_slow"][q].mean())
    fe1 = (ev["kind"] == A.KIND_FAST) & (ev["episode"] >= 1)
    assert diag["D2_U0_won_by_past"] == pytest.approx(ev["u0_past"][fe1].mean())


def test_query_tie_flag_matches_an_independent_count(world) -> None:
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, ev, _ = world
    obs = _dwell_obs(R, len(seq.episodes))
    G = PR.PromotionStore(rollback=True)
    q = ev["kind"] == A.KIND_QUERY
    for e in range(len(seq.episodes)):
        for i in np.flatnonzero(q & (ev["episode"] == e)):
            qi = R.start[e] + int(ev["t"][i])
            slow = [it for it in G.items if it.slow is not None]
            if not slow:
                assert ev["query_tie"][i] == 0
                continue
            score, ok = PR.place_scores(np.array([it.anchor_xy for it in slow]), np.array([it.anchor_ter for it in slow]), R.xy[qi], R.terrain[qi])
            best = score[ok].max() if ok.any() else None
            assert ev["query_tie"][i] == int(best is not None and int((score[ok] == best).sum()) > 1)
        G.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]])


def test_replay_check_compares_the_whole_state_not_only_versions(world) -> None:
    """K3 must notice a restore that loses an unpromoted item's votes even when the version chain survives."""
    from ainerzero.v9.experiments.s3 import promotion as PR

    seq, R, _, _ = world
    obs = _dwell_obs(R, len(seq.episodes))
    s = PR.PromotionStore(rollback=True)
    checkpoints = []
    for e in range(len(seq.episodes)):
        s.absorb(e, R.xy[obs[e]], R.terrain[obs[e]], R.token[obs[e]])
        checkpoints.append(json.loads(json.dumps(s.state())))
    lonely = [k for k, it in enumerate(checkpoints[-2]["items"]) if it[4] is None and len(it[3]) == 1 and it[0] == len(checkpoints[-2]["items"]) - 1]
    assert lonely, "need an unpromoted item created in the second-to-last episode"
    tampered = json.loads(json.dumps(checkpoints))
    tampered[-2]["items"][lonely[0]][3].append([len(seq.episodes) - 2, 99])
    ch = A.reproducibility_checks(s, tampered, obs, R, [])
    assert ch["replay_mismatch"] == [len(seq.episodes) - 2]
    r = PR.PromotionStore.restore(tampered[-2])
    r.absorb(len(seq.episodes) - 1, R.xy[obs[-1]], R.terrain[obs[-1]], R.token[obs[-1]])
    assert r.versions == s.versions  # the versions alone would not have shown it


# --- statistics ------------------------------------------------------------------------
def _events(n_worlds, per_world, p_a, p_b, seed=0, shared=False):
    rng = np.random.default_rng(seed)
    n = n_worlds * per_world
    ev = {k: np.zeros(n, dtype=np.int64) for k in A.FIELDS}
    ev["world"] = np.repeat(np.arange(n_worlds), per_world)
    ev["answer"] = np.ones(n, dtype=np.int64)
    if shared:  # all-or-nothing within a world: strongly clustered
        wa = rng.random(n_worlds) < p_a
        wb = rng.random(n_worlds) < p_b
        a, b = wa[ev["world"]], wb[ev["world"]]
    else:
        a, b = rng.random(n) < p_a, rng.random(n) < p_b
    ev["pred_G"] = np.where(a, 1, 0)
    ev["pred_C"] = np.where(b, 1, 0)
    return ev


def test_paired_bootstrap_estimates_and_covers() -> None:
    ev = _events(200, 20, 0.7, 0.5)
    r = A.paired(ev, np.ones(4000, bool), "G", "C")
    assert r["delta"] == pytest.approx(0.2, abs=0.03)
    assert r["ci_low"] < r["delta"] < r["ci_high"] and r["n_worlds"] == 200 and r["n_events"] == 4000
    assert r["bonf_low"] < r["ci_low"] and r["bonf_high"] > r["ci_high"]


def test_interval_levels_are_the_registered_ones() -> None:
    ev = _events(60, 10, 0.6, 0.5, seed=5)
    r = A.paired(ev, np.ones(600, bool), "G", "C", m=10)
    d = (ev["pred_G"] == 1).astype(float) - (ev["pred_C"] == 1).astype(float)
    worlds, idx = np.unique(ev["world"], return_inverse=True)
    n_w, d_w = np.bincount(idx).astype(float), np.bincount(idx, weights=d)
    draws = np.random.default_rng(A.BOOT_SEED).integers(0, len(worlds), size=(A.BOOT_N, len(worlds)))
    boot = d_w[draws].sum(1) / n_w[draws].sum(1)
    assert (r["ci_low"], r["ci_high"]) == tuple(np.quantile(boot, [0.025, 0.975]))
    assert (r["bonf_low"], r["bonf_high"]) == tuple(np.quantile(boot, [0.0025, 0.9975]))
    assert A.LEVEL == 0.95 and A.N_COMPARISONS == len(A.COMPARISONS) + 3 * len(A.OFFSETS)


def test_bootstrap_resamples_whole_worlds() -> None:
    clustered = A.paired(_events(100, 20, 0.6, 0.4, shared=True), np.ones(2000, bool), "G", "C")
    independent = A.paired(_events(100, 20, 0.6, 0.4), np.ones(2000, bool), "G", "C")
    assert (clustered["ci_high"] - clustered["ci_low"]) > 2 * (independent["ci_high"] - independent["ci_low"])


def test_bootstrap_is_seeded() -> None:
    ev = _events(50, 10, 0.6, 0.5)
    m = np.ones(500, bool)
    assert A.paired(ev, m, "G", "C") == A.paired(ev, m, "G", "C")
    assert A.paired(ev, m, "G", "C", seed=1)["ci_low"] != A.paired(ev, m, "G", "C")["ci_low"]


def test_empty_comparison_reports_nothing() -> None:
    ev = _events(5, 5, 0.9, 0.1)
    r = A.paired(ev, np.zeros(25, bool), "G", "C")
    assert r["delta"] is None and r["n_events"] == 0


# --- synthetic events for the contract gates ---------------------------------------------
def _synthetic(n_worlds=40):
    """Every set present, labels consistent, all memory policies right."""
    rows = []
    for w in range(n_worlds):
        for e in range(1, 12):
            rows += [dict(kind=A.KIND_FAST, world=w, episode=e, t=100 + e, answer=1, shown=2, first_ok=1)] * 2
        rows += [dict(kind=A.KIND_FAST, world=w, episode=0, t=90, answer=1, shown=2, first_ok=1)] * 2
        rows += [dict(kind=A.KIND_QUERY, world=w, episode=2, t=10, answer=1, shown=2, decoy=1, relocated=0, tok_before=1, tok_after=1, first_ok=1)] * 8
        rows += [dict(kind=A.KIND_QUERY, world=w, episode=7, t=20, answer=3, shown=2, decoy=1, relocated=1, tok_before=1, tok_after=3, first_ok=1)] * 5
        rows += [dict(kind=A.KIND_QUERY, world=w, episode=7, t=30, answer=3, shown=3, decoy=0, relocated=1, tok_before=1, tok_after=3, first_ok=1)] * 6
        rows += [dict(kind=A.KIND_QUERY, world=w, episode=3, t=40, answer=1, shown=1, decoy=0, relocated=0, tok_before=1, tok_after=1, first_ok=1)] * 10
    ev = {k: np.array([r.get(k, 0) for r in rows], dtype=np.int64) for k in A.FIELDS}
    for p in A.POLICIES:
        ev[f"pred_{p}"] = ev["answer"].copy()
    ev["pred_C"] = np.where(ev["kind"] == A.KIND_QUERY, ev["shown"], ev["answer"])
    return ev


def _logs(ev=None, **bad):
    """World logs that agree with the events row by row (K6), with optional check problems."""
    ev = _synthetic() if ev is None else ev
    checks = {"chain": [], "snapshot_mismatch": [], "replay_mismatch": [], "n_queries": 29, "n_checkpoints": 12} | bad
    items = {k: 0 for k in ("items", "slow", "slow_off_persistent", "persistent_with_several_slow", "mixed_items", "versions", "writes_matched", "write_ties", "votes", "vote_ties")}
    out = []
    for w in sorted(set(ev["world"].tolist())):
        m = ev["world"] == w
        q = m & (ev["kind"] == A.KIND_QUERY)
        f = m & (ev["kind"] == A.KIND_FAST)
        queries = [{"episode": int(ev["episode"][i]), "t": int(ev["t"][i]), "answer": int(ev["answer"][i]), "shown": int(ev["shown"][i]),
                    "decoy": int(ev["decoy"][i]), "relocated": int(ev["relocated"][i]), "pred_G": int(ev["pred_G"][i]), "pred_L": int(ev["pred_L"][i])}
                   for i in np.flatnonzero(q)]
        fast = [[int(ev["episode"][i]), int(ev["t"][i]), int(ev["answer"][i])] for i in np.flatnonzero(f)]
        out.append({"world": w, "checks": checks, "items": items, "queries": queries, "fast_events": fast})
    return out


def _ok(ev):
    q, f = int((ev["kind"] == A.KIND_QUERY).sum()), int((ev["kind"] == A.KIND_FAST).sum())
    w = len(set(ev["world"].tolist()))
    return ({"passed": True, "worlds": w, "queries": q, "versions": 3, "n_problems": 0, "problems": []},
            {"passed": True, "worlds": w, "queries": q, "fast_events": f, "n_problems": 0, "problems": []})


DEFAULT = object()


def _eval(ev=None, logs=None, *, stage=None, n_worlds=40, external=DEFAULT, external_gen=DEFAULT, offsets=None):
    ev = _synthetic() if ev is None else ev
    k2, k2b = _ok(ev)
    return A.evaluate(ev, _logs(ev) if logs is None else logs, stage=stage, n_worlds=n_worlds,
                      external=k2 if external is DEFAULT else external, external_gen=k2b if external_gen is DEFAULT else external_gen, offsets=offsets)


ALL_GATES = {"K1_versions", "K2_independent", "K2b_generator", "K3_restore_replay", "K4_labels", "K6_events_match_log", "valid"}


def test_synthetic_events_satisfy_the_contract() -> None:
    r = _eval()
    assert r["valid"] and set(r["legality"]) == ALL_GATES


@pytest.mark.parametrize("passed", [False, "yes", None, 1])
def test_k2_needs_a_passing_independent_report(passed) -> None:
    k2, _ = _ok(_synthetic())  # counts right, only the verdict differs
    if passed is None:
        del k2["passed"]
    else:
        k2["passed"] = passed
    r = _eval(external=k2)
    assert not r["legality"]["K2_independent"]["passed"] and not r["valid"]
    assert not _eval(external=None)["legality"]["K2_independent"]["passed"]


@pytest.mark.parametrize("field,value", [("worlds", 20), ("queries", 1159), ("worlds", None)])
def test_k2_counts_must_match(field, value) -> None:
    k2, _ = _ok(_synthetic())
    k2[field] = value
    assert not _eval(external=k2)["legality"]["K2_independent"]["passed"]


@pytest.mark.parametrize("field,value", [("passed", False), ("worlds", 39), ("queries", 1), ("fast_events", 959)])
def test_k2b_must_pass_with_matching_counts(field, value) -> None:
    _, k2b = _ok(_synthetic())
    k2b[field] = value
    r = _eval(external_gen=k2b)
    assert not r["legality"]["K2b_generator"]["passed"] and not r["valid"]
    assert not _eval(external_gen=None)["legality"]["K2b_generator"]["passed"]


@pytest.mark.parametrize("col", ["pred_G", "pred_L", "answer", "shown", "decoy", "relocated", "t", "episode"])
def test_k6_catches_events_that_differ_from_the_log(col) -> None:
    ev = _synthetic()
    logs = _logs(ev)
    i = int(np.flatnonzero(ev["kind"] == A.KIND_QUERY)[17])
    ev[col][i] = ev[col][i] + 1
    r = A.evaluate(ev, logs, stage=None, n_worlds=40, external=_ok(ev)[0], external_gen=_ok(ev)[1])
    assert not r["legality"]["K6_events_match_log"]["queries_match"] and not r["valid"]


def test_k6_catches_fast_events_and_missing_worlds() -> None:
    ev = _synthetic()
    logs = _logs(ev)
    ev2 = {k: v.copy() for k, v in ev.items()}
    ev2["answer"][int(np.flatnonzero(ev["kind"] == A.KIND_FAST)[3])] = 7
    assert not A.log_linkage(ev2, logs)["fast_events_match"]
    assert not A.log_linkage(ev, logs[:-1])["passed"]
    assert A.log_linkage(ev, logs)["passed"]


@pytest.mark.parametrize("key", ["chain", "snapshot_mismatch"])
def test_k1_version_problems_invalidate(key) -> None:
    logs = _logs()
    logs[7]["checks"] = dict(logs[7]["checks"], **{key: [1]})
    r = _eval(logs=logs)
    assert not r["legality"]["K1_versions"]["passed"] and not r["valid"]


def test_k1_needs_checked_queries() -> None:
    assert not _eval(logs=_logs(n_queries=0))["legality"]["K1_versions"]["passed"]


@pytest.mark.parametrize("bad", [{"replay_mismatch": [2]}, {"n_checkpoints": 1}])
def test_k3_replay_problems_invalidate(bad) -> None:
    r = _eval(logs=_logs(**bad))
    assert not r["legality"]["K3_restore_replay"]["passed"] and not r["valid"]


def _flip(ev, sel, col, value):
    i = int(np.flatnonzero(A.event_sets(ev)[sel])[0])
    ev[col][i] = value
    return ev


@pytest.mark.parametrize(
    "sel,col,value,check",
    [
        ("clean", "decoy", 1, "decoy_iff_shown_differs"),       # a clean query labelled decoy
        ("decoy", "decoy", 0, "decoy_iff_shown_differs"),       # a decoy labelled clean
        ("decoy_stable", "tok_before", 5, "stable_answer_is_episode0_value"),
        ("relocated", "tok_after", 5, "relocated_answer_is_new_value"),
        ("relocated", "tok_before", 3, "relocated_answer_is_new_value"),
        ("query", "first_ok", 0, "query_is_first_arrival"),
    ],
)
def test_k4_label_checks(sel, col, value, check) -> None:
    r = _eval(ev=_flip(_synthetic(), sel, col, value))
    assert r["legality"]["K4_labels"][check] is False and not r["legality"]["K4_labels"]["passed"] and not r["valid"]


def test_k4_relocation_label_one_episode_late_is_caught() -> None:
    ev = _synthetic()
    reloc = A.event_sets(ev)["relocated"]
    ev["relocated"][reloc] = 0  # the reviewer's probe: relocated queries labelled stable
    assert not _eval(ev=ev)["legality"]["K4_labels"]["stable_answer_is_episode0_value"]


def test_k4_needs_every_set() -> None:
    ev = _synthetic()
    keep = ~A.event_sets(ev)["decoy"]
    ev = {k: v[keep] for k, v in ev.items()}
    assert not _eval(ev=ev)["legality"]["K4_labels"]["all_sets_present"]


def test_k5_band() -> None:
    assert A.EXPECTED_PER_100 == {"fast": 2030, "decoy_stable": 800, "relocated": 1070}
    assert A.SAMPLE_BAND == {"fast": 0.07, "decoy_stable": 0.13, "relocated": 0.21}
    have = {k: int(A.event_sets(_synthetic())[k].sum()) for k in A.EXPECTED_PER_100}
    assert have == {"fast": 960, "decoy_stable": 320, "relocated": 440}
    # 40 worlds: fast 755-869, stable 278-362, relocated 338-518; 960 fast events are too many
    assert not _eval(stage="final")["legality"]["K5_samples"]["passed"]
    # 45 worlds: fast 850-977, stable 313-407, relocated 380-583: all inside
    r = _eval(stage="final", n_worlds=45)["legality"]["K5_samples"]
    assert r["passed"], r
    assert not _eval(stage="final", n_worlds=52)["legality"]["K5_samples"]["passed"]  # stable 362-470: 320 too few
    assert "K5_samples" not in _eval(stage=None)["legality"]
    band = _eval(stage="final", n_worlds=100)["legality"]["K5_samples"]["band"]
    assert band["fast"] == pytest.approx([2030 * 0.93, 2030 * 1.07]) and band["relocated"] == pytest.approx([1070 * 0.79, 1070 * 1.21])


def test_registered_comparisons_use_their_sets_and_arms(monkeypatch) -> None:
    ev = _synthetic()
    sets = A.event_sets(ev)
    seen = []
    real = A.paired

    def spy(e, mask, a, b, **kw):
        seen.append((int(mask.sum()), a, b))
        return real(e, mask, a, b, **kw)

    monkeypatch.setattr(A, "paired", spy)
    k2, k2b = _ok(ev)
    r = A.evaluate(ev, _logs(ev), stage=None, n_worlds=40, external=k2, external_gen=k2b, offsets={k: ev for k in A.OFFSETS})
    want = [(int(sets[sel].sum()), a, b) for _, sel, a, b in A.COMPARISONS]
    want += [(int(sets[sel].sum()), a, b) for _ in A.OFFSETS for _, sel, a, b in A.OFFSET_COMPARISONS]
    assert seen == want
    assert set(r["descriptive"]) == {c[0] for c in A.COMPARISONS} and set(r["offsets"]) == {str(k) for k in A.OFFSETS}


def test_registered_comparison_list() -> None:
    assert [(c[1], c[2], c[3]) for c in A.COMPARISONS] == [
        ("decoy", "G", "GP"), ("decoy", "G", "C"), ("query", "G", "C"),
        ("fast_e1", "C", "U0"), ("fast_e1", "C", "U05"), ("fast_e1", "C", "U1"), ("fast_e1", "C", "U2"),
        ("decoy_stable", "G", "L"), ("decoy_stable", "G", "MODE"), ("decoy_stable", "MODE", "L"), ("decoy_stable", "G", "GNR"),
        ("relocated", "G", "GNR"), ("relocated", "G", "L"), ("relocated", "G", "MODE"),
        ("query", "SR", "G"), ("fast", "SR", "G"),
        ("decoy_stable", "GT", "G"), ("decoy_stable", "LT", "L"), ("relocated", "GT", "G"), ("relocated", "LT", "L"),
        ("clean", "C", "G"),
    ]
    assert [(c[1], c[2], c[3]) for c in A.OFFSET_COMPARISONS] == [("fast_e1", "C", "U0"), ("decoy_stable", "G", "L"), ("relocated", "G", "GNR")]
    assert A.OFFSETS == (1, 2, 3, 5)


def test_event_sets() -> None:
    s = A.event_sets(_synthetic())
    assert int(s["fast_e1"].sum()) == 40 * 22 and int(s["fast"].sum()) == 40 * 24
    assert int(s["decoy"].sum()) == 40 * 13 and int(s["clean"].sum()) == 40 * 16
    assert not (s["decoy_stable"] & s["relocated"]).any()


def test_recovery_curve_and_first_episode() -> None:
    ev = _synthetic()
    reloc = A.event_sets(ev)["relocated"]
    ev["pred_G"][reloc] = 0
    r = A.recovery_curve(ev, reloc)
    assert r["by_episode"]["7"]["G"] == 0.0 and r["first_episode_G_beats_C"] is None
    assert A.recovery_curve(_synthetic(), reloc)["first_episode_G_beats_C"] == 7


def test_first_episode_needs_g_strictly_above_c() -> None:
    ev = {k: np.zeros(4, dtype=np.int64) for k in A.FIELDS}
    ev["episode"] = np.array([7, 7, 8, 8])
    ev["answer"] = np.ones(4, dtype=np.int64)
    for p in ("L", "GNR", "MODE"):
        ev[f"pred_{p}"] = np.ones(4, dtype=np.int64)
    ev["pred_C"] = np.array([1, 0, 0, 0])
    ev["pred_G"] = np.array([0, 1, 1, 0])  # episode 7: G = C = 0.5; episode 8: G 0.5 > C 0
    assert A.recovery_curve(ev, np.ones(4, bool))["first_episode_G_beats_C"] == 8


def test_invalidated_keeps_the_result_and_marks_it() -> None:
    r = _eval()
    x = A.invalidated(r, "why")
    assert x["valid"] is False and x["invalid_reason"] == "why" and r["valid"] is True
    assert x["descriptive"] == r["descriptive"]


# --- partitions --------------------------------------------------------------------------
def test_namespaces_are_distinct_and_disjoint_from_earlier_phases() -> None:
    ours = list(A.NAMESPACES.values())
    assert len(set(ours)) == 4
    earlier = ["s3p1-train", "s3p1-dev", "s3p1-final", "s3p1-probe", "s3p2-train", "s3p2-dev", "s3p2-final", "s3p2-probe",
               "s3p2b-dev", "s3p2b-final", "s3p3x-explore", "s3p3x-rv1109", "s3p3x-smoke"]
    assert not set(ours) & set(earlier)
    seeds = {}
    for ns in ours + earlier:
        for w in range(300):
            for tag in (("world", w), ("persist", w)):
                s = D.derive_seed(ns, *tag)
                assert s not in seeds or seeds[s][0] == ns, (ns, tag, seeds.get(s))
                seeds[s] = (ns, tag)


def test_no_test_generates_a_registered_partition() -> None:
    pat = re.compile(r"allow_registered\s*=\s*True")
    for p in (REPO / "tests").rglob("*.py"):
        assert not pat.search(p.read_text(encoding="utf-8")), p


# --- r2 recheck: K6 verdict, world set, K7, tie-rate denominator --------------------------
def test_k6_verdict_fails_when_only_fast_events_differ() -> None:
    ev = _synthetic()
    logs = _logs(ev)
    logs[3]["fast_events"][0][2] += 1
    r = A.log_linkage(ev, logs)
    assert r["queries_match"] and not r["fast_events_match"] and not r["passed"]


def test_k6_catches_an_extra_world_without_events() -> None:
    ev = _synthetic()
    logs = _logs(ev) + [{"world": 40, "queries": [], "fast_events": [], "checks": _logs(ev)[0]["checks"], "items": _logs(ev)[0]["items"]}]
    r = A.log_linkage(ev, logs)
    assert r["queries_match"] and r["fast_events_match"] and not r["passed"]


def test_k7_offset_files_must_hold_the_same_events() -> None:
    ev = _synthetic()
    same = {k: {c: v.copy() for c, v in ev.items()} for k in A.OFFSETS}
    for k in A.OFFSETS:
        same[k]["pred_G"] = same[k]["pred_G"] + k  # predictions may differ
    assert _eval(ev=ev, offsets=same)["legality"]["K7_offsets_same_events"]["passed"]
    bad = {k: {c: v.copy() for c, v in d.items()} for k, d in same.items()}
    bad[3]["answer"][5] += 1
    r = _eval(ev=ev, offsets=bad)["legality"]["K7_offsets_same_events"]
    assert not r["passed"] and r["differing"] == {"3": ["answer"]}
    missing = {k: v for k, v in same.items() if k != 5}
    assert not _eval(ev=ev, offsets=missing)["legality"]["K7_offsets_same_events"]["passed"]
    assert not _eval(ev=ev, stage="final", offsets=None)["legality"]["K7_offsets_same_events"]["passed"]
    assert "K7_offsets_same_events" not in _eval(ev=ev)["legality"]


def test_query_tie_rate_is_over_queries_answered_from_slow() -> None:
    ev = _synthetic()
    q = np.flatnonzero(ev["kind"] == A.KIND_QUERY)
    ev["g_slow"][q[:400]] = 1
    ev["query_tie"][q[:40]] = 1
    d = _eval(ev=ev)["diagnostics"]
    assert d["D8_query_tie_rate"] == pytest.approx(40 / 400) and d["D8_slow_hit_rate"] == pytest.approx(400 / len(q))
