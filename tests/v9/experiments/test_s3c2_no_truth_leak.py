"""Unit test verifying that S3-C2 episodic memory and heuristic cues NEVER read truth.

Asserts that altering, corrupting, or deleting the 'truth' key in step data
has zero effect on EpisodicRecord creation, cue ranking, or candidate pool generation.
"""

from __future__ import annotations

import copy
import random

import numpy as np
import pytest

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.cues import build_multi_cue_candidate_pool, rank_candidates
from ainerzero.v9.experiments.s3.data import generate_episode
from ainerzero.v9.experiments.s3.store import EpisodicStore, parse_student_step


def test_no_truth_leak_in_store_and_cues() -> None:
    # Generate 1 realistic episode
    ep = generate_episode(world_seed=42, episode_seed=101, family="F1")
    original_steps = ep["steps"]

    # Make corrupted copy of steps with truth obliterated or deleted
    corrupted_steps = copy.deepcopy(original_steps)
    for s in corrupted_steps:
        # Obliterate truth values
        s["truth"]["x"] = -999.0
        s["truth"]["y"] = 999.0
        s["truth"]["heading"] = 99
        s["truth"]["corrupted"] = True

    store_clean = EpisodicStore()
    store_corrupted = EpisodicStore()

    for s_clean, s_corrupt in zip(original_steps, corrupted_steps):
        rec_clean = store_clean.add_step(s_clean)
        rec_corrupt = store_corrupted.add_step(s_corrupt)

        # Records must be identical
        assert rec_clean.t == rec_corrupt.t
        assert rec_clean.est_pose == rec_corrupt.est_pose
        np.testing.assert_array_equal(rec_clean.world_terrain, rec_corrupt.world_terrain)
        assert rec_clean.observed_token == rec_corrupt.observed_token

    # Verify ranking and candidate pool identically match across query timestamps
    for query_t in range(20, min(100, len(original_steps)), 10):
        for mode in ("pose", "view", "both"):
            ranked_clean = rank_candidates(store_clean, query_t, mode=mode)
            ranked_corrupt = rank_candidates(store_corrupted, query_t, mode=mode)

            assert len(ranked_clean) == len(ranked_corrupt)
            for (r1, s1), (r2, s2) in zip(ranked_clean, ranked_corrupt):
                assert r1.t == r2.t
                assert abs(s1 - s2) < 1e-9

        pool_clean = build_multi_cue_candidate_pool(store_clean, query_t)
        pool_corrupt = build_multi_cue_candidate_pool(store_corrupted, query_t)

        assert len(pool_clean) == len(pool_corrupt)
        assert [r.t for r in pool_clean] == [r.t for r in pool_corrupt]


def test_truth_key_optional() -> None:
    """Deleting the 'truth' key altogether must not cause KeyError."""
    ep = generate_episode(world_seed=42, episode_seed=101, family="F1")
    step_no_truth = copy.deepcopy(ep["steps"][0])
    del step_no_truth["truth"]

    store = EpisodicStore()
    rec = store.add_step(step_no_truth)
    assert rec.t == 0
    assert rec.est_pose == (
        float(step_no_truth["est_pose"][0]),
        float(step_no_truth["est_pose"][1]),
        int(step_no_truth["est_pose"][2]),
    )
