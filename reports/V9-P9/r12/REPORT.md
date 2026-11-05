# ainerzero.V9.P34 执行报告（S1 预登记 r12：新实验 ID ＋ 入口先判后写）

角色：executor（二级执行层）；负责人：`deepseek-p34x`（DeepSeek-V4.1-Flash）；时间：2026-10-23
任务状态：reported（未 accepted）；实验状态：未执行真实训练/评测（纯 CPU 工程卡）
任务依据：`RESEARCH_LOG ## R20261023-S1-phase1-r11-budget`（用户批准方案 A）＋ 一级裁定
`AinerRelay/reports/coordination/claude-20261022-e32/P31-LEDGER-INCIDENT-RULING.md`
输入身份：`reports/V9-P9/r12/evidence/sha256sums.txt`；前值归档 `reports/V9-P9/r12/before/`
参数：v2（照用不改）

## 摘要（30 行内）

- **承接**：上一棒 `claude-opus-e87n` 两次主动释放（按卡面 `excluded_agents` 自判为 Claude，未读写文件）。本棒从零开始，无半成品可接。
- **新实验身份**：`s1-phase1-20261023-r12`；`spec.R12_EXPERIMENT_ID` 新增，`R11_*` 常量原样保留为历史；`REGISTERED_EXPERIMENT_IDS=(r11,r12)` 决定谁能走登记预算路径、谁的作用域守卫生效；旧实验 `s1-phase1-20261021` 与 r11 的台账行/attempt/失败记录一律未动。
- **顺序修复（承重）**：train 与 eval（arm1 的 D 路径、arm2/3/4）所有只需 CPU 的前置条件现在都在**第一次写台账之前**判定：批准行、源码绑定、预登记校验、数据集绑定、eval_batches 预算门、arm×seed 训练绑定、attempt 守卫、D 守卫、阶段墙钟。判定用台账的**只读快照**（SQLite backup API 复制到临时目录后用同一个 `PrepLedger` 打开），因为 `RunStore` 一打开就会重写台账字节；`PrepLedger` 只在放行后构造。只调顺序，未新增门、未改阈值。
- **唯一实质缺陷**：r5–r11 的 trainable eval 先 `open_aux_run`（建实验/建 run/begin_work/reserve）再由 `_evaluate_arm` 抛 `EvalBindingError`。现由 `_eval_binding_precondition`（同一个 `_bind_completed_run`）在写之前判定，拒绝返回 `refused_stage=eval_binding_unavailable`。
- **零写入证据**：新增 10 条测试逐个拒绝分支断言临时库 `control.sqlite3` 的 SHA 前后完全一致（含生产事故那条分支）；坏控在隔离副本里只拆这道顺序守卫 → 台账字节改变、状态非 refused，测试变红（产品代码无开关）。
- **重冻结**：`artifacts/v9/s1/phase1/r12/`，用现行冻结路径（`--mode freeze`）生成；doc `044d5599…18dd`，file `fe539209…9658`，状态 `awaiting_coordinator_approval`，`reverified=true`。
- **叶差异**：431 叶，仅 7 叶变化（`experiment_id`、`created_unix`、3 个绑定源文件哈希、`package_map_digest`、`spec.sha256`）；白名单外 **0**；3510/1200/1250/175/种子/数据/指标/注记/arms **全等**。
- **入口（只在隔离副本）**：复制整个 `artifacts/v9/s1/phase1` 到临时 host；`--output-root` 指向副本时 verify=completed、train/eval 被 `output_root_not_canonical` 拒绝（exit 3，台账零写入）；再把副本声明为 host 后跑真实入口，train 在 `preregistration_not_approved` 拒绝、eval 在 `eval_binding_unavailable` 拒绝，副本台账 SHA 三次一致。
- **生产台账**：开工 `36426891…b67d`，收尾 `36426891…b67d`，两次一致且等于卡面值；`eval_report.json` 同为 `4d958d1a…e0c2cc`。
- **测试**：r12 新增 16 条全过；`tests/v9/experiments` 335 passed / **7 failed**（与 before 树同一批：6 条本 shell 的 pytest tmpdir 沙箱 `EEXIST` + 1 条已知真实台账拷贝断言）；其余 `tests/v9` 378 passed。
- **未执行**：真实 MLX、训练、评测、写批准行、改 RunStore、对生产 output-root 跑任何入口。

## 1. 承接与起始对账

