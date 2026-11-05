# ainerzero.V9.P11 执行报告：V9.P11 独立对抗复核 P9 r2

角色：reviewer（非 P9/P10 作者）；负责人：deepseek-4m9t（二级）；时间：2026-10-21 13:15–13:40（+03:00）
任务状态：reported；实验状态：未训练、未更新任何参数、未读 final；被复核对象：ainerzero.V9.P9 r2（reported）
任务依据：接力台 ainerzero.V9.P11 任务卡（参数 v0 `{}` 照用未改）+ 一级 13:11 口径（a）步数按 r1 测量记录冻结、（b）artifacts 双根
沙箱：`/private/tmp/v9p11/{sandbox,train_stub,mut2,f1,drift}`；真实树只读

## 摘要（≤30 行）

1. **变异矩阵独立复跑 12/12 全部被捕获**，并逐项记下失败用例名（不是"红了就算"）。P10 原 harness 逐字节复制（只改 3 行路径）先跑一遍：**10 CAUGHT + M10/M11 SKIP**，证实 F1 确实把 `status` 门整段删掉、旧 anchor 已不存在；仅把 M10/M11 的 anchor 移到新批准门调用后 12/12 CAUGHT，M1/M2 由 pacer/duty 行为用例捕获，M11 由 worker 侧两个用例捕获，M12 由"参数真被改过时冒烟必须报更新"用例捕获。
2. **F2/F4 复核通过**：pacer 用假时钟断言 `sleep == 实测单步 × (1/duty − 1)`（0.25→0.06、0.5→0.02、0.1→0.18），删 pacer 即 4 红；无更新由 `verify` 独立重建四臂重哈希判定，我在沙箱重跑 `--mode verify`：四臂 recomputed = smoke before = smoke after，全部 match。
3. **F1 只关闭了"改 status"这一条，第 5 类没关**：`--research-log` 是调用方可控路径，把批准行写进自己的 `RESEARCH_LOG.md` 再传该参数，**train exit 0 放行**（C5a），RunStore 还会写出一条"看起来合规"的批准记录。卡面要求第 5 类也 exit 3，故 **F1 判定不通过**。
4. 另外两点同源缺口（实测/静态双证）：**train 不校验源绑定**——同一棵树 `train` exit 0、`verify` exit 1 `source_binding_drift`（D1/D2）；**train 不比对数据集摘要**（AST：`_train` 从不读 `document["data_identity"]`）。
5. **F1 其余 4 类全部 exit 3**：改 status 并自洽重算 SHA（a36d4b15…）→3、批准行缺失→3、SHA 差一位→3、指向 r1 旧文档（32c30f50…）→3；旁路伪造 `APPROVAL.json`/`.approved` 侧车→3。
6. **正例放行成立且凭据入账**：CLI `--mode train` 拿到完全一致的批准行 → exit 0；RunStore 记录 `line` 原文、`line_number=4`、`document_sha256=0547744f…4c07`、`research_log_sha256=8fafe012…`，状态链 created→initializing→training→completed，optimizer_steps=0。
7. **预登记身份全部复现**：document `0547744f…4c07`、file `56ac88a0…f1fe`、sidecar 一致、reports 副本与 artifacts 逐字节相同；r1↔r2 逐叶差异 **37 项**（changed 17 + added 20），**参数/预算/种子/步数/资源线/指标/停止规则/数据计划零差异**（0 leaks）。
8. **预算推导一致**（独立重算）：r1 记录 → 3510 步、estimate 359.93 s、deadline 450 s、supervision 500 s、arm1 450 s、phase 4099.605 s ≤ 14400 s、单次 450 ≤ 1200；r2 复测（6.527 ms）→ 3749 步、estimate 359.91 s、deadline 仍 450 s，**仍在登记的单次上限内**（与一级 13:11 口径（a）一致）。
9. **notice #297 落地**：账本 `artifacts/v9/s1/phase1/control.sqlite3`，数据集 `artifacts/v9/s1/datasets/8234f2f3…ad26/`（目录名=digest，manifest SHA 与 ref 一致），`reports/V9-P9/r2/` 无数据集字节（最大文件 1 MB 清单）。
10. **真实锁与中央账本未动**：`artifacts/locks/m0-worker.lock` mtime 仍 1790110663（09-22 23:57:43），`artifacts/control.sqlite3` mtime 仍 1792008059（10-14 23:00:59）；我的全部 train/verify/反例都在 `/private/tmp` 副本里跑。
11. 退出码契约复测：收紧内存/放宽内存/放宽 duty → exit 2 且原因正确；`--wall-budget-seconds 99999` → exit 1；**锁忙 → exit 4**（P10 F5 已修）；未批准 train → exit 3。
12. **建议：打回**（只差 F1 第 5 类 + 两条同源缺口）；其余 6 项卡面要求全部通过。**在此之前不要写 `0547744f…` 的批准行**——修 P-1/P-2 会改 `commands.py`/`worker.py` 的源绑定，必然换 document SHA，会把这条批准行作废。

