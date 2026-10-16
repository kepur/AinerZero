# ainerzero.V9.A6：r4 与 v10.1 建议的非作者审议

日期：2026-10-16（Europe/Istanbul）。主责：Codex；被审 r4 作者：Claude。
任务范围：只读审议，新增本报告目录；未编辑根架构、产品源码、契约、旧报告或中央账本。

**结论：继续架构改造的方向成立；r4 目前不通过冻结审议，建议补修后再复核。代码任务继续暂停。** 新增必修项不否定已关闭的 r3 问题，也不恢复旧 RSSM 主线。三平面可以作为职责视图，并入现有 v9 r4；无需另起框架或仅为编号重建 v10.1。

## 1. 输入与本轮证据

- 当前工作区 r4 SHA256：e69a0e1ce7cb92187961de387fc84d4fb390aab84ed2e4682601f39566521dda，与 A5 作者报告一致。
- r3 架构、r3 调研、整合前 ADR-0012、整合前落地方案共 4 份归档，全部与原 Codex 审议输入 SHA 一致；调研、ADR 和落地方案旧内容均为当前文件的完整前缀，追加约束成立。
- Downloads 原件与 docs/research/AinerZero_v10_Architecture_Validation.source.md 逐字节相同，SHA256 79b6547cc27cf8900553fd738144768435e086b382532e4c00241cf62b9d3c0f。
- 19 个关键文档/源文件的完整身份见 input-identities.json；原始归档核对见 archive-checks.json。被审 r4、ADR、落地方案字节在本目录另存，不覆盖作者文件。
- 实时 Relay 四项目看板取样见 task-status-snapshot.json；原 19 张暂停实现卡全部 blocked，无 claimed/ready，未放行。
- 非作者执行层顺序领取并交回 A7/T14。详见：
  - [A2 r1 独立报告](/Users/mac/AinerWorkFlow/AnimeWorldZero/reports/V-V9-A2-r1/codex-v101-20261016/REPORT.md)；
  - [T1 r1 独立报告](/Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-T1-r1/codex-v101-20261016/REPORT.md)。

## 2. 原 r3 审议关闭表

| 项 | 本轮判断 | 限定 |
|---|---|---|
| “最优”是待检验研究目标 | 成立 | r4 §0 已降为当前证据下默认选择 |
| RSSM 结构性归因降为假说，D 未晋升 | 成立 | 既有负结果和检查点不被改写 |
| 存储分离不保证梯度无干扰，记忆带编码器版本 | 成立 | 仍须 M2 诊断 |
| 主动物理旋转与被动换坐标区分 | 成立 | 完整 SE(3) 不被一概否定 |
| 位姿方向、扰动、规范、等变前提、RGB 限制 | 基本成立 | 协方差表述还应明确切空间，见 C1 |
| 本层宏动作、detach、时间聚合、防坍塌 | 成立（设计） | 尚非训练协议或模型能力证明 |
| 最小时间白名单、sim_truth 通道、四分区 | 成立（局部契约） | A7 独立正反例通过；引用解析未覆盖 |
| S0 误差界附前提、CPU 不替代科学门 | 成立 | G1 已登记容差未改 |
| S1 同观察输出、不可比阻断、逐臂登记 | 原则成立 | 具体 C0/空间适配、预算仍待预登记，不能据原则开跑 |
| S3–S6 顺序与外部预训练披露 | 成立（路线） | 未恢复训练 |
| T1 同锁、Core ML、缓存身份修订 | 五项局部关闭成立 | T14 新发现来源兼容缺口，整体不能视为通过 |
| THICK/V-JEPA 2.1 勘误 | 追加记录成立 | 本轮未重做全部论文算法审查 |

## 3. 冻结前必须修订

### F1：Persistent World Core 的归属违反 D-012

ARCHITECTURE_V9.md:271 把 Persistent World Core 写为“AWZ 运行时 + 快照 + 事件日志”，归属 AWZ，称 object_id、版本与快照都在这里。这遗漏现有 AinerHub 持久世界库及版本权威。

ADR-0011 修订一第 114–120 行明确：持久区域/地标/实例/事实/版本归 AinerHub；运行、时间、事件和确定性求值归 AWZ。WORLD_CHANGE_PROTOCOL §1–4 也明确 AWZ 只保存只读派生输入，不再建可写持久库。应在 r4 §2、§8.1 和任务映射明确列出两类状态与唯一写者，复用 Hub 的现有 Blender worker。

三平面是职责视图；不能替代 D-011 的制作脑、世界系统、世界脑，也不能把制作脑和 Forge 数据治理遗漏掉。建议映射：

