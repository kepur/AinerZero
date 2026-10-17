# AinerZero 执行层任务清单

## 2026-10-17 当前入口：r5 + 角色优先兼容扩展

用户已同意“工作台和方案落地”，工作台明确为现有 AinerRelay。**CF-r1-20261017** 为角色优先兼容扩展设计正文；最终采用状态与精确SHA见本轮[DECISION](reports/character-first-landing-20261017/DECISION.md)、[publication.json](reports/character-first-landing-20261017/publication.json)及工作台awz.CF.A3发布记录（登记中）；现行 **V9-r5-20261016 + v10 工程验证层** 与原冻结 JSON 继续有效。

[ADR-0013](../AnimeWorldZero/docs/adr/ADR-0013-character-first-production.md)、[逐卡落地计划](../AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md)。Hub 意图/编辑→跨工具编译→AWZ准入/运行求值→既有Hub worker；CPE/ACC/TACE沿原合同补齐。AinerZero旁路学习、训练暂停及M2常设对照不变。

代码总门 `awz.V9.A10` 未放行；本轮不写实现/Schema，不训练、下载或实跑。任务先按现有AinerRelay登记，真实ID/模块/依赖和即时状态由主责后续registration报告记录，不将本地草案冒称在线卡。

以下原基线与旧记录保留其出版时语境；旧“当前”字样不替代本节和最新独立报告。

新增队列以逐卡计划为正文：先设计/消费者映射，再runtime绑定/真实角色与统一worker/最小DAG缓存，同批P0身体+表情口型+编辑消费，再接触双人、跨镜头15秒QA。每项实现配非作者验证，原卡范围、paused与业务依赖保留；下方原19/21集合是2026-10-16出版快照，不当实时总数。

更新：2026-10-16 · 平级统筹：Codex / Claude · 当前只收口设计与任务

## 当前任务入口：V9-r5-20261016

