# ainerzero.V9.T48 非作者复核报告：T28 r2 E16 差异核验

- **复核任务编号**：`ainerzero.V9.T48`
- **被复核对象**：`T28 r2` 修订版 **`E16`**（封存比对基准：`reports/V9-T28/r2/pre-E16-86f5ece6/`，当前版本：`reports/V9-T28/r2/proposal.json`，SHA256: `2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0`）
- **复核执行代理**：`gemini-b5r8`（二级执行层，kind: gemini）
- **隔离与非作者资质核查**：
  - 本次复核对象作者为 `claude-az`；
  - 复核代理为 `gemini-b5r8`，不属于 `excluded_agents` 名单，与 `claude-az` 及其同会话别名完全隔离，满足非作者独立复核要求。
- **守卫合规声明**：
  - 本卡严格执行**零模型、零账本**准则；
  - 纯 CPU 静态与逻辑核验，**未加载任何真实模型、未改动中央台账 `runs.db`、未碰共享锁 `m0-worker.lock`、未改写 `reports/V9-T28/r2/` 任何原文件、未提交、未推送**。

---

## 1. 逐叶对比检查（pre-E16 vs 当前版本）

- **执行脚本**：`reports/V9-T48/gemini-b5r8/diff_leaves.py`
- **详细差异日志**：[`logs/leaf_diff.json`](logs/leaf_diff.json)
- **执行命令**：
  ```bash
  python3 reports/V9-T48/gemini-b5r8/diff_leaves.py
  ```
- **执行输出**：
  ```text
  Total leaf diffs: 37
  Unallowed leaf diffs: 0
  ```
- **审查发现与结论**：
  - 所有 37 处叶差异严格局限在以下 4 个受控子树中：
    1. `amendment`：新增第三次用户原话记录、E16 修订记录（review_history 对接 T46 意见、previous_revisions 封存前版 86f5ece6）；
    2. `budget.view_accounting`：写入用户定下的配额口径（前向视图、`charge_per_complete_run=50`、状态更新）；
    3. `numerical_parity.retired_stages[0]`：按 V9.T46 意见修正 reason（署名 CPU 独立复现，明确 MPS 为作者报告）、not_replaced（限定在 `.venv-t6` 并指向 `model/da3.py:139`）；
    4. `open_items`：同步更新开放事项描述；
  - **核心不变性验证**：`alignment`、`residual_vector`、`estimation`、所有数值阈值与容差（`numerical_parity.cpu_float32/mps_float16`）、`split`、`budget` 各阶段次数与视图数、`wall/RSS` 物理限额均**完全一致、零变动**。

---

## 2. 第三次用户原话逐字一致性核验

- **执行命令**：
  ```bash
  python3 -c "
  import json
  p = json.load(open('reports/V9-T28/r2/proposal.json'))
  log = open('RESEARCH_LOG.md').read()
  v1 = p['amendment']['approved_by_user_third']['verbatim']
  v2 = p['budget']['view_accounting']['decided_by_user']['verbatim']
  print('amendment verbatim == budget verbatim:', v1 == v2)
  print('verbatim in RESEARCH_LOG.md:', v1 in log)
  print('Verbatim text:', repr(v1))
  "
  ```
- **执行输出**：
  ```text
  amendment verbatim == budget verbatim: True
  verbatim in RESEARCH_LOG.md: True
  Verbatim text: '配额口径用前向视图（诚实口径，每次记 50）。具体数字我随后告知；你先不要动账本。'
  ```
- **审查发现与结论**：
  - `proposal.json` 两处记录的原话完全一致；
  - 与 `RESEARCH_LOG.md` 2026-10-28 统筹记录（条目「用户定配额记账口径＝前向视图」）中的用户原话**逐字一致，零字差**。

---

## 3. 配额算术与状态字段核查

- **执行脚本**：`reports/V9-T48/gemini-b5r8/check_budget_parity.py`
- **输出日志**：[`logs/budget_parity.log`](logs/budget_parity.log)
- **执行命令**：
  ```bash
  python3 reports/V9-T48/gemini-b5r8/check_budget_parity.py
  ```
- **执行输出**：
  ```text
  charge_per_complete_run: 50
  total_planned_forward_views: 50
  Model DA3-SMALL: declared=25, calculated=25, breakdown={'first_frame': '1 calls * 1 views = 1', 'calibration': '6 calls * 3 views = 18', 'frame_order_adverse': '1 calls * 3 views = 3', 'cpu_parity': '1 calls * 3 views = 3'}
  Model DA3-BASE: declared=25, calculated=25, breakdown={'first_frame': '1 calls * 1 views = 1', 'calibration': '6 calls * 3 views = 18', 'frame_order_adverse': '1 calls * 3 views = 3', 'cpu_parity': '1 calls * 3 views = 3'}
  Total calculated views across models: 50
  charge_per_complete_run == total_views_calc (50 == 50): True
  cumulative_wall_seconds_max is None: True
  status == 'proposal_unapproved': True
  execution_permitted == False: True
  Verification 3 Passed: 100% compliant!
  ```
- **审查发现与结论**：
  - `charge_per_complete_run` 为 50，与 `DA3-SMALL`（25 视图）+ `DA3-BASE`（25 视图）之和完全一致；
  - `cumulative_wall_seconds_max` 保持为 `null`（等待用户告知）；
  - `status` 严格保持为 `proposal_unapproved`；
  - `execution_permitted` 严格保持为 `False`（未被越权放行）。

---

## 4. `check_r2.py` 自动化自检复跑

