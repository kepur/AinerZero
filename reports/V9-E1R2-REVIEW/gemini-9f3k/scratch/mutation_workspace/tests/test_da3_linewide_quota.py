"""Tests for DA3 line-wide quota accounting and sitecustomize task-ID retirement.

Verifies:
1. Multi-task line-wide aggregation (T6, T33, T33.r2, arbitrary task IDs) for DA3 runs.
2. Segregation of non-DA3 models (e.g. V-JEPA, SAM).
3. Quota enforcement across tasks (views & wall seconds).
4. Retirement of envs/teachers/t6/sitecustomize.py task ID rebinding.
5. Dismantled guard load-bearing controls (reverting to per-task matching allows evasion).
"""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.teachers.benchmark_protocol import (
    T6_TASK_ID,
    DA3RunSpec,
)
from ainerzero.v9.teachers.da3_controlled import (
    BenchmarkBudgetRefused,
    calculate_t6_cumulative_reserved_seconds,
    calculate_t6_cumulative_views,
    inspect_da3_benchmark,
    is_da3_ledger_run,
    query_t6_ledger_read_only,
)


def _create_consumed_run(store: RunStore, cfg: dict, request_id: str, run_id: str, active_seconds: float) -> None:
    store.create_run(cfg, request_id=request_id, run_id=run_id)
    store.transition(run_id, "initializing", reason="test init")
    store.transition(run_id, "validating", reason="test validate")
    store.consume(run_id, active_seconds=active_seconds)


def test_is_da3_ledger_run_classification():
    """Verify is_da3_ledger_run correctly identifies all DA3 model variants and historical tasks."""
    # Approved DA3 models regardless of task ID
    assert is_da3_ledger_run({"model": "da3-small", "task": "custom.task.A"}) is True
    assert is_da3_ledger_run({"model": "da3-base", "task": "custom.task.B"}) is True
    assert is_da3_ledger_run({"model": "da3-all", "task": "ainerzero.V9.T99"}) is True
    assert is_da3_ledger_run({"model": "DA3-SMALL", "task": "random"}) is True
    assert is_da3_ledger_run({"model": "small", "task": "arbitrary"}) is True
    assert is_da3_ledger_run({"model": "da3_base", "task": "other"}) is True

    # Historical DA3 tasks with DA3 models
    assert is_da3_ledger_run({"model": "da3-all", "task": "ainerzero.V9.T6"}) is True
    assert is_da3_ledger_run({"model": "da3-small", "task": "ainerzero.V9.T33"}) is True
    assert is_da3_ledger_run({"model": "da3-base", "task": "ainerzero.V9.T33.r2"}) is True

    # Non-DA3 models and non-DA3 tasks
    assert is_da3_ledger_run({"model": "vjepa", "task": "ainerzero.V9.T4"}) is False
    assert is_da3_ledger_run({"model": "sam-2.1", "task": "ainerzero.V9.T10"}) is False
    assert is_da3_ledger_run({"model": "tapir", "task": "ainerzero.V9.T12"}) is False
    assert is_da3_ledger_run({"model": "resnet50", "task": "vision.benchmark"}) is False

    # Missing or null model field is treated as corrupted ledger state and raises BenchmarkRefusalError
    from ainerzero.v9.teachers.benchmark_protocol import BenchmarkRefusalError
    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        is_da3_ledger_run({})
    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        is_da3_ledger_run({"task": "ainerzero.V9.T6"})
    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        is_da3_ledger_run({"model": None, "task": "ainerzero.V9.T6"})
    with pytest.raises(BenchmarkRefusalError, match="invalid or non-string 'model'"):
        is_da3_ledger_run({"model": "", "task": "ainerzero.V9.T6"})


