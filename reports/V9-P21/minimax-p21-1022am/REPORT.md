# ainerzero.V9.P21 独立复核报告（非作者复核 · tier-2 · minimax-p21-1022am）

- 角色：二级执行层（非作者复核），agent `minimax-p21-1022am`，固定模型 `opencode/minimax-m3.1-flash-free`。
- 被复核对象：`ainerzero.V9.P15`（S1 入口 r7，作者 `gemini-b7m9` + `deepseek-r7xq`），冻结文档 `artifacts/v9/s1/phase1/r7/pre_registration.json`（document SHA `523a5b35…3d667`，文件 SHA `14c435ed…b2ed`）。
- 依据：`S1-R7-DECISION.md`、`P17-EVIDENCE-ADDENDUM.md`、`P15-r7-review-inputs.json`、`reports/V9-P9/r7/REPORT.md`。
- 文件范围：只写 `reports/V9-P21/minimax-p21-1022am/`；**未修改任何被审源码、测试、冻结文件、真实中央账本、RESEARCH_LOG 或 artifacts**。
- 约束：CPU 工程。无 MLX 导入、无模型前向/梯度/更新、无 train/eval CLI 真实运行、无下载/安装、无 git 提交、无生产 Relay/8790 变更。
- 证据目录：`reports/V9-P21/minimax-p21-1022am/evidence/*.json`（13 个）、`logs/`（pytest 日志与 JUnit）、`probes/`（14 个探针脚本，全部可复跑）。

## 0. 结论

**建议 Reject（不通过）**。r7 的三项裁决中，「宿主唯一锚」与「终态逐行保守计量」在本次独立复核中**基本成立**（计量有一处状态覆盖缺口）；但**「D 候选复验」这一项在真冻结文档下不可用**，且发现 3 个可复现的强制反例。按卡内口径「任何强制反例真实失败即 Reject，不写 ConditionalAccept 掩盖」，结论为 Reject：r7 冻结参数本身无问题（7 叶差异在允许清单内、科学值未动），缺陷在代码控制流。

强制缺陷（可复现，见 §3）：

| 编号 | 缺陷 | 证据 |
|---|---|---|
| **F1** | 终态 `completed` 提交不受 450 s 截止约束 | `evidence/09-train-control-flow.json` → `findings.finish_hole` |
| **F2** | r7 计量拒绝产品自身写入的 `collecting`/`validating`/`stopping` 状态 | `evidence/06-phase-scope.json` → `findings.product_written_states_refused` |
| **F3** | 真冻结文档下 arm1/D 评测入口**无法完成**（任何预算都不行） | `evidence/08-d-eval-path.json` → `cases.A/B` |
| **F4** | D 候选「只允许 1 次评测」守卫失效（arm1 行未登记 arm_id） | `evidence/08-d-eval-path.json` → `cases.D` |

披露项（不单独阻断，但必须写进结论）：F5 NaN/远期时间戳未被拒（报告口径超出实现）、F6 A2 清单与 RunStore 等未冻结身份缺口、F7 r7 测试「不导入 MLX」的声明与 `arms.py` 模块级 `import mlx.core` 不符、F8 `run_worker` 的 train 分支不转发 CPU 替身（r7 证据只到 `_train` 层）。

## 1. 冻结身份与来源漂移

- `evidence/01-frozen-identity-before.json` / `12-frozen-identity-after.json`：`P15-r7-review-inputs.json` 里 **51/51 个冻结文件 SHA 全部匹配**，复核前后一致，**无来源漂移**。
- 真实中央账本 `artifacts/v9/s1/phase1/control.sqlite3` 复核前后**字节一致**（sha256 `a099c7ce2d5f465b5c05bf0c25acf83b296447cf87dcaffa5683e27fb18ad977`），`-wal` 与 `m0-worker.lock` 字节一致；仅 `-shm`（SQLite 易失共享索引，非账本内容）mtime 前移，其 sha256 未变——已实测「只读连接 WAL 库会刷新 -shm mtime」，故**不作零写断言**，只作「账本内容字节未变」的断言。
- 真实 `RESEARCH_LOG.md` 未被写入；r7 文档 `status` 仍为 `awaiting_coordinator_approval`（`evidence/10-leaf-diff.json`）。
- 复核期：2026-10-22 10:51–11:45 (+03:00)。

