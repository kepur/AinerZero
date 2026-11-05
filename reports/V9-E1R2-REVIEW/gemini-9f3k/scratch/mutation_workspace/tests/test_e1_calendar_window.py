"""Tests for E1 phase-2 calendar window separation and lineage aggregation (ainerzero.V9.P104).

Verifies, for r2 (own ledger, own budget, reused dataset):
(a) Idle gap does not reject: a gap longer than the phase ceiling does not block a cell.
(b) Budget ceiling: r2 reservations stop at phase_total_wall_ceiling_seconds exactly.
(c) Duplicates: a cell completed in r2 is refused; a run from another experiment in the same
    ledger does not block r2, because r2 retrains on purpose. generate-data is refused.
(d) Prereg validation: missing ledger_experiment_ids, mismatched entries, or a calendar window
    below the phase ceiling raise SpecValidationError. Direct subprocess verifies
    validate(build_draft()) without conftest.
(e) Dual-family full r2 schedule with a 7.5h gap between P and S succeeds.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import numpy as np
import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.experiments.e1 import (
    commands,
    prereg,
    prior,
    spec,
    worker,
)


class FakeClock:
    """Deterministic simulated clock for calendar and schedule testing."""

    def __init__(self, start: float = 1700000000.0):
        self.curr = float(start)

    def time(self) -> float:
        return self.curr

    def advance(self, dt: float) -> None:
        self.curr += float(dt)


class FakeCellRunner(worker.CellRunner):
    """Fast fake runner simulating completion of work cells."""

    def __init__(self, clock: FakeClock | None = None):
        self.clock = clock

    def run_generate_data(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop("Fake generate-data timeout")
        if self.clock is not None:
            self.clock.advance(10.0)
        return {"mode": "generate-data", "status": "completed"}

    def run_train(self, arm: int, family: str, seed: int, output_root: Path, data_dir: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop(f"Fake train arm {arm} timeout")
        if self.clock is not None:
            self.clock.advance(15.0)
        ckpt_dir = output_root / "checkpoints" / f"arm{arm}_{family}_seed{seed}"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        ckpt_file = ckpt_dir / "model_weights.npz"
        np.savez(ckpt_file, dummy=np.zeros(1))
        return {
            "mode": "train",
            "arm": arm,
            "family": family,
            "seed": seed,
            "checkpoint_path": str(ckpt_file),
            "checkpoint_sha256": hashlib.sha256(ckpt_file.read_bytes()).hexdigest(),
            "status": "completed",
        }

    def run_eval(self, arm: int, family: str, seed: int | None, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop(f"Fake eval arm {arm} timeout")
        if self.clock is not None:
            self.clock.advance(5.0)
        return {
            "mode": "eval",
            "arm": arm,
            "family": family,
            "seed": seed,
            "metrics": {"position_error_10_step": 0.05, "collision_f1": 0.95},
            "status": "completed",
        }

    def run_final_eval(self, data_dir: Path, output_root: Path, clock_fn, deadline: float, budget: float, **kwargs):
        if clock_fn() > deadline:
            raise worker.BudgetStop("Fake final-eval timeout")
        if self.clock is not None:
            self.clock.advance(10.0)
        return {
            "mode": "final-eval",
            "family": kwargs.get("family", "P"),
            "status": "completed",
            "final_read_once": True,
            "metrics": {"position_error_10_step": 0.048, "collision_f1": 0.96},
        }


def _setup_environment(tmp_path: Path):
    """Set up temporary directory structure, frozen prereg, and research log."""
    output_root = tmp_path / "phase2"
    output_root.mkdir(parents=True, exist_ok=True)
    ledger_path = output_root / "control.sqlite3"
    lock_path = tmp_path / "locks" / "m0-worker.lock"
    research_log = tmp_path / "RESEARCH_LOG.md"
    data_dir = tmp_path / "datasets"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Freeze valid prereg
    draft = prereg.build_draft()
    prereg.validate(draft)
    frozen_doc, digest = prereg.freeze(draft)
    prereg_file = output_root / "prereg.json"
    prereg_file.write_bytes(spec.canonical_json(frozen_doc))

    # Write approval log
    approval_content = f"""# Research Log
