# 任务执行报告：E1 入口接线（ainerzero.V9.P76）

- **任务 ID**: `ainerzero.V9.P76`
- **执行者 ID**: `gemini-w7m2`（Tier 2，类型：`gemini`）
- **交付状态**: 完成（零真实训练/GPU 运行，纯 CPU / dry-run 验证）
- **关联代码范围**:
  - `src/ainerzero/v9/experiments/e1/worker.py`
  - `src/ainerzero/v9/experiments/e1/commands.py`
  - `src/ainerzero/cli.py`
  - `tests/test_e1_wiring.py`
  - `tests/test_e1_entry.py`
  - `reports/V9-E1W/gemini-w7m2/`

---

## 1. 删掉的 P72 伪代码清单与新旧对照

P72 在 `worker.py` 中遗留了大量写死默认值、假检查点回退、假 read-once 状态以及自评自夸的假评估逻辑。本任务将其彻底删除并替换为四个已验收的真实 runner。

### 1.1 删掉的伪代码清单

1. **写死的评估默认指标**（`worker.py` 原 655–658 行）：
   - `mean_pos_err = float(np.mean(pos_errors_10)) if pos_errors_10 else 0.05`
   - `mean_f1 = float(np.mean(collision_f1s)) if collision_f1s else 0.95`
   - `mean_drift = float(np.mean(energy_drifts)) if energy_drifts else 0.01`
   - `mean_lat = float(np.median(latencies_ms)) if latencies_ms else 1.2`
2. **写死的 final-eval 报告与伪状态**（`worker.py` 原 710–719 行）：
   - `"final_read_once": True`
   - `"position_error_10_step": 0.048`
   - `"collision_f1": 0.96`
   - `"ballistic_energy_drift": 0.009`
3. **真实/真值自评伪逻辑**（`worker.py` 原 644 行）：
   - `metrics.evaluate_collision_f1(truth_contacts, truth_contacts)`（直接用 ground truth 与 ground truth 算 F1，永远得 1.0）。
4. **缺失检查点静默放行**（`worker.py` 原 551–553 行）：
   - `if ckpt_file.is_file(): model.load(ckpt_file)`（如果检查点不存在，不报错直接跑随机初始化的模型）。
5. **假单族 final-eval 硬编码**（`commands.py` 与 `worker.py`）：
   - 之前只支持单次全局 final，无法执行 P 族与 S 族各一次的正式日程。

### 1.2 新旧实现对照

| 维度 | P72 遗留伪实现 | P76 真实 runner 接线 |
| :--- | :--- | :--- |
| **generate-data** | 直接读取本地已有文件；空目录直接伪完成 | 真实调用 `data_runner.generate_and_export`，计数取 `spec` 正式数据计划（`TRAIN_WORLDS_PER_FAMILY=1000`，`DEV_WORLDS_PER_FAMILY=200`，`FINAL_WORLDS_PER_FAMILY=200`） |
| **train** | 伪手写循环，无占空比节流，忽略真实 `train_runner` | 真实调用 `train_runner.train_cell`，严格执行 0.25 占空比（3x 休眠节流）、真实优化器步进与真实 `arms_net.save()` 保存 |
| **eval** | 手工解析并在缺数据时回退写死常数（0.05, 0.95）；缺少检查点静默忽略 | 真实调用 `eval_runner.evaluate_cell`；臂 ②③⑥ 严格检查检查点，缺检查点在预检阶段即刻拒绝；臂 ④ 评测侧读取真 φ 构造并标 diagnostic |
| **final-eval** | 返回写死的 0.048 / 0.96 指标与假标记 | 真实调用 `eval_runner.evaluate_final_once`，经 `open_sealed_final_once` 鉴权通道读取，支持 P/S 双族各一次封存读取 |
| **台账记录** | 未记录执行 runner 身份与源码散列 | 每格创建独立 run，记录 `arm`, `family`, `seed`, `runner_name`, `runner_module_sha256` |
| **预检拦截与台账不变** | 拒绝前有时会触碰或创建账本 | 所有拒绝（缺批准行、SHA 不匹配、超预算、重复训练、缺检查点、final 第二次）均在触碰账本**之前**拦截，账本文件 SHA256 绝对不变 |

---

## 2. 生产默认 Runner 接线细节

在 `src/ainerzero/v9/experiments/e1/worker.py` 中，定义了生产默认 runner 映射，并断言与真实函数同一对象：

