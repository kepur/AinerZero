from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ainerzero.runtime.lifecycle import (
    BudgetExceeded,
    LifecycleError,
    RunStore,
    SchemaVersionError,
)


class Clock:
    def __init__(self, instant: datetime | None = None):
        self.instant = instant or datetime(2026, 9, 22, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.instant

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)


def config(**budget):
    return {
        "model": {"name": "test-brain"},
        "budget": {
            "max_environment_steps": 20,
            "max_optimizer_steps": 10,
            "max_wall_seconds": 1000,
            "max_daily_active_seconds": 1000,
            "timezone": "Europe/Belgrade",
            **budget,
        },
    }


def working(store, request="request-1", **budget):
    run = store.create_run(config(**budget), request)
    store.transition(run.run_id, "initializing")
    return store.transition(run.run_id, "training")


def test_reservations_are_durable_before_work_and_denials_are_atomic(tmp_path):
    path = tmp_path / "control.sqlite3"
    clock = Clock()
    with RunStore(path, now=clock) as store:
        run = working(store, max_environment_steps=5)
        reserved = store.consume(
            run.run_id, environment_steps=4, optimizer_steps=1, active_seconds=3
        )
        assert reserved.reserved_environment_steps == 4
        assert reserved.reserved_optimizer_steps == 1
        with pytest.raises(BudgetExceeded, match="environment_step_budget"):
            store.consume(run.run_id, environment_steps=2, optimizer_steps=2, active_seconds=10)
        unchanged = store.get_run(run.run_id)
        assert unchanged.reserved_environment_steps == 4
        assert unchanged.reserved_optimizer_steps == 1
        assert unchanged.reserved_active_seconds == 3
    with RunStore(path, now=clock) as reopened:
        persisted = reopened.get_run(run.run_id)
        assert persisted.state == "training"
        assert persisted.reserved_active_seconds == 3
        assert persisted.remaining["daily_active_seconds"] == 997


def test_preflight_does_not_reserve_and_cannot_replace_atomic_consume(tmp_path):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        run = working(store, max_optimizer_steps=1)
        assert store.assert_can_work(run.run_id, optimizer_steps=1).allowed
        assert store.assert_can_work(run.run_id, optimizer_steps=1).allowed
        assert store.get_run(run.run_id).reserved_optimizer_steps == 0
        store.consume(run.run_id, optimizer_steps=1)
        with pytest.raises(BudgetExceeded, match="optimizer_step_budget"):
            store.consume(run.run_id, optimizer_steps=1)


def test_same_instant_reservations_cannot_exceed_session_time_limit(tmp_path):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        run = working(store, max_wall_seconds=10)
        store.consume(run.run_id, active_seconds=6)
        assert store.get_run(run.run_id).remaining["wall_seconds"] == 4
        with pytest.raises(BudgetExceeded, match="wall_time_budget"):
            store.consume(run.run_id, active_seconds=5)
        store.consume(run.run_id, active_seconds=4)
        assert not store.check_budget(run.run_id).allowed


def test_shared_daily_budget_cannot_be_reset_by_another_run_or_larger_limit(tmp_path):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        first = working(store, "first", max_daily_active_seconds=10)
        store.consume(first.run_id, active_seconds=7)
        second = working(store, "second", max_daily_active_seconds=100)
        assert second.remaining["daily_limit_seconds"] == 10
        assert second.remaining["daily_active_seconds"] == 3
        with pytest.raises(BudgetExceeded, match="daily_active_time_budget"):
            store.consume(second.run_id, active_seconds=4)
        store.consume(second.run_id, active_seconds=3)
        assert store.get_run(first.run_id).remaining["daily_active_seconds"] == 0
        with pytest.raises(LifecycleError, match="timezone"):
            store.create_run(config(timezone="UTC"), "other-zone")


