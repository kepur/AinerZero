"""S1 metric computations (pure numpy; the frozen definitions live in spec).

Every function here is deterministic, side-effect free, and unit-tested with
synthetic cases that have a known answer plus a broken control (mutating the
prediction must move the metric in the declared bad direction).  The metrics are
the registered S1 phase-1 set:

- localization error (translation/yaw, loop-closure segment separately),
- unseen-map generalization (development/final localization + prediction NLL),
- topology edge precision/recall under confounded observations,
- few-experience unseen-transition accuracy / displacement error,
- sample-efficiency curve.
- M2 memory-interference delta (zero-state vs history-paired, retention).

None of these functions touches a model runtime or the sealed final partition;
they consume arrays produced by the arms/evaluator and the truth view.
"""

from __future__ import annotations

import math
from typing import Iterable, Mapping, Sequence

import numpy as np

from . import spec

METRIC_IDS = tuple(row["id"] for row in spec.METRIC_DEFINITIONS)


def _as_array(value, *, columns: int | None = None, name: str = "array") -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or (columns is not None and array.shape[1] != columns):
        raise ValueError(f"{name} must be a 2-D array with {columns} columns")
    if not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite")
    return array


def wrap_degrees(value):
    return (np.asarray(value, dtype=np.float64) + 180.0) % 360.0 - 180.0


# --- 1. localization ------------------------------------------------------
def localization_error(pose_estimate, pose_truth) -> dict:
    """Pose belief vs evaluator truth: x/z translation (m) and yaw (deg)."""
    estimate = _as_array(pose_estimate, columns=4, name="pose_estimate")
    truth = _as_array(pose_truth, columns=4, name="pose_truth")
    if estimate.shape != truth.shape:
        raise ValueError("pose estimate and truth must have the same shape")
    if len(estimate) == 0:
        raise ValueError("localization_error needs at least one step")
    translation = np.hypot(estimate[:, 0] - truth[:, 0], estimate[:, 2] - truth[:, 2])
    yaw = np.abs(wrap_degrees(estimate[:, 3] - truth[:, 3]))
    return {
        "steps": int(len(translation)),
        "translation_mean_m": float(np.mean(translation)),
        "translation_median_m": float(np.median(translation)),
        "translation_rmse_m": float(np.sqrt(np.mean(translation**2))),
        "translation_max_m": float(np.max(translation)),
        "yaw_mean_deg": float(np.mean(yaw)),
        "yaw_median_deg": float(np.median(yaw)),
        "yaw_max_deg": float(np.max(yaw)),
    }


def loop_closure_error(pose_estimate, pose_truth, *, loop_pairs: Sequence[tuple[int, int]]) -> dict:
    """Extra localization diagnostics on a frozen set of loop-closure step pairs."""
    estimate = _as_array(pose_estimate, columns=4, name="pose_estimate")
    truth = _as_array(pose_truth, columns=4, name="pose_truth")
    if not loop_pairs:
        raise ValueError("loop_pairs must be non-empty for the loop-closure metric")
    rows = []
    for first, second in loop_pairs:
        if not (0 <= first < len(estimate) and 0 <= second < len(estimate)):
            raise IndexError("loop pair step index outside the episode")
        est = np.hypot(
            estimate[second, 0] - estimate[first, 0], estimate[second, 2] - estimate[first, 2]
        )
        tru = np.hypot(truth[second, 0] - truth[first, 0], truth[second, 2] - truth[first, 2])
        yaw = abs(float(wrap_degrees(estimate[second, 3] - truth[second, 3])))
        rows.append(
            {
                "pair": [int(first), int(second)],
                "distance_error_m": float(est - tru),
                "yaw_error_deg": yaw,
            }
        )
    return {
        "pairs": len(rows),
        "distance_error_mean_m": float(np.mean([row["distance_error_m"] for row in rows])),
        "yaw_error_mean_deg": float(np.mean([row["yaw_error_deg"] for row in rows])),
        "details": rows,
    }


# --- 2. prediction error / unseen-map generalisation ----------------------
def observation_prediction_metrics(prediction, target) -> dict:
    """Next-observation prediction error; masks absent slots like the training loss."""
    predicted = np.asarray(prediction, dtype=np.float64).reshape((-1, 10))
    truth = np.asarray(target, dtype=np.float64).reshape((-1, 10))
    if predicted.shape != truth.shape:
        raise ValueError("prediction and target must have the same number of slots")
    present = truth[:, 3] > 0.5
    if np.any(present):
        position_mse = float(
            np.sum((predicted[present, 0:3] - truth[present, 0:3]) ** 2)
            / (3.0 * float(np.sum(present)))
        )
    else:
        # No present slot carries no position signal; report null rather than 0.
        position_mse = None
    logit = np.clip(predicted[:, 3], -60.0, 60.0)
    label = truth[:, 3]
    presence_bce = float(np.mean(np.maximum(logit, 0.0) - logit * label + np.log1p(np.exp(-np.abs(logit)))))
    if np.any(present):
        class_logits = predicted[present, 4:]
        labels = np.argmax(truth[present, 4:], axis=-1)
        shifted = class_logits - class_logits.max(axis=-1, keepdims=True)
        log_probs = shifted - np.log(np.sum(np.exp(shifted), axis=-1, keepdims=True))
        class_ce = float(-np.mean(log_probs[np.arange(len(labels)), labels]))
    else:
        class_ce = None
    return {
        "slots": int(len(predicted)),
        "present_slots": int(np.sum(present)),
        "position_mse": position_mse,
        "presence_bce": presence_bce,
        "class_ce": class_ce,
    }


