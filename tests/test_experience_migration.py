import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ainerzero.core.contracts import (
    ActionRequest,
    ActionResult,
    ActionStatus,
    Observation,
    RecordBase,
    SourceKind,
    SymbolObservation,
)
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    Actor,
    ActorKind,
    AssistanceKind,
    DatasetPartition,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
    admit_training,
)
from ainerzero.core.experience_migration import migrate_v1


def legacy_records(source):
    common = {"run_id": uuid4(), "episode_id": uuid4(), "source_kind": source}
    observations = [
        Observation(
            **common,
            step=step,
            payload=SymbolObservation(
                symbols=(0, 65, 66, 67, 0, 69, 70, 71),
                visible_mask=(False, True, True, True, False, True, True, True),
                cursor=step,
                episode_start=step == 0,
            ),
        )
        for step in range(2)
    ]
    before, after = observations
    request = ActionRequest(**common, step=0, action=3)
    result = ActionResult(
        **common,
        step=0,
        request_id=request.id,
        action=request.action,
        status=ActionStatus.ACCEPTED,
        observation_id=after.id,
        submitted_at=before.created_at,
        completed_at=after.created_at,
        submitted_monotonic_ns=100,
        completed_monotonic_ns=250,
    )
    return {
        "observation": before,
        "action_request": request,
        "action_result": result,
        "next_observation": after,
    }


def student_policy():
    return TrainingPolicy(
        allowed_actors=(Actor(kind=ActorKind.STUDENT, actor_id="student-1", policy_revision="v1"),)
    )


@pytest.mark.parametrize("source", list(SourceKind))
def test_each_legacy_source_preserves_linked_content_but_remains_quarantined(source):
    originals = legacy_records(source)
    snapshots = {name: record.model_dump_json() for name, record in originals.items()}
    conversions = {name: migrate_v1(record) for name, record in originals.items()}
    converted = {name: result.record for name, result in conversions.items()}
    archived = ExperienceTransition(**converted)
    assert {name: record.model_dump_json() for name, record in originals.items()} == snapshots
    expected_origin = {
        SourceKind.OBSERVED: OriginKind.OBSERVED,
        SourceKind.TEACHER_DEMO: OriginKind.OBSERVED,
        SourceKind.TEACHER_CLAIM: OriginKind.TEACHER_CLAIM,
        SourceKind.IMAGINED: OriginKind.IMAGINED,
        SourceKind.EVAL_ONLY: OriginKind.UNKNOWN,
    }[source]
    for name, previous in originals.items():
        record = converted[name]
        assert record.id == previous.id
        assert record.created_at == previous.created_at
        assert record.step == previous.step
        assert record.schema_version == 2
        assert record.context.run_id == previous.run_id
        assert record.context.episode_id == previous.episode_id
        assert record.context.partition is DatasetPartition.QUARANTINE
        assert record.context.environment_instance_id is None
        assert record.context.environment_revision is None
        assert record.context.action_schema_revision is None
        assert record.legacy.record_id == previous.id
        assert record.legacy.source_kind is source
        canonical = json.dumps(
            previous.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        assert record.legacy.record_sha256 == hashlib.sha256(canonical).hexdigest()
        assert conversions[name].warnings
        if isinstance(record, ObservationV2):
            assert record.payload == previous.payload
            assert record.origin is expected_origin
        elif isinstance(record, ActionRequestV2):
            assert record.action == previous.action
            assert record.actor == Actor(kind=ActorKind.UNKNOWN)
            assert AssistanceKind.UNKNOWN in record.assistance
            assert (AssistanceKind.DEMONSTRATION in record.assistance) == (
                source is SourceKind.TEACHER_DEMO
            )
        else:
            assert isinstance(record, ActionResultV2)
            assert record.origin is expected_origin
            assert record.action == previous.action
            assert record.request_id == previous.request_id
            assert record.observation_id == previous.observation_id
            assert record.status == previous.status
            assert record.submitted_at == previous.submitted_at
            assert record.completed_at == previous.completed_at
            assert record.elapsed_ns == 150
    assert ExperienceTransition.model_validate_json(archived.model_dump_json()) == archived
    with pytest.raises(ValueError, match="only train partition"):
        admit_training(archived, student_policy())


@pytest.mark.parametrize("source", list(SourceKind))
@pytest.mark.parametrize("partition", [DatasetPartition.TRAIN, DatasetPartition.FINAL])
def test_legacy_trace_rejects_partition_relabelling_even_with_model_copy(source, partition):
    converted = {name: migrate_v1(record).record for name, record in legacy_records(source).items()}
    forged = {
        name: record.model_copy(
            update={"context": record.context.model_copy(update={"partition": partition})}
        )
        for name, record in converted.items()
    }
    with pytest.raises(ValidationError, match="legacy records remain quarantined"):
        ExperienceTransition(**forged)


def test_eval_only_cannot_be_migrated_with_partition_override():
    original = legacy_records(SourceKind.EVAL_ONLY)["observation"]
    with pytest.raises(TypeError, match="partition"):
        migrate_v1(original, partition=DatasetPartition.TRAIN)
    result = migrate_v1(original)
    assert result.record.context.partition is DatasetPartition.QUARANTINE
    assert any("development/final" in warning for warning in result.warnings)


def test_migrated_unknown_actor_and_assistance_cannot_be_authorized():
    request = migrate_v1(legacy_records(SourceKind.OBSERVED)["action_request"]).record
    with pytest.raises(ValidationError, match="unknown actors"):
        TrainingPolicy(allowed_actors=(request.actor,))
    with pytest.raises(ValidationError, match="unknown assistance"):
        TrainingPolicy(
            allowed_actors=student_policy().allowed_actors,
            allowed_assistance=request.assistance,
        )


def test_migration_revalidates_nested_copied_legacy_record():
    original = legacy_records(SourceKind.OBSERVED)["observation"]
    bad_payload = original.payload.model_copy(update={"symbols": (65,) * 8})
    forged = original.model_copy(update={"payload": bad_payload})
    with pytest.raises(ValidationError, match="placeholder"):
        migrate_v1(forged)


def test_migration_rejects_unsupported_or_already_migrated_inputs():
    original = legacy_records(SourceKind.OBSERVED)["observation"]
    for unsupported in (
        original.model_dump(),
        RecordBase(run_id=uuid4(), source_kind=SourceKind.OBSERVED),
        migrate_v1(original).record,
    ):
        with pytest.raises(TypeError, match="supported v1 record"):
            migrate_v1(unsupported)


def test_migration_hash_is_repeatable_and_sensitive_to_source_content():
    original = legacy_records(SourceKind.OBSERVED)["observation"]
    first = migrate_v1(original).record
    second = migrate_v1(original).record
    assert first == second
    changed_raw = original.model_dump()
    changed_raw["payload"]["cursor"] = 3
    changed = migrate_v1(Observation.model_validate(changed_raw)).record
    assert first.id == changed.id
    assert first.legacy.record_sha256 != changed.legacy.record_sha256


def test_legacy_trace_cannot_claim_a_different_record_identity():
    converted = migrate_v1(legacy_records(SourceKind.OBSERVED)["observation"]).record
    raw = converted.model_dump()
    raw["legacy"]["record_id"] = uuid4()
    with pytest.raises(ValidationError, match="preserve the original record ID"):
        ObservationV2.model_validate(raw)
