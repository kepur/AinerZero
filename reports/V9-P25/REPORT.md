# ainerzero.V9.P25 执行报告（非作者复核 · S1 r9）

**自证（第一行）：** 执行者 `composer-m7k2` **不在** `params.excluded_agents`（claude / codex / deepseek-r7xq / deepseek-v41f-r9x2 / deepseek-v41f-w3q7 / ds-s1r5-1021n / ds-s1r6b-1022 / ds-s1r8-1200 / gemini-b7m9 / minimax-p21-1022am / step5-k7m2）中；不是其中任何会话的换名或子执行者；也不是被验证任务 `ainerzero.V9.P15` 的作者 `deepseek-v41f-r9x2`。

角色：executor（二级 · verify）；负责人：`composer-m7k2`；时间：2026-10-22
任务状态：reported；实验状态：未执行真实训练/评测（只读 CPU 复核）
任务依据：P15-R8-DECISION R1/R2；S1-R8-DECISION F3/F1；params v1（`review_inputs` 钉扎）
输入身份：`P15-r9-review-inputs.json` sha256=`b8e0a4ddb49102d87de73b9bef680774f39a5130c7e293b6257450f2dac1358e`（与 params 一致）
修改文件：仅 `reports/V9-P25/`（harness / logs / 本报告 / 指标）；**未改源码、未写中央台账/批准行、未跑 MLX**
结论：**建议通过**

## 摘要（30 行内）

- 接力上一棒半成品：沿用并审阅 `harness/verify_pinned.py`、`r1_probe.py`、`r2_probe.py`、`r1_concurrency_probe.py`（原 step5p-4b89/9q4t 起草）；本棒 **全部用 `relay exec` + `.venv/bin/python` 独立重跑**；新增 `f4_f5_spotcheck.py`、`leaf_diff_check.py`。
- 钉扎：74/74 OK；r8 原件 22、P24 原件 34、`artifacts/v9/s1/phase1/r8/` 自核全部字节不变；相对 r8 仅 `worker.py` 变为 r9 钉扎 `7fa74b18…b3aa`。
- R1：先 D 后 train / 先 train 后 D 同实验 ID 成功，预算 2.0 s / 450.0 s；异 manifest 双拒；拆 `_manifest_digest_matches` 坏控变绿（反向变通过）。
- R2：before / inside-after / 无标记终态 二次 `_complete_run` 皆 `refused` 且如实报账本；拆 `_completion_precondition` 坏控复现 `completed`+ledger=`failed`。
- must_also：两进程并发 `ensure_shared_experiment`（同/异 manifest×10 轮）行为符合预期；普通 `.venv` 回归计数与作者一致（300 + 378）。
- F4/F5 抽查通过；r8→r9 叶差 3 叶全在白名单，科学字段全等；冻结 3510 / [0,1,2] / 450 / 2 / 48 / 14400 未变。
- **工程复核建议通过 ≠ 能力通过；不授权 P1 / 真实训练。**

## 1. 钉扎 SHA（脚本输出直接粘贴）

