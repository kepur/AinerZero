# v9 落地与重构方案（ADR-0012）

- 起草：Claude（统筹）· 2026-10-15 · 依据：[v9 RFC](../spec/AinerWorkFlow_v9_RFC.md)、[ADR-0012](../adr/ADR-0012-v9-neurogeometry-hjepa.md)
- 原则：**保留已验证成果，不保留走不通的方向**。凡与 v9 冲突的任务收束；与 v9 一致的任务保留并补 v9 口径；缺的协议与接口新建。
- 授权边界不变：训练、下载、付费、推送、删除、超预算运行都要用户批准。本方案里需要授权的任务一律建为草稿。

## 1. 差异结论（一句话版）

| 方面 | 现状 | v9 要求 | 处置 |
|---|---|---|---|
| 三系统分工 | ADR-0011 + D-012 已定 | 原样，边界收紧 | 保留 |
| 世界脑 | 39 万参数 RSSM/GRU；D 候选；历史记忆与动作能力冲突未解；训练暂停 | 几何内核 + 互补记忆 + H-JEPA 式分层 + 主动实验；RSSM 降为快速动力学基线 | 新建架构与接口（P0 无训练），实验阶段建草稿待批准 |
| 跨系统数据 | 有 C0/GridLab/T10/W0 各自格式；Forge APACK 已有分区与封存 | 四个协议 + 字段级防泄露 | 新建 WorldSnapshot、ObservationPacket（AWZ）、SkillProposal（AinerZero）、ExperienceEpisode（Forge，建在 APACK 上） |
| 世界变更 | E1 r2（WorldCommand）与 E3（合并 WorldDelta）并行 | 一个信封：base_revision、scope、locks、WorldDelta | E1 不再出 r3；E1/E4/awz.P3.E7 的结论并入 E3 |
| AWZ W 轨 | W1 训练刚完成（预算内，Gate B 未过） | 世界系统不训练竞争性世界模型 | W6 复核完成后结案，W1 转为考场与对照基线 |
| 世界运行 | I1–I3 等前置 | P1 核心：小房间、确定性日志、受限观察考场 | 保留并优先，I1 补 v9 口径 |
| 渲染与美术 | A3–A8、B、C、D 轨在推进 | Blender 主路径、风格包、NPR | 保留 |
| 制作脑 | 技法库、审片、表演接口 | 五种执行策略、多模态输入 | 新建一项一级设计 |

## 2. 现有任务逐项处置

### AnimeWorldZero

| 任务 | 处置 | 说明 |
|---|---|---|
| P2.W2（T08，待验收）、P2.W6（复核进行中） | 照常完成后结案 | W2 按“流程合格、能力未过”终审；之后由 awz.V9.C1 结案与迁移 |
| P2 其余阻塞项（H1、A1、A8、I1、I18、I29、I37、S7、S8） | 保持阻塞 | Godot/T10 已暂停；v9 保留 Godot Gate A 成果，未来用于实时/全景/VR |
| P3.I1 世界运行契约 | 保留，补 v9 口径 | 稳定对象 ID、统一世界时钟、StateDelta、事件真实性分层、与 awz.V9.A2 的快照/观察协议对齐 |
| P3.I2 / I3 小房间切片与复核 | 保留，优先 | v9 P1 第一站；之后由 awz.V9.B1 从它导出受限观察 |
| P3.E1（r2 待验收）、E4、awz.P3.E7 | E1 不出 r3 | 复核结论并入 E3；E1/E4/awz.P3.E7 由 Codex 终审 |
| P3.E2 `.aworld` 清单 | 保留 | 与 D-012 持久层一致 |
| P3.E3 统一变更协议 | 保留，补 v9 口径 | 信封字段命名为 base_revision、scope、locks、WorldDelta；吸收 E4 与 awz.P3.E7 的 10 个反例 |
| P3.E5 / E6 | 保留 | 跟随 E3 |
| P3.A3–A8 Blender 主路径、性能、Cycles | 保留 | v9 P1 主渲染路径；A5/A6 预算已批准 |
| P3.B1–B4 生成器 | 保留 | 程序化生成器属世界系统 |
| P3.C1–C4、D1–D5 美术与角色 | 保留 | 身份与风格权威在 AWZ；付费插件不买（D-014） |
| P3.H1 / H2 交换格式 | 保留 | 勘误已入日志 |
| P3.R1 REA | 保持草稿 | 等用户给来源地址 |

