"""S4 phase 1 learned dynamics (MLX): the code constraint, message symmetries, training pools,
training and the filter wrapper. Runs on the MLX CPU device."""

from __future__ import annotations

import ast
import inspect
import math
import textwrap
from pathlib import Path

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
from mlx.utils import tree_flatten  # noqa: E402

from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

NS = "test-s4-learned"
SRC = Path(L.__file__)


@pytest.fixture(autouse=True)
def _cpu():
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(prev)


@pytest.fixture(scope="module")
def eps():
    return [W.generate_episode(NS, w, n, steps=60) for w, n in enumerate([4, 6, 8])]


@pytest.fixture(scope="module")
def pool(eps):
    return L.make_pool(eps, 300, np.random.default_rng(0), W.physics)


def _params(m):
    return {k: np.array(v) for k, v in tree_flatten(m.parameters())}


def _model(arm, seed=0):
    mx.random.seed(seed)
    m = L.Dynamics(arm)
    mx.eval(m.parameters())
    return m


def _state(n=6, seed=0):
    rng = np.random.default_rng(seed)
    p = rng.uniform(2, 8, (1, n, 2)).astype(np.float32)
    v = rng.normal(0, 1, (1, n, 2)).astype(np.float32)
    pil = np.array([[[2.0, 2.0, 0.5], [7.0, 3.0, 0.8], [5.0, 8.0, 0.6]]], dtype=np.float32)
    return p, v, pil


# --- code constraint (DESIGN-r3 §3) ---------------------------------------------------------------
def test_model_code_does_not_use_the_world_physics() -> None:
    tree = ast.parse(SRC.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
            imported |= {f"{node.module}.{a.name}" for a in node.names}
    assert not any("experiments.s4" in m or m.endswith((".world", ".models", ".filter")) for m in imported), imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & {"world", "W", "true_physics", "bounce"}


def test_forward_path_has_no_contact_rule() -> None:
    """The forward pass may compare only to cut messages at MSG_RADIUS: no branch on contact
    distance, no reflection, no NumPy."""
    fns = [L.node_features, L.pair_geometry, L.Dynamics.messages, L.Dynamics.__call__]
    compares = []
    for fn in fns:
        t = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        for node in ast.walk(t):
            if isinstance(node, ast.Compare):
                compares.append(ast.unparse(node))
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                assert node.value.id != "np", f"{fn.__qualname__} uses NumPy: {ast.unparse(node)}"
                assert not (node.value.id == "mx" and node.attr in {"where", "abs", "sign", "maximum", "minimum"}), ast.unparse(node)
    # the one numeric comparison is the message cut; the other two choose code paths, not values
    assert sorted(compares) == sorted(["dist < MSG_RADIUS", "self.arm == 'L-int-s'", "vec is not None"]), compares


# --- symmetries ------------------------------------------------------------------------------------
def _rot(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]], dtype=np.float32)


@pytest.mark.parametrize("theta", [0.7, 2.3, -1.9])
def test_canonical_messages_are_rotation_equivariant(theta) -> None:
    m = _model("L-int-c")
    p, v, _ = _state(seed=1)
    R = _rot(theta)
    c = np.array([5.0, 5.0], dtype=np.float32)
    p2 = (p - c) @ R.T + c
    v2 = v @ R.T
    l1, s1, w1 = m.messages(mx.array(p), mx.array(v))
    l2, s2, w2 = m.messages(mx.array(p2), mx.array(v2))
    assert np.allclose(np.array(l1), np.array(l2), atol=1e-4)
    assert np.allclose(np.array(s1), np.array(s2), atol=1e-4)
    assert np.allclose(np.array(w1) @ R.T, np.array(w2), atol=1e-4)
    # the plain L-int messages use raw coordinates and are not invariant (the test can see a difference)
    q = _model("L-int")
    a, _, _ = q.messages(mx.array(p), mx.array(v))
    b, _, _ = q.messages(mx.array(p2), mx.array(v2))
    assert not np.allclose(np.array(a), np.array(b), atol=1e-3)