## 2. 通过项（独立复现，均非作者自证）

1. **宿主唯一锚**（`evidence/02-anchor-uniqueness.json`、`03-entry-path.json`、`04-shared-lock.json`）
   - 两个**真实源码 checkout**（`src/ainerzero` 的独立副本）在各自进程、异地 cwd、恶意 env（`AINERZERO_*`/`REPO_ROOT`/`HOME`）下解析到**同一** phase1 根、同一中央账本、同一 `m0-worker.lock`、同一 `RESEARCH_LOG.md`；锚常量是绝对字面量，不来自 `__file__`/cwd/env；解析本身无副作用。
   - **真实入口**（`commands.mode_train`，即 CLI `s1-phase1 --mode train` 的唯一实现）五种情形全部符合裁决：①隔离宿主 + **合法 SHA 批准行**（真实批准格式、真冻结文档 SHA）+ 中央账本已有 completed/failed/stopped 尝试 → `already_attempted`（说明批准门已通过、尝试守卫确实打在中央账本上）；②clone 根（自带合法空 prep DB + 自带批准日志）→ `output_root_not_canonical`，且 clone 账本 0 行、前后 sha 相同（**第二个 checkout 的空 DB 没有成为新中央台账**）；③无批准对照 → `preregistration_not_approved`（证明批准门真实，反例①不是被「没批准」掩盖）；④真宿主 + 真冻结文档 → `preregistration_not_approved`（P1 仍禁跑），真账本未变；⑤第二个真实 checkout 的外部根 → `output_root_not_canonical`。
   - 共享锁：两个来自不同 checkout 的 CPU 子进程竞争**同一个已登记锁**，第二个被 `WorkerLockBusy` 拒绝，锁文件字节不变。
2. **终态逐行保守计量**（`evidence/05-phase-accounting.json`）
   - 用**真实账本字节副本 + 真实 RunStore** 读出真正 `RunRecord`（ISO 时间戳串、真实 `reserved_active_seconds` 字段），与独立重算逐行完全一致：终态 `max(预留, 终态区间)`、活动 `max(预留, now-created)`、**逐行求和**；合计 **720.267 s = 预留合计**（与作者一致），日历年合计 ≈ 236 205 s（旧规则会全拒），新规则不拒；无任何一行被退款。
   - 坏守卫对照 5 个全部被区分：r6 日历年龄、未知状态当 0、未知状态当活动、丢弃预留、全局 max 代替逐行 max；另用合成两行证明「逐行 max ≠ 全局 max」（1100 vs 1010）。
   - 坏行拒绝：未知状态、倒序时间戳、NaN、Inf、缺时间戳、不可解析时间戳 → 全部抛错拒绝。
