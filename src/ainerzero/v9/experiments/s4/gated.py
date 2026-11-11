"""S4 phase 2 contact-gated process models (reports/V9-S4-P2-DESIGN, §3).

Per member and per disk: where the gate opens, the response of the arm, otherwise the hand-made
wall-and-pillar rule E-B (``models.bounce``, the generator's physics without disk-disk collisions).

Gates:
  head p        the L-int contact head: some other disk within MSG_RADIUS whose pair logit gives a
                contact probability above ``p`` (logit > log(p / (1 - p)));
  "geo"         phase 1's contact baseline (``analysis.cv_contact_pairs``) on the member state: a pair
                approaching on straight lines that touches within one step, or overlapping and approaching;
  ("random", r) each member and disk opens independently with probability r (a control: same share,
                no timing).

Responses where the gate is open:
  "learned"     the prediction of the phase-1 model (L-int or L-ind), bit for bit;
  "scatter"     E-B's position, and E-B's velocity turned by an angle drawn uniformly per member and
                disk (speed kept): a control that knows when a contact comes but not what it does.

Gates read only the member states the filter passes in (its own estimates), never the truth, and
never call the generator's physics with disk collisions (``true_physics``). Stochastic arms (a random
gate or the scatter response) draw from their own generator, which ``reseed`` must set before every
tracking or dynamics pass; they refuse to run without it.
"""

from __future__ import annotations

import math
from typing import Sequence

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

RESPONSES = ("learned", "scatter")


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


def scatter_velocity(v: np.ndarray, theta: np.ndarray) -> np.ndarray:
    """Turn each velocity v [..., 2] by the angle theta [...]; the speed is kept."""
    c, s = np.cos(theta), np.sin(theta)
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)


class GatedModel:
    """Process model (P, V [M, n, 2], pillars) -> (P', V'). See the module docstring for gates and
    responses. ``counter``, if given, accumulates [disk-steps with the gate open, all disk-steps]."""

    def __init__(self, net: L.Dynamics, gate, *, response: str = "learned", counter: list | None = None):
        if net.arm == "L-int-s":
            raise ValueError("gate a mean model, not L-int-s")
        if response not in RESPONSES:
            raise ValueError(f"unknown response {response!r}")
        if isinstance(gate, (tuple, list)):
            if len(gate) != 2 or gate[0] != "random" or not 0.0 < float(gate[1]) < 1.0:
                raise ValueError("a random gate is ('random', rate) with rate in (0, 1)")
            self.kind, self.rate = "random", float(gate[1])
        elif gate == "geo":
            self.kind = "geo"
        else:
            p = float(gate)
            if not 0.0 < p < 1.0:
                raise ValueError("the gate threshold must lie in (0, 1)")
            if not net.interact:
                raise ValueError("the contact-head gate needs a model with a contact head")
            self.kind, self.p = "head", p
        self.net, self.response, self.counter = net, response, counter
        self.stochastic = self.kind == "random" or response == "scatter"
        self._rng: np.random.Generator | None = None

    def reseed(self, seed: int) -> None:
        self._rng = np.random.default_rng(seed)

    def __call__(self, P, V, pillars):
        if self.stochastic and self._rng is None:
            raise RuntimeError("a stochastic gated arm needs reseed() before it runs")
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            if self.counter is not None:
                self.counter[1] += P.shape[0] * P.shape[1]
            return pb, vb
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        p_, v_, logits, _ = self.net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        mx.eval(p_, v_)
        if self.kind == "geo":
            g = geo_gate(P, V)
        elif self.kind == "head":
            g = head_gate(np.array(logits), P, self.p)
        else:
            g = self._rng.random(P.shape[:2]) < self.rate
        if self.counter is not None:
            self.counter[0] += int(g.sum())
            self.counter[1] += int(g.size)
        if self.response == "scatter":
            theta = self._rng.uniform(0.0, 2 * math.pi, P.shape[:2])
            return pb, np.where(g[..., None], scatter_velocity(vb, theta), vb)
        g = g[..., None]
        return (np.where(g, np.array(p_, dtype=np.float64), pb), np.where(g, np.array(v_, dtype=np.float64), vb))


def gated_model(net: L.Dynamics, gate, *, response: str = "learned", counter: list | None = None) -> GatedModel:
    return GatedModel(net, gate, response=response, counter=counter)


def reseed_if_stochastic(model, seed: int) -> None:
    """Set the generator of a stochastic arm; a deterministic model is left alone."""
    if getattr(model, "stochastic", False):
        model.reseed(seed)
