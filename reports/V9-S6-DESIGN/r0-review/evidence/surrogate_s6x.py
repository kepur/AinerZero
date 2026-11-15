#!/usr/bin/env python3
"""Zero-knowledge surrogate selectors on the explore_s6c schedule.

Same pool, seeds, first-round RNG, training and mixed evaluation as explore_s6c.py.
Later rounds do not call score_pool and do not read contact / v1 / p1 labels.

Arms:
  vmax     highest max-disk speed ||v||_2 (state velocity only)
  mindist  smallest pairwise centre distance (state position only; no approach test)

Also records the 6-disk and 10-disk splits, and per-seed metrics.
Usage (MLX, under the shared lock): <this> PER ROUNDS STEPS_PER_ROUND OUT.json [CAND_NS TEST_NS]
"""
import json
import sys
import time

import mlx.core as mx
import numpy as np

sys.path.insert(0, "reports/V9-S6-DESIGN/tier1-explore")
import explore_s6a as XA  # noqa: E402
import explore_s6c as XC  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

KEYS = ("collision", "graze", "wall_pillar", "free", "all", "D")


def state_scores(pool):
    """Per-bucket scores from p and v only. Returns (vmax, mindist_closeness)."""
    vmax, close = {}, {}
    for n, e in pool.by_n.items():
        v = np.asarray(e["v"], dtype=np.float64)
        vmax[n] = np.linalg.norm(v, axis=-1).max(-1)
        p = np.asarray(e["p"], dtype=np.float64)
        d = np.linalg.norm(p[:, :, None, :] - p[:, None, :, :], axis=-1)
        d[:, np.eye(n, dtype=bool)] = np.inf
        close[n] = -d.min(axis=(1, 2))  # larger = nearer
    return vmax, close


def pack(ev, arm):
    summ = {k: float(np.mean([ev[f"{arm}#{s}"][k] for s in XA.SEEDS])) for k in KEYS}
    summ["per_seed"] = {
        str(s): {k: float(ev[f"{arm}#{s}"][k]) for k in KEYS} for s in XA.SEEDS
    }
    return summ


def main():
    per, rounds, spr, out = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
    cand_ns = sys.argv[5] if len(sys.argv) > 5 else "s6x-cand"
    test_ns = sys.argv[6] if len(sys.argv) > 6 else "s6x-test"
    t0 = time.time()
    cand = L.make_pool(A.train_worlds(cand_ns, 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
    main6 = [W.generate_episode(test_ns, w, 6) for w in range(20)]
    extrap10 = [W.generate_episode(test_ns, 1000 + w, 10) for w in range(10)]
    tests = {"mixed": main6 + extrap10, "main6": main6, "extrap10": extrap10}
    allp = XA.flat_pool(cand)
    coll = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
    vmax_b, close_b = state_scores(cand)
    scores = {
        "vmax": np.array([vmax_b[n][i] for n, i in allp]),
        "mindist": np.array([close_b[n][i] for n, i in allp]),
    }
    print(
        f"pool {time.time() - t0:.0f}s, disk-contact share {coll.mean():.3f} "
        f"score_inputs vmax=v mindist=p",
        flush=True,
    )
    res = {
        "per": per,
        "rounds": rounds,
        "steps_per_round": spr,
        "namespaces": {"candidates": cand_ns, "test": test_ns},
        "score_inputs": {"vmax": ["v"], "mindist": ["p"]},
        "note": "selection ranks state scores only; contact is counted after selection for the log",
        "curves": {},
    }
    for arm in ("vmax", "mindist"):
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
                row[tname] = pack(ev, arm)
            res["curves"][arm].append(row)
            m = row["mixed"]
            print(
                f"{arm:9} round {r} n={len(chosen):6d} contact={row['disk_contact_share']:.3f} "
                f"D={m['D']:.4f} per={[round(m['per_seed'][str(s)]['D'], 4) for s in XA.SEEDS]} "
                f"coll={m['collision']:.4f} wall={m['wall_pillar']:.4f} free={m['free']:.4f} all={m['all']:.4f} "
                f"main6D={row['main6']['D']:.4f} extrapD={row['extrap10']['D']:.4f}  {time.time() - t0:.0f}s",
                flush=True,
            )
            if r == rounds - 1:
                break
            rest = np.setdiff1d(np.arange(len(allp)), chosen)
            score = scores[arm]
            new = rest[np.argsort(-score[rest])[:per]]
            chosen += list(map(int, new))
            mx.set_default_device(mx.gpu)
        json.dump(res, open(out, "w"), indent=1)
        print(f"wrote {out} after {arm}", flush=True)
    print(f"total {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
