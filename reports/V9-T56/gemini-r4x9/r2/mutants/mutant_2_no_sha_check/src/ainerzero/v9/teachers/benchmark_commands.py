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
    coordinator_release = bool(
        getattr(args, "coordinator_release", False)
        or getattr(args, "allow_model_execution", False)
    )
    allow_model_execution = bool(getattr(args, "allow_model_execution", False))
    # V9.T44 (F-3)：CLI 选路只认**显式** `--coordinator-release`。
    # 上面的 `coordinator_release` 仍把 `--allow-model-execution` 折算进来，供 spec 字段与
    # 内层发布门（execute_guarded 的 is_released）使用；但"要不要真跑"的最后一道开关只保留
    # 一个输入，多一个能提升它的输入就多一条静默放宽路径。
    explicit_coordinator_release = bool(getattr(args, "coordinator_release", False))

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
        coordinator_release=coordinator_release,
        allow_model_execution=allow_model_execution,
    )

    test_substitute = getattr(args, "test_substitute", False) or (adapter is not None)

    try:
        if mode == "inspect":
            report = inspect_da3_benchmark(spec)
            return report, EXIT_COMPLETED
        elif mode == "run":
            if not test_substitute:
                if store_path != DEFAULT_STORE_PATH or lock_path != DEFAULT_LOCK_PATH:
                    raise BenchmarkRefusalError(
                        "Formal run must use central RunStore and central worker lock; custom paths are restricted to CPU testing with explicit isolation."
                    )
            # V9.T44 r2（一级 claude-az 打回后）：只给 `--allow-model-execution`、没给显式 `--coordinator-release`
            # 时，`coordinator_release` 已被折算为 True，内层发布门会放行并**预扣视图/墙钟**；若此时选路是 mock_run，
            # 就是「配额照扣、跑的是 mock、model_runs=0」。所以在任何预扣之前直接拒绝，并说明要补哪个 flag。
            if not test_substitute and allow_model_execution and not explicit_coordinator_release:
                raise BenchmarkRefusalError(
                    "--allow-model-execution alone cannot start a real DA3 run: also pass the explicit --coordinator-release. "
                    "Refused before reservation; nothing was reserved, consumed or started."
                )
            # V9.T42: CLI 在 test_substitute 下恒选 mock_run，即使带有 coordinator_release 亦同。
            # V9.T44 (F-3): real 分支只认显式 --coordinator-release；`or allow_model_execution`
            # 这一条**故意不写**——它是 T43 变异 M-B 的写法，写上去就等于静默放宽 CLI 门。
            worker_action = "mock_run" if test_substitute else (
                "real_pipeline" if explicit_coordinator_release else "mock_run"
            )
            report = execute_guarded_da3_benchmark(
                spec,
                adapter=adapter,
                test_substitute=test_substitute,
                coordinator_release=coordinator_release,
                allow_model_execution=allow_model_execution,
                allow_custom_paths=test_substitute,
                worker_action=worker_action,
            )
            # V9.T44: 选路结果在输出里可见，避免"用户以为真跑、实际拿到 mock"的静默降级。
            if isinstance(report, dict):
                report.setdefault("worker_action", worker_action)
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
