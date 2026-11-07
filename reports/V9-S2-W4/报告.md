# S2 生产路径集成 W4 报告：smoke 补规划回合计时与总预算推算（附录 D6）

- **任务 ID**：`ainerzero.V9.P167`
- **执行 Agent**：`gemini-b7x4`（二级执行代理）
- **会话 ID**：`sess-bf83650114e6`
- **日期**：2026-11-07
- **工作区**：`/Users/mac/AinerWorkFlow/AinerZero`

---

## 1. 任务背景与核心要求

按照 `reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 D6、附录 B、§6 以及附录 D3.1 / E (r2.6) 的规范：
1. **规划回合计时实测**：`smoke` 阶段针对三大臂（A 扁平、B 子目标、C 层次）各在 smoke long goal specs 上实测 $n_{\text{episodes\_per\_arm}} = 2$ 回合的端到端规划用时，取各臂中位数 $t_{\text{plan}}[a]$。
2. **总预算 7 阶段显式推算**：在 `check_smoke_budget` 中按公式推算 7 个阶段的用时并校验天花板：
   - 数据生成阶段：$1000 \times 8 \times 0.145 = 1160.0$ s（上限 3600.0 s）
   - 训练阶段：$3 \times \sum_{a} \min(1200, \text{shared\_steps} \times t_{\text{step}}[a])$（上限 10800.0 s）
   - 方案选择阶段：$\sum_{a} \text{grid\_size}[a] \times 50 \times t_{\text{plan}}[a]$（上限 1800.0 s）
   - 训后门禁阶段：$100 \times t_{\text{plan}}[\text{arm\_c}]$（计入总预算）
   - 开发集评估阶段：$\sum_{a} (300 \times 3 \times 3.5 + 200 \times 3) \times t_{\text{plan}}[a]$（上限 9000.0 s）
   - 封存最终集评估阶段：$\sum_{a} 300 \times 3 \times t_{\text{plan}}[a]$（上限 5400.0 s）
   - Smoke 阶段：1200.0 s（上限 1200.0 s）
   - 总体上限：36,000.0 s（10 小时）
3. **零捏造常数与故障闭环（fail-closed）**：当缺少 `plan_episode_times`、`step_times` 或前置指标时，必须返回 `passed=False, sufficient=False` 并在 `reasons` 中明确点名缺失字段。
4. **Oracle 熔断门走 s2 规划器（附录 D3.1 / E r2.6）**：熔断门调用 `learned_planning.cem_config_for_budget("flat", spec.SMOKE_PLAN_CHOICE["flat"], n_fwd)`，使用轨迹感知 BFS 距离引导代价。
5. **纯 CPU 执行**：严禁执行或导入 MLX，全部单测在纯 CPU 环境下执行。

---

## 2. 修改文件清单与范围

严格遵循卡面范围约束，仅修改/新增以下文件：
1. `src/ainerzero/v9/experiments/s2/smoke.py`
   - 新增 `measure_planning_episode_times` 函数
   - 升级 `check_smoke_budget` 实现 7 阶段预算公式推算与超额点名校验
   - 更新 `run_smoke` 与 `run_smoke_phases` 产出 `planning_timing` 与完整 `budget_analysis`
2. `src/ainerzero/v9/experiments/s2/smoke_checks.py`
   - 仅升级 `oracle_feasibility_with_s2_planner`：接入 `learned_planning.cem_config_for_budget`，保持附录 E (r2.6) 规划协议契约
3. `tests/v9/experiments/test_s2_smoke_budget.py`（新加单测套件）
   - 8 个测试，全面覆盖推算分解、天花板判定、缺失实测报错、AST 零常数扫描、Oracle 注册配置核验
4. `tests/v9/experiments/test_s2_wiring.py`
   - 为 `_DummySmokeArm` 补齐 `encode`, `latents`, `encode_l2`, `predict_l2` 桩方法
   - 断言缺少输入时 reasons 必须包含 `"plan_episode_times"`
   - 修复 runner 调度用例中的输出目录与桩前置数据
5. `reports/V9-S2-W4/`
   - `REPORT.md`, `metrics.json`, `git_diff.patch`, `mutation_summary.json`

---

## 3. 坏对照与变异分析 (Bad Controls / Mutation Suite)

在沙盒中实施 3 处针对性变异，全部成功变红杀死（Kill Rate 100%）：

| 编号 | 变异描述 | 目标文件 | 捕获测试 | 状态 |
|---|---|---|---|---|
| **W4-M1** | 漏检 dev 阶段天花板超额（注释 dev ceiling 校验） | `smoke.py` | `test_dev_exceeds_budget_fails_and_names_dev` | **RED (killed)** |
| **W4-M2** | 缺少规划计时时默认通过预算推算 | `smoke.py` | `test_missing_planning_times_fails_closed` | **RED (killed)** |
| **W4-M3** | Oracle 熔断门退回写死 CEM 假参数 | `smoke_checks.py` | `test_oracle_planner_uses_registered_cem_config` | **RED (killed)** |

详细记录见 `reports/V9-S2-W4/mutation_summary.json`。

---

## 4. 自动化测试与验证

### 4.1 单元测试通过记录
- `tests/v9/experiments/test_s2_smoke_budget.py`: **8 / 8 passed** (0.84s)
- `tests/v9/experiments/test_s2_wiring.py`: **23 / 23 passed** (165.30s)
- 合计通过数：**31 / 31 passed** (0 失败)

### 4.2 纯 CPU 与零 MLX 泄漏验证
通过 `-I` 子进程验证：
```bash
python3 -I -c "import sys; sys.path.insert(0, '/Users/mac/Library/Python/3.12/lib/python/site-packages'); sys.path.insert(0, 'src'); from ainerzero.v9.experiments.s2 import smoke, smoke_checks; assert not any(m == 'mlx' or m.startswith('mlx.') for m in sys.modules); print('PURE_CPU_VERIFIED')"
```
输出：`PURE_CPU_VERIFIED`，确认未载入任何 MLX 模块。

---

## 5. 交付产物

- 补丁文件：`reports/V9-S2-W4/git_diff.patch` (30 KB)
- 指标数据：`reports/V9-S2-W4/metrics.json`
- 变异报告：`reports/V9-S2-W4/mutation_summary.json`
- 完整报告：`reports/V9-S2-W4/REPORT.md`
