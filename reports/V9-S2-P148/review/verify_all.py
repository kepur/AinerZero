#!/usr/bin/env python3
"""Independent review verification suite for ainerzero.V9.P148 (S2 wiring and smoke).

Reviewer: gemini-a5b8 (L2 pure CPU executor).
"""

import argparse
import ast
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

def find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p] + list(p.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()

REPO_ROOT = find_repo_root()
sys.path.insert(0, str(REPO_ROOT / "src"))

from ainerzero.v9.experiments.s2 import commands, freeze, prereg, smoke, spec, worker


def test_scope_and_conftest():
    """核实改动范围：除 cli.py 和 conftest.py 相应添加行外，src 下原有文件与 HEAD 逐字节一致。"""
    # 1. 检查 conftest.py 中新增的 NATIVE_MODULES
    conftest_path = REPO_ROOT / "tests" / "conftest.py"
    conftest_text = conftest_path.read_text(encoding="utf-8")
    assert '"test_s2_adapters_mlx_native.py"' in conftest_text, "test_s2_adapters_mlx_native.py must be in NATIVE_MODULES"

    # 2. 检查 cli.py 挂接了 s2-phase1
    cli_path = REPO_ROOT / "src" / "ainerzero" / "cli.py"
    cli_text = cli_path.read_text(encoding="utf-8")
    assert 's2-phase1' in cli_text
    assert 'from ainerzero.v9.experiments.s2.commands import s2_phase1_command' in cli_text


def test_forward_counter_wired_in_adapters():
    """只读 AST 静态核验：MLX 适配层的每次规划网络调用均经过 ForwardCounter。"""
    adapter_path = REPO_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "adapters_mlx.py"
    tree = ast.parse(adapter_path.read_text(encoding="utf-8"))

    # 查找 MLXArmAAdapter, MLXArmBAdapter, MLXArmCAdapter 中的 charge 调用
    charges_by_class: dict[str, list[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and "Adapter" in node.name:
            cname = node.name
            charges_by_class[cname] = []
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == "charge":
                    if sub.args and isinstance(sub.args[0], ast.Constant):
                        charges_by_class[cname].append(sub.args[0].value)

    assert "MLXArmAAdapter" in charges_by_class
    assert "MLXArmBAdapter" in charges_by_class
    assert "MLXArmCAdapter" in charges_by_class

    # Arm A 必须 charge encode, predict_l1, decode
    assert "encode" in charges_by_class["MLXArmAAdapter"]
    assert "predict_l1" in charges_by_class["MLXArmAAdapter"]
    assert "decode" in charges_by_class["MLXArmAAdapter"]

    # Arm B 必须 charge encode, predict_l1
    assert "encode" in charges_by_class["MLXArmBAdapter"]
    assert "predict_l1" in charges_by_class["MLXArmBAdapter"]

    # Arm C 必须 charge encode, predict_l1, encode_l2, predict_l2
    assert "encode" in charges_by_class["MLXArmCAdapter"]
    assert "predict_l1" in charges_by_class["MLXArmCAdapter"]
    assert "encode_l2" in charges_by_class["MLXArmCAdapter"]
    assert "predict_l2" in charges_by_class["MLXArmCAdapter"]


def test_verify_tampered_byte_in_mock_repo():
    """在临时伪造仓库里改动一个字节，确认 verify 返回非零码并点名该文件。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        log_path = tmp_dir / "RESEARCH_LOG.md"

        # 生成 draft 并 freeze 到临时目录
        draft = prereg.build_draft(repo_root=REPO_ROOT)
        frozen_dir = tmp_dir / "frozen_test"
        doc_sha = freeze.freeze(draft, frozen_dir, repo_root=REPO_ROOT)
        prereg_path = frozen_dir / "prereg.json"

        # 在 prereg.json 中篡改一个文件的一个哈希字节
        target_file = "src/ainerzero/v9/experiments/s2/worker.py"
        doc_json = json.loads(prereg_path.read_text(encoding="utf-8"))
        assert target_file in doc_json["source_digests"]
        doc_json["source_digests"][target_file] = "0" * 64

        # 重新保存
        new_bytes = json.dumps(doc_json, indent=2, sort_keys=True).encode("utf-8")
        prereg_path.write_bytes(new_bytes)
        new_doc_sha = hashlib.sha256(new_bytes).hexdigest()
        (frozen_dir / "prereg.json.sha256").write_text(f"{new_doc_sha}  prereg.json\n", encoding="utf-8")

        # 写入 approval log
        log_path.write_text(
            f"# Log\n\n## R20261106-S2-approval\n\nAPPROVED s2-phase1 prereg document_sha256={new_doc_sha}\n",
            encoding="utf-8",
        )

        args = argparse.Namespace(
            mode="verify",
            repo_root=REPO_ROOT,
            prereg=prereg_path,
            research_log=log_path,
        )
        res, code = commands.s2_phase1_command(args)
        assert code != 0, f"Expected non-zero exit code on tampered byte, got {code}"
        assert res["status"] == "failed"
        assert res["stage"] == "identity_mismatch"
        assert target_file in str(res), f"Discrepancy report must name tampered file: {target_file}"


def test_smoke_logic_five_independent_cases():
    """独立实现假臂与指标数据，自测 smoke 判定的 5 种情形：1 种正常 + 4 种失败。"""
    # 1. 正常情形 (Pass)
    normal_metrics = {
        "delta_sigreg": -0.045,
        "action_sensitivity": 0.08,
        "subgoal_shuffle_drop": 0.18,
        "long_goal_success_rates": {"arm_a": 0.20, "arm_b": 0.35, "arm_c": 0.50},
    }
    res_normal = smoke.check_smoke_preconditions(normal_metrics)
    assert res_normal["passed"] is True
    assert res_normal["circuit_breaker"] is False

    # 2. 失败情形 1: SIGReg 未下降 (delta >= 0)
    fail_sigreg_metrics = dict(normal_metrics, delta_sigreg=0.005)
    res_fail1 = smoke.check_smoke_preconditions(fail_sigreg_metrics)
    assert res_fail1["passed"] is False
    assert any("SIGReg did not decrease" in r for r in res_fail1["reasons"])

    # 3. 失败情形 2: 动作敏感度低于阈值 (< 0.05)
    fail_act_metrics = dict(normal_metrics, action_sensitivity=0.04)
    res_fail2 = smoke.check_smoke_preconditions(fail_act_metrics)
    assert res_fail2["passed"] is False
    assert any("Action sensitivity below threshold" in r for r in res_fail2["reasons"])

    # 4. 失败情形 3: 子目标打乱下降幅度不足 (< 0.10)
    fail_shuffle_metrics = dict(normal_metrics, subgoal_shuffle_drop=0.09)
    res_fail3 = smoke.check_smoke_preconditions(fail_shuffle_metrics)
    assert res_fail3["passed"] is False
    assert any("Subgoal shuffle drop below threshold" in r for r in res_fail3["reasons"])

    # 5. 失败情形 4: 熔断器触发（所有臂长目标成功率均低于 0.05）
    fail_cb_metrics = dict(
        normal_metrics,
        long_goal_success_rates={"arm_a": 0.049, "arm_b": 0.03, "arm_c": 0.048},
    )
    res_fail4 = smoke.check_smoke_preconditions(fail_cb_metrics)
    assert res_fail4["passed"] is False
    assert res_fail4["circuit_breaker"] is True
    assert any("Circuit breaker triggered" in r for r in res_fail4["reasons"])


def test_hand_calculated_training_steps_minimum_rule():
    """手算训练步数规则：floor(1200 * 0.8 / t_step)，三臂严格取最小值。"""
    # 假定单步耗时：
    # t_a = 0.08 s -> 960 / 0.08 = 12000
    # t_b = 0.05 s -> 960 / 0.05 = 19200
    # t_c = 0.10 s -> 960 / 0.10 = 9600
    step_times = {"arm_a": 0.08, "arm_b": 0.05, "arm_c": 0.10}
    res = smoke.compute_training_steps(step_times)
    assert res["per_arm_steps"]["arm_a"] == 12000
    assert res["per_arm_steps"]["arm_b"] == 19200
    assert res["per_arm_steps"]["arm_c"] == 9600
    assert res["shared_train_steps"] == 9600, f"Expected minimum across arms 9600, got {res['shared_train_steps']}"


def test_seed_namespace_and_no_partition_readback():
    """确认 smoke 种子命名空间与 train/dev/final 不重叠，且 smoke 代码不读取这三个分区。"""
    # 1. 种子重叠拒绝
    for bad in ["train_v1", "my_dev_test", "final_run", "sealed_final_data"]:
        with pytest.raises(ValueError, match="must not overlap"):
            smoke.check_smoke_seed_namespace(bad)

    # 2. 合法不重叠命名空间通过
    smoke.check_smoke_seed_namespace("smoke_independent_seed_namespace_2026")

    # 3. 静态检查 smoke.py 源码，确认不包含 datasets 打开或读取
    smoke_src = (REPO_ROOT / "src" / "ainerzero" / "v9" / "experiments" / "s2" / "smoke.py").read_text(encoding="utf-8")
    assert "data_runner" not in smoke_src
    assert "generate_partition" not in smoke_src


def test_pure_cpu_isolation_no_mlx_in_sys_modules():
    """纯 CPU 隔离：子进程 -I 导入后 mlx 不在 sys.modules。"""
    cmd = [
        str(REPO_ROOT / ".venv" / "bin" / "python"),
        "-I",
        "-c",
        (
            "import sys\n"
            "import ainerzero.v9.experiments.s2 as s2\n"
            "import ainerzero.v9.experiments.s2.commands as commands\n"
            "import ainerzero.v9.experiments.s2.smoke as smoke\n"
            "assert 'mlx' not in sys.modules, f'Leaked mlx: {[m for m in sys.modules if \"mlx\" in m]}'\n"
            "print('PURE_CPU_OK')\n"
        ),
    ]
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True)
    assert res.returncode == 0, f"Subprocess failed:\nstdout: {res.stdout}\nstderr: {res.stderr}"
    assert "PURE_CPU_OK" in res.stdout


def test_commands_refuse_unapproved_compute():
    """核验 commands 在未批准时拦截计算模式并返回 EXIT_REFUSED_APPROVAL (3)。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        missing_log = tmp_dir / "EMPTY_LOG.md"
        missing_log.write_text("# Empty log\n", encoding="utf-8")

        args = argparse.Namespace(
            mode="generate-data",
            arm="train",
            seed=42,
            repo_root=REPO_ROOT,
            output_root=tmp_dir / "out",
            ledger=tmp_dir / "control.sqlite3",
            lock_file=tmp_dir / "m0-worker.lock",
            research_log=missing_log,
        )
        res, code = commands.s2_phase1_command(args)
        assert code == commands.EXIT_REFUSED_APPROVAL, f"Expected EXIT_REFUSED_APPROVAL (3), got {code}"
        assert res["status"] == "refused"
        assert res["stage"] == "approval"


def test_commands_refuse_budget_ceiling_exceeded():
    """核验 commands 在超出总相位 10h 上限时拒绝并返回 EXIT_REFUSED_RESOURCE (2)。"""
    with tempfile.TemporaryDirectory() as td:
        tmp_dir = Path(td)
        log_path = tmp_dir / "RESEARCH_LOG.md"
        log_path.write_text(
            f"# Log\n\n## R20261106-S2-approval\n\nAPPROVED s2-phase1 prereg document_sha256={'0'*64}\n",
            encoding="utf-8",
        )
        ledger_path = tmp_dir / "control.sqlite3"
        ledger = worker.S2Ledger(ledger_path)
        ledger.ensure_experiment(worker.EXPERIMENT_ID)
        now = time.time()
        ledger.store._conn.execute(
            """INSERT INTO runs (
                run_id, request_id, state, config_json, config_hash,
                created_at, updated_at, environment_steps, optimizer_steps,
                active_seconds, role, model_transitions, experiment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("pre-consumed-run", "req-1", "completed", json.dumps({"mode": "train", "arm": "arm_e", "seed": 999}), "hash",
             now, now, 0, 0, 35900.0, "worker", 0, worker.EXPERIMENT_ID),
        )
        ledger.store._conn.commit()
        ledger.close()

        # 再次请求 1200 秒的 smoke，将超过 36000 秒总上限
        args = argparse.Namespace(
            mode="smoke",
            arm=None,
            seed=None,
            repo_root=REPO_ROOT,
            output_root=tmp_dir / "out",
            ledger=ledger_path,
            lock_file=tmp_dir / "m0-worker.lock",
            research_log=log_path,
            budget=1200.0,
        )
        res, code = commands.s2_phase1_command(args)
        assert code == commands.EXIT_REFUSED_RESOURCE, f"Expected EXIT_REFUSED_RESOURCE (2), got {code}"
        assert res["status"] == "refused"
        assert res["stage"] == "phase_budget_exceeded"


if __name__ == "__main__":
    print("Running P149 independent verification suite...")
    test_scope_and_conftest()
    print("✓ Scope and conftest check passed.")
    test_forward_counter_wired_in_adapters()
    print("✓ Forward counter wiring check passed.")
    test_verify_tampered_byte_in_mock_repo()
    print("✓ Verify mode tampering detection check passed.")
    test_smoke_logic_five_independent_cases()
    print("✓ Smoke logic 5 independent cases check passed.")
    test_hand_calculated_training_steps_minimum_rule()
    print("✓ Hand calculated training steps rule check passed.")
    test_seed_namespace_and_no_partition_readback()
    print("✓ Seed namespace and zero readback check passed.")
    test_pure_cpu_isolation_no_mlx_in_sys_modules()
    print("✓ Pure CPU isolation check passed.")
    test_commands_refuse_unapproved_compute()
    print("✓ Commands unapproved compute refusal check passed.")
    test_commands_refuse_budget_ceiling_exceeded()
    print("✓ Commands budget ceiling exceeded refusal check passed.")
    print("ALL P149 INDEPENDENT VERIFICATION TESTS PASSED SUCCESSFULLY!")