@pytest.mark.parametrize("arm", ["L-int", "L-int-c"])
def test_messages_are_translation_invariant(arm) -> None:
    m = _model(arm)
    p, v, _ = _state(seed=2)
    a = m.messages(mx.array(p), mx.array(v))
    b = m.messages(mx.array(p + np.float32(1.25)), mx.array(v))
    for x, y in zip(a, b):
        if x is not None:
            assert np.allclose(np.array(x), np.array(y), atol=1e-4)


def test_independent_arm_never_sees_other_disks() -> None:
    p, v, pil = _state(n=4, seed=3)
    q = p.copy()
    q[0, 1] = p[0, 0] + np.array([0.5, 0.0], dtype=np.float32)   # disk 1 right next to disk 0
    for arm, same in (("L-ind", True), ("L-int", False)):
        m = _model(arm)
        a = np.array(m(mx.array(p), mx.array(v), mx.array(pil))[1])[0, 0]
        b = np.array(m(mx.array(q), mx.array(v), mx.array(pil))[1])[0, 0]
        assert np.allclose(a, b, atol=1e-6) == same, arm


def test_messages_stop_at_the_message_radius() -> None:
    m = _model("L-int")
    p = np.array([[[3.0, 3.0], [3.0 + L.MSG_RADIUS + 0.2, 3.0], [8.0, 8.0]]], dtype=np.float32)
    v = np.zeros_like(p)
    pil = _state()[2]
    q = p.copy()
    q[0, 2] = [8.5, 7.0]                                       # a far disk moves: disk 0 unchanged
    a = np.array(m(mx.array(p), mx.array(v), mx.array(pil))[1])[0, 0]
    b = np.array(m(mx.array(q), mx.array(v), mx.array(pil))[1])[0, 0]
    assert np.array_equal(a, b)
    q[0, 1] = [3.0 + L.MSG_RADIUS - 0.2, 3.0]                  # the neighbour comes inside the radius
    c = np.array(m(mx.array(q), mx.array(v), mx.array(pil))[1])[0, 0]
    assert not np.allclose(a, c, atol=1e-6)


# --- pools -----------------------------------------------------------------------------------------
def test_perturbation_rules() -> None:
    rng = np.random.default_rng(7)
    pos = np.array([[2.0 + i, 5.0] for i in range(6)])
    vel = np.zeros((6, 2))
    p, v = L.perturb(pos, vel, rng, exact=True)
    assert np.array_equal(p, pos) and np.array_equal(v, vel)
    counts = [len(L.perturb(pos, vel, rng, exact=False)[0]) for _ in range(20000)]
    assert abs(np.mean(counts) - (6 * (1 - L.P_DROP) + L.GHOSTS)) < 0.03
    # noise level per disk without drops and ghosts
    old = (L.P_DROP, L.GHOSTS)
    try:
        L.P_DROP, L.GHOSTS = 0.0, 0.0
        dp, dv = [], []
        for _ in range(5000):
            p, v = L.perturb(pos, vel, rng, exact=False)
            dp.append(np.linalg.norm(p - pos, axis=1)); dv.append(v - vel)
        dp, dv = np.concatenate(dp), np.concatenate(dv)
    finally:
        L.P_DROP, L.GHOSTS = old
    big = L.P_HIDDEN * math.exp(-0.3 ** 2 / (2 * L.HIDDEN_SIGMA[0] ** 2))
    assert abs(np.mean(dp > 0.3) - big) < 0.01
    small = dp < 0.15
    assert 0.19 < np.std(dv[small]) < 0.26
    # a ghost copies a disk already in the sample: the same velocity, a position a few GHOST_SIGMA away
    vel2 = np.arange(12, dtype=np.float64).reshape(6, 2) + 1.0
    old = (L.P_DROP, L.GHOSTS, L.VISIBLE_SIGMA, L.HIDDEN_SIGMA)
    try:
        L.P_DROP, L.GHOSTS, L.VISIBLE_SIGMA, L.HIDDEN_SIGMA = 0.0, 3.0, (0.0, 0.0), (0.0, 0.0)
        ghosts = 0
        for _ in range(200):
            p, v = L.perturb(pos, vel2, rng, exact=False)
            assert np.array_equal(p[:6], pos) and np.array_equal(v[:6], vel2)
            for g in range(6, len(p)):
                src = [k for k in range(g) if np.array_equal(v[g], v[k])]
                assert src and 0 < min(np.linalg.norm(p[g] - p[k]) for k in src) < 6 * L.GHOST_SIGMA
                ghosts += 1
        assert ghosts > 300
    finally:
        L.P_DROP, L.GHOSTS, L.VISIBLE_SIGMA, L.HIDDEN_SIGMA = old


