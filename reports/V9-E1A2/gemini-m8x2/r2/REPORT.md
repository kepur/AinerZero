# E1-A2 网络臂实现与测试报告（r2 复核交付）

- **执行者**：gemini-m8x2（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P69`（轮次：r2）
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 69 步（E1-A2 网络臂）
- **依据协议**：
  - 一级 claude 对抗验收打回意见（r1 必改项）；
  - `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-A2；
  - `reports/V9-P48/PREREG_DRAFT.md` §2（臂表：②③⑥）；
  - `reports/frontier-integration-20261027/DESIGN_CORE.md` §2 第 7 条（残差与参数灵敏度正交投影）。
- **文件改动范围**：
  - 核心实现：`src/ainerzero/v9/experiments/e1/arms_net.py`
  - 单元测试：`tests/test_e1_arms_net.py`
  - 交付成果：`reports/V9-E1A2/gemini-m8x2/r2/`
- **上轮打回问题定位与解决**：
  - **问题根源**：r1 的正交性测试仅直接验证了底层静态函数 `project_onto_orthogonal_complement`，未在 `IdentifyResidualArm.predict` 真实预测路径上采样实际施加的状态修正量。当一级将 `arms_net.py:571` 的 `if self.project:` 改为 `if False:` 时，测试未被触发变红（8 passed）。
  - **r2 必改修复**：
    1. 在 `IdentifyResidualArm` 中新增 `self.last_applied_corrections: list[np.ndarray]` 与 `self.last_jacobians: list[np.ndarray]`，记录自回归预测过程中每一步实际施加的修正向量与对应状态处关于物理参数的 1 步先验中心差分雅可比矩阵 $J$；并在 `return_info=True` 时一并返回；
    2. 新增单元测试 `test_arm6_predict_path_applied_corrections_orthogonality`，执行完整的 `predict()` 调用：
       - `project=True` 时，检验自回归展开的每一步施加修正向量 $c$ 均满足 $|J^T c|_\infty < 10^{-8}$；
       - `project=False` 时，检验至少存在一步不满足（违背正交性，被未修正残差直接污染）；
    3. 坏对照变异 1 专门将 `predict` 内的 `if self.project:` 替换为 `if False:`，在隔离副本与独立 `PYTHONPATH` 下验证新测试立即变红（Exit Code 1）。

---

## 1. 网络臂架构与接口实现

全部实现运行于 **MLX CPU 设备**（`mx.set_default_device(mx.cpu)`），接口与 E1-A1 完全兼容：`predict(observed_prefix, static_env, n_future)`，辅以 `train_step(batch)`、`save(path)`、`load(path)`、`parameter_sha256()` 及 `count_parameters()`。

### 1.1 ② PureNetArm（纯 MLX 动力学网络）
- **输入特征**：滑动窗口内最近 $K=4$ 帧的状态历史（各物体位置与速度，共 $4 \times 6 = 24$ 维）。
- **网络结构**：MLX 3 层全连接多层感知机（`DynamicsMLP`：$24 \to 64 \to 64 \to 6$）。
- **展开方式**：预测下一帧状态增量 $[\Delta \mathbf{x}, \Delta \mathbf{v}]$，自回归（autoregressive）向后展开 $n\_future$ 步。

### 1.2 ③ PriorResidualArm（先验 + MLX 残差网络）
- **机理设计**：每帧先用 `prior.DEFAULT_BIASED_PRIOR` 进行 600 Hz 半隐式欧拉积分（10 个子步），随后叠加残差网络预测的状态修正量 $[\Delta \mathbf{x}_{res}, \Delta \mathbf{v}_{res}]$。
- **网络结构**：与 ② 采用完全相同的 `DynamicsMLP`（$24 \to 64 \to 64 \to 6$）。