def test_local_midnight_splits_reservations_between_days(tmp_path):
    # Belgrade is UTC+2 on this date: 21:59:58 UTC is two seconds before midnight.
    clock = Clock(datetime(2026, 9, 22, 21, 59, 58, tzinfo=timezone.utc))
    with RunStore(tmp_path / "control.db", now=clock) as store:
        run = working(store, max_daily_active_seconds=5)
        current = store.consume(run.run_id, active_seconds=4)
        assert current.remaining["daily_date"] == "2026-09-22"
        assert current.remaining["daily_active_seconds"] == 3
        clock.advance(4)
        following = store.get_run(run.run_id)
        assert following.remaining["daily_date"] == "2026-09-23"
        assert following.remaining["daily_active_seconds"] == 3
        with pytest.raises(BudgetExceeded, match="daily_active_time_budget"):
            store.consume(run.run_id, active_seconds=4)


def test_pause_resume_keeps_counters_and_wall_budget(tmp_path):
    clock = Clock()
    with RunStore(tmp_path / "control.db", now=clock) as store:
        run = working(store)
        store.consume(run.run_id, environment_steps=3, optimizer_steps=2, active_seconds=4)
        store.transition(run.run_id, "pausing", reason="manual")
        store.transition(run.run_id, "paused", reason="manual")
        clock.advance(20)
        with pytest.raises(LifecycleError, match="paused"):
            store.consume(run.run_id, optimizer_steps=1)
        with pytest.raises(LifecycleError, match="Resume must return"):
            store.transition(run.run_id, "collecting")
        resumed = store.resume(run.run_id)
        assert resumed.state == "training"
        assert resumed.reserved_environment_steps == 3
        assert resumed.reserved_optimizer_steps == 2
        assert resumed.remaining["wall_seconds"] == 980
        assert resumed.remaining["daily_active_seconds"] == 996


def test_resume_refuses_expired_budget_and_leaves_run_paused(tmp_path):
    clock = Clock()
    with RunStore(tmp_path / "control.db", now=clock) as store:
        run = working(store, max_wall_seconds=5)
        store.transition(run.run_id, "pausing")
        store.transition(run.run_id, "paused")
        clock.advance(6)
        with pytest.raises(BudgetExceeded, match="wall_time_budget"):
            store.resume(run.run_id)
        assert store.get_run(run.run_id).state == "paused"


def test_recovery_requires_explicit_startup_and_preserves_manual_pause(tmp_path):
    path = tmp_path / "control.db"
    clock = Clock()
    with RunStore(path, now=clock) as store:
        active = working(store, "active")
        store.consume(active.run_id, optimizer_steps=2)
        manual = working(store, "manual")
        store.transition(manual.run_id, "pausing", reason="manual")
        store.transition(manual.run_id, "paused", reason="manual")
        stopping = working(store, "stopping")
        store.transition(stopping.run_id, "stopping")
        pausing = working(store, "pausing")
        store.transition(pausing.run_id, "pausing")
    with RunStore(path, now=clock) as store:
        assert store.get_run(active.run_id).state == "training"
        recovered = {record.run_id: record for record in store.recover_interrupted_runs()}
        assert set(recovered) == {active.run_id, stopping.run_id, pausing.run_id}
        assert recovered[active.run_id].state == "paused"
        assert recovered[active.run_id].resume_state == "training"
        assert recovered[active.run_id].reserved_optimizer_steps == 2
        assert recovered[stopping.run_id].state == "stopped"
        assert recovered[pausing.run_id].resume_state == "training"
        assert store.get_run(manual.run_id).reason == "manual"
        assert store.recover_interrupted_runs() == []
        assert store.resume(active.run_id).state == "training"


def test_create_is_idempotent_only_for_identical_payload_and_run_id(tmp_path):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        snapshot = config()
        run = store.create_run(snapshot, "request", run_id="run-fixed")
        assert (
            store.create_run(dict(reversed(list(snapshot.items()))), "request").run_id == run.run_id
        )
        assert len(store.list_runs()) == 1
        with pytest.raises(LifecycleError, match="different payload"):
            store.create_run(config(max_optimizer_steps=5), "request")
        with pytest.raises(LifecycleError, match="different payload"):
            store.create_run(snapshot, "request", run_id="different-run")
        with pytest.raises(LifecycleError, match="already exists"):
            store.create_run(snapshot, "different-request", run_id="run-fixed")
        snapshot["budget"]["max_optimizer_steps"] = 1
        assert store.get_run(run.run_id).config_snapshot["budget"]["max_optimizer_steps"] == 10


