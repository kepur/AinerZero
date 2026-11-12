"""S5 训练循环与蒸馏/读出头训练模块（MLX）。

依据 reports/V9-S5-DESIGN/DESIGN-r1.md §3、§5、§6、§7 实现：
- TrainConfig: 冻结超参数数据类
- distill: 教师特征蒸馏循环（A1/A2/A3/C-sh/R 臂）
- train_supervised: 端到端监督训练（A0/A4/A0-R/全量微调）
- train_heads: 冻结学生仅训练读出头
- predict: 多头预测接口
- 确定性、检查点周期保存与详细日志
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Iterator, Sequence

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_flatten, tree_map
import numpy as np

from ainerzero.v9.experiments.s5.data import (
    ClipIndex,
    ItemCache,
    batches,
    load_item,
    load_teacher,
)
from ainerzero.v9.experiments.s5.heads import (
    DepthDistillHead,
    FlatHead,
    R1Head,
    VJEPAProjHead,
)
from ainerzero.v9.experiments.s5.losses import (
    align_loss,
    cosine_distill_loss,
    permutation,
    ssi_depth_loss,
)
from ainerzero.v9.experiments.s5.student import Student
from ainerzero.v9.experiments.s5.tokens import rlt_keep


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _clip_grad_norm(grads: dict[str, Any], max_norm: float) -> dict[str, Any]:
    flat = tree_flatten(grads)
    total_norm = mx.sqrt(sum(mx.sum(g * g) for _, g in flat))
    scale = mx.minimum(1.0, max_norm / (total_norm + 1e-6))
    return tree_map(lambda g: g * scale, grads)


@dataclass(frozen=True)
class TrainConfig:
    """训练超参数配置类（冻结不可变）。"""

    lr: float = 1e-4
    weight_decay: float = 0.01
    batch_size: int = 8
    epochs: int = 1
    seed: int = 0
    warmup_frac: float = 0.0
    ckpt_every_frac: float = 1.0 / 16.0
    tau: float | None = None
    eta: float | None = None
    align_layer: int = 3
    grad_clip: float | None = None
    ckpt_dir: Path | str | None = None


class HeadsContainer(nn.Module):
    """读出头与投影头的命名组合容器。"""

    def __init__(self, mapping: dict[str, nn.Module] | None = None, **heads: nn.Module):
        super().__init__()
        all_heads = {}
        if mapping:
            all_heads.update(mapping)
        all_heads.update(heads)
        for k, v in all_heads.items():
            setattr(self, k, v)
        self.head_keys = list(all_heads.keys())

    def __getitem__(self, key: str) -> nn.Module:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)


class ModelWithHeads(nn.Module):
    """联合学生与读出头的统一模块容器。"""

    def __init__(self, student: Student, heads: HeadsContainer):
        super().__init__()
        self.student = student
        self.heads = heads


def restore_runs(tokens: mx.array, keep: mx.array | None) -> mx.array:
    """在 RLT 稀疏模式下，将每个空间位置上被并掉 (keep=False) 的 token 还原为其所在游程起点的 token。

    三处共用：A0-R 端到端训练、train_heads 读出头微调、predict 推理。

    参数:
        tokens: [B, 1568, d] 或 [B, 8, 14, 14, d]
        keep: [B, 8, 14, 14] 或 [B, 1568] 布尔掩码；为 None 时直接返回 tokens。
    返回:
        restored: 形状与 tokens 相同，被并掉位置取其所在游程起点 (最近保留管长) 的 token 特征。
    """
    if keep is None:
        return tokens

    orig_shape = tokens.shape
    B = orig_shape[0]
    d = orig_shape[-1]

    t_4d = tokens.reshape(B, 8, 14, 14, d)
    k_3d = keep.reshape(B, 8, 14, 14)

    out_list = [t_4d[:, 0]]
    curr = t_4d[:, 0]

    for t in range(1, 8):
        mask_t = k_3d[:, t, :, :, None]  # [B, 14, 14, 1]
        curr = mx.where(mask_t, t_4d[:, t], curr)
        out_list.append(curr)

    out = mx.stack(out_list, axis=1)  # [B, 8, 14, 14, d]
    return out.reshape(orig_shape)


def _compute_lr(step: int, total_steps: int, cfg: TrainConfig) -> float:
    warmup_steps = int(total_steps * cfg.warmup_frac)
    decay_steps = max(1, total_steps - warmup_steps)
    if step < warmup_steps:
        return cfg.lr * (step + 1) / max(1, warmup_steps)
    p = (step - warmup_steps) / max(1, decay_steps - 1)
    p = min(max(p, 0.0), 1.0)
    return float(0.5 * cfg.lr * (1.0 + math.cos(math.pi * p)))


def _maybe_save_checkpoint(
    step: int,
    total_steps: int,
    model: nn.Module,
    loss_val: float,
    wall_s: float,
    cfg: TrainConfig,
    ckpt_history: list[dict[str, Any]],
) -> None:
    if cfg.ckpt_dir is None:
        return
    ckpt_dir = Path(cfg.ckpt_dir)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    ckpt_interval = max(1, int(round(total_steps * cfg.ckpt_every_frac)))
    is_interval = (step % ckpt_interval == 0)
    is_last = (step == total_steps)

    if is_interval or is_last:
        ckpt_path = ckpt_dir / f"step_{step:06d}.npz"
        flat_weights = dict(tree_flatten(model.parameters()))
        mx.savez(str(ckpt_path), **flat_weights)
        sha = _sha256_file(ckpt_path)
        ckpt_history.append(
            {
                "step": step,
                "path": str(ckpt_path),
                "sha256": sha,
                "loss": float(loss_val),
                "wall_s": float(wall_s),
            }
        )


def distill(
    arm: str,
    index: ClipIndex,
    teachers: str | Path | dict[str, str | Path],
    cfg: TrainConfig,
    *,
    perm_seed: int | None = None,
    student: Student | None = None,
    heads: HeadsContainer | dict[str, nn.Module] | None = None,
    cache: ItemCache | None = None,
) -> tuple[Student, HeadsContainer, dict[str, Any]]:
    """教师特征蒸馏训练循环（A1、A2、A3、C-sh、R 臂）。"""
    if arm not in ("A1", "A2", "A3"):
        raise ValueError(f"Unknown arm {arm!r}; expected 'A1', 'A2', or 'A3'")

    active_cache = cache if cache is not None else ItemCache()
    t_types = ("da2",) if arm == "A1" else (("vjepa",) if arm == "A2" else ("vjepa", "da2"))

    mx.random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    # 1. 初始化模型
    if student is None:
        student = Student()

    if heads is None:
        heads_dict: dict[str, nn.Module] = {}
        if arm in ("A1", "A3"):
            heads_dict["da2"] = DepthDistillHead(d=student.d)
        if arm in ("A2", "A3"):
            heads_dict["vjepa"] = VJEPAProjHead(d=student.d, out_dim=1024)
        heads_container = HeadsContainer(**heads_dict)
    elif isinstance(heads, dict):
        heads_container = HeadsContainer(**heads)
    else:
        heads_container = heads

    combined_model = ModelWithHeads(student, heads_container)

    # 2. 准备错排映射（C-sh 专用）
    perm_map = None
    if perm_seed is not None:
        perm_mx = permutation(len(index), perm_seed)
        perm_map = np.array(perm_mx)

    # 3. 优化器准备
    total_steps = max(1, cfg.epochs * (len(index) // cfg.batch_size))
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=cfg.weight_decay)

    log: dict[str, Any] = {
        "arm": arm,
        "perm_seed": perm_seed,
        "tau": cfg.tau,
        "total_steps": total_steps,
        "step_logs": [],
        "checkpoints": [],
        "start_time": time.time(),
    }

    step = 0
    t_start_all = time.perf_counter()

    for epoch in range(cfg.epochs):
        for b_indices in batches(index, cfg.batch_size, cfg.seed, epoch):
            step += 1
            t_data_0 = time.perf_counter()

            # 数据读取
            patches_list = []
            da2_list = []
            vjepa_list = []
            keep_list = []
            run_len_list = []

            for b_idx in b_indices:
                s_item = load_item(index, b_idx, appearance_suffix="", cache=active_cache)
                patches_list.append(s_item["patches"])

                # 教师特征来源：普通情况来自 b_idx，C-sh 来自 perm_map[b_idx]
                t_idx = perm_map[b_idx] if perm_map is not None else b_idx
                t_item = load_teacher(index, t_idx, teachers, teacher_types=t_types, cache=active_cache)
                if arm in ("A1", "A3"):
                    da2_list.append(t_item["da2"])
                if arm in ("A2", "A3"):
                    vjepa_list.append(t_item["vjepa"])

                if cfg.tau is not None:
                    k, rl = rlt_keep(s_item["patches"], cfg.tau)
                    keep_list.append(k)
                    run_len_list.append(rl)

            patches_mx = mx.array(np.stack(patches_list, axis=0))  # [B, 8, 14, 14, 1536]
            da2_mx = mx.array(np.stack(da2_list, axis=0)) if da2_list else None  # [B, 8, 56, 56]
            vjepa_mx = mx.array(np.stack(vjepa_list, axis=0)) if vjepa_list else None  # [B, 1568, 1024]

            keep_mx = mx.array(np.stack(keep_list, axis=0)) if keep_list else None
            run_len_mx = mx.array(np.stack(run_len_list, axis=0)) if run_len_list else None

            data_dt = time.perf_counter() - t_data_0

            # 学习率调度
            lr_t = _compute_lr(step - 1, total_steps, cfg)
            opt.learning_rate = lr_t

            # 前向与损失计算
            def loss_fn(model: ModelWithHeads) -> mx.array:
                tokens, mask = model.student(patches_mx, keep=keep_mx, run_len=run_len_mx)
                total_loss = mx.array(0.0)

                # A1 / A3 深度蒸馏损失
                if arm in ("A1", "A3"):
                    pred_da2 = model.heads["da2"](tokens)
                    valid_mask = None
                    if keep_mx is not None:
                        # R 臂：将 keep (8, 14, 14) 扩展为 56x56 掩码，被并掉区域从 valid 中去掉
                        keep_56 = mx.repeat(mx.repeat(keep_mx, 4, axis=-2), 4, axis=-1)
                        valid_mask = keep_56
                    l_da2 = ssi_depth_loss(pred_da2, da2_mx, valid=valid_mask)
                    total_loss = total_loss + l_da2

                # A2 / A3 V-JEPA 蒸馏损失
                if arm in ("A2", "A3"):
                    proj_vjepa = model.heads["vjepa"](tokens)
                    l_vjepa = cosine_distill_loss(proj_vjepa, vjepa_mx, mask=mask)
                    total_loss = total_loss + l_vjepa

                return total_loss

            t_step_0 = time.perf_counter()
            loss_val, grads = nn.value_and_grad(combined_model, loss_fn)(combined_model)

            if cfg.grad_clip is not None:
                grads = _clip_grad_norm(grads, cfg.grad_clip)

            opt.update(combined_model, grads)
            mx.eval(combined_model.parameters(), opt.state, loss_val)

            step_dt = time.perf_counter() - t_step_0
            current_loss = float(loss_val.item())

            log["step_logs"].append(
                {
                    "step": step,
                    "loss": current_loss,
                    "lr": lr_t,
                    "data_s": data_dt,
                    "step_s": step_dt,
                }
            )

            wall_so_far = time.perf_counter() - t_start_all
            _maybe_save_checkpoint(
                step,
                total_steps,
                combined_model,
                current_loss,
                wall_so_far,
                cfg,
                log["checkpoints"],
            )

    log["total_wall_s"] = time.perf_counter() - t_start_all
    return student, heads_container, log


def train_supervised(
    index: ClipIndex,
    cfg: TrainConfig,
    *,
    teachers: str | Path | dict[str, str | Path] | None = None,
    init_student: Student | None = None,
    student: Student | None = None,
    heads: HeadsContainer | dict[str, nn.Module] | None = None,
    cache: ItemCache | None = None,
) -> tuple[Student, HeadsContainer, dict[str, Any]]:
    """端到端监督训练学生与读出头（A0、A4、A0-R、A* 全量微调）。"""
    active_cache = cache if cache is not None else ItemCache()
    mx.random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    if init_student is not None:
        curr_student = init_student
    elif student is not None:
        curr_student = student
    else:
        curr_student = Student()

    heads_dict: dict[str, nn.Module] = {}
    if isinstance(heads, HeadsContainer):
        for k in heads.head_keys:
            heads_dict[k] = heads[k]
    elif isinstance(heads, dict):
        heads_dict.update(heads)

    if "r1" not in heads_dict:
        heads_dict["r1"] = R1Head(d=curr_student.d)
    if "r2" not in heads_dict:
        heads_dict["r2"] = FlatHead(d=curr_student.d, k=4)
    if "r3" not in heads_dict:
        heads_dict["r3"] = FlatHead(d=curr_student.d, k=4)
    if cfg.eta is not None and "align_proj" not in heads_dict:
        heads_dict["align_proj"] = VJEPAProjHead(d=curr_student.d, out_dim=1024)

    heads_container = HeadsContainer(**heads_dict)

    combined_model = ModelWithHeads(curr_student, heads_container)

    total_steps = max(1, cfg.epochs * (len(index) // cfg.batch_size))
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=cfg.weight_decay)

    log: dict[str, Any] = {
        "eta": cfg.eta,
        "tau": cfg.tau,
        "total_steps": total_steps,
        "step_logs": [],
        "checkpoints": [],
        "start_time": time.time(),
    }

    step = 0
    t_start_all = time.perf_counter()

    for epoch in range(cfg.epochs):
        for b_indices in batches(index, cfg.batch_size, cfg.seed, epoch):
            step += 1
            t_data_0 = time.perf_counter()

            patches_list = []
            r1_logd_list = []
            r1_sky_list = []
            r2_list = []
            r3_list = []
            vjepa_list = []
            keep_list = []
            run_len_list = []

            for b_idx in b_indices:
                item = load_item(
                    index,
                    b_idx,
                    teachers=teachers if cfg.eta is not None else None,
                    cache=active_cache,
                )
                patches_list.append(item["patches"])
                r1_logd_list.append(item["r1_logd"])
                r1_sky_list.append(item["r1_sky"])
                r2_list.append(item["r2"])
                r3_list.append(item["r3"])

                if cfg.eta is not None and "vjepa" in item:
                    vjepa_list.append(item["vjepa"])

                if cfg.tau is not None:
                    k, rl = rlt_keep(item["patches"], cfg.tau)
                    keep_list.append(k)
                    run_len_list.append(rl)

            patches_mx = mx.array(np.stack(patches_list, axis=0))
            r1_logd_mx = mx.array(np.stack(r1_logd_list, axis=0))
            r1_sky_mx = mx.array(np.stack(r1_sky_list, axis=0))
            r2_mx = mx.array(np.stack(r2_list, axis=0))
            r3_mx = mx.array(np.stack(r3_list, axis=0))

            vjepa_mx = mx.array(np.stack(vjepa_list, axis=0)) if vjepa_list else None
            keep_mx = mx.array(np.stack(keep_list, axis=0)) if keep_list else None
            run_len_mx = mx.array(np.stack(run_len_list, axis=0)) if run_len_list else None

            data_dt = time.perf_counter() - t_data_0

            lr_t = _compute_lr(step - 1, total_steps, cfg)
            opt.learning_rate = lr_t

            def loss_fn(model: ModelWithHeads) -> mx.array:
                tokens, mask = model.student(patches_mx, keep=keep_mx, run_len=run_len_mx)

                # R1 深度损失
                r1_tokens = restore_runs(tokens, keep_mx)
                pred_logd, pred_sky = model.heads["r1"](r1_tokens)
                l_r1 = model.heads["r1"].loss(pred_logd, pred_sky, r1_logd_mx, r1_sky_mx)

                # R2 / R3：与 R1 同一份 token。开 RLT 时已是 restore_runs 的结果，不再传注意力掩码。
                logits_r2 = model.heads["r2"](r1_tokens)
                l_r2 = model.heads["r2"].loss(logits_r2, r2_mx)

                logits_r3 = model.heads["r3"](r1_tokens)
                l_r3 = model.heads["r3"].loss(logits_r3, r3_mx)

                tot_loss = l_r1 + l_r2 + l_r3

                # A4 对齐损失
                if cfg.eta is not None and vjepa_mx is not None:
                    actual_layer = (
                        min(cfg.align_layer, len(model.student.blocks))
                        if cfg.align_layer > 0
                        else cfg.align_layer
                    )
                    feat = model.student.features(layer=actual_layer)
                    proj_feat = model.heads["align_proj"](feat)
                    l_align = align_loss(proj_feat, vjepa_mx, mask=mask)
                    tot_loss = tot_loss + cfg.eta * l_align

                return tot_loss

            t_step_0 = time.perf_counter()
            loss_val, grads = nn.value_and_grad(combined_model, loss_fn)(combined_model)

            if cfg.grad_clip is not None:
                grads = _clip_grad_norm(grads, cfg.grad_clip)

            opt.update(combined_model, grads)
            mx.eval(combined_model.parameters(), opt.state, loss_val)

            step_dt = time.perf_counter() - t_step_0
            current_loss = float(loss_val.item())

            log["step_logs"].append(
                {
                    "step": step,
                    "loss": current_loss,
                    "lr": lr_t,
                    "data_s": data_dt,
                    "step_s": step_dt,
                }
            )

            wall_so_far = time.perf_counter() - t_start_all
            _maybe_save_checkpoint(
                step,
                total_steps,
                combined_model,
                current_loss,
                wall_so_far,
                cfg,
                log["checkpoints"],
            )

    log["total_wall_s"] = time.perf_counter() - t_start_all
    return curr_student, heads_container, log


def train_heads(
    student: Student,
    index: ClipIndex,
    cfg: TrainConfig,
    *,
    heads: HeadsContainer | dict[str, nn.Module] | None = None,
    cache_dir: str | Path | None = None,
    cache: ItemCache | None = None,
) -> tuple[HeadsContainer, dict[str, Any]]:
    """学生冻结，仅训练读出头（R1Head 与两个 FlatHead）。"""
    active_cache = cache if cache is not None else ItemCache()
    mx.random.seed(cfg.seed)
    np.random.seed(cfg.seed)

    heads_dict: dict[str, nn.Module] = {}
    if isinstance(heads, HeadsContainer):
        for k in heads.head_keys:
            heads_dict[k] = heads[k]
    elif isinstance(heads, dict):
        heads_dict.update(heads)

    if "r1" not in heads_dict:
        heads_dict["r1"] = R1Head(d=student.d)
    if "r2" not in heads_dict:
        heads_dict["r2"] = FlatHead(d=student.d, k=4)
    if "r3" not in heads_dict:
        heads_dict["r3"] = FlatHead(d=student.d, k=4)

    heads_container = HeadsContainer(**heads_dict)

    # 1. 前置抽取并缓存学生 tokens（带 stop_gradient，完全不构建学生反传图）
    cached_tokens: list[tuple[mx.array, mx.array, mx.array | None]] = []
    t_cache_0 = time.perf_counter()

    for i in range(len(index)):
        item = load_item(index, i, cache=active_cache)
        patches_mx = mx.array(item["patches"][None, ...])
        if cfg.tau is not None:
            k, rl = rlt_keep(item["patches"], cfg.tau)
            k_mx = mx.array(k[None, ...])
            rl_mx = mx.array(rl[None, ...])
            t_out, m_out = student(patches_mx, keep=k_mx, run_len=rl_mx)
            k_saved = k_mx[0]
        else:
            t_out, m_out = student(patches_mx)
            k_saved = None

        # 显式截断梯度并保持在内存
        mx.eval(t_out, m_out)
        cached_tokens.append((mx.stop_gradient(t_out[0]), mx.stop_gradient(m_out[0]), k_saved))

    cache_dt = time.perf_counter() - t_cache_0

    # 2. 优化读出头
    total_steps = max(1, cfg.epochs * (len(index) // cfg.batch_size))
    opt = optim.AdamW(learning_rate=cfg.lr, weight_decay=cfg.weight_decay)

    log: dict[str, Any] = {
        "cache_time_s": cache_dt,
        "total_steps": total_steps,
        "step_logs": [],
        "checkpoints": [],
        "start_time": time.time(),
    }

    step = 0
    t_start_all = time.perf_counter()

    for epoch in range(cfg.epochs):
        for b_indices in batches(index, cfg.batch_size, cfg.seed, epoch):
            step += 1
            t_data_0 = time.perf_counter()

            tokens_list = [cached_tokens[b][0] for b in b_indices]
            keep_list = [cached_tokens[b][2] for b in b_indices]

            r1_logd_list = []
            r1_sky_list = []
            r2_list = []
            r3_list = []

            for b in b_indices:
                it = load_item(index, b, cache=active_cache)
                r1_logd_list.append(it["r1_logd"])
                r1_sky_list.append(it["r1_sky"])
                r2_list.append(it["r2"])
                r3_list.append(it["r3"])

            b_tokens = mx.stack(tokens_list, axis=0)
            b_keep = mx.stack(keep_list, axis=0) if keep_list[0] is not None else None
            r1_logd_mx = mx.array(np.stack(r1_logd_list, axis=0))
            r1_sky_mx = mx.array(np.stack(r1_sky_list, axis=0))
            r2_mx = mx.array(np.stack(r2_list, axis=0))
            r3_mx = mx.array(np.stack(r3_list, axis=0))

            data_dt = time.perf_counter() - t_data_0

            lr_t = _compute_lr(step - 1, total_steps, cfg)
            opt.learning_rate = lr_t

            def loss_fn(model_heads: HeadsContainer) -> mx.array:
                r1_tokens = restore_runs(b_tokens, b_keep)
                pred_logd, pred_sky = model_heads["r1"](r1_tokens)
                l_r1 = model_heads["r1"].loss(pred_logd, pred_sky, r1_logd_mx, r1_sky_mx)

                logits_r2 = model_heads["r2"](r1_tokens)
                l_r2 = model_heads["r2"].loss(logits_r2, r2_mx)

                logits_r3 = model_heads["r3"](r1_tokens)
                l_r3 = model_heads["r3"].loss(logits_r3, r3_mx)

                return l_r1 + l_r2 + l_r3

            t_step_0 = time.perf_counter()
            loss_val, grads = nn.value_and_grad(heads_container, loss_fn)(heads_container)

            if cfg.grad_clip is not None:
                grads = _clip_grad_norm(grads, cfg.grad_clip)

            opt.update(heads_container, grads)
            mx.eval(heads_container.parameters(), opt.state, loss_val)

            step_dt = time.perf_counter() - t_step_0
            current_loss = float(loss_val.item())

            log["step_logs"].append(
                {
                    "step": step,
                    "loss": current_loss,
                    "lr": lr_t,
                    "data_s": data_dt,
                    "step_s": step_dt,
                }
            )

            wall_so_far = time.perf_counter() - t_start_all
            _maybe_save_checkpoint(
                step,
                total_steps,
                heads_container,
                current_loss,
                wall_so_far,
                cfg,
                log["checkpoints"],
            )

    log["total_wall_s"] = time.perf_counter() - t_start_all
    return heads_container, log


def predict(
    student: Student,
    heads: HeadsContainer | dict[str, nn.Module],
    index: ClipIndex,
    *,
    tau: float | None = None,
    batch_size: int = 16,
    cache: ItemCache | None = None,
) -> dict[str, Any]:
    """多头预测接口：输出 r1_logd [N, 16, 14, 14]、r2_logit [N, 12, 7]、r3_logit [N, 12, 7]。"""
    active_cache = cache if cache is not None else ItemCache()
    heads_container = heads if isinstance(heads, HeadsContainer) else HeadsContainer(**heads)

    r1_logd_all = []
    r2_logit_all = []
    r3_logit_all = []
    keep_rates = []

    for i in range(len(index)):
        item = load_item(index, i, cache=active_cache)
        patches_mx = mx.array(item["patches"][None, ...])

        if tau is not None:
            k, rl = rlt_keep(item["patches"], tau)
            keep_rates.append(float(np.mean(k)))
            k_mx = mx.array(k[None, ...])
            rl_mx = mx.array(rl[None, ...])
            tokens, _mask = student(patches_mx, keep=k_mx, run_len=rl_mx)
        else:
            tokens, _mask = student(patches_mx)

        r1_tokens = restore_runs(tokens, k_mx if tau is not None else None)
        pred_logd, _ = heads_container["r1"](r1_tokens)
        r2_logit = heads_container["r2"](r1_tokens)
        r3_logit = heads_container["r3"](r1_tokens)

        mx.eval(pred_logd, r2_logit, r3_logit)
        r1_logd_all.append(np.array(pred_logd[0]))
        r2_logit_all.append(np.array(r2_logit[0]))
        r3_logit_all.append(np.array(r3_logit[0]))

    res: dict[str, Any] = {
        "r1_logd": np.stack(r1_logd_all, axis=0),
        "r2_logit": np.stack(r2_logit_all, axis=0),
        "r3_logit": np.stack(r3_logit_all, axis=0),
    }
    if tau is not None:
        res["keep_rate"] = float(np.mean(keep_rates))
    return res
