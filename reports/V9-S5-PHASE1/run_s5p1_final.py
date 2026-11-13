"""S5 冻结后登记运行器：训练 C-sh / R / A0(512,2048) / A4 / A0-R / FT 及 C-sh、R 读出头，随后一次性物化并评测 final 与 final-shift，计算全部门 (GT1-GT3, GA, GR)。

依据 reports/V9-S5-FINAL/SPEC.md §2 与 reports/V9-S5-DESIGN/DESIGN-r1.md §§3-7 实现：
- 不读取 s5p1-dev，不写 dev-uses.json；
- 独立登记账本 artifacts/v9/s5/registered-runs.json，同一 PREREG 只许成功完成一次；
- 启动顺序：先拿 artifacts/locks/m0-worker.lock（忙则退出码 75，不创建任何目录），再核对 pycache、PREREG SHA、代码传递闭包清单、git 干净状态、66 个冻结前权重 SHA 与 tune 文件 SHA，最后才创建运行目录；
- 训练格全部在 spawn 子进程中执行，逐格前核对冻结清单，支持单格时限与 GPU 硬件复位重试；
- 全部训练格完成后、评测开始前再核对一次冻结清单；一次性物化 final 与 final-shift（目标目录已存在则报错拒绝覆盖），评完 102 个模型与 96 个 GA 检查点并写出 gates.json 后，结尾再核对一次冻结清单（闭合最后一格缺口）；
- 支持 --resume <run_dir>（仅跳过已有 cell_end 且输出文件 SHA 匹配的训练格；评测一旦开始则整段重评并记 eval_attempt）与 --dry-run（不拿锁、不写盘）。
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import multiprocessing as mp
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Sequence

STARTED = time.time()

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

from ainerzero.v9.experiments.s3 import run_guard as GD  # noqa: E402
from ainerzero.v9.experiments.s5 import data as s5_data  # noqa: E402
from ainerzero.v9.experiments.s5 import evaluate as s5_eval  # noqa: E402
from ainerzero.v9.experiments.s5 import materialize as s5_mat  # noqa: E402
from ainerzero.v9.experiments.s5 import metrics as s5_metrics  # noqa: E402
from ainerzero.v9.experiments.s5 import tokens as s5_tokens  # noqa: E402
from ainerzero.v9.experiments.s5 import world as s5_world  # noqa: E402
from ainerzero.v9.experiments.s5.data import ClipIndex, ItemCache  # noqa: E402
from ainerzero.v9.experiments.s5.materialize import materialize_partition  # noqa: E402

import plan_s5p1 as plan  # noqa: E402
import run_s5p1 as pre  # noqa: E402

LOCK = REPO / "artifacts/locks/m0-worker.lock"
RUNS = REPO / "artifacts/v9/s5/runs"
DEV_LEDGER = REPO / "artifacts/v9/s5/dev-uses.json"
REGISTERED_LEDGER = REPO / "artifacts/v9/s5/registered-runs.json"
DATA_ROOT = REPO / "artifacts/v9/s5/data"
TEACHERS = REPO / "artifacts/v9/s5/teachers"

REAL_FINAL_PARTITIONS = {
    "pool": "s5p1-pool",
    "lab": "s5p1-lab",
    "final": "s5p1-final",
    "final_shift": "s5p1-final-shift",
}
REAL_REGISTERED_NAMES = frozenset({"s5p1-final", "s5p1-final-shift"})

CSH_PERM_SEED = 20261113
LAB_SUBSET_SEED = 20261112
BOOT_SEED = 20261114
N_BOOT = 2000
GT_BONFERRONI_M = 3
GT_ALPHA = 0.05
GT_LEVEL = 1.0 - GT_ALPHA / float(GT_BONFERRONI_M)
GR_LEVEL = 0.95
RLT_TAU = 0.02
CKPT_EVERY_FRAC = 1.0 / 16.0
EVAL_THRESHOLD = 0.5
CELL_LIMIT_S = pre.CELL_LIMIT_S
DEFAULT_STAGE_LIMIT_S = 10 * 3600

# 实测每步与每格墙钟估算参数（来自 dev-tune 与 dev-tune-b 实测，见 SPEC.md §2.4）
EST_DISTILL_STEP_S = 0.285
EST_DISTILL_RLT_STEP_S = 0.285 / 1.3
EST_SUPER_STEP_BY_L = {64: 0.275, 512: 0.371, 2048: 0.283}
EST_SUPER_STEP_S = 0.30
EST_SUPER_A4_STEP_S = 0.312
EST_SUPER_RLT_STEP_S = 0.270
EST_HEAD_CELL_S = 27.0
EST_MATERIALIZE_WORLD_S = 2.2
EST_EVAL_CLIP_S = 0.0045
EST_GA_CKPT_S = 2.5

sha256_file = pre.sha256_file
_append = pre._append
_json_default = pre._json_default


def cell_limit_seconds(cell_index: int) -> float:
    return float(CELL_LIMIT_S)


def _manifest(repo: Path = REPO) -> dict[str, str]:
    # Every entry is taken from ``repo`` so a copy of the repository pins its own files (tier-1, 11-13).
    repo = Path(repo).resolve()
    phase = repo / "reports/V9-S5-PHASE1"
    entries = [
        phase / "run_s5p1_final.py",
        phase / "run_s5p1.py",
        phase / "plan_s5p1.py",
        repo / "src/ainerzero/v9/experiments/s5/train.py",
        repo / "src/ainerzero/v9/experiments/s5/evaluate.py",
        repo / "src/ainerzero/v9/experiments/s5/data.py",
        repo / "src/ainerzero/v9/experiments/s5/metrics.py",
        repo / "src/ainerzero/v9/experiments/s5/tokens.py",
        repo / "src/ainerzero/v9/experiments/s5/materialize.py",
        repo / "src/ainerzero/v9/experiments/s5/world.py",
    ]
    return GD.build_manifest(repo, entries, src_root=repo / "src")


def manifest_sha256(manifest: dict[str, str]) -> str:
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def build_final_cells(prereg: dict[str, Any]) -> list[dict[str, Any]]:
    """按 PREREG 生成冻结后登记运行的全部 44 个训练格（不碰 dev，也不碰 final）。"""
    frozen = prereg["frozen"]
    pinned = prereg["pinned_artifacts"]
    a_star = str(frozen["a_star"])
    if a_star not in ("A1", "A2", "A3"):
        raise GD.GuardError(f"invalid frozen a_star: {a_star!r}")

    distill_lr = float(frozen["distill_lr"])
    supervised_lr = float(frozen["supervised_lr"])
    eta = float(frozen["eta"])
    tau = float(frozen.get("tau", RLT_TAU))
    batch_size = int(frozen.get("batch_size", plan.BATCH))
    distill_epochs = int(frozen.get("distill_epochs", plan.DISTILL_EPOCHS))
    super_epochs_map = {int(k): int(v) for k, v in frozen.get("super_epochs", plan.SUPER_EPOCHS).items()}
    readout_epochs_map = {int(k): int(v) for k, v in frozen.get("readout_epochs", plan.SUPER_EPOCHS).items()}
    ckpt_every_frac = float(frozen.get("ckpt_every_frac", CKPT_EVERY_FRAC))
    csh_perm_seed = int(frozen.get("csh_perm_seed", CSH_PERM_SEED))
    lab_subset_seed = int(frozen.get("lab_subset_seed", LAB_SUBSET_SEED))

    partitions = frozen.get("partitions") or REAL_FINAL_PARTITIONS
    pool_part = str(partitions["pool"])
    lab_part = str(partitions["lab"])
    for p_name in (pool_part, lab_part):
        if "final" in p_name or "dev" in p_name:
            raise GD.GuardError(f"training cell partition must not be dev or final: {p_name!r}")

    pool_clips = int(frozen.get("pool_n_clips", plan.POOL_WORLDS * plan.CLIPS_PER_WORLD))
    seeds_cfg = frozen.get("seeds") or {}
    distill_seeds = [int(s) for s in seeds_cfg.get("distill", [0, 1])]
    readout_seeds = [int(s) for s in seeds_cfg.get("readout", [0, 1, 2])]
    a0_seeds = [int(s) for s in seeds_cfg.get("A0", [0, 1, 2])]
    a4_seeds = [int(s) for s in seeds_cfg.get("A4", [0, 1, 2])]
    a0r_seeds = [int(s) for s in seeds_cfg.get("A0-R", [0, 1, 2])]
    ft_seeds = [int(s) for s in seeds_cfg.get("FT", [0, 1, 2])]

    dev_distill_run = Path(pinned["dev_distill_run"])
    if not dev_distill_run.is_absolute():
        dev_distill_run = (REPO / dev_distill_run).resolve()
    ft_init_fname = f"distill-{a_star}-s1-student.npz"
    if ft_init_fname not in pinned.get("distill_students", {}):
        raise GD.GuardError(f"pinned_artifacts missing FT init student {ft_init_fname}")
    ft_init_path = str(dev_distill_run / "weights" / ft_init_fname)
    ft_init_sha = str(pinned["distill_students"][ft_init_fname])

    cells: list[dict[str, Any]] = []

    # 1. C-sh 蒸馏 × 种子 (0, 1)
    for d_seed in distill_seeds:
        steps = max(1, distill_epochs * (pool_clips // batch_size))
        cells.append({
            "cell_id": f"distill-C-sh-s{d_seed}",
            "group": "C-sh",
            "kind": "distill",
            "arm": a_star,
            "control_arm": "C-sh",
            "seed": d_seed,
            "perm_seed": csh_perm_seed,
            "lr": distill_lr,
            "epochs": distill_epochs,
            "batch_size": batch_size,
            "n_clips": pool_clips,
            "steps": steps,
            "partition": pool_part,
            "save_ckpts": False,
        })

    # 2. R 蒸馏 × 种子 (0, 1)
    for d_seed in distill_seeds:
        steps = max(1, distill_epochs * (pool_clips // batch_size))
        cells.append({
            "cell_id": f"distill-R-s{d_seed}",
            "group": "R",
            "kind": "distill",
            "arm": a_star,
            "control_arm": "R",
            "seed": d_seed,
            "perm_seed": None,
            "tau": tau,
            "lr": distill_lr,
            "epochs": distill_epochs,
            "batch_size": batch_size,
            "n_clips": pool_clips,
            "steps": steps,
            "partition": pool_part,
            "save_ckpts": False,
        })

    # 3. A0 监督：L ∈ {512, 2048} × 种子 (0, 1, 2)（L=64 复用 dev-distill 钉住的 3 个模型）
    for label_n in (512, 2048):
        epochs = super_epochs_map[label_n]
        eff_clips = int(frozen.get("effective_l_clips", {}).get(str(label_n), label_n))
        steps = max(1, epochs * (eff_clips // batch_size))
        for seed in a0_seeds:
            cells.append({
                "cell_id": f"A0-L{label_n}-s{seed}",
                "group": "A0",
                "kind": "supervised",
                "arm": "A0",
                "label_n": label_n,
                "seed": seed,
                "lr": supervised_lr,
                "epochs": epochs,
                "batch_size": batch_size,
                "n_clips": eff_clips,
                "steps": steps,
                "partition": lab_part,
                "lab_subset_seed": lab_subset_seed,
                "save_ckpts": label_n == 512,
                "ckpt_every_frac": ckpt_every_frac,
            })

    # 4. A4 监督：L=512 × 种子 (0, 1, 2)，存 16 个检查点供 GA 用
    epochs_512 = super_epochs_map[512]
    eff_512 = int(frozen.get("effective_l_clips", {}).get("512", 512))
    steps_512 = max(1, epochs_512 * (eff_512 // batch_size))
    for seed in a4_seeds:
        cells.append({
            "cell_id": f"A4-L512-s{seed}",
            "group": "A4",
            "kind": "supervised",
            "arm": "A4",
            "label_n": 512,
            "seed": seed,
            "lr": supervised_lr,
            "eta": eta,
            "epochs": epochs_512,
            "batch_size": batch_size,
            "n_clips": eff_512,
            "steps": steps_512,
            "partition": lab_part,
            "lab_subset_seed": lab_subset_seed,
            "save_ckpts": True,
            "ckpt_every_frac": ckpt_every_frac,
        })

    # 5. A0-R 监督：L=512 × 种子 (0, 1, 2)，tau=0.02
    for seed in a0r_seeds:
        cells.append({
            "cell_id": f"A0-R-L512-s{seed}",
            "group": "A0-R",
            "kind": "supervised",
            "arm": "A0-R",
            "label_n": 512,
            "seed": seed,
            "lr": supervised_lr,
            "tau": tau,
            "epochs": epochs_512,
            "batch_size": batch_size,
            "n_clips": eff_512,
            "steps": steps_512,
            "partition": lab_part,
            "lab_subset_seed": lab_subset_seed,
            "save_ckpts": False,
        })

    # 6. FT 全量微调：L ∈ {64, 512, 2048} × 种子 (0, 1, 2)，从 A* 蒸馏种子 1 的学生出发
    for label_n in (64, 512, 2048):
        epochs = super_epochs_map[label_n]
        eff_clips = int(frozen.get("effective_l_clips", {}).get(str(label_n), label_n))
        steps = max(1, epochs * (eff_clips // batch_size))
        for seed in ft_seeds:
            cells.append({
                "cell_id": f"FT-L{label_n}-s{seed}",
                "group": "FT",
                "kind": "supervised",
                "arm": "FT",
                "label_n": label_n,
                "seed": seed,
                "lr": supervised_lr,
                "epochs": epochs,
                "batch_size": batch_size,
                "n_clips": eff_clips,
                "steps": steps,
                "partition": lab_part,
                "lab_subset_seed": lab_subset_seed,
                "init_student_file": ft_init_path,
                "init_student_sha": ft_init_sha,
                "save_ckpts": False,
            })

    # 7. C-sh 读出头：2 蒸馏种子 × 3 档 L × 3 读出种子 = 18 格
    for d_seed in distill_seeds:
        for label_n in (64, 512, 2048):
            epochs = readout_epochs_map[label_n]
            eff_clips = int(frozen.get("effective_l_clips", {}).get(str(label_n), label_n))
            steps = max(1, epochs * (eff_clips // batch_size))
            for r_seed in readout_seeds:
                cells.append({
                    "cell_id": f"heads-C-sh-d{d_seed}-L{label_n}-r{r_seed}",
                    "group": "heads-C-sh",
                    "kind": "heads",
                    "arm": "C-sh",
                    "student_cell": f"distill-C-sh-s{d_seed}",
                    "distill_seed": d_seed,
                    "label_n": label_n,
                    "readout_seed": r_seed,
                    "seed": r_seed,
                    "lr": supervised_lr,
                    "epochs": epochs,
                    "batch_size": batch_size,
                    "n_clips": eff_clips,
                    "steps": steps,
                    "partition": lab_part,
                    "lab_subset_seed": lab_subset_seed,
                    "save_ckpts": False,
                })

    # 8. R 读出头：2 蒸馏种子 × L=512 × 3 读出种子 = 6 格
    for d_seed in distill_seeds:
        epochs = readout_epochs_map[512]
        eff_clips = int(frozen.get("effective_l_clips", {}).get("512", 512))
        steps = max(1, epochs * (eff_clips // batch_size))
        for r_seed in readout_seeds:
            cells.append({
                "cell_id": f"heads-R-d{d_seed}-L512-r{r_seed}",
                "group": "heads-R",
                "kind": "heads",
                "arm": "R",
                "student_cell": f"distill-R-s{d_seed}",
                "distill_seed": d_seed,
                "label_n": 512,
                "readout_seed": r_seed,
                "seed": r_seed,
                "lr": supervised_lr,
                "tau": tau,
                "epochs": epochs,
                "batch_size": batch_size,
                "n_clips": eff_clips,
                "steps": steps,
                "partition": lab_part,
                "lab_subset_seed": lab_subset_seed,
                "save_ckpts": False,
            })

    return cells


def estimate_cell_seconds(cell: dict[str, Any]) -> float:
    """按 dev-tune 与 dev-distill 实测每步时间估算单格墙钟秒数（SPEC.md §2.4）。"""
    kind = cell["kind"]
    steps = int(cell["steps"])
    if kind == "distill":
        per_step = EST_DISTILL_RLT_STEP_S if cell.get("tau") is not None else EST_DISTILL_STEP_S
        return round(steps * per_step, 2)
    if kind == "heads":
        return round(EST_HEAD_CELL_S, 2)
    if kind == "supervised":
        if cell.get("eta") is not None:
            per_step = EST_SUPER_A4_STEP_S
        elif cell.get("tau") is not None:
            per_step = EST_SUPER_RLT_STEP_S
        else:
            per_step = EST_SUPER_STEP_BY_L.get(int(cell.get("label_n", 512)), EST_SUPER_STEP_S)
        return round(steps * per_step, 2)
    raise GD.GuardError(f"unknown cell kind: {kind!r}")


def dry_run_plan(prereg: dict[str, Any] | None = None, *, budget_h: float | None = None, n_final: int | None = None) -> dict[str, Any]:
    """列出全部 44 个训练格与一次性评测计划，并按实测速度给出逐格与总墙钟估计（不拿锁）。"""
    if prereg is None:
        eff_n_final = int(n_final or 48)
        eff_budget_h = float(budget_h or 10.0)
        synth_prereg = {
            "frozen": {
                "a_star": "A2",
                "distill_lr": 0.0003,
                "supervised_lr": 0.001,
                "eta": 1.0,
                "tau": RLT_TAU,
                "distill_epochs": plan.DISTILL_EPOCHS,
                "super_epochs": {str(k): v for k, v in plan.SUPER_EPOCHS.items()},
                "readout_epochs": {str(k): v for k, v in plan.SUPER_EPOCHS.items()},
                "batch_size": plan.BATCH,
                "ckpt_every_frac": CKPT_EVERY_FRAC,
                "csh_perm_seed": CSH_PERM_SEED,
                "lab_subset_seed": LAB_SUBSET_SEED,
                "n_final": eff_n_final,
                "partitions": dict(REAL_FINAL_PARTITIONS),
            },
            "pinned_artifacts": {
                "dev_distill_run": "artifacts/v9/s5/runs/dev-distill-placeholder",
                "distill_students": {f"distill-{a}-s{s}-student.npz": "0" * 64 for a in ("A1", "A2", "A3") for s in (0, 1)},
            },
            "budget": {"budget_h": eff_budget_h},
        }
        prereg = synth_prereg
    else:
        eff_n_final = int(n_final if n_final is not None else prereg["frozen"]["n_final"])
        eff_budget_h = float(budget_h if budget_h is not None else prereg.get("budget", {}).get("budget_h", 10.0))

    raw_cells = build_final_cells(prereg)
    cells_with_est: list[dict[str, Any]] = []
    group_totals_s: dict[str, float] = {}
    training_s = 0.0
    for cell in raw_cells:
        est_s = estimate_cell_seconds(cell)
        row = {**cell, "estimated_wall_s": est_s, "cell_limit_s": CELL_LIMIT_S}
        cells_with_est.append(row)
        grp = str(cell["group"])
        group_totals_s[grp] = round(group_totals_s.get(grp, 0.0) + est_s, 2)
        training_s += est_s

    n_models = 102  # 54 (A1-A3 heads) + 18 (C-sh heads) + 6 (R heads) + 9 (A0) + 3 (A4) + 3 (A0-R) + 9 (FT)
    n_ga_ckpts = 96  # 2 arms (A0, A4) * 3 seeds * 16 checkpoints
    clips_per_partition = eff_n_final * 16
    materialize_s = round(2 * eff_n_final * EST_MATERIALIZE_WORLD_S, 2)
    # 3 套外观评测：final (default) + final-shift (shift_bg, shift_all)
    models_eval_s = round(n_models * 3 * clips_per_partition * EST_EVAL_CLIP_S, 2)
    ga_eval_s = round(n_ga_ckpts * (eff_n_final / 48.0) * EST_GA_CKPT_S, 2)
    eval_total_s = round(materialize_s + models_eval_s + ga_eval_s, 2)
    total_s = round(training_s + eval_total_s, 2)
    total_h = round(total_s / 3600.0, 3)
    budget_s = round(eff_budget_h * 3600.0, 2)
    exceeds = total_s > budget_s

    return {
        "stage": "final",
        "n_cells": len(cells_with_est),
        "n_models_evaluated": n_models,
        "n_ga_checkpoints": n_ga_ckpts,
        "n_final_worlds": eff_n_final,
        "cell_limit_s": CELL_LIMIT_S,
        "budget_h": eff_budget_h,
        "budget_s": budget_s,
        "estimated_training_s": round(training_s, 2),
        "estimated_training_h": round(training_s / 3600.0, 3),
        "estimated_evaluation_breakdown_s": {
            "materialize_final_and_shift_s": materialize_s,
            "models_102_on_final_and_shift_s": models_eval_s,
            "ga_96_checkpoints_on_final_s": ga_eval_s,
            "total_evaluation_s": eval_total_s,
        },
        "estimated_total_s": total_s,
        "estimated_total_h": total_h,
        "within_budget": not exceeds,
        "exceeds_budget": exceeds,
        "exceeds_budget_by_h": round(max(0.0, total_h - eff_budget_h), 3),
        "budget_warning": (
            f"WARNING: estimated wall-clock {total_h:.3f} h exceeds budget_h {eff_budget_h:.3f} h"
            if exceeds
            else None
        ),
        "group_totals_s": group_totals_s,
        "unit_assumptions": {
            "distill_step_s": EST_DISTILL_STEP_S,
            "distill_rlt_step_s": round(EST_DISTILL_RLT_STEP_S, 4),
            "supervised_step_s": EST_SUPER_STEP_S,
            "supervised_a4_step_s": EST_SUPER_A4_STEP_S,
            "supervised_rlt_step_s": EST_SUPER_RLT_STEP_S,
            "readout_head_cell_s": EST_HEAD_CELL_S,
        },
        "cells": cells_with_est,
    }


def _index_for_final(
    partition_dir: Path,
    clips: Sequence[int] | None,
    *,
    label_n: int | None = None,
    lab_subset_seed: int = LAB_SUBSET_SEED,
    l_worlds_map: dict[int, int] | None = None,
) -> ClipIndex:
    if label_n is not None:
        worlds_map = l_worlds_map if l_worlds_map is not None else plan.L_WORLDS
        n_w = int(worlds_map[int(label_n)])
        sub = ClipIndex(partition_dir).subset_by_worlds(n_w, seed=int(lab_subset_seed))
        if clips is not None:
            return ClipIndex(partition_dir, worlds=sub.worlds, clips=clips)
        return sub
    return ClipIndex(partition_dir, clips=clips)


def _execute_final_cell_body(cell: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """在 spawn 子进程中执行单个冻结后训练格（不读取 dev 或 final）。"""
    import mlx.core as mx

    from ainerzero.v9.experiments.s5.student import Student
    from ainerzero.v9.experiments.s5.train import TrainConfig, distill, train_heads, train_supervised

    kind = cell["kind"]
    part_name = str(cell["partition"])
    if "final" in part_name or "dev" in part_name:
        raise GD.GuardError(f"training cell attempted to read forbidden partition: {part_name}")

    clips = ctx.get("clips")
    l_worlds_map = ctx.get("l_worlds_map")
    lab_subset_seed = int(cell.get("lab_subset_seed", LAB_SUBSET_SEED))
    index = _index_for_final(
        ctx["dirs"][part_name],
        clips,
        label_n=cell.get("label_n"),
        lab_subset_seed=lab_subset_seed,
        l_worlds_map=l_worlds_map,
    )
    student_kw = dict(ctx.get("student_kwargs") or {})
    weights_dir: Path = ctx["weights"]
    ckpts_root: Path = ctx.get("checkpoints") or (ctx["out"] / "checkpoints")

    save_ckpts = bool(cell.get("save_ckpts", False))
    ckpt_dir = (ckpts_root / cell["cell_id"]) if save_ckpts else None
    cfg = TrainConfig(
        lr=float(cell["lr"]),
        batch_size=int(cell["batch_size"]),
        epochs=int(cell["epochs"]),
        seed=int(cell["seed"]),
        ckpt_every_frac=float(cell.get("ckpt_every_frac", CKPT_EVERY_FRAC)),
        eta=cell.get("eta"),
        tau=cell.get("tau"),
        ckpt_dir=ckpt_dir,
    )

    t0 = time.perf_counter()
    files: dict[str, str] = {}
    if kind == "distill":
        student = Student(**student_kw)
        student, heads, log = distill(
            cell["arm"],
            index,
            ctx["teachers"],
            cfg,
            perm_seed=cell.get("perm_seed"),
            student=student,
        )
        files[f"{cell['cell_id']}-student.npz"] = pre._save_weights(
            student, weights_dir / f"{cell['cell_id']}-student.npz"
        )
        files[f"{cell['cell_id']}-heads.npz"] = pre._save_weights(
            heads, weights_dir / f"{cell['cell_id']}-heads.npz"
        )
    elif kind == "supervised":
        init_student = None
        if cell.get("init_student_file"):
            init_path = Path(cell["init_student_file"])
            if not init_path.is_file():
                raise GD.GuardError(f"FT init student file missing: {init_path}")
            got_sha = sha256_file(init_path)
            if got_sha != cell.get("init_student_sha"):
                raise GD.GuardError(
                    f"FT init student SHA mismatch for {init_path}: got {got_sha} != {cell.get('init_student_sha')}"
                )
            init_student = Student(**student_kw)
            init_student.load_weights(str(init_path))
        student = Student(**student_kw) if init_student is None else None
        teachers = ctx["lab_teachers"] if cell.get("eta") is not None else None
        student, heads, log = train_supervised(
            index,
            cfg,
            teachers=teachers,
            init_student=init_student,
            student=student,
        )
        files[f"{cell['cell_id']}-student.npz"] = pre._save_weights(
            student, weights_dir / f"{cell['cell_id']}-student.npz"
        )
        files[f"{cell['cell_id']}-heads.npz"] = pre._save_weights(
            heads, weights_dir / f"{cell['cell_id']}-heads.npz"
        )
    elif kind == "heads":
        student_cell = cell["student_cell"]
        student_file = weights_dir / f"{student_cell}-student.npz"
        if not student_file.is_file():
            raise GD.GuardError(f"student weights file missing for heads cell {cell['cell_id']}: {student_file}")
        expected_student_sha = cell.get("student_sha")
        if expected_student_sha and sha256_file(student_file) != expected_student_sha:
            raise GD.GuardError(
                f"student weights SHA mismatch for {student_file}: got {sha256_file(student_file)} != {expected_student_sha}"
            )
        student = Student(**student_kw)
        student.load_weights(str(student_file))
        heads, log = train_heads(student, index, cfg)
        files[f"{cell['cell_id']}.npz"] = pre._save_weights(
            heads, weights_dir / f"{cell['cell_id']}.npz"
        )
    else:
        raise GD.GuardError(f"unknown cell kind: {kind!r}")

    wall_s = time.perf_counter() - t0
    step_logs = log.get("step_logs") or []
    n_steps = len(step_logs)
    step_compute_vals = [float(r.get("step_s", 0.0)) for r in step_logs]
    step_total_vals = [float(r.get("step_s", 0.0)) + float(r.get("data_s", 0.0)) for r in step_logs]
    return {
        "cell_id": cell["cell_id"],
        "group": cell.get("group"),
        "kind": kind,
        "arm": cell.get("arm"),
        "control_arm": cell.get("control_arm"),
        "label_n": cell.get("label_n"),
        "seed": cell.get("seed"),
        "distill_seed": cell.get("distill_seed"),
        "readout_seed": cell.get("readout_seed"),
        "perm_seed": cell.get("perm_seed"),
        "tau": cell.get("tau"),
        "eta": cell.get("eta"),
        "device": str(mx.default_device()),
        "wall_s": wall_s,
        "steps_logged": n_steps,
        "wall_per_step_s": float(wall_s / max(1, n_steps)),
        "median_step_compute_s": float(np.median(step_compute_vals)) if step_compute_vals else 0.0,
        "median_step_total_s": float(np.median(step_total_vals)) if step_total_vals else 0.0,
        "data_fraction": pre._data_fraction(log),
        "final_loss": step_logs[-1]["loss"] if step_logs else None,
        "checkpoints": log.get("checkpoints") or [],
        "files": files,
    }


def _final_cell_worker_target(
    cell: dict[str, Any],
    ctx_data: dict[str, Any],
    result_json_path: str,
    err_json_path: str,
    runner_fn: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> None:
    try:
        fn = runner_fn if runner_fn is not None else _execute_final_cell_body
        ctx = {
            "stage": ctx_data["stage"],
            "out": Path(ctx_data["out"]),
            "weights": Path(ctx_data["weights"]),
            "metrics": Path(ctx_data["metrics"]),
            "checkpoints": Path(ctx_data["checkpoints"]),
            "teachers": ctx_data["teachers"],
            "lab_teachers": ctx_data.get("lab_teachers"),
            "dirs": {k: Path(v) for k, v in ctx_data["dirs"].items()},
            "student_kwargs": ctx_data.get("student_kwargs") or {},
            "clips": ctx_data.get("clips"),
            "l_worlds_map": {int(k): int(v) for k, v in (ctx_data.get("l_worlds_map") or {}).items()} or None,
        }
        res = fn(cell, ctx)
        with open(result_json_path, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, default=_json_default)
    except Exception as exc:
        import traceback
        with open(err_json_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "error": str(exc),
                    "type": type(exc).__name__,
                    "traceback": traceback.format_exc(),
                },
                f,
                ensure_ascii=False,
            )
        sys.exit(1)


def verify_prereg_and_Save_Check(
    prereg_path: Path,
    expected_prereg_sha: str,
    *,
    repo: Path = REPO,
) -> dict[str, Any]:
    """核对 PREREG 文件 SHA、代码清单、git 清洁状态、tune 文件与全部 66 个冻结前权重文件 SHA。"""
    if not prereg_path.is_file():
        raise GD.GuardError(f"PREREG file is missing: {prereg_path}")
    got_sha = sha256_file(prereg_path)
    if got_sha != expected_prereg_sha.strip().lower():
        raise GD.GuardError(f"PREREG SHA mismatch: got {got_sha} != {expected_prereg_sha}")

    try:
        prereg = json.loads(prereg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GD.GuardError(f"malformed PREREG JSON: {prereg_path}") from exc
    if not isinstance(prereg, dict) or prereg.get("schema") != "s5.phase1.prereg.v1":
        raise GD.GuardError(f"invalid PREREG schema in {prereg_path}")

    for key in ("frozen", "gates", "pinned_artifacts", "manifest", "budget"):
        if key not in prereg or not isinstance(prereg[key], dict):
            raise GD.GuardError(f"PREREG missing required section: {key}")

    manifest = prereg["manifest"]
    changed = GD.check_manifest(repo, manifest)
    if changed:
        raise GD.GuardError("frozen manifest mismatch: " + "; ".join(changed[:6]))

    current_manifest = _manifest(repo)
    missing_from_prereg = [k for k in current_manifest if k not in manifest]
    if missing_from_prereg:
        raise GD.GuardError("PREREG manifest lacks files from import closure: " + "; ".join(missing_from_prereg[:6]))

    _head, dirty = GD.check_git_clean(repo, list(manifest))
    if dirty:
        raise GD.GuardError("frozen files are not committed: " + "; ".join(dirty[:6]))

    verify_pinned_artifacts(prereg, repo=repo)
    return prereg


def verify_pinned_artifacts(prereg: dict[str, Any], *, repo: Path = REPO) -> None:
    """核对 PREREG 钉住的 tune 文件与 dev-distill 权重（6 蒸馏学生 + 54 读出头 + 3 A0-L64 学生与头）。"""
    pinned = prereg["pinned_artifacts"]
    tune_rel = Path(pinned["tune_file"])
    tune_path = tune_rel if tune_rel.is_absolute() else (repo / tune_rel)
    if not tune_path.is_file():
        raise GD.GuardError(f"pinned tune file missing: {tune_path}")
    if sha256_file(tune_path) != pinned["tune_sha256"]:
        raise GD.GuardError(f"pinned tune file SHA mismatch: {tune_path}")

    dev_run_rel = Path(pinned["dev_distill_run"])
    dev_run = dev_run_rel if dev_run_rel.is_absolute() else (repo / dev_run_rel)
    weights_dir = dev_run / "weights"
    if not weights_dir.is_dir():
        raise GD.GuardError(f"pinned dev-distill weights directory missing: {weights_dir}")

    distill_students = pinned.get("distill_students") or {}
    readout_heads = pinned.get("readout_heads") or {}
    a0_l64_students = pinned.get("a0_l64_students") or {}
    a0_l64_heads = pinned.get("a0_l64_heads") or {}

    if len(distill_students) != 6:
        raise GD.GuardError(f"expected 6 pinned distill students, got {len(distill_students)}")
    if len(readout_heads) != 54:
        raise GD.GuardError(f"expected 54 pinned readout heads, got {len(readout_heads)}")
    if len(a0_l64_students) != 3 or len(a0_l64_heads) != 3:
        raise GD.GuardError(
            f"expected 3 pinned A0-L64 students and 3 heads, got {len(a0_l64_students)} and {len(a0_l64_heads)}"
        )

    for group_name, mapping in (
        ("distill_students", distill_students),
        ("readout_heads", readout_heads),
        ("a0_l64_students", a0_l64_students),
        ("a0_l64_heads", a0_l64_heads),
    ):
        for fname, want_sha in mapping.items():
            fpath = weights_dir / fname
            if not fpath.is_file():
                raise GD.GuardError(f"pinned {group_name} file missing: {fpath}")
            got_sha = sha256_file(fpath)
            if got_sha != want_sha:
                raise GD.GuardError(
                    f"pinned {group_name} SHA mismatch for {fname}: got {got_sha} != {want_sha}"
                )


def _read_registered_ledger(ledger: Path) -> list[dict[str, Any]]:
    if not ledger.is_file():
        return []
    try:
        rows = json.loads(ledger.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GD.GuardError(f"malformed registered-runs ledger: {ledger}") from exc
    if not isinstance(rows, list):
        raise GD.GuardError(f"malformed registered-runs ledger: {ledger}")
    return rows


def begin_registered_run(
    lock: GD.RunLock,
    ledger: Path,
    *,
    run_id: str,
    prereg_sha: str,
    out_dir: Path,
    resume: bool,
    expected_lock: Path = LOCK,
) -> dict[str, Any]:
    """在持有锁的前提下登记或续跑一次冻结后运行；同一 PREREG 只许成功完成一次。"""
    GD._require_held(lock, expected_lock)
    if not GD.valid_use_id(run_id):
        raise GD.GuardError(f"invalid run id: {run_id!r}")

    with GD._ledger_mutex(ledger):
        rows = _read_registered_ledger(ledger)
        for row in rows:
            if row.get("prereg_sha256") == prereg_sha and row.get("status") == "completed":
                raise GD.GuardError(
                    f"PREREG {prereg_sha} has already completed a registered run ({row.get('run_id')})"
                )

        if not resume:
            for row in rows:
                if row.get("run_id") == run_id:
                    raise GD.GuardError(f"registered run_id already exists: {run_id}")
                if row.get("prereg_sha256") == prereg_sha:
                    raise GD.GuardError(
                        f"PREREG {prereg_sha} already has an incomplete run ({row.get('run_id')}); use --resume"
                    )
            entry = {
                "run_id": run_id,
                "prereg_sha256": prereg_sha,
                "out": str(out_dir),
                "status": "running",
                "started_at": time.time(),
                "resumes": 0,
            }
            rows.append(entry)
            GD._atomic_write(ledger, json.dumps(rows, ensure_ascii=False, indent=1))
            return entry

        matched = None
        for row in rows:
            if row.get("run_id") == run_id and row.get("prereg_sha256") == prereg_sha:
                matched = row
                break
        if matched is None:
            raise GD.GuardError(
                f"cannot --resume: no incomplete registered run with run_id={run_id!r} and prereg_sha={prereg_sha}"
            )
        if Path(matched.get("out", "")).resolve() != out_dir.resolve():
            raise GD.GuardError(
                f"--resume directory {out_dir} does not match ledger directory {matched.get('out')}"
            )
        matched["status"] = "running"
        matched["resumes"] = int(matched.get("resumes", 0)) + 1
        matched["resumed_at"] = time.time()
        GD._atomic_write(ledger, json.dumps(rows, ensure_ascii=False, indent=1))
        return matched


def finish_registered_run(
    lock: GD.RunLock,
    ledger: Path,
    *,
    run_id: str,
    prereg_sha: str,
    failed: str | None,
    expected_lock: Path = LOCK,
) -> None:
    GD._require_held(lock, expected_lock)
    with GD._ledger_mutex(ledger):
        rows = _read_registered_ledger(ledger)
        for row in rows:
            if row.get("run_id") == run_id and row.get("prereg_sha256") == prereg_sha:
                row["status"] = "failed" if failed else "completed"
                row["failed"] = failed
                row["finished_at"] = time.time()
                break
        GD._atomic_write(ledger, json.dumps(rows, ensure_ascii=False, indent=1))


@contextlib.contextmanager
def _bind_eval_item_loader(
    appearance_suffix: str,
    cache: ItemCache,
):
    """在不修改 src/ 的前提下，为 evaluate() / predict() 绑定外观后缀与进程内 ItemCache，并启用向量化 rlt_keep_fast。"""
    orig_data_load = s5_data.load_item
    orig_eval_load = s5_eval.load_item
    orig_eval_rlt = s5_eval.rlt_keep

    from ainerzero.v9.experiments.s5 import train as s5_train
    orig_train_load = s5_train.load_item

    def _wrapped_load_item(
        index: ClipIndex,
        i: int,
        *,
        teachers: Any = None,
        appearance_suffix: str = appearance_suffix,
        tau: float | None = None,
        cache: ItemCache | None = cache,
    ) -> dict[str, Any]:
        return orig_data_load(
            index,
            i,
            teachers=teachers,
            appearance_suffix=appearance_suffix,
            tau=tau,
            cache=cache,
        )

    s5_data.load_item = _wrapped_load_item
    s5_eval.load_item = _wrapped_load_item
    s5_train.load_item = _wrapped_load_item
    s5_eval.rlt_keep = s5_tokens.rlt_keep_fast
    try:
        yield
    finally:
        s5_data.load_item = orig_data_load
        s5_eval.load_item = orig_eval_load
        s5_train.load_item = orig_train_load
        s5_eval.rlt_keep = orig_eval_rlt


def _save_eval_artifacts(
    metrics_dir: Path,
    model_id: str,
    part_tag: str,
    ev: dict[str, Any],
    *,
    extra_arrays: dict[str, np.ndarray] | None = None,
    extra_summary: dict[str, Any] | None = None,
) -> dict[str, str]:
    """保存 <model_id>.<part_tag>.npz、.disk_groups.json、.ordering_pairs.json、.groups.json 与 .json。"""
    npz_path = metrics_dir / f"{model_id}.{part_tag}.npz"
    disk_groups_path = metrics_dir / f"{model_id}.{part_tag}.disk_groups.json"
    ordering_pairs_path = metrics_dir / f"{model_id}.{part_tag}.ordering_pairs.json"
    groups_path = metrics_dir / f"{model_id}.{part_tag}.groups.json"
    summary_path = metrics_dir / f"{model_id}.{part_tag}.json"

    arrays: dict[str, Any] = {
        "r1_logd": np.asarray(ev["r1_logd"]),
        "r2_logit": np.asarray(ev["r2_logit"]),
        "r3_logit": np.asarray(ev["r3_logit"]),
        "r1_target": np.asarray(ev["r1_target"]),
        "r1_sky": np.asarray(ev["r1_sky"]),
        "r1_obj": np.asarray(ev["r1_obj"]),
        "r2": np.asarray(ev["r2"]),
        "r3": np.asarray(ev["r3"]),
        "world_ids": np.asarray(ev["world_ids"], dtype=np.int64),
        "clips_per_world": np.asarray(int(ev["clips_per_world"]), dtype=np.int64),
    }
    if ev.get("keep_rate_per_clip") is not None:
        arrays["keep_rate_per_clip"] = np.asarray(ev["keep_rate_per_clip"], dtype=np.float64)
    if extra_arrays:
        arrays.update(extra_arrays)

    np.savez_compressed(npz_path, **arrays)

    disk_groups_path.write_text(
        json.dumps(ev["disk_groups"], ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )
    ordering_pairs_path.write_text(
        json.dumps(ev["ordering_pairs"], ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    groups_doc = {
        "model_id": model_id,
        "partition": part_tag,
        "world_ids": [int(w) for w in np.asarray(ev["world_ids"]).tolist()],
        "clips_per_world": int(ev["clips_per_world"]),
        "threshold": float(ev["threshold"]),
        "tau": ev.get("tau"),
        "disk_groups": ev["disk_groups"],
        "ordering_pairs": ev["ordering_pairs"],
    }
    groups_path.write_text(
        json.dumps(groups_doc, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )

    summary_doc = {
        "model_id": model_id,
        "partition": part_tag,
        **ev["metrics"],
    }
    if extra_summary:
        summary_doc.update(extra_summary)
    summary_path.write_text(
        json.dumps(summary_doc, ensure_ascii=False, indent=1, default=_json_default),
        encoding="utf-8",
    )

    return {
        npz_path.name: sha256_file(npz_path),
        disk_groups_path.name: sha256_file(disk_groups_path),
        ordering_pairs_path.name: sha256_file(ordering_pairs_path),
        groups_path.name: sha256_file(groups_path),
        summary_path.name: sha256_file(summary_path),
    }


def _write_timing_file(timing_dir: Path, row: dict[str, Any]) -> None:
    """按 SPEC.md 补记 1 写出 timing/{cell_id}.json（含 seconds_per_step：训练步墙钟中位数）。"""
    timing_dir.mkdir(parents=True, exist_ok=True)
    cid = str(row["cell_id"])
    sec_per_step = float(
        row.get("median_step_total_s")
        if row.get("median_step_total_s") is not None and float(row.get("median_step_total_s", 0.0)) > 0.0
        else row.get("wall_per_step_s", 0.0)
    )
    doc = {
        "cell_id": cid,
        "seconds_per_step": sec_per_step,
        "median_step_total_s": float(row.get("median_step_total_s", sec_per_step)),
        "median_step_compute_s": float(row.get("median_step_compute_s", sec_per_step)),
        "wall_per_step_s": float(row.get("wall_per_step_s", sec_per_step)),
        "wall_s": float(row.get("wall_s", 0.0)),
        "steps_logged": int(row.get("steps_logged", 0)),
    }
    (timing_dir / f"{cid}.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=_json_default) + "\n",
        encoding="utf-8",
    )


def load_eval_bundle(metrics_dir: Path, model_id: str, part_tag: str) -> dict[str, Any]:
    """从落盘的 .npz 与 .groups.json 还原出可供 evaluate.metric_value 使用的字典。"""
    npz_path = metrics_dir / f"{model_id}.{part_tag}.npz"
    groups_path = metrics_dir / f"{model_id}.{part_tag}.groups.json"
    with np.load(npz_path) as data:
        ev: dict[str, Any] = {
            "r1_logd": np.array(data["r1_logd"]),
            "r2_logit": np.array(data["r2_logit"]),
            "r3_logit": np.array(data["r3_logit"]),
            "r1_target": np.array(data["r1_target"]),
            "r1_sky": np.array(data["r1_sky"]),
            "r1_obj": np.array(data["r1_obj"]),
            "r2": np.array(data["r2"]),
            "r3": np.array(data["r3"]),
            "world_ids": np.array(data["world_ids"]),
            "clips_per_world": int(np.asarray(data["clips_per_world"]).item()),
        }
        if "keep_rate_per_clip" in data.files:
            ev["keep_rate_per_clip"] = np.array(data["keep_rate_per_clip"])
    groups = json.loads(groups_path.read_text(encoding="utf-8"))
    ev["disk_groups"] = groups["disk_groups"]
    ev["ordering_pairs"] = groups["ordering_pairs"]
    ev["threshold"] = float(groups.get("threshold", EVAL_THRESHOLD))
    ev["tau"] = groups.get("tau")
    return ev


def nested_seed_mean_on_clips(
    nested_group: Sequence[Sequence[dict[str, Any]]],
    clips: np.ndarray,
    metric: str,
) -> float:
    """两阶段种子平均：先在每个外层（蒸馏种子）内部平均内层（读出种子），再在外层种子间平均。"""
    if not nested_group:
        raise ValueError("nested_group must not be empty")
    outer_means: list[float] = []
    for inner_list in nested_group:
        if not inner_list:
            raise ValueError("inner seed list must not be empty")
        inner_vals = [s5_eval.metric_value(ev, clips, metric) for ev in inner_list]
        outer_means.append(float(sum(inner_vals) / len(inner_vals)))
    return float(sum(outer_means) / len(outer_means))


def nested_seed_group_stat(
    nested_a: Sequence[Sequence[dict[str, Any]]],
    nested_b: Sequence[Sequence[dict[str, Any]]],
    metric: str,
) -> Callable[[np.ndarray], float]:
    """构造世界级配对自助法统计量：先按两阶段顺序平均种子，再计算 A - B。"""
    flat = [ev for grp in (*nested_a, *nested_b) for ev in grp]
    if not flat:
        raise ValueError("empty groups")
    clips_per_world = int(flat[0]["clips_per_world"])
    if any(int(ev["clips_per_world"]) != clips_per_world for ev in flat):
        raise ValueError("clips_per_world mismatch across evaluation bundles")

    def stat(world_idx: np.ndarray) -> float:
        clips = s5_metrics.expand_world_index(world_idx, clips_per_world=clips_per_world)
        mean_a = nested_seed_mean_on_clips(nested_a, clips, metric)
        mean_b = nested_seed_mean_on_clips(nested_b, clips, metric)
        return float(mean_a - mean_b)

    return stat


def seed_dispersion_stats(
    nested_group: Sequence[Sequence[dict[str, Any]]],
    metric: str,
) -> dict[str, Any]:
    """在全量 final 段上计算两阶段种子均值及种子间标准差（DESIGN-r1.md §4）。"""
    first = nested_group[0][0]
    all_clips = np.arange(first["r2"].shape[0], dtype=np.int64)
    per_outer_inner: list[list[float]] = []
    outer_means: list[float] = []
    flat_vals: list[float] = []
    for inner_list in nested_group:
        vals = [float(s5_eval.metric_value(ev, all_clips, metric)) for ev in inner_list]
        per_outer_inner.append(vals)
        outer_means.append(float(sum(vals) / len(vals)))
        flat_vals.extend(vals)
    point = float(sum(outer_means) / len(outer_means))
    flat_std = float(np.std(flat_vals, ddof=1)) if len(flat_vals) > 1 else 0.0
    between_outer_std = float(np.std(outer_means, ddof=1)) if len(outer_means) > 1 else 0.0
    within_inner_stds = [
        float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0 for vals in per_outer_inner
    ]
    return {
        "mean": point,
        "seed_std": flat_std,
        "between_distill_seed_std": between_outer_std,
        "within_distill_readout_stds": within_inner_stds,
        "per_seed_values": per_outer_inner,
    }


def build_model_specs(prereg: dict[str, Any], weights_dir: Path, *, repo: Path = REPO) -> list[dict[str, Any]]:
    """列出需要在 final 与 final-shift 上评测的全部 102 个模型规格。"""
    frozen = prereg["frozen"]
    pinned = prereg["pinned_artifacts"]
    tau_val = float(frozen.get("tau", RLT_TAU))
    seeds_cfg = frozen.get("seeds") or {}
    distill_seeds = [int(s) for s in seeds_cfg.get("distill", [0, 1])]
    readout_seeds = [int(s) for s in seeds_cfg.get("readout", [0, 1, 2])]
    a0_seeds = [int(s) for s in seeds_cfg.get("A0", [0, 1, 2])]
    a4_seeds = [int(s) for s in seeds_cfg.get("A4", [0, 1, 2])]
    a0r_seeds = [int(s) for s in seeds_cfg.get("A0-R", [0, 1, 2])]
    ft_seeds = [int(s) for s in seeds_cfg.get("FT", [0, 1, 2])]

    dev_run_rel = Path(pinned["dev_distill_run"])
    dev_run = dev_run_rel if dev_run_rel.is_absolute() else (repo / dev_run_rel)
    dev_weights = dev_run / "weights"

    specs: list[dict[str, Any]] = []

    # 1. A1-A3 的 54 个读出头（冻结前训好）
    for arm in ("A1", "A2", "A3"):
        for d_seed in distill_seeds:
            s_file = dev_weights / f"distill-{arm}-s{d_seed}-student.npz"
            for label_n in (64, 512, 2048):
                for r_seed in readout_seeds:
                    model_id = f"heads-{arm}-d{d_seed}-L{label_n}-r{r_seed}"
                    h_file = dev_weights / f"{model_id}.npz"
                    specs.append({
                        "model_id": model_id,
                        "arm": arm,
                        "mode": "frozen_heads",
                        "distill_seed": d_seed,
                        "readout_seed": r_seed,
                        "seed": r_seed,
                        "label_n": label_n,
                        "tau": None,
                        "student_file": s_file,
                        "heads_file": h_file,
                    })

    # 2. C-sh 的 18 个读出头
    for d_seed in distill_seeds:
        s_file = weights_dir / f"distill-C-sh-s{d_seed}-student.npz"
        for label_n in (64, 512, 2048):
            for r_seed in readout_seeds:
                model_id = f"heads-C-sh-d{d_seed}-L{label_n}-r{r_seed}"
                h_file = weights_dir / f"{model_id}.npz"
                specs.append({
                    "model_id": model_id,
                    "arm": "C-sh",
                    "mode": "frozen_heads",
                    "distill_seed": d_seed,
                    "readout_seed": r_seed,
                    "seed": r_seed,
                    "label_n": label_n,
                    "tau": None,
                    "student_file": s_file,
                    "heads_file": h_file,
                })

    # 3. R 的 6 个读出头（L=512，tau=0.02）
    for d_seed in distill_seeds:
        s_file = weights_dir / f"distill-R-s{d_seed}-student.npz"
        for r_seed in readout_seeds:
            model_id = f"heads-R-d{d_seed}-L512-r{r_seed}"
            h_file = weights_dir / f"{model_id}.npz"
            specs.append({
                "model_id": model_id,
                "arm": "R",
                "mode": "frozen_heads",
                "distill_seed": d_seed,
                "readout_seed": r_seed,
                "seed": r_seed,
                "label_n": 512,
                "tau": tau_val,
                "student_file": s_file,
                "heads_file": h_file,
            })

    # 4. A0 的 9 个模型（L=64 来自 dev-distill，L=512/2048 来自本次登记运行）
    for label_n in (64, 512, 2048):
        src_dir = dev_weights if label_n == 64 else weights_dir
        for seed in a0_seeds:
            model_id = f"A0-L{label_n}-s{seed}"
            specs.append({
                "model_id": model_id,
                "arm": "A0",
                "mode": "supervised",
                "distill_seed": None,
                "readout_seed": None,
                "seed": seed,
                "label_n": label_n,
                "tau": None,
                "student_file": src_dir / f"{model_id}-student.npz",
                "heads_file": src_dir / f"{model_id}-heads.npz",
            })

    # 5. A4 的 3 个模型（L=512）
    for seed in a4_seeds:
        model_id = f"A4-L512-s{seed}"
        specs.append({
            "model_id": model_id,
            "arm": "A4",
            "mode": "supervised",
            "distill_seed": None,
            "readout_seed": None,
            "seed": seed,
            "label_n": 512,
            "tau": None,
            "student_file": weights_dir / f"{model_id}-student.npz",
            "heads_file": weights_dir / f"{model_id}-heads.npz",
        })

    # 6. A0-R 的 3 个模型（L=512，tau=0.02）
    for seed in a0r_seeds:
        model_id = f"A0-R-L512-s{seed}"
        specs.append({
            "model_id": model_id,
            "arm": "A0-R",
            "mode": "supervised",
            "distill_seed": None,
            "readout_seed": None,
            "seed": seed,
            "label_n": 512,
            "tau": tau_val,
            "student_file": weights_dir / f"{model_id}-student.npz",
            "heads_file": weights_dir / f"{model_id}-heads.npz",
        })

    # 7. FT 的 9 个全量微调模型（L ∈ {64, 512, 2048}）
    for label_n in (64, 512, 2048):
        for seed in ft_seeds:
            model_id = f"FT-L{label_n}-s{seed}"
            specs.append({
                "model_id": model_id,
                "arm": "FT",
                "mode": "supervised",
                "distill_seed": None,
                "readout_seed": None,
                "seed": seed,
                "label_n": label_n,
                "tau": None,
                "student_file": weights_dir / f"{model_id}-student.npz",
                "heads_file": weights_dir / f"{model_id}-heads.npz",
            })

    return specs


def _load_student_and_heads(
    student_file: Path,
    heads_file: Path,
    student_kw: dict[str, Any],
) -> tuple[Any, Any]:
    from ainerzero.v9.experiments.s5.heads import FlatHead, R1Head, VJEPAProjHead
    from ainerzero.v9.experiments.s5.student import Student
    from ainerzero.v9.experiments.s5.train import HeadsContainer

    student = Student(**student_kw)
    student.load_weights(str(student_file))
    with np.load(heads_file) as npz:
        has_align = any(k.startswith("align_proj.") for k in npz.files)
    heads_map: dict[str, Any] = {
        "r1": R1Head(d=student.d),
        "r2": FlatHead(d=student.d, k=4),
        "r3": FlatHead(d=student.d, k=4),
    }
    if has_align:
        heads_map["align_proj"] = VJEPAProjHead(d=student.d, out_dim=1024)
    heads = HeadsContainer(heads_map)
    heads.load_weights(str(heads_file))
    return student, heads


def _load_ga_checkpoint(
    ckpt_file: Path,
    student_kw: dict[str, Any],
) -> tuple[Any, Any]:
    from ainerzero.v9.experiments.s5.heads import FlatHead, R1Head, VJEPAProjHead
    from ainerzero.v9.experiments.s5.student import Student
    from ainerzero.v9.experiments.s5.train import HeadsContainer, ModelWithHeads

    student = Student(**student_kw)
    with np.load(ckpt_file) as npz:
        has_align = any(k.startswith("heads.align_proj.") for k in npz.files)
    heads_map: dict[str, Any] = {
        "r1": R1Head(d=student.d),
        "r2": FlatHead(d=student.d, k=4),
        "r3": FlatHead(d=student.d, k=4),
    }
    if has_align:
        heads_map["align_proj"] = VJEPAProjHead(d=student.d, out_dim=1024)
    heads = HeadsContainer(heads_map)
    combined = ModelWithHeads(student, heads)
    combined.load_weights(str(ckpt_file))
    return student, heads


def _compute_rlt_restoration_stats(index: ClipIndex, tau: float, cache: ItemCache) -> dict[str, float]:
    """计算 final 分区上 RLT 像素级还原误差 ||patches - restored_patches||_inf 的中位数与 95% 分位（DESIGN-r1.md §4）。"""
    max_errs: list[float] = []
    for i in range(len(index)):
        item = s5_data.load_item(index, i, tau=tau, cache=cache)
        patches = np.asarray(item["patches"], dtype=np.float32)  # [8, 14, 14, 1536]
        keep = np.asarray(item["keep"], dtype=bool)  # [8, 14, 14]
        restored = np.empty_like(patches)
        curr = patches[0]
        restored[0] = curr
        for t in range(1, patches.shape[0]):
            curr = np.where(keep[t, :, :, None], patches[t], curr)
            restored[t] = curr
        err_inf = float(np.max(np.abs(patches - restored)))
        max_errs.append(err_inf)
    return {
        "tau": float(tau),
        "median_linf": float(np.median(max_errs)) if max_errs else 0.0,
        "p95_linf": float(np.percentile(max_errs, 95)) if max_errs else 0.0,
        "max_linf": float(np.max(max_errs)) if max_errs else 0.0,
        "n_clips": len(max_errs),
    }


def compute_gates_from_metrics(
    prereg: dict[str, Any],
    metrics_dir: Path,
    *,
    completed_cells: Sequence[dict[str, Any]],
    rlt_restoration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 metrics_dir 落盘的评测结果与训练日志计算 GT1-GT3、GA、GR 及描述性统计（与独立复算器共享同一口径）。"""
    frozen = prereg["frozen"]
    pinned = prereg["pinned_artifacts"]
    a_star = str(frozen["a_star"])
    partitions = frozen.get("partitions") or REAL_FINAL_PARTITIONS
    final_part = str(partitions["final"])
    shift_part = str(partitions["final_shift"])
    seeds_cfg = frozen.get("seeds") or {}
    distill_seeds = [int(s) for s in seeds_cfg.get("distill", [0, 1])]
    readout_seeds = [int(s) for s in seeds_cfg.get("readout", [0, 1, 2])]
    a0_seeds = [int(s) for s in seeds_cfg.get("A0", [0, 1, 2])]
    a4_seeds = [int(s) for s in seeds_cfg.get("A4", [0, 1, 2])]
    a0r_seeds = [int(s) for s in seeds_cfg.get("A0-R", [0, 1, 2])]
    ft_seeds = [int(s) for s in seeds_cfg.get("FT", [0, 1, 2])]
    n_boot = int(frozen.get("n_boot", N_BOOT))
    boot_seed = int(frozen.get("boot_seed", BOOT_SEED))

    def _distill_nested(arm: str, label_n: int, part_tag: str = final_part) -> list[list[dict[str, Any]]]:
        return [
            [
                load_eval_bundle(metrics_dir, f"heads-{arm}-d{d_seed}-L{label_n}-r{r_seed}", part_tag)
                for r_seed in readout_seeds
            ]
            for d_seed in distill_seeds
        ]

    def _sup_nested(arm_prefix: str, label_n: int, seeds: Sequence[int], part_tag: str = final_part) -> list[list[dict[str, Any]]]:
        return [
            [
                load_eval_bundle(metrics_dir, f"{arm_prefix}-L{label_n}-s{seed}", part_tag)
                for seed in seeds
            ]
        ]

    # 1. GT1, GT2, GT3 (L=64, Bonferroni m=3, level = 1 - 0.05/3)
    astar_l64 = _distill_nested(a_star, 64, final_part)
    csh_l64 = _distill_nested("C-sh", 64, final_part)
    a0_l64 = _sup_nested("A0", 64, a0_seeds, final_part)
    n_worlds = int(astar_l64[0][0]["r2"].shape[0] // astar_l64[0][0]["clips_per_world"])

    gt1_boot = s5_metrics.paired_world_bootstrap(
        n_worlds,
        nested_seed_group_stat(astar_l64, a0_l64, "r2_ap"),
        n_boot=n_boot,
        seed=boot_seed,
        level=GT_LEVEL,
    )
    gt1_astar_stats = seed_dispersion_stats(astar_l64, "r2_ap")
    gt1_a0_stats = seed_dispersion_stats(a0_l64, "r2_ap")
    gt1_pass = bool(
        not math.isnan(gt1_boot["point_estimate"])
        and gt1_boot["point_estimate"] + 1e-12 >= 0.05
        and gt1_boot["ci_lower"] > 0.0
    )

    gt2_boot = s5_metrics.paired_world_bootstrap(
        n_worlds,
        nested_seed_group_stat(astar_l64, csh_l64, "r2_ap"),
        n_boot=n_boot,
        seed=boot_seed,
        level=GT_LEVEL,
    )
    gt2_csh_stats = seed_dispersion_stats(csh_l64, "r2_ap")
    gt2_pass = bool(
        not math.isnan(gt2_boot["point_estimate"])
        and gt2_boot["point_estimate"] + 1e-12 >= 0.03
        and gt2_boot["ci_lower"] > 0.0
    )

    gt3_boot = s5_metrics.paired_world_bootstrap(
        n_worlds,
        nested_seed_group_stat(astar_l64, a0_l64, "r1_rmse"),
        n_boot=n_boot,
        seed=boot_seed,
        level=GT_LEVEL,
    )
    gt3_astar_stats = seed_dispersion_stats(astar_l64, "r1_rmse")
    gt3_a0_stats = seed_dispersion_stats(a0_l64, "r1_rmse")
    gt3_margin = float(0.05 * gt3_a0_stats["mean"])
    gt3_pass = bool(
        not math.isnan(gt3_boot["ci_upper"])
        and gt3_boot["ci_upper"] <= gt3_margin + 1e-12
    )

    # 2. GA (L=512, 96 checkpoints on final)
    a0_tuples: list[tuple[list[float], list[float]]] = []
    a4_tuples: list[tuple[list[float], list[float]]] = []
    cap_candidates: list[float] = []
    for arm_name, arm_seeds, target_list in (("A0", a0_seeds, a0_tuples), ("A4", a4_seeds, a4_tuples)):
        for s in arm_seeds:
            ckpt_json = metrics_dir / f"ckpt-{arm_name}-L512-s{s}.json"
            if not ckpt_json.is_file():
                raise GD.GuardError(f"missing GA curve file: {ckpt_json}")
            cdoc = json.loads(ckpt_json.read_text(encoding="utf-8"))
            steps_seq = [float(x) for x in cdoc["steps"]]
            ap_seq = [float(x) for x in cdoc["r2_ap"]]
            target_list.append((steps_seq, ap_seq))
            if cdoc.get("cap") is not None:
                cap_candidates.append(float(cdoc["cap"]))
            elif steps_seq:
                cap_candidates.append(float(max(steps_seq)))

    ga_cap = float(
        prereg.get("ga_cap")
        if prereg.get("ga_cap") is not None
        else (max(cap_candidates) if cap_candidates else 3840.0)
    )
    ga_res = s5_metrics.ga_decision(a0_tuples, a4_tuples, cap=ga_cap)

    # 3. GR (L=512: keep_rate <= 0.8, distill step wall reduction >= 15% vs C-sh median, R2 AP drop 95% CI upper <= 0.03)
    astar_l512 = _distill_nested(a_star, 512, final_part)
    r_l512 = _distill_nested("R", 512, final_part)
    gr_keep_stats = seed_dispersion_stats(r_l512, "keep_rate")
    gr_keep_rate = float(gr_keep_stats["mean"])
    _eps = 1e-12
    gr_keep_pass = bool(gr_keep_rate <= 0.8 + _eps)

    gr_drop_boot = s5_metrics.paired_world_bootstrap(
        n_worlds,
        nested_seed_group_stat(astar_l512, r_l512, "r2_ap"),
        n_boot=n_boot,
        seed=boot_seed,
        level=GR_LEVEL,
    )
    gr_astar_stats = seed_dispersion_stats(astar_l512, "r2_ap")
    gr_r_stats = seed_dispersion_stats(r_l512, "r2_ap")
    gr_ap_pass = bool(
        not math.isnan(gr_drop_boot["ci_upper"])
        and gr_drop_boot["ci_upper"] <= 0.03 + _eps
    )

    timing_dir = metrics_dir.parent / "timing"
    timing_map: dict[str, float] = {}
    if timing_dir.is_dir():
        for tpath in sorted(timing_dir.glob("*.json")):
            tdoc = json.loads(tpath.read_text(encoding="utf-8"))
            raw_t = tdoc.get("seconds_per_step", tdoc.get("step_seconds"))
            if raw_t is not None:
                timing_map[tpath.stem] = (
                    float(np.median(np.asarray(raw_t, dtype=np.float64)))
                    if isinstance(raw_t, (list, tuple))
                    else float(raw_t)
                )

    cell_by_id = {c["cell_id"]: c for c in completed_cells}
    csh_step_walls: list[float] = []
    r_step_walls: list[float] = []
    for d in distill_seeds:
        c_id = f"distill-C-sh-s{d}"
        r_id = f"distill-R-s{d}"
        if c_id in timing_map:
            csh_step_walls.append(float(timing_map[c_id]))
        elif c_id in cell_by_id:
            csh_step_walls.append(
                float(cell_by_id[c_id].get("median_step_total_s") or cell_by_id[c_id]["wall_per_step_s"])
            )
        if r_id in timing_map:
            r_step_walls.append(float(timing_map[r_id]))
        elif r_id in cell_by_id:
            r_step_walls.append(
                float(cell_by_id[r_id].get("median_step_total_s") or cell_by_id[r_id]["wall_per_step_s"])
            )

    csh_median_step_s = float(np.median(csh_step_walls)) if csh_step_walls else float("nan")
    r_median_step_s = float(np.median(r_step_walls)) if r_step_walls else float("nan")
    step_wall_reduction = (
        float(1.0 - r_median_step_s / csh_median_step_s)
        if csh_median_step_s > 0
        else float("nan")
    )
    gr_wall_pass = bool(math.isfinite(step_wall_reduction) and step_wall_reduction + _eps >= 0.15)
    gr_pass = bool(gr_keep_pass and gr_wall_pass and gr_ap_pass)

    dev_astar_step_map = pinned.get("dev_distill_a_star_step_s") or {}
    dev_astar_vals = [float(v) for v in dev_astar_step_map.values() if isinstance(v, (int, float))]
    dev_astar_median_s = float(np.median(dev_astar_vals)) if dev_astar_vals else None
    dev_astar_reduction = (
        float(1.0 - r_median_step_s / dev_astar_median_s)
        if (dev_astar_median_s is not None and dev_astar_median_s > 0)
        else None
    )

    # 4. 描述性（只报告）统计：各臂 × 各档 L 在 final 与 final-shift (shift_bg, shift_all) 上的表现
    arm_summaries: dict[str, Any] = {}
    for arm in ("A1", "A2", "A3", "C-sh"):
        arm_summaries[arm] = {}
        for label_n in (64, 512, 2048):
            grp_final = _distill_nested(arm, label_n, final_part)
            grp_bg = _distill_nested(arm, label_n, f"{shift_part}.shift_bg")
            grp_all = _distill_nested(arm, label_n, f"{shift_part}.shift_all")
            arm_summaries[arm][f"L{label_n}"] = {
                "r2_ap": seed_dispersion_stats(grp_final, "r2_ap"),
                "r3_ap": seed_dispersion_stats(grp_final, "r3_ap"),
                "r1_rmse": seed_dispersion_stats(grp_final, "r1_rmse"),
                "r1_rmse_object": seed_dispersion_stats(grp_final, "r1_rmse_object"),
                "r1_rmse_floor": seed_dispersion_stats(grp_final, "r1_rmse_floor"),
                "ordering_all": seed_dispersion_stats(grp_final, "ordering_all"),
                "shift_bg_r2_ap": seed_dispersion_stats(grp_bg, "r2_ap"),
                "shift_all_r2_ap": seed_dispersion_stats(grp_all, "r2_ap"),
            }

    # R 臂 (L=512)
    grp_r_bg = _distill_nested("R", 512, f"{shift_part}.shift_bg")
    grp_r_all = _distill_nested("R", 512, f"{shift_part}.shift_all")
    arm_summaries["R"] = {
        "L512": {
            "r2_ap": gr_r_stats,
            "r3_ap": seed_dispersion_stats(r_l512, "r3_ap"),
            "r1_rmse": seed_dispersion_stats(r_l512, "r1_rmse"),
            "keep_rate": gr_keep_stats,
            "shift_bg_r2_ap": seed_dispersion_stats(grp_r_bg, "r2_ap"),
            "shift_all_r2_ap": seed_dispersion_stats(grp_r_all, "r2_ap"),
        }
    }

    # A0 與 FT (L=64, 512, 2048)
    for sup_arm, sup_seeds in (("A0", a0_seeds), ("FT", ft_seeds)):
        arm_summaries[sup_arm] = {}
        for label_n in (64, 512, 2048):
            grp_final = _sup_nested(sup_arm, label_n, sup_seeds, final_part)
            grp_bg = _sup_nested(sup_arm, label_n, sup_seeds, f"{shift_part}.shift_bg")
            grp_all = _sup_nested(sup_arm, label_n, sup_seeds, f"{shift_part}.shift_all")
            arm_summaries[sup_arm][f"L{label_n}"] = {
                "r2_ap": seed_dispersion_stats(grp_final, "r2_ap"),
                "r3_ap": seed_dispersion_stats(grp_final, "r3_ap"),
                "r1_rmse": seed_dispersion_stats(grp_final, "r1_rmse"),
                "r1_rmse_object": seed_dispersion_stats(grp_final, "r1_rmse_object"),
                "r1_rmse_floor": seed_dispersion_stats(grp_final, "r1_rmse_floor"),
                "ordering_all": seed_dispersion_stats(grp_final, "ordering_all"),
                "shift_bg_r2_ap": seed_dispersion_stats(grp_bg, "r2_ap"),
                "shift_all_r2_ap": seed_dispersion_stats(grp_all, "r2_ap"),
            }

    # A4 與 A0-R (L=512)
    for sup_arm, sup_seeds in (("A4", a4_seeds), ("A0-R", a0r_seeds)):
        grp_final = _sup_nested(sup_arm, 512, sup_seeds, final_part)
        grp_bg = _sup_nested(sup_arm, 512, sup_seeds, f"{shift_part}.shift_bg")
        grp_all = _sup_nested(sup_arm, 512, sup_seeds, f"{shift_part}.shift_all")
        entry = {
            "r2_ap": seed_dispersion_stats(grp_final, "r2_ap"),
            "r3_ap": seed_dispersion_stats(grp_final, "r3_ap"),
            "r1_rmse": seed_dispersion_stats(grp_final, "r1_rmse"),
            "shift_bg_r2_ap": seed_dispersion_stats(grp_bg, "r2_ap"),
            "shift_all_r2_ap": seed_dispersion_stats(grp_all, "r2_ap"),
        }
        if sup_arm == "A0-R":
            entry["keep_rate"] = seed_dispersion_stats(grp_final, "keep_rate")
        arm_summaries[sup_arm] = {"L512": entry}

    # 多教师合一描述对比：A3 - max(A1, A2)（DESIGN-r1.md §4）
    multi_teacher: dict[str, Any] = {}
    for label_n in (64, 512, 2048):
        a1_grp = _distill_nested("A1", label_n, final_part)
        a2_grp = _distill_nested("A2", label_n, final_part)
        a3_grp = _distill_nested("A3", label_n, final_part)
        m1 = arm_summaries["A1"][f"L{label_n}"]["r2_ap"]["mean"]
        m2 = arm_summaries["A2"][f"L{label_n}"]["r2_ap"]["mean"]
        best_single_arm = "A1" if m1 >= m2 else "A2"
        best_grp = a1_grp if best_single_arm == "A1" else a2_grp
        mt_r2 = s5_metrics.paired_world_bootstrap(
            n_worlds,
            nested_seed_group_stat(a3_grp, best_grp, "r2_ap"),
            n_boot=n_boot,
            seed=boot_seed,
            level=0.95,
        )
        mt_r1 = s5_metrics.paired_world_bootstrap(
            n_worlds,
            nested_seed_group_stat(a3_grp, best_grp, "r1_rmse"),
            n_boot=n_boot,
            seed=boot_seed,
            level=0.95,
        )
        multi_teacher[f"L{label_n}"] = {
            "best_single_arm": best_single_arm,
            "r2_ap_diff": mt_r2,
            "r1_rmse_diff": mt_r1,
        }

    # 成本描述指标：各臂达到 A0@L=2048 R2 AP 所需墙钟（DESIGN-r1.md §4）
    target_a0_2048_ap = float(arm_summaries["A0"]["L2048"]["r2_ap"]["mean"])
    cost_to_target: dict[str, Any] = {}
    for arm in ("A0", "A1", "A2", "A3", "C-sh", "FT", "A4", "R", "A0-R"):
        best_ap = -1.0
        reached_l = None
        for l_key, l_data in arm_summaries.get(arm, {}).items():
            ap_val = float(l_data["r2_ap"]["mean"])
            if ap_val > best_ap:
                best_ap = ap_val
            if reached_l is None and ap_val >= target_a0_2048_ap:
                reached_l = l_key
        cost_to_target[arm] = {
            "target_a0_l2048_r2_ap": target_a0_2048_ap,
            "reached": reached_l is not None,
            "first_reached_L": reached_l,
            "best_r2_ap": best_ap,
        }

    return {
        "schema": "s5.phase1.gates.v1",
        "a_star": a_star,
        "n_final_worlds": n_worlds,
        "n_boot": n_boot,
        "boot_seed": boot_seed,
        "gt_level": GT_LEVEL,
        "seed_mean_order": "readouts_then_distills",
        "gates": {
            "GT1": {
                "gate": "GT1",
                "passed": gt1_pass,
                "pass": gt1_pass,
                "label_n": 64,
                "metric": "r2_ap_diff",
                "arm": a_star,
                "comparison": f"{a_star} (frozen+heads) - A0",
                "effect": 0.05,
                "min_diff_threshold": 0.05,
                "level": GT_LEVEL,
                "ci_level": GT_LEVEL,
                "bonferroni_m": GT_BONFERRONI_M,
                "point_estimate": float(gt1_boot["point_estimate"]),
                "ci_lower": float(gt1_boot["ci_lower"]),
                "ci_upper": float(gt1_boot["ci_upper"]),
                "seed_std": float(gt1_astar_stats["between_distill_seed_std"]),
                "bootstrap_std": float(gt1_boot["bootstrap_std"]),
                "n_nan": int(gt1_boot["n_nan"]),
                "a_star_stats": gt1_astar_stats,
                "a0_stats": gt1_a0_stats,
            },
            "GT2": {
                "gate": "GT2",
                "passed": gt2_pass,
                "pass": gt2_pass,
                "label_n": 64,
                "metric": "r2_ap_diff",
                "arm": a_star,
                "comparison": f"{a_star} (frozen+heads) - C-sh (frozen+heads)",
                "effect": 0.03,
                "min_diff_threshold": 0.03,
                "level": GT_LEVEL,
                "ci_level": GT_LEVEL,
                "bonferroni_m": GT_BONFERRONI_M,
                "point_estimate": float(gt2_boot["point_estimate"]),
                "ci_lower": float(gt2_boot["ci_lower"]),
                "ci_upper": float(gt2_boot["ci_upper"]),
                "bootstrap_std": float(gt2_boot["bootstrap_std"]),
                "n_nan": int(gt2_boot["n_nan"]),
                "a_star_stats": gt1_astar_stats,
                "c_sh_stats": gt2_csh_stats,
            },
            "GT3": {
                "gate": "GT3",
                "passed": gt3_pass,
                "pass": gt3_pass,
                "label_n": 64,
                "metric": "r1_rmse_diff",
                "arm": a_star,
                "comparison": f"{a_star} (frozen+heads) - A0",
                "margin_frac": 0.05,
                "non_inferiority_frac": 0.05,
                "margin": gt3_margin,
                "margin_threshold": gt3_margin,
                "a0_rmse": float(gt3_a0_stats["mean"]),
                "level": GT_LEVEL,
                "ci_level": GT_LEVEL,
                "bonferroni_m": GT_BONFERRONI_M,
                "point_estimate": float(gt3_boot["point_estimate"]),
                "ci_lower": float(gt3_boot["ci_lower"]),
                "ci_upper": float(gt3_boot["ci_upper"]),
                "bootstrap_std": float(gt3_boot["bootstrap_std"]),
                "n_nan": int(gt3_boot["n_nan"]),
                "a_star_stats": gt3_astar_stats,
                "a0_stats": gt3_a0_stats,
            },
            "GA": {
                "gate": "GA",
                "passed": bool(ga_res["passed"]),
                "pass": bool(ga_res["passed"]),
                "label_n": 512,
                "metric": "r2_ap",
                "point_estimate": float(ga_res["ratio"]),
                "ci_lower": float("nan"),
                "ci_upper": float("nan"),
                "level": float("nan"),
                "ratio": float(ga_res["ratio"]),
                "ratio_max": 0.7,
                "max_median_step_ratio": 0.7,
                "target_ap": float(ga_res["target_ap"]),
                "median_a0": float(ga_res["median_a0"]),
                "median_a4": float(ga_res["median_a4"]),
                "a0_median_steps": float(ga_res["median_a0"]),
                "a4_median_steps": float(ga_res["median_a4"]),
                "a0_steps": ga_res["a0_steps"],
                "a4_steps": ga_res["a4_steps"],
                "a0_censored": ga_res["a0_censored"],
                "a4_censored": ga_res["a4_censored"],
                "stair": ga_res["stair"],
                "cap": ga_cap,
            },
            "GR": {
                "gate": "GR",
                "passed": gr_pass,
                "pass": gr_pass,
                "label_n": 512,
                "arm": a_star,
                "point_estimate": float(gr_drop_boot["point_estimate"]),
                "ci_lower": float(gr_drop_boot["ci_lower"]),
                "ci_upper": float(gr_drop_boot["ci_upper"]),
                "level": float(GR_LEVEL),
                "keep_rate": gr_keep_rate,
                "keep_max": 0.8,
                "max_keep_rate_threshold": 0.8,
                "keep_ok": gr_keep_pass,
                "keep_rate_pass": gr_keep_pass,
                "wall_drop": step_wall_reduction,
                "step_wall_reduction": step_wall_reduction,
                "wall_drop_min": 0.15,
                "min_step_wall_reduction_threshold": 0.15,
                "wall_ok": gr_wall_pass,
                "step_wall_pass": gr_wall_pass,
                "ap_drop_ci_max": 0.03,
                "ap_ok": gr_ap_pass,
                "r_step_median": r_median_step_s if math.isfinite(r_median_step_s) else None,
                "csh_step_median": csh_median_step_s if math.isfinite(csh_median_step_s) else None,
                "csh_distill_step_wall_s": csh_step_walls,
                "r_distill_step_wall_s": r_step_walls,
                "descriptive_dev_distill_a_star_median_step_s": dev_astar_median_s,
                "descriptive_reduction_vs_dev_distill_a_star": dev_astar_reduction,
                "r2_ap_drop": {
                    "comparison": f"{a_star} (frozen+heads) - R (frozen+heads)",
                    "ci_level": GR_LEVEL,
                    "max_ci_upper_threshold": 0.03,
                    "pass": gr_ap_pass,
                    "point_estimate": float(gr_drop_boot["point_estimate"]),
                    "ci_lower": float(gr_drop_boot["ci_lower"]),
                    "ci_upper": float(gr_drop_boot["ci_upper"]),
                    "bootstrap_std": float(gr_drop_boot["bootstrap_std"]),
                    "n_nan": int(gr_drop_boot["n_nan"]),
                },
                "a_star_l512_stats": gr_astar_stats,
                "r_l512_stats": gr_r_stats,
            },
        },
        "descriptive": {
            "arm_summaries": arm_summaries,
            "multi_teacher_a3_minus_max_single": multi_teacher,
            "rlt_restoration_linf": rlt_restoration,
            "cost_to_reach_a0_l2048_r2_ap": cost_to_target,
            "power_reading": "未测",
            "scale_note": "DA2 仅提供相对深度（尺度未知），所有从 DA2 蒸馏的模型只报真值 R1 对数深度读出头误差，不报 DA2 直接米制深度。",
            "external_pretraining": {
                "vjepa2_1_vit_l": "MIT (envs/teachers/src/vjepa2-mlx/LICENSE)",
                "depth_anything_v2_small_coreml": "apache-2.0 per model card (no local license text file bundled)",
                "student_weights": "trained from scratch; teachers used only as distillation/alignment targets",
            },
        },
    }


def _verify_materialized_partition(part_dir: Path, expected_manifest_sha: str) -> None:
    manifest_file = part_dir / "manifest.json"
    if not manifest_file.is_file():
        raise GD.GuardError(f"partition manifest missing: {manifest_file}")
    if sha256_file(manifest_file) != expected_manifest_sha:
        raise GD.GuardError(f"partition manifest SHA mismatch: {manifest_file}")
    doc = json.loads(manifest_file.read_text(encoding="utf-8"))
    for rel, info in (doc.get("files") or {}).items():
        fpath = part_dir / rel
        if not fpath.is_file() or sha256_file(fpath) != info.get("sha256"):
            raise GD.GuardError(f"materialized file corrupted or missing: {fpath}")


def _materialize_and_evaluate(
    prereg: dict[str, Any],
    *,
    run_id: str,
    out: Path,
    weights_dir: Path,
    metrics_dir: Path,
    ckpts_root: Path,
    data_root: Path,
    events: Path,
    eval_attempt: int,
    prior_events: list[dict[str, Any]],
    completed_cells: Sequence[dict[str, Any]],
    repo: Path = REPO,
) -> dict[str, Any]:
    """全部训练格完成后一次性生成 final 与 final-shift，评测 102 个模型 + 96 个 GA 检查点并写出 gates.json。"""
    frozen = prereg["frozen"]
    partitions = frozen.get("partitions") or REAL_FINAL_PARTITIONS
    final_part = str(partitions["final"])
    shift_part = str(partitions["final_shift"])
    n_final = int(frozen["n_final"])
    tau_val = float(frozen.get("tau", RLT_TAU))
    threshold = float(frozen.get("eval_threshold", EVAL_THRESHOLD))
    student_kw = dict(frozen.get("student_kwargs") or {})
    clips = frozen.get("clips")
    standin_test = bool(frozen.get("standin_test", False))

    if standin_test:
        for p_name in (final_part, shift_part):
            if p_name in REAL_REGISTERED_NAMES or "s5p1-final" in p_name or "s5p1-dev" in p_name:
                raise GD.GuardError(f"standin_test must never touch real final or dev partition: {p_name}")
            if not p_name.startswith("s5test-"):
                raise GD.GuardError(f"standin_test final partition must start with 's5test-': {p_name}")
    else:
        if final_part != "s5p1-final" or shift_part != "s5p1-final-shift":
            raise GD.GuardError(f"registered final run requires s5p1-final and s5p1-final-shift, got {final_part}, {shift_part}")
        if not (48 <= n_final <= 96):
            raise GD.GuardError(f"n_final must be in [48, 96], got {n_final}")

    final_dir = data_root / final_part
    shift_dir = data_root / shift_part

    # 检查是否是由 --resume 触发的整段重评
    prior_mat = {
        e["partition"]: e["manifest_sha256"]
        for e in prior_events
        if e.get("event") == "materialize_end" and "partition" in e and "manifest_sha256" in e
    }

    _append(events, {"event": "eval_start", "eval_attempt": eval_attempt, "n_final": n_final})

    orig_world_reg = s5_world.REGISTERED
    orig_mat_reg = s5_mat.REGISTERED
    orig_part_sizes = dict(s5_world.PARTITIONS)
    try:
        if standin_test:
            standin_reg = frozenset(set(orig_world_reg) | {final_part, shift_part})
            s5_world.REGISTERED = standin_reg
            s5_mat.REGISTERED = standin_reg
        for part_name in (final_part, shift_part):
            s5_world.PARTITIONS[part_name] = max(int(s5_world.PARTITIONS.get(part_name, 0)), n_final)

        for part_name, part_dir in ((final_part, final_dir), (shift_part, shift_dir)):
            if eval_attempt > 1 and part_name in prior_mat and part_dir.exists():
                _verify_materialized_partition(part_dir, prior_mat[part_name])
                continue
            if eval_attempt > 1 and part_name not in prior_mat and part_dir.exists():
                shutil.rmtree(part_dir)
            if part_dir.exists():
                raise GD.GuardError(f"final partition directory already exists, refusing to overwrite: {part_dir}")
            materialize_partition(
                part_name,
                part_dir,
                world_range=(0, n_final),
                registered_run_id=run_id,
            )
            # materialize_partition returns the manifest content and writes manifest.json; pin the file (tier-1, 11-13).
            _append(
                events,
                {
                    "event": "materialize_end",
                    "partition": part_name,
                    "n_worlds": n_final,
                    "manifest_sha256": sha256_file(part_dir / "manifest.json"),
                },
            )
    finally:
        s5_world.REGISTERED = orig_world_reg
        s5_mat.REGISTERED = orig_mat_reg
        s5_world.PARTITIONS.clear()
        s5_world.PARTITIONS.update(orig_part_sizes)

    # 若是重评，先清空旧的 metrics 目录以保证整段重评不混入半截旧文件
    if eval_attempt > 1 and metrics_dir.exists():
        shutil.rmtree(metrics_dir)
        metrics_dir.mkdir(parents=True, exist_ok=True)

    final_index = ClipIndex(final_dir, clips=clips)
    shift_index = ClipIndex(shift_dir, clips=clips)

    final_cache = ItemCache()
    shift_bg_cache = ItemCache()
    shift_all_cache = ItemCache()

    model_specs = build_model_specs(prereg, weights_dir, repo=repo)
    eval_files_sha: dict[str, str] = {}

    for spec in model_specs:
        model_id = spec["model_id"]
        tau_model = spec["tau"]
        student, heads = _load_student_and_heads(
            Path(spec["student_file"]),
            Path(spec["heads_file"]),
            student_kw,
        )

        with _bind_eval_item_loader("", final_cache):
            ev_final = s5_eval.evaluate(student, heads, final_index, tau=tau_model, threshold=threshold)
        eval_files_sha.update(_save_eval_artifacts(metrics_dir, model_id, final_part, ev_final))

        with _bind_eval_item_loader("shift_bg", shift_bg_cache):
            ev_shift_bg = s5_eval.evaluate(student, heads, shift_index, tau=tau_model, threshold=threshold)
        eval_files_sha.update(
            _save_eval_artifacts(metrics_dir, model_id, f"{shift_part}.shift_bg", ev_shift_bg)
        )

        with _bind_eval_item_loader("shift_all", shift_all_cache):
            ev_shift_all = s5_eval.evaluate(student, heads, shift_index, tau=tau_model, threshold=threshold)
        eval_files_sha.update(
            _save_eval_artifacts(metrics_dir, model_id, f"{shift_part}.shift_all", ev_shift_all)
        )

        # 同时写合并的 <model_id>.<shift_part>.npz 与 .json（含 shift_bg 与 shift_all 两套数组与指标）
        extra_shift_arrays = {
            "shift_bg_r1_logd": np.asarray(ev_shift_bg["r1_logd"]),
            "shift_bg_r2_logit": np.asarray(ev_shift_bg["r2_logit"]),
            "shift_bg_r3_logit": np.asarray(ev_shift_bg["r3_logit"]),
            "shift_all_r1_logd": np.asarray(ev_shift_all["r1_logd"]),
            "shift_all_r2_logit": np.asarray(ev_shift_all["r2_logit"]),
            "shift_all_r3_logit": np.asarray(ev_shift_all["r3_logit"]),
        }
        if ev_shift_bg.get("keep_rate_per_clip") is not None:
            extra_shift_arrays["shift_bg_keep_rate_per_clip"] = np.asarray(
                ev_shift_bg["keep_rate_per_clip"], dtype=np.float64
            )
        if ev_shift_all.get("keep_rate_per_clip") is not None:
            extra_shift_arrays["shift_all_keep_rate_per_clip"] = np.asarray(
                ev_shift_all["keep_rate_per_clip"], dtype=np.float64
            )
        eval_files_sha.update(
            _save_eval_artifacts(
                metrics_dir,
                model_id,
                shift_part,
                ev_shift_bg,
                extra_arrays=extra_shift_arrays,
                extra_summary={"shift_bg": ev_shift_bg["metrics"], "shift_all": ev_shift_all["metrics"]},
            )
        )

    # 3. GA：A0 L=512 与 A4 L=512 的 2 × 3 × 16 = 96 个检查点，只在 final 上评
    seeds_cfg = frozen.get("seeds") or {}
    a0_seeds = [int(s) for s in seeds_cfg.get("A0", [0, 1, 2])]
    a4_seeds = [int(s) for s in seeds_cfg.get("A4", [0, 1, 2])]
    expected_n_ckpts = int(frozen.get("ga_num_checkpoints", 16))
    ga_records: dict[str, dict[str, list[dict[str, Any]]]] = {"A0": {}, "A4": {}}

    for arm_name, arm_seeds in (("A0", a0_seeds), ("A4", a4_seeds)):
        for seed in arm_seeds:
            cell_id = f"{arm_name}-L512-s{seed}"
            cdir = ckpts_root / cell_id
            ckpt_files = sorted(cdir.glob("step_*.npz"))
            if len(ckpt_files) != expected_n_ckpts:
                raise GD.GuardError(
                    f"GA cell {cell_id} expected {expected_n_ckpts} checkpoints in {cdir}, found {len(ckpt_files)}"
                )
            curve: list[dict[str, Any]] = []
            last_ev_ckpt: dict[str, Any] | None = None
            for ckpt_file in ckpt_files:
                step_num = int(ckpt_file.stem.split("_")[1])
                c_student, c_heads = _load_ga_checkpoint(ckpt_file, student_kw)
                with _bind_eval_item_loader("", final_cache):
                    ev_ckpt = s5_eval.evaluate(c_student, c_heads, final_index, tau=None, threshold=threshold)
                last_ev_ckpt = ev_ckpt
                curve.append({
                    "step": step_num,
                    "r2_ap": float(ev_ckpt["metrics"]["r2_ap"]),
                    "r1_rmse": float(ev_ckpt["metrics"]["r1_rmse"]),
                    "sha256": sha256_file(ckpt_file),
                })
            ga_records[arm_name][str(seed)] = curve

            # 按 SPEC.md 补记 1 写出 metrics/ckpt-{arm}-L512-s{s}.json 及同 stem 的 .{final_part}.npz/.json
            ckpt_model_id = f"ckpt-{arm_name}-L512-s{seed}"
            cap_val = int(prereg.get("ga_cap") or curve[-1]["step"])
            curve_doc = {
                "model_id": ckpt_model_id,
                "arm": arm_name,
                "label_n": 512,
                "seed": seed,
                "steps": [int(pt["step"]) for pt in curve],
                "r2_ap": [float(pt["r2_ap"]) for pt in curve],
                "r1_rmse": [float(pt["r1_rmse"]) for pt in curve],
                "sha256": [str(pt["sha256"]) for pt in curve],
                "cap": cap_val,
            }
            for c_json_path in (
                metrics_dir / f"{ckpt_model_id}.json",
                metrics_dir / f"{ckpt_model_id}.{final_part}.json",
            ):
                c_json_path.write_text(
                    json.dumps(curve_doc, ensure_ascii=False, indent=1, default=_json_default) + "\n",
                    encoding="utf-8",
                )
                eval_files_sha[c_json_path.name] = sha256_file(c_json_path)

            if last_ev_ckpt is not None:
                ckpt_npz_path = metrics_dir / f"{ckpt_model_id}.{final_part}.npz"
                np.savez_compressed(
                    ckpt_npz_path,
                    r1_logd=np.asarray(last_ev_ckpt["r1_logd"]),
                    r2_logit=np.asarray(last_ev_ckpt["r2_logit"]),
                    r3_logit=np.asarray(last_ev_ckpt["r3_logit"]),
                    r1_target=np.asarray(last_ev_ckpt["r1_target"]),
                    r1_sky=np.asarray(last_ev_ckpt["r1_sky"]),
                    r1_obj=np.asarray(last_ev_ckpt["r1_obj"]),
                    r2=np.asarray(last_ev_ckpt["r2"]),
                    r3=np.asarray(last_ev_ckpt["r3"]),
                    world_ids=np.asarray(last_ev_ckpt["world_ids"], dtype=np.int64),
                    clips_per_world=np.asarray(int(last_ev_ckpt["clips_per_world"]), dtype=np.int64),
                )
                eval_files_sha[ckpt_npz_path.name] = sha256_file(ckpt_npz_path)

    ga_json_path = metrics_dir / "ga_checkpoints.json"
    ga_json_path.write_text(
        json.dumps(ga_records, ensure_ascii=False, indent=1, default=_json_default),
        encoding="utf-8",
    )
    eval_files_sha[ga_json_path.name] = sha256_file(ga_json_path)

    rlt_restoration = _compute_rlt_restoration_stats(final_index, tau_val, final_cache)
    gates_doc = compute_gates_from_metrics(
        prereg,
        metrics_dir,
        completed_cells=completed_cells,
        rlt_restoration=rlt_restoration,
    )
    gates_path = out / "gates.json"
    gates_path.write_text(
        json.dumps(gates_doc, ensure_ascii=False, indent=1, default=_json_default),
        encoding="utf-8",
    )
    gates_sha = sha256_file(gates_path)

    _append(
        events,
        {
            "event": "eval_end",
            "eval_attempt": eval_attempt,
            "n_models": len(model_specs),
            "n_ga_checkpoints": sum(len(v) for m in ga_records.values() for v in m.values()),
            "gates_sha256": gates_sha,
        },
    )
    return gates_doc


def _verify_Completed_Cell_Outputs(cell: dict[str, Any], event_row: dict[str, Any], weights_dir: Path, ckpts_root: Path) -> bool:
    """续跑检查：该格不仅要有 cell_end 事件，而且登记的全部输出权重与检查点在盘上的 SHA256 必须一致。"""
    files = event_row.get("files") or {}
    if not files:
        return False
    for fname, want_sha in files.items():
        fpath = weights_dir / fname
        if not fpath.is_file() or sha256_file(fpath) != want_sha:
            return False
    if cell.get("save_ckpts"):
        ckpts = event_row.get("checkpoints") or []
        if not ckpts:
            return False
        for ck in ckpts:
            cpath = Path(ck.get("path", ""))
            if not cpath.is_file():
                cpath = ckpts_root / cell["cell_id"] / cpath.name
            if not cpath.is_file() or sha256_file(cpath) != ck.get("sha256"):
                return False
    return True


def run_final_locked(
    args: argparse.Namespace,
    lock: GD.RunLock,
    *,
    cell_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
) -> int:
    GD._require_held(lock, LOCK)
    GD.require_fresh_pycache(STARTED)

    dev_ledger_before = DEV_LEDGER.read_bytes() if DEV_LEDGER.is_file() else None
    prereg_path = Path(args.prereg).resolve()
    prereg = verify_prereg_and_Save_Check(prereg_path, args.prereg_sha, repo=REPO)
    prereg_sha = sha256_file(prereg_path)
    manifest = prereg["manifest"]
    head, _ = GD.check_git_clean(REPO, list(manifest))

    frozen = prereg["frozen"]
    partitions = frozen.get("partitions") or REAL_FINAL_PARTITIONS
    pool_part = str(partitions["pool"])
    lab_part = str(partitions["lab"])
    final_part = str(partitions["final"])
    shift_part = str(partitions["final_shift"])

    data_root = Path(frozen.get("data_root") or DATA_ROOT)
    if not data_root.is_absolute():
        data_root = (REPO / data_root).resolve()
    teachers_root = Path(frozen.get("teachers_root") or TEACHERS)
    if not teachers_root.is_absolute():
        teachers_root = (REPO / teachers_root).resolve()

    pool_dir = data_root / pool_part
    lab_dir = data_root / lab_part
    if not pool_dir.is_dir() or not lab_dir.is_dir():
        raise GD.GuardError(f"missing pool or lab data directory: {pool_dir}, {lab_dir}")

    # Same layout as run_s5p1.REAL_TEACHERS: teachers/<teacher>/<partition> (tier-1 fix, 11-13).
    pool_teachers = {
        "vjepa": str(teachers_root / "vjepa" / pool_part),
        "da2": str(teachers_root / "da2" / pool_part),
    }
    lab_teachers = {
        "vjepa": str(teachers_root / "vjepa" / lab_part),
    }
    for t_path in (*pool_teachers.values(), *lab_teachers.values()):
        if not (Path(t_path) / "progress.jsonl").is_file():
            raise GD.GuardError(f"missing teacher progress.jsonl under {t_path}")

    resume_mode = bool(getattr(args, "resume", None))
    if resume_mode:
        out = Path(args.resume).resolve()
        if not out.is_dir() or RUNS.resolve() not in out.parents:
            raise GD.GuardError(f"--resume must point to an existing run directory under {RUNS}: {out}")
    else:
        # 新运行启动前，final 与 final-shift 目标目录不得已存在
        for f_part in (final_part, shift_part):
            f_dir = data_root / f_part
            if f_dir.exists():
                raise GD.GuardError(f"final partition directory already exists before run: {f_dir}")
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        out = RUNS / f"final-{args.run_id}-{stamp}"
        if out.exists():
            raise GD.GuardError(f"run directory already exists: {out}")

    report = Path(args.report)
    if not resume_mode or not report.exists():
        GD.claim_report(report)

    begin_registered_run(
        lock,
        REGISTERED_LEDGER,
        run_id=args.run_id,
        prereg_sha=prereg_sha,
        out_dir=out,
        resume=resume_mode,
        expected_lock=LOCK,
    )

    out.mkdir(parents=True, exist_ok=True)
    events = out / "events.jsonl"
    weights_dir = out / "weights"
    metrics_dir = out / "metrics"
    ckpts_root = out / "checkpoints"
    timing_dir = out / "timing"
    weights_dir.mkdir(exist_ok=True)
    metrics_dir.mkdir(exist_ok=True)
    ckpts_root.mkdir(exist_ok=True)
    timing_dir.mkdir(exist_ok=True)
    if not (out / "PREREG.json").is_file():
        shutil.copy2(prereg_path, out / "PREREG.json")

    prior_events: list[dict[str, Any]] = []
    if resume_mode and events.is_file():
        prior_events = [
            json.loads(line)
            for line in events.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        starts = [e for e in prior_events if e.get("event") == "stage_start"]
        if not starts or starts[0].get("run_id") != args.run_id or starts[0].get("prereg_sha256") != prereg_sha:
            raise GD.GuardError("resume directory stage_start does not match --run-id and --prereg-sha")
        resume_count = sum(1 for e in prior_events if e.get("event") == "resume") + 1
        _append(
            events,
            {
                "event": "resume",
                "run_id": args.run_id,
                "prereg_sha256": prereg_sha,
                "resume_count": resume_count,
                "lock": str(LOCK),
            },
        )
    else:
        _append(
            events,
            {
                "event": "stage_start",
                "stage": "final",
                "run_id": args.run_id,
                "prereg_sha256": prereg_sha,
                "lock": str(LOCK),
            },
        )

    prior_cell_ends: dict[str, dict[str, Any]] = {}
    for e in prior_events:
        if e.get("event") == "cell_end" and "cell_id" in e:
            prior_cell_ends[str(e["cell_id"])] = e

    prior_eval_attempts = sum(1 for e in prior_events if e.get("event") == "eval_start")

    budget_s = float(prereg.get("budget", {}).get("budget_s") or (float(prereg["budget"]["budget_h"]) * 3600.0))
    stage_deadline = GD.Deadline(budget_s if budget_s > 0 else DEFAULT_STAGE_LIMIT_S)
    cells = build_final_cells(prereg)
    completed: list[dict[str, Any]] = []
    skipped_on_resume: list[str] = []
    failed: str | None = None
    gpu_retries = 0
    gates_doc: dict[str, Any] | None = None
    eval_attempt = prior_eval_attempts + 1

    ctx = {
        "stage": "final",
        "out": out,
        "weights": weights_dir,
        "metrics": metrics_dir,
        "checkpoints": ckpts_root,
        "teachers": pool_teachers,
        "lab_teachers": lab_teachers,
        "dirs": {pool_part: pool_dir, lab_part: lab_dir},
        "student_kwargs": frozen.get("student_kwargs") or {},
        "clips": frozen.get("clips"),
        "l_worlds_map": frozen.get("l_worlds_map"),
    }

    try:
        stage_deadline.check()
        student_sha_by_cell: dict[str, str] = {}

        for index, cell in enumerate(cells):
            cid = cell["cell_id"]
            if resume_mode and cid in prior_cell_ends:
                prev_row = prior_cell_ends[cid]
                if _verify_Completed_Cell_Outputs(cell, prev_row, weights_dir, ckpts_root):
                    completed.append(prev_row)
                    skipped_on_resume.append(cid)
                    _write_timing_file(timing_dir, prev_row)
                    if cell["kind"] == "distill":
                        s_fname = f"{cid}-student.npz"
                        student_sha_by_cell[cid] = prev_row["files"][s_fname]
                    continue
                # 若旧检查点目录残留在盘上，清理后重跑该格
                if (ckpts_root / cid).exists():
                    shutil.rmtree(ckpts_root / cid)

            if cell["kind"] == "heads" and cell.get("student_cell") in student_sha_by_cell:
                cell = {**cell, "student_sha": student_sha_by_cell[cell["student_cell"]]}

            cell_limit = cell_limit_seconds(index)
            remaining_stage = stage_deadline.left()
            timeout_s = min(cell_limit, remaining_stage)
            if timeout_s <= 0.0:
                failed = f"timeout: stage deadline reached before cell {cid}"
                _append(events, {"event": "cell_fail", "cell_id": cid, "error": "timeout", "limit_s": 0.0, "wall_s": 0.0})
                break

            changed = GD.check_manifest(REPO, manifest)
            if changed:
                failed = "code changed during stage: " + "; ".join(changed[:6])
                _append(events, {"event": "cell_fail", "cell_id": cid, "error": failed})
                break

            start_idx = _index_for_final(
                ctx["dirs"][cell["partition"]],
                ctx["clips"],
                label_n=cell.get("label_n"),
                lab_subset_seed=int(cell.get("lab_subset_seed", LAB_SUBSET_SEED)),
                l_worlds_map={int(k): int(v) for k, v in (ctx["l_worlds_map"] or {}).items()} or None,
            )
            _append(
                events,
                {
                    "event": "cell_start",
                    "cell_id": cid,
                    "index": index,
                    "group": cell.get("group"),
                    "worlds": list(start_idx.worlds),
                    "n_worlds": len(start_idx.worlds),
                    "n_clips": len(start_idx),
                    "label_n": cell.get("label_n"),
                },
            )

            result_path = out / f".cell_{index}_{cid}.result.json"
            err_path = out / f".cell_{index}_{cid}.err.json"
            result_path.unlink(missing_ok=True)
            err_path.unlink(missing_ok=True)

            ctx_data = {
                "stage": ctx["stage"],
                "out": str(ctx["out"]),
                "weights": str(ctx["weights"]),
                "metrics": str(ctx["metrics"]),
                "checkpoints": str(ctx["checkpoints"]),
                "teachers": ctx["teachers"],
                "lab_teachers": ctx["lab_teachers"],
                "dirs": {k: str(v) for k, v in ctx["dirs"].items()},
                "student_kwargs": ctx["student_kwargs"],
                "clips": ctx["clips"],
                "l_worlds_map": ctx["l_worlds_map"],
            }

            mp_ctx = mp.get_context("spawn")
            attempt = 0
            run_attempt = True
            while run_attempt:
                run_attempt = False
                p = mp_ctx.Process(
                    target=_final_cell_worker_target,
                    args=(cell, ctx_data, str(result_path), str(err_path), cell_runner),
                )
                t_cell0 = time.perf_counter()
                p.start()
                p.join(timeout=timeout_s)

                if p.is_alive():
                    p.terminate()
                    p.join(timeout=3.0)
                    if p.is_alive():
                        p.kill()
                        p.join()
                    cell_wall = time.perf_counter() - t_cell0
                    failed = f"timeout: cell {cid} timed out after {timeout_s:.1f}s"
                    _append(events, {"event": "cell_fail", "cell_id": cid, "error": "timeout", "limit_s": timeout_s, "wall_s": cell_wall})
                    break

                if p.exitcode != 0:
                    err_msg = f"cell process exited with code {p.exitcode}"
                    if err_path.is_file():
                        try:
                            err_data = json.loads(err_path.read_text(encoding="utf-8"))
                            err_msg = f"{err_data.get('type')}: {err_data.get('error')}"
                        except Exception:
                            pass
                    retry_left = stage_deadline.left()
                    if (
                        pre.is_gpu_reset(err_msg)
                        and attempt < pre.MAX_GPU_RETRIES_PER_CELL
                        and gpu_retries < pre.MAX_GPU_RETRIES_PER_STAGE
                        and retry_left > 0.0
                    ):
                        attempt += 1
                        gpu_retries += 1
                        aside = pre._set_aside_attempt(ckpts_root, cid, attempt)
                        err_path.unlink(missing_ok=True)
                        result_path.unlink(missing_ok=True)
                        _append(
                            events,
                            {
                                "event": "cell_retry",
                                "cell_id": cid,
                                "attempt": attempt,
                                "error": err_msg,
                                "wall_s": time.perf_counter() - t_cell0,
                                "set_aside": aside,
                            },
                        )
                        changed = GD.check_manifest(REPO, manifest)
                        if changed:
                            failed = "code changed during stage: " + "; ".join(changed[:6])
                            _append(events, {"event": "cell_fail", "cell_id": cid, "error": failed})
                            break
                        timeout_s = min(cell_limit, retry_left)
                        run_attempt = True
                        continue
                    failed = err_msg
                    _append(events, {"event": "cell_fail", "cell_id": cid, "error": failed})
                    break

            if failed:
                break

            if not result_path.is_file():
                failed = f"cell {cid} finished but result file is missing"
                _append(events, {"event": "cell_fail", "cell_id": cid, "error": failed})
                break

            result = json.loads(result_path.read_text(encoding="utf-8"))
            result_path.unlink(missing_ok=True)

            try:
                for fname, expected_sha in (result.get("files") or {}).items():
                    fpath = weights_dir / fname
                    if not fpath.is_file():
                        raise GD.GuardError(f"cell output file missing: {fname}")
                    got_sha = sha256_file(fpath)
                    if got_sha != expected_sha:
                        raise GD.GuardError(f"cell output file SHA mismatch for {fname}: got {got_sha} != {expected_sha}")
            except GD.GuardError as exc:
                failed = str(exc)
                _append(events, {"event": "cell_fail", "cell_id": cid, "error": failed})
                break

            if cell["kind"] == "distill":
                student_sha_by_cell[cid] = result["files"][f"{cid}-student.npz"]
            _write_timing_file(timing_dir, result)
            completed.append(result)
            _append(events, {"event": "cell_end", **result})

        # 全部训练格完成后、评测开始前，再次核对冻结清单与钉住的权重（SPEC.md §2.2 第 5 条）
        if not failed:
            changed = GD.check_manifest(REPO, manifest)
            if changed:
                failed = "code changed before final evaluation: " + "; ".join(changed[:6])
                _append(events, {"event": "stage_fail", "error": failed})
            else:
                verify_pinned_artifacts(prereg, repo=REPO)
                gates_doc = _materialize_and_evaluate(
                    prereg,
                    run_id=args.run_id,
                    out=out,
                    weights_dir=weights_dir,
                    metrics_dir=metrics_dir,
                    ckpts_root=ckpts_root,
                    data_root=data_root,
                    events=events,
                    eval_attempt=eval_attempt,
                    prior_events=prior_events,
                    completed_cells=completed,
                    repo=REPO,
                )
                # 全部结束后再核对一次冻结清单，补上 P242 复核指出的「最后一格」缺口
                changed_after = GD.check_manifest(REPO, manifest)
                if changed_after:
                    failed = "code changed during final evaluation: " + "; ".join(changed_after[:6])
                    _append(events, {"event": "stage_fail", "error": failed})
    except GD.GuardError as exc:
        failed = str(exc)
        _append(events, {"event": "stage_fail", "error": failed})

    finish_registered_run(
        lock,
        REGISTERED_LEDGER,
        run_id=args.run_id,
        prereg_sha=prereg_sha,
        failed=failed,
        expected_lock=LOCK,
    )

    versions = {}
    try:
        versions = GD.third_party_versions(REPO, ("numpy",))
    except GD.GuardError as exc:
        versions = {"error": str(exc)}

    stage_doc = {
        "stage": "final",
        "run_id": args.run_id,
        "prereg_path": str(prereg_path),
        "prereg_sha256": prereg_sha,
        "git_head": head,
        "failed": failed,
        "completed": [row["cell_id"] for row in completed],
        "n_completed": len(completed),
        "skipped_on_resume": skipped_on_resume,
        "eval_attempt": eval_attempt if not failed or prior_eval_attempts > 0 else 0,
        "gpu_retries": gpu_retries,
        "manifest": manifest,
        "third_party": versions,
        "dev_ledger_written": False,
        "registered_ledger_written": True,
        "gates_summary": {k: v.get("pass") for k, v in (gates_doc or {}).get("gates", {}).items()} if gates_doc else None,
    }
    (out / "stage.json").write_text(
        json.dumps(stage_doc, ensure_ascii=False, indent=1, default=_json_default),
        encoding="utf-8",
    )
    report.write_text(
        json.dumps(
            {
                "out": str(out),
                "run_id": args.run_id,
                "prereg_sha256": prereg_sha,
                "failed": failed,
                "n_completed": len(completed),
                "eval_attempt": stage_doc["eval_attempt"],
                "gates": stage_doc["gates_summary"],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    _append(events, {"event": "stage_end", "failed": failed, "n_completed": len(completed)})

    dev_ledger_after = DEV_LEDGER.read_bytes() if DEV_LEDGER.is_file() else None
    if dev_ledger_before != dev_ledger_after:
        raise GD.GuardError("registered final run modified dev-uses.json")
    return 2 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S5 Phase 1 post-freeze registered runner")
    parser.add_argument("--prereg", help="Path to frozen PREREG.json")
    parser.add_argument("--prereg-sha", help="Expected SHA256 of PREREG.json")
    parser.add_argument("--run-id", help="Unique registered run ID")
    parser.add_argument("--report", help="Output report JSON path")
    parser.add_argument("--resume", help="Existing incomplete final run directory to resume")
    parser.add_argument("--dry-run", action="store_true", help="Print cell plan and wall-clock estimate without lock")
    args = parser.parse_args(argv)

    if args.dry_run:
        try:
            prereg_doc = None
            if args.prereg:
                p_path = Path(args.prereg)
                if args.prereg_sha:
                    got = sha256_file(p_path)
                    if got != args.prereg_sha.strip().lower():
                        raise GD.GuardError(f"PREREG SHA mismatch: got {got} != {args.prereg_sha}")
                prereg_doc = json.loads(p_path.read_text(encoding="utf-8"))
            plan_doc = dry_run_plan(prereg_doc)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            return 1
        json.dump(plan_doc, sys.stdout, ensure_ascii=False, indent=1, default=_json_default)
        sys.stdout.write("\n")
        return 0

    if not args.prereg or not args.prereg_sha:
        print("a registered final run requires --prereg and --prereg-sha", file=sys.stderr)
        return 1
    if not args.run_id or not GD.valid_use_id(args.run_id):
        print(f"invalid or missing --run-id: {args.run_id!r}", file=sys.stderr)
        return 1
    if not args.report:
        print("a registered final run requires --report", file=sys.stderr)
        return 1

    # Acquire the shared worker lock before any directory or ledger write
    try:
        with GD.RunLock(LOCK) as lock:
            return run_final_locked(args, lock)
    except GD.GuardError as exc:
        print(str(exc), file=sys.stderr)
        if "lock is busy" in str(exc):
            return 75
        return 1


if __name__ == "__main__":
    sys.exit(main())
