"""S05: CPU tests for S04 record schemas (no MLX, no data collection, no model)."""

import sys
import uuid

import pytest

from ainerzero.core import spacetime_records as sr
from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.core.spacetime import C0CellRef, TimeIndex

RUN, EP, WORLD = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)
DIG = "a" * 64


def t(step, avail=None, partition=DatasetPartition.TRAIN, world=WORLD):
    return TimeIndex(run_id=RUN, world_id=world, episode_id=EP, partition=partition, step=step,
                     available_at_step=step if avail is None else avail)


def cell(step, c=0, origin=OriginKind.OBSERVED, **kw):
    return C0CellRef(time=t(step, **kw), cell=c, observation_id=uuid.UUID(int=1000 + step),
                     observation_sha256=DIG, origin=origin)


def est(step=5, kind="grid_xy", value=(1.0, 2.0), unit="cell", origin="observed", supports=None, **kw):
    return sr.SpatialEstimate(
        estimate_id=uuid.uuid4(), time=kw.pop("time", t(step)), coordinate_kind=kind, frame_id="grid",
        frame_revision=0, unit=unit, axes="x_right_y_down", value=value,
        uncertainty_basis=kw.pop("uncertainty_basis", "none"),
        supports=(cell(step),) if supports is None else supports, origin=origin, **kw)


def test_no_mlx():
    # S07-R2: fresh interpreter, so other tests importing MLX cannot affect the result
    import subprocess
    code = ("import sys; import ainerzero.core.spacetime_records; "
            "bad = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]; "
            "assert not bad, bad")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


# ---- SpatialEstimate

def test_valid_estimates_round_trip():
    e = est()
    raw = sr.to_canonical_json(e)
    back = sr.load_record(sr.SpatialEstimate, raw)
    assert sr.record_digest(back) == sr.record_digest(e)
    w = est(kind="world_xyz", value=(0.1, 0.2, 0.3), unit="metre", origin="student_estimate",
            orientation=(1.0, 0.0, 0.0, 0.0), uncertainty=(0.1, 0.1, 0.2), uncertainty_basis="calibrated")
    assert sr.record_digest(w) != sr.record_digest(e)


@pytest.mark.parametrize("kind,value,unit", [
    ("grid_xy", (1.0, 2.0, 0.0), "cell"),          # fabricated z on 2D
    ("image_xy", (1.0, 2.0, 0.0), "pixel"),
    ("world_xyz", (1.0, 2.0), "metre"),             # missing depth
    ("grid_xy", (1.0, 2.0), "metre"),               # unit mismatch
    ("image_xy", (1.0, 2.0), "cell"),
    ("symbol_slot", (1.5,), "cell"),                # not a slot index
])
def test_dimension_and_unit_rejections(kind, value, unit):
    with pytest.raises(ValueError):
        est(kind=kind, value=value, unit=unit)


def test_uncertainty_needs_basis_and_no_basis_without_values():
    with pytest.raises(ValueError, match="basis"):
        est(uncertainty=(0.1, 0.1))
    with pytest.raises(ValueError, match="basis"):
        est(uncertainty_basis="calibrated")
    with pytest.raises(ValueError):
        est(uncertainty=(0.1,), uncertainty_basis="empirical_dev")
    with pytest.raises(ValueError):
        est(value=(float("nan"), 1.0))
    with pytest.raises(ValueError, match="quaternion"):
        est(orientation=(1.0, 0.0, 0.0, 0.0))


def test_future_evidence_and_partition_mixing_rejected():
    with pytest.raises(ValueError, match="not yet available"):
        est(step=5, supports=(cell(6),))
    with pytest.raises(ValueError, match="partitions"):
        est(step=5, supports=(cell(4, partition=DatasetPartition.DEVELOPMENT),))
    with pytest.raises(ValueError, match="duplicate"):
        est(step=5, supports=(cell(4), cell(4)))


def test_observed_requires_observed_c0_only():
    with pytest.raises(ValueError, match="observed"):
        est(supports=(cell(5, origin=OriginKind.IMAGINED),))
    ref = sr.record_ref(est(step=3))
    with pytest.raises(ValueError):
        est(supports=(ref,))
    assert est(origin="student_estimate", supports=(ref,)).origin is sr.EstimateOrigin.STUDENT_ESTIMATE


def test_private_truth_and_student_view():
    private = est(origin="evaluator_private", supports=())
    with pytest.raises(ValueError):
        est(origin="evaluator_private")
    with pytest.raises(ValueError, match="supporting"):
        est(origin="student_estimate", supports=())
    with pytest.raises(ValueError, match="evaluator-private"):
        sr.student_visible([est(), private])
    assert len(sr.student_visible([est()])) == 1


