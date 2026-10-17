# CF-r1-20261017 设计发布决定

- 收尾日期：2026-10-18（Europe/Istanbul）；主责与本文件唯一编辑负责人：Codex。
- 发布任务：`awz.CF.A3`；文档交付：`awz.CF.A1`；非作者复核：`awz.CF.A2`。
- 出版修订：r2。r1 条件发布字节保存在 [publication-r1](revision-r2/publication-r1/publication.json)，没有生效。
- 用户已明确要求“工作台和方案落地”，并选择现有 AinerRelay 任务工作台；本次“继续”恢复该项收尾。
- 本决定及 [publication.json](publication.json) 是供 A2 非作者检查的具体发布对象。**仅在 A2 明确建议通过、必修项关闭，且 A1/A2/A3 均为 accepted 后生效。** 条件未满足时不视为已发布。

## 决定内容

条件满足后，采用 **CF-r1-20261017** 作为 **V9-r5-20261016 + v10 工程验证层** 的角色制作能力兼容扩展。具体正文为 [ADR-0013](../../../AnimeWorldZero/docs/adr/ADR-0013-character-first-production.md) 与 [逐卡落地计划](../../../AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md)，精确字节由 [r2 source-after.json](revision-r2/source-after.json) 和 publication 清单绑定。

r2 仅修正落地计划复用旧 A3 段的两行：能力标签按现有卡为 code，直接前置精确列出原 A2/A10 及新增三份 CF 验证前置。原计划、r1 清单与负面发现均保留；没有借勘误改变任务或运行授权，见 [r2 报告](revision-r2/REPORT.md)。

1. 生产主线是 Hub 表演意图/编辑、跨工具编译、AWZ 准入与运行求值、现有 Hub Blender worker 和独立审片。持久世界、运行状态、角色身份、学习信念继续按原职责各有唯一权威。
2. 第一批角色目标包含身体、面部、眼神、手势与对白同步及可编辑回放；再扩展接触、双人编排和跨镜头验收。固定角色资产与 IK 不自动证明自然度或商业质量。
3. World Compiler 只管理跨工具任务及派生缓存。solve/adopt/render 分版本并保持无环；候选不写真值。情绪与口型重叠部位采用唯一的已登记混合控制者，不新增隐式 priority/weight。
4. 29 张 CF 任务落实到既有工作台：本轮文档/复核/发布 3 张，后续 13 对设计或实现及非作者验证。仅合同与消费者映射设计可在发布后领取；24 张产品实现及运行验证卡保持 blocked，各自保留 A10 与业务前置。
5. 原 `awz.P3.A3` 仅追加 `awz.CF.B2`、`awz.CF.C2`、`hub.CF.B2` 三个前置，原依赖顺序、状态、文件范围及参数不变。其余原卡及项目关联目录不改；模块成熟度与暂停状态不提高。

## 冻结、回滚与边界

原 baseline JSON、主架构、ADR-0012、原发布快照及旧候选/失败证据保持原字节。旧 r5 身份按其 published-inputs 快照解析；本轮 live 索引和落地计划的兼容增补另记新摘要，不声称仍匹配旧摘要。

E3/A2、120Hz、用户锁、来源与分区政策、ADR-0007、观察隔离及 M2 常设对照保持。AinerZero 训练继续暂停；`awz.V9.A10` 保持 draft。本决定不授权产品实现、模型/训练、渲染、下载、付费或新的运行预算。

现有任务工作台恢复原已部署版本，没有部署新服务源码或启动 runner。元数据核对与看板生成分别记录，不能作为产品代码测试、真实角色、视觉或性能验收。

本次非作者意见见 [INDEPENDENT_REVIEW.md](INDEPENDENT_REVIEW.md)；最终生效状态由 A3 在线记录及后续 release-receipt.json 取样证明。正文冻结后只追加发布回执，不回写被审字节。
