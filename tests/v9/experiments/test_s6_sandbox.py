"""S6 sandbox (pure NumPy): outcomes simulated on reveal only, reveal-once log, pick rules. DESIGN-r2 §2-§3, §6."""
from __future__ import annotations

import ast
import inspect

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S

SIZES = ((4, 7), (6, 5), (8, 3))      # (disk count, samples): ids 0-6, 7-11, 12-14


def _states(sizes=SIZES):
    """States shaped like the runner's candidate states (float64), from real worlds."""
    by_n = {}
    for w, (n, s) in enumerate(sizes):
        ep = W.generate_episode("s6t-sandbox", w, n, steps=20)
        by_n[n] = {"p": np.stack([ep.steps[t].positions for t in range(s)]),
                   "v": np.stack([ep.steps[t].velocities for t in range(s)]),
                   "pil": np.broadcast_to(np.asarray(ep.pillars, float), (s, 3, 3)).copy()}
    return by_n


class Spy:
    """A labeller that records every call and returns labels computed from the states it is given."""

    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, P, V, PIL):
        self.calls.append((P.copy(), V.copy(), PIL.copy()))
        if self.fail:
            raise RuntimeError("sandbox unavailable")
        n = P.shape[1]
        out = {"contact": (np.abs(P[..., :1] - P[..., :1].transpose(0, 2, 1)) < 0.5).astype(np.float32)}
        for k in S.ROLLOUT:
            out[f"p{k}"] = (P + k * 0.01 * V).astype(np.float32)
            out[f"v{k}"] = (V * (1 - 0.01 * k)).astype(np.float32)
        assert out["contact"].shape == (len(P), n, n)
        return out


def _pool(spy=None, **kw):
    return S.CandidatePool(_states(), labeller=spy or Spy(), **kw)


# --- states ---------------------------------------------------------------------------------------------------
def test_states_fields_ids_dtype_and_copies():
    src = _states()
    cp = S.CandidatePool(src, labeller=Spy())
    st = cp.states()
    assert sorted(st) == [4, 6, 8] and len(cp) == 15
    ids = []
    for n, e in st.items():
        assert set(e) == {"id", "p", "v", "pil"}
        assert not set(e) & set(S.LABEL_KEYS)
        assert e["p"].dtype == e["v"].dtype == e["pil"].dtype == np.float32
        np.testing.assert_array_equal(e["p"], src[n]["p"].astype(np.float32))
        np.testing.assert_array_equal(e["pil"], src[n]["pil"].astype(np.float32))
        assert all(not a.flags.writeable and a.flags.owndata for a in e.values())
        ids.extend(e["id"].tolist())
    assert ids == list(range(15))
    assert st[6]["id"].tolist() == [7, 8, 9, 10, 11] and st[8]["id"].tolist() == [12, 13, 14]
    # writing into a returned array (after forcing it writable) does not reach the pool
    st[4]["p"].flags.writeable = True
    st[4]["p"][0, 0, 0] = 99.0
    assert cp.states()[4]["p"][0, 0, 0] != 99.0
    # nor does changing the caller's source arrays
    src[4]["p"][0, 0, 0] = 77.0
    assert cp.states()[4]["p"][0, 0, 0] != 77.0


# --- nothing about outcomes exists before reveal --------------------------------------------------------------
def test_pick_loop_never_simulates():
    spy = Spy()
    cp = _pool(spy)
    rng = np.random.default_rng(5)
    st = cp.states()
    flags = S.geo_flags(st)
    score = np.concatenate([np.linalg.norm(st[n]["v"], axis=-1).max(-1) for n in sorted(st)])
    rem = cp.remaining()
    S.pick_random(rem, 4, rng); S.pick_top(score, rem, 4); S.pick_geo(flags, rem, 4, rng)
    len(cp); cp.revealed_ids(); cp.log(); cp.revealed_pool()
    for name in dir(cp):
        if name.startswith("_") or name == "reveal":
            continue
        attr = getattr(cp, name)
        if callable(attr) and all(p.default is not p.empty for p in inspect.signature(attr).parameters.values()):
            attr()
    assert spy.calls == []
    assert cp._outcomes == {}


def test_reveal_simulates_exactly_the_chosen_states():
    spy = Spy()
    cp = _pool(spy)
    src = _states()
    cp.reveal([13, 2, 8, 0])
    got = sorted(map(tuple, np.concatenate([c[0][:, 0, :] for c in spy.calls]).tolist()))
    want = sorted(map(tuple, np.stack([src[4]["p"][2, 0], src[4]["p"][0, 0], src[6]["p"][1, 0], src[8]["p"][1, 0]]).tolist()))
    assert got == want
    assert all(c[0].dtype == np.float64 for c in spy.calls)          # the simulator gets the float64 states


