#!/usr/bin/env python3
"""P213 non-author review: surrogate gates for the S4 phase-2 design r0 (exploration worlds s4x-p2a only).

Tracks every arm with the registered phase-2 evaluation code (analysis_p2.world_record: same filter,
same filter seeds "base", same calibration hooks, same dynamics sums) and writes one record per world.
Arms (three seeds each; hand arms with the three filter seeds):

  E-CV, E-B, E-P   hand models (models.HAND_MODELS)
  L-int-g          registered main arm: gated.gated_model(L-int, 0.5)           (reference)
  L-ind-geo        registered negative control: gated.gated_model(L-ind, "geo") (needed by decide())
  L-int            gate always open  = phase-1 L-int ungated (learned_mlx.as_process_model), as the worker builds it
  OFF              gate always closed: the gated code path with an all-False gate (must equal E-B bit for bit)
  RAND             random gate: each member, disk and step opens independently with probability RATE;
                   open -> L-int prediction, closed -> E-B (RATE = the design's 2.0% gate share)
  L-ind-g          extra: the L-int contact head as the gate (p = 0.5), prediction from L-ind (no interaction)
  SCATTER          extra: geometric gate; open -> E-B position, E-B velocity rotated by a uniform random
                   angle (knows *when* a contact happens, not *how*; only widens the ensemble)

The surrogate step functions mirror gated.gated_model line for line except for the gate decision.
Random numbers of RAND / SCATTER come from their own generators seeded per (world, seed, use) under
the seed label "s4x-p2rev" (no world is generated under that label).

Usage (MLX; run from the repository root under the shared lock):
  hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -I -B <this> KIND N OUT.json
  KIND = main (worlds 0..N-1, 6 disks) or extrap (worlds 1000..1000+N-1, 10 disks)
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
RATE = 0.020
SEED_LABEL = "s4x-p2rev"
SURROGATES = ("L-int-g", "L-ind-geo", "L-int", "OFF", "RAND", "L-ind-g", "SCATTER")


def _pil(P, pillars):
    return mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))


def surrogate(kind: str, lint: L.Dynamics, lind: L.Dynamics, rng: np.random.Generator | None, counter: list | None = None):
    """Process model (P, V, pillars) -> (P', V'): gated.gated_model with a surrogate gate / response."""
    pred_net = lind if kind == "L-ind-g" else lint

    def step(P, V, pillars):
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            if counter is not None:
                counter[1] += P.shape[0] * P.shape[1]
            return pb, vb
        pil = _pil(P, pillars)
        x_p, x_v = mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32))
        p_, v_, logits, _ = pred_net(x_p, x_v, pil)
        mx.eval(p_, v_)
        if kind == "OFF":
            g = np.zeros(P.shape[:2], dtype=bool)
        elif kind == "RAND":
            g = rng.random(P.shape[:2]) < RATE
        elif kind == "L-ind-g":
            _, _, lg, _ = lint(x_p, x_v, pil)
            g = G.head_gate(np.array(lg), P, 0.5)
        elif kind == "SCATTER":
            g = G.geo_gate(P, V)
        else:
            raise ValueError(kind)
        if counter is not None:
            counter[0] += int(g.sum())
            counter[1] += int(g.size)
        if kind == "SCATTER":
            th = rng.uniform(0.0, 2 * np.pi, P.shape[:2])
            c, s = np.cos(th), np.sin(th)
            vr = np.stack([c * vb[..., 0] - s * vb[..., 1], s * vb[..., 0] + c * vb[..., 1]], -1)
            return pb, np.where(g[..., None], vr, vb)
        g = g[..., None]
        return (np.where(g, np.array(p_, dtype=np.float64), pb), np.where(g, np.array(v_, dtype=np.float64), vb))
    return step


def main():
    kind, n, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    assert kind in ("main", "extrap")
    mx.set_default_device(mx.cpu)
    lint = {s: L.load("L-int", f"{WDIR}/L-int#{s}.safetensors") for s in P2.SEEDS}
    lind = {s: L.load("L-ind", f"{WDIR}/L-ind#{s}.safetensors") for s in P2.SEEDS}
    ids = [(k, w, d) for k, w, d in A.eval_world_ids((n, 0) if kind == "main" else (0, n))]
    t0 = time.time()
    recs = []
    for k, w, d in ids:
        ep = W.generate_episode(NS, w, d)
        models = {a: Mo.HAND_MODELS[a] for a in P2.HAND}
        counters, dyn = {}, {"E-B": Mo.bounce}
        for s in P2.SEEDS:
            for arm in SURROGATES:
                c = [0, 0]
                counters[f"{arm}#{s}"] = c
                if arm == "L-int-g":
                    models[f"{arm}#{s}"] = G.gated_model(lint[s], 0.5, counter=c)
                    dyn[f"{arm}#{s}"] = G.gated_model(lint[s], 0.5)
                elif arm == "L-ind-geo":
                    models[f"{arm}#{s}"] = G.gated_model(lind[s], "geo", counter=c)
                    dyn[f"{arm}#{s}"] = G.gated_model(lind[s], "geo")
                elif arm == "L-int":
                    models[f"{arm}#{s}"] = dyn[f"{arm}#{s}"] = L.as_process_model(lint[s])
                    del counters[f"{arm}#{s}"]
                else:
                    r_track = np.random.default_rng(W.derive_seed(SEED_LABEL, arm, "track", w, s))
                    r_dyn = np.random.default_rng(W.derive_seed(SEED_LABEL, arm, "dyn", w, s))
                    models[f"{arm}#{s}"] = surrogate(arm, lint[s], lind[s], r_track, counter=c)
                    dyn[f"{arm}#{s}"] = surrogate(arm, lint[s], lind[s], r_dyn)
        rec = P2.world_record(ep, k, NS, models, counters=counters, dyn_models=dyn)
        recs.append(rec)
        print(f"{k} {w} {time.time() - t0:.0f}s", flush=True)
        with open(out, "w") as f:   # rewritten after every world, so a stopped run keeps its worlds
            json.dump({"namespace": NS, "kind": kind, "rate": RATE, "seed_label": SEED_LABEL, "records": recs}, f)
    print(f"done {len(recs)} worlds {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
