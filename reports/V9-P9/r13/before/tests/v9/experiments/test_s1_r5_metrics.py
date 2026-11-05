"""r5 metric counterexamples (CPU only).

These tests do not prove scientific capability.  They prove that the frozen
aggregates consume identity-aligned episode/world/tick rows, that a wrong or
confused prediction changes the number, and that a missing sample fails closed
instead of being reported as a perfect zero.
"""

from __future__ import annotations

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import data, evaluation, metrics


def _episode(episode_id: str, scene_id: str, family: str, poses, *, tick_step: int = 3):
    steps = []
    for index, pose in enumerate(poses):
        steps.append(
            {
                "seq": index,
                "tick": index * tick_step,
                "agent_world_pose": {
                    "position": [float(pose[0]), float(pose[1]), float(pose[2])],
                    "yaw_deg": float(pose[3]),
                },
            }
        )
    return data.TruthEpisode(
        episode_id=episode_id,
        partition="development",
        family=family,
        scene_id=scene_id,
        world={"width": 16, "height": 16, "blocked": []},
        steps=tuple(steps),
    )


def _probe_rows():
    # Episode A has three scored windows, episode B only one.  A min-length
    # truncation (the r4 defect) would silently drop two of A's rows.
    return {
        "rows": [
            {"episode_id": "A", "start": 0, "pose": np.zeros(4), "loss": 0.3, "parts": {"presence": 0.1, "class": 0.2}},
            {"episode_id": "A", "start": 1, "pose": np.zeros(4), "loss": 0.3, "parts": {"presence": 0.1, "class": 0.2}},
            {"episode_id": "A", "start": 2, "pose": np.zeros(4), "loss": 0.3, "parts": {"presence": 0.1, "class": 0.2}},
            {"episode_id": "B", "start": 0, "pose": np.zeros(4), "loss": 0.3, "parts": {"presence": 0.1, "class": 0.2}},
        ],
        "batches": 2,
        "windows": 4,
    }


def test_development_rows_keeps_every_episode_and_tick():
    truth = [
        _episode("A", "scene-A", "navigation", [(0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0), (3, 0, 0, 0)]),
        _episode("B", "scene-B", "relation", [(5, 0, 5, 0), (6, 0, 5, 0)]),
    ]
    rows = evaluation.development_rows(_probe_rows(), truth)
    report = evaluation.localization_report(rows)
    assert report["unseen"]["episodes"] == 2
    assert report["unseen"]["worlds"] == 2
    assert sorted(report["unseen"]["by_family"]) == ["navigation", "relation"]
    by_id = {row["episode_id"]: row for row in rows}
    assert by_id["A"]["steps"] == 3
    assert by_id["A"]["ticks"] == [3, 6, 9]
    assert by_id["B"]["steps"] == 1
    assert by_id["A"]["prediction_nll"] == pytest.approx(0.3)
    # The zero relative pose is anchored to the truth pose of the same start tick,
    # so the one-step error is exactly the true motion, not a min-truncated match.
    assert by_id["A"]["translation_mean_m"] == pytest.approx(1.0)
    assert by_id["B"]["translation_mean_m"] == pytest.approx(1.0)


def test_development_rows_rejects_duplicate_ticks_and_unknown_episode():
    truth = [
        _episode(
            "A",
            "scene-A",
            "navigation",
            [(0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0), (3, 0, 0, 0)],
            tick_step=0,
        )
    ]
    a_only = {"rows": [row for row in _probe_rows()["rows"] if row["episode_id"] == "A"]}
    with pytest.raises((metrics.MetricIdentityError, evaluation.EvaluationError)):
        evaluation.development_rows(a_only, truth)
    unknown = {"rows": [_probe_rows()["rows"][0]]}
    with pytest.raises(evaluation.EvaluationError):
        evaluation.development_rows(
            unknown, [_episode("Z", "scene-Z", "time", [(0, 0, 0, 0)])]
        )


def test_strict_unseen_map_requires_identity_and_a_real_nll():
    good = {
        "episode_id": "A",
        "scene_id": "scene-A",
        "family": "navigation",
        "ticks": [1],
        "translation_mean_m": 0.5,
        "yaw_mean_deg": 1.0,
        "prediction_nll": 0.4,
    }
    assert metrics.strict_unseen_map([good])["episodes"] == 1
    for field in ("episode_id", "scene_id", "family"):
        broken = dict(good)
        broken[field] = ""
        with pytest.raises(metrics.MetricIdentityError):
            metrics.strict_unseen_map([broken])
    missing_nll = dict(good)
    missing_nll["prediction_nll"] = None
    with pytest.raises(metrics.MetricIdentityError):
        metrics.strict_unseen_map([missing_nll])
    with pytest.raises(metrics.MetricIdentityError):
        metrics.strict_unseen_map([good, good])


