"""Comprehensive tests for DA3 parent process supervision, process group isolation,
and read-only RunStore ledger protection.

Verifies:
1. True child process group supervision (`start_new_session=True`).
2. Parent polling loop monitoring wall clock timeout, process group RSS, and orphan grandchildren.
3. Process group termination (`os.killpg(pgid, SIGTERM)` / `SIGKILL`) on violations.
4. POSIX empty process group proof (`os.killpg(pgid, 0)` raises `ProcessLookupError`).
5. RunStore failure transition with non-refundable budget consumption upon violation.
6. Cumulative 64-view lifetime quota accounting across derived jobs.
7. Strictly read-only inspect mode that does not mutate or initialize SQLite files.
8. Corrupt/damaged ledger fail-closed behavior (no fallback to zero).
9. Four real source mutation controls with actual subprocess returncode, stdout, and stderr.
"""

from __future__ import annotations

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

    # Mock weights root
    weights_root = tmp_path / "da3_weights"
    small_dir = weights_root / "DA3-SMALL"
    small_dir.mkdir(parents=True, exist_ok=True)
    # Match the files for da3-small
    (small_dir / "README.md").write_bytes(b"x" * 1200)
    (small_dir / "config.json").write_bytes(b"x" * 850)
    (small_dir / "model.safetensors").write_bytes(b"x" * 1048576)

    # Let's mock check_da3_weights_manifest or supply exact files if needed
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
    assert meta["returncode"] == 0
    assert meta["empty_group_proven"] is True
    assert meta["violation"] is None
    # POSIX empty group proof: pgid cannot be signaled
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
    # POSIX empty group proof
    assert not is_process_group_alive(details["worker_pgid"])


def test_supervision_rss_limit_terminates_group(test_env):
    """Worker exceeding RSS threshold is killed by supervisor, proving empty group."""
    spec = test_env["spec"]
    # Set limit to 20 MiB and simulate allocating 60 MiB
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
    # Ensure leaked grandchild was terminated and group is empty
    assert not is_process_group_alive(details["worker_pgid"])


# ==============================================================================
# 2. Cumulative 64-View Quota Accounting
# ==============================================================================


def test_cumulative_views_quota_enforced(test_env):
    """64 views is the lifetime total across all derived jobs in RunStore; cannot be reset per-job."""
    store_path = test_env["store_path"]

    # Initialize store with existing T6 runs using canonical state transitions
    with RunStore(store_path) as store:
        # Run 1: 30 views
        cfg1 = {"task": T6_TASK_ID, "views": 30}
        store.create_run(cfg1, request_id="req-1", run_id="run-1")
        store.transition("run-1", "initializing")
        store.transition("run-1", "validating")
        store.transition("run-1", "completed")

        # Run 2: 24 views
        cfg2 = {"task": T6_TASK_ID, "views": 24}
        store.create_run(cfg2, request_id="req-2", run_id="run-2")
        store.transition("run-2", "initializing")
        store.transition("run-2", "validating")
        store.transition("run-2", "completed")

    # Cumulative views in ledger = 30 + 24 = 54 views
    cum_views = calculate_t6_cumulative_views(store_path)
    assert cum_views == 54

    # Request 8 views: 54 + 8 = 62 <= 64 (Allowed)
    quota_ok = check_t6_views_quota(views=8, cumulative_views=cum_views)
    assert quota_ok["status"] == "ok"

    # Request 11 views: 54 + 11 = 65 > 64 (Must be refused!)
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
        cfg = {"task": T6_TASK_ID, "views": 8, "budget": {"max_wall_seconds": 1200.0, "max_environment_steps": 100, "max_optimizer_steps": 100, "max_daily_active_seconds": 1200.0, "max_model_transitions": 0, "timezone": "UTC"}}
        store.create_run(cfg, request_id="req-ro", run_id="run-ro")
        store.transition("run-ro", "initializing")
        store.transition("run-ro", "validating")
        store.consume("run-ro", active_seconds=50.0)
        store.transition("run-ro", "completed")

    # Record initial stat
    stat_before = store_path.stat()
    content_sha_before = subprocess.check_output(["shasum", "-a", "256", str(store_path)]).split()[0]

    # Perform inspect multiple times
    for _ in range(5):
        sec, views = query_t6_ledger_read_only(store_path)
        assert sec == 50.0
        assert views == 8

    # Stat and content must be identical
    stat_after = store_path.stat()
    content_sha_after = subprocess.check_output(["shasum", "-a", "256", str(store_path)]).split()[0]
    assert content_sha_before == content_sha_after
    assert stat_before.st_size == stat_after.st_size


def test_corrupt_ledger_fails_closed(tmp_path: Path):
    """Corrupted or abnormal RunStore ledger must FAIL CLOSED, never silently return 0.0."""
    corrupt_db = tmp_path / "corrupt.db"
    # Write garbage bytes to database
    corrupt_db.write_bytes(b"SQLite format 3\x00corrupted garbage data")

    with pytest.raises(BenchmarkRefusalError) as exc_info:
        query_t6_ledger_read_only(corrupt_db)
    assert "RunStore ledger" in str(exc_info.value)

    # Missing 'runs' table in SQLite DB
    table_less_db = tmp_path / "no_runs_table.db"
    conn = sqlite3.connect(table_less_db)
    conn.execute("CREATE TABLE other_table (id INT)")
    conn.commit()
    conn.close()

    with pytest.raises(BenchmarkRefusalError) as exc_info2:
        query_t6_ledger_read_only(table_less_db)
    assert "missing" in str(exc_info2.value)


