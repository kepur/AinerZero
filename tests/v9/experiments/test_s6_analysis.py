"""S6 metrics, gates and intervals (pure NumPy). DESIGN-r2 §4."""
from __future__ import annotations

import ast
import inspect
import math

import numpy as np
import pytest

from ainerzero.v9.experiments.s6 import analysis as AN

ERR = np.array([0.30, 0.05, 0.80, 0.012])        # per-kind mean error of a reference learner
FACT = {"R": [1.00, 1.00, 1.00, 1.00], "E": [0.75, 1.10, 0.90, 1.30], "Z": [0.76, 1.00, 1.00, 1.28],
        "T": [0.72, 1.20, 1.10, 1.50], "P": [0.76, 1.10, 0.92, 1.30], "G": [0.65, 1.00, 1.05, 0.90]}


def make_data(K=5, N=3, W=(20, 10), KG=3, seed=0, fact=FACT, noise=0.03):
    rng = np.random.default_rng(seed)
    data = {}
    for t, Wt in zip(AN.TEST_SETS, W):
        counts = rng.integers(5, 40, (Wt, 4)) * np.array([1, 4, 2, 60])
        eb = counts[:, 0] * 0.45 * rng.uniform(0.9, 1.1, Wt)
        sums = {}
        for arm in AN.ARMS:
            R = KG if arm == "G" else K
            f = np.asarray(fact[arm])
            sums[arm] = counts[None, None] * ERR * f * rng.lognormal(0, noise, (R, N, Wt, 4))
        data[t] = {"sums": sums, "counts": counts, "eb": eb}
    return data


# --- distributions ------------------------------------------------------------------------------------------
@pytest.mark.parametrize("p,df,want", [(0.975, 1, 12.7062), (0.975, 2, 4.30265), (0.975, 3, 3.18245),
                                       (0.975, 4, 2.77645), (1 - 0.025 / 8, 4, 5.26106), (0.975, 5, 2.57058),
                                       (0.975, 7, 2.36462), (0.975, 9, 2.26216), (0.975, 10, 2.22814),
                                       (0.975, 30, 2.04227)])
def test_t_quantiles(p, df, want):
    assert AN.t_ppf(p, df) == pytest.approx(want, abs=2e-5)


def test_normal_quantile_and_t_limit():
    assert AN.norm_ppf(0.975) == pytest.approx(1.959964, abs=1e-6)
    assert AN.t_ppf(0.975, 400) == pytest.approx(1.965912, abs=1e-5)       # tends to the normal 1.96
    assert AN.t_cdf(0.0, 3) == pytest.approx(0.5) and AN.t_cdf(1.0, 1) == pytest.approx(0.75)
    with pytest.raises(ValueError):
        AN.t_cdf(1.0, 2.5)


# --- statistics ----------------------------------------------------------------------------------------------
def test_stats_by_hand():
    sums = np.array([[[[2.0, 1.0, 3.0, 4.0], [1.0, 1.0, 1.0, 2.0]],
                      [[4.0, 2.0, 3.0, 2.0], [3.0, 1.0, 1.0, 4.0]]]])        # [1 rep, 2 nets, 2 worlds, 4]
    counts = np.array([[2, 2, 3, 8], [1, 2, 1, 4]])
    eb = np.array([4.0, 2.0])
    s = AN.stats(sums, counts, eb, [0], [0, 1])
    # net 0: sums (3, 2, 4, 6), net 1: (7, 3, 4, 6); counts (3, 4, 4, 12); eb 6
    assert s["D"] == pytest.approx(((1 - 3 / 6) + (1 - 7 / 6)) / 2)
    assert s["collision"] == pytest.approx((3 / 3 + 7 / 3) / 2)
    assert s["graze"] == pytest.approx((2 / 4 + 3 / 4) / 2)
    assert s["free"] == pytest.approx(0.5)
    assert s["all"] == pytest.approx((15 / 23 + 20 / 23) / 2)
    # world 0 twice, world 1 never
    s2 = AN.stats(sums, counts, eb, [0], [0, 0])
    assert s2["D"] == pytest.approx(((1 - 4 / 8) + (1 - 8 / 8)) / 2)


