"""CPU-only synthetic memory checks; no real student training is launched."""

import builtins
from copy import deepcopy

import mlx.core as mx
import mlx.nn as nn
import numpy as np
import pytest
from mlx.utils import tree_flatten
from test_pilot_evaluation import episode, payloads_for
from test_sequences import make_episode

from ainerzero.core.experience import DatasetPartition
from ainerzero.learning.one_step_memory import evaluate_one_step_memory, memory_sequence_loss

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_only():
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


class FakeMemory:
    """Synthetic perfect retention, independent of the actual student weights."""

    def __init__(self, *, events=None, erase_on_observe=False, mixture=False):
        self.events = events if events is not None else []
        self.weights = np.array([1.25])
        self.erase_on_observe = erase_on_observe
        self.mixture = mixture

    def initial(self, size):
        self.events.append(("initial", size))
        return mx.zeros((size, 256)), mx.zeros((size, 16))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        self.events.append(
            (
                "observe",
                np.asarray(symbols).tolist(),
                np.asarray(visible_mask).tolist(),
                np.asarray(cursor).tolist(),
                np.asarray(key).tolist(),
                np.asarray(h).tolist(),
            )
        )
        slots = mx.broadcast_to(
            mx.where(visible_mask, symbols, 0)[..., None], (*symbols.shape, 16)
        ).reshape(-1, 128)
        tail = mx.zeros_like(h[:, 128:]) if self.erase_on_observe else h[:, 128:]
        return {
            "h": mx.concatenate([slots, tail], axis=-1),
            "z": mx.zeros((symbols.shape[0], 16)),
            "logits": {"symbols": mx.full((symbols.shape[0], 8, 256), float("nan"))},
        }

    def imagine(self, h, z, actions, *, key):
        self.events.append(("imagine", np.asarray(actions).tolist(), np.asarray(key).tolist()))
        return {"h": mx.concatenate([h[:, :128], h[:, :128]], axis=-1), "z": z}

    def symbol_readout(self, slots):
        self.events.append(("readout", np.asarray(slots[..., 0]).tolist()))
        if self.mixture:
            probs = np.full((slots.shape[0], 8, 256), 0.2 / 255)
            probs[: slots.shape[0] // 2, :, 0] = 0.8
            probs[slots.shape[0] // 2 :, :, :] = 0.8 / 255
            probs[slots.shape[0] // 2 :, :, 0] = 0.2
            return mx.array(np.log(probs))
        return (slots[..., :1] == mx.arange(256)[None, None, :]) * 12.0


def changing_episode(steps=6, *, seed=9, partition=DatasetPartition.DEVELOPMENT):
    source = episode(steps=steps, seed=seed, partition=partition)
    payloads = [
        item.model_copy(update={"symbols": (tick + 1,) + (2,) * 7})
        for tick, item in enumerate(payloads_for(source))
    ]
    return episode(steps=steps, seed=seed, partition=partition, payloads=payloads)


def run(model=None, data=None, **kwargs):
    return evaluate_one_step_memory(
        model if model is not None else FakeMemory(),
        data if data is not None else [changing_episode()],
        partition=kwargs.pop("partition", DatasetPartition.DEVELOPMENT),
        before_work=kwargs.pop("before_work", lambda _: None),
        support_ticks=kwargs.pop("support_ticks", 2),
        **kwargs,
    )


def batch(steps=3, size=1):
    return {
        "symbols": mx.broadcast_to(
            mx.arange(1, steps + 2, dtype=mx.int32)[None, :, None], (size, steps + 1, 8)
        ),
        "visible_mask": mx.ones((size, steps + 1, 8), dtype=mx.bool_),
        "cursor": mx.zeros((size, steps + 1), dtype=mx.int32),
        "episode_start": mx.zeros((size, steps + 1), dtype=mx.bool_),
        "actions": mx.zeros((size, steps), dtype=mx.int32),
    }


def replaced(values, index, value):
    result = np.array(values, copy=True)
    result[index] = value
    return mx.array(result)


def loss(model=None, data=None, *, burn_in=0):
    return memory_sequence_loss(
        model if model is not None else FakeMemory(),
        data if data is not None else batch(),
        burn_in=burn_in,
        key=mx.random.key(71),
    )


def test_previous_frame_is_read_after_current_observation_without_fitting_or_mutation():
    model, data = FakeMemory(), changing_episode()
    saved_data, saved_weights = deepcopy(data), model.weights.copy()
    result = run(model, [data])
    assert result["query_count"] == 5
    assert result["methods"]["memory_tail"]["accuracy"] == 1.0
    assert result["methods"]["memory_tail"]["changed_accuracy"] == 1.0
    assert result["methods"]["memory_tail"]["count"] == 40
    assert result["methods"]["memory_tail"]["changed_count"] == 5
    assert result["methods"]["copy_current"]["changed_accuracy"] == 0.0
    assert result["methods"]["fixed_current_codec"]["changed_accuracy"] == 0.0
    assert result["methods"]["reset_history"]["accuracy"] == 0.0
    assert data == saved_data
    np.testing.assert_array_equal(model.weights, saved_weights)
    assert result["protocol"]["weight_updates"] is False
    assert result["protocol"]["fitted_readout"] is False


def test_evaluation_rejects_a_tail_erased_by_the_current_observation():
    result = run(FakeMemory(erase_on_observe=True))
    assert result["methods"]["memory_tail"]["accuracy"] == 0
    assert result["methods"]["fixed_current_codec"]["accuracy"] == 7 / 8


def test_dense_queries_include_final_tick_and_per_world_reconcile():
    data = [
        make_episode(steps=128, seed=seed, partition=DatasetPartition.DEVELOPMENT)[0]
        for seed in range(4)
    ]
    reservations = []
    result = run(data=data, support_ticks=32, before_work=reservations.append)
    assert result["query_count"] == 388
    assert result["methods"]["memory_tail"]["count"] == 3104
    assert result["logical_model_transitions"] == 4 * (129 + 97) * 8 == 7232
    assert sum(reservations) == result["logical_model_transitions"]
    assert result["initial_observation_encodes"] == 32
    assert result["feedback_model_transitions"] == 4096
    assert result["reset_observation_encodes"] == 3104
    for row in result["per_world"]:
        assert row["query_ticks"] == list(range(32, 129))
        assert row["query_count"] == 97
        assert row["methods"]["memory_tail"]["count"] == 776


def test_every_initial_and_feedback_is_prepaid_and_reset_reuses_current_input_and_key():
    events = []
    run(FakeMemory(events=events), before_work=lambda count: events.append(("reserve", count)))
    observations = [event for event in events if event[0] == "observe"]
    assert len(observations) == 12  # Seven full-history and five reset observations.
    for index, event in enumerate(events):
        if event[0] in ("initial", "imagine"):
            assert events[index - 1] == ("reserve", 8)
        if event[0] == "observe":
            assert events[index - 1][0] in ("initial", "imagine")
        if event[0] == "initial" and index > 1:
            # All later initials belong to reset controls, immediately followed
            # by the exact current input and key of the preceding full observe.
            full = next(item for item in reversed(events[:index]) if item[0] == "observe")
            reset = events[index + 1]
            assert reset[1:5] == full[1:5]
            assert not np.asarray(reset[5]).any()


def test_budget_rejection_precedes_lazy_import_and_all_student_work(monkeypatch):
    model, imports = FakeMemory(), []
    original_import = builtins.__import__

    def track_import(name, *args, **kwargs):
        if name.startswith("mlx"):
            imports.append(name)
        return original_import(name, *args, **kwargs)

    def reject(_):
        raise RuntimeError("budget exhausted")

    monkeypatch.setattr(builtins, "__import__", track_import)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run(model, before_work=reject)
    assert imports == model.events == []


@pytest.mark.parametrize("reject_at", [2, 4, 7])
def test_later_budget_rejection_precedes_next_model_call(reject_at):
    model, reservations = FakeMemory(), []

    def reserve(count):
        reservations.append((count, len(model.events)))
        if len(reservations) == reject_at:
            raise RuntimeError("budget exhausted")

    with pytest.raises(RuntimeError, match="budget exhausted"):
        run(model, before_work=reserve)
    assert len(model.events) == reservations[-1][1]


def test_evaluation_averages_particle_probabilities_before_nll():
    source = episode(steps=2)
    payloads = [item.model_copy(update={"symbols": (0,) * 8}) for item in payloads_for(source)]
    result = run(FakeMemory(mixture=True), [episode(steps=2, payloads=payloads)])
    assert result["methods"]["memory_tail"]["nll"] == pytest.approx(-np.log(0.5), abs=1e-6)


def test_hidden_past_is_excluded_while_current_visibility_only_limits_change_groups():
    source = changing_episode(steps=2)
    payloads = payloads_for(source)
    payloads[1] = payloads[1].model_copy(
        update={"symbols": (0, 2, 2, 2, 2, 2, 2, 2), "visible_mask": (False,) + (True,) * 7}
    )
    payloads[2] = payloads[2].model_copy(
        update={"symbols": (3, 0, 2, 2, 2, 2, 2, 2), "visible_mask": (True, False) + (True,) * 6}
    )
    result = run(data=[episode(steps=2, payloads=payloads)])
    for method in result["methods"].values():
        assert method["count"] == 7
        assert method["changed_count"] == 0
        assert method["unchanged_count"] == 6


def test_train_evaluation_requires_explicit_matching_partition_and_is_frozen():
    result = run(
        data=[changing_episode(partition=DatasetPartition.TRAIN)], partition=DatasetPartition.TRAIN
    )
    assert result["partition"] == "train"
    assert result["methods"]["memory_tail"]["accuracy"] == 1


@pytest.mark.parametrize("partition", [DatasetPartition.FINAL, DatasetPartition.QUARANTINE, "x"])
def test_final_and_quarantine_partitions_rejected_before_work(partition):
    model, reservations = FakeMemory(), []
    with pytest.raises(ValueError, match="train or development"):
        run(model, partition=partition, before_work=reservations.append)
    assert model.events == reservations == []


def test_partition_mismatch_and_duplicate_world_rejected_before_work():
    model = FakeMemory()
    with pytest.raises(ValueError, match="declared partition"):
        run(model, data=[changing_episode(partition=DatasetPartition.TRAIN)])
    data = changing_episode()
    with pytest.raises(ValueError, match="must be distinct"):
        run(model, data=[data, data])
    assert model.events == []


@pytest.mark.parametrize("data", [[], [changing_episode(steps=1)]])
def test_no_queries_have_no_model_work_or_invented_metrics(data):
    model, reservations = FakeMemory(), []
    result = run(model, data, before_work=reservations.append)
    assert result["query_count"] == result["logical_model_transitions"] == 0
    assert result["methods"]["memory_tail"]["count"] == 0
    assert result["methods"]["memory_tail"]["accuracy"] is None
    assert model.events == reservations == []


@pytest.mark.parametrize(
    "options",
    [
        {"seed": -1},
        {"seed": True},
        {"seed": 2**32},
        {"support_ticks": 0},
        {"support_ticks": True},
        {"particles": 1},
        {"particles": True},
        {"before_work": None},
    ],
)
def test_invalid_options_rejected_before_work(options):
    model = FakeMemory()
    with pytest.raises(ValueError):
        run(model, **options)
    assert model.events == []


def test_loss_uses_existing_tail_after_observe_and_has_exact_sequence_call_count():
    model = FakeMemory()
    value, metrics = loss(model, batch(steps=5, size=2), burn_in=2)
    assert value.item() < 0.01
    assert metrics["visible_targets"].item() == 2 * 3 * 8
    assert metrics["valid_transitions"].item() == 6
    assert sum(event[0] == "observe" for event in model.events) == 6
    assert sum(event[0] == "imagine" for event in model.events) == 5
    assert sum(event[0] == "initial" for event in model.events) == 1
    assert loss(FakeMemory(erase_on_observe=True))[0].item() > 10


def test_loss_masks_hidden_poison_invalid_edges_and_episode_boundaries():
    data = batch(steps=4)
    data["symbols"] = data["symbols"].at[:, :, 0].add(1000)
    data["visible_mask"] = replaced(data["visible_mask"], (slice(None), slice(None), 0), False)
    data["valid_mask"] = mx.array([[True, False, True, True]])
    data["episode_start"] = replaced(data["episode_start"], (slice(None), 3), True)
    model = FakeMemory()
    value, metrics = loss(model, data)
    assert np.isfinite(value.item())
    assert metrics["valid_transitions"].item() == 2
    assert metrics["visible_targets"].item() == 14
    observations = [event for event in model.events if event[0] == "observe"]
    assert not np.asarray(observations[3][5]).any()
    # The step after an internal reset remembers only that episode's first frame.
    assert value.item() < 0.01


def test_loss_with_no_valid_visible_targets_is_zero_without_nan():
    data = batch()
    data["valid_mask"] = mx.zeros((1, 3), dtype=mx.bool_)
    value, metrics = loss(data=data)
    assert value.item() == 0
    assert metrics["visible_targets"].item() == 0


def test_valid_edge_after_invalid_hole_has_the_correct_preceding_observation():
    data = batch()
    data["valid_mask"] = mx.array([[True, False, True]])
    value, metrics = loss(data=data)
    assert value.item() < 0.01
    assert metrics["valid_transitions"].item() == 2


def test_loss_is_uniform_per_visible_cell_without_change_reweighting():
    data = batch(steps=2)
    # Erasing the tail predicts zero: one correct visible cell, eight incorrect
    # visible cells. Cell-uniform weighting must not weight these frames equally.
    data["symbols"] = replaced(data["symbols"], (slice(None), 0), 0)
    data["visible_mask"] = replaced(data["visible_mask"], (slice(None), 0, slice(1, None)), False)
    value, metrics = loss(FakeMemory(erase_on_observe=True), data)
    zero_nll = np.log(1 + 255 * np.exp(-12))
    assert metrics["visible_targets"].item() == 9
    assert value.item() == pytest.approx(zero_nll + 12 * 8 / 9, abs=1e-6)


def test_loss_explicit_keys_are_reproducible_and_do_not_consume_global_rng():
    mx.random.seed(19)
    expected = mx.random.normal((8,))
    mx.eval(expected)
    mx.random.seed(19)
    first, second = FakeMemory(), FakeMemory()
    assert loss(first)[0].item() == loss(second)[0].item()
    np.testing.assert_array_equal(np.asarray(mx.random.normal((8,))), np.asarray(expected))
    assert first.events == second.events


@pytest.mark.parametrize(
    "name", ["symbols", "visible_mask", "cursor", "episode_start", "valid_mask"]
)
def test_invalid_sequence_shapes_rejected_before_model_work(name):
    data = batch()
    data[name] = mx.zeros((1,))
    model = FakeMemory()
    with pytest.raises(ValueError, match="must have shape"):
        loss(model, data)
    assert model.events == []


@pytest.mark.parametrize("burn_in", [-1, 3, True])
def test_invalid_burn_in_rejected_before_model_work(burn_in):
    model = FakeMemory()
    with pytest.raises(ValueError, match="burn_in"):
        loss(model, burn_in=burn_in)
    assert model.events == []


def test_loss_refuses_private_or_future_auxiliary_fields():
    data = dict(batch(), private_state=mx.zeros((1,)))
    with pytest.raises(ValueError, match="only the public"):
        loss(data=data)


class ToyGRU(nn.Module):
    def __init__(self):
        super().__init__()
        self.gain = mx.array([0.1, 0.2, 0.3, 0.4])

    def __call__(self, h, actions):
        tail = h[:, 128:] * 0.2 + h[:, :128] * self.gain[actions, None]
        return mx.concatenate([h[:, :128], tail], axis=-1)


class ToyTrainableMemory(nn.Module):
    """Tiny differentiable module to check gradient flow, never the student."""

    def __init__(self):
        super().__init__()
        self.gru = ToyGRU()
        self.codec_scale = mx.array([0.1])

    def initial(self, size):
        return mx.zeros((size, 256)), mx.zeros((size, 16))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        slots = mx.broadcast_to(
            mx.where(visible_mask, symbols, 0)[..., None] * self.codec_scale,
            (*symbols.shape, 16),
        ).reshape(-1, 128)
        return {"h": mx.concatenate([slots, h[:, 128:]], axis=-1), "z": h[:, :16]}

    def imagine(self, h, z, actions, *, key):
        return {"h": self.gru(h, actions), "z": z}

    def symbol_readout(self, slots):
        return -((slots[..., :1] - mx.arange(256)[None, None, :] * 0.01) ** 2)


def test_burn_in_detaches_history_and_frozen_codec_has_no_gradient_keys():
    model = ToyTrainableMemory()
    model.freeze()
    model.gru.unfreeze()
    data = batch(steps=3)
    data["actions"] = mx.array([[0, 1, 1]])
    (value, metrics), grads = nn.value_and_grad(model, memory_sequence_loss)(
        model, data, burn_in=1, key=mx.random.key(6)
    )
    mx.eval(value, metrics, grads)
    assert [name for name, _ in tree_flatten(grads)] == ["gru.gain"]
    grad = np.asarray(grads["gru"]["gain"])
    assert grad[0] == 0
    assert abs(grad[1]) > 0
    # Burn-in still contributes the numerical state, despite being detached.
    before = value.item()
    model.gru.gain = replaced(model.gru.gain, 0, 0.9)
    after = memory_sequence_loss(model, data, burn_in=1, key=mx.random.key(6))[0].item()
    assert not np.isclose(before, after, atol=1e-7, rtol=0)


def test_future_observations_do_not_change_an_earlier_loss_or_state_trace():
    data = batch(steps=3)
    changed = dict(data, symbols=replaced(data["symbols"], (slice(None), 3), 91))
    first, second = FakeMemory(), FakeMemory()
    # Perfect synthetic recall remains correct after ingesting different final
    # observations; a shortcut that reads the current front would fail here.
    assert loss(first, data)[0].item() == loss(second, changed)[0].item()
    first_calls = [event for event in first.events if event[0] in ("observe", "imagine")]
    second_calls = [event for event in second.events if event[0] in ("observe", "imagine")]
    assert first_calls[:-1] == second_calls[:-1]
