# 非作者复核报告：E1 方案 A（ainerzero.V9.P105）

- **任务**：`ainerzero.V9.P105`【L2·gemini/claude·复核】非作者复核 P104（E1 日历窗口与 5 h 分开；引用逐字带行号）
- **复核者**：`gemini-x3n8`（二级执行 agent，新开独立会话）
- **被复核任务**：`ainerzero.V9.P104`（作者：`gemini-k8m2`）
- **复核原则**：只读核对、零真实运行、零源码改动、逐字引用带行号
- **自证**：复核者 ID 为 `gemini-x3n8`，非 P104 作者 `gemini-k8m2`，非其同会话别名，不在排除名单内。已在 `reports/V9-E1-A1/CARD-P105.md` 顶端写入自证。

---

## 结论

### **`RECOMMEND_ACCEPT`**

P104（E1 方案 A）代码改动严格限制在指定 4 个文件内，语义完全符合用户批准的方案 A 及冻结参数；全部 12 个其余源文件、`lifecycle.py`、生产数据与检查点 SHA256 与 `PRE-SEAL.sha256`、`PRE-DATASETS.sha256` 字节级一致；独立隔离副本变异测试证明测试真实有效；生产账本副本演练精确复算且不改动证据；全量回归 0 引入失败（3662 passed，净增 +5 passed）。

---

## 一、范围独立核实

### 1. 源码差异范围
运行 `diff -ru reports/V9-E1-A1/pre/src src/ainerzero/v9/experiments/e1`，确认有且仅有以下 4 个源文件存在改动：
- `src/ainerzero/v9/experiments/e1/spec.py`
- `src/ainerzero/v9/experiments/e1/worker.py`
- `src/ainerzero/v9/experiments/e1/commands.py`
- `src/ainerzero/v9/experiments/e1/prereg.py`

### 2. 其余文件与生产资产 SHA256 对账（独立复算，不依赖 POST-SEAL）
对所有基线文件执行哈希复算并比对 `reports/V9-E1-A1/PRE-SEAL.sha256` 与 `reports/V9-E1-A1/PRE-DATASETS.sha256`：
- **其余 12 个 E1 源文件**（`__init__.py`, `analysis.py`, `arms_net.py`, `arms_nonnet.py`, `data_runner.py`, `eval_runner.py`, `export.py`, `identity.py`, `jacobian.py`, `metrics.py`, `prior.py`, `train_runner.py`）：全部 100% 吻合，0 差异。
- **运行时核心**：`src/ainerzero/runtime/lifecycle.py` SHA256 为 `22ded55ce136b3186e48051ca1681cef5fc129e8a13fcd515261afccde196b3f`，与 PRE-SEAL 完全一致。
- **生产资产**：
  - `artifacts/v9/e1/phase2/prereg.json`（SHA: `ad8ef44faae00ec3e951475c7b399222c95e33d4aa09db542c8bc5c4b8b64e16`）
  - `artifacts/v9/e1/phase2/control.sqlite3`（SHA: `508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244`）
  - 生产 `checkpoints/` 下全部 27 个检查点文件（9 个格点各 3 文件）：全部 100% 吻合。
- **AWZ 数据集**：`reports/V9-E1-A1/PRE-DATASETS.sha256` 所列全部 7611 个数据文件，逐一核验 SHA256，0 缺失、0 差异。

### 3. `spec.py` 差异核验
`spec.py` 与 `pre/src/spec.py` 对比仅有 3 处变动，其余科学常数字节不变：
1. **实验 ID 更新**（第 48 行）：
   ```python
   48: EXPERIMENT_ID = "e1-phase2-20261029-r1"
   ```
2. **谱系声明与末项断言**（第 49–53 行）：
   ```python
   49: LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (
   50:     "e1-phase2-20261029-r0",
   51:     "e1-phase2-20261029-r1",
   52: )
   53: assert LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID
   ```
3. **日历窗口常量注入**（第 303 行）：
   ```python
   303:     "experiment_calendar_window_seconds": 259200.0,  # 72.0 h calendar window
   ```
物理超参数、网络结构超参数、各格预算与门槛常量完全未变。

---

## 二、语义逐条核查（逐字引用带行号）

