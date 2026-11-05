# ainerzero.V9.P15（S1 入口 r8）执行报告

- 角色：二级执行层 · 作者 `deepseek-v41f-w3q7` · 2026-10-22
- 依据：`S1-R8-DECISION.md`、`P21-EVIDENCE-ADDENDUM.md`、`reports/V9-P21/minimax-p21-1022am/REPORT.md`（F1–F8）
- 交付：`reports/V9-P9/r8/`；新冻结 `artifacts/v9/s1/phase1/r8/`（doc `2082e2a3…7175`，file `e8cfa239…114a`，状态 `awaiting_coordinator_approval`）
- 未执行：真实 MLX 前向/训练/评测/final、生成新数据、下载/安装、写批准行、启动 P1；未写真实中央台账、`RESEARCH_LOG.md`、r4–r7/P21 原件

## 1. 起始对账与交接（先做，未覆盖任何旧证据）

- `provenance/STARTING-BYTES.json`：r7 交付的 51 个绑定输入逐字节重算，**45 匹配 / 6 漂移**（`arms.py`、`commands.py`、`prereg.py`、`spec.py`、`worker.py`、`test_s1_r7_d_candidate.py`），另有 `completion.py`、`identity.py` 两个新模块。
- 漂移来源已定性：上一棒 `ds-s1r8-1200`（12:14 领卡、12:43 因 29 分钟无心跳被收回，未交付报告）的未提交 WIP。本卡**逐文件审计**后才继续，未当可信输入。
- `provenance/PROVENANCE.json` 记录 gemini-b7m9 / deepseek-r7xq / ds-s1r8-1200 / minimax-p21-1022am 的贡献与本卡改动，未用新 ID 掩盖作者。

## 2. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P9/r8/harness/archive_starting_bytes.py
.venv/bin/python reports/V9-P9/r8/harness/refreeze_draft.py
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r8 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1/r8
.venv/bin/python reports/V9-P9/r8/harness/prereg_leaf_diff.py
.venv/bin/python reports/V9-P9/r8/harness/phase_accounting_evidence.py
.venv/bin/python reports/V9-P9/r8/harness/ledger_and_eval_evidence.py
.venv/bin/python reports/V9-P9/r8/harness/decision_evidence.py
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r8/logs/tests-s1-r8.xml
.venv/bin/python -m pytest tests/v9/geometry tests/v9/contracts tests/v9/teachers \
  tests/v9/tokenization -q -p no:cacheprovider --junitxml=reports/V9-P9/r8/logs/tests-v9-other-r8.xml
