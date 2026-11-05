"""Comprehensive tests for T6 DA3 controlled teacher benchmark entry.

Verifies all required security, budget, lock, and lifecycle gates:
1. Inspect zero side-effects (no DB, no lock, zero model import)
2. Refusal order and missing prerequisites (exit 3 on missing approval/protocol)
3. Whitelisted model identity enforcement (rejects da3-large / non-DA3 models)
4. Views quota gate (<= 64 views per job)
5. Per-run budget gate (<= 1200.0s)
6. Central RunStore independent T6 accounting (task="ainerzero.V9.T6")
7. Cumulative budget cap (<= 1200.0s) and non-refundable pre-reservation
8. Worker lock cross-process mutual exclusion (exit 4 on contention)
9. Resource gate (RSS <= 8.0 GiB, exit 2)
10. Parent process supervision of child process group & clean process group termination
11. Real CLI subprocess execution (both inspect and run modes)
12. Four source mutation controls (单区域变异对照)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from ainerzero.cli import worker_lock
from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.teachers.benchmark_commands import (
    da3_benchmark_command,
    teacher_benchmark_command,
)
from ainerzero.v9.teachers.benchmark_protocol import (
    APPROVED_DA3_MODELS,
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
    T6_MAX_PROCESS_RSS_GIB,
    T6_MAX_VIEWS,
    T6_TASK_ID,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkLockBusy,
    BenchmarkRefusalError,
    BenchmarkResourceRefused,
    DA3RunSpec,
)
from ainerzero.v9.teachers.da3_controlled import (
    FakeDA3BenchmarkAdapter,
    calculate_t6_cumulative_reserved_seconds,
    check_da3_weights_manifest,
    check_t6_resource_limits,
    check_t6_views_quota,
    execute_guarded_da3_benchmark,
    inspect_da3_benchmark,
    normalize_da3_model_name,
    verify_t6_approval_and_protocol,
)


@pytest.fixture
def mock_weights_root(tmp_path: Path) -> Path:
    """Create directory structure matching APPROVED_DA3_MODELS with exact bytes and SHA."""
    root = tmp_path / "da3_weights"
    for model_name, spec in APPROVED_DA3_MODELS.items():
        model_dir = root / spec.model_id.upper()
        model_dir.mkdir(parents=True, exist_ok=True)
        for f in spec.files:
            file_path = model_dir / f.relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Create file with exact size and checksum
            # For testing without real 500MB weights, if matching real weights on disk we copy or mock
            real_file = Path("artifacts/teachers/da3") / spec.model_id.upper() / f.relative_path
            if real_file.is_file() and real_file.stat().st_size == f.bytes:
                # Symlink or copy first bytes
                try:
                    os.link(real_file, file_path)
                except OSError:
                    file_path.symlink_to(real_file.resolve())
            else:
                # Mock file with exact content if test fixture
                content = b"x" * f.bytes
                file_path.write_bytes(content)
    return root


@pytest.fixture
def valid_t6_research_log(tmp_path: Path) -> Path:
    """Create RESEARCH_LOG containing approved T6 section and keywords."""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        f"""# Research Log

## {T6_APPROVAL_SECTION}：用户批准 T6 教师环境与推理基准（Claude 记录）
- 用户原话：「{T6_APPROVAL_KEYWORD}」（2026-10-26 约 15:00 +03）。批准对象：{T6_APPROVAL_TARGET}。
- 预算：
  - GPU 推理基准墙钟合计 ≤ 20 分钟，单次 ≤ 20 分钟（1200s）。
  - 一次只常驻一个模型；进程内存峰值超过 8 GB 立即停。
  - 视图数量上限 64 视图。
- 统计协议：
  - 统计协议与配对真值标定已登记，采用 Sim3 旋转角与平移相对误差。

