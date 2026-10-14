"""S02 adversarial contract audit and S02-R1 CPU acceptance of S01 repairs.

Original author: s02_spacetime_contract_audit; S02-R1 editor:
/root/c05_budget_reconciliation. The external audit read the internal audit's
findings and is not blind-independent. Original BUG IDs and failed evidence:
artifacts/reports/S02-s02_spacetime_contract_audit-20261012T104900+0300.md.
Repair policy: S01_REPAIR_PLAN.md. Fixed cases are ordinary acceptance tests;
the original failure/xfail logs remain intact, with no new xfail markers.
"""

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
    to_canonical_json,
    verify_cell_ref,
)


def _ctx(partition=DatasetPartition.TRAIN, world=True):
    return EpisodeIdentity(
        run_id=uuid4(), episode_id=uuid4(), partition=partition,
        environment_instance_id=uuid4() if world else None,
        environment_revision="switchlab-c0-v1", action_schema_revision="switchlab-actions-v1",
    )


def _obs(c, step, origin=OriginKind.OBSERVED, sym=65):
    return ObservationV2(
        context=c, step=step, origin=origin,
        payload=SymbolObservation(symbols=(sym,) * 8, visible_mask=(True,) * 8,
                                  cursor=0, episode_start=step == 0),
    )


def _t(**kw):
    base = dict(run_id=RUN, world_id=WORLD, episode_id=EP,
                partition=DatasetPartition.TRAIN, step=0, available_at_step=0)
    base.update(kw)
    if "step" in kw and "available_at_step" not in kw and isinstance(kw["step"], int) \
            and not isinstance(kw["step"], bool) and kw["step"] >= 0:
        base["available_at_step"] = kw["step"]
    return TimeIndex(**base)


RUN, WORLD, EP = uuid4(), uuid4(), uuid4()


def _link(subject, supports, kind=EvidenceKind.CO_OCCURRENCE, at=None, **kw):
    refs = (subject, *supports)
    at = max(r.time.available_at_step for r in refs) if at is None else at
    return EvidenceLink(kind=kind, subject=subject, supports=tuple(supports),
                        asserted_by="s02", asserted_at_step=at, **kw)


# ---------- references: world / episode / cell / time validity ----------

@pytest.mark.parametrize("cell", [-1, 8, 99, True, 1.0, "3"])
def test_cell_index_out_of_range_or_wrong_type_rejected(cell):
    o = _obs(_ctx(), 1)
    with pytest.raises(ValidationError):
        cell_ref_from_observation(o, cell)


@pytest.mark.parametrize("bad", [
    {"step": -1}, {"step": True}, {"available_at_step": -1},
    {"run_id": "not-a-uuid"}, {"episode_id": None}, {"partition": "secret"},
    {"schema_version": 2}, {"extra": 1},
])
def test_time_index_rejects_malformed_fields(bad):
    with pytest.raises(ValidationError):
        _t(**bad)


def test_json_tampering_of_ref_rejected():
    o = _obs(_ctx(), 2)
    d = json.loads(to_canonical_json(cell_ref_from_observation(o, 1)))
    for k, v in [("physical_xyz", [0, 0, 0]), ("coordinate_kind", "xyz"), ("cell", 8),
                 ("observation_sha256", "ABC"), ("kind", "pixel")]:
        bad = {**d, k: v}
        with pytest.raises(ValidationError):
            load_cell_ref(json.dumps(bad))


def test_verify_rejects_ref_pointed_at_other_cells_observation_world():
    c = _ctx()
    o = _obs(c, 3)
    other_world = c.model_copy(update={"environment_instance_id": uuid4()})
    o2 = ObservationV2.model_validate({**o.model_dump(), "context": other_world.model_dump()})
    ref = cell_ref_from_observation(o, 0)
    with pytest.raises(ValueError):
        verify_cell_ref(ref, o2)


def test_verify_rejects_legacy_none_world_vs_known_world():
    c = _ctx(world=False)
    o = _obs(c, 1)
    ref = cell_ref_from_observation(o, 0)
    verify_cell_ref(ref, o)
    forged = ref.model_copy(update={"time": ref.time.model_copy(update={"world_id": uuid4()})})
    with pytest.raises(ValueError):
        verify_cell_ref(forged, o)


def test_available_before_step_rejected_via_constructor():
    with pytest.raises(ValidationError):
        cell_ref_from_observation(_obs(_ctx(), 5), 0, available_at_step=4)


# ---------- cross-clock comparisons ----------

