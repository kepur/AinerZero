"""Worker execution and central RunStore ledger coordination for S2 Phase 1.

All executions are preflight-guarded, recorded in the central SQLite3 ledger,
and protected by the shared worker lock.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Generator, Mapping, Sequence
from uuid import uuid4

from ainerzero.runtime.lifecycle import (
    BudgetExceeded,
    LifecycleError,
    RunRecord,
    RunStore,
    TERMINAL_STATES,
)
from ainerzero.v9.experiments.s2 import spec

EXPERIMENT_ID = spec.EXPERIMENT_ID
LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (
    EXPERIMENT_ID,
    "s2-phase1-20261106-r1",
    "s2-phase1-20261106-r2",
)
TIMEZONE = "Asia/Shanghai"
CALENDAR_WINDOW_SECONDS = float(spec.CALENDAR_WINDOW_SECONDS)
PHASE_TOTAL_WALL_CEILING_SECONDS = float(spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS)


def get_experiment_manifest() -> dict[str, Any]:
    """Construct the immutable experiment manifest for RunStore registration.

    Calendar window (72 h = 259,200 s) is enforced at the experiment budget level,
    while actual compute wall-clock ceiling (10 h = 36,000 s) is aggregated across
    runs in the ledger lineage.
    """
    wall_ceiling = PHASE_TOTAL_WALL_CEILING_SECONDS
    calendar_window = CALENDAR_WINDOW_SECONDS

    return {
        "spec": spec.SPEC_NAME,
        "experiment_id": EXPERIMENT_ID,
        "task_id": spec.TASK_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Run-level default budget limits
        "budget": {
            "max_environment_steps": 10_000_000,
            "max_optimizer_steps": 1_000_000,
            "max_wall_seconds": wall_ceiling,
            "max_daily_active_seconds": wall_ceiling,
            "max_model_transitions": 0,
            "timezone": TIMEZONE,
        },
        # Experiment-level calendar window budget (E1 Plan A separation)
        "experiment_budget": {
            "max_model_runs": 200,
            "max_environment_steps": 20_000_000,
            "max_optimizer_steps": 10_000_000,
            "max_model_transitions": 1,
            "max_wall_seconds": calendar_window,
            "max_calibration_seconds": 3600.0,
        },
        "tags": ["v9", "s2", "phase1", "neurogeometry", "hjepa"],
    }


@contextmanager
def ledger_read_snapshot(ledger_path: Path | str) -> Generator[RunStore | None, None, None]:
    """Provide a read-only snapshot connection to the ledger if it exists.

    Copies the database, WAL, and SHM files to an isolated system temporary directory
    before opening RunStore on the replica. This ensures zero disk modifications
    (mtime, size, inode, or shm updates) to the real ledger, and leaves no temporary
    files in the real ledger directory.
    """
    import shutil
    import tempfile

    p = Path(ledger_path).resolve()
    if not p.is_file():
        yield None
        return

    tmp_dir = Path(tempfile.mkdtemp(prefix="s2_ledger_read_"))
    temp_db = tmp_dir / p.name
    wal_path = p.parent / f"{p.name}-wal"
    shm_path = p.parent / f"{p.name}-shm"
    temp_wal = tmp_dir / f"{p.name}-wal"
    temp_shm = tmp_dir / f"{p.name}-shm"

    try:
        shutil.copy2(p, temp_db)
        if wal_path.is_file():
            shutil.copy2(wal_path, temp_wal)
        if shm_path.is_file():
            shutil.copy2(shm_path, temp_shm)

        store = RunStore(temp_db)
        try:
            yield store
        finally:
            store.close()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def check_cell_already_completed(
    ledger_path: Path | str,
    mode: str,
    arm: str | None,
    seed: int | None,
    experiment_ids: Sequence[str] = LEDGER_EXPERIMENT_IDS,
) -> bool:
    """Check if the given (mode, arm, seed) has already completed in the ledger."""
    with ledger_read_snapshot(ledger_path) as store:
        if store is None:
            return False
        placeholders = ", ".join("?" for _ in experiment_ids)
        cursor = store._conn.execute(
            f"SELECT config_json, state FROM runs WHERE experiment_id IN ({placeholders})",
            list(experiment_ids),
        )
        for row in cursor.fetchall():
            if row["state"] != "completed":
                continue
            try:
                cfg = json.loads(row["config_json"])
            except Exception:
                continue
            if cfg.get("mode") != mode:
                continue
            if mode == "dev-eval":
                # dev-eval allows up to 2 calls governed by dev_ledger.json (§5, D4)
                continue
            if mode == "generate-data":
                cell_part = cfg.get("partition") or cfg.get("arm")
                if cell_part == arm:
                    return True
                continue
            if cfg.get("arm") == arm:
                if seed is None or cfg.get("seed") == seed:
                    return True
    return False


class S2Ledger:
    """Central RunStore ledger interface for S2 Phase 1."""

    def __init__(self, db_path: Path | str, clock: Callable[[], float] | None = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or time.time
        now_fn = lambda: datetime.fromtimestamp(self.clock(), timezone.utc)
        self.store = RunStore(self.db_path, now=now_fn)

    def close(self) -> None:
        self.store.close()

    def ensure_experiment(self, experiment_id: str = EXPERIMENT_ID) -> Any:
        manifest = get_experiment_manifest()
        manifest["experiment_id"] = experiment_id
        request_id = f"init:{experiment_id}"
        try:
            return self.store.get_experiment(experiment_id)
        except KeyError:
            return self.store.create_experiment(manifest, request_id, experiment_id)

    def open_run(
        self,
        mode: str,
        arm: str | None,
        seed: int | None,
        cell_wall_budget: float,
        *,
        experiment_id: str = EXPERIMENT_ID,
        runner_name: str | None = None,
        snapshot_extra: Mapping[str, Any] | None = None,
    ) -> str:
        self.ensure_experiment(experiment_id)
        run_id = uuid4().hex
        request_id = f"{experiment_id}:{mode}:{arm}:{seed}:{run_id[:8]}"
        snapshot: dict[str, Any] = {
            "spec": spec.SPEC_NAME,
            "mode": mode,
            "arm": arm,
            "seed": seed,
            "runner_name": runner_name or "stub",
            "cell_wall_budget_seconds": cell_wall_budget,
            "budget": {
                "max_environment_steps": 1_000_000,
                "max_optimizer_steps": 1_000_000,
                "max_wall_seconds": cell_wall_budget,
                "max_daily_active_seconds": PHASE_TOTAL_WALL_CEILING_SECONDS,
                "max_model_transitions": 0,
                "timezone": TIMEZONE,
            },
        }
        if snapshot_extra:
            snapshot.update(dict(snapshot_extra))

        self.store.create_run(
            snapshot,
            request_id,
            run_id,
            experiment_id=experiment_id,
            role="model",
        )
        self.store.transition(run_id, "initializing", reason=f"mode={mode}")
        return run_id

    def begin_run(self, run_id: str, state: str = "training") -> None:
        self.store.transition(run_id, state, reason="execution started")

    def complete_run(
        self,
        run_id: str,
        *,
        active_seconds: float = 0.0,
        optimizer_steps: int = 0,
        metrics: Mapping[str, Any] | None = None,
    ) -> None:
        if active_seconds > 0 or optimizer_steps > 0:
            self.store.consume(
                run_id,
                active_seconds=float(active_seconds),
                optimizer_steps=int(optimizer_steps),
            )
        reason_str = "execution completed"
        if metrics is not None:
            self.record_metrics(run_id, metrics)
            try:
                reason_str = json.dumps(dict(metrics))
            except Exception:
                reason_str = "execution completed"
        self.store.transition(run_id, "completed", reason=reason_str)

    def record_metrics(self, run_id: str, metrics: Mapping[str, Any]) -> None:
        """Record run metrics into the ledger metadata table (run:<run_id>:metrics)."""
        val = json.dumps(dict(metrics))
        with self.store._transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (f"run:{run_id}:metrics", val),
            )

    def get_run_metrics(self, run_id: str) -> dict[str, Any] | None:
        """Retrieve metrics recorded for a run from metadata or reason fallback."""
        return get_run_metrics(self.store, run_id)

    def fail_run(self, run_id: str, reason: str = "execution failed") -> None:
        self.store.transition(run_id, "failed", reason=reason)

    def stop_run(self, run_id: str, reason: str = "execution stopped") -> None:
        self.store.transition(run_id, "stopped", reason=reason)


def get_run_metrics(store: RunStore, run_id: str) -> dict[str, Any] | None:
    """Retrieve run metrics from RunStore metadata or reason column."""
    with store._transaction() as db:
        row = db.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (f"run:{run_id}:metrics",),
        ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                pass
        row = db.execute("SELECT reason FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row and row[0]:
            try:
                d = json.loads(row[0])
                if isinstance(d, dict):
                    return d
            except Exception:
                pass
    return None


def default_stub_runner(
    ledger: S2Ledger,
    run_id: str,
    mode: str,
    arm: str | None,
    seed: int | None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Default stub runner: refuses real execution since real training/eval is not yet wired."""
    raise RuntimeError(
        f"Default runner stub: mode {mode!r} execution is refused; "
        f"real training and evaluation will be wired in subsequent tasks."
    )


