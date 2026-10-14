"""Numerical checks for the real pilot on MLX CPU; never launches a GPU job."""

import math

import numpy as np
import pytest

mx = pytest.importorskip("mlx.core")
nn = pytest.importorskip("mlx.nn")
optim = pytest.importorskip("mlx.optimizers")

from mlx.utils import tree_flatten  # noqa: E402

from ainerzero.learning.pilot_model import (  # noqa: E402
    ObservationStatePredictor,
    PilotPredictor,
    SharedSymbolPredictor,
    observation_loss,
    reconstruction_loss,
    sequence_loss,
)

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_only():
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


def batch(steps=2, size=1):
    return {
        "symbols": mx.full((size, steps + 1, 8), 2, dtype=mx.int32),
        "visible_mask": mx.ones((size, steps + 1, 8), dtype=mx.bool_),
        "cursor": mx.zeros((size, steps + 1), dtype=mx.int32),
        "episode_start": mx.zeros((size, steps + 1), dtype=mx.bool_),
        "actions": mx.zeros((size, steps), dtype=mx.int32),
    }


def model():
    return PilotPredictor(key=mx.random.key(81))


def loss(network, data, burn_in=0):
    return sequence_loss(network, data, burn_in=burn_in, beta_kl=0.1, key=mx.random.key(7))


def assert_tree_equal(a, b):
    aa, bb = tree_flatten(a), tree_flatten(b)
    assert [name for name, _ in aa] == [name for name, _ in bb]
    for (_, x), (_, y) in zip(aa, bb, strict=True):
        np.testing.assert_array_equal(np.asarray(x), np.asarray(y))


def test_registered_parameter_count_dtype_and_zero_biases():
    parameters = tree_flatten(model().parameters())
    assert sum(value.size for _, value in parameters) == 653_072
    assert all(value.dtype == mx.float32 for _, value in parameters)
    for name, value in parameters:
        if name.endswith((".bias", ".b", ".bhn")):
            assert np.count_nonzero(np.asarray(value)) == 0


def test_shared_symbol_codec_is_smaller_and_learned_not_a_fixed_copy():
    network = SharedSymbolPredictor(key=mx.random.key(0))
    assert sum(v.size for _, v in tree_flatten(network.parameters())) == 393232
    values = {
        "symbols": mx.array([[1, 2, 3, 4, 5, 6, 7, 8]], dtype=mx.int32),
        "visible_mask": mx.ones((1, 8), dtype=mx.bool_),
        "cursor": mx.array([0]),
    }
    h, _ = network.initial(1)
    state = network.observe(h, **values, key=mx.random.key(5))
    # Output is a learned independent head, never a one-hot from the inputs.
    network.symbol_readout.weight = mx.zeros_like(network.symbol_readout.weight)
    network.symbol_readout.bias = mx.zeros_like(network.symbol_readout.bias)
    logits = network.decode(state["h"], state["z"])["symbols"]
    np.testing.assert_array_equal(np.asarray(logits), np.zeros((1, 8, 256)))


def test_shared_symbol_codec_shares_positions_and_masks_hidden_bytes():
    network = SharedSymbolPredictor(key=mx.random.key(0))
    h, _ = network.initial(1)
    symbols = mx.array([[1, 2, 1, 4, 5, 6, 7, 8]], dtype=mx.int32)
    mask = mx.array([[True, False, True, True, True, True, True, True]])
    a = network.observe(h, symbols, mask, mx.array([0]), key=mx.random.key(3))
    b = network.observe(h, symbols.at[:, 1].add(70), mask, mx.array([0]), key=mx.random.key(3))
    np.testing.assert_array_equal(np.asarray(a["h"]), np.asarray(b["h"]))
    np.testing.assert_array_equal(
        np.asarray(a["logits"]["symbols"][:, 0]), np.asarray(a["logits"]["symbols"][:, 2])
    )
    np.testing.assert_array_equal(np.asarray(a["h"][:, 16:32]), np.zeros((1, 16)))


