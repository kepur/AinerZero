"""M2n-M5: additionally freeze the GRU tail self-recurrent block at its M2d values.

On top of the M2j tail-row scope (``tail_update``: only rows 128:256, 384:512,
640:768 of Wx/Wh/b and 128:256 of bhn may change), M2n-M5 also freezes
``model.gru.Wh[tail rows, tail cols 128:256]`` -- three 128x128 gate blocks,
49,152 elements. Trainable elements drop from 111,104 to 61,952; frozen rise from
282,128 to 331,280 (total 393,232 unchanged).

Same three-layer protection as the front rows: the gradient is masked, the
gradient actually handed to the optimizer is guarded (L2 <= 1e-8 over every
frozen GRU element), and after AdamW the block is projected back by selection
(not arithmetic) so bit patterns survive; then every frozen element is verified
bitwise. Numpy-only except ``mask_*``/``project_*`` which import MLX lazily.
"""

from collections.abc import Mapping
import math

import numpy as np

from ainerzero.learning.gru_intervention import GRU_SHAPES, MODEL_PARAMETER_COUNT, _model_arrays
from ainerzero.learning.tail_update import (
    FROZEN_PARAMETER_COUNT as TAIL_FROZEN_PARAMETER_COUNT,
    TAIL_PARAMETER_COUNT,
    TAIL_ROW_RANGES,
    _tail_rows,
    _validate_gradient_tree,
    project_gru_front,
    verify_tail_update,
)

TAILSELF_TENSOR = "model.gru.Wh"
TAILSELF_ROW_RANGES = TAIL_ROW_RANGES          # (128,256), (384,512), (640,768)
TAILSELF_COL_RANGE = (128, 256)
TAILSELF_BLOCK_ELEMENTS = 49_152
TAILSELF_TRAINABLE_PARAMETER_COUNT = TAIL_PARAMETER_COUNT - TAILSELF_BLOCK_ELEMENTS   # 61,952
TAILSELF_FROZEN_PARAMETER_COUNT = TAIL_FROZEN_PARAMETER_COUNT + TAILSELF_BLOCK_ELEMENTS  # 331,280
APPLIED_FROZEN_GRADIENT_MAX = 1e-8


def tailself_block_mask(shape: tuple = GRU_SHAPES[TAILSELF_TENSOR]) -> np.ndarray:
    """Boolean element mask of the newly frozen Wh[tail rows, tail cols] block."""
    if tuple(shape) != GRU_SHAPES[TAILSELF_TENSOR]:
        raise ValueError("tailself block mask applies only to model.gru.Wh (768, 256)")
    mask = np.zeros(shape, dtype=bool)
    for start, stop in TAILSELF_ROW_RANGES:
        mask[start:stop, TAILSELF_COL_RANGE[0]:TAILSELF_COL_RANGE[1]] = True
    return mask


def trainable_element_mask(key: str, shape: tuple) -> np.ndarray:
    """Element mask of what may change: tail rows, minus the Wh tail-self block."""
    rows = _tail_rows(key, shape)
    mask = np.broadcast_to(rows.reshape((-1,) + (1,) * (len(shape) - 1)), shape).copy()
    if key == TAILSELF_TENSOR:
        mask &= ~tailself_block_mask(shape)
    return mask


def mask_counts() -> dict:
    trainable = sum(int(trainable_element_mask(k, s).sum()) for k, s in GRU_SHAPES.items())
    block = int(tailself_block_mask().sum())
    return {"trainable": trainable, "tailself_block": block,
            "frozen": MODEL_PARAMETER_COUNT - trainable, "total": MODEL_PARAMETER_COUNT}


def mask_tailself_gradients(grads: Mapping) -> dict:
    """Fresh GRU gradient tree with front rows AND the Wh tail-self block zeroed."""
    gru = _validate_gradient_tree(grads)
    import mlx.core as mx

    masked = {}
    for name, value in gru.items():
        key = f"model.gru.{name}"
        keep = trainable_element_mask(key, tuple(value.shape))
        masked[name] = mx.where(mx.array(keep), value, mx.zeros_like(value))
    return {"gru": masked}