def test_linewide_aggregation_across_different_tasks(tmp_path: Path):
    """Line-wide accounting accumulates views and seconds across all DA3 tasks while excluding non-DA3 runs."""
    store_path = tmp_path / "linewide_store.db"

    with RunStore(store_path) as store:
        # T6 run: 81 views, 1170.0s
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T6", "model": "da3-all", "views": 81},
            request_id="req-t6",
            run_id="run-t6",
            active_seconds=1170.0,
        )

        # T33 run: 82 views, 140.0s
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T33", "model": "da3-all", "views": 82},
            request_id="req-t33",
            run_id="run-t33",
            active_seconds=140.0,
        )

        # T33.r2 run: 36 views, 10.0s
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T33.r2", "model": "da3-all", "views": 36},
            request_id="req-t33-r2",
            run_id="run-t33-r2",
            active_seconds=10.0,
        )

        # Non-DA3 run: T4 V-JEPA, 1500s, 100 views -> MUST NOT CONTAMINATE
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T4", "model": "vjepa", "views": 100},
            request_id="req-t4",
            run_id="run-t4",
            active_seconds=1500.0,
        )

    # Line-wide query
    total_seconds, total_views = query_t6_ledger_read_only(store_path)
    assert total_views == 81 + 82 + 36 == 199
    assert total_seconds == 1170.0 + 140.0 + 10.0 == 1320.0

    # Convenience wrappers
    assert calculate_t6_cumulative_views(store_path) == 199
    assert calculate_t6_cumulative_reserved_seconds(store_path) == 1320.0


def test_adversary_task_id_cannot_reset_or_evade_linewide_quota(tmp_path: Path):
    """An adversary creating runs under a new task ID still has those runs counted line-wide."""
    store_path = tmp_path / "adversary_store.db"

    with RunStore(store_path) as store:
        # Initial legitimate T6 run: 81 views, 1170.0s
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T6", "model": "da3-all", "views": 81},
            request_id="req-t6",
            run_id="run-t6",
            active_seconds=1170.0,
        )

        # Adversary attempts to hide under a new task ID "ainerzero.V9.T99_bypass"
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T99_bypass", "model": "da3-small", "views": 50},
            request_id="req-adv",
            run_id="run-adv",
            active_seconds=100.0,
        )

    # Both must be accumulated under line-wide accounting
    total_seconds, total_views = query_t6_ledger_read_only(store_path)
    assert total_views == 81 + 50 == 131
    assert total_seconds == 1170.0 + 100.0 == 1270.0


def test_sitecustomize_retirement_no_rebinding(monkeypatch):
    """Verify envs/teachers/t6/sitecustomize.py is retired and no longer rewrites T6_TASK_ID."""
    sitecustomize_path = Path("/Users/mac/AinerWorkFlow/AinerZero/envs/teachers/t6/sitecustomize.py")
    assert sitecustomize_path.is_file(), "sitecustomize.py must exist"

    # Set environment variables that previously triggered rewrites
    monkeypatch.setenv("DA3_TASK_ID", "ainerzero.V9.T33_MALICIOUS")
    monkeypatch.setenv("T33_DAILY_OVERRIDE_SECONDS", "1260.0")

    # Read and execute sitecustomize in a clean namespace
    ns = {}
    exec(sitecustomize_path.read_text(encoding="utf-8"), ns)

    import ainerzero.v9.teachers.benchmark_protocol as bp
    import ainerzero.v9.teachers.da3_controlled as dc

    # Constants must remain intact
    assert bp.T6_TASK_ID == "ainerzero.V9.T6"
    assert dc.T6_TASK_ID == "ainerzero.V9.T6"


