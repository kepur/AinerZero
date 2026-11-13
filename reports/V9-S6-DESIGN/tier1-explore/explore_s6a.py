#!/usr/bin/env python3
"""S6 exploration, round A (exploration namespaces s6x-*; exploration only, not a result).

Pool-based self-directed fine-tuning of the phase-1 L-int. A labelled candidate pool is built from
s6x-cand worlds (phase-1 sampling: perturbed states, 20% exact, simulator labels at 1, 5, 10 steps); the
labels stay hidden until an arm selects the sample. Each arm selects K samples, then each seed's
L-int#s is fine-tuned on them, alternating batches with a replay pool (s6x-replay, same sampling) as
the old data. Arms:
  base        no fine-tuning
  replay      fine-tune on replay batches only (same steps): extra training without new data
  random      K samples uniformly
  disagree    the K samples with the largest ensemble disagreement (max over disks of the spread of
              L-int#1-3 next-velocity predictions); no labels read
  oracle      the K samples with the largest true error of the ensemble mean (reads labels; upper bound)
  curriculum  phase-1 hand curriculum: half with a disk contact at step 1 (reads labels), half random
Evaluation on independent s6x-test worlds (exact states): mean next-velocity error per step kind
(collision, graze, wall/pillar, free) and D = 1 - err/err(E-B) on collision disk-steps, per seed.

Usage (MLX; under the shared lock): <this> K STEPS OUT.json
"""
import json
import sys
import time

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

WDIR = "artifacts/v9/s4/phase1/final-final/weights"
SEEDS = (1, 2, 3)
LR = 1e-4
BATCH = 256


def flat_pool(pool):
    """List of (n, index) for every sample, and the per-bucket arrays."""
    return [(n, i) for n, e in sorted(pool.by_n.items()) for i in range(len(e["p"]))]


def subset(pool, picks):
    by = {}
    for n, i in picks:
        by.setdefault(n, []).append(i)
    return L.Pool({n: {k: v[np.array(idx)] for k, v in pool.by_n[n].items()} for n, idx in sorted(by.items())})


def score_pool(pool, nets):
    """Per sample: (disagreement, true error of the ensemble mean), each the max over disks."""
    dis, err = {}, {}
    for n, e in pool.by_n.items():
        p, v, pil = mx.array(e["p"]), mx.array(e["v"]), mx.array(e["pil"])
        preds = []
        for net in nets:
            _, vv, _, _ = net(p, v, pil)
            preds.append(np.array(vv, dtype=np.float64))
        st = np.stack(preds)
        mean = st.mean(0)
        dis[n] = np.linalg.norm(st - mean[None], axis=-1).mean(0).max(-1)
        err[n] = np.linalg.norm(mean - e["v1"], axis=-1).max(-1)
    return dis, err


def finetune(seed, sel_pool, replay_pool, steps, *, replay_only=False):
    mx.random.seed(seed)
    model = L.load("L-int", f"{WDIR}/L-int#{seed}.safetensors")
    opt = optim.Adam(learning_rate=LR)
    vg = nn.value_and_grad(model, L.rollout_loss)
    rng = np.random.default_rng(seed)
    gen_r = L.batches(replay_pool, steps, BATCH, rng, coll_share=0.0)
    gen_s = None if replay_only else L.batches(sel_pool, steps, BATCH, np.random.default_rng(seed + 100), coll_share=0.0)
    for t in range(steps):
        src, gen = (replay_pool, gen_r) if (replay_only or t % 2 == 1) else (sel_pool, gen_s)
        n, idx = next(gen)
        b = {k: mx.array(v[idx]) for k, v in src.by_n[n].items()}
        loss, grads = vg(model, b)
        grads, _ = optim.clip_grad_norm(grads, max_norm=L.CLIP)
        opt.update(model, grads)
        mx.eval(model.parameters(), opt.state)
    return model


def classify(ep, t):
    s = ep.steps[t]
    disk = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    wallp = {i for k, i, j in s.contacts if k in ("wall", "pillar")}
    nxt = ep.steps[t + 1].positions
    d = np.linalg.norm(nxt[:, None] - nxt[None], axis=-1) + np.eye(ep.n_disks) * 99
    return np.array([0 if i in disk else (1 if d[i].min() < 2 * W.RADIUS + 0.3 else (2 if i in wallp else 3)) for i in range(ep.n_disks)])


