"""Public sensor/action contracts and a fail-closed training data boundary.

Environment snapshots and evaluator truth are intentionally absent. These
contracts protect structure/provenance, not the truthfulness of an untrusted
producer; the environment adapter must construct payloads from its public view.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from time import monotonic_ns
from typing import Annotated, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CELL_COUNT = 8
HIDDEN_PLACEHOLDER_BYTE = 0
Byte = Annotated[int, Field(strict=True, ge=0, le=255)]
CellIndex = Annotated[int, Field(strict=True, ge=0, lt=CELL_COUNT)]
ActionId = Annotated[int, Field(strict=True, ge=0, le=3)]
StepIndex = Annotated[int, Field(strict=True, ge=0)]


class SourceKind(StrEnum):
    OBSERVED = "observed"
    TEACHER_DEMO = "teacher_demo"
    TEACHER_CLAIM = "teacher_claim"
    IMAGINED = "imagined"
    EVAL_ONLY = "eval_only"


TRAINING_SOURCES = frozenset({SourceKind.OBSERVED, SourceKind.TEACHER_DEMO})


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        validate_default=True,
        allow_inf_nan=False,
        revalidate_instances="always",
    )


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("record timestamps must include an explicit timezone")
    return value.astimezone(timezone.utc)


class RecordBase(Contract):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)] = 1
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    # Monotonic timestamps are comparable only inside the producing process.
    monotonic_ns: StepIndex = Field(default_factory=monotonic_ns)
    run_id: UUID
    episode_id: UUID | None = None
    source_kind: SourceKind

    @field_validator("created_at")
    @classmethod
    def timestamp_in_utc(cls, value: datetime) -> datetime:
        return _utc(value)


class SymbolObservation(Contract):
    symbols: Annotated[tuple[Byte, ...], Field(min_length=CELL_COUNT, max_length=CELL_COUNT)]
    visible_mask: Annotated[
        tuple[Annotated[bool, Field(strict=True)], ...],
        Field(min_length=CELL_COUNT, max_length=CELL_COUNT),
    ]
    cursor: CellIndex
    episode_start: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def no_hidden_values(self) -> Self:
        for symbol, visible in zip(self.symbols, self.visible_mask, strict=True):
            if not visible and symbol != HIDDEN_PLACEHOLDER_BYTE:
                raise ValueError("hidden cells must contain the placeholder byte 0")
        return self


class Observation(RecordBase):
    episode_id: UUID
    step: StepIndex
    payload: SymbolObservation

    @model_validator(mode="after")
    def start_matches_step(self) -> Self:
        if self.payload.episode_start != (self.step == 0):
            raise ValueError("episode_start must be true exactly at step 0")
        return self


class ActionRequest(RecordBase):
    episode_id: UUID
    step: StepIndex
    action: ActionId


class ActionStatus(StrEnum):
    # Accepted means delivered to the environment, not successful at the goal.
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class ActionResult(RecordBase):
    episode_id: UUID
    request_id: UUID
    step: StepIndex
    action: ActionId
    status: ActionStatus
    observation_id: UUID | None = None
    submitted_at: datetime
    completed_at: datetime
    submitted_monotonic_ns: StepIndex
    completed_monotonic_ns: StepIndex

    @field_validator("submitted_at", "completed_at")
    @classmethod
    def timestamps_in_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def valid_result(self) -> Self:
        if self.completed_monotonic_ns < self.submitted_monotonic_ns:
            raise ValueError("completion cannot precede submission on the monotonic clock")
        if self.status is ActionStatus.ACCEPTED and self.observation_id is None:
            raise ValueError("an accepted action must reference its resulting observation")
        return self


def require_training_source(record: RecordBase) -> None:
    """Reject claims, imagined rollouts, and evaluation records at replay entry."""
    if record.source_kind not in TRAINING_SOURCES:
        raise ValueError(f"source {record.source_kind.value!r} is not permitted for training")


class TrainingTransition(Contract):
    observation: Observation
    action_result: ActionResult
    next_observation: Observation

    @model_validator(mode="after")
    def validate_evidence_chain(self) -> Self:
        records = (self.observation, self.action_result, self.next_observation)
        for record in records:
            require_training_source(record)
        if len({record.run_id for record in records}) != 1:
            raise ValueError("training transition cannot cross runs")
        if len({record.episode_id for record in records}) != 1:
            raise ValueError("training transition cannot cross episodes")
        if len({record.source_kind for record in records}) != 1:
            raise ValueError("training transition must preserve a consistent provenance")
        if self.action_result.status is not ActionStatus.ACCEPTED:
            raise ValueError("training transition requires an accepted action")
        if self.action_result.observation_id != self.next_observation.id:
            raise ValueError("action result must reference next_observation")
        if self.action_result.step != self.observation.step:
            raise ValueError("action step must match the preceding observation")
        if self.next_observation.step != self.observation.step + 1:
            raise ValueError("training observations must be consecutive")
        return self