def test_dismantled_guard_load_bearing_control(tmp_path: Path):
    """Load-bearing control: Reverting to the old per-task match allows evasion (RED), whereas intact guard catches it (GREEN)."""
    store_path = tmp_path / "control_store.db"

    # Seed RunStore with 199 views and 1320s split across T6 (81) and T33 (118)
    with RunStore(store_path) as store:
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T6", "model": "da3-all", "views": 81},
            request_id="req-1",
            run_id="run-1",
            active_seconds=1170.0,
        )

        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T33", "model": "da3-all", "views": 118},
            request_id="req-2",
            run_id="run-2",
            active_seconds=150.0,
        )

    # 1. Intact line-wide guard:
    # Sees total 199 views and 1320.0s
    sec_intact, views_intact = query_t6_ledger_read_only(store_path)
    assert views_intact == 199
    assert sec_intact == 1320.0

    # 2. Dismantled / Bad Control (the old per-task vulnerability):
    def dismantled_query_t6_ledger(store_path: Path) -> tuple[float, int]:
        conn = sqlite3.connect(f"file:{store_path.resolve()}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT config_json, active_seconds FROM runs")
        total_seconds = 0.0
        total_views = 0
        for config_json, active_seconds in cur.fetchall():
            cfg = __import__("json").loads(config_json)
            # Vulnerability: only counts runs where task == T6_TASK_ID ("ainerzero.V9.T6")
            if cfg.get("task") == T6_TASK_ID:
                total_seconds += float(active_seconds or 0.0)
                total_views += int(cfg.get("views") or 0)
        conn.close()
        return total_seconds, total_views

    sec_dismantled, views_dismantled = dismantled_query_t6_ledger(store_path)
    # The bad control only sees 81 views and 1170s!
    assert views_dismantled == 81
    assert sec_dismantled == 1170.0

    # Under dismantled control, T33's 118 views / 150s are completely invisible!
    assert views_dismantled < views_intact
    assert sec_dismantled < sec_intact

def _make_valid_research_log(tmp_path: Path) -> Path:
    from ainerzero.v9.teachers.benchmark_protocol import (
        T6_APPROVAL_KEYWORD,
        T6_APPROVAL_SECTION,
        T6_APPROVAL_TARGET,
    )
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
""",
        encoding="utf-8",
    )
    return log_file


def _make_valid_protocol(tmp_path: Path) -> Path:
    proto_file = tmp_path / "protocol.json"
    proto_data = {
        "protocol_id": "az.v9.da3.calibration.v1",
        "metrics": ["rotation_error_deg", "translation_rel_error"],
        "calibration_inputs": {
            "world_list_sha256": "982dc676ad377d2439cb4ce92d4c58875d2175a949885fd2dfcc588d2f8a86ca",
            "n_worlds": 32,
        },
        "tolerance": {
            "max_rotation_deg": 1.0,
            "max_translation_rel": 0.05,
        },
    }
    proto_file.write_text(json.dumps(proto_data), encoding="utf-8")
    return proto_file


def test_linewide_budget_refusal_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """End-to-end: Pre-existing runs under T33 count towards line-wide budget and cause refusal when exceeding cap."""
    from ainerzero.v9.teachers import t28_registration
    from ainerzero.v9.teachers.da3_controlled import (
        FakeDA3BenchmarkAdapter,
        execute_guarded_da3_benchmark,
    )

    clean_repo = tmp_path / "clean_repo"
    clean_repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", clean_repo)

    store_path = tmp_path / "quota_refusal.db"
    lock_path = tmp_path / "quota_refusal.lock"
    research_log = _make_valid_research_log(tmp_path)
    protocol_path = _make_valid_protocol(tmp_path)
    weights_root = Path("artifacts/teachers/da3")

    # Seed RunStore with a T33 run using 1150s (out of 1200s default cap)
    with RunStore(store_path) as store:
        _create_consumed_run(
            store,
            {"task": "ainerzero.V9.T33", "model": "da3-small", "views": 18, "budget": {"timezone": "UTC"}},
            request_id="req-t33-prior",
            run_id="run-t33-prior",
            active_seconds=1150.0,
        )

    # Now attempt a new run requesting 100s: 1150 + 100 = 1250 > 1200
    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=100.0,
        views=4,
        research_log_path=research_log,
        store_path=store_path,
        lock_path=lock_path,
        weights_root=weights_root,
        statistical_protocol_path=protocol_path,
    )

    with pytest.raises(BenchmarkBudgetRefused) as exc_info:
        execute_guarded_da3_benchmark(spec, adapter=FakeDA3BenchmarkAdapter())
    assert "Cumulative wall budget exceeded" in str(exc_info.value)
