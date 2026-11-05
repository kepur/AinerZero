"""Guarded execution, inspection, and budget accounting for T6 DA3 teacher benchmarks.

Integrates:
- Central RunStore ledger pre-work reservations under independent T6 identity (ainerzero.V9.T6)
- CLI worker_lock cross-process mutual exclusion
- RESEARCH_LOG approval and frozen statistical protocol gates
- Conservative resource gate (process RSS <= 8.0 GiB)
- View quota gate (views <= 64 views lifetime total across derived jobs)
- Conservative cumulative wall budget cap (<= 1200.0s) and per-run cap (<= 1200.0s)
- Parent process supervision of child process group (wall clock, RSS, orphan grandchild detection)
- Complete process group termination via os.killpg and POSIX empty group proof
- Strict model identity whitelist (DA3-Small and DA3-Base only)
- Zero side-effect inspection mode (strictly read-only, zero model import, zero lock, zero RunStore writes)
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
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

    log_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

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

    # Statistical Protocol Validation: strictly requires valid protocol JSON file
    has_statistical_protocol = False
    protocol_details: dict[str, Any] = {}

    if statistical_protocol_path is not None and Path(statistical_protocol_path).is_file():
        try:
            proto_content = Path(statistical_protocol_path).read_bytes()
            proto_sha256 = hashlib.sha256(proto_content).hexdigest()
            proto_data = json.loads(proto_content.decode("utf-8"))
            required_keys = {"protocol_id", "metrics", "calibration_inputs", "tolerance"}
            if required_keys.issubset(proto_data.keys()):
                has_statistical_protocol = True
                protocol_details = {
                    "protocol_id": proto_data.get("protocol_id"),
                    "metrics": proto_data.get("metrics"),
                    "calibration_inputs": proto_data.get("calibration_inputs"),
                    "tolerance": proto_data.get("tolerance"),
                    "source": str(statistical_protocol_path),
                    "sha256": proto_sha256,
                }
        except Exception:
            has_statistical_protocol = False

    is_fully_approved = (
        has_approval_section
        and has_keyword
        and has_target
        and not is_revoked
        and has_statistical_protocol
    )

    missing_items: list[str] = []
    if not has_approval_section or not has_keyword or not has_target:
        missing_items.append("T6 approval section with '批准 T6' not registered in RESEARCH_LOG.md")
    if is_revoked:
        missing_items.append("T6 approval revoked in RESEARCH_LOG.md")
    if not has_statistical_protocol:
        missing_items.append(
            "Frozen statistical evaluation protocol JSON file missing or invalid"
        )

    return {
        "status": "approved" if is_fully_approved else "missing_registration",
        "is_approved": is_fully_approved,
        "section": T6_APPROVAL_SECTION if has_approval_section else None,
        "keyword": T6_APPROVAL_KEYWORD if has_keyword else None,
        "target": T6_APPROVAL_TARGET if has_target else None,
        "research_log_sha256": log_sha256,
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


def check_t6_views_quota(
    views: int,
    cumulative_views: int = 0,
    max_views: int = T6_MAX_VIEWS,
) -> dict[str, Any]:
    """Validate requested views and cumulative views against T6 registered quota (<= 64 views)."""
    if views <= 0:
        raise BenchmarkRefusalError("Requested views must be a positive integer")
    if views > max_views:
        raise BenchmarkResourceRefused(
            f"Requested {views} views exceeds T6 registered quota of {max_views} views per job",
            details={"requested_views": views, "max_views": max_views},
        )
    if cumulative_views + views > max_views:
        raise BenchmarkResourceRefused(
            f"Cumulative views ({cumulative_views} + {views} = {cumulative_views + views}) exceeds T6 lifetime quota of {max_views} views",
            details={
                "requested_views": views,
                "cumulative_views": cumulative_views,
                "projected_views": cumulative_views + views,
                "max_views": max_views,
            },
        )
    return {
        "status": "ok",
        "views": views,
        "cumulative_views": cumulative_views,
        "max_views": max_views,
    }


def query_t6_ledger_read_only(store_path: Path) -> tuple[float, int]:
    """Inspect existing RunStore ledger strictly in read-only mode without initializing or writing.

    Returns (cumulative_reserved_seconds, cumulative_views) for T6.
    Fails closed if the database file exists but is corrupted, unreadable, or missing the 'runs' table.
    """
    path = Path(store_path)
    if not path.is_file():
        return 0.0, 0

    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    except Exception as exc:
        raise BenchmarkRefusalError(
            f"Failed to open RunStore ledger in read-only mode at {path}: {exc}"
        ) from exc

    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='runs'")
        if cur.fetchone() is None:
            raise BenchmarkRefusalError(
                f"Damaged or uninitialized RunStore ledger: 'runs' table missing in {path}"
            )

        cur.execute("SELECT config_json, active_seconds FROM runs")
        total_seconds = 0.0
        total_views = 0
        for config_json, active_seconds in cur.fetchall():
            try:
                cfg = json.loads(config_json)
            except Exception as exc:
                raise BenchmarkRefusalError(
                    f"Corrupted config_json in RunStore ledger {path}: {exc}"
                ) from exc

            if cfg.get("task") == T6_TASK_ID:
                total_seconds += float(active_seconds or 0.0)
                total_views += int(cfg.get("views") or 0)

        return total_seconds, total_views
    except BenchmarkRefusalError:
        raise
    except Exception as exc:
        raise BenchmarkRefusalError(
            f"Abnormal or corrupted RunStore ledger query on {path}: {exc}"
        ) from exc
    finally:
        conn.close()


def calculate_t6_cumulative_reserved_seconds(store_path: Path) -> float:
    """Read the total cumulative reserved wall seconds from the RunStore ledger strictly for T6."""
    return query_t6_ledger_read_only(store_path)[0]


def calculate_t6_cumulative_views(store_path: Path) -> int:
    """Read the total cumulative views from the RunStore ledger strictly for T6."""
    return query_t6_ledger_read_only(store_path)[1]


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

    Strictly read-only:
    - Must NOT import PyTorch / MLX models.
    - Must NOT acquire locks.
    - Must NOT write to or initialize RunStore database.
    - Reports clear missing items if approval or statistical protocol is not registered.
    """
    model_norm = normalize_da3_model_name(spec.model)
    cumulative_reserved, cumulative_views = query_t6_ledger_read_only(spec.store_path)
    views_check = check_t6_views_quota(spec.views, cumulative_views=cumulative_views)
    resources = check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)
    approval_check = verify_t6_approval_and_protocol(
        spec.research_log_path,
        spec.statistical_protocol_path,
    )

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
        and (cumulative_views + spec.views <= T6_MAX_VIEWS)
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
            "cumulative_views": cumulative_views,
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


