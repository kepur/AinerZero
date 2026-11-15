#!/usr/bin/env python3
"""Round G through the formal statistics (s6/analysis.py): gate point values and, with one replicate, the
world-sampling interval only (K = 1: no replicate layer, normal quantile). Exploration, not a gate decision.

Usage: analyze_s6g.py <results-s6g.json> [round]
"""
import json
import sys

import numpy as np

from ainerzero.v9.experiments.s6 import analysis as AN


def main():
    res = json.load(open(sys.argv[1]))
    rnd = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    arms = [a for a in AN.ARMS if a in res["arms"]]
    data = {}
    for t in AN.TEST_SETS:
        data[t] = {"counts": np.array(res["counts"][t]), "eb": np.array(res["eb"][t]),
                   "sums": {a: np.array(res["arms"][a]["rounds"][rnd][t]["sums"])[None] for a in arms}}
    out = {"round": rnd, "arms": arms, "decide_K1": AN.decide(data), "describe": AN.describe(data)}
    print(f"round {rnd}, arms {arms}; one replicate: intervals cover world sampling only")
    for g, row in out["decide_K1"]["gates"].items():
        print(f"  {g:5} point {row['point']:+.4f}  bonf(K=1) [{row['bonferroni'][0]:+.4f}, {row['bonferroni'][1]:+.4f}]"
              f"  point_ok {row['point_ok']}  interval_ok {row['interval_ok']}")
    m = out["describe"]["main6"]
    print("  main6 D:", {a: round(m["arms"][a]["D"], 4) for a in m["arms"]})
    print("  main6 E/R:", {k: round(v, 3) for k, v in m["E/R"].items()})
    print("  main6 E/Z:", {k: round(v, 3) for k, v in m["E/Z"].items()})
    for k in ("D(E)-D(T)", "D(P)-D(E)", "D(E)-D(G)"):
        if k in m:
            print(f"  main6 {k}: {m[k]:+.4f}")
    json.dump(out, open(sys.argv[1].replace(".json", f"-gates-r{rnd}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
