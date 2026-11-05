"""r10: evaluation.query_limit registration + option-A reporting notes (CPU).

P1-READINESS / P26: register ``evaluation.query_limit = 8``, read it from the
verified preregistration (no code-only default), refuse missing or different
values, and pin the option-A reporting notes without changing metrics[3].

Also pins the already-landed k=1 stop boundary (``stop = support[-1] + 2``) so
the r10 freeze carries an explicit regression for that repair.
"""

from __future__ import annotations

import copy
import inspect

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import evaluation, metrics, prereg, spec
from s1_testkit import frozen_document


def _broken_require_query_limit_missing_guard(document):
    """Isolated bad control: drop only the missing-key refuse, keep the value check.

    With the missing-key guard removed, a prereg that lacks ``query_limit`` falls
    back to the old code-only default of 8.  That is the r9 hole; the real
    ``require_query_limit`` must refuse instead.
    """
    evaluation_block = document.get("evaluation") if isinstance(document, dict) else None
    if not isinstance(evaluation_block, dict):
        evaluation_block = {}
    value = evaluation_block.get("query_limit", 8)  # DEFECT: silent default
    if isinstance(value, bool) or not isinstance(value, int):
        raise metrics.QueryLimitError(
            f"preregistration evaluation.query_limit must be an int, got {type(value).__name__}"
        )
    expected = int(spec.EVALUATION["query_limit"])
    if value != expected:
        raise metrics.QueryLimitError(
            f"preregistration evaluation.query_limit {value!r} differs from "
            f"the registered {expected}"
        )
    return expected


def test_draft_and_frozen_register_query_limit_and_reporting_notes():
    document = frozen_document()
    assert document["evaluation"]["query_limit"] == 8
    assert document["evaluation"]["reporting_notes"] == list(spec.EVALUATION["reporting_notes"])
    assert document["metrics"][3]["id"] == "few_shot_unseen_transition"
    assert prereg.validate(document) == []


def test_missing_query_limit_refuses():
    document = frozen_document()
    del document["evaluation"]["query_limit"]
    with pytest.raises(metrics.QueryLimitError, match="missing"):
        metrics.require_query_limit(document)
    reasons = prereg.validate(document)
    assert any("query_limit is missing" in reason for reason in reasons)


def test_different_query_limit_refuses():
    document = frozen_document()
    document["evaluation"]["query_limit"] = 4
    with pytest.raises(metrics.QueryLimitError, match="differs"):
        metrics.require_query_limit(document)
    with pytest.raises(metrics.QueryLimitError, match="differs"):
        metrics.split_support_query(9, 1, query_limit=4)
    reasons = prereg.validate(document)
    assert any("differs from the registered" in reason for reason in reasons)


def test_bad_control_missing_guard_turns_red():
    """Only the missing-key refuse is deleted; the bad control must wrongly accept."""
    document = frozen_document()
    del document["evaluation"]["query_limit"]
    with pytest.raises(metrics.QueryLimitError, match="missing"):
        metrics.require_query_limit(document)
    # Bad control turns red: missing key silently becomes 8.
    assert _broken_require_query_limit_missing_guard(document) == 8


def test_split_support_query_has_no_default_query_limit():
    parameters = inspect.signature(metrics.split_support_query).parameters
    assert parameters["query_limit"].default is inspect.Parameter.empty
    with pytest.raises(TypeError):
        metrics.split_support_query(9, 1)  # type: ignore[call-arg]


def test_few_shot_requires_prereg_or_explicit_registered_limit():
    with pytest.raises(metrics.QueryLimitError, match="requires preregistration"):
        evaluation.few_shot_report(object(), object(), [], [], k_values=(1,))


def test_k1_stop_boundary_is_support_last_plus_two():
    """Regression for the r5/r6 repair: exclusive stop must be support[-1] + 2."""

    class _StopBackend:
        def __init__(self):
            self.stops = []

        def step_sequence(self, model, sequence, *, stop=None, memory=None, pose=None):
            self.stops.append(int(stop))
            frames = int(stop)
            nodes = np.zeros((frames, 2), dtype=np.float64)
            return {
                "steps": [{"frame": i + 1, "loss": 0.0, "pose": np.zeros(4)} for i in range(frames - 1)],
                "memory": {
                    "nodes": nodes,
                    "positions": np.zeros((frames, 2)),
                    "edges": set(),
                    "threshold": 0.0,
                },
                "pose": np.zeros((1, 4)),
            }

        def probe_graph(self, model, memory, pose=None):
            return memory

        def encode(self, model, obs_row):
            return np.asarray(obs_row, dtype=np.float64)

        # r15 (ainerzero.V9.P53): few-shot queries through probe_query (same space here).
        def probe_query(self, model, obs_row):
            return self.encode(model, obs_row)

    poses = [(float(i), 0, 0, 0) for i in range(6)]
    steps = []
    for index, pose in enumerate(poses):
        steps.append(
            {
                "seq": index,
                "tick": index * 3,
                "agent_world_pose": {
                    "position": [pose[0], pose[1], pose[2]],
                    "yaw_deg": pose[3],
                },
            }
        )
    from ainerzero.v9.experiments.s1 import data

    episode = data.TruthEpisode(
        episode_id="K1",
        partition="development",
        family="navigation",
        scene_id="scene-K1",
        world={"width": 16, "height": 16, "blocked": []},
        steps=tuple(steps),
    )
    sequence = {"episode_id": "K1", "obs": np.ones((6, 2), dtype=np.float32)}
    backend = _StopBackend()
    report = evaluation.few_shot_report(
        backend,
        object(),
        [sequence],
        [episode],
        k_values=(1,),
        query_limit=8,
    )
    # k=1 → support=[0] → stop = 0 + 2 = 2 (r5 used +1 and crashed).
    assert backend.stops == [2]
    assert "1" in report["curve"] or "1" in report.get("unavailable", {})


def test_reporting_notes_tamper_fails_validate():
    document = frozen_document()
    document["evaluation"]["reporting_notes"] = list(document["evaluation"]["reporting_notes"]) + [
        "extra"
    ]
    reasons = prereg.validate(document)
    assert any("reporting_notes" in reason for reason in reasons)


def test_option_a_notes_do_not_alter_metric_definition():
    document = frozen_document()
    baseline = copy.deepcopy(spec.METRIC_DEFINITIONS[3])
    assert document["metrics"][3] == dict(baseline)
    assert "coverage" not in document["metrics"][3]["definition"].lower()
    assert "fpr" not in document["metrics"][3]["definition"].lower()
