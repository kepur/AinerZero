"""CPU test double for :class:`~ainerzero.v9.interfaces.TimeScaleAdapter`.

Explicit-dt hierarchy clock on the registered 120 Hz world clock (r5 §3, §4 式 3):

- every level carries ``stride_ticks``; ``align`` reports
  ``delta_s = dt_ticks / 120`` **exactly**, so an irregular ``dt`` stays
  representable — the frame index never substitutes for time;
- ``macro_action`` applies the registered aggregation rule of that level.  Only
  the two rules below are registered; anything else is refused at construction
  (frozen rules, no runtime registration).

Pure CPU: numpy only, no model, no I/O.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

from ..interfaces.errors import ContractViolation, UnsupportedInput
from ..interfaces.timescale import TimeScaleAdapter
from ..interfaces.types import SIM_HZ, LevelAlignment, LevelSpec, MacroAction

__all__ = ["FakeTimeScaleAdapter", "REGISTERED_MACRO_RULES"]

REGISTERED_MACRO_RULES: tuple = ("displacement_heading", "action_histogram")
"""Frozen macro rules this double can apply (``A_k`` of r5 §4 式 3)."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class FakeTimeScaleAdapter(TimeScaleAdapter):
    """Registered levels + the two frozen macro rules, all tick-based."""

    def __init__(self, levels: Sequence[LevelSpec]) -> None:
        specs = tuple(levels)
        if not specs:
            raise ContractViolation("at least one level must be registered")
        seen: set[int] = set()
        for spec in specs:
            if not isinstance(spec, LevelSpec):
                raise ContractViolation(f"levels must be LevelSpec entries, got {type(spec).__name__}")
            if spec.level in seen:
                raise ContractViolation(f"duplicate level {spec.level}")
            seen.add(spec.level)
            if spec.macro_rule not in REGISTERED_MACRO_RULES:
                raise ContractViolation(
                    f"macro rule {spec.macro_rule!r} is not registered; "
                    f"registered={REGISTERED_MACRO_RULES}"
                )
            if spec.macro_rule == "action_histogram" and not spec.action_classes:
                raise ContractViolation("the action_histogram rule needs a non-empty action_classes")
            if spec.macro_rule == "action_histogram" and spec.macro_dim != len(spec.action_classes):
                raise ContractViolation(
                    f"macro_dim={spec.macro_dim} must equal len(action_classes)="
                    f"{len(spec.action_classes)} for the action_histogram rule"
                )
        self._levels = tuple(sorted(specs, key=lambda spec: spec.level))

    def levels(self) -> tuple:
        return self._levels

    def align(self, t_ticks: int, dt_ticks: int) -> tuple:
        """Align every registered level to 120 Hz for one real step (式 3)."""
        if not _is_int(t_ticks) or t_ticks < 0:
            raise UnsupportedInput(f"t_ticks must be a non-negative integer, got {t_ticks!r}")
        if not _is_int(dt_ticks) or dt_ticks < 0:
            raise UnsupportedInput(f"dt_ticks must be a non-negative integer, got {dt_ticks!r}")
        delta_s = dt_ticks / SIM_HZ  # 式 3: the real elapsed time of this step
        alignments = []
        for spec in self._levels:
            step_index = t_ticks // spec.stride_ticks
            alignments.append(
                LevelAlignment(
                    level=spec.level,
                    stride_ticks=spec.stride_ticks,
                    t_ticks=t_ticks,
                    dt_ticks=dt_ticks,
                    aligned_ticks=step_index * spec.stride_ticks,
                    step_index=step_index,
                    delta_s=delta_s,
                )
            )
        return self.require_alignments(tuple(alignments))

    def macro_action(self, level: int, actions: Sequence[Mapping]) -> MacroAction:
        """Aggregate one stride with the level's registered rule (A_k)."""
        spec = self.require_level(self._levels, level)
        if not isinstance(actions, (list, tuple)) or not actions:
            raise ContractViolation(f"macro_action(level={level}) needs a non-empty action sequence")
        delta_ticks = 0
        dx = dy = dtheta = 0.0
        histogram = [0] * len(spec.action_classes)
        for index, action in enumerate(actions):
            if not isinstance(action, Mapping):
                raise ContractViolation(f"action[{index}] must be a mapping, got {type(action).__name__}")
            ticks = action.get("dt_ticks", 0)
            if not _is_int(ticks) or ticks < 0:
                raise ContractViolation(f"action[{index}].dt_ticks must be a non-negative integer")
            delta_ticks += ticks
            if spec.macro_rule == "displacement_heading":
                for key in ("dx", "dy", "dtheta"):
                    value = action.get(key, 0.0)
                    if isinstance(value, bool) or not isinstance(value, (int, float)):
                        raise ContractViolation(f"action[{index}].{key} must be a number")
                    if not math.isfinite(float(value)):
                        raise ContractViolation(f"action[{index}].{key} must be finite")
                dx += float(action.get("dx", 0.0))
                dy += float(action.get("dy", 0.0))
                dtheta += float(action.get("dtheta", 0.0))
            else:  # action_histogram
                name = action.get("action_class")
                if not isinstance(name, str) or name not in spec.action_classes:
                    raise ContractViolation(
                        f"action[{index}].action_class={name!r} is not in the registered "
                        f"action_classes={spec.action_classes}"
                    )
                histogram[spec.action_classes.index(name)] += 1
        if spec.macro_rule == "displacement_heading":
            if spec.macro_dim != 3:
                raise ContractViolation(
                    f"displacement_heading expects macro_dim=3, got {spec.macro_dim}"
                )
            values = [dx, dy, dtheta]
        else:
            values = histogram
        if len(values) != spec.macro_dim:
            raise ContractViolation(
                f"aggregated action has dim {len(values)} but level {level} declares "
                f"macro_dim={spec.macro_dim}"
            )
        return MacroAction(
            level=level,
            rule=spec.macro_rule,
            values=np.asarray(values, dtype=float),
            delta_ticks=delta_ticks,
            delta_s=delta_ticks / SIM_HZ,
        )
