# ainerzero.V9.P16 执行报告（非作者独立复核）

角色：executor（二级）；负责人：workbuddy-c4k8（WorkBuddy AI，tier 2）；时间：2026-10-21（客户端）
任务状态：reported；实验状态：未执行（纯 CPU 工程复核，无真实训练/评测）
任务依据：ainerzero.V9.P15 的 r5 修复（承接 P13 r4 负面复核与 P15 修复裁决）；本卡为非作者独立复核，依据 AGENTS.md / COORDINATION.md / P14-ACCEPTANCE-ADDENDUM / P15-REPAIR-DECISION 与 P15-r5-frozen-review-inputs.json。
被验证任务作者：ds-s1r5-1021n（deepseek）。本代理 ID 与之不同，满足“非作者”资格。

## 输入身份（独立复算的哈希）
- r5 冻结文档 SHA256（canonical）：`c2f56b5ac79706417bcf0a810fcabd984c57b21c06143df45e00cf2917a7c98d`（与 P15 报告一致 ✅）
- r5 落盘文件 SHA256：`895bb3676cd3db6ad7995814ee940e23b1bff55747e8dea665f5fe426386075b`（与 P15-r5-frozen-review-inputs.json 的 `prereg_file_sha256` 一致 ✅）
- 数据集 digest：`8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`（未变）
- 14 个绑定源码文件 on-disk SHA：14/14 与 frozen-review-inputs.json 期望值逐一吻合 ✅
- `prereg.source_binding_state` 项目自带权威检查：`status=passed` ✅
- 冻结步数 `updates=3510`，检查点 `[0,439,878,1755,3510]`；`deadline_seconds=450`、`supervision_seconds=500`；arm2/3/4 × seed 0/1/2（均未变）

## 修改文件
无源码修改。本卡只新增 `reports/V9-P16/` 下的复核产物（见末尾产物清单）。未提交、未推送、未训练、未下载模型、未写批准行、未改历史证据。

## 实际执行（独立隔离复核）
- 评审代理：workbuddy-c4k8（与被验证任务作者 ds-s1r5-1021n 非同一 agent，符合非作者复核资格）。
- 编写并运行**独立**验证脚本 `reports/V9-P16/verify_p16.py`（用 `.venv` 的 numpy 运行），全程**未复用** P15 的 `ledger_and_eval_evidence.py`，且使用**不同的 CPU 后端替身**（IndependentBackend，参数以 2×2 矩阵而非 P15 的 1×1 标量，便于检测参数写入/SHA 变化）。
- 关键约束遵守：运行的是**生产 `_train` 函数本体 + 真实 `RunStore` 账本**（PrepLedger 走真实 SQLite），并**直接计算真实 3510 次 optimizer 预留计数**；**未整体 stub `_train`、未对 ledger 做 +1000 之类豁免**。
- 真实数据：从 `artifacts/v9/s1/datasets/8234f2f…` 加载真实 development/training 分区；window_probe 按真实窗口逐条返回。

## 验证结果与逐条核对

### A. 实际 3510 台账路径 + 一次最终检查点（生产 _train 本体 + 真实 RunStore）
- 实际 optimizer 预留计数 = **3510**（与冻结 updates 逐一相等）。
- 检查点写入 = `[0,439,878,1755,3510]`，**最终检查点（params.npz）恰好写 1 次**。
- 最终检查点文件 SHA == receipt SHA == 绑定 SHA（三处一致 ✅）。
- 账本 `reserved_optimizer_steps=3510`，`remaining.optimizer_steps=0`，run 终态 `completed`。
- 末步之后的 optimizer 预留 = 0；`post_final_optimizer_reservations=0`。
- 完成后的 `train_attempts` 能回查到该 run（即“任一已启动 attempt 计入、completed 后仍拒绝重跑”的账本依据成立）。

### A2. 3511 越界拒绝（预算边界）
- 文档要求 updates=3511、但 run 预算冻结为 3511-1=3510：第 3511 次 optimizer 预留被账本以 `BudgetStop: optimizer_step_budget` 拒绝；run 停在只消耗 3510 步。
- 完成后直接 `store.consume(run, optimizer_steps=1)` 亦抛 `BudgetExceeded: Budget exhausted: optimizer_step_budget`。
- **结论：r5 修复只把 run 账本 `max_optimizer_steps` 设为冻结 updates，没有把 optimizer 预算改成 3511，也没有 ledger +1000 豁免**（与 P15-REPAIR-DECISION 要求一致）。