def unseen_map_generalization(per_episode: Iterable[Mapping]) -> dict:
    """Aggregate development/final metric rows over unseen worlds.

    Each row must provide ``translation_mean_m`` and ``prediction_nll``; rows may
    also provide ``family`` so the report shows all arena families.
    """
    rows = list(per_episode)
    if not rows:
        raise ValueError("unseen_map_generalization needs at least one episode row")
    required = ("translation_mean_m", "prediction_nll")
    for row in rows:
        missing = [key for key in required if key not in row]
        if missing:
            raise ValueError(f"episode row is missing {missing}")
    translation = np.asarray([row["translation_mean_m"] for row in rows], dtype=np.float64)
    nll = np.asarray([row["prediction_nll"] for row in rows], dtype=np.float64)
    families: dict[str, list[float]] = {}
    for row in rows:
        families.setdefault(str(row.get("family", "unknown")), []).append(
            float(row["translation_mean_m"])
        )
    return {
        "episodes": len(rows),
        "translation_mean_m": float(np.mean(translation)),
        "translation_median_m": float(np.median(translation)),
        "prediction_nll_mean": float(np.mean(nll)),
        "prediction_nll_median": float(np.median(nll)),
        "by_family": {key: float(np.mean(values)) for key, values in sorted(families.items())},
    }


# --- 3. topology recovery -------------------------------------------------
def _nearest_cell(position: Sequence[float], cells: Sequence[tuple[int, int]], tolerance_m: float):
    x, z = float(position[0]), float(position[1])
    best = None
    best_distance = math.inf
    for cell in cells:
        distance = math.hypot(x - cell[0], z - cell[1])
        if distance < best_distance:
            best, best_distance = cell, distance
    if best is None or best_distance > tolerance_m:
        return None
    return best


def topology_edge_metrics(
    predicted_nodes: Sequence[Sequence[float]],
    predicted_edges: Iterable[tuple[int, int]],
    true_visited_cells: Sequence[tuple[int, int]],
    true_edges: Iterable[tuple[tuple[int, int], tuple[int, int]]],
    *,
    match_tolerance_m: float = 0.75,
) -> dict:
    """Edge precision/recall of the arm's place graph against visited-cell truth.

    Node ids are matched to the nearest true visited cell; unmatched nodes count
    as false positives (their edges cannot be true edges of the map).
    """
    cells = [tuple(int(value) for value in cell) for cell in true_visited_cells]
    truth_edges = {
        tuple(sorted((tuple(map(int, first)), tuple(map(int, second)))))
        for first, second in true_edges
    }
    nodes = list(predicted_nodes)
    mapping: dict[int, tuple[int, int] | None] = {}
    for index, position in enumerate(nodes):
        if len(position) < 2:
            raise ValueError("predicted node positions need at least x/z")
        mapping[index] = _nearest_cell((position[0], position[1]), cells, match_tolerance_m)
    predicted = set()
    unmatched_edges = 0
    for first, second in predicted_edges:
        first_cell, second_cell = mapping[int(first)], mapping[int(second)]
        if first_cell is None or second_cell is None:
            unmatched_edges += 1
            continue
        if first_cell == second_cell:
            continue
        predicted.add(tuple(sorted((first_cell, second_cell))))
    true_positive = len(predicted & truth_edges)
    precision = true_positive / len(predicted) if predicted else (1.0 if not truth_edges else 0.0)
    recall = true_positive / len(truth_edges) if truth_edges else (1.0 if not predicted else 0.0)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return {
        "predicted_nodes": len(nodes),
        "matched_nodes": sum(1 for value in mapping.values() if value is not None),
        "predicted_edges": len(predicted),
        "unmatched_edges": unmatched_edges,
        "true_edges": len(truth_edges),
        "true_positive_edges": true_positive,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
    }


