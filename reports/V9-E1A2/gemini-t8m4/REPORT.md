# E1-A2 网络臂实现与测试报告（ainerzero.V9.P69）

- **执行者**：gemini-t8m4（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P69`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 69 步（E1-A2 网络臂）
- **依据协议**：
  - `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-A2
  - `reports/V9-P48/PREREG_DRAFT.md` §2（臂表：②③⑥）
  - `reports/frontier-integration-20261027/DESIGN_CORE.md` §2 第 7 条（残差与参数灵敏度正交投影）
- **文件改动范围**：
  - 新增：`src/ainerzero/v9/experiments/e1/arms_net.py`
  - 新增：`tests/test_e1_arms_net.py`
  - 导出更新：`src/ainerzero/v9/experiments/e1/__init__.py`
  - 交付成果：`reports/V9-E1A2/gemini-t8m4/`

---

## 1. 网络臂架构与接口实现

本模块严格在 **MLX CPU 设备**（`mx.set_default_device(mx.cpu)`）上实现，遵循 E1-A1 统一接口：
`predict(observed_prefix, static_env, n_future)`，并提供 `train_step(batch)`、`save(path)`、`load(path)`、`parameter_sha256()` 及 `count_parameters()`。

### 1.1 ② PureNetArm（纯 MLX 动力学网络）
- **输入**：滑动窗口内最近 $K=4$ 帧的状态历史（位置与速度，共 $4 \times 6 = 24$ 维）。
- **结构**：MLX 3 层全连接网络（`DynamicsMLP`：$24 \to 64 \to 64 \to 6$）。
- **预测**：输出下一帧状态增量 $[\Delta \mathbf{x}, \Delta \mathbf{v}]$，自回归（autoregressive）向后展开 $n\_future$ 步。

### 1.2 ③ PriorResidualArm（先验 + MLX 残差网络）
- **机理**：每帧先用 `prior.DEFAULT_BIASED_PRIOR` 进行 600 Hz 半隐式欧拉积分（10 个子步，与先验积分器完全一致），随后叠加 MLX 残差网络预测的状态修正量 $[\Delta \mathbf{x}_{res}, \Delta \mathbf{v}_{res}]$。
- **结构**：与 ② 采用完全相同的 `DynamicsMLP` 结构（$24 \to 64 \to 64 \to 6$）。

### 1.3 ⑥ IdentifyResidualArm（辨识 + 正交投影残差网络）
- **参数辨识**：定义可注入的辨识函数接口 `IdentificationFn`；前缀观测先由辨识器推断 $\hat{\phi}$（缺省回退至 `DEFAULT_BIASED_PRIOR`），物理先验步带入 $\hat{\phi}$ 积分。
- **正交投影（DESIGN_CORE §2 第 7 条）**：
  - 残差修正量先投影到中心差分雅可比 $\partial F_{prior}/\partial \phi$（形状 $6 \times 5$）张成子空间的正交补上：
    $$\mathbf{r}_{\perp} = \mathbf{r} - \mathbf{U}_{basis} (\mathbf{U}_{basis}^T \mathbf{r})$$
  - 采用 `jacobian.compute_orthogonal_projection_basis` 进行奇异值截断（截断阈值相对 $10^{-6} \cdot \sigma_{max}$）；
  - 统计被截断（降秩）的方向数并存入 `last_truncated_counts`。
- **诊断变体**：支持 `project=False` 模式作为未施加正交约束的对照组。

---

## 2. 结构参数与确定性验证

- **参数量严格一致**：
  - 模块常量 `REGISTERED_PARAMETER_COUNT = 6150`；
  - ② `PureNetArm`：$24 \times 64 + 64 + 64 \times 64 + 64 + 64 \times 6 + 6 = 6150$；
  - ③ `PriorResidualArm`：$6150$；
  - ⑥ `IdentifyResidualArm`：$6150$；
  - 三臂网络参数量逐位相等。
- **确定性初始化**：
  - 同一种子（如 42）初始化时，参数 SHA256 完全一致（`f939cfdb6239f069788f1a239c8dc91e6b9bb6d1d2614588d05a71ea6ea5eea2`）；
  - 不同种子（如 999）初始化时，参数 SHA256 必然不同（`73e86699a4098b302ff988e3cc61ba2d8731919a738b04b5e41c0d1aaddfdd5a`）。
- **前缀隔离**：前缀后打上 `NaN` 的观测输入与无 `NaN` 输入给出的预测结果逐位一致。
- **保存与加载**：`save` 保存至 safetensors 文件后由异种种子实例 `load`，恢复后预测结果逐位完全一致。

