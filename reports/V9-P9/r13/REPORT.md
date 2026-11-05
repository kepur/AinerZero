# ainerzero.V9.P38 执行报告（S1 预登记 r13：新实验 ID 重冻结）

环境说明：运行于宿主非沙箱环境（`ps` 可用，`python 3.12.4`，全量 `tests/v9` 726 项已实跑完成：725 passed / 1 已知真实台账断言失败）。
角色：executor（二级执行层）；负责人：`geminiflash-9a7c`（Gemini-3.8-Flash）；时间：2026-10-24 22:20 +0300
任务状态：reported（待统筹验收）；实验状态：未执行真实训练/评测（纯 CPU 预登记冻结卡）
任务依据：AinerZero/RESEARCH_LOG.md `## R20261024-S1-phase1-r13-budget`（用户 10-24 批准 r13 重冻结，方案 A 同值）
输入身份：`reports/V9-P9/r13/evidence/sha256sums.txt`；前值归档 `reports/V9-P9/r13/before/`
参数：v0（照用不改）

## 摘要（30 行内）

- **承接与背景**：S1 r12 阶段由于主机两次休眠未全部完成（3/9 训练完成，2 失败，窗口已关）。用户批准以方案 A 相同值开启 r13。本卡完成 r13 新实验身份登记与预登记重冻结。
- **新实验身份**：`s1-phase1-20261024-r13`；`spec.R13_EXPERIMENT_ID` 新增，`R11_*`、`R12_*` 保留为历史；`REGISTERED_EXPERIMENT_IDS=(r11, r12, r13)` 纳入当前身份；历史台账行、attempt、失败记录原样保留，不归还额度。
- **最小改动**：源码仅在 `spec.py` 登记 r13 常量并设为 `CURRENT_EXPERIMENT_ID`，不改任何门槛或判定。既有测试中仅更新 `test_s1_r12_registration.py` 中 1 处「当前身份 = r12」断言为 r13（行 61 与行 70）。新增 `test_s1_r13_registration.py`（6 passed）。
- **重冻结产物**：输出至 `artifacts/v9/s1/phase1/r13/`，经现行 `--mode freeze` 生成：document SHA `1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30`，file SHA `9868b913d3cea59acc860e17b6362afcbbb746990e0ddb4962bc6b78123e0f0d`，状态 `awaiting_coordinator_approval`，`reverified=true`。
- **叶差异**：总计 431 叶，仅 5 叶变化（`experiment_id`、`created_unix`、`spec.py` 源码 SHA、`package_map_digest`、`spec.sha256`）；白名单外差异为 **0**；3510 / 1200 / 1250 / 175 / 种子 / 数据 / 指标 / 注记 / arms **完全全等**。
- **隔离入口检查**：整个 `artifacts/v9/s1/phase1` 拷贝至临时 host 隔离执行。`verify` completed（source_binding=passed、approval=false）；`train` 拒绝于 `preregistration_not_approved`；`eval` 拒绝于 `eval_binding_unavailable`。三次操作前后副本台账 SHA 完全不变。生产 output-root 零入口调用。
- **生产台账核实**：开工 `6b604983b5d1c944bdfe814fd0d72cb7b768c8b8a23f422607f946ce341b3f44`，收尾 `6b604983b5d1c944bdfe814fd0d72cb7b768c8b8a23f422607f946ce341b3f44`，两次一致且完全等于卡面登记值；`eval_report.json` 同样保持不变（`4d958d1a…`）。
- **全量测试对账**：`test_s1_r12_ordering.py` 10 passed；`test_s1_r12_registration.py` 6 passed；`test_s1_r13_registration.py` 6 passed；`tests/v9/experiments` 347 passed / 1 failed（已知既有失败：`test_s1_r7_phase_accounting.py::test_the_real_ledger_copy…`）；`tests/v9`（排除 experiments）378 passed。总计 725 passed。
- **范围外严格遵守**：未运行 MLX、真实训练、评测；未写入批准行；未修改 RunStore；未对生产 output-root 发起任何入口调用。

---

## 一、修改文件清单与改动说明

| 文件 | 改动性质 | 说明 |
|---|---|---|
| `src/ainerzero/v9/experiments/s1/spec.py` | 源码最小改动 | 新增 `R13_EXPERIMENT_ID = "s1-phase1-20261024-r13"`；`REGISTERED_EXPERIMENT_IDS` 追加 `R13_EXPERIMENT_ID`；`CURRENT_EXPERIMENT_ID` 设为 `R13_EXPERIMENT_ID`。`R11_*`、`R12_*` 保留。 |
| `tests/v9/experiments/test_s1_r12_registration.py` | 既有测试同步 | 仅将 `test_the_current_registration_defaults_to_r12` 中对当前默认身份的断言更新为 r13（第 61 行与 70 行），保留其它所有断言。 |
| `tests/v9/experiments/test_s1_r13_registration.py` | 新增测试 | 覆盖 r13 身份规则、三代已登记身份兼容性、拒绝未登记身份、守卫作用域、登记值全等、r12→r13 叶差异。共 6 项测试全部通过。 |
| `artifacts/v9/s1/phase1/r13/` | 预登记产物目录 | 生成 `draft_preregistration.json`、`pre_registration.json`、`pre_registration.json.sha256`、`dataset_ref.json`。 |
| `reports/V9-P9/r13/` | 审计与交付证据 | 包含 `before/` 备份、`harness/` 工具集、`logs/` 执行日志、`evidence/sha256sums.txt`、`prereg-leaf-diff.json`、`指标.json` 与本报告。 |

