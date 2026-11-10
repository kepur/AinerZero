"""S4 phase 1 world: physics, contacts, view, detections, events, partition guard. CPU only."""

from __future__ import annotations

import hashlib
import json
import math

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import world as W

NS = "test-s4-world"


def _fp(ep):
    h = hashlib.sha256()
    h.update(json.dumps(ep.pillars).encode())
    for s in ep.steps:
        for a in (s.positions, s.velocities, s.visible.astype(np.int8), s.detections, s.truth_ids):
            h.update(np.ascontiguousarray(a).tobytes())
        h.update(json.dumps([list(c) for c in s.contacts]).encode())
    return h.hexdigest()


@pytest.mark.parametrize(
    "w,digest",
    [
        (0, "a98aa9707dec7badeef7d6efcf4b4b850a786d582cbc9589e33d3174e3c47756"),
        (1, "ceada71d2aed5d09bf8e185e5e2cf475a745d3c76574851a8134153a4a939d1f"),
        (2, "92beba9757113054ffb0309fa3726b6d4ed6002b073ace58488863668d2693e8"),
    ],
)
def test_module_rebuilds_the_exploration_worlds(w, digest) -> None:
    """Digests of s4x-explore worlds; on 2026-11-10 they matched tier1-explore/explore2.py exactly."""
    assert _fp(W.generate_episode("s4x-explore", w, 6)) == digest


@pytest.fixture(scope="module")
def ep():
    return W.generate_episode(NS, 0, 6)


def test_generation_is_deterministic(ep) -> None:
    assert _fp(W.generate_episode(NS, 0, 6)) == _fp(ep)
    assert _fp(W.generate_episode(NS, 1, 6)) != _fp(ep)


@pytest.mark.parametrize("name", sorted(W.REGISTERED))
def test_registered_partitions_are_refused_before_anything_is_generated(name, monkeypatch) -> None:
    def boom(*a, **k):
        raise AssertionError("generated a registered partition")

    monkeypatch.setattr(W, "derive_seed", boom)
    with pytest.raises(PermissionError):
        W.generate_episode(name, 0, 6)


def test_registered_names() -> None:
    assert W.REGISTERED == {"s4p1-final"}


# --- physics ---------------------------------------------------------------------------------
def _two(p0, v0, p1, v1):
    return np.array([[p0, p1]], float), np.array([[v0, v1]], float)


def test_head_on_collision_swaps_velocities_and_is_logged() -> None:
    p, v = _two((4.6, 5.0), (1.0, 0.0), (5.4, 5.0), (-1.0, 0.0))
    for _ in range(3):
        p, v, c = W.physics(p, v, (), log=True)
        if c:
            break
    assert ("disk", 0, 1) in c
    assert v[0, 0, 0] < 0 < v[0, 1, 0]
    assert np.allclose(np.abs(v[0, :, 0]), 1.0, atol=1e-9)


def test_disk_collisions_conserve_momentum_and_energy() -> None:
    p, v = _two((4.0, 5.0), (1.2, 0.3), (6.0, 5.1), (-0.8, -0.2))
    mom, en = v.sum(1).copy(), (v ** 2).sum()
    logged = []
    for _ in range(10):  # one second: the disks meet, no wall is reached
        p, v, c = W.physics(p, v, (), log=True)
        logged += c
    assert ("disk", 0, 1) in logged and not any(kind == "wall" for kind, _, _ in logged)
    assert np.allclose(v.sum(1), mom, atol=1e-12)
    assert (v ** 2).sum() == pytest.approx(en, rel=1e-12)


def test_walls_and_pillars_reflect_and_are_logged() -> None:
    p, v = np.array([[[0.35, 5.0]]]), np.array([[[-1.0, 0.0]]])
    p2, v2, c = W.physics(p, v, (), log=True)
    assert ("wall", 0, -1) in c and v2[0, 0, 0] > 0 and p2[0, 0, 0] >= W.RADIUS
    pil = ((5.0, 5.0, 0.5),)
    p, v = np.array([[[4.15, 5.0]]]), np.array([[[1.0, 0.0]]])
    hit = []
    for _ in range(3):
        p, v, c = W.physics(p, v, pil, log=True)
        hit += c
    assert ("pillar", 0, 0) in hit and v[0, 0, 0] < 0
    assert np.linalg.norm(p[0, 0] - np.array([5.0, 5.0])) >= 0.5 + W.RADIUS - 1e-9


def test_batched_copies_equal_single_runs() -> None:
    ep0 = W.generate_episode(NS, 2, 8, steps=1)
    s = ep0.steps[0]
    rng = np.random.default_rng(1)
    P = np.stack([s.positions + rng.normal(0, 0.2, s.positions.shape) for _ in range(5)])
    V = np.stack([s.velocities + rng.normal(0, 0.2, s.velocities.shape) for _ in range(5)])
    Pb, Vb, _ = W.physics(P, V, ep0.pillars)
    for b in range(5):
        p1, v1, _ = W.physics(P[b : b + 1], V[b : b + 1], ep0.pillars)
        assert np.array_equal(p1[0], Pb[b]) and np.array_equal(v1[0], Vb[b])


