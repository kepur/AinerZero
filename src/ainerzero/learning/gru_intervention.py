"""CPU-only construction of the preregistered M2i frozen GRU intervention.

The restored rows correspond to front *output* coordinates of all three GRU
gates. They do not isolate the front state from tail inputs or the posterior.
This module does not load checkpoints, execute a model, or perform optimization.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from numbers import Real

import numpy as np

MODEL_PARAMETER_COUNT = 393_232
GRU_PARAMETER_COUNT = 222_208
GRU_SHAPES = {
    "model.gru.Wx": (768, 32),
    "model.gru.Wh": (768, 256),
    "model.gru.b": (768,),
    "model.gru.bhn": (256,),
}
FRONT_ROW_RANGES = ((0, 128), (256, 384), (512, 640))


def _model_arrays(tensors: Mapping, label: str) -> dict[str, np.ndarray]:
    if not isinstance(tensors, Mapping) or any(not isinstance(k, str) for k in tensors):
        raise ValueError(f"{label} must be a mapping with string tensor keys")
    result = {}
    for key, value in tensors.items():
        if not key.startswith("model."):
            continue
        array = np.asarray(value)
        if array.dtype.kind != "f" or not np.isfinite(array).all():
            raise ValueError(f"{label} {key} must contain finite floating-point weights")
        result[key] = array
    if sum(array.size for array in result.values()) != MODEL_PARAMETER_COUNT:
        raise ValueError(f"{label} model parameter count must be {MODEL_PARAMETER_COUNT}")
    gru = {k: a.shape for k, a in result.items() if k.startswith("model.gru.")}
    if gru != GRU_SHAPES:
        raise ValueError(f"{label} GRU keys and shapes do not match the fixed M2i architecture")
    if sum(result[key].size for key in GRU_SHAPES) != GRU_PARAMETER_COUNT:
        raise ValueError(f"{label} GRU parameter count must be {GRU_PARAMETER_COUNT}")
    return result


def _equal(left: np.ndarray, right: np.ndarray) -> bool:
    # Include signed zero: intervention identities are exact saved tensor bits.
    return left.tobytes(order="C") == right.tobytes(order="C")


def _digest(tensors: dict[str, np.ndarray]) -> str:
    digest = hashlib.sha256()
    for key, array in sorted(tensors.items()):
        payload = array.tobytes(order="C")
        descriptor = json.dumps(
            [key, list(array.shape), array.dtype.str, len(payload)],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("ascii")
        digest.update(descriptor + b"\0" + payload)
    return digest.hexdigest()


def _changed_elements(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    # The caller has already checked matching dtype and shape.
    left_bytes = np.ascontiguousarray(left).view(np.uint8).reshape(left.shape + (-1,))
    right_bytes = np.ascontiguousarray(right).view(np.uint8).reshape(right.shape + (-1,))
    return np.any(left_bytes != right_bytes, axis=-1)


def _ranges(rows: np.ndarray) -> list[list[int]]:
    """Compress sorted row indices into end-exclusive contiguous ranges."""
    result = []
    for row in rows.tolist():
        if result and row == result[-1][1]:
            result[-1][1] += 1
        else:
            result.append([row, row + 1])
    return result


def build_front_reverted_variants(
    source_tensors: Mapping, candidate_tensors: Mapping
) -> tuple[dict[str, dict[str, np.ndarray]], dict]:
    """Return independent source/candidate/front_reverted copies and evidence.

    Inputs may include optimizer or RNG tensors; only ``model.*`` tensors are
    returned or fingerprinted. All model keys, shapes and dtypes must match,
    weights must be finite, and every non-GRU tensor must be bitwise identical.
    The fixed model/GRU parameter counts and four GRU shapes are enforced.

    The temporary hybrid restores only ``Wx/Wh/b`` rows ``0:128, 256:384,
    512:640`` and ``bhn[:128]``. Every other element retains the candidate value.
    No output array shares storage with an input or another variant. Evidence
    contains JSON-compatible differences and deterministic model fingerprints;
    it is not evidence of a behavioral effect or permission to promote a model.
    """
    source = _model_arrays(source_tensors, "source")
    candidate = _model_arrays(candidate_tensors, "candidate")
    if source.keys() != candidate.keys():
        raise ValueError("source and candidate model tensor keys must match")
    for key, original in source.items():
        updated = candidate[key]
        if original.shape != updated.shape or original.dtype != updated.dtype:
            raise ValueError(f"source and candidate shape/dtype mismatch: {key}")
        if key not in GRU_SHAPES and not _equal(original, updated):
            raise ValueError(f"frozen non-GRU tensor changed: {key}")

    variants = {
        "source": {key: value.copy() for key, value in source.items()},
        "candidate": {key: value.copy() for key, value in candidate.items()},
        "front_reverted": {key: value.copy() for key, value in candidate.items()},
    }
    hybrid = variants["front_reverted"]
    details = {}
    restored_count = 0
    for key in sorted(GRU_SHAPES):
        original, updated, reverted = source[key], candidate[key], hybrid[key]
        ranges = ((0, 128),) if key.endswith(".bhn") else FRONT_ROW_RANGES
        front_rows = np.zeros(original.shape[0], dtype=bool)
        for start, stop in ranges:
            reverted[start:stop] = original[start:stop]
            front_rows[start:stop] = True
        changed = _changed_elements(original, updated)
        changed_from_candidate = _changed_elements(updated, reverted)
        changed_from_source = _changed_elements(original, reverted)
        row_size = original.size // original.shape[0]
        front_count = int(front_rows.sum()) * row_size
        restored_count += front_count
        details[key] = {
            "restored_row_ranges": [list(pair) for pair in ranges],
            "restored_parameter_count": front_count,
            "front_source_candidate_changed_elements": int(changed[front_rows].sum()),
            "tail_source_candidate_changed_elements": int(changed[~front_rows].sum()),
            "hybrid_candidate_changed_elements": int(changed_from_candidate.sum()),
            "hybrid_candidate_changed_row_ranges": _ranges(
                np.flatnonzero(changed_from_candidate.reshape(original.shape[0], -1).any(axis=1))
            ),
            "hybrid_source_changed_elements": int(changed_from_source.sum()),
            "hybrid_source_changed_row_ranges": _ranges(
                np.flatnonzero(changed_from_source.reshape(original.shape[0], -1).any(axis=1))
            ),
            "restored_front_equals_source": _equal(reverted[front_rows], original[front_rows]),
            "retained_tail_equals_candidate": _equal(reverted[~front_rows], updated[~front_rows]),
        }
        if not (
            details[key]["restored_front_equals_source"]
            and details[key]["retained_tail_equals_candidate"]
            and not changed_from_candidate[~front_rows].any()
        ):
            raise RuntimeError(f"front-output intervention verification failed: {key}")

    frozen_equal = all(_equal(hybrid[k], candidate[k]) for k in source if k not in GRU_SHAPES)
    if not frozen_equal or restored_count != GRU_PARAMETER_COUNT // 2:
        raise RuntimeError("front-output intervention changed its declared scope")
    evidence = {
        "schema_version": 1,
        "intervention": "frozen_front_output_row_reversion",
        "diagnostic_only": True,
        "student_updates": 0,
        "model_parameter_count": MODEL_PARAMETER_COUNT,
        "gru_parameter_count": GRU_PARAMETER_COUNT,
        "restored_parameter_count": restored_count,
        "model_keys_shapes_dtypes_match": True,
        "all_model_weights_finite": True,
        "frozen_non_gru_tensors_bitwise_identical": frozen_equal,
        "source_candidate_changed_model_tensors": sorted(
            key for key in source if not _equal(source[key], candidate[key])
        ),
        "hybrid_candidate_changed_model_tensors": sorted(
            key for key in source if not _equal(hybrid[key], candidate[key])
        ),
        "hybrid_source_changed_model_tensors": sorted(
            key for key in source if not _equal(hybrid[key], source[key])
        ),
        "row_ranges_end_exclusive": True,
        "per_gru_tensor": details,
        "model_sha256": {name: _digest(arrays) for name, arrays in variants.items()},
        "hash_format": "sha256(sorted model keys; JSON[key,shape,dtype.str,byte_count] + NUL + C-order tensor bytes)",
        "state_path_isolation_established": False,
        "behavioral_effect_established": False,
        "promotion_allowed": False,
    }
    return variants, evidence


def action_nll_recovery(source_nll: Real, candidate_nll: Real, hybrid_nll: Real) -> dict:
    """Report the unbounded NLL recovery ratio, without a pass threshold.

    A nonpositive candidate-minus-source denominator makes the ratio
    inapplicable. All three scores and both raw differences are still returned.
    Finite nonnegative real scalar NLLs and finite derived values are required.
    """
    scores = {}
    for name, value in (
        ("source_nll", source_nll),
        ("candidate_nll", candidate_nll),
        ("hybrid_nll", hybrid_nll),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
            raise ValueError(f"{name} must be a finite nonnegative real scalar")
        try:
            score = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"{name} must be a finite nonnegative real scalar") from exc
        if not math.isfinite(score) or score < 0:
            raise ValueError(f"{name} must be a finite nonnegative real scalar")
        scores[name] = score
    denominator = scores["candidate_nll"] - scores["source_nll"]
    numerator = scores["candidate_nll"] - scores["hybrid_nll"]
    if not math.isfinite(denominator) or not math.isfinite(numerator):
        raise ValueError("action NLL recovery differences must be finite")
    ratio = numerator / denominator if denominator > 0 else None
    if ratio is not None and not math.isfinite(ratio):
        raise ValueError("action NLL recovery ratio must be finite")
    return {
        **scores,
        "candidate_minus_source_nll": denominator,
        "candidate_minus_hybrid_nll": numerator,
        "recovery_ratio": ratio,
        "applicable": denominator > 0,
        "reason": None if denominator > 0 else "candidate_nll_not_worse_than_source",
        "ratio_clipped": False,
        "promotion_threshold": None,
    }
