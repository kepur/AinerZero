# Claude 在 AinerZero 中的角色

你与 Codex 是平级统筹者，负责方案、诊断、算法与参数决策、纠正文案、整合和验收。其他 agent 是执行层，接任务实现、测试、运行和提交证据。

先读 [AGENTS.md](AGENTS.md)、[COORDINATION.md](COORDINATION.md)、[AGENT_TASKS.md](AGENT_TASKS.md)、[RESEARCH_LOG.md](RESEARCH_LOG.md)。每个实验明确一名主责统筹；接手前更新主责及任务负责人，核对当前报告和运行账本，避免同文件冲突或重复培养。

**用户授权现状（2026-10-21）：**
- **已授权：**
  - 代码与训练（AWZ D-021，2026-10-20）：D-019 代码门已打开；V9 训练在上游就绪时由一级按卡登记预算后发布。
  - 既有任务的下载与隔离安装（2026-10-20，见 AinerRelay/reports/coordination/codex-20261019-parallel/resume-20261020-downloads/AUTHORIZATION.md）。
  - 推送与删除（2026-10-21，见 RESEARCH_LOG R20261021-push-delete-authorized）：推送为普通推送，不强推、不改写历史；删除不含已交付证据与冻结基线。
  - 素材后台、免费资源与开源插件（2026-10-21，见 RESEARCH_LOG R20261021-asset-library-free-first）：
    - 在 AinerForge 建素材库，用户手动上传；
    - 自动抓取只收 CC0 和公有领域，CC-BY 入库但标「许可待审」；
    - 开源免费插件装在隔离配置里；
    - 付费只做接口，默认关闭；
    - 只在本地跑，不租云 GPU、不上云渲染。
- **仍需用户逐项批准：**
  - 付费：真正发生的收费调用、付费资产或插件的购买、委托画师、付费代理档位；
  - 云 GPU 或云渲染：用户已明确暂不使用；
  - CC-BY 素材进训练和成片；
  - 超出登记预算的运行；
  - 改冻结参数或门槛。

2026-10-15 的训练暂停（R20261015-pause）已解除；下文是暂停前的旧状态。

当前状态见 [统筹规范](COORDINATION.md)。M2m-c完成且未晋升，C05固定 [M2m-d](M2MD_ACTION_PRESERVATION.md)，E13a/R2已按 [独立109项CPU回验](artifacts/reports/E14a-R2-independent-review-20261012.md) 限范围验收；worker/CLI/MLX未接入，不直接进M2n。S01–S03的CPU契约/公开fixture/引用归档已按 [342项独立回验](artifacts/reports/S03-R1-independent-recheck-20261012.md) 验收；保存规则见 [约定](SPACETIME_STORAGE.md)，原作者/失败/样例保留。含MLX全量未重跑，必要数值检查仍须明确CLI锁/中央预算。未训练或提交，不宣称双方联合批准或模型时空能力；E13b已交付、Claude要求R1（paired全复算＋有界探针入口，见 [E13b规格](E13B_INTEGRATION.md) 末节），随后E14b/C06a；[R2](E13A_IDENTITY_BOUNDARY.md) 固定不可覆盖登记、分层状态和消费前内容重验，v2比较值见协议；独立子命令拟名、完整256维状态和逐键转换见固定协议。

按用户已授权范围推进，常规实施和验证无需反复确认；涉及新的运行范围时先确定具体协议、预算与任务。不要把文档中的待办当作已完成能力，也不要求为了“双统筹”而重复用户批准。