def test_a_failed_simulation_registers_nothing():
    cp = S.CandidatePool(_states(), labeller=Spy(fail=True))
    with pytest.raises(RuntimeError, match="sandbox unavailable"):
        cp.reveal([0, 1])
    assert cp.revealed_ids().tolist() == [] and cp.log() == [] and cp.remaining().tolist() == list(range(15))
    assert cp._outcomes == {}
    cp._labeller = Spy()
    assert len(cp.reveal([0, 1]).by_n[4]["p"]) == 2 and cp.log() == [{"call": 0, "ids": [0, 1]}]


POOL_ATTRS = {"_labeller", "_pool_type", "_states", "_first_id", "_index", "_revealed", "_revealed_set", "_outcomes", "_log"}


def test_the_simulator_runs_only_on_reveal(monkeypatch):
    """Trap the simulator itself (the module attribute sim_labels reaches): building the pool, every outcome-free
    member and every pick rule call it zero times; a reveal calls it exactly 10 times per revealed sample."""
    real, calls = W.physics, []

    def counting(*a, **k):
        calls.append(1)
        return real(*a, **k)

    states = _states()                                           # world generation itself runs the simulator
    monkeypatch.setattr(W, "physics", counting)
    cp = S.CandidatePool(states)                                 # default labeller: sim_labels
    st = cp.states()
    rem = cp.remaining()
    cp.log(); cp.revealed_ids(); cp.revealed_pool(); len(cp)
    flags = S.geo_flags(st)
    score = np.concatenate([np.linalg.norm(st[n]["v"], axis=-1).max(-1) for n in sorted(st)])
    S.pick_random(rem, 3, np.random.default_rng(0)); S.pick_top(score, rem, 3); S.pick_geo(flags, rem, 3, np.random.default_rng(0))
    assert calls == []
    assert set(vars(cp)) == POOL_ATTRS and cp._outcomes == {}       # nothing extra kept (e.g. a precomputed cache)
    cp.reveal([0, 8, 13])
    assert len(calls) == 3 * max(S.ROLLOUT)
    assert set(vars(cp)) == POOL_ATTRS and set(cp._outcomes) == {0, 8, 13}
    cp.revealed_pool()
    assert len(calls) == 3 * max(S.ROLLOUT)


def test_a_failure_in_a_later_disk_count_group_registers_nothing():
    """A reveal spanning two disk counts whose second group fails leaves no outcome of the first group behind."""
    good = Spy()

    def fail_on_six(P, V, PIL):
        if P.shape[1] == 6:
            raise RuntimeError("second group fails")
        return good(P, V, PIL)

    cp = S.CandidatePool(_states(), labeller=fail_on_six)
    with pytest.raises(RuntimeError, match="second group"):
        cp.reveal([0, 1, 8])
    assert len(good.calls) == 1                                  # the first group was simulated ...
    assert cp._outcomes == {} and cp.revealed_ids().tolist() == [] and cp.log() == []   # ... and dropped


def test_labeller_missing_keys_is_an_error_and_registers_nothing():
    cp = S.CandidatePool(_states(), labeller=lambda P, V, PIL: {"contact": np.zeros((len(P), P.shape[1], P.shape[1]))})
    with pytest.raises(ValueError, match="did not return"):
        cp.reveal([0])
    assert cp.log() == []


# --- structure: only reveal reaches the simulator ---------------------------------------------------------------
def _references(cls_src: str, attr: str) -> set[str]:
    tree = ast.parse(cls_src)
    out = set()
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef):
            if any(isinstance(n, ast.Attribute) and n.attr == attr for n in ast.walk(fn)):
                out.add(fn.name)
    return out


def test_only_reveal_reaches_the_labeller():
    src = inspect.getsource(S.CandidatePool)
    assert _references(src, "_simulate") == {"reveal"}
    assert _references(src, "_labeller") == {"__init__", "_simulate"}
    assert _references(src, "_outcomes") == {"__init__", "reveal", "_assemble"}


