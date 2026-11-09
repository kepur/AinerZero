"""Turn GridLab-S3 episodes into the arrays the MLX arms train on.

Per reports/V9-S3-DESIGN/DESIGN-r2.md §3. Pure NumPy, zero MLX imports.

Retrieval is computed here once per event using ``cues.py`` (the authoritative
scoring module). The arms only see record indices and student-visible features.
``oracle`` is the only field derived from truth and is used only by arm O.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from ainerzero.v9.experiments.s3 import spec
from ainerzero.v9.experiments.s3.cues import (
    build_multi_cue_candidate_pool,
    compute_pose_distance,
    compute_view_similarity,
    rank_candidates,
)
from ainerzero.v9.experiments.s3.store import EpisodicStore

MAX_CANDIDATES = 12
CAND_FEATURES = 3
BUCKET_CODE = {None: 0, spec.BUCKET_SHORT: 1, spec.BUCKET_MID: 2, spec.BUCKET_LONG: 3}


@dataclass(frozen=True)
class PreparedEpisode:
    obs: np.ndarray            # [T, OBS_DIM]
    query_t: np.ndarray        # [E]
    top1: np.ndarray           # [E] hand-cue top record index
    oracle: np.ndarray         # [E] prev_visit_t (truth-derived, arm O only)
    shuffled: np.ndarray       # [E] within-episode permuted top1 (arm N)
    candidates: np.ndarray     # [E, K] record indices, -1 padded
    cand_feats: np.ndarray     # [E, K, CAND_FEATURES]
    cand_mask: np.ndarray      # [E, K] bool
    answer: np.ndarray         # [E] token id
    swapped: np.ndarray        # [E] bool
    bucket: np.ndarray         # [E] BUCKET_CODE


def prepare_episode(episode: dict[str, Any], lam: float, *, perm_seed: int) -> PreparedEpisode:
    """Compute retrieval for every readout event of one generated episode."""
    steps = episode["steps"]
    store = EpisodicStore()
    for s in steps:
        store.add_step(s)

    n_steps = len(steps)
    perm = list(range(n_steps))
    random.Random(perm_seed).shuffle(perm)

    q, top1, oracle, shuffled, cands, feats, masks, ans, swp, bkt = [], [], [], [], [], [], [], [], [], []
    for e in episode["events"]:
        t = int(e["t"])
        ranked = rank_candidates(store, t, mode="both", lam=lam)
        pool = build_multi_cue_candidate_pool(store, t, lam=lam)
        if not ranked or not pool:
            continue
        q_rec = store[t]
        idx = np.full(MAX_CANDIDATES, -1, dtype=np.int32)
        f = np.zeros((MAX_CANDIDATES, CAND_FEATURES), dtype=np.float32)
        m = np.zeros(MAX_CANDIDATES, dtype=bool)
        for i, r in enumerate(pool[:MAX_CANDIDATES]):
            idx[i] = r.t
            f[i] = (
                compute_pose_distance(q_rec, r) / float(spec.T),
                compute_view_similarity(q_rec, r),
                (t - r.t) / float(spec.T),
            )
            m[i] = True
        top = ranked[0][0].t
        q.append(t)
        top1.append(top)
        oracle.append(int(e["prev_visit_t"]))
        shuffled.append(perm[top])
        cands.append(idx)
        feats.append(f)
        masks.append(m)
        ans.append(int(e["answer"]))
        swp.append(bool(e["swapped"]))
        bkt.append(BUCKET_CODE[e["bucket"]])

    n = len(q)
    return PreparedEpisode(
        obs=np.stack([np.asarray(s["obs"], dtype=np.float32) for s in steps]),
        query_t=np.array(q, dtype=np.int32),
        top1=np.array(top1, dtype=np.int32),
        oracle=np.array(oracle, dtype=np.int32),
        shuffled=np.array(shuffled, dtype=np.int32),
        candidates=np.stack(cands) if n else np.zeros((0, MAX_CANDIDATES), dtype=np.int32),
        cand_feats=np.stack(feats) if n else np.zeros((0, MAX_CANDIDATES, CAND_FEATURES), dtype=np.float32),
        cand_mask=np.stack(masks) if n else np.zeros((0, MAX_CANDIDATES), dtype=bool),
        answer=np.array(ans, dtype=np.int32),
        swapped=np.array(swp, dtype=bool),
        bucket=np.array(bkt, dtype=np.int32),
    )


def collate(episodes: Sequence[PreparedEpisode]) -> dict[str, np.ndarray]:
    """Stack episodes into one batch; ``ep`` maps each event to its episode."""
    return {
        "obs": np.stack([e.obs for e in episodes]),
        "ep": np.concatenate([np.full(len(e.query_t), i, dtype=np.int32) for i, e in enumerate(episodes)]),
        "query_t": np.concatenate([e.query_t for e in episodes]),
        "top1": np.concatenate([e.top1 for e in episodes]),
        "oracle": np.concatenate([e.oracle for e in episodes]),
        "shuffled": np.concatenate([e.shuffled for e in episodes]),
        "candidates": np.concatenate([e.candidates for e in episodes]),
        "cand_feats": np.concatenate([e.cand_feats for e in episodes]),
        "cand_mask": np.concatenate([e.cand_mask for e in episodes]),
        "answer": np.concatenate([e.answer for e in episodes]),
        "swapped": np.concatenate([e.swapped for e in episodes]),
        "bucket": np.concatenate([e.bucket for e in episodes]),
    }
