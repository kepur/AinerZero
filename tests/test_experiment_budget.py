from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from ainerzero.runtime.lifecycle import BudgetExceeded, LifecycleError, RunStore


class Clock:
    def __init__(self):
        self.instant = datetime(2026, 9, 23, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.instant

    def advance(self, seconds):
        self.instant += timedelta(seconds=seconds)


def manifest(**experiment_budget):
    return {
        "name": "bounded-c0-pilot",
        "mechanism_revision": "fixed-learner-v1",
        "budget": {
            "max_environment_steps": 10,
            "max_optimizer_steps": 10,
            "max_model_transitions": 100,
            "max_wall_seconds": 100,
            "max_daily_active_seconds": 1000,
            "timezone": "Europe/Belgrade",
        },
        "experiment_budget": {
            "max_model_runs": 3,
            "max_environment_steps": 25,
            "max_optimizer_steps": 25,
            "max_model_transitions": 250,
            "max_wall_seconds": 300,
            "max_calibration_seconds": 30,
            **experiment_budget,
        },
    }


def snapshot(plan, **budget):
    return {"model": {"name": "test-pilot"}, "budget": {**plan["budget"], **budget}}


def working(store, experiment, plan, request, *, role="model", **budget):
    run = store.create_run(
        snapshot(plan, **budget), request, experiment_id=experiment.experiment_id, role=role
    )
    store.transition(run.run_id, "initializing")
    return store.transition(run.run_id, "training")


def counts(record):
    return (
        record.reserved_environment_steps,
        record.reserved_optimizer_steps,
        record.reserved_model_transitions,
        record.reserved_active_seconds,
    )


def test_experiment_identity_manifest_snapshot_and_hash_are_durable(tmp_path):
    path = tmp_path / "control.db"
    plan = manifest()
    expected = copy.deepcopy(plan)
    canonical = json.dumps(
        plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    with RunStore(path, now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment-request", experiment_id="pilot")
        assert experiment.experiment_id == "pilot"
        assert experiment.manifest_hash == hashlib.sha256(canonical.encode()).hexdigest()
        assert experiment.manifest == expected
        assert counts(experiment) == (0, 0, 0, 0)
        assert experiment.model_run_count == 0
        plan["experiment_budget"]["max_model_runs"] = 99
        assert store.get_experiment("pilot").manifest == expected
    with RunStore(path, now=Clock()) as store:
        assert store.get_experiment("pilot").manifest == expected
        assert store.get_experiment("pilot").manifest_hash == experiment.manifest_hash


def test_experiment_creation_retry_is_idempotent_and_conflicts_are_rejected(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "request", experiment_id="pilot")
        reordered = dict(reversed(list(plan.items())))
        assert store.create_experiment(reordered, "request").experiment_id == "pilot"
        with pytest.raises(LifecycleError):
            store.create_experiment(manifest(max_model_runs=2), "request")
        with pytest.raises(LifecycleError):
            store.create_experiment(plan, "request", experiment_id="different")
        with pytest.raises(LifecycleError):
            store.create_experiment(plan, "other-request", experiment_id="pilot")
        assert counts(store.get_experiment(experiment.experiment_id)) == (0, 0, 0, 0)


def test_completed_and_failed_runs_keep_their_experiment_reservations(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        first = working(store, experiment, plan, "first")
        store.consume(
            first.run_id,
            environment_steps=4,
            optimizer_steps=2,
            model_transitions=30,
            active_seconds=5,
        )
        store.transition(first.run_id, "completed")
        second = working(store, experiment, plan, "second")
        store.consume(
            second.run_id,
            environment_steps=3,
            optimizer_steps=1,
            model_transitions=20,
            active_seconds=6,
        )
        store.transition(second.run_id, "failed", reason="worker_crash")
        current = store.get_experiment(experiment.experiment_id)
        assert counts(current) == (7, 3, 50, 11)
        assert current.model_run_count == 2
        assert current.remaining["environment_steps"] == 18
        assert current.remaining["optimizer_steps"] == 22
        assert current.remaining["model_transitions"] == 200
        assert current.remaining["wall_seconds"] == 289


@pytest.mark.parametrize(
    ("limit", "first_units", "second_units"),
    [
        ("max_environment_steps", {"environment_steps": 9}, {"environment_steps": 7}),
        ("max_optimizer_steps", {"optimizer_steps": 9}, {"optimizer_steps": 7}),
        ("max_model_transitions", {"model_transitions": 90}, {"model_transitions": 70}),
    ],
)
def test_aggregate_denials_do_not_charge_run_experiment_or_shared_daily(
    tmp_path, limit, first_units, second_units
):
    plan = manifest(**{limit: 150 if limit == "max_model_transitions" else 15})
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        first = working(store, experiment, plan, "first")
        store.consume(first.run_id, **first_units, active_seconds=2)
        store.transition(first.run_id, "completed")
        second = working(store, experiment, plan, "second")
        before_experiment = counts(store.get_experiment(experiment.experiment_id))
        before_run = counts(store.get_run(second.run_id))
        before_daily = store.get_run(second.run_id).remaining["daily_active_seconds"]
        units = {"environment_steps": 1, "optimizer_steps": 1, "model_transitions": 1}
        units.update(second_units)
        assert not store.check_budget(second.run_id, **units, active_seconds=3).allowed
        with pytest.raises(BudgetExceeded):
            store.assert_can_work(second.run_id, **units, active_seconds=3)
        with pytest.raises(BudgetExceeded):
            store.consume(second.run_id, **units, active_seconds=3)
        assert counts(store.get_experiment(experiment.experiment_id)) == before_experiment
        assert counts(store.get_run(second.run_id)) == before_run
        assert store.get_run(second.run_id).remaining["daily_active_seconds"] == before_daily


def test_preflight_does_not_charge_imagined_model_transitions(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        run = working(store, experiment, plan, "model")
        assert store.check_budget(run.run_id, model_transitions=100).allowed
        assert store.assert_can_work(run.run_id, model_transitions=100).allowed
        assert counts(store.get_run(run.run_id)) == (0, 0, 0, 0)
        assert counts(store.get_experiment(experiment.experiment_id)) == (0, 0, 0, 0)
        reserved = store.consume(run.run_id, model_transitions=100)
        assert counts(reserved) == (0, 0, 100, 0)
        assert not store.check_budget(run.run_id).allowed
        with pytest.raises(BudgetExceeded):
            store.consume(run.run_id, environment_steps=1)


def test_model_slots_include_failed_runs_but_creation_retries_do_not_use_slots(tmp_path):
    plan = manifest(max_model_runs=2)
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        first = working(store, experiment, plan, "first")
        retry = store.create_run(snapshot(plan), "first", experiment_id=experiment.experiment_id)
        assert retry.run_id == first.run_id
        assert store.get_experiment(experiment.experiment_id).model_run_count == 1
        store.transition(first.run_id, "failed")
        second = working(store, experiment, plan, "second")
        assert store.get_experiment(experiment.experiment_id).model_run_count == 2
        # The last admitted model still has its full work allocation.
        store.consume(second.run_id, model_transitions=1)
        store.transition(second.run_id, "completed")
        with pytest.raises(BudgetExceeded):
            store.create_run(snapshot(plan), "third", experiment_id=experiment.experiment_id)
        auxiliary = working(store, experiment, plan, "evaluation", role="auxiliary")
        store.consume(auxiliary.run_id, model_transitions=1)
        assert store.get_experiment(experiment.experiment_id).model_run_count == 2


@pytest.mark.parametrize("state", ["created", "training", "paused", "stopping"])
def test_nonterminal_model_holds_the_only_active_model_slot(tmp_path, state):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        first = store.create_run(snapshot(plan), "first", experiment_id=experiment.experiment_id)
        if state != "created":
            store.transition(first.run_id, "initializing")
            store.transition(first.run_id, "training")
        if state == "paused":
            store.transition(first.run_id, "pausing")
            store.transition(first.run_id, "paused")
        elif state == "stopping":
            store.transition(first.run_id, "stopping")
        with pytest.raises(LifecycleError):
            store.create_run(snapshot(plan), "second", experiment_id=experiment.experiment_id)
        assert store.get_experiment(experiment.experiment_id).model_run_count == 1
        if state != "stopping":
            store.transition(first.run_id, "stopping")
        store.transition(first.run_id, "stopped")
        working(store, experiment, plan, "after-stop")
        assert store.get_experiment(experiment.experiment_id).model_run_count == 2


def test_calibration_and_auxiliary_share_totals_without_taking_model_slots(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        calibration = working(store, experiment, plan, "calibrate", role="calibration")
        store.consume(
            calibration.run_id, environment_steps=2, model_transitions=3, active_seconds=20
        )
        store.transition(calibration.run_id, "completed")
        second = working(store, experiment, plan, "calibrate-again", role="calibration")
        with pytest.raises(BudgetExceeded):
            store.consume(second.run_id, optimizer_steps=1, active_seconds=11)
        assert counts(store.get_run(second.run_id)) == (0, 0, 0, 0)
        store.consume(second.run_id, active_seconds=10)
        store.transition(second.run_id, "completed")
        auxiliary = working(store, experiment, plan, "baseline", role="auxiliary")
        store.consume(auxiliary.run_id, environment_steps=1, active_seconds=2)
        current = store.get_experiment(experiment.experiment_id)
        assert counts(current) == (3, 0, 3, 32)
        assert current.model_run_count == 0
        store.transition(auxiliary.run_id, "completed")
        model = working(store, experiment, plan, "model")
        store.consume(model.run_id, optimizer_steps=1, active_seconds=1)
        assert counts(store.get_experiment(experiment.experiment_id)) == (3, 1, 3, 33)


@pytest.mark.parametrize("first_role", ["model", "calibration", "auxiliary"])
@pytest.mark.parametrize("second_role", ["model", "calibration", "auxiliary"])
def test_all_roles_share_one_nonterminal_run_slot(tmp_path, first_role, second_role):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        first = working(store, experiment, plan, "first", role=first_role)
        store.transition(first.run_id, "pausing")
        store.transition(first.run_id, "paused")
        before = store.get_experiment(experiment.experiment_id)
        with pytest.raises(LifecycleError):
            store.create_run(
                snapshot(plan), "second", experiment_id=experiment.experiment_id, role=second_role
            )
        assert len(store.list_runs()) == 1
        assert store.get_experiment(experiment.experiment_id) == before


def test_auxiliary_cannot_bypass_model_slots_with_optimizer_updates(tmp_path):
    plan = manifest(max_model_runs=1)
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        model = working(store, experiment, plan, "model")
        store.transition(model.run_id, "failed")
        auxiliary = working(store, experiment, plan, "evaluate", role="auxiliary")
        before = store.get_experiment(experiment.experiment_id)
        assert not store.check_budget(auxiliary.run_id, optimizer_steps=1).allowed
        for method in (store.assert_can_work, store.consume):
            with pytest.raises(BudgetExceeded, match="auxiliary_optimizer_updates_forbidden"):
                method(auxiliary.run_id, optimizer_steps=1, environment_steps=1, active_seconds=2)
        assert counts(store.get_run(auxiliary.run_id)) == (0, 0, 0, 0)
        assert store.get_experiment(experiment.experiment_id) == before
        assert store.get_run(auxiliary.run_id).remaining["daily_active_seconds"] == 1000
        store.consume(auxiliary.run_id, model_transitions=1)


def test_calibration_cannot_restart_after_a_model_run(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        calibration = working(store, experiment, plan, "calibrate", role="calibration")
        store.consume(calibration.run_id, optimizer_steps=1, active_seconds=1)
        store.transition(calibration.run_id, "completed")
        model = working(store, experiment, plan, "model")
        store.transition(model.run_id, "failed")
        with pytest.raises(LifecycleError, match="calibration must precede"):
            store.create_run(
                snapshot(plan),
                "new-calibration",
                experiment_id=experiment.experiment_id,
                role="calibration",
            )
        assert len(store.list_runs()) == 2
        assert counts(store.get_experiment(experiment.experiment_id)) == (0, 1, 0, 1)


def test_shared_daily_denial_does_not_charge_experiment(tmp_path):
    plan = manifest()
    plan["budget"]["max_daily_active_seconds"] = 10
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        first_experiment = store.create_experiment(plan, "first-experiment")
        first = working(store, first_experiment, plan, "first-run")
        store.consume(first.run_id, active_seconds=8)
        second_experiment = store.create_experiment(plan, "second-experiment")
        second = working(store, second_experiment, plan, "second-run")
        with pytest.raises(BudgetExceeded):
            store.consume(second.run_id, environment_steps=1, model_transitions=1, active_seconds=3)
        assert counts(store.get_experiment(second_experiment.experiment_id)) == (0, 0, 0, 0)
        assert counts(store.get_run(second.run_id)) == (0, 0, 0, 0)
        assert store.get_run(second.run_id).remaining["daily_active_seconds"] == 2


def test_experiment_total_clock_survives_pause_reopen_and_clock_rollback(tmp_path):
    path = tmp_path / "control.db"
    clock = Clock()
    plan = manifest(max_wall_seconds=120)
    with RunStore(path, now=clock) as store:
        experiment = store.create_experiment(plan, "experiment")
        clock.advance(40)
        run = working(store, experiment, plan, "first")
        store.consume(run.run_id, active_seconds=3)
        store.transition(run.run_id, "pausing")
        store.transition(run.run_id, "paused")
        clock.advance(81)
        assert store.get_experiment(experiment.experiment_id).remaining["wall_seconds"] == 0
    clock.advance(-3600)
    with RunStore(path, now=clock) as store:
        assert store.get_experiment(experiment.experiment_id).remaining["wall_seconds"] == 0
        with pytest.raises(BudgetExceeded):
            store.resume(run.run_id)
        assert store.get_run(run.run_id).state == "paused"
        assert counts(store.get_experiment(experiment.experiment_id)) == (0, 0, 0, 3)


def test_two_connections_cannot_overspend_last_experiment_rollout_quota(tmp_path):
    path = tmp_path / "control.db"
    clock = Clock()
    plan = manifest(max_model_transitions=150)
    with RunStore(path, now=clock) as first, RunStore(path, now=clock) as second:
        experiment = first.create_experiment(plan, "experiment")
        previous = working(first, experiment, plan, "previous")
        first.consume(previous.run_id, model_transitions=90)
        first.transition(previous.run_id, "completed")
        run = working(first, experiment, plan, "current")
        barrier = threading.Barrier(2)

        def reserve(store):
            barrier.wait(timeout=5)
            try:
                store.consume(run.run_id, model_transitions=40, optimizer_steps=1, active_seconds=2)
                return "allowed"
            except BudgetExceeded:
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(reserve, [first, second]))
        assert sorted(outcomes) == ["allowed", "denied"]
        assert counts(first.get_run(run.run_id)) == (0, 1, 40, 2)
        assert counts(second.get_experiment(experiment.experiment_id)) == (0, 1, 130, 2)
        assert second.get_run(run.run_id).remaining["daily_active_seconds"] == 998


def test_two_connections_cannot_admit_parallel_experiment_runs(tmp_path):
    path = tmp_path / "control.db"
    plan = manifest()
    with RunStore(path, now=Clock()) as first, RunStore(path, now=Clock()) as second:
        experiment = first.create_experiment(plan, "experiment")
        barrier = threading.Barrier(2)

        def admit(item):
            store, request, role = item
            barrier.wait(timeout=5)
            try:
                store.create_run(
                    snapshot(plan), request, experiment_id=experiment.experiment_id, role=role
                )
                return "allowed"
            except LifecycleError:
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(
                workers.map(
                    admit,
                    [
                        (first, "model", "model"),
                        (second, "evaluation", "auxiliary"),
                    ],
                )
            )
        assert sorted(outcomes) == ["allowed", "denied"]
        assert len(first.list_runs()) == 1
        assert counts(second.get_experiment(experiment.experiment_id)) == (0, 0, 0, 0)


def test_rejected_run_creation_keeps_expired_experiment_clock_across_reopen(tmp_path):
    path = tmp_path / "control.db"
    clock = Clock()
    plan = manifest(max_wall_seconds=40)
    with RunStore(path, now=clock) as store:
        experiment = store.create_experiment(plan, "experiment")
        clock.advance(41)
        with pytest.raises(BudgetExceeded, match="experiment_wall_seconds_budget"):
            store.create_run(snapshot(plan), "run", experiment_id=experiment.experiment_id)
        # Do not query another record here: the rejected creation itself must
        # persist the high-water, while creating no run or daily reservation.
    clock.advance(-3600)
    with RunStore(path, now=clock) as store:
        with pytest.raises(BudgetExceeded, match="experiment_wall_seconds_budget"):
            store.create_run(snapshot(plan), "run", experiment_id=experiment.experiment_id)
        assert store.list_runs() == []
        assert store.get_experiment(experiment.experiment_id).remaining["wall_seconds"] == 0
        with sqlite3.connect(path) as db:
            assert db.execute("SELECT COUNT(*) FROM daily_budget").fetchone()[0] == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_environment_steps", 11),
        ("max_optimizer_steps", 11),
        ("max_model_transitions", 101),
        ("max_wall_seconds", 101),
        ("max_daily_active_seconds", 1001),
        ("timezone", "UTC"),
    ],
)
def test_attached_run_cannot_raise_frozen_manifest_limits(tmp_path, field, value):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        with pytest.raises(LifecycleError):
            store.create_run(
                snapshot(plan, **{field: value}), "invalid", experiment_id=experiment.experiment_id
            )
        assert store.list_runs() == []
        assert store.get_experiment(experiment.experiment_id).model_run_count == 0


def test_run_creation_retry_must_match_experiment_and_role(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        first = store.create_experiment(plan, "first")
        second = store.create_experiment(plan, "second")
        run = store.create_run(snapshot(plan), "run", experiment_id=first.experiment_id)
        for experiment_id, role in [
            (first.experiment_id, "auxiliary"),
            (second.experiment_id, "model"),
            (None, "model"),
        ]:
            with pytest.raises(LifecycleError):
                store.create_run(snapshot(plan), "run", experiment_id=experiment_id, role=role)
        assert store.get_run(run.run_id).state == "created"
        assert store.get_experiment(first.experiment_id).model_run_count == 1
        assert store.get_experiment(second.experiment_id).model_run_count == 0


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan"), float("inf"), 2**64])
def test_invalid_model_transition_units_change_no_counters(tmp_path, value):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        experiment = store.create_experiment(plan, "experiment")
        run = working(store, experiment, plan, "run")
        for method in [store.check_budget, store.assert_can_work, store.consume]:
            with pytest.raises(LifecycleError):
                method(run.run_id, model_transitions=value)
        assert counts(store.get_run(run.run_id)) == (0, 0, 0, 0)
        assert counts(store.get_experiment(experiment.experiment_id)) == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_model_runs", True),
        ("max_model_runs", 0),
        ("max_model_runs", 1.5),
        ("max_environment_steps", -1),
        ("max_optimizer_steps", 0),
        ("max_model_transitions", float("inf")),
        ("max_wall_seconds", float("nan")),
        ("max_calibration_seconds", -1),
    ],
)
def test_invalid_experiment_limits_are_rejected(tmp_path, field, value):
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        with pytest.raises(LifecycleError):
            store.create_experiment(manifest(**{field: value}), "invalid")


@pytest.mark.parametrize("missing", ["budget", "experiment_budget"])
def test_experiment_requires_both_frozen_budget_sections(tmp_path, missing):
    plan = manifest()
    del plan[missing]
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        with pytest.raises(LifecycleError):
            store.create_experiment(plan, "invalid")


@pytest.mark.parametrize("missing", list(manifest()["budget"]))
def test_experiment_cannot_silently_default_a_missing_run_limit(tmp_path, missing):
    plan = manifest()
    del plan["budget"][missing]
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        with pytest.raises(LifecycleError, match="freeze all"):
            store.create_experiment(plan, "invalid")


def test_unknown_experiment_and_role_are_rejected_before_run_admission(tmp_path):
    plan = manifest()
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        with pytest.raises((KeyError, LifecycleError)):
            store.create_run(snapshot(plan), "unknown", experiment_id="missing")
        experiment = store.create_experiment(plan, "experiment")
        with pytest.raises(LifecycleError):
            store.create_run(
                snapshot(plan), "bad-role", experiment_id=experiment.experiment_id, role="unlimited"
            )
        assert store.list_runs() == []
        assert store.get_experiment(experiment.experiment_id).model_run_count == 0


def test_experiments_use_the_project_timezone(tmp_path):
    plan = manifest()
    other = copy.deepcopy(plan)
    other["budget"]["timezone"] = "UTC"
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        store.create_experiment(plan, "first")
        with pytest.raises(LifecycleError, match="timezone"):
            store.create_experiment(other, "second")


def test_old_run_without_rollout_budget_still_works_but_cannot_reserve_rollouts(tmp_path):
    plan = manifest()
    old = snapshot(plan)
    del old["budget"]["max_model_transitions"]
    with RunStore(tmp_path / "control.db", now=Clock()) as store:
        run = store.create_run(old, "old-run")
        store.transition(run.run_id, "initializing")
        store.transition(run.run_id, "training")
        assert store.assert_can_work(run.run_id, optimizer_steps=1).allowed
        store.consume(run.run_id, optimizer_steps=1)
        with pytest.raises(BudgetExceeded):
            store.consume(run.run_id, model_transitions=1, active_seconds=2)
        assert counts(store.get_run(run.run_id)) == (0, 1, 0, 0)


def test_schema_one_migration_preserves_existing_run_and_daily_reservations(tmp_path):
    path = tmp_path / "old.db"
    clock = Clock()
    old_config = snapshot(manifest())
    del old_config["budget"]["max_model_transitions"]
    payload = json.dumps(old_config, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    at = clock().timestamp()
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL, resume_state TEXT, reason TEXT,
                config_json TEXT NOT NULL, config_hash TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                environment_steps INTEGER NOT NULL DEFAULT 0,
                optimizer_steps INTEGER NOT NULL DEFAULT 0,
                active_seconds REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE daily_budget (
                local_date TEXT PRIMARY KEY, limit_seconds REAL NOT NULL,
                reserved_seconds REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE run_transitions (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                from_state TEXT, to_state TEXT NOT NULL, reason TEXT, at REAL NOT NULL
            );
            PRAGMA user_version=1;
        """)
        db.execute("INSERT INTO metadata VALUES ('project_timezone', 'Europe/Belgrade')")
        db.execute("INSERT INTO metadata VALUES ('clock_high_water', ?)", (str(at),))
        db.execute(
            "INSERT INTO runs VALUES ('legacy','old-request','training',NULL,NULL,?,?,?,?,2,3,4)",
            (payload, digest, at, at),
        )
        db.execute("INSERT INTO daily_budget VALUES ('2026-09-23', 1000, 4)")
        db.execute("INSERT INTO run_transitions VALUES (1,'legacy',NULL,'created',NULL,?)", (at,))
    with RunStore(path, now=clock) as store:
        old = store.get_run("legacy")
        assert old.config_hash == digest
        assert old.state == "training"
        assert counts(old) == (2, 3, 0, 4)
        assert old.remaining["daily_active_seconds"] == 996
        store.consume("legacy", optimizer_steps=1)
        assert store.get_run("legacy").reserved_optimizer_steps == 4
        experiment = store.create_experiment(manifest(), "new-experiment")
        run = working(store, experiment, manifest(), "new-run")
        assert run.remaining["daily_active_seconds"] == 996
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert (
            db.execute("SELECT COUNT(*) FROM run_transitions WHERE run_id='legacy'").fetchone()[0]
            == 1
        )
