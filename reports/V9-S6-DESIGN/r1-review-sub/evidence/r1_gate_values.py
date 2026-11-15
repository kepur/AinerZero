#!/usr/bin/env python3
"""S6 r1 review, items 1 and 4: DESIGN-r1's new gate statistics on the r0-review C-world per-world data
(r0-review-sub/evidence/{perworld,proxy}-s6x.json, round 3 = 12000 labels), world-only paired bootstrap
as in r0 (one replicate only, so no replicate level), Bonferroni m = 8. Also the C-world graze E/Z that
DESIGN-r1 §1 line 83 lists as not computed. CPU / NumPy only."""
import json

import numpy as np

from ainerzero.v9.experiments.s4 import metrics as M

E = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN/r0-review-sub/evidence"
runs = {}
for f in ("perworld-s6x.json", "proxy-s6x.json"):
    runs.update(json.load(open(f"{E}/{f}"))["arms"])


def ws(arm):
    pw = runs[arm]["rounds"][-1]["per_world"]
    s = np.array([[pw[k][w]["sums"] for w in range(30)] for k in sorted(pw)]).mean(0)   # [W, 4] averaged over nets
    c = np.array([pw[sorted(pw)[0]][w]["cnt"] for w in range(30)], dtype=float)
    b = np.array([pw[sorted(pw)[0]][w]["eb_coll"] for w in range(30)])
    return s, c, b


S = {a: ws(a)[0] for a in ("random", "disagree", "truthcur", "mindist")}
_, cnt, eb = ws("random")
splits = {"main6": np.arange(20), "C_all30": np.arange(30), "extrap10": np.arange(20, 30)}


def fmt(b):
    return f"{b['value']:+.4f}  95% [{b['ci_low']:+.4f}, {b['ci_high']:+.4f}]  Bonf(m=8) [{b['bonf_low']:+.4f}, {b['bonf_high']:+.4f}]"


for sp, idx in splits.items():
    sums = {"e": S["disagree"][:, 0], "r": S["random"][:, 0], "t": S["truthcur"][:, 0], "z": S["mindist"][:, 0], "b": eb,
            "ew": S["disagree"][:, 2], "zw": S["mindist"][:, 2], "ef": S["disagree"][:, 3], "zf": S["mindist"][:, 3],
            "eg": S["disagree"][:, 1], "zg": S["mindist"][:, 1], "ea": S["disagree"].sum(1), "ra": S["random"].sum(1)}
    sub = {k: v[idx] for k, v in sums.items()}
    gt = M.bootstrap(lambda e, r, t, b, **_: ((r - e) - 0.5 * (r - t)) / b, sub, m=8)
    gzd = M.bootstrap(lambda e, z, b, **_: (z - e) / b, sub, m=8)
    gzw = M.bootstrap(lambda ew, zw, **_: M._ratio(ew, zw), sub, m=8)
    gkf = M.bootstrap(lambda ef, zf, **_: M._ratio(ef, zf), sub, m=8)
    gka = M.bootstrap(lambda ea, ra, **_: M._ratio(ea, ra), sub, m=8)
    gs = M.bootstrap(lambda e, r, b, **_: (r - e) / b, sub, m=8)
    graze = M.bootstrap(lambda eg, zg, **_: M._ratio(eg, zg), sub, m=8)
    print(f"--- {sp} ({len(idx)} worlds), world-only bootstrap ---")
    print(f"GS   D(E)-D(R)              {fmt(gs)}")
    print(f"GT   [E-R]-0.5[T-R]         {fmt(gt)}")
    print(f"GZ-D D(E)-D(Z)              {fmt(gzd)}")
    print(f"GZ-W wall E/Z               {fmt(gzw)}")
    print(f"GK-A all E/R                {fmt(gka)}")
    print(f"GK-F free E/Z               {fmt(gkf)}")
    print(f"     graze E/Z (descriptive) {fmt(graze)}")
