"""Pure NumPy model/runtime doubles: no student or real MLX work is launched."""

import builtins
import json
import sys
from copy import deepcopy
from types import ModuleType

import numpy as np
import pytest
from test_sequences import make_episode

from ainerzero.core.experience import DatasetPartition
from ainerzero.data.trajectory import EpisodeTrajectory
from ainerzero.learning.micro_memory import select_micro_memory_samples
from ainerzero.learning.paired_memory import (
    GROUPS,
    METHODS,
    evaluate_paired_memory,
    paired_memory_samples,
)
from ainerzero.runtime.c0_collection import RANDOM_ACTOR


@pytest.fixture(scope="module")
def dataset():
    partitions = {}
    for partition, count in ((DatasetPartition.TRAIN, 16), (DatasetPartition.DEVELOPMENT, 4)):
        rows = []
        for index in range(count):
            value = make_episode(
                128,
                seed=1000 * (partition is DatasetPartition.DEVELOPMENT) + index,
                partition=partition,
            )[0].model_dump(mode="json")
            observations = [value["initial"]]
            for edge in value["transitions"]:
                edge["action_request"]["actor"] = RANDOM_ACTOR.model_dump(mode="json")
                observations.extend((edge["observation"], edge["next_observation"]))
            for observed in observations:
                tick = observed["step"]
                observed["payload"]["symbols"] = [index + 2 + tick // 2] + [index + 2] * 7
                observed["payload"]["visible_mask"] = [True] * 8
                observed["payload"]["cursor"] = tick % 8
            rows.append(EpisodeTrajectory.model_validate(value))
        partitions[partition] = rows
    return partitions


@pytest.fixture
def fake_mlx(monkeypatch):
    package, core = ModuleType("mlx"), ModuleType("mlx.core")
    package.core = core
    core.array = np.array
    core.full = np.full
    core.int32 = np.int32
    core.bool_ = np.bool_
    random = ModuleType("mlx.core.random")
    random.key = lambda seed: int(seed)
    core.random = random
    monkeypatch.setitem(sys.modules, "mlx", package)
    monkeypatch.setitem(sys.modules, "mlx.core", core)
    return core


class FakePairedMemory:
    """Perfect preceding-symbol retention, with an independently visible depth."""

    def __init__(self, *, events=None, history_error=False, mixture=False):
        self.events = [] if events is None else events
        self.weights = np.array([1.25])
        self.history_error = history_error
        self.mixture = mixture

    def initial(self, size):
        self.events.append(("initial", size))
        return np.zeros((size, 256)), np.zeros((size, 1))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        self.events.append(
            (
                "observe",
                symbols[0].tolist(),
                visible_mask[0].tolist(),
                cursor[0].item(),
                key,
                int(h[0, -1]),
            )
        )
        slots = np.broadcast_to(
            np.where(visible_mask, symbols, 0)[..., None], (*symbols.shape, 16)
        ).reshape(-1, 128)
        return {
            "h": np.concatenate([slots, h[:, 128:]], axis=-1),
            "z": np.zeros((symbols.shape[0], 1)),
        }

    def imagine(self, h, z, actions, *, key):
        depth = h[:, -1] + 1
        self.events.append(("imagine", actions.tolist(), key, int(h[0, -1])))
        tail = h[:, :128].copy()
        if self.history_error:
            tail[depth > 1] = 255
        tail[:, -1] = depth
        return {"h": np.concatenate([h[:, :128], tail], axis=-1), "z": z}

    def symbol_readout(self, slots):
        self.events.append(("readout",))
        if self.mixture:
            probabilities = np.full((8, 8, 256), 0.2 / 255)
            probabilities[:4, :, 0] = 0.8
            probabilities[4:, :, :] = 0.8 / 255
            probabilities[4:, :, 0] = 0.2
            return np.log(probabilities)
        return (slots[..., :1] == np.arange(256)[None, None, :]) * 12.0


def run(dataset, **kwargs):
    model = kwargs.pop("model", FakePairedMemory())
    return evaluate_paired_memory(
        model, dataset, before_work=kwargs.pop("before_work", lambda _: None), **kwargs
    )


def changed_episode(data, partition, index, alter):
    result = {key: list(value) for key, value in data.items()}
    value = result[partition][index].model_dump(mode="json")
    alter(value)
    result[partition][index] = EpisodeTrajectory.model_validate(value)
    return result


def test_cpu_evidence_covers_every_edge_and_matches_m2j(dataset, monkeypatch):
    original = builtins.__import__

    def guard(name, *args, **kwargs):
        assert not name.startswith("mlx"), "preregistration must not import MLX"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    evidence = paired_memory_samples(dataset)
    _, old = select_micro_memory_samples(dataset["train"])
    assert evidence["query_count"] == 2560
    assert evidence["world_count"] == 20
    assert evidence["micro_fit_sample_manifest_sha256"] == old["sample_manifest_sha256"]
    assert evidence["micro_fit_batch_sha256"] == old["batch_sha256"]
    assert [evidence["groups"][name]["query_count"] for name in GROUPS] == [16, 2032, 512]
    assert evidence["groups"]["fitted_train"]["changed_count"] == 16
    assert [row["row"] for row in evidence["queries"]] == list(range(2560))
    assert [row["query_tick"] for row in evidence["queries"] if row["group"] == "fitted_train"] == [
        2
    ] * 16
    assert len(evidence["query_manifest_sha256"]) == 64
    json.dumps(evidence, allow_nan=False)


def test_evidence_order_is_stable_and_sensor_overlap_excludes_ids(dataset):
    evidence = paired_memory_samples(dataset)
    reversed_data = {key: list(reversed(value)) for key, value in reversed(list(dataset.items()))}
    assert evidence == paired_memory_samples(reversed_data)
    fitted = [row for row in evidence["queries"] if row["group"] == "fitted_train"]
    assert all(
        row["previous_input_matches_fitted"] and row["edge_input_matches_fitted"] for row in fitted
    )
    # Same symbols but a different cursor are not identical observe inputs.
    first_world = evidence["queries"][:128]
    assert first_world[0]["previous_input_sha256"] != first_world[1]["previous_input_sha256"]


def test_perfect_fake_model_metrics_partition_counts_and_no_mutation(dataset, fake_mlx):
    saved = deepcopy(dataset)
    model = FakePairedMemory()
    weights = model.weights.copy()
    result = run(dataset, model=model)
    assert result["logical_model_transitions"] == 82080
    assert result["first_edge_pair_checks"] == 20
    assert result["first_edge_pairs_identical"] is True
    assert len(result["per_query"]) == 2560
    assert len(result["per_world"]) == 20
    for name in GROUPS:
        group = result["groups"][name]
        assert tuple(group["methods"]) == METHODS
        assert group["methods"]["history_tail"]["accuracy"] == 1
        assert group["methods"]["zero_context_tail"]["accuracy"] == 1
        assert group["methods"]["history_tail"]["changed_accuracy"] == 1
        assert group["methods"]["reset_history"]["accuracy"] == 0
        assert group["methods"]["copy_current"]["changed_accuracy"] == 0
        assert group["methods"]["fixed_current_codec"]["changed_accuracy"] == 0
        assert group["paired"]["both_correct"] == group["target_visible_count"]
        assert group["paired"]["prediction_disagreements"] == 0
        assert group["paired"]["history_minus_zero_nll"] == 0
    assert dataset == saved
    np.testing.assert_array_equal(model.weights, weights)
    assert result["protocol"]["weight_updates"] is False
    assert result["protocol"]["other_train_independent_holdout"] is False
    assert result["protocol"]["m2j_local_scores_directly_comparable"] is False
    json.dumps(result, allow_nan=False)


def test_three_keys_inputs_and_actions_are_paired_and_history_is_unmodified(dataset, fake_mlx):
    events = []
    result = run(dataset, model=FakePairedMemory(events=events))
    observes = [row for row in events if row[0] == "observe"]
    imagines = [row for row in events if row[0] == "imagine"]
    assert len(observes) == 20 * (1 + 4 * 128)
    assert len(imagines) == 2 * 2560
    for world in range(20):
        full_observations = [observes[world * 513]]
        for offset in range(128):
            tick = offset + 1
            start = world * 513 + 1 + offset * 4
            full, zero_previous, zero_current, reset_current = observes[start : start + 4]
            previous = full_observations[-1]
            assert previous[1:5] == zero_previous[1:5]
            assert full[1:5] == zero_current[1:5] == reset_current[1:5]
            full_action, zero_action = imagines[
                (world * 128 + offset) * 2 : (world * 128 + offset + 1) * 2
            ]
            assert full_action[1:3] == zero_action[1:3]
            assert full_action[3] == tick - 1
            assert zero_action[3] == 0
            assert full[5] == tick
            assert zero_current[5] == 1
            assert reset_current[5] == 0
            assert result["per_query"][world * 128 + offset]["paired_random_seeds"] == [
                previous[4],
                full_action[2],
                full[4],
            ]
            full_observations.append(full)


def test_each_model_chunk_is_reserved_before_work_and_totals_reconcile(dataset, fake_mlx):
    events = []
    result = run(
        dataset,
        model=FakePairedMemory(events=events),
        before_work=lambda count: events.append(("reserve", count)),
    )
    reservations = [row[1] for row in events if row[0] == "reserve"]
    assert reservations == [8] * (20 + 4 * 2560)
    assert sum(reservations) == 82080
    assert result["initial_observation_encodes"] == 160
    assert result["feedback_model_transitions"] == 20480
    assert result["zero_context_initial_observation_encodes"] == 20480
    assert result["zero_context_feedback_model_transitions"] == 20480
    assert result["reset_observation_encodes"] == 20480
    for index, row in enumerate(events):
        if row[0] in ("initial", "imagine"):
            assert events[index - 1] == ("reserve", 8)


@pytest.mark.parametrize("reject_at", [1, 2, 3, 4, 5, 6, 514])
def test_budget_rejection_precedes_remaining_imports_and_model_calls(
    dataset, fake_mlx, monkeypatch, reject_at
):
    model, imports, reservations = FakePairedMemory(), [], []
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
        run(dataset, model=model, before_work=reserve)
    assert len(model.events) == reservations[-1][1]
    assert len(imports) == reservations[-1][2]


def test_paired_counts_expose_harm_from_history_on_identical_targets(dataset, fake_mlx):
    result = run(dataset, model=FakePairedMemory(history_error=True))
    for group in result["groups"].values():
        paired = group["paired"]
        assert paired["history_only_correct"] == 0
        assert paired["zero_only_correct"] > 0
        assert paired["history_minus_zero_accuracy"] < 0
        assert paired["history_minus_zero_nll"] > 0
        assert paired["count"] == sum(
            paired[name]
            for name in (
                "history_only_correct",
                "zero_only_correct",
                "both_correct",
                "neither_correct",
            )
        )
    fitted = result["groups"]["fitted_train"]
    assert fitted["paired"]["zero_only_correct"] == 128
    assert fitted["paired"]["changed_zero_only_correct"] == 16
    assert sum(row["paired"]["zero_only_correct"] for row in result["per_query"]) == sum(
        row["paired"]["zero_only_correct"] for row in result["per_world"]
    )


def test_particle_probabilities_are_averaged_before_nll(dataset, fake_mlx):
    result = run(dataset, model=FakePairedMemory(mixture=True))
    expected = -np.log(0.5 / 255)  # Labels are all nonzero in the synthetic fixture.
    for group in result["groups"].values():
        assert group["methods"]["history_tail"]["nll"] == pytest.approx(expected)
        assert group["methods"]["zero_context_tail"]["nll"] == pytest.approx(expected)


def test_random_schedule_and_results_do_not_depend_on_input_order(dataset, fake_mlx):
    first = run(dataset)
    second = run({key: list(reversed(value)) for key, value in dataset.items()})
    assert first == second


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.5, "7103", None])
def test_invalid_seeds_rejected_before_work(dataset, seed):
    with pytest.raises(ValueError, match="seed"):
        run(dataset, seed=seed, before_work=lambda _: pytest.fail("must reject before work"))


