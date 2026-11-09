"""Unit test for S3-C2 multi-cue candidate pool properties.

Verifies:
1. Pool deduplication (unique records).
2. Size bound: K <= 12 (top 4 pose, top 4 view, top 4 combined).
3. Recent step exclusion: strictly r.t <= query_t - gap (default gap=5).
4. Edge cases: query_t < gap, query_t == gap, large query_t.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.experiments.s3.cues import build_multi_cue_candidate_pool
from ainerzero.v9.experiments.s3.data import generate_episode
from ainerzero.v9.experiments.s3.store import EpisodicStore


def test_candidate_pool_properties() -> None:
    ep = generate_episode(world_seed=123, episode_seed=456, family="F1")
    steps = ep["steps"]

    store = EpisodicStore()
    for s in steps:
        store.add_step(s)

    # Edge case 1: query_t < gap
    pool_early = build_multi_cue_candidate_pool(store, query_t=3, gap=5)
    assert pool_early == [], f"Expected empty pool for query_t < gap, got {pool_early}"

    # Edge case 2: query_t == gap (gap=5 -> query_t=5)
    # Only step t=0 is eligible (0 <= 5 - 5)
    pool_at_gap = build_multi_cue_candidate_pool(store, query_t=5, gap=5)
    assert len(pool_at_gap) == 1
    assert pool_at_gap[0].t == 0

    # General queries across trajectory
    for query_t in (10, 20, 50, 100, 200, 300, len(steps) - 1):
        pool = build_multi_cue_candidate_pool(store, query_t=query_t, gap=5)

        # 1. Size bound
        assert len(pool) <= 12, f"Pool size exceeded 12: {len(pool)}"

        # 2. Deduplication
        timestamps = [r.t for r in pool]
        assert len(timestamps) == len(set(timestamps)), f"Duplicate timestamps in pool: {timestamps}"

        # 3. Gap exclusion: strictly t <= query_t - 5
        for r in pool:
            assert r.t <= query_t - 5, f"Candidate t={r.t} violates gap=5 for query_t={query_t}"
