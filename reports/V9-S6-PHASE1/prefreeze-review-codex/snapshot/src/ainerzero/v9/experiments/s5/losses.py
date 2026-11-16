"""S5 损失函数与置换工具模块（MLX）。

包含：
- `ssi_depth_loss`：MiDaS 尺度与平移不变深度损失（支持逐帧最小二乘对齐后算 L1）；
- `cosine_distill_loss`：学生投影与教师特征余弦蒸馏损失（1 - cos）；
- `align_loss`：式 11 对齐损失（教师侧显式 stop_gradient）；
- `permutation`：C-sh 用的固定错排（Derangement），保证不动点为 0。
"""
from __future__ import annotations

import mlx.core as mx
import numpy as np


def ssi_depth_loss(
    pred: mx.array,
    target: mx.array,
    valid: mx.array | None = None,
    eps: float = 1e-6,
) -> mx.array:
    """MiDaS 尺度与平移不变深度损失（Scale-and-Shift Invariant Loss）。

    对每个样本/帧，通过最小二乘法求尺度 s 与平移 t：
        min_{s, t} || (s * pred + t) - target ||^2
    解析解：
        s = cov(pred, target) / (var(pred) + eps)
        t = mean(target) - s * mean(pred)
    随后计算对齐后预测值与目标的 L1 误差：
        L_ssi = mean(| (s * pred + t) - target |)

    参数：
        pred: [B, 8, 56, 56] 或任意 [..., H, W] 预测张量
        target: [B, 8, 56, 56] 或同形目标张量
        valid: 可选布尔/浮点有效像素掩码；若为 None 则全部有限像素有效
        eps: 数值稳定微小项

    数学性质：
        对任意 a > 0 与任意 b，pred -> a * pred + b 时损失严格不变。
    """
    orig_shape = pred.shape
    spatial_dim = orig_shape[-2] * orig_shape[-1]
    batch_frames = int(np.prod(orig_shape[:-2]))

    p_flat = pred.reshape(batch_frames, spatial_dim)
    t_flat = target.reshape(batch_frames, spatial_dim)

    if valid is not None:
        v_flat = valid.reshape(batch_frames, spatial_dim).astype(mx.float32)
        n_valid = mx.sum(v_flat, axis=-1, keepdims=True) + eps
        p_mean = mx.sum(p_flat * v_flat, axis=-1, keepdims=True) / n_valid
        t_mean = mx.sum(t_flat * v_flat, axis=-1, keepdims=True) / n_valid

        p_center = (p_flat - p_mean) * v_flat
        t_center = (t_flat - t_mean) * v_flat

        var_p = mx.sum(p_center * p_center, axis=-1, keepdims=True) + eps
        cov_pt = mx.sum(p_center * t_center, axis=-1, keepdims=True)

        s = cov_pt / var_p
        t_shift = t_mean - s * p_mean
        p_aligned = s * p_flat + t_shift
        l1_err = mx.abs(p_aligned - t_flat) * v_flat
        return mx.sum(l1_err) / (mx.sum(n_valid) + eps)
    else:
        p_mean = mx.mean(p_flat, axis=-1, keepdims=True)
        t_mean = mx.mean(t_flat, axis=-1, keepdims=True)

        p_center = p_flat - p_mean
        t_center = t_flat - t_mean

        var_p = mx.sum(p_center * p_center, axis=-1, keepdims=True) + eps
        cov_pt = mx.sum(p_center * t_center, axis=-1, keepdims=True)

        s = cov_pt / var_p
        t_shift = t_mean - s * p_mean
        p_aligned = s * p_flat + t_shift
        return mx.mean(mx.abs(p_aligned - t_flat))


def cosine_distill_loss(
    student_proj: mx.array,
    teacher: mx.array,
    mask: mx.array | None = None,
    eps: float = 1e-6,
) -> mx.array:
    """余弦蒸馏损失：1 - cos(student, teacher)，按 mask 平均。

    参数：
        student_proj: [B, N, D]
        teacher: [B, N, D]
        mask: 可选 [B, N] 布尔或浮点权重
    """
    dot = mx.sum(student_proj * teacher, axis=-1)
    norm_s = mx.sqrt(mx.sum(student_proj * student_proj, axis=-1) + eps)
    norm_t = mx.sqrt(mx.sum(teacher * teacher, axis=-1) + eps)
    cos_sim = dot / (norm_s * norm_t)
    loss_per_token = 1.0 - cos_sim

    if mask is not None:
        m = mask.astype(mx.float32)
        total_tokens = mx.sum(m) + eps
        return mx.sum(loss_per_token * m) / total_tokens

    return mx.mean(loss_per_token)


def align_loss(
    student_proj: mx.array,
    teacher: mx.array,
    mask: mx.array | None = None,
    eps: float = 1e-6,
) -> mx.array:
    """式 11 对齐损失：1 - cos(h_phi(z^{(l)}), sg(T(x)))。

    教师一侧显式施加 mx.stop_gradient，保证无教师反传梯度。
    """
    teacher_sg = mx.stop_gradient(teacher)
    return cosine_distill_loss(student_proj, teacher_sg, mask=mask, eps=eps)


def permutation(n: int, seed: int) -> mx.array:
    """生成长度为 n 的确定性错排（Derangement），严格无任何不动点（fixed point = 0）。

    采用 Sattolo 算法生成单一全长随机环，保证 pi(i) != i 对所有 i 成立。
    """
    if n <= 1:
        raise ValueError(f"Derangement is impossible for n={n}")

    rng = np.random.default_rng(seed)
    p = np.arange(n)
    for i in range(n - 1, 0, -1):
        j = rng.integers(0, i)  # 严格 j < i
        p[i], p[j] = p[j], p[i]

    return mx.array(p)
