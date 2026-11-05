# 任务报告 ainerzero.V9.P76 (r2)：E1 入口接线与中央台账预留重构

## 1. 任务基本信息
- **任务编号**：`ainerzero.V9.P76`
- **交付轮次**：`r2`
- **执行 Agent**：`gemini-cv3y`（二级执行 agent，code 类型）
- **所属阶段**：AinerZero · V9 落地世界系统侧 (E1 实验体系)
- **文件范围**：
  - `src/ainerzero/v9/experiments/e1/worker.py`
  - `src/ainerzero/v9/experiments/e1/commands.py`
  - `src/ainerzero/cli.py`
  - `tests/test_e1_wiring.py`
  - `tests/test_e1_entry.py`
  - `reports/V9-E1W/gemini-cv3y/r2/`
- **交付状态**：`completed`

---

## 2. 统筹者打回意见与 r2 针对性修复

针对一级统筹者（Claude）在 r1 提出的 4 项必改问题，本轮进行了逐条彻底重构：

### 问题 1：台账预留只有 1 秒导致 32 h 上限失真
- **原缺陷**：`active_cost = simulated_duration if simulated_duration is not None else 1.0`，无论格预算多大台账只记 1 s，中央累计失真，32 h 总上限永远触发不了。
- **r2 修复**：
  1. 在 `execute_work_cell` 中遵循 S1 原则（**先预留再干活**），开工时全额预留格预算：`ledger.reserve(run_id, active_seconds=cell_wall_budget)`。
  2. 修复 `open_run` 中 snapshot 的 `max_wall_seconds` 为总上限（避免微小时间流逝导致初始预留越界），并在 `RunRecord` 的 `active_seconds` / `reserved_active_seconds` 中忠实记录该格预留量。
  3. 重构 `_check_phase_budget_ceiling`：通过只读快照查询台账中所有运行的 `active_seconds`（或配置中的格预算），计算全部已预留总和，严格判断 `consumed + new_cell_budget > total_ceiling`。

### 问题 2：runner 返回的状态被忽略，一律收尾为 completed
- **原缺陷**：runner 因预算或截止时间返回 `status: "stopped"` 时，台账仍记为 `completed`，导致防重复训练拒绝重训、eval 找不到权重。
- **r2 修复**：
  1. `execute_work_cell` 严格读取 runner 返回的 `status`：
     - 若 `status == "stopped"`，收尾状态记为 `stopped`，记录停止原因；
     - 若 `status == "failed"`，收尾状态记为 `failed`；
     - 仅当正常完成时才收尾为 `completed`。
  2. `check_cell_already_completed` 仅匹配 `state == "completed"`，对于 `stopped` 或 `failed` 的单元格，明确允许重试运行。

### 问题 3：runner 调用缺少 try/except 导致异常后状态悬挂
- **原缺陷**：调用 runner 外层无保护，一旦抛出异常，run 永久停留在 `training` 或 `validating`。
- **r2 修复**：
  在 `execute_work_cell` 中对外层 runner 调用包裹完整的 `try ... except Exception as exc`：
  捕获异常后立即执行 `ledger.finish_run(run_id, state="failed", reason=f"{type(exc).__name__}: {str(exc)}")`，将台账正确置为失败状态，然后无损重新抛出（`raise`）。

### 问题 4：生产路径中混入测试钩子 `simulated_duration` 与 `advance_clock_fn`
- **原缺陷**：`simulated_duration` 与 `advance_clock_fn` 侵入生产代码并在 runner 之前推进时钟，生产运行时此检查等于没做。
- **r2 修复**：
  1. 从 `execute_work_cell` 的参数列表与内部逻辑中彻底删除 `simulated_duration` 和 `advance_clock_fn`。
  2. 从 `commands.py` 中删除相关参数传递。
  3. 假时钟演练完全通过外部注入的 `FakeClock` 与 `FakeCellRunner` 实现：测试用的 fake runner 在自身的方法内部主动调用 `clock.advance(dt)`，生产路径达到零测试钩子纯净度。

---

## 3. 测试验证与结果

### 3.1 新增单元测试与全流程演练 (`tests/test_e1_wiring.py`)
1. **`test_reserve_amount_equals_cell_wall_budget`**：
   验证启动 work cell 时，中央台账中生成的记录其 `reserved_active_seconds` 严格等于入参的 `cell_wall_budget`（1200.0 s）。
