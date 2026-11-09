"""Scoring contract for S3-C2 cues: pose distance, view similarity, three-way pool.

Added by tier-1 during review P207. Mutation checks showed the existing suite still
passed when the candidate pool used only the combined cue, and when pose distance
ignored the y axis, even though both define probes P-c and P-c2.
"""

from __future__ import annotations

import numpy as np

from ainerzero.v9.experiments.s3.cues import (
    build_multi_cue_candidate_pool,
    compute_combined_score,
    compute_pose_distance,
    compute_view_similarity,
)
from ainerzero.v9.experiments.s3.store import EpisodicRecord, EpisodicStore

Q_VIEW = [[0, 1, 0], [1, 0, 1], [0, 2, 0]]
OTHER_VIEW = [[3, 3, 3], [3, 3, 3], [3, 3, 3]]


def _rec(t: int, x: float, y: float, view: list[list[int]]) -> EpisodicRecord:
    return EpisodicRecord(
        t=t,
        est_pose=(float(x), float(y), 0),
        world_terrain=np.array(view, dtype=np.int8),
        observed_token=0,
    )


def test_pose_distance_is_manhattan_on_both_axes() -> None:
    q = _rec(0, 3.0, 7.0, Q_VIEW)
    assert compute_pose_distance(q, _rec(1, 10.0, 2.0, Q_VIEW)) == 12.0
    assert compute_pose_distance(q, _rec(2, 3.0, 11.0, Q_VIEW)) == 4.0
    assert compute_pose_distance(q, _rec(3, 1.0, 7.0, Q_VIEW)) == 2.0


def test_view_similarity_is_fraction_of_matching_cells() -> None:
    q = _rec(0, 0.0, 0.0, Q_VIEW)
    one_off = [row[:] for row in Q_VIEW]
    one_off[0][0] = 3
    assert compute_view_similarity(q, _rec(1, 0.0, 0.0, Q_VIEW)) == 1.0
    assert abs(compute_view_similarity(q, _rec(2, 0.0, 0.0, one_off)) - 8.0 / 9.0) < 1e-9
    assert compute_view_similarity(q, _rec(3, 0.0, 0.0, OTHER_VIEW)) == 0.0


def test_combined_score_rewards_similarity_and_penalises_distance() -> None:
    assert compute_combined_score(pose_dist=2.0, view_sim=1.0, lam=0.5, scale=49.0) == 22.5
    assert compute_combined_score(pose_dist=5.0, view_sim=1.0, lam=0.5, scale=49.0) < compute_combined_score(
        pose_dist=2.0, view_sim=1.0, lam=0.5, scale=49.0
    )
    assert compute_combined_score(pose_dist=2.0, view_sim=0.5, lam=0.5, scale=49.0) < compute_combined_score(
        pose_dist=2.0, view_sim=1.0, lam=0.5, scale=49.0
    )


def _crafted_store() -> EpisodicStore:
    """Records whose top-4 sets under pose, view and combined cues are disjoint.

    t 0-3   near in pose, wrong view: top of the pose cue.
    t 4-7   right view, moderately near: top of the combined cue.
    t 8-11  right view, far: top of the view cue (recency breaks the sim=1 tie).
    t 12-35 filler, far and wrong view.
    t 36-40 perfect matches inside the exclusion gap; query is t=40.
    """
    store = EpisodicStore()
    for i, t in enumerate(range(0, 4)):
        store.add_record(_rec(t, i * 0.1, 0.0, OTHER_VIEW))
    for i, t in enumerate(range(4, 8)):
        store.add_record(_rec(t, 1.0 + i, 0.0, Q_VIEW))
    for i, t in enumerate(range(8, 12)):
        store.add_record(_rec(t, 30.0 + i, 0.0, Q_VIEW))
    for t in range(12, 36):
        store.add_record(_rec(t, 50.0, 50.0, OTHER_VIEW))
    for t in range(36, 41):
        store.add_record(_rec(t, 0.0, 0.0, Q_VIEW))
    return store


def test_candidate_pool_is_union_of_all_three_cues() -> None:
    store = _crafted_store()
    pool = build_multi_cue_candidate_pool(store, query_t=40, lam=0.5, gap=5, top_k_per_cue=4)
    got = sorted(r.t for r in pool)

    assert got == list(range(0, 12)), f"pool must be pose(0-3) + combined(4-7) + view(8-11), got {got}"


def test_candidate_pool_excludes_recent_perfect_matches() -> None:
    store = _crafted_store()
    pool = build_multi_cue_candidate_pool(store, query_t=40, lam=0.5, gap=5, top_k_per_cue=4)

    assert all(r.t <= 35 for r in pool)
