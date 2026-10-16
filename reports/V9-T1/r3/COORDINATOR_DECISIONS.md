# T1 r3 统筹决定（Codex，2026-10-16）

本轮只补候选契约定义、schema、合成夹具和报告目录中的CPU参考核对，不实现缓存/ModeGuard/模型消费者。不改主架构r5、ADR-0005、旧科学门与预算，不启动模型/GPU，不放行A10。

## 设计裁决
1. B1：AWZ → external_derived 是强制来源组合；actor=student不能改变origin。每条upstream（system/origin/actor/input_ref/eligibility）、world/partition须与独立于缓存记录的不可变原来源清单逐项绑定。不能从同blob另一条来源继承；没有可信来源上下文就拒绝/未验证，不准训。来源条目自报以及其自行重算的哈希不是可信批准。
2. B2：source.timestamps_s必须与引用blob.key_material.input.timestamps_s逐项一致；截止从blob真实输入和可信当前Observation包时间取值，不从可编辑副本取值。时间统一为Observation的episode-relative t_ticks/120，不用故事world_time；可信上下文绑定episode/epoch/120Hz和当前观察截止，跨域或缺上下文拒绝。input全帧≤当前截止，target可含未来帧但不得当输入，明确区分二者。具体序列化由执行者按最小契约扩展落实，不能引入世界真值或未来标签到输入。
3. B3：当前获批ADR-0005训练例外集合为空。非空revision_ref不构成批准；必须经独立冻结的可信批准登记解析并核实身份/适用来源/分区。不存在、未批准、引用不匹配或无法解析都拒训。未来例外路径是设计格式，本轮不增加任何例外，合成正例不得冒充实际授权。
4. B4：derivation.teacher_id、有序weights_sha256、preprocess_spec_sha256须与引用blob逐项一致；任何不一致都拒绝。直接调用资格判定也必须先完成结构/绑定/策略检查，不能只算布尔交集。保留五项交集、单锁全程、两层存储、四分区和跨分区blob拒绝。
5. 参考核对的trusted context必须与待验记录分开，通过调用方固定的预期身份核对；测试使用明确标为synthetic的冻结上下文，缺失/错误摘要/替换上下文应有负例。这只证明上下文绑定规则，不声称来源认证或审批服务已实现；生产接入另归T2/Forge。

## 执行与证据
先归档当前r2（文档/schema/夹具/作者报告及脚本）与SHA，不覆盖旧报告/参考检查器。候选尚未采用，可在teacher_cache.v2候选内修订，文档r3说明迁移；新增参考核对放reports/V9-T1/r3/，doc指向新入口。保留原v0/v1和r2全部失败证据。除落实上述规则的契约材料外不改源码。

复现旧正反例和11个破坏对照；新增T17五个隔离探针、跨episode/epoch、伪ADR/缺可信上下文/自改当前截止等反例，确保每个指定条件独立触发真实非零、关闭该检查后其专用反例会漏检。未来target与等于截止边界应通过。报告实际命令、全部输入/输出SHA、计数、失败与未验证；不把异常退出算成有效破坏对照。材料完成后交T19支持卡与原T1，非作者T18复核。
