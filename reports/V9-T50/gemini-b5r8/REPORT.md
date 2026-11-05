# ainerzero.V9.T50 非作者复核报告：T28 r2 E17 配额数字核验

- **复核任务编号**：`ainerzero.V9.T50`
- **被复核对象**：`T28 r2` 修订版 **`E17`**（封存比对基准：`reports/V9-T28/r2/pre-E17-2a984531/`，当前版本：`reports/V9-T28/r2/proposal.json`，SHA256: `1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5`）
- **复核执行代理**：`gemini-b5r8`（二级执行层，kind: gemini）
- **隔离与非作者资质核查**：
  - 本次复核对象 E17 作者为一级 `claude`，E1–E16 的作者为 `claude-az`；
  - 复核代理为 `gemini-b5r8`，不属于 `excluded_agents` 名单，与 `claude`、`claude-az` 及其同会话别名完全隔离，满足非作者独立复核要求。
- **守卫合规声明**：
  - 本卡严格执行**零模型、零账本**准则；
  - 纯 CPU 逻辑与静态核查，**未加载任何真实模型、未改动中央台账 `runs.db`、未碰共享锁 `m0-worker.lock`、未改写 `reports/V9-T28/r2/` 任何原文件、未提交、未推送**。

---

## 1. 独立逐叶对比检查（pre-E17 vs 当前版本）

- **执行说明**：独立编写 `diff_e17_leaves.py` 进行深层叶节点遍历对比，未 import 或复制作者脚本。
- **差异日志**：[`logs/leaf_diff.json`](logs/leaf_diff.json)
- **执行命令**：
  ```bash
  python3 reports/V9-T50/gemini-b5r8/diff_e17_leaves.py
  ```
- **执行输出**：
  ```text
  Total leaf diffs: 38
  Unallowed leaf diffs: 0
  ```
- **审查发现与结论**：
  - 全部 38 处叶差异严格限定在授权的 5 个子树：
    1. `amendment`：记录第四次用户原话「Approve as proposed」、所批提议引用、E17 修订记录、作者署名更新（E1-E16: claude-az, E17: claude）以及封存前版 `2a984531`；
    2. `budget.view_accounting`：写入用户批准的累计视图上限（`cumulative_view_cap=131`）、台账前向记账机制及状态由 `OPEN` 更新；
    3. `budget.cumulative_wall_seconds_max`：写入用户批准的累计墙钟上限 `1290`（原为 null）；
    4. `budget.wall_accounting`：写入批准的单次墙钟预算 `120 s`、累计上限 `1290 s` 及状态更新；
    5. `open_items`：同步关闭配额数字待定事项；
  - **核心不变性验证**：各阶段调用次数与视图数、`single_run_wall_seconds_max` (1200)、RSS 限额 (8GiB)、`retry_allowed` (false)、全部数学阈值与容差均**绝对未动、完全一致**。

---

## 2. 配额数字算术一致性核验

- **执行命令**：
  ```bash
  python3 -c "
  import json
  p = json.load(open('reports/V9-T28/r2/proposal.json'))
  b, va, wa = p['budget'], p['budget']['view_accounting'], p['budget']['wall_accounting']
  assert va['ledger_views_used_before_run'] + va['charge_per_complete_run'] == va['cumulative_view_cap'] == 131 == va['ledger_views_after_this_run']
  assert wa['ledger_reserved_s'] + wa['approved_run_wall_budget_seconds'] == b['cumulative_wall_seconds_max'] == wa['cumulative_cap_s'] == 1290 == wa['ledger_reserved_after_this_run_s']
  assert wa['approved_run_wall_budget_seconds'] <= b['single_run_wall_seconds_max']
  assert va['charge_per_complete_run'] == b['total_planned_forward_views'] == sum(m['forward_views'] for m in b['models']) == 50
  assert b['retry_allowed'] is False
  print('Arithmetic check passed!')
  "
  ```
- **执行输出**：
  ```text
  Arithmetic check passed!
  ```
- **审查发现与结论**：
  - **视图账目**：已用 81 + 本次 50 = 累计上限 131，完全闭环；
  - **墙钟账目**：已预留 1170 s + 本次 120 s = 累计上限 1290 s，完全闭环；
  - **单次约束**：单次预算 120 s ≤ 单次上限 1200 s；
  - **模型对齐**：每次完整运行计费 50 视图 = DA3-SMALL (25) + DA3-BASE (25)；
  - **重试策略**：严格禁止重试（`retry_allowed: false`）。

---

## 3. 用户原话与批准提议核查

- **执行命令**：
  ```bash
  python3 -c "
  import json
  p = json.load(open('reports/V9-T28/r2/proposal.json'))
  log = open('RESEARCH_LOG.md').read()
  coord = open('reports/coordination/PENDING-USER-20261028.md').read()
  v = p['amendment']['approved_by_user_fourth']['verbatim']
  assert v == p['budget']['view_accounting']['decided_numbers_by_user']['verbatim'] == 'Approve as proposed'
  assert f'「{v}」' in log
  assert 'view cap 131, wall cap 1290 s, 120 s per run' in log
  assert '视图上限 131、墙钟上限 1290 s、单次 120 s' in coord
  print('User approval verbatim check passed!')
  "
  ```
- **执行输出**：
  ```text
  User approval verbatim check passed!
  ```