def test_replicates_weighted_by_multiplicity_and_pooled_equivalence():
    d = make_data(K=3)["main6"]
    a = AN.stats(d["sums"]["E"], d["counts"], d["eb"], [0, 0, 2], np.arange(20))
    b = [AN.stats(d["sums"]["E"][[k]], d["counts"], d["eb"], [0], np.arange(20)) for k in (0, 0, 2)]
    assert a["D"] == pytest.approx(np.mean([x["D"] for x in b]))
    # equals the ratio of sums pooled over replicates, networks and worlds
    S = d["sums"]["E"][[0, 0, 2]].sum((0, 1, 2))
    nrn = 3 * d["sums"]["E"].shape[1]
    assert a["D"] == pytest.approx(1 - S[0] / (nrn * d["eb"].sum()))
    assert a["wall_pillar"] == pytest.approx(S[2] / (nrn * d["counts"][:, 2].sum()))
    assert a["all"] == pytest.approx(S.sum() / (nrn * d["counts"].sum()))


def test_stats_matches_the_exploration_arithmetic():
    """explore_s6a.evaluate: mean = sums / cnt per kind, all = sums.sum() / cnt.sum(), D = 1 - sums[0] / eb_coll."""
    d = make_data(K=1, N=1)["main6"]
    s = AN.stats(d["sums"]["E"], d["counts"], d["eb"], [0], np.arange(20))
    sums, cnt, eb = d["sums"]["E"][0, 0].sum(0), d["counts"].sum(0), d["eb"].sum()
    assert s["D"] == pytest.approx(1 - sums[0] / eb)
    for c, k in enumerate(AN.KINDS):
        assert s[k] == pytest.approx(sums[c] / cnt[c])
    assert s["all"] == pytest.approx(sums.sum() / cnt.sum())


def test_zero_denominators_give_nan():
    d = make_data(K=2, KG=2)
    d["main6"]["counts"][:, 2] = 0
    d["main6"]["eb"][:] = 0
    s = AN.point_stats(d, "main6")["E"]
    assert math.isnan(s["D"]) and math.isnan(s["wall_pillar"]) and math.isfinite(s["free"])


# --- the world bootstrap -------------------------------------------------------------------------------------------
def test_world_draws_order_and_reproducibility():
    a = AN.world_draws({"main6": 7, "extrap10": 3}, 4, 11)
    rng = np.random.default_rng(11)
    for b in range(4):
        assert a["main6"][b].tolist() == rng.integers(0, 7, 7).tolist()
        assert a["extrap10"][b].tolist() == rng.integers(0, 3, 3).tolist()
    b = AN.world_draws({"main6": 7, "extrap10": 3}, 4, 11)
    assert all(np.array_equal(a[t], b[t]) for t in a)
    c = AN.world_draws({"main6": 7, "extrap10": 3}, 4, 12)
    assert not np.array_equal(a["main6"], c["main6"])


def test_bootstrap_is_paired_across_arms():
    d = make_data()
    for t in AN.TEST_SETS:
        d[t]["sums"]["Z"] = d[t]["sums"]["E"] * 1.25         # every disk-step error of Z is 1.25 x E's
        d[t]["sums"]["R"] = d[t]["sums"]["E"].copy()          # R identical to E
    boot = AN.world_bootstrap(d, n=300, seed=3)
    assert np.allclose(boot["GZ-W"], 1 / 1.25) and np.allclose(boot["GK-F"], 1 / 1.25)
    assert np.allclose(boot["GS"], 0.0) and np.allclose(boot["GX"], 0.0) and np.allclose(boot["GK-A"], 1.0)