def test_class_members_are_the_documented_ones():
    public = {n for n in vars(S.CandidatePool) if not n.startswith("_")}
    assert public == {"states", "remaining", "revealed_ids", "log", "reveal", "revealed_pool"}
    dunders = {n for n, v in vars(S.CandidatePool).items() if n.startswith("__") and callable(v)}
    assert dunders == {"__init__", "__len__"}


# --- reveal ---------------------------------------------------------------------------------------------------------
def test_reveal_returns_exactly_this_calls_samples_with_their_labels():
    spy = Spy()
    cp = _pool(spy)
    src = _states()
    first = cp.reveal([13, 2, 8, 0])
    assert type(first) is S.LabelledPool and sorted(first.by_n) == [4, 6, 8]
    np.testing.assert_array_equal(first.by_n[4]["p"], src[4]["p"][[2, 0]].astype(np.float32))
    lab = spy(src[4]["p"][[2, 0]], src[4]["v"][[2, 0]], src[4]["pil"][[2, 0]])
    for k in S.LABEL_KEYS:
        np.testing.assert_array_equal(first.by_n[4][k], lab[k])
        assert first.by_n[4][k].dtype == np.float32
    second = cp.reveal([9, 3])
    assert sorted(second.by_n) == [4, 6] and len(second.by_n[4]["p"]) == 1 and len(second.by_n[6]["p"]) == 1
    np.testing.assert_array_equal(second.by_n[6]["v"], src[6]["v"][[2]].astype(np.float32))
    for n in first.by_n:
        assert set(first.by_n[n]) == set(S.STATE_KEYS) | set(S.LABEL_KEYS)


def test_reveal_errors_are_atomic():
    cp = _pool()
    cp.reveal([1, 2])
    for bad, err in (([3, 2], ValueError), ([4, 4], ValueError), ([15], IndexError), ([-1], IndexError),
                     ([], ValueError), ([[1]], ValueError), ([1.0], TypeError)):
        with pytest.raises(err):
            cp.reveal(bad)
    assert cp.revealed_ids().tolist() == [1, 2] and len(cp.log()) == 1


def test_log_remaining_and_revealed_pool():
    cp = _pool()
    src = _states()
    assert cp.revealed_pool().by_n == {} and cp.log() == []
    cp.reveal([9, 3])
    cp.reveal(np.array([14, 0], dtype=np.int64))
    assert cp.log() == [{"call": 0, "ids": [9, 3]}, {"call": 1, "ids": [14, 0]}]
    assert cp.revealed_ids().tolist() == [9, 3, 14, 0]
    assert cp.remaining().tolist() == [i for i in range(15) if i not in (9, 3, 14, 0)]
    rp = cp.revealed_pool()
    np.testing.assert_array_equal(rp.by_n[4]["p"], src[4]["p"][[3, 0]].astype(np.float32))   # reveal order
    np.testing.assert_array_equal(rp.by_n[6]["p"], src[6]["p"][[2]].astype(np.float32))
    np.testing.assert_array_equal(rp.by_n[8]["p"], src[8]["p"][[2]].astype(np.float32))
    assert rp.size() == 4
    log = cp.log(); log[0]["ids"].append(77)
    assert cp.log()[0]["ids"] == [9, 3]


def test_sim_labels_is_the_simulator_rollout():
    ep = W.generate_episode("s6t-sandbox-contacts", 0, 8, steps=300)
    hit = [t for t in range(len(ep.steps)) if any(k == "disk" for k, i, j in ep.steps[t].contacts)][:2]
    ts = hit + [t for t in range(len(ep.steps)) if t not in hit][:1]
    assert len(hit) == 2                                     # the sample includes disk contacts
    wall = [t for t in range(len(ep.steps)) if any(k in ("wall", "pillar") for k, i, j in ep.steps[t].contacts)
            and not any(k == "disk" for k, i, j in ep.steps[t].contacts)]
    assert wall
    lw = S.sim_labels(ep.steps[wall[0]].positions[None], ep.steps[wall[0]].velocities[None], np.asarray(ep.pillars, float)[None])
    assert lw["contact"].sum() == 0                          # walls and pillars are not disk contacts
    P = np.stack([ep.steps[t].positions for t in ts]); V = np.stack([ep.steps[t].velocities for t in ts])
    PIL = np.broadcast_to(np.asarray(ep.pillars, float), (3, 3, 3)).copy()
    lab = S.sim_labels(P, V, PIL)
    assert lab["contact"][:2].sum() > 0
    for b in range(3):
        pillars = tuple(map(tuple, PIL[b]))
        p, v, c = W.physics(P[b:b + 1], V[b:b + 1], pillars, log=True)
        np.testing.assert_array_equal(lab["p1"][b], p[0].astype(np.float32))
        np.testing.assert_array_equal(lab["v1"][b], v[0].astype(np.float32))
        pairs = {(min(i, j), max(i, j)) for kind, i, j in c if kind == "disk"}
        got = {(i, j) for i in range(8) for j in range(i + 1, 8) if lab["contact"][b, i, j]}
        assert got == pairs and np.array_equal(lab["contact"][b], lab["contact"][b].T)
        for _ in range(4):
            p, v, _ = W.physics(p, v, pillars)
        np.testing.assert_array_equal(lab["p5"][b], p[0].astype(np.float32))
        for _ in range(5):
            p, v, _ = W.physics(p, v, pillars)
        np.testing.assert_array_equal(lab["v10"][b], v[0].astype(np.float32))
    assert all(a.dtype == np.float32 for a in lab.values())


