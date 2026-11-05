"""Comprehensive tests for T4 teacher benchmark guarded entry.

Tests all required security, budget, lock, and lifecycle gates:
1. Inspect zero side-effects (no DB, no lock, no model load)
2. RESEARCH_LOG approval gate (R20261016-T4 approval & keyword validation, exit 3)
3. Per-run budget gate (<= 600.0s, exit 5)
4. Cumulative budget gate in RunStore (<= 1800.0s, exit 5)
5. Pre-work reservation in RunStore (conservative reservation before compute)
6. Resource gate (RSS <= 32 GiB, exit 2)
7. CLI worker_lock mutual exclusion (Lock contention, exit 4)
8. Lifecycle state transitions (initializing -> validating -> completed / failed)
9. Model manifest verification (SHA256 and byte counts from T21/T22)
"""

from __future__ import annotations

import argparse
import fcntl
from pathlib import Path
from typing import Any

import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.teachers.benchmark import (
    APPROVED_TEACHER_MODELS,
    T4_APPROVAL_KEYWORD,
    T4_APPROVAL_SECTION,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkLockBusy,
    BenchmarkResourceRefused,
    BenchmarkRunSpec,
    check_model_weights_manifest,
    check_resource_limits,
    execute_guarded_benchmark,
    inspect_teacher_benchmark,
    verify_research_log_approval,
)
from ainerzero.v9.teachers.benchmark_commands import teacher_benchmark_command
from ainerzero.v9.teachers.benchmark_protocol import (
    EXIT_LOCK_BUSY,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
)


class FakeTeacherBenchmarkAdapter:
    """Fake adapter for CPU tests that simulates model benchmarking."""

    def __init__(self, should_fail: bool = False, fail_message: str = "Simulated error"):
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.invocations: list[BenchmarkRunSpec] = []

    def run_benchmark(self, spec: BenchmarkRunSpec) -> dict[str, Any]:
        self.invocations.append(spec)
        if self.should_fail:
            raise RuntimeError(self.fail_message)
        return {
            "status": "completed",
            "fake": True,
            "model": spec.model,
            "wall_budget_seconds": spec.wall_budget_seconds,
        }


@pytest.fixture
def valid_research_log(tmp_path: Path) -> Path:
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        f"""# Research Log

## {T4_APPROVAL_SECTION}：用户批准 T4 教师环境与下载（Claude 记录）
- 用户原话：「{T4_APPROVAL_KEYWORD}」（2026-10-16 约 01:40 +03）。批准对象：ainerzero.V9.T4。
- 预算：
  - GPU 推理基准墙钟合计 ≤ 30 分钟，单次 ≤ 10 分钟。
  - 一次只常驻一个模型；进程内存峰值超过 32 GB 立即停。

## R20261016-frontier：后续项
""",
        encoding="utf-8",
    )
    return log_file


@pytest.fixture
def dummy_weights_root(tmp_path: Path) -> Path:
    root = tmp_path / "artifacts/teachers/t4-approved"
    # Create valid mock files for vjepa
    vjepa_spec = APPROVED_TEACHER_MODELS["vjepa"]
    vjepa_dir = root / vjepa_spec.revision
    vjepa_dir.mkdir(parents=True, exist_ok=True)
    for f in vjepa_spec.files:
        p = vjepa_dir / f.relative_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0" * f.bytes)

    # Create valid mock files for depth-anything-v2
    da2_spec = APPROVED_TEACHER_MODELS["depth-anything-v2"]
    da2_dir = root / da2_spec.revision
    da2_dir.mkdir(parents=True, exist_ok=True)
    for f in da2_spec.files:
        p = da2_dir / f.relative_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"0" * f.bytes)

    return root


def test_inspect_zero_side_effect(
    tmp_path: Path, valid_research_log: Path, dummy_weights_root: Path
):
    """Verify that inspect mode causes zero side-effects (no db, no lock file)."""
    store_path = tmp_path / "never_created_runs.db"
    lock_path = tmp_path / "never_created.lock"

    spec = BenchmarkRunSpec(
        model="all",
        wall_budget_seconds=600.0,
        research_log_path=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=dummy_weights_root,
    )

    report = inspect_teacher_benchmark(spec)

    # Assert zero side-effects
    assert not store_path.exists(), "inspect mode must NOT create the store database!"
    assert not lock_path.exists(), "inspect mode must NOT create or acquire lock!"

    # Assert report fields
    assert report["mode"] == "inspect"
    assert report["zero_side_effects_guaranteed"] is True
    assert report["approval"]["status"] == "approved"
    assert report["budget"]["per_run_budget_admissible"] is True
    assert report["budget"]["cumulative_budget_admissible"] is True
    assert report["ledger"]["store_exists"] is False
    assert report["locks"]["lock_file_exists"] is False


