# ainerzero.V9.P9 执行报告（r2）

角色：executor；负责人：deepseek-flash-q8m4（二级）；时间：2026-10-21（+03:00）
任务状态：reported；实验状态：未执行真实训练（本卡只做数据/预登记/无更新冒烟）
任务依据：接力台 ainerzero.V9.P9 任务卡（第 2/3 次）+ V9.P10 打回项 F1–F4 + 一级 notice #297 + RESEARCH_LOG `R20261021-P1-stageA-budget`（含 12:20 补的批准机制段）。参数 v0 `{}` 照用未改。

## 摘要（≤30 行）

1. **F1 已修**：预登记 `status` 字段不再是批准依据。`train` 只认 `RESEARCH_LOG.md` 里一级写入的裸行 `APPROVED s1-phase1 prereg document_sha256=<64 hex>`，且必须与冻结文件 document SHA **完全相等**；找不到/不匹配一律 exit 3，并把批准行原文、行号、日志 SHA256、文档 SHA256 写进 RunStore run 的 `config_snapshot.approval`。伪造 `status=approved` + 重算 SHA + 重写 sidecar 实测 exit 3（`evidence/forged-status.out`）。
2. **F2 已修**：pacer 与 duty 都改成行为测试。用假时钟/假 MLX 驱动 `worker._train`，断言每次更新后 `sleep == 实测单步 × (1/duty − 1)`（duty 0.25→0.06 s、0.5→0.02 s、0.1→0.18 s）；`evaluate()` 的 duty 分支现在可达（`RuntimeGuard` 直接传 limits）并被 5 个用例覆盖。
3. **F3 已修**：worker 侧批准门独立成立（不依赖 CLI 门）。新测试直接调 `worker.run_worker("train", …)` 断言 refused，且把 `_train` 换成 tripwire。
4. **F4 已修**：无更新由测试**独立重算参数 SHA** 判定。另加 `verify` 模式的 `independent_parameter_check`：从冻结 spec 重建四臂、只哈希参数、不读数据集、不做前向，与冒烟记录的前后 SHA 三方比对 → `passed`。
   `verify` 还新增 `source_binding`：把冻结文件绑定的 12 个源文件逐个重算 SHA，任何漂移即 `failed/source_binding_drift`（r2 实测 12/12 match）。
5. **变异矩阵 12/12 全部被捕获**（P10 时只有 8/12）。M1/M2/M12 用原 anchor 一字未改；M10/M11 的 anchor 必须移动，因为 F1 已把 status 门整段删掉（见「与 P10 harness 的差异」）。
6. **notice #297 已落地**：账本 `artifacts/v9/s1/phase1/`，数据集 `artifacts/v9/s1/datasets/8234f2f3…ad26/`，`reports/V9-P9/r2/` 只放清单与 SHA。数据集独立重生成，**digest 与 r1 完全一致**。
7. **预算不变**：`updates=3510`（②③④ 相同）、seeds 0/1/2、deadline 450 s、监督 500 s、arm1 2 s/52 s、第一阶段总墙钟 4099.6 s ≤ 4 h。冒烟实测 5.758/2.139/6.527 ms（arm1 1.308 ms），峰值进程 0.175 GiB、MLX 3.28 MiB。
8. **重新冻结**：document SHA `0547744f…4c07`（r1 `32c30f50…4de6`）。r1↔r2 逐叶差异 37 项，全部落在 `source_identity`(10)/`commands`(5)/`storage`(3)/`approval_rule`(5)/`timing`(11，仅 smoke_source+smoke_recheck 记账)/`created_unix`(1)/`data_identity`(2，export_meta 时间戳与生成耗时)；**arms、training_protocol、resource_limits、metrics、stop_rules、data plan/counts 一字未变**。
9. **反例全部实测**：资源门收紧 exit 2、放宽内存 exit 2、放宽占空比 exit 2、锁忙 exit 4、预算守卫 exit 1（RunStore stopped）、未批准 train exit 3、伪造 status exit 3、批准行差一位 exit 3；唯一放行的是 SHA 完全一致的那一行（`evidence/approval-exact.json`）。
10. **测试 106 passed / 0 failed / 0 skipped**（r1 为 67），XML 在 `reports/V9-P9/r2/tests-s1.xml`。
11. **未做/限制**：未训练、未更新参数、未读 final；`relay exec` 在本机沙箱仍报 `exit_unconfirmed`（ps 枚举被拒）并留下一条未归档的 exec 记录，之后 relay exec 一律静默失败 → 本卡的长命令改由 CLI 直跑（仍走共享锁/RunStore/预算守卫），详见「限制」。
12. **交回**：请 V9.P11 复核 → 一级确认「步数按 r1 测量记录冻结」与「reports 副本 + artifacts 权威」两处口径 → 再写批准行（本卡未写、也不会写）。