### AinerZero

当前无未完结任务；训练暂停。检查点、登记、RunStore 与失败证据只读保留。

### AinerRelay、AinerForge、AinerHub

relay 的 P1/P2 基础设施任务不受影响；forge 的 F1 已全部收口（TOCTOU 限制转为 forge.V9.B1）；hub 的 B1（阻塞）、D2/D3 不受影响。

## 3. 阶段与门槛

| 阶段 | 内容 | 是否需要用户批准 | 晋升门槛 |
|---|---|---|---|
| **P0 契约与接口**（现在） | 四个协议、防泄露检测器、世界脑五个可替换接口与假实现、基线冻结清单、研究注册表 | 否（纯 CPU、无训练、无下载） | 契约有断言测试与改坏对照；接口假实现通过合同测试；基线哈希可复验 |
| **P1 世界系统优先**（现在） | 小房间运行切片、受限传感出口、2D 导航/时间/对象关系考场、Blender 主路径 | 渲染按已批准预算 | 考场真值只在封存评测通道；学生输入经泄露检测器 |
世界脑的研究顺序按用户 2026-10-15 指示修订（r2，见 `AinerZero/ARCHITECTURE_V9.md` §5 与 `AinerZero/docs/research/V9_RESEARCH_SURVEY.md`）：**先空间与认知地图、再多时间尺度**；旧 RSSM 只作对照，不并入新架构；M2 记忆干扰诊断作为每个阶段的常设对照。

| 阶段 | 内容 | 是否需要用户批准 | 晋升门槛 |
|---|---|---|---|
| **S0 数学核心**（现在） | NeuroGeometry 李群、切空间高斯信念、已知运动学预测、位姿图；解析参考实现 | 否（不训练） | 群公理与数值性质测试；已知运动学下定位与回环达到解析上界 |
| **S1 空间与认知地图** | 等变度量地图记忆 + 情景拓扑图 vs 旧 RSSM | **是**（训练预算） | 定位误差、未见地图、混淆观察下拓扑恢复、少经验预测未见转移、样本效率 |
| **S2 多时间尺度** | flat RSSM vs flat JEPA（LeWM 小模型）vs 两层 H-JEPA 式（含逆动力学），显式 `dt` | 是 | 长时域预测与规划成功率、子目标合法性、规划计算量；第三层仅在第二层成功后加 |
| S3 记忆检索与巩固 | 手工线索 vs 按预测效用学习的检索；回放巩固 | 是 | 历史读回、旧技能保留 |
| S4 对象交互 | 重力对齐等变图网络 | 是 | 未见对象组合与接触 |
| S5 视觉 | V-JEPA 2.1 冻结特征仅作教师/基线 | 是（含可能的下载） | 对象 ID 不泄露；遮挡、3D 关系 |
| S6 自驱成长 | 学习缺口、信息增益、沙盒行动、技能晋升与撤销 | 是 | 无教师独立测试、旧技能保留 |

S1、S2 的实验卡建为草稿（ainerzero.V9.P1–P4），其余阶段等前一级过门再开卡。

## 4. 新建任务

所有新任务在各项目的 `V9` 期下；一级设计由非作者一级平级审议，二级实现都配非作者复核。

### awz（世界系统侧）

| ID | 层级 | 内容 | 前置 |
|---|---|---|---|
| awz.V9.A1 | 一级 | 平级审议 ADR-0012 与本方案（非 claude 一级） | — |
| awz.V9.A2 | 一级 | `WorldSnapshot/v1` + `ObservationPacket/v1` 契约与字段级真值泄露规则 | — |
| awz.V9.A3 | 二级 | 两个契约的纯 CPU 校验器与泄露检测器 | A2 |
| awz.V9.A4 | 二级复核 | 独立复核 A3（泄露对抗） | A3 |
| awz.V9.B1 | 二级 | 受限传感出口 v0：小房间运行切片 → ObservationPacket 流，真值只进封存评测通道 | A3、P3.I2 |
| awz.V9.B2 | 二级复核 | 独立复核 B1 | B1 |
| awz.V9.B3 | 二级 | 考场生成器 v0：2D 导航、时间、对象关系考试，评测真值封存为 APACK final | B1、forge.V9.A2 |
| awz.V9.B4 | 二级复核 | 独立复核 B3 | B3 |
| awz.V9.C1 | 一级 | W 轨结案与迁移（W1/W3 停训，W1 生成器与评测转考场/基线，W2 归美术） | P2.W6 |

