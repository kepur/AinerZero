"""S4 phase 2 contact-gated process models: the gates, the per-member, per-disk switch between the
learned model and E-B, and the code constraint. MLX on the CPU device."""

from __future__ import annotations

import ast
import inspect
import math
import textwrap

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")

from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import gated as G  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

PILLARS = ((8.0, 8.0, 0.5), (2.0, 8.0, 0.6), (8.0, 2.0, 0.4))


@pytest.fixture(autouse=True)
def _cpu():
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(prev)


@pytest.fixture(scope="module")
def nets():
    mx.random.seed(0)
    a, b = L.Dynamics("L-int"), L.Dynamics("L-ind")
    mx.eval(a.parameters(), b.parameters())
    return a, b


def _states(rng, m=8, n=6, spread=3.0):
    P = rng.uniform(W.RADIUS, spread, (m, n, 2))
    V = rng.normal(0, 1.2, (m, n, 2))
    return P, V


def test_geo_gate_equals_the_phase1_contact_baseline() -> None:
    rng = np.random.default_rng(0)
    hits = 0
    for _ in range(300):
        n = int(rng.integers(2, 9))
        P, V = _states(rng, m=1, n=n)
        ref = np.zeros(n, bool)
        for i, j in A.cv_contact_pairs(P[0], V[0]):
            ref[i] = ref[j] = True
        got = G.geo_gate(P, V)[0]
        assert np.array_equal(got, ref)
        hits += int(ref.sum())
    assert hits > 100


def test_head_gate_threshold_and_neighbourhood() -> None:
    P = np.array([[[1.0, 1.0], [1.5, 1.0], [5.0, 5.0]]])
    lg = np.full((1, 3, 3), 10.0)                      # every pair "certain"
    g = G.head_gate(lg, P, 0.5)
    assert g.tolist() == [[True, True, False]]          # disk 2 has nobody within MSG_RADIUS; no self pairs
    lg = np.full((1, 3, 3), math.log(0.3 / 0.7))        # probability exactly 0.3
    assert not G.head_gate(lg, P, 0.3).any()            # strictly above the threshold
    assert G.head_gate(lg + 1e-9, P, 0.3)[0, :2].all()
    for bad in (0.0, 1.0, -0.1):
        with pytest.raises(ValueError):
            G.head_gate(lg, P, bad)


def test_closed_gate_is_eb_and_open_gate_is_the_learned_model_bit_for_bit(nets, monkeypatch) -> None:
    net = nets[0]
    rng = np.random.default_rng(1)
    P, V = _states(rng)
    learned = L.as_process_model(net)(P, V, PILLARS)
    eb = Mo.bounce(P, V, PILLARS)
    monkeypatch.setattr(G, "head_gate", lambda lg, P, p: np.zeros(P.shape[:2], bool))
    out = G.gated_model(net, 0.5)(P, V, PILLARS)
    assert np.array_equal(out[0], eb[0]) and np.array_equal(out[1], eb[1])
    monkeypatch.setattr(G, "head_gate", lambda lg, P, p: np.ones(P.shape[:2], bool))
    out = G.gated_model(net, 0.5)(P, V, PILLARS)
    assert np.array_equal(out[0], learned[0]) and np.array_equal(out[1], learned[1])


def test_gate_switches_per_member_and_per_disk(nets, monkeypatch) -> None:
    net = nets[0]
    rng = np.random.default_rng(2)
    P, V = _states(rng)
    mask = rng.random(P.shape[:2]) < 0.4
    monkeypatch.setattr(G, "head_gate", lambda lg, P, p: mask)
    cnt = [0, 0]
    out = G.gated_model(net, 0.5, counter=cnt)(P, V, PILLARS)
    learned = L.as_process_model(net)(P, V, PILLARS)
    eb = Mo.bounce(P, V, PILLARS)
    for k in (0, 1):
        assert np.array_equal(out[k][mask], learned[k][mask])
        assert np.array_equal(out[k][~mask], eb[k][~mask])
    assert cnt == [int(mask.sum()), mask.size]


def test_geo_gated_independent_model_and_refusals(nets) -> None:
    lint, lind = nets
    rng = np.random.default_rng(3)
    P, V = _states(rng)
    g = G.geo_gate(P, V)
    out = G.gated_model(lind, "geo")(P, V, PILLARS)
    learned = L.as_process_model(lind)(P, V, PILLARS)
    eb = Mo.bounce(P, V, PILLARS)
    assert np.array_equal(out[1][g], learned[1][g]) and np.array_equal(out[1][~g], eb[1][~g])
    with pytest.raises(ValueError):
        G.gated_model(lind, 0.5)                        # no contact head
    with pytest.raises(ValueError):
        G.gated_model(lint, 1.5)
    s = L.Dynamics("L-int-s")
    with pytest.raises(ValueError):
        G.gated_model(s, "geo")