### 1.3 ⑥ IdentifyResidualArm（辨识 + 正交投影残差网络）
- **参数辨识**：提供可注入的辨识函数接口 `IdentificationFn`；缺省回退至固定先验参数 `DEFAULT_BIASED_PRIOR`。
- **正交补投影机制（DESIGN_CORE §2 第 7 条）**：
  - 每一步物理先验仿真前计算当前状态处的先验雅可比 $J = \partial F_{prior}/\partial \phi \in \mathbb{R}^{6 \times 5}$；
  - 采用 `jacobian.compute_orthogonal_projection_basis` 进行 SVD 截断分解（相对奇异值阈值 $10^{-6} \cdot \sigma_{max}$）；
  - 残差修正量投影至正交补空间：$\mathbf{r}_{\perp} = \mathbf{r} - \mathbf{U}_{basis} (\mathbf{U}_{basis}^T \mathbf{r})$；
  - 截断方向数记录在 `last_truncated_counts` 中；
  - 每一步实际施加的修正向量与雅可比矩阵分别保存在 `last_applied_corrections` 与 `last_jacobians` 中。
- **诊断变体**：支持 `project=False` 模式（不施加正交补投影），用于消融与对照。

---

## 2. 结构参数量一致性与确定性验证

- **参数量严格一致**：
  - 预登记冻结参数量：`REGISTERED_PARAMETER_COUNT = 6150`；
  - ② `PureNetArm`：$24 \times 64 + 64 + 64 \times 64 + 64 + 64 \times 6 + 6 = 6150$；
  - ③ `PriorResidualArm`：$6150$；
  - ⑥ `IdentifyResidualArm`：$6150$；
  - 三臂网络模型结构在模块常量中固定，实测参数量逐位相等且等于 6150。
- **确定性初始化**：
  - 种子 42：SHA256 为 `f939cfdb6239f069788f1a239c8dc91e6b9bb6d1d2614588d05a71ea6ea5eea2`；
  - 种子 999：SHA256 为 `73e86699a4098b302ff988e3cc61ba2d8731919a738b04b5e41c0d1aaddfdd5a`；
  - 同一种子下三臂权重哈希逐位完全一致；不同种子必不相同。
- **前缀隔离**：前缀后的无效帧打上 `NaN`，预测路径严格切除，结果与无 `NaN` 输入逐位一致。
- **权重存取**：`save` 保存至 safetensors 文件后，由异种初始化的实例通过 `load` 恢复，参数哈希与多步展开预测均逐位一致。

---

## 3. 单元测试结果与性能耗时（tests/test_e1_arms_net.py）

测试环境：MLX CPU 设备（macOS darwin arm64，Python 3.12）。全部 9 项测试通过，总耗时 0.19 秒（最长单项测试耗时 0.0475 秒，严格满足 $\le 10$ 秒约束）：

| 序号 | 测试用例 | 耗时 (s) | 状态 | 验证目标与判定依据 |
|:---:|---|:---:|:---:|---|
| 1 | `test_parameter_count_equality` | 0.0011 | PASSED | 验证 ②③⑥ 三臂参数量严格等于 6150 |
| 2 | `test_determinism_seed` | 0.0033 | PASSED | 验证同种子参数 SHA 完全一致，异种子互异 |
| 3 | `test_arm3_error_lower_than_prior_after_200_steps` | 0.0475 | PASSED | 120 步极小拟合（$\le 200$ 步），10 步误差 0.000787 m 显著低于纯先验 0.006903 m |
| 4 | `test_arm6_orthogonal_projection_inner_product` | 0.0009 | PASSED | 投影底层函数验证：投影后残差与 $J$ 内积 $< 10^{-8}$，未投影 $> 10^{-8}$ |
| 5 | `test_arm6_predict_with_projection_and_diagnostic` | 0.0086 | PASSED | 验证 `predict()` 记录截断数、修正量与雅可比，诊断分支 `project=False` 正常 |
| 6 | `test_arm6_predict_path_applied_corrections_orthogonality` | 0.0084 | PASSED | **（r2 新增必改项）** 走实际 `predict()` 路径：`project=True` 时每步施加修正满足 $\|J^T c\|_\infty < 10^{-8}$；`project=False` 时至少一步不满足 |
| 7 | `test_arm6_injected_identifier_fn` | 0.0021 | PASSED | 验证外部注入参数辨识器正确被调用并更新先验物理参数 |
| 8 | `test_observed_prefix_nan_isolation` | 0.0019 | PASSED | 验证前缀后带有 NaN 时不污染预测结果 |
| 9 | `test_save_load_bitwise_consistency` | 0.0031 | PASSED | 验证权重序列化与反序列化后预测与参数哈希逐位一致 |

