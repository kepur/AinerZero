# ainerzero.V9.P26 执行报告（S1 预登记 r10：query_limit + 选项 A 注记 + 重冻结）

角色：executor（二级执行层）；负责人：`composer-r8x3`；时间：2026-10-22
任务状态：reported（未 accepted）；实验状态：未执行真实训练/评测（本卡为纯 CPU 工程卡）
任务依据：`claude-20261022-e32/P1-READINESS.md`（走 P18 选项 A）；基线 r9 accepted（`P15-R9-ACCEPT.md`，doc `6abce031…5577`）
输入身份：`reports/V9-P9/r10/source-identity.json`（21 个绑定文件，0 漂移）；`provenance/STARTING-BYTES.json`（r9 起始字节）

## 摘要（30 行内）

- **query_limit 已登记**：预登记新增 `evaluation.query_limit = 8`；`metrics.require_query_limit` / `split_support_query` / `evaluation.few_shot_report` / `worker._evaluate_arm` 均从已验证预登记读取；缺键 fail-closed，无代码默认回落。
- **反例与坏控**：缺键拒绝；`query_limit≠8` 拒绝；只删「缺失即拒绝」守卫的隔离坏控在缺键时错误返回 8（变红），证明拒绝来自该守卫。
- **选项 A 报告注记**：`evaluation.reporting_notes` 三条写入预登记；`metrics[3]`（few_shot_unseen_transition）定义未改、未新增指标 id。
- **既有修复仍在**：`evaluation.py` 保持 `stop=support[-1]+2`；`runtime.py` 保持 metric-map `(r,c)` remap；回归见 `test_s1_r10_query_limit.py::test_k1_stop_boundary…` 与 `test_s1_r6_probe_graph.py`。
- **重冻结**：`artifacts/v9/s1/phase1/r10/`，doc `19639d86…0718`，file `5fea3ca7…d1ff`，状态 `awaiting_coordinator_approval`；r9 原件一字未动（file `1afc4900…1572` / doc `6abce031…5577`）。
- **叶差异**：402 叶，12 叶变化；白名单外科学叶 0；绑定变化仅 spec/prereg/metrics/evaluation/worker。冻结值 3510 / seeds [0,1,2] / 450 / arm1 2 s / eval_batches 48 / 14400 不变。
- **测试**：`tests/v9/experiments` **309 passed**；其余 `tests/v9` **378 passed**；0 失败。
- **未执行**：真实 MLX 前向/训练/评测/final、新数据、下载安装、批准行、中央台账、P1。
- **交回**：等 P27 非作者复核；r10 冻结需一级批准后才可谈 P1。工程绿不等于能力通过。

## 1. 起始对账

- `provenance/STARTING-BYTES.json`：r9 冻结 4 文件 + 21 个绑定源码入库；收工复核 r9 冻结 SHA 仍为 `1afc4900…1572` / `6abce031…5577`。
- 本卡编辑范围：`src/ainerzero/v9/experiments/s1/{spec,prereg,metrics,evaluation,worker}.py`、`tests/v9/experiments/{test_s1_r10_query_limit,test_s1_r5_metrics,test_s1_r5_eval}.py`、`artifacts/v9/s1/phase1/r10/`、`reports/V9-P9/r10/`。

## 2. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P9/r10/harness/archive_starting_bytes.py
.venv/bin/python reports/V9-P9/r10/harness/confirm_prior_fixes.py
.venv/bin/python reports/V9-P9/r10/harness/refreeze_draft.py
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r10 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1/r10
.venv/bin/python reports/V9-P9/r10/harness/prereg_leaf_diff.py
.venv/bin/python reports/V9-P9/r10/harness/source_identity.py
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r10/logs/tests-s1-r10.xml
.venv/bin/python -m pytest tests/v9 -q -p no:cacheprovider --ignore=tests/v9/experiments \
  --junitxml=reports/V9-P9/r10/logs/tests-v9-other-r10.xml
