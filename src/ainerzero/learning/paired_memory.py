"""Frozen same-edge history versus zero-context memory diagnosis.

All 2,560 public feedback edges are scored. Fitted edges are identified by the
exact M2j selection manifest; other training edges are not independent held-out
examples. No private state, fitted readout, optimizer, or model update is used.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

import numpy as np

from ainerzero.core.experience import DatasetPartition
from ainerzero.learning.baselines import copy_probabilities, symbol_metrics
from ainerzero.learning.evaluation import _mean_probabilities, _Summary
from ainerzero.learning.micro_memory import _digest, select_micro_memory_samples
from ainerzero.learning.one_step_memory import _validated_episodes
from ainerzero.runtime.c0_collection import RANDOM_ACTOR

METHODS = (
    "history_tail",
    "zero_context_tail",
    "reset_history",
    "copy_current",
    "fixed_current_codec",
)
GROUPS = ("fitted_train", "other_train", "development")
PARTITIONS = (DatasetPartition.TRAIN, DatasetPartition.DEVELOPMENT)


def _sensor_identity(observation) -> dict:
    # These are exactly the public fields passed to observe, without IDs/ticks.
    return {
        "symbols": list(observation.symbols),
        "visible_mask": list(observation.visible_mask),
        "cursor": observation.cursor,
    }


def _prepare(episodes_by_partition):
    if not isinstance(episodes_by_partition, Mapping) or set(episodes_by_partition) != set(
        PARTITIONS
    ):
        raise ValueError("paired memory requires exactly train and development partitions")
    ordered = []
    episode_ids, world_ids = set(), set()
    for partition, count in zip(PARTITIONS, (16, 4), strict=True):
        episodes, _ = _validated_episodes(episodes_by_partition[partition], partition)
        if len(episodes) != count:
            raise ValueError(f"paired memory requires exactly {count} {partition.value} worlds")
        episodes.sort(
            key=lambda item: (
                str(item.initial.context.episode_id),
                str(item.initial.context.environment_instance_id),
            )
        )
        for episode in episodes:
            context = episode.initial.context
            if context.episode_id in episode_ids or context.environment_instance_id in world_ids:
                raise ValueError("episodes and worlds must be distinct across both partitions")
            episode_ids.add(context.episode_id)
            world_ids.add(context.environment_instance_id)
            if len(episode.transitions) != 128:
                raise ValueError("paired memory requires exactly 128 transitions per world")
            for item in episode.transitions:
                if item.action_request.actor != RANDOM_ACTOR or item.action_request.assistance:
                    raise ValueError(
                        "paired memory requires the unassisted authorized random actor"
                    )
        ordered.extend(episodes)

    _, selected = select_micro_memory_samples(ordered[:16])
    fitted = {(row["episode_id"], row["query_tick"]) for row in selected["samples"]}
    fitted_previous, fitted_edges = set(), set()
    for episode in ordered[:16]:
        for edge in episode.transitions:
            identity = (str(episode.initial.context.episode_id), edge.next_observation.step)
            if identity in fitted:
                previous = _sensor_identity(edge.observation.payload)
                fitted_previous.add(_digest(previous))
                fitted_edges.add(
                    _digest(
                        {
                            "previous": previous,
                            "current": _sensor_identity(edge.next_observation.payload),
                            "action": edge.action_request.action,
                        }
                    )
                )
    queries = []
    groups = {
        name: {"query_count": 0, "target_visible_count": 0, "changed_count": 0} for name in GROUPS
    }
    for world_index, episode in enumerate(ordered):
        context = episode.initial.context
        for edge in episode.transitions:
            target, current = edge.observation.payload, edge.next_observation.payload
            episode_id, tick = str(context.episode_id), edge.next_observation.step
            group = (
                "development"
                if context.partition is DatasetPartition.DEVELOPMENT
                else "fitted_train"
                if (episode_id, tick) in fitted
                else "other_train"
            )
            target_mask = np.asarray(target.visible_mask)
            changed = (
                target_mask
                & np.asarray(current.visible_mask)
                & (np.asarray(target.symbols) != np.asarray(current.symbols))
            )
            previous = _sensor_identity(target)
            previous_sha = _digest(previous)
            edge_sha = _digest(
                {
                    "previous": previous,
                    "current": _sensor_identity(current),
                    "action": edge.action_request.action,
                }
            )
            row = {
                "row": len(queries),
                "world_index": world_index,
                "episode_id": episode_id,
                "environment_instance_id": str(context.environment_instance_id),
                "partition": context.partition.value,
                "group": group,
                "target_tick": edge.observation.step,
                "query_tick": tick,
                "target_observation_id": str(edge.observation.id),
                "current_observation_id": str(edge.next_observation.id),
                "action_request_id": str(edge.action_request.id),
                "target_visible_count": int(target_mask.sum()),
                "changed_count": int(changed.sum()),
                "previous_input_sha256": previous_sha,
                "edge_input_sha256": edge_sha,
                "previous_input_matches_fitted": previous_sha in fitted_previous,
                "edge_input_matches_fitted": edge_sha in fitted_edges,
                "public_transition_sha256": _digest(edge.model_dump(mode="json")),
            }
            queries.append(row)
            groups[group]["query_count"] += 1
            groups[group]["target_visible_count"] += row["target_visible_count"]
            groups[group]["changed_count"] += row["changed_count"]
    evidence = {
        "schema_version": 1,
        "scope": "same_public_edge_history_vs_zero_context_memory",
        "world_count": 20,
        "query_count": len(queries),
        "ordering": [
            "train_then_development",
            "episode_id",
            "environment_instance_id",
            "query_tick",
        ],
        "micro_fit_sample_manifest_sha256": selected["sample_manifest_sha256"],
        "micro_fit_batch_sha256": selected["batch_sha256"],
        "query_manifest_sha256": _digest(queries),
        "groups": groups,
        "queries": queries,
    }
    return ordered, evidence


def paired_memory_samples(episodes_by_partition) -> dict:
    """Validate public inputs and return CPU-only preregistration evidence."""
    return _prepare(episodes_by_partition)[1]


def _paired_counts(history, zero, target, current) -> dict:
    labels = np.asarray(target.symbols)
    visible = np.asarray(target.visible_mask)
    changed = visible & np.asarray(current.visible_mask) & (labels != np.asarray(current.symbols))
    h_prediction, z_prediction = history.argmax(axis=-1), zero.argmax(axis=-1)
    h_correct, z_correct = h_prediction == labels, z_prediction == labels
    result = {}
    for prefix, mask in (("", visible), ("changed_", changed)):
        result.update(
            {
                f"{prefix}count": int(mask.sum()),
                f"{prefix}history_only_correct": int((mask & h_correct & ~z_correct).sum()),
                f"{prefix}zero_only_correct": int((mask & z_correct & ~h_correct).sum()),
                f"{prefix}both_correct": int((mask & h_correct & z_correct).sum()),
                f"{prefix}neither_correct": int((mask & ~h_correct & ~z_correct).sum()),
                f"{prefix}prediction_disagreements": int(
                    (mask & (h_prediction != z_prediction)).sum()
                ),
            }
        )
    return result


def _paired_result(counts, methods) -> dict:
    result = dict(counts)
    history, zero = methods["history_tail"], methods["zero_context_tail"]
    for field in ("accuracy", "nll", "changed_accuracy", "changed_nll"):
        a, b = history[field], zero[field]
        result[f"history_minus_zero_{field}"] = None if a is None or b is None else a - b
    return result


def evaluate_paired_memory(
    model,
    episodes_by_partition,
    *,
    before_work: Callable[[int], None],
    seed: int = 7103,
    particles: int = 8,
) -> dict:
    """Score identical edges under history, zero context, and current-only reset.

    A branch-independent CPU seed schedule is fixed before any model work. The
    history and zero-context branches share their final previous-observe,
    imagine, and current-observe keys. Continuous history always advances from
    its own prior state. Eight particle probabilities are averaged before loss.

    Each initial observation or imagine/observe edge reserves eight units before
    tensor/model work; readouts are included in those units. Full evaluation costs
    82,080 logical units: 20,640 history + 40,960 zero context + 20,480 reset.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(particles) is not int or particles != 8:
        raise ValueError("particles must be exactly 8")
    episodes, evidence = _prepare(episodes_by_partition)
    rng = np.random.default_rng(seed)
    schedules = [rng.integers(0, 2**32, size=257, dtype=np.uint64).tolist() for _ in episodes]
    groups = {
        name: {"methods": {method: _Summary() for method in METHODS}, "paired": {}}
        for name in GROUPS
    }
    per_query, per_world = [], []
    first_edge_pair_checks = 0
    initial_units = feedback_units = zero_initial_units = zero_feedback_units = reset_units = 0
    for world_index, episode in enumerate(episodes):
        keys = schedules[world_index]
        before_work(particles)
        initial_units += particles
        import mlx.core as mx

        def observe(h, observation, key):
            return model.observe(
                h,
                mx.array([observation.symbols] * particles, dtype=mx.int32),
                mx.array([observation.visible_mask] * particles, dtype=mx.bool_),
                mx.array([observation.cursor] * particles, dtype=mx.int32),
                key=mx.random.key(key),
            )

        def feedback(state, edge, action_key, observation_key):
            imagined = model.imagine(
                state["h"],
                state["z"],
                mx.full((particles,), edge.action_request.action, dtype=mx.int32),
                key=mx.random.key(action_key),
            )
            return observe(imagined["h"], edge.next_observation.payload, observation_key)

        def probabilities(state, offset):
            if state["h"].shape != (particles, 256):
                raise ValueError("paired memory state must have shape [8,256]")
            logits = model.symbol_readout(
                state["h"][:, offset : offset + 128].reshape(particles, 8, 16)
            )
            return _mean_probabilities(logits, (particles, 8, 256))

        h, _ = model.initial(particles)
        history = observe(h, episode.initial.payload, keys[0])
        world_summaries = {method: _Summary() for method in METHODS}
        world_paired = {}
        for tick, edge in enumerate(episode.transitions, start=1):
            previous_key, action_key, current_key = keys[2 * tick - 2 : 2 * tick + 1]
            before_work(particles)
            feedback_units += particles
            history = feedback(history, edge, action_key, current_key)
            predictions = {
                "history_tail": probabilities(history, 128),
                "fixed_current_codec": probabilities(history, 0),
            }

            before_work(particles)
            zero_initial_units += particles
            zero_h, _ = model.initial(particles)
            zero_previous = observe(zero_h, edge.observation.payload, previous_key)
            before_work(particles)
            zero_feedback_units += particles
            zero_posterior = feedback(zero_previous, edge, action_key, current_key)
            predictions["zero_context_tail"] = probabilities(zero_posterior, 128)
            if tick == 1:
                if not np.array_equal(
                    predictions["history_tail"], predictions["zero_context_tail"]
                ):
                    raise ValueError(
                        "first-edge history and zero-context probabilities must match exactly"
                    )
                first_edge_pair_checks += 1

            before_work(particles)
            reset_units += particles
            reset_h, _ = model.initial(particles)
            reset = observe(reset_h, edge.next_observation.payload, current_key)
            predictions["reset_history"] = probabilities(reset, 128)
            target, current = edge.observation.payload, edge.next_observation.payload
            predictions["copy_current"] = copy_probabilities(
                np.asarray(current.symbols), np.asarray(current.visible_mask)
            )
            identity = evidence["queries"][len(per_query)]
            group = groups[identity["group"]]
            methods = {}
            for name in METHODS:
                value = symbol_metrics(
                    predictions[name],
                    np.asarray(target.symbols),
                    np.asarray(target.visible_mask),
                    np.asarray(current.symbols),
                    np.asarray(current.visible_mask),
                )
                methods[name] = value
                group["methods"][name].add(value)
                world_summaries[name].add(value)
            paired = _paired_counts(
                predictions["history_tail"], predictions["zero_context_tail"], target, current
            )
            for counts in (group["paired"], world_paired):
                for name, count in paired.items():
                    counts[name] = counts.get(name, 0) + count
            per_query.append(
                {
                    **identity,
                    "paired_random_seeds": [previous_key, action_key, current_key],
                    "methods": methods,
                    "paired": _paired_result(paired, methods),
                }
            )
        methods = {name: summary.result() for name, summary in world_summaries.items()}
        per_world.append(
            {
                "world_index": world_index,
                "episode_id": str(episode.initial.context.episode_id),
                "environment_instance_id": str(episode.initial.context.environment_instance_id),
                "partition": episode.initial.context.partition.value,
                "query_count": 128,
                "methods": methods,
                "paired": _paired_result(world_paired, methods),
            }
        )
    group_results = {}
    for name, group in groups.items():
        methods = {method: summary.result() for method, summary in group["methods"].items()}
        group_results[name] = {
            **evidence["groups"][name],
            "methods": methods,
            "paired": _paired_result(group["paired"], methods),
        }
    return {
        **{name: value for name, value in evidence.items() if name not in ("queries", "groups")},
        "seed": seed,
        "particles": particles,
        "random_schedule_sha256": _digest(schedules),
        "first_edge_pair_checks": first_edge_pair_checks,
        "first_edge_pairs_identical": first_edge_pair_checks == len(episodes),
        "groups": group_results,
        "per_query": per_query,
        "per_world": per_world,
        "initial_observation_encodes": initial_units,
        "feedback_model_transitions": feedback_units,
        "zero_context_initial_observation_encodes": zero_initial_units,
        "zero_context_feedback_model_transitions": zero_feedback_units,
        "reset_observation_encodes": reset_units,
        "logical_model_transitions": initial_units
        + feedback_units
        + zero_initial_units
        + zero_feedback_units
        + reset_units,
        "budget_unit": "particle_observations_and_feedback_edges_including_readouts",
        "protocol": {
            "target": "previous_observation_visible_symbols",
            "readout": "fixed_symbol_head_on_post_current_observation_h_tail",
            "changed_reference": "current_observation_visible_symbols",
            "paired_noise": "identical_previous_observe_action_and_current_observe_keys",
            "continuous_state": "advanced_only_by_own_original_public_history",
            "particle_aggregation": "mean_probabilities_before_metrics",
            "weight_updates": False,
            "fitted_readout": False,
            "private_state": False,
            "tail_prefilled": False,
            "other_train_independent_holdout": False,
            "m2j_local_scores_directly_comparable": False,
            "m2j_comparison_caveat": "new_seed_and_eight_particles_vs_training_microbatch_single_particle",
            "longer_delay_memory": "not_evaluated",
            "promotion": "not_authorized_by_this_diagnostic",
        },
    }