| 平面 | 当前组件及边界 |
|---|---|
| Control | AinerRelay/runner 管任务、租约、作业监督；真实模型执行继续由 AinerZero CLI 锁、RunStore、预算和资源守卫授权 |
| World | AinerHub 持久库与渲染 worker + AWZ 内核运行/求值/传感/考场，按状态类型各有唯一权威 |
| Learning | AinerZero 信念与 MLX 研究；Forge 管数据包、分区、封存与训练资格。学生残差只更新信念，不改生成器真值 |

### F2：学习侧稀疏调度存在真值旁路，未来引用隔离尚无 consumer 契约

r4:96 的 UpdateScheduler.mark_dirty(event) 未限定事件来源；式 12 的接触、附着、距离、可见性关系可以来自世界真值。§8.2 只禁止 affected_ids 进入 ObservationPacket，不足以阻止世界脑在调度路径读取隐藏接触或世界实体 ID。

须区分：世界侧调度可以读权威事件；学习侧只读当前及过去的允许观察、学生已执行动作和自身信念。世界事件、观察事件、信念事件要有明确的可见性/时间边界。未知真值不能以 dirty 集合、对象句柄、图边、回退标志等形式间接进入模型。

A7 独立合成探针还确认：把合法 image.uri 改成 private/future_tick_999999.png，当前 schema/字段规则仍接受。它只证明缺少因果引用解析约束，未证明生产已泄漏；没有真实 resolver/E2E。应将 as-of 引用解析、允许命名空间、实际加载路径、教师输入片段截止时间与缓存 lineage 写入 A3/B1/编码器任务。

必要反例：两世界在 t 以前学生观察完全相同、隐藏未来不同，其模型输入、学习侧调度和可解析资产必须相同。未来帧可以作隔离标签，不能反向混入 t 时刻的教师输入特征。

### F3：教师缓存不能保留 AWZ 原始来源

TEACHERS_AND_CACHE §2.5 及 teacher_cache.v1.schema.json:205–208 把 origin_native.system/origin 固定为 ainerzero/observed，且不接受额外来源字段。A2 r1 / ADR-0005 却要求 AWZ 观察是 external_derived，与 actor 独立。

T14 独立探针确认：现有合法条目为 observed 时接受；忠实保留 external_derived 后被 schema 拒绝。这是跨契约不兼容，不是已发生训练污染的证据。冻结教师变换不能改变输入来源或授予训练资格。

须设计兼容的新版本/迁移：逐来源条目保存 upstream origin、system、actor、输入身份与资格；教师变换另记 derivation；训练资格取输入资格与教师许可交集。external_derived 默认拒训保持不变。同 blob 多来源仍分别判定，不能继承另一来源的训练许可。

同步 T1、Forge teacher_feature 映射及 T2/Forge 消费卡，先独立复核设计，再实现。A7 的局部契约通过不能替代这一闭包。

### F4：稀疏正确性尚缺持续动力学与依赖闭包定义

式 12 仅列动作/接触变化/遮挡/新观测/不确定性种子。没有新事件时，有速度的物体、重力、持续外力、计时器仍可能演化；固定 k 跳也不自动覆盖长链约束或新接触。

须在 A8/B9 明确 active/sleep 集合、时间推进、持续力、碰撞宽相检测、依赖闭包或安全回退。若不能证明被省略对象本步保持不变或可按等价解析规则延迟求值，就应更新或回退，不能冻结后再靠阈值掩盖误差。

30% 是研究目标。端到端计时应含 dirty 发现、依赖图维护、碰撞检测、回退和输出/校验成本；使用经过优化的全量基线。Blender/Bullet 的精确重放域要绑定构建、求解器、步长、平台和输入；未实测前不承诺跨平台逐位确定性。

## 4. 任务与运行表述应同时收口