## R20261105-E1-r2-approval
APPROVED e1-phase2 prereg document_sha256={digest}
APPROVED e1-phase2 final-eval document_sha256={digest}
"""
    research_log.write_text(approval_content, encoding="utf-8")

    # Generator identity
    gen_id_payload = {
        "generator_digests": dict(draft.get("generator_digests") or {}),
        "velocity_injection": draft.get("required_velocity_injection", "disabled"),
        "timestamp": 1700000000.0,
    }
    (data_dir / "generator_identity.json").write_text(
        json.dumps(gen_id_payload), encoding="utf-8"
    )

    return {
        "output_root": output_root,
        "ledger": ledger_path,
        "lock": lock_path,
        "research_log": research_log,
        "data_dir": data_dir,
        "prereg": prereg_file,
    }


def _make_args(env: dict[str, Any], mode: str, **kwargs) -> argparse.Namespace:
    base = {
        "command": "e1-phase2",
        "mode": mode,
        "output_root": env["output_root"],
        "ledger": env["ledger"],
        "lock_file": env["lock"],
        "research_log": env["research_log"],
        "data_dir": env["data_dir"],
        "prereg": env["prereg"],
        "arm": None,
        "family": None,
        "seed": None,
        "wall_budget_seconds": None,
        "runner": None,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


def _seed_r2_run(store: RunStore, index: int, active_seconds: float) -> None:
    """Record one completed r2 training run that reserved active_seconds."""
    cfg = {
        "mode": "train",
        "arm": 3,
        "family": "S",
        "seed": 100 + index,
        "cell_wall_budget_seconds": active_seconds,
        "budget": {
            "max_wall_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
            "max_environment_steps": 1000000,
            "max_optimizer_steps": 76800,
            "max_daily_active_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
            "max_model_transitions": 0,
            "timezone": worker.TIMEZONE,
        },
        "experiment_id": spec.EXPERIMENT_ID,
    }
    r = store.create_run(
        config_snapshot=cfg,
        request_id=f"r2:fill:{index}",
        role="model",
        experiment_id=spec.EXPERIMENT_ID,
    )
    store.transition(r.run_id, "initializing")
    store.transition(r.run_id, "training")
    store.consume(r.run_id, active_seconds=active_seconds)
    store.transition(r.run_id, "completed")


def test_case_a_gap_does_not_reject(tmp_path: Path):
    """(a) A gap longer than the phase ceiling does not block a cell."""
    from datetime import datetime, timezone

    env = _setup_environment(tmp_path)
    t0 = 1700000000.0
    clock = FakeClock(start=t0)
    runner = FakeCellRunner(clock=clock)

    store = RunStore(env["ledger"], now=lambda: datetime.fromtimestamp(clock.time(), timezone.utc))
    store.create_experiment(worker.get_experiment_manifest(), f"init:{spec.EXPERIMENT_ID}", spec.EXPERIMENT_ID)
    store.close()

    clock.advance(float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]) + 22810.0)

    args = _make_args(env, "train", arm=6, family="S", seed=42, fake_clock=clock, runner=runner)
    rep, code = commands.e1_phase2_command(args)
    assert code == commands.EXIT_COMPLETED, f"Expected successful admission, got code {code}: {rep}"
    assert rep.get("status") == "completed"


def test_case_b_phase_ceiling(tmp_path: Path):
    """(b) r2 reservations stop at the phase ceiling exactly."""
    from datetime import datetime, timezone

    env = _setup_environment(tmp_path)
    clock = FakeClock(start=1700000000.0)
    runner = FakeCellRunner(clock=clock)
    ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
    arm6_cell = float(spec.BUDGET_CAPS["train_cell_wall_by_arm"]["6"])

    store = RunStore(env["ledger"], now=lambda: datetime.fromtimestamp(clock.time(), timezone.utc))
    store.create_experiment(worker.get_experiment_manifest(), f"init:{spec.EXPERIMENT_ID}", spec.EXPERIMENT_ID)
    fill = ceiling - arm6_cell
    for i in range(10):
        _seed_r2_run(store, i, fill / 10.0)
    store.close()

    # Exactly at the ceiling is admitted.
    args_boundary = _make_args(env, "train", arm=6, family="S", seed=42, fake_clock=clock, runner=runner)
    rep_bound, code_bound = commands.e1_phase2_command(args_boundary)
    assert code_bound == commands.EXIT_COMPLETED, f"Boundary cell failed: {rep_bound}"

    # Any further cell is refused.
    args_exceed = _make_args(
        env, "train", arm=3, family="S", seed=43, fake_clock=clock, runner=runner, wall_budget_seconds=60.0
    )
    rep_exceed, code_exceed = commands.e1_phase2_command(args_exceed)
    assert code_exceed == commands.EXIT_REFUSED_RESOURCE
    assert rep_exceed.get("stage") == "phase_budget_exceeded", f"got: {rep_exceed}"


def test_case_c_duplicates_are_per_experiment(tmp_path: Path):
    """(c) Only r2's own completed cells block a rerun; generate-data is refused."""
    from datetime import datetime, timezone

    env = _setup_environment(tmp_path)
    clock = FakeClock(start=1700000000.0)
    runner = FakeCellRunner(clock=clock)

    store = RunStore(env["ledger"], now=lambda: datetime.fromtimestamp(clock.time(), timezone.utc))
    old_id = "e1-phase2-20261029-r1"
    manifest_old = copy.deepcopy(worker.get_experiment_manifest())
    manifest_old["experiment_id"] = old_id
    store.create_experiment(manifest_old, f"init:{old_id}", old_id)
    cfg_old = {
        "mode": "train",
        "arm": 6,
        "family": "P",
        "seed": 42,
        "cell_wall_budget_seconds": 1000.0,
        "budget": {
            "max_wall_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
            "max_environment_steps": 1000000,
            "max_optimizer_steps": 76800,
            "max_daily_active_seconds": float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"]),
            "max_model_transitions": 0,
            "timezone": worker.TIMEZONE,
        },
        "experiment_id": old_id,
    }
    r = store.create_run(config_snapshot=cfg_old, request_id="old:train", role="model", experiment_id=old_id)
    store.transition(r.run_id, "initializing")
    store.transition(r.run_id, "training")
    store.consume(r.run_id, active_seconds=1000.0)
    store.transition(r.run_id, "completed")
    store.close()

    rep_gen, code_gen = commands.e1_phase2_command(_make_args(env, "generate-data", fake_clock=clock, runner=runner))
    assert code_gen == commands.EXIT_FAILED
    assert rep_gen.get("stage") == "data_generation_not_allowed", f"got: {rep_gen}"

    args_train = _make_args(env, "train", arm=6, family="P", seed=42, fake_clock=clock, runner=runner)
    rep_first, code_first = commands.e1_phase2_command(args_train)
    assert code_first == commands.EXIT_COMPLETED, f"r2 must retrain despite the old run: {rep_first}"

    rep_second, code_second = commands.e1_phase2_command(args_train)
    assert code_second == commands.EXIT_FAILED
    assert rep_second.get("stage") == "duplicate_execution", f"got: {rep_second}"


