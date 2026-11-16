"""S6 phase 2 world B (pure NumPy): one unified law, the vortex ring, placement, labels, step kinds."""
from __future__ import annotations

import ast
import inspect
import math

import numpy as np
import pytest

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s6 import sandbox as S
from ainerzero.v9.experiments.s6 import world_b as B

NS = "s6t-world-b"


@pytest.fixture(scope="module")
def episodes():
    return [B.generate_episode_b(NS, w, n, steps=120) for w, n in enumerate([4, 6, 8, 6])]


def test_on_a_world_without_a_big_pillar_the_law_is_world_a():
    ep = W.generate_episode(NS + "-a", 0, 6, steps=60)
    assert max(r for _, _, r in ep.pillars) < B.BIG_MIN
    for t in (0, 17, 44):
        s = ep.steps[t]
        a = W.physics(s.positions[None], s.velocities[None], ep.pillars, log=True)
        b = B.physics_b(s.positions[None], s.velocities[None], ep.pillars, log=True)
        assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]) and a[2] == b[2]
        assert not B.in_halo(s.positions, ep.pillars).any()


def test_ring_membership_by_hand():
    pillars = ((5.0, 5.0, 1.2), (1.0, 1.0, 0.5), (9.0, 9.0, 0.5))
    edge = 1.2 + W.RADIUS + B.HALO                       # centre distance at which the ring ends
    p = np.array([[5.0 + edge - 0.01, 5.0], [5.0 + edge + 0.01, 5.0], [1.0 + 0.5 + W.RADIUS + 0.1, 1.0], [5.0, 5.0 - 1.6]])
    assert B.in_halo(p, pillars).tolist() == [True, False, False, True]     # a small pillar has no ring
    assert not B.in_halo(p, ((5.0, 5.0, 0.99), (1.0, 1.0, 0.5), (9.0, 9.0, 0.5))).any()


def test_the_vortex_turns_the_velocity_and_keeps_the_speed():
    pillars = ((5.0, 5.0, 1.2), (1.5, 1.5, 0.5), (8.5, 8.5, 0.5))
    p = np.array([[[7.0, 5.0], [9.0, 2.0]]])             # disk 0 in the ring, disk 1 far away
    v = np.array([[[0.0, 1.0], [0.6, 0.0]]])
    pn, vn, _ = B.physics_b(p, v, pillars)
    c, s = math.cos(B.TURN), math.sin(B.TURN)
    np.testing.assert_allclose(vn[0, 0], [c * 0.0 - s * 1.0, s * 0.0 + c * 1.0])     # counter-clockwise turn
    np.testing.assert_allclose(vn[0, 1], [0.6, 0.0])
    assert np.linalg.norm(vn[0, 0]) == pytest.approx(1.0)
    np.testing.assert_allclose(pn[0, 0], p[0, 0] + vn[0, 0] * W.DT)                 # the turned velocity moves the disk
    # exactly the world-A step applied to the turned velocity
    want = W.physics(p, B.turn(v, np.array([[True, False]])), pillars)
    assert np.array_equal(pn, want[0]) and np.array_equal(vn, want[1])


def test_worlds_have_one_big_pillar_in_a_random_slot(episodes):
    slots = []
    for w in range(40):
        pil = B.place_pillars_b(np.random.default_rng(w))
        big = [i for i, (_, _, r) in enumerate(pil) if r >= B.BIG_MIN]
        assert len(pil) == 3 and len(big) == 1
        cx, cy, r = pil[big[0]]
        assert B.BIG_RADIUS[0] <= r <= B.BIG_RADIUS[1]
        assert min(cx, cy) - r - B.HALO - W.RADIUS > 0 and max(cx, cy) + r + B.HALO + W.RADIUS < W.ARENA   # ring inside the arena
        for i in range(3):
            for j in range(i + 1, 3):
                assert math.hypot(pil[i][0] - pil[j][0], pil[i][1] - pil[j][1]) > pil[i][2] + pil[j][2] + W.PILLAR_GAP
        slots.append(big[0])
    assert set(slots) == {0, 1, 2}
    for ep in episodes:
        assert sum(r >= B.BIG_MIN for _, _, r in ep.pillars) == 1