@pytest.mark.parametrize("a,b", [
    (dict(), dict(clock_domain=ClockDomain.WALL_UTC, clock_id="utc", event_time_s=0.0)),
    (dict(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="cam", event_time_s=1.0),
     dict(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="imu", event_time_s=2.0)),
    (dict(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="x", event_time_s=1.0),
     dict(clock_domain=ClockDomain.WALL_UTC, clock_id="x", event_time_s=2.0)),
    (dict(), dict(episode_id=uuid4(), step=1)),
    (dict(), dict(run_id=uuid4(), step=1)),
    (dict(), dict(world_id=uuid4(), step=1)),
])
def test_cross_scope_or_clock_is_not_comparable_both_directions(a, b):
    x, y = _t(**a), _t(**b)
    assert compare_time(x, y) is TimeOrder.NOT_COMPARABLE
    assert compare_time(y, x) is TimeOrder.NOT_COMPARABLE


def test_event_step_rejects_seconds_and_timed_requires_clock_id():
    with pytest.raises(ValidationError):
        _t(event_time_s=1.0)
    with pytest.raises(ValidationError):
        _t(clock_domain=ClockDomain.WALL_UTC)


def test_compare_is_antisymmetric_for_timed_clock():
    a = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u", event_time_s=1.0, time_error_s=0.1)
    b = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u", event_time_s=1.5, time_error_s=0.1, step=1,
           available_at_step=1)
    assert compare_time(a, b) is TimeOrder.BEFORE and compare_time(b, a) is TimeOrder.AFTER


def test_timed_clock_missing_time_not_comparable():
    a = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u")
    b = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u", event_time_s=3.0)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


# S02-B1: equal centres with nonzero error must remain incomparable.
def test_equal_centres_with_error_not_claimed_same():
    a = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u", event_time_s=2.0, time_error_s=0.5)
    b = _t(clock_domain=ClockDomain.WALL_UTC, clock_id="u", event_time_s=2.0, time_error_s=0.5, step=3,
           available_at_step=3)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


# S02-B2: partition is part of the comparison scope.
def test_compare_across_partition_not_comparable():
    a = _t()
    b = _t(partition=DatasetPartition.DEVELOPMENT, step=1, available_at_step=1)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


# S02-B3: monotonic-clock step/seconds conflict must remain incomparable.
def test_monotonic_clock_inconsistent_with_step_order_detected():
    a = _t(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="cam", step=1, available_at_step=1,
           event_time_s=5.0)
    b = _t(clock_domain=ClockDomain.SENSOR_MONOTONIC, clock_id="cam", step=2, available_at_step=2,
           event_time_s=1.0)
    assert compare_time(a, b) is TimeOrder.NOT_COMPARABLE


# ---------- evidence links: broken / provenance / partition ----------

def _refs(n=3, origin=OriginKind.OBSERVED, partition=DatasetPartition.TRAIN):
    c = _ctx(partition)
    return c, [cell_ref_from_observation(_obs(c, s, origin), 0) for s in range(n)]


def test_link_rejects_mixed_episode_partition_and_nonobserved():
    _, a = _refs()
    _, b = _refs()
    with pytest.raises(ValidationError):
        _link(a[0], [b[1]])
    _, d = _refs(partition=DatasetPartition.DEVELOPMENT)
    with pytest.raises(ValidationError):
        _link(a[0], [d[1]])
    for origin in (OriginKind.IMAGINED, OriginKind.TEACHER_CLAIM, OriginKind.EXTERNAL_DERIVED,
                   OriginKind.UNKNOWN):
        c, _ = _refs()
        bad = cell_ref_from_observation(_obs(c, 1, origin), 0)
        good = cell_ref_from_observation(_obs(c, 0), 0)
        with pytest.raises(ValidationError):
            _link(good, [bad])
        with pytest.raises(ValidationError):
            _link(bad, [good])


def test_link_rejects_empty_supports_and_verified_causal_and_bad_revision():
    _, r = _refs()
    with pytest.raises(ValidationError):
        EvidenceLink(kind="co_occurrence", subject=r[0], supports=(), asserted_by="x", asserted_at_step=0)
    with pytest.raises(ValidationError):
        _link(r[0], [r[1]], verified_causal=True)
    with pytest.raises(ValidationError):
        _link(r[0], [r[1]], revision=1)
    with pytest.raises(ValidationError):
        _link(r[0], [r[1]], supersedes_sha256="a" * 64)


def test_json_tampered_link_origin_flip_rejected():
    _, r = _refs()
    d = json.loads(to_canonical_json(_link(r[0], [r[1]])))
    d["supports"][0]["origin"] = "imagined"
    with pytest.raises(ValidationError):
        load_evidence_link(json.dumps(d))
    d = json.loads(to_canonical_json(_link(r[0], [r[1]])))
    d["supports"][0]["time"]["partition"] = "development"
    with pytest.raises(ValidationError):
        load_evidence_link(json.dumps(d))


