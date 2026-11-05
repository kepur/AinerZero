from copy import deepcopy

import numpy as np
import pytest

from ainerzero.learning import residual_probe
from ainerzero.learning.recall_probe import FEATURE_KINDS, make_probe_rows
from ainerzero.learning.residual_probe import (
    fit_residual_rows,
    fit_zero_delay_dense,
    make_residual_rows,
    score_residual_rows,
    score_zero_delay_controls,
)


def codec():
    embedding = np.zeros((256, 16), dtype=np.float64)
    embedding[:16] = np.eye(16)
    return embedding, 10 * embedding, np.zeros(256)


def rows(*, partition="train", delay=1):
    current = np.tile(np.arange(8, dtype=np.int32), (4, 1))
    mask = np.ones((4, 8), dtype=np.bool_)
    current_mask = mask.copy()
    current_mask[2, 3] = False
    targets = current.copy()
    if delay:
        targets[0, 0] = 8
        targets[1, 2] = 9
        targets[2, 3] = 10
        mask[3, 4] = False
    else:
        mask = current_mask.copy()
    return {
        "partition": partition,
        "delay": delay,
        "minimum_tick": 4,
        "features": {
            kind: np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]) + offset
            for offset, kind in enumerate(FEATURE_KINDS)
        },
        "targets": targets,
        "target_mask": mask,
        "current_symbols": current,
        "current_mask": current_mask,
        "world": np.array([0, 0, 1, 1], dtype=np.int32),
        "ticks": np.array([4, 5, 4, 5], dtype=np.int32),
    }


def constant_probe(value=0.0):
    coefficients = np.zeros((8, 3, 16), dtype=np.float64)
    coefficients[:, -1, :] = value
    return {
        "feature_mean": np.zeros(2),
        "feature_scale": np.ones(2),
        "coefficients": coefficients,
        "fit_counts": np.full(8, 4, dtype=np.int64),
    }


def collection():
    sequences = []
    for world in range(2):
        symbols = np.arange(6 * 8, dtype=np.int32).reshape(6, 8) + 50 * world
        visible = np.ones((6, 8), dtype=np.bool_)
        visible[4, 2] = False
        sequences.append(
            {
                "symbols": symbols,
                "visible_mask": visible,
                "features": {
                    kind: np.arange(12, dtype=np.float64).reshape(6, 2) + 50 * world
                    for kind in FEATURE_KINDS
                },
            }
        )
    return {"partition": "train", "sequences": sequences}


@pytest.mark.parametrize("delay", [0, 1, 2, 4])
def test_residual_rows_pair_public_same_episode_targets_including_zero(delay):
    source = collection()
    result = make_residual_rows(source, delay=delay, minimum_tick=4)
    np.testing.assert_array_equal(result["world"], [0, 0, 1, 1])
    np.testing.assert_array_equal(result["ticks"], [4, 5, 4, 5])
    for world, sequence in enumerate(source["sequences"]):
        block = slice(2 * world, 2 * world + 2)
        np.testing.assert_array_equal(
            result["targets"][block], sequence["symbols"][[4 - delay, 5 - delay]]
        )
        np.testing.assert_array_equal(result["current_symbols"][block], sequence["symbols"][[4, 5]])
        np.testing.assert_array_equal(
            result["target_mask"][block], sequence["visible_mask"][[4 - delay, 5 - delay]]
        )
        for kind in FEATURE_KINDS:
            np.testing.assert_array_equal(
                result["features"][kind][block], sequence["features"][kind][[4, 5]]
            )


def test_original_probe_interface_still_requires_explicit_zero_delay_opt_in():
    source = collection()
    with pytest.raises(ValueError, match="zero requires explicit opt-in"):
        make_probe_rows(source, delay=0, minimum_tick=4)
    opted = make_probe_rows(source, delay=0, minimum_tick=4, allow_zero_delay=True)
    residual = make_residual_rows(source, delay=0, minimum_tick=4)
    np.testing.assert_array_equal(opted["targets"], residual["targets"])
    np.testing.assert_array_equal(residual["targets"], residual["current_symbols"])
    np.testing.assert_array_equal(residual["target_mask"], residual["current_mask"])


@pytest.mark.parametrize("delay", [1, 2, 4])
def test_nonzero_rows_preserve_original_interface(delay):
    source = collection()
    previous = make_probe_rows(source, delay=delay, minimum_tick=4)
    current = make_residual_rows(source, delay=delay, minimum_tick=4)
    assert previous.keys() == current.keys()
    for key in previous:
        if key == "features":
            for kind in FEATURE_KINDS:
                np.testing.assert_array_equal(previous[key][kind], current[key][kind])
        else:
            np.testing.assert_array_equal(previous[key], current[key])


