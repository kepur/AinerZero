#!/usr/bin/env python3
"""S6 r0 non-author review, item 2: can zero-knowledge proxy rules pass GS/GK?

Exactly round C's framework (explore_s6c.py: same candidate pool, seeds, first random round, training,
schedule and evaluation), with extra selection rules that read only the candidate state (p, v) and use
no learner and no simulator label:
  maxspeed   each later round the PER candidates with the largest max-over-disks speed |v|
  mindist    each later round the PER candidates with the smallest min-over-pairs centre distance
             (no approach test, no velocity)
The round-C arms can be rerun as well (random, disagree, truthcur), coded as in explore_s6c.py, so
that their rounds can be compared with run-s6c.log and per-world sums are available for the bootstrap
check of item 3.

Evaluation reproduces explore_s6a.evaluate's arithmetic (sequential accumulation over worlds in the same
order), and in addition keeps per-world, per-network sums so that the C-style combined test (20 six-disk
+ 10 ten-disk worlds), the F-style main6 / extrap10 splits and bootstraps can all be computed from them.

Usage (MLX; under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json CAND_NS TEST_NS ARMS
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/tier1-explore")
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import gated as G  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import models as Mo  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

KINDS = ("collision", "graze", "wall_pillar", "free")


def states_only(pool):
    """The only thing a proxy rule is given: per bucket, copies of the candidate positions and velocities."""
    return {n: {"p": e["p"].copy(), "v": e["v"].copy()} for n, e in pool.by_n.items()}


def proxy_scores(states, rule):
    """Per bucket a score where LARGER means pick first. Reads p, v only."""
    out = {}
    for n, e in states.items():
        p, v = e["p"].astype(np.float64), e["v"].astype(np.float64)
        if rule == "maxspeed":
            out[n] = np.linalg.norm(v, axis=-1).max(-1)
        elif rule == "mindist":
            d = np.linalg.norm(p[:, :, None] - p[:, None], axis=-1) + np.eye(p.shape[1])[None] * 1e9
            out[n] = -d.min((1, 2))
        else:
            raise ValueError(rule)
    return out


def prepare_tests(test_eps):
    pre = []
    for ep in test_eps:
        T = len(ep.steps) - 1
        P = np.stack([s.positions for s in ep.steps[:T]]).astype(np.float32)
        V = np.stack([s.velocities for s in ep.steps[:T]]).astype(np.float32)
        tgt = np.stack([s.velocities for s in ep.steps[1:T + 1]])
        kinds = np.stack([XA.classify(ep, t) for t in range(T)])
        _, vb = Mo.bounce(P.astype(np.float64), V.astype(np.float64), ep.pillars)
        pil = mx.array(np.broadcast_to(np.array(ep.pillars, dtype=np.float32), (T, L.N_PILLARS, 3)))
        pre.append((P, V, tgt, kinds, np.linalg.norm(vb - tgt, axis=-1), pil))
    return pre


def per_world(model, pre):
    """Per world: sums[4], counts[4], E-B collision sum (as explore_s6a.evaluate, kept apart per world)."""
    rows = []
    for P, V, tgt, kinds, eb_err, pil in pre:
        _, v, _, _ = model(mx.array(P), mx.array(V), pil)
        e = np.linalg.norm(np.array(v, dtype=np.float64) - tgt, axis=-1)
        rows.append({"sums": [float(e[kinds == k].sum()) for k in range(4)],
                     "cnt": [int((kinds == k).sum()) for k in range(4)],
                     "eb_coll": float(eb_err[kinds == 0].sum())})
    return rows


def summarize(rows, idx):
    """explore_s6a.evaluate's arithmetic over the worlds idx, accumulated in the same order."""
    sums = np.zeros(4); cnt = np.zeros(4); eb = 0.0
    for w in idx:
        r = rows[w]
        for k in range(4):
            sums[k] += r["sums"][k]; cnt[k] += r["cnt"][k]
        eb += r["eb_coll"]
    mean = sums / cnt
    return {**{KINDS[k]: float(mean[k]) for k in range(4)}, "all": float(sums.sum() / cnt.sum()), "D": float(1 - sums[0] / eb)}


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns, test_ns, arms = sys.argv[5], sys.argv[6], sys.argv[7].split(",")
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    test_eps = [W.generate_episode(test_ns, w, 6) for w in range(20)] + [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]
    pre = prepare_tests(test_eps)
    splits = {"C_all30": list(range(30)), "main6": list(range(20)), "extrap10": list(range(20, 30))}
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])        # reporting only
    gvec = np.concatenate([G.geo_gate(cand.by_n[n]["p"].astype(np.float64), cand.by_n[n]["v"].astype(np.float64)).any(-1)
                           for n in sorted(cand.by_n)])                                 # reporting only
    states = states_only(cand)
    print(f"pool {time.time() - t0:.0f}s, disk-contact share {coll.mean():.3f}, geo share {gvec.mean():.4f}", flush=True)
    res = {"per": per, "rounds": rounds, "steps_per_round": spr, "namespaces": {"candidates": cand_ns, "test": test_ns},
           "seeds": list(XA.SEEDS), "splits": splits, "arms": {}}
    for arm in arms:
        t_arm = time.time()
        mx.set_default_device(mx.gpu)
        learners = [XC.Learner(s) for s in XA.SEEDS]
        rng = np.random.default_rng(100)
        chosen = list(rng.choice(len(allp), per, replace=False))
        rec = {"rounds": [], "chosen": None}
        for r in range(rounds):
            pool = XA.subset(cand, [allp[i] for i in chosen])
            for lr_ in learners:
                lr_.train(pool, spr, 0.5 if arm == "truthcur" else 0.0)
            mx.set_default_device(mx.cpu)
            pw = {str(s): per_world(l.model, pre) for s, l in zip(XA.SEEDS, learners)}
            row = {"n_labels": len(chosen), "disk_contact_share": float(coll[chosen].mean()), "geo_share": float(gvec[chosen].mean()),
                   "per_world": pw}
            for sname, idx in splits.items():
                per_seed = {s: summarize(pw[s], idx) for s in pw}
                row[sname] = {k: float(np.mean([per_seed[s][k] for s in pw])) for k in (*KINDS, "all", "D")}
                row[sname]["D_per_seed"] = [per_seed[s]["D"] for s in pw]
            rec["rounds"].append(row)
            c, m6, x10 = row["C_all30"], row["main6"], row["extrap10"]
            print(f"{arm:9} round {r} n={len(chosen):6d} contact={row['disk_contact_share']:.3f} geo={row['geo_share']:.3f} "
                  f"D={c['D']:.3f} coll={c['collision']:.4f} wall={c['wall_pillar']:.4f} free={c['free']:.4f} all={c['all']:.4f} "
                  f"| main6 D={m6['D']:.3f} {['%.3f' % d for d in m6['D_per_seed']]} | extrap10 D={x10['D']:.3f}  {time.time() - t0:.0f}s", flush=True)
            if r == rounds - 1:
                break
            rest = np.setdiff1d(np.arange(len(allp)), chosen)
            if arm in ("random", "truthcur"):
                new = rng.choice(rest, per, replace=False)
            elif arm == "disagree":
                dis, _ = XA.score_pool(cand, [l.model for l in learners])
                score = np.array([dis[n][i] for n, i in allp])
                new = rest[np.argsort(-score[rest])[:per]]
            elif arm in ("maxspeed", "mindist"):
                sc = proxy_scores(states, arm)
                score = np.array([sc[n][i] for n, i in allp])
                new = rest[np.argsort(-score[rest], kind="stable")[:per]]
            else:
                raise ValueError(arm)
            chosen += list(new)
            mx.set_default_device(mx.gpu)
        rec["chosen"] = [int(i) for i in chosen]
        rec["seconds"] = time.time() - t_arm
        res["arms"][arm] = rec
        json.dump(res, open(out, "w"))
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
