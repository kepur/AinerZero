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


class QueryLimitError(ValueError):
    """Preregistration ``evaluation.query_limit`` is missing or not the registered value."""


def require_query_limit(document: Mapping) -> int:
    """Read ``evaluation.query_limit`` from a verified preregistration (fail closed).

    Missing key, wrong type, or a value other than the registered ``spec.EVALUATION``
    entry refuses.  There is no default fallback: a code-only ``query_limit=8`` was
    the r9 hole closed by P26.
    """
    evaluation = document.get("evaluation") if isinstance(document, Mapping) else None
    if not isinstance(evaluation, Mapping) or "query_limit" not in evaluation:
        raise QueryLimitError("preregistration evaluation.query_limit is missing")
    value = evaluation["query_limit"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise QueryLimitError(
            f"preregistration evaluation.query_limit must be an int, got {type(value).__name__}"
        )
    expected = int(spec.EVALUATION["query_limit"])
    if value != expected:
        raise QueryLimitError(
            f"preregistration evaluation.query_limit {value!r} differs from "
            f"the registered {expected}"
        )
    return expected


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


# --- 7. r5 identity-aligned aggregates ------------------------------------
class MetricIdentityError(ValueError):
    """A metric row is missing its episode/world/tick identity or is ambiguous."""


def _require_identity(row: Mapping, fields: Iterable[str]) -> None:
    for field in fields:
        if field not in row or row[field] in (None, ""):
            raise MetricIdentityError(f"metric row is missing identity field {field!r}")


def revisit_pairs(cells: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """First non-consecutive revisit pair for every repeated true cell."""
    seen: dict[tuple[int, int], int] = {}
    pairs: list[tuple[int, int]] = []
    used: set[tuple[int, int]] = set()
    for index, cell in enumerate(cells):
        key = (int(cell[0]), int(cell[1]))
        if key in seen and index - seen[key] > 1 and key not in used:
            pairs.append((seen[key], index))
            used.add(key)
        seen.setdefault(key, index)
    return pairs


def episode_localization_row(
    *,
    episode_id: str,
    scene_id: str,
    family: str,
    ticks: Sequence[int],
    estimate,
    truth,
    prediction_nll: float | None = None,
    loop_pairs: Sequence[tuple[int, int]] | None = None,
) -> dict:
    """One identity-checked episode row for localization / unseen-map scoring.

    The estimate must already be expressed in the evaluator frame by the
    documented per-episode anchor transform; this function only checks that the
    tick list is unique and that estimate and truth cover exactly those ticks.
    """
    if not episode_id or not scene_id or not family:
        raise MetricIdentityError("episode_id, scene_id and family are required")
    tick_list = [int(value) for value in ticks]
    if not tick_list:
        raise MetricIdentityError(f"episode {episode_id} has no scored ticks")
    if len(set(tick_list)) != len(tick_list):
        raise MetricIdentityError(f"episode {episode_id} repeats a tick in the scored set")
    localization = localization_error(estimate, truth)
    row = {
        "episode_id": str(episode_id),
        "scene_id": str(scene_id),
        "family": str(family),
        "ticks": tick_list,
        "ticks_unique": True,
        "steps": localization["steps"],
        "translation_mean_m": localization["translation_mean_m"],
        "translation_median_m": localization["translation_median_m"],
        "yaw_mean_deg": localization["yaw_mean_deg"],
        "prediction_nll": None if prediction_nll is None else float(prediction_nll),
    }
    if loop_pairs:
        row["loop_closure"] = loop_closure_error(estimate, truth, loop_pairs=loop_pairs)
    return row


def strict_unseen_map(rows: Iterable[Mapping]) -> dict:
    """Per-episode / per-world / per-family unseen-map report (frozen rule 3).

    Unlike :func:`unseen_map_generalization` (kept for the r4 unit tests), this
    refuses rows without episode and world identity, repeated episodes, or a
    missing NLL.  No row may stand in for the whole library.
    """
    collected = list(rows)
    if not collected:
        raise MetricIdentityError("unseen_map needs at least one episode row")
    seen_episodes: set[str] = set()
    families: dict[str, list[dict]] = {}
    for row in collected:
        _require_identity(row, ("episode_id", "scene_id", "family", "ticks"))
        if "translation_mean_m" not in row or "yaw_mean_deg" not in row:
            raise MetricIdentityError("unseen_map row is missing its localization values")
        if row.get("prediction_nll") is None:
            raise MetricIdentityError(
                f"episode {row['episode_id']} has no next-observation NLL; null is not zero"
            )
        episode_id = str(row["episode_id"])
        if episode_id in seen_episodes:
            raise MetricIdentityError(f"episode {episode_id} appears twice in the unseen map")
        seen_episodes.add(episode_id)
        families.setdefault(str(row["family"]), []).append(row)
    translation = np.asarray([float(row["translation_mean_m"]) for row in collected])
    yaw = np.asarray([float(row["yaw_mean_deg"]) for row in collected])
    nll = np.asarray([float(row["prediction_nll"]) for row in collected])
    by_family = {}
    for family, family_rows in sorted(families.items()):
        by_family[family] = {
            "episodes": len(family_rows),
            "worlds": len({row["scene_id"] for row in family_rows}),
            "translation_mean_m": float(
                np.mean([float(row["translation_mean_m"]) for row in family_rows])
            ),
            "yaw_mean_deg": float(np.mean([float(row["yaw_mean_deg"]) for row in family_rows])),
            "prediction_nll_mean": float(
                np.mean([float(row["prediction_nll"]) for row in family_rows])
            ),
        }
    by_world = {}
    for row in collected:
        key = str(row["scene_id"])
        by_world.setdefault(key, {"episodes": 0, "families": set()})
        by_world[key]["episodes"] += 1
        by_world[key]["families"].add(str(row["family"]))
    return {
        "episodes": len(collected),
        "worlds": len(by_world),
        "translation_mean_m": float(np.mean(translation)),
        "translation_median_m": float(np.median(translation)),
        "yaw_mean_deg": float(np.mean(yaw)),
        "prediction_nll_mean": float(np.mean(nll)),
        "prediction_nll_median": float(np.median(nll)),
        "by_family": by_family,
        "by_world": {
            key: {"episodes": value["episodes"], "families": sorted(value["families"])}
            for key, value in sorted(by_world.items())
        },
        "alignment_rule": "per episode, model pose is anchored to the evaluator truth pose "
        "of the same window's first tick; scored ticks are unique and listed per episode",
    }


def topology_report(rows: Iterable[Mapping]) -> dict:
    """Aggregate per-episode/per-world topology rows; no library-wide family label."""
    collected = list(rows)
    if not collected:
        raise MetricIdentityError("topology report needs at least one episode row")
    seen: set[str] = set()
    families: dict[str, list[dict]] = {}
    for row in collected:
        _require_identity(row, ("episode_id", "scene_id", "family", "precision", "recall"))
        episode_id = str(row["episode_id"])
        if episode_id in seen:
            raise MetricIdentityError(f"episode {episode_id} appears twice in topology")
        seen.add(episode_id)
        families.setdefault(str(row["family"]), []).append(row)
    def _mean(key: str) -> float:
        return float(np.mean([float(row[key]) for row in collected]))
    by_family = {
        family: {
            "episodes": len(family_rows),
            "precision": float(np.mean([float(row["precision"]) for row in family_rows])),
            "recall": float(np.mean([float(row["recall"]) for row in family_rows])),
            "f1": float(np.mean([float(row["f1"]) for row in family_rows])),
        }
        for family, family_rows in sorted(families.items())
    }
    return {
        "episodes": len(collected),
        "worlds": len({row["scene_id"] for row in collected}),
        "precision": _mean("precision"),
        "recall": _mean("recall"),
        "f1": _mean("f1"),
        "by_family": by_family,
        "aggregation": "macro mean over per-episode edge precision/recall against that "
        "episode's own visited-cell truth graph",
    }


def split_support_query(
    n_transitions: int, k: int, *, query_limit: int
) -> tuple[list[int], list[int]]:
    """Deterministic non-overlapping support/query split for one world.

    Support transitions are the first ``k`` transitions of the world; query
    transitions are the following ones.  When fewer than ``k`` support
    transitions or no query transition exists, the split is empty and the
    caller must report ``insufficient_data`` (never a perfect zero).

    ``query_limit`` has no default: callers must pass the value from a verified
    preregistration (``require_query_limit``) so a missing registration cannot
    silently fall back to a code-only constant.
    """
    if isinstance(query_limit, bool) or not isinstance(query_limit, int):
        raise QueryLimitError(
            f"query_limit must be an int from the preregistration, got {type(query_limit).__name__}"
        )
    if query_limit != int(spec.EVALUATION["query_limit"]):
        raise QueryLimitError(
            f"query_limit {query_limit!r} differs from the registered "
            f"{spec.EVALUATION['query_limit']}"
        )
    total = int(n_transitions)
    support = min(max(int(k), 0), total)
    if support < int(k) or total - support < 1:
        return [], []
    query = list(range(support, min(total, support + int(query_limit))))
    return list(range(support)), query


def few_shot_report(per_k: Iterable[Mapping]) -> dict:
    """Aggregate the k-support/query rows; unavailable k values stay explicit."""
    rows = sorted((dict(row) for row in per_k), key=lambda row: int(row["k"]))
    if not rows:
        raise MetricIdentityError("few-shot report needs at least one k row")
    curve = {}
    unavailable = {}
    for row in rows:
        k = int(row["k"])
        if k in curve:
            raise MetricIdentityError(f"k={k} appears twice in the few-shot report")
        if not row.get("queries"):
            unavailable[str(k)] = {
                "status": "insufficient_data",
                "reason": row.get("reason", "no held-out query transition"),
                "support": int(row.get("support", 0)),
                "worlds": int(row.get("worlds", 0)),
            }
            continue
        curve[str(k)] = {
            "support_transitions": int(row.get("support", k)),
            "queries": int(row["queries"]),
            "worlds": int(row.get("worlds", 0)),
            "accuracy": float(row["accuracy"]),
            "balanced_accuracy": float(row.get("balanced_accuracy", row["accuracy"])),
            "displacement_mae_m": (
                None if row.get("displacement_mae_m") is None else float(row["displacement_mae_m"])
            ),
            "displacement_samples": int(row.get("displacement_samples", 0)),
            "edge_samples": int(row.get("edge_samples", row["queries"])),
            "by_world": dict(row.get("by_world") or {}),
        }
    if not curve:
        raise MetricIdentityError(
            "no k value had both support and a held-out query; the frozen probe cannot "
            "be scored on this dataset"
        )
    return {
        "k_values": [int(row["k"]) for row in rows],
        "curve": curve,
        "unavailable": unavailable,
        "support_rule": "support writes only model memory (no parameter update); query "
        "transitions are disjoint and follow the support prefix in the same world",
    }


def sample_efficiency_dual(rows: Iterable[Mapping]) -> dict:
    """loc + next-observation NLL curves over the frozen update checkpoints."""
    collected = sorted((dict(row) for row in rows), key=lambda row: int(row["updates"]))
    if not collected:
        raise MetricIdentityError("sample efficiency needs at least one checkpoint")
    for row in collected:
        if "development_nll" not in row or "localization_translation_mean_m" not in row:
            raise MetricIdentityError(
                "each sample-efficiency checkpoint needs both development_nll and "
                "localization_translation_mean_m"
            )
    nll_rows = [(int(row["updates"]), float(row["development_nll"])) for row in collected]
    loc_rows = [
        (int(row["updates"]), float(row["localization_translation_mean_m"])) for row in collected
    ]
    return {
        "nll_curve": sample_efficiency_curve(nll_rows),
        "localization_curve": sample_efficiency_curve(loc_rows),
        "checkpoints": [
            {
                "updates": int(row["updates"]),
                "development_nll": float(row["development_nll"]),
                "localization_translation_mean_m": float(
                    row["localization_translation_mean_m"]
                ),
                "nll_samples": int(row.get("nll_samples", 0)),
                "localization_samples": int(row.get("localization_samples", 0)),
            }
            for row in collected
        ],
    }


def interference_probes(
    *,
    zero_state: Mapping[str, float],
    history_paired: Mapping[str, float],
    before_new_world: Mapping[str, float],
    after_new_world: Mapping[str, float],
    probe: Mapping[str, Any] | None = None,
) -> dict:
    """M2 diagnostic: zero-state vs history vs post-new-world-write probe."""
    base = memory_interference(
        before=before_new_world,
        after=after_new_world,
        history_paired=history_paired,
        zero_state=zero_state,
    )
    base.update(
        {
            "zero_state": dict(zero_state),
            "history_paired": dict(history_paired),
            "before_new_world": dict(before_new_world),
            "after_new_world": dict(after_new_world),
            "probe": dict(probe or {}),
            "definition": "all probes are the same fixed development probe; history is "
            "written from another world; the new-world write happens after the history "
            "probe without parameter updates; parameters are hashed before and after",
        }
    )
    return base


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
