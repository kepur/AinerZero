#!/usr/bin/env python3
"""S4 phase 2 exploration, round G (s4x-p2a; exploration only): the registered phase-2 code itself
(worker_p2, analysis_p2, registered filter and arm seeds) on the exploration worlds, all 11 arms
including the r1 controls L-sc-g (main arm's gate, scattered velocity) and L-int-rand (random gate).
Main worlds 0..N-1 (6 disks), extrapolation 1000.. (10 disks). Prints every gate statistic and the
decision of analysis_p2.decide, as if these worlds were a run; also the descriptive tracking table.

Usage (under the shared lock): <this> N_MAIN N_EXTRAP OUT.json
"""
import json
import multiprocessing as mp
import sys
import time
from concurrent.futures import ProcessPoolExecutor

from ainerzero.v9.experiments.s4 import analysis_p2 as P2
from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4 import worker_p2 as WK

NS = "s4x-p2a"
WDIR = "artifacts/v9/s4/phase1/final-final/weights"


def main():
    n_main, n_ext, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    weights = {n: f"{WDIR}/{n}.safetensors" for n in WK.weight_names()}
    ids = P2.eval_world_ids((n_main, n_ext))
    tasks = [{"kind": k, "ns": NS, "episode": W.generate_episode(NS, w, d)} for k, w, d in ids]
    t0 = time.time()
    with ProcessPoolExecutor(6, mp_context=mp.get_context("spawn"), initializer=WK.init, initargs=(weights,)) as ex:
        recs = list(ex.map(WK.evaluate_world, tasks))
    main_r = [r for r in recs if r["kind"] == "main"]
    ext_r = [r for r in recs if r["kind"] == "extrap"]
    st = P2.gate_stats(main_r, ext_r)
    passed, neg = P2.decide(st)
    desc = P2.summarize_descriptive(main_r, ext_r, P2.HAND + P2.LEARNED)
    json.dump({"ns": NS, "elapsed_s": time.time() - t0, "stats": st, "passed": passed, "negative_control": neg,
               "descriptive": desc, "records": recs}, open(out, "w"))
    print(f"{len(recs)} worlds in {time.time() - t0:.0f}s")
    f = lambda d: "—" if d is None or d.get("value") is None else f"{d['value']:+.3f} [{d['bonf_low']:+.3f}, {d['bonf_high']:+.3f}]"
    for k, v in st.items():
        print(f"{k:18} {f(v)}")
    print("passed", passed, "negative control", neg)
    for part in ("main", "extrap"):
        print(f"\n{part}: arm  coll  non  all | 1-step all/coll | reappear non/coll | C | gate share")
        for a, row in desc[part].items():
            c = row.get("C", {}).get("value") if isinstance(row.get("C"), dict) else None
            print(f"{a:11} {row['acc_collision']:.3f} {row['acc_non_collision']:.3f} {row['acc_all']:.3f} | {row['one_step_all']:.3f}/{row['one_step_collision']:.3f}"
                  f" | {row['reappear_non_collision']:.3f}/{row['reappear_collision']:.3f} | {'' if c is None else f'{c:.3f}'} | {row.get('gate_share') or ''}")
        print("L-int-g − L-sc-g:", {w: f(v) for w, v in desc["learned_minus_scatter"][part].items()})
    print("\ndynamics", json.dumps({p: {a: {k: round(x, 4) for k, x in v.items() if x is not None} for a, v in d.items()} for p, d in desc["dynamics"].items()}))


if __name__ == "__main__":
    main()
