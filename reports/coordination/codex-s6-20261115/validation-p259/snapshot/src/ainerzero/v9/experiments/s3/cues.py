"""GridLab-S3 Heuristic Cues and Multi-Cue Candidate Pool.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §3, §5, and task P206 specification.
Pure CPU, NumPy / standard library only. Zero MLX imports.
"""

from __future__ import annotations

import collections
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.store import EpisodicRecord, EpisodicStore


DEFAULT_SCALE: float = 49.0  # Scaling constant matching tier1-probe/alias_probe.py:109


def compute_pose_distance(
    q: EpisodicRecord,
    r: EpisodicRecord,
) -> float:
    """Compute Manhattan distance between query and candidate estimated poses."""
    return abs(q.est_pose[0] - r.est_pose[0]) + abs(q.est_pose[1] - r.est_pose[1])


def compute_view_similarity(
    q: EpisodicRecord,
    r: EpisodicRecord,
) -> float:
    """Compute terrain-only similarity between world-aligned 3x3 terrain views.

    Strictly compares terrain classes (FREE, WALL, PILLAR, UNSEEN).
    Never uses token channels since tokens swap during the episode.
    """
    return float(np.mean(q.world_terrain == r.world_terrain))


def compute_combined_score(
    pose_dist: float,
    view_sim: float,
    lam: float,
    scale: float = DEFAULT_SCALE,
) -> float:
    """Compute combined heuristic score: view_sim * scale * lam - pose_dist.

    Matches authoritative formula from tier1-probe/alias_probe.py:109.
    """
    return view_sim * scale * lam - pose_dist


