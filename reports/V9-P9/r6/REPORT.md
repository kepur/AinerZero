# V9.P15 / S1 r6 候选修复报告（纯 CPU 工程，不授权真实训练）

- 任务：`ainerzero.V9.P15`（S1 r6，执行 `S1-R6-DECISION.md` 2026-10-22 版的六项修复裁决）
- 执行者：`step5-k7m2`（tier 2）；本报告作者即执行者，不能自验收
- 报告写入：`reports/V9-P9/r6/`；新预登记根：`artifacts/v9/s1/phase1/r6/`
- r5 原证据：未覆盖、未改动（`reports/V9-P9/r5/` 只读引用）；真实中央台账 `artifacts/v9/s1/phase1/control.sqlite3` 与真实 `RESEARCH_LOG.md` 均未写入（SHA256 前后一致，见证据 JSON）
- 执行边界：纯 CPU；无 MLX 实际推理/梯度/训练，无 GPU、无渲染、无下载/安装、无付费服务、无 git commit/push、无删除、无生产 Relay 改动、**无批准行写入**
- 结论性质：工程修复候选；**不是**能力结果，不晋升任何模型，也不代表科学指标已成立

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# (0) 领取/心跳（摘要，见交接记录）

# (1) r6 草稿：只改 source_identity + created_unix（不重跑 preregister，避免 MLX 建模型数参数）
.venv/bin/python reports/V9-P9/r6/harness/refreeze_draft.py \
  > reports/V9-P9/r6/logs/refreeze_draft.json

# (2) 重冻 + 复验（测量记录仍是 r1 归档那份，预算/种子/步数不变）
.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze \
  --output-root artifacts/v9/s1/phase1/r6 \
  --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json \
  > reports/V9-P9/r6/logs/freeze.json
.venv/bin/python -m ainerzero.cli s1-phase1 --mode verify \
  --output-root artifacts/v9/s1/phase1/r6 \
  > reports/V9-P9/r6/logs/verify.json

# (3) r5→r6 逐叶差异（只允许 source_identity/created_unix）
.venv/bin/python reports/V9-P9/r6/harness/prereg_leaf_diff.py \
  > reports/V9-P9/r6/logs/prereg_leaf_diff.txt

# (4) 生产 _train + 真实 RunStore + 真实 3510 记账 + 真实 development 数据 + 生产 _evaluate_arm
#     （数值后端替身，非 MLX；不 stub _train，不豁免 ledger；含 r6 末步墙钟负面控制）
.venv/bin/python reports/V9-P9/r6/harness/ledger_and_eval_evidence.py \
  > reports/V9-P9/r6/logs/ledger_and_eval.out

# (5) CPU 隔离副本权威批准模拟（不写真实 RESEARCH_LOG、不 mock 预算/尝试查询）
.venv/bin/python reports/V9-P9/r6/harness/isolated_approval_sim.py \
  > reports/V9-P9/r6/logs/isolated_approval_sim.txt

# (6) CPU 工程测试（全套 experiments + 隔离复跑）
.venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider \
  --junitxml=reports/V9-P9/r6/logs/tests-s1-r6.xml \
  > reports/V9-P9/r6/logs/tests-s1-r6.txt
