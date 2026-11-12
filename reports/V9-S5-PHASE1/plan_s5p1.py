"""S5 冻结前各阶段的格清单、选参、选 A* 与 GT1 功效。纯标准库，不训练。"""

from __future__ import annotations

import math

BATCH = 8
CLIPS_PER_WORLD = 16
POOL_WORLDS = 250
LAB_WORLDS = 128
DISTILL_EPOCHS = 15
SUPER_EPOCHS = {64: 300, 512: 60, 2048: 20}
L_WORLDS = {64: 4, 512: 32, 2048: 128}
DISTILL_LRS = (3e-4, 1e-3)
SUPER_LRS = (3e-4, 1e-3)
ETAS = (0.1, 0.5, 1.0)
ARM_ORDER = ("A1", "A2", "A3")
SEG_PER_S = 54.0
FINAL_WORLD_CAP = 96
GT1_EFFECT = 0.05
GT1_LEVEL = 1.0 - 0.05 / 3.0
GT1_POWER = 0.80
PROBE_STEP_SCALE = 0.1
TUNE_DISTILL_STEP_SCALE = 0.25

# 设计 §6 的整段墙钟，dry-run 在逐步估算之外另报这组数。
STAGE_WALL_H = {
    "probe": 0.5,
    "dev-tune": 1.6,
    "dev-distill": 2.0 + 0.75 + 0.47,
}


HEADS_CACHE_SEG_PER_S = 54.0   # 学生前向抽取并缓存特征（按 54 段/秒）
HEADS_TRAIN_STEP_PER_S = 100.0  # 仅更新读出头参数的优化器步速（按 100 步/秒估算）


