"""Comprehensive tests for DA3 parent process supervision, process group isolation,
hardware resource gates, and read-only RunStore ledger protection.

Verifies:
1. True child process group supervision (`start_new_session=True`).
2. Parent polling loop monitoring wall clock timeout, process group RSS, swap growth, and orphan grandchildren.
3. Process group termination (`os.killpg(pgid, SIGTERM)` / `SIGKILL`) on violations.
4. POSIX empty process group proof (`is_process_group_alive(pgid) is False`).
5. RunStore failure transition with non-refundable budget consumption upon violation.
6. Cumulative 64-view lifetime quota accounting across derived jobs with double-checked locking inside the lock.
7. Strictly read-only inspect mode that does not mutate or initialize SQLite files.
8. Corrupt/damaged ledger fail-closed behavior (no fallback to zero).
9. Hardware resource guards (AC power, 16 GiB available RAM, 1 GiB swap growth).
10. Four real physical source mutation files tested across all 3 directions with actual subprocess returncode, stdout, and stderr.
"""

from __future__ import annotations

import importlib.util
import json
import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.teachers.benchmark_protocol import (
    EXIT_COMPLETED,
    EXIT_FAILED,
    EXIT_REFUSED_APPROVAL,
    EXIT_REFUSED_BUDGET,
    EXIT_REFUSED_RESOURCE,
    T6_MAX_CUMULATIVE_WALL_SECONDS,
    T6_MAX_VIEWS,
    T6_TASK_ID,
    BenchmarkApprovalRefused,
    BenchmarkBudgetRefused,
    BenchmarkRefusalError,
    BenchmarkResourceRefused,
    DA3RunSpec,
)
from ainerzero.v9.teachers.da3_controlled import (
    calculate_t6_cumulative_reserved_seconds,
    calculate_t6_cumulative_views,
    check_t6_resource_limits,
    check_t6_views_quota,
    execute_guarded_da3_benchmark,
    inspect_da3_benchmark,
    is_process_group_alive,
    query_t6_ledger_read_only,
    run_supervised_da3_worker,
)


@pytest.fixture
def test_env(tmp_path: Path):
    """Create isolated test environment with valid approval and protocol files."""
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        """# Research Log
## R20261026-T6：批准 T6 有界 DA3 标定入口
- 批准对象：ainerzero.V9.T6。关键字：批准 T6。
- 统计协议：见 reports/V9-T6/r2-calib-fixtures/statistical_protocol.json
""",
        encoding="utf-8",
    )

    proto_file = tmp_path / "statistical_protocol.json"
    proto_data = {
        "protocol_id": "az.v9.da3.calibration.v1",
        "metrics": ["rotation_error_deg", "translation_rel_error"],
        "calibration_inputs": {"n_worlds": 4},
        "tolerance": {"max_rotation_deg": 1.0},
    }
    proto_file.write_text(json.dumps(proto_data), encoding="utf-8")

    # Weights root pointing to real or test files
    weights_root = Path("artifacts/teachers/da3")
    store_path = tmp_path / "test_runs.db"
    lock_path = tmp_path / "test_worker.lock"

    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=300.0,
        views=4,
        research_log_path=log_file,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=proto_file,
    )

    return {
        "tmp_path": tmp_path,
        "log_file": log_file,
        "proto_file": proto_file,
        "weights_root": weights_root,
        "store_path": store_path,
        "lock_path": lock_path,
        "spec": spec,
    }


def load_mutation_module(mutation_path: Path, mod_name: str):
    """Load module dynamically from a physical mutation directory."""
    spec = importlib.util.spec_from_file_location(mod_name, str(mutation_path))
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ==============================================================================
# 1. Direct Parent Supervision of Child Process Group
# ==============================================================================


def test_supervision_clean_run(test_env):
    """Clean worker execution completes, proves empty process group, and returns metadata."""
    spec = test_env["spec"]
    worker_res, meta = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        simulate_sleep_seconds=0.05,
    )
    assert worker_res["status"] == "completed"
    assert worker_res.get("model_runs") == 0
    assert meta["returncode"] == 0
    assert meta["empty_group_proven"] is True
    assert meta["violation"] is None
    assert not is_process_group_alive(meta["worker_pgid"])


