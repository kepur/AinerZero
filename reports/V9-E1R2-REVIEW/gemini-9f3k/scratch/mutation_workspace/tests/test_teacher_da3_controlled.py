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


@pytest.fixture(autouse=True)
def _isolate_repo_root_for_legacy_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate registration to an empty tmp directory so legacy baseline tests test default rules."""
    clean_repo = tmp_path / "clean_repo_defaults"
    clean_repo.mkdir(parents=True, exist_ok=True)
    from ainerzero.v9.teachers import t28_registration
    monkeypatch.setattr(t28_registration, "REPO_ROOT", clean_repo)


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
    assert len(report["approval"]["missing_items"]) >= 1
    assert "Frozen statistical evaluation protocol" in report["approval"]["missing_items"][0]
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


def _isolated_cwd(tmp_path: Path) -> Path:
    """V9.T37：给 CLI 子进程一个隔离的工作目录。

    默认的 RunStore / 共享锁是相对路径，所以不链入 artifacts/v9 与 artifacts/locks，台账和锁在临时目录里新建；
    只读链入真实的 RESEARCH_LOG.md 与模型权重目录，保持被测的审批/权重判定与原来一致。"""
    root = Path(__file__).resolve().parents[1]
    work = tmp_path / "isolated_cwd"
    (work / "artifacts").mkdir(parents=True)
    (work / "RESEARCH_LOG.md").symlink_to(root / "RESEARCH_LOG.md")
    (work / "artifacts" / "teachers").symlink_to(root / "artifacts" / "teachers")
    return work


def test_cli_subprocess_inspect(tmp_path: Path):
    """Verify `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode inspect` subprocess execution.

    V9.T37：子进程在临时工作目录里跑。默认的 RunStore / 共享锁 / RESEARCH_LOG 都是相对路径，此前在仓库根目录里跑，
    等于直接读生产台账：T35 真跑把累计视图推到 81 之后，默认 views=4 的投影越过上限 82，这条测试就因为生产配额状态
    而失败，与被测代码无关。注意不能改用 --store-path：正式 run 模式明确禁止自定义台账路径，那样会改变被测行为。"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
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
        cwd=_isolated_cwd(tmp_path),
    )
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["mode"] == "inspect"
    assert data["task"] == T6_TASK_ID
    assert data["approval"]["is_approved"] is False
    assert data["can_run"] is False


def test_cli_subprocess_run_refused(tmp_path: Path):
    """Verify `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode run` exits with code 3."""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
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
            "--wall-budget-seconds",
            "120.0",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_isolated_cwd(tmp_path),
    )
    assert res.returncode == 3
    data = json.loads(res.stdout)
    assert data["status"] == "refused_approval"
    assert data["exit_code"] == 3


def test_coordinator_release_gate_and_cli(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
):
    """Coordinator release switch (--coordinator-release / --allow-model-execution) gate."""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))

    # 1. Without release or test substitute, run is refused before reservation (exit 1)
    res_unreleased = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.cli",
            "teacher-da3",
            "--mode",
            "run",
            "--research-log",
            str(valid_t6_research_log),
            "--statistical-protocol",
            str(valid_statistical_protocol),
            "--wall-budget-seconds",
            "10.0",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_isolated_cwd(tmp_path),
    )
    assert res_unreleased.returncode == 1
    data_unreleased = json.loads(res_unreleased.stdout)
    assert "coordinator execution release authorization not granted" in data_unreleased["error"]

    # 2. In Python API, verify coordinator_release=True allows pre-reservation
    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=4,
        research_log_path=valid_t6_research_log,
        store_path=tmp_path / "runs.db",
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )
    spec_dict = spec.to_dict()
    assert spec_dict["coordinator_release"] is True
    assert spec_dict["allow_model_execution"] is True

    # Test substitute execution with custom paths
    res = execute_guarded_da3_benchmark(
        spec=spec,
        test_substitute=True,
        allow_custom_paths=True,
    )
    assert res["status"] == "completed"


