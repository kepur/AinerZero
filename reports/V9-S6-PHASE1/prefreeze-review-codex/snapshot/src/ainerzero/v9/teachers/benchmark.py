"""Guarded execution, inspection, and budget accounting for T4 teacher benchmarks.

Integrates:
- Central RunStore ledger pre-work reservations
- CLI worker_lock cross-process mutual exclusion
- RESEARCH_LOG approval gate (R20261016-T4)
- Resource gate (process RSS <= 32 GiB)
- Cumulative (1800s) and per-run (600s) conservative budget caps
- Zero side-effect inspection mode
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import psutil

from ainerzero.cli import WorkerLockBusy, worker_lock
from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore

from .benchmark_protocol import (
    APPROVED_TEACHER_MODELS,
    T4_APPROVAL_KEYWORD,
    T4_APPROVAL_SECTION,
    T4_APPROVAL_TARGET,
    T4_MAX_CUMULATIVE_WALL_SECONDS,
    T4_MAX_PER_RUN_WALL_SECONDS,
    T4_MAX_PROCESS_RSS_GIB,
    T4_MAX_RESIDENT_MODELS,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkLockBusy,
    BenchmarkResourceRefused,
    BenchmarkRunSpec,
    TeacherModelSpec,
)


def verify_research_log_approval(research_log_path: Path) -> dict[str, Any]:
    """Verify that RESEARCH_LOG.md contains the approved R20261016-T4 section and keywords."""
    path = Path(research_log_path)
    if not path.is_file():
        raise BenchmarkApprovalRefused(f"RESEARCH_LOG file not found: {path}")

    try:
        content = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise BenchmarkApprovalRefused(f"Failed to read RESEARCH_LOG {path}: {exc}") from exc

    # Parse sections
    lines = content.splitlines()
    in_target_section = False
    section_lines: list[str] = []

    for line in lines:
        if line.startswith("## "):
            if T4_APPROVAL_SECTION in line:
                in_target_section = True
                section_lines.append(line)
                continue
            elif in_target_section:
                # Reached next section
                break
        if in_target_section:
            section_lines.append(line)

    if not in_target_section or not section_lines:
        raise BenchmarkApprovalRefused(
            f"Required approval section '## {T4_APPROVAL_SECTION}' not found in {path}"
        )

    section_text = "\n".join(section_lines)
    if T4_APPROVAL_KEYWORD not in section_text:
        raise BenchmarkApprovalRefused(
            f"Approval keyword '{T4_APPROVAL_KEYWORD}' missing in section {T4_APPROVAL_SECTION}"
        )

    if T4_APPROVAL_TARGET not in section_text and "T4" not in section_text:
        raise BenchmarkApprovalRefused(
            f"Approval target '{T4_APPROVAL_TARGET}' missing in section {T4_APPROVAL_SECTION}"
        )

    # Check for negative revocations
    if "撤销 T4" in section_text or "作废 T4" in section_text:
        raise BenchmarkApprovalRefused(f"Section {T4_APPROVAL_SECTION} indicates approval revocation")

    return {
        "status": "approved",
        "section": T4_APPROVAL_SECTION,
        "keyword": T4_APPROVAL_KEYWORD,
        "target": T4_APPROVAL_TARGET,
        "max_cumulative_wall_seconds": T4_MAX_CUMULATIVE_WALL_SECONDS,
        "max_per_run_wall_seconds": T4_MAX_PER_RUN_WALL_SECONDS,
        "max_resident_models": T4_MAX_RESIDENT_MODELS,
        "max_process_rss_gib": T4_MAX_PROCESS_RSS_GIB,
    }


def measure_process_rss_bytes() -> int:
    """Measure the current process RSS in bytes."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss


def check_resource_limits(max_rss_gib: float = T4_MAX_PROCESS_RSS_GIB) -> dict[str, Any]:
    """Check process memory against registered resource limits (process RSS <= 32 GiB)."""
    rss_bytes = measure_process_rss_bytes()
    rss_gib = rss_bytes / (1024**3)
    max_rss_bytes = int(max_rss_gib * (1024**3))

    if rss_bytes > max_rss_bytes:
        raise BenchmarkResourceRefused(
            f"Process RSS {rss_gib:.2f} GiB exceeds registered protection limit of {max_rss_gib:.2f} GiB",
            details={"rss_bytes": rss_bytes, "rss_gib": rss_gib, "max_rss_gib": max_rss_gib},
        )

    return {
        "status": "ok",
        "rss_bytes": rss_bytes,
        "rss_gib": round(rss_gib, 4),
        "max_rss_gib": max_rss_gib,
    }


