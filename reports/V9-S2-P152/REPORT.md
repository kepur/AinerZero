# S2 smoke 第 3/4 步实现交付报告（ainerzero.V9.P152）

- **执行者**：`gemini-a5b8`（二级执行 Agent）· 纯 CPU（未运行 MLX、零实盘写入、严禁常数指标）
- **交付目标**：实现 `smoke_checks.py` 供 smoke 调用（附录 B 第 3、4 步精确算法，缺实测一律报错）：
  1. `short_train_sanity(arm, batches, S, sigreg_probe=None)`：训练 S 步（S≥20），严格判定所有损失有限、末 20 步均值 < 首 20 步均值、SIGReg 末值 ≤ 1.1 × 初值；
  2. `action_sensitivity(predict_fn, states, n_actions=4)`：计算 4 动作两两 L2 预测距离均值，归一化除以 `mean(||z||)`，纯指标计算不设假门；
  3. `oracle_feasibility(layout_specs, planner_fn, n_fwd, rng, threshold=0.05)`：用真实 GridLab 动力学推演 + BFS 距离代价驱动 CEM，< 0.05 时熔断。
- **改动范围**：仅新增 `src/ainerzero/v9/experiments/s2/smoke_checks.py` 与 `tests/v9/experiments/test_s2_smoke_checks.py`（未改动 `smoke.py` 或 `commands.py`）。
- **实测指标**：
  - **Oracle 任务可行性实测**：2 世界 × 6 长目标（共 12 回合），$N_{\text{fwd}}=2000$ 下**实际成功率 83.33%（10/12）**，`fuse_triggered=False`；在极小预算 $N_{\text{fwd}}=8$ 下成功率 0.00%（0/12），精确触发熔断。
  - **动作敏感性实测**：手算基准值精确匹配 $(2\sqrt{2}+2)/3 \approx 1.6095$；动作无关模型输出 0.0000。
- **对抗变异（3/3 全红变绿已复原，隔离沙盒执行）**：
  - **P152-M1**（去除 NaN/有限损失检查）：`test_short_train_sanity_nan_loss_fails` 变红拦截（KILLED, exit 1）；
  - **P152-M2**（默认熔断阈值放宽至 0.50）：`test_oracle_feasibility_partial_success_does_not_fuse_at_005` 变红拦截（KILLED, exit 1）；
  - **P152-M3**（函数中硬编码常数指标字典）：`test_anti_fabrication_ast_scan` 变红拦截（KILLED, exit 1）。
- **反捏造 AST 审计**：AST 遍历确认代码中零常数指标字典、零固定虚假成功率赋值。
- **全量回归与实盘审计**：前台纯 CPU pytest（SIG_DFL 还原）：**3595 passed, 6 deselected, 0 failed**（271.19s）；实盘 `artifacts/` 80,929 项 stat 差异数严格为 0。
- **新文件 SHA256**：
  - `src/ainerzero/v9/experiments/s2/smoke_checks.py`: `090a404e5dde55c5d59a105eb7f045c31ec83f930a4753653c521d5176c359d7`
  - `tests/v9/experiments/test_s2_smoke_checks.py`: `9f4eabbf935aca9d643a4ae1168c7ebb49a4990b949da9e7e567c2a7ea2bb04e`
