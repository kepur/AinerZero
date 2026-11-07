# S2 生产路径集成 W5：规划协议 r2.6 与批量化推演（附录 E）交付报告

- **任务 ID：** ainerzero.V9.P171
- **层级：** L2（执行层）
- **执行 Agent：** gemini-7k2q (tier 2)
- **会话 Session：** sess-1b76bd83a8ad
- **工作目录：** `/Users/mac/AinerWorkFlow/AinerZero`
- **日期：** 2026-11-07

---

## 1. 概述与核心变更

根据 `reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 E（规划协议可行性修正 r2.6），完成了规划协议修正与批量化推演集成：

1. **协议常数与 MPC 重规划（Appendix E §1, §2）：**
   - 在 `spec.py` 追加登记常数：
     - `PLAN_REPLAN_EVERY_OBS_STEPS = 1`（取代原来的 `REPLAN_M_STEPS = 4` 进行决策执行，m=1 消除开环累积转向偏航）；
     - `PLAN_FUTURE_DT_L1 = 1`（L1 预测后续步使用整数众数 1.0，不再使用非整数 E[k]=1.7）；
     - `PLAN_FUTURE_DT_L2 = 14`（宏步后续步使用 round(s2 * E[k]) = round(8 * 1.7) = 14）；
     - `PLAN_COST_TRAJECTORY_SUM = "trajectory_sum"` 与 `PLAN_COST_TERMINAL = "terminal"`；
   - 在 `learned_planning.cem_config_for_budget` 中更新 `n_exec = int(spec.PLAN_REPLAN_EVERY_OBS_STEPS) = 1`；
   - 在 `learned_planning.make_plan_fn` 中：
     - Flat 臂预测 dts：第一步为宣告的真实 `float(k)`，后续步为 `float(spec.PLAN_FUTURE_DT_L1) = 1.0`；
     - Hierarchical 宏步 dts：第一步为 `float(k) + float(round((s2 - 1) * E[k])) = k + 12.0`，后续步为 `float(spec.PLAN_FUTURE_DT_L2) = 14.0`；下层微步 dts 第一步为 `float(k)`，后续步为 1.0。

2. **代价函数计算（Appendix E §3）：**
   - Flat 臂与上层 CEM：采用预测轨迹全步平方距离和 $\sum_{t=0}^{H-1} ||z_t - z_{\text{goal}}||^2$（Flat 在 L1 空间，上层在 L2 空间）；
   - 下层 CEM：保持终点代价 $||E_2(\hat{z}^1_T) - \hat{z}^2_{\text{subgoal}}||^2$；
   - 计数不变：轨迹累加只利用已前向计算出的潜状态向量，不追加任何额外的网络调用；
   - `flat_cem_plan` 默认使用 `trajectory_sum`；`FlatCEMConfig` 增加 `cost_mode: str = "trajectory_sum"`。

3. **批量化推演与计数不变性（Appendix E §4）：**
   - `planner.py` 实现批量化 CEM：`predict_l1`、`predict_l2`、`encode_l2` 在每一步推演中对整个种群批量调用（`z` 输入维度为 `(pop_size, z_dim)`）；
   - `fwd_counter.ForwardCounter` 依据 `batch_size_of` 自动按 leading dimension `B` 计费（`pop_size`），与逐个调用的总计数值逐位完全一致；
   - `adapters_mlx.py`：对 `MLXArmAAdapter`、`MLXArmBAdapter`、`MLXArmCAdapter` 扩充 2D 批量推演支持，单样本（1D）行为逐位不变；
   - `planner.py` 保留非批量参考实现 `flat_cem_plan_reference` 与 `hierarchical_cem_plan_reference`，供测试验证行为逐位一致。

---

## 2. 闭环验证（GeoPoseArm ≥ 10/12）

在 GridLab-S2 的 2 个世界 × 6 个长目标（共 12 个长目标回合，位姿 BFS 距离 40–46）上测试 r2.6 协议：
- **GeoPoseArm 成功率：** **12/12 (100%)**（门槛要求 ≥ 10/12）；
- **RandomArm 基线成功率：** **0/12 (0%)**（显著低于假臂）；
- 闭环验证完全达标。

---

## 3. 逐位一致性验证（Batching Parity）

在相同 RNG 种子下，批量实现与单步参考实现进行比对：
- **Flat CEM：** `flat_cem_plan` 与 `flat_cem_plan_reference` 输出动作完全逐位一致（`np.testing.assert_array_equal` 通过），`ForwardCounter.total` 与 `by_name` 明细完全一致；
- **Hierarchical CEM：** `hierarchical_cem_plan` 与 `hierarchical_cem_plan_reference` 输出动作及 L2 目标完全逐位一致，`ForwardCounter.total` 与 `by_name` 明细完全一致；
- **速度提升：** CPU 模拟下单次决策规划耗时大幅缩减，`test_s2_learned_planning.py` 全套 41 个测试（含 12 回合闭环与多次参数网格推演）运行总时间由原先估算的 > 200 秒缩短至 16.17 秒。

---

## 4. 坏对照变异测试（Bad Controls，隔离沙箱）

在独立沙箱环境中分别测试 4 项坏对照变异，全部成功变红（RED）：

| 坏对照 ID | 变异内容 | 预期现象 | 实测结果 | 判定 |
|---|---|---|---|---|
| **W5-M1** | Flat 臂回退至终点代价（terminal cost） | 闭环测试失败（< 10/12） | 成功率骤降至 6/12，断言变红 | **RED (通过)** |
| **W5-M2** | 后续步 dt 回退至非整数 E[k]=1.7 | 闭环测试失败（< 10/12） | 成功率骤降至 6/12，断言变红 | **RED (通过)** |
| **W5-M3** | n_exec 回退至 4 步开环重规划 | 转向开环累积偏航失败（< 10/12） | 成功率骤降至 2/12，断言变红 | **RED (通过)** |
| **W5-M4** | 批量推演漏计（batch_size=1） | 计数一致性测试失败 | `c_mut.total=26` vs `c_ref.total=290`，断言变红 | **RED (通过)** |

---

## 5. 纯 CPU 与架构隔离验证

- **纯 CPU 隔离：** 使用 `.venv/bin/python -I` 导入 `ainerzero.v9.experiments.s2`、`commands`、`smoke` 后，`sys.modules` 中包含 `mlx` 的模块数量为 0；
- **Native MLX 测试：** 在 `tests/v9/experiments/test_s2_learned_planning_native.py` 中编写 `test_native_batching_wall_clock_and_parity_per_arm`，测试三臂各做 1 次决策并记录前后 wall clock，按规范只写不跑（受 `pytest.mark.native_mlx` 保护，纯 CPU 回归中自动忽略）；
- **实盘文件保护：** 对 `artifacts/` 目录下全部 59,746 个文件在测试前后执行 `lstat`（mtime、ctime、size、ino）严格校验，差异为 0，零触碰实盘资产。
