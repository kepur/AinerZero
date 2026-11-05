import builtins
from copy import deepcopy

import mlx.core as mx
import numpy as np
import pytest
from test_pilot_evaluation import episode, payloads_for
from test_sequences import make_episode

from ainerzero.core.experience import DatasetPartition
from ainerzero.learning.reconstruction import evaluate_reconstruction, reconstruction_gate

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


class FakeReconstructor:
    """Inspectable, weight-free encoder/decoder; no learning or imagined actions."""

    def __init__(self, *, events=None, mixture=False, damage_roundtrip=False):
        self.events = events if events is not None else []
        self.weights = np.array([1.25])
        self.mixture = mixture
        self.damage_roundtrip = damage_roundtrip
        self.decode_calls = 0

    def initial(self, size):
        self.events.append(("initial", size))
        return mx.zeros((size, 8)), mx.zeros((size, 8))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        assert np.array_equal(np.asarray(h), np.zeros(h.shape))
        self.events.append(
            (
                "observe",
                np.asarray(symbols).tolist(),
                np.asarray(visible_mask).tolist(),
                np.asarray(cursor).tolist(),
                np.asarray(key).tolist(),
            )
        )
        return {
            "h": mx.where(visible_mask, symbols, 0).astype(mx.float32),
            "z": visible_mask.astype(mx.float32),
            # Deliberately unusable: the evaluator must explicitly decode h/z.
            "logits": {"symbols": mx.full((symbols.shape[0], 8, 256), float("nan"))},
        }

    def decode(self, h, z):
        self.decode_calls += 1
        self.events.append(("decode", np.asarray(h).tolist()))
        size = h.shape[0]
        if self.mixture:
            probabilities = np.full((size, 8, 256), 0.2 / 255)
            probabilities[: size // 2, :, 0] = 0.8
            probabilities[size // 2 :, :, :] = 0.8 / 255
            probabilities[size // 2 :, :, 0] = 0.2
            symbols = mx.array(np.log(probabilities))
        else:
            symbols = (mx.arange(256)[None, None, :] == h[:, :, None]) * 12.0
        if self.damage_roundtrip and self.decode_calls % 2 == 0:
            symbols = symbols + 1.0
        return {"symbols": symbols, "visibility": z}


@pytest.fixture(autouse=True)
def cpu_stream():
    with mx.stream(mx.cpu):
        yield


def run(model=None, data=None, **kwargs):
    return evaluate_reconstruction(
        model if model is not None else FakeReconstructor(),
        data if data is not None else [episode()],
        before_work=kwargs.pop("before_work", lambda _: None),
        **kwargs,
    )


def nonzero_episode(steps=6, **kwargs):
    source = episode(steps=steps)
    payloads = [
        item.model_copy(update={"symbols": tuple(range(1, 9))}) for item in payloads_for(source)
    ]
    return episode(steps=steps, payloads=payloads, **kwargs)


def test_reconstructs_from_state_and_roundtrips_without_weights_or_action_changes():
    model = FakeReconstructor()
    data = nonzero_episode()
    original_data, weights = deepcopy(data), model.weights.copy()
    result = run(model, [data])
    assert result["model"]["accuracy"] == 1.0
    assert result["model"]["nll"] < 0.01
    assert result["model"]["count"] == 16
    assert result["zero_symbols"]["accuracy"] == 0.0
    assert result["ablation_gap"]["nll_increase"] == pytest.approx(12.0)
    assert result["state_roundtrip_equal"] is True
    assert result["gate"]["status"] == "passed"
    assert result["gate"]["dynamics"] == result["gate"]["long_term_memory"] == "not_evaluated"
    assert result["state_roundtrip_checks"] == result["observation_encodes"] == 32
    assert model.decode_calls == 4
    assert np.array_equal(model.weights, weights)
    assert data == original_data


def test_fixed_tick_sampling_includes_final_and_short_partial_batch():
    data, _, _ = make_episode(128, partition=DatasetPartition.DEVELOPMENT)
    calls = []
    result = run(data=[data], batch_size=6, before_work=calls.append)
    assert result["sampled_ticks"][0]["ticks"] == list(range(0, 129, 8))
    assert result["observation_count"] == 17
    assert result["model"]["count"] == 17 * 8
    assert calls == [48, 48, 48, 48, 40, 40]
    assert result["observation_encodes"] == 17 * 8 * 2
    assert "environment_steps" not in result


def test_each_branch_reserves_before_model_and_matches_ablation_randomness():
    events = []
    model = FakeReconstructor(events=events)
    result = run(
        model,
        [nonzero_episode()],
        batch_size=1,
        before_work=lambda n: events.append(("reserve", n)),
    )
    assert result["observation_encodes"] == 32
    assert [event[0] for event in events] == [
        "reserve",
        "initial",
        "observe",
        "decode",
        "decode",
    ] * 4
    observations = [event for event in events if event[0] == "observe"]
    for real, zero in zip(observations[::2], observations[1::2], strict=True):
        assert real[1] != zero[1]
        assert np.asarray(zero[1]).sum() == 0
        assert real[2:] == zero[2:]


def test_budget_rejection_precedes_even_lazy_runtime_import(monkeypatch):
    model = FakeReconstructor()
    data = [episode()]
    original_import = builtins.__import__
    imports = []

    def tracked_import(name, *args, **kwargs):
        if name.startswith("mlx"):
            imports.append(name)
        return original_import(name, *args, **kwargs)

    def reject(_):
        raise RuntimeError("budget exhausted")

    monkeypatch.setattr(builtins, "__import__", tracked_import)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        run(model, data, before_work=reject)
    assert imports == []
    assert model.events == []


def test_second_branch_budget_rejection_never_observes_ablated_input():
    model = FakeReconstructor()
    reservations = []

    def reject_second(count):
        reservations.append(count)
        if len(reservations) == 2:
            raise RuntimeError("second reservation rejected")

    with pytest.raises(RuntimeError, match="second reservation"):
        run(model, before_work=reject_second)
    assert [event[0] for event in model.events] == ["initial", "observe", "decode", "decode"]


def test_mean_particle_probability_precedes_nll():
    source = episode(steps=1)
    payloads = [item.model_copy(update={"symbols": (0,) * 8}) for item in payloads_for(source)]
    result = run(FakeReconstructor(mixture=True), [episode(steps=1, payloads=payloads)])
    assert result["model"]["nll"] == pytest.approx(-np.log(0.5), abs=1e-6)
    assert result["model"]["nll"] != pytest.approx((-np.log(0.8) - np.log(0.2)) / 2)
    assert result["gate"]["status"] == "not_passed"


def test_hidden_targets_excluded_and_per_position_counts_reconcile():
    source = nonzero_episode(steps=1)
    payloads = payloads_for(source)
    payloads[1] = payloads[1].model_copy(
        update={"symbols": (1,) + (0,) * 7, "visible_mask": (True,) + (False,) * 7}
    )
    result = run(data=[episode(steps=1, payloads=payloads)])
    for name in ("model", "zero_symbols"):
        metric = result[name]
        assert metric["count"] == 9
        assert [row["count"] for row in metric["per_position"]] == [2] + [1] * 7
        assert sum(row["count"] for row in metric["per_position"]) == metric["count"]
        assert metric["nll"] == pytest.approx(
            sum(row["nll"] * row["count"] for row in metric["per_position"]) / 9
        )


@pytest.mark.parametrize("empty_episodes", [False, True])
def test_no_visible_targets_cannot_pass(empty_episodes):
    source = episode(steps=1)
    payloads = [
        item.model_copy(update={"symbols": (0,) * 8, "visible_mask": (False,) * 8})
        for item in payloads_for(source)
    ]
    result = run(data=[] if empty_episodes else [episode(steps=1, payloads=payloads)])
    assert result["model"]["count"] == result["zero_symbols"]["count"] == 0
    assert result["model"]["nll"] is result["model"]["accuracy"] is None
    assert result["ablation_gap"]["nll_increase"] is None
    assert result["gate"]["status"] == "not_passed"
    if empty_episodes:
        assert result["state_roundtrip_equal"] is False
        assert result["observation_encodes"] == 0


def test_recorded_actions_never_enter_reconstruction():
    data = nonzero_episode()
    changed = []
    for transition in data.transitions:
        action = (transition.action_request.action + 1) % 4
        changed.append(
            transition.model_copy(
                update={
                    "action_request": transition.action_request.model_copy(
                        update={"action": action}
                    ),
                    "action_result": transition.action_result.model_copy(update={"action": action}),
                }
            )
        )
    altered = data.model_copy(update={"transitions": tuple(changed)})
    first, second = FakeReconstructor(), FakeReconstructor()
    assert run(first, [data]) == run(second, [altered])
    assert first.events == second.events


def test_state_transport_mismatch_prevents_gate_pass():
    result = run(FakeReconstructor(damage_roundtrip=True), [nonzero_episode()])
    assert result["model"]["accuracy"] == 1.0
    assert result["state_roundtrip_equal"] is False
    assert result["gate"]["status"] == "not_passed"


@pytest.mark.parametrize(
    "partition", [DatasetPartition.TRAIN, DatasetPartition.FINAL, DatasetPartition.QUARANTINE]
)
def test_only_development_accepted_before_model_or_budget_work(partition):
    model, reservations = FakeReconstructor(), []
    with pytest.raises(ValueError, match="only development"):
        run(model, [episode(partition=partition)], before_work=reservations.append)
    assert reservations == model.events == []


def test_duplicate_worlds_and_episodes_rejected_before_model_work():
    data = episode()
    model = FakeReconstructor()
    with pytest.raises(ValueError, match="must be distinct"):
        run(model, [data, data])
    assert model.events == []


@pytest.mark.parametrize(
    "options",
    [
        {"seed": -1},
        {"seed": True},
        {"seed": 2**32},
        {"batch_size": 0},
        {"batch_size": 257},
        {"batch_size": True},
        {"before_work": None},
    ],
)
def test_invalid_options_rejected_before_model_work(options):
    model = FakeReconstructor()
    with pytest.raises(ValueError):
        run(model, **options)
    assert model.events == []


def test_gate_requires_every_measured_position_not_just_aggregate():
    result = run(data=[nonzero_episode()])
    result["model"]["accuracy"] = 0.98
    result["model"]["per_position"][7]["accuracy"] = 0.84
    gate = reconstruction_gate(result)
    assert gate["checks"]["reconstruction_accuracy_at_least_0_95"] is True
    assert gate["checks"]["each_measured_position_accuracy_at_least_0_95"] is False
    assert gate["status"] == "not_passed"


@pytest.mark.parametrize(
    "field,value",
    [("accuracy", float("nan")), ("nll", float("inf")), ("count", 0), ("count", True)],
)
def test_gate_rejects_invalid_or_empty_metrics(field, value):
    result = run(data=[nonzero_episode()])
    result["model"][field] = value
    assert reconstruction_gate(result)["status"] == "not_passed"