3. **阶段范围**（`evidence/06-phase-scope.json`）：prep(data/smoke/verify)、train、eval 各类行**都计入**总额（种子账本 405 s = prep 205 + train 200 + eval 40）；失败尝试永不清除；真入口在超额时以 `phase_budget_exceeded` 拒绝并附逐行 breakdown。
4. **D 候选身份**（`evidence/07-d-candidate-identity.json`）：真宿主 **9 条**全部核验，tensors/manifest/metadata/checkpoint_id 与登记身份**完全一致**；`checkpoint_id`（UUID）与 `tensors_sha256`（64 位 hex）是**不同字段**、未被混用；篡改/缺失/登记摘要不符/清单未钉住该 checkpoint 四种反例**全部拒绝**（合成候选，隔离目录）；**真实 MLX 未加载**。
5. **D 评测路径顺序**（`evidence/08-d-eval-path.json`）：D 分支**不被** eval-48 门误杀（对照组文档下 D 路径完成且只调用 1 次 CPU 前向替身）；arm2/3/4 评测仍以 `eval_call_budget_exceeded` fail closed，**不开 run、不发起任何前向**（175 批窗口探针 > 登记 48 批）；身份校验失败时在**任何前向之前、开 run 之前**拒绝；S1 不可比指标全部显式 `not_applicable`。
6. **生产训练控制流**（`evidence/09-train-control-flow.json`）：真 `_train` + 真 RunStore + 真 development 数据 + CPU 数值替身，跑**冻结 3510 步**协议：3510 次 value_and_grad、3511 次预留（每步一次 + 纯墙钟预留）、末步之后**零**预留、**恰好 1 份**最终检查点且文件 SHA 与 receipt 一致、run `completed`；截止链四个反例（末次梯度 / 占空比睡眠 / 检查点 IO / 尾部 metadata IO）全部中止且不写 receipt，**恰好 450 s 边界**仍完成。
7. **非有限停止规则**（`evidence/11-nonfinite-stop-rule.json`）：NaN 损失、NaN 梯度叶、非有限参数在**第 1 步与最后一步**都中止、不写 receipt（r6 修复未退化）。
8. **r6→r7 逐叶差异**（`evidence/10-leaf-diff.json`）：独立展平比对 = **7 叶变化，全部在允许清单内**（`created_unix` + 4 个绑定源 + `package_map_digest` + `spec.sha256`）；科学值全部未动（数据 digest、48 批、种子 [0,1,2]、450/500 s、4 h=14400、3510 步、检查点集合、资源线、指标定义、停止规则）。
9. **测试套件**（`evidence/13-test-suites.json`）：`tests/v9/experiments` **228/235 通过**（7 个需真实 MLX 运行时，CPU 约束下不可复跑 → 记为**未验证**而非失败）；其余 v9 套件 **378/378 通过**（其中 2 个「禁止导入 mlx」用例在无 stub 下复跑通过）。**绿测只支持工程主张，不等于能力通过。**

## 3. 强制缺陷（可复现反例）

### F1 — 终态 `completed` 提交不受 450 s 截止约束（阻断）

- 裁决原文（S1-R7-DECISION §5）：「末步 IO/ledger.finish 提交耗时超过 450 也不能 completed」。
- 实现：`worker._train` 末尾的 `_enforce_deadline()` 在**返回之前**；`worker.run_worker` 随后调用 `ledger.finish(active_run, "completed", reason)`（`worker.py` 744 行附近）**没有任何时间检查**；而 `RunStore.transition` 对**终态**不做墙钟预算检查（`_check` 只对 `RECOVERABLE_STATES` 生效），所以 450 s 预算与墙钟都不会在提交处兜底。
- 反例（**真实墙钟**，非假计时）：截止 20 s 的运行，`_train` 正常返回后模拟一次 21 s 的慢提交（fsync 卡顿）→ `ledger.finish` 成功、run 状态 `completed`、报告 `completed`，完成时 `wall_seconds = 24.81 s > 20 s`。
- 对照：同样的超时放在**最后一次梯度**里 → `TimeoutError: frozen per-run deadline exceeded`、不写 receipt（守卫在 finish 之前是有效的，缺口精确落在 finish/receipt 这一步）。
- 作者 r7 证据的 5 个 deadline 对照（last-gradient / duty-sleep / checkpoint-io / metadata-io / exact-boundary）**都没有覆盖 `ledger.finish`**；本卡要求的「不能靠假计时范围遮住 finish/receipt」由此得到实证反例。

### F2 — r7 计量拒绝产品自身写入的 `collecting` / `validating` / `stopping`（阻断）

- `worker.ACTIVE_STATES = {created, initializing, training, pausing, paused}`，**不含** 生命周期自己的 `WORK_STATES`（`collecting`、`validating`）与过渡态 `stopping`。
- 而 S1 产品自己就在写这些状态：`worker.run_worker` 把 prep **data** 运行置为 `collecting`，把 prep **smoke/verify** 与**所有 eval** 运行置为 `validating`。
- 后果：这样一行**合法**账本行被当成「未知状态」→ `phase_total_wall_seconds` 抛 `ValueError` → train/eval 入口以 `ledger_timestamp_invalid` 拒绝，**理由是假的**（时间戳没问题），且该行**没有被计入**阶段总额（裁决要求「所有 phase 相关 prep/train/eval/verify 实际登记行均计入」）。一次被中断的 prep/eval 行会长期卡死 train 入口。
- 作者 r7 测试只覆盖 `completed` 与人为造的 `quarantined`，**没有**覆盖产品自写的三个状态。

### F3 — 真冻结文档下 D/arm1 评测入口无法完成（阻断）