def test_fewer_than_two_tracks_is_eb(nets) -> None:
    for n in (0, 1):
        P = np.full((4, n, 2), 3.0)
        V = np.ones((4, n, 2))
        cnt = [0, 0]
        out = G.gated_model(nets[0], 0.5, counter=cnt)(P, V, PILLARS)
        eb = Mo.bounce(P, V, PILLARS)
        assert np.array_equal(out[0], eb[0]) and np.array_equal(out[1], eb[1])
        assert cnt == [0, 4 * n]


def test_real_contact_opens_the_geo_gate_only_for_the_pair() -> None:
    P = np.array([[[3.0, 3.0], [3.65, 3.0], [7.0, 7.0]]])
    V = np.array([[[1.0, 0.0], [-1.0, 0.0], [1.0, 0.0]]])
    assert G.geo_gate(P, V).tolist() == [[True, True, False]]
    V2 = np.array([[[-1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]])   # separating
    assert not G.geo_gate(P, V2).any()


def _names(fn) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            out.add(f"{node.value.id}.{node.attr}")
    return out


def test_gates_never_read_the_world_or_its_physics() -> None:
    for fn in (G.geo_gate, G.head_gate):
        names = _names(fn)
        assert not any(x.startswith("W.") and x not in ("W.RADIUS", "W.DT") for x in names), names
        assert "W.physics" not in names
    names = _names(G.GatedModel.__call__)
    assert "W.physics" not in names and "Mo.true_physics" not in names
    assert {x for x in names if x.startswith("Mo.")} == {"Mo.bounce"}
    assert "W.physics" not in _names(G.GatedModel.__init__) and "W.physics" not in _names(G.scatter_velocity)


# --- phase-2 r1 controls: the scatter response and the random gate -------------------------------
def test_scatter_response_turns_eb_velocity_keeps_speed_and_eb_position(nets, monkeypatch) -> None:
    net = nets[0]
    rng = np.random.default_rng(10)
    P, V = _states(rng)
    mask = rng.random(P.shape[:2]) < 0.5
    monkeypatch.setattr(G, "head_gate", lambda lg, P, p: mask)
    m = G.gated_model(net, 0.5, response="scatter")
    m.reseed(123)
    out = m(P, V, PILLARS)
    pb, vb = Mo.bounce(P, V, PILLARS)
    assert np.array_equal(out[0], pb)                                    # positions are E-B's everywhere
    assert np.array_equal(out[1][~mask], vb[~mask])
    assert np.allclose(np.linalg.norm(out[1][mask], axis=-1), np.linalg.norm(vb[mask], axis=-1))
    assert not np.allclose(out[1][mask], vb[mask])
    theta = np.random.default_rng(123).uniform(0.0, 2 * math.pi, P.shape[:2])
    assert np.allclose(out[1], np.where(mask[..., None], G.scatter_velocity(vb, theta), vb))


def test_stochastic_arms_need_a_seed_and_repeat_with_it(nets) -> None:
    rng = np.random.default_rng(11)
    P, V = _states(rng)
    for gate, resp in ((0.5, "scatter"), (("random", 0.3), "learned"), ("geo", "scatter")):
        m = G.gated_model(nets[0], gate, response=resp)
        assert m.stochastic
        with pytest.raises(RuntimeError):
            m(P, V, PILLARS)
        m.reseed(5)
        a = m(P, V, PILLARS)
        m.reseed(5)
        b = m(P, V, PILLARS)
        m.reseed(6)
        c = m(P, V, PILLARS)
        assert all(np.array_equal(x, y) for x, y in zip(a, b))
        assert not all(np.array_equal(x, y) for x, y in zip(a, c))
    d = G.gated_model(nets[0], 0.5)
    assert not d.stochastic
    G.reseed_if_stochastic(d, 1)                                         # deterministic arms ignore it
    d(P, V, PILLARS)


def test_random_gate_opens_at_its_rate_and_uses_the_learned_model(nets) -> None:
    net = nets[0]
    P, V = _states(np.random.default_rng(12), m=200, n=6)
    cnt = [0, 0]
    m = G.gated_model(net, ("random", 0.1), counter=cnt)
    m.reseed(9)
    out = m(P, V, PILLARS)
    g = np.random.default_rng(9).random(P.shape[:2]) < 0.1
    learned = L.as_process_model(net)(P, V, PILLARS)
    eb = Mo.bounce(P, V, PILLARS)
    assert np.array_equal(out[1][g], learned[1][g]) and np.array_equal(out[1][~g], eb[1][~g])
    assert cnt == [int(g.sum()), g.size] and 0.07 < cnt[0] / cnt[1] < 0.13
    for bad in (("random", 0.0), ("random", 1.0), ("rand", 0.1), ("random",)):
        with pytest.raises(ValueError):
            G.gated_model(net, bad)
    with pytest.raises(ValueError):
        G.gated_model(net, 0.5, response="other")