def test_episodes_are_deterministic_follow_the_law_and_keep_disks_legal(episodes):
    again = B.generate_episode_b(NS, 1, 6, steps=120)
    assert all(np.array_equal(a.positions, b.positions) and np.array_equal(a.velocities, b.velocities) and a.contacts == b.contacts
               for a, b in zip(again.steps, episodes[1].steps))
    other = B.generate_episode_b(NS, 5, 6, steps=5)
    assert not np.array_equal(other.steps[0].positions, episodes[1].steps[0].positions)
    ring_steps = 0
    for ep in episodes:
        for t in range(len(ep.steps) - 1):
            s = ep.steps[t]
            pn, vn, cont = B.physics_b(s.positions[None], s.velocities[None], ep.pillars, log=True)
            assert np.array_equal(pn[0], ep.steps[t + 1].positions) and np.array_equal(vn[0], ep.steps[t + 1].velocities)
            assert tuple(cont) == s.contacts
            ring_steps += int(B.in_halo(s.positions, ep.pillars).sum())
        P = np.stack([s.positions for s in ep.steps])
        assert P.min() >= W.RADIUS - 1e-9 and P.max() <= W.ARENA - W.RADIUS + 1e-9
    assert ring_steps > 100                                   # the ring is visited


def test_registered_partitions_are_refused():
    for ns in ("s6p2-final", "s6p1-final", "s4p2-final"):
        with pytest.raises(PermissionError):
            B.generate_episode_b(ns, 0, 6, steps=2)
    assert B.REGISTERED == {"s6p2-final"}


def test_labels_follow_the_unified_law(episodes):
    ep = episodes[1]
    ts = [t for t in range(100) if B.in_halo(ep.steps[t].positions, ep.pillars).any()][:2] + [0]
    P = np.stack([ep.steps[t].positions for t in ts]); V = np.stack([ep.steps[t].velocities for t in ts])
    PIL = np.broadcast_to(np.asarray(ep.pillars, float), (len(ts), 3, 3)).copy()
    lab = B.sim_labels_b(P, V, PIL)
    assert set(lab) == set(S.LABEL_KEYS) and all(a.dtype == np.float32 for a in lab.values()) and B.ROLLOUT == S.ROLLOUT
    for b, t in enumerate(ts):
        np.testing.assert_array_equal(lab["v1"][b], ep.steps[t + 1].velocities.astype(np.float32))
        np.testing.assert_array_equal(lab["p5"][b], ep.steps[t + 5].positions.astype(np.float32))
        np.testing.assert_array_equal(lab["v10"][b], ep.steps[t + 10].velocities.astype(np.float32))
    # on a world-A state the labels are sandbox.sim_labels
    a = W.generate_episode(NS + "-a", 1, 6, steps=20)
    Pa, Va = a.steps[3].positions[None], a.steps[3].velocities[None]
    PILa = np.asarray(a.pillars, float)[None]
    la, lb = S.sim_labels(Pa, Va, PILa), B.sim_labels_b(Pa, Va, PILa)
    assert all(np.array_equal(la[k], lb[k]) for k in la)
    # in the ring the old law gives a different outcome
    old = S.sim_labels(P[:1], V[:1], PIL[:1])
    assert not np.array_equal(old["v1"], lab["v1"][:1])


