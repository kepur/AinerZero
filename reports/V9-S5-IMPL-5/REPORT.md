# P235：S5 实现 5，数据读取与训练循环交付报告（第 2 轮对齐验收）

- **任务编号**：`ainerzero.V9.P235`
- **执行者**：`gemini-k7x2`（二级执行 agent，会话 `sess-7350d561b3fc`）
- **轮次**：第 2 轮交付（完全响应一级 claude 在 `reports/V9-S5-IMPL-5/tier1-review/REVIEW.md` 提出的 3 项设计口径改动与 3 项变异补漏）
- **类型**：实现交付（纯 CPU 数据读取 + 原生 MLX 训练循环，经 `artifacts/locks/m0-worker.lock` 经锁验证，未触碰真实待训练分区与 `artifacts/v9/s5/data/`）
- **依据**：`reports/V9-S5-DESIGN/DESIGN-r1.md`（b021db0）§2、§3、§6、§7 及「实现阶段补记」；`src/ainerzero/v9/experiments/s5/heads.py`（P230）；`src/ainerzero/v9/experiments/s5/student.py`（P231）；`src/ainerzero/v9/experiments/s5/tokens.py`（P232）；`src/ainerzero/v9/experiments/s5/losses.py`（P233）；`src/ainerzero/v9/experiments/s5/metrics.py`（P234）。

---

## 1. 第 2 轮改动与对齐汇总

针对一级审查意见，第 2 轮在生产代码与契约测试中完成如下对齐：

### 1.1 设计口径改动（3 项全部落实）
1. **RLT 下 R1 读出的取法与 `restore_runs`**：
   - 生产改动：在 `train.py` 中实现 `restore_runs(tokens, keep) -> tokens` 辅助函数。对于被并掉位置（`keep == False`），取同一空间位置上、所在游程起点（最近一个保留的管长）那个 token 的输出，避免零向量将 R1Head 偏置拉向「从零向量猜深度」。
   - 在 `train_supervised`（A0-R 臂）、`train_heads` 与 `predict` 三处统一复用 `restore_runs`。
   - 新增测试：`test_restore_runs_properties` 验证全保留时恒等、部分保留时被并掉位置严格等于游程起点 token、被并掉位置填入脏数据时输出严格不变；`test_a0_r_dropped_tokens_r1_loss_invariance` 验证 A0-R 下将被并掉位置的学生输出改极端值，R1 损失严格不变。
2. **A4 对齐特征取自同一次前向**：
   - 生产改动：在 `train_supervised` 中消除冗余的前向调用 `model.student.features(patches_mx, layer=actual_layer)`。在同一次前向计算 `model.student(patches_mx, ...)` 后，直接调用 `model.student.features(layer=actual_layer)`（不传 patches），复用前向中间张量，计算量严格符合设计 §6 预算（约 +10%）。
   - 新增测试：`test_a4_single_forward_call` 通过包装 `Student.__call__` 计数，断言 2 步训练严格恰好触发 2 次前向调用（每步恰好 1 次）。
3. **教师特征单次读取与 `load_teacher`**：
   - 生产改动：在 `data.py` 中新增独立函数 `load_teacher(index, i, teachers, *, teacher_types)`，只读指定教师特征并校验 `progress.jsonl` SHA256 账本，避免加载不必要的学生帧与计算管长 patches；`load_item` 内部亦委托给 `load_teacher`。
   - 在 `train.py` 的 `distill` 循环中，统一改用 `load_teacher` 读取教师特征（C-sh 模式下错排读取），解决每段两次 `load_item` 导致的冗余耗时。
   - 新增测试：`test_load_teacher_only_reads_teacher_features` 验证其只读特征并返回干净字典。