def test_bootstrap_draws_equal_stats_on_the_drawn_worlds():
    d = make_data(K=3)
    n_worlds = {t: d[t]["counts"].shape[0] for t in AN.TEST_SETS}
    draws = AN.world_draws(n_worlds, 5, 7)
    boot = AN.world_bootstrap(d, n=5, seed=7)
    for b in range(5):
        A = {arm: AN.stats(d["main6"]["sums"][arm], d["main6"]["counts"], d["main6"]["eb"], np.arange(3), draws["main6"][b])
             for arm in AN.GATE_ARMS}
        assert boot["GS"][b] == pytest.approx(A["E"]["D"] - A["R"]["D"])
        assert boot["GT"][b] == pytest.approx((A["E"]["D"] - A["R"]["D"]) - 0.5 * (A["T"]["D"] - A["R"]["D"]))
        assert boot["GZ-W"][b] == pytest.approx(A["E"]["wall_pillar"] / A["Z"]["wall_pillar"])
        X = {arm: AN.stats(d["extrap10"]["sums"][arm], d["extrap10"]["counts"], d["extrap10"]["eb"], np.arange(3), draws["extrap10"][b])
             for arm in ("E", "R")}
        assert boot["GX"][b] == pytest.approx(X["E"]["D"] - X["R"]["D"])


# --- intervals --------------------------------------------------------------------------------------------------------
def test_interval_t_on_replicates_plus_world_bootstrap():
    spec = AN.GATES["GS"]
    tk = [0.05, 0.07, 0.06, 0.09, 0.08]
    boot = np.array([0.069, 0.071] * 50)
    se_w = np.std(boot, ddof=1)
    lo, hi, parts = AN.interval(spec, 0.07, tk, boot, 0.975)
    se = math.sqrt(np.std(tk, ddof=1) ** 2 / 5 + se_w ** 2)
    assert parts["se"] == pytest.approx(se) and parts["df"] == 4
    assert lo == pytest.approx(0.07 - 2.77645 * se, abs=1e-6) and hi == pytest.approx(0.07 + 2.77645 * se, abs=1e-6)


def test_ratio_intervals_on_the_log_scale():
    spec = AN.GATES["GZ-W"]
    tk = [0.88, 0.92, 0.90, 0.95, 0.86]
    boot = np.full(10, 0.9)
    lo, hi, parts = AN.interval(spec, 0.9, tk, boot, 1 - 0.025 / 8)
    s = np.std(np.log(tk), ddof=1)
    q = AN.t_ppf(1 - 0.025 / 8, 4)
    assert lo == pytest.approx(0.9 * math.exp(-q * s / math.sqrt(5)))
    assert hi == pytest.approx(0.9 * math.exp(q * s / math.sqrt(5)))
    assert lo * hi == pytest.approx(0.81)                    # symmetric on the log scale


def test_single_replicate_uses_the_normal_quantile():
    lo, hi, parts = AN.interval(AN.GATES["GS"], 0.05, [0.05], np.array([0.04, 0.06] * 10), 0.975)
    assert parts["s_rep"] == 0.0 and parts["df"] is None
    assert parts["q"] == pytest.approx(AN.norm_ppf(0.975))


def test_nan_anywhere_fails():
    lo, hi, parts = AN.interval(AN.GATES["GS"], 0.05, [0.05, float("nan")], np.zeros(5), 0.975)
    assert math.isnan(lo) and math.isnan(hi)
    d = make_data()
    d["main6"]["eb"][:] = 0
    res = AN.decide(d, n=200)
    for g in ("GS", "GT", "GZ-D", "GP"):
        assert not res["gates"][g]["passed"]
    assert res["gates"]["GX"]["passed"] in (True, False) and not res["all_pass"]


# --- gates ---------------------------------------------------------------------------------------------------------------
def test_gate_table_is_the_design():
    want = {
        "GS": ("main6", "D", "diff", "E", "R", (">=", 0.03), ("lower", ">", 0.0)),
        "GT": ("main6", "D", "half_gain", "E", "R", None, ("lower", ">", 0.0)),
        "GZ-D": ("main6", "D", "diff", "E", "Z", (">=", -0.02), ("lower", ">", -0.04)),
        "GZ-W": ("main6", "wall_pillar", "ratio", "E", "Z", ("<=", 0.95), ("upper", "<", 1.0)),
        "GK-A": ("main6", "all", "ratio", "E", "R", ("<=", 1.10), ("upper", "<=", 1.20)),
        "GK-F": ("main6", "free", "ratio", "E", "Z", ("<=", 1.10), ("upper", "<=", 1.20)),
        "GP": ("main6", "D", "diff", "P", "R", (">=", 0.03), ("lower", ">", 0.0)),
        "GX": ("extrap10", "D", "diff", "E", "R", (">=", 0.02), ("lower", ">", 0.0)),
    }
    got = {g: (s["set"], s["stat"], s["form"], s["a"], s["b"], s["point"], s["interval"]) for g, s in AN.GATES.items()}
    assert got == want
    assert AN.GATES["GT"]["c"] == "T" and AN.GATES["GS"]["per_replicate"] == 0.03
    assert AN.M == 8