def test_topology_is_per_family_not_first_episode():
    rows = [
        {"episode_id": "A", "scene_id": "scene-A", "family": "navigation", "precision": 1.0, "recall": 1.0, "f1": 1.0},
        {"episode_id": "B", "scene_id": "scene-B", "family": "relation", "precision": 0.0, "recall": 0.0, "f1": 0.0},
    ]
    report = metrics.topology_report(rows)
    assert report["precision"] == pytest.approx(0.5)
    assert report["by_family"]["navigation"]["precision"] == pytest.approx(1.0)
    assert report["by_family"]["relation"]["precision"] == pytest.approx(0.0)
    with pytest.raises(metrics.MetricIdentityError):
        metrics.topology_report([rows[0], rows[0]])


def test_topology_edges_follow_the_prediction():
    cells = [(0, 0), (1, 0), (2, 0)]
    truth_edges = [((0, 0), (1, 0))]
    correct = metrics.topology_edge_metrics(cells, [(0, 1)], cells, truth_edges)
    wrong = metrics.topology_edge_metrics(cells, [(0, 2)], cells, truth_edges)
    assert correct["precision"] == pytest.approx(1.0)
    assert wrong["precision"] == pytest.approx(0.0)


def test_few_shot_k_is_traversed_and_missing_support_fails_closed():
    assert metrics.split_support_query(4, 4, query_limit=8) == ([], [])
    assert metrics.split_support_query(5, 4, query_limit=8) == ([0, 1, 2, 3], [4])
    assert metrics.split_support_query(9, 8, query_limit=8) == (list(range(8)), [8])
    present = metrics.few_shot_transition_metrics(
        predicted_exists=[True, False], true_exists=[True, False]
    )
    inverted = metrics.few_shot_transition_metrics(
        predicted_exists=[False, True], true_exists=[True, False]
    )
    assert present["accuracy"] == pytest.approx(1.0)
    assert inverted["accuracy"] == pytest.approx(0.0)
    report = metrics.few_shot_report(
        [
            {"k": 2, "queries": 2, "support": 2, "worlds": 1, **present},
            {"k": 8, "queries": 0, "support": 8, "worlds": 0, "reason": "no query"},
        ]
    )
    assert report["curve"]["2"]["accuracy"] == pytest.approx(1.0)
    assert report["unavailable"]["8"]["status"] == "insufficient_data"
    with pytest.raises(metrics.MetricIdentityError):
        metrics.few_shot_report([{"k": 8, "queries": 0, "reason": "no query"}])


def test_sample_efficiency_needs_both_curves():
    report = metrics.sample_efficiency_dual(
        [
            {"updates": 0, "development_nll": 2.0, "localization_translation_mean_m": 1.0},
            {"updates": 10, "development_nll": 1.0, "localization_translation_mean_m": 0.5},
        ]
    )
    assert report["nll_curve"]["improvement"] > 0
    assert report["localization_curve"]["improvement"] > 0
    with pytest.raises(metrics.MetricIdentityError):
        metrics.sample_efficiency_dual([{"updates": 0, "development_nll": 2.0}])


class _ProbeBackend:
    """Memory changes the probe loss; a step may also change parameters."""

    name = "metric-counterexample"

    def __init__(self, *, mutate_parameters: bool = False):
        self.mutate_parameters = mutate_parameters
        self.version = 0

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        if self.mutate_parameters:
            self.version += 1
        frames = len(sequence["obs"]) if stop is None else int(stop)
        if memory is None:
            loss = 1.0
            current = {"bias": 0.0}
        else:
            loss = float(memory["bias"])
            current = {"bias": float(memory["bias"])}
        steps = []
        for index in range(frames - 1):
            steps.append(
                {
                    "frame": index + 1,
                    "loss": loss,
                    "pose": np.zeros(4),
                    "predictions": None,
                    "parts": {"presence": loss, "class": 0.0},
                }
            )
        return {"steps": steps, "memory": current, "pose": np.zeros((1, 4))}

    def parameter_sha256(self, model):
        return f"params-{self.version}"


