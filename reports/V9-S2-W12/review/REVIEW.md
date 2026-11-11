# P195 非作者复核 · S2 集成 W12（P194）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-k8d4`（二级执行层；非 P194 作者；P194 作者为一级 `claude`）
- **被复核任务：** `ainerzero.V9.P194`（reported）
- **复核日期：** 2026-11-09
- **任务目标：** 非作者只读审查 S2 集成 W12（运行中补记用时，修复账本对同一段时间的重复计算）。深入审查账本语义与单格墙钟检查不等式；对 7 个并发/状态分支逐条对抗核验；在隔离副本中亲手复做 M1–M5 及自选 M6 坏对照；前台运行全量回归并核验实盘 artifacts 零改动。

---

## 1. 范围（Scope）

- **W12 声明修改文件**（共 2 个模块）：
  - `src/ainerzero/v9/experiments/s2/worker.py`
  - `tests/v9/experiments/test_s2_active_ticker.py`（新增）
- **SHA256 逐一校验**：
  实盘盘上 2 个文件与 `reports/V9-S2-W12/sha256.txt` 逐字 100% 完全匹配：
  - `src/ainerzero/v9/experiments/s2/worker.py`: `d259f24f9941e99dd7097662586a130e0d6a05281e3d26b2be82d9e72470d511`
  - `tests/v9/experiments/test_s2_active_ticker.py`: `699ab5ca2e549a82c469287922014e13f8599a79ec637748618f401b04409121`
- **补丁核对**：
  `git diff df2ac1c~1 df2ac1c -- src/ tests/` 与作者报告提交的补丁 `reports/V9-S2-W12/git_diff.patch` 逐文件比对，差异严格为 0。
- **工作树其他文件说明**：
  工作树中未跟踪文件均为历史任务残留报告及前置运行目录，未触碰任何受保护文件；严格未打开实盘账本 `artifacts/v9/s2/phase1/control.sqlite3`。

---

## 2. 账本语义与单格墙钟检查不等式（Ledger Semantics）

### 2.1 源码公式与不等式推导
根据 `src/ainerzero/runtime/lifecycle.py` 中 `consume`（第 795–837 行）与 `_remaining`（第 368–372 行）：
设单格总预算上限为 $T_{\max} = \text{budget}["\text{max\_wall\_seconds}"]$。
当在时刻 $t = \text{instant}$ 尝试扣减活跃秒数 $\Delta$ 时：
- 从创建至今已流逝的日历墙钟为：$\Delta t_{\text{elapsed}} = \text{instant} - \text{row}["\text{created\_at}"] \ge 0$；
- 数据库中已记录扣减的活跃秒数为：$S_{\text{reserved}} = \text{row}["\text{active\_seconds}"]$。
`_remaining["wall_seconds"]` 的计算公式为：
$$R_{\text{wall}} = \max\left(0.0, T_{\max} - \max(\Delta t_{\text{elapsed}}, S_{\text{reserved}})\right)$$
在 `_check` 中对扣减量 $\Delta$ 的准入判定条件为 $\Delta \le R_{\text{wall}}$，即：
$$\max(\Delta t_{\text{elapsed}}, S_{\text{reserved}}) + \Delta \le T_{\max}$$

### 2.2 为什么完成时一次性扣减在超过上限一半时必然被拒？
- 在 W12 之前，运行期间没有任何中间扣减，即 $S_{\text{reserved}} = 0$。
- 任务执行完毕耗时为 $\tau$ 时，调用 `complete_run(..., active_seconds=\tau)`。此时已过墙钟 $\Delta t_{\text{elapsed}} \approx \tau$。
- 代入准入不等式：
  $$\max(\tau, 0) + \tau \le T_{\max} \iff 2\tau \le T_{\max} \iff \tau \le \frac{1}{2} T_{\max}$$
- **结论**：因为 `consume` 的设计哲学是「派发前预留（reserve before dispatch）」，若在运行完成后一次性扣减，同一段运行时间 $\tau$ 既作为「已流逝墙钟 $\Delta t_{\text{elapsed}}$」被扣除了一次额度，又作为「请求扣减量 $\Delta$」被扣除了一次额度，构成了**重复计算（double counting）**！只要运行用时超过单格上限的一半（$\tau > 0.5 T_{\max}$），就会必然因 $2\tau > T_{\max}$ 被拒（如 P193 中臂 B 运行 677 s，上限 1200 s，因 $677 \times 2 = 1354 > 1200$ 被拒）。