def test_strict_and_non_strict_boundaries():
    assert not AN._holds("<", 1.0, 1.0) and AN._holds("<=", 1.20, 1.20)
    assert not AN._holds(">", 0.0, 0.0) and AN._holds(">=", 0.03, 0.03)
    assert not AN._holds(">=", float("nan"), 0.0)


def test_decide_on_synthetic_effects():
    res = AN.decide(make_data(), n=400)
    g = res["gates"]
    assert res["m"] == 8 and res["replicates"] == 5 and res["levels"]["bonferroni"] == pytest.approx(1 - 0.025 / 8)
    assert g["GS"]["passed"] and g["GP"]["passed"] and g["GX"]["passed"] and g["GT"]["passed"]
    assert g["GZ-W"]["point"] == pytest.approx(0.90, abs=0.02) and g["GZ-W"]["passed"]
    assert g["GK-F"]["point"] == pytest.approx(1.30 / 1.28, abs=0.02)
    for row in g.values():
        assert row["bonferroni"][0] <= row["ci95"][0] <= row["point"] <= row["ci95"][1] <= row["bonferroni"][1]
        assert len(row["per_replicate"]) == 5


def test_gt_formula():
    d = make_data()
    A = AN.point_stats(d, "main6")
    want = (A["E"]["D"] - A["R"]["D"]) - 0.5 * (A["T"]["D"] - A["R"]["D"])
    assert AN.decide(d, n=100)["gates"]["GT"]["point"] == pytest.approx(want)


def test_gs_needs_every_replicate_at_least_003():
    d = make_data(noise=0.005)
    d["main6"]["sums"]["E"][2] = d["main6"]["sums"]["R"][2] * 0.99        # replicate 2: E barely beats R
    g = AN.decide(d, n=300)["gates"]["GS"]
    assert g["point_ok"] and min(g["per_replicate"]) < 0.03 and not g["per_replicate_ok"] and not g["passed"]


def test_gx_reads_the_extrapolation_set_only():
    d = make_data()
    before = AN.decide(d, n=100)["gates"]
    d["extrap10"]["sums"]["E"] = d["extrap10"]["sums"]["R"].copy()
    after = AN.decide(d, n=100)["gates"]
    assert after["GX"]["point"] == pytest.approx(0.0) and not after["GX"]["passed"]
    for gname in ("GS", "GT", "GZ-D", "GZ-W", "GK-A", "GK-F", "GP"):
        assert after[gname]["point"] == pytest.approx(before[gname]["point"])


def test_g_is_descriptive_and_paired_on_its_replicates():
    d = make_data()
    base = AN.decide(d, n=100)
    d2 = make_data();
    for t in AN.TEST_SETS:
        d2[t]["sums"]["G"] = d2[t]["sums"]["G"] * 3.0
    assert AN.decide(d2, n=100)["gates"] == base["gates"]
    desc = AN.describe(d)["main6"]
    e3 = AN.stats(d["main6"]["sums"]["E"], d["main6"]["counts"], d["main6"]["eb"], [0, 1, 2], np.arange(20))
    assert desc["D(E)-D(G)"] == pytest.approx(e3["D"] - desc["arms"]["G"]["D"]) and desc["G_replicates"] == 3
    assert desc["E/Z"]["wall_pillar"] == pytest.approx(desc["arms"]["E"]["wall_pillar"] / desc["arms"]["Z"]["wall_pillar"])


