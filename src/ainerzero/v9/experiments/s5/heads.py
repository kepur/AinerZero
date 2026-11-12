"""S5 读出头与投影头模块（MLX）。

包含：
- `R1Head`：线性映射预测 2 帧对数深度与天空占比，与 `labels.r1` 的 [16, 14, 14] 对齐（NaN 缺失块不计损失）；
- `GridHead`：注意力池化（1 个可学查询按 mask 池化）+ 2 层 MLP，输出 [12, 7] 占用 logits 与 BCE 损失；
- `FlatHead`：只读最后一个管长，逐 token 打 k 分，再按位置线性映射到 [12, 7]（R2/R3 现用这个头）；
- `DepthDistillHead`：每个 token 线性输出 4×4，重组成 [8, 56, 56] 空间网格；
- `VJEPAProjHead`：线性 192 -> 1024 维度投影。
"""
from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn


class R1Head(nn.Module):
    """R1 读出头：预测每个 Tubelet 块对应 2 帧的 log(深度) 与天空占比。"""

    def __init__(self, d: int = 192):
        super().__init__()
        # 每个 token 对应 2 帧：[logd_0, logd_1, sky_0, sky_1]
        self.proj = nn.Linear(d, 4)

    def __call__(self, tokens: mx.array) -> tuple[mx.array, mx.array]:
        """前向预测。

        参数:
            tokens: [B, 1568, d] 或 [B, 8, 14, 14, d]
        返回:
            pred_logd: [B, 16, 14, 14]
            pred_sky: [B, 16, 14, 14]
        """
        B = tokens.shape[0]
        if tokens.ndim == 3:
            tokens = tokens.reshape(B, 8, 14, 14, -1)

        out = self.proj(tokens)  # [B, 8, 14, 14, 4]
        logd_2f = out[..., :2]  # [B, 8, 14, 14, 2]
        sky_2f = out[..., 2:]   # [B, 8, 14, 14, 2]

        # 重组成 [B, 16, 14, 14]：帧顺序为 2*t + dt
        pred_logd = logd_2f.transpose(0, 1, 4, 2, 3).reshape(B, 16, 14, 14)
        pred_sky = sky_2f.transpose(0, 1, 4, 2, 3).reshape(B, 16, 14, 14)

        return pred_logd, pred_sky

    def loss(
        self,
        pred_logd: mx.array,
        pred_sky: mx.array,
        target_logd: mx.array,
        target_sky: mx.array,
        eps: float = 1e-6,
    ) -> mx.array:
        """计算 R1 损失。全天空导致的 NaN 块不计入深度损失。"""
        # 1. 深度损失：仅对非 NaN 的有效块计算 L1
        valid_logd = ~mx.isnan(target_logd)
        v_float = valid_logd.astype(mx.float32)

        # 对 NaN 位置填充 0 以防梯度污染
        clean_target = mx.where(valid_logd, target_logd, mx.zeros_like(target_logd))
        l1_depth = mx.abs(pred_logd - clean_target) * v_float
        depth_loss = mx.sum(l1_depth) / (mx.sum(v_float) + eps)

        # 2. 天空占比损失：BCE 或 L1
        sky_loss = mx.mean(mx.abs(pred_sky - target_sky))

        return depth_loss + sky_loss


