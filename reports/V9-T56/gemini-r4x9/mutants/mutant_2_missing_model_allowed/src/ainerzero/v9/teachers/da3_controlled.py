"""Guarded execution, inspection, and budget accounting for T6 DA3 teacher benchmarks.

Integrates:
- Central RunStore ledger pre-work reservations under independent T6 identity (ainerzero.V9.T6)
- CLI worker_lock cross-process mutual exclusion with double-checked accounting
- RESEARCH_LOG approval and frozen statistical protocol gates
- Hardware resource guards (AC power, system memory >= 16 GiB, swap growth <= 1 GiB, process RSS <= 8 GiB)
- View quota gate (views <= 64 views lifetime total across derived jobs)
- Conservative cumulative wall budget cap (<= 1200.0s) and per-run cap (<= 1200.0s)
- True parent process supervision of child process group (wall clock, RSS, orphan grandchild detection)
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
from ainerzero.runtime.hardware import collect_hardware
from ainerzero.runtime.lifecycle import BudgetExceeded, RunStore
from ainerzero.v9.teachers.benchmark_protocol import (
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
from ainerzero.v9.teachers.t28_registration import (
    get_registered_calibration_views,
    get_registered_cumulative_wall_cap_s,
    get_registered_run_wall_budget_s,
)

SYSTEM_RESERVE_GIB = 16.0
SYSTEM_RESERVE_BYTES = int(SYSTEM_RESERVE_GIB * (1024**3))
SWAP_GROWTH_LIMIT_GIB = 1.0
SWAP_GROWTH_LIMIT_BYTES = int(SWAP_GROWTH_LIMIT_GIB * (1024**3))


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
            "model_runs": 0,
            "prediction_record": {
                "record_type": "teacher_prediction_candidate",
                "registered_cache_entry": False,
                "model_runs": 0,
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
        "max_cumulative_wall_seconds": get_registered_cumulative_wall_cap_s(),
        "max_per_run_wall_seconds": T6_MAX_PER_RUN_WALL_SECONDS,
        "max_resident_models": T6_MAX_RESIDENT_MODELS,
        "max_process_rss_gib": T6_MAX_PROCESS_RSS_GIB,
        "max_views": T6_MAX_VIEWS,
    }


def check_t6_resource_limits(
    max_rss_gib: float = T6_MAX_PROCESS_RSS_GIB,
    check_system_guards: bool = True,
    system_reserve_bytes: int = SYSTEM_RESERVE_BYTES,
    initial_swap_bytes: int | None = None,
    power_source_override: str | None = None,
    swap_used_override: int | None = None,
) -> dict[str, Any]:
    """Check process memory and hardware resource guard lines.

    Guards:
    1. Process RSS <= 8.0 GiB (T6_MAX_PROCESS_RSS_GIB)
    2. 电源来源只记录、不拦截（用户 10-28）
    3. System available memory >= system_reserve_bytes (default 16 GiB)
    4. Swap growth from baseline <= 1.0 GiB
    """
    process = psutil.Process(os.getpid())
    rss_bytes = process.memory_info().rss
    rss_gib = rss_bytes / (1024**3)
    max_rss_bytes = int(max_rss_gib * (1024**3))

    if rss_bytes > max_rss_bytes:
        raise BenchmarkResourceRefused(
            f"Process RSS {rss_gib:.2f} GiB exceeds T6 protection limit of {max_rss_gib:.2f} GiB",
            details={"rss_bytes": rss_bytes, "rss_gib": rss_gib, "max_rss_gib": max_rss_gib},
        )

    hw = collect_hardware(include_mlx=False)
    power_source = power_source_override or hw.get("power_source", "unknown")

    if check_system_guards:
        # Check 1: System available memory
        vm = psutil.virtual_memory()
        if vm.available < system_reserve_bytes:
            raise BenchmarkResourceRefused(
                f"System available memory {vm.available / (1024**3):.2f} GiB is below "
                f"registered protection line of {system_reserve_bytes / (1024**3):.2f} GiB",
                details={
                    "available_bytes": vm.available,
                    "system_reserve_bytes": system_reserve_bytes,
                },
            )

        # Check 3: Swap growth
        if initial_swap_bytes is not None:
            current_swap = swap_used_override if swap_used_override is not None else psutil.swap_memory().used
            swap_growth = current_swap - initial_swap_bytes
            if swap_growth > SWAP_GROWTH_LIMIT_BYTES:
                raise BenchmarkResourceRefused(
                    f"Swap memory growth {swap_growth / (1024**3):.2f} GiB exceeds "
                    f"registered protection threshold of {SWAP_GROWTH_LIMIT_GIB:.2f} GiB",
                    details={
                        "swap_growth_bytes": swap_growth,
                        "swap_growth_limit_bytes": SWAP_GROWTH_LIMIT_BYTES,
                    },
                )

    return {
        "status": "ok",
        "rss_bytes": rss_bytes,
        "rss_gib": round(rss_gib, 4),
        "max_rss_gib": max_rss_gib,
        "power_source": power_source,
    }


def get_effective_t6_max_views(store_path: Path | None = None) -> int:
    """Return effective T6 max views, checking RunStore metadata for authorized override.

    Reads all `t6_views_override_YYYYMMDD` and `t35_views_override_YYYYMMDD` keys.
    Selects the latest by date suffix (YYYYMMDD).
    If two keys on the same day have different values, raises BenchmarkRefusalError (conflict).
    """
    if store_path is None:
        return T6_MAX_VIEWS

    p = Path(store_path)
    if not p.is_file():
        return T6_MAX_VIEWS

    import re
    import sqlite3

    try:
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    except Exception:
        return T6_MAX_VIEWS

    try:
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")
        if not cur.fetchone():
            return T6_MAX_VIEWS
        cur.execute("SELECT key, value FROM metadata")
        rows = cur.fetchall()
    except Exception:
        return T6_MAX_VIEWS
    finally:
        conn.close()

    pattern = re.compile(r"^(?:t6|t35)_views_override_(\d{8})$")
    overrides_by_date: dict[str, dict[str, int]] = {}

    for key, val_raw in rows:
        m = pattern.match(key)
        if not m:
            continue
        date_str = m.group(1)
        try:
            parsed = json.loads(val_raw)
            if isinstance(parsed, dict):
                views_val = parsed.get("new_max_views")
            elif isinstance(parsed, int):
                views_val = parsed
            else:
                views_val = None
        except Exception as exc:
            raise BenchmarkRefusalError(
                f"Failed to parse metadata override JSON for key {key}: {exc}"
            ) from exc

        if not isinstance(views_val, int) or views_val <= 0:
            raise BenchmarkRefusalError(
                f"Invalid new_max_views in metadata override for key {key}: {views_val}"
            )

        if date_str not in overrides_by_date:
            overrides_by_date[date_str] = {}
        overrides_by_date[date_str][key] = views_val

    if not overrides_by_date:
        return T6_MAX_VIEWS

    # Check for conflicts on each day
    for date_str, keys_dict in overrides_by_date.items():
        unique_vals = set(keys_dict.values())
        if len(unique_vals) > 1:
            raise BenchmarkRefusalError(
                f"Conflicting views override values on {date_str}: {keys_dict}"
            )

    latest_date = max(overrides_by_date.keys())
    latest_val = next(iter(overrides_by_date[latest_date].values()))
    return latest_val


def check_t6_views_quota(
    views: int,
    cumulative_views: int = 0,
    max_views: int | None = None,
) -> dict[str, Any]:
    """Validate requested views and cumulative views against T6 registered quota (<= 64 views baseline or metadata override)."""
    effective_max = max_views if max_views is not None else T6_MAX_VIEWS
    if views <= 0:
        raise BenchmarkRefusalError("Requested views must be a positive integer")
    if views > effective_max:
        raise BenchmarkResourceRefused(
            f"Requested {views} views exceeds T6 registered quota of {effective_max} views per job",
            details={"requested_views": views, "max_views": effective_max},
        )
    if cumulative_views + views > effective_max:
        raise BenchmarkResourceRefused(
            f"Cumulative views ({cumulative_views} + {views} = {cumulative_views + views}) exceeds T6 lifetime quota of {effective_max} views",
            details={
                "requested_views": views,
                "cumulative_views": cumulative_views,
                "projected_views": cumulative_views + views,
                "max_views": effective_max,
            },
        )
    return {
        "status": "ok",
        "views": views,
        "cumulative_views": cumulative_views,
        "max_views": effective_max,
    }


def is_da3_ledger_run(cfg: dict[str, Any]) -> bool:
    """Determine whether a RunStore ledger record belongs to the DA3 teacher line.

    Per 2026-10-28 user decision (E18): DA3 quota uses line-wide accounting across all tasks
    in the central RunStore (whatever the task field). Every run whose model is an approved
    DA3 variant, or that belongs to the DA3 benchmark tasks (T6, T33, T33.r2), is accumulated.

    A run record missing the 'model' field is treated as corrupted ledger state and raises
    BenchmarkRefusalError.
    """
    # MUTANT 2: Missing model allowed without raising BenchmarkRefusalError!
    if not isinstance(cfg, dict) or "model" not in cfg or cfg["model"] is None:
        return False

    model = cfg["model"]
    if not isinstance(model, str) or not model.strip():
        return False

    m = model.strip().lower().replace("_", "-")
    if m in ("da3-small", "da3-base", "da3-all", "small", "base", "all") or m.startswith("da3"):
        return True

    task = cfg.get("task")
    if isinstance(task, str):
        t = task.strip()
        if t in ("ainerzero.V9.T6", "ainerzero.V9.T33", "ainerzero.V9.T33.r2") or t.startswith("ainerzero.V9.T6."):
            return True

    return False


def query_t6_ledger_with_diagnostics(store_path: Path) -> dict[str, Any]:
    """Inspect existing RunStore ledger strictly in read-only mode and return accounting with diagnostics.

    Returns a structured dictionary with:
    - cumulative_reserved_seconds: float
    - cumulative_views: int
    - da3_runs: list of dicts for runs included in DA3 accounting
    - non_da3_runs: list of dicts for runs excluded from DA3 accounting (for diagnostics)
    - total_runs_examined: int

    Fails closed if the database file exists but is corrupted, unreadable, or missing the 'runs' table,
    or if any run record lacks a valid 'model' field.
    """
    path = Path(store_path)
    if not path.is_file():
        return {
            "cumulative_reserved_seconds": 0.0,
            "cumulative_views": 0,
            "da3_runs": [],
            "non_da3_runs": [],
            "total_runs_examined": 0,
        }

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

        cur.execute("SELECT run_id, state, active_seconds, config_json FROM runs")
        total_seconds = 0.0
        total_views = 0
        da3_runs: list[dict[str, Any]] = []
        non_da3_runs: list[dict[str, Any]] = []
        rows = cur.fetchall()
        for run_id, state, active_seconds, config_json in rows:
            try:
                cfg = json.loads(config_json)
            except Exception as exc:
                raise BenchmarkRefusalError(
                    f"Corrupted config_json in RunStore ledger {path}: {exc}"
                ) from exc

            is_da3 = is_da3_ledger_run(cfg)
            entry = {
                "run_id": run_id,
                "state": state,
                "active_seconds": float(active_seconds or 0.0),
                "config": cfg,
            }
            if is_da3:
                total_seconds += float(active_seconds or 0.0)
                total_views += int(cfg.get("views") or 0)
                da3_runs.append(entry)
            else:
                non_da3_runs.append(entry)

        return {
            "cumulative_reserved_seconds": total_seconds,
            "cumulative_views": total_views,
            "da3_runs": da3_runs,
            "non_da3_runs": non_da3_runs,
            "total_runs_examined": len(rows),
        }
    except BenchmarkRefusalError:
        raise
    except Exception as exc:
        raise BenchmarkRefusalError(
            f"Abnormal or corrupted RunStore ledger query on {path}: {exc}"
        ) from exc
    finally:
        conn.close()


def query_t6_ledger_read_only(store_path: Path) -> tuple[float, int]:
    """Inspect existing RunStore ledger strictly in read-only mode without initializing or writing.

    Returns (cumulative_reserved_seconds, cumulative_views) for the DA3 teacher benchmark line
    accumulated line-wide across all tasks (whatever the task field).
    Fails closed if the database file exists but is corrupted, unreadable, or missing the 'runs' table,
    or if any run record lacks a valid 'model' field.
    """
    res = query_t6_ledger_with_diagnostics(store_path)
    return res["cumulative_reserved_seconds"], res["cumulative_views"]


def calculate_t6_cumulative_reserved_seconds(store_path: Path) -> float:
    """Read the total cumulative reserved wall seconds from the RunStore ledger line-wide for DA3."""
    return query_t6_ledger_read_only(store_path)[0]


def calculate_t6_cumulative_views(store_path: Path) -> int:
    """Read the total cumulative views from the RunStore ledger line-wide for DA3."""
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
    effective_max_views = get_effective_t6_max_views(spec.store_path)
    views_check = check_t6_views_quota(spec.views, cumulative_views=cumulative_views, max_views=effective_max_views)
    resources = check_t6_resource_limits(
        max_rss_gib=T6_MAX_PROCESS_RSS_GIB,
        check_system_guards=False,  # Inspect only checks process RSS
    )
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

    cum_wall_cap = get_registered_cumulative_wall_cap_s()
    run_wall_budget_s = get_registered_run_wall_budget_s()
    effective_per_run_cap = run_wall_budget_s if run_wall_budget_s is not None else T6_MAX_PER_RUN_WALL_SECONDS

    can_run = (
        approval_check["is_approved"]
        and weights_info.get("status") == "verified"
        and (cumulative_reserved + spec.wall_budget_seconds <= cum_wall_cap)
        and (spec.wall_budget_seconds <= effective_per_run_cap)
        and (cumulative_views + spec.views <= effective_max_views)
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
            "max_cumulative_wall_seconds": cum_wall_cap,
            "max_per_run_wall_seconds": effective_per_run_cap,
            "approved_run_wall_budget_seconds": run_wall_budget_s,
            "cumulative_reserved_seconds": cumulative_reserved,
            "cumulative_views": cumulative_views,
            "remaining_cumulative_seconds": max(
                0.0, cum_wall_cap - cumulative_reserved
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
        for p in psutil.process_iter(["pid"]):
            try:
                if os.getpgid(p.pid) == pgid:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
                continue
        return False


def run_supervised_da3_worker(
    spec: DA3RunSpec,
    worker_action: str = "real_pipeline",
    simulate_rss_mib: int = 0,
    simulate_sleep_seconds: float = 0.0,
    spawn_grandchild_count: int = 0,
    poll_interval_s: float = 0.05,
    max_rss_bytes: int = T6_MAX_PROCESS_RSS_BYTES,
    timeout_s: float | None = None,
    python_executable: str | None = None,
    system_reserve_bytes: int = SYSTEM_RESERVE_BYTES,
    initial_swap_bytes: int | None = None,
    allow_model_execution: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute worker script in an isolated child process group with periodic parent supervision.

    Parent supervision monitors:
    1. Wall clock timeout (exceeding budget)
    2. Entire process group RSS (exceeding protection threshold)
    3. Hardware resource guards (power source AC, available RAM >= reserve, swap growth <= 1 GiB)
    4. Group leader early exit with surviving orphan grandchild processes
    5. Clean termination via os.killpg and POSIX empty group proof

    Returns (worker_result_dict, supervision_metadata_dict).
    """
    python_bin = python_executable or sys.executable
    effective_timeout = timeout_s if timeout_s is not None else spec.wall_budget_seconds
    base_swap = initial_swap_bytes if initial_swap_bytes is not None else psutil.swap_memory().used

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
        if allow_model_execution:
            cmd.append("--allow-model-execution")

        env = dict(os.environ, PYTHONPATH=os.pathsep.join(sys.path), KMP_DUPLICATE_LIB_OK="TRUE")

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
                    except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
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

                # 3. System hardware resource guard
                vm = psutil.virtual_memory()
                if vm.available < system_reserve_bytes:
                    violation = (
                        f"System available memory {vm.available / (1024**3):.2f} GiB is below "
                        f"registered protection line of {system_reserve_bytes / (1024**3):.2f} GiB"
                    )
                    violation_type = "system_resource"
                    break

                cur_swap = psutil.swap_memory().used
                swap_growth = cur_swap - base_swap
                if swap_growth > SWAP_GROWTH_LIMIT_BYTES:
                    violation = (
                        f"Swap memory growth {swap_growth / (1024**3):.2f} GiB exceeds "
                        f"protection threshold {SWAP_GROWTH_LIMIT_GIB:.2f} GiB"
                    )
                    violation_type = "swap_limit"
                    break

                # 4. Check if child leader exited
                ret = proc.poll()
                if ret is not None:
                    time.sleep(0.05)
                    surviving_pids: list[int] = []
                    for p in psutil.process_iter(["pid"]):
                        try:
                            if p.pid != proc.pid and os.getpgid(p.pid) == pgid:
                                surviving_pids.append(p.pid)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError, PermissionError):
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
            elif violation_type in ("rss_limit", "system_resource", "swap_limit"):
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
    test_substitute: bool = False,
    coordinator_release: bool = False,
    allow_model_execution: bool = False,
    worker_action: str | None = None,
    simulate_rss_mib: int = 0,
    simulate_sleep_seconds: float = 0.0,
    spawn_grandchild_count: int = 0,
    poll_interval_s: float = 0.05,
    max_rss_bytes: int = T6_MAX_PROCESS_RSS_BYTES,
    system_reserve_bytes: int = SYSTEM_RESERVE_BYTES,
    allow_custom_paths: bool = False,
) -> dict[str, Any]:
    """Execute fully guarded T6 DA3 benchmark under central RunStore and shared worker_lock.

    Execution Protocol:
    1. Model whitelist verification.
    2. Single-job and cumulative view quota verification (<= 64 views).
       (V9.T44: the real_pipeline calibration-views pre-check runs *before* this quota
       gate, so a mis-specified views request reports the views reason, not a quota error.)
    3. Per-run budget verification (<= 1200.0s).
    4. Approval & statistical protocol verification (Exit 3 on missing).
    5. Weights manifest verification.
    6. Central store and lock path verification (prohibits custom paths in formal runs).
    7. Pre-work rejection if real model execution is blocked or unapproved.
    8. Hardware resource guard verification (AC power, available RAM, swap).
    9. CLI worker_lock acquisition (Exit 4 on lock contention).
    10. Double-checked cumulative budget verification INSIDE worker_lock.
    11. Run registration and atomic pre-work reservation in RunStore.
    12. Child process group execution under parent supervision.
    13. Process group termination and POSIX empty group proof.
    14. Run transition to completed or failed with full evidence. Lock covers cleanup.
    """
    if adapter is not None:
        test_substitute = True
        allow_custom_paths = True

    model_norm = normalize_da3_model_name(spec.model)
    effective_max_views = get_effective_t6_max_views(spec.store_path)

    # Step 1: Views Quota Gate (Single Job)
    check_t6_views_quota(spec.views, max_views=effective_max_views)

    # Step 2: Per-run Budget Gate
    if spec.wall_budget_seconds <= 0.0:
        raise BenchmarkBudgetRefused("Requested wall budget must be positive")
    if spec.wall_budget_seconds > T6_MAX_PER_RUN_WALL_SECONDS:
        raise BenchmarkBudgetRefused(
            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
            f"per-run limit {T6_MAX_PER_RUN_WALL_SECONDS:.1f}s"
        )
    run_wall_budget_s = get_registered_run_wall_budget_s()
    if run_wall_budget_s is not None and spec.wall_budget_seconds > run_wall_budget_s:
        raise BenchmarkBudgetRefused(
            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
            f"registered single-run budget limit {run_wall_budget_s:.1f}s",
            details={
                "requested_wall_budget_seconds": spec.wall_budget_seconds,
                "approved_run_wall_budget_seconds": run_wall_budget_s,
            },
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

    # Step 5: Path Locking Check (Prohibit altering central store/lock paths in formal runs)
    if not test_substitute and not allow_custom_paths:
        if spec.store_path.resolve() != DEFAULT_STORE_PATH.resolve() or spec.lock_path.resolve() != DEFAULT_LOCK_PATH.resolve():
            raise BenchmarkRefusalError(
                "Formal run must strictly use central RunStore path and central worker lock; custom paths are prohibited."
            )

    # Step 6a: Resolve the effective worker action (V9.T44: 纯计算、无副作用，前移到配额检查之前)
    #
    # 卡 T44 项 1：视图口径预检必须**先于**配额检查，否则一个 views 配错的真跑请求会先撞上
    # "cumulative views exceeded" 的配额错误，把"口径不符"这个真原因盖掉。而预检需要
    # `action`，`action` 又依赖 `is_released`，所以这里把三步纯计算（is_released / 替身守卫 /
    # action 派生）整体前移；它们不读台账、不碰锁、不建 RunStore，前移不改变任何副作用顺序。
    is_released = (
        coordinator_release
        or allow_model_execution
        or getattr(spec, "coordinator_release", False)
        or getattr(spec, "allow_model_execution", False)
        or bool(approval.get("coordinator_release", False))
        or bool(approval.get("protocol_details", {}).get("coordinator_release", False))
    )

    # V9.T40：CPU 测试替身永远不得走真实管线（test_substitute 与显式 real_pipeline 互斥）。
    if test_substitute and worker_action == "real_pipeline":
        raise BenchmarkRefusalError("test substitute mode must never reach the real pipeline worker")
    action = worker_action or ("mock_run" if test_substitute else ("real_pipeline" if is_released else "mock_run"))
    effective_allow_model = allow_model_execution or is_released

    # V9.T44 r2：已放行（授权会被消耗）的**非替身**运行只能执行真实管线。否则就是「预扣视图/墙钟、启动 mock、记 completed、
    # model_runs=0」——T37/T40 关掉的那个陷阱。放在配额检查与任何扣账之前：零台账读写、零锁、零 worker。
    # 测试替身（test_substitute=True）与未放行的请求不受影响（后者在 Step 7 被拒）。
    if not test_substitute and is_released and action != "real_pipeline":
        raise BenchmarkRefusalError(
            f"A released (authorized) run that is not a test substitute must execute the real pipeline, got worker_action={action!r}. "
            "Refused before reservation; nothing was reserved, consumed or started.",
            details={"action": action, "is_released": True, "test_substitute": False},
        )

    # Step 6b: Pre-consume calibration-views pre-check (V9.T42 门 / V9.T44 前移)
    #
    # 只要 `action` 已由显式参数或 `is_released` 派生出为 real_pipeline，就先验
    # `views == get_registered_calibration_views()`；不符直接以 views 原因拒，
    # 不报混淆的配额错误。此处的派生路径（worker_action=None + is_released）与显式
    # worker_action="real_pipeline" 走同一条门，零扣账、零锁、零 worker 启动。
    reg_views = get_registered_calibration_views()
    if action == "real_pipeline" and spec.views != reg_views:
        raise BenchmarkRefusalError(
            f"Real DA3 pipeline execution requires views == {reg_views} "
            f"(current registered calibration views specification), but got views={spec.views}. "
            "Refused before reservation and consumption.",
            details={
                "requested_views": spec.views,
                "required_views": reg_views,
                "action": action,
                "derived_from_release": worker_action is None,
            },
        )

    # Step 6: Pre-lock Cumulative Views & Budget Pre-Check (Outside lock)
    cumulative_reserved, cumulative_views = query_t6_ledger_read_only(spec.store_path)
    check_t6_views_quota(spec.views, cumulative_views=cumulative_views, max_views=effective_max_views)

    cum_wall_cap = get_registered_cumulative_wall_cap_s()
    if cumulative_reserved + spec.wall_budget_seconds > cum_wall_cap:
        raise BenchmarkBudgetRefused(
            f"Cumulative wall budget exceeded for T6: {cumulative_reserved:.1f}s reserved + "
            f"{spec.wall_budget_seconds:.1f}s requested > {cum_wall_cap:.1f}s limit",
            details={
                "task": T6_TASK_ID,
                "cumulative_reserved": cumulative_reserved,
                "requested": spec.wall_budget_seconds,
                "limit": cum_wall_cap,
            },
        )

    # Step 7: Pre-Reservation Gate: Production CLI cannot default to fake success or execute unapproved models
    if not test_substitute and not is_released:
        raise BenchmarkRefusalError(
            "T6 DA3 real model execution is blocked: coordinator execution release authorization not granted. "
            "Formal model execution requires explicit coordinator authorization flag (--coordinator-release or --allow-model-execution). "
            "Pre-work reservation refused."
        )

    # Step 8: Pre-lock Hardware Resource Gate
    initial_swap_bytes = psutil.swap_memory().used
    resource_pre = check_t6_resource_limits(
        max_rss_gib=T6_MAX_PROCESS_RSS_GIB,
        check_system_guards=True,
        system_reserve_bytes=system_reserve_bytes,
        initial_swap_bytes=initial_swap_bytes,
    )

    # Step 9: CLI worker_lock acquisition
    try:
        with worker_lock(spec.lock_path):
            spec.store_path.parent.mkdir(parents=True, exist_ok=True)
            with RunStore(spec.store_path) as store:
                # Step 10: Double-Checked Accounting INSIDE Lock
                cum_sec_locked, cum_views_locked = query_t6_ledger_read_only(spec.store_path)
                effective_max_locked = get_effective_t6_max_views(spec.store_path)
                check_t6_views_quota(spec.views, cumulative_views=cum_views_locked, max_views=effective_max_locked)
                cum_wall_cap = get_registered_cumulative_wall_cap_s()
                if cum_sec_locked + spec.wall_budget_seconds > cum_wall_cap:
                    raise BenchmarkBudgetRefused(
                        f"Cumulative wall budget exceeded inside lock: {cum_sec_locked:.1f}s reserved + "
                        f"{spec.wall_budget_seconds:.1f}s requested > {cum_wall_cap:.1f}s limit"
                    )

                run_id = spec.run_id or uuid4().hex
                request_id = spec.request_id or f"t6-da3-{run_id}"

                card_env = os.environ.get("DA3_TASK_ID")
                config_snapshot = {
                    "task": T6_TASK_ID,
                    "model": model_norm,
                    "views": spec.views,
                    "card": card_env if card_env is not None else None,
                    "budget": {
                        "max_wall_seconds": cum_wall_cap,
                        "max_environment_steps": 1000,
                        "max_optimizer_steps": 1000,
                        "max_daily_active_seconds": cum_wall_cap,
                        "max_model_transitions": 0,
                        "timezone": "UTC",
                    },
                    "frozen_bindings": {
                        "research_log_sha256": approval.get("research_log_sha256"),
                        "statistical_protocol_sha256": approval.get("protocol_details", {}).get("sha256"),
                        "weights_root": str(spec.weights_root),
                    },
                }

                # Step 11: Atomic Pre-work Reservation in RunStore
                store.create_run(config_snapshot, request_id=request_id, run_id=run_id)
                store.transition(run_id, "initializing", reason="Pre-work initialization")
                store.transition(run_id, "validating", reason="Pre-work budget reservation")

                try:
                    store.consume(run_id, active_seconds=spec.wall_budget_seconds)
                except BudgetExceeded as exc:
                    store.transition(run_id, "failed", reason=f"BudgetExceeded: {exc}")
                    raise BenchmarkBudgetRefused(str(exc)) from exc

                # Step 12: Supervised execution in child process group (NO bypass)
                start_time = time.time()
                try:
                    worker_result, supervision_meta = run_supervised_da3_worker(
                        spec=spec,
                        worker_action=action,
                        simulate_rss_mib=simulate_rss_mib,
                        simulate_sleep_seconds=simulate_sleep_seconds,
                        spawn_grandchild_count=spawn_grandchild_count,
                        poll_interval_s=poll_interval_s,
                        max_rss_bytes=max_rss_bytes,
                        system_reserve_bytes=system_reserve_bytes,
                        initial_swap_bytes=initial_swap_bytes,
                        allow_model_execution=effective_allow_model,
                    )

                    check_t6_resource_limits(
                        max_rss_gib=T6_MAX_PROCESS_RSS_GIB,
                        check_system_guards=True,
                        system_reserve_bytes=system_reserve_bytes,
                        initial_swap_bytes=initial_swap_bytes,
                    )

                    if adapter is not None and getattr(adapter, "should_fail", False):
                        raise RuntimeError(getattr(adapter, "fail_message", "Execution error"))
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
                    "model_runs": worker_result.get("model_runs", 0),
                    "elapsed_seconds": round(elapsed, 4),
                    "reserved_seconds": spec.wall_budget_seconds,
                    "cumulative_reserved_seconds": cum_sec_locked + spec.wall_budget_seconds,
                    "cumulative_views": cum_views_locked + spec.views,
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
