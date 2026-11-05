# ainerzero.V9.P30 执行报告（S1 预登记 r11：方案 A 重冻结）

角色：executor（二级执行层）；负责人：`composer-m7k2`（接手 `step5-ub8z` 租约过期后的半成品）；时间：2026-10-23
任务状态：reported（未 accepted）；实验状态：未执行真实训练/评测（本卡为纯 CPU 工程卡）
任务依据：`RESEARCH_LOG ## R20261023-S1-phase1-r11-budget`（用户批准方案 A）；前置 P1/P2 accepted
输入身份：`reports/V9-P9/r11/source-identity.json`（binding passed，0 漂移）；前值归档 `reports/V9-P9/r11/before/`

## 摘要（30 行内）

- **承接**：`step5-ub8z` 已完成 before 归档、spec/prereg/worker/commands 与 17 条 r11 测试；本棒补齐冻结、入口三模式、叶差异与报告。未重写已通过的登记路径代码。
- **登记值**：updates=3510、deadline=1200（`deadline_source=user_approved R20261023-S1-phase1-r11-budget`）、supervision=1250、eval_batches=175、seeds=[0,1,2]、checkpoint_updates=[0,439,878,1755,3510]。
- **推导值（公式如实）**：estimate≈381.15 s、derived_deadline=477、arm1_deadline=**7 s**（卡面「约 6 s」）、phase_wall≈10854.6 s ≤14400。
- **吞吐注记**：中位 0.20182 / 最慢 0.2829 s/步；3510×最慢≈992.98 s；1200/992.98≈1.2085（约 21% 余量）；来源 `reports/V9-S1/metrics.json` SHA `8b5017c2…`。
- **新实验 ID**：`s1-phase1-20261023-r11`；旧实验 `s1-phase1-20261021` 行/attempt/失败不动；作用域守卫有测试。
- **重冻结**：`artifacts/v9/s1/phase1/r11/`，doc `b73b5589…fb4e`，file `aeb8a7a8…f105`，状态 `awaiting_coordinator_approval`；r10 原件 file SHA 仍为 `5fea3ca7…d1ff`。
- **叶差异**：431 叶，58 变化；白名单外科学叶 **0**；绑定变化仅 spec/prereg/worker/commands。
- **入口（无 MLX）**：verify completed；train 在 `preregistration_not_approved` 拒绝（exit 3）；eval 175 过预算门后 `EvalBindingError`；48 对照 `eval_call_budget_exceeded`（175 window-probe）。
- **测试**：r11 注册 17 passed；`tests/v9/experiments` 325 passed / **1 failed**（既有真实台账拷贝断言，r10 运行后环境性，before 对照同失败）；其余 `tests/v9` 378 passed。
- **未执行**：真实 MLX、训练、评测、读 final、写批准行、写中央台账、启动运行。
- **交回**：等 P31 非作者复核；工程绿 ≠ 能力通过；批准行由一级在复核后写。

## 1. 起始对账与接手说明

- 前值：`reports/V9-P9/r11/before/`（47 个 .py + SHA256SUMS）。
- 上一棒进度见 `PROGRESS-step5-ub8z.md`：代码与 17 测已完成；缺 r11 冻结产物与入口验证。
- 本棒相对上一棒的修正：`refreeze_draft` **保留 r10 arm 行**（避免 `build_draft` 重写 arm1 identity 新增键导致叶差异出白名单）；eval 48 对照用「r11 文档改 eval_batches=48」隔离预算门（完整 r10 冻结件在当前源码绑定下会 `source_binding_drift`）。

## 2. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python reports/V9-P9/r11/harness/refreeze_draft.py
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r11 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify --output-root artifacts/v9/s1/phase1/r11
.venv/bin/python -m ainerzero.cli s1-phase1 --mode train --arm arm2 --seed 0 \
  --output-root artifacts/v9/s1/phase1 \
  --prereg artifacts/v9/s1/phase1/r11/pre_registration.json