---

## 4. 坏对照变异实验（对抗性红灯复核）

在独立临时隔离目录 `/tmp/e1_a2_r2_mutants/` 下构建四个独立变异副本，设置独立 `PYTHONPATH` 指向各变异副本的 `src`，并经由 `python -c "import ainerzero.v9.experiments.e1.arms_net as m; print(m.__file__)"` 逐一确认文件加载隔离性。

### 4.1 变异 1：去掉 ⑥ 的投影（对抗一级 claude 审查绕过）
- **变异位置**：`predict` 内部 `if self.project:` 改为 `if False:`；
- **加载源确认**：`/tmp/e1_a2_r2_mutants/mutant_1_predict_no_projection/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **命中目标测试**：`test_arm6_predict_path_applied_corrections_orthogonality`；
- **运行结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_arm6_predict_path_applied_corrections_orthogonality
  AssertionError: Step 0: max |J^T c| = 0.00022576463146899617 >= 1e-8
  Exit Code: 1
  ```
  **结论**：变异 1 成功变红！彻底封堵了 `predict` 内部正交投影分支被绕过的缺陷。

### 4.2 变异 2：让 ③ 的宽度比 ② 多 1
- **变异位置**：`PriorResidualArm` 中覆盖隐藏层宽度为 65（`hidden_dim = 65`）；
- **加载源确认**：`/tmp/e1_a2_r2_mutants/mutant_2_arm3_width_plus_1/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **命中目标测试**：`test_parameter_count_equality`；
- **运行结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_parameter_count_equality
  AssertionError: assert 6311 == 6150
  Exit Code: 1
  ```

### 4.3 变异 3：初始化不用种子
- **变异位置**：`BaseNetArm.__init__` 中将固定种子替换为系统时间戳随机种子；
- **加载源确认**：`/tmp/e1_a2_r2_mutants/mutant_3_no_seed_init/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **命中目标测试**：`test_determinism_seed`；
- **运行结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_determinism_seed
  AssertionError: assert sha2_a1 == sha2_a2
  Exit Code: 1
  ```

### 4.4 变异 4：save 时漏掉一个参数
- **变异位置**：`BaseNetArm.save` 保存前剔除 `fc3.bias`；
- **加载源确认**：`/tmp/e1_a2_r2_mutants/mutant_4_save_drops_param/src/ainerzero/v9/experiments/e1/arms_net.py`；
- **命中目标测试**：`test_save_load_bitwise_consistency`；
- **运行结果**：
  ```text
  FAILED tests/test_e1_arms_net.py::test_save_load_bitwise_consistency
  RuntimeError: [read] Unable to read 8 bytes from file.
  Exit Code: 1
  ```

---

## 5. 交付物与校验和

- **合规声明**：
  - 本轮工作完全遵循二级执行 agent 规则，未改动范围外文件；
  - 仅使用 MLX CPU 设备，耗时小于 0.2 秒，未触碰真实 GPU 训练或外部预训练权重；
  - 未执行 `git commit` 或 `git push`。

- **交付清单**：
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `tests/test_e1_arms_net.py`
  - `reports/V9-E1A2/gemini-m8x2/r2/REPORT.md`
  - `reports/V9-E1A2/gemini-m8x2/r2/data.json`
  - `reports/V9-E1A2/gemini-m8x2/r2/SHA256SUMS.txt`
