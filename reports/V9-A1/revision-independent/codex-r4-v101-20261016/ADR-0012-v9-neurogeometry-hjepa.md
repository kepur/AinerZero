# ADR-0012 采用 v9 架构：NeuroGeometry × H-JEPA 三系统融合

- 状态：accepted（用户决定 D-016，2026-10-15）· 起草：Claude（统筹）· Codex 平级审议待补（任务 awz.V9.A1）
- 用户原话：「现在你首要任务是之前框架任务先放下 不适应的重新可能要推翻 架构要调整最新架构 架构一定要最优后面才不会走弯路 … 理解并实现完整落地v9架构 落地实现 重构 方案 写入任务库」；此前对话：「那直接按照这个下一代改造趁着现在刚开始」。
- 依据：[v9 RFC](../spec/AinerWorkFlow_v9_RFC.md)（用户提供，原样存档，sha256 前缀 68bf544b）；上位与关联：[ADR-0011](ADR-0011-three-systems.md)（含 D-012）、[ADR-0010](ADR-0010-v8-alignment.md)、[NORTH_STAR](../NORTH_STAR.md)。
- 落地方案：[V9_LANDING_PLAN](../design/V9_LANDING_PLAN.md)；世界脑内部架构：`AinerZero/ARCHITECTURE_V9.md`。

> 本 ADR 只定架构方向、协议归属与迁移规则。**不授权训练、下载、付费或改动他人代码**；AinerZero 训练暂停（D-008、R20261015-pause）继续有效，恢复需用户另行决定。

## 背景

ADR-0011 已确立“三系统加共享底座”。v9 在其上做三件事：

1. **世界脑升级目标**：AinerZero 从“单体 RSSM/GRU 继续堆功能”改为“几何内核 + 互补记忆 + H-JEPA 式分层潜在动力学 + 主动实验”的模块化世界脑；现有 RSSM/GRU 降为快速动力学模块与可回退基线。
2. **四个跨系统协议**：没有统一的观察与经历契约，任何新架构都无法公平验收（RFC §11 第 3 条）。
3. **前沿研究的接入方式**：H-JEPA、LeWM、V-JEPA 2.1 等只借鉴机制、在本机小模型上做同预算对照，不直接替换、不引入生产依赖。

## 决定

### 1. 三系统分工不变，边界收紧

| 系统 | v9 下的要求 |
|---|---|
| 制作脑（AinerHub） | 用现有 LLM + 技法库 + 资产库独立出片，不等世界脑；新增五种执行策略（WORLD_NATIVE / IMAGE_GUIDED / KEYFRAME_GUIDED / HYBRID_NEURAL / FULL_DIFFUSION），扩散产物不自动变成可编辑世界 |
| 世界系统（AnimeWorldZero + AinerHub 持久世界库） | 确定性运行、机制包、语义、状态与事件、受限观察出口与考场；**不训练与 AinerZero 竞争的认知世界模型**；程序化生成器与美术专项模型可以有，但不宣称是世界模型 |
| 世界脑（AinerZero） | 唯一学习世界的脑；只能从受限观察形成概率信念；通过 `SkillProposal` 经能力门禁提出行动，不直接写世界 |

D-012 的权威划分原样有效。

### 2. 四个协议的归属

| 协议 | 权威 | 落点 | 说明 |
|---|---|---|---|
| `WorldSnapshot/v1` | AWZ 运行内核 | `contracts/v9/`（awz.V9.A2） | 渲染、评测、回放用；**不是学生输入** |
| `ObservationPacket/v1` | AWZ 受限传感出口 | `contracts/v9/`（awz.V9.A2） | 学生唯一输入；字段级真值泄露规则写进契约并有检测器 |
| `SkillProposal/v1` | AinerZero | AinerZero `contracts/v9/`（ainerzero.V9.B1） | 只能提案，经 AWZ 命令门禁；不能直接改世界库 |
| `ExperienceEpisode/v1` | 经验平台 = AinerForge | 建在 APACK 分片上（forge.V9.A1） | 自观察、教师断言/示范、仿真真值分区；沿用 APACK 的分区、封存与来源词表，不另起格式 |