def test_default_labeller_is_the_simulator():
    cp = S.CandidatePool(_states())
    src = _states()
    got = cp.reveal([7])
    want = S.sim_labels(src[6]["p"][:1], src[6]["v"][:1], src[6]["pil"][:1])
    for k in S.LABEL_KEYS:
        np.testing.assert_array_equal(got.by_n[6][k], want[k])


def test_pool_validation():
    with pytest.raises(ValueError, match="empty"):
        S.CandidatePool({})
    bad = _states(); bad[4]["contact"] = np.zeros((7, 4, 4))
    with pytest.raises(ValueError, match="exactly"):
        S.CandidatePool(bad)
    bad = _states(); bad[4]["v"] = bad[4]["v"][:-1]
    with pytest.raises(ValueError, match="shapes"):
        S.CandidatePool(bad)
    bad = _states(); bad[6]["p"] = bad[6]["p"][:, :4]
    with pytest.raises(ValueError, match="shapes"):
        S.CandidatePool(bad)


# --- pick rules -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("pick", ["random", "top", "geo"])
def test_picks_are_deterministic_unique_and_within_remaining(pick):
    rng0 = np.random.default_rng(0)
    N = 200
    score = rng0.random(N)
    flags = rng0.random(N) < 0.1
    rem = np.sort(rng0.choice(N, 120, replace=False))

    def run(r, seed, k=30):
        g = np.random.default_rng(seed)
        if pick == "random":
            return S.pick_random(r, k, g)
        if pick == "top":
            return S.pick_top(score, r, k)
        return S.pick_geo(flags, r, k, g)

    a = run(rem, 7)
    np.testing.assert_array_equal(a, run(rem, 7))
    np.testing.assert_array_equal(a, run(rem[::-1].copy(), 7))     # caller order does not matter
    assert len(a) == 30 and len(set(a.tolist())) == 30 and set(a.tolist()) <= set(rem.tolist())
    assert a.dtype == np.int64
    with pytest.raises(ValueError):
        run(rem, 7, k=121)
    with pytest.raises(ValueError, match="duplicate"):
        run(np.concatenate([rem, rem[:1]]), 7)
    with pytest.raises(IndexError):
        run(np.concatenate([rem, [-3]]), 7)
    if pick != "random":
        with pytest.raises(IndexError):
            run(np.concatenate([rem, [N]]), 7)


def test_pick_random_matches_prototype_round_zero():
    """explore_s6c round 0: rng.choice(len(allp), per, replace=False)."""
    a = S.pick_random(np.arange(500), 40, np.random.default_rng(11))
    b = np.random.default_rng(11).choice(500, 40, replace=False)
    np.testing.assert_array_equal(a, b)


def test_pick_top_order_and_ties_by_id_ascending():
    score = np.array([0.5, 0.9, 0.9, 0.1, 0.9, 0.7, 0.9])
    rem = np.array([6, 4, 3, 2, 1, 5])
    assert S.pick_top(score, rem, 3).tolist() == [1, 2, 4]
    assert S.pick_top(score, rem, 5).tolist() == [1, 2, 4, 6, 5]
    assert S.pick_top(score, rem, 0).tolist() == []
    with pytest.raises(ValueError, match="non-finite"):
        S.pick_top(np.array([0.0, np.nan, 1.0]), np.array([0, 1, 2]), 1)
    assert S.pick_top(np.array([np.nan, 0.2, 1.0]), np.array([1, 2]), 1).tolist() == [2]