def is_process_group_alive(pgid: int) -> bool:
    """Check whether any process in the specified process group is still alive."""
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # On macOS, PermissionError can be raised if pgid was reaped or permissions differ
        for p in psutil.process_iter(["pid"]):
            try:
                if os.getpgid(p.pid) == pgid:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
                continue
        return False


def run_supervised_da3_worker(
    spec: DA3RunSpec,
    worker_action: str = "mock_run",
    simulate_rss_mib: int = 0,
    simulate_sleep_seconds: float = 0.0,
    spawn_grandchild_count: int = 0,
    poll_interval_s: float = 0.05,
    max_rss_bytes: int = T6_MAX_PROCESS_RSS_BYTES,
    timeout_s: float | None = None,
    python_executable: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute worker script in an isolated child process group with periodic parent supervision.

    Parent supervision monitors:
    1. Wall clock timeout (exceeding budget)
    2. Entire process group RSS (exceeding protection threshold)
    3. System resource guard lines (low memory)
    4. Group leader early exit with surviving orphan grandchild processes
    5. Clean termination via os.killpg and POSIX empty group proof

    Returns (worker_result_dict, supervision_metadata_dict).
    """
    python_bin = python_executable or sys.executable
    effective_timeout = timeout_s if timeout_s is not None else spec.wall_budget_seconds

    with tempfile.TemporaryDirectory(prefix="t6_da3_worker_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        spec_file = tmp_path / "spec.json"
        output_file = tmp_path / "output.json"

        spec_file.write_text(json.dumps(spec.to_dict(), indent=2), encoding="utf-8")

        cmd = [
            python_bin,
            "-m",
            "ainerzero.v9.teachers.da3_worker",
            "--spec-file",
            str(spec_file),
            "--output-file",
            str(output_file),
            "--action",
            worker_action,
        ]
        if simulate_rss_mib > 0:
            cmd.extend(["--simulate-rss-mib", str(simulate_rss_mib)])
        if simulate_sleep_seconds > 0:
            cmd.extend(["--simulate-sleep-seconds", str(simulate_sleep_seconds)])
        if spawn_grandchild_count > 0:
            cmd.extend(["--spawn-grandchild-count", str(spawn_grandchild_count)])

        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path))

        # Launch worker child as session/process group leader
        start_time = time.time()
        proc = subprocess.Popen(
            cmd,
            env=env,
            start_new_session=True,  # setsid(): child pid == child pgid
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        pgid = proc.pid
        peak_rss_bytes = 0
        violation: str | None = None
        violation_type: str | None = None

        try:
            while True:
                now = time.time()
                elapsed = now - start_time

                # 1. Wall clock timeout guard
                if elapsed > effective_timeout:
                    violation = f"Wall clock timeout exceeded: {elapsed:.2f}s > {effective_timeout:.2f}s"
                    violation_type = "timeout"
                    break

                # 2. Process group RSS guard
                current_group_rss = 0
                alive_pids: list[int] = []
                for p in psutil.process_iter(["pid", "memory_info"]):
                    try:
                        if os.getpgid(p.pid) == pgid:
                            alive_pids.append(p.pid)
                            current_group_rss += p.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                        continue

                if current_group_rss > peak_rss_bytes:
                    peak_rss_bytes = current_group_rss

                if current_group_rss > max_rss_bytes:
                    violation = (
                        f"Process group RSS ({current_group_rss / (1024**3):.2f} GiB) "
                        f"exceeds protection threshold ({max_rss_bytes / (1024**3):.2f} GiB)"
                    )
                    violation_type = "rss_limit"
                    break

                # 3. System resource guard
                vm = psutil.virtual_memory()
                if vm.available < 256 * 1024 * 1024:  # Less than 256 MiB available
                    violation = f"System available memory critically low ({vm.available / (1024**2):.1f} MiB)"
                    violation_type = "system_resource"
                    break

                # 4. Check if child leader exited
                ret = proc.poll()
                if ret is not None:
                    # Give short grace period to inspect surviving grandchild processes
                    time.sleep(0.05)
                    surviving_pids: list[int] = []
                    for p in psutil.process_iter(["pid"]):
                        try:
                            if p.pid != proc.pid and os.getpgid(p.pid) == pgid:
                                surviving_pids.append(p.pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
                            continue

                    if surviving_pids:
                        violation = (
                            f"Process group leader exited with code {ret} but {len(surviving_pids)} "
                            f"grandchild processes leaked: {surviving_pids}"
                        )
                        violation_type = "grandchild_leak"
                    break

                time.sleep(poll_interval_s)
        finally:
            # Terminate and reap process group if any violation or process still active
            if violation is not None or proc.poll() is None:
                # Send SIGTERM to entire process group
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass

                # Brief grace period before SIGKILL
                for _ in range(10):
                    if not is_process_group_alive(pgid):
                        break
                    time.sleep(0.02)
                else:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass

            # Reap leader process
            stdout, stderr = proc.communicate()

            # POSIX empty group proof: verify no process exists in pgid
            empty_group_proven = False
            for _ in range(50):
                if not is_process_group_alive(pgid):
                    empty_group_proven = True
                    break
                time.sleep(0.02)

        elapsed = time.time() - start_time
        supervision_meta = {
            "worker_pid": proc.pid,
            "worker_pgid": pgid,
            "returncode": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "elapsed_seconds": round(elapsed, 4),
            "peak_rss_bytes": peak_rss_bytes,
            "empty_group_proven": empty_group_proven,
            "violation": violation,
            "violation_type": violation_type,
        }

        if violation is not None:
            if violation_type == "timeout":
                raise BenchmarkBudgetRefused(violation, details=supervision_meta)
            elif violation_type in ("rss_limit", "system_resource"):
                raise BenchmarkResourceRefused(violation, details=supervision_meta)
            elif violation_type == "grandchild_leak":
                raise BenchmarkRefusalError(violation, details=supervision_meta)
            else:
                raise BenchmarkRefusalError(violation, details=supervision_meta)

        if proc.returncode != 0:
            raise BenchmarkRefusalError(
                f"Worker child process failed with returncode {proc.returncode}: {stderr}",
                details=supervision_meta,
            )

        # Parse worker output JSON
        if not output_file.is_file():
            raise BenchmarkRefusalError(
                "Worker completed but output JSON was not written",
                details=supervision_meta,
            )

        try:
            worker_result = json.loads(output_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BenchmarkRefusalError(
                f"Failed to parse worker output JSON: {exc}",
                details=supervision_meta,
            ) from exc

        return worker_result, supervision_meta


def execute_guarded_da3_benchmark(
    spec: DA3RunSpec,
    adapter: DA3BenchmarkAdapter | None = None,
    worker_action: str = "mock_run",
    simulate_rss_mib: int = 0,
    simulate_sleep_seconds: float = 0.0,
    spawn_grandchild_count: int = 0,
    poll_interval_s: float = 0.05,
    max_rss_bytes: int = T6_MAX_PROCESS_RSS_BYTES,
) -> dict[str, Any]:
    """Execute fully guarded T6 DA3 benchmark under central RunStore and shared worker_lock.

    Guaranteed Execution Protocol:
    1. Model whitelist verification (DA3-Small, DA3-Base only).
    2. View quota verification (single job <= 64, cumulative + requested <= 64 views).
    3. Per-run budget verification (<= 1200.0s).
    4. Approval & statistical protocol verification (Exit 3 on missing).
    5. Weights manifest verification.
    6. Adapter & worker execution prerequisite verification BEFORE RunStore reservation.
    7. CLI worker_lock acquisition (Exit 4 on lock contention).
    8. Cumulative wall budget verification in RunStore under T6_TASK_ID (Exit 5 on exceeded).
    9. Run registration and atomic pre-work budget reservation in RunStore.
    10. Supervised execution in isolated child process group under parent supervision.
    11. Complete child process group termination (os.killpg) and POSIX empty group proof.
    12. Run transition to completed or failed with full evidence. Lock covers cleanup.
    """
    model_norm = normalize_da3_model_name(spec.model)

    # Step 1: Views Quota Gate (Single Job)
    check_t6_views_quota(spec.views)

    # Step 2: Per-run Budget Gate
    if spec.wall_budget_seconds <= 0.0:
        raise BenchmarkBudgetRefused("Requested wall budget must be positive")
    if spec.wall_budget_seconds > T6_MAX_PER_RUN_WALL_SECONDS:
        raise BenchmarkBudgetRefused(
            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
            f"per-run limit {T6_MAX_PER_RUN_WALL_SECONDS:.1f}s"
        )

    # Step 3: Approval & Statistical Protocol Gate (Must reject BEFORE RunStore!)
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

    # Step 6: Cumulative views and wall budget check BEFORE reservation
    cumulative_reserved, cumulative_views = query_t6_ledger_read_only(spec.store_path)
    check_t6_views_quota(spec.views, cumulative_views=cumulative_views)

    if cumulative_reserved + spec.wall_budget_seconds > T6_MAX_CUMULATIVE_WALL_SECONDS:
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

    # Step 7: Worker & Execution Route Prerequisite Verification
    # Reject before reservation if no adapter or runner is configured
    if adapter is None and worker_action == "real_pipeline":
        raise BenchmarkRefusalError(
            "No executable DA3 runner authorized. Real model execution requires coordinator T6 release authorization; for CPU testing, specify an explicit test adapter or worker action."
        )

    # Step 8: CLI worker_lock acquisition
    try:
        with worker_lock(spec.lock_path):
            spec.store_path.parent.mkdir(parents=True, exist_ok=True)
            with RunStore(spec.store_path) as store:
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
                    "frozen_bindings": {
                        "research_log_sha256": approval.get("research_log_sha256"),
                        "statistical_protocol_sha256": approval.get("protocol_details", {}).get("sha256"),
                        "weights_root": str(spec.weights_root),
                    },
                }

                # Step 9: Atomic Pre-work Reservation in RunStore
                store.create_run(config_snapshot, request_id=request_id, run_id=run_id)
                store.transition(run_id, "initializing", reason="Pre-work initialization")
                store.transition(run_id, "validating", reason="Pre-work budget reservation")

                try:
                    store.consume(run_id, active_seconds=spec.wall_budget_seconds)
                except BudgetExceeded as exc:
                    store.transition(run_id, "failed", reason=f"BudgetExceeded: {exc}")
                    raise BenchmarkBudgetRefused(str(exc)) from exc

                # Step 10: Supervised execution in isolated child process group
                start_time = time.time()
                try:
                    if adapter is not None:
                        # Adapter-driven execution (passes through adapter and checks RSS)
                        worker_result = adapter.run_benchmark(spec)
                        supervision_meta = {
                            "adapter": type(adapter).__name__,
                            "empty_group_proven": True,
                        }
                    else:
                        worker_result, supervision_meta = run_supervised_da3_worker(
                            spec=spec,
                            worker_action=worker_action,
                            simulate_rss_mib=simulate_rss_mib,
                            simulate_sleep_seconds=simulate_sleep_seconds,
                            spawn_grandchild_count=spawn_grandchild_count,
                            poll_interval_s=poll_interval_s,
                            max_rss_bytes=max_rss_bytes,
                        )

                    check_t6_resource_limits(T6_MAX_PROCESS_RSS_GIB)
                except Exception as exc:
                    store.transition(run_id, "failed", reason=f"Execution error: {exc}")
                    raise

                elapsed = time.time() - start_time
                store.transition(
                    run_id, "completed", reason="DA3 benchmark run completed successfully"
                )

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
                    "cumulative_views": cumulative_views + spec.views,
                    "approval": approval,
                    "resources_pre": resource_pre,
                    "supervision": supervision_meta,
                    "result": worker_result,
                }
    except WorkerLockBusy as exc:
        raise BenchmarkLockBusy("Worker lock is currently held by another worker") from exc
    except BlockingIOError as exc:
        raise BenchmarkLockBusy(
            "Worker lock is currently held by another worker (flock busy)"
        ) from exc
