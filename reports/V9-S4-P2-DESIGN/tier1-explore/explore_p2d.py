#!/usr/bin/env python3
"""S4 phase 2 exploration, round D (s4x-p2a worlds; exploration only).

Calibration where it matters for re-identification: at every reappearance event (k seen at a,
hidden a+1..b-1, seen at b), the ensemble predicted at b (before the update) of the track that held
k at a; NLL and whether the true position at b lies in its 90% region; split by collision events and
by gap length. Also one-step coverage of visible tracks by step kind (as round A). Arms: E-B, E-P,
L-int, L-int-r, L-int-r+Q (process noise = registered + learned error variance), and process-noise
scales for L-int-r.

Usage (under the shared lock): <this> N_WORLDS SCRATCH_DIR OUT.json
"""
import json
import sys
import time
from dataclasses import replace

import mlx.core as mx
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_p2a as XA  # noqa: E402
import explore_p2b as XB  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

GAP_BINS = (0, 10, 25, 50, 10_000)


class Snap:
    """Keeps the predicted ensemble mean and covariance of every track at the steps in ``want``."""

    def __init__(self, want):
        self.want, self.snaps = set(want), {}

    def __call__(self, t, P, V, assign, last):
        if t in self.want and P.shape[1]:
            mu = P.mean(0)
            cov = np.einsum("mki,mkj->kij", P - mu, P - mu) / (P.shape[0] - 1) + np.eye(2)[None] * 1e-9
            self.snaps[t] = (mu, cov)


def reappear_rows(ep, ids, events, snaps):
    at = [dict(zip(s.truth_ids.tolist(), np.asarray(i).tolist())) for s, i in zip(ep.steps, ids)]
    rows = []
    for e in events:
        trk = at[e["a"]][e["k"]]
        mu, cov = snaps[e["b"]]
        if trk >= len(mu):
            continue
        d = ep.steps[e["b"]].positions[e["k"]] - mu[trk]
        c = cov[trk]
        m2 = float(d @ np.linalg.solve(c, d))
        nll = float(0.5 * (np.log((2 * np.pi) ** 2 * np.linalg.det(c)) + m2))
        rows.append((int(e["collision"]), int(e["gap"]), bool(m2 <= A.CHI2_2_90), nll, float(np.sqrt(d @ d)), float(np.sqrt(np.trace(c)))))
    return rows


def main():
    n, sdir, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    mx.set_default_device(mx.cpu)
    lint = {s: L.as_process_model(L.load("L-int", f"{XB.WDIR}/L-int#{s}.safetensors")) for s in XB.SEEDS}
    R, Q = {}, {}
    for s in XB.SEEDS:
        m = XB.Residual(); m.load_weights(f"{sdir}/R#{s}.safetensors"); mx.eval(m.parameters()); R[s] = m
    import os
    if all(os.path.exists(f"{sdir}/QR#{s}.safetensors") for s in XB.SEEDS):
        for s in XB.SEEDS:
            q = XB.ResidualS(); q.load_weights(f"{sdir}/QR#{s}.safetensors"); mx.eval(q.parameters()); Q[s] = q
    cells = [("E-B", s, 1.0, lambda s: Mo.bounce) for s in XB.SEEDS] + [("E-P", s, 1.0, lambda s: Mo.true_physics) for s in XB.SEEDS]
    cells += [("L-int", s, 1.0, lambda s: lint[s]) for s in XB.SEEDS]
    for sc in (1.0, 1.5, 2.0):
        cells += [(f"L-int-r@x{sc:g}", s, sc, lambda s: XB.wrap(R[s])) for s in XB.SEEDS]
    if Q:
        caps = {s: XB.error_cap(R[s], f"{sdir}/poolR#{s}.npz") for s in XB.SEEDS}
        print("caps", caps, flush=True)
        res_caps = caps
        cells += [("L-int-r+Q", s, 1.0, lambda s: XB.wrap(R[s], q_head=Q[s])) for s in XB.SEEDS]
        cells += [("L-int-r+Qcap", s, 1.0, lambda s: XB.wrap(R[s], q_head=Q[s], q_cap=caps[s])) for s in XB.SEEDS]
    res = {"per_world": []}
    t0 = time.time()
    for w in range(n):
        ep = W.generate_episode(XA.NS, w, A.MAIN_DISKS)
        events = W.reappearances(ep)
        dets = A.student_detections(ep)
        rec = {"world": w, "events": [[e["k"], e["a"], e["b"], int(e["collision"]), e["gap"]] for e in events], "cells": {}}
        for name, s, sc, mk in cells:
            snap, cal = Snap([e["b"] for e in events]), XA.Calib(ep)

            def hook(t, P, V, assign, last, snap=snap, cal=cal):
                snap(t, P, V, assign, last); cal(t, P, V, assign, last)
            cfg = replace(F.FilterConfig(), q_pos=0.01 * sc, q_vel=0.05 * sc)
            rng = np.random.default_rng(W.derive_seed(XA.NS, "filter", w, s, "q1" if sc == 1.0 else f"x{sc:g}"))
            got = XB.safe_track(dets, ep.pillars, mk(s), rng, cfg, hook)
            if got is None:
                rec["cells"][f"{name}#{s}"] = {"diverged": True}
                continue
            ids, nt = got
            rows = np.array(cal.rows, dtype=np.float64).reshape(-1, 5)
            one = {k: [int((rows[:, 0] == kk).sum()) if kk is not None else len(rows),
                       float(rows[(rows[:, 0] == kk) if kk is not None else slice(None), 1].sum())] for k, kk in (("all", None), ("collision", 0), ("free", 2))}
            rec["cells"][f"{name}#{s}"] = {"correct": [x["correct"] for x in Me.reid(ep, ids, events)], "n_tracks": nt,
                                           "reappear": reappear_rows(ep, ids, events, snap.snaps), "one_step": one}
        res["per_world"].append(rec)
        print(f"world {w} {time.time() - t0:.0f}s", flush=True)
    json.dump(res, open(out, "w"))


if __name__ == "__main__":
    main()
