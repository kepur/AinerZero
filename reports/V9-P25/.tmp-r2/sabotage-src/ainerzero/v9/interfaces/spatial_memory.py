"""``SpatialMemory`` interface (ARCHITECTURE_V9 r5 §2, §3).

Contracts owned here:

- writing is non-parametric: a memory write never changes any network
  parameter (``parameter_fingerprint`` must be stable across
  ``write``/``transform``/``consolidate``);
- the metric layer transforms equivariantly with self-motion (式 5);
- the episodic layer is partition-sealed: ``final`` (and anything not on the
  write allowlist) is refused, and ``promote`` into SLOW needs independent test
  evidence and may never be fed by a teacher or an LLM directly;
- every entry carries the encoder version that wrote it; interpreting entries
  in another latent space is refused instead of silently assumed.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Mapping, Sequence

from .types import ConsolidationReport, Fragment, PromotionEvidence, QueryResult

__all__ = ["SpatialMemory"]


class SpatialMemory(ABC):
    """Replaceable metric + episodic memory (non-parametric storage)."""

    @abstractmethod
    def write(self, fragment: Fragment) -> str:
        """Store one fragment; returns its storage id.  Sealed partitions are refused."""

    @abstractmethod
    def transform(self, ego_motion: Mapping) -> None:
        """Equivariantly transform the metric layer with the measured self-motion."""

    @abstractmethod
    def query_metric(self, region: Mapping, *, encoder_version: str) -> QueryResult:
        """Query the metric layer inside ``region`` (``center`` + ``radius_m``).

        Entries written in another encoder's latent space are never returned nor
        interpreted: they are excluded and reported in ``QueryResult.excluded``.
        """

    @abstractmethod
    def query_topology(self, place: str, *, encoder_version: str) -> QueryResult:
        """Query the topological / episodic layer at ``place`` (same version rule)."""

    @abstractmethod
    def consolidate(self, budget: int) -> ConsolidationReport:
        """Replay/compact within an explicit item budget; never exceeds it."""

    @abstractmethod
    def promote(self, item_id: str, evidence: PromotionEvidence) -> Mapping:
        """Promote one entry into SLOW; independent test evidence is mandatory."""

    @abstractmethod
    def parameter_fingerprint(self) -> str:
        """Digest of every externally owned parameter the memory can see."""

    # ---- shared helpers for implementations ------------------------------- #

    @staticmethod
    def require_writable(partition: str) -> None:
        from .errors import PartitionWriteRejected
        from .types import WRITABLE_PARTITIONS

        if partition not in WRITABLE_PARTITIONS:
            raise PartitionWriteRejected(
                f"partition {partition!r} is not writable; write allowlist={WRITABLE_PARTITIONS} "
                "(final is sealed)"
            )

    @staticmethod
    def require_evidence(evidence: Any) -> PromotionEvidence:
        from .errors import EvidenceRequired

        if not isinstance(evidence, PromotionEvidence):
            raise EvidenceRequired(
                f"promote() requires PromotionEvidence (kind='independent_test'), got {type(evidence).__name__}"
            )
        return evidence

    @staticmethod
    def require_fragments(values: Sequence[Any]) -> tuple:
        from .errors import EncoderVersionMismatch

        for value in values:
            if not isinstance(value, Fragment):
                raise EncoderVersionMismatch(f"memory entries must be Fragments, got {type(value).__name__}")
        return tuple(values)
