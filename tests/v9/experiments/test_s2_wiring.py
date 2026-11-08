"""Pure-CPU integration and wiring tests for S2 Phase 1 (ainerzero.V9.P148).

Pure CPU only (DOES NOT IMPORT MLX).
Uses fake models, fake arms, and mocks to test:
1. Each mode in commands.py dispatches to the true runner.
2. verify mode handles three cases:
   - prereg.json missing -> returns unfrozen (未冻结)
   - prereg.json valid -> returns verified
   - modified s2 file byte -> returns non-zero exit code and names the modified file
3. smoke mode logic:
   - normal fake arm passes
   - SIGReg not decreasing fails
   - action not sensitive fails
   - subgoal shuffle drop below threshold fails
   - all arms success < 0.05 triggers circuit breaker
   - training steps rule calculates floor(1200 * 0.8 / t) and takes minimum across arms
4. smoke seed namespace disjointness:
   - rejects train/dev/final overlapping namespaces
5. pure CPU isolation:
   - subprocess importing commands, smoke, train_runner, eval_runner does NOT leak mlx.
"""

from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import commands, freeze, smoke, smoke_checks, spec, worker


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in [current] + list(current.parents):
        if (parent / "pyproject.toml").is_file():
            return parent
    return current.parents[3]


def _make_dummy_research_log(path: Path, sha256_hex: str) -> None:
    path.write_text(
        f"# Research Log\n\n"
        f"## R20261106-S2-approval\n\n"
        f"APPROVED s2-phase1 prereg document_sha256={sha256_hex}\n",
        encoding="utf-8",
    )


# ==============================================================================
# 1. Runner Wiring Tests
# ==============================================================================