def calculate_cumulative_reserved_seconds(store_path: Path) -> float:
    """Read the total cumulative reserved wall seconds from the RunStore ledger for T4.

    Strictly read-only: does not trigger RunStore initialization, schema migration, or writes.
    Fails closed on corrupt or abnormal database files.
    """
    path = Path(store_path)
    if not path.is_file():
        return 0.0

    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except Exception as exc:
        raise BenchmarkRefusalError(
            f"Failed to open RunStore ledger in read-only mode at {path}: {exc}"
        ) from exc

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'")
        if cursor.fetchone() is None:
            raise BenchmarkRefusalError(
                f"Damaged or uninitialized RunStore ledger: 'runs' table missing in {path}"
            )
        cursor.execute("SELECT config_json, active_seconds FROM runs")
        total = 0.0
        for config_json, active_seconds in cursor.fetchall():
            try:
                cfg = json.loads(config_json)
            except Exception as exc:
                raise BenchmarkRefusalError(
                    f"Corrupted config_json in RunStore ledger {path}: {exc}"
                ) from exc
            if cfg.get("task") != "ainerzero.V9.T6":
                total += float(active_seconds or 0.0)
        return total
    except BenchmarkRefusalError:
        raise
    except Exception as exc:
        raise BenchmarkRefusalError(
            f"Abnormal or corrupted RunStore ledger query on {path}: {exc}"
        ) from exc
    finally:
        conn.close()


