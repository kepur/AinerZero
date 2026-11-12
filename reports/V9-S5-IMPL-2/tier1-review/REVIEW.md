# P230 一级对抗验收（第 1 轮）：打回

验收人：一级 claude，2026-11-12。

## 已核实，没问题
- **RLT 还原：** `rlt_frame_dropping` 返回的保留 token 按位置优先排列（`src/ainerzero/v9/tokenization/rlt.py` 第 90–128 行）。`tokens.rlt_keep` 按同一顺序还原，结果正确。
- **`GridHead.loss`：** 本机 MLX 0.32.2 的 `binary_cross_entropy` 默认 `reduction='mean'`，返回标量。
- **稀疏分支的梯度能回传**（`grad_probe.py`）：
  - 两个样本各随机保留约一半时，位置嵌入有梯度的行是 1222 / 1568，与两个样本保留位置的并集（理论约 1225）一致，被去掉的位置没有梯度；
  - 嵌入层与游程长度嵌入都有非零梯度。

## 改坏源码（隔离副本，持锁，`mutations.py`）
副本基线：20 项全过。

| 改动 | 结果 | 拦住它的测试 |
|---|---|---|
| N1 RLT 阈值 ×3（与权威不一致） | 拦住 | test_rlt_keep_parity_with_authority |
| N2 块的行列对调 | 拦住 | test_tubelet_patches_mapping_and_order |
| N3 稀疏分支不传注意力掩码 | **漏网** | — |
| N4 SSI 损失去掉平移项 | **漏网** | — |
| N5 对齐损失去掉 stop_gradient | 拦住 | test_cosine_distill_and_align_loss |
| N6 GridHead 忽略掩码 | 拦住 | test_grid_head_mask_invariance |
| N7 R1Head 帧顺序错 | **漏网** | — |
| N8 DepthDistillHead 拼 4×4 时转置错 | **漏网** | — |
| N9 不加游程长度嵌入 | **漏网** | — |
| N10 还原误差改成对上一帧比 | 拦住 | test_restoration_error_gradient_sequence |

## 必须补的测试（都调用生产代码，并在报告里写明各自的源码坏对照结果）
1. **N3 补齐泄漏：**
   - 批量 2，两个样本保留数不同（例如 60% 与 30%）；
   - 每个样本在批内的输出，必须与单独跑这个样本的输出一致（误差 < 1e-4）；
   - 现有的「改被去掉的 token 的值」测不到这一点：被去掉的 token 根本没进紧凑序列，泄漏的是补齐用的零向量。
2. **N4 平移不变：**
   - 对 pred 加一个明显的常数平移，例如 +3.7，并与尺度变换组合；
   - 损失不变（误差 < 1e-5），有 valid 掩码与没有掩码两条路径都要测。
3. **N7 R1Head 帧顺序：**
   - 构造只在第 t 个管长、第 dt 帧的输出通道上非零的权重（或直接构造 proj 输出）；
   - 断言它落在 `pred_logd[:, 2t+dt]`；
   - 与 `labels.r1` 的 `[16,14,14]` 帧顺序对齐。
4. **N8 DepthDistillHead 空间排列：**
   - 构造只有块 (h, w) 的第 (i, j) 个输出非零；
   - 断言它落在 `grid[:, t, 4h+i, 4w+j]`。
5. **N9 游程长度嵌入：**
   - 把 `run_len_embed` 设成非零；
   - 同一输入换不同的 `run_len`，保留 token 的输出必须改变；
   - 不给 keep 时输出不变。

## 另外
- `Student` 把每层特征存在 `self._layer_features` 上。以下划线开头，不会被当成参数，可以保留。
- 但 `features()` 不传 patches 时，返回的是「上一次前向」的特征。在 `value_and_grad` 里这样用容易拿到旧的计算图。请在 docstring 写明：训练时必须传 patches 调用；并加一条测试，证明两种调用在同一次前向内结果一致。