def test_commands_dispatch_to_runners(tmp_path: Path) -> None:
    """Verify that s2_phase1_command dispatches to each runner correctly."""
    repo_root = _find_repo_root()
    output_root = tmp_path / "output"
    output_root.mkdir(exist_ok=True)
    (output_root / "datasets" / "dev").mkdir(parents=True, exist_ok=True)
    (output_root / "datasets" / "sealed_final").mkdir(parents=True, exist_ok=True)
    (output_root / "dev_ledger.json").write_text(json.dumps({"passed": True}))
    (output_root / "plan_config.json").write_text(json.dumps({}))
    log_path = tmp_path / "RESEARCH_LOG.md"
    # Run modes require a frozen prereg + approval bound to its document SHA (commands Preflight 0, 11-07).
    from ainerzero.v9.experiments.s2 import prereg as s2_prereg

    frozen_sha = freeze.freeze(s2_prereg.build_draft(repo_root=repo_root), out_dir=output_root, repo_root=repo_root)
    _make_dummy_research_log(log_path, frozen_sha)

    # 1. generate-data
    with patch("ainerzero.v9.experiments.s2.data_runner.run_generate_data") as mock_data:
        def _data_side_effect(ledger, run_id, **kwargs):
            ledger.complete_run(run_id)
            return {"status": "completed", "n_episodes": 10}
        mock_data.side_effect = _data_side_effect

        args = argparse.Namespace(
            mode="generate-data",
            partition="train",
            seed=42,
            repo_root=repo_root,
            output_root=output_root,
            ledger=tmp_path / "control_gen.sqlite3",
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0
        assert mock_data.called
        assert mock_data.call_args.kwargs["partition"] == "train"

    # 2. train
    train_ledger_path = tmp_path / "control_train.sqlite3"
    led = worker.S2Ledger(train_ledger_path)
    rid = led.open_run(
        mode="smoke",
        arm=None,
        seed=None,
        cell_wall_budget=1200.0,
        snapshot_extra={"passed": True, "shared_train_steps": 200, "status": "completed"},
    )
    led.begin_run(rid, state="training")
    led.complete_run(rid, metrics={"passed": True, "shared_train_steps": 200, "status": "completed"})
    led.close()

    with patch("ainerzero.v9.experiments.s2.train_runner.run_train_cell") as mock_train:
        def _train_side_effect(ledger, run_id, **kwargs):
            ledger.complete_run(run_id)
            return {"status": "completed", "steps": 16}
        mock_train.side_effect = _train_side_effect

        args = argparse.Namespace(
            mode="train",
            arm="arm_a",
            seed=43,
            repo_root=repo_root,
            output_root=output_root,
            ledger=train_ledger_path,
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0
        assert mock_train.called
        assert mock_train.call_args.kwargs["arm_id"] == "arm_a"
        assert mock_train.call_args.kwargs["seed"] == 43

    # 3. plan-select
    with patch("ainerzero.v9.experiments.s2.eval_runner.run_plan_select") as mock_ps, \
         patch("ainerzero.v9.experiments.s2.eval_runner.run_post_train_gates", create=True) as mock_gates:
        def _ps_side_effect(**kwargs):
            (output_root / "plan_config.json").write_text("{}")
            return {"status": "completed"}
        mock_ps.side_effect = _ps_side_effect
        mock_gates.return_value = {"passed": True}

        fake_model = MagicMock()
        args = argparse.Namespace(
            mode="plan-select",
            arm="arm_a",
            seed=None,
            repo_root=repo_root,
            output_root=output_root,
            ledger=tmp_path / "control_ps.sqlite3",
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
            model_by_arm={"arm_a": fake_model, "arm_b": fake_model, "arm_c": fake_model},
            train_episode_specs=[{"partition": "train", "id": 1}],
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0 or res.get("result", {}).get("plan_select", {}).get("status") == "completed", f"Plan select failed: {res}"
        assert mock_ps.called

    # 4. dev-eval
    with patch("ainerzero.v9.experiments.s2.eval_runner.run_dev_eval") as mock_dev:
        def _dev_side_effect(**kwargs):
            return {"status": "completed"}
        mock_dev.side_effect = _dev_side_effect

        args = argparse.Namespace(
            mode="dev-eval",
            arm=None,
            seed=None,
            repo_root=repo_root,
            output_root=output_root,
            ledger=tmp_path / "control_dev.sqlite3",
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
            model_by_arm={"arm_a": MagicMock()},
            frozen_plan_config={"arms": {}},
            long_specs=[{"world_id": 0, "subset": "long"}],
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0
        assert mock_dev.called

    # 5. final-eval
    with patch("ainerzero.v9.experiments.s2.eval_runner.run_final_eval") as mock_final:
        def _final_side_effect(**kwargs):
            return {"status": "completed"}
        mock_final.side_effect = _final_side_effect

        args = argparse.Namespace(
            mode="final-eval",
            arm=None,
            seed=None,
            repo_root=repo_root,
            output_root=output_root,
            ledger=tmp_path / "control_final.sqlite3",
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
            model_by_arm={"arm_a": MagicMock()},
            frozen_plan_config={"arms": {}},
            long_specs=[{"world_id": 0, "subset": "long"}],
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0
        assert mock_final.called

    # 6. smoke
    with patch("ainerzero.v9.experiments.s2.smoke.run_smoke") as mock_smoke:
        def _smoke_side_effect(ledger, run_id, **kwargs):
            ledger.complete_run(run_id)
            return {"status": "completed", "passed": True}
        mock_smoke.side_effect = _smoke_side_effect

        args = argparse.Namespace(
            mode="smoke",
            arm=None,
            seed=None,
            repo_root=repo_root,
            output_root=output_root,
            ledger=tmp_path / "control_smoke.sqlite3",
            lock_file=tmp_path / "worker.lock",
            research_log=log_path,
        )
        res, code = commands.s2_phase1_command(args)
        assert code == 0
        assert mock_smoke.called
        assert mock_smoke.call_args.kwargs.get("execute_real") is True


# ==============================================================================
# 2. Verify Mode Three Cases
# ==============================================================================


def test_verify_case_unfrozen_when_prereg_missing(tmp_path: Path) -> None:
    """Case 1: When prereg.json does not exist, verify returns unfrozen (未冻结)."""
    repo_root = _find_repo_root()
    log_path = tmp_path / "RESEARCH_LOG.md"
    _make_dummy_research_log(log_path, "0" * 64)
    missing_prereg = tmp_path / "nonexistent_prereg.json"

    args = argparse.Namespace(
        mode="verify",
        repo_root=repo_root,
        prereg=missing_prereg,
        research_log=log_path,
    )
    res, code = commands.s2_phase1_command(args)
    assert code == 0
    assert res["status"] == "verified"
    assert res["prereg_status"] == "unfrozen"
    assert "未冻结" in res["message"]
    assert res["prereg_exists"] is False


def test_verify_case_frozen_valid_passes(tmp_path: Path) -> None:
    """Case 2: When prereg.json exists and current repo matches frozen identity, verify passes."""
    repo_root = _find_repo_root()
    log_path = tmp_path / "RESEARCH_LOG.md"

    from ainerzero.v9.experiments.s2 import prereg
    draft = prereg.build_draft(repo_root=repo_root)
    frozen_dir = tmp_path / "frozen_valid"
    doc_sha = freeze.freeze(draft, frozen_dir, repo_root=repo_root)
    prereg_path = frozen_dir / "prereg.json"

    _make_dummy_research_log(log_path, doc_sha)

    args = argparse.Namespace(
        mode="verify",
        repo_root=repo_root,
        prereg=prereg_path,
        research_log=log_path,
    )
    res, code = commands.s2_phase1_command(args)
    assert code == 0
    assert res["status"] == "verified"
    assert res["prereg_exists"] is True


def test_verify_case_tampered_byte_fails_and_names_file(tmp_path: Path) -> None:
    """Case 3: If an S2 file has a modified byte, verify fails non-zero and names the file."""
    repo_root = _find_repo_root()
    log_path = tmp_path / "RESEARCH_LOG.md"

    from ainerzero.v9.experiments.s2 import prereg
    draft = prereg.build_draft(repo_root=repo_root)
    frozen_dir = tmp_path / "frozen_tampered"
    doc_sha = freeze.freeze(draft, frozen_dir, repo_root=repo_root)
    prereg_path = frozen_dir / "prereg.json"

    # Tamper one file's hash in prereg.json
    target_file = "src/ainerzero/v9/experiments/s2/spec.py"
    doc_json = json.loads(prereg_path.read_text(encoding="utf-8"))
    assert target_file in doc_json["source_digests"]
    doc_json["source_digests"][target_file] = "f" * 64

    # Re-save tampered prereg.json and update companion sha
    new_bytes = json.dumps(doc_json, indent=2, sort_keys=True).encode("utf-8")
    prereg_path.write_bytes(new_bytes)
    new_doc_sha = hashlib.sha256(new_bytes).hexdigest()
    (frozen_dir / "prereg.json.sha256").write_text(f"{new_doc_sha}  prereg.json\n", encoding="utf-8")

    _make_dummy_research_log(log_path, new_doc_sha)

    args = argparse.Namespace(
        mode="verify",
        repo_root=repo_root,
        prereg=prereg_path,
        research_log=log_path,
    )
    res, code = commands.s2_phase1_command(args)
    assert code != 0, f"Tampered byte must return non-zero exit code, got {code}"
    assert res["status"] == "failed"
    assert target_file in str(res), f"Discrepancy must name {target_file}"


# ==============================================================================
# 3. Smoke Logic & Preconditions Tests
# ==============================================================================


def test_smoke_logic_normal_fake_arm_passes() -> None:
    """Verify normal fake arm metrics pass all smoke preconditions."""
    metrics = {
        "delta_sigreg": -0.08,
        "action_sensitivity": 0.12,
        "subgoal_shuffle_drop": 0.25,
        "long_goal_success_rates": {"arm_a": 0.35, "arm_b": 0.40, "arm_c": 0.55},
    }
    res = smoke.check_smoke_preconditions(metrics)
    assert res["passed"] is True
    assert res["circuit_breaker"] is False
    assert res["sigreg_decreased"] is True
    assert res["action_sensitive"] is True
    assert res["subgoal_shuffle_effective"] is True


def test_smoke_logic_sigreg_not_decreasing_fails() -> None:
    """Verify smoke fails if SIGReg fails to decrease (delta >= 0)."""
    metrics = {
        "delta_sigreg": 0.02,  # Not decreasing
        "action_sensitivity": 0.12,
        "subgoal_shuffle_drop": 0.25,
        "long_goal_success_rates": {"arm_a": 0.35, "arm_b": 0.40, "arm_c": 0.55},
    }
    res = smoke.check_smoke_preconditions(metrics)
    assert res["passed"] is False
    assert res["sigreg_decreased"] is False
    assert any("SIGReg did not decrease" in r for r in res["reasons"])


def test_smoke_logic_action_insensitivity_fails() -> None:
    """Verify smoke fails if action sensitivity is below threshold (0.05)."""
    metrics = {
        "delta_sigreg": -0.05,
        "action_sensitivity": 0.02,  # Below 0.05
        "subgoal_shuffle_drop": 0.25,
        "long_goal_success_rates": {"arm_a": 0.35, "arm_b": 0.40, "arm_c": 0.55},
    }
    res = smoke.check_smoke_preconditions(metrics)
    assert res["passed"] is False
    assert res["action_sensitive"] is False
    assert any("Action sensitivity below threshold" in r for r in res["reasons"])


def test_smoke_logic_subgoal_shuffle_insufficient_drop_fails() -> None:
    """Verify smoke fails if shuffling subgoals drops success by < 0.10."""
    metrics = {
        "delta_sigreg": -0.05,
        "action_sensitivity": 0.10,
        "subgoal_shuffle_drop": 0.03,  # Below 0.10
        "long_goal_success_rates": {"arm_a": 0.35, "arm_b": 0.40, "arm_c": 0.55},
    }
    res = smoke.check_smoke_preconditions(metrics)
    assert res["passed"] is False
    assert res["subgoal_shuffle_effective"] is False
    assert any("Subgoal shuffle drop below threshold" in r for r in res["reasons"])


def test_smoke_logic_circuit_breaker_when_all_arms_below_floor() -> None:
    """Verify circuit breaker triggers when all arms long-goal success rate < 0.05."""
    metrics = {
        "delta_sigreg": -0.05,
        "action_sensitivity": 0.10,
        "subgoal_shuffle_drop": 0.15,
        "long_goal_success_rates": {"arm_a": 0.02, "arm_b": 0.04, "arm_c": 0.03},
    }
    res = smoke.check_smoke_preconditions(metrics)
    assert res["passed"] is False
    assert res["circuit_breaker"] is True
    assert any("Circuit breaker triggered" in r for r in res["reasons"])

    # If at least one arm is above threshold, circuit breaker does not trigger
    metrics_one_good = copy.deepcopy(metrics)
    metrics_one_good["long_goal_success_rates"]["arm_c"] = 0.20
    res_good = smoke.check_smoke_preconditions(metrics_one_good)
    assert res_good["circuit_breaker"] is False


def test_smoke_timing_and_training_steps_minimum_rule() -> None:
    """Verify training steps = floor(1200 * 0.8 / t) and strictly takes minimum across arms."""
    step_times = {
        "arm_a": 0.05,  # 1200 * 0.8 / 0.05 = 19200
        "arm_b": 0.04,  # 1200 * 0.8 / 0.04 = 24000
        "arm_c": 0.06,  # 1200 * 0.8 / 0.06 = 16000
    }
    res = smoke.compute_training_steps(step_times)
    assert res["per_arm_steps"]["arm_a"] == 19200
    assert res["per_arm_steps"]["arm_b"] == 24000
    assert res["per_arm_steps"]["arm_c"] == 16000
    # Must be minimum, not maximum or mean
    assert res["shared_train_steps"] == 16000


class _DummySmokeArm:
    def __init__(self, n_params: int, decreasing: bool = True) -> None:
        self._n_params = n_params
        self.decreasing = decreasing
        self.step = 0

    def n_params(self) -> int:
        return self._n_params

    def train_step(self, batch: Any) -> dict[str, float]:
        self.step += 1
        l = 1.0 - (self.step * 0.003) if self.decreasing else 0.5 + (self.step * 0.003)
        return {"loss": float(l)}

    def evaluate_sigreg(self, *args: Any) -> float:
        return 0.5

    def encode(self, obs: Any) -> np.ndarray:
        arr = np.asarray(obs)
        if arr.ndim >= 2:
            return np.zeros((arr.shape[0], 64), dtype=np.float64)
        return np.zeros(64, dtype=np.float64)

    def latents(self, obs: Any) -> tuple[np.ndarray, np.ndarray]:
        arr = np.asarray(obs)
        if arr.ndim >= 2:
            z1 = np.zeros((arr.shape[0], 64), dtype=np.float64)
            z2 = np.zeros((arr.shape[0], 64), dtype=np.float64)
        else:
            z1 = np.zeros(64, dtype=np.float64)
            z2 = np.zeros(64, dtype=np.float64)
        return z1, z2

    def encode_l2(self, obs: Any) -> np.ndarray:
        arr = np.asarray(obs)
        if arr.ndim >= 2:
            return np.zeros((arr.shape[0], 64), dtype=np.float64)
        return np.zeros(64, dtype=np.float64)

    def predict_l1(self, z: np.ndarray, a: Any, dt: float = 1.0) -> np.ndarray:
        arr = np.asarray(z)
        if arr.ndim >= 2:
            return np.zeros((arr.shape[0], 64), dtype=np.float64)
        return np.zeros(64, dtype=np.float64)

    def predict_l2(self, z2: np.ndarray, a: Any, dt: float = 1.0) -> np.ndarray:
        arr = np.asarray(z2)
        if arr.ndim >= 2:
            return np.zeros((arr.shape[0], 64), dtype=np.float64)
        return np.zeros(64, dtype=np.float64)


def test_smoke_batch_shape_registered() -> None:
    """Requirement (2) & (3): Timing batch shape must strictly be (32, H_train+1, ...)."""
    batch = smoke.make_smoke_timing_batch()
    assert batch["observations"].shape == (spec.BATCH_SIZE, spec.H_TRAIN + 1, spec.OBS_DIM)
    assert batch["actions"].shape == (spec.BATCH_SIZE, spec.H_TRAIN + 1, spec.ACTION_DIM)
    assert batch["dts"].shape == (spec.BATCH_SIZE, spec.H_TRAIN + 1)


def test_smoke_no_injected_measurements_fails_with_named_reasons(tmp_path: Path) -> None:
    """Requirement (3): No injected measurements fails closed with status=failed, reasons naming missing items."""
    smoke_out = tmp_path / "smoke_no_measure"
    res = smoke.run_smoke(smoke_out)

    assert res["passed"] is False
    assert res["status"] == "failed"
    reasons_str = " ".join(res["reasons"])
    assert "arms_by_id" in reasons_str, f"reasons must name missing arms_by_id: {reasons_str}"
    assert "step_times" in reasons_str, f"reasons must name missing step_times: {reasons_str}"
    assert "plan_episode_times" in reasons_str, f"reasons must name missing plan_episode_times: {reasons_str}"
    assert "preconditions_metrics" in reasons_str, f"reasons must name missing preconditions_metrics: {reasons_str}"
    assert "Step 3" in reasons_str
    assert "Step 4" in reasons_str
    assert res["step_3_short_train"]["passed"] is False
    assert res["step_4_feasibility"]["passed"] is False
    assert res["budget_analysis"]["sufficient"] is False
    assert (smoke_out / "smoke_report.json").is_file()


def test_smoke_end_to_end_fake_arms_loss_increasing_fails_and_names_arms(tmp_path: Path) -> None:
    """P154: 注入 3 个 NumPy 假臂实现臂协议，其中一个损失下降、两个损失上升，
    smoke 必须 failed，并在 reasons 里明确点名后两个臂。
    """
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_end_to_end_increasing_fails"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=False),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=False),
    }
    fake_step_times = {
        "arm_a": 0.05,
        "arm_b": 0.04,
        "arm_c": 0.06,
    }

    res = smoke.run_smoke(
        smoke_out,
        arms_by_id=fake_arms,
        step_times=fake_step_times,
    )

    assert res["passed"] is False, "Smoke must fail when arms fail short-train sanity"
    assert res["status"] == "failed"
    reasons_str = " ".join(res["reasons"])
    assert "arm_b" in reasons_str, f"reasons must name arm_b: {reasons_str}"
    assert "arm_c" in reasons_str, f"reasons must name arm_c: {reasons_str}"


def test_smoke_end_to_end_fake_arms_all_decreasing_passes(tmp_path: Path) -> None:
    """P154: 注入 3 个损失持续下降的假臂，smoke 全流程通过 (status=completed, passed=True)。"""
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_end_to_end_passes"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=True),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=True),
    }
    fake_step_times = {
        "arm_a": 0.05,
        "arm_b": 0.04,
        "arm_c": 0.06,
    }

    res = smoke.run_smoke(
        smoke_out,
        arms_by_id=fake_arms,
        step_times=fake_step_times,
    )

    assert res["passed"] is True, f"Smoke must pass when all conditions met: {res.get('reasons')}"
    assert res["status"] == "completed"
    assert res["reasons"] == []
    assert (smoke_out / "smoke_report.json").is_file()
    assert res["step_4_feasibility"].get("planner") == "s2_planner"
    assert res["step_4_feasibility"].get("success_rate", 0.0) > 0.5


def test_smoke_anti_fabrication_ast_scan() -> None:
    """用 AST 扫描 smoke.py 和 smoke_checks.py，确认没有常数指标字典。"""
    for mod in (smoke, smoke_checks):
        source_file = Path(mod.__file__).resolve()
        tree = ast.parse(source_file.read_text(encoding="utf-8"))

        forbidden_keys = {"long_goal_success_rates", "delta_sigreg", "subgoal_shuffle_drop"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if isinstance(k, ast.Constant) and k.value in forbidden_keys:
                        # Forbid dictionary literals assigning constant numbers or constant dicts
                        if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                            raise AssertionError(f"Forbidden constant metric in {source_file}: {k.value}={v.value}")
                        if isinstance(v, ast.Dict):
                            for sub_v in v.values:
                                if isinstance(sub_v, ast.Constant) and isinstance(sub_v.value, (int, float)):
                                    raise AssertionError(f"Forbidden constant sub-dict in {source_file}: {k.value}")


def test_smoke_p154_m1_default_oracle_mpc_red(tmp_path: Path) -> None:
    """P154-M1 坏对照检测：熔断门必须由 oracle_feasibility_with_s2_planner 提供。"""
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_p154_m1"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=True),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=True),
    }
    fake_step_times = {"arm_a": 0.05, "arm_b": 0.04, "arm_c": 0.06}

    res = smoke.run_smoke(smoke_out, arms_by_id=fake_arms, step_times=fake_step_times)
    assert res["step_4_feasibility"].get("planner") == "s2_planner", (
        "熔断门必须由 s2 规划器驱动 (planner='s2_planner')"
    )


def test_smoke_p154_m2_ignore_step3_arm_failure_red(tmp_path: Path) -> None:
    """P154-M2 坏对照检测：第 3 步任一臂失败时整体必须判 failed。"""
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_p154_m2"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=False),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=True),
    }
    fake_step_times = {"arm_a": 0.05, "arm_b": 0.04, "arm_c": 0.06}

    res = smoke.run_smoke(smoke_out, arms_by_id=fake_arms, step_times=fake_step_times)
    assert res["passed"] is False, "任一臂失败整体必须判 failed"
    assert res["status"] == "failed"
    assert "arm_b" in " ".join(res["reasons"])


def test_smoke_p154_m3_rejects_train_dev_namespace(tmp_path: Path) -> None:
    """P154-M3 坏对照检测：smoke 严禁读取 train/dev/final 分区或使用其种子命名空间。"""
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_p154_m3"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=True),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=True),
    }
    fake_step_times = {"arm_a": 0.05, "arm_b": 0.04, "arm_c": 0.06}

    for bad_ns in ("train", "dev", "final"):
        with pytest.raises(ValueError, match="must not overlap"):
            smoke.run_smoke(
                smoke_out,
                arms_by_id=fake_arms,
                step_times=fake_step_times,
                seed_namespace=bad_ns,
            )


def test_smoke_over_budget_fails(tmp_path: Path) -> None:
    """Requirement (4): Measured total wall-clock exceeding 10h ceiling causes sufficient=False and fails smoke."""
    from ainerzero.v9.experiments.s2 import param_count

    smoke_out = tmp_path / "smoke_over_budget"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form()),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form()),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form()),
    }
    fake_step_times = {
        "arm_a": 0.05,
        "arm_b": 0.04,
        "arm_c": 0.06,
    }
    fake_metrics = {
        "delta_sigreg": -0.06,
        "action_sensitivity": 0.14,
        "subgoal_shuffle_drop": 0.22,
        "long_goal_success_rates": {"arm_a": 0.28, "arm_b": 0.32, "arm_c": 0.45},
    }

    # Pass a tiny ceiling (e.g. 1000 seconds) so total estimated (28200s) exceeds it
    res = smoke.run_smoke(
        smoke_out,
        arms_by_id=fake_arms,
        step_times=fake_step_times,
        preconditions_metrics=fake_metrics,
        budget_ceiling_seconds=1000.0,
    )

    assert res["passed"] is False
    assert res["status"] == "failed"
    assert res["budget_analysis"]["sufficient"] is False
    assert any("exceeds" in r or "ceiling" in r for r in res["reasons"])