def test_shared_symbol_reconstruction_updates_both_codec_sides():
    network = SharedSymbolPredictor(key=mx.random.key(0))
    values = {
        "symbols": mx.array([[1, 2, 3, 4, 5, 6, 7, 8]], dtype=mx.int32),
        "visible_mask": mx.ones((1, 8), dtype=mx.bool_),
        "cursor": mx.array([0]),
    }
    (_, _), grads = nn.value_and_grad(network, reconstruction_loss)(
        network, values, key=mx.random.key(9)
    )
    flat = dict(tree_flatten(grads))
    assert np.linalg.norm(np.asarray(flat["byte_embedding.weight"])) > 0
    assert np.linalg.norm(np.asarray(flat["symbol_readout.weight"])) > 0


def test_explicit_keys_reproduce_initialization_without_consuming_global_rng():
    mx.random.seed(19)
    expected = mx.random.normal((8,))
    mx.eval(expected)
    mx.random.seed(19)
    first, second = model(), model()
    actual = mx.random.normal((8,))
    assert_tree_equal(first.parameters(), second.parameters())
    np.testing.assert_array_equal(np.asarray(actual), np.asarray(expected))
    other = PilotPredictor(key=mx.random.key(82))
    assert not np.array_equal(np.asarray(first.gru.Wx), np.asarray(other.gru.Wx))


def test_gru_matches_installed_mlx_equations():
    network = model()
    reference = nn.GRU(32, 256)
    reference.update(network.gru.parameters())
    x = mx.random.normal((2, 32), key=mx.random.key(40))
    h = mx.random.normal((2, 256), key=mx.random.key(41))
    np.testing.assert_allclose(
        np.asarray(network.gru(x, h)),
        np.asarray(reference(x[:, None], h)[:, 0]),
        rtol=1e-5,
        atol=1e-6,
    )


def test_observe_and_imagine_shapes_determinism_and_positive_scale():
    network = model()
    data = batch(size=3)
    h, z = network.initial(3)
    assert h.shape == (3, 256) and z.shape == (3, 16)
    assert np.count_nonzero(np.asarray(h)) == np.count_nonzero(np.asarray(z)) == 0
    posterior = network.observe(
        h,
        data["symbols"][:, 0],
        data["visible_mask"][:, 0],
        data["cursor"][:, 0],
        key=mx.random.key(42),
    )
    first = network.imagine(h, posterior["z"], data["actions"][:, 0], key=mx.random.key(43))
    second = network.imagine(h, posterior["z"], data["actions"][:, 0], key=mx.random.key(43))
    assert_tree_equal(first, second)
    assert first["logits"]["symbols"].shape == (3, 8, 256)
    assert first["logits"]["visibility"].shape == (3, 8)
    assert first["logits"]["cursor"].shape == (3, 8)
    assert np.all(np.asarray(first["std"]) >= 0.1)
    # Each particle receives independent draws even with the same observation.
    assert not np.array_equal(np.asarray(first["z"][0]), np.asarray(first["z"][1]))


@pytest.mark.parametrize("network_class", [PilotPredictor, ObservationStatePredictor])
def test_hidden_bytes_cannot_change_belief_or_produce_labels(network_class):
    network = network_class(key=mx.random.key(81))
    h, _ = network.initial(1)
    hidden = mx.zeros((1, 8), dtype=mx.bool_)
    cursor = mx.zeros((1,), dtype=mx.int32)
    zeros = mx.zeros((1, 8), dtype=mx.int32)
    # Deliberately illegal placeholders are masked before lookup / label gather.
    poison = mx.full((1, 8), 999, dtype=mx.int32)
    a = network.observe(h, zeros, hidden, cursor, key=mx.random.key(4))
    b = network.observe(h, poison, hidden, cursor, key=mx.random.key(4))
    assert_tree_equal(a, b)
    total, symbol_nll = observation_loss(a["logits"], poison, hidden, cursor)
    assert np.isfinite(np.asarray(total)).all()
    assert np.asarray(symbol_nll).item() == 0


def test_observation_loss_uses_visible_count_and_registered_head_weights():
    logits = {
        "symbols": mx.zeros((2, 8, 256)),
        "visibility": mx.zeros((2, 8)),
        "cursor": mx.zeros((2, 8)),
    }
    mask = mx.array([[True] + [False] * 7, [True] * 8])
    total, symbol = observation_loss(
        logits, mx.zeros((2, 8), dtype=mx.int32), mask, mx.zeros((2,), dtype=mx.int32)
    )
    np.testing.assert_allclose(np.asarray(symbol), math.log(256), atol=1e-6)
    np.testing.assert_allclose(
        np.asarray(total), math.log(256) + 0.2 * math.log(2) + 0.2 * math.log(8), atol=1e-6
    )


