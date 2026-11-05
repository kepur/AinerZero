# ainerzero.V9.P93 执行报告

- **角色**：executor（二级 执行层）
- **负责人**：gemini-e2v7
- **时间**：2026-10-30（+03）
- **任务状态**：reported
- **实验状态**：completed（纯 CPU，无 GPU，无 MLX 外部训练）
- **任务依据**：AinerRelay 任务 `ainerzero.V9.P93`；参数 v2
- **输出目录**：`reports/V9-E1NET/gemini-e2v7/`

---

## 1. 任务背景与核心修改

依据一级架构裁定修订 r4（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md`）：
- **历史缺陷**：P92 中网络臂在 dev 上的 e_1（0.008–0.011 m）显著差于先验 ①（0.0005 m），残差在第 1 步就把准确先验拉坏；训练越久 e_1 越差，收敛非单调。根因在于网络输入与目标均未归一化、输出层默认初始化导致残差在未训练或初训时产生厘米级扰动，且训练未划分验证集与早停导致过拟合。
- **修订裁定**：
  1. **输入与目标逐维标准化**：`BaseNetArm` 维护逐维 `input_mean`/`input_std` 与 `target_mean`/`target_std`（标准差下限 1e-6）；`train_step` 与 `predict` 均在标准化空间计算，predict 输出时严格反标准化；统计量严格只用训练子集计算；检查点同时保存权重与统计量，`load` 缺少统计量时抛出 `FileNotFoundError`；`parameter_sha256` 覆盖统计量字节。
  2. **输出层零初始化**：②③⑥ 的 `ResidualMLP.out` 权重与偏置显式初始化为 0。未训练时 ③ 与 ① 逐位相同，⑥ 与 ⑤ 逐位相同，② 为严格保持不动模型。网络参数量保持 6150 不变。
  3. **按 episode 划分验证集与早停**：训练窗口按 episode 划分，留出 10% 作验证集，划分种子只取决于族（与训练种子无关，确保三臂、三种子验证集完全相同），不使用 dev；每 500 步评估一次标准化空间 MSE，保留验证损失最低权重；步数上限 32000，连续 10 次无改善触发早停；检查点与训练结果记录 `best_step`、`stopped_step`、`val_loss_curve`、`val_episodes`。
  4. **spec 常量落地**：写入一级裁定常量，去掉 pending 注释。

---

## 2. 修改文件清单

| 修改文件 | 修改内容摘要 |
|---|---|
| `src/ainerzero/v9/experiments/e1/spec.py` | 落地 `DEFAULT_TRAIN_STEPS=32000`、`EARLY_STOP_EVAL_EVERY=500`、`EARLY_STOP_PATIENCE=10`、`VALIDATION_FRACTION=0.1`、`VALIDATION_SPLIT_SEED=20261030`，去掉 pending 注释 |
| `src/ainerzero/v9/experiments/e1/arms_net.py` | `ResidualMLP` 输出层零初始化；`BaseNetArm` 增加输入/目标均值与标准差及 `predict_delta`；`save`/`load` 支持 `normalization.npz` 与缺失校验；`parameter_sha256` 覆盖标准化统计量 |
| `src/ainerzero/v9/experiments/e1/train_runner.py` | 增加 `split_episodes`、`compute_validation_loss`、`get_validation_split_seed`；`train_cell` 按 episode 划分 10% 验证集、统计量仅自训练集计算、早停与最优步权重恢复、输出元数据 |
| `tests/test_e1_arms_net.py` | 调整 `test_arm6_predict_path_applied_corrections_orthogonality` 显式设置非零输出以校验投影截断 |
| `tests/test_e1_p93_revision.py` | 新增 7 项单测，全面覆盖零初始化等价、统计量往返/缺失、训练集纯洁性、划分确定性与互斥性、早停保存最优步权重、反标准化及参数量冻结 |

---

## 3. 测试验证与结果

### 3.1 零初始化等价（运动中的 Episode）
- 场景构造：自由飞行的球（半径 0.15 m，初始速度 [1.5, 0.5, 2.0]）+ 地面上摩擦滑动的盒子（半尺寸 [0.25, 0.25, 0.25]，初始速度 [2.0, 0.0, 0.0]），物理引擎运行 10 帧前缀。
- 未训练 ③ 与 ①：`pred3` 与 `pred1` 对 ball 与 box 的 10 步未来轨迹逐位完全相同（`np.array_equal` 为 True，最大绝对差 0.0）。
- 未训练 ⑥ 与 ⑤：`pred6` 与 `pred5` 对 ball 与 box 的 10 步未来轨迹逐位完全相同（`np.array_equal` 为 True，最大绝对差 0.0）。
- 未训练 ②：对 ball 与 box 的所有预测帧位置严格等于前缀最后一帧观测位置（严格保持不动）。

### 3.2 标准化统计量存取与纯洁性
- 存取往返：`custom_in_mean`、`custom_in_std`、`custom_tar_mean`、`custom_tar_std` 保存后加载回全新实例，各维数据完全一致；`parameter_sha256` 一致。
- 缺失报警：删除 `normalization.npz` 后调用 `load`，立即抛出 `FileNotFoundError: Missing normalization statistics`。
- 纯洁性：在验证子集注入数值高达 1e9 的异常值，训练后读取检查点，`input_mean` 与 `target_mean` 各维绝对值均正常（< 100.0），证明统计量仅自训练子集计算。

### 3.3 验证集划分与早停
- 划分互斥性与确定性：20 个 episode 划分出 2 个验证 episode 与 18 个训练 episode，交集为空；在 Arm 2（种子 42）、Arm 3（种子 43）、Arm 6（种子 44）之间，得到的 `val_episodes` 列表完全相同。
- 早停权重保存：注入人为验证损失曲线（第 1500 步取到全局最小值 0.1，2000 步上升到 0.6），训练完成保存的权重与第 1500 步权重逐位一致，且与第 2000 步权重不同。
- 反标准化应用：设置非零 `target_mean`，未训练网络输出严格反标准化至 `target_mean`。
- 参数量：②、③、⑥ 均严格为 6150。

---

## 4. 坏对照（Bad Controls）在隔离副本中验证

在隔离目录 `/tmp/e1_bad_controls_gemini_e2v7`（独立代码与单测副本）执行：

1. **坏对照 (a)：去掉零初始化**
   - 改动：`ResidualMLP` 设置 `zero_init_out = False`
   - 测试：`test_zero_initialization_equivalence`
   - 结果：**FAIL（变红）**，报错 `AssertionError: Untrained Arm 3 and Arm 1 diverged on ball`
   - 证据文件：`reports/V9-E1NET/gemini-e2v7/evidence/bad_control_a.log`

2. **坏对照 (b)：统计量计算时混入验证窗口**
   - 改动：`train_cell` 统计量计算混入 `val_windows.inputs`
   - 测试：`test_normalization_computed_strictly_from_train_subset`
   - 结果：**FAIL（变红）**，报错 `AssertionError: input_mean contaminated: [1.0000002e+08 ...]`
   - 证据文件：`reports/V9-E1NET/gemini-e2v7/evidence/bad_control_b.log`

3. **坏对照 (c)：保留最后一步的权重，而不是最佳的**
   - 改动：`train_cell` 略过 `model.net.update(mlx.utils.tree_unflatten(list(best_weights.items())))`
   - 测试：`test_early_stopping_saves_best_step_weights`
   - 结果：**FAIL（变红）**，报错 `AssertionError: Weight fc1.weight does not match best_step 1500`
   - 证据文件：`reports/V9-E1NET/gemini-e2v7/evidence/bad_control_c.log`

4. **坏对照 (d)：predict 时漏掉反标准化**
   - 改动：`predict_delta` 直接返回 `out_norm_np`，忽略 `target_std` 与 `target_mean`
   - 测试：`test_predict_denormalization_applied`
   - 结果：**FAIL（变红）**，报错 `AssertionError: Denormalization missing in predict_delta: expected [12.5 -8.  ...], got [0. 0. ...]`
   - 证据文件：`reports/V9-E1NET/gemini-e2v7/evidence/bad_control_d.log`

---

## 5. E1 全量测试集运行结果

命令：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py`
- 结果：**201 项全部通过（201 passed in 27.35s）**
- 覆盖模块：
  - `test_e1_analysis.py`: 13 passed
  - `test_e1_arms_net.py`: 18 passed
  - `test_e1_arms_nonnet.py`: 14 passed
  - `test_e1_data_runner.py`: 10 passed
  - `test_e1_entry.py`: 12 passed
  - `test_e1_eval_runner.py`: 19 passed
  - `test_e1_export.py`: 17 passed
  - `test_e1_identity.py`: 7 passed
  - `test_e1_metrics.py`: 20 passed
  - `test_e1_p87_geometry.py`: 7 passed
  - `test_e1_p93_revision.py`: 7 passed
  - `test_e1_prereg.py`: 18 passed
  - `test_e1_prior.py`: 13 passed
  - `test_e1_prior_box.py`: 9 passed
  - `test_e1_train_runner.py`: 9 passed
  - `test_e1_wiring.py`: 8 passed