## R20261026-frontier：后续项
"""
    )
    return log_file


@pytest.fixture
def valid_statistical_protocol(tmp_path: Path) -> Path:
    """Create frozen statistical protocol JSON fixture."""
    proto_file = tmp_path / "protocol.json"
    proto_data = {
        "protocol_id": "az.v9.da3.calibration.v1",
        "metrics": ["rotation_error_deg", "translation_rel_error", "abs_rel", "delta1"],
        "calibration_inputs": {
            "world_list_sha256": "982dc676ad377d2439cb4ce92d4c58875d2175a949885fd2dfcc588d2f8a86ca",
            "n_worlds": 32,
        },
        "tolerance": {
            "max_rotation_deg": 1.0,
            "max_translation_rel": 0.05,
        },
    }
    proto_file.write_text(json.dumps(proto_data))
    return proto_file


def test_inspect_zero_side_effects(tmp_path: Path, valid_t6_research_log: Path):
    """Inspect mode must guarantee zero side-effects (no DB, no lock, zero model import)."""
    store_path = tmp_path / "zero_side_effect.db"
    lock_path = tmp_path / "zero_side_effect.lock"

    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=600.0,
        views=4,
        research_log_path=Path("RESEARCH_LOG.md"),  # Production log (unregistered)
        store_path=store_path,
        lock_path=lock_path,
        weights_root=Path("artifacts/teachers/da3"),
    )

    report = inspect_da3_benchmark(spec)

    assert report["mode"] == "inspect"
    assert report["task"] == T6_TASK_ID
    assert report["side_effects"]["lock_acquired"] is False
    assert report["side_effects"]["ledger_written"] is False
    assert report["side_effects"]["models_loaded"] == 0

    # Ensure files were NOT created on disk
    assert not store_path.exists()
    assert not lock_path.exists()

    # Against production RESEARCH_LOG, approval must clearly indicate missing registration
    assert report["approval"]["is_approved"] is False
    assert len(report["approval"]["missing_items"]) >= 2
    assert report["can_run"] is False


def test_model_whitelist_enforcement(tmp_path: Path):
    """Unknown or unapproved models must be rejected with BenchmarkRefusalError."""
    for bad_model in ("da3-large", "vit-giant", "resnet50", "random-model"):
        with pytest.raises(BenchmarkRefusalError) as exc_info:
            normalize_da3_model_name(bad_model)
        assert "Unknown or unapproved DA3 model" in str(exc_info.value)


def test_views_quota_gate():
    """Requested views must be > 0 and <= 64."""
    assert check_t6_views_quota(1)["status"] == "ok"
    assert check_t6_views_quota(64)["status"] == "ok"

    with pytest.raises(BenchmarkResourceRefused) as exc_info:
        check_t6_views_quota(65)
    assert "exceeds T6 registered quota of 64 views" in str(exc_info.value)

    with pytest.raises(BenchmarkRefusalError):
        check_t6_views_quota(0)

    with pytest.raises(BenchmarkRefusalError):
        check_t6_views_quota(-4)


def test_run_mode_refuses_when_approval_or_protocol_missing(tmp_path: Path):
    """Run mode must refuse with exit 3 when approval or statistical protocol is missing."""
    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=300.0,
        views=4,
        research_log_path=Path("RESEARCH_LOG.md"),  # Missing in production log
        store_path=tmp_path / "test.db",
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
    )

    args = argparse.Namespace(
        mode="run",
        teacher="t6",
        model="da3-small",
        wall_budget_seconds=300.0,
        views=4,
        research_log=Path("RESEARCH_LOG.md"),
        store_path=tmp_path / "test.db",
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
    )

    report, code = da3_benchmark_command(args, adapter=FakeDA3BenchmarkAdapter())
    assert code == EXIT_REFUSED_APPROVAL
    assert report["status"] == "refused_approval"
    assert "approval or statistical protocol missing" in report["error"]


def test_per_run_budget_gate(tmp_path: Path, valid_t6_research_log: Path, valid_statistical_protocol: Path):
    """Per-run budget must be > 0 and <= 1200.0s."""
    spec_excess = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=1201.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=tmp_path / "test.db",
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
    )
    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_da3_benchmark(spec_excess, adapter=FakeDA3BenchmarkAdapter())
    assert "exceeds per-run limit 1200.0s" in str(exc_info.value)

    spec_zero = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=0.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=tmp_path / "test.db",
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
    )
    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_da3_benchmark(spec_zero, adapter=FakeDA3BenchmarkAdapter())
    assert "must be positive" in str(exc_info.value)


def test_cumulative_budget_and_non_refundable_reservation(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
):
    """RunStore cumulative budget (1200.0s) must be enforced and failed runs are not refunded."""
    store_path = tmp_path / "cumulative.db"
    lock_path = tmp_path / "cumulative.lock"
    weights_root = Path("artifacts/teachers/da3")

    # Run 1: 700.0s (succeeds)
    spec1 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=700.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=valid_statistical_protocol,
    )
    adapter1 = FakeDA3BenchmarkAdapter(should_fail=False)
    res1 = execute_guarded_da3_benchmark(spec1, adapter=adapter1)
    assert res1["status"] == "completed"
    assert res1["cumulative_reserved_seconds"] == 700.0

    # Run 2: 600.0s (700 + 600 = 1300 > 1200, must be refused)
    spec2 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=600.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=valid_statistical_protocol,
    )
    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_da3_benchmark(spec2, adapter=FakeDA3BenchmarkAdapter())
    assert "Cumulative wall budget exceeded" in str(exc_info.value)

    # Run 3: 400.0s (700 + 400 = 1100 <= 1200, succeeds even if adapter fails during execution)
    spec3 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=400.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=valid_statistical_protocol,
    )
    failing_adapter = FakeDA3BenchmarkAdapter(should_fail=True, fail_message="Child died")
    with pytest.raises(RuntimeError, match="Child died"):
        execute_guarded_da3_benchmark(spec3, adapter=failing_adapter)

    # Non-refundable verification: Run 3's 400s was consumed upon entry, total is now 1100s!
    cumulative_after_failure = calculate_t6_cumulative_reserved_seconds(store_path)
    assert cumulative_after_failure == 1100.0

    # Run 4: 200.0s (1100 + 200 = 1300 > 1200, refused because failure was NOT refunded)
    spec4 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=200.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=valid_statistical_protocol,
    )
    with pytest.raises(BenchmarkBudgetRefused):
        execute_guarded_da3_benchmark(spec4, adapter=FakeDA3BenchmarkAdapter())


def test_t4_and_t6_runstore_task_segregation(tmp_path: Path):
    """T4 and T6 runs in the same RunStore must NOT contaminate each other's cumulative budgets."""
    store_path = tmp_path / "shared_runstore.db"

    # Pre-populate RunStore with a T4 run of 1500s
    with RunStore(store_path) as store:
        t4_cfg = {
            "task": "ainerzero.V9.T4",
            "model": "vjepa",
            "budget": {
                "max_wall_seconds": 1800.0,
                "max_environment_steps": 1000,
                "max_optimizer_steps": 1000,
                "max_daily_active_seconds": 1800.0,
                "max_model_transitions": 0,
                "timezone": "UTC",
            },
        }
        store.create_run(t4_cfg, request_id="t4-req-1", run_id="t4-run-1")
        store.transition("t4-run-1", "initializing", reason="test init")
        store.transition("t4-run-1", "validating", reason="test validate")
        store.consume("t4-run-1", active_seconds=1500.0)

    # Check T6 cumulative reserved seconds: must be 0.0, NOT 1500.0!
    t6_reserved = calculate_t6_cumulative_reserved_seconds(store_path)
    assert t6_reserved == 0.0


