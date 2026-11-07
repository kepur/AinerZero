"""Tests for S2 evaluation framework (run_episode, perturbation, irregular dt, and budgeting).

Pure CPU, NumPy only.
"""

from __future__ import annotations

import collections
import random
from typing import Any

import numpy as np
import pytest

from ainerzero.v9.experiments.s2.data import assert_k_distribution
from ainerzero.v9.experiments.s2.eval import (
    EpisodeResult,
    make_oracle_planner,
    make_random_planner,
    run_episode,
)
from ainerzero.v9.experiments.s2.fwd_counter import ForwardBudgetExceeded, ForwardCounter
from ainerzero.v9.experiments.s2.world import (
    ACTIONS,
    ACTION_FORWARD,
    ACTION_TURN_LEFT,
    ACTION_TURN_RIGHT,
    ACTION_WAIT,
    EAST,
    NORTH,
    Layout,
    State,
    make_layout,
    sample_goal,
    sample_start_goal_pair,
    truth,
)


def _get_test_layout(seed: int = 101) -> Layout:
    return make_layout(seed)


def test_oracle_planner_short_goal_success_rate() -> None:
    """Oracle planner achieves 100% success on short goals (bfs_dist <= 10)."""
    layout = _get_test_layout(seed=202)
    rng = random.Random(42)

    n_test_episodes = 5
    success_count = 0

    for ep_idx in range(n_test_episodes):
        start, goal, goal_obs, stats = sample_start_goal_pair(
            layout, rng, kind="short", max_pair_attempts=50
        )
        spec = {
            "start": truth(start),
            "goal": truth(goal),
            "goal_obs": goal_obs,
            "bfs_distance": stats["bfs_distance"],
            "perturb": False,
        }
        planner = make_oracle_planner(layout, goal, m=4)
        res = run_episode(
            layout,
            spec,
            planner,
            counter=None,
            rng=ep_idx + 100,
            dt_mode="regular",
            m=4,
        )
        if res.success:
            success_count += 1

    assert success_count == n_test_episodes, (
        f"Oracle failed short goal: {success_count}/{n_test_episodes} succeeded"
    )


def test_random_planner_inferior_to_oracle_on_long_goal() -> None:
    """Uniform random planner fails or achieves dramatically lower success than oracle on long goals."""
    layout = _get_test_layout(seed=303)
    rng = random.Random(77)

    start, goal, goal_obs, stats = sample_start_goal_pair(
        layout, rng, kind="long", max_pair_attempts=100
    )
    spec = {
        "start": truth(start),
        "goal": truth(goal),
        "goal_obs": goal_obs,
        "bfs_distance": stats["bfs_distance"],
        "perturb": False,
    }

    # Oracle run
    oracle_planner = make_oracle_planner(layout, goal, m=4)
    res_oracle = run_episode(
        layout,
        spec,
        oracle_planner,
        counter=None,
        rng=1,
        dt_mode="regular",
        m=4,
    )
    assert res_oracle.success, "Oracle failed long goal in regular mode"

    # Random planner run
    random_planner = make_random_planner(m=4, rng=42)
    res_random = run_episode(
        layout,
        spec,
        random_planner,
        counter=None,
        rng=2,
        dt_mode="regular",
        m=4,
    )
    assert not res_random.success, "Random planner unexpectedly solved long goal"


