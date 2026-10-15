"""S01: minimal time index, C0 cell references and typed evidence links.

A side-car contract layer for ARCHITECTURE_REVISION section 6.4 (CPU only).
It never modifies v2 experience records or student inputs, imports no tensor
runtime and implements no 3D, object tracking or semantics. A C0 reference
names a *symbol slot*; physical coordinates are absent by construction, so a
cell index can never pass for xyz. Structure checks are not proof of
authenticity, and storing these records does not mean the model uses them.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, TypeVar
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from ainerzero.core.contracts import CellIndex, Contract, StepIndex
from ainerzero.core.experience import DatasetPartition, ObservationV2, OriginKind

SPACETIME_SCHEMA_VERSION = 1
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Seconds = Annotated[float, Field(strict=True, ge=0)]
_M = TypeVar("_M", bound=Contract)


def _revalidate(cls: type[_M], value: Any) -> _M:
    """Fail closed on unchecked Python objects (model_copy/model_construct).

    Public consumers call this instead of trusting an instance's history;
    direct instance validation preserves undeclared attributes for rejection,
    including those on nested payloads, instead of discarding them in a dump.
    """
    if not isinstance(value, cls):
        raise ValueError(f"expected {cls.__name__}, got {type(value).__name__}")
    try:
        return cls.model_validate(value)
    except ValueError:
        raise
    except Exception as exc:  # malformed constructed instance
        raise ValueError(f"cannot revalidate {cls.__name__}: {exc}") from exc


class ClockDomain(StrEnum):
    EVENT_STEP = "event_step"  # ordinal steps only; no seconds
    SENSOR_MONOTONIC = "sensor_monotonic"
    WALL_UTC = "wall_utc"


class TimeOrder(StrEnum):
    BEFORE = "before"
    SAME = "same"
    AFTER = "after"
    NOT_COMPARABLE = "not_comparable"


class TimeIndex(Contract):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = SPACETIME_SCHEMA_VERSION
    run_id: UUID
    world_id: UUID | None  # environment_instance_id; None for legacy records
    episode_id: UUID
    partition: DatasetPartition
    step: StepIndex
    stream_seq: StepIndex = 0
    clock_domain: ClockDomain = ClockDomain.EVENT_STEP
    clock_id: Name | None = None
    event_time_s: Seconds | None = None
    time_error_s: Seconds | None = None
    # Online order at which this index first became available (>= step).
    available_at_step: StepIndex

    @model_validator(mode="after")
    def clock_rules(self) -> Self:
        if self.clock_domain is ClockDomain.EVENT_STEP:
            if self.event_time_s is not None or self.time_error_s is not None:
                raise ValueError("event steps carry no seconds; leave times empty")
        elif self.clock_id is None:
            raise ValueError("timed clock domains require a clock_id")
        if self.time_error_s is not None and self.event_time_s is None:
            raise ValueError("time error requires an event time")
        if self.available_at_step < self.step:
            raise ValueError("an index cannot be available before its own step")
        return self


def compare_time(a: TimeIndex, b: TimeIndex) -> TimeOrder:
    """Order only within one run/episode/known world/partition/clock.

    Invalid structures raise; valid but incomparable pairs return
    NOT_COMPARABLE. An equal reading only means equal recorded coordinates,
    not proven physical simultaneity. Ordering is never causal evidence.
    """
    a = _revalidate(TimeIndex, a)
    b = _revalidate(TimeIndex, b)
    if a.world_id is None or b.world_id is None:
        return TimeOrder.NOT_COMPARABLE
    scope_a = (a.run_id, a.episode_id, a.world_id, a.partition, a.clock_domain, a.clock_id)
    scope_b = (b.run_id, b.episode_id, b.world_id, b.partition, b.clock_domain, b.clock_id)
    if scope_a != scope_b:
        return TimeOrder.NOT_COMPARABLE
    seq_a, seq_b = (a.step, a.stream_seq), (b.step, b.stream_seq)
    if a.clock_domain is ClockDomain.EVENT_STEP:
        return _order(seq_a, seq_b)
    if a.event_time_s is None or b.event_time_s is None:
        return TimeOrder.NOT_COMPARABLE
    err = (a.time_error_s or 0.0) + (b.time_error_s or 0.0)
    if err > 0 and abs(a.event_time_s - b.event_time_s) <= err:
        return TimeOrder.NOT_COMPARABLE  # intervals intersect or touch
    by_seconds = _order((a.event_time_s,), (b.event_time_s,))
    if a.clock_domain is ClockDomain.SENSOR_MONOTONIC and by_seconds is not TimeOrder.SAME:
        by_seq = _order(seq_a, seq_b)
        if by_seq is not TimeOrder.SAME and by_seq is not by_seconds:
            return TimeOrder.NOT_COMPARABLE  # step order contradicts seconds
    return by_seconds


def _order(x: tuple, y: tuple) -> TimeOrder:
    return TimeOrder.BEFORE if x < y else TimeOrder.AFTER if x > y else TimeOrder.SAME


def observation_digest(observation: ObservationV2) -> str:
    """SHA-256 of the revalidated observation's canonical JSON (sorted keys)."""
    observation = _revalidate(ObservationV2, observation)
    return _sha(observation.model_dump(mode="json"))


