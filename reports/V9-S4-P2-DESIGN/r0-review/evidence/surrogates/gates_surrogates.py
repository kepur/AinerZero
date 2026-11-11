#!/usr/bin/env python3
"""P213: evaluate the registered phase-2 gates (analysis_p2.THRESHOLDS / decide, Bonferroni m = 11,
bootstrap 10000 over worlds, seed 20261111) for every arm in the surrogate records.

stats_for(arm) is analysis_p2.gate_stats with MAIN_ARM replaced by ``arm``; the script first checks
that stats_for("L-int-g") equals analysis_p2.gate_stats exactly, so every surrogate is judged by the
registered code path. Pure CPU (no MLX). Usage: python -I -B <this> records-main.json records-extrap.json OUT.json
"""
from __future__ import annotations

import json
import sys

import numpy as np

from ainerzero.v9.experiments.s4 import analysis_p2 as P2

ARMS = ("L-int-g", "L-int", "OFF", "RAND", "L-ind-g", "SCATTER", "L-ind-geo", "E-B", "E-P")


NONE = {"value": None, "ci_low": None, "ci_high": None, "bonf_low": None, "bonf_high": None}


def stats_for(main, extrap, a):
    dyn = a != "E-P"   # the reference E-P has no dynamics sums (D(E-P) = 1 by definition): GD left undefined
    return {"GN": P2.acc_diff(main, a, "E-B", "non_collision"), "GA": P2.acc_diff(main, a, "E-B", "all"), "GC": P2.C_of(main, a),
            "GK1_all": P2.coverage_one_step(main, a, "all"), "GK1_collision": P2.coverage_one_step(main, a, "collision"),
            "GK2_non_collision": P2.coverage_reappear(main, a, "non_collision"), "GK2_collision": P2.coverage_reappear(main, a, "collision"),
            "GD_D": P2.D_of(main, a) if dyn else NONE, "GD_ratio": P2.HF_of(main, a) if dyn else NONE,
            "GX_diff": P2.acc_diff(extrap, a, "E-B", "all"), "GX_C": P2.C_of(extrap, a),
            "neg_C": P2.C_of(main, P2.NEG_ARM, m=1), "neg_D": P2.D_of(main, P2.NEG_ARM, m=1)}


def fmt(st, key):
    v = st[key]
    f = lambda x: "  None" if x is None else f"{x:+.3f}"
    return f"{f(v['value'])} [{f(v.get('bonf_low'))},{f(v.get('bonf_high'))}]"


def gate_share(recs, arm):
    o = sum(r["cells"][f"{arm}#{s}"].get("gate", [0, 0])[0] for r in recs for s in P2.SEEDS)
    t = sum(r["cells"][f"{arm}#{s}"].get("gate", [0, 0])[1] for r in recs for s in P2.SEEDS)
    return o / t if t else None


def main():
    main_r = json.load(open(sys.argv[1]))["records"]
    ext_r = json.load(open(sys.argv[2]))["records"]
    out = {"n_main": len(main_r), "n_extrap": len(ext_r), "arms": {}}
    ref = P2.gate_stats(main_r, ext_r)
    mine = stats_for(main_r, ext_r, "L-int-g")
    same = json.dumps(ref, sort_keys=True) == json.dumps(mine, sort_keys=True)
    print(f"worlds main {len(main_r)} extrap {len(ext_r)}; stats_for('L-int-g') == analysis_p2.gate_stats: {same}")
    assert same
    # OFF must equal E-B bit for bit (gate closed -> E-B): identical track ids in every cell
    off_same = all(r["cells"][f"OFF#{s}"]["ids_sha256"] == r["cells"][f"E-B#{s}"]["ids_sha256"] for r in main_r + ext_r for s in P2.SEEDS)
    print(f"OFF track ids identical to E-B in all {3 * (len(main_r) + len(ext_r))} cells: {off_same}")
    out["off_equals_EB"] = off_same
    keys = ("GN", "GA", "GC", "GK1_all", "GK1_collision", "GK2_non_collision", "GK2_collision", "GD_D", "GD_ratio", "GX_diff", "GX_C")
    print("\nvalue [Bonferroni m=11 low, high] per statistic; gate decisions by analysis_p2.decide")
    for a in ARMS:
        st = stats_for(main_r, ext_r, a)
        passed, neg = P2.decide(st)
        out["arms"][a] = {"stats": st, "passed": passed, "gate_share_main": gate_share(main_r, a) if f"{a}#1" in main_r[0]["cells"] and "gate" in main_r[0]["cells"][f"{a}#1"] else None,
                          "gate_share_extrap": gate_share(ext_r, a) if f"{a}#1" in ext_r[0]["cells"] and "gate" in ext_r[0]["cells"][f"{a}#1"] else None,
                          "acc": {w: P2.acc_of(main_r, a, w)["value"] for w in ("collision", "non_collision", "all")}}
        print(f"\n== {a}  gate share main {out['arms'][a]['gate_share_main']}  extrap {out['arms'][a]['gate_share_extrap']}")
        print("   acc coll/non/all " + " ".join(f"{out['arms'][a]['acc'][w]:.3f}" for w in ("collision", "non_collision", "all")))
        for k in keys:
            print(f"   {k:18} {fmt(st, k)}")
        print("   passed: " + " ".join(f"{g}={'PASS' if v else 'fail'}" for g, v in passed.items()) + f" | negative control (L-ind-geo) {'PASS' if neg else 'fail'}")
    print("\npaired differences L-int-g - X on the main worlds (event accuracy, seeds averaged per event; 95% world bootstrap, m = 1):")
    out["paired"] = {}
    for x in ("SCATTER", "RAND", "L-int", "L-ind-geo"):
        for w in ("collision", "non_collision", "all"):
            d = P2.acc_diff(main_r, "L-int-g", x, w, m=1)
            out["paired"][f"L-int-g-{x}:{w}"] = d
            print(f"   L-int-g - {x:10} {w:14} {d['value']:+.3f} [{d['ci_low']:+.3f}, {d['ci_high']:+.3f}]")
        c = P2.C_of(main_r, x, m=1)
        print(f"   C({x}) = {c['value']:.3f} [{c['ci_low']:.3f}, {c['ci_high']:.3f}] (95%)")
    print(f"\nnegative control: C {fmt(ref, 'neg_C')} (95%: [{ref['neg_C']['ci_low']}, {ref['neg_C']['ci_high']}])  D {ref['neg_D']['value']} (95% high {ref['neg_D']['ci_high']})")
    json.dump(out, open(sys.argv[3], "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
