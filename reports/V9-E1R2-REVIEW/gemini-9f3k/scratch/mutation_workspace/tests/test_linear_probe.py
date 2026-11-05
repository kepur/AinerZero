from copy import deepcopy

import numpy as np
import pytest

from ainerzero.learning.linear_probe import decode_embeddings, fit_ridge, predict_ridge


def data():
    rng = np.random.default_rng(120)
    features = rng.normal(size=(80, 5))
    weights = rng.normal(size=(8, 5, 16))
    offsets = rng.normal(size=(8, 16))
    targets = np.einsum("nd,pdk->npk", features, weights) + offsets
    return features, targets, np.ones((80, 8), dtype=bool)


def test_affine_recovery_on_distinct_features_and_no_input_mutation():
    features, targets, mask = data()
    originals = [value.copy() for value in (features, targets, mask)]
    probe = fit_ridge(features[:60], targets[:60], mask[:60], ridge=1e-10)
    assert set(probe) == {"feature_mean", "feature_scale", "coefficients", "fit_counts"}
    assert probe["coefficients"].shape == (8, 6, 16)
    np.testing.assert_array_equal(probe["fit_counts"], np.full(8, 60))
    np.testing.assert_allclose(predict_ridge(probe, features[60:]), targets[60:], atol=1e-8)
    for original, current in zip(originals, (features, targets, mask), strict=True):
        np.testing.assert_array_equal(original, current)


def test_predict_uses_only_fitted_training_normalization(monkeypatch):
    features, targets, mask = data()
    probe = fit_ridge(features, targets, mask)
    original = deepcopy(probe)
    np.testing.assert_allclose(probe["feature_mean"], features.mean(axis=0))
    np.testing.assert_allclose(probe["feature_scale"], features.std(axis=0))
    query = np.full((2, 5), 100.0)
    normalized = (query - features.mean(axis=0)) / features.std(axis=0)
    design = np.column_stack((normalized, np.ones(2)))
    expected = np.einsum("nd,pdk->npk", design, probe["coefficients"])

    def fail_fit(*args, **kwargs):
        raise AssertionError("prediction attempted a fit")

    monkeypatch.setattr(np.linalg, "solve", fail_fit)
    np.testing.assert_allclose(predict_ridge(probe, query), expected)
    for name in probe:
        np.testing.assert_array_equal(probe[name], original[name])


def test_mask_excludes_poisoned_hidden_labels_independently_per_position():
    features, targets, mask = data()
    for position in range(8):
        mask[position::3, position] = False
    reference = fit_ridge(features, targets, mask)
    poisoned = targets.copy()
    poisoned[~mask] = 1e100
    actual = fit_ridge(features, poisoned, mask)
    for name in reference:
        np.testing.assert_array_equal(actual[name], reference[name])
    np.testing.assert_array_equal(actual["fit_counts"], mask.sum(axis=0))


def test_ridge_penalty_matches_mean_squared_objective_not_sample_sum():
    features = np.array([[-1.0], [1.0]])
    targets = np.broadcast_to((3 + 2 * features)[:, :, None], (2, 8, 16)).copy()
    mask = np.ones((2, 8), dtype=bool)
    probe = fit_ridge(features, targets, mask, ridge=1.0)
    np.testing.assert_allclose(probe["coefficients"][:, 0], 1.0)
    np.testing.assert_allclose(probe["coefficients"][:, 1], 3.0)
    repeated = fit_ridge(
        np.tile(features, (5, 1)), np.tile(targets, (5, 1, 1)), np.tile(mask, (5, 1)), ridge=1.0
    )
    np.testing.assert_allclose(probe["coefficients"], repeated["coefficients"])


def test_constant_columns_and_single_visible_sample_have_finite_unpenalized_intercept():
    features = np.full((3, 2), 8.0)
    targets = np.full((3, 8, 16), 11.0)
    mask = np.zeros((3, 8), dtype=bool)
    mask[1] = True
    probe = fit_ridge(features, targets, mask, ridge=1e6)
    np.testing.assert_array_equal(probe["feature_scale"], [1.0, 1.0])
    np.testing.assert_array_equal(probe["coefficients"][:, :-1], 0.0)
    np.testing.assert_allclose(predict_ridge(probe, features), targets)


