# E13a-R1：动作保持 CPU 协议补修

日期：2026-10-12 · 主责统筹：Codex · 状态：R1已reported并独立回验50项；剩余F02消费边界转 [R2](E13A_IDENTITY_BOUNDARY.md)，本文件保留原补修要求；不是训练任务。

依据：[E13部分交付](artifacts/reports/E13-grokbot-newbot-20261012T151753+0300.md)、[E14a独立审查](artifacts/reports/E14a-action-preservation-protocol-review-20261012.md)、[M2m-d固定协议](M2MD_ACTION_PRESERVATION.md)。E13a 的23项CPU测试通过，但以下反例表明协议层尚未验收；原报告和测试结果保留。

## 领取与交付范围

先在 [任务表](AGENT_TASKS.md) 领取 E13a-R1，只改 `src/ainerzero/learning/action_preservation.py` 和 `tests/test_action_preservation.py`。必要的可移植CPU整数fixture先登记自己的新文件范围；不要领取或修改worker、CLI、旧协议、共享研究结论或其他人的测试。实现者交自己的报告/XML，独立审查者回验后由统筹验收。

保持 M2d 起点、lr0.003、200次、λ/温度1、原池/调度/双射/种子、参数范围、208,546单位/1,610秒与全部科学门。CPU协议不导入MLX，不产生环境动作、模型调用、run或训练预算预留。不要跑含MLX的全量测试。

## 五项必须修复的不变量

| ID | 最小修复 | 必须有的CPU反例 |
| --- | --- | --- |
| F01 | 每次返回计划及嵌套gates均独立；提供固定计划内容核对，不把调用者可改dict当预登记 | 修改一份计划不改变下一份；更改门槛、单位或种子后固定计划核对拒绝 |
| F02 | 将通用窗口/预算计算与真实输入身份验证分开。真实输入验证绑定原samples、200×16调度逻辑SHA、train分区、16个world/episode映射及公开记录中的观察/动作身份；窗口摘要关联episode/world/公开源身份，调度摘要单列 | 换episode/world/分区、换观察/动作、交换批内行或批次、改窗口但保留units都不能冒充原输入；同预算/同键不能代替同调度 |
| F03 | 缓存固定 `pilot_shared_symbol_v1`；incoming_h=(256,256) FP32，logits=(256,2,8,256) FP32，mask=(256,8) bool且每行至少一格可见。绑定字段严格检查SHA256、UUID、粒子整数1、温度1、公开q掩码和teacher预算2,254；拒绝bool冒充数字。expected identity来自明确可信输入 | 错宽度/架构/摘要/UUID/负预算/未来掩码/全隐行均拒绝；合法合成fixture不再使用unregistered或假架构 |
| F04 | 梯度树非空、每分支键/叶子shape完全相同且所有输入有限；有效目标数有限正值且非bool，不能依赖广播或只检查输出 | (1,)与(3,)错配、inf/NaN/0/bool分母、空树、非有限原始分支拒绝；正常归一化数值不变 |
| F05 | 真正核对应用梯度的冻结区域。以现有四个GRU叶子/shape及尾部范围建立明确CPU掩码；检查masked冻结区域L2≤1e-8，并分别记录raw冻结区范数。不得用raw−masked推定冻结区 | raw==masked且冻结区非零必须拒绝；仅尾部非零可通过；错误树/shape/NaN拒绝 |

F02可接收已经加载并验证的公开记录及其权威身份，不必在纯计算模块内引入模型或数据库。完整真实文件/中央账本的闭包入口留给E13b，但本层必须拒绝内部身份不一致，函数名和报告必须区分“算出预算”与“真实来源已验证”。输入身份补强使window/key manifest的绑定摘要发生变化时，记录新旧schema/摘要和原因；实际窗口、调度、逐调用seed值和成本保持不变，不覆盖原E13清单或将schema变化写成训练改动。

F03的CPU验证只能检查结构和声明之间的一致性。生产run是否存在、角色/已预付预算是否正确，以及检查点manifest是否真实绑定权重文件，必须由E13b在现有RunStore/文件入口核对。`_array_identity`是连续原始数组内容SHA，不是.npy/safetensors容器文件SHA；落盘manifest还须分别记录文件大小/SHA，不能混用。

F05沿用Wx/Wh/b的尾部行128:256、384:512、640:768，以及bhn的128:256；shape从现有GRU契约核对，不接受调用者自定放宽掩码。仅修改本轮新模块，不改 `tail_update.py` 或旧B/M2m-c的raw-front≤1e-8断言。新协议raw-front可有限非零；应用梯度、AdamW后投影及282,128冻结元素逐位核对是不同保护步骤，后两项仍待E13b/C06a验证。

## 验证与完成条件

定向执行不导入MLX的本模块CPU测试，保存实际命令、XML/日志、源码/fixture SHA、通过/失败数量和所有未验证项。缺原M2m-c artifact不能把必须的协议验收整组skip：可将原整数清单做明确来源的固定CPU fixture，或把真实本机核对作为单列探针；合成数据不充当真实输入闭包通过。

原23项正向断言不放宽；新增反例验证以上缺口。有限数值阈值和门槛不改。交付时仍标reported，独立回验通过后才accepted E13a；worker/CLI/MLX、教师缓存生产、数值/反向等价、内存峰值、运行耗时及能力门均不在本任务已完成范围。

下一步为E13b接入，细节见 [固定协议的分阶段交接](M2MD_ACTION_PRESERVATION.md#分阶段交付与接口固定)。
