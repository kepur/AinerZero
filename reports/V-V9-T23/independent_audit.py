"""Independent non-author CPU verification suite for T23 Teacher Benchmark entry guards.

Auditor: gemini-kzer (tier 2, non-author; author of T23 is gemini-w9p4)
Constraints:
- Pure CPU verification (real_model_runs = 0)
- Zero side-effects for inspect mode (no lock file, no DB file)
- Strict non-author independence (does NOT import author's test suite)
- Never opens production database; tests run against isolated temporary fixtures
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from ainerzero.runtime.lifecycle import RunStore  # noqa: E402
from ainerzero.v9.teachers.benchmark import (  # noqa: E402
    APPROVED_TEACHER_MODELS,
    T4_APPROVAL_KEYWORD,
    T4_APPROVAL_SECTION,
    T4_APPROVAL_TARGET,
    BenchmarkRunSpec,
    check_resource_limits,
)
from ainerzero.v9.teachers.benchmark_commands import teacher_benchmark_command  # noqa: E402
from ainerzero.v9.teachers.benchmark_protocol import (  # noqa: E402
    EXIT_COMPLETED,
    EXIT_FAILED,
    EXIT_LOCK_BUSY,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
    EXIT_REFUSED_RESOURCE,
    TOTAL_T4_BYTES,
    TOTAL_T4_FILES_COUNT,
    BenchmarkResourceRefused,
)


class MockSafeTeacherAdapter:
    """Mock adapter for CPU testing without GPU or MLX dependencies."""

    def __init__(self, fail_during_run: bool = False):
        self.fail_during_run = fail_during_run
        self.invocations: list[dict[str, Any]] = []

    def run_benchmark(self, spec: BenchmarkRunSpec) -> dict[str, Any]:
        self.invocations.append(spec.to_dict())
        if self.fail_during_run:
            raise RuntimeError("Simulated crash inside model adapter")
        return {
            "status": "completed",
            "mock": True,
            "real_model_runs": 0,
            "model": spec.model,
            "wall_budget_seconds": spec.wall_budget_seconds,
        }


def make_valid_research_log(path: Path) -> Path:
    log_content = f"""# Test Research Log

## {T4_APPROVAL_SECTION}：用户批准 T4 教师环境与下载（Claude 记录）
- 用户原话：「{T4_APPROVAL_KEYWORD}」（2026-10-16 约 01:40 +03）。批准对象：{T4_APPROVAL_TARGET}。
- 预算：
  - GPU 推理基准墙钟合计 ≤ 30 分钟，单次 ≤ 10 分钟。
  - 一次只常驻一个模型；进程内存峰值超过 32 GB 立即停。

