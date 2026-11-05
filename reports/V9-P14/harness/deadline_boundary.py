#!/usr/bin/env python3
"""P14 reviewer: boundary case for the #349 deadline-accumulation defect.

claude's #356 asks specifically for "a 2nd training call approaching 450 s".
This harness drives the real r4 train path in-process on the fake clock:

  A  arm2 seed0, small clock step  -> a normal short run
     (400 s of phase wall clock then elapse, so any *phase-cumulative* timer
      would already be far past 450 s)
  B  arm2 seed1, clock step scaled so this call's OWN window ~= 449 s
     -> must still complete (exit 0): the per-call deadline restarts each call
  C  arm3 seed0, clock step scaled so this call's OWN window would exceed 450 s
     -> must FAIL with `TimeoutError: frozen per-run deadline exceeded`
        (negative control: the deadline is real, not disabled)

The clock step is calibrated from the observed short run, because the loop
advances the fake clock a fixed amount per update (3 perf_counter calls plus a
duty-cycle sleep proportional to the step).

Read-only w.r.t. the real tree; artefacts land in a temp sandbox.
Output: reports/V9-P14/evidence/deadline-boundary-p14.json
"""
from __future__ import annotations

import contextlib
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

REAL = Path("/Users/mac/AinerWorkFlow/AinerZero")
HERE = REAL / "reports" / "V9-P14" / "harness"
EV = REAL / "reports" / "V9-P14" / "evidence"
sys.path[:0] = [str(HERE), str(REAL / "src"), str(REAL / "tests/v9/experiments")]

import full_flow as ff  # noqa: E402  (reviewer's own sibling harness)
import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import mlx.optimizers as optim  # noqa: E402

