# S2 评测补测试交付报告：扰动动作轨迹精确断言（ainerzero.V9.P130）

- **执行代理**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（无 MLX 导入、不修改 `src/`、零实盘写入）
- **背景与目标**：P123 复核 P122 时发现变异 REV-M4（扰动动作数篡改为 1）存活。本卡在 `tests/v9/experiments/test_s2_eval.py` 中对 `test_perturb_inserts_at_step_20_and_is_reproducible` 进行轨迹断言加固，彻底击杀 REV-M4。
- **测试加固实现（`test_s2_eval.py`）**：
  - 设计状态跟踪规划器 `TrackingPlanner`：前 5 次决策（步骤 0..19）返回 `ACTION_WAIT`，第 6 次决策（决策 ID 5）返回特征动作签名 `[ACTION_TURN_LEFT, ACTION_TURN_RIGHT, ACTION_WAIT, ACTION_WAIT]`；
  - **断言 1（扰动前轨迹）**：步骤 0..19（前 20 步）全部严格匹配规划器动作；
  - **断言 2（扰动 5 步精确定位）**：步骤 20..24 恰好为 5 个动作，与 `perturb_rng = random.Random(seed + 99991)` 逐步位对齐匹配；
  - **断言 3（规划器恢复控制）**：步骤 25 准时恢复规划器控制，步骤 25..28 精确呈现决策 ID 5 的特征动作签名；
  - **断言 4（跨回合复现性）**：同种子两次运行的完整动作、轨迹、用步完全逐字相等；
  - **断言 5（非扰动对照）**：非 perturb 回合零扰动动作，决策 ID 5 准时在步骤 20 触发，与扰动模式形成互斥互证。
- **坏对照变异矩阵（隔离副本运行，均变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P130-M1**（扰动动作数改为 1，复现 P123 REV-M4）：变红（KILLED, exit 1），捕捉 `assert [2, 1, 2, 3, 3] == [2, 3, 3, 2, 2]`；
  - **P130-M2**（扰动起点改为第 10 步）：变红（KILLED, exit 1），捕捉 `At index 10 diff: 2 != 3`。
- **全量回归与实盘零写入审计**：
  - 前台纯 CPU pytest 配合 `SIG_DFL` 信号还原：**3516 passed, 6 deselected, 0 failed**；
  - 实盘 `artifacts/` 全量 80,929 项在测试前后执行逐项 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
- **产物与变更**：
  - 仅修改 `tests/v9/experiments/test_s2_eval.py`（零修改 `src/`）；
  - 产物归档于 `reports/V9-S2-P130/`（含 `REPORT.md`、`eval_test.diff`、`mutation_summary.json`、`metrics.json`、`sha256.json`）。
