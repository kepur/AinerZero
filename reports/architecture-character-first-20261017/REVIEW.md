# CF-REVIEW-20261017 非作者候选方案审阅

- 领取：2026-10-17；审阅者与本文件唯一编辑负责人：`character_inventory`。
- 非作者关系：被审方案由 `proposal_writer` 整理；本审阅者仅做过只读证据盘点，未编辑方案、清单或 CLAIM。
- 唯一写入范围：本文件；其余输入只读。状态：本次候选方案审阅完成。
- 最终被审 PROPOSAL.md（200 行）SHA256：`8fa626e72a42c442d85827ed8dd77461fa74654cbe6a61c2e31b314c5c745bbb`。
- 被审 INPUT_MANIFEST.json SHA256：`770299eb98012fd57ba5c02e2a2b550e0c31dc5e4a12f9055181850df3010997`。
- 范围：D-012 职责、消费者缺口、时钟/音频/控制权、ADR-0007、来源隔离、候选任务与授权边界、清单文件身份；只读直接抽查源文件，不运行测试/Blender/模型/服务，不改 Relay。
- 初读版本为 197 行、SHA256 `925e929dc42acba3aa65e15c6d33710c9b378da849621a5d0f0bb74d625679e7`；收到主责冻结通知后全文重读最终 200 行，以下结论只对应最终版。

## 结论

**建议可作为候选方案，交 Codex 最终架构审议；无阻碍性必修项。**
这不发布现行基线，不接受实现或视觉能力，不开放 A10、训练、下载、渲染或其他运行预算。
文档内“待非作者审阅”是被审字节中的时间状态，本报告追加最终审阅结果，不回写原件。

## 身份与只读核对

- 逐一读取 INPUT_MANIFEST.json 的 26 个 input_files：26/26 当前内容 SHA256 和 size_bytes 均匹配，0 缺失、0 失配。
- 附件原件大小 20249 字节、SHA256 `bf58bf7ea4ed69a205d798a9c44f37871a0022a672296ef72aa41155c587cc86`，与 attachment 项匹配，未改 Library 文件。
- AinerZero、AnimeWorldZero、AinerHub、AinerRelay 的当前 HEAD 分别与清单相符；AinerForge 仍无可解析 HEAD，与清单失败状态相符。
- 不用当前 dirty 清单覆盖作者时间取样；HEAD 只是提交基点，26 个文件哈希才是本轮指定输入的内容身份。未主张工作区原子快照。

## 直接检查的关键断言

| 被审位置 | 独立读取的源证据 | 判读 |
|---|---|---|
| PROPOSAL 61–64、73–75 | [ADR-0011:112](/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0011-three-systems.md:112)，权威表至 122 行 | 保留 Hub 持久、AWZ 运行、AWZ 身份/风格、单一变更信封及复用 Hub worker；外层 DAG 没获得新世界写权。 |
| PROPOSAL 25、103–106 | [performance_contract.py:8](/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/production/performance_contract.py:8)、49–56、1027–1110 行 | 校验器不生成/执行/渲染；现行合同无 priority/blend weight；pending 不可执行。提案没有把 fixture executable 误当真实注册。 |
| PROPOSAL 26、153 | [motion.py:204](/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/worldmodel/motion.py:204)，尤其 213、217 行 | 实际代码确实是毫秒双闭区间与角度累加；第 0 阶段列出半开 tick、显式混合与单写者适配，未称已完成 Composer。 |
| PROPOSAL 27–30、154–155 | [humanoid_rig.py:120](/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/director/blender_worker/loaders/humanoid_rig.py:120)、[Curves.tsx:6](/Users/mac/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-studio/src/stage/Curves.tsx:6)、[blender_adapter.py:67](/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/render_backend/blender_adapter.py:67)、[eevee_slice.py:137](/Users/mac/AinerWorkFlow/AnimeWorldZero/tools/blender/backend/eevee_slice.py:137) 与 198–209 行 | rest-space 姿态应用、只读机位曲线、未调用统一 worker、GLB 清场后代理球的描述均准确；真实角色与曲线消费者作为阶段交付缺口保留。 |
| PROPOSAL 78、115–116、128 | [ADR-0007:5](/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0007-render-determinism.md:5)，至 8 行 | 当前禁止历史帧依赖；状态/事件与图像的不同确定性口径保留。有状态物理的检查点要求没有给历史后处理豁免。 |
| PROPOSAL 32–33、134–135 | [backend_capabilities.v1.json](/Users/mac/AinerWorkFlow/AnimeWorldZero/contracts/backend_capabilities.v1.json)、[session.py:53](/Users/mac/AinerWorkFlow/AnimeWorldZero/tools/gate_id/ccip/session.py:53) | Blender line/normal/motion 未支持、真实 CCIP 恒阻断均为当前代码状态；缺通道和假评分不会被候选方案升级。 |
| PROPOSAL 98–106、136–137 | [CHARACTER_PACKAGE_V2.md:33](/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/CHARACTER_PACKAGE_V2.md:33)，至 51 行；[ARCHITECTURE_BASELINE.md:32](/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_BASELINE.md:32)；[ARCHITECTURE_V9.md:352](/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md:352)，至 363 行 | 120Hz、音频身份、单一写者与既有合同一致；真值 ID、隐藏接触、完整缓存、封存 QA 均不得成为学习输入。external_derived 默认拒训及训练暂停保留。 |

## 架构与阶段判读

- 阶段 0→5 先合同/消费者、再真实角色竖切、多轨表演、共享接触、完整 QA，最后可选增强；CPE 与基础 TACE 没被推迟到动作优化之后。
- 真实接触只由 AWZ 核准的运行结果产生；worker 的 retarget/IK 为候选，风格化/重定时后重新校验，未授予 Blender 与 Bullet 同时双写。
- 缓存绑定权威身份、依赖、seed、后端/物理配置/检查点，命中仍重验权限；早期接触改动沿闭包传播，无有效检查点扩大重算。未把 blob 去重等同分区或资格共用。
- 第 141–158 行明确 CF 只是本地候选任务、逐阶段保留 A10 与业务依赖、非作者验证及预算；不能据此启动实现。
- 第 162–179 行要求预登记数值/人工门和坏对照，区分文档、消费者、真实资产/运行、视觉能力；没有把 15 秒题目包装成商业质量承诺。

## 非阻碍性建议与复核限制

- 正式 CF-C01 卡面宜把面部情绪与音频口型重叠部位的唯一 blend owner 列成具体交付；现有 FACS 会共同写嘴部，分轨本身不能消除写者冲突。提案 101、103–105 行已提供原则，不阻碍本轮候选整理。
- 第 51–52、62 行的反馈是“候选→AWZ 校验采用→核准结果”的架构流程；正式 CF-C02 单次任务 DAG 须拆 solve/adopt/render 节点和版本边界，不能原样把反馈环当 DAG。现稿不提供具体任务图，作为后续落卡细化，不阻碍候选整理。
- 正式消费者实现时将信息隔离落实为基线要求的“同观察异未来”反例与实际资产加载路径检查，不能只复用本轮文档核对。
- 外部 HY-Motion/Audio2Face/depsgraph 线上事实未由本审阅者联网复验；只确认提案明确归因主责查证、未宣称本机运行。主责最终审议负责其官方来源证据。
- 实际操作仅 bounded 文件读取、文本定位、SHA256/字节数核对、Git HEAD 读取及写本 REVIEW；模型/优化/环境动作/渲染/CPU 测试/新增 RunStore 与预算预留均为 0。