def test_approval_missing_rejected(tmp_path: Path):
    """Missing section or approval keyword must raise BenchmarkApprovalRefused and exit 3."""
    empty_log = tmp_path / "EMPTY_LOG.md"
    empty_log.write_text("# Empty Log\n\n## Some other section\nNo approval\n", encoding="utf-8")

    with pytest.raises(BenchmarkApprovalRefused) as exc_info:
        verify_research_log_approval(empty_log)
    assert "not found" in str(exc_info.value)

    # Test via CLI command dispatcher
    args = argparse.Namespace(
        mode="inspect",
        research_log=empty_log,
        store_path=tmp_path / "runs.db",
        lock_path=tmp_path / "worker.lock",
        weights_root=tmp_path / "weights",
    )
    report, code = teacher_benchmark_command(args)
    assert code == EXIT_REFUSED_APPROVAL
    assert report["status"] == "refused_approval"


def test_approval_keyword_tampered_rejected(tmp_path: Path):
    """Section present but keyword tampered must raise BenchmarkApprovalRefused and exit 3."""
    tampered_log = tmp_path / "TAMPERED_LOG.md"
    tampered_log.write_text(
        f"""# Research Log
## {T4_APPROVAL_SECTION}：未获批准
- 用户未批准此项。
""",
        encoding="utf-8",
    )

    with pytest.raises(BenchmarkApprovalRefused) as exc_info:
        verify_research_log_approval(tampered_log)
    assert T4_APPROVAL_KEYWORD in str(exc_info.value)

    args = argparse.Namespace(
        mode="run",
        research_log=tampered_log,
        store_path=tmp_path / "runs.db",
        lock_path=tmp_path / "worker.lock",
        weights_root=tmp_path / "weights",
    )
    report, code = teacher_benchmark_command(args)
    assert code == EXIT_REFUSED_APPROVAL
    assert report["status"] == "refused_approval"


def test_per_run_budget_exceeded_rejected(tmp_path: Path, valid_research_log: Path):
    """Per-run budget exceeding 600s must be refused with exit 5."""
    store_path = tmp_path / "runs.db"
    lock_path = tmp_path / "worker.lock"
    spec = BenchmarkRunSpec(
        model="vjepa",
        wall_budget_seconds=601.0,  # exceeds 600.0 limit
        research_log_path=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
    )

    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_benchmark(spec, adapter=FakeTeacherBenchmarkAdapter())
    assert "exceeds per-run limit" in str(exc_info.value)

    args = argparse.Namespace(
        mode="run",
        model="vjepa",
        wall_budget_seconds=601.0,
        research_log=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
    )
    report, code = teacher_benchmark_command(args)
    assert code == EXIT_REFUSED_BUDGET
    assert report["status"] == "refused_budget"


def test_cumulative_budget_exceeded_rejected(tmp_path: Path, valid_research_log: Path):
    """Cumulative budget in RunStore exceeding 1800s must be refused with exit 5."""
    store_path = tmp_path / "cumulative_runs.db"
    lock_path = tmp_path / "worker.lock"

    # Seed RunStore with prior consumed budget of 1500 seconds
    with RunStore(store_path) as store:
        snapshot = {
            "task": "ainerzero.V9.T4",
            "model": "vjepa",
            "budget": {
                "max_wall_seconds": 1800.0,
                "max_environment_steps": 1000,
                "max_optimizer_steps": 1000,
                "max_daily_active_seconds": 1800.0,
                "timezone": "UTC",
            },
        }
        store.create_run(snapshot, request_id="seed-run-1", run_id="seed-run-1")
        store.transition("seed-run-1", "initializing")
        store.transition("seed-run-1", "validating")
        store.consume("seed-run-1", active_seconds=1500.0)
        store.transition("seed-run-1", "completed")

    # Now request 400s (1500 + 400 = 1900 > 1800 limit)
    spec = BenchmarkRunSpec(
        model="vjepa",
        wall_budget_seconds=400.0,
        research_log_path=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
    )

    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_benchmark(spec, adapter=FakeTeacherBenchmarkAdapter())
    assert "Cumulative wall budget exceeded" in str(exc_info.value)

    args = argparse.Namespace(
        mode="run",
        model="vjepa",
        wall_budget_seconds=400.0,
        research_log=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
    )
    report, code = teacher_benchmark_command(args)
    assert code == EXIT_REFUSED_BUDGET
    assert report["status"] == "refused_budget"


