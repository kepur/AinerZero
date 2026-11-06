自证声明：复核者为独立二级代理 gemini-a5b8（会话 sess-7b3b52555339），绝非 V9.P148 作者 gemini-w4x2，亦非其同会话别名。本次为全新独立会话纯 CPU 只读复核。

# 非作者复核报告：V9.P148 S2 接线收尾（ainerzero.V9.P149）

- **复核结论**：`RECOMMEND_ACCEPT`（强烈建议接受 P148，各项契约完备，纯 CPU 隔离彻底）
- **复核代理**：`gemini-a5b8`（二级执行 Agent）· 纯 CPU 独立复核（零 GPU/MLX 导入、只读核对、零源码污染）
- **被复核任务**：`ainerzero.V9.P148`（作者：`gemini-w4x2`）

---

## 1. 改动范围核实（文件边界）

1. **`git status` 与 `git diff --stat HEAD` 审查**：
   - 卡面涉及的新模块：
     - `src/ainerzero/v9/experiments/s2/adapters_mlx.py`：MLX 臂适配层；
     - `src/ainerzero/v9/experiments/s2/smoke.py`：smoke 冒烟模式；
     - `src/ainerzero/v9/experiments/s2/commands.py`：supervisor 生命周期入口与 runner 接线；
     - `tests/v9/experiments/test_s2_wiring.py`：纯 CPU 挂接单测；
     - `tests/v9/experiments/test_s2_adapters_mlx_native.py`：隔离 native MLX 测试；
   - 现有代码改动：
     - `src/ainerzero/cli.py`：仅添加 `s2-phase1` 子命令挂接至 `s2_phase1_command`；
     - `tests/conftest.py`：严格只在 `NATIVE_MODULES` 中添加 1 行 `"test_s2_adapters_mlx_native.py"`。
   - 确认 `src/` 下原有历史文件与 HEAD 逐字节一致，零越界改动。

---

## 2. 接线、Verify 模式与 ForwardCounter 核查

1. **各模式接线与前置门禁**：
   - `commands.s2_phase1_command` 对全部 6 个计算模式（`generate-data`, `train`, `plan-select`, `dev-eval`, `final-eval`, `smoke`）逐一在 `worker.execute_work_cell` 内延迟导入对应 runner 并执行；
   - 全部经过三大前置安全门：
     - 预检 A：`_check_approval_preflight` 严格扫描 `RESEARCH_LOG.md` 提取合规批注文档；
     - 预检 B：`check_cell_already_completed` 严格防重；
     - 预检 C：`_check_phase_budget_ceiling` 严格限制单格与 10 小时总相位墙钟上限；
     - 全程在 `worker_lock`（`artifacts/locks/m0-worker.lock`）互斥锁内运行。
2. **`verify` 模式三种状态与篡改检测**：
   - 缺 `prereg.json` 时返回状态 `verified`，标记 `prereg_status: "unfrozen"`，退出码 0；
   - 存在合法 `prereg.json` 且身份吻合时返回状态 `verified`，退出码 0；
   - **篡改检测自测**：在独立的临时隔离仓库中，对 `src/ainerzero/v9/experiments/s2/worker.py` 的 SHA256 修改 1 个字节，运行 `verify` 立即返回非零退出码（exit 1），状态为 `failed`，stage 为 `identity_mismatch`，并在报告中明确点名该文件。
3. **ForwardCounter 评估计费核查**：
   - 静态 AST 检查确认：`MLXArmAAdapter`、`MLXArmBAdapter`、`MLXArmCAdapter` 在规划接口（`encode`, `predict_l1`, `predict_l2`, `encode_l2`, `cost_fn`）中均严格包含 `self.counter.charge(...)`，规划期间评估调用全额计费。

---

## 3. Smoke 冒烟模式独立假臂与规则手算核查

1. **训练步数规则手算核查**：
   - 公式：$\text{steps} = \lfloor 1200 \times 0.8 / t_{\text{step}} \rfloor = \lfloor 960 / t_{\text{step}} \rfloor$；
   - 验证单步耗时：$t_A = 0.08\,\text{s} \to 12000$ 步，$t_B = 0.05\,\text{s} \to 19200$ 步，$t_C = 0.10\,\text{s} \to 9600$ 步；
   - 三臂取最小值：$\min(12000, 19200, 9600) = 9600$ 步，计算规则完全符合附录 A。
