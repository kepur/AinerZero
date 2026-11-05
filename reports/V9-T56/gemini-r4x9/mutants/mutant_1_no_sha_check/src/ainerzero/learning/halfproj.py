"""M2n-M6: one-sided projection of the history-half gradient off the single-edge half.

Pure NumPy. Takes the two masked half-gradient trees (``{"gru": {Wx, Wh, b, bhn}}``)
that the mixed branch already computes, flattens only the M2n-M5 trainable elements
(``tailself_freeze.trainable_element_mask``: tail rows minus the Wh tail-self block)
into float64 vectors g_h, g_s and applies

    if <g_h, g_s> < 0:  g_h <- g_h - <g_h, g_s> / ||g_s||^2 * g_s

``g_s`` is never modified. If ``||g_s||^2 < 1e-12`` the projection is skipped and
recorded. Non-trainable elements of the history tree are left untouched (they are
masked later by the unchanged M2n-M5 pipeline). When no projection happens the
*same* history tree object is returned, so the merged gradient is bitwise that of
M2n-M5. No model calls, no MLX import.
"""

from collections.abc import Mapping
import math

import numpy as np

from ainerzero.learning.gru_intervention import GRU_SHAPES
from ainerzero.learning.tailself_freeze import trainable_element_mask

SKIP_NORM_SQ_BELOW = 1e-12
POST_CHECK_RELATIVE_TOLERANCE = 1e-6
LEAVES = tuple(k.removeprefix("model.gru.") for k in GRU_SHAPES)


def _leaves(tree: Mapping, label: str) -> dict:
    if not isinstance(tree, Mapping) or set(tree) != {"gru"} or set(tree["gru"]) != set(LEAVES):
        raise ValueError(f"halfproj {label} tree must be exactly gru.{{{','.join(LEAVES)}}}")
    out = {}
    for name in LEAVES:
        value = np.asarray(tree["gru"][name])
        if value.shape != GRU_SHAPES[f"model.gru.{name}"]:
            raise ValueError(f"halfproj {label} shape mismatch: {name}")
        out[name] = value
    return out


def _masks() -> dict:
    return {n: trainable_element_mask(f"model.gru.{n}", GRU_SHAPES[f"model.gru.{n}"]) for n in LEAVES}


def flatten_trainable(tree: Mapping, label: str = "gradient") -> np.ndarray:
    """Concatenate the trainable elements of the four leaves (fixed order) as float64."""
    leaves, masks = _leaves(tree, label), _masks()
    return np.concatenate([leaves[n][masks[n]].astype(np.float64) for n in LEAVES])


def project_history_half(history: Mapping, single: Mapping) -> tuple:
    """Return ``(new_history_tree, telemetry)``; ``single`` is only read."""
    g_h = flatten_trainable(history, "history")
    g_s = flatten_trainable(single, "single_edge")
    if not (np.isfinite(g_h).all() and np.isfinite(g_s).all()):
        raise ValueError("halfproj half gradients must be finite")
    hh, ss, hs = float(g_h @ g_h), float(g_s @ g_s), float(g_h @ g_s)
    h_l2, s_l2 = math.sqrt(hh), math.sqrt(ss)
    cos = hs / (h_l2 * s_l2) if h_l2 > 0 and s_l2 > 0 else 0.0
    telemetry = {
        "inner_product": hs, "cos_gh_gs": cos, "history_l2": h_l2, "single_l2": s_l2,
        "projected": False, "skipped_small_single_norm": False, "removed_fraction": 0.0,
        "post_inner_product": hs, "elements": int(g_h.size),
    }
    if ss < SKIP_NORM_SQ_BELOW:
        telemetry["skipped_small_single_norm"] = True
        return history, telemetry
    if not hs < 0:
        return history, telemetry
    projected = g_h - (hs / ss) * g_s
    leaves, masks = _leaves(history, "history"), _masks()
    new_leaves, offset = {}, 0
    for name in LEAVES:
        mask = masks[name]
        count = int(mask.sum())
        value = leaves[name].copy()
        value[mask] = projected[offset:offset + count].astype(value.dtype)
        new_leaves[name] = value
        offset += count
    new_tree = {"gru": new_leaves}
    g_new = flatten_trainable(new_tree, "projected history")   # as stored (float32 cast)
    post = float(g_new @ g_s)
    removed = math.sqrt(float((g_h - g_new) @ (g_h - g_new))) / h_l2 if h_l2 > 0 else 0.0
    if not (np.isfinite(g_new).all() and math.isfinite(post) and math.isfinite(removed)):
        raise ValueError("halfproj projected history gradient is not finite")
    if post < -POST_CHECK_RELATIVE_TOLERANCE * h_l2 * s_l2:
        raise ValueError(f"halfproj post-projection inner product {post} is negative")
    telemetry.update(projected=True, post_inner_product=post, removed_fraction=removed,
                     projected_history_l2=math.sqrt(float(g_new @ g_new)))
    return new_tree, telemetry