### B. 评测绑定（原 SHA & run 绑定）+ 坏控
- 干净完成 run → `_bind_completed_run` 成功返回 run/检查点/最终 SHA。
- 篡改最终检查点字节 → `EvalBindingError`（现算 SHA ≠ receipt SHA）。
- 删除 `updates-0.npz` → `EvalBindingError: missing`。
- 错误 prereg SHA → 无匹配 completed run → `EvalBindingError`。
- **结论：eval 回查合法已完成 run 并现算核原 SHA，不信任 run_info.json（其 authoritative=false），不把被改文件现算摘要当期望值。**

### C. 六指标符合冻结定义 + 预测变化反例 / 定向破坏对照（独立重算 ≥2 项）
直接用 `metrics.py` 真实函数 + 自建输入逐组验证（不依赖 P15 的输出）：
- `localization_error`：预测平移变化 → translation_mean 由 0.5 → 3.0，且空输入被拒 ✅。
- `few_shot_transition_metrics`：预测变化 → accuracy 由 1.0 → 0.5，空输入被拒 ✅。
- `topology_edge_metrics`：预测边变化 → precision 由 1.0 → 0.0（真正例 2→0）✅；`topology_report` 按 episode 独立聚合、按 family 分离（per-family，不把首 episode 当全局）。
- `strict_unseen_map`：**拒缺 NLL（null 不冒充 0）、拒重复 episode、拒缺身份字段** ✅（即“空样本假 0 / 跨 world 混图”防护）。
- `split_support_query`：k=8 且世界 transition 不足 → 返回空（caller 报 `insufficient_data`，绝不返回完美值）✅；k=8 充足时返回 support+query ✅。
- `memory_interference`：before/after 无共享键 → 被拒；`interference_probes` 要求参数 SHA 前后一致否则拒绝（拒绝参数变化）。
- **真值边界**：`observation_prediction_metrics`/NLL 仅进独立评分旁路；support 不更新参数、query 不泄露未来或真值（由 `_train`/`_evaluate_arm` 调用约定保证，未做反向越权测试但代码路径无真值写入模型分支）。

### D. 核完整逐叶差异 + 资源/种子/步数不变 + 身份
- 独立重算 r4→r5 逐叶差异：398 叶中仅 16 处变化，且**全部落在 allowlist 内**（created_unix；source_identity.package_files.{arms,commands,data,evaluation(新增),metrics,worker}.py；source_identity.package_map_digest；timing.smoke_recheck.* 移除），**allowlist 之外 0 处** ✅。
  - 与 P15 的 `prereg-leaf-diff.json` 结论一致（差异仅在于本代理把被移除的 `timing.smoke_recheck` 整个子树计为 1 个节点，P15 逐叶子枚举为 7 个；方向一致、均在 allowlist）。
- 14 个绑定源码文件 on-disk SHA：14/14 与 frozen-review-inputs.json 期望值吻合 ✅；`unbound_package_py=[]`（无未绑定依赖闭包需补审）。
- `updates=3510`、检查点、seeds=[0,1,2]、dims、metrics 定义、stop rules、data_identity 均未变（冻结文档内核对）。

### E. 预算 / 身份 / 阶段目录边界（CPU 隔离反例）
- **新 output-root → 新 control.sqlite3（账本重置）**：空 ledger 的 `train_attempts` 返回空（即“复制冻结件/数据到另一 --output-root 或新建 control.sqlite3 会把同阶段账本重置成看似可再跑”在账本层成立）。
- **但权威拒绝点不在账本层**：该 fresh-root 上的 `worker.run_worker(mode=train, ...)` 仍被拒绝，拒绝阶段 = `preregistration_not_approved`（因为 RESEARCH_LOG.md 没有对应该文档 SHA 的协调者批准行，本卡也未写批准行）。即**同阶段预算/同 arm×seed 重置并不能真正再跑**——权威保护是批准门 + 源码/数据集绑定，而非 per-root 账本。
- `--research-log` 指向非 canonical 路径 → 拒绝阶段 = `research_log_not_canonical`（worker 只读仓库 RESEARCH_LOG.md，重定向路径被拒）。
- 切换 `--prereg` 到被篡改（非冻结）文档 → `verify_frozen_file` 因文档 SHA 自洽校验失败而拒绝。
- **结论：实现未“钉死 canonical storage/root”做跨目录绕过防护；跨目录重置只发生在 per-root 账本层，真实再跑被批准门 + 源/数据绑定拦下。无证据支持“全部跨目录绕过已防”，本卡据实声明实际拒绝点。**

