"""S4 phase 1 metrics (DESIGN-r3 §4, §5). Pure CPU, NumPy only.

- Re-identification at reappearance events and IDF1 from a tracker's per-detection track ids.
- Collision dynamics from the exact truth: one-step velocity error of the disks in a disk
  contact (D) and of grazing disks (HF), per world, for any process model.
- Bootstrap over worlds for ratios of world sums: D, the HF ratio, the gap-closure share C and
  plain differences, with the 95% interval and a Bonferroni interval.
"""

from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import world as W
from ainerzero.v9.experiments.s4.assign import hungarian

GRAZE_MARGIN = 0.3
BOOT_N, BOOT_SEED, LEVEL = 10_000, 20261110, 0.95


# --- identity --------------------------------------------------------------------------------
def reid(ep: W.Episode, ids: Sequence[np.ndarray], events: Sequence[dict] | None = None) -> list[dict[str, Any]]:
    """Each reappearance event with ``correct``: the track id of k at b equals its track id at a."""
    events = W.reappearances(ep) if events is None else events
    at = [dict(zip(s.truth_ids.tolist(), np.asarray(i).tolist())) for s, i in zip(ep.steps, ids)]
    return [dict(e, correct=int(at[e["a"]][e["k"]] == at[e["b"]][e["k"]])) for e in events]


def idf1(ep: W.Episode, ids: Sequence[np.ndarray]) -> float:
    """Detection-level IDF1: the best one-to-one mapping of tracks to identities, matched detections / all."""
    pairs: dict[tuple[int, int], int] = {}
    n = 0
    for s, i in zip(ep.steps, ids):
        for truth, trk in zip(s.truth_ids.tolist(), np.asarray(i).tolist()):
            pairs[(trk, truth)] = pairs.get((trk, truth), 0) + 1
            n += 1
    if n == 0:
        return float("nan")
    tracks = sorted({k for k, _ in pairs})
    truths = sorted({t for _, t in pairs})
    cnt = np.zeros((len(tracks), len(truths)))
    for (k, t), c in pairs.items():
        cnt[tracks.index(k), truths.index(t)] = c
    matched = sum(cnt[r, c] for r, c in hungarian(-cnt))
    return float(matched / n)


# --- collision dynamics ------------------------------------------------------------------------
def dynamics_errors(ep: W.Episode, model: Callable) -> dict[str, list[float]]:
    """One-step velocity errors from the exact truth: disks in a disk contact, and grazing disks
    (closer than 2R + GRAZE_MARGIN at the end of the step without a disk contact)."""
    coll_err: list[float] = []
    graze_err: list[float] = []
    for s, nxt in zip(ep.steps[:-1], ep.steps[1:]):
        coll = {i for kind, i, j in s.contacts if kind == "disk"} | {j for kind, i, j in s.contacts if kind == "disk"}
        d = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(ep.n_disks) * 1e9
        graze = sorted({i for i in range(ep.n_disks) if d[i].min() < 2 * W.RADIUS + GRAZE_MARGIN} - coll)
        if not coll and not graze:
            continue
        out = model(s.positions[None], s.velocities[None], ep.pillars)
        err = np.linalg.norm(np.asarray(out[1])[0] - nxt.velocities, axis=1)
        coll_err += err[sorted(coll)].tolist()
        graze_err += err[graze].tolist()
    return {"coll": coll_err, "graze": graze_err}


# --- bootstrap over worlds --------------------------------------------------------------------
def bootstrap(stat: Callable[..., float], sums: dict[str, np.ndarray], *, n_boot: int = BOOT_N, seed: int = BOOT_SEED,
              m: int = 1) -> dict[str, Any]:
    """``sums`` maps names to per-world arrays (same length); ``stat`` takes their totals as keywords.

    Worlds are resampled with replacement; returns the point value, the 95% interval and a
    Bonferroni interval over ``m`` comparisons."""
    names = list(sums)
    arr = np.stack([np.asarray(sums[k], dtype=np.float64) for k in names])  # [K, W]
    n_w = arr.shape[1]
    if n_w == 0:
        return {"value": None, "ci_low": None, "ci_high": None, "bonf_low": None, "bonf_high": None, "n_worlds": 0}
    with np.errstate(divide="ignore", invalid="ignore"):
        point = float(stat(**dict(zip(names, arr.sum(1)))))
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_w, size=(n_boot, n_w))
    tot = arr[:, draws].sum(-1)                                              # [K, n_boot]
    with np.errstate(divide="ignore", invalid="ignore"):
        boot = np.array(stat(**dict(zip(names, tot))), dtype=np.float64)
    boot = boot[np.isfinite(boot)]
    if not np.isfinite(point) or len(boot) < n_boot:
        # An undefined ratio (e.g. E-P no better than E-B) in the point value or in any resample:
        # dropping those resamples would narrow the interval, so no interval is given and every
        # gate that needs one fails. The point value is kept when it is defined.
        return {"value": float(point) if np.isfinite(point) else None, "ci_low": None, "ci_high": None,
                "bonf_low": None, "bonf_high": None, "n_worlds": int(n_w), "n_boot_finite": int(len(boot))}
    tail = (1 - LEVEL) / 2
    lo, hi = np.quantile(boot, [tail, 1 - tail])
    blo, bhi = np.quantile(boot, [tail / m, 1 - tail / m])
    return {"value": float(point), "ci_low": float(lo), "ci_high": float(hi), "bonf_low": float(blo), "bonf_high": float(bhi),
            "n_worlds": int(n_w), "n_boot_finite": int(len(boot))}


def _ratio(num, den):
    """num / den, undefined (NaN) wherever den is not positive: a resample in which a denominator
    vanishes or changes sign gives no ratio, so the bootstrap gives no interval."""
    num, den = np.asarray(num, dtype=np.float64), np.asarray(den, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / np.where(den > 0, den, 1.0), np.nan)


def stat_D(x_coll, b_coll, **_):
    """D(X) = 1 - err(X) / err(E-B) on collision disk-steps (same disk-steps for both)."""
    return 1 - _ratio(x_coll, b_coll)


def stat_HF(x_graze, n_graze, b_coll, n_coll, **_):
    """Mean grazing error of X over E-B's mean collision error."""
    return _ratio(_ratio(x_graze, n_graze), _ratio(b_coll, n_coll))


def stat_C(x, b, p, **_):
    """C(X) = (acc X - acc E-B) / (acc E-P - acc E-B) on one event set (sums of correctness)."""
    return _ratio(np.asarray(x, dtype=np.float64) - b, np.asarray(p, dtype=np.float64) - b)


def stat_diff(x, y, n, **_):
    return _ratio(np.asarray(x, dtype=np.float64) - y, n)


def per_world(values_by_world: Sequence[Sequence[float]]) -> np.ndarray:
    return np.array([float(np.sum(v)) for v in values_by_world])
