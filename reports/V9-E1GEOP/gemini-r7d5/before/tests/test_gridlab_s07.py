"""S07: GridLab-v1 tests (CPU only, no MLX, no training)."""

import json
import sys
from pathlib import Path
from uuid import UUID

import numpy as np
import pytest

from ainerzero.core import spacetime_records as sr
from ainerzero.core.experience import DatasetPartition, OriginKind
from ainerzero.data import gridlab_v1_trajectory as gt
from ainerzero.environments import gridlab_v1 as v1

SAMPLE = Path(__file__).resolve().parents[1] / "artifacts" / "gridlab2d" / "s07-sample"
RUN = UUID(int=7)


def test_no_mlx():
    # S07-R2: fresh interpreter, so other tests importing MLX cannot affect the result
    import subprocess
    code = ("import sys; import ainerzero.environments.gridlab_v1, ainerzero.data.gridlab_v1_trajectory; "
            "bad = [m for m in sys.modules if m == 'mlx' or m.startswith('mlx.')]; "
            "assert not bad, bad")
    r = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr


def test_spec_dimensions_and_determinism():
    w = v1.make_world(1)
    assert len(w.terrain) == len(w.terrain[0]) == 11 and len(v1.Action) == 6
    obs = w.public_observation(UUID(int=1), None)
    assert len(obs["view"]) == 5 and all(len(r) == 5 for r in obs["view"])
    rgb = v1.decode_rgb(obs)
    assert rgb.shape == (80, 80, 3) and rgb.dtype == np.uint8
    assert tuple(rgb[40, 40]) == v1.AGENT_COLOR
    a, b = gt.simulate(3, "door_room", 10), gt.simulate(3, "door_room", 10)
    assert [o["observation_sha256"] for o in a["public"]] == [o["observation_sha256"] for o in b["public"]]
    assert v1.make_world(3, family="open").world_id != v1.make_world(3, family="door_room").world_id
    with pytest.raises(ValueError):
        v1.make_world(1, family="nope")


def test_rgb_tamper_detected():
    obs = v1.make_world(2).public_observation(UUID(int=1), None)
    bad = dict(obs, rgb_sha256="0" * 64)
    with pytest.raises(ValueError, match="rgb"):
        v1.decode_rgb(bad)


def test_render_shows_only_visible():
    view = [[v1.UNSEEN] * 5 for _ in range(5)]
    img = v1.render(view, [])
    assert tuple(img[0, 0]) == v1.COLORS[v1.UNSEEN]
    img = v1.render([[v1.FREE] * 5 for _ in range(5)], [[1, 0, "red_disc"]])
    assert tuple(img[2 * 16 + 8, 3 * 16 + 8]) == v1.OBJ_COLORS["red_disc"]


def test_door_and_switch():
    w = v1.make_world(4, family="door_room")
    (sw, door), = w.switches.items()
    assert w.terrain[door[1]][door[0]] == v1.DOOR_CLOSED and not w.free(*door)
    w.agent = sw
    w.objects = []
    w.apply(v1.Action.INTERACT)
    assert w.terrain[door[1]][door[0]] == v1.DOOR_OPEN and w.free(*door) and w.toggles == 1
    w.apply(v1.Action.INTERACT)
    assert w.terrain[door[1]][door[0]] == v1.DOOR_CLOSED
    w.agent = (door[0] - 1, door[1])
    w.apply(v1.Action.RIGHT)
    assert w.agent == (door[0] - 1, door[1])  # closed door blocks
    w.apply(v1.Action.INTERACT)  # not on switch: nothing
    assert w.toggles == 2


def test_closed_door_is_opaque():
    w = v1.make_world(4, family="door_room", pillars=0, balls=0, boxes=0)
    (_, door), = w.switches.items()
    w.agent = (door[0] - 1, door[1])
    assert w.visibility_of(door[0] + 1, door[1]) == "occluded"
    w.terrain[door[1]][door[0]] = v1.DOOR_OPEN
    assert w.visibility_of(door[0] + 1, door[1]) == "visible"


def test_public_obs_hides_identity_and_hidden_objects():
    w = v1.make_world(5)
    obs = w.public_observation(UUID(int=1), None)
    raw = v1.canonical(obs).decode()
    assert all(str(o.object_id) not in raw for o in w.objects) and "object_id" not in raw
    ax, ay = w.agent
    hidden = [[o.x - ax, o.y - ay] for o in w.objects if w.visibility_of(o.x, o.y) != "visible"]
    assert all(h not in [v[:2] for v in obs["visible_objects"]] for h in hidden)
    assert all(abs(v[0]) <= 2 and abs(v[1]) <= 2 for v in obs["visible_objects"])


def test_scenario_events():
    swap = gt.simulate(27, "swap_lane", 16)
    types = {e["type"] for e in swap["events"]}
    assert "identity_swap" in types and swap["flags"]["similar_objects"]
    walk = gt.simulate(28, "occlusion_walk", 16)
    assert any(e["type"] == "occlusion" and e["k"] == 3 for e in walk["events"]) and walk["flags"]["occlusion"]
    door = gt.simulate(24, "door_room", 16)
    assert any(e["type"] == "door_toggle" for e in door["events"])