### F. 末步更新 / sleep / IO 跨 450s 明确拒绝，500s 仅兜底
- 冻结 `deadline_seconds=450`、`supervision_seconds=500`。
- 验证 `_train` 内循环顶部的 per-run 截止守卫：run wall 预算设 600s（避免先撞 wall），但文档 in-loop deadline 设 0.001s、后端 value_and_grad 每次 sleep 0.05s → 第 2 步即抛 `TimeoutError: frozen per-run deadline exceeded`，被 worker 捕获为 failed/stopped。
- **结论：450s 是明确的 per-run 截止拒绝点；500s 是 commands.py 监督进程的硬超时兜底（外层），二者分工与 P15 描述一致。**

## 与 P15 披露一致的独立确认
- **k=8 全局 `insufficient_data`**：独立加载真实 development 分区实测 200 个世界，**≥9 个 transition（k=8 所需）的世界 = 0/200**；≥5（k=4 所需）= 50/200；中位 3.5、均值 3.75、最大 6 个 transition/世界。与 P15 报告的「k=8=0/200、k=4=50/200」精确吻合 ✅。这是冻结协议与数据粒度的真实冲突，需统筹决定披露接受或另开卡调数据/指标登记。
- **评测调用量超旧登记**：冻结文档仅 `eval_batches=48`，而 r5 评测套件含 175 个 window batch 之外还有 ~611 次序列前向/1703 帧与 3500 次 encode。P15 未静默扩预算、未做真实 eval，已明确上报缺口。本卡确认该缺口属实（P15 报告已登记，非伪称零差异）。
- 无真实 MLX 前向/梯度/优化器或真实训练/评测；所有数值为替身，**不用于任何能力或科学结论**，不晋升任何模型。

## 失败与限制（如实写，不当作通过）
- 未做真实 MLX 训练/评测，所有数值为 CPU 替身；指标只能证明管道与身份对齐，**不能**得出科学/能力结论。
- r5 未写批准行；9 次真实 arm×seed 训练仍应被 train 门拒绝（`approval.approved=false`）。本卡未启动、未消耗任何真实训练预算。
- k=8 在真实 development split 全局不可用，k=4 仅 50/200 世界（数据粒度冲突，见上）。
- 评测调用量高于旧 `eval_batches=48` 登记，真实评测预算尚未重新登记。
- `arms.py` 模块级导入 MLX 是 r5 之前既有结构；本卡 CPU-only 证明只覆盖 arm2/3/4 评测导入图与全部新测试路径。
- 跨目录重置的权威防护来自批准门 + 源/数据绑定，而非 per-root 账本；本卡未验证“全部跨目录绕过已防”（无证据，已据实声明）。
- P14 的其他系统性问题未在本卡范围内全部重验；本卡只复核 P15 列出的预算/检查点/指标/重跑/绑定范围。本卡不替代 P14 负面证据，也不构成 P15/P1 接受。

## 交回统筹（需决定的问题，不擅自追加运行或换参数）
1. 接受 P16 非作者独立复核结论：P15 的 r5 工程修复（3510 台账、一次终检、3511 拒绝、重跑拒绝、原 SHA/run 绑定、六指标符合冻结定义、逐叶差异在 allowlist 内、14 文件身份吻合）**独立可复现**。
2. 对 k=8 全局 `insufficient_data`、k=4 仅 50/200 世界给出处置（披露接受 / 另卡调数据或改指标登记）。
3. 对 r5 评测调用量超出旧 `eval_batches=48` 给出新的评测预算/登记，之后才可真实 eval。
4. 只有上述完成且一级在 RESEARCH_LOG.md 写入批准行后，真实 9 次 arm×seed 训练才可能启动；本卡未启动、未消耗任何真实训练预算。

## 产物清单（均在 reports/V9-P16/）
- `REPORT.md`：本报告。
- `P16-METRICS.json`：结构化验证指标（逐条 pass/fail）。
- `evidence_p16.json`：独立验证脚本的完整原始输出（含各 reserved_optimizer_steps、SHA、坏控、指标反例、逐叶差异、身份核对、边界反例）。
- `verify_p16.py`：独立验证脚本（可重跑；用 `.venv/bin/python reports/V9-P16/verify_p16.py`）。
- `P16-r5-frozen-review-inputs-verified.json`：本卡对 frozen-review-inputs.json 的逐项核对（14 文件 SHA、updates、seeds、unbound_package_py）。