def check_model_weights_manifest(
    model_spec: TeacherModelSpec,
    weights_root: Path,
    verify_content_sha: bool = True,
) -> dict[str, Any]:
    """Inspect model files against official T21/T22 manifest without loading weights."""
    model_dir = Path(weights_root) / model_spec.revision
    missing_files: list[str] = []
    corrupted_files: list[str] = []
    verified_files: list[str] = []
    total_found_bytes = 0

    for file_spec in model_spec.files:
        file_path = model_dir / file_spec.relative_path
        if not file_path.is_file():
            missing_files.append(file_spec.relative_path)
            continue

        actual_size = file_path.stat().st_size
        if actual_size != file_spec.bytes:
            corrupted_files.append(
                f"{file_spec.relative_path} (size mismatch: {actual_size} != {file_spec.bytes})"
            )
            continue

        total_found_bytes += actual_size

        if verify_content_sha:
            hasher = hashlib.sha256()
            with open(file_path, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    hasher.update(chunk)
            actual_sha = hasher.hexdigest()
            if actual_sha != file_spec.sha256:
                corrupted_files.append(
                    f"{file_spec.relative_path} (sha mismatch: {actual_sha} != {file_spec.sha256})"
                )
                continue

        verified_files.append(file_spec.relative_path)

    is_complete = not missing_files and not corrupted_files
    return {
        "model_id": model_spec.model_id,
        "repository": model_spec.repository,
        "revision": model_spec.revision,
        "license": model_spec.license,
        "complete": is_complete,
        "total_files": len(model_spec.files),
        "verified_files_count": len(verified_files),
        "missing_files": missing_files,
        "corrupted_files": corrupted_files,
        "total_bytes": model_spec.total_bytes,
        "found_bytes": total_found_bytes,
    }


def inspect_teacher_benchmark(spec: BenchmarkRunSpec) -> dict[str, Any]:
    """Zero side-effect inspection mode.

    Guarantees:
    - Never creates or acquires lock files.
    - Never creates or modifies SQLite databases.
    - Never imports MLX, CoreML, or model weights.
    - Measures read-only environment and verifies specifications.
    """
    # 1. Approval inspection (read-only)
    approval = verify_research_log_approval(spec.research_log_path)

    # 2. Resource check (read-only measurement)
    resources = check_resource_limits(T4_MAX_PROCESS_RSS_GIB)

    # 3. Model inspection
    models_to_check: list[str] = (
        list(APPROVED_TEACHER_MODELS.keys())
        if spec.model == "all"
        else [spec.model]
        if spec.model in APPROVED_TEACHER_MODELS
        else []
    )
    if not models_to_check and spec.model != "all":
        models_to_check = [spec.model]

    model_inspections: dict[str, Any] = {}
    for m in models_to_check:
        if m in APPROVED_TEACHER_MODELS:
            # For inspect, verify file presence and size; SHA can be checked if files exist
            model_inspections[m] = check_model_weights_manifest(
                APPROVED_TEACHER_MODELS[m],
                spec.weights_root,
                verify_content_sha=False,
            )
        else:
            model_inspections[m] = {
                "model_id": m,
                "complete": False,
                "error": f"Unknown or unapproved teacher model: {m}",
            }

    # 4. Store ledger inspection (read-only, no file creation)
    store_exists = spec.store_path.is_file()
    cumulative_reserved = (
        calculate_cumulative_reserved_seconds(spec.store_path) if store_exists else 0.0
    )
    remaining_cumulative = max(0.0, T4_MAX_CUMULATIVE_WALL_SECONDS - cumulative_reserved)

    # 5. Lock check (read-only check, does NOT create lock file)
    lock_exists = spec.lock_path.is_file()

    return {
        "mode": "inspect",
        "status": "inspected",
        "zero_side_effects_guaranteed": True,
        "approval": approval,
        "resources": resources,
        "budget": {
            "requested_per_run_seconds": spec.wall_budget_seconds,
            "max_per_run_limit_seconds": T4_MAX_PER_RUN_WALL_SECONDS,
            "cumulative_reserved_seconds": cumulative_reserved,
            "max_cumulative_limit_seconds": T4_MAX_CUMULATIVE_WALL_SECONDS,
            "remaining_cumulative_seconds": remaining_cumulative,
            "per_run_budget_admissible": spec.wall_budget_seconds <= T4_MAX_PER_RUN_WALL_SECONDS,
            "cumulative_budget_admissible": (
                cumulative_reserved + spec.wall_budget_seconds <= T4_MAX_CUMULATIVE_WALL_SECONDS
            ),
        },
        "models": model_inspections,
        "ledger": {
            "store_path": str(spec.store_path),
            "store_exists": store_exists,
        },
        "locks": {
            "lock_path": str(spec.lock_path),
            "lock_file_exists": lock_exists,
        },
    }


class TeacherBenchmarkAdapter(Protocol):
    """Protocol for teacher benchmark execution adapters."""

    def run_benchmark(self, spec: BenchmarkRunSpec) -> dict[str, Any]:
        ...


class RealTeacherBenchmarkAdapter:
    """Production teacher benchmark adapter (lazy loading, strict checks)."""

    def run_benchmark(self, spec: BenchmarkRunSpec) -> dict[str, Any]:
        # Verify model files strictly with SHA256 before any compute
        models = (
            list(APPROVED_TEACHER_MODELS.keys())
            if spec.model == "all"
            else [spec.model]
        )
        for m in models:
            if m not in APPROVED_TEACHER_MODELS:
                raise ValueError(f"Unapproved teacher model: {m}")
            manifest = check_model_weights_manifest(
                APPROVED_TEACHER_MODELS[m], spec.weights_root, verify_content_sha=True
            )
            if not manifest["complete"]:
                raise RuntimeError(
                    f"Model {m} weights verification failed: missing={manifest['missing_files']}, "
                    f"corrupted={manifest['corrupted_files']}"
                )

        # In CPU implementation stage (real_model_runs = 0), full execution is blocked
        # by coordinator until GPU gate is opened.
        return {
            "status": "completed",
            "models_verified": models,
            "real_model_runs": 0,
            "note": "Weights verified against official SHA256 manifest; GPU execution gated",
        }


def execute_guarded_benchmark(
    spec: BenchmarkRunSpec,
    adapter: TeacherBenchmarkAdapter | None = None,
) -> dict[str, Any]:
    """Execute a teacher benchmark run under all required guards.

    Execution sequence:
    1. Check RESEARCH_LOG approval line (R20261016-T4). Exit 3 on missing/invalid.
    2. Check per-run budget (<= 600.0s). Exit 5 on exceeded.
    3. Check pre-lock resource gate (RSS <= 32 GiB). Exit 2 on exceeded.
    4. Acquire CLI worker_lock. Exit 4 on lock contention.
    5. Check cumulative budget from RunStore (cumulative + requested <= 1800.0s). Exit 5 on exceeded.
    6. Register run and pre-reserve budget in central RunStore ledger.
    7. Supervise execution under adapter; re-check resource gate.
    8. Transition run to completed or failed with full evidence.
    """
    # Step 1: Approval Gate
    approval = verify_research_log_approval(spec.research_log_path)

    # Step 2: Per-run Budget Gate
    if spec.wall_budget_seconds <= 0.0:
        raise BenchmarkBudgetRefused("Requested wall budget must be positive")
    if spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:
        raise BenchmarkBudgetRefused(
            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
            f"per-run limit {T4_MAX_PER_RUN_WALL_SECONDS:.1f}s"
        )

    # Step 3: Pre-lock Resource Gate
    resource_pre = check_resource_limits(T4_MAX_PROCESS_RSS_GIB)

    # Step 4: CLI worker_lock acquisition
    try:
        with worker_lock(spec.lock_path):
            # Step 5: RunStore Central Ledger & Cumulative Budget Gate
            spec.store_path.parent.mkdir(parents=True, exist_ok=True)
            with RunStore(spec.store_path) as store:
                runs = store.list_runs()
                cumulative_reserved = sum(r.reserved_active_seconds for r in runs)
                if (
                    cumulative_reserved + spec.wall_budget_seconds
                    > T4_MAX_CUMULATIVE_WALL_SECONDS
                ):
                    raise BenchmarkBudgetRefused(
                        f"Cumulative wall budget exceeded: {cumulative_reserved:.1f}s reserved + "
                        f"{spec.wall_budget_seconds:.1f}s requested > {T4_MAX_CUMULATIVE_WALL_SECONDS:.1f}s limit",
                        details={
                            "cumulative_reserved": cumulative_reserved,
                            "requested": spec.wall_budget_seconds,
                            "limit": T4_MAX_CUMULATIVE_WALL_SECONDS,
                        },
                    )

                run_id = spec.run_id or uuid4().hex
                request_id = spec.request_id or f"t4-bench-{run_id}"

                config_snapshot = {
                    "task": "ainerzero.V9.T4",
                    "model": spec.model,
                    "budget": {
                        "max_wall_seconds": T4_MAX_CUMULATIVE_WALL_SECONDS,
                        "max_environment_steps": 1000,
                        "max_optimizer_steps": 1000,
                        "max_daily_active_seconds": T4_MAX_CUMULATIVE_WALL_SECONDS,
                        "max_model_transitions": 0,
                        "timezone": "UTC",
                    },
                }

                # Register run
                store.create_run(config_snapshot, request_id=request_id, run_id=run_id)
                store.transition(run_id, "initializing", reason="Pre-work initialization")
                store.transition(run_id, "validating", reason="Pre-work budget reservation")

                # Step 6: Atomic Pre-work Reservation in RunStore
                try:
                    store.consume(run_id, active_seconds=spec.wall_budget_seconds)
                except BudgetExceeded as exc:
                    store.transition(run_id, "failed", reason=f"BudgetExceeded: {exc}")
                    raise BenchmarkBudgetRefused(str(exc)) from exc

                # Step 7: Execution under adapter
                check_resource_limits(T4_MAX_PROCESS_RSS_GIB)

                start_time = time.time()
                actual_adapter = adapter or RealTeacherBenchmarkAdapter()
                execution_result: dict[str, Any] = {}
                try:
                    execution_result = actual_adapter.run_benchmark(spec)
                except Exception as exc:
                    store.transition(run_id, "failed", reason=f"Adapter error: {exc}")
                    raise

                elapsed = time.time() - start_time
                store.transition(run_id, "completed", reason="Benchmark run completed successfully")

                return {
                    "mode": "run",
                    "status": "completed",
                    "run_id": run_id,
                    "request_id": request_id,
                    "elapsed_seconds": round(elapsed, 4),
                    "reserved_seconds": spec.wall_budget_seconds,
                    "cumulative_reserved_seconds": cumulative_reserved + spec.wall_budget_seconds,
                    "approval": approval,
                    "resources_pre": resource_pre,
                    "result": execution_result,
                }
    except WorkerLockBusy as exc:
        raise BenchmarkLockBusy("Worker lock is currently held by another worker") from exc
    except BlockingIOError as exc:
        raise BenchmarkLockBusy("Worker lock is currently held by another worker (flock busy)") from exc