### 1. 实验级 `max_wall_seconds` 取 259200，运行级 `budget` 仍为 18000
- **`worker.py` 第 186–187 行**：
  ```python
  186:     wall_ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
  187:     calendar_window = float(spec.BUDGET_CAPS["experiment_calendar_window_seconds"])
  ```
- **`worker.py` 第 205–212 行（运行级预算不变）**：
  ```python
  205:         "budget": {
  206:             "max_environment_steps": 10_000_000,
  207:             "max_optimizer_steps": derived_run_optimizer_steps,
  208:             "max_wall_seconds": wall_ceiling,
  209:             "max_daily_active_seconds": wall_ceiling,
  210:             "max_model_transitions": 0,
  211:             "timezone": TIMEZONE,
  212:         },
  ```
- **`worker.py` 第 219–226 行（实验级预算取日历窗口）**：
  ```python
  219:         "experiment_budget": {
  220:             "max_model_runs": 100,
  221:             "max_environment_steps": 10_000_000,
  222:             "max_optimizer_steps": derived_experiment_optimizer_steps,
  223:             "max_model_transitions": 1,
  224:             "max_wall_seconds": calendar_window,
  225:             "max_calibration_seconds": 3600.0,
  226:         },
  ```

### 2. `_check_phase_budget_ceiling` 与 `check_cell_already_completed` 跨 r0+r1 参数化查询
- **`commands.py` 第 141–145 行**：
  ```python
  141:             placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
  142:             cursor = store._conn.execute(
  143:                 f"SELECT active_seconds, config_json FROM runs WHERE experiment_id IN ({placeholders})",
  144:                 spec.LEDGER_EXPERIMENT_IDS,
  145:             )
  ```
  此处 `placeholders` 生成 `?, ?`，以元组 `spec.LEDGER_EXPERIMENT_IDS` 作为查询参数传入，无字符串拼接注入风险，且同时覆盖 r0 与 r1。
- **`worker.py` 第 160–164 行**：
  ```python
  160:         placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
  161:         cursor = store._conn.execute(
  162:             f"SELECT config_json, state FROM runs WHERE experiment_id IN ({placeholders})",
  163:             spec.LEDGER_EXPERIMENT_IDS,
  164:         )
  ```
  同样采用参数化查询，遍历 `LEDGER_EXPERIMENT_IDS` 下所有运行，防止 r0 已完成的单元格在 r1 下重复执行。

### 3. `prereg.py` `validate` 覆盖卡面全部要求
- **`prereg.py` 第 115 行（`build_draft` 注入）**：
  ```python
  115:         "ledger_experiment_ids": list(spec.LEDGER_EXPERIMENT_IDS),
  ```
- **`prereg.py` 第 206–218 行（谱系完整校验）**：
  ```python
  206:     # Lineage validation
  207:     ledger_ids = document.get("ledger_experiment_ids")
  208:     if not isinstance(ledger_ids, (list, tuple)):
  209:         raise SpecValidationError("Missing or invalid ledger_experiment_ids list")
  210:     if tuple(ledger_ids) != spec.LEDGER_EXPERIMENT_IDS:
  211:         raise SpecValidationError(
  212:             f"ledger_experiment_ids mismatch: expected {spec.LEDGER_EXPERIMENT_IDS}, got {tuple(ledger_ids)}"
  213:         )
  214:     if not ledger_ids or ledger_ids[-1] != document.get("experiment_id"):
  215:         raise SpecValidationError(
  216:             f"Last element of ledger_experiment_ids ({ledger_ids[-1] if ledger_ids else None}) "
  217:             f"must match experiment_id ({document.get('experiment_id')})"
  218:         )
  ```
- **`prereg.py` 第 337 行与第 350–356 行（日历窗口存在、正数且 `>= 18000.0`）**：
  ```python
  337:         "experiment_calendar_window_seconds",
  ...
  350:     cal_window = float(budget["experiment_calendar_window_seconds"])
  351: 
  352:     if cal_window < total_ceiling:
  353:         raise SpecValidationError(
  354:             f"experiment_calendar_window_seconds ({cal_window:.1f} s) must be >= "
  355:             f"phase_total_wall_ceiling_seconds ({total_ceiling:.1f} s)"
  356:         )
  ```