2. **独立编写假臂与指标数据测试 5 种情形**：
   - **Case 1（正常放行）**：$\Delta\text{SIGReg} = -0.045 < 0$，敏感度 $0.08 \ge 0.05$，打乱 drop $0.18 \ge 0.10$，长目标成功率 $\ge 0.05$ $\to$ `passed: True`, `circuit_breaker: False`；
   - **Case 2（SIGReg 未下降）**：$\Delta\text{SIGReg} = 0.005 \ge 0$ $\to$ `passed: False`，拦截点名 `SIGReg did not decrease`；
   - **Case 3（动作不敏感）**：敏感度 $0.04 < 0.05$ $\to$ `passed: False`，拦截点名 `Action sensitivity below threshold`；
   - **Case 4（宏观子目标打乱 drop 不足）**：drop $0.09 < 0.10$ $\to$ `passed: False`，拦截点名 `Subgoal shuffle drop below threshold`；
   - **Case 5（熔断器触发）**：所有臂长目标成功率均 $< 0.05$（$0.049, 0.030, 0.048$）$\to$ `passed: False`, `circuit_breaker: True`，拦截点名 `Circuit breaker triggered`。
3. **种子空间隔离与分区零读取**：
   - 命名空间含 `train`, `dev`, `final`, `sealed_final` 均被 `check_smoke_seed_namespace` 拒绝；
   - 源码审计确认 `smoke.py` 绝不打开或读取实盘任何数据分区。

---

## 4. 测试真伪核查

- 审查 `tests/v9/experiments/test_s2_wiring.py` 中 12 项测试：
  - 测试直接调用真实的被测入口 `commands.s2_phase1_command`、`smoke.check_smoke_preconditions`、`smoke.compute_training_steps`、`smoke.check_smoke_seed_namespace`；
  - 没有在测试中重新实现算法逻辑，亦非假常量比对，断言精细有效。

---

## 5. 复核者自做变异（4 处隔离沙盒坏对照，全部变红 KILLED）

复核者在完全隔离的沙盒副本（完整拷贝 `src/`、`tests/`、`pyproject.toml`，断言导入严格解析至副本）中，自做了 4 处**完全独立于作者变异表（P148-M1..M4 之外）**的对抗变异：

| 变异编号 | 变异位置与内容 | 拦截测试用例 | 运行结果 |
|---|---|---|---|
| **REV-P148-M1** | `commands.py` 绕过计算模式的批准预检（`if False:` 替代 `if not approved:`） | `test_commands_refuse_unapproved_compute` | **变红 KILLED** (exit 1) |
| **REV-P148-M2** | `commands.py` 绕过 10 小时总相位预算上限检查（`if False:` 替代 `if not budget_ok:`） | `test_commands_refuse_budget_ceiling_exceeded` | **变红 KILLED** (exit 1) |
| **REV-P148-M3** | `smoke.py` 将动作敏感度阈值判断反转（`act_sens < threshold`） | `test_smoke_logic_five_independent_cases` | **变红 KILLED** (exit 1) |
| **REV-P148-M4** | `smoke.py` 禁用禁止分区种子命名空间断言检查（`if False:` 替代 `if forbidden in norm:`） | `test_seed_namespace_and_no_partition_readback` | **变红 KILLED** (exit 1) |

- 沙盒变异跑完后经 SHA256 逐字节比对，100% 干净还原。

---

## 6. 纯 CPU 隔离验证与全量回归审计

1. **子进程 `-I` 隔离验证**：
   - 运行 `python -I -c "import ainerzero.v9.experiments.s2 as s2, ainerzero.v9.experiments.s2.commands, ainerzero.v9.experiments.s2.smoke; assert 'mlx' not in sys.modules"`；
   - 确认无任何 MLX 模块被载入。
2. **前台全量纯 CPU 回归（SIG_DFL 还原）**：
   - 测试通过计数：**3579 passed, 6 deselected, 0 failed**（总计 3585 项，用时 270.83s）；
3. **实盘 `artifacts/` stat 差异审计**：
   - 测试前扫描：80,929 项；
   - 测试后扫描：80,929 项；
   - **差异数：0 新增、0 删除、0 修改（严格零差异）**。