### 1.2 变异漏网补强（3 项全部拦截）
- **T3（`align_layer + 1`）**：在 `test_a4_alignment_gradients` 中增加断言，通过监控 `s.features(layer=...)` 的入参，断言 `requested_layers[0] == cfg.align_layer`。一旦生产代码将层号变为 `align_layer + 1` 即立刻触发测试失败。变异结果：**KILLED**。
- **T5（`train_supervised` 不设 `mx.random.seed`）**：新增 `test_train_supervised_determinism`。在运行之间先用 `mx.random.seed(999)` 与 `np.random.seed(999)` 扰乱全局随机状态，不传外部实例让函数内部在 seed 之后构建模型，断言两次产出的模型与读出头权重逐元素完全相同。一旦去除 seed 立即触发测试失败。变异结果：**KILLED**。
- **T8（A2 蒸馏余弦损失不传 mask）**：新增 `test_r_arm_vjepa_dropped_tokens_loss_invariance`。首先单元级验证 `cosine_distill_loss(..., mask=mask)` 在被并掉 token 改极端值时损失严格不变；其次拦截 `T.cosine_distill_loss` 验证在 R 臂（$\tau > 0$）+ A2 下确实传入了非空 `mask`。变异结果：**KILLED**。

---

## 2. 交付文件清单

- **数据读取实现**：`src/ainerzero/v9/experiments/s5/data.py`（含 `ClipIndex`, `load_item`, `load_teacher`, `batches`，纯 CPU）
- **训练循环实现**：`src/ainerzero/v9/experiments/s5/train.py`（含 `distill`, `train_supervised`, `train_heads`, `predict`, `restore_runs`, 检查点与确定性）
- **数据契约测试**：`tests/v9/experiments/test_s5_data.py`（5 项测试全通，耗时约 9.1s）
- **原生 MLX 测试**：`tests/v9/experiments/test_s5_train_mlx.py`（21 项测试全通，经锁执行，耗时约 13.8s）
- **测试配置更新**：`tests/conftest.py`（将 `test_s5_train_mlx.py` 纳入 `NATIVE_MODULES` 白名单）
- **一级对抗变异套件与输出**：
  - `reports/V9-S5-IMPL-5/evidence/mutations.py`（一级 claude 对抗变异测试脚本）
  - `reports/V9-S5-IMPL-5/evidence/mutations-output.txt`（8 项变异在隔离副本中持锁运行结果，8/8 全部 KILLED）
- **测试证据日志**：
  - `reports/V9-S5-IMPL-5/evidence/pytest_data.txt`
  - `reports/V9-S5-IMPL-5/evidence/pytest_train_mlx.txt`
- **补丁与校验**：`reports/V9-S5-IMPL-5/diff.patch`、`reports/V9-S5-IMPL-5/SHA256SUMS.txt`、`reports/V9-S5-IMPL-5/metrics.json`

---

## 3. 对抗变异验证结果（8 项 100% 击杀）

在隔离副本中持锁执行 `reports/V9-S5-IMPL-5/tier1-review/mutations.py`，基线 26 项全通，8 处源码变异全部被相应测试捕获击杀：

```
lock held by 45861
imports from /private/tmp/gemini_mut235/src/ainerzero/__init__.py
BASELINE 0 [] ['26 passed in 21.89s']
T1_csh_ignores_perm: KILLED ['test_c_sh_teacher_targets_are_permuted'] ['1 failed, 25 passed in 21.85s']
T2_r_arm_no_da2_valid: KILLED ['test_r_arm_dropped_tokens_da2_region_loss_invariance'] ['1 failed, 25 passed in 21.47s']
T3_align_layer_plus1: KILLED ['test_a4_alignment_gradients'] ['1 failed, 25 passed in 21.22s']
T4_ckpt_every_eighth: KILLED ['test_checkpoints_count_and_step_numbers'] ['1 failed, 25 passed in 20.95s']
T5_no_seed_supervised: KILLED ['test_train_supervised_determinism'] ['1 failed, 25 passed in 21.93s']
T6_no_teacher_sha_check: KILLED ['test_tampered_teacher_output_raises_runtime_error'] ['1 failed, 25 passed in 21.59s']
T7_batches_no_shuffle: KILLED ['test_batches_determinism_and_tail_drop', 'test_all_arms_run_and_loss_decreases[arm_config0]'] ['2 failed, 24 passed in 21.26s']
T8_a2_loss_no_mask: KILLED ['test_r_arm_vjepa_dropped_tokens_loss_invariance'] ['1 failed, 25 passed in 20.78s']
```

