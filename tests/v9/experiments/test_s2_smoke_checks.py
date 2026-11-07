"""Unit tests for S2 smoke sanity and oracle feasibility checks (ainerzero.V9.P152).

Pure CPU, pure NumPy. Zero MLX imports.
Tests:
1. short_train_sanity:
   - Loss decreases with step count: passes.
   - Loss increases with step count: fails.
   - NaN encountered: fails.
   - SIGReg increases to 1.5x initial: fails.
2. action_sensitivity:
   - Model ignoring action: returns 0.0.
   - Model responsive to actions: returns > 0.05.
   - Hand-calculated analytic test matching exact formula.
3. oracle_feasibility:
   - True world dynamics on 2 worlds x 6 long goals: success rate >> 0.05.
   - Extremely constrained budget (N_fwd=8): success rate < 0.05, fuse triggers.
4. Anti-fabrication AST scan:
   - Ensures no dictionary literals containing constant fake metrics.
"""

from __future__ import annotations

import ast
import math
import random
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import smoke_checks, world


# -----------------------------------------------------------------------------
# 1. Fake Arms for short_train_sanity
# -----------------------------------------------------------------------------


class FakeDecreasingArm:
    """Arm whose loss monotonically decreases."""

    def __init__(self, initial_loss: float = 2.0, decay: float = 0.99) -> None:
        self.loss = initial_loss
        self.decay = decay
        self.step_count = 0

    def train_step(self, batch: Any) -> dict[str, float]:
        self.step_count += 1
        self.loss *= self.decay
        return {"loss": self.loss}


class FakeIncreasingArm:
    """Arm whose loss increases over time."""

    def __init__(self, initial_loss: float = 1.0, growth: float = 1.01) -> None:
        self.loss = initial_loss
        self.growth = growth

    def train_step(self, batch: Any) -> dict[str, float]:
        self.loss *= self.growth
        return {"loss": self.loss}


class FakeNaNArm:
    """Arm that produces NaN at step 25."""

    def __init__(self) -> None:
        self.step_count = 0

    def train_step(self, batch: Any) -> dict[str, float]:
        self.step_count += 1
        if self.step_count == 25:
            return {"loss": float("nan")}
        return {"loss": 1.0 / self.step_count}


# -----------------------------------------------------------------------------
# Tests: short_train_sanity
# -----------------------------------------------------------------------------


def test_short_train_sanity_decreasing_loss_passes() -> None:
    """NumPy 假臂，损失随步数下降：通过。"""
    arm = FakeDecreasingArm(initial_loss=2.0, decay=0.98)
    batches = [{"x": i} for i in range(50)]

    res = smoke_checks.short_train_sanity(arm, batches, S=40)
    assert res["passed"] is True
    assert res["all_losses_finite"] is True
    assert res["loss_decreased"] is True
    assert res["mean_last_window"] < res["mean_first_window"]
    assert len(res["reasons"]) == 0


def test_short_train_sanity_increasing_loss_fails() -> None:
    """假臂损失上升：不通过。"""
    arm = FakeIncreasingArm(initial_loss=1.0, growth=1.02)
    batches = [{"x": i} for i in range(50)]

    res = smoke_checks.short_train_sanity(arm, batches, S=40)
    assert res["passed"] is False
    assert res["all_losses_finite"] is True
    assert res["loss_decreased"] is False
    assert res["mean_last_window"] > res["mean_first_window"]
    assert any("Loss did not decrease" in r for r in res["reasons"])


def test_short_train_sanity_nan_loss_fails() -> None:
    """出现 NaN：不通过。

    Catches mutation P152-M1 (omitting NaN / finite check).
    """
    arm = FakeNaNArm()
    batches = [{"x": i} for i in range(50)]

    res = smoke_checks.short_train_sanity(arm, batches, S=40)
    assert res["passed"] is False
    assert res["all_losses_finite"] is False
    assert any("Non-finite loss" in r for r in res["reasons"])


