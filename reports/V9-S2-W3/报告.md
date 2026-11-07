# S2 生产路径集成 W3：plan-select / 训练后门 / dev / final 接线与端到端测试报告

- **任务 ID**：`ainerzero.V9.P168`
- **执行 Agent**：`gemini-7k2q` (Tier 2, session `sess-1b76bd83a8ad`)
- **工作规范**：`AGENTS.md`、`reports/V9-S2-DESIGN/DESIGN-r2.md` §5、§6、附录 B、D4、D5、D7
- **执行环境**：纯 CPU（Apple Silicon Mac, Darwin 24.3.0, Python 3.12.2, pytest-9.1.1），无 MLX 运行，无 GPU 抢占

---

## 一、 执行摘要与自证

本 Agent (`gemini-7k2q`) 严格按照 S2 研发规范完成 **W3 生产路径集成** 工作。
在整个实现和验证过程中：
1. **纯 CPU 离线验证**：全量测试套件在纯 CPU 下执行，未启动任何原生 MLX 训练，未侵占中央锁 `artifacts/locks/m0-worker.lock`。
2. **零 Fallback 约束（Zero Fallbacks in Production）**：彻底剔除生产路径中的 fallback 降级分支，确保生产代码故障时快速拒跑（fail-closed），不掩盖真实错误。
3. **闭环生产端到端验证**：实现全生命周期端到端测试 `tests/v9/experiments/test_s2_production_e2e.py`，完整覆盖 `smoke -> generate-data (train, dev, final) -> train (3 arms x 3 seeds) -> plan-select (含训练后门) -> dev-eval (严格限额 2 次) -> final-eval (单次开封只读标记)`。

---

## 二、 关键架构实现与问题修复

### 1. 消除生产路径 Fallback (Zero Fallbacks)
- **剔除假成功与随机分支**：在 `eval_runner._episode_success_stub` 中彻底消除随机概率分支，统一走 `learned_planning.make_plan_fn` 与 `eval.run_episode`（附录 D4/D5）。
- **剔除打分兜底**：在 `_score_config_on_train` 中消除 0.5 默认打分兜底，真实执行 CEM 网格打分；输入非法时直接抛出 `PlanSelectError`。
- **剔除命令层静默字典降级**：在 `commands.py` 各 runner 中移除 `or []`、`or {}`、`or None -> new` 静默兜底；上游产物缺失时显式拒跑并指明缺失阶段。

### 2. 训练后门（Post-train Gates）接线与基线合理性门禁
- **动作敏感性门禁（Action Sensitivity Gate）**：验证 3 臂 × 3 种子共 9 个模型，断言扰动动作下输出变化率达到阈值。
- **C 臂子目标打乱负对照（C Negative Control Gate）**：对分层 C 臂进行子目标乱序测试，断言成功率下降值 $\ge 0.05$（附录 B 防范下层不使用子目标的合谋行为）。
- **基线合理性门禁（Baseline Rationality Gate）**：依据附录 B / D4 要求，增加 $\max(\text{Arm A}, \text{Arm B}) \in [0.10, 0.80]$ 检查。若基准臂全部未学会（$<0.10$）或已封顶（$>0.80$），拒绝放行。

### 3. Dev 评估限额与 Final 单次开封只读保护
- **Dev Ledger 2-Call Cap**：在 `eval_runner.run_dev_eval` 中强制读取并写入 `output_root/dev_ledger.json`，第 3 次调用严格抛出 `DevEvalCapExceeded`。
- **免除 SQLite 重复执行死锁**：在 `worker.py` 与 `commands.py` 中，对 `dev-eval` 豁免 SQLite 的 cell 重复执行检查（因 `dev-eval` 的 2 次调用额度受 `dev_ledger.json` 严格管辖）。
- **Final Read-Once Marker**：在 `eval_runner.run_final_eval` 中要求 `RESEARCH_LOG.md` 存在合规审批，首次运行自动创建 `READ_ONCE_MARKER_NAME`，二次运行直接抛出 `FinalEvalRefused`。

