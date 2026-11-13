#!/usr/bin/env python3
"""S5 登记运行独立复算（P246）。

只读登记运行目录的 ``metrics/*.npz`` / JSON 与 ``PREREG.json``，
重算 GT1/GT2/GT3/GA/GR 与只报告项，写出 ``recompute.json``，并与
``gates.json`` 逐项比对（差 > 1e-9 列出）。

不 import ``run_s5p1_final.py`` / ``run_s5p1.py``。
指标可调用 ``ainerzero.v9.experiments.s5.metrics``；另附 R2 AP / R1 RMSE
的最小独立实现，供合成数据逐值核对。

契约（相对 SPEC §2.2 与补记 1；若 P245 落盘不符，以本契约为准并在报告列出）：

分区名从 PREREG ``frozen.partitions`` 读取（``final`` / ``final_shift``），
不把登记分区写死成 ``s5p1-final``。换域只报告项另读
``{final_shift}.shift_bg`` 与 ``{final_shift}.shift_all``。

metrics 文件名：``{model_id}.{partition}.npz``
  数组键：r1_logd, r2_logit, r3_logit, r1_target, r1_sky, r1_obj, r2, r3,
          world_ids, clips_per_world；可选 keep_rate_per_clip
同 stem 的 ``.disk_groups.json`` / ``.ordering_pairs.json`` 可选。

model_id：
  heads-{arm}-d{d}-L{L}-r{r}     arm ∈ {A1,A2,A3,C-sh,R,A*}
  {arm}-L{L}-s{s}                arm ∈ {A0,A4,A0-R,FT}
  ckpt-{arm}-L{L}-s{s}           GA 曲线：另含 steps / r2_ap 的同名 .json

墙钟：``timing/{cell_id}.json``，含 ``seconds_per_step``（标量或序列）。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

# ---------------------------------------------------------------------------
# 独立最小实现（与生产 metrics 逐值核对）
# ---------------------------------------------------------------------------


def independent_grid_ap(scores: np.ndarray, targets: np.ndarray) -> float:
    """R2 微平均 AP：分数降序，同分时负例在前（保守并列）。"""
    s = np.asarray(scores, dtype=np.float64).ravel()
    t = np.asarray(targets, dtype=np.int64).ravel()
    if s.shape != t.shape:
        raise ValueError(f"shape mismatch {s.shape} vs {t.shape}")
    n_pos = int(np.sum(t == 1))
    if n_pos == 0:
        return float("nan")
    order = np.lexsort((t, -s))
    sorted_t = t[order]
    cum_tp = np.cumsum(sorted_t)
    ranks = np.arange(1, len(sorted_t) + 1, dtype=np.float64)
    prec = cum_tp / ranks
    return float(np.mean(prec[sorted_t == 1]))


def independent_logd_rmse(
    pred: np.ndarray,
    target: np.ndarray,
    *,
    sky: np.ndarray | None = None,
) -> float:
    """R1 非天空块对数深度 RMSE；target 非有限（含纯天空 nan）不计入。"""
    p = np.asarray(pred, dtype=np.float64)
    t = np.asarray(target, dtype=np.float64)
    if p.shape != t.shape:
        raise ValueError(f"shape mismatch {p.shape} vs {t.shape}")
    mask = np.isfinite(t)
    if sky is not None:
        # 独立路径只按 target 有限性过滤；sky 参数保留以对齐调用方签名。
        _ = np.asarray(sky, dtype=np.float64)
    if not np.any(mask):
        return float("nan")
    diff = p[mask] - t[mask]
    return float(np.sqrt(np.mean(diff ** 2)))


# ---------------------------------------------------------------------------
# 常量与门阈值（可被 PREREG 覆盖）
# ---------------------------------------------------------------------------

BONFERRONI_M = 3
GT_LEVEL = 1.0 - 0.05 / BONFERRONI_M  # ≈ 0.983333...
GR_AP_LEVEL = 0.95
GT1_EFFECT = 0.05
GT2_EFFECT = 0.03
GT3_MARGIN_FRAC = 0.05
GA_TARGET_FRAC = 0.95
GA_RATIO_MAX = 0.7
GR_KEEP_MAX = 0.8
GR_WALL_DROP_MIN = 0.15
GR_AP_DROP_CI_MAX = 0.03
COMPARE_TOL = 1e-9
THRESHOLD_TOL = 1e-12
# 设计 r1 常量。审核用字面量，不跟可被改写的 GT_* 默认值走。
DESIGN_GT_LEVEL = 1.0 - 0.05 / 3.0
DESIGN_GT1_EFFECT = 0.05
DESIGN_GT2_EFFECT = 0.03
DESIGN_GT3_MARGIN_FRAC = 0.05
DESIGN_GA_TARGET_FRAC = 0.95
DESIGN_GA_RATIO_MAX = 0.7
DESIGN_GR_KEEP_MAX = 0.8
DESIGN_GR_WALL_DROP_MIN = 0.15
DESIGN_GR_AP_DROP_CI_MAX = 0.03
DESIGN_GR_AP_LEVEL = 0.95
DEFAULT_FINAL_PARTITION = "s5p1-final"
DEFAULT_SHIFT_PARTITION = "s5p1-final-shift"

HEADS_RE = re.compile(
    r"^heads-(?P<arm>A1|A2|A3|C-sh|R|A\*)-d(?P<d>\d+)-L(?P<L>\d+)-r(?P<r>\d+)$"
)
SUP_RE = re.compile(r"^(?P<arm>A0|A4|A0-R|FT)-L(?P<L>\d+)-s(?P<s>\d+)$")
CKPT_RE = re.compile(r"^ckpt-(?P<arm>A0|A4)-L(?P<L>\d+)-s(?P<s>\d+)$")
_MODEL_PREFIXES = (
    re.compile(r"heads-(?:A1|A2|A3|C-sh|R|A\*)-d\d+-L\d+-r\d+"),
    re.compile(r"(?:A0-R|A0|A4|FT)-L\d+-s\d+"),
    re.compile(r"ckpt-(?:A0|A4)-L\d+-s\d+"),
)


# ---------------------------------------------------------------------------
# 种子嵌套平均（可突变对照的关键符号）
# ---------------------------------------------------------------------------


def mean_over_readouts_then_distills(
    values: Mapping[Any, Mapping[Any, float]] | Sequence[Sequence[float]],
) -> float:
    """先在蒸馏种子内平均读出种子，再在蒸馏种子间平均。

    ``values`` 为 ``{distill_seed: {readout_seed: metric}}`` 或等长二维序列。
    这是设计稿规定的顺序；反过来会在非齐备网格上得到不同值。
    """
    if isinstance(values, Mapping):
        distill_means: list[float] = []
        for _d, readout_map in values.items():
            if not readout_map:
                continue
            distill_means.append(float(np.mean(list(readout_map.values()))))
        if not distill_means:
            return float("nan")
        return float(np.mean(distill_means))

    rows = [list(row) for row in values if len(row) > 0]
    if not rows:
        return float("nan")
    return float(np.mean([float(np.mean(row)) for row in rows]))


def mean_over_distills_then_readouts(
    values: Mapping[Any, Mapping[Any, float]],
) -> float:
    """坏对照顺序：先在读出种子内平均蒸馏种子，再在读出种子间平均。"""
    by_readout: dict[Any, list[float]] = {}
    for _d, readout_map in values.items():
        for r, v in readout_map.items():
            by_readout.setdefault(r, []).append(float(v))
    if not by_readout:
        return float("nan")
    return float(np.mean([float(np.mean(vs)) for vs in by_readout.values()]))


# 生产路径绑定正确顺序（突变测试会把这一行改成反向函数名）
SEED_MEAN = mean_over_readouts_then_distills


def seed_std_nested(
    values: Mapping[Any, Mapping[Any, float]],
) -> float:
    """蒸馏级种子间标准差：先平均读出，再对蒸馏均值取样本标准差。"""
    distill_means = []
    for _d, readout_map in values.items():
        if readout_map:
            distill_means.append(float(np.mean(list(readout_map.values()))))
    if len(distill_means) < 2:
        return float("nan")
    return float(np.std(distill_means, ddof=1))


# ---------------------------------------------------------------------------
# 生产 metrics / bootstrap 包装
# ---------------------------------------------------------------------------


def _prod_metrics():
    from ainerzero.v9.experiments.s5 import metrics as M

    return M


def metric_on_clips(ev: Mapping[str, Any], clips: np.ndarray, metric: str) -> float:
    """在给定段下标上重算标量指标（与 evaluate.metric_value 对齐的子集）。"""
    M = _prod_metrics()
    clips = np.asarray(clips, dtype=np.int64)

    def take(key: str) -> np.ndarray:
        return np.asarray(ev[key])[clips]

    if metric == "r2_ap":
        return float(M.grid_ap(take("r2_logit"), take("r2")))
    if metric == "r3_ap":
        return float(M.grid_ap(take("r3_logit"), take("r3")))
    if metric == "r1_rmse":
        return float(M.logd_rmse(take("r1_logd"), take("r1_target")))
    if metric == "keep_rate":
        per = ev.get("keep_rate_per_clip")
        if per is None:
            return float("nan")
        return float(np.mean(np.asarray(per)[clips]))
    if metric.startswith("r2_ap_"):
        group = metric.split("_")[-1]
        return float(M.grid_ap_by_distance(take("r2_logit"), take("r2"))[group])
    raise ValueError(f"unsupported metric {metric!r}")


def nested_group_stat(
    group_by_distill: Mapping[Any, Mapping[Any, Mapping[str, Any]]],
    baseline: Sequence[Mapping[str, Any]] | Mapping[Any, Mapping[str, Any]],
    metric: str,
    *,
    seed_mean: Callable[..., float] = SEED_MEAN,
) -> Callable[[np.ndarray], float]:
    """嵌套种子平均后的配对差：mean_nested(A) - mean(B)。

    ``group_by_distill``: distill -> readout -> eval dict
    ``baseline``: 无蒸馏结构时为 eval 列表；或 seed -> eval
    """
    M = _prod_metrics()
    sample = next(iter(next(iter(group_by_distill.values())).values()))
    cpw = int(sample["clips_per_world"])

    if isinstance(baseline, Mapping):
        base_list = list(baseline.values())
    else:
        base_list = list(baseline)
    if not base_list:
        raise ValueError("baseline group is empty")

    def stat(world_idx: np.ndarray) -> float:
        clips = M.expand_world_index(world_idx, clips_per_world=cpw)
        nested: dict[Any, dict[Any, float]] = {}
        for d, rmap in group_by_distill.items():
            nested[d] = {r: metric_on_clips(ev, clips, metric) for r, ev in rmap.items()}
        mean_a = float(seed_mean(nested))
        mean_b = float(np.mean([metric_on_clips(ev, clips, metric) for ev in base_list]))
        return mean_a - mean_b

    return stat


def flat_group_stat(
    group_a: Sequence[Mapping[str, Any]],
    group_b: Sequence[Mapping[str, Any]],
    metric: str,
) -> Callable[[np.ndarray], float]:
    """两侧都是扁平种子列表时的配对差。"""
    M = _prod_metrics()
    cpw = int(group_a[0]["clips_per_world"])

    def stat(world_idx: np.ndarray) -> float:
        clips = M.expand_world_index(world_idx, clips_per_world=cpw)
        mean_a = float(np.mean([metric_on_clips(ev, clips, metric) for ev in group_a]))
        mean_b = float(np.mean([metric_on_clips(ev, clips, metric) for ev in group_b]))
        return mean_a - mean_b

    return stat


def bootstrap_gate(
    n_worlds: int,
    stat_fn: Callable[[np.ndarray], float],
    *,
    n_boot: int,
    seed: int,
    level: float,
) -> dict[str, Any]:
    M = _prod_metrics()
    return M.paired_world_bootstrap(n_worlds, stat_fn, n_boot=n_boot, seed=seed, level=level)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------


def _load_npz(path: Path) -> dict[str, Any]:
    data = np.load(path, allow_pickle=False)
    ev: dict[str, Any] = {k: data[k] for k in data.files}
    if "clips_per_world" in ev:
        ev["clips_per_world"] = int(np.asarray(ev["clips_per_world"]).reshape(-1)[0])
    else:
        n = int(ev["r2"].shape[0])
        if n % 16 != 0:
            raise ValueError(f"{path.name}: cannot infer clips_per_world from n={n}")
        ev["clips_per_world"] = 16
    stem = path.name[: -len(".npz")]
    # stem = model.partition
    disk_path = path.with_name(stem + ".disk_groups.json")
    ord_path = path.with_name(stem + ".ordering_pairs.json")
    if disk_path.is_file():
        ev["disk_groups"] = json.loads(disk_path.read_text(encoding="utf-8"))
    if ord_path.is_file():
        ev["ordering_pairs"] = json.loads(ord_path.read_text(encoding="utf-8"))
    return ev


def _parse_model(model_id: str) -> dict[str, Any]:
    m = HEADS_RE.match(model_id)
    if m:
        return {
            "kind": "heads",
            "arm": m.group("arm"),
            "distill_seed": int(m.group("d")),
            "label_n": int(m.group("L")),
            "readout_seed": int(m.group("r")),
            "model_id": model_id,
        }
    m = SUP_RE.match(model_id)
    if m:
        return {
            "kind": "supervised",
            "arm": m.group("arm"),
            "label_n": int(m.group("L")),
            "seed": int(m.group("s")),
            "model_id": model_id,
        }
    m = CKPT_RE.match(model_id)
    if m:
        return {
            "kind": "ckpt",
            "arm": m.group("arm"),
            "label_n": int(m.group("L")),
            "seed": int(m.group("s")),
            "model_id": model_id,
        }
    return {"kind": "unknown", "model_id": model_id}


def split_metrics_filename(filename: str) -> tuple[str, str] | None:
    """``{model_id}.{partition}.npz``。partition 可含点（``.shift_bg`` / ``.shift_all``）。"""
    if not filename.endswith(".npz"):
        return None
    stem = filename[: -len(".npz")]
    for rx in _MODEL_PREFIXES:
        m = rx.match(stem)
        if m and m.end() < len(stem) and stem[m.end()] == ".":
            return stem[: m.end()], stem[m.end() + 1 :]
    return None


def resolve_partitions(prereg: Mapping[str, Any]) -> dict[str, str]:
    """从 PREREG ``frozen.partitions`` 读分区名。缺省才用设计稿里的 final 名。"""
    raw = prereg.get("raw") if isinstance(prereg.get("raw"), Mapping) else prereg
    frozen = raw.get("frozen") if isinstance(raw.get("frozen"), Mapping) else {}
    parts = frozen.get("partitions") if isinstance(frozen.get("partitions"), Mapping) else None
    if parts is None and isinstance(raw.get("partitions"), Mapping):
        parts = raw.get("partitions")
    parts = parts or {}
    final = str(parts.get("final") or DEFAULT_FINAL_PARTITION)
    shift = str(parts.get("final_shift") or DEFAULT_SHIFT_PARTITION)
    return {
        "final": final,
        "final_shift": shift,
        "shift_bg": f"{shift}.shift_bg",
        "shift_all": f"{shift}.shift_all",
    }


def _dig(doc: Mapping[str, Any], path: tuple[str, ...]) -> Any:
    cur: Any = doc
    for key in path:
        if not isinstance(cur, Mapping) or key not in cur:
            return None
        cur = cur[key]
    return cur


def audit_prereg_thresholds(doc: Mapping[str, Any]) -> dict[str, Any]:
    """把 PREREG 里出现的阈值与设计 r1 常量逐项核对。

    缺字段不算不一致（运行器可以只写它用到的键）。写了但和设计不符则标红。
    """
    checks: tuple[tuple[str, tuple[str, ...], Any], ...] = (
        ("gates.GT1.effect", ("gates", "GT1", "effect"), DESIGN_GT1_EFFECT),
        ("gates.GT1.min_diff", ("gates", "GT1", "min_diff"), DESIGN_GT1_EFFECT),
        ("gates.GT1.level", ("gates", "GT1", "level"), DESIGN_GT_LEVEL),
        ("gates.GT1.ci_level", ("gates", "GT1", "ci_level"), DESIGN_GT_LEVEL),
        ("gates.GT2.effect", ("gates", "GT2", "effect"), DESIGN_GT2_EFFECT),
        ("gates.GT2.min_diff", ("gates", "GT2", "min_diff"), DESIGN_GT2_EFFECT),
        ("gates.GT2.level", ("gates", "GT2", "level"), DESIGN_GT_LEVEL),
        ("gates.GT2.ci_level", ("gates", "GT2", "ci_level"), DESIGN_GT_LEVEL),
        ("gates.GT3.margin_frac", ("gates", "GT3", "margin_frac"), DESIGN_GT3_MARGIN_FRAC),
        ("gates.GT3.non_inferiority_frac", ("gates", "GT3", "non_inferiority_frac"), DESIGN_GT3_MARGIN_FRAC),
        ("gates.GT3.level", ("gates", "GT3", "level"), DESIGN_GT_LEVEL),
        ("gates.GT3.ci_level", ("gates", "GT3", "ci_level"), DESIGN_GT_LEVEL),
        ("gates.GA.target_frac", ("gates", "GA", "target_frac"), DESIGN_GA_TARGET_FRAC),
        ("gates.GA.target_frac_of_a0_final_median", ("gates", "GA", "target_frac_of_a0_final_median"), DESIGN_GA_TARGET_FRAC),
        ("gates.GA.ratio_max", ("gates", "GA", "ratio_max"), DESIGN_GA_RATIO_MAX),
        ("gates.GA.max_median_step_ratio", ("gates", "GA", "max_median_step_ratio"), DESIGN_GA_RATIO_MAX),
        ("gates.GR.keep_max", ("gates", "GR", "keep_max"), DESIGN_GR_KEEP_MAX),
        ("gates.GR.max_keep_rate", ("gates", "GR", "max_keep_rate"), DESIGN_GR_KEEP_MAX),
        ("gates.GR.wall_drop_min", ("gates", "GR", "wall_drop_min"), DESIGN_GR_WALL_DROP_MIN),
        ("gates.GR.min_distill_step_wall_reduction", ("gates", "GR", "min_distill_step_wall_reduction"), DESIGN_GR_WALL_DROP_MIN),
        ("gates.GR.ap_drop_ci_max", ("gates", "GR", "ap_drop_ci_max"), DESIGN_GR_AP_DROP_CI_MAX),
        ("gates.GR.max_r2_ap_drop_ci95_upper", ("gates", "GR", "max_r2_ap_drop_ci95_upper"), DESIGN_GR_AP_DROP_CI_MAX),
        ("gates.GR.ap_level", ("gates", "GR", "ap_level"), DESIGN_GR_AP_LEVEL),
        ("gates.GR.ci_level", ("gates", "GR", "ci_level"), DESIGN_GR_AP_LEVEL),
        ("gates.family_gt.alpha", ("gates", "family_gt", "alpha"), 0.05),
        ("gates.family_gt.bonferroni_m", ("gates", "family_gt", "bonferroni_m"), 3),
        ("gates.family_gt.ci_level", ("gates", "family_gt", "ci_level"), DESIGN_GT_LEVEL),
        ("gt_level", ("gt_level",), DESIGN_GT_LEVEL),
    )
    mismatches: list[dict[str, Any]] = []
    for name, path, want in checks:
        got = _dig(doc, path)
        if got is None:
            continue
        try:
            same = abs(float(got) - float(want)) <= THRESHOLD_TOL
        except (TypeError, ValueError):
            same = got == want
        if not same:
            mismatches.append({"key": name, "prereg": got, "design": want})
    ok = not mismatches
    return {
        "ok": ok,
        "status": "ok" if ok else "red",
        "n_mismatches": len(mismatches),
        "mismatches": mismatches,
        "design": {
            "GT1_effect": DESIGN_GT1_EFFECT,
            "GT2_effect": DESIGN_GT2_EFFECT,
            "GT3_margin_frac": DESIGN_GT3_MARGIN_FRAC,
            "gt_level": DESIGN_GT_LEVEL,
            "GA_target_frac": DESIGN_GA_TARGET_FRAC,
            "GA_ratio_max": DESIGN_GA_RATIO_MAX,
            "GR_keep_max": DESIGN_GR_KEEP_MAX,
            "GR_wall_drop_min": DESIGN_GR_WALL_DROP_MIN,
            "GR_ap_drop_ci_max": DESIGN_GR_AP_DROP_CI_MAX,
            "GR_ap_level": DESIGN_GR_AP_LEVEL,
        },
    }


def load_run_catalog(run_dir: Path) -> dict[str, Any]:
    metrics_dir = run_dir / "metrics"
    if not metrics_dir.is_dir():
        raise FileNotFoundError(f"missing metrics dir: {metrics_dir}")
    catalog: dict[str, Any] = {"by_key": {}, "files": []}
    for path in sorted(metrics_dir.glob("*.npz")):
        split = split_metrics_filename(path.name)
        if split is None:
            continue
        model_id, part = split
        meta = _parse_model(model_id)
        meta["partition"] = part
        meta["path"] = path
        meta["eval"] = _load_npz(path)
        key = (meta.get("kind"), meta.get("arm"), meta.get("label_n"), part,
               meta.get("distill_seed"), meta.get("readout_seed"), meta.get("seed"))
        catalog["by_key"][key] = meta
        catalog["files"].append(meta)
        # ckpt curve sidecar：同 stem（含分区）或 SPEC 的无分区 json
        if meta["kind"] == "ckpt":
            for side in (path.with_suffix(".json"), path.parent / f"{model_id}.json"):
                if side.is_file():
                    meta["curve"] = json.loads(side.read_text(encoding="utf-8"))
                    break
    return catalog


def load_prereg(path: Path) -> dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    frozen = doc.get("frozen") if isinstance(doc.get("frozen"), dict) else {}
    a_star = doc.get("a_star", frozen.get("a_star"))
    if isinstance(a_star, dict):
        a_star = a_star.get("arm", a_star)
    gates = doc.get("gates") or doc.get("gate_thresholds") or {}
    loaded = {
        "raw": doc,
        "a_star": str(a_star),
        "boot_seed": int(doc.get("boot_seed", 20261114)),
        "n_boot": int(doc.get("n_boot", 2000)),
        "gt_level": float(gates.get("GT1", {}).get("level", doc.get("gt_level", GT_LEVEL))),
        "gt1_effect": float(gates.get("GT1", {}).get("effect", GT1_EFFECT)),
        "gt2_effect": float(gates.get("GT2", {}).get("effect", GT2_EFFECT)),
        "gt3_margin_frac": float(gates.get("GT3", {}).get("margin_frac", GT3_MARGIN_FRAC)),
        "ga_target_frac": float(gates.get("GA", {}).get("target_frac", GA_TARGET_FRAC)),
        "ga_ratio_max": float(gates.get("GA", {}).get("ratio_max", GA_RATIO_MAX)),
        "gr_keep_max": float(gates.get("GR", {}).get("keep_max", GR_KEEP_MAX)),
        "gr_wall_drop_min": float(gates.get("GR", {}).get("wall_drop_min", GR_WALL_DROP_MIN)),
        "gr_ap_drop_ci_max": float(gates.get("GR", {}).get("ap_drop_ci_max", GR_AP_DROP_CI_MAX)),
        "gr_ap_level": float(gates.get("GR", {}).get("ap_level", GR_AP_LEVEL)),
        "distill_seeds": list(doc.get("distill_seeds", [0, 1])),
        "readout_seeds": list(doc.get("readout_seeds", [0, 1, 2])),
        "supervised_seeds": list(doc.get("supervised_seeds", [0, 1, 2])),
        "ga_cap": doc.get("ga_cap"),
    }
    loaded["partitions"] = resolve_partitions(loaded)
    return loaded


def load_timing(run_dir: Path) -> dict[str, float]:
    """返回 cell_id -> seconds_per_step 中位数。"""
    out: dict[str, float] = {}
    timing_dir = run_dir / "timing"
    if not timing_dir.is_dir():
        return out
    for path in timing_dir.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        raw = doc.get("seconds_per_step", doc.get("step_seconds"))
        if raw is None:
            continue
        if isinstance(raw, (list, tuple)):
            val = float(np.median(np.asarray(raw, dtype=np.float64)))
        else:
            val = float(raw)
        out[path.stem] = val
    return out


# ---------------------------------------------------------------------------
# 门计算
# ---------------------------------------------------------------------------


def _heads_nested(
    catalog: dict[str, Any],
    *,
    arm: str,
    label_n: int,
    partition: str,
    distill_seeds: Sequence[int],
    readout_seeds: Sequence[int],
) -> dict[int, dict[int, dict[str, Any]]]:
    nested: dict[int, dict[int, dict[str, Any]]] = {}
    for d in distill_seeds:
        row: dict[int, dict[str, Any]] = {}
        for r in readout_seeds:
            key = ("heads", arm, label_n, partition, d, r, None)
            meta = catalog["by_key"].get(key)
            if meta is None:
                # allow arm alias A* stored as literal
                continue
            row[r] = meta["eval"]
        if row:
            nested[d] = row
    if not nested:
        raise KeyError(f"no heads for arm={arm} L={label_n} part={partition}")
    return nested


def _supervised_list(
    catalog: dict[str, Any],
    *,
    arm: str,
    label_n: int,
    partition: str,
    seeds: Sequence[int],
) -> list[dict[str, Any]]:
    out = []
    for s in seeds:
        key = ("supervised", arm, label_n, partition, None, None, s)
        meta = catalog["by_key"].get(key)
        if meta is None:
            raise KeyError(f"missing {arm}-L{label_n}-s{s}.{partition}")
        out.append(meta["eval"])
    return out


def _n_worlds(ev: Mapping[str, Any]) -> int:
    n = int(np.asarray(ev["r2"]).shape[0])
    cpw = int(ev["clips_per_world"])
    if n % cpw != 0:
        raise ValueError("clips not divisible by clips_per_world")
    return n // cpw


def _gate_record(
    name: str,
    *,
    point: float,
    ci_lower: float,
    ci_upper: float,
    level: float,
    passed: bool,
    seed_std: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rec: dict[str, Any] = {
        "gate": name,
        "point_estimate": float(point),
        "ci_lower": float(ci_lower),
        "ci_upper": float(ci_upper),
        "level": float(level),
        "passed": bool(passed),
    }
    if seed_std is not None and not (isinstance(seed_std, float) and math.isnan(seed_std)):
        rec["seed_std"] = float(seed_std)
    if extra:
        rec.update(extra)
    return rec


def _partition(prereg, partition: str | None) -> str:
    if partition is not None:
        return partition
    return prereg["partitions"]["final"]


def compute_gt1(catalog, prereg, partition: str | None = None) -> dict[str, Any]:
    partition = _partition(prereg, partition)
    arm = prereg["a_star"]
    nested = _heads_nested(
        catalog, arm=arm, label_n=64, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    a0 = _supervised_list(
        catalog, arm="A0", label_n=64, partition=partition, seeds=prereg["supervised_seeds"],
    )
    n_worlds = _n_worlds(a0[0])
    stat = nested_group_stat(nested, a0, "r2_ap")
    boot = bootstrap_gate(
        n_worlds, stat, n_boot=prereg["n_boot"], seed=prereg["boot_seed"], level=prereg["gt_level"],
    )
    point = float(boot["point_estimate"])
    passed = bool(point + 1e-12 >= prereg["gt1_effect"] and boot["ci_lower"] > 0.0)
    # seed std on full-data per-(d) means of (mean_r A* - mean A0)
    clips = np.arange(a0[0]["r2"].shape[0], dtype=np.int64)
    a0_mean = float(np.mean([metric_on_clips(ev, clips, "r2_ap") for ev in a0]))
    per_d = {}
    for d, rmap in nested.items():
        per_d[d] = {r: metric_on_clips(ev, clips, "r2_ap") - a0_mean for r, ev in rmap.items()}
    return _gate_record(
        "GT1",
        point=point,
        ci_lower=float(boot["ci_lower"]),
        ci_upper=float(boot["ci_upper"]),
        level=prereg["gt_level"],
        passed=passed,
        seed_std=seed_std_nested(per_d),
        extra={
            "effect": float(prereg["gt1_effect"]),
            "arm": arm,
            "metric": "r2_ap_diff",
            "label_n": 64,
        },
    )


def compute_gt2(catalog, prereg, partition: str | None = None) -> dict[str, Any]:
    partition = _partition(prereg, partition)
    arm = prereg["a_star"]
    nested = _heads_nested(
        catalog, arm=arm, label_n=64, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    csh = _heads_nested(
        catalog, arm="C-sh", label_n=64, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    n_worlds = _n_worlds(next(iter(next(iter(nested.values())).values())))
    # A* - C-sh with nested means on both sides
    M = _prod_metrics()

    def stat(world_idx: np.ndarray) -> float:
        sample = next(iter(next(iter(nested.values())).values()))
        clips = M.expand_world_index(world_idx, clips_per_world=int(sample["clips_per_world"]))
        a_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in nested.items()}
        b_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in csh.items()}
        return float(SEED_MEAN(a_vals) - SEED_MEAN(b_vals))

    boot = bootstrap_gate(
        n_worlds, stat, n_boot=prereg["n_boot"], seed=prereg["boot_seed"], level=prereg["gt_level"],
    )
    point = float(boot["point_estimate"])
    passed = bool(point + 1e-12 >= prereg["gt2_effect"] and boot["ci_lower"] > 0.0)
    return _gate_record(
        "GT2",
        point=point,
        ci_lower=float(boot["ci_lower"]),
        ci_upper=float(boot["ci_upper"]),
        level=prereg["gt_level"],
        passed=passed,
        extra={"effect": float(prereg["gt2_effect"]), "arm": arm, "metric": "r2_ap_diff", "label_n": 64},
    )


def compute_gt3(catalog, prereg, partition: str | None = None) -> dict[str, Any]:
    partition = _partition(prereg, partition)
    arm = prereg["a_star"]
    nested = _heads_nested(
        catalog, arm=arm, label_n=64, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    a0 = _supervised_list(
        catalog, arm="A0", label_n=64, partition=partition, seeds=prereg["supervised_seeds"],
    )
    n_worlds = _n_worlds(a0[0])
    # 点估计侧的 A0 RMSE（全量世界），用作非劣边际
    clips_all = np.arange(a0[0]["r2"].shape[0], dtype=np.int64)
    a0_rmse = float(np.mean([metric_on_clips(ev, clips_all, "r1_rmse") for ev in a0]))
    margin = prereg["gt3_margin_frac"] * a0_rmse
    stat = nested_group_stat(nested, a0, "r1_rmse")
    boot = bootstrap_gate(
        n_worlds, stat, n_boot=prereg["n_boot"], seed=prereg["boot_seed"], level=prereg["gt_level"],
    )
    point = float(boot["point_estimate"])
    passed = bool(boot["ci_upper"] <= margin + 1e-12)
    return _gate_record(
        "GT3",
        point=point,
        ci_lower=float(boot["ci_lower"]),
        ci_upper=float(boot["ci_upper"]),
        level=prereg["gt_level"],
        passed=passed,
        extra={
            "margin": margin,
            "margin_frac": prereg["gt3_margin_frac"],
            "a0_rmse": a0_rmse,
            "arm": arm,
            "metric": "r1_rmse_diff",
            "label_n": 64,
        },
    )


def _load_ga_curves(catalog, arm: str, seeds: Sequence[int], partition: str):
    curves = []
    cap = None
    for s in seeds:
        key = ("ckpt", arm, 512, partition, None, None, s)
        meta = catalog["by_key"].get(key)
        if meta is None or "curve" not in meta:
            # allow curve-only json without npz
            raise KeyError(f"missing ckpt curve for {arm} seed={s}")
        curve = meta["curve"]
        steps = list(curve["steps"])
        ap = list(curve["r2_ap"])
        curves.append((steps, ap))
        c = curve.get("cap")
        if c is not None:
            cap = float(c)
    if cap is None:
        cap = float(max(max(s) for s, _ in curves))
    return curves, cap


def compute_ga(catalog, prereg, partition: str | None = None) -> dict[str, Any]:
    partition = _partition(prereg, partition)
    M = _prod_metrics()
    seeds = prereg["supervised_seeds"]
    a0_curves, cap = _load_ga_curves(catalog, "A0", seeds, partition)
    a4_curves, cap4 = _load_ga_curves(catalog, "A4", seeds, partition)
    cap = float(prereg["ga_cap"] if prereg.get("ga_cap") is not None else max(cap, cap4))
    # 使用生产 ga_decision（线性插值）；突变可改成 stair
    decision = M.ga_decision(a0_curves, a4_curves, cap=cap)
    # 允许 PREREG 覆盖达标比例 / 比值上限时重算判定
    target = float(prereg["ga_target_frac"] * decision["a0_last_median"])
    if abs(target - decision["target_ap"]) > 1e-12:
        a0_res = [M.steps_to_target(s, a, target, cap) for s, a in a0_curves]
        a4_res = [M.steps_to_target(s, a, target, cap) for s, a in a4_curves]
        med_a0 = float(np.median([r[0] for r in a0_res]))
        med_a4 = float(np.median([r[0] for r in a4_res]))
        ratio = float(med_a4 / med_a0) if med_a0 > 0 else float("inf")
        passed = bool(med_a4 <= prereg["ga_ratio_max"] * med_a0 + 1e-12)
        decision = {
            **decision,
            "target_ap": target,
            "median_a0": med_a0,
            "median_a4": med_a4,
            "ratio": ratio,
            "passed": passed,
            "a0_steps": [r[0] for r in a0_res],
            "a4_steps": [r[0] for r in a4_res],
            "a0_censored": [r[1] for r in a0_res],
            "a4_censored": [r[1] for r in a4_res],
        }
    else:
        # 仍按 PREREG 比值上限判定（生产 ga_decision 写死 0.7）
        passed = bool(decision["median_a4"] <= prereg["ga_ratio_max"] * decision["median_a0"] + 1e-12)
        decision = {**decision, "passed": passed, "ratio": float(decision["median_a4"] / decision["median_a0"]) if decision["median_a0"] else float("inf")}

    return _gate_record(
        "GA",
        point=float(decision["ratio"]),
        ci_lower=float("nan"),
        ci_upper=float("nan"),
        level=float("nan"),
        passed=bool(decision["passed"]),
        extra={
            "target_ap": decision["target_ap"],
            "median_a0": decision["median_a0"],
            "median_a4": decision["median_a4"],
            "ratio_max": prereg["ga_ratio_max"],
            "a0_steps": decision["a0_steps"],
            "a4_steps": decision["a4_steps"],
            "a0_censored": decision["a0_censored"],
            "a4_censored": decision["a4_censored"],
            "stair": decision.get("stair"),
            "cap": cap,
            "label_n": 512,
        },
    )


def compute_gr(catalog, prereg, timing: Mapping[str, float], partition: str | None = None) -> dict[str, Any]:
    partition = _partition(prereg, partition)
    arm = prereg["a_star"]
    # RLT 臂读出：arm R；对照 A* 同 L=512
    nested_star = _heads_nested(
        catalog, arm=arm, label_n=512, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    nested_r = _heads_nested(
        catalog, arm="R", label_n=512, partition=partition,
        distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
    )
    n_worlds = _n_worlds(next(iter(next(iter(nested_r.values())).values())))
    M = _prod_metrics()

    def drop_stat(world_idx: np.ndarray) -> float:
        sample = next(iter(next(iter(nested_r.values())).values()))
        clips = M.expand_world_index(world_idx, clips_per_world=int(sample["clips_per_world"]))
        a_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in nested_star.items()}
        b_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in nested_r.items()}
        return float(SEED_MEAN(a_vals) - SEED_MEAN(b_vals))

    boot = bootstrap_gate(
        n_worlds, drop_stat,
        n_boot=prereg["n_boot"], seed=prereg["boot_seed"], level=prereg["gr_ap_level"],
    )

    # keep rate：R 臂各 eval 的全量 keep_rate 嵌套平均
    clips_all = np.arange(next(iter(next(iter(nested_r.values())).values()))["r2"].shape[0], dtype=np.int64)
    keep_vals = {
        d: {r: metric_on_clips(ev, clips_all, "keep_rate") for r, ev in rmap.items()}
        for d, rmap in nested_r.items()
    }
    keep_rate = float(SEED_MEAN(keep_vals))

    # 墙钟：R 蒸馏 vs C-sh 蒸馏（SPEC：C-sh 为同算量稠密对照）
    r_set: list[float] = []
    c_set: list[float] = []
    for d in prereg["distill_seeds"]:
        for stem in (f"distill-R-s{d}", f"distill-R-d{d}", f"R-s{d}"):
            if stem in timing:
                r_set.append(float(timing[stem]))
                break
        for stem in (f"distill-C-sh-s{d}", f"distill-C-sh-d{d}", f"C-sh-s{d}"):
            if stem in timing:
                c_set.append(float(timing[stem]))
                break
    if not r_set or not c_set:
        wall_drop = float("nan")
    else:
        wall_drop = 1.0 - float(np.median(r_set)) / float(np.median(c_set))

    # 阈值比较留一点浮点余量，避免 0.8 的均值表示成 0.8000…02 被误判失败
    _eps = 1e-12
    keep_ok = bool(keep_rate <= prereg["gr_keep_max"] + _eps)
    wall_ok = bool(wall_drop + _eps >= prereg["gr_wall_drop_min"]) if math.isfinite(wall_drop) else False
    ap_ok = bool(boot["ci_upper"] <= prereg["gr_ap_drop_ci_max"] + _eps)
    passed = bool(keep_ok and wall_ok and ap_ok)

    return _gate_record(
        "GR",
        point=float(boot["point_estimate"]),
        ci_lower=float(boot["ci_lower"]),
        ci_upper=float(boot["ci_upper"]),
        level=prereg["gr_ap_level"],
        passed=passed,
        extra={
            "keep_rate": keep_rate,
            "keep_max": prereg["gr_keep_max"],
            "wall_drop": wall_drop,
            "wall_drop_min": prereg["gr_wall_drop_min"],
            "ap_drop_ci_max": prereg["gr_ap_drop_ci_max"],
            "keep_ok": keep_ok,
            "wall_ok": wall_ok,
            "ap_ok": ap_ok,
            "r_step_median": float(np.median(r_set)) if r_set else None,
            "csh_step_median": float(np.median(c_set)) if c_set else None,
            "label_n": 512,
            "arm": arm,
        },
    )


def compute_report_only(catalog, prereg) -> dict[str, Any]:
    """只报告项：L=512/2048 教师价值、换域（含 shift_bg / shift_all）、R3、距离分组。"""
    out: dict[str, Any] = {}
    arm = prereg["a_star"]
    parts = prereg["partitions"]
    final = parts["final"]

    def _nested_or_none(label_n: int, part: str):
        try:
            return _heads_nested(
                catalog, arm=arm, label_n=label_n, partition=part,
                distill_seeds=prereg["distill_seeds"], readout_seeds=prereg["readout_seeds"],
            )
        except KeyError:
            return None

    def _a0_or_none(label_n: int, part: str):
        try:
            return _supervised_list(
                catalog, arm="A0", label_n=label_n, partition=part, seeds=prereg["supervised_seeds"],
            )
        except KeyError:
            return None

    for L in (512, 2048):
        for part in (final, parts["final_shift"]):
            nested = _nested_or_none(L, part)
            a0 = _a0_or_none(L, part)
            if nested is None or a0 is None:
                continue
            clips = np.arange(a0[0]["r2"].shape[0], dtype=np.int64)
            a_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in nested.items()}
            a0_mean = float(np.mean([metric_on_clips(ev, clips, "r2_ap") for ev in a0]))
            out[f"teacher_value_L{L}_{part}"] = {
                "r2_ap_diff": float(SEED_MEAN(a_vals) - a0_mean),
                "a_star_r2_ap": float(SEED_MEAN(a_vals)),
                "a0_r2_ap": a0_mean,
            }
            a_r3 = {d: {r: metric_on_clips(ev, clips, "r3_ap") for r, ev in rmap.items()} for d, rmap in nested.items()}
            out[f"r3_L{L}_{part}"] = {"a_star_r3_ap": float(SEED_MEAN(a_r3))}
            for grp in ("near", "mid", "far"):
                a_g = {
                    d: {r: metric_on_clips(ev, clips, f"r2_ap_{grp}") for r, ev in rmap.items()}
                    for d, rmap in nested.items()
                }
                out.setdefault(f"r2_by_distance_L{L}_{part}", {})[grp] = float(SEED_MEAN(a_g))

    for tag, part in (("shift_bg", parts["shift_bg"]), ("shift_all", parts["shift_all"])):
        for L in (64, 512, 2048):
            nested = _nested_or_none(L, part)
            if nested is None:
                continue
            sample = next(iter(next(iter(nested.values())).values()))
            clips = np.arange(sample["r2"].shape[0], dtype=np.int64)
            a_vals = {d: {r: metric_on_clips(ev, clips, "r2_ap") for r, ev in rmap.items()} for d, rmap in nested.items()}
            slot: dict[str, Any] = {
                "partition": part,
                "a_star_r2_ap": float(SEED_MEAN(a_vals)),
            }
            a0 = _a0_or_none(L, part)
            if a0 is not None:
                a0_mean = float(np.mean([metric_on_clips(ev, clips, "r2_ap") for ev in a0]))
                slot["a0_r2_ap"] = a0_mean
                slot["r2_ap_diff"] = slot["a_star_r2_ap"] - a0_mean
            out.setdefault("domain_shift", {}).setdefault(tag, {})[f"L{L}"] = slot

    try:
        ft = _supervised_list(
            catalog, arm="FT", label_n=64, partition=final, seeds=prereg["supervised_seeds"],
        )
        a0 = _supervised_list(
            catalog, arm="A0", label_n=64, partition=final, seeds=prereg["supervised_seeds"],
        )
        clips = np.arange(a0[0]["r2"].shape[0], dtype=np.int64)
        out["ft_vs_a0_L64"] = {
            "r2_ap_diff": float(
                np.mean([metric_on_clips(ev, clips, "r2_ap") for ev in ft])
                - np.mean([metric_on_clips(ev, clips, "r2_ap") for ev in a0])
            )
        }
    except KeyError:
        pass
    return out


def recompute_all(run_dir: Path, prereg_path: Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    if prereg_path is None:
        for cand in (run_dir / "PREREG.json", run_dir / "prereg.json"):
            if cand.is_file():
                prereg_path = cand
                break
        if prereg_path is None:
            # also allow sibling reports path
            alt = Path(__file__).resolve().parents[1] / "V9-S5-FINAL" / "PREREG.json"
            if alt.is_file():
                prereg_path = alt
    if prereg_path is None or not Path(prereg_path).is_file():
        raise FileNotFoundError("PREREG.json not found")
    prereg = load_prereg(Path(prereg_path))
    catalog = load_run_catalog(run_dir)
    timing = load_timing(run_dir)
    final = prereg["partitions"]["final"]

    gates = {
        "GT1": compute_gt1(catalog, prereg, final),
        "GT2": compute_gt2(catalog, prereg, final),
        "GT3": compute_gt3(catalog, prereg, final),
        "GA": compute_ga(catalog, prereg, final),
        "GR": compute_gr(catalog, prereg, timing, final),
    }
    report_only = compute_report_only(catalog, prereg)
    return {
        "prereg_path": str(Path(prereg_path).resolve()),
        "run_dir": str(run_dir.resolve()),
        "a_star": prereg["a_star"],
        "boot_seed": prereg["boot_seed"],
        "n_boot": prereg["n_boot"],
        "gt_level": prereg["gt_level"],
        "partitions": prereg["partitions"],
        "threshold_audit": audit_prereg_thresholds(prereg["raw"]),
        "gates": gates,
        "report_only": report_only,
        "seed_mean_order": "readouts_then_distills",
    }


def _finite_close(a: Any, b: Any, tol: float = COMPARE_TOL) -> bool:
    if a is None and b is None:
        return True
    try:
        fa, fb = float(a), float(b)
    except (TypeError, ValueError):
        return a == b
    if math.isnan(fa) and math.isnan(fb):
        return True
    if math.isnan(fa) or math.isnan(fb):
        return False
    return abs(fa - fb) <= tol


def compare_gates(recomputed: Mapping[str, Any], gates_doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    """与 gates.json 逐项比对，返回差异列表。"""
    diffs: list[dict[str, Any]] = []
    src = gates_doc.get("gates", gates_doc)
    for name, rec in recomputed.get("gates", recomputed).items():
        other = src.get(name)
        if other is None:
            diffs.append({"gate": name, "field": "<missing>", "recompute": rec, "gates": None})
            continue
        for field in ("point_estimate", "ci_lower", "ci_upper", "level", "passed", "seed_std"):
            if field not in rec and field not in other:
                continue
            if field == "passed":
                if bool(rec.get(field)) != bool(other.get(field)):
                    diffs.append({
                        "gate": name, "field": field,
                        "recompute": rec.get(field), "gates": other.get(field),
                    })
                continue
            if not _finite_close(rec.get(field), other.get(field)):
                diffs.append({
                    "gate": name, "field": field,
                    "recompute": rec.get(field), "gates": other.get(field),
                    "abs_diff": (
                        abs(float(rec[field]) - float(other[field]))
                        if rec.get(field) is not None and other.get(field) is not None
                        and math.isfinite(float(rec[field])) and math.isfinite(float(other[field]))
                        else None
                    ),
                })
    return diffs


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--prereg", type=Path, default=None)
    p.add_argument("--out", type=Path, default=None, help="default: <run-dir>/recompute.json")
    p.add_argument("--gates", type=Path, default=None, help="default: <run-dir>/gates.json")
    args = p.parse_args(argv)

    result = recompute_all(args.run_dir, args.prereg)
    out = args.out or (args.run_dir / "recompute.json")
    gates_path = args.gates or (args.run_dir / "gates.json")
    diffs: list[dict[str, Any]] = []
    if gates_path.is_file():
        gates_doc = json.loads(gates_path.read_text(encoding="utf-8"))
        diffs = compare_gates(result, gates_doc)
        result["compare"] = {
            "gates_path": str(gates_path.resolve()),
            "n_diffs": len(diffs),
            "diffs": diffs,
            "tol": COMPARE_TOL,
        }
    else:
        result["compare"] = {"gates_path": None, "n_diffs": None, "note": "gates.json not found; skip compare"}

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, allow_nan=True) + "\n", encoding="utf-8")
    audit = result.get("threshold_audit") or {}
    rc = 0 if audit.get("ok", True) else 2
    flag = "RED" if rc else "ok"
    print(
        f"wrote {out} (gate diffs={result['compare'].get('n_diffs')}; "
        f"threshold_audit={flag})"
    )
    return rc


if __name__ == "__main__":
    sys.exit(main())
