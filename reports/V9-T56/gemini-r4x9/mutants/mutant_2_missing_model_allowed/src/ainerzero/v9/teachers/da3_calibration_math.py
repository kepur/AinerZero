"""T6 DA3 标定的纯数值函数（只依赖 numpy，不加载任何模型）。

口径一律来自 reports/V9-T28/proposal.json（T28 预登记，T29 独立复核）：
  - 位姿用 camera-to-world；锚点视图 0，尺度视图 2，被评分视图 1；
  - 旋转残差 = LogSO3(Rrel_gt_1.T @ Rrel_pred_1)；平移残差 = (s*u_pred_1 - u_gt_1)/b_gt，s = |u_gt_2| / |u_pred_2|；
  - 深度：s_depth = median(D_gt_0 / D_pred_0)，用 s_depth * D_pred_1 对 D_gt_1 评分，**不对目标视图再拟合**；
  - 7 维残差顺序：rot_x, rot_y, rot_z, trans_x, trans_y, trans_z, mean_log_depth_ratio；
  - 数值对拍：逐元素 |a-b| <= atol + rtol*|ref|，同形且有限，结果出来后不得放宽。

本模块没有任何"写死的结论"：返回值全部由输入算出。尺寸、有限性、基线退化一律抛 ValueError，不静默修复、不静默缩放。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np

PI_BRANCH_REFUSAL_RAD = 1e-6          # T28 alignment.pi_branch_refusal_rad
GT_BASELINE_MIN_M = 1e-6              # T28 alignment.gt_baseline_min_metres
PRED_BASELINE_MIN = 1e-12             # T28 alignment.predicted_baseline_min_model_units
RESIDUAL_ORDER = (
    "rotation_x_rad", "rotation_y_rad", "rotation_z_rad",
    "translation_x_per_anchor_baseline", "translation_y_per_anchor_baseline",
    "translation_z_per_anchor_baseline", "mean_log_depth_ratio_target",
)


def w2c_to_c2w(extrinsics: np.ndarray) -> np.ndarray:
    """DA3/管线的 extrinsics 是 world_to_camera（回执 coordinate_frame.extrinsics）。转成 4x4 camera_to_world。

    接受 (N,3,4) 或 (N,4,4)。旋转部分必须是 SO(3)，否则抛错，不做静默修复。
    """
    e = np.asarray(extrinsics, dtype=np.float64)
    if e.ndim != 3 or e.shape[1:] not in ((3, 4), (4, 4)):
        raise ValueError(f"extrinsics must be (N,3,4) or (N,4,4), got {e.shape}")
    if not np.isfinite(e).all():
        raise ValueError("non-finite extrinsics")
    n = e.shape[0]
    full = np.tile(np.eye(4), (n, 1, 1))
    full[:, :3, :4] = e[:, :3, :4]
    for i in range(n):
        r = full[i, :3, :3]
        if not np.allclose(r.T @ r, np.eye(3), atol=1e-4) or not np.isclose(np.linalg.det(r), 1.0, atol=1e-4):
            raise ValueError(f"extrinsics[{i}] rotation is not SO(3)")
    return np.linalg.inv(full)


def _rel(seq: Sequence[np.ndarray], i: int) -> tuple[np.ndarray, np.ndarray]:
    a, c = np.asarray(seq[0], dtype=np.float64), np.asarray(seq[i], dtype=np.float64)
    return a[:3, :3].T @ c[:3, :3], a[:3, :3].T @ (c[:3, 3] - a[:3, 3])


def _log_so3(delta: np.ndarray) -> tuple[np.ndarray, float]:
    skew = np.array([delta[2, 1] - delta[1, 2], delta[0, 2] - delta[2, 0], delta[1, 0] - delta[0, 1]]) / 2.0
    sin = float(np.linalg.norm(skew))
    cos = float(np.clip((np.trace(delta) - 1.0) / 2.0, -1.0, 1.0))
    angle = math.atan2(sin, cos)
    if math.pi - angle < PI_BRANCH_REFUSAL_RAD:
        raise ValueError("rotation residual too close to pi; LogSO3 branch refused")
    rv = skew if angle < 1e-8 else skew * (angle / sin)
    return rv, angle


def anchored_residual(
    gt_c2w: Sequence[np.ndarray],
    pred_c2w: Sequence[np.ndarray],
    gt_depths: Sequence[np.ndarray],
    pred_depths: Sequence[np.ndarray],
) -> dict[str, Any]:
    """T28 的锚点相对残差与深度指标。输入的位姿必须已经是 camera_to_world。

    返回 residual_7d 以及由同一组量派生的原始指标（rotation_deg、translation_rel_anchor_baseline、
    depth_abs_rel、depth_delta1、各计数），不做任何多余的"对齐"。
    """
    if len(gt_c2w) < 3 or len(pred_c2w) < 3 or len(gt_depths) < 2 or len(pred_depths) < 2:
        raise ValueError("need 3 poses and 2 depth maps (anchor view 0, scored view 1, scale view 2)")
    for name, arrs in (("gt_depths", gt_depths), ("pred_depths", pred_depths)):
        for a in arrs[:2]:
            if np.asarray(a).ndim != 2:
                raise ValueError(f"{name} must be 2-D depth maps")
    for i in (0, 1):
        if np.asarray(pred_depths[i]).shape != np.asarray(gt_depths[i]).shape:
            raise ValueError(
                f"paired depth shapes must agree (view {i}: pred {np.asarray(pred_depths[i]).shape} "
                f"vs gt {np.asarray(gt_depths[i]).shape}); resampling is not allowed")

    rg, ug = _rel(gt_c2w, 1)
    rp, up = _rel(pred_c2w, 1)
    _, g2 = _rel(gt_c2w, 2)
    _, p2 = _rel(pred_c2w, 2)
    bg, bp = float(np.linalg.norm(g2)), float(np.linalg.norm(p2))
    if not (bg > GT_BASELINE_MIN_M):
        raise ValueError("ground-truth anchor baseline below minimum")
    if not (bp > PRED_BASELINE_MIN):
        raise ValueError("predicted anchor baseline below minimum")

    rv, angle = _log_so3(rg.T @ rp)
    trans_res = ((bg / bp) * up - ug) / bg

    p0, g0 = np.asarray(pred_depths[0], dtype=np.float64), np.asarray(gt_depths[0], dtype=np.float64)
    p1, g1 = np.asarray(pred_depths[1], dtype=np.float64), np.asarray(gt_depths[1], dtype=np.float64)
    m0 = np.isfinite(p0) & np.isfinite(g0) & (p0 > 0) & (g0 > 0)
    m1 = np.isfinite(p1) & np.isfinite(g1) & (p1 > 0) & (g1 > 0)
    if not m0.any() or not m1.any():
        raise ValueError("zero valid depth pixels")
    s_depth = float(np.median(g0[m0] / p0[m0]))
    aligned = s_depth * p1[m1]
    truth = g1[m1]
    ratio = np.maximum(aligned / truth, truth / aligned)
    depth_res = float(np.mean(np.log(aligned / truth)))
    abs_rel = float(np.mean(np.abs(aligned - truth) / truth))
    delta1 = float(np.mean(ratio < 1.25))

    residual = np.concatenate([rv, trans_res, [depth_res]])
    if not np.isfinite(residual).all():
        raise ValueError("non-finite residual")
    return {
        "residual_7d": residual,
        "rotation_error_rad": float(angle),
        "rotation_deg": float(np.degrees(angle)),
        "translation_residual_norm": float(np.linalg.norm(trans_res)),
        "translation_rel_anchor_baseline": float(np.linalg.norm(trans_res)),
        "depth_abs_rel": abs_rel,
        "depth_delta1": delta1,
        "s_depth": s_depth,
        "valid_pixels_anchor": int(m0.sum()),
        "valid_pixels_target": int(m1.sum()),
        "total_pixels": int(m1.size),
    }


def adverse_score(metrics: Mapping[str, Any]) -> float:
    """T28 negative_controls.score = rotation_error_rad + norm(translation_residual3) + depth_abs_rel。"""
    return float(metrics["rotation_error_rad"] + metrics["translation_residual_norm"] + metrics["depth_abs_rel"])


def required_red(s_clean: float, s_bad: float, floor: float = 1e-4, rel: float = 0.1) -> bool:
    """T28: S_bad >= S_clean + max(0.0001, 0.1 * S_clean)。常数由调用方从预登记读取后传入。"""
    return bool(s_bad >= s_clean + max(floor, rel * s_clean))


def parity_compare(reference: Mapping[str, np.ndarray], other: Mapping[str, np.ndarray],
                   fields: Sequence[str], atol: float, rtol: float) -> dict[str, Any]:
    """逐元素 |a-b| <= atol + rtol*|ref|；同形且有限；报 max_abs 与失败元素数；不放宽。"""
    out: dict[str, Any] = {"atol": atol, "rtol": rtol, "fields": {}}
    all_pass = True
    for f in fields:
        if f not in reference or f not in other:
            out["fields"][f] = {"pass": False, "error": "missing field"}
            all_pass = False
            continue
        a, b = np.asarray(reference[f], dtype=np.float64), np.asarray(other[f], dtype=np.float64)
        if a.shape != b.shape:
            out["fields"][f] = {"pass": False, "error": f"shape mismatch {a.shape} vs {b.shape}"}
            all_pass = False
            continue
        if not (np.isfinite(a).all() and np.isfinite(b).all()):
            out["fields"][f] = {"pass": False, "error": "non-finite values"}
            all_pass = False
            continue
        diff = np.abs(a - b)
        failed = int((diff > atol + rtol * np.abs(a)).sum())
        out["fields"][f] = {"pass": failed == 0, "max_abs": float(diff.max()) if diff.size else 0.0,
                            "failed_elements": failed, "total_elements": int(diff.size)}
        all_pass = all_pass and failed == 0
    out["pass"] = all_pass
    return out


def fit_statistics(residuals: Sequence[np.ndarray]) -> dict[str, Any]:
    """T28 estimation：mean=sum/n，sample_covariance=centered.T@centered/(n-1)，无正则、无求逆。

    rank 上限由样本数得出（min(n-1, 7)），不写死；本函数不产生任何"噪声模型已注册"之类的结论。
    """
    x = np.asarray(residuals, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 7 or x.shape[0] < 2:
        raise ValueError("need >=2 fit residual vectors of dimension 7")
    if not np.isfinite(x).all():
        raise ValueError("non-finite fit residuals")
    mean = x.sum(axis=0) / x.shape[0]
    centered = x - mean
    cov = (centered.T @ centered) / (x.shape[0] - 1)
    tol = 1e-10
    return {
        "n_fit": int(x.shape[0]),
        "mean": mean.tolist(),
        "covariance": cov.tolist(),
        "diagonal_descriptive_only": np.diag(cov).tolist(),
        "rank": int(np.linalg.matrix_rank(cov, tol=tol)),
        "rank_tol": tol,
        "rank_ceiling": int(min(x.shape[0] - 1, 7)),
        "regularization": "none",
    }