def test_future_observe_does_not_modify_prior_and_actions_change_prediction():
    network = model()
    h, z = network.initial(1)
    actions = mx.zeros((1,), dtype=mx.int32)
    original = network.imagine(h, z, actions, key=mx.random.key(6))
    network.observe(
        original["h"],
        mx.full((1, 8), 231, dtype=mx.int32),
        mx.ones((1, 8), dtype=mx.bool_),
        mx.array([7]),
        key=mx.random.key(10),
    )
    repeated = network.imagine(h, z, actions, key=mx.random.key(6))
    assert_tree_equal(original, repeated)
    other_action = network.imagine(h, z, mx.array([1]), key=mx.random.key(6))
    assert not np.array_equal(
        np.asarray(original["logits"]["symbols"]), np.asarray(other_action["logits"]["symbols"])
    )


def test_burn_in_supplies_context_but_cuts_its_embedding_gradient():
    network = model()
    data = batch()
    data["symbols"] = mx.array([[[1] * 8, [2] * 8, [2] * 8]])
    (value, _), grads = nn.value_and_grad(network, loss)(network, data, 1)
    mx.eval(value, grads)
    embedding_grad = np.asarray(grads["byte_embedding"]["weight"])
    assert np.count_nonzero(embedding_grad[1]) == 0
    assert np.linalg.norm(embedding_grad[2]) > 0
    changed = dict(data, symbols=mx.array([[[3] * 8, [2] * 8, [2] * 8]]))
    assert not np.isclose(value.item(), loss(network, changed, 1)[0].item(), rtol=0, atol=1e-7)


def test_episode_start_resets_all_previous_context():
    network = model()
    data = batch(steps=3)
    data["episode_start"] = mx.array([[False, False, True, False]])
    data["valid_mask"] = mx.array([[False, True, True]])
    # Transition 1 crosses a reset and must not contribute; only transition 2 trains.
    changed = dict(data, symbols=mx.array([[[14] * 8, [219] * 8, [2] * 8, [2] * 8]]))
    a, am = loss(network, data)
    b, bm = loss(network, changed)
    np.testing.assert_array_equal(np.asarray(a), np.asarray(b))
    assert_tree_equal(am, bm)


def test_padding_cannot_contribute_loss_or_gradients():
    network = model()
    data = batch()
    data["valid_mask"] = mx.zeros((1, 2), dtype=mx.bool_)
    (value, metrics), grads = nn.value_and_grad(network, loss)(network, data)
    mx.eval(value, metrics, grads)
    assert value.item() == 0
    assert all(item.item() == 0 for item in metrics.values())
    assert all(np.count_nonzero(np.asarray(grad)) == 0 for _, grad in tree_flatten(grads))


def test_real_gradients_and_small_batch_fit_reduce_prior_loss():
    network = model()
    data = batch(steps=1)
    before, before_metrics = loss(network, data)
    mx.eval(before, before_metrics)
    optimizer = optim.AdamW(learning_rate=0.003, weight_decay=0.0001, bias_correction=True)
    optimizer.init(network.trainable_parameters())
    value_grad = nn.value_and_grad(network, loss)
    for _ in range(6):
        (value, _), gradients = value_grad(network, data)
        mx.eval(value, gradients)
        assert np.isfinite(value.item())
        assert all(np.isfinite(np.asarray(g)).all() for _, g in tree_flatten(gradients))
        gradients, _ = optim.clip_grad_norm(gradients, 1.0)
        optimizer.update(network, gradients)
        mx.eval(network.parameters(), optimizer.state)
    after, after_metrics = loss(network, data)
    mx.eval(after, after_metrics)
    assert after.item() < before.item()
    assert after_metrics["prior_loss"].item() < before_metrics["prior_loss"].item()
    assert after_metrics["symbol_prior_nll"].item() < before_metrics["symbol_prior_nll"].item()