def test_short_train_sanity_sigreg_increase_fails() -> None:
    """SIGReg 末值是初值的 1.5 倍：不通过。"""
    arm = FakeDecreasingArm(initial_loss=2.0, decay=0.98)
    batches = [{"x": i} for i in range(50)]

    sigreg_calls = [1.0, 1.5]  # initial=1.0, final=1.5 (> 1.1x)
    call_idx = 0

    def sigreg_probe(*args: Any) -> float:
        nonlocal call_idx
        val = sigreg_calls[min(call_idx, len(sigreg_calls) - 1)]
        call_idx += 1
        return val

    res = smoke_checks.short_train_sanity(arm, batches, S=40, sigreg_probe=sigreg_probe)
    assert res["passed"] is False
    assert res["sigreg_stable"] is False
    assert res["initial_sigreg"] == 1.0
    assert res["final_sigreg"] == 1.5
    assert any("SIGReg increased above 1.1x" in r for r in res["reasons"])


def test_short_train_sanity_sigreg_stable_passes() -> None:
    """SIGReg 末值 <= 1.1x 初值：通过。"""
    arm = FakeDecreasingArm(initial_loss=2.0, decay=0.98)
    batches = [{"x": i} for i in range(50)]

    sigreg_calls = [1.0, 1.05]  # initial=1.0, final=1.05 (<= 1.1x)
    call_idx = 0

    def sigreg_probe(*args: Any) -> float:
        nonlocal call_idx
        val = sigreg_calls[min(call_idx, len(sigreg_calls) - 1)]
        call_idx += 1
        return val

    res = smoke_checks.short_train_sanity(arm, batches, S=40, sigreg_probe=sigreg_probe)
    assert res["passed"] is True
    assert res["sigreg_stable"] is True
    assert res["initial_sigreg"] == 1.0
    assert res["final_sigreg"] == 1.05


# -----------------------------------------------------------------------------
# Tests: action_sensitivity
# -----------------------------------------------------------------------------


def test_action_sensitivity_zero_when_ignoring_action() -> None:
    """动作完全不影响预测的假模型：值为 0。"""
    def dummy_predict(z: np.ndarray, a: Any) -> np.ndarray:
        return z.copy()

    states = [np.array([1.0, 2.0]), np.array([3.0, 4.0]), np.array([0.5, 1.5])]
    score = smoke_checks.action_sensitivity(dummy_predict, states, n_actions=4)
    assert math.isclose(score, 0.0, abs_tol=1e-12)


def test_action_sensitivity_responsive_model_above_floor() -> None:
    """动作影响明显的假模型：值 > 0.05。"""
    def responsive_predict(z: np.ndarray, a: Any) -> np.ndarray:
        act_idx = int(a) if isinstance(a, (int, np.integer)) else int(np.argmax(a))
        deltas = [
            np.array([0.5, 0.0]),
            np.array([-0.5, 0.0]),
            np.array([0.0, 0.5]),
            np.array([0.0, -0.5]),
        ]
        return z + deltas[act_idx]

    states = [np.array([1.0, 1.0]), np.array([2.0, 0.0]), np.array([0.0, 2.0])]
    score = smoke_checks.action_sensitivity(responsive_predict, states, n_actions=4)
    assert score > 0.05


def test_action_sensitivity_hand_calculated_exact_formula() -> None:
    """用手算的小例子核对公式：
    单个状态 z = [1.0, 0.0], ||z|| = 1.0
    4 个动作给出:
      z'_0 = [1, 0]
      z'_1 = [0, 1]
      z'_2 = [-1, 0]
      z'_3 = [0, -1]
    6 个两两距离分别为: sqrt(2), 2, sqrt(2), sqrt(2), 2, sqrt(2)
    平均距离 = (4*sqrt(2) + 4) / 6 = (2*sqrt(2) + 2) / 3 ≈ 1.6094757
    除以 ||z|| (1.0) = (2*sqrt(2) + 2) / 3。
    """
    cardinal_states = [
        np.array([1.0, 0.0]),
        np.array([0.0, 1.0]),
        np.array([-1.0, 0.0]),
        np.array([0.0, -1.0]),
    ]

    def exact_predict(z: np.ndarray, a: Any) -> np.ndarray:
        act_idx = int(a) if isinstance(a, (int, np.integer)) else int(np.argmax(a))
        return cardinal_states[act_idx]

    single_state = [np.array([1.0, 0.0])]
    score = smoke_checks.action_sensitivity(exact_predict, single_state, n_actions=4)

    expected = (2.0 * math.sqrt(2.0) + 2.0) / 3.0
    assert math.isclose(score, expected, rel_tol=1e-9)