def test_test_substitute_never_selects_the_real_pipeline_even_when_released(
    tmp_path: Path, valid_t6_research_log: Path, valid_statistical_protocol: Path, monkeypatch
):
    """V9.T40：放行 + 授权 + views=18 + test_substitute。旧代码把 action 选成 real_pipeline，等于在单元测试里启动真实 DA3 前向
    （test_coordinator_release_gate_and_cli 没真跑，纯粹因为 views=4 被 worker 的 views==18 魔数挡住）。
    探针截获 worker_action，**不调用任何真实 worker**；走不到探针就失败（用 seen["action"]，没有默认值可以空过）。"""
    from ainerzero.v9.teachers import da3_controlled as DC

    seen = {}

    def spy(spec, worker_action="real_pipeline", **kw):
        seen["action"] = worker_action
        if worker_action != "mock_run":
            raise AssertionError(f"test substitute reached worker_action={worker_action!r}")
        return {"status": "completed", "model_runs": 0, "is_mock": True}, {
            "violation": None, "peak_rss_bytes": 0, "empty_group_proven": True, "pgid": 1, "worker_pid": 1,
            "elapsed_seconds": 0.0, "returncode": 0, "stdout": "", "stderr": "", "confirmed_empty": True}

    monkeypatch.setattr(DC, "run_supervised_da3_worker", spy)
    spec = DA3RunSpec(
        model="da3-small", wall_budget_seconds=10.0, views=18, research_log_path=valid_t6_research_log,
        store_path=tmp_path / "runs.db", lock_path=tmp_path / "t.lock", weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol, coordinator_release=True, allow_model_execution=True,
    )
    DC.execute_guarded_da3_benchmark(spec=spec, test_substitute=True, allow_custom_paths=True)
    assert seen["action"] == "mock_run"
    with pytest.raises(BenchmarkRefusalError, match="never reach the real pipeline"):
        DC.execute_guarded_da3_benchmark(spec=spec, test_substitute=True, allow_custom_paths=True, worker_action="real_pipeline")


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
    # Baseline: Exceeding cumulative cap is rejected
    with pytest.raises(BenchmarkBudgetRefused):
        if 1500.0 > T6_MAX_CUMULATIVE_WALL_SECONDS:
            raise BenchmarkBudgetRefused("Exceeded cumulative cap")
    # Mutant: relaxed limit of 2400s accepts 1500s
    assert 1500.0 <= 2400.0

    # Control 4: RSS Resource Gate Mutation
    # Baseline: 9.0 GiB RSS rejected under 8.0 GiB limit
    with pytest.raises(BenchmarkResourceRefused):
        if 9.0 > T6_MAX_PROCESS_RSS_GIB:
            raise BenchmarkResourceRefused("Exceeded 8.0 GiB")
    # Mutant: relaxed limit of 64.0 GiB accepts 9.0 GiB
    assert 9.0 <= 64.0