def test_pool_has_the_exact_share(eps) -> None:
    seen = {s.positions.astype(np.float32).tobytes() for e in eps for s in e.steps}
    pool = L.make_pool(eps, 2000, np.random.default_rng(3), W.physics)
    hits = sum(e["p"][i].tobytes() in seen
               for e in pool.by_n.values() for i in range(len(e["p"])))
    # pools store float32: compare the float32 bytes; a perturbed state never equals a truth state
    assert abs(hits / pool.size() - L.EXACT_FRAC) < 0.04
    ex = L.make_pool(eps, 50, np.random.default_rng(4), W.physics, exact_frac=1.0)
    assert set(ex.by_n) <= {4, 6, 8}


def test_pool_keeps_each_sample_with_the_pillars_of_its_own_world(eps) -> None:
    """An exact sample is a truth state, so the episode it came from is known without the pool's help."""
    where = {s.positions.astype(np.float32).tobytes(): w for w, e in enumerate(eps) for s in e.steps}
    pool = L.make_pool(eps, 600, np.random.default_rng(3), W.physics)
    found = set()
    for e in pool.by_n.values():
        for i in range(len(e["p"])):
            w = where.get(e["p"][i].tobytes())
            if w is not None:
                assert np.array_equal(e["pil"][i], np.array(eps[w].pillars, dtype=np.float32))
                found.add(w)
    assert found == {0, 1, 2}
    assert len({np.array(e.pillars).tobytes() for e in eps}) == 3


def test_zero_output_is_constant_velocity() -> None:
    """The network adds a correction to constant velocity: with a zero output layer the step is
    p + v DT with v unchanged, and a position output of 1 moves the disk by P_SCALE."""
    p, v, pil = _state()
    for arm in ("L-ind", "L-int", "L-int-c"):
        m = _model(arm, 1)
        m.out.weight = mx.zeros_like(m.out.weight)
        m.out.bias = mx.zeros_like(m.out.bias)
        pn, vn, _, _ = m(mx.array(p), mx.array(v), mx.array(pil))
        assert np.allclose(np.array(pn), p + v * W.DT, atol=1e-6) and np.array_equal(np.array(vn), v)
        m.out.bias = mx.array([1.0, -2.0, 0.5, 0.25])
        pn, vn, _, _ = m(mx.array(p), mx.array(v), mx.array(pil))
        assert np.allclose(np.array(pn) - (p + v * W.DT), np.array([1.0, -2.0]) * L.P_SCALE, atol=1e-5)
        assert np.allclose(np.array(vn) - v, [0.5, 0.25], atol=1e-6)


