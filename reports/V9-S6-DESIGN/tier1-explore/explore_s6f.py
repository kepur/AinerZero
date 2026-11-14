#!/usr/bin/env python3
"""S6 exploration, round F (s6x-*; exploration only): the geometric heuristic against the learner's own
disagreement, with the 6-disk and 10-disk test worlds reported apart.

Arms (3 networks each, round C's budget and schedule): random, disagree (round C), geo: each later round
picks candidates where some pair approaches on straight lines and touches within one step (the phase-1
contact baseline, gated.geo_gate on the exact state; label-free, hand-made geometry), filled at random when
fewer. Evaluation as explore_s6a.evaluate, separately on the 6-disk and on the 10-disk test worlds.

Usage (MLX; under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json [CAND_NS TEST_NS]
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, __file__.rsplit("/", 1)[0])
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import gated as G
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import world as W


def geo_flags(pool):
    return {n: G.geo_gate(e["p"].astype(np.float64), e["v"].astype(np.float64)).any(-1) for n, e in pool.by_n.items()}


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns = sys.argv[5] if len(sys.argv) > 5 else "s6x-cand"
    test_ns = sys.argv[6] if len(sys.argv) > 6 else "s6x-test"
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    tests = {"main6": [W.generate_episode(test_ns, w, 6) for w in range(20)], "extrap10": [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]}
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    gf = geo_flags(cand)
    gvec = np.array([gf[n][i] for n, i in allp])
    print(f"pool {time.time() - t0:.0f}s; geo-flagged share {gvec.mean():.4f}; of them with a disk contact {coll[gvec].mean():.3f}; "
          f"contacts flagged {gvec[coll].mean():.3f}", flush=True)
    res = {"namespaces": {"candidates": cand_ns, "test": test_ns}, "geo_flagged_share": float(gvec.mean()), "curves": {}}
    for arm in ("random", "disagree", "geo"):
        mx.set_default_device(mx.gpu)
        learners = [XC.Learner(s) for s in XA.SEEDS]
        rng = np.random.default_rng(100)
        chosen = list(rng.choice(len(allp), per, replace=False))
        res["curves"][arm] = []
        for r in range(rounds):
            pool = XA.subset(cand, [allp[i] for i in chosen])
            for lr_ in learners:
                lr_.train(pool, spr, 0.0)
            mx.set_default_device(mx.cpu)
            row = {"n_labels": len(chosen), "disk_contact_share": float(coll[chosen].mean())}
            for tname, eps in tests.items():
                ev = XA.evaluate({f"{arm}#{s}": l.model for s, l in zip(XA.SEEDS, learners)}, eps)
                row[tname] = {k: float(np.mean([ev[f"{arm}#{s}"][k] for s in XA.SEEDS])) for k in ("collision", "graze", "wall_pillar", "free", "all", "D")}
                row[tname]["D_per_seed"] = [float(ev[f"{arm}#{s}"]["D"]) for s in XA.SEEDS]
            res["curves"][arm].append(row)
            m, x = row["main6"], row["extrap10"]
            print(f"{arm:9} round {r} n={len(chosen):6d} contact={row['disk_contact_share']:.3f} | main6 D={m['D']:.3f} {['%.3f' % d for d in m['D_per_seed']]} "
                  f"free={m['free']:.4f} wall={m['wall_pillar']:.4f} all={m['all']:.4f} | extrap10 D={x['D']:.3f} all={x['all']:.4f}  {time.time() - t0:.0f}s", flush=True)
            if r == rounds - 1:
                break
            rest = np.setdiff1d(np.arange(len(allp)), chosen)
            if arm == "random":
                new = rng.choice(rest, per, replace=False)
            elif arm == "geo":
                flagged = rest[gvec[rest]]
                take = rng.choice(flagged, min(per, len(flagged)), replace=False)
                fill = rng.choice(np.setdiff1d(rest, take), per - len(take), replace=False) if len(take) < per else np.array([], int)
                new = np.concatenate([take, fill]).astype(int)
            else:
                dis, _ = XA.score_pool(cand, [l.model for l in learners])
                score = np.array([dis[n][i] for n, i in allp])
                new = rest[np.argsort(-score[rest])[:per]]
            chosen += list(new)
            mx.set_default_device(mx.gpu)
    json.dump(res, open(out, "w"), indent=1)
    print(f"total {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
