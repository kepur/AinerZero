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
    to_canonical_json,
    verify_cell_ref,
)


def ctx(partition=DatasetPartition.TRAIN):
    return EpisodeIdentity(
        run_id=uuid4(), episode_id=uuid4(), partition=partition,
        environment_instance_id=uuid4(), environment_revision="switchlab-c0-v1",
        action_schema_revision="switchlab-actions-v1",
    )


def obs(context, step, origin=OriginKind.OBSERVED, symbol=65):
    return ObservationV2(
        context=context, step=step, origin=origin,
        payload=SymbolObservation(symbols=(symbol,) * 8, visible_mask=(True,) * 8,
                                  cursor=0, episode_start=step == 0),
    )


def tindex(**kw):
    base = dict(run_id=uuid4(), world_id=uuid4(), episode_id=uuid4(),
                partition=DatasetPartition.TRAIN, step=0, available_at_step=0)
    return TimeIndex(**{**base, **kw})


def test_cell_ref_matches_observation_and_roundtrips():
    o = obs(ctx(), 3)
    ref = cell_ref_from_observation(o, 5)
    verify_cell_ref(ref, o)
    assert ref.physical_xyz is None and ref.coordinate_kind == "symbol_slot"
    again = load_cell_ref(to_canonical_json(ref))
    assert again == ref and record_digest(again) == record_digest(ref)


def test_original_observation_is_unchanged():
    o = obs(ctx(), 1)
    before = o.model_dump_json()
    cell_ref_from_observation(o, 0)
    assert o.model_dump_json() == before


@pytest.mark.parametrize("field", ["symbol", "step", "origin", "episode"])
def test_mismatched_observation_rejected(field):
    c = ctx()
    o = obs(c, 2)
    ref = cell_ref_from_observation(o, 1)
    other = {
        "symbol": o.model_copy(update={"payload": obs(c, 2, symbol=66).payload}),
        "step": obs(c, 3).model_copy(update={"id": o.id}),
        "origin": o.model_copy(update={"origin": OriginKind.TEACHER_CLAIM}),
        "episode": obs(ctx(), 2).model_copy(update={"id": o.id}),
    }[field]
    with pytest.raises(ValueError):
        verify_cell_ref(ref, other)


def test_cell_cannot_claim_xyz_or_bad_index():
    ref = cell_ref_from_observation(obs(ctx(), 0), 0)
    data = ref.model_dump(mode="json")
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**data, "physical_xyz": [0, 0, 0]})
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**data, "cell": 8})
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**data, "coordinate_kind": "world_xyz"})
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**data, "extra": 1})


def test_event_steps_carry_no_seconds_and_availability_not_before_step():
    with pytest.raises(ValidationError):
        tindex(event_time_s=1.0)
    with pytest.raises(ValidationError):
        tindex(step=4, available_at_step=3)
    with pytest.raises(ValidationError):
        tindex(clock_domain=ClockDomain.WALL_UTC, event_time_s=1.0)  # no clock_id


def test_cross_clock_and_cross_episode_not_comparable():
    a = tindex(step=1, available_at_step=1)
    b = a.model_copy(update={"step": 2, "available_at_step": 2})
    assert compare_time(a, b) is TimeOrder.BEFORE
    assert compare_time(b, a) is TimeOrder.AFTER
    assert compare_time(a, a) is TimeOrder.SAME
    assert compare_time(a, tindex(step=2, available_at_step=2)) is TimeOrder.NOT_COMPARABLE
    unknown = a.model_copy(update={"world_id": None})
    assert compare_time(unknown, unknown) is TimeOrder.NOT_COMPARABLE
    s1 = a.model_copy(update={"clock_domain": ClockDomain.SENSOR_MONOTONIC, "clock_id": "c1", "event_time_s": 1.0})
    s2 = s1.model_copy(update={"clock_id": "c2", "event_time_s": 2.0})
    assert compare_time(s1, s2) is TimeOrder.NOT_COMPARABLE
    assert compare_time(a, s1) is TimeOrder.NOT_COMPARABLE
    e1 = s1.model_copy(update={"time_error_s": 0.6})
    e2 = s1.model_copy(update={"event_time_s": 2.0, "time_error_s": 0.6})
    assert compare_time(e1, e2) is TimeOrder.NOT_COMPARABLE