- `run_worker` 的 arm1 分支用 `train_experiment_manifest(deadline_seconds=document["timing"]["arm1_deadline_seconds"], updates=0)` 登记实验（r7 文档里 **arm1_deadline_seconds = 2**），却用**入口传入的墙钟预算**（`commands.PREP_BUDGET["eval"] = 300`，CLI 默认）登记 run → `RunStore.create_run` 拒绝：「run budget exceeds experiment run limits」→ 状态 `failed`，不开 run、不前向。
- 换成 ≤ 2 s 的预算也不行：`ledger.reserve` 的预留下限是 `max(5.0, 0.5*budget)` = 5 s > run 的 2 s 墙钟 → `BudgetExceeded: wall_time_budget` → 状态 `stopped`，**白白消耗一条 arm1 账本行**且没有做任何评测。
- 即：**任何预算取值都不能完成 D 复验**；r7 冻结的 D 复验路径实际上不可用。作者的 r7 D 测试只测 `_evaluate_arm` 层与两条拒绝路径，从未用**真文档**走通 `run_worker(eval, arm1)`；其 fixture 文档 `arm1_deadline_seconds = 15`，恰好掩盖了这个预算/截止不一致。

### F4 — D 候选「只允许 1 次评测」守卫失效（阻断）

- `run_worker` 的 arm1 分支用 `PrepLedger.open_aux_run` 开 run，其 config snapshot 只有 `purpose`，**没有 `arm_id`/`seed`**；而「第二次尝试」守卫筛的是 `config_snapshot["arm_id"] == "arm1"` → **产品自己开的 arm1 行永远匹配不上**。
- 反例（对照组文档下路径可跑通时）：连续两次 arm1 评测 → 第二次**未**被 `already_attempted` 拒绝，状态 `completed`，中央账本里出现**两条**已完成的 arm1 评测行（两条 `arm_id` 均为 null）。登记的 `d_candidate_eval_runs = 1` 因此**没有生效**。
- 作者的 r7 测试 `test_a_second_arm1_attempt_is_refused` 手工造了一条带 `arm_id="arm1"` 的行——那是产品**从不创建**的形状，守卫在生产中因此是空的。

## 4. 披露项（非阻断，但必须随结论披露）

- **F5 报告口径超出实现**：r7 报告把 `non_finite`、`overflow_timestamp` 列为「refused states」，但 `run_conservative_wall_seconds` 用 `max(0.0, float(value))` 归一化预留，而 Python 的 `max(0.0, nan)` **等于 0.0** → NaN（以及 -inf）预留被**静默当 0**，紧随其后的 `isfinite` 守卫**永远不会触发**；有限的远期时间戳（如 1e308）也被接受、时长部分按 0 计。两者在真实账本中**不可达**（SQLite 把 NaN 存成 NULL，NOT NULL + `CHECK(active_seconds >= 0)` 拒绝；账本时间戳由生命周期写入），所以不是现网漏洞，但**违反卡内「未知或不合规字段不能按 0」**，且报告的拒绝清单需要更正。`tests/v9/experiments` 里**没有任何**用例覆盖 overflow/NaN 预留。
- **F6 未冻结身份缺口（不得装作不存在）**：r7 预登记只钉住 14 个源文件；**通用 RunStore 模块 `src/ainerzero/runtime/lifecycle.py`（账本实现本身）未被冻结**（复核确认其 sha256 `22ded55c…6b3f` 与冻结输入一致，作者**没有**改它），**A2 清单 `reports/V9-baseline/r3/baseline_manifest.json`（D 候选信任根）也未被冻结**，`src/ainerzero/learning/pilot_model.py`、`src/ainerzero/runtime/checkpoints.py` 同样未冻结。而 `arms.verify_d_candidate_identity` 里算出的 `digest` 局部变量**赋值后从未被读**（AST 校验），登记的 `frozen_manifest_digest 3481b6ad…` 只以 `manifest_digest_hint` 形式**报告**、从未与任何东西比较 → **D 候选信任根的自身身份没有被验证**（逐文件字节核验是有效的，但清单本身可被替换而不被察觉）。
- **F7 文档不实**：`tests/v9/experiments/test_s1_r7_d_candidate.py` 声称「No MLX is imported here」，但 `arms.py` 在**模块级** `import mlx.core as mx` / `import mlx.nn as nn` → 导入该测试模块即加载真实 MLX 运行时。本复核为守住「无 MLX 导入」约束，注入了 stub `mlx` 包（`probes/p21_mlx_stub_plugin.py`），并逐例确认「7 个失败全部源于 stub」；这些用例在真实 MLX 下未被本复核复跑。
- **F8 证据层级**：`run_worker` 的 train 分支**不转发** `backend` 参数给 `_train`（生产路径固定用 `runtime.MlxBackend`），所以 CPU 替身只能从 `_train` 层进入；作者的「生产 `_train` + 真 RunStore + 3510 CPU 后端」证据与我的 F1 反例都建立在这一层，**真 `run_worker` train 路径在 CPU 下无法被复验**。

