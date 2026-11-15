#!/usr/bin/env python3
"""P256 review, item 2: the eight gates recomputed from the r1-review formula with my own code.

Does NOT import analysis.py (checked at the end). Gate table typed in from DESIGN-r2 §4. Statistic written
as the ratio of sums pooled over replicates, networks and worlds (r1 review, must-fix 1 / DESIGN-r2 §4),
not as analysis.py's mean of per-(replicate, network) ratios. t and normal quantiles from mpmath
(regularized incomplete beta / erfinv), not from analysis.t_ppf.

Usage: indep_gates.py OUT_JSON BOOT_DIR"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import mpmath as mp
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indep_data as D  # noqa: E402

mp.mp.dps = 40
ALPHA, M = 0.05, 8
SEED = 20261114

# DESIGN-r2 §4, typed from the table: (set, statistic, form, a, b, c, point (op, v) or None, interval (end, op, v), per-replicate min)
GATES = {
    "GS":   ("main6", "D", "diff", "E", "R", None, (">=", 0.03), ("lower", ">", 0.0), 0.03),
    "GT":   ("main6", "D", "half", "E", "R", "T", None, ("lower", ">", 0.0), None),
    "GZ-D": ("main6", "D", "diff", "E", "Z", None, (">=", -0.02), ("lower", ">", -0.04), None),
    "GZ-W": ("main6", "wall_pillar", "ratio", "E", "Z", None, ("<=", 0.95), ("upper", "<", 1.0), None),
    "GK-A": ("main6", "all", "ratio", "E", "R", None, ("<=", 1.10), ("upper", "<=", 1.20), None),
    "GK-F": ("main6", "free", "ratio", "E", "Z", None, ("<=", 1.10), ("upper", "<=", 1.20), None),
    "GP":   ("main6", "D", "diff", "P", "R", None, (">=", 0.03), ("lower", ">", 0.0), None),
    "GX":   ("extrap10", "D", "diff", "E", "R", None, (">=", 0.02), ("lower", ">", 0.0), None),
}
KIND = {"collision": 0, "graze": 1, "wall_pillar": 2, "free": 3}


def t_quantile(p, df):
    nu = mp.mpf(df)
    cdf = lambda x: 1 - mp.betainc(nu / 2, mp.mpf(1) / 2, 0, nu / (nu + x * x), regularized=True) / 2
    lo, hi = mp.mpf(0), mp.mpf(1)
    while cdf(hi) < p:
        hi *= 2
    return float(mp.findroot(lambda x: cdf(x) - mp.mpf(p), (lo, hi), solver="anderson"))


def z_quantile(p):
    return float(mp.sqrt(2) * mp.erfinv(2 * mp.mpf(p) - 1))


def sd1(x):
    x = np.asarray(x, float)
    return math.sqrt(float(((x - x.mean()) ** 2).sum()) / (len(x) - 1))


def pooled(sums, counts, eb, reps, mult):
    """Ratio of sums pooled over the replicates ``reps`` (list, repeats count), all networks and the worlds
    weighted by ``mult`` [..., W]. Returns dict of arrays with shape mult.shape[:-1]."""
    s_kw = sum(sums[k].sum(0) for k in reps)                       # [W, 4] summed over networks and replicates
    reps_nets = len(reps) * sums.shape[1]
    S = mult @ s_kw                                                 # [..., 4]
    C = reps_nets * (mult @ counts.astype(float))                   # [..., 4]
    B = reps_nets * (mult @ eb.astype(float))                       # [...]
    with np.errstate(invalid="ignore", divide="ignore"):
        out = {"D": 1 - S[..., 0] / np.where(B == 0, np.nan, B)}
        for name, c in KIND.items():
            out[name] = S[..., c] / np.where(C[..., c] == 0, np.nan, C[..., c])
        tot = C.sum(-1)
        out["all"] = S.sum(-1) / np.where(tot == 0, np.nan, tot)
    return out


def gate_value(g, A):
    _, st, form, a, b, c, *_ = GATES[g]
    with np.errstate(invalid="ignore", divide="ignore"):
        if form == "diff":
            return A[a][st] - A[b][st]
        if form == "ratio":
            return A[a][st] / A[b][st]
        return (A[a][st] - A[b][st]) - 0.5 * (A[c][st] - A[b][st])


def scale(g, x):
    if GATES[g][2] != "ratio":
        return np.asarray(x, float)
    with np.errstate(invalid="ignore", divide="ignore"):
        x = np.asarray(x, float)
        return np.log(np.where(x > 0, x, np.nan))


def unscale(g, x):
    return math.exp(x) if GATES[g][2] == "ratio" and math.isfinite(x) else x


def holds(op, x, v):
    if not math.isfinite(x):
        return False
    return {">=": x >= v, ">": x > v, "<=": x <= v, "<": x < v}[op]


def draws(n_worlds, n, seed):
    rng = np.random.default_rng(seed)
    mult = {t: np.zeros((n, n_worlds[t])) for t in D.TEST_SETS}
    for b in range(n):
        for t in D.TEST_SETS:                      # main6 then extrap10, one generator: shared by all arms and replicates
            mult[t][b] = np.bincount(rng.integers(0, n_worlds[t], n_worlds[t]), minlength=n_worlds[t])
    return mult


def analyse(data, n, seed=SEED):
    K = data["main6"]["sums"]["R"].shape[0]
    arms = ("R", "E", "Z", "T", "P")
    allw = {t: np.ones(data[t]["counts"].shape[0]) for t in D.TEST_SETS}
    point = {t: {a: pooled(data[t]["sums"][a], data[t]["counts"], data[t]["eb"], list(range(K)), allw[t]) for a in arms} for t in D.TEST_SETS}
    per_k = {t: [{a: pooled(data[t]["sums"][a], data[t]["counts"], data[t]["eb"], [k], allw[t]) for a in arms} for k in range(K)]
             for t in D.TEST_SETS}
    mult = draws({t: data[t]["counts"].shape[0] for t in D.TEST_SETS}, n, seed)
    boot_arm = {t: {a: pooled(data[t]["sums"][a], data[t]["counts"], data[t]["eb"], list(range(K)), mult[t]) for a in arms} for t in D.TEST_SETS}
    p_bonf, p95 = 1 - ALPHA / (2 * M), 1 - ALPHA / 2
    q = {"bonf": t_quantile(p_bonf, K - 1) if K > 1 else z_quantile(p_bonf),
         "95": t_quantile(p95, K - 1) if K > 1 else z_quantile(p95)}
    out, boots = {}, {}
    for g, (tset, st, form, a, b, c, pt, (end, op, v), per_min) in GATES.items():
        theta = float(gate_value(g, point[tset]))
        tk = [float(gate_value(g, per_k[tset][k])) for k in range(K)]
        boot = np.asarray(gate_value(g, boot_arm[tset]), float)
        boots[g] = boot
        th, tks, bs = float(scale(g, theta)), scale(g, tk), scale(g, boot)
        row = {"point": theta, "per_replicate": tk}
        if math.isfinite(th) and np.all(np.isfinite(tks)) and np.all(np.isfinite(bs)):
            s_rep = sd1(tks) if K > 1 else 0.0
            se_w = sd1(bs)
            se = math.sqrt(s_rep ** 2 / K + se_w ** 2)
            row.update(s_rep=s_rep, se_w=se_w, se=se, q=q["bonf"],
                       bonferroni=[unscale(g, th - q["bonf"] * se), unscale(g, th + q["bonf"] * se)],
                       ci95=[unscale(g, th - q["95"] * se), unscale(g, th + q["95"] * se)])
        else:
            row.update(se=float("nan"), bonferroni=[float("nan")] * 2, ci95=[float("nan")] * 2)
        row["point_ok"] = math.isfinite(theta) and (pt is None or holds(pt[0], theta, pt[1]))
        row["interval_ok"] = holds(op, row["bonferroni"][0] if end == "lower" else row["bonferroni"][1], v)
        if per_min is not None:
            row["per_replicate_ok"] = all(holds(">=", x, per_min) for x in tk)
        row["passed"] = bool(row["point_ok"] and row["interval_ok"] and row.get("per_replicate_ok", True))
        out[g] = row
    return {"gates": out, "all_pass": all(r["passed"] for r in out.values()), "K": K,
            "q_bonf": q["bonf"], "q95": q["95"], "p_bonf": p_bonf}, boots, mult


def alt_se_w(data, n, seed=SEED + 1):
    """Sensitivity: se_w of GS and GZ-W if the worlds were NOT shared (redrawn per arm), or redrawn per replicate."""
    K = data["main6"]["sums"]["R"].shape[0]
    Wn = data["main6"]["counts"].shape[0]
    rng = np.random.default_rng(seed)
    d = data["main6"]
    res = {}
    for design in ("per-arm draws (unpaired)", "per-replicate draws (nested)"):
        vals = {"GS": [], "GZ-W": []}
        for _ in range(n):
            A = {}
            per_rep = [np.bincount(rng.integers(0, Wn, Wn), minlength=Wn) for _ in range(K)]
            for a in ("E", "R", "Z"):
                if design.startswith("per-arm"):
                    m = np.bincount(rng.integers(0, Wn, Wn), minlength=Wn).astype(float)
                    A[a] = pooled(d["sums"][a], d["counts"], d["eb"], list(range(K)), m)
                else:   # each replicate its own worlds (shared across arms within the replicate)
                    S = sum(per_rep[k] @ d["sums"][a][k].sum(0) for k in range(K))
                    C = sum(d["sums"][a].shape[1] * (per_rep[k] @ d["counts"].astype(float)) for k in range(K))
                    B = sum(d["sums"][a].shape[1] * (per_rep[k] @ d["eb"]) for k in range(K))
                    A[a] = {"D": 1 - S[0] / B, "wall_pillar": S[2] / C[2]}
            vals["GS"].append(A["E"]["D"] - A["R"]["D"])
            vals["GZ-W"].append(math.log(A["E"]["wall_pillar"] / A["Z"]["wall_pillar"]))
        res[design] = {g: sd1(v) for g, v in vals.items()}
    return res


def main():
    out_json, boot_dir = Path(sys.argv[1]), Path(sys.argv[2])
    boot_dir.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, cfg in D.CONFIGS.items():
        data = D.build(cfg)
        res, boots, mult = analyse(data, cfg["n"])
        np.savez(boot_dir / f"indep-{name.split()[0]}.npz", **{g: v for g, v in boots.items()})
        if name.startswith("C6"):
            res["alt_se_w"] = alt_se_w(data, 2000)
        result[name] = res
        g = res["gates"]
        print(f"{name}: K={res['K']} q_bonf={res['q_bonf']:.6f} q95={res['q95']:.6f} all_pass={res['all_pass']}")
        for k, r in g.items():
            print(f"   {k:5s} point {r['point']:+.6f} bonf [{r['bonferroni'][0]:+.6f}, {r['bonferroni'][1]:+.6f}] "
                  f"se {r['se']:.6f} passed {r['passed']}")
    out_json.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
    loaded = sorted(m for m in sys.modules if m.startswith("ainerzero"))
    print("ainerzero modules loaded by this script:", loaded)
    assert not any(m.endswith("s6.analysis") for m in sys.modules)


if __name__ == "__main__":
    main()