### ainerzero（世界脑侧）

| ID | 层级 | 内容 | 前置 |
|---|---|---|---|
| ainerzero.V9.A1 | 一级 | 平级审议 `ARCHITECTURE_V9.md`（非 claude 一级） | — |
| ainerzero.V9.A2 | 二级 | 基线冻结清单：D 候选、C0、GridLab 检查点与登记的只读哈希与复验脚本（不加载 MLX） | — |
| ainerzero.V9.A3 | 二级复核 | 独立复核 A2 | A2 |
| ainerzero.V9.B1 | 一级 | `SkillProposal/v1` 契约（能力门禁、TTL、证据版本） | A1 |
| ainerzero.V9.B2 | 二级 | 六个可替换接口与假实现 + 合同测试（含 GeometryCore、SpatialMemory；纯 CPU，新目录，不改现有训练代码） | A1 |
| ainerzero.V9.B3 | 二级复核 | 独立复核 B2 | B2 |
| ainerzero.V9.G1 | 二级 | S0 NeuroGeometry 数学核心库与解析参考实现（不训练） | — |
| ainerzero.V9.G2 | 二级复核 | 独立复核 G1（群公理、数值性质、滤波上界） | G1 |
| ainerzero.V9.R1 | 二级 | Research Adapter Registry v0（只读条目，不下载；补入调研报告的新来源） | — |
| ainerzero.V9.R2 | 二级复核 | 独立复核 R1 | R1 |
| ainerzero.V9.P1 | 草稿 | S1 空间与认知地图实验（需用户批准训练预算） | B2、G1、A2、awz.V9.B3 |
| ainerzero.V9.P2 | 草稿 | 独立复核 P1 | P1 |
| ainerzero.V9.P3 | 草稿 | S2 多时间尺度实验（需用户批准训练预算） | P1 |
| ainerzero.V9.P4 | 草稿 | 独立复核 P3 | P3 |

### forge（经验平台）

| ID | 层级 | 内容 | 前置 |
|---|---|---|---|
| forge.V9.A1 | 一级 | `ExperienceEpisode/v1` 契约（建在 APACK 分片上） | — |
| forge.V9.A2 | 二级 | Episode 校验器与 APACK 挂载集成（纯 CPU） | A1 |
| forge.V9.A3 | 二级复核 | 独立复核 A2 | A2 |
| forge.V9.B1 | 二级 | 读取期完整性：按登记哈希读时校验（F1-B1 TOCTOU 限制） | — |
| forge.V9.B2 | 二级复核 | 独立复核 B1 | B1 |

### hub（制作脑侧）

| ID | 层级 | 内容 | 前置 |
|---|---|---|---|
| hub.V9.A1 | 一级 | 制作计划 v1.x 的五种执行策略与多模态输入约束（扩散产物不自动成为可编辑世界） | — |

## 5. 给在途任务的口径变更（以信箱 change_request 下发，不改状态）

- awz.P3.I1：对齐 awz.V9.A2 的快照与观察协议；稳定对象 ID、统一世界时钟、StateDelta、事件真实性分层（实际发生 / 角色相信 / 艺术表现等）写进契约。
- awz.P3.E3：信封字段统一为 base_revision、scope、locks、WorldDelta；吸收 E4（reports/V-P3-E1/REPORT.md）与 awz.P3.E7（reports/V-P3-E1/r2/report.md）的全部反例；E1 r2 作为输入，不再出 E1 r3。

## 6. 推进顺序

1. 立即可并行：awz.V9.A1/A2、ainerzero.V9.A1/A2/R1、forge.V9.A1/B1、hub.V9.A1，以及原有 P3 世界系统任务。
2. 契约落定后：awz.V9.A3、forge.V9.A2、ainerzero.V9.B1/B2。
3. 小房间切片（P3.I2）交付后：awz.V9.B1 → B3。
4. P0 全部通过后，向用户申请 P2 训练预算，再发布 ainerzero.V9.P1。

