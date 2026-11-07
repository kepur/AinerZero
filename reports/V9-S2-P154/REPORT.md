# S2 smoke 收口实现交付报告（ainerzero.V9.P154）

- **执行者**：`gemini-7k2q`（二级执行 Agent）· 纯 CPU（未运行 MLX、零实盘写入、零常数指标）
- **交付目标**：完成 S2 smoke 收口，接线第 3/4 步并由 s2 规划器驱动任务可行性熔断门（附录 B）：
  1. **Smoke 数据分区生成**：`smoke.py` 中 `generate_smoke_partition` 在隔离命名空间（`smoke_isolated`）生成 4 世界 × 4 回合及 12 个长目标规格至 `output_root/datasets/smoke/`；抽取 shape=(32, 17, 205) 批次；严禁读取 train/dev/final 分区；
  2. **第 3 步（短训健全性接入）**：调用 `smoke_checks.short_train_sanity` 对三臂执行 $S=200$ 步健全性检查，臂 B/C 附挂 SIGReg probe，记录 `action_sensitivity`（纯记录不设假门）；任一臂失败即判定 smoke 失败并列出具体原因；
  3. **第 4 步（S2 规划器驱动 Oracle 任务可行性熔断门）**：在 `smoke_checks.py` 严格新增唯一函数 `oracle_feasibility_with_s2_planner`，采用真实环境动力学 + 位姿编码 + CEM（$N_{\text{fwd}}=4096, L=3 \times \min\text{dist}$）对 12 个长目标回合推演，真实达成率作为熔断门（阈值 0.05）；P152 `_default_oracle_mpc` 作为对照；
  4. **聚合与熔断**：第 1–4 步均通过才置 `passed=True, status="completed"`；缺实测或任一步不通过则 fail-closed。
- **改动范围**：仅改动卡面指定文件：
  - `src/ainerzero/v9/experiments/s2/smoke.py`
  - `src/ainerzero/v9/experiments/s2/smoke_checks.py`（严格仅末尾新增 1 个函数，原有代码一字未改）
  - `src/ainerzero/v9/experiments/s2/spec.py`（严格仅末尾追加 smoke 规模常量）
  - `tests/v9/experiments/test_s2_wiring.py`
  - `tests/v9/experiments/test_s2_smoke_checks.py`
  - `reports/V9-S2-P154/`
- **实测指标**：
  - **S2 规划器 Oracle 可行性实测**：2 世界 × 6 目标共 12 回合，$N_{\text{fwd}}=4096$ 下**实际成功率 83.33%（10/12）**，`fuse_triggered=False`；极小预算 $N_{\text{fwd}}=8$ 下成功率 0.00%（0/12），精确触发熔断门；
  - **端到端伪臂短训判定**：三臂均损失下降时 smoke `passed=True`；一臂下降两臂上升时 smoke `passed=False` 且 `reasons` 明确点名 `arm_b` 与 `arm_c`；
  - **反捏造 AST 审计**：AST 扫描确认 `smoke.py` 与 `smoke_checks.py` 中零常数指标字典、零固定虚假成功率赋硬编码。
- **坏对照对抗变异（3/3 全部 KILLED，独立沙箱隔离执行）**：
  - **P154-M1**（熔断门改回 `_default_oracle_mpc`）：`test_smoke_p154_m1_default_oracle_mpc_red` 变红拦截（KILLED, exit 1）；
  - **P154-M2**（忽略第 3 步短训失败 force passed=True）：`test_smoke_p154_m2_ignore_step3_arm_failure_red` 变红拦截（KILLED, exit 1）；
  - **P154-M3**（绕过种子命名空间检查允许 train/dev 分区）：`test_smoke_p154_m3_rejects_train_dev_namespace` 变红拦截（KILLED, exit 1）。
- **全量回归与实盘审计**：
  - 前台纯 CPU pytest（SIG_DFL 还原）：**3602 passed, 6 deselected, 0 failed**（316.36s）；
  - 实盘 `artifacts/` 80,929 项 stat 差异数严格为 **0**。
- **交付文件 SHA256**：
  - `src/ainerzero/v9/experiments/s2/smoke.py`: `41c07f3d9381d43d3b12928f08982aa638e3ef24df5b69ead93c0ac77ee4929e`
  - `src/ainerzero/v9/experiments/s2/smoke_checks.py`: `13a03b7565be654191ffc8b2092a086fa7eabf0aa62893a8f1edfecebd8eb560`
  - `src/ainerzero/v9/experiments/s2/spec.py`: `b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`
  - `tests/v9/experiments/test_s2_wiring.py`: `c04b5cdb298b470a0d6e0c4ee9cbebb09277210dda4db15af0e91013100e0ec0`
  - `tests/v9/experiments/test_s2_smoke_checks.py`: `d4ed6e933f83e26c45c6a13230299b583020d66ea4678ce4fe91e441802b6c3b`
