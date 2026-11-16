"""Durable run lifecycle and atomic, pre-work budget reservations.

``consume`` reserves quota *before* a worker starts a bounded unit. Reservations
are conservative (not refunded on a crash) and are not evidence of completed
environment actions or optimizer updates. Workers record actual results apart.
Only the supervisor charges elapsed activity, once for overlapping workers.
Each reservation's duration starts at the current effective time and is split
over local midnights. The project timezone is fixed at its first experiment or run.

Opening a second store never changes a live run's lifecycle. On exclusive
supervisor startup, call ``recover_interrupted_runs`` before admitting workers.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEMA_VERSION = 2
WORK_STATES = frozenset({"collecting", "training", "validating"})
RECOVERABLE_STATES = WORK_STATES | {"initializing"}
TERMINAL_STATES = frozenset({"completed", "stopped", "failed"})
TRANSITIONS = {
    "created": {"initializing", "stopping", "failed"},
    "initializing": set(WORK_STATES) | {"pausing", "stopping", "failed"},
    **{
        s: (set(WORK_STATES) - {s}) | {"completed", "pausing", "stopping", "failed"}
        for s in WORK_STATES
    },
    "pausing": {"paused", "stopping", "failed"},
    "paused": set(RECOVERABLE_STATES) | {"stopping", "failed"},
    "stopping": {"stopped", "failed"},
    **{s: set() for s in TERMINAL_STATES},
}


class LifecycleError(ValueError):
    """An invalid lifecycle, configuration, or idempotency request."""


class SchemaVersionError(LifecycleError):
    """The database needs an explicit migration before it can be used."""


class BudgetExceeded(LifecycleError):
    def __init__(self, reason: str, remaining: dict[str, Any]):
        self.reason = reason
        self.remaining = remaining
        super().__init__(f"Budget exhausted: {reason}")


@dataclass(frozen=True)
class BudgetStatus:
    allowed: bool
    reason: str | None
    remaining: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    request_id: str
    state: str
    resume_state: str | None
    reason: str | None
    config_snapshot: dict[str, Any]
    config_hash: str
    created_at: str
    updated_at: str
    reserved_environment_steps: int
    reserved_optimizer_steps: int
    reserved_active_seconds: float
    wall_seconds: float
    remaining: dict[str, Any]
    experiment_id: str | None
    role: str
    reserved_model_transitions: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    request_id: str
    manifest: dict[str, Any]
    manifest_hash: str
    created_at: str
    model_run_count: int
    reserved_environment_steps: int
    reserved_optimizer_steps: int
    reserved_model_transitions: int
    reserved_active_seconds: float
    remaining: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _nonnegative(value: Any, field: str, *, integer: bool = False) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LifecycleError(f"{field} must be a finite nonnegative number")
    if isinstance(value, int) and value > 2**63 - 1:
        raise LifecycleError(f"{field} exceeds SQLite integer range")
    if value < 0 or (integer and not isinstance(value, int)) or not math.isfinite(value):
        raise LifecycleError(
            f"{field} must be a finite nonnegative {'integer' if integer else 'number'}"
        )
    return value


def _budget(snapshot: dict[str, Any]) -> dict[str, Any]:
    values = snapshot.get("budget", {})
    if not isinstance(values, dict):
        raise LifecycleError("config_snapshot.budget must be an object")
    result = {
        "max_environment_steps": 1_000_000,
        "max_optimizer_steps": 20_000,
        "max_wall_seconds": 21_600,
        "max_daily_active_seconds": 21_600,
        # Legacy M0 has no model rollout operation; it receives no such quota.
        "max_model_transitions": 0,
        "timezone": "Europe/Belgrade",
        **values,
    }
    for key in (
        "max_environment_steps",
        "max_optimizer_steps",
        "max_wall_seconds",
        "max_daily_active_seconds",
    ):
        _nonnegative(result[key], key, integer=key.endswith("steps"))
        if result[key] <= 0:
            raise LifecycleError(f"{key} must be positive")
    try:
        ZoneInfo(result["timezone"])
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise LifecycleError("budget.timezone must name an installed IANA timezone") from exc
    _nonnegative(result["max_model_transitions"], "max_model_transitions", integer=True)
    return result


def _experiment_budget(manifest: dict[str, Any]) -> dict[str, Any]:
    run_fields = {
        "max_environment_steps",
        "max_optimizer_steps",
        "max_model_transitions",
        "max_wall_seconds",
        "max_daily_active_seconds",
        "timezone",
    }
    run_limits = manifest.get("budget")
    if not isinstance(run_limits, dict) or set(run_limits) != run_fields:
        raise LifecycleError("experiment budget must freeze all supported run limits")
    values = manifest.get("experiment_budget")
    fields = {
        "max_model_runs",
        "max_environment_steps",
        "max_optimizer_steps",
        "max_model_transitions",
        "max_wall_seconds",
        "max_calibration_seconds",
    }
    if not isinstance(values, dict) or set(values) != fields:
        raise LifecycleError("experiment_budget must contain exactly the supported limits")
    for key, value in values.items():
        _nonnegative(value, key, integer=not key.endswith("seconds"))
        if value <= 0:
            raise LifecycleError(f"{key} must be positive")
    if values["max_calibration_seconds"] > values["max_wall_seconds"]:
        raise LifecycleError("calibration cannot exceed experiment wall budget")
    _budget(manifest)
    return values


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


class RunStore:
    def __init__(self, db_path: str | Path, now: Callable[[], datetime] | None = None):
        self.path = Path(db_path) if str(db_path) != ":memory:" else None
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            str(db_path), timeout=30, isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        try:
            self._initialize()
        except BaseException:
            self._conn.close()
            raise

    def __enter__(self) -> RunStore:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    def _initialize(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise SchemaVersionError(
                f"Database schema {version} is unsupported; expected {SCHEMA_VERSION}"
            )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        with self._transaction() as db:
            # A concurrent opener may have initialized the file while we waited.
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version == 0:
                tables = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                if tables:
                    raise SchemaVersionError(
                        "Unversioned nonempty database requires an explicit migration"
                    )
                db.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("""CREATE TABLE runs (
                    run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    state TEXT NOT NULL, resume_state TEXT, reason TEXT,
                    config_json TEXT NOT NULL, config_hash TEXT NOT NULL,
                    created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    environment_steps INTEGER NOT NULL DEFAULT 0 CHECK(environment_steps >= 0),
                    optimizer_steps INTEGER NOT NULL DEFAULT 0 CHECK(optimizer_steps >= 0),
                    active_seconds REAL NOT NULL DEFAULT 0 CHECK(active_seconds >= 0)
                )""")
                db.execute("""CREATE TABLE daily_budget (
                    local_date TEXT PRIMARY KEY, limit_seconds REAL NOT NULL,
                    reserved_seconds REAL NOT NULL DEFAULT 0 CHECK(reserved_seconds >= 0)
                )""")
                db.execute("""CREATE TABLE run_transitions (
                    id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id),
                    from_state TEXT, to_state TEXT NOT NULL, reason TEXT, at REAL NOT NULL
                )""")
                version = 1
            elif version not in (1, SCHEMA_VERSION):
                raise SchemaVersionError(f"Database schema {version} is unsupported")
            else:
                expected = {"metadata", "runs", "daily_budget", "run_transitions"}
                actual = {
                    r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                if not expected <= actual:
                    raise SchemaVersionError(
                        "Database schema is incomplete; restore or explicitly migrate it"
                    )
            if version == 1:
                # Known v1 -> v2 additive migration, in the same transaction.
                # Old snapshots, counters and lifecycle histories are untouched.
                db.execute("""CREATE TABLE experiments (
                    experiment_id TEXT PRIMARY KEY, request_id TEXT NOT NULL UNIQUE,
                    manifest_json TEXT NOT NULL, manifest_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                )""")
                db.execute(
                    "ALTER TABLE runs ADD COLUMN experiment_id TEXT REFERENCES experiments(experiment_id)"
                )
                db.execute("ALTER TABLE runs ADD COLUMN role TEXT NOT NULL DEFAULT 'model'")
                db.execute(
                    "ALTER TABLE runs ADD COLUMN model_transitions INTEGER NOT NULL DEFAULT 0 CHECK(model_transitions >= 0)"
                )
                db.execute("CREATE INDEX runs_experiment ON runs(experiment_id)")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            columns = {r[1] for r in db.execute("PRAGMA table_info(runs)")}
            if (
                not {"experiment_id", "role", "model_transitions"} <= columns
                or not db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='experiments'"
                ).fetchone()
            ):
                raise SchemaVersionError("Database experiment schema is incomplete")

    def _effective_now(self, db: sqlite3.Connection) -> float:
        instant = self._now()
        if (
            not isinstance(instant, datetime)
            or instant.tzinfo is None
            or instant.utcoffset() is None
        ):
            raise LifecycleError("Clock must return a timezone-aware datetime")
        current = instant.timestamp()
        previous = db.execute("SELECT value FROM metadata WHERE key='clock_high_water'").fetchone()
        effective = max(current, float(previous[0])) if previous else current
        db.execute(
            "INSERT INTO metadata(key,value) VALUES('clock_high_water',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(effective),),
        )
        return effective

    @staticmethod
    def _row(db: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown run: {run_id}")
        return row

    @staticmethod
    def _day(db: sqlite3.Connection, date: str, limit: float) -> sqlite3.Row:
        # Admission/reservation may tighten a day's shared cap. Queries must
        # use _daily_capacity instead: historical runs cannot set today's cap.
        db.execute(
            "INSERT INTO daily_budget(local_date,limit_seconds) VALUES(?,?) ON CONFLICT(local_date) DO UPDATE SET limit_seconds=MIN(limit_seconds,excluded.limit_seconds)",
            (date, limit),
        )
        return db.execute("SELECT * FROM daily_budget WHERE local_date=?", (date,)).fetchone()

    @staticmethod
    def _daily_capacity(db: sqlite3.Connection, date: str, run_limit: float) -> tuple[float, float]:
        """Read the capacity this run could use, without changing project policy."""
        day = db.execute(
            "SELECT limit_seconds,reserved_seconds FROM daily_budget WHERE local_date=?",
            (date,),
        ).fetchone()
        if day is None:
            return run_limit, 0.0
        return min(run_limit, day["limit_seconds"]), day["reserved_seconds"]

    def _remaining(
        self, db: sqlite3.Connection, row: sqlite3.Row, instant: float
    ) -> dict[str, Any]:
        budget = _budget(json.loads(row["config_json"]))
        date = datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"])).date().isoformat()
        daily_limit, daily_reserved = self._daily_capacity(
            db, date, budget["max_daily_active_seconds"]
        )
        return {
            "environment_steps": max(0, budget["max_environment_steps"] - row["environment_steps"]),
            "optimizer_steps": max(0, budget["max_optimizer_steps"] - row["optimizer_steps"]),
            "model_transitions": max(0, budget["max_model_transitions"] - row["model_transitions"]),
            # Pre-work reservations can arrive faster than the wall clock
            # advances. They still share one finite session allocation.
            "wall_seconds": max(
                0.0,
                budget["max_wall_seconds"]
                - max(0.0, instant - row["created_at"], row["active_seconds"]),
            ),
            "daily_active_seconds": max(0.0, daily_limit - daily_reserved),
            "daily_date": date,
            "daily_limit_seconds": daily_limit,
        }

    def _record(self, db: sqlite3.Connection, row: sqlite3.Row, instant: float) -> RunRecord:
        return RunRecord(
            run_id=row["run_id"],
            request_id=row["request_id"],
            state=row["state"],
            resume_state=row["resume_state"],
            reason=row["reason"],
            config_snapshot=json.loads(row["config_json"]),
            config_hash=row["config_hash"],
            created_at=_iso(row["created_at"]),
            updated_at=_iso(row["updated_at"]),
            reserved_environment_steps=row["environment_steps"],
            reserved_optimizer_steps=row["optimizer_steps"],
            reserved_active_seconds=row["active_seconds"],
            wall_seconds=max(0.0, instant - row["created_at"]),
            remaining=self._remaining(db, row, instant),
            experiment_id=row["experiment_id"],
            role=row["role"],
            reserved_model_transitions=row["model_transitions"],
        )

    def _experiment_record(
        self, db: sqlite3.Connection, experiment_id: str, instant: float
    ) -> ExperimentRecord:
        row = db.execute(
            "SELECT * FROM experiments WHERE experiment_id=?", (experiment_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown experiment: {experiment_id}")
        manifest = json.loads(row["manifest_json"])
        budget = _experiment_budget(manifest)
        runs = db.execute("SELECT * FROM runs WHERE experiment_id=?", (experiment_id,)).fetchall()
        totals = {
            key: sum(r[key] for r in runs)
            for key in (
                "environment_steps",
                "optimizer_steps",
                "model_transitions",
                "active_seconds",
            )
        }
        calibration = sum(
            max(
                r["active_seconds"],
                max(
                    0,
                    (r["updated_at"] if r["state"] in TERMINAL_STATES else instant)
                    - r["created_at"],
                ),
            )
            for r in runs
            if r["role"] == "calibration"
        )
        count = sum(r["role"] == "model" for r in runs)
        remaining = {
            key: max(0, budget[f"max_{key}"] - totals[key])
            for key in ("environment_steps", "optimizer_steps", "model_transitions")
        }
        remaining.update(
            wall_seconds=max(
                0.0,
                budget["max_wall_seconds"]
                - max(0.0, instant - row["created_at"], totals["active_seconds"]),
            ),
            calibration_seconds=max(0.0, budget["max_calibration_seconds"] - calibration),
            model_runs=max(0, budget["max_model_runs"] - count),
        )
        return ExperimentRecord(
            experiment_id,
            row["request_id"],
            manifest,
            row["manifest_hash"],
            _iso(row["created_at"]),
            count,
            totals["environment_steps"],
            totals["optimizer_steps"],
            totals["model_transitions"],
            totals["active_seconds"],
            remaining,
        )

    def create_experiment(
        self, manifest: dict[str, Any], request_id: str, experiment_id: str | None = None
    ) -> ExperimentRecord:
        """Register an immutable experiment; creation starts its wall clock.

        Registration is explicit. Workers must never auto-create a replacement
        experiment on exhaustion. Pure configuration inspection uses no ledger.
        """
        if not isinstance(manifest, dict):
            raise LifecycleError("manifest must be an object")
        if not isinstance(request_id, str) or not request_id.strip():
            raise LifecycleError("request_id must be nonempty")
        if experiment_id is not None and (
            not isinstance(experiment_id, str) or not experiment_id.strip()
        ):
            raise LifecycleError("experiment_id must be nonempty")
        _experiment_budget(manifest)
        budget = _budget(manifest)
        try:
            payload = json.dumps(
                manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
        except (TypeError, ValueError) as exc:
            raise LifecycleError("manifest must be finite JSON data") from exc
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self._transaction() as db:
            instant = self._effective_now(db)
            self._fix_timezone(db, budget["timezone"])
            previous = db.execute(
                "SELECT * FROM experiments WHERE request_id=?", (request_id,)
            ).fetchone()
            if previous:
                if previous["manifest_hash"] != digest or (
                    experiment_id is not None and experiment_id != previous["experiment_id"]
                ):
                    raise LifecycleError(
                        "experiment request_id was already used for a different payload or ID"
                    )
                return self._experiment_record(db, previous["experiment_id"], instant)
            identity = experiment_id or uuid4().hex
            try:
                db.execute(
                    "INSERT INTO experiments VALUES(?,?,?,?,?)",
                    (identity, request_id, payload, digest, instant),
                )
            except sqlite3.IntegrityError as exc:
                raise LifecycleError(f"experiment_id already exists: {identity}") from exc
            return self._experiment_record(db, identity, instant)

    def get_experiment(self, experiment_id: str) -> ExperimentRecord:
        with self._transaction() as db:
            return self._experiment_record(db, experiment_id, self._effective_now(db))

    @staticmethod
    def _fix_timezone(db: sqlite3.Connection, zone: str) -> None:
        fixed_zone = db.execute(
            "SELECT value FROM metadata WHERE key='project_timezone'"
        ).fetchone()
        if fixed_zone and fixed_zone[0] != zone:
            raise LifecycleError("Project timezone cannot change between runs or experiments")
        db.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES('project_timezone',?)", (zone,)
        )

    def create_run(
        self,
        config_snapshot: dict[str, Any],
        request_id: str,
        run_id: str | None = None,
        *,
        experiment_id: str | None = None,
        role: str = "model",
    ) -> RunRecord:
        """Admit one sequential run inside an experiment's immutable limits.

        Calibration can update weights only before the first model run. Auxiliary
        runs may collect or evaluate, but cannot reserve optimizer updates. Every
        role holds the same single experiment slot until it becomes terminal.
        These are ledger rules; workers must still reserve before dispatch.
        """
        if not isinstance(config_snapshot, dict):
            raise LifecycleError("config_snapshot must be an object")
        if not isinstance(request_id, str) or not request_id.strip():
            raise LifecycleError("request_id must be nonempty")
        if run_id is not None and (not isinstance(run_id, str) or not run_id.strip()):
            raise LifecycleError("run_id must be nonempty")
        try:
            payload = json.dumps(
                config_snapshot,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise LifecycleError("config_snapshot must be finite JSON data") from exc
        budget = _budget(config_snapshot)
        if role not in {"model", "calibration", "auxiliary"}:
            raise LifecycleError("unsupported experiment run role")
        if experiment_id is None and (role != "model" or "experiment_budget" in config_snapshot):
            raise LifecycleError("experiment configuration requires experiment_id")
        digest = hashlib.sha256(payload.encode()).hexdigest()
        rejection: BudgetExceeded | None = None
        record: RunRecord | None = None
        with self._transaction() as db:
            instant = self._effective_now(db)
            previous = db.execute("SELECT * FROM runs WHERE request_id=?", (request_id,)).fetchone()
            if previous is not None:
                if (
                    previous["config_hash"] != digest
                    or previous["experiment_id"] != experiment_id
                    or previous["role"] != role
                    or (run_id is not None and run_id != previous["run_id"])
                ):
                    raise LifecycleError(
                        "request_id was already used for a different payload or run_id"
                    )
                return self._record(db, previous, instant)
            if experiment_id is not None:
                experiment = self._experiment_record(db, experiment_id, instant)
                ceiling = _budget(experiment.manifest)
                if (
                    any(budget[key] > ceiling[key] for key in ceiling if key != "timezone")
                    or budget["timezone"] != ceiling["timezone"]
                ):
                    raise LifecycleError("run budget exceeds experiment run limits")
                for key in (
                    "environment_steps",
                    "optimizer_steps",
                    "model_transitions",
                    "wall_seconds",
                ):
                    if experiment.remaining[key] <= 0:
                        rejection = BudgetExceeded(f"experiment_{key}_budget", experiment.remaining)
                        break
                if role == "calibration" and experiment.remaining["calibration_seconds"] <= 0:
                    rejection = rejection or BudgetExceeded(
                        "experiment_calibration_budget", experiment.remaining
                    )
                if role == "model" and experiment.remaining["model_runs"] <= 0:
                    rejection = rejection or BudgetExceeded(
                        "experiment_model_run_budget", experiment.remaining
                    )
                if rejection is None:
                    if role == "calibration" and experiment.model_run_count:
                        raise LifecycleError("calibration must precede the first model run")
                    if db.execute(
                        "SELECT 1 FROM runs WHERE experiment_id=? AND state NOT IN ('completed','failed','stopped')",
                        (experiment_id,),
                    ).fetchone():
                        raise LifecycleError(
                            "experiment runs must be sequential; finish or stop the existing run"
                        )
            if rejection is None:
                self._fix_timezone(db, budget["timezone"])
                identity = run_id or uuid4().hex
                try:
                    db.execute(
                        "INSERT INTO runs(run_id,request_id,state,config_json,config_hash,created_at,updated_at,experiment_id,role) VALUES(?,?,'created',?,?,?,?,?,?)",
                        (
                            identity,
                            request_id,
                            payload,
                            digest,
                            instant,
                            instant,
                            experiment_id,
                            role,
                        ),
                    )
                except sqlite3.IntegrityError as exc:
                    raise LifecycleError(f"run_id already exists: {identity}") from exc
                db.execute(
                    "INSERT INTO run_transitions(run_id,from_state,to_state,at) VALUES(?,NULL,'created',?)",
                    (identity, instant),
                )
                date = (
                    datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"])).date().isoformat()
                )
                self._day(db, date, budget["max_daily_active_seconds"])
                record = self._record(db, self._row(db, identity), instant)
        # Keep the observed clock high-water even on budget denial, as consume
        # does. A later clock rollback cannot make this package affordable again.
        if rejection is not None:
            raise rejection
        assert record is not None
        return record

    def get_run(self, run_id: str) -> RunRecord:
        with self._transaction() as db:
            instant = self._effective_now(db)
            return self._record(db, self._row(db, run_id), instant)

    def list_runs(self) -> list[RunRecord]:
        with self._transaction() as db:
            instant = self._effective_now(db)
            return [
                self._record(db, row, instant)
                for row in db.execute("SELECT * FROM runs ORDER BY created_at,run_id").fetchall()
            ]

    @staticmethod
    def _allocations(instant: float, seconds: float, zone: str) -> list[tuple[str, float]]:
        allocations: list[tuple[str, float]] = []
        end = instant + seconds
        cursor = instant
        tz = ZoneInfo(zone)
        while cursor < end:
            date = datetime.fromtimestamp(cursor, tz).date()
            midnight = datetime.combine(date + timedelta(days=1), time.min, tz).timestamp()
            next_cursor = min(midnight, end)
            allocations.append((date.isoformat(), next_cursor - cursor))
            cursor = next_cursor
        return allocations

    def _check(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        instant: float,
        environment_steps: int,
        optimizer_steps: int,
        active_seconds: float,
        model_transitions: int = 0,
    ) -> BudgetStatus:
        remaining = self._remaining(db, row, instant)
        if row["experiment_id"] is not None and row["role"] == "auxiliary" and optimizer_steps:
            return BudgetStatus(False, "auxiliary_optimizer_updates_forbidden", remaining)
        checks = (
            ("environment_steps", environment_steps, "environment_step_budget"),
            ("optimizer_steps", optimizer_steps, "optimizer_step_budget"),
            ("wall_seconds", active_seconds, "wall_time_budget"),
            ("daily_active_seconds", 0, "daily_active_time_budget"),
        )
        for name, amount, reason in checks:
            if remaining[name] <= 0 or amount > remaining[name]:
                return BudgetStatus(False, reason, remaining)
        budget = _budget(json.loads(row["config_json"]))
        if model_transitions > remaining["model_transitions"] or (
            budget["max_model_transitions"] > 0 and remaining["model_transitions"] <= 0
        ):
            return BudgetStatus(False, "model_transition_budget", remaining)
        if row["experiment_id"] is not None:
            experiment = self._experiment_record(db, row["experiment_id"], instant)
            # Expose both levels; a full run allowance cannot hide an exhausted package.
            remaining["experiment"] = experiment.remaining
            amounts = {
                "environment_steps": environment_steps,
                "optimizer_steps": optimizer_steps,
                "model_transitions": model_transitions,
                "wall_seconds": active_seconds,
            }
            if row["role"] == "calibration":
                amounts["calibration_seconds"] = active_seconds
            for name, amount in amounts.items():
                if experiment.remaining[name] <= 0 or amount > experiment.remaining[name]:
                    return BudgetStatus(False, f"experiment_{name}_budget", remaining)
        for date, amount in self._allocations(instant, active_seconds, budget["timezone"]):
            limit, reserved = self._daily_capacity(db, date, budget["max_daily_active_seconds"])
            if amount > max(0.0, limit - reserved):
                return BudgetStatus(False, "daily_active_time_budget", remaining)
        return BudgetStatus(True, None, remaining)

    @staticmethod
    def _validate_units(
        environment_steps: int,
        optimizer_steps: int,
        active_seconds: float,
        model_transitions: int = 0,
    ) -> None:
        _nonnegative(environment_steps, "environment_steps", integer=True)
        _nonnegative(optimizer_steps, "optimizer_steps", integer=True)
        _nonnegative(active_seconds, "active_seconds")
        _nonnegative(model_transitions, "model_transitions", integer=True)

    def check_budget(
        self,
        run_id: str,
        *,
        environment_steps: int = 0,
        optimizer_steps: int = 0,
        active_seconds: float = 0,
        model_transitions: int = 0,
    ) -> BudgetStatus:
        """Inspect quota, committing the clock high-water even when denied."""
        self._validate_units(environment_steps, optimizer_steps, active_seconds, model_transitions)
        with self._transaction() as db:
            instant = self._effective_now(db)
            return self._check(
                db,
                self._row(db, run_id),
                instant,
                environment_steps,
                optimizer_steps,
                active_seconds,
                model_transitions,
            )

    def assert_can_work(
        self,
        run_id: str,
        *,
        environment_steps: int = 0,
        optimizer_steps: int = 0,
        active_seconds: float = 0,
        model_transitions: int = 0,
    ) -> BudgetStatus:
        """A preflight only; consume still atomically checks/reserves the units."""
        self._validate_units(environment_steps, optimizer_steps, active_seconds, model_transitions)
        with self._transaction() as db:
            instant = self._effective_now(db)
            row = self._row(db, run_id)
            if row["state"] not in WORK_STATES:
                raise LifecycleError(f"Cannot work while run is {row['state']}")
            result = self._check(
                db,
                row,
                instant,
                environment_steps,
                optimizer_steps,
                active_seconds,
                model_transitions,
            )
        if not result.allowed:
            raise BudgetExceeded(result.reason or "unknown", result.remaining)
        return result

    def consume(
        self,
        run_id: str,
        *,
        environment_steps: int = 0,
        optimizer_steps: int = 0,
        active_seconds: float = 0,
        model_transitions: int = 0,
    ) -> RunRecord:
        """Atomically reserve a unit before dispatch, never after performing it."""
        self._validate_units(environment_steps, optimizer_steps, active_seconds, model_transitions)
        record: RunRecord | None = None
        with self._transaction() as db:
            instant = self._effective_now(db)
            row = self._row(db, run_id)
            if row["state"] not in WORK_STATES:
                raise LifecycleError(f"Cannot reserve work while run is {row['state']}")
            result = self._check(
                db,
                row,
                instant,
                environment_steps,
                optimizer_steps,
                active_seconds,
                model_transitions,
            )
            if result.allowed:
                budget = _budget(json.loads(row["config_json"]))
                date = (
                    datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"])).date().isoformat()
                )
                self._day(db, date, budget["max_daily_active_seconds"])
                for date, amount in self._allocations(instant, active_seconds, budget["timezone"]):
                    self._day(db, date, budget["max_daily_active_seconds"])
                    db.execute(
                        "UPDATE daily_budget SET reserved_seconds=reserved_seconds+? WHERE local_date=?",
                        (amount, date),
                    )
                db.execute(
                    "UPDATE runs SET environment_steps=environment_steps+?,optimizer_steps=optimizer_steps+?,active_seconds=active_seconds+?,model_transitions=model_transitions+?,updated_at=? WHERE run_id=?",
                    (
                        environment_steps,
                        optimizer_steps,
                        active_seconds,
                        model_transitions,
                        instant,
                        run_id,
                    ),
                )
                record = self._record(db, self._row(db, run_id), instant)
        if not result.allowed:
            raise BudgetExceeded(result.reason or "unknown", result.remaining)
        assert record is not None
        return record

    def transition(self, run_id: str, target_state: str, reason: str | None = None) -> RunRecord:
        if target_state not in TRANSITIONS:
            raise LifecycleError(f"Unknown state: {target_state}")
        if reason is not None and not isinstance(reason, str):
            raise LifecycleError("reason must be text or null")
        result: BudgetStatus | None = None
        record: RunRecord | None = None
        with self._transaction() as db:
            instant = self._effective_now(db)
            row = self._row(db, run_id)
            source = row["state"]
            if target_state not in TRANSITIONS[source]:
                raise LifecycleError(f"Invalid transition: {source} -> {target_state}")
            resume_state = row["resume_state"]
            if source == "paused":
                if target_state in RECOVERABLE_STATES:
                    if target_state != resume_state:
                        raise LifecycleError(
                            f"Resume must return to {resume_state}, not {target_state}"
                        )
                    result = self._check(db, row, instant, 0, 0, 0)
                    resume_state = None
            if target_state == "pausing":
                resume_state = source
            if row["experiment_id"] is not None and target_state in RECOVERABLE_STATES:
                result = self._check(db, row, instant, 0, 0, 0)
            if result is None or result.allowed:
                if target_state in RECOVERABLE_STATES:
                    budget = _budget(json.loads(row["config_json"]))
                    date = (
                        datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"]))
                        .date()
                        .isoformat()
                    )
                    self._day(db, date, budget["max_daily_active_seconds"])
                db.execute(
                    "UPDATE runs SET state=?,resume_state=?,reason=?,updated_at=? WHERE run_id=?",
                    (target_state, resume_state, reason, instant, run_id),
                )
                db.execute(
                    "INSERT INTO run_transitions(run_id,from_state,to_state,reason,at) VALUES(?,?,?,?,?)",
                    (run_id, source, target_state, reason, instant),
                )
                record = self._record(db, self._row(db, run_id), instant)
        if result is not None and not result.allowed:
            raise BudgetExceeded(result.reason or "unknown", result.remaining)
        assert record is not None
        return record

    def resume(self, run_id: str) -> RunRecord:
        """Explicit human/supervisor request; paused runs never auto-resume."""
        record = self.get_run(run_id)
        if record.state != "paused" or record.resume_state is None:
            raise LifecycleError(f"Cannot resume {record.state}")
        return self.transition(run_id, record.resume_state, reason="explicit_resume")

    def recover_interrupted_runs(self) -> list[RunRecord]:
        """Call only at exclusive supervisor startup, not per DB connection."""
        recovered: list[RunRecord] = []
        with self._transaction() as db:
            instant = self._effective_now(db)
            rows = db.execute(
                "SELECT * FROM runs WHERE state IN ('initializing','collecting','training','validating','pausing','stopping')"
            ).fetchall()
            for row in rows:
                source = row["state"]
                target = "stopped" if source == "stopping" else "paused"
                resume = (
                    row["resume_state"]
                    if source == "pausing"
                    else (source if target == "paused" else None)
                )
                db.execute(
                    "UPDATE runs SET state=?,resume_state=?,reason='process_restart',updated_at=? WHERE run_id=?",
                    (target, resume, instant, row["run_id"]),
                )
                db.execute(
                    "INSERT INTO run_transitions(run_id,from_state,to_state,reason,at) VALUES(?,?,?,'process_restart',?)",
                    (row["run_id"], source, target, instant),
                )
                recovered.append(self._record(db, self._row(db, row["run_id"]), instant))
        return recovered