def make_link(o_subject, o_support, asserted_at_step, **kw):
    return EvidenceLink(kind=EvidenceKind.SAME_CELL_LATER,
                        subject=cell_ref_from_observation(o_subject, 0),
                        supports=(cell_ref_from_observation(o_support, 0),),
                        asserted_by="test", asserted_at_step=asserted_at_step, **kw)


def test_link_roundtrip_and_never_verified_causal():
    c = ctx()
    link = make_link(obs(c, 0), obs(c, 1), 1)
    assert load_evidence_link(to_canonical_json(link)) == link
    with pytest.raises(ValidationError):
        EvidenceLink.model_validate({**link.model_dump(mode="json"), "verified_causal": True})


def test_link_rejects_future_evidence_and_supports_as_of_query():
    c = ctx()
    with pytest.raises(ValidationError):
        make_link(obs(c, 0), obs(c, 5), 2)
    s0 = obs(c, 0)
    v0 = make_link(s0, obs(c, 1), 1)
    v1 = make_link(s0, obs(c, 4), 4, revision=1, supersedes_sha256=record_digest(v0))
    assert links_visible_at((v0, v1), 2) == (v0,)
    assert links_visible_at((v0, v1), 4) == (v0, v1)
    with pytest.raises(ValidationError):
        make_link(obs(c, 0), obs(c, 1), 1, revision=1)


def test_link_rejects_cross_episode_partition_and_non_observed():
    with pytest.raises(ValidationError):
        make_link(obs(ctx(), 0), obs(ctx(), 1), 1)
    c = ctx()
    with pytest.raises(ValidationError):
        make_link(obs(c, 0), obs(c, 1, origin=OriginKind.IMAGINED), 1)
    d = c.model_copy(update={"partition": DatasetPartition.FINAL})
    with pytest.raises(ValidationError):
        make_link(obs(c, 0), obs(d, 1), 1)


def test_digest_is_stable_canonical():
    o = obs(ctx(), 0)
    assert observation_digest(o) == observation_digest(ObservationV2.model_validate_json(o.model_dump_json()))


def test_module_imports_without_mlx():
    code = "import sys, ainerzero.core.spacetime; assert 'mlx' not in sys.modules and 'mlx.core' not in sys.modules"
    subprocess.run([sys.executable, "-c", code], check=True)


# ---- S01-R1 additions ----
from ainerzero.core.spacetime import (  # noqa: E402
    resolve_link,
    resolved_links_visible_at,
    validate_link_history,
)


def chain():
    c = ctx()
    s0, a, b = obs(c, 0), obs(c, 1), obs(c, 3)
    v0 = make_link(s0, a, 1)
    v1 = make_link(s0, b, 3, revision=1, supersedes_sha256=record_digest(v0))
    return c, s0, a, b, v0, v1


def test_valid_history_and_future_revision_hidden_until_available():
    *_, v0, v1 = chain()
    assert validate_link_history((v0, v1)) == (v0, v1)
    assert links_visible_at((v0, v1), 2) == (v0,)
    assert links_visible_at((v0, v1), 9) == (v0, v1)


def test_history_rejects_missing_skip_fork_kind_subject_and_backdating():
    c, s0, a, b, v0, v1 = chain()
    d0 = record_digest(v0)
    bad = {
        "missing": (v1,),
        "skip": (v0, make_link(s0, b, 3, revision=2, supersedes_sha256=d0)),
        "fork": (v0, v1, make_link(s0, obs(c, 2), 2, revision=1, supersedes_sha256=d0)),
        "subject": (v0, make_link(obs(c, 0), b, 3, revision=1, supersedes_sha256=d0)),
        "duplicate": (v0, v0),
    }
    co = EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=v0.subject, supports=v0.supports,
                      asserted_by="test", asserted_at_step=3, revision=1, supersedes_sha256=d0)
    bad["kind"] = (v0, co)
    late0 = make_link(s0, a, 3)
    bad["backdated"] = (late0, make_link(s0, a, 1, revision=1, supersedes_sha256=record_digest(late0)))
    for name, links in bad.items():
        with pytest.raises(ValueError):
            validate_link_history(links)
        with pytest.raises(ValueError):
            links_visible_at(links, 10)