class C0CellRef(Contract):
    """Reference to one symbol slot of one public C0 observation."""

    kind: Literal["c0_cell"] = "c0_cell"
    coordinate_kind: Literal["symbol_slot"] = "symbol_slot"
    time: TimeIndex
    cell: CellIndex
    observation_id: UUID
    observation_sha256: Digest
    origin: OriginKind
    # Physical position is unknown for C0; the field is fixed empty on purpose.
    physical_xyz: None = None


def cell_ref_from_observation(
    observation: ObservationV2, cell: int, *, available_at_step: int | None = None
) -> C0CellRef:
    observation = _revalidate(ObservationV2, observation)
    ctx = observation.context
    time = TimeIndex(
        run_id=ctx.run_id,
        world_id=ctx.environment_instance_id,
        episode_id=ctx.episode_id,
        partition=ctx.partition,
        step=observation.step,
        available_at_step=observation.step if available_at_step is None else available_at_step,
    )
    return C0CellRef(
        time=time,
        cell=cell,
        observation_id=observation.id,
        observation_sha256=observation_digest(observation),
        origin=observation.origin,
    )


def verify_cell_ref(ref: C0CellRef, observation: ObservationV2) -> None:
    """Fail closed when the reference does not match the referenced observation."""
    ref = _revalidate(C0CellRef, ref)
    observation = _revalidate(ObservationV2, observation)
    ctx = observation.context
    checks = {
        "observation_id": ref.observation_id == observation.id,
        "observation_sha256": ref.observation_sha256 == observation_digest(observation),
        "run_id": ref.time.run_id == ctx.run_id,
        "episode_id": ref.time.episode_id == ctx.episode_id,
        "world_id": ref.time.world_id == ctx.environment_instance_id,
        "partition": ref.time.partition is ctx.partition,
        "step": ref.time.step == observation.step,
        "origin": ref.origin is observation.origin,
    }
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise ValueError(f"cell reference does not match observation: {', '.join(bad)}")


class EvidenceKind(StrEnum):
    SAME_CELL_LATER = "same_cell_later"  # temporal succession only, not causation
    ACTION_OUTCOME_CANDIDATE = "action_outcome_candidate"
    CO_OCCURRENCE = "co_occurrence"


class EvidenceLink(Contract):
    """Typed, sourced association between C0 cell references.

    Records support; never a verified causal claim. ``asserted_at_step`` is
    the online order at which the link was made: it may not use evidence that
    only became available later (no back-writing of future revisions).
    """

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = SPACETIME_SCHEMA_VERSION
    kind: EvidenceKind
    subject: C0CellRef
    supports: Annotated[tuple[C0CellRef, ...], Field(min_length=1)]
    asserted_by: Name
    asserted_at_step: StepIndex
    revision: Annotated[int, Field(strict=True, ge=0)] = 0
    supersedes_sha256: Digest | None = None
    verified_causal: Literal[False] = False

    @model_validator(mode="after")
    def evidence_rules(self) -> Self:
        refs = (self.subject, *self.supports)
        scope = {(r.time.run_id, r.time.episode_id, r.time.world_id) for r in refs}
        if len(scope) != 1:
            raise ValueError("C0 evidence links stay within one run/episode/world")
        if len({r.time.partition for r in refs}) != 1:
            raise ValueError("evidence cannot mix dataset partitions")
        if any(r.origin is not OriginKind.OBSERVED for r in refs):
            raise ValueError("observed-view links accept only observed origins")
        if any(r.time.available_at_step > self.asserted_at_step for r in refs):
            raise ValueError("link uses evidence not yet available when asserted")
        # Reference metadata may vary without supplying a new observation.
        # Content digests remain integrity/lineage checks, not evidence counts.
        identities = [(r.observation_id, r.cell) for r in self.supports]
        if len(set(identities)) != len(identities):
            raise ValueError("duplicate support references")
        if (self.subject.observation_id, self.subject.cell) in identities:
            raise ValueError("a link cannot cite its own subject as support")
        if self.kind is EvidenceKind.SAME_CELL_LATER:
            for r in self.supports:
                if r.cell != self.subject.cell:
                    raise ValueError("same_cell_later supports must name the subject's cell")
                if compare_time(self.subject.time, r.time) is not TimeOrder.BEFORE:
                    raise ValueError("same_cell_later supports must be strictly later")
        if (self.revision == 0) != (self.supersedes_sha256 is None):
            raise ValueError("revisions >0 must name the superseded link and only they")
        return self


