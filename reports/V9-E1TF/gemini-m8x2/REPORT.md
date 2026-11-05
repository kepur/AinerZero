# E1 修复：残差臂 ③⑥ 训练目标与往返一致性报告（ainerzero.V9.P79）

- **执行者**：gemini-m8x2（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P79`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 79 步（E1 训练目标修复）
- **依据协议**：
  - 一级裁定数学定义与 docstring 规范；
  - `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-A2 & §E1-T；
  - `reports/frontier-integration-20261027/DESIGN_CORE.md` §2 第 7 条（正交补投影）。
- **文件改动范围**：
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `src/ainerzero/v9/experiments/e1/train_runner.py`
  - `tests/test_e1_arms_net.py`
  - `tests/test_e1_train_runner.py`
  - 交付目录：`reports/V9-E1TF/gemini-m8x2/`（含 `before/` 原始备份）

---

## 1. 背景与核心修复

### 1.1 问题定位
P78 smoke 验证暴露：P74 的 `train_runner` 原先在 `build_training_windows` 中统一给所有网络臂赋予了纯状态增量目标 $y = s_{t+1} - s_t$。由于 ②③⑥ 网络结构完全一致（6150 参数），在相同种子与输入下训练更新完全一致，导致 ③⑥ 的残差网络退化为重复拟合完整动力学增量。

### 1.2 数学定义实现（一级裁定，已写入各臂 docstring）
三个网络臂现均实现内建的 `training_target(state_window, next_state, static_env, prefix_for_identification)` 方法：

1. **② PureNetArm**：
   $$y = s_{t+1} - s_t$$
   纯状态增量拟合，网络直接输出状态导数步长。

2. **③ PriorResidualArm**：
   $$y = s_{t+1} - F_{prior}(s_t; \hat{\phi}_0, \text{statics})$$
   其中 $\hat{\phi}_0$ 为固定偏置先验 `DEFAULT_BIASED_PRIOR`；$F_{prior}$ 为从 $s_t$（含姿态与角速度）执行 1 帧 600 Hz 半隐式欧拉积分所得的状态。网络拟合先验未捕获的动力学扰动。

3. **⑥ IdentifyResidualArm**：
   $$y = P_{\perp}(\hat{\phi}) \cdot (s_{t+1} - F_{prior}(s_t; \hat{\phi}, \text{statics}))$$
   其中 $\hat{\phi}$ 为前缀参数辨识推断结果；$P_{\perp}$ 为残差向中心差分雅可比 $\partial F_{prior}/\partial \phi$ 正交补空间的投影。
   - **共用底层函数**：`IdentifyResidualArm` 的 `predict()` 与 `training_target()` 共用私有方法 `_apply_correction(corr, J_matrix)`，投影逻辑与 SVD 截断阈值逐位一致；
   - **Episode 级缓存**：`train_runner.build_training_windows` 增加 episode 缓存机制 `(sequence_id, body_name)`，每个序列的前缀仅执行一次参数辨识推断，避免重复开销。

---

## 2. 往返一致性与参数分化验证

### 2.1 往返一致性（Round-trip Consistency）
对于 ②③⑥ 三臂，当 mock 网络精准输出对应臂的 `training_target` 时，调用 `predict(n_future=1)` 走一步得到的状态与真实下一帧 $s_{t+1}$ 之间的 L2 误差：
- **② PureNetArm**：误差 $0.000000 \times 10^0 < 10^{-6}$；
- **③ PriorResidualArm**：误差 $0.000000 \times 10^0 < 10^{-6}$；
- **⑥ IdentifyResidualArm**：
  - 正交扰动展开误差 $0.000000 \times 10^0 < 10^{-6}$；
  - 训练目标与雅可比各列内积 $\|J^T y\|_\infty < 10^{-8}$；
  - 对于带有非正交参数分量的状态转移，`training_target` 自动过滤平行分量并严格投影至正交补空间。

