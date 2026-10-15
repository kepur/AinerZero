"""External residual readouts with a fixed, masked current-symbol path.

Past labels are used for fitting and scoring only. The prediction rule never
branches on the true change mask, and no function updates the student model.
"""

from __future__ import annotations

import numpy as np

from ainerzero.learning.baselines import copy_probabilities, symbol_metrics
from ainerzero.learning.linear_probe import decode_embeddings, fit_ridge, predict_ridge
from ainerzero.learning.recall_probe import FEATURE_KINDS, make_probe_rows


def make_residual_rows(collection: dict, *, delay: int, minimum_tick: int) -> dict:
    return make_probe_rows(
        collection, delay=delay, minimum_tick=minimum_tick, allow_zero_delay=True
    )


def _current_embeddings(rows, embedding):
    return embedding[rows["current_symbols"]] * rows["current_mask"][..., None]


def _require_train(rows):
    if rows.get("partition") != "train":
        raise ValueError("only train probe rows may fit readouts")


def _require_zero(rows):
    if type(rows.get("delay")) is not int or rows["delay"] != 0:
        raise ValueError("zero-delay control requires delay 0")
    if not np.array_equal(rows["target_mask"], rows["current_mask"]) or not np.array_equal(
        rows["targets"][rows["target_mask"]], rows["current_symbols"][rows["current_mask"]]
    ):
        raise ValueError("zero-delay labels must equal visible current observations")


def fit_residual_rows(rows, embedding, *, ridge=0.01):
    _require_train(rows)
    labels = embedding[rows["targets"]] - _current_embeddings(rows, embedding)
    return {
        kind: fit_ridge(rows["features"][kind], labels, rows["target_mask"], ridge=ridge)
        for kind in FEATURE_KINDS
    }


def fit_zero_delay_dense(rows, embedding, *, ridge=0.01):
    _require_train(rows)
    _require_zero(rows)
    return fit_ridge(
        rows["features"]["current_only"],
        embedding[rows["targets"]],
        rows["target_mask"],
        ridge=ridge,
    )


def _score_embeddings(predictions, rows, embedding, weight, bias):
    """Targets affect metrics, never any diagnostic prediction branch."""
    methods = {}
    for name in (*predictions, "copy_current"):
        probabilities = (
            copy_probabilities(rows["current_symbols"], rows["current_mask"])
            if name == "copy_current"
            else decode_embeddings(predictions[name], weight, bias)
        )
        squared = (
            None
            if name == "copy_current"
            else np.mean((predictions[name] - embedding[rows["targets"]]) ** 2, axis=-1)
        )

        def score(mask):
            metrics = symbol_metrics(
                probabilities, rows["targets"], mask, rows["current_symbols"], rows["current_mask"]
            )
            changed = mask & rows["current_mask"] & (rows["targets"] != rows["current_symbols"])
            if squared is not None:
                metrics.update(
                    embedding_mse=float(squared[mask].mean()) if mask.any() else None,
                    changed_embedding_mse=float(squared[changed].mean()) if changed.any() else None,
                )
            return metrics

        methods[name] = score(rows["target_mask"])
        methods[name]["per_world"] = [
            {
                "world_index": int(world),
                **score(rows["target_mask"] & (rows["world"] == world)[:, None]),
            }
            for world in np.unique(rows["world"])
        ]
    return {
        "partition": rows["partition"],
        "delay": rows["delay"],
        "minimum_tick": rows["minimum_tick"],
        "frame_count": len(rows["targets"]),
        "world_count": len(np.unique(rows["world"])),
        "methods": methods,
        "changed_definition": "past_target_differs_from_current_at_same_visible_position",
        "interpretation": "external_probe_performance_not_student_recall_capability",
    }


def score_residual_rows(probes, rows, embedding, weight, bias):
    base = _current_embeddings(rows, embedding)
    predictions = {
        kind: base + predict_ridge(probes[kind], rows["features"][kind]) for kind in FEATURE_KINDS
    }
    predictions["fixed_current_codec"] = base
    # Label-dependent oracle is a named scoring reference, never a feature.
    predictions["target_codec_oracle"] = embedding[rows["targets"]]
    result = _score_embeddings(predictions, rows, embedding, weight, bias)
    result["prediction_rule"] = "masked_current_embedding_plus_predicted_residual_for_every_sample"
    return result


def score_zero_delay_controls(dense_probe, rows, embedding, weight, bias):
    _require_zero(rows)
    base = _current_embeddings(rows, embedding)
    zero_output = base + np.zeros_like(base)
    result = _score_embeddings(
        {
            "dense_current_only": predict_ridge(dense_probe, rows["features"]["current_only"]),
            "fixed_current_codec": base,
            "zero_residual_codec": zero_output,
        },
        rows,
        embedding,
        weight,
        bias,
    )
    result["pipeline_checks"] = {
        "visible_targets_present": bool(rows["target_mask"].any()),
        "zero_residual_preserves_embedding": bool(np.array_equal(base, zero_output)),
        "zero_residual_preserves_decoding": bool(
            np.array_equal(
                decode_embeddings(base, weight, bias), decode_embeddings(zero_output, weight, bias)
            )
        ),
    }
    result["interpretation"] = (
        "fixed_zero_residual_checks_pipeline_only; dense_control_tests_readout_generalization_not_memory"
    )
    return result
