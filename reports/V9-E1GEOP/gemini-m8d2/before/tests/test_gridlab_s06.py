"""S06: GridLab 2D environment/trajectory tests (CPU only, no MLX, no training)."""

import json
import sys
from pathlib import Path
from uuid import UUID

import pytest

from ainerzero.core import spacetime_records as sr
from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.data import gridlab_trajectory as gt
from ainerzero.environments import gridlab2d as gl

SAMPLE = Path(__file__).resolve().parents[1] / "artifacts" / "gridlab2d" / "s06-sample"
RUN = UUID(int=5)


def test_no_mlx():
    # S07-R2: fresh interpreter, so other tests importing MLX cannot affect the result
    import subprocess
    code = ("import sys; import ainerzero.environments.gridlab2d, ainerzero.data.gridlab_trajectory; "
            "bad = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]; "
            "assert not bad, bad")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_determinism_and_distinct_seeds():
    a, b = gl.make_world(3), gl.make_world(3)
    assert a.layout_sha256() == b.layout_sha256() and a.world_id == b.world_id
    ea, pa, _, aa = gt.rollout(a, steps=10, policy_seed=1)
    eb, pb, _, ab = gt.rollout(b, steps=10, policy_seed=1)
    assert (ea, aa) == (eb, ab) and [o["observation_sha256"] for o in pa] == [o["observation_sha256"] for o in pb]
    assert gl.make_world(4).layout_sha256() != a.layout_sha256()
    with pytest.raises(ValueError):
        gl.make_world(-1)


def test_persistent_identity_and_ball_dynamics():
    w = gl.make_world(7)
    ids = [o.object_id for o in w.objects]
    ball = next(o for o in w.objects if o.kind == "ball")
    before = (ball.x, ball.y)
    w.apply(gl.Action.WAIT)
    assert [o.object_id for o in w.objects] == ids
    assert max(abs(ball.x - before[0]), abs(ball.y - before[1])) <= 1
    for _ in range(30):
        w.apply(gl.Action.WAIT)
        cells = [(o.x, o.y) for o in w.objects]
        assert len(set(cells)) == len(cells) and w.agent not in cells
        assert all(w.terrain[y][x] == gl.FREE for x, y in cells)


def test_constant_velocity_is_predictable_in_open_space():
    w = gl.make_world(1, pillars=0, balls=1, boxes=0, width=15, height=15)
    b = w.objects[0]
    b.x, b.y, b.vx, b.vy = 7, 7, 1, 0
    w.agent = (1, 1)
    w.apply(gl.Action.WAIT)
    assert (b.x, b.y) == (8, 7)


def test_reflection_off_wall():
    w = gl.make_world(1, pillars=0, balls=1, boxes=0)
    b = w.objects[0]
    b.x, b.y, b.vx, b.vy = w.width - 2, 4, 1, 0
    w.agent = (1, 1)
    w.apply(gl.Action.WAIT)
    assert (b.x, b.vx) == (w.width - 3, -1)


def test_push_box():
    w = gl.make_world(1, pillars=0, balls=0, boxes=1)
    box = w.objects[0]
    w.agent, box.x, box.y = (3, 4), 4, 4
    w.apply(gl.Action.RIGHT)
    assert w.agent == (4, 4) and (box.x, box.y) == (5, 4)
    box.x = w.width - 2
    w.agent = (w.width - 3, 4)
    w.apply(gl.Action.RIGHT)  # box against wall: nothing moves
    assert w.agent == (w.width - 3, 4) and box.x == w.width - 2


def test_occlusion_by_pillar_and_window():
    w = gl.make_world(1, pillars=0, balls=0, boxes=0, width=11, height=11, view_radius=3)
    w.agent = (2, 5)
    w.terrain[5][3] = gl.PILLAR
    assert w.visibility_of(4, 5) == "occluded"
    assert w.visibility_of(2, 3) == "visible"
    assert w.visibility_of(9, 5) == "out_of_view"


def test_public_observation_has_no_identity_or_hidden_objects():
    w = gl.make_world(13)
    eid = UUID(int=9)
    obs = w.public_observation(eid, None)
    raw = gl.canonical(obs).decode()
    assert all(str(o.object_id) not in raw for o in w.objects)
    assert "object_id" not in raw and "velocity" not in raw
    hidden = [(o.x, o.y) for o in w.objects if w.visibility_of(o.x, o.y) != "visible"]
    assert all([x, y] not in [v[:2] for v in obs["visible_objects"]] for x, y in hidden)


def test_annotations_follow_s05_rules(tmp_path):
    w = gl.make_world(14)
    d = gt.write_episode(tmp_path, w, run_id=RUN, partition=DatasetPartition.TRAIN, steps=15)
    p = gt.load_private(d)
    seen_hidden = False
    for t in p["entity_tracks"]:
        assert t.world_id == w.world_id and t.concept_id in ("ball", "box")
        for s in t.states:
            if s.visibility is sr.Visibility.VISIBLE:
                assert s.estimate.origin is sr.EstimateOrigin.OBSERVED
                (ref,) = s.estimate.supports
                assert isinstance(ref, sr.GridCellRef) and ref.time.step == s.time.step
                assert len(s.estimate.value) == 2  # grid xy, no z
            else:
                seen_hidden = True
                assert s.estimate is None or s.estimate.origin is sr.EstimateOrigin.PREDICTED
    assert seen_hidden
    with pytest.raises(ValueError, match="evaluator-private"):
        sr.student_visible(p["truth_estimates"][:1])