# -----------------------------------------------------------------------------
# Tests: oracle_feasibility
# -----------------------------------------------------------------------------


def test_oracle_feasibility_on_gridlab_two_worlds() -> None:
    """在 GridLab-S2 上用真实动力学跑 2 个世界 × 6 个长目标：
    成功率应明显高于 0.05，报告实际数字。
    """
    episodes: list[dict[str, Any]] = []
    for w_seed in (101, 102):
        rng = random.Random(w_seed)
        layout, pairs, _ = world.prepare_world_with_long_pairs(seed=w_seed, rng=rng)
        for pair in pairs:
            episodes.append({"layout": layout, "spec": pair})

    assert len(episodes) == 12

    # 使用默认 threshold (0.05)
    res = smoke_checks.oracle_feasibility(episodes, n_fwd=2000, rng=42)
    assert res["passed"] is True
    assert res["fuse_triggered"] is False
    assert res["threshold"] == 0.05, f"Default threshold must be 0.05, got {res['threshold']}"
    assert res["total_episodes"] == 12
    # 真实动力学下成功率应当很高 (远高于 0.05)
    assert res["success_rate"] > 0.50, f"Expected success_rate > 0.50, got {res['success_rate']}"
    assert res["successful_episodes"] >= 6


def test_oracle_feasibility_partial_success_does_not_fuse_at_005() -> None:
    """当成功率为 0.25 时，在 0.05 阈值下不应熔断；若阈值被改成 0.5 则必变红。"""
    # 构造 4 个回合的假规划器：只有 1 个成功（成功率 0.25）
    episodes: list[dict[str, Any]] = []
    w_seed = 101
    rng = random.Random(w_seed)
    layout, pairs, _ = world.prepare_world_with_long_pairs(seed=w_seed, rng=rng)
    for pair in pairs[:4]:
        episodes.append({"layout": layout, "spec": pair})

    call_count = 0

    def mock_planner_quarter_success(**kwargs: Any):
        nonlocal call_count
        call_count += 1
        # 只有第 1 个成功，其余失败
        succ = (call_count == 1)
        return succ, 50, []

    res = smoke_checks.oracle_feasibility(episodes, planner_fn=mock_planner_quarter_success, n_fwd=2000)
    assert res["success_rate"] == 0.25
    assert res["fuse_triggered"] is False, "0.25 success rate should NOT trigger fuse under 0.05 threshold"
    assert res["passed"] is True


def test_oracle_feasibility_budget_fuse_triggered() -> None:
    """再构造一个预算极小（N_fwd=8）的情形：成功率应 < 0.05，熔断。

    Catches mutation P152-M2 (relaxing fuse threshold or ignoring budget exceeded).
    """
    episodes: list[dict[str, Any]] = []
    for w_seed in (101, 102):
        rng = random.Random(w_seed)
        layout, pairs, _ = world.prepare_world_with_long_pairs(seed=w_seed, rng=rng)
        for pair in pairs:
            episodes.append({"layout": layout, "spec": pair})

    res = smoke_checks.oracle_feasibility(episodes, n_fwd=8, rng=42, threshold=0.05)
    assert res["passed"] is False
    assert res["fuse_triggered"] is True
    assert res["success_rate"] < 0.05
    assert res["successful_episodes"] == 0


def test_oracle_feasibility_fuse_threshold_boundary() -> None:
    """熔断阈值边界检验：当阈值设置高于实际成功率时，精确触发熔断。"""
    episodes: list[dict[str, Any]] = []
    w_seed = 101
    rng = random.Random(w_seed)
    layout, pairs, _ = world.prepare_world_with_long_pairs(seed=w_seed, rng=rng)
    for pair in pairs[:2]:
        episodes.append({"layout": layout, "spec": pair})

    # Set threshold to 1.5 (impossible to meet)
    res = smoke_checks.oracle_feasibility(episodes, n_fwd=2000, rng=42, threshold=1.5)
    assert res["fuse_triggered"] is True
    assert res["passed"] is False


# -----------------------------------------------------------------------------
# Tests: Anti-fabrication AST Scan
# -----------------------------------------------------------------------------