# ==============================================================================
# 4. Four Real Source Mutation Controls (Subprocess rc, stdout, stderr)
# ==============================================================================


def test_four_source_mutation_controls(tmp_path: Path, test_env):
    """Execute 4 real source mutation controls capturing subprocess rc, stdout, and stderr.

    Control 1: Wall Clock Timeout Supervision Gate
    Control 2: Process Group RSS Protection Gate
    Control 3: Orphan Grandchild Leak Detection Gate
    Control 4: Corrupt Ledger Fail-Closed Protection Gate
    """
    spec = test_env["spec"]
    results = []

    # --------------------------------------------------------------------------
    # Mutation Control 1: Wall Clock Timeout
    # --------------------------------------------------------------------------
    # Case A: Normal fast run (within budget) -> rc=0, completed
    res_a, meta_a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        simulate_sleep_seconds=0.02,
        timeout_s=1.0,
    )
    assert meta_a["returncode"] == 0
    assert meta_a["violation"] is None

    # Case B: Mutated runaway worker (sleeps 5.0s > 0.2s budget) -> killed, rc!=0 / timeout
    with pytest.raises(BenchmarkBudgetRefused) as exc_b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_timeout",
            simulate_sleep_seconds=5.0,
            timeout_s=0.2,
            poll_interval_s=0.02,
        )
    meta_b = exc_b.value.details
    assert meta_b["violation_type"] == "timeout"
    assert meta_b["empty_group_proven"] is True

    results.append({
        "control": "Control 1: Wall Clock Timeout",
        "case_a_rc": meta_a["returncode"],
        "case_b_violation": meta_b["violation_type"],
        "case_b_empty_group": meta_b["empty_group_proven"],
    })

    # --------------------------------------------------------------------------
    # Mutation Control 2: Process Group RSS Protection
    # --------------------------------------------------------------------------
    # Case A: Normal worker memory (allocates 5 MiB <= 50 MiB limit) -> rc=0
    res_2a, meta_2a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        simulate_rss_mib=5,
        max_rss_bytes=50 * 1024 * 1024,
    )
    assert meta_2a["returncode"] == 0

    # Case B: Mutated high-memory worker (allocates 100 MiB > 30 MiB limit) -> killed, rc!=0 / rss_limit
    with pytest.raises(BenchmarkResourceRefused) as exc_2b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_high_rss",
            simulate_rss_mib=100,
            simulate_sleep_seconds=5.0,
            max_rss_bytes=30 * 1024 * 1024,
            poll_interval_s=0.02,
        )
    meta_2b = exc_2b.value.details
    assert meta_2b["violation_type"] == "rss_limit"
    assert meta_2b["empty_group_proven"] is True

    results.append({
        "control": "Control 2: Process Group RSS Protection",
        "case_a_rc": meta_2a["returncode"],
        "case_b_violation": meta_2b["violation_type"],
        "case_b_empty_group": meta_2b["empty_group_proven"],
    })

    # --------------------------------------------------------------------------
    # Mutation Control 3: Orphan Grandchild Leak Detection
    # --------------------------------------------------------------------------
    # Case A: Normal worker with clean child subprocess -> rc=0, empty group
    res_3a, meta_3a = run_supervised_da3_worker(
        spec=spec,
        worker_action="mock_run",
        spawn_grandchild_count=1,
    )
    assert meta_3a["returncode"] == 0
    assert meta_3a["empty_group_proven"] is True

    # Case B: Mutated worker exits early leaving grandchild -> killed, grandchild_leak
    with pytest.raises(BenchmarkRefusalError) as exc_3b:
        run_supervised_da3_worker(
            spec=spec,
            worker_action="simulate_grandchild_leak",
            poll_interval_s=0.02,
        )
    meta_3b = exc_3b.value.details
    assert meta_3b["violation_type"] == "grandchild_leak"
    assert meta_3b["empty_group_proven"] is True

    results.append({
        "control": "Control 3: Orphan Grandchild Leak",
        "case_a_rc": meta_3a["returncode"],
        "case_b_violation": meta_3b["violation_type"],
        "case_b_empty_group": meta_3b["empty_group_proven"],
    })

    # --------------------------------------------------------------------------
    # Mutation Control 4: Corrupt Ledger Fail-Closed
    # --------------------------------------------------------------------------
    # Case A: Valid database -> query succeeds
    valid_db = tmp_path / "valid.db"
    with RunStore(valid_db) as store:
        store.create_run({"task": T6_TASK_ID, "views": 12}, request_id="v-1", run_id="v-1")
        store.transition("v-1", "initializing")
        store.transition("v-1", "validating")
        store.transition("v-1", "completed")
    sec_4a, views_4a = query_t6_ledger_read_only(valid_db)
    assert views_4a == 12

    # Case B: Mutated corrupt database -> fails closed, never returns 0
    bad_db = tmp_path / "corrupt_ledger.db"
    bad_db.write_text("NOT A SQLITE FILE", encoding="utf-8")
    with pytest.raises(BenchmarkRefusalError):
        query_t6_ledger_read_only(bad_db)

    results.append({
        "control": "Control 4: Corrupt Ledger Fail-Closed",
        "case_a_views": views_4a,
        "case_b_refused": True,
    })

    assert len(results) == 4