## 输入身份

| 对象 | 身份 |
|---|---|
| 冻结预登记（权威） | `artifacts/v9/s1/phase1/pre_registration.json`；document SHA256 `0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07`；file SHA256 `56ac88a0646365e4833d04e4409ceaccb08aa39732e32a3dfb99d9183475f1fe` |
| reports 副本 | `reports/V9-P9/r2/pre_registration.json` + `.sha256`（与权威逐字节相同） |
| r1 冻结（已归档） | `reports/V9-P9/r1-archive/pre_registration.json`，document `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6` |
| 源绑定 | s1 包 11 文件 + `src/ainerzero/cli.py`（r2 新增绑定）共 12 项 SHA256 图；`verify` 每次重算；`package_map_digest` 见 `source_identity.package_map_digest` |
| 数据集 | `dataset_digest 8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`（与 r1 相同）；manifest 文件 sha256 `5cbd6522…b4ed594`；2000/200 世界、rounds=1、9500/950 包；生成 45.74 s；final 未生成未读 |
| 冒烟测量记录 | r1 `reports/V9-P9/r1-archive/smoke_metrics.json` sha256 `b4e7d121…1ce8`（冻结预算的测量来源）；r2 复测 `artifacts/v9/s1/phase1/smoke_metrics.json`（6.527 ms/步 → 若用它推导为 3749 步） |
| A2 冻结清单 | `reports/V9-baseline/r3/baseline_manifest.json`；D 候选 `pilot-b4e75e9b…` / checkpoint `96b72328…`；`arms.py` 与 r1 逐字节相同 |
| 变异矩阵 | `reports/V9-P9/r2/harness/mutations.json`（12/12 CAUGHT） |

## 修改文件

| 文件 | 目的 |
|---|---|
| `src/ainerzero/v9/experiments/s1/prereg.py` | 新增批准行读取/校验（`read_approval_lines`/`require_coordinator_approval`/`ApprovalRefused`）；`approval_rule`、`storage` 块；`commands` 路径改到 artifacts；源绑定加入 `cli.py` |
| `src/ainerzero/v9/experiments/s1/commands.py` | `_output_root` 默认 `artifacts/v9/s1/phase1`；`--research-log`；监督侧批准门 `_require_approval`；`lock_busy` → exit 4；`_freeze` 支持 `--smoke-metrics` 并记录 `smoke_source`/`smoke_recheck`；`verify` 增 `independent_parameter_check`、`frozen_smoke_source`、`approval` |
| `src/ainerzero/v9/experiments/s1/worker.py` | worker 侧批准门 `_require_approval`；批准行写入 run snapshot；修 `train_experiment_manifest` 的 `max_model_transitions=0`（账本要求正数）与 `created→initializing→training` 缺边（r1 潜伏缺陷，被 F3 测试暴露）；dataset 解析走 `resolve_dataset_dir` |
| `src/ainerzero/v9/experiments/s1/data.py` | 数据集发布到 `datasets/<digest>/` + `dataset_ref.json` + `resolve_dataset_dir`（fail-closed） |
| `src/ainerzero/v9/experiments/s1/resource_gate.py` | duty 线取自 `spec.RESOURCE_LIMITS`；`evaluate` 的 duty 分支改为运行期可达并被覆盖 |
| `src/ainerzero/v9/experiments/s1/smoke.py` | 新增 `parameter_digests()`（只哈希参数，独立重算用）；`parameters_unchanged` 行保持原样 |
| `src/ainerzero/v9/experiments/s1/spec.py` | `PHASE1_ROOT`/`DATASETS_DIR`/`RESEARCH_LOG`；`REPORTS_DIR` 保留给清单 |
| `src/ainerzero/cli.py` | `--output-root` 默认改 artifacts；新增 `--research-log`、`--smoke-metrics`；`WorkerLockBusy` 异常 |
| `tests/v9/experiments/` | 新增 5 个文件（批准、pacer/duty、无更新、存储布局、锁与退出码）；`s1_testkit.py` 加冻结文档/研究日志助手；`test_s1_prereg.py` 训练拒绝用例改用临时日志 |

