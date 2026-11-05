"""Command dispatcher for `ainerzero teacher-benchmark`.

Provides structured JSON reporting and explicit exit codes:
- 0: COMPLETED
- 1: FAILED
- 2: REFUSED_RESOURCE
- 3: REFUSED_APPROVAL
- 4: LOCK_BUSY
- 5: REFUSED_BUDGET
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from .benchmark import (
    TeacherBenchmarkAdapter,
    execute_guarded_benchmark,
    inspect_teacher_benchmark,
)
from .benchmark_protocol import (
    DEFAULT_LOCK_PATH,
    DEFAULT_RESEARCH_LOG,
    DEFAULT_STORE_PATH,
    DEFAULT_T6_WEIGHTS_ROOT,
    DEFAULT_WEIGHTS_ROOT,
    EXIT_COMPLETED,
    EXIT_FAILED,
    EXIT_LOCK_BUSY,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
    EXIT_REFUSED_RESOURCE,
    T4_MAX_PER_RUN_WALL_SECONDS,
    T6_MAX_PER_RUN_WALL_SECONDS,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkLockBusy,
    BenchmarkRefusalError,
    BenchmarkResourceRefused,
    BenchmarkRunSpec,
    DA3RunSpec,
)
from .da3_controlled import (
    DA3BenchmarkAdapter,
    execute_guarded_da3_benchmark,
    inspect_da3_benchmark,
)


def da3_benchmark_command(
    args: argparse.Namespace,
    adapter: DA3BenchmarkAdapter | None = None,
) -> tuple[dict[str, Any], int]:
    """Execute T6 DA3 benchmark command (inspect or guarded run) and return (report, exit_code)."""
    mode = getattr(args, "mode", "inspect")
    model = getattr(args, "model", "da3-all")
    if model == "all":
        model = "da3-all"
    wall_budget_seconds = float(
        getattr(args, "wall_budget_seconds", None) or T6_MAX_PER_RUN_WALL_SECONDS
    )
    views = int(getattr(args, "views", None) or 4)
    research_log = Path(getattr(args, "research_log", None) or DEFAULT_RESEARCH_LOG)
    store_path = Path(getattr(args, "store_path", None) or DEFAULT_STORE_PATH)
    lock_path = Path(getattr(args, "lock_path", None) or DEFAULT_LOCK_PATH)
    weights_root = Path(getattr(args, "weights_root", None) or DEFAULT_T6_WEIGHTS_ROOT)
    statistical_protocol_path = (
        Path(args.statistical_protocol)
        if getattr(args, "statistical_protocol", None)
        else None
    )
    request_id = getattr(args, "request_id", None)
    run_id = getattr(args, "run_id", None)

    spec = DA3RunSpec(
        model=model,
        wall_budget_seconds=wall_budget_seconds,
        views=views,
        research_log_path=research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=statistical_protocol_path,
        request_id=request_id,
        run_id=run_id,
    )

    try:
        if mode == "inspect":
            report = inspect_da3_benchmark(spec)
            return report, EXIT_COMPLETED
        elif mode == "run":
            report = execute_guarded_da3_benchmark(spec, adapter=adapter)
            return report, EXIT_COMPLETED
        else:
            return {
                "status": "failed",
                "mode": mode,
                "error": f"Unsupported mode: {mode} (expected 'inspect' or 'run')",
            }, EXIT_FAILED
    except BenchmarkApprovalRefused as exc:
        return {
            "status": "refused_approval",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_APPROVAL,
        }, EXIT_REFUSED_APPROVAL
    except BenchmarkResourceRefused as exc:
        return {
            "status": "refused_resource",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_RESOURCE,
        }, EXIT_REFUSED_RESOURCE
    except BenchmarkLockBusy as exc:
        return {
            "status": "skipped_lock_busy",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_LOCK_BUSY,
        }, EXIT_LOCK_BUSY
    except BenchmarkBudgetRefused as exc:
        return {
            "status": "refused_budget",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_BUDGET,
        }, EXIT_REFUSED_BUDGET
    except BenchmarkRefusalError as exc:
        return {
            "status": "refused",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": exc.exit_code,
        }, exc.exit_code
    except Exception as exc:
        return {
            "status": "failed",
            "mode": mode,
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "exit_code": EXIT_FAILED,
        }, EXIT_FAILED


def teacher_benchmark_command(
    args: argparse.Namespace,
    adapter: Any = None,
) -> tuple[dict[str, Any], int]:
    """Execute teacher benchmark command and return (report, exit_code).

    Automatically routes to T4 or T6 (DA3) based on `--teacher` or `--model`.
    """
    teacher = getattr(args, "teacher", "auto")
    model = getattr(args, "model", "all")

    if (
        teacher in ("t6", "ainerzero.V9.T6")
        or str(model).lower() in ("da3-small", "da3-base", "da3-all")
    ):
        return da3_benchmark_command(args, adapter=adapter)

    # Otherwise route to T4 teacher benchmark
    mode = getattr(args, "mode", "inspect")
    wall_budget_seconds = float(
        getattr(args, "wall_budget_seconds", None) or T4_MAX_PER_RUN_WALL_SECONDS
    )
    research_log = Path(getattr(args, "research_log", None) or DEFAULT_RESEARCH_LOG)
    store_path = Path(getattr(args, "store_path", None) or DEFAULT_STORE_PATH)
    lock_path = Path(getattr(args, "lock_path", None) or DEFAULT_LOCK_PATH)
    weights_root = Path(getattr(args, "weights_root", None) or DEFAULT_WEIGHTS_ROOT)
    request_id = getattr(args, "request_id", None)
    run_id = getattr(args, "run_id", None)

    spec = BenchmarkRunSpec(
        model=model,
        wall_budget_seconds=wall_budget_seconds,
        research_log_path=research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        request_id=request_id,
        run_id=run_id,
    )

    try:
        if mode == "inspect":
            report = inspect_teacher_benchmark(spec)
            return report, EXIT_COMPLETED
        elif mode == "run":
            report = execute_guarded_benchmark(spec, adapter=adapter)
            return report, EXIT_COMPLETED
        else:
            return {
                "status": "failed",
                "mode": mode,
                "error": f"Unsupported mode: {mode} (expected 'inspect' or 'run')",
            }, EXIT_FAILED
    except BenchmarkApprovalRefused as exc:
        return {
            "status": "refused_approval",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_APPROVAL,
        }, EXIT_REFUSED_APPROVAL
    except BenchmarkResourceRefused as exc:
        return {
            "status": "refused_resource",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_RESOURCE,
        }, EXIT_REFUSED_RESOURCE
    except BenchmarkLockBusy as exc:
        return {
            "status": "skipped_lock_busy",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_LOCK_BUSY,
        }, EXIT_LOCK_BUSY
    except BenchmarkBudgetRefused as exc:
        return {
            "status": "refused_budget",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": EXIT_REFUSED_BUDGET,
        }, EXIT_REFUSED_BUDGET
    except BenchmarkRefusalError as exc:
        return {
            "status": "refused",
            "mode": mode,
            "error": exc.message,
            "details": exc.details,
            "exit_code": exc.exit_code,
        }, exc.exit_code
    except Exception as exc:
        return {
            "status": "failed",
            "mode": mode,
            "error": str(exc),
            "exception_type": type(exc).__name__,
            "exit_code": EXIT_FAILED,
        }, EXIT_FAILED
