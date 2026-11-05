"""S1 metric script tests: known answers and broken controls (pure CPU)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from ainerzero.v9.experiments.s1 import metrics, spec


def test_metric_ids_match_frozen_definitions():
    assert metrics.METRIC_IDS == tuple(row["id"] for row in spec.METRIC_DEFINITIONS)


# --- localization ---------------------------------------------------------
def test_localization_known_answer_and_broken_control():
    truth = np.array([[0, 0, 0, 0], [1, 0, 1, 10], [2, 0, 2, 20]], dtype=float)
    perfect = truth.copy()
    result = metrics.localization_error(perfect, truth)
    assert result["translation_mean_m"] == 0.0
    assert result["yaw_mean_deg"] == 0.0
    broken = truth.copy()
    broken[:, 0] += 0.3  # 0.3 m error every step
    broken[:, 3] += 5.0
    worse = metrics.localization_error(broken, truth)
    assert worse["translation_mean_m"] == pytest.approx(0.3)
    assert worse["yaw_mean_deg"] == pytest.approx(5.0)
    # Broken control must move the metric in the declared bad direction.
    assert worse["translation_mean_m"] > result["translation_mean_m"]
    assert worse["translation_rmse_m"] > result["translation_rmse_m"]


def test_localization_rejects_bad_shapes_and_nonfinite():
    with pytest.raises(ValueError):
        metrics.localization_error(np.zeros((2, 3)), np.zeros((2, 4)))
    with pytest.raises(ValueError):
        metrics.localization_error(np.zeros((0, 4)), np.zeros((0, 4)))
    bad = np.zeros((1, 4))
    bad[0, 0] = np.nan
    with pytest.raises(ValueError):
        metrics.localization_error(bad, np.zeros((1, 4)))


def test_loop_closure_known_answer():
    truth = np.array([[0, 0, 0, 0], [1, 0, 0, 0], [0, 0, 0, 0]], dtype=float)
    estimate = truth.copy()
    estimate[2, 0] = 0.4
    result = metrics.loop_closure_error(estimate, truth, loop_pairs=[(0, 2)])
    assert result["distance_error_mean_m"] == pytest.approx(0.4)
    assert result["yaw_error_mean_deg"] == 0.0


# --- prediction / unseen map ---------------------------------------------
def test_observation_prediction_known_answer_and_control():
    target = np.zeros((1, 10))
    target[0, 0:3] = [0.0, 0.0, 2.0]
    target[0, 3] = 1.0
    target[0, 4] = 1.0  # class 0
    prediction = np.zeros((1, 10))
    prediction[0, 0:3] = [0.0, 0.0, 2.0]
    prediction[0, 3] = 10.0
    prediction[0, 4] = 10.0
    result = metrics.observation_prediction_metrics(prediction, target)
    assert result["position_mse"] == pytest.approx(0.0)
    assert result["class_ce"] == pytest.approx(0.0, abs=1e-3)
    # Broken control: shift position and class -> both errors must grow.
    broken = prediction.copy()
    broken[0, 2] = 3.0
    broken[0, 4] = -10.0
    broken[0, 5] = 10.0
    worse = metrics.observation_prediction_metrics(broken, target)
    assert worse["position_mse"] == pytest.approx(1.0 / 3.0)
    assert worse["class_ce"] > result["class_ce"]


def test_unseen_map_generalization_known_answer():
    rows = [
        {"translation_mean_m": 0.2, "prediction_nll": 1.0, "family": "navigation"},
        {"translation_mean_m": 0.4, "prediction_nll": 2.0, "family": "navigation"},
        {"translation_mean_m": 0.6, "prediction_nll": 3.0, "family": "relation"},
    ]
    result = metrics.unseen_map_generalization(rows)
    assert result["translation_mean_m"] == pytest.approx(0.4)
    assert result["prediction_nll_mean"] == pytest.approx(2.0)
    assert result["by_family"] == {"navigation": pytest.approx(0.3), "relation": 0.6}
    with pytest.raises(ValueError):
        metrics.unseen_map_generalization([])


# --- topology -------------------------------------------------------------
def test_topology_perfect_recovery_and_three_broken_controls():
    cells = [(0, 0), (1, 0), (1, 1)]
    edges = [((0, 0), (1, 0)), ((1, 0), (1, 1))]
    nodes = [[0.0, 0.0], [1.0, 0.1], [1.1, 1.0]]
    perfect = metrics.topology_edge_metrics(nodes, [(0, 1), (1, 2)], cells, edges)
    assert perfect["precision"] == 1.0
    assert perfect["recall"] == 1.0
    # Missing edge -> recall drops.
    missing = metrics.topology_edge_metrics(nodes, [(0, 1)], cells, edges)
    assert missing["recall"] == pytest.approx(0.5)
    assert missing["precision"] == 1.0
    # Spurious diagonal edge -> precision drops (both endpoint cells are true cells).
    spurious = metrics.topology_edge_metrics(
        nodes,
        [(0, 1), (1, 2), (0, 2)],
        cells,
        edges,
    )
    assert spurious["precision"] < 1.0
    # Unmatched node -> its edge cannot count as true.
    unmatched = metrics.topology_edge_metrics(
        [[10.0, 10.0], [1.0, 0.0]], [(0, 1)], cells, edges
    )
    assert unmatched["precision"] == 0.0
    assert unmatched["unmatched_edges"] == 1


# --- few-shot transition --------------------------------------------------
def test_few_shot_transition_known_answer_and_control():
    truth = [True, True, False, False]
    good = [True, True, False, False]
    result = metrics.few_shot_transition_metrics(good, truth, [0.4, 0.5, 0.1, 0.1], [0.5, 0.5, 0.2, 0.2])
    assert result["accuracy"] == 1.0
    assert result["balanced_accuracy"] == 1.0
    assert result["displacement_mae_m"] == pytest.approx(0.05)
    flipped = [False, False, True, True]
    worse = metrics.few_shot_transition_metrics(flipped, truth)
    assert worse["accuracy"] == 0.0
    assert worse["balanced_accuracy"] == 0.0


# --- sample efficiency ----------------------------------------------------
def test_sample_efficiency_curve_known_answer_and_control():
    result = metrics.sample_efficiency_curve([(200, 1.0), (0, 3.0), (100, 2.0)])
    assert [row["updates"] for row in result["checkpoints"]] == [0, 100, 200]
    assert result["first"] == 3.0
    assert result["last"] == 1.0
    assert result["improvement"] == pytest.approx(2.0)
    assert result["best"] == {"updates": 200, "metric": 1.0}
    assert result["normalised_area"] == pytest.approx((3.0 + 2.0) / 2 * 100 / 200 + (2.0 + 1.0) / 2 * 100 / 200)
    # Broken control: a worse final metric shows less improvement.
    worse = metrics.sample_efficiency_curve([(0, 3.0), (100, 2.0), (200, 2.5)])
    assert worse["improvement"] < result["improvement"]
    with pytest.raises(ValueError):
        metrics.sample_efficiency_curve([])


# --- M2 interference ------------------------------------------------------
def test_memory_interference_known_answer_and_control():
    result = metrics.memory_interference(
        before={"nll": 1.0, "loc": 0.2},
        after={"nll": 1.25, "loc": 0.5},
        history_paired={"nll": 1.1},
        zero_state={"nll": 1.6},
    )
    assert result["retention_delta"] == {"loc": pytest.approx(0.3), "nll": pytest.approx(0.25)}
    assert result["worst_retention_delta"] == pytest.approx(0.3)
    assert result["zero_state_penalty"] == {"nll": pytest.approx(-0.5)}
    # Broken control: no degradation -> zero deltas (the metric is not constant-bad).
    clean = metrics.memory_interference(before={"nll": 1.0}, after={"nll": 1.0})
    assert clean["retention_delta"]["nll"] == 0.0
    with pytest.raises(ValueError):
        metrics.memory_interference(before={"nll": 1.0}, after={"other": 1.0})


def test_metric_suite_report_is_json_ready():
    report = metrics.metric_suite_report(
        localization=metrics.localization_error(np.zeros((2, 4)), np.zeros((2, 4))),
        unseen=metrics.unseen_map_generalization([{"translation_mean_m": 0.1, "prediction_nll": 1.0}]),
        topology=metrics.topology_edge_metrics([], [], [], []),
        few_shot=metrics.few_shot_transition_metrics([True], [True]),
        sample_efficiency=metrics.sample_efficiency_curve([(0, 1.0)]),
        interference=metrics.memory_interference(before={"nll": 1.0}, after={"nll": 1.0}),
        arm_id="arm2",
        seed=0,
    )
    assert report["arm_id"] == "arm2"
    assert report["topology_recovery"]["precision"] == 1.0
    assert math.isfinite(report["localization_error"]["translation_mean_m"])
