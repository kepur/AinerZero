"""Frozen observation reconstruction from transient state, using public evidence.

This screen tests an observation encoder and decoder before learning dynamics.
It does not establish long-term memory, action understanding, or prediction.
Tensor runtime imports remain lazy and follow the first successful reservation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from numbers import Real

import numpy as np

from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.baselines import symbol_metrics
from ainerzero.learning.evaluation import _Summary, _validate_episodes

PARTICLES = 8
QUERY_STRIDE = 8


def reconstruction_gate(evaluation: dict) -> dict:
    """A development prerequisite screen, never a dynamics or promotion gate."""
    real = evaluation.get("model", {})
    zero = evaluation.get("zero_symbols", {})

    def finite(value) -> bool:
        return isinstance(value, Real) and not isinstance(value, bool) and np.isfinite(value)

    count = real.get("count")
    measurable = (
        type(count) is int
        and count > 0
        and type(zero.get("count")) is int
        and zero["count"] == count
        and all(finite(row.get(key)) for row in (real, zero) for key in ("nll", "accuracy"))
        and all(0 <= row["accuracy"] <= 1 and row["nll"] >= 0 for row in (real, zero))
    )
    positions = real.get("per_position", [])
    position_accuracy = (
        len(positions) == 8
        and all(type(row.get("count")) is int and row["count"] >= 0 for row in positions)
        and sum(row["count"] for row in positions) == count
        and all(
            finite(row.get("accuracy")) and 0.95 <= row["accuracy"] <= 1
            for row in positions
            if row["count"]
        )
    )
    checks = {
        "measurable_visible_targets": bool(measurable),
        "reconstruction_accuracy_at_least_0_95": bool(measurable and real["accuracy"] >= 0.95),
        "reconstruction_nll_at_most_0_3": bool(measurable and real["nll"] <= 0.3),
        "each_measured_position_accuracy_at_least_0_95": bool(measurable and position_accuracy),
        "zero_input_accuracy_at_most_0_1": bool(measurable and zero["accuracy"] <= 0.1),
        "zero_input_nll_increase_at_least_2": bool(measurable and zero["nll"] - real["nll"] >= 2.0),
        "state_roundtrip_equal": evaluation.get("state_roundtrip_equal") is True,
    }
    return {
        "status": "passed" if all(checks.values()) else "not_passed",
        "scope": "development_observation_reconstruction_only",
        "checks": checks,
        "dynamics": "not_evaluated",
        "long_term_memory": "not_evaluated",
        "promotion": "not_authorized_by_this_screen",
    }


def evaluate_reconstruction(
    model,
    episodes: Sequence[EpisodeTrajectory],
    *,
    before_work: Callable[[int], None],
    seed: int = 1700,
    batch_size: int = 32,
) -> dict:
    """Reconstruct current observations through returned h/z and explicit decode.

    Every episode contributes observations at ticks 0, 8, ... and its final tick.
    Each observation starts from zero history; no recorded action is dispatched.
    Eight sampled posterior probabilities are averaged before scoring. The zero
    input ablation retains the original labels, cursor, masks, and random key.

    Each real/ablated branch reserves ``8 * batch_observations`` *observation
    encodes* before runtime import, array creation, initialization, or inference.
    One such bounded slot includes observe, explicit decode, and another decode
    after h/z pass through NumPy. These counts are not environment steps or
    unique observations. The callback must enforce time and resource budgets.
    NumPy roundtrip tests temporary-state transport, not persistent cognition.
    """
    if not callable(before_work):
        raise ValueError("before_work must be a budget reservation callback")
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("reconstruction seed must be an integer in [0, 2**32)")
    if type(batch_size) is not int or not 1 <= batch_size <= 256:
        raise ValueError("batch_size must be an integer in [1, 256]")
    episodes = _validate_episodes(episodes)
    observations = []
    sampled_ticks = []
    for episode in episodes:
        sequence = [episode.initial.payload] + [
            transition.next_observation.payload for transition in episode.transitions
        ]
        ticks = sorted(set(range(0, len(sequence), QUERY_STRIDE)) | {len(sequence) - 1})
        observations.extend(sequence[tick] for tick in ticks)
        sampled_ticks.append(
            {"episode_id": str(episode.initial.context.episode_id), "ticks": ticks}
        )

    summaries = {name: _Summary() for name in ("model", "zero_symbols")}
    position_summaries = {name: [_Summary() for _ in range(8)] for name in summaries}
    rng = np.random.default_rng(seed)
    observation_encodes = state_checks = 0
    roundtrip_equal = True
    for start in range(0, len(observations), batch_size):
        batch = observations[start : start + batch_size]
        size = len(batch)
        symbols = np.asarray([item.symbols for item in batch], dtype=np.int32)
        visible = np.asarray([item.visible_mask for item in batch], dtype=np.bool_)
        cursor = np.asarray([item.cursor for item in batch], dtype=np.int32)
        sample_seed = int(rng.integers(0, 2**32))
        for name in summaries:
            before_work(PARTICLES * size)
            observation_encodes += PARTICLES * size
            # A failed reservation cannot initialize the tensor runtime or model.
            import mlx.core as mx

            inputs = symbols if name == "model" else np.zeros_like(symbols)
            input_symbols = np.broadcast_to(inputs, (PARTICLES, size, 8)).reshape(-1, 8)
            input_visible = np.broadcast_to(visible, (PARTICLES, size, 8)).reshape(-1, 8)
            input_cursor = np.broadcast_to(cursor, (PARTICLES, size)).reshape(-1)
            h, _ = model.initial(PARTICLES * size)
            state = model.observe(
                h,
                mx.array(input_symbols, dtype=mx.int32),
                mx.array(input_visible, dtype=mx.bool_),
                mx.array(input_cursor, dtype=mx.int32),
                key=mx.random.key(sample_seed),
            )
            h, z = state["h"], state["z"]
            mx.eval(h, z)
            stored_h, stored_z = np.array(h, copy=True), np.array(z, copy=True)
            if (
                stored_h.ndim < 1
                or stored_z.ndim < 1
                or stored_h.shape[0] != PARTICLES * size
                or stored_z.shape[0] != PARTICLES * size
                or not np.isfinite(stored_h).all()
                or not np.isfinite(stored_z).all()
            ):
                raise ValueError("reconstruction state must be finite with the particle batch size")
            # Ignore any logits returned by observe: decoding must consume h/z.
            decoded = model.decode(h, z)
            restored_h, restored_z = mx.array(stored_h), mx.array(stored_z)
            restored = model.decode(restored_h, restored_z)
            logits = np.asarray(decoded["symbols"], dtype=np.float64)
            if logits.shape != (PARTICLES * size, 8, 256) or not np.isfinite(logits).all():
                raise ValueError("reconstruction logits must be finite with shape [8*B,8,256]")
            state_checks += PARTICLES * size
            equal = (
                np.array_equal(np.asarray(restored_h), stored_h)
                and np.array_equal(np.asarray(restored_z), stored_z)
                and set(decoded) == set(restored)
            )
            for output in decoded:
                if output not in restored:
                    equal = False
                    continue
                original, recovered = np.asarray(decoded[output]), np.asarray(restored[output])
                equal = bool(
                    equal
                    and original.shape == recovered.shape
                    and np.isfinite(original).all()
                    and np.isfinite(recovered).all()
                    and np.allclose(original, recovered, rtol=1e-5, atol=2e-5)
                )
            roundtrip_equal &= equal
            logits = logits.reshape(PARTICLES, size, 8, 256)
            logits -= logits.max(axis=-1, keepdims=True)
            probabilities = np.maximum(np.exp(logits), np.finfo(np.float64).tiny)
            probabilities /= probabilities.sum(axis=-1, keepdims=True)
            mean_probabilities = probabilities.mean(axis=0)
            summaries[name].add(symbol_metrics(mean_probabilities, symbols, visible))
            for position, summary in enumerate(position_summaries[name]):
                position_mask = np.zeros_like(visible)
                position_mask[:, position] = visible[:, position]
                summary.add(symbol_metrics(mean_probabilities, symbols, position_mask))

    metrics = {name: summary.result() for name, summary in summaries.items()}
    for name, row in metrics.items():
        row["per_position"] = [
            {"position": index, **summary.result()}
            for index, summary in enumerate(position_summaries[name])
        ]
    real, zero = metrics["model"], metrics["zero_symbols"]
    result = {
        "schema_version": 1,
        "scope": "public_development_observations_no_actions_no_weight_updates",
        "generalization_scope": "new_worlds_and_observation_combinations_not_unseen_byte_vocabulary",
        "seed": seed,
        "particles": PARTICLES,
        "batch_size": batch_size,
        "query_stride": QUERY_STRIDE,
        "include_episode_final_tick": True,
        "sampled_ticks": sampled_ticks,
        "observation_count": len(observations),
        "observation_encodes": observation_encodes,
        "budget_unit": "particle_observation_encodes_including_zero_input_ablation",
        "state_roundtrip_checks": state_checks,
        "state_roundtrip_equal": bool(state_checks and roundtrip_equal),
        "state_roundtrip_scope": "transient_h_z_numpy_transport_not_long_term_memory",
        "ablation_gap": {
            "accuracy_drop": real["accuracy"] - zero["accuracy"] if real["count"] else None,
            "nll_increase": zero["nll"] - real["nll"] if real["count"] else None,
        },
        **metrics,
    }
    result["gate"] = reconstruction_gate(result)
    return result