- 上一棒交接记录：两次「按卡面 excluded_agents 不能领」，未读写任何文件；本棒检查 `git status` 与本卡文件范围，无本任务的半成品代码或报告（`reports/V9-P9/r12/` 由本棒新建）。
- 前值归档：`reports/V9-P9/r12/before/`（4 个 src 文件 + 6 个测试文件 + `SHA256SUMS.txt`）。
- 生产台账开工/收尾各记一次：`36426891…b67d` / `36426891…b67d`。

## 2. 修改文件与理由

| 文件 | 改动 |
|---|---|
| `src/ainerzero/v9/experiments/s1/spec.py` | 新增 `R12_EXPERIMENT_ID`、`REGISTERED_EXPERIMENT_IDS`、`CURRENT_EXPERIMENT_ID`；`R11_*` 全部保留为历史 |
| `src/ainerzero/v9/experiments/s1/prereg.py` | `build_draft` 默认身份改为 r12；`build_frozen`/`validate` 接受 r11（历史）与 r12（现行），其它 id 一律拒 |
| `src/ainerzero/v9/experiments/s1/worker.py` | 新增 `ledger_read_snapshot()`（只读快照）与 `_eval_binding_precondition()`；`run_worker` 把 train/eval 的 CPU 前置条件全部前移，`PrepLedger` 改为放行后才构造；`document_experiment_scope` 覆盖两个已登记身份 |
| `tests/v9/experiments/test_s1_r12_ordering.py` | 新增：9 个拒绝分支的台账字节不变 + 1 个隔离副本坏控 |
| `tests/v9/experiments/test_s1_r12_registration.py` | 新增：r12 身份规则、登记值不变、r11→r12 叶差异 |
| `tests/v9/experiments/s1_testkit.py` | 新增 `stage_phase1_host()`（隔离 host + 合成数据集 + 冻结件 + 台账），供测试与坏控驱动共用 |
| `tests/v9/experiments/test_s1_timing_sequence.py` | 该用例 mock 掉 `_evaluate_arm` 且假训练 run 没有 completion receipt；eval 入口现在先判绑定，故同步 stub `_eval_binding_precondition`（真实绑定由 r5/r12 测试覆盖），注释已写明原因 |

`commands.py` 未改：CLI 侧本来就不写台账，隔离守卫（`output_root_not_canonical`）已在 worker 之前拦住越界根。

## 3. 顺序修复的具体做法

1. `ledger_read_snapshot(ledger_path)`：用 `sqlite3` 的 `mode=ro` + online backup 把台账复制到临时目录，再用**同一个** `PrepLedger` 打开副本。理由：`RunStore.__init__` 的 `_initialize` 会开事务并重写文件（实测「打开再关闭」SHA 就变），所以只读判定不能用 RunStore 直连生产台账。
2. train：`verify_frozen_file` → 批准行 → 源码绑定 → 数据集绑定 → arm/seed → （快照）attempt 守卫 + 阶段墙钟 → **放行后才 `PrepLedger(...)`** → `_open_train_run` → `begin_work`。
3. eval arm1（D 路径）：源码绑定 → D 身份校验 → （快照）D 守卫 → 冻结的 D 预算校验 → 放行后才写。
4. eval arm2/3/4：源码绑定 → 开发窗口 → eval_batches 预算门 → **（快照）`_bind_completed_run` 绑定判定** → 放行后才 `open_aux_run`。
5. 阶段墙钟：现有代码的判定是 `total_wall + deadline > phase_cap`（worker 与 CLI 各一处），本来就在写之前；本卡未新增「剩余墙钟 vs 最坏强杀时长」的新门（卡面禁止新增门），也没有改阈值。

