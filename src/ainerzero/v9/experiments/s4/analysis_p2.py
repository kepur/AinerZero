"""S4 phase 2 evaluation (reports/V9-S4-P2-DESIGN). Pure CPU, NumPy; process models are callables.

- partitions and world lists (no training partition: phase 2 trains nothing);
- one record per evaluation world: reappearance events; per tracking cell (arm, seed) the
  correctness of every event, the one-step coverage counts (collision steps and the others), the
  reappearance coverage of every event, IDF1, track count, a digest of the track ids and the gate
  share; the dynamics sums from the exact truth;
- aggregation over seeds and worlds; the gates GN, GA, GC, GK1, GK2, GD, GX, the negative control
  and the legality gates.

Every arm is tracked with the filter seed of (world, seed) used in phase 1 (variant "base"), so arms
share their random numbers. An event's correctness and its reappearance coverage are averaged over
the three seeds before summing per world; one-step rows of the three seeds are pooled.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import world as W

NAMESPACES = {"probe": "s4p2-probe", "final": "s4p2-final"}
SIZES = {"probe": (50, 25), "final": (200, 100)}            # (main, extrapolation) worlds
SEEDS = A.SEEDS
HAND = ("E-CV", "E-B", "E-P")
LEARNED = ("L-int", "L-int-g", "L-int-g3", "L-int-g7", "L-int-geo", "L-ind-geo")
MAIN_ARM, NEG_ARM = "L-int-g", "L-ind-geo"
GATES = {"L-int-g": 0.5, "L-int-g3": 0.3, "L-int-g7": 0.7, "L-int-geo": "geo", "L-ind-geo": "geo"}   # arm -> gate
BASE_MODEL = {"L-int": "L-int", "L-int-g": "L-int", "L-int-g3": "L-int", "L-int-g7": "L-int", "L-int-geo": "L-int", "L-ind-geo": "L-ind"}
BOOT_SEED = 20261111
N_COMPARISONS = 11                 # GN, GA, GC, GK1 (2), GK2 (2), GD (2), GX (2)
EXPECTED_COLL_EVENTS_PER_40 = 267  # exploration round A, s4x-p2a
EXPECTED_COLL_DISK_STEPS_PER_40 = A.EXPECTED_COLL_DISK_STEPS_PER_40
SAMPLE_BAND = A.SAMPLE_BAND
DYN_FLOOR = A.DYN_FLOOR
GAP_BINS = (0, 10, 25, 50)         # reappearance coverage by hidden length: [0,10), [10,25), [25,50), [50, inf)

THRESHOLDS = {
    "GN": {"diff": -0.01, "diff_low": -0.03},
    "GA": {"diff": 0.03, "diff_low": 0.0},
    "GC": {"C": 0.75, "C_low": 0.5},
    "GK1": {"all": (0.87, 0.93), "all_interval": (0.85, 0.95), "collision": 0.85, "collision_low": 0.80},
    "GK2": {"non_collision": 0.85, "non_collision_low": 0.80, "collision": 0.75, "collision_low": 0.65},
    "GD": {"D": 0.8, "D_low": 0.7, "ratio": 0.10, "ratio_high": 0.15},
    "GX": {"diff": 0.03, "diff_low": 0.0, "C": 0.6, "C_low": 0.4},
    "negative_control": {"C_high_below": 0.5, "D_high_below": 0.5},
}


def eval_world_ids(stage_sizes: tuple[int, int]) -> list[tuple[str, int, int]]:
    return A.eval_world_ids(stage_sizes)


def cell_key(arm: str, seed: int) -> str:
    return f"{arm}#{seed}"


def filter_seed(ns: str, w: int, seed: int) -> int:
    return A.filter_seed(ns, w, seed, "base")


def ids_digest(ids: Sequence[np.ndarray]) -> str:
    return hashlib.sha256(json.dumps([np.asarray(i).tolist() for i in ids]).encode()).hexdigest()


# --- hooks (read-only: on_predict gets copies) -----------------------------------------------------
def _gauss_inside(x: np.ndarray, truth: np.ndarray) -> bool:
    """Whether ``truth`` lies in the 90% ellipse of the ensemble ``x`` [M, 2] (mean, sample covariance)."""
    mu = x.mean(0)
    cov = np.cov(x.T) + np.eye(2) * 1e-9
    d = truth - mu
    return bool(float(d @ np.linalg.solve(cov, d)) <= A.CHI2_2_90)


class Calibration:
    """``on_predict`` hook. One-step rows: a track assigned at t-1 and t, the predicted ensemble at t
    against the true position of the detected disk, split by whether that disk had a disk contact in
    the step t-1 -> t. Reappearance: the predicted ensembles of all tracks at the steps ``want``."""

    def __init__(self, ep: W.Episode, want: Sequence[int]):
        self.ep = ep
        self.want = set(want)
        self.one = {"collision": [0, 0], "other": [0, 0]}      # [rows, inside]
        self.snaps: dict[int, np.ndarray] = {}

    def __call__(self, t, P, V, assign, last):
        s = self.ep.steps[t]
        if t in self.want:
            self.snaps[t] = P.copy()
        if t == 0:
            return
        touched = {i for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"} | {j for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"}
        for r, k in assign.items():
            if last[k] != t - 1:
                continue
            truth = int(s.truth_ids[r])
            row = self.one["collision" if truth in touched else "other"]
            row[0] += 1
            row[1] += int(_gauss_inside(P[:, k], s.positions[truth]))


def reappearance_inside(ep: W.Episode, ids: Sequence[np.ndarray], events: Sequence[dict], snaps: Mapping[int, np.ndarray]) -> list[int]:
    """Per event: whether the true position at b lies in the 90% ellipse of the ensemble predicted at b
    (before the update) for the track that held the disk at a."""
    at = [dict(zip(s.truth_ids.tolist(), np.asarray(i).tolist())) for s, i in zip(ep.steps, ids)]
    out = []
    for e in events:
        trk = at[e["a"]][e["k"]]
        out.append(int(_gauss_inside(snaps[e["b"]][:, trk], ep.steps[e["b"]].positions[e["k"]])))
    return out


# --- one world ------------------------------------------------------------------------------------
def track_cell(ep: W.Episode, model: Callable, ns: str, seed: int, events: Sequence[dict]) -> dict[str, Any]:
    rng = np.random.default_rng(filter_seed(ns, ep.world_index, seed))
    cal = Calibration(ep, [e["b"] for e in events])
    ids, n_tracks = F.track(A.student_detections(ep), ep.pillars, model, rng, F.FilterConfig(), on_predict=cal)
    return {"correct": [x["correct"] for x in Me.reid(ep, ids, events)], "one_step": cal.one,
            "reappear": reappearance_inside(ep, ids, events, cal.snaps), "idf1": Me.idf1(ep, ids),
            "n_tracks": n_tracks, "ids_sha256": ids_digest(ids)}


def world_record(ep: W.Episode, kind: str, ns: str, models: Mapping[str, Callable], *, counters: Mapping[str, list] | None = None,
                 dyn_models: Mapping[str, Callable] | None = None) -> dict[str, Any]:
    """``models`` maps a hand arm or a learned arm#seed to its process model; every hand arm is
    tracked with the three filter seeds. ``counters`` (arm#seed -> [open, all]) are reset per cell and
    give the gate share. ``dyn_models`` (name -> model) get the dynamics sums from the exact truth."""
    events = W.reappearances(ep)
    rec: dict[str, Any] = {"kind": kind, "world": ep.world_index, "n_disks": ep.n_disks,
                           "events": [[e["k"], e["a"], e["b"], int(e["collision"]), e["gap"]] for e in events],
                           "cells": {}, "dyn": {}}
    for name, m in models.items():
        seeds = [int(name.split("#")[1])] if "#" in name else list(SEEDS)
        arm = name.split("#")[0]
        for s in seeds:
            c = counters.get(f"{arm}#{s}") if counters else None
            if c is not None:
                c[0] = c[1] = 0
            cell = track_cell(ep, m, ns, s, events)
            if c is not None:
                cell["gate"] = [int(c[0]), int(c[1])]
            rec["cells"][cell_key(arm, s)] = cell
    for name, m in (dyn_models or {}).items():
        rec["dyn"][name] = A.dyn_sums(ep, m)
    return rec


# --- aggregation -----------------------------------------------------------------------------------
def _event_mean(r: dict, arm: str, field: str) -> np.ndarray:
    return np.mean([np.asarray(r["cells"][cell_key(arm, s)][field], dtype=np.float64) for s in SEEDS], axis=0) if r["events"] else np.zeros(0)


def _mask(r: dict, which: str) -> np.ndarray:
    coll = np.array([e[3] == 1 for e in r["events"]], dtype=bool)
    return {"collision": coll, "non_collision": ~coll, "all": np.ones_like(coll)}[which]


def event_sums(records: Sequence[dict], arm: str, which: str, field: str = "correct") -> np.ndarray:
    """Per world: sum over the events of ``which`` of the seed-averaged ``field``."""
    return np.array([float(_event_mean(r, arm, field)[_mask(r, which)].sum()) if r["events"] else 0.0 for r in records])


def event_counts(records: Sequence[dict], which: str) -> np.ndarray:
    return np.array([float(_mask(r, which).sum()) if r["events"] else 0.0 for r in records])


def one_step_sums(records: Sequence[dict], arm: str, which: str) -> tuple[np.ndarray, np.ndarray]:
    """Per world (inside, rows) of the one-step coverage, the three seeds pooled; which: collision or all."""
    parts = ("collision",) if which == "collision" else ("collision", "other")
    ins = np.array([float(sum(r["cells"][cell_key(arm, s)]["one_step"][p][1] for s in SEEDS for p in parts)) for r in records])
    n = np.array([float(sum(r["cells"][cell_key(arm, s)]["one_step"][p][0] for s in SEEDS for p in parts)) for r in records])
    return ins, n


def _boot(stat, sums, m):
    return Me.bootstrap(stat, sums, seed=BOOT_SEED, m=m)


def acc_of(records, arm, which, *, m=1):
    return _boot(Me.stat_diff, {"x": event_sums(records, arm, which), "y": np.zeros(len(records)), "n": event_counts(records, which)}, m)


def acc_diff(records, a, b, which, *, m=N_COMPARISONS):
    return _boot(Me.stat_diff, {"x": event_sums(records, a, which), "y": event_sums(records, b, which), "n": event_counts(records, which)}, m)


def C_of(records, arm, *, m=N_COMPARISONS):
    return _boot(Me.stat_C, {"x": event_sums(records, arm, "collision"), "b": event_sums(records, "E-B", "collision"),
                             "p": event_sums(records, "E-P", "collision")}, m)


def coverage_one_step(records, arm, which, *, m=N_COMPARISONS):
    ins, n = one_step_sums(records, arm, which)
    return _boot(Me.stat_diff, {"x": ins, "y": np.zeros(len(records)), "n": n}, m)


def coverage_reappear(records, arm, which, *, m=N_COMPARISONS):
    return _boot(Me.stat_diff, {"x": event_sums(records, arm, which, "reappear"), "y": np.zeros(len(records)), "n": event_counts(records, which)}, m)


def _dyn(records, name, field):
    return np.array([np.mean([r["dyn"][f"{name}#{s}"][field] for s in SEEDS]) if f"{name}#1" in r["dyn"] else r["dyn"][name][field] for r in records],
                    dtype=np.float64)


def D_of(records, name, *, m=N_COMPARISONS):
    return _boot(Me.stat_D, {"x_coll": _dyn(records, name, "coll"), "b_coll": _dyn(records, "E-B", "coll")}, m)


def HF_of(records, name, *, m=N_COMPARISONS):
    return _boot(Me.stat_HF, {"x_graze": _dyn(records, name, "graze"), "n_graze": _dyn(records, name, "n_graze"),
                              "b_coll": _dyn(records, "E-B", "coll"), "n_coll": _dyn(records, "E-B", "n_coll")}, m)


# --- gates -----------------------------------------------------------------------------------------
def legality(main, extrap, *, n_main, n_extrap, labels_ok, student_ok, replay_ok, weights_ok) -> dict[str, Any]:
    acc = {a: acc_of(main, a, "collision")["value"] for a in ("E-CV", "E-B", "E-P")}
    missing = [a for a, v in acc.items() if v is None]
    floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]
    n_coll_events = int(event_counts(main, "collision").sum())
    expected = EXPECTED_COLL_EVENTS_PER_40 * n_main / 40
    n_coll_steps = int(_dyn(main, "E-B", "n_coll").sum()) if main else 0
    dyn_expected = EXPECTED_COLL_DISK_STEPS_PER_40 * n_main / 40
    return {
        "labels": {"passed": bool(labels_ok)},
        "student_view": {"passed": bool(student_ok)},
        "floor": {"passed": bool(floor), "acc": acc, **({"undefined": missing} if missing else {})},
        "complete": {"passed": len(main) == n_main and len(extrap) == n_extrap, "main": len(main), "extrap": len(extrap),
                     "registered": [n_main, n_extrap]},
        "samples": {"passed": bool(abs(n_coll_events - expected) <= SAMPLE_BAND * expected and n_coll_steps >= DYN_FLOOR * dyn_expected),
                    "collision_events": n_coll_events, "expected": expected, "collision_disk_steps": n_coll_steps, "dyn_expected": dyn_expected},
        "determinism": {"passed": bool(replay_ok)},
        "weights": {"passed": bool(weights_ok)},
    }


def _ge(stat, key, thr):
    v = stat.get(key)
    return v is not None and v >= thr


def _gt(stat, key, thr):
    v = stat.get(key)
    return v is not None and v > thr


def _le(stat, key, thr):
    v = stat.get(key)
    return v is not None and v <= thr


def _lt(stat, key, thr):
    v = stat.get(key)
    return v is not None and v < thr


def gate_stats(main, extrap) -> dict[str, dict]:
    """Every statistic a gate or the negative control reads (Bonferroni m = N_COMPARISONS for the gates)."""
    a = MAIN_ARM
    return {"GN": acc_diff(main, a, "E-B", "non_collision"), "GA": acc_diff(main, a, "E-B", "all"), "GC": C_of(main, a),
            "GK1_all": coverage_one_step(main, a, "all"), "GK1_collision": coverage_one_step(main, a, "collision"),
            "GK2_non_collision": coverage_reappear(main, a, "non_collision"), "GK2_collision": coverage_reappear(main, a, "collision"),
            "GD_D": D_of(main, a), "GD_ratio": HF_of(main, a),
            "GX_diff": acc_diff(extrap, a, "E-B", "all"), "GX_C": C_of(extrap, a),
            "neg_C": C_of(main, NEG_ARM, m=1), "neg_D": D_of(main, NEG_ARM, m=1)}


def decide(st: Mapping[str, dict]) -> tuple[dict[str, bool], bool]:
    """(passed per gate, negative control passed) from the statistics alone. A missing value or bound fails."""
    T = THRESHOLDS
    lo1, hi1 = T["GK1"]["all"]
    lo1i, hi1i = T["GK1"]["all_interval"]
    k1a, k1c = st["GK1_all"], st["GK1_collision"]
    k2n, k2c = st["GK2_non_collision"], st["GK2_collision"]
    d, hf = st["GD_D"], st["GD_ratio"]
    passed = {
        "GN": _ge(st["GN"], "value", T["GN"]["diff"]) and _gt(st["GN"], "bonf_low", T["GN"]["diff_low"]),
        "GA": _ge(st["GA"], "value", T["GA"]["diff"]) and _gt(st["GA"], "bonf_low", T["GA"]["diff_low"]),
        "GC": _ge(st["GC"], "value", T["GC"]["C"]) and _gt(st["GC"], "bonf_low", T["GC"]["C_low"]),
        "GK1": (_ge(k1a, "value", lo1) and _le(k1a, "value", hi1) and _ge(k1a, "bonf_low", lo1i) and _le(k1a, "bonf_high", hi1i)
                and _ge(k1c, "value", T["GK1"]["collision"]) and _gt(k1c, "bonf_low", T["GK1"]["collision_low"])),
        "GK2": (_ge(k2n, "value", T["GK2"]["non_collision"]) and _gt(k2n, "bonf_low", T["GK2"]["non_collision_low"])
                and _ge(k2c, "value", T["GK2"]["collision"]) and _gt(k2c, "bonf_low", T["GK2"]["collision_low"])),
        "GD": (_ge(d, "value", T["GD"]["D"]) and _gt(d, "bonf_low", T["GD"]["D_low"])
               and _le(hf, "value", T["GD"]["ratio"]) and _le(hf, "bonf_high", T["GD"]["ratio_high"])),
        "GX": (_ge(st["GX_diff"], "value", T["GX"]["diff"]) and _gt(st["GX_diff"], "bonf_low", T["GX"]["diff_low"])
               and _ge(st["GX_C"], "value", T["GX"]["C"]) and _gt(st["GX_C"], "bonf_low", T["GX"]["C_low"])),
    }
    neg = (_lt(st["neg_C"], "ci_high", T["negative_control"]["C_high_below"])
           and _lt(st["neg_D"], "ci_high", T["negative_control"]["D_high_below"]))
    return {k: bool(v) for k, v in passed.items()}, bool(neg)


GATE_STATS = {"GN": ("GN",), "GA": ("GA",), "GC": ("GC",), "GK1": ("GK1_all", "GK1_collision"),
              "GK2": ("GK2_non_collision", "GK2_collision"), "GD": ("GD_D", "GD_ratio"), "GX": ("GX_diff", "GX_C")}


def evaluate(main, extrap, *, n_main, n_extrap, labels_ok, student_ok, replay_ok, weights_ok) -> dict[str, Any]:
    lg = legality(main, extrap, n_main=n_main, n_extrap=n_extrap, labels_ok=labels_ok, student_ok=student_ok,
                  replay_ok=replay_ok, weights_ok=weights_ok)
    valid = all(v["passed"] for v in lg.values())
    st = gate_stats(main, extrap)
    passed, neg_ok = decide(st)
    g = {k: {"passed": passed[k], **{name: st[name] for name in GATE_STATS[k]}} for k in GATE_STATS}
    neg = {"passed": neg_ok, "C": st["neg_C"], "D": st["neg_D"]}
    if not neg_ok:
        for k in ("GA", "GC", "GX"):
            g[k] = dict(g[k], passed=False, void="negative control failed")
    if not valid:
        for k in g:
            g[k] = dict(g[k], passed=False, void="legality failed")
    return {"valid": valid, "legality": lg, "negative_control": neg, "gates": g}


# --- descriptive -----------------------------------------------------------------------------------
def gap_coverage(records, arm) -> dict[str, float | None]:
    out = {}
    edges = list(GAP_BINS) + [10 ** 9]
    for lo, hi in zip(edges[:-1], edges[1:]):
        x = n = 0.0
        for r in records:
            if not r["events"]:
                continue
            per = _event_mean(r, arm, "reappear")
            gaps = np.array([e[4] for e in r["events"]])
            m = (gaps >= lo) & (gaps < hi)
            x += float(per[m].sum()); n += float(m.sum())
        out[f"{lo}-{hi if hi < 10 ** 9 else 'inf'}"] = x / n if n else None
    return out


def summarize_descriptive(main, extrap, arms: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for part, recs in (("main", main), ("extrap", extrap)):
        if not recs:
            continue
        d: dict[str, Any] = {}
        for arm in arms:
            row = {f"acc_{w}": acc_of(recs, arm, w)["value"] for w in ("collision", "non_collision", "all")}
            row["one_step_all"] = coverage_one_step(recs, arm, "all", m=1)["value"]
            row["one_step_collision"] = coverage_one_step(recs, arm, "collision", m=1)["value"]
            row["reappear_non_collision"] = coverage_reappear(recs, arm, "non_collision", m=1)["value"]
            row["reappear_collision"] = coverage_reappear(recs, arm, "collision", m=1)["value"]
            row["reappear_by_gap"] = gap_coverage(recs, arm)
            row["idf1"] = float(np.mean([np.mean([r["cells"][cell_key(arm, s)]["idf1"] for s in SEEDS]) for r in recs]))
            row["n_tracks"] = float(np.mean([np.mean([r["cells"][cell_key(arm, s)]["n_tracks"] for s in SEEDS]) for r in recs]))
            if arm not in HAND:
                row["C"] = C_of(recs, arm, m=1)
                row["diff_non_collision_vs_EB"] = acc_diff(recs, arm, "E-B", "non_collision", m=1)
                row["diff_all_vs_EB"] = acc_diff(recs, arm, "E-B", "all", m=1)
            if arm in GATES:
                o = sum(r["cells"][cell_key(arm, s)].get("gate", [0, 0])[0] for r in recs for s in SEEDS)
                t = sum(r["cells"][cell_key(arm, s)].get("gate", [0, 0])[1] for r in recs for s in SEEDS)
                row["gate_share"] = o / t if t else None
            d[arm] = row
        out[part] = d
    out["dynamics"] = {part: {name: {"D": D_of(recs, name, m=1)["value"], "HF": HF_of(recs, name, m=1)["value"]}
                              for name in ("L-int", *GATES)} for part, recs in (("main", main), ("extrap", extrap)) if recs}
    return out
