#!/usr/bin/env python3
"""S6 r1 review, item 3: how good is a percentile bootstrap over 5 replicates (with replacement) at the
Bonferroni level DESIGN-r1 uses (m = 8, one side 0.025 / 8 = 0.3125%)? NumPy only, no MLX.

(1) exact bootstrap distribution of the mean of 5 values resampled with replacement (126 compositions,
    multinomial weights), so no Monte Carlo error inside the bootstrap;
(2) coverage over 20000 simulated experiments with normal replicate effects: P(lower bound < true mean),
    nominal 1 - 0.003125 = 0.996875; compared with the t interval on the 5 replicate values (df = 4);
(3) the design's gate statistics recomputed on the four exploration runs as if they were replicates
    (C, D, r3, r4: different pools and test worlds), both ways.
"""
import itertools
import json
import math

import numpy as np

ALPHA = 0.025 / 8
n = 5


def t_ppf(p, df, lo=0.0, hi=100.0):
    """Quantile of Student's t by bisection on a numerically integrated CDF (no scipy here)."""
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    def cdf(x):
        g = np.linspace(0.0, x, 200001)
        f = c * (1 + g * g / df) ** (-(df + 1) / 2)
        return 0.5 + np.trapezoid(f, g)
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


T4 = t_ppf(1 - ALPHA, 4)
T3 = t_ppf(1 - ALPHA, 3)
print(f"t quantiles at one-sided {ALPHA:.6f}: df=4 {T4:.3f}, df=3 {T3:.3f}  (check: df=4 at 0.975 = {t_ppf(0.975, 4):.3f}, table 2.776)")

# exact bootstrap distribution: compositions of 5 draws over 5 replicates
comps = [c for c in itertools.product(range(n + 1), repeat=n) if sum(c) == n]
W = np.array(comps, dtype=float) / n                                      # weights on the 5 replicates
P = np.array([math.factorial(n) / np.prod([math.factorial(k) for k in c]) for c in comps]) / n ** n
print(f"distinct bootstrap resamples of 5 replicates: {len(comps)}; probabilities sum {P.sum():.6f}")


def boot_lower(vals):
    m = W @ vals
    o = np.argsort(m)
    cum = np.cumsum(P[o])
    return m[o][np.searchsorted(cum, ALPHA)]


def t_lower(vals):
    return vals.mean() - T4 * vals.std(ddof=1) / math.sqrt(len(vals))


rng = np.random.default_rng(20261114)
trials = 20000
cov_b = cov_t = 0
wid_b = []; wid_t = []
for _ in range(trials):
    v = rng.normal(0.0, 1.0, n)
    lb, lt = boot_lower(v), t_lower(v)
    cov_b += lb < 0; cov_t += lt < 0
    wid_b.append(v.mean() - lb); wid_t.append(v.mean() - lt)
print(f"coverage of the one-sided bound (nominal {1 - ALPHA:.4f}): replicate bootstrap {cov_b / trials:.4f}, t (df=4) {cov_t / trials:.4f}")
print(f"median distance mean - bound (sigma = 1): bootstrap {np.median(wid_b):.3f}, t {np.median(wid_t):.3f}")
print(f"the bootstrap bound can never fall below the smallest replicate: min over trials of (bound - min value) = "
      f"{min(boot_lower(v) - v.min() for v in rng.normal(0, 1, (2000, n))):.4f}")

# (3) the exploration runs as stand-in replicates (combined test; DESIGN-r1 §1)
X = "/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S6-DESIGN"
runs = [("C", "tier1-explore/results-s6c.json"), ("D", "tier1-explore/results-s6d.json"),
        ("r3", "replication/results-s6r3.json"), ("r4", "replication/results-s6r4.json")]
gs, gt = [], []
for name, path in runs:
    c = json.load(open(f"{X}/{path}"))["curves"]
    e, r, t = c["disagree"][-1]["D"], c["random"][-1]["D"], c["truthcur"][-1]["D"]
    gs.append(e - r); gt.append((e - r) - 0.5 * (t - r))
for lab, v in (("GS  D(E)-D(R)", np.array(gs)), ("GT  [E-R]-0.5[T-R]", np.array(gt))):
    m, s = v.mean(), v.std(ddof=1)
    print(f"{lab}: runs {['%+.4f' % x for x in v]}  mean {m:+.4f}  SD {s:.4f}  "
          f"t-bound with 4 runs (df=3) {m - T3 * s / 2:+.4f}; projected with 5 replicates of the same SD (df=4) {m - T4 * s / math.sqrt(5):+.4f}")
