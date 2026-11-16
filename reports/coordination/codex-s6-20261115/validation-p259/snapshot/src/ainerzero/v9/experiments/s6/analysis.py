#!/usr/bin/env python3
"""S6 phase 1 metrics, gates and intervals. DESIGN-r2 §4 is the authority.

Input, per test set ("main6", "extrap10"):
  sums[arm]  float [R_arm, N_net, W, 4]  next-velocity error sums per step kind (collision, graze,
                                         wall_pillar, free) of replicate k, network j, test world w;
  counts     int   [W, 4]                disk-steps per kind (the same for every network);
  eb         float [W]                   E-B baseline error sum on collision disk-steps.

Arms R E Z T P share the replicate count K (5 in the final run); G has at most K replicates (0..K_G-1)
and its replicate k shares the candidate pool of the others' replicate k. G is descriptive only.

Statistic of an arm on replicates ``reps`` and worlds ``worlds``: for every (replicate, network), pool
error sums and counts over the worlds (D = 1 - sum collision error / sum eb; kind mean = sum / count;
all = all sums / all counts), then average over the replicates and networks. Because counts and eb do
not depend on the network or replicate, this equals the ratio of sums pooled over replicates, networks
and worlds. A zero denominator gives NaN, and NaN fails a gate.

Intervals (DESIGN-r2 §4, after the r1 review: a bootstrap over 5 replicates under-covers):
  theta_hat  the gate statistic on all replicates and all worlds (ratio gates on the log scale);
  theta_k    the same on replicate k alone, all worlds;  s_rep = SD(theta_k), ddof 1;
  se_w       SD of the statistic over a paired world bootstrap (all replicates kept; the drawn worlds
             shared by every arm and replicate), N_BOOT draws;
  se         sqrt(s_rep^2 / K + se_w^2);
  bounds     theta_hat -/+ q * se, q the Student t quantile with K-1 degrees of freedom at 1 - alpha/(2m)
             (Bonferroni, m = 8) or 0.975 (95%); ratio bounds are exponentiated. With K = 1 there is no
             replicate layer: s_rep = 0 and q is the normal quantile (used only by the probe).

Pure NumPy.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

KINDS = ("collision", "graze", "wall_pillar", "free")
STATS = ("D", "collision", "graze", "wall_pillar", "free", "all")
GATE_ARMS = ("R", "E", "Z", "T", "P")
ARMS = GATE_ARMS + ("G",)
TEST_SETS = ("main6", "extrap10")
ALPHA = 0.05
N_BOOT = 10_000
SEED = 20261114

# DESIGN-r2 §4. point: (op, value) or None; interval: (end, op, value).
GATES: dict[str, dict[str, Any]] = {
    "GS":   {"set": "main6", "stat": "D", "form": "diff", "a": "E", "b": "R",
             "point": (">=", 0.03), "interval": ("lower", ">", 0.0), "per_replicate": 0.03},
    "GT":   {"set": "main6", "stat": "D", "form": "half_gain", "a": "E", "b": "R", "c": "T",
             "point": None, "interval": ("lower", ">", 0.0)},
    "GZ-D": {"set": "main6", "stat": "D", "form": "diff", "a": "E", "b": "Z",
             "point": (">=", -0.02), "interval": ("lower", ">", -0.04)},
    "GZ-W": {"set": "main6", "stat": "wall_pillar", "form": "ratio", "a": "E", "b": "Z",
             "point": ("<=", 0.95), "interval": ("upper", "<", 1.0)},
    "GK-A": {"set": "main6", "stat": "all", "form": "ratio", "a": "E", "b": "R",
             "point": ("<=", 1.10), "interval": ("upper", "<=", 1.20)},
    "GK-F": {"set": "main6", "stat": "free", "form": "ratio", "a": "E", "b": "Z",
             "point": ("<=", 1.10), "interval": ("upper", "<=", 1.20)},
    "GP":   {"set": "main6", "stat": "D", "form": "diff", "a": "P", "b": "R",
             "point": (">=", 0.03), "interval": ("lower", ">", 0.0)},
    "GX":   {"set": "extrap10", "stat": "D", "form": "diff", "a": "E", "b": "R",
             "point": (">=", 0.02), "interval": ("lower", ">", 0.0)},
}
M = len(GATES)

_OPS = {">=": np.greater_equal, ">": np.greater, "<=": np.less_equal, "<": np.less}


# --- distributions (no SciPy) --------------------------------------------------------------------------------
def t_cdf(x: float, df: int) -> float:
    """Student t CDF for a positive integer number of degrees of freedom (closed-form series)."""
    if df < 1 or int(df) != df:
        raise ValueError("df must be a positive integer")
    th = math.atan(x / math.sqrt(df))
    c2, s = math.cos(th) ** 2, math.sin(th)
    if df % 2 == 1:
        acc, term = 0.0, math.cos(th)
        if df > 1:
            acc = term
            for j in range(1, (df - 3) // 2 + 1):
                term *= c2 * (2 * j) / (2 * j + 1)
                acc += term
        return 0.5 + (th + s * acc) / math.pi if df > 1 else 0.5 + th / math.pi
    acc, term = 1.0, 1.0
    for j in range(1, (df - 2) // 2 + 1):
        term *= c2 * (2 * j - 1) / (2 * j)
        acc += term
    return 0.5 + 0.5 * s * acc


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _invert(cdf, p: float) -> float:
    if not 0.5 < p < 1:
        raise ValueError("p must lie in (0.5, 1)")
    lo, hi = 0.0, 1.0
    while cdf(hi) < p:
        hi *= 2
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) < p else (lo, mid)
    return (lo + hi) / 2


def t_ppf(p: float, df: int) -> float:
    return _invert(lambda x: t_cdf(x, df), p)


def norm_ppf(p: float) -> float:
    return _invert(norm_cdf, p)


# --- statistics ------------------------------------------------------------------------------------------
def _per_rep_net(S: np.ndarray, C: np.ndarray, B: np.ndarray) -> dict[str, np.ndarray]:
    """S [..., 4] pooled sums, C [..., 4] pooled counts, B [...] pooled eb (broadcastable). -> stat arrays."""
    with np.errstate(invalid="ignore", divide="ignore"):
        out = {"D": 1.0 - S[..., 0] / np.where(B != 0, B, np.nan)}
        Cn = np.where(C != 0, C, np.nan)
        for c, name in enumerate(KINDS):
            out[name] = S[..., c] / Cn[..., c]
        tot = C.sum(-1)
        out["all"] = S.sum(-1) / np.where(tot != 0, tot, np.nan)
    return out


def stats(sums: np.ndarray, counts: np.ndarray, eb: np.ndarray, reps, worlds) -> dict[str, float]:
    """One arm on a multiset of replicate ids ``reps`` and world ids ``worlds`` (repeats count)."""
    sums, counts, eb = np.asarray(sums, float), np.asarray(counts, float), np.asarray(eb, float)
    reps, worlds = np.asarray(reps, dtype=np.int64), np.asarray(worlds, dtype=np.int64)
    S = sums[:, :, worlds].sum(2)                       # [R, N, 4]
    C = counts[worlds].sum(0)                           # [4]
    B = eb[worlds].sum()
    per = _per_rep_net(S[reps], C[None, None], np.asarray(B)[None, None])
    return {k: float(v.mean()) for k, v in per.items()}


def _gate_value(spec: dict, A: dict[str, dict[str, Any]]):
    st = spec["stat"]
    a, b = A[spec["a"]][st], A[spec["b"]][st]
    with np.errstate(invalid="ignore", divide="ignore"):
        if spec["form"] == "diff":
            return a - b
        if spec["form"] == "ratio":
            return a / b
        if spec["form"] == "half_gain":
            c = A[spec["c"]][st]
            return (a - b) - 0.5 * (c - b)
    raise ValueError(spec["form"])


def _to_scale(spec: dict, x):
    if spec["form"] != "ratio":
        return x
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(np.where(np.asarray(x) > 0, x, np.nan))


def _from_scale(spec: dict, x: float) -> float:
    return float(math.exp(x)) if spec["form"] == "ratio" and math.isfinite(x) else float(x)


def _replicate_count(data: dict) -> int:
    ks = {data[t]["sums"][arm].shape[0] for t in TEST_SETS for arm in GATE_ARMS}
    if len(ks) != 1:
        raise ValueError(f"arms {GATE_ARMS} must have the same replicate count, got {sorted(ks)}")
    K = ks.pop()
    if K < 1:
        raise ValueError("no replicates")
    for t in TEST_SETS:
        if "G" in data[t]["sums"] and data[t]["sums"]["G"].shape[0] > K:
            raise ValueError("G has more replicates than the gate arms")
        W_ = data[t]["counts"].shape[0]
        for arm, s in data[t]["sums"].items():
            if s.ndim != 4 or s.shape[2] != W_ or s.shape[3] != 4:
                raise ValueError(f"{t}/{arm}: sums must be [R, N, W={W_}, 4], got {s.shape}")
        if data[t]["eb"].shape != (W_,):
            raise ValueError(f"{t}: eb must have one entry per world")
    return K


def point_stats(data: dict, set_name: str, reps=None) -> dict[str, dict[str, float]]:
    """Each gate arm on all worlds of ``set_name`` and the replicates ``reps`` (default: all)."""
    d = data[set_name]
    W_ = d["counts"].shape[0]
    K = _replicate_count(data)
    reps = np.arange(K) if reps is None else np.asarray(reps)
    return {arm: stats(d["sums"][arm], d["counts"], d["eb"], reps, np.arange(W_)) for arm in GATE_ARMS}


# --- the world bootstrap -------------------------------------------------------------------------------------------
def world_draws(n_worlds: dict[str, int], n: int, seed: int) -> dict[str, np.ndarray]:
    """Per draw, in this order: the main6 world ids, then the extrap10 world ids, with replacement from one
    generator. Shared by every arm and replicate."""
    rng = np.random.default_rng(seed)
    out = {t: np.empty((n, n_worlds[t]), dtype=np.int64) for t in TEST_SETS}
    for b in range(n):
        for t in TEST_SETS:
            out[t][b] = rng.integers(0, n_worlds[t], n_worlds[t])
    return out


def _multiplicity(idx: np.ndarray, size: int) -> np.ndarray:
    out = np.zeros((idx.shape[0], size))
    for b in range(idx.shape[0]):
        out[b] = np.bincount(idx[b], minlength=size)
    return out


def world_bootstrap(data: dict, n: int = N_BOOT, seed: int = SEED) -> dict[str, np.ndarray]:
    """Per gate, n draws of its statistic with all replicates kept and the test worlds resampled (paired)."""
    _replicate_count(data)
    n_worlds = {t: data[t]["counts"].shape[0] for t in TEST_SETS}
    draws = world_draws(n_worlds, n, seed)
    arm_stats = {}
    for t in TEST_SETS:
        d = data[t]
        Mw = _multiplicity(draws[t], n_worlds[t])                         # [n, W]
        C = Mw @ np.asarray(d["counts"], float)                           # [n, 4]
        B = Mw @ np.asarray(d["eb"], float)                               # [n]
        arm_stats[t] = {}
        for arm in GATE_ARMS:
            S = np.einsum("bw,knwc->bknc", Mw, np.asarray(d["sums"][arm], float))   # [n, K, N, 4]
            per = _per_rep_net(S, C[:, None, None, :], B[:, None, None])           # [n, K, N]
            arm_stats[t][arm] = {k: v.mean((1, 2)) for k, v in per.items()}
    return {g: _gate_value(spec, arm_stats[spec["set"]]) for g, spec in GATES.items()}


# --- decisions -------------------------------------------------------------------------------------------------------
def _holds(op: str, x: float, v: float) -> bool:
    return bool(math.isfinite(x) and _OPS[op](x, v))


def interval(spec: dict, theta_hat: float, theta_k: list[float], boot: np.ndarray, p: float) -> tuple[float, float, dict]:
    """Two-sided interval at level p per side (p = 1 - alpha/2 or 1 - alpha/(2m)) on the gate's scale."""
    th = float(_to_scale(spec, theta_hat))
    tk = np.asarray(_to_scale(spec, np.asarray(theta_k, float)), float)
    bs = np.asarray(_to_scale(spec, boot), float)
    K = len(tk)
    if not (math.isfinite(th) and np.all(np.isfinite(tk)) and np.all(np.isfinite(bs))):
        return float("nan"), float("nan"), {"se": float("nan")}
    s_rep = float(np.std(tk, ddof=1)) if K > 1 else 0.0
    se_w = float(np.std(bs, ddof=1))
    se = math.sqrt(s_rep ** 2 / K + se_w ** 2)
    q = t_ppf(p, K - 1) if K > 1 else norm_ppf(p)
    lo, hi = _from_scale(spec, th - q * se), _from_scale(spec, th + q * se)
    return lo, hi, {"s_rep": s_rep, "se_w": se_w, "se": se, "q": q, "df": K - 1 if K > 1 else None}