# S02-B4: consumers must revalidate copied observations and references.
@pytest.mark.parametrize("which", ["obs_payload", "ref_cell", "ref_xyz"])
def test_consumers_revalidate_copied_instances(which):
    o = _obs(_ctx(), 1)
    ref = cell_ref_from_observation(o, 0)
    try:
        if which == "obs_payload":
            bad = o.model_copy(update={"payload": o.payload.model_copy(update={"symbols": (999,) * 8})})
            cell_ref_from_observation(bad, 0)
        else:
            upd = {"cell": 8} if which == "ref_cell" else {"physical_xyz": (1.0, 2.0, 3.0)}
            verify_cell_ref(ref.model_copy(update=upd), o)
    except (ValueError, ValidationError):
        return
    raise AssertionError("invalid copied instance accepted")


# S02-B5: same_cell_later requires the same cell and a strict later time.
@pytest.mark.parametrize("cell,step", [(1, 2), (0, 0), (0, 1)])
def test_same_cell_later_semantics_enforced(cell, step):
    c = _ctx()
    subj = cell_ref_from_observation(_obs(c, 1), 0)
    sup = cell_ref_from_observation(_obs(c, step), cell)
    with pytest.raises(ValidationError):
        _link(subj, [sup], kind=EvidenceKind.SAME_CELL_LATER)


# S02-B6: a subject cannot support itself.
def test_self_support_rejected():
    _, r = _refs()
    with pytest.raises(ValidationError):
        _link(r[0], [r[0]])


# S02-B7: schema loading stays separate from explicit public resolution.
def test_broken_reference_to_unknown_observation_is_rejected_at_query():
    c = _ctx()
    observations = [_obs(c, step) for step in (0, 1)]
    r = [cell_ref_from_observation(o, 0) for o in observations]
    ghost = r[1].model_validate({**r[1].model_dump(), "observation_id": uuid4(), "observation_sha256": "0" * 64})
    link = load_evidence_link(to_canonical_json(_link(r[0], [ghost])))
    with pytest.raises((ValueError, ValidationError), match="unresolved observation"):
        resolve_link(link, {o.id: o for o in observations})


# ---------- no write-back / leakage of future revisions ----------

def test_link_cannot_cite_evidence_available_later_than_assertion():
    c = _ctx()
    late = cell_ref_from_observation(_obs(c, 2), 0, available_at_step=9)
    early = cell_ref_from_observation(_obs(c, 1), 0)
    with pytest.raises(ValidationError):
        _link(early, [late], at=5)


def test_as_of_view_hides_later_revision_and_is_stable():
    _, r = _refs()
    v0 = _link(r[0], [r[1]], at=2)
    v1 = _link(r[0], [r[1], r[2]], at=6, revision=1, supersedes_sha256=record_digest(v0))
    before = to_canonical_json(v0)
    view = links_visible_at((v0, v1), 3)
    assert view == (v0,)
    assert to_canonical_json(v0) == before  # revision does not mutate v0
    with pytest.raises(ValidationError):
        v0.asserted_at_step = 99  # frozen


# S02-B8: malformed backdated copies must raise, not be silently hidden.
def test_back_dated_copy_does_not_leak_into_earlier_view():
    c = _ctx()
    late = cell_ref_from_observation(_obs(c, 4), 0)
    early = cell_ref_from_observation(_obs(c, 0), 0)
    link = _link(early, [late], at=4)
    backdated = link.model_copy(update={"asserted_at_step": 0})
    with pytest.raises((ValueError, ValidationError), match="not yet available"):
        links_visible_at((backdated,), 1)


# S02-B9: retroactive revision chains must raise before as-of filtering.
def test_revision_cannot_predate_its_predecessor():
    _, r = _refs()
    v0 = _link(r[0], [r[1]], at=5)
    v1 = _link(r[0], [r[1]], at=1, revision=1, supersedes_sha256=record_digest(v0))
    with pytest.raises((ValueError, ValidationError), match="before its predecessor"):
        links_visible_at((v0, v1), 2)


# ---------- serialization / independence ----------

def test_digest_canonical_and_roundtrip_stable():
    _, r = _refs()
    link = _link(r[0], [r[1], r[2]])
    again = load_evidence_link(to_canonical_json(link))
    assert again == link and record_digest(again) == record_digest(link)
    shuffled = json.dumps(dict(reversed(list(json.loads(to_canonical_json(link)).items()))))
    assert record_digest(load_evidence_link(shuffled)) == record_digest(link)


def test_module_imports_without_mlx():
    code = ("import sys\nsys.modules['mlx']=None\nimport ainerzero.core.spacetime as s\n"
            "assert not any(m=='mlx' or m.startswith('mlx.') for m in sys.modules if sys.modules[m] is not None)\n"
            "print('ok')")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "ok"


