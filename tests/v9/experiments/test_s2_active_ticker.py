"""W12: in-flight active-time accounting for S2 work cells (real time, small budgets).

RunStore admits a consume only when amount <= wall_budget - max(wall_elapsed, consumed).
Consuming the whole elapsed time once at completion is refused for any cell that ran longer
than half its budget (registered run P193: arm_b seed 42, 677 s of 1200 s). The ticker records
active time in arrears so a cell can use (almost) its whole budget, and a real overrun fails.
"""

from __future__ import annotations

import threading
import time

import pytest

from ainerzero.runtime.lifecycle import BudgetExceeded
from ainerzero.v9.experiments.s2 import commands, worker

BUDGET = 2.0
CHUNK = 0.1


def _ledger(tmp_path):
    return worker.S2Ledger(tmp_path / "control.sqlite3")


def _sleep_runner(seconds, *, self_complete=False, raise_exc=None):
    def runner(ledger, run_id, **kwargs):
        time.sleep(seconds)
        if raise_exc is not None:
            raise raise_exc
        result = {"status": "completed", "elapsed_seconds": seconds}
        if self_complete:  # like train_runner / data_runner, which complete the run themselves
            ledger.complete_run(run_id, active_seconds=seconds, optimizer_steps=3, metrics=result)
        return result

    runner.__name__ = "sleep_runner"
    return runner


def _run(ledger, runner, chunk=CHUNK, budget=BUDGET):
    return worker.execute_work_cell(
        ledger, "train", "arm_a", 42, budget, runner=runner, reservation_chunk_seconds=chunk
    )


def _only_run(ledger):
    runs = ledger.store.list_runs()
    assert len(runs) == 1
    return runs[0]


def _tickers_alive():
    return [t for t in threading.enumerate() if t.name.startswith("s2-active-ticker-")]


def test_cell_longer_than_half_budget_completes(tmp_path):
    led = _ledger(tmp_path)
    _run(led, _sleep_runner(1.4))
    rec = _only_run(led)
    assert rec.state == "completed"
    assert 1.3 <= rec.reserved_active_seconds <= 1.4 + CHUNK
    assert not _tickers_alive()


def test_without_in_flight_catch_up_the_same_cell_is_refused(tmp_path):
    """Documents the RunStore rule that broke P193 (ticker never fires with a huge chunk)."""
    led = _ledger(tmp_path)
    with pytest.raises(BudgetExceeded, match="wall_time_budget"):
        _run(led, _sleep_runner(1.4), chunk=1e9)
    assert _only_run(led).state == "failed"


def test_self_completing_runner_is_not_double_counted(tmp_path):
    led = _ledger(tmp_path)
    _run(led, _sleep_runner(1.4, self_complete=True))
    rec = _only_run(led)
    assert rec.state == "completed"
    assert rec.reserved_active_seconds <= 1.4 + CHUNK
    assert rec.reserved_optimizer_steps == 3


def test_real_overrun_fails_the_cell(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(BudgetExceeded, match="wall_time_budget"):
        _run(led, _sleep_runner(2.6))
    rec = _only_run(led)
    assert rec.state == "failed"
    assert "in-flight catch-up refused" in (rec.reason or "")
    assert rec.reserved_active_seconds <= BUDGET
    assert not _tickers_alive()


def test_runner_exception_stops_ticker_and_fails_run(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(RuntimeError, match="boom"):
        _run(led, _sleep_runner(0.5, raise_exc=RuntimeError("boom")))
    rec = _only_run(led)
    assert rec.state == "failed"
    assert 0.3 <= rec.reserved_active_seconds <= 0.5 + CHUNK
    assert not _tickers_alive()


def test_short_cell_accounting_unchanged(tmp_path):
    """A cell that ends before the first catch-up consumes its reported elapsed time, as before."""
    led = _ledger(tmp_path)

    def runner(ledger, run_id, **kwargs):
        return {"status": "completed", "elapsed_seconds": 0.75}

    worker.execute_work_cell(led, "train", "arm_a", 42, BUDGET, runner=runner, reservation_chunk_seconds=5.0)
    rec = _only_run(led)
    assert rec.state == "completed"
    assert rec.reserved_active_seconds == pytest.approx(0.75)


def test_phase_ceiling_counts_partial_consumption_of_failed_cell(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(RuntimeError):
        _run(led, _sleep_runner(0.5, raise_exc=RuntimeError("boom")))
    consumed_by_run = _only_run(led).reserved_active_seconds
    led.close()
    ok, consumed, _ = commands._check_phase_budget_ceiling(tmp_path / "control.sqlite3", 0.0)
    assert ok
    assert consumed == pytest.approx(consumed_by_run)
    assert consumed < BUDGET  # actual seconds, not the full cell budget


def test_nonpositive_chunk_is_refused(tmp_path):
    led = _ledger(tmp_path)
    with pytest.raises(ValueError, match="chunk_seconds"):
        _run(led, _sleep_runner(0.0), chunk=0.0)