@pytest.mark.parametrize("particles", [True, 0, 1, 4, 8.0, 16])
def test_particle_count_is_fixed(dataset, particles):
    with pytest.raises(ValueError, match="particles"):
        run(
            dataset,
            particles=particles,
            before_work=lambda _: pytest.fail("must reject before work"),
        )


def test_missing_callback_rejected(dataset):
    with pytest.raises(ValueError, match="before_work"):
        run(dataset, before_work=None)


@pytest.mark.parametrize(
    "partitions", [None, {}, {"train": []}, {"train": [], "development": [], "final": []}, []]
)
def test_partition_mapping_is_exact(partitions):
    with pytest.raises(ValueError, match="partitions"):
        paired_memory_samples(partitions)


@pytest.mark.parametrize("partition,count", [("train", 0), ("train", 15), ("development", 3)])
def test_world_counts_are_exact(dataset, partition, count):
    bad = {key: list(value) for key, value in dataset.items()}
    bad[partition] = bad[partition][:count]
    with pytest.raises(ValueError, match="exactly"):
        paired_memory_samples(bad)


def test_world_length_is_exact(dataset):
    def alter(value):
        value["transitions"].pop()
        value["stop_reason"] = "requested_steps"

    bad = changed_episode(dataset, "train", 0, alter)
    with pytest.raises(ValueError, match="128"):
        paired_memory_samples(bad)


