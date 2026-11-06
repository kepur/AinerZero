"""S1 r7: terminal-phase accounting must count consumption, not calendar age.

The P17 addendum measured the r6 defect precisely: a terminal row created
211,859.9 s ago with a 59.53 s terminal interval and a 720.27 s reservation was
being charged 211,859.9 s, so the 4 h cap fired on rows that had already ended.
r7 charges every row ``max(reserved_active, terminal_interval)`` and sums per
row -- never ``max`` of two global totals, never the age of a finished run.

Every ledger here is a fresh isolated file; the real ledger is only ever read.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

import pytest
from types import SimpleNamespace

from ainerzero.v9.experiments.s1 import commands, spec, worker

from test_s1_r6_entry_guards import _args, _approved

DAY = 86_400.0


def _ledger_with_rows(tmp_path: Path, rows: list[dict]) -> tuple[Path, worker.PrepLedger]:
    """Create a real RunStore ledger whose rows carry controlled timestamps."""
    path = tmp_path / "control.sqlite3"
    ledger = worker.PrepLedger(path)
    try:
        ledger.store.create_experiment(
            worker.prep_experiment_manifest(), worker.PREP_REQUEST_ID, worker.PREP_EXPERIMENT_ID
        )
        ids = []
        for index, _row in enumerate(rows):
            run_id = f"row{index:02d}"
            # One experiment per synthetic row: the RunStore keeps model runs
            # sequential inside an experiment, and these rows are only about
            # accounting, not about a legal lifecycle.
            experiment = ledger.store.create_experiment(
                worker.prep_experiment_manifest(),
                f"{worker.PREP_REQUEST_ID}:row{index}",
                f"{worker.PREP_EXPERIMENT_ID}-row{index}",
            )
            ledger.store.create_run(
                worker.run_config_snapshot(wall_budget_seconds=600.0, purpose="phase-accounting"),
                f"request-{index}",
                run_id,
                experiment_id=experiment.experiment_id,
                role="auxiliary",
            )
            ids.append(run_id)
    finally:
        ledger.close()
    connection = sqlite3.connect(path)
    try:
        for run_id, row in zip(ids, rows):
            connection.execute(
                "UPDATE runs SET state = ?, created_at = ?, updated_at = ?, "
                "active_seconds = ? WHERE run_id = ?",
                (
                    row["state"],
                    row["created_at"],
                    row["updated_at"],
                    row["active_seconds"],
                    run_id,
                ),
            )
        connection.commit()
    finally:
        connection.close()
    ledger = worker.PrepLedger(path)
    return path, ledger


def test_a_three_day_old_completed_row_is_charged_its_reservation(tmp_path):
    now = time.time()
    _path, ledger = _ledger_with_rows(
        tmp_path,
        [
            {
                "state": "completed",
                "created_at": now - 3 * DAY,
                "updated_at": now - 3 * DAY + 59.53,
                "active_seconds": 720.27,
            }
        ],
    )
    try:
        runs = ledger.store.list_runs()
        assert worker.phase_total_wall_seconds(runs, instant=now) == pytest.approx(720.27)
        breakdown = worker.phase_ledger_breakdown(runs, instant=now)
    finally:
        ledger.close()
    row = breakdown["rows"][0]
    assert row["terminal_interval_seconds"] == pytest.approx(59.53)
    assert row["counted_seconds"] == pytest.approx(720.27)
    assert row["rule"] == "max(reserved, terminal_interval)"


def test_a_long_terminal_interval_wins_over_a_small_reservation(tmp_path):
    now = time.time()
    _path, ledger = _ledger_with_rows(
        tmp_path,
        [
            {
                "state": "failed",
                "created_at": now - DAY,
                "updated_at": now - DAY + 5000.0,
                "active_seconds": 100.0,
            }
        ],
    )
    try:
        total = worker.phase_total_wall_seconds(ledger.store.list_runs(), instant=now)
    finally:
        ledger.close()
    assert total == pytest.approx(5000.0)


def test_the_total_is_a_per_row_sum_not_a_global_max(tmp_path):
    now = time.time()
    _path, ledger = _ledger_with_rows(
        tmp_path,
        [
            {
                "state": "completed",
                "created_at": now - 2 * DAY,
                "updated_at": now - 2 * DAY + 59.53,
                "active_seconds": 720.27,
            },
            {
                "state": "stopped",
                "created_at": now - DAY,
                "updated_at": now - DAY + 5000.0,
                "active_seconds": 100.0,
            },
        ],
    )
    try:
        total = worker.phase_total_wall_seconds(ledger.store.list_runs(), instant=now)
    finally:
        ledger.close()
    # max(sum(reserved), sum(interval)) would be max(820.27, 5059.53) = 5059.53.
    assert total == pytest.approx(5720.27)
    assert total > max(820.27, 5059.53)


def test_an_active_row_keeps_growing_with_wall_time(tmp_path):
    now = time.time()
    _path, ledger = _ledger_with_rows(
        tmp_path,
        [
            {
                "state": "training",
                "created_at": now - 100.0,
                "updated_at": now - 1.0,
                "active_seconds": 5.0,
            }
        ],
    )
    try:
        total = worker.phase_total_wall_seconds(ledger.store.list_runs(), instant=now)
    finally:
        ledger.close()
    assert total == pytest.approx(100.0, abs=1.0)


@pytest.mark.parametrize(
    "state,created_at,updated_at",
    [
        ("mystery", 1000.0, 1100.0),  # unknown terminal/active state
        ("completed", 1100.0, 1000.0),  # reverse timestamps
    ],
)
def test_corrupt_rows_are_refused_not_charged(tmp_path, state, created_at, updated_at):
    now = time.time()
    _path, ledger = _ledger_with_rows(
        tmp_path,
        [
            {
                "state": state,
                "created_at": created_at,
                "updated_at": updated_at,
                "active_seconds": 10.0,
            }
        ],
    )
    try:
        with pytest.raises(ValueError):
            worker.phase_total_wall_seconds(ledger.store.list_runs(), instant=now)
    finally:
        ledger.close()


@pytest.mark.parametrize(
    "created_at,updated_at",
    [(None, 1000.0), (1000.0, None), (float("nan"), 1000.0), (1000.0, float("inf"))],
)
def test_non_finite_or_missing_timestamps_are_refused(created_at, updated_at):
    # The SQLite reader rejects some of these before the accounting is reached
    # (a NOT NULL column, an out-of-range time_t); the accounting itself must
    # also refuse them instead of charging 0 or the full wall clock.
    row = SimpleNamespace(
        run_id="synthetic",
        state="completed",
        created_at=created_at,
        updated_at=updated_at,
        reserved_active_seconds=10.0,
    )
    with pytest.raises(ValueError):
        worker.run_conservative_wall_seconds(row, instant=2000.0)


def test_an_unknown_state_is_refused_with_or_without_a_reservation():
    row = SimpleNamespace(
        run_id="synthetic",
        state="quarantined",
        created_at=1000.0,
        updated_at=1100.0,
        reserved_active_seconds=0.0,
    )
    with pytest.raises(ValueError):
        worker.run_conservative_wall_seconds(row, instant=2000.0)


# The fixed run set the P17 addendum measured: the ledger as it stood at r7, i.e. the
# three S1 prereg-prep rows of 2026-10-21 (terminal intervals 59.53 s, reservations
# 720.27 s in total).  Later rounds (r8-r15, final) append rows to the same real
# ledger; those rows are not the r7 evidence, so the assertion is bound to these
# pinned rows, never to whatever the ledger holds today.
#   run_id: (state, created_at, updated_at, active_seconds), exact stored REALs
R7_LEDGER_ROWS = {
    "f3f29a16369c400bb140b0d982f80ad2": (
        "completed", 1792576573.9644, 1792576624.302446, 350.57941137500075,
    ),
    "7b21d3dfd2714afa8f68a5484c5596eb": (
        "completed", 1792576638.852673, 1792576643.396393, 184.79119249999985,
    ),
    "c03caffeb5304f668e711dc9d3ab9831": (
        "completed", 1792579501.883355, 1792579506.531561, 184.89637216699884,
    ),
}


def test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original(
    tmp_path,
):
    """Byte-isolated copy: the age rule blows the 4 h cap, the r7 rule does not."""
    import hashlib

    real = Path(spec.REGISTERED_HOST_LEDGER)
    before = hashlib.sha256(real.read_bytes()).hexdigest()
    copy = tmp_path / "control-copy.sqlite3"
    shutil.copyfile(real, copy)
    before_copy = hashlib.sha256(copy.read_bytes()).hexdigest()

    connection = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    try:
        raw = list(
            connection.execute(
                "SELECT run_id, state, created_at, updated_at, active_seconds FROM runs "
                f"WHERE run_id IN ({','.join('?' * len(R7_LEDGER_ROWS))}) ORDER BY run_id",
                tuple(R7_LEDGER_ROWS),
            )
        )
    finally:
        connection.close()
    # The r7 rows are still present and bit-for-bit what was measured.
    assert {row[0]: tuple(row[1:]) for row in raw} == R7_LEDGER_ROWS
    runs = [
        SimpleNamespace(
            run_id=run_id,
            state=state,
            created_at=created_at,
            updated_at=updated_at,
            reserved_active_seconds=active_seconds,
        )
        for run_id, state, created_at, updated_at, active_seconds in raw
    ]
    now = time.time()
    conservative = worker.phase_total_wall_seconds(runs, instant=now)
    age_based = 0.0
    reserved_based = 0.0
    for run in runs:
        created = worker._parse_timestamp(run.created_at)
        age_based += max(0.0, now - created)
        reserved_based += max(0.0, float(run.reserved_active_seconds or 0.0))

    terminal_based = sum(
        worker._parse_timestamp(run.updated_at) - worker._parse_timestamp(run.created_at)
        for run in runs
    )
    # The P17 addendum figures (module docstring) are reproduced from the copy.
    assert terminal_based == pytest.approx(59.53, abs=0.005)
    assert reserved_based == pytest.approx(720.27, abs=0.005)
    assert age_based > spec.TIMING["phase_wall_max_seconds"], "the r6 bug must be reproducible"
    assert conservative == pytest.approx(reserved_based)
    assert conservative < spec.TIMING["phase_wall_max_seconds"]
    # The copy is read-only evidence: no repair, no rewrite, no migration.
    assert hashlib.sha256(copy.read_bytes()).hexdigest() == before_copy
    assert hashlib.sha256(real.read_bytes()).hexdigest() == before


def test_the_train_entry_still_refuses_an_over_cap_phase_under_the_conservative_rule(
    tmp_path, monkeypatch, canonical_root
):
    path, _digest, _document = _approved(tmp_path, monkeypatch, canonical_root)
    # A finished auxiliary run that really did consume 14,200 s (the reservation
    # says so).  It is not an arm2/seed0 attempt, so only the phase cap can refuse.
    ledger = worker.PrepLedger(canonical_root / "control.sqlite3")
    try:
        ledger.store.create_run(
            worker.run_config_snapshot(wall_budget_seconds=600.0, purpose="phase-cap"),
            "phase-cap-request",
            "phase-cap-run",
            experiment_id=worker.PREP_EXPERIMENT_ID,
            role="auxiliary",
        )
    finally:
        ledger.close()
    with sqlite3.connect(canonical_root / "control.sqlite3") as connection:
        connection.execute(
            "UPDATE runs SET state = 'completed', created_at = created_at - 14200.0, "
            "updated_at = created_at - 14100.0, active_seconds = 14200.0 "
            "WHERE run_id = 'phase-cap-run'"
        )

    def _must_not_start(**_kwargs):  # pragma: no cover - tripwire
        raise AssertionError("an over-budget run reached the worker")

    monkeypatch.setattr(commands, "_supervised_worker", _must_not_start)
    report = commands.mode_train(_args(canonical_root, path))
    assert report["status"] == "refused"
    assert report["stage"] == "phase_budget_exceeded"
    assert report["total_wall_seconds"] == pytest.approx(14200.0, abs=2.0)
    assert report["phase_breakdown"]["rows"][0]["counted_seconds"] == pytest.approx(
        14200.0, abs=2.0
    )
    assert commands._exit_code_for(report) == commands.EXIT_REFUSED_APPROVAL


def test_the_cap_itself_is_unchanged():
    assert spec.TIMING["phase_wall_max_seconds"] == 14_400.0
    assert spec.TIMING["smoke_steps"] == 3
    assert spec.DATA_CAPS["train_worlds_max"] == 2_000
