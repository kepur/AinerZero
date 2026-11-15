#!/usr/bin/env python3
"""P256 review, item 2b: analysis.t_ppf / t_cdf / norm_ppf against textbook tables and mpmath."""
from __future__ import annotations

import math

import mpmath as mp

from ainerzero.v9.experiments.s6 import analysis as AN

mp.mp.dps = 40
print("analysis from", AN.__file__)

# Two-sided-table values (upper quantile p), 3 decimals as printed in standard Student t tables
# (e.g. Fisher & Yates; NIST/SEMATECH e-Handbook 1.3.6.7.2); t(4, 0.996875) = 5.261 is the r1-review value.
TEXTBOOK = [(0.975, 1, 12.706), (0.975, 2, 4.303), (0.975, 3, 3.182), (0.975, 4, 2.776), (0.975, 5, 2.571),
            (0.975, 7, 2.365), (0.975, 9, 2.262), (0.975, 20, 2.086), (0.95, 15, 1.753), (0.99, 9, 2.821),
            (0.995, 1, 63.657), (0.995, 3, 5.841), (0.995, 4, 4.604), (0.995, 5, 4.032), (0.995, 10, 3.169),
            (0.999, 4, 7.173), (0.9995, 4, 8.610), (0.9995, 5, 6.869), (1 - 0.025 / 8, 4, 5.261)]
worst = 0.0
for p, df, want in TEXTBOOK:
    got = AN.t_ppf(p, df)
    worst = max(worst, abs(got - want))
    print(f"t({df:2d}, {p:.6f}) analysis {got:.6f}  table {want:.3f}  |diff| {abs(got - want):.2e}")
print(f"textbook: {len(TEXTBOOK)} values, worst |diff| {worst:.2e} (tables round to 5e-4)")


def ref_cdf(x, df):
    nu = mp.mpf(df)
    x = mp.mpf(x)
    tail = mp.betainc(nu / 2, mp.mpf(1) / 2, 0, nu / (nu + x * x), regularized=True) / 2
    return 1 - tail if x >= 0 else tail


def ref_ppf(p, df):
    lo, hi = mp.mpf(0), mp.mpf(1)
    while ref_cdf(hi, df) < p:
        hi *= 2
    for _ in range(160):                       # bisection at 40 digits
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ref_cdf(mid, df) < p else (lo, mid)
    return (lo + hi) / 2


ps = (0.6, 0.9, 0.95, 0.975, 0.99, 0.995, 1 - 0.025 / 8, 0.999, 0.9995, 0.99999)
worst_q, worst_c, at_q, at_c = 0.0, 0.0, None, None
for df in range(1, 61):
    for p in ps:
        r = float(ref_ppf(p, df))
        rel = abs(AN.t_ppf(p, df) - r) / r
        if rel > worst_q:
            worst_q, at_q = rel, (df, p)
    for x in (-30.0, -5.0, -2.0, -0.7, -0.01, 0.0, 0.3, 1.0, 2.5, 4.0, 9.0, 50.0):
        d = abs(AN.t_cdf(x, df) - float(ref_cdf(x, df)))
        if d > worst_c:
            worst_c, at_c = d, (df, x)
print(f"mpmath, df 1..60 x {len(ps)} levels: worst relative error of t_ppf {worst_q:.2e} at (df, p) = {at_q}")
print(f"mpmath, df 1..60 x 12 points (negative x included): worst |error| of t_cdf {worst_c:.2e} at (df, x) = {at_c}")
odd = [(df, AN.t_ppf(0.975, df), float(ref_ppf(0.975, df))) for df in (5, 7, 9, 11)]
print("odd df >= 5 (the odd-series loop body runs only from df = 5):", [(d, round(a, 9), round(b, 9)) for d, a, b in odd])
for p in (0.975, 1 - 0.025 / 8, 0.999):
    z = float(mp.sqrt(2) * mp.erfinv(2 * mp.mpf(p) - 1))
    print(f"norm_ppf({p:.6f}) analysis {AN.norm_ppf(p):.12f}  mpmath {z:.12f}")
print("levels used by decide(): Bonferroni p =", 1 - AN.ALPHA / (2 * AN.M), "| t(4, that p) =", AN.t_ppf(1 - AN.ALPHA / (2 * AN.M), 4),
      "| t(4, 0.975) =", AN.t_ppf(0.975, 4))
for bad in ((0.5, 4), (1.0, 4)):
    try:
        AN.t_ppf(*bad)
        print("t_ppf", bad, "accepted")
    except ValueError as e:
        print("t_ppf", bad, "ValueError:", e)
for bad_df in (0, 2.5, -1):
    try:
        AN.t_cdf(1.0, bad_df)
        print("t_cdf df", bad_df, "accepted")
    except ValueError as e:
        print("t_cdf df", bad_df, "ValueError:", e)
print("t_cdf(1e300, 4) =", AN.t_cdf(1e300, 4), "| t_cdf(-1e300, 3) =", AN.t_cdf(-1e300, 3), "| isfinite",
      math.isfinite(AN.t_cdf(1e300, 4)))
