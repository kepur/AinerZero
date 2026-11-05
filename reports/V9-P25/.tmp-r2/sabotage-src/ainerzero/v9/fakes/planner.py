"""CPU test double for :class:`~ainerzero.v9.interfaces.HierarchicalPlanner`.

Top-down planner with explicit per-level budgets (r5 §3, §5 RFC 4.2):

- a level without a registered :class:`LevelBudget` is not planned at all —
  the whole call is refused (fail closed), never planned "for free";
- a level whose budget cannot cover its registered expansion cost finishes
  **exhausted**: it emits no subgoal, records a ``FallbackRecord`` and the plan
  is marked as fallen back instead of overspending;
- every emitted subgoal is scanned with the observation-path forbidden-key
  rules: subgoals are latent/relative and never carry unconfirmed world-truth
  coordinates.

Registered fake cost: the top level needs 2 expansions, every other level 1.
Pure CPU: no search, no model, no I/O.
"""

from __future__ import annotations

from typing import Mapping

from ..interfaces.errors import ContractViolation, UnsupportedInput
from ..interfaces.planner import HierarchicalPlanner
from ..interfaces.types import (
    FallbackRecord,
    Plan,
    PlanBudget,
    PlanLevel,
    PoseBelief,
    Subgoal,
    frozen_mapping,
)
from ..interfaces.validation import assert_no_forbidden_keys, scan_forbidden_keys

__all__ = ["FakeHierarchicalPlanner"]


def _expansion_cost(level: int, levels: tuple) -> int:
    return 2 if level == levels[0] else 1


class FakeHierarchicalPlanner(HierarchicalPlanner):
    """Budget-respecting double; emits only latent/relative subgoals."""

    def __init__(self, levels: tuple = (2, 1, 0)) -> None:
        ordered = tuple(levels)
        if not ordered:
            raise ContractViolation("the planner needs at least one level (top first)")
        if any(not isinstance(level, int) or isinstance(level, bool) or level < 0 for level in ordered):
            raise ContractViolation(f"level indices must be non-negative integers, got {ordered!r}")
        if len(set(ordered)) != len(ordered):
            raise ContractViolation(f"duplicate level index in {ordered!r}")
        self._levels = ordered
        self._fallback: FallbackRecord | None = None

    def levels(self) -> tuple:
        return self._levels

    def plan(self, goal: Mapping, belief: PoseBelief, budget: PlanBudget) -> Plan:
        """Plan ``goal`` top-down under explicit budgets; never overspends."""
        self.require_budget_coverage(budget, self._levels)
        if not isinstance(goal, Mapping):
            raise ContractViolation(f"goal must be a mapping, got {type(goal).__name__}")
        assert_no_forbidden_keys(goal, origin="goal")
        if not isinstance(belief, PoseBelief):
            raise UnsupportedInput(f"belief must be a PoseBelief, got {type(belief).__name__}")
        plan_levels: list[PlanLevel] = []
        fallback: FallbackRecord | None = None
        for level in self._levels:
            level_budget = budget.for_level(level)
            needed = _expansion_cost(level, self._levels)
            expansions = min(needed, level_budget.max_expansions)
            exhausted = expansions < needed
            subgoals: list[Subgoal] = []
            if exhausted:
                fallback = FallbackRecord(
                    level=level, reason="budget_exhausted", expansions=expansions
                )
            else:
                target = {
                    "level": level,
                    "relative_to": "current_belief",
                    "latent_target": f"latent-{level}",
                }
                assert_no_forbidden_keys(target, origin="subgoal")
                subgoals.append(Subgoal(level=level, target=frozen_mapping(target), cost=expansions))
            plan_levels.append(
                PlanLevel(
                    level=level,
                    budget=level_budget,
                    expansions=expansions,
                    subgoals=tuple(subgoals),
                    exhausted=exhausted,
                    fallback_reason=fallback.reason if (fallback and exhausted) else None,
                )
            )
        self._fallback = fallback
        return Plan(
            goal=frozen_mapping(goal),
            levels=tuple(plan_levels),
            fallback_used=fallback is not None,
            fallback_reason=fallback.reason if fallback else None,
        )

    def fallback(self) -> FallbackRecord | None:
        return self._fallback

    # ---- test probes ------------------------------------------------------ #

    @staticmethod
    def scan_subgoals(plan: Plan) -> list:
        """Every forbidden key present in any emitted subgoal (empty when clean)."""
        findings: list = []
        for level in plan.levels:
            for subgoal in level.subgoals:
                findings.extend(scan_forbidden_keys(subgoal.target))
        return findings
