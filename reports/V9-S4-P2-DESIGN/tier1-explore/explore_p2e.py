#!/usr/bin/env python3
"""S4 phase 2 exploration, round E (s4x-p2a worlds; exploration only; phase-1 L-int weights, no training).

Contact-gated L-int: per disk, the L-int prediction if the L-int contact head gives any pair within
MSG_RADIUS a contact probability above GATE_P, otherwise the E-B rule. Free motion is then E-B's,
exactly. Arms (registered noise unless said): E-B, E-P, L-int, L-int-g, L-int+Qcap (round B's
error heads on L-int, learned variance capped at the 99.9th percentile of the training errors),
L-int-g+Qcap (the capped learned variance on gated disks only, registered noise elsewhere).
Also D and HF from the exact truth for L-int-g.

Usage (under the shared lock): <this> N_WORLDS SCRATCH_DIR OUT.json [GATE_P]
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


def gated(net, gate_p, *, q_head=None, q_cap=None, q_reg=(0.01, 0.05), stats=None):
    def step(P, V, pillars):
        pb, vb = Mo.bounce(P, V, pillars)
        if P.shape[1] < 2:
            return (pb, vb) if q_head is None else (pb, vb, np.full_like(P, q_reg[0] ** 2), np.full_like(V, q_reg[1] ** 2))
        pil = mx.array(np.broadcast_to(np.array(pillars, dtype=np.float32), (P.shape[0], L.N_PILLARS, 3)))
        pp, vv = mx.array(P.astype(np.float32)), mx.array(V.astype(np.float32))
        p, v, lg, _ = net(pp, vv, pil)
        d = np.linalg.norm(P[:, :, None] - P[:, None], axis=-1) + np.eye(P.shape[1])[None] * 99
        prob = 1 / (1 + np.exp(-np.array(lg, dtype=np.float64)))
        g = ((prob > gate_p) & (d < L.MSG_RADIUS)).any(-1)[..., None]     # [M, n, 1]
        if stats is not None:
            stats[0] += int(g.sum()); stats[1] += g.size
        out = [np.where(g, np.array(p, dtype=np.float64), pb), np.where(g, np.array(v, dtype=np.float64), vb)]
        if q_head is not None:
            _, _, _, lv = q_head(pp, vv, pil)
            var = np.exp(np.array(lv, dtype=np.float64))
            vp, vvv = np.minimum(var[..., :2], q_cap[0]), np.minimum(var[..., 2:], q_cap[1])
            out += [np.where(g, vp, 0.0) + q_reg[0] ** 2, np.where(g, vvv, 0.0) + q_reg[1] ** 2]
        return tuple(out)
    return step


def main():
    n, sdir, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    gate_p = float(sys.argv[4]) if len(sys.argv) > 4 else 0.5
    mx.set_default_device(mx.cpu)
    raw = {s: L.load("L-int", f"{XB.WDIR}/L-int#{s}.safetensors") for s in XB.SEEDS}
    qs = {s: L.load("L-int-s", f"{sdir}/Q#{s}.safetensors") for s in XB.SEEDS}
    caps = {s: XB.error_cap(raw[s], f"{sdir}/p2b-pool.npz") for s in XB.SEEDS}
    stats = [0, 0]
    arms = {
        "E-B": lambda s: Mo.bounce, "E-P": lambda s: Mo.true_physics,
        "L-int": lambda s: L.as_process_model(raw[s]),
        "L-int-g": lambda s: gated(raw[s], gate_p, stats=stats),
        "L-int+Qcap": lambda s: XB.wrap(raw[s], q_head=qs[s], q_cap=caps[s]),
        "L-int-g+Qcap": lambda s: gated(raw[s], gate_p, q_head=qs[s], q_cap=caps[s]),
    }
    res = {"gate_p": gate_p, "caps": caps, "per_world": [], "dyn": {}}
    dyn = {}
    t0 = time.time()
    for w in range(n):
        ep = W.generate_episode(XA.NS, w, A.MAIN_DISKS)
        events = W.reappearances(ep)
        dets = A.student_detections(ep)
        rec = {"world": w, "events": [[e["k"], e["a"], e["b"], int(e["collision"]), e["gap"]] for e in events], "cells": {}}
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
        for s in XB.SEEDS:
            e = Me.dynamics_errors(ep, gated(raw[s], gate_p))
            d = dyn.setdefault(f"L-int-g#{s}", [0.0, 0, 0.0, 0])
            d[0] += sum(e["coll"]); d[1] += len(e["coll"]); d[2] += sum(e["graze"]); d[3] += len(e["graze"])
        e = Me.dynamics_errors(ep, Mo.bounce)
        d = dyn.setdefault("E-B", [0.0, 0, 0.0, 0])
        d[0] += sum(e["coll"]); d[1] += len(e["coll"])
        res["per_world"].append(rec)
        print(f"world {w} {time.time() - t0:.0f}s", flush=True)
    eb = dyn["E-B"][0] / dyn["E-B"][1]
    res["dyn"] = {k: {"D": 1 - (v[0] / v[1]) / eb, "HF": (v[2] / v[3]) / eb if v[3] else None} for k, v in dyn.items() if k != "E-B"}
    res["gated_share"] = stats[0] / max(stats[1], 1)
    json.dump(res, open(out, "w"))
    print(json.dumps(res["dyn"]), "gated share", res["gated_share"])


if __name__ == "__main__":
    main()
