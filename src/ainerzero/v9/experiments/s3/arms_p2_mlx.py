"""Phase 2 training path on the frozen S3 arms (DESIGN-r1 §3). Import only from entry points.

``arms_mlx.ReadoutArm`` and ``arms_mlx.forward`` are reused unchanged; evaluation always goes
through ``arms_mlx.forward(hard=True)``.
"""

from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn

from ainerzero.v9.experiments.s3 import arms_mlx as A


def sample_candidate(scores: mx.array, mask: mx.array, key: mx.array) -> mx.array:
    """Draw one valid candidate per event from the scorer's masked softmax."""
    return mx.random.categorical(A._masked_log_softmax(scores, mask), key=key)


def a3_sampled_forward(model: A.ReadoutArm, b: dict[str, mx.array], key: mx.array) -> tuple[mx.array, mx.array]:
    """A3H: during training the readout sees one candidate sampled from the scorer.

    Evaluation also shows the readout a single record, so training and evaluation match. The
    scorer target is unchanged: the review showed the no-memory CE term is identical across
    candidates of an event and cancels in the softmax, so ``-ce_c`` is equivalent.
    """
    if model.arm != "A3":
        raise ValueError("the sampled path exists only for arm A3")
    ep, t = b["ep"], b["query_t"]
    z_q = model.encode(b["obs"][ep, t])
    cand, mask = b["candidates"], b["cand_mask"]
    safe = mx.where(cand < 0, mx.zeros_like(cand), cand)
    n, k = cand.shape
    ep_k = mx.broadcast_to(ep[:, None], (n, k))
    z_c = model.encode(b["obs"][ep_k, safe])
    m_c = model.project(z_c)
    z_q_k = mx.broadcast_to(z_q[:, None, :], (n, k, z_q.shape[-1]))
    s = model.score(b["cand_feats"], mx.stop_gradient(z_q), mx.stop_gradient(z_c))

    y_k = mx.broadcast_to(b["answer"][:, None], (n, k))
    ce_c = nn.losses.cross_entropy(model.readout(z_q_k, m_c), y_k, reduction="none")
    util = mx.stop_gradient(-ce_c)
    target = mx.exp(A._masked_log_softmax(util / A.UTILITY_TEMPERATURE, mask))
    aux = -(target * A._masked_log_softmax(s, mask)).sum(-1).mean()

    idx = sample_candidate(s, mask, key)
    w = (mx.arange(k)[None, :] == idx[:, None]).astype(mx.float32)
    m = (w[..., None] * m_c).sum(1)
    return model.readout(z_q, m), aux


def a3_sampled_loss(model: A.ReadoutArm, b: dict[str, mx.array], key: mx.array) -> mx.array:
    logits, aux = a3_sampled_forward(model, b, key)
    return nn.losses.cross_entropy(logits, b["answer"], reduction="mean") + aux


def zero_memory_logits(model: A.ReadoutArm, b: dict[str, mx.array]) -> mx.array:
    """Readout with the memory input replaced by the projection of zeros (standing diagnostic).

    Defined for the episodic arms only; A1 has no projection of a retrieved record.
    """
    if model.arm == "A1":
        raise ValueError("arm A1 has no record projection")
    z_q = model.encode(b["obs"][b["ep"], b["query_t"]])
    return model.readout(z_q, model.project(mx.zeros_like(z_q)))
