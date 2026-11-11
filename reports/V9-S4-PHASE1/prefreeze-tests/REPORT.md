# S4 第一阶段冻结前补测试报告

- 任务：`ainerzero.V9.P209`（二级 执行层 gemini）
- 依据：`reports/V9-S4-PHASE1/impl-review-r2-recheck/REPORT.md` 第 3 项与建议 A、C
- 基线代码：`4c88f62`
- 文件范围（严格仅改测试，源码零改动）：
  - `tests/v9/experiments/test_s4_analysis.py`
  - `tests/v9/experiments/test_s4p1_runner_native.py`
  - `reports/V9-S4-PHASE1/prefreeze-tests/`

---

## 1. 补测内容与对应变异

### 1.1 建议 A（纯 CPU）
- **改动文件**：`tests/v9/experiments/test_s4_analysis.py`
- **新增测试**：
  - `test_future_mutation_comparison` 追加短步数断言；
  - 新增独立测试 `test_mutation_row_consumed_requires_equal_step_count`。
  - 断言 `mutation_row` 在跟踪器少返回一步（`len(b) == len(mut) - 1`，但返回的各步长度均与 `mut` 匹配）时，`consumed` 严格为假。
- **对应变异**：`an_mut_row_consumed_steps_only`（去掉 `len(b) == len(mut)` 检查）。
- **变异结果**：**killed**（8.0s 杀掉，`test_future_mutation_comparison` 失败，`1 failed, 21 passed in 7.39s`）。

### 1.2 评测预留数值测试（复核第 3 项）
- **改动文件**：`tests/v9/experiments/test_s4p1_runner_native.py`
- **新增测试**：
  - `test_make_prereg_reserve_is_post_marker_time`；
  - `test_final_path_after_a_frozen_probe` 中追加数值断言。
  - 断言 `budget.eval_reserve_s == ceil(1.5 × scale × post_marker_seconds)`，其中 `scale = sum(SIZES["final"]) / sum(SIZES["probe"]) == 4`；
  - 断言预留来源是 `post_marker_seconds`（覆盖世界生成、评测、写文件与校验），而非仅评测本身的 `eval_seconds`。
- **对应变异**：`mp_reserve_eval_only`（预留改按 `eval_seconds` 计算）。
- **变异结果**：**killed**（61.9s 杀掉，`test_final_path_after_a_frozen_probe` 失败，`1 failed, 14 passed in 61.65s`）。

### 1.3 超时预估拒绝与边界测试（复核第 3 项）
- **改动文件**：`tests/v9/experiments/test_s4p1_runner_native.py`
- **新增测试**：`test_make_prereg_refuses_when_training_plus_reserve_exceeds_four_hours`。
  - 构造 `1.2 × pre_eval_seconds <= 14400` 但 `1.2 × pre + 预留 > 14400` 的场景（如 `pre=10000`, `post=500`, 预留=3000, 合计 15000s），断言非零退出、报错含「预计超出硬上限」，且预登记文件不落地；
  - 边界测试：合计恰好为 14400s（如 `pre=10000`, `post=400`, 预留=2400, 合计 14400s），断言成功通过（源码为严格大于号 `>`）。
- **对应变异**：`mp_budget_ignores_reserve`（超时判断忽略预留）。
- **变异结果**：**killed**（90.3s 杀掉，`test_make_prereg_refuses_when_training_plus_reserve_exceeds_four_hours` 失败，`1 failed, 16 passed in 90.07s`）。

### 1.4 建议 C（计时起点测试）
- **改动文件**：`tests/v9/experiments/test_s4p1_runner_native.py`
- **新增测试**：`test_post_marker_timing_starts_before_eval_generation`。
  - 副本中在 `world.py` 对 `generate_episode` 在评测命名空间包装延时（每个世界 1 秒，评测共 3 个世界）；
  - 断言 `post_marker_seconds - eval_seconds - check_seconds >= 2.9`，确保评测世界的生成耗时计入 `post_marker_seconds`。
- **对应变异**：`ru_post_marker_after_generation`（计时起点挪到生成评测世界之后）。
- **变异结果**：**killed**（107.6s 杀掉，`test_post_marker_timing_starts_before_eval_generation` 失败，`1 failed, 17 passed in 107.43s`）。

### 1.5 自定义变异（自定义第 5 个变异）
- **改动文件**：`reports/V9-S4-PHASE1/make_prereg.py`
- **对应变异**：`mp_reserve_no_margin`（`make_prereg.py` 去除 1.5 倍余量系数，改用 1.0 倍）。
- **变异结果**：**killed**（59.2s 杀掉，`test_final_path_after_a_frozen_probe` 失败，`1 failed, 14 passed in 58.98s`）。

---

## 2. 测试计数对比

全量测试均在隔离环境中真实执行并通过：

| 范围 | 补测前 | 补测后 | 说明 | 运行耗时 |
|---|---|---|---|---|
| CPU 默认入口 | 76 passed | **77 passed** | `test_s4_analysis.py` (+1) | 16.83s |
| MLX（`test_s4_learned_mlx.py`） | 40 passed | **40 passed** | 未改动 | 4.39s |
| 运行器（`test_s4p1_runner_native.py`） | 29 passed | **32 passed** | 新增 3 项测试 (+3) | 172.98s (0:02:52) |
| **合计** | **145 passed** | **149 passed** | 全部通过 | — |

---

## 3. 坏对照变异结果

变异运行脚本：`reports/V9-S4-PHASE1/prefreeze-tests/mut_prefreeze.py`。
执行环境：在共享锁 `artifacts/locks/m0-worker.lock` 下由 `hold_lock.py` 调度执行；
原始日志见 `mut_results.log`，结构化结果见 `mut_results.json`。

| 变异名 | 被改文件 | 原文 | 突变文本 | 状态 | 耗时 | 捕获测试与特征 |
|---|---|---|---|---|---|---|
| `an_mut_row_consumed_steps_only` | `src/.../analysis.py` | `"consumed": len(b) == len(mut) and all(` | `"consumed": all(` | **killed** | 8.0s | `test_future_mutation_comparison` 报 `assert not True` |
| `mp_reserve_eval_only` | `reports/.../make_prereg.py` | `eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])` | `eval_reserve = math.ceil(1.5 * scale * pr["eval_seconds"])` | **killed** | 61.9s | `test_final_path_after_a_frozen_probe` 预留数值不符 |
| `mp_budget_ignores_reserve` | `reports/.../make_prereg.py` | `if 1.2 * train_s + eval_reserve > HARD_LIMIT_S:` | `if 1.2 * train_s > HARD_LIMIT_S:` | **killed** | 90.3s | `test_make_prereg_refuses_when_training_plus_reserve_exceeds_four_hours` 未能拒绝超时 |
| `ru_post_marker_after_generation` | `reports/.../run_s4p1.py` | `t_post` 在 `eval_eps` 生成前记录 | `t_post` 挪至 `eval_eps` 生成后记录 | **killed** | 107.6s | `test_post_marker_timing_starts_before_eval_generation` `diff` 远小于 2.9s |
| `mp_reserve_no_margin` | `reports/.../make_prereg.py` | `1.5 * scale` | `1.0 * scale` | **killed** | 59.2s | `test_final_path_after_a_frozen_probe` 预留缺少 1.5 倍余量 |

**总结**：点名要杀的 4 个变异及 1 个自定义变异（共 5 个）在隔离副本中真实变红并被 100% 杀掉（5 / 5 killed），测试计数如实更新（145 -> 149 passed）。
