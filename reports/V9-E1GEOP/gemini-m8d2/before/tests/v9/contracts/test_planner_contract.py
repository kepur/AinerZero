"""Contract: HierarchicalPlanner (r5 §3, §5 RFC 4.2).

Positive: per-level budgets are explicit, spend never exceeds them, exhausted
levels fall back instead of overspending, emitted subgoals are latent/relative.

Counter-examples: a level without a budget, a goal carrying world truth, a
non-PoseBelief belief, and — via the sabotage harness — a planner that emits a
truth key inside a subgoal (this suite scans every emitted subgoal).
"""

from __future__ import annotations

import pytest

from ainerzero.v9.fakes import FakeHierarchicalPlanner
from ainerzero.v9.interfaces.errors import ContractViolation, TruthFieldRejected, UnsupportedInput
from ainerzero.v9.interfaces.types import (
    LevelBudget,
    Plan,
    PlanBudget,
    PoseBelief,
    as_points,
)
from ainerzero.v9.interfaces.validation import assert_no_forbidden_keys, scan_forbidden_keys

LEVELS = (2, 1, 0)
FULL_BUDGET = PlanBudget(
    levels=(LevelBudget(2, 4), LevelBudget(1, 4), LevelBudget(0, 4))
)


@pytest.fixture
def planner() -> FakeHierarchicalPlanner:
    return FakeHierarchicalPlanner(LEVELS)


def make_belief() -> PoseBelief:
    return PoseBelief(
        group="SE2",
        mean=((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
        covariance=((0.01, 0.0, 0.0), (0.0, 0.01, 0.0), (0.0, 0.0, 0.01)),
        gravity=(0.0, 0.0, -1.0),
        unobservable_dof=(),
    )


GOAL = {"kind": "symbolic", "description": "reach the chair"}


# ---- budgets --------------------------------------------------------------- #


def test_every_planned_level_gets_explicit_budget(planner):
    plan = planner.plan(GOAL, make_belief(), FULL_BUDGET)
    assert isinstance(plan, Plan)
    assert [level.level for level in plan.levels] == list(LEVELS)
    for level in plan.levels:
        assert level.budget is FULL_BUDGET.for_level(level.level)
        assert level.expansions <= level.budget.max_expansions
        assert level.exhausted is False
    assert plan.fallback_used is False and plan.fallback_reason is None
    assert planner.fallback() is None


def test_missing_budget_refuses_the_whole_plan(planner):
    partial = PlanBudget(levels=(LevelBudget(2, 4), LevelBudget(1, 4)))  # level 0 unregistered
    with pytest.raises(ContractViolation) as caught:
        planner.plan(GOAL, make_belief(), partial)
    assert "every planned level needs an explicit budget" in str(caught.value)
    with pytest.raises(ContractViolation):
        planner.plan(GOAL, make_belief(), "not-a-budget")


@pytest.mark.parametrize(
    ("budgets", "expected_exhausted"),
    [
        ({2: 2, 1: 1, 0: 1}, (False, False, False)),
        ({2: 1, 1: 1, 0: 1}, (True, False, False)),  # top level costs 2
        ({2: 2, 1: 0, 0: 1}, (False, True, False)),
        ({2: 2, 1: 1, 0: 0}, (False, False, True)),
    ],
)
def test_spend_never_exceeds_the_registered_budget(planner, budgets, expected_exhausted):
    budget = PlanBudget(levels=tuple(LevelBudget(level, cap) for level, cap in budgets.items()))
    plan = planner.plan(GOAL, make_belief(), budget)
    for level, exhausted in zip(plan.levels, expected_exhausted, strict=True):
        assert level.expansions <= level.budget.max_expansions
        assert level.exhausted is exhausted


def test_exhausted_level_falls_back_instead_of_overspending(planner):
    budget = PlanBudget(levels=(LevelBudget(2, 1), LevelBudget(1, 1), LevelBudget(0, 1)))
    plan = planner.plan(GOAL, make_belief(), budget)
    top = plan.levels[0]
    assert top.exhausted is True
    assert top.expansions == 1  # spent exactly what was allowed, not 2
    assert top.subgoals == ()  # an unfinished level emits nothing
    assert top.fallback_reason == "budget_exhausted"
    assert plan.fallback_used is True and plan.fallback_reason == "budget_exhausted"
    record = planner.fallback()
    assert record.level == 2 and record.reason == "budget_exhausted" and record.expansions == 1


def test_funded_plan_emits_subgoals_for_every_level(planner):
    plan = planner.plan(GOAL, make_belief(), FULL_BUDGET)
    for level in plan.levels:
        assert len(level.subgoals) == 1
        subgoal = level.subgoals[0]
        assert subgoal.level == level.level
        assert subgoal.cost == level.expansions
        assert "latent_target" in subgoal.target
        assert "relative_to" in subgoal.target


# ---- latent/relative subgoals --------------------------------------------- #


def test_emitted_subgoals_have_no_truth_keys(planner):
    """Scans every subgoal the planner emits (the sabotage target for M9)."""
    plan = planner.plan(GOAL, make_belief(), FULL_BUDGET)
    assert FakeHierarchicalPlanner.scan_subgoals(plan) == []
    for level in plan.levels:
        for subgoal in level.subgoals:
            assert_no_forbidden_keys(dict(subgoal.target))  # raises on any leak
            assert list(scan_forbidden_keys(dict(subgoal.target))) == []


def test_goal_with_world_truth_is_refused(planner):
    with pytest.raises(TruthFieldRejected) as caught:
        planner.plan({"position": [0.0, 0.0]}, make_belief(), FULL_BUDGET)
    assert caught.value.code == "truth_field_rejected"
    with pytest.raises(TruthFieldRejected):  # identity keys too (L2)
        planner.plan({"entity_id": "e-1"}, make_belief(), FULL_BUDGET)


def test_plan_requires_a_real_belief_and_mapping_goal(planner):
    with pytest.raises(UnsupportedInput):
        planner.plan(GOAL, as_points([[0.0, 0.0]]), FULL_BUDGET)
    with pytest.raises(ContractViolation):
        planner.plan("reach the chair", make_belief(), FULL_BUDGET)


# ---- construction ---------------------------------------------------------- #


def test_planner_level_registration_guards():
    with pytest.raises(ContractViolation):
        FakeHierarchicalPlanner(())
    with pytest.raises(ContractViolation):
        FakeHierarchicalPlanner((1, 1))
    with pytest.raises(ContractViolation):
        FakeHierarchicalPlanner((-1,))
    with pytest.raises(ContractViolation):
        FakeHierarchicalPlanner(("top",))
    assert FakeHierarchicalPlanner(LEVELS).levels() == LEVELS
