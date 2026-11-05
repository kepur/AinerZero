# AinerZero E1 Phase 2 冻结代码卡报告 (ainerzero.V9.P96 · r2 定稿)

**执行者**：gemini-v9p2 (Level 2 执行 agent · gemini)  
**日期**：2026-11-02  
**轮次**：r2 (修复 r1 假绿打回并彻底解决生产与测试自洽)  
**状态**：完成 (Completed · 零运行纯 CPU 契约代码、单测与隔离变异验证)  
**关联任务**：`ainerzero.V9.P96` (前置 `ainerzero.V9.P95`)  

---

## 一、执行摘要与打回必修项解决 (r1 → r2)

### 1. 上次被打回原因回顾 (r1 假绿)
在 r1 轮次中，`tests/conftest.py` 注入了针对 `prereg.build_draft` 的运行时 monkey-patch，强行将单格墙钟上限由 `1200` 改为 `600`，以迎合旧的硬编码等式 `train_total_wall == count * cell_wall`。导致在脱离 conftest 的生产环境（如 `.venv/bin/python -I`）下 `prereg.validate(prereg.build_draft())` 抛出 `SpecValidationError`。报告中的 206 passed 实为**假绿**。

### 2. 本轮 (r2) 必修解决项落实
1. **采纳 #745 架构裁定 (Option A) 改造 `prereg.py validate()` 算术检验**：
   - 检验公式更新为：
     - 单格占空比算术：`|train_cell_wall_max_seconds * training_duty_cycle - train_cell_compute_max_seconds| <= 1e-3`
     - 训练墙钟总上限与单格护栏区间关系：`train_cell_wall_max_seconds <= train_total_wall_max_seconds <= train_cells_count * train_cell_wall_max_seconds`
     - 阶段总预算组件求和不超过总上限：`component_sum <= phase_total_wall_ceiling_seconds`
   - `spec.py` 中的定稿数值（`1200 / 10800 / 18000`）完全保持不变，未作任何降格或调整。
2. **`tests/conftest.py` 彻底清理并字节还原到 HEAD**：
   - 彻底删除一切 E1 相关的 monkey patch 代码。
   - 恢复后 SHA-256 为 `95f1490c94d0909e39e8a5cabf37b474cf3e8a1593c677f28e97d9efc5973d3f`，与 HEAD 完全一致。
3. **新增子进程无补丁测试与坏对照**：
   - 在 `tests/test_e1_prereg.py` 中新增 `test_isolated_subprocess_draft_and_freeze`，在 `python -I` 隔离子进程中直接验证 `validate(build_draft())` 与 `freeze()` 成功通过。
   - 子进程内严格测试三条坏对照：
     - `total > count * wall` 被拒（抛出 `SpecValidationError` 包含 `out of bounds`）
     - `wall > total` 被拒（抛出 `SpecValidationError` 包含 `out of bounds`）
     - `compute != wall * duty` 被拒（抛出 `SpecValidationError` 包含 `does not equal`）
   - 测试内包含进程式防御断言：若任何外部环境篡改 `build_draft` 的 `train_cell_wall_max_seconds`，测试即刻变红崩溃。
4. **变异表扩充至 7 条坏对照，全部变红 (RED)**：
   - 新增 MUT-6（新规则改回旧等式 -> 捕获转红）。
   - 新增 MUT-7（conftest 重新注入改写补丁 -> 进程式与子进程测试捕获转红）。
5. **真实全量测试计数**：
   - 在无任何补丁的干净 conftest 环境下，`tests/test_e1*.py` 207 个测试全部一次性通过（207 passed, 0 failed）。

---

## 二、文件改动与哈希前后核验