## 7. 9.1 增补：3D 创作与评测平面（ADR-0012 修订二）

| ID | 层级 | 内容 | 前置 |
|---|---|---|---|
| awz.V9.D1 | 一级 | 场景质量评测协议 v0（判据、结构/视觉分路、新鲜渲染、失败计零；确定性结构检查优先） | — |
| awz.V9.D2 | 二级 | 确定性结构检查器：Blender 后台只读检查 `.blend`（对象、层级、尺寸、材质、相机、动画），不渲染 | D1 |
| awz.V9.D3 | 二级复核 | 独立复核 D2 | D2 |
| awz.V9.D4 | 二级 | 锁定守卫：生成/修复的 WorldDelta 触碰锁定字段一律拒绝；“为提分改锁定字段”对抗套件 | D1、P3.E5 |
| awz.V9.D5 | 二级复核 | 独立复核 D4 | D4 |
| awz.V9.D6 | 草稿 | `blenderworld_adapter`：提交格式互转（默认关闭）；官方基准外部对标需用户批准下载数据集、安装 Blender 4.2.10、付费评测接口 | D2 |
| awz.V9.D7 | 草稿 | 独立复核 D6 | D6 |
| hub.V9.A2 | 一级 | 3D 创作智能体流程：参考图/文本/视频 → 可编辑 `.blend`，只经世界命令信封提交，锁定字段不可改，轨迹与用户修正入 Forge | hub.V9.A1 |

另：forge.V9.A1 的 ExperienceEpisode 增加 `agent_trajectory`、`user_correction` 来源与“仅专项模型可用”的消费限制；ainerzero.V9.R3 补登记 BlenderWorld。

## 8. 本机集成增补（ADR-0012 修订三）

| ID | 层级 | 内容 | 前置 | 授权 |
|---|---|---|---|---|
| ainerzero.V9.T1 | 一级 | 教师与缓存规范：三种运行模式、内存互斥、缓存 schema、教师作带噪传感器的接入、授权清单 | — | 不需要 |
| ainerzero.V9.T2 / T3 | 二级 / 复核 | 教师特征缓存与运行模式守卫（纯 CPU，假教师） | T1 | 不需要 |
| ainerzero.V9.T4 / T5 | 草稿 | V-JEPA 2.1（vjepa2-mlx）与 Depth Anything V2 Small（Core ML）接入与本机基准 | T2 | 下载与安装 |
| ainerzero.V9.T6 / T7 | 草稿 | VGGT-1B 关键帧批处理接入 | T2 | 许可审查（CC-BY-NC）、PyTorch 安装、下载 |
| awz.V9.B5 / B6 | 草稿 | Blender 合成观测数据生成器（刚体、碰撞、遮挡、相机运动；受限观察 + 封存真值 + sim_truth 分区） | B1 | 渲染预算 |

另：forge.V9.A1 增加 `teacher_feature`、`sim_truth` 来源；ainerzero.V9.P1（S1）加视觉臂与新增指标；hub.V9.A1 纳入 WorldForge 与 Hunyuan3D 的归属与许可约束。

## 9. 前沿增补（ADR-0012 修订四，D-017）

| ID | 层级 | 内容 | 前置 | 授权 |
|---|---|---|---|---|
| ainerzero.V9.G3 / G4 | 二级 / 复核 | 解析规范化算子 `canonicalize/decanonicalize` 与等变性质测试（纯 CPU） | G1、G2 | 不需要 |
| ainerzero.V9.T8 / T9 | 二级 / 复核 | RLT 停帧去重（numpy 参考实现 + 合成停帧片段测试，纯 CPU） | — | 不需要；V-JEPA 上的 GPU 实测另批 |
| ainerzero.V9.R5 / R6 | 二级 / 复核 | 注册表补登记前沿增补调研的来源 | R3 | 不需要 |
| ainerzero.V9.T6 / T7 | 草稿（改写） | DA3-Small/Base 关键帧相机位姿与深度教师（替代 VGGT） | T2 | 下载 + PyTorch |
| ainerzero.V9.T10 / T11 | 草稿 | SAM 2.1 对象掩码 + TAPNext 点跟踪教师（S4 前） | T2 | 下载 + PyTorch/JAX |
| ainerzero.V9.T12 / T13 | 草稿 | MapAnything Apache 版几何评测台 | T2 | 下载 + PyTorch |
| ainerzero.V9.P5 / P6 | 草稿 | S5 多教师合一与教师表示对齐、RLT 开/关 | P3、T4 | 训练预算 |
| awz.V9.B7 / B8 | 草稿 | Genesis World 安装与 Metal 物理真值基准 | B1 | 安装 |

