**E1 方案 A 实现：把实验级「日历窗口」与 5 h 实际用时分开，新登记实验 r1，总上限与防重复跨 r0+r1 合并。** CPU、零训练、零真实运行。

裁定依据：`RESEARCH_LOG.md` 的 `R20261103-E1-calendar-window-stop`（现象）与 `R20261103-E1-A-ruling`（用户批准与参数）。下文的参数是一级定的，不得改动。

## 背景（一级读码核实）
- `src/ainerzero/runtime/lifecycle.py` 第 436–440 行：实验剩余墙钟 = `max_wall_seconds − max(从实验登记起已过时间, 累计 active_seconds)`。所以实验级 `max_wall_seconds` 实际上是从登记起算的日历窗口。
- `worker.get_experiment_manifest`（第 183 行起）把它设成 `phase_total_wall_ceiling_seconds = 18000`。r0 在 11-03 01:10 登记，P 族跑完后空了 7.5 h，窗口在空档里耗尽，S 族第一格在准入时被拒（`experiment_wall_seconds_budget`）。
- 实验清单不可变（`create_experiment` 按 request_id 幂等），所以只能另登记新 id。

## 要做（文件范围仅限下列 4 个源文件，加 tests/ 与 `reports/V9-E1-A1/`）

1. **`spec.py`**（只改以下几行，其余字节不变）：
   - `EXPERIMENT_ID = "e1-phase2-20261029-r1"`；
   - 新增 `LEDGER_EXPERIMENT_IDS: tuple[str, ...] = ("e1-phase2-20261029-r0", "e1-phase2-20261029-r1")`，并在模块级断言 `LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID`；
   - `BUDGET_CAPS` 新增 `"experiment_calendar_window_seconds": 259200.0`（72 h，实验级日历窗口，从 r1 登记起算），其余键值不变。
2. **`worker.py`**：
   - `get_experiment_manifest`：`experiment_budget.max_wall_seconds` 改取 `experiment_calendar_window_seconds`；运行级 `budget`（18000）不变；在注释里写明两者的区别。
   - `check_cell_already_completed`：查询范围改为 `experiment_id IN LEDGER_EXPERIMENT_IDS`（用参数化占位符，不要拼字符串）。
3. **`commands.py`**：`_check_phase_budget_ceiling` 把 `LEDGER_EXPERIMENT_IDS` 里所有实验的预留一起累计，计算口径（`active_seconds`，为 0 时回退到 `cell_wall_budget_seconds`）不变。
4. **`prereg.py`**：
   - `build_draft` 新增 `"ledger_experiment_ids": list(spec.LEDGER_EXPERIMENT_IDS)`；
   - `validate` 新增两类检查：
     - 文档里的 `ledger_experiment_ids` 必须与 spec 完全一致，并且最后一项等于 `experiment_id`；
     - `budget_caps.experiment_calendar_window_seconds` 必须存在且为正数，不小于 `phase_total_wall_ceiling_seconds`。
   - `scan_approval_log`、`find_approval`、`freeze`、`APPROVAL_*` 一字不改。

## 禁止
- 不改其他 12 个实现源文件，即 `train_runner`、`arms_net`、`arms_nonnet`、`data_runner`、`eval_runner`、`metrics`、`prior`、`jacobian`、`analysis`、`export`、`identity`、`__init__`；也不改 `src/ainerzero/runtime/lifecycle.py` 和 AWZ 生成器。交回时这些文件的 SHA 必须与 `reports/V9-E1-A1/PRE-SEAL.sha256` 一致。
- 不碰生产数据：`artifacts/v9/e1/phase2/` 下的 `prereg.json`、`control.sqlite3`、`checkpoints/`、`datasets/` 一律只读。只允许用文件拷贝把账本复制到临时目录使用，不得用 sqlite 直接打开生产账本。不改 `RESEARCH_LOG.md` 和批准行。
- 不跑任何真实的 `e1-phase2` 模式（包括对生产路径的 `verify`；代码改动后它本来就会因身份不符而拒绝）。不 freeze，不训练，不用 MLX/GPU，不下载。
- 测试与演练全部用临时 `output_root`、`ledger`、`lock_file`、`research_log`、`prereg`，在任何写操作之前断言这些路径都在临时目录下。

