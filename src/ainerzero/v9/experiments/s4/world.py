"""S4 phase 1 world: same-looking disks with elastic collisions, an agent with partial view.

Per reports/V9-S4-DESIGN/DESIGN-r1.md §2. Pure CPU, NumPy / standard library only.

- Arena 10 x 10 with elastic walls; circular pillars block motion and sight.
- Disks of equal radius and mass, one appearance; elastic disk-disk, disk-wall and disk-pillar
  collisions. The physics is batched over independent copies [B, N, 2], so the world and any
  filter that uses "true physics" run the same function.
- The agent knows its own pose (a declared truth input), tours random waypoints, sees disks
  within 180 degrees and radius 7 unless a pillar blocks the line of sight. Disks do not
  occlude each other.
- Observations are anonymous detections: world-frame positions with noise, 5% missed, shuffled
  within a step. No identity, no velocity. Truth (positions, velocities, identities, contacts)
  is kept apart for training labels and evaluation.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

ARENA = 10.0
RADIUS = 0.3
DT = 0.1
SUBSTEPS = 4
SPEED = (0.6, 1.4)
N_PILLARS = 3
PILLAR_RADIUS = (0.4, 0.8)
PILLAR_GAP = 1.2
STEPS = 300
FOV = math.radians(180)
VIEW_RANGE = 7.0
AGENT_STEP = 0.15
AGENT_TURN = 0.3
SIGMA = 0.05
P_MISS = 0.05

# Registered partitions that only a registered run may generate (dev is not used in phase 1).
REGISTERED = frozenset({"s4p1-final"})

Pillar = tuple[float, float, float]


def derive_seed(namespace: str, *keys: Any) -> int:
    """Deterministic 31-bit seed from a namespace and keys (same recipe as phase 1-3)."""
    raw = f"{namespace}:" + ":".join(str(k) for k in keys)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16], 16) & 0x7FFFFFFF


# --- physics ---------------------------------------------------------------------------------
def physics(p: np.ndarray, v: np.ndarray, pillars: Sequence[Pillar], *, disks: bool = True,
            log: bool = False) -> tuple[np.ndarray, np.ndarray, list[tuple[str, int, int]]]:
    """One step of DT for B independent copies; p and v are [B, N, 2] and are not modified.

    Returns (p, v, contacts). With ``log`` the contacts of copy 0 are listed as ("disk", i, j)
    with i < j, ("wall", i, -1) and ("pillar", i, k): a contact is a substep in which the
    normal velocity was reversed.
    """
    p, v = np.array(p, dtype=np.float64, copy=True), np.array(v, dtype=np.float64, copy=True)
    _, n, _ = p.shape
    h = DT / SUBSTEPS
    contacts: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()

    def note(kind, i, j):
        if (kind, i, j) not in seen:
            seen.add((kind, i, j))
            contacts.append((kind, i, j))

    for _ in range(SUBSTEPS):
        p += v * h
        for d in range(2):
            lo, hi = p[..., d] < RADIUS, p[..., d] > ARENA - RADIUS
            if log:
                for i in np.flatnonzero((lo[0] & (v[0, :, d] < 0)) | (hi[0] & (v[0, :, d] > 0))):
                    note("wall", int(i), -1)
            v[..., d] = np.where(lo, np.abs(v[..., d]), np.where(hi, -np.abs(v[..., d]), v[..., d]))
            p[..., d] = np.clip(p[..., d], RADIUS, ARENA - RADIUS)
        for k, (cx, cy, cr) in enumerate(pillars):
            c = np.array([cx, cy])
            dvec = p - c
            dist = np.linalg.norm(dvec, axis=-1, keepdims=True)
            nrm = dvec / np.maximum(dist, 1e-9)
            hit = dist < cr + RADIUS
            vn = (v * nrm).sum(-1, keepdims=True)
            back = hit & (vn < 0)
            if log:
                for i in np.flatnonzero(back[0, :, 0]):
                    note("pillar", int(i), k)
            v = np.where(back, v - 2 * vn * nrm, v)
            p = np.where(hit, c + nrm * (cr + RADIUS), p)
        if disks and n > 1:
            d = p[:, None, :, :] - p[:, :, None, :]                 # d[b, i, j] = p_j - p_i
            dist = np.linalg.norm(d, axis=-1)
            nrm = d / np.maximum(dist, 1e-9)[..., None]
            rel = ((v[:, :, None, :] - v[:, None, :, :]) * nrm).sum(-1)  # (v_i - v_j) . n_ij
            upper = np.triu(np.ones((n, n), bool), 1)[None]
            ok = upper & (dist < 2 * RADIUS) & (dist > 1e-9)
            approach = ok & (rel > 0)
            if log:
                for i, j in zip(*np.nonzero(approach[0])):
                    note("disk", int(i), int(j))
            dv = np.where(approach[..., None], rel[..., None] * nrm, 0.0)  # equal masses
            v = v - dv.sum(2) + dv.sum(1)
            push = np.where(ok, 2 * RADIUS - dist, 0.0)[..., None] * nrm / 2
            p = p - push.sum(2) + push.sum(1)
    return p, v, contacts


# --- world ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Step:
    t: int
    agent: tuple[float, float, float]        # x, y, heading (declared truth input)
    detections: np.ndarray                   # [D, 2] world-frame positions, shuffled; student-visible
    truth_ids: np.ndarray                    # [D] identity of each detection; evaluation only
    positions: np.ndarray                    # [N, 2] truth
    velocities: np.ndarray                   # [N, 2] truth
    visible: np.ndarray                      # [N] bool truth
    contacts: tuple[tuple[str, int, int], ...]  # contacts during t -> t+1, truth


@dataclass(frozen=True)
class Episode:
    namespace: str
    world_index: int
    n_disks: int
    pillars: tuple[Pillar, ...]
    steps: tuple[Step, ...]


def _place_pillars(rng: np.random.Generator) -> tuple[Pillar, ...]:
    out: list[Pillar] = []
    while len(out) < N_PILLARS:
        c = rng.uniform(2, ARENA - 2, 2)
        r = rng.uniform(*PILLAR_RADIUS)
        if all(math.hypot(c[0] - a, c[1] - b) > r + rr + PILLAR_GAP for a, b, rr in out):
            out.append((float(c[0]), float(c[1]), float(r)))
    return tuple(out)


def _place_disks(rng: np.random.Generator, n: int, pillars: Sequence[Pillar]) -> tuple[np.ndarray, np.ndarray]:
    p: list[np.ndarray] = []
    while len(p) < n:
        c = rng.uniform(RADIUS + 0.1, ARENA - RADIUS - 0.1, 2)
        if all(math.hypot(*(c - q)) > 2 * RADIUS + 0.2 for q in p) and all(
            math.hypot(c[0] - a, c[1] - b) > rr + RADIUS + 0.2 for a, b, rr in pillars):
            p.append(c)
    ang = rng.uniform(0, 2 * math.pi, n)
    spd = rng.uniform(*SPEED, n)
    return np.array(p), np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)


def line_blocked(a: np.ndarray, b: np.ndarray, pillars: Sequence[Pillar]) -> bool:
    """Whether the segment a-b passes through a pillar."""
    ab = b - a
    lab = float(ab @ ab)
    for cx, cy, cr in pillars:
        c = np.array([cx, cy])
        s = 0.0 if lab == 0 else max(0.0, min(1.0, float((c - a) @ ab) / lab))
        if np.linalg.norm(a + s * ab - c) < cr:
            return True
    return False


def in_view(agent: tuple[float, float, float], q: np.ndarray, pillars: Sequence[Pillar]) -> bool:
    x, y, head = agent
    d = q - np.array([x, y])
    ang = abs((math.atan2(d[1], d[0]) - head + math.pi) % (2 * math.pi) - math.pi)
    return bool(math.hypot(d[0], d[1]) <= VIEW_RANGE and ang <= FOV / 2 and not line_blocked(np.array([x, y]), q, pillars))


def generate_episode(namespace: str, world_index: int, n_disks: int, *, steps: int = STEPS,
                     allow_registered: bool = False) -> Episode:
    """One world and its episode. Registered partitions are refused unless the caller is a registered run."""
    if namespace in REGISTERED and not allow_registered:
        raise PermissionError(f"{namespace} is a registered partition; only a registered run may generate it")
    wr = np.random.default_rng(derive_seed(namespace, "world", world_index))
    pillars = _place_pillars(wr)
    p, v = _place_disks(wr, n_disks, pillars)
    ar = np.random.default_rng(derive_seed(namespace, "agent", world_index))
    pos, head, goal = ar.uniform(1, ARENA - 1, 2), float(ar.uniform(0, 2 * math.pi)), ar.uniform(1, ARENA - 1, 2)
    out = []
    for t in range(steps):
        to = goal - pos
        if np.linalg.norm(to) < 0.5:
            goal = ar.uniform(1, ARENA - 1, 2)
            to = goal - pos
        dh = (math.atan2(to[1], to[0]) - head + math.pi) % (2 * math.pi) - math.pi
        head += max(-AGENT_TURN, min(AGENT_TURN, dh))
        pos = np.clip(pos + AGENT_STEP * np.array([math.cos(head), math.sin(head)]), 0.5, ARENA - 0.5)
        agent = (float(pos[0]), float(pos[1]), float(head))
        visible = np.array([in_view(agent, p[i], pillars) for i in range(n_disks)], dtype=bool)
        # Same draw order as tier1-explore/explore2.py, so the exploration worlds rebuild exactly.
        pairs = [(i, p[i] + ar.normal(0, SIGMA, 2)) for i in range(n_disks) if visible[i] and ar.random() > P_MISS]
        ar.shuffle(pairs)
        det = np.array([q for _, q in pairs]).reshape(-1, 2)
        truth_ids = np.array([i for i, _ in pairs], dtype=np.int64)
        pn, vn, cont = physics(p[None], v[None], pillars, log=True)
        out.append(Step(t, agent, det, truth_ids, p.copy(), v.copy(), visible, tuple(cont)))
        p, v = pn[0], vn[0]
    return Episode(namespace, world_index, n_disks, pillars, tuple(out))


def student_view(step: Step) -> dict[str, Any]:
    """What a tracker may read at a step: the agent pose and anonymous detection positions."""
    return {"t": step.t, "agent": step.agent, "detections": step.detections.copy()}


STUDENT_KEYS = frozenset({"t", "agent", "detections"})


# --- events -------------------------------------------------------------------------------------
def reappearances(ep: Episode) -> list[dict[str, Any]]:
    """Object k detected at a, not visible a+1..b-1, detected at b (b - a >= 2).

    ``collision`` is whether the contact log has a disk contact of k in a step s with a < s < b
    (the contacts of step s happen between s and s+1). Defined from the truth.
    """
    T = len(ep.steps)
    vis = np.array([s.visible for s in ep.steps])
    detected = [set(s.truth_ids.tolist()) for s in ep.steps]
    disk_contacts = [{i for kind, i, j in s.contacts if kind == "disk"} | {j for kind, i, j in s.contacts if kind == "disk"} for s in ep.steps]
    out = []
    for k in range(ep.n_disks):
        last = None
        for t in range(T):
            if vis[t, k]:
                if last is not None and t - last > 1 and k in detected[last] and k in detected[t]:
                    coll = any(k in disk_contacts[s] for s in range(last + 1, t))
                    out.append({"k": k, "a": last, "b": t, "gap": t - last - 1, "collision": bool(coll)})
                last = t
    return out