def test_step_kinds(episodes):
    seen = set()
    for ep in episodes:
        for t in range(len(ep.steps) - 1):
            kinds = B.classify_b(ep, t)
            s = ep.steps[t]
            ring = B.in_halo(s.positions, ep.pillars)
            hit = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
            for i, k in enumerate(kinds):
                assert (k == 0) == (i in hit)
                if k == 4:
                    assert ring[i]
                if k == 3:
                    assert not ring[i]
            seen |= set(kinds.tolist())
    assert seen == {0, 1, 2, 3, 4}
    # on a world-A episode the kinds are those of phase 1 (cells.classify, restated here; cells imports MLX)
    a = W.generate_episode(NS + "-a", 2, 6, steps=60)
    for t in range(59):
        s = a.steps[t]
        disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
        wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
        nxt = a.steps[t + 1].positions
        d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(6) * 99
        want = [0 if i in disk else (1 if d[i].min() < 2 * W.RADIUS + 0.3 else (2 if i in wallp else 3)) for i in range(6)]
        assert B.classify_b(a, t).tolist() == want


def test_module_is_pure_numpy_and_leaves_world_a_alone():
    tree = ast.parse(inspect.getsource(B))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert not any("mlx" in m for m in mods)
    assert W.REGISTERED == {"s4p1-final", "s4p2-final", "s6p1-final"}


@pytest.mark.parametrize("kind", ["tiny", "large"])
def test_decoy_worlds_look_new_and_follow_the_old_law(kind):
    ep = B.generate_episode_b(NS, 0, 6, steps=40, kind=kind)
    radii = sorted(r for _, _, r in ep.pillars)
    lo, hi = (B.TINY_RADIUS, B.LARGE_RADIUS)[kind == "large"]
    special = radii[0] if kind == "tiny" else radii[-1]
    assert lo <= special <= hi and special < B.BIG_MIN
    assert not (W.PILLAR_RADIUS[0] <= special <= W.PILLAR_RADIUS[1])         # outside the old range
    assert sum(not (W.PILLAR_RADIUS[0] <= r <= W.PILLAR_RADIUS[1]) for r in radii) == 1
    for t in (0, 9, 30):
        s = ep.steps[t]
        assert not B.in_halo(s.positions, ep.pillars).any()
        a = W.physics(s.positions[None], s.velocities[None], ep.pillars)
        assert np.array_equal(a[0][0], ep.steps[t + 1].positions) and np.array_equal(a[1][0], ep.steps[t + 1].velocities)
    big = B.generate_episode_b(NS, 0, 6, steps=5)                       # the default kind is unchanged by the decoy option
    assert max(r for _, _, r in big.pillars) >= B.BIG_MIN
    assert not np.array_equal(big.steps[0].positions, ep.steps[0].positions)
    with pytest.raises(ValueError):
        B.generate_episode_b(NS, 0, 6, steps=2, kind="other")


def test_a_disk_inside_the_ring_can_be_caught_and_one_passing_through_leaves():
    """A free disk in the ring moves on a circle of radius ~0.83 |v|. Started inside with a small circle it never
    leaves; a fast disk entering from outside follows its circle back out."""
    pillars = ((5.0, 5.0, 1.2), (1.2, 1.2, 0.5), (8.8, 8.8, 0.5))
    assert 0.1 / (2 * math.sin(B.TURN / 2)) == pytest.approx(0.834, abs=1e-3)

    def stay(p0, v0, steps):
        p, v = np.array([[p0]], float), np.array([[v0]], float)
        inside = []
        for _ in range(steps):
            inside.append(bool(B.in_halo(p[0], pillars)[0]))
            p, v, _ = B.physics_b(p, v, pillars)
        return inside

    mid = 1.2 + W.RADIUS + B.HALO / 2
    assert all(stay([5.0 + mid, 5.0], [0.0, 0.5], 300))                      # circle of radius 0.42 inside a 1.2 ring
    edge = 1.2 + W.RADIUS + B.HALO + 0.05                                    # just outside the ring
    through = stay([5.0 + edge, 5.0], [-1.3, 0.0], 150)
    assert not through[0] and any(through) and not through[-1] and sum(through) < 60
