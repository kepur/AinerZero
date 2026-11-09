"""Unit test for S3-C2 negative control token shuffling.

Verifies:
1. shuffle_tokens creates a new store of equal length.
2. Timestamps, estimated poses, and world terrain grids are identical.
3. Token counts (histogram) are exactly preserved.
4. Token sequence is permuted (token-location association destroyed).
"""

from __future__ import annotations

import collections
import random

import numpy as np
import pytest

from ainerzero.v9.experiments.s3.data import generate_episode
from ainerzero.v9.experiments.s3.store import EpisodicStore


def test_shuffle_tokens_negative_control() -> None:
    ep = generate_episode(world_seed=77, episode_seed=88, family="F1")
    store = EpisodicStore()
    for s in ep["steps"]:
        store.add_step(s)

    rng = random.Random(999)
    shuffled_store = store.shuffle_tokens(rng)

    assert len(shuffled_store) == len(store)

    orig_tokens = [r.observed_token for r in store]
    shuf_tokens = [r.observed_token for r in shuffled_store]

    # Multiset preservation
    assert collections.Counter(orig_tokens) == collections.Counter(shuf_tokens)

    # Sequence permutation
    assert orig_tokens != shuf_tokens, "Shuffled tokens should not match original order exactly"

    # Invariance of timestamps, poses, and terrain
    for r_orig, r_shuf in zip(store, shuffled_store):
        assert r_orig.t == r_shuf.t
        assert r_orig.est_pose == r_shuf.est_pose
        np.testing.assert_array_equal(r_orig.world_terrain, r_shuf.world_terrain)