def test_clock_rollback_does_not_restore_wall_or_daily_budget_across_reopen(tmp_path):
    clock = Clock(datetime(2026, 9, 22, 22, 0, 1, tzinfo=timezone.utc))
    path = tmp_path / "control.db"
    with RunStore(path, now=clock) as store:
        run = working(store, max_wall_seconds=10)
        store.consume(run.run_id, active_seconds=3)
        clock.advance(11)
        with pytest.raises(BudgetExceeded, match="wall_time_budget"):
            store.consume(run.run_id, active_seconds=1)
    clock.advance(-3600)
    with RunStore(path, now=clock) as store:
        after = store.get_run(run.run_id)
        assert after.wall_seconds == 11
        assert after.remaining["wall_seconds"] == 0
        assert after.remaining["daily_date"] == "2026-09-23"
        assert after.remaining["daily_active_seconds"] == 997
        with pytest.raises(BudgetExceeded, match="wall_time_budget"):
            store.assert_can_work(run.run_id)


def test_future_schema_is_rejected_without_overwriting_database(tmp_path):
    path = tmp_path / "future.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE future_data (message TEXT)")
        connection.execute("INSERT INTO future_data VALUES ('keep me')")
        connection.execute("PRAGMA user_version=42")
    with pytest.raises(SchemaVersionError, match="42"):
        RunStore(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 42
        assert connection.execute("SELECT message FROM future_data").fetchone()[0] == "keep me"


def test_unversioned_nonempty_database_requires_migration(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE old_data (message TEXT)")
    with pytest.raises(SchemaVersionError, match="explicit migration"):
        RunStore(path)


def test_two_sqlite_connections_compete_for_exactly_one_shared_reservation(tmp_path):
    path = tmp_path / "concurrent.db"
    clock = Clock()
    with RunStore(path, now=clock) as first, RunStore(path, now=clock) as second:
        left = working(first, "left", max_daily_active_seconds=1)
        right = working(second, "right", max_daily_active_seconds=1)
        barrier = threading.Barrier(2)

        def reserve(store, run_id):
            barrier.wait(timeout=5)
            try:
                store.consume(run_id, optimizer_steps=1, active_seconds=1)
                return "allowed"
            except BudgetExceeded:
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(
                workers.map(
                    lambda args: reserve(*args), [(first, left.run_id), (second, right.run_id)]
                )
            )
        assert sorted(outcomes) == ["allowed", "denied"]
        records = first.list_runs()
        assert sum(record.reserved_optimizer_steps for record in records) == 1
        assert sum(record.reserved_active_seconds for record in records) == 1


def test_same_run_concurrent_step_reservations_do_not_overshoot(tmp_path):
    path = tmp_path / "concurrent.db"
    clock = Clock()
    with RunStore(path, now=clock) as first, RunStore(path, now=clock) as second:
        run = working(first, max_optimizer_steps=9)
        barrier = threading.Barrier(2)

        def reserve_all(store):
            barrier.wait(timeout=5)
            successful = 0
            for _ in range(10):
                try:
                    store.consume(run.run_id, optimizer_steps=1)
                    successful += 1
                except BudgetExceeded:
                    break
            return successful

        with ThreadPoolExecutor(max_workers=2) as workers:
            counts = list(workers.map(reserve_all, [first, second]))
        assert sum(counts) == 9
        assert first.get_run(run.run_id).reserved_optimizer_steps == 9


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan"), float("inf"), 2**1024, -(2**1024)])
def test_invalid_reservation_units_never_change_counters(tmp_path, value):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        run = working(store)
        with pytest.raises(LifecycleError):
            store.consume(run.run_id, environment_steps=value)
        assert store.get_run(run.run_id).reserved_environment_steps == 0


def test_terminal_run_and_created_run_cannot_start_work(tmp_path):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        run = store.create_run(config(), "request")
        with pytest.raises(LifecycleError, match="created"):
            store.consume(run.run_id, optimizer_steps=1)
        store.transition(run.run_id, "initializing")
        store.transition(run.run_id, "training")
        store.transition(run.run_id, "stopping")
        store.transition(run.run_id, "stopped")
        with pytest.raises(LifecycleError, match="stopped"):
            store.consume(run.run_id, optimizer_steps=1)
        with pytest.raises(LifecycleError, match="Invalid transition"):
            store.transition(run.run_id, "initializing")


def test_naive_clock_is_rejected(tmp_path):
    with RunStore(tmp_path / "control.db", now=lambda: datetime(2026, 9, 22)) as store:
        with pytest.raises(LifecycleError, match="timezone-aware"):
            store.create_run(config(), "request")


@pytest.mark.parametrize("terminal_state", ["completed", "failed", "stopped"])
def test_historical_terminal_queries_do_not_change_new_day_budget(tmp_path, terminal_state):
    path = tmp_path / "control.db"
    clock = Clock()
    with RunStore(path, now=clock) as store:
        old = working(store, "yesterday", max_daily_active_seconds=2)
        if terminal_state == "stopped":
            store.transition(old.run_id, "stopping")
        store.transition(old.run_id, terminal_state)
        clock.advance(24 * 3600)
        current = working(store, "today", max_daily_active_seconds=100)
        store.consume(current.run_id, active_seconds=3)
        with sqlite3.connect(path) as db:
            before = db.execute("SELECT * FROM daily_budget ORDER BY local_date").fetchall()
        store.get_run(old.run_id)
        store.list_runs()
        store.check_budget(old.run_id)
        # An idempotent create retry is also a lookup, not a new admission.
        store.create_run(config(max_daily_active_seconds=2), "yesterday")
        with sqlite3.connect(path) as db:
            after = db.execute("SELECT * FROM daily_budget ORDER BY local_date").fetchall()
        assert before == after
        assert store.get_run(current.run_id).remaining["daily_limit_seconds"] == 100
        assert store.get_run(current.run_id).remaining["daily_active_seconds"] == 97
        store.consume(current.run_id, active_seconds=3)


def test_budget_preflight_does_not_create_future_day_ledger(tmp_path):
    path = tmp_path / "control.db"
    clock = Clock(datetime(2026, 9, 22, 21, 59, 58, tzinfo=timezone.utc))
    with RunStore(path, now=clock) as store:
        run = working(store, max_daily_active_seconds=5)
        assert store.check_budget(run.run_id, active_seconds=4).allowed
        assert store.assert_can_work(run.run_id, active_seconds=4).allowed
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT local_date FROM daily_budget").fetchall() == [("2026-09-22",)]
        store.consume(run.run_id, active_seconds=4)
        with sqlite3.connect(path) as db:
            assert db.execute(
                "SELECT local_date,reserved_seconds FROM daily_budget ORDER BY local_date"
            ).fetchall() == [("2026-09-22", 2), ("2026-09-23", 2)]


@pytest.mark.parametrize("admission", ["consume", "resume", "initialize"])
def test_previous_day_run_tightens_today_only_when_admitted_for_work(tmp_path, admission):
    path = tmp_path / "control.db"
    clock = Clock()
    long_wall = 3 * 24 * 3600
    with RunStore(path, now=clock) as store:
        old = store.create_run(
            config(max_wall_seconds=long_wall, max_daily_active_seconds=5), "yesterday"
        )
        if admission != "initialize":
            store.transition(old.run_id, "initializing")
            store.transition(old.run_id, "training")
        if admission == "resume":
            store.transition(old.run_id, "pausing", reason="manual")
            store.transition(old.run_id, "paused", reason="manual")
        clock.advance(24 * 3600)
        current = working(store, "today", max_daily_active_seconds=100)
        store.get_run(old.run_id)
        store.list_runs()
        assert store.get_run(current.run_id).remaining["daily_limit_seconds"] == 100
        if admission == "consume":
            store.assert_can_work(old.run_id, active_seconds=1)
            assert store.get_run(current.run_id).remaining["daily_limit_seconds"] == 100
            store.consume(old.run_id, active_seconds=1)
        elif admission == "resume":
            store.resume(old.run_id)
        else:
            store.transition(old.run_id, "initializing")
        assert store.get_run(current.run_id).remaining["daily_limit_seconds"] == 5
