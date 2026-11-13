#!/usr/bin/env python3
"""S6 inventory (read-only, exploration namespace s6x-inv): can the phase-1 learned dynamics find their own
learning gaps? On exact states of fresh S4 worlds, per disk and step: velocity error of an ensemble's mean
against the simulator, and the ensemble's spread (mean distance of members to the mean). Ensembles:
L-int#1-3, L-int-c#1-3, both (6), and the 1/8-data L-int-e8#1-3. Disk-steps are classed collision (disk
contact this step), graze, wall/pillar contact, free. Reports rank correlation of spread and error, AUC of
spread for collision steps and for the top 5% errors, and the share of squared error in the top 5% spread.
Also base rates of collisions in random sandbox placements.

Usage (MLX on CPU, under the shared lock): <this> N6 N10 OUT.json
"""
import json
import sys

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W

NS = "s6x-inv"
WDIR = "artifacts/v9/s4/phase1/final-final/weights"
ENSEMBLES = {"L-int": [("L-int", s) for s in (1, 2, 3)], "L-int-c": [("L-int-c", s) for s in (1, 2, 3)],
             "both6": [(a, s) for a in ("L-int", "L-int-c") for s in (1, 2, 3)], "L-int-e8": [("L-int-e8", s) for s in (1, 2, 3)]}


def rank(x):
    r = np.empty(len(x)); r[np.argsort(x, kind="stable")] = np.arange(len(x)); return r


def auc(score, label):
    label = label.astype(bool)
    if label.all() or not label.any():
        return None
    r = rank(score) + 1
    return float((r[label].sum() - label.sum() * (label.sum() + 1) / 2) / (label.sum() * (~label).sum()))


def classify(ep, t):
    s = ep.steps[t]
    kinds = np.full(ep.n_disks, 3)                                   # 3 free
    disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
    nxt = ep.steps[t + 1].positions
    d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(ep.n_disks) * 99
    for i in range(ep.n_disks):
        kinds[i] = 0 if i in disk else (1 if d[i].min() < 2 * W.RADIUS + 0.3 else (2 if i in wallp else 3))
    return kinds


def main():
    n6, n10, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    mx.set_default_device(mx.cpu)
    base = lambda a: a[:-3] if a.endswith("-e8") else a
    nets = {(a, s): L.load(base(a), f"{WDIR}/{a}#{s}.safetensors") for e in ENSEMBLES.values() for a, s in e}
    rows = {k: {"err": [], "spread": [], "kind": [], "n": []} for k in ENSEMBLES}
    for n_disks, nw, off in ((6, n6, 0), (10, n10, 1000)):
        for w in range(nw):
            ep = W.generate_episode(NS, off + w, n_disks)
            T = len(ep.steps) - 1
            P = np.stack([s.positions for s in ep.steps[:T]]).astype(np.float32)
            V = np.stack([s.velocities for s in ep.steps[:T]]).astype(np.float32)
            target = np.stack([s.velocities for s in ep.steps[1:T + 1]])
            pil = mx.array(np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, L.N_PILLARS, 3)))
            preds = {}
            for key, net in nets.items():
                _, v, _, _ = net(mx.array(P), mx.array(V), pil)
                preds[key] = np.array(v, dtype=np.float64)
            kinds = np.stack([classify(ep, t) for t in range(T)])
            for name, members in ENSEMBLES.items():
                stack = np.stack([preds[m] for m in members])              # [M, T, n, 2]
                mean = stack.mean(0)
                spread = np.linalg.norm(stack - mean[None], axis=-1).mean(0)
                err = np.linalg.norm(mean - target, axis=-1)
                rows[name]["err"].append(err.ravel()); rows[name]["spread"].append(spread.ravel())
                rows[name]["kind"].append(kinds.ravel()); rows[name]["n"].append(np.full(err.size, n_disks))
    res = {"namespace": NS, "worlds": {"6": n6, "10": n10}, "ensembles": {}}
    for name, r in rows.items():
        err, spread, kind, nd = (np.concatenate(r[k]) for k in ("err", "spread", "kind", "n"))
        top5 = err >= np.quantile(err, 0.95)
        order = np.argsort(-spread)
        k5 = int(0.05 * len(err))
        e2 = err ** 2
        out_k = {}
        for kname, kv in (("collision", 0), ("graze", 1), ("wall_pillar", 2), ("free", 3)):
            m = kind == kv
            out_k[kname] = {"n": int(m.sum()), "mean_err": float(err[m].mean()), "mean_spread": float(spread[m].mean()),
                            "share_sq_error": float(e2[m].sum() / e2.sum()),
                            "share_in_top5_spread": float(np.isin(np.flatnonzero(m), order[:k5]).mean())}
        res["ensembles"][name] = {
            "n_disk_steps": int(len(err)),
            "spearman_spread_err": float(np.corrcoef(rank(spread), rank(err))[0, 1]),
            "auc_spread_collision": auc(spread, kind == 0),
            "auc_spread_top5_error": auc(spread, top5),
            "share_sq_error_in_top5_spread": float(e2[order[:k5]].sum() / e2.sum()),
            "share_sq_error_on_collision_steps": float(e2[kind == 0].sum() / e2.sum()),
            "by_kind": out_k,
            "by_disks": {str(n): {"spearman": float(np.corrcoef(rank(spread[nd == n]), rank(err[nd == n]))[0, 1]),
                                  "auc_collision": auc(spread[nd == n], kind[nd == n] == 0)} for n in (6, 10)},
        }
    # base rates: collision share of one-step transitions from random sandbox placements
    rng = np.random.default_rng(0)
    pil_ep = W.generate_episode(NS, 0, 6).pillars
    hits = tot = 0
    for _ in range(2000):
        p, v = W._place_disks(rng, 6, pil_ep)
        _, _, c = W.physics(p[None], v[None], pil_ep, log=True)
        hits += len({i for k, i, j in c if k == "disk"} | {j for k, i, j in c if k == "disk"}); tot += 6
    res["sandbox_random_placement_collision_disk_share"] = hits / tot
    json.dump(res, open(out, "w"), indent=1)
    for name, e in res["ensembles"].items():
        print(name, {k: (round(v, 3) if isinstance(v, float) else v) for k, v in e.items() if k not in ("by_kind", "by_disks")})
        print("   ", {k: (v["n"], round(v["mean_err"], 4), round(v["mean_spread"], 4), round(v["share_sq_error"], 3), round(v["share_in_top5_spread"], 3)) for k, v in e["by_kind"].items()})
    print("sandbox collision share", res["sandbox_random_placement_collision_disk_share"])


if __name__ == "__main__":
    main()
