"""Independent S02 CPU acceptance audit; failed criteria are kept as real failures.

No expected-failure markers and no changes to S01. The tests distinguish strict
schema/round-trip success from trust-boundary, temporal and revision defects.
"""

import hashlib
import json
import subprocess
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ainerzero.core.contracts import SymbolObservation
from ainerzero.core.experience import DatasetPartition, EpisodeIdentity, ObservationV2, OriginKind
from ainerzero.core.spacetime import (
    C0CellRef,
    ClockDomain,
    EvidenceKind,
    EvidenceLink,
    TimeIndex,
    TimeOrder,
    cell_ref_from_observation,
    compare_time,
    links_visible_at,
    load_cell_ref,
    load_evidence_link,
    observation_digest,
    record_digest,
    resolve_link,
    resolved_links_visible_at,
    to_canonical_json,
    verify_cell_ref,
)


def _context(**updates):
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


def _observation(context, step, **updates):
    return ObservationV2(
        **{
            "context": context,
            "step": step,
            "origin": OriginKind.OBSERVED,
            "payload": SymbolObservation(
                symbols=(65,) * 8,
                visible_mask=(True,) * 8,
                cursor=0,
                episode_start=step == 0,
            ),
            **updates,
        }
    )


def _time(context=None, step=0, **updates):
    context = context or _context()
    return TimeIndex(
        **{
            "run_id": context.run_id,
            "world_id": context.environment_instance_id,
            "episode_id": context.episode_id,
            "partition": context.partition,
            "step": step,
            "available_at_step": step,
            **updates,
        }
    )


def _link(subject, support, **updates):
    return EvidenceLink(
        **{
            "kind": EvidenceKind.SAME_CELL_LATER,
            "subject": subject,
            "supports": (support,),
            "asserted_by": "S02-auditor",
            "asserted_at_step": max(subject.time.available_at_step, support.time.available_at_step),
            **updates,
        }
    )


def _pair():
    context = _context()
    return (
        cell_ref_from_observation(_observation(context, 0), 0),
        cell_ref_from_observation(_observation(context, 1), 0),
    )


def test_canonical_digest_uses_observation_json_not_transport_file_bytes():
    observation = _observation(_context(), 0)
    canonical = json.dumps(
        observation.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert observation_digest(observation) == hashlib.sha256(canonical).hexdigest()
    transport = json.dumps({"observation": observation.model_dump(mode="json")}).encode() + b"\n"
    assert observation_digest(observation) != hashlib.sha256(transport).hexdigest()


def test_roundtrip_reordered_json_preserves_cell_and_link_digest():
    subject, support = _pair()
    link = _link(subject, support)
    for record, loader in ((subject, load_cell_ref), (link, load_evidence_link)):
        data = record.model_dump(mode="json")
        reordered = json.dumps(dict(reversed(list(data.items()))), indent=2)
        recovered = loader(reordered)
        assert record_digest(recovered) == record_digest(record)
        assert to_canonical_json(recovered) == to_canonical_json(record)


@pytest.mark.parametrize("origin", [OriginKind.TEACHER_CLAIM, OriginKind.IMAGINED,
                                   OriginKind.EXTERNAL_DERIVED, OriginKind.UNKNOWN])
def test_non_observed_origins_are_rejected_in_observed_link_view(origin):
    context = _context()
    before = cell_ref_from_observation(_observation(context, 0), 0)
    after = cell_ref_from_observation(_observation(context, 1, origin=origin), 0)
    with pytest.raises(ValidationError):
        _link(before, after)


@pytest.mark.parametrize("field", ["run_id", "episode_id", "world_id", "partition"])
def test_link_rejects_mixed_scope(field):
    before, after = _pair()
    data = after.model_dump(mode="python")
    time = data["time"]
    time[field] = DatasetPartition.DEVELOPMENT if field == "partition" else uuid4()
    modified = C0CellRef.model_validate(data)
    with pytest.raises(ValidationError):
        _link(before, modified)


@pytest.mark.parametrize("field", ["observation_id", "observation_sha256", "origin",
                                   "run_id", "episode_id", "world_id", "partition", "step"])
def test_reference_resolution_rejects_valid_schema_but_wrong_identity(field):
    observation = _observation(_context(), 1)
    ref = cell_ref_from_observation(observation, 0)
    data = ref.model_dump(mode="python")
    if field == "observation_id":
        data[field] = uuid4()
    elif field == "observation_sha256":
        data[field] = "0" * 64
    elif field == "origin":
        data[field] = OriginKind.IMAGINED
    else:
        data["time"][field] = {
            "partition": DatasetPartition.FINAL,
            "step": 0,
        }.get(field, uuid4())
    modified = C0CellRef.model_validate(data)
    with pytest.raises(ValueError):
        verify_cell_ref(modified, observation)


def test_valid_observed_origin_does_not_invent_student_actor_identity():
    # ObservationV2 deliberately has no actor field. A teacher taking the next
    # action must not relabel this observation as a teacher claim.
    observation = _observation(_context(), 0)
    ref = cell_ref_from_observation(observation, 0)
    assert ref.origin is OriginKind.OBSERVED
    assert "actor" not in ObservationV2.model_fields
    assert "actor" not in C0CellRef.model_fields
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**ref.model_dump(mode="python"), "actor": "student"})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_invalid_seconds_are_rejected(value):
    with pytest.raises(ValidationError):
        _time(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="sensor-A", event_time_s=value)