---

## 二、r12 → r13 叶差异详细审计

运行 `reports/V9-P9/r13/harness/prereg_leaf_diff.py` 产出对比结果：
- 总叶数：431
- 变更叶数：5
- **白名单外变更数：0**
- 5 项变更叶详情：
  1. `created_unix`：时间戳更新（`1792764872.80` → `1792869405.75`）
  2. `experiment_id`：身份更新（`s1-phase1-20261023-r12` → `s1-phase1-20261024-r13`）
  3. `source_identity.package_files.src/ainerzero/v9/experiments/s1/spec.py`：源码散列更新
  4. `source_identity.package_map_digest`：源码包清单散列更新
  5. `source_identity.spec.sha256`：spec 散列更新
- **全等核对**：
  - `training_protocol.updates` = 3510
  - `timing.deadline_seconds` = 1200
  - `timing.supervision_seconds` = 1250
  - `training_protocol.eval_batches` = 175
  - `training_protocol.seeds` = [0, 1, 2]
  - `timing.phase_wall_max_seconds` = 14400
  - `data_identity.dataset_digest` = `8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`
  - `arms`、`evaluation`、`metrics`、`stop_rules` 完全一致。

---

## 三、隔离副本入口实测与台账零改动验证

通过 `reports/V9-P9/r13/harness/entry_checks.py` 执行全隔离测试：
1. **生产台账基线记录**：
   - `artifacts/v9/s1/phase1/control.sqlite3` SHA256：`6b604983b5d1c944bdfe814fd0d72cb7b768c8b8a23f422607f946ce341b3f44`
   - `artifacts/v9/s1/phase1/eval_report.json` SHA256：`4d958d1ad59db1a897245d1acb000dda14a4db08dd0ccb069760061511e0c2cc`
2. **隔离副本 CLI 测试**：
   - `verify`：status=`completed`，`preregistration_sha256=1cb98a21…`，`source_binding=passed`，`approval_approved=false`
   - `train`：refused_stage=`output_root_not_canonical`，exit code=3
   - `eval`：refused_stage=`output_root_not_canonical`，exit code=3
   - 副本 `control.sqlite3` SHA256 在 CLI 运行前后完全不变（`6b604983…`）
3. **隔离副本 declared-host 状态前置条件实测**：
   - `train`：refused_stage=`preregistration_not_approved`（无 r13 批准行，在写台账前坚决拒绝）
   - `eval`：refused_stage=`eval_binding_unavailable`（无 r13 绑定的已完成训练 run，在写台账前坚决拒绝）
   - 副本 `control.sqlite3` SHA256 在此两次 worker 调用前后完全不变（`6b604983…`）
4. **收尾生产台账核实**：
   - 生产 `control.sqlite3` SHA256：`6b604983b5d1c944bdfe814fd0d72cb7b768c8b8a23f422607f946ce341b3f44`（完全未动）
   - 生产 `eval_report.json` SHA256：`4d958d1ad59db1a897245d1acb000dda14a4db08dd0ccb069760061511e0c2cc`（完全未动）

---

## 四、测试与回归汇总

| 测试套件 | 通过数 | 失败数 | 说明 |
|---|---|---|---|
| `test_s1_r12_ordering.py` | 10 | 0 | r12 顺序守卫及 9 个零写入分支完全通过 |
| `test_s1_r12_registration.py` | 6 | 0 | 既有 r12 登记测试通过 |
| `test_s1_r13_registration.py` | 6 | 0 | 新增 r13 身份、规则与叶差异测试通过 |
| `tests/v9/experiments` | 347 | 1 | 仅 1 项已知既有失败：`test_s1_r7_phase_accounting.py::test_the_real_ledger_copy…`（旧断言读实时台账；按任务说明保留不改） |
| `tests/v9`（排除 experiments） | 378 | 0 | 全部通过 |
| **全量总计** | **725** | **1** | 与改动前基线完全一致，未引入任何新失败 |

---

## 交付文件清单
1. 预登记冻结文件：`artifacts/v9/s1/phase1/r13/pre_registration.json`
2. 校验文件：`artifacts/v9/s1/phase1/r13/pre_registration.json.sha256`
3. 预登记草稿：`artifacts/v9/s1/phase1/r13/draft_preregistration.json`
4. 数据集引用：`artifacts/v9/s1/phase1/r13/dataset_ref.json`
5. 测试用例：`tests/v9/experiments/test_s1_r13_registration.py`
6. 叶差异证据：`reports/V9-P9/r13/prereg-leaf-diff.json`
7. 审计台账：`reports/V9-P9/r13/指标.json`
8. 散列汇总：`reports/V9-P9/r13/evidence/sha256sums.txt`
9. 隔离测试日志：`reports/V9-P9/r13/logs/entry-checks.json`
10. 前值归档：`reports/V9-P9/r13/before/`

## 交回统筹
- r13 预登记已在纯 CPU 流程下合规重冻结，白名单外无任何科学或配置漂移。
- 生产环境台账零改动，隔离副本上的拒绝与零写入均获证实。
- 等待一级统筹（Codex / Claude）与非作者复核。