世界变更只有一个信封：`base_revision`、`scope`、`locks`、`WorldDelta`。它就是 awz.P3.E3（E1 与 AinerHub WorldDelta 合并）的产物；awz.P3.E1 不再单独出 r3，E4、awz.P3.E7 的复核发现并入 E3。

### 3. AWZ 的 W 轨收束

ADR-0010 已把 AWZ 的 W0–W3 定为“参照模型，不算 AinerZero 能力”。v9 进一步收紧：

- W1（对象动力学）、W3（潜在动力学）**不再在 AWZ 训练**。W1 的数据生成器与评测转为考场生成器和 AinerZero 的对照基线；T08 结果（Gate B 未过，神经模型劣于规则基线）如实存档。
- W2（线稿编码器）属于美术专项，可保留在世界系统/风格侧。
- 正在进行的 awz.P2.W6 独立复核照常完成，W2 按“流程合格、能力未过”终审；结案与迁移由 awz.V9.C1 执行。

### 4. 世界脑的目标架构与路线

- 目标架构见 `AinerZero/ARCHITECTURE_V9.md`：感知与对象绑定 → NeuroGeometry 内核（SE(3)、信念滤波、认知地图）→ 快/中/慢三层动力学 → 情景记忆与慢速巩固 → 分层规划 → 学习进展与主动实验。
- 路线沿用 RFC §9：P0 契约与接口（现在做，无训练）→ P1 世界系统优先 → P2 记忆与连续时间 → P3 2D 空间认知 → P4 两层 H-JEPA 式时间抽象 → P5 视觉与对象几何 → P6 自驱成长。**P2 起每一步都要用户批准训练预算**，且只有在同数据、同预算、同观测下独立评测胜过上一级基线才晋升。
- 现有 RSSM/GRU、D 候选、C0/GridLab 检查点与全部失败记录只读保留，作为可回退基线；P1 历史旁路保留为消融候选，不视为已成功。

### 5. 研究适配注册表

H-JEPA、LeWM、V-JEPA 2.1、DreamerV3、Stable WorldModel、EGNN、Slot Attention 等进入只读的 Research Adapter Registry（ainerzero.V9.R1）：记录论文、仓库、许可、可借鉴机制、MLX 可行性与不可推断项。**下载代码、权重或数据集一律先经用户批准**；外部预训练特征（例如 V-JEPA 2.1）只能作教师或基线，并在来源与能力描述中注明，不得宣称从零自主学得。

### 6. 验收规范

采用 RFC §10 的九个维度（基线保留、记忆、时间、空间、动态、规划、自驱、艺术、系统），每个维度的反作弊项写进对应任务卡。所有判定用断言，测试要有“故意改坏必须变红”的对照。

## 不变

- ADR-0001–0011 与 D-001–D-015 全部有效；本 ADR 不覆盖其中任何明确禁止事项。
- 训练暂停、下载与付费须经用户批准、素材许可（自产/CC0）不变。
- P3 世界系统任务（Blender 主路径、生成器、风格与角色包、世界运行 I1–I3、`.aworld`、交换格式）全部保留并优先推进。

## 后果

- **好处**：世界脑有了明确的模块边界与可替换接口，旧基线可随时回退；三系统通过四个协议协作，各自独立验收；前沿研究以同预算对照进入，不靠论文成绩替代本机实验。
- **代价**：先做契约与接口，世界脑短期内没有新训练成果；AWZ 的 W 轨投入结案。
- **风险**：H-JEPA 在本项目场景的收益尚无本机证据；MLX 移植成本未知；分层与模块化不自动更快，需实测。

## 后续任务

见 [V9_LANDING_PLAN](../design/V9_LANDING_PLAN.md) 第 4 节：awz.V9.*、ainerzero.V9.*、forge.V9.*、hub.V9.*。

