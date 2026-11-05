# V9.P15 / S1 r5 候选修复报告（纯 CPU 工程，不授权真实训练）

- 任务：`ainerzero.V9.P15`（S1 r5，承接 P13 r4 的负面复核与 P15 修复裁决）
- 执行者：`ds-s1r5-1021n`（deepseek，tier 2）；本报告作者即执行者，不能自验收
- 报告写入：`reports/V9-P9/r5/`；新预登记根：`artifacts/v9/s1/phase1/r5/`
- r4 原证据：未覆盖，已封存于 `reports/V9-P9/r5/archive-r4/`（12/12 bound source 摘要吻合）
- 执行边界：纯 CPU；无 MLX 实际推理/梯度/训练，无 GPU、无渲染、无下载/安装、无付费服务、无 git commit/push、无删除、无生产 Relay 改动、无批准行写入
- 结论性质：工程修复候选；**不是**能力结果，不晋升任何模型，也不代表科学指标已成立

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# (0) 领取/心跳（摘要，见交接记录）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay heartbeat ainerzero.V9.P15 --agent ds-s1r5-1021n --msg "..."

# (1) r4 封存（已完成，12/12 摘要吻合）
#     产物：reports/V9-P9/r5/archive-r4/{ARCHIVE_MANIFEST.json,SHA256SUMS.txt,bound-source-r4/,r4-reports/}

# (2) r5 草稿：只改 source_identity + created_unix（不重跑 preregister，避免 MLX 建模型数参数）
.venv/bin/python reports/V9-P9/r5/harness/refreeze_draft.py \
  > reports/V9-P9/r5/logs/refreeze_draft.json

# (3) 重冻 + 复验（测量记录仍是 r1 归档那份，预算/种子/步数不变）
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r5 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json \
  > reports/V9-P9/r5/logs/freeze.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify \
  --output-root artifacts/v9/s1/phase1/r5 \
  > reports/V9-P9/r5/logs/verify.json

# (4) r4→r5 逐叶差异
.venv/bin/python reports/V9-P9/r5/harness/prereg_leaf_diff.py \
  > reports/V9-P9/r5/logs/prereg_leaf_diff.txt

# (5) 生产 _train + 真实 RunStore + 真实 3510 记账 + 真实 development 数据 + 生产 _evaluate_arm
#     （数值后端替身，非 MLX；不 stub _train，不豁免 ledger）
.venv/bin/python reports/V9-P9/r5/harness/ledger_and_eval_evidence.py \
  > reports/V9-P9/r5/logs/ledger_and_eval.out

# (6) CPU 工程测试（全套 experiments）
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r5/logs/tests-s1-r5.xml \
  > reports/V9-P9/r5/logs/tests-s1-r5.txt

