自证：本复核由 `composer-a7k2` 执行；被验卡 ainerzero.V9.P126 作者为 `gemini-w4x2`，本会话未以其他 ID 实现或改写过 P126，不存在自审冲突。

# ainerzero.V9.P127 非作者复核报告（验 P126）

角色：executor（L2 verify）；负责人：composer-a7k2；时间：2026-11-06
任务状态：reported；实验状态：未执行（纯 CPU 复核，无训练）
任务依据：ainerzero.V9.P127 v0；验 ainerzero.V9.P126；只改 `reports/V9-S2-P126/review/`
结论：**RECOMMEND_ACCEPT_SCOPED**

## 范围

- 卡面范围：`s2/commands.py`、`s2/worker.py`、`cli.py`、`tests/.../test_s2_lifecycle.py`、`reports/V9-S2-P126/`。
- `commands.py` / `worker.py` / `test_s2_lifecycle.py` 为相对 HEAD 的新增未跟踪文件；`cli.py` 相对 HEAD **+56 / -0**，与 `cli.diff` 逐字节一致；`e1-phase2` 分发块与 HEAD **逐字节相同**。
- 已跟踪 `src/` 除 `cli.py` 外与 HEAD **151 文件逐字节一致**；`e1/*`、`runtime/lifecycle.py` 无 diff。
- 工作树另有 `tests/conftest.py` 等其他卡脏文件（diff 不含 s2），**不计入 P126 交付**；未移动/改写它们。

## 与 E1 逐项对照

| 口径 | S2 | E1 | 判定 |
|---|---|---|---|
| 总上限累计 | `commands._check_phase_budget_ceiling` L246–275：对 `LEDGER_EXPERIMENT_IDS` 累加 `active_seconds`，缺则回退 `cell_wall_budget_seconds`；`consumed + new > ceiling` 拒绝 | `e1/commands.py` L142–170：同算法，ID 来自 `spec.LEDGER_EXPERIMENT_IDS` | **相同**（S2 跨 r0/r1/r2 合理，卡面要求） |
| 日历/计算分离 | `worker.get_experiment_manifest` L50–72：`experiment_budget.max_wall_seconds=日历 72h`；`open_run` L170 运行级 `max_wall_seconds=cell`；10h 由 phase ceiling 聚合 | `e1/worker.py` L205–226：同 Plan A 注释与结构 | **相同** |
| 防重复 | `worker.check_cell_already_completed` L91–121：(mode, arm, seed)；`generate-data` 整模去重 | `e1/worker.py` L149–181：(mode, arm, family, seed) | **同构**；S2 无 family 合理 |
| 批准扫描 | `commands.scan_approval_log` L73–189：节内唯一行；忽略 fence/引用/缩进 | `e1/prereg.py` L489–573：同跳过规则；缺文件/歧义 **抛异常** | **规则相同**；S2 返回 `found:False` 字典适配本卡「无批准拒非 verify」——合理 |
| 实盘预检读账本 | `ledger_read_snapshot` L77–88：**直接** `RunStore(path)` | `e1/worker.py` L109–146：复制到临时 sqlite 再读 | **不同**；见 scoped 范围 |

`cli.py`：仅追加 `s2-phase1` 注册与分发；e1 分发未改。

## 零实盘写入

- 路径均可经 `--ledger/--lock-file/--research-log/--output-root` 换成临时路径。
- 独立子进程：临时路径 `s2-phase1 --mode verify` → exit 0、未建账本；无批准 `train` → exit 3 / `stage=approval`、仍无账本。
- 生命周期测试与本复核变异均在 `tmp_path`/隔离副本；未打开生产 `artifacts/v9/s2/phase1/control.sqlite3`（本机该文件亦不存在）。
- 全量前后 `artifacts/` 条目数 80929→80929；`m0-worker.lock` mtime/ino 不变。

## 测试真伪

- `test_s2_lifecycle.py` 直接调用 `commands.s2_phase1_command`、`commands.scan_approval_log`、`worker.S2Ledger` / `open_run`；假时钟/假 runner 注入，断言 exit/stage/边界数值，**非**常数比常数或测试内重写业务。
- 本机复跑：6 passed / 1.36s。

## 自做变异（作者 P126-M1..M4 之外，隔离副本，import 断言落副本，逐处还原 SHA）

| ID | 变异 | 结果 |
|---|---|---|
| R127-X1 | 去掉 fence 跳过（非 M4 引用块） | **KILLED**（test_e） |
| R127-X2 | ceiling 判断 `>`→`>=` | **KILLED**（test_c 边界） |
| R127-X3 | 防重复忽略 arm（非 M3 忽略 seed） | **KILLED**（suite + 同种子异臂 oracle） |

无存活项。证据：`mutation_results.json`。

## 纯 CPU

- `-I` 导入 s2.commands/worker 后 `mlx` / `mlx.core` **不在** `sys.modules`。
- 前台 SIG_DFL+`os.execv` 全量：`3516 passed, 6 deselected in 261.93s`，0 failed。日志：`pytest_full_p127.log`。

## 非阻断备注

1. 作者 `metrics.json` 谱系列出 r3，源码 `LEDGER_EXPERIMENT_IDS` 实为 r0–r2——报告笔误，以源码为准。
2. S2 预检读账本未做 E1 式临时副本；当前卡无训练/默认可换临时路径，**不构成拒绝**，但实盘接线前应对齐。

## RECOMMEND_ACCEPT_SCOPED（范围）

接受 P126 作为 **S2 phase1 生命周期接线（runner 桩、批准预检、10h 跨谱系上限、72h 日历分离、防重复、cli 只增不改）** 的交付；不接受把「生产账本预检已与 E1 同级 hermetic」或「LEDGER 含 r3」写成已实现事实。

修改文件：仅 `reports/V9-S2-P126/review/`。
交回统筹：可按 scoped 接受；实盘接线卡再收紧 `ledger_read_snapshot`。
