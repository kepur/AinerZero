import builtins
from copy import deepcopy
from uuid import uuid4

import mlx.core as mx
import numpy as np
import pytest
from test_pilot_evaluation import episode, payloads_for

from ainerzero.core.experience import DatasetPartition
from ainerzero.learning import recall_probe
from ainerzero.learning.linear_probe import predict_ridge
from ainerzero.learning.recall_probe import (
    FEATURE_KINDS,
    FEATURE_WIDTH,
    PARTICLES,
    collect_probe_features,
    feature_summary,
    fit_probe_rows,
    make_probe_rows,
    score_probe_rows,
)

pytestmark = pytest.mark.native_mlx(reason="module-level real MLX import (A39)")


@pytest.fixture(autouse=True)
def cpu_stream():
    with mx.stream(mx.cpu):
        yield


class FakeMemory:
    """Causal CPU state with inspectable inputs, particles and immutable weights."""

    def __init__(self, events=None):
        self.events = events if events is not None else []
        self.weight = np.array([2.0])

    def initial(self, count):
        self.events.append(("initial", count))
        return mx.zeros((count, 256)), mx.zeros((count, 16))

    def observe(self, h, symbols, visible_mask, cursor, *, key):
        self.events.append(
            (
                "observe",
                {
                    name: np.asarray(value).copy()
                    for name, value in (
                        ("h", h),
                        ("symbols", symbols),
                        ("mask", visible_mask),
                        ("cursor", cursor),
                        ("key", key),
                    )
                },
            )
        )
        sensory = mx.sum(mx.where(visible_mask, symbols, 0), axis=-1).astype(mx.float32)
        updated = h + sensory[:, None] + cursor[:, None]
        z = mx.random.normal((len(symbols), 16), key=key) + updated[:, :16]
        return {"h": updated, "z": z}

    def imagine(self, h, z, actions, *, key):
        self.events.append(("imagine", np.asarray(actions).copy(), np.asarray(key).copy()))
        return {"h": h + actions[:, None] + 1, "z": z}


def embedding_table():
    return np.arange(256 * 16, dtype=np.float64).reshape(256, 16) / 100


def collect(data=None, model=None, **kwargs):
    return collect_probe_features(
        model or FakeMemory(),
        data if data is not None else [episode()],
        embedding_table(),
        partition=kwargs.pop("partition", "development"),
        seed=kwargs.pop("seed", 701),
        before_work=kwargs.pop("before_work", lambda _: None),
        **kwargs,
    )


def with_context(source, **updates):
    value = source.model_dump()
    value["initial"]["context"].update(updates)
    for transition in value["transitions"]:
        for record in transition.values():
            record["context"].update(updates)
    return value


def test_collection_is_causal_and_future_changes_cannot_rewrite_prefix_features():
    source = episode(steps=6)
    payloads = payloads_for(source)
    revised = [
        item if tick < 4 else item.model_copy(update={"symbols": (255,) * 8})
        for tick, item in enumerate(payloads)
    ]
    normal = collect([source])["sequences"][0]
    changed = collect([episode(steps=6, payloads=revised)])["sequences"][0]
    for kind in FEATURE_KINDS:
        np.testing.assert_array_equal(normal["features"][kind][:4], changed["features"][kind][:4])
        assert not np.array_equal(normal["features"][kind][4:], changed["features"][kind][4:])


def test_full_and_reset_share_observation_keys_and_current_only_has_no_history():
    source = episode(steps=3)
    payloads = payloads_for(source)
    payloads[2] = payloads[2].model_copy(
        update={
            "symbols": (0,) + tuple(range(1, 8)),
            "visible_mask": (False,) + (True,) * 7,
            "cursor": 5,
        }
    )
    source = episode(steps=3, payloads=payloads)
    model = FakeMemory()
    weight = model.weight.copy()
    result = collect([source], model)
    features = result["sequences"][0]["features"]
    observes = [event[1] for event in model.events if event[0] == "observe"]
    assert len(observes) == 8
    for tick, observation in enumerate(payloads):
        full, reset = observes[2 * tick : 2 * tick + 2]
        np.testing.assert_array_equal(full["key"], reset["key"])
        np.testing.assert_array_equal(reset["h"], 0)
        for name in ("symbols", "mask", "cursor"):
            np.testing.assert_array_equal(full[name], reset[name])
        np.testing.assert_array_equal(full["symbols"], [observation.symbols] * PARTICLES)
        visible = np.asarray(observation.visible_mask)
        expected = np.concatenate(
            (
                (embedding_table()[np.asarray(observation.symbols)] * visible[:, None]).ravel(),
                visible,
                np.eye(8)[observation.cursor],
                np.zeros(FEATURE_WIDTH - 144),
            )
        )
        np.testing.assert_array_equal(features["current_only"][tick], expected)
    np.testing.assert_array_equal(features["full_state"][0], features["reset_state"][0])
    assert not np.array_equal(features["full_state"][1:], features["reset_state"][1:])
    np.testing.assert_array_equal(features["current_only"][2, :16], 0)
    np.testing.assert_array_equal(model.weight, weight)