## 实际执行（准确命令）

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
# 1. 数据集（独立重生成，digest 与 r1 相同）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode data --output-root artifacts/v9/s1/phase1
# 2. 无更新冒烟（前向+损失，无梯度、无更新）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode smoke --output-root artifacts/v9/s1/phase1
# 3. 草稿 → 冻结（测量记录 = r1 smoke，见「限制」第 2 条）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode preregister --output-root artifacts/v9/s1/phase1
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode freeze --output-root artifacts/v9/s1/phase1 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
# 4. 复验（含独立参数重算 + 批准状态）
.venv-ainerzero/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1
# 5. 测试
PYTHONPATH=src .venv-ainerzero/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r2/tests-s1.xml
# 6. 反例（全部经真实 CLI）
bash reports/V9-P9/r2/harness/run_refusals.sh
# 7. 变异矩阵（P10 harness 副本）
.venv-ainerzero/bin/python reports/V9-P9/r2/harness/mutation.py
```

## 验证结果

| 项 | 结果 |
|---|---|
| 测试 | **106 passed / 0 failed / 0 skipped**（2.1 s）；`reports/V9-P9/r2/tests-s1.xml` |
| 变异矩阵 | **12/12 CAUGHT**（M1 4 failed、M2 6 failed、M3/M4/M6/M7/M9/M12 各 1 failed、M5 4 failed、M8 26 failed、M10 3 failed、M11 2 failed） |
| 资源门（真实 CLI） | 收紧进程内存 0.01 GiB → exit 2 `process_memory_limit`；放宽内存 16 GiB → exit 2 `loosening refused`；放宽 duty 1.0 → exit 2 |
| 共享锁 | 另一进程持锁时 `--mode data` → exit 4 `lock_busy` |
| 预算守卫 | `--mode smoke --wall-budget-seconds 20` → exit 1，RunStore run 转 `stopped/budget_exhausted` |
| 批准 | 无批准行/伪造 status/差一位/旧文档 → 全部 exit 3；SHA 完全一致 → 放行（`evidence/approval-exact.json`） |
| 无更新 | `parameters_unchanged=true`、`updated_parameters=false`、`gradients_computed=false`；`verify` 独立重算四臂参数 SHA 全部 match |
| 源绑定 | `verify` 重算 12 个绑定文件（s1 包 11 + `cli.py`）全部 match；改坏任一绑定即 `source_binding_drift` 失败（有单测） |
| 预算 | estimate 359.93 s → deadline 450 s → supervision 500 s；phase 4099.6 s ≤ 14400 s；单次 450 ≤ 1200 |
| 冒烟 | 单步 5.758 / 2.139 / 6.527 ms（arm1 1.308 ms）；峰值进程 0.175 GiB、MLX 3.28 MiB；总 5.6 s |
| 数据 | 2000 世界/9500 包、200 世界/950 包、rounds=1（上限 4）；digest 与 r1 相同；final 未生成未读 |
| 四臂 | 393,232 / 207,519 / 159,455 / 274,031 参数；②③④ 均 3510 步、seeds 0/1/2 |

## 与 P10 harness 的差异（只改输出路径 + 两处 anchor）

- 输出路径：`SB`/`MUT`/`OUT`/结果目录改到 `/private/tmp/v9p9r2/*` 与 `reports/V9-P9/r2/harness/`。
- **M10/M11 anchor 移动**：P10 的 anchor 是 `document.get("status") != prereg.STATUS_APPROVED`，而 F1 明确要求删掉这条 status 门，旧 anchor 已不存在于源码。新 anchor 指向批准门调用本身（`approval = _require_approval(…)`），变异语义、编号、期望与其余 10 项一字未改。若强行保留旧 anchor，harness 会 SKIP 而不是 CAUGHT，等于降低门槛。
- M1/M2/M3–M9/M12 的 anchor 与断言与 P10 逐字节相同。

## 失败与限制

1. **relay exec 不可用（环境）**：`relay exec` 在本机沙箱无法枚举进程组，报 `exit_unconfirmed` 且不归档终态；此后所有 `relay exec` 调用静默 exit 1（连 `/bin/echo` 也是）。本卡因此用 CLI 直跑长命令（共享锁/RunStore/预算守卫都在 CLI 内，未绕过），并把墙钟写进报告。**留给一级**：接力台上这条 exec 记录仍是 running，可能需要人工归档，否则会挡住后续 agent 的 exec。
2. **步数按 r1 的测量记录冻结（需一级确认）**：冻结规则 `updates = f(实测单步耗时)`，r2 复测 6.527 ms 比 r1 的 6.963 ms 快 6.3%，若用 r2 实测会得到 **3749** 步。任务卡要求「步数一律不变」，故冻结文件用 r1 的测量记录（`timing.smoke_source`，sha `b4e7d121…`，`arms.py` 与 r1 逐字节相同）推导 3510 步，并把 r2 复测作为 `timing.smoke_recheck`（`derived_updates_if_recheck_used=3749`、deadline 仍 450）写进同一份冻结文件。规则、上限、预算线都没有改。若一级认为应当用 r2 实测，重冻一次即可（`--mode freeze` 不带 `--smoke-metrics`），但那会把步数变成 3749。
3. **数据集不是逐字节复用 r1**：重新生成后 `dataset_digest` 相同，但 `data_identity.files["export_meta.json"]` 与 `generation_seconds`（45.74 vs 47.61）不同——这两个字段不进 digest 规则，属于生成时间戳/耗时，不是数据内容差异。
4. **r1 潜伏缺陷（已修，报告备查）**：`train_experiment_manifest` 的 `experiment_budget.max_model_transitions=0` 被账本拒绝（要求正数），且 `_open_train_run` 少了 `created→initializing` 边。r1 从未走到 train 分支所以没暴露；F3 的测试第一次把它打出来。修法：实验级上限 1（run 级仍 0，等于不放开任何额度）+ 补 `initializing` 转移。
5. **未验证项**：真实训练/评测未跑（按卡）；`--mode train` 的批准路径只到「门放行 + 登记 run + 调 `_train`」为止，`_train` 的真实训练循环仍未在真机上跑过（等 V9.P1）。
6. **数据落盘位置**：`reports/V9-P9/r1-archive/dataset/` 保留了 r1 的 17 MB 数据集副本（归档要求），与 artifacts 下的同一 digest 重复；如需省空间可只留 manifest + SHA。

## 交回统筹

1. V9.P11 复核本 r2（重点：批准门两侧、pacer/duty 行为测试、独立参数重算、12/12 变异、r1↔r2 差异范围）。
2. 一级确认第 2 条（步数按 r1 测量记录冻结）与「reports 放清单副本、artifacts 为权威」的口径，然后在 RESEARCH_LOG 追加批准行 `APPROVED s1-phase1 prereg document_sha256=0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07`。
3. 接力台上那条未归档的 exec 记录需要人工收尾。
