"""B5: public-observation tracking baselines and evaluator (synthetic CPU tests only).

No real GridLab samples are read here (B4: formal baseline reports wait for B6/B7).
"""

import ast
import copy
import random
import subprocess
import sys
from pathlib import Path

import pytest

from ainerzero.learning import gridlab_tracking as gt
from ainerzero.learning import gridlab_tracking_eval as ge


def frames(paths, *, hidden=(), appearances=None, agent=(0, 0), extra=False):
    """paths: list of per-object [(x, y)] per step; hidden: {(k, step)} not visible."""
    steps = len(paths[0])
    apps = appearances or [1] * len(paths)
    public, private = [], []
    for s in range(steps):
        vis_objs, objs = [], []
        for k, path in enumerate(paths):
            x, y = path[s]
            visible = (k, s) not in hidden
            if visible:
                vis_objs.append([x - agent[0], y - agent[1], apps[k]])
            vx, vy = (path[s][0] - path[s - 1][0], path[s][1] - path[s - 1][1]) if s else (0, 0)
            objs.append({"object_id": f"obj-{k}", "kind": "ball", "appearance": apps[k], "xy": [x, y],
                         "v": [vx, vy], "visibility": "visible" if visible else "occluded"})
        obs = {"step": s, "agent_xy": list(agent), "last_action": None, "view": [[0]],
               "visible_objects": vis_objs}
        if extra:
            obs.update(private={"objects": objs}, objects=objs, object_ids=[o["object_id"] for o in objs])
        public.append(obs)
        private.append({"step": s, "objects": objs})
    return public, private


def ids(frame, observed=True):
    return [t["track_id"] for t in frame["tracks"] if t["observed"] == observed]


def random_scene(seed=0, steps=30, n=3):
    rng = random.Random(seed)
    paths, hidden = [], set()
    for k in range(n):
        x, y = rng.randrange(2, 12), rng.randrange(2, 12)
        p = []
        for s in range(steps):
            x += rng.choice((-1, 0, 1))
            y += rng.choice((-1, 0, 1))
            p.append((x, y))
            if rng.random() < 0.25:
                hidden.add((k, s))
        paths.append(p)
    return frames(paths, hidden=hidden, appearances=[1, 1, 2][:n])


def test_no_mlx_imported():
    code = ("import sys, ainerzero.learning.gridlab_tracking_eval; "
            "assert not any(k == 'mlx' or k.startswith('mlx.') for k in sys.modules)")
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_public_view_drops_private_keys():
    public, _ = frames([[(3, 3), (4, 3)]], extra=True)
    assert set(gt.public_view(public[0])) == set(gt.PUBLIC_KEYS)
    clean, _ = frames([[(3, 3), (4, 3)]])
    for b in gt.BASELINES:
        assert gt.run_tracker(b, public) == gt.run_tracker(b, clean)


def test_detections_use_agent_offset():
    public, _ = frames([[(5, 7)]], agent=(2, 3))
    assert public[0]["visible_objects"] == [[3, 4, 1]]
    assert gt.detections(gt.public_view(public[0])) == [(5, 7, 1)]


@pytest.mark.parametrize("baseline", gt.BASELINES)
def test_causal_prefix_unchanged_by_future_frames(baseline):
    public, _ = random_scene(1)
    full = gt.run_tracker(baseline, public)
    for t in (1, 5, 17, 29):
        assert gt.run_tracker(baseline, public[:t]) == full[:t]


@pytest.mark.parametrize("baseline", gt.BASELINES)
def test_private_tampering_never_changes_tracker_output(baseline):
    public, private = random_scene(2)
    tampered = copy.deepcopy(private)
    for st in tampered:
        for o in st["objects"]:
            o["object_id"] = "tampered-" + o["object_id"][::-1]
            o["v"] = [99, -99]
    with_private = [dict(p, private=t, objects=t["objects"]) for p, t in zip(public, tampered)]
    out = gt.run_tracker(baseline, public)
    assert gt.run_tracker(baseline, with_private) == out
    # evaluation reads only xy/visibility/appearance: ids and velocities do not matter either
    assert ge.evaluate_episode(out, private)["counts"] == ge.evaluate_episode(out, tampered)["counts"]


def test_same_appearance_tie_is_deterministic():
    # two tracks at (5,5) and (7,5); one detection at (6,5) equidistant -> lower track sequence
    public, _ = frames([[(5, 5), (6, 5)], [(7, 5), (7, 5)]], hidden={(1, 1)})
    out = gt.run_tracker("last_seen_nn", public)
    first = {t["xy"][0]: t["track_id"] for t in out[0]["tracks"]}
    assert ids(out[1]) == [first[5.0]]
    assert gt.run_tracker("last_seen_nn", public) == out
    assert gt.assign([(6, 5, 1)], [(2, 1, (7.0, 5.0)), (1, 1, (5.0, 5.0))]) == {0: 1}


