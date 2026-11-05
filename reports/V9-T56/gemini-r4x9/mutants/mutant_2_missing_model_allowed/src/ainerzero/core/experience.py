"""Minimal v2 symbol experience, separating evidence from action ownership.

These contracts check declared structure, not authenticity. The future trusted
collector assigns the episode partition; a sender saying "train" is not proof.
No database, tensor runtime, or general-purpose asset registry is needed here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, StringConstraints, field_validator, model_validator

from ainerzero.core.contracts import (
    ActionId,
    ActionStatus,
    Contract,
    SourceKind,
    StepIndex,
    SymbolObservation,
    _utc,
    utc_now,
)

Name = Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)]
Digest = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]


class DatasetPartition(StrEnum):
    TRAIN = "train"
    DEVELOPMENT = "development"
    FINAL = "final"
    QUARANTINE = "quarantine"


class OriginKind(StrEnum):
    OBSERVED = "observed"
    TEACHER_CLAIM = "teacher_claim"
    IMAGINED = "imagined"
    EXTERNAL_DERIVED = "external_derived"
    UNKNOWN = "unknown"


class ActorKind(StrEnum):
    STUDENT = "student"
    HUMAN_TEACHER = "human_teacher"
    LLM_TEACHER = "llm_teacher"
    BASELINE = "baseline"
    SYSTEM = "system"
    UNKNOWN = "unknown"


class AssistanceKind(StrEnum):
    DEMONSTRATION = "demonstration"
    CURRICULUM = "curriculum"
    LABEL = "label"
    RULE = "rule"
    UNKNOWN = "unknown"


class Actor(Contract):
    """The decision maker, not the adapter that delivers the action."""

    kind: ActorKind
    actor_id: Name | None = None
    policy_revision: Name | None = None

    @model_validator(mode="after")
    def identified_when_known(self) -> Self:
        if self.kind is not ActorKind.UNKNOWN and (
            self.actor_id is None or self.policy_revision is None
        ):
            raise ValueError("known actors require actor_id and policy_revision")
        if self.kind is ActorKind.UNKNOWN and (
            self.actor_id is not None or self.policy_revision is not None
        ):
            raise ValueError("unknown actors cannot claim an identity")
        return self


class EpisodeIdentity(Contract):
    run_id: UUID
    episode_id: UUID
    partition: DatasetPartition
    # None is retained for legacy records that did not capture these fields.
    environment_instance_id: UUID | None
    environment_revision: Name | None
    action_schema_revision: Name | None


class LegacyTrace(Contract):
    record_id: UUID
    source_kind: SourceKind
    record_sha256: Digest


class ExperienceRecord(Contract):
    schema_version: Annotated[int, Field(strict=True, ge=2, le=2)] = 2
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=utc_now)
    context: EpisodeIdentity
    step: StepIndex
    legacy: LegacyTrace | None = None

    @field_validator("created_at")
    @classmethod
    def aware_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def legacy_stays_quarantined(self) -> Self:
        if self.legacy is not None:
            if self.legacy.record_id != self.id:
                raise ValueError("legacy trace must preserve the original record ID")
            if self.context.partition is not DatasetPartition.QUARANTINE:
                raise ValueError("legacy records remain quarantined until a separate review")
        return self


class ObservationV2(ExperienceRecord):
    kind: Literal["observation"] = "observation"
    origin: OriginKind
    payload: SymbolObservation

    @model_validator(mode="after")
    def start_matches_step(self) -> Self:
        if self.payload.episode_start != (self.step == 0):
            raise ValueError("episode_start must be true exactly at step 0")
        return self


class ActionRequestV2(ExperienceRecord):
    kind: Literal["action_request"] = "action_request"
    action: ActionId
    actor: Actor
    assistance: tuple[AssistanceKind, ...] = ()

    @model_validator(mode="after")
    def teacher_action_is_a_demo(self) -> Self:
        if self.actor.kind in {ActorKind.HUMAN_TEACHER, ActorKind.LLM_TEACHER}:
            if AssistanceKind.DEMONSTRATION not in self.assistance:
                raise ValueError("teacher actions must declare demonstration assistance")
        return self


class ActionResultV2(ExperienceRecord):
    kind: Literal["action_result"] = "action_result"
    origin: OriginKind
    request_id: UUID
    action: ActionId
    status: ActionStatus
    observation_id: UUID | None = None
    submitted_at: datetime
    completed_at: datetime
    # Computed within the executor's clock domain, never by comparing clocks
    # from different processes or episodes. Wall time may move backwards.
    elapsed_ns: StepIndex

    @field_validator("submitted_at", "completed_at")
    @classmethod
    def execution_timestamps_utc(cls, value: datetime) -> datetime:
        return _utc(value)

    @model_validator(mode="after")
    def accepted_result_has_observation(self) -> Self:
        if self.status is ActionStatus.ACCEPTED and self.observation_id is None:
            raise ValueError("accepted actions must reference their resulting observation")
        return self


class ExperienceTransition(Contract):
    """A linked transition can be archived even when not admissible for training."""

    observation: ObservationV2
    action_request: ActionRequestV2
    action_result: ActionResultV2
    next_observation: ObservationV2

    @model_validator(mode="after")
    def linked_transition(self) -> Self:
        before, request, result, after = (
            self.observation,
            self.action_request,
            self.action_result,
            self.next_observation,
        )
        records = (before, request, result, after)
        if any(record.context != before.context for record in records):
            raise ValueError("transition cannot cross run, episode, partition or environment")
        if len({record.id for record in records}) != len(records):
            raise ValueError("transition records must have distinct IDs")
        if request.step != before.step or result.step != before.step:
            raise ValueError("action steps must match the preceding observation")
        if after.step != before.step + 1:
            raise ValueError("training observations must be consecutive")
        if result.request_id != request.id or result.action != request.action:
            raise ValueError("result must match its action request")
        if result.status is not ActionStatus.ACCEPTED:
            raise ValueError("a transition requires an accepted action")
        if result.observation_id != after.id:
            raise ValueError("result must reference next_observation")
        return self


class TrainingPolicy(Contract):
    """Explicit actor/version allowlist; no implicit permission for all baselines."""

    allowed_actors: tuple[Actor, ...]
    allowed_assistance: tuple[AssistanceKind, ...] = ()

    @model_validator(mode="after")
    def unknown_is_not_permission(self) -> Self:
        if any(actor.kind is ActorKind.UNKNOWN for actor in self.allowed_actors):
            raise ValueError("unknown actors cannot be authorized for training")
        if AssistanceKind.UNKNOWN in self.allowed_assistance:
            raise ValueError("unknown assistance cannot be authorized for training")
        return self


def admit_training(
    transition: ExperienceTransition, policy: TrainingPolicy
) -> ExperienceTransition:
    """Replay-entry guard, not authentication or whole-experiment attribution.

    A student action after a teacher action is still student-owned. Calling an
    entire experiment "unassisted" additionally requires its full history and
    run conditions; this local transition check does not establish that claim.
    """
    # Revalidate copied/mutated Pydantic instances at the actual entry boundary.
    transition = ExperienceTransition.model_validate(transition)
    policy = TrainingPolicy.model_validate(policy)
    context = transition.observation.context
    if context.partition is not DatasetPartition.TRAIN:
        raise ValueError("only train partition experience is admitted")
    if any(
        value is None
        for value in (
            context.environment_instance_id,
            context.environment_revision,
            context.action_schema_revision,
        )
    ):
        raise ValueError("training requires known environment and action versions")
    for record in (
        transition.observation,
        transition.action_result,
        transition.next_observation,
    ):
        if record.origin is not OriginKind.OBSERVED:
            raise ValueError("training requires observed evidence throughout the transition")
    request = transition.action_request
    if request.actor not in policy.allowed_actors:
        raise ValueError("action actor or policy revision is not authorized")
    if not set(request.assistance).issubset(policy.allowed_assistance):
        raise ValueError("action assistance is not authorized")
    return transition
