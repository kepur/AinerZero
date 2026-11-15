#!/usr/bin/env python3
"""P256 review, item 2: degenerate inputs of analysis.decide (K = 0, 1, 2; no G arm; one bootstrap draw)."""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_data as D  # noqa: E402
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402

warnings.simplefilter("error", RuntimeWarning)
for K in (1, 2):
    r = AN.decide(D.my_make_data(K=K, KG=1), n=2000)
    gs = r["gates"]["GS"]
    print(f"K={K}: q {gs['q']:.4f} df {gs['df']} s_rep {gs['s_rep']} | GS per_replicate {gs['per_replicate']} point {gs['point']:.6f} "
          f"| passed {[g for g, x in r['gates'].items() if x['passed']]}")
try:
    d = D.my_make_data(K=0, KG=0)
    AN.decide(d, n=10)
    print("K=0 accepted")
except Exception as e:      # noqa: BLE001
    print("K=0:", type(e).__name__, e)
d = D.my_make_data()
for t in D.TEST_SETS:
    del d[t]["sums"]["G"]
r = AN.decide(d, n=500)
print("no G arm: decide runs, all_pass", r["all_pass"], "| describe keys", sorted(AN.describe(d)["main6"]))
try:
    r = AN.decide(D.my_make_data(), n=1)
    print("n=1 bootstrap draw:", {g: x["bonferroni"] for g, x in r["gates"].items()}, "all_pass", r["all_pass"])
except Exception as e:      # noqa: BLE001
    print("n=1 bootstrap draw:", type(e).__name__, e)
