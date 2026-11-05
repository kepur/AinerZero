# ainerzero.V9.P52 执行报告：S1 r14 运行独立复核（复核 P51）

- **角色**：executor（二级独立复核）；**负责人**：`gemini-b4e7`；**时间**：2026-10-28
- **任务状态**：reported；**裁决结论**：**建议通过**
- **复核目标**：`ainerzero.V9.P51`（作者：一级 `claude`）
- **复核人身份**：`gemini-b4e7`（二级执行层，kind: gemini），全新独立外部会话，非 P51 作者，未列于 excluded_agents 排除名单。
- **只读审计与零生产修改**：生产台账只做 shasum，所有 SQLite 数据查询及 JSON 校验均在复制到临时隔离目录的副本（`isolated/phase1_copy/`）中完成；产物严格收敛于 `reports/V9-P52/gemini-b4e7/`。

---

## 1. 生产台账只读与前后一致性
- **生产台账路径**：`artifacts/v9/s1/phase1/control.sqlite3`
- **P51 发起时 SHA**：`fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`
- **P51 停止时 SHA**：`b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`production-ledger-at-stop.txt`）
- **复核开工 SHA**：`b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`evidence/production-ledger-start.txt`）
- **复核收尾 SHA**：`b0314c9d44a356d5330a71ca80951c3c1b6e08e49da123b3e44dcb9bc8ac2648`（`evidence/production-ledger-end.txt`）
- **结论**：复核期间生产台账保持严格 0 写入，台账状态与 P51 报告完全吻合。

---

## 2. 训练作业真实终态、步数与 SHA 核验（6 次）
在隔离数据库与 Relay 服务端核查所有 6 次训练：
1. **arm2 s2 (A2)**：`run_id = 33d09a1266bd4d9eabc2e59050048658`，作业 `job-5fed34f5…`
   - 终态：DB `state=completed`，Relay `status=completed`，返回码 `rc=0`，进程组 `group_empty=True`（监督确认空）。
   - 步数：优化器步数 3510，收据确认 3510。
   - 参数 SHA：当场复算 `params.npz` SHA256 为 `f7f9a661f24140404005325aec714bba85970f323333940ba934458821accf01`。
   - **A2 结论**：与 r13 arm2 s2 之 `params.npz` 逐位完全一致，**A2 复现确凿成立**。
2. **arm3 s1**：`run_id = 6d606a3e949f40e0a8077d70e7c02f77`，作业 `job-5455ba0b…`
   - 终态：`completed`，`rc=0`，`group_empty=True`，步数 3510。
   - SHA256：`d4036d8b5bb6689a3be4673aad0b70ba352b132f0c5645a4f5434f0dd4a4fe1b`。
3. **arm3 s2**：`run_id = 3cd7524870174be898382ce15edbaaec`，作业 `job-1a3e11a5…`
   - 终态：`completed`，`rc=0`，`group_empty=True`，步数 3510。
   - SHA256：`3681887a56585b683485a74546eeaca10c35e5bd4bd1349777f37de991972b97`。
4. **arm4 s0**：`run_id = 1c051659ff504acdb76e77f830a279a9`，作业 `job-96e8175c…`
   - 终态：DB `state=stopped`（`reason=budget_exhausted`），Relay `status=failed`，`rc=1`，`group_empty=True`。
   - 步数：3006 / 3510（合盖休眠导致单次墙钟超限），无最终 `params.npz`，环境失败记录如实。
5. **arm4 s1**：`run_id = bc0264a2f90d4a688bb0abe571fa90c7`，作业 `job-afc407d4…`
   - 终态：`completed`，`rc=0`，`group_empty=True`，步数 3510。
   - SHA256：`dae8d526ff27eaa7e619bc933b2f51a7a4c01a2ea065e252f6123956a05517d2`。
6. **arm4 s2**：`run_id = a5c631f535354e628d8f38d25361bef3`，作业 `job-92364f4c…`
   - 终态：`completed`，`rc=0`，`group_empty=True`，步数 3510。
   - SHA256：`3b1d9e03f897363c9f63e5e26749ec07067fc3cbeb68c2ddf3d94bf62286c604`。

---

## 3. 评测作业终态、继承绑定与缺陷核查（6 次）
核对所有启动的 6 次评测作业 stdout 日志与 Relay 状态：
1. **eval-arm1**：作业 `job-abce86ba…`，终态 `completed`，`rc=0`，`group_empty=True`。
2. **继承格绑定核查（3 格全中）**：
   - `eval-arm2-seed0`：stdout 明确记录 `eval_binding.inherited.source_run_id` 为 `19f2d1eb4bf04da4909d87501348028d`（属于 r13），绑定无误。
   - `eval-arm2-seed1`：stdout 明确记录 `eval_binding.inherited.source_run_id` 为 `7d155060fecc4070a9a68e95fb3761fa`（属于 r13），绑定无误。
   - `eval-arm3-seed0`：stdout 明确记录 `eval_binding.inherited.source_run_id` 为 `403ae816720c4ad9b4f75ecd86e7b109`（属于 r13），绑定无误。
3. **评测缺陷核实（5 格失败）**：
   - `eval-arm2-seed0`、`eval-arm2-seed1`、`eval-arm2-seed2`、`eval-arm3-seed0`、`eval-arm3-seed1` 均在几秒内退出（`status=failed`，`rc=1`，`group_empty=True`）。
   - 报错信息一致为 `ValueError: matmul: Input operand 1 has a mismatch in its core dimension 0 ... (size 224/192 is different from 32)`，确系 `evaluation.few_shot_report` 中查询向量未做切片与节点维度失配所致。
   - 缺陷诊断已在隔离环境确认，P51 未继续盲目消耗预算，果断停止驱动，处置合规。

---

## 4. 阶段墙钟、防重跑与未启动清单核验
- **阶段总墙钟**：首次启动时间 13:00:14，最后作业完成 14:50:14，总耗时约 6590 s，**严格处于 9000 s 上限之内**。
- **未启动清单（not_run）**：`arm3 s2`、`arm4 s0`、`arm4 s1`、`arm4 s2` 的评测未启动，数据库中无对应 run 记录。
- **零重跑**：12 项已执行的请求在数据库中无任何重复（无任何格被重跑）。

---

## 5. 最终结论
各项运行结果、参数哈希、A2 复现逐位一致性、继承绑定及进程组终态均真实可靠，生产台账全程只读保持原样。
**建议通过**（accept）。
