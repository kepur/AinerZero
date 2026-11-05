"""CPU test double for :class:`~ainerzero.v9.interfaces.SpatialMemory`.

Non-parametric metric + episodic storage (r5 §2, §3):

- writing is confined to the fail-closed allowlist ``WRITABLE_PARTITIONS``
  (``train``/``development``); ``final`` and unknown partitions are refused;
- the metric layer transforms equivariantly with the measured self-motion: for
  every stored point ``p`` and region ``c``,
  ``query(u·c, r) after transform(u) == query(c, r) before`` (式 5);
- queries never interpret an entry written in another encoder's latent space:
  foreign-version hits are excluded **and** reported, never silently returned;
- ``parameter_fingerprint`` is a constant digest of the (empty) set of external
  parameters: it must not move across ``write``/``transform``/``consolidate``;
- ``promote`` into SLOW needs ``PromotionEvidence`` **v2** whose producer is an
  independent identity bound to a trusted context (ADR-0014 §3 C1/C2: v1
  evidence and ``producer="student"`` are both refused, fail-closed);
- entries that miss the ARCH §2 provenance triple cannot be promoted (C3);
- ``revoke``/``demote``/``supersede`` retire a SLOW entry with an auditable
  record, and ``usable_slow_items`` refuses to hand a drifted-version entry to
  the deterministic layer (C4, fail-closed revalidation).

Pure CPU: numpy only, no model, no I/O beyond in-memory storage.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

import numpy as np

from ..interfaces.errors import (
    ContractViolation,
    EvidenceRequired,
    UnsupportedInput,
)
from ..interfaces.spatial_memory import DEMOTABLE_LEVELS, SpatialMemory
from ..interfaces.types import (
    ConsolidationReport,
    Fragment,
    PromotionEvidence,
    QueryResult,
    as_points,
)
from .geometry import FakeGeometryCore

__all__ = ["FakeSpatialMemory"]

_FINGERPRINT = hashlib.sha256(
    b"fake-spatial-memory:non-parametric;externally-owned-parameters=none"
).hexdigest()


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class FakeSpatialMemory(SpatialMemory):
    """In-memory double: disk-metric query, partition seal, version-checked reads."""

    def __init__(self, geometry: Any | None = None) -> None:
        self._geometry = geometry if geometry is not None else FakeGeometryCore()
        self._entries: dict[str, dict] = {}
        self._order: list[str] = []

    # ---- writes ----------------------------------------------------------- #

    def write(self, fragment: Fragment) -> str:
        """Store one fragment; sealed (non-allowlisted) partitions are refused."""
        if not isinstance(fragment, Fragment):
            raise ContractViolation(f"write() takes a Fragment, got {type(fragment).__name__}")
        self.require_writable(fragment.partition)
        if fragment.fragment_id in self._entries:
            raise ContractViolation(f"fragment id {fragment.fragment_id!r} already exists")
        metric = None
        if fragment.metric is not None:
            metric = np.asarray(fragment.metric, dtype=float)
            if metric.shape != (2,) or not np.isfinite(metric).all():
                raise UnsupportedInput("fragment.metric must be a finite 2-vector (disk centre)")
        self._entries[fragment.fragment_id] = {
            "fragment": fragment,
            "metric": metric,
            "level": "fast",
            "revoked": False,
            "revocation": None,
            "superseded_by": None,
            "promotion": None,
        }
        self._order.append(fragment.fragment_id)
        return fragment.fragment_id

    def transform(self, ego_motion: Mapping) -> None:
        """Re-express every stored disk centre under the measured self-motion."""
        if not isinstance(ego_motion, Mapping):
            raise ContractViolation(f"ego_motion must be a mapping, got {type(ego_motion).__name__}")
        values = []
        for key in ("dx", "dy", "dtheta"):
            value = ego_motion.get(key, 0.0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ContractViolation(f"ego_motion.{key} must be a number")
            if not np.isfinite(float(value)):
                raise ContractViolation(f"ego_motion.{key} must be finite")
            values.append(float(value))
        pose = self._geometry.exp(values)
        ids = [item_id for item_id, entry in self._entries.items() if entry["metric"] is not None]
        if not ids:
            return
        points = as_points([self._entries[item_id]["metric"] for item_id in ids])
        moved = np.asarray(self._geometry.act(pose, points))
        for item_id, point in zip(ids, moved, strict=True):
            self._entries[item_id]["metric"] = np.asarray(point, dtype=float)

    # ---- queries ---------------------------------------------------------- #

    def query_metric(self, region: Mapping, *, encoder_version: str) -> QueryResult:
        """Disk query; foreign-latent-space entries are excluded and reported."""
        if not isinstance(region, Mapping) or "center" not in region or "radius_m" not in region:
            raise ContractViolation("region must be a mapping with 'center' and 'radius_m'")
        center = np.asarray(region["center"], dtype=float)
        radius = region["radius_m"]
        if center.shape != (2,) or not np.isfinite(center).all():
            raise UnsupportedInput("region.center must be a finite 2-vector")
        if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not np.isfinite(float(radius)):
            raise UnsupportedInput("region.radius_m must be a finite number")
        if float(radius) < 0:
            raise UnsupportedInput("region.radius_m must be non-negative")
        hits: list[Fragment] = []
        excluded: list[Fragment] = []
        for item_id in self._order:
            entry = self._entries[item_id]
            metric = entry["metric"]
            fragment = entry["fragment"]
            if metric is None:
                continue
            if float(np.linalg.norm(metric - center)) > float(radius):
                continue
            if fragment.encoder_version == encoder_version:
                hits.append(fragment)
            else:
                excluded.append(fragment)
        return QueryResult(entries=tuple(hits), encoder_version=encoder_version, excluded=tuple(excluded))

    def query_topology(self, place: str, *, encoder_version: str) -> QueryResult:
        """Place query with the same fail-closed encoder-version rule."""
        if not isinstance(place, str) or not place:
            raise UnsupportedInput("place must be a non-empty string")
        hits: list[Fragment] = []
        excluded: list[Fragment] = []
        for item_id in self._order:
            fragment = self._entries[item_id]["fragment"]
            if fragment.place != place:
                continue
            if fragment.encoder_version == encoder_version:
                hits.append(fragment)
            else:
                excluded.append(fragment)
        return QueryResult(entries=tuple(hits), encoder_version=encoder_version, excluded=tuple(excluded))

    # ---- consolidation and promotion ------------------------------------- #

    def consolidate(self, budget: int) -> ConsolidationReport:
        """Replay/compact within ``budget`` items; never examines more than it."""
        if not _is_int(budget) or budget < 0:
            raise ContractViolation(f"consolidate(budget) must be a non-negative integer, got {budget!r}")
        scanned_ids = self._order[:budget]
        promoted = tuple(
            item_id
            for item_id in scanned_ids
            if self._entries[item_id]["level"] != "slow"
            and self._entries[item_id]["fragment"].partition == "development"
        )
        return ConsolidationReport(
            budget=budget, scanned=len(scanned_ids), kept=len(scanned_ids), promoted_candidates=promoted
        )

    def promote(self, item_id: str, evidence: PromotionEvidence) -> Mapping:
        """Promote one entry into SLOW; ``PromotionEvidence`` v2 is mandatory.

        C1: v1 evidence is refused here (fail-closed).
        C2: the producer guard runs again through ``require_evidence``.
        C3: the entry must carry provenance / object / action keys and the digest
        must match the content that was actually tested.
        """
        evidence = self.require_evidence(evidence)
        if item_id not in self._entries:
            raise ContractViolation(f"unknown memory item {item_id!r}")
        entry = self._entries[item_id]
        fragment = self.require_promotable_fragment(entry["fragment"], evidence)
        if entry["revoked"]:
            raise EvidenceRequired(
                f"memory item {item_id!r} was revoked ({entry['revocation']['reason']!r}); "
                "it needs a fresh independent test, not a re-promotion of the old evidence"
            )
        if entry["level"] == "slow":
            raise ContractViolation(f"memory item {item_id!r} is already SLOW")
        entry["level"] = "slow"
        entry["promotion"] = {
            "report_ref": evidence.report_ref,
            "test_id": evidence.test_id,
            "producer": evidence.producer,
            "producer_category": "see registry",
            "domain_ref": evidence.domain_ref,
            "alpha_t": evidence.error_control["alpha_t"],
            "attempts_N": evidence.error_control["attempts_N"],
            "origin_category": evidence.origin_category,
            "entry_digest": evidence.entry_digest,
            "encoder_version": evidence.encoder_version,
            "prior_version": evidence.prior_version,
        }
        return {
            "item_id": item_id,
            "level": "slow",
            "report_ref": evidence.report_ref,
            "test_id": evidence.test_id,
            "producer": evidence.producer,
            "domain_ref": evidence.domain_ref,
            "entry_digest": evidence.entry_digest,
            "encoder_version": evidence.encoder_version,
            "prior_version": evidence.prior_version,
        }

    # ---- revocation, demotion, supersession (C4) -------------------------- #

    def revoke(self, item_id: str, reason: str, evidence_ref: str) -> Mapping:
        """作废一个 SLOW 条目；条目退出 SLOW 且不再被确定性层使用。"""
        entry = self._entry(item_id)
        if entry["revoked"]:
            raise ContractViolation(f"memory item {item_id!r} is already revoked")
        if entry["level"] != "slow":
            raise ContractViolation(
                f"only SLOW entries can be revoked; {item_id!r} is {entry['level']!r}"
            )
        if not isinstance(reason, str) or not reason:
            raise UnsupportedInput("revoke(reason) must be a non-empty string")
        if not isinstance(evidence_ref, str) or not evidence_ref:
            raise UnsupportedInput("revoke(evidence_ref) must be a non-empty string")
        entry["revoked"] = True
        entry["level"] = "mid"
        entry["revocation"] = {"reason": reason, "evidence_ref": evidence_ref}
        return {
            "item_id": item_id,
            "level": entry["level"],
            "revoked": True,
            "reason": reason,
            "evidence_ref": evidence_ref,
        }

    def demote(self, item_id: str, to_level: str, reason: str) -> Mapping:
        """把 SLOW 条目降到 FAST/MID；``to_level`` 不能是 SLOW。"""
        entry = self._entry(item_id)
        if to_level not in DEMOTABLE_LEVELS:
            raise ContractViolation(
                f"demote() target must be one of {DEMOTABLE_LEVELS}, got {to_level!r}; "
                "a demotion never lands on SLOW"
            )
        if entry["level"] != "slow":
            raise ContractViolation(
                f"only SLOW entries can be demoted; {item_id!r} is {entry['level']!r}"
            )
        if entry["revoked"]:
            raise ContractViolation(f"memory item {item_id!r} is revoked; it cannot be demoted")
        if not isinstance(reason, str) or not reason:
            raise UnsupportedInput("demote(reason) must be a non-empty string")
        previous = entry["level"]
        entry["level"] = to_level
        return {
            "item_id": item_id,
            "from_level": previous,
            "level": to_level,
            "reason": reason,
        }

    def supersede(self, item_id: str, replacement_item_id: str) -> Mapping:
        """给旧 SLOW 条目写 supersede 指针（§2 D3-9 版本化回滚）。"""
        entry = self._entry(item_id)
        replacement = self._entry(replacement_item_id)
        if item_id == replacement_item_id:
            raise ContractViolation("an entry cannot supersede itself")
        if entry["level"] != "slow":
            raise ContractViolation(
                f"only SLOW entries can be superseded; {item_id!r} is {entry['level']!r}"
            )
        if entry["superseded_by"] is not None:
            raise ContractViolation(
                f"memory item {item_id!r} is already superseded by {entry['superseded_by']!r}"
            )
        if replacement["level"] != "slow" or replacement["revoked"]:
            raise ContractViolation(
                f"replacement {replacement_item_id!r} must be a live SLOW entry"
            )
        if replacement["superseded_by"] is not None:
            raise ContractViolation(
                f"replacement {replacement_item_id!r} is itself superseded"
            )
        entry["superseded_by"] = replacement_item_id
        return {
            "item_id": item_id,
            "superseded_by": replacement_item_id,
            "level": entry["level"],
        }

    def usable_slow_items(self, *, encoder_version: str, prior_version: str) -> tuple:
        """确定性层可用的 SLOW 条目：未撤销、未被取代、版本未漂移（fail-closed）。"""
        if not isinstance(encoder_version, str) or not encoder_version:
            raise UnsupportedInput("encoder_version must be a non-empty string")
        if not isinstance(prior_version, str) or not prior_version:
            raise UnsupportedInput("prior_version must be a non-empty string")
        usable: list[str] = []
        for item_id in self._order:
            entry = self._entries[item_id]
            if entry["level"] != "slow" or entry["revoked"] or entry["superseded_by"]:
                continue
            promotion = entry["promotion"]
            if promotion is None:  # pragma: no cover - defensive
                continue
            if promotion["encoder_version"] != encoder_version:
                continue
            if promotion["prior_version"] != prior_version:
                continue
            usable.append(item_id)
        return tuple(usable)

    def _entry(self, item_id: str) -> dict:
        if item_id not in self._entries:
            raise ContractViolation(f"unknown memory item {item_id!r}")
        return self._entries[item_id]

    # ---- read-only probes ------------------------------------------------- #

    def parameter_fingerprint(self) -> str:
        """Constant digest: this storage has no externally owned parameter."""
        return _FINGERPRINT

    def slow_items(self) -> tuple:
        """Ids currently sitting in SLOW (revoked entries have already left it)."""
        return tuple(
            item_id
            for item_id in self._order
            if self._entries[item_id]["level"] == "slow" and not self._entries[item_id]["revoked"]
        )

    def __len__(self) -> int:
        return len(self._order)
