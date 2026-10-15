"""S05: S04 record-schema proposals as strict CPU contracts (no runtime wiring).

SpatialEstimate, EntityTrack, SemanticBinding and ImaginedBranch from the S04
evaluation-protocol draft section 3, built on the S01 ``TimeIndex`` /
``C0CellRef`` contracts. Pure data validation: nothing here is imported by data
collection, the model, or M2m-d; storing these records is not evidence that any
model tracks objects, perceives 3D, or binds words.

Rules enforced (fail closed, ValueError):
* coordinates have exactly the dimensionality of their kind (2D never gets z);
* uncertainty is empty unless a calibration/empirical basis is declared;
* nothing cites evidence that was not yet available when the record was made;
* occluded/lost/unknown track states never cite an *observed* estimate;
* an imagined branch is usable as support only after checks against real,
  later observed outcomes, and then only as prediction/outcome pairs;
* evaluator-private estimates are rejected from student-visible views;
* revisions append (revision>0 <=> supersedes_sha256) and never rewrite.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, TypeVar
from uuid import UUID

from pydantic import Field, StringConstraints, model_validator

from ainerzero.core.contracts import Contract, StepIndex
from ainerzero.core.experience import OriginKind
from ainerzero.core.spacetime import (
    C0CellRef,
    TimeIndex,
    TimeOrder,
    _revalidate,
    canonical_bytes,
    compare_time,
)

S05_SCHEMA_VERSION = 1
Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]
Finite = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Revision = Annotated[int, Field(strict=True, ge=0)]
_R = TypeVar("_R")


class RecordType(StrEnum):
    SPATIAL_ESTIMATE = "spatial_estimate"
    ENTITY_TRACK = "entity_track"
    SEMANTIC_BINDING = "semantic_binding"
    IMAGINED_BRANCH = "imagined_branch"


class RecordRef(Contract):
    """Content-addressed reference to another S05 record (digest, not a name)."""

    kind: Literal["record"] = "record"
    record_type: RecordType
    sha256: Digest
    available_at_step: StepIndex


class GridCellRef(Contract):
    """S06: reference to one visible cell of one public GridLab observation.

    Grid analogue of ``C0CellRef``: integer world-grid coordinates (x right,
    y down, no z), bound to the public observation's id and SHA.
    """

    kind: Literal["grid_cell"] = "grid_cell"
    coordinate_kind: Literal["grid_xy"] = "grid_xy"
    time: TimeIndex
    x: StepIndex
    y: StepIndex
    observation_id: UUID
    observation_sha256: Digest
    origin: OriginKind


ObservationRef = (C0CellRef, GridCellRef)
Ref = C0CellRef | GridCellRef | RecordRef


def _ref_step(ref: Ref) -> int:
    return ref.time.available_at_step if isinstance(ref, ObservationRef) else ref.available_at_step


def _ref_identity(ref: Ref) -> tuple:
    if isinstance(ref, C0CellRef):
        return ("c0", ref.observation_id, ref.cell)
    if isinstance(ref, GridCellRef):
        return ("grid", ref.observation_id, ref.x, ref.y)
    return ("record", ref.record_type, ref.sha256)


def _check_refs(refs: Iterable[Ref], *, asserted_at: int, partition, label: str) -> None:
    seen = set()
    for ref in refs:
        if _ref_step(ref) > asserted_at:
            raise ValueError(f"{label} cites evidence not yet available")
        if isinstance(ref, ObservationRef) and partition is not None and ref.time.partition is not partition:
            raise ValueError(f"{label} cannot mix dataset partitions")
        identity = _ref_identity(ref)
        if identity in seen:
            raise ValueError(f"{label} has duplicate references")
        seen.add(identity)


def _check_revision(revision: int, supersedes: str | None) -> None:
    if (revision == 0) != (supersedes is None):
        raise ValueError("revisions >0 must name the superseded record and only they")


# ---------------------------------------------------------------- SpatialEstimate


class CoordinateKind(StrEnum):
    SYMBOL_SLOT = "symbol_slot"
    GRID_XY = "grid_xy"
    IMAGE_XY = "image_xy"
    BODY_XYZ = "body_xyz"
    WORLD_XYZ = "world_xyz"


class Unit(StrEnum):
    CELL = "cell"
    PIXEL = "pixel"
    METRE = "metre"


class UncertaintyBasis(StrEnum):
    CALIBRATED = "calibrated"
    EMPIRICAL_DEV = "empirical_dev"
    NONE = "none"


class EstimateOrigin(StrEnum):
    OBSERVED = "observed"
    STUDENT_ESTIMATE = "student_estimate"
    PREDICTED = "predicted"
    TEACHER_CLAIM = "teacher_claim"
    IMAGINED = "imagined"
    EVALUATOR_PRIVATE = "evaluator_private"


DIMENSIONS = {
    CoordinateKind.SYMBOL_SLOT: 1,
    CoordinateKind.GRID_XY: 2,
    CoordinateKind.IMAGE_XY: 2,
    CoordinateKind.BODY_XYZ: 3,
    CoordinateKind.WORLD_XYZ: 3,
}
UNITS = {
    CoordinateKind.SYMBOL_SLOT: Unit.CELL,
    CoordinateKind.GRID_XY: Unit.CELL,
    CoordinateKind.IMAGE_XY: Unit.PIXEL,
    CoordinateKind.BODY_XYZ: Unit.METRE,
    CoordinateKind.WORLD_XYZ: Unit.METRE,
}


class SpatialEstimate(Contract):
    schema_version: Literal[1] = S05_SCHEMA_VERSION
    estimate_id: UUID
    time: TimeIndex
    coordinate_kind: CoordinateKind
    frame_id: Name
    frame_revision: Revision
    unit: Unit
    axes: Name
    body_version: Name | None = None
    sensor_id: Name | None = None
    value: tuple[Finite, ...]
    orientation: tuple[Finite, ...] | None = None
    extent: tuple[Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)], ...] | None = None
    uncertainty: tuple[Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)], ...] | None = None
    uncertainty_basis: UncertaintyBasis
    supports: tuple[Ref, ...] = ()
    origin: EstimateOrigin
    revision: Revision = 0
    supersedes_sha256: Digest | None = None

    @model_validator(mode="after")
    def spatial_rules(self) -> Self:
        dims = DIMENSIONS[self.coordinate_kind]
        if len(self.value) != dims:
            raise ValueError(f"{self.coordinate_kind} needs exactly {dims} coordinates (no fabricated z)")
        if self.unit is not UNITS[self.coordinate_kind]:
            raise ValueError(f"{self.coordinate_kind} must use unit {UNITS[self.coordinate_kind]}")
        if self.coordinate_kind is CoordinateKind.SYMBOL_SLOT and not float(self.value[0]).is_integer():
            raise ValueError("symbol_slot value is a slot index")
        if self.orientation is not None and (dims != 3 or len(self.orientation) != 4):
            raise ValueError("orientation is a quaternion and only exists for xyz kinds")
        if self.extent is not None and len(self.extent) != dims:
            raise ValueError("extent must match the coordinate dimensionality")
        if self.uncertainty is None:
            if self.uncertainty_basis is not UncertaintyBasis.NONE:
                raise ValueError("a basis without uncertainty values is meaningless")
        else:
            if self.uncertainty_basis is UncertaintyBasis.NONE:
                raise ValueError("uncertainty requires a calibrated or empirical basis")
            if len(self.uncertainty) != dims:
                raise ValueError("uncertainty must match the coordinate dimensionality")
        if self.origin is EstimateOrigin.EVALUATOR_PRIVATE:
            if self.supports:
                raise ValueError("evaluator-private truth cites no student evidence")
        elif not self.supports:
            raise ValueError("non-private estimates must cite supporting evidence")
        _check_refs(self.supports, asserted_at=self.time.available_at_step,
                    partition=self.time.partition, label="estimate")
        if self.origin is EstimateOrigin.OBSERVED:
            c0 = [r for r in self.supports if isinstance(r, ObservationRef)]
            if not c0 or any(r.origin is not OriginKind.OBSERVED for r in c0):
                raise ValueError("an observed estimate must cite observed C0 references only")
            if any(isinstance(r, RecordRef) for r in self.supports):
                raise ValueError("an observed estimate cannot rest on derived records")
        _check_revision(self.revision, self.supersedes_sha256)
        return self


def comparable(a: SpatialEstimate, b: SpatialEstimate) -> bool:
    """Same coordinate kind/frame revision/unit/axes/body and ordered times only."""
    a, b = _revalidate(SpatialEstimate, a), _revalidate(SpatialEstimate, b)
    same_frame = (a.coordinate_kind, a.frame_id, a.frame_revision, a.unit, a.axes, a.body_version) == (
        b.coordinate_kind, b.frame_id, b.frame_revision, b.unit, b.axes, b.body_version)
    return same_frame and compare_time(a.time, b.time) is not TimeOrder.NOT_COMPARABLE


def student_visible(records: Iterable[Any]) -> tuple:
    """Raise if evaluator-private truth would reach a student view."""
    out = []
    for record in records:
        record = revalidate_record(record)
        estimates = _nested_estimates(record)
        if any(e.origin is EstimateOrigin.EVALUATOR_PRIVATE for e in estimates):
            raise ValueError("evaluator-private estimate in a student-visible view")
        out.append(record)
    return tuple(out)


# ---------------------------------------------------------------- EntityTrack


class Visibility(StrEnum):
    VISIBLE = "visible"
    OCCLUDED = "occluded"
    LOST = "lost"  # should be visible (in view, line of sight) but not found
    UNKNOWN = "unknown"
    OUT_OF_VIEW = "out_of_view"  # S07: outside the field of view; same rules as occluded


class TrackState(Contract):
    time: TimeIndex
    visibility: Visibility
    estimate: SpatialEstimate | None = None

    @model_validator(mode="after")
    def state_rules(self) -> Self:
        e = self.estimate
        if e is None:
            if self.visibility is Visibility.VISIBLE:
                raise ValueError("a visible state needs an estimate")
            return self
        if self.visibility is not Visibility.VISIBLE and e.origin not in (
            EstimateOrigin.PREDICTED, EstimateOrigin.IMAGINED
        ):
            raise ValueError("occluded/lost/unknown states may only cite predicted or imagined estimates")
        if self.visibility is Visibility.VISIBLE and e.origin not in (
            EstimateOrigin.OBSERVED, EstimateOrigin.STUDENT_ESTIMATE
        ):
            raise ValueError("a visible state rests on an observed or student estimate")
        if compare_time(e.time, self.time) is not TimeOrder.SAME:
            raise ValueError("state estimate must be for the state's own time")
        return self


class IdentityHypothesis(Contract):
    candidate_world_id: UUID
    candidate_track_id: UUID
    supports: Annotated[tuple[Ref, ...], Field(min_length=1)]


class EntityTrack(Contract):
    schema_version: Literal[1] = S05_SCHEMA_VERSION
    world_id: UUID
    track_id: UUID  # instance identity, scoped to world_id
    concept_id: Name | None = None  # category, never the instance id
    identity_hypotheses: tuple[IdentityHypothesis, ...] = ()
    states: Annotated[tuple[TrackState, ...], Field(min_length=1)]
    asserted_at_step: StepIndex
    revision: Revision = 0
    supersedes_sha256: Digest | None = None

    @model_validator(mode="after")
    def track_rules(self) -> Self:
        partition = self.states[0].time.partition
        for state in self.states:
            if state.time.world_id != self.world_id or state.time.partition is not partition:
                raise ValueError("track states stay within the track's world and partition")
            if state.time.available_at_step > self.asserted_at_step:
                raise ValueError("track cites states not yet available")
        for prev, cur in zip(self.states, self.states[1:]):
            if compare_time(prev.time, cur.time) is not TimeOrder.BEFORE:
                raise ValueError("track states must be strictly time ordered")
        keys = set()
        for h in self.identity_hypotheses:
            key = (h.candidate_world_id, h.candidate_track_id)
            if key == (self.world_id, self.track_id) or key in keys:
                raise ValueError("identity hypotheses must be distinct other tracks")
            keys.add(key)
            _check_refs(h.supports, asserted_at=self.asserted_at_step, partition=None,
                        label="identity hypothesis")
        _check_revision(self.revision, self.supersedes_sha256)
        return self


# ---------------------------------------------------------------- SemanticBinding


class BindingRelation(StrEnum):
    NAMES = "names"
    ATTRIBUTE = "attribute"
    ACTION = "action"
    GOAL = "goal"


class Assistance(StrEnum):
    NONE = "none"
    TEACHER_NAMED = "teacher_named"
    CURRICULUM_HINT = "curriculum_hint"
    DEMONSTRATION = "demonstration"
    LABEL = "label"


class SemanticBinding(Contract):
    schema_version: Literal[1] = S05_SCHEMA_VERSION
    binding_id: UUID
    subject: Ref
    concept_id: Name
    concept_revision: Revision
    term: Annotated[str, StringConstraints(strict=True, min_length=1, max_length=256)]
    relation: BindingRelation
    namer: Name
    assistance: Assistance  # explicit: no default may hide teacher help
    supports: Annotated[tuple[Ref, ...], Field(min_length=1)]
    counterexamples: tuple[Ref, ...] = ()
    available_at_step: StepIndex
    revision: Revision = 0
    supersedes_sha256: Digest | None = None

    @model_validator(mode="after")
    def binding_rules(self) -> Self:
        if self.term != self.term.strip():
            raise ValueError("term must not carry surrounding whitespace")
        partitions = {r.time.partition for r in (self.subject, *self.supports, *self.counterexamples)
                      if isinstance(r, ObservationRef)}
        if len(partitions) > 1:
            raise ValueError("binding cannot mix dataset partitions")
        refs = (self.subject, *self.supports, *self.counterexamples)
        if any(_ref_step(r) > self.available_at_step for r in refs):
            raise ValueError("binding cites evidence not yet available")
        support_ids = [_ref_identity(r) for r in self.supports]
        counter_ids = [_ref_identity(r) for r in self.counterexamples]
        if len(set(support_ids)) != len(support_ids) or len(set(counter_ids)) != len(counter_ids):
            raise ValueError("duplicate references")
        if set(support_ids) & set(counter_ids):
            raise ValueError("a reference cannot both support and contradict a binding")
        if _ref_identity(self.subject) in set(support_ids) | set(counter_ids):
            raise ValueError("a binding cannot cite its own subject as evidence")
        _check_revision(self.revision, self.supersedes_sha256)
        return self


# ---------------------------------------------------------------- ImaginedBranch


class ImaginedBranch(Contract):
    schema_version: Literal[1] = S05_SCHEMA_VERSION
    branch_id: UUID
    parent_branch_id: UUID | None = None
    start_belief: RecordRef
    evidence_cutoff_step: StepIndex
    model_version: Name
    mechanism_version: Name
    hypothetical_actions: Annotated[tuple[Annotated[int, Field(strict=True, ge=0)], ...], Field(min_length=1)]
    horizon: Annotated[int, Field(strict=True, ge=1)]
    budget_units: Annotated[int, Field(strict=True, ge=1)]
    predictions: Annotated[tuple[SpatialEstimate, ...], Field(min_length=1)]
    checked_against: tuple[C0CellRef, ...] = ()
    revision: Revision = 0
    supersedes_sha256: Digest | None = None

    @model_validator(mode="after")
    def branch_rules(self) -> Self:
        if self.parent_branch_id == self.branch_id:
            raise ValueError("a branch cannot be its own parent")
        if self.horizon != len(self.hypothetical_actions):
            raise ValueError("horizon must equal the number of hypothetical actions")
        if self.start_belief.available_at_step > self.evidence_cutoff_step:
            raise ValueError("start belief was not available at the evidence cutoff")
        for p in self.predictions:
            if p.origin is not EstimateOrigin.IMAGINED:
                raise ValueError("branch predictions must have origin imagined")
            if p.time.step <= self.evidence_cutoff_step:
                raise ValueError("predictions are about steps after the evidence cutoff")
            if any(_ref_step(r) > self.evidence_cutoff_step for r in p.supports):
                raise ValueError("predictions cannot use evidence after the cutoff")
        seen = set()
        for ref in self.checked_against:
            if ref.origin is not OriginKind.OBSERVED:
                raise ValueError("branches are checked only against observed outcomes")
            if ref.time.step <= self.evidence_cutoff_step:
                raise ValueError("checking outcomes must come after the evidence cutoff")
            if _ref_identity(ref) in seen:
                raise ValueError("duplicate outcome references")
            seen.add(_ref_identity(ref))
        _check_revision(self.revision, self.supersedes_sha256)
        return self


def branch_evidence(branch: ImaginedBranch) -> dict:
    """Support derived from a branch: prediction/outcome pairs, never the prediction alone."""
    branch = _revalidate(ImaginedBranch, branch)
    if not branch.checked_against:
        raise ValueError("an unchecked imagined branch cannot serve as evidence")
    return {
        "branch_sha256": record_digest(branch),
        "predictions": [record_digest(p) for p in branch.predictions],
        "outcomes": [{"observation_id": str(r.observation_id), "cell": r.cell,
                      "observation_sha256": r.observation_sha256} for r in branch.checked_against],
        "kind": "prediction_outcome_pairs",
    }


# ---------------------------------------------------------------- serialisation & views

RECORD_TYPES = {
    SpatialEstimate: RecordType.SPATIAL_ESTIMATE,
    EntityTrack: RecordType.ENTITY_TRACK,
    SemanticBinding: RecordType.SEMANTIC_BINDING,
    ImaginedBranch: RecordType.IMAGINED_BRANCH,
}
_ID_FIELD = {SpatialEstimate: "estimate_id", EntityTrack: "track_id", SemanticBinding: "binding_id",
             ImaginedBranch: "branch_id"}


def revalidate_record(record: Any):
    for cls in RECORD_TYPES:
        if isinstance(record, cls):
            return _revalidate(cls, record)
    raise ValueError(f"not an S05 record: {type(record).__name__}")


def to_canonical_json(record) -> bytes:
    return canonical_bytes(revalidate_record(record).model_dump(mode="json"))


def record_digest(record) -> str:
    return hashlib.sha256(to_canonical_json(record)).hexdigest()


def record_ref(record) -> RecordRef:
    record = revalidate_record(record)
    return RecordRef(record_type=RECORD_TYPES[type(record)], sha256=record_digest(record),
                     available_at_step=available_at(record))


def load_record(cls: type[_R], raw: bytes | str) -> _R:
    if cls not in RECORD_TYPES:
        raise ValueError("unknown S05 record type")
    return cls.model_validate_json(raw)


def available_at(record) -> int:
    record = revalidate_record(record)
    if isinstance(record, SpatialEstimate):
        return record.time.available_at_step
    if isinstance(record, EntityTrack):
        return record.asserted_at_step
    if isinstance(record, SemanticBinding):
        return record.available_at_step
    return max([record.evidence_cutoff_step, *(_ref_step(r) for r in record.checked_against)])


def _nested_estimates(record) -> list[SpatialEstimate]:
    if isinstance(record, SpatialEstimate):
        return [record]
    if isinstance(record, EntityTrack):
        return [s.estimate for s in record.states if s.estimate is not None]
    if isinstance(record, ImaginedBranch):
        return list(record.predictions)
    return []


def validate_history(records: Iterable[Any]) -> tuple:
    """Append-only revision chains per (type, id): no gaps, forks, rewrites or backdating."""
    checked = tuple(revalidate_record(r) for r in records)
    by_digest = {}
    for r in checked:
        d = record_digest(r)
        if d in by_digest:
            raise ValueError("duplicate record identity in history")
        by_digest[d] = r
    successors = set()
    for r in checked:
        if r.supersedes_sha256 is None:
            continue
        prev = by_digest.get(r.supersedes_sha256)
        if prev is None:
            raise ValueError("revision predecessor is missing")
        if type(prev) is not type(r) or getattr(prev, _ID_FIELD[type(r)]) != getattr(r, _ID_FIELD[type(r)]):
            raise ValueError("revision must keep record type and id")
        if r.supersedes_sha256 in successors:
            raise ValueError("forked revision")
        successors.add(r.supersedes_sha256)
        if r.revision != prev.revision + 1:
            raise ValueError("revision numbers must increase by exactly one")
        if available_at(r) < available_at(prev):
            raise ValueError("revision made available before its predecessor")
    return checked


def records_visible_at(records: Iterable[Any], step: int) -> tuple:
    """As-of view: validated history, then hide records not yet available at ``step``."""
    if type(step) is not int or step < 0:
        raise ValueError("step must be a non-negative int")
    return tuple(r for r in validate_history(records) if available_at(r) <= step)
