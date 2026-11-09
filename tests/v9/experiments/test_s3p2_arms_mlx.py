"""Contracts for the S3 phase 2 training path: sampling, gradients and isolation."""

from __future__ import annotations

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
import mlx.nn as nn  # noqa: E402
from mlx.utils import tree_flatten  # noqa: E402

from ainerzero.v9.experiments.s3 import arms_mlx as A  # noqa: E402
from ainerzero.v9.experiments.s3 import arms_p2_mlx as P  # noqa: E402
from ainerzero.v9.experiments.s3 import batching as B  # noqa: E402
from ainerzero.v9.experiments.s3 import data as D  # noqa: E402
from ainerzero.v9.experiments.s3 import replay as RP  # noqa: E402
from ainerzero.v9.experiments.s3 import spec  # noqa: E402

NS = "test-s3p2-arms"


@pytest.fixture(scope="module", autouse=True)
def _cpu():
    mx.set_default_device(mx.cpu)


@pytest.fixture(scope="module")
def batch():
    eps = []
    for i in range(4):
        ep = D.generate_episode(D.derive_seed(NS, "world", i), D.derive_seed(NS, "ep", i))
        eps.append(RP.past_only_shuffle(B.prepare_episode(ep, 1.0, perm_seed=i), 100 + i))
    return {k: mx.array(v) for k, v in B.collate(eps).items()}


def model_of(arm="A3", seed=7):
    mx.random.seed(seed)
    m = A.ReadoutArm(arm)
    mx.eval(m.parameters())
    return m


def sampled(m, b, seed=3):
    lg, aux = P.a3_sampled_forward(m, b, mx.random.key(seed))
    mx.eval(lg, aux)
    return np.asarray(lg), float(aux)


def test_same_key_reproduces_and_different_keys_differ(batch) -> None:
    m = model_of()
    a, _ = sampled(m, batch, 3)
    b, _ = sampled(m, batch, 3)
    c, _ = sampled(m, batch, 4)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_sampling_does_not_depend_on_the_global_random_state(batch) -> None:
    m = model_of()
    mx.random.seed(1)
    a, _ = sampled(m, batch, 3)
    mx.random.seed(999)
    b, _ = sampled(m, batch, 3)
    assert np.array_equal(a, b)


def test_sampler_never_picks_a_masked_candidate() -> None:
    n, k = 200, 12
    mask = np.zeros((n, k), dtype=bool)
    mask[:, [2, 7]] = True
    scores = mx.array(np.random.default_rng(0).normal(size=(n, k)), dtype=mx.float32)
    for seed in range(20):
        idx = np.asarray(P.sample_candidate(scores, mx.array(mask), mx.random.key(seed)))
        assert set(idx.tolist()) <= {2, 7}
    assert set(idx.tolist()) == {2, 7}


def test_sampler_follows_the_scores() -> None:
    scores = mx.array(np.tile([0.0, 3.0, 0.0], (4000, 1)), dtype=mx.float32)
    idx = np.asarray(P.sample_candidate(scores, mx.ones((4000, 3), dtype=mx.bool_), mx.random.key(1)))
    expected = np.exp(3.0) / (2 + np.exp(3.0))
    assert (idx == 1).mean() == pytest.approx(expected, abs=0.03)


def test_readout_sees_a_single_record(batch) -> None:
    """Perturbing every candidate record except the sampled one must not change the output."""
    m = model_of()
    key = mx.random.key(3)
    base, _ = P.a3_sampled_forward(m, batch, key)
    mx.eval(base)
    z_q = m.encode(batch["obs"][batch["ep"], batch["query_t"]])
    cand, mask = batch["candidates"], batch["cand_mask"]
    n, k = cand.shape
    safe = mx.where(cand < 0, mx.zeros_like(cand), cand)
    z_c = m.encode(batch["obs"][mx.broadcast_to(batch["ep"][:, None], (n, k)), safe])
    idx = np.asarray(P.sample_candidate(m.score(batch["cand_feats"], z_q, z_c), mask, key))
    ep, q, c = np.array(batch["ep"]), np.array(batch["query_t"]), np.array(cand)
    i = 0
    chosen = int(c[i, idx[i]])
    # Replace the scorer's view with a fixed, unrelated record by moving the event's own query
    # out of the way: the output for event i is a function of z_q and the chosen record only.
    m_chosen = m.project(m.encode(batch["obs"][int(ep[i]), chosen])[None])
    expected = np.asarray(m.readout(z_q[i : i + 1], m_chosen))[0]
    assert np.allclose(np.asarray(base)[i], expected, atol=1e-5)


