#!/usr/bin/env python3
"""S4 phase 2 exploration, round F (s4x-p2a; exploration only; phase-1 weights, no training).

Contact gating, its sensitivity and its controls. Per disk, a learned model's prediction if the gate
fires, otherwise the E-B rule. Gates: the L-int contact head (any pair within MSG_RADIUS with
probability above p; p = 0.3, 0.5, 0.7), or the geometric rule of phase 1's contact baseline on the
member state (a pair approaching on straight lines that touches within one step). Arms:
E-B, E-P, L-int-g@0.3/0.5/0.7 (head gate, L-int prediction), L-int-geo (geometric gate, L-int
prediction), L-ind-geo (geometric gate, L-ind prediction: a model without interaction; negative
control). Main worlds 0..N-1 (6 disks) and extrapolation worlds 1000.. (10 disks).

Usage (under the shared lock): <this> N_MAIN N_EXTRAP OUT.json
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_p2a as XA  # noqa: E402
import explore_p2b as XB  # noqa: E402
import explore_p2d as XD  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W


def geo_gate(P, V):
    """[M, n] bool: some other disk approaches on straight lines and touches within one step (or overlaps and approaches)."""
    d = P[:, None, :, :] - P[:, :, None, :]
    u = V[:, None, :, :] - V[:, :, None, :]
    a = (u * u).sum(-1)
    b = 2 * (d * u).sum(-1)
    c = (d * d).sum(-1) - (2 * W.RADIUS) ** 2
    disc = b * b - 4 * a * c
    with np.errstate(invalid="ignore", divide="ignore"):
        tau = (-b - np.sqrt(np.maximum(disc, 0))) / (2 * np.where(a > 0, a, 1))
    hit = ((c <= 0) & (b < 0)) | ((a > 0) & (disc >= 0) & (b < 0) & (tau >= 0) & (tau < W.DT))
    n = P.shape[1]
    hit &= ~np.eye(n, dtype=bool)[None]
    return hit.any(-1)


def gated(net, gate, stats):
    def step(P, V, pillars):
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            return pb, vb
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        p, v, lg, _ = net(mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32)), pil)
        if gate == "geo":
            g = geo_gate(P, V)
        else:
            d = np.linalg.norm(P[:, :, None] - P[:, None], axis=-1) + np.eye(P.shape[1])[None] * 99
            prob = 1 / (1 + np.exp(-np.array(lg, dtype=np.float64)))
            g = ((prob > gate) & (d < L.MSG_RADIUS)).any(-1)
        stats[0] += int(g.sum()); stats[1] += g.size
        g = g[..., None]
        return np.where(g, np.array(p, dtype=np.float64), pb), np.where(g, np.array(v, dtype=np.float64), vb)
    return step


def main():
    n_main, n_ext, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    mx.set_default_device(mx.cpu)
    lint = {s: L.load("L-int", f"{XB.WDIR}/L-int#{s}.safetensors") for s in XB.SEEDS}
    lind = {s: L.load("L-ind", f"{XB.WDIR}/L-ind#{s}.safetensors") for s in XB.SEEDS}
    stats = {}
    specs = {"L-int-g@0.3": (lint, 0.3), "L-int-g@0.5": (lint, 0.5), "L-int-g@0.7": (lint, 0.7),
             "L-int-geo": (lint, "geo"), "L-ind-geo": (lind, "geo")}
    arms = {"E-B": lambda s: Mo.bounce, "E-P": lambda s: Mo.true_physics}
    for name, (nets, g) in specs.items():
        stats[name] = [0, 0]
        arms[name] = (lambda nets, g, st: (lambda s: gated(nets[s], g, st)))(nets, g, stats[name])
    res = {"per_world": [], "dyn": {}}
    dyn = {}
    t0 = time.time()
    worlds = [("main", w, A.MAIN_DISKS) for w in range(n_main)] + [("extrap", A.EXTRAP_OFFSET + w, A.EXTRAP_DISKS) for w in range(n_ext)]
    for kind, w, nd in worlds:
        ep = W.generate_episode(XA.NS, w, nd)
        events = W.reappearances(ep)
        dets = A.student_detections(ep)
        rec = {"kind": kind, "world": w, "events": [[e["k"], e["a"], e["b"], int(e["collision"]), e["gap"]] for e in events], "cells": {}}
        for name, mk in arms.items():
            for s in XB.SEEDS:
                snap, cal = XD.Snap([e["b"] for e in events]), XA.Calib(ep)

                def hook(t, P, V, assign, last, snap=snap, cal=cal):
                    snap(t, P, V, assign, last); cal(t, P, V, assign, last)
                rng = np.random.default_rng(W.derive_seed(XA.NS, "filter", w, s, "q1"))
                got = XB.safe_track(dets, ep.pillars, mk(s), rng, F.FilterConfig(), hook)
                if got is None:
                    rec["cells"][f"{name}#{s}"] = {"diverged": True}
                    continue
                ids, nt = got
                rows = np.array(cal.rows, dtype=np.float64).reshape(-1, 5)
                one = {k: [int((rows[:, 0] == kk).sum()) if kk is not None else len(rows),
                           float(rows[(rows[:, 0] == kk) if kk is not None else slice(None), 1].sum())] for k, kk in (("all", None), ("collision", 0), ("free", 2))}
                rec["cells"][f"{name}#{s}"] = {"correct": [x["correct"] for x in Me.reid(ep, ids, events)], "n_tracks": nt,
                                               "reappear": XD.reappear_rows(ep, ids, events, snap.snaps), "one_step": one}
        for name, (nets, g) in specs.items():
            for s in XB.SEEDS:
                e = Me.dynamics_errors(ep, gated(nets[s], g, [0, 0]))
                d = dyn.setdefault(f"{kind}:{name}", [0.0, 0, 0.0, 0])
                d[0] += sum(e["coll"]) / 3; d[1] += len(e["coll"]) / 3; d[2] += sum(e["graze"]) / 3; d[3] += len(e["graze"]) / 3
        e = Me.dynamics_errors(ep, Mo.bounce)
        d = dyn.setdefault(f"{kind}:E-B", [0.0, 0, 0.0, 0])
        d[0] += sum(e["coll"]); d[1] += len(e["coll"])
        res["per_world"].append(rec)
        print(f"{kind} {w} {time.time() - t0:.0f}s", flush=True)
    for k, v in dyn.items():
        kind, name = k.split(":")
        if name == "E-B":
            continue
        eb = dyn[f"{kind}:E-B"][0] / dyn[f"{kind}:E-B"][1]
        res["dyn"][k] = {"D": 1 - (v[0] / v[1]) / eb, "HF": (v[2] / v[3]) / eb}
    res["gated_share"] = {k: v[0] / max(v[1], 1) for k, v in stats.items()}
    json.dump(res, open(out, "w"))
    print(json.dumps(res["dyn"], indent=1), json.dumps(res["gated_share"]))


if __name__ == "__main__":
    main()