# ==============================================================================
# 4. Smoke Seed Namespace Disjointness
# ==============================================================================


def test_smoke_seed_namespace_rejects_overlapping() -> None:
    """Verify smoke rejects seed namespaces overlapping with train, dev, or final."""
    for bad_ns in ("train", "train_seed_1", "dev", "my_dev_eval", "final", "sealed_final"):
        with pytest.raises(ValueError, match="must not overlap"):
            smoke.check_smoke_seed_namespace(bad_ns)

    # Disjoint namespace passes
    smoke.check_smoke_seed_namespace("smoke_isolated_namespace")


# ==============================================================================
# 5. Pure-CPU Isolation Check
# ==============================================================================


def test_pure_cpu_isolation_commands_and_smoke_do_not_import_mlx() -> None:
    """Verify importing commands, smoke, train_runner, eval_runner does NOT leak mlx."""
    repo_root = _find_repo_root()
    import site
    user_site = site.getusersitepackages()

    code = (
        f"import sys\n"
        f"sys.path.insert(0, '{user_site}')\n"
        f"sys.path.insert(0, '{repo_root}/src')\n"
        f"from ainerzero.v9.experiments.s2 import commands, smoke, train_runner, eval_runner\n"
        f"loaded_mlx = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]\n"
        f"assert not loaded_mlx, f'MLX modules leaked into sys.modules: {{loaded_mlx}}'\n"
        f"print('PURE_CPU_CLEAN')\n"
    )

    python_bin = repo_root / ".venv" / "bin" / "python"
    if not python_bin.exists():
        python_bin = Path(sys.executable)

    res = subprocess.run(
        [str(python_bin), "-I", "-c", code],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, f"Pure CPU check failed:\nstdout:\n{res.stdout}\nstderr:\n{res.stderr}"
    assert "PURE_CPU_CLEAN" in res.stdout


# ==============================================================================
# 6. S2 Clean-up Tests (ainerzero.V9.P160)
# ==============================================================================


def test_no_getattr_spec_with_default_in_s2_package() -> None:
    """AST scan of all s2 Python source files: forbid getattr(spec, <str>, <default>).

    Exception whitelist:
    - data_runner.py: getattr(spec, 'REGISTERED_HOST_ROOT', None) or ... (P138 transitional fallback).
    """
    repo_root = _find_repo_root()
    s2_dir = repo_root / "src" / "ainerzero" / "v9" / "experiments" / "s2"
    assert s2_dir.is_dir()

    violations = []
    for py_file in sorted(s2_dir.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
            ):
                if len(node.args) >= 3:
                    obj, attr = node.args[0], node.args[1]
                    if isinstance(obj, ast.Name) and obj.id == "spec":
                        attr_name = attr.value if isinstance(attr, ast.Constant) else None
                        # Whitelist check for data_runner.py P138 transitional fallback
                        if (
                            py_file.name == "data_runner.py"
                            and attr_name in ("REGISTERED_HOST_ROOT", "REGISTERED_OUTPUT_ROOT")
                        ):
                            continue
                        violations.append(
                            f"{py_file.name}:{node.lineno}: getattr(spec, {attr_name!r}, ...)"
                        )

    assert not violations, "Found forbidden getattr(spec, ..., default) calls:\n" + "\n".join(violations)


def test_smoke_fails_when_smoke_short_train_steps_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When spec.SMOKE_SHORT_TRAIN_STEPS is deleted, smoke must fail with AttributeError and not fall back silently."""
    from ainerzero.v9.experiments.s2 import param_count

    monkeypatch.delattr(spec, "SMOKE_SHORT_TRAIN_STEPS", raising=False)
    smoke_out = tmp_path / "smoke_no_train_steps"
    fake_arms = {
        "arm_a": _DummySmokeArm(param_count.count_arm_a_closed_form(), decreasing=True),
        "arm_b": _DummySmokeArm(param_count.count_arm_b_closed_form(), decreasing=True),
        "arm_c": _DummySmokeArm(param_count.count_arm_c_closed_form(), decreasing=True),
    }
    fake_batches = [{"observations": np.zeros((32, 17, 205), dtype=np.float32)}]

    # 1. generate_smoke_partition path must raise AttributeError
    with pytest.raises(AttributeError, match="SMOKE_SHORT_TRAIN_STEPS"):
        smoke.generate_smoke_partition(output_root=smoke_out)

    # 2. run_smoke step 3 path must raise AttributeError
    with pytest.raises(AttributeError, match="SMOKE_SHORT_TRAIN_STEPS"):
        smoke.run_smoke(smoke_out, arms_by_id=fake_arms, batches=fake_batches)
