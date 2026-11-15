#!/usr/bin/env python3
"""P256 review, item 4: are the surviving analysis mutants (Q1, Q2, Q3, Q5) equivalent?

Each mutant is built in memory from the live analysis.py text with the same anchor/replacement as
mutate_review.sh (nothing is written), then decide() is compared with the original on synthetic data,
including data with a replicate effect shared by the arms (indep_data.paired_data)."""
from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import indep_data as D  # noqa: E402
from ainerzero.v9.experiments.s6 import analysis as AN  # noqa: E402

TEXT = Path(AN.__file__).read_text(encoding="utf-8")
MUTANTS = {
    "Q1": [('        lo, hi, parts = interval(spec, x, tk, boot[g], p_bonf)',
            '        lo, hi, parts = interval(spec, x, tk, boot[g], p_95)')],
    "Q2": [('    return {arm: stats(d["sums"][arm], d["counts"], d["eb"], reps, np.arange(W_)) for arm in GATE_ARMS}',
            '    return {arm: stats(d["sums"][arm], d["counts"], d["eb"], (reps + (arm in ("R", "Z"))) % K, np.arange(W_)) for arm in GATE_ARMS}')],
    "Q3": [('        tk = [float(_gate_value(spec, per_rep[spec["set"]][k])) for k in range(K)]',
            '        tk = [float(_gate_value(spec, per_rep[spec["set"]][k])) for k in range(K)]\n'
            '        if spec["form"] == "ratio":\n            x = float(np.exp(np.mean(np.log(tk))))')],
    "Q5": [('                term *= c2 * (2 * j) / (2 * j + 1)', '                term *= c2 * (2 * j - 1) / (2 * j)')],
}


def build(name):
    s = TEXT
    for old, new in MUTANTS[name]:
        assert s.count(old) == 1, name
        s = s.replace(old, new, 1)
    m = types.ModuleType(f"analysis_{name}")
    sys.modules[m.__name__] = m
    exec(compile(s, f"analysis.py[{name}]", "exec"), m.__dict__)
    return m


def show(tag, a, b, gates=("GS", "GT", "GZ-W", "GK-F")):
    for g in gates:
        x, y = a["gates"][g], b["gates"][g]
        print(f"   {tag} {g:5s} point {x['point']:+.6f} -> {y['point']:+.6f} | s_rep {x.get('s_rep', float('nan')):.5f} -> "
              f"{y.get('s_rep', float('nan')):.5f} | bonferroni [{x['bonferroni'][0]:+.5f}, {x['bonferroni'][1]:+.5f}] -> "
              f"[{y['bonferroni'][0]:+.5f}, {y['bonferroni'][1]:+.5f}] | passed {x['passed']} -> {y['passed']}"
              + (f" | per_replicate_ok {x['per_replicate_ok']} -> {y['per_replicate_ok']}" if "per_replicate_ok" in x else ""))


mut = {k: build(k) for k in MUTANTS}
c1 = D.my_make_data()
c6 = D.paired_data()
print("original module:", AN.__file__)

print("Q1 gate intervals at the 95% level")
show("C1", AN.decide(c1, n=4000), mut["Q1"].decide(c1, n=4000))
# a near-threshold case: move E's wall-pillar factor towards Z's (1.00) until GZ-W's 95% upper bound is below 1
# but the Bonferroni one is not; any gate whose decision differs is reported
flip = None
for f in np.linspace(0.85, 0.99, 57):
    fact = dict(D.FACT); fact["E"] = D.FACT["E"][:2] + [float(f)] + D.FACT["E"][3:]
    d = D.my_make_data(seed=7, noise=0.15, fact=fact)
    a, b = AN.decide(d, n=2000), mut["Q1"].decide(d, n=2000)
    diff = [g for g in a["gates"] if a["gates"][g]["passed"] != b["gates"][g]["passed"]]
    if diff:
        flip = (round(float(f), 4), diff, a, b)
        break
if flip:
    f, diff, a, b = flip
    print(f"   flip: make_data(seed=7, noise=0.15) with E wall-pillar factor {f}: gates whose decision changes {diff}")
    show("flip", a, b, gates=tuple(diff))
else:
    print("   no flip found on this grid")

print("Q2 theta_k not paired by replicate (R and Z on replicate k+1)")
show("C1", AN.decide(c1, n=4000), mut["Q2"].decide(c1, n=4000))
show("C6", AN.decide(c6, n=4000), mut["Q2"].decide(c6, n=4000))
flip = None
for sd in (0.03, 0.06, 0.1, 0.15, 0.2):
    for seed in range(40):
        d = D.paired_data(seed=seed, rep_sd=sd)
        a, b = AN.decide(d, n=1000), mut["Q2"].decide(d, n=1000)
        diff = [g for g in a["gates"] if a["gates"][g]["passed"] != b["gates"][g]["passed"]]
        if diff:
            flip = (sd, seed, diff, a, b)
            break
    if flip:
        break
if flip:
    sd, seed, diff, a, b = flip
    print(f"   flip: paired_data(seed={seed}, rep_sd={sd}): gates whose decision changes {diff}")
    show("flip", a, b, gates=tuple(diff))
else:
    print("   no decision flip found on this grid")

print("Q3 ratio-gate point = geometric mean of the per-replicate ratios")
for tag, d in (("C1", c1), ("C6", c6), ("C6 rep_sd=0.2", D.paired_data(rep_sd=0.2))):
    a, b = AN.decide(d, n=1000), mut["Q3"].decide(d, n=1000)
    print(f"   {tag}: " + "; ".join(f"{g} {a['gates'][g]['point']:.7f} -> {b['gates'][g]['point']:.7f}" for g in ("GZ-W", "GK-A", "GK-F")))

print("Q5 t_cdf odd series with the even factor")
for df in (1, 3, 4, 5, 7):
    print(f"   t_ppf(0.996875, {df}): original {AN.t_ppf(0.996875, df):.6f}  mutant {mut['Q5'].t_ppf(0.996875, df):.6f}")
d6 = D.my_make_data(K=6)
a, b = AN.decide(d6, n=1000), mut["Q5"].decide(d6, n=1000)
print(f"   K=6: q {a['gates']['GS']['q']:.6f} -> {b['gates']['GS']['q']:.6f}; GS bonferroni lower {a['gates']['GS']['bonferroni'][0]:+.6f} -> "
      f"{b['gates']['GS']['bonferroni'][0]:+.6f}")
d5 = D.my_make_data(K=5)
print("   K=5 (the registered run): decide() identical:", AN.decide(d5, n=500) == mut["Q5"].decide(d5, n=500))
