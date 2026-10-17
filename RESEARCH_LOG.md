# AinerZero 统筹决策记录

该文件记录人类可读的研究决策与交接；SQLite 仍是实际运行和预算的中央账本，原始 JSON/日志/检查点保留。历史事实只追加勘误，不覆盖成新的实验结果。

## D20261012-01：角色分工与方案同步

- 用户指令：Codex 与 Claude 为统筹者，其他 agent 为执行层；执行层运行测试并交报告，统筹负责优化、纠正、改造、参数决策和训练规划。
- 主责：Codex；本次没有收到 Claude 的共同审议，不记录为双方已批准。
- 交付：[分工规范](COORDINATION.md)、[任务清单](AGENT_TASKS.md)、根目录 [AGENTS.md](AGENTS.md) / [CLAUDE.md](CLAUDE.md) 接入说明，以及 README、实现指南、首轮计划和架构文档的当前进度同步。
- 发现：README 已记录 M2l 和 M2m-a，但其余三份方案仍以 M2k 为最新。统一以已完成报告为依据；本次不重复这些模型运行。
- 初始读取快照：M2l 200 次尾部更新完成；M2m-a 零更新诊断完成；当时 58 个运行均终态。随后检测到外部阶段 B 实现与新运行，见 D20261012-03；不能继续使用“阶段 B 未实现”的旧状态。
- E00 已由 `execution_evidence_check` 只读交付并获 Codex 接受：完成报告 SHA256 `25997e1d12762d5748b15468da9f5c055fc1ac3d925c27d2a93ad01b85bfa8ab` 与核对文件一致；SQLite 确认 106,496 单位、410 秒预付、0 更新，58 个既有运行均终态；已有 XML 包含 1,794 条测试、0 失败/错误/跳过。本次核对没有重新训练或重跑测试，也未重新加载权重逐位验证。

## D20261012-02：收敛假说，准备一致换名对照

证据：[M2l 报告](artifacts/reports/m2l-diverse-memory.json)、[覆盖分析](artifacts/reports/m2l-coverage-analysis.json)、[M2m-a 完成报告](artifacts/reports/m2ma-slot-interference-r1.json)、[独立核对](artifacts/reports/m2ma-verification.json)。

- M2l 中，与训练池上一输入不重复的 505 条训练世界查询，零状态 86.36%；开发零状态仅 1.34%、历史 0%。训练分布内进步不等于跨世界泛化。
- M2m-a A2 中，位置未见替换格为 2/2,048（0.10%），其余格下降 0.36 个百分点；R1 成立，R2 不成立。支持研究符号身份/位置覆盖；单格跨槽干扰未证实。
- 开发世界同位置见过格也仅 17/608（2.80%）。单格覆盖不能完整解释整帧失败，多格组合、后验 z、门控等仍需区分。输入子空间外范数是描述性统计，不是错误因果证明。
- 纠正：NLL 接近均匀只说明平均目标损失接近均匀基准；不能推出没有信息、没有高置信错误或已知校准情况。拟合成功证明当前任务的局部表达能力，不能全面排除容量或结构瓶颈。
- 下一候选：保留 M2d 起点、M2l 池与顺序、200 次更新、原损失和尾部范围，只增加逐样本一致换名。执行层的外部交付已出现并启动运行，转为接收、审查与独立核对；本次 Codex 没有发起或重复候选训练。
- 结果分支：零状态迁移后再单独处理历史；换名池好而开发差则研究组合/z/门控；欠拟合先检查优化证据，不现场追加更新；动作/重建回归单独记录。维持正式筛查与独立晋升要求。
- 失败处理：M2m-a 的首次资源中断与获授权的第二次运行均保留；不把失败预留额度或模型工作量从累计记录中消去。

## 以后每次决策的最小记录

记录 ID、客户端日期、主责/参与统筹、当前事实与产物身份、待检验假说、唯一主要改动、固定参数/预算/门槛、执行者和任务 ID、实际结果及回归、未验证项、下一步或回滚原因。结论改变时引用新的证据；不同统筹有分歧时同时保留各自主张和最终选择。

## D20261012-03：外部阶段 B 执行交接

- 共享工作区出现 `relabel_memory.py`、运行器/CLI 修改、新测试和 [执行协议](M2M_CONSISTENT_RELABEL_FIT.md)，不是本次统筹写入的代码。具体执行模型/聊天与主责统筹身份不能由账本推断，暂记外部执行者待交接。
- 运行已登记为 `m2m-consistent-relabel-20261012`、run `056e38aa-597e-4c1c-9233-ea5449ef74d8`。本次不干预已启动参数，不派发重复模型任务。
- 独立执行 agent 核对现有 XML：1,856 项测试、0 失败/错误/跳过；本次没有重跑该测试。登记计划为 200 更新、264,480 单位、1,670 秒预付、截止 1,720 秒；CLI 监督 1,770 秒。
- 相对初稿增加冻结 M2l 的配对逐格基线 82,080 / 300 与换名池基线 4,096 / 30，共 86,176 单位 / 330 秒。训练参数没有因本次统筹改变。
- 原始注册规则及机器报告分支保留；其中“coverage_main”等文字标签不直接构成因果结论，统筹按 D20261012-02 的证据边界解释，不修改正在运行的判读实现。
- 下一交付：E06 核对完成或失败产物，C02 记录迁移、欠拟合与旧能力回归，再决定参数和结构改动。原先的报告真实性与来源检查仍有效，最终结果尚待交接。

## D20261012-04：接受阶段 B 的独立证据，固定单一参数候选

- 主责统筹：Codex；独立执行核对：`execution_evidence_check`。Claude 的审议尚未取得，不宣称联合批准。原实现/运行负责人仍待交接。
- 输入：[阶段 B 完成报告](artifacts/reports/m2m-consistent-relabel.json)，SHA256 `d835138daf1fffca6b833fa790e52dad1e098516dc3e5cdd3f09e3f9299f6b2c`；run `056e38aa-597e-4c1c-9233-ea5449ef74d8`。中央账本 completed/model、200 次更新、264,480 单位、1,670 秒预付，报告实测 333.027 秒；0 新环境步。
- E06 核对：纯 CPU 从 20 个公开轨迹重建 2,560 查询目标/分组，从逐格 argmax/NLL 复算全部 5 组零状态与历史指标；重放 seed 9103 换名池目标并复算汇总，均吻合。读取源/候选 safetensors：24 个模型张量、393,232 参数，282,128 冻结元素逐字节一致，只有 4 个 GRU 张量尾部 111,104 个元素改变；检查点文件哈希/长度、metadata 的 run/plan/200 步身份正确。
- 执行核对还重放了全部 3,200 个训练双射和 200 批调度，与预登记/更新日志逐项一致；augmentation RNG 的保存状态吻合，登记的 53 个源码/配置文件哈希一致。核对报告通过 agent 消息交回，本条归档；本次未写入外部 `m2m-verification.json`，不能将其列为已有产物。
- 证据边界：中间 200 次冻结检查依赖更新日志；本次没有重新生成模型概率，也没有验证跨进程下一次优化更新。接收核对交付不等于接受能力或晋升。

| 结果 | 精确计数 / 指标 | 解读 |
| --- | --- | --- |
| 局部训练噪声 / 新噪声 | 均 18/128；变化 3/29、4/29 | 两组筛查失败 |
| 开发零状态 | 409/4,096＝9.9853515625%；变化 4/127；NLL 4.93537 | 严格 <10%，不能四舍五入成部分迁移 |
| 换名池 | 196/2,048＝9.5703125%；变化 16/140；NLL 4.90918 | 严格 <10%；M2l 同池仅 46/2,048，但改善尚未达到门槛 |
| 开发历史 | 7/4,096；变化 0/127；NLL 7.09412 | 历史问题未解决 |
| 连续开发 | 0/3,104；变化 0/77 | 正式 memory_screen failed |
| 原动作/重建 | 动作准确率保持 98.18%/93.49%；重建 544/544 | 登记回归 false，不能推为全部能力无损 |
| 动作变化格 | 仍 0/7、0/25；NLL 8.8959/8.5063→9.2075/8.8159 | 子项变差必须披露，不倒改原回归门槛 |

- 原判读优先级得到 `underfit`：局部筛查失败先判定，不改成覆盖假说被否定。增加换名改变了学习难度，未过局部筛查不证明只缺更新次数，也不能直接定位结构不足。
- E07：200 条日志完整、损失/梯度有限；前 20 次损失均值 5.88339，后 20 次 4.96930，十段均值持续下降。裁剪前梯度 1.13472–1.46679，200/200 次超过 1.0；前半原始梯度均 0，冻结日志均 true。优化仍有进展，尚无充分扩模依据。
- 预算纠正：600 次若仅多 400 次、每次仍 2 秒预付，总额至少 2,470 秒，超过单次 1,800 秒。不能直接使用原预算开跑或降低保护线。
- **决定：M2m-c 只将学习率 0.001→0.003**，保留 M2d 起点、AdamW 重置、200 次、1.0 裁剪、393,232/111,104/282,128 参数范围、全部原池/调度/双射/随机条件/损失/门槛。比较固定末次与阶段 B 的相同查询。它检验当前预算内较大学习率能否改善拟合，不承诺成功。
- 交付：E06/E07 的只读核对与有限结论接受；C02 本轮优化方案已写入分工与根目录文档。E08 实现、E09 独立测试、C03 实际登记、E10 有界运行、E11 独立结果核对尚未执行。预算草案 264,480 / 1,670，任何额外模型调用必须重新核算。
- 失败后保持：不自动改下一学习率、不续接阶段 B 权重、不增加历史/课程/结构；先保留报告，再由统筹按证据决定下一轮。当前候选未晋升，本次没有新增模型运行。

## D20261012-05：纳入 4D 时空与语义等多维关联

- 用户要求：继续统筹，并把“记录 4D 空间/时间、语义等多维度思考”设计进入当前架构。
- 主责：Codex；执行层只读设计核对：`spacetime_semantic_design_review`。核对确认源码仍只有八格符号观察，现有身体/概念/来源规则需要补统一时空组织；没有执行模型或修改源码。
- 定义：4D＝三维空间 x/y/z＋时间 t。对象实例、语义、因果候选、目标和技能是有类型关联视图，共享证据，不与米/秒拼成一个任意向量。
- 设计：TimeIndex、SpatialEstimate、EntityTrack、SemanticBinding、RelationEvidence、ImaginedBranch；保存时间/坐标/单位/身体/编码版本、支持观察、修订、首次可用顺序、不确定性及作用域。二维像素不冒充三维，未知深度不补零；教师标签和仿真私有真值不混成学生发现；后来的修订不泄漏进过去查询；预测/反事实不进入真实观察视图。
- 分阶段：先 CPU 事件/离散 C0 格引用，保持原 v2 文件和学生输入；记忆/动作通过后研究二维对象持续性，再增加有标定 3D 或有限命名。有限语义不强制等待完整 3D。每轮能力分别验收记录、检索、预测与行动收益。
- 融合：[架构规范](ARCHITECTURE_REVISION.md) 升为 1.2，新增第 6.4 节并补身体/Bundle/执行顺序；[主指南](IMPLEMENTATION_GUIDE.md) 第 11、12、15、18 与进度表同步；[README](README.md)、[统筹规范](COORDINATION.md)、[执行任务](AGENT_TASKS.md) 加入 S01–S04。
- 边界：本次是架构与任务文档交付。S01–S04 尚未实现，ST0–ST3 尚未通过；不扩模、不新建大型数据库、不接入额外视觉模型。M2m-c 的唯一训练改动仍为学习率，不能捎带新增时空特征或损失。

## D20261012-06：文档验收与下一候选源码交接快照

- 执行层 `spacetime_semantic_design_review` 只读核对通过：11 份 Markdown 共 263 个链接，245 个本地路径均存在；排除代码块后无重复/空标题，`git diff --check` 通过。时空设计和当前/未来能力边界自洽，未运行训练或测试。
- 采纳两项勘误：S01 仍是计划，不能把“准备追加旁路索引”写成已经实现；共享 M2m-c 源码草稿已出现，改为待交付验收，不再称完全未实现。
- Codex 只读确认 `cli.py`、`memory_worker.py` 与新增 `tests/test_relabel_learning_rate_variant.py` 有外部学习率对照草稿；入口仅列 0.001/0.003，实际可运行性与新测试结果尚未接收。本次不修改或覆盖这些源码。
- 中央账本读取快照的最新运行仍为已完成阶段 B `056e38aa…`，没有 M2m-c 登记；尚无 m2mc 报告。E08 标为进行中/外部负责人待交接，E09/C03/E10/E11 待交付。不得把源代码或测试文件存在称为训练通过。
- 原报告与 E06 的来源哈希核对是当时快照；之后新增源码属于下一候选，不能倒写成旧运行采用的新实现。后续更新继续按实际交付追加记录。

## D20261012-07：接收 M2m-c，零状态迁移通过但动作回归阻止晋升

- 主责统筹：Codex；执行交付：Grok Bot（用户直接授权实现、登记并运行一次，见 [执行协议](M2MC_LEARNING_RATE_FIT.md)）；本次额外只读 CPU 核对：`m2mc_handoff_audit`。E08–E11 按用户交接标为 reported，不统一改为 accepted，也不宣称 Claude 联合批准。
- 输入：[完成报告](artifacts/reports/m2mc-lr0003-relabel.json)，SHA256 `47d1f1c8fca4ecf340b18fb7e431751ae37326c78e66075b8d7e2119fe7a3216`；[执行者复算](artifacts/reports/m2mc-verification.json)；实验 `m2mc-lr0003-relabel-20261012`，run `9169008d-348b-47b3-8519-8f87affcb60c`。本地 main 与 origin/main 跟踪引用为 `02f4e3255d433a148c79a9f217dddab2e4fe56d6`；用户报告已推送，本次未联网核验远端。
- 中央账本 completed/model、200 更新、0 新环境步、264,480 单位 / 1,670 秒预付；报告耗时 329.575 秒，账本墙钟 327.234 秒。预登记、中央 manifest 与报告计划一致，manifest `3bc5652ed1e1a4cc1005dcce10bf84ab839283d1c68da0d0fd7426f763a8c215`；相对 B 只有学习率及协议/说明字段差异，200 批次行与 3,200 双射摘要逐条相同。

| 测量 | 结果 | 判定 |
| --- | --- | --- |
| 开发零状态 | 3,923/4,096＝95.7764%；变化 115/127＝90.5512% | transferred |
| 固定换名池 | 1,999/2,048＝97.6074%；变化 133/140＝95% | transferred；与原训练边共享结构，不是新终局验收 |
| 全部配对零状态 | 19,789/20,480＝96.6260% | 所测范围改善 |
| 开发带历史 | 392/4,096＝9.5703%；变化 9/127 | 历史问题未解决 |
| 正式连续记忆 | 训练 530/12,416＝4.2687%；开发 157/3,104＝5.0580%、变化 2/77 | memory_screen failed |
| 一步动作 | 377→285/384；NLL 0.300653→1.549518，+1.248865 | 准确率与 NLL 两门失败 |
| 四步动作 | 359→266/384；NLL 0.919029→2.227566，+1.308537 | 准确率与 NLL 两门失败 |
| 当前重建 | 544/544 | 门通过 |

- 动作变化命中原来就是 0/7、0/25，之后仍为零；两个步长各新增 92 个未变化格错误。变化格 NLL 反而略好（8.895887→8.784253、8.506345→8.461890），不能写成所有动作子项变差或已学会动作变化又遗忘。
- 原注册 outcome `coverage_main_cause` 保留，但它是分类标签。证据支持一致换名＋0.003 在固定预算内实现本组零状态迁移，且 B 对优化设置敏感；覆盖/优化的相对作用与交互没有完全拆开。M2l→M2m-c 同时改变换名和学习率，缺少 0.003 无换名对照；不能证明覆盖是唯一/主要原因或 B 只是学得慢，本次不补跑归因实验。
- “位置未见”以原未换名 M2l 池为参照；增强训练已暴露字节，冻结词汇/codec 也已覆盖 256 字节。此次不是新词汇或语义理解。NLL≈2 是平均真值概率损失，未做置信度/校准分析，不能直接称置信度偏低。开发世界已反复用于研究诊断，正式晋升仍需新独立验收。
- 验证范围：本次 agent 核对报告哈希、预算、注册/检查点元数据与文件完整性、来源 manifest、有限更新日志、保存计数及 XML；没有重生成模型概率、重新读取张量复算冻结元素或验证跨进程下一次更新。执行者另写的复算脚本与另一 agent 的完整验收分开，最终冻结 282,128 参数不变来自已有执行核对记录。
- 测试：运行前 [1,870 条 XML](artifacts/reports/m2mc-tests-prerun.xml)，收尾 [1,884 条 XML](artifacts/reports/m2mc-tests-final.xml)，均 0 失败/错误/跳过；收尾增加的 14 条全部为未提交 S01 自测。verification 内 tests_passed=1870 属预运行记录，不是与收尾计数冲突。本次没有重跑测试。
- 决定：零状态迁移等级通过，回归 true、promoted false；保留候选，不替换原模型，不直接进 M2n。先做 E12 的 CPU 状态路径/成本审查，再由 C05 固定一个动作保持候选。已有冻结头/前半参数没有保护循环状态的行为影响；新增损失/蒸馏/展开必须重新核算预算，不能照搬 264,480 / 1,670。
- 共享文档由 Codex 更新：README、RESEARCH_LOG、AGENT_TASKS、COORDINATION、主指南、首轮计划、架构进度与 CLAUDE 入口同步。原预登记和原始结果不改；本次不训练、不修改 S01 源码、不提交或推送，本轮文档补丁尚在工作区。

## D20261012-08：S01 来源与待审查状态

- 用户明确确认 S01 的未提交代码由汇报执行者编写，不是 Codex；[S01 报告](artifacts/reports/S01-grokbot-newbot-20261012T085918+0300.md) 的负责人为 `grokbot-newbot`。Codex 负责架构与统筹文档，不领取实现者署名。
- 交付：`src/ainerzero/core/spacetime.py`，SHA256 `04fd59dbd3280cf57e6764fadc252721e0169c397fa841d07d103d3580e63f52`；`tests/test_spacetime_s01.py`，SHA256 `737b5f859519d7861b132792ee5ace02a94f46c1170ef1e8f4dee6021533e86e`；14 项自测已计入收尾 1,884 项。当前均未提交，保持不动。
- 状态：S01 reported，未 accepted；S02 独立契约检查和 S03 公共轨迹样例仍未完成。实现存在不等于已接通采集/SQLite/模型，也不代表 3D/语义能力。
- 待 S02 核对：观察规范 JSON 摘要与轨迹文件哈希的口径、未知世界/跨时钟比较、误差区间、合法 v2 来源/操作者分离、断证据及未来修订隔离。源报告中的任务领域称呼不构成 Codex 代码作者认定。
- 按用户要求，审查通过前不提交 S01。本次仅记录来源和状态，没有修改代码或运行测试。

## D20261012-09：派发下一批 CPU 执行任务

- 用户询问接下来子 agent 的任务。当前先并行 E12 动作保持路径/成本审查与 S02 时空契约独立审查，不启动新训练；C05 由统筹在 E12 后固定唯一候选。
- E12 新建 agent 在启动前因服务容量限制失败，没有工作产物或模型运行；改由已有 `m2mc_handoff_audit` 复用上下文接手。只读源码/报告，写自己的 E12 报告，不改变损失或参数。
- S02 由 `s02_spacetime_contract_audit` 领取，仅可新增独立测试/报告，不修改 grokbot-newbot 的 S01 实现或自测；保留真实失败，交回统筹决定修复，不自验收。
- S03 在 S02 审查及必要修复后再接真实公开 C0 引用样例；S04 评测草案仍可另行领取，不作为当前训练前置。
- 根目录任务表由 Codex 更新，执行者只写受领测试/报告。当前是 in_progress，无新完成结果、无新训练预算登记。

## D20261012-10：C05 固定 M2m-d 动作蒸馏保持，先工程实现

