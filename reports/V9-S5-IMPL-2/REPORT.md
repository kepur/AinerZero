# S5 实现 2 验收交付报告（r1 修订版）：学生 ViT、蒸馏与对齐损失、RLT 接入与读出头

- **任务编号**：`ainerzero.V9.P230`
- **执行者**：`gemini-k7x2`（二级执行 agent，会话 `sess-7350d561b3fc`）
- **类型**：实现交付（纯 CPU NumPy 预处理 + 原生 MLX 模型，持锁运行原生测试，无未授权真实训练，无模型权重下载）
- **设计依据**：`reports/V9-S5-DESIGN/DESIGN-r1.md`（§3、§4、§5、§7）、`reports/V9-S5-IMPL-2/tier1-review/REVIEW.md`

---

## 1. 针对一级对抗验收（Tier-1 Review Round 1）打回意见的逐条整改与回应

针对一级对抗验收在第 1 轮中通过 `reports/V9-S5-IMPL-2/tier1-review/mutations.py` 测出的 5 处漏网突变，本版（r1）进行了彻底重构与全面加固。原生测试用例从 13 项扩充至 19 项，**10 个对抗性突变全部 100% 杀死（0 漏网）**：

### 1.1 5 条加固测试全部直接调用真实生产代码，精准斩杀漏网突变

1. **N3（稀疏分支补齐泄漏：`block(curr_compact, mask=None)`）**：
   - **机制分析**：当批量为 2 且样本保留数不同时（如样本 0 保留 500 个，样本 1 保留 1000 个），批处理必须将样本 0 补齐 500 个零向量至 $k_{\max}=1000$。若移除注意力掩码 `attn_mask`，前 500 个保留 token 会在自注意力中关联到后 500 个补齐的零向量，产生特征泄漏。旧测试仅在单样本上改扰动，无法测出多样本批内对齐补齐引入的零向量泄漏。
   - **整改落实**：新增 `test_student_sparse_batch_padding_isolation`。构造批大小 2、保留数分别为 500 与 1000 的输入。将批运行中样本 0 的保留 token 与单独跑样本 0（$k_{\max}=500$，无任何补齐零向量）的输出进行比对。在正确代码下两者逐元素一致（误差仅 $2.50\times 10^{-6} < 10^{-4}$）；当 N3 去掉 `attn_mask` 时，补齐零向量造成注意力泄漏，误差达 $>0.01$，断言立即失败，**N3 被直接杀死**。

2. **N4（SSI 损失去掉平移项：`t_shift = 0.0 * ...`）**：
   - **机制分析**：MiDaS 式尺度与平移不变深度损失的核心特性在于同时对尺度 $s$ 与平移 $t$ 具有不变性。若去掉平移对齐项，预测值施加平移常数时损失必将发生显著变化。
   - **整改落实**：新增 `test_ssi_depth_loss_shift_invariance`。对 `pred` 施加常数平移 $+3.7$ 与尺度变换 $\times 2.5$。分别在无掩码与有 `valid` 掩码两条路径下，直接断言变换前后的损失差异严格小于 $10^{-5}$（实测差异仅 $7.45\times 10^{-9}$）。当 N4 破坏移除平移项时，平移无法被抵消，损失剧增数倍，断言失败，**N4 被直接杀死**。

3. **N7（R1Head 帧时间顺序错：`transpose(0, 4, 1, 2, 3)`）**：
   - **机制分析**：`R1Head` 将形状 `[B, 8, 14, 14, 4]` 重构为 `[B, 16, 14, 14]`。对于管长 $t \in [0..7]$ 与子帧 $dt \in [0, 1]$，在全局 16 帧中的时间对应关系必须是 $2t + dt$。若转置为 `(0, 4, 1, 2, 3)`，将变成 $8dt + t$，导致第 0 帧与第 1 帧被分裂为前后半段。
   - **整改落实**：新增 `test_r1_head_frame_ordering_contract`。构造特定输入使得输出仅在管长 $t=1$、子帧 $dt=1$ 为 $4.5$（其余为 0）。直接调用 `R1Head` 生产代码，断言全局第 $2\times 1 + 1 = 3$ 帧的像素值为 4.5，而错误帧（第 9 帧）的值为 0.0。当 N7 破坏转置顺序时，4.5 出现在第 9 帧而非第 3 帧，断言失败，**N7 被直接杀死**。