def check_applied_frozen_gradient(raw: Mapping, applied: Mapping) -> dict:
    """Guard on the gradient handed to the optimizer over ALL frozen GRU elements.

    Like ``check_applied_front_gradient`` but the frozen set also includes the
    Wh tail-self block. Inputs are ``{leaf: array}`` (``Wx/Wh/b/bhn``).
    """
    names = {k.removeprefix("model.gru."): k for k in GRU_SHAPES}
    if set(raw) != set(names) or set(applied) != set(names):
        raise ValueError("frozen-gradient guard needs exactly the four GRU leaves")
    raw_sq = applied_sq = block_raw_sq = block_applied_sq = 0.0
    with np.errstate(over="ignore", invalid="ignore"):
        for name, key in names.items():
            r = np.asarray(raw[name], dtype=np.float64)
            a = np.asarray(applied[name], dtype=np.float64)
            if r.shape != GRU_SHAPES[key] or a.shape != GRU_SHAPES[key]:
                raise ValueError(f"frozen-gradient guard shape mismatch: {name}")
            frozen = ~trainable_element_mask(key, GRU_SHAPES[key])
            raw_sq += float(np.sum(r[frozen] ** 2))
            applied_sq += float(np.sum(a[frozen] ** 2))
            if key == TAILSELF_TENSOR:
                block = tailself_block_mask()
                block_raw_sq = float(np.sum(r[block] ** 2))
                block_applied_sq = float(np.sum(a[block] ** 2))
    values = [math.sqrt(v) for v in (raw_sq, applied_sq, block_raw_sq, block_applied_sq)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("derived frozen-element gradient norms must be finite")
    if values[1] > APPLIED_FROZEN_GRADIENT_MAX:
        raise ValueError(f"applied frozen-element gradient {values[1]} exceeds 1e-8")
    return {"raw_frozen_gradient_l2": values[0], "applied_frozen_gradient_l2": values[1],
            "raw_tailself_gradient_l2": values[2], "applied_tailself_gradient_l2": values[3],
            "applied_frozen_gradient_max": APPLIED_FROZEN_GRADIENT_MAX}


def project_tailself(model, source_tensors: Mapping) -> None:
    """Restore front rows (``project_gru_front``) and then the Wh tail-self block."""
    project_gru_front(model, source_tensors)
    source = _model_arrays(source_tensors, "source")
    import mlx.core as mx

    current = model.gru.Wh
    original = mx.array(source[TAILSELF_TENSOR])
    if tuple(current.shape) != GRU_SHAPES[TAILSELF_TENSOR] or current.dtype != original.dtype:
        raise ValueError("tailself projection model/source shape or dtype mismatch")
    block = mx.array(tailself_block_mask())
    model.update({"gru": {"Wh": mx.where(block, original, current)}})


def verify_tailself_update(source_tensors: Mapping, current_tensors: Mapping) -> dict:
    """Bitwise check of all 331,280 frozen elements (282,128 via tail_update + block)."""
    base = verify_tail_update(source_tensors, current_tensors)
    source = _model_arrays(source_tensors, "source")
    current = _model_arrays(current_tensors, "current")
    block = tailself_block_mask()
    a, b = source[TAILSELF_TENSOR][block], current[TAILSELF_TENSOR][block]
    if a.dtype != b.dtype or a.tobytes() != b.tobytes():
        raise ValueError("frozen GRU Wh tail-self block changed")
    frozen = base["frozen_parameter_count"] + int(block.sum())
    if frozen != TAILSELF_FROZEN_PARAMETER_COUNT:
        raise RuntimeError("tailself frozen parameter count mismatch")
    return {**base,
            "update_scope": "gru_tail_output_rows_minus_Wh_tail_self_block",
            "allowed_parameter_count": TAILSELF_TRAINABLE_PARAMETER_COUNT,
            "frozen_parameter_count": frozen,
            "tailself_block": {"tensor": TAILSELF_TENSOR,
                               "rows": [list(r) for r in TAILSELF_ROW_RANGES],
                               "cols": list(TAILSELF_COL_RANGE),
                               "elements": int(block.sum()),
                               "bitwise_identical": True}}