def test_perturb_inserts_at_step_20_and_is_reproducible() -> None:
    """Perturbation inserts exactly 5 random actions at step 20; planner resumes control at step 25;
    identical seed produces bit-for-bit output; and non-perturb episodes contain zero perturbation actions.

    Catches mutation P122-M2, P123 REV-M4 (perturb action count != 5), and perturb offset tampering.
    """
    layout = _get_test_layout(seed=404)
    rng = random.Random(88)

    start, goal, goal_obs, stats = sample_start_goal_pair(
        layout, rng, kind="long", max_pair_attempts=100
    )
    spec = {
        "start": truth(start),
        "goal": truth(goal),
        "goal_obs": goal_obs,
        "bfs_distance": stats["bfs_distance"],
        "perturb": True,
        "perturb_spec": {"at_step": 20, "n_random_actions": 5},
    }

    class TrackingPlanner:
        def __init__(self) -> None:
            self.call_history: list[int] = []

        def __call__(self, obs: Any, goal_obs: Any, **kwargs: Any) -> list[int]:
            call_id = len(self.call_history)
            self.call_history.append(call_id)
            # Decisions 0..4 (steps 0..19): return WAIT actions
            # Decision 5 (at resumption after perturbation, step 25): return distinctive signature
            if call_id < 5:
                return [ACTION_WAIT] * 4
            elif call_id == 5:
                return [ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT, ACTION_WAIT]
            return [ACTION_WAIT] * 4

    # Run twice with the exact same seed
    p1 = TrackingPlanner()
    res1 = run_episode(
        layout, spec, p1, counter=None, rng=54321, dt_mode="regular", m=4
    )
    p2 = TrackingPlanner()
    res2 = run_episode(
        layout, spec, p2, counter=None, rng=54321, dt_mode="regular", m=4
    )

    # Verification 1: Perturbation must be recorded and active
    assert res1.perturb_applied is True, "Perturbation flag was not applied"
    assert res1.steps_used >= 25, f"Expected >= 25 steps, got {res1.steps_used}"

    # Verification 2: Actions before step 20 come from planner (decisions 0..4, all ACTION_WAIT)
    assert res1.actions_taken[0:20] == [ACTION_WAIT] * 20, (
        f"Expected 20 initial planner actions, got {res1.actions_taken[0:20]}"
    )

    # Verification 3: From step 20, exactly 5 actions come from perturb rng
    expected_perturb_rng = random.Random(54321 + 99991)
    expected_perturb_actions = [expected_perturb_rng.choice(ACTIONS) for _ in range(5)]
    assert len(expected_perturb_actions) == 5
    assert res1.actions_taken[20:25] == expected_perturb_actions, (
        f"Expected perturb actions {expected_perturb_actions}, got {res1.actions_taken[20:25]}"
    )

    # Verification 4: Control returns to planner at step 25 (Decision 5 executed at steps 25..28)
    assert res1.actions_taken[25:29] == [ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT, ACTION_WAIT], (
        f"Expected planner signature at steps 25..28, got {res1.actions_taken[25:29]}"
    )

    # Verification 5: Bit-for-bit reproducibility
    assert res1.actions_taken == res2.actions_taken
    assert res1.trajectory == res2.trajectory
    assert res1.steps_used == res2.steps_used

    # Verification 6: Non-perturb episode check - zero perturbation actions inserted
    spec_no_perturb = dict(spec, perturb=False)
    p_no = TrackingPlanner()
    res_no = run_episode(
        layout, spec_no_perturb, p_no, counter=None, rng=54321, dt_mode="regular", m=4
    )
    assert res_no.perturb_applied is False, "Non-perturb episode had perturb_applied=True"
    # In non-perturb episode, decision 5 occurs at step 20 rather than step 25
    assert res_no.actions_taken[20:24] == [ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT, ACTION_WAIT], (
        "Non-perturb episode did not execute decision 5 at step 20"
    )
    assert res_no.actions_taken[20:25] != expected_perturb_actions, (
        "Non-perturb episode unexpectedly contained perturbation actions"
    )