def test_maximum_matching_before_total_distance():
    # greedy nearest would pair det0 with track A and leave det1 unmatched
    dets = [(5, 5, 1), (3, 5, 1)]
    preds = [(1, 1, (4.0, 5.0)), (2, 1, (6.0, 5.0))]
    assert gt.assign(dets, preds) == {0: 1, 1: 0}


def test_appearance_and_l1_gate():
    assert gt.assign([(5, 5, 2)], [(1, 1, (5.0, 5.0))]) == {}
    assert gt.assign([(8, 5, 1)], [(1, 1, (5.0, 5.0))]) == {}
    public, _ = frames([[(5, 5), (8, 5)]])
    out = gt.run_tracker("last_seen_nn", public)
    assert ids(out[0]) != ids(out[1])


def test_retention_eight_ticks_then_lost():
    hidden = {(0, s) for s in range(1, 9)}
    public, _ = frames([[(5, 5)] * 10], hidden=hidden)
    out = gt.run_tracker("last_seen_nn", public)
    tid = ids(out[0])[0]
    assert [t["unseen_ticks"] for t in out[8]["tracks"]] == [8]
    assert out[8]["tracks"][0]["reason"] == "unobserved"
    assert ids(out[9]) == [tid]  # reappears after exactly 8 unseen ticks: kept
    hidden9 = {(0, s) for s in range(1, 10)}
    public, _ = frames([[(5, 5)] * 11], hidden=hidden9)
    out = gt.run_tracker("last_seen_nn", public)
    assert out[9]["tracks"] == []  # unseen 9 > 8: lost
    assert ids(out[10]) != [tid] and len(ids(out[10])) == 1


def test_constant_velocity_zero_and_single_point():
    t = gt.Track(1, 1, [(3, 4, 4)])
    assert t.predict(7, True) == (4.0, 4.0)  # single sighting: zero velocity
    t = gt.Track(1, 1, [(1, 4, 4), (3, 4, 4)])
    assert t.predict(9, True) == (4.0, 4.0)  # zero velocity
    t = gt.Track(1, 1, [(1, 2, 4), (3, 6, 4)])
    assert t.predict(6, True) == (12.0, 4.0)  # integer tick gap extrapolation
    assert t.predict(6, False) == (6.0, 4.0)


def test_constant_velocity_reassociates_where_last_seen_switches():
    path = [(2 + s, 5) for s in range(9)]
    public, private = frames([path], hidden={(0, 3), (0, 4), (0, 5)})
    cv = ge.evaluate_episode(gt.run_tracker("constant_velocity_nn", public), private)
    ls = ge.evaluate_episode(gt.run_tracker("last_seen_nn", public), private)
    assert cv["metrics"]["reappearance_correct"] == [1, 1] and cv["metrics"]["id_switches"] == 0
    assert ls["metrics"]["reappearance_correct"] == [0, 1] and ls["metrics"]["id_switches"] == 1
    assert cv["metrics"]["hidden_prediction_coverage"] == 1.0
    assert cv["metrics"]["hidden_prediction_l1_mean"] == 0.0
    assert ls["metrics"]["hidden_prediction_l1_mean"] == pytest.approx((1 + 2 + 3) / 3)


def test_current_only_never_associates():
    public, private = frames([[(2 + s, 5) for s in range(5)]])
    out = gt.run_tracker("current_only", public)
    assert len({ids(f)[0] for f in out}) == 5
    ev = ge.evaluate_episode(out, private)
    assert ev["counts"]["visible_miss"] == 4 and ev["metrics"]["id_switches"] == 4
    public, private = frames([[(5, 5)] * 4], hidden={(0, 1), (0, 2)})
    ev = ge.evaluate_episode(gt.run_tracker("current_only", public), private)
    assert ev["metrics"]["hidden_prediction_coverage"] == 0.0
    assert ev["metrics"]["hidden_prediction_l1_mean"] is None  # not predicting is not "zero error"