- **E3 非新缺项**：现有 WORLD_CHANGE_PROTOCOL 已设计五元组、CAS、幂等 change_id/receipt、精确源摘要、崩溃恢复黄金用例、跨族禁止混合。E3 当前 ready/待返工，E5 blocked，不能写成已验收或从零另建事务框架。Hub apply_delta 现有版本比较和嵌套事务，不等同已验证生产并发 CAS/receipt。只读看到的旧快照还含当前 assets/chunks/current_version，历史封存缺口已在 E3 原稿说明。
- **代码暂停不由“无训练”自动解除**：r4 的“S0 现在可做”、V0 可做须附 D-019 总门。落地表 §11.1/11.3 的放行条件是各自业务依赖的附加门；E5 仍等 E3、I2 仍等 I1 与 Event，不能“原样”批量绕过。
- **19 与 12 不是同一个基线**：19 张原暂停卡已核全部 blocked；用户转述中“12 张原样卡”额外包含 Forge B3 后续，后者不属于原 19 张暂停集合。Forge B3 当前 reported，仍待 B5 等复核，不能把后续工作自动算作已放行实现。
- **电源策略存在差异**：本轮 pmset 显示电池放电；新 T1/T4 文档要求接电。AinerZero RESEARCH_LOG 的 R20261014-power-policy 则记录用户取消旧训练/诊断 AC 守卫，memory_worker.py:1428 也明确无 AC 阻断。故不能笼统宣称“已有统一电源守卫会拦住全部 GPU”。应按入口和任务登记说明实际策略，不用本轮审议恢复旧守卫；当前本轮没有任何模型/GPU运行。
- **Serafina**：本轮所核当前调度能力来自实际 AinerRelay/runner。无需因历史名称未确认而阻塞 A8，也不推断历史别名等价或新建第二套 Runtime。进程退出/作业监督不等于重启后自动续训能力已验收。
- **版本命名**：awz.P3.E3 是统一变更任务，v10.E3 是遮挡/身份实验，建议始终带命名空间。保留所有旧任务 ID、失败与门槛。

### C1（澄清项）：右扰动协方差

r4:103 的 Adjoint 公式应明确针对被重新表达的同一个切向量，不能误用为任意 world frame 改变时的右扰动协方差。G1 源码已写清右/左误差关系：xi_l=Ad(mu)xi_r；纯左乘世界坐标变换下右误差不变。架构应直接引用 G1 约定，避免 B2/G3 实现时解释分叉。本项未重跑数学测试。

## 5. 外部能力核实及其边界

本轮只读打开原作者页面，没有下载代码/权重或安装环境：

- [Meta V-JEPA 2 官方仓库](https://github.com/facebookresearch/vjepa2)：官方实现为 PyTorch，已列 2.1；不能把社区 MLX 适配的能力当作本机测试结果。
- [MLX 移植作者仓库](https://github.com/dgrauet/vjepa2-mlx)：确有 MLX 2.1/2.0 移植及作者数值对齐说明；本机 parity、耗时、峰值内存未验证。
- [Apple DA2 Small 模型卡](https://huggingface.co/apple/coreml-depth-anything-v2-small)：列 Core ML 和 Apache-2.0；本机算子/计算单元和数值一致性未验证。
- [DA3 官方 Model Zoo](https://github.com/ByteDance-Seed/Depth-Anything-3)：Small/Base 标注 Apache 2.0。当前官方示例用 CUDA；“可选 MPS”仍是待独立推理验证的本机接入假设。保留现有 T6 的 DA3 方向，不重新把 VGGT 排回优先集。

论文收益、0.1M–2M 候选范围、30% 提速与 10% 误差改善均是研究设计，不是新运行授权或已证实本机收益。未改既有科学参数、注册门槛、固定种子、预算、数据或检查点。

## 6. 建议下一顺序

1. 保持实现暂停；Claude 可继续已领取的 A8 文档设计。
2. r4/ADR/落地方案补 F1–F4、上游来源策略和总放行门；保留本次 r4 字节与不通过报告。
3. T1 兼容性修订及非作者复核；A3/B1 等任务加入实际引用解析与同观察异真值负例。
4. 两张 A6 完成修订后的非作者通过，再由一级逐张核原依赖、授权与文件负责人。没有前置的代码卡也不因本报告自行 ready。
5. 之后才是 CPU 工程实现与 consumer 闭包，再到已批准范围内的教师基准；训练继续暂停，新科研实验须独立登记。

本轮结论分类：归档、任务暂停、原 r3 多数文档修订成立；r4 冻结不成立；生产事务、完整信息隔离、真实锁集成、物理/MLX 能力及降本未验证。

## 7. 实际操作与限制

实际只读命令包括 relay show/prompt/board --json、rg/sed/nl/git status/git rev-parse、pmset -g batt；Python 标准库 hashlib 对文档与源码计算 SHA，逐字节/前缀核对归档，保存必要输入副本与筛选后的看板快照。领取及 heartbeat 两张 A6，执行层领取/report A7/T14。未 import Relay server/db，未访问生产数据库文件。

一次 Hub 源路径按旧文档位置查找未找到，随后以 rg --files 定位 code/apps/ainer-core/app/worldmodel/service.py；一次 board 输出截断产生无状态副作用的 BrokenPipeError，改用完整捕获 JSON 后解析。此两项不作为产品失败。

CPU 契约运行与变异证据来自独立执行层报告，各自保存原始失败及修正；父审未重跑模型、训练或全量测试。模型预算预留 0、模型调用 0；未新增 RunStore 记录、没有 GPU/渲染/下载/安装/付费/提交/推送/部署。只 report 两张 A6，不自行 accept。
