"""S5 评测汇总。

``evaluate`` 调用 ``train.predict`` 再交给 ``metrics``。``per_world_stat`` 只依赖预测数组，
供 ``metrics.paired_world_bootstrap`` 在抽到的世界上重算同一指标的差值。世界被抽中多次时，
段按 ``expand_world_index`` 重复计入。
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from ainerzero.v9.experiments.s5 import metrics
from ainerzero.v9.experiments.s5.data import ClipIndex, load_item
from ainerzero.v9.experiments.s5.tokens import rlt_keep

SCALAR_METRICS = (
    "r2_ap",
    "r3_ap",
    "r2_ap_near",
    "r2_ap_mid",
    "r2_ap_far",
    "r3_ap_near",
    "r3_ap_mid",
    "r3_ap_far",
    "r1_rmse",
    "r1_rmse_object",
    "r1_rmse_floor",
    "ordering_all",
    "keep_rate",
)


def _reorder_by_world(world_ids: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
    """把段排成按世界连续的块，返回 (新下标, 世界原号, 每世界段数)。"""
    order_worlds: list[int] = []
    seen: set[int] = set()
    for raw in world_ids.tolist():
        world = int(raw)
        if world not in seen:
            seen.add(world)
            order_worlds.append(world)
    groups: dict[int, list[int]] = {world: [] for world in order_worlds}
    for index, raw in enumerate(world_ids.tolist()):
        groups[int(raw)].append(index)
    counts = {len(groups[world]) for world in order_worlds}
    if len(counts) != 1:
        raise ValueError(f"each world needs the same number of clips, got {counts}")
    clips_per_world = int(next(iter(counts)))
    order: list[int] = []
    for world in order_worlds:
        order.extend(groups[world])
    return np.asarray(order, dtype=np.int64), np.asarray(order_worlds, dtype=np.int64), clips_per_world


def _take(array: np.ndarray, clips: np.ndarray) -> np.ndarray:
    return np.asarray(array)[np.asarray(clips, dtype=np.int64)]


def _take_list(rows: list[Any], clips: np.ndarray) -> list[Any]:
    return [rows[int(i)] for i in np.asarray(clips, dtype=np.int64)]


def metric_value(ev: dict[str, Any], clips: np.ndarray, metric: str) -> float:
    """在给定段下标（可重复）上重算一个标量指标。"""
    if metric not in SCALAR_METRICS:
        raise ValueError(f"unknown metric {metric!r}; expected one of {SCALAR_METRICS}")
    clips = np.asarray(clips, dtype=np.int64)
    if metric == "keep_rate":
        per_clip = ev.get("keep_rate_per_clip")
        if per_clip is None:
            return float("nan")
        return float(np.mean(_take(per_clip, clips)))
    if metric == "r2_ap":
        return float(metrics.grid_ap(_take(ev["r2_logit"], clips), _take(ev["r2"], clips)))
    if metric == "r3_ap":
        return float(metrics.grid_ap(_take(ev["r3_logit"], clips), _take(ev["r3"], clips)))
    if metric.startswith("r2_ap_") or metric.startswith("r3_ap_"):
        which, _, group = metric.partition("_ap_")
        scores = _take(ev[f"{which}_logit"], clips)
        targets = _take(ev[which], clips)
        grouped = metrics.grid_ap_by_distance(scores, targets)
        return float(grouped[group])
    pred_logd = _take(ev["r1_logd"], clips)
    target_logd = _take(ev["r1_target"], clips)
    if metric == "r1_rmse":
        return float(metrics.logd_rmse(pred_logd, target_logd))
    if metric == "r1_rmse_object":
        return float(metrics.logd_rmse(pred_logd, target_logd, obj=_take(ev["r1_obj"], clips), split="object"))
    if metric == "r1_rmse_floor":
        return float(
            metrics.logd_rmse(
                pred_logd,
                target_logd,
                sky=_take(ev["r1_sky"], clips),
                obj=_take(ev["r1_obj"], clips),
                split="floor",
            )
        )
    pred_last = pred_logd[:, -1]
    ordering = metrics.ordering_accuracy(
        pred_last,
        _take_list(ev["ordering_pairs"], clips),
        _take_list(ev["disk_groups"], clips),
    )
    return float(ordering["all"][1])


def paired_group_stat(
    group_a: list[dict[str, Any]],
    group_b: list[dict[str, Any]],
    metric: str,
) -> Callable[[np.ndarray], float]:
    """多个种子先在同一批段上各自重算，再取平均，然后做 A 减 B。"""
    if not group_a or not group_b:
        raise ValueError("both groups need at least one eval")
    clips_per_world = int(group_a[0]["clips_per_world"])
    groups = (*group_a, *group_b)
    if any(int(ev["clips_per_world"]) != clips_per_world for ev in groups):
        raise ValueError("clips_per_world mismatch")

    def stat(world_idx: np.ndarray) -> float:
        clips = metrics.expand_world_index(world_idx, clips_per_world=clips_per_world)
        mean_a = sum(metric_value(ev, clips, metric) for ev in group_a) / len(group_a)
        mean_b = sum(metric_value(ev, clips, metric) for ev in group_b) / len(group_b)
        return float(mean_a - mean_b)

    return stat


def per_world_stat(
    eval_a: dict[str, Any],
    eval_b: dict[str, Any],
    metric: str,
) -> Callable[[np.ndarray], float]:
    """返回 ``stat(world_idx) = metric(A) - metric(B)``，两边都只在这些世界上重算。

    ``world_idx`` 里的重复世界会经 ``metrics.expand_world_index`` 变成重复的段。
    """
    clips_per_world = int(eval_a["clips_per_world"])
    if int(eval_b["clips_per_world"]) != clips_per_world:
        raise ValueError("eval_a and eval_b clips_per_world differ")

    def stat(world_idx: np.ndarray) -> float:
        clips = metrics.expand_world_index(world_idx, clips_per_world=clips_per_world)
        return float(metric_value(eval_a, clips, metric) - metric_value(eval_b, clips, metric))

    return stat


def _summarize(ev: dict[str, Any], threshold: float) -> dict[str, Any]:
    clips = np.arange(ev["r2"].shape[0], dtype=np.int64)
    recall_r2 = metrics.disk_recall(ev["r2_logit"], ev["disk_groups"], threshold, "occlusion_group")
    recall_dist = metrics.disk_recall(ev["r2_logit"], ev["disk_groups"], threshold, "distance_group")
    ordering = metrics.ordering_accuracy(
        ev["r1_logd"][:, -1],
        ev["ordering_pairs"],
        ev["disk_groups"],
    )
    summary = {
        "r2_ap": metric_value(ev, clips, "r2_ap"),
        "r3_ap": metric_value(ev, clips, "r3_ap"),
        "r2_ap_by_distance": metrics.grid_ap_by_distance(ev["r2_logit"], ev["r2"]),
        "r3_ap_by_distance": metrics.grid_ap_by_distance(ev["r3_logit"], ev["r3"]),
        "r2_recall_occlusion": recall_r2,
        "r2_recall_distance": recall_dist,
        "r1_rmse": metric_value(ev, clips, "r1_rmse"),
        "r1_rmse_object": metric_value(ev, clips, "r1_rmse_object"),
        "r1_rmse_floor": metric_value(ev, clips, "r1_rmse_floor"),
        "ordering_accuracy": ordering,
        "threshold": float(threshold),
    }
    if ev.get("keep_rate_per_clip") is not None:
        summary["keep_rate"] = float(np.mean(ev["keep_rate_per_clip"]))
    return summary


def evaluate(student: Any, heads: Any, index: ClipIndex, *, tau: float | None = None, threshold: float = 0.5) -> dict[str, Any]:
    """逐段预测后计算 R1/R2/R3、召回、次序，以及可选的 RLT keep 率。

    返回的预测和标签已按世界排成连续段，``world_ids[k]`` 对应段 ``[k*clips_per_world, (k+1)*clips_per_world)``。
    """
    from ainerzero.v9.experiments.s5.train import predict

    predicted = predict(student, heads, index, tau=tau)
    r1_target, r1_sky, r1_obj = [], [], []
    r2, r3 = [], []
    disks, pairs = [], []
    worlds = []
    keep_rates = []
    for i in range(len(index)):
        item = load_item(index, i)
        worlds.append(int(item["world"]))
        r1_target.append(np.asarray(item["r1_logd"]))
        r1_sky.append(np.asarray(item["r1_sky"]))
        r1_obj.append(np.asarray(item["r1_obj"]))
        r2.append(np.asarray(item["r2"]))
        r3.append(np.asarray(item["r3"]))
        disks.append(item["disk_groups"])
        pairs.append(item["ordering_pairs"])
        if tau is not None:
            kept, _run_len = rlt_keep(item["patches"], tau)
            keep_rates.append(float(np.mean(kept)))

    order, world_ids, clips_per_world = _reorder_by_world(np.asarray(worlds, dtype=np.int64))
    ev: dict[str, Any] = {
        "r1_logd": np.asarray(predicted["r1_logd"])[order],
        "r2_logit": np.asarray(predicted["r2_logit"])[order],
        "r3_logit": np.asarray(predicted["r3_logit"])[order],
        "r1_target": np.stack(r1_target, axis=0)[order],
        "r1_sky": np.stack(r1_sky, axis=0)[order],
        "r1_obj": np.stack(r1_obj, axis=0)[order],
        "r2": np.stack(r2, axis=0)[order],
        "r3": np.stack(r3, axis=0)[order],
        "disk_groups": [disks[int(i)] for i in order],
        "ordering_pairs": [pairs[int(i)] for i in order],
        "world_ids": world_ids,
        "clips_per_world": clips_per_world,
        "threshold": float(threshold),
        "tau": tau,
    }
    if tau is not None:
        ev["keep_rate_per_clip"] = np.asarray(keep_rates, dtype=np.float64)[order]
    ev["metrics"] = _summarize(ev, threshold)
    return ev