@pytest.mark.parametrize("allow", [1, "yes", None])
def test_zero_opt_in_requires_actual_boolean(allow):
    with pytest.raises(ValueError):
        make_probe_rows(collection(), delay=0, minimum_tick=4, allow_zero_delay=allow)


def test_fit_residual_uses_past_minus_masked_current_and_visible_past_targets(monkeypatch):
    source = rows()
    embedding, _, _ = codec()
    calls = []

    def fit(features, labels, mask, *, ridge):
        calls.append((features, labels.copy(), mask.copy(), ridge))
        return constant_probe()

    monkeypatch.setattr(residual_probe, "fit_ridge", fit)
    result = fit_residual_rows(source, embedding)
    assert set(result) == set(FEATURE_KINDS)
    assert len(calls) == 3
    for kind, (features, labels, mask, ridge) in zip(FEATURE_KINDS, calls, strict=True):
        assert features is source["features"][kind]
        assert ridge == 0.01
        np.testing.assert_array_equal(mask, source["target_mask"])
        np.testing.assert_array_equal(labels[0, 0], embedding[8] - embedding[0])
        np.testing.assert_array_equal(labels[1, 2], embedding[9] - embedding[2])
        # A currently hidden symbol contributes zero, although the past target is visible.
        np.testing.assert_array_equal(labels[2, 3], embedding[10])
        np.testing.assert_array_equal(labels[0, 1], np.zeros(16))


@pytest.mark.parametrize("fit", [fit_residual_rows, fit_zero_delay_dense])
@pytest.mark.parametrize("partition", ["development", "final", "quarantine", None])
def test_no_nontraining_partition_can_fit_either_readout(fit, partition, monkeypatch):
    monkeypatch.setattr(
        residual_probe, "fit_ridge", lambda *args, **kwargs: pytest.fail("fit dispatched")
    )
    with pytest.raises(ValueError, match="only train"):
        fit(rows(partition=partition, delay=0), codec()[0])


def test_dense_zero_control_fits_absolute_current_embeddings_once(monkeypatch):
    source = rows(delay=0)
    embedding, _, _ = codec()
    calls = []

    def fit(features, targets, mask, *, ridge):
        calls.append((features, targets, mask, ridge))
        return constant_probe()

    monkeypatch.setattr(residual_probe, "fit_ridge", fit)
    fit_zero_delay_dense(source, embedding)
    assert len(calls) == 1
    features, targets, mask, ridge = calls[0]
    assert features is source["features"]["current_only"]
    assert ridge == 0.01
    np.testing.assert_array_equal(targets, embedding[source["current_symbols"]])
    np.testing.assert_array_equal(mask, source["current_mask"])


@pytest.mark.parametrize("delay", [1, 2, 4, True, 0.0])
def test_dense_control_cannot_fit_nonzero_or_invalid_delay(delay):
    with pytest.raises(ValueError, match="requires delay 0"):
        fit_zero_delay_dense(rows(delay=delay), codec()[0])


@pytest.mark.parametrize("fault", ["mask", "visible_label"])
def test_zero_control_rejects_mismatched_current_labels(fault):
    source = rows(delay=0)
    if fault == "mask":
        source["target_mask"][0, 0] = False
    else:
        source["targets"][0, 0] = 10
    embedding, weight, bias = codec()
    with pytest.raises(ValueError, match="labels must equal"):
        fit_zero_delay_dense(source, embedding)
    with pytest.raises(ValueError, match="labels must equal"):
        score_zero_delay_controls(constant_probe(), source, embedding, weight, bias)