def test_two_same_appearance_objects_in_one_cell_are_ambiguous():
    paths = [[(5, 5), (5, 5), (4, 5), (3, 5)], [(5, 5), (5, 5), (6, 5), (7, 5)]]
    public, private = frames(paths)
    ev = ge.evaluate_episode(gt.run_tracker("last_seen_nn", public), private)
    assert ev["counts"]["ambiguous_steps"] == 4  # 2 objects x 2 shared steps
    assert all(o["mapped_track"] is not None for o in ev["per_object"])  # mapped once separable
    # different appearances on one cell are not ambiguous
    public, private = frames(paths, appearances=[1, 2])
    ev = ge.evaluate_episode(gt.run_tracker("last_seen_nn", public), private)
    assert ev["counts"]["ambiguous_steps"] == 0


def test_mapping_is_never_reassigned_and_swaps_are_counted():
    public, private = frames([[(2, 2)] * 4, [(9, 9)] * 4])
    out = gt.run_tracker("last_seen_nn", public)
    a, b = (t["track_id"] for t in out[0]["tracks"])
    swapped = copy.deepcopy(out)
    for f in swapped[2:]:
        for t in f["tracks"]:
            t["track_id"] = b if t["track_id"] == a else a
    ev = ge.evaluate_episode(swapped, private)
    assert ev["metrics"]["id_switches"] == 2
    assert [o["mapped_track"] for o in ev["per_object"]] == [a, b]
    # the mapped track is observed on the other object's cell: matched but with the swap distance
    assert ev["counts"]["visible_miss"] == 0
    assert ev["counts"]["visible_l1_sum"] == 4 * 14


def test_unidentifiable_reappearance_is_separate():
    paths = [[(5, 5), (5, 6), (5, 6)], [(8, 8), (5, 6), (5, 6)]]
    public, private = frames(paths, hidden={(0, 1), (1, 1)})
    ev = ge.evaluate_episode(gt.run_tracker("last_seen_nn", public), private)
    assert ev["counts"]["reappearance_unidentifiable"] == 2
    assert ev["metrics"]["reappearance_correct"][1] == 0
    assert ev["metrics"]["reappearance_correct_rate"] is None


def test_subsets_overlap_and_empty_is_null():
    public, private = random_scene(3)
    eps = [{"episode_id": "e1", "public": public, "private": private,
            "meta": {"scripted": False, "flags": {"occlusion": True, "similar_objects": False},
                     "events": [{"type": "identity_swap"}], "unseen_paths": False}}]
    res = ge.run_baselines(eps)
    assert res["capability_gate"] is None
    assert res["parameters"] == {"association_l1_max": 2, "retention_ticks": 8}
    assert set(res["source_sha256"]) == {"gridlab_tracking.py", "gridlab_tracking_eval.py"}
    for b in gt.BASELINES:
        subs = res["baselines"][b]["subsets"]
        assert subs["scripted"] is None and subs["similar_objects"] is None and subs["unseen_paths"] is None
        assert subs["all"]["counts"] == subs["random"]["counts"] == subs["occlusion"]["counts"]
        assert subs["identity_swap"]["episodes"] == ["e1"]
    assert ge.metrics(dict.fromkeys(ge.COUNT_KEYS, 0))["visible_position_l1_mean"] is None


def test_frames_must_be_increasing_and_aligned():
    public, private = frames([[(1, 1), (1, 1)]])
    with pytest.raises(ValueError):
        gt.run_tracker("last_seen_nn", [public[1], public[0]])
    with pytest.raises(ValueError):
        ge.evaluate_episode(gt.run_tracker("last_seen_nn", public), private[:1])
    with pytest.raises(ValueError):
        gt.public_view({"agent_xy": [0, 0]})


def test_tracking_is_not_wired_into_training_or_runtime():
    root = Path(gt.__file__).resolve().parents[1]
    users = [p.relative_to(root).as_posix() for p in root.rglob("*.py")
             if p.name not in ("gridlab_tracking.py", "gridlab_tracking_eval.py")
             and ("gridlab_tracking" in p.read_text())]
    assert users == []


def _ast_imports(path: Path) -> set[str]:
    """Module names from Import / ImportFrom nodes. Not a source-text search."""
    found = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            if node.module == "ainerzero.learning":
                found.update(f"ainerzero.learning.{alias.name}" for alias in node.names)
    return found


def test_tracking_modules_import_only_each_other():
    # 评测专用、只读公开观测、不接训练
    root = Path(gt.__file__).resolve().parent
    allowed = {"gridlab_tracking", "gridlab_tracking_eval"}
    for name in sorted(allowed):
        modules = _ast_imports(root / f"{name}.py")
        assert not any(item == "mlx" or item.startswith("mlx.") for item in modules)
        assert not any(item == "ainerzero.runtime" or item.startswith("ainerzero.runtime.") for item in modules)
        learning = {item.removeprefix("ainerzero.learning.") for item in modules if item.startswith("ainerzero.learning.")}
        assert learning <= allowed