def test_c0_ref_has_no_physical_coordinates_by_construction():
    _, r = _refs()
    assert r[0].physical_xyz is None and r[0].coordinate_kind == "symbol_slot"
    with pytest.raises(ValidationError):
        C0CellRef.model_validate({**r[0].model_dump(), "physical_xyz": (1.0, 2.0, 3.0)})


# S01-R2 acceptance added after the R1-aligned XML was saved. The coordinator
# fixed ref identity to (observation_id, cell), with digests still checked
# separately. These were real residual failures, never expected failures.

def test_r2_duplicate_support_alias_cannot_change_availability_to_count_twice():
    _, refs = _refs(2)
    alias = C0CellRef.model_validate({
        **refs[1].model_dump(mode="python"),
        "time": {**refs[1].time.model_dump(mode="python"), "available_at_step": 2},
    })
    assert record_digest(refs[1]) != record_digest(alias)
    with pytest.raises((ValueError, ValidationError)):
        _link(refs[0], [refs[1], alias], at=2)


def test_r2_subject_alias_cannot_change_availability_to_support_itself():
    _, refs = _refs(1)
    alias = C0CellRef.model_validate({
        **refs[0].model_dump(mode="python"),
        "time": {**refs[0].time.model_dump(mode="python"), "available_at_step": 1},
    })
    assert record_digest(refs[0]) != record_digest(alias)
    with pytest.raises((ValueError, ValidationError)):
        _link(refs[0], [alias], at=1)


def test_r2_one_observation_cannot_fake_temporal_successor_with_stream_seq():
    observation = _obs(_ctx(), 0)
    subject = cell_ref_from_observation(observation, 0)
    alias = C0CellRef.model_validate({
        **subject.model_dump(mode="python"),
        "time": {**subject.time.model_dump(mode="python"), "stream_seq": 1},
    })
    with pytest.raises((ValueError, ValidationError)):
        resolve_link(
            _link(subject, [alias], kind=EvidenceKind.SAME_CELL_LATER),
            {observation.id: observation},
        )


def test_r2_different_cells_of_same_observation_remain_valid_cooccurrence():
    observation = _obs(_ctx(), 0)
    subject, support = [cell_ref_from_observation(observation, cell) for cell in (0, 1)]
    link = _link(subject, [support])
    assert resolve_link(link, {observation.id: observation}) == link


@pytest.mark.parametrize("consumer", ["digest", "cell_ref", "verify", "resolver"])
def test_r2_observation_copy_with_undeclared_extra_is_rejected(consumer):
    observations = [_obs(_ctx(), 0)]
    observation = observations[0]
    copied = observation.model_copy(update={"undeclared_s02": "smuggled"})
    assert "undeclared_s02" in copied.__dict__
    ref = cell_ref_from_observation(observation, 0)
    with pytest.raises((ValueError, ValidationError)):
        if consumer == "digest":
            observation_digest(copied)
        elif consumer == "cell_ref":
            cell_ref_from_observation(copied, 0)
        elif consumer == "verify":
            verify_cell_ref(ref, copied)
        else:
            support = cell_ref_from_observation(observation, 1)
            resolve_link(_link(ref, [support]), {observation.id: copied})


def test_r2_nested_payload_copy_with_undeclared_extra_is_rejected():
    observation = _obs(_ctx(), 0)
    payload = observation.payload.model_copy(update={"undeclared_s02": "smuggled"})
    copied = observation.model_copy(update={"payload": payload})
    with pytest.raises((ValueError, ValidationError)):
        observation_digest(copied)


@pytest.mark.parametrize("consumer", ["verify", "canonical", "digest"])
def test_r2_cell_ref_copy_with_undeclared_extra_is_rejected(consumer):
    observation = _obs(_ctx(), 0)
    ref = cell_ref_from_observation(observation, 0)
    copied = ref.model_copy(update={"undeclared_s02": "smuggled"})
    with pytest.raises((ValueError, ValidationError)):
        if consumer == "verify":
            verify_cell_ref(copied, observation)
        elif consumer == "canonical":
            to_canonical_json(copied)
        else:
            record_digest(copied)


def test_r2_time_copy_with_undeclared_extra_is_rejected():
    time = _t()
    copied = time.model_copy(update={"undeclared_s02": "smuggled"})
    with pytest.raises((ValueError, ValidationError)):
        compare_time(copied, time)


@pytest.mark.parametrize("nested", [False, True])
def test_r2_link_or_nested_ref_copy_with_undeclared_extra_is_rejected(nested):
    _, refs = _refs(2)
    link = _link(refs[0], [refs[1]])
    if nested:
        support = refs[1].model_copy(update={"undeclared_s02": "smuggled"})
        copied = link.model_copy(update={"supports": (support,)})
    else:
        copied = link.model_copy(update={"undeclared_s02": "smuggled"})
    with pytest.raises((ValueError, ValidationError)):
        links_visible_at((copied,), 2)