def test_pick_top_ties_at_scale():
    """200 ids on three score levels: exactly the first k of the (-score, id) order. NumPy's argsort,
    which the prototype used, orders ties differently above 16 elements, so this tells them apart."""
    rng = np.random.default_rng(3)
    N = 200
    score = rng.choice([0.1, 0.5, 0.9], N)
    rem = np.sort(rng.choice(N, 150, replace=False))
    want = sorted(rem.tolist(), key=lambda g: (-score[g], g))
    for k in (5, 40, 100, 150):
        assert S.pick_top(score, rem, k).tolist() == want[:k]
    proto = rem[np.argsort(-score[rem])[:100]]
    assert proto.tolist() != want[:100]               # the check bites: the prototype order differs


def test_pick_geo_takes_flagged_first_then_fills():
    N = 50
    flags = np.zeros(N, bool); flags[[3, 7, 11, 40]] = True
    rem = np.array([i for i in range(N) if i != 40])
    got = S.pick_geo(flags, rem, 10, np.random.default_rng(2))
    assert set(got[:3].tolist()) == {3, 7, 11}
    assert not flags[got[3:]].any() and len(set(got.tolist())) == 10
    flags2 = np.zeros(N, bool); flags2[::2] = True
    assert flags2[S.pick_geo(flags2, np.arange(N), 10, np.random.default_rng(2))].all()
    assert len(set(S.pick_geo(np.zeros(N, bool), np.arange(N), 5, np.random.default_rng(2)).tolist())) == 5
    with pytest.raises(ValueError, match="bool"):
        S.pick_geo(flags.astype(int), rem, 3, np.random.default_rng(2))


def test_pick_geo_matches_prototype_stream():
    """explore_s6f: take = rng.choice(flagged, min(per, len)), fill = rng.choice(setdiff1d(rest, take), ...)."""
    rng0 = np.random.default_rng(1)
    N = 300
    flags = rng0.random(N) < 0.05
    rest = np.sort(rng0.choice(N, 250, replace=False))
    r = np.random.default_rng(9)
    flagged = rest[flags[rest]]
    take = r.choice(flagged, min(40, len(flagged)), replace=False)
    fill = r.choice(np.setdiff1d(rest, take), 40 - len(take), replace=False)
    want = np.concatenate([take, fill]).astype(int)
    np.testing.assert_array_equal(S.pick_geo(flags, rest, 40, np.random.default_rng(9)), want)


def test_geo_flags_hand_cases():
    R = W.RADIUS
    pil = np.zeros((1, 3, 3), np.float32)

    def flag(p, v):
        st = {2: {"id": np.array([0]), "p": np.array([p], float), "v": np.array([v], float), "pil": pil}}
        return bool(S.geo_flags(st)[0])

    gap = 2 * R + 0.05
    assert flag([[0, 0], [gap, 0]], [[1.0, 0], [-1.0, 0]])            # closes 0.05 in 0.025 s < dt
    assert not flag([[0, 0], [gap, 0]], [[-1.0, 0], [1.0, 0]])        # receding
    assert not flag([[0, 0], [2 * R + 1.0, 0]], [[1.0, 0], [-1.0, 0]])  # too far for one step
    assert flag([[0, 0], [R, 0]], [[1.0, 0], [0, 0]])                 # overlapping, approaching
    assert not flag([[0, 0], [R, 0]], [[-1.0, 0], [0, 0]])            # overlapping, separating
    assert not flag([[0, 0], [gap, 0]], [[0, 0], [0, 0]])             # at rest
    assert not flag([[0, 0], [0, 3.0]], [[1.0, 0], [1.0, 0]])         # parallel, same velocity
    assert not flag([[0, 0], [2 * R, 0]], [[0, 1.0], [0, -1.0]])      # exactly touching, sliding past (b = c = 0)


def test_geo_flags_needs_all_ids():
    cp = _pool()
    st = cp.states()
    flags = S.geo_flags(st)
    assert flags.shape == (15,) and flags.dtype == bool
    del st[6]
    with pytest.raises(ValueError, match="cover"):
        S.geo_flags(st)
    st = cp.states(); del st[8]
    short = S.geo_flags(st)
    assert short.shape == (12,)
    with pytest.raises(IndexError):
        S.pick_geo(short, cp.remaining(), 3, np.random.default_rng(0))


def test_module_is_pure_numpy():
    tree = ast.parse(inspect.getsource(S))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert not any("mlx" in m for m in mods)
    assert not any(m.endswith(("learned_mlx", "gated")) for m in mods)