def test_comparable_requires_same_frame_and_time_scope():
    a, b = est(step=4, supports=(cell(4),)), est(step=5)
    assert sr.comparable(a, b)
    other = sr.SpatialEstimate(**{**b.model_dump(), "frame_revision": 1})
    assert not sr.comparable(a, other)
    c = est(step=5, time=t(5, world=uuid.UUID(int=9)), supports=(cell(5, world=uuid.UUID(int=9)),))
    assert not sr.comparable(a, c)


def test_constructed_instances_revalidated():
    bad = sr.SpatialEstimate.model_construct(**{**est().model_dump(), "value": (1.0, 2.0, 0.0)})
    with pytest.raises(ValueError):
        sr.record_digest(bad)
    with pytest.raises(ValueError):
        sr.revalidate_record(object())
    with pytest.raises(Exception):
        sr.load_record(sr.SpatialEstimate, sr.to_canonical_json(est())[:-1] + b',"extra":1}')


# ---- EntityTrack

def state(step, vis, origin="observed"):
    e = None if origin is None else est(step=step, origin=origin,
                                        supports=(cell(step),) if origin == "observed" else (cell(step - 1),))
    return sr.TrackState(time=t(step), visibility=vis, estimate=e)


def track(states, **kw):
    return sr.EntityTrack(world_id=WORLD, track_id=uuid.UUID(int=50), states=states,
                          asserted_at_step=kw.pop("asserted_at_step", 20), **kw)


def test_track_valid_with_occlusion_prediction():
    tr = track([state(1, "visible"), state(2, "occluded", "predicted"), state(3, "occluded", None),
                state(4, "visible")])
    assert sr.available_at(tr) == 20


@pytest.mark.parametrize("vis", ["occluded", "lost", "unknown"])
def test_hidden_states_cannot_cite_observed(vis):
    with pytest.raises(ValueError, match="predicted or imagined"):
        state(2, vis, "observed")
    with pytest.raises(ValueError, match="predicted or imagined"):
        state(2, vis, "student_estimate")


def test_visible_state_rules():
    with pytest.raises(ValueError, match="needs an estimate"):
        state(2, "visible", None)
    with pytest.raises(ValueError, match="observed or student"):
        state(2, "visible", "imagined")
    e = est(step=3)
    with pytest.raises(ValueError, match="own time"):
        sr.TrackState(time=t(2), visibility="visible", estimate=e)


def test_track_order_world_and_availability():
    with pytest.raises(ValueError, match="strictly time ordered"):
        track([state(2, "visible"), state(1, "visible")])
    with pytest.raises(ValueError, match="not yet available"):
        track([state(1, "visible"), state(5, "visible")], asserted_at_step=4)
    other = uuid.UUID(int=9)
    s = sr.TrackState(time=t(1, world=other), visibility="occluded")
    with pytest.raises(ValueError, match="world"):
        track([s])


def test_identity_hypotheses_need_evidence_and_distinct():
    h = sr.IdentityHypothesis(candidate_world_id=uuid.UUID(int=8), candidate_track_id=uuid.UUID(int=51),
                              supports=(cell(1),))
    assert track([state(1, "visible")], identity_hypotheses=(h,))
    with pytest.raises(ValueError):
        sr.IdentityHypothesis(candidate_world_id=uuid.UUID(int=8), candidate_track_id=uuid.UUID(int=51),
                              supports=())
    with pytest.raises(ValueError, match="distinct"):
        track([state(1, "visible")], identity_hypotheses=(h, h))
    self_h = sr.IdentityHypothesis(candidate_world_id=WORLD, candidate_track_id=uuid.UUID(int=50),
                                   supports=(cell(1),))
    with pytest.raises(ValueError, match="distinct"):
        track([state(1, "visible")], identity_hypotheses=(self_h,))


# ---- SemanticBinding

def binding(**kw):
    base = dict(binding_id=uuid.UUID(int=70), subject=cell(2), concept_id="cup", concept_revision=0,
                term="杯子", relation="names", namer="teacher-1", assistance="teacher_named",
                supports=(cell(3),), available_at_step=5)
    base.update(kw)
    return sr.SemanticBinding(**base)