.venv/bin/python reports/V9-P9/r10/harness/collect_evidence.py
```

环境：`PYTHONPATH=<repo>/src`；长命令经 `relay exec`；未加载会误伤 symlink 的 shim。

## 3. query_limit 登记与 fail-closed

代码：

- `spec.EVALUATION.query_limit = 8` + `reporting_notes`（选项 A 三条）。
- `prereg.build_draft` 写入 `evaluation`；`prereg.validate` 缺键 / 异值 / 注记篡改均拒绝。
- `metrics.require_query_limit(document)`：缺键 / 非 int / ≠ 登记值 → `QueryLimitError`。
- `metrics.split_support_query(..., query_limit=)`：**无默认参数**；异值拒绝。
- `evaluation.few_shot_report(..., preregistration=...)`：生产路径读预登记；fixture 可显式传登记值。
- `worker._evaluate_arm`：`preregistration=document` 传入。

证据（`test_s1_r10_query_limit.py`）：

| 场景 | 结果 |
|---|---|
| 缺 `evaluation.query_limit` | `QueryLimitError` + validate 失败 |
| `query_limit=4` | `QueryLimitError` + validate 失败 |
| 坏控（只删缺失守卫） | 缺键时错误返回 8 → 变红 |
| `split_support_query` 无关键字 | `TypeError`（无默认） |

## 4. 选项 A 报告注记（不改 metrics[3]）

预登记 `evaluation.reporting_notes`：

1. k=8 永远标 `insufficient_data`（0/200 世界有样本），不得记成 0 或满分；
2. k 曲线按 family 分开报告，不合并；
3. coverage 事实（k=8: 0/200；k=4: 50/200 且仅 navigation）只作注记；coverage/FPR 不是本阶段指标。

`metrics[3]` 定义与 r9 逐字段相等；未新增指标 id。

## 5. 既有修复确认

| 修复 | 源码位置 | 回归测试 |
|---|---|---|
| k=1 stop=`support[-1]+2` | `evaluation.py`（SHA `90e174c0…fb92`） | `test_s1_r10_query_limit.py::test_k1_stop_boundary_is_support_last_plus_two` |
| probe_graph metric-map `(r,c)` | `runtime.py`（SHA `d5417b18…60df`） | `tests/v9/experiments/test_s1_r6_probe_graph.py` |

详见 `evidence/prior-fixes.json`。

## 6. 验证结果

- `tests/v9/experiments`：**309 passed**（r9 的 300 + 本卡 9），0 failed/skipped（`logs/tests-s1-r10.xml`）。
- 其余 `tests/v9`：**378 passed**，0 failed（`logs/tests-v9-other-r10.xml`）。
- 冻结：`--mode verify` completed；doc `19639d86b8f14ce0873ba367ae8d233fd371495a4c055af2b7344aa50b850718`；file `5fea3ca73da29658753932ff8d38c96dadd33314b1db022576caea505c20d1ff`；状态 `awaiting_coordinator_approval`（无批准行，符合本卡禁止项）。
- 叶差异：402 叶，12 变化，白名单外 0；绑定变化 5 文件均在 allowlist。
- 冻结参数：3510 / [0,1,2] / 450 / 2 / 48 / 14400；`query_limit=8`。
- 预算：本卡未消耗训练/评测预算；未写中央台账。

## 7. 产物

- 报告：本文件、`metrics.json`、`source-identity.json`、`prereg-leaf-diff.json`
- 证据：`evidence/prior-fixes.json`、`evidence/r10-tests.json`
- 日志：`logs/tests-s1-r10.xml`、`logs/tests-v9-other-r10.xml`、`logs/verify-r10.txt`
- 冻结：`artifacts/v9/s1/phase1/r10/{pre_registration.json,.sha256,draft_preregistration.json,dataset_ref.json}`
- 来源：`provenance/STARTING-BYTES.json`、`provenance/PROVENANCE.json`
- 复现：`harness/*.py`（只写 `reports/V9-P9/r10/` 与 `artifacts/.../r10/`）

## 8. 失败与限制

- 未运行真实 MLX 前向/训练/评测/final；未生成新数据；未下载/安装；未写批准行与中央台账；未启动 P1。
- 选项 A 下评测墙钟仍无实测（P1-READINESS 已标给用户的 B3 风险）；本卡不替用户决定 B3。
- D 真实前向成本仍未知（沿用 2 s 冻结值）。

## 9. 交回统筹

1. r10 是否接受：query_limit 正/反/坏控齐备；reporting_notes 已登记；r9→r10 叶差异在白名单内。
2. 需要一级决定：是否批准 `artifacts/v9/s1/phase1/r10/`（本卡不写批准行）；P27 非作者复核后，再核对 doc SHA 写 APPROVED。
3. P1 仍 blocked，直至一级写批准行并处理评测墙钟风险（建议用户批 B3 或接受选项 A 风险）。