---

## 3. 单元测试与性能（tests/test_e1_arms_net.py）

全部 8 项测试在纯 MLX CPU 设备上运行通过，总耗时 0.30 秒：

| 测试项 | 耗时 | 验证要点 |
|---|---|---|
| `test_parameter_count_equality` | 0.003s | ②③⑥ 参数量严格等于 6150 |
| `test_determinism_seed` | 0.004s | 同种子 SHA 相同，异种子 SHA 不同 |
| `test_arm3_error_lower_than_prior_after_200_steps` | 0.074s | 120 步 CPU 极小拟合（$\le 200$ 步、$\le 10$ s），10 步误差 0.000787 m 显著低于纯先验 0.006903 m（相对降低 88.6%） |
| `test_arm6_orthogonal_projection_inner_product` | 0.002s | 投影后残差与 Jacobian 各列内积最大 $6.44 \times 10^{-20} < 10^{-8}$；`project=False` 时 $1.06 \times 10^{-3} > 10^{-8}$ |
| `test_arm6_predict_with_projection_and_diagnostic` | 0.012s | 截断方向数准确计数返回；`project=False` 诊断变体正常运行 |
| `test_arm6_injected_identifier_fn` | 0.003s | 可注入辨识器正常捕获前缀并更新参数 |
| `test_observed_prefix_nan_isolation` | 0.003s | 前缀之后打上 NaN 不污染预测 |
| `test_save_load_bitwise_consistency` | 0.004s | 权重存盘与加载后预测逐位一致 |

---

## 4. 坏对照（源码变异攻击验证）

在独立隔离目录（`/tmp/e1_a2_mutants/`）下对源码实施变异，设置独立 `PYTHONPATH` 并打印 `__file__`，逐项证明对应测试变红（失败）：

1. **变异 1：去掉 ⑥ 的正交投影**
   - 变异操作：在 `project_onto_orthogonal_complement` 中将投影残差替换为未投影原始残差；
   - 指向源：`/tmp/e1_a2_mutants/mutant_1_no_projection/ainerzero/v9/experiments/e1/arms_net.py`；
   - 目标测试：`test_arm6_orthogonal_projection_inner_product`；
   - 变红结果：`FAILED: AssertionError: Max dot product 0.0010579 >= 1e-8`（Exit Code 1）。
2. **变异 2：让 ③ 的宽度比 ② 多 1**
   - 变异操作：在 `PriorResidualArm.__init__` 中强制 `hidden_dim = 65`；
   - 指向源：`/tmp/e1_a2_mutants/mutant_2_arm3_width_plus_1/ainerzero/v9/experiments/e1/arms_net.py`；
   - 目标测试：`test_parameter_count_equality`；
   - 变红结果：`FAILED: AssertionError: assert 6311 == 6150`（Exit Code 1）。
3. **变异 3：初始化不用种子**
   - 变异操作：在 `BaseNetArm.__init__` 中移除固定种子，改用未锁定的随机种子；
   - 指向源：`/tmp/e1_a2_mutants/mutant_3_no_seed_init/ainerzero/v9/experiments/e1/arms_net.py`；
   - 目标测试：`test_determinism_seed`；
   - 变红结果：`FAILED: AssertionError: assert sha2_a1 == sha2_a2`（Exit Code 1）。
4. **变异 4：save 时漏掉一个参数**
   - 变异操作：在 `BaseNetArm.save` 中保存前从参数字典中剔除 `fc3.bias`；
   - 指向源：`/tmp/e1_a2_mutants/mutant_4_save_drops_param/ainerzero/v9/experiments/e1/arms_net.py`；
   - 目标测试：`test_save_load_bitwise_consistency`；
   - 变红结果：`FAILED: RuntimeError / Mismatch`（Exit Code 1）。

四组坏对照全数变红，变异监督测试无虚假放行。

---

## 5. 合规声明与交付物

- **合规声明**：本次工作纯粹在 MLX CPU 设备完成，不使用 GPU，不申请也不消耗训练预算，不触碰真实数据，不写入中央台账。未改动 `src/ainerzero/v9/geometry/` 或其他非授权范围文件，不执行 git commit 或 git push。
- **交付清单**：
  - 源码：`src/ainerzero/v9/experiments/e1/arms_net.py`
  - 模块入口：`src/ainerzero/v9/experiments/e1/__init__.py`
  - 单元测试：`tests/test_e1_arms_net.py`
  - 报告目录：`reports/V9-E1A2/gemini-t8m4/REPORT.md`、`data.json`、`SHA256SUMS.txt`
