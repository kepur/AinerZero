"""``WorldBrainAdapter`` interface (ARCHITECTURE_V9 r5 §3).

Contracts owned here:

- ``step`` consumes **only** the ``payload`` of ObservationPacket/v1.1 (with its
  four-field time whitelist).  The envelope, a ``schema_version`` wrapper, a
  WorldSnapshot and any forbidden truth / identity / randomness / world-metadata
  key are refused before the model sees anything;
- ``reset`` starts an episode from metadata that is itself free of world truth;
- ``propose`` returns SkillProposal-shaped records that carry a TTL and an
  evidence version, and whose params contain no world-side identity keys.

The world-side producer and the leak gate on the AWZ side are awz.V9.A2/A3/B1;
this interface is the consumer half of the same boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping

from .types import BeliefSummary, SkillProposal

__all__ = ["WorldBrainAdapter"]


class WorldBrainAdapter(ABC):
    """Replaceable world-brain entry point (perception -> belief -> proposal)."""

    @abstractmethod
    def reset(self, meta: Mapping) -> None:
        """Start a new episode.  ``meta`` must not carry world truth or snapshots."""

    @abstractmethod
    def step(self, payload: Mapping) -> BeliefSummary:
        """Consume one ObservationPacket/v1.1 **payload** and return the belief summary.

        Raises a typed ``ObservationRejected`` subclass for envelope-level input,
        snapshots, forbidden keys or an inconsistent time whitelist.
        """

    @abstractmethod
    def propose(self, goal: Mapping) -> tuple:
        """Propose ``SkillProposal`` records for ``goal`` (never writes the world)."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def validate_payload(payload: Any):
        """The ObservationPacket/v1.1 payload gate every implementation must apply."""
        from .validation import validate_observation_payload

        return validate_observation_payload(payload)

    @staticmethod
    def require_skill_proposal(value: Any) -> SkillProposal:
        from .errors import ContractViolation

        if not isinstance(value, SkillProposal):
            raise ContractViolation(f"propose() must return SkillProposal records, got {type(value).__name__}")
        return value