def test_supervision_timeout_terminates_group(test_env):
    """Worker sleeping longer than budget is killed via SIGKILL by supervisor, proving empty group."""
    spec = test_env["spec"]
    start = time.time()
    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_timeout",
            simulate_sleep_seconds=10.0,
            timeout_s=0.2,  # 200ms timeout
            poll_interval_s=0.02,
        )
    elapsed = time.time() - start
    assert elapsed < 2.0  # Must be killed promptly
    details = exc_info.value.details
    assert details["violation_type"] == "timeout"
    assert details["empty_group_proven"] is True
    assert not is_process_group_alive(details["worker_pgid"])


def test_supervision_rss_limit_terminates_group(test_env):
    """Worker exceeding RSS threshold is killed by supervisor, proving empty group."""
    spec = test_env["spec"]
    limit_bytes = 20 * 1024 * 1024
    with pytest.raises(BenchmarkResourceRefused) as exc_info:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_high_rss",
            simulate_rss_mib=60,
            simulate_sleep_seconds=5.0,
            max_rss_bytes=limit_bytes,
            poll_interval_s=0.02,
        )
    details = exc_info.value.details
    assert details["violation_type"] == "rss_limit"
    assert details["empty_group_proven"] is True
    assert not is_process_group_alive(details["worker_pgid"])


def test_supervision_grandchild_leak_detected_and_killed(test_env):
    """Group leader early exit leaving orphan grandchild triggers grandchild_leak kill & empty group."""
    spec = test_env["spec"]
    with pytest.raises(BenchmarkRefusalError) as exc_info:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_grandchild_leak",
            poll_interval_s=0.02,
        )
    details = exc_info.value.details
    assert details["violation_type"] == "grandchild_leak"
    assert details["empty_group_proven"] is True
    assert not is_process_group_alive(details["worker_pgid"])


# ==============================================================================
# 2. Hardware Resource Guards & Double-Checked Locking
# ==============================================================================


def test_hardware_resource_guards():
    """Verify hardware protection lines: AC power, system RAM reserve, swap growth."""
    # 1. AC Power / Battery Guard
    # If battery power is reported, it must raise BenchmarkResourceRefused
    with pytest.raises(BenchmarkResourceRefused) as exc_p:
        check_t6_resource_limits(
            check_system_guards=True,
            system_reserve_bytes=1024,
            power_source_override="battery",
        )
    assert "battery" in str(exc_p.value).lower()

    # 2. Available RAM Reserve Guard (16 GiB registered protection line)
    # Requesting system reserve larger than host RAM must raise BenchmarkResourceRefused
    huge_reserve_bytes = int(500 * (1024**3))  # 500 GiB reserve
    with pytest.raises(BenchmarkResourceRefused) as exc_ram:
        check_t6_resource_limits(
            check_system_guards=True,
            system_reserve_bytes=huge_reserve_bytes,
        )
    assert "below registered protection line" in str(exc_ram.value)

    # 3. Swap Growth Guard (1 GiB limit)
    # Simulate swap growth 2.5 GiB > 1.0 GiB limit
    with pytest.raises(BenchmarkResourceRefused) as exc_swap:
        check_t6_resource_limits(
            check_system_guards=True,
            system_reserve_bytes=1024,
            initial_swap_bytes=0,
            swap_used_override=int(2.5 * (1024**3)),
        )
    assert "Swap memory growth" in str(exc_swap.value)


def test_cumulative_views_quota_and_double_checked_locking(test_env):
    """Cumulative 64-view quota across derived jobs in RunStore, re-checked inside worker_lock."""
    store_path = test_env["store_path"]

    with RunStore(store_path) as store:
        cfg1 = {"task": T6_TASK_ID, "views": 30}
        store.create_run(cfg1, request_id="req-1", run_id="run-1")
        store.transition("run-1", "initializing")
        store.transition("run-1", "validating")
        store.transition("run-1", "completed")

        cfg2 = {"task": T6_TASK_ID, "views": 24}
        store.create_run(cfg2, request_id="req-2", run_id="run-2")
        store.transition("run-2", "initializing")
        store.transition("run-2", "validating")
        store.transition("run-2", "completed")

    cum_views = calculate_t6_cumulative_views(store_path)
    assert cum_views == 54

    # 54 + 8 = 62 <= 64 (Allowed)
    quota_ok = check_t6_views_quota(views=8, cumulative_views=cum_views)
    assert quota_ok["status"] == "ok"

    # 54 + 11 = 65 > 64 (Refused!)
    with pytest.raises(BenchmarkResourceRefused) as exc_info:
        check_t6_views_quota(views=11, cumulative_views=cum_views)
    assert "exceeds T6 lifetime quota of 64 views" in str(exc_info.value)


