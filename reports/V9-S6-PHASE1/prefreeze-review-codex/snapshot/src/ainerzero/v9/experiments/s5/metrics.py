"""S5 评测指标与统计分析模块（纯 CPU / NumPy）。

依据 reports/V9-S5-DESIGN/DESIGN-r1.md §4、§5 与末尾补记规范实现：
1. grid_ap: 微平均网格平均精度（AP），并列时负例排前（保守口径）；
2. grid_ap_by_distance: 按距离网格分组计算 AP（near, mid, far）；
3. disk_recall: 按遮挡组或距离组计算圆盘二值占据召回率；
4. logd_rmse: R1 对数深度 RMSE，支持全图、物体块、地面块分组切分；
5. ordering_accuracy: 前后次序准确率，比较中心 patch 预测深度；
6. steps_to_target / steps_to_target_stair: 达到目标 AP 的步数（线性插值 / 阶梯式），支持删失；
7. ga_decision: 对齐加速 GA 门判定分析与多度量中位数比值；
8. paired_world_bootstrap: 世界级配对自助法置信区间估计。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

import numpy as np

AZIMUTH_BINS: int = 12
DISTANCE_BINS: int = 7
DIST_MIN: float = 0.5
DIST_MAX: float = 7.0

# 距离格边界：exp(linspace(log 0.5, log 7.0, 8))
# 约为 [0.5, 0.729, 1.062, 1.549, 2.259, 3.293, 4.803, 7.0]
DIST_BIN_EDGES = np.exp(np.linspace(np.log(DIST_MIN), np.log(DIST_MAX), DISTANCE_BINS + 1))

# 距离分组定义：
# near: 第 0–3 格 (< 2.259 m)
# mid: 第 4–5 格 (2.259–4.803 m)
# far: 第 6 格 (> 4.803 m)
# 注：设计稿中的「< 2、2–4、> 4 m」是圆盘级连续几何分组，这里网格只能按格边界取近似。
DISTANCE_GRID_GROUPS: dict[str, tuple[int, int]] = {
    "near": (0, 4),
    "mid": (4, 6),
    "far": (6, 7),
}


def grid_ap(scores: np.ndarray, targets: np.ndarray) -> float:
    """计算拉平后的微平均平均精度（Average Precision, AP）。

    参数：
        scores: 任意实数数组（如 logit 或概率），可为 [N, 12, 7] 或任意维度。
        targets: 与 scores 形状一致的二值标签（0 或 1）。

    返回：
        float: 微平均 AP。若无正例（所有 target 为 0）则返回 float("nan")。

    并列处理：
        先按分数降序排序。当分数相等时，负例（target=0）排在正例（target=1）前面。
        这是保守口径，可避免同分预测虚高正例排位。
    """
    s_flat = np.asarray(scores, dtype=np.float64).ravel()
    t_flat = np.asarray(targets, dtype=np.int64).ravel()
    if s_flat.shape != t_flat.shape:
        raise ValueError(f"scores shape {scores.shape} != targets shape {targets.shape}")

    num_pos = int(np.sum(t_flat == 1))
    if num_pos == 0:
        return float("nan")

    # 保守并列口径：先按 -scores 升序（即 scores 降序），同分时 targets 升序（0 排在 1 前面）
    order = np.lexsort((t_flat, -s_flat))
    sorted_targets = t_flat[order]

    cum_tp = np.cumsum(sorted_targets)
    ranks = np.arange(1, len(sorted_targets) + 1, dtype=np.float64)
    precisions = cum_tp / ranks

    pos_mask = (sorted_targets == 1)
    return float(np.mean(precisions[pos_mask]))


def grid_ap_by_distance(scores: np.ndarray, targets: np.ndarray) -> dict[str, float]:
    """按距离格分组计算微平均 AP。

    距离格按边界 exp(linspace(log 0.5, log 7, 8)) 分三组：
    - near: 第 0–3 格（< 2.26 m）
    - mid: 第 4–5 格（2.26–4.80 m）
    - far: 第 6 格（> 4.80 m）

    注：设计稿中的「< 2、2–4、> 4 m」是圆盘级连续几何分组，这里网格只能按格边界取近似。

    参数：
        scores: [N, 12, 7] 评分
        targets: [N, 12, 7] 目标

    返回：
        dict: {"near": ap_near, "mid": ap_mid, "far": ap_far}
    """
    scores = np.asarray(scores)
    targets = np.asarray(targets)
    if scores.shape[-1] != DISTANCE_BINS:
        raise ValueError(f"expected last dimension {DISTANCE_BINS}, got {scores.shape}")

    res = {}
    for grp, (d_start, d_end) in DISTANCE_GRID_GROUPS.items():
        sub_s = scores[..., d_start:d_end]
        sub_t = targets[..., d_start:d_end]
        res[grp] = grid_ap(sub_s, sub_t)
    return res


def disk_recall(
    scores: np.ndarray,
    disk_groups: list[list[dict[str, Any]]],
    threshold: float,
    key: str,
) -> dict[str, tuple[int, int, float]]:
    """按分组属性计算圆盘二值占据召回率。

    每个圆盘在其 (azimuth_bin, distance_bin) 格上，若 sigmoid(score) >= threshold 记为命中。
    按 key（"occlusion_group" 或 "distance_group"）分组，统计命中数、总数与召回率。

    参数：
        scores: [N, 12, 7] 或 [12, 7] 评分实数（取 sigmoid 与 threshold 比较）
        disk_groups: 逐段的圆盘属性字典列表（list of list of dict）
        threshold: 命中阈值（0.0 到 1.0）
        key: 分组字段名，如 "occlusion_group" 或 "distance_group"

    返回：
        dict: {组名: (命中数, 总数, 召回率)}
    """
    s_arr = np.asarray(scores, dtype=np.float64)
    if s_arr.ndim == 2:
        s_arr = s_arr[None, ...]
        disk_groups = [disk_groups]  # type: ignore

    n_clips = len(disk_groups)
    if s_arr.shape[0] != n_clips:
        raise ValueError(f"scores clips {s_arr.shape[0]} != disk_groups len {n_clips}")

    counts: dict[str, list[int]] = {}
    if key == "occlusion_group":
        counts = {"full": [0, 0], "partial": [0, 0]}
    elif key == "distance_group":
        counts = {"< 2": [0, 0], "2–4": [0, 0], "> 4": [0, 0]}

    for c_idx in range(n_clips):
        for disk in disk_groups[c_idx]:
            grp = str(disk.get(key, "unknown"))
            if grp not in counts:
                counts[grp] = [0, 0]

            az = int(disk["azimuth_bin"])
            db = int(disk["distance_bin"])
            val = float(s_arr[c_idx, az, db])
            prob = 1.0 / (1.0 + math.exp(-max(min(val, 60.0), -60.0)))

            is_hit = (prob >= threshold)
            counts[grp][1] += 1
            if is_hit:
                counts[grp][0] += 1

    out: dict[str, tuple[int, int, float]] = {}
    for grp, (hit, tot) in counts.items():
        rec = float(hit / tot) if tot > 0 else float("nan")
        out[grp] = (hit, tot, rec)
    return out


def logd_rmse(
    pred: np.ndarray,
    target: np.ndarray,
    *,
    sky: np.ndarray | None = None,
    obj: np.ndarray | None = None,
    split: str | None = None,
) -> float:
    """计算 R1 非天空块对数深度均方根误差（RMSE）。

    参数：
        pred: [N, 16, 14, 14] 预测对数深度
        target: [N, 16, 14, 14] 真值对数深度（纯天空块为 nan，不计入）
        sky: 可选 [N, 16, 14, 14] 天空占比
        obj: 可选 [N, 16, 14, 14] 物体占比
        split: 切分选项，None 表示全部有效块；
               "object": obj >= 0.5 的块；
               "floor": 1 - sky - obj >= 0.5 的块。

    返回：
        float: RMSE。若无符合条件的块则返回 float("nan")。
    """
    p = np.asarray(pred, dtype=np.float64)
    t = np.asarray(target, dtype=np.float64)
    if p.shape != t.shape:
        raise ValueError(f"pred shape {p.shape} != target shape {t.shape}")

    valid = np.isfinite(t)

    if split is None:
        mask = valid
    elif split == "object":
        if obj is None:
            raise ValueError("obj must be provided when split='object'")
        o_arr = np.asarray(obj, dtype=np.float64)
        mask = valid & (o_arr >= 0.5)
    elif split == "floor":
        if sky is None or obj is None:
            raise ValueError("both sky and obj must be provided when split='floor'")
        s_arr = np.asarray(sky, dtype=np.float64)
        o_arr = np.asarray(obj, dtype=np.float64)
        floor = 1.0 - s_arr - o_arr
        mask = valid & (floor >= 0.5)
    else:
        raise ValueError(f"unknown split {split!r}; expected None, 'object', or 'floor'")

    if not np.any(mask):
        return float("nan")

    diff = p[mask] - t[mask]
    return float(np.sqrt(np.mean(diff ** 2)))


def ordering_accuracy(
    pred_logd_last: np.ndarray,
    pairs: list[list[dict[str, Any]]],
    disk_groups: list[list[dict[str, Any]]],
) -> dict[str, tuple[int, float]]:
    """计算段末帧成对前后次序判断准确率。

    规则：
    - 比较两对象各自 patch 处的预测对数深度，预测值较小者判定为较近。
    - 若两处预测深度相等，判定为错误。
    - 真值为 "equal" 的样本对不计入。
    - 按 type ("disk_disk", "disk_pillar") 分组；
    - 再按遮挡组分组：只要对里有一个圆盘的遮挡组为 "partial"，该对即归为 "partial"，否则为 "full"。
      圆盘编号 id - 100 对应 disk_groups 中的 disk_id。

    参数：
        pred_logd_last: [N, 14, 14] 每段最后一帧的预测对数深度
        pairs: 逐段的 ordering_pairs 列表（list of list of dict）
        disk_groups: 逐段的 disk_groups 列表（list of list of dict）

    返回：
        dict: 各组的 (样本对数, 准确率)
              包含 "all", "disk_disk", "disk_pillar", "full", "partial",
              以及复合组 "disk_disk_full", "disk_disk_partial", "disk_pillar_full", "disk_pillar_partial"。
    """
    preds = np.asarray(pred_logd_last, dtype=np.float64)
    if preds.ndim == 2:
        preds = preds[None, ...]
        pairs = [pairs]  # type: ignore
        disk_groups = [disk_groups]  # type: ignore

    n_clips = len(pairs)
    if preds.shape[0] != n_clips:
        raise ValueError(f"preds len {preds.shape[0]} != pairs len {n_clips}")

    group_keys = [
        "all",
        "disk_disk",
        "disk_pillar",
        "full",
        "partial",
        "disk_disk_full",
        "disk_disk_partial",
        "disk_pillar_full",
        "disk_pillar_partial",
    ]
    counts: dict[str, list[int]] = {k: [0, 0] for k in group_keys}

    for c_idx in range(n_clips):
        clip_disks = disk_groups[c_idx] if c_idx < len(disk_groups) else []
        disk_occ = {int(d["disk_id"]): str(d.get("occlusion_group", "full")) for d in clip_disks}

        for pair in pairs[c_idx]:
            closer = pair.get("closer")
            if closer == "equal":
                continue  # 真值为 "equal" 的对不计

            p_type = str(pair.get("type", "unknown"))
            r_a, c_a = pair["patch_a"]
            r_b, c_b = pair["patch_b"]

            z_pred_a = float(preds[c_idx, r_a, c_a])
            z_pred_b = float(preds[c_idx, r_b, c_b])

            if math.isnan(z_pred_a) or math.isnan(z_pred_b) or z_pred_a == z_pred_b:
                pred_closer = None
            elif z_pred_a < z_pred_b:
                pred_closer = "a"
            else:
                pred_closer = "b"

            is_correct = (pred_closer is not None and pred_closer == closer)

            # 遮挡组判定：只要对里有一个圆盘是 partial，即为 partial
            # id - 100 对应 disk_id
            id_a = int(pair["id_a"])
            id_b = int(pair["id_b"])
            occ_a = disk_occ.get(id_a - 100, "full")
            if p_type == "disk_disk":
                occ_b = disk_occ.get(id_b - 100, "full")
                occ_group = "partial" if (occ_a == "partial" or occ_b == "partial") else "full"
            else:
                # disk_pillar：柱子没有遮挡组，只看圆盘
                occ_group = "partial" if (occ_a == "partial") else "full"

            matched_tags = ["all", p_type, occ_group, f"{p_type}_{occ_group}"]
            for tag in matched_tags:
                if tag not in counts:
                    counts[tag] = [0, 0]
                counts[tag][1] += 1
                if is_correct:
                    counts[tag][0] += 1

    out: dict[str, tuple[int, float]] = {}
    for tag, (correct, total) in counts.items():
        acc = float(correct / total) if total > 0 else float("nan")
        out[tag] = (total, acc)
    return out


def steps_to_target(
    steps: Sequence[float] | np.ndarray,
    ap: Sequence[float] | np.ndarray,
    target: float,
    cap: float,
) -> tuple[float, bool]:
    """计算达到目标 AP 的步数（线性插值）。

    - 若首个检查点即达标 (ap[0] >= target)，返回 (steps[0], False)；
    - 若在第 j 个检查点首次达标，在 (steps[j-1], ap[j-1]) 与 (steps[j], ap[j]) 之间线性插值；
    - 若全序列未达标，返回 (cap, True)，第二项表示删失 (censored)。

    参数：
        steps: 严格递增的检查点步数序列
        ap: 对应检查点的 AP 序列
        target: 达标阈值
        cap: 步数上限

    返回：
        tuple[float, bool]: (达标步数, 是否删失)
    """
    s_arr = np.asarray(steps, dtype=np.float64)
    a_arr = np.asarray(ap, dtype=np.float64)
    if len(s_arr) != len(a_arr) or len(s_arr) == 0:
        raise ValueError("steps and ap must be non-empty and of equal length")

    hits = np.where(a_arr >= target)[0]
    if len(hits) == 0:
        return float(cap), True

    j = int(hits[0])
    if j == 0:
        return float(s_arr[0]), False

    s_prev, a_prev = s_arr[j - 1], a_arr[j - 1]
    s_curr, a_curr = s_arr[j], a_arr[j]
    denom = a_curr - a_prev
    if denom == 0.0:
        return float(s_curr), False

    ratio = (target - a_prev) / denom
    interp_step = s_prev + ratio * (s_curr - s_prev)
    return float(interp_step), False


def steps_to_target_stair(
    steps: Sequence[float] | np.ndarray,
    ap: Sequence[float] | np.ndarray,
    target: float,
    cap: float,
) -> tuple[float, bool]:
    """阶梯版达标步数：取首次达标检查点的 steps[j]，不进行插值（仅作描述报告）。"""
    s_arr = np.asarray(steps, dtype=np.float64)
    a_arr = np.asarray(ap, dtype=np.float64)
    if len(s_arr) != len(a_arr) or len(s_arr) == 0:
        raise ValueError("steps and ap must be non-empty and of equal length")

    hits = np.where(a_arr >= target)[0]
    if len(hits) == 0:
        return float(cap), True
    return float(s_arr[hits[0]]), False


def ga_decision(
    a0_curves: Sequence[tuple[Sequence[float] | np.ndarray, Sequence[float] | np.ndarray]],
    a4_curves: Sequence[tuple[Sequence[float] | np.ndarray, Sequence[float] | np.ndarray]],
    cap: float,
) -> dict[str, Any]:
    """对齐加速 GA 门判定分析。

    依据 DESIGN-r1 §4：
    - 达标线 = 0.95 × A0 三条曲线末次检查点 R2 AP 的中位数；
    - 两臂各自取三个种子步数的中位数；
    - passed = median(A4) <= 0.7 × median(A0)；
    - 另返回不插值的阶梯版分析。
    """
    if len(a0_curves) != 3 or len(a4_curves) != 3:
        raise ValueError(f"expected 3 curves per arm, got a0={len(a0_curves)}, a4={len(a4_curves)}")

    a0_last_aps = [float(curve[1][-1]) for curve in a0_curves]
    a0_last_median = float(np.median(a0_last_aps))
    target_ap = float(0.95 * a0_last_median)

    # 线性插值版
    a0_res = [steps_to_target(s, a, target_ap, cap) for s, a in a0_curves]
    a0_steps = [r[0] for r in a0_res]
    a0_censored = [r[1] for r in a0_res]

    a4_res = [steps_to_target(s, a, target_ap, cap) for s, a in a4_curves]
    a4_steps = [r[0] for r in a4_res]
    a4_censored = [r[1] for r in a4_res]

    median_a0 = float(np.median(a0_steps))
    median_a4 = float(np.median(a4_steps))
    ratio = float(median_a4 / median_a0) if median_a0 > 0 else float("inf")
    passed = bool(median_a4 <= 0.7 * median_a0)

    # 阶梯版
    a0_stair_res = [steps_to_target_stair(s, a, target_ap, cap) for s, a in a0_curves]
    a4_stair_res = [steps_to_target_stair(s, a, target_ap, cap) for s, a in a4_curves]
    stair_a0_steps = [r[0] for r in a0_stair_res]
    stair_a0_censored = [r[1] for r in a0_stair_res]
    stair_a4_steps = [r[0] for r in a4_stair_res]
    stair_a4_censored = [r[1] for r in a4_stair_res]

    stair_median_a0 = float(np.median(stair_a0_steps))
    stair_median_a4 = float(np.median(stair_a4_steps))
    stair_ratio = float(stair_median_a4 / stair_median_a0) if stair_median_a0 > 0 else float("inf")
    stair_passed = bool(stair_median_a4 <= 0.7 * stair_median_a0)

    return {
        "target_ap": target_ap,
        "a0_last_median": a0_last_median,
        "a0_last_aps": a0_last_aps,
        "a0_steps": a0_steps,
        "a0_censored": a0_censored,
        "a4_steps": a4_steps,
        "a4_censored": a4_censored,
        "median_a0": median_a0,
        "median_a4": median_a4,
        "ratio": ratio,
        "passed": passed,
        "stair": {
            "a0_steps": stair_a0_steps,
            "a0_censored": stair_a0_censored,
            "a4_steps": stair_a4_steps,
            "a4_censored": stair_a4_censored,
            "median_a0": stair_median_a0,
            "median_a4": stair_median_a4,
            "ratio": stair_ratio,
            "passed": stair_passed,
        },
    }


def expand_world_index(
    world_indices: Sequence[int] | np.ndarray,
    clips_per_world: int = 16,
) -> np.ndarray:
    """展开抽样的世界索引为段索引序列。

    若某个世界被重复抽中多次，其包含的所有段将重复计入。

    参数：
        world_indices: 世界索引序列 [W]
        clips_per_world: 每个世界的段数，默认为 16

    返回：
        np.ndarray: [W * clips_per_world] 段索引序列
    """
    w_arr = np.asarray(world_indices, dtype=np.int64)
    offsets = np.arange(clips_per_world, dtype=np.int64)
    return (w_arr[:, None] * clips_per_world + offsets[None, :]).ravel()


def paired_world_bootstrap(
    n_worlds: int,
    stat_fn: Callable[[np.ndarray], float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> dict[str, Any]:
    """世界级配对自助法置信区间估计。

    依据 DESIGN-r1 §4：
    - 以 final 的世界为单位有放回抽样；
    - 同一世界的段一起抽（调用方在 stat_fn 中根据世界索引重算或索引统计量）；
    - 返回点估计（全部世界）、等尾分位数置信区间 [lo, hi]。
    - 当使用 Bonferroni 校正时，由调用方传入 level = 1 - 0.05 / 3 (约 0.9833)。

    参数：
        n_worlds: 世界总数
        stat_fn: 统计量计算函数，接收形状为 [n_worlds] 的世界索引数组，返回标量统计值
        n_boot: 自助重抽样次数，默认 2000
        seed: 随机数发生器种子，默认 0
        level: 置信水平，默认 0.95

    返回：
        dict: 包含 point_estimate, ci, ci_lower, ci_upper, level, n_boot, seed, n_nan 等字段。

    nan 行为：
        若某次重抽上 stat_fn 返回 nan（例如抽到的世界里一个正例都没有），
        该次计入 n_nan。区间仍用 np.percentile，不用 nanpercentile，也不丢弃这些重抽。
        因此只要 n_nan > 0，np.percentile 会把 ci_lower 与 ci_upper 都变成 nan。
    """
    if n_worlds <= 0:
        raise ValueError(f"n_worlds must be > 0, got {n_worlds}")
    if not (0.0 < level < 1.0):
        raise ValueError(f"level must be in (0, 1), got {level}")

    all_worlds = np.arange(n_worlds, dtype=np.int64)
    point_est = float(stat_fn(all_worlds))

    rng = np.random.default_rng(seed)
    boot_vals = np.empty(n_boot, dtype=np.float64)

    for b in range(n_boot):
        boot_idx = rng.choice(n_worlds, size=n_worlds, replace=True)
        boot_vals[b] = stat_fn(boot_idx)

    alpha = 1.0 - level
    # 等尾区间：下界分位是 alpha/2，上界是 1 - alpha/2。含 nan 时 percentile 传播为 nan。
    lo = float(np.percentile(boot_vals, 100.0 * (alpha / 2.0)))
    hi = float(np.percentile(boot_vals, 100.0 * (1.0 - alpha / 2.0)))
    n_nan = int(np.isnan(boot_vals).sum())

    return {
        "point_estimate": point_est,
        "ci": (lo, hi),
        "ci_lower": lo,
        "ci_upper": hi,
        "level": float(level),
        "n_boot": int(n_boot),
        "seed": int(seed),
        "n_nan": n_nan,
        "bootstrap_std": float(np.std(boot_vals)),
    }