### 2.3 补记之后，一格最多能用多少？
- 引入 `_ActiveTimeTicker` 后，每隔 $\delta = \text{RESERVATION\_CHUNK\_SECONDS} = 15.0\text{ s}$ 补记一次增量。
- 在运行中间的每一次补记时，已扣时长 $S_{\text{reserved}}$ 与已流逝时长 $\Delta t_{\text{elapsed}}$ 的差距始终小于一个分片 $\delta$。
- 到最终运行完成时，未扣减的剩余增量至多为最后一个分片 $\Delta_{\text{final}} \le \delta$。
- 完成时的准入条件变为：
  $$\tau + \Delta_{\text{final}} \le \tau + \delta \le T_{\max} \implies \tau \le T_{\max} - \delta$$
- **结论**：对于 1200 s 的格子，单格最多能用满约 **1185 s（占总额度的 98.75%）**，彻底消除了将额度压缩至一半的缺陷。

---

## 3. 逐个分支对抗核验（Adversarial Branch Verification）

复核者对 7 个并发/状态分支进行了逐行深度审查（详见 `reports/V9-S2-W12/review/branch_analysis.json`）：

1. **(a) 计时器线程与 `complete_run` 并发防重算：**
   - **代码行号**：`src/ainerzero/v9/experiments/s2/worker.py:243–252, 358–375`
   - **核验**：`complete_run` 在 `with self._accounting_lock:` 临界区内原子执行「读取已扣 `already`」和「扣减余量 `remainder = max(0, active_seconds - already)`」；`catch_up` 同样在同一会计锁内执行 `consume` 与 `self._last = now` 更新。两者严格互斥，绝不会对同一时间片重复计费。
2. **(b) runner 自行完成 vs `execute_work_cell` 兜底完成：**
   - **代码行号**：`worker.py:431–441, tests/v9/experiments/test_s2_active_ticker.py:74–81`
   - **核验**：`train_runner` / `data_runner` 自行调用 `complete_run` 后，`execute_work_cell` 检查 `run_record.state in TERMINAL_STATES` 跳过二次完成；stub runner 未自行完成时由 `execute_work_cell` 统一完成。两条路径均正确扣减余量并在 `finally` 中通过 `ticker.stop()` 安全退出。
3. **(c) runner 抛出异常时的线程退出与防泄漏：**
   - **代码行号**：`worker.py:377–380, 442–457`
   - **核验**：`execute_work_cell` 的 `except Exception` 与 `finally` 均显式调用 `ticker.stop()`，触发 `self._stop.set()` 唤醒等待并同步 `join()`。线程设为守护线程，单测 `test_runner_exception_stops_ticker_and_fails_run` 确认无残留线程。
4. **(d) `train_runner` 墙钟超限提前停止路径：**
   - **代码行号**：`src/ainerzero/v9/experiments/s2/train_runner.py:576–586`
   - **核验**：`train_runner` 在早停路径中对 `store.consume` 套有 `try...except Exception: pass`；若加总超限会被静默捕获，紧接着调用 `stop_run` 将状态置为 `stopped`。ticker 随后捕获 `LifecycleError` 安全退出。数据库保留了 ticker 记录的真实部分用时，状态与数据均未损坏。
5. **(e) 系统休眠后墙钟跳变：**
   - **代码行号**：`worker.py:343, 360, src/ainerzero/runtime/lifecycle.py:370–372`
   - **核验**：单调时钟 `monotonic()` 休眠时不虚增，保证增量非负；但 RunStore 的 `instant` 采用日历墙钟，休眠会导致 `instant - created_at` 骤增使 `remaining['wall_seconds']` 归零。下一次 `catch_up` 触发 `BudgetExceeded` 写入 `_overruns`，`complete_run` 判该格失败，准确守护日历墙钟窗口。
6. **(f) RunStore 单连接跨线程安全性：**
   - **代码行号**：`src/ainerzero/runtime/lifecycle.py:200–203, 222–231`
   - **核验**：RunStore 内部初始化 `check_same_thread=False`，所有事务通过 `threading.RLock()` 互斥执行 `BEGIN IMMEDIATE`；上层再加 `_accounting_lock` 保护业务原子性，多线程访问完全安全。
7. **(g) `_check_phase_budget_ceiling` 统计口径一致性：**
   - **代码行号**：`src/ainerzero/v9/experiments/s2/commands.py:268–281, test_s2_active_ticker.py:117–127`
   - **核验**：`_check_phase_budget_ceiling` 读取 `runs.active_seconds`。改动前未完成/失败格子的 `active_seconds` 为 0，导致回退按整格预算多计；改动后 ticker 实时持久化活跃秒数，使失败格按真实消耗统计，完成格按全量统计，总额统计既无少计亦无虚高多计。