def test_duplicate_worlds_across_partitions_are_rejected(dataset):
    duplicated = str(dataset["train"][0].initial.context.environment_instance_id)

    def alter(value):
        records = [value["initial"]]
        for edge in value["transitions"]:
            records.extend(edge.values())
        for record in records:
            record["context"]["environment_instance_id"] = duplicated

    bad = changed_episode(dataset, "development", 0, alter)
    with pytest.raises(ValueError, match="distinct across"):
        paired_memory_samples(bad)


@pytest.mark.parametrize("partition", ["train", "development"])
@pytest.mark.parametrize("mutation", ["actor", "assistance"])
def test_every_public_edge_requires_authorized_source(dataset, partition, mutation):
    def alter(value):
        for edge in value["transitions"]:
            request = edge["action_request"]
            if mutation == "actor":
                request["actor"]["actor_id"] = "unapproved"
            else:
                request["assistance"] = ["curriculum"]

    bad = changed_episode(dataset, partition, 0, alter)
    with pytest.raises(ValueError, match="authorized random actor|consistent action source"):
        paired_memory_samples(bad)


def test_mislabeled_partition_rejected(dataset):
    bad = {"train": dataset["development"] * 4, "development": dataset["development"]}
    with pytest.raises(ValueError, match="declared partition"):
        paired_memory_samples(bad)


def test_first_edge_mismatch_fails_without_running_remaining_branches(dataset, fake_mlx):
    class BrokenPair(FakePairedMemory):
        def __init__(self):
            super().__init__()
            self.readout_count = 0

        def symbol_readout(self, slots):
            self.readout_count += 1
            value = super().symbol_readout(slots)
            return np.roll(value, 1, axis=-1) if self.readout_count == 3 else value

    reservations = []
    with pytest.raises(ValueError, match="first-edge.*match exactly"):
        run(dataset, model=BrokenPair(), before_work=reservations.append)
    assert reservations == [8] * 4
