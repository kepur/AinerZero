# ainerzero.V9.T53 执行报告
角色：executor；负责人：gemini-r4x9；时间：2026-10-28
任务状态：reported；实验状态：未执行
任务依据：任务 ainerzero.V9.T53【L2·gemini·非作者复核】T28 r2 E18（全线合计 249 视 / 1440 s；独立重算账本副本）
输入身份：
  - 当前提案：`reports/V9-T28/r2/proposal.json` (SHA256: `31eef66689f82ea79ab50dd4cca7a15b8430c7d44aaf0dbcf0abf98fb989d278`)
  - 封存前版：`reports/V9-T28/r2/pre-E18-1694ed30/proposal.json` (SHA256: `1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5`)
  - 生产账本：`artifacts/v9/teachers/benchmark/runs.db` (SHA256: `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`，前后一致)
修改文件：`reports/V9-T53/gemini-r4x9/`（仅在自身目录编写复核脚本、日志与报告，未修改 `reports/V9-T28/r2/` 任何文件）
实际执行：
  - `python3 reports/V9-T53/gemini-r4x9/leaf_diff.py`
  - `python3 reports/V9-T53/gemini-r4x9/recalculate_ledger.py`
  - `python3 reports/V9-T53/gemini-r4x9/verify_consistency.py`
  - `/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python reports/V9-T53/gemini-r4x9/run_author_check_e18.py`
  - `python3 reports/V9-T53/gemini-r4x9/adversarial_test.py`
  - `python3 reports/V9-T53/gemini-r4x9/run_all_checks.py`
验证结果：
  - 逐叶比较：总变更叶节点 48 处，越界叶节点 0 处，严格局限于 `amendment` (19)、`budget.view_accounting` (18)、`budget.cumulative_wall_seconds_max` (1)、`budget.wall_accounting` (6)、`open_items` (4)；其他顶层节全部逐字未变。
  - 账本重算：复制 `runs.db` 只读查询，DA3 全线 14 条 run 视图和为 199、活跃秒数和为 1320.0 s；按任务分组完全吻合（T33: 82视/140s; T33.r2: 36视/10s; T6: 81视/1170s）。生产账本前后 SHA256 保持 `64b66805…` 严格不变。
  - 自洽与日志逐字：199 + 50 = 249；1320 + 120 = 1440；120 ≤ 1200；`retry_allowed` 为 false；状态为 `proposal_unapproved` 且不可执行；E17 历史数字保留。用户原话 `Whole line, 249/1440` 与 `RESEARCH_LOG.md:1501` 逐字一致。
  - 作者脚本复验：16 项检查全部 PASS。
  - 对抗实验：上限变 250 被自洽校验捕获；删 T33 run 导致总视 181 被重算校验捕获。全部测试通过。
产物：`reports/V9-T53/gemini-r4x9/` 下脚本、`logs/`、`metrics.json`、`SHA256SUMS.txt`
失败与限制：零模型、零训练、零账本修改，未改动生产库；已按只读副本与隔离输出运行。
交回统筹：复核全数通过，建议推进后续代码卡与登记流程。

---

## 详细复核依据与引用

### 1. 逐叶比对（非作者独立实现，禁 import/copy `check_e18.py`）
- 依据：`reports/V9-T28/r2/pre-E18-1694ed30/proposal.json` 对比 `reports/V9-T28/r2/proposal.json`。
- 脚本：`reports/V9-T53/gemini-r4x9/leaf_diff.py`，日志：`logs/leaf_diff.log`。
- 结果：总叶节点数由 362 增至 394，变化叶节点共 48 项，非授权路径改动数为 0。
- 改动分布：
  - `amendment`：19 项（含 `approved_by_user_fifth`、`changes.17`、`previous_revisions.4` 等）；
  - `budget.view_accounting`：18 项（`cumulative_view_cap` 131->249、`ledger_views_used_before_run` 81->199、`scope` 变更为 `"line_wide_all_da3_runs_in_central_runstore"`、引入 `ledger_by_task_2026_10_28` 及保留 `e17_t6_counter_figures`）；
  - `budget.cumulative_wall_seconds_max`：1 项（1290 -> 1440.0）；
  - `budget.wall_accounting`：6 项（`cumulative_cap_s` 1290->1440.0、`ledger_reserved_s` 1170->1320.0、`ledger_reserved_after_this_run_s` 1290->1440.0、`note` 更新及保留 `e17_t6_counter_figures`）；
  - `open_items`：4 项（明确记录 E18 口径与后续动作）。
- 未改动部分：`alignment`、`author`、`claims_forbidden`、`estimation`、`execution_permitted`、`execution_prerequisites`、`failure_policy`、`generator_sha256`、`input_manifest_sha256`、`lead_protocol_observed_sha256`、`negative_controls`、`numerical_parity`、`profile`、`protocol_id`、`residual_vector`、`review_task`、`schema`、`split`、`status`、`supersedes`、`task_id` 全部严格逐字相同。

