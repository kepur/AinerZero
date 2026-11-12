"""Contract tests for the S3 MLX arms (DESIGN-r2 §3, §8)."""

from __future__ import annotations

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
import mlx.nn as nn  # noqa: E402
from mlx.utils import tree_flatten  # noqa: E402

from ainerzero.v9.experiments.s3 import arms_mlx as A  # noqa: E402
from ainerzero.v9.experiments.s3 import batching as B  # noqa: E402
from ainerzero.v9.experiments.s3 import data as D  # noqa: E402
from ainerzero.v9.experiments.s3 import spec  # noqa: E402

pytestmark = pytest.mark.native_mlx


@pytest.fixture(autouse=True)
def _cpu():
    prev = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(prev)


@pytest.fixture(scope="module")
def batch():
    eps = []
    for i in range(3):
        ep = D.generate_episode(D.derive_seed("arms-test", "world", i), D.derive_seed("arms-test", "ep", i))
        eps.append(B.prepare_episode(ep, 1.0, perm_seed=i))
    assert all(len(e.query_t) > 0 for e in eps)
    return {k: mx.array(v) for k, v in B.collate(eps).items()}


def _grads(arm, b, loss):
    model = A.ReadoutArm(arm)
    mx.eval(model.parameters())
    _, g = nn.value_and_grad(model, loss)(model, b)
    return dict(tree_flatten(g))


@pytest.mark.parametrize("arm", A.ARMS)
def test_forward_shape_and_finite(arm, batch) -> None:
    model = A.ReadoutArm(arm)
    mx.eval(model.parameters())
    logits, aux = A.forward(model, batch, hard=True)
    mx.eval(logits, aux)
    assert logits.shape == (batch["query_t"].shape[0], spec.NUM_TOKEN_CLASSES)
    assert np.isfinite(np.asarray(logits)).all()
    assert np.isfinite(float(aux))


def test_param_counts_within_ten_percent() -> None:
    counts = {arm: A.param_count(A.ReadoutArm(arm)) for arm in A.ARMS}
    lo, hi = min(counts.values()), max(counts.values())
    assert (hi - lo) / lo <= 0.10, counts


def test_scorer_loss_does_not_reach_encoder(batch) -> None:
    """DESIGN-r2 §8: the scorer's gradient must not move the encoder."""

    def scorer_only(model, b):
        return A.forward(model, b, hard=False)[1]

    g = _grads("A3", batch, scorer_only)
    for name in ("enc1.weight", "enc2.weight", "head1.weight", "head2.weight", "mem1.weight", "mem2.weight"):
        assert float(mx.abs(g[name]).max()) == 0.0, name
    assert float(mx.abs(g["score2.weight"]).max()) > 0.0


def test_readout_loss_reaches_encoder_but_not_scorer(batch) -> None:
    def readout_only(model, b):
        logits, _ = A.forward(model, b, hard=False)
        return nn.losses.cross_entropy(logits, b["answer"], reduction="mean")

    g = _grads("A3", batch, readout_only)
    assert float(mx.abs(g["enc1.weight"]).max()) > 0.0
    assert float(mx.abs(g["score2.weight"]).max()) == 0.0


def test_a2_reads_the_retrieved_record_not_the_query(batch) -> None:
    """Perturbing only a retrieved record must change that event's output."""
    model = A.ReadoutArm("A2")
    mx.eval(model.parameters())
    base, _ = A.forward(model, batch, hard=True)
    base = np.asarray(base)
    ep, top1, q = np.array(batch["ep"]), np.array(batch["top1"]), np.array(batch["query_t"])
    queried = set(zip(ep.tolist(), q.tolist()))
    picks = [i for i in range(len(ep)) if (int(ep[i]), int(top1[i])) not in queried]
    assert len(picks) >= 3

    i = picks[0]
    obs = np.array(batch["obs"])
    obs[ep[i], top1[i]] = 1.0 - obs[ep[i], top1[i]]
    other = dict(batch)
    other["obs"] = mx.array(obs)
    changed, _ = A.forward(model, other, hard=True)
    assert not np.allclose(base[i], np.asarray(changed)[i], atol=1e-5), "A2 must read the retrieved record"

    # A record that is neither queried nor retrieved must not matter.
    obs = np.array(batch["obs"])
    used = {(int(a), int(b)) for a, b in zip(ep, top1)} | queried
    free = next((e, t) for e in range(obs.shape[0]) for t in range(obs.shape[1]) if (e, t) not in used)
    obs[free] = 1.0 - obs[free]
    other["obs"] = mx.array(obs)
    same, _ = A.forward(model, other, hard=True)
    assert np.allclose(base, np.asarray(same), atol=1e-5)


def test_batching_records_precede_query(batch) -> None:
    q, top = np.array(batch["query_t"]), np.array(batch["top1"])
    assert (top <= q - 5).all()
    cand, mask = np.array(batch["candidates"]), np.array(batch["cand_mask"])
    q_k = np.repeat(q[:, None], cand.shape[1], axis=1)
    assert (cand[mask] <= q_k[mask] - 5).all()
    assert (np.array(batch["oracle"]) < q).all()