def test_same_cell_later_requires_same_cell_strictly_later_and_no_self_support():
    c = ctx()
    o0, o1 = obs(c, 0), obs(c, 1)
    with pytest.raises(ValidationError):
        EvidenceLink(kind=EvidenceKind.SAME_CELL_LATER, subject=cell_ref_from_observation(o0, 0),
                     supports=(cell_ref_from_observation(o1, 1),), asserted_by="t", asserted_at_step=1)
    for sup in (o0, obs(c, 0)):
        with pytest.raises(ValidationError):
            make_link(o1, sup, 1)
    r = cell_ref_from_observation(o0, 0)
    with pytest.raises(ValidationError):
        EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=r, supports=(r,), asserted_by="t", asserted_at_step=0)
    r1 = cell_ref_from_observation(o1, 0)
    with pytest.raises(ValidationError):
        EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=r, supports=(r1, r1), asserted_by="t", asserted_at_step=1)


def test_resolver_accepts_real_and_rejects_missing_forged_key_origin():
    c, s0, a, b, v0, v1 = chain()
    m = {o.id: o for o in (s0, a, b)}
    assert resolve_link(v0, m) == v0
    assert resolved_links_visible_at((v0, v1), 2, m) == (v0,)
    with pytest.raises(ValueError):
        resolve_link(v0, {s0.id: s0})
    with pytest.raises(ValueError):
        resolve_link(v0, {s0.id: s0, a.id: obs(c, 1)})  # key != observation.id
    with pytest.raises(ValueError):
        resolve_link(v0, {s0.id: s0, a.id: a.model_copy(update={"payload": obs(c, 1, symbol=66).payload})})
    with pytest.raises(ValueError):
        resolve_link(v0, {s0.id: s0, a.id: a.model_copy(update={"origin": OriginKind.IMAGINED})})


def test_consumers_revalidate_nested_copied_objects():
    c = ctx()
    o = obs(c, 1)
    bad_payload = o.model_copy(update={"payload": o.payload.model_copy(update={"symbols": (999,) * 8})})
    for fn in (observation_digest, lambda x: cell_ref_from_observation(x, 0)):
        with pytest.raises(ValueError):
            fn(bad_payload)
    ref = cell_ref_from_observation(o, 0)
    bad_time = ref.model_copy(update={"time": ref.time.model_copy(update={"available_at_step": 0, "step": 5})})
    for fn in (to_canonical_json, record_digest, lambda x: verify_cell_ref(x, o)):
        with pytest.raises(ValueError):
            fn(bad_time)
    with pytest.raises(ValueError):
        compare_time(bad_time.time, ref.time)
    link = make_link(obs(c, 0), obs(c, 4), 4)
    with pytest.raises(ValueError):
        links_visible_at((link.model_copy(update={"asserted_at_step": 0}),), 0)
    with pytest.raises(ValueError):
        links_visible_at((link,), -1)


def test_timed_clock_rules():
    a = tindex(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="c", event_time_s=2.0, time_error_s=0.5)
    assert compare_time(a, a) is TimeOrder.NOT_COMPARABLE  # same centre, nonzero error
    b = a.model_copy(update={"event_time_s": 3.0})
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE  # touching intervals
    z1 = a.model_copy(update={"time_error_s": None, "step": 1, "available_at_step": 1, "event_time_s": 5.0})
    z2 = z1.model_copy(update={"step": 2, "available_at_step": 2, "event_time_s": 1.0})
    assert compare_time(z1, z2) is TimeOrder.NOT_COMPARABLE  # step vs seconds contradiction
    z3 = z2.model_copy(update={"event_time_s": 6.0})
    assert compare_time(z1, z3) is TimeOrder.BEFORE
    w1 = z1.model_copy(update={"clock_domain": ClockDomain.WALL_UTC})
    w2 = z2.model_copy(update={"clock_domain": ClockDomain.WALL_UTC})
    assert compare_time(w1, w2) is TimeOrder.AFTER  # wall clock not assumed monotonic
    p = z3.model_copy(update={"partition": DatasetPartition.DEVELOPMENT})
    assert compare_time(z1, p) is TimeOrder.NOT_COMPARABLE


# ---- S01-R2 identity and direct-instance revalidation ----
@pytest.mark.parametrize("metadata", ["availability", "stream_seq", "both"])
def test_support_identity_cannot_be_duplicated_by_reference_metadata(metadata):
    c = ctx()
    subject = cell_ref_from_observation(obs(c, 0), 0)
    support = cell_ref_from_observation(obs(c, 1), 0)
    changes = {}
    if metadata in ("availability", "both"):
        changes["available_at_step"] = 2
    if metadata in ("stream_seq", "both"):
        changes["stream_seq"] = 1
    alias = support.model_copy(update={"time": support.time.model_copy(update=changes)})
    assert record_digest(support) != record_digest(alias)
    with pytest.raises(ValidationError, match="duplicate support references"):
        EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=subject,
                     supports=(support, alias), asserted_by="test", asserted_at_step=2)


