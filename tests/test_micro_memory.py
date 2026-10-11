"""CPU-only synthetic examples; never initialize or optimize a real student."""

import builtins
import hashlib
import json
from copy import deepcopy
from pathlib import Path

import mlx.core as mx
import numpy as np
import pytest
from test_one_step_memory import FakeMemory
from test_pilot_evaluation import episode, payloads_for

from ainerzero.core.experience import DatasetPartition
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.micro_memory import (
    evaluate_micro_memory,
    select_micro_memory_samples,
)
from ainerzero.learning.one_step_memory import memory_sequence_loss


@pytest.fixture(autouse=True)
def cpu_only():
    previous = mx.default_device()
    mx.set_default_device(mx.cpu)
    yield
    mx.set_default_device(previous)


def examples(count=16, *, partition=DatasetPartition.TRAIN, change=True):
    result = []
    for index in range(count):
        source = episode(seed=index + 10, steps=3, partition=partition)
        payloads = payloads_for(source)
        for tick, payload in enumerate(payloads):
            symbols = [index + 2] * 8
            if change and tick >= 2:
                symbols[0] += 1
            if change and tick >= 3:
                symbols[1] += 1
            payloads[tick] = payload.model_copy(update={"symbols": tuple(symbols)})
        result.append(episode(seed=index + 10, steps=3, partition=partition, payloads=payloads))
    return result


def selected():
    return select_micro_memory_samples(examples())


def run(model=None, batch=None, **kwargs):
    return evaluate_micro_memory(
        model if model is not None else FakeMemory(),
        selected()[0] if batch is None else batch,
        seed=kwargs.pop("seed", 2203),
        before_work=kwargs.pop("before_work", lambda _: None),
        **kwargs,
    )


def test_selection_is_earliest_visible_change_from_each_stably_ordered_world():
    source = examples()
    batch, evidence = select_micro_memory_samples(source)
    expected = sorted(source, key=lambda item: str(item.initial.context.episode_id))
    assert list(batch) == ["symbols", "visible_mask", "cursor", "episode_start", "actions"]
    assert batch["symbols"].shape == batch["visible_mask"].shape == (16, 2, 8)
    assert batch["cursor"].shape == batch["episode_start"].shape == (16, 2)
    assert batch["actions"].shape == (16, 1)
    assert batch["episode_start"][:, 0].all()
    assert not batch["episode_start"][:, 1].any()
    assert evidence["changed_count"] == 16
    assert evidence["unchanged_count"] == 112
    assert evidence["target_visible_count"] == 128
    assert evidence["partition"] == "train"
    assert evidence["burn_in"] == 0
    assert evidence["sequence_steps"] == 1
    for row, (item, identity) in enumerate(zip(expected, evidence["samples"], strict=True)):
        transition = item.transitions[1]
        assert identity["row"] == row
        assert identity["episode_id"] == str(item.initial.context.episode_id)
        assert identity["environment_instance_id"] == str(
            item.initial.context.environment_instance_id
        )
        assert identity["transition_index"] == identity["target_tick"] == 1
        assert identity["query_tick"] == 2
        assert identity["target_observation_id"] == str(transition.observation.id)
        assert identity["current_observation_id"] == str(transition.next_observation.id)
        assert identity["action_request_id"] == str(transition.action_request.id)
        np.testing.assert_array_equal(
            batch["symbols"][row, 0], transition.observation.payload.symbols
        )
        np.testing.assert_array_equal(
            batch["symbols"][row, 1], transition.next_observation.payload.symbols
        )
        assert batch["actions"][row, 0] == transition.action_request.action