def test_case_d_prereg_validation_and_subprocess():
    """(d) Prereg validation: missing/reversed/mismatched lineage or bad calendar window raise SpecValidationError; subprocess test passes."""
    # 1. Missing ledger_experiment_ids
    d1 = prereg.build_draft()
    del d1["ledger_experiment_ids"]
    with pytest.raises(prereg.SpecValidationError, match="ledger_experiment_ids"):
        prereg.validate(d1)

    # 2. Inverted ledger_experiment_ids order
    d2 = prereg.build_draft()
    d2["ledger_experiment_ids"] = [spec.EXPERIMENT_ID, "e1-phase2-20261029-r1"]
    with pytest.raises(prereg.SpecValidationError, match="ledger_experiment_ids mismatch"):
        prereg.validate(d2)

    # 3. Last entry not equal to experiment_id
    d3 = prereg.build_draft()
    d3["ledger_experiment_ids"] = ["e1-phase2-20261029-r0", "e1-phase2-20261029-other"]
    with pytest.raises(prereg.SpecValidationError):
        prereg.validate(d3)

    # 4a. Missing experiment_calendar_window_seconds
    d4a = prereg.build_draft()
    del d4a["budget_caps"]["experiment_calendar_window_seconds"]
    with pytest.raises(prereg.SpecValidationError, match="experiment_calendar_window_seconds"):
        prereg.validate(d4a)

    # 4b. experiment_calendar_window_seconds < phase_total_wall_ceiling_seconds
    d4b = prereg.build_draft()
    d4b["budget_caps"]["experiment_calendar_window_seconds"] = 13199.0
    with pytest.raises(prereg.SpecValidationError, match="must be >="):
        prereg.validate(d4b)

    # 5. Direct subprocess invocation without conftest
    sub_code = """
import sys
sys.path.insert(0, 'src')
from ainerzero.v9.experiments.e1 import prereg, spec

draft = prereg.build_draft()
assert draft["ledger_experiment_ids"] == list(spec.LEDGER_EXPERIMENT_IDS)
assert draft["budget_caps"]["experiment_calendar_window_seconds"] == 259200.0
prereg.validate(draft)
print("SUBPROCESS_PREREG_VALIDATE_OK")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", sub_code],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"Subprocess failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    assert "SUBPROCESS_PREREG_VALIDATE_OK" in result.stdout


def test_case_e_full_schedule_rehearsal_with_7_5h_gap(tmp_path: Path):
    """(e) The full r2 schedule with a 7.5h gap between P and S, at the real reservations."""
    env = _setup_environment(tmp_path)
    clock = FakeClock(start=1700000000.0)
    runner = FakeCellRunner(clock=clock)

    # Arm 2 is not trained in r2: its checkpoints carry over from r1.
    for family in spec.FAMILIES:
        for seed in spec.TRAINING_SEEDS:
            cell_dir = env["output_root"] / "checkpoints" / f"arm2_{family}_seed{seed}"
            cell_dir.mkdir(parents=True)
            (cell_dir / "model_weights.npz").write_bytes(b"inherited")

    def run_family(family: str) -> None:
        for arm in spec.RETRAIN_ARM_IDS:
            for seed in spec.TRAINING_SEEDS:
                rep, code = commands.e1_phase2_command(
                    _make_args(env, "train", arm=arm, family=family, seed=seed, fake_clock=clock, runner=runner)
                )
                assert code == commands.EXIT_COMPLETED, f"train arm {arm} {family} seed {seed} failed: {rep}"

    run_family("P")
    clock.advance(7.5 * 3600.0)
    run_family("S")

    for family in spec.FAMILIES:
        for arm in range(1, 8):
            seeds = spec.TRAINING_SEEDS if arm in spec.TRAINABLE_ARM_IDS else (None,)
            for seed in seeds:
                rep, code = commands.e1_phase2_command(
                    _make_args(env, "eval", arm=arm, family=family, seed=seed, fake_clock=clock, runner=runner)
                )
                assert code == commands.EXIT_COMPLETED, f"eval arm {arm} {family} seed {seed} failed: {rep}"

    for family in spec.FAMILIES:
        rep, code = commands.e1_phase2_command(
            _make_args(env, "final-eval", family=family, fake_clock=clock, runner=runner)
        )
        assert code == commands.EXIT_COMPLETED, f"final-eval {family} failed: {rep}"

    # Every reservation fits, and the total lands on the registered ceiling exactly.
    ok, consumed, ceiling = commands._check_phase_budget_ceiling(env["ledger"], 0.0)
    assert ok
    assert consumed == pytest.approx(ceiling)