def test_success_does_not_require_heading_match() -> None:
    """Primary success metric requires arriving at goal cell within L steps; heading not required.

    Catches mutation P122-M3 (success判定要求朝向也对).
    """
    layout = _get_test_layout(seed=505)

    # Find two adjacent free cells
    found = False
    for y in range(1, 24):
        for x in range(1, 24):
            if layout.terrain[y][x] == 0 and layout.terrain[y][x + 1] == 0:
                sx, sy = x, y
                gx, gy = x + 1, y
                found = True
                break
        if found:
            break
    assert found

    # Start facing EAST at (sx, sy); goal is at (gx, gy) facing NORTH
    # Walking FORWARD puts agent at (gx, gy) with heading EAST != NORTH
    start = State(x=sx, y=sy, heading=EAST)
    goal = State(x=gx, y=gy, heading=NORTH)

    spec = {
        "start": truth(start),
        "goal": truth(goal),
        "bfs_distance": 2,  # 1 step to cell, 1 turn to heading
        "perturb": False,
    }

    def step_forward_planner(obs: Any, goal_obs: Any, **kwargs: Any) -> list[int]:
        return [ACTION_FORWARD, ACTION_WAIT, ACTION_WAIT, ACTION_WAIT]

    res = run_episode(
        layout,
        spec,
        step_forward_planner,
        counter=None,
        rng=99,
        dt_mode="regular",
        m=4,
    )

    # The agent reaches (gx, gy) with heading EAST != NORTH.
    # Primary success MUST be True; strict_success MUST be False!
    assert res.success is True, "Arriving at goal cell must count as success"
    assert res.strict_success is False, "Strict success must require matching heading"


def test_dt_mode_regular_and_irregular_distribution() -> None:
    """In regular mode k ≡ 1; in irregular mode k matches registered distribution χ² < threshold.

    Catches mutation P122-M5 (irregular mode k fixed to 1).
    """
    layout = _get_test_layout(seed=606)

    # 1. Regular mode check
    spec_reg = {
        "start": {"x": 5, "y": 5, "heading": 0},
        "goal": {"x": 20, "y": 20, "heading": 0},
        "bfs_distance": 50,
        "perturb": False,
    }

    def wait_planner(obs: Any, goal_obs: Any, **kwargs: Any) -> list[int]:
        return [ACTION_WAIT] * 4

    res_reg = run_episode(
        layout, spec_reg, wait_planner, counter=None, rng=11, dt_mode="regular", m=4, max_steps=40
    )
    assert all(k == 1 for k in res_reg.k_history), "Regular mode had k != 1"

    # 2. Irregular mode check: collect >= 5000 draws
    counts: collections.Counter[int] = collections.Counter()
    rng = random.Random(20261106)
    total_draws = 5500

    # Draw across episodes as evaluated by run_episode
    for _ in range(120):
        res_irreg = run_episode(
            layout,
            spec_reg,
            wait_planner,
            counter=None,
            rng=rng,
            dt_mode="irregular",
            m=4,
            max_steps=100,
        )
        counts.update(res_irreg.k_history)
        if sum(counts.values()) >= total_draws:
            break

    # Chi-square test with frozen threshold (K_CHI2_THRESHOLD = 20.0, df=2)
    chi2 = assert_k_distribution(counts, threshold=20.0, min_n=5000)
    assert chi2 < 20.0


def test_forward_budget_exceeded_raises_immediately() -> None:
    """ForwardCounter budget is hard enforced; raises ForwardBudgetExceeded without silent truncation."""
    layout = _get_test_layout(seed=707)
    spec = {
        "start": {"x": 5, "y": 5, "heading": 0},
        "goal": {"x": 20, "y": 20, "heading": 0},
        "bfs_distance": 50,
        "perturb": False,
    }

    counter = ForwardCounter(budget=100)

    def greedy_budget_planner(obs: Any, goal_obs: Any, counter: ForwardCounter, **kwargs: Any) -> list[int]:
        # Exceed budget of 100
        counter.charge("predict_l1", 150)
        return [ACTION_WAIT] * 4

    with pytest.raises(ForwardBudgetExceeded, match="forward budget exceeded"):
        run_episode(
            layout,
            spec,
            greedy_budget_planner,
            counter=counter,
            rng=123,
            dt_mode="regular",
            m=4,
        )