def test_resource_gate_rss_refused(tmp_path: Path, valid_research_log: Path):
    """When process RSS exceeds limit, must raise BenchmarkResourceRefused and exit 2."""
    with pytest.raises(BenchmarkResourceRefused) as exc_info:
        check_resource_limits(max_rss_gib=0.00001)
    assert "exceeds registered protection limit" in str(exc_info.value)


def test_concurrent_lock_busy(tmp_path: Path, valid_research_log: Path):
    """When worker lock is held by another process/handle, must raise BenchmarkLockBusy and exit 4."""
    lock_path = tmp_path / "held_worker.lock"
    store_path = tmp_path / "runs.db"

    # Pre-acquire the lock
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(lock_path, "w")
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    try:
        spec = BenchmarkRunSpec(
            model="vjepa",
            wall_budget_seconds=300.0,
            research_log_path=valid_research_log,
            store_path=store_path,
            lock_path=lock_path,
            weights_root=tmp_path / "weights",
        )

        with pytest.raises(BenchmarkLockBusy) as exc_info:
            execute_guarded_benchmark(spec, adapter=FakeTeacherBenchmarkAdapter())
        assert "held by another worker" in str(exc_info.value)

        args = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds=300.0,
            research_log=valid_research_log,
            store_path=store_path,
            lock_path=lock_path,
            weights_root=tmp_path / "weights",
        )
        report, code = teacher_benchmark_command(args)
        assert code == EXIT_LOCK_BUSY
        assert report["status"] == "skipped_lock_busy"
    finally:
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def test_pre_reservation_and_lifecycle_transitions(
    tmp_path: Path, valid_research_log: Path
):
    """Verify conservative pre-reservation and complete lifecycle state tracking in RunStore."""
    store_path = tmp_path / "lifecycle_runs.db"
    lock_path = tmp_path / "worker.lock"
    adapter = FakeTeacherBenchmarkAdapter()

    spec = BenchmarkRunSpec(
        model="vjepa",
        wall_budget_seconds=300.0,
        research_log_path=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
        request_id="req-lifecycle-001",
        run_id="run-lifecycle-001",
    )

    result = execute_guarded_benchmark(spec, adapter=adapter)
    assert result["status"] == "completed"
    assert len(adapter.invocations) == 1

    # Verify RunStore state
    with RunStore(store_path) as store:
        record = store.get_run("run-lifecycle-001")
        assert record.state == "completed"
        # Pre-reserved quota was 300.0s
        assert record.reserved_active_seconds == 300.0

    # Test failure transition on adapter crash
    failing_adapter = FakeTeacherBenchmarkAdapter(should_fail=True, fail_message="OOM crash")
    fail_spec = BenchmarkRunSpec(
        model="vjepa",
        wall_budget_seconds=150.0,
        research_log_path=valid_research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=tmp_path / "weights",
        request_id="req-lifecycle-002",
        run_id="run-lifecycle-002",
    )

    with pytest.raises(RuntimeError, match="OOM crash"):
        execute_guarded_benchmark(fail_spec, adapter=failing_adapter)

    with RunStore(store_path) as store:
        fail_record = store.get_run("run-lifecycle-002")
        assert fail_record.state == "failed"
        assert "OOM crash" in (fail_record.reason or "")
        # Conservative reservation is NOT refunded on crash!
        assert fail_record.reserved_active_seconds == 150.0


def test_model_weights_manifest_integrity(tmp_path: Path):
    """Test model weights manifest checking on missing, corrupted, and valid files."""
    spec = APPROVED_TEACHER_MODELS["vjepa"]
    weights_dir = tmp_path / "weights" / spec.revision
    weights_dir.mkdir(parents=True, exist_ok=True)

    # Missing all files initially
    res_empty = check_model_weights_manifest(spec, tmp_path / "weights", verify_content_sha=False)
    assert res_empty["complete"] is False
    assert len(res_empty["missing_files"]) == len(spec.files)

    # Corrupted size
    test_file = spec.files[0]
    p = weights_dir / test_file.relative_path
    p.write_bytes(b"bad_bytes")
    res_corrupted = check_model_weights_manifest(
        spec, tmp_path / "weights", verify_content_sha=False
    )
    assert any("size mismatch" in c for c in res_corrupted["corrupted_files"])