def decide(data: dict, n: int = N_BOOT, seed: int = SEED) -> dict[str, Any]:
    K = _replicate_count(data)
    boot = world_bootstrap(data, n, seed)
    points = {t: point_stats(data, t) for t in TEST_SETS}
    per_rep = {t: [point_stats(data, t, [k]) for k in range(K)] for t in TEST_SETS}
    p_bonf, p_95 = 1 - ALPHA / (2 * M), 1 - ALPHA / 2
    out = {}
    for g, spec in GATES.items():
        x = float(_gate_value(spec, points[spec["set"]]))
        tk = [float(_gate_value(spec, per_rep[spec["set"]][k])) for k in range(K)]
        lo95, hi95, _ = interval(spec, x, tk, boot[g], p_95)
        lo, hi, parts = interval(spec, x, tk, boot[g], p_bonf)
        point_ok = math.isfinite(x) and (spec["point"] is None or _holds(spec["point"][0], x, spec["point"][1]))
        end, op, v = spec["interval"]
        interval_ok = _holds(op, lo if end == "lower" else hi, v)
        row = {"point": x, "per_replicate": tk, "ci95": [lo95, hi95], "bonferroni": [lo, hi], **parts,
               "point_ok": bool(point_ok), "interval_ok": interval_ok}
        if "per_replicate" in spec:
            row["per_replicate_ok"] = all(_holds(">=", p, spec["per_replicate"]) for p in tk)
        row["passed"] = bool(row["point_ok"] and row["interval_ok"] and row.get("per_replicate_ok", True))
        out[g] = row
    return {"gates": out, "all_pass": all(r["passed"] for r in out.values()), "m": M, "alpha": ALPHA,
            "n_boot": n, "seed": seed, "replicates": K, "levels": {"bonferroni": p_bonf, "ci95": p_95}}


def describe(data: dict) -> dict[str, Any]:
    """Point values only (all replicates, all worlds); D(E)-D(G) on G's replicates (0..K_G-1) only."""
    K = _replicate_count(data)
    out = {}
    for t in TEST_SETS:
        d = data[t]
        allw = np.arange(d["counts"].shape[0])
        arms = {arm: stats(d["sums"][arm], d["counts"], d["eb"], np.arange(d["sums"][arm].shape[0]), allw)
                for arm in d["sums"]}
        row = {"arms": arms, "D(E)-D(T)": arms["E"]["D"] - arms["T"]["D"], "D(P)-D(E)": arms["P"]["D"] - arms["E"]["D"]}
        if "G" in d["sums"]:
            kg = d["sums"]["G"].shape[0]
            e_on_g = stats(d["sums"]["E"], d["counts"], d["eb"], np.arange(kg), allw)
            row["D(E)-D(G)"] = e_on_g["D"] - arms["G"]["D"]
            row["G_replicates"] = kg
        with np.errstate(invalid="ignore", divide="ignore"):
            for base in ("R", "Z"):
                row[f"E/{base}"] = {k: arms["E"][k] / arms[base][k] for k in STATS if k != "D"}
        out[t] = row
    out["replicates"] = K
    return out