def steps_for(n_clips: int, epochs: int, batch: int = BATCH) -> int:
    return max(1, int(epochs) * (int(n_clips) // int(batch)))


def wall_seconds(n_clips: int, epochs: int, *, kind: str = "train", batch: int = BATCH) -> float:
    """按设计里的每秒段数估算墙钟，只用于 dry-run。

    对于 heads 格子，学生模型已冻结，耗时按「缓存一次学生特征 + 只训读出头」估算；
    单头耗时约 25–89 s（平均约 50 s），dev-distill 54 个读出头合计约 0.81 h（对照设计 §6 的 0.75 h）；
    待 probe 实测后校准覆盖。
    """
    if kind == "heads":
        steps = steps_for(n_clips, epochs, batch)
        cache_s = float(n_clips / HEADS_CACHE_SEG_PER_S)
        train_s = float(steps / HEADS_TRAIN_STEP_PER_S)
        return cache_s + train_s
    return float(n_clips * epochs / SEG_PER_S)


def scaled_epochs(design_epochs: int, scale: float) -> int:
    return max(1, int(round(design_epochs * scale)))


def normal_ppf(p: float) -> float:
    """标准正态分位数。Acklam 近似，足够用来锁定功效公式。"""
    if not 0.0 < p < 1.0:
        raise ValueError(f"probability out of range: {p}")
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        return num / den
    if p > 1.0 - plow:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        num = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        den = ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
        return -(num / den)
    q = p - 0.5
    r = q * q
    num = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q
    den = (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    return num / den


def worlds_for_power(
    sigma_world: float,
    *,
    effect: float = GT1_EFFECT,
    level: float = GT1_LEVEL,
    power: float = GT1_POWER,
    cap: int = FINAL_WORLD_CAP,
) -> dict[str, float | int | None]:
    """GT1：真效应为 ``effect`` 时，98.3% 区间下界大于 0 的功效达到 ``power`` 所需世界数。

    ``sigma_world`` 是配对差值的世界级标准差。区间用等尾分位，所以正态临界值取
    ``(1-level)/2`` 而不是 ``1-level``。功效项再加 ``normal_ppf(power)``。
    设计补记把 ``s5p1-final`` 封在 ``cap`` 个世界；超出的数仍记在 ``n_uncapped``。
    """
    if sigma_world < 0 or effect <= 0 or not 0.0 < power < 1.0:
        raise ValueError("sigma, effect and power are out of range")
    z_ci = normal_ppf(1.0 - (1.0 - level) / 2.0)
    z_pow = normal_ppf(power)
    if sigma_world == 0.0:
        n_uncapped = 1
    else:
        n_uncapped = int(math.ceil((sigma_world * (z_ci + z_pow) / effect) ** 2))
    return {
        "n_uncapped": n_uncapped,
        "n_worlds": min(n_uncapped, int(cap)),
        "capped": bool(n_uncapped > cap),
        "effect": float(effect),
        "level": float(level),
        "power": float(power),
        "sigma_world": float(sigma_world),
        "z_ci": float(z_ci),
        "z_power": float(z_pow),
    }


def _mean(rows: list[float]) -> float:
    if not rows:
        raise ValueError("no rows to average")
    return float(sum(rows) / len(rows))


def select_a_star(rows: list[dict]) -> dict:
    """L=64 的 R2 AP：先在蒸馏种子内平均读出种子，再在蒸馏种子间平均。

    平局按 A1 < A2 < A3 取靠前的臂。
    """
    buckets: dict[str, dict[int, list[float]]] = {arm: {} for arm in ARM_ORDER}
    for row in rows:
        arm = str(row["arm"])
        if arm not in buckets:
            raise ValueError(f"unexpected arm {arm!r}")
        seed = int(row["distill_seed"])
        buckets[arm].setdefault(seed, []).append(float(row["r2_ap"]))
    scored = []
    for arm in ARM_ORDER:
        per_distill = [_mean(values) for values in buckets[arm].values()]
        if not per_distill:
            raise ValueError(f"arm {arm} has no rows")
        scored.append((arm, _mean(per_distill)))
    best_score = max(score for _arm, score in scored)
    tied = [arm for arm, score in scored if score == best_score]
    chosen = next(arm for arm in ARM_ORDER if arm in tied)
    return {"arm": chosen, "score": best_score, "per_arm": {arm: score for arm, score in scored}, "tied": tied}


def choose_value(rows: list[dict], value_key: str) -> dict:
    """同一取值先对 R2 AP 取平均，再按平均分选；平局取更小的取值。"""
    groups: dict[float, list[float]] = {}
    for row in rows:
        groups.setdefault(float(row[value_key]), []).append(float(row["r2_ap"]))
    averaged = [{value_key: key, "r2_ap": _mean(values)} for key, values in groups.items()]
    return choose_smaller(averaged, value_key)


def choose_smaller(rows: list[dict], value_key: str) -> dict:
    """R2 AP 高者胜；平局取 ``value_key`` 更小的那个。"""
    if not rows:
        raise ValueError("no rows")
    best = max(float(row["r2_ap"]) for row in rows)
    tied = [row for row in rows if float(row["r2_ap"]) == best]
    tied.sort(key=lambda row: float(row[value_key]))
    winner = tied[0]
    return {"value": float(winner[value_key]), "r2_ap": float(winner["r2_ap"]), "tied": len(tied)}


def _cell(cell_id: str, kind: str, **fields) -> dict:
    n_clips = int(fields.pop("n_clips"))
    epochs = int(fields.pop("epochs"))
    batch = int(fields.pop("batch", BATCH))
    fields.update(
        {
            "cell_id": cell_id,
            "kind": kind,
            "n_clips": n_clips,
            "epochs": epochs,
            "batch_size": batch,
            "steps": steps_for(n_clips, epochs, batch),
            "wall_s_est": wall_seconds(n_clips, epochs, kind=kind, batch=batch),
        }
    )
    return fields


def stage_cells(stage: str, *, pool_worlds: int = POOL_WORLDS, lab_worlds: int = LAB_WORLDS) -> list[dict]:
    """该阶段要跑的训练格。smoke 的格由运行器另列（固定 2 步）。"""
    if stage == "smoke":
        return []
    pool_clips = pool_worlds * CLIPS_PER_WORLD
    if stage == "probe":
        cells = []
        distill_epochs = scaled_epochs(DISTILL_EPOCHS, PROBE_STEP_SCALE)
        for arm in ARM_ORDER:
            cells.append(_cell(
                f"probe-distill-{arm}-s0", "distill", arm=arm, seed=0, lr=1e-3,
                n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-pool",
            ))
        for label_n, worlds in L_WORLDS.items():
            epochs = scaled_epochs(SUPER_EPOCHS[label_n], PROBE_STEP_SCALE)
            n_clips = worlds * CLIPS_PER_WORLD
            cells.append(_cell(
                f"probe-A0-L{label_n}-s0", "supervised", arm="A0", seed=0, lr=1e-3,
                label_n=label_n, n_clips=n_clips, epochs=epochs, partition="s5p1-lab",
            ))
        cells.append(_cell(
            "probe-A4-L512-s0", "supervised", arm="A4", seed=0, lr=1e-3, eta=0.5,
            label_n=512, n_clips=L_WORLDS[512] * CLIPS_PER_WORLD,
            epochs=scaled_epochs(SUPER_EPOCHS[512], PROBE_STEP_SCALE), partition="s5p1-lab",
        ))
        cells.append(_cell(
            "probe-A0R-L512-s0", "supervised", arm="A0-R", seed=0, lr=1e-3, tau=0.02,
            label_n=512, n_clips=L_WORLDS[512] * CLIPS_PER_WORLD,
            epochs=scaled_epochs(SUPER_EPOCHS[512], PROBE_STEP_SCALE), partition="s5p1-lab",
        ))
        for arm in ARM_ORDER:
            for label_n, worlds in L_WORLDS.items():
                cells.append(_cell(
                    f"probe-heads-{arm}-L{label_n}-s0", "heads", arm=arm, seed=0,
                    distill_seed=0, readout_seed=0, lr=1e-3, label_n=label_n,
                    n_clips=worlds * CLIPS_PER_WORLD,
                    epochs=scaled_epochs(SUPER_EPOCHS[label_n], PROBE_STEP_SCALE),
                    partition="s5p1-lab",
                ))
        return cells
    if stage == "dev-tune":
        cells = []
        epochs = scaled_epochs(DISTILL_EPOCHS, TUNE_DISTILL_STEP_SCALE)
        for lr in DISTILL_LRS:
            cells.append(_cell(
                f"tune-distill-A2-lr{lr}", "distill", arm="A2", seed=0, lr=lr,
                n_clips=pool_clips, epochs=epochs, partition="s5p1-pool", role="distill_lr",
            ))
        for label_n, worlds in L_WORLDS.items():
            for lr in SUPER_LRS:
                cells.append(_cell(
                    f"tune-A0-L{label_n}-lr{lr}", "supervised", arm="A0", seed=0, lr=lr,
                    label_n=label_n, n_clips=worlds * CLIPS_PER_WORLD,
                    epochs=SUPER_EPOCHS[label_n], partition="s5p1-lab", role="supervised_lr",
                ))
        for eta in ETAS:
            cells.append(_cell(
                f"tune-A4-eta{eta}", "supervised", arm="A4", seed=0, lr=None, eta=eta,
                label_n=512, n_clips=L_WORLDS[512] * CLIPS_PER_WORLD,
                epochs=SUPER_EPOCHS[512], partition="s5p1-lab", role="eta",
            ))
        return cells
    if stage == "dev-distill":
        cells = []
        for arm in ARM_ORDER:
            for seed in (0, 1):
                cells.append(_cell(
                    f"distill-{arm}-s{seed}", "distill", arm=arm, seed=seed, lr=None,
                    n_clips=pool_clips, epochs=DISTILL_EPOCHS, partition="s5p1-pool",
                ))
        for arm in ARM_ORDER:
            for distill_seed in (0, 1):
                for label_n, worlds in L_WORLDS.items():
                    for readout_seed in (0, 1, 2):
                        cells.append(_cell(
                            f"heads-{arm}-d{distill_seed}-L{label_n}-r{readout_seed}",
                            "heads", arm=arm, seed=readout_seed, distill_seed=distill_seed,
                            readout_seed=readout_seed, lr=None, label_n=label_n,
                            n_clips=worlds * CLIPS_PER_WORLD, epochs=SUPER_EPOCHS[label_n],
                            partition="s5p1-lab",
                        ))
        for seed in (0, 1, 2):
            cells.append(_cell(
                f"A0-L64-s{seed}", "supervised", arm="A0", seed=seed, lr=None,
                label_n=64, n_clips=L_WORLDS[64] * CLIPS_PER_WORLD,
                epochs=SUPER_EPOCHS[64], partition="s5p1-lab",
            ))
        return cells
    raise ValueError(f"unknown stage {stage!r}")


def summarize_stage(stage: str, cells: list[dict]) -> dict:
    wall = float(sum(cell["wall_s_est"] for cell in cells))
    summary = {
        "stage": stage,
        "n_cells": len(cells),
        "steps": int(sum(cell["steps"] for cell in cells)),
        "wall_s_est": wall,
        "wall_h_est": wall / 3600.0,
        "design_wall_h": STAGE_WALL_H.get(stage),
        "cells": cells,
    }
    if stage in ("probe", "dev-distill"):
        heads_cells = [cell for cell in cells if cell.get("kind") == "heads"]
        if heads_cells:
            heads_wall_s = float(sum(c["wall_s_est"] for c in heads_cells))
            summary["heads_wall_est_s"] = heads_wall_s
            summary["heads_wall_est_h"] = heads_wall_s / 3600.0
            summary["heads_design_ref_h"] = 0.75 if stage == "dev-distill" else None
            summary["heads_note"] = (
                "读出头墙钟按「缓存一次学生特征 + 只训读出头」估算（单头约 25–89 s，平均约 50 s）；"
                f"本阶段读出头总估算约 {heads_wall_s / 3600.0:.2f} h"
                + ("（对照设计 §6 的 0.75 h）；" if stage == "dev-distill" else "；")
                + "待 probe 实测后校准覆盖此估计。"
            )
    return summary