---

## 4. 回退清零（Zero Fallback Check）

对 `worker.py` 新增代码执行模式检查：
- `except ...: pass`：仅在 `execute_work_cell` 的异常捕获块中，尝试写 `fail_run` 失败时忽略二级异常，但紧接着执行 `raise` 原异常，**绝对未吞掉或掩盖原异常**；
- `or 0` / `getattr(..., 默认值)` / `if ... is None else`：零命中；
- `chunk_seconds <= 0` 严格抛出 `ValueError`；
- 超时记录严格在 `complete_run` 中抛出 `BudgetExceeded`，实现 fail-closed。

---

## 5. 亲手隔离变异（Isolated Mutations M1–M6）

在独立目录 `/tmp/s2_w12_mutation_env` 中执行变异（复制 `src/`, `tests/`, `pyproject.toml`，并断言 `import ainerzero` 指向副本）：

亲手复现作者 5 处坏对照 M1–M5，并增加复核者自选变异 M6（共 6 处），全部精准变红失败（Exit code 1），还原后 SHA256 100% 恢复，干净环境 8 条测试全绿通过：

| # | 变异操作 | 目标文件 | 变异后测试结果 (RED) | 还原 SHA 核对 |
|---|---|---|---|:---:|
| **M1** | 计时器不启动（移除 `.start()`） | `worker.py` | 5 项失败（半数预算以上用例全挂） | 100% MATCH |
| **M2** | 完成时重复计算（不减已扣 `already`） | `worker.py` | 2 项失败 | 100% MATCH |
| **M3** | 忽略超时记录（`overrun = None`） | `worker.py` | 1 项失败（`test_real_overrun_fails_the_cell`） | 100% MATCH |
| **M4** | `finally` 中不停止计时器（`pass`） | `worker.py` | 1 项失败（线程未退出残留） | 100% MATCH |
| **M5** | 补记后不前移起点（未更新 `self._last`） | `worker.py` | 3 项失败 | 100% MATCH |
| **M6** | **自选**：禁用正数分片守卫（`if False:`） | `worker.py` | 1 项失败（非正数分片未抛 `ValueError`） | 100% MATCH |

详细变异结果记录于 `reports/V9-S2-W12/review/mutations_summary.json`。

---

## 6. 全量测试与实盘 artifacts 零改动审计

- **执行方式**：
  `SIG_DFL+execv` 前台替换执行，通过 `relay exec --every 120` 进行全程心跳与墙钟监控：
  `python3 /tmp/run_pytest_full_w12.py`（内部执行 `.venv/bin/pytest tests/ -ra -q`）。
- **实盘 `artifacts/` lstat 比对**：
  - 测试前扫描：105,457 项（`artifacts_stat_before.json`）
  - 测试后扫描：105,457 项（`artifacts_stat_after.json`）
  - 比对差异：新增 0，删除 0，修改 0（`artifacts_diff.json` 净差异严格为 0）。
- **测试结果**：
  - 3741 passed, 7 deselected in 1049.48s (0:17:29).
  - 退出码：0。

---

## 7. 逐字抽查（Spot Checks）

从 `reports/V9-S2-W12/REPORT.md` 中抽取 5 处声明与实盘/代码/日志逐字比对，全部 100% 一致：
- **SC-1**：P193 臂 B 种子 42 在 677 s 被拒事实与 RESEARCH_LOG `R20261109-S2-train-r3-refused` 逐字吻合；
- **SC-2**：`RunStore.consume` 文档字符串与剩余墙钟公式逐字吻合；
- **SC-3**：`_ActiveTimeTicker` 15 s 增量补记、`_overruns` 记录及异常/终止机制与源码逐字吻合；
- **SC-4**：`complete_run` 超时抛错与减去已扣余量逻辑与源码逐字吻合；
- **SC-5**：`tests/v9/experiments/test_s2_active_ticker.py` 8 条测试用例全部存在且通过。
详细抽查对照见 `reports/V9-S2-W12/review/spot_checks.json`。

---

## 8. 总结与建议

S2 集成 W12 对账本预算机制的修复深刻、严密，以单向追加且线程安全的方式完美解决了 RunStore 预留机制与后验完成扣减之间的语义冲突，使得长训练/评估格子能够安全用满整格预算。7 个关键并发/状态分支核验均显示设计安全闭环，隔离坏对照全部变红，默认全量测试通过且实盘 artifacts 零改动。

**建议统筹者与一级作者：`RECOMMEND_ACCEPT`（予以接收并推进至 r4 冻结与后续训练）。**