def test_shape_and_replicate_checks():
    d = make_data()
    d["main6"]["sums"]["P"] = d["main6"]["sums"]["P"][:4]
    with pytest.raises(ValueError, match="same replicate count"):
        AN.decide(d, n=10)
    d = make_data(KG=6)
    with pytest.raises(ValueError, match="G has more"):
        AN.decide(d, n=10)
    d = make_data()
    d["extrap10"]["eb"] = d["extrap10"]["eb"][:-1]
    with pytest.raises(ValueError, match="eb"):
        AN.decide(d, n=10)


def test_works_with_one_and_two_replicates():
    for K in (1, 2):
        res = AN.decide(make_data(K=K, KG=1), n=100)
        assert res["replicates"] == K and set(res["gates"]) == set(AN.GATES)


def test_module_is_pure_numpy():
    tree = ast.parse(inspect.getsource(AN))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mods.add(node.module or "")
    assert not any("mlx" in m or "scipy" in m for m in mods)


# --- end to end, against an independent formula (DESIGN-r2 §4; the r1 review's must-fix 1) -------------------------
def paired_data(K=5, N=3, W=(20, 10), seed=3, rep_sd=0.03):
    """Like make_data, plus a per-replicate effect shared by every arm of that replicate (a common candidate
    pool), so pairing by replicate matters."""
    d = make_data(K=K, N=N, W=W, seed=seed)
    rng = np.random.default_rng(seed + 100)
    shared = rng.lognormal(0, rep_sd, (K, 4))                    # replicate k's pool effect, all arms
    for t in AN.TEST_SETS:
        for arm in AN.ARMS:
            R = d[t]["sums"][arm].shape[0]
            d[t]["sums"][arm] = d[t]["sums"][arm] * shared[:R, None, None, :]
    return d


def _pooled(d, arm, reps, worlds):
    """Ratio of sums pooled over the given replicates (with multiplicity), all networks and the given worlds."""
    S = sum(d["sums"][arm][k][:, worlds].sum((0, 1)) for k in reps)
    nrn = len(reps) * d["sums"][arm].shape[1]
    C = d["counts"][worlds].sum(0) * nrn
    out = {"D": 1 - S[0] / (d["eb"][worlds].sum() * nrn), "all": S.sum() / C.sum()}
    out.update({k: S[c] / C[c] for c, k in enumerate(AN.KINDS)})
    return out


def _value(g, A):
    st = {"GS": "D", "GT": "D", "GZ-D": "D", "GP": "D", "GX": "D", "GZ-W": "wall_pillar", "GK-A": "all", "GK-F": "free"}[g]
    a, b = {"GS": ("E", "R"), "GT": ("E", "R"), "GZ-D": ("E", "Z"), "GZ-W": ("E", "Z"), "GK-A": ("E", "R"),
            "GK-F": ("E", "Z"), "GP": ("P", "R"), "GX": ("E", "R")}[g]
    if g == "GT":
        return (A["E"][st] - A["R"][st]) - 0.5 * (A["T"][st] - A["R"][st])
    return A[a][st] / A[b][st] if g in ("GZ-W", "GK-A", "GK-F") else A[a][st] - A[b][st]


# DESIGN-r2 §4, typed out here rather than read from AN.GATES
POINT = {"GS": (">=", 0.03), "GT": None, "GZ-D": (">=", -0.02), "GZ-W": ("<=", 0.95), "GK-A": ("<=", 1.10),
         "GK-F": ("<=", 1.10), "GP": (">=", 0.03), "GX": (">=", 0.02)}
INTERVAL = {"GS": ("lower", ">", 0.0), "GT": ("lower", ">", 0.0), "GZ-D": ("lower", ">", -0.04), "GZ-W": ("upper", "<", 1.0),
            "GK-A": ("upper", "<=", 1.20), "GK-F": ("upper", "<=", 1.20), "GP": ("lower", ">", 0.0), "GX": ("lower", ">", 0.0)}
_CMP = {">": lambda a, b: a > b, "<": lambda a, b: a < b, ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b}
NEAR_MISS = {**FACT, "E": [0.75, 1.10, 0.97 * 1.00, 1.30], "P": [0.97, 1.10, 0.92, 1.30]}   # E/Z wall 0.97, D(P)-D(R) 0.02


