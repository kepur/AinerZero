"""S4 phase 2 contact-gated process models (reports/V9-S4-P2-DESIGN, §3).

Per member and per disk: the prediction of a phase-1 learned model where the gate opens, otherwise
the hand-made wall-and-pillar rule E-B (``models.bounce``). Gates:

  head  the L-int contact head: some other disk within MSG_RADIUS whose pair logit gives a contact
        probability above ``p`` (logit > log(p / (1 - p)));
  geo   phase 1's contact baseline (``analysis.cv_contact_pairs``) on the member state: a pair
        approaching on straight lines that touches within one step, or overlapping and approaching.

Gates read only the member states the filter passes in (its own estimates), never the truth. With
the gate closed the prediction is E-B's bit for bit, with it open the learned model's bit for bit.
"""

from __future__ import annotations

import math
from typing import Callable, Sequence

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

ProcessModel = Callable[[np.ndarray, np.ndarray, Sequence[W.Pillar]], tuple]


def geo_gate(P: np.ndarray, V: np.ndarray) -> np.ndarray:
    """[M, n] bool for member states P, V [M, n, 2]: the disk is in a pair that the phase-1 contact
    baseline flags (approaching and touching within DT on straight lines, or overlapping and approaching)."""
    d = P[:, None, :, :] - P[:, :, None, :]                  # d[m, i, j] = p_j - p_i
    u = V[:, None, :, :] - V[:, :, None, :]
    a = (u * u).sum(-1)
    b = 2 * (d * u).sum(-1)
    c = (d * d).sum(-1) - (2 * W.RADIUS) ** 2
    disc = b * b - 4 * a * c
    with np.errstate(invalid="ignore", divide="ignore"):
        tau = (-b - np.sqrt(np.maximum(disc, 0.0))) / (2 * np.where(a > 0, a, 1.0))
    hit = ((c <= 0) & (b < 0)) | ((a > 0) & (disc >= 0) & (b < 0) & (tau >= 0) & (tau < W.DT))
    hit &= ~np.eye(P.shape[1], dtype=bool)[None]
    return hit.any(-1)


def head_gate(logits: np.ndarray, P: np.ndarray, p: float) -> np.ndarray:
    """[M, n] bool: some other disk within MSG_RADIUS with contact probability above ``p``."""
    if not 0.0 < p < 1.0:
        raise ValueError("the gate threshold must lie in (0, 1)")
    n = P.shape[1]
    dist = np.linalg.norm(P[:, :, None] - P[:, None], axis=-1)
    near = (dist < L.MSG_RADIUS) & ~np.eye(n, dtype=bool)[None]
    return ((np.asarray(logits, dtype=np.float64) > math.log(p / (1 - p))) & near).any(-1)


def gated_model(net: L.Dynamics, gate: str | float, *, counter: list | None = None) -> ProcessModel:
    """Process model (P, V [M, n, 2], pillars) -> (P', V'). ``gate`` is a head threshold p in (0, 1) or
    "geo". The head gate needs an interaction arm (L-int). ``counter``, if given, accumulates
    [disk-steps with the gate open, all disk-steps]."""
    if gate != "geo":
        p = float(gate)
        if not 0.0 < p < 1.0:
            raise ValueError("the gate threshold must lie in (0, 1)")
        if not net.interact:
            raise ValueError("the contact-head gate needs a model with a contact head")
    if net.arm == "L-int-s":
        raise ValueError("gate a mean model, not L-int-s")

    def step(P, V, pillars):
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            if counter is not None:
                counter[1] += P.shape[0] * P.shape[1]
            return pb, vb
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        p_, v_, logits, _ = net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        mx.eval(p_, v_)
        g = geo_gate(P, V) if gate == "geo" else head_gate(np.array(logits), P, float(gate))
        if counter is not None:
            counter[0] += int(g.sum())
            counter[1] += int(g.size)
        g = g[..., None]
        return (np.where(g, np.array(p_, dtype=np.float64), pb), np.where(g, np.array(v_, dtype=np.float64), vb))
    return step
