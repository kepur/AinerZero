# ainerzero.V9.P54 执行报告：S1 r15 修复与重冻结独立复核（复核 P53）

- **角色**：executor（二级独立复核）；**负责人**：`gemini-b4e7`；**时间**：2026-10-28
- **任务状态**：reported；**裁决结论**：**建议通过**
- **复核目标**：`ainerzero.V9.P53`（作者：一级 `claude`）
- **复核人身份**：`gemini-b4e7`（二级执行层，kind: gemini），全新独立外部会话，非 P53 作者，未列于 excluded_agents 排除名单。
- **纯只读复核**：生产台账只做 shasum，未直接写入任何生产台账或运行文件；所有测试、对抗破坏及真实评测均在临时隔离目录（`reports/V9-P54/gemini-b4e7/` 下及 tempdir）中进行。

---

## 1. 生产台账零写入与身份冻结
- **生产台账路径**：`artifacts/v9/s1/phase1/control.sqlite3`
  - 开工 SHA256：`b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`evidence/production-ledger-start.txt`）
  - 收尾 SHA256：`b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`evidence/production-ledger-end.txt`）
  - 生产台账全程保持 0 写入。
- **实验身份**：`s1-phase1-20261028-r15`（当前身份），r11–r14 为已登记历史。
- **冻结预登记路径**：`artifacts/v9/s1/phase1/r15/pre_registration.json`
  - **file SHA256**：`361e57f3f78fb2e0d76a0ed5980662da851f56d97de523c979d87a33361ee75d`
  - **document SHA256**：`2174de670c844535ce63795a23ba4b413ad70ef3f1c2cf7a929b3de5bb5a99f9`
  - 两个 SHA 与 P53 报告及卡面完全吻合。

---

## 2. 叶差异白名单与数学等价性
1. **r14 → r15 逐叶差异**（`harness/prereg_leaf_diff.py` → `logs/prereg-leaf-diff.json`）：
   - 共 56 叶变化，**白名单外意外叶子为 0**（`unexpected: []`）。
   - 外部 10 叶均为身份与文件来源绑定变动，新增 46 叶完全位于多来源 `inheritance` 节。
   - `arms`、`evaluation`、`metrics`、`stop_rules`、`training_protocol`、`data_identity`、`resource_limits` 七大科学节与 `effective_metadata` 与 r14 完全逐位等价。
2. **训练数学与切片修复等价性**（`harness/equivalence_checks.py` → `logs/equivalence.json`）：
   - 在 r14 树上，切片型 few-shot 测试抛出 `ValueError: matmul … size 5 is different from 2`（成功复现 r14 缺陷）；
   - 在 r15 树上，切片型 few-shot 测试顺利 `completed`；
   - 真实 MLX 下 arm2/arm3/arm4 seed 0 的窗口探针损失，在 r14 与 r15 源码树下**十六进制浮点数逐位完全相同**（训练数学严格未受任何影响）。

---

## 3. 隔离副本入口检查（12/12 全部通过）
复跑 `harness/entry_checks.py`（产物见 `logs/entry-checks.json`）：
- CLI verify 为 completed，source_binding 通过，未获批准；CLI train/eval 拒绝退出；
- 未批准的 arm4 s0 训练与评测均被前置守卫拦截拒止；
- 继承的 8 个格（r13 三格、r14 五格）在批准副本日志下均被拒绝为 `inherited_cell_not_trainable`（先判后拒，台账零写入）；
- 只读绑定 8/8 均正确解析到各自所属的源实验与源 run，未继承的 arm4 s0 拒绝绑定；
- 在副本台账中真实运行 arm2 s0、arm3 s1、arm4 s2 评测，全部 `completed`。

---

## 4. 独立对抗性检查（Adversarial Mutant Checks）
按 P54 要求，本执行者另行设计并执行了独立对抗变异验证（产物见 `adversarial/`）：
1. **切片函数改坏测试（变异 1）**：
   - 在源码副本中篡改 `spec.memory_key_slices`：将 `arm3` probe 切片由 `(0, place_dim)` 故意改错为完整 hidden 维度 `(0, hidden)`（复现维度失配）。
   - 运行 `pytest tests/v9/experiments/test_s1_r15_registration.py -k test_probe_slices_match_the_stored_node_widths_not_hidden`。
   - **结果变红**：测试立即失败（`AssertionError: assert 192 == 32`），捕获日志记录于 `adversarial/mutant_pytest_failure.log`。
2. **查询接口未切片回退测试（变异 2）**：
   - 在源码副本中篡改 `evaluation.py`：将 `backend.probe_query` 强制回退为未切片的 `backend.encode`。
   - 运行 `pytest tests/v9/experiments/test_s1_r15_registration.py -k test_few_shot_with_a_sliced_memory_completes_through_probe_query`。
   - **结果变红**：测试立即失败（`ValueError: matmul ... (size 5 is different from 2)`），捕获日志记录于 `adversarial/mutant_eval_failure.log`。
   - 充分证明：作者的回归测试套件具有完全的拒止有效性，绝非形式空跑。
3. **隔离副本独立真实评测**：
   - 独立脚本 `evidence/run_standalone_evals.py` 在全新的隔离临时目录下对 3 个臂各运行一次真实评测：
     - `arm2 s0`（继承自 r13）：`completed`
     - `arm3 s1`（继承自 r14）：`completed`
     - `arm4 s2`（继承自 r14）：`completed`
   - 确认各臂评测已彻底摆脱维度失配问题，结果记录于 `evidence/standalone_eval_results.json`。

---

## 5. 测试套件回归
- `tests/v9/experiments/test_s1_r15_registration.py`：15/15 全部通过。
- 全量 `tests/v9` 套件：978 通过，3 项已知历史用例失败（与 P38/P49/P51 相同）。

---

## 6. 最终结论
r15 的切片修复确凿有效且不影响训练数学，多来源继承机制健全，对抗变异测试变红验证充分，真实隔离评测全部成功。
**建议通过**（accept）。