4. **N8（DepthDistillHead 空间排列错：`transpose(0, 1, 2, 3, 4, 5)`）**：
   - **机制分析**：每个 token 预测 4×4 深度子网格（共 16 通道），应拼装至 $56\times 56$ 全局深度图。大块索引 $(h, w)$ 与块内子像素 $(i, j)$ 的全局网格坐标必须是 $(\text{row}=4h+i, \text{col}=4w+j)$。若未转置相邻维度，子块与块级展开顺序错乱，全局图像空间结构被破坏。
   - **整改落实**：新增 `test_depth_distill_head_spatial_alignment_contract`。构造特定 token 使仅在大块 $(h=2, w=3)$ 内的子像素 $(i=1, j=2)$ 输出 $7.2$。调用生产函数，断言输出网格全局像素 $(\text{row}=9, \text{col}=14)$ 严格等于 7.2 且全图仅此 1 个非零点。当 N8 破坏为顺序转置时，像素落入错误空间位置，断言失败，**N8 被直接杀死**。

5. **N9（不加游程长度嵌入：`x = x + 0.0 * self.run_len_embed[rl]`）**：
   - **机制分析**：游程长度嵌入 `run_len_embed` 用于向保留 token 注入其代表的管长信息。在赋予非零可学权重后，不同的游程长度必须导致保留 token 的特征表示产生区分性变化。
   - **整改落实**：新增 `test_student_run_length_embedding_contract`。将 `model.run_len_embed` 赋予非零初始权重，在相同输入与保留掩码下，分别传入游程长度全为 1 与全为 4 的张量。断言保留 token 输出的最大绝对差异显著大于 $0.05$（实测差异达 $3.7571$）；同时断言未提供 `keep`（`keep=None`）时游程嵌入严格不介入（差异恒为 0）。当 N9 破坏将游程嵌入乘以 0 时，不同游程长度下输出完全无差别，断言失败，**N9 被直接杀死**。

### 1.2 `Student.features()` 训练安全规范与一致性检验
- **Docstring 规范说明**：在 `src/ainerzero/v9/experiments/s5/student.py` 的 `features()` 方法注释中明确标明训练安全要求：
  > “重要提示（训练规范）：在训练循环或 `mx.value_and_grad` 中调用时，必须显式传入 patches 参数：`feat, mask = model.features(patches, keep=keep, layer=k)`。这样可保证反向传播计算图准确建立，避免读取上一次前向留下的旧计算图缓存。不传 patches 的用法仅适用于只读推理或前向后的瞬时核验。”
- **双路径完全等价性测试**：新增 `test_student_features_parity_call_vs_cache`，严格证明显式传入 `patches` 计算特征与先 `forward` 再读取 `_layer_features` 在同一次前向中逐元素绝对误差小于 $10^{-6}$（实测为 $0.00\times 10^0$）。

---

## 2. 10 个对抗性突变杀伤结果全景表（直接对标 `tier1-review/mutations.py`）

持锁在隔离副本中执行 Tier-1 验收人提供的 `reports/V9-S5-IMPL-2/tier1-review/mutations.py` 脚本，全量测试实测结果如下：

