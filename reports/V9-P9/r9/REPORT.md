# ainerzero.V9.P15 执行报告（S1 入口 r9：R1 共享实验注册 + R2 完成前置条件）

角色：executor（二级执行层）；负责人：`deepseek-v41f-r9x2`；时间：2026-10-22
任务状态：reported（未 accepted）；实验状态：未执行真实训练/评测（本卡为 CPU 工程卡）
任务依据：`claude-20261022-e32/P15-R8-DECISION.md`（只修 R1、R2）；`S1-R8-DECISION.md` 的冻结参数与禁止项不变
输入身份：`reports/V9-P9/r9/source-identity.json`（21 个绑定文件，0 漂移）；`provenance/STARTING-BYTES.json`（r8 起始字节）

## 摘要（30 行内）

- **只做了裁决要求的两项**。r8/P24 原件、r8 冻结、`RESEARCH_LOG.md`、中央台账、通用 `RunStore` 全部未动（逐字节核对，见 §1）。
- **R1 已修**：新增 `worker.ensure_shared_experiment()`，D（`open_aux_run`）与训练（`_open_train_run`）都走"取到或创建"；已存在时比对存量 `manifest_hash` 与本次 manifest 的规范摘要，不等则 fail-closed（`ExperimentManifestMismatch`），两条路径都转成 `status=refused` 报告。先 D 后 train、先 train 后 D 现在都在**同一个实验 ID** 下注册成功，2 s / 450 s 各归各的运行预算。
- **R2 已修**：新增 `worker._completion_precondition()`，`_complete_run` 进入时若已有失效标记，或账本已是 `completed` 以外的终态，就拒绝并**如实报告账本状态**；不删标记、不改终态行、不退款、不新造标记。
- 证据：两种顺序 + 外来 manifest 双拒 + 拆守卫坏控（`evidence/shared-experiment.json`）；P24 F1 双调用复探（before/after/无标记终态）+ 拆守卫坏控（`evidence/completion-precondition.json`）。
- 测试：新增 9 条（5 + 4），`tests/v9/experiments` 300 passed，其余 `tests/v9` 378 passed，0 失败。
- 冻结：`artifacts/v9/s1/phase1/r9/`，doc `6abce031…5577`，file `1afc4900…1572`，状态 `awaiting_coordinator_approval`；398 叶中只变 3 叶（`created_unix`、`source_identity.package_map_digest`、`package_files.worker.py`），科学字段 0 变化，绑定文件白名单外 0 个。
- 未执行：真实 MLX 前向/训练/评测/final、新数据、下载安装、批准行、中央台账、P1。D 的真实成本仍未知。
- 交回：等 P25 非作者独审；r9 冻结需一级批准后才可谈 P1。**工程绿不等于能力通过。**

## 1. 起始对账（先做，未覆盖任何旧证据）

- `provenance/STARTING-BYTES.json`：r8 冻结绑定的 21 个文件逐字节重算，**0 漂移**；r8 冻结 5 个文件、r8 报告 17 个文件全部入库留档。
- 收工复核：r8 冻结与 r8 报告 **0 改动**；21 个绑定文件中本卡期间只有 `worker.py` 变化（即本卡唯一编辑的源码）。
- 未发现他人并发写入本卡 scope；`git status` 中 `cli.py`、`geometry/*` 的改动早于本卡，不是本卡产生。

## 2. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P9/r9/harness/archive_starting_bytes.py
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r9/logs/tests-s1-r9.xml
.venv/bin/python -m pytest tests/v9 -q -p no:cacheprovider --ignore=tests/v9/experiments \
  --junitxml=reports/V9-P9/r9/logs/tests-v9-other-r9.xml
