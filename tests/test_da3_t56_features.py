"""Tests covering V9.T56 DA3 runner proposal verification, ledger model validation, diagnostics, and card recording.

Coverage requirements:
- 有登记且 SHA 一致 → 通过 (0)
- SHA 不一致 → 拒绝（--proposal 与环境变量两条路都测，退出码非 0）
- 无登记 → 保持 r1 行为 (EXIT_UNSATISFIABLE == 6)
- 缺 model 时拒绝 (BenchmarkRefusalError)
- 非 DA3 进诊断 (query_t6_ledger_with_diagnostics non_da3_runs)
- card 字段写入 (DA3_TASK_ID 环境变量写入 config.card，未设置时为 null)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ainerzero.runtime.lifecycle import RunStore
from ainerzero.v9.teachers import (
    da3_calibration_runner as R,
    da3_controlled as DC,
    t28_registration,
)
from ainerzero.v9.teachers.benchmark_protocol import (
    BenchmarkRefusalError,
    DA3RunSpec,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
R1_PROPOSAL = REPO_ROOT / "reports/V9-T28/proposal.json"
R2_PROPOSAL = REPO_ROOT / "reports/V9-T28/r2/proposal.json"


def _make_isolated_repo_with_registration(tmp_path: Path, proposal_path: Path) -> Path:
    """Create a temporary fake repo root containing reports/V9-T28/REGISTERED.json pointing to proposal."""
    fake_root = tmp_path / "repo_root"
    fake_t28 = fake_root / "reports/V9-T28"
    fake_t28.mkdir(parents=True, exist_ok=True)

    prop_bytes = proposal_path.read_bytes()
    dest_prop = fake_t28 / "proposal.json"
    dest_prop.write_bytes(prop_bytes)
    sha256 = hashlib.sha256(prop_bytes).hexdigest()

    reg_file = fake_t28 / "REGISTERED.json"
    reg_file.write_text(
        json.dumps({
            "proposal_path": "reports/V9-T28/proposal.json",
            "sha256": sha256,
            "registered_by": "gemini-test",
        }),
        encoding="utf-8",
    )
    return fake_root


def test_runner_registered_sha_match_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """有登记且 SHA 一致 → 通过 (0)。"""
    fake_repo = _make_isolated_repo_with_registration(tmp_path, R2_PROPOSAL)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_repo)

    args = [
        "--preflight-only",
        "--output", str(tmp_path / "out.json"),
        "--predictions-dir", str(tmp_path / "preds"),
    ]
    code = R.main(args)
    assert code == R.EXIT_OK


def test_runner_registered_sha_mismatch_refused_via_proposal_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SHA 不一致 → --proposal 显式传入非登记的 proposal 时拒绝（退出码非 0）。"""
    fake_repo = _make_isolated_repo_with_registration(tmp_path, R2_PROPOSAL)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_repo)

    # Pass R1 proposal (which has different SHA than registered R2)
    args = [
        "--preflight-only",
        "--output", str(tmp_path / "out.json"),
        "--predictions-dir", str(tmp_path / "preds"),
        "--proposal", str(R1_PROPOSAL),
    ]
    code = R.main(args)
    assert code == R.EXIT_PREFLIGHT


