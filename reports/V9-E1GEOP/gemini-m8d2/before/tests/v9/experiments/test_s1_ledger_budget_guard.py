"""RunStore budget-guard tests for the S1 prep ledger (pure CPU, no model import)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ainerzero.v9.experiments.s1 import worker


def test_prep_ledger_registers_and_reserves_inside_runstore(tmp_path):
    ledger = worker.PrepLedger(tmp_path / "control.sqlite3")
    try:
        run_id = ledger.open_aux_run(mode="verify", wall_budget_seconds=120.0)
        ledger.begin_work(run_id, work_state="validating")
        ledger.reserve(run_id, active_seconds=5.0)
        record = ledger.get(run_id)
        assert record["state"] == "validating"
        assert record["role"] == "auxiliary"
        assert record["experiment_id"] == worker.PREP_EXPERIMENT_ID
        assert record["reserved_active_seconds"] == pytest.approx(5.0)
        assert record["reserved_optimizer_steps"] == 0
        finished = ledger.finish(run_id, "completed", "test_completed")
        assert finished["state"] == "completed"
    finally:
        ledger.close()


def test_prep_ledger_budget_guard_refuses_over_reservation(tmp_path):
    ledger = worker.PrepLedger(tmp_path / "control.sqlite3")
    try:
        run_id = ledger.open_aux_run(mode="smoke", wall_budget_seconds=1.0)
        ledger.begin_work(run_id, work_state="validating")
        ledger.reserve(run_id, active_seconds=0.7)  # admitted
        with pytest.raises(worker.BudgetStop) as excinfo:
            ledger.reserve(run_id, active_seconds=30.0)  # over the remaining allowance
        assert "wall_time_budget" in str(excinfo.value)
        # The failed reservation did not change the recorded reservation.
        assert ledger.get(run_id)["reserved_active_seconds"] == pytest.approx(0.7)
        stopped = ledger.finish(run_id, "stopped", "budget_exhausted")
        assert stopped["state"] == "stopped"
        assert stopped["reason"] == "budget_exhausted"
    finally:
        ledger.close()


def test_prep_experiment_manifest_has_all_frozen_budget_fields():
    manifest = worker.prep_experiment_manifest()
    assert set(manifest["budget"]) == {
        "max_environment_steps",
        "max_optimizer_steps",
        "max_model_transitions",
        "max_wall_seconds",
        "max_daily_active_seconds",
        "timezone",
    }
    assert set(manifest["experiment_budget"]) == {
        "max_model_runs",
        "max_environment_steps",
        "max_optimizer_steps",
        "max_model_transitions",
        "max_wall_seconds",
        "max_calibration_seconds",
    }
    assert all(value > 0 for value in manifest["experiment_budget"].values())
    assert manifest["budget"]["max_wall_seconds"] <= manifest["experiment_budget"]["max_wall_seconds"]
