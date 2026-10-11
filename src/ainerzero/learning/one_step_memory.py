"""Retain the preceding public observation in the existing recurrent state.

The fixed symbol head reads the second half of the state *after* the next
observation is ingested. This module adds neither parameters nor a fitted
readout. Freezing all parameters except the existing GRU belongs to the worker.
Tensor imports are lazy so evaluation's first reservation precedes tensor work.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from ainerzero.core.experience import DatasetPartition
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import copy_probabilities, symbol_metrics
from ainerzero.learning.evaluation import _mean_probabilities, _Summary

METHODS = ("memory_tail", "reset_history", "copy_current", "fixed_current_codec")


def memory_sequence_loss(model, batch: dict, *, burn_in: int = 4, key):
    """Uniform visible-symbol CE for o_t read from post-observation state at t+1.

    Observations are [B,T+1,8], actions [B,T], episode_start [B,T+1], and optional
    valid_mask [B,T]. Burn-in supplies context but contributes no loss; both h
    and z are detached at its boundary. Hidden past slots, invalid transitions,
    and transitions crossing an episode boundary never become labels.

    There is exactly one initial observation and T imagine/observe feedback
    edges: the caller must reserve B*(T+1) logical units before calling. No past
    embedding is copied into the tail by this loss; only model.imagine can learn
    to write it. The loss does not select or change trainable parameters.
    """
    required = {"symbols", "visible_mask", "cursor", "actions", "episode_start"}
    if not required <= set(batch) or set(batch) - required - {"valid_mask"}:
        raise ValueError("memory batch must contain only the public sequence fields")
    actions = batch["actions"]
    if actions.ndim != 2:
        raise ValueError("actions must have shape [B,T]")
    size, steps = actions.shape
    if size < 1 or type(burn_in) is not int or not 0 <= burn_in < steps:
        raise ValueError("burn_in must leave at least one training transition")
    for name, shape in {
        "symbols": (size, steps + 1, 8),
        "visible_mask": (size, steps + 1, 8),
        "cursor": (size, steps + 1),
        "episode_start": (size, steps + 1),
        "valid_mask": (size, steps),
    }.items():
        if name in batch and batch[name].shape != shape:
            raise ValueError(f"{name} must have shape {shape}")

    import mlx.core as mx
    import mlx.nn as nn

    valid = batch.get("valid_mask")
    if valid is None:
        valid = mx.ones(actions.shape, dtype=mx.bool_)
    keys = mx.random.split(key, num=2 * steps + 1)
    h, _ = model.initial(size)
    state = model.observe(
        h,
        batch["symbols"][:, 0],
        batch["visible_mask"][:, 0],
        batch["cursor"][:, 0],
        key=keys[0],
    )
    errors, masks, transitions = [], [], []
    for t in range(steps):
        h, z = state["h"], state["z"]
        if t == burn_in:
            h, z = mx.stop_gradient(h), mx.stop_gradient(z)
        imagined = model.imagine(h, z, actions[:, t], key=keys[2 * t + 1])
        starts = batch["episode_start"][:, t + 1]
        # An invalid action cannot advance recurrent history. Its next public
        # observation is still ingested, so a later valid edge has the correct
        # preceding observation even when valid_mask has an internal hole.
        next_h = mx.where(valid[:, t, None], imagined["h"], h)
        next_h = mx.where(starts[:, None], mx.zeros_like(h), next_h)
        posterior = model.observe(
            next_h,
            batch["symbols"][:, t + 1],
            batch["visible_mask"][:, t + 1],
            batch["cursor"][:, t + 1],
            key=keys[2 * t + 2],
        )
        if t >= burn_in:
            if posterior["h"].shape != (size, 256):
                raise ValueError("memory state must have shape [B,256]")
            logits = model.symbol_readout(posterior["h"][:, 128:].reshape(size, 8, 16))
            if logits.shape != (size, 8, 256):
                raise ValueError("symbol readout must have shape [B,8,256]")
            path_valid = valid[:, t] & ~starts
            visible = batch["visible_mask"][:, t] & path_valid[:, None]
            labels = mx.where(visible, batch["symbols"][:, t], 0)
            errors.append(nn.losses.cross_entropy(logits, labels))
            masks.append(visible.astype(mx.float32))
            transitions.append(path_valid.astype(mx.float32))
        state = posterior
    weights = mx.stack(masks, axis=1)
    count = mx.sum(weights)
    total = mx.sum(mx.stack(errors, axis=1) * weights) / mx.maximum(count, 1)
    return total, {
        "memory_loss": total,
        "memory_symbol_nll": total,
        "valid_transitions": mx.sum(mx.stack(transitions, axis=1)),
        "visible_targets": count,
    }


def _validated_episodes(episodes, partition):
    try:
        partition = DatasetPartition(partition)
    except (TypeError, ValueError) as error:
        raise ValueError("partition must be train or development") from error
    if partition not in (DatasetPartition.TRAIN, DatasetPartition.DEVELOPMENT):
        raise ValueError("partition must be train or development")
    validated = [EpisodeTrajectory.model_validate(episode) for episode in episodes]
    ids, worlds, source = set(), set(), None
    for episode in validated:
        context = episode.initial.context
        if context.partition is not partition:
            raise ValueError("memory evaluation episodes must match the declared partition")
        if context.episode_id in ids or context.environment_instance_id in worlds:
            raise ValueError(
                "memory evaluation episodes and environment instances must be distinct"
            )
        ids.add(context.episode_id)
        worlds.add(context.environment_instance_id)
        for transition in episode.transitions:
            request = transition.action_request
            current_source = (request.actor, request.assistance)
            if source is not None and current_source != source:
                raise ValueError("memory evaluation requires one consistent action source")
            source = current_source
    return validated, partition


def evaluate_one_step_memory(
    model,
    episodes: Sequence[EpisodeTrajectory],
    *,
    partition: DatasetPartition,
    before_work: Callable[[int], None],
    seed: int = 3901,
    support_ticks: int = 32,
    particles: int = 8,
) -> dict:
    """Frozen dense readback of o_(t-1) after observing o_t, t >= support_ticks.

    The full-history tail and a reset-history tail share the current observation
    and its random key. Copy-current and the fixed current codec are scored on
    the same past-visible targets; changed means different from the currently
    visible symbol. Only the public trajectory enters this diagnostic.

    Every initial observation, feedback edge (imagine then observe), and reset
    observation reserves eight units before any associated model/tensor work.
    The fixed head's readout is included in these units. No optimizer, fitted
    probe, private state, or parameter modification is used here.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(support_ticks) is not int or support_ticks < 1:
        raise ValueError("support_ticks must be a positive integer")
    if type(particles) is not int or particles != 8:
        raise ValueError("particles must be exactly 8")
    episodes, partition = _validated_episodes(episodes, partition)
    summaries = {name: _Summary() for name in METHODS}
    per_world = []
    initial_units = feedback_units = reset_units = query_count = 0
    rng = np.random.default_rng(seed)

    for episode in episodes:
        observations = [episode.initial.payload] + [
            item.next_observation.payload for item in episode.transitions
        ]
        ticks = list(range(support_ticks, len(observations)))
        local = {name: _Summary() for name in METHODS}
        if ticks:
            before_work(particles)
            initial_units += particles
            import mlx.core as mx

            def observe(h, observation, sample_seed):
                return model.observe(
                    h,
                    mx.array([observation.symbols] * particles, dtype=mx.int32),
                    mx.array([observation.visible_mask] * particles, dtype=mx.bool_),
                    mx.array([observation.cursor] * particles, dtype=mx.int32),
                    key=mx.random.key(sample_seed),
                )

            def probabilities(state, *, start):
                if state["h"].shape != (particles, 256):
                    raise ValueError("memory state must have shape [8,256]")
                logits = model.symbol_readout(
                    state["h"][:, start : start + 128].reshape(particles, 8, 16)
                )
                return _mean_probabilities(logits, (particles, 8, 256))

            h, _ = model.initial(particles)
            state = observe(h, observations[0], int(rng.integers(0, 2**32)))
            for tick, transition in enumerate(episode.transitions, start=1):
                before_work(particles)
                feedback_units += particles
                imagined = model.imagine(
                    state["h"],
                    state["z"],
                    mx.full((particles,), transition.action_request.action, dtype=mx.int32),
                    key=mx.random.key(int(rng.integers(0, 2**32))),
                )
                sample_seed = int(rng.integers(0, 2**32))
                current = observations[tick]
                state = observe(imagined["h"], current, sample_seed)
                if tick < support_ticks:
                    continue
                query_count += 1
                predictions = {
                    "memory_tail": probabilities(state, start=128),
                    "fixed_current_codec": probabilities(state, start=0),
                    "copy_current": copy_probabilities(
                        np.asarray(current.symbols), np.asarray(current.visible_mask)
                    ),
                }
                before_work(particles)
                reset_units += particles
                reset_h, _ = model.initial(particles)
                reset = observe(reset_h, current, sample_seed)
                predictions["reset_history"] = probabilities(reset, start=128)
                target = observations[tick - 1]
                for name in METHODS:
                    result = symbol_metrics(
                        predictions[name],
                        np.asarray(target.symbols),
                        np.asarray(target.visible_mask),
                        np.asarray(current.symbols),
                        np.asarray(current.visible_mask),
                    )
                    summaries[name].add(result)
                    local[name].add(result)
        per_world.append(
            {
                "episode_id": str(episode.initial.context.episode_id),
                "environment_instance_id": str(episode.initial.context.environment_instance_id),
                "query_count": len(ticks),
                "query_ticks": ticks,
                "methods": {name: summary.result() for name, summary in local.items()},
            }
        )
    return {
        "schema_version": 1,
        "scope": "one_step_previous_public_observation_retention_after_current_observation",
        "partition": partition.value,
        "seed": seed,
        "particles": particles,
        "support_ticks": support_ticks,
        "query_stride": 1,
        "query_count": query_count,
        "methods": {name: summary.result() for name, summary in summaries.items()},
        "per_world": per_world,
        "initial_observation_encodes": initial_units,
        "feedback_model_transitions": feedback_units,
        "reset_observation_encodes": reset_units,
        "logical_model_transitions": initial_units + feedback_units + reset_units,
        "budget_unit": "particle_initial_observations_feedback_edges_and_reset_observations",
        "protocol": {
            "target": "previous_observation_visible_symbols",
            "readout": "fixed_symbol_head_on_post_current_observation_h_tail",
            "changed_reference": "current_observation_visible_symbols",
            "reset_control": "zero_state_then_identical_current_observation_and_random_key",
            "weight_updates": False,
            "fitted_readout": False,
            "private_state": False,
            "longer_delay_memory": "not_evaluated",
            "promotion": "not_authorized_by_this_diagnostic",
        },
    }