## 修订一（2026-10-16，用户指示）：世界脑取最优方案、研究顺序改为空间优先

- 用户原话：「你不要想着融合 一切都是以最牛逼最优的方案去做这样后面才不会多走弯路从新搞」「最先研究 SE(3) 空间表示、认知地图和多时间尺度模型，同时保持原来的记忆干扰实验不被新结构掩盖」。
- 决定 4 据此修订：旧 RSSM/GRU **不并入**新架构，只作对照基线；新架构为“几何化的结构状态 × 地图即记忆 × H-JEPA 式分层预测（每层含逆动力学项）”，详见 `AinerZero/ARCHITECTURE_V9.md` r2 与调研 `AinerZero/docs/research/V9_RESEARCH_SURVEY.md`。
- 研究顺序改为 S0 数学核心（现在、不训练）→ S1 空间与认知地图 → S2 多时间尺度 → S3 记忆检索与巩固 → S4 对象 → S5 视觉 → S6 自驱；S1 起每级需用户批准训练预算。M2 记忆干扰诊断作为每级的常设对照。

## 修订二（2026-10-16，用户指示）：AinerWorkFlow 9.1 —— 3D 创作与评测平面（3D Creation & Evaluation Plane）

- 用户原话：「其中 blenderworld_adapter 是可选插件，可以关闭而不影响正常动漫生产。所有生成和修复都必须经过 AnimeWorld 的世界状态与版本验证，不能允许 Agent 为了提高视觉评分，悄悄修改用户已经锁定的角色、镜头或剧情事件。… 值得融入，但不要把 BlenderWorld 当作世界模型或新的主引擎 … 正式进入 AinerWorkFlow 9.1，命名为 3D Creation & Evaluation Plane。」
- 核实（2026-10-16，github.com/QwenLM/BlenderWorld 与其 docs）：BlenderWorld 是“从真实参考到可编辑 Blender 场景”的**评测基准**——223 个任务、2,651 条加权二元判据（文本 78 / 图文 130 / 视频文 15），交付 `.blend` 与导出；评分 = 50% 判据（场景检查由 Agent 裁判，视觉判据由 VLM）+ 50% 八个画质维度；代码 MIT。官方评测要求 **Linux、Blender 4.2.10（版本不符即中止）、Claude Code CLI 与付费视觉模型接口**；数据集许可在文档中未写明（需看 HuggingFace 数据卡）。
- 决定：
  1. **平面定位**：横跨制作脑与世界系统的“创作—评测”平面；不是世界模型、不是主引擎、不替代 Blender 主路径与 RenderBackend 契约。
  2. **方法原生化**：在 AWZ 原生实现场景质量评测协议，吸收 BlenderWorld 的方法（加权二元判据、结构与视觉分路、每次新鲜渲染、缺交/失败计零、结构结论不得用视觉猜测顶替），并以**确定性结构检查优先**（Blender 只读脚本检查 `.blend`），LLM/VLM 只判语义与画质；付费评测接口按次经用户批准。
  3. **`blenderworld_adapter` 为可选插件**：默认关闭；负责我方产出与官方提交格式互转，以及（用户批准后）在官方环境跑外部对标。关闭它不影响生产。
  4. **锁定守卫**：所有生成与修复只能经 E3 世界命令信封（base_revision、scope、locks、WorldDelta）提交，并通过 AWZ 世界状态与版本验证；触碰用户锁定的角色、镜头、剧情事件一律拒绝，与评分无关；必须有“为提分改锁定字段”的对抗测试。
  5. **数据**：生成轨迹与用户修正以 `agent_trajectory`、`user_correction` 来源进入 Forge ExperienceEpisode，只供场景规划、美术策略等专项模型；不得作为 AinerZero 物理理解的证据。
- 不变：AinerZero 继续独立研究时空理解、记忆与行动规划；训练、下载、安装、付费仍需用户批准。

