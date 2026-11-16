"""``UpdateScheduler`` interface (ARCHITECTURE_V9 r5 §3, §4 式 12b, §8.6 F2).

This is the **learning-side** scheduler only; the world-side counterpart lives
in AWZ (awz.V9.B9) and is not part of this interface.

Contracts owned here:

- a signal may only come from three sources: the current and past allowed
  observations, the student's own executed actions, and changes of its own
  belief (e.g. uncertainty growth over ``u_max``);
- Event/v1 records, world entity ids, hidden contacts, world-side dirty sets,
  world fallback flags and truth graphs are refused;
- the dependency graph is derived from the belief only: seeds that are not
  belief nodes are refused, and the expansion is the transitive closure over the
  supplied belief graph;
- when the closure exceeds ``f_max`` the scheduler updates **everything** and
  records the fallback reason (式 12b); thresholds are frozen at construction.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from .types import UpdateSignal

__all__ = ["UpdateScheduler"]


class UpdateScheduler(ABC):
    """Replaceable learning-side sparse update scheduler."""

    @abstractmethod
    def mark_dirty(self, signal: UpdateSignal) -> None:
        """Record one learning-side signal (world-side signals are refused)."""

    @abstractmethod
    def dirty_set(self, belief_graph: Mapping) -> tuple:
        """Return the transitive closure of the seeded nodes over ``belief_graph``."""

    @abstractmethod
    def update(self, belief: Mapping, dirty: Sequence) -> Any:
        """Update ``belief`` on ``dirty`` (sparse) or on everything (fallback)."""

    @abstractmethod
    def fallback_reason(self) -> str | None:
        """Why the last update went full, or ``None`` when it stayed sparse."""

    @abstractmethod
    def thresholds(self) -> Mapping:
        """Frozen registration thresholds (``f_max``, ``u_max``); read-only."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def require_signal(value: Any) -> UpdateSignal:
        from .errors import SignalRejected

        if not isinstance(value, UpdateSignal):
            raise SignalRejected(
                f"mark_dirty() requires a typed learning-side UpdateSignal, got {type(value).__name__}"
            )
        return value

    @staticmethod
    def require_graph(value: Any) -> Mapping:
        from .errors import SignalRejected

        if not isinstance(value, Mapping):
            raise SignalRejected(f"dirty_set() requires a belief-derived graph mapping, got {type(value).__name__}")
        for node, neighbours in value.items():
            if not isinstance(node, str):
                raise SignalRejected("belief graph node ids must be strings")
            if not isinstance(neighbours, (list, tuple, set, frozenset)):
                raise SignalRejected(f"belief graph neighbours of {node!r} must be a sequence of node ids")
        return value
