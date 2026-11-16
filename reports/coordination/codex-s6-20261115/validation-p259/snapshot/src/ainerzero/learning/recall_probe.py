"""Causal frozen-state collection and past-symbol probe datasets.

Probe coefficients are external diagnostic artifacts. Nothing here updates the
student or treats an external decoder's success as the student's own recall.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from ainerzero.core.experience import DatasetPartition
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import copy_probabilities, symbol_metrics
from ainerzero.learning.linear_probe import decode_embeddings, fit_ridge, predict_ridge

FEATURE_KINDS = ("full_state", "reset_state", "current_only")
FEATURE_WIDTH = 272
PARTICLES = 8
DELAYS = (1, 2, 4)


def collect_probe_features(
    model,
    episodes: Sequence[EpisodeTrajectory],
    byte_embedding: np.ndarray,
    *,
    partition: str,
    seed: int,
    before_work: Callable[[int], None],
) -> dict:
    """Replay public prefixes, storing posterior [h,z] particle means at each tick.

    Full and reset arms share the current-observation key. A full feedback edge
    (imagine + observe) costs eight units; each initial/reset observation costs
    eight. Current-only has 128 learned byte features + 8 mask + 8 cursor fields,
    zero-padded to the same 272-column interface. Equal column counts do not
    imply equal effective information rank.
    """
    if partition not in ("train", "development"):
        raise ValueError("probe collection requires train or development partition")
    if type(seed) is not int or not 0 <= seed < 2**32 or not callable(before_work):
        raise ValueError("probe collection requires a valid seed and budget callback")
    embedding = np.asarray(byte_embedding, dtype=np.float64)
    if embedding.shape != (256, 16) or not np.isfinite(embedding).all():
        raise ValueError("byte embedding must be finite [256,16]")
    validated = [EpisodeTrajectory.model_validate(ep) for ep in episodes]
    seen_ids, seen_worlds = set(), set()
    for ep in validated:
        context = ep.initial.context
        if context.partition is not DatasetPartition(partition):
            raise ValueError("probe episode partition mismatch")
        if context.episode_id in seen_ids or context.environment_instance_id in seen_worlds:
            raise ValueError("probe episodes and worlds must be distinct")
        seen_ids.add(context.episode_id)
        seen_worlds.add(context.environment_instance_id)
    sequences = []
    units = 0
    rng = np.random.default_rng(seed)

    def reserve():
        nonlocal units
        before_work(PARTICLES)
        units += PARTICLES

    for ep in validated:
        observations = [ep.initial.payload] + [t.next_observation.payload for t in ep.transitions]
        actions = [t.action_request.action for t in ep.transitions]
        # Reservation precedes tensor-runtime import, construction and first model call.
        reserve()
        import mlx.core as mx

        def key():
            return mx.random.key(int(rng.integers(0, 2**32)))

        h, z = model.initial(PARTICLES)
        values = {kind: [] for kind in FEATURE_KINDS}
        for tick, observation in enumerate(observations):
            if tick:
                reserve()
                prior = model.imagine(
                    h, z, mx.full((PARTICLES,), actions[tick - 1], dtype=mx.int32), key=key()
                )
                h = prior["h"]
            observation_key = key()
            arguments = (
                mx.array([observation.symbols] * PARTICLES, dtype=mx.int32),
                mx.array([observation.visible_mask] * PARTICLES, dtype=mx.bool_),
                mx.array([observation.cursor] * PARTICLES, dtype=mx.int32),
            )
            full = model.observe(h, *arguments, key=observation_key)
            h, z = full["h"], full["z"]
            reserve()
            zero, _ = model.initial(PARTICLES)
            reset = model.observe(zero, *arguments, key=observation_key)
            for kind, state in (("full_state", full), ("reset_state", reset)):
                mx.eval(state["h"], state["z"])
                hh, zz = np.asarray(state["h"]), np.asarray(state["z"])
                if hh.shape != (PARTICLES, 256) or zz.shape != (PARTICLES, 16):
                    raise ValueError("probe requires h[8,256] and z[8,16]")
                feature = np.concatenate((hh, zz), axis=-1).astype(np.float64).mean(axis=0)
                if not np.isfinite(feature).all():
                    raise ValueError("non-finite frozen probe state")
                values[kind].append(feature)
            visible = np.asarray(observation.visible_mask)
            current = embedding[np.asarray(observation.symbols)] * visible[:, None]
            raw = np.concatenate((current.ravel(), visible, np.eye(8)[observation.cursor]))
            values["current_only"].append(np.pad(raw, (0, FEATURE_WIDTH - len(raw))))
        sequences.append(
            {
                "partition": partition,
                "episode_id": str(ep.initial.context.episode_id),
                "features": {kind: np.stack(items) for kind, items in values.items()},
                "symbols": np.asarray([o.symbols for o in observations], dtype=np.int32),
                "visible_mask": np.asarray([o.visible_mask for o in observations], dtype=np.bool_),
                "ticks": np.arange(len(observations), dtype=np.int32),
            }
        )
    return {
        "sequences": sequences,
        "logical_model_units": units,
        "partition": partition,
        "seed": seed,
    }


def make_probe_rows(
    collection: dict, *, delay: int, minimum_tick: int, allow_zero_delay: bool = False
) -> dict:
    """Pair current-state features at t with public labels at t-delay only."""
    allowed = (0, *DELAYS) if allow_zero_delay else DELAYS
    if type(allow_zero_delay) is not bool or type(delay) is not int or delay not in allowed:
        raise ValueError("probe delay must be 1, 2, or 4; zero requires explicit opt-in")
    if type(minimum_tick) is not int or minimum_tick < delay:
        raise ValueError("probe minimum tick must cover the complete delay")
    blocks = []
    for world, seq in enumerate(collection["sequences"]):
        count = len(seq["symbols"])
        ticks = np.arange(minimum_tick, count, dtype=np.int32)
        if not len(ticks):
            continue
        blocks.append(
            {
                "features": {kind: seq["features"][kind][ticks] for kind in FEATURE_KINDS},
                "targets": seq["symbols"][ticks - delay],
                "target_mask": seq["visible_mask"][ticks - delay],
                "current_symbols": seq["symbols"][ticks],
                "current_mask": seq["visible_mask"][ticks],
                "world": np.full(len(ticks), world, dtype=np.int32),
                "ticks": ticks,
            }
        )
    if not blocks:
        raise ValueError("no complete probe rows for this delay")
    result = {
        name: np.concatenate([b[name] for b in blocks]) for name in blocks[0] if name != "features"
    }
    result["features"] = {
        kind: np.concatenate([b["features"][kind] for b in blocks]) for kind in FEATURE_KINDS
    }
    result.update(partition=collection["partition"], delay=delay, minimum_tick=minimum_tick)
    return result


def feature_summary(features: np.ndarray) -> dict:
    centered = features - features.mean(axis=0)
    return {
        "rows": len(features),
        "columns": features.shape[1],
        "near_constant_columns": int(np.sum(features.std(axis=0) <= 1e-6)),
        "centered_numerical_rank": int(np.linalg.matrix_rank(centered)),
        "rank_threshold": "numpy_default_smax_times_max_shape_times_float64_eps",
    }


def fit_probe_rows(rows: dict, embedding: np.ndarray, *, ridge: float = 0.01) -> dict:
    """Only admitted training-partition rows may determine probe coefficients."""
    if rows.get("partition") != "train":
        raise ValueError("only train probe rows may fit readouts")
    targets = embedding[rows["targets"]]
    return {
        kind: fit_ridge(rows["features"][kind], targets, rows["target_mask"], ridge=ridge)
        for kind in FEATURE_KINDS
    }


def score_probe_rows(probes, rows, embedding, readout_weight, readout_bias) -> dict:
    """All scores concern past targets; changed means past differs from current."""
    predictions = {
        kind: predict_ridge(probes[kind], rows["features"][kind]) for kind in FEATURE_KINDS
    }
    predictions["target_codec_oracle"] = embedding[rows["targets"]]
    metrics = {}
    for name in (*FEATURE_KINDS, "target_codec_oracle", "copy_current"):
        probabilities = (
            copy_probabilities(rows["current_symbols"], rows["current_mask"])
            if name == "copy_current"
            else decode_embeddings(predictions[name], readout_weight, readout_bias)
        )

        def score(mask):
            value = symbol_metrics(
                probabilities, rows["targets"], mask, rows["current_symbols"], rows["current_mask"]
            )
            chosen = mask & rows["current_mask"] & (rows["targets"] != rows["current_symbols"])
            if name != "copy_current":
                squared_error = np.mean(
                    (predictions[name] - embedding[rows["targets"]]) ** 2, axis=-1
                )
                value.update(
                    embedding_mse=float(squared_error[mask].mean()) if mask.any() else None,
                    changed_embedding_mse=float(squared_error[chosen].mean())
                    if chosen.any()
                    else None,
                )
            return value

        all_scores = score(rows["target_mask"])
        all_scores["per_world"] = [
            {
                "world_index": int(world),
                **score(rows["target_mask"] & (rows["world"] == world)[:, None]),
            }
            for world in np.unique(rows["world"])
        ]
        metrics[name] = all_scores
    return {
        "partition": rows["partition"],
        "delay": rows["delay"],
        "minimum_tick": rows["minimum_tick"],
        "frame_count": len(rows["targets"]),
        "world_count": len(np.unique(rows["world"])),
        "methods": metrics,
        "changed_definition": "past_target_differs_from_current_at_same_visible_position",
        "interpretation": "external_probe_performance_not_student_recall_capability",
    }