### 2. 独立重算全线已用量（副本只读）
- 依据：生产文件 `artifacts/v9/teachers/benchmark/runs.db` 初始 SHA256 为 `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`。
- 副本：复制至 `reports/V9-T53/gemini-r4x9/runs.db` 并以 `mode=ro` 打开。
- 脚本：`reports/V9-T53/gemini-r4x9/recalculate_ledger.py`，日志：`logs/recalculate_ledger.log`。
- 提取规则：筛选 `config_json` 中 `model` 以 `da3` 开头的全部 run，共 14 条；累加 `config_json.views` 与 `active_seconds`。
- 重算结果：
  - 全线合计：`views` 总和 = **199**，`active_seconds` 总和 = **1320.0**。
  - 按 `task` 分组汇总：
    - `ainerzero.V9.T33`（5 条 run）：`views` = 82，`active_seconds` = 140.0；
    - `ainerzero.V9.T33.r2`（2 条 run）：`views` = 36，`active_seconds` = 10.0；
    - `ainerzero.V9.T6`（7 条 run）：`views` = 81，`active_seconds` = 1170.0。
- 提案一致性：与 `proposal.json` 中 `budget.view_accounting.ledger_by_task_2026_10_28` 字段逐项逐值完全一致。
- 生产库防篡改确认：重算完成后重新计算生产 `runs.db` 的 SHA256，仍为 `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`，未被触碰或修改。

### 3. 数字自洽与控制状态
- 依据文件：`reports/V9-T28/r2/proposal.json`
- 脚本：`reports/V9-T53/gemini-r4x9/verify_consistency.py`，日志：`logs/verify_consistency.log`
- 算术自洽：
  - 视图上限：`ledger_views_used_before_run` (199) + `charge_per_complete_run` (50) = `cumulative_view_cap` (249) = `ledger_views_after_this_run` (249)；每次计费 50 等于两模型前向视图和 (`models[0].forward_views` 25 + `models[1].forward_views` 25 = 50)。
  - 墙钟上限：`ledger_reserved_s` (1320.0) + `approved_run_wall_budget_seconds` (120) = `cumulative_wall_seconds_max` (1440.0) = `cumulative_cap_s` (1440.0) = `ledger_reserved_after_this_run_s` (1440.0)。
  - 单次时间限制：`approved_run_wall_budget_seconds` (120) ≤ `single_run_wall_seconds_max` (1200)。
  - 执行与重试限制：`budget.retry_allowed` = `false`；`status` = `"proposal_unapproved"`；`execution_permitted` = `false`。
  - E17 历史数字保留：
    - `budget.view_accounting.e17_t6_counter_figures` 保持 `{"cumulative_view_cap": 131, "ledger_views_used_before_run": 81}`；
    - `budget.wall_accounting.e17_t6_counter_figures` 保持 `{"cumulative_cap_s": 1290, "ledger_reserved_s": 1170}`。

### 4. 用户原话与 RESEARCH_LOG 对齐
- 逐字引用核对：
  - `proposal.json` 的 `amendment.approved_by_user_fifth.verbatim` 为 `"Whole line, 249/1440"`；
  - `proposal.json` 的 `budget.view_accounting.decided_numbers_by_user.verbatim` 为 `"Whole line, 249/1440"`；
  - `RESEARCH_LOG.md:1501` 原句逐字为：`  - **用户原话**（2026-10-28，本会话）：「Whole line, 249/1440」。`
  - `RESEARCH_LOG.md:1502-1506` 提议要点：
    - `DA3 配额按全线合计记账；`
    - `累计视图上限 249（已用 199 + 50），累计墙钟上限 1440 s（已用 1320 + 120）；`
    - `单次 120 s，只跑一次，不重试；`
    - `修掉 sitecustomize 按任务 ID 分账的漏洞。`
  - `proposal.json` 的 `approved_proposal` 字段值与上述日志记录完全一致。

### 5. 作者 `check_e18.py` 隔离复验
- 脚本位置：复制并修改输出路径至 `reports/V9-T53/gemini-r4x9/run_author_check_e18.py`。
- 目标路径：指向 `reports/V9-T28/r2/` 真实文件只读比对，产出写入 `logs/check_e18.out`，绝不改写 `reports/V9-T28/r2/`。
- 结果：16 项测试全部通过（`ALL PASS`），真实 runner `load_plan` 返回 `process_res=280`。

### 6. 对抗实验（证明 Step 1~3 检测能力）
- 脚本：`reports/V9-T53/gemini-r4x9/adversarial_test.py`，日志：`logs/adversarial_test.log`。
- 变异体 A：在提案副本中将 `cumulative_view_cap` 由 249 篡改为 250。
  - 检出证据：Step 3 校验断言 `199 + 50 = 249 != cap(250)` 立即报错触发 `AssertionError`，成功拦截。
- 变异体 B：在数据库副本中删除 1 条 T33 run（`0b5137b4049d48708c5df424b77dddc0`，18 views）。
  - 检出证据：Step 2 重算校验检测到全线视图和由 199 降至 181，T33 视图和由 82 降至 64，触发 `AssertionError: Total views mismatch: 181 != 199 (deficit: 18)`，成功拦截。

---

## 结论
建议通过
