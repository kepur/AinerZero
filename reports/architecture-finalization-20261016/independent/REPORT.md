# ainerzero.V9.A8：V9-r5-20261016 出版基线非作者复核

执行者：codex-v101-contract-audit-20261016（二级，非 A7 作者）。2026-10-16。任务正常 claim，所有新文件仅写本 independent/ 目录。

**建议接受 A7 的主架构设计基线与文档出版。** 本结论只覆盖 V9-r5-20261016 的身份、入口、职责/信息边界、任务依赖与暂停状态；不验收 Event/T1 候选、生产消费者、模型能力或性能，不放行代码及训练。

## 有限核对结果

- 独立检查 45 项全部成立。15 份 publication snapshot 的 SHA256 和字节数逐项匹配 manifest；已采用且不可变的 live 文档与快照一致。5 份出版前副本的 SHA 也与归档身份一致。
- reviewed-r5 身份为 ea786389…；独立重算出版前后 unified diff，与 architecture-publication.diff 逐字节相同。人工读差异：仅状态/基线入口、旧契约版本指针、候选补修状态和 Serafina 历史名称说明，没有改变 F1–F4/C1、算法式、科学门或预算。
- AWZ 落地方案保留出版前全部字节为完整前缀，仅追加 §12。README/COORDINATION/AGENT_TASKS 当前入口均指向同一个基线索引，历史“当前可做”等文字已标为历史，不构成新授权。新索引的本地文件链接均存在。
- 主架构/索引明确 Hub 为持久世界唯一写者、AWZ 管运行求值，AinerZero 保存信念而非真值；世界事件与学习侧调度分开，输入和可解析引用受因果截止约束。三平面保留现有三系统和 Forge 治理，不创建第二套运行时。
- 独立通过 live HTTP 读取 99 张相关卡，结果另存 live-http-tasks.json。原19实现卡全部 blocked，每卡登记的原业务依赖仍保留；新增 B9/B11 为 draft，21 卡均附加 awz.V9.A10，总门当前仍 draft。
- P3.A3 修正证据成立：原取样只有 A10，修正后和本轮 live 都为 P3.A2+A10；status/params/acceptance/prompt/file_scope 保持。原任务正文也明确 P3.A2 依赖。E5→E3、I2→I1/Event、B3→B1/Forge 等依赖未被总门替换。
- 8 张补验收要求的卡，其状态、依赖和参数与作者保留记录逐项相同。新出版/后续复核任务在模块表中各登记一次；module-check.txt 的严格检查结果无未归档未完成任务、无无效登记。
- 主架构 A5 与整合 A5 已 accepted；负面 AWZ A9、AZ T17 已 accepted 仅代表负报告被采纳；被验 Event A8 和 T1 当前仍 ready 待补修、未 accepted，新 A12/T18 的 verifies 和前置正确。
- manifest 将 Event/snapshot v1.2、teacher_cache.v2 放在 request_changes_not_adopted 的候选快照组；R1–R4/B1–B4 作为必须补修的边界登记。A2 v1.1 单列限范围契约接受，不伪称完成实际信息隔离。
- 5 份既有负审报告存在，先前 Event/T17 报告的精确 SHA 未变。训练资格仍为 external_derived 默认拒训，当前没有新获批例外；manifest 的 implementation_authorized、training_authorized、runtime_or_scientific_acceptance 均为 false。
- 本轮核对期间，全部被验输入前后 SHA 未变；未发现需要改正文的出版必修项。

## 实际命令与证据

```text
python3 -I /Users/mac/AinerWorkFlow/AinerZero/reports/architecture-finalization-20261016/independent/check_publication.py
```

返回码 0；输出 accept_design_publication、45 checks、0 failures、15 frozen files、99 live tasks。

- metrics.json：逐文件 SHA/字节数、前后身份、归档、链接、任务依赖、保留字段和结论。
- live-http-tasks.json：独立 HTTP 取样时间、服务部署身份及卡面；仅用 urllib HTTP，没有导入 relay.server/relay.db，没有直接打开数据库。
- check_publication.py：本次独立检查入口；不调用作者的发布检查器，不写被验文件。

精确出版身份（SHA256）：

```text
0f54a96ace5b9c6fad2f3a16f3e6417a2f521fe131a13400263a0f5d9920f2a4  ARCHITECTURE_V9.md
49324616a805c1a46d48db293051ed57f72a124f31b87f90512f3d5deec906d0  ARCHITECTURE_BASELINE.md
b765d20693262fb0bbcd094812eded16edaa0fa2984bc388b57ebba191973a35  docs/architecture/baseline.v1.json
abf8272c2671f990068e678b12fab92539566a8aeb2ad2ccc2978c88bb0c350e  reports/architecture-finalization-20261016/REPORT.md
```

## 范围与未验证项

本次是有限文档出版复核，没有重复底层契约测试，也没有恢复或实现消费者。Event/T1 的负审结论与探针完整保留，后续原设计卡补修；它们不阻断已清楚定义职责和信息边界的主架构定版，也不能因主架构定版自动转为通过。

任务状态是本轮 HTTP 取样时刻的事实，后续进度写入 Relay 和新报告，不静默改本次冻结字节。原19集合以外的历史任务和全模块成熟度不在本次重新验收范围；取样中仍为 ready 的 R1/R3 虽 kind 标 implement，正文只要求来源调研和文档，不授权产品代码/模型工作。

本轮无产品源码修改、MLX/GPU/模型/训练、下载、安装、付费、RunStore 或模型预算登记、git提交推送、服务重启/部署。没有自行 accept A7 或自己的 A8 报告。
