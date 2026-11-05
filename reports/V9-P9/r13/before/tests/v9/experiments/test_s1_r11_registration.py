"""r11 registered budget + new experiment identity (ainerzero.V9.P30).

The r10 phase run failed: 9/9 trainings stopped at the 450 s deadline after
1591-2676 of 3510 updates, and the arm2/3/4 evals were refused because the
registered eval_batches=48 cannot cover the 175-batch window probe.  The user
approved option A verbatim (RESEARCH_LOG R20261023-S1-phase1-r11-budget): keep
3510 updates, register the single-run deadline as 1200 s instead of deriving
ceil(1.25 x estimate), raise eval_batches to 175, and register a new experiment
ID so the old experiment's rows, attempts and failures stay untouched.

These tests are pure CPU: no MLX, no training, no eval of a real model, no
approval line, no new data, no central-ledger write.  Every ledger below is a
fresh isolated file; the real one is only ever read.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import prereg, spec, worker

from s1_testkit import FAKE_COUNTS, FAKE_IDENTITY, fake_smoke

R11 = spec.R11_EXPERIMENT_ID
OLD = spec.EXPERIMENT_ID
SMOKE_OF_RECORD = (
    Path(__file__).resolve().parents[3]
    / "reports"
    / "V9-P9"
    / "r1-archive"
    / "smoke_metrics.json"
)


def _r11_draft(*, data_identity=None, parameter_counts=None):
    return prereg.build_draft(
        data_identity=data_identity or FAKE_IDENTITY,
        parameter_counts=parameter_counts or FAKE_COUNTS,
        created_unix=1_000.0,
        experiment_id=R11,
        budget_registration=spec.R11_BUDGET_REGISTRATION,
    )


def _r11_frozen(*, smoke=None, data_identity=None):
    return prereg.build_frozen(
        _r11_draft(data_identity=data_identity),
        smoke=smoke or fake_smoke(),
        data_identity=data_identity or FAKE_IDENTITY,
        created_unix=1_000.0,
    )


# --- the registered budget itself ------------------------------------------
def test_registered_budget_freezes_the_approved_values():
    smoke = json.loads(SMOKE_OF_RECORD.read_text(encoding="utf-8"))
    budget = prereg.registered_budget(smoke)
    # the user-approved registration
    assert budget["updates"] == 3_510
    assert budget["deadline_seconds"] == 1_200
    assert budget["supervision_seconds"] == 1_250
    # the honest derived values at eval_batches=175, recorded as measured
    assert budget["estimate_seconds"] == pytest.approx(381.1528007568777)
    assert budget["derived_deadline_seconds"] == 477
    assert budget["arm1_estimate_seconds"] == pytest.approx(5.47487220082985)
    assert budget["arm1_deadline_seconds"] == 7
    assert budget["arm1_supervision_seconds"] == 57
    # 9 x 1200 + 1 x 7 + 47.605... data generation
    assert budget["phase_wall_seconds"] == pytest.approx(10_854.605202458999)
    assert budget["phase_wall_headroom_seconds"] == pytest.approx(3_545.394797541001)
    assert budget["fits_per_run_cap"] is True
    assert budget["fits_phase_cap"] is True
    # the P1 measurement that motivated the registration
    throughput = budget["measured_throughput"]
    assert throughput["per_step_seconds"] == {"median": 0.20182, "slowest": 0.2829}
    assert throughput["slowest_wall_seconds"] == pytest.approx(992.98)
    assert throughput["registered_deadline_seconds"] == 1_200
    assert throughput["deadline_over_slowest_ratio"] == pytest.approx(1.2085)


def test_registered_path_is_not_the_derived_path():
    """eval_batches=175 makes the derivation yield 3299 updates; the registered
    path must freeze the approved 3510 instead, and record the contrast."""
    smoke = json.loads(SMOKE_OF_RECORD.read_text(encoding="utf-8"))
    derived = prereg.estimate_budget(smoke)
    assert derived["updates"] == 3_299  # what the old rule would freeze
    assert derived["deadline_seconds"] == 450
    frozen = _r11_frozen(smoke=smoke)
    assert frozen["training_protocol"]["updates"] == 3_510
    assert frozen["training_protocol"]["checkpoint_updates"] == [0, 439, 878, 1755, 3510]
    assert frozen["training_protocol"]["eval_batches"] == 175
    for arm_id in ("arm2", "arm3", "arm4"):
        assert frozen["arms"][arm_id]["training_updates"] == 3_510
    timing = frozen["timing"]
    assert timing["deadline_seconds"] == 1_200
    assert timing["supervision_seconds"] == 1_250
    assert timing["deadline_source"] == spec.R11_DEADLINE_SOURCE
    assert timing["registered_updates"] == 3_510
    assert timing["registered_deadline_seconds"] == 1_200
    assert timing["registered_supervision_seconds"] == 1_250
    assert timing["derived_deadline_seconds"] == 477
    assert timing["arm1_deadline_seconds"] == 7
    assert timing["measured_throughput"] == dict(spec.R11_MEASURED_THROUGHPUT)


def test_r11_freeze_registers_the_new_experiment_identity():
    frozen = _r11_frozen()
    assert frozen["experiment_id"] == R11
    assert frozen["budget_registration"] == spec.R11_BUDGET_REGISTRATION
    assert frozen["status"] == prereg.STATUS_FROZEN == "awaiting_coordinator_approval"
    # the derived path is untouched for the old registration
    old = prereg.build_frozen(
        prereg.build_draft(data_identity=FAKE_IDENTITY, parameter_counts=FAKE_COUNTS),
        smoke=fake_smoke(),
        data_identity=FAKE_IDENTITY,
        created_unix=1_000.0,
    )
    assert old["experiment_id"] == OLD
    assert old["budget_registration"] == "RESEARCH_LOG R20261021-P1-stageA-budget"
    assert old["timing"].get("deadline_source") is None
    assert old["timing"]["deadline_seconds"] == int(old["budget_estimate"]["deadline_seconds"])


def test_registered_budget_refuses_when_the_derivation_would_shrink_updates():
    """A smoke measurement whose derived deadline exceeds the per-run cap is
    exactly the case the old code answered by cutting the update count; the
    registered path refuses instead of freezing a reduced count."""
    slow = fake_smoke(step_seconds=0.02)  # derived deadline ~1369 s > 1200 s cap
    with pytest.raises(ValueError, match="shrink the update count"):
        prereg.registered_budget(slow)


def test_registered_budget_refuses_a_deadline_above_the_per_run_cap(monkeypatch):
    monkeypatch.setattr(spec, "R11_REGISTERED_DEADLINE_SECONDS", 1_500)
    with pytest.raises(ValueError, match="per-run cap"):
        prereg.registered_budget(fake_smoke())


def test_freeze_refuses_a_draft_whose_registered_values_were_reduced():
    """Fail-closed at the draft boundary: a registration that declares 3299
    updates (the derived count) or a 1150 s deadline is not the approved one."""
    reduced = _r11_draft()
    reduced["timing"]["registered_updates"] = 3_299
    with pytest.raises(ValueError, match="reduced update count"):
        prereg.build_frozen(
            reduced, smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0
        )
    moved = _r11_draft()
    moved["timing"]["registered_deadline_seconds"] = 1_150
    with pytest.raises(ValueError, match="registered_deadline_seconds=1150"):
        prereg.build_frozen(
            moved, smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0
        )


def test_freeze_refuses_the_r11_registration_with_the_old_experiment_id():
    foreign = _r11_draft()
    foreign["experiment_id"] = OLD
    with pytest.raises(ValueError, match="registered experiment id"):
        prereg.build_frozen(
            foreign, smoke=fake_smoke(), data_identity=FAKE_IDENTITY, created_unix=1_000.0
        )


# --- validation fail-closed on the frozen document --------------------------
def test_validate_refuses_a_registered_deadline_that_is_not_1200():
    frozen = _r11_frozen()
    frozen["timing"]["deadline_seconds"] = 1_150
    reasons = prereg.validate(frozen)
    assert any("user-approved 1200" in reason for reason in reasons)


def test_validate_refuses_a_reduced_registered_update_count():
    frozen = _r11_frozen()
    frozen["timing"]["registered_updates"] = 3_299
    frozen["training_protocol"]["updates"] = 3_299
    reasons = prereg.validate(frozen)
    assert any("reduced update count" in reason for reason in reasons)


def test_validate_refuses_a_tampered_measured_throughput_block():
    frozen = _r11_frozen()
    frozen["timing"]["measured_throughput"]["per_step_seconds"]["slowest"] = 0.20
    reasons = prereg.validate(frozen)
    assert any("measured throughput" in reason for reason in reasons)


def test_validate_refuses_a_registered_supervision_that_is_not_deadline_plus_50():
    frozen = _r11_frozen()
    frozen["timing"]["supervision_seconds"] = 1_200
    reasons = prereg.validate(frozen)
    assert any("supervision" in reason for reason in reasons)


def test_validate_refuses_an_eval_batches_registration_below_the_frozen_value():
    frozen = _r11_frozen()
    frozen["training_protocol"]["eval_batches"] = 48
    reasons = prereg.validate(frozen)
    assert any("eval_batches" in reason for reason in reasons)


# --- the new experiment identity in the guards -------------------------------
def _started_run(ledger, *, experiment_id: str, arm_id: str, seed: int, run_id: str):
    """A real started model run (an attempt) inside one experiment."""
    snapshot = worker.run_config_snapshot(
        wall_budget_seconds=1_200.0, purpose=f"s1_phase1_training_run:{arm_id}:seed{seed}"
    )
    snapshot["arm_id"] = arm_id
    snapshot["seed"] = int(seed)
    snapshot["updates"] = 3_510
    ledger.store.create_run(
        snapshot,
        f"{experiment_id}:{arm_id}:{seed}:{run_id}",
        run_id,
        experiment_id=experiment_id,
        role="model",
    )
    ledger.store.transition(run_id, "initializing", reason="train_prereg_approved")
    ledger.store.transition(run_id, "training", reason="worker_started")
    return run_id


def _two_experiment_ledger(tmp_path: Path):
    """Old experiment with a started arm2/seed0 attempt; new experiment empty."""
    path = tmp_path / "control.sqlite3"
    ledger = worker.PrepLedger(path)
    try:
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3_510),
            f"{OLD}:training",
            OLD,
        )
        old_run = _started_run(
            ledger, experiment_id=OLD, arm_id="arm2", seed=0, run_id="old-arm2-seed0"
        )
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3_510),
            f"{R11}:training",
            R11,
        )
        runs = ledger.store.list_runs()
    finally:
        ledger.close()
    return path, runs, old_run


def test_new_experiment_starts_attempts_at_zero(tmp_path):
    _path, runs, old_run = _two_experiment_ledger(tmp_path)
    assert worker.train_attempts(runs, arm_id="arm2", seed=0, experiment_id=R11) == []
    assert worker.train_attempts(runs, arm_id="arm2", seed=1, experiment_id=R11) == []
    # the old registration still refuses the same arm x seed
    old_attempts = worker.train_attempts(runs, arm_id="arm2", seed=0, experiment_id=OLD)
    assert [run.run_id for run in old_attempts] == [old_run]
    # the pre-r11 whole-ledger behaviour is unchanged
    assert worker.train_attempts(runs, arm_id="arm2", seed=0) == old_attempts


def test_new_experiment_phase_wall_starts_at_zero(tmp_path):
    _path, runs, _old_run = _two_experiment_ledger(tmp_path)
    now = time.time()
    assert worker.phase_total_wall_seconds(runs, instant=now, experiment_id=R11) == 0.0
    old_total = worker.phase_total_wall_seconds(runs, instant=now, experiment_id=OLD)
    assert old_total > 0.0
    assert worker.phase_total_wall_seconds(runs, instant=now) == pytest.approx(old_total)
    breakdown = worker.phase_ledger_breakdown(runs, instant=now, experiment_id=R11)
    assert breakdown["rows"] == []
    assert breakdown["total_seconds"] == 0.0


def test_document_experiment_scope_only_scopes_the_r11_registration():
    assert worker.document_experiment_scope({"experiment_id": R11}) == R11
    # the old experiment and any unregistered id keep the whole-ledger guard
    assert worker.document_experiment_scope({"experiment_id": OLD}) is None
    assert worker.document_experiment_scope({}) is None
    assert worker.document_experiment_scope({"experiment_id": "some-future-id"}) is None
    # the run-registration id still follows the document
    assert worker.document_experiment_id({"experiment_id": R11}) == R11
    assert worker.document_experiment_id({"experiment_id": OLD}) == OLD
    assert worker.document_experiment_id({}) is None


def test_d_candidate_guard_is_scoped_to_the_registration(tmp_path):
    """The old experiment's completed D row does not block the new
    registration's single D evaluation, and vice versa."""
    path = tmp_path / "control.sqlite3"
    ledger = worker.PrepLedger(path)
    try:
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3_510), f"{OLD}:training", OLD
        )
        old_run = _started_run(
            ledger, experiment_id=OLD, arm_id="arm1", seed=0, run_id="old-arm1"
        )
        ledger.store.create_experiment(
            worker.train_experiment_manifest(updates=3_510), f"{R11}:training", R11
        )
        runs = ledger.store.list_runs()
    finally:
        ledger.close()
    new_state = worker.d_candidate_attempt_state(runs, experiment_id=R11)
    assert new_state["status"] == "ok"
    old_state = worker.d_candidate_attempt_state(runs, experiment_id=OLD)
    assert old_state["status"] == "already_attempted"
    assert old_state["run_ids"] == [old_run]
    # the pre-r11 whole-ledger behaviour still refuses
    assert worker.d_candidate_attempt_state(runs)["status"] == "already_attempted"


def test_bad_control_unscoped_attempts_would_refuse_the_new_experiment(tmp_path):
    """Control: the pre-r11 guard body (no experiment filter) counts the old
    experiment's row for the new registration -- which is exactly the defect
    the scoping fixes.  The scoped guard above is therefore load-bearing."""
    _path, runs, old_run = _two_experiment_ledger(tmp_path)

    def _unscoped(runs, *, arm_id, seed, experiment_id=None):
        return [
            run
            for run in runs
            if (run.config_snapshot or {}).get("arm_id") == arm_id
            and int((run.config_snapshot or {}).get("seed", -1)) == int(seed)
            and (run.state != "created" or int(run.reserved_optimizer_steps) > 0)
        ]

    assert [run.run_id for run in _unscoped(runs, arm_id="arm2", seed=0)] == [old_run]
    assert worker.train_attempts(runs, arm_id="arm2", seed=0, experiment_id=R11) == []