命令：

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P25/harness/verify_pinned.py
# 关键：shasum -a 256 … → reports/V9-P25/logs/key-sha256.txt
```

关键摘要（完整逐文件列表见 `logs/pinned-verify-rerun.txt` / `logs/pinned-verify.txt`）：

```
== review_inputs.json sha256 = b8e0a4ddb49102d87de73b9bef680774f39a5130c7e293b6257450f2dac1358e  match=True
== pinned files: total=74 ok=74 mismatch=0 missing=0
r8 originals mismatch=0
p24 originals mismatch=0
r8 freeze dir self-check mismatch=0
worker.py actual=7fa74b18…b3aa matches_r9_pin=True changed_vs_r8=True
TOTAL PROBLEMS = 0
```

关键文件 SHA（`shasum -a 256`）：

| 路径 | sha256 |
|---|---|
| `P15-r9-review-inputs.json` | `b8e0a4ddb49102d87de73b9bef680774f39a5130c7e293b6257450f2dac1358e` |
| `logs/pinned-verify.json` | `fc2516bbe19e66ceca1b15b500eee94836ea41395d5e0c6a277056c565953cf9` |
| `worker.py`（当前） | `7fa74b18c47d0b1c8cddf717d8287b3a0822c9d57dec00fc09cba4f14d8fb3aa` |
| `artifacts/.../r9/pre_registration.json` | `1afc49006cc264980b29741eacdab38ab7a09814c43823226f057debf0df1572` |
| `artifacts/.../r8/pre_registration.json` | `e8cfa2390624fdf6e82829a658942e11bc012043ae8fba5602d76d9189c8114a` |

## 2. R1 共享 TRAIN 实验（独立临时库探针）

命令：`.venv/bin/python reports/V9-P25/harness/r1_probe.py`

```
A_d_then_train: error=None d=completed train=completed same_experiment=True budgets={'d': 2.0, 'train': 450.0} one_experiment_row=True breakdown_sees_both=True
B_train_then_d: error=None d=completed train=completed same_experiment=True budgets={'d': 2.0, 'train': 450.0} one_experiment_row=True breakdown_sees_both=True
C_foreign_manifest: d=refused/train_experiment_manifest_mismatch train=refused/train_experiment_manifest_mismatch runs_registered=0
D_sabotage: d=completed train=completed  （隔离副本只删 manifest 比对 → 反向变通过）
```

证据：`logs/r1-shared-experiment.json` sha256=`378c641216d673f9fc6019f0954fb0720f04c86f3af3d79d7249493bca0d8147`

## 3. R2 完成入口诚实

命令：`.venv/bin/python reports/V9-P25/harness/r2_probe.py`

```
before_truncation: PASS second=refused/completion_already_invalid ledger=failed
after_truncation: PASS second=refused/completion_already_invalid ledger=completed
terminal_without_marker: PASS second=refused/ledger_terminal_not_completed ledger=failed
sabotage_control: second_status=completed ledger=failed bug_reproduced=True
```

证据：`logs/r2-completion-precondition.json` sha256=`477940bf8381ec22f0fb6080a439f8cf6f93e2538811bcb5b82171aa3e66e7a7`

## 4. must_also① 两进程并发 `ensure_shared_experiment`

命令：`.venv/bin/python reports/V9-P25/harness/r1_concurrency_probe.py`

```
same_manifest tally: {"slot0(same):returned|slot1(same):returned": 10}
same: all_both_returned=True  exactly_one_row=True
foreign_manifest tally: mismatch|returned 与 returned|mismatch 合计 10；无意外逃逸；exactly_one_row=True
```

（作者只覆盖 LifecycleError 重读路径；本探针用真实双进程竞争，**已验证**。）

证据：`logs/r1-concurrency.json` sha256=`72f0af634996cd5808199cc1d6659ec74b9e48ef1c84b7ca055f84b57ceb6322`

## 5. F4 / F5 抽查 + 回归（must_also② `.venv`）

F4/F5（只读复用钉扎的 P24 `probe_core.case_f4/f5`，不调作者 `test_s1_r9_*`）：

```bash
.venv/bin/python reports/V9-P25/harness/f4_f5_spotcheck.py
# f4_pass=True second=refused/already_attempted
# f5_pass=True nan_refused=True reserved_count=8 ts_count=6
```

回归（普通 `.venv`，**未**设 `PYTHONPATH=src`）：

```bash
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider
# 300 passed in 15.48s
.venv/bin/python -m pytest tests/v9/geometry tests/v9/contracts tests/v9/teachers tests/v9/tokenization -q -p no:cacheprovider
# 378 passed in 27.73s
```

与作者报告计数一致（300 / 378，0 失败）。

## 6. r8→r9 逐叶差异

命令：`.venv/bin/python reports/V9-P25/harness/leaf_diff_check.py`

- 作者 `prereg-leaf-diff.json` sha 钉扎匹配；独立重走 398 叶，**仅 3 叶变化**：`created_unix`、`source_identity.package_files.…/worker.py`、`source_identity.package_map_digest`。
- `bound_files_outside_allowlist=[]`；`non_identity_leaves_outside_allowlist=[]`。
- 冻结常量：`updates=3510`，`seeds=[0,1,2]`，`deadline_seconds=450`，`arm1_deadline_seconds=2`，`eval_batches=48`，`phase_wall_max_seconds=14400.0`。

证据：`logs/leaf-diff-check.json` sha256=`ecf177045fe5feeecc81bf7c2bc923b8319ea975bb549fe637adebbd310d55c1`

## 7. 对上一棒的处理

- step5p-4b89 / step5p-9q4t：失租；留下钉扎脚本与部分日志。
- 本棒：审阅脚本逻辑后全部重跑；补 F4/F5、叶差独立核对与并发探针确认；不采信未签字的半成品结论。

## 失败与限制

- 未跑真实 MLX / 训练 / 评测 / final；未生成新数据；未下载安装；未启动 P1。
- 探针 JSON 内 `probe_by` 字段仍标脚本起草者 step5p-9q4t；**实际重跑与签字人为 composer-m7k2**（见本报告与 relay 执行记录）。
- D 真实成本仍未知。

## 交回统筹

- **建议通过** P15 r9 工程项（R1/R2 + 钉扎 + 叶差 + 回归抽查）。
- 是否 accept / 是否批准 r9 冻结进 P1：一级决定；本卡不写批准行。
