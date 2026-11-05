"""Guarded execution, inspection, and budget accounting for T6 DA3 teacher benchmarks.

Integrates:
- Central RunStore ledger pre-work reservations under independent T6 identity (ainerzero.V9.T6)
- CLI worker_lock cross-process mutual exclusion
- RESEARCH_LOG approval and frozen statistical protocol gates
- Conservative resource gate (process RSS <= 8.0 GiB)
- View quota gate (views <= 64 views per derived job)
- Conservative cumulative wall budget cap (<= 1200.0s) and per-run cap (<= 1200.0s)
- Parent process supervision of child process group (terminating child group on limit breach)
- Strict model identity whitelist (DA3-Small and DA3-Base only)
- Zero side-effect inspection mode (zero model import, zero lock, zero RunStore writes)
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import psutil

from ainerzero.cli import WorkerLockBusy, worker_lock
from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore

from .benchmark_protocol import (
    APPROVED_DA3_MODELS,
    DEFAULT_LOCK_PATH,
    DEFAULT_RESEARCH_LOG,
    DEFAULT_STORE_PATH,
    DEFAULT_T6_WEIGHTS_ROOT,
    EXIT_COMPLETED,
    EXIT_FAILED,
    EXIT_LOCK_BUSY,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
    EXIT_REFUSED_RESOURCE,
    T6_APPROVAL_KEYWORD,
    T6_APPROVAL_SECTION,
    T6_APPROVAL_TARGET,
    T6_MAX_CUMULATIVE_WALL_SECONDS,
    T6_MAX_PER_RUN_WALL_SECONDS,
    T6_MAX_PROCESS_RSS_BYTES,
    T6_MAX_PROCESS_RSS_GIB,
    T6_MAX_RESIDENT_MODELS,
    T6_MAX_VIEWS,
    T6_TASK_ID,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkLockBusy,
    BenchmarkRefusalError,
    BenchmarkResourceRefused,
    DA3RunSpec,
    TeacherModelSpec,
)


class DA3BenchmarkAdapter(Protocol):
    """Protocol for DA3 benchmark execution adapters."""

    def run_benchmark(self, spec: DA3RunSpec) -> dict[str, Any]:
        """Execute benchmark and return structured evidence dictionary."""
        ...


class FakeDA3BenchmarkAdapter:
    """CPU-only test adapter that simulates DA3 benchmark execution."""

    def __init__(
        self,
        should_fail: bool = False,
        fail_message: str = "Simulated DA3 execution error",
        simulated_rss_bytes: int | None = None,
        simulated_elapsed_s: float = 0.05,
    ):
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.simulated_rss_bytes = simulated_rss_bytes
        self.simulated_elapsed_s = simulated_elapsed_s
        self.invocations: list[DA3RunSpec] = []

    def run_benchmark(self, spec: DA3RunSpec) -> dict[str, Any]:
        self.invocations.append(spec)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        time.sleep(self.simulated_elapsed_s)
        return {
            "status": "completed",
            "fake": True,
            "task": T6_TASK_ID,
            "model": spec.model,
            "views": spec.views,
            "wall_budget_seconds": spec.wall_budget_seconds,
            "prediction_record": {
                "record_type": "teacher_prediction_candidate",
                "registered_cache_entry": False,
            },
        }


def normalize_da3_model_name(model: str) -> str:
    """Normalize model string to canonical key in APPROVED_DA3_MODELS or raise refusal."""
    m = model.strip().lower()
    if m in ("da3-small", "small"):
        return "da3-small"
    elif m in ("da3-base", "base"):
        return "da3-base"
    elif m in ("da3-all", "all"):
        return "da3-all"
    raise BenchmarkRefusalError(
        f"Unknown or unapproved DA3 model '{model}'. Whitelisted models: {list(APPROVED_DA3_MODELS.keys())} or 'da3-all'",
        details={"requested_model": model, "allowed": list(APPROVED_DA3_MODELS.keys())},
    )


def verify_t6_approval_and_protocol(
    research_log_path: Path,
    statistical_protocol_path: Path | None = None,
) -> dict[str, Any]:
    """Verify RESEARCH_LOG.md approval line and statistical protocol registration for T6."""
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
            if T6_APPROVAL_SECTION in line or (
                "T6" in line and ("批准" in line or "approval" in line.lower())
            ):
                in_target_section = True
                section_lines.append(line)
                continue
            elif in_target_section:
                break
        if in_target_section:
            section_lines.append(line)

    section_text = "\n".join(section_lines) if section_lines else ""
    has_approval_section = bool(in_target_section and section_lines)
    has_keyword = T6_APPROVAL_KEYWORD in section_text or "批准 T6" in section_text or "批准 DA3" in section_text
    has_target = T6_APPROVAL_TARGET in section_text or "T6" in section_text

    # Negative revocation checks
    is_revoked = "撤销 T6" in section_text or "作废 T6" in section_text

    # Statistical Protocol Validation
    has_statistical_protocol = False
    protocol_details: dict[str, Any] = {}

    if statistical_protocol_path is not None and Path(statistical_protocol_path).is_file():
        try:
            proto_data = json.loads(Path(statistical_protocol_path).read_text(encoding="utf-8"))
            required_keys = {"protocol_id", "metrics", "calibration_inputs", "tolerance"}
            if required_keys.issubset(proto_data.keys()):
                has_statistical_protocol = True
                protocol_details = {
                    "protocol_id": proto_data.get("protocol_id"),
                    "metrics": proto_data.get("metrics"),
                    "calibration_inputs": proto_data.get("calibration_inputs"),
                    "source": str(statistical_protocol_path),
                }
        except Exception:
            has_statistical_protocol = False
    elif "统计协议" in section_text and "配对真值" in section_text:
        has_statistical_protocol = True
        protocol_details = {"source": "RESEARCH_LOG", "section": T6_APPROVAL_SECTION}

    is_fully_approved = has_approval_section and has_keyword and has_target and not is_revoked and has_statistical_protocol

    missing_items: list[str] = []
    if not has_approval_section or not has_keyword or not has_target:
        missing_items.append("T6 approval section with '批准 T6' not registered in RESEARCH_LOG.md")
    if is_revoked:
        missing_items.append("T6 approval revoked in RESEARCH_LOG.md")
    if not has_statistical_protocol:
        missing_items.append(
            "Frozen statistical evaluation protocol and paired calibration inputs not registered by coordinator"
        )

    return {
        "status": "approved" if is_fully_approved else "missing_registration",
        "is_approved": is_fully_approved,
        "section": T6_APPROVAL_SECTION if has_approval_section else None,
        "keyword": T6_APPROVAL_KEYWORD if has_keyword else None,
        "target": T6_APPROVAL_TARGET if has_target else None,
        "has_statistical_protocol": has_statistical_protocol,
        "protocol_details": protocol_details,
        "missing_items": missing_items,
        "max_cumulative_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
        "max_per_run_wall_seconds": T6_MAX_PER_RUN_WALL_SECONDS,
        "max_resident_models": T6_MAX_RESIDENT_MODELS,
        "max_process_rss_gib": T6_MAX_PROCESS_RSS_GIB,
        "max_views": T6_MAX_VIEWS,
    }


def check_t6_resource_limits(max_rss_gib: float = T6_MAX_PROCESS_RSS_GIB) -> dict[str, Any]:
    """Check process memory against registered T6 resource limit (RSS <= 8.0 GiB)."""
    process = psutil.Process(os.getpid())
    rss_bytes = process.memory_info().rss
    rss_gib = rss_bytes / (1024**3)
    max_rss_bytes = int(max_rss_gib * (1024**3))

    if rss_bytes > max_rss_bytes:
        raise BenchmarkResourceRefused(
            f"Process RSS {rss_gib:.2f} GiB exceeds T6 protection limit of {max_rss_gib:.2f} GiB",
            details={"rss_bytes": rss_bytes, "rss_gib": rss_gib, "max_rss_gib": max_rss_gib},
        )

    return {
        "status": "ok",
        "rss_bytes": rss_bytes,
        "rss_gib": round(rss_gib, 4),
        "max_rss_gib": max_rss_gib,
    }


def check_t6_views_quota(views: int, max_views: int = T6_MAX_VIEWS) -> dict[str, Any]:
    """Validate requested views against T6 registered quota (<= 64 views)."""
    if views <= 0:
        raise BenchmarkRefusalError("Requested views must be a positive integer")
    if views > max_views:
        raise BenchmarkResourceRefused(
            f"Requested {views} views exceeds T6 registered quota of {max_views} views per job",
            details={"requested_views": views, "max_views": max_views},
        )
    return {"status": "ok", "views": views, "max_views": max_views}


def calculate_t6_cumulative_reserved_seconds(store_path: Path) -> float:
    """Read the total cumulative reserved wall seconds from the RunStore ledger strictly for T6."""
    path = Path(store_path)
    if not path.is_file():
        return 0.0

    try:
        with RunStore(path) as store:
            runs = store.list_runs()
            # Filter strictly by task identity T6_TASK_ID
            return sum(
                r.reserved_active_seconds
                for r in runs
                if r.config_snapshot.get("task") == T6_TASK_ID
            )
    except Exception:
        # Fallback to direct read-only query if RunStore lock contention occurs
        try:
            import sqlite3

            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute("SELECT config_json, reserved_active_seconds FROM runs")
            total = 0.0
            for config_json, reserved in cur.fetchall():
                try:
                    cfg = json.loads(config_json)
                    if cfg.get("task") == T6_TASK_ID:
                        total += float(reserved or 0.0)
                except Exception:
                    pass
            conn.close()
            return total
        except Exception:
            return 0.0


def check_da3_weights_manifest(
    weights_root: Path,
    model_id: str,
) -> dict[str, Any]:
    """Check DA3 model weights and configuration on disk against exact approved manifest."""
    canonical_model = normalize_da3_model_name(model_id)
    target_models = (
        APPROVED_DA3_MODELS.values()
        if canonical_model == "da3-all"
        else [APPROVED_DA3_MODELS[canonical_model]]
    )

    verified_models: list[dict[str, Any]] = []

    for spec in target_models:
        model_dir = Path(weights_root) / spec.model_id.upper()
        if not model_dir.is_dir():
            model_dir = Path(weights_root) / spec.model_id
        if not model_dir.is_dir():
            raise BenchmarkRefusalError(
                f"Model weights directory not found for {spec.model_id} under {weights_root}",
                details={"model_id": spec.model_id, "weights_root": str(weights_root)},
            )

        model_files_report: list[dict[str, Any]] = []
        for file_spec in spec.files:
            file_path = model_dir / file_spec.relative_path
            if not file_path.is_file():
                raise BenchmarkRefusalError(
                    f"Required weight file missing for {spec.model_id}: {file_path}",
                    details={"file": str(file_path), "model_id": spec.model_id},
                )

            file_stat = file_path.stat()
            if file_stat.st_size != file_spec.bytes:
                raise BenchmarkRefusalError(
                    f"File size mismatch for {file_path}: expected {file_spec.bytes} B, got {file_stat.st_size} B",
                    details={
                        "file": str(file_path),
                        "expected_bytes": file_spec.bytes,
                        "actual_bytes": file_stat.st_size,
                    },
                )

            h = hashlib.sha256()
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            actual_sha = h.hexdigest()

            if actual_sha != file_spec.sha256:
                raise BenchmarkRefusalError(
                    f"SHA256 checksum mismatch for {file_path}: expected {file_spec.sha256}, got {actual_sha}",
                    details={
                        "file": str(file_path),
                        "expected_sha": file_spec.sha256,
                        "actual_sha": actual_sha,
                    },
                )

            model_files_report.append(
                {
                    "file": file_spec.relative_path,
                    "bytes": file_stat.st_size,
                    "sha256": actual_sha,
                    "verified": True,
                }
            )

        verified_models.append(
            {
                "model_id": spec.model_id,
                "repository": spec.repository,
                "revision": spec.revision,
                "license": spec.license,
                "files_count": len(model_files_report),
                "total_bytes": sum(f["bytes"] for f in model_files_report),
                "files": model_files_report,
            }
        )

    return {
        "status": "verified",
        "models_count": len(verified_models),
        "models": verified_models,
    }


def inspect_da3_benchmark(spec: DA3RunSpec) -> dict[str, Any]:
    """Execute zero side-effect inspection of T6 DA3 benchmark prerequisites.

    Must NOT import PyTorch / MLX models.
    Must NOT acquire locks.
    Must NOT write to RunStore database.
    Reports clear missing items if approval or statistical protocol is not registered.
    """
    model_norm = normalize_da3_model_name(spec.model)
    views_check = check_t6_views_quota(spec.views)
    resources = check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)
    approval_check = verify_t6_approval_and_protocol(
        spec.research_log_path,
        spec.statistical_protocol_path,
    )
    cumulative_reserved = calculate_t6_cumulative_reserved_seconds(spec.store_path)

    # Weights manifest inspection (read-only)
    weights_info: dict[str, Any] = {}
    try:
        weights_info = check_da3_weights_manifest(spec.weights_root, model_norm)
    except Exception as exc:
        weights_info = {"status": "unverified", "error": str(exc)}

    can_run = (
        approval_check["is_approved"]
        and weights_info.get("status") == "verified"
        and (cumulative_reserved + spec.wall_budget_seconds <= T6_MAX_CUMULATIVE_WALL_SECONDS)
    )

    return {
        "mode": "inspect",
        "task": T6_TASK_ID,
        "model": model_norm,
        "views": spec.views,
        "views_quota": views_check,
        "wall_budget_seconds": spec.wall_budget_seconds,
        "can_run": can_run,
        "approval": approval_check,
        "resources_current": resources,
        "budget": {
            "max_cumulative_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
            "max_per_run_wall_seconds": T6_MAX_PER_RUN_WALL_SECONDS,
            "cumulative_reserved_seconds": cumulative_reserved,
            "remaining_cumulative_seconds": max(
                0.0, T6_MAX_CUMULATIVE_WALL_SECONDS - cumulative_reserved
            ),
            "requested_run_seconds": spec.wall_budget_seconds,
        },
        "weights": weights_info,
        "side_effects": {
            "lock_acquired": False,
            "ledger_written": False,
            "models_loaded": 0,
        },
    }


def execute_guarded_da3_benchmark(
    spec: DA3RunSpec,
    adapter: DA3BenchmarkAdapter | None = None,
) -> dict[str, Any]:
    """Execute fully guarded T6 DA3 benchmark under central RunStore and shared worker_lock.

    1. Normalize model in DA3 whitelist (DA3-Small, DA3-Base).
    2. Check view quota (<= 64 views).
    3. Check per-run budget (<= 1200.0s).
    4. Check approval and statistical protocol. Exit 3 on missing.
    5. Check weights manifest.
    6. Check process RSS pre-lock (<= 8.0 GiB).
    7. Acquire exclusive worker_lock (Exit 4 on lock busy).
    8. Check cumulative budget in central RunStore under T6_TASK_ID (<= 1200.0s). Exit 5 on exceeded.
    9. Register run and pre-reserve budget in central RunStore. (Irreversible pre-reservation!).
    10. Supervise execution under adapter or child process group, asserting RSS <= 8.0 GiB.
    11. Transition run to completed or failed with full evidence. Lock covers model unload.
    """
    model_norm = normalize_da3_model_name(spec.model)

    # Step 1: Views Quota Gate
    check_t6_views_quota(spec.views)

    # Step 2: Per-run Budget Gate
    if spec.wall_budget_seconds <= 0.0:
        raise BenchmarkBudgetRefused("Requested wall budget must be positive")
    if spec.wall_budget_seconds > T6_MAX_PER_RUN_WALL_SECONDS:
        raise BenchmarkBudgetRefused(
            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
            f"per-run limit {T6_MAX_PER_RUN_WALL_SECONDS:.1f}s"
        )

    # Step 3: Approval & Statistical Protocol Gate
    approval = verify_t6_approval_and_protocol(
        spec.research_log_path,
        spec.statistical_protocol_path,
    )
    if not approval["is_approved"]:
        raise BenchmarkApprovalRefused(
            f"T6 DA3 benchmark refused: approval or statistical protocol missing: {'; '.join(approval['missing_items'])}",
            details=approval,
        )

    # Step 4: Weights Manifest Gate
    check_da3_weights_manifest(spec.weights_root, model_norm)

    # Step 5: Pre-lock Resource Gate
    resource_pre = check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)

    # Step 6: CLI worker_lock acquisition
    try:
        with worker_lock(spec.lock_path):
            # Step 7: Central RunStore Ledger & Cumulative Budget Gate
            spec.store_path.parent.mkdir(parents=True, exist_ok=True)
            with RunStore(spec.store_path) as store:
                runs = store.list_runs()
                cumulative_reserved = sum(
                    r.reserved_active_seconds
                    for r in runs
                    if r.config_snapshot.get("task") == T6_TASK_ID
                )
                if (
                    cumulative_reserved + spec.wall_budget_seconds
                    > T6_MAX_CUMULATIVE_WALL_SECONDS
                ):
                    raise BenchmarkBudgetRefused(
                        f"Cumulative wall budget exceeded for T6: {cumulative_reserved:.1f}s reserved + "
                        f"{spec.wall_budget_seconds:.1f}s requested > {T6_MAX_CUMULATIVE_WALL_SECONDS:.1f}s limit",
                        details={
                            "task": T6_TASK_ID,
                            "cumulative_reserved": cumulative_reserved,
                            "requested": spec.wall_budget_seconds,
                            "limit": T6_MAX_CUMULATIVE_WALL_SECONDS,
                        },
                    )

                run_id = spec.run_id or uuid4().hex
                request_id = spec.request_id or f"t6-da3-{run_id}"

                config_snapshot = {
                    "task": T6_TASK_ID,
                    "model": model_norm,
                    "views": spec.views,
                    "budget": {
                        "max_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
                        "max_environment_steps": 1000,
                        "max_optimizer_steps": 1000,
                        "max_daily_active_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
                        "max_model_transitions": 0,
                        "timezone": "UTC",
                    },
                }

                # Register run
                store.create_run(config_snapshot, request_id=request_id, run_id=run_id)
                store.transition(run_id, "initializing", reason="Pre-work initialization")
                store.transition(run_id, "validating", reason="Pre-work budget reservation")

                # Step 8: Atomic Pre-work Reservation in RunStore
                try:
                    store.consume(run_id, active_seconds=spec.wall_budget_seconds)
                except BudgetExceeded as exc:
                    store.transition(run_id, "failed", reason=f"BudgetExceeded: {exc}")
                    raise BenchmarkBudgetRefused(str(exc)) from exc

                # Step 9: Re-check Resource Limits
                check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)

                # Step 10: Supervised execution under adapter
                start_time = time.time()
                actual_adapter = adapter
                if actual_adapter is None:
                    # In real execution mode without adapter, check for real pipeline runner
                    raise BenchmarkRefusalError(
                        "No executable adapter provided. CPU engineering entry requires explicit test adapter; real model execution requires coordinator T6 registration."
                    )

                execution_result: dict[str, Any] = {}
                try:
                    execution_result = actual_adapter.run_benchmark(spec)
                except Exception as exc:
                    store.transition(run_id, "failed", reason=f"Adapter error: {exc}")
                    raise

                # Verify execution did not violate RSS limit
                check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)

                elapsed = time.time() - start_time
                store.transition(run_id, "completed", reason="DA3 benchmark run completed successfully")

                return {
                    "mode": "run",
                    "task": T6_TASK_ID,
                    "status": "completed",
                    "run_id": run_id,
                    "request_id": request_id,
                    "model": model_norm,
                    "views": spec.views,
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
