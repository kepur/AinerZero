"""Unit test for EpisodicStore clear() and zero cross-episode leakage.

Verifies:
1. store.clear() resets store length to 0.
2. Store state does not persist across episodes.
"""

from __future__ import annotations

import pytest

from ainerzero.v9.experiments.s3.data import generate_episode
from ainerzero.v9.experiments.s3.store import EpisodicStore


def test_episodic_store_clear_and_no_leakage() -> None:
    ep1 = generate_episode(world_seed=10, episode_seed=20, family="F1")
    ep2 = generate_episode(world_seed=30, episode_seed=40, family="F2")

    store = EpisodicStore()
    for s in ep1["steps"]:
        store.add_step(s)

    assert len(store) == len(ep1["steps"])
    assert len(store.get_pool(50)) > 0

    # Clear at episode boundary
    store.clear()
    assert len(store) == 0
    assert store.get_pool(50) == []
    assert list(store) == []

    # Second episode
    for s in ep2["steps"][:10]:
        store.add_step(s)

    assert len(store) == 10
    # First record corresponds to ep2 t=0, not ep1
    assert store[0].t == 0
    assert store[0].est_pose == (
        float(ep2["steps"][0]["est_pose"][0]),
        float(ep2["steps"][0]["est_pose"][1]),
        int(ep2["steps"][0]["est_pose"][2]),
    )
