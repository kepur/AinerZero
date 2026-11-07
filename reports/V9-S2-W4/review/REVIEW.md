# 非作者独立复核报告：S2 集成 W4（附录 D6 smoke 补规划回合计时与总预算推算）

**自证声明**：本人（复核执行代理：`gemini-7k2q`，会话：`sess-1b76bd83a8ad`）非被验任务 `ainerzero.V9.P167` 之作者（原作者：`gemini-b7x4`，会话：`sess-bf83650114e6`），亦非其同会话别名；本次复核为只读独立核查，纯 CPU 环境执行，未启动或导入 MLX，未修改被测源码。

- **复核任务**：`ainerzero.V9.P169`
- **被复核任务**：`ainerzero.V9.P167`
- **复核结论**：`RECOMMEND_ACCEPT`（建议完全验收）
- **复核日期**：2026-11-07

---

## 1. 范围与代码一致性核查 (Scope & Diff Audit)

核查被验任务交付补丁 `reports/V9-S2-W4/git_diff.patch` 与实际工作区修改：
1. **涉及修改/新增文件**：
   - `src/ainerzero/v9/experiments/s2/smoke.py`（增加 `measure_planning_episode_times` 与 7 阶段预算推算）
   - `src/ainerzero/v9/experiments/s2/smoke_checks.py`（`oracle_feasibility_with_s2_planner` 接入 registered CEM config）
   - `tests/v9/experiments/test_s2_smoke_budget.py`（新加 8 个专项测试）
   - `tests/v9/experiments/test_s2_wiring.py`（桩方法与 reasons 断言对齐）
   - `reports/V9-S2-W4/`（报告、指标与补丁文件）
2. **非卡面文件**：按 `git_diff.patch` 核对，补丁只涉及上述文件。注意：工作区 `git status` 另显示 `adapters_mlx.py`、`commands.py`、`worker.py` 等其他 src 文件有未提交改动，来自其他卡（W1–W3），本复核未逐字节对比，也不归因于 P167。

---

## 2. 生产路径接线与零捏造常数审计 (Production Path & Zero-Fallback Audit)

1. **生产调用链追踪**：
   - `cli.main` -> `s2_phase1_command` -> `_smoke_runner` -> `smoke.run_smoke(execute_real=True)`。
   - 在真实 smoke 路径下，先调用 `measure_planning_episode_times` 实测 3 大臂的 long-goal 规划用时，并在阶段 2 真实测量每臂 $K=20$ 步训练耗时。
   - 所有测量数据显式注入 `check_smoke_budget(timing_res, step_times, plan_episode_times)`，严禁硬编码。
2. **零回退/零写死常数静态扫描**：
   - 检查 `smoke.py` 与 `smoke_checks.py` 中的关键路径，未见 `or []`、`or {}`、`getattr(..., default)` 等隐式保底。
   - 当缺少 `plan_episode_times`、`step_times` 或 `shared_train_steps` 时，直接返回 `sufficient=False, passed=False` 并在 `reasons` 中明确点名缺失字段，实现严格的 fail-closed 故障闭环。

---

## 3. 坏对照与独立变异测试 (Bad Controls & Mutation Verification)

在隔离沙箱环境中对作者提出的 3 处变异及复核者自选的 1 处变异进行重放验证，每处均按字节变更、运行测试确认变红（RED / Killed），再按 SHA256 逐字节还原：

| 变异编号 | 变异位置与描述 | 捕获测试与特征 | 验证状态 | SHA256 还原核对 |
|---|---|---|---|---|
| **W4-M1** | `smoke.py`: 注释掉 dev 阶段天花板检查 (`est_dev > ceil_dev`) | `test_dev_exceeds_budget_fails_and_names_dev` 失败并报告未捕获超额 | **RED (Killed)** | 恢复后 SHA 校验一致 |
| **W4-M2** | `smoke.py`: 缺少规划计时仍返回 `sufficient=True` | `test_missing_planning_times_fails_closed` 失败 (`assert not res["sufficient"]`) | **RED (Killed)** | 恢复后 SHA 校验一致 |
| **W4-M3** | `smoke_checks.py`: Oracle 熔断门退回写死 `FlatCEMConfig` | `test_oracle_planner_uses_registered_cem_config` 抛出 `AssertionError: ... must NOT use hardcoded FlatCEMConfig` | **RED (Killed)** | 恢复后 SHA 校验一致 |
| **W4-M4** (自选) | `smoke.py`: 注释掉 final evaluation 阶段天花板检查 (`est_final > ceil_final`) | `test_final_exceeds_budget_fails_and_names_final` 失败并报告未捕获 final 超额 | **RED (Killed)** | 恢复后 SHA 校验一致 |