def test_cross_clock_domain_and_clock_identity_are_not_comparable():
    context = _context()
    a = _time(context, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="boot-A", event_time_s=1.0)
    b = _time(context, 1, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="boot-B", event_time_s=2.0)
    c = _time(context, 1, clock_domain=ClockDomain.WALL_UTC,
              clock_id="boot-A", event_time_s=2.0)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE
    assert compare_time(a, c) is TimeOrder.NOT_COMPARABLE


def test_touching_uncertainty_intervals_are_not_comparable():
    context = _context()
    a = _time(context, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="sensor-A", event_time_s=1.0, time_error_s=0.25)
    b = _time(context, 1, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="sensor-A", event_time_s=1.5, time_error_s=0.25)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


def test_equal_centres_with_nonzero_uncertainty_are_not_known_same_event():
    context = _context()
    a = _time(context, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="sensor-A", event_time_s=1.0, time_error_s=0.25)
    b = _time(context, 1, clock_domain=ClockDomain.SENSOR_MONOTONIC,
              clock_id="sensor-A", event_time_s=1.0, time_error_s=0.25)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


def test_unknown_world_is_not_evidence_of_same_world():
    context = _context(environment_instance_id=None)
    assert compare_time(_time(context, 0), _time(context, 1)) is TimeOrder.NOT_COMPARABLE


def test_compare_time_does_not_cross_dataset_partition():
    context = _context()
    a = _time(context, 0)
    b = _time(context, 1, partition=DatasetPartition.DEVELOPMENT)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


@pytest.mark.parametrize("violation", ["other_cell", "earlier", "same_instant"])
def test_same_cell_later_checks_the_named_relation(violation):
    context = _context()
    subject = cell_ref_from_observation(_observation(context, 1), 0)
    support = cell_ref_from_observation(
        _observation(context, {"other_cell": 2, "earlier": 0, "same_instant": 1}[violation]),
        1 if violation == "other_cell" else 0,
    )
    with pytest.raises(ValidationError):
        _link(subject, support)


@pytest.mark.parametrize("violation", ["cell", "coordinate_kind", "physical_xyz"])
def test_verify_cell_ref_revalidates_copied_instance_at_consumer_boundary(violation):
    observation = _observation(_context(), 0)
    ref = cell_ref_from_observation(observation, 0)
    copied = ref.model_copy(update={violation: {
        "cell": 8, "coordinate_kind": "world_xyz", "physical_xyz": (1.0, 2.0, 3.0),
    }[violation]})
    with pytest.raises(ValueError):
        verify_cell_ref(copied, observation)


def test_reference_constructor_revalidates_copied_observation_payload():
    observation = _observation(_context(), 0)
    invalid_payload = observation.payload.model_copy(update={"symbols": (999,) * 8})
    copied = observation.model_copy(update={"payload": invalid_payload})
    with pytest.raises(ValueError):
        cell_ref_from_observation(copied, 0)


