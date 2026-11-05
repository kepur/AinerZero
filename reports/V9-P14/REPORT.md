# ainerzero.V9.P14 独立复核报告（P13 / V9-P9 r4）

- 复核者：`deepseek-p14a`（二级执行）；**非** P9 任一 round 与 P13 的作者
- 被复核卡：`ainerzero.V9.P13`（r4，作者 `antigravity-v9k2`）
- 日期：2026-10-21；结论：**建议打回**

## 摘要（≤30 行）

1. **结论：建议打回。** 两类独立阻断：训练台账缺陷（真实路径无法产出检查点）与指标保真缺陷（多个预登记指标是写死夹具/错配）。
2. **阻断一（台账）**：按 r4 现有代码，任何登记的 r4 训练 run 都无法写出检查点（`evidence/train-ledger-probe.json`，`blocker_confirmed`）。
3. 场景 A：run 预算 `max_optimizer_steps` 默认 1，第 2 步即 `BudgetExceeded`，state `stopped`，无检查点。
4. 场景 B：预算抬到冻结 `updates` 后，最后一步更新耗尽额度，随后的零步检查点预留仍被 `RunStore._check` 拒绝。
5. 场景 C：预算取 `updates+1` 被 `LifecycleError: run budget exceeds experiment run limits` 拒绝——实验上限钉死为 `updates`，A/B/C 夹死所有取值。
6. **阻断二（指标 F1）**：`worker.py:809` 的 `few_shot_unseen_transition` 四个参数**全为字面量且预测==真值**，恒为 accuracy 1.0 / mae 0.0，与模型/检查点/episode 无关（`evidence/metric-fidelity-p14.json`）。
7. F1 负对照：同一函数喂入不一致预测即得 accuracy 0.5 / mae 1.0——缺陷在调用点写死，不是函数不会算。
8. **阻断三（指标 F3）**：localization 以 `min(估计数, 真值数)` 前缀配对、按索引对齐，跨 episode/world/tick 错配。
9. F3 负对照：对 episode B 的完美估计，因与 episode A 的真值按索引配对，得 translation 10.0 m；按 episode 对齐为 0.0 m。
10. **阻断四（指标 F2）**：M2 干扰的 before/after 是同模型对同一 dev 数据的两次前向（`worker.py:746/825`，其间无写入），必然为 0，不是预登记的干扰诊断。
11. F4（major）：重复运行守卫只查 `completed`，`failed`/`aborted`/`stopped` 的同 arm×seed 可重跑（违反冻结规则 6）。
12. F5（major）：eval 信任可自填的 `runs/<id>/run_info.json`（仅比 arm/seed），`_load_checkpoint_params` 加载不核 SHA（违反冻结规则 7）。
13. F6（major）：`unseen_map_generalization` 仅喂单行 + `truth_view[0]` 的 family 汇总整库（违反冻结规则 3）。
14. 冻结身份（`evidence/frozen-diff.json`）：verdict `zero_substantive_difference`；r4 doc `6cbe7ead…39842`、file `e9f0844a…e64d9`、r3 doc `ed39c97c…5c94`，与 P13 声明一致。
15. r3↔r4 叶差异 **8 处**，全在 `commands`/`created_unix`/`effective_metadata`/`source_identity`；所有不可变块逐字节相同。
16. 次要：P13 报告 `changed_groups` 记 `commands 2 / source_identity 4`，实为 `1 / 5`（总数 8 正确）。
17. 全流程假时钟（`evidence/full-flow.json`）：9 训练 + 4 eval 全完成；每次训练自持窗口 145.23 s < 450 s；监督 500 s/次；阶段跨度 4507.25 s。
18. 截止累计缺陷（#349）已修复：无训练调用继承前次时间；重复调用 exit 3 `already_completed` 且未触发 supervisor；阶段守卫 exit 3 `phase_budget_exceeded`。
19. 按 #356 追加边界用例（`evidence/deadline-boundary-p14.json`）：第 2 次训练自持 **449.0 s 完成**（累计 994.3 s > 450，共享计时必误超时）；第 3 次自持 450.07 s 被 `TimeoutError` 拒绝（证明截止仍生效）。
20. 检查点 0444 + 侧车校验和一致——但仅在复核者的 stub `_train` 路径可观察，真实路径被阻断一挡住。
21. eval 不更新参数（optimizer_steps 0）；4 次 eval 均输出全部 6 项指标；**不读 final**（tripwire 未触发，仅开 `development.jsonl`，诱饵未开，数据集内无 final 文件）。
22. 指标独立复算：定位误差、sample_efficiency、m2 以复核者自写算术重算，`abs_diff = 0.0`。
23. 变异矩阵 **18/18 全部捕获**（M1–M15 + 复核者自写 V1/V2/V3）；沙箱基线 `129 passed`。
24. 变异矩阵的局限：捕获的是「拒绝/守卫」类缺陷，**不能**证明真实训练路径跑得通——掩盖不了第 2–6、10 条。
25. P12 P1–P4 复跑 **15/15**；P11/F1 复跑 **9/9**；真实文件前后逐字节一致（含仍为空的 `m0-worker.lock`）。
26. 限制：全流程为单进程假时钟，生产是每调用一个 worker 进程；为评估时序/eval 对 `max_optimizer_steps` 打了 +1000 的显式豁免；未做真实 MLX 训练、未独立重实现模型前向。
27. 放行建议：修台账步数记账与检查点预留语义、修 F1/F2/F3 指标实现、把 F4 守卫扩展到 failed/aborted/stopped、给 F5 绑定已登记 SHA、修 F6 的逐世界汇总，并补一条**不替换 `_train`** 的真实路径测试后重交。