## 输入身份

| 对象 | 身份 |
|---|---|
| 被复核源码 | `src/ainerzero/v9/experiments/s1/`（11 文件，mtime 11:22–13:05）+ `src/ainerzero/cli.py`（13:01）；我未改任何源码（全部 mtime 早于本会话 13:15） |
| 冻结预登记 | document `0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07`；file `56ac88a0646365e4833d04e4409ceaccb08aa39732e32a3dfb99d9183475f1fe`；status `awaiting_coordinator_approval` |
| 旧（r1）预登记 | `reports/V9-P9/r1-archive/pre_registration.json`，document `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6` |
| 测量记录（冻结来源） | `reports/V9-P9/r1-archive/smoke_metrics.json` sha256 `b4e7d121…1ce8`（实测最大单步 6.962 ms） |
| 复测记录 | `artifacts/v9/s1/phase1/smoke_metrics.json` sha256 `75368e5e…8957`（6.527 ms → 3749 步，仅记账） |
| 数据集 | `dataset_digest 8234f2f3…ad26`；manifest sha `5cbd6522…94`；ref 指向 `artifacts/v9/s1/datasets/<digest>/` |
| P9 r2 报告包 | `reports/V9-P9/r2/SHA256SUMS.txt` 37/37 校验 OK（身份可核验） |
| 沙箱 | `spec.REPO_ROOT` = `/private/tmp/v9p11/{sandbox,train_stub,drift}`；`train_stub` 仅把 `_train` 换成桩，未跑一步优化 |

## 修改文件（只写本卡范围）

- 新增 `reports/V-V9-P9/r2/`：`REPORT.md`、`metrics.json`、`harness/{mutation_p10_copy.py, mutation_rerun.py, f1_approval.py, drift_check.py, refusals.py, prereg_review.py}`、`evidence/{f1-approval.json, train-binding-gap.json, cli-refusals.json, prereg-review.json, verify-sandbox.json, harness-anchor-diff.json}`、`results/{mutations-p10-copy.json, mutations-v9p11.json}`。
- 未改源码、测试、配置、artifacts；未提交/推送；未下载模型；未调用付费服务。

## 实际执行（准确命令与退出码）

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
# 0) 沙箱（逐字节副本）+ 桩 train（只改副本）
rsync -a src/ /private/tmp/v9p11/sandbox/src/ ; rsync -a tests/ ... ; rsync -a RESEARCH_LOG.md ...
rsync -a artifacts/v9/s1 /private/tmp/v9p11/sandbox/artifacts/v9/ ; rsync -a reports/V9-baseline ... ; rsync -a artifacts/pilot/.../96b72328-... ...

# 1) P10 harness 逐字节副本（只改 3 行路径）-> 10 CAUGHT + M10/M11 SKIP
.venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/mutation_p10_copy.py            # rc 0, 84 s

# 2) 12 项变异 + anchor 移动 + 失败用例归因 + 4 个额外探针 -> 12/12 CAUGHT, 探针 4/4
.venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/mutation_rerun.py               # rc 0, 99 s

# 3) F1 六类伪造 + 正例 + 钉住范围（全部经真实 CLI，沙箱桩 train）
.venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/f1_approval.py                  # rc 0

# 4) 冻结身份不绑运行入口（D1/D2/D3）
.venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/drift_check.py                  # rc 0

# 5) 退出码契约（沙箱）
.venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/refusals.py                     # rc 0

# 6) 预登记身份 / 预算推导 / 逐叶 diff / 存储布局（只读）
PYTHONPATH=src .venv-ainerzero/bin/python reports/V-V9-P9/r2/harness/prereg_review.py # rc 0

