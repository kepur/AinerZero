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

__all__ = ["SpatialMemory", "MEMORY_LEVELS", "DEMOTABLE_LEVELS"]

#: 记忆层级（FAST/MID/SLOW）；SLOW 只能由 ``promote`` 进入。
MEMORY_LEVELS = ("fast", "mid", "slow")

#: ``demote`` 允许落到哪些层级（降级不能是"升到 SLOW"）。
DEMOTABLE_LEVELS = ("fast", "mid")


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
        """Promote one entry into SLOW; ``PromotionEvidence`` v2 is mandatory (fail-closed)."""

    @abstractmethod
    def revoke(self, item_id: str, reason: str, evidence_ref: str) -> Mapping:
        """作废一个 SLOW 条目（ADR-0014 §3 C4）：留下原因与证据引用，条目退出 SLOW。"""

    @abstractmethod
    def demote(self, item_id: str, to_level: str, reason: str) -> Mapping:
        """把一个 SLOW 条目降到 ``DEMOTABLE_LEVELS`` 之一，并记原因。"""

    @abstractmethod
    def supersede(self, item_id: str, replacement_item_id: str) -> Mapping:
        """给旧条目写上 supersede 指针（§2 D3-9 回滚：SLOW 条目版本化）。"""

    @abstractmethod
    def usable_slow_items(self, *, encoder_version: str, prior_version: str) -> tuple:
        """确定性层可用（未被撤销/取代、版本未漂移）的 SLOW 条目。

        编码器、``F_prior`` 或 GeometryCore 版本一变，条目就进入"待重验"状态，
        在重验完成前**不被确定性层使用**（fail-closed，§2 D3-9）。
        """

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
        """C1 + C2 的共同入口：只接受 v2 证据；在消费时复验完整不变量，不信任构造历史。"""
        from .errors import EvidenceRequired
        from .validation import require_independent_slow_producer, require_slow_eligible_origin

        if not isinstance(evidence, PromotionEvidence):
            raise EvidenceRequired(
                f"promote() requires PromotionEvidence (kind='independent_test'), got {type(evidence).__name__}"
            )
        try:
            from dataclasses import fields

            values = {field.name: getattr(evidence, field.name)
                      for field in fields(PromotionEvidence)}
            if values["schema_version"] != "v2":
                raise EvidenceRequired(
                    f"promote() only accepts PromotionEvidence schema_version='v2', got "
                    f"{values['schema_version']!r}; v1 evidence stays readable but may not promote "
                    "(ADR-0014 §3 C1, fail-closed)"
                )
            require_independent_slow_producer(values["producer"], trusted_context=values["trusted_context"])
            require_slow_eligible_origin(values["origin_category"])
            # Reconstruct the base type, never dispatch validators on a forged
            # instance/subclass. Nested mappings must be valid now, not just
            # when the original object was constructed.
            evidence = PromotionEvidence(**values)
        except (ValueError, TypeError, AttributeError, OverflowError) as exc:
            raise EvidenceRequired(f"invalid promotion evidence at consumption: {exc}") from exc
        return evidence

    @staticmethod
    def require_promotable_fragment(fragment: Fragment, evidence: PromotionEvidence) -> Fragment:
        """C3 守卫：缺来源/对象/动作键的条目不可晋升；摘要与编码器版本必须对上。"""
        from .errors import EncoderVersionMismatch, EvidenceRequired

        gaps = fragment.promotion_gaps()
        if gaps:
            raise EvidenceRequired(
                f"fragment {fragment.fragment_id!r} cannot be promoted: it is missing ARCH §2 "
                f"field(s) {list(gaps)} (ADR-0014 §3 C3)"
            )
        if fragment.encoder_version != evidence.encoder_version:
            raise EncoderVersionMismatch(
                f"evidence.encoder_version {evidence.encoder_version!r} does not match the stored "
                f"entry's {fragment.encoder_version!r}"
            )
        actual = fragment.content_digest()
        if actual != evidence.entry_digest:
            raise EvidenceRequired(
                f"evidence.entry_digest does not match the stored entry {fragment.fragment_id!r} "
                f"(evidence {evidence.entry_digest!r} != entry {actual!r}); the promoted content must "
                "be the content that was tested"
            )
        return fragment

    @staticmethod
    def require_fragments(values: Sequence[Any]) -> tuple:
        from .errors import EncoderVersionMismatch

        for value in values:
            if not isinstance(value, Fragment):
                raise EncoderVersionMismatch(f"memory entries must be Fragments, got {type(value).__name__}")
        return tuple(values)