def test_runner_registered_sha_mismatch_refused_via_env_var(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SHA 不一致 → T6_PROPOSAL_PATH 环境变量传入非登记 proposal 时拒绝（退出码非 0）。"""
    fake_repo = _make_isolated_repo_with_registration(tmp_path, R2_PROPOSAL)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_repo)
    monkeypatch.setenv("T6_PROPOSAL_PATH", str(R1_PROPOSAL))

    args = [
        "--preflight-only",
        "--output", str(tmp_path / "out.json"),
        "--predictions-dir", str(tmp_path / "preds"),
    ]
    code = R.main(args)
    assert code == R.EXIT_PREFLIGHT


def test_runner_no_registration_defaults_to_r1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """无登记 → 默认保持 r1 行为（未做模型工作前因协议不可满足直接拒绝，退出码 6）。"""
    empty_repo = tmp_path / "empty_repo"
    t28_dir = empty_repo / "reports/V9-T28"
    t28_dir.mkdir(parents=True, exist_ok=True)
    (t28_dir / "proposal.json").write_bytes(R1_PROPOSAL.read_bytes())
    sidecar = R1_PROPOSAL.with_name("proposal.sha256")
    if sidecar.is_file():
        (t28_dir / "proposal.sha256").write_bytes(sidecar.read_bytes())

    monkeypatch.setattr(t28_registration, "REPO_ROOT", empty_repo)
    monkeypatch.delenv("T6_PROPOSAL_PATH", raising=False)

    args = [
        "--preflight-only",
        "--output", str(tmp_path / "out.json"),
        "--predictions-dir", str(tmp_path / "preds"),
    ]
    code = R.main(args)
    assert code == R.EXIT_UNSATISFIABLE


def test_is_da3_ledger_run_missing_model_refuses():
    """缺 model 字段的 run 一律视为账本损坏，抛 BenchmarkRefusalError。"""
    # Missing key completely
    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        DC.is_da3_ledger_run({})

    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        DC.is_da3_ledger_run({"task": "ainerzero.V9.T6", "views": 10})

    # None model
    with pytest.raises(BenchmarkRefusalError, match="missing or null 'model'"):
        DC.is_da3_ledger_run({"model": None, "task": "ainerzero.V9.T6"})

    # Non-string or empty model
    with pytest.raises(BenchmarkRefusalError, match="invalid or non-string 'model'"):
        DC.is_da3_ledger_run({"model": "", "task": "ainerzero.V9.T6"})

    with pytest.raises(BenchmarkRefusalError, match="invalid or non-string 'model'"):
        DC.is_da3_ledger_run({"model": 123, "task": "ainerzero.V9.T6"})


def test_non_da3_runs_in_diagnostics_and_excluded_from_accounting(tmp_path: Path):
    """非 DA3 的 run 不计入记账，但列在可选诊断返回 non_da3_runs 里；不改原签名。"""
    db_path = tmp_path / "diagnostic_runs.db"

    with RunStore(db_path) as store:
        # Run 1: DA3 run
        store.create_run(
            {"task": "ainerzero.V9.T6", "model": "da3-small", "views": 25},
            request_id="da3-req-1",
            run_id="da3-run-1",
        )
        store.transition("da3-run-1", "initializing")
        store.transition("da3-run-1", "validating")
        store.consume("da3-run-1", active_seconds=60.0)
        store.transition("da3-run-1", "completed")

        # Run 2: Non-DA3 run (vjepa)
        store.create_run(
            {"task": "ainerzero.V9.T4", "model": "vjepa", "views": 100},
            request_id="non-req-1",
            run_id="non-run-1",
        )
        store.transition("non-run-1", "initializing")
        store.transition("non-run-1", "validating")
        store.consume("non-run-1", active_seconds=500.0)
        store.transition("non-run-1", "completed")

        # Run 3: Non-DA3 run (sam-2.1)
        store.create_run(
            {"task": "ainerzero.V9.T10", "model": "sam-2.1", "views": 50},
            request_id="non-req-2",
            run_id="non-run-2",
        )
        store.transition("non-run-2", "initializing")
        store.transition("non-run-2", "validating")
        store.consume("non-run-2", active_seconds=200.0)
        store.transition("non-run-2", "completed")

    # 1. New diagnostics function
    diag = DC.query_t6_ledger_with_diagnostics(db_path)
    assert diag["total_runs_examined"] == 3
    assert diag["cumulative_reserved_seconds"] == 60.0
    assert diag["cumulative_views"] == 25
    assert len(diag["da3_runs"]) == 1
    assert diag["da3_runs"][0]["run_id"] == "da3-run-1"
    assert len(diag["non_da3_runs"]) == 2
    non_da3_ids = [r["run_id"] for r in diag["non_da3_runs"]]
    assert "non-run-1" in non_da3_ids
    assert "non-run-2" in non_da3_ids

    # 2. Original signature function query_t6_ledger_read_only unchanged
    sec, views = DC.query_t6_ledger_read_only(db_path)
    assert sec == 60.0
    assert views == 25


def test_new_run_config_records_card_field(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """新建 run 的 config 增加 card 字段，取环境变量 DA3_TASK_ID（未设置时为 null），只作记录，不参与记账。"""
    db_path = tmp_path / "card_test.db"
    lock_path = tmp_path / "card_test.lock"

    # Make valid approval & protocol
    log_file = tmp_path / "RESEARCH_LOG.md"
    log_file.write_text(
        "# Research Log\n## R20261026-T6：批准 T6 有界 DA3 标定入口\n- 批准对象：ainerzero.V9.T6。关键字：批准 T6。\n- 统计协议：见 statistical_protocol.json\n",
        encoding="utf-8",
    )
    proto_file = tmp_path / "statistical_protocol.json"
    proto_file.write_text(
        json.dumps({
            "protocol_id": "az.v9.da3.calibration.v1",
            "metrics": ["rotation_error_deg"],
            "calibration_inputs": {"n_worlds": 4},
            "tolerance": {"max_rotation_deg": 1.0},
        }),
        encoding="utf-8",
    )

    clean_repo = tmp_path / "clean_repo_defaults"
    clean_repo.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(t28_registration, "REPO_ROOT", clean_repo)

    # 1. With DA3_TASK_ID set
    monkeypatch.setenv("DA3_TASK_ID", "ainerzero.V9.T56")
    spec1 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=4,
        research_log_path=log_file,
        store_path=db_path,
        lock_path=lock_path,
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=proto_file,
    )
    res1 = DC.execute_guarded_da3_benchmark(spec1, adapter=DC.FakeDA3BenchmarkAdapter())
    assert res1["status"] == "completed"

    with RunStore(db_path) as store:
        run1_data = store.get_run(res1["run_id"])
        cfg1 = run1_data.config_snapshot
        assert cfg1.get("card") == "ainerzero.V9.T56"

    # 2. Without DA3_TASK_ID set -> null in JSON / None in dict
    monkeypatch.delenv("DA3_TASK_ID", raising=False)
    spec2 = DA3RunSpec(
        model="da3-small",
        wall_budget_seconds=10.0,
        views=4,
        research_log_path=log_file,
        store_path=db_path,
        lock_path=lock_path,
        weights_root=Path("artifacts/teachers/da3"),
        statistical_protocol_path=proto_file,
    )
    res2 = DC.execute_guarded_da3_benchmark(spec2, adapter=DC.FakeDA3BenchmarkAdapter())
    assert res2["status"] == "completed"

    with RunStore(db_path) as store:
        run2_data = store.get_run(res2["run_id"])
        cfg2 = run2_data.config_snapshot
        assert "card" in cfg2
        assert cfg2["card"] is None


def test_runner_corrupted_registration_fails_loudly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """REGISTERED.json 存在但内容损坏时，大声失败抛出 PreflightError，不静默退回 r1。"""
    fake_repo = tmp_path / "corrupt_repo"
    fake_t28 = fake_repo / "reports/V9-T28"
    fake_t28.mkdir(parents=True, exist_ok=True)
    (fake_t28 / "REGISTERED.json").write_text("{corrupt json", encoding="utf-8")
    monkeypatch.setattr(t28_registration, "REPO_ROOT", fake_repo)

    with pytest.raises(R.PreflightError, match="Failed to read T28 registration"):
        R.get_default_proposal_path()


def test_real_venv_t6_runner_script_execution_without_pythonpath(tmp_path: Path):
    """集成测试：用 envs/teachers/.venv-t6/bin/python，不带 PYTHONPATH，以脚本方式跑 --preflight-only。"""
    import os
    import subprocess

    t6_python = REPO_ROOT / "envs/teachers/.venv-t6/bin/python"
    if not t6_python.is_file():
        pytest.skip(f".venv-t6 python not found at {t6_python}")

    custom_runner = os.environ.get("DA3_RUNNER_SCRIPT")
    runner_script = Path(custom_runner) if custom_runner else REPO_ROOT / "src/ainerzero/v9/teachers/da3_calibration_runner.py"
    r1_proposal = REPO_ROOT / "reports/V9-T28/proposal.json"
    pre_e18_proposal = REPO_ROOT / "reports/V9-T28/r2/pre-E18-1694ed30/proposal.json"

    # Base clean env without PYTHONPATH
    clean_env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    # 1. Default (reads registered proposal, i.e. r2) -> exit code 0
    out1 = tmp_path / "out1.json"
    pred1 = tmp_path / "pred1"
    res1 = subprocess.run(
        [str(t6_python), str(runner_script), "--preflight-only", "--output", str(out1), "--predictions-dir", str(pred1)],
        cwd=str(REPO_ROOT),
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0, f"Default preflight in .venv-t6 failed: {res1.stdout}\n{res1.stderr}"
    assert "preflight" in res1.stdout

    # 2. T6_PROPOSAL_PATH pointing to r1 -> non-zero (exit 2)
    out2 = tmp_path / "out2.json"
    pred2 = tmp_path / "pred2"
    env_r1 = dict(clean_env)
    env_r1["T6_PROPOSAL_PATH"] = str(r1_proposal)
    res2 = subprocess.run(
        [str(t6_python), str(runner_script), "--preflight-only", "--output", str(out2), "--predictions-dir", str(pred2)],
        cwd=str(REPO_ROOT),
        env=env_r1,
        capture_output=True,
        text=True,
    )
    assert res2.returncode != 0, f"Expected non-zero exit for T6_PROPOSAL_PATH=r1, got {res2.returncode}"
    assert res2.returncode == 2

    # 3. --proposal pointing to pre-E18 -> non-zero (exit 2)
    out3 = tmp_path / "out3.json"
    pred3 = tmp_path / "pred3"
    res3 = subprocess.run(
        [str(t6_python), str(runner_script), "--preflight-only", "--output", str(out3), "--predictions-dir", str(pred3),
         "--proposal", str(pre_e18_proposal)],
        cwd=str(REPO_ROOT),
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert res3.returncode != 0, f"Expected non-zero exit for pre-E18 proposal, got {res3.returncode}"
    assert res3.returncode == 2