.venv/bin/python reports/V9-P9/r11/harness/entry_eval_check.py
.venv/bin/python reports/V9-P9/r11/harness/prereg_leaf_diff.py
.venv/bin/python reports/V9-P9/r11/harness/source_identity.py
.venv/bin/python reports/V9-P9/r11/harness/collect_shas.py
.venv/bin/python -m pytest tests/v9/experiments/test_s1_r11_registration.py -q -p no:cacheprovider
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider
.venv/bin/python -m pytest tests/v9 -q -p no:cacheprovider --ignore=tests/v9/experiments
```

长命令经 `relay exec`；未写批准行；未碰中央台账写路径（train 在批准门拒绝；eval 用临时 host）。

## 3. 登记路径与 fail-closed（上一棒实现，本棒验收）

- `prereg.registered_budget`：登记值路径，不跑缩步数循环；推导会砍步数 / 截止≠1200 / 超单次上限 → 拒。
- `validate`：deadline=1200、supervision=1250、updates=3510、eval_batches=175、`measured_throughput` 与登记块一致。
- `worker.document_experiment_scope`：仅 r11 实验 ID 作用域；旧实验全台账守卫不变。
- 测试：`test_s1_r11_registration.py` 17 条全过（含新实验 attempt=0、旧实验仍拒、坏控）。

## 4. 入口原始结果

| 模式 | 结果 | 证据 |
|---|---|---|
| verify | `status=completed`；approval.approved=false | `logs/verify-r11.json` |
| train | `refused_stage=preregistration_not_approved`；exit 3；未更新参数 | `logs/train-refuse-r11.json` |
| eval 175 | 过 call-budget；`EvalBindingError: no completed run binds…`；experiment_id=r11 | `logs/eval-entry-r11.json` |
| eval 48 对照 | `eval_call_budget_exceeded`；window_probe=175 vs registered=48 | 同上 |

## 5. 验证结果

- r11 注册测试：**17 passed**
- `tests/v9/experiments`：**325 passed / 1 failed**（`test_the_real_ledger_copy_reproduces_the_old_bug…`，真实台账已被 r10 运行改写；上一棒 before 对照同失败）
- 其余 `tests/v9`：**378 passed**
- 叶差异：白名单外 0；r10 file SHA 复检 `5fea3ca7…d1ff` 未变
- 冻结参数：3510 / [0,1,2] / 1200 / 1250 / arm1 7 / 175 / 14400；query_limit=8；reporting_notes 与 r10 一致

## 6. SHA256（脚本直贴）

```
c42413c8d872e0e1554dad3c242926559c14de208b8ec4f4e47e26ac5190becb  src/ainerzero/v9/experiments/s1/spec.py
d3a6029157721c2bd82df101d26c98e2ddc8d9076042fbc61e7a49625f6b4580  src/ainerzero/v9/experiments/s1/prereg.py
237680260e3d57338015168525e24cb11f38f7f9d190865b1ed89933d2894505  src/ainerzero/v9/experiments/s1/worker.py
c66e02c383a13ae30ad7ea509e2ad8f991200cdee1d528b7d58903d420cfb91a  src/ainerzero/v9/experiments/s1/commands.py
290d88de728fa06087c146dfb0bf63eb4608b9c639baad8e8939fb807b818519  tests/v9/experiments/test_s1_r11_registration.py
abb7a672642e4585a8afeb0e3a1d4401b7c8af217193d176c70f83d34ffc752d  tests/v9/experiments/test_s1_prereg.py
27b7d6215ded6a074b707dc2747b8a1862d8796a91d092679bbd592f6ba21d85  tests/v9/experiments/test_s1_r8_completion.py
6940c17f86a47bbd7f2cfb79ded97886e1f6ace35b4f6898c2dd5c18defafd24  tests/v9/experiments/test_s1_r8_d_budget.py
05cf4503b1d9928603e74be9adb6cf18cb8c2ad2b8aa8031a0557998c1a857c2  artifacts/v9/s1/phase1/r11/draft_preregistration.json
aeb8a7a800deab87bce08940489796edb0cc1949cde0f4999163f52decc1f105  artifacts/v9/s1/phase1/r11/pre_registration.json
c297870d60e1dd30abc281616772d06ba578bfd563d09b63b81aef73b4e4d765  artifacts/v9/s1/phase1/r11/pre_registration.json.sha256
3c9fd77953b94d87141c2ac896bd2470f46b952eee65a10e9eed34d4391c1047  artifacts/v9/s1/phase1/r11/dataset_ref.json
5fea3ca73da29658753932ff8d38c96dadd33314b1db022576caea505c20d1ff  artifacts/v9/s1/phase1/r10/pre_registration.json
8b5017c24fb710a3bf55508a8ac917d17cb41e29ba464c32b092e37b14db6ce4  reports/V9-S1/metrics.json
b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8  reports/V9-P9/r1-archive/smoke_metrics.json
b73b558953a06ce551c2e8613a09d0785b1c0222f8ff57f99c49da2ec812fb4e  DOCUMENT_SHA256(artifacts/v9/s1/phase1/r11/pre_registration.json)
```

完整列表：`evidence/sha256sums.txt`。

## 7. 产物

- 冻结：`artifacts/v9/s1/phase1/r11/{pre_registration.json,.sha256,draft_preregistration.json,dataset_ref.json}`
- 报告：本文件、`指标.json`、`source-identity.json`、`prereg-leaf-diff.json`、`PROGRESS-step5-ub8z.md`
- 日志：`logs/verify-r11.json`、`train-refuse-r11.json`、`eval-entry-r11.json`、`freeze-r11.json`、junit XML
- harness：`reports/V9-P9/r11/harness/`

## 8. 失败与限制

- 未写批准行（禁止项）；冻结状态仍为 `awaiting_coordinator_approval`。
- `tests/v9/experiments` 1 条既有失败（真实台账拷贝），非本卡引入。
- arm1 公式结果为 7 s，不是「约 6 s」——按任务要求如实登记、未手改。
- 未宣称训练/时空能力；工程完成 ≠ 晋升。

## 9. 交回统筹

1. P31 非作者复核本冻结（doc `b73b5589…fb4e`）。
2. 复核通过后，一级在 `## R20261021-P1-stageA-budget` 写 r11 批准行（并按细则作废 r10 行格式）。
3. 是否放行 P32 正式重跑由一级决定；本卡不启动运行。