def test_detect_events_counterexamples():
    def st(vis_a, xy_a, vis_b, xy_b, toggles=0):
        return {"toggles": toggles, "objects": [
            {"appearance": "red_disc", "visibility": vis_a, "xy": xy_a},
            {"appearance": "red_disc", "visibility": vis_b, "xy": xy_b}]}
    # both hidden then reappear on their own sides: no swap
    seq = [st("visible", [3, 6], "visible", [7, 6]), st("occluded", [4, 6], "occluded", [6, 6]),
           st("visible", [3, 6], "visible", [7, 6])]
    assert not any(e["type"] == "identity_swap" for e in v1.detect_events(seq))
    seq[2] = st("visible", [7, 6], "visible", [3, 6])
    assert any(e["type"] == "identity_swap" for e in v1.detect_events(seq))
    # occlusion that never ends visible is not an occlusion event
    seq = [st("visible", [1, 1], "out_of_view", [9, 9]), st("occluded", [1, 1], "out_of_view", [9, 9]),
           st("out_of_view", [1, 1], "out_of_view", [9, 9])]
    assert not any(e["type"] == "occlusion" for e in v1.detect_events(seq))


def test_annotations(tmp_path):
    sim = gt.simulate(27, "swap_lane", 16)
    d = gt.write_episode(tmp_path, sim, run_id=RUN, partition=DatasetPartition.FINAL, unseen_paths=True)
    p = gt.load_private(d)
    vis_seen = set()
    for t in p["entity_tracks"]:
        for s in t.states:
            vis_seen.add(s.visibility)
            if s.visibility is sr.Visibility.VISIBLE:
                assert s.estimate.origin is sr.EstimateOrigin.OBSERVED and len(s.estimate.value) == 2
            else:
                assert s.visibility is not sr.Visibility.LOST
                assert s.estimate is None or s.estimate.origin is sr.EstimateOrigin.PREDICTED
    assert {sr.Visibility.VISIBLE, sr.Visibility.OCCLUDED, sr.Visibility.OUT_OF_VIEW} <= vis_seen
    with pytest.raises(ValueError, match="evaluator-private"):
        sr.student_visible(p["truth_estimates"][:1])


def test_out_of_view_state_rules():
    sim = gt.simulate(21, "open", 2)
    t = gt.annotate(sim["world"], RUN, sim["episode_id"], DatasetPartition.TRAIN, sim["public"],
                    sim["private"])[0][0].states[0].time
    ref = sr.GridCellRef(time=t, x=1, y=1, observation_id=UUID(int=2), observation_sha256="c" * 64,
                         origin=OriginKind.OBSERVED)
    e = sr.SpatialEstimate(estimate_id=UUID(int=3), time=t, value=(1.0, 1.0), uncertainty_basis="none",
                           supports=(ref,), origin="observed", **gt.FRAME)
    with pytest.raises(ValueError, match="predicted or imagined"):
        sr.TrackState(time=t, visibility="out_of_view", estimate=e)
    assert sr.TrackState(time=t, visibility="out_of_view").estimate is None
    assert sr.Visibility("lost") is sr.Visibility.LOST  # legacy value still valid


def test_tamper_and_private_isolation(tmp_path, monkeypatch):
    sim = gt.simulate(22, "open", 4)
    d = gt.write_episode(tmp_path, sim, run_id=RUN, partition=DatasetPartition.TRAIN, unseen_paths=False)
    real = Path.read_bytes

    def guard(self):
        if self.name == "private.json":
            raise AssertionError("public loader touched private.json")
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", guard)
    gt.load_public(d)
    monkeypatch.undo()
    raw = (d / "public.jsonl").read_bytes()
    (d / "public.jsonl").write_bytes(raw.replace(b'"step":2', b'"step":3', 1))
    with pytest.raises(ValueError, match="manifest"):
        gt.load_public(d)


def test_heldout_assignment_and_leakage():
    sims = [gt.simulate(s, f, 16) for s, f in gt.SAMPLE_SPECS]
    splits = gt.assign_with_heldout(sims)
    for s in sims:
        if any(s["flags"].values()):
            assert splits[s["world"].world_id] is not DatasetPartition.TRAIN
    base = {"path_sha256": "p", "content_digests": [], "unseen_paths": False}
    with pytest.raises(ValueError, match="held-out"):
        v1.check_heldout_leakage([{**base, "partition": "train", "flags": {"occlusion": True}}])
    with pytest.raises(ValueError, match="unseen_paths"):
        v1.check_heldout_leakage([{**base, "partition": "train", "flags": {}},
                                  {**base, "partition": "final", "flags": {}, "unseen_paths": True}])
    stats = v1.check_heldout_leakage([{**base, "partition": "train", "flags": {}, "content_digests": ["a"]},
                                      {**base, "partition": "final", "flags": {}, "content_digests": ["a"]}])
    assert stats["content_overlap"] == {"final|train": 1}


@pytest.mark.skipif(not SAMPLE.exists(), reason="S07 sample not generated")
def test_real_sample():
    summary = json.loads((SAMPLE / "splits.json").read_bytes())
    v1.check_heldout_leakage(summary["episodes"])
    dirs = sorted(p for p in SAMPLE.iterdir() if p.is_dir())
    assert len(dirs) == len(summary["episodes"]) == len(gt.SAMPLE_SPECS)
    parts, events = set(), set()
    for d in dirs:
        p = gt.load_private(d)
        parts.add(p["public"]["header"]["partition"])
        events |= {e["type"] for e in p["events"]}
        if p["public"]["header"]["partition"] == "train":
            assert not any(p["heldout_flags"].values())
        assert "object_id" not in (d / "public.jsonl").read_text()
    assert parts == {"train", "development", "final"}
    assert {"identity_swap", "same_appearance_confusion", "occlusion", "door_toggle"} <= events


def test_not_wired_into_training():
    # gridlab_tracking.py、gridlab_tracking_eval.py：评测专用、只读公开观测、不接训练
    root = Path(v1.__file__).resolve().parents[1]
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
    users = [p for p in root.rglob("*.py") if p.name not in allowed and "gridlab" in p.read_text()]
    assert users == []
