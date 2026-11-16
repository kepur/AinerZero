"""A fixed, CPU-only compatibility check for the frozen symbol codec.

The existing GRU's memory half starts at zero, is preserved by ``observe``,
and is updated as a convex combination of its old value and a tanh candidate.
With finite arithmetic, that half remains in [-1, 1]. A successful check below
exhibits a decodable vector in that box for every byte. It neither establishes
that the GRU can learn those vectors nor that its update can reach them.

These clipped embedding vectors are diagnostic witnesses only. They must never
be copied into student state or weights, or used as memory training targets.
Failure means this fixed check did not establish compatibility; it is not a
proof that no other bounded code exists. This module performs no optimization.
"""

import numpy as np


def _codec_array(value, name: str, shape: tuple[int, ...]) -> np.ndarray:
    array = np.asarray(value)
    if array.shape != shape or array.dtype.kind not in "iuf":
        raise ValueError(f"{name} must be a real numeric array with shape {shape}")
    with np.errstate(over="ignore", invalid="ignore"):
        array = array.astype(np.float64, copy=False)
    if not np.isfinite(array).all():
        raise ValueError(f"{name} must be finite in float64")
    return array


def audit_bounded_codec(embedding, weight, bias) -> dict:
    """Test fixed ``clip(embedding, -1, 1)`` witnesses without modifying inputs.

    ``weight`` and ``bias`` are the frozen 256-class linear readout. The
    returned object is JSON-compatible and deliberately does not expose witness
    arrays for use by a student. Each byte's margin is its target logit minus
    the highest *other* class logit; its NLL uses the actual 256-way softmax.
    Success requires correct top-1 predictions and strictly positive margins
    for all 256 bytes. Ties do not establish compatibility. Positive margins
    also avoid claiming success only because of an exact boundary tie.

    Nonfinite inputs or derived results raise ``ValueError``. No clipped loss,
    probability floor, fitted probe, or optimization masks a failed check.
    """
    embedding = _codec_array(embedding, "embedding", (256, 16))
    weight = _codec_array(weight, "weight", (256, 16))
    bias = _codec_array(bias, "bias", (256,))
    witnesses = np.clip(embedding, -1.0, 1.0)
    with np.errstate(over="ignore", invalid="ignore"):
        logits = witnesses @ weight.T + bias
    if not np.isfinite(logits).all():
        raise ValueError("bounded codec logits must be finite")

    labels = np.arange(256)
    top1 = logits.argmax(axis=1)
    target_logits = logits[labels, labels]
    competitors = logits.copy()
    np.fill_diagonal(competitors, -np.inf)
    maxima = logits.max(axis=1)
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        margins = target_logits - competitors.max(axis=1)
        # Shift first, then subtract target logits: large common offsets cancel.
        shifted = logits - maxima[:, None]
        nll = np.log(np.exp(shifted).sum(axis=1)) - shifted[labels, labels]
    if not np.isfinite(margins).all() or not np.isfinite(nll).all():
        raise ValueError("bounded codec margins and NLL must be finite")

    correct = top1 == labels
    positive = margins > 0
    all_correct = bool(correct.all())
    compatible = bool(all_correct and positive.all())
    clipped_counts = (witnesses != embedding).sum(axis=1)
    return {
        "audit": "fixed_clipped_embedding_witness_v1",
        "diagnostic_only": True,
        "witness_rule": "clip(frozen_byte_embedding, -1, 1)",
        "witnesses_copied_into_student": False,
        "witnesses_used_as_training_targets": False,
        "optimization_performed": False,
        "student_update_performed": False,
        "gru_learnability_established": False,
        "failure_does_not_prove_no_bounded_code_exists": True,
        "state_region": "h[:,128:]",
        "state_bounds": [-1.0, 1.0],
        "arithmetic": "numpy_float64_cpu",
        "class_count": 256,
        "correct_count": int(correct.sum()),
        "all_256_correct": all_correct,
        "positive_margin_count": int(positive.sum()),
        "bounded_codec_compatible": compatible,
        "minimum_margin": float(margins.min()),
        "mean_nll": float(np.sum(nll / 256)),
        "maximum_nll": float(nll.max()),
        "clipped_element_count": int(clipped_counts.sum()),
        "clipped_byte_count": int((clipped_counts > 0).sum()),
        "witness_minimum": float(witnesses.min()),
        "witness_maximum": float(witnesses.max()),
        "failed_bytes": labels[~(correct & positive)].tolist(),
        "per_byte": [
            {
                "byte": int(label),
                "predicted_byte": int(top1[label]),
                "correct": bool(correct[label]),
                "margin": float(margins[label]),
                "nll": float(nll[label]),
                "clipped_element_count": int(clipped_counts[label]),
            }
            for label in labels
        ],
    }