# --- 4. few-experience transition prediction ------------------------------
def few_shot_transition_metrics(
    predicted_exists: Sequence[bool],
    true_exists: Sequence[bool],
    predicted_displacement_m: Sequence[float] | None = None,
    true_displacement_m: Sequence[float] | None = None,
) -> dict:
    """Held-out transition existence accuracy and displacement error."""
    predicted = np.asarray(predicted_exists, dtype=bool)
    truth = np.asarray(true_exists, dtype=bool)
    if predicted.shape != truth.shape or predicted.ndim != 1 or len(predicted) == 0:
        raise ValueError("predicted_exists and true_exists must be equal non-empty 1-D arrays")
    accuracy = float(np.mean(predicted == truth))
    positives = truth.astype(bool)
    if np.any(positives) and np.any(~positives):
        recall = float(np.mean(predicted[positives]))
        precision = float(np.mean(truth[predicted])) if np.any(predicted) else 0.0
        balanced = 0.5 * (recall + float(np.mean(~predicted[~positives])))
    else:
        recall = float(np.mean(predicted == truth))
        precision = recall
        balanced = accuracy
    result = {
        "transitions": int(len(predicted)),
        "accuracy": accuracy,
        "balanced_accuracy": float(balanced),
        "positive_recall": recall,
        "positive_precision": float(precision),
    }
    if predicted_displacement_m is not None or true_displacement_m is not None:
        if predicted_displacement_m is None or true_displacement_m is None:
            raise ValueError("displacement error needs both predicted and true values")
        predicted_m = np.asarray(predicted_displacement_m, dtype=np.float64)
        true_m = np.asarray(true_displacement_m, dtype=np.float64)
        if predicted_m.shape != true_m.shape or predicted_m.ndim != 1:
            raise ValueError("displacement arrays must share a 1-D shape")
        if len(predicted_m) != len(predicted):
            raise ValueError("displacement arrays must cover every transition")
        mask = truth
        if np.any(mask):
            result["displacement_mae_m"] = float(
                np.mean(np.abs(predicted_m[mask] - true_m[mask]))
            )
        else:
            result["displacement_mae_m"] = None
    return result


# --- 5. sample-efficiency curve ------------------------------------------
def sample_efficiency_curve(checkpoints: Iterable[tuple[int, float]]) -> dict:
    """Metric-vs-updates curve plus a trapezoidal area (lower is better)."""
    rows = sorted((int(step), float(value)) for step, value in checkpoints)
    if not rows:
        raise ValueError("sample_efficiency_curve needs at least one checkpoint")
    if len({step for step, _ in rows}) != len(rows):
        raise ValueError("checkpoint update counts must be unique")
    if any(step < 0 for step, _ in rows):
        raise ValueError("checkpoint update counts must be nonnegative")
    if any(not math.isfinite(value) for _, value in rows):
        raise ValueError("curve values must be finite")
    steps = np.asarray([row[0] for row in rows], dtype=np.float64)
    values = np.asarray([row[1] for row in rows], dtype=np.float64)
    area = (
        float(np.trapezoid(values, steps) / max(steps[-1] - steps[0], 1.0))
        if len(rows) > 1
        else float(values[0])
    )
    best_step, best_value = min(rows, key=lambda row: row[1])
    return {
        "checkpoints": [{"updates": step, "metric": value} for step, value in rows],
        "first": float(values[0]),
        "last": float(values[-1]),
        "best": {"updates": int(best_step), "metric": float(best_value)},
        "improvement": float(values[0] - values[-1]),
        "normalised_area": area,
    }


# --- 6. M2 memory interference -------------------------------------------
def memory_interference(
    *,
    before: Mapping[str, float],
    after: Mapping[str, float],
    history_paired: Mapping[str, float] | None = None,
    zero_state: Mapping[str, float] | None = None,
) -> dict:
    """Retention delta after writing new memories (no parameter updates)."""
    keys = sorted(set(before) & set(after))
    if not keys:
        raise ValueError("before and after metrics share no keys")
    deltas = {key: float(after[key]) - float(before[key]) for key in keys}
    result = {
        "retention_delta": deltas,
        "worst_retention_delta": max(deltas.values()),
        "keys": keys,
    }
    if history_paired is not None and zero_state is not None:
        shared = sorted(set(history_paired) & set(zero_state))
        if not shared:
            raise ValueError("history/zero-state probes share no metric keys")
        result["zero_state_penalty"] = {
            key: float(history_paired[key]) - float(zero_state[key]) for key in shared
        }
    return result


def metric_suite_report(
    *,
    localization: Mapping,
    unseen: Mapping,
    topology: Mapping,
    few_shot: Mapping,
    sample_efficiency: Mapping,
    interference: Mapping,
    arm_id: str,
    seed: int,
) -> dict:
    """One JSON-ready row for the P1/P2 evaluator; not executed in P9."""
    return {
        "arm_id": arm_id,
        "seed": int(seed),
        "localization_error": dict(localization),
        "unseen_map_generalization": dict(unseen),
        "topology_recovery": dict(topology),
        "few_shot_unseen_transition": dict(few_shot),
        "sample_efficiency": dict(sample_efficiency),
        "m2_memory_interference": dict(interference),
    }
