"""MLX arms for S3 phase 1 (DESIGN-r2 §3). Import only from training entry points.

All arms share one encoder and readout head. Only the memory path differs:

- A0: no memory (zeros).
- A1: GRU hidden state.
- A2: episodic record chosen by hand cues.
- A3: episodic record chosen by a learned scorer over the multi-cue pool.
- O:  the true previous-visit record (upper bound, diagnostic only).
- N:  A2 with the record index permuted within the episode (negative control).

A3's scorer is trained on the readout utility of each candidate
(CE without memory minus CE with that record). Scorer inputs and targets are
stop-gradiented so the scorer cannot move the encoder.
"""

from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn

from ainerzero.v9.experiments.s3 import batching, spec

ARMS = ("A0", "A1", "A2", "A3", "O", "N")
Z_DIM = 64
GRU_DIM = 32
NUM_CLASSES = spec.NUM_TOKEN_CLASSES
UTILITY_TEMPERATURE = 0.5


class ReadoutArm(nn.Module):
    def __init__(self, arm: str):
        super().__init__()
        if arm not in ARMS:
            raise ValueError(f"unknown arm {arm!r}")
        self.arm = arm
        self.enc1 = nn.Linear(spec.OBS_DIM, 128)
        self.enc2 = nn.Linear(128, Z_DIM)
        self.head1 = nn.Linear(2 * Z_DIM, 128)
        self.head2 = nn.Linear(128, NUM_CLASSES)
        if arm == "A1":
            self.gru = nn.GRU(Z_DIM, GRU_DIM)
            self.mem1 = nn.Linear(GRU_DIM, Z_DIM)
        else:
            self.mem1 = nn.Linear(Z_DIM, 96)
            self.mem2 = nn.Linear(96, Z_DIM)
        if arm == "A3":
            self.score1 = nn.Linear(batching.CAND_FEATURES + 1, 32)
            self.score2 = nn.Linear(32, 1)

    def encode(self, obs: mx.array) -> mx.array:
        return self.enc2(nn.relu(self.enc1(obs)))

    def project(self, z: mx.array) -> mx.array:
        return self.mem2(nn.relu(self.mem1(z)))

    def readout(self, z_q: mx.array, m: mx.array) -> mx.array:
        return self.head2(nn.relu(self.head1(mx.concatenate([z_q, m], axis=-1))))

    def score(self, feats: mx.array, z_q: mx.array, z_c: mx.array) -> mx.array:
        """Candidate logits [E, K]. Inputs are stop-gradiented by the caller."""
        eps = 1e-6
        cos = (z_q[:, None, :] * z_c).sum(-1) / (
            mx.linalg.norm(z_q[:, None, :], axis=-1) * mx.linalg.norm(z_c, axis=-1) + eps
        )
        x = mx.concatenate([feats, cos[..., None]], axis=-1)
        return self.score2(nn.relu(self.score1(x))).squeeze(-1)


def _masked_log_softmax(logits: mx.array, mask: mx.array) -> mx.array:
    masked = mx.where(mask, logits, mx.array(-1e9))
    return masked - mx.logsumexp(masked, axis=-1, keepdims=True)


def forward(model: ReadoutArm, b: dict[str, mx.array], *, hard: bool) -> tuple[mx.array, mx.array]:
    """Return (readout logits [E, C], scorer loss). ``hard`` picks the top candidate (eval)."""
    ep, t = b["ep"], b["query_t"]
    z_q = model.encode(b["obs"][ep, t])
    aux = mx.array(0.0)
    arm = model.arm

    if arm == "A0":
        m = model.project(mx.zeros_like(z_q))
    elif arm == "A1":
        h = model.gru(model.encode(b["obs"]))
        m = model.mem1(h[ep, t])
    elif arm in ("A2", "O", "N"):
        key = {"A2": "top1", "O": "oracle", "N": "shuffled"}[arm]
        m = model.project(model.encode(b["obs"][ep, b[key]]))
    else:  # A3
        cand, mask = b["candidates"], b["cand_mask"]
        safe = mx.where(cand < 0, mx.zeros_like(cand), cand)
        n, k = cand.shape
        ep_k = mx.broadcast_to(ep[:, None], (n, k))
        z_c = model.encode(b["obs"][ep_k, safe])
        m_c = model.project(z_c)
        z_q_k = mx.broadcast_to(z_q[:, None, :], (n, k, z_q.shape[-1]))
        s = model.score(b["cand_feats"], mx.stop_gradient(z_q), mx.stop_gradient(z_c))

        # Utility of each candidate: readout CE without memory minus CE with it.
        y_k = mx.broadcast_to(b["answer"][:, None], (n, k))
        ce_c = nn.losses.cross_entropy(model.readout(z_q_k, m_c), y_k, reduction="none")
        ce_0 = nn.losses.cross_entropy(
            model.readout(z_q, model.project(mx.zeros_like(z_q))), b["answer"], reduction="none"
        )
        util = mx.stop_gradient(ce_0[:, None] - ce_c)
        target = mx.exp(_masked_log_softmax(util / UTILITY_TEMPERATURE, mask))
        aux = -(target * _masked_log_softmax(s, mask)).sum(-1).mean()

        w = mx.exp(_masked_log_softmax(mx.stop_gradient(s), mask))
        if hard:
            top = mx.argmax(mx.where(mask, s, mx.array(-1e9)), axis=-1)
            w = (mx.arange(k)[None, :] == top[:, None]).astype(mx.float32)
        m = (w[..., None] * m_c).sum(1)
    return model.readout(z_q, m), aux


def loss_fn(model: ReadoutArm, b: dict[str, mx.array]) -> mx.array:
    logits, aux = forward(model, b, hard=False)
    return nn.losses.cross_entropy(logits, b["answer"], reduction="mean") + aux


def param_count(model: ReadoutArm) -> int:
    from mlx.utils import tree_flatten

    return sum(v.size for _, v in tree_flatten(model.parameters()))