def _sha(data: object) -> str:
    return hashlib.sha256(canonical_bytes(data)).hexdigest()


def canonical_bytes(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()



def _revalidate_record(record: Any) -> TimeIndex | C0CellRef | EvidenceLink:
    for cls in (EvidenceLink, C0CellRef, TimeIndex):
        if isinstance(record, cls):
            return _revalidate(cls, record)
    raise ValueError(f"not a spacetime record: {type(record).__name__}")


def to_canonical_json(record: TimeIndex | C0CellRef | EvidenceLink) -> bytes:
    """Structure only: no observation or predecessor resolution here."""
    return canonical_bytes(_revalidate_record(record).model_dump(mode="json"))


def record_digest(record: TimeIndex | C0CellRef | EvidenceLink) -> str:
    return hashlib.sha256(to_canonical_json(record)).hexdigest()


def load_cell_ref(raw: bytes | str) -> C0CellRef:
    """Schema loader only; does not prove the observation exists."""
    return C0CellRef.model_validate_json(raw)


def load_evidence_link(raw: bytes | str) -> EvidenceLink:
    """Schema loader only; an isolated revision may load but is not history."""
    return EvidenceLink.model_validate_json(raw)


def resolve_link(
    link: EvidenceLink, observations_by_id: Mapping[UUID, ObservationV2]
) -> EvidenceLink:
    """Resolve every ref against caller-supplied public observations.

    The mapping must come from an explicit public loading path. Matching
    content is not producer authentication: a forged mapping plus forged
    claims cannot be detected without signatures, which do not exist here.
    """
    link = _revalidate(EvidenceLink, link)
    if not isinstance(observations_by_id, Mapping):
        raise ValueError("observations_by_id must be a mapping")
    for ref in (link.subject, *link.supports):
        if ref.observation_id not in observations_by_id:
            raise ValueError(f"unresolved observation {ref.observation_id}")
        observation = _revalidate(ObservationV2, observations_by_id[ref.observation_id])
        if observation.id != ref.observation_id:
            raise ValueError("mapping key does not match observation.id")
        verify_cell_ref(ref, observation)
    return link


def validate_link_history(links: Iterable[EvidenceLink]) -> tuple[EvidenceLink, ...]:
    """Validate a revision set; raise on any broken, forked or rewritten chain."""
    checked = tuple(_revalidate(EvidenceLink, link) for link in links)
    by_digest: dict[str, EvidenceLink] = {}
    for link in checked:
        d = record_digest(link)
        if d in by_digest:
            raise ValueError("duplicate link identity in history")
        by_digest[d] = link
    successors: set[str] = set()
    for link in checked:
        if link.supersedes_sha256 is None:
            continue
        prev = by_digest.get(link.supersedes_sha256)
        if prev is None:
            raise ValueError("revision predecessor is missing")
        if link.supersedes_sha256 in successors:
            raise ValueError("forked revision: predecessor already has a successor")
        successors.add(link.supersedes_sha256)
        if link.revision != prev.revision + 1:
            raise ValueError("revision numbers must increase by exactly one")
        if link.asserted_at_step < prev.asserted_at_step:
            raise ValueError("revision asserted before its predecessor")
        if link.kind is not prev.kind or record_digest(link.subject) != record_digest(prev.subject):
            raise ValueError("revision cannot change relation kind or subject identity")
    # revision == predecessor + 1 makes cycles impossible; walk anyway.
    for link in checked:
        seen: set[str] = set()
        cur: EvidenceLink | None = link
        while cur is not None and cur.supersedes_sha256 is not None:
            if cur.supersedes_sha256 in seen:
                raise ValueError("revision cycle")
            seen.add(cur.supersedes_sha256)
            cur = by_digest.get(cur.supersedes_sha256)
    return checked


def links_visible_at(links: Iterable[EvidenceLink], step: int) -> tuple[EvidenceLink, ...]:
    """As-of view: structure and revision closure only, not resolved evidence.

    Revalidates records, validates the whole history (raising on defects),
    then hides links asserted after ``step``. Late steps return all known
    versions, not only the latest.
    """
    if type(step) is not int or step < 0:
        raise ValueError("step must be a non-negative int")
    checked = validate_link_history(links)
    return tuple(link for link in checked if link.asserted_at_step <= step)


def resolved_links_visible_at(
    links: Iterable[EvidenceLink],
    step: int,
    observations_by_id: Mapping[UUID, ObservationV2],
) -> tuple[EvidenceLink, ...]:
    """resolve each link -> validate history -> as-of filter."""
    resolved = tuple(resolve_link(link, observations_by_id) for link in links)
    return links_visible_at(resolved, step)