## 4. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P9/r12/harness/refreeze_draft.py
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r12 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
.venv/bin/python reports/V9-P9/r12/harness/prereg_leaf_diff.py
.venv/bin/python reports/V9-P9/r12/harness/entry_checks.py
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider --basetemp=<fresh>
.venv/bin/python -m pytest tests/v9 -q -p no:cacheprovider --ignore=tests/v9/experiments --basetemp=<fresh>
```

`--basetemp` 用全新目录：本 shell 的 python 带一个会拦截 `mkdir` 的 shim，`exist_ok=True` 落在已存在目录上会抛 `EEXIST`（before 树同样失败，见 §6）。

## 5. 重冻结与叶差异

- 冻结路径：`refreeze_draft.py` 从 **r11 的 draft** 取科学行（arm 行、arm1 identity 键、data_identity、metrics、evaluation、stop_rules 全部原样），只重建登记字段与 `experiment_id`，再交给现行 `--mode freeze`。
- **是否沿用 r10/r11 的 arm 行：沿用 r11 的 arm 行。理由**：r11 与 r10 的 arm 行逐字节相同，且 r10 之后 `_arm_rows` 会重新生成 arm1 identity 键；用 `build_draft` 从零重排会让科学叶出现白名单外差异（r11 卡面已踩过）。沿用保证「r11→r12 只有身份/来源/时间」。
- 叶差异：431 叶 / 7 变化，`non_identity_leaves_outside_allowlist=[]`、`bound_files_outside_allowlist=[]`；`registered_values` 逐项相等，`data_identity`/`metrics`/`evaluation`/`stop_rules`/`arms` 全等。
- 冻结值：updates=3510、deadline=1200（`deadline_source=user_approved R20261023-S1-phase1-r11-budget`）、supervision=1250、eval_batches=175、seeds=[0,1,2]、checkpoint_updates=[0,439,878,1755,3510]、arm1_deadline=7、phase_wall=10854.605（≤14400）、per_run_cap=1200、query_limit=8、measured_throughput 与 r11 一致。

## 6. 验证结果

| 项目 | 结果 |
|---|---|
| `test_s1_r12_ordering.py` | **10 passed**（9 个拒绝分支 + 坏控） |
| `test_s1_r12_registration.py` | **6 passed** |
| `tests/v9/experiments` | **335 passed / 7 failed** |
| `tests/v9`（除 experiments） | **378 passed** |
| before 树对照（同 shell） | **319 passed / 7 failed** |

7 条失败与 before 树完全同一批，非本卡引入：

- 6 条 `test_s1_approval.py`(2)、`test_s1_train_gates.py`(4)：本 shell 的 python shim 拦截 `mkdir`，`Path.mkdir(exist_ok=True)` 落在 `canonical_root` fixture 造的 `phase1` 符号链接上抛 `PermissionError: EEXIST`（before 树同失败）。
- 1 条已知失败 `test_s1_r7_phase_accounting.py::test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original`：读实时生产台账，r10/r11 运行后 `conservative=5012.096` vs `reserved_based=2214.076`；按要求照实记录，**未修**。

零写入断言覆盖的分支：train 的 `preregistration_not_approved`、`source_binding_drift`、`dataset_identity_mismatch`、`already_attempted`、`phase_budget_exceeded`；eval 的 `source_binding_drift`、`eval_call_budget_exceeded`（190 vs 175）、`already_attempted`（D 守卫）、`eval_binding_unavailable`。每条都断言 `control.sqlite3` SHA 前后相同。

坏控（`test_the_ordering_guard_is_load_bearing_bad_control`）：同一冻结 host、同一驱动脚本、同一 Python，只换导入的源码树。真实树 → `refused / eval_binding_unavailable`、台账不变；隔离副本删掉 `_eval_binding_precondition` 调用后 → 状态 `failed`、`EvalBindingError`、**台账 SHA 改变**。产品代码里没有开关。

## 7. 入口检查（只在隔离副本）

| 入口 | 命令根 | 结果 |
|---|---|---|
| verify | 副本 | `completed`（exit 0），`source_binding=passed`（drifted=[]），`approval.approved=false`，final 未读 |
| train | 副本（`--output-root` 副本） | `refused / output_root_not_canonical`（exit 3），台账零写入 |
| eval | 副本（`--output-root` 副本） | `refused / output_root_not_canonical`（exit 3），台账零写入 |
| train | 副本声明为 host | `refused / preregistration_not_approved`（无 r12 批准行），台账零写入 |
| eval | 副本声明为 host | `refused / eval_binding_unavailable`，台账零写入 |

- 生产 output-root 从未被传给任何入口；生产 `control.sqlite3` 与 `eval_report.json` 前后 SHA 一致且等于卡面值。
- 副本台账三次记录（CLI 三模式后、worker train 后、worker eval 后）全为 `36426891…b67d`，即副本本身也没有被写入。
- 说明：卡面写「train（无批准行，应被拒）」——直接按卡面用 `--output-root` 指向副本时，r6 的隔离守卫先拒绝（`output_root_not_canonical`），这本身就是更强的零写入；批准门与绑定门由「副本声明为 host」的那一组真实入口验证（同一 `run_worker` 代码路径）。

## 8. SHA256（脚本直贴，完整见 `evidence/sha256sums.txt`）

```
33f750174f27848b8e806dee5b257fca2479e0f78ff2c0f438edb1028ff1b053  src/ainerzero/v9/experiments/s1/spec.py
018f33d4beb1a12645b476f03aa4bbe73a115c82ff95fdd1c85170bd93170755  src/ainerzero/v9/experiments/s1/prereg.py
873fc3760dc38ad41136aeffdf940f4859a7e5d90c857ac2117645fe548f8fc4  src/ainerzero/v9/experiments/s1/worker.py
c66e02c383a13ae30ad7ea509e2ad8f991200cdee1d528b7d58903d420cfb91a  src/ainerzero/v9/experiments/s1/commands.py
0af2a4bab1ec58c1648aedd2fa996b4463459d3210b323fba5ccce98c127f44f  tests/v9/experiments/test_s1_r12_ordering.py
ec792023593f1a408865737f1af3357397244d3895e06f4153bc69cdb7b2bfb2  tests/v9/experiments/test_s1_r12_registration.py
a0e6dd0c5705c9de686a73f0f53bdeceb8e45e101cb0c799980fab94ae3e9a98  tests/v9/experiments/test_s1_timing_sequence.py
ca4186c02b5f93e58aebb882929dc9901546cb41e493cb558ff94be27a113acc  tests/v9/experiments/s1_testkit.py
edbe050eb3ef41a11dc427061b9b3e072f587602e3ebb03ec68f2b8d68f1ace0  artifacts/v9/s1/phase1/r12/draft_preregistration.json
fe539209179e3c59405526880dc1ea8dffe5416d34e393cd86b5f0373ece9658  artifacts/v9/s1/phase1/r12/pre_registration.json
65f325b97b4a231207227659640ba7faa181fe24b9366e074f86364486d0ad23  artifacts/v9/s1/phase1/r12/pre_registration.json.sha256
3c9fd77953b94d87141c2ac896bd2470f46b952eee65a10e9eed34d4391c1047  artifacts/v9/s1/phase1/r12/dataset_ref.json
aeb8a7a800deab87bce08940489796edb0cc1949cde0f4999163f52decc1f105  artifacts/v9/s1/phase1/r11/pre_registration.json（未动）
36426891021c9bfcdb9cb25a3adef30f1d2dbfb3d84b3c124b908bd7aeadb67d  artifacts/v9/s1/phase1/control.sqlite3（未动）
4d958d1ad59db1a897245d1acb000dda14a4db08dd0ccb069760061511e0c2cc  artifacts/v9/s1/phase1/eval_report.json（未动）
044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd  DOCUMENT_SHA256(artifacts/v9/s1/phase1/r12/pre_registration.json)
```

## 9. 产物

- 冻结：`artifacts/v9/s1/phase1/r12/{pre_registration.json,.sha256,draft_preregistration.json,dataset_ref.json}`
- 报告：本文件、`指标.json`、`prereg-leaf-diff.json`、`evidence/sha256sums.txt`、`before/`
- 日志：`logs/freeze-r12.json`、`logs/entry-checks.json`
- harness：`harness/{refreeze_draft.py,prereg_leaf_diff.py,entry_checks.py}`

## 10. 失败与限制

- 未写批准行（禁止项）；r12 冻结状态仍是 `awaiting_coordinator_approval`，未执行训练/评测。
- 7 条测试失败如 §6 所述：6 条本 shell 环境（before 树同失败），1 条已知真实台账断言（未修，按卡面照实记录）。
- `test_s1_timing_sequence.py` 有改动（见 §2）：该用例的 mock 训练 run 没有 completion receipt，新的绑定前置条件必然拒绝，故同步 stub；真实绑定由 `test_s1_r5_ledger.py` 与 `test_s1_r12_ordering.py` 覆盖。若一级认为该改动不可接受，请指出，我按裁定回退。
- 未验证：真实 MLX 吞吐、真实训练/评测、r12 的批准后运行；工程绿 ≠ 能力通过。
- 生产目录在只读快照读取时可能出现/刷新 `control.sqlite3-wal/-shm`（SQLite WAL 语义），`control.sqlite3` 主文件字节未变。

## 11. 交回统筹

1. 请 P35 非作者复核本卡：顺序修复（`ledger_read_snapshot` + `_eval_binding_precondition`）、r12 冻结件（doc `044d5599…18dd`）、以及 `test_s1_timing_sequence.py` 的改动是否可接受。
2. 复核通过后由一级在 `## R20261021-P1-stageA-budget` 写 r12 批准行（本卡不写）；批准行落盘前 train 会一直 `preregistration_not_approved`。
3. r11 与旧实验的台账行、attempt、失败记录均未动，也未归还额度；是否放行 P32 正式运行由一级决定。
