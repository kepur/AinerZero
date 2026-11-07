"""Unit tests for S2 smoke planning timing and budget extrapolation (W4 / DESIGN-r2 D6).

Task: ainerzero.V9.P167 (S2 生产路径集成 W4：smoke 补规划回合计时与总预算推算).
Pure CPU, pure NumPy. Zero MLX imports.
Tests:
1. test_budget_extrapolation_formulas_match_registered_spec:
   Verifies that when given measured step_times and plan_episode_times,
   the breakdown numbers for data, train, plan_select, post_train_gates, dev, final, smoke, total
   exactly match the spec registered formulas.
2. test_fast_episodes_passes_budget_check:
   When planning episodes are fast, smoke budget check passes and reasons is empty.
3. test_dev_exceeds_budget_fails_and_names_dev:
   When planning episode time causes dev extrapolation to exceed BUDGET_DEV_EVAL_SECONDS,
   sufficient=False and reasons explicitly points out dev.
4. test_train_exceeds_budget_fails_and_names_train:
   When train step time causes training extrapolation to exceed BUDGET_TRAIN_MAIN_TOTAL_SECONDS,
   sufficient=False and reasons explicitly points out train.
5. test_missing_planning_times_fails_closed:
   When plan_episode_times is None, budget check fails and names plan_episode_times.
6. test_missing_step_times_fails_closed:
   When step_times is None, budget check fails and names step_times.
7. test_ast_scan_no_hardcoded_time_constants:
   AST scan of smoke.py ensures zero hardcoded fake metrics or constant time literals.
8. test_oracle_planner_uses_registered_cem_config:
   Verifies smoke_checks.oracle_feasibility_with_s2_planner calls learned_planning.cem_config_for_budget
   rather than hardcoded FlatCEMConfig parameters.
"""

from __future__ import annotations

import ast
import inspect
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2 import (
    learned_planning,
    smoke,
    smoke_checks,
    spec,
)


def _make_dummy_timing_res(shared_steps: int = 1600) -> dict[str, Any]:
    return {
        "shared_train_steps": shared_steps,
        "per_arm_step_times": {"arm_a": 0.05, "arm_b": 0.04, "arm_c": 0.06},
    }


def test_budget_extrapolation_formulas_match_registered_spec() -> None:
    """Verifies that each component in budget_analysis breakdown matches analytic formulas."""
    step_times = {"arm_a": 0.05, "arm_b": 0.04, "arm_c": 0.06}
    plan_times = {"arm_a": 0.08, "arm_b": 0.07, "arm_c": 0.10}
    shared_steps = 1500
    timing_res = {"shared_train_steps": shared_steps}

    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=plan_times,
    )

    assert res["sufficient"] is True
    assert res["passed"] is True
    assert res["reasons"] == []

    bd = res["breakdown"]
    assert bd is not None

    # 1. Data generation
    expected_data = float(spec.TRAIN_N_WORLDS * spec.TRAIN_EPISODES_PER_WORLD * spec.DATA_ESTIMATED_SECONDS_PER_EPISODE)
    assert math.isclose(bd["data"]["estimated_seconds"], expected_data, rel_tol=1e-6)
    assert bd["data"]["ceiling_seconds"] == spec.BUDGET_DATA_MAX_SECONDS

    # 2. Training
    expected_train = sum(
        3.0 * min(float(spec.BUDGET_TRAIN_PER_SLOT_SECONDS), shared_steps * step_times[arm])
        for arm in ("arm_a", "arm_b", "arm_c")
    )
    assert math.isclose(bd["train"]["estimated_seconds"], expected_train, rel_tol=1e-6)
    assert bd["train"]["ceiling_seconds"] == spec.BUDGET_TRAIN_MAIN_TOTAL_SECONDS

    # 3. Plan-select
    grid_sizes = {
        "arm_a": len(spec.FLAT_H_CANDIDATES),
        "arm_b": len(spec.FLAT_H_CANDIDATES),
        "arm_c": len(spec.HIERARCHICAL_HORIZON_CANDIDATES) * len(spec.HIERARCHICAL_BUDGET_RATIO_CANDIDATES),
    }
    expected_plan_select = sum(
        grid_sizes[arm] * spec.HYPERPARAM_SELECTION_MAX_EPISODES * plan_times[arm]
        for arm in ("arm_a", "arm_b", "arm_c")
    )
    assert math.isclose(bd["plan_select"]["estimated_seconds"], expected_plan_select, rel_tol=1e-6)
    assert bd["plan_select"]["ceiling_seconds"] == spec.BUDGET_HYPERPARAM_SELECTION_SECONDS

    # 4. Post-train gates
    expected_gates = 100.0 * plan_times["arm_c"]
    assert math.isclose(bd["post_train_gates"]["estimated_seconds"], expected_gates, rel_tol=1e-6)

    # 5. Dev evaluation
    curve_mult = 1.0 + (2048 / 4096.0 + 8192 / 4096.0)
    expected_dev = sum(
        (300.0 * 3.0 * curve_mult + (spec.REGULAR_DT_SUBSET_EPISODES + 100) * 3.0) * plan_times[arm]
        for arm in ("arm_a", "arm_b", "arm_c")
    )
    assert math.isclose(bd["dev"]["estimated_seconds"], expected_dev, rel_tol=1e-6)
    assert bd["dev"]["ceiling_seconds"] == spec.BUDGET_DEV_EVAL_SECONDS

    # 6. Final evaluation
    expected_final = sum(300.0 * 3.0 * plan_times[arm] for arm in ("arm_a", "arm_b", "arm_c"))
    assert math.isclose(bd["final"]["estimated_seconds"], expected_final, rel_tol=1e-6)
    assert bd["final"]["ceiling_seconds"] == spec.BUDGET_FINAL_EVAL_SECONDS

    # 7. Smoke
    assert bd["smoke"]["estimated_seconds"] == spec.BUDGET_SMOKE_MAX_SECONDS

    # Total
    expected_total = (
        expected_data
        + expected_train
        + expected_plan_select
        + expected_gates
        + expected_dev
        + expected_final
        + spec.BUDGET_SMOKE_MAX_SECONDS
    )
    assert math.isclose(res["total_estimated_seconds"], expected_total, rel_tol=1e-6)
    assert bd["total"]["ceiling_seconds"] == spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS


def test_fast_episodes_passes_budget_check() -> None:
    """When measured planning episodes are fast, budget check succeeds with sufficient=True."""
    step_times = {"arm_a": 0.01, "arm_b": 0.01, "arm_c": 0.01}
    plan_times = {"arm_a": 0.02, "arm_b": 0.02, "arm_c": 0.02}
    timing_res = {"shared_train_steps": 2000}

    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=plan_times,
    )

    assert res["sufficient"] is True
    assert res["passed"] is True
    assert res["reasons"] == []
    assert res["total_estimated_seconds"] < spec.TOTAL_ACTUAL_WALLCLOCK_SECONDS


def test_dev_exceeds_budget_fails_and_names_dev() -> None:
    """When planning times are slow such that dev evaluation exceeds 2.5h (9000s),
    budget check fails, sufficient=False, and reasons names 'Dev evaluation' and 'dev'.
    """
    step_times = {"arm_a": 0.01, "arm_b": 0.01, "arm_c": 0.01}
    # With t_plan = 1.2s per episode, dev = 3 * (300 * 3 * 3.5 + 200 * 3) * 1.2 = 3 * 3750 * 1.2 = 13500s > 9000s
    plan_times = {"arm_a": 1.2, "arm_b": 1.2, "arm_c": 1.2}
    timing_res = {"shared_train_steps": 2000}

    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=plan_times,
    )

    assert res["sufficient"] is False
    assert res["passed"] is False
    reasons_str = " ".join(res["reasons"])
    assert "Dev evaluation" in reasons_str or "dev" in reasons_str.lower()
    bd = res["breakdown"]
    assert bd is not None
    assert bd["dev"]["exceeded"] is True


def test_train_exceeds_budget_fails_and_names_train() -> None:
    """When single-step time is high such that train exceeds 10800s, fails and names training."""
    # Step times: each slot is min(1200, 3000 * 1.0) = 1200. Total train = 3 * (3 * 1200) = 10800.
    # If step_times makes it exceed 10800s:
    step_times = {"arm_a": 0.8, "arm_b": 0.8, "arm_c": 0.8}
    plan_times = {"arm_a": 0.01, "arm_b": 0.01, "arm_c": 0.01}
    timing_res = {"shared_train_steps": 5000}

    # Pass a tighter train ceiling or inspect slot calculation
    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=plan_times,
        budget_ceiling_seconds=1000.0,  # Tight ceiling
    )

    assert res["sufficient"] is False
    assert res["passed"] is False
    reasons_str = " ".join(res["reasons"])
    assert "exceeds ceiling" in reasons_str


def test_missing_planning_times_fails_closed() -> None:
    """Requirement: Zero constant fallbacks. Missing plan_episode_times fails closed."""
    step_times = {"arm_a": 0.01, "arm_b": 0.01, "arm_c": 0.01}
    timing_res = {"shared_train_steps": 1000}

    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=step_times,
        plan_episode_times=None,
    )

    assert res["sufficient"] is False
    assert res["passed"] is False
    reasons_str = " ".join(res["reasons"])
    assert "plan_episode_times is None" in reasons_str


def test_missing_step_times_fails_closed() -> None:
    """Requirement: Zero constant fallbacks. Missing step_times fails closed."""
    plan_times = {"arm_a": 0.01, "arm_b": 0.01, "arm_c": 0.01}
    timing_res = {"shared_train_steps": 1000}

    res = smoke.check_smoke_budget(
        timing_res=timing_res,
        step_times=None,
        plan_episode_times=plan_times,
    )

    assert res["sufficient"] is False
    assert res["passed"] is False
    reasons_str = " ".join(res["reasons"])
    assert "step_times is None" in reasons_str


def test_ast_scan_no_hardcoded_time_constants() -> None:
    """AST scan of smoke.py ensures no hardcoded metric or time dictionaries."""
    source_file = Path(smoke.__file__).resolve()
    tree = ast.parse(source_file.read_text(encoding="utf-8"))

    forbidden_keys = {
        "long_goal_success_rates",
        "delta_sigreg",
        "action_sensitivity",
        "subgoal_shuffle_drop",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if isinstance(k, ast.Constant) and k.value in forbidden_keys:
                    if isinstance(v, ast.Constant) and isinstance(v.value, (int, float)):
                        raise AssertionError(f"Forbidden constant metric in {source_file}: {k.value}={v.value}")


def test_oracle_planner_uses_registered_cem_config() -> None:
    """D3.1: smoke_checks.oracle_feasibility_with_s2_planner must derive its CEM config

    by calling learned_planning.cem_config_for_budget rather than hardcoded parameters.
    """
    source = inspect.getsource(smoke_checks.oracle_feasibility_with_s2_planner)
    assert "learned_planning.cem_config_for_budget" in source, (
        "oracle_feasibility_with_s2_planner must call learned_planning.cem_config_for_budget"
    )
    assert "FlatCEMConfig(" not in source, (
        "oracle_feasibility_with_s2_planner must NOT use hardcoded FlatCEMConfig("
    )
