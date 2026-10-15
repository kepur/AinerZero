"""Conservative v1 archive conversion. It never grants training eligibility."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ainerzero.core.contracts import ActionRequest, ActionResult, Observation, SourceKind
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    Actor,
    ActorKind,
    AssistanceKind,
    DatasetPartition,
    EpisodeIdentity,
    LegacyTrace,
    ObservationV2,
    OriginKind,
)


@dataclass(frozen=True)
class MigrationResult:
    record: ObservationV2 | ActionRequestV2 | ActionResultV2
    warnings: tuple[str, ...]


def migrate_v1(record: Observation | ActionRequest | ActionResult) -> MigrationResult:
    """Preserve IDs/content; missing partition, actor and body metadata stay unknown.

    The digest identifies canonical v1 JSON, not the original file's byte order.
    No partition override is accepted. This is archive migration, not review or
    admission; a later review would produce a separate, traceable derived record.
    """
    if type(record) not in (Observation, ActionRequest, ActionResult):
        raise TypeError("migration requires a supported v1 record")
    record = type(record).model_validate(record)
    encoded = json.dumps(
        record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    context = EpisodeIdentity(
        run_id=record.run_id,
        episode_id=record.episode_id,
        partition=DatasetPartition.QUARANTINE,
        environment_instance_id=None,
        environment_revision=None,
        action_schema_revision=None,
    )
    common = {
        "id": record.id,
        "created_at": record.created_at,
        "step": record.step,
        "context": context,
        "legacy": LegacyTrace(
            record_id=record.id,
            source_kind=record.source_kind,
            record_sha256=hashlib.sha256(encoded).hexdigest(),
        ),
    }
    origin = {
        SourceKind.OBSERVED: OriginKind.OBSERVED,
        SourceKind.TEACHER_DEMO: OriginKind.OBSERVED,
        SourceKind.TEACHER_CLAIM: OriginKind.TEACHER_CLAIM,
        SourceKind.IMAGINED: OriginKind.IMAGINED,
        SourceKind.EVAL_ONLY: OriginKind.UNKNOWN,
    }[record.source_kind]
    warnings = ["v1 dataset partition and environment identity are unknown; quarantined"]
    if record.source_kind is SourceKind.EVAL_ONLY:
        warnings.append("v1 eval_only does not distinguish development/final or evidence origin")
    if isinstance(record, Observation):
        converted = ObservationV2(**common, origin=origin, payload=record.payload)
    elif isinstance(record, ActionRequest):
        assistance = (AssistanceKind.UNKNOWN,)
        if record.source_kind is SourceKind.TEACHER_DEMO:
            assistance += (AssistanceKind.DEMONSTRATION,)
        converted = ActionRequestV2(
            **common,
            action=record.action,
            actor=Actor(kind=ActorKind.UNKNOWN),
            assistance=assistance,
        )
        warnings.append("v1 does not identify the action decision maker or full assistance")
    else:
        converted = ActionResultV2(
            **common,
            origin=origin,
            request_id=record.request_id,
            action=record.action,
            status=record.status,
            observation_id=record.observation_id,
            submitted_at=record.submitted_at,
            completed_at=record.completed_at,
            elapsed_ns=record.completed_monotonic_ns - record.submitted_monotonic_ns,
        )
    return MigrationResult(converted, tuple(warnings))
