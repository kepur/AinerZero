#!/usr/bin/env python3
"""S6 r3 review, item 2 (pure CPU): how much room does the r3 training cap (19800 s) leave? Per-round training
times of the probe cells (artifacts/v9/s6/phase1/probe/cells/*/cell.json) and of the round-G cells
(artifacts/v9/s6/explore/s6x-cand5-r0/*/cell.json, same formal code path, same sizes), and the final's
projected training wall clock under a few stresses, with the runner's ledger rule (an invocation that dies
after its last heartbeat is charged DANGLING_CHARGE_S = 900 s more)."""
import json
from pathlib import Path

A = Path("/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s6")
REPS = {"R": 5, "E": 5, "Z": 5, "T": 5, "P": 5, "G": 3}
CAP, POOL_S, DANGLING = 19800.0, 28.0, 900.0      # pool: the probe built its pool in ~28 s (train-probe.log)
runs = {"probe": A / "phase1/probe/cells/{a}-r0/cell.json", "roundG": A / "explore/s6x-cand5-r0/{a}/cell.json"}
sec, per_round = {}, {}
for name, pat in runs.items():
    for a in REPS:
        rec = json.load(open(str(pat).format(a=a)))
        sec[(name, a)] = rec["seconds"]
        per_round[(name, a)] = [round(t["train_s"], 1) for t in rec.get("timings", [])]
for a in REPS:
    p, g = sec[("probe", a)], sec[("roundG", a)]
    print(f"{a}: probe {p:6.1f} s {per_round[('probe', a)]}  | round G {g:6.1f} s {per_round[('roundG', a)]}  | probe/G {p / g:.3f}")
allr = [x for v in per_round.values() for x in v]
print(f"per-round training time over both runs: min {min(allr):.1f} s, max {max(allr):.1f} s, max/min {max(allr) / min(allr):.2f}")


def total(cell):
    return sum(cell[a] * k for a, k in REPS.items()) + 5 * POOL_S


base = {a: sec[("probe", a)] for a in REPS}
worst = {a: max(sec[("probe", a)], sec[("roundG", a)]) for a in REPS}
slowest_round = max(allr)
uniform = {a: base[a] * slowest_round / (sum(per_round[("probe", a)]) / len(per_round[("probe", a)])) for a in REPS}
for lab, cells in (("probe cell times", base), ("slower of probe / round G per arm", worst),
                   (f"every round at the slowest observed {slowest_round:.1f} s", uniform)):
    t = total(cells)
    print(f"{lab:42}: {t:8.1f} s  -> cap/total {CAP / t:.3f}; slack {CAP - t:7.1f} s = {(CAP - t) / DANGLING:.1f} crashes at {DANGLING:.0f} s each")
need = (CAP - 5 * POOL_S) / sum(base[a] * k for a, k in REPS.items())
print(f"uniform slowdown of every cell (vs probe) that reaches the cap with no crash: x{need:.3f}")