### 1. 修改文件清单与 SHA-256 前后对比
| 文件路径 | 修改前 SHA-256 | 修改后 SHA-256 | 修改说明 |
| :--- | :--- | :--- | :--- |
| `src/ainerzero/v9/experiments/e1/spec.py` | `0507204481fa7ff0...` | `415a449cfb2dced018046d8b1b621bc0b35092cfbdefb430b3973b326d4ba63b` | 指向 r4 定稿、64000 步上限、5 h 预算常数及求和等式 |
| `src/ainerzero/v9/experiments/e1/train_runner.py` | `bb57b2185a539fe5...` | `906929f9f8b789e7a9d6cee4f0e373560a70b87028536d894052855bb3922309` | 训练前验证集为空/样本不足2即抛 ValueError，阻断写盘 |
| `src/ainerzero/v9/experiments/e1/worker.py` | `a3f019087ebccfdc...` | `c7aa252398f12d89bb8e08192ac136aad37e23129ba9128219525fb0f7ad6156` | RunStore 预算由 spec 动态派生，消除硬编码魔数 |
| `src/ainerzero/v9/experiments/e1/prereg.py` | `08e9763a5bccd2c7...` | `f2698be9ff690a953687fabdd4e0b334ee832eca2ad79800aa5444e79af427e0` | 按 #745 Option A 更新 validate() 预算区间与占空比约束 |
| `tests/conftest.py` | `626d7b34f4748e79...` (r1污染) | `95f1490c94d0909e39e8a5cabf37b474cf3e8a1593c677f28e97d9efc5973d3f` | 还原到 HEAD，彻底清除猴子补丁 |
| `tests/test_e1_prereg.py` | `4bd0aa80210214c7...` | `d534f2d51e5beb10e5dcb30c69abf45f5a6b703b9f4d4b91be6e0a61e57a5820` | 新增 r4 常数核验、预算坏对照与无补丁子进程深度测试 |
| `tests/test_e1_train_runner.py` | `f50a8b9e6ffcfd1b...` | `49b3c6fb811fa2fcb13615ac8f698e6aa3a006a591c9575edcc8b1c86408863b` | 新增空 episode/空 window/无 checkpoint 抛错检验 |
| `tests/test_e1_entry.py` | `0b77b75225aa2e9d...` | `eb68893cfde07b65934facf720ba98a18a21d248c2728daabd1e8dc40dceeb43` | 适配多样本训练与 5h 演练预算 |
| `tests/test_e1_wiring.py` | `6b976f62b1bdf626...` | `ba89191c274c9d6f780b76a56e34f993a4868edbccfa2f26499e87d8075c5098` | 新增 RunStore 派生预算验证 |
| `reports/V9-E1FREEZE/run_mutations.py` | (新增/重构) | `3e6619803a6b4607645b63f7444468f1c88233aba09d8da0475491bd8c7d01db` | 7 组坏对照隔离沙箱变异测试脚本 |

### 2. 受保护锚点文件状态（零运行铁律核验）
| 关键锚点 | 预期 SHA-256 | 实际读取 SHA-256 | 状态 |
| :--- | :--- | :--- | :--- |
| `artifacts/v9/teachers/benchmark/runs.db` | `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01` | `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01` | 未修改 (mtime=1793225768.2078843) |
| `artifacts/locks/m0-worker.lock` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | 未修改 (mtime=1790110663.3796358) |
| `reports/V9-P48/PREREG_DRAFT_r4_candidate.md` | `ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e` | `ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e` | 未修改 (mtime=1793350476.8243046) |
| `reports/V9-P48/PREREG_DRAFT.md` | `372e724bd6b028da9dde76d7f1fb52aa6e1497926b5a081a64032950662f2872` | `372e724bd6b028da9dde76d7f1fb52aa6e1497926b5a081a64032950662f2872` | 未修改 (mtime=1793218333.247729) |
| `artifacts/v9/e1/` 目录 | 保持空（零文件） | 保持空（零文件） | 确认未产生任何数据或检查点 |

### 3. 旧 Draft 摘要钉子清零核查
全仓（`src/` 与 `tests/`）检索旧 hash `372e724b`：
```bash
grep -rn "372e724b" src/ tests/
```
**结果**：0 命中（返回码 1，无任何输出），确认代码及单测中旧摘要钉子已彻底清零。

---

## 三、RunStore 预算自洽性与源码审计分析

针对 `worker.py` 中 RunStore 预算是否与 64,000 步及 18 个训练 cell 自洽，审计了 `src/ainerzero/runtime/lifecycle.py`：