另：
- 已改写的卡：P1（S1）、P3（S2）加 r3 对照臂；B2 接口按 r3 §3 加 `canonicalize/decanonicalize`、`token_policy`；awz.V9.B5 借鉴 MOVi 任务设计。
- DINOv3 自定义许可由用户审阅，列入 ainerzero.V9.T1 授权清单。

## 10. 一致性替代（ADR-0012 修订五，awz.V9.A5）

本方案上文与 ADR-0012 修订五 §5.3 的替代表冲突时，以替代表为准，涉及：
- RSSM 的定位；
- S1 起才需要训练预算；
- 七个接口；
- T4 已获批且不依赖 T2；
- T6 用 DA3；
- `sim_truth` 只是通道；
- E1 已 superseded。

原文保留，原件归档于 `reports/V9-A1/consolidated-revision/archive/`。

## 11. 按 ARCHITECTURE_V9 r4 重新落地任务（D-019：先架构、后代码）

### 11.1 被暂停的 19 张实现卡怎么处理

| 卡 | 处理 | 放行条件 |
|---|---|---|
| ainerzero.V9.B2 接口与假实现 | **改写**：七个接口（加 `UpdateScheduler`）、`step(payload)` 吃时间白名单、GeometryCore 约定（§4 约定段）、`SpatialMemory` 版本检查与 `promote`、`TimeScaleAdapter.macro_action` | r4 经 ainerzero.V9.A6 复核并验收 |
| ainerzero.V9.G3 解析规范化 | **改写**：输入只限点、对象向量、地图坐标；等变误差按插值、边界、数值、数据关联分列报告；约定与 G1 一致 | G1 验收（G2）且 r4 验收 |
| ainerzero.V9.T2 缓存与模式守卫 | **改写**：按 T1 r1 实现单锁整段持有、内容块与来源条目两层、`cross_partition_blob`、v1 schema；真实双进程复现锁结论 | T1 验收（T14） |
| ainerzero.V9.T8 RLT 参考实现 | 原样放行 | 用户放行代码任务后 |
| ainerzero.V9.T4 教师接入与基准 | 原样放行（用户已批准） | 总门 awz.V9.A10；AinerZero 已取消交流电守卫（R20261014-power-policy），不以电源为条件 |
| ainerzero.V9.A2 基线冻结清单 | 原样放行 | 用户放行 |
| awz.V9.A3 校验器与泄露检测器 | **改写**：实现 ObservationPacket/WorldSnapshot v1.1、L10 与规则作用范围、`time_whitelist_consistent` | awz.V9.A2 r1 验收（A7） |
| awz.V9.B1 受限传感出口 | **改写**：按 v1.1 输出，`actor`/`origin`/时间白名单 | A3 验收、P3.I2 验收 |
| awz.V9.B3 考场生成器 | **改写**：按 v1.1；增加 E3 遮挡后身份考题（句柄重发） | B1 验收、forge.V9.A2 验收 |
| awz.P3.I2 小房间运行切片 | **改写**：事件日志按 Event/v1 输出，并带 `affected_ids`，供 E2a/E3 使用 | Event/v1 验收（awz.V9.A9 复核后） |
| awz.V9.D2 结构检查器、awz.V9.D4 锁定守卫 | 原样放行；D4 的版本基准用统一信封 `base` 五元组 | 用户放行 |
| awz.P3.E5 统一变更合同校验 | 原样放行 | 总门；**仍等 awz.P3.E3**：E3 原稿已有五元组、CAS、幂等 change_id/receipt、精确源摘要与崩溃恢复设计，但尚未实现验收，E5 不能绕过 |
| awz.P3.A3 Blender 切片（CPU 补修）、awz.P3.A7 渲染基线 | 原样放行 | 总门；各卡原依赖照旧 |
| awz.P3.C1、awz.P3.C3 美术闭环 | 原样放行 | 总门；C1 还要等 B1 验收（B5） |
| forge.V9.A2 经验片段校验器 | **改写**：`observation` 通道接受 `external_derived`，并在 `origin_native` 保留 `actor`（与 ObservationPacket r1 §3.11 对齐） | 用户放行，且 awz.V9.A2 r1 验收 |
| hub.P1.D2 表演曲线校验（补修） | 原样放行（打回的补修项不变） | 用户放行 |

