"""``HierarchicalPlanner`` interface (ARCHITECTURE_V9 r5 §3, §5 RFC 4.2).

Contracts owned here:

- every level receives an explicit budget; a level without a registered budget
  is not planned at all, and an exhausted level falls back instead of
  overspending (``fallback`` reports it);
- subgoals are latent / relative: they never carry unconfirmed world-truth
  coordinates, so the same forbidden-key rules as the observation path apply to
  every subgoal the planner emits.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .types import FallbackRecord, Plan, PlanBudget, PoseBelief

__all__ = ["HierarchicalPlanner"]


class HierarchicalPlanner(ABC):
    """Replaceable top-down planner (upper prediction becomes the lower subgoal)."""

    @abstractmethod
    def levels(self) -> tuple:
        """Planned level indices, top first."""

    @abstractmethod
    def plan(self, goal: Mapping, belief: PoseBelief, budget: PlanBudget) -> Plan:
        """Plan ``goal`` under per-level budgets; every level reports its own spend."""

    @abstractmethod
    def fallback(self) -> FallbackRecord | None:
        """Record of the last fallback, or ``None`` when nothing fell back."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def require_budget_coverage(budget: PlanBudget, levels: tuple) -> None:
        from .errors import ContractViolation

        if not isinstance(budget, PlanBudget):
            raise ContractViolation(f"budget must be a PlanBudget, got {type(budget).__name__}")
        missing = [level for level in levels if all(entry.level != level for entry in budget.levels)]
        if missing:
            raise ContractViolation(f"every planned level needs an explicit budget; missing {missing}")

    @staticmethod
    def require_no_truth_keys(subgoal: Mapping) -> None:
        """Subgoals are latent/relative; world truth keys are refused."""
        from .validation import assert_no_forbidden_keys

        assert_no_forbidden_keys(subgoal, origin="subgoal")

    @staticmethod
    def require_plan(value: Any) -> Plan:
        from .errors import ContractViolation

        if not isinstance(value, Plan):
            raise ContractViolation(f"plan() must return a Plan, got {type(value).__name__}")
        return value