def test_as_of_query_revalidates_copied_link_and_prevents_future_evidence_leak():
    before, after = _pair()
    copied = _link(before, after).model_copy(update={"asserted_at_step": 0})
    with pytest.raises(ValueError):
        links_visible_at((copied,), 0)


def test_as_of_query_refuses_revision_without_resolvable_predecessor():
    before, after = _pair()
    orphan = _link(before, after, revision=7, supersedes_sha256="0" * 64)
    decoded = load_evidence_link(to_canonical_json(orphan))
    with pytest.raises(ValueError):
        links_visible_at((decoded,), 1)


def test_as_of_query_refuses_retroactive_revision_chain():
    before, after = _pair()
    original = _link(before, after, asserted_at_step=4)
    retroactive = _link(before, after, asserted_at_step=1, revision=1,
                        supersedes_sha256=record_digest(original))
    with pytest.raises(ValueError):
        links_visible_at((original, retroactive), 2)


def test_link_schema_is_not_a_resolved_observation_evidence_boundary():
    # A normal JSON load may stay schema-only; it must not be advertised as
    # resolving evidence. This passing test documents that distinction.
    context = _context()
    observation = _observation(context, 0)
    support_observation = _observation(context, 1)
    ref = cell_ref_from_observation(observation, 0)
    support = cell_ref_from_observation(support_observation, 0)
    data = ref.model_dump(mode="python")
    data["observation_id"] = uuid4()
    forged = C0CellRef.model_validate(data)
    # Two distinct refs preserve the schema-only criterion without self-support.
    link = _link(forged, support, kind=EvidenceKind.CO_OCCURRENCE)
    assert load_evidence_link(to_canonical_json(link)) == link
    with pytest.raises(ValueError):
        verify_cell_ref(forged, observation)
    with pytest.raises(ValueError, match="unresolved observation"):
        resolve_link(link, {o.id: o for o in (observation, support_observation)})


def test_resolver_verifies_real_public_refs_without_mutating_inputs():
    context = _context()
    observations = [_observation(context, step) for step in range(3)]
    subject, support, later = [cell_ref_from_observation(o, 0) for o in observations]
    original = _link(subject, support, asserted_at_step=1)
    revision = _link(subject, later, asserted_at_step=3, revision=1,
                     supersedes_sha256=record_digest(original))
    mapping = {o.id: o for o in observations}
    snapshots = [to_canonical_json(link) for link in (original, revision)]
    assert resolve_link(original, mapping) == original
    assert resolved_links_visible_at((original, revision), 2, mapping) == (original,)
    assert resolved_links_visible_at((original, revision), 3, mapping) == (original, revision)
    assert snapshots == [to_canonical_json(link) for link in (original, revision)]
    assert tuple(mapping.values()) == tuple(observations)


@pytest.mark.parametrize("side", ["subject", "support"])
@pytest.mark.parametrize("violation", ["missing", "wrong_mapping_id", "digest", "origin"])
def test_resolver_rejects_unresolved_or_mismatched_public_observation(side, violation):
    context = _context()
    observations = [_observation(context, step) for step in (0, 1)]
    refs = [cell_ref_from_observation(o, 0) for o in observations]
    position = 0 if side == "subject" else 1
    expected_observation = observations[position]
    mapping = {o.id: o for o in observations}
    if violation == "missing":
        del mapping[expected_observation.id]
    elif violation == "wrong_mapping_id":
        mapping[expected_observation.id] = _observation(context, position)
    elif violation == "digest":
        raw = refs[position].model_dump(mode="python")
        raw["observation_sha256"] = "0" * 64
        refs[position] = C0CellRef.model_validate(raw)
    else:
        mapping[expected_observation.id] = ObservationV2.model_validate({
            **expected_observation.model_dump(mode="python"),
            "origin": OriginKind.IMAGINED,
        })
    link = _link(*refs)
    with pytest.raises((ValueError, ValidationError)):
        resolve_link(link, mapping)
    with pytest.raises((ValueError, ValidationError)):
        resolved_links_visible_at((link,), 5, mapping)


def test_import_and_contract_probe_are_cpu_only():
    code = (
        "import sys; import ainerzero.core.spacetime; "
        "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