def test_anti_fabrication_ast_scan() -> None:
    """用 ast 扫描 smoke_checks.py，函数体里不得出现形如
    "long_goal_success_rates": {…数字…} 的字典字面量，也不得出现指标名直接赋予数字常量。

    Catches mutation P152-M3 (stuffing constant metric dictionary literal).
    """
    source_file = Path(smoke_checks.__file__).resolve()
    tree = ast.parse(source_file.read_text(encoding="utf-8"))

    forbidden_metric_names = {
        "long_goal_success_rates",
        "delta_sigreg",
        "action_sensitivity",
        "subgoal_shuffle_drop",
    }

    for node in ast.walk(tree):
        # 1. 检查字典字面量中的键
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and k.value in forbidden_metric_names:
                    raise AssertionError(
                        f"Forbidden metric dictionary key found in {source_file}: {k.value!r}"
                    )

        # 2. 检查指标变量直接赋常量数字
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in forbidden_metric_names:
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, (int, float)):
                        raise AssertionError(
                            f"Forbidden constant assignment to metric variable {target.id} = {node.value.value}"
                        )


def test_oracle_feasibility_with_s2_planner_two_worlds() -> None:
    """P154: 在 GridLab-S2 上用 s2 规划器跑 2 个世界 x 6 个长目标：
    成功率应明显高于 0.50，并在 N_fwd=8 极端紧缩时触发熔断。
    """
    episodes: list[dict[str, Any]] = []
    for w_seed in (101, 102):
        rng = random.Random(w_seed)
        layout, pairs, _ = world.prepare_world_with_long_pairs(seed=w_seed, rng=rng)
        for pair in pairs:
            episodes.append({"layout": layout, "spec": pair})

    assert len(episodes) == 12

    # 1. N_fwd = 4096 (正常规划预算) -> 成功率 > 0.50
    res = smoke_checks.oracle_feasibility_with_s2_planner(episodes, n_fwd=4096, rng=42)
    assert res["passed"] is True
    assert res["fuse_triggered"] is False
    assert res["threshold"] == 0.05
    assert res["total_episodes"] == 12
    assert res["planner"] == "s2_planner"
    assert res["success_rate"] > 0.50, f"Expected success_rate > 0.50, got {res['success_rate']}"
    assert res["successful_episodes"] >= 6

    # 2. N_fwd = 8 (极低预算) -> 必然触发熔断
    res_low = smoke_checks.oracle_feasibility_with_s2_planner(episodes, n_fwd=8, rng=42)
    assert res_low["fuse_triggered"] is True
    assert res_low["passed"] is False
    assert res_low["success_rate"] < 0.05


def test_oracle_feasibility_missing_bfs_distance_raises() -> None:
    """When episode spec lacks bfs_distance, both oracle_feasibility and oracle_feasibility_with_s2_planner must raise ValueError."""
    layout, pairs, _ = world.prepare_world_with_long_pairs(seed=101, rng=random.Random(101))
    bad_pair = dict(pairs[0])
    del bad_pair["bfs_distance"]
    episodes = [{"layout": layout, "spec": bad_pair}]

    with pytest.raises(ValueError, match="Missing bfs_distance in episode spec 0"):
        smoke_checks.oracle_feasibility(episodes, n_fwd=16)

    with pytest.raises(ValueError, match="Missing bfs_distance in episode spec 0"):
        smoke_checks.oracle_feasibility_with_s2_planner(episodes, n_fwd=16)


def test_oracle_feasibility_missing_start_or_goal_raises() -> None:
    """When episode spec lacks start or goal, ValueError must name the missing field."""
    layout, pairs, _ = world.prepare_world_with_long_pairs(seed=101, rng=random.Random(101))

    bad_pair_start = dict(pairs[0])
    del bad_pair_start["start"]
    with pytest.raises(ValueError, match="Missing start in episode spec 0"):
        smoke_checks.oracle_feasibility([{"layout": layout, "spec": bad_pair_start}], n_fwd=16)

    bad_pair_goal = dict(pairs[0])
    del bad_pair_goal["goal"]
    with pytest.raises(ValueError, match="Missing goal in episode spec 0"):
        smoke_checks.oracle_feasibility([{"layout": layout, "spec": bad_pair_goal}], n_fwd=16)