def test_selection_hashes_are_json_reproducible_and_input_order_independent():
    source = examples()
    batch, evidence = select_micro_memory_samples(source)
    reverse_batch, reverse_evidence = select_micro_memory_samples(list(reversed(source)))
    assert evidence == reverse_evidence
    for name in batch:
        np.testing.assert_array_equal(batch[name], reverse_batch[name])
    encoded = json.dumps(
        {name: value.tolist() for name, value in batch.items()},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert evidence["batch_sha256"] == hashlib.sha256(encoded).hexdigest()
    json.dumps(evidence, allow_nan=False)
    for row in evidence["samples"]:
        for name in ("public_episode_sha256", "public_transition_sha256", "public_sample_sha256"):
            assert len(row[name]) == 64


def test_selection_only_uses_public_records_and_returns_independent_arrays(monkeypatch):
    source = examples()
    saved = deepcopy(source)

    def forbid_read(*_args, **_kwargs):
        raise AssertionError("selection must not read snapshots or any filesystem path")

    monkeypatch.setattr(Path, "open", forbid_read)
    batch, evidence = select_micro_memory_samples(source)
    for value in batch.values():
        value[...] = 0
    assert source == saved
    assert evidence["changed_count"] == 16


@pytest.mark.parametrize("count", [0, 1, 15, 17])
def test_selection_requires_exactly_sixteen_worlds(count):
    with pytest.raises(ValueError, match="exactly 16"):
        select_micro_memory_samples(examples(count))


def test_duplicate_worlds_and_episodes_rejected():
    source = examples()
    source[-1] = source[0]
    with pytest.raises(ValueError, match="distinct"):
        select_micro_memory_samples(source)


@pytest.mark.parametrize("partition", [DatasetPartition.DEVELOPMENT, DatasetPartition.FINAL])
def test_nontraining_examples_rejected(partition):
    with pytest.raises(ValueError, match="partition"):
        select_micro_memory_samples(examples(partition=partition))


def test_no_changed_edge_fails_without_unchanged_fallback():
    source = examples()
    source[0] = examples(change=False)[0]
    with pytest.raises(ValueError, match="no mutually visible changed"):
        select_micro_memory_samples(source)


def test_zero_transition_episode_fails_without_fallback():
    source = examples()
    source[0] = episode(steps=0, seed=999, partition=DatasetPartition.TRAIN)
    with pytest.raises(ValueError, match="no mutually visible changed"):
        select_micro_memory_samples(source)


@pytest.mark.parametrize("change", ["actor", "assistance"])
def test_policy_checks_even_unselected_later_transitions(change):
    source = examples()
    values = source[0].model_dump(mode="json")
    request = values["transitions"][-1]["action_request"]
    if change == "actor":
        request["actor"]["policy_revision"] = "other-policy"
    else:
        request["assistance"] = ["curriculum"]
    source[0] = EpisodeTrajectory.model_validate(values)
    with pytest.raises(ValueError, match="source|authorized"):
        select_micro_memory_samples(source)


def test_consistent_but_unapproved_actor_is_rejected_by_training_policy():
    source = []
    for item in examples():
        values = item.model_dump(mode="json")
        for transition in values["transitions"]:
            transition["action_request"]["actor"]["actor_id"] = "unapproved"
        source.append(EpisodeTrajectory.model_validate(values))
    with pytest.raises(ValueError, match="actor or policy revision is not authorized"):
        select_micro_memory_samples(source)


def test_change_selection_requires_visibility_at_both_ends():
    source = examples()
    data = source[0]
    payloads = payloads_for(data)
    # Hide the first changed cell at t=1: earliest valid change becomes t=3.
    payloads[1] = payloads[1].model_copy(
        update={"symbols": (0,) + payloads[1].symbols[1:], "visible_mask": (False,) + (True,) * 7}
    )
    source[0] = episode(seed=10, steps=3, partition=DatasetPartition.TRAIN, payloads=payloads)
    _, evidence = select_micro_memory_samples(source)
    row = next(
        item
        for item in evidence["samples"]
        if item["episode_id"] == str(source[0].initial.context.episode_id)
    )
    assert row["target_tick"] == 2
    assert row["query_tick"] == 3
    assert row["changed_count"] == 1


def test_evaluation_perfect_fake_memory_keeps_examples_separate_and_does_not_modify():
    batch, evidence = selected()
    saved = deepcopy(batch)
    model = FakeMemory()
    weights = model.weights.copy()
    result = run(model, batch)
    assert result["batch_sha256"] == evidence["batch_sha256"]
    assert result["methods"]["memory_tail"]["accuracy"] == 1
    assert result["methods"]["memory_tail"]["changed_accuracy"] == 1
    assert result["methods"]["memory_tail"]["count"] == 128
    assert result["methods"]["memory_tail"]["changed_count"] == 16
    assert result["methods"]["copy_current"]["accuracy"] == 7 / 8
    assert result["methods"]["fixed_current_codec"]["changed_accuracy"] == 0
    assert result["methods"]["reset_history"]["accuracy"] == 0
    assert result["particles"] == 1
    assert result["noise_condition"] == "training_noise"
    assert result["protocol"]["generalization_evaluation"] is False
    assert result["protocol"]["weight_updates"] is False
    assert result["protocol"]["fitted_readout"] is False
    assert result["protocol"]["tail_prefilled"] is False
    assert [row["row"] for row in result["per_sample"]] == list(range(16))
    for name in saved:
        np.testing.assert_array_equal(batch[name], saved[name])
    np.testing.assert_array_equal(model.weights, weights)
    json.dumps(result, allow_nan=False)


def test_other_noise_uses_same_inputs_and_is_not_called_generalization():
    batch, _ = selected()
    old_model, new_model = FakeMemory(), FakeMemory()
    old = run(old_model, batch)
    new = run(new_model, batch, seed=2603)
    assert new["noise_condition"] == "same_inputs_new_noise"
    assert old["batch_sha256"] == new["batch_sha256"]
    assert new["protocol"]["generalization_evaluation"] is False
    old_observes = [event for event in old_model.events if event[0] == "observe"]
    new_observes = [event for event in new_model.events if event[0] == "observe"]
    assert [row[1:4] for row in old_observes] == [row[1:4] for row in new_observes]
    assert [row[4] for row in old_observes] != [row[4] for row in new_observes]


def test_reservation_covers_each_micro_before_tensor_or_model_work():
    events = []
    result = run(FakeMemory(events=events), before_work=lambda n: events.append(("reserve", n)))
    assert [row for row in events if row[0] == "reserve"] == [("reserve", 12)] * 4
    assert result["logical_model_transitions"] == 48
    assert result["initial_observation_encodes"] == 16
    assert result["feedback_model_transitions"] == 16
    assert result["reset_observation_encodes"] == 16
    for index, event in enumerate(events):
        if event[0] == "reserve":
            assert events[index + 1] == ("initial", 4)


@pytest.mark.parametrize("reject_at", [1, 2, 4])
def test_budget_rejection_precedes_lazy_import_and_remaining_student_work(monkeypatch, reject_at):
    batch, _ = selected()
    model, imports, reservations = FakeMemory(), [], []
    original = builtins.__import__

    def track(name, *args, **kwargs):
        if name.startswith("mlx"):
            imports.append(name)
        return original(name, *args, **kwargs)

    def reserve(count):
        reservations.append((count, len(model.events), len(imports)))
        if len(reservations) == reject_at:
            raise RuntimeError("budget exhausted")

    monkeypatch.setattr(builtins, "__import__", track)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run(model, batch, before_work=reserve)
    assert len(model.events) == reservations[-1][1]
    assert len(imports) == reservations[-1][2]


def test_seed_keys_and_memory_nll_match_fixed_training_microbatches():
    batch, _ = selected()
    evaluation_model = FakeMemory()
    result = run(evaluation_model, batch)
    keys = mx.random.split(mx.random.key(2203), num=4)
    losses, expected_keys = [], []
    for index in range(4):
        model = FakeMemory()
        micro = {
            name: mx.array(value[index * 4 : (index + 1) * 4]) for name, value in batch.items()
        }
        value, _ = memory_sequence_loss(model, micro, burn_in=0, key=keys[index])
        losses.append(float(value))
        expected_keys.extend([row[4] for row in model.events if row[0] == "observe"])
        expected_imagine = next(row for row in model.events if row[0] == "imagine")
        observed_imagine = [row for row in evaluation_model.events if row[0] == "imagine"][index]
        assert expected_imagine == observed_imagine
    observed = [row for row in evaluation_model.events if row[0] == "observe"]
    retained = [row[4] for index, row in enumerate(observed) if index % 3 != 2]
    assert retained == expected_keys
    # The frozen scorer uses float64 softmax; the training CE is float32.
    assert result["methods"]["memory_tail"]["nll"] == pytest.approx(np.mean(losses), abs=3e-6)


def test_context_is_zero_per_micro_and_reset_uses_same_current_inputs_and_key():
    model = FakeMemory()
    run(model)
    observes = [row for row in model.events if row[0] == "observe"]
    assert len(observes) == 12
    for start in range(0, 12, 3):
        initial, posterior, reset = observes[start : start + 3]
        assert not np.asarray(initial[5]).any()
        assert not np.asarray(reset[5]).any()
        assert posterior[1:5] == reset[1:5]


def test_overall_and_changed_metrics_ignore_hidden_past_symbols():
    batch, _ = selected()
    batch["visible_mask"][:, 0, 1] = False
    batch["symbols"][:, 0, 1] = 0
    result = run(batch=batch)
    memory = result["methods"]["memory_tail"]
    assert memory["count"] == 112
    assert memory["changed_count"] == 16
    assert memory["unchanged_count"] == 96
    assert memory["accuracy"] == 1


def test_current_hidden_symbols_only_exclude_change_and_unchanged_groups():
    batch, _ = selected()
    batch["visible_mask"][:, 1, 1] = False
    batch["symbols"][:, 1, 1] = 0
    result = run(batch=batch)
    memory = result["methods"]["memory_tail"]
    assert memory["count"] == 128
    assert memory["changed_count"] == 16
    assert memory["unchanged_count"] == 96
    assert memory["accuracy"] == 1


@pytest.mark.parametrize("seed", [True, -1, 0, 2**32, 2203.0, "2203"])
def test_unregistered_seeds_rejected_before_work(seed):
    model, reservations = FakeMemory(), []
    with pytest.raises(ValueError, match="seed"):
        run(model, seed=seed, before_work=reservations.append)
    assert model.events == reservations == []


@pytest.mark.parametrize("size", [True, 1, 8, 4.0])
def test_micro_size_cannot_silently_change_training_noise(size):
    model, reservations = FakeMemory(), []
    with pytest.raises(ValueError, match="micro_batch_size"):
        run(model, micro_batch_size=size, before_work=reservations.append)
    assert model.events == reservations == []


def test_missing_callback_rejected():
    with pytest.raises(ValueError, match="callback"):
        run(before_work=None)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda b: b.update(extra=np.zeros(1)),
        lambda b: b.pop("cursor"),
        lambda b: b.update(symbols=b["symbols"].astype(np.float32)),
        lambda b: b.update(symbols=b["symbols"][:4]),
        lambda b: b.update(visible_mask=b["visible_mask"].astype(np.int32)),
        lambda b: b["symbols"].__setitem__((0, 0, 0), 256),
        lambda b: b["symbols"].__setitem__((0, 0, 0), -1),
        lambda b: b["cursor"].__setitem__((0, 0), 8),
        lambda b: b["actions"].__setitem__((0, 0), 4),
        lambda b: b["episode_start"].__setitem__((0, 0), False),
        lambda b: b["episode_start"].__setitem__((0, 1), True),
        lambda b: b["visible_mask"].__setitem__((0, 0, 0), False),
        lambda b: b["symbols"].__setitem__((0, 1), b["symbols"][0, 0]),
    ],
)
def test_invalid_batch_fails_before_any_budget_or_model_call(mutation):
    batch, _ = selected()
    mutation(batch)
    model, reservations = FakeMemory(), []
    with pytest.raises(ValueError):
        run(model, batch, before_work=reservations.append)
    assert model.events == reservations == []


@pytest.mark.parametrize("failure", ["bad_state", "bad_logits", "nan_logits"])
def test_malformed_model_output_rejected(failure):
    class BrokenMemory(FakeMemory):
        def observe(self, *args, **kwargs):
            result = super().observe(*args, **kwargs)
            if failure == "bad_state":
                result["h"] = result["h"][:, :-1]
            return result

        def symbol_readout(self, slots):
            result = super().symbol_readout(slots)
            if failure == "bad_logits":
                return result[..., :-1]
            if failure == "nan_logits":
                return result * float("nan")
            return result

    with pytest.raises(ValueError, match="shape|finite"):
        run(BrokenMemory())