2. **`test_runner_stopped_recorded_as_stopped_and_permits_rerun`**：
   验证假 runner 返回 `{"status": "stopped", "reason": "budget_exhausted"}` 时，台账状态准确置为 `stopped`；随后 `check_cell_already_completed` 返回 `False` 允许重跑；第二轮使用成功 runner 执行后，状态转为 `completed`，且防重复正式生效。
3. **`test_runner_exception_recorded_as_failed`**：
   验证假 runner 抛出运行时异常时，外层捕获并收尾为 `state="failed"`，原因携带异常信息，并向上重抛。
4. **`test_fake_clock_full_schedule_rehearsal_dual_family`**：
   - 完整模拟 E1 Phase 2 注册表中的全部 51 个单元格（1 数据生成 + 18 训练 + 30 验证评估 + 2 最终评测）；
   - 验证已预留总和精确为 111600.0 s（7200 + 18×4800 + 18×600 + 12×300 + 2×1800）；
   - 验证已预留总和 ≤ 32 h 上限（115200.0 s）；
   - 演练补充消耗剩余 3600.0 s 预算达到满额（115200.0 s）后，后续任何新增单元格均被 `_check_phase_budget_ceiling` 拦截，返回 `EXIT_REFUSED_RESOURCE` 且 `stage == "phase_budget_exceeded"`。

### 3.2 测试执行实测
```bash
# Wiring 专项测试 (8 passed)
.venv-ainerzero/bin/pytest tests/test_e1_wiring.py -v
============================== 8 passed in 2.46s ===============================

# Entry 专项测试 (11 passed)
.venv-ainerzero/bin/pytest tests/test_e1_entry.py -v
============================== 11 passed in 1.89s ==============================

# E1 全量测试回归 (111 passed)
.venv-ainerzero/bin/pytest tests/test_e1_*.py -v
============================= 111 passed in 12.97s =============================
```
111 项测试全部绿灯通过，零失败，零回归。

---

## 4. 源码突变坏对照（Bad Controls）证据

在独立隔离的临时沙箱目录中执行 `reports/V9-E1W/gemini-cv3y/r2/run_bad_controls.py`，打印了执行脚本路径并验证 4 项源码突变全部有效变红（RED）：

| 坏对照编号 | 源码突变内容 | 预期变红表现 | 实测结果 | 结论 |
|---|---|---|---|---|
| **BC 1** | 将 `ledger.reserve` 预留额改回写死的 `1.0` s | `test_reserve_amount_equals_cell_wall_budget` 断言 `1.0 == 1200.0` 失败 | `AssertionError: assert 1.0 == 1200.0` (exit code 1) | **RED (通过)** |
| **BC 2** | 忽略 runner 返回状态，一律记录为 `completed` | `test_runner_stopped_recorded_as_stopped_and_permits_rerun` 断言 stopped 状态失败 | `AssertionError: assert 'completed' == 'stopped'` (exit code 1) | **RED (通过)** |
| **BC 3** | 去掉 runner 调用外层的 try/except 保护 | `test_runner_exception_recorded_as_failed` 断言状态为 failed 失败（保持 training） | `AssertionError: assert 'training' == 'failed'` (exit code 1) | **RED (通过)** |
| **BC 4** | 修改 `check_cell_already_completed`，将 `stopped` 也视为已完成 | `test_runner_stopped_recorded_as_stopped_and_permits_rerun` 中断言允许重跑失败 | `AssertionError: Stopped cell must not be considered already completed` (exit code 1) | **RED (通过)** |

详细日志已写入 `reports/V9-E1W/gemini-cv3y/r2/bad_controls_summary.json`。

---

## 5. 交付物清册与校验和

交付目录 `reports/V9-E1W/gemini-cv3y/r2/` 包含以下文件：
- `before/worker.py`（r2 修改前备份）
- `before/commands.py`（r2 修改前备份）
- `before/test_e1_wiring.py`（r2 修改前备份）
- `before/test_e1_entry.py`（r2 修改前备份）
- `run_bad_controls.py`（自动化坏对照执行脚本，打印 `__file__`）
- `bad_controls_summary.json`（坏对照测试明细）
- `data.json`（结构化指标记录）
- `REPORT.md`（本报告）
- `SHA256SUMS.txt`（校验和文件）