### 2.2 20 步训练权重哈希两两互异
在相同合成序列数据集、同一种子（42）、相同网络超参数（batch_size=4）下，各臂经 `train_cell` 训练 20 步后导出的 safetensors 权重 SHA256 为：
- **Arm 2**：`bb481872b499df2871b4fc2e2aaafc4d6f20bdc658e28e1df716d8a862398662`
- **Arm 3**：`95eb9ff35b80ee11db98877ae84639e4a8ea17b8f6c547849e7b2661e7fc3572`
- **Arm 6**：`4bdfc9725f7a07563ee9a98efca42371bfe96f9bf0df2272a089d7146522cbb5`

三者两两完全不同，证明动力学学习轨迹已有效分化，彻底消除了权重重合问题。

### 2.3 残差有效性验证
在附加了 $0.5\text{ m/s}^2$ 恒定水平加速度偏差的合成数据上，③ `PriorResidualArm` 在 CPU 上经 120 步（$\le 200$ 步）极小拟合后，10 步位置误差仅 0.000787 m，显著优于 ① 纯先验的 0.006903 m（误差相对下降 88.6%）。

---

## 3. 单元测试结果（tests/test_e1_arms_net.py & tests/test_e1_train_runner.py）

测试全部在纯 MLX CPU 设备（macOS darwin arm64）上运行，18 项测试全部通过，总耗时 0.51 秒（最长单项 0.13 秒）：

| 模块 | 测试用例 | 耗时 (s) | 状态 | 验证内容 |
|---|---|:---:|:---:|---|
| `test_e1_arms_net.py` | `test_parameter_count_equality` | 0.001 | PASSED | ②③⑥ 参数量严格等于 6150 |
| `test_e1_arms_net.py` | `test_determinism_seed` | 0.003 | PASSED | 同种子 SHA 一致，异种子 SHA 互异 |
| `test_e1_arms_net.py` | `test_arm3_error_lower_than_prior_after_200_steps` | 0.052 | PASSED | ③ 残差网络 120 步拟合后误差显著低于 ① |
| `test_e1_arms_net.py` | `test_arms_training_target_predict_roundtrip_consistency` | 0.005 | PASSED | **（P79 新增）** ②③⑥ mock 往返一致性误差 $< 10^{-6}$ 且 ⑥ 投影内积 $< 10^{-8}$ |
| `test_e1_arms_net.py` | `test_arm6_orthogonal_projection_inner_product` | 0.001 | PASSED | 验证静态正交投影算子内积 $< 10^{-8}$ |
| `test_e1_arms_net.py` | `test_arm6_predict_with_projection_and_diagnostic` | 0.008 | PASSED | 验证截断方向统计与 `project=False` 诊断分支 |
| `test_e1_arms_net.py` | `test_arm6_predict_path_applied_corrections_orthogonality` | 0.008 | PASSED | 实际预测路径上施加修正量正交性 |
| `test_e1_arms_net.py` | `test_arm6_injected_identifier_fn` | 0.002 | PASSED | 外部注入参数辨识器回调正确性 |
| `test_e1_arms_net.py` | `test_observed_prefix_nan_isolation` | 0.002 | PASSED | 前缀后 NaN 污染隔离 |
| `test_e1_arms_net.py` | `test_save_load_bitwise_consistency` | 0.003 | PASSED | 权重序列化与反序列化逐位一致 |
| `test_e1_train_runner.py` | `test_build_training_windows_extracts_correct_shapes` | 0.004 | PASSED | 训练窗口提取与形状校验 |
| `test_e1_train_runner.py` | `test_train_3_steps_saves_weights_and_loads_identical_sha[2]` | 0.016 | PASSED | Arm 2 真实 3 步训练保存与加载哈希一致 |
| `test_e1_train_runner.py` | `test_train_3_steps_saves_weights_and_loads_identical_sha[3]` | 0.012 | PASSED | Arm 3 真实 3 步训练保存与加载哈希一致 |
| `test_e1_train_runner.py` | `test_train_3_steps_saves_weights_and_loads_identical_sha[6]` | 0.018 | PASSED | Arm 6 真实 3 步训练保存与加载哈希一致 |
| `test_e1_train_runner.py` | `test_train_zero_budget_or_past_deadline_stops_without_writing_weights` | 0.009 | PASSED | 零预算/超时守卫拦截与不落盘保证 |
| `test_e1_train_runner.py` | `test_duty_cycle_sleep_injection_approx_3x_compute` | 0.004 | PASSED | 0.25 占空比 3x 节奏注水休眠精确性 |
| `test_e1_train_runner.py` | `test_rejection_of_nontrainable_arm_and_unregistered_seed` | 0.003 | PASSED | 非训练臂与未登记种子严格拒绝 |
| `test_e1_train_runner.py` | `test_training_20_steps_arms_parameter_sha_pairwise_different` | 0.134 | PASSED | **（P79 新增）** ②③⑥ 20 步训练后参数 SHA 两两不同 |