主架构和后续任务统一见 [ARCHITECTURE_BASELINE.md](ARCHITECTURE_BASELINE.md)、[跨仓落地方案 §12](../AnimeWorldZero/docs/design/V9_LANDING_PLAN.md#12-当前定版入口与实施队列2026-10-16)。Relay 是任务状态与领取入口，本文件以下保留历史任务正文。

- 原19张实现卡继续 blocked，新增2张实现卡 draft；总门 `awz.V9.A10` 保持 draft，原业务依赖不能被替换。包括 CPU 实现也不因“不训练”自行开工。
- 目前只领取文档设计、补修与非作者只读复核。Event/v1 与 T1 的新发现分别补回原设计卡；不以已有正例全绿替代这些未关闭边界。
- 今后实施顺序：契约设计补齐与复核 → 用户明确放行代码 → 接口/校验/来源缓存 → 世界运行与传感出口 → 稀疏更新与小样 → 获批教师与预登记实验。具体依赖及每张验证卡见基线索引与 Relay。
- 训练暂停、固定科学门、来源政策、原报告与预算不变；任何新模型工作仍走 CLI、共享锁、RunStore 和既有资源守卫。

## 历史任务记录（2026-10-12 起）

以下原文中的“当前可领取”“下一步”等仅代表记录当时，不能作为当前领取、代码或运行授权。

执行者先阅读 [README](README.md)、[分工规则](COORDINATION.md)、本任务对应协议和 [研究记录](RESEARCH_LOG.md)。M2m-c完成且未晋升，C05设计固定，E13a/R2已按独立109项CPU回验限范围验收；当前可领取E13b接入，不重复训练。S01/S02/S03及公开fixture/引用归档已按342项独立CPU范围验收，无失败/跳过/xfail；含MLX全量本轮未重跑。时空工程收尾后回到E13动作保持实现，不直接进M2n。

## 任务总表

| ID | 执行任务 | 依赖 | 状态 / 负责人 | 交付 |
| --- | --- | --- | --- | --- |
| E00 | 核对 M2m-a 来源、账本、判定及测试记录 | 无 | accepted / execution_evidence_check；Codex 已复核并采纳勘误 | 只读证据报告，文案过强项 |
| E01 | 阶段 B 数据与换名清单准备 | 统筹方案纠正 | reported / 外部执行者待确认 | CPU 覆盖统计、训练与评测映射身份、预算核算 |
| E02 | 一致换名与固定池评测实现 | E01 | reported / 外部执行者待确认 | 换名记录接口、冻结评测、对应测试 |
| E03 | 阶段 B 运行器与 CLI 接入 | E01；集成 E02 | reported / 外部执行者待确认 | 有界入口、谱系校验、保护与恢复点 |
| E04 | 独立工程测试与协议审查 | E02 + E03 | reported / 外部测试报告；本次执行 agent 已核对 1,856 项通过 | 测试 XML、静态检查、失败路径报告 |
| C01 | 统筹审查与具体运行登记 | E01–E04 | reported / 外部主责待交接；实际已登记运行 | 最终协议、配置哈希、运行身份、执行任务 |
| E05 | 一次有界训练和评测 | C01 的具体运行任务 | accepted / 外部执行者待确认；run 056e38aa… completed，能力未过 | 原始报告、日志、200 次更新、候选检查点 |
| E06 | 独立产物核对与结果报告 | E05（含失败情况） | accepted / execution_evidence_check；Codex 按有限核对范围接受 | 账本/预算/最终参数/逐格复算，见决策记录 D04 |
| C02 | 优化决策与根目录记录更新 | E06 | accepted / Codex；学习率方案已由执行者完成，结果接收见 C04 | 保留候选、学习率对照、决策日志 |
| E07 | 曲线、梯度与覆盖的 CPU 审计 | E05 | accepted / execution_evidence_check，与 E06 同批核对 | 损失趋势、200 次裁剪、数值/梯度、3,200 双射重放 |
| E08 | M2m-c 学习率对照实现及测试 | E06/E07 验收 + C02 | reported / Grok Bot；代码与固定协议已交付 | 固定 0.003 单一协议、来源/预算检查、测试报告 |
| E09 | M2m-c 工程与协议审查交付 | E08 | reported / Grok Bot；测试 XML 已交付，非另一 agent 的完整独立验收 | 旧协议未改、单因素核对、真实测试记录 |
| C03 | M2m-c 唯一运行登记与交接 | E08 + E09 | reported / 用户直接授权 Grok Bot 实现、登记并运行；Codex 提供方案 | 具体 ID、最终命令、源码与配置身份、资源检查 |
| E10 | M2m-c 一次有界训练和报告 | C03 | reported / Grok Bot；run 9169008d… completed，迁移过/回归触发/未晋升 | 与 B 相同查询的结果、回归和失败记录 |
| E11 | M2m-c 复算报告交付 | E10（含失败情况） | reported / Grok Bot 的独立实现脚本；本次另由 m2mc_handoff_audit 只读核对有限项目 | 新旧候选差值、账本与恢复核对、交回统筹 |
| C04 | M2m-c 结果接收、勘误与共享文档 | E08–E11 交付 | reviewed / Codex；已接收进度与有限核对，未晋升 | 结果、证据边界、S01 作者与记录 |
| E12 | 动作保持候选的 CPU 路径与成本审查 | M2m-c 结果 | reviewed / 内部与外部 m2mc_handoff_audit 报告；Codex 已审议，另由 c05_budget_reconciliation 核算 | [内部路径审查](artifacts/reports/E12-action-preservation-review-20261012.md)、[外部建议](artifacts/reports/E12-m2mc_handoff_audit-20261012T1047+0300.md)、[预算差异核对](artifacts/reports/C05-budget-reconciliation-20261012.md) |
| C05 | 固定动作保持候选协议 | E12 | accepted / Codex；仅设计完成，未登记真实运行 | [M2m-d](M2MD_ACTION_PRESERVATION.md)：M2d 重启、λ=1、最多4边后缀、208,546单位/1,610秒；不直接进 M2n |
| E13 | M2m-d 蒸馏保持实现与 CPU 协议测试 | C05 | reported（部分：CPU协议层；worker/CLI/MLX接入未做） / grokbot-newbot（2026-10-12 15:13 领取，15:20 交报告） | 独立协议、教师缓存/随机键/损失/梯度保护、精确预算、失败测试；不启动 MLX |
| E13a | M2m-d CPU协议层交付 | C05 + R1/R2 + E14a-R2 | accepted / Codex限CPU范围；原作者grokbot-newbot，R2执行e13a_r2_identity_boundary | [独立109项回验](artifacts/reports/E14a-R2-independent-review-20261012.md)通过；worker/CLI/数值接入未完成 |
| E14a | E13a独立CPU审查 | E13a | reviewed / s01_repair_scope_review；Codex接收审查、未验收协议层 | [审查报告](artifacts/reports/E14a-action-preservation-protocol-review-20261012.md)：23项通过但有F01–F05边界缺口，无模型 |
| E13a-R1 | 修复冻结计划/源身份/缓存/梯度CPU不变量 | E14a + 统筹接口固定 | reviewed / grokbot-newbot；50项R1快照保留，F02余项由R2修正后整体验收；新增fixture `tests/fixtures/m2md_pool_manifest.json` | 按 [补修单](E13A_PROTOCOL_REPAIR.md) 修F01–F05，科学参数/原worker/CLI不改 |
| E14a-R1 | 补修后独立CPU回验 | E13a-R1交付 | reviewed / e14a_r1_review；Codex接收，F02消费边界转R2 | [独立报告](artifacts/reports/E14a-R1-independent-review-20261012.md)：50通过、真实16公开episode核对，未验收整体 |
| E13a-R2 | 固定登记身份/分层状态/窗口消费重验 | E14a-R1稳定报告与文件移交已完成 | accepted / e13a_r2_identity_boundary实现，Codex按独立109项CPU回验接受；源码0d897c68…75aa2 | 按 [边界补修](E13A_IDENTITY_BOUNDARY.md) 处理剩余F02，不改科学参数/摘要schema |
| E14a-R2 | 固定身份与消费边界独立CPU回验 | E13a-R2稳定交付/文件已释放 | accepted / e14a_r1_review独立审查，Codex限CPU范围验收 | [独立报告](artifacts/reports/E14a-R2-independent-review-20261012.md)：109全过、固定v2/keys/plan/成本复算一致，未运行模型 |
| C05b | E13a-R2统筹复核与E13b接入规格 | E14a-R2 | accepted / Claude | [复核](artifacts/reports/E13a-R2-claude-coordinator-review-20261012.md)同意限CPU范围验收，提出B1/B2；[接入规格](E13B_INTEGRATION.md)固定文件范围/接口/CPU测试，不授权运行 |
| E13b | 独立入口与MLX训练路径接入 | E13a-R2与E14a-R2回验通过，统筹验收E13a；C05b规格 | reviewed / Claude核对未accepted，需R1；原作者grokbot-newbot（21:45领取，21:56交付；[报告](artifacts/reports/E13b-grokbot-newbot-20261012T215628+0300.md)：新增40+原109+旧379项CPU全过、P1通过；MLX路径已实现未运行） | 新建closure/mlx两模块，改memory_worker新分支与CLI新子命令；B1/B2生产门、首更新零不变量、T1–T8与P1只读探针；不跑MLX，真模型等C06a |
| E13b-R1 | paired全复算与C06a有界探针入口 | E13b统筹决定 | reported / grokbot-newbot（22:47领取，22:51交付；[报告](artifacts/reports/E13b-R1-grokbot-newbot-20261012T225120+0300.md)：59+109+379项CPU全过，P1重跑通过，探针入口已实现未运行；C06a未登记故未跑） | 按 [E13b规格](E13B_INTEGRATION.md) 末节“交付后统筹决定” 补paired全部字段复算＋交换反例、query manifest自查；新增 `probe-action-preserved-memory`（5,025单位/179秒，截止229/279，3次更新，不存checkpoint）；重跑P1并分列时钟高水位；不运行MLX |
| E14b | 接入的静态/CPU失败路径审查 | E13b＋E13b-R1 | **reported / E14b-independent-review，10-12 22:18→10-13 09:08；E13b＋R1 静态/CPU 范围通过，待统筹 reviewed** | [最终报告](artifacts/reports/E14b-integration-independent-review-20261013.md)：R1身份5项一致、独立重算paired **87,822字段差0.0**、探针入口5,025/179/229/279复算一致、交换反例被拒、query manifest自查、583项CPU测试0失败、账本门10负例、控制库仅时钟高水位；pre-R1版[报告](artifacts/reports/E14b-integration-static-cpu-review-20261012.md)保留 |
| E14 | M2m-d 独立工程与预算审查汇总 | E13a/R1/R2 + E13b + E14a-R2/E14b + C06a结果 | todo / 审查执行者待领取 | 实际源码和调用清单与协议一致，旧 B/M2m-c 未改，测试/XML及未验证项 |
| C06a | 有限数值/资源预检的具体登记与验证 | E13b-R1 + E14b | **reported / Claude，2026-10-13 09:13–09:14 唯一一次登记运行；判读(b)，用户批准登记 τ=1e-5 首更新界** | [预登记](artifacts/reports/C06a-probe-registration-20261013.md)、[执行报告](artifacts/reports/C06a-probe-execution-20261013.md)：run `6ac8b328…ddac` completed、5,025单位/179秒/3更新/23.73秒、教师缓存重复逐位一致、冻结282,128逐位、裁剪冻结行0、优化器树仅GRU、峰值30.2MiB；首更新16行keep loss ±1.21e-7→**修订界1e-5**（[规格附录](E13B_INTEGRATION.md)），修订后585项CPU测试0失败 |
| C06 | 唯一训练运行身份、命令和资源登记 | E14b已过 + C06a已交付 + τ修订已记录 | **reported / Claude**：原登记已执行（E15 首次失败）；修复后[重跑登记](artifacts/reports/C06-rerun-registration-20261013.md)待授权 | 原登记[文件](artifacts/reports/C06-training-registration-20261013.md)；修复后 worker `939f230b…aca8`、其余不变；新 experiment `m2md-action-preserved-20261013-r1`，208,546单位/1,610秒；不追加未登记预检 |
| E15 | M2m-d 一次有界训练与完整评测 | C06 的具体运行交接 | **reported（修复后重跑 completed，未晋升）/ Claude，2026-10-13；首次尝试 failed 已留档** | [结果报告](artifacts/reports/E15-m2md-training-20261013.md)：run `d96b3c79…3abb` 200次/208,546单位/382.5秒/峰值30.3MiB；零状态3,930/4,096与换名池1,998/2,048两项**通过**，动作一步287/384、四步266/384、ΔNLL+1.1751/+1.4051**失败**，重建544/544，`preservation_screen=failed`、历史memory_screen failed；[首次失败](artifacts/reports/E15-first-attempt-failure-20261013.md)保留 |
| E16 | M2m-d 独立结果核对 | E15（含失败） | **reported（第二方独立核对完成，verdict = passed：8 条主张 0 证伪）/ subagent e257091d，只读、无 MLX、未改实现** | [独立报告](artifacts/reports/E16-independent-verification/E16-independent-report-20261013.md)：逐格重算 dev 4096/3930/127/115、动作 377→287、359→266、ΔNLL +1.1751/+1.4051（36 字段差 0.0）；换名池 63 字段零差；冻结 282,128 含三组负控制；账本/无晋升/200 行日志；另从 dataset 重建整条生产闭包与单位表。**发现**：F1 核对期间源码被改（已登记为遥测修订并冻结工作树）、A1 日志键覆盖（已完整修复 `d795690e…`）、两项账本语义注意（见 [决策记录](RESEARCH_LOG.md) D20261013-23） |
| E20 | C07 λ=10 单因素对照 | E17 诊断＋用户授权 | **reported（负结果：动作门仍失败且更差，未晋升）/ Claude；复核 approved，F1 已修** | [结果报告](artifacts/reports/C07-result-20261013.md)、[复核](artifacts/reports/C07-review/C07-independent-review-20261013.md)、[登记](artifacts/reports/C07-run-registration-20261013.md)：run `db8c9a7c…` 200次/208,546单位/394.2秒；零状态 3,904 与换名池 1,972 仍过门，动作 273/266、ΔNLL +1.605/+1.821 更差；机制证据＝教师拟合更好/尾部位移更小但动作更差 → 目标与覆盖失配，非量级不足；下一步 D/E/B/F 待选 |
| E21 | D 条件：批内教师蒸馏（实现·复核·运行） | C07 负结果＋用户选择 D | **reported / Claude：run `96b72328…` completed，五门全过，未晋升** | [结果报告](artifacts/reports/E20-d/D-result-20261013.md)、[复核](artifacts/reports/E20-d/review/D-reverification-20261013.md)、[登记](artifacts/reports/E20-d/D-run-registration-20261013.md)：184,704单位/1,540秒/480.4秒；开发 4,007/4,096（变化124）、换名池 2,016/2,048（变化138）、动作 377/384（ΔNLL−0.0090）、359/384（−0.0773）、重建544/544；**首次通过动作保持门**，历史 memory_screen 仍 failed；两次失败尝试留档 |
| E22 | D 条件结果报告与只读核对 | E21 运行 | **reported / Claude：run `96b72328…` completed、五门全过、未晋升** | [结果报告](artifacts/reports/E20-d/D-result-20261013.md)、[核对输出](artifacts/reports/E20-d/r2_verification.txt)（verdict=passed）、[核对脚本](artifacts/reports/E20-d/verify_and_report.py)；两次失败尝试留档 |
| E23 | M2n 非零历史一步保持（实现·复核·运行） | E22＋用户"推进" | **reported / Claude：run `ddb5882a…` completed，负结果（四门退步、历史主门仍失败），未晋升** | [结果报告](artifacts/reports/E23-m2n/M2N-result-20261013.md)、[运行后复核 supported](artifacts/reports/E23-m2n/review/M2N-postrun-verification-20261013.md)、[登记](artifacts/reports/E23-m2n/M2N-run-registration-20261013.md)：255,104 单位/1,740 秒/489.5 秒；开发零状态 2,218（D 4,007）、换名池 1,108（2,016）、动作 NLL +0.0755/+0.6183；**经运行后复核修正归因：纯 CE 与 D 持平（2.1269 vs 2.1060），机制＝能力置换＋师生发散（非欠拟合）；历史无相对优势（0.3780 < 0.6142）；唯一正面进展＝稠密读回 0→0.3057**；首轮 57.8 秒 fail-closed（单边不变量误伤，已修＋回归）留档 |
| E17 | 保持项只读诊断（λ=1 为何没保住动作） | E15 结果 | **reported / Claude，纯 CPU 只读** | [诊断报告](artifacts/reports/E17-diagnosis/keep-branch-diagnosis-20261013.md)：keep/memory 梯度比中位 3.7%、应用能量 99.9% 在尾部、keep loss 单调升、未变化格 100%→76%/74%、池覆盖 256/256 行；附日志键 `raw_front_gradient_l2` 被覆盖的发现；候选单因素 A–D |
| E18 | M2n 非零历史方案草案 | E15＋E17 | **reported（草案，未授权运行）/ Claude** | [方案](M2N_NONZERO_HISTORY_PROPOSAL.md)：推荐先做 λ=10 单因素（同 208,546 单位/1,610 秒）修动作门，再进非零历史；门/预算/起点与"不自动进 M2n"的边界已写明 |
| E19 | 含 MLX 全量工程测试（持共享锁） | 用户 2026-10-13 指令 | **reported / Claude**：三次运行；最终冻结修订 **2290 passed / 0 failed**（69.1 秒） | [报告](artifacts/reports/E19-full-mlx-suite-20261013.md)；第 1 次 2286/4（隔离性冲突，XML 保留）、第 2 次 2290/0（`229beafa`）、第 3 次 2290/0（`d795690e`）；运行器仅在外部 MLX 空闲时持锁开跑、不占训练预算 |

E01–E05 已有外部交付，E01–E04 的整个实现/工程协议尚未由本次统筹完整验收；缺口只针对既有实现提任务，不重复建设。E00、E05、E06/E07 已接受，有限核对范围见 [决策记录 D04](RESEARCH_LOG.md)。E08–E11 已收到 Grok Bot 的完整交付，按用户交接标为 reported；中央账本确认 M2m-c 完成。本次只读审查核对身份、计数、门槛及保存完整性，没有重新生成模型概率或复算冻结张量，不能把任务统一标成 accepted。任务表本身不自动启动运行。未来修改仍按下面文件边界领取。

## E01：数据和预算准备

- 只读已有公开训练数据，重建 M2l 的 256 条池与 200×16 调度；哈希必须与原报告一致。开发与最终验收数据不参与训练或映射选择。
- 用训练 RNG 2307 按更新、样本顺序生成 3,200 个一致双射。双射同时作用于两帧所有可见符号；掩码、光标、动作和 episode 标记保持合法，隐藏格保持占位 0。可见字节 0 仍是可换名的真实符号。
- 登记 256 个独立 seed 9103 评测双射，并核对与训练映射摘要不重合。映射不能按模型结果挑选。
- 报告每位置、全局字节覆盖及各字节的呈现次数；使用实际计数，不承诺“随机换名必然全覆盖”。把变换后的输入标记为训练增强或诊断变体，不伪造新观察经历。
- 初稿 178,304 单位 / 1,340 秒；当前登记执行版 264,480 / 1,670，增加 M2l 逐格重测和换名池基线共 86,176 / 330。核对版本、每日余额与所有额外调用，不漏记或事后改账。
- 已有报告为 `artifacts/reports/m2m-preflight.json`，不覆盖；补充核对用独立 task ID。只允许 CPU 工作，不启动 MLX。

## E02：换名与评测模块

文件范围：现有 `src/ainerzero/learning/relabel_memory.py`、复用的 `src/ainerzero/data/augmentation.py` 及对应测试；不修改 CLI、运行器或根目录研究结论。已有实现先核对，不能照初稿重复建模块。

- 复用现有 `permute_symbols`；增加可核对的映射摘要/状态记录时保持现有调用兼容，不另造完整学习系统。
- 测试同一映射覆盖两帧与全部格、双射、隐藏/可见 0、变化掩码保持、可重复 RNG、输入不被原地改写。
- 固定换名池评测使用冻结候选，8 粒子平均概率后评分，零状态一步，每次模型工作先预算。输出逐格准确性与 NLL，当前 codec 控制、变化格、按实际增强训练覆盖分层。
- 新评测映射不能与训练映射重复；codec 失败、非有限结果、键不配对或预算失败必须明确停止。
- 不把换名后的动作轨迹当作已验证的新仿真实验；本轮只评价上一观察保留。

## E03：运行器与入口

文件范围：`src/ainerzero/runtime/memory_worker.py`、`src/ainerzero/cli.py` 及入口/运行器测试。现有新增入口为 `train-relabel-memory`；以真实 CLI 和登记命令核对，不再另建重复入口。

- 独立阶段/协议身份；严格绑定 M2d 起点、M2l 池/调度、已完成 M2m-a 报告及账本。失败或未完整核对的来源不得通过。
- 200 次更新、原损失、原冻结头、尾部 111,104 参数、前半梯度上限、AdamW 后投影与 282,128 参数逐位核对照旧。
- 保存训练双射的顺序与摘要、RNG 恢复状态、源码/配置/数据身份、逐次损失、实际更新数及资源数据；只保存固定第 200 次候选。
- 原局部检查、连续记忆、一步/四步动作、当前重建、配对、固定换名池全部进入预算。配对每世界首条边检查一致；新旧候选比较使用相同查询。
- 完整经过共享 CLI 锁、中央 RunStore、受监督子进程及当前资源守卫。失败保留已耗预算、报告和原因，不自动补跑。
- 测试失败、启动前资源不足、谱系不符等情况时，不得保存“完成”候选或宣称跨进程续训。

## E04：独立测试报告

文件范围：测试、独立核对脚本及自己的报告文件；不自行修改训练配置、门槛或实现以让结果通过。若发现错误，提交最小复现，由统筹指派实现负责人修正后复验。

- 重点检查：来源错误提前拒绝、非训练数据拒绝、空/错映射拒绝、训练/评测映射碰撞、逐步预付、保护失败后真实更新数、超时/锁/资源失败留档、候选恢复核对。
- 增加有意义的回归测试；已通过且代码未变的检查不反复重跑。测试与 MLX 推理区分：需要真实模型的检查须另受模型预算控制。
- 交付实际测试数、失败/跳过数、耗时、运行命令、源码身份、XML 路径，以及没有执行的检查。单元测试通过不能代替学习效果评测。

## E05 / E06：运行与独立证据

E05 按 C01 指定的唯一实验 ID、最终 CLI 命令和配置执行一次。启动前核对 AC 电源、稳定内存余量及共享账本，不能通过降低 16GiB 余量线使训练强行运行；不停止其他服务。状态失败时立即留档并交回统筹。

E06 以只读 CPU 核对为主：

- 数据/映射/查询身份，完整 200 次计划与实际更新区别，固定与可变参数范围，训练/评测预算与每日账本一致。
- 第 200 次权重、优化器、RNG 与文件恢复，原检查点、M2k/M2l/M2m-a 报告未被覆盖；跨进程继续更新未测试就写未验证。
- 从逐格结果重新汇总相同查询上的新旧候选；报告池内、未选输入是否重复、开发、换名池，以及原动作和重建回归。
- 精确沿用 [阶段 B 判读与回归标记](M2M_PROPOSAL.md)；达到零状态迁移等级也不代表历史记忆筛查或正式晋升通过。
- 失败运行同样提交报告，不能仅转交最后一份成功输出。

当前外部产物前缀为 `artifacts/reports/m2m-`，协议见 [执行版](M2M_CONSISTENT_RELABEL_FIT.md)；不改名或覆盖它们。后续独立核对另用 task ID 区分。E05 完成报告、E06 独立核对与 C02 决策互相链接。

## E07–E11：M2m-c 已交付任务与原约束

E08–E11已reported，下面保留原实施/核对要求，不重新领取或补跑。E12/C05设计固定，S01–S03 CPU工程已验收，当前可领取E13b接入；CPU源码/测试/fixture已冻结，尚未登记下一候选训练。

E07 仅用已有 `updates.jsonl`、覆盖清单与源码核对：每 20 次损失均值、梯度裁剪率、冻结/前半保护、输入/目标换名一致性和各位置真实字节呈现次数。全局字节覆盖是必要诊断，不能当作已学会全部组合；较低损失也不替代迁移。发现缺失直接报告，不补跑模型填数。

E08 文件范围：`runtime/memory_worker.py`、`cli.py`、相关来源校验与测试。实现 [M2m-c 固定候选](COORDINATION.md)：仅学习率改成 0.003；从原 M2d 重置优化器，固定 200 次，与阶段 B 的样本/调度/换名/评测身份逐项一致。使用独立协议名与输出路径，保留原 B 入口/计划；不添加通用参数搜索、自动学习率重试或在 B 权重上续训。对照 B 的已有逐格结果只做 CPU 复算；若增加模型调用，向统筹交回预算差额。

E09 独立核对唯一训练差异、梯度保护、原 B 回归测试、来源不符提前拒绝、非有限与预算失败留档；提交实际 XML 和未执行项目。与 E08 同文件有冲突时由实现者修复，测试者不改规则让结果通过。

C03 必须把最终 manifest、264,480 / 1,670 草案核算、截止/监督、资源状态和真实 CLI 命令写清，再交 E10。E10 只执行一个固定候选，E11 独立汇总；无论成功失败都交回统筹，不现场增加训练次数、改 seed 或继续搜索。相同 200 更新只使本对照工作规模可比，不是保证局部拟合成功。

## E12 / C05：已审议的动作保持设计（未启动新模型工作）

E12 只读现有源码和报告，提交自己的 CPU 报告，不修改运行器、损失或门槛：

- 列出记忆尾部如何通过循环状态、后验/先验或动作读出影响行为；已有冻结头/前半参数不能保证运行状态隔离。动作 1/4 步各新增 92 个未变化格错误，变化命中原本就是 0，不能称为学会动作变化后又遗忘。
- 比较动作保持损失、原 M2d 教师蒸馏或状态通路约束的适用性；提出一个候选，区分工程先验与学习结果。若用原模型蒸馏，只是在保留原行为，不自动证明获得新动力学。
- 写清训练用公共样本、起点、可变参数、教师/学生前向与 1/4 步展开次数、缓存身份、全部评测及资源预付。现有 264,480 / 1,670 不能直接套给增加模型调用的新损失。

C05 主责为 Codex，固定 [M2m-d](M2MD_ACTION_PRESERVATION.md)。直接蒸馏、不先增加四通路模型消融；原 M2d 重置学生/优化器，λ=1、温度1、新保持种子3307，历史训练另列。教师完整因果缓存＋原16行学生最多4边后缀采用208,546逻辑单位/1,610秒，不能套用另一份8边×4窗口建议的199,104/1,550。复用哈希闭合的旧M2l基线，保留全部候选评测与新增95%/90%保持门。原报告和失败保留；CPU层部分交付待补修，运行接入未实现，当前没有新真实运行登记。

## E13–E16：M2m-d 实现与有界验证

E13保留为部分reported；E13a经R1及 [R2边界补修](E13A_IDENTITY_BOUNDARY.md)、[独立109项CPU回验](artifacts/reports/E14a-R2-independent-review-20261012.md) 后accepted。原23/50项快照与失败保留，原作者归属不变。两个CPU源码/测试及fixture冻结，修改需重新领取；当前可领取E13b接入，不能把CPU验收当模型数值或完整基线/账本闭包通过。

E13b再领取 `src/ainerzero/runtime/memory_worker.py`、`src/ainerzero/cli.py` 与自己的新增接入测试文件；若隔离路径另需文件，先列确切范围。不另建通用训练平台；拟采用独立子命令 `train-action-preserved-memory`，尚不存在，完整256维incoming_h/逐调用mx.random.key转换和旧M2l闭包按固定协议。窗口摘要60e862…7b83、键绑定71deb…c1ca已登记；消费前重算，不把5a644…ad1旧键内容值用作cache的key_manifest_sha256。固定CPUverifier不接受registered覆盖，生产入口必须读取实际公开记录和中央账本，不能依赖可改状态标记。

- 实现独立 M2m-d 协议与预登记，旧 B/M2m-c 参数、原始前半梯度断言和入口原样保留；新增多步分支采用协议规定的梯度屏蔽与逐位冻结检查。
- 教师缓存绑定完整来源/数据/调度/随机键，学生逐行 B=1；原记忆 micro4 不变。不计算填充边，不让教师状态进入正式评测，不使用未来观察或开发数据训练。
- CPU 测试核对清单、时间顺序、掩码/归一化、分支随机键隔离、缓存失配拒绝、预算/保护失败留档与旧协议兼容；不能把未运行的 MLX 梯度/数值等价写成通过。需要真实模型的有限预检交 C06a 单独登记。
- 交实际实现和命令语法、源码/数据/缓存配置哈希、模型调用清单、测试/XML、未验证项。根目录结论仍由 Codex 整合；不提交、推送或训练。

E14a-R1/R2已完成CPU补修回验，接下来E14b审查接入及CPU失败路径；只领取自己的测试/核对脚本和报告。发现实现差异交原作者修复，不能自行改λ、窗口、种子、门槛或预算。C06a按已实现调用图另登记有限真实数值/资源检查，通过现有CLI共享锁和中央预算执行，不直接pytest；E14汇总通过后，C06冻结训练命令/来源/余额/资源。具体训练运行未交接前E15不执行。E15/E16 保留成功或中断的全部结果，固定末次候选，不自动追加更新或晋升。

## S01–S04：时空与多维关联准备

用户要求将4D与多维思考设计进入架构，见 [第6.4节](ARCHITECTURE_REVISION.md)。原作者grokbot-newbot交付S01/R1/S03，spacetime_identity_repair补修；两份S02/原报告/失败保留。Codex先接受277项核心契约，再接受S03固定公开fixture/引用归档及 [342项独立CPU回验](artifacts/reports/S03-R1-independent-recheck-20261012.md)，无失败/error/skip/xfail。保存规则见 [SPACETIME_STORAGE](SPACETIME_STORAGE.md)。外部审查不是盲测，含MLX全量未重跑，不宣称全工程绿色。**S01–S03不改变模型输入/分区/损失/参数**。

| ID | 任务与文件范围 | 依赖 / 状态 | 交付与验收 |
| --- | --- | --- | --- |
| S01 | 单一小模块 `core/spacetime.py`：时间索引、C0格引用、有类型证据引用及序列化 | accepted / Codex按R1/R2与S02-R1的CPU契约范围验收；原作者grokbot-newbot | 源码/引用消费工程通过；未接真实轨迹样例/数据库/模型，不代表3D/语义能力 |
| S02 | 两份 CPU 契约核对及测试 | reviewed / 内部 `/root/s02_spacetime_contract_audit`；外部 s02_spacetime_contract_audit；Codex 已审议 | [内部报告](artifacts/reports/S02-spacetime-contract-audit-20261012.md) 39项26过13失败；[外部报告](artifacts/reports/S02-s02_spacetime_contract_audit-20261012T104900+0300.md) 48项35过13xfail；保留两份 |
| S01-R1 | 消费入口重验、显式观察解析和修订链校验 | reviewed / grokbot-newbot；原报告保留，R2补闭包后整体验收 | [原作者交付](artifacts/reports/S01-R1-grokbot-newbot-20261012T125731+0300.md)；不将其全量“无模型调用”声明无条件采纳 |
| S01-R2 | 引用身份去重/自证与保留extra的对象重验 | accepted / spacetime_identity_repair实现；Codex按独立回验接受 | [R2报告](artifacts/reports/S01-R2-identity-revalidation-20261012.md)；源码df18bc02…a2727，自测36通过；原作者归属保留 |
| S02-R1 | 修复后的契约回验及旧契约回归 | accepted / c05_budget_reconciliation编辑S02/CPU回验，s01_repair_scope_review独立源码核对；Codex限范围验收 | [回验报告](artifacts/reports/S02-R1-cpu-revalidation-20261012.md)、[277项XML](artifacts/reports/S02-R1-post-R2-20261012.xml)、[源码关闭复核](artifacts/reports/S02-R1-source-R2-recheck-20261012.md)；相关xfail全移除，原失败保留，未跑MLX全量 |
| S03 | 最小公开C0引用样例与兼容说明 | accepted / grokbot-newbot交付；Codex按原13项及R1独立CPU回验接受 | [原报告](artifacts/reports/S03-grokbot-newbot-20261012T135448+0300.md)、[原审查](artifacts/reports/S03-review-20261012.md)；2030全量为作者声明无XML，本轮不重跑模型 |
| S03-R1 | 固定公开fixture与引用产物归档 | accepted / spacetime_identity_repair实现，s01_repair_scope_review独立回验，Codex限范围验收 | [实现报告](artifacts/reports/S03-R1-portable-fixtures-20261012.md)、[342项回验](artifacts/reports/S03-R1-independent-recheck-20261012.md)、[保存约定](SPACETIME_STORAGE.md)；fixture490577B，双快照已发布，原报告/数据保留 |
| S04 | 二维→3D→有限语义的评测草案，报告文件独立命名 | 架构设计；reported / grokbot-newbot（10:52领取，10:55交付；[协议草案](artifacts/reports/S04-evaluation-protocol-draft-grokbot-newbot-20261013.md)、[报告](artifacts/reports/S04-grokbot-newbot-20261013T105500+0300.md)；门槛待登记） | 完整世界拆分，遮挡/相似对象/未见路径/命名组合、复制/外推/仅当前/无关联对照；只做协议，不启动新环境培养 |
| S05 | S04记录结构提案写成代码：新建 `src/ainerzero/core/spacetime_records.py`＋`tests/test_spacetime_s05.py`，纯CPU，不接数据采集/模型/M2m-d，不改spacetime.py | 用户2026-10-13 11:51批准；S04草案；reported / grokbot-newbot（11:55；报告 artifacts/reports/S05-grokbot-newbot-20261013T115449+0300.md；CPU 221 passed；全量待C07结束后跑） | SpatialEstimate/EntityTrack/SemanticBinding/ImaginedBranch＋规范JSON/SHA/入口重验；按冻结规则重登记源码SHA并跑CPU与全量 |
| S06 | 搭二维 GridLab（CPU，只做环境和轨迹，不训练）：新建 `src/ainerzero/environments/gridlab2d.py`＋`src/ainerzero/data/gridlab_trajectory.py`＋`tests/test_gridlab_s06.py`＋极小样本 `artifacts/gridlab2d/`；不导入MLX、不接模型/M2m-d/C07/E系列、不取 m0-worker.lock | 用户2026-10-13 12:16批准；S04草案＋S05记录；reported / grokbot-newbot（12:22；报告 artifacts/reports/S06-grokbot-newbot-20261013T122003+0300.md；CPU 236 passed；spacetime_records.py 最小扩展 GridCellRef 待重登记；全量待跑；S07 已迁移窗口外为 out_of_view 并重生成样本） | 确定性种子世界、持久身份、遮挡、简单动力学、公开/私有分存、S05注记、世界级划分与泄漏检查；只跑S06＋spacetime CPU测试，全量记待跑 |
| S07 | GridLab-v1 完整规格：11×11、5×5 自我中心视野、80×80 RGB、门/开关、特殊事件（身份交换/同外观混淆）、S04 保留子集定义；新建 `src/ainerzero/environments/gridlab_v1.py`＋`src/ainerzero/data/gridlab_v1_trajectory.py`＋`tests/test_gridlab_s07.py`＋极小样本 `artifacts/gridlab2d/s07-sample/`；TrackState 新增 out_of_view（改 spacetime_records.py，向后兼容）并迁移 S06 注记；纯CPU，不训练、不接模型 | 用户2026-10-13 13:01批准（委托统筹决策）；S04/S05/S06；reported / grokbot-newbot（13:08；报告 artifacts/reports/S07-grokbot-newbot-20261013T130718+0300.md；CPU 251 passed；全量 pending：外部 MLX 忙；SHA 重登记归统筹） | S06＋S07＋spacetime CPU 测试；锁空闲则按规范取 m0-worker.lock 前台跑一次全量，否则记待跑；正式 SHA 重登记归统筹 |
| S07-R1 | S07 收尾：消除 development/final 公开内容重合、冻结划分清单＋校验器、文件身份跨分区重合检查；新输出 `artifacts/gridlab2d/s07-closeout/`，新建 `src/ainerzero/data/gridlab_v1_closeout.py`＋`tests/test_gridlab_s07_r1.py`；原 s07-sample 与 S07 报告不改不删 | 用户2026-10-13 16:16批准；S07；reported / grokbot-newbot（16:20；报告 artifacts/reports/S07-R1-grokbot-newbot-20261013T161840+0300.md；冻结清单 1f80c54a…；重合全0；CPU 257 passed；全量 pending：外部 MLX 6.4%；16:21 豁免运行被中断未完成、豁免已撤销；16:23 复检 472% 仍 pending；16:36 按用户豁免取锁跑全量 2406：2398 passed/8 failed（4×test_no_mlx 测试顺序依赖缺陷、4×smoke 内存守卫），见补记2） | S06＋S07＋spacetime CPU；全量按 E17/E19 规则一次性，否则 pending | 【统筹登记 2026-10-13：独立复核 approved（[报告](artifacts/reports/E24-mixed/review/MIXED-AND-GRIDLAB-independent-review-20261013.md)）；**冻结划分清单摘要 `1f80c54a…36d8` 由统筹正式登记，未经独立复核不得重登记**；`artifacts/gridlab2d/s07-closeout/` 为**唯一有效划分根**，`s07-sample/` 仅作历史样例（两者持同一批 8 个 episode_id 且 seed 25/27 分区相反——见发现 A-F4）；遗留 A-F1/A-F2（校验器不校验清单自述元数据；跨分区路径复用只由生成器门控）登记为后续收紧项】
| S07-R2 | ①四个 test_no_mlx 改为子进程隔离（改 `tests/test_spacetime_s05.py`、`tests/test_gridlab_s06.py`、`tests/test_gridlab_s07.py`、`tests/test_gridlab_s07_r1.py` 各自 test_no_mlx）；②撤回 S07-R1 的 25/27 互换：按世界/轨迹身份＋保留规则划分，单帧重合只报告；新建 `src/ainerzero/data/gridlab_v1_r2.py`＋`tests/test_gridlab_s07_r2.py`＋输出 `artifacts/gridlab2d/s07-r2/`；原 S07/S07-R1 产物与报告字节不变 | 用户2026-10-13 16:53批准；S07/S07-R1；accepted（限冻结样例与隔离修复；Einstein独立264项通过，校验器旧A-F1/A-F2未关闭）/ grokbot-newbot（17:00；报告 artifacts/reports/S07-R2-grokbot-newbot-20261013T165920+0300.md；清单 52eda9a5…；定向 CPU 264 passed；全量 2415 passed 无豁免） | 定向 CPU 回归＋划分校验；全量一次（原守卫、无豁免、共享锁）；待独立复核 |

S07-R2 清单身份登记（Codex，2026-10-13）：`artifacts/gridlab2d/s07-r2/split_manifest.json` SHA256 `52eda9a56722eabe1c80e797e969ab33cd371377597fa56a4f61f7450d6eb3b6` 为当前示例划分清单，按独立复核限范围验收；S07-R1 `1f80c54a5ff3c4089ae902b6862f540ace1513e976a7280917b8e491e46d36d8` 已撤回为活动划分，原产物与审查证据保留。原条目中的“唯一有效划分根”已被此登记替代。

S01–S03源码/测试/fixture和两正式快照已交付冻结，后续修改重新领取，原作者归属保留。重复/自证按(observation_id,cell)，内容/修订仍用规范摘要；未知world不构成same_cell_later，非法对象ValueError系拒绝。当前回到E13；S01–S03只证明记录/引用/保存工程有效，不代表模型已会4D或多维思考。S04训练与能力验收在后续阶段另行领取。

### S03 已交付范围与保存规则

- 已交付 `examples/c0_spacetime_refs.py`、S03/public-loader测试及 `tests/fixtures/c0_spacetime_v1/`；trajectory.py新增显式两文件公开加载profile，默认full/训练/replay要求不放宽。后续不重复建设，修改重新领取。
- 使用现有 `load_trajectory` 读取明确指定的既有公开C0 episode，保留manifest/public文件校验；不调用replay、reset、step，不打开private.json内容，不采集新数据。使用两个不同观察的同一格建立工程sidecar引用，显式resolve和as-of验证，不将研究员创建的关系称学生发现。
- 报告episode/数据分区/known world/观察ID、观察规范SHA与public.jsonl文件SHA（分开）、源码/命令/输出身份；新sidecar输出不覆盖旧数据/报告。拒绝失配/缺引用；world未知不伪造补齐。
- 验证原文件未变、无MLX导入、合法引用和缺失/篡改拒绝。只执行CPU工程测试；交真实样例和运行证据，标reported等待统筹，不自行accepted或提交/推送。

## 执行报告模板

```markdown
# <task_id> 执行报告
角色：executor；负责人：<agent>；时间：<客户端日期>
任务状态：reported；实验状态：未执行 / completed / failed
任务依据：<统筹任务、协议版本、具体授权范围>
输入身份：<源码/配置/数据/检查点/查询/映射哈希>
修改文件：<路径与目的，或无修改>
实际执行：<准确命令、实验 ID、run ID、运行角色>
验证结果：<测试数、失败/跳过、指标、回归、预算实际与预留>
产物：<原始报告、日志、XML、独立核对、候选路径>
失败与限制：<未执行、未验证、不一致、错误、保留预算>
交回统筹：<需要决定的问题；不擅自追加运行或换参数>
```

领取任务时只更新自己的行：负责人、状态、文件范围和交付位置。统筹审查后才标记 `accepted`。模型能力的成败独立于任务是否交付完成。
| E24 | M2n-M 混合批候选（12 行单边＋4 历史窗口） | 用户路线选择（不追加 M2n 次数） | **reported / Claude：run `e7151f2c…` completed，迁移保住（4,035/4,096）但动作门失败、历史未解决** | [结果报告](artifacts/reports/E24-mixed/MIXED-RESULT-20261013.md)、[方案＋登记](artifacts/reports/E24-mixed/MIXED-BATCH-SCHEME-20261013.md)、[复核](artifacts/reports/E24-mixed/review/)：200 次/202,304 单位/1,740 秒预付/287.4 秒；开发 4,035（D 4,007、M2n 2,218）、池 1,989、动作 ΔNLL +0.2339/+1.5381；**逐半遥测：4 行历史半占约 44% 梯度（256 目标 vs 96、KL 1.887 vs 0.825）→ 行权重≠梯度权重**；前两次环境超窗尝试留档 |


## AinerRelay 本轮任务补充（Codex，2026-10-13）

状态以接力台为准；本节登记范围与验收正文，不重复创建原任务。

| 接力任务 | 范围与验收 |
|---|---|
| M2.A4 | 按 artifacts/reports/relay-codex-20261013/A3-registration.md 与JSON；仅memory_worker.py、action_preservation_closure.py、mixed测试及新weight测试。不得改GridLab或preflight。纯CPU与四变异，实际condition SHA另交一级登记。 |
| M2.V1 | A4不同作者独立CPU复核；只新建E25-weighted/review证据。 |
| M2.B2/B3 | B2范围新增test_gridlab_s07_r1.py的拒绝断言，禁止含MLX全量重跑；B3只读独立审查身份权威、公开路径重算、重复约束与假MLX负对照，复核全量来源，不凭锁mtime下结论。 |
| M2.C2 | 只实现外部占用检测与CPU模拟；在C1释放文件后领取，范围run_when_quiet.py/preflight.py/test_preflight.py；未知占用fail-closed，不等同CPU闲=GPU闲，不运行watcher。 |
| M2.CV1/GV1 | 分别独立审C1/C2，只新增各自报告目录，不运行实际训练，不写账本。 |
| M2.A5 | 真实训练保持draft，最新用户授权未允许发布；预算沿用成功r2的202304/1740/1760/1780，不使用陈旧1540/1590/1640。 |
