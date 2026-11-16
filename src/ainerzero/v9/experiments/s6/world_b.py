#!/usr/bin/env python3
"""S6 phase 2 world B: the S4 disk world plus one new kind of object, a big pillar with a vortex ring.

World A (``s4.world``) has three pillars of radius 0.4-0.8. World B replaces one of them by a big pillar
(radius 1.0-1.3). A disk whose surface is within ``HALO`` of a big pillar's surface has its velocity turned
by ``TURN`` radians (counter-clockwise) at the start of each step; then the ordinary world-A step follows.
The speed is unchanged, so the speed distribution of the world stays what it was.

One law covers both worlds: ``physics_b`` on a world without a big pillar is exactly ``s4.world.physics``.
Old-world experience therefore stays valid after the change: nothing it recorded is contradicted, the new
mechanism lives where the old world had no states (a pillar radius it never saw).

A third kind of world is a decoy: one pillar is tiny (radius 0.15-0.25), which the old world never had
either, but nothing new happens there. It looks new and is not.

Pure NumPy. ``s4.world`` is not modified.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import world as W

BIG_MIN = 1.0                      # a pillar at least this large carries a vortex ring
BIG_RADIUS = (1.0, 1.3)
BIG_CENTRE = (3.2, 6.8)            # the ring stays inside the arena
TINY_RADIUS = (0.15, 0.25)         # decoy: out of the old range, old law
KINDS_OF_WORLD = ("big", "tiny")
HALO = 1.2                         # ring width, measured from the pillar surface to the disk surface
TURN = 0.12                        # radians per step
ROLLOUT = (1, 5, 10)

# Partitions only a registered run may generate.
REGISTERED = frozenset({"s6p2-final"})


@dataclass(frozen=True)
class StepB:
    positions: np.ndarray
    velocities: np.ndarray
    contacts: tuple


@dataclass(frozen=True)
class EpisodeB:
    namespace: str
    world_index: int
    n_disks: int
    pillars: tuple
    steps: tuple


def in_halo(p: np.ndarray, pillars: Sequence[W.Pillar]) -> np.ndarray:
    """[..., n] bool: the disk's surface is within HALO of a big pillar's surface. p [..., n, 2]."""
    out = np.zeros(p.shape[:-1], dtype=bool)
    for cx, cy, r in pillars:
        if r >= BIG_MIN:
            gap = np.hypot(p[..., 0] - cx, p[..., 1] - cy) - r - W.RADIUS
            out |= gap < HALO
    return out


def turn(v: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Rotate the masked velocities by TURN (counter-clockwise); the others are returned unchanged."""
    c, s = math.cos(TURN), math.sin(TURN)
    rot = np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)
    return np.where(mask[..., None], rot, v)


def physics_b(p: np.ndarray, v: np.ndarray, pillars: Sequence[W.Pillar], *, disks: bool = True, log: bool = False):
    """One step of the unified law: vortex turn inside a big pillar's ring, then the world-A step."""
    p = np.asarray(p, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    mask = in_halo(p, pillars)
    if mask.any():
        v = turn(v, mask)
    return W.physics(p, v, pillars, disks=disks, log=log)


def place_pillars_b(rng: np.random.Generator, kind: str = "big") -> tuple[W.Pillar, ...]:
    """One special pillar (big with a ring, or a tiny decoy) and two ordinary ones (the W.PILLAR_GAP rule between
    all three), in a random order."""
    if kind not in KINDS_OF_WORLD:
        raise ValueError(f"unknown kind of world {kind!r}")
    c = rng.uniform(*BIG_CENTRE, 2)
    out: list[W.Pillar] = [(float(c[0]), float(c[1]), float(rng.uniform(*(BIG_RADIUS if kind == "big" else TINY_RADIUS))))]
    while len(out) < W.N_PILLARS:
        c = rng.uniform(2, W.ARENA - 2, 2)
        r = rng.uniform(*W.PILLAR_RADIUS)
        if all(math.hypot(c[0] - a, c[1] - b) > r + rr + W.PILLAR_GAP for a, b, rr in out):
            out.append((float(c[0]), float(c[1]), float(r)))
    order = rng.permutation(W.N_PILLARS)
    return tuple(out[i] for i in order)


def generate_episode_b(namespace: str, world_index: int, n_disks: int, *, steps: int = W.STEPS,
                       allow_registered: bool = False, kind: str = "big") -> EpisodeB:
    """One world B (``kind`` "big": a big pillar with its ring; "tiny": a decoy) and its trajectory under ``physics_b``."""
    if (namespace in REGISTERED or namespace in W.REGISTERED) and not allow_registered:
        raise PermissionError(f"{namespace} is a registered partition; only a registered run may generate it")
    rng = np.random.default_rng(W.derive_seed(namespace, "world-b" if kind == "big" else "world-tiny", world_index))
    pillars = place_pillars_b(rng, kind)
    p, v = W._place_disks(rng, n_disks, pillars)
    out = []
    for _ in range(steps):
        pn, vn, cont = physics_b(p[None], v[None], pillars, log=True)
        out.append(StepB(p.copy(), v.copy(), tuple(cont)))
        p, v = pn[0], vn[0]
    return EpisodeB(namespace, world_index, n_disks, pillars, tuple(out))


def sim_labels_b(P: np.ndarray, V: np.ndarray, PIL: np.ndarray) -> dict[str, np.ndarray]:
    """Outcome of each state under ``physics_b``, in the layout of ``sandbox.sim_labels``."""
    S_, n = P.shape[0], P.shape[1]
    out = {f"{x}{k}": np.empty((S_, n, 2)) for k in ROLLOUT for x in "pv"}
    contact = np.zeros((S_, n, n), dtype=np.float32)
    for b in range(S_):
        pillars = tuple(map(tuple, PIL[b]))
        p, v, c = physics_b(P[b:b + 1], V[b:b + 1], pillars, log=True)
        for kind, i, j in c:
            if kind == "disk":
                contact[b, i, j] = contact[b, j, i] = 1.0
        for k in range(1, max(ROLLOUT) + 1):
            if k > 1:
                p, v, _ = physics_b(p, v, pillars)
            if k in ROLLOUT:
                out[f"p{k}"][b], out[f"v{k}"][b] = p[0], v[0]
    return {"contact": contact, **{k: a.astype(np.float32) for k, a in out.items()}}


KINDS_B = ("collision", "graze", "wall_pillar", "free", "halo")


def classify_b(ep: Any, t: int) -> np.ndarray:
    """Step kind per disk at step t: 0 disk collision, 1 graze, 2 wall or pillar, 3 free, 4 in the vortex ring
    (and otherwise free). Kinds 0-3 are those of S6 phase 1; on a world without a big pillar kind 4 never occurs."""
    s = ep.steps[t]
    disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
    nxt = ep.steps[t + 1].positions
    d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(ep.n_disks) * 99
    halo = in_halo(s.positions, ep.pillars)
    out = []
    for i in range(ep.n_disks):
        if i in disk:
            out.append(0)
        elif d[i].min() < 2 * W.RADIUS + 0.3:
            out.append(1)
        elif i in wallp:
            out.append(2)
        else:
            out.append(4 if halo[i] else 3)
    return np.array(out)