## 修订三（2026-10-16，用户提供《AinerZero M2 Max 96GB 无 CUDA 集成与训练降本方案》，要求“结合集成”）

- 原件存档：`AinerZero/docs/research/M2Max_NoCUDA_Integration_Plan.source.md`；评审结论写入 `AinerZero/ARCHITECTURE_V9.md` §7。
- 本机核实：MacBook Pro M2 Max（38 核 GPU）、96 GB、MLX 0.32.x、未装 PyTorch。
- 采纳：离线教师 + 特征缓存 + 原生 MLX 小型学生 + Blender 仿真真值；Teacher / Train / World 三种运行模式与内存互斥；1/5/10/30 步误差、碰撞事件 F1、ID 切换、恒速/解析物理/冻结特征基线；同质量阈值下实测成本。
- 改进：几何教师当带噪声的传感器接入信念滤波，不当真值；仿真真值监督单独分区并在能力声明中注明；SIGReg 取原作者 LeWM 定义。
- 顺序：教师接入（T）与 S0 并行，S1 设结构化观察与冻结视觉教师特征两条观察臂；原 S5 改为学生端编码器蒸馏/微调对照。
- 归属：WorldForge 归制作脑混合神经策略；Hunyuan3D 只作资产服务（地域限制、产出禁止进入训练）；高斯泼溅归 P3-H1；Cosmos 只作参考。
- 授权：所有下载与安装（vjepa2-mlx 与 V-JEPA 2.1 权重、Depth Anything V2 Small Core ML、V-JEPA2-AC MLX、PyTorch 与 VGGT-1B）逐项需用户批准；**VGGT-1B 权重为 CC-BY-NC-4.0**，用于本项目前需许可审查与用户决定；Blender 合成数据的渲染预算需批准。

## 修订四（2026-10-16，用户「全部写入」，D-017）：前沿技术增补

- 依据：`AinerZero/docs/research/V9_FRONTIER_COST_SURVEY.md`。架构文本见 `AinerZero/ARCHITECTURE_V9.md` r3（§1 两条新决定、式 9–11、§5 各阶段对照臂、§7.3 教师清单、§7.6 降本手段清单）。
- 世界脑侧决定：
  1. SE(2) 等变改由**解析规范化**获得：用估计位姿换到重力对齐的智能体坐标系，再接普通网络。等变图网络只留给对象间相互作用。
  2. 几何教师用 **DA3-Small/Base（Apache 2.0）替代 VGGT-1B（CC-BY-NC-4.0）**；VGGT 不再下载，只作论文结果对照。
  3. 视频输入加 **RLT 停帧去重**（动漫有限动画收益可能更大，须实测）。
  4. S5 起做**多教师合一**的学生编码器和教师表示对齐；S2 只把对齐作消融。
  5. 对照臂：S1 加 Muon、多步滚动训练；S2 加多频率更新；S3 加 Titans 式记忆；S4 加 SlotSSMs、SAM 2.1、TAPNext；S6 加 epinet。
- 世界系统侧决定：
  - Genesis World（Apache-2.0，可编译到 Apple Metal）作为多物理真值候选，Blender 继续负责渲染与可编辑场景；
  - Kubric/MOVi 只借鉴任务设计。
- 授权不变：
  - 需批准：所有下载与安装（DA3、PyTorch、SAM 2.1、TAPNext、MapAnything、Genesis）、DINOv3 自定义许可审阅、任何训练和新的 GPU 运行；
  - 论文加速倍数只作假设。

## 修订五（2026-10-16）：v10 工程验证层、验收独立性规则、先架构后代码；正文一致性替代表

本段只追加，不覆盖上文已接受的历史决定。上文与本段冲突时，以本段和下面的替代表为准。

