# ainerzero.V9.P50 执行报告：S1 r14 入口继承与重冻结独立复核（复核 P49）

- **角色**：executor（二级独立复核）；**负责人**：`gemini-b4e7`；**时间**：2026-10-28
- **任务状态**：reported；**裁决结论**：**建议通过**
- **复核目标**：`ainerzero.V9.P49`（作者：一级 `claude`）
- **复核人身份**：`gemini-b4e7`（二级执行层，kind: gemini），全新独立外部会话，非 P49 作者，未列于 excluded_agents 排除名单。
- **纯只读复核**：未修改任何业务源码或生产台账，未运行真实训练/评测/MLX，所有复跑产物严格收敛于 `reports/V9-P50/gemini-b4e7/`。

---

## 1. 生产台账零写入核验
- **生产台账路径**：`artifacts/v9/s1/phase1/control.sqlite3`
- **开工 SHA256**：`fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`（记录于 `evidence/production-ledger-start.txt`）
- **收尾 SHA256**：`fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`（记录于 `evidence/production-ledger-end.txt`）
- **结论**：开工与收尾 SHA256 逐位一致，生产台账全程保持 0 写入。

---

## 2. 身份与预登记冻结核验
- **实验身份**：`s1-phase1-20261028-r14`（当前身份），r11–r13 为已登记历史。
- **冻结预登记路径**：`artifacts/v9/s1/phase1/r14/pre_registration.json`
  - **file SHA256**：`14e2aeda943f134c262b227ae8c5c2f08c5b794f8eb5c88ccfdf29d607185e54`
  - **document SHA256**：`e28c49cd5652fb26b09d2555189269183093f550331ef54c1d1fe8b65ec3c7a2`
- 与 P49 报告及卡面完全吻合。

---

## 3. r13 → r14 逐叶差异核验（白名单审计）
复跑独立 harness `harness/prereg_leaf_diff.py`（产物见 `logs/prereg-leaf-diff.json`）：
- **全量叶子节点数**：新预登记共 126 叶。
- **差异叶子总数**：29 叶。
- **白名单外意外叶子**：**0 项**（`unexpected: []`）。
  - 非 inheritance 节 9 叶：`experiment_id`、`created_unix`、`effective_metadata.equivariant_source`（P47 验收表述修正）及 6 项源码绑定哈希（`source_identity.*`）。
  - inheritance 节 20 叶：完全收敛在新增的继承元数据内。
- **核心科学节全等验证**：`arms`、`evaluation`、`metrics`、`stop_rules`、`training_protocol`、`data_identity`、`resource_limits` 七大节与 r13 完全逐字节等价。

---

## 4. 隔离副本入口检查（三检 10/10 通过）
复跑独立 harness `harness/entry_checks.py`（产物见 `logs/entry-checks.json`），在纯临时目录副本中执行全流程检查：
1. `production_untouched`: 生产台账未受任何污染（True）。
2. `cli_copy_ledger_untouched`: CLI 操作前后临时副本台账保持不变（True）。
3. `verify_completed_binding_passed_not_approved`: CLI verify 状态为 completed，source_binding 通过，未获批准（True）。
4. `cli_train_eval_refused`: CLI train/eval 均因非 canonical output root 拒绝退出（True）。
5. `worker_unapproved_train_refused`: 未批准训练被 `preregistration_not_approved` 拒绝（True）。
6. `worker_eval_non_inherited_refused`: 未继承格评测被 `eval_binding_unavailable` 拒绝（True）。
7. `inherited_cells_not_trainable`: 在副本日志临时批准下，继承的三格（arm2 s0、arm2 s1、arm3 s0）均被守卫拦截并拒绝为 `inherited_cell_not_trainable`，在写入台账前退出（True）。
8. `inherited_cells_bind_registered_runs`: 只读评测前置中，继承三格正确绑定到已登记的 r13 成果（arm2 s0 → `19f2d1eb…`，arm2 s1 → `7d155060…`，arm3 s0 → `403ae816…`）（True）。
9. `non_inherited_cells_refuse_binding`: 未继承格（arm2 s2、arm4 s0）拒绝绑定（True）。
10. `copy_ledger_untouched_by_worker`: worker 所有被拒尝试前后，副本台账哈希完全未变（True）。

---

## 5. 继承规则与全套坏对照审计（27/27 全部通过）
独立运行 `tests/v9/experiments/test_s1_r14_registration.py`：
- **继承先判后写与零写入**：`test_train_refuses_an_inherited_cell_and_writes_nothing` 验证继承格被拒时台账哈希前后绝对不变，对照非继承格正常越过该门走向后续检查。
- **坏对照全面拒绝**：
  - 错误 run_id：拒绝（`not the registered source run`）；
  - 错误 SHA：拒绝（`does not equal the registered`）；
  - 错误源实验：拒绝（`belongs to experiment`）；
  - 错误源预登记：拒绝（`no completed run binds`）；
  - 私自篡改文档节：拒绝（`no completed run binds`）；
  - 篡改检查点文件：拒绝（`does not match the original receipt SHA`）；
  - 9 种畸形结构字段（错臂、重复格、错字符集、空列表等）：全部被结构校验拒绝；
  - 篡改继承节/缺失继承节/外来继承节：全部被 `prereg.validate` 拒绝。

---

## 6. 测试套件回归
- `tests/v9/experiments/test_s1_r14_registration.py`：27 passed。
- `tests/v9/experiments/` 全量套件：374 passed，1 failed（`test_s1_r7_phase_accounting.py::test_the_real_ledger_copy…` 为已登记的实时台账预期历史旧用例，已知且符合预期，日志见 `evidence/pytest-experiments.log`）。

---

## 7. 最终结论
各项指标与证据完全符合 P49 卡面与冻结协议要求，台账零写入、继承先判后写与坏对照均有效拒止，叶差异与三检均绿。
**建议通过**（accept）。