- 主责统筹：Codex；没有 Claude 联合批准记录。E12 内部/外部报告均已审议；CPU 预算复核：`c05_budget_reconciliation`。外部报告是建议，不单独构成运行授权。
- 输入：[内部 E12](artifacts/reports/E12-action-preservation-review-20261012.md)，SHA256 `e5d0c612cdf3825b1a4013f20ee86fa3a1f6bab8260041ca80ec062dc0f1f014`；[外部 E12](artifacts/reports/E12-m2mc_handoff_audit-20261012T1047+0300.md)，SHA256 `fa54109ea58e612c05cb31c1fc10ebbedaf6631c67b0be8a19a638e252b24c73`；[预算复核](artifacts/reports/C05-budget-reconciliation-20261012.md)，SHA256 `907894ad6e60f002bb09aa49d76a7b4000459a00bde1b11d5fd16762cd1071f8`。只读源码/JSON/清单核对，没有新模型测量。
- 机制判断：固定权重不隔离循环状态；尾部会进入GRU/prior/posterior/decoder，但共享符号的symbols由前半symbol_readout读出，decoder主要输出cursor/visibility。现有范数/改动量是路径证据，不等于四条通路的独立因果贡献；两个步长各新增92个未变化格错误，原变化命中仍为0，不能称为已学动作变化后遗忘。
- 决定：[M2m-d](M2MD_ACTION_PRESERVATION.md) 直接做一个M2d教师KL保持候选，不先增加四通路模型消融。从原M2d检查点 `f33974c9-b86f-4429-9ea9-8ea0e733142a` 重置学生/AdamW，不接M2m-c；原记忆200次、lr0.003、原池/调度/3,200双射、原micro4与393,232/111,104/282,128范围保持。
- 新保持项：λ=1、温度1，完整256类symbols的1/4步KL，未换名公开训练数据。教师完整因果历史只缓存一次；学生从所需教师incoming_h的stop-gradient副本出发，使用原16行查询的最多4条真实反馈后缀＋4步自由展开。正式评测用学生自身状态，禁止教师注入。独立种子3307，逐行B=1按原查询键配对；不消费原memory/augmentation RNG，不计算填充边。
- 梯度：各分支分别归一化后相加，整批仅一次mask/clip/AdamW；只裁剪允许尾部，冻结参数逐步/最终逐位不变。新多步协议允许有限的原始前半梯度，但应用于优化器的前半梯度仍≤1e-8；旧B/M2m-c原始前半断言原样保留。分支日志复用已计前向，不为范数暗增调用。
- 预算取舍：外部199,104/1,550与本轮208,546/1,610是不同窗口协议。选择可按原调度精确核算的后者：原候选工作178,304＋teacher2,254＋student27,988。固定四边填充会多812，本轮不采用。只读复用完整哈希闭合的旧M2l配对/换名基线，省去本轮86,176单位/330秒重测；原账本成本/原报告和候选所有新评测保留。
- 时间硬窗：1,610秒预付、1,660工作/1,710监督截止；200×3秒更新和60秒缓存尚未实测，不能保证完成。保护线、共享锁、中央RunStore及每日余额照旧，超窗/保护失败留档，不自动补跑或扩预算。
- 先定保持门：开发与固定换名池总体≥95%、变化≥90%；分别至少3892/4096、115/127及1946/2048、126/140。原M2d动作基线377/384与359/384，NLL增幅≤0.05/0.15；重建原gate且544/544。历史/连续筛查另报，不加入历史训练；保持门通过也不自动晋升。
- 执行顺序：E13工程实现/CPU测试→E14独立工程审查→C06具体CLI/run/来源/预算与资源登记→E15一次有界运行→E16独立核对。任务表新增依赖；当前C05仅设计完成，E13–E16未执行，未创建run/teacher cache、未校准/训练。

## D20261012-11：S02 缺陷接收与 S01-R1 修复职责固定

- 主责统筹：Codex；S01作者仍为grokbot-newbot。输入：[内部S02](artifacts/reports/S02-spacetime-contract-audit-20261012.md)，SHA256 `5c85b0dfdf896c21acb9210f81ee529b79d10536363ad5f04eaea32dfd0b2efd`；[外部S02](artifacts/reports/S02-s02_spacetime_contract_audit-20261012T104900+0300.md)，SHA256 `7a51453a4ea2b1888418806f395c84aefeacdc633fdda820abf8f32575009139`；[CPU修复范围复核](artifacts/reports/S01-repair-scope-review-20261012.md)，SHA256 `96d8e4ee87990d8a9da4482117ef7ab23cdb67975fcc806a6c1220edef6b79f8`。外部读取内部结论后写测试，不记为盲测独立。
- 事实：内部测试39项26过/13失败；外部48项35过/13 strict xfail。[外部全量XML](artifacts/reports/S02-s02_spacetime_contract_audit-20261012T104640+0300-full.xml) 经本次CPU解析为1971条，13failure、0error、13skipped节点对应报告xfail：**1945通过/13失败/13xfail**。本次未重跑测试，旧1884全过保持为先前快照，不能覆盖当前红状态。
- API决定：[S01-R1规范](S01_REPAIR_PLAN.md) 将公共消费入口重验Python对象定为必须，包括model_copy/model_construct与嵌套载荷。现有Contract的revalidate_instances=always保持，不改全局/v2。结构加载与事实解析分责，新增显式observation mapping resolver和修订集合校验，均留在单CPU模块；未知/缺失/摘要或作用域不符拒绝。
- 时间策略：比较包含partition；任一world=None保留记录但NOT_COMPARABLE；误差区间相交/接触不能认定先后或同刻；SENSOR_MONOTONIC步序/秒序方向冲突不可比较，WALL_UTC不假定单调。非法对象抛错，合法不可比返回状态。
- 关系/修订：拒绝自证/重复支持，same_cell_later必须同格严格后继；修订须前驱闭合、revision连续、作用域/kind/subject身份一致、断言不倒写，同前驱分叉拒绝。无效历史抛错，不静默隐藏；未来合法revision不能提前进入在线视图，不改变晚时点返回全部历史的原语义。
- 测试决定：保留两份S02文件/原失败报告；内部真失败不改xfail，外部已修复13项移除strict xfail。B7测试显式resolver而不是无映射过滤器；B8/B9改为期待拒绝异常。原S01正向时间fixture改已知world，内部结构loader正例改非自证；未知world/自证负例仍保留，不为通过删除测试。
- 文件归属：S01-R1由原作者领取spacetime.py与S01自测；S02-R1审查者分别领取两份S02测试，顺序交接、每文件一编辑负责人。先定向时空＋v2/旧契约回归，再必要全量收尾；真实模型检查另受CLI/预算约束，禁止以测试名绕过。S01仍reported/待修复，修复/独立回验通过后才接S03，本次不提交/推送。
- 本次操作为读取报告/源码、CPU解析XML、`shasum -a 256`身份核对、文档编辑和`git diff --check`；没有模型、测试或源码/数据更改。S01源码摘要仍 `04fd59dbd3280cf57e6764fadc252721e0169c397fa841d07d103d3580e63f52`，原自测仍 `737b5f859519d7861b132792ee5ace02a94f46c1170ef1e8f4dee6021533e86e`；仅增加两个修复/候选协议并同步根目录当前状态。
- 文档收尾：10份本次方案/共享文档的276个本地链接全部存在，`git diff --check`通过。预算执行者只读复核后采纳随机键tick、整批梯度合并/裁剪、日志不重做前向及修订分叉拒绝四项澄清；这属于文档验收，不是修复测试或新模型能力验收。
- `s01_repair_scope_review`另核对10份文档共294个Markdown链接/276个本地路径，依赖/作者/API/测试快照/未训练边界一致；采纳“可并行领取”及M2m-d正文补C06收尾依赖两项措辞澄清。

## D20261012-12：S01-R1 接收、三项契约决定与 S02-R1 回验

- 主责统筹：Codex；R1作者grokbot-newbot，保持reported。输入 [R1报告](artifacts/reports/S01-R1-grokbot-newbot-20261012T125731+0300.md)，SHA256 `9899ce0a860d4b062d3179300839fd41d0a33bd2aa324f6ce099ffec86162d62`；R1源码 `53a0c4ae24f9a36ca09111323039e98b6b89ec5be6bb198597cec449d1eb4572`、自测 `251e703d62e9f2b77d41d94db463d4391dc2420b00fb9d84b9a63c53d397a441` 与交付摘要一致。作者声明自测20通过、全量1963通过/13失败/1xfail，但无新XML，本次不把其声明当独立全量验收。
- 三项决定：接受world=None不能建立same_cell_later（未知世界不可比，不伪造world补齐）；重复支持及自证按(observation_id,cell)身份判断，digest保留作内容/序列化/修订身份核对；非法对象允许ValueError系异常，包括Pydantic ValidationError，不把合法NOT_COMPARABLE改为异常。
- CPU执行分工：c05_budget_reconciliation领取两份S02测试编辑/回验，s01_repair_scope_review只读源码复核。原两测试均保留；亲测 [R1旧测试快照](artifacts/reports/S02-R1-before-20261012.xml) 93通过/13失败/1xfail，确认10个XPASS、B8/B9拒绝和一个自证正fixture问题，不盲删标记。
- 按先前登记策略移除对应strict xfail，B8/B9期待拒绝异常、内部正fixture改两个不同引用，B7调用显式resolver并补正/负例。[R1对齐回验](artifacts/reports/S02-R1-aligned-20261012.xml) 246通过/0失败/0error/0skip/0xfail：三时空20+48+48与旧契约50/v2 59/迁移21；不改变源码或原S01自测，不声称全量绿色。
- [独立源码报告](artifacts/reports/S02-R1-source-review-20261012.md) 复现R2-01：同观察同格仅availability变化可重复支持/自证，stream_seq变1可把单观察伪作same_cell_later且resolver接受；R2-02：先model_dump会丢copied对象非法extra，消费者清洗后误接受。既定重验/身份规则须补这两处，不能提前宣布S01完整验收。
- 新普通负例不xfail，[pre-R2快照](artifacts/reports/S02-R1-pre-R2-20261012.xml) 261项247通过/14失败/0error/0skip/0xfail，包含3个身份绕过与11个顶层/嵌套extra失败；同观察不同格正例通过。保存R1源码身份后才通知补修者开始编辑，避免并发改源码污染基线。
- S01-R2派给spacetime_identity_repair，接手已reported后的spacetime.py/S01自测；原作者归属保持。仅按观察ID+格号去重/拒自证，并直接model_validate(instance)保留完整extra重验；不改全局Contract/v2/源数据/时钟策略/修订subject摘要/模型。S02-R1继续编辑自己的测试并独立回验，根目录文档由Codex整合，无提交/推送。
- 证据边界纠正：全量现有test_pilot_model.py等直接执行MLX CPU前向/反向/优化，不能以“CPU”认定无模型调用；原报告的全量“无MLX/无模型调用”不能无条件采纳。不推断原运行具体GPU、成本或全部路径。本轮只跑明确无MLX的契约范围，含真实模型的全量/数值收尾须另通过现有CLI锁/中央RunStore与预算，不能以测试文件名绕过。S03依赖CPU契约修复/独立回验，模型运行另等C06。

## D20261012-13：S01-R2 关闭、S02-R1 限范围验收与 S03 交接

- 主责统筹：Codex。S01/R1原作者grokbot-newbot；R2实现spacetime_identity_repair；独立S02测试执行c05_budget_reconciliation；独立源码关闭核对s01_repair_scope_review。互不交叉编辑、原报告/失败快照保留，不把已知缺陷的定向复验称盲测。
- [R2实现报告](artifacts/reports/S01-R2-identity-revalidation-20261012.md)，SHA256 `453c9b1e43b5b383521c7015f8dc3cc4f17fc00784e3a9879ccc921114fd8b31`；[S02-R1回验报告](artifacts/reports/S02-R1-cpu-revalidation-20261012.md)，SHA256 `15e64e9a0ab32a26c2fa606805457a9dfe3f99242c05a417b116c15956a244b1`；[源码关闭复核](artifacts/reports/S02-R1-source-R2-recheck-20261012.md)，SHA256 `55261e3556b00961b7526b51e9f7cb5a8abc222d5de1a7021c3879b58f90ea8e`。
- 最小代码改变仅两处：supports重复和subject自证按(observation_id,cell)，不因availability/stream_seq元数据变化制造证据；_revalidate直接cls.model_validate(value)，不先dump掉非法extra。ValueError系异常、unknown world不可比、完整修订subject digest、来源/时间/分区/显式映射责任保持。没有签名认证能力，仍不声称识别同时伪造的mapping与声明。
- 固定输入：spacetime.py `df18bc02e029f63751ed591c0f141ac3ef6c5abf91bb45b852661bbca7ea2727`；S01自测 `b9cceaeddc961a980a28143c8702314e7630e43405c3b70b8a398a793e025b27`；内部S02 `4f8d0245f7850d352abfeaa75815cc24c0f2344d942a42f56dc4869d427347df`；外部S02 `76b49670f79a9fee30aa782a40ab688de3933a02a4292589f17fd0f068fcf94d`。全局Contract仍 `84282b0c07bea481161dc4ad4b5e001776043c151933756f01427ac907eb657c`、v2仍 `d9890fcd0ecd6a47160fb075d4a662f295975773acacbe0aa32a7a4bf86eba2a`。
- 执行与验证：R2作者自测36通过，另一执行者六文件定向回验 [post-R2 XML](artifacts/reports/S02-R1-post-R2-20261012.xml)，SHA256 `ddb2ea8da36bdf79bf9141667a828717d39dce579b7ec582d2ab6ad2ebe9e34d`；**277通过、0failure/error/skipped/xfail，0.57秒**。主责再次CPU解析全部XML并核对实际classname计数36/48/63/50/59/21；新14项真实失败全转过，合法同观察不同格仍通过。原自测20项断言保持，新增16用例；两S02测试ruff通过，源码/自测ruff及git diff检查通过。没有重复跑已通过套件。
- 只读源码复核重新执行原身份/extra反例与constructed resolver拒绝、修订subject元数据改变拒绝、正常不同格正例，确认两残余关闭，未发现范围内阻断问题；这不是全工程/模型能力验收。
- 执行者最终回传发生使用额度中断；此前报告、日志/XML和哈希均已完整落盘，Codex实际读取确认后整合，不新建重复测试或覆盖原报告。失败通知不抹去已完成证据，也不冒充执行者新增运行。
- **验收决定：S01基础契约、S01-R2、S02-R1 accepted，仅上述CPU契约与消费入口范围；S01-R1原报告reviewed，其闭包由R2补齐。** 含MLX全量没有重跑；此前全量1963/13/1是作者原报告快照，不宣称当前全工程绿色。源码/两S02/自测冻结，后续重新领取；没有模型run、预算预留、环境动作、训练或提交/推送。
- S03依赖已满足，交原执行者grokbot-newbot领取最小公共C0引用样例：拟单examples脚本/对应CPU测试和本人报告，复用现有load_trajectory只读公开内容，明确观察ID/规范摘要与public文件摘要，resolve/as-of验证；不读private真值、不重放/执行动作、不训练或接数据库。S03仍todo，不把任务交接写成已实现。
- 根目录README/COORDINATION/AGENT_TASKS/S01修复规范/主指南/架构/首轮计划/CLAUDE入口已同步。E13仍待领取，M2m-d未实现/未登记/未训练；必要真实数值检查由C06明确CLI锁/中央预算与资源路径后执行，不以直接pytest绕过。
- 收尾检查：10份当前方案/共享文档的289个本地链接全部存在，git diff --check通过；当前入口未残留“待修复/未验收/1945全量当前”措辞。再次解析post-R2 XML仍277/0failure/error/skipped，摘要一致；仅核对已有产物，不重复运行测试。

## D20261012-14：S03 公共样例接收与 fixture/归档方案固定

- 主责统筹：Codex；S03作者grokbot-newbot，交付reported；独立CPU审查s01_repair_scope_review。输入 [S03原报告](artifacts/reports/S03-grokbot-newbot-20261012T135448+0300.md)，SHA256 `e402054e0562fe1ddb206c30f0a3bd883e10279370db7ab11d29dc114adb7e8a`；[独立报告](artifacts/reports/S03-review-20261012.md)，SHA256 `ec58126111b896a897a2feaf3f1c790d1c803785951408d0757b0bb5c8afad18`。
- 原交付脚本ce334f1b…e24a、自测31c2721c…cb29d与报告一致；只读development episode242b7060…的64步及train episode2d457a1e…的128步。研究员为格0前三个可见观察创建v0/v1，显式resolver/as-of：0步空、1步v0、2步及末步v0/v1；不是学生发现，不改变经历或模型。
- 独立执行S03定向CPU [13项XML](artifacts/reports/S03-review-20261012-tests.xml)，SHA256 `a7a912c5af53cc51a7372cdc103eb48f378aaef551caafb7ddf65dc84eb5077d`，13通过/0failure/error/skipped/xfail；两原样例经公开路径重算全文相等。公共/manifest摘要前后相同、private内容未读；目录存在性检查不等于完全不访问private路径。
- 作者所报2030项全量全部通过未保存XML，增量还包括他人测试变化，不全归因S03；本次未重跑含MLX全量、不当作独立工程/模型验收。原报告和两个sample保留：sample dev `a7fbd9fe45b23bac689baafa6e0a1aecb562d1462f1c1c9cb6a29e59e3d40e67`、train `2fb4a1a35ef31ec4a860cf866a92709cd7177efeb893b5c9136a450b4ef4287b`。
- 三项决定写入 [时空保存约定](SPACETIME_STORAGE.md)：固定tests/fixtures/c0_spacetime_v1中的公开镜像；正式产物artifacts/spacetime/{partition}/{episode_id}/{snapshot_digest}/，evidence_links.jsonl/summary.json/manifest.json；报告继续artifacts/reports，原sample不移动/覆盖。引用逻辑身份由规范内容/观察ID和修订谱系保证，不由目录名或词语决定。
- fixture逐字节保留两个原public.jsonl+manifest.json，共490577字节/479.1KiB，不复制/读private、不截短伪装原轨迹；来源世界/分区/大小/摘要及contract_test_only/not_for_training/non-generalization记录在fixture_manifest。缺必需fixture直接失败，测试不枚举本机artifact或整组skip；无MLX导入检查始终执行。
- 发现旧load_trajectory强制三文件目录，虽不读private内容也要求其存在。新增明确public-only两文件加载入口，复用原manifest/public/header/完整公开链校验；默认full/replay/training入口要求不放宽，不假/空private。本阶段无需与私有真值对照，它验证公开引用而非真实物理状态。
- S03-R1交执行者spacetime_identity_repair接手已reported后的example/S03测试，并领取trajectory.py、独立public-loader测试与fixture目录，原作者归属保留。先确认13项原基线留档再改两个文件。仅public-only/fixture/归档与非法cell边界，manifest最后发布，已有目标排他拒绝，未完成/损坏产物不消费；不引入DB/模型输入/新环境。
- 旧trajectory测试包含reset/step/replay/private读取，按本轮无新交互/私有内容范围不执行；以静态fixture的public/full边界和必要原完整episode公开只读加载校验，不把未执行套件写通过。新路径/真实归档及独立回验仍待交付，S03为reviewed，S03-R1 in_progress，无模型run/预算预留/训练/提交或推送。

## D20261012-15：S03-R1 可移植公开fixture与引用快照验收