@pytest.mark.parametrize("kind", list(EvidenceKind))
def test_subject_identity_cannot_support_itself_by_later_reference_metadata(kind):
    subject = cell_ref_from_observation(obs(ctx(), 1), 0)
    alias = subject.model_copy(update={"time": subject.time.model_copy(
        update={"stream_seq": 1, "available_at_step": 2})})
    assert compare_time(subject.time, alias.time) is TimeOrder.BEFORE
    assert record_digest(subject) != record_digest(alias)
    with pytest.raises(ValidationError, match="own subject"):
        EvidenceLink(kind=kind, subject=subject, supports=(alias,),
                     asserted_by="test", asserted_at_step=2)


def test_same_observation_different_cells_are_distinct_cooccurrence_evidence():
    o = obs(ctx(), 1)
    subject = cell_ref_from_observation(o, 0)
    supports = (cell_ref_from_observation(o, 1), cell_ref_from_observation(o, 2))
    link = EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=subject,
                        supports=supports, asserted_by="test", asserted_at_step=1)
    assert resolve_link(link, {o.id: o}) == link
    assert load_evidence_link(to_canonical_json(link)) == link
    assert resolved_links_visible_at((link,), 1, {o.id: o}) == (link,)


@pytest.mark.parametrize("location", ["observation", "payload", "context"])
def test_observation_consumers_reject_copied_undeclared_fields(location):
    o = obs(ctx(), 1)
    ref = cell_ref_from_observation(o, 0)
    if location == "observation":
        bad = o.model_copy(update={"undeclared": True})
    else:
        nested = getattr(o, location).model_copy(update={"undeclared": True})
        bad = o.model_copy(update={location: nested})
    for consume in (observation_digest, lambda value: cell_ref_from_observation(value, 0),
                    lambda value: verify_cell_ref(ref, value)):
        with pytest.raises(ValueError):
            consume(bad)


@pytest.mark.parametrize("location", ["reference", "time"])
def test_reference_consumers_reject_copied_undeclared_fields(location):
    o = obs(ctx(), 1)
    ref = cell_ref_from_observation(o, 0)
    if location == "reference":
        bad = ref.model_copy(update={"undeclared": True})
    else:
        bad = ref.model_copy(update={"time": ref.time.model_copy(update={"undeclared": True})})
    for consume in (to_canonical_json, record_digest, lambda value: verify_cell_ref(value, o)):
        with pytest.raises(ValueError):
            consume(bad)
    with pytest.raises(ValueError):
        EvidenceLink(kind=EvidenceKind.CO_OCCURRENCE, subject=bad,
                     supports=(cell_ref_from_observation(o, 1),), asserted_by="test", asserted_at_step=1)


@pytest.mark.parametrize("location", ["link", "subject", "support"])
def test_link_consumers_reject_copied_undeclared_fields(location):
    c = ctx()
    s0, s1 = obs(c, 0), obs(c, 1)
    link = make_link(s0, s1, 1)
    if location == "link":
        bad = link.model_copy(update={"undeclared": True})
    elif location == "subject":
        bad = link.model_copy(update={"subject": link.subject.model_copy(update={"undeclared": True})})
    else:
        bad = link.model_copy(update={"supports": (link.supports[0].model_copy(update={"undeclared": True}),)})
    for consume in (to_canonical_json, record_digest, validate_link_history,
                    lambda value: resolve_link(value, {s0.id: s0, s1.id: s1})):
        with pytest.raises(ValueError):
            consume((bad,) if consume is validate_link_history else bad)


def test_consumers_reject_incomplete_constructed_records_as_value_error():
    o = obs(ctx(), 1)
    ref = cell_ref_from_observation(o, 0)
    broken_time = TimeIndex.model_construct()
    broken_ref = C0CellRef.model_construct(time=ref.time, cell=0)
    broken_observation = ObservationV2.model_construct(payload=o.payload)
    broken_link = EvidenceLink.model_construct(kind=EvidenceKind.CO_OCCURRENCE, subject=ref)
    consumers = (
        lambda: compare_time(broken_time, ref.time),
        lambda: record_digest(broken_ref),
        lambda: observation_digest(broken_observation),
        lambda: links_visible_at((broken_link,), 1),
    )
    for consume in consumers:
        with pytest.raises(ValueError):
            consume()