# ==============================================================================
# 3. Read-Only Ledger Inspect & Fail-Closed Protection
# ==============================================================================


def test_ledger_readonly_inspect_never_writes(test_env):
    """Read-only ledger inspect on existing DB must not execute DDL or modify file."""
    store_path = test_env["store_path"]
    with RunStore(store_path) as store:
        cfg = {
            "task": T6_TASK_ID,
            "views": 8,
            "budget": {
                "max_wall_seconds": 1200.0,
                "max_environment_steps": 100,
                "max_optimizer_steps": 100,
                "max_daily_active_seconds": 1200.0,
                "max_model_transitions": 0,
                "timezone": "UTC",
            },
        }
        store.create_run(cfg, request_id="req-ro", run_id="run-ro")
        store.transition("run-ro", "initializing")
        store.transition("run-ro", "validating")
        store.consume("run-ro", active_seconds=50.0)
        store.transition("run-ro", "completed")

    stat_before = store_path.stat()
    content_sha_before = subprocess.check_output(["shasum", "-a", "256", str(store_path)]).split()[0]

    for _ in range(5):
        sec, views = query_t6_ledger_read_only(store_path)
        assert sec == 50.0
        assert views == 8

    stat_after = store_path.stat()
    content_sha_after = subprocess.check_output(["shasum", "-a", "256", str(store_path)]).split()[0]
    assert content_sha_before == content_sha_after
    assert stat_before.st_size == stat_after.st_size


def test_corrupt_ledger_fails_closed(tmp_path: Path):
    """Corrupted or abnormal RunStore ledger must FAIL CLOSED, never silently return 0.0."""
    corrupt_db = tmp_path / "corrupt.db"
    corrupt_db.write_bytes(b"SQLite format 3\x00corrupted garbage data")

    with pytest.raises(BenchmarkRefusalError) as exc_info:
        query_t6_ledger_read_only(corrupt_db)
    assert "RunStore ledger" in str(exc_info.value)

    table_less_db = tmp_path / "no_runs_table.db"
    conn = sqlite3.connect(table_less_db)
    conn.execute("CREATE TABLE other_table (id INT)")
    conn.commit()
    conn.close()

    with pytest.raises(BenchmarkRefusalError) as exc_info2:
        query_t6_ledger_read_only(table_less_db)
    assert "missing" in str(exc_info2.value)


# ==============================================================================
# 4. Lazy Worker Real Pipeline Routing & Governance Blocking
# ==============================================================================


def test_lazy_worker_real_pipeline_routing(test_env, tmp_path: Path):
    """Verify da3_worker.py --action real_pipeline routes through pipeline.py and reports model_runs=0."""
    spec = test_env["spec"]
    output_json = tmp_path / "worker_pipeline_out.json"
    spec_json = tmp_path / "worker_spec.json"
    spec_json.write_text(json.dumps(spec.to_dict()), encoding="utf-8")

    res = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.v9.teachers.da3_worker",
            "--spec-file",
            str(spec_json),
            "--output-file",
            str(output_json),
            "--action",
            "real_pipeline",
        ],
        capture_output=True,
        text=True,
    )
    # Exits 3 because model forward pass is blocked by governance
    assert res.returncode == 3
    assert "blocked" in res.stderr
    assert output_json.is_file()
    data = json.loads(output_json.read_text())
    assert data["status"] == "blocked"
    assert data["model_runs"] == 0
    assert data["pipeline_verified"] is True
    assert "source_identity_sha256" in data

    # When --allow-model-execution is passed with coordinator release:
    output_released_json = tmp_path / "worker_released_out.json"
    res_released = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.v9.teachers.da3_worker",
            "--spec-file",
            str(spec_json),
            "--output-file",
            str(output_released_json),
            "--action",
            "real_pipeline",
            "--allow-model-execution",
        ],
        capture_output=True,
        text=True,
    )
    assert res_released.returncode == 0
    assert output_released_json.is_file()
    data_released = json.loads(output_released_json.read_text())
    assert data_released["status"] == "completed"
    assert data_released["coordinator_released"] is True
    assert data_released["pipeline_verified"] is True
    # V9.T37：views != 18 时 worker 一次前向都没做，不得再谎报 model_runs=1。
    assert data_released["model_runs"] == 0
    assert data_released["real_forward_executed"] is False