### 11.2 新建的卡

| ID（拟） | 层级 | 内容 | 前置 | 授权 |
|---|---|---|---|---|
| awz.V9.A8 / A9 | 一级 / 复核 | Event/v1 契约（v10 字段 + 真实性层、因果父事件、所在修订）与 WorldSnapshot v1.2（`geometry_ref`、`collider_ref`、`relations`）；schema、正反例、核对脚本 | awz.V9.A2 r1 | 不需要（设计） |
| awz.V9.B9 / B10 | 二级 / 复核 | E2a 世界侧稀疏更新：依赖图、脏集合、全量回退的 CPU 参考实现；与全量更新状态哈希逐位一致；100/1000 对象 × 1%/5%/20% 变化的端到端时间与回退率 | A8、P3.I2 | 不需要（CPU，单次 ≤ 10 分钟墙钟）；暂停中，随代码任务放行 |
| awz.V9.B11 / B12 | 二级 / 复核 | E0 物理真值序列生成器（不渲染）：Blender/Bullet 无头，隐藏参数随机化，3 个种子，按世界划分；本卡只做 ≤ 100 段的 CPU 小样 | A8 | 小样不需要；**1k–10k 批量要用户批准运行预算** |
| ainerzero.V9.P7 / P8 | 草稿 | E2b 世界脑侧稀疏更新的非劣检验 | P1 | 训练预算 |
| ainerzero.V9.T15 / T16 | 草稿 | E4 教师价值（无教师 / DA2 / DA3 / V-JEPA 2.1 / 组合，完整成本） | T4、T6 | 下载与运行 |

已有草稿改写（仍是草稿）：
- ainerzero.V9.P1（S1）：并入 E1 的四组对照（有偏先验、纯 MLX、先验 + 残差、真参数上界诊断）；模型规模 0.1M–2M 起步；S1 共同口径与预登记规则。
- ainerzero.V9.P3（S2）：本层宏动作逆动力学、宏动作编码防坍塌；预登记规则。

### 11.3 放行顺序

1. **现在**（不写代码）：
   - 各复核卡照常可领：ainerzero.V9.A6、awz.V9.A6、T14、A7、G2 等；
   - Event/v1 契约设计（awz.V9.A8）可以开始。
2. **总门 awz.V9.A10 办理后**：§11.1 里“原样放行”的卡逐张放行。放行时一级逐张核原依赖、授权与文件负责人；电源只按各入口的实际策略（AinerZero 无交流电守卫，AWZ 训练按 ADR-0009）。
3. **r4 验收后**：B2、G3。
4. **T1 验收后**：T2。
5. **awz.V9.A2 验收后**：A3 → B1 → B3；forge.V9.A2。
6. **Event/v1 验收后**：P3.I2 → B9；B11 小样。
7. **用户批准后**：E0 批量、S1（含 E1）、S2、E2b、E4、E6，以及 T6/T10/T12、B5、B7、D6。

### 11.4 复核后的收口（awz.V9.A5 r2，回应 awz.V9.A6）

1. **D-019 代码放行总门 awz.V9.A10**：
   - 所有暂停的实现卡与新建代码卡（共 21 张）都以它为前置；
   - 它只在“r5 与本整合方案经非作者复核建议通过”且“用户在对话里明确同意放行代码”后办理；
   - 它是**附加门**：§11.1 的放行条件、各卡原业务依赖都照旧，例如 E5 等 E3、I2 等 I1 与 Event/v1。没有前置的代码卡也不因总门存在而自行 ready。