### 1. 源码行号与统计口径
- **实验级全局累计机制**：
  - `src/ainerzero/runtime/lifecycle.py` 第 409–418 行：
    ```python
    runs = db.execute("SELECT * FROM runs WHERE experiment_id=?", (experiment_id,)).fetchall()
    totals = {
        key: sum(r[key] for r in runs)
        for key in (
            "environment_steps",
            "optimizer_steps",
            "model_transitions",
            "active_seconds",
        )
    }
    ```
    明确表明：`optimizer_steps` 在实验层级（`ExperimentRecord`）是**全实验所有 run 累加求和**。
  - 第 429–432 行：
    ```python
    remaining = {
        key: max(0, budget[f"max_{key}"] - totals[key])
        for key in ("environment_steps", "optimizer_steps", "model_transitions")
    }
    ```
  - 第 578–586 行（`create_run` 校验）：
    ```python
    for key in ("environment_steps", "optimizer_steps", "model_transitions", "wall_seconds"):
        if experiment.remaining[key] <= 0:
            rejection = BudgetExceeded(f"experiment_{key}_budget", experiment.remaining)
            break
    ```
- **原魔数 100,000 的致命隐患**：
  若实验全局 `max_optimizer_steps = 100_000`，18 个训练 cell 中每个最多执行 64,000 步。第 1 个 cell 跑满后剩余仅 36,000 步；第 2 个 cell 在执行至第 36,000 步（或第 3 个 cell 尝试 `create_run`）时，`experiment.remaining["optimizer_steps"]` 必然归零，抛出 `BudgetExceeded` 异常强行中断训练。
- **动态派生公式落实**：
  在 `worker.py` 第 186–194 行：
  ```python
  train_cells = int(spec.BUDGET_CAPS["train_cells_count"]) # 18
  max_steps_per_cell = int(spec.DEFAULT_TRAIN_STEPS)        # 64,000
  # 实验总上限：18 * 64,000 * 1.2 = 1,382,400 steps (含 20% 安全余量)
  derived_experiment_optimizer_steps = int(train_cells * max_steps_per_cell * 1.2)
  # 单 run 上限：64,000 * 1.2 = 76,800 steps (含 20% 安全余量)
  derived_run_optimizer_steps = int(max_steps_per_cell * 1.2)
  ```
  留 20% 余量的原因：为可能的校准步骤或计数对齐开销提供弹性，同时严格锁死步数上限，杜绝失控无限跑。

### 2. `max_daily_active_seconds` 与 `max_model_runs` 审计
- **跨自然日行为**：
  `src/ainerzero/runtime/lifecycle.py` 第 814–823 行：
  ```python
  date = datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"])).date().isoformat()
  self._day(db, date, budget["max_daily_active_seconds"])
  for date, amount in self._allocations(instant, active_seconds, budget["timezone"]):
      self._day(db, date, budget["max_daily_active_seconds"])
      db.execute(
          "UPDATE daily_budget SET reserved_seconds=reserved_seconds+? WHERE local_date=?",
          (amount, date),
      )
  ```
  配额按当地时区自然日（`local_date`）记录与重置，每天享有独立的 `max_daily_active_seconds`（设为总上限 18,000 s = 5 h）。跨自然日不会累计既往耗时，不会被错误切断。
- **`max_model_runs = 100`**：
  `lifecycle.py` 第 426 行统计 `count = sum(r["role"] == "model" for r in runs)`。E1 共包含 18 个训练 cell 与 8 个非训练 cell（共 26 cell），100 充足容纳全部运行及测试重试，安全合理。

---

## 四、隔离副本变异测试 (Bad-Control Mutations)

在隔离临时沙箱（`tempfile.mkdtemp`）中复制 `src/` 与 `tests/`，通过 `PYTHONPATH` 隔离运行。每一项变异均在对应单测上验证变红（RED），恢复后 SHA 100% 吻合：