@pytest.mark.parametrize("burn_in", [-1, 2, True])
def test_invalid_burn_in_rejected(burn_in):
    with pytest.raises(ValueError, match="burn_in"):
        loss(model(), batch(), burn_in)


@pytest.mark.parametrize("beta", [float("nan"), -0.1, 1.0])
def test_invalid_kl_weight_rejected(beta):
    with pytest.raises(ValueError, match="beta_kl"):
        sequence_loss(model(), batch(), burn_in=0, beta_kl=beta, key=mx.random.key(1))


def test_mismatched_observation_length_rejected():
    data = batch()
    data["symbols"] = data["symbols"][:, :-1]
    with pytest.raises(ValueError, match="symbols must have shape"):
        loss(model(), data)


def current_frame(size=2):
    return {
        "symbols": mx.array(np.arange(size * 8).reshape(size, 8), dtype=mx.int32),
        "visible_mask": mx.ones((size, 8), dtype=mx.bool_),
        "cursor": mx.arange(size, dtype=mx.int32) % 8,
    }


def test_observation_variant_preserves_parameter_count_and_exact_initialization():
    original = model()
    candidate = ObservationStatePredictor(key=mx.random.key(81))
    assert original.ARCHITECTURE == "pilot_predictor_v1"
    assert candidate.ARCHITECTURE == "pilot_observation_state_v1"
    assert_tree_equal(original.parameters(), candidate.parameters())
    assert sum(value.size for _, value in tree_flatten(candidate.parameters())) == 653_072


def test_observation_write_preserves_posterior_and_half_memory_without_mutation():
    original = model()
    candidate = ObservationStatePredictor(key=mx.random.key(81))
    frame = current_frame()
    incoming = mx.arange(2 * 256, dtype=mx.float32).reshape((2, 256)) / 256
    saved_incoming = np.array(incoming)
    args = (incoming, frame["symbols"], frame["visible_mask"], frame["cursor"])
    old = original.observe(*args, key=mx.random.key(17))
    new = candidate.observe(*args, key=mx.random.key(17))
    for name in ("mean", "std", "z"):
        np.testing.assert_array_equal(np.asarray(old[name]), np.asarray(new[name]))
    np.testing.assert_array_equal(np.asarray(old["h"]), saved_incoming)
    np.testing.assert_array_equal(np.asarray(incoming), saved_incoming)
    expected_embedding = candidate.encode(frame["symbols"], frame["visible_mask"], frame["cursor"])
    np.testing.assert_array_equal(np.asarray(new["h"][:, :128]), np.asarray(expected_embedding))
    np.testing.assert_array_equal(np.asarray(new["h"][:, 128:]), saved_incoming[:, 128:])
    # The deterministic observation path is independent of latent sampling.
    another = candidate.observe(*args, key=mx.random.key(18))
    np.testing.assert_array_equal(np.asarray(new["h"]), np.asarray(another["h"]))
    assert not np.array_equal(np.asarray(new["z"]), np.asarray(another["z"]))


def test_saved_observation_state_decodes_without_reobserving_or_hidden_cache():
    candidate = ObservationStatePredictor(key=mx.random.key(81))
    frame = current_frame()
    h, _ = candidate.initial(2)
    observed = candidate.observe(
        h, frame["symbols"], frame["visible_mask"], frame["cursor"], key=mx.random.key(22)
    )
    saved_h, saved_z = mx.array(np.array(observed["h"])), mx.array(np.array(observed["z"]))
    expected = {name: mx.array(np.array(value)) for name, value in observed["logits"].items()}
    candidate.observe(
        h,
        mx.full((2, 8), 255, dtype=mx.int32),
        frame["visible_mask"],
        frame["cursor"],
        key=mx.random.key(23),
    )
    assert_tree_equal(candidate.decode(saved_h, saved_z), expected)