```

**测试执行环境（必须披露）**：本会话的 WorkBuddy 沙箱 `sitecustomize` 会拦截 `Path.mkdir` 并把 `EEXIST` 变成 `PermissionError`，在默认解释器下使 6 个既有用例（`test_s1_approval`×2、`test_s1_train_gates`×4）在 fixture 建目录阶段就报错。为取得可解释信号，最终证据用 `python -S`（不加载 sitecustomize）+ `PYTHONPATH=site-packages:src` 运行；同一套件在默认解释器下为 `229 passed / 6 failed`，6 个失败全部是该沙箱伪影，与被测代码无关。`CODEBUDDY_SAFE_DELETE_SANDBOX=0` 与 `CODEBUDDY_BROKERED_FS_HOOK_ENABLED=0` 均无效（钩子由 `_IN_SANDBOX` 硬开）。

## 3. F1–F8 的修复与反例

### F1 完成边界（统一完成协议）
新增 `s1/completion.py`：`CompletionProtocol` 一条 `perf_counter` 计时覆盖整条有界运行，成功路径 = **提交前检查 → 提交在 watchdog 下执行 → 提交后检查**。`worker._complete_run` 成为 train/eval/arm1 的唯一终态出口。
- 反例 A（提交前 21 s 停顿，`TEST_SEAM` 注入）：`failed` / `completion_deadline_exceeded`，台账停在 `failed`，无 completed。
- 反例 B（**真实 SQLite 写锁等待**，`BEGIN IMMEDIATE` 占 0.6 s，截止 0.3 s）：`expired_in_flight=true`、`failed`、`rolled_back=false`；台账行已落地为 `completed`，**未被改写为 stopped、未删失败、未退款**，改为写不可变 `completion_invalid.json`（`ledger_state_at_invalidation=completed`）。
- 消费者侧：`_bind_completed_run` 拒绝 ① 带失效标记的运行 ② receipt 无 `completion_protocol` 记录 ③ receipt 自述 elapsed > deadline ④ `expired_in_flight`。即 **completion.json 存在 ≠ 有效完成**。
- 技术边界（如实）：本适配层**无法撤销已提交的 SQLite 终态行**，只能拒绝报告它并让所有消费者拒绝；这是磁盘提交确认的边界，不是"已回滚"。
- 反例均在工程缩比（0.3–20 s）下取得；冻结 450 s 的替身验证见 §4（4 个截止控制 + 恰好 450 s 边界）。二者分开记录，未混用。

### F2 阶段状态
`ACTIVE_STATES` 补齐通用生命周期实际可写的 `collecting/validating/stopping`（连同 created/initializing/training/pausing/paused），未知状态仍拒绝；拒绝原因按 `LedgerStateInvalid`（状态）与 `LedgerTimestampInvalid`（时间）分开。证据：8 个非终态状态全部被接受并按 `max(reserved, now-created)` 计入；`quarantined/None/archived` 全部以状态错误拒绝，**不再冒充时间戳错误**，也未当 0。

### F3 D 单次预算
`train_experiment_manifest` 改为**只冻结上限**（`phase_wall_max_seconds=14400`、`max_optimizer_steps=updates`），payload 与调用方 deadline 无关 → D 先/训练先都不冲突，不按新实验 ID 重置尝试或总账。arm1 运行改用冻结的 `arm1_deadline_seconds=2` 登记（不再用 eval 入口 300 s），单次预留 `min(0.5*budget, remaining)=1.0 s`，**不再有 5 s 下限吞掉 2 s**。实测：真冻结形状（3510 步、450 s、arm1 2 s）下 `run_worker(eval, arm1)` 走通 `completed`，run budget=2.0 s，`0 < reserved ≤ 2`，优化器步 0，D 前向替身恰好 1 次。

### F4 一次守卫
`open_aux_run` 现在由产品自己写入 `arm_id/seed/purpose/preregistration_sha256/d_candidate_identity`；`d_candidate_attempt_state` 对**已开始**的 arm1 行报 `already_attempted`，对"像 D 但没有 arm_id"的旧行报 `unidentifiable` 并 fail closed，不删不改不自动修表。实测：第二次 arm1 被拒（`already_attempted`，只有 1 条 arm1 行）；纯遗留行 → `unidentifiable`；`arm2` 行与从未开始的 `created` 行都不误判。

### F5 字段契约
`_validate_reserved` 在**任何 max 之前**校验存在/数值/有限/非负（NaN、±inf、-5、None、字符串、bool、缺字段全部拒绝，不再 `max(0.0,nan)=0`）；`_parse_timestamp` 校验可表示、有限、顺序（`1e308`、NaN/inf、倒序、不可解析全部拒绝），`now` 也校验；合法未来时钟高水位（created>now）按 0 龄接受，不与 RunStore 语义冲突。证据见 `evidence/decision-evidence.json` 的 `F5_field_contract`。

### F6 冻结信任链
新增 `s1/identity.py`（**纯标准库 + MLX-free**）：① 以登记 `frozen_manifest_file_sha256=2c991f05…be5b` 钉住 A2 清单**原始字节**；② 用**原 A2 r3 算法**（`sha256(canonical(manifest − generated_at, manifest_digest, policy_check))`，与 `scripts/v9_baseline_manifest_r3.py` 的 `canonical/digest` 逐字一致）重算并与登记 `3481b6ad…45e9` **真比较**（P21 指出 r7 只报告不比较）；③ 逐文件核 A2 钉住条目（9 条）；④ 逐字段核 `tensors/manifest/metadata` 摘要。反例：换字节、改登记摘要、缺钉住字节、改任一字段摘要、缺 pilot 目录、翻一个字节 → 全部拒绝。冻结源新增 `runtime/lifecycle.py`、`core/pilot.py`、`learning/pilot_model.py`、`runtime/checkpoints.py`、A2 清单（**只读纳入身份**，不改科学值），绑定文件 14→**21**。

### F7/F8 诚实 CPU
`identity.py`/`worker.py` 导入链 **不加载 mlx、不加载 arms**（子进程断言）。`run_worker` 的 train 分支把 CPU 替身转发进 `_train`（内部 seam，CLI 无入口），因此**真公共控制流**（审批门→源绑定→数据摘要→尝试守卫→阶段预算→真 RunStore→完成协议）在 CPU 下可审；替身**不跳过**审批/共享锁/台账/阶段/次数/完成协议（F3 反例：无批准行仍 `preregistration_not_approved`）。

## 4. 生产形状证据（真 RunStore + 真 development 数据 + CPU 数值替身）

`evidence/ledger-and-eval.json`（跑在 **r8 冻结文档** `2082e2a3…` 上）：
- 3510 步：`optimizer_reservations=3510`、末步后 **0** 次预留、**恰好 1 份**最终检查点、`run_state=completed`、`mlx_imported=false`。
- 5 个截止控制：last-gradient / duty-sleep / checkpoint-io / metadata-io **全部中止**（`CompletionDeadlineExceeded`，走统一协议），**恰好 450 s 边界仍完成**。
- 3511 步反例：第 3512 次预留被 `BudgetStop: optimizer_step_budget` 拒，run 未 completed。
- 台账重跑：已完成 run 再跑被拒；缺失/篡改检查点/错误 prereg SHA 三个负控全部拒绝。

`evidence/phase-accounting.json`（真实台账**字节副本**）：3 行，日历年合计 **258,686.758 s**（旧规则会全拒）vs 保守合计 **720.267 s** = 预留合计；真实台账 sha 前后一致。

## 5. 验证结果

| 套件 | 结果 |
|---|---|
| `tests/v9/experiments` | **291 passed / 0 failed**（r7 235 + 本卡新增 56；junit `logs/tests-s1-r8.xml`） |
| 其他 v9（geometry/contracts/teachers/tokenization） | **378 passed / 0 failed** |
| r7→r8 逐叶差异 | 398 叶、**15 叶变化**（`created_unix` + 13 个绑定源/新增源 + `package_map_digest` + `spec.sha256`），**outside allowlist: []** |
| 科学值 | 3510 / 450 / 500 / 14400 / 48 / 种子 [0,1,2] / 检查点集合 / 数据 digest **全部未变** |
| 新增测试 | F1/F8 5 例、F2/F5 32 例、F3/F4 7 例、F6/F7 12 例 |

## 6. 失败、未验证与限制（如实）

1. **未运行真实 MLX**：D 的真实成本仍未知；`arm1_deadline_seconds=2` 是否够真实前向未验证，**只报告不足、不扩预算**。
2. **eval 入口（arm2–4）**：`evidence/ledger-and-eval.json` 的 eval 段是 `_evaluate_arm` 直调（175 窗口批 > 登记 48 批），**不是入口放行**；入口仍 fail closed（r6 入口门用例在 291 绿中）。本卡未放宽 48 批。
3. **F1 提交后边界**：已提交的终态行不可撤销；本卡只保证"拒绝报告 + 所有消费者拒绝"。未声称回滚。
4. **锁等待反例**是 SQLite 写锁真实阻塞，但延迟由测试线程施加（0.6 s），**不是**真实 fsync 卡顿注入；工程缩比与冻结 450 s 分开记录。
5. 未验证 `run_worker` train 在**无尝试记录 + 合法批准行**下的真实 MLX 全链（会启动真实训练，未获授权）。
6. 未复核 r4–r7/P21 旧报告与 A2 清单生成过程；AWZ 评测包未使用。
7. 沙箱测试伪影见 §2；本卡未修改测试语义来掩盖它。

## 7. 交回统筹

请新非作者 P24 独审：① 统一完成协议在 `finish` 内部/DB 锁等待下的捕获与"不撤销"边界；② 阶段状态覆盖与两类拒绝原因；③ D 2 s 预算与单次守卫是否真在**产品自建行**上生效；④ 字段契约与"合法未来时钟"；⑤ 冻结信任链是否真比较 `manifest_digest`；⑥ r8 冻结是否只动允许叶。

工程绿不等于能力通过：本卡**未**晋升、**未**写批准行、**未**发布 P1。