### 4. `scan_approval_log`、`find_approval`、`freeze` 未被改动
通过 `diff -u reports/V9-E1-A1/pre/src/prereg.py src/ainerzero/v9/experiments/e1/prereg.py` 严格核验：第 360 行之后完全没有任何 diff。`scan_approval_log`、`find_approval`、`freeze` 及审批签名校验逻辑一字未改。

---

## 三、Lifecycle 交互独立判断

### 1. 代码机制研判（`lifecycle.py` 第 355–460 行与第 570–720 行）
- **实验级日历窗口判定**（第 437–441 行）：
  ```python
  remaining.update(
      wall_seconds=max(
          0.0,
          budget["max_wall_seconds"]
          - max(0.0, instant - row["created_at"], totals["active_seconds"]),
      ), ...
  ```
  在方案 A 下，r1 作为一个独立的实验行登记在 `experiments` 表中，其 `created_at` 为 r1 首次初始化时刻，`budget["max_wall_seconds"]` 为 259200.0 s（72 h）。因此，从登记起算的日历窗口拥有充裕的 72 h，r0 的 7.5 h 空档不会挤占 r1 的窗口。
- **准入检查机制**（第 577–601 行）：
  `create_run` 在准入时核查 `experiment.remaining["wall_seconds"] > 0`。由于日历窗口扩展为 72 h，不再发生 P101 遇到的 `BudgetExceeded("experiment_wall_seconds_budget")`。

### 2. 日上限核算（2026-11-03 Asia/Shanghai 当天）
- 检查生产账本 `artifacts/v9/e1/phase2/control.sqlite3` 中的 `daily_budget` 表：
  - `local_date`: `2026-11-03`
  - `limit_seconds`: `18000.0`
  - `reserved_seconds`: `9600.0`
  - 当天剩余日额度：`18000.0 - 9600.0 = 8400.0 s`。
- 后续待跑单元格预算需求：
  - **S 族 9 格**（⑥ 3 格 × 1200 s = 3600 s；②③ 6 格 × 450 s = 2700 s）：合计 `6300.0 s`。
  - **dev 26 格**（可训练臂 18 格：⑥ 6 格 × 150 s = 900 s，②③ 12 格 × 40 s = 480 s；非训练臂 8 格 × 45 s = 360 s）：合计 `1740.0 s`。
  - **待跑总计**：`6300.0 + 1740.0 = 8040.0 s`。
- **判断**：
  `8040.0 s <= 8400.0 s`，尚余 `360.0 s` 裕量。
  因此，即使 S 族与 dev 全部在 2026-11-03 当天跑完，**日上限完全够用**，不会被 `daily_active_time_budget` 拦截。若跨过午夜至次日（11-04），次日将获得全新的 18000 s 日限额，更不可能受限。

---

## 四、测试真伪与变异核实

### 1. (a)–(e) 测试真伪核实
查阅 `tests/test_e1_calendar_window.py` 源码：
- `test_case_a_gap_does_not_reject`: 真实调用 `commands.e1_phase2_command(args)`，通过 `FakeClock` 推进 36010 s，经由 `worker_lock` -> `execute_work_cell` -> `RunStore.create_run` 完整走通准入。
- `test_case_b_combined_phase_ceiling`: 在测试账本中构造 r0=9600s + r1=7200s（共 16800s），分别验证边界格 1200s 成功（累计刚好 18000.0s）与再申请 60s 被 `_check_phase_budget_ceiling` 以 `phase_budget_exceeded` 拒绝。
- `test_case_c_cross_lineage_anti_duplicate`: 真实调用 `commands.e1_phase2_command` 测试 `generate-data` 与 `train(6, P, 42)`，均在 Preflight C 返回 `duplicate_execution`。
- `test_case_d_prereg_validation_and_subprocess`: 针对缺少谱系、反序、末项不匹配、日历窗口缺失、日历窗口小于 18000 共 5 种非法文档调用 `prereg.validate`，并启动独立无外部环境变量的 python 子进程（`-I`）执行校验。
- `test_case_e_full_schedule_rehearsal_with_7_5h_gap`: 完整调度演练数据生成、P 族、推进 7.5 h 假时钟、S 族、dev 评测及 final 评测。

