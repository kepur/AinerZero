# E1-E2 入口第二半交付报告：e1-phase2 CLI + 中央台账 + 假时钟全程演练（零真实运行）

- **任务 ID**：`ainerzero.V9.P72`
- **执行 Agent**：`gemini-t8m4`（Tier 2，kind: gemini）
- **交付日期**：2026-10-29
- **工作性质**：CLI 入口（commands/worker/cli）、中央台账管理、预检只读防御、假时钟全程日程演练、对抗变异坏对照
- **权限与环境约束**：纯 CPU / NumPy / Python 标准库；零真实运行、零训练、零 GPU、零正式数据生成；不改动 S1 台账与产物。

---

## 1. 交付文件清单

1. `src/ainerzero/v9/experiments/e1/commands.py`:
   - 实现 `e1_phase2_command(args)`，支持五种显式模式：`verify`、`generate-data`、`train`、`eval`、`final-eval`。
   - 预检只读判定：所有计算模式开工前必须依次通过预登记校验、统筹批准行检索（`prereg.find_approval` 恰有一行有效）、领域参数验证（训练臂仅限 2, 3, 6；种子仅限 42, 43, 44；族仅限 P, S）、台账只读防重复检查、预算天花板算术。任一检查未通过，**在写任何台账或文件之前直接拒绝**，台账文件字节完全不变。
   - 共享锁守护：预检通过后获取 `worker_lock(spec.REGISTERED_HOST_LOCK)`（`m0-worker.lock`，基于 `fcntl.flock`）。
2. `src/ainerzero/v9/experiments/e1/worker.py`:
   - 封装独立中央台账 `E1Ledger`（绑定 `spec.REGISTERED_HOST_LEDGER` 的 `RunStore`），实现模式 run 的创建、状态流转（`created` -> `initializing` -> 工作状态 -> `completed`/`stopped`）与预工作预算扣除（`reserve`）。
   - `ledger_read_snapshot`：通过 SQLite 只读备份在临时副本上查询，避免 `RunStore` 打开时修改生产数据库文件哈希。
   - 每格独立截止时间与预算重置：每格严格根据该格专属预算重置 `cell_deadline = cell_start_time + cell_wall_budget`。
   - 电源策略：遵循 `RESEARCH_LOG R20261028-battery-policy`，通过 `get_power_info()` 记录电源来源与开盖状态，不因电池供电而拦截。
   - 数据生成参数拼装 `build_generate_data_argv`。
3. `src/ainerzero/cli.py`:
   - 增加子命令 `e1-phase2` 及其完整参数定义与分发逻辑。改动前备份保留在 `reports/V9-E1E2/gemini-t8m4/before/cli.py`。
4. `src/ainerzero/v9/experiments/e1/__init__.py`:
   - 统一导出 `commands` 与 `worker`。
5. `tests/test_e1_entry.py`:
   - 9 项独立单元测试，覆盖只读核验、预检拒绝与台账 SHA 零变动、参数白名单、防重复训练、final-eval 仅读一次、数据生成命令拼装、预算耗尽拦截、电池策略记录、以及 50 格假时钟全程演练。

---

## 2. E1 Phase 2 与 S1 Phase 1 入口架构对照表

| 对比维度 | S1 Phase 1 入口 (`s1-phase1`) | E1 Phase 2 入口 (`e1-phase2`) |
|---|---|---|
| **中央台账位置** | `artifacts/v9/s1/phase1/control.sqlite3` | `artifacts/v9/e1/phase2/control.sqlite3`（完全物理隔离，不共用） |
| **共享互斥锁** | `artifacts/locks/m0-worker.lock` | `artifacts/locks/m0-worker.lock`（复用主机共享互斥锁） |
| **批准行语法** | `APPROVED s1-phase1 prereg document_sha256=<64hex>` | `APPROVED e1-phase2 prereg document_sha256=<64hex>` |
| **批准日志专区** | `## R20261021-P1-stageA-budget` | `## R20261029-E1-approval` |
| **臂定义与参数量** | 4 臂，可训练臂 arm2..arm4（0.1M~2M 参数） | 7 臂，可训练臂 ②③⑥ 严格登记为 `6150` 参数；④ 为真参数诊断臂 |
| **训练格数** | 3 可训练臂 × 3 种子 = 9 格 | 3 可训练臂（②③⑥）× 2 族（P, S）× 3 种子（42, 43, 44）= 18 格 |
| **评测格数** | 4 臂 × 3 种子 = 12 格 | 18 训练评测格 + 12 非训练评测格 = 30 dev 评测格 |
| **每格计算预算** | 训练每格 ≤ 1200 s，占空比 0.25（墙钟 4800 s） | 训练每格 ≤ 1200 s，占空比 0.25（墙钟 4800 s）；dev 评测 ≤ 600 s / 300 s |
| **总墙钟上限** | 阶段提议上限 ≤ 4 h（单次冒烟前） | 阶段总上限提议 ≤ 32 h（115200 s） |
| **预检拒绝时机** | 在写任何台账前通过只读快照决断 | 在写任何台账前通过只读快照决断（台账文件 SHA 前后不变） |
| **最终分区控制** | final 分区封存，只读一次 | `final` 分区封存，`.read_once` 标记与台账双重防重，永久只读一次 |
| **电源策略** | 历史版本要求接电 | 按 `R20261028-battery-policy` 取消电池拦截，仅记录电源来源与开盖 |