# (7) 进程隔离复核（几何 CPU-only 用例单独跑）
.venv/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider
.venv/bin/python -m pytest tests/v9/contracts tests/v9/teachers tests/v9/tokenization -q -p no:cacheprovider
```

未执行：任何 `--mode train` 真实训练、`--mode eval` 真实评测、MLX 前向/梯度/优化器步骤、数据生成/重建、模型下载/安装。

## 2. 输入与身份

| 项 | 值 |
| --- | --- |
| r4 冻结文档 SHA256 | `6cbe7eada77d760860cae44490998e2b0a7ac223006471df411e7a9943c39842` |
| r5 冻结文档 SHA256（canonical） | `c2f56b5ac79706417bcf0a810fcabd984c57b21c06143df45e00cf2917a7c98d` |
| r5 文件 SHA256（落盘字节） | `895bb3676cd3db6ad7995814ee940e23b1bff55747e8dea665f5fe426386075b` |
| 数据集 digest | `8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`（2000 train/200 dev worlds，未变） |
| 测量记录 | `reports/V9-P9/r1-archive/smoke_metrics.json`，SHA256 `b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8`（未变） |
| 冻结步数 | `updates = 3510`；检查点 `[0, 439, 878, 1755, 3510]`；每 run 450 s 截止/500 s 监督（未变） |
| 种子/分区/科学门 | arm2/3/4 × seed 0/1/2；参数、dims、metrics、stop rules、final 分区规则均未改 |

`verify`：`source_binding=passed`（14 个绑定文件全部吻合，drifted 为空）、`dataset.files=5`、`frozen_smoke_source.match=true`、`approval.approved=false`（本卡无批准行，也未写）。

## 3. run budget / 检查点可达性修复

r4 根因（与 P14 一致）：训练 run 的预算快照沿用辅助 run 的默认 `max_optimizer_steps=1`；RunStore 在任一计数器归零后拒绝**任何** consume（包括 `optimizer_steps=0` 的墙钟预留），因此第 3510 步之后无法再做检查点探针/保存。

r5 修复（只动 S1 adapter，不动 `runtime/lifecycle.py`）：

1. `worker._open_train_run` 显式把 `max_optimizer_steps` 设为冻结 `updates`（另带 `updates`、`preregistration_sha256`、`dataset_digest`、`checkpoint_updates` 快照字段）。
2. 每一步恰好一次 optimizer 预留；命中冻结检查点的那一步，其预留额外带上探针/保存墙钟；最后一步（`update == updates`）的预留内包含最终检查点墙钟。**不存在**第 3511 次预留、也不把 optimizer 预算改成 3511。
3. 最终检查点只写一次（`exclusive=True`），随后写 `completion.json`（权威 receipt）与 `run_info.json`（`authoritative: false`，仅供便利）。
4. 账本 reason 保存 `s1_train_completed:<receipt-json>`，eval 必须回查该 completed run 并核对 receipt/检查点原 SHA。

生产 `_train` 实测（真实 RunStore、真实 development 数据、数值后端替身，`reports/V9-P9/r5/evidence/ledger-and-eval.json`）：

| 项 | 实测 |
| --- | --- |
| optimizer 预留 | 3510（另有 1 次 checkpoint-0 墙钟预留，总预留 3511 条记录） |
| 最后一次预留 | `optimizer_steps=1`, `active_seconds=2.05`（含检查点墙钟） |
| 检查点 | `[0,439,878,1755,3510]` 各 1 次，共 5 次写盘 |
| 最终检查点写次数 | 1；写盘 SHA == receipt SHA == 绑定 SHA |
| 最终步之后的 optimizer 预留 | 0 |
| run 终态/剩余预算 | `completed`；`reserved_optimizer_steps=3510`；`remaining.optimizer_steps=0` |
| 3511 越界 | `BudgetStop: optimizer_step_budget`；run 停在 `training`、只消耗 3510；直接 `consume` 也抛 `BudgetExceeded` |
| 重跑拒绝 | 任何非 `created` 的已有 attempt 都计入 `train_attempts`，completed 后仍返回该 run，重跑入口拒绝 |
| 坏控 | 旧默认预算 1 的 run 在第 2 次 optimizer 预留下即被账本拒绝（新增测试） |

## 4. 指标实现（r5）

按 `P13-METRIC-DECISION.md` 与冻结 metrics 定义实现，真值只进独立评分旁路：

- `localization_error`：每 episode 按同一 anchor（真值首帧）做相对对齐；逐 episode/tick 行，拒绝重复 tick；loop closure 只在有非相邻 revisit 时报告，否则 `no_samples`（不以 0 冒充）。
- `unseen_map_generalization`：逐 episode/world/family 汇总，要求 `episode_id/scene_id/family/ticks` 与非空 NLL；NLL 为 `presence+class`，缺失即失败，不补 0。
- `topology_recovery`：逐 episode 的 precision/recall/F1，按 family 分开；节点匹配到真实 visited cell（0.75 m 容差），未匹配边计入假阳性。
- `few_shot_unseen_transition`：k={0,1,2,4,8}，support 为该世界前 k 个 transition，query 为紧随其后的 held-out transition；support 只写记忆、不更新参数；k 不足或该世界无 query 时明确 `insufficient_data`，绝不返回完美值。query 目标 tick 取 truth step 的 `tick`。
- `sample_efficiency`：每个冻结检查点重新 load、重新在 development 上算 loc + NLL，得到双曲线。
- `m2_memory_interference`：同一固定 development 探针的 zero-state / history-paired / 写入新世界后三条件；探针前后参数 SHA 必须一致，否则拒绝。

真实 development 数据上的编排证据（**数值后端替身**，仅证明管道与身份对齐，不作能力声明）：

| 组 | 覆盖 |
| --- | --- |
| localization / unseen | 200 episodes、200 worlds、4 families |
| topology | 200 episodes、200 worlds、4 families |
| few-shot | k=0: 750 queries/200 worlds；k=1: 550/200；k=2: 350/150；k=4: 100/50；k=8: **unavailable（0 worlds）** |
| sample efficiency | 5 个检查点（0/439/878/1755/3510），loc+NLL 各 5 点 |
| M2 | zero/history/after-new-world 三条件；探针前后参数 SHA 相同 |

**必须上报的样本缺口**：真实 development 世界平均只有约 4.75 个 packet、约 3.5 个 transition，因此冻结协议里的 k=8 在 200 个世界中**没有一个**能提供 8 个 support + 1 个 query；k=4 也只有 50/200 个世界可用。代码按规则报 `insufficient_data`，未伪造、未改 k 集合、未换数据。这是冻结指标与数据粒度之间的真实冲突，需一级/P16 决定：接受“k=8 全局不可用”的披露，或另开卡调整数据/指标登记；本卡不擅自改。

## 5. 评测模型调用清单 vs 旧登记预算

静态/实测调用清单（真实 development split，5 个检查点）：

| 调用 | 次数 | 说明 |
| --- | --- | --- |
| `window_probe` | 5 次 / 175 batch | 每次覆盖全部 550 windows（ceil(550/16)=35 batch），最终检查点复用一次结果 |
| `step_sequence` | 611 次 / 1703 帧 | topology 200 + few-shot support + M2 11 次 |
| `probe_graph` | 800 次 | topology 200 + few-shot 每 k 每世界 1 次 |
| `encode` | 3500 次 | few-shot 每条 query transition 2 次 |
| checkpoint `load_params` | 7 次 | 绑定 + 双曲线重载 + 最终复位 |

对照旧登记：冻结文档只有 `training_protocol.eval_batches = 48` 与旧 `estimated_eval_cost_seconds ≈ 1.67 s`，它**覆盖不了** r5 评测套件（175 个 window batch 之外还有 ~611 次序列前向/1703 帧与 3500 次 encode）。本卡未改这个字段、未静默扩预算、未做真实 eval；在此明确报告缺口，等待一级决定新的评测登记/预算后再跑真实评测。训练期检查点探针（5×35 batch）与评测期探针是两笔不同开销，报告不把它们混为一谈。

## 6. 测试与反例（CPU）

- 全套：`.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider` → **146 passed in 4.12 s**（junit：`logs/tests-s1-r5.xml`）。
- 隔离复核：`tests/v9/geometry` **149 passed**；`tests/v9/contracts tests/v9/teachers tests/v9/tokenization` **229 passed**。
- 已知进程级现象：把整个 `tests/v9` 放进同一 pytest 进程时，`geometry` 的两个“未导入 MLX”用例会失败，因为旧的 `tests/v9/experiments/test_s1_pacer_duty.py` 在模块级 `from ... import arms`，而 `arms.py` 模块级导入 MLX（r5 之前既有）。单独运行 geometry 通过。按“不改无关文件/不改旧测试身份”的边界，本卡未改它，只如实记录。r5 新增的 `test_arm_eval_import_graph_does_not_import_mlx` 用独立子进程证明 arm2/3/4 评测导入图不导入 MLX。

关键反例/坏控（全部通过，节点见 `evidence/test-map.json`）：

| 要求 | 用例 |
| --- | --- |
| 生产 `_train` + 真实账本跑满 3510、只写一次最终检查点 | `test_production_train_3510_has_exactly_one_final_checkpoint` |
| 3511 越界拒绝 | `test_3511th_optimizer_reservation_is_refused_at_the_3510_budget` |
| 旧默认预算 1 的坏控 | `test_run_snapshot_carries_the_frozen_updates_and_a_one_step_budget_still_fails` |
| 实际启动后禁止重跑（completed/failed 均算） | `test_rerun_is_refused_after_any_started_attempt` |
| eval 绑定拒绝：篡改/缺失/错误 prereg/重复 completed | `test_eval_binding_rejects_tampered_missing_and_duplicate_evidence` |
| 六组指标从合法 run 产出 | `test_evaluate_arm_binds_run_and_computes_all_six_groups` |
| 指标随预测变化、family/拓扑分离 | `test_topology_edges_follow_the_prediction`、`test_topology_is_per_family_not_first_episode` |
| 标识缺失/重复/空样本失败 | `test_strict_unseen_map_requires_identity_and_a_real_nll`、`test_development_rows_rejects_duplicate_ticks_and_unknown_episode`、`test_few_shot_k_is_traversed_and_missing_support_fails_closed` |
| 真实重复格（连续停留）不再 IndexError/错位 | `test_few_shot_uses_the_per_step_cell_path_when_the_agent_stays_put`、`test_development_rows_maps_loop_pairs_from_per_step_cells` |
| M2 记忆变化可见、参数变化被拒 | `test_m2_interference_changes_with_memory_and_rejects_parameter_updates` |
| CPU-only 导入图 | `test_arm_eval_import_graph_does_not_import_mlx` |

证据 harness 另附三组绑定坏控（真实文件系统）：篡改最终检查点 → `EvalBindingError`（现算 SHA ≠ 原 receipt SHA）；删除 `updates-0.npz` → `EvalBindingError: missing`；错误 prereg SHA → 无匹配 completed run。

## 7. 重新冻结的逐叶差异

`reports/V9-P9/r5/prereg-leaf-diff.json`：398 个叶，16 处变化，**allowlist 之外 0 处**。

- `created_unix`：新时间。
- `source_identity.package_files`：`arms.py`、`commands.py`、`data.py`、`metrics.py`、`worker.py` 更新；新增 `evaluation.py`、`runtime.py`（r5 新文件，必须绑定）。
- `source_identity.package_map_digest`：随上变化。
- `timing.smoke_recheck.*` 全部移除：r5 运行根没有本地重测 smoke，按实现不再生成这份交叉核对叶子；它是记账/诊断字段，不参与冻结预算推导。测量记录 `timing.smoke_source` 与 `timing.smoke.*` 完全未变。

未变：`training_protocol.updates=3510`、`checkpoint_updates`、`timing.deadline_seconds=450`、`timing.supervision_seconds=500`、参数数量、dims、seeds、metrics 定义、stop rules、data_identity。

## 8. 源码差异（相对 r4 归档）

`reports/V9-P9/r5/evidence/source-deltas.json`：绑定 14 个文件，未变 7、修改 5、新增 2。

- 修改：`worker.py`（预算/检查点/receipt/绑定/eval 编排）、`commands.py`（重跑守卫、阶段墙钟含 aux eval）、`data.py`（episode sequence）、`metrics.py`（r5 严格聚合）、`arms.py`（跨调用 memory/pose 接口）。
- 新增：`evaluation.py`（身份对齐指标编排）、`runtime.py`（backend seam、排他保存、全覆盖探针）。
- 未变：`cli.py`、`__init__.py`、`awz_export.py`、`prereg.py`、`resource_gate.py`、`smoke.py`、`spec.py`。

## 9. 失败、修复与未验证项

本卡过程中真实发现并修复的缺陷：

1. 真实 development 数据上 few-shot 用去重后的 `relative_cells` 按步号索引，连续停留时 `IndexError`（合成测试数据未暴露）。改为逐 step 的 `relative_cell_path`，并新增回归用例。
2. few-shot 的 query 目标 tick 用 `index+1` 而非 truth step 的 `tick`，在 tick 步长非 1 时错位。改为读 truth tick，测试覆盖。
3. 真实数据上 M2/拓扑/曲线编排首次跑通后，确认 6 组都产出；此前只有合成数据证据。

未验证 / 限制（不得当作通过）：

- 没有真实 MLX 前向、梯度、优化器或真实训练/评测；所有数值均为替身，**不能**用于任何能力或科学结论。
- k=8 在真实 development split 全局不可用，k=4 仅 50/200 世界；见 §4，需一级决定。
- 评测调用量显著高于旧登记 `eval_batches=48`；真实评测预算尚未重新登记（§5）。
- `arms.py` 模块级导入 MLX 是 r5 之前既有结构；本卡的 CPU-only 证明只覆盖 arm2/3/4 评测导入图与所有新测试路径。
- r4/P14 指出的其他系统性问题未在本卡范围内全部重验；本卡只修 P15 列出的预算/检查点/指标/重跑/绑定范围。
- 未写批准行；9 次真实训练仍应被 `train` gate 拒绝（`approval.approved=false`）。
- 作者不能验收自己的工作；需 P16 非作者独立复核，之后一级才可能批准 P1。

## 10. 产物清单

```text
artifacts/v9/s1/phase1/r5/
  dataset_ref.json                 # 指向未变的数据集 digest
  draft_preregistration.json       # r4 草稿 + 新 source_identity/created_unix
  pre_registration.json            # 冻结文档 c2f56b5a…
  pre_registration.json.sha256