def rank_candidates(
    store: EpisodicStore,
    query_t: int,
    mode: str = "both",
    lam: float = 0.5,
    gap: int = 5,
    scale: float = DEFAULT_SCALE,
) -> list[tuple[EpisodicRecord, float]]:
    """Rank all eligible memory records for query at step query_t.

    Excludes records within the most recent `gap` steps (r.t <= query_t - gap).
    Modes:
    - 'pose': -pose_distance + 1e-6 * r.t
    - 'view': view_similarity + 1e-6 * r.t
    - 'both': view_similarity * scale * lam - pose_distance + 1e-6 * r.t
    """
    pool = store.get_pool(query_t, gap=gap)
    if not pool or query_t >= len(store):
        return []

    q = store[query_t]
    scored: list[tuple[EpisodicRecord, float]] = []

    for r in pool:
        d = compute_pose_distance(q, r)
        sim = compute_view_similarity(q, r)

        if mode == "pose":
            score = -d
        elif mode == "view":
            score = sim
        elif mode == "both":
            score = compute_combined_score(d, sim, lam, scale=scale)
        else:
            raise ValueError(f"Unknown mode: {mode}; expected 'pose', 'view', or 'both'")

        # Tie-breaker preferring more recent visits
        score += 1e-6 * r.t
        scored.append((r, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def build_multi_cue_candidate_pool(
    store: EpisodicStore,
    query_t: int,
    lam: float = 0.5,
    gap: int = 5,
    top_k_per_cue: int = 4,
    scale: float = DEFAULT_SCALE,
) -> list[EpisodicRecord]:
    """Construct multi-cue candidate pool by merging top-k from pose, view, and both.

    Requirements:
    - Top 4 by pose distance (closest estimated pose)
    - Top 4 by view similarity (highest terrain match)
    - Top 4 by combined heuristic score
    - Deduplicated union preserving rank order, K <= 12
    - Excludes records within the most recent `gap` steps
    """
    pool = store.get_pool(query_t, gap=gap)
    if not pool or query_t >= len(store):
        return []

    q = store[query_t]
    scored_all: list[tuple[EpisodicRecord, float, float, float]] = []

    for r in pool:
        d = compute_pose_distance(q, r)
        sim = compute_view_similarity(q, r)
        s_both = compute_combined_score(d, sim, lam, scale=scale) + 1e-6 * r.t
        s_pose = -d + 1e-6 * r.t
        s_view = sim + 1e-6 * r.t
        scored_all.append((r, s_pose, s_view, s_both))

    top_pose = [x[0] for x in sorted(scored_all, key=lambda x: x[1], reverse=True)[:top_k_per_cue]]
    top_view = [x[0] for x in sorted(scored_all, key=lambda x: x[2], reverse=True)[:top_k_per_cue]]
    top_both = [x[0] for x in sorted(scored_all, key=lambda x: x[3], reverse=True)[:top_k_per_cue]]

    # Deduplicated union preserving combined score priority then pose then view
    cand_pool: list[EpisodicRecord] = []
    seen_t: set[int] = set()

    for r in top_both + top_pose + top_view:
        if r.t not in seen_t:
            seen_t.add(r.t)
            cand_pool.append(r)

    assert len(cand_pool) <= 3 * top_k_per_cue
    return cand_pool


def find_dwell_start(steps: Sequence[dict[str, Any]], prev_visit_t: int, target_cell: tuple[int, int]) -> int:
    """Find the start of the continuous dwell period ending at prev_visit_t."""
    t_start = prev_visit_t
    while t_start > 0:
        prev_step_pos = (
            int(steps[t_start - 1]["truth"]["x"]),
            int(steps[t_start - 1]["truth"]["y"]),
        )
        if prev_step_pos == target_cell:
            t_start -= 1
        else:
            break
    return t_start


def check_hit(
    candidate_t: int,
    event: dict[str, Any],
    steps: Sequence[dict[str, Any]],
) -> tuple[bool, bool]:
    """Check if candidate step t is a strict hit or loose hit for event.

    Returns:
        (is_strict, is_loose)
        - is_strict: candidate_t is in the continuous dwell period ending at event['prev_visit_t'].
        - is_loose: candidate_t position in steps matches event['cell'].
    """
    target_cell = tuple(event["cell"])
    prev_visit_t = event["prev_visit_t"]

    t_start = find_dwell_start(steps, prev_visit_t, target_cell)
    is_strict = (t_start <= candidate_t <= prev_visit_t)

    cand_pos = (
        int(steps[candidate_t]["truth"]["x"]),
        int(steps[candidate_t]["truth"]["y"]),
    )
    is_loose = (cand_pos == target_cell)
    return is_strict, is_loose


def fit_lambda_on_episodes(
    episodes: Sequence[dict[str, Any]],
    candidate_lambdas: Sequence[float] = (0.1, 0.25, 0.5, 1.0, 2.0),
    scale: float = DEFAULT_SCALE,
    gap: int = 5,
) -> tuple[float, dict[float, float], dict[str, Any]]:
    """Fit lambda on training episodes by maximizing precision@1 on long-interval events.

    Strict protocol: Evaluates only long-interval return events.
    """
    precisions: dict[float, float] = {}
    details: dict[float, dict[str, Any]] = {}

    for lam in candidate_lambdas:
        strict_hits = 0
        loose_hits = 0
        total_events = 0

        for ep in episodes:
            steps = ep["steps"]
            store = EpisodicStore()
            for s in steps:
                store.add_step(s)

            for ev in ep["events"]:
                if ev.get("bucket") != spec.BUCKET_LONG:
                    continue

                qt = ev["t"]
                ranked = rank_candidates(store, qt, mode="both", lam=lam, gap=gap, scale=scale)
                if not ranked:
                    continue

                top_rec = ranked[0][0]
                is_strict, is_loose = check_hit(top_rec.t, ev, steps)
                if is_strict:
                    strict_hits += 1
                if is_loose:
                    loose_hits += 1
                total_events += 1

        prec = (strict_hits / total_events) if total_events else 0.0
        loose_prec = (loose_hits / total_events) if total_events else 0.0
        precisions[lam] = prec
        details[lam] = {
            "strict_hits": strict_hits,
            "loose_hits": loose_hits,
            "total_events": total_events,
            "strict_precision": prec,
            "loose_precision": loose_prec,
        }

    # Best lambda achieves highest strict precision@1
    best_lam = max(candidate_lambdas, key=lambda l: precisions[l])
    return best_lam, precisions, details


def evaluate_probes(
    episodes: Sequence[dict[str, Any]],
    lam: float,
    scale: float = DEFAULT_SCALE,
    gap: int = 5,
) -> dict[str, Any]:
    """Evaluate Probes P-c and P-c2 across episodes on long-interval events.

    Returns:
    - P-c: Hand-tuned combination cue precision@1 (strict and loose).
    - P-c2: Multi-cue candidate pool recall (strict and loose).
    - Cues standalone precision: pose precision@1 and view precision@1.
    """
    total_long_events = 0
    pose_strict_hits = 0
    pose_loose_hits = 0
    view_strict_hits = 0
    view_loose_hits = 0
    both_strict_hits = 0
    both_loose_hits = 0
    pool_strict_hits = 0
    pool_loose_hits = 0
    pool_sizes: list[int] = []

    for ep in episodes:
        steps = ep["steps"]
        store = EpisodicStore()
        for s in steps:
            store.add_step(s)

        for ev in ep["events"]:
            if ev.get("bucket") != spec.BUCKET_LONG:
                continue

            qt = ev["t"]
            ranked_both = rank_candidates(store, qt, mode="both", lam=lam, gap=gap, scale=scale)
            ranked_pose = rank_candidates(store, qt, mode="pose", gap=gap, scale=scale)
            ranked_view = rank_candidates(store, qt, mode="view", gap=gap, scale=scale)
            cand_pool = build_multi_cue_candidate_pool(store, qt, lam=lam, gap=gap, scale=scale)

            if not ranked_both:
                continue

            total_long_events += 1
            pool_sizes.append(len(cand_pool))

            # P-c (both top 1)
            is_strict, is_loose = check_hit(ranked_both[0][0].t, ev, steps)
            if is_strict:
                both_strict_hits += 1
            if is_loose:
                both_loose_hits += 1

            # Pose top 1
            p_strict, p_loose = check_hit(ranked_pose[0][0].t, ev, steps)
            if p_strict:
                pose_strict_hits += 1
            if p_loose:
                pose_loose_hits += 1

            # View top 1
            v_strict, v_loose = check_hit(ranked_view[0][0].t, ev, steps)
            if v_strict:
                view_strict_hits += 1
            if v_loose:
                view_loose_hits += 1

            # P-c2 (pool recall)
            pool_strict = any(check_hit(r.t, ev, steps)[0] for r in cand_pool)
            pool_loose = any(check_hit(r.t, ev, steps)[1] for r in cand_pool)
            if pool_strict:
                pool_strict_hits += 1
            if pool_loose:
                pool_loose_hits += 1

    return {
        "n_episodes": len(episodes),
        "total_long_events": total_long_events,
        "lambda_used": lam,
        "scale_used": scale,
        "avg_pool_size": float(np.mean(pool_sizes)) if pool_sizes else 0.0,
        "max_pool_size": int(np.max(pool_sizes)) if pool_sizes else 0,
        "p_c_both_precision_strict": (both_strict_hits / total_long_events) if total_long_events else 0.0,
        "p_c_both_precision_loose": (both_loose_hits / total_long_events) if total_long_events else 0.0,
        "p_c2_pool_recall_strict": (pool_strict_hits / total_long_events) if total_long_events else 0.0,
        "p_c2_pool_recall_loose": (pool_loose_hits / total_long_events) if total_long_events else 0.0,
        "pose_precision_strict": (pose_strict_hits / total_long_events) if total_long_events else 0.0,
        "pose_precision_loose": (pose_loose_hits / total_long_events) if total_long_events else 0.0,
        "view_precision_strict": (view_strict_hits / total_long_events) if total_long_events else 0.0,
        "view_precision_loose": (view_loose_hits / total_long_events) if total_long_events else 0.0,
    }