def _sequence(episode_id: str, length: int = 3):
    return {
        "episode_id": episode_id,
        "obs": np.zeros((length, 1), dtype=np.float32),
    }


def test_m2_interference_changes_with_memory_and_rejects_parameter_updates():
    truth = [_episode("P", "s-P", "time", [(0, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0)])]
    backend = _ProbeBackend()
    # History/new-world writes are represented by the backend's memory bias.
    original = backend.step_sequence

    def step(model, sequence, *, stop=None, memory=None, pose=None):
        run = original(model, sequence, stop=stop, memory=memory, pose=pose)
        if sequence["episode_id"] == "H":
            run["memory"] = {"bias": 0.5}
        if sequence["episode_id"] == "N" and memory is not None:
            memory["bias"] = 0.75
        return run

    backend.step_sequence = step
    report = evaluation.m2_interference(
        backend,
        object(),
        [_sequence("P")],
        truth,
        _sequence("H"),
        _sequence("N"),
    )
    assert report["zero_state"]["development_nll"] == pytest.approx(1.0)
    assert report["history_paired"]["development_nll"] == pytest.approx(0.5)
    assert report["after_new_world"]["development_nll"] == pytest.approx(0.75)
    assert report["probe"]["parameter_sha256_before"] == report["probe"]["parameter_sha256_after"]

    mutating = _ProbeBackend(mutate_parameters=True)
    with pytest.raises(evaluation.EvaluationError):
        evaluation.m2_interference(
            mutating, object(), [_sequence("P")], truth, _sequence("H"), _sequence("N")
        )


class _PathBackend:
    """Graph over the frames actually processed; zero threshold always matches."""

    name = "fewshot-path-counterexample"

    def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
        frames = len(sequence["obs"]) if stop is None else int(stop)
        nodes = np.asarray(sequence["obs"][:frames], dtype=np.float64)
        graph = {
            "nodes": nodes,
            "positions": np.zeros((frames, 2)),
            "edges": {(index, index + 1) for index in range(frames - 1)},
            "threshold": 0.0,
        }
        steps = [
            {
                "frame": index + 1,
                "loss": 0.5,
                "pose": np.zeros(4),
                "predictions": None,
                "parts": {"presence": 0.1, "class": 0.1},
            }
            for index in range(frames - 1)
        ]
        return {"steps": steps, "memory": graph, "pose": np.zeros((1, 4))}

    def probe_graph(self, model, memory, pose=None):
        return memory

    def encode(self, model, obs_row):
        return np.asarray(obs_row, dtype=np.float64)


def test_few_shot_uses_the_per_step_cell_path_when_the_agent_stays_put():
    # Consecutive stays: relative_cells() dedups to 3 entries but the last query
    # transition index is 4.  A deduped list indexed by a step number raises
    # IndexError on the real development split (found by the r5 evidence run).
    poses = [(0, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0), (1, 0, 0, 0), (2, 0, 0, 0), (2, 0, 0, 0)]
    episode = _episode("R", "scene-R", "navigation", poses)
    assert len(evaluation.relative_cell_path(episode)) == 6
    assert len(evaluation.relative_cells(episode)) == 3
    sequence = {"episode_id": "R", "obs": np.ones((6, 2), dtype=np.float32)}
    report = evaluation.few_shot_report(
        _PathBackend(),
        object(),
        [sequence],
        [episode],
        k_values=(2, 4),
        query_limit=8,
    )
    assert report["curve"]["2"]["by_world"]["R"]["target_ticks"] == [9, 12, 15]
    assert report["curve"]["4"]["by_world"]["R"]["target_ticks"] == [15]


def test_development_rows_maps_loop_pairs_from_per_step_cells():
    poses = [(0, 0, 0, 0), (1, 0, 0, 0), (0, 0, 0, 0), (1, 0, 0, 0)]
    episode = _episode("L", "scene-L", "navigation", poses)
    probe = {
        "rows": [
            {
                "episode_id": "L",
                "start": start,
                "pose": np.zeros(4),
                "loss": 0.3,
                "parts": {"presence": 0.1, "class": 0.2},
            }
            for start in (0, 1, 2)
        ]
    }
    row = evaluation.development_rows(probe, [episode])[0]
    # Revisit pairs (0,2) and (1,3) exist in the per-step path; only (1,3) is
    # fully scored (targets 1,2,3), so it must be reported with its tick pair.
    assert row["loop_closure"]["pairs"] == 1
