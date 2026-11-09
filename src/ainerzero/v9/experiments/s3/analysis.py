"""Registered statistics and gates for S3 phase 1 (DESIGN-r2 §4). Pure NumPy.

Missing or empty data raises instead of passing: a gate can only pass on measured values.
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

CHANCE = 1.0 / 7.0
FLOOR = CHANCE + 0.03
H1_MIN_DELTA = 0.10
H2_MIN_DELTA = 0.05
H3_MAX_DROP = 0.05
UPPER_MIN = 0.90
UNSWAPPED_MIN = 0.80
BOOTSTRAP_RESAMPLES = 10000
BOOTSTRAP_SEED = 20261109


def accuracy(correct: np.ndarray, mask: np.ndarray) -> float:
    if int(mask.sum()) == 0:
        raise ValueError("no events selected; a gate cannot be evaluated on empty data")
    return float(correct[mask].mean())


def paired_bootstrap_delta(
    episode_ids: np.ndarray,
    correct_a: np.ndarray,
    correct_b: np.ndarray,
    *,
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, float]:
    """95% CI for accuracy(A) - accuracy(B), resampling whole episodes.

    Inputs are aligned per event. Episodes are the resampling unit because events
    inside an episode share a trajectory.
    """
    if len(episode_ids) == 0:
        raise ValueError("no events; cannot bootstrap")
    if not (len(episode_ids) == len(correct_a) == len(correct_b)):
        raise ValueError("misaligned inputs")
    uniq, inv = np.unique(episode_ids, return_inverse=True)
    n_ep = len(uniq)
    n_ev = np.bincount(inv, minlength=n_ep).astype(float)
    sum_a = np.bincount(inv, weights=correct_a.astype(float), minlength=n_ep)
    sum_b = np.bincount(inv, weights=correct_b.astype(float), minlength=n_ep)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n_ep, size=(resamples, n_ep))
    tot = n_ev[idx].sum(1)
    delta = (sum_a[idx].sum(1) - sum_b[idx].sum(1)) / tot
    point = (sum_a.sum() - sum_b.sum()) / n_ev.sum()
    lo, hi = np.percentile(delta, [2.5, 97.5])
    return {"delta": float(point), "ci_low": float(lo), "ci_high": float(hi), "n_episodes": int(n_ep), "n_events": int(n_ev.sum())}


def difference_gate(boot: Mapping[str, float], min_delta: float) -> bool:
    return bool(boot["delta"] >= min_delta and boot["ci_low"] > 0.0)


def legality(primary: Mapping[str, float], unswapped: Mapping[str, float], claimed: Sequence[str]) -> dict[str, bool]:
    """Validity gates. Any failure voids H1-H3 for the run."""
    out = {
        "floor_A0": primary["A0"] <= FLOOR,
        "upper_O": primary["O"] >= UPPER_MIN,
        "negative_N": primary["N"] <= FLOOR,
    }
    for arm in claimed:
        out[f"unswapped_{arm}"] = unswapped[arm] >= UNSWAPPED_MIN
    return out