def zero_context_tail_probabilities(
    model,
    previous,
    action: int,
    current,
    seeds,
    *,
    before_work: Callable[[int], None],
    particles: int = 8,
) -> np.ndarray:
    """M2k zero-context branch for one explicit edge, returned as mean probabilities.

    ``previous``/``current`` are ``(symbols, visible_mask, cursor)`` public frames;
    ``seeds`` are the previous-observe, imagine and current-observe keys. Exactly
    the same tensor construction and readout as ``evaluate_paired_memory``; one
    reservation of ``particles`` units precedes each of the two model chunks.
    """
    import mlx.core as mx

    previous_key, action_key, current_key = (int(seed) for seed in seeds)

    def observe(h, frame, key):
        symbols, visible, cursor = frame
        return model.observe(
            h,
            mx.array([[int(s) for s in symbols]] * particles, dtype=mx.int32),
            mx.array([[bool(v) for v in visible]] * particles, dtype=mx.bool_),
            mx.array([int(cursor)] * particles, dtype=mx.int32),
            key=mx.random.key(key),
        )

    before_work(particles)
    zero_h, _ = model.initial(particles)
    zero_previous = observe(zero_h, previous, previous_key)
    before_work(particles)
    imagined = model.imagine(
        zero_previous["h"],
        zero_previous["z"],
        mx.full((particles,), int(action), dtype=mx.int32),
        key=mx.random.key(action_key),
    )
    posterior = observe(imagined["h"], current, current_key)
    if posterior["h"].shape != (particles, 256):
        raise ValueError("zero-context state must have shape [8,256]")
    logits = model.symbol_readout(posterior["h"][:, 128:256].reshape(particles, 8, 16))
    return _mean_probabilities(logits, (particles, 8, 256))