### 5.1 用户决定
- **D-018**（「改」）：两位一级不分彼此；作者的交付经非作者复核建议通过后，作者可办验收。
- **D-019**（「先不要动代码 先改写架构  架构方案和任务落地 再开始实现代码任务」）：
  - 19 张写代码的实现卡暂停；
  - 架构改写为 `AinerZero/ARCHITECTURE_V9.md` r4（ainerzero.V9.A5）；
  - 任务按 r4 重新落地（`docs/design/V9_LANDING_PLAN.md` §11）后再放行。
- 用户提供《AinerZero v10 架构验证》（存档 `AinerZero/docs/research/AinerZero_v10_Architecture_Validation.source.md`），作为工程验证层并入 r4 §8，不替代 v9 主线。

### 5.2 跨系统新增
1. **世界真值与世界脑信念分开**：AWZ 快照只放权威状态；置信度、证据引用、推断量只在 AinerZero 信念里。
2. **Event/v1 契约**（新卡，AWZ）：
   - v10 字段：`event_id`、`tick`、`source`、`affected_ids`、`event_type`、`payload`、`evidence_ref`；
   - 加上真实性层、因果父事件、所在修订。
   同卡增补 WorldSnapshot v1.2：`geometry_ref`、`collider_ref`、`relations`。
3. **事件驱动稀疏更新**：
   - AWZ 运行时：要求与全量更新状态哈希逐位一致；
   - AinerZero 信念更新：要求非劣（配对 bootstrap 上界 `U ≤ δ`）。
4. **验证实验 E0–E6** 按 r4 §8.3 预登记。其中 E1 的物理先验必须带登记的偏差（数据端随机化隐藏参数）；E4 不含 VGGT。
5. **“Serafina”** 暂定对应 AinerRelay + relay-runner，待用户确认，确认前不新建调度器。

### 5.3 正文一致性替代表（依 Codex 2026-10-16 平级审议，awz.V9.A1）

| 上文位置 | 原写法 | 以此为准 |
|---|---|---|
| 背景第 1 条、决定 4 第 1 段 | “现有 RSSM/GRU 降为快速动力学模块与可回退基线”；“快/中/慢三层动力学” | **已被修订一替代**：RSSM/GRU 退出新主线，只作对照基线；新架构见 ARCHITECTURE_V9 r4 |
| 决定 4 第 2 段 | “路线沿用 RFC §9 … P2 起每一步都要用户批准训练预算” | 研究顺序以修订一与 r4 §5 为准（S0 → V0 → S1 → S2 → S3–S6，T 与 S0 并行）；**S1 起**每一级都要用户批准训练预算 |
| 落地方案 §3 P0 行 | “世界脑五个可替换接口” | 统一为接口清单 r4 §3：**七个**（r3 的六个 + `UpdateScheduler`） |
| 落地方案 §8 T4/T5 行 | “草稿，依赖 T2，下载与安装待批” | T4 已由用户单独批准（AinerZero R20261016-T4），不依赖 T2；现因 D-019 暂停，放行时还要确认接了电源 |
| 修订三、落地方案 §8 T6/T7 行 | “VGGT-1B 关键帧批处理” | 以修订四与落地方案 §9 为准：T6 用 **DA3-Small/Base（Apache 2.0）**，VGGT 不下载 |
| 修订三、落地方案 §8 B5 行与“另：”段 | “sim_truth 分区”“forge.V9.A1 增加 sim_truth 来源” | `sim_truth` 只是**监督通道**，来源沿用 `simulator_truth`，分区仍为 `train`/`development`/`final`/`quarantine` 四值（forge.V9.A1 已验收口径） |
| 背景说明与修订三的训练暂停 | — | 训练暂停只针对 AinerZero 训练；T4 的推理基准获批不等于恢复训练 |
| 修订一里 E1 的处理 | — | awz.P3.E1 已按用户迁移决定取消为 superseded，E4/E7 的负面报告已验收，四项必补并入 E3；E1 不出 r3 |
| AWZ 观察的来源 | — | 实时出口的包来源仍是 `external_derived`（ADR-0005）；能否训练需要另行登记 ADR-0005 修订（ObservationPacket r1 §3.11） |