reports/V9-P9/r5/
  REPORT.md
  prereg-leaf-diff.json
  archive-r4/                      # r4 原证据封存（未覆盖）
  evidence/ledger-and-eval.json    # 生产 _train/_evaluate_arm 实测证据
  evidence/source-deltas.json      # r4→r5 绑定源码差异
  evidence/test-map.json           # 146 用例汇总与要求映射
  harness/refreeze_draft.py
  harness/prereg_leaf_diff.py
  harness/ledger_and_eval_evidence.py
  logs/freeze.json
  logs/verify.json
  logs/refreeze_draft.json
  logs/prereg_leaf_diff.txt
  logs/ledger_and_eval.out
  logs/tests-s1-r5.txt
  logs/tests-s1-r5.xml
  SHA256SUMS.txt
```

## 11. 给一级 / P16 的决策点

1. 接受 r5 的预算/检查点/重跑/绑定修复与 §6 的测试证据，进入 P16 非作者独立复核。
2. 对 k=8 全局 `insufficient_data`、k=4 仅 50/200 世界给出处置（披露接受 / 另卡调数据或改指标登记）。
3. 对 r5 评测调用量超出旧 `eval_batches=48` 给出新的评测预算/登记，之后才可真实 eval。
4. 只有上述完成且一级写入批准行后，真实 9 次 arm×seed 训练才可能启动；本卡未启动、未消耗任何真实训练预算。
