"""Uniform public-experience windows for the first offline C0 experiment.

This is a window sampler, not the planned recent/reservoir/failure replay mix.
Burn-in observations are returned without padding; the learner must exclude its
first ``burn_in`` transitions from its supervised loss. No window crosses an
episode and no environment IDs, hidden snapshots, or seeds enter the batch.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import numpy as np

from ainerzero.core.experience import TrainingPolicy
from ainerzero.data.trajectory import load_training_trajectory


class SequenceSampler:
    """Sample with replacement, uniformly over all full, admissible windows."""

    def __init__(
        self,
        paths: Sequence[Path],
        policy: TrainingPolicy,
        *,
        burn_in: int = 4,
        sequence_steps: int = 16,
    ) -> None:
        if type(burn_in) is not int or burn_in < 0:
            raise ValueError("burn_in must be a nonnegative integer")
        if type(sequence_steps) is not int or sequence_steps < 1:
            raise ValueError("sequence_steps must be a positive integer")
        policy = TrainingPolicy.model_validate(policy)
        original_paths = tuple(Path(path) for path in paths)
        if not original_paths:
            raise ValueError("at least one training trajectory is required")
        resolved_paths = tuple(path.resolve() for path in original_paths)
        if len(set(resolved_paths)) != len(resolved_paths):
            raise ValueError("duplicate trajectory paths are not allowed")

        self.burn_in = burn_in
        self.sequence_steps = sequence_steps
        self.paths = resolved_paths
        self._episodes: list[dict[str, np.ndarray]] = []
        self._windows: list[tuple[int, int]] = []
        seen_ids = set()
        transitions_per_window = burn_in + sequence_steps
        for path in original_paths:
            # The admission loader reads public.jsonl only. Preserve the original
            # path here so its symlink checks cannot be bypassed by resolve().
            episode = load_training_trajectory(path, policy)
            episode_id = episode.initial.context.episode_id
            if episode_id in seen_ids:
                raise ValueError("duplicate episode IDs are not allowed")
            seen_ids.add(episode_id)
            observations = [episode.initial.payload] + [
                transition.next_observation.payload for transition in episode.transitions
            ]
            index = len(self._episodes)
            self._episodes.append(
                {
                    "symbols": np.asarray([item.symbols for item in observations], dtype=np.int32),
                    "visible_mask": np.asarray(
                        [item.visible_mask for item in observations], dtype=np.bool_
                    ),
                    "cursor": np.asarray([item.cursor for item in observations], dtype=np.int32),
                    "episode_start": np.asarray(
                        [item.episode_start for item in observations], dtype=np.bool_
                    ),
                    "actions": np.asarray(
                        [item.action_request.action for item in episode.transitions],
                        dtype=np.int32,
                    ),
                }
            )
            self._windows.extend(
                (index, start)
                for start in range(len(episode.transitions) - transitions_per_window + 1)
            )
        if not self._windows:
            raise ValueError("no episode has enough transitions for burn-in and sequence")

    @property
    def episode_count(self) -> int:
        """Number of admitted input episodes, including any too short to sample."""
        return len(self._episodes)

    @property
    def window_count(self) -> int:
        return len(self._windows)

    def sample(self, batch_size: int, rng: np.random.Generator) -> dict[str, np.ndarray]:
        """Return aligned T actions and T+1 observations; RNG state belongs to caller."""
        if type(batch_size) is not int or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(rng, np.random.Generator):
            raise TypeError("rng must be a numpy.random.Generator")
        indices = rng.integers(self.window_count, size=batch_size)
        slices: dict[str, list[np.ndarray]] = {name: [] for name in self._episodes[0]}
        steps = self.burn_in + self.sequence_steps
        for index in indices:
            episode_index, start = self._windows[int(index)]
            episode = self._episodes[episode_index]
            for name in slices:
                length = steps if name == "actions" else steps + 1
                slices[name].append(episode[name][start : start + length])
        # stack copies: a caller changing a batch cannot corrupt the replay source.
        return {name: np.stack(items) for name, items in slices.items()}
