"""Registered statistics and gates for S3 phase 2 (DESIGN-r2 §4). Pure NumPy.

``per`` maps ``(condition, seed, phase)`` to per-event arrays. Phases are ``F1`` (end of the
F1 stage), ``F1_after`` (F1 events after the F2 stage) and ``F2`` (F2 events after the F2
stage). Required arrays: ``correct``, ``correct_8``, ``pred``, ``swapped``, ``bucket``, ``ep``,
``query_t``, ``answer``.
Missing or empty data raises instead of passing.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s3 import analysis as P1

NAMESPACES = {"train": "s3p2-train", "dev": "s3p2-dev", "final": "s3p2-final", "probe": "s3p2-probe"}
LONG = 3  # batching.BUCKET_CODE[spec.BUCKET_LONG]
BUCKET_NAMES = {1: "short", 2: "mid", 3: "long"}

CHANCE = P1.CHANCE
FLOOR = P1.FLOOR
UPPER_MIN = P1.UPPER_MIN
UNSWAPPED_MIN = P1.UNSWAPPED_MIN
H1_MIN_DELTA = 0.10
H2_MIN_DELTA = 0.05
H2B_MIN_DELTA = 0.03
H3_MARGIN = 0.05
INTERFERENCE_MIN = 2 * H3_MARGIN
CONTENT_MIN = 2 * H3_MARGIN
MIN_EVENTS_PER_SEED = 200
MIN_EPISODES_PER_SEED = 50

CAPACITIES = (16, 64, 256)
DETERMINISM_GROUPS = (
    ("A2-C0", "A2-R16", "A2-R64", "A2-R256", "A2-CN"),
    ("A3H-C0", "A3H-R16", "A3H-R64", "A3H-R256"),
)
PairKey = tuple[str, str]


def primary_mask(r: Mapping[str, np.ndarray]) -> np.ndarray:
    return (r["bucket"] == LONG) & r["swapped"]


def unswapped_mask(r: Mapping[str, np.ndarray]) -> np.ndarray:
    return (r["bucket"] == LONG) & ~r["swapped"]


def _stack(per: Mapping, cond: str, phase: str, seeds: Sequence[int]) -> dict[str, np.ndarray]:
    rows = [per[cond, s, phase] for s in seeds]
    return {k: np.concatenate([r[k] for r in rows]) for k in ("correct", "correct_8", "swapped", "bucket", "ep", "query_t", "answer")}


def _acc(per: Mapping, cond: str, phase: str, seeds: Sequence[int], mask_fn=primary_mask, key: str = "correct") -> float:
    s = _stack(per, cond, phase, seeds)
    return P1.accuracy(s[key], mask_fn(s))


def paired(
    per: Mapping,
    a: PairKey,
    b: PairKey,
    seeds: Sequence[int],
    *,
    key: str = "correct",
) -> dict[str, float]:
    """Paired bootstrap of accuracy(a) - accuracy(b) on primary events; events must align."""
    sa, sb = _stack(per, *a, seeds), _stack(per, *b, seeds)
    for k in ("ep", "query_t", "answer", "bucket", "swapped"):
        if not np.array_equal(sa[k], sb[k]):
            raise ValueError(f"events do not align on {k}: {a} vs {b}")
    m = primary_mask(sa)
    return P1.paired_bootstrap_delta(sa["ep"][m], sa[key][m], sb[key][m])


def non_inferior(boot: Mapping[str, float], margin: float) -> bool:
    """True only when the upper bound of a loss is measured and within ``margin``."""
    return bool(boot["ci_high"] <= margin)


def enough_samples(per: Mapping, cond: str, phase: str, seeds: Sequence[int]) -> bool:
    """Each seed needs enough primary events from enough episodes."""
    for s in seeds:
        r = per[cond, s, phase]
        m = primary_mask(r)
        if int(m.sum()) < MIN_EVENTS_PER_SEED or len(np.unique(r["ep"][m])) < MIN_EPISODES_PER_SEED:
            return False
    return True


def identical_f1(per: Mapping, conds: Sequence[str], seeds: Sequence[int]) -> bool:
    """Same seed, independently trained: the F1 stage must give identical predictions."""
    for s in seeds:
        ref = per[conds[0], s, "F1"]["pred"]
        for c in conds[1:]:
            if not np.array_equal(ref, per[c, s, "F1"]["pred"]):
                return False
    return True


def legality(per: Mapping, seeds: Sequence[int], *, check_samples: bool = True) -> dict[str, bool]:
    """Conditions without which no hypothesis in the run is interpreted."""
    out = {
        "floor_A0": _acc(per, "A0", "F1", seeds) <= FLOOR,
        "upper_O": _acc(per, "O", "F1", seeds) >= UPPER_MIN,
        "floor_N": _acc(per, "N", "F1", seeds) <= FLOOR,
        "unswapped_A2": _acc(per, "A2-C0", "F1", seeds, unswapped_mask) >= UNSWAPPED_MIN,
        "unswapped_A3H": _acc(per, "A3H-C0", "F1", seeds, unswapped_mask) >= UNSWAPPED_MIN,
        "determinism_A2": identical_f1(per, DETERMINISM_GROUPS[0], seeds),
        "determinism_A3H": identical_f1(per, DETERMINISM_GROUPS[1], seeds),
    }
    if check_samples:
        out["min_sample_F1"] = enough_samples(per, "A2-C0", "F1", seeds)
        out["min_sample_F2"] = enough_samples(per, "A2-C0", "F2", seeds)
    return out


def _with_gate(boot: Mapping[str, float], min_delta: float) -> dict[str, Any]:
    return {**boot, "pass": P1.difference_gate(boot, min_delta)}


def h3_prime(per: Mapping, seeds: Sequence[int], capacity: int) -> dict[str, Any]:
    """Retention and plasticity of A2 with a replay buffer, both as non-inferiority gates.

    The two validity checks use the 8-class readout: on the 16-class readout the disjoint token
    sets make the no-protection drop large regardless of real forgetting. A failed validity
    check voids H3' only.
    """
    cond = f"A2-R{capacity}"
    interference = paired(per, ("A2-C0", "F1"), ("A2-C0", "F1_after"), seeds, key="correct_8")
    content = paired(per, ("A2-CN", "F1"), ("A2-CN", "F1_after"), seeds, key="correct_8")
    retention = paired(per, (cond, "F1"), (cond, "F1_after"), seeds)
    plasticity = paired(per, ("A2-C0", "F2"), (cond, "F2"), seeds)
    replay_vs_cn = paired(per, (cond, "F1_after"), ("A2-CN", "F1_after"), seeds, key="correct_8")
    valid = bool(interference["delta"] >= INTERFERENCE_MIN) and bool(content["delta"] >= CONTENT_MIN)
    gates = {"retention": non_inferior(retention, H3_MARGIN), "plasticity": non_inferior(plasticity, H3_MARGIN)}
    return {
        "capacity": capacity,
        "interference_8class": interference,
        "content_8class": content,
        "replay_minus_cn_8class": replay_vs_cn,
        "valid": valid,
        "retention": retention,
        "plasticity": plasticity,
        "gates": gates,
        "pass": valid and all(gates.values()),
    }


def capacity_curve(per: Mapping, seeds: Sequence[int], memory: str) -> dict[str, Any]:
    """Descriptive only: retention and plasticity at every replay capacity."""
    out = {}
    for cap in CAPACITIES:
        cond = f"{memory}-R{cap}"
        out[cond] = {
            "drop": paired(per, (cond, "F1"), (cond, "F1_after"), seeds),
            "drop_8class": paired(per, (cond, "F1"), (cond, "F1_after"), seeds, key="correct_8"),
            "plasticity_cost": paired(per, (f"{memory}-C0", "F2"), (cond, "F2"), seeds),
        }
    return out


def select_capacity(curve: Mapping[str, Any], memory: str = "A2") -> int | None:
    """Smallest capacity whose probe upper bounds meet the margin; ``None`` when none does."""
    for cap in CAPACITIES:
        row = curve[f"{memory}-R{cap}"]
        if non_inferior(row["drop"], H3_MARGIN) and non_inferior(row["plasticity_cost"], H3_MARGIN):
            return cap
    return None


def evaluate(per: Mapping, seeds: Sequence[int], *, capacity: int, has_a1: bool = True, check_samples: bool = True) -> dict[str, Any]:
    """All registered gates. H1, H2 and H2b are read at the end of the F1 stage."""
    legal = legality(per, seeds, check_samples=check_samples)
    out: dict[str, Any] = {
        "legality": legal,
        "valid": all(legal.values()),
        "accuracy_F1": {
            c: _acc(per, c, "F1", seeds)
            for c in ("A0", "O", "N", "A2-C0", "A3S", "A3H-C0") + (("A1",) if has_a1 else ())
        },
        "h2": _with_gate(paired(per, ("A3H-C0", "F1"), ("A2-C0", "F1"), seeds), H2_MIN_DELTA),
        "h2b": _with_gate(paired(per, ("A3H-C0", "F1"), ("A3S", "F1"), seeds), H2B_MIN_DELTA),
        "h3_prime": h3_prime(per, seeds, capacity),
        "capacity_A2": capacity_curve(per, seeds, "A2"),
        "capacity_A3H": capacity_curve(per, seeds, "A3H"),
    }
    if has_a1:
        out["h1"] = _with_gate(paired(per, ("A2-C0", "F1"), ("A1", "F1"), seeds), H1_MIN_DELTA)
    claims = {k: out["valid"] and out[k]["pass"] for k in ("h2", "h2b", "h3_prime")}
    if has_a1:
        claims["h1"] = out["valid"] and out["h1"]["pass"]
    out["claims"] = claims
    return out


def invalidated(result: dict[str, Any], reason: str) -> dict[str, Any]:
    """Mark a finished evaluation invalid, e.g. when frozen files changed during the run."""
    return {**result, "valid": False, "invalid_reason": reason, "claims": {k: False for k in result["claims"]}}


def balanced_accuracy(correct: np.ndarray, answer: np.ndarray) -> float:
    """Mean recall over the answer classes present."""
    if len(answer) == 0:
        raise ValueError("no events selected")
    return float(np.mean([correct[answer == c].mean() for c in np.unique(answer)]))


def bucket_table(r: Mapping[str, np.ndarray]) -> dict[str, dict[str, float | int]]:
    """Accuracy by gap bucket and by whether the token changed, with event counts."""
    out: dict[str, dict[str, float | int]] = {}
    for code, name in BUCKET_NAMES.items():
        for label, m in (("swapped", r["swapped"]), ("unswapped", ~r["swapped"])):
            sel = (r["bucket"] == code) & m
            if sel.any():
                out[f"{name}/{label}"] = {"n": int(sel.sum()), "acc": float(r["correct"][sel].mean()), "acc_8": float(r["correct_8"][sel].mean())}
    return out
