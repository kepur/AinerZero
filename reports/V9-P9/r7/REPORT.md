# ainerzero.V9.P15（S1 入口 r7）执行报告

角色：executor（二级）；负责人：`deepseek-r7xq`；时间：2026-10-22
任务状态：reported；实验状态：未执行真实训练/评测（CPU 工程与真实 RunStore 记账证据已完成）
任务依据：`S1-R7-DECISION.md`、`P17-EVIDENCE-ADDENDUM.md`、`P15-REPAIR-DECISION.md`、`S1-R6-DECISION.md`；
范围：`src/ainerzero/v9/experiments/s1/`、`src/ainerzero/cli.py`、`tests/v9/experiments/`、`artifacts/v9/s1/phase1/`、`reports/V9-P9/r7/`。
交付目录：`reports/V9-P9/r7/`；新冻结：`artifacts/v9/s1/phase1/r7/`（doc `523a5b35…`）；旧 r4/r5/r6/P17 只读。

## 1. 实际执行的命令（完整日志见 `logs/`）

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
# 起始字节对账：35/35 与 gemini-b7m9 停滞 WIP 清单逐字节一致，0 漂移
# → reports/V9-P9/r7/deepseek-r7xq/provenance/STARTING-BYTES.json
.venv/bin/python reports/V9-P9/r7/harness/refreeze_draft.py      > logs/refreeze_draft.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r7 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json     > logs/freeze.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify \
  --output-root artifacts/v9/s1/phase1/r7                         > logs/verify.json
.venv/bin/python reports/V9-P9/r7/harness/prereg_leaf_diff.py     > logs/prereg_leaf_diff.txt
.venv/bin/python reports/V9-P9/r7/harness/phase_accounting_evidence.py
.venv/bin/python reports/V9-P9/r7/harness/ledger_and_eval_evidence.py > logs/ledger_and_eval.out
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r7/logs/tests-s1-r7.xml                > logs/tests-s1-r7.txt
.venv/bin/python -m pytest tests/v9/geometry tests/v9/contracts tests/v9/teachers tests/v9/tokenization -q
```

## 2. 三项 r7 裁决的实现与证据

1. **宿主唯一锚**（`spec.py` 新增 `host_anchor_state()/host_anchor()`）：唯一绝对锚 `/Users/mac/AinerWorkFlow/AinerZero` → phase1/central ledger/approval/lock 全由同一 dict 派生；`worker.run_worker` 与 `commands._canonical_run_root` 双侧 fail closed（`host_anchor_missing_root|missing_approval|unreadable_approval|mismatch`）；`commands._lock_path()` 改走锚。行为：clone 用自己的空合法 RunStore + 真实格式 SHA 批准行仍被拒（`output_root_not_canonical` / `research_log_not_canonical`）；两个真实源码 checkout 解析到同一 ledger 与同一锁；env 变量不能移动锚；未改通用 RunStore/数据库，未迁移或清空真实账本。
2. **终态阶段计量**（`run_conservative_wall_seconds` / `phase_ledger_breakdown`）：终态行 `max(reserved_active, terminal_at-created_at)`，非终态 `max(reserved_active, now-created_at)`，逐行求和；未知状态/倒序/非有限/缺失时间戳拒绝（读侧 `OverflowError` 也归为 `ledger_timestamp_invalid`）。字节隔离副本证据 `evidence/phase-accounting.json`：日历时龄合计 **230,799.829 s**（>14,400 会全拒）vs 保守合计 **720.267 s** = 预留合计，真实账本 sha 前后一致。4h/450-500/3510/三种子/资源线未改。
3. **D/arm1 复验身份**：`arms.verify_d_candidate_identity` 用 A2 权威清单逐文件核字节（tensors/manifest/metadata/候选身份），真实 host 上 9 条通过、tensors `cbb14d87…286a`；`worker._evaluate_arm` 现在**即使有 CPU 前向替身也先跑真身份校验**，替身不能顶替身份；篡改/缺失/摘要不符/第二次 attempt 均拒（`arm1_identity_verification_failed` / `already_attempted`，拒时未开 run）；S1 不可比项全部显式 `not_applicable`。

## 3. 验证结果

- `tests/v9/experiments`：**235 passed / 0 failed**（原 198 + 新增 r7 37 例；junit `logs/tests-s1-r7.xml`）。
- 其他 v9 套件：**378 passed**（geometry/contracts/teachers/tokenization），无回归。
- 逐叶差异（r6→r7，`prereg-leaf-diff.json`）：391 叶、7 叶变化（`created_unix` + 绑定源 `arms/commands/spec/worker.py` + `package_map_digest` + `spec.sha256`），**outside allowlist: []**；科学字段、数据 digest、3510/450/48/三种子未变。
- 生产 `_train` + 真 RunStore + 3510 步 + 真实 development 数据（`evidence/ledger-and-eval.json`）：3510 次 value_and_grad、3511 次预留、恰 1 份最终检查点、`mlx_imported=false`；末步控制 4/4 中止（last-gradient、duty-sleep、checkpoint-io、metadata-io），恰好 450.0 s 正常完成；3511 步在第 3511 次预留被 `BudgetStop` 拒，未产生 completed。
- 未写批准行：r7 文档 `status=awaiting_coordinator_approval`；未改 `RESEARCH_LOG.md`，未运行真实 MLX/训练/评测/final/下载/安装，未启动 P1。

## 4. 修改文件（摘要）

- `spec.py`：锚 resolver；`worker.py`：锚检查、未知状态拒绝、逐行 breakdown、arm1 替身不绕过身份、OverflowError 归一；`commands.py`：锚化 lock/root 检查、拒绝时带 breakdown；`arms.py`：checkpoint id 取自 identity。
- 测试：新增 `test_s1_r7_{host_anchor,phase_accounting,d_candidate,lock}.py`；`conftest.py`/`s1_testkit.py` 增加 `install_test_host`（锚一致，不再只 patch `PHASE1_ROOT`）与 `make_source_checkout`；3 个 r6 测试改为用该 helper（语义不变，仅修 fixture 一致性）。

## 5. 失败与限制

- r6 的 `isolated_approval_sim.py` 假设“每个 checkout 用自己的根”；该假设在 r7 被裁决否定，故未原样重跑，改用两个真实 checkout 的 pytest + 子进程入口反例（结果等价且更严格）。
- 未运行真实 MLX 推理/训练/评测；D 的实际成本仍未知，仅保留拒绝与缺口。
- 未声称防御任意源码篡改、未声称跨进程续训可用、未做零写断言（真实账本 sha 前后一致仅覆盖本次执行）。
- 未实现预算不足下的额外调用计划；eval 48 批语义仍未获新批准，保持 fail closed。
- 上一个作者 `gemini-b7m9` 的 35 文件 WIP 全部保留并列入 provenance；未用新 ID 掩盖其贡献。

## 6. 交回统筹

请新非作者 P21 独审：锚是否真正唯一（含 clone 子进程反例）、终态计量与反例、D 身份替身边界、以及 r7 冻结是否只动允许叶。工程绿不等于能力通过，未自动晋升。