from ainerzero.v9.experiments.s1 import arms, commands, spec, worker  # noqa: E402
from test_s1_pacer_duty import _FakeClock, _FakeModel, _FakeOptimizer  # noqa: E402


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="p14-boundary-", dir=tempfile.gettempdir()))
    sb = ff.build_sandbox(root)
    clock = _FakeClock(step=0.01)
    nll_calls: list[float] = []

    def fake_nll(*_a, **_k):
        value = 2.5 - 0.1 * len(nll_calls)
        nll_calls.append(round(value, 6))
        return value

    windows: list[dict] = []
    real_train = worker._train

    def observing_train(*args, **kwargs):
        start = clock.now
        try:
            return real_train(*args, **kwargs)
        finally:
            windows.append({"start": start, "end": clock.now, "elapsed": clock.now - start})

    updates = int(sb["document"]["training_protocol"]["updates"])
    out: dict = {
        "schema": "ainerzero.v9.p14.deadline-boundary.v1",
        "sandbox": str(root),
        "frozen_updates_per_run": updates,
        "fake_clock_step_seconds_base": clock.step,
        "ledger_waiver": {
            "applied": True,
            "what": "max_optimizer_steps headroom (run + experiment-per-run)",
            "why": "same as full-flow; see evidence/train-ledger-probe.json",
            "not_waived": "deadline, supervision, phase wall cap, updates, seeds, checkpoint policy",
        },
        "calls": [],
    }

    stack = contextlib.ExitStack()
    try:
        stack.enter_context(patch.object(spec, "RESEARCH_LOG", sb["log"]))
        stack.enter_context(
            patch.object(commands, "_supervised_worker", ff.in_process_supervisor([])))
        updates_per_run = int(sb["document"]["training_protocol"]["updates"])
        real_rcs = worker.run_config_snapshot

        def waived_rcs(*, wall_budget_seconds, purpose):
            snap = real_rcs(wall_budget_seconds=wall_budget_seconds, purpose=purpose)
            snap["budget"]["max_optimizer_steps"] = updates_per_run + 1000
            return snap

        stack.enter_context(patch.object(worker, "run_config_snapshot", waived_rcs))
        real_tem = worker.train_experiment_manifest

        def waived_tem(*, deadline_seconds, updates):
            man = real_tem(deadline_seconds=deadline_seconds, updates=updates)
            man["budget"]["max_optimizer_steps"] = updates + 1000
            return man

        stack.enter_context(patch.object(worker, "train_experiment_manifest", waived_tem))
        stack.enter_context(patch.object(worker, "time", clock))
        stack.enter_context(patch.object(worker, "_train", observing_train))
        stack.enter_context(patch.object(worker, "_development_nll", fake_nll))
        stack.enter_context(patch.object(worker.data, "resolve_dataset_dir", lambda _root: sb["dataset_dir"]))
        stack.enter_context(patch.object(worker.data, "load_training_windows",
                                         lambda *a, **k: {"obs": np.zeros((4, 2, 72))}))
        stack.enter_context(patch.object(worker.data, "load_development_windows",
                                         lambda *a, **k: {"obs": np.zeros((1, 2, 72))}))
        stack.enter_context(patch.object(worker.data, "iter_batches",
                                         lambda *a, **k: iter([{"obs": None}] * 40_000)))
        stack.enter_context(patch.object(arms, "build_trainable_arm", lambda arm_id, **kw: _FakeModel()))
        stack.enter_context(patch.object(arms, "parameter_sha256", lambda model: "0" * 64))
        stack.enter_context(patch.object(nn, "value_and_grad",
                                         lambda model, loss: (lambda m, b: ((np.float32(1.0), {}), {}))))
        stack.enter_context(patch.object(optim, "AdamW", _FakeOptimizer))
        stack.enter_context(patch.object(optim, "clip_grad_norm", lambda g, n: (g, 1.0), create=True))
        stack.enter_context(patch.object(mx, "eval", lambda *a, **k: None))
        stack.enter_context(patch.object(mx, "set_default_device", lambda *a, **k: None, create=True))

        deadline = float(sb["document"]["timing"]["deadline_seconds"])

        def call(arm, seed, step, label):
            clock.step = step
            before = len(windows)
            phase_before = clock.now
            report = commands.mode_train(SimpleNamespace(
                mode="train", output_root=sb["phase1"], prereg=sb["prereg"], limits_file=None,
                wall_budget_seconds=None, research_log=None, arm=arm, seed=seed))
            win = windows[before] if len(windows) > before else None
            row = {
                "label": label, "arm": arm, "seed": seed,
                "clock_step_seconds": step,
                "own_window_seconds": None if win is None else round(win["elapsed"], 6),
                "phase_clock_before": round(phase_before, 6),
                "phase_clock_after": round(clock.now, 6),
                "cumulative_phase_seconds_since_first_call": round(clock.now - out["calls"][0]["phase_clock_before"], 6)
                if out["calls"] else 0.0,
                "status": report.get("status"),
                "error": (report.get("error") or "")[:120],
                "exit_code": commands._exit_code_for(report),
                "run_id": report.get("run_id"),
            }
            out["calls"].append(row)
            return row

        # A: short calibration run
        a = call("arm2", 0, 0.01, "A_short_calibration")
        per_update = a["own_window_seconds"] / updates
        out["calibration"] = {
            "own_window_seconds": a["own_window_seconds"],
            "seconds_per_update_at_step_0.01": round(per_update, 8),
            "predicted_linear_seconds_per_update_per_step": 6.0,
        }

        # 400 s of phase wall clock between CLI invocations
        clock.now += 400.0

        # B: this call's own window ~= 449 s (near the 450 s boundary)
        step_b = 0.01 * 449.0 / a["own_window_seconds"]
        b = call("arm2", 1, step_b, "B_second_call_near_450s")

        # C: negative control, own window ~= 451 s (just over the deadline)
        step_c = 0.01 * 451.0 / a["own_window_seconds"]
        c = call("arm3", 0, step_c, "C_second_call_over_450s")

        checks = {
            "A_short_run_completed": a["status"] == "completed" and a["exit_code"] == 0,
            "B_own_window_near_but_under_450": (
                b["own_window_seconds"] is not None and 430.0 < b["own_window_seconds"] < deadline),
            "B_completed_despite_cumulative_over_450": (
                b["status"] == "completed" and b["exit_code"] == 0
                and b["cumulative_phase_seconds_since_first_call"] > deadline),
            "C_refused_with_deadline_timeout": (
                c["status"] == "failed" and "TimeoutError" in c["error"]
                and "deadline" in c["error"]),
            "C_negative_control_proves_deadline_live": c["exit_code"] != 0,
        }
        out["checks"] = checks
        out["counterfactual"] = {
            "shared_started_would_refuse_B": True,
            "cumulative_phase_seconds_at_B": b["cumulative_phase_seconds_since_first_call"],
            "note": "a module/phase-level `started` would see >450 s at B's first update and "
                    "raise TimeoutError; B completing shows the timer restarts per call.",
        }
        out["verdict"] = "boundary_pass" if all(checks.values()) else "boundary_fail"
    finally:
        stack.close()

    EV.mkdir(parents=True, exist_ok=True)
    (EV / "deadline-boundary-p14.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"verdict": out["verdict"], "checks": out["checks"],
                      "calls": [(r["label"], r["own_window_seconds"], r["status"]) for r in out["calls"]]},
                     ensure_ascii=False))
    return 0 if out.get("verdict") == "boundary_pass" else 1


if __name__ == "__main__":
    sys.exit(main())
