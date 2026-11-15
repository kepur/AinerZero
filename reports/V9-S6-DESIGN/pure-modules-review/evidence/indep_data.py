"""P256 review: synthetic data for the independent gate recomputation. Does not import analysis.py.

``my_make_data`` restates tests/v9/experiments/test_s6_analysis.py::make_data (same draws, same order);
author_decide.py checks the arrays are bit-for-bit those of the test's make_data. ``paired_data`` adds a
replicate effect shared by every arm of replicate k (the real design pairs arms by replicate), which the
test's make_data does not have."""
from __future__ import annotations

import numpy as np

TEST_SETS = ("main6", "extrap10")
ARMS = ("R", "E", "Z", "T", "P", "G")
ERR = np.array([0.30, 0.05, 0.80, 0.012])
FACT = {"R": [1.00, 1.00, 1.00, 1.00], "E": [0.75, 1.10, 0.90, 1.30], "Z": [0.76, 1.00, 1.00, 1.28],
        "T": [0.72, 1.20, 1.10, 1.50], "P": [0.76, 1.10, 0.92, 1.30], "G": [0.65, 1.00, 1.05, 0.90]}


def my_make_data(K=5, N=3, W=(20, 10), KG=3, seed=0, fact=FACT, noise=0.03):
    rng = np.random.default_rng(seed)
    data = {}
    for t, Wt in zip(TEST_SETS, W):
        counts = rng.integers(5, 40, (Wt, 4)) * np.array([1, 4, 2, 60])
        eb = counts[:, 0] * 0.45 * rng.uniform(0.9, 1.1, Wt)
        sums = {}
        for arm in ARMS:
            R = KG if arm == "G" else K
            sums[arm] = counts[None, None] * ERR * np.asarray(fact[arm]) * rng.lognormal(0, noise, (R, N, Wt, 4))
        data[t] = {"sums": sums, "counts": counts, "eb": eb}
    return data


def paired_data(K=5, N=3, W=(30, 15), KG=3, seed=11, rep_sd=0.06, noise=0.04):
    """As my_make_data, plus a multiplicative effect per (replicate, kind) shared by all arms of that replicate
    (same candidate pool and first round), and a world effect shared by all arms (same test world)."""
    rng = np.random.default_rng(seed)
    rep = rng.lognormal(0, rep_sd, (K, 4))
    data = {}
    for t, Wt in zip(TEST_SETS, W):
        counts = rng.integers(5, 40, (Wt, 4)) * np.array([1, 4, 2, 60])
        eb = counts[:, 0] * 0.45 * rng.uniform(0.9, 1.1, Wt)
        world = rng.lognormal(0, 0.15, (Wt, 4))
        sums = {}
        for arm in ARMS:
            R = KG if arm == "G" else K
            sums[arm] = (counts[None, None] * ERR * np.asarray(FACT[arm]) * world[None, None] * rep[:R, None, None, :]
                         * rng.lognormal(0, noise, (R, N, Wt, 4)))
        data[t] = {"sums": sums, "counts": counts, "eb": eb}
    return data


def zero_wall(data):
    data["main6"]["counts"] = data["main6"]["counts"].copy()
    data["main6"]["counts"][:, 2] = 0
    return data


CONFIGS = {
    "C1 make_data() K=5": dict(kind="make", kw={}, n=10_000),
    "C2 make_data(seed=7, noise=0.15)": dict(kind="make", kw={"seed": 7, "noise": 0.15}, n=10_000),
    "C3 make_data(K=2, KG=1)": dict(kind="make", kw={"K": 2, "KG": 1}, n=4_000),
    "C4 make_data(K=1, KG=1)": dict(kind="make", kw={"K": 1, "KG": 1}, n=4_000),
    "C5 make_data(K=3, W=(200,100), noise=0.05)": dict(kind="make", kw={"K": 3, "W": (200, 100), "noise": 0.05}, n=2_000),
    "C6 paired_data() K=5": dict(kind="paired", kw={}, n=10_000),
    "C7 make_data() with main6 wall_pillar counts 0": dict(kind="zero_wall", kw={}, n=500),
}


def build(cfg):
    if cfg["kind"] == "make":
        return my_make_data(**cfg["kw"])
    if cfg["kind"] == "paired":
        return paired_data(**cfg["kw"])
    return zero_wall(my_make_data(**cfg["kw"]))
