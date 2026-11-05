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
- ``promote`` into SLOW needs ``PromotionEvidence(kind="independent_test")``
  whose producer is neither a teacher nor an LLM (§1, §8.5).

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
from ..interfaces.spatial_memory import SpatialMemory
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
            "slow": False,
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
            if not self._entries[item_id]["slow"]
            and self._entries[item_id]["fragment"].partition == "development"
        )
        return ConsolidationReport(
            budget=budget, scanned=len(scanned_ids), kept=len(scanned_ids), promoted_candidates=promoted
        )

    def promote(self, item_id: str, evidence: PromotionEvidence) -> Mapping:
        """Promote one entry into SLOW; independent test evidence is mandatory."""
        evidence = self.require_evidence(evidence)
        if evidence.kind != "independent_test":
            raise EvidenceRequired(f"promotion needs kind='independent_test', got {evidence.kind!r}")
        if item_id not in self._entries:
            raise ContractViolation(f"unknown memory item {item_id!r}")
        self._entries[item_id]["slow"] = True
        return {
            "item_id": item_id,
            "level": "slow",
            "report_ref": evidence.report_ref,
            "test_id": evidence.test_id,
            "producer": evidence.producer,
        }

    # ---- read-only probes ------------------------------------------------- #

    def parameter_fingerprint(self) -> str:
        """Constant digest: this storage has no externally owned parameter."""
        return _FINGERPRINT

    def slow_items(self) -> tuple:
        """Ids already promoted into SLOW (test probe)."""
        return tuple(item_id for item_id in self._order if self._entries[item_id]["slow"])

    def __len__(self) -> int:
        return len(self._order)
