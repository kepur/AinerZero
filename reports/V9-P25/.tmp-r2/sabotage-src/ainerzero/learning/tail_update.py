"""Restrict M2j updates to the existing GRU's tail output coordinates.

Masking gradients alone does not protect frozen rows from AdamW weight decay.
The worker must project the front rows after each update, evaluate its tensors,
then call the CPU verifier before accepting the update. This isolates parameter
changes, not recurrent state paths or behavioral effects.
"""

from collections.abc import Mapping

import numpy as np

from ainerzero.learning.gru_intervention import (
    GRU_PARAMETER_COUNT,
    GRU_SHAPES,
    MODEL_PARAMETER_COUNT,
    _changed_elements,
    _digest,
    _equal,
    _model_arrays,
    _ranges,
)

TAIL_ROW_RANGES = ((128, 256), (384, 512), (640, 768))
TAIL_PARAMETER_COUNT = GRU_PARAMETER_COUNT // 2
FROZEN_PARAMETER_COUNT = MODEL_PARAMETER_COUNT - TAIL_PARAMETER_COUNT


def _tail_rows(key: str, shape: tuple) -> np.ndarray:
    rows = np.zeros(shape[0], dtype=bool)
    for start, stop in ((128, 256),) if key.endswith(".bhn") else TAIL_ROW_RANGES:
        rows[start:stop] = True
    return rows


def _validate_gradient_tree(grads: Mapping) -> Mapping:
    def empty_branch(value):
        if isinstance(value, Mapping):
            return all(empty_branch(child) for child in value.values())
        if isinstance(value, (list, tuple)):
            return all(empty_branch(child) for child in value)
        return False

    names = {key.removeprefix("model.gru.") for key in GRU_SHAPES}
    if (
        not isinstance(grads, Mapping)
        or "gru" not in grads
        or any(not empty_branch(value) for key, value in grads.items() if key != "gru")
        or not isinstance(grads["gru"], Mapping)
        or set(grads["gru"]) != names
    ):
        raise ValueError("tail gradients must contain exactly the four gru parameter leaves")
    for name, value in grads["gru"].items():
        if getattr(value, "shape", None) != GRU_SHAPES[f"model.gru.{name}"]:
            raise ValueError(f"tail gradient shape mismatch: gru.{name}")
    return grads["gru"]


def mask_gru_tail_gradients(grads: Mapping) -> dict:
    """Return a fresh GRU gradient tree with front output rows set to zero.

    MLX may retain empty dict/list branches for frozen modules. Those carry
    no gradient leaves and are discarded; any non-GRU leaf is still rejected.
    Retained rows are 128:256, 384:512 and 640:768 of Wx/Wh/b, and 128:256
    of bhn. Inputs are not modified. The worker owns finite-gradient checks,
    clipping, optimization, budget reservation and subsequent projection.
    """
    gru = _validate_gradient_tree(grads)
    import mlx.core as mx

    masked = {}
    for name, value in gru.items():
        key = f"model.gru.{name}"
        rows = _tail_rows(key, value.shape).reshape((-1,) + (1,) * (value.ndim - 1))
        masked[name] = mx.where(mx.array(rows), value, mx.zeros_like(value))
    return {"gru": masked}


def project_gru_front(model, source_tensors: Mapping) -> None:
    """Restore source front rows after optimization while retaining current tails.

    Source tensors use checkpoint names (``model.gru.Wx`` etc.). Non-GRU model
    parameters are untouched here: ``verify_tail_update`` must independently
    reject any change there. All four replacements are prepared and validated
    before ``model.update`` is called. Selection rather than arithmetic retains
    the original frozen bit patterns, including signed zero.
    """
    source = _model_arrays(source_tensors, "source")
    import mlx.core as mx

    restored = {}
    for key, shape in GRU_SHAPES.items():
        name = key.removeprefix("model.gru.")
        current = getattr(model.gru, name)
        original = mx.array(source[key])
        if current.shape != shape or current.dtype != original.dtype:
            raise ValueError(f"projection model/source shape or dtype mismatch: {key}")
        rows = _tail_rows(key, shape).reshape((-1,) + (1,) * (current.ndim - 1))
        restored[name] = mx.where(mx.array(rows), current, original)
    model.update({"gru": restored})


def verify_tail_update(source_tensors: Mapping, current_tensors: Mapping) -> dict:
    """Verify finite equal-shape/dtype weights and bitwise-frozen parameters.

    Only ``model.*`` tensors are examined; optimizer/RNG state is outside this
    contract. The full fixed model and GRU parameter counts are checked, and
    every model key, shape and dtype must match the source. All 282,128 frozen
    parameters must be bitwise unchanged. Tail changes are optional so callers
    can verify the source before the first update. No tensors are modified.
    """
    source = _model_arrays(source_tensors, "source")
    current = _model_arrays(current_tensors, "current")
    if source.keys() != current.keys():
        raise ValueError("source and current model tensor keys must match")
    changed_tensors, details = [], {}
    total_changed = frozen_count = 0
    for key, original in source.items():
        updated = current[key]
        if original.shape != updated.shape or original.dtype != updated.dtype:
            raise ValueError(f"source and current shape/dtype mismatch: {key}")
        if key not in GRU_SHAPES:
            if not _equal(original, updated):
                raise ValueError(f"frozen non-GRU tensor changed: {key}")
            frozen_count += original.size
            continue
        tail_rows = _tail_rows(key, original.shape)
        changed = _changed_elements(original, updated)
        if changed[~tail_rows].any():
            raise ValueError(f"frozen GRU front output rows changed: {key}")
        count = int(changed.sum())
        if count:
            changed_tensors.append(key)
        total_changed += count
        frozen_count += original.size // 2
        details[key] = {
            "allowed_tail_row_ranges": _ranges(np.flatnonzero(tail_rows)),
            "changed_elements": count,
            "changed_row_ranges": _ranges(
                np.flatnonzero(changed.reshape(original.shape[0], -1).any(axis=1))
            ),
            "frozen_front_bitwise_identical": True,
        }
    if frozen_count != FROZEN_PARAMETER_COUNT:
        raise RuntimeError("tail update frozen parameter count mismatch")
    return {
        "schema_version": 1,
        "update_scope": "gru_tail_output_rows_only",
        "model_parameter_count": MODEL_PARAMETER_COUNT,
        "gru_parameter_count": GRU_PARAMETER_COUNT,
        "allowed_parameter_count": TAIL_PARAMETER_COUNT,
        "frozen_parameter_count": frozen_count,
        "model_keys_shapes_dtypes_match": True,
        "all_model_weights_finite": True,
        "frozen_parameters_bitwise_identical": True,
        "changed_model_tensors": sorted(changed_tensors),
        "changed_elements": total_changed,
        "per_gru_tensor": {key: details[key] for key in sorted(details)},
        "row_ranges_end_exclusive": True,
        "model_sha256": {"source": _digest(source), "current": _digest(current)},
        "state_path_isolation_established": False,
        "behavioral_effect_established": False,
        "promotion_allowed": False,
    }