def test_binding_valid_and_rules():
    b = binding(counterexamples=(cell(4),))
    assert sr.load_record(sr.SemanticBinding, sr.to_canonical_json(b)) == b
    with pytest.raises(ValueError):
        binding(assistance=None)
    with pytest.raises(ValueError, match="both support and contradict"):
        binding(counterexamples=(cell(3),))
    with pytest.raises(ValueError, match="own subject"):
        binding(supports=(cell(2),))
    with pytest.raises(ValueError, match="not yet available"):
        binding(supports=(cell(9),))
    with pytest.raises(ValueError, match="partitions"):
        binding(supports=(cell(3, partition=DatasetPartition.DEVELOPMENT),))
    with pytest.raises(ValueError, match="whitespace"):
        binding(term=" 杯子")
    with pytest.raises(ValueError):
        binding(supports=())


# ---- ImaginedBranch

def branch(**kw):
    pred = est(step=8, origin="imagined", supports=(cell(5),), time=t(8))
    base = dict(branch_id=uuid.UUID(int=90), start_belief=sr.record_ref(est(step=5)), evidence_cutoff_step=5,
                model_version="m", mechanism_version="k", hypothetical_actions=(1, 2, 3), horizon=3,
                budget_units=10, predictions=(pred,))
    base.update(kw)
    return sr.ImaginedBranch(**base)


def test_unchecked_branch_is_not_evidence():
    b = branch()
    with pytest.raises(ValueError, match="unchecked"):
        sr.branch_evidence(b)
    checked = branch(checked_against=(cell(8),))
    ev = sr.branch_evidence(checked)
    assert ev["kind"] == "prediction_outcome_pairs" and len(ev["outcomes"]) == 1


def test_branch_rules():
    with pytest.raises(ValueError, match="own parent"):
        branch(parent_branch_id=uuid.UUID(int=90))
    with pytest.raises(ValueError, match="horizon"):
        branch(horizon=2)
    with pytest.raises(ValueError, match="origin imagined"):
        branch(predictions=(est(step=8, origin="predicted", supports=(cell(5),)),))
    with pytest.raises(ValueError, match="after the evidence cutoff"):
        branch(predictions=(est(step=5, origin="imagined", supports=(cell(5),)),))
    with pytest.raises(ValueError, match="after the cutoff"):
        branch(predictions=(est(step=8, origin="imagined", supports=(cell(7),)),))
    with pytest.raises(ValueError, match="observed outcomes"):
        branch(checked_against=(cell(8, origin=OriginKind.IMAGINED),))
    with pytest.raises(ValueError, match="after the evidence cutoff"):
        branch(checked_against=(cell(4),))
    with pytest.raises(ValueError, match="start belief"):
        branch(start_belief=sr.record_ref(est(step=7)))


# ---- revisions & as-of view

def test_revision_history_and_visibility():
    b0 = binding()
    b1 = binding(revision=1, supersedes_sha256=sr.record_digest(b0), available_at_step=7, concept_revision=1)
    assert sr.records_visible_at([b0, b1], 6) == (b0,)
    assert sr.records_visible_at([b0, b1], 7) == (b0, b1)
    with pytest.raises(ValueError, match="missing"):
        sr.validate_history([b1])
    with pytest.raises(ValueError, match="pair|superseded"):
        binding(revision=1)
    fork = binding(revision=1, supersedes_sha256=sr.record_digest(b0), available_at_step=8)
    with pytest.raises(ValueError, match="forked"):
        sr.validate_history([b0, b1, fork])
    back = binding(revision=1, supersedes_sha256=sr.record_digest(b0), available_at_step=4)
    with pytest.raises(ValueError, match="before its predecessor"):
        sr.validate_history([b0, back])
    other_id = binding(binding_id=uuid.UUID(int=71), revision=1, supersedes_sha256=sr.record_digest(b0))
    with pytest.raises(ValueError, match="keep record type and id"):
        sr.validate_history([b0, other_id])
    with pytest.raises(ValueError, match="duplicate"):
        sr.validate_history([b0, b0])
    with pytest.raises(ValueError):
        sr.records_visible_at([b0], -1)


def test_record_ref_carries_type_and_availability():
    e = est(step=4, supports=(cell(4),))
    r = sr.record_ref(e)
    assert r.record_type is sr.RecordType.SPATIAL_ESTIMATE and r.available_at_step == 4
    assert r.sha256 == sr.record_digest(e)


def test_module_is_not_wired_anywhere():
    import pathlib
    root = pathlib.Path(sr.__file__).resolve().parents[1]
    users = [p for p in root.rglob("*.py") if p.name not in ("spacetime_records.py", "gridlab_trajectory.py", "gridlab_v1_trajectory.py")  # S06/S07 annotators
             and "spacetime_records" in p.read_text()]
    assert users == []