@pytest.mark.parametrize("ridge", [0, -0.1, np.inf, np.nan, True, "0.01", 1j])
def test_invalid_ridge_rejected(ridge):
    with pytest.raises(ValueError, match="ridge"):
        fit_ridge(*data(), ridge=ridge)


@pytest.mark.parametrize(
    "field,value",
    [
        (0, np.zeros((80,))),
        (0, np.zeros((80, 0))),
        (0, np.full((80, 5), np.nan)),
        (0, np.full((80, 5), np.inf)),
        (0, np.zeros((80, 5), dtype=complex)),
        (0, np.full((80, 5), "x")),
        (1, np.zeros((80, 8, 15))),
        (1, np.full((80, 8, 16), np.nan)),
        (2, np.ones((80, 8), dtype=int)),
        (2, np.ones((80, 7), dtype=bool)),
    ],
)
def test_invalid_fit_arrays_rejected(field, value):
    values = list(data())
    values[field] = value
    with pytest.raises(ValueError):
        fit_ridge(*values)


def test_empty_training_or_unobserved_position_rejected():
    features, targets, mask = data()
    with pytest.raises(ValueError, match="N > 0"):
        fit_ridge(features[:0], targets[:0], mask[:0])
    mask[:, 3] = False
    with pytest.raises(ValueError, match="every position"):
        fit_ridge(features, targets, mask)


@pytest.mark.parametrize(
    "field,value",
    [
        ("feature_mean", np.zeros(6)),
        ("feature_scale", np.zeros(5)),
        ("feature_scale", np.full(5, np.nan)),
        ("coefficients", np.zeros((8, 5, 16))),
        ("coefficients", np.full((8, 6, 16), np.inf)),
        ("fit_counts", np.ones(8, dtype=float)),
        ("fit_counts", np.zeros(8, dtype=int)),
    ],
)
def test_invalid_fitted_probe_rejected(field, value):
    features, targets, mask = data()
    probe = fit_ridge(features, targets, mask)
    probe[field] = value
    with pytest.raises(ValueError):
        predict_ridge(probe, features)


def test_prediction_requires_complete_probe_and_matching_finite_features():
    features, targets, mask = data()
    probe = fit_ridge(features, targets, mask)
    for malformed in (None, {}):
        with pytest.raises(ValueError):
            predict_ridge(malformed, features)
    for query in (np.zeros((2, 4)), np.full((2, 5), np.nan)):
        with pytest.raises(ValueError):
            predict_ridge(probe, query)
    assert predict_ridge(probe, features[:0]).shape == (0, 8, 16)


def test_decoder_uses_frozen_linear_head_with_known_probabilities():
    embeddings = np.zeros((2, 8, 16))
    embeddings[..., 0] = 2.0
    weight = np.zeros((256, 16))
    weight[42, 0] = np.log(2)
    bias = np.zeros(256)
    bias[42] = np.log(3)
    probabilities = decode_embeddings(embeddings, weight, bias)
    expected = np.full((2, 8, 256), 1 / 267)
    expected[..., 42] = 12 / 267
    np.testing.assert_allclose(probabilities, expected, atol=1e-15)
    np.testing.assert_allclose(probabilities.sum(axis=-1), 1.0)
    assert probabilities.dtype == np.float64


def test_decoder_extreme_finite_logits_stay_positive_normalized():
    embeddings = np.zeros((1, 8, 16))
    weight = np.zeros((256, 16))
    bias = np.full(256, -1e308)
    bias[2] = 1e308
    probabilities = decode_embeddings(embeddings, weight, bias)
    assert np.isfinite(probabilities).all()
    assert (probabilities > 0).all()
    np.testing.assert_allclose(probabilities.sum(axis=-1), 1.0)
    np.testing.assert_array_equal(probabilities.argmax(axis=-1), 2)
    assert decode_embeddings(embeddings[:0], weight, bias).shape == (0, 8, 256)


@pytest.mark.parametrize(
    "field,value",
    [
        (0, np.zeros((1, 7, 16))),
        (0, np.full((1, 8, 16), np.inf)),
        (1, np.zeros((16, 256))),
        (1, np.full((256, 16), np.nan)),
        (2, np.zeros((256, 1))),
        (2, np.full(256, np.inf)),
    ],
)
def test_decoder_invalid_arrays_rejected(field, value):
    values = [np.zeros((1, 8, 16)), np.zeros((256, 16)), np.zeros(256)]
    values[field] = value
    with pytest.raises(ValueError):
        decode_embeddings(*values)