- 主责统筹：Codex；S03原作者grokbot-newbot，R1执行者spacetime_identity_repair；独立审查/测试s01_repair_scope_review。先保存原13项基线再改example/S03测试，实现者交稳定源码后独立回验；原报告、源数据和两sample JSON不覆盖，作者归属保留。
- [实现报告](artifacts/reports/S03-R1-portable-fixtures-20261012.md)，最终SHA256 `3281631df3c16f8c8d71e306a64889435a8d838012430dfd144f66c2dcde115f`；[独立回验](artifacts/reports/S03-R1-independent-recheck-20261012.md)，SHA256 `6b2e73d4d9fdf6e0bdad92d414d1eb845d5a539cc853cb44fdd964065f75e7c8`。仅CPU文件/契约工程，没有模型run/环境动作/优化更新或模型预算预留。
- 固定 [fixture](tests/fixtures/c0_spacetime_v1/README.md)：development/242b7060…和train/2d457a1e…，原public.jsonl/manifest.json共490577字节逐字节相等；fixture_manifest登记source/run/world/episode/分区/大小/SHA，标记contract_test_only/not_for_training/not_generalization_evidence。没有private文件，不读/复制private内容；原manifest的private描述保留但不声称核验。固定路径缺失失败、无整体skip，不依赖本机artifacts数据；当前未提交，跨机器需携带。
- 新load_public_trajectory显式两文件profile，复用原manifest/header/hash/v2链校验，拒symlink/缺失/额外文件；原complete/training/replay默认仍要求三文件，不自动接受公共镜像。两个原完整episode公开加载与镜像加载结果完全相等，在private-open guard下成立。旧完整/训练/replay拒公共镜像的负例在目录检查处失败，未执行环境重放/动作或读private。
- example新增public-only与archive-root，cell必须非bool int且0..7；研究员创建的v0/v1引用和规范link摘要保持。正式目标按 [保存约定](SPACETIME_STORAGE.md) 为partition/episode/snapshot_digest，保存evidence_links.jsonl、summary.json、最后写的manifest.json。identity绑定source/protocol/producer三份源码SHA/格号/link SHA/加载profile；重复summary作用域/使用标记不一致发布前拒绝。
- 实际首次 [65项XML](artifacts/reports/S03-R1-portable-tests-20261012.xml)（S03 47/public-loader18）全过；另一执行者 [342项独立XML](artifacts/reports/S03-R1-independent-tests-20261012.xml)，SHA256 `7bb9a22f8931fc29c45851908ec4a5ebcf1a071595dc1604e76b4e1dd3781509`，342通过/0failure/error/skipped/xfail，1.58秒。实际8个文件数量47/18/36/48/63/50/59/21；根统筹只解析已有XML/大小/哈希，不再运行通过的套件。新增fixture缺失/不可见选择/跨作用域/归档碰撞/断写/摘要身份失配/穿越/symlink/CLI等边界通过；Ruff和git diff检查通过。
- 源码固定：example `42154b4deca97c776e73bfe70575219d20af1754f8bba243de5cc2786d1de7b8`；trajectory `7e2a38b96584d2214296eed20472b213d4e49388c73287bb105cb0b35f4b0837`；S03测试 `aa362c65290bfcf4e98928ce372d495fca9c708849de83378c9bec14b7bee797`；public-loader测试 `739873a3822d3c7bd3449af151f728cec28de5f229f9b5e1a247f7e1eba8c9ff`；fixture_manifest `d154f538aa9e3ae11075e976433220b33492296934f9171d290c9f0648619c94`。spacetime、Contract与v2仍为前次df18bc02/84282b0c/d9890fcd身份，模型/数据分区/损失/权重未改。
- 两正式快照经明确public-only fixture命令各生成一次：[development manifest](artifacts/spacetime/development/242b7060-4a2c-4ca9-aa46-e4bbc59f4786/5753d1680fc80038d1a56fb9675d7e1ab11cfef4bca3364cc330512eb49828e1/manifest.json)，SHA256 `739c4daaa78ced9960c7c4b944f315ff2d840c372ef34ca0c77f86f1274e60bf`；[train manifest](artifacts/spacetime/train/2d457a1e-c746-48ae-8adb-59b47929d69e/3ce7fd64d002b18229c7bbaebf4c282b05f9f7fdf8005b5467fe9f2f92d065be/manifest.json)，SHA256 `a1b55eccca96bd2473d0b68e6e7a4064814a74b68bad38e786ec9153254d7747`。两snapshot分别5753d168…28e1/3ce7fd64…65be，与目录/身份一致；根统筹核对两个数据文件大小/SHA，独立consumer读回等于当前run结果。
- 独立只读probe对既有正式目标再请求同身份archive均FileExistsError，全部正式文件hash前后不变；缺manifest/source身份篡改用内存模拟拒绝，实际tmp断写等由测试覆盖，不破坏正式产物。原公开4文件与镜像相等、源hash不变，原sample两SHA仍a7fbd9fe…0e67/2fb4a1a3…287b。
- **验收决定：S03/S03-R1 accepted，仅公开记录/固定fixture/引用保存及上述CPU范围。** 保存位置和命名已实际落实；reports留说明、旧sample保留，spacetime留正式数据产物，不写回原episode、不接DB/模型。未验证跨平台移动、真实断电恢复、恶意并发完全隔离、签名认证或大规模索引；公共完整性不是生产者真实性，也不是新泛化或4D/语义能力。
- 原作者2030全量为未留XML的执行快照，本轮不重跑含MLX全量或旧trajectory套件；只接受342项真实定向与公开数据probe，不将其写成全工程绿色。所有实现/测试/fixture/快照冻结，后续重新领取；没有训练、提交或推送。根目录保存规范/任务/README/统筹/架构/指南/首轮计划/CLAUDE/S01记录同步，时空准备收尾后回到E13动作保持实现，C05协议/预算不变。
- 文档收尾：12份当前方案/入口/fixture说明的322个本地链接全部存在，git diff --check通过；当前入口无S03待实现/待领取的旧状态。再次解析已有独立XML仍342/0failure/error/skipped，没有重复运行测试；保存规范已请求在Codex文件面板展示，工具返回queued，未称已打开。

## D20261012-16：E13部分交付接收、CPU补修与接入接口固定

- 主责统筹：Codex；E13a原作者grokbot-newbot；E14a独立执行审查s01_repair_scope_review。接收 [E13报告](artifacts/reports/E13-grokbot-newbot-20261012T151753+0300.md)，SHA256 `995dc0912f2944f17ca6e31ebab9bbd153bf5194290a992a0b11fbfe47df3edd`，保留部分reported，不把parent E13或CPU层标为accepted。worker/CLI/MLX未接入，当前不能训练。
- [E14a审查](artifacts/reports/E14a-action-preservation-protocol-review-20261012.md)，SHA256 `fbcd7bf5ee5006de9d5359c5d884b4102f61607b61a53c9431dac19374158eae`。实际命令 `.venv-ainerzero/bin/python -B -m pytest -q -p no:cacheprovider tests/test_action_preservation.py --junitxml=artifacts/reports/E14a-action-preservation-tests-20261012.xml`，stdout/stderr保存同名log；23通过，XML0failure/error/skipped，0.416秒。[XML](artifacts/reports/E14a-action-preservation-tests-20261012.xml) SHA `51def31239fd9d3f985d39abeba0cd0632bb76f95fae84d8d8f8a66b75a3e9c7`，log SHA `8eabe360a72bf88c528179ad899e20ab29f195536925b6f1cd491238936d1962`。根统筹只解析已有XML/哈希，不重复执行。
- 审查者临时纯NumPy反例确认F01返回gates别名可污染后续计划；F02改episode/world或调度顺序仍能得到同成本/键摘要；F03 incoming_h任意宽度及错误typed binding可通过；F04梯度广播、inf分母清空记忆项和空树可通过；F05 raw−masked范数不是应用front保护。正向清单teacher2254/student27988/retained178304=208546及原samples/schedule/逐调用键与KL归一化核对通过。没有改source/test或原报告；问题不等于已证明训练算法失败。
- **决定一：接受分阶段交付，先补修再接入。** [E13a-R1补修单](E13A_PROTOCOL_REPAIR.md) 固定F01–F05及普通失败测试，原作者可领取两个CPU文件；E14a-R1独立回验后验收E13a，继而E13b接入/E14b静态CPU审查/C06a有限数值与资源验证/E14汇总/C06训练登记/E15一次有界运行/E16核对。CPU文件可先实现完整；数值不可验证不意味着跳过CPU不变量，也不要求先直接跑未经登记的模型。
- **决定二：独立子命令，拟名train-action-preserved-memory，尚未实现。** 复用现有CLI锁、监督、中央RunStore和预算/资源守卫；旧train-relabel-memory默认lr0.001及B/M2m-c协议/raw-front断言不变，新监督用1710而非旧1770。不另建调度器。科学参数仍M2d重启、lr0.003、200次、λ/温度1、原256行/200×16/3200双射、尾部111104及冻结282128，预算208546/1610、工作1660/监督1710；探针不静默加进200次或生产缓存。
- 固定教师incoming_h为完整256维FP32、256池行cache shape(256,256)，逐行(1,256)，s帧observe之前；teacher_logits(256,2,8,256) FP32按horizon[1,4]，q-mask(256,8)bool。posterior读取完整incoming状态，不能只留128维尾部。数组物化stop-gradient；学生observe重新得到z，正式评测不注入teacher缓存。本机M2d metadata只读确认pilot_shared_symbol_v1/hidden_dim256，metadata文件SHA `34da5a4f07627ca3301c493b918d032718036c06cb7d5eb65577fa8514325d4c`；pilot_model源码SHA `6e7bc8def57fdf26297f00a0a4d38a740f1ef5308a5a6f1ce8e41b8554417f82`。
- 3307仅作调用命名空间：每调用CPU SeedSequence产生uint32→Python int→mx.random.key(seed_u32)。只读本机MLX0.32.2 METADATA、random.pyi及random.h核对key(int)/key(uint64_t)接口，不导入MLX。禁用全局seed/额外split/fold/手拼key；原生key内容/shape/dtype、潜变量噪声和MLX梯度等价仍待C06a真实验证。原键值清单SHA5a644900…ad1保留作CPU证据，身份schema补强另记版本/新摘要，不能悄悄换键值。
- **决定三：C05冻结M2l闭包清单为必须下限。** [固定协议](M2MD_ACTION_PRESERVATION.md) 补明确报告/检查点/权重、公开数据/池/调度、查询/seed/8粒子/分组、两套逐格缓存内容及CPU复算、中央原run/experiment终态、生产评测语义兼容身份；文件SHA/逻辑SHA/原始数组SHA分开，真实登记不靠自填UUID。新增无关文档或协议文件不要求整棵源码树与旧树一致，影响评测的源码变化须兼容性证据，否则停止。原M2l训练200次不是“冻结复用optimizer_steps=0”；不加载/推理M2l，旧argmax/NLL不能代替M2d完整logits。缺项失配停止，无补跑fallback，原历史成本保留。
- E13a源码 `f1af39cb560bae84f9032dfa804b4e1c4b8d58cd43237b723b9805dffeeb522a`、测试 `50bb71183f0ca710a083d88e2e355e015600929cdb25dfa54bc7b081fe087566` 未改；worker `1236103976ef9459037c58e25e7cdadbb67698f45e30f179d784db1ce037263e`、CLI `fbde423e8f8d9a9033a5dcb77f83e3c0399b68dfcf78a46369eae30f69fb753c` 未改。当前HEAD02f4e32，根统筹仅写方案/任务/入口和日志，保留所有原作者的未提交改动。
- E13作者2105全量未存XML。本机全量包含MLX CPU前向/反向/优化路径，不能无条件接受原报告“无MLX模型调用”；不推断其具体GPU成本。本轮独立执行只限上述23项纯CPU协议，不重跑含MLX全量，不称全工程绿色或新能力通过。新增模型单位/优化更新/环境动作=0，未登记或预留模型预算、未生产教师缓存、未校准/训练/提交/推送；真实内存峰值、耗时、旧动作/零状态保持及历史能力仍未验证。
- 文档收尾：根统筹核对10份文档326个本地链接存在、四份源码/测试SHA未改、git diff --check通过；独立审查者只读复核六份文档179个本地链接/依赖/接口/证据边界，指出的两处C06旧编号已统一为C06a。补修单展示请求返回queued，未称已打开。接口核对原拟委派spacetime_identity_repair因所选模型容量错误未执行，已由Codex直接只读核对，不虚称第二份独立接口报告；不重试模型工作或扩展训练任务。

## D20261012-17：R1独立回验、登记接口收口与v2固定比较值