.venv/bin/python -m pytest tests/v9/geometry -q -p no:cacheprovider
.venv/bin/python -m pytest tests/v9/contracts tests/v9/teachers tests/v9/tokenization -q -p no:cacheprovider
```

未执行：任何 `--mode train` 真实训练、`--mode eval` 真实评测、MLX 前向/梯度/优化器步骤、数据生成/重建、模型下载/安装、批准行写入。

## 2. 输入与身份

| 项 | 值 |
| --- | --- |
| r5 冻结文档 SHA256 | `c2f56b5ac79706417bcf0a810fcabd984c57b21c06143df45e00cf2917a7c98d` |
| r6 冻结文档 SHA256（canonical） | `deaa7bc92cac0c7b8d7b33d9580c64c33f75aff9d22af32207d56c78538d2794` |
| r6 文件 SHA256（落盘字节） | `58b1276730e87a4409c079594e0eadfd19899abd1ee3a4fe9d843d39b21ca318` |
| 数据集 digest | `8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`（2000 train/200 dev worlds，未变） |
| 测量记录 | `reports/V9-P9/r1-archive/smoke_metrics.json`，SHA256 `b4e7d1218b29652c188425ec6d1def2fe49d8fd1a22e7192d01b705ae4b11ce8`（未变） |
| 冻结步数 | `updates = 3510`；检查点 `[0, 439, 878, 1755, 3510]`；每 run 450 s 截止/500 s 监督（未变） |
| 种子/分区/科学门 | arm2/3/4 × seed 0/1/2；参数、dims、metrics、stop rules、final 分区规则均未改 |

`verify`：`source_binding=passed`（14 个绑定文件全部吻合，drifted 为空）、`dataset.files=5`、`frozen_smoke_source.match=true`、`approval.approved=false`（本卡无批准行，也未写）。

**逐叶差异**（`reports/V9-P9/r6/prereg-leaf-diff.json`）：391 叶中仅 7 叶变化，全部在允许清单内（`created_unix` + 5 个绑定源文件哈希 + `package_map_digest`），`outside allowlist: []`。变化的绑定文件：`cli.py`、`commands.py`、`evaluation.py`、`runtime.py`、`worker.py`。

## 3. 修复一：中央 RunStore 台账锚定（P15 第 1 项）

r5 及以前：`train`/`eval` 的尝试守卫与阶段总额只在"当前 output root 恰好有 control.sqlite3 时"才读，缺账本时**跳过**守卫——换个 output root、改 cwd、换个 checkout、复制一份 prereg 就能重置 `arm × seed` 尝试守卫与阶段墙钟总额。

r6（只动 S1 adapter，不动 `runtime/lifecycle.py` 与锁）：

1. `worker.canonical_ledger_path()` = `spec.PHASE1_ROOT / "control.sqlite3"`：唯一中央台账锚点（notice #297 布局，即仓库里现有那一份）。
2. `worker.canonical_ledger_state()`：只读身份校验（`sqlite3` `mode=ro`），要求 5 张 RunStore 表**且**存在 `s1-phase1-prereg-prep-20261021` 实验；状态 `missing` / `unreadable` / `unrecognized` / `ok`。
3. `run_worker`：`BOUNDED_MODES = ("train", "eval")` 先校验中央台账状态，非 `ok` 即 `central_ledger_{status}` 拒绝；再校验 `output_root.resolve() == spec.PHASE1_ROOT.resolve()`，否则 `output_root_not_canonical`。**绝不创建新账本**。
4. `commands` 入口双侧校验：`mode_train` 在建目录/读批准门之前先查规范根（`_canonical_run_root`），批准门之后、启动 worker 之前查中央台账（`_central_ledger_refusal`）；`mode_eval` 同样两道。worker 端再各查一遍（defence in depth）。
5. `attempt`/`phase_budget` 守卫改读中央台账，去掉旧的 `if control_db.is_file():` 跳过分支——缺账本从"跳过守卫"变成"拒绝"。
6. prep 模式（data/smoke/verify）保持每根诊断账本不变；eval 辅助 run 改注册到 train/eval 实验（r1 prep 实验的 3600 s 墙窗已过期，复用它会让每次 eval 都被过期实验预算拒绝）。

测试：`tests/v9/experiments/test_s1_r6_ledger_anchor.py`（13 例，台账四态 + `run_worker` 各类拒绝 + "拒绝后不新建账本" + 正常路径到达批准门 + run 落在中央台账）、`test_s1_r6_entry_guards.py`（13 例，入口侧规范根/中央台账/`already_attempted`/`phase_budget_exceeded`/eval 镜像，全部带 tripwire 证明 worker 未启动）。

## 4. 修复二：450 s 末步墙钟（P15 第 2 项）

r5 只在循环顶部检查截止时间；最后一步梯度、最终检查点探针/保存、duty 休眠、receipt/元数据 IO 都发生在最后一次循环顶部检查**之后**，可以越过 450 s 仍报告 `completed`。

r6 `_train` 三处 `_enforce_deadline()`（`time.perf_counter() - started > deadline` 才抛 `TimeoutError`，恰好等于 450.0 s 不算越界）：

1. 循环顶部（原语义保留）；
2. **循环结束后、任何 receipt/权威完成写入之前**；
3. `run_info.json` 写完之后、返回之前（trailing metadata IO）。

`run_worker` 的既有 `except BaseException` 把超时转成 `status=failed` 报告并把 run 终态为 `failed`——超时、保存失败、guard 拒绝都不可能产生合法 `completed`。

测试 `tests/v9/experiments/test_s1_r6_deadline.py`（9 例，真实 3510 步 + 假时钟，无 3511 步）：最后梯度越过 / duty 休眠越过 / 检查点 IO 越过 / 元数据 IO 越过（receipt 已落盘仍中止）/ 恰好 450.0 s 正常完成（`wall_seconds == 450.0`）/ 449.9 s 正常完成 / 最终保存失败不完成 / 末步 guard 拒绝不完成 / `run_worker` 超时后中央台账无 completed、无 train receipt。生产级复现见 `reports/V9-P9/r6/evidence/ledger-and-eval.json` 的 `r6_deadline_controls`（五种控制各跑真实 3510 步）。

## 5. 修复三：`probe_graph` 解包缺陷（P15 第 3 项）

缺陷（P16 证据 `S1-metric-map-direct-probe.json`）：`runtime.MlxBackend.probe_graph` 在度量图非空时把 flat index 当 `(row, col)` 解包，抛 `TypeError: cannot unpack non-iterable numpy.int64`。

修复（只改真实后端方法，不替换被审计算法）：cell 身份是 `(row, col)` 对，flat index 经 `remap` 映射回该对：

```python
occupied_cells = {(int(r), int(c)) for r, c in zip(rows, cols)}
remap = {(int(r), int(c)): position for position, (r, c) in enumerate(zip(rows, cols))}
```

测试 `tests/v9/experiments/test_s1_r6_probe_graph.py`（17 例）：空图、单格、水平/垂直相邻、对角/远距非相邻、被审计的 2×2 块（`edges == {(0,1),(0,2),(1,3),(2,3)}`）、节点取值顺序、姿态旋转（90° yaw）、零姿态、拓扑臂互邻、单向边拒绝、拓扑/度量契约一致、graph wrapper dict，以及子进程断言不导入 MLX。

## 6. 修复四（同一裁决附带）：few-shot support 边界 + eval 入口 fail-closed

- `evaluation.few_shot` 的 support `stop` 边界差一：`step_sequence` 的 `stop` 是排他帧界，覆盖 support 转移 `support[-1]` 需要 `support[-1] + 2`；r5 用 `+1`，k=1 只要到一帧、k=2/k=4 少写一条 support 转移。修复后 `step_frames` 1703 → 2103（+400，正好是每个被覆盖世界少掉的那一帧）。
- eval 入口补 fail-closed 门（协调信息 386）：源码绑定漂移拒绝、arm1（冻结 D 候选，无已训练检查点可绑定）拒绝、注册 `eval_batches=48` 连窗口探针批量都覆盖不了时在启动任何 suite 之前拒绝。**没有**静默扩大调用预算。

## 7. CPU 隔离副本：权威批准生效模拟

`reports/V9-P9/r6/harness/isolated_approval_sim.py` 造一个一次性仓库副本（`src/ainerzero` + r6 预登记 + 数据集字节 + 中央 RunStore + 带**模拟**批准行的 `RESEARCH_LOG.md`），以子进程驱动生产 `worker.run_worker("train")`；数值后端替身，无 MLX 前向/梯度。12/12 检查通过（`reports/V9-P9/r6/evidence/isolated-approval-sim.json`）：

| 场景 | 结果 |
| --- | --- |
| 批准生效 + arm2/seed0 训练 | `completed`，3510 梯度、5 次保存、中央台账 run=`completed`、`s1_train_completed:` receipt、`reserved_optimizer_steps=3510` |
| 第二个 arm×seed | `completed`（守卫按 arm×seed，不是全局锁） |
| 跨根（复制整个 run root） | `output_root_not_canonical`，副本账本未被写入 |
| 改 cwd 重跑同一 arm×seed | `already_attempted`（attempt_states=[completed]） |
| 同 SHA prereg 副本 + 新根 | `output_root_not_canonical`，**没有**新建账本、没有起 run |
| 后端失败后重跑 | 首次 `failed`，重跑 `already_attempted` |
| BudgetStop 后重跑 | 首次 `stopped`，重跑 `already_attempted` |
| 删掉中央台账 | `central_ledger_missing`，且不重建 |
| 替换中央台账为垃圾字节 | `central_ledger_unreadable`，字节未被改写 |
| 替换为"合法但非本阶段"账本 | `central_ledger_unrecognized` |
| 真实中央台账逐字节副本 | `phase_budget_exceeded`（见第 9 节发现） |

真实 `RESEARCH_LOG.md` 与真实中央台账 SHA256 前后一致（未触碰）。

## 8. 生产 `_train` / `_evaluate_arm` 实测

`reports/V9-P9/r6/evidence/ledger-and-eval.json`（数值后端替身，真实 RunStore、真实 development 数据、真实 3510 步）：

- 预留：3510 次 optimizer 预留 + 1 次 wall-only（检查点 0）；`post_final_optimizer_reservations=0`；最终检查点只写 1 次；run 终态 `completed`，`reserved_optimizer_steps=3510`，`remaining.optimizer_steps=0`。
- 3511 边界负面控制：文档 `updates=3511` 而 run 预算 3510 → `BudgetStop: optimizer_step_budget`，run 停在 `training`，直接 `consume` 也被拒。
- eval：run 绑定 `passed`（从中央台账 completed run 的不可变 reason 取原 SHA，不用 `run_info.json`）；六组指标齐全；`unseen_map`/`topology` 各 200 episodes/200 worlds；few-shot k=0..4 有数据、k=8 `insufficient_data`（200 个开发世界没有一个能提供 8 条 support 转移外加留出 query）。
- 绑定负面控制：篡改检查点 / 删除检查点 / 错 prereg SHA 全部拒绝。
- 调用记账（未变，仍超注册值）：window probe 5 次 175 批量、`step_sequence` 611 次、`probe_graph` 800 次、`encode` 3500 次，注册 `eval_batches=48`。

## 9. 需要 tier-1 裁决的发现

1. **真实中央台账的阶段墙钟总额已超限**：`RunRecord.wall_seconds = now - created_at`，三条 r1 辅助 run 的该值随时间无限增长，当前合计 **133,102 s**，阶段上限 14,400 s。因此锚定生效后，规范根上任何 `train` 都会被 `phase_budget_exceeded` 拒绝（隔离模拟第 11 项即此）。这是 fail-closed 的正确方向，但意味着阶段在实际训练前就已"过期"。建议（**未实施**，属于 S1 adapter 层可选修复）：阶段总额对终态历史行改用 `updated_at - created_at`（≈720 s 真实占用），或由 tier-1 显式 reconciliation 那三行；改法会动 r5 冻结的守卫语义，故只报告不动手。
2. **eval 调用量 vs 注册 `eval_batches=48`**：suite 实际调用量远大与注册值；r6 选择 fail closed（`eval_call_budget_exceeded`）而不是静默扩大，需 tier-1 重新注册或裁定口径。
3. **few-shot k=8 全量 `insufficient_data`；k=4 仅 50/200 世界**：开发分区数据特性，非代码缺陷，需在结果表中如实披露。
4. **arm1 无检查点绑定**：冻结 D 候选没有已训练检查点，eval 入口 fail closed。
5. **r1 prep 实验 3600 s 墙窗已过期**：规范根上新的 prep 模式 run（data/smoke）会被实验墙预算拒绝；这是正确 fail closed，但若需重新测量需 tier-1 处理实验窗口。

## 10. 测试结果

| 范围 | 结果 |
| --- | --- |
| `tests/v9/experiments` | **198 passed**（r5 为 146；r6 新增 52 例：probe_graph 17、deadline 9、ledger anchor 13、entry guards 13） |
| `tests/v9/geometry`（隔离复跑） | 149 passed |
| `tests/v9/contracts` + `teachers` + `tokenization` | 229 passed |
| `tests/v9` 合跑 | 568 passed, 2 failed——既有进程污染：合跑时有测试模块在 import 期拉入 MLX，使 2 个 geometry "CPU-only import" 检查失败；各套件单独跑全绿（r5 已记录的同一现象） |

junit：`reports/V9-P9/r6/logs/tests-s1-r6.xml`。

## 11. 限制

- 数值 CPU 替身；无 MLX 前向/梯度/优化器，无真实训练/评测，无任何能力或科学结论。
- 训练损失是占位常数，sample-efficiency 数值只证明管线连通。
- 未写任何批准行；真实 9 个 arm×seed run 仍被拒绝（本卡不授权）。
- 作者不能验收自己的作品；需非作者复核（P16）。
