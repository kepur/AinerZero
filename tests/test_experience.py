from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ainerzero.core.contracts import ActionStatus, SymbolObservation
from ainerzero.core.experience import (
    ActionRequestV2,
    ActionResultV2,
    Actor,
    ActorKind,
    AssistanceKind,
    DatasetPartition,
    EpisodeIdentity,
    ExperienceTransition,
    ObservationV2,
    OriginKind,
    TrainingPolicy,
    admit_training,
)


def student(**updates):
    return Actor(
        **{
            "kind": ActorKind.STUDENT,
            "actor_id": "student-1",
            "policy_revision": "candidate-3",
            **updates,
        }
    )


def episode(**updates):
    return EpisodeIdentity(
        **{
            "run_id": uuid4(),
            "episode_id": uuid4(),
            "partition": DatasetPartition.TRAIN,
            "environment_instance_id": uuid4(),
            "environment_revision": "switchlab-c0-v1",
            "action_schema_revision": "switchlab-actions-v1",
            **updates,
        }
    )


def observe(context, step):
    return ObservationV2(
        context=context,
        step=step,
        origin=OriginKind.OBSERVED,
        payload=SymbolObservation(
            symbols=(65,) * 8,
            visible_mask=(True,) * 8,
            cursor=0,
            episode_start=step == 0,
        ),
    )


def transition(*, context=None, actor=None, assistance=(), before=None):
    context = before.context if before is not None else context or episode()
    before = before or observe(context, 0)
    after = observe(context, before.step + 1)
    request = ActionRequestV2(
        context=context,
        step=before.step,
        action=3,
        actor=actor or student(),
        assistance=assistance,
    )
    result = ActionResultV2(
        context=context,
        step=before.step,
        origin=OriginKind.OBSERVED,
        request_id=request.id,
        action=request.action,
        status=ActionStatus.ACCEPTED,
        observation_id=after.id,
        submitted_at=before.created_at,
        completed_at=after.created_at,
        elapsed_ns=10,
    )
    return ExperienceTransition(
        observation=before,
        action_request=request,
        action_result=result,
        next_observation=after,
    )


def autonomous_policy():
    return TrainingPolicy(allowed_actors=(student(),))


def test_teacher_takeover_and_return_reuse_existing_observations_without_relabelling():
    first = transition()
    original = first.next_observation.model_dump_json()
    teacher = Actor(
        kind=ActorKind.HUMAN_TEACHER,
        actor_id="teacher-1",
        policy_revision="manual-v1",
    )
    demo = transition(
        before=first.next_observation,
        actor=teacher,
        assistance=(AssistanceKind.DEMONSTRATION,),
    )
    resumed = transition(before=demo.next_observation)
    assert first.next_observation.model_dump_json() == original
    assert demo.observation.model_dump_json() == original
    assert resumed.observation == demo.next_observation
    assert {item.origin for item in (demo.observation, demo.next_observation)} == {
        OriginKind.OBSERVED
    }
    teaching_policy = TrainingPolicy(
        allowed_actors=(student(), teacher),
        allowed_assistance=(AssistanceKind.DEMONSTRATION,),
    )
    assert admit_training(first, autonomous_policy()) == first
    assert admit_training(demo, teaching_policy) == demo
    with pytest.raises(ValueError, match="actor or policy revision"):
        admit_training(demo, autonomous_policy())
    assert ExperienceTransition.model_validate_json(resumed.model_dump_json()) == resumed


@pytest.mark.parametrize("partition", list(DatasetPartition))
def test_only_train_partition_can_enter_replay(partition):
    record = transition(context=episode(partition=partition))
    if partition is DatasetPartition.TRAIN:
        assert admit_training(record, autonomous_policy()) == record
    else:
        with pytest.raises(ValueError, match="only train partition"):
            admit_training(record, autonomous_policy())


