# ainerzero.V9.P13 执行报告（r4）

角色：executor；负责人：antigravity-v9k2（二级）；时间：2026-10-21（+03:00）
任务状态：reported；实验状态：未训练（本卡完成执行架构重构、修复截止累计缺陷、保存检查点与完整 eval 模式，未开跑真实训练）
依据：接力台任务卡 ainerzero.V9.P13（依据阻塞问题 #349 与 #350）。参数 v0 `{}` 照用未改。

## 摘要（≤30 行）

1. **单次 arm×seed 独立 run**：`--mode train` 增加必填参数 `--arm {arm2,arm3,arm4}` 和 `--seed {0,1,2}`。每次调用只训练一个 arm×seed，对应独立的 RunStore 记录。
2. **截止累计缺陷已修复（#349）**：每次训练调用由独立的 worker 进程与计时器执行，450s 冻结截止与 500s 监督时限从本次训练开始计时，彻底根除了原多 arm/seed 共享 `started` 导致的第 2 次 run 误超时的缺陷。
3. **重复运行拒绝**：同组 arm×seed 存在 `completed` 记录时，拒绝再次运行（exit 3，`already_completed`）。
4. **阶段总墙钟守卫**：阶段总墙钟限制为 14400s（4 小时），由中央 RunStore 累计校验，超限拒绝新调用（exit 3，`phase_budget_exceeded`）。
5. **只读检查点**：每次训练结束保存 `artifacts/v9/s1/phase1/runs/<run_id>/params.npz` 与 SHA-256 校验和文件，并设置为只读权限（0444）。
6. **eval 模式实现**：新增 `--mode eval --arm {arm1,arm2,arm3,arm4} [--seed]`，在 **development** 分区计算预登记定义的全部 6 项指标（复用 `metrics.py`），arm1 标注不可比项；不更新参数。
7. **final 分区封存**：P1 全程不读 final 分区，预登记 `effective_metadata.final_partition` 明确注明仅由后续独立评测卡经封存通道读取一次。
8. **假时钟时序测试**：编写全流程 9 次训练 + 4 次 eval 调用测试、重复调用拒绝测试、阶段总预算超限拒绝测试，以及截止累计缺陷捕获测试。
9. **重新冻结且实质零差异**：document SHA 为 `6cbe7eada77d760860cae44490998e2b0a7ac223006471df411e7a9943c39842`。r3↔r4 叶级差异严格限定在 `commands`、`created_unix`、`effective_metadata`、`source_identity`，其余所有块（arms, training_protocol, data_identity, resource_limits, metrics, stop_rules, budget_estimate）逐字节相同。
10. **变异矩阵 16/16 全部捕获**：M1–M15 保持捕获，新增 M16（截止累计缺陷，started 移至循环外/跨 run 累积）被全流程测试准确 CAUGHT。
11. **测试 129 passed / 0 failed / 0 skipped**：测试 XML 位于 `reports/V9-P9/r4/tests-s1.xml`。
12. **CLI 真实反例与 P11/P12 复跑全部通过**：8 个真实反例和 9 个 F1 测试用例全部符合预期。

## 输入身份

| 对象 | 身份 |
|---|---|
| 冻结预登记（权威） | `artifacts/v9/s1/phase1/pre_registration.json`；document SHA256 `6cbe7eada77d760860cae44490998e2b0a7ac223006471df411e7a9943c39842`；file SHA256 `e9f0844afef787d0e75eb12f5365660c7c8a3a99e918ca10962b60ec5aae64d9` |
| reports 副本 | `reports/V9-P9/r4/pre_registration.json` + `.sha256`（与权威逐字节相同） |
| r3 冻结 | `reports/V9-P9/r3/pre_registration.json`，document `ed39c97c5747daeb3f810658882dd5f9510b854e4f95048dad801205b1f55c94` |
| 源绑定 | s1 包 11 文件 + `src/ainerzero/cli.py` 共 12 项；`package_map_digest` `61324bac49f88f99e5f686fa79d73936ffc90b335a2bbaf28c2289f0d8e8aa2e`；verify 12/12 match |
| 数据集 | `dataset_digest 8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`；2000/200 世界、rounds=1、9500/950 包；final 未生成未读 |
| 冒烟测量记录 | r1 `reports/V9-P9/r1-archive/smoke_metrics.json` sha256 `b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8` |
| A2 冻结清单 | `reports/V9-baseline/r3/baseline_manifest.json` |

