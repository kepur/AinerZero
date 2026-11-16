"""Frozen, public-trajectory development evaluation with causal query rollouts.

Support and later feedback update belief only. Each prediction starts before its
target observations, rolls forward using recorded actions, and averages eight
particle probabilities before computing NLL. This is an offline prediction
diagnostic, not evidence of autonomous exploration or goal-directed control.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from ainerzero.core.contracts import SymbolObservation
from ainerzero.core.experience import DatasetPartition
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import NoActionBaseline, copy_probabilities, symbol_metrics


@dataclass
class _Summary:
    loss: float = 0.0
    count: int = 0
    correct: float = 0.0
    changed_loss: float = 0.0
    changed_count: int = 0
    changed_correct: float = 0.0
    unchanged_loss: float = 0.0
    unchanged_count: int = 0
    unchanged_correct: float = 0.0

    def add(self, result: dict) -> None:
        if result["count"]:
            self.loss += result["nll"] * result["count"]
            self.correct += result["accuracy"] * result["count"]
            self.count += result["count"]
        if result["changed_count"]:
            self.changed_loss += result["changed_nll"] * result["changed_count"]
            self.changed_count += result["changed_count"]
            self.changed_correct += result["changed_accuracy"] * result["changed_count"]
        if result["unchanged_count"]:
            self.unchanged_loss += result["unchanged_nll"] * result["unchanged_count"]
            self.unchanged_correct += result["unchanged_accuracy"] * result["unchanged_count"]
            self.unchanged_count += result["unchanged_count"]

    def result(self) -> dict:
        return {
            "nll": self.loss / self.count if self.count else None,
            "count": self.count,
            "accuracy": self.correct / self.count if self.count else None,
            "changed_nll": self.changed_loss / self.changed_count if self.changed_count else None,
            "changed_count": self.changed_count,
            "changed_accuracy": self.changed_correct / self.changed_count
            if self.changed_count
            else None,
            "unchanged_count": self.unchanged_count,
            "unchanged_nll": self.unchanged_loss / self.unchanged_count
            if self.unchanged_count
            else None,
            "unchanged_accuracy": self.unchanged_correct / self.unchanged_count
            if self.unchanged_count
            else None,
        }


class _Metrics:
    def __init__(
        self, training_symbol_support: np.ndarray | None = None, *, history_groups=False
    ) -> None:
        self.groups = {name: _Summary() for name in ("all", "seen", "unseen")}
        self.training_symbol_support = training_symbol_support
        self.training_support_mass = 0.0
        self.training_support_count = 0
        self.history_groups = history_groups
        if history_groups:
            self.groups.update(
                {
                    name: _Summary()
                    for name in ("history_seen_at_position", "history_unseen_at_position")
                }
            )
        if training_symbol_support is not None:
            self.groups.update(
                {
                    name: _Summary()
                    for name in ("training_seen_at_position", "training_unseen_at_position")
                }
            )

    def add(
        self,
        probabilities: np.ndarray,
        current: SymbolObservation,
        target: SymbolObservation,
        seen: set[int],
        position_seen: np.ndarray | None = None,
    ) -> None:
        symbols = np.asarray(target.symbols)
        visible = np.asarray(target.visible_mask)
        known = np.isin(symbols, tuple(seen))
        masks = {"all": visible, "seen": visible & known, "unseen": visible & ~known}
        if self.history_groups:
            if position_seen is None or position_seen.shape != (8, 256):
                raise ValueError("history metrics require per-position prefix support")
            positional_known = position_seen[np.arange(8), symbols]
            masks.update(
                history_seen_at_position=visible & positional_known,
                history_unseen_at_position=visible & ~positional_known,
            )
        if self.training_symbol_support is not None:
            support = self.training_symbol_support
            training_known = support[np.arange(8), symbols]
            masks.update(
                training_seen_at_position=visible & training_known,
                training_unseen_at_position=visible & ~training_known,
            )
            self.training_support_mass += float(
                np.sum(np.sum(probabilities * support, axis=-1)[visible])
            )
            self.training_support_count += int(visible.sum())
        for name, group in self.groups.items():
            group.add(
                symbol_metrics(
                    probabilities,
                    symbols,
                    masks[name],
                    np.asarray(current.symbols),
                    np.asarray(current.visible_mask),
                )
            )

    def result(self) -> dict:
        result = self.groups["all"].result()
        result.update(
            {name: group.result() for name, group in self.groups.items() if name != "all"}
        )
        if self.training_symbol_support is not None:
            result["mean_probability_on_training_support"] = (
                self.training_support_mass / self.training_support_count
                if self.training_support_count
                else None
            )
        return result


def _mean_probabilities(logits, expected_shape: tuple[int, ...]) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    if values.shape != expected_shape or not np.isfinite(values).all():
        raise ValueError(f"model logits must be finite with shape {expected_shape}")
    values = values - values.max(axis=-1, keepdims=True)
    probabilities = np.maximum(np.exp(values), np.finfo(np.float64).tiny)
    probabilities /= probabilities.sum(axis=-1, keepdims=True)
    # Mean probabilities, never mean particle NLL or softmax(mean(logits)).
    return probabilities.mean(axis=0)


def _validate_episodes(episodes: Sequence[EpisodeTrajectory]) -> list[EpisodeTrajectory]:
    validated = [EpisodeTrajectory.model_validate(episode) for episode in episodes]
    ids = set()
    worlds = set()
    source = None
    for episode in validated:
        context = episode.initial.context
        if context.partition is not DatasetPartition.DEVELOPMENT:
            raise ValueError("prediction evaluation accepts only development episodes")
        if context.episode_id in ids or context.environment_instance_id in worlds:
            raise ValueError("development episodes and environment instances must be distinct")
        ids.add(context.episode_id)
        worlds.add(context.environment_instance_id)
        for transition in episode.transitions:
            request = transition.action_request
            current_source = (request.actor, request.assistance)
            if source is not None and current_source != source:
                raise ValueError("evaluation must use one consistent action actor and assistance")
            source = current_source
    return validated


def evaluate_predictor(
    model,
    episodes: Sequence[EpisodeTrajectory],
    baseline: NoActionBaseline,
    *,
    seed: int = 700,
    support_ticks: int = 32,
    query_stride: int = 8,
    particles: int = 8,
    before_work: Callable[[int], None] | None = None,
    action_ablation: bool = False,
    training_symbol_support: np.ndarray | None = None,
    history_ablation: bool = False,
) -> dict:
    """Score frozen weights on shared 1/4-step queries after a support prefix.

    ``before_work`` runs before every bounded model transition batch. One real
    feedback edge (prior then posterior) or one imagined edge costs eight
    logical transitions; initial observation calls it with zero for a time check.
    The callback owns budget enforcement. No optimizer or private world state
    is accessed. Evaluation never changes model parameters or training mode.
    Optional [8,256] boolean training support only stratifies reported metrics;
    it is never an input to the model or the action rollouts.
    History interventions replay public prefixes independently at each query;
    their extra initial observations each cost eight encodes. Their prefix
    rebuild cost is reported separately from their imagined rollout cost.
    """
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("evaluation seed must be an integer in [0, 2**32)")
    if type(support_ticks) is not int or not 0 <= support_ticks <= 128:
        raise ValueError("support_ticks must be an integer in [0, 128]")
    if type(query_stride) is not int or not 1 <= query_stride <= 128:
        raise ValueError("query_stride must be an integer in [1, 128]")
    if type(particles) is not int or particles != 8:
        raise ValueError("the registered evaluation requires exactly eight particles")
    if type(action_ablation) is not bool:
        raise ValueError("action_ablation must be boolean")
    if type(history_ablation) is not bool:
        raise ValueError("history_ablation must be boolean")
    if training_symbol_support is not None:
        if (
            not isinstance(training_symbol_support, np.ndarray)
            or training_symbol_support.shape != (8, 256)
            or training_symbol_support.dtype != np.bool_
        ):
            raise ValueError(
                "training_symbol_support must be a boolean numpy array with shape [8,256]"
            )
        training_symbol_support = training_symbol_support.copy()
    episodes = _validate_episodes(episodes)
    # Keep tensor runtime optional until an actual model evaluation is requested.
    import mlx.core as mx

    methods = ("model", "copy", "no_action") + (("action_ablation",) if action_ablation else ())
    if history_ablation:
        methods += ("reset_history", "shuffled_history")
    metrics = {
        horizon: {
            name: _Metrics(training_symbol_support, history_groups=history_ablation)
            for name in methods
        }
        for horizon in (1, 4)
    }
    horizon_queries = {1: 0, 4: 0}
    probes = {
        horizon: dict(symbol_changes=0, symbol_count=0, cursor_changes=0) for horizon in (1, 4)
    }
    logical_transitions = feedback_transitions = rollout_transitions = query_count = 0
    actor = assistance = None
    feedback_seed, query_seed = np.random.SeedSequence(seed).spawn(2)
    feedback_rng = np.random.default_rng(feedback_seed)
    query_rng = np.random.default_rng(query_seed)
    # An independent diagnostic stream must not shift existing feedback/query keys.
    shuffle_rng = np.random.default_rng(np.random.SeedSequence([seed, 4901]))
    history_transitions = 0
    shuffled_queries = 0
    sensitivity = {
        h: {
            name: dict(
                tv_sum=0.0,
                cells=0,
                changed_tv_sum=0.0,
                changed_cells=0,
                argmax_changes=0,
                changed_argmax_changes=0,
                nll_delta_sum=0.0,
                changed_nll_delta_sum=0.0,
            )
            for name in ("reset_history", "shuffled_history")
        }
        for h in (1, 4)
    }

    def key(rng):
        return mx.random.key(int(rng.integers(0, 2**32)))

    def reserve(count: int, *, feedback: bool = False, history: bool = False) -> None:
        nonlocal logical_transitions, feedback_transitions, rollout_transitions, history_transitions
        if before_work is not None:
            before_work(count)
        logical_transitions += count
        if history:
            history_transitions += count
        elif feedback:
            feedback_transitions += count
        else:
            rollout_transitions += count

    def observe(h, observation: SymbolObservation, sample_key=None):
        state = model.observe(
            h,
            mx.array([observation.symbols] * particles, dtype=mx.int32),
            mx.array([observation.visible_mask] * particles, dtype=mx.bool_),
            mx.array([observation.cursor] * particles, dtype=mx.int32),
            key=key(feedback_rng) if sample_key is None else sample_key,
        )
        mx.eval(state["h"], state["z"])
        return state["h"], state["z"]

    def rollout(h, z, actions: list[int], keys: list, *, rotate: bool = False):
        predictions = {}
        for offset, (action, sample_key) in enumerate(zip(actions, keys, strict=True), start=1):
            reserve(particles)
            chosen = (action + 1) % 4 if rotate else action
            state = model.imagine(
                h, z, mx.full((particles,), chosen, dtype=mx.int32), key=sample_key
            )
            h, z = state["h"], state["z"]
            mx.eval(h, z)
            if offset in (1, 4):
                predictions[offset] = (
                    _mean_probabilities(state["logits"]["symbols"], (particles, 8, 256)),
                    _mean_probabilities(state["logits"]["cursor"], (particles, 8)),
                )
        return predictions

    for episode in episodes:
        count = len(episode.transitions)
        query_ticks = set(range(support_ticks, count, query_stride))
        if not query_ticks:
            continue
        observations = [episode.initial.payload] + [
            transition.next_observation.payload for transition in episode.transitions
        ]
        actions = [transition.action_request.action for transition in episode.transitions]
        request = episode.transitions[0].action_request
        actor = request.actor.model_dump(mode="json")
        assistance = [value.value for value in request.assistance]
        reserve(0)
        h, _ = model.initial(particles)
        observation_keys = [key(feedback_rng)]
        feedback_keys = []
        h, z = observe(h, observations[0], observation_keys[0])
        seen = set()
        position_seen = np.zeros((8, 256), dtype=np.bool_)
        for tick in range(max(query_ticks) + 1):
            current = observations[tick]
            seen.update(
                symbol
                for symbol, visible in zip(current.symbols, current.visible_mask, strict=True)
                if visible
            )
            for position, (symbol, visible) in enumerate(
                zip(current.symbols, current.visible_mask, strict=True)
            ):
                if visible:
                    position_seen[position, symbol] = True
            if tick in query_ticks:
                query_count += 1
                # A tail query with <4 remaining ticks contributes only horizon 1.
                width = 4 if tick + 4 <= count else 1
                sample_keys = [key(query_rng) for _ in range(width)]
                predictions = rollout(h, z, actions[tick : tick + width], sample_keys)
                ablated = (
                    rollout(h, z, actions[tick : tick + width], sample_keys, rotate=True)
                    if action_ablation
                    else {}
                )
                history_predictions = {}
                if history_ablation:
                    # Reset: keep only the identical current frame. Common current
                    # observation and rollout noise isolate the history intervention.
                    reserve(particles, history=True)
                    reset_h, _ = model.initial(particles)
                    reset_h, reset_z = observe(reset_h, current, observation_keys[tick])
                    history_predictions["reset_history"] = rollout(
                        reset_h, reset_z, actions[tick : tick + width], sample_keys
                    )

                    # Shuffle incoming (action, outcome observation) pairs strictly
                    # before the last real feedback pair. Preserve initial/current
                    # observations and the immediate preceding action. This is an
                    # intentionally incoherent history, not an alternate valid world.
                    order = shuffle_rng.permutation(max(tick - 1, 0)).tolist()
                    shuffled_queries += int(order != list(range(max(tick - 1, 0))))
                    if tick:
                        order.append(tick - 1)
                    reserve(particles, history=True)
                    shuffle_h, _ = model.initial(particles)
                    shuffle_h, shuffle_z = observe(shuffle_h, observations[0], observation_keys[0])
                    for slot, source_index in enumerate(order):
                        reserve(particles, history=True)
                        past = model.imagine(
                            shuffle_h,
                            shuffle_z,
                            mx.full((particles,), actions[source_index], dtype=mx.int32),
                            key=feedback_keys[slot],
                        )
                        shuffle_h, shuffle_z = observe(
                            past["h"], observations[source_index + 1], observation_keys[slot + 1]
                        )
                    history_predictions["shuffled_history"] = rollout(
                        shuffle_h, shuffle_z, actions[tick : tick + width], sample_keys
                    )
                current_symbols = np.asarray(current.symbols)
                current_visible = np.asarray(current.visible_mask)
                for horizon, (probabilities, cursor) in predictions.items():
                    horizon_queries[horizon] += 1
                    target = observations[tick + horizon]
                    values = {
                        "model": probabilities,
                        "copy": copy_probabilities(current_symbols, current_visible),
                        "no_action": baseline.predict(
                            current_symbols, current_visible, horizon=horizon
                        ),
                    }
                    if action_ablation:
                        changed, changed_cursor = ablated[horizon]
                        values["action_ablation"] = changed
                        probe = probes[horizon]
                        probe["symbol_changes"] += int(
                            np.sum(probabilities.argmax(axis=-1) != changed.argmax(axis=-1))
                        )
                        probe["symbol_count"] += 8
                        probe["cursor_changes"] += int(cursor.argmax() != changed_cursor.argmax())
                    if history_ablation:
                        visible = np.asarray(target.visible_mask)
                        changed_mask = (
                            visible
                            & current_visible
                            & (np.asarray(target.symbols) != current_symbols)
                        )
                        target_indices = np.asarray(target.symbols)[..., None]
                        full_nll = -np.log(
                            np.take_along_axis(probabilities, target_indices, axis=-1)[:, 0]
                        )
                        for name, imagined in history_predictions.items():
                            altered, _ = imagined[horizon]
                            values[name] = altered
                            tv = np.sum(np.abs(probabilities - altered), axis=-1) / 2
                            diff = probabilities.argmax(-1) != altered.argmax(-1)
                            delta = (
                                -np.log(np.take_along_axis(altered, target_indices, axis=-1)[:, 0])
                                - full_nll
                            )
                            probe = sensitivity[horizon][name]
                            probe["tv_sum"] += float(tv[visible].sum())
                            probe["cells"] += int(visible.sum())
                            probe["changed_tv_sum"] += float(tv[changed_mask].sum())
                            probe["changed_cells"] += int(changed_mask.sum())
                            probe["argmax_changes"] += int(diff[visible].sum())
                            probe["changed_argmax_changes"] += int(diff[changed_mask].sum())
                            probe["nll_delta_sum"] += float(delta[visible].sum())
                            probe["changed_nll_delta_sum"] += float(delta[changed_mask].sum())
                    for name, value in values.items():
                        metrics[horizon][name].add(value, current, target, seen, position_seen)
            if tick < max(query_ticks):
                reserve(particles, feedback=True)
                feedback_keys.append(key(feedback_rng))
                predicted = model.imagine(
                    h,
                    z,
                    mx.full((particles,), actions[tick], dtype=mx.int32),
                    key=feedback_keys[-1],
                )
                # Only real feedback enters the next online posterior. Query
                # rollouts and action perturbations never replace online belief.
                observation_keys.append(key(feedback_rng))
                h, z = observe(predicted["h"], observations[tick + 1], observation_keys[-1])

    horizons = {}
    for horizon, buckets in metrics.items():
        result = {name: metric.result() for name, metric in buckets.items()}
        result["query_count"] = horizon_queries[horizon]
        if action_ablation:
            probe = probes[horizon]
            result["action_probe"] = {
                **probe,
                "symbol_change_fraction": probe["symbol_changes"] / probe["symbol_count"]
                if probe["symbol_count"]
                else None,
                "cursor_change_fraction": probe["cursor_changes"] / horizon_queries[horizon]
                if horizon_queries[horizon]
                else None,
                "interpretation": "diagnostic_only_no_automatic_pass",
            }
        if history_ablation:
            result["history_probe"] = {}
            for name, probe in sensitivity[horizon].items():
                cells, changed = probe["cells"], probe["changed_cells"]
                result["history_probe"][name] = {
                    "count": cells,
                    "changed_count": changed,
                    "mean_total_variation": probe["tv_sum"] / cells if cells else None,
                    "changed_mean_total_variation": probe["changed_tv_sum"] / changed
                    if changed
                    else None,
                    "argmax_change_count": probe["argmax_changes"],
                    "changed_argmax_change_count": probe["changed_argmax_changes"],
                    "nll_delta_from_full": probe["nll_delta_sum"] / cells if cells else None,
                    "changed_nll_delta_from_full": probe["changed_nll_delta_sum"] / changed
                    if changed
                    else None,
                    "delta_interpretation": "positive_means_full_history_has_lower_nll; diagnostic_only_not_a_pass",
                }
        horizons[str(horizon)] = result
    report = {
        "horizons": horizons,
        "query_count": query_count,
        "episode_count": len(episodes),
        "logical_model_transitions": logical_transitions,
        "feedback_model_transitions": feedback_transitions,
        "rollout_model_transitions": rollout_transitions,
        "eval_seed": seed,
        "actor": actor,
        "assistance": assistance,
        "protocol": {
            "partition": "development",
            "support_ticks": support_ticks,
            "query_stride": query_stride,
            "particles": particles,
            "weights": "frozen",
            "belief": "causal_actual_feedback_carried_within_episode_only",
            "particle_reduction": "mean_probabilities_then_nll",
            "aggregation": "global_visible_cell_weighted",
            "seen_definition": "target_byte_observed_in_visible_history_through_query_tick",
            "action_ablation": "rotate_recorded_action_plus_one_mod_four_same_keys"
            if action_ablation
            else "disabled",
            "initial_observation_transition_cost": 0,
            "goal_control": "not_evaluated",
        },
    }
    if history_ablation:
        report["history_model_transitions"] = history_transitions
        report["protocol"].update(
            history_ablation="reset_at_query_and_shuffle_earlier_incoming_feedback_pairs_keep_initial_and_final_pair",
            history_shuffle_seed=[seed, 4901],
            reordered_query_count=shuffled_queries,
            history_group_definition="target_byte_seen_at_same_position_in_original_public_prefix_through_query; shared_across_ablations",
            history_confounds="shuffle_breaks_valid_world_order; reset_changes_prefix_length; null_effect_does_not_prove_empty_memory",
            current_observation_and_future_actions="identical_across_methods",
            stochastic_keys="original_full_stream_unchanged; replay_slot_keys_and_current_observation_key_shared",
            history_initial_observation_cost=particles,
            history_counter_scope="prefix_reconstruction_only; intervention_predictions_in_rollout_counter",
        )
    return report