**变异击杀率**：4 / 4 (100%)。

---

## 4. REPORT.md 事实性原话三点抽验 (3-Point Verbatim Spot Check)

对 `reports/V9-S2-W4/REPORT.md` 的核心论断进行逐字源码对照：
1. **抽验项 1：训练阶段总预算计算公式**
   - *REPORT.md 原话*：`3 * sum(min(1200, shared_steps * t_step[a]))`
   - *源码实测*：`smoke.py` L332-L334：
     ```python
     slot_sec = min(float(spec.BUDGET_TRAIN_PER_SLOT_SECONDS), shared_steps * t_step_by_arm[arm_id])
     per_arm_train[arm_id] = 3.0 * slot_sec
     est_train = float(sum(per_arm_train.values()))
     ```
     其中 `spec.BUDGET_TRAIN_PER_SLOT_SECONDS = 1200.0`，3 个种子 3 个臂，完全相符。
2. **抽验项 2：开发集评估阶段倍率 (3.5)**
   - *REPORT.md 原话*：`3.5`（由 `1.0 + 2048/4096 + 8192/4096` 算出）
   - *源码实测*：`smoke.py` L365：
     ```python
     curve_multiplier = 1.0 + (2048 / 4096.0 + 8192 / 4096.0)  # 3.5
     ```
     完全相符。
3. **抽验项 3：缺失规划计时时的报错点名**
   - *REPORT.md 原话*：缺少 `plan_episode_times` 时返回 `passed=False, sufficient=False` 并在 `reasons` 中明确点名缺失字段。
   - *源码实测*：`smoke.py` L256-L265：
     ```python
     if plan_episode_times is None:
         reasons.append("Budget analysis failed: plan_episode_times is None")
     if reasons:
         return {"sufficient": False, "passed": False, "reasons": reasons, ...}
     ```
     完全相符。

---

## 5. 回归测试与纯 CPU / 守卫验证 (Regression & Guards Verification)

1. **S2 核心自动化单测**：
   - 运行 148 个 S2 核心测试用例（包括 `test_s2_smoke_budget.py`、`test_s2_wiring.py`、`test_s2_learned_planning.py` 等）：
   - 结果：**148 passed in 218.92s (0:03:38)**，0 failed。
2. **Artifacts 守卫审计**：
   - 测试前 snapshot：59,746 个文件。
   - 测试后 snapshot：59,746 个文件。
   - 增量对比：Added = 0, Removed = 0, Modified = 0。零污染。
3. **纯 CPU / 零 MLX 导入独立验证**：
   - 运行独立纯净 `-I` 子进程：
     ```bash
     python3 -I -c "import sys; sys.path.insert(0, '/Users/mac/Library/Python/3.12/lib/python/site-packages'); sys.path.insert(0, 'src'); from ainerzero.v9.experiments.s2 import smoke, smoke_checks, commands; assert not any(m == 'mlx' or m.startswith('mlx.') for m in sys.modules); print('PURE_CPU_VERIFIED_INDEPENDENT')"
     ```
   - 输出：`PURE_CPU_VERIFIED_INDEPENDENT`，无任何 MLX 模块泄露到 `sys.modules`。

---

## 6. 最终复核意见

本任务实现完全满足 `reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 D6 及统筹参数约束。零写死数字，fail-closed 机制完备，坏对照全部变红，回归全通且无资源泄露。

**判定结果**：`RECOMMEND_ACCEPT`。
