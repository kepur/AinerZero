#!/usr/bin/env python3
"""S6 r1 review: structure of the exploration candidate pool (s6x-cand, built exactly as explore_s6c.py /
DESIGN-r1 §2: make_pool(train_worlds(ns, 120), 60000, default_rng(11), physics, exact_frac=1.0)).

(1) duplicates: make_pool draws (world, step) with replacement from 120 x 300 = 36000 states, so the
    pool repeats states; how many distinct states, and how many distinct states each arm's 12000
    "labels" contain (chosen ids from r0-review-sub/evidence/{perworld,proxy}-s6x.json, global ids in
    the flat (disk count, index) order that sandbox.CandidatePool also uses);
(2) successors: for how many candidates is the one-step outcome (p1, v1) itself another candidate's
    state in the pool (same pillars), i.e. readable from states() alone; and for how many of the
    candidates with a disk contact at step 1.
CPU only (numpy physics); run under the shared lock anyway because learned_mlx imports MLX.
"""
import json
import sys

import numpy as np

sys.path.insert(0, "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/tier1-explore")
import explore_s6a as XA  # noqa: E402
from ainerzero.v9.experiments.s4 import analysis as A  # noqa: E402
from ainerzero.v9.experiments.s4 import learned_mlx as L  # noqa: E402
from ainerzero.v9.experiments.s4 import world as W  # noqa: E402

R0 = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/r0-review-sub/evidence"
cand = L.make_pool(A.train_worlds("s6x-cand", 120), 60_000, np.random.default_rng(11), W.physics, exact_frac=1.0)
allp = XA.flat_pool(cand)


def key(p, v, pil):
    return p.tobytes() + v.tobytes() + pil.tobytes()


state_key = [key(cand.by_n[n]["p"][i], cand.by_n[n]["v"][i], cand.by_n[n]["pil"][i]) for n, i in allp]
succ_key = [key(cand.by_n[n]["p1"][i], cand.by_n[n]["v1"][i], cand.by_n[n]["pil"][i]) for n, i in allp]
contact = np.array([cand.by_n[n]["contact"][i].sum() > 0 for n, i in allp])
present = set(state_key)
has_succ = np.array([k in present for k in succ_key])
N = len(allp)
print(f"pool size {N}; distinct states {len(present)} ({len(present) / N:.3f})")
print(f"candidates whose one-step outcome (p1, v1) is itself a candidate state: {has_succ.mean():.3f}; "
      f"among candidates with a disk contact at step 1: {has_succ[contact].mean():.3f} ({int(has_succ[contact].sum())} of {int(contact.sum())})")

runs = {}
for f in ("perworld-s6x.json", "proxy-s6x.json"):
    runs.update(json.load(open(f"{R0}/{f}"))["arms"])
per = 3000
for arm in ("random", "disagree", "mindist", "truthcur", "maxspeed"):
    if arm not in runs:
        continue
    ch = runs[arm]["chosen"]
    rows = []
    for r in range(4):
        new = ch[r * per:(r + 1) * per]
        rows.append(f"r{r} new {len({state_key[i] for i in new})}/{per}")
    tot = len({state_key[i] for i in ch})
    print(f"{arm:9} distinct states among the 12000 chosen: {tot} ({tot / len(ch):.3f});  " + ", ".join(rows))