.venv/bin/python reports/V9-P9/r9/harness/refreeze_draft.py
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r9 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1/r9
.venv/bin/python reports/V9-P9/r9/harness/prereg_leaf_diff.py
.venv/bin/python reports/V9-P9/r9/harness/source_identity.py
.venv/bin/python reports/V9-P9/r9/harness/shared_experiment_evidence.py
.venv/bin/python reports/V9-P9/r9/harness/completion_evidence.py
.venv/bin/python reports/V9-P9/r9/harness/collect_evidence.py
```

环境说明：WorkBuddy 的 Python shim 会把 `mkdir(exist_ok=True)` 落在 symlink 上误报 `PermissionError`，因此测试以 `PYTHONPATH=<repo>/src` 运行（不加载 shim）。源码与测试未为迁就环境改动。

## 3. R1：共享 TRAIN 实验的"取到或创建"

代码（`worker.py`）：

- `_canonical_manifest_digest()`：与 `RunStore.create_experiment` 同构的规范摘要（sorted/compact JSON 的 SHA256）。
- `_manifest_digest_matches()`：唯一一处"是否可复用"的比较，单独成函数以便坏控只删这一处。
- `ensure_shared_experiment(store, manifest=…, request_id=…, experiment_id=…)`：
  实验不存在 → 创建；存在 → 摘要相等才复用，否则 `ExperimentManifestMismatch`；并发插入（`LifecycleError`）时重读再比对，不盲目重试。
- `PrepLedger.open_aux_run`（D 路径）与 `_open_train_run`（训练路径）都改走它；两处调用点把 mismatch 转成 `status=refused`、`refused_stage=train_experiment_manifest_mismatch`，不再冒泡成 `failed`。
- 通用 `RunStore` 未改：没有新实验 ID、没有重置尝试次数或总账、`request_id` 保护未放宽。

证据（`evidence/shared-experiment.json`，临时卡内 RunStore，不碰中央台账）：

| 场景 | 结果 |
|---|---|
| A 先 D 后 train | 两 run 同属 `s1-phase1-20261021`，预算 2.0 s / 450.0 s，无异常 |
| B 先 train 后 D | 同上，同一实验 ID |
| C 同 ID + 不同 manifest 预建 | D 与 train 都 `ExperimentManifestMismatch`（附完整错误文本），且没有新增 run 行 |
| D 坏控（只删摘要比较） | D 复用了外来实验并成功注册 → 证明拒绝来自该比较 |

测试：`test_s1_r9_shared_experiment.py` 5 条，覆盖两种顺序（走真实 `run_worker` + CPU 替身，`phase_ledger_breakdown` 同时看到 D 与 train 两行）、外来 manifest 双拒、坏控、以及 helper 幂等单元用例。

## 4. R2：`_complete_run` 的完成前置条件

代码（`worker.py`）：`_completion_precondition()` 在 `_complete_run` 最前面执行——

- 已有 `completion_invalid*.json` → `status=refused`、`refused_stage=completion_already_invalid`；
- 账本终态且不是 `completed` → `refused_stage=ledger_terminal_not_completed`；
- 否则继续（无标记的 `completed` 行重读仍允许，因为它什么都不改）。

报告如实带 `ledger_state`、`ledger_state_is_completed`、`completion_invalid_markers`、`rolled_back=false`；不写新标记、不重写终态。

证据（`evidence/completion-precondition.json`）：

| 场景 | 第二次调用的结果 | 账本 |
|---|---|---|
| before 截断点（首次已拒） | `refused / completion_already_invalid` | `failed`（未变），标记仍 1 个 |
| after 截断点（行已 completed） | `refused / completion_already_invalid` | `completed`（未改写） |
| 无标记的终态 `failed` | `refused / ledger_terminal_not_completed` | `failed` |
| 坏控（删掉前置条件） | 报 `completed` 而行仍是 `failed` → P24 F1 缺陷复现 | `failed` |

测试：`test_s1_r9_completion_precondition.py` 4 条，逐条对应上表。

## 5. 验证结果

- `tests/v9/experiments`：**300 passed**（291 旧 + 9 新），0 failed/skipped（`logs/tests-s1-r9.xml`）。
- 其余 `tests/v9`（geometry/contracts/teachers/tokenization）：**378 passed**，0 failed（`logs/tests-v9-other-r9.xml`）。
- 冻结复验：`--mode verify` completed，doc `6abce031f00fa1fc042bd6475101462b08856cedecf4f4c86c6e2eb326be5577`；状态 `awaiting_coordinator_approval`。
- 冻结参数不变：3510 updates / 三种子 0,1,2 / 450 s / arm1 2 s / eval_batches 48 / phase 14400 s / checkpoint 0,439,878,1755,3510。
- 叶差异：398 叶，3 叶变化，白名单外 0；绑定文件只有 `worker.py` 变化，白名单外 0。
- 预算：本卡未消耗任何训练/评测预算；未写中央台账，因此没有预留与实际完成的台账数。

## 6. 产物

- 报告：本文件、`metrics.json`、`source-identity.json`、`prereg-leaf-diff.json`
- 证据：`evidence/shared-experiment.json`、`evidence/completion-precondition.json`、`evidence/r9-tests.json`
- 日志：`logs/tests-s1-r9.xml`、`logs/tests-v9-other-r9.xml`
- 冻结：`artifacts/v9/s1/phase1/r9/{pre_registration.json,.sha256,draft_preregistration.json,dataset_ref.json}`
- 来源：`provenance/STARTING-BYTES.json`、`provenance/PROVENANCE.json`
- 复现脚本：`harness/*.py`（全部只写 `reports/V9-P9/r9/` 与 `.tmp/`）

## 7. 失败与限制

- 未运行真实 MLX 前向/训练/评测/final，未生成新数据，未下载/安装，未写批准行与中央台账，未启动 P1。
- D 的真实前向成本仍未知（沿用 2 s 冻结值，未实测）；本卡的 D 证据是 CPU 替身 + 冻结身份校验，不是能力证据。
- R2 的技术边界如实保留：本适配层不能撤销已提交的 SQLite 终态行，只能拒绝上报并让所有消费者拒绝该 run。
- 未做：真实锁竞争下的并发注册压测（只做了 `LifecycleError` 重读分支的代码路径覆盖，未构造多进程竞争）。
- 未验证：r9 冻结在真实 P1 训练下的端到端行为（本卡禁止）。

## 8. 交回统筹

1. r9 是否接受：R1/R2 各一条正向、一条反向、一条拆守卫坏控，证据与测试齐备。
2. 需要一级决定：是否批准 `artifacts/v9/s1/phase1/r9/` 这份冻结（本卡不写批准行）。
3. P25 非作者独审可开工；排除本卡作者 `deepseek-v41f-r9x2` 与全部 P15 历任作者。