- **审查发现与结论**：
  - 用户原话 `Approve as proposed` 逐字真实一致；
  - 提案文本所指的提议内容（视图上限 131、墙钟上限 1290 s、单次 120 s，只跑一次，不重试）与 `RESEARCH_LOG.md` 及 `reports/coordination/PENDING-USER-20261028.md` 第 1 节完全相符。

---

## 4. 状态与权限安全核查

- **执行命令**：
  ```bash
  python3 -c "
  import json
  p = json.load(open('reports/V9-T28/r2/proposal.json'))
  assert p['status'] == 'proposal_unapproved'
  assert p['execution_permitted'] is False
  print('Status check passed!')
  "
  ```
- **执行输出**：
  ```text
  Status check passed!
  ```
- **审查结论**：E17 修订仅写入参数，**未发生越权放行**，提案仍处于未批准状态且禁止执行。

---

## 5. SHA256 与封存自洽性核实

- **执行命令**：
  ```bash
  shasum -a 256 reports/V9-T28/r2/pre-E17-2a984531/proposal.json
  shasum -a 256 reports/V9-T28/r2/proposal.json
  cat reports/V9-T28/r2/proposal.sha256
  grep "proposal.json" reports/V9-T28/r2/SHA256SUMS.txt
  ```
- **执行输出**：
  - `pre-E17-2a984531/proposal.json`：`2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0`
  - 当前 `proposal.json`：`1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5`
  - `proposal.sha256`：`1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5  proposal.json`
  - `SHA256SUMS.txt`：`1694ed305c1a80d14ec0bfcf4117e16b246ce82b85c51fab16394e530dda9ff5  proposal.json`
- **审查结论**：封存上一版 SHA 精确吻合 T48 验收结果；当前 proposal 文件 SHA 与单列校验文件及总清单 100% 自洽。

---

## 6. 作者自检脚本独立复跑（零修改保障）

- **执行说明**：复制脚本至 `reports/V9-T50/gemini-b5r8/run_check_e17.py`，输出重定向至本目录 `logs/check_e17.out`，确认对 `reports/V9-T28/r2/` 零写入。
- **输出日志**：[`logs/check_e17.log`](logs/check_e17.log) 与 [`logs/check_e17.out`](logs/check_e17.out)
- **执行命令**：
  ```bash
  .venv/bin/python reports/V9-T50/gemini-b5r8/run_check_e17.py
  ```
- **执行输出**：
  ```text
  PASS 封存的上一版 SHA 为 2a984531
  PASS proposal.sha256 与文件一致
  PASS 变化只在 amendment / view_accounting / cumulative_wall_seconds_max / wall_accounting / open_items  [38 changed leaves; outside=[]]
  PASS 视图账：81 + 50 = 131 = 上限
  PASS 每次完整运行记 50 = 两型号前向视图之和
  PASS 墙钟账：1170 + 120 = 1290 = 上限
  PASS 单次 120 s 不超过单次上限
  PASS 不重试
  PASS 状态仍为 proposal_unapproved / 不可执行
  PASS 用户原话与 RESEARCH_LOG 逐字一致（原话与所批提议都在日志里）
  PASS 上一版登记在 previous_revisions
  PASS 其余顶层节逐字未变
  PASS budget 内只动了 view_accounting / cumulative_wall_seconds_max / wall_accounting
  PASS 真实 runner 能加载 E17 提案（零模型、零账本）  [process_res=280]
  ALL PASS
  ```
- **审查结论**：14 项业务、契约与加载断言全部通过（ALL PASS），退出码为 `0`。

---

## 7. 对抗性破坏实验验证

- **执行脚本**：`reports/V9-T50/gemini-b5r8/run_adversarial.py`
- **输出日志**：[`logs/adversarial.log`](logs/adversarial.log)
- **执行命令**：
  ```bash
  python3 reports/V9-T50/gemini-b5r8/run_adversarial.py
  ```
- **对抗场景与拦截结果**：
  1. **对抗样本 1（篡改配额上限）**：将 `cumulative_view_cap` 从 131 改为 132；
     - **拦截表现**：第 2 步算术核查立即捕获 `81 + 50 = 131 != 132`，立即拒绝；
  2. **对抗样本 2（篡改数值容差）**：将 `numerical_parity.cpu_float32.translation_norm_rel_max` 篡改为 0.09；
     - **拦截表现**：第 1 步逐叶比对立即捕获未授权字段差异并报警拦截。
- **审查结论**：复核检测工具链具备完备的异常识别与篡改防御能力。

---

## 8. 交付产物与最终结论

复核过程文件归档于 `reports/V9-T50/gemini-b5r8/`：
- [`REPORT.md`](REPORT.md)：本复核报告；
- [`metrics.json`](metrics.json)：指标与断言汇总；
- [`diff_e17_leaves.py`](diff_e17_leaves.py)：逐叶比对脚本；
- [`run_check_e17.py`](run_check_e17.py)：自检复跑脚本；
- [`run_adversarial.py`](run_adversarial.py)：对抗实验验证脚本；
- `logs/`：
  - [`logs/leaf_diff.json`](logs/leaf_diff.json)：38 处差异结构化记录；
  - [`logs/check_e17.out`](logs/check_e17.out) / [`logs/check_e17.log`](logs/check_e17.log)：自检日志；
  - [`logs/adversarial.log`](logs/adversarial.log)：对抗拦截记录；
- [`SHA256SUMS.txt`](SHA256SUMS.txt)：产物 SHA256 校验和。

**复核结论**：**建议通过**。
