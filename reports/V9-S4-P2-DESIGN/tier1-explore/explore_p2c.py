#!/usr/bin/env python3
"""S4 phase 2 exploration, round C (s4x-p2a worlds; exploration only).

Where does the learned model's velocity error on free member states come from? On the member
states the filter produces (L-int, registered noise), every PROBE_EVERY-th predict call, members
that no disk interaction changes are split by the distance to the nearest other track in the same
member: near (< MSG_RADIUS, the model exchanges messages) or far; and far members by whether a wall
or pillar is within reach this step (gap < 0.3). Velocity error against the simulator.

Usage (under the shared lock): <this> N_WORLDS SCRATCH_DIR_WITH_R OUT.json
"""
import json
import sys

import mlx.core as mx
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_p2a as XA  # noqa: E402
import explore_p2b as XB  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W


class Split:
    def __init__(self, model):
        self.model, self.calls = model, 0
        self.s = {k: [0.0, 0] for k in ("near", "far_wall", "far_open", "coll")}

    def __call__(self, P, V, pillars):
        out = self.model(P, V, pillars)
        self.calls += 1
        if self.calls % XA.PROBE_EVERY == 0 and P.shape[1] >= 2:
            tp, tv, _ = W.physics(P, V, pillars)
            bp, bv, _ = W.physics(P, V, pillars, disks=False)
            hit = np.linalg.norm(tv - bv, axis=-1) > 1e-6
            err = np.linalg.norm(np.asarray(out[1]) - tv, axis=-1)
            d = np.linalg.norm(P[:, :, None] - P[:, None], axis=-1) + np.eye(P.shape[1])[None] * 99
            near = d.min(-1) < L.MSG_RADIUS
            wall = (np.minimum(P, W.ARENA - P).min(-1) < W.RADIUS + 0.3)
            for cx, cy, cr in pillars:
                wall |= np.linalg.norm(P - np.array([cx, cy]), axis=-1) < cr + W.RADIUS + 0.3
            for k, m in (("coll", hit), ("near", ~hit & near), ("far_wall", ~hit & ~near & wall), ("far_open", ~hit & ~near & ~wall)):
                self.s[k][0] += float(err[m].sum()); self.s[k][1] += int(m.sum())
        return out


def main():
    n, sdir, out = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    mx.set_default_device(mx.cpu)
    arms = {"L-int": {s: L.as_process_model(L.load("L-int", f"{XB.WDIR}/L-int#{s}.safetensors")) for s in XB.SEEDS}}
    R = {}
    for s in XB.SEEDS:
        m = XB.Residual(); m.load_weights(f"{sdir}/R#{s}.safetensors"); mx.eval(m.parameters()); R[s] = XB.wrap(m)
    arms["L-int-r"] = R
    tot = {a: {k: [0.0, 0] for k in ("near", "far_wall", "far_open", "coll")} for a in arms}
    for w in range(n):
        ep = W.generate_episode(XA.NS, w, A.MAIN_DISKS)
        dets = A.student_detections(ep)
        for a, by in arms.items():
            for s, mdl in by.items():
                sp = Split(mdl)
                F.track(dets, ep.pillars, sp, np.random.default_rng(W.derive_seed(XA.NS, "filter", w, s, "q1")))
                for k, (e, c) in sp.s.items():
                    tot[a][k][0] += e; tot[a][k][1] += c
        print("world", w, flush=True)
    res = {a: {k: {"mean_vel_err": e / c if c else None, "n": c} for k, (e, c) in d.items()} for a, d in tot.items()}
    json.dump(res, open(out, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