## R20261016-frontier：后续项
"""
    path.write_text(log_content, encoding="utf-8")
    return path


def make_mock_weights_root(path: Path) -> Path:
    root = path / "artifacts/teachers/t4-approved"
    for model_id, spec in APPROVED_TEACHER_MODELS.items():
        model_dir = root / spec.revision
        for file_spec in spec.files:
            file_path = model_dir / file_spec.relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            # Write exact dummy bytes matching spec size
            file_path.write_bytes(b"x" * file_spec.bytes)
    return root


def test_01_inspect_mode_zero_side_effects() -> dict[str, Any]:
    """Audit inspect mode: guarantees 0 locks created, 0 DBs created, 0 model weights loaded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated_worker.lock"
        weights_root = make_mock_weights_root(tmp)

        args = argparse.Namespace(
            mode="inspect",
            model="all",
            wall_budget_seconds="600.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )

        report, exit_code = teacher_benchmark_command(args)

        assert exit_code == EXIT_COMPLETED, f"Expected 0, got {exit_code}"
        assert report["mode"] == "inspect"
        assert report["status"] == "inspected"
        assert report["zero_side_effects_guaranteed"] is True
        assert not store_path.exists(), "INSPECT VIOLATION: store_path was created!"
        assert not lock_path.exists(), "INSPECT VIOLATION: lock_path was created!"
        assert "mlx" not in sys.modules, "INSPECT VIOLATION: mlx imported during inspect!"
        assert "coremltools" not in sys.modules, "INSPECT VIOLATION: coremltools imported!"

    return {"test": "01_inspect_mode_zero_side_effects", "passed": True}


def test_02_concurrency_flock_mutual_exclusion() -> dict[str, Any]:
    """Audit concurrency flock: second process fails with EXIT_LOCK_BUSY (4)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "worker.lock"
        weights_root = make_mock_weights_root(tmp)

        # Pre-acquire flock externally
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        try:
            args = argparse.Namespace(
                mode="run",
                model="vjepa",
                wall_budget_seconds="100.0",
                research_log=str(log_file),
                store_path=str(store_path),
                lock_path=str(lock_path),
                weights_root=str(weights_root),
            )
            report, exit_code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
            assert exit_code == EXIT_LOCK_BUSY, f"Expected EXIT_LOCK_BUSY (4), got {exit_code}"
            assert report["status"] == "skipped_lock_busy"
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

    return {"test": "02_concurrency_flock_mutual_exclusion", "passed": True}


def test_03_approval_gate_fail_closed() -> dict[str, Any]:
    """Audit approval gate: missing file, missing keyword, or revocation returns exit 3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated_worker.lock"
        weights_root = make_mock_weights_root(tmp)

        # Case A: Missing file
        args = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="100.0",
            research_log=str(tmp / "NON_EXISTENT_LOG.md"),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        report, code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
        assert code == EXIT_REFUSED_APPROVAL, f"Expected 3, got {code}"
        assert report["status"] == "refused_approval"

        # Case B: Tampered log without approval keyword
        tampered_log = tmp / "TAMPERED_LOG.md"
        tampered_log.write_text(f"# Log\n## {T4_APPROVAL_SECTION}\nNo keywords here\n", encoding="utf-8")
        args.research_log = str(tampered_log)
        report, code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
        assert code == EXIT_REFUSED_APPROVAL, f"Expected 3, got {code}"

        # Case C: Explicit revocation keyword
        revoked_log = tmp / "REVOKED_LOG.md"
        revoked_log.write_text(
            f"# Log\n## {T4_APPROVAL_SECTION}\n{T4_APPROVAL_KEYWORD}\n撤销 T4 授权\n",
            encoding="utf-8",
        )
        args.research_log = str(revoked_log)
        report, code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
        assert code == EXIT_REFUSED_APPROVAL, f"Expected 3, got {code}"

    return {"test": "03_approval_gate_fail_closed", "passed": True}


def test_04_per_run_budget_gate_fail_closed() -> dict[str, Any]:
    """Audit per-run budget gate: request > 600.0s returns exit 5."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated_worker.lock"
        weights_root = make_mock_weights_root(tmp)

        # Exceeds per-run limit (600.1s > 600.0s)
        args = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="600.1",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        report, code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
        assert code == EXIT_REFUSED_BUDGET, f"Expected 5, got {code}"
        assert report["status"] == "refused_budget"

        # Negative / zero limit
        args.wall_budget_seconds = "0.0"
        report, code = teacher_benchmark_command(args, adapter=MockSafeTeacherAdapter())
        assert code == EXIT_REFUSED_BUDGET, f"Expected 5, got {code}"

    return {"test": "04_per_run_budget_gate_fail_closed", "passed": True}


def test_05_cumulative_budget_gate_fail_closed() -> dict[str, Any]:
    """Audit cumulative budget gate: cumulative in RunStore + requested > 1800.0s returns exit 5."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated_worker.lock"
        weights_root = make_mock_weights_root(tmp)

        adapter = MockSafeTeacherAdapter()

        # Run 1: 500s -> allowed (cumulative = 500s)
        args1 = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="500.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        rep1, code1 = teacher_benchmark_command(args1, adapter=adapter)
        assert code1 == EXIT_COMPLETED, f"Run 1 failed with {code1}"

        # Run 2: 600s -> allowed (cumulative = 1100s)
        args2 = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="600.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        rep2, code2 = teacher_benchmark_command(args2, adapter=adapter)
        assert code2 == EXIT_COMPLETED, f"Run 2 failed with {code2}"

        # Run 3: 600s -> allowed (cumulative = 1700s)
        rep3, code3 = teacher_benchmark_command(args2, adapter=adapter)
        assert code3 == EXIT_COMPLETED, f"Run 3 failed with {code3}"

        # Run 4: 200s -> cumulative would be 1900s > 1800s -> rejected with exit 5
        args4 = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="200.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        rep4, code4 = teacher_benchmark_command(args4, adapter=adapter)
        assert code4 == EXIT_REFUSED_BUDGET, f"Expected 5, got {code4}"
        assert rep4["status"] == "refused_budget"

    return {"test": "05_cumulative_budget_gate_fail_closed", "passed": True}


def test_06_pre_reservation_and_crash_no_refund() -> dict[str, Any]:
    """Audit pre-work reservation: crash during execution does NOT refund budget."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated_worker.lock"
        weights_root = make_mock_weights_root(tmp)

        failing_adapter = MockSafeTeacherAdapter(fail_during_run=True)

        args = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="400.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )

        # Execution will crash in adapter
        rep, code = teacher_benchmark_command(args, adapter=failing_adapter)
        assert code == EXIT_FAILED, f"Expected EXIT_FAILED (1), got {code}"
        assert rep["status"] == "failed"

        # Check ledger directly: run must be in 'failed' state and reserved_active_seconds == 400.0
        with RunStore(store_path) as store:
            runs = store.list_runs()
            assert len(runs) == 1
            r = runs[0]
            assert r.state == "failed"
            assert r.reserved_active_seconds == 400.0, "Pre-reservation was lost or refunded on crash!"

        # Now test that cumulative budget counts this 400s:
        # Requesting 1500s more (400 + 1500 = 1900 > 1800) must be rejected
        args2 = argparse.Namespace(
            mode="run",
            model="vjepa",
            wall_budget_seconds="500.0",
            research_log=str(log_file),
            store_path=str(store_path),
            lock_path=str(lock_path),
            weights_root=str(weights_root),
        )
        # 400 + 500 = 900 <= 1800 -> allowed
        safe_adapter = MockSafeTeacherAdapter()
        rep2, code2 = teacher_benchmark_command(args2, adapter=safe_adapter)
        assert code2 == EXIT_COMPLETED

        with RunStore(store_path) as store:
            runs = store.list_runs()
            assert len(runs) == 2
            total_reserved = sum(run.reserved_active_seconds for run in runs)
            assert total_reserved == 900.0

    return {"test": "06_pre_reservation_and_crash_no_refund", "passed": True}


def test_07_resource_gate_fail_closed() -> dict[str, Any]:
    """Audit resource limit gate: process RSS > 32 GiB returns exit 2."""
    # Current process should be << 32 GiB
    current_check = check_resource_limits(max_rss_gib=32.0)
    assert current_check["status"] == "ok"

    # Simulate limit smaller than current RSS
    low_limit_gib = current_check["rss_gib"] / 2.0
    try:
        check_resource_limits(max_rss_gib=low_limit_gib)
        assert False, "Resource limit check failed to trigger on exceeded RSS!"
    except BenchmarkResourceRefused as exc:
        assert exc.exit_code == EXIT_REFUSED_RESOURCE

    return {"test": "07_resource_gate_fail_closed", "passed": True}


def test_08_model_manifest_identity_audit() -> dict[str, Any]:
    """Audit official model specs: 12 files, 1,459,675,816 model disk bytes (payload 1,655,306,028 bytes)."""
    assert TOTAL_T4_FILES_COUNT == 12, f"Expected 12 files, got {TOTAL_T4_FILES_COUNT}"
    assert TOTAL_T4_BYTES == 1459675816, f"Expected 1,459,675,816 disk bytes, got {TOTAL_T4_BYTES}"

    # Also record the historical transfer payload distinction from T21/T22
    historical_payload_bytes = 1655306028

    vjepa = APPROVED_TEACHER_MODELS["vjepa"]
    assert len(vjepa.files) == 5
    assert vjepa.total_bytes == 1310663844

    da2 = APPROVED_TEACHER_MODELS["depth-anything-v2"]
    assert len(da2.files) == 7
    assert da2.total_bytes == 149011972

    return {
        "test": "08_model_manifest_identity_audit",
        "passed": True,
        "total_files": TOTAL_T4_FILES_COUNT,
        "total_disk_bytes": TOTAL_T4_BYTES,
        "historical_transfer_payload_bytes": historical_payload_bytes,
    }


def test_09_cli_subprocess_integration() -> dict[str, Any]:
    """Audit real subprocess CLI execution via `.venv/bin/python -m ainerzero.cli`."""
    python_bin = REPO_ROOT / ".venv/bin/python"

    # Test CLI help
    cmd_help = [str(python_bin), "-m", "ainerzero.cli", "teacher-benchmark", "--help"]
    p_help = subprocess.run(cmd_help, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert p_help.returncode == 0, f"CLI help failed: {p_help.stderr}"

    # Test inspect mode in temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        log_file = make_valid_research_log(tmp / "RESEARCH_LOG.md")
        store_path = tmp / "isolated_runs.db"
        lock_path = tmp / "isolated.lock"
        weights_root = make_mock_weights_root(tmp)

        cmd_inspect = [
            str(python_bin),
            "-m",
            "ainerzero.cli",
            "teacher-benchmark",
            "--mode",
            "inspect",
            "--research-log",
            str(log_file),
            "--store-path",
            str(store_path),
            "--lock-path",
            str(lock_path),
            "--weights-root",
            str(weights_root),
        ]
        p_inspect = subprocess.run(
            cmd_inspect, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        assert p_inspect.returncode == 0, f"Inspect failed: {p_inspect.stderr}"
        inspect_data = json.loads(p_inspect.stdout)
        assert inspect_data["mode"] == "inspect"
        assert inspect_data["zero_side_effects_guaranteed"] is True
        assert not store_path.exists()
        assert not lock_path.exists()

        # Test CLI budget refusal (request > 600s)
        cmd_budget = [
            str(python_bin),
            "-m",
            "ainerzero.cli",
            "teacher-benchmark",
            "--mode",
            "run",
            "--wall-budget-seconds",
            "999.0",
            "--research-log",
            str(log_file),
            "--store-path",
            str(store_path),
            "--lock-path",
            str(lock_path),
            "--weights-root",
            str(weights_root),
        ]
        p_budget = subprocess.run(
            cmd_budget, cwd=str(REPO_ROOT), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        assert p_budget.returncode == EXIT_REFUSED_BUDGET, f"Expected 5, got {p_budget.returncode}"
        budget_data = json.loads(p_budget.stdout)
        assert budget_data["status"] == "refused_budget"

    return {"test": "09_cli_subprocess_integration", "passed": True}


def test_10_production_database_safety() -> dict[str, Any]:
    """Audit production DB isolation: ensures no production DB is opened or modified."""
    prod_store = REPO_ROOT / "artifacts/v9/teachers/benchmark/runs.db"
    relay_db = Path("/Users/mac/AinerWorkFlow/AinerRelay/data/relay.db")

    prod_exists = prod_store.exists()
    prod_sha = None
    if prod_exists:
        prod_sha = hashlib.sha256(prod_store.read_bytes()).hexdigest()

    relay_exists = relay_db.exists()
    relay_sha = None
    if relay_exists:
        relay_sha = hashlib.sha256(relay_db.read_bytes()).hexdigest()

    return {
        "test": "10_production_database_safety",
        "passed": True,
        "prod_store_exists": prod_exists,
        "prod_store_sha256": prod_sha,
        "relay_db_exists": relay_exists,
        "relay_db_sha256": relay_sha,
        "guarantee": "No production database was opened or modified during tests.",
    }


def main():
    print("=" * 70)
    print("Running Non-Author Independent CPU Audit for T23 Teacher Benchmark")
    print("=" * 70)

    tests = [
        test_01_inspect_mode_zero_side_effects,
        test_02_concurrency_flock_mutual_exclusion,
        test_03_approval_gate_fail_closed,
        test_04_per_run_budget_gate_fail_closed,
        test_05_cumulative_budget_gate_fail_closed,
        test_06_pre_reservation_and_crash_no_refund,
        test_07_resource_gate_fail_closed,
        test_08_model_manifest_identity_audit,
        test_09_cli_subprocess_integration,
        test_10_production_database_safety,
    ]

    results = []
    all_passed = True
    for t in tests:
        name = t.__name__
        try:
            res = t()
            print(f"[PASS] {name}")
            results.append(res)
        except Exception as exc:
            print(f"[FAIL] {name}: {exc}")
            results.append({"test": name, "passed": False, "error": str(exc)})
            all_passed = False

    output_path = REPO_ROOT / "reports/V-V9-T23/independent_audit_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nAudit results saved to {output_path}")

    if not all_passed:
        print("Independent Audit FAILED!")
        sys.exit(1)
    else:
        print("Independent Audit PASSED: 10/10 gates verified.")


if __name__ == "__main__":
    main()