def test_physics_does_not_modify_its_inputs_and_can_skip_disks() -> None:
    p, v = _two((4.6, 5.0), (1.0, 0.0), (5.4, 5.0), (-1.0, 0.0))
    p0, v0 = p.copy(), v.copy()
    W.physics(p, v, ())
    assert np.array_equal(p, p0) and np.array_equal(v, v0)
    for _ in range(4):
        p, v, _ = W.physics(p, v, (), disks=False)
    assert v[0, 0, 0] > 0 > v[0, 1, 0]  # passed through each other


def test_disks_stay_inside_and_apart(ep) -> None:
    for s in ep.steps[::10]:
        assert (s.positions >= W.RADIUS - 1e-9).all() and (s.positions <= W.ARENA - W.RADIUS + 1e-9).all()
        d = np.linalg.norm(s.positions[:, None] - s.positions[None], axis=-1) + np.eye(len(s.positions)) * 9
        assert d.min() > 2 * W.RADIUS - 0.1


# --- view and detections -------------------------------------------------------------------
def test_in_view_geometry() -> None:
    agent = (2.0, 5.0, 0.0)  # facing +x
    assert W.in_view(agent, np.array([6.0, 5.0]), ())
    assert not W.in_view(agent, np.array([1.0, 5.0]), ())          # behind (180 degree view)
    assert W.in_view(agent, np.array([2.0, 8.0]), ())              # exactly sideways is inside 180
    assert not W.in_view(agent, np.array([9.5, 5.0]), ())          # beyond 7
    assert not W.in_view(agent, np.array([8.0, 5.0]), ((5.0, 5.0, 0.6),))  # blocked by a pillar


def test_detections_are_anonymous_noisy_and_shuffled(ep) -> None:
    orders, errs = [], []
    for s in ep.steps:
        assert set(s.truth_ids.tolist()) <= set(np.flatnonzero(s.visible).tolist())
        assert len(s.detections) == len(s.truth_ids)
        errs += np.linalg.norm(s.detections - s.positions[s.truth_ids], axis=1).tolist() if len(s.truth_ids) else []
        if len(s.truth_ids) > 1:
            orders.append(tuple(s.truth_ids.tolist()) == tuple(sorted(s.truth_ids.tolist())))
        view = W.student_view(s)
        assert set(view) == W.STUDENT_KEYS and view["detections"].shape[-1] == 2
    assert 0.02 < np.median(errs) < 0.1
    assert not all(orders)
    missed = sum(int(s.visible.sum()) - len(s.truth_ids) for s in ep.steps) / sum(int(s.visible.sum()) for s in ep.steps)
    assert 0.0 < missed < 0.12


def test_student_view_carries_no_identity(ep) -> None:
    view = W.student_view(ep.steps[50])
    blob = json.dumps({k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in view.items()})
    for word in ("truth", "ids", "velocit", "visible", "contact"):
        assert word not in blob


# --- events ------------------------------------------------------------------------------------
def test_reappearances_follow_the_truth(ep) -> None:
    ev = W.reappearances(ep)
    assert ev
    for e in ev:
        k, a, b = e["k"], e["a"], e["b"]
        assert ep.steps[a].visible[k] and ep.steps[b].visible[k] and b - a >= 2
        assert not any(ep.steps[t].visible[k] for t in range(a + 1, b))
        assert k in ep.steps[a].truth_ids and k in ep.steps[b].truth_ids
        coll = any(kind == "disk" and k in (i, j) for t in range(a, b) for kind, i, j in ep.steps[t].contacts)
        assert e["collision"] == coll and e["gap"] == b - a - 1


def test_collision_window_is_between_the_two_observations() -> None:
    """Contacts of steps a .. b-1 count (they happen after seeing k at a, before seeing it at b); step b does not."""
    def step(t, vis, cont):
        z = np.zeros((2, 2))
        return W.Step(t, (0.0, 0.0, 0.0), z[:0], np.array([0] if vis else [], dtype=np.int64), z, z, np.array([vis, True]), tuple(cont))

    def ev(contact_at):
        seq = [step(t, t in (0, 3), [("disk", 0, 1)] if t == contact_at else []) for t in range(5)]
        return W.reappearances(W.Episode("x", 0, 2, (), tuple(seq)))

    assert ev(None) == [{"k": 0, "a": 0, "b": 3, "gap": 2, "collision": False}]
    assert ev(0)[0]["collision"] is True   # between a and a+1
    assert ev(2)[0]["collision"] is True   # between b-1 and b
    assert ev(3)[0]["collision"] is False  # after b


def test_seed_recipe_matches_earlier_phases() -> None:
    from ainerzero.v9.experiments.s3.data import derive_seed as s3_seed

    for keys in (("world", 0), ("agent", 7), ("ep", 3, 2)):
        assert W.derive_seed("s4p1-train", *keys) == s3_seed("s4p1-train", *keys)


def test_package_imports_no_mlx() -> None:
    import ainerzero.v9.experiments.s4.world as mod

    src = open(mod.__file__, encoding="utf-8").read()
    assert "import mlx" not in src and "from mlx" not in src
