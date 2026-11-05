#!/usr/bin/env python3
"""V9.P14 focused probe: can one registered r4 train run ever write a checkpoint?

Three scenarios, each driving exactly one `--mode train` invocation through the
real `commands.mode_train` + `worker.run_worker` + `worker._train` + real
RunStore (sandbox ledger), with the fake clock/model fakes the project's own
timing tests use:

  A. as shipped: `run_config_snapshot()` -> `_budget_block()` defaults to
     max_optimizer_steps=1, while `_train` reserves one optimizer step per update.
  B. run budget = the frozen `updates` (the largest value the experiment ceiling
     admits): RunStore refuses any reserve once a remaining count is <= 0, so the
     zero-step checkpoint reservation on the final update is still refused.
  C. run budget = updates + 1: `create_run` refuses a run budget that exceeds the
     experiment ceiling, which `train_experiment_manifest` pins at `updates`.

Read-only for the real tree; writes reports/V9-P14/evidence/train-ledger-probe.json.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

REPO = Path("/Users/mac/AinerWorkFlow/AinerZero")
OUT_DIR = REPO / "reports/V9-P14"
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests/v9/experiments"), str(REPO / "reports/V9-P14/harness")]

import mlx.core as mx  # noqa: E402
import mlx.nn as nn  # noqa: E402
import mlx.optimizers as optim  # noqa: E402

from ainerzero.v9.experiments.s1 import arms, commands, spec, worker  # noqa: E402
from ainerzero.v9.experiments.s1.worker import PrepLedger  # noqa: E402
from test_s1_pacer_duty import _FakeClock, _FakeModel, _FakeOptimizer  # noqa: E402

import full_flow  # noqa: E402

REAL_RESERVE = PrepLedger.reserve


def run_scenario(sb: dict, shadow: dict, clock: _FakeClock, rcs_override, reserves: list):
    """One train invocation with the ledger budget shaped by `rcs_override`."""

    def counting_reserve(self, run_id, *, active_seconds, optimizer_steps=0):
        reserves.append((float(active_seconds), int(optimizer_steps)))
        return REAL_RESERVE(self, run_id, active_seconds=active_seconds, optimizer_steps=optimizer_steps)

    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(spec, "RESEARCH_LOG", sb["log"]))
        # Never reach commands._supervised_worker: it would take the real lock.
        stack.enter_context(patch.object(commands, "_supervised_worker", full_flow.in_process_supervisor([])))
        if rcs_override is not None:
            stack.enter_context(patch.object(worker, "run_config_snapshot", rcs_override))
        stack.enter_context(patch.object(worker, "time", clock))
        stack.enter_context(patch.object(worker, "_development_nll", lambda *a, **k: 1.0))
        stack.enter_context(
            patch.object(worker.data, "resolve_dataset_dir", lambda _r: shadow["dataset_dir"])
        )
        stack.enter_context(
            patch.object(worker.data, "load_training_windows", lambda *a, **k: {"obs": np.zeros((4, 2, 72))})
        )
        stack.enter_context(
            patch.object(worker.data, "load_development_windows", lambda *a, **k: {"obs": np.zeros((1, 2, 72))})
        )
        stack.enter_context(
            patch.object(worker.data, "iter_batches", lambda *a, **k: iter([{"obs": None}] * 40_000))
        )
        stack.enter_context(patch.object(arms, "build_trainable_arm", lambda arm_id, **k: _FakeModel()))
        stack.enter_context(patch.object(arms, "parameter_sha256", lambda m: "0" * 64))
        stack.enter_context(
            patch.object(nn, "value_and_grad", lambda m, l: (lambda mm, b: ((np.float32(1.0), {}), {})))
        )
        stack.enter_context(patch.object(optim, "AdamW", _FakeOptimizer))
        stack.enter_context(patch.object(optim, "clip_grad_norm", lambda g, n: (g, 1.0), create=True))
        stack.enter_context(patch.object(mx, "eval", lambda *a, **k: None))
        stack.enter_context(patch.object(mx, "set_default_device", lambda *a, **k: None, create=True))
        stack.enter_context(patch.object(PrepLedger, "reserve", counting_reserve))
        report = commands.mode_train(
            SimpleNamespace(
                mode="train", output_root=shadow["phase1"], prereg=shadow["prereg"], limits_file=None,
                wall_budget_seconds=None, research_log=None, arm="arm2", seed=0,
            )
        )

    run_dir = shadow["phase1"] / "runs" / str(report.get("run_id"))
    stored = {}
    control_db = shadow["phase1"] / "control.sqlite3"
    if control_db.is_file() and report.get("run_id"):
        with sqlite3.connect(control_db) as conn:
            row = conn.execute(
                "SELECT config_json, state, optimizer_steps FROM runs WHERE run_id=?",
                (report["run_id"],),
            ).fetchone()
        if row:
            stored = {
                "run_config_budget": json.loads(row[0]).get("budget"),
                "db_state": row[1],
                "db_optimizer_steps": row[2],
            }
    return {
        "status": report.get("status"),
        "error": report.get("error"),
        "refused_stage": report.get("refused_stage"),
        "run_id": report.get("run_id"),
        "worker_exit_code": report.get("worker_exit_code"),
        "cli_exit_code": commands._exit_code_for(report),
        "reserve_calls": len(reserves),
        "optimizer_step_reserves": sum(1 for _s, step in reserves if step),
        "zero_step_reserves": sum(1 for _s, step in reserves if not step),
        "checkpoint_written": (run_dir / "params.npz").is_file(),
        "run_info_written": (run_dir / "run_info.json").is_file(),
        **stored,
    }


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="p14-probe-", dir=tempfile.gettempdir()))
    sb = full_flow.build_sandbox(root)
    updates = int(sb["document"]["training_protocol"]["updates"])
    checkpoint_updates = list(sb["document"]["training_protocol"]["checkpoint_updates"])
    real_rcs = worker.run_config_snapshot

    def rcs_with(steps):
        def patched(*, wall_budget_seconds, purpose):
            snap = real_rcs(wall_budget_seconds=wall_budget_seconds, purpose=purpose)
            snap["budget"]["max_optimizer_steps"] = steps
            return snap

        return patched

    results = {
        "schema": "ainerzero.v9.p14.train-ledger-probe.v1",
        "frozen_updates_per_run": updates,
        "frozen_checkpoint_updates": checkpoint_updates,
        "experiment_ceiling_rule": (
            "create_run refuses any run budget field larger than the experiment manifest's "
            "budget block; train_experiment_manifest pins the experiment optimizer ceiling at "
            "exactly `updates`, so the run budget can be at most `updates`"
        ),
        "scenarios": {},
    }
    results["scenarios"]["A_as_shipped"] = run_scenario(sb, sb, _FakeClock(step=0.01), None, [])
    root_b = Path(tempfile.mkdtemp(prefix="p14-probe-b-", dir=tempfile.gettempdir()))
    sb_b = full_flow.build_sandbox(root_b)
    results["scenarios"]["B_budget_equals_updates"] = run_scenario(
        sb, sb_b, _FakeClock(step=0.01), rcs_with(updates), []
    )
    root_c = Path(tempfile.mkdtemp(prefix="p14-probe-c-", dir=tempfile.gettempdir()))
    sb_c = full_flow.build_sandbox(root_c)
    results["scenarios"]["C_budget_updates_plus_one"] = run_scenario(
        sb, sb_c, _FakeClock(step=0.01), rcs_with(updates + 1), []
    )

    a, b, c = (results["scenarios"][k] for k in ("A_as_shipped", "B_budget_equals_updates", "C_budget_updates_plus_one"))
    results["checks"] = {
        "A_stops_before_second_update": (
            a["status"] == "stopped" and a["db_optimizer_steps"] == 1 and a["checkpoint_written"] is False
        ),
        "B_consumes_all_updates_but_never_checkpoints": (
            b["status"] == "stopped" and b["db_optimizer_steps"] == updates and b["checkpoint_written"] is False
        ),
        "C_run_budget_above_experiment_ceiling_refused": (
            c["status"] == "failed"
            and "run budget exceeds experiment run limits" in str(c.get("error"))
            and c.get("run_id") is None
        ),
    }
    results["verdict"] = "blocker_confirmed" if all(results["checks"].values()) else "inconclusive"
    results["conclusion"] = (
        "No registered r4 train run can reach its checkpoint: the run budget admits 1 optimizer "
        "step, the experiment ceiling forbids a larger run budget than `updates`, and an "
        "exact-equality budget is consumed by the last update so the trailing zero-step "
        "checkpoint reservation is still refused."
    )
    OUT_DIR.joinpath("evidence").mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "evidence/train-ledger-probe.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(results, indent=1))
    return 0 if results["verdict"] == "blocker_confirmed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
