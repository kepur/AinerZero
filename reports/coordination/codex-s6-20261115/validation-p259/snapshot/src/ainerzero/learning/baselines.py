"""Frozen copy and action-blind Markov baselines using public observations only."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from ainerzero.core.contracts import CELL_COUNT
from ainerzero.core.experience import DatasetPartition, TrainingPolicy, admit_training
from ainerzero.data.trajectory import EpisodeTrajectory

VOCAB_SIZE = 256
UNIFORM_MIX = 0.01


def _sensor_arrays(symbols: np.ndarray, visible_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    symbols = np.asarray(symbols)
    visible_mask = np.asarray(visible_mask)
    if symbols.ndim < 1 or symbols.shape[-1] != CELL_COUNT:
        raise ValueError("symbols must have shape [..., 8]")
    if symbols.dtype.kind not in "iu" or np.any(symbols < 0) or np.any(symbols >= VOCAB_SIZE):
        raise ValueError("symbols must contain integer bytes in [0, 255]")
    if visible_mask.shape != symbols.shape or visible_mask.dtype.kind != "b":
        raise ValueError("visible_mask must be boolean with the symbols shape")
    return symbols, visible_mask


def copy_probabilities(symbols: np.ndarray, visible_mask: np.ndarray) -> np.ndarray:
    """Persistence prediction with 1% uniform smoothing; invisible cells are uniform."""
    symbols, visible_mask = _sensor_arrays(symbols, visible_mask)
    probabilities = np.full((*symbols.shape, VOCAB_SIZE), UNIFORM_MIX / VOCAB_SIZE)
    np.put_along_axis(
        probabilities, symbols[..., None], 1.0 - UNIFORM_MIX + UNIFORM_MIX / VOCAB_SIZE, axis=-1
    )
    return np.where(visible_mask[..., None], probabilities, 1.0 / VOCAB_SIZE)


class NoActionBaseline:
    """Per-position current-byte to next-byte counts, without actions or future input.

    Fit replaces the previous fit atomically and admits train evidence through an
    explicit actor policy. Multi-step predictions multiply the frozen transition
    probabilities; an unknown initial cell remains uniform at every horizon.
    """

    def __init__(self, policy: TrainingPolicy) -> None:
        self.policy = TrainingPolicy.model_validate(policy)
        self._transition_probabilities: np.ndarray | None = None

    def fit(self, episodes: Sequence[EpisodeTrajectory]) -> NoActionBaseline:
        counts = np.zeros((CELL_COUNT, VOCAB_SIZE, VOCAB_SIZE), dtype=np.int64)
        seen_ids = set()
        observed_count = 0
        policy = TrainingPolicy.model_validate(self.policy)
        for episode in episodes:
            episode = EpisodeTrajectory.model_validate(episode)
            if episode.initial.context.partition is not DatasetPartition.TRAIN:
                raise ValueError("only train partition episodes can fit a baseline")
            episode_id = episode.initial.context.episode_id
            if episode_id in seen_ids:
                raise ValueError("duplicate episode IDs cannot fit a baseline")
            seen_ids.add(episode_id)
            for transition in episode.transitions:
                transition = admit_training(transition, policy)
                before = transition.observation.payload
                after = transition.next_observation.payload
                for cell in range(CELL_COUNT):
                    if before.visible_mask[cell] and after.visible_mask[cell]:
                        counts[cell, before.symbols[cell], after.symbols[cell]] += 1
                        observed_count += 1
        if observed_count == 0:
            raise ValueError("fit requires at least one pair of visible observations")
        totals = counts.sum(axis=-1, keepdims=True)
        probabilities = np.full(counts.shape, 1.0 / VOCAB_SIZE, dtype=np.float64)
        np.divide(counts, totals, out=probabilities, where=totals > 0)
        self._transition_probabilities = (
            1.0 - UNIFORM_MIX
        ) * probabilities + UNIFORM_MIX / VOCAB_SIZE
        return self

    def predict(
        self, symbols: np.ndarray, visible_mask: np.ndarray, *, horizon: int = 1
    ) -> np.ndarray:
        symbols, visible_mask = _sensor_arrays(symbols, visible_mask)
        if type(horizon) is not int or horizon < 1:
            raise ValueError("horizon must be a positive integer")
        if self._transition_probabilities is None:
            raise ValueError("baseline must be fitted before prediction")
        kernel = self._transition_probabilities
        distribution = kernel[np.arange(CELL_COUNT), symbols]
        for _ in range(horizon - 1):
            distribution = np.einsum("...ci,cij->...cj", distribution, kernel, optimize=True)
        return np.where(visible_mask[..., None], distribution, 1.0 / VOCAB_SIZE)


def symbol_metrics(
    probabilities: np.ndarray,
    targets: np.ndarray,
    target_mask: np.ndarray,
    previous_symbols: np.ndarray | None = None,
    previous_mask: np.ndarray | None = None,
) -> dict[str, float | int | None]:
    """Mean natural-log NLL and accuracy over visible targets, without invented success.

    Changed-cell scores require visibility at both ends and compare the supplied
    previous state with the target. If no previous state is supplied their count
    and NLL are unavailable (None), rather than evidence of zero changes.
    """
    targets, target_mask = _sensor_arrays(targets, target_mask)
    probabilities = np.asarray(probabilities)
    if probabilities.shape != (*targets.shape, VOCAB_SIZE):
        raise ValueError("probabilities must have shape [..., 8, 256] matching targets")
    if (
        probabilities.dtype.kind not in "fiu"
        or not np.isfinite(probabilities).all()
        or np.any(probabilities <= 0)
        or np.any(probabilities > 1)
        or not np.allclose(probabilities.sum(axis=-1), 1.0, rtol=1e-6, atol=1e-6)
    ):
        raise ValueError("probabilities must be positive, finite and normalized")
    if (previous_symbols is None) != (previous_mask is None):
        raise ValueError("previous_symbols and previous_mask must be supplied together")
    changed_mask = unchanged_mask = None
    if previous_symbols is not None:
        previous_symbols, previous_mask = _sensor_arrays(previous_symbols, previous_mask)
        if previous_symbols.shape != targets.shape:
            raise ValueError("previous observations must match the target shape")
        changed_mask = target_mask & previous_mask & (targets != previous_symbols)
        unchanged_mask = target_mask & previous_mask & (targets == previous_symbols)
    count = int(target_mask.sum())
    selected = np.take_along_axis(probabilities, targets[..., None], axis=-1)[..., 0]
    losses = -np.log(selected)
    changed_count = int(changed_mask.sum()) if changed_mask is not None else None
    unchanged_count = int(unchanged_mask.sum()) if unchanged_mask is not None else None
    correct = probabilities.argmax(axis=-1) == targets
    return {
        "nll": float(losses[target_mask].mean()) if count else None,
        "count": count,
        "accuracy": float((probabilities.argmax(axis=-1) == targets)[target_mask].mean())
        if count
        else None,
        "changed_nll": float(losses[changed_mask].mean()) if changed_count else None,
        "changed_count": changed_count,
        "changed_accuracy": float(correct[changed_mask].mean()) if changed_count else None,
        "unchanged_count": unchanged_count,
        "unchanged_nll": float(losses[unchanged_mask].mean()) if unchanged_count else None,
        "unchanged_accuracy": float(correct[unchanged_mask].mean()) if unchanged_count else None,
    }
