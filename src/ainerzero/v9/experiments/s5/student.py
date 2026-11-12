"""S5 学生时空 ViT 编码器模块（MLX）。

结构规范：
- `Student(d=192, depth=6, heads=3)`
  - 输入：patches [B, 8, 14, 14, 1536] 或 [B, 1568, 1536]
  - 可选参数：keep [B, 8, 14, 14] 与 run_len [B, 8, 14, 14]
  - 线性嵌入：nn.Linear(1536, d)
  - 1568 个可学位置嵌入：self.pos (形状 [1568, d])
  - 游程长度嵌入：self.run_len_embed (长度 1..8，初始化为全 0，只在给了 keep 时加)
  - 6 层前置 LayerNorm 的 Transformer 块，最后 LayerNorm
  - 输出：tokens [B, 1568, d] 和 mask [B, 1568]
  - 被并掉的 token 不进注意力：按批内最大保留数补齐，再用注意力掩码
- `features(layer=k)`：取第 k 层后的 token，给对齐损失使用
- 全保留时，带 keep 和不带 keep 的输出逐元素一致，误差 < 1e-5
"""
from __future__ import annotations

import mlx.core as mx
import mlx.nn as nn
import numpy as np


class TransformerBlock(nn.Module):
    """前置 LayerNorm 的 Transformer 编码器块。"""

    def __init__(self, d: int, heads: int):
        super().__init__()
        self.n1 = nn.LayerNorm(d)
        self.attn = nn.MultiHeadAttention(d, heads)
        self.n2 = nn.LayerNorm(d)
        self.mlp = nn.Sequential(
            nn.Linear(d, 4 * d),
            nn.GELU(),
            nn.Linear(4 * d, d),
        )

    def __call__(self, x: mx.array, mask: mx.array | None = None) -> mx.array:
        h = self.n1(x)
        x = x + self.attn(h, h, h, mask=mask)
        return x + self.mlp(self.n2(x))


class Student(nn.Module):
    """学生端时空 ViT 模型。"""

    def __init__(
        self,
        d: int = 192,
        depth: int = 6,
        heads: int = 3,
        num_tokens: int = 1568,
        patch_dim: int = 1536,
    ):
        super().__init__()
        self.d = d
        self.depth = depth
        self.heads = heads
        self.num_tokens = num_tokens

        self.embed = nn.Linear(patch_dim, d)
        # 1568 个可学位置嵌入
        self.pos = mx.random.normal((num_tokens, d)) * 0.02
        # 可学游程长度嵌入 1..8（索引 0 保留不用；初始化为 0 保证初始时与不加完全等价）
        self.run_len_embed = mx.zeros((9, d))

        self.blocks = [TransformerBlock(d, heads) for _ in range(depth)]
        self.norm = nn.LayerNorm(d)

        # 缓存每层中间特征供 features() 访问
        self._layer_features: list[mx.array] = []
        self._last_mask: mx.array | None = None

    def __call__(
        self,
        patches: mx.array,
        keep: mx.array | None = None,
        run_len: mx.array | None = None,
    ) -> tuple[mx.array, mx.array]:
        """前向传播。

        参数:
            patches: [B, 8, 14, 14, 1536] 或 [B, 1568, 1536]
            keep: 可选 [B, 8, 14, 14] 或 [B, 1568] 布尔保留掩码
            run_len: 可选 [B, 8, 14, 14] 或 [B, 1568] 整数游程长度

        返回:
            tokens: [B, 1568, d]
            mask: [B, 1568] 布尔掩码
        """
        B = patches.shape[0]
        if patches.ndim == 5:
            # [B, 8, 14, 14, 1536] -> [B, 1568, 1536]
            patches = patches.reshape(B, self.num_tokens, -1)

        # 1. 线性嵌入与位置编码
        x = self.embed(patches) + self.pos  # [B, 1568, d]

        # 2. 游程长度嵌入（只在给定了 keep 时加）
        if keep is not None:
            mask = keep.reshape(B, self.num_tokens).astype(mx.bool_)
            if run_len is not None:
                rl = mx.clip(run_len.reshape(B, self.num_tokens), 0, 8)
                x = x + self.run_len_embed[rl]
        else:
            mask = mx.ones((B, self.num_tokens), dtype=mx.bool_)

        self._last_mask = mask
        self._layer_features = []

        # 3. 检查是否全量保留
        # 若所有样本全保留，则直接执行全序列自注意力
        is_all_kept = bool(mx.all(mask).item())

        if is_all_kept:
            curr_h = x
            for block in self.blocks:
                curr_h = block(curr_h, mask=None)
                self._layer_features.append(curr_h)
            out_tokens = self.norm(curr_h)
            return out_tokens, mask

        # 4. 稀疏保留分支：按批内最大保留数补齐，不保留的 token 不进注意力
        mask_np = np.array(mask)
        indices_list = [np.where(mask_np[b])[0] for b in range(B)]
        k_counts = [len(idx) for idx in indices_list]
        k_max = max(k_counts)

        # 聚合紧凑表示 [B, k_max, d]
        compact_x = mx.zeros((B, k_max, self.d))
        for b in range(B):
            if k_counts[b] > 0:
                compact_x[b, :k_counts[b]] = x[b, mx.array(indices_list[b])]

        # 构造加性注意力掩码 [B, 1, 1, k_max]
        attn_mask = mx.zeros((B, 1, 1, k_max))
        for b in range(B):
            if k_counts[b] < k_max:
                attn_mask[b, 0, 0, k_counts[b]:] = -1e9

        curr_compact = compact_x
        for block in self.blocks:
            curr_compact = block(curr_compact, mask=attn_mask)
            # 还原至 [B, 1568, d] 并记录层特征
            layer_tokens = mx.zeros((B, self.num_tokens, self.d))
            for b in range(B):
                if k_counts[b] > 0:
                    layer_tokens[b, mx.array(indices_list[b])] = curr_compact[b, :k_counts[b]]
            self._layer_features.append(layer_tokens)

        compact_norm = self.norm(curr_compact)
        out_tokens = mx.zeros((B, self.num_tokens, self.d))
        for b in range(B):
            if k_counts[b] > 0:
                out_tokens[b, mx.array(indices_list[b])] = compact_norm[b, :k_counts[b]]

        return out_tokens, mask

    def features(
        self,
        patches: mx.array | None = None,
        keep: mx.array | None = None,
        run_len: mx.array | None = None,
        *,
        layer: int = -1,
    ) -> mx.array | tuple[mx.array, mx.array]:
        """取第 layer 层（1-indexed 或 0-indexed，支持负索引）后的 token 特征。

        重要提示（训练规范）：
        在训练循环或 mx.value_and_grad 中调用时，必须显式传入 patches 参数：
        `feat, mask = model.features(patches, keep=keep, layer=k)`。
        这样可保证反向传播计算图准确建立，避免读取上一次前向留下的旧计算图缓存。
        不传 patches 的用法仅适用于只读推理或前向后的瞬时核验。
        """
        if patches is not None:
            tokens, mask = self(patches, keep=keep, run_len=run_len)
            # 解析层索引（1-based 转换为 0-based，负数直接使用）
            idx = (layer - 1) if layer > 0 else layer
            return self._layer_features[idx], mask

        if not self._layer_features:
            raise RuntimeError("No cached features available; call forward first or pass patches.")

        idx = (layer - 1) if layer > 0 else layer
        return self._layer_features[idx]