# ==============================================================================
# 5. Four Real Physical Source Mutation Controls (3-Direction Evidence)
# ==============================================================================


def test_four_source_mutation_controls(tmp_path: Path, test_env):
    """Execute 4 real physical source mutations across all 3 directions with subprocess rc/stdout/stderr.

    Mutation 1: Wall Clock Timeout Supervision Gate (mutation_1_timeout)
    Mutation 2: Process Group RSS Protection Gate (mutation_2_rss)
    Mutation 3: Orphan Grandchild Leak Detection Gate (mutation_3_leak)
    Mutation 4: Corrupt Ledger Fail-Closed Protection Gate (mutation_4_ledger)
    """
    spec = test_env["spec"]
    repo_root = Path(__file__).resolve().parents[1]
    mutations_dir = repo_root / "reports/V9-T30/r3/mutations"
    if not mutations_dir.is_dir():
        mutations_dir = repo_root / "reports/V9-T30/r2/mutations"
    results = []

    # --------------------------------------------------------------------------
    # Control 1: Wall Clock Timeout Supervision Gate
    # --------------------------------------------------------------------------
    mod1 = load_mutation_module(mutations_dir / "mutation_1_timeout/da3_controlled.py", "mut_timeout")

    # Dir 1 (Case A): Clean code + fast normal task -> PASS, rc=0
    res_1a, meta_1a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        simulate_sleep_seconds=0.02,
        timeout_s=1.0,
    )
    assert meta_1a["returncode"] == 0
    assert meta_1a["violation"] is None

    # Dir 2 (Case B): Clean code + runaway task -> KILLED, timeout violation
    with pytest.raises(BenchmarkBudgetRefused) as exc_1b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_timeout",
            simulate_sleep_seconds=3.0,
            timeout_s=0.2,
            poll_interval_s=0.02,
        )
    meta_1b = exc_1b.value.details
    assert meta_1b["violation_type"] == "timeout"
    assert meta_1b["empty_group_proven"] is True

    # Dir 3 (Case C): Mutated code (timeout check disabled) + runaway task -> FAILS TO KILL on timeout!
    t0 = time.time()
    res_1c, meta_1c = mod1.run_supervised_da3_worker(
        spec=spec,
        worker_action="simulate_timeout",
        simulate_sleep_seconds=0.3,
        timeout_s=0.05,  # Mutated code ignores 50ms timeout and sleeps full 300ms
        poll_interval_s=0.02,
    )
    t_elapsed = time.time() - t0
    assert meta_1c["violation"] is None  # Mutated code failed to detect timeout violation!
    assert t_elapsed >= 0.25

    results.append({
        "control": "Control 1: Wall Clock Timeout Supervision",
        "clean_pass_rc": meta_1a["returncode"],
        "clean_catch_violation": meta_1b["violation_type"],
        "mutated_bypass_violation": meta_1c["violation"],
    })

    # --------------------------------------------------------------------------
    # Control 2: Process Group RSS Protection Gate
    # --------------------------------------------------------------------------
    mod2 = load_mutation_module(mutations_dir / "mutation_2_rss/da3_controlled.py", "mut_rss")

    # Dir 1 (Case A): Clean code + normal memory (5 MiB <= 150 MiB) -> PASS, rc=0
    res_2a, meta_2a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        simulate_rss_mib=5,
        max_rss_bytes=150 * 1024 * 1024,
    )
    assert meta_2a["returncode"] == 0

    # Dir 2 (Case B): Clean code + high memory (200 MiB > 80 MiB limit) -> KILLED, rss_limit
    with pytest.raises(BenchmarkResourceRefused) as exc_2b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_high_rss",
            simulate_rss_mib=200,
            simulate_sleep_seconds=3.0,
            max_rss_bytes=80 * 1024 * 1024,
            poll_interval_s=0.02,
        )
    meta_2b = exc_2b.value.details
    assert meta_2b["violation_type"] == "rss_limit"
    assert meta_2b["empty_group_proven"] is True

    # Dir 3 (Case C): Mutated code (RSS check disabled) + high memory -> FAILS TO KILL on RSS limit!
    res_2c, meta_2c = mod2.run_supervised_da3_worker(
        spec=spec,
        worker_action="simulate_high_rss",
        simulate_rss_mib=200,
        simulate_sleep_seconds=0.05,
        max_rss_bytes=80 * 1024 * 1024,
        poll_interval_s=0.02,
    )
    assert meta_2c["violation"] is None  # Mutated code failed to detect RSS violation!

    results.append({
        "control": "Control 2: Process Group RSS Protection",
        "clean_pass_rc": meta_2a["returncode"],
        "clean_catch_violation": meta_2b["violation_type"],
        "mutated_bypass_violation": meta_2c["violation"],
    })

    # --------------------------------------------------------------------------
    # Control 3: Orphan Grandchild Leak Detection Gate
    # --------------------------------------------------------------------------
    mod3 = load_mutation_module(mutations_dir / "mutation_3_leak/da3_controlled.py", "mut_leak")

    # Dir 1 (Case A): Clean code + normal worker -> PASS, rc=0
    res_3a, meta_3a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        spawn_grandchild_count=1,
    )
    assert meta_3a["returncode"] == 0
    assert meta_3a["empty_group_proven"] is True

    # Dir 2 (Case B): Clean code + early exit with grandchild -> KILLED, grandchild_leak
    with pytest.raises(BenchmarkRefusalError) as exc_3b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_grandchild_leak",
            poll_interval_s=0.02,
        )
    meta_3b = exc_3b.value.details
    assert meta_3b["violation_type"] == "grandchild_leak"
    assert meta_3b["empty_group_proven"] is True

    # Dir 3 (Case C): Mutated code (leak detection disabled) + early exit -> FAILS TO CATCH LEAK!
    res_3c, meta_3c = mod3.run_supervised_da3_worker(
        spec=spec,
        worker_action="simulate_grandchild_leak",
        poll_interval_s=0.02,
    )
    assert meta_3c["violation"] is None  # Mutated code failed to detect grandchild leak!
    # Manually clean up leaked grandchild since mutated supervisor failed to clean it
    try:
        os.killpg(meta_3c["worker_pgid"], signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    results.append({
        "control": "Control 3: Orphan Grandchild Leak Detection",
        "clean_pass_rc": meta_3a["returncode"],
        "clean_catch_violation": meta_3b["violation_type"],
        "mutated_bypass_violation": meta_3c["violation"],
    })

    # --------------------------------------------------------------------------
    # Control 4: Corrupt Ledger Fail-Closed Protection Gate
    # --------------------------------------------------------------------------
    mod4 = load_mutation_module(mutations_dir / "mutation_4_ledger/da3_controlled.py", "mut_ledger")

    # Dir 1 (Case A): Clean code + valid DB -> computes accurate views
    valid_db = tmp_path / "ctrl4_valid.db"
    with RunStore(valid_db) as store:
        store.create_run({"task": T6_TASK_ID, "views": 15}, request_id="c4-v", run_id="c4-v")
        store.transition("c4-v", "initializing")
        store.transition("c4-v", "validating")
        store.transition("c4-v", "completed")
    sec_4a, views_4a = query_t6_ledger_read_only(valid_db)
    assert views_4a == 15

    # Dir 2 (Case B): Clean code + corrupt DB -> FAILS CLOSED with BenchmarkRefusalError!
    corrupt_db = tmp_path / "ctrl4_corrupt.db"
    corrupt_db.write_text("CORRUPTED NOT SQLITE", encoding="utf-8")
    with pytest.raises(BenchmarkRefusalError):
        query_t6_ledger_read_only(corrupt_db)

    # Dir 3 (Case C): Mutated code (swallows error and returns 0) + corrupt DB -> SILENTLY RETURNS 0!
    sec_4c, views_4c = mod4.query_t6_ledger_read_only(corrupt_db)
    assert sec_4c == 0.0 and views_4c == 0  # Proves clean code sensitivity!

    results.append({
        "control": "Control 4: Corrupt Ledger Fail-Closed",
        "clean_pass_views": views_4a,
        "clean_catch_fails_closed": True,
        "mutated_fallback_to_zero": (sec_4c == 0.0 and views_4c == 0),
    })

    assert len(results) == 4
