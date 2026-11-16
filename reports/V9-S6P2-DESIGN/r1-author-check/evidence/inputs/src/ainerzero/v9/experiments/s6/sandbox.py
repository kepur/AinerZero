#!/usr/bin/env python3
"""S6 sandbox: a candidate pool of states whose outcomes are simulated only when chosen, and the pick rules.

DESIGN-r2 §2-§3, §6. The learner sees candidate *states* (positions, velocities, pillars) and chooses
which ones to run before anything about their outcome exists in the process: ``CandidatePool`` keeps
states only, and ``reveal`` runs the simulator (``sim_labels``, the same rollout as
``learned_mlx.make_pool``) on the chosen states, once per sample, with a log. Unrevealed outcomes are
never computed, so there is nothing to read. The pick rules take scores, flags or states, never labels.

Global ids flatten the pool by (disk count, index), disk counts ascending.

States are kept in float64 for the simulator and handed out in float32 (what the learner trains on, as
``make_pool``); labels are float32.

Pure NumPy: no MLX import (``gated.geo_gate`` imports MLX, so ``geo_flags`` restates its formula; a
native test checks the two agree sample by sample).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ainerzero.v9.experiments.s4 import world as W

STATE_KEYS = ("p", "v", "pil")
ROLLOUT = (1, 5, 10)                       # as learned_mlx.ROLLOUT; a native test checks they agree
LABEL_KEYS = ("contact",) + tuple(f"{x}{k}" for k in ROLLOUT for x in "pv")


@dataclass(frozen=True)
class LabelledPool:
    """Pool-shaped result when no pool type is given (``learned_mlx.Pool`` has the same shape)."""
    by_n: dict

    def size(self) -> int:
        return sum(len(e["p"]) for e in self.by_n.values())


def sim_labels(P: np.ndarray, V: np.ndarray, PIL: np.ndarray) -> dict[str, np.ndarray]:
    """Simulator outcome of each state, labelled as ``learned_mlx.make_pool`` does: step 1 with the
    disk-contact log, then steps 2..10; positions and velocities after 1, 5 and 10 steps. P, V
    [S, n, 2] and PIL [S, 3, 3] in float64. Returns float32 arrays."""
    S_, n = P.shape[0], P.shape[1]
    out = {k: np.empty((S_, n, 2)) for k in LABEL_KEYS if k != "contact"}
    contact = np.zeros((S_, n, n), dtype=np.float32)
    for b in range(S_):
        pillars = tuple(map(tuple, PIL[b]))
        p, v, c = W.physics(P[b:b + 1], V[b:b + 1], pillars, log=True)
        for kind, i, j in c:
            if kind == "disk":
                contact[b, i, j] = contact[b, j, i] = 1.0
        for k in range(1, max(ROLLOUT) + 1):
            if k > 1:
                p, v, _ = W.physics(p, v, pillars)
            if k in ROLLOUT:
                out[f"p{k}"][b], out[f"v{k}"][b] = p[0], v[0]
    return {"contact": contact, **{k: a.astype(np.float32) for k, a in out.items()}}


class CandidatePool:
    """Candidate states; outcomes simulated on reveal only.

    ``states_by_n[n]`` holds exactly ``p``, ``v`` [S, n, 2] and ``pil`` [S, 3, 3] (stored in float64).
    ``labeller`` maps (P, V, PIL) of some samples to their label arrays (default ``sim_labels``).
    ``pool_type`` builds the returned pools from ``by_n`` (the runner passes ``learned_mlx.Pool``)."""

    def __init__(self, states_by_n: dict[int, dict[str, np.ndarray]], *, labeller: Callable | None = None,
                 pool_type: Callable = LabelledPool):
        if not states_by_n:
            raise ValueError("empty candidate pool")
        self._labeller = sim_labels if labeller is None else labeller
        self._pool_type = pool_type
        self._states: dict[int, dict[str, np.ndarray]] = {}
        index: list[tuple[int, int]] = []
        self._first_id: dict[int, int] = {}
        first = 0
        for n in sorted(states_by_n):
            e = states_by_n[n]
            if set(e) != set(STATE_KEYS):
                raise ValueError(f"bucket n={n} must hold exactly {STATE_KEYS}, got {sorted(e)}")
            size = len(e["p"])
            if size == 0 or np.shape(e["p"]) != (size, n, 2) or np.shape(e["v"]) != (size, n, 2) \
                    or np.shape(e["pil"]) != (size, 3, 3):
                raise ValueError(f"bucket n={n}: bad shapes {np.shape(e['p'])}, {np.shape(e['v'])}, {np.shape(e['pil'])}")
            self._states[n] = {k: np.array(e[k], dtype=np.float64, copy=True) for k in STATE_KEYS}
            self._first_id[n] = first
            index.extend((n, i) for i in range(size))
            first += size
        self._index = np.array(index, dtype=np.int64)            # [N, 2]: (n, i) per global id
        self._revealed: list[int] = []
        self._revealed_set: set[int] = set()
        self._outcomes: dict[int, dict[str, np.ndarray]] = {}    # global id -> labels, for revealed ids only
        self._log: list[dict[str, Any]] = []

    # --- public, outcome-free ------------------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self._index)

    def states(self) -> dict[int, dict[str, np.ndarray]]:
        """Per disk count n: ``id`` [S] (global ids) and p, v [S, n, 2], pil [S, 3, 3] in float32.
        Fresh read-only copies; no outcome."""
        out = {}
        for n, e in self._states.items():
            ids = np.arange(self._first_id[n], self._first_id[n] + len(e["p"]), dtype=np.int64)
            row = {"id": ids, **{k: v.astype(np.float32) for k, v in e.items()}}
            for a in row.values():
                a.flags.writeable = False
            out[n] = row
        return out

    def remaining(self) -> np.ndarray:
        """Global ids not yet revealed, ascending."""
        mask = np.ones(len(self._index), dtype=bool)
        if self._revealed:
            mask[np.array(self._revealed, dtype=np.int64)] = False
        return np.flatnonzero(mask).astype(np.int64)

    def revealed_ids(self) -> np.ndarray:
        """Global ids revealed so far, in reveal order."""
        return np.array(self._revealed, dtype=np.int64)

    def log(self) -> list[dict[str, Any]]:
        """One entry per ``reveal`` call: {"call": k (from 0), "ids": [...]}. A copy."""
        return [{"call": r["call"], "ids": list(r["ids"])} for r in self._log]

    # --- the sandbox ----------------------------------------------------------------------------------------
    def reveal(self, ids) -> Any:
        """Run the sandbox on these candidates (at least one): simulate their outcomes and return exactly
        these samples with labels, grouped by disk count (ascending), in the given order within a group.
        Each id may be revealed once; a repeat (within the call or across calls) raises before anything is
        simulated. If simulating fails, nothing is registered."""
        ids = self._check_new(ids)
        outcomes = self._simulate(ids)
        self._revealed.extend(ids)
        self._revealed_set.update(ids)
        self._outcomes.update(outcomes)
        self._log.append({"call": len(self._log), "ids": list(ids)})
        return self._assemble(ids)

    def revealed_pool(self) -> Any:
        """Every revealed sample so far, in reveal order within each disk count: the training pool."""
        return self._assemble(list(self._revealed))

    # --- private ----------------------------------------------------------------------------------------------
    def _check_new(self, ids) -> list[int]:
        arr = np.asarray(ids)
        if arr.ndim != 1:
            raise ValueError("ids must be one-dimensional")
        if arr.size == 0:
            raise ValueError("reveal needs at least one id")
        if not np.issubdtype(arr.dtype, np.integer):
            raise TypeError("ids must be integers")
        out = [int(x) for x in arr]
        if any(x < 0 or x >= len(self._index) for x in out):
            raise IndexError("id out of range")
        if len(set(out)) != len(out):
            raise ValueError("duplicate id within one reveal")
        again = sorted(set(out) & self._revealed_set)
        if again:
            raise ValueError(f"ids already revealed: {again[:10]}")
        return out

    def _groups(self, ids: list[int]) -> dict[int, tuple[list[int], np.ndarray]]:
        groups: dict[int, tuple[list[int], list[int]]] = {}
        for g in ids:
            n, i = (int(x) for x in self._index[g])
            gs, rows = groups.setdefault(n, ([], []))
            gs.append(g); rows.append(i)
        return {n: (gs, np.array(rows, dtype=np.int64)) for n, (gs, rows) in groups.items()}

    def _simulate(self, ids: list[int]) -> dict[int, dict[str, np.ndarray]]:
        """The only call of the labeller; ``reveal`` is its only caller (checked by a test)."""
        out = {}
        for n, (gs, rows) in self._groups(ids).items():
            e = self._states[n]
            lab = self._labeller(e["p"][rows], e["v"][rows], e["pil"][rows])
            missing = set(LABEL_KEYS) - set(lab)
            if missing:
                raise ValueError(f"labeller did not return {sorted(missing)}")
            for j, g in enumerate(gs):
                out[g] = {k: np.array(lab[k][j], dtype=np.float32, copy=True) for k in LABEL_KEYS}
        return out

    def _assemble(self, ids: list[int]) -> Any:
        """Revealed ids only (raises KeyError otherwise)."""
        by_n = {}
        for n, (gs, rows) in sorted(self._groups(ids).items()):
            e = self._states[n]
            by_n[n] = {**{k: e[k][rows].astype(np.float32) for k in STATE_KEYS},
                       **{k: np.stack([self._outcomes[g][k] for g in gs]) for k in LABEL_KEYS}}
        return self._pool_type(by_n)


# --- pick rules: scores, flags or states only ----------------------------------------------------------
def _canon(remaining, k: int, size: int | None = None) -> np.ndarray:
    rem = np.asarray(remaining)
    if rem.ndim != 1:
        raise ValueError("remaining must be one-dimensional")
    if rem.size and not np.issubdtype(rem.dtype, np.integer):
        raise TypeError("remaining must hold integer ids")
    rem = rem.astype(np.int64)
    srt = np.unique(rem)
    if len(srt) != len(rem):
        raise ValueError("remaining has duplicate ids")
    if srt.size and (srt[0] < 0 or (size is not None and srt[-1] >= size)):
        raise IndexError("remaining id out of range")
    if not 0 <= k <= len(srt):
        raise ValueError(f"cannot pick {k} from {len(srt)} remaining")
    return srt


def pick_random(remaining, k: int, rng: np.random.Generator) -> np.ndarray:
    """k ids drawn uniformly without replacement from ``remaining`` (taken ascending, so the order the
    caller lists them in does not matter)."""
    rem = _canon(remaining, k)
    return rng.choice(rem, k, replace=False).astype(np.int64)


def pick_top(score, remaining, k: int) -> np.ndarray:
    """The k remaining ids with the largest score (``score`` indexed by global id); ties by id ascending.
    Returned in that order (score descending)."""
    s = np.asarray(score, dtype=np.float64)
    if s.ndim != 1:
        raise ValueError("score must be one-dimensional, indexed by global id")
    rem = _canon(remaining, k, len(s))
    sr = s[rem]
    if not np.all(np.isfinite(sr)):
        raise ValueError("non-finite score among remaining ids")
    order = np.lexsort((rem, -sr))
    return rem[order[:k]]


def pick_geo(flags, remaining, k: int, rng: np.random.Generator) -> np.ndarray:
    """Up to k flagged remaining ids at random (``flags`` bool, indexed by global id); if fewer than k
    are flagged, the rest drawn at random from the unflagged remaining ids."""
    f = np.asarray(flags)
    if f.dtype != bool or f.ndim != 1:
        raise ValueError("flags must be a one-dimensional bool array indexed by global id")
    rem = _canon(remaining, k, len(f))
    flagged = rem[f[rem]]
    take = rng.choice(flagged, min(k, len(flagged)), replace=False).astype(np.int64)
    if len(take) < k:
        fill = rng.choice(np.setdiff1d(rem, take), k - len(take), replace=False).astype(np.int64)
    else:
        fill = np.array([], dtype=np.int64)
    return np.concatenate([take, fill])


def geo_flags(states: dict[int, dict[str, np.ndarray]]) -> np.ndarray:
    """[N] bool by global id: some pair of disks, moving on straight lines, touches within one step
    while approaching, or already overlaps while approaching. Same formula as ``s4.gated.geo_gate``
    (any disk of the sample), on the float64 cast of the states."""
    total = 1 + max((int(np.max(e["id"])) for e in states.values() if len(e["id"])), default=-1)
    out = np.zeros(total, dtype=bool)
    seen = np.zeros(total, dtype=bool)
    for e in states.values():
        P = np.asarray(e["p"], dtype=np.float64)
        V = np.asarray(e["v"], dtype=np.float64)
        d = P[:, None, :, :] - P[:, :, None, :]
        u = V[:, None, :, :] - V[:, :, None, :]
        a = (u * u).sum(-1)
        b = 2 * (d * u).sum(-1)
        c = (d * d).sum(-1) - (2 * W.RADIUS) ** 2
        disc = b * b - 4 * a * c
        with np.errstate(invalid="ignore", divide="ignore"):
            tau = (-b - np.sqrt(np.maximum(disc, 0.0))) / (2 * np.where(a > 0, a, 1.0))
        hit = ((c <= 0) & (b < 0)) | ((a > 0) & (disc >= 0) & (b < 0) & (tau >= 0) & (tau < W.DT))
        hit &= ~np.eye(P.shape[1], dtype=bool)[None]
        ids = np.asarray(e["id"], dtype=np.int64)
        out[ids] = hit.any(-1).any(-1)
        seen[ids] = True
    if not seen.all():
        raise ValueError("states do not cover ids 0..N-1")
    return out