def evaluate(models, test_eps):
    """Per model: mean velocity error per kind, and D on collision disk-steps."""
    out = {}
    pre = []
    for ep in test_eps:
        T = len(ep.steps) - 1
        P = np.stack([s.positions for s in ep.steps[:T]]).astype(np.float32)
        V = np.stack([s.velocities for s in ep.steps[:T]]).astype(np.float32)
        tgt = np.stack([s.velocities for s in ep.steps[1:T + 1]])
        kinds = np.stack([classify(ep, t) for t in range(T)])
        _, vb = Mo.bounce(P.astype(np.float64), V.astype(np.float64), ep.pillars)
        pil = mx.array(np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, L.N_PILLARS, 3)))
        pre.append((P, V, tgt, kinds, np.linalg.norm(vb - tgt, axis=-1), pil))
    for name, m in models.items():
        sums = np.zeros(4); cnt = np.zeros(4); eb_coll = 0.0
        for P, V, tgt, kinds, eb_err, pil in pre:
            _, v, _, _ = m(mx.array(P), mx.array(V), pil)
            e = np.linalg.norm(np.array(v, dtype=np.float64) - tgt, axis=-1)
            for k in range(4):
                sums[k] += e[kinds == k].sum(); cnt[k] += (kinds == k).sum()
            eb_coll += eb_err[kinds == 0].sum()
        mean = sums / cnt
        out[name] = {"collision": mean[0], "graze": mean[1], "wall_pillar": mean[2], "free": mean[3],
                     "all": sums.sum() / cnt.sum(), "D": 1 - sums[0] / eb_coll}
    return out


def main():
    K, steps, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    t0 = time.time()
    cand_eps = A.train_worlds("s6x-cand", 120)
    rep_eps = A.train_worlds("s6x-replay", 120)
    test_eps = [W.generate_episode("s6x-test", w, 6) for w in range(20)] + [W.generate_episode("s6x-test", 1000 + w, 10) for w in range(10)]
    cand = L.make_pool(cand_eps, 60_000, np.random.default_rng(1), W.physics)
    replay = L.make_pool(rep_eps, 60_000, np.random.default_rng(2), W.physics)
    print(f"pools {time.time() - t0:.0f}s", flush=True)
    mx.set_default_device(mx.cpu)
    base_nets = [L.load("L-int", f"{WDIR}/L-int#{s}.safetensors") for s in SEEDS]
    dis, err = score_pool(cand, base_nets)
    allp = flat_pool(cand)
    dvec = np.array([dis[n][i] for n, i in allp]); evec = np.array([err[n][i] for n, i in allp])
    rng = np.random.default_rng(7)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    half = K // 2
    curr = list(rng.choice(np.flatnonzero(coll), half, replace=False)) + list(rng.choice(np.flatnonzero(~coll), K - half, replace=False))
    picks = {"random": rng.choice(len(allp), K, replace=False), "disagree": np.argsort(-dvec)[:K], "oracle": np.argsort(-evec)[:K],
             "curriculum": np.array(curr)}
    sel_info = {a: {"mean_true_err": float(evec[p].mean()), "disk_contact_share": float(coll[p].mean()),
                    "overlap_with_oracle": float(len(set(p.tolist()) & set(picks["oracle"].tolist())) / K)} for a, p in picks.items()}
    print("selection", json.dumps(sel_info), flush=True)
    print(f"spearman(disagree, true err) on pool: {np.corrcoef(np.argsort(np.argsort(dvec)), np.argsort(np.argsort(evec)))[0, 1]:.3f}", flush=True)
    mx.set_default_device(mx.gpu)
    results = {"K": K, "steps": steps, "lr": LR, "selection": sel_info, "eval": {}}
    models = {}
    for s in SEEDS:
        models[f"base#{s}"] = base_nets[s - 1]
        models[f"replay#{s}"] = finetune(s, None, replay, steps, replay_only=True)
        for arm, p in picks.items():
            models[f"{arm}#{s}"] = finetune(s, subset(cand, [allp[i] for i in p]), replay, steps)
        print(f"seed {s} trained {time.time() - t0:.0f}s", flush=True)
    mx.set_default_device(mx.cpu)
    ev = evaluate(models, test_eps)
    results["eval"] = ev
    arms = ["base", "replay", *picks]
    summ = {a: {k: float(np.mean([ev[f"{a}#{s}"][k] for s in SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")} for a in arms}
    results["summary"] = summ
    json.dump(results, open(out, "w"), indent=1, default=float)
    print(f"\n{'arm':11} {'coll':>7} {'graze':>7} {'wall':>7} {'free':>7} {'all':>7} {'D':>6}")
    for a in arms:
        r = summ[a]
        print(f"{a:11} {r['collision']:7.4f} {r['graze']:7.4f} {r['wall_pillar']:7.4f} {r['free']:7.4f} {r['all']:7.4f} {r['D']:6.3f}")
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
