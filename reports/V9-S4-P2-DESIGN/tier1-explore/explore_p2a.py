#!/usr/bin/env python3
"""S4 phase 2 exploration, round A (namespace s4x-p2a; exploration only, not a result).

Uses the phase-1 final weights read-only. Diagnoses the phase-1 learned process model inside the
registered ensemble Kalman filter:
  A1. one-step predictive coverage of tracks seen at t-1 and t, split by the step kind of the
      detected disk during t-1 -> t (collision / graze / free), with squared bias and spread;
  A2. model error on the filter's own member states, labels from the simulator on those states:
      D_filter = 1 - err(model) / err(E-B) on members whose velocity a disk interaction changes,
      and the velocity error on the other members;
  A3. track breaks: tracks born for a disk detected at t-1 (visible break) or after a gap;
  A4. process-noise scales for E-B and L-int: coverage, NLL, re-identification, IDF1, tracks.

Usage (MLX, so under the shared lock):
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py \
      artifacts/locks/m0-worker.lock .venv/bin/python <this> N_WORLDS OUT.json
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import replace

import mlx.core as mx
import numpy as np

from ainerzero.v9.experiments.s4 import analysis as A
from ainerzero.v9.experiments.s4 import filter as F
from ainerzero.v9.experiments.s4 import learned_mlx as L
from ainerzero.v9.experiments.s4 import metrics as Me
from ainerzero.v9.experiments.s4 import models as Mo
from ainerzero.v9.experiments.s4 import world as W

NS = "s4x-p2a"
WDIR = "artifacts/v9/s4/phase1/final-final/weights"
SEEDS = (1, 2, 3)
SCALES = {"q1": (1, 1), "q1.5": (1.5, 1.5), "q2": (2, 2), "q3": (3, 3), "qp3": (3, 1), "qv3": (1, 3)}
PROBE_EVERY = 5


def step_kinds(ep, t):
    """Kind of every disk for the step t-1 -> t: 0 disk contact, 1 graze, 2 free."""
    s, nxt = ep.steps[t - 1], ep.steps[t]
    coll = {i for k, i, j in s.contacts if k == "disk"} | {j for k, i, j in s.contacts if k == "disk"}
    d = np.linalg.norm(nxt.positions[:, None] - nxt.positions[None], axis=-1) + np.eye(ep.n_disks) * 1e9
    return np.array([0 if i in coll else (1 if d[i].min() < A.GRAZE else 2) for i in range(ep.n_disks)])


class Calib:
    def __init__(self, ep):
        self.ep, self.rows = ep, []

    def __call__(self, t, P, V, assign, last):
        if t == 0:
            return
        s = self.ep.steps[t]
        kinds = step_kinds(self.ep, t)
        for r, k in assign.items():
            if last[k] != t - 1:
                continue
            x = P[:, k]
            mu = x.mean(0)
            cov = np.cov(x.T) + np.eye(2) * 1e-9
            truth = int(s.truth_ids[r])
            d = s.positions[truth] - mu
            m2 = float(d @ np.linalg.solve(cov, d))
            nll = float(0.5 * (np.log((2 * np.pi) ** 2 * np.linalg.det(cov)) + m2))
            self.rows.append((int(kinds[truth]), m2 <= A.CHI2_2_90, nll, float(d @ d), float(np.trace(cov))))


class Probe:
    """Wraps a process model; every PROBE_EVERY-th call compares it with the simulator on the same member states."""

    def __init__(self, model):
        self.model, self.calls = model, 0
        self.s = dict(coll_m=0.0, coll_b=0.0, n_coll=0, free_m=0.0, free_pos=0.0, n_free=0, coll_pos=0.0)

    def __call__(self, P, V, pillars):
        out = self.model(P, V, pillars)
        self.calls += 1
        if self.calls % PROBE_EVERY == 0 and P.shape[1] >= 2:
            tp, tv, _ = W.physics(P, V, pillars)
            bp, bv, _ = W.physics(P, V, pillars, disks=False)
            hit = np.linalg.norm(tv - bv, axis=-1) > 1e-6
            em = np.linalg.norm(np.asarray(out[1]) - tv, axis=-1)
            ep_ = np.linalg.norm(np.asarray(out[0]) - tp, axis=-1)
            eb = np.linalg.norm(bv - tv, axis=-1)
            self.s["coll_m"] += float(em[hit].sum()); self.s["coll_b"] += float(eb[hit].sum()); self.s["n_coll"] += int(hit.sum())
            self.s["coll_pos"] += float(ep_[hit].sum())
            self.s["free_m"] += float(em[~hit].sum()); self.s["free_pos"] += float(ep_[~hit].sum()); self.s["n_free"] += int((~hit).sum())
        return out


def breaks(ep, ids):
    seen_track: dict[int, int] = {}
    births = {"first": 0, "visible": 0, "gap": 0}
    swaps = 0
    prev: dict[int, int] = {}
    known = set()
    for t, (s, i) in enumerate(zip(ep.steps, ids)):
        cur = dict(zip(s.truth_ids.tolist(), np.asarray(i).tolist()))
        for k, trk in cur.items():
            if trk not in seen_track:
                seen_track[trk] = t
                births["first" if k not in known else ("visible" if k in prev else "gap")] += 1
            elif k in prev and prev[k] != trk:
                swaps += 1
            known.add(k)
        prev = cur
    return births, swaps


def main():
    n_worlds, out_path = int(sys.argv[1]), sys.argv[2]
    mx.set_default_device(mx.cpu)
    nets = {s: L.as_process_model(L.load("L-int", f"{WDIR}/L-int#{s}.safetensors")) for s in SEEDS}
    t0 = time.time()
    res = {"namespace": NS, "n_worlds": n_worlds, "weights": WDIR, "per_world": []}
    for w in range(n_worlds):
        ep = W.generate_episode(NS, w, A.MAIN_DISKS)
        events = W.reappearances(ep)
        dets = A.student_detections(ep)
        rec = {"world": w, "events": [[e["k"], e["a"], e["b"], int(e["collision"])] for e in events], "cells": {}}
        runs = [("E-P", "q1")] + [(arm, tag) for arm in ("E-B", "L-int") for tag in SCALES]
        for arm, tag in runs:
            for s in SEEDS:
                sp, sv = SCALES[tag]
                cfg = replace(F.FilterConfig(), q_pos=0.01 * sp, q_vel=0.05 * sv)
                base = {"E-P": Mo.true_physics, "E-B": Mo.bounce}.get(arm) or nets[s]
                probe = Probe(base) if tag == "q1" else None
                cal = Calib(ep)
                rng = np.random.default_rng(W.derive_seed(NS, "filter", w, s, tag))
                ids, n_tracks = F.track(dets, ep.pillars, probe or base, rng, cfg, on_predict=cal)
                b, sw = breaks(ep, ids)
                rows = np.array(cal.rows, dtype=np.float64).reshape(-1, 5)
                calib = {}
                for kname, kk in (("all", None), ("collision", 0), ("graze", 1), ("free", 2)):
                    m = np.ones(len(rows), bool) if kk is None else rows[:, 0] == kk
                    calib[kname] = [int(m.sum()), float(rows[m, 1].sum()), float(rows[m, 2].sum()), float(rows[m, 3].sum()), float(rows[m, 4].sum())]
                rec["cells"][f"{arm}#{s}@{tag}"] = {
                    "correct": [x["correct"] for x in Me.reid(ep, ids, events)], "idf1": Me.idf1(ep, ids),
                    "n_tracks": n_tracks, "births": b, "swaps": sw, "calib": calib,
                    "probe": probe.s if probe else None}
        res["per_world"].append(rec)
        print(f"world {w} done {time.time() - t0:.0f}s", flush=True)
    res["elapsed_s"] = time.time() - t0
    with open(out_path, "w") as f:
        json.dump(res, f)


if __name__ == "__main__":
    main()