| 突变编号与名称 | 破坏源码位置与改动 | 状态 | 直接杀死它的测试用例（生产函数真实调用） |
| :--- | :--- | :---: | :--- |
| **N1_rlt_anchor_compare** | `tokens.py`: RLT 阈值 $\times 3$ | **KILLED** | `test_rlt_keep_parity_with_authority` |
| **N2_patch_hw_swap** | `tokens.py`: 块的行列轴对调 | **KILLED** | `test_tubelet_patches_mapping_and_order` |
| **N3_no_attn_mask_sparse** | `student.py`: 稀疏分支不传注意力掩码 | **KILLED** | `test_student_sparse_batch_padding_isolation`（多样本补齐零向量隔离） |
| **N4_ssi_no_shift** | `losses.py`: SSI 损失去掉平移项 | **KILLED** | `test_ssi_depth_loss_shift_invariance`（常数平移与尺度不变性） |
| **N5_align_no_stopgrad** | `losses.py`: 对齐损失去掉 `stop_gradient` | **KILLED** | `test_cosine_distill_and_align_loss` |
| **N6_gridhead_ignore_mask** | `heads.py`: GridHead 注意力池化忽略掩码 | **KILLED** | `test_grid_head_mask_invariance` |
| **N7_r1_frame_order** | `heads.py`: R1Head 重构帧转置顺序错 | **KILLED** | `test_r1_head_frame_ordering_contract`（$2t+dt$ 时间全局索引对齐） |
| **N8_depthhead_transpose** | `heads.py`: DepthDistillHead 拼 4×4 时空间轴错 | **KILLED** | `test_depth_distill_head_spatial_alignment_contract`（$4h+i, 4w+j$ 空间对齐） |
| **N9_no_runlen_embed** | `student.py`: 游程嵌入置零（不加游程嵌入） | **KILLED** | `test_student_run_length_embedding_contract`（不同游程长度输出变化检验） |
| **N10_restoration_prev_frame**| `tokens.py`: 还原误差改成对上一帧比较 | **KILLED** | `test_restoration_error_gradient_sequence` |

**突变杀伤率统计：10 / 10 全部杀死（100% 杀伤率，0 漏网）**。

---

## 3. V-JEPA 2.1 Token 顺序源码核实与出处引用

依据任务要求，从真实模型环境源码中核实 V-JEPA 时空 Token 的展平顺序：