def test_pool_labels_match_the_simulator_sample_by_sample(eps, pool) -> None:
    by_pil = {np.array(e.pillars, dtype=np.float32).tobytes(): e for e in eps}
    checked = 0
    for n, e in pool.by_n.items():
        for i in range(0, len(e["p"]), max(len(e["p"]) // 4, 1)):
            ep = by_pil[e["pil"][i].tobytes()]
            p = e["p"][i][None].astype(np.float64); v = e["v"][i][None].astype(np.float64)
            # inputs are stored in float32, labels came from the float64 draw: compare with a tolerance
            q, u, c = W.physics(p, v, ep.pillars, log=True)
            contact = np.zeros((n, n))
            for kind, a, b in c:
                if kind == "disk":
                    contact[a, b] = contact[b, a] = 1
            assert np.array_equal(contact, e["contact"][i])
            assert np.allclose(q[0], e["p1"][i], atol=1e-5) and np.allclose(u[0], e["v1"][i], atol=1e-5)
            for k in range(2, 11):
                q, u, _ = W.physics(q, u, ep.pillars)
                if k in L.ROLLOUT:
                    assert np.allclose(q[0], e[f"p{k}"][i], atol=1e-3) and np.allclose(u[0], e[f"v{k}"][i], atol=1e-3)
            checked += 1
    assert checked >= 10


def test_batched_labels_equal_per_sample_labels(eps) -> None:
    """Steps 2-10 run batched per episode and disk count; the result is identical to one sample at a time."""
    def per_sample(episodes, n_samples, rng, physics, **kw):
        return L.make_pool(episodes, n_samples, rng, lambda p, v, pil, **k: _one_by_one(physics, p, v, pil, **k), **kw)

    def _one_by_one(physics, p, v, pil, log=False):
        outs = [physics(p[b:b + 1], v[b:b + 1], pil, log=log) for b in range(len(p))]
        return np.concatenate([o[0] for o in outs]), np.concatenate([o[1] for o in outs]), outs[0][2]

    a = L.make_pool(eps, 200, np.random.default_rng(9), W.physics)
    b = per_sample(eps, 200, np.random.default_rng(9), W.physics)
    assert a.by_n.keys() == b.by_n.keys()
    for n in a.by_n:
        for k in a.by_n[n]:
            assert np.array_equal(a.by_n[n][k], b.by_n[n][k]), (n, k)


def test_sigma_pool(eps) -> None:
    sp = L.make_sigma_pool(eps, 400, np.random.default_rng(5))
    assert set(sp.by_n) <= {4, 6, 8}
    nxt = {}
    for ep in eps:
        for a, b in zip(ep.steps[:-1], ep.steps[1:]):
            nxt[b.positions.astype(np.float32).tobytes()] = (a, b)
    for n, e in sp.by_n.items():
        assert set(e) == {"p", "v", "pil", "tp", "tv"}
        for i in range(len(e["p"])):
            # the target is exactly a truth step t+1, and the input is truth step t plus visible noise
            a, b = nxt[e["tp"][i].tobytes()]
            assert np.array_equal(e["tv"][i], b.velocities.astype(np.float32))
            assert np.abs(e["p"][i] - a.positions).max() < 6 * L.VISIBLE_SIGMA[0]
            assert np.abs(e["v"][i] - a.velocities).max() < 6 * L.VISIBLE_SIGMA[1]
    dv = np.concatenate([np.ravel(e["v"][i] - nxt[e["tp"][i].tobytes()][0].velocities) for e in sp.by_n.values() for i in range(len(e["p"]))])
    assert abs(np.std(dv) - L.VISIBLE_SIGMA[1]) < 0.02


# --- training ----------------------------------------------------------------------------------------
def test_training_is_seeded_and_lowers_the_loss(pool) -> None:
    a, la = L.train("L-int", pool, steps=40, batch=16, seed=3, log_every=10)
    b, lb = L.train("L-int", pool, steps=40, batch=16, seed=3, log_every=10)
    c, _ = L.train("L-int", pool, steps=40, batch=16, seed=4, log_every=10)
    pa, pb, pc = _params(a), _params(b), _params(c)
    assert all(np.array_equal(pa[k], pb[k]) for k in pa) and la == lb
    assert not all(np.array_equal(pa[k], pc[k]) for k in pa)
    full = {k: mx.array(v) for k, v in pool.by_n[6].items()}
    assert float(L.rollout_loss(a, full)) < float(L.rollout_loss(_model("L-int", 3), full))


def test_sigma_arm_keeps_the_frozen_mean(eps, pool) -> None:
    mean, _ = L.train("L-int", pool, steps=5, batch=8, seed=1)
    sp = L.make_sigma_pool(eps, 200, np.random.default_rng(2))
    s, log = L.train("L-int-s", sp, steps=30, batch=16, seed=1, mean_model=mean, log_every=10)
    pm, ps = _params(mean), _params(s)
    assert all(np.array_equal(pm[k], ps[k]) for k in pm)
    assert {k for k in ps if k not in pm} == {"var1.weight", "var1.bias", "var2.weight", "var2.bias"}
    p, v, pil = _state()
    a = mean(mx.array(p), mx.array(v), mx.array(pil))
    b = s(mx.array(p), mx.array(v), mx.array(pil))
    assert np.array_equal(np.array(a[0]), np.array(b[0])) and np.array_equal(np.array(a[1]), np.array(b[1]))
    assert log[-1][1] < log[0][1]
    # two separate protections of the mean: only the variance head is trainable, and the loss has
    # no gradient into the mean even on a model that is not frozen
    assert {k.split(".")[0] for k, _ in tree_flatten(s.trainable_parameters())} == {"var1", "var2"}
    import mlx.nn as nn

    free = _model("L-int-s", 5)
    batch = {k: mx.array(x[:8]) for k, x in sp.by_n[6].items()}
    _, g = nn.value_and_grad(free, L.nll_loss)(free, batch)
    g = {k: np.array(x) for k, x in tree_flatten(g)}
    assert all(not x.any() for k, x in g.items() if not k.startswith("var")) and any(x.any() for k, x in g.items() if k.startswith("var"))
    with pytest.raises(ValueError):
        L.train("L-int-s", sp, steps=1, batch=4, seed=1)
    with pytest.raises(ValueError):
        L.train("L-int", pool, steps=1, batch=4, seed=1, mean_model=mean)


def test_save_and_load(tmp_path, pool) -> None:
    m, _ = L.train("L-int-c", pool, steps=3, batch=8, seed=2)
    path = str(tmp_path / "m.safetensors")
    L.save(m, path)
    r = L.load("L-int-c", path)
    pa, pr = _params(m), _params(r)
    assert pa.keys() == pr.keys() and all(np.array_equal(pa[k], pr[k]) for k in pa)


# --- filter wrapper -------------------------------------------------------------------------------
def test_process_model_wrapper(eps) -> None:
    m = _model("L-int")
    step = L.as_process_model(m)
    s = eps[1].steps[0]
    P = np.repeat(s.positions[None], 32, 0); V = np.repeat(s.velocities[None], 32, 0)
    p, v = step(P, V, eps[1].pillars)
    assert p.shape == P.shape and v.shape == V.shape and p.dtype == np.float64
    pil = np.broadcast_to(np.array(eps[1].pillars, dtype=np.float32), (32, 3, 3))
    d = m(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), mx.array(pil))
    assert np.array_equal(p, np.array(d[0], dtype=np.float64)) and np.array_equal(v, np.array(d[1], dtype=np.float64))
    e0 = step(np.zeros((32, 0, 2)), np.zeros((32, 0, 2)), eps[1].pillars)
    assert e0[0].shape == (32, 0, 2) and len(e0) == 2
    with pytest.raises(ValueError):
        L.as_process_model(m, with_variance=True)
    sv = L.as_process_model(_model("L-int-s"), with_variance=True)
    out = sv(P, V, eps[1].pillars)
    assert len(out) == 4 and (out[2] > 0).all() and (out[3] > 0).all()
    assert len(sv(np.zeros((32, 0, 2)), np.zeros((32, 0, 2)), eps[1].pillars)) == 4


def test_wrapper_variances_are_the_head_outputs(eps) -> None:
    m = _model("L-int-s", 5)
    s = eps[0].steps[3]
    P = np.repeat(s.positions[None], 4, 0); V = np.repeat(s.velocities[None], 4, 0)
    out = L.as_process_model(m, with_variance=True)(P, V, eps[0].pillars)
    pil = np.broadcast_to(np.array(eps[0].pillars, dtype=np.float32), (4, 3, 3))
    lv = np.array(m(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), mx.array(pil))[3], dtype=np.float64)
    assert np.allclose(out[2], np.exp(lv[..., 0:2])) and np.allclose(out[3], np.exp(lv[..., 2:4]))


