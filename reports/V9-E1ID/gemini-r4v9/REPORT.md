# E1 冻结前钉住源码与 E0 生成器身份报告（ainerzero.V9.P83）

## 1. 执行摘要
- **执行 Agent**：`gemini-r4v9`（二级 执行层 · code）
- **关联任务**：`ainerzero.V9.P83`
- **核心变更**：
  1. `spec.IMPLEMENTATION_SOURCES` 钉住 `src/ainerzero/v9/experiments/e1/` 下全部 16 个 `.py` 模块（按字母排序），并增补测试验证清单与磁盘集合完全相等；
  2. `spec.GENERATOR_SOURCES` 钉住 AWZ E0 生成器 8 个源文件，并定义 `spec.REQUIRED_VELOCITY_INJECTION = "kinematic_preroll_2f_v1"`；
  3. `prereg.collect_source_digests` 与 `collect_generator_digests` 在文件缺失时抛出 `FileNotFoundError`；
  4. 新建 `src/ainerzero/v9/experiments/e1/identity.py`，实现 `verify_frozen_identity`；在 `commands.py` 的计算模式（`generate-data`, `train`, `eval`, `final-eval`）执行前强校验，不一致直接拒绝且不写台账、不启动运行；在 `verify` 模式中报告结果不拒绝；
  5. `data_runner.py` 生成后逐条核验原始轨迹 metadata 的 `velocity_injection`，并在数据根目录写入 `generator_identity.json`；计算模式读取数据时核对该文件，不一致则拒绝；
  6. 完成隔离副本坏对照 (a), (b), (c)，全部证明测试变红；P83 关联测试 32/32 全部通过，全量非 P81 测试 109/109 全部通过。
- **并行约束遵循**：未修改 `worker.py`、`eval_runner.py`、`test_e1_eval_runner.py`、`test_e1_wiring.py`、`test_e1_entry.py` 5 个文件；未修改 AWZ 只读仓库源文件；生成器摘要实时重新计算。

---

## 2. 变更文件与范围核对
| 文件路径 | 状态 | 说明 |
| :--- | :--- | :--- |
| `src/ainerzero/v9/experiments/e1/spec.py` | 修改 | 扩展 IMPLEMENTATION_SOURCES 至 16 模块；新增 GENERATOR_SOURCES 与 REQUIRED_VELOCITY_INJECTION |
| `src/ainerzero/v9/experiments/e1/prereg.py` | 修改 | collect 缺失抛 FileNotFoundError；build_draft 包含生成器与初速度字段；validate 校验 |
| `src/ainerzero/v9/experiments/e1/identity.py` | **新建** | 实现 `verify_frozen_identity` 逐项比对与 `FrozenIdentityMismatchError` |
| `src/ainerzero/v9/experiments/e1/data_runner.py` | 修改 | 原始轨迹 velocity_injection 校验；写入与验证 `generator_identity.json` |
| `src/ainerzero/v9/experiments/e1/commands.py` | 修改 | 各模式在 Preflight 阶段执行源码/生成器身份与数据源身份核查 |
| `tests/test_e1_identity.py` | **新建** | 覆盖 7 项身份核查断言：happy path、源文件突变拒绝、生成器突变拒绝、文件缺失、各模式拦截、只读报告等 |
| `tests/test_e1_prereg.py` | 修改 | 增补清单精确匹配测试、缺失源文件 FileNotFoundError 测试、预登记字段完整性测试（共 18 项全部通过） |
| `tests/test_e1_data_runner.py` | 修改 | 增补缺失/错误初速度校验测试、generator_identity.json 写入与校验测试（共 7 项全部通过） |
| `reports/V9-E1ID/gemini-r4v9/` | **新建** | 包含 `before/` 原始备份、`SHA256SUMS.txt` 与本报告 |

---

## 3. 坏对照（Negative Control / Mutation Testing）验证
所有坏对照均在独立的隔离副本中执行，复制 `src` 与 `tests` 并打印加载文件的 `__file__`，执行结果如下：

### (a) `verify_frozen_identity` 只比较文件名、不比较摘要
- **变异位置**：`/tmp/bad_control_a/src/ainerzero/v9/experiments/e1/identity.py`
- **执行命令**：`python3 -m pytest /tmp/bad_control_a/tests/test_e1_identity.py -k test_mutate_e1_sources_rejected`
- **打印载入**：`[BAD CONTROL A] Loaded identity from: /tmp/bad_control_a/src/ainerzero/v9/experiments/e1/identity.py`
- **测试结果**：`FAILED (exit code 1)`
- **失败证据**：`Failed: DID NOT RAISE <class 'ainerzero.v9.experiments.e1.identity.FrozenIdentityMismatchError'>`

### (b) `commands.py` 在 `train` 模式下跳过核对
- **变异位置**：`/tmp/bad_control_b/src/ainerzero/v9/experiments/e1/commands.py`
- **执行命令**：`python3 -m pytest /tmp/bad_control_b/tests/test_e1_identity.py -k test_commands_preflight_blocks_compute_modes_on_identity_mismatch`
- **打印载入**：`[BAD CONTROL B] Loaded commands from: /tmp/bad_control_b/src/ainerzero/v9/experiments/e1/commands.py`
- **测试结果**：`FAILED (exit code 1)`
- **失败证据**：`AssertionError: assert 'budget_validation' == 'identity_verification'`，证明 `train` 模式跳过了源码核查直接进入后续流程，被断言捕获。

### (c) `data_runner.py` 不检查 `velocity_injection`
- **变异位置**：`/tmp/bad_control_c/src/ainerzero/v9/experiments/e1/data_runner.py`
- **执行命令**：`python3 -m pytest /tmp/bad_control_c/tests/test_e1_data_runner.py -k test_missing_velocity_injection_raises_error`
- **打印载入**：`[BAD CONTROL C] Loaded data_runner from: /tmp/bad_control_c/src/ainerzero/v9/experiments/e1/data_runner.py`
- **测试结果**：`FAILED (exit code 1)`
- **失败证据**：`Failed: DID NOT RAISE <class 'ValueError'>`，证明当原始轨迹缺失 `velocity_injection` 时未进行拦截。

---

## 4. 测试与验证汇总
1. **本任务核心与增补测试**：
   - `tests/test_e1_identity.py`: 7 passed in 0.30s
   - `tests/test_e1_prereg.py`: 18 passed in 0.22s
   - `tests/test_e1_data_runner.py`: 7 passed in 5.58s
   - **核心增补小计**：32 passed (100%)
2. **全量非 P81 模块回归测试**：
   - 包含 `arms_net`, `arms_nonnet`, `export`, `metrics`, `prior`, `train_runner` 等全部 109 项单测 100% 通过（10.65s）。
3. **真实环境 Blender Smoke**：
   - `test_blender_smoke_generation_and_export` 真实运行 Blender 仿真物理流水线并成功通过验证。