@pytest.mark.parametrize("case", ["healthy3", "healthy8", "near_miss"])
def test_decide_matches_an_independent_computation(case):
    if case == "near_miss":
        d = make_data(seed=5, fact=NEAR_MISS, noise=0.004)
    else:
        d = paired_data(seed=int(case[-1]))
    n = 300
    res = AN.decide(d, n=n, seed=11)["gates"]
    K = 5
    nw = {t: d[t]["counts"].shape[0] for t in AN.TEST_SETS}
    draws = AN.world_draws(nw, n, 11)
    Q = {"bonf": 5.261057575066, "95": 2.776445105198}            # t(4, 1 - 0.025/8), t(4, 0.975)
    ratio = {"GZ-W", "GK-A", "GK-F"}
    decisions = {}
    for g in AN.GATES:
        t = "extrap10" if g == "GX" else "main6"
        allw = np.arange(nw[t])
        f = (lambda x: math.log(x)) if g in ratio else (lambda x: x)
        point = _value(g, {arm: _pooled(d[t], arm, range(K), allw) for arm in AN.GATE_ARMS})
        tk = [_value(g, {arm: _pooled(d[t], arm, [k], allw) for arm in AN.GATE_ARMS}) for k in range(K)]
        boot = [_value(g, {arm: _pooled(d[t], arm, range(K), draws[t][b]) for arm in AN.GATE_ARMS}) for b in range(n)]
        s_rep = np.std([f(x) for x in tk], ddof=1)
        se_w = np.std([f(x) for x in boot], ddof=1)
        se = math.sqrt(s_rep ** 2 / K + se_w ** 2)
        back = (lambda x: math.exp(x)) if g in ratio else (lambda x: x)
        row = res[g]
        assert row["point"] == pytest.approx(point, abs=1e-12)
        assert row["per_replicate"] == pytest.approx(tk, abs=1e-12)
        assert row["s_rep"] == pytest.approx(s_rep, abs=1e-12) and row["se_w"] == pytest.approx(se_w, abs=1e-12)
        assert row["q"] == pytest.approx(Q["bonf"], abs=1e-9)
        assert row["bonferroni"] == pytest.approx([back(f(point) - Q["bonf"] * se), back(f(point) + Q["bonf"] * se)], abs=1e-9)
        assert row["ci95"] == pytest.approx([back(f(point) - Q["95"] * se), back(f(point) + Q["95"] * se)], abs=1e-9)
        end, op, v = INTERVAL[g]
        bound = row["bonferroni"][0] if end == "lower" else row["bonferroni"][1]
        interval_ok = _CMP[op](bound, v)
        point_ok = POINT[g] is None or _CMP[POINT[g][0]](point, POINT[g][1])
        per_rep_ok = all(x >= 0.03 for x in tk) if g == "GS" else True
        assert row["interval_ok"] == interval_ok and row["point_ok"] == point_ok
        assert row.get("per_replicate_ok", True) == per_rep_ok
        assert row["passed"] == (interval_ok and point_ok and per_rep_ok)
        decisions[g] = (point_ok, interval_ok, row["passed"])
    if case == "near_miss":                     # the check bites: point thresholds decide here, intervals do not
        assert decisions["GZ-W"] == (False, True, False) and decisions["GP"] == (False, True, False)
    else:
        assert all(v[2] for v in decisions.values())


def test_pairing_by_replicate_changes_the_answer():
    """With a strong shared replicate effect, pairing removes it from s_rep: the paired s_rep of a diff gate
    is far below what unpaired replicates would give."""
    d = paired_data(seed=3, rep_sd=0.15)
    row = AN.decide(d, n=200, seed=11)["gates"]["GZ-W"]
    allw = np.arange(20)
    unpaired = [_pooled(d["main6"], "E", [k], allw)["wall_pillar"] / _pooled(d["main6"], "Z", [(k + 1) % 5], allw)["wall_pillar"]
                for k in range(5)]
    assert row["s_rep"] < 0.5 * np.std(np.log(unpaired), ddof=1)