| 变异编号与名称 | 变异注入位置 | 击杀测试用例 | 结果 |
|---|---|---|---|
| `T1_csh_ignores_perm` | `train.py: t_idx = b_idx`（忽略错排） | `test_c_sh_teacher_targets_are_permuted` | **KILLED** |
| `T2_r_arm_no_da2_valid` | `train.py: valid_mask = None`（R 臂未传 DA2 掩码） | `test_r_arm_dropped_tokens_da2_region_loss_invariance` | **KILLED** |
| `T3_align_layer_plus1` | `train.py: align_layer + 1`（对齐层错位） | `test_a4_alignment_gradients` | **KILLED** |
| `T4_ckpt_every_eighth` | `train.py: ckpt_every_frac * 2`（保存步长加倍） | `test_checkpoints_count_and_step_numbers` | **KILLED** |
| `T5_no_seed_supervised` | `train.py: seed 替换为 pass`（监督训练未设种子） | `test_train_supervised_determinism` | **KILLED** |
| `T6_no_teacher_sha_check` | `data.py: 旁路 SHA 校验` | `test_tampered_teacher_output_raises_runtime_error` | **KILLED** |
| `T7_batches_no_shuffle` | `data.py: 不打乱样本` | `test_batches_determinism_and_tail_drop` | **KILLED** |
| `T8_a2_loss_no_mask` | `train.py: A2 蒸馏 mask=None`（R 臂未屏蔽 dropped token） | `test_r_arm_vjepa_dropped_tokens_loss_invariance` | **KILLED** |

---

## 4. 契约测试集概览

### 4.1 数据读取模块 `tests/v9/experiments/test_s5_data.py`（5 项，纯 CPU）
1. `test_clip_index_ordering_and_nested_subsets`：验证索引按 (w, c) 严格递增排序，嵌套抽分子集 $L=64 \subset L=512 \subset L=2048$。
2. `test_load_item_patches_and_labels_parity`：验证 patches 形状与数值对齐、labels 完整加载。
3. `test_tampered_teacher_output_raises_runtime_error`：验证篡改教师特征触发 SHA256 账本校验报错。
4. `test_batches_determinism_and_tail_drop`：验证批次洗牌确定性与末尾不足批样本严格丢弃。
5. `test_load_teacher_only_reads_teacher_features`：验证 `load_teacher` 仅加载教师特征且严格校验哈希。

### 4.2 训练循环模块 `tests/v9/experiments/test_s5_train_mlx.py`（21 项，经锁 MLX）
1–9. `test_all_arms_run_and_loss_decreases`（参数化覆盖 A1, A2, A3, C-sh, R, A0, A4, A0-R, train_heads 9 种臂与配置组合，每种跑 20 步，损失均有限且单调下降）。
10. `test_c_sh_teacher_targets_are_permuted`：验证错排无不动点且 `distill` 传入错排索引。
11. `test_r_arm_dropped_tokens_da2_region_loss_invariance`：验证 R 臂 DA2 掩码生效，被并掉区域改极端值损失严格不变。
12. `test_a4_alignment_gradients`：验证对齐项对教师无梯度、对学生第 $k$ 层前有梯度对后无梯度，对齐层严格等于 `cfg.align_layer`。
13. `test_frozen_student_weights_invariant_in_train_heads`：验证 `train_heads` 训练后学生权重逐元素完全不变。
14. `test_checkpoints_count_and_step_numbers`：验证 32 步 frac=1/16 时恰存 16 个检查点，最后一步必存。
15. `test_training_determinism`：验证蒸馏训练在同一 seed 下权重逐元素完全相同。
16. `test_predict_shapes_and_tau`：验证多头预测输出形状符合约定，tau 稀疏统计正确。
17. `test_restore_runs_properties`：验证 `restore_runs` 在全保留下恒等、部分保留下被并掉位置等于游程起点 token、被并掉位置脏数据输出不变。
18. `test_a0_r_dropped_tokens_r1_loss_invariance`：验证 A0-R 下被并掉位置学生输出改极端值，R1 损失严格不变。
19. `test_a4_single_forward_call`：验证 A4 一步训练中 `Student.__call__` 严格恰好被调用一次。
20. `test_train_supervised_determinism`：验证 `train_supervised` 在全局状态扰乱后仍能实现严格数值确定性。
21. `test_r_arm_vjepa_dropped_tokens_loss_invariance`：验证 R 臂 A2 蒸馏中 mask 传入 `cosine_distill_loss`，被并掉 token 教师特征改极端值损失严格不变。