@pytest.mark.parametrize("network_class", [PilotPredictor, ObservationStatePredictor])
def test_current_reconstruction_matches_explicit_decode_with_registered_head_weights(network_class):
    network = network_class(key=mx.random.key(81))
    frame = current_frame()
    key = mx.random.key(24)
    value, metrics = reconstruction_loss(network, frame, key=key)
    h, _ = network.initial(2)
    observed = network.observe(h, frame["symbols"], frame["visible_mask"], frame["cursor"], key=key)
    direct, symbols = observation_loss(
        network.decode(observed["h"], observed["z"]),
        frame["symbols"],
        frame["visible_mask"],
        frame["cursor"],
    )
    np.testing.assert_array_equal(np.asarray(value), np.asarray(mx.mean(direct)))
    np.testing.assert_array_equal(np.asarray(metrics["reconstruction_loss"]), np.asarray(value))
    np.testing.assert_array_equal(np.asarray(metrics["symbol_nll"]), np.asarray(mx.mean(symbols)))


def test_reconstruction_has_encoder_decoder_gradients_without_training_dynamics():
    network = ObservationStatePredictor(key=mx.random.key(81))
    (value, _), gradients = nn.value_and_grad(network, reconstruction_loss)(
        network, current_frame(), key=mx.random.key(25)
    )
    mx.eval(value, gradients)
    assert np.isfinite(value.item())
    flat = dict(tree_flatten(gradients))
    for name in (
        "byte_embedding.weight",
        "encoder.0.weight",
        "encoder.1.weight",
        "decoder.0.weight",
    ):
        assert np.linalg.norm(np.asarray(flat[name])) > 0
    for name, gradient in flat.items():
        if name.startswith(("action_embedding.", "gru.", "prior.")):
            assert np.count_nonzero(np.asarray(gradient)) == 0


@pytest.mark.parametrize("extra", ["actions", "next_symbols", "episode_start"])
def test_reconstruction_rejects_transition_or_history_fields(extra):
    with pytest.raises(ValueError, match="must contain only"):
        reconstruction_loss(None, {**current_frame(), extra: mx.array([0])}, key=mx.random.key(1))


@pytest.mark.parametrize(
    ("field", "bad_shape"),
    [("symbols", (0, 8)), ("symbols", (2, 9)), ("visible_mask", (2, 7)), ("cursor", (2, 1))],
)
def test_reconstruction_rejects_invalid_current_frame_shape(field, bad_shape):
    frame = {**current_frame(), field: mx.zeros(bad_shape)}
    with pytest.raises(ValueError, match=field):
        reconstruction_loss(None, frame, key=mx.random.key(1))


def test_sequence_uses_observed_state_for_dynamics_and_unobserved_state_for_kl():
    class StateSpy:
        def __init__(self):
            self.imagined_states = []
            self.prior_states = []

        def initial(self, size):
            return mx.zeros((size, 256)), mx.zeros((size, 16))

        def decode(self, size):
            return {
                "symbols": mx.zeros((size, 8, 256)),
                "visibility": mx.zeros((size, 8)),
                "cursor": mx.zeros((size, 8)),
            }

        def observe(self, h, symbols, visible_mask, cursor, *, key):
            size = h.shape[0]
            return {
                "h": h + 1,
                "z": mx.zeros((size, 16)),
                "mean": mx.full((size, 16), 2.0),
                "std": mx.ones((size, 16)),
                "logits": self.decode(size),
            }

        def imagine(self, h, z, actions, *, key):
            self.imagined_states.append(np.array(h))
            return {"h": h + 1, "logits": self.decode(h.shape[0])}

        def prior_distribution(self, h):
            self.prior_states.append(np.array(h))
            return mx.broadcast_to(h[:, :1], (h.shape[0], 16)), mx.ones((h.shape[0], 16))

    spy = StateSpy()
    _, metrics = sequence_loss(spy, batch(), burn_in=0, beta_kl=0.1, key=mx.random.key(31))
    np.testing.assert_array_equal(spy.imagined_states[0], np.ones((1, 256)))
    np.testing.assert_array_equal(spy.imagined_states[1], np.full((1, 256), 3))
    np.testing.assert_array_equal(spy.prior_states[0], np.zeros((1, 256)))
    np.testing.assert_array_equal(spy.prior_states[1], np.full((1, 256), 2))
    # First KL = 16 * 0.5 * (2-0)^2 = 32; second is clamped from 0 to 1.
    np.testing.assert_allclose(np.asarray(metrics["kl"]), 16.5)