def test_logits_do_not_depend_on_labels_or_truth(batch) -> None:
    m = model_of()
    base, _ = sampled(m, batch)
    rng = np.random.default_rng(1)
    n = batch["query_t"].shape[0]
    other = dict(batch)
    other["oracle"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    other["swapped"] = mx.array(rng.random(n) < 0.5)
    other["bucket"] = mx.array(rng.integers(0, 4, size=n), dtype=mx.int32)
    other["top1"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    other["shuffled"] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    assert np.array_equal(base, sampled(m, other)[0])


def test_answers_steer_the_scorer_loss_only(batch) -> None:
    m = model_of()
    # An untrained head barely separates candidates; widen it so the target visibly moves.
    m.head2.weight = m.head2.weight * 200.0
    m.score2.weight = m.score2.weight * 50.0
    base, aux = sampled(m, batch)
    other = dict(batch)
    other["answer"] = mx.array(np.array(batch["answer"]) % 16 + 1, dtype=mx.int32)
    lg, aux2 = sampled(m, other)
    assert np.array_equal(base, lg)
    assert aux != aux2


def _grads(batch, loss):
    m = model_of()
    _, g = nn.value_and_grad(m, loss)(m, batch)
    return dict(tree_flatten(g))


def test_scorer_loss_does_not_reach_the_encoder(batch) -> None:
    g = _grads(batch, lambda m, b: P.a3_sampled_forward(m, b, mx.random.key(3))[1])
    for name in ("enc1.weight", "enc2.weight", "head1.weight", "head2.weight", "mem1.weight", "mem2.weight"):
        assert float(mx.abs(g[name]).max()) == 0.0, name
    assert float(mx.abs(g["score2.weight"]).max()) > 0.0


def test_readout_loss_reaches_the_encoder_but_not_the_scorer(batch) -> None:
    def readout(m, b):
        lg, _ = P.a3_sampled_forward(m, b, mx.random.key(3))
        return nn.losses.cross_entropy(lg, b["answer"], reduction="mean")

    g = _grads(batch, readout)
    assert float(mx.abs(g["enc1.weight"]).max()) > 0.0
    assert float(mx.abs(g["score2.weight"]).max()) == 0.0


def test_full_loss_is_finite_and_has_gradients(batch) -> None:
    m = model_of()
    loss, g = nn.value_and_grad(m, P.a3_sampled_loss)(m, batch, mx.random.key(3))
    assert np.isfinite(float(loss))
    assert any(float(mx.abs(v).max()) > 0 for _, v in tree_flatten(g))


def test_scorer_target_matches_the_frozen_utility(batch) -> None:
    """The phase 1 utility subtracts a term that is constant across an event's candidates."""
    u = np.array([[0.3, 0.9, 1.5, 2.0]], dtype=np.float32)
    mask = mx.ones((1, 4), dtype=mx.bool_)
    plain = mx.exp(A._masked_log_softmax(mx.array(u) / A.UTILITY_TEMPERATURE, mask))
    shifted = mx.exp(A._masked_log_softmax(mx.array(u + 7.0) / A.UTILITY_TEMPERATURE, mask))
    assert np.allclose(np.asarray(plain), np.asarray(shifted), atol=1e-5)


@pytest.mark.parametrize("arm", ["A0", "A2", "N", "O"])
def test_sampled_path_is_only_for_a3(batch, arm) -> None:
    with pytest.raises(ValueError):
        P.a3_sampled_forward(model_of(arm), batch, mx.random.key(1))


@pytest.mark.parametrize("arm", ["A2", "A3"])
def test_zero_memory_ignores_every_retrieval_field(batch, arm) -> None:
    m = model_of(arm)
    base = np.asarray(P.zero_memory_logits(m, batch))
    rng = np.random.default_rng(2)
    n = batch["query_t"].shape[0]
    other = dict(batch)
    for key in ("top1", "oracle", "shuffled"):
        other[key] = mx.array(rng.integers(0, spec.T, size=n), dtype=mx.int32)
    assert np.array_equal(base, np.asarray(P.zero_memory_logits(m, other)))


def test_zero_memory_differs_from_reading_a_record(batch) -> None:
    m = model_of("A2")
    lg, _ = A.forward(m, batch, hard=True)
    assert not np.allclose(np.asarray(lg), np.asarray(P.zero_memory_logits(m, batch)))


def test_zero_memory_refuses_the_gru_arm(batch) -> None:
    with pytest.raises(ValueError):
        P.zero_memory_logits(model_of("A1"), batch)


def test_arm_n_reads_a_record_from_the_past_of_the_event(batch) -> None:
    assert (np.array(batch["shuffled"]) <= np.array(batch["query_t"]) - RP.MIN_GAP).all()


def test_arm_n_output_ignores_records_after_the_event(batch) -> None:
    m = model_of("N")
    base = np.asarray(A.forward(m, batch, hard=True)[0])
    obs = np.array(batch["obs"])
    ep, q = np.array(batch["ep"]), np.array(batch["query_t"])
    i = int(np.argmin(q))
    obs[ep[i], q[i] + 1 :] = 1.0 - obs[ep[i], q[i] + 1 :]
    other = dict(batch)
    other["obs"] = mx.array(obs)
    assert np.array_equal(base[i], np.asarray(A.forward(m, other, hard=True)[0])[i])


def _candidates(m, b):
    ep, t = b["ep"], b["query_t"]
    z_q = m.encode(b["obs"][ep, t])
    cand, mask = b["candidates"], b["cand_mask"]
    safe = mx.where(cand < 0, mx.zeros_like(cand), cand)
    n, k = cand.shape
    z_c = m.encode(b["obs"][mx.broadcast_to(ep[:, None], (n, k)), safe])
    z_q_k = mx.broadcast_to(z_q[:, None, :], (n, k, z_q.shape[-1]))
    return z_q, z_c, z_q_k, mask, n, k


def test_scorer_target_rewards_low_readout_loss_at_the_registered_temperature(batch) -> None:
    """Recompute the scorer loss by hand; a flipped sign or other temperature must differ."""
    m = model_of()
    m.head2.weight = m.head2.weight * 200.0
    m.score2.weight = m.score2.weight * 50.0
    z_q, z_c, z_q_k, mask, n, k = _candidates(m, batch)
    y = mx.broadcast_to(batch["answer"][:, None], (n, k))
    ce = nn.losses.cross_entropy(m.readout(z_q_k, m.project(z_c)), y, reduction="none")
    assert A.UTILITY_TEMPERATURE == 0.5
    target = mx.exp(A._masked_log_softmax(-ce / 0.5, mask))
    s = m.score(batch["cand_feats"], z_q, z_c)
    expected = float(-(target * A._masked_log_softmax(s, mask)).sum(-1).mean())
    assert sampled(m, batch)[1] == pytest.approx(expected, rel=1e-5)


def test_full_loss_is_readout_loss_plus_scorer_loss(batch) -> None:
    m = model_of()
    m.head2.weight = m.head2.weight * 200.0
    m.score2.weight = m.score2.weight * 50.0
    key = mx.random.key(3)
    lg, aux = P.a3_sampled_forward(m, batch, key)
    ce = nn.losses.cross_entropy(lg, batch["answer"], reduction="mean")
    assert float(ce) > 1e-3 and float(aux) > 1e-3
    assert float(P.a3_sampled_loss(m, batch, key)) == pytest.approx(float(ce) + float(aux), rel=1e-5)