---

## 3. 假时钟全程日程演练（50 格）

在 `tests/test_e1_entry.py::test_fake_clock_full_schedule_rehearsal` 中，使用 `FakeClock` 完整串行执行预登记规定的 50 格日程：
1. **数据生成格（1 格）**：`generate-data`，推进时钟 50.0 s，成功登记与结算；
2. **训练格（18 格）**：遍历 `family in ("P", "S")`、`arm in (2, 3, 6)`、`seed in (42, 43, 44)`，每格独立重置截止时间，每格推进时钟 30.0 s，18 格全部成功完成；
3. **Dev 评测格（30 格）**：
   - 18 格可训练臂评测（2, 3, 6 × P, S × 42, 43, 44）；
   - 12 格非训练臂评测（1, 4, 5, 7 × 组合）；
   - 30 格全部完成；
4. **Final 评测格（1 格）**：`final-eval`，产出 read-once 标记并完成结算；
5. **断言与验证**：
   - 全程总耗时严格小于总上限 `phase_total_wall_ceiling_seconds`（115200 s）；
   - 再次调用任一已完成训练格：严格拒绝（`duplicate_execution`，exit 1）；
   - 再次调用 `final-eval`：严格拒绝（`final_eval_already_read_once`，exit 1）。

---

## 4. 单元测试与回归证据

- **本入口单测**：
  `python3 -m pytest tests/test_e1_entry.py -v`
  **9 passed in 2.23s**
- **E1 整体全量测试**：
  `python3 -m pytest tests/test_e1*.py -v`
  **80 passed in 5.05s**（涵盖 net arms 9 项、nonnet arms 11 项、export 8 项、metrics 16 项、prereg 14 项、prior 13 项、entry 9 项）。

---

## 5. 五项对抗变异坏对照（Adversarial Mutants）

所有变异体均在 `/tmp/e1_e2_mutants/` 隔离目录中构建，并通过 `PYTHONPATH` 指向隔离副本执行目标单测，全部严格变红（FAILED as expected）：

| 变异体编号 | 变异内容与部位 | 载入源码路径验证 | 目标测试 | 结果与错误类型 |
|---|---|---|---|---|
| **Mutant 1** | 去掉批准检查（`_check_approval_preflight` 旁路返回 True） | `/tmp/e1_e2_mutants/mutant_1/src/.../commands.py` | `tests/test_e1_entry.py::test_verify_mode` | **RED** (`assert 0 == 3 (EXIT_REFUSED_APPROVAL)`) |
| **Mutant 2** | 预算改成整个进程共用一个截止时间、不按格重置 | `/tmp/e1_e2_mutants/mutant_2/src/.../commands.py` | `tests/test_e1_entry.py::test_fake_clock_full_schedule_rehearsal` | **RED** (`assert 2 == 0 (EXIT_REFUSED_RESOURCE on subsequent cell)`) |
| **Mutant 3** | 允许重复训练（旁路 `check_cell_already_completed`） | `/tmp/e1_e2_mutants/mutant_3/src/.../commands.py` | `tests/test_e1_entry.py::test_duplicate_training_rejected` | **RED** (`assert 0 == 1 (EXIT_FAILED)`) |
| **Mutant 4** | final-eval 不标记只读一次（旁路 `.read_once` 文件写入） | `/tmp/e1_e2_mutants/mutant_4/src/.../commands.py` | `tests/test_e1_entry.py::test_final_eval_read_once` | **RED** (`AssertionError: .read_once file missing`) |
| **Mutant 5** | 拒绝发生在写台账之后（在 preflight 检查前提前创建/修改台账 run） | `/tmp/e1_e2_mutants/mutant_5/src/.../commands.py` | `tests/test_e1_entry.py::test_preflight_refusal_leaves_ledger_sha_unchanged` | **RED** (`AssertionError: ledger SHA256 was modified on refusal`) |

---

## 6. 零真实运行承诺

- **零正式训练**：未启动任何真实 MLX 优化器更新；
- **零真实数据生成**：未调用 Blender 或 AWZ 物理生成进程；
- **零 GPU**：全部测试基于纯 CPU / NumPy / SQLite 假后端运行；
- **隔离性保障**：未修改 S1 的任何代码、台账或检查点。