def _cell_scores(probabilities, targets, visible):
    targets = np.asarray(targets)
    selected = np.take_along_axis(probabilities, targets[:, None], axis=-1)[:, 0]
    nll = np.where(np.asarray(visible, dtype=bool), -np.log(selected), np.nan)
    return probabilities.argmax(axis=-1), nll


def evaluate_zero_context_cells(
    model,
    episodes_by_partition,
    *,
    before_work: Callable[[int], None],
    seed: int = 7103,
    particles: int = 8,
) -> dict:
    """M2m-a A1: only the zero-context branch of all 2,560 queries, per cell.

    The per-world key schedule is identical to ``evaluate_paired_memory``, so
    query metrics must reproduce the zero-context scores of an earlier paired
    run on the same frozen weights exactly. Costs 2 x 8 units per query.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(particles) is not int or particles != 8:
        raise ValueError("particles must be exactly 8")
    episodes, evidence = _prepare(episodes_by_partition)
    rng = np.random.default_rng(seed)
    schedules = [rng.integers(0, 2**32, size=257, dtype=np.uint64).tolist() for _ in episodes]
    per_query, units = [], 0

    def reserve(count):
        nonlocal units
        before_work(count)
        units += count

    for world_index, episode in enumerate(episodes):
        keys = schedules[world_index]
        for tick, edge in enumerate(episode.transitions, start=1):
            seeds = keys[2 * tick - 2 : 2 * tick + 1]
            target, current = edge.observation.payload, edge.next_observation.payload
            probabilities = zero_context_tail_probabilities(
                model,
                (target.symbols, target.visible_mask, target.cursor),
                edge.action_request.action,
                (current.symbols, current.visible_mask, current.cursor),
                seeds,
                before_work=reserve,
                particles=particles,
            )
            argmax, nll = _cell_scores(probabilities, target.symbols, target.visible_mask)
            identity = evidence["queries"][len(per_query)]
            per_query.append(
                {
                    "row": identity["row"],
                    "episode_id": identity["episode_id"],
                    "query_tick": identity["query_tick"],
                    "partition": identity["partition"],
                    "paired_random_seeds": list(seeds),
                    "zero_context_tail": symbol_metrics(
                        probabilities,
                        np.asarray(target.symbols),
                        np.asarray(target.visible_mask),
                        np.asarray(current.symbols),
                        np.asarray(current.visible_mask),
                    ),
                    "cell_argmax": argmax.tolist(),
                    "cell_nll": [None if np.isnan(v) else float(v) for v in nll],
                }
            )
    return {
        "schema_version": 1,
        "scope": "zero_context_branch_only_per_cell_scores",
        "query_count": len(per_query),
        "query_manifest_sha256": evidence["query_manifest_sha256"],
        "seed": seed,
        "particles": particles,
        "random_schedule_sha256": _digest(schedules),
        "per_query": per_query,
        "logical_model_transitions": units,
        "budget_unit": "particle_observations_and_feedback_edges_including_readouts",
        "protocol": {
            "branch": "zero_context_tail_same_keys_as_paired_evaluation",
            "weight_updates": False,
            "private_state": False,
        },
    }


def evaluate_zero_context_inputs(
    model,
    batch: dict[str, np.ndarray],
    seeds,
    *,
    before_work: Callable[[int], None],
    particles: int = 8,
) -> dict:
    """Score explicit two-frame inputs (e.g. substitutions) from zero context.

    ``batch`` holds pool-format arrays ([N,2,8] symbols/mask, [N,2] cursor,
    [N,1] actions); ``seeds`` is [N,3] paired keys. Targets are each input's own
    previous frame. Returns per-cell argmax and NLL; 2 x 8 units per input.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(particles) is not int or particles != 8:
        raise ValueError("particles must be exactly 8")
    symbols, visible = np.asarray(batch["symbols"]), np.asarray(batch["visible_mask"])
    cursor, actions = np.asarray(batch["cursor"]), np.asarray(batch["actions"])
    seeds = [list(map(int, row)) for row in seeds]
    count = len(symbols)
    if (
        symbols.shape != (count, 2, 8)
        or visible.shape != (count, 2, 8)
        or cursor.shape != (count, 2)
        or actions.shape != (count, 1)
        or len(seeds) != count
        or any(len(row) != 3 for row in seeds)
    ):
        raise ValueError("zero-context inputs must be aligned two-frame pool arrays and keys")
    argmax, nll, units = [], [], 0

    def reserve(units_count):
        nonlocal units
        before_work(units_count)
        units += units_count

    for index in range(count):
        probabilities = zero_context_tail_probabilities(
            model,
            (symbols[index, 0], visible[index, 0], cursor[index, 0]),
            int(actions[index, 0]),
            (symbols[index, 1], visible[index, 1], cursor[index, 1]),
            seeds[index],
            before_work=reserve,
            particles=particles,
        )
        cells, losses = _cell_scores(probabilities, symbols[index, 0], visible[index, 0])
        argmax.append(cells)
        nll.append(losses)
    return {
        "argmax": np.asarray(argmax, dtype=np.int32).reshape(count, 8),
        "nll": np.asarray(nll, dtype=np.float64).reshape(count, 8),
        "logical_model_transitions": units,
    }
