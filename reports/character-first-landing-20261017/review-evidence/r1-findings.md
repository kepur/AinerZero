# CF-LANDING A2 r1 必修发现

- 发现者：非作者 `character_inventory` / 正式持有者 `cf-reviewer-20261017`，2026-10-18。
- 状态：`request_changes`，仅指本条文档/线上原卡对齐；不修改被验物，不交终报、不办理接受。
- r1 source-after SHA256：`cf2ee745a8d6174c0d8e1dc75e80c0213a78847a0e9e03a0264d94fd13fee3d4`。
- r1 CHARACTER_FIRST_LANDING_PLAN.md SHA256：`f4402743cd5c5da1e281b53557d3f78fec95dbc002ed50cb170f45bd568c0137`。
- r1 ADR0013 SHA256：`15f5a43b6ab027634674a2cfeaff68e4c90b19bf5d35860a52862e118a83aa4c`。
- r1 DECISION SHA256：`af40a3ea284e4506bee8b3265585290eaa80cdca630a5cd537aa10dcc329ff80`；r1 publication SHA256：`3b2f179fee03230de0a07c9888db8544f4d03a664b7f21727c77bcd1ea80627b`。

## CF-R1-F01：原 A3 needs 与直接依赖的正文不等于 live

文件：`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/CHARACTER_FIRST_LANDING_PLAN.md`。

- 第 92 行写：二级原卡补齐；`code, vision`。
- 第 93 行写：`A10、原 awz.P3.A2、awz.CF.B1/awz.CF.B2、awz.CF.C1/awz.CF.C2、hub.CF.B1 交付`。
- 独立直接 GET `/api/tasks/awz.P3.A3` 的原 needs 实为 `["code"]`；直接 depends_on 严格为 `["awz.P3.A2", "awz.V9.A10", "awz.CF.B2", "awz.CF.C2", "hub.CF.B2"]`。
- 原卡 status 为 blocked；原 scope/params 与旧快照不变。主责允许的唯一原卡修改仅追加上列三个 CF 验证前置，不能借改文档重写原卡 needs 或增减直接依赖。
- 影响：照正文派发会把原卡能力及直接前置看成另一份合同，且漏写实际 `hub.CF.B2` 验证门；不满足本轮“正文/正式ID/payload/live精确对齐”。

## 最小建议替换（由原作者修改）

第 92 行：

> - 层级/needs/项目模块：二级原卡补齐；`code`（保留原卡 needs；视觉复核由原 awz.P3.A4 承担）；awz，主模块3.5.2；原验证awz.P3.A4。

第 93 行：

> - 前置（本轮在线直接 depends_on）：awz.P3.A2、awz.V9.A10、awz.CF.B2、awz.CF.C2、hub.CF.B2；awz.CF.B1、awz.CF.C1、hub.CF.B1 分别经对应验证卡形成传递依赖，不另改原卡；原 A3 预算照旧。

保留 r1 原计划、原 source-after/REPORT 和原条件发布字节；新修订由原作者另记 revision-r2 清单，主责更新条件发布绑定。A2 只核新身份和对应差异，不代写正文。

## 独立预核通过部分与限制

- 自行读取29张CF卡及旧卡/传递依赖：100个HTTP任务节点，71个CF可达节点，0缺依赖、0环。
- 24产品卡均 blocked、保留A10且新运行预算未批；13组实现/设计与验证搭档元数据有明确 `verifies`。
- 23张旧卡仅A3精确追加三个前置，原前置顺序/status/scope/params保留；5项目配置完全一致。
- 91模块只在9模块添加29条归属，原任务顺序/level/paused保留，live唯一映射与JSON一致。
- 15输出、11备份、9不可改引用、15旧published快照均按r1清单独立核当前内容SHA和字节数匹配；此项仅证明该清单身份，旧baseline逐项绑定另核。
- A2 prompt/acceptance/context及A2/A3 scope相对payload的增补来自主责明示本轮收尾授权，保留实际差异，不记为未经授权产品改动。
- 原始独立GET及本轮脚本结果：同目录 `independent-live-tasks.json`、`independent-live-modules.json`、`independent-live-projects.json`、`independent-audit-result.json`。
- 未运行产品tests/模型/渲染/下载/部署；元数据和设计核对不代表实际能力。