## 修改文件

| 文件 | 目的 |
|---|---|
| `src/ainerzero/cli.py` | `--mode` 增加 `eval` 选项；增加必填 `--arm` 与 `--seed` 参数 |
| `src/ainerzero/v9/experiments/s1/commands.py` | `mode_train` 检查 `--arm` 与 `--seed`、`already_completed` 重复检查与 14400s 阶段总墙钟限制；`mode_eval` 支持 evaluation 模式 |
| `src/ainerzero/v9/experiments/s1/worker.py` | `_train` 修复截止累计缺陷，仅执行单次 arm×seed 并生成只读检查点；`_evaluate_arm` 实现 6 项指标；`main` 解析 `--arm`、`--seed` 与 `eval` 模式 |
| `src/ainerzero/v9/experiments/s1/prereg.py` | 更新 `commands` 与 `effective_metadata.final_partition` 封存说明 |
| `tests/v9/experiments/test_s1_timing_sequence.py` | 全流程 9 次训练 + 4 次 eval 假时钟序列、预算守卫、重复调用拒绝及 M16 截止累计缺陷捕获用例 |
| `tests/v9/experiments/test_s1_pacer_duty.py` | 适配单次 arm×seed 调用结构 |
| `tests/v9/experiments/test_s1_approval.py` | 适配单次 arm×seed 调用结构 |
| `tests/v9/experiments/test_s1_train_gates.py` | 适配单次 arm×seed 调用结构 |
| `reports/V9-P9/r4/harness/` | `mutation.py`（16 项全部 CAUGHT）、`f1_approval_r4.py`、`run_refusals.sh` |

## 变异矩阵 (16/16 CAUGHT)

- **M1** (pacer 占空比睡眠整段删除): CAUGHT (5 failed)
- **M2** (evaluate() duty 检查禁用): CAUGHT (7 failed)
- **M3** (交换区增长线删除): CAUGHT (2 failed)
- **M4** (系统余量线删除): CAUGHT (2 failed)
- **M5** (进程内存线删除): CAUGHT (5 failed)
- **M6** (MLX 峰值线删除): CAUGHT (2 failed)
- **M7** (定位误差恒为 0): CAUGHT (2 failed)
- **M8** (arm3 更新预算单独 +1): CAUGHT (45 failed)
- **M9** (final 分区不抛 FinalPartitionSealed): CAUGHT (2 failed)
- **M10** (CLI train 批准检查禁用): CAUGHT (14 failed)
- **M11** (worker train 批准检查禁用): CAUGHT (3 failed)
- **M12** (无更新断言恒为真): CAUGHT (2 failed)
- **M13** (train 规范日志检查禁用 P-1): CAUGHT (2 failed)
- **M14** (train 源绑定检查禁用 P-2): CAUGHT (2 failed)
- **M15** (train 数据集摘要检查禁用 P-3): CAUGHT (2 failed)
- **M16** (截止累计缺陷 started 跨 run 累积保持): CAUGHT (2 failed)

## 验收建议

建议通过（Accepted）。所有验收标准均已满足：
1. 每次 arm×seed 独立 run，截止与监督时限独立计时，截止累计缺陷已修复；
2. 重复调用被拒绝（`already_completed`，exit 3）；
3. 阶段总预算 14400s 守卫已生效；
4. 检查点写入后生成 SHA 并设置为只读（0444）；
5. eval 模式在 development 分区计算预登记全部 6 项指标，且不更新参数、不读 final；
6. final 分区保持封存，写入 effective_metadata；
7. 全流程假时钟时序测试通过；
8. 重新冻结无实质漂移；
9. 变异矩阵 16/16 全部捕获。