def test_contact_term_only_for_interaction_arms(pool) -> None:
    b = {k: mx.array(v[:8]) for k, v in pool.by_n[6].items()}
    ones = dict(b, contact=mx.ones_like(b["contact"]))
    zeros = dict(b, contact=mx.zeros_like(b["contact"]))
    for arm, differs in (("L-ind", False), ("L-int", True), ("L-int-c", True)):
        m = _model(arm)
        assert (float(L.rollout_loss(m, ones)) != float(L.rollout_loss(m, zeros))) == differs, arm
    m = _model("L-int")
    n = 6
    p, v, logits, _ = m(b["p"], b["v"], b["pil"])
    off = 1 - np.eye(n)[None]
    lg = np.array(logits, dtype=np.float64)
    bce1 = (np.logaddexp(0, -lg) * off).sum() / (off.sum() * 8)   # target 1
    bce0 = (np.logaddexp(0, lg) * off).sum() / (off.sum() * 8)    # target 0
    gap = float(L.rollout_loss(m, ones)) - float(L.rollout_loss(m, zeros))
    assert gap == pytest.approx(L.CONTACT_WEIGHT * (bce1 - bce0), rel=1e-3, abs=1e-5)


def test_registered_constants() -> None:
    assert (L.MSG_RADIUS, L.HID, L.MSG, L.P_SCALE, L.ROLLOUT, L.CONTACT_WEIGHT) == (1.5, 128, 64, 0.1, (1, 5, 10), 0.1)
    assert (L.P_HIDDEN, L.VISIBLE_SIGMA, L.HIDDEN_SIGMA, L.P_DROP, L.GHOSTS, L.GHOST_SIGMA, L.EXACT_FRAC) == (0.7, (0.05, 0.2), (0.7, 0.6), 0.1, 0.3, 0.3, 0.2)
    assert (L.ARENA, L.RADIUS, L.DT, L.N_PILLARS) == (W.ARENA, W.RADIUS, W.DT, W.N_PILLARS)
    assert L.ARMS == ("L-ind", "L-int", "L-int-c", "L-int-s")