### 2. 独立变异坏对照（在完全隔离临时目录中执行，排除 `__pycache__` 并断言 import 路径）
在临时副本中执行了 6 项变异（包含 4 项作者变异表之外的全新变异，以及 2 项结构性边界变异）：

| 变异 ID | 变异位置与操作 | 针对测试 | 测试结果 | 深度分析 |
| :--- | :--- | :--- | :--- | :--- |
| **M-IND-1** | `prereg.py` `validate`: 旁路 `cal_window < total_ceiling` 检查 | `test_case_d` | **RED (FAILED)** (code=1) | `test_case_d` 第 396 行捕获 `DID NOT RAISE SpecValidationError`，变红成功。 |
| **M-IND-2** | `commands.py` `_check_phase_budget_ceiling`: 边界判断由 `>` 改为 `>=` | `test_case_b` | **RED (FAILED)** (code=1) | 导致恰好等于 18000.0 s 的边界单元格被误判为超限，断言失败变红。 |
| **M-IND-3** | `prereg.py` `build_draft`: 不注入 `ledger_experiment_ids` 字段 | `test_case_d` | **RED (FAILED)** (code=1) | 子进程校验第 406 行触发 `KeyError: 'ledger_experiment_ids'`，变红成功。 |
| **M-IND-4** | `worker.py` `check_cell_already_completed`: 屏蔽状态判断 `if state != "completed"` | `test_case_c` | **RED (FAILED)** (code=1) | 已完成单元格不再被识别，导致 r0 任务未能触发 `duplicate_execution` 拒绝。 |
| **M-IND-5** | `prereg.py` `validate`: 删除末项匹配检查 `if not ledger_ids or ledger_ids[-1] != ...` | `test_case_d` | **SURVIVED (PASSED)** (code=0) | **存活分析（死代码/前置拦截）**：在 `validate` 中，前面紧随的 `tuple(ledger_ids) != spec.LEDGER_EXPERIMENT_IDS` 已经对整个元组进行了严格全等比对；由于 `spec.py` 模块级硬性断言 `LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID`，任何末项不符合 `experiment_id` 的输入在上一行已被 `ledger_experiment_ids mismatch` 拦截抛错。因此该分支在现有前置条件严格成立下属于防守性冗余代码。 |
| **M-IND-6** | `worker.py` `check_cell_already_completed`: 屏蔽 `if mode == "generate-data": return True` | `test_case_c` | **SURVIVED (PASSED)** (code=0) | **存活分析（重叠逻辑）**：对于 `generate-data`，其 `arm`、`family`、`seed` 均为 `None`；即便跳过特判，后续的通用匹配 `if cfg.get("arm") == arm and cfg.get("family") == family:` 同样评估为 `None == None` 并返回 `True`，因此该特判与通用逻辑等价重叠。 |

### 3. 一级关注点核验与回应
1. **P104 `mutations.json` 测试回溯路径指向主仓库问题**：
   - **核验确认**：P104 使用 `shutil.copytree` 复制 `tests` 时未排除 `__pycache__`，带入了主仓库中已预编译的 `.pyc` 字节码。Python 在回溯打印时直接使用了 `.pyc` 内嵌的 `co_filename`（绝对路径），造成回溯路径显示为主仓库。
   - **复核验证**：复核者在隔离复制时加入 `ignore=shutil.ignore_patterns('__pycache__', '*.pyc')` 并设置 `PYTHONDONTWRITEBYTECODE=1`、`-p no:cacheprovider`，证实 pytest 回溯正确指向临时工作树路径。同时经由 `git status` 及 SHA 比对确认，**主仓库源码在变异测试期间始终未被触碰或修改**。
2. **`spec.py` 模块级 `assert` 在 `python -O` 下被优化剥离的风险**：
   - **核验确认**：`assert LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID` 在 `python -O` / `PYTHONOPTIMIZE=1` 下确实会被编译器剥离。
   - **兜底研判**：在一切正常入口流程中，`prereg.validate(build_draft())` 均会显式执行。由于 `validate` 内部对 `ledger_ids[-1] != document.get("experiment_id")` 有显式 `if` 判断与 `raise SpecValidationError`，即使没有模块级 assert，依然拥有双重兜底。
   - **后续建议**：为防御未来可能有直接 import `spec.py` 而绕过 `prereg.validate` 的极端场景，建议统筹在后续版本中将第 53 行显式改为 `if LEDGER_EXPERIMENT_IDS[-1] != EXPERIMENT_ID: raise ValueError(...)`。
