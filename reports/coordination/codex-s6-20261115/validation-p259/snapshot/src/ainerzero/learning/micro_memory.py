"""Fixed public one-edge memory examples, with no inherited recurrent context.

The sixteen examples deliberately revisit training inputs. They test whether
the existing model can fit a minimal memory task, not generalization. Selecting
a changed public edge is an engineered curriculum, not autonomous exploration.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence

import numpy as np

from ainerzero.core.experience import DatasetPartition, TrainingPolicy, admit_training
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import copy_probabilities, symbol_metrics
from ainerzero.learning.evaluation import _mean_probabilities, _Summary
from ainerzero.learning.one_step_memory import METHODS, _validated_episodes
from ainerzero.runtime.c0_collection import RANDOM_ACTOR

SAMPLE_COUNT = 16
MICRO_BATCH_SIZE = 4
TRAINING_SEED = 2203
NEW_NOISE_SEED = 2603


def _digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _batch_digest(batch: dict[str, np.ndarray]) -> str:
    return _digest({name: value.tolist() for name, value in batch.items()})


def select_micro_memory_samples(
    episodes: Sequence[EpisodeTrajectory],
) -> tuple[dict[str, np.ndarray], dict]:
    """One earliest visible changed edge from each of exactly 16 training worlds.

    All public transitions, including those not selected, must pass the fixed
    unassisted random-actor policy. Stable IDs determine row order; symbols do not.
    The returned batch contains only public sensor/action fields. Original record
    IDs, ticks, public hashes, and selection counts are kept separately as evidence.
    Each two-frame slice explicitly starts a new computational context at zero.
    No private snapshot, environment seed, or hidden truth is inspected.
    """
    episodes, _ = _validated_episodes(episodes, DatasetPartition.TRAIN)
    if len(episodes) != SAMPLE_COUNT:
        raise ValueError("micro memory requires exactly 16 distinct training worlds")
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    episodes.sort(
        key=lambda item: (
            str(item.initial.context.episode_id),
            str(item.initial.context.environment_instance_id),
        )
    )
    rows, identities = [], []
    for episode in episodes:
        admitted = [admit_training(item, policy) for item in episode.transitions]
        selected = None
        for index, transition in enumerate(admitted):
            target, current = transition.observation.payload, transition.next_observation.payload
            shared = np.asarray(target.visible_mask) & np.asarray(current.visible_mask)
            changed = shared & (np.asarray(target.symbols) != np.asarray(current.symbols))
            if changed.any():
                selected = (index, transition, changed, shared)
                break
        if selected is None:
            raise ValueError(
                "training world has no mutually visible changed transition: "
                f"{episode.initial.context.environment_instance_id}"
            )
        index, transition, changed, shared = selected
        target, current = transition.observation.payload, transition.next_observation.payload
        row = {
            "symbols": np.asarray([target.symbols, current.symbols], dtype=np.int32),
            "visible_mask": np.asarray([target.visible_mask, current.visible_mask], dtype=np.bool_),
            "cursor": np.asarray([target.cursor, current.cursor], dtype=np.int32),
            "episode_start": np.asarray([True, False], dtype=np.bool_),
            "actions": np.asarray([transition.action_request.action], dtype=np.int32),
        }
        rows.append(row)
        context = episode.initial.context
        identities.append(
            {
                "row": len(rows) - 1,
                "episode_id": str(context.episode_id),
                "environment_instance_id": str(context.environment_instance_id),
                "transition_index": index,
                "target_tick": transition.observation.step,
                "query_tick": transition.next_observation.step,
                "target_observation_id": str(transition.observation.id),
                "current_observation_id": str(transition.next_observation.id),
                "action_request_id": str(transition.action_request.id),
                "target_visible_count": int(np.count_nonzero(target.visible_mask)),
                "changed_count": int(changed.sum()),
                "unchanged_count": int((shared & ~changed).sum()),
                "public_episode_sha256": _digest(episode.model_dump(mode="json")),
                "public_transition_sha256": _digest(transition.model_dump(mode="json")),
                "public_sample_sha256": _batch_digest(row),
            }
        )
    batch = {name: np.stack([row[name] for row in rows]) for name in rows[0]}
    _validate_batch(batch)
    return batch, {
        "schema_version": 1,
        "scope": "fixed_training_inputs_for_one_edge_memory_fit",
        "partition": DatasetPartition.TRAIN.value,
        "selection": "earliest_mutually_visible_changed_transition_per_training_world",
        "ordering": ["episode_id", "environment_instance_id"],
        "sample_count": SAMPLE_COUNT,
        "sequence_steps": 1,
        "burn_in": 0,
        "context_reset": "zero_state_for_each_selected_two_frame_slice",
        "actor": RANDOM_ACTOR.model_dump(mode="json"),
        "assistance": [],
        "target_visible_count": sum(row["target_visible_count"] for row in identities),
        "changed_count": sum(row["changed_count"] for row in identities),
        "unchanged_count": sum(row["unchanged_count"] for row in identities),
        "batch_sha256": _batch_digest(batch),
        "sample_manifest_sha256": _digest(identities),
        "samples": identities,
    }


def _validate_batch(batch: dict[str, np.ndarray]) -> None:
    specs = {
        "symbols": ((SAMPLE_COUNT, 2, 8), np.dtype(np.int32)),
        "visible_mask": ((SAMPLE_COUNT, 2, 8), np.dtype(np.bool_)),
        "cursor": ((SAMPLE_COUNT, 2), np.dtype(np.int32)),
        "episode_start": ((SAMPLE_COUNT, 2), np.dtype(np.bool_)),
        "actions": ((SAMPLE_COUNT, 1), np.dtype(np.int32)),
    }
    if not isinstance(batch, dict) or set(batch) != set(specs):
        raise ValueError("micro memory batch must contain only the public sequence fields")
    for name, (shape, dtype) in specs.items():
        values = batch[name]
        if not isinstance(values, np.ndarray) or values.shape != shape or values.dtype != dtype:
            raise ValueError(f"{name} must be a numpy array of shape {shape} and dtype {dtype}")
    if np.any(batch["symbols"] < 0) or np.any(batch["symbols"] > 255):
        raise ValueError("symbols must be bytes")
    if np.any(batch["symbols"][~batch["visible_mask"]] != 0):
        raise ValueError("hidden symbols must be the public zero placeholder")
    if np.any(batch["cursor"] < 0) or np.any(batch["cursor"] > 7):
        raise ValueError("cursor must index a public position")
    if np.any(batch["actions"] < 0) or np.any(batch["actions"] > 3):
        raise ValueError("actions must use the C0 action space")
    if not batch["episode_start"][:, 0].all() or batch["episode_start"][:, 1].any():
        raise ValueError("every micro memory example must have a fresh two-frame context")
    shared = batch["visible_mask"][:, 0] & batch["visible_mask"][:, 1]
    changed = shared & (batch["symbols"][:, 0] != batch["symbols"][:, 1])
    if not changed.any(axis=-1).all():
        raise ValueError("every micro memory example must contain a visible changed symbol")


def evaluate_micro_memory(
    model,
    batch: dict[str, np.ndarray],
    *,
    seed: int,
    before_work: Callable[[int], None],
    micro_batch_size: int = MICRO_BATCH_SIZE,
) -> dict:
    """Frozen single-particle score on the fixed sixteen one-edge examples.

    RNG uses split(key(seed), 4), then split(micro_key, 3), exactly as the
    burn_in=0 training loss for each four-example microbatch. Reset history receives
    the same current observation and posterior key. Each microbatch reserves 3*B
    units before importing MLX or constructing any tensors: initial observation,
    imagine/observe feedback, and reset observation. Four microbatches cost 48 units.
    The second seed changes latent noise on identical inputs, not held-out data.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(seed) is not int or seed not in (TRAINING_SEED, NEW_NOISE_SEED):
        raise ValueError("micro memory seed must be preregistered 2203 or 2603")
    if type(micro_batch_size) is not int or micro_batch_size != MICRO_BATCH_SIZE:
        raise ValueError("micro_batch_size must be exactly 4")
    _validate_batch(batch)
    summaries = {name: _Summary() for name in METHODS}
    per_sample = []
    micro_count = SAMPLE_COUNT // micro_batch_size
    for micro_index in range(micro_count):
        before_work(3 * micro_batch_size)
        import mlx.core as mx

        start = micro_index * micro_batch_size
        stop = start + micro_batch_size
        values = {name: mx.array(data[start:stop]) for name, data in batch.items()}
        micro_key = mx.random.split(mx.random.key(seed), num=micro_count)[micro_index]
        keys = mx.random.split(micro_key, num=3)
        h, _ = model.initial(micro_batch_size)
        state = model.observe(
            h,
            values["symbols"][:, 0],
            values["visible_mask"][:, 0],
            values["cursor"][:, 0],
            key=keys[0],
        )
        imagined = model.imagine(state["h"], state["z"], values["actions"][:, 0], key=keys[1])
        posterior = model.observe(
            imagined["h"],
            values["symbols"][:, 1],
            values["visible_mask"][:, 1],
            values["cursor"][:, 1],
            key=keys[2],
        )

        def probabilities(state, offset):
            if state["h"].shape != (micro_batch_size, 256):
                raise ValueError("micro memory state must have shape [4,256]")
            logits = model.symbol_readout(
                state["h"][:, offset : offset + 128].reshape(micro_batch_size, 8, 16)
            )
            # The leading dimension is the sole particle. Never average the
            # four distinct examples into one prediction.
            return _mean_probabilities(logits[None], (1, micro_batch_size, 8, 256))

        predictions = {
            "memory_tail": probabilities(posterior, 128),
            "fixed_current_codec": probabilities(posterior, 0),
            "copy_current": copy_probabilities(
                batch["symbols"][start:stop, 1], batch["visible_mask"][start:stop, 1]
            ),
        }
        reset_h, _ = model.initial(micro_batch_size)
        reset = model.observe(
            reset_h,
            values["symbols"][:, 1],
            values["visible_mask"][:, 1],
            values["cursor"][:, 1],
            key=keys[2],
        )
        predictions["reset_history"] = probabilities(reset, 128)
        for local_index, row in enumerate(range(start, stop)):
            methods = {}
            for name in METHODS:
                result = symbol_metrics(
                    predictions[name][local_index],
                    batch["symbols"][row, 0],
                    batch["visible_mask"][row, 0],
                    batch["symbols"][row, 1],
                    batch["visible_mask"][row, 1],
                )
                summaries[name].add(result)
                methods[name] = result
            per_sample.append({"row": row, "methods": methods})
    return {
        "schema_version": 1,
        "scope": "fixed_training_inputs_for_one_edge_memory_fit",
        "partition": DatasetPartition.TRAIN.value,
        "noise_condition": "training_noise" if seed == TRAINING_SEED else "same_inputs_new_noise",
        "seed": seed,
        "particles": 1,
        "sample_count": SAMPLE_COUNT,
        "query_count": SAMPLE_COUNT,
        "micro_batch_size": micro_batch_size,
        "batch_sha256": _batch_digest(batch),
        "initial_observation_encodes": SAMPLE_COUNT,
        "feedback_model_transitions": SAMPLE_COUNT,
        "reset_observation_encodes": SAMPLE_COUNT,
        "logical_model_transitions": 3 * SAMPLE_COUNT,
        "methods": {name: summary.result() for name, summary in summaries.items()},
        "per_sample": per_sample,
        "protocol": {
            "weight_updates": False,
            "fitted_readout": False,
            "state_reset_per_example": True,
            "generalization_evaluation": False,
            "targets": "preceding_public_observation_visible_symbols",
            "tail_prefilled": False,
            "rng": "split(key(seed),4), then split(micro_key,3)",
        },
    }