def test_particle_state_features_are_means_not_first_particle():
    class ParticleMemory(FakeMemory):
        def observe(self, h, symbols, visible_mask, cursor, *, key):
            positions = mx.arange(PARTICLES)[:, None].astype(mx.float32)
            return {
                "h": mx.broadcast_to(positions, (PARTICLES, 256)),
                "z": mx.broadcast_to(2 * positions, (PARTICLES, 16)),
            }

    values = collect([episode(steps=0)], ParticleMemory())["sequences"][0]["features"]
    for kind in ("full_state", "reset_state"):
        np.testing.assert_array_equal(values[kind][0, :256], 3.5)
        np.testing.assert_array_equal(values[kind][0, 256:], 7)


def test_collection_reserves_every_full_edge_and_reset_before_dispatch():
    events = []
    source = episode(steps=3)
    result = collect(
        [source], FakeMemory(events), before_work=lambda n: events.append(("reserve", n))
    )
    assert result["logical_model_units"] == 16 * 4
    reserves = [event[1] for event in events if event[0] == "reserve"]
    assert reserves == [PARTICLES] * 8
    expected = ["reserve", "initial", "observe", "reserve", "initial", "observe"]
    expected += ["reserve", "imagine", "observe", "reserve", "initial", "observe"] * 3
    assert [event[0] for event in events] == expected


