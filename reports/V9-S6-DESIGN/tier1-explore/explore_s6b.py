#!/usr/bin/env python3
"""S6 exploration, round B (s6x-*; exploration only). Two questions after round A:
  1. Is the wall/pillar gap of the phase-1 L-int fixable by data? Arm "wallcur": half of each
     fine-tuning batch from samples whose step 1 has a wall or pillar reflection (labels read), half
     random from the same exact-state pool.
  2. Does selection by disagreement help when the candidates are exact states (sandbox placements of
     real configurations) rather than phase-1 perturbed states? Arms "random-x", "disagree-x" (max over
     disks), "disagree-mean-x" (mean over disks), "oracle-x" (true error; reads labels).
All fine-tune each seed's L-int#s for STEPS steps, alternating with the phase-1-style replay pool, and
are evaluated as in round A (explore_s6a.evaluate) on the same s6x-test worlds.

Usage (MLX; under the shared lock): <this> K STEPS OUT.json
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_s6a as XA  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W


def wall_flag(pool):
    out = {}
    for n, e in pool.by_n.items():
        p, v = e["p"].astype(np.float64), e["v"].astype(np.float64)
        flags = np.zeros(len(p), bool)
        for i in range(len(p)):
            pillars = tuple(map(tuple, e["pil"][i]))
            _, vb = Mo.bounce(p[i:i + 1], v[i:i + 1], pillars)
            flags[i] = (np.abs(vb[0] - v[i]) > 1e-6).any()
        out[n] = flags
    return out


def main():
    K, steps, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    t0 = time.time()
    cand_eps = A.train_worlds("s6x-cand", 120)
    rep_eps = A.train_worlds("s6x-replay", 120)
    test_eps = [W.generate_episode("s6x-test", w, 6) for w in range(20)] + [W.generate_episode("s6x-test", 1000 + w, 10) for w in range(10)]
    cand = L.make_pool(cand_eps, 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    replay = L.make_pool(rep_eps, 60_000, np.random.default_rng(2), W.physics)
    mx.set_default_device(mx.cpu)
    base_nets = [L.load("L-int", f"{XA.WDIR}/L-int#{s}.safetensors") for s in XA.SEEDS]
    dis, err = XA.score_pool(cand, base_nets)
    # mean-over-disks disagreement
    dmean = {}
    for n, e in cand.by_n.items():
        p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
        st = np.stack([np.array(net(p, v, pil)[1], dtype=np.float64) for net in base_nets])
        dmean[n] = np.linalg.norm(st - st.mean(0)[None], axis=-1).mean(0).mean(-1)
    wf = wall_flag(cand)
    allp = XA.flat_pool(cand)
    dvec = np.array([dis[n][i] for n, i in allp]); evec = np.array([err[n][i] for n, i in allp])
    mvec = np.array([dmean[n][i] for n, i in allp]); wvec = np.array([wf[n][i] for n, i in allp])
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    rng = np.random.default_rng(7)
    half = K // 2
    wallcur = list(rng.choice(np.flatnonzero(wvec), half, replace=False)) + list(rng.choice(np.flatnonzero(~wvec), K - half, replace=False))
    picks = {"random-x": rng.choice(len(allp), K, replace=False), "disagree-x": np.argsort(-dvec)[:K],
             "disagree-mean-x": np.argsort(-mvec)[:K], "oracle-x": np.argsort(-evec)[:K], "wallcur": np.array(wallcur)}
    sel = {a: {"mean_true_err": float(evec[p].mean()), "disk_contact_share": float(coll[p].mean()), "wall_share": float(wvec[p].mean())} for a, p in picks.items()}
    print(f"pools+scores {time.time() - t0:.0f}s; pool wall share {wvec.mean():.3f}, disk-contact share {coll.mean():.3f}", flush=True)
    print("selection", json.dumps(sel), flush=True)
    mx.set_default_device(mx.gpu)
    models = {}
    for s in XA.SEEDS:
        models[f"base#{s}"] = base_nets[s - 1]
        for arm, p in picks.items():
            models[f"{arm}#{s}"] = XA.finetune(s, XA.subset(cand, [allp[i] for i in p]), replay, steps)
        print(f"seed {s} trained {time.time() - t0:.0f}s", flush=True)
    mx.set_default_device(mx.cpu)
    ev = XA.evaluate(models, test_eps)
    arms = ["base", *picks]
    summ = {a: {k: float(np.mean([ev[f"{a}#{s}"][k] for s in XA.SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")} for a in arms}
    json.dump({"K": K, "steps": steps, "selection": sel, "eval": ev, "summary": summ}, open(out, "w"), indent=1, default=float)
    print(f"\n{'arm':16} {'coll':>7} {'graze':>7} {'wall':>7} {'free':>7} {'all':>7} {'D':>6}")
    for a in arms:
        r = summ[a]
        print(f"{a:16} {r['collision']:7.4f} {r['graze']:7.4f} {r['wall_pillar']:7.4f} {r['free']:7.4f} {r['all']:7.4f} {r['D']:6.3f}")
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