- **核查源码文件**：[`envs/teachers/src/vjepa2-mlx/packages/vjepa2-core-mlx/src/vjepa2_core_mlx/models/utils/patch_embed.py`](file:///Users/mac/AinerWorkFlow/AinerZero/envs/teachers/src/vjepa2-mlx/packages/vjepa2-core-mlx/src/vjepa2_core_mlx/models/utils/patch_embed.py)
- **核心实现位置**：类 `PatchEmbed3D` 的 `__call__` 方法（第 110–115 行）：
  ```python
  110:     def __call__(self, x, **kwargs):
  111:         # Expects x as (B, T, H, W, C) (channels-last).
  112:         x = self.proj(x)  # (B, T', H', W', embed_dim)
  113:         B, T, H, W, E = x.shape
  114:         x = x.reshape(B, T * H * W, E)
  115:         return x
  ```
- **模块文档说明**（第 32–42 行）：
  ```
  Output token ordering (identical to upstream proj(x).flatten(2).transpose(1,2)):
      * 3D : frame-major then row-major over (T', H', W') -> n = t * (H'*W') + h * W' + w
      The 3D ordering is what the downstream 3D-RoPE position ids assume
      (frame-major, then row-major). In MLX, proj already yields the spatial
      axes in trailing-channel form (B, *spatial, embed_dim), so a plain
      reshape(B, N, embed_dim) produces exactly this ordering — no transpose
      of the spatial axes is needed.
  ```
- **结论与实现对齐**：
  V-JEPA 3D 卷积在时间步优先（frame-major，即 $T'$），随后按空间行优先（row-major，即 $H', W'$）顺序展平：
  $$n = t \times (H' \times W') + h \times W' + w$$
  本模块在 [`tokens.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/tokens.py) 的 `tubelet_patches` 中严格采用 `(t, h, w, dt, dh, dw, c)` 转置与展平，空间与时间展平顺序与 V-JEPA 2.1 逐 token 严格一致。

---

## 4. 交付文件清单与结构

### 4.1 核心源码与测试清单
| 文件路径 | 职责说明 | 测试数与状态 |
| :--- | :--- | :--- |
| [`src/.../s5/__init__.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/__init__.py) | 顶层包导出，CPU 与 MLX 符号清晰划分。 | — |
| [`src/.../s5/tokens.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/tokens.py) | 纯 NumPy 模块：`tubelet_patches`、`rlt_keep`（权威调用 `rlt_frame_dropping`）、`restoration_error`。 | — |
| [`src/.../s5/student.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/student.py) | 学生时空 ViT（MLX）：$d=192$, depth=6, heads=3；位置编码与游程长度嵌入；稀疏自注意力批内补齐隔离掩码；`features()` 训练安全规范。 | — |
| [`src/.../s5/losses.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/losses.py) | 损失函数模块（MLX）：MiDaS 式 `ssi_depth_loss`（尺度与平移双重鲁棒）、`cosine_distill_loss`、带 `stop_gradient` 的 `align_loss`、错排 `permutation`。 | — |
| [`src/.../s5/heads.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/heads.py) | 读出与对齐头（MLX）：`R1Head`（$2t+dt$ 时间重构）、`GridHead`（注意力池化 + 2层 MLP）、`DepthDistillHead`（$4h+i, 4w+j$ 空间子网格展开）、`VJEPAProjHead`。 | — |
| [`tests/.../test_s5_tokens.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s5_tokens.py) | 纯 CPU 测试套件：块展平映射、RLT 极限与权威一致性、重建误差分布及各自坏对照。 | **7 passed**（0.97s） |
| [`tests/.../test_s5_student_mlx.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s5_student_mlx.py) | 原生 MLX 测试套件（需持锁）：掩码不变性、稀疏补齐隔离（杀 N3）、SSI 平移不变性（杀 N4）、蒸馏梯度截断、错排性质、GridHead 掩码、R1 帧时间顺序（杀 N7）、深度头空间排列（杀 N8）、游程嵌入（杀 N9）、特征双路径一致性、200 步过拟合冒烟。 | **19 passed**（47.22s） |
| [`tests/conftest.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/conftest.py) | 仅登记一行：`"test_s5_student_mlx.py": "module-level importorskip mlx.core/mlx.nn (S5 student ViT, losses, heads)"`。 | — |
| **测试套件总计** | 全套 26 项测试全部通过（纯 CPU 7 项 + 原生 MLX 19 项）。 | **26 passed** |

### 4.2 证据文件清单
| 证据文件 | 说明 |
| :--- | :--- |
| [`reports/V9-S5-IMPL-2/diff.patch`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/diff.patch) | S5-IMPL-2 全部源码、测试与 conftest 配置的 unified diff 补丁。 |
| [`reports/V9-S5-IMPL-2/evidence/metrics.json`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/evidence/metrics.json) | 包含 9 项基准测试、5 项对抗验证与 10 项突变杀伤率的完整结构化指标。 |
| [`reports/V9-S5-IMPL-2/evidence/run_evidence.py`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/evidence/run_evidence.py) | 包含全部度量与对抗断言的独立度量脚本。 |
| [`reports/V9-S5-IMPL-2/evidence/run_evidence.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/evidence/run_evidence.txt) | `run_evidence.py` 持锁运行实录。 |
| [`reports/V9-S5-IMPL-2/evidence/pytest_cpu_tests.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/evidence/pytest_cpu_tests.txt) | 纯 CPU 7 项测试运行实录。 |
| [`reports/V9-S5-IMPL-2/evidence/pytest_native_tests.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/evidence/pytest_native_tests.txt) | 原生 MLX 19 项测试持锁运行实录。 |
| [`reports/V9-S5-IMPL-2/SHA256SUMS.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-2/SHA256SUMS.txt) | 交付目录下全部交付物 SHA256 校验列表。 |

---

## 5. 关键度量快照（`metrics.json` 全文字段）

```json
{
  "test_1_tubelet_patches": {
    "status": "PASSED",
    "mapped_pos": [3, 5, 9],
    "inner_offset": 214,
    "expected_offset": 214,
    "bad_control_caught": true
  },
  "test_2_rlt_keep": {
    "status": "PASSED",
    "static_retention_rate": 0.125,
    "dynamic_retention_rate": 1.0
  },
  "test_3_restoration_error": {
    "status": "PASSED",
    "median_error": 0.05999999865889549,
    "p95_error": 0.10499999672174454
  },
  "test_4_student_invariance": {
    "status": "PASSED",
    "full_retention_diff": 0.0,
    "masked_token_perturbation_diff": 0.0
  },
  "test_5_ssi_depth_loss": {
    "status": "PASSED",
    "invariance_diff": 0.0,
    "base_loss": 0.09911710023880005,
    "random_loss": 0.7981479167938232
  },
  "test_6_distill_and_align": {
    "status": "PASSED",
    "identical_loss": -8.940696183401542e-09,
    "teacher_gradient_norm": 0.0
  },
  "test_7_permutation": {
    "status": "PASSED",
    "length": 1568,
    "fixed_points": 0,
    "deterministic": true
  },
  "test_8_grid_head": {
    "status": "PASSED",
    "mask_invariance_diff": 0.0
  },
  "test_9_overfit_smoke": {
    "status": "PASSED",
    "initial_loss": 0.7015689611434937,
    "final_loss": 5.08667699250509e-06,
    "loss_ratio": 7.250430498256749e-06,
    "threshold": 0.2,
    "elapsed_seconds": 49.99639458399906
  },
  "adversarial_n3_padding_isolation": {
    "status": "PASSED",
    "diff_batch_vs_single": 2.5033950805664062e-06
  },
  "adversarial_n4_ssi_shift_invariance": {
    "status": "PASSED",
    "diff_shift": 7.450580596923828e-09
  },
  "adversarial_n7_r1_frame_ordering": {
    "status": "PASSED",
    "expected_frame_val": 4.5,
    "mutated_frame_val": 0.0
  },
  "adversarial_n8_depth_distill_spatial": {
    "status": "PASSED",
    "pixel_val": 7.199999809265137,
    "nonzeros": 1
  },
  "adversarial_n9_run_length_embed": {
    "status": "PASSED",
    "diff_run_length": 3.75711727142334
  },
  "mutations_kill_rate": {
    "status": "PASSED",
    "total": 10,
    "killed": 10,
    "leaked": 0,
    "details": {
      "N1_rlt_anchor_compare": "KILLED",
      "N2_patch_hw_swap": "KILLED",
      "N3_no_attn_mask_sparse": "KILLED",
      "N4_ssi_no_shift": "KILLED",
      "N5_align_no_stopgrad": "KILLED",
      "N6_gridhead_ignore_mask": "KILLED",
      "N7_r1_frame_order": "KILLED",
      "N8_depthhead_transpose": "KILLED",
      "N9_no_runlen_embed": "KILLED",
      "N10_restoration_prev_frame": "KILLED"
    }
  }
}
```

---

## 6. 结论

本阶段 S5 实现 2（r1 修订版）已彻底解决 Tier-1 对抗验收第 1 轮指出的全部问题：
1. **10 个对抗性源码突变 100% 杀死（0 漏网）**；
2. **5 条新测试全部调用生产函数**，消除了测试自建逻辑的虚假防御；
3. **`Student.features()` 显式传入规范明确并经双路径等价性验证**；
4. 纯 CPU 测试（7 项）与持锁原生 MLX 测试（19 项）全量通过；
5. 端到端 200 步过拟合冒烟测试损失下降比例达 $0.00\% \ll 20\%$。

交付物已就绪，所有约束与工作规则严格遵守，请求一级验收。