| 变异 ID | 变异名称 | 注入文件 | 目标测试节点 | 退出码 | 变异状态 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MUT-1** | `spec_sha_mutated_1_char` | `spec.py` | `test_e1_prereg.py::test_spec_constants` | 1 | **RED (pass)** |
| **MUT-2** | `default_train_steps_reverted_to_32000` | `spec.py` | `test_e1_prereg.py::test_spec_constants` | 1 | **RED (pass)** |
| **MUT-3** | `budget_caps_sum_equation_broken` | `spec.py` | `test_e1_prereg.py::test_spec_constants` | 1 | **RED (pass)** |
| **MUT-4** | `train_runner_empty_validation_guard_disabled` | `train_runner.py` | `test_e1_train_runner.py::test_compute_validation_loss_empty_windows_raises_value_error` | 1 | **RED (pass)** |
| **MUT-5** | `worker_runstore_optimizer_steps_reverted_to_100k` | `worker.py` | `test_e1_wiring.py::test_runstore_budget_derived_from_spec` | 1 | **RED (pass)** |
| **MUT-6** | `prereg_reverted_to_legacy_exact_equality` | `prereg.py` | `test_e1_prereg.py::test_isolated_subprocess_draft_and_freeze` | 1 | **RED (pass)** |
| **MUT-7** | `conftest_monkey_patch_re_injected` | `conftest.py` | `test_e1_prereg.py::test_isolated_subprocess_draft_and_freeze` | 1 | **RED (pass)** |

所有 7 组变异全部成功转红（RED）。详细变异输出记录见 `reports/V9-E1FREEZE/mutation_results.json`。

---

## 五、完整测试套件执行证据

运行命令：
```bash
.venv/bin/pytest tests/test_e1*.py -v
```
运行环境：纯 CPU 环境，未加载 MLX 真实训练，`tests/conftest.py` 纯净（SHA-256 `95f1490c...`）。

输出尾部摘要：
```
tests/test_e1_wiring.py::test_default_runners_are_identical_to_real_runner_functions PASSED [ 96%]
tests/test_e1_wiring.py::test_end_to_end_train_and_eval_matches_direct_eval_cell PASSED [ 96%]
tests/test_e1_wiring.py::test_refusal_paths_leave_ledger_sha_strictly_identical PASSED [ 97%]
tests/test_e1_wiring.py::test_fake_clock_full_schedule_rehearsal_dual_family PASSED [ 97%]
tests/test_e1_wiring.py::test_reserve_amount_equals_cell_wall_budget PASSED [ 98%]
tests/test_e1_wiring.py::test_runner_stopped_recorded_as_stopped_and_permits_rerun PASSED [ 98%]
tests/test_e1_wiring.py::test_runner_exception_recorded_as_failed PASSED [ 99%]
tests/test_e1_wiring.py::test_no_hardcoded_metrics_in_production_code PASSED [ 99%]
tests/test_e1_wiring.py::test_runstore_budget_derived_from_spec PASSED   [100%]

============================= 207 passed in 28.60s =============================
```

子进程无补丁测试（`test_isolated_subprocess_draft_and_freeze`）独立运行命令验证：
```bash
.venv/bin/pytest tests/test_e1_prereg.py -k "test_isolated_subprocess_draft_and_freeze" -v
```
输出：
```
tests/test_e1_prereg.py::test_isolated_subprocess_draft_and_freeze PASSED [100%]
============================== 1 passed in 0.58s ===============================
```

---

## 六、明确没有做的事 (红线声明)

1. **没有启动真实 GPU 或 MLX 训练**：全过程处于 CPU 验证模式，未加载真实神经网络权重的 MLX 训练。
2. **没有触碰锁或台账文件**：未获取或更改 `artifacts/locks/m0-worker.lock`，未触碰或写入 `artifacts/v9/teachers/benchmark/runs.db`。
3. **没有在 `artifacts/v9/e1/` 下生成任何数据或模型文件**：`artifacts/v9/e1/` 维持空目录状态。
4. **没有修改预登记正文文件**：`PREREG_DRAFT.md` 与 `PREREG_DRAFT_r4_candidate.md` 保持完全只读，未更改任何字节。
5. **没有修改 `prereg.py` 的批准行与冻结核心逻辑**：仅按 #745 Option A 修订了 `validate()` 中的预算区间等式，批准行扫描器与冻结哈希逻辑完全保持不变。
6. **没有写入 `RESEARCH_LOG.md`**：未添加任何新的实验登记或研究记录。
7. **没有提交或推送 git 分支**：未执行 `git commit` 或 `git push`。
8. **没有覆盖历史 r1 报告**：r1 报告完整归档至 `reports/V9-E1FREEZE/r1-archive/`。
