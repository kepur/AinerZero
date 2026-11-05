from datetime import datetime, timedelta, timezone
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
    TrainingTransition,
    require_training_source,
)


def sensor(**overrides):
    return SymbolObservation.model_validate(
        {
            "symbols": [65] * 8,
            "visible_mask": [True] * 8,
            "cursor": 0,
            "episode_start": True,
            **overrides,
        }
    )


def transition(source=SourceKind.OBSERVED):
    run_id, episode_id = uuid4(), uuid4()
    common = {"run_id": run_id, "episode_id": episode_id, "source_kind": source}
    before = Observation(**common, step=0, payload=sensor())
    after = Observation(**common, step=1, payload=sensor(episode_start=False))
    result = ActionResult(
        **common,
        request_id=uuid4(),
        step=0,
        action=3,
        status=ActionStatus.ACCEPTED,
        observation_id=after.id,
        submitted_at=before.created_at,
        completed_at=after.created_at,
        submitted_monotonic_ns=10,
        completed_monotonic_ns=20,
    )
    return {"observation": before, "action_result": result, "next_observation": after}


@pytest.mark.parametrize("value", [-1, 256, True, "65", 2.5, float("nan"), float("inf")])
def test_symbols_must_be_actual_bytes(value):
    with pytest.raises(ValidationError):
        sensor(symbols=[value] + [65] * 7)


@pytest.mark.parametrize(
    "overrides",
    [
        {"symbols": [65] * 7},
        {"symbols": [65] * 9},
        {"visible_mask": [True] * 7},
        {"visible_mask": [1] * 8},
        {"cursor": 8},
        {"cursor": -1},
        {"cursor": True},
        {"episode_start": 1},
        {"visible_mask": [False] + [True] * 7},
    ],
)
def test_sensor_shape_and_hidden_value_contract(overrides):
    with pytest.raises(ValidationError):
        sensor(**overrides)


def test_hidden_placeholder_does_not_make_visible_zero_invalid():
    payload = sensor(symbols=[0] * 8, visible_mask=[False] + [True] * 7)
    assert payload.symbols[0] == payload.symbols[1] == 0
    assert payload.visible_mask[0] is False
    assert payload.visible_mask[1] is True


@pytest.mark.parametrize(
    "hidden_field",
    ["hidden_values", "roles", "wiring", "gate_types", "delays", "eval_seed", "info"],
)
def test_sensor_rejects_private_environment_fields(hidden_field):
    with pytest.raises(ValidationError):
        sensor(**{hidden_field: [1, 2, 3]})


@pytest.mark.parametrize("source", [SourceKind.OBSERVED, SourceKind.TEACHER_DEMO])
def test_training_accepts_only_consistent_real_experience(source):
    sample = TrainingTransition(**transition(source))
    encoded = sample.model_dump_json()
    assert TrainingTransition.model_validate_json(encoded) == sample


@pytest.mark.parametrize(
    "source", [SourceKind.IMAGINED, SourceKind.TEACHER_CLAIM, SourceKind.EVAL_ONLY]
)
def test_training_rejects_each_non_evidence_source(source):
    with pytest.raises(ValidationError, match="not permitted for training"):
        TrainingTransition(**transition(source))
    record = RecordBase(run_id=uuid4(), source_kind=source)
    with pytest.raises(ValueError, match="not permitted for training"):
        require_training_source(record)


@pytest.mark.parametrize("part", ["observation", "action_result", "next_observation"])
def test_eval_source_cannot_be_hidden_in_one_part_of_a_transition(part):
    raw = {key: value.model_dump() for key, value in transition().items()}
    raw[part]["source_kind"] = SourceKind.EVAL_ONLY
    with pytest.raises(ValidationError, match="not permitted for training"):
        TrainingTransition.model_validate(raw)


@pytest.mark.parametrize(
    "part,field,value",
    [
        ("next_observation", "run_id", uuid4()),
        ("next_observation", "episode_id", uuid4()),
        ("next_observation", "step", 2),
        ("action_result", "step", 1),
        ("action_result", "observation_id", uuid4()),
        ("action_result", "status", ActionStatus.REJECTED),
        ("action_result", "source_kind", SourceKind.TEACHER_DEMO),
    ],
)
def test_training_rejects_broken_evidence_links(part, field, value):
    raw = {key: item.model_dump() for key, item in transition().items()}
    raw[part][field] = value
    with pytest.raises(ValidationError):
        TrainingTransition.model_validate(raw)


def test_training_has_no_hidden_target_or_arbitrary_labels_field():
    with pytest.raises(ValidationError):
        TrainingTransition(**transition(), hidden_labels=[1] * 8)


def test_unique_ids_and_utc_normalization():
    common = {"run_id": uuid4(), "source_kind": SourceKind.OBSERVED}
    first, second = RecordBase(**common), RecordBase(**common)
    assert first.id != second.id
    assert first.created_at.utcoffset() == timedelta(0)
    other_zone = datetime(2026, 1, 1, 10, tzinfo=timezone(timedelta(hours=2)))
    record = RecordBase(**common, created_at=other_zone)
    assert record.created_at.hour == 8
    assert record.created_at.tzinfo is timezone.utc
    with pytest.raises(ValidationError, match="explicit timezone"):
        RecordBase(**common, created_at=datetime(2026, 1, 1))


def test_monotonic_clock_checks_order_despite_wall_clock_adjustment():
    raw = transition()["action_result"].model_dump()
    raw["completed_at"] = raw["submitted_at"] - timedelta(minutes=1)
    assert ActionResult.model_validate(raw).completed_monotonic_ns == 20
    raw["completed_monotonic_ns"] = 9
    with pytest.raises(ValidationError, match="monotonic clock"):
        ActionResult.model_validate(raw)


@pytest.mark.parametrize("action", [-1, 4, True, "1", 1.5])
def test_only_four_integer_actions_are_accepted(action):
    with pytest.raises(ValidationError):
        ActionRequest(
            run_id=uuid4(), episode_id=uuid4(), source_kind="observed", step=0, action=action
        )


def test_episode_start_and_observation_step_are_consistent():
    with pytest.raises(ValidationError, match="episode_start"):
        Observation(
            run_id=uuid4(), episode_id=uuid4(), source_kind="observed", step=1, payload=sensor()
        )


def test_preconstructed_sensor_cannot_bypass_hidden_value_validation():
    invalid = sensor().model_copy(update={"visible_mask": (False,) * 8})
    with pytest.raises(ValidationError, match="placeholder"):
        Observation(
            run_id=uuid4(), episode_id=uuid4(), source_kind="observed", step=0, payload=invalid
        )


def test_record_schema_version_does_not_accept_boolean():
    with pytest.raises(ValidationError):
        RecordBase(run_id=uuid4(), source_kind="observed", schema_version=True)