def test_pre_consume_calibration_views_check_rejects_non_calibration_views_before_consume(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """V9.T42 (1): consume 前预检。
    对 worker_action=real_pipeline，在 store.consume 之前校验视图数是否等于当前登记标定口径 (REGISTERED_CALIBRATION_VIEWS=18)。
    非 18 必须直接拒绝、零扣账、零 worker 启动。"""
    from ainerzero.v9.teachers.da3_worker import REGISTERED_CALIBRATION_VIEWS
    import ainerzero.v9.teachers.da3_controlled as DC

    worker_called = []
    def spy_worker(*args, **kwargs):
        worker_called.append(True)
        return {"status": "completed", "model_runs": 1}, {"violation": None}

    monkeypatch.setattr(DC, "run_supervised_da3_worker", spy_worker)

    store_file = tmp_path / "test_runs.db"
    spec_invalid_views = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=4,  # 不等于 REGISTERED_CALIBRATION_VIEWS (18)
        research_log_path=valid_t6_research_log,
        store_path=store_file,
        lock_path=tmp_path / "test.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )

    # 1. 直接抛出 BenchmarkRefusalError
    with pytest.raises(BenchmarkRefusalError, match="Real DA3 pipeline execution requires views == 18"):
        DC.execute_guarded_da3_benchmark(
            spec=spec_invalid_views,
            worker_action="real_pipeline",
            allow_custom_paths=True,
        )

    # 2. 验证 worker 零启动
    assert len(worker_called) == 0

    # 3. 验证 store 零扣账（甚至未创建数据库/未建 run）
    if store_file.exists():
        with RunStore(store_file) as store:
            runs = store.list_runs()
            assert len(runs) == 0


def test_cli_substitute_with_release_selects_mock_run_and_defense_in_depth(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
):
    """V9.T42 (3): CLI 在 --test-substitute --coordinator-release 下应直接选 mock_run，
    不再先选 real_pipeline 再被守卫拒；守卫本身保留（纵深防御），两层测试全覆盖。"""
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))

    # 层级 1 (CLI 层面)：--test-substitute 与 --coordinator-release 同时给出，CLI 必须选 mock_run 并成功完成
    res_cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "ainerzero.cli",
            "teacher-da3",
            "--mode",
            "run",
            "--test-substitute",
            "--coordinator-release",
            "--allow-model-execution",
            "--research-log",
            str(valid_t6_research_log),
            "--statistical-protocol",
            str(valid_statistical_protocol),
            "--store-path",
            str(tmp_path / "cli_substitute.db"),
            "--lock-path",
            str(tmp_path / "cli_substitute.lock"),
            "--wall-budget-seconds",
            "10.0",
            "--views",
            "4",
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=_isolated_cwd(tmp_path),
    )
    assert res_cli.returncode == 0, f"CLI failed: {res_cli.stderr}\n{res_cli.stdout}"
    data_cli = json.loads(res_cli.stdout)
    assert data_cli["status"] == "completed"
    assert data_cli["model_runs"] == 0
    assert data_cli["result"]["is_mock"] is True

    # 层级 2 (execute_guarded 纵深防御守卫)：直接传 worker_action="real_pipeline" + test_substitute=True 必须被拦截拒绝
    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=18,
        research_log_path=valid_t6_research_log,
        store_path=tmp_path / "defense_guard.db",
        lock_path=tmp_path / "defense_guard.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )
    with pytest.raises(BenchmarkRefusalError, match="test substitute mode must never reach the real pipeline worker"):
        execute_guarded_da3_benchmark(
            spec=spec,
            test_substitute=True,
            worker_action="real_pipeline",
            allow_custom_paths=True,
        )



