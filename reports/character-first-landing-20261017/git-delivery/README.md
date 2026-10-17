# 本次 Git 交付范围与证据身份

用户于 2026-10-18 明确要求“帮我提交git and push”。只提交本轮 CF 方案、任务落地与审查证据；保留其他任务的未提交改动。

原 `publication.json`、`revision-r2/source-after.json` 绑定的是本机已审工作区及 Relay 取样，**不是本次 Git checkout 的完整身份**。它们原字节与验收结论均不回写。`RECEIPT.json` 记录基准提交、局部暂存的索引身份及原工作区摘要；实际提交与推送结果以本次 Git 执行结果为准。

- AWZ 的 `RESEARCH_LOG.md` 只暂存 CF 节，前存两节保留工作区。
- Relay 的 `modules/modules.v1.json` 只暂存 29 张 CF 卡在 9 个既有模块中的归属；26 条前存归档及格式变化保留工作区。
- `modules/BOARD.md` 是包含其他任务即时进度的生成快照，本次不暂存共享主文件。完整本轮看板已在 `local-publication-inputs/AinerRelay/modules/BOARD.md` 及既有 `workbench/` 生成证据中归档。

`local-publication-inputs/` 追加保存原已审日志、登记表和看板的完整字节，便于从 Git 归档核对原发布摘要；这些副本不改动各仓权威工作文件，也不对其中其他候选追加验收。

本次提交推送不改变 A10 代码总门、训练暂停、预算和生产部署状态。