def test_predictions_add_residual_uniformly_and_never_route_using_true_change_labels(monkeypatch):
    source = rows(partition="development")
    embedding, weight, bias = codec()
    probes = {kind: constant_probe(0.02) for kind in FEATURE_KINDS}
    original = deepcopy(probes)
    captured = []
    actual_decode = residual_probe.decode_embeddings

    def capture(values, weight, bias):
        captured.append(values.copy())
        return actual_decode(values, weight, bias)

    monkeypatch.setattr(residual_probe, "decode_embeddings", capture)
    score_residual_rows(probes, source, embedding, weight, bias)
    original_predictions = captured.copy()
    altered = deepcopy(source)
    altered["targets"] = (altered["targets"] + 4) % 16
    captured.clear()
    score_residual_rows(probes, altered, embedding, weight, bias)
    assert len(captured) == len(original_predictions) == 5
    base = embedding[source["current_symbols"]] * source["current_mask"][..., None]
    for index in range(3):
        np.testing.assert_allclose(original_predictions[index], base + 0.02)
        np.testing.assert_array_equal(captured[index], original_predictions[index])
    np.testing.assert_array_equal(captured[3], base)
    np.testing.assert_array_equal(original_predictions[3][2, 3], np.zeros(16))
    # Only the explicitly named target-codec oracle is allowed to depend on labels.
    assert not np.array_equal(captured[4], original_predictions[4])
    for kind in FEATURE_KINDS:
        for key in probes[kind]:
            np.testing.assert_array_equal(probes[kind][key], original[kind][key])


def test_zero_pipeline_uses_no_fit_and_preserves_fixed_codec_probabilities(monkeypatch):
    source = rows(partition="development", delay=0)
    embedding, weight, bias = codec()
    monkeypatch.setattr(
        residual_probe, "fit_ridge", lambda *args, **kwargs: pytest.fail("unexpected fit")
    )
    result = score_zero_delay_controls(constant_probe(), source, embedding, weight, bias)
    assert all(value is True for value in result["pipeline_checks"].values())
    assert result["methods"]["zero_residual_codec"] == result["methods"]["fixed_current_codec"]
    assert result["methods"]["fixed_current_codec"]["accuracy"] == 1
    assert result["methods"]["dense_current_only"]["accuracy"] < 1
    assert "not_memory" in result["interpretation"]


def test_zero_pipeline_does_not_require_hidden_target_identity():
    source = rows(partition="development", delay=0)
    source["targets"][2, 3] = 15
    result = score_zero_delay_controls(constant_probe(), source, *codec())
    assert result["pipeline_checks"]["zero_residual_preserves_embedding"] is True
    assert result["methods"]["fixed_current_codec"]["accuracy"] == 1


def test_zero_pipeline_without_visible_labels_is_not_a_success():
    source = rows(partition="development", delay=0)
    source["current_mask"][:] = False
    source["target_mask"][:] = False
    result = score_zero_delay_controls(constant_probe(), source, *codec())
    assert result["pipeline_checks"]["visible_targets_present"] is False
    assert result["methods"]["zero_residual_codec"]["count"] == 0
    assert result["methods"]["zero_residual_codec"]["accuracy"] is None


def test_residual_metrics_preserve_per_world_and_mutual_visibility_counts():
    source = rows(partition="development")
    probes = {kind: constant_probe() for kind in FEATURE_KINDS}
    result = score_residual_rows(probes, source, *codec())
    assert (result["frame_count"], result["world_count"]) == (4, 2)
    assert set(result["methods"]) == {
        *FEATURE_KINDS,
        "fixed_current_codec",
        "target_codec_oracle",
        "copy_current",
    }
    for metric in result["methods"].values():
        assert metric["count"] == 31
        assert metric["changed_count"] == 2
        assert metric["unchanged_count"] == 28
        first, second = metric["per_world"]
        assert (first["world_index"], first["count"], first["changed_count"]) == (0, 16, 2)
        assert (second["world_index"], second["count"], second["changed_count"]) == (1, 15, 0)
        assert second["changed_nll"] is None
    for kind in FEATURE_KINDS:
        assert result["methods"][kind] == result["methods"]["fixed_current_codec"]
    assert result["methods"]["target_codec_oracle"]["embedding_mse"] == 0
    assert result["methods"]["target_codec_oracle"]["accuracy"] == 1


def test_small_real_ridge_fit_and_scores_keep_student_inputs_immutable():
    source = rows()
    embedding, weight, bias = codec()
    originals = [array.copy() for array in (embedding, weight, bias)]
    probes = fit_residual_rows(source, embedding)
    assert set(probes) == set(FEATURE_KINDS)
    assert all(probe["coefficients"].shape == (8, 3, 16) for probe in probes.values())
    result = score_residual_rows(probes, source, embedding, weight, bias)
    assert all(np.isfinite(result["methods"][kind]["nll"]) for kind in FEATURE_KINDS)
    dense = fit_zero_delay_dense(rows(delay=0), embedding)
    control = score_zero_delay_controls(dense, rows(delay=0), embedding, weight, bias)
    assert all(value is True for value in control["pipeline_checks"].values())
    for actual, original in zip((embedding, weight, bias), originals, strict=True):
        np.testing.assert_array_equal(actual, original)
