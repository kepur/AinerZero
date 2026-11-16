"""``TimeScaleAdapter`` interface (ARCHITECTURE_V9 r5 §3, §4 式 3).

Contracts owned here:

- time is **explicit**: every level carries ``stride_ticks`` and is aligned
  against the registered 120 Hz world clock; a frame index is never a
  substitute for time (the signature takes ``t_ticks``/``dt_ticks`` only);
- ``align`` reports ``delta_s = dt_ticks / 120`` exactly, so irregular ``dt``
  stays representable (式 3: ``Delta t_k`` is the sum of the real step durations);
- ``macro_action`` applies the **registered** aggregation rule ``A_k`` of that
  level and returns both the macro action and its real duration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Mapping, Sequence

from .types import LevelAlignment, LevelSpec, MacroAction

__all__ = ["TimeScaleAdapter"]


class TimeScaleAdapter(ABC):
    """Replaceable hierarchy clock and macro-action aggregator."""

    @abstractmethod
    def levels(self) -> tuple:
        """Registered :class:`LevelSpec` entries, lowest level first."""

    @abstractmethod
    def align(self, t_ticks: int, dt_ticks: int) -> tuple:
        """Align every registered level to the 120 Hz clock for one real step."""

    @abstractmethod
    def macro_action(self, level: int, actions: Sequence[Mapping]) -> MacroAction:
        """Aggregate the lower-level actions of one stride with the registered rule."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def require_level(specs: tuple, level: int) -> LevelSpec:
        from .errors import ContractViolation

        for spec in specs:
            if spec.level == level:
                return spec
        raise ContractViolation(f"level {level} is not registered; levels={[s.level for s in specs]}")

    @staticmethod
    def require_alignments(values: object) -> tuple:
        from .errors import ContractViolation

        if not isinstance(values, (list, tuple)) or not values:
            raise ContractViolation("align() must return a non-empty sequence of LevelAlignment records")
        for value in values:
            if not isinstance(value, LevelAlignment):
                raise ContractViolation(f"align() must return LevelAlignment records, got {type(value).__name__}")
        return tuple(values)