def test_collision_oversampling(pool) -> None:
    assert (L.COLL_SHARE, L.CLIP) == (0.5, 10.0)
    k = int(round(16 * 0.5))
    seen_hit = seen_any = 0
    for n, idx in L.batches(pool, 200, 16, np.random.default_rng(0), coll_share=0.5):
        hit = pool.by_n[n]["contact"][idx].sum((1, 2)) > 0
        if (pool.by_n[n]["contact"].sum((1, 2)) > 0).any():
            assert hit[:k].all()                          # the first share always comes from contact samples
            seen_hit += 1
        else:
            seen_any += 1
    assert seen_hit > 50
    plain = [hit for n, idx in L.batches(pool, 200, 16, np.random.default_rng(0)) for hit in (pool.by_n[n]["contact"][idx].sum((1, 2)) > 0)]
    assert np.mean(plain) < 0.3
    sp_like = L.Pool({4: {"p": np.zeros((5, 4, 2), np.float32)}})
    assert all(len(i) == 3 for _, i in L.batches(sp_like, 5, 3, np.random.default_rng(0), coll_share=0.5))


def test_near_miss_sampling(pool) -> None:
    """Sample kinds recomputed pair by pair from the simulator's labels; the batch layout; and the
    collision-only sampler is unchanged when the near-miss share is zero."""
    assert L.NEAR_GAP == pytest.approx(2 * W.RADIUS + 0.3)
    both = 0
    for n, e in pool.by_n.items():
        hit, near = L.sample_kinds(e)
        want_hit, want_near = [], []
        for i in range(len(e["p"])):
            dmin = min(float(np.linalg.norm(e["p1"][i][a] - e["p1"][i][b])) for a in range(n) for b in range(a + 1, n))
            if e["contact"][i].any():
                want_hit.append(i)
            elif dmin < L.NEAR_GAP:
                want_near.append(i)
        assert hit.tolist() == want_hit and near.tolist() == want_near
        both += bool(want_hit and want_near)
    assert both >= 2
    seen = 0
    for n, idx in L.batches(pool, 200, 16, np.random.default_rng(0), coll_share=0.25, near_share=0.5):
        hit, near = L.sample_kinds(pool.by_n[n])
        assert len(idx) == 16
        if len(hit) and len(near):
            assert np.isin(idx[:4], hit).all() and np.isin(idx[4:12], near).all()
            seen += 1
        elif len(near):
            assert np.isin(idx[:8], near).all()
    assert seen > 50
    # near_share = 0: the same draws as the collision-only sampler, written out here
    rng = np.random.default_rng(5)
    ns = sorted(pool.by_n)
    sizes = np.array([len(pool.by_n[n]["p"]) for n in ns], dtype=np.float64)
    want = []
    for _ in range(40):
        j = int(rng.choice(len(ns), p=sizes / sizes.sum()))
        h = np.flatnonzero(pool.by_n[ns[j]]["contact"].sum((1, 2)) > 0)
        if len(h):
            want.append((ns[j], np.concatenate([h[rng.integers(0, len(h), 8)], rng.integers(0, int(sizes[j]), 8)]).tolist()))
        else:
            want.append((ns[j], rng.integers(0, int(sizes[j]), 16).tolist()))
    assert [(n, i.tolist()) for n, i in L.batches(pool, 40, 16, np.random.default_rng(5), coll_share=0.5)] == want
    with pytest.raises(ValueError, match="exceed the batch"):
        next(L.batches(pool, 1, 16, np.random.default_rng(0), coll_share=0.75, near_share=0.5))
    sp_like = L.Pool({4: {"p": np.zeros((5, 4, 2), np.float32)}})
    assert all(len(i) == 3 for _, i in L.batches(sp_like, 5, 3, np.random.default_rng(0), coll_share=0.3, near_share=0.3))