@pytest.mark.parametrize("part", ["observation", "action_result", "next_observation"])
@pytest.mark.parametrize(
    "origin", [origin for origin in OriginKind if origin is not OriginKind.OBSERVED]
)
def test_one_non_observed_record_disqualifies_whole_transition(part, origin):
    raw = transition().model_dump()
    raw[part]["origin"] = origin
    archived = ExperienceTransition.model_validate(raw)
    with pytest.raises(ValueError, match="observed evidence throughout"):
        admit_training(archived, autonomous_policy())


@pytest.mark.parametrize(
    "changed_actor",
    [
        {"actor_id": "student-2"},
        {"policy_revision": "candidate-4"},
        {"kind": ActorKind.BASELINE},
        {"kind": ActorKind.SYSTEM},
    ],
)
def test_actor_whitelist_binds_kind_identity_and_exact_policy_revision(changed_actor):
    record = transition(actor=student(**changed_actor))
    with pytest.raises(ValueError, match="actor or policy revision"):
        admit_training(record, autonomous_policy())
    explicit = TrainingPolicy(allowed_actors=(record.action_request.actor,))
    assert admit_training(record, explicit) == record


@pytest.mark.parametrize(
    "assistance", [item for item in AssistanceKind if item is not AssistanceKind.UNKNOWN]
)
def test_student_actor_does_not_hide_assistance(assistance):
    record = transition(assistance=(assistance,))
    with pytest.raises(ValueError, match="assistance is not authorized"):
        admit_training(record, autonomous_policy())
    assert (
        admit_training(
            record,
            TrainingPolicy(allowed_actors=(student(),), allowed_assistance=(assistance,)),
        )
        == record
    )


@pytest.mark.parametrize("kind", [ActorKind.HUMAN_TEACHER, ActorKind.LLM_TEACHER])
def test_known_teacher_requires_explicit_demonstration(kind):
    teacher = Actor(kind=kind, actor_id="teacher-1", policy_revision="v1")
    with pytest.raises(ValidationError, match="demonstration assistance"):
        transition(actor=teacher)


def test_unknown_actor_or_assistance_cannot_be_authorized():
    unknown = Actor(kind=ActorKind.UNKNOWN)
    archived = transition(actor=unknown, assistance=(AssistanceKind.UNKNOWN,))
    with pytest.raises(ValueError, match="actor or policy revision"):
        admit_training(archived, autonomous_policy())
    with pytest.raises(ValidationError, match="unknown actors"):
        TrainingPolicy(allowed_actors=(unknown,))
    with pytest.raises(ValidationError, match="unknown assistance"):
        TrainingPolicy(allowed_actors=(student(),), allowed_assistance=(AssistanceKind.UNKNOWN,))


@pytest.mark.parametrize(
    "actor",
    [
        {"kind": "student"},
        {"kind": "student", "actor_id": "student-1", "policy_revision": " "},
        {"kind": "unknown", "actor_id": "pretend-known"},
        {"kind": "unknown", "policy_revision": "v1"},
    ],
)
def test_actor_identity_cannot_be_incomplete_or_claimed_when_unknown(actor):
    with pytest.raises(ValidationError):
        Actor.model_validate(actor)


@pytest.mark.parametrize(
    "field,value",
    [
        ("run_id", uuid4()),
        ("episode_id", uuid4()),
        ("partition", DatasetPartition.FINAL),
        ("environment_instance_id", uuid4()),
        ("environment_revision", "switchlab-c0-v2"),
        ("action_schema_revision", "actions-permuted-v1"),
    ],
)
def test_transition_cannot_cross_episode_context(field, value):
    raw = transition().model_dump()
    raw["next_observation"]["context"][field] = value
    with pytest.raises(ValidationError, match="cannot cross"):
        ExperienceTransition.model_validate(raw)


