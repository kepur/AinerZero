# ainerzero.V9.P1 执行报告
角色：executor；负责人：composer-6bf9；时间：2026-10-23
任务状态：reported；实验状态：failed（训练均未完成冻结步数；arm1 复验完成；arm2/3/4 eval 拒绝）
任务依据：接力台 ainerzero.V9.P1 参数 v1；RESEARCH_LOG R20261021-P1-stageA-budget 批准行 776；r10 预登记 document SHA `19639d86…0718`
输入身份：`--prereg artifacts/v9/s1/phase1/r10/pre_registration.json`（file SHA `5fea3ca7…d1ff`）；dataset_digest `8234f2f3…ad26`；不改源码
修改文件：仅 `reports/V9-S1/` 与 `artifacts/v9/s1/phase1/`（RunStore/训练产物/检查点）
实际执行：verify×1 + train×9 + eval×10，全部经 `relay submit-job`（auth `ainerzero:registration/19639d86…0718`），串行
验证结果：见下表与 `metrics.json`；**不宣称能力晋升**
产物：`reports/V9-S1/metrics.json`、`run_ledger.json`、本报告；作业日志在 `AinerRelay/data/runs/jobs-v1/job-*`；部分检查点在 `artifacts/v9/s1/phase1/runs/<run_id>/checkpoints/`
失败与限制：9/9 训练未跑完 3510 步；arm2–4 eval 因 `eval_batches=48` vs window-probe 175 被入口拒绝；final 读取 0 次
交回统筹：见文末三问（截止偏紧、eval48 拒绝、lost-exec 挡后续）

## 摘要（≤30 行）

1. **verify** `job-d1ed6a05…` exit 0：批准行 776、源绑定、数据集、资源门全绿。
2. **训练 9/9 失败/中止**：8 次 `CompletionDeadlineExceeded`（~450.0s 墙钟撞冻结 deadline 450s），1 次 `BudgetExceeded: wall_time_budget`（arm4-seed0）。完成步数约 1591–2676 / 3510，多数写到 updates-1755.npz；**未重跑、未改参**。
3. **eval-arm1** `job-27d416cd…` exit 0：D 身份核验通过；S1 指标均为 `not_applicable`（不可比输入布局）；C0：symbol_nll_t0=0.099 / t1=2.452；observation_loss_t0=0.194 / t1=2.745。
4. **eval arm2/3/4×seed**：全部 exit 3 `refused`——`eval_batches=48` 无法覆盖冻结 window-probe 175 批。
5. **final**：全程 0 次读取（目录不存在；prereg `not_generated_not_read`）。
6. **口径**：held-out=时间续段；checkpoint0=未训练基线；M2 选点=字典序前 5；eval48=身份字段——均按放行核定标注，**无能力结论**。

## 训练表（命令模板见卡面 argv_template_train）

| label | job | rc | 墙钟(s) | 步数(reserved) | 原因 | 检查点 |
|---|---|---|---|---|---|---|
| arm2-seed0 | job-22457f6e… | 1 | 450.13 | 2309 | DeadlineExceeded | 0/439/878/1755 |
| arm2-seed1 | job-21f1d058… | 1 | 450.03 | 2322 | DeadlineExceeded | 0/439/878/1755 |
| arm2-seed2 | job-939e81d3… | 1 | 450.06 | 2230 | DeadlineExceeded | 0/439/878/1755 |
| arm3-seed0 | job-b38698da… | 1 | 450.18 | 2676 | DeadlineExceeded | 0/439/878/1755 |
| arm3-seed1 | job-0fc20b83… | 1 | 450.19 | 2075 | DeadlineExceeded | 0/439/878/1755 |
| arm3-seed2 | job-112fef7d… | 1 | 450.05 | 2564 | DeadlineExceeded | 0/439/878/1755 |
| arm4-seed0 | job-49cedeb8… | 1 | 449.99 | 2076 | BudgetExceeded wall | 0/439/878/1755 |
| arm4-seed1 | job-49111813… | 1 | 450.11 | 1889 | DeadlineExceeded | 0/439/878/1755 |
| arm4-seed2 | job-cdeb8776… | 1 | 450.10 | 1591 | DeadlineExceeded | 0/439/878（无 1755） |

## 评测表

| label | job | rc | 结果 |
|---|---|---|---|
| eval-arm1 | job-27d416cd… | 0 | D 复验完成；S1 指标 N/A；C0 见 metrics.json |
| eval-arm2/3/4 ×3 | 各 job-… | 3 | refused：eval_batches=48 不能覆盖 175 window-probe |

## arm1 与 D/M2 同表（不可比已标注）

| 项 | 值 |
|---|---|
| localization / unseen_map / topology / few_shot / sample_efficiency | not_applicable（incomparable input layout） |
| m2_memory_interference | not_applicable（无 S1 情景记忆）；附带 d_candidate_symbol_nll t0/t1 |
| d_candidate_c0_metrics | obs_loss 0.194→2.745；symbol_nll 0.099→2.452 |
| 身份 | tensors/manifest/metadata SHA 全 match；entries_verified=9 |

## 工程备注（不扩预算）

- 启动后发现 jobs-v1 把失败训练的 exec 标成 `lost`，挡住同任务下一 job；组空后对本 exec 调 finish→`finished` 才继续。详见 metrics `open_questions`。
- 后台 Python 驱动曾被会话回收；最终由仍存活的 `serial_run` 与本会话前台补齐。账本以 `run_ledger.json` + RunStore + jobs-v1 为准。

## 交回统筹

1. 450s deadline 相对实测训练吞吐过紧，9 次无一完成——是否重冻步数/deadline/占空比（需新批准行）。
2. eval 入口用 eval_batches=48 拒绝 175 批探针，与「eval48 只作身份字段」的放行文是否一致。
3. 建议修复 jobs：失败但组空时不要把 exec 留在 `lost` 阻塞串行。