3. **M1 变异下 (a) 的拒绝阶段与退出码**：
   - **路径梳理**：M1 将 `max_wall_seconds` 还原为 18000s，在经过 36010s 假时钟后准入。此时 `commands._check_phase_budget_ceiling` 只累计实际用时（9600s + 1200s = 10800s <= 18000s），Preflight D 准入通过；
   - 随后进入 `worker.execute_work_cell` -> `ledger.open_run` -> `store.create_run`；
   - 在 `lifecycle.py` 第 591 行，中央守卫检测到 `experiment.remaining["wall_seconds"] <= 0`，抛出 `BudgetExceeded("experiment_wall_seconds_budget")`；
   - `commands.py` 第 444 行 `except Exception as exc:` 捕获该异常，返回 `status="failed"`, `stage="execution_failed"`, `message="Budget exhausted: experiment_wall_seconds_budget"`，并退出 `EXIT_FAILED` (= 1)。
   - **结论**：这一行为完全阻止了运行行的脏写入，立即停机并向调用方返回失败退出码，完全符合运行卡「被拒就停下交回」的判读。

---

## 五、生产账本副本演练复算

### 1. 证据防篡改执行
为遵守 COORDINATION 规则 8，复核者将 `reports/V9-E1-A1/rehearse_on_copy.py` 复制到临时目录并重定向输出至 `/tmp/rehearsal_isolated_out.json`，原始证据文件 `reports/V9-E1-A1/rehearsal.json` 在复算前后字节未变。

### 2. 演练复算结果
- **生产账本 SHA256**：
  - 拷贝前：`508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244`
  - 拷贝后：`508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244`（完全一致，生产零改动）
- **核对指标**：
  - r0 初始已消耗：`9600.0 s`
  - 数据生成状态：`completed`（r0 已完成）
  - P 族 9 格状态：全部 `completed`（r0 已完成）
  - S 族 9 格状态：全部 `uncompleted`
  - S 族 9 格准入后累计：`15900.0 s`（与预期 15900.0 完全一致）
  - dev 26 格准入后累计：`17640.0 s`（与预期 17640.0 完全一致）
  - 尝试准入第 36 格（1200.0 s）：被中央守卫在 Preflight 拒绝，`code=2`（`EXIT_REFUSED_RESOURCE`），`stage="phase_budget_exceeded"`。
- **证据 SHA 比对**：
  复算生成的 JSON 哈希与 P104 提交的 `reports/V9-E1-A1/rehearsal.json` 完全一致：
  `1f35dbb9617f8c2d5e62f4574dea4407380d7b4da8884dbae650bacc3a91ceaf`。

---

## 六、全量回归计数（SIG_DFL + execv 前台运行）

使用 `signal.signal(signal.SIGINT, signal.SIG_DFL)` 恢复信号默认行为并通过前台同步执行：

1. **E1 专属回归测试**：
   - 命令：`.venv/bin/pytest tests/test_e1_*.py -q`
   - 结果：**212 passed in 31.89s**（通过率 100%）。
2. **全仓库 pytest 回归测试**：
   - 命令：`pytest -q`
   - 计数：**6 failed, 3662 passed, 5 deselected in 246.77s**。
   - **分析**：失败的 6 项测试均为全仓既有外部硬编码基线（如 MLX 导入哨兵、阶段记账测试等），与 P104 报告基线完全相同；通过测试从基线 3657 稳步净增 +5 项（来自 `test_e1_calendar_window.py`），全仓 **0 回归**。

---

## 七、复核意见与交接

1. **验收结论**：**`RECOMMEND_ACCEPT`**。P104 实现完整、严谨，满足方案 A 的全部要求。
2. **建议一级统筹后续动作**：
   - 归档 `prereg.json` 为 `prereg.r0.json`；
   - 冻结 `e1-phase2-20261029-r1` 的预登记；
   - 替换 `RESEARCH_LOG.md` 批准行为 r1 授权行；
   - 放行 S 族训练（P101）与 dev 评测（P102），并执行连续派发。
