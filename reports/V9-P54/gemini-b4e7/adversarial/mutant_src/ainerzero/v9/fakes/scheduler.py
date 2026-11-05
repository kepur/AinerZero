"""CPU test double for :class:`~ainerzero.v9.interfaces.UpdateScheduler`.

Learning-side sparse update scheduler (r5 §3, §4 式 12b, §8.6 F2):

- only the three registered signal kinds exist (``observation_change``,
  ``executed_action``, ``belief_uncertainty``); world-side records (events,
  world entity ids, hidden contacts, world dirty/fallback flags, truth graphs)
  are refused, and so is any payload carrying an observation-path forbidden key;
- seeds must be belief nodes (``bn-`` prefix) **and** present in the supplied
  belief graph; the dirty set is the transitive closure over that graph;
- when the closure exceeds the frozen ``f_max`` the scheduler updates
  **everything** and records the fallback reason (式 12b);
- a ``belief_uncertainty`` signal below the frozen ``u_max`` threshold does not
  seed anything (thresholds are frozen at construction).

Pure CPU: no model, no I/O.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from ..interfaces.errors import ContractViolation, SignalRejected, UnsupportedInput
from ..interfaces.scheduler import UpdateScheduler
from ..interfaces.types import (
    UpdateResult,
    UpdateSignal,
    frozen_mapping,
)
from ..interfaces.validation import scan_forbidden_keys

__all__ = ["FakeUpdateScheduler", "WORLD_SIGNAL_KEYS", "BELIEF_NODE_PREFIX"]

BELIEF_NODE_PREFIX = "bn-"
"""Only nodes carrying this prefix are belief nodes (seeds must be belief nodes)."""

WORLD_SIGNAL_KEYS: tuple = (
    "event",
    "event_id",
    "event_record",
    "world_entity",
    "world_entity_id",
    "entity_state",
    "hidden_contact",
    "contact",
    "world_dirty",
    "world_fallback",
    "truth_graph",
)
"""World-side keys that may never appear in a learning-side signal payload."""


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class FakeUpdateScheduler(UpdateScheduler):
    """Closure-based double with frozen ``f_max`` / ``u_max`` thresholds."""

    def __init__(self, *, f_max: int, u_max: float) -> None:
        if not _is_int(f_max) or f_max < 1:
            raise ContractViolation(f"f_max must be an integer >= 1, got {f_max!r}")
        if isinstance(u_max, bool) or not isinstance(u_max, (int, float)) or not math.isfinite(float(u_max)):
            raise ContractViolation(f"u_max must be a finite number, got {u_max!r}")
        if float(u_max) < 0:
            raise ContractViolation(f"u_max must be non-negative, got {u_max!r}")
        self._thresholds = frozen_mapping({"f_max": int(f_max), "u_max": float(u_max)})
        self._seeds: list[str] = []
        self._pending_full: str | None = None
        self._fallback: str | None = None

    # ---- signals ---------------------------------------------------------- #

    def mark_dirty(self, signal: UpdateSignal) -> None:
        """Record one learning-side signal (world-side payloads are refused)."""
        signal = self.require_signal(signal)
        if not signal.node.startswith(BELIEF_NODE_PREFIX):
            raise SignalRejected(
                f"signal.node={signal.node!r} is not a belief node "
                f"(expected the {BELIEF_NODE_PREFIX!r} prefix)"
            )
        detail = dict(signal.detail)
        for key in WORLD_SIGNAL_KEYS:
            if key in detail:
                raise SignalRejected(f"world-side key {key!r} in signal.detail is not a learning-side source")
        findings = list(scan_forbidden_keys(detail, root="signal.detail"))
        if findings:
            raise SignalRejected(f"forbidden key(s) in signal.detail: {findings}")
        if signal.kind == "belief_uncertainty":
            uncertainty = detail.get("uncertainty")
            if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
                raise SignalRejected("a belief_uncertainty signal must carry a numeric 'uncertainty'")
            if not math.isfinite(float(uncertainty)):
                raise SignalRejected("'uncertainty' must be finite")
            if float(uncertainty) <= float(self._thresholds["u_max"]):
                return  # below the frozen u_max threshold: no seed
        if signal.node not in self._seeds:
            self._seeds.append(signal.node)

    # ---- closure ---------------------------------------------------------- #

    def dirty_set(self, belief_graph: Mapping) -> tuple:
        """Transitive closure of the seeds; full-set fallback past ``f_max``."""
        graph = self.require_graph(belief_graph)
        unknown = [seed for seed in self._seeds if seed not in graph]
        if unknown:
            raise SignalRejected(f"seed(s) {unknown} are not nodes of the belief graph")
        reached: set[str] = set()
        frontier = list(self._seeds)
        while frontier:
            node = frontier.pop()
            if node in reached:
                continue
            reached.add(node)
            frontier.extend(
                str(neighbour) for neighbour in graph[node] if str(neighbour) not in reached
            )
        limit = int(self._thresholds["f_max"])
        if len(reached) > limit:
            self._pending_full = f"closure size {len(reached)} exceeds f_max={limit}"
            return tuple(sorted(graph.keys()))
        self._pending_full = None
        return tuple(sorted(reached))

    def update(self, belief: Mapping, dirty: Sequence) -> Any:
        """``+1`` every updated node: sparse on ``dirty``, full on fallback."""
        if not isinstance(belief, Mapping) or not belief:
            raise UnsupportedInput(f"update(belief) must be a non-empty mapping, got {type(belief).__name__}")
        full_reason = self._pending_full
        if full_reason is not None:
            nodes = tuple(belief.keys())
            mode = "full"
            fallback_reason = full_reason
        else:
            nodes = tuple(dirty)
            missing = [node for node in nodes if node not in belief]
            if missing:
                raise SignalRejected(f"dirty node(s) {missing} are not in the belief")
            mode = "sparse"
            fallback_reason = None
        updated = dict(belief)
        for node in nodes:
            updated[node] = belief[node] + 1
        self._fallback = fallback_reason
        self._pending_full = None
        self._seeds.clear()
        return UpdateResult(
            belief=frozen_mapping(updated),
            nodes_updated=tuple(nodes),
            mode=mode,
            fallback_reason=fallback_reason,
            expansions=len(nodes),
        )

    def fallback_reason(self) -> str | None:
        return self._fallback

    def thresholds(self) -> Mapping:
        return self._thresholds
