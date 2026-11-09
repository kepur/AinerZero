"""Bounded episode replay and the data-level controls for S3 phase 2. Pure NumPy.

Per reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md §3.
"""

from __future__ import annotations

import dataclasses
from typing import Sequence

import numpy as np

from ainerzero.v9.experiments.s3.batching import PreparedEpisode

MIN_GAP = 5


def buffer_indices(n_episodes: int, capacity: int, seed: int) -> np.ndarray:
    """Episodes kept for replay: the first ``capacity`` of one seeded permutation.

    Sharing the permutation makes buffers nested, so R16 is a subset of R64 of R256 and the
    capacity curve does not compare unrelated samples.
    """
    if not 0 < capacity <= n_episodes:
        raise ValueError(f"capacity {capacity} must be in 1..{n_episodes}")
    return np.random.default_rng(seed).permutation(n_episodes)[:capacity]


def permute_answers(buffer: Sequence[PreparedEpisode], seed: int) -> list[PreparedEpisode]:
    """Control CN: permute answers across all events in the buffer; nothing else changes.

    The class distribution of the replayed answers is preserved, so any loss of protection
    comes from breaking the link between a record and its answer.
    """
    if not buffer:
        raise ValueError("buffer is empty")
    sizes = [len(p.answer) for p in buffer]
    permuted = np.random.default_rng(seed).permutation(np.concatenate([p.answer for p in buffer]))
    out, start = [], 0
    for p, n in zip(buffer, sizes):
        out.append(dataclasses.replace(p, answer=permuted[start : start + n]))
        start += n
    return out


def past_only_shuffle(p: PreparedEpisode, seed: int) -> PreparedEpisode:
    """Arm N: each event reads one record drawn uniformly from ``[0, t - MIN_GAP]``.

    Replaces the frozen ``batching.prepare_episode`` field, whose whole-episode permutation
    could hand an event a record from its own future. An event earlier than ``MIN_GAP`` has
    no record to draw and raises ``ValueError``.
    """
    rng = np.random.default_rng(seed)
    drawn = [int(rng.integers(0, int(t) - MIN_GAP + 1)) for t in p.query_t]
    return dataclasses.replace(p, shuffled=np.array(drawn, dtype=np.int32))
