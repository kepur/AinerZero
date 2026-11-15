#!/usr/bin/env python3
"""P256 review, item 2: compare indep_gates.py with analysis.decide(), gate by gate, |diff| < 1e-9.
Usage: compare_gates.py INDEP_JSON AUTHOR_JSON BOOT_DIR"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

TOL = 1e-9
ind = json.loads(Path(sys.argv[1]).read_text())
aut = json.loads(Path(sys.argv[2]).read_text())
boot_dir = Path(sys.argv[3])


def close(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    a, b = float(a), float(b)
    if math.isnan(a) or math.isnan(b):
        return math.isnan(a) and math.isnan(b)
    return abs(a - b) < TOL


worst, bad, n_cmp = 0.0, [], 0
for cfg in ind:
    gi, ga = ind[cfg]["gates"], aut[cfg]["gates"]
    assert sorted(gi) == sorted(ga), (cfg, sorted(gi), sorted(ga))
    print(f"== {cfg}: K={ind[cfg]['K']} replicates (author {aut[cfg]['replicates']}); "
          f"q_bonf indep {ind[cfg]['q_bonf']:.12f}; all_pass indep {ind[cfg]['all_pass']} author {aut[cfg]['all_pass']}")
    for g in gi:
        a, b = gi[g], ga[g]
        pairs = [("point", a["point"], b["point"])]
        pairs += [(f"theta_{k}", x, y) for k, (x, y) in enumerate(zip(a["per_replicate"], b["per_replicate"]))]
        pairs += [("bonf_lo", a["bonferroni"][0], b["bonferroni"][0]), ("bonf_hi", a["bonferroni"][1], b["bonferroni"][1]),
                  ("ci95_lo", a["ci95"][0], b["ci95"][0]), ("ci95_hi", a["ci95"][1], b["ci95"][1]), ("se", a["se"], b["se"])]
        if "s_rep" in a:
            pairs += [("s_rep", a["s_rep"], b["s_rep"]), ("se_w", a["se_w"], b["se_w"]), ("q", a["q"], b["q"])]
        pairs += [(k, a[k], b[k]) for k in ("point_ok", "interval_ok", "passed")]
        if "per_replicate_ok" in a or "per_replicate_ok" in b:
            pairs.append(("per_replicate_ok", a.get("per_replicate_ok"), b.get("per_replicate_ok")))
        if len(a["per_replicate"]) != len(b["per_replicate"]):
            bad.append((cfg, g, "per_replicate length"))
        for name, x, y in pairs:
            n_cmp += 1
            if not close(x, y):
                bad.append((cfg, g, name, x, y))
            elif not isinstance(x, bool) and math.isfinite(float(x)):
                worst = max(worst, abs(float(x) - float(y)))
        print(f"   {g:5s} point {a['point']:+.9f} | bonf [{a['bonferroni'][0]:+.9f}, {a['bonferroni'][1]:+.9f}] "
              f"vs [{b['bonferroni'][0]:+.9f}, {b['bonferroni'][1]:+.9f}] | passed {a['passed']}/{b['passed']}")
    key = cfg.split()[0]
    bi, ba = np.load(boot_dir / f"indep-{key}.npz"), np.load(boot_dir / f"author-{key}.npz")
    with np.errstate(invalid="ignore"):
        d = {g: float(np.nanmax(np.abs(bi[g] - ba[g]))) if np.isfinite(bi[g]).any() else float("nan") for g in bi.files}
    nan_same = all(np.array_equal(np.isnan(bi[g]), np.isnan(ba[g])) for g in bi.files)
    print(f"   bootstrap draws: {len(bi['GS'])} per gate; max |indep - author| per gate {d}; NaN pattern identical {nan_same}")
    if "alt_se_w" in ind[cfg]:
        print(f"   sensitivity (se_w if the worlds were not shared): {ind[cfg]['alt_se_w']}; "
              f"shared (design): GS {ind[cfg]['gates']['GS'].get('se_w')}, GZ-W {ind[cfg]['gates']['GZ-W'].get('se_w')}")
print(f"compared {n_cmp} quantities; largest |diff| among finite values {worst:.3e}; mismatches: {bad if bad else 'none'}")