@pytest.mark.parametrize(
    "field", ["environment_instance_id", "environment_revision", "action_schema_revision"]
)
def test_unknown_environment_metadata_is_archivable_but_not_trainable(field):
    archived = transition(context=episode(**{field: None}))
    with pytest.raises(ValueError, match="known environment and action versions"):
        admit_training(archived, autonomous_policy())


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("action_result", "request_id", uuid4()),
        ("action_result", "action", 2),
        ("action_result", "observation_id", uuid4()),
        ("action_result", "status", ActionStatus.REJECTED),
        ("action_result", "status", ActionStatus.FAILED),
        ("action_request", "step", 1),
        ("action_result", "step", 1),
        ("next_observation", "step", 2),
    ],
)
def test_request_result_and_observation_links_must_agree(part, field, value):
    raw = transition().model_dump()
    raw[part][field] = value
    with pytest.raises(ValidationError):
        ExperienceTransition.model_validate(raw)


def test_records_cannot_share_an_identity():
    raw = transition().model_dump()
    raw["action_request"]["id"] = raw["observation"]["id"]
    raw["action_result"]["request_id"] = raw["observation"]["id"]
    with pytest.raises(ValidationError, match="distinct IDs"):
        ExperienceTransition.model_validate(raw)


def test_replay_entry_revalidates_nested_model_copy_sensor_bypass():
    valid = transition()
    bad_payload = valid.observation.payload.model_copy(update={"visible_mask": (False,) * 8})
    bad_observation = valid.observation.model_copy(update={"payload": bad_payload})
    tampered = valid.model_copy(update={"observation": bad_observation})
    with pytest.raises(ValidationError, match="placeholder"):
        admit_training(tampered, autonomous_policy())


def test_replay_entry_revalidates_copied_request_and_policy():
    valid = transition()
    tampered = valid.model_copy(
        update={"action_request": valid.action_request.model_copy(update={"action": 1})}
    )
    with pytest.raises(ValidationError, match="match its action request"):
        admit_training(tampered, autonomous_policy())
    forged_policy = autonomous_policy().model_copy(
        update={"allowed_actors": (Actor(kind=ActorKind.UNKNOWN),)}
    )
    with pytest.raises(ValidationError, match="unknown actors"):
        admit_training(valid, forged_policy)


def test_timestamp_rules_allow_wall_clock_adjustment_but_reject_negative_duration():
    raw = transition().action_result.model_dump()
    raw["completed_at"] = raw["submitted_at"] - timedelta(minutes=1)
    assert ActionResultV2.model_validate(raw).elapsed_ns == 10
    raw["elapsed_ns"] = -1
    with pytest.raises(ValidationError):
        ActionResultV2.model_validate(raw)
    raw["elapsed_ns"] = 0
    raw["submitted_at"] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="explicit timezone"):
        ActionResultV2.model_validate(raw)


@pytest.mark.parametrize(
    "part,field",
    [
        ("observation", "created_at"),
        ("action_request", "created_at"),
        ("action_result", "created_at"),
        ("action_result", "submitted_at"),
        ("action_result", "completed_at"),
    ],
)
def test_all_record_and_execution_timestamps_require_explicit_timezone(part, field):
    record = getattr(transition(), part)
    raw = record.model_dump()
    raw[field] = datetime(2026, 1, 1)
    with pytest.raises(ValidationError, match="explicit timezone"):
        type(record).model_validate(raw)


def test_v2_schema_and_payload_stay_strict():
    raw = transition().observation.model_dump()
    raw["schema_version"] = True
    with pytest.raises(ValidationError):
        ObservationV2.model_validate(raw)
    raw["schema_version"] = 2
    raw["payload"]["hidden_rule"] = "XOR"
    with pytest.raises(ValidationError):
        ObservationV2.model_validate(raw)
    raw["payload"].pop("hidden_rule")
    raw["created_at"] = datetime(2026, 1, 1, 10, tzinfo=timezone(timedelta(hours=2)))
    assert ObservationV2.model_validate(raw).created_at.hour == 8