## 5. 未验证 / 未获授权项（逐条列出）

- 真 MLX 的 D 候选前向、真实训练、真实评测、真实 `final` 分区、生成新数据、下载/安装、付费服务：**未获授权，未运行**（真实 D 的成本仍未知）。
- 7 个需真实 MLX 运行时的测试（`test_s1_no_update` ×2、`test_s1_pacer_duty` ×4、`test_s1_timing_sequence` ×1）：CPU 约束下**未验证**（非失败）。
- `run_worker` 的 train 分支端到端（CPU 不可达，见 F8）；`commands.mode_train` 在**无尝试记录**下的「合法批准 → 进入训练」全链（会启动真实 MLX）。
- 真实中央账本中不存在 arm2/3/4×种子训练行、失败/停止行与 arm1 行（账本只有 3 条 prep completed 行），所以「中央已有 completed/failed/stopped 尝试」的入口正例是在**隔离宿主 + 真实 RunStore** 中构造的；真实账本上的同形情形**未验证**。
- r5/r6/P17 旧报告、A2 基线清单的生成过程、AWZ 评测包：未复核。
- 真实 `RESEARCH_LOG.md` 内**不存在** r7 文档的批准行（既有那行是「已作废」文本，不符合 bare-line 格式），因此**批准解析**只在隔离宿主的**真实格式**批准行上验证过。

## 6. 复跑方法（全部只读被审源，输出各自独立目录）

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
P=reports/V9-P21/minimax-p21-1022am/probes
for p in p01_identity p02_anchor p03_entry_path p05_phase_accounting p06_phase_scope \
         p07_d_candidate p08_d_eval_path p09_train_flow p10_leaf_diff p11_nonfinite \
         p12_after p13_tests; do
  .venv/bin/python $P/$p.py            # 各自写 evidence/NN-*.json
done
PYTHONPATH=$P .venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  -p p21_mlx_stub_plugin --junitxml=reports/V9-P21/minimax-p21-1022am/logs/pytest-experiments.xml
```

隔离要求：所有临时宿主/账本/数据副本都建在 `/private/var/folders/.../T/opencode/p21-scratch`；真实账本只以**字节副本**打开；宿主锚用项目自带的受控 CPU seam（`spec.REGISTERED_HOST_ROOT` / `spec.PHASE1_ROOT`）声明，**不修改被审源**；`arms.py` 的模块级 MLX 导入用 stub 挡掉，真实 MLX 未加载（每个证据文件都记录 `real_mlx_loaded`）。

## 7. 给统筹的建议（不代做决策）

1. **Reject P15 r7**（F1–F4 为强制反例）；r7 冻结参数本身可保留（7 叶差异合规、科学值未动）。
2. r8 至少要覆盖：finish/receipt 后的截止复核；`ACTIVE_STATES` 补齐生命周期真实状态（或改为「非已知状态才拒」并把 prep/eval 状态显式纳入）；arm1 实验的墙钟预算与 `arm1_deadline_seconds` 一致化；arm1 评测行登记 `arm_id`（或让守卫改按 `purpose`/experiment 匹配）以便「只 1 次」真正生效。
3. 冻结源身份：把 `src/ainerzero/runtime/lifecycle.py`、A2 清单（及其 `manifest_digest`）纳入冻结或显式登记为已知缺口；r7 报告的 `refused_states` 清单按 F5 更正。
4. 保持 P1 禁跑：**没有**新的批准行，本次复核不构成任何运行授权。