- 主责统筹Codex接收 [原作者R1交付](artifacts/reports/E13a-R1-grokbot-newbot-20261012T160618+0300.md)，报告SHA `eed2c39d54b00fa116b42098be5689f57949759a2458de5b413d9f4bb1229c74`。源b6c39b76…2270、测试67eac13f…086e、fixture718a81b0…fbe9，原作者XML11724b3d…b34c/log06db019a…e27b；根统筹解析XML确为50/0failure/error/skipped，0.786秒。未将作者快照当独立验收。
- 先在任务表领取E14a-R1给e14a_r1_review，只读源码/公开数据并定向测试，交 [独立报告](artifacts/reports/E14a-R1-independent-review-20261012.md)，SHA `d5e6b5306f584961f3f63be5a18c28e792286ffcdd23d4615d6d45016ffbe6de`。[独立XML](artifacts/reports/E14a-R1-independent-tests-20261012.xml) SHA `dd49e083a1349a9c04db518d7fc442f23388c862e24336cd405be76ad0115675`，50/0failure/error/skipped/xfail，1.198秒；命令 `.venv-ainerzero/bin/python -B -m pytest -q -p no:cacheprovider tests/test_action_preservation.py --junitxml=artifacts/reports/E14a-R1-independent-tests-20261012.xml`，stdout/stderr独立log保留。根统筹未重复运行该套件。
- 独立只读probe核对fixture清单与原M2m-c逐字段相同、逻辑SHA和原report/dataset文件SHA一致。仅读取16个train episode的manifest/public，2,048条现有transition独立解析成public_records，256行观察/动作/规范内容身份全部匹配；未读development内容或private，Python open守卫private尝试0。35个输入文件前后SHA不变，没有环境reset/step/replay、MLX导入或模型工作；真实文件/账本/M2l完整闭包仍未全部验证。
- F01/F03/F04/F05主修及208,546成本计算有效，但F02还有三项明确反例：自填registered或改变默认可变REGISTERED_INPUT能接受假episode池；无public_records仍给source_verified=True，check_budget又转述；验证后改episode/展开动作步序/调度，预算通过且key绑定继续信任旧摘要。不能将50项通过写成全部五项已无缺口。附带finite raw极值平方和inf仅为CPU诊断边界，不是实际MLX或动作失败证据。
- **对用户三个问题的决定：** 当前不另登记含MLX全量；固定M2m-d生产verifier去registered覆盖并使用不可变内置权威；独立复算的v2窗口/键绑定作为E13b固定比较值登记，原keys内容值保留。用户直接指令优先于文档，本轮按所询问的收尾范围明确选择CPU定向和独立来源核对；必要数值/资源工作待E13b/E14b后C06a按实际调用/更新/角色/资源登记。现有直接全量pytest不是已经实现的受控验证入口，不借“测试”绕过锁或预付。
- 固定值登记在 [M2m-d最后一节](M2MD_ACTION_PRESERVATION.md#e13a-r1r2登记身份与摘要的固定解释)：windows schema m2md_windows_v2_source_bound/SHA60e86293…7b83，key binding schema m2md_keys_v2_bound/SHA71deb0f0…c1ca，per-call keys SHA仍5a644900…ad1，plan SHA仍cb1437ef…f489。teacher-cache的key_manifest_sha256用v2绑定值，不能换成旧keys内容SHA；先重算再对照固定值，cache自填expected不构成证明。科学protocol v1、实际窗口/调度/seed/成本和所有门均保持。
- 增加 [E13a-R2小范围补修](E13A_IDENTITY_BOUNDARY.md)：删除覆盖入口/固定不可变注册；用registered_manifest_verified和public_records_checked拆明CPU声明，去source_verified，预算仅数字；预算与键消费者重验当前窗口/调度摘要、schema、row/q/s/feedback/四步动作步序、qmax/units。通用计算器仍可做合成研究，但不可据可改布尔值冒充固定生产池。旧报告/失败和原作者归属保留。
- 在E14a-R1保存稳定报告并核对末尾SHA、释放只读审查之后，明确移交已reported的两个CPU文件给e13a_r2_identity_boundary并先登记领取；fixture/worker/CLI/旧协议/其他测试不改。R2实现、定向测试与独立回验另留报告/XML；最终是否验收E13a按实际回验决定，不先标accepted。根统筹处理路线/身份/任务/共享文档，不在本轮登记模型run或训练预算。

## D20261012-18：E13a-R2验收补记、Claude复核与E13b接入规格

- 补记：E13a-R2/E14a-R2的验收决定由Codex在17:26写入COORDINATION/AGENT_TASKS/M2MD/E13A_IDENTITY_BOUNDARY，但本日志没有对应条目；本条由Claude 18:20接手文档整合时补记，不改变Codex的决定内容。[R2实现报告](artifacts/reports/E13a-R2-identity-boundary-20261012.md) SHA `1d05bbd4e05dccf623f6f952e163f4f19c7492fd9ab3a0846c5f39e1616389d5`，作者XML `8d8703cf…a282` 109/0failure/error/skipped；[E14a-R2独立回验](artifacts/reports/E14a-R2-independent-review-20261012.md) SHA `c569eff06aa8abd1ad16f2b444759e13ff82eb1f4f5b11cad21183ce2cc1d6be`，独立XML `40d24213…a68a` 109全过，probe log `2b0a247b…6d`。源码 `0d897c68…75aa2`、测试 `29df7d57…1c53`、fixture `718a81b0…fbe9`；worker/CLI未改。**E13a CPU协议层accepted（Codex，限CPU范围）**。
- [Claude统筹复核](artifacts/reports/E13a-R2-claude-coordinator-review-20261012.md)（SHA `f4f4b4221ed507ab433d1f20f567d240887cc3323a5d15aba44f817a8206c4ce`）：自行重跑同一定向套件109通过，进程内未加载mlx；另有对抗Sequence探针（P2）被末尾内容重验拒绝。同意限范围验收，记为另一统筹者的独立意见，不写成双方联合批准。
- 复核发现两项**E13b必须条件**（不是E13a缺陷）：B1：通用窗口降级并替换16个episode后，预算仍为208,546、逐调用键内容不变、缓存binding能通过结构检查，且模块内没有v2键绑定 `71deb0f0…` 常量。因此生产入口必须要求登记窗口，并把窗口/键绑定/keys内容与固定值比对。B2：`public_records_checked` 可以伪造；字符串键或 `np.int64` 输入会失败关闭，所以生产路径要从真实episode构造int规范的记录，并在入口内亲自核对。
- **决定（Claude主责C05b）：固定 [E13b接入规格](E13B_INTEGRATION.md)。** 新建CPU `action_preservation_closure.py`（B1/B2生产门、M2l/M2m-c复用闭包、缓存expected binding、保持门判定）和 `action_preservation_mlx.py`（教师逐世界B=1缓存、单行KL保持损失、每次调用独立 `mx.random.key(seed_u32)`）。在 `memory_worker` 新增独立分支，在CLI新增 `train-action-preserved-memory`（无学习率参数，监督1,710秒）。已验收的 `action_preservation.py`、测试/fixture、`tail_update.py`、旧协议不改。
- 实现选择：实际应用的组合梯度直接由已验收的CPU `combine_branch_gradients` 生成（float64合并后转float32再裁剪/AdamW），应用前用 `check_applied_front_gradient` 守卫，不另写一份MLX组合，免去“MLX组合≡CPU参考”的容差登记。plan由 `relabel_memory_plan(0.003)` 派生：训练更新3秒，删去M2l重测330秒，新增教师缓存60秒和缓存核对10秒，按阶段次数复算为1,610秒；每次更新预留32＋该批学生单位（137–144，合计27,988）。
- 新增运行时停止条件：第1次更新时学生权重与教师相同，且每次调用共用同一键，B=1下教师与学生logits逐位相同，16行keep loss理论上恰为0。E13b把它实现为期望精确0.0的停止条件；保持梯度只记录范数，因log-softmax反向的fp32舍入可能有极小残差，不要求为0。该条件用来暴露键、tick、offset或窗口错位；C06a先实测。若非零，交回统筹，不能自行改为容差。科学参数、λ/温度、窗口、seed、预算与门均不改。
- 本条只写规格与文档；没有实现E13b代码，没有新run、教师缓存、MLX或训练，也没有提交或推送。文件范围的领取、实现、T1–T8/P1测试与报告交给执行者；之后依次是E14b独立审查和C06a有限数值/资源登记。

## D20261012-19：E13b交付核对与三项统筹决定

- 主责统筹Claude（C05b/C06a）。接收 [E13b报告](artifacts/reports/E13b-grokbot-newbot-20261012T215628+0300.md)（grokbot-newbot，21:45领取，21:56交付）。核对改后源码SHA与报告一致：closure `e26e58d2…a06c`、mlx `f002ce5f…bc5f`、memory_worker `d3c2a2e7…a255`、cli `c0a88f99…c2c1`、两测试 `01ed69c6…fb54`/`7b9969c5…3787`；E13a三文件仍为 `0d897c68…`/`29df7d57…`/`718a81b0…`。Claude重跑新增40＋原109项（149通过）和旧入口379项（全过），测试进程未加载MLX，控制库在测试前后字节相同。新分支与规格一致：闭包在建run之前完成，教师独立加载且用后删除，组合梯度用CPU函数生成，首更新keep loss不为0.0即停止，逐更新预留32加学生单位。MLX路径从未运行。**E13b记为reviewed，未accepted。**
- **决定一（P1/控制库）：** 字节变化的原因不是推测中的WAL或其他agent。`RunStore.get_run`/`get_experiment` 在 `BEGIN IMMEDIATE` 中执行 `_effective_now`，会upsert `metadata.clock_high_water`。用SQLite `immutable=1` 读取：高水位21:53:08，正是P1时刻；最新run、experiment和状态转换仍是09:02的M2m-c。接受闭包结论，但不得称“只读”，应写“业务记录未改、时钟高水位推进”。RunStore不改；独立审查若需零写入，在无运行时用immutable快照读取。
- **决定二（复用闭包）：** 接受 `episodes=` 参数，但函数内部须自查query manifest SHA。**不接受只复算methods**：两支各自的边际统计无法发现同一query内history/zero的重新配对（同标签两格交换history，边际不变而四类配对计数改变）。R1须逐query、逐世界、逐组复算paired全部字段及 `history_minus_zero_*`，并加入交换反例测试。
- **决定三（首更新不变量/C06a）：** 生产入口保持精确0.0停止条件。现入口只能跑完整200次（即E15），无法做有界验证，因此R1加入独立探针 `probe-action-preserved-memory`：CPU闭包、教师缓存2,254、缓存核对、第二次完整教师生产2,254并逐位比较、3次完整更新（32＋139/138/144），合计5,025单位/179秒，截止229/279秒；不做评测，不保存checkpoint，探针缓存因run_id不同而不能冒充生产缓存。看结果前固定判读：(a)重复教师逐位一致且16行全0 → 保持精确0；(b)重复一致但有非零 → 实现错位，修复后重跑，不加容差；(c)重复教师本身不一致 → 改用同16行KL(缓存‖重复)最大值作阈值，由统筹在C06前登记。第1次更新超出3秒窗口则按原守卫失败留档，生产计时由统筹重新登记。
- C06a主责由Codex转为Claude（探针设计与判读规则同属E13b规格；Codex可审议）。顺序：E13b-R1 → E14b一次审查E13b与R1 → C06a登记具体ID与中央预留后运行探针 → 视结果进入E14汇总/C06。本条只写决定与文档；没有新run、MLX、教师缓存、训练、提交或推送。

## D20261013-20：E13b-R1交付、E14b最终审查、C06a探针与首更新界修订

- **E13b-R1 交付**（grokbot-newbot，10-12 22:51）：closure `53049e3b…02aa`、memory_worker `f187eea3…e748`、cli `e8f7a131…26de`、closure测试 `e600dcf5…bd55`、新建 probe 测试 `332e7f89…f213`；59＋109＋379 项 CPU 全过；paired 全字段复算与 `query_manifest_sha256` 自查落地；`probe-action-preserved-memory` 实现但未运行。原 E13b 报告与失败证据保留。
- **E14b 最终审查**（独立审查者，10-12 22:18→10-13 09:08）[报告](artifacts/reports/E14b-integration-independent-review-20261013.md)：R1 五项身份一致；审查者用**自带算术**从 M2m-c 保存的 2,560 cells 独立重算逐 query/世界/组的方法与 paired 共 **87,822 字段，最大浮点差 0.0**；交换反例被拒（`per_query[0].paired.history_only_correct: 0 != 1`）；探针计划 5,025/179/229/279 复算一致、CLI 无科学参数、worker 互斥、运行器无 checkpoint 与评测调用、探针缓存被生产 binding 拒绝；账本/角色门 10 负例全部拒绝；控制库仅时钟高水位推进。**583 项 CPU 测试 0 失败**。pre-R1 版报告保留不覆盖。
- **C06a 探针执行**（Claude，10-13 09:13:44→09:14:08，[预登记](artifacts/reports/C06a-probe-registration-20261013.md)/[执行报告](artifacts/reports/C06a-probe-execution-20261013.md)）：运行前发现外部项目 MLX 作业占用本机，按“不并行启动 MLX、不停用户作业”等待 241 秒其自然结束。run `6ac8b328-e4a5-433e-8ba0-da6c0945ddac`，experiment `c06a-action-preserved-probe-20261013`，role model，completed；5,025 单位＝预留＝计划、3 次更新、账本预留 179 秒、实测 23.73 秒；教师缓存重复逐位一致；冻结 282,128 元素逐位；裁剪后冻结行恰 0；优化器树仅学生 GRU；峰值 30.2 MiB；首次更新 0.787 秒＜3 秒窗口；未存 checkpoint。**判读 (b)**：首更新 16 行 keep loss ∈[−7.74e-8, +1.21e-7]，非精确 0。
- **决定（用户批准）：登记首更新界 τ=1e-5。** 证据支持 fp32 舍入（logits 差 1 ULP、KL 正负各半、更新 2/3 升至 4.4e-5/2.5e-3），而非键/tick/offset/窗口错位；教师缓存与学生会话后缀是两份独立 MLX 图，逐位相等不可保证。生产停止条件改为 `check_first_update_keep_loss`（非有限即停、`max|loss| ≤ 1e-5` 通过），记录 max_abs/all_exact_zero/within_bound；教师重复逐位一致仍为探针硬条件；**能力门/科学参数/数据/预算/冻结保护全不变**。修订写入 [E13b规格附录](E13B_INTEGRATION.md)、代码 `action_preservation_closure.py` 与 `memory_worker.py`；修订后 585 项 CPU 测试 0 失败（38 审查＋59 R1＋109 E14a＋379 旧入口），ruff 通过。**修订属审查后变更，需在 C06/E15 登记中记录新源码身份，独立复审可由另一 agent 事后确认。**
- 下一步：C06 冻结训练命令/来源/余额/资源（含修订后源码 SHA）→ E15 一次有界 200 次更新训练与完整评测 → E16 独立核对。不自动晋升；E15 结果无论成败全部保留。

## D20261013-21：E15 训练结果、实现缺陷修复与首更新界落地

- **E15 首次尝试失败留档**（run `4d98cf08-0bc0-42d7-bffb-d7ffc14155f6`，09:49:51–09:55:42）：200/200 次更新、before/after、5 次局部检查与 paired 全部完成，止于 `after_relabel_pool` 的 `UnboundLocalError`。根因：`evaluate_zero_context_inputs`/`summarize_relabel_pool` 的导入写在 `if relabel_fit and not action_preservation_fit:` 内，而候选换名池评测在 `if relabel_fit:` 中执行（action 路径下名字未绑定）。已耗 1,560 秒预留不退还。**未换 ID 自动补跑**，先修复并新增 AST 守卫链回归测试；修复后 worker `939f230b…aca8`，CPU 回归 586 项 0 失败。报告 [首次失败](artifacts/reports/E15-first-attempt-failure-20261013.md)。
- **首更新界落地（用户批准）**：C06a 判读 (b) 后，生产停止条件由"16 行 keep loss 精确 0.0"改为 `check_first_update_keep_loss`（非有限即停、`max|loss| ≤ 1e-5`、记录 max_abs/all_exact_zero/within_bound）。理由：教师缓存重复逐位一致（KL 0.0），学生/教师 logits 仅差 1 ULP（7e-7–1.4e-6），KL 正负各半，属两份独立 MLX 图的 fp32 舍入；更新 2/3 损失升至 4.4e-5/2.5e-3 证明错位判据仍有效。**能力门、科学参数、数据、预算与冻结保护不变**；写入 [E13b 规格附录](E13B_INTEGRATION.md)。
- **E15 重跑成功**（用户授权，新 ID `m2md-action-preserved-20261013-r1`，run `d96b3c79-c033-4f8a-a05c-6e2391193abb`，09:57:48–10:04:12，382.5 秒，200 次更新，208,546 单位＝预留＝计划，MLX 峰值 30.3 MiB，200 次更新合计 27.4 秒/单次最大 0.680 秒）：零状态开发 **3,930/4,096＝95.95%**（变化 115/127）与固定换名池 **1,998/2,048＝97.56%**（变化 133/140）**通过**；一步/四步动作 **287/384、266/384**，ΔNLL **+1.1751/+1.4051**，四项动作回归失败；重建 544/544；`preservation_screen = failed`，开发历史 memory_screen failed。冻结 282,128 元素逐位、应用前部梯度 200/200 恰为 0、checkpoint 回读 200 步、源文件未变、M2l 复用闭包 87,822 字段差 0.0。**未晋升。** 结果 [报告](artifacts/reports/E15-m2md-training-20261013.md)。
- **判读**：λ=1 的 M2d 蒸馏保持项**没有阻止动作退化**。相对 M2m-c（285/384、266/384，ΔNLL 1.2489/1.3085）一步略好、四步略差，零状态与换名池持平；keep loss 由首更新 5.90e-9 升至末次 9.52e-3（峰值 1.41e-2），说明 200 次更新中学生持续偏离冻结教师。这是结果事实而非实现错误（全程冻结保护、单位账本一致、应用前部为 0）。
- **E16 第一遍只读核对**（同一 agent，非第二独立 agent）[报告](artifacts/reports/E16-readonly-verification-20261013.md)：12/12 通过——源码身份、账本（completed/model/200/208,546/1,610s）、从保存 checkpoint 独立复算的 282,128 冻结逐位、checkpoint 步数、仅 GRU 四张量变化、开发组 512 query 微平均重算、换名池用 `summarize_relabel_pool` 重建 batch 重算、屏幕输入与登记门一致、动作回归自洽、`updates.jsonl` 200 行且应用前部全 0。正式独立 E16 仍建议另派。
- **下一步（不自动执行）**：①诊断保持项为何不足（keep/memory 梯度范数、原始前部梯度增长与动作退化关系、λ 与 horizon 单因素对照）；②可提出非零历史 M2n，但 C05 明确不直接进入，需先决定与登记；③保留候选与全部失败证据，不追加更新、不改种子、不降保护线。本轮没有提交或推送。

## D20261013-22：保持项诊断、M2n 草案与含 MLX 全量测试

- **E17 保持项只读诊断**（纯 CPU）[报告](artifacts/reports/E17-diagnosis/keep-branch-diagnosis-20261013.md)：λ=1 的 KL 项只占合梯度 **中位 3.7%/均值 4.1%**（200 次）；应用更新的能量 **99.9% 在可训练尾部**，保持分支原始前部梯度升到 4.46e-2（峰值 8.39e-2）却被完全屏蔽；keep_loss 分块均值 2.33e-3→7.58e-3（末次 9.52e-3），memory_loss 5.78→2.24；h=4 保持损失是 h=1 的 **3.12 倍**；池覆盖不是问题（256/256 行、每行 12–13 次）；动作退化集中在**未变化格 100%→76.1%/74.1%**，变化格前后都是 0%（NLL 略降）；局部训练拟合 @200 仍 96.9%。结论：不是数值或控制流失败，而是**梯度量级、作用位置与目标覆盖**三重不足。顺带发现并修复日志键 `raw_front_gradient_l2` 被组合值覆盖（新增 `memory_raw_front_gradient_l2`，587 项 CPU 回归通过，worker `229beafac…`）。
- **E18 M2n 方案草案** [文件](M2N_NONZERO_HISTORY_PROPOSAL.md)：推荐先做 λ=10 单因素（成本不变 208,546 单位/1,610 秒）修动作门，再进非零历史；含起点/数据/门/预算/边界与"不直接进 M2n"。配套 [C07 登记草案与实现清单](artifacts/reports/C07-lambda-experiment-registration-draft.md)（未授权运行；λ 必须在 closure 显式传参，不得改 E13a 冻结层 plan SHA）。
- **E19 含 MLX 全量工程测试**（用户指令）[报告](artifacts/reports/E19-full-mlx-suite-20261013.md)：在共享锁内、仅当外部 MLX 空闲（`omlx-server` 24.29 GiB / 1.5–1.7% CPU）时运行。第 1 次 2286 passed / 4 failed——4 项均为"本进程未导入 MLX"断言在全量单进程下的固有冲突；按仓内既有子进程惯例修正后第 2 次 **2290 passed / 0 failed**（71.1 秒）。只改测试文件、未改产品代码；该自检不登记实验、不占训练预算，也不构成能力结论。
- 至此本轮"接手继续训练"的四项后续全部落地：诊断、M2n 方案、独立 E16（第二方核对进行中）、含 MLX 全量测试。下一步待用户/统筹在 C07（λ=10）与 M2n 之间选择并授权运行；不自动执行。

## D20261013-23：E16 第二方独立核对通过、四项发现处置与工作树冻结

- **E16 第二方独立核对完成**（subagent `e257091d`，全新上下文，只读、未 import mlx、未创建 run、未改实现）[报告](artifacts/reports/E16-independent-verification/E16-independent-report-20261013.md)：**verdict = passed，8 条主张 0 证伪**。独立重算要点：冻结 282,128 元素逐位不变（含三组负控制：改非 GRU→raise、改 GRU 冻结前部行→raise、改允许尾部→接受，并验证前后行掩码互补拼满 768 行）；开发零状态 4096/3930/变化 127/变化正确 115、动作 before 377/359 → after 287/266、ΔNLL +1.175109470217544/+1.405050474476635（从 `cells.m2m` 原始 argmax/nll 与从 dataset 重建的帧逐格复算，36 个有值字段浮点差 0.0）；换名池重建 batch 后 **63 字段零差**；`failed`、`promotion=false`、9 条晋升路径全 false；200 行日志、应用前部全 0；另从公开 dataset 独立重建整条生产闭包（windows `60e86293…`、keys `71deb0f0…`、内容 `5a644900…`、200 项单位表合计 27,988）与 before 块。边界：禁用 MLX，故 cells/teacher_logits/每步 loss 是受信输入，核对的是算术链与闭包身份，不构成能力验收。
- **F1（中—高，我的流程错误）**：核对进行中我于 10:46:34 修改了 `memory_worker.py`（`939f230b…`→`229beafa…`），使"活动工作树 == 登记 SHA"当场失效。处置：①按核对方建议正式登记该次改动为**仅遥测键名**修订、注明不影响已完成 run 的产物与判读；②采纳流程约束：**独立核对进行期间冻结工作树，任何改动必须先等核对结束**；③最终修订冻结为 `memory_worker.py` = `d795690e5809c7ec5bae5e58…`、closure `11ef181a…b71d0`、cli `e8f7a131…26de`、审查测试 `d4a18c24…`。
- **A1（低—中，已完整修复）**：`updates.jsonl` 的 `raw_front_gradient_l2` 被 `entry.update(**keep_details)` 覆盖为**组合**前部范数（200 行中 163 行与 `combined_front_gradient_l2` 逐位相等）。我此前的 `memory_raw_front_gradient_l2` 补键只是部分修复。现已把组合守卫值改名 `combined_raw_front_gradient_l2`/`combined_applied_front_gradient_l2`/`combined_front_applied_gradient_max`，`raw_front_gradient_l2` 恢复"记忆分支"原义。**勘误**：E15 报告"原始前部范数最大 0.084"与诊断报告的同一数字均为组合值（记忆分支单独值受 ≤1e-8 断言约束、该 run 日志已不可恢复）；门/冻结/权重/预算/结论均不受影响。CPU 回归 587 项通过，含 MLX 全量在最终修订上 **2290 passed / 0 failed**。
- **对核对方 Note A 的更正（记录在案，不改变其 verdict）**：M2m-d 路径**确实强制** `logical_model_transitions == plan["expected_total_model_units"]`——`memory_worker.py:1511-1512` 在 `if local_fit:` 内（action 路径经 relabel⇒diverse⇒local 恒为真），与 `reserved_units` 一并构成两重等式。Note A 中"主路径未强制"仅对非 local-fit 的旧 memory 路径成立。其余部分接受：`RunRecord.reserved_*` 直接读 `runs` 表的消耗列（`lifecycle.py:390/396`），账本没有独立的"单位预留"列；"208,546 三方相等"是报告事实＋该路径断言，不是独立测量；`active_seconds=1610.0` 是预付配额之和，实测墙钟 382.5 秒，二者不得混用（E15/E19 报告均已分列）。
- **工作树冻结**：此后任何源码改动都必须重新登记、重跑 CPU 与全量套件；下一步 C07（λ=10）与 M2n 均待用户授权后按 [C07 草案](artifacts/reports/C07-lambda-experiment-registration-draft.md) 与 [M2n 方案](M2N_NONZERO_HISTORY_PROPOSAL.md) 执行。

## D20261013-24：C07 首次独立复核 rejected、F1 修复与重审

- **C07 首次独立复核 verdict = rejected**（subagent `94065aef`，只读、未 import MLX、未创建 run）[报告](artifacts/reports/C07-review/C07-independent-review-20261013.md)。它自写 4 个脚本独立复算，确认：五份文件 SHA 与声称一致且复核前后不变；**单一因素成立**（顶层差异键恰为 protocol/keep_lambda/single_factor/action_preservation_condition，其余 208546/1610/1660/1710/lr0.003/200×16×4/seeds/gates 深比较全等）；冻结基准 `cb1437ef…f489` 未污染（基准 λ 仍 1.0，条件 λ=10，`condition_sha256` 自算 `9b9cabfc…fd62` 与文档一致）；λ=1 组合器**逐位**等于冻结层（25 seed×3 dtype×5 target，含 −0.0/次正规/1e308）；λ=10 逐位等于 `memory/targets + 10×mean(16 行)`；24 个非法 λ 全拒；入口无任何可传 λ 的路径（全 src AST 扫描）；5 个旧计划摘要与窗口/键绑定逐字节未变。6 组自选对抗检查另有 5 组通过。
- **F1（阻断/HIGH，已修）**：`memory_worker.py:1382` 的 `entry.update(memory_loss=total, keep_lambda=plan["keep_lambda"], **keep_details)` 与 `_keep_update` details 里新增的同名 `keep_lambda` 键冲突 → CPython 必抛 `TypeError: dict.update() got multiple values for keyword argument 'keep_lambda'`。触发点在 `action_preservation_fit` 分支内、`optimizer.update` 之后，**λ=1 与 λ=10 都走**：若直接运行 C07，会是"教师缓存 2,254 单位/60 秒已花＋1 步 AdamW 已落地→run failed、无 checkpoint"。**2049 个 CPU 测试全过也抓不到**（该语句只在真实 MLX 循环执行），而当时的 C07 测试反而把缺陷断言固化——这是本轮第二次由独立复核抓出"CPU 全绿但真实路径必错"的缺陷（第一次是 E15 的 `UnboundLocalError`）。
- **我的处置**：①删除显式关键字（`keep_lambda` 仍由 `**keep_details` 记录，两条件都保留遥测）；②改写被固化的断言；③新增回归测试 `test_log_update_cannot_duplicate_a_keep_details_keyword`（AST 提取 details 键集合，断言 `entry.update` 显式关键字与 `**` 映射键集合**不相交**，并用含 `keep_lambda` 的 mapping 实测该写法安全）——把这类"字典关键字冲突"变成可静态检出的回归；④重跑 CPU：230＋379＝**609 通过**、ruff 通过；⑤更新登记身份（worker `2b8c9b1e…`、C07 测试 `6b490166…`，closure/cli/冻结层未动）；⑥按复核者放行条件**再派同一复核者复验**，通过后才执行 C07。
- 其余 F2–F6（v2 无默认 λ 更严格、np 标量 λ 被拒、探针 `**details` 同类风险、M2m-d 报告 `action_preservation_condition` 为 None、账本无 C07 记录）均为 INFO/低，逐条在报告中保留。

## D20261013-25：C07 复核 approved、执行被电源守卫拦下并排队等 AC

- **C07 复验 verdict = approved**（subagent `94065aef` 第二次复核）[报告 §8](artifacts/reports/C07-review/C07-independent-review-20261013.md)。F1 关闭有四层独立证据：① 复核者自写审计器（不依赖项目测试）解析 `_keep_update` details 的 13 个键、解析 `run_memory` 全部 `entry.update`，并把 `**keep_details` 沿闭包 `return tree, details` 做数据流对齐 → 显式关键字 ∩ 供给键 = ∅、`keep_lambda` 仍由 details 提供；② 控制流确认该语句外层守卫链恰为 `['action_preservation_fit']`，λ=1 与 λ=10 必经；③ 把源码真实语句编译执行，两个计划各跑一次均无异常、日志分别记 λ=1.0/10.0、16 字段可 `allow_nan=False` 序列化；④ **4 组变异验证**（加回显式关键字、删 details 的 keep_lambda、换另一冲突键、`**extra_details`）——前三组项目测试与新测试都 FAIL，第四组项目测试放过 → 记为 **N1（LOW，不阻断）**：新测试不校验闭包是否真的返回 details、也不拒绝不可解析的 `**` 操作数；建议后续把"`**` 操作数必须是 keep_details"或数据流解析补进断言。复核同时确认修复未引入新问题：全部计划摘要与修复前**逐字节相同**（M2m-d `48885d95…0fa7`、C07 `ea4a9197…d36a`、条件 `9b9cabfc…fd62`）、CPU 动作系列 230 passed、CPU-only 全量 2050 passed、ruff 全过、账本无新记录。**执行前提（程序性）**：工作树冻结在 worker `2b8c9b1e…` / 测试 `6b490166…`，再变动则复验作废。
- **C07 首次执行被电源守卫拦下**（11:27:10–11:27:15，4.8 秒）：`RuntimeError: memory experiment requires AC power`，当时本机为 **Battery Power**。**未创建 run、未消耗预算**（账本 63 runs/28 experiments、当日 3,349 秒不变），只留一份失败 `report.json`。按"不降保护线、不绕过、不换 ID 自动补跑"处置：不重试、不改配置，改为登记排队——**等 AC 电源恢复且外部 MLX 空闲后自动执行同一条登记命令**（`artifacts/reports/C07/run_when_ac.py`，最长 4 小时，仍取共享 `m0-worker.lock` 并走全部守卫；失败/超时全部留档）。
- 本轮第三次由保护/复核拦下问题（前两次：E15 的 `UnboundLocalError`、C07 的 F1 重复关键字），均未造成训练结论污染；C07 仍未执行，E15 的 M2m-d 结果与"动作门失败、未晋升"的结论不变。

## D20261013-26：C07（λ=10）负结果——提高保持权重反而更差，机制是目标/覆盖失配

- **C07 执行完成**（run `db8c9a7c-8e01-42f4-b3a3-1f257e0c05d8`，2026-10-13 11:50:57–11:57:34，394.2 秒，200 次更新，208,546 单位 = 预留 = 计划，role model completed，MLX 峰值与冻结保护全部达标，应用前部梯度 200/200 恰为 0，冻结 282,128 逐位；日志按 A1 修复后的 `combined_*` 键分列并记录 `keep_lambda=10.0`）。执行前两次被拦下均无损留档：AC 电源守卫（4.8 秒，未建 run）、我的排队脚本自持锁导致 CLI 取不到同一把锁（0.2 秒，未建 run）；两次都未消耗账本额度。
- **结果：动作门仍失败，且比 λ=1 更差**。同查询对照（λ=1 → λ=10）：开发零状态 3,930→**3,904**（门 3,892 仍过）、变化 115→**117**；换名池 1,998→**1,972**（门 1,946 仍过）、变化 133→**131**；一步动作 287→**273**（门 377）、ΔNLL +1.1751→**+1.6052**（门 0.05）；四步动作 266→**266**（门 359）、ΔNLL +1.4051→**+1.8205**（门 0.15）；重建 544→**544**。`preservation_screen=failed`、未晋升；动作退化仍集中在未变化格（一步 1.0000→0.7241，λ=1 为 0.7613）。
- **机制证据（关键）**：λ=10 让学生**更贴近教师**（keep loss 末次 9.52e-3→**7.92e-3**、峰值 1.41e-2→1.03e-2）、**离 M2d 更近**（尾部相对 M2d 位移 Wx 18.57→17.76、Wh 16.25→14.95、b 5.76→5.46、bhn 0.65→0.62），但**动作更差**；keep/memory 梯度比中位反而由 0.037 降到 0.027，组合梯度前部范数由 4.46e-2 升到 **3.51e-1（×7.9）后被完全屏蔽**。→ **不是"λ 太小"**：加大权重把更多梯度压到冻结前部与与记忆目标冲突的尾部方向，既未改善评测分布上的动作行为，还轻微压低了零状态/换名池迁移。E17 的假设（份额不足）被本次单因素实验**证伪**。
- **判读与下一步**：原登记规则写"动作门仍失败→改用方案 B（提高保持行数）"，但本次证据对 B 不利（同一目标的更强/更多版本）。修正建议：**D（推荐）**把教师信号并入记忆分支目标、让动作相关行参与记忆批；**E** 重新审视"只训尾部/冻结前部"（保持信号大量落在被屏蔽方向）；**B** 仍可做但预期收益低；**F** 停止 λ 线、带动作退化披露推进 M2n。**不建议**继续微调 λ（1→3/30），单因素对照已显示反向且非单调。C07 报告、原始对照数据与全部失败留档保留。

## D20261013-27：D 条件实现被独立复核 rejected（F1–F3），修复后待复验

- **D（批内教师蒸馏）实现**：新增 `apc.d_condition_plan()`（协议 `m2m_d1_inbatch_teacher_distillation_v1`，条件 SHA `5aab99e5…`；冻结基准 `cb1437ef…` 原样保留、基准 λ 仍 1.0）、MLX 层 `memory_distill_sequence_loss`（师生同批同键、教师 logits 停梯度、mask/分母与记忆 CE 同规则、KL 作用在换名空间）、worker D 计划与分支、CLI `train-action-preserved-distill-memory`（无科学参数，超时 min(1,640, max_wall)）。成本 **184,704 单位 / 1,540 秒 / 截止 1,590·1,640**（每次更新 64 单位＝学生 32＋在线教师 32）；取消独立 16 行保持项与其教师缓存。**T8 静态键规则按语义精确放宽**：允许把调用方的登记键转发给师生（创建键仍只能经 `_key`→`mx.random.key`，模块内仍不得出现 split/seed/fold）。
- **独立复核 verdict = rejected**（subagent `ced439db`，只读、未 import MLX、未建 run）[报告](artifacts/reports/E20-d/review/D-independent-review-20261013.md)。三个运行期致命缺陷同根同源（复用 `action_preservation_fit` 门控时漏排除）：**F1(BLOCKER)** D 分支 `stage("teacher_cache")` 而 D 计划无该键 → KeyError；**F2(HIGH)** `cache_path/cache_file` 未绑定却被收尾校验读取 → UnboundLocalError（在 200 次更新+评测之后）；**F3(HIGH)** 每更新记账漏排除 keep 学生单位 → 预留 12,800 实记 40,788。**F4(MEDIUM)** 新测试全为 AST/文本断言、无执行路径覆盖：复核者实跑 115 项 CPU 全绿而 D 一个单位都跑不了。科学设计本身被判干净：未过滤逐键 diff 仅 12 个簿记键（数据/种子 2203·2307·9103/batch16·micro4/lr0.003/200 次/窗口/门/保护线/冻结范围全同）、λ=1.0、`cb1437ef…f489` 未污染、师生同批同键、mask/分母同规则、T8 放宽紧致（5 个造键/偷种子变异体全被拒）。
- **修复（未改 1,540 秒与 184,704 单位）**：①D 分支不再开任何未预留 stage（教师加载留在已开的 `initialization` 窗口内，另记 `teacher_load_seconds`；keep 分支保留自己的 `teacher_cache` 窗口——注意两次同前缀补丁曾误改 keep 分支，已按唯一标记重做并核对）；②缓存身份校验加 `not distill` 守卫；③记账行加同一排除；④新增 3 项**接线回归**：`stage` 常量必须 ⊆ 计划预算键、D 分支不得触碰 `cache_path/cache_file/cache_arrays/cache_manifest`、预留与记账两处都必须带 distill 排除，并断言 run_memory 中每个 stage 常量都被某个登记条件计划覆盖。修复后 worker `89147751530c765ce9547171…`、D 测试 `cc0972bf…`；CPU **242＋379＝621 通过**、ruff 通过；复核者脚本在本树复跑：`unbound_local_reads_under_d=[]`、T8 shipped_module 通过且 5 个变异体全拒、λ token 仅出现在新函数。
- **这是本轮第四次"CPU 全绿但真实路径必错"由独立复核拦下**（前三次：E15 `UnboundLocalError`、C07 重复关键字、E16 期源码改动流程问题）。处置原则不变：先修、加可静态检出的回归、再复验；未复验通过前不执行运行。

## D20261013-28：D 首次执行失败（同类缺陷第四处 m2l_cells）、通用审计与首更新 KL=0 实证

- **D 首次执行失败**（run `2a6ba430-71c8-4486-9054-9e2d4ce93447`，12:39:24–12:46:31，424.8 秒，state failed）：`UnboundLocalError: m2l_cells`。这是"只在 keep 分支绑定、却在 D 路径读取"的**第四处**（前三次 F1 stage/F2 cache_path/F3 记账已修）。复核者的可达性审计只扫 `cache_*` 名字集、我的接线测试也只盯这几个名字，因此漏掉。
- **但本次失败给出了两个关键实证**：① `distill_first_update = {count: 4, max_abs: 0.0, all_exact_zero: true, within_registered_bound: true}` —— 首更新 4 个 micro-batch 的 KL **恰为 0.0**，在真实 MLX 上证实"师生同批同键⇒同一计算"的 D 设计（旧保持项从未达到 0，而是 ±1e-7）；② `teacher_load_seconds = 1.7 ms`，F8 关注的 15 秒 initialization 窗口实测余量巨大。200/200 更新完成，账本 200 步/184,704 单位/1,490 秒预付。
- **修复改为系统性**：D 路径补 `m2l_cells`；接线回归升级为**通用未绑定名审计**（D 旗标集下可达的所有名字读取，凡在 run_memory 内被赋值但 D 路径无任何可达绑定点即失败，排除导入/参数/内建）。变异验证：基线 `[]`；M6b（删 D 路径 `m2l_cells`＝真实故障）→ `['m2l_cells']`；M5 → 未预留 stage；M4b → 未绑定缓存读。修复后 worker `01ba1b7f…`、D 测试 `9d3482dd…`，CPU 622 项通过。
- 按登记规则不自动换 ID 补跑；待用户授权后以新 ID 重跑。

## D20261013-29：D 第二次尝试因环境争用超窗失败（我的策略违规），改为等静默窗口

- **D 第二次执行失败**（run `6b41f461-5307-4789-89ea-d922d003c04b`，430.8 秒，state failed）：`exceeded prepaid stage window`，`current_stage = after_memory_train`（90 秒窗口），`after` 评测无结果；200/200 次更新完成（合计 26.8 秒、单次最大 1.60 秒）。修复后的代码行为正确：首更新 KL 仍恰为 0.0（4 个 micro-batch）、`teacher_load_seconds = 5.3 ms`、无一次更新超 3 秒窗口。
- **根因是环境争用**：运行前预检实测外部 MLX **19.3% CPU**、load average 24–36，而我仍开跑——**违反自定策略（外部 MLX ≤5% CPU）**，这是我的执行错误，已记录。保护 fail-closed，无错账：账本 200 步/75,504 单位/1,010 秒预付，当日 7,459 秒。
- **处置**：不降窗口、不改预算、不绕守卫；排队等待"AC＋外部 MLX ≤5% CPU＋load ≤4＋锁空闲"连续 3 次采样，然后用新 ID `m2md-distill-20261013-r2` 重跑（后台作业，最长 6 小时；运行器只探测锁、不持锁，避免此前"自持锁导致 CLI 取不到锁"的错误）。
- 两次失败均留档，D 的结论仍未产生；M2m-d/C07 的既有结论不受影响。

## D20261013-30：D 的机制假设获得强证据（失败运行的评测数据九门全过）

- **关键事实**：D 第 1 次尝试（run `2a6ba430…`，失败于其后的 `m2l_cells` 组装）**已经完成了全部 before/after 评测与 paired、换名池 m2m**。其指标显示 **九项登记门全部通过**：开发零状态 **4,007/4,096**（变化 124/127）、换名池 **2,016/2,048**（变化 138/140）、一步动作 **377/384（ΔNLL −0.0090）**、四步 **359/384（ΔNLL −0.0773）**、重建 544/544。对照：M2m-d λ=1 为 3,930/1,998/287(+1.1751)/266(+1.4051)，C07 λ=10 为 3,904/1,972/273(+1.6052)/266(+1.8205)。
- **判读**：C07 暴露的"符号空间冲突"根因假设**成立**——把教师 KL 折进**同一批、同一次前向、同一套换名符号**后，动作预测被完整保住（与 M2d 基线逐格相同、NLL 略好），零状态与换名池迁移同时**高于**前两个候选。代价是记忆批 CE 末值 2.953（λ=1 为 1.999），即批内 KL 与 CE 存在张力，但换来评测分布上更好的行为。
- **边界**：该 run 状态为 `failed`（停在 `m2l_cells`），无 `cells`/`stratified`/`regression`/`transfer`/`preservation_screen`/checkpoint → **不是正式通过、不晋升**，只作为机制证据。正式结果以排队中的 `m2md-distill-20261013-r2` 完成为准；机器当前仍被外部 MLX 与高 load 占用（load 5–36、外部 MLX 16–21% CPU），运行器在等"AC＋外部 MLX ≤5%＋load ≤4＋锁空闲"连续三次采样。
- 本轮至此四次由独立复核/保护拦下的问题（E15 UnboundLocalError、C07 重复关键字、E16 期改源码、D 的 F1/F2/F3＋`m2l_cells`）全部修复并加了可静态检出的回归；D 的两次失败也都如实留档，未影响结论。

## D20261013-31：D 条件一次有界训练成功——五项门全部通过（未晋升）

- **run `96b72328-d9c1-4b48-b69c-1fa30ba8123c`**（experiment `m2md-distill-20261013-r2`，13:25:16–13:33:18，**480.4 秒**，200 次更新，**184,704 单位＝预留＝计划**，role model，completed）。
- **五项登记门全部通过**（本轮首次）：开发零状态 **4,007/4,096**（变化 124/127）、固定换名池 **2,016/2,048**（变化 138/140）、一步动作 **377/384（ΔNLL −0.00896）**、四步 **359/384（ΔNLL −0.07735）**、重建 **544/544**；`preservation_screen = passed`、`regression` 六项全 true、迁移两项 `transferred`；**未晋升**（`promotion=false`），开发历史 `memory_screen` 仍 failed。
- **机制判读**：C07 暴露的"符号空间冲突"根因**成立**——λ 不变（1.0），只把教师 KL 折进同一批/同一次前向/同一套换名符号，动作从 287/384 恢复到与 M2d 逐格相同的 377/384（NLL 略好），且迁移**高于** λ=1 与 λ=10 两个候选（4,007 vs 3,930/3,904；2,016 vs 1,998/1,972）。代价：记忆批 CE 末值 2.953（λ=1 为 1.999）——KL 与 CE 的张力真实存在，但换来评测分布上更好的行为。首更新 KL **恰为 0.0**（4 个 micro-batch），在真实 MLX 上自校验了"师生同批同键"。
- **保护与账本**：冻结 282,128 逐位（从保存 checkpoint 独立复算）、仅 GRU 四张量变化、教师加载 0.0020 秒（F8 余量充足）、MLX 峰值 15.5 MiB、源文件未变、M2l 复用 87,822 字段 diff 0.0；账本 completed/model/200/184,704/1,540 秒；当日 8,999 秒。
- **独立核对**（CPU 只读脚本 [verify_and_report.py](artifacts/reports/E20-d/verify_and_report.py)）：verdict = passed，全部检查 OK，门重算与屏幕状态一致。
- **三次尝试全部留档**：第 1 次实现缺陷（`m2l_cells`，同类第 4 处，已修＋通用未绑定名审计＋变异验证）、第 2 次环境争用超窗（我违反自定空闲策略，已记录）、第 3 次成功。**下一步**（需另行授权与登记）：按 [M2n 方案](M2N_NONZERO_HISTORY_PROPOSAL.md) 路线 A 以本候选为起点做非零历史一步保持；或对同一 D 条件做单因素延伸（一次只改一项）。

## M20261013-01：M2n（非零历史一步保持）实现、复核 rejected（F1 致命 / F2 单位低估）与处置

- **目标**：D 已过五门但**开发历史 `memory_screen` 失败**；M2n 让学生在**自己的多步历史**下保持上一步观察，同时不失去迁移与动作保持。**性质＝新能力实验，不是单因素消融**：相对 D 同时改①记忆批序列形式（单边 → burn_in 4 上下文步 ＋ 8 损失步 ＝ 12 转移/13 帧）、②批来源（登记的 256 行池单边行 → `SequenceSampler` 历史窗口，种子 windows 2101 / augmentation 2307）、③不再用登记的双射清单（改为 M2h 协议的逐窗口一致字节置换）。其余保持：M2d 起点、尾部 111,104/冻结 282,128、200 次、lr 0.003、裁剪 1.0、batch16-micro4、λ=1 批内教师蒸馏（同批/同前向/同键）、同一套评测与五门，另加主门＝开发历史 `memory_screen`。
- **成本（复核后修正）**：每次更新 **416 单位**（学生 16×13＝208 ＋ 在线教师 208）、总计 **255,104 = 171,904 ＋ 200×416**；预付 **1,740 秒**（940 固定 ＋ 200×4）、工作 1,760、监督 1,790 ≤ 单次上限 1,800；无 teacher_cache 阶段。
- **独立复核（subagent `cdd328c5`）verdict = rejected**（[报告](artifacts/reports/E23-m2n/review/M2N-independent-review-20261013.md)）：**F1（CRITICAL）** 计划 `seeds` 被 `micro_memory_plan` 整字典覆盖、**没有 `windows`**，而 M2n 的 `window_rng` 守卫为真 → **每次运行必然 KeyError（0 次更新）**；**F2（HIGH）** 采样器语义是 `burn_in + sequence_steps` 个转移，8 损失步＝12 转移/13 帧 → 应为 416/更新、255,104，原登记 288/229,504 **低估 25,600 单位（+11.2%）**；F3 闭包基线未披露；F4–F6 主门仅为报告字段、陈旧字段/死常量、`permutation_sha256` 恒 null；**F7＝第 5 次"CPU 全绿真实路径必错"**（仓内 7/7 通过＋名称级审计 0 发现，而真实路径必崩：缺陷是**值级**的）。
- **处置**：①补 `seeds["windows"]=2101` 与"缺键即抛"检查；②按 8 损失步**重登记** 416/255,104（秒数不变）；③明确接受新闭包基线并写明 diff＝末尾追加的 M2n 条件块；④确认屏幕是判定依据而非运行中止条件；⑤修 `transitions_per_window=12`、死常量改为实际使用；⑥历史条件不再写 `permutation_sha256`；⑦**新增两项值级审计**（按条件求值的**种子键可达性**、以登记 M2h 计划为参照的**单位/窗口契约**），变异 M7/M8/M9 全部被捕获（[证据](artifacts/reports/E23-m2n/mutation_evidence.txt)）。
- **一致性补齐（用户要求，两轮）**：第一轮改源码注释、登记正文、核对脚本与实现补丁说明中的陈旧口径为 416/255,104/"8 损失步＝12 转移/13 帧"；第二轮（复核者指出后）修①登记身份表哈希、②**被哈希的 `plan["loss"]` 字段**（仍写 "4 loss edges"，会随报告/checkpoint/preregistration 永久留档并导致按 288 复算误判）→ 改为 8 损失步并同步新 `condition_sha256 = 5db7e2fc…`、③核对脚本残留 `units_per_update == 64` → 416，④按 INFO 给种子键审计补 `For.iter/While.test/With.items` 头部扫描。历史补丁脚本标注为复核前修订并保留原文作为证据。
- **F3 澄清（可复现）**：在追加点精确切分闭包，前缀 SHA256 = `ff6e0a8ac31400acc404affbe12c0fe00fe7fca13f216eafc7cb550423e6b5f4`，**逐字节等于 D 已验证的闭包**；复核者最初测得的 `cfb1510d…` ＝ 该前缀 ＋ 追加时插入的两个空行分隔符（度量口径差异，非未披露改动）。
- 当前状态：等独立复核者在**最终身份**上确认 F1/F2 关闭后，才登记运行；未启动 MLX、未训练。

## M20261013-02：M2n 首次执行因"单边不变量误伤"fail-closed（第 6 例复用守卫未设限）

- **run `a4f19145-571f-4e55-aac6-244c7f6331aa`，57.8 秒，state failed，0 次更新**：`single-edge memory unexpectedly has front-output gradients`（`current_stage=training_update`；before 四项评测与 `local_checks[0]` 已完成；账本 1 步/43,136 单位/284.0 秒预付，无错账）。
- **根因**：`memory_worker.py` 把"单边记忆 ⇒ GRU 前排行梯度必为 0"的**结构性不变量**无条件施加在 local-fit 路径。它对登记的 M2m-d/C07/D/探针（窗口＝1）成立，但 M2n 的 12 转移窗口使损失经早前步骤**合法**到达前排行 → 守卫误伤。这是本轮**第 6 例**"复用分支守卫未按登记配方设限"（前五例：E15 UnboundLocalError、C07 重复关键字、D 的 F1/F2/F3＋`m2l_cells`、M2n 的 F1 种子键）。
- **修复**：不变量按 `plan["transitions_per_window"] == 1` 设限（保留非有限检查并把前排行梯度记为遥测）；**应用梯度仍是 mask 后的结果**，可训练范围保持登记的尾部 111,104。新增 AST 回归测试断言该 raise 的守卫必须含窗口条件；变异 M10（去掉设限＝真实故障）/M11（禁用不变量）均被捕获。
- 修复后 worker `e9831f8e…`、M2n 测试 `dfb962fd…`；CPU 回归 **632 项通过**；条件 SHA `5db7e2fc…` 与冻结基准未变。按登记不自动补跑，待独立复核对新身份确认后重跑。

## M20261013-03：M2n 一次有界训练完成——负结果（四门退步、历史主门仍失败），首个正历史信号

- **run `ddb5882a-50b2-4507-8135-7cd13ef2e250`**（experiment `m2n-nonzero-history-20261013-r1`，15:41:54–15:50:05，**489.5 秒**，200 次更新，**255,104 单位＝预留＝计划**，role model，completed）。
- **结果**：五门中四门退步、**历史主门仍 failed**（`preservation_screen=failed`、`transfer.outcome=underfit`、`promotion=false`）：开发零状态 **2,218/4,096**（D 为 4,007；变化 78/127）、固定换名池 **1,108/2,048**（D 为 2,016；变化 75/140）、一步/四步动作准确率保持 377/359 但 **ΔNLL +0.0755/+0.6183** 越界、重建 544/544 通过。
- **训练侧诊断（经运行后复核 P1 修正）**：`loss`/`memory_loss` 是**含 KL 的合成目标**——分解后**纯 CE 末值 M2n 2.1269 vs D 2.1060 几乎相同**，故「记忆未收敛」的因果解释**不成立**；真实机制是**能力置换＋学生–教师发散**：固定单边局部屏 0.9766/1.0 → **0.4297/0.3793**、开发零状态 4,007→**2,218**、换名池 2,016→**1,108**，批内 KL 0.42→**1.4544**（D 为 0.8465）。前排行梯度遥测 2.8e-2→1.4e-2（合法非零，证实守卫设限正确）、200 次合计 40.0 秒（中位 0.190 秒 ≪ 4 秒窗口）。
- **历史侧（经 P2 修正）**：**没有**相对优势——同查询配对上 `history_tail` 变化单元 **48/127＝0.3780 低于** `zero_context_tail` 的 **78/127＝0.6142**（差 −0.2362）；`beats_current_and_reset_changed=true` 仅因 `copy_current`/`reset_history` 在该子集恰为 0（门槛极低）。**真正站得住的正面信号是稠密读回 `memory_tail`：开发 0.0000→0.3057（NLL 7.8662→2.7855）、训练 0.0035→0.3901（7.1160→2.7035）**，而 D 的开发读回几乎为 0（→0.0023）——即能被教出读回、但还不会用历史，且远低于 95%/80% 门槛。
- **完整性达标（负结果不是实现缺陷）**：255,104＝预留＝计划、200 次、冻结 282,128 逐位（从 checkpoint 独立复算）、仅 GRU 四张量变化、首更新 KL 恰 0.0、教师加载 0.00197 秒、MLX 峰值 19.6 MiB、账本 completed/model/200/255,104/1,740、当日 11,023 秒。
- **前序**：首轮 run `a4f19145…` 在 57.8 秒、0 次更新处 fail-closed（"单边不变量"误伤多步窗口）→ 按 `transitions_per_window == 1` 设限＋AST 回归＋变异 M10/M11＋独立复核后重跑；两次尝试全部留档。
- **结论与候选方向**：该配方**回退**（置换既有能力、历史仍未换到）；D 仍是唯一过五门的候选。下一候选建议①**混合批**（D 配方不变，batch 内 12 单边＋4 历史，直接限制置换幅度），②自由想象历史，③更长预算（**不建议**：纯 CE 已与 D 持平、非欠拟合），④解冻前部（需单独论证），⑤就此收束并披露。**需用户决定，不自动运行。**
- **运行后独立复核（subagent `cdd328c5`）verdict = supported**（[报告](artifacts/reports/E23-m2n/review/M2N-postrun-verification-20261013.md)）：完整性全通（255,104＝预留＝计划、冻结逐位、首更新 KL 恰 0、账本与当日秒一致），负结果可信、非实现缺陷；其**数据流重放**（重放 200 次登记采样＋置换后的 PCG64 终态与 checkpoint `rng_states` 逐字段相等）与**评测侧 before 块与 D 逐字节相同**两条证据锁死数据与评测身份；发现 P1/P2（归因，已修正）、P3（`training_sample_rows` 记的是池调度而非实际窗口，下一实现修正）、P4（分块均值口径，已注明）。

## M20261013-04：M2n-M 混合批实现完成并通过独立复核（A 范围 GridLab S07-R1 同步 approved）

- **路线**：用户决定先做混合批候选、**不追加 M2n 训练次数**；"能力置换＋师生发散"目前是**证据支持的解释**而非已证因果，混合批正是检验"降低历史占比能否保住单边能力"的可证伪预测。
- **设计**（[方案](artifacts/reports/E24-mixed/MIXED-BATCH-SCHEME-20261013.md)）：登记 16 行调度的前 12 行保持单边（双射沿用登记清单），调度行 12–15 不训练；历史半＝4 个 12 转移窗口（burn_in 4＋8 损失步），登记种子 2101 采样、**独立生成器 2407** 置换；两半**各自与在线冻结教师同批同键**、**分别累加**后按 **12:4 加权**合并（各半先按可见目标取均值）；**单边半独享**前排行梯度不变量。成本 **152 单位/更新 → 202,304 总量**、**1,540 秒预付**、截止 1,590/1,640。
- **独立复核（3 轮，subagent `645a15ef`）**：B 范围最终 **approved**。修掉三项硬伤：**B-F1（阻断）**历史半实际是 2 帧窗口（生产采样器取了单边几何；测试夹具手写参数导致全绿）→ 新增 `sampler_geometry` 并让测试与生产同源；**B-F3（阻断）**历史半与单边半共享置换生成器、清单流序自 update 1 错位（复核者重放 3,200 次抽取证明）→ 独立生成器 2407＋**流序重放测试**（摘要哈希等于 M2m-c 报告锚点）；**B-F2（HIGH）**共享尾部二次除 `target_count`（真实数据 352 倍）→ 混合条件跳过。另有 F4–F7（记录字段缺失、死分支、陈旧注释、断言只钉表达式）全部修复；三处"声称与实物不符"（方案正文未改、补丁未标注、测试 docstring 过度声称）已如实更正。
- **测试加固（按复核最小断言）**：把 `ast.unparse` 子串匹配升级为**结构相等＋旗标集求值**——C01（死守卫使所有条件归一化失效、无兜底）、B08（`rng_states` 链）、C02（三元别名）、C03/C04（摘要截断/清空）五个探针**全部被捕获**；同源形状证据改用 `plan["sampler_geometry"]`。
- **A 范围（GridLab S07-R1，执行者 grokbot-newbot）**：独立复核 **approved**——冻结清单摘要 `1f80c54a…36d8` 独立重算相符、22 项篡改 22/22 被拒、公开内容重合 0（绕过 helper 自算 18 项）、257＋21 项 CPU 复现、不 import MLX。统筹已登记：摘要未经复核不得重登记；`s07-closeout/` 为唯一有效划分根（`s07-sample/` 仅历史样例）。
- **现状**：CPU **267＋379＝646 通过**、ruff 全过；worker `0d85f786…`、closure `9151050a…`、条件摘要 `c422c354…`。**未启动真实运行**——复核条件⑤明确"不构成运行授权"，是否起运行按预算/资源单独决定。


## S20261013-R2：GridLab 示例划分身份登记与独立复核领取

- Codex领取本次三个根文档的R2状态整合；执行者不得同时编辑。实测新清单完整SHA为 `52eda9a56722eabe1c80e797e969ab33cd371377597fa56a4f61f7450d6eb3b6`，登记为当前示例划分身份，验收待独立复核；旧清单 `1f80c54a5ff3c4089ae902b6862f540ace1513e976a7280917b8e491e46d36d8` 撤回活动身份，历史证据不改。此前单帧重合驱动的25/27交换撤销，单帧重合只报告。
- 独立复核由 Einstein（agent `01a135b5-b4df-75a1-94f8-df87c4fd0bc2`）领取：源码/四项隔离测试/冻结身份/重复定义/篡改拒绝/旧A-F1与A-F2/全量证据；只可新建独立报告与CPU证据，不导入MLX、不跑全量、不写RunStore、不创建run。
- 作者全量XML独立解析为2415 tests、0 failures/errors/skipped；summary退出码0、171.1秒、waiver=null。没有重复运行全量。白名单增加gridlab_v1_r2.py在原受领测试文件内，按必要兼容性调整接收，是否扩大生产接线由复核检查。身份登记不代替工程验收，也不将8世界示例称正式最终评测池。

## M20261013-05：混合批首次执行因环境争用超窗（记录在案），排队等静默窗口

- **run `85b844f5-a9dd-4ecc-933c-82f8b4cc7b18`，95.7 秒，state failed，0 次更新**：`exceeded prepaid stage window`（`current_stage = before_memory_train`，90 秒窗口）；账本 0 步 / 22,632 单位 / 120.0 秒预付，无错账；当日 11,143 秒。
- **根因是环境争用**：预检 1 分钟 load 3.87（低于记录阈值 ≤8），但 **5/15 分钟 load 为 7.41/10.45** —— 机器整体仍忙使评测超窗。对照：D（480 秒）与 M2n（489 秒）成功时负载约 4–5。`pmset -g therm` 无热/性能告警，CPU 频率 3504/3504，**无热降频证据**。
- **处置**：不改窗口/预算/守卫；排队等 **1 分钟与 5 分钟 load 同时 ≤4**、无繁忙外部 MLX、AC、锁空闲（连续 3 次采样）后用 `m2nm-mixed-20261013-r1` 重跑（[run_when_quiet.py](artifacts/reports/E24-mixed/run_when_quiet.py)，最长 6 小时，只探测锁不持锁）。
- 本轮至此的环境性超窗共 3 次（D 第 2 次、混合批第 1 次由我引起；另一次为 M2n 前的调度策略讨论），共同教训：**只看 1 分钟 load 不足**，须同时看 5 分钟负载与外部 MLX 占用。


## S20261013-R2-close：限范围验收与混合批排队边界

- Codex接收 artifacts/reports/S07-R2-independent-review-20261013.md：supported仅限固定52eda9a5清单、8世界原分区、当前重复为0、子进程隔离；独立264项CPU通过，作者2415项全量证据通过。S07-R2在此范围accepted。旧A-F1/A-F2在caller替换expected SHA后仍可绕过，另有负对照未区分ImportError与断言的F3；不登记为已关闭。旧1f80c54a活动身份撤回不变，不影响混合批B范围复核。
- 混合批run85b844f5的超窗和0更新按执行者证据记录；负载争用是合理解释，单凭load均值和无热告警不足以确定因果。当前run_when_quiet.py与进程已只读查看，未启动/停止/修改watcher或外部进程。新重跑应在启动时重核源码、配置、清单、预算与内存；低load预检不是运行期间资源充足的保证。

## M20261013-06：混合批两次尝试均因 Metal 争用超窗；运营性窗口修订 + 误改披露

- **两次失败**（`85b844f5…` 95.7 秒、`0602dae2…` 96.6 秒）均为 `before_memory_train` 阶段窗口（90 秒）用尽，0 次更新，fail-closed 无错账；第二次由静默窗口 watcher 在 load 3.36/3.66 时执行——说明**负载均值不是有效判据**。
- **根因：持久 Metal/GPU 争用**——Docker VM `com.apple.Virtualization.VirtualMachine` 8.74 GiB/~25% CPU，另加 node(AinerStudio)、Codex、Antigravity、Docker backend、oMLX、stream_viewer；无热降频证据。计划全量 diff：D 与混合评测旋钮完全相同 → 与条件定义无关。
- **修订（只动窗口）**：两个 memory 分区 90→150、其余六个评测阶段 +20% → 预付 1,740 / 工作 1,760 / 监督 1,780 ≤ 1,800；单位/种子/λ/几何/门全部不变；D 与 M2n 未动；条件新摘要 `dd02c4fe…`。
- **流程失误（已披露并回滚）**：首个补丁锚点误匹配到**已登记的 D 条件** seconds 块；发现后立即回滚，D 恢复 `5aab99e5…`、M2n 仍 `5db7e2fc…`，误改状态**从未用于任何运行**。教训：改条件计划必须逐条件比对摘要，锚点必须唯一化。
- **下一步**：等独立复核确认新身份后，在争用降低时执行；若用户能暂停 Docker/Electron/oMLX，成功概率显著提高。

## M20261013-07：窗口修订经复核维持 approved；运行改按"全系统 CPU 占用"排队

- 复核者逐字段证明**误改已完全回滚**（D 侧变化字段数 0；D `5aab99e5…`＋`seconds={940,600,1540,1590,1640}`、M2n `5db7e2fc…`、C07 `9b9cabfc…`、冻结基准 `cb1437ef…`），改动面恰为 `mixed_condition` 6 字段＋`mixed_plan` 17 字段，**科学字段 0 改动**，Σ 复算 1,740 ✓；变异捕获 **12/21**，B01–B08 全部捕获、C01–C04 由 4/4 全漏变 **4/4 全捕获**。
- **B4-F1 措辞更正（不改源码）**：条件内 amendment 文本"其他六个 +20%"不实，实际为 +44.4%×2、+16.7%×2、+22.2%×2（合计 +26.7%）；数值与算术正确，已在本报告留档更正，留待下次条件变更顺带修正。
- **复核者定量推断**：D 的 `before.memory_train` 需 28,928 单位且曾在 90 秒内完成；两次混合在 90 秒内推进 78%/91% → 速率 251–292 单位/秒 → 预估需 99–115 秒，修订给 150 秒 → **余量 1.30×–1.51×**。
- **排队判据升级**：两次失败证明 load 均值不是有效判据（本次实测 `mediaanalysisd` 曾占 **301% CPU**、Docker VM 12%、load 11.5）。watcher 改为要求**全系统 CPU ≤20%、单进程 ≤40%、load ≤4、AC、锁空闲**连续三次采样后再执行；预算 1,740 秒预付、CLI 超时 min(1780, max_wall)。

## M20261013-08：混合批完成——迁移保住（4,035/4,096），动作门仍失败；逐半遥测定位到"梯度份额"问题

- **run `e7151f2c-afc7-4512-bfc9-7b97b8899c1f`**（`m2nm-mixed-20261013-r2`，287.4 秒，200 次，**202,304＝预留＝计划**，completed；前两次尝试因环境争用超窗失败，修订评测窗口后通过）。
- **结果**：开发零状态 **4,035/4,096**（变化 124/127；D 为 4,007、M2n 为 2,218）、换名池 **1,989/2,048**（变化 136/140；D 2,016、M2n 1,108）、动作 376/384（**ΔNLL +0.2339**）与 342/384（**+1.5381**）（D 为 377/−0.0090、359/−0.0773）、重建 544/544；`preservation_screen=failed`、历史屏 failed、未晋升。
- **判读**：**迁移侧证实置换假设**——把历史压到 4/16 即把单边能力从 2,218 恢复到 4,035（略高于 D）。**动作侧反而更差**：逐半遥测显示 4 行历史半有 **256 个可见目标**（12 行单边半只有 96），KL 1.887 vs 0.825，应用梯度 L2 2.659 vs 1.124 → 按 12:4 行权重合并后历史半仍占约 **44% 的梯度**。**结论：行权重 ≠ 梯度权重**，下一步应直接限制历史半的损失/梯度贡献（λ_h）。
- **完整性**：首更新 KL 恰 0.0、冻结逐位、`source_files_unchanged`、账本 `completed/model/200/202304/1740`、当日 13,003 秒、训练算力 10.1 秒（中位 0.048 秒/更新）。
- **下一候选（按用户"取消限制直接跑"）**：M2n-M2 ＝ 混合批 ＋ 登记 λ_h=0.25（只缩放历史半贡献，行数不变）；预登记门与判读见 [结果报告](artifacts/reports/E24-mixed/MIXED-RESULT-20261013.md)。流程变更如实披露：不再等预运行复核，改为运行后独立复核。

## M20261013-09：用户指示取消空闲限制、全力跑（运行节奏，不改科学条件）

- **用户原话**（10-13 晚）：「之前设计的是使用 cpu gpu 空闲跑，现在可以取消限制，全力跑，会更快」。由 Claude（统筹）记录并落实。
- **改动 1：训练占空比 0.25 → 1.0**（`configs/pilot.yaml` 的 `resources.active.training_duty_cycle`）。
  - `memory_worker` 读的就是 active 档。原来每次更新后要休息 3 倍的计算时间；混合批 r2 的 10.1 秒训练算力，约对应 30 秒休息。
  - 只改节奏，不改训练数学、种子、单位、门槛、条件摘要。`source_files_unchanged` 校验的是输入报告、检查点和缓存，不包括这个配置。
- **改动 2：不再等静默窗口**。运行直接启动，不再要求全系统 CPU ≤20%、单进程 ≤40%、load ≤4 连续三次采样（M20261013-07 的排队判据作废）。
  - 共享锁、RunStore、预付窗口和预算、fail-closed 都照旧：超窗仍然 0 次更新、留档、不自动重试。
- **保留**：系统余量 16GiB、项目进程 8GiB、MLX 4GiB、swap 增长守卫、磁盘余量、用电池不训练。这些是防崩溃的保护线，不是空闲限制。
- **全机 GPU**：AinerRelay 的闸门改为只让重型任务（LTX 这类大模型）互相串行。轻量 GPU 任务（含本项目约 39 万参数的模型）随时并行，AinerZero 的锁不再挡别的项目。
- **后续登记**：在这之后登记的运行，记录的配置是占空比 1.0；之前的 run 记录不变。



## R20261013-Relay：Codex一级统筹接手、验收与判读纠正

- AinerRelay作为派活状态入口（Z1），任务正文/文件范围仍在仓库；最新用户保留真实训练发布、下载、付费、推送、删除批准。A1/A2接受完整性与负结果证据，不晋升。
- Z2审议更正M20261013-08：历史半加权范数量级均值34.9%、末次44.1%，非投影份额；归一化后的目标数不自动解释梯度差，更大范数不证明方向冲突或因果。原结果报告保留，本附录纠正解释。只恢复动作不证明历史可用，单次失败不证明结构不可能。
- A3设计固定λ_h=0.25且不二次归一化：0.75*(CE_s+KL_s)+0.0625*(CE_h+KL_h)，起点原M2d，202304单位/1740秒/1760·1780；原五门、D锚点4007/2016、历史屏分开判。文档 artifacts/reports/relay-codex-20261013/，condition SHA待实现，不执行运行。
- B2失败打回：扩展tests/test_gridlab_s07_r1.py受领范围，旧拒绝断言改为登记身份先拒绝；纯CPU定向回归后由B3独立复核。此前2421/1全量的MLX/锁/资源证据须补交，不能称tests/天然纯CPU。C1由原作者继续，不抢文件。


R20261013-Relay附注：读取到并行统筹M20261013-09与AWZ ADR-0009新策略后，C2/GV1同步为轻量占用只报告、重型互斥，资源/身份守卫保留；A3设计记录duty1.0及其与历史r2的运行策略差异，不宣称所有配置单因素。原预算202304/1740/1760·1780不变，A5仍draft。


R20261013-Relay-B3结论：修订独立复核报告accepted（支持其rejected实现结论）。A-F1/F3独立支持收口，A-F2仍缺public agent_xy真实重算；B2三次失败留档并blocked，剩余补修拆B6、不同作者B7回验。纠正新B2/B3早先归因：原16:56 S07-R2全量脚本和summary确有flock/资源证据，锁mtime不变不能推出未持锁；attempt2全量纪律单独记录不混淆原R2。原活动清单52eda9a5与2415通过证据仍有效。


## R20261013-B4：公开对象观测跟踪基线设计

Codex固定三非学习CPU基线current_only/last_seen_nn/constant_velocity_nn，因果逐帧只读公开对象观测，不接private身份/速度或真值EntityTrack；评估单独读私有，不回喂。阈值2格、最长保留8tick、一对一穷举L1、平局与不可辨识单列，随机/scripted及遮挡/混淆/交换/未见路径分别计数。方案 artifacts/reports/relay-codex-20261013/B4-public-tracking-scheme.md。B5范围与A4/B6互不重叠，实施纯CPU；正式8世界基线输出待B6/B7路径闭包验收；B8独立回验，不训练、不宣称RGB感知能力。


## R20261014-Relay-01：最新授权与第一轮验收

Codex按10-14用户新授权：已登记且预算内运行可直接发布，不再要求逐次用户批准；超预算/冻结参数或门改动/下载/付费/推送/删除仍保留批准。B5/B9结合既有B8限CPU实现与导入隔离验收；B10/B11派固定8世界CPU样例评测与独立复算，60秒/零模型调用，不作为正式final能力验收。
C1生产fail-closed由CV1证实（报告accepted），实现因成功集成测试活树钉旧freeze仍红打回fixture补修，旧E24锚点保持。A8/A9打回身份门反例files={}仍通过，证据relay-codex-20261014/A8-identity-counterexample.json；补严格必需文件/协议/config绑定，科学参数预算不改，新源码身份另登记。A5待前置通过再发布，无本轮训练启动。


## R20261014-Relay-02：M2n-M2真实运行发布

A10独立回验身份门supported并accepted，A8补修accepted；纯CPU在一级现场再次重算身份/实际config与条件6e98299668221d0ba970198b1af662ba5c2a1b4c9dd0f29ccb56ce0ed06041d0，λ0.25/单位202304/预付1740/截止1760·1780与登记一致，未导MLX。按最新用户授权发布A5一次运行experiment m2nm2-weight025-20261014，冻结清单完整身份与参数见relay-codex-20261014/A5-final-registration.json；源M2d/重置AdamW/200更新/duty1.0，CLI锁RunStore/原保护不改，失败不自动重试，A6不同作者运行后复核。该记录是发布，不是模型完成或能力验收。
C1补修与CV2限CPU范围accepted，保留旧E24冻结；测试仍有机器内存依赖的小项，不能称原等待脚本适合新协议运行，本次A5直接新CLI。


## R20261014-Relay-03：已授权调度迁移与历史来源配置相等冲突

A5登记命令在00:14:16启动后1秒因validate_history_source整配置相等拒绝，0次更新/无checkpoint/无能力评测。原输出run-m2nm2-weight025-20261014.json保留，A5 blocked不重领；不是负能力结果或环境超窗。执行者CPU对照仅active duty来源0.25/live1.0不同。新A11/A12补显式新协议兼容已登记调度迁移，不能忽略整个resources或修改旧检查点/科学参数/保护线；完整新源码/条件/配置身份及CPU回验后再决定新ID预算内运行，不自动重试原ID。


### R20261014-Relay-04：样例基线验收与来源闭包再次退回（Codex）

B10-r1/B12按冻结清单52eda9a5…复算24文件、16动作/17观察、private.events仅用于评测；三基线计数精确一致，按CPU样例范围验收，不构成正式能力过门。A11/A12尚未满足原任务全调用链：memory_worker._prepare_relabel仍将live config交validate_coverage_source，其内部validate_history_source将再次拒绝历史.25与live1.0。退回补齐真实CPU来源闭包；保留A5失败与原证据，不启动新运行。


## R20261014-Relay-05：来源闭包通过、身份重登记、A5同一登记以新ID重跑发布（Claude）

Codex额度耗尽后Claude接任一级统筹。A13完整历史来源CPU闭包与A14独立回验均accepted：Claude现场补审A14未覆盖的内部绑定——仅weight025开关路径在weight025_source_schedule_compat严格核验后（唯一允许差异active duty 0.25→1.0、类型与其余全部字段逐项相等）改用真实checkpoint元数据的历史config作lineage视图，live config不变，调用者无法注入替代config；0.5等非登记duty反例测试既有。A11/A12、A5标记取消（被A13/A14、A15取代，证据与原产物全部保留）。
身份重登记：原weight025-identity.json（65ffe4da…，A5使用）字节原样归档为weight025-identity-A5-20261014.json；新文件e30504d2…只更新memory_worker.py→ac76995b…（A13）与action_preservation_closure.py→1c0f0247…（A11 helper，A12/A14覆盖），并记录supersedes/changed_files。现场CPU重算config_hash 0169cc73…、condition 6e982996…、design 279655b7…均与A5登记相等；CLI verify_weight025_identity通过，weight_entry/source_compat/mixed_weight共27项通过，未导MLX。
决策：A5失败发生在训练前守卫、0更新、未评估任何门，非科学尝试，不构成选择偏差；按Codex R20261014-Relay-03既定路线，以新ID m2nm2-weight025-r2-20261014 发布A15同一登记运行（λ0.25、单位202304/预付1740/截止1760·1780、源M2d重置AdamW、200更新、duty1.0、CLI锁RunStore），no_retry不变，用户10-13「取消限制直接跑」授权覆盖。A6改为复核A15，A7排在A6后。这是发布，不是模型完成或能力验收。


## R20261014-Relay-06：r2被执行环境回收，r3由一级托管运行（Claude）

A15（m2nm2-weight025-r2-20261014）预检全过，启动后进程在 validating 阶段被二级执行环境回收（shell 退出即杀后台），stdout/stderr 0 字节、无输出 JSON；RunStore 留 e244d307 state=validating、0 更新、预留 180 秒（CLI 监督清理只处理本次调用新建的运行，父进程被杀故未清理；按账本纪律不手改，A6 记录）。此前 grokbot-80dl 也因单条前台约 13 分钟上限、后台被回收而放弃。结论：现有二级执行器无法托管约 30 分钟进程，属基础设施限制，非实验结果。
同 R20261014-Relay-05 理由（0 更新、无门评估、非科学尝试），以新 ID m2nm2-weight025-r3-20261014 发布 A16，由一级 claude 在自身会话后台托管，命令与登记逐项一致（CLI pid 95143 参数比对 True），01:20:29 启动；当时 load 12.7、mediaanalysisd 134% CPU、可用内存约 50 GiB、AC 供电，按 M20261013-09 不等空闲。A6 改为复核 A16，A7 一级判读。no_retry 仍适用于 r3。


## R20261014-Relay-07：M2n-M2判读——λ_h杠杆证伪，登记λ_h=0最小区分对照（Claude，A7）

A16（λ_h=0.25）经 A6 独立复算：开发零状态 3914（123/127）、换名池 1982（135/140）、动作 376/+0.2502、331/+1.5081、重建 544/544；D 锚点未达；历史屏 failed（整体 0.600、变化 0.442、各世界 0.786/0.588/0.643/0.125）。预登记成功条件未满足；按 Z2 不称多步历史可用、也不称结构冲突；不晋升不重试不调λ。
关键：历史半原始梯度范数份额 44%→19.6%（投影 5.1%）而动作 ΔNLL 与 E24（λ=1）基本相同（0.234/1.538→0.250/1.508），4 步准确率 342→331——λ_h 作为动作保护杠杆在 [0.25,1] 不敏感，E24 “梯度份额致退化”诊断在损失加权形式下不成立；零状态 4035→3914 为降权代价。待区分：(A) 任何非零历史梯度经 AdamW 逐坐标归一化扰动动作；(B) 12+4 混合几何本身（少 4 行单边/采样）。登记唯一因素对照 M2n-M3-control（λ_h=0，其余与 M2n-M2 全同，预算同类，非能力候选），设计与预固定判读见 artifacts/reports/relay-claude-20261014/A7-interpretation.md 与 M2NM3-control-registration.json（84cf6938…）。实现→不同作者CPU复核→一级身份登记→一级托管运行→独立复核→判读。


### R20261014-Relay-08：A17 因放宽 weight025 身份门被打回（Claude）

A17（λ_h=0 对照实现，条件 e7666014…）在 cli.py 新增 WEIGHT025_FROZEN_SHAS，并让 verify_weight025_identity 在“登记 sha 等于硬编码旧值”时忽略实际文件不符。结果是 cli/memory_worker/closure 已变，weight025 live 门仍通过，身份门失效，“全量 0 失败”建立在这个绕过上。按保护线不放宽原则打回：删除绕过，weight025-identity.json 作为历史登记保留（今后任何 weight025 运行需一级重登记），测试改为现算 record，并新增“改动任一登记文件即拒绝”的反例。报告里对五门的描述也写错了，要求更正。教训：改动共享入口的任务必须显式处理旧身份登记失效，不能让旧门静默放行。


## R20261014-Relay-09：M2n-M3-control 身份登记与运行发布（Claude）

A17 重做版（F1 豁免与 F2 调用栈推断已删除，F3 变异改为真实修改生产代码）经 A18（λ=0 核心，独立）与 A19（F1–F3 修复）复核，统筹抽查：FROZEN 与 _getframe 0 处，条件 e7666014…，design 84cf6938…，weight0 门通过，weight025 门如实拒绝（历史登记），weight0 专项 20 项通过。统筹核验登记 artifacts/reports/E26-weight0/weight0-identity.json（sha256 bea2df34…，run_authorized 仍为 false，单次授权写在任务参数里）。A20 实验 m2nm3-control-20261014 由一级托管，预检全过，09:02:02 启动（load 6.6）；A21 独立复核、A22 一级判读。weight025 入口测试读取历史身份而失败，属预期，另派 A23/A24 改为现算 record。


## R20261014-Relay-10：M2n-M3-control 判读——非零历史梯度即伤动作，转向解耦路线（Claude，A22）

A20（λ_h=0，run b4998f72…）经 A21 独立复核 86/86：动作 377/−0.0089、359/−0.0772（与 D 的 377/−0.0090、359/−0.0773 几乎相同）；开发零状态 3863（121/127，未过 3892）；换名池 1956；重建 544；历史屏 0.010/0.000（预期，不作证据）；历史梯度在 200/200 次更新上恰为 0。按预固定判读支持主张 A，排除主张 B（12+4 几何本身）。动作退化对 λ_h 呈开关式：λ_h 为 1 和 0.25 时退化相同，为 0 时消失，所以损失加权在 (0,1] 上都无法折中。历史训练对单边迁移有正贡献（开发零状态 3863/3914/4035 对应 λ_h=0/0.25/1）。按 Z2 不称结构根本不可能：冲突只在“共享尾部行 + 单一 AdamW + 损失加权”这一形式上得到证明。不晋升；D 仍为五门候选。下一步另行登记解耦路线（尾部行划分 / 梯度投影 / 分离优化器状态 / 预登记的自由想象历史或解构窗口），交一级设计任务 A25；超出 202304 单位/1740 秒的方案需用户批准。详见 artifacts/reports/relay-claude-20261014/A22-interpretation.md。


## R20261014-Relay-11：M2n-M4 设计登记——非零历史 + 一步截断反传（Claude，A25）

在解耦候选中先选 (v)：历史窗口照常前向，提供非零隐状态；每个损失步对传入的 (h,z) 做 stop_gradient，历史梯度只穿过一步转移（现实现只在 burn_in 处截断一次）。唯一因素相对 E24（λ_h=1，dd02c4fe…）；前向、单位 202304、秒数 1740/1760/1780、门全部不变，在已登记预算类别内。理由：历史屏衡量的就是非零历史下的一步保持；这个设计检验“多步反传重塑循环动态”这一剩余机制；代价最低。(i)(ii)(iii) 留作下一步，(ii) 需用户批准预算。预固定判读与登记见 artifacts/reports/relay-claude-20261014/A25-design.md、M2NM4-onestep-registration.json（fa3a37e2…）。


## R20261014-Relay-12：M2n-M4 实现通过、身份登记与运行发布（Claude）

A26（一步截断反传，条件 f6e71ddc…，design fa3a37e2…）经 A27 独立复核：计算图证明截断后每个损失项的梯度只穿过当前一步、前向逐位不变；4 条真实变异全部被抓到；7 个登记文件的身份门无任何豁免；全量回归 2543 项通过、0 失败。统筹核对差异键 start、backward 等都是描述字段，起点仍是同一个 f33974c9、重置 AdamW。工作树全部通过验证后提交 git 6df7b34。统筹核验并登记 artifacts/reports/E27-onestep/onestep-identity.json（sha256 9cd249f4…，run_authorized 仍为 false）。A28 实验 m2nm4-onestep-20261014 由一级托管运行（发布瞬间被 grokbot-vvym 抢领，7 秒后它自行释放），A29 做独立复核，A30 由一级判读。


### R20261014-Relay-13：M2n-M4 首跑失败于训练前来源守卫（Claude）

A28（实验 m2nm4-onestep-20261014）预检全过，启动 1 秒后在 run_memory 的严格 validate_history_source 处退出（起点 M2d 保存时 duty 0.25，现行配置 1.0），0 更新，没有评估任何门，RunStore 没有记录，不是科学尝试。原因：一步截断协议路径没有接上 A13 为 weight025 建立的“登记占空比迁移”兼容；A26 任务卡（统筹撰写）也没有要求真实起点的完整 CPU 准备链路探针，A27 的 CPU 复核同样没有覆盖。修复交 A31/A32：只为该协议显式接上同一条迁移，并加 source-full-chain 探针；修复后重新登记身份，以新 ID 运行，A29/A30 改指向新运行。教训：今后凡是新协议的实现任务，都必须附“真实起点完整 CPU 准备链路”探针，作为验收项。

## R20261014-power-policy：用户授权取消交流电守卫（Codex，A35）
用户明确要求取消电源守卫，已移除所有训练/诊断的AC强制检查；历史配置字节保留，电源策略字段不再强制true。其他资源保护/锁/预算/身份门保留。CPU定向419项通过；未训练。A34待独立复核与新源码身份登记，不能沿用旧SHA放行。

## R20261014-Relay-14：M2n-M4 判读——截断只减轻部分退化，归入“非零状态训练本身冲突”（Claude，A30）

A34（λ_h=1、历史半每个损失步截断到一步，run 1ec7f7e6…）经 A29 独立复核 172/172：动作 1 步 377、ΔNLL +0.1393；4 步 357、ΔNLL +1.0560，两项都在门外；零状态 4005、换名池 2000、重建 544 过门；D 锚点 4007/2016 未达到；历史屏 0.448/0.390。相对 E24（多步反传，+0.234/+1.538，4 步 342，历史屏 0.629/0.520），截断使 1 步 ΔNLL 减少约 40%、4 步 ΔNLL 减少约 31%，但 4 步 NLL 增幅仍约为门槛的 7 倍，且历史屏同时下降。按 A25 看结果前固定的三条规则，归入第三支：非零状态训练本身就在共享尾部与动作冲突，多步反传只是次要部分。补充证据：历史半 front 行梯度恰为 0，动作仍退化，说明伤害经由被改写的尾部隐藏状态进入后续 GRU 步。不晋升、不重试、不调 λ；D 仍是唯一过五门的候选。下一步按规则转 (i) 尾部行划分（先做与冻结读出头 8×16 布局兼容性的设计）或 (iv) 自由想象历史/解构窗口；(ii) 梯度投影超出登记预算，需用户批准。详见 [A30 判读](artifacts/reports/relay-claude-20261014/A30-interpretation.md)。

## R20261014-Relay-15：M2n-M5 设计——尾部行划分不可行，改为冻结尾部自循环块（Claude，A42）

CPU 静态分析（只读加载 6 个已登记 checkpoint，未导入 MLX；`A42/analysis.py`）。① (i) 尾部行划分不可行：冻结的 GRU 前段行、prior、posterior 第一层对尾部列的读取强度与前段列相当（中位数比 1.11/1.05/1.04），128 个尾部维没有一个低于前段中位数的 10%；任何被历史训练改写的尾部状态都会经冻结权重进入动作通路。② 区分“动作通过/退化”的是 `Wh[尾部行, 尾部列]` 自循环块：D 与 M2n-M3 这一块只有权重衰减量级（≈0.0004），因为单步零状态输入的尾部为 0；E24、M2n-M2、M2n-M4 这一块变化 5–7，其余块各 run 相当，前段行和非 GRU 参数全部为 0。这是 5 个 run 的相关证据，不是因果证明。③ 新候选 (vi)：以 E24 为基线，唯一改动是把这 49,152 个元素也冻结在 M2d 原值（可训练 111,104→61,952，冻结 282,128→331,280），预算同 E24 类别。看结果前固定四支判读（动作过门且历史屏 ≥0.448 / 0.05–0.448 / <0.05 / 动作不过门）。登记草案 `M2NM5-tailself-freeze-registration-draft.json` 尚未登记，实现与独立复核交二级，之后一级再登记身份并托管运行。(ii) 梯度投影仍需用户批准预算。详见 [A42 设计](artifacts/reports/relay-claude-20261014/A42-design.md)。

## R20261014-Relay-16：M2n-M5 判读——尾部自循环是动作伤害主通道，但冻结它把冲突挪到写入通路（Claude，A49）

A47（E24 基线上额外冻结 `Wh[尾部行, 尾部列]` 49,152 元素，run 0bbf1168…）经 A48 独立复核 59/59：331,280 冻结元素逐位不变；动作 1 步 377、ΔNLL +0.0351（过）；4 步 359、ΔNLL +0.1735（门槛 0.15，不过）；零状态 3724（门槛 3892，不过）、换名池 1883（门槛 1946，不过）；重建 544；历史屏 0.158/0.169。按 A42 预固定规则，(a)–(c) 都要求动作两项过门，故归入 (d)。相对 E24，1 步与 4 步 ΔNLL 分别减少约 85% 与 89%，是所有带历史训练的 run 中离动作门最近的一次，但不能事后改判。结论：尾部自循环块是动作伤害的主通道（有干预证据）；冻结后历史目标改经尾部行×前段列、`Wx`、偏置起作用，历史半梯度 L2 从 2.66 升到 3.74，与单边零状态学习争用写入通路，零状态迁移与换名池失守，历史屏降到 0.158。在共享尾部参数、单一优化器的形式下，靠冻结某一块切不开冲突。不晋升；D 仍是唯一过五门候选。下一步按 (d)：(ii) 梯度投影（证据最对口，但超出登记预算，需用户批准）或 (iv)（预算内备选），交 A50 设计与成本估算。详见 [A49 判读](artifacts/reports/relay-claude-20261014/A49-interpretation.md)。

## R20261014-Relay-17：下一条路线——M2n-M6 半间梯度投影（预算内）与 (ii) 完整投影的预算申请（Claude，A50）

关键事实：混合批每次更新本来就分别算出单边半与历史半的梯度树（`memory_worker.py` 约第 1850–1975 行），在两半之间做投影只是张量运算，不增加模型调用。限制：单边半是零状态输入，它的梯度在尾部自循环块上恰为 0，单独使用碰不到 E24 的动作主通道；但 M2n-M5 已冻结这一块，剩下的问题（零状态 3724、换名池 1883 失守，4 步 ΔNLL 余 +0.1735）正落在单边梯度覆盖的写入通路上。决定：推荐 M2n-M6 = M2n-M5 + 单侧半间投影（⟨g_h,g_s⟩<0 时把 g_h 在 g_s 上的冲突分量去掉，单边梯度不改），预算同 E24 类别，看结果前固定四支判读（五门全过且历史屏 ≥0.05 / 五门过但历史屏 <0.05 / 动作过但迁移不过 / 动作不过）。(ii) 完整投影（历史半内 CE 与 KL 梯度分开）需对历史半多做一次前向与反向：复用教师 logits 时 +10,400 单位（212,704，+5.1%），不复用时 +20,800（223,104，+10.3%），秒数与截止不变；作为预算申请提交用户，批准前不登记。(iv) 自由想象历史仅作后备概要。详见 [A50 设计](artifacts/reports/relay-claude-20261014/A50-design.md)。


## R20261014-Relay-Codex-18：M6 验收补充闭包（Codex，M2.Z3）

接手实时 A51/A52。A51 的五个申报源码/测试身份与 A52 核对一致，条件 f5a1e45febb65ca28f2c3b1772e24173cb04aab87d5d6f7868ec2f759dbad519，预算仍 202304 单位、1740 秒、1760/1780 截止；A52 的默认纯 CPU 2329 passed、5 deselected、零 MLX 导入属于工程证据，不是运行授权或能力验收。

A52 退回补两项：任务明确要求的 SKIP_NORM_SQ_BELOW 放宽真实变异被 worker_skips_projection 替代，必须补介于原/变异阈值之间的负内积例；按此前 M4 首跑失败教训，新增真实登记 M2d 起点的完整 CPU 来源准备调用链闭包（schedule compat、relabel、coverage/history），不得只靠静态接线。原报告与原变异保留，追加修订报告。A51 暂不验收，未写 M6 身份、未创建 RunStore、未启动训练。A50 判读和科学参数不变。当前一级主责为 Codex，真实预算内运行须待此闭包通过后单次登记发布；完整投影新增单位仍需用户授权。


## R20261014-Relay-Codex-19：M6闭包通过、十文件身份登记及单次运行启动（Codex，A53）

A52修订由gemini-8v4a独立交付，原grok47证据保留；五种真实变异含跳过阈值放宽全部被捕获，默认CPU2329通过、5 deselected、零真实MLX。一级补充实际run_memory(action_preservation_mixed_tailself_halfproj=True)入口CPU探针：由入口真实调用halfproj schedule兼容、_prepare_relabel（onestep_lineage=True来自分支绑定）、production_windows与M2l reuse闭包，中央账本以mode=ro替身消费，在pilot_manifest/创建运行/写报告/加载模型之前哨兵停止，输出文件与模型更新均0。独立报告的helper链和一级的实际入口证据分开保存，不把前者称成直接运行了worker。A51/A52按CPU工程范围验收。

一级登记halfproj-identity.json（10必需文件，manifest SHA a7359170a7dd031e533a79773f075fbbb8aa694dd5439bf69431bb14f602e007；condition f5a1e45f…；design acca1d7d…；config 0169cc73…）。原A50草案字节和旧M5等身份不改；run_authorized仍false，单次授权写Relay A53 params v1。启动前现算源码与所有输入哈希、锁空闲、实验ID未用，可用45.86GiB/磁盘3302GiB；今日中央已预留7140/21600秒，余量足本次1740预付。

A53通过relay exec托管现有CLI train-action-preserved-mixed-tailself-halfproj-memory，一次实验m2nm6-halfproj-20261014，200更新，202304单位/1740秒/1760·1780；no_retry。启动脚本用独占创建launch-once.json避免误重启。当前只登记与启动，尚无模型结论，不晋升。A54独立只读复核→A55按A50四支判读已排；完整投影新增单位仍未授权。


## R20261014-Relay-Codex-20：M6第(d)支，半间原始梯度投影无实质改善

A54独立32项与最终331280冻结元通过；五门2过3不过。M6零状态3729/池1883/动作377+0.035558、359+0.174890/重建544，历史0.157539；相对M5几乎不变，归A50第(d)。55/200步投影，投影步移走均值1.669%，全200步均值0.459%；支持当前原始梯度投影无效，不证明所有更新空间方向无冲突或结构不可能。D仍唯一既有五门候选，历史未解决；不晋升重试调lambda。完整(ii)新增10400单位需用户批准，212704/1740/1760/1780为预算申请，尚未实现登记或运行。限制：仅开发逐格重建、其他聚合复算，缺原逐查询/映射及独立运行时持锁日志。详见E29-halfproj/A55-interpretation/A55-interpretation.md。


## R20261014-Relay-21：用户批准完整投影预算，登记 M2n-M7 设计（Claude，A56）

用户 2026-10-14 批准：“A56 新增 10400 单位，总预算 212704，秒数 1740/1760/1780 不变”。据此登记 M2n-M7（协议 m2m_n_mixed_history_tailself_fullproj_v1，登记文件 artifacts/reports/relay-claude-20261014/M2NM7-fullproj-registration.json，sha256 0a1f8dd0…）。相对 M2n-M6（f5a1e45f…）的唯一因素：历史半内 CE 与 KL 梯度分开反传，CE_h 与 KL_h 冲突时把 CE_h 从 KL_h 方向投影掉（KL_h 不动），其余包括 M6 对 g_s 的投影、冻结尾部自循环块、门、种子、秒数全部不变。教师 logits 复用，学生历史半多一次前向与反向，每次更新加 52 单位，共 212704。必须附真实起点的完整 CPU 准备链路探针（Relay-13 教训）。预固定判读 (a)–(d) 见登记文件；结构性扩容需要另行用户批准。任务链：A57 实现 → A58 不同作者 CPU 复核 → 一级身份登记 → 有界运行 → 独立复核 → 一级判读。


## R20261014-Relay-22：M2n-M7 归第 (c) 支，投影族关闭；推荐历史旁路单元（Claude，A61）

A59 一次运行（run 6e0ef7fc…，212,704 单位/200 更新/235.8 s，不重试）经 A60 r2 独立复核（musespark-8k4q，对照值全部由脚本从原报告读出并附 sha256；r1 因对照表手写失实被打回，r1 产物保留）。M7 动作 1 步 377、ΔNLL +0.009133，4 步 359、ΔNLL +0.032755，两项都过门；零状态 3653（变化 107/127）、换名池 1821（126/140）不过门；重建 544；历史屏 0.062/0.026。按登记归第 (c) 支。历史半内投影 199/200 步触发，cos(g_CEh,g_KLh) 均值 −0.66，平均去掉 g_CEh 的 66%；半间投影 74/200 步，平均只去掉 0.8%。

结论：M5/M6 残余的动作伤害沿 g_KLh 方向，历史半内投影消除了它（有干预证据）。在共享尾部 + 冻结读取的形式下，存储历史的写入方向与保动作在一阶上大部分相反；去掉冲突分量后，历史屏从 0.158 降到 0.062，迁移也低于 λ_h=0 对照（3863/1956）。迁移下降不经由与 g_s 的一阶冲突，具体来自优化器共享还是函数空间漂移，本次数据不能区分。即使历史半对迁移完全无害，同配置 λ_h=0 的零状态 3863 仍低于 3892，所以投影族与同类优化器微调都无法产出五门候选，投影族关闭。不晋升、不重试、不调 λ/门；D 仍是唯一五门候选；按 Z2 不称根本不可能。

下一路线（任何训练都需用户另行授权）：推荐 P1 历史旁路单元——从 D 出发新增 k=128 个 GRU 单元，原参数全冻，动作通路按构造不读新单元，记忆读出改为冻结 head 作用于 h_tail+h_new，初值逐位等于 D；新增 160,256 个参数（总数 553,488），属参数扩展，需用户批准；单位预估约 202,304，秒数 1740/1760/1780。本轮只派 CPU 静态可行性（不跑 MLX、不训练）与独立复核。(iv) 自由想象历史降为后备（存储位置不变，冲突仍在）；分离优化器状态诊断不推荐（上限约为 λ_h=0 对照，仍不过门）；也可以收束披露。详见 [A61 判读](artifacts/reports/E30-fullproj/tier1-decision/A61-decision.md)。


## R20261015-Relay-23：P1 历史旁路单元 CPU 可行性通过，登记草案待用户批准（Claude）

A63（opencode-a1b2）纯 NumPy 静态分析、A64（musespark-9x4q）用不同种子与样本独立复核，均已验收：从 D 出发新增 128 个 GRU 单元，原 GRU 行读新单元的列固定为 0，prior/posterior/decoder 只读 h[:, :256]，记忆读出为冻结 head 作用于 h_tail+h_new。四项性质都逐位成立：零初值时新单元恒为 0；动作通路逐位等于 D；起点读出逐位等于 D；随机扰动新参数后动作通路仍逐位不变，只有读出改变。A64 的反例显示，让一个原 GRU 行偷读新单元，零耦合核验就会失败，说明检查有效。零初值下 reset/update 门的新参数一阶梯度为 0，读出位置已打破单元对称，不需要改初始化。成本：新增参数 160,256（总 553,488）；单位方面，152/更新含在线教师，P1 不需要教师（KL 对新参数梯度恒 0），合计 171,904+200×76=187,104；每步计算量 1.384 倍（A63 的 1.414 重复计了 Wx_new，A64 指出，一级复核属实）。另记：A64 结果文件中 boundaries/flop_recheck/units_source_lines 三节不是其脚本生成，数值由一级独立复核成立。登记草案 artifacts/reports/relay-claude-20261015/M2NP1-bypass-registration-draft.json（run_authorized=false），预固定判读 (a)–(d)，其中任何动作指标偏离 D 都判实现缺陷。参数扩展与一次 187,104 单位/1740 秒的有界运行需用户批准；批准前不实现入口、不登记身份、不运行。


## R20261015-v8-align：v8 目标架构对齐对 AinerZero 的影响（Claude）

用户 2026-10-15 决定按统筹推荐对齐 AnimeWorld Zero v8 RFC，记录为 AWZ 的 D-006 和 ADR-0010（`~/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0010-v8-alignment.md`）。这次只写文档，对本仓库的影响：

1. **不动本仓库**：不改源码，不改在途登记，不搬 `artifacts/`。halfproj、fullproj、P1 等登记的文件身份保持有效。
2. **Brain-0**：只是 `configs/brain0.yaml` 这份配置名，不代表已训练的能力。实际训练过的是 `pilot_shared_symbol_v1`（393,232 参数）。最好候选 D（run `96b72328…`）五项门通过、历史门失败、未晋升。
3. **命名**：v8 的课程段 W0–W7 改称 G0–G7。本仓库目前处在 C0 阶段（G-pre），G0 还没开始。G 段只是路线标签，进入任何一段都要在本仓库预登记门槛并做独立评测。
4. **AinerForge**：训练系统独立成仓（`~/AinerWorkFlow/AinerForge`，现在只有 F0 设计文档）。它用 `.apack` 旁注清单**只读**登记本仓库的数据和检查点，不写本仓库的 `artifacts/` 或 RunStore。本仓库的运行仍以本仓库的 CLI、共享锁、RunStore 和预算为权威。
5. **跨仓扩展**：接 AWZ 对象和视觉观察需要的契约扩展仍是 AZ-X1–X5，需要时在本仓库另开任务登记。D 候选在 AWZ 上首考（E-1，经 `awz_symbol8_v1`，不训练）需要本仓库实现一个只读读取器，也要另开任务。
6. **P1 历史旁路单元**：仍待用户批准，和 v8 对齐没有冲突。它的「旧参数全冻、新单元零耦合、起点逐位一致」正是以后接新模态的扩展范式。

本次没有运行模型，没有训练，没有改变科学参数或门。


## R20261015-pause：用户决定暂停 AinerZero 训练，资源转向世界系统（Claude）

用户原话：「A：暂停 AinerZero 训练，资源全部转到世界系统。它的检查点和证据原样保留，以后随时接着做」。

背景：用户澄清了分层架构。AinerZero 是独立的世界脑；AnimeWorld 是世界系统（用户称"世界模型"），可以先由现有 LLM（DeepSeek、Claude、Gemini、Codex 等）驱动建世界、出动漫。近期要训练和进化的是世界系统，不是世界脑。各层通过带版本号的契约连接，各自进化、互不影响；渲染底座和训练底座（MLX → CUDA/ROCm）都可以插拔。

落实：
1. **暂停**：不新增 AinerZero 训练、运行登记或运行授权。P1 历史旁路单元（R20261015-Relay-23 的登记草案）搁置，未批准、未运行。
2. **保留**：所有检查点（含 D 候选 `artifacts/pilot/pilot-b4e75e9b4a1a4ba086118d37017b2a1a/checkpoints/96b72328-…`）、登记文件、报告、失败证据、RunStore 和中央账本原样保留，不删除、不移动、不改写。
3. **暂停时的状态**：没有在途运行，`artifacts/locks/m0-worker.lock` 无人持有。接力台 ainerzero 项目上只剩 A65（reported）和 A66（ready），两者都是为 AWZ CCIP 身份校验做的纯 CPU RunStore 可行性探针，不训练、不导入 MLX，服务于世界系统，所以不挂起。
4. **恢复**：需要用户另行决定。恢复时从暂停点接着做：D 仍是唯一过五门的候选，历史记忆问题未解决，P1 是推荐的下一条路线。
5. **不变**：AinerZero 的工作规则、锁、RunStore 和预算守卫不变。世界系统如果要借用中央 RunStore（如 CCIP），仍按原规则走。

已同步：COORDINATION.md「当前交接」首行、CLAUDE.md 首段、AWZ RESEARCH_LOG D-008。

## R20261015-D011：三个系统与名称约定（Claude，记录指针）

用户 2026-10-15 决定（AWZ RESEARCH_LOG D-011，原话「好的按照你的123执行」）：
- 顶层是三个系统加共享底座：制作脑（影视创作与控制，代码归 AinerHub）、世界系统（AnimeWorld，负责运行世界）、世界脑（AinerZero）；
- “世界模型”只指 AinerZero，AnimeWorld 改称世界系统。

对本仓库的影响：只有名称和接入位置。训练暂停（R20261015-pause）不变，不新增运行、登记或授权，源码和证据不动。世界脑将来按技能、通过与 LLM 共用的技能接口接入世界系统（观察 → 任务与约束 → 提案 → 世界校验执行 → 实际结果）；现有观察仍是 8 格符号、动作 0–3，不能宣称已能控制三维人物。总文档：AnimeWorldZero/docs/NORTH_STAR.md；决定：AnimeWorldZero/docs/adr/ADR-0011-three-systems.md。


## R20261015-v9：用户决定采用 v9 目标架构（Claude 记录，D-016）
- 用户原话：「现在你首要任务是之前框架任务先放下 … 架构要调整最新架构 架构一定要最优后面才不会走弯路 … 理解并实现完整落地v9架构」。
- 目标架构：`ARCHITECTURE_V9.md`（NeuroGeometry 内核 + 互补记忆 + H-JEPA 式分层潜在动力学 + 主动实验）；现有 RSSM/GRU 降为快速动力学基线与回退，D 候选与全部检查点、失败证据只读保留，P1 历史旁路保留为消融候选。
- **训练暂停（R20261015-pause）不变**：本决定只启动 P0（契约、接口与假实现、基线冻结清单、研究注册表），全部纯 CPU、无训练、无下载。P2 起每一级训练需用户另行批准预算。
- 跨系统决定见 AWZ `docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`，落地任务见 AWZ `docs/design/V9_LANDING_PLAN.md` 第 4 节（ainerzero.V9.*）。

## R20261016-T4：用户批准 T4 教师环境与下载（Claude 记录）
- 用户原话：「批准 T4」（2026-10-16 约 01:40 +03）。批准对象：ainerzero.V9.T4。
- 下载前许可核对（2026-10-16，浏览器打开 HF 页面）：
  - `dgrauet/vjepa2-mlx` 代码 MIT，README 写明 "Preserves Meta's upstream MIT license"。
  - 权重 HF `dgrauet/vjepa-2.1-vitl-mlx`，许可字段 mit。文件：encoder.safetensors 1.22 GB、predictor.safetensors 91.9 MB。由 mlx-forge 转换自 Meta 的 `vjepa2_1_vitl_dist_vitG_384.pt`。Meta 官方 HF 卡 `facebook/vjepa2-vitl-fpc64-256` 的许可字段也是 mit。
  - `apple/coreml-depth-anything-v2-small` 许可字段 apache-2.0，含 F16/F32 及量化变体共 8 个 mlpackage。
- 批准范围：
  1. 在隔离环境装 `vjepa2-core-mlx`。Core ML 运行时 `coremltools`（Apple 官方）作为运行 mlpackage 的必需依赖，装在同一隔离环境。
  2. 下载上面的 V-JEPA 2.1 ViT-L MLX 权重。
  3. 下载 Depth Anything V2 Small 的 F16、F32 两个 mlpackage。
  4. 在 M2 Max 上做数值检查和推理基准。
- 不在批准内：
  - VGGT（T6：CC-BY-NC-4.0 待许可审查，还需 PyTorch）。
  - PyTorch，因此会拉入 torch 的 `[parity]` 额外依赖也不装。
  - 从 Meta `.pt` 自行转换权重。
  - V-JEPA2-AC、任何训练、写入 T2 缓存（T2 验收后另发集成卡）。
- 预算：
  - 下载总量 ≤ 2 GB。
  - GPU 推理基准墙钟合计 ≤ 30 分钟，单次 ≤ 10 分钟。
  - 一次只常驻一个模型；进程内存峰值超过 32 GB 立即停。
  - 这是推理基准，不是训练。训练暂停（R20261015-pause）不变。
- 落点：
  - 环境放 `envs/teachers/`，venv 用 `.venv-*` 名，已被 .gitignore 忽略。
  - 权重和 HF 缓存放 `artifacts/teachers/`，已忽略。
  - 报告放 `reports/V9-T4/`。
  - 不改 `src/`：T2 正在用 `src/ainerzero/v9/teachers/`，避免同目录冲突。

## R20261016-frontier：用户决定把前沿技术增补全部写入架构与任务库（Claude 记录，AWZ D-017）
- 用户原话：「全部写入」（2026-10-16 约 02:30 +03）。所回问题：要不要把 `docs/research/V9_FRONTIER_COST_SURVEY.md` 写进架构和任务库——零下载项直接写入 ARCHITECTURE_V9 与任务协议，需下载项写成草稿卡等批准，T6 一并改成 DA3。
- 写入范围：
  - 零下载项写入 `ARCHITECTURE_V9.md` r3：
    - 解析规范化（用已估位姿换到重力对齐的智能体坐标系）；
    - RLT 停帧 token 去重；
    - Muon / 多步滚动 / epinet 对照臂；
    - 记忆候选：Titans、Nested Learning、CUT3R、SlotSSMs；
    - 多教师合一；
    - S5 的 REPA 式对齐。
  - 需下载或安装的写成草稿卡：
    - T6 由 VGGT 改为 DA3-Small/Base（Apache-2.0）；
    - SAM 2.1 与 TAPNext/BootsTAPIR 对象/点跟踪教师；
    - MapAnything Apache 版；
    - Genesis World 物理真值；
    - DINOv3 自定义许可审阅。
- 不变：
  - 本决定不批准任何下载、安装、训练或新的 GPU 运行；
  - 训练暂停（R20261015-pause）、T4 批准范围（R20261016-T4）、各草稿卡的批准门槛都不变；
  - 论文加速倍数只作假设，采用前必须本项目 A/B，并照常报告 M2 记忆干扰诊断。

## R20261016-review-rule：一级验收改为“非作者复核建议通过后作者可办”（Claude 记录，AWZ D-018）
- 用户原话：「改」（2026-10-16 约 04:05 +03）。
- 所回提议：非作者二级复核建议通过后，由一级作者直接办验收，不必等另一位一级。
- 规则见 `COORDINATION.md`「双统筹如何避免冲突」第 6 条。本仓库受影响的卡：ainerzero.V9.T1（补派复核）、ainerzero.V9.A1（架构审议改由二级独立审议）。


## R20261016-Codex-v9-peer：r3平级审议需修订

**方向同意；当前r3不足以冻结为训练协议，需r4修订后平级复核。** 本轮审的是实际r3，不是卡面旧r2。仅只读审议与原始文档身份登记，无CPU模型实验、无训练、无RunStore或预算登记；原D/M2失败完整保留。待修订不是否定结构化状态/地图/分层路线，也不是恢复旧RSSM主线。


完整逐节结论：[审议报告](reports/V9-A1/codex-r3-review-20261016/review.md)。本轮不改架构原件，不恢复训练。

## R20261016-arch-first：先改写架构与任务落地，暂不动代码（Claude 记录，AWZ D-019）
- 用户原话：「先不要动代码 先改写架构  架构方案和任务落地 再开始实现代码任务」（2026-10-16 上午）。
- 上下文：用户提供 v10 架构验证文档（存档 `docs/research/AinerZero_v10_Architecture_Validation.source.md`）。
- 本仓库暂停的实现卡：V9.A2、B2、G3、T2、T4、T8。架构 r4 走 `ainerzero.V9.A5`，合并 Codex r3 审议的强制修订与 v10 验证层；复核走 A6。

## R20261016-SkillProposal-B4/B5：独立核对发现泄露通道（Codex）

B4 的 `SkillProposal/v1` 契约和 B5 的正向复核报告已交回，但本轮一级只读反例使验收条件不成立：从有效提案只改 `expected_outcomes[0].quantity` 为 `world_id` 或 `hidden_contact`，schema 都放行，参考门禁都返回 `accepted`；`params.worldId` 与 `params.entityID` 也通过 schema。B5 未覆盖这四种写法，且只是读取作者保存的退出码，未按任务要求真实复跑作者脚本。B4/B5 均已打回，原报告保留；作者须修订并补真非零/破坏对照，随后由非作者重新核对新 SHA。此裁决仅针对 CPU 契约，不构成世界脑学习能力或训练授权。

## R20261016-SkillProposal-B4-r2：键名拦截仍可绕过，B4/B5 再退回（Claude）

B4 r2 已补上 Codex 指出的 camelCase（worldId/entityID）与 quantity 两个通道，B5 复核建议验收。一级复核发现：world_id_key 正则只覆盖蛇形全词和 World/Entity/Scene/Event 四种驼峰，OBJECT_ID、Entity_Id、ENTITY_ID、entity-id、world.id、objectId、actorIds、instanceId、agentId、gtObjectId 等仍能通过。

不过这不构成直接泄露，因为 params 还要过能力登记的封闭 param_schema。真正的缺口在登记条目核对：没有拦截像世界 ID 的属性名。

处理：
- B4 出 r3：核对器按“小写、去分隔符”规范化后判定，同时覆盖提案任意层级和登记条目的 param_schema 属性名；每种拼写配反例与破坏对照；并修正 --suite 原地删除重写夹具的问题。
- B5 退回，r3 交付后重新复核，必须做系统化的键名变体探针。

## R20261016-evidence-hygiene：复跑不得改写交付证据（Claude，COORDINATION 规则 8）

14:54 我复跑 B4 的 `--suite` 时，另一进程也在同一目录运行。脚本会对交付夹具先删除再重写，结果我方出现 21 条假失败，交付文件被临时删除；对方跑完后逐字节恢复，没有留下损伤。P3-E8 的核对器写死了仓库绝对路径，复制到隔离副本运行时仍会写回原交付目录；内容幂等，45/45 SHA 仍然一致。

规则（COORDINATION 第 8 条）：
- 核对脚本默认只读交付物，生成的东西在临时目录里逐字节比对；
- 原地重新生成必须显式加 `--regenerate`，复核和验收不得调用；
- 不写死仓库路径。

新卡从派发时起执行，旧脚本在下次修订时顺带改正。


## R20261017-CF-landing：角色优先兼容扩展与任务工作台落地候选

- 用户新指令：“好的那工作台和方案落地”；已明确工作台为“现有任务工作台（推荐）”，即 AinerRelay。
- 主责Codex；文档二级proposal_writer；非作者character_inventory。只做正式设计/逐卡队列/当前入口，发布待本轮非作者核对，作者不自行验收。
- 扩展CF-r1-20261017兼容V9-r5-20261016，见 [ADR-0013](../AnimeWorldZero/docs/adr/ADR-0013-character-first-production.md) 和 [落地计划](../AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md)。原baseline JSON、主架构、旧PROPOSAL/REVIEW/DECISION与失败证据不改，改前字节/摘要另存 [本轮报告目录](reports/character-first-landing-20261017/REPORT.md)。
- 保留Hub唯一持久世界、AWZ运行/曲线/接触权威、Hub worker只读消费、AinerZero独立研究/训练暂停与M2常设对照；明确情绪/口型同部位唯一blend owner，solve/adopt/render按版本拆无环图。
- 主责本轮live读取：A8r2+A12已登记accepted，范围仅CPU合成契约层及R1–R4/F2/F4落纸，Event/snapshot仍未采用候选；T1r3+T18亦accepted，缓存仍未采用候选，真实加载/ModeGuard/Forge消费者未实现。原baseline第3节保留出版时失败快照，不倒改旧失败；不能由新正向报告外推来源真实性/内核输出/消费者或能力。
- 当前入口与任务分层可见不等于代码放行：A10与原业务依赖/paused保留，实施卡仍受门；运行预算另冻结。本次没有产品实现/Schema/测试/模型/训练/渲染/下载安装/付费/提交推送。在线登记由主责另办，真实卡ID与依赖以其后续registration报告为准。