def test_non_finite_loss_stops_training(pool, monkeypatch) -> None:
    monkeypatch.setattr(L, "rollout_loss", lambda m, b: mx.array(float("nan")) + 0 * m.out.bias.sum())
    with pytest.raises(FloatingPointError):
        L.train("L-int", pool, steps=3, batch=4, seed=1)


def test_recorded_divergence_case_has_a_finite_gradient(monkeypatch) -> None:
    """The batch sample and L-int-c weights at which exploration round 5 diverged (two disks
    clipped onto the corner (9.7, 9.7)): with the old softening 1e-6 the gradient norm is inf."""
    import mlx.nn as nn

    data = np.load(Path(__file__).parent / "data" / "s4_coincident_case.npz")
    b = {k[2:]: mx.array(data[k]) for k in data.files if k.startswith("b:")}
    m = L.Dynamics("L-int-c")
    m.load_weights([(k[2:], mx.array(data[k])) for k in data.files if k.startswith("w:")])

    def norm():
        _, g = nn.value_and_grad(m, L.rollout_loss)(m, b)
        return float(mx.sqrt(sum((x ** 2).sum() for _, x in tree_flatten(g))))

    assert np.isfinite(norm())
    monkeypatch.setattr(L, "EPS_DIR", 1e-6)
    assert not np.isfinite(norm())


