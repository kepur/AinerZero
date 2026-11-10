"""S4 phase 1 tracker: an ensemble Kalman filter with a pluggable process model.

Per reports/V9-S4-DESIGN/DESIGN-r3.md §4. Pure CPU, NumPy / standard library only.

Each step:
  1. predict: member m of every track goes through the process model together (so an
     interaction model sees the other tracks inside each member); then the registered process
     noise is added, or, for a model that returns variances, noise drawn from them;
  2. associate: Euclidean distance between detections and track ensemble means, Hungarian
     assignment, gate 0.6 + 1.5 * seconds since the track was last assigned; an unassigned
     detection starts a track at the detection with velocities from the prior;
  3. update: perturbed-observation EnKF update of each assigned track.

The tracker reads student views only (detection positions); truth identities are used by the
scoring code, never here. The new-track velocity prior (uniform direction, speed 0.6-1.4) is the
generator's speed distribution and is a declared truth input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4.assign import hungarian

# A process model maps member states P, V [M, n, 2] and the pillars to the next P, V, optionally
# with per-coordinate variances (var_p, var_v) of the same shape.
ProcessModel = Callable[[np.ndarray, np.ndarray, Sequence[W.Pillar]], tuple]


@dataclass(frozen=True)
class FilterConfig:
    members: int = 32
    q_pos: float = 0.01
    q_vel: float = 0.05
    obs_sigma: float = W.SIGMA
    gate_base: float = 0.6
    gate_grow: float = 1.5
    speed: tuple[float, float] = W.SPEED


def _predict(P, V, model, pillars, cfg, rng):
    out = model(P, V, pillars)
    P2, V2 = out[0], out[1]
    if len(out) == 4:  # a model with learned variances: sample from them instead of the registered noise
        P2 = P2 + rng.normal(0.0, 1.0, P2.shape) * np.sqrt(np.maximum(out[2], 0.0))
        V2 = V2 + rng.normal(0.0, 1.0, V2.shape) * np.sqrt(np.maximum(out[3], 0.0))
    else:
        P2 = P2 + rng.normal(0.0, cfg.q_pos, P2.shape)
        V2 = V2 + rng.normal(0.0, cfg.q_vel, V2.shape)
    return P2, V2


def _associate(P, z, last, t, cfg):
    if P.shape[1] == 0 or len(z) == 0:
        return {}
    mu = P.mean(0)
    dist = np.linalg.norm(z[:, None, :] - mu[None], axis=-1)
    out = {}
    for r, c in hungarian(dist):
        if dist[r, c] <= cfg.gate_base + cfg.gate_grow * W.DT * (t - last[c]):
            out[r] = c
    return out


def _update(P, V, k, q, cfg, rng):
    M = P.shape[0]
    X = np.concatenate([P[:, k], V[:, k]], 1)                    # [M, 4]
    A = X - X.mean(0)
    Hx = P[:, k]
    Pxz = A.T @ (Hx - Hx.mean(0)) / (M - 1)                       # [4, 2]
    Pzz = np.cov(Hx.T) + np.eye(2) * cfg.obs_sigma ** 2
    K = Pxz @ np.linalg.inv(Pzz)
    zp = q + rng.normal(0.0, cfg.obs_sigma, (M, 2))
    X = X + (zp - Hx) @ K.T
    P[:, k], V[:, k] = X[:, :2], X[:, 2:]


def _new_track(P, V, q, cfg, rng):
    M = cfg.members
    newP = q + rng.normal(0.0, cfg.obs_sigma, (M, 1, 2))
    ang = rng.uniform(0.0, 2 * math.pi, M)
    spd = rng.uniform(*cfg.speed, M)
    newV = np.stack([np.cos(ang) * spd, np.sin(ang) * spd], 1)[:, None, :]
    return np.concatenate([P, newP], 1), np.concatenate([V, newV], 1)


def track(detections: Sequence[np.ndarray], pillars: Sequence[W.Pillar], model: ProcessModel,
          rng: np.random.Generator, cfg: FilterConfig = FilterConfig()) -> tuple[list[np.ndarray], int]:
    """Track one episode from its detection lists. Returns (track id per detection per step, number of tracks)."""
    M = cfg.members
    P = np.zeros((M, 0, 2))
    V = np.zeros((M, 0, 2))
    last: list[int] = []
    out: list[np.ndarray] = []
    for t, z in enumerate(detections):
        z = np.asarray(z, dtype=np.float64).reshape(-1, 2)
        if P.shape[1]:
            P, V = _predict(P, V, model, pillars, cfg, rng)
        assign = _associate(P, z, last, t, cfg)
        ids = np.empty(len(z), dtype=np.int64)
        for r in range(len(z)):
            if r in assign:
                k = assign[r]
                _update(P, V, k, z[r], cfg, rng)
                last[k] = t
                ids[r] = k
            else:
                P, V = _new_track(P, V, z[r], cfg, rng)
                last.append(t)
                ids[r] = P.shape[1] - 1
        out.append(ids)
    return out, P.shape[1]


def track_truth_diagnostic(ep: W.Episode, model: ProcessModel, rng: np.random.Generator,
                           cfg: FilterConfig = FilterConfig()) -> tuple[list[np.ndarray], int]:
    """Diagnostic upper reference S-P: on assignment (and at birth) a track's members are set to the
    true state of the detected disk. Reads the truth; never a student arm."""
    M = cfg.members
    P = np.zeros((M, 0, 2))
    V = np.zeros((M, 0, 2))
    last: list[int] = []
    out = []
    for t, s in enumerate(ep.steps):
        z = s.detections
        if P.shape[1]:
            P, V = _predict(P, V, model, ep.pillars, cfg, rng)
        assign = _associate(P, z, last, t, cfg)
        ids = np.empty(len(z), dtype=np.int64)
        for r in range(len(z)):
            truth = int(s.truth_ids[r])
            if r in assign:
                k = assign[r]
                P[:, k], V[:, k] = s.positions[truth], s.velocities[truth]
                last[k] = t
                ids[r] = k
            else:
                P, V = _new_track(P, V, z[r], cfg, rng)
                P[:, -1], V[:, -1] = s.positions[truth], s.velocities[truth]
                last.append(t)
                ids[r] = P.shape[1] - 1
        out.append(ids)
    return out, P.shape[1]