def execute_work_cell(
    ledger: S2Ledger,
    mode: str,
    arm: str | None,
    seed: int | None,
    cell_wall_budget: float,
    *,
    experiment_id: str = EXPERIMENT_ID,
    clock: Callable[[], float] | None = None,
    runner: Callable[..., Any] | None = None,
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    """Execute one work cell inside the ledger lifecycle."""
    run_id = ledger.open_run(
        mode=mode,
        arm=arm,
        seed=seed,
        cell_wall_budget=cell_wall_budget,
        experiment_id=experiment_id,
        runner_name=getattr(runner, "__name__", "stub" if runner is None else "custom"),
    )

    actual_runner = runner or default_stub_runner
    active_state = "collecting" if mode == "generate-data" else ("validating" if "eval" in mode or mode == "plan-select" else "training")
    try:
        ledger.begin_run(run_id, state=active_state)
        result = actual_runner(
            ledger=ledger,
            run_id=run_id,
            mode=mode,
            arm=arm,
            seed=seed,
            cell_wall_budget=cell_wall_budget,
            experiment_id=experiment_id,
            clock=clock,
            output_root=output_root,
        )
        # If the runner returned a result and the run has not been transitioned to a terminal state:
        run_record = ledger.store.get_run(run_id)
        if run_record.state not in TERMINAL_STATES:
            if isinstance(result, dict) and result.get("passed") is False:
                fail_reason = result.get("failure_reason") or "smoke precondition failed"
                if isinstance(result, dict):
                    ledger.record_metrics(run_id, result)
                ledger.fail_run(run_id, reason=str(fail_reason))
            else:
                active_sec = float(result.get("active_seconds", result.get("elapsed_seconds", 0.0))) if isinstance(result, dict) else 0.0
                opt_steps = int(result.get("optimizer_steps", 0)) if isinstance(result, dict) else 0
                ledger.complete_run(
                    run_id,
                    active_seconds=active_sec,
                    optimizer_steps=opt_steps,
                    metrics=result if isinstance(result, dict) else None,
                )
        return result
    except Exception as exc:
        try:
            run_record = ledger.store.get_run(run_id)
            if run_record.state not in TERMINAL_STATES:
                ledger.fail_run(run_id, reason=str(exc))
        except Exception:
            pass
        raise