### 4. 接口与类型安全修复
- **S2Ledger 实例路径解析**：在 `adapters_mlx.load_trained_model` 中，安全提取 `ledger.db_path` 或 `ledger.path`，解决传入 `S2Ledger` 对象时的 `TypeError`。
- **Multi-seed 臂名称解析**：在 `eval_runner.run_dev_eval` 中从 `frozen_plan_config["arms"]` 提取干净的臂名称（`arm_a`, `arm_b`, `arm_c`），避免将种子后缀键（如 `arm_a/42`）错误当作臂名抛出 `ValueError`。
- **ProductionFakeArm 存储校验**：端到端假臂保存真实字节并计算 SHA256，匹配 ledger 校验规则。

---

## 三、 变异测试（Bad Controls / Mutation Testing）

在隔离环境中实施了 5 处针对性变异（W3-M1 至 W3-M5），全部成功变红（100% 击杀）：

| 变异 ID | 变异描述 | 目标文件 | 失败用例 | 失败特征 / 错误信息 | 判定结果 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **W3-M1** | 恢复 planning 中伪造成功或随机分支 | `eval_runner.py` | `test_dev_voids_when_forward_budget_exceeded` | `AssertionError: expected voided comparisons when budget exceeded` | **KILLED** |
| **W3-M2** | plan-select 打分回退到 0.5 常数 | `eval_runner.py` | `test_plan_select_tie_break_smaller_compute` | `assert 16 == 32`（打分无区分度导致择优失效） | **KILLED** |
| **W3-M3** | dev 评估仅测单个种子 `seeds=(42,)` | `eval_runner.py` | `test_dev_eval_evaluates_all_seeds` | `AssertionError: Dev eval must evaluate all 3 seeds (42, 43, 44), got {42}` | **KILLED** |
| **W3-M4** | Bootstrap 重采样数降为 200（低于 10,000） | `spec.py` | `test_spec.py`, `test_prereg.py` | `assert 200 == 10000` / `PreregValidationError` | **KILLED** |
| **W3-M5** | 绕过 / 禁用基线合理性门禁 | `eval_runner.py` | `test_production_e2e_blocks_unplannable_arm` | `Failed: DID NOT RAISE PostTrainGateRefused` | **KILLED** |

---

## 四、 单元测试与端到端测试结果

执行命令：
```bash
PYTHONPATH=. .venv/bin/pytest tests/v9/experiments -k "s2 and not native"
```

测试结果：
- **总通过用例数**：266 passed
- **失败用例数**：0 failed
- **反选 / 跳过原生用例数**：381 deselected
- **MLX 导入检查**：`test_zero_mlx_imported` 与 `test_pure_cpu_isolation_commands_and_smoke_do_not_import_mlx` 全部通过，无 MLX 导入。
- **端到端流程验证**：
  1. `test_production_e2e_pipeline`: 成功打通 `smoke -> generate-data -> train -> plan-select -> dev-eval (2次) -> final-eval (只读封存)`。
  2. `test_production_e2e_blocks_unplannable_arm`: 成功拦截基线成功率仅 0.05 的不合理臂。
  3. `test_production_e2e_blocks_colluding_c_arm`: 成功拦截子目标乱序未下降的合谋 C 臂。

---

## 五、 交付产物清单

- 完整补丁：`reports/V9-S2-W3/git_diff.patch`
- 变异摘要：`reports/V9-S2-W3/mutation_summary.json`
- 测试指标：`reports/V9-S2-W3/metrics.json` / `reports/V9-S2-W3/指标.json`
- 中英文总结报告：`reports/V9-S2-W3/REPORT.md` / `reports/V9-S2-W3/报告.md`

结论：S2 W3 生产路径集成全部验收项达标，无任何降级 fallback，通过纯 CPU 回归与全生命周期端到端测试。