## 测试（新文件 `tests/test_e1_calendar_window.py`，必要时更新现有测试里写死 r0 或 18000 的断言，逐条列出）
- (a) **空档不再拒绝**：在临时账本里用假时钟登记一个 r0 实验（清单按旧口径，实验级 18000），写入已完成的运行，预留合计 9600 s。在 t0+36010 s 通过 `e1_phase2_command` 与假 runner 准入一格 r1 训练，必须通过。
- (b) **合并总上限**：r0 记 9600 s，r1 累计到使 r0+r1 超过 18000 的那一格时，必须以 `phase_budget_exceeded` 拒绝，即使 r1 单独并未超限。边界值（恰好等于 18000）要单独测一条。
- (c) **跨谱系防重复**：r0 已完成的 `generate-data` 与 `train(6,P,42)` 在 r1 下返回 `duplicate_execution`；`train(6,S,42)` 不被拒绝。
- (d) **prereg 校验**：缺 `ledger_experiment_ids`、顺序颠倒、末项不等于 `experiment_id`、日历窗口小于 18000 或缺失，四种情况各自抛 `SpecValidationError`。另用 `.venv/bin/python -I` 的子进程直接跑 `validate(build_draft())`，不经 conftest。
- (e) **全程演练**：扩展或新增假时钟双族演练，在 P 族与 S 族之间插入 7.5 h 空档，必须全程通过。

## 生产账本副本上的演练（脚本放 `reports/V9-E1-A1/rehearse_on_copy.py`，不进 pytest）
1. 拷贝 `artifacts/v9/e1/phase2/control.sqlite3` 到临时目录，拷贝前后对生产文件复算 SHA，两次须一致。
2. 在副本上核对：`_check_phase_budget_ceiling(copy, 1200)` 得到 consumed = 9600；P 族 9 格与数据生成为「已完成」，S 族 9 格为「未完成」。
3. 用假 runner、临时 output_root 与 lock，以当前真实时间为时钟，依次准入 S 族 9 格（⑥ 1200、②③ 450）和 dev 26 格（⑥ 150、②③ 40、非训练臂 45）。全部准入后 consumed 应为 17640。再加一格 1200，必须以 `phase_budget_exceeded` 拒绝。
4. 输出写进 `rehearsal.json`。

## 变异坏对照（隔离副本：复制 `src`、`tests`、`pyproject.toml`，断言 import 解析到副本；每处跑完按字节还原并校验 SHA）
- M1：实验级 `max_wall_seconds` 改回 `phase_total_wall_ceiling_seconds` → (a) 和 (e) 必须变红；
- M2：`_check_phase_budget_ceiling` 只查 `spec.EXPERIMENT_ID` → (b) 必须变红；
- M3：`check_cell_already_completed` 只查当前 id → (c) 必须变红；
- M4：删掉 `validate` 里的谱系检查 → (d) 必须变红；
- M5：`LEDGER_EXPERIMENT_IDS` 去掉 r0 → (b) 或 (c) 必须变红。
- 变异脚本放 `reports/V9-E1-A1/run_mutations.py`。不得在测试里重写被测函数，也不得用恒真式。

## 全量回归
- E1 测试与全量 pytest 的前后计数。不能用 nohup 或 & 在后台跑（SIGINT 测试会假失败）；用 SIG_DFL+execv 还原信号后前台跑。

## 交回 `reports/V9-E1-A1/`
- `REPORT.md`：改动摘要、4 个源文件的 unified diff（对 `reports/V9-E1-A1/pre/`）、测试清单、演练输出、变异表（命令与输出尾部）、全量计数；
- `POST-SEAL.sha256`：改动后 4 个源文件与新增/修改测试的 SHA，以及其余 12 个源文件、lifecycle、生产 prereg/账本/checkpoint 的 SHA，后者须与 PRE-SEAL 一致；
- 再写一份 `metrics.json`。
- 如有设计疑问，先在卡上提问（`relay tell --kind question`），不要自行改参数。