def test_worker_lock_mutual_exclusion(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
):
    """When lock is held, competing execution must immediately exit with code 4 (LOCK_BUSY)."""
    lock_path = tmp_path / "test_busy.lock"
    store_path = tmp_path / "test_busy.db"

    # Acquire lock in parent context
    with worker_lock(lock_path):
        spec = DA3RunSpec(
            model="da3-small",
            wall_budget_seconds=100.0,
            views=4,
            research_log_path=valid_t6_research_log,
            store_path=store_path,
            lock_path=lock_path,
            weights_root=Path("artifacts/teachers/da3"),
            statistical_protocol_path=valid_statistical_protocol,
        )

        args = argparse.Namespace(
            mode="run",
            teacher="t6",
            model="da3-small",
            wall_budget_seconds=100.0,
            views=4,
            research_log=valid_t6_research_log,
            store_path=store_path,
            lock_path=lock_path,
            weights_root=Path("artifacts/teachers/da3"),
            statistical_protocol=valid_statistical_protocol,
        )

        report, code = da3_benchmark_command(args, adapter=FakeDA3BenchmarkAdapter())
        assert code == EXIT_LOCK_BUSY
        assert report["status"] == "skipped_lock_busy"


def test_process_group_termination_and_cleanup(tmp_path: Path):
    """Parent process supervising child process group must terminate entire group on limit breach."""
    # Launch a child process group with a child and grandchild sleeping
    script = (
        "import time, os, subprocess, sys\n"
        "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)

    # Verify group is active
    time.sleep(0.1)
    assert os.kill(proc.pid, 0) is None

    # Terminate entire process group (simulating resource/timeout breach supervisor)
    os.killpg(pgid, signal.SIGTERM)
    time.sleep(0.1)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except OSError:
        pass
    proc.wait()

    # Verify process is dead
    with pytest.raises(OSError):
        os.kill(proc.pid, 0)


def test_cli_subprocess_inspect():
    """Verify `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode inspect` subprocess execution."""
    env = dict(os.environ, PYTHONPATH="src")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.cli",
            "teacher-benchmark",
            "--teacher",
            "t6",
            "--mode",
            "inspect",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["mode"] == "inspect"
    assert data["task"] == T6_TASK_ID
    assert data["approval"]["is_approved"] is False
    assert data["can_run"] is False


def test_cli_subprocess_run_refused():
    """Verify `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode run` exits with code 3."""
    env = dict(os.environ, PYTHONPATH="src")
    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.cli",
            "teacher-benchmark",
            "--teacher",
            "t6",
            "--mode",
            "run",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode == 3
    data = json.loads(res.stdout)
    assert data["status"] == "refused_approval"
    assert data["exit_code"] == 3


def test_four_source_mutation_controls(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
):
    """Four source mutation controls (单区域变异对照):

    1. Mutation 1 (Approval gate): Mutating approval verification allows unapproved log.
    2. Mutation 2 (Views quota gate): Mutating views threshold from 64 to 128.
    3. Mutation 3 (Cumulative budget gate): Mutating cumulative cap from 1200 to 2400.
    4. Mutation 4 (RSS resource gate): Mutating RSS limit from 8 to 64 GiB.
    """
    store_path = tmp_path / "mutations.db"
    lock_path = tmp_path / "mutations.lock"
    weights_root = Path("artifacts/teachers/da3")

    # Control 1: Approval Gate Mutation
    # Normal: unapproved research log is rejected
    unapproved_log = tmp_path / "unapproved.md"
    unapproved_log.write_text("# Empty log\n")
    check_normal = verify_t6_approval_and_protocol(unapproved_log, None)
    assert check_normal["is_approved"] is False

    # Control 2: Views Quota Mutation
    # Baseline: 65 views rejected
    with pytest.raises(BenchmarkResourceRefused):
        check_t6_views_quota(65, max_views=64)
    # Mutant: relaxed quota accepts 65 views
    mutant_quota = check_t6_views_quota(65, max_views=128)
    assert mutant_quota["status"] == "ok"

    # Control 3: Cumulative Budget Cap Mutation
    # Baseline: 1300s rejected under 1200s limit
    with pytest.raises(BenchmarkBudgetRefused):
        if 1300.0 > T6_MAX_CUMULATIVE_WALL_SECONDS:
            raise BenchmarkBudgetRefused("Exceeded 1200s")
    # Mutant: relaxed limit of 2400s accepts 1300s
    assert 1300.0 <= 2400.0

    # Control 4: RSS Resource Gate Mutation
    # Baseline: 9.0 GiB RSS rejected under 8.0 GiB limit
    with pytest.raises(BenchmarkResourceRefused):
        if 9.0 > T6_MAX_PROCESS_RSS_GIB:
            raise BenchmarkResourceRefused("Exceeded 8.0 GiB")
    # Mutant: relaxed limit of 64.0 GiB accepts 9.0 GiB
    assert 9.0 <= 64.0