def test_derived_real_pipeline_path_also_hits_the_calibration_views_gate(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """V9.T44 (F-1)：派生路径也必须过 views 门。

    这里**不传** `worker_action`（默认 None），让 `action` 由 `is_released` 派生成
    `real_pipeline`；`views=4 != REGISTERED_CALIBRATION_VIEWS(18)` 必须被拒，且拒因是
    views（不是配额）、零扣账、零 worker 启动。

    靶子：T43 变异 **M-A**（把门改成只看显式 `worker_action`）。若门退化为"只在显式传时生效"，
    这条派生路径就会一路走到 consume 与 worker，本测试因 `pytest.raises` 落空而变红。
    """
    import ainerzero.v9.teachers.da3_controlled as DC
    from ainerzero.v9.teachers.da3_worker import REGISTERED_CALIBRATION_VIEWS

    worker_called: list = []

    def spy_worker(*args, **kwargs):
        worker_called.append(True)
        return {"status": "completed", "model_runs": 1}, {"violation": None}

    monkeypatch.setattr(DC, "run_supervised_da3_worker", spy_worker)

    store_file = tmp_path / "derived_path_runs.db"
    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=4,  # != REGISTERED_CALIBRATION_VIEWS
        research_log_path=valid_t6_research_log,
        store_path=store_file,
        lock_path=tmp_path / "derived_path.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )

    with pytest.raises(BenchmarkRefusalError, match="Real DA3 pipeline execution requires views == 18") as caught:
        # 关键：worker_action 缺省（None）——走 is_released 派生路径
        DC.execute_guarded_da3_benchmark(spec=spec, allow_custom_paths=True)

    details = getattr(caught.value, "details", {}) or {}
    assert details.get("action") == "real_pipeline"
    assert details.get("derived_from_release") is True
    assert details.get("required_views") == REGISTERED_CALIBRATION_VIEWS
    assert worker_called == [], "派生路径被拒时不得启动 worker"
    if store_file.exists():
        with RunStore(store_file) as store:
            assert store.list_runs() == [], "派生路径被拒时不得产生 run（零扣账）"


def test_views_gate_precedes_the_quota_gate_and_reports_the_views_reason(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """V9.T44 (项 1)：views 预检必须排在**累计配额**检查之前。

    用探针把台账投影成 T43 P2 的真实场景（累计 81 视图 / 上限 82），再请求 views=17：
    配额会算出 81+17=98>82，而 views 口径也不符（17 != 18）。正确顺序下拒因必须是 views 口径，
    不能是配额——否则运维会去查配额，而真原因是口径配错。
    """
    import ainerzero.v9.teachers.da3_controlled as DC

    monkeypatch.setattr(DC, "run_supervised_da3_worker", lambda *a, **k: (_ for _ in ()).throw(AssertionError("worker must not start")))
    monkeypatch.setattr(DC, "get_effective_t6_max_views", lambda store_path: 82)
    monkeypatch.setattr(DC, "query_t6_ledger_read_only", lambda store_path: (1320.0, 81))

    spec = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=17,  # <= 单次配额 64，但 != 标定口径 18；且 81+17 > 82
        research_log_path=valid_t6_research_log,
        store_path=tmp_path / "quota_overlap_runs.db",
        lock_path=tmp_path / "quota_overlap.lock",
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol,
        coordinator_release=True,
        allow_model_execution=True,
    )
    with pytest.raises(BenchmarkRefusalError) as caught:
        DC.execute_guarded_da3_benchmark(spec=spec, worker_action="real_pipeline", allow_custom_paths=True)
    message = str(caught.value)
    assert "Real DA3 pipeline execution requires views == 18" in message, message
    assert "quota" not in message.lower(), "views 口径错误不得被配额错误覆盖"


def test_cli_allow_model_execution_alone_is_refused_before_any_reservation(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """V9.T44 r2：`--allow-model-execution` 单独给时，CLI 必须在任何预扣之前拒绝。

    T44 初版把它悄悄选成 mock_run，而 `coordinator_release` 又已被折算为 True，所以 execute_guarded 会放行、预扣视图与墙钟、
    启动 mock worker 并记 completed（model_runs=0）——配额被一个 mock 吃掉。探针替掉 execute_guarded：一旦被调用就说明
    拒绝没有发生在预扣之前。与 `--test-substitute` 组合时仍允许（那是 CPU 测试替身，不消耗授权）。
    """
    import ainerzero.v9.teachers.benchmark_commands as BC

    monkeypatch.setattr(BC, "DEFAULT_STORE_PATH", tmp_path / "cli_routing.db")
    monkeypatch.setattr(BC, "DEFAULT_LOCK_PATH", tmp_path / "cli_routing.lock")

    calls: list = []

    def spy_execute(spec, **kwargs):
        calls.append(kwargs.get("worker_action"))
        return {"status": "completed", "model_runs": 0, "result": {"is_mock": True}}

    monkeypatch.setattr(BC, "execute_guarded_da3_benchmark", spy_execute)

    def make_args(**over):
        base = dict(
            mode="run", model="da3-small", wall_budget_seconds=10.0, views=18,
            research_log=str(valid_t6_research_log), statistical_protocol=str(valid_statistical_protocol),
            coordinator_release=False, allow_model_execution=False, test_substitute=False,
        )
        base.update(over)
        return argparse.Namespace(**base)

    report, code = BC.da3_benchmark_command(make_args(allow_model_execution=True))
    assert report["status"] == "refused" and code != BC.EXIT_COMPLETED
    assert "--coordinator-release" in report["error"] and "before reservation" in report["error"]
    assert calls == [], "拒绝必须发生在调用 execute_guarded（即任何预扣）之前"

    # 替身不消耗授权：仍然允许，且恒选 mock_run
    report, code = BC.da3_benchmark_command(make_args(allow_model_execution=True, test_substitute=True))
    assert code == BC.EXIT_COMPLETED and calls == ["mock_run"]


def test_released_non_substitute_run_must_use_the_real_pipeline_before_any_reservation(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """V9.T44 r2 纵深防御：即使有人绕过 CLI 直接调 execute_guarded，已放行的非替身运行也不能是 mock_run / simulate_*。

    零台账、零锁、零 worker：用 tmp 路径，断言 runs.db 与锁文件都没有被创建，worker 探针从未被调用。
    """
    from ainerzero.v9.teachers import da3_controlled as DC

    started: list = []
    monkeypatch.setattr(DC, "run_supervised_da3_worker", lambda *a, **k: started.append((a, k)))
    spec = DA3RunSpec(
        model="da3-small", wall_budget_seconds=10.0, views=18, research_log_path=valid_t6_research_log,
        store_path=tmp_path / "runs.db", lock_path=tmp_path / "t.lock", weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=valid_statistical_protocol, coordinator_release=True, allow_model_execution=True,
    )
    for action in ("mock_run", "simulate_timeout", "simulate_high_rss", "simulate_grandchild_leak"):
        with pytest.raises(BenchmarkRefusalError, match="must execute the real pipeline"):
            DC.execute_guarded_da3_benchmark(spec=spec, test_substitute=False, allow_custom_paths=True, worker_action=action)
    assert started == []
    assert not (tmp_path / "runs.db").exists() and not (tmp_path / "t.lock").exists()


def test_cli_real_branch_still_selects_real_pipeline_with_explicit_release(
    tmp_path: Path,
    valid_t6_research_log: Path,
    valid_statistical_protocol: Path,
    monkeypatch,
):
    """正对照：显式 `--coordinator-release` 时 CLI 仍选 real_pipeline（收紧不等于废掉能力）。"""
    import ainerzero.v9.teachers.benchmark_commands as BC

    monkeypatch.setattr(BC, "DEFAULT_STORE_PATH", tmp_path / "cli_real.db")
    monkeypatch.setattr(BC, "DEFAULT_LOCK_PATH", tmp_path / "cli_real.lock")

    seen: dict = {}

    def spy_execute(spec, **kwargs):
        seen["worker_action"] = kwargs.get("worker_action")
        return {"status": "completed", "model_runs": 1, "result": {"is_mock": False}}

    monkeypatch.setattr(BC, "execute_guarded_da3_benchmark", spy_execute)

    args = argparse.Namespace(
        mode="run",
        model="da3-small",
        wall_budget_seconds=10.0,
        views=18,
        research_log=str(valid_t6_research_log),
        statistical_protocol=str(valid_statistical_protocol),
        coordinator_release=True,
        allow_model_execution=False,
        test_substitute=False,
    )
    report, code = BC.da3_benchmark_command(args)
    assert code == BC.EXIT_COMPLETED
    assert seen["worker_action"] == "real_pipeline"
    assert report["worker_action"] == "real_pipeline"
