# S2 集成 W12：运行中补记用时，修复账本对同一段时间的重复计算（一级 claude，2026-11-09）

## 起因
- 登记运行 P193 中，臂 B 种子 42 训练了 677 s，单格上限 1200 s，却以 `Budget exhausted: wall_time_budget` 被拒（RESEARCH_LOG `R20261109-S2-train-r3-refused`）。
- RunStore 的 `consume` 要求 `amount ≤ 单格上限 − max(已过墙钟, 已扣时长)`，文档字符串原文为「reserve before dispatch, never after performing it」。
- S2 worker 在完成时一次性扣减全部用时，同一段时间被算了两次，所以用时超过上限一半的运行必然被拒。
- 臂 C（约 970 s）和 dev（约 20,000 s，上限 36,000 s）都会因此被拒。

## 改动（只改 `src/ainerzero/v9/experiments/s2/worker.py`）
1. **`_ActiveTimeTicker`：**
   - `execute_work_cell` 在 `begin_run` 之后启动一个守护线程，每 `RESERVATION_CHUNK_SECONDS`（15 s）调用一次 `store.consume`，把上次以来的单调时钟增量补记进账本，账本因此始终只比实际用时少不到 15 s。
   - 账本拒绝时（BudgetExceeded），在 `ledger._overruns[run_id]` 里记下原因，计时器随之停止。
   - 运行已经离开工作状态时（LifecycleError），计时器直接停止。
   - 计时器在 `finally` 和 `except` 中都会停止并 join。
2. **`S2Ledger.complete_run`：**
   - 如果有超时记录，抛出 `BudgetExceeded`，这一格判为失败。
   - 否则，在会计锁内读取已扣的 `reserved_active_seconds`，只扣 `max(0, 报告用时 − 已扣)` 的余量和优化步数。
3. **会计锁：** `_accounting_lock` 让计时器线程和完成时的「先读已扣、再扣减」两步互斥执行。RunStore 的事务本身已有 RLock 保护，两个线程共用同一个连接没有问题。

**行为说明：**
- 不到 15 s 就结束的运行，记账与原来完全相同，由完成时一次扣清。
- 一格能用上几乎全部的单格预算。
- 真正超时的运行（按墙钟计，休眠时间也算在内）在补记被拒后判为失败，与原先超时的语义一致。
- 失败的运行按实际用时计入总额；原先 active_seconds 为 0 时，会按整格预算计入。

## 用例：`tests/v9/experiments/test_s2_active_ticker.py`（默认套件，8 条，真实时间，约 9 s）
- 预算 2 s 的格子跑 1.4 s：完成，账本记 1.3–1.5 s。
- **对照：** 同一格如果不补记（间隔设为 1e9），会以 `wall_time_budget` 被拒。这条用例把导致 P193 失败的规则直接写了出来。
- runner 自己调用 `complete_run`（与 train_runner、data_runner 相同）时不会重复计算，优化步数照常记入。
- 跑 2.6 s 超出 2 s 预算：判为失败，原因中含 in-flight catch-up refused，已扣时长不超过预算。
- runner 抛出异常时：计时器停止，运行判为失败，已扣时长约等于实际用时。
- 很短的格子记账与原来相同（0.75 s）。
- 失败的格子在总额检查中按实际用时计入，而不是按整格预算。
- 间隔不为正数时报错。

## 证据
- **相关现有用例：** lifecycle、train_runner、data_runner、smoke_budget、wiring、w1_wiring 共 90 条，全部通过。
- **坏对照：** 在隔离副本中运行（`mutations.txt`），5 处全部变红，还原后 8 条通过。

  | # | 变异 | 结果 |
  |---|---|---|
  | M1 | 计时器不启动 | 5 条失败 |
  | M2 | 完成时重复计算 | 2 条失败 |
  | M3 | 忽略超时记录 | 1 条失败 |
  | M4 | finally 中不停止计时器 | 1 条失败 |
  | M5 | 补记后不前移起点 | 3 条失败 |

- **默认全量：** SIG_DFL+execv，不跳过任何文件；3741 passed，7 deselected，0 failed，用时 1040 s；实盘 artifacts 的 lstat 前后差异为 0（`pytest_full_tail.txt`）。

## 影响
- 要冻结 r4，源码只有 worker.py 变化，冻结参数不变。
- 已完成的臂 A 种子 42 保留，训练代码没有改。
- 训练从臂 B 种子 42 接着跑：已完成的格子会被 `check_cell_already_completed` 跳过，驱动脚本改为跳过已完成的格子。
