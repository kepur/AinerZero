#!/usr/bin/env python3
"""P215: crude contact responses behind the main arm's gate, against GR (s4x-p2a main worlds only).

Every arm here uses exactly the L-int-g gate (L-int contact head on the member state, p = 0.5, via
gated.head_gate) and E-B's position; only the velocity where the gate is open differs:

  H-zero     velocity set to zero
  H-rev      velocity reversed (-v_EB)
  H-mirror   v_EB mirrored about the line of centres to the nearest other disk of the member:
             v - 2 (v . n) n, n = unit vector to that disk (applied whenever the gate is open)
  H-elastic  the analytic equal-mass elastic exchange with the nearest other disk, if approaching:
             v_i - ((v_i - v_j) . n) n  (the collision law of the generator itself, i.e. hand physics;
             a reference for "the right response at this gate", not an admissible learned arm)

The step function copies gated.GatedModel.__call__ line for line except the response. The arms are
deterministic (no generator). Tracking uses the registered analysis_p2.world_record (same filter, same
"base" filter seeds, same hooks, same dynamics sums), so the cells merge with round G's stored records
(tier1-explore/results-p2g.json) for E-B, E-P, L-int-g and L-sc-g.

Usage (MLX; under the shared lock; repository root): <this> N_MAIN OUT.json
"""
from __future__ import annotations

import json
import sys
import time

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import gated as G
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NS = "s4x-p2a"
WDIR = "artifacts/v9/s4/phase1/final-final/weights"
ARMS = ("H-zero", "H-rev", "H-mirror", "H-elastic")


def nearest_unit(P):
    """[M, n] index of the nearest other disk and [M, n, 2] unit vector towards it (member state P [M, n, 2])."""
    d = P[:, None, :, :] - P[:, :, None, :]                      # d[m, i, j] = p_j - p_i
    dist = np.linalg.norm(d, axis=-1) + np.eye(P.shape[1])[None] * 1e9
    j = dist.argmin(-1)
    dj = np.take_along_axis(d, j[..., None, None].repeat(2, -1), axis=2)[:, :, 0, :]
    return j, dj / np.maximum(np.linalg.norm(dj, axis=-1, keepdims=True), 1e-9)


def response(kind, P, vb):
    if kind == "H-zero":
        return np.zeros_like(vb)
    if kind == "H-rev":
        return -vb
    j, n = nearest_unit(P)
    if kind == "H-mirror":
        return vb - 2 * (vb * n).sum(-1, keepdims=True) * n
    if kind == "H-elastic":
        vj = np.take_along_axis(vb, j[..., None].repeat(2, -1), axis=1)
        rel = ((vb - vj) * n).sum(-1, keepdims=True)              # (v_i - v_j) . n_ij, > 0 approaching
        return np.where(rel > 0, vb - rel * n, vb)
    raise ValueError(kind)


def heuristic(kind, net, counter=None):
    def step(P, V, pillars):
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            if counter is not None:
                counter[1] += P.shape[0] * P.shape[1]
            return pb, vb
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        p_, v_, logits, _ = net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        mx.eval(p_, v_)
        g = G.head_gate(np.array(logits), P, 0.5)
        if counter is not None:
            counter[0] += int(g.sum())
            counter[1] += int(g.size)
        return pb, np.where(g[..., None], response(kind, P, vb), vb)
    return step


def main():
    n, out = int(sys.argv[1]), sys.argv[2]
    mx.set_default_device(mx.cpu)
    lint = {s: L.load("L-int", f"{WDIR}/L-int#{s}.safetensors") for s in P2.SEEDS}
    t0 = time.time()
    recs = []
    for kind, w, d in A.eval_world_ids((n, 0)):
        ep = W.generate_episode(NS, w, d)
        models, counters, dyn = {}, {}, {}
        for s in P2.SEEDS:
            for a in ARMS:
                c = [0, 0]
                counters[f"{a}#{s}"] = c
                models[f"{a}#{s}"] = heuristic(a, lint[s], c)
                dyn[f"{a}#{s}"] = heuristic(a, lint[s])
        recs.append(P2.world_record(ep, kind, NS, models, counters=counters, dyn_models=dyn))
        print(f"{kind} {w} {time.time() - t0:.0f}s", flush=True)
        with open(out, "w") as f:
            json.dump({"namespace": NS, "arms": ARMS, "records": recs}, f)
    print(f"done {len(recs)} worlds {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