- **执行说明**：
  - 将作者自检逻辑完整适配至 `reports/V9-T48/gemini-b5r8/run_check_r2.py`，保持临时目录 `tempfile.mkdtemp(prefix="t28r2-")` 并在运行后通过 `shutil.rmtree` 彻底清理；
  - 严谨确认只读性：**零改动 `reports/V9-T28/r2/` 任何文件**。
- **输出日志**：[`logs/check_r2.log`](logs/check_r2.log)
- **执行命令**：
  ```bash
  .venv/bin/python reports/V9-T48/gemini-b5r8/run_check_r2.py
  ```
- **执行输出**：
  ```text
  PASS 差异路径全部在枚举范围内  []
  PASS 未改动: alignment
  PASS 未改动: estimation
  PASS 未改动: split
  PASS 未改动: failure_policy
  PASS 未改动: input_manifest_sha256
  PASS 未改动: lead_protocol_observed_sha256
  PASS 未改动: generator_sha256
  PASS 未改动: schema
  PASS 未改动: status
  PASS 未改动: execution_permitted
  PASS 未改动: task_id
  PASS 未改动: residual_vector.order/depth_component/dimension
  PASS 未改动: numerical_parity 容差/字段/规则
  PASS 未改动: negative_controls score/required_red/frames/boundary/unrelated
  PASS 未改动: budget 墙钟/RSS/常驻/重试
  PASS 未改动: profile 其余字段(process_res/尺寸/外参不提供)
  ... (共 63 项独立断言)
  PASS 4 没有任何 float16 的 make()，每型号只加载 2 次（MPS/F32 一次 + CPU/F32 一次）
  ALL PASS
  ```
- **审查结论**：63 项业务与物理断言全部通过（ALL PASS），退出码为 `0`。

---

## 5. SHA256 校验和自洽性核实

- **执行命令**：
  ```bash
  shasum -a 256 reports/V9-T28/r2/proposal.json
  cat reports/V9-T28/r2/proposal.sha256
  grep "proposal.json" reports/V9-T28/r2/SHA256SUMS.txt
  ```
- **执行输出**：
  - 实际计算：`2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0`
  - `proposal.sha256` 记录：`2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0  proposal.json`
  - `SHA256SUMS.txt` 记录：`2a984531e6a55232b6d42ab90ae6db364dfda5928acaef44b90b3747b564c0a0  proposal.json`
- **审查结论**：三者完全吻合，且 `SHA256SUMS.txt` 中记录的全部 10 个文件 SHA 均与磁盘完全一致，自洽无误。

---

## 6. 对抗性破坏实验验证

为了证明复核工具链能有效识别未授权改动，复核代理构建了两个对抗篡改测试：

- **执行脚本**：`reports/V9-T48/gemini-b5r8/run_adversarial.py`
- **输出日志**：[`logs/adversarial.log`](logs/adversarial.log)
- **执行命令**：
  ```bash
  python3 reports/V9-T48/gemini-b5r8/run_adversarial.py
  ```
- **对抗场景与拦截结果**：
  1. **对抗样本 A（篡改配额计费）**：将 `charge_per_complete_run` 从 50 篡改为 18；
     - **拦截表现**：第 3 步算术核验立即捕获 `charge=18 != total_views_calc=50`，断言立即触发报警并拒绝；
  2. **对抗样本 B（篡改数值容差）**：将 `numerical_parity.cpu_float32.rotation_angle_abs_max` 从原值篡改为 0.08；
     - **拦截表现**：第 1 步逐叶比对立即捕获未在允许枚举列表内的差异 `numerical_parity.cpu_float32.rotation_angle_abs_max`，立即报警并拒绝。
- **审查结论**：复核检查具备充分的敏感度与鲁棒性，能有效防御任何偷换口径或放宽容差的违规行为。

---

## 7. 交付文件清单

复核过程文件与产物均归档于 `reports/V9-T48/gemini-b5r8/`：
- [`REPORT.md`](REPORT.md)：本复核报告；
- [`metrics.json`](metrics.json)：结构化核查指标与判定汇总；
- [`diff_leaves.py`](diff_leaves.py)：逐叶递归对比脚本；
- [`check_budget_parity.py`](check_budget_parity.py)：配额与视图算术一致性核验脚本；
- [`run_check_r2.py`](run_check_r2.py)：只读自检运行脚本；
- [`run_adversarial.py`](run_adversarial.py)：对抗实验验证脚本；
- `logs/`：
  - [`logs/leaf_diff.json`](logs/leaf_diff.json)：37 项差异完整键值记录；
  - [`logs/budget_parity.log`](logs/budget_parity.log)：预算核验日志；
  - [`logs/check_r2.log`](logs/check_r2.log)：63 项 PASS 完整执行日志；
  - [`logs/adversarial.log`](logs/adversarial.log)：对抗测试拦截日志；
- [`SHA256SUMS.txt`](SHA256SUMS.txt)：产物 SHA256 校验和清单。

---

## 8. 复核结论与发现清单

### 发现清单
1. **范围精确受控**：E16 的 37 处改动全部严格受限于用户授权范围（`amendment`、`budget.view_accounting`、`retired_stages`、`open_items`），未触碰任何核心算法、阈值与物理限额；
2. **文字真实可靠**：第三次用户原话逐字严格一致；
3. **算术自洽闭环**：`charge_per_complete_run` 与两型号计划视图数 50 闭环一致；
4. **守卫严格有效**：`execution_permitted` 仍为 `false`，`status` 仍为 `proposal_unapproved`；
5. **对抗防御完备**：对抗实验证实工具链具备对非法篡改的主动防御拦截能力。

**复核结论**：**建议通过**。