```python
DEFAULT_GENERATE_DATA_RUNNER = data_runner.generate_and_export
DEFAULT_TRAIN_RUNNER = train_runner.train_cell
DEFAULT_EVAL_RUNNER = eval_runner.evaluate_cell
DEFAULT_FINAL_EVAL_RUNNER = eval_runner.evaluate_final_once

DEFAULT_RUNNERS = {
    "generate-data": DEFAULT_GENERATE_DATA_RUNNER,
    "train": DEFAULT_TRAIN_RUNNER,
    "eval": DEFAULT_EVAL_RUNNER,
    "final-eval": DEFAULT_FINAL_EVAL_RUNNER,
}
```

并且 `DefaultCellRunner` 类中的方法和属性直接指向这四个真实函数：
- `runner.generate_and_export is data_runner.generate_and_export`
- `runner.train_cell is train_runner.train_cell`
- `runner.evaluate_cell is eval_runner.evaluate_cell`
- `runner.evaluate_final_once is eval_runner.evaluate_final_once`

---

## 3. 测试验证

### 3.1 单元与接线测试

执行 `tests/test_e1_wiring.py` 与 `tests/test_e1_entry.py`：

```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_wiring.py tests/test_e1_entry.py -v
```

**测试结果**: 16 passed in 4.01s (100% 通过)
- `test_default_runners_are_identical_to_real_runner_functions`: 通过
- `test_end_to_end_train_and_eval_matches_direct_eval_cell`: 通过（CLI eval 输出与直接调用 `eval_runner.evaluate_cell` 逐值相同）
- `test_refusal_paths_leave_ledger_sha_strictly_identical`: 通过（6 个拒绝路径下账本 SHA 严格相同）
- `test_fake_clock_full_schedule_rehearsal_dual_family`: 通过（51 个格全流程演练，每格截止时间独立重置，总墙钟 ≤ 115200s）
- `test_no_hardcoded_metrics_in_production_code`: 通过（源码正则 grep 零写死指标）
- `test_verify_mode` ~ `test_fake_clock_full_schedule_rehearsal`: 11 项原有入口测试全数通过

### 3.2 全仓库 E1 套件回归

```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -v
```

**测试结果**: 108 passed in 12.98s (100% 通过，零失败)

---

## 4. 坏对照（Bad Control）变异证明

在隔离副本目录 `/tmp/e1_bad_controls/` 中，分别对源码进行变异，通过单独设置 `PYTHONPATH` 导入变异源码并验证 `__file__`，证明对应测试变红（RED）：

| 坏对照 ID | 变异描述 | 导入模块 `__file__` 验证 | 测试退出码 | 变红证明 |
| :--- | :--- | :--- | :---: | :---: |
| **bc1_eval_hardcoded** | eval 改回写死指标（DefaultCellRunner 返回硬编码 0.05/0.95） | `/tmp/e1_bad_controls/bc1_eval_hardcoded/src/ainerzero/v9/experiments/e1/worker.py` | 1 | `AssertionError`（CLI eval 指标与真实 `evaluate_cell` 逐值比对失败） |
| **bc2_no_approval_check** | 去掉批准检查（跳过 `_check_approval_preflight`） | `/tmp/e1_bad_controls/bc2_no_approval_check/src/ainerzero/v9/experiments/e1/commands.py` | 1 | `AssertionError`（未拒绝非法日志，返回 completed 而非 exit 3） |
| **bc3_write_ledger_before_refusal** | 拒绝之前先写台账（在预检拒绝前修改 ledger 文件） | `/tmp/e1_bad_controls/bc3_write_ledger_before_refusal/src/ainerzero/v9/experiments/e1/commands.py` | 1 | `AssertionError: assert '877dc3cd...' == '7544dcf7...'`（拒绝前后账本 SHA 发生漂移） |
| **bc4_shared_global_deadline** | 全程共用一个截止时间（截止时间不按格重置） | `/tmp/e1_bad_controls/bc4_shared_global_deadline/src/ainerzero/v9/experiments/e1/worker.py` | 1 | `AssertionError: BudgetStop`（第 2 个格或后续格发生全局超时） |
| **bc5_allow_duplicate_training** | 允许重复训练（跳过 `check_cell_already_completed`） | `/tmp/e1_bad_controls/bc5_allow_duplicate_training/src/ainerzero/v9/experiments/e1/commands.py` | 1 | `AssertionError`（重复调用返回 completed，未被拒绝） |

---

## 5. 产出文件完整性

1. `before/`: 保留了 P72 修改前的原始文件 (`cli.py`, `commands.py`, `worker.py`)。
2. `REPORT.md`: 本报告文档。
3. `data.json`: 结构化交付元数据与测试证明。
4. `SHA256SUMS.txt`: 包含产出文件与源码文件的 SHA256 校验清单。