## 阻断项一：训练台账（可复现）

`evidence/train-ledger-probe.json`，三场景：

| 场景 | run 预算 `max_optimizer_steps` | 结果 | 检查点 |
|---|---|---|---|
| A 现状 | 1（默认） | 第 2 步 `BudgetExceeded: optimizer_step_budget`，state `stopped`，optimizer_steps 1 | 无 |
| B 等于 updates | 2420 | 耗尽 2420 步后，零步检查点预留仍被拒（`zero_step_reserves` 4 次全拒），state `stopped` | 无 |
| C = updates+1 | 2421 | `LifecycleError: run budget exceeds experiment run limits` | 无 |

成因：`worker.py:run_config_snapshot` → `_budget_block` 默认 `max_optimizer_steps=1`；`train_experiment_manifest` 把实验 optimizer 上限钉成 `updates`；`runtime/lifecycle.py:RunStore._check` 在任一 remaining ≤ 0 时拒绝预留，而检查点发生在最后一步更新之后。

## 阻断项二至四与主要问题：指标保真（可复现）

`evidence/metric-fidelity-p14.json`（复核者自写 AST + 纯 numpy 行为检查，未导入 MLX、未改被验源）：

| id | 级别 | 事实 | 证据 |
|---|---|---|---|
| F1 | blocker | `few_shot_transition_metrics` 调用点四参全字面量、预测==真值 → 恒完美 | worker.py:809；行为：1.0/0.0；对照 0.5/1.0 |
| F2 | blocker | M2 before/after 同模型两次 dev 前向，无中间写入 → 恒 0 | worker.py:746/825；行为：delta 0.0；对照 0.2 |
| F3 | blocker | localization `min()` 前缀按索引配对，跨 episode 错配 | worker.py:773-775；对照：10.0 m vs 0.0 m |
| F4 | major | 重复运行守卫只查 `completed` | worker.py:309-323 |
| F5 | major | eval 信任自填 `run_info.json`、加载不核 SHA | worker.py:645-687 |
| F6 | major | unseen_map 单行 + 第一世界 family 汇总 | worker.py:776-784 |

## 通过的项（供统筹参考）

- 冻结身份与叶差异：`evidence/frozen-diff.json`
- 全流程时序 / eval / final 封存：`evidence/full-flow.json`
- 截止边界用例（#356）：`evidence/deadline-boundary-p14.json`
- 变异矩阵：`evidence/mutations-p14.json`
- 指标保真探针（#372/#374）：`evidence/metric-fidelity-p14.json`
- P12 P1–P4 复跑：`evidence/p1-p4-counterexamples-rerun-p14.json`
- P11/F1 复跑：`evidence/f1-approval-r4-rerun-p14.json`
- 用例判定汇总：`evidence/case-verdicts-p14.json`
- 真实文件前后快照：`evidence/real-files-before.txt`、`evidence/real-files-after.txt`（diff 为空）

## 诚实限制与未验证项

1. 假时钟单进程 vs 生产多进程：模块级 `started` 在生产每进程重置，本复核以自写 V1 在进程内证明其可被捕获，并以边界用例在单进程内证明每次调用计时器独立；未在多进程路径复跑。
2. `ledger_waiver`：仅抬 `max_optimizer_steps` 额度（run 与 experiment-per-run 各 +1000），用于让时序/eval/边界检查得以执行；不构成对阻断项的放行。
3. 指标复算与 F1–F3 探针共用同一份观测/模型前向或直接调用冻结函数；未独立重实现模型前向。
4. 未做真实模型训练；`checkpoint_save_and_sha` 仅在 stub `_train` 路径被观察到，真实路径因阻断一不可达。
5. 未验证 final 分区封存通道的"唯一一次读取"实现（本次仅验证 P1 阶段不读 final）。
6. `test_full_sequence_9_trains_and_4_evals` 非自洽：arm1 eval 依赖 `reports/V9-baseline/r3/baseline_manifest.json` 与 `artifacts/pilot`，变异沙箱需复制二者才能达到 129/129。
7. 报告期有一次早期探针短暂进入真实 `_supervised_worker` 并被拒绝；锁文件仍为空，mtime/SHA 未变。
