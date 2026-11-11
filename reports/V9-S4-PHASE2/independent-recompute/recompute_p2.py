#!/usr/bin/env python3
"""S4 Phase 2 Independent Recomputation Script.
Pure Python standard library and NumPy ONLY.
Does NOT import ainerzero, MLX, or any project code.

Computes:
- Gate statistics (GN, GA, GC, GK1_all, GK1_collision, GK2_non_collision, GK2_collision,
  GD_D, GD_ratio, GX_diff, GX_C, GR, neg_C, neg_D) with point estimates, 95% CIs,
  and Bonferroni CIs (m=12).
- Gate decisions (GN, GA, GC, GK1, GK2, GD, GX, GR) and negative control.
- Record-verifiable legality checks: floor, samples, completeness.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

# Default thresholds matching DESIGN-r1.md §5 / analysis_p2.py
DEFAULT_THRESHOLDS = {
    "GN": {"diff": -0.01, "diff_low": -0.03},
    "GA": {"diff": 0.03, "diff_low": 0.0},
    "GC": {"C": 0.75, "C_low": 0.5},
    "GK1": {
        "all": (0.87, 0.93),
        "all_interval": (0.85, 0.95),
        "collision": 0.85,
        "collision_low": 0.80,
    },
    "GK2": {
        "non_collision": 0.85,
        "non_collision_low": 0.80,
        "collision": 0.75,
        "collision_low": 0.65,
    },
    "GD": {
        "D": 0.8,
        "D_low": 0.7,
        "ratio": 0.10,
        "ratio_high": 0.15,
    },
    "GX": {
        "diff": 0.03,
        "diff_low": 0.0,
        "C": 0.6,
        "C_low": 0.4,
    },
    "GR": {"diff": 0.0, "diff_low": 0.0},
    "negative_control": {"C_high_below": 0.5, "D_high_below": 0.5},
}

DEFAULT_LEGALITY = {
    "expected_collision_events_per_40": 267.0,
    "sample_band": 0.25,
    "expected_collision_disk_steps_per_40": 552.0,
    "dyn_floor": 0.75,
}


def safe_ratio(num: Any, den: Any) -> np.ndarray:
    """num / den, returning NaN when den <= 0."""
    n = np.asarray(num, dtype=np.float64)
    d = np.asarray(den, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(d > 0, n / np.where(d > 0, d, 1.0), np.nan)


def stat_diff(x: Any, y: Any, n: Any, **_: Any) -> np.ndarray:
    """Mean difference (x - y) / n."""
    return safe_ratio(np.asarray(x, dtype=np.float64) - y, n)


def stat_C(x: Any, b: Any, p: Any, **_: Any) -> np.ndarray:
    """Gap-closure ratio: (x - b) / (p - b)."""
    return safe_ratio(
        np.asarray(x, dtype=np.float64) - b, np.asarray(p, dtype=np.float64) - b
    )


def stat_D(x_coll: Any, b_coll: Any, **_: Any) -> np.ndarray:
    """Dynamics accuracy: 1 - err(X) / err(E-B) on collision disk-steps."""
    return 1.0 - safe_ratio(x_coll, b_coll)


def stat_HF(
    x_graze: Any, n_graze: Any, b_coll: Any, n_coll: Any, **_: Any
) -> np.ndarray:
    """High-frequency false-alarm ratio: mean graze error / mean collision error."""
    return safe_ratio(safe_ratio(x_graze, n_graze), safe_ratio(b_coll, n_coll))


def bootstrap(
    stat_fn: Callable[..., Any],
    sums_dict: Dict[str, np.ndarray],
    *,
    n_boot: int = 10000,
    seed: int = 20261111,
    level: float = 0.95,
    m: int = 12,
) -> Dict[str, Any]:
    """Paired bootstrap over worlds with replacement for ratios/differences."""
    names = list(sums_dict.keys())
    arr = np.stack([np.asarray(sums_dict[k], dtype=np.float64) for k in names])
    n_w = arr.shape[1]
    if n_w == 0:
        return {
            "value": None,
            "ci_low": None,
            "ci_high": None,
            "bonf_low": None,
            "bonf_high": None,
            "n_worlds": 0,
            "n_boot_finite": 0,
        }

    with np.errstate(divide="ignore", invalid="ignore"):
        point = float(stat_fn(**dict(zip(names, arr.sum(1)))))

    rng = np.random.default_rng(seed)
    draws = rng.integers(0, n_w, size=(n_boot, n_w))
    tot = arr[:, draws].sum(-1)

    with np.errstate(divide="ignore", invalid="ignore"):
        boot = np.array(stat_fn(**dict(zip(names, tot))), dtype=np.float64)

    boot = boot[np.isfinite(boot)]
    if not np.isfinite(point) or len(boot) < n_boot:
        return {
            "value": float(point) if np.isfinite(point) else None,
            "ci_low": None,
            "ci_high": None,
            "bonf_low": None,
            "bonf_high": None,
            "n_worlds": int(n_w),
            "n_boot_finite": int(len(boot)),
        }

    tail = (1.0 - level) / 2.0
    lo, hi = np.quantile(boot, [tail, 1.0 - tail])
    blo, bhi = np.quantile(boot, [tail / m, 1.0 - tail / m])

    return {
        "value": float(point),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "bonf_low": float(blo),
        "bonf_high": float(bhi),
        "n_worlds": int(n_w),
        "n_boot_finite": int(len(boot)),
    }


def _mask(record: Dict[str, Any], which: str) -> np.ndarray:
    """Mask of events matching `which` ('collision', 'non_collision', 'all')."""
    if not record.get("events"):
        return np.zeros(0, dtype=bool)
    coll = np.array([e[3] == 1 for e in record["events"]], dtype=bool)
    if which == "collision":
        return coll
    elif which == "non_collision":
        return ~coll
    elif which == "all":
        return np.ones_like(coll)
    raise ValueError(f"Unknown event category: {which}")


def _event_mean(
    record: Dict[str, Any],
    arm: str,
    field: str,
    seeds: Sequence[int] = (1, 2, 3),
) -> np.ndarray:
    """Event values averaged across seeds for one world."""
    if not record.get("events"):
        return np.zeros(0, dtype=np.float64)
    cell_arrays = [
        np.asarray(record["cells"][f"{arm}#{s}"][field], dtype=np.float64)
        for s in seeds
        if f"{arm}#{s}" in record["cells"]
    ]
    if not cell_arrays:
        return np.zeros(len(record["events"]), dtype=np.float64)
    return np.mean(cell_arrays, axis=0)


def event_sums(
    records: Sequence[Dict[str, Any]],
    arm: str,
    which: str,
    field: str = "correct",
    seeds: Sequence[int] = (1, 2, 3),
) -> np.ndarray:
    """Per-world sum of seed-averaged field on masked events."""
    out = []
    for r in records:
        if not r.get("events"):
            out.append(0.0)
            continue
        m = _mask(r, which)
        em = _event_mean(r, arm, field, seeds=seeds)
        out.append(float(em[m].sum()) if len(em) else 0.0)
    return np.array(out, dtype=np.float64)


def event_counts(
    records: Sequence[Dict[str, Any]], which: str
) -> np.ndarray:
    """Per-world count of masked events."""
    out = []
    for r in records:
        if not r.get("events"):
            out.append(0.0)
            continue
        m = _mask(r, which)
        out.append(float(m.sum()))
    return np.array(out, dtype=np.float64)


def one_step_sums(
    records: Sequence[Dict[str, Any]],
    arm: str,
    which: str,
    seeds: Sequence[int] = (1, 2, 3),
) -> Tuple[np.ndarray, np.ndarray]:
    """Per-world (inside, rows) counts of one-step coverage pooled over seeds."""
    parts = ("collision",) if which == "collision" else ("collision", "other")
    ins_list = []
    n_list = []
    for r in records:
        ins_val = 0.0
        n_val = 0.0
        for s in seeds:
            key = f"{arm}#{s}"
            if key in r.get("cells", {}):
                cell_one = r["cells"][key].get("one_step", {})
                for p in parts:
                    if p in cell_one:
                        n_val += float(cell_one[p][0])
                        ins_val += float(cell_one[p][1])
        ins_list.append(ins_val)
        n_list.append(n_val)
    return np.array(ins_list, dtype=np.float64), np.array(n_list, dtype=np.float64)


def _dyn(
    records: Sequence[Dict[str, Any]],
    name: str,
    field: str,
    seeds: Sequence[int] = (1, 2, 3),
) -> np.ndarray:
    """Per-world array of dynamics values (averaged over seeds for learned arms)."""
    out = []
    for r in records:
        dyn = r.get("dyn", {})
        seed_keys = [f"{name}#{s}" for s in seeds if f"{name}#{s}" in dyn]
        if seed_keys:
            out.append(float(np.mean([dyn[k][field] for k in seed_keys])))
        elif name in dyn:
            out.append(float(dyn[name][field]))
        else:
            out.append(0.0)
    return np.array(out, dtype=np.float64)


def compute_gate_stats(
    main_records: Sequence[Dict[str, Any]],
    extrap_records: Sequence[Dict[str, Any]],
    *,
    main_arm: str = "L-int-g",
    scatter_arm: str = "L-sc-g",
    negative_arm: str = "L-ind-geo",
    seeds: Sequence[int] = (1, 2, 3),
    n_boot: int = 10000,
    seed: int = 20261111,
    level: float = 0.95,
    m: int = 12,
) -> Dict[str, Dict[str, Any]]:
    """Compute all 14 gate & negative control statistics."""
    ins_all, n_all = one_step_sums(main_records, main_arm, "all", seeds=seeds)
    ins_coll, n_coll = one_step_sums(main_records, main_arm, "collision", seeds=seeds)

    stats: Dict[str, Dict[str, Any]] = {
        # GN: non-collision diff vs E-B
        "GN": bootstrap(
            stat_diff,
            {
                "x": event_sums(main_records, main_arm, "non_collision", seeds=seeds),
                "y": event_sums(main_records, "E-B", "non_collision", seeds=seeds),
                "n": event_counts(main_records, "non_collision"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GA: all events diff vs E-B
        "GA": bootstrap(
            stat_diff,
            {
                "x": event_sums(main_records, main_arm, "all", seeds=seeds),
                "y": event_sums(main_records, "E-B", "all", seeds=seeds),
                "n": event_counts(main_records, "all"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GC: gap closure C on collision events
        "GC": bootstrap(
            stat_C,
            {
                "x": event_sums(main_records, main_arm, "collision", seeds=seeds),
                "b": event_sums(main_records, "E-B", "collision", seeds=seeds),
                "p": event_sums(main_records, "E-P", "collision", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GK1_all: 1-step coverage on all steps
        "GK1_all": bootstrap(
            stat_diff,
            {"x": ins_all, "y": np.zeros(len(main_records)), "n": n_all},
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GK1_collision: 1-step coverage on collision steps
        "GK1_collision": bootstrap(
            stat_diff,
            {"x": ins_coll, "y": np.zeros(len(main_records)), "n": n_coll},
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GK2_non_collision: reappearance coverage on non-collision events
        "GK2_non_collision": bootstrap(
            stat_diff,
            {
                "x": event_sums(
                    main_records, main_arm, "non_collision", field="reappear", seeds=seeds
                ),
                "y": np.zeros(len(main_records)),
                "n": event_counts(main_records, "non_collision"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GK2_collision: reappearance coverage on collision events
        "GK2_collision": bootstrap(
            stat_diff,
            {
                "x": event_sums(
                    main_records, main_arm, "collision", field="reappear", seeds=seeds
                ),
                "y": np.zeros(len(main_records)),
                "n": event_counts(main_records, "collision"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GD_D: dynamics D on collision disk-steps
        "GD_D": bootstrap(
            stat_D,
            {
                "x_coll": _dyn(main_records, main_arm, "coll", seeds=seeds),
                "b_coll": _dyn(main_records, "E-B", "coll", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GD_ratio: grazing error ratio
        "GD_ratio": bootstrap(
            stat_HF,
            {
                "x_graze": _dyn(main_records, main_arm, "graze", seeds=seeds),
                "n_graze": _dyn(main_records, main_arm, "n_graze", seeds=seeds),
                "b_coll": _dyn(main_records, "E-B", "coll", seeds=seeds),
                "n_coll": _dyn(main_records, "E-B", "n_coll", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GX_diff: extrapolation all events diff vs E-B
        "GX_diff": bootstrap(
            stat_diff,
            {
                "x": event_sums(extrap_records, main_arm, "all", seeds=seeds),
                "y": event_sums(extrap_records, "E-B", "all", seeds=seeds),
                "n": event_counts(extrap_records, "all"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GX_C: extrapolation C on collision events
        "GX_C": bootstrap(
            stat_C,
            {
                "x": event_sums(extrap_records, main_arm, "collision", seeds=seeds),
                "b": event_sums(extrap_records, "E-B", "collision", seeds=seeds),
                "p": event_sums(extrap_records, "E-P", "collision", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # GR: collision events diff vs scatter arm
        "GR": bootstrap(
            stat_diff,
            {
                "x": event_sums(main_records, main_arm, "collision", seeds=seeds),
                "y": event_sums(main_records, scatter_arm, "collision", seeds=seeds),
                "n": event_counts(main_records, "collision"),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # neg_C: negative control C
        "neg_C": bootstrap(
            stat_C,
            {
                "x": event_sums(main_records, negative_arm, "collision", seeds=seeds),
                "b": event_sums(main_records, "E-B", "collision", seeds=seeds),
                "p": event_sums(main_records, "E-P", "collision", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
        # neg_D: negative control D
        "neg_D": bootstrap(
            stat_D,
            {
                "x_coll": _dyn(main_records, negative_arm, "coll", seeds=seeds),
                "b_coll": _dyn(main_records, "E-B", "coll", seeds=seeds),
            },
            n_boot=n_boot,
            seed=seed,
            level=level,
            m=m,
        ),
    }
    return stats


def decide_gates(
    st: Dict[str, Dict[str, Any]], thresholds: Dict[str, Any]
) -> Tuple[Dict[str, bool], bool]:
    """Evaluate gate criteria and negative control."""
    def _ge(stat: Dict[str, Any], key: str, thr: float) -> bool:
        v = stat.get(key)
        return v is not None and v >= thr

    def _gt(stat: Dict[str, Any], key: str, thr: float) -> bool:
        v = stat.get(key)
        return v is not None and v > thr

    def _le(stat: Dict[str, Any], key: str, thr: float) -> bool:
        v = stat.get(key)
        return v is not None and v <= thr

    def _lt(stat: Dict[str, Any], key: str, thr: float) -> bool:
        v = stat.get(key)
        return v is not None and v < thr

    T = thresholds
    lo1, hi1 = T["GK1"]["all"]
    lo1i, hi1i = T["GK1"]["all_interval"]
    k1a, k1c = st["GK1_all"], st["GK1_collision"]
    k2n, k2c = st["GK2_non_collision"], st["GK2_collision"]
    d, hf = st["GD_D"], st["GD_ratio"]

    passed = {
        "GN": _ge(st["GN"], "value", T["GN"]["diff"])
        and _gt(st["GN"], "bonf_low", T["GN"]["diff_low"]),
        "GA": _ge(st["GA"], "value", T["GA"]["diff"])
        and _gt(st["GA"], "bonf_low", T["GA"]["diff_low"]),
        "GC": _ge(st["GC"], "value", T["GC"]["C"])
        and _gt(st["GC"], "bonf_low", T["GC"]["C_low"]),
        "GK1": (
            _ge(k1a, "value", lo1)
            and _le(k1a, "value", hi1)
            and _ge(k1a, "bonf_low", lo1i)
            and _le(k1a, "bonf_high", hi1i)
            and _ge(k1c, "value", T["GK1"]["collision"])
            and _gt(k1c, "bonf_low", T["GK1"]["collision_low"])
        ),
        "GK2": (
            _ge(k2n, "value", T["GK2"]["non_collision"])
            and _gt(k2n, "bonf_low", T["GK2"]["non_collision_low"])
            and _ge(k2c, "value", T["GK2"]["collision"])
            and _gt(k2c, "bonf_low", T["GK2"]["collision_low"])
        ),
        "GD": (
            _ge(d, "value", T["GD"]["D"])
            and _gt(d, "bonf_low", T["GD"]["D_low"])
            and _le(hf, "value", T["GD"]["ratio"])
            and _le(hf, "bonf_high", T["GD"]["ratio_high"])
        ),
        "GX": (
            _ge(st["GX_diff"], "value", T["GX"]["diff"])
            and _gt(st["GX_diff"], "bonf_low", T["GX"]["diff_low"])
            and _ge(st["GX_C"], "value", T["GX"]["C"])
            and _gt(st["GX_C"], "bonf_low", T["GX"]["C_low"])
        ),
        "GR": _ge(st["GR"], "value", T["GR"]["diff"])
        and _gt(st["GR"], "bonf_low", T["GR"]["diff_low"]),
    }

    neg = _lt(
        st["neg_C"], "bonf_high", T["negative_control"]["C_high_below"]
    ) and _lt(st["neg_D"], "bonf_high", T["negative_control"]["D_high_below"])

    return {k: bool(v) for k, v in passed.items()}, bool(neg)


def compute_legality_from_records(
    main_records: Sequence[Dict[str, Any]],
    extrap_records: Sequence[Dict[str, Any]],
    *,
    n_main_registered: int,
    n_extrap_registered: int,
    legality_cfg: Dict[str, Any],
    seeds: Sequence[int] = (1, 2, 3),
) -> Dict[str, Any]:
    """Compute floor, sample size, and completeness legality checks."""
    # Floor check
    acc: Dict[str, Optional[float]] = {}
    for arm in ("E-CV", "E-B", "E-P"):
        x = event_sums(main_records, arm, "collision", seeds=seeds).sum()
        n = event_counts(main_records, "collision").sum()
        acc[arm] = float(x / n) if n > 0 else None

    missing = [a for a, v in acc.items() if v is None]
    floor_passed = (
        not missing
        and acc["E-CV"] is not None
        and acc["E-B"] is not None
        and acc["E-P"] is not None
        and acc["E-CV"] < acc["E-B"] < acc["E-P"]
    )

    # Samples check
    n_coll_events = int(event_counts(main_records, "collision").sum())
    exp_per_40 = legality_cfg.get(
        "expected_collision_events_per_40", DEFAULT_LEGALITY["expected_collision_events_per_40"]
    )
    expected_coll_events = exp_per_40 * len(main_records) / 40.0

    n_coll_steps = int(_dyn(main_records, "E-B", "n_coll", seeds=seeds).sum())
    exp_dyn_per_40 = legality_cfg.get(
        "expected_collision_disk_steps_per_40",
        DEFAULT_LEGALITY["expected_collision_disk_steps_per_40"],
    )
    dyn_expected = exp_dyn_per_40 * len(main_records) / 40.0

    sample_band = legality_cfg.get("sample_band", DEFAULT_LEGALITY["sample_band"])
    dyn_floor = legality_cfg.get("dyn_floor", DEFAULT_LEGALITY["dyn_floor"])

    samples_passed = bool(
        abs(n_coll_events - expected_coll_events) <= sample_band * expected_coll_events
        and n_coll_steps >= dyn_floor * dyn_expected
    )

    # Completeness check
    complete_passed = (
        len(main_records) == n_main_registered
        and len(extrap_records) == n_extrap_registered
    )

    return {
        "floor": {
            "passed": bool(floor_passed),
            "acc": acc,
            **({"undefined": missing} if missing else {}),
        },
        "samples": {
            "passed": bool(samples_passed),
            "collision_events": n_coll_events,
            "expected": expected_coll_events,
            "collision_disk_steps": n_coll_steps,
            "dyn_expected": dyn_expected,
            "sample_band": sample_band,
            "dyn_floor": dyn_floor,
        },
        "complete": {
            "passed": bool(complete_passed),
            "main": len(main_records),
            "extrap": len(extrap_records),
            "registered": [n_main_registered, n_extrap_registered],
        },
    }


def load_records(records_path: Path) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Load records from .json or .jsonl, returning (records_list, raw_loaded_dict_or_None)."""
    text = records_path.read_text(encoding="utf-8")
    if records_path.suffix == ".jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
        return records, None
    raw = json.loads(text)
    if isinstance(raw, list):
        return raw, None
    elif isinstance(raw, dict) and "records" in raw:
        return raw["records"], raw
    elif isinstance(raw, dict):
        # Perhaps a single record or dict of records
        raise ValueError(f"Unexpected JSON structure in {records_path}")
    raise ValueError(f"Cannot parse records from {records_path}")


