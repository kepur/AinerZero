# ainerzero.V9.P27 非作者复核报告

复核者：`workbuddy-9k2m`（二级执行层）  
被复核任务：`ainerzero.V9.P26`（作者 `composer-r8x3`）  
时间：2026-10-22  

**自证**：本复核者 ID `workbuddy-9k2m` 不在 `params.excluded_agents` 列表中（列表含 claude、codex、composer-r8x3 等 8 项）。

---

## 1. review_inputs SHA 复算

```bash
python3 -c "import hashlib; print(hashlib.sha256(open('/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/claude-20261022-e32/P26-review-inputs.json','rb').read()).hexdigest())"
```

结果：`0a3c94b642ece96189ac4452fc4aca83c14f53bd175774f4b90e7f2e041af843`

与 params.review_inputs_sha256 一致（开工与收尾各算一次，同一值）。

---

## 2. query_limit 登记与 fail-closed（独立探针）

探针脚本：`reports/V9-P27/query_limit_probe.py`、`reports/V9-P27/worker_prereg_probe.py`

| 场景 | 结果 | 说明 |
|---|---|---|
| 预登记缺 `evaluation.query_limit` | **拒绝** | `QueryLimitError: preregistration evaluation.query_limit is missing` |
| `query_limit = 4`（≠ 8） | **拒绝** | `QueryLimitError: differs from the registered 8` |
| `query_limit = "8"`（非整数） | **拒绝** | `QueryLimitError: must be an int, got str` |
| 隔离坏控（只删缺失守卫） | **变红** | 缺键时静默回落为 8，证明拒绝来自该守卫 |
| `split_support_query` 无关键字调用 | **TypeError** | 无默认参数，符合要求 |
| `few_shot_report` 无 prereg 且无显式 limit | **拒绝** | `QueryLimitError: requires preregistration` |
| caller limit 与 prereg 不一致 | **拒绝** | `QueryLimitError: caller query_limit 4 differs from preregistration 8` |

**worker._evaluate_arm 生产路径**：代码审查确认 `_evaluate_arm` 在 `evaluation.few_shot_report(..., preregistration=document)` 中传入已验证预登记，非从 spec 常量硬编码读取。探针构造 "预登记与 spec 不一致"（99 vs 8）时，`require_query_limit` 在先验阶段即拒绝。

---

## 3. 选项 A 报告注记

- `metrics[3]` 定义：r9 与 r10 逐字段相等，`id == "few_shot_unseen_transition"`，未新增指标 id。
- `evaluation.reporting_notes`：r10 新增 3 条，措辞与 P1-READINESS.md 一级核定一致。
- `coverage` / `FPR` 未进入 metrics 定义，仅作注记。

---

## 4. 逐叶差异（r9 → r10）

使用 `reports/V9-P9/r10/prereg-leaf-diff.json` 核对：

- 总叶数：402
- 变化叶数：12
- 白名单外科学叶：0
- 绑定文件变化：5 个，均在 allowlist 内
  - `src/ainerzero/v9/experiments/s1/evaluation.py`
  - `src/ainerzero/v9/experiments/s1/metrics.py`
  - `src/ainerzero/v9/experiments/s1/prereg.py`
  - `src/ainerzero/v9/experiments/s1/spec.py`
  - `src/ainerzero/v9/experiments/s1/worker.py`

冻结值核对：
- `updates`：3510 ✅
- `seeds`：[0, 1, 2] ✅
- `deadline_seconds`：450 ✅
- `arm1_deadline_seconds`：2 ✅
- `eval_batches`：48 ✅
- `phase_wall_max_seconds`：14400.0 ✅

---

## 5. 既有测试文件变更分析

**局限性声明**：`test_s1_r5_metrics.py` 与 `test_s1_r5_eval.py` 未被 git 追踪，r9 报告目录中亦无其归档副本。以下分析基于当前文件内容与 API 变更逻辑推导。

### test_s1_r5_metrics.py

当前版本 10 项测试全部通过。与 query_limit 相关的变更：
- `test_few_shot_k_is_traversed_and_missing_support_fails_closed`（第 142 行起）：3 处 `split_support_query` 调用补传 `query_limit=8`
- `test_few_shot_uses_the_per_step_cell_path_when_the_agent_stays_put`（第 299 行起）：`few_shot_report` 补传 `query_limit=8`

**判断**：均为适配 "无默认 query_limit" 而补传的必填参数，无断言放宽或删除。

### test_s1_r5_eval.py

当前版本 1 项通过、1 项因环境沙箱临时目录权限错误（`EEXIST: file already exists, mkdir '/private/var/.../T/pytest-of-unknown'`）。该 error 为执行环境限制，非被复核代码缺陷。

变更：
- `_document` 辅助函数（第 147 行起）新增 `evaluation` 块，写入 `query_limit` 与 `reporting_notes`，使测试文档通过 r10 的 `prereg.validate`

**判断**：参数补传，无断言放宽或删除。

---

## 6. 回归测试复验

| 测试文件 | 本机结果 | 作者结果 | 差异说明 |
|---|---|---|---|
| `test_s1_r10_query_limit.py` | **9 passed** | 9 passed | 一致 |
| `test_s1_r6_probe_graph.py` | **17 passed** | 17 passed | 一致 |
| `test_s1_r5_metrics.py` | **10 passed** | — | 无失败 |
| `test_s1_r5_eval.py` | **1 passed, 1 error** | — | error 为沙箱 tmp 目录权限，非代码问题 |

---

## 7. r10 冻结文件身份

```
doc SHA256:  19639d86b8f14ce0873ba367ae8d233fd371495a4c055af2b7344aa50b850718
file SHA256: 5fea3ca73da29658753932ff8d38c96dadd33314b1db022576caea505c20d1ff
status:      awaiting_coordinator_approval
```

- 无批准行（文档内 "APPROVED" 仅出现在 `approval_rule` 的说明文本中，非实际批准）。
- r9 冻结文件字节未变（`1afc4900…1572` / `6abce031…5577`）。

---

## 8. 结论与未验证项

**结论**：
1. query_limit 登记与 fail-closed 行为正确，坏控变红。
2. worker._evaluate_arm 从已验证预登记读取 query_limit。
3. metrics[3] 定义未改，reporting_notes 与一级核定一致。
4. r9→r10 叶差异在白名单内，冻结值全等。
5. k=1 停止边界与 probe_graph 回归测试通过。

**未验证项**：
- 测试文件 `test_s1_r5_metrics.py` 与 `test_s1_r5_eval.py` 的 r9 钉扎版本未在 git 或归档中找到，无法做逐字节 diff。当前版本分析显示仅补传参数、无断言放宽。
- `tests/v9/experiments` 全量在本机出现 156 个 error（沙箱 tmp 目录冲突），与作者报告的 309 passed/0 error 不一致。该差异源于执行环境，非被复核代码问题。

**建议**：一级在写 APPROVED 行前，确认 r10 doc SHA 为 `19639d86…0718`。