# 7) 沙箱内真实 verify（12 绑定 + 数据集 + 独立参数重算 + 批准状态）
PYTHONPATH=/private/tmp/v9p11/sandbox/src .venv-ainerzero/bin/python -m ainerzero.cli \
  s1-phase1 --mode verify --output-root /private/tmp/v9p11/sandbox/artifacts/v9/s1/phase1  # rc 0
```

## 验证结果（卡面逐条）

| 卡面要求 | 判定 | 证据 |
|---|---|---|
| 12 项变异 12/12 被捕获（含 M1/M2/M11/M12） | **通过** | `results/mutations-v9p11.json`：12/12 CAUGHT，失败用例逐项列出；P10 原 anchor 只剩 10 项可应用（M10/M11 SKIP，`results/mutations-p10-copy.json`），anchor 移动合法且未降低门槛 |
| F1 五类伪造全部 exit 3 | **不通过** | C1/C2/C3/C4/C5b exit 3；**C5a 伪造批准文件（`--research-log` 指向执行层可写日志）exit 0 放行** |
| 批准行正确时放行，原文与 SHA 写进 RunStore | **通过** | C6 exit 0；`config_snapshot.approval` = 行原文/行号 4/文档 SHA/log SHA，逐项与我独立重算一致 |
| 新旧预登记差异只在源绑定与路径 | **通过（含记账项）** | 37 叶：source_identity 10、commands 5、storage 3、approval_rule 5、timing 11（smoke_source/smoke_recheck 记账）、created_unix 1、data_identity 2（export_meta 时间戳/生成耗时）；参数类 0 差异 |
| 账本/数据集路径 = artifacts/v9/s1/phase1/、artifacts/v9/s1/datasets/<digest>/ | **通过** | `pre_registration.json.storage` + 落盘实测；reports 无数据集字节 |
| 未触真实锁与中央账本 | **通过** | mtime 1790110663 / 1792008059 与基线一致；S1 账本 2 条 auxiliary run、0 optimizer steps、无 train run |

## 变异矩阵（独立复跑，含失败用例归因）

| # | 变异 | 期望 | 结果 | 抓住它的用例（节选） |
|---|---|---|---|---|
| M1 | 删除 pacer 睡眠 | RED | **CAUGHT** 4 failed | `test_s1_pacer_duty.py::test_pacer_sleeps_to_hold_the_duty_cycle[0.25-0.06 / 0.5-0.02 / 0.1-0.18]`、`test_pacer_records_the_registered_duty_cycle_only` |
| M2 | 禁用 `evaluate()` duty 分支 | RED | **CAUGHT** 6 failed | `test_evaluate_refuses_a_loosened_duty_cycle[0.5/1.0/0.2500001]`、`test_evaluate_refuses_a_nonpositive_duty_cycle[0.0/-0.25]`、`test_runtime_guard_refuses_a_loosened_duty_cycle` |
| M3 | 删交换区增长线 | RED | **CAUGHT** 1 | `test_each_protection_line_refuses_with_an_explicit_reason[swap_growth_limit]` |
| M4 | 删系统余量线 | RED | **CAUGHT** 1 | 同表 `system_reserve_limit` |
| M5 | 删进程内存线 | RED | **CAUGHT** 4 | 同表 `process_memory_limit` + `test_assert_start_with_injected_probes` + `test_runtime_guard_stops_on_a_violation` + `test_cli_refuses_to_start_on_an_unmet_protection_line` |
| M6 | 删 MLX 峰值线 | RED | **CAUGHT** 1 | 同表 `mlx_memory_limit: peak` |
| M7 | 定位误差恒 0 | RED | **CAUGHT** 1 | `test_localization_known_answer_and_broken_control` |
| M8 | arm3 预算 +1 | RED | **CAUGHT** 27 | 预登记校验/批准/布局系列 27 条 |
| M9 | final 不再抛 `FinalPartitionSealed` | RED | **CAUGHT** 1 | `test_final_partition_is_sealed_everywhere` |
| M10 | 禁用 CLI 批准门（anchor 移到新门） | RED | **CAUGHT** 3 | `test_forged_status_with_recomputed_sha_is_refused` 等 3 条 |
| M11 | 禁用 worker 批准门（anchor 移到新门） | RED | **CAUGHT** 2 | `test_worker_refuses_train_without_an_approval_line`、`test_worker_records_the_approval_line_and_sha_in_the_runstore` |
| M12 | `parameters_unchanged` 恒真 | RED | **CAUGHT** 1 | `test_smoke_reports_an_update_when_a_parameter_really_changed` |
| X1 | 批准行不再比对 SHA（额外探针） | RED | **CAUGHT** 3 | off-by-one / 旧文档 / `test_approval_requires_the_exact_document_sha` |
| X2 | `verify` 源绑定恒报 passed | RED | **CAUGHT** 1 | `test_source_binding_is_rehashed_and_drift_is_fatal` |
| X3 | `verify` 独立参数重算恒报 passed | RED | **CAUGHT** 2 | `test_verify_recomputes_parameters_instead_of_trusting_the_flag` 等 |
| X5 | RunStore 快照不记批准行原文 | RED | **CAUGHT** 1 | `test_worker_records_the_approval_line_and_sha_in_the_runstore` |

基线（未变异）`106 passed in 2.21s`。P10↔r2 harness 的 anchor 比对：M1–M9、M12 逐字节相同，只有 M10/M11 移动（`evidence/harness-anchor-diff.json`）。

## F1 逐类结果（真实 CLI，沙箱桩 train）

| 类 | 构造 | 期望 | 实测 | 证据 |
|---|---|---|---|---|
| C1 | 只改 status=approved + 重算 canonical SHA + 重写侧车（自洽） | exit 3 | **3** `preregistration_not_approved` | `forged_document_sha256 a36d4b15…`（self_consistent=true） |
| C2 | 批准行缺失（只有说明性文字） | exit 3 | **3** | — |
| C3 | 批准行 SHA 差一位（…c00） | exit 3 | **3** | detail 记录 frozen=SHA、log=[…c00] |
| C4 | 批准行指向 r1 旧文档 32c30f50… | exit 3 | **3** | detail 两条 SHA 都在 |
| C5a | **执行层可写位置伪造批准文件，`--research-log` 指向它** | exit 3 | **0 → 放行** | RunStore 记 `research_log=/private/tmp/v9p11/f1/forged/RESEARCH_LOG.md`、approved=true |
| C5b | 预登记旁伪造 `APPROVAL.json`/`pre_registration.json.approved` | exit 3 | **3** | 侧车被忽略 |
| C5c | 默认 `RESEARCH_LOG.md`（可写副本）被写入批准行 | 设计允许 | **0** | 与 C6 同路径（见 R-6：唯一屏障是写权限） |
| C6 | 完全一致的批准行（正例） | exit 0 + 入账 | **0** | 行原文/行号 4/文档 SHA/log SHA 四项与我重算一致；状态链 created→initializing→training→completed；optimizer_steps 0 |
| C7 | 同一伪造日志 + 换掉 `data_identity.dataset_digest` 的文档 | — | **0** | 说明凭据只钉文档 SHA，不钉数据/参数来源（与 R-3 同源） |

## 发现（按严重度）

| ID | 级别 | 问题 | 证据 | 建议 |
|---|---|---|---|---|
| **R-1** | **高** | F1 第 5 类未关闭：`--research-log` 由调用方指定，执行层把批准行写进自己的文件即可自批；RunStore 里留下的批准记录与合法记录**无法从字段区分**（只有路径不同） | C5a（exit 0 + 入账） | `mode_train` 固定只认 `spec.RESEARCH_LOG`（或要求 `log_path.resolve()==spec.RESEARCH_LOG.resolve()`，否则 exit 3）；测试改用 monkeypatch `spec.RESEARCH_LOG`，不要保留可被 CLI 指定凭据位置的口子 |
| **R-2** | **高** | `train` 不校验源绑定：同一棵树 `train` exit 0、`verify` exit 1 `source_binding_drift`；冻结的 12 项源 SHA 只在 verify 生效，**真正跑训练的入口不查** | `evidence/train-binding-gap.json` D1/D2（worker.py bound `08f758…` vs tree `3c33b3…`）；AST：`mode_train` 不含 `_source_binding_state` | `mode_train` 里加 `_source_binding_state`，drift → exit 3 `source_binding_drift`；`_train` 开头再查一次（纵深防御） |
| **R-3** | 中 | `train` 不比对数据集摘要：`_train` 只 `resolve_dataset_dir(output_root)`，从不读 `document["data_identity"]`；ref 只保证"目录名=ref digest"，与冻结文档无关 | AST 事实 + `resolve_dataset_dir` 签名无 document 参数；C7 实测换 digest 的文档照样放行 | `mode_train` 断言 `resolve_dataset_dir(...).name == document.data_identity.dataset_digest`，否则 exit 3 |
| R-4 | 低 | r2 报告正文写 M8「26 failed」，自身 `mutations.json` 是「27 failed」；我复跑也是 27 | `results/mutations-v9p11.json` | 更正正文数字 |
| R-5 | 低 | 账本 `active_seconds` 记的是**预留**不是实测（data 46 s → 350.58 s，smoke 5.6 s → 184.79 s），`daily_budget` 已用 535.37/14400 | S1 账本只读查询 | 按 README 属既定口径，但建议在报告里点明"预留≠实际"，避免复核者误读 |
| R-6 | 信息 | 批准凭据的唯一屏障是"执行层不写 RESEARCH_LOG.md"这一纪律，无技术约束（C5c）；若要做到技术保证，需二级不可写 + 批准行带签名或双人复核 | C5c | 由一级决定是否风险接受；若接受，卡面第 5 类判定口径要同步改写 |
| R-7 | 信息 | `evaluate()` 的 duty 分支在合法运行里仍不可达（生产 limits 恒 0.25 且 `validate_limits` 拒 >0.25），只能在 `RuntimeGuard` 直接构造时触发；真正的 F2 保证来自 pacer 行为测试。pacer 的 `min(rest,2.0)` 上限、不计 checkpoint eval 时间是既有 F9，S1 单步 6 ms 下无影响 | 代码 + 测试 | 记录，不需要改 |
| R-8 | 信息 | reports/V9-P9/r2 放的是完整冻结文档副本（21 KB）+ 1 MB 数据集清单；符合"清单与 SHA"的合理解释，但与 notice #297 字面略有出入（不是数据集字节） | 目录实测 | 记录 |

## 失败与限制

1. **本复核未跑任何真实训练**：`train` 正例/伪造例都在"沙箱副本 + `_train` 桩"下跑，只证明"批准门放行 + 登记 run + 调用 `_train`"，不证明训练循环正确（与 P9 同一边界）。
2. 未重建数据集（17 MB，直接用现成副本）；只按 ref/manifest/digest 关系校验，未逐 packet 复核 9500 条语义。
3. 沙箱 verify 需要 A2 基线 manifest 与 pilot checkpoint 副本（`reports/V9-baseline`、`artifacts/pilot/…/96b72328-…`），已只读复制；未验证真实 `artifacts/v9/s1` 双根在**新**数据生成时的落盘（未重跑 data 模式）。
4. `relay exec` 本机仍不可用（ps 枚举被拒，P9/P10 已记录），本卡长命令用直跑，墙钟：变异 84 s + 99 s、F1 ≈ 25 s、verify ≈ 3 s。
5. 未验证 r1→r2 测试文件的逐行差异（s1 包与 tests 均未被 git 跟踪，无基线可比）；改用"变异全部被正确用例捕获 + 4 个额外探针"作为强度证据。

## 交回统筹

1. **建议打回，只差 F1**：P-1 修 R-1（train 只认 `RESEARCH_LOG`，取消可指定的批准文件路径）；P-2 修 R-2（train 校源绑定）；P-3 修 R-3（train 校数据集摘要）。修完重冻（会换 document SHA）→ 重跑 12 变异 + 我的 C5a/C5b/C6 → 再请复核。
2. **在此之前不要写 `APPROVED s1-phase1 prereg document_sha256=0547744fc142adae198b6d2fcfe6a6ac273fa092857649361bbf2dd157a14c07`**：P-1/P-2 改的是 `commands.py`/`worker.py`，它们进源绑定，重冻必换 SHA，这条批准行会立刻作废。
3. 若一级决定**风险接受** C5a（理由：执行层本就不该写 RESEARCH_LOG.md，`--research-log` 仅为测试），则请把卡面第 5 类改为"显式风险接受 + 记录"，并把 R-2/R-3 作为 V9.P1 开跑前必修。在此口径下其余 6 项全部通过，可批准 `0547744f…`。
4. 其余已复核通过、无需返工：12/12 变异（含归因）、F2 pacer/duty、F4 独立参数重算、源绑定 12/12、预算推导（3510 步/450 s/500 s/4099.6 s）、notice #297 双根、锁忙 exit 4、真实锁与中央账本未动、r2 报告包 SHA 37/37。