def load_params(params_path: Optional[Path]) -> Dict[str, Any]:
    """Load configuration parameters from JSON if provided."""
    if params_path is None or not params_path.exists():
        return {}
    return json.loads(params_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="S4 Phase 2 Independent Recomputation (pure NumPy, no project code)"
    )
    parser.add_argument(
        "--records", required=True, type=Path, help="Path to results-p2g.json or worlds.jsonl"
    )
    parser.add_argument(
        "--params", type=Path, default=None, help="Path to PREREG-r1.json or params JSON"
    )
    parser.add_argument("--out", type=Path, default=None, help="Path to output JSON")
    parser.add_argument(
        "--bootstrap-n", type=int, default=None, help="Bootstrap iterations (default 10000)"
    )
    parser.add_argument(
        "--bootstrap-seed", type=int, default=None, help="Bootstrap seed (default 20261111)"
    )
    parser.add_argument(
        "--bonferroni-m", type=int, default=None, help="Bonferroni comparisons m (default 12)"
    )
    parser.add_argument(
        "--level", type=float, default=None, help="Confidence level (default 0.95)"
    )
    parser.add_argument(
        "--n-main", type=int, default=None, help="Expected main worlds count"
    )
    parser.add_argument(
        "--n-extrap", type=int, default=None, help="Expected extrap worlds count"
    )
    parser.add_argument("--main-arm", type=str, default="L-int-g", help="Main arm name")
    parser.add_argument("--scatter-arm", type=str, default="L-sc-g", help="Scatter arm name")
    parser.add_argument(
        "--negative-arm", type=str, default="L-ind-geo", help="Negative control arm name"
    )
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=None,
        help="Seeds to average over (default 1 2 3)",
    )
    parser.add_argument(
        "--summary", action="store_true", help="Print summary table to stdout"
    )
    parser.add_argument(
        "--assert-stored",
        action="store_true",
        help="Assert bit-for-bit equivalence if stored stats exist in input JSON",
    )

    args = parser.parse_args()

    # Load records
    records, raw_file_data = load_records(args.records)
    main_r = [r for r in records if r.get("kind") == "main"]
    extrap_r = [r for r in records if r.get("kind") == "extrap"]

    # Load params
    params = load_params(args.params)
    boot_cfg = params.get("statistics", {}).get("bootstrap", {})
    leg_cfg = params.get("legality", DEFAULT_LEGALITY)
    thresholds = params.get("gates", DEFAULT_THRESHOLDS)
    arms_cfg = params.get("arms", {})
    world_cfg = params.get("world", {})

    n_boot = (
        args.bootstrap_n
        if args.bootstrap_n is not None
        else boot_cfg.get("n", 10000)
    )
    boot_seed = (
        args.bootstrap_seed
        if args.bootstrap_seed is not None
        else boot_cfg.get("seed", 20261111)
    )
    level = (
        args.level
        if args.level is not None
        else boot_cfg.get("level", 0.95)
    )
    m = (
        args.bonferroni_m
        if args.bonferroni_m is not None
        else params.get("statistics", {}).get("bonferroni_m", 12)
    )
    seeds = (
        args.seeds
        if args.seeds is not None
        else arms_cfg.get("seeds", [1, 2, 3])
    )
    main_arm = arms_cfg.get("main", args.main_arm)
    scatter_arm = arms_cfg.get("scatter_control", args.scatter_arm)
    negative_arm = arms_cfg.get("negative_control", args.negative_arm)

    n_main_reg = (
        args.n_main
        if args.n_main is not None
        else world_cfg.get("main", {}).get("worlds", len(main_r))
    )
    n_extrap_reg = (
        args.n_extrap
        if args.n_extrap is not None
        else world_cfg.get("extrapolation", {}).get("worlds", len(extrap_r))
    )

    # Compute gate statistics
    st = compute_gate_stats(
        main_r,
        extrap_r,
        main_arm=main_arm,
        scatter_arm=scatter_arm,
        negative_arm=negative_arm,
        seeds=seeds,
        n_boot=n_boot,
        seed=boot_seed,
        level=level,
        m=m,
    )

    # Decide gates
    passed, neg_ok = decide_gates(st, thresholds)

    # Legality checks
    leg = compute_legality_from_records(
        main_r,
        extrap_r,
        n_main_registered=n_main_reg,
        n_extrap_registered=n_extrap_reg,
        legality_cfg=leg_cfg,
        seeds=seeds,
    )

    # Format human-readable output
    def fmt_stat(d: Optional[Dict[str, Any]]) -> str:
        if d is None or d.get("value") is None:
            return "—"
        blo = d.get("bonf_low")
        bhi = d.get("bonf_high")
        if blo is None or bhi is None:
            return f"{d['value']:+.3f} [no CI]"
        return f"{d['value']:+.3f} [{blo:+.3f}, {bhi:+.3f}]"

    print("=== S4 Phase 2 Independent Recomputation (pure NumPy) ===")
    print(f"Records loaded: {len(main_r)} main worlds, {len(extrap_r)} extrapolation worlds")
    print(f"Bootstrap settings: n={n_boot}, seed={boot_seed}, level={level}, Bonferroni m={m}")
    print(f"Arms: main={main_arm}, scatter={scatter_arm}, negative={negative_arm}, seeds={seeds}\n")

    print(f"{'Statistic':<20} {'Point [Bonferroni CI]':<26} {'95% CI':<24}")
    print("-" * 72)
    for k, v in st.items():
        ci_str = f"[{v['ci_low']:+.3f}, {v['ci_high']:+.3f}]" if v.get("ci_low") is not None else "—"
        print(f"{k:<20} {fmt_stat(v):<26} {ci_str:<24}")

    print("\nGate Decisions:")
    for g, p in passed.items():
        print(f"  {g:<5}: {'PASS' if p else 'FAIL'}")
    print(f"  Negative Control: {'PASS' if neg_ok else 'FAIL'}")

    print("\nLegality Checks (from records):")
    print(f"  Floor:        {'PASS' if leg['floor']['passed'] else 'FAIL'} ({leg['floor']['acc']})")
    print(
        f"  Samples:      {'PASS' if leg['samples']['passed'] else 'FAIL'} "
        f"(events={leg['samples']['collision_events']}/{leg['samples']['expected']:.1f}, "
        f"dyn_steps={leg['samples']['collision_disk_steps']}/{leg['samples']['dyn_expected']:.1f})"
    )
    print(
        f"  Completeness: {'PASS' if leg['complete']['passed'] else 'FAIL'} "
        f"(main={leg['complete']['main']}/{leg['complete']['registered'][0]}, "
        f"extrap={leg['complete']['extrap']}/{leg['complete']['registered'][1]})"
    )

    out_doc = {
        "stats": st,
        "passed": passed,
        "negative_control": neg_ok,
        "legality": leg,
        "config": {
            "bootstrap_n": n_boot,
            "bootstrap_seed": boot_seed,
            "bonferroni_m": m,
            "level": level,
            "seeds": seeds,
            "main_arm": main_arm,
            "scatter_arm": scatter_arm,
            "negative_arm": negative_arm,
            "n_main_registered": n_main_reg,
            "n_extrap_registered": n_extrap_reg,
        },
    }

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out_doc, f, indent=2)
        print(f"\nWrote full recomputation output to {args.out}")

    # Assertion against stored stats if requested
    if args.assert_stored and raw_file_data is not None:
        if "stats" in raw_file_data:
            stored_st = raw_file_data["stats"]
            for k in st:
                if k in stored_st:
                    for field in ("value", "ci_low", "ci_high", "bonf_low", "bonf_high"):
                        calc_val = st[k].get(field)
                        stor_val = stored_st[k].get(field)
                        if calc_val is not None and stor_val is not None:
                            assert (
                                calc_val == stor_val
                            ), f"Bit-for-bit mismatch in {k}.{field}: {calc_val} != {stor_val}"
            print("\n[VERIFICATION SUCCESS] All recomputed stats are 100% BIT-FOR-BIT IDENTICAL to stored values!")

        if "passed" in raw_file_data:
            stored_passed = raw_file_data["passed"]
            for k, p in passed.items():
                if k in stored_passed:
                    assert p == stored_passed[k], f"Gate decision mismatch for {k}: {p} != {stored_passed[k]}"
            print("[VERIFICATION SUCCESS] All gate decisions match stored decisions exactly!")

        if "negative_control" in raw_file_data:
            assert neg_ok == raw_file_data["negative_control"], "Negative control decision mismatch!"
            print("[VERIFICATION SUCCESS] Negative control decision matches stored value!")


if __name__ == "__main__":
    main()