---

## 4. 坏对照变异实验（对抗性红灯检验）

在独立隔离目录 `/tmp/e1_tf_mutants/` 下构建变异副本，设置独立 `PYTHONPATH` 指向副本 `src` 并通过 `python -c "import ...; print(mod.__file__)"` 逐一确认副本隔离性：

### 4.1 变异 1：③ 的目标改回 $s_{t+1} - s_t$
- **变异操作**：在 `PriorResidualArm.training_target` 中直接返回 $s_{t+1} - s_t$（忽略先验单步转移 $F_{prior}$）；
- **加载路径**：`/tmp/e1_tf_mutants/mutant_1_arm3_target_reverted/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **目标测试**：`test_arms_training_target_predict_roundtrip_consistency`；
- **测试结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_arms_training_target_predict_roundtrip_consistency
  AssertionError: Arm 3 roundtrip error 0.163351 >= 1e-6
  Exit Code: 1
  ```
  **结论**：变异 1 立即变红，成功拦截目标回退。

### 4.2 变异 2：⑥ 去掉投影
- **变异操作**：在 `IdentifyResidualArm._apply_correction` 中绕过投影直接返回未投影原始残差；
- **加载路径**：`/tmp/e1_tf_mutants/mutant_2_arm6_no_projection/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **目标测试**：`test_arms_training_target_predict_roundtrip_consistency`；
- **测试结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_arms_training_target_predict_roundtrip_consistency
  AssertionError: Arm 6 target orthogonality violated: 0.04000000000000001 >= 1e-8
  Exit Code: 1
  ```
  **结论**：变异 2 立即变红，成功拦截残差投影旁路。

### 4.3 变异 3：train_runner 绕开 `training_target`
- **变异操作**：在 `train_runner.build_training_windows` 中统一给所有臂使用 $s_{t+1} - s_t$，不调用各臂的 `training_target`；
- **加载路径**：`/tmp/e1_tf_mutants/mutant_3_runner_bypasses_arm_target/src/ainerzero/v9/experiments/e1/train_runner.py`；
- **目标测试**：`test_training_20_steps_arms_parameter_sha_pairwise_different`；
- **测试结果**：
  ```text
  FAILED tests/test_e1_train_runner.py::test_training_20_steps_arms_parameter_sha_pairwise_different
  AssertionError: Arm 2 and Arm 3 parameter SHA match unexpectedly: bb481872b499df2871b4fc2e2aaafc4d6f20bdc658e28e1df716d8a862398662
  Exit Code: 1
  ```
  **结论**：变异 3 立即变红，成功拦截 runner 侧旁路逻辑。

---

## 5. 交付清单与校验和

- **合规声明**：
  - 仅在指定文件范围内修改（`arms_net.py`、`train_runner.py`、`test_e1_arms_net.py`、`test_e1_train_runner.py`）；
  - 全流程在纯 MLX CPU 设备完成，不使用 GPU，不触碰正式训练与真实生产数据；
  - 未执行 `git commit` 或 `git push`；
  - 原始未修改文件已完整备份在 `before/` 目录下。

- **交付清单**：
  - `reports/V9-E1TF/gemini-m8x2/before/`（改动前 4 个文件原始备份）
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `src/ainerzero/v9/experiments/e1/train_runner.py`
  - `tests/test_e1_arms_net.py`
  - `tests/test_e1_train_runner.py`
  - `reports/V9-E1TF/gemini-m8x2/REPORT.md`
  - `reports/V9-E1TF/gemini-m8x2/data.json`
  - `reports/V9-E1TF/gemini-m8x2/SHA256SUMS.txt`