@pytest.mark.parametrize("rejected_reservation", [0, 1, 2, 3, 5])
def test_budget_rejection_stops_all_later_dispatch_and_lazy_materialization(
    monkeypatch, rejected_reservation
):
    events, calls = [], 0
    original_eval = mx.eval

    def tracked_eval(*args, **kwargs):
        events.append(("eval",))
        return original_eval(*args, **kwargs)

    def reserve(units):
        nonlocal calls
        if calls == rejected_reservation:
            events.append(("rejected", units))
            raise RuntimeError("budget exhausted")
        calls += 1
        events.append(("reserve", units))

    monkeypatch.setattr(mx, "eval", tracked_eval)
    with pytest.raises(RuntimeError, match="budget exhausted"):
        collect([episode(steps=3)], FakeMemory(events), before_work=reserve)
    assert events[-1] == ("rejected", PARTICLES)
    assert calls == rejected_reservation
    if rejected_reservation == 0:
        assert events == [("rejected", PARTICLES)]
    # Only completed full/reset pairs may be explicitly evaluated.
    assert sum(event[0] == "eval" for event in events) == 2 * (rejected_reservation // 2)


def test_first_budget_rejection_precedes_mlx_import_or_tensor_construction(monkeypatch):
    original_import = builtins.__import__
    model = FakeMemory()

    def reject_import(name, *args, **kwargs):
        if name.startswith("mlx"):
            raise AssertionError("runtime import preceded budget reservation")
        return original_import(name, *args, **kwargs)

    def reject(*args, **kwargs):
        raise RuntimeError("no budget")

    monkeypatch.setattr(builtins, "__import__", reject_import)
    for name in ("array", "full", "eval"):
        monkeypatch.setattr(
            mx, name, lambda *args, **kwargs: pytest.fail("tensor dispatch before budget")
        )
    with pytest.raises(RuntimeError, match="no budget"):
        collect([episode(steps=0)], model, before_work=reject)
    assert model.events == []


@pytest.mark.parametrize("partition", ["final", "quarantine", "unknown"])
def test_invalid_requested_partition_rejected_before_model_work(partition):
    model = FakeMemory()
    with pytest.raises(ValueError, match="partition"):
        collect(model=model, partition=partition)
    assert model.events == []


@pytest.mark.parametrize(
    "invalid", ["partition", "duplicate_episode", "duplicate_world", "imagined"]
)
def test_collection_validates_all_episodes_and_provenance_before_dispatch(invalid):
    first, second = episode(steps=1), episode(steps=1, seed=10)
    if invalid == "partition":
        second = with_context(second, partition=DatasetPartition.TRAIN)
    elif invalid == "duplicate_episode":
        second = with_context(second, episode_id=first.initial.context.episode_id)
    elif invalid == "duplicate_world":
        second = with_context(
            second, environment_instance_id=first.initial.context.environment_instance_id
        )
    else:
        second = second.model_dump()
        second["transitions"][0]["next_observation"]["origin"] = "imagined"
    model, reservations = FakeMemory(), []
    with pytest.raises(ValueError):
        collect([first, second], model, before_work=reservations.append)
    assert model.events == reservations == []


@pytest.mark.parametrize("seed", [True, -1, 2**32, 1.5])
def test_invalid_seed_rejected(seed):
    with pytest.raises(ValueError, match="seed"):
        collect(seed=seed)


@pytest.mark.parametrize("fault", ["shape", "nonfinite"])
def test_malformed_model_states_rejected(fault):
    class BadMemory(FakeMemory):
        def observe(self, h, symbols, visible_mask, cursor, *, key):
            return {
                "h": mx.zeros((8, 255)) if fault == "shape" else mx.full((8, 256), float("nan")),
                "z": mx.zeros((8, 16)),
            }

    with pytest.raises(ValueError, match="requires|non-finite"):
        collect([episode(steps=0)], BadMemory())


def synthetic_collection():
    sequences = []
    for world, count in enumerate((7, 6)):
        symbols = np.tile(np.arange(count, dtype=np.int32)[:, None] + 20 * world, (1, 8))
        masks = np.ones((count, 8), dtype=bool)
        masks[2, 0] = False
        features = np.tile((np.arange(count) + 100 * world)[:, None], (1, FEATURE_WIDTH))
        sequences.append(
            {
                "episode_id": str(uuid4()),
                "symbols": symbols,
                "visible_mask": masks,
                "ticks": np.arange(count),
                "features": {kind: features.copy() for kind in FEATURE_KINDS},
            }
        )
    return {"partition": "development", "sequences": sequences}


@pytest.mark.parametrize("delay", [1, 2, 4])
def test_probe_rows_use_t_minus_delay_and_never_cross_episode_boundaries(delay):
    collection = synthetic_collection()
    original = deepcopy(collection)
    rows = make_probe_rows(collection, delay=delay, minimum_tick=4)
    np.testing.assert_array_equal(rows["ticks"], [4, 5, 6, 4, 5])
    np.testing.assert_array_equal(rows["world"], [0, 0, 0, 1, 1])
    for index, (world, tick) in enumerate(zip(rows["world"], rows["ticks"], strict=True)):
        seq = collection["sequences"][world]
        np.testing.assert_array_equal(rows["targets"][index], seq["symbols"][tick - delay])
        np.testing.assert_array_equal(rows["target_mask"][index], seq["visible_mask"][tick - delay])
        np.testing.assert_array_equal(rows["current_symbols"][index], seq["symbols"][tick])
        for kind in FEATURE_KINDS:
            np.testing.assert_array_equal(
                rows["features"][kind][index], seq["features"][kind][tick]
            )
    for source, unchanged in zip(collection["sequences"], original["sequences"], strict=True):
        np.testing.assert_array_equal(source["symbols"], unchanged["symbols"])
    assert (rows["delay"], rows["minimum_tick"], rows["partition"]) == (delay, 4, "development")


@pytest.mark.parametrize(
    "delay,minimum_tick", [(0, 4), (3, 4), (True, 4), (4, 3), (1, 1.5), (1, True)]
)
def test_invalid_probe_row_offsets_rejected(delay, minimum_tick):
    with pytest.raises(ValueError):
        make_probe_rows(synthetic_collection(), delay=delay, minimum_tick=minimum_tick)


def test_probe_rows_require_at_least_one_complete_history():
    with pytest.raises(ValueError, match="no complete"):
        make_probe_rows(synthetic_collection(), delay=4, minimum_tick=7)


def test_development_rows_cannot_fit_probe_or_even_access_embedding_labels(monkeypatch):
    class UnavailableEmbedding:
        def __getitem__(self, key):
            pytest.fail("development labels reached probe fitting")

    def forbidden_fit(*args, **kwargs):
        pytest.fail("development partition reached ridge fitting")

    monkeypatch.setattr(recall_probe, "fit_ridge", forbidden_fit)
    rows = make_probe_rows(synthetic_collection(), delay=1, minimum_tick=4)
    with pytest.raises(ValueError, match="only train"):
        fit_probe_rows(rows, UnavailableEmbedding())


def test_train_rows_fit_all_three_external_probes_against_frozen_embedding_labels():
    sample = np.arange(1, 7, dtype=np.float64)
    targets = sample.astype(np.int32)[:, None] + np.arange(8)[None, :]
    mask = np.ones((6, 8), dtype=bool)
    mask[0, 3] = False
    embedding = np.arange(256)[:, None] * np.linspace(0.1, 1.6, 16)[None, :] + 3.0
    features = {
        kind: np.column_stack((sample * scale + offset, np.full(6, 2.0)))
        for kind, scale, offset in zip(FEATURE_KINDS, (1, 2, -1), (0, -2, 4), strict=True)
    }
    rows = {"partition": "train", "features": features, "targets": targets, "target_mask": mask}
    expected = embedding[targets].copy()
    originals = [value.copy() for value in (embedding, targets, mask, *features.values())]
    for value in (embedding, targets, mask, *features.values()):
        value.flags.writeable = False
    probes = fit_probe_rows(rows, embedding, ridge=1e-10)
    assert set(probes) == set(FEATURE_KINDS)
    for kind in FEATURE_KINDS:
        assert probes[kind]["coefficients"].shape == (8, 3, 16)
        np.testing.assert_array_equal(probes[kind]["fit_counts"], mask.sum(axis=0))
        np.testing.assert_allclose(predict_ridge(probes[kind], features[kind]), expected, atol=1e-8)
    for original, current in zip(
        originals, (embedding, targets, mask, *features.values()), strict=True
    ):
        np.testing.assert_array_equal(original, current)
        assert not current.flags.writeable


def scoring_fixture():
    embedding = np.zeros((256, 16))
    embedding[:16] = np.eye(16)
    weight = embedding * 12
    bias = np.zeros(256)
    targets = np.array([[0] * 8, [1] * 8], dtype=np.int32)
    current = targets.copy()
    current[0, 0] = 1
    current[1, :2] = 2
    target_mask, current_mask = np.ones((2, 8), dtype=bool), np.ones((2, 8), dtype=bool)
    target_mask[1, 0] = False
    current_mask[1, 1] = False
    rows = {
        "features": {kind: np.zeros((2, FEATURE_WIDTH)) for kind in FEATURE_KINDS},
        "targets": targets,
        "target_mask": target_mask,
        "current_symbols": current,
        "current_mask": current_mask,
        "world": np.array([0, 1]),
        "ticks": np.array([4, 4]),
        "delay": 4,
        "minimum_tick": 4,
        "partition": "development",
    }
    coefficients = np.zeros((8, FEATURE_WIDTH + 1, 16))
    coefficients[:, -1] = embedding[0]
    probe = {
        "feature_mean": np.zeros(FEATURE_WIDTH),
        "feature_scale": np.ones(FEATURE_WIDTH),
        "coefficients": coefficients,
        "fit_counts": np.ones(8, dtype=np.int64),
    }
    return {kind: deepcopy(probe) for kind in FEATURE_KINDS}, rows, embedding, weight, bias


def test_scores_separate_worlds_oracle_copy_and_mask_changed_cells():
    probes, rows, embedding, weight, bias = scoring_fixture()
    result = score_probe_rows(probes, rows, embedding, weight, bias)
    assert result["frame_count"] == result["world_count"] == 2
    assert result["interpretation"] == "external_probe_performance_not_student_recall_capability"
    assert set(result["methods"]) == {*FEATURE_KINDS, "target_codec_oracle", "copy_current"}
    for name, metric in result["methods"].items():
        assert metric["count"] == 15
        assert metric["changed_count"] == 1
        assert metric["unchanged_count"] == 13
        assert [item["count"] for item in metric["per_world"]] == [8, 7]
        assert [item["changed_count"] for item in metric["per_world"]] == [1, 0]
        assert metric["per_world"][1]["changed_accuracy"] is None
        assert metric["nll"] == pytest.approx(
            sum(item["nll"] * item["count"] for item in metric["per_world"]) / 15
        )
        if name != "copy_current":
            assert metric["per_world"][1]["changed_embedding_mse"] is None
    oracle = result["methods"]["target_codec_oracle"]
    assert oracle["accuracy"] == oracle["changed_accuracy"] == 1.0
    assert oracle["embedding_mse"] == oracle["changed_embedding_mse"] == 0.0
    assert result["methods"]["copy_current"]["changed_accuracy"] == 0.0
    for kind in FEATURE_KINDS:
        assert result["methods"][kind]["accuracy"] == pytest.approx(8 / 15)
        assert result["methods"][kind]["changed_accuracy"] == 1.0


def test_hidden_past_targets_do_not_contribute_to_any_score():
    probes, rows, embedding, weight, bias = scoring_fixture()
    rows["target_mask"][:] = False
    metrics = score_probe_rows(probes, rows, embedding, weight, bias)["methods"]
    for name, value in metrics.items():
        assert value["count"] == value["changed_count"] == value["unchanged_count"] == 0
        assert value["accuracy"] is value["nll"] is value["changed_nll"] is None
        if name != "copy_current":
            assert value["embedding_mse"] is value["changed_embedding_mse"] is None


def test_feature_summary_distinguishes_nominal_columns_from_observed_rank():
    values = np.array([[1, 1, 0, 5], [2, 2, 1, 5], [3, 3, 0, 5]], dtype=np.float64)
    result = feature_summary(values)
    assert result["rows"] == 3
    assert result["columns"] == 4
    assert result["near_constant_columns"] == 1
    assert result["centered_numerical_rank"] == 2
