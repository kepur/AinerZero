"""M2n-M7: intra-history CE/KL gradient projection followed by M2n-M6 half-projection.

Pure NumPy. Takes three masked gradient trees (``{"gru": {Wx, Wh, b, bhn}}``):
1. ``ce_history``: cross-entropy gradient from the student history half
2. ``kl_history``: action-preservation KL distillation gradient from the student history half
3. ``single``: single-edge half gradient (M2n-M6 baseline)

Algorithm:
1. Flattens only the M2n-M5 trainable elements (tail rows minus the Wh tail-self block)
   into float64 vectors g_CEh, g_KLh, g_s.
2. Intra-history projection:
   if <g_CEh, g_KLh> < 0:
       g_CEh <- g_CEh - <g_CEh, g_KLh> / ||g_KLh||^2 * g_KLh
   g_KLh is never modified. Skip if ||g_KLh||^2 < 1e-12.
3. Form g_h = g_CEh + g_KLh.
4. M2n-M6 inter-half projection:
   if <g_h, g_s> < 0:
       g_h <- g_h - <g_h, g_s> / ||g_s||^2 * g_s
   g_s is never modified. Skip if ||g_s||^2 < 1e-12.
5. Merged gradient, mask, clip and AdamW follow M2n-M6 unchanged.
"""

from collections.abc import Mapping
import math

import numpy as np

from ainerzero.learning.gru_intervention import GRU_SHAPES
from ainerzero.learning.halfproj import (
    LEAVES,
    POST_CHECK_RELATIVE_TOLERANCE,
    SKIP_NORM_SQ_BELOW,
    _leaves,
    _masks,
    flatten_trainable,
    project_history_half,
)


def project_intra_history(ce_history: Mapping, kl_history: Mapping) -> tuple[dict, dict]:
    """Project ``ce_history`` off ``kl_history`` when <g_CEh, g_KLh> < 0.

    ``kl_history`` is never modified.
    Returns ``(new_ce_history_tree, telemetry)``.
    """
    g_ce = flatten_trainable(ce_history, "ce_history")
    g_kl = flatten_trainable(kl_history, "kl_history")
    if not (np.isfinite(g_ce).all() and np.isfinite(g_kl).all()):
        raise ValueError("fullproj history gradients must be finite")
    ce_sq, kl_sq, c = float(g_ce @ g_ce), float(g_kl @ g_kl), float(g_ce @ g_kl)
    ce_l2, kl_l2 = math.sqrt(ce_sq), math.sqrt(kl_sq)
    cos = c / (ce_l2 * kl_l2) if ce_l2 > 0 and kl_l2 > 0 else 0.0
    telemetry = {
        "inner_product": c,
        "cos_gCEh_gKLh": cos,
        "ce_h_l2": ce_l2,
        "kl_h_l2": kl_l2,
        "intra_projected": False,
        "skipped_small_kl_norm": False,
        "intra_removed_fraction": 0.0,
        "post_inner_product": c,
        "elements": int(g_ce.size),
    }
    if kl_sq < SKIP_NORM_SQ_BELOW:
        telemetry["skipped_small_kl_norm"] = True
        return ce_history, telemetry
    if not c < 0:
        return ce_history, telemetry
    projected = g_ce - (c / kl_sq) * g_kl
    leaves, masks = _leaves(ce_history, "ce_history"), _masks()
    new_leaves, offset = {}, 0
    for name in LEAVES:
        mask = masks[name]
        count = int(mask.sum())
        value = leaves[name].copy()
        value[mask] = projected[offset:offset + count].astype(value.dtype)
        new_leaves[name] = value
        offset += count
    new_tree = {"gru": new_leaves}
    g_new = flatten_trainable(new_tree, "projected ce_history")
    post = float(g_new @ g_kl)
    removed = math.sqrt(float((g_ce - g_new) @ (g_ce - g_new))) / ce_l2 if ce_l2 > 0 else 0.0
    if not (np.isfinite(g_new).all() and math.isfinite(post) and math.isfinite(removed)):
        raise ValueError("fullproj projected ce_history gradient is not finite")
    if post < -POST_CHECK_RELATIVE_TOLERANCE * ce_l2 * kl_l2:
        raise ValueError(f"fullproj post-projection inner product {post} is negative")
    telemetry.update(
        intra_projected=True,
        post_inner_product=post,
        intra_removed_fraction=removed,
        projected_ce_h_l2=math.sqrt(float(g_new @ g_new)),
    )
    return new_tree, telemetry


def add_gradient_trees(tree_a: Mapping, tree_b: Mapping) -> dict:
    """Elementwise addition of two gradient trees."""
    leaves_a = _leaves(tree_a, "tree_a")
    leaves_b = _leaves(tree_b, "tree_b")
    out = {}
    for name in LEAVES:
        out[name] = (leaves_a[name] + leaves_b[name]).astype(np.float32)
    return {"gru": out}


def project_full(ce_history: Mapping, kl_history: Mapping, single: Mapping) -> tuple[dict, dict]:
    """Execute the full two-stage projection for M2n-M7.

    1. Intra-history: project ce_history off kl_history when <g_CEh, g_KLh> < 0
    2. Sum: g_h = g_CEh' + g_KLh
    3. Inter-half: project g_h off g_s when <g_h, g_s> < 0 (M2n-M6)

    Returns ``(new_history_tree, telemetry)``.
    Neither ``kl_history`` nor ``single`` is ever modified.
    """
    new_ce_h, intra_tel = project_intra_history(ce_history, kl_history)
    g_h_tree = add_gradient_trees(new_ce_h, kl_history)
    new_g_h, inter_tel = project_history_half(g_h_tree, single)

    telemetry = {
        "cos_gCEh_gKLh": intra_tel["cos_gCEh_gKLh"],
        "intra_projected": intra_tel["intra_projected"],
        "intra_removed_fraction": intra_tel["intra_removed_fraction"],
        "cos_gh_gs": inter_tel["cos_gh_gs"],
        "projected": inter_tel["projected"],
        "removed_fraction": inter_tel["removed_fraction"],
        "history_l2": inter_tel["history_l2"],
        "single_l2": inter_tel["single_l2"],
        "kl_h_l2": intra_tel["kl_h_l2"],
        "ce_h_l2": intra_tel["ce_h_l2"],
        "intra_inner_product": intra_tel["inner_product"],
        "inter_inner_product": inter_tel["inner_product"],
        "intra_post_inner_product": intra_tel["post_inner_product"],
        "inter_post_inner_product": inter_tel["post_inner_product"],
        "elements": intra_tel["elements"],
        "skipped_small_kl_norm": intra_tel["skipped_small_kl_norm"],
        "skipped_small_single_norm": inter_tel["skipped_small_single_norm"],
    }
    return new_g_h, telemetry