def test_hidden_state_cannot_be_annotated_as_observed():
    w = gl.make_world(14)
    t = gt._time(RUN, w, UUID(int=1), DatasetPartition.TRAIN, 3)
    ref = sr.GridCellRef(time=t, x=1, y=1, observation_id=UUID(int=2), observation_sha256="b" * 64,
                         origin=OriginKind.OBSERVED)
    e = sr.SpatialEstimate(estimate_id=UUID(int=3), time=t, value=(1.0, 1.0), uncertainty_basis="none",
                           supports=(ref,), origin="observed", **gt.FRAME)
    with pytest.raises(ValueError, match="predicted or imagined"):
        sr.TrackState(time=t, visibility="occluded", estimate=e)
    with pytest.raises(ValueError):
        sr.SpatialEstimate(estimate_id=UUID(int=3), time=t, value=(1.0, 1.0, 0.0), uncertainty_basis="none",
                           supports=(ref,), origin="observed", **gt.FRAME)
    imagined_ref = sr.GridCellRef(**{**ref.model_dump(), "origin": OriginKind.IMAGINED})
    with pytest.raises(ValueError, match="observed"):
        sr.SpatialEstimate(estimate_id=UUID(int=3), time=t, value=(1.0, 1.0), uncertainty_basis="none",
                           supports=(imagined_ref,), origin="observed", **gt.FRAME)
    later = gt._time(RUN, w, UUID(int=1), DatasetPartition.TRAIN, 4)
    with pytest.raises(ValueError, match="not yet available"):
        sr.SpatialEstimate(estimate_id=UUID(int=3), time=t, value=(1.0, 1.0), uncertainty_basis="none",
                           supports=(sr.GridCellRef(**{**ref.model_dump(), "time": later}),),
                           origin="observed", **gt.FRAME)


def test_tamper_detection(tmp_path):
    d = gt.write_episode(tmp_path, gl.make_world(15), run_id=RUN, partition=DatasetPartition.TRAIN, steps=5)
    pub = (d / "public.jsonl").read_bytes()
    (d / "public.jsonl").write_bytes(pub.replace(b'"step":3', b'"step":4', 1))
    with pytest.raises(ValueError, match="manifest"):
        gt.load_public(d)
    (d / "public.jsonl").write_bytes(pub)
    gt.load_public(d)
    (d / "extra.txt").write_text("x")
    with pytest.raises(ValueError, match="unexpected"):
        gt.load_public(d)


def test_public_loader_never_reads_private(tmp_path, monkeypatch):
    d = gt.write_episode(tmp_path, gl.make_world(16), run_id=RUN, partition=DatasetPartition.TRAIN, steps=4)
    real = Path.read_bytes

    def guard(self):
        if self.name == "private.json":
            raise AssertionError("public loader touched private.json")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", guard)
    assert len(gt.load_public(d)["observations"]) == 5


def test_world_level_splits_and_leakage():
    ids = [gl.world_id_for(s) for s in range(10)]
    a = gl.assign_splits(ids)
    assert a == gl.assign_splits(list(reversed(ids)))
    counts = {p: list(a.values()).count(p) for p in gl.SPLIT_FRACTIONS}
    assert counts == {DatasetPartition.TRAIN: 6, DatasetPartition.DEVELOPMENT: 2, DatasetPartition.FINAL: 2}
    with pytest.raises(ValueError):
        gl.assign_splits(ids + ids[:1])
    w = gl.make_world(1)
    ep = {"world_id": str(w.world_id), "seed": 1, "layout_sha256": w.layout_sha256()}
    gl.check_split_leakage([{**ep, "partition": "train"}, {**ep, "partition": "train"}])
    with pytest.raises(ValueError, match="world_id"):
        gl.check_split_leakage([{**ep, "partition": "train"}, {**ep, "partition": "final"}])
    copy = {"world_id": "other", "seed": 99, "layout_sha256": w.layout_sha256()}
    with pytest.raises(ValueError, match="layout"):
        gl.check_split_leakage([{**ep, "partition": "train"}, {**copy, "partition": "development"}])
    with pytest.raises(ValueError, match="quarantine"):
        gl.check_split_leakage([{**ep, "partition": "quarantine"}])


@pytest.mark.skipif(not SAMPLE.exists(), reason="S06 sample not generated")
def test_real_sample():
    splits = json.loads((SAMPLE / "splits.json").read_bytes())
    gl.check_split_leakage(splits["episodes"])
    dirs = sorted(p for p in SAMPLE.iterdir() if p.is_dir())
    assert len(dirs) == len(splits["episodes"]) == 5
    parts = set()
    for d in dirs:
        p = gt.load_private(d)
        header = p["public"]["header"]
        parts.add(header["partition"])
        assert all(t.states[0].time.partition.value == header["partition"] for t in p["entity_tracks"])
        assert "object_id" not in (d / "public.jsonl").read_text()
    assert parts == {"train", "development", "final"}


def test_not_wired_into_training():
    # gridlab_tracking.py、gridlab_tracking_eval.py：评测专用、只读公开观测、不接训练
    allowed = {
        "gridlab2d.py",
        "gridlab_trajectory.py",
        "gridlab_v1.py",
        "gridlab_v1_trajectory.py",
        "gridlab_v1_closeout.py",
        "gridlab_v1_r2.py",
        "gridlab_tracking.py",
        "gridlab_tracking_eval.py",
    }
    root = Path(gl.__file__).resolve().parents[1]
    users = [p for p in root.rglob("*.py") if p.name not in allowed and "gridlab" in p.read_text()]
    assert users == []
