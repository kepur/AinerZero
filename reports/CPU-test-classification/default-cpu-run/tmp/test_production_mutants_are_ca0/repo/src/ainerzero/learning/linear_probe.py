"""Small, diagnostic linear readouts; these never update a world model.

The caller must split training and evaluation trajectories before fitting. All
normalization statistics belong to the training features supplied to ``fit_ridge``.
"""

from collections.abc import Mapping
from numbers import Real

import numpy as np


def _finite_array(value, name: str) -> np.ndarray:
    array = np.asarray(value)
    if array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain real numeric values")
    array = array.astype(np.float64, copy=False)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite")
    return array


def _features(value, *, nonempty: bool = False) -> np.ndarray:
    features = _finite_array(value, "features")
    if features.ndim != 2 or features.shape[1] == 0:
        raise ValueError("features must have shape [N, D] with D > 0")
    if nonempty and features.shape[0] == 0:
        raise ValueError("training features must have N > 0")
    return features


def _standardize(features, mean, scale):
    with np.errstate(over="ignore", invalid="ignore"):
        standardized = (features - mean) / scale
    if not np.isfinite(standardized).all():
        raise ValueError("standardized features must be finite")
    return np.column_stack((standardized, np.ones(features.shape[0])))


def fit_ridge(features, targets, mask, *, ridge=0.01) -> dict[str, np.ndarray]:
    """Fit one affine 16-dimensional embedding readout per visible position.

    Each position minimizes ``mean(sum((prediction - target)**2, axis=-1))``
    plus ``ridge * sum(coefficients[:-1]**2)``. The last row is the unpenalized
    intercept. Masked target rows never enter that position's normal equations.
    """
    if isinstance(ridge, bool) or not isinstance(ridge, Real):
        raise ValueError("ridge must be a positive finite number")
    if not np.isfinite(ridge) or ridge <= 0:
        raise ValueError("ridge must be a positive finite number")
    features = _features(features, nonempty=True)
    targets = _finite_array(targets, "targets")
    if targets.shape != (features.shape[0], 8, 16):
        raise ValueError("targets must have shape [N, 8, 16]")
    mask = np.asarray(mask)
    if mask.dtype != np.bool_ or mask.shape != (features.shape[0], 8):
        raise ValueError("mask must be boolean with shape [N, 8]")
    counts = mask.sum(axis=0, dtype=np.int64)
    if np.any(counts == 0):
        raise ValueError("every position needs at least one visible training target")
    with np.errstate(over="ignore", invalid="ignore"):
        mean = features.mean(axis=0)
        scale = features.std(axis=0)
    if not np.isfinite(mean).all() or not np.isfinite(scale).all():
        raise ValueError("training normalization statistics must be finite")
    scale = np.where(scale > 1e-6, scale, 1.0)
    design = _standardize(features, mean, scale)
    penalty = np.eye(design.shape[1]) * float(ridge)
    penalty[-1, -1] = 0.0
    coefficients = np.empty((8, design.shape[1], 16), dtype=np.float64)
    for position in range(8):
        rows = design[mask[:, position]]
        labels = targets[mask[:, position], position]
        count = counts[position]
        with np.errstate(over="ignore", invalid="ignore"):
            gram = rows.T @ rows / count + penalty
            rhs = rows.T @ labels / count
        if not np.isfinite(gram).all() or not np.isfinite(rhs).all():
            raise ValueError("ridge normal equations must be finite")
        coefficients[position] = np.linalg.solve(gram, rhs)
    if not np.isfinite(coefficients).all():
        raise ValueError("ridge coefficients must be finite")
    return {
        "feature_mean": mean,
        "feature_scale": scale,
        "coefficients": coefficients,
        "fit_counts": counts,
    }


def predict_ridge(probe, features) -> np.ndarray:
    """Read frozen probe outputs without fitting or updating normalization."""
    features = _features(features)
    if not isinstance(probe, Mapping):
        raise ValueError("probe must be a mapping of fitted arrays")
    required = ("feature_mean", "feature_scale", "coefficients", "fit_counts")
    if not all(key in probe for key in required):
        raise ValueError("probe is missing fitted arrays")
    mean = _finite_array(probe["feature_mean"], "feature_mean")
    scale = _finite_array(probe["feature_scale"], "feature_scale")
    coefficients = _finite_array(probe["coefficients"], "coefficients")
    counts = np.asarray(probe["fit_counts"])
    width = features.shape[1]
    if mean.shape != (width,) or scale.shape != (width,):
        raise ValueError("probe normalization does not match feature width")
    if np.any(scale <= 0):
        raise ValueError("feature_scale must be positive")
    if coefficients.shape != (8, width + 1, 16):
        raise ValueError("coefficients must have shape [8, D + 1, 16]")
    if counts.shape != (8,) or counts.dtype.kind not in "iu" or np.any(counts <= 0):
        raise ValueError("fit_counts must contain eight positive integers")
    design = _standardize(features, mean, scale)
    with np.errstate(over="ignore", invalid="ignore"):
        predictions = np.einsum("nd,pdk->npk", design, coefficients)
    if not np.isfinite(predictions).all():
        raise ValueError("probe predictions must be finite")
    return predictions


def decode_embeddings(embeddings, readout_weight, readout_bias) -> np.ndarray:
    """Decode embedding predictions using a caller-provided frozen byte head."""
    embeddings = _finite_array(embeddings, "embeddings")
    weight = _finite_array(readout_weight, "readout_weight")
    bias = _finite_array(readout_bias, "readout_bias")
    if embeddings.ndim != 3 or embeddings.shape[1:] != (8, 16):
        raise ValueError("embeddings must have shape [N, 8, 16]")
    if weight.shape != (256, 16) or bias.shape != (256,):
        raise ValueError("readout weight/bias must have shapes [256, 16] and [256]")
    with np.errstate(over="ignore", invalid="ignore"):
        logits = embeddings @ weight.T + bias
    if not np.isfinite(logits).all():
        raise ValueError("readout logits must be finite")
    with np.errstate(over="ignore", under="ignore"):
        probabilities = np.exp(logits - logits.max(axis=-1, keepdims=True))
    probabilities = np.maximum(probabilities, np.finfo(np.float64).tiny)
    return probabilities / probabilities.sum(axis=-1, keepdims=True)