def test_training_uses_the_oversampling_and_the_clip(pool, monkeypatch) -> None:
    import mlx.optimizers as optim

    shares, clips = [], []
    real_batches, real_clip = L.batches, optim.clip_grad_norm
    monkeypatch.setattr(L, "batches", lambda *a, **k: (shares.append((k.get("coll_share"), k.get("near_share"))), real_batches(*a, **k))[1])
    monkeypatch.setattr(optim, "clip_grad_norm", lambda g, max_norm: (clips.append(max_norm), real_clip(g, max_norm))[1])
    monkeypatch.setattr(L, "NEAR_SHARE", 0.25)
    m, _ = L.train("L-int", pool, steps=3, batch=4, seed=1)
    assert shares == [(L.COLL_SHARE, 0.25)] and clips == [L.CLIP] * 3
    shares.clear()
    L.train("L-int-s", L.make_sigma_pool([W.generate_episode(NS, 0, 4, steps=20)], 20, np.random.default_rng(0)), steps=2, batch=4, seed=1, mean_model=m)
    assert shares == [(0.0, 0.0)]


def test_learning_rate_is_constant_or_a_cosine_decay_over_the_run(pool, monkeypatch) -> None:
    import mlx.optimizers as optim

    rates, calls = [], []
    real_adam, real_cos = optim.Adam, optim.cosine_decay
    monkeypatch.setattr(optim, "Adam", lambda learning_rate: (rates.append(learning_rate), real_adam(learning_rate=learning_rate))[1])
    monkeypatch.setattr(optim, "cosine_decay", lambda init, steps, end: (calls.append((init, steps, end)), real_cos(init, steps, end))[1])
    monkeypatch.setattr(L, "LR_END", None)
    L.train("L-int", pool, steps=3, batch=4, seed=1)
    assert rates == [1e-3] and calls == []
    monkeypatch.setattr(L, "LR_END", 1e-5)
    m, _ = L.train("L-int", pool, steps=7, batch=4, seed=1)
    assert calls == [(1e-3, 7, 1e-5)] and callable(rates[1])
    assert float(rates[1](0)) == pytest.approx(1e-3) and float(rates[1](7)) == pytest.approx(1e-5, rel=1e-3)
    assert float(rates[1](3)) < 1e-3
    L.train("L-int-s", L.make_sigma_pool([W.generate_episode(NS, 0, 4, steps=20)], 20, np.random.default_rng(0)), steps=5, batch=4, seed=1, mean_model=m)
    assert calls[-1] == (1e-3, 5, 1e-5)


def test_a_cell_over_its_time_limit_stops(pool) -> None:
    with pytest.raises(TimeoutError):
        L.train("L-int", pool, steps=50, batch=4, seed=1, time_limit=0.0)
    m, log = L.train("L-int", pool, steps=3, batch=4, seed=1, time_limit=600.0)
    assert log[-1][0] == 3


def test_rollout_weights_scale_their_own_terms(pool, monkeypatch) -> None:
    assert L.ROLLOUT_WEIGHTS == (1.0, 1.0, 1.0)
    b = {k: mx.array(v[:6]) for k, v in pool.by_n[6].items()}
    m = _model("L-ind", 2)                                          # no contact term
    base = float(L.rollout_loss(m, b))
    terms = []
    for i in range(3):
        w = [1.0, 1.0, 1.0]
        w[i] = 2.0
        monkeypatch.setattr(L, "ROLLOUT_WEIGHTS", tuple(w))
        terms.append(float(L.rollout_loss(m, b)) - base)
    assert all(t > 0 for t in terms) and sum(terms) == pytest.approx(base, rel=1e-4)
    assert terms[0] < terms[1] < terms[2]                           # error grows along the rollout