2. **两个基线不要混**：
   - “19 张暂停卡”是 D-019 暂停的集合，见 §11.1，全部 blocked；
   - 回复用户时提到的“12 张原样卡”是 §11.1 里标“原样放行”的那些卡，另外加了 forge B3 的后续。forge.V9.B3 不属于 19 张暂停集合，它当前 reported，仍等 forge.V9.B5 复核，不能算作已放行的实现。
3. **E3**：`awz.P3.E3`（统一变更协议）有设计、未实现验收；它与 v10 的遮挡与身份实验无关，后者写作 V10-E3（ARCHITECTURE_V9 r5 §8.3）。
4. **F1–F4 的任务落点**：
   - F1：persistent 族变更只经 Hub，AWZ 不另建可写持久库，见 WORLD_CHANGE_PROTOCOL；
   - F2：A3、B1 已写入截至时刻引用解析与实际加载路径测试；
   - F3：T2、forge.V9.A2 改按 TEACHERS_AND_CACHE r2；
   - F4：B9 按 Event/v1 r1 §4.1–§4.3。
5. **电源**：撤回本节以前写的“GPU 与渲染要接电源”“电池不跑”的笼统条件。AinerZero 已取消交流电守卫；AWZ 训练按 ADR-0009 用电池不训练；渲染没有统一电源守卫，以各卡登记为准。

## 12. 当前定版入口与实施队列（2026-10-16）

当前主架构设计基线为 **V9-r5-20261016**：[统一索引](../../../AinerZero/ARCHITECTURE_BASELINE.md)、[主架构 r5](../../../AinerZero/ARCHITECTURE_V9.md)。本节追加当前采用状态，保留 §1–§11 的历史原文；旧表的 r4、T1 r1/v1、旧复核卡与“现在可做”等指针不再单独作为开工依据。

- 用户当前只要求架构方案和任务落地，后续慢慢实现。主架构 r5 经非修订作者 `ainerzero.V9.A9` 建议接受，整合 r2 经 `awz.V9.A11` 建议接受，两张作者 A5 已接受设计。当前发布入口/版本指针由 `ainerzero.V9.A7` 收口，再由 A8 非作者复核；不是模型或生产验收。
- 代码总门 **awz.V9.A10 保持 draft**。原19实现卡全部 blocked，新增 B9/B11 draft；21卡均有总门且各卡原依赖保留。`awz.P3.A3` 漏掉的原前置 `awz.P3.A2` 已由 A7 恢复，纠正前后证据另存。E5 仍等 E3；I2 仍等 I1/Event。§11.3 第3–6步都必须同时满足总门，不能只凭某个契约验收开工。
- `awz.V9.A8` 的 Event/v1、WorldSnapshot v1.2 r1 经 A9 发现流身份、快照截止、base 时间线绑定、接触类型语义缺口，**退回补修**；新增 `awz.V9.A12` 独立复核。A9 的 accepted 是接受负面报告，不是 A8 通过。主架构 F2/F4 边界成立，不代替完整契约验收。
- `ainerzero.V9.T1` 的 teacher_cache.v2/r2 经 T17 发现 AWZ 来源组合、可信批准、blob 时间和 derivation 指纹绑定缺口，**退回补修**；新增 `ainerzero.V9.T18` 独立复核。T2 改依完成补修后的 T1 契约，不依历史 T14“验收”字样开工；Forge A2 同步，T17 accepted 只表示负面报告被采纳。
- A2 r1 的 ObservationPacket/WorldSnapshot v1.1 已按独立 A7 限范围验收；实际资产解析与信息隔离仍属 A3/B1。awz.P3.E3 已有统一事务设计、未实现验收，复用该卡，不另造事务框架。
- 当前先做两项文档补修及只读复核；以后用户明确放行代码，依原卡逐步做接口/校验/缓存→世界运行/传感/考场→稀疏验证/小样→获批教师及预登记研究。每卡原验证搭档、授权和预算照旧。完整阶段表与稳定设计变更规则见统一索引。

子契约补修与实现进度写入各自新修订及任务报告，不反复改写主架构。改变权威职责、来源政策、观察边界或科学门才提 ADR、迁移和非作者复核后升版。训练暂停不变，没有新模型或运行授权。
