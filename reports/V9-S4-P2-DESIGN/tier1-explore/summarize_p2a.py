#!/usr/bin/env python3
"""Summarize explore_p2a results: per arm and noise scale, re-identification (events averaged over the
three seeds, then pooled), IDF1, tracks, births, one-step coverage by step kind, and the member-state probe."""
import json
import sys
from collections import defaultdict

import numpy as np

r = json.load(open(sys.argv[1]))
W = r["per_world"]
keys = sorted({k.split("#")[0] + "@" + k.split("@")[1] for k in W[0]["cells"]})
out = {}
for ak in keys:
    arm, tag = ak.split("@")
    acc = {"coll": [0.0, 0], "all": [0.0, 0]}
    idf1, ntr, births, swaps = [], [], defaultdict(float), 0.0
    cal = defaultdict(lambda: np.zeros(5))
    probe = defaultdict(float)
    for w in W:
        cells = [w["cells"][f"{arm}#{s}@{tag}"] for s in (1, 2, 3)]
        if any(c.get("diverged") for c in cells):
            diverged = locals().get("diverged", 0) + sum(1 for c in cells if c.get("diverged"))
            continue
        if w["events"]:
            per = np.mean([c["correct"] for c in cells], axis=0)
            coll = np.array([e[3] == 1 for e in w["events"]])
            acc["coll"][0] += per[coll].sum(); acc["coll"][1] += coll.sum()
            acc["all"][0] += per.sum(); acc["all"][1] += len(per)
        for c in cells:
            idf1.append(c["idf1"]); ntr.append(c["n_tracks"]); swaps += c["swaps"] / 3
            for k, v in c["births"].items():
                births[k] += v / 3
            for k, v in c["calib"].items():
                cal[k] += np.array(v)
            if c["probe"]:
                for k, v in c["probe"].items():
                    probe[k] += v
    o = {"acc_coll": acc["coll"][0] / max(acc["coll"][1], 1), "acc_all": acc["all"][0] / max(acc["all"][1], 1),
         "n_coll_events": int(acc["coll"][1]), "n_events": int(acc["all"][1]),
         "idf1": float(np.mean(idf1)), "n_tracks": float(np.mean(ntr)),
         "births_per_world": {k: v / len(W) for k, v in births.items()}, "swaps_per_world": swaps / len(W),
         "calib": {k: {"n": int(v[0]), "cov90": v[1] / v[0], "nll": v[2] / v[0], "bias2": v[3] / v[0], "spread": v[4] / v[0]} for k, v in cal.items() if v[0]}}
    if probe:
        o["probe"] = {"D_filter": 1 - probe["coll_m"] / probe["coll_b"] if probe["coll_b"] else None,
                      "coll_vel_err": probe["coll_m"] / max(probe["n_coll"], 1), "coll_vel_err_EB": probe["coll_b"] / max(probe["n_coll"], 1),
                      "coll_pos_err": probe["coll_pos"] / max(probe["n_coll"], 1),
                      "free_vel_err": probe["free_m"] / max(probe["n_free"], 1), "free_pos_err": probe["free_pos"] / max(probe["n_free"], 1),
                      "coll_share": probe["n_coll"] / max(probe["n_coll"] + probe["n_free"], 1)}
    o["diverged_cells"] = locals().get("diverged", 0)
    o["worlds_used"] = len(W) - sum(1 for w in W if any(w["cells"][f"{arm}#{s}@{tag}"].get("diverged") for s in (1, 2, 3)))
    out[ak] = o
    if "diverged" in locals():
        del diverged

print(f"{'cell':12} {'accC':>6} {'accA':>6} {'idf1':>6} {'trk':>5} {'bVis':>5} {'bGap':>5} {'swap':>5} | cov all/coll/graze/free | nll all/coll/free | bias2 free, spread free, bias2 coll, spread coll")
for ak, o in out.items():
    c = o["calib"]
    g = lambda k, f: c[k][f] if k in c else float("nan")
    print(f"{ak:12} {o['acc_coll']:6.3f} {o['acc_all']:6.3f} {o['idf1']:6.3f} {o['n_tracks']:5.2f} {o['births_per_world'].get('visible',0):5.2f} {o['births_per_world'].get('gap',0):5.2f} {o['swaps_per_world']:5.2f} | "
          f"{g('all','cov90'):.3f}/{g('collision','cov90'):.3f}/{g('graze','cov90'):.3f}/{g('free','cov90'):.3f} | {g('all','nll'):.2f}/{g('collision','nll'):.2f}/{g('free','nll'):.2f} | "
          f"{g('free','bias2'):.5f} {g('free','spread'):.5f} {g('collision','bias2'):.5f} {g('collision','spread'):.5f}")
for ak, o in out.items():
    if "probe" in o:
        print(ak, json.dumps({k: round(v, 5) if isinstance(v, float) else v for k, v in o["probe"].items()}))
for ak, o in out.items():
    if o["diverged_cells"]:
        print(ak, "diverged cells", o["diverged_cells"], "worlds used", o["worlds_used"])
print("n events", out[keys[0]]["n_events"], "collision", out[keys[0]]["n_coll_events"], "elapsed", round(r.get("elapsed_s", 0)))
if len(sys.argv) > 2:
    json.dump(out, open(sys.argv[2], "w"), indent=1)
