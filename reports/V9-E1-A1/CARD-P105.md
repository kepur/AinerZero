**非作者复核 P104（E1 方案 A：日历窗口与 5 h 实际用时分开，r1 谱系）。** 只读、零真实运行。每条发现都要逐字引用并带行号。

> **复核者自证**：执行者 ID 为 gemini-x3n8（独立新会话），非 P104 作者（gemini-k8m2），亦非其同会话别名，不在排除名单中。严格遵守只读核对、零真实运行、零源码改动规则。

先读：
- 实现卡 `reports/V9-E1-A1/CARD-P104.md`；
- `RESEARCH_LOG.md` 的 `R20261103-E1-calendar-window-stop` 与 `R20261103-E1-A-ruling`；
- P104 的交回 `reports/V9-E1-A1/REPORT.md`。

复核者不得是 P104 的作者，也不得是作者的同会话别名。领卡后先在卡上写一行自证。

## 必须独立核实
1. **范围**：
   - 用 `diff -ru reports/V9-E1-A1/pre/src src/ainerzero/v9/experiments/e1` 对照，确认只有 `spec.py`、`worker.py`、`commands.py`、`prereg.py` 四个文件改动；
   - 其余 12 个源文件、`src/ainerzero/runtime/lifecycle.py`，以及生产 `prereg.json`、`control.sqlite3`、checkpoint、数据集的 SHA 与 `PRE-SEAL.sha256` 和 `PRE-DATASETS.sha256` 一致（自己复算，不用作者的 POST-SEAL）；
   - `spec.py` 的 diff 只涉及 `EXPERIMENT_ID`、`LEDGER_EXPERIMENT_IDS` 与 `experiment_calendar_window_seconds` 三处，其余科学常数字节不变。
2. **语义**，逐条带行号说明：
   - 实验级 `max_wall_seconds` 取 259200；运行级 `budget` 仍为 18000；
   - `_check_phase_budget_ceiling` 与 `check_cell_already_completed` 都覆盖 r0+r1，并且用参数化查询；
   - `validate` 的新检查覆盖卡面列出的全部情况；
   - `scan_approval_log`、`find_approval`、`freeze` 一字未改。
3. **lifecycle 交互**：读 `lifecycle.py` 第 355–460 行与第 570–720 行，独立判断 r1 是否还有别的路径会被 5 h 日历窗口或日上限挡住。日上限按 Asia/Shanghai 日期计算，11-03 已预留 9600 s，限额 18000 s。写明 S 族与 dev 在 11-03 当天跑完时，日上限是否够用。
4. **测试真伪**：
   - 确认 (a)–(e) 真的调用了被测函数，不是在测试里重写，也不是常数比较；
   - 自己在隔离副本里另做 **至少 3 处** 作者变异表之外的变异（连同 `tests` 与 `pyproject.toml` 一起复制，断言 import 解析到副本），报告每处是变红还是存活；存活的要判断是测试漏洞，还是改了等于没改的死代码。
5. **演练复算**：在你自己的临时目录里重跑 `reports/V9-E1-A1/rehearse_on_copy.py`（它只拷贝生产账本，拷贝前后对生产文件复算 SHA），核对 consumed 9600 → 17640，以及第 36 格被拒。
6. **全量回归**：E1 测试与全量 pytest 的计数。前台用 SIG_DFL+execv 跑，不用 nohup 或 &。

## 结论
在交回报告里写 `RECOMMEND_ACCEPT`、`RECOMMEND_ACCEPT_SCOPED`（写明范围）或 `RECOMMEND_REJECT`（列出阻断项）。报告放 `reports/V9-E1-A1/REVIEW-P105.md`。不改任何源码或测试。
