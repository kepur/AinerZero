"""CPU-only, fixed public input expansion for zero-context one-edge retention.

M2l uses 256 distinct preceding observations: four changed and twelve unchanged
edges per training world. This changes both input diversity and the changed-edge
mixture relative to M2j; it is not a single-factor diversity ablation.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

import numpy as np

from ainerzero.core.experience import DatasetPartition, TrainingPolicy, admit_training
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.micro_memory import _batch_digest, _digest, select_micro_memory_samples
from ainerzero.learning.one_step_memory import _validated_episodes
from ainerzero.runtime.c0_collection import RANDOM_ACTOR

WORLD_COUNT = 16
SAMPLES_PER_WORLD = 16
SAMPLE_COUNT = 256
UPDATE_COUNT = 200
BATCH_SIZE = 16
CHANGED_RANKS = (0, 4, 8, 12)


def _sensor_identity(observation) -> dict:
    return {
        "symbols": list(observation.symbols),
        "visible_mask": list(observation.visible_mask),
        "cursor": observation.cursor,
    }


def diverse_training_schedule() -> np.ndarray:
    """Zero-based update rows, one edge per world and four changed edges per batch."""
    return np.asarray(
        [
            [
                world * SAMPLES_PER_WORLD + (update + world) % SAMPLES_PER_WORLD
                for world in range(WORLD_COUNT)
            ]
            for update in range(UPDATE_COUNT)
        ],
        dtype=np.int32,
    )


def _validate_pool(pool: dict[str, np.ndarray]) -> None:
    specs = {
        "symbols": ((SAMPLE_COUNT, 2, 8), np.dtype(np.int32)),
        "visible_mask": ((SAMPLE_COUNT, 2, 8), np.dtype(np.bool_)),
        "cursor": ((SAMPLE_COUNT, 2), np.dtype(np.int32)),
        "episode_start": ((SAMPLE_COUNT, 2), np.dtype(np.bool_)),
        "actions": ((SAMPLE_COUNT, 1), np.dtype(np.int32)),
    }
    if not isinstance(pool, dict) or set(pool) != set(specs):
        raise ValueError("diverse pool must contain only the public sequence fields")
    for name, (shape, dtype) in specs.items():
        values = pool[name]
        if not isinstance(values, np.ndarray) or values.shape != shape or values.dtype != dtype:
            raise ValueError(f"{name} must be a numpy array of shape {shape} and dtype {dtype}")
    if np.any(pool["symbols"] < 0) or np.any(pool["symbols"] > 255):
        raise ValueError("symbols must be bytes")
    if np.any(pool["symbols"][~pool["visible_mask"]] != 0):
        raise ValueError("hidden symbols must be the public zero placeholder")
    if np.any(pool["cursor"] < 0) or np.any(pool["cursor"] > 7):
        raise ValueError("cursor must index a public position")
    if np.any(pool["actions"] < 0) or np.any(pool["actions"] > 3):
        raise ValueError("actions must use the C0 action space")
    if not pool["episode_start"][:, 0].all() or pool["episode_start"][:, 1].any():
        raise ValueError("every diverse example must have a fresh two-frame context")
    if not pool["visible_mask"][:, 0].any(axis=1).all():
        raise ValueError("every diverse example needs a visible target")
    shared = pool["visible_mask"][:, 0] & pool["visible_mask"][:, 1]
    changed = (shared & (pool["symbols"][:, 0] != pool["symbols"][:, 1])).any(axis=1)
    if not np.array_equal(changed, np.arange(SAMPLE_COUNT) % 4 == 0):
        raise ValueError("each world needs changed ranks 0,4,8,12 and twelve unchanged edges")
    previous = np.concatenate(
        [pool["symbols"][:, 0], pool["visible_mask"][:, 0], pool["cursor"][:, :1]], axis=1
    )
    if np.unique(previous, axis=0).shape[0] != SAMPLE_COUNT:
        raise ValueError("all preceding public observations must be distinct")


def get_diverse_batch(pool: dict[str, np.ndarray], update_index: int) -> dict[str, np.ndarray]:
    """Return independent NumPy arrays for the preregistered zero-based update."""
    if type(update_index) is not int or not 0 <= update_index < UPDATE_COUNT:
        raise ValueError("update_index must be a Python integer from 0 through 199")
    _validate_pool(pool)
    rows = diverse_training_schedule()[update_index]
    return {name: values[rows].copy() for name, values in pool.items()}


def select_diverse_memory_samples(
    episodes: Sequence[EpisodeTrajectory],
) -> tuple[dict[str, np.ndarray], dict]:
    """Admit every train edge, then select earliest distinct 4 changed + 12 unchanged.

    Worlds are ordered by public IDs. Changed edges are selected first, followed
    by unchanged edges, without reusing any selected preceding observation across
    the entire pool. Within a world changes occupy ranks 0,4,8,12. Insufficient
    coverage fails closed; repeated examples never silently fill a quota.
    """
    episodes, _ = _validated_episodes(episodes, DatasetPartition.TRAIN)
    if len(episodes) != WORLD_COUNT:
        raise ValueError("diverse memory requires exactly 16 distinct training worlds")
    episodes.sort(
        key=lambda item: (
            str(item.initial.context.episode_id),
            str(item.initial.context.environment_instance_id),
        )
    )
    policy = TrainingPolicy(allowed_actors=(RANDOM_ACTOR,))
    admitted_episodes = []
    for episode in episodes:
        if len(episode.transitions) != 128:
            raise ValueError("diverse memory requires exactly 128 transitions per world")
        admitted_episodes.append([admit_training(item, policy) for item in episode.transitions])

    rows, identities, world_coverage = [], [], []
    seen_previous = set()
    for world, (episode, transitions) in enumerate(zip(episodes, admitted_episodes, strict=True)):
        candidates = []
        for index, transition in enumerate(transitions):
            target, current = transition.observation.payload, transition.next_observation.payload
            target_visible = np.asarray(target.visible_mask)
            shared = target_visible & np.asarray(current.visible_mask)
            changed = shared & (np.asarray(target.symbols) != np.asarray(current.symbols))
            previous = _sensor_identity(target)
            candidates.append(
                {
                    "index": index,
                    "transition": transition,
                    "shared": shared,
                    "changed": changed,
                    "previous_sha": _digest(previous),
                    "edge_sha": _digest(
                        {
                            "previous": previous,
                            "current": _sensor_identity(current),
                            "action": transition.action_request.action,
                        }
                    ),
                }
            )
        selected = {True: [], False: []}
        for wanted, required in ((True, 4), (False, 12)):
            for candidate in candidates:
                if bool(candidate["changed"].any()) != wanted:
                    continue
                if candidate["previous_sha"] in seen_previous:
                    continue
                if not any(candidate["transition"].observation.payload.visible_mask):
                    continue
                selected[wanted].append(candidate)
                seen_previous.add(candidate["previous_sha"])
                if len(selected[wanted]) == required:
                    break
            if len(selected[wanted]) != required:
                raise ValueError(
                    f"training world {episode.initial.context.environment_instance_id} needs "
                    f"{required} distinct {'changed' if wanted else 'unchanged'} previous inputs"
                )
        iterators = {key: iter(value) for key, value in selected.items()}
        public_episode_sha = _digest(episode.model_dump(mode="json"))
        context = episode.initial.context
        for rank in range(SAMPLES_PER_WORLD):
            chosen = next(iterators[rank in CHANGED_RANKS])
            transition = chosen["transition"]
            target, current = transition.observation.payload, transition.next_observation.payload
            row = {
                "symbols": np.asarray([target.symbols, current.symbols], dtype=np.int32),
                "visible_mask": np.asarray(
                    [target.visible_mask, current.visible_mask], dtype=np.bool_
                ),
                "cursor": np.asarray([target.cursor, current.cursor], dtype=np.int32),
                "episode_start": np.asarray([True, False], dtype=np.bool_),
                "actions": np.asarray([transition.action_request.action], dtype=np.int32),
            }
            identities.append(
                {
                    "row": len(rows),
                    "world_index": world,
                    "world_rank": rank,
                    "episode_id": str(context.episode_id),
                    "environment_instance_id": str(context.environment_instance_id),
                    "transition_index": chosen["index"],
                    "target_tick": transition.observation.step,
                    "query_tick": transition.next_observation.step,
                    "target_observation_id": str(transition.observation.id),
                    "current_observation_id": str(transition.next_observation.id),
                    "action_request_id": str(transition.action_request.id),
                    "target_visible_count": int(np.count_nonzero(target.visible_mask)),
                    "changed_count": int(chosen["changed"].sum()),
                    "unchanged_count": int((chosen["shared"] & ~chosen["changed"]).sum()),
                    "previous_input_sha256": chosen["previous_sha"],
                    "edge_input_sha256": chosen["edge_sha"],
                    "public_episode_sha256": public_episode_sha,
                    "public_transition_sha256": _digest(transition.model_dump(mode="json")),
                    "public_sample_sha256": _batch_digest(row),
                }
            )
            rows.append(row)
        world_coverage.append(
            {
                "world_index": world,
                "episode_id": str(context.episode_id),
                "environment_instance_id": str(context.environment_instance_id),
                "selected_count": 16,
                "selected_changed_edges": 4,
                "selected_unchanged_edges": 12,
                "available_changed_unique_previous": len(
                    {c["previous_sha"] for c in candidates if c["changed"].any()}
                ),
                "available_unchanged_unique_previous": len(
                    {c["previous_sha"] for c in candidates if not c["changed"].any()}
                ),
            }
        )
    pool = {name: np.stack([row[name] for row in rows]) for name in rows[0]}
    _validate_pool(pool)
    _, old = select_micro_memory_samples(episodes)
    old_ids = {(row["episode_id"], row["query_tick"]) for row in old["samples"]}
    current_ids = {(row["episode_id"], row["query_tick"]) for row in identities}
    if not old_ids <= current_ids:
        raise ValueError("diverse pool must include all sixteen original micro-fit edges")
    schedule = diverse_training_schedule()
    counts = np.bincount(schedule.ravel(), minlength=SAMPLE_COUNT)
    position_counts = [
        Counter(map(int, pool["symbols"][:, 0, position][pool["visible_mask"][:, 0, position]]))
        for position in range(8)
    ]
    symbol_counts = sum(position_counts, Counter())
    coverage = {
        "world_count": WORLD_COUNT,
        "unique_previous_inputs": len(seen_previous),
        "unique_edge_inputs": len({row["edge_input_sha256"] for row in identities}),
        "changed_edges": 64,
        "unchanged_edges": 192,
        "old_micro_fit_edges_included": len(old_ids & current_ids),
        "target_symbol_ids": sorted(symbol_counts),
        "target_symbol_counts": {str(key): symbol_counts[key] for key in sorted(symbol_counts)},
        "target_symbol_counts_by_position": [
            {str(key): counts[key] for key in sorted(counts)} for counts in position_counts
        ],
        "target_unique_symbols_by_position": [len(counts) for counts in position_counts],
        "action_counts": {
            str(action): int((pool["actions"] == action).sum()) for action in range(4)
        },
        "cursor_counts": {
            str(cursor): int((pool["cursor"][:, 0] == cursor).sum()) for cursor in range(8)
        },
        "worlds": world_coverage,
    }
    return pool, {
        "schema_version": 1,
        "scope": "fixed_training_input_distribution_expansion_for_one_edge_memory_fit",
        "partition": DatasetPartition.TRAIN.value,
        "selection": "earliest_4_changed_then_12_unchanged_global_unique_previous_inputs_per_world",
        "ordering": ["episode_id", "environment_instance_id", "world_rank_changed_at_0_4_8_12"],
        "sample_count": SAMPLE_COUNT,
        "sequence_steps": 1,
        "burn_in": 0,
        "context_reset": "zero_state_for_each_selected_two_frame_slice",
        "actor": RANDOM_ACTOR.model_dump(mode="json"),
        "assistance": [],
        "target_visible_count": sum(row["target_visible_count"] for row in identities),
        "changed_count": sum(row["changed_count"] for row in identities),
        "unchanged_count": sum(row["unchanged_count"] for row in identities),
        "batch_sha256": _batch_digest(pool),
        "sample_manifest_sha256": _digest(identities),
        "schedule_sha256": _digest(schedule.tolist()),
        "schedule": schedule.tolist(),
        "schedule_rule": "row=w*16+(zero_based_update+w)%16",
        "sample_presentations": counts.tolist(),
        "micro_fit_sample_manifest_sha256": old["sample_manifest_sha256"],
        "coverage": coverage,
        "samples": identities,
    }