class GridHead(nn.Module):
    """自我中心极坐标圆盘网格占据读出头（用于 R2 与 R3）。

    结构：
    - 1 个可学查询（Learnable Query）
    - 注意力池化（带注意力掩码，忽略被并掉或 padding 的 token）
    - LayerNorm 归一化
    - 两层 MLP + GELU
    - 输出 [B, 12, 7] logits
    """

    def __init__(self, out: tuple[int, int] = (12, 7), d: int = 192, heads: int = 3):
        super().__init__()
        self.out = out
        self.query = mx.random.normal((1, 1, d))
        self.pool = nn.MultiHeadAttention(d, heads)
        self.norm = nn.LayerNorm(d)
        self.mlp = nn.Sequential(
            nn.Linear(d, 2 * d),
            nn.GELU(),
            nn.Linear(2 * d, out[0] * out[1]),
        )

    def __call__(
        self, tokens: mx.array, mask: mx.array | None = None
    ) -> mx.array:
        """前向池化与预测。

        参数:
            tokens: [B, N, d]
            mask: 可选 [B, N] 布尔有效掩码（True 表示有效保留 token）
        """
        B, N, d = tokens.shape
        q = mx.repeat(self.query, B, axis=0)  # [B, 1, d]

        attn_mask = None
        if mask is not None:
            # 构造加性 mask: [B, 1, 1, N]，有效为 0.0，无效为 -1e9
            m_bool = mask.reshape(B, 1, 1, N)
            attn_mask = mx.where(m_bool, mx.zeros_like(m_bool, dtype=mx.float32), -1e9)

        pooled = self.pool(q, tokens, tokens, mask=attn_mask).squeeze(1)  # [B, d]
        pooled_norm = self.norm(pooled)
        logits = self.mlp(pooled_norm).reshape(B, self.out[0], self.out[1])
        return logits

    def loss(self, logits: mx.array, targets: mx.array) -> mx.array:
        """BCE 分类损失。"""
        t = targets.astype(mx.float32)
        return nn.losses.binary_cross_entropy(logits, t, with_logits=True)


class FlatHead(nn.Module):
    """R2/R3 读出头：最后一个管长逐 token 打分，再按位置线性映射到网格。

    输入学生 token ``[B, 1568, d]``（或等价的 ``[B, 8, 14, 14, d]``）。
    只取最后一个管长 ``reshape(B, 8, 196, d)[:, 7]``，LayerNorm 后线性投到
    ``k`` 个分数，展平成 ``[B, 196*k]``，再一层线性映射到 ``12*7`` 个 logit。
    损失是 BCE（with_logits、mean），不加正例权重。
    """

    def __init__(self, d: int = 192, k: int = 4, out: tuple[int, int] = (12, 7)):
        super().__init__()
        self.k = k
        self.out = out
        self.norm = nn.LayerNorm(d)
        self.score = nn.Linear(d, k)
        self.position = nn.Linear(196 * k, out[0] * out[1])

    def __call__(self, tokens: mx.array) -> mx.array:
        B = tokens.shape[0]
        d = tokens.shape[-1]
        last = tokens.reshape(B, 8, 196, d)[:, 7]
        scores = self.score(self.norm(last)).reshape(B, 196 * self.k)
        return self.position(scores).reshape(B, self.out[0], self.out[1])

    def loss(self, logits: mx.array, targets: mx.array) -> mx.array:
        """BCE（with_logits、mean）。不加正例权重。"""
        t = targets.astype(mx.float32)
        return nn.losses.binary_cross_entropy(
            logits, t, with_logits=True, reduction="mean"
        )


class DepthDistillHead(nn.Module):
    """深度蒸馏头：每个 token 输出 4×4 像素深度，拼成 [B, 8, 56, 56]。"""

    def __init__(self, d: int = 192):
        super().__init__()
        self.proj = nn.Linear(d, 16)

    def __call__(self, tokens: mx.array) -> mx.array:
        """前向重组成空间网格。

        参数:
            tokens: [B, 1568, d] 或 [B, 8, 14, 14, d]
        返回:
            grid: [B, 8, 56, 56]
        """
        B = tokens.shape[0]
        if tokens.ndim == 3:
            tokens = tokens.reshape(B, 8, 14, 14, -1)

        # 线性输出 16 个值并拆分为 (4, 4)
        out = self.proj(tokens).reshape(B, 8, 14, 14, 4, 4)
        # 转置并重组空间尺寸: 14*4=56
        # (B, 8, 14, 4, 14, 4) -> (B, 8, 56, 56)
        grid = out.transpose(0, 1, 2, 4, 3, 5).reshape(B, 8, 56, 56)
        return grid


class VJEPAProjHead(nn.Module):
    """V-JEPA 特征对齐投影头：192 -> 1024 线性映射。"""

    def __init__(self, d: int = 192, out_dim: int = 1024):
        super().__init__()
        self.proj = nn.Linear(d, out_dim)

    def __call__(self, x: mx.array) -> mx.array:
        return self.proj(x)
