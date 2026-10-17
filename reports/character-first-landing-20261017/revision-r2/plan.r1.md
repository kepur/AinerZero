# Character First 设计与任务落地计划

扩展 ID：**CF-r1-20261017**；2026-10-17；主责 Codex；二级文档执行 proposal_writer；非作者核对 character_inventory。
采用口径：用户已同意方向与方案落地；本文件与[ADR-0013](../adr/ADR-0013-character-first-production.md)为CF-r1设计正文。最终采用状态与精确SHA见本轮[DECISION](../../../AinerZero/reports/character-first-landing-20261017/DECISION.md)、[publication.json](../../../AinerZero/reports/character-first-landing-20261017/publication.json)及工作台awz.CF.A3发布记录（登记中）；不以正文冻结时的流程状态冒充发布结果。现行 [V9-r5-20261016](../../../AinerZero/ARCHITECTURE_BASELINE.md) 与原 baseline JSON 保持有效。
用户已明确工作台为既有 AinerRelay；本轮不新建网站。AinerStudio 角色曲线编辑是下列实现候选的一部分，不表示已经可用。
旧方案及原始评审见 [PROPOSAL](../../../AinerZero/reports/architecture-character-first-20261017/PROPOSAL.md)、[REVIEW](../../../AinerZero/reports/architecture-character-first-20261017/REVIEW.md)、[DECISION](../../../AinerZero/reports/architecture-character-first-20261017/DECISION.md)。

## 1. 阶段和执行权限

| 阶段 | 交付目标 | 现阶段状态 |
|---|---|---|
| 0 合同/消费者映射 | 已有能力与缺口、身份/时钟/控制权、无环版本边界、原卡复用 | 文档设计与只读复核可推进 |
| 1 真实角色竖切 | runtime 绑定、统一 Hub worker、最小编译 DAG/缓存；基础身份从此开始 | 实现候选，受 A10 和业务依赖阻塞 |
| 2 同批 P0 同步表演 | Body+Face/Gaze/Hands/Voice、编辑提交/回放，10 秒有台词与情绪的表演 | 拆为小卡并保持同批目标；无运行授权 |
| 3 接触与双人 | 根轨迹/计划接触/共享节拍/最终校验、单一物理域 | 前阶段正确性通过后才推进 |
| 4 完整 QA | 跨镜头与完整 15 秒、480p/24fps/360 帧、可编辑证据和成本 | 另冻结门槛/输入/预算后执行 |
| 5 可选研究 | 已复现缺口的神经/REA 旁路 | 默认关闭、非阻塞；无下载/运行授权 |

设计采用、文档发布、代码开工、运行登记、工程通过、视觉/能力和生产验证分别记状态。用户本轮同意不打开 `awz.V9.A10`，不授权训练、下载、模型或渲染实跑。
所有实现候选都必须附加 **A10 + 每卡原业务前置 + 对应非作者验证**；真实运行再单独冻结输入、argv、预算和停止条件。AinerZero 保持暂停。
本轮已登记29张awz.CF/hub.CF卡；下列为正式ID，**当前状态以[registration-result](../../../AinerZero/reports/character-first-landing-20261017/workbench/registration-result.json)与live为准**。原 CF 本地键不另建重复卡；未来X14仅保留文档，不登记执行卡。

### 本轮文档链（主模块均为0.1）

| 正式ID | 层级/needs | 前置/文件范围/交付 | 状态与验证 |
|---|---|---|---|
| awz.CF.A1 | 二级文档，text | 本轮已授权11份当前入口/追加记录、ADR-0013、此计划、AZ报告目录；精确scope按CLAIM/source-before及工作台payload | 整理中；非作者awz.CF.A2，不自行验收 |
| awz.CF.A2 | 二级只读核对，text | A1；核文档/扩展清单、29新卡/模块、A3唯一有意增依赖、其他原卡/项目配置与paused保持 | 待A1交付；只写独立报告，不改交付 |
| awz.CF.A3 | 一级主责发布，text | A1+A2建议通过；核确切身份、追加采用决定与registration报告引用 | 发布未完成；不打开代码门/运行预算 |

awz.CF.B1设计映射登记为ready但依赖awz.CF.A3发布，未满足前不可执行；awz.CF.B2等待awz.CF.B1。其余产品实现与验证全部blocked；登记不构成执行。未来X14无本轮卡。

## 2. 既有卡与模块复用

模块号来自主责本轮工作台盘点；登记时按现有名称和 legacy 共享 JSON 实际核对，不依赖未部署的 catalogue 接口，不升级工作台源码。

| 模块 | 本轮用途 | 复用边界 |
|---|---|---|
| 4.10 制作计划/控制编译 | 制作计划/控制合同映射 | 复用 awz.P3.J1、hub.V9.A1–A5 的既有谱系，不复制叙事/制作计划 |
| 4.6 表演指导 | Hub 意图/编辑、CPU 校验和同步表演消费 | 复用 hub.P1.D1–D4/D6；D1/D2 原文件仍归原卡，新增卡不抢写 |
| 1.3.4 角色控制权/运行 | 可执行绑定、Body、接触与编排 | 与 awz.P3.I1/I2、E3/E5 和运行控制权合同一致 |
| 1.3.3 台词口型 | 锁定声音/口型/表情同步 | 不改定稿音频、不另建声纹/身份系统 |
| 1.4.3 角色包 | D5/D10/D11 的控制面、身份引用 | 当前 paused=true，不解冻原卡或重写资产；新 runtime 绑定等其通过 |
| 1.4.2 GateID/CCIP | 身份 QA 的既有门 | CPUFake 不是真实评分，真实入口未接通则报告未验证 |
| 1.5.3 Blender NPR/ACIS | 基础外观及跨镜头 QA | 复用 awz.P3.D2，不以 canny 或旧 Godot 金样冒充 Blender 正式门 |
| 3.5.2 Blender 主路径 | 真实角色和统一 Hub worker | 复用 awz.P3.A3/A4，保留原 P3.A2 前置及预算 |
| 1.2.2 场景编译 | 跨工具 Compiler/DAG/缓存缺口 | 当前无任务，可承载新增编译任务；不混入 1.1.2 世界侧稀疏求值 |

同一实际文件同一时刻只有一名编辑负责人；登记前先核原卡状态/范围/历史作者。表内复用原卡仅追加补齐交付，不重复创建相同实现卡。
主责允许唯一旧卡变更：对awz.P3.A3只增前置awz.CF.B2、awz.CF.C2、hub.CF.B2，保留其全部原依赖/status/file_scope/params；这是收紧真实角色/统一worker前置，不放行代码。runtime绑定和Hubworker不得反依赖AWZA3完成；其他旧卡不改。

## 3. 必须在落卡时固定的合同

Hub 意图/编辑 → 外层编译 → AWZ 准入/运行求值 → Hub worker；Hub 唯一持久世界库、AWZ 唯一运行权威不变。worker 的离线求解产候选，不能直接写真值。
一代编译绑定 base B：`solve(B) → candidate(B,k) → adopt(B,k) → approved(B+1) → render(B+1)`。拒绝或新修订另起 generation；旧节点输入不可被回写。
多角色共享接触在一个有界联合求解节点内完成，或明确有限迭代/终止条件后统一采用；不得把角色之间反馈写成相互等待的任务环。
最小派生 IR 只含 plan、world_snapshot_ref、performance/action refs、render job 与版本/依赖；E3 五元组、事务信封、A2 时间白名单和来源不替换。
保持 120Hz、半开区间、24fps=5tick/帧；音频保持原字节 digest/采样时钟/对齐，嘴型缺可信音频则 unsupported。改声速/留白只能产生新版本并重新定稿。
Body、Face、Gaze、Hands、Voice 分轨同步；情绪和 mouth 在同一实际部位相交时，登记唯一 blend owner 和明确合成规则。v0 无 priority/weight 字段，需这些字段先升合同，不能偷加。
rig/control 绑定须解析实际别名与单位/域/版本，pending/unsupported 永不执行；能力声明、资产存在、真实权限和执行证据分别核对。
风格化/重定时之后再次验接触/穿模/足滑/连续性；计划接触、实际事件、表现效果分离，夸张声明 mechanism/作用域。
一个权威物理域，轨迹烘焙；Blender/Bullet 不双写。ADR-0007 无历史帧依赖，随机访问和顺序结果须按登记域/图像容差比较。
最小缓存身份先于竖切：E3、动作/rig/曲线依赖、算法/适配器/seed、物理步长/顺序/暖启动、后端/色彩/相机/输出设置。命中仍重验锁/版本/来源/分区。
早期接触改动沿闭包传播，无有效检查点重算整段；相机只重渲染；嘴型独立性证明不足则扩大重算。内容复用不授训练资格。
学习侧只读允许观察，不读真值 ID、隐藏接触、完整缓存、封存 QA/反例标签；external_derived 默认拒训，研究注册表不等于执行能力表。

## 4. 可逐张登记的任务正文

以下拟定新路径只界定候选范围，**登记前核存在性、原卡占用和接口归属**；本文件不创建这些路径或执行代码。验证卡只能写独立报告/独立夹具目录，不能改实现交付或重生成原证据。
每张验证卡须核确切源码/资产身份并独立构造坏对照；作者不领自己的验证卡。needs只用Relay固定词表 text/code/math/vision/godot/multimodal/longrun；专业说明不作为needs。每卡仅一个主模块，其他模块只读关联。

### awz.CF.B1 合同与实际消费者映射（阶段 0）

- 层级/needs/项目模块：二级文档设计；`text, code`；awz，主模块4.10；4.6/1.2.2为只读关联。
- 前置（本轮在线登记值）：awz.CF.A3；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`docs/design/CHARACTER_CONSUMER_MAP.md`、`reports/CF-B1`；登记不创建产品文件。
- 交付：字段→控制器→求值→worker→编辑回放映射；列真实资产/通道缺口、情绪/口型重叠部位 blend owner、音频和单位/时间映射、solve/adopt/render 版本图。
- 验证/正反例：awz.CF.B2（非作者，`text, code`），核合法映射；错骨/别名重复写者、float 秒/双闭边界、pending 执行、隐式权重必须列为拒绝或缺口。
- 状态：ready，依赖awz.CF.A3发布；本轮仅完成计划正文，未执行本设计映射卡，实际可领取条件以live为准。

### awz.CF.C1 runtime rig/control 可执行绑定（阶段 1）

- 层级/needs/项目模块：二级实现；`code, math`（控制合同/rig绑定）；awz，主模块1.3.4；1.4.3只引用不解冻。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.P3.D5、awz.P3.D10、awz.P3.D11、hub.P1.D1、hub.P1.D2、hub.P1.D6、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A2、awz.V9.A7、awz.P3.I1、awz.P3.I2、awz.P3.I3；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/performance/control_registry.py`、`tests/performance/test_control_registry.py`、`reports/CF-C1`；登记不创建产品文件。
- 交付：角色/rig/控制器精确版本与实际部位别名映射；域/单位/可执行证据；缺能力 fail-closed，显式 blend 规则引用。
- 验证/正反例：awz.CF.C2（非作者，`code, math`）；合法冻结资产绑定通过，错 rig/过期身份/别名冲突/pending 自称 executable 拒绝。
- 状态：blocked（本轮在线登记值）；角色包 paused 原样，不能因新卡绕开。

### CF-W03A 真实角色进入统一渲染桥（复用原 awz.P3.A3，阶段 1）

- 层级/needs/项目模块：二级原卡补齐；`code, vision`（Blender/RenderBackend）；awz，主模块3.5.2；原验证awz.P3.A4。
- 前置：A10、原 awz.P3.A2、awz.CF.B1/awz.CF.B2、awz.CF.C1/awz.CF.C2、hub.CF.B1 交付；原 A3 其余依赖与预算照旧。
- 文件范围：原卡范围内 `python/animeworld/render_backend/blender_adapter.py`、`tools/blender/backend/eevee_slice.py` 及原测试/报告；登记时由原卡负责人确认，不另开同文件实现卡。
- 交付：AWZ 核准状态/曲线→Hub 既有 worker 的桥；实际角色/rig/身份摘要入报告，旧代理球探针保留为历史证据。
- 验证/正反例：原 A4 非作者链，追加真实角色加载及曲线消费；代理球冒充角色、错资产 hash、未核准状态、缺 required 通道拒绝。
- 状态：仅提出原卡补充正文，已按主责裁决仅追加CF验证前置，status/file_scope/params与全部原依赖保留；真实渲染须原预算或新冻结批准。

### hub.CF.B1 Hub worker 消费核准产物（阶段 1）

- 层级/needs/项目模块：二级实现；`code, vision`（Blender消费）；hub，主模块3.5.2；4.6只读关联。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、awz.CF.D2、awz.CF.D4、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A2、awz.V9.A7、awz.P3.A2；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`code/apps/ainer-core/app/director/blender_worker/world_multicam.py`、`code/apps/ainer-core/app/worldmodel/blender_run.py`、`code/apps/ainer-core/app/director/blender_worker/loaders/approved_performance.py`、`code/apps/ainer-core/tests/test_approved_performance.py`、`reports/CF-B1`；登记不创建产品文件。
- 交付：现有 worker 只读加载 approved 版本、真实 rig/曲线/身份，candidate 求解与 render 分入口；不在 worker 写世界。
- 验证/正反例：hub.CF.B2（非作者，`code, vision`）；核合法加载，candidate 未采用/旧版本/错 hash/未授权世界写入必须失败。
- 状态：blocked（本轮在线登记值）；与原 A3 分仓分文件交付，集成由原 A3/A4 验证。

### awz.CF.D1 最小跨工具编译 DAG（阶段 1）

- 层级/needs/项目模块：二级实现；`code, math`（DAG合同）；awz，主模块1.2.2；不占1.1.2稀疏求值。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A2、awz.V9.A7、awz.P3.J1、hub.V9.A1、hub.V9.A2、hub.V9.A5；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/production_compiler/graph.py`、`tests/production_compiler/test_graph.py`、`reports/CF-D1`；登记不创建产品文件。
- 交付：最小派生 IR 与 solve/adopt/render 节点/版本；依赖固定、拒绝环、候选失败保留、revision 冲突拒绝。
- 验证/正反例：awz.CF.D2（非作者，`code, math`）；合法无环图；循环依赖、B 变更仍采用旧候选、render 读取未采用候选拒绝。
- 状态：blocked（本轮在线登记值）；不自建新 scheduler/Serafina。

### awz.CF.D3 最小内容缓存与失效（阶段 1）

- 层级/needs/项目模块：二级实现；`code, math`（缓存/来源合同）；awz，主模块1.2.2。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.D2、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A2、awz.V9.A7；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/production_compiler/cache.py`、`tests/production_compiler/test_cache.py`、`reports/CF-D3`；登记不创建产品文件。
- 交付：内容键、来源资格分离、闭包失效、安全全段回退、成本日志；优化范围在正确性后扩展。
- 验证/正反例：awz.CF.D4（非作者，`code, math`）；合法命中；换 seed/步长/暖启动/后端仍命中、跨分区资格复用、接触前置漏传播必须变红。
- 状态：blocked（本轮在线登记值）；缓存命中不产生运行授权或训练资格。

### awz.CF.E1 Body/Gaze/Hands 同步曲线编译（阶段 2，同批 P0）

- 层级/needs/项目模块：二级实现；`code, math`（动作/rig）；awz，主模块1.3.4；4.6只读关联。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、awz.CF.D2、awz.CF.D4、awz.P3.I1、awz.P3.I2、awz.P3.I3、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A8、awz.V9.A9、awz.V9.A13、awz.V9.A12、hub.P1.D1、hub.P1.D2、hub.P1.D6；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/performance/body_compile.py`、`tests/performance/test_body_compile.py`、`reports/CF-E1`；登记不创建产品文件。
- 交付：120Hz/半开曲线、根运动/姿态/注视/手势映射、单写者、候选输出与编辑层；角色不支持的动作明确 unsupported。
- 验证/正反例：awz.CF.E2（非作者，`code, math`）；合法时间段/姿态；错单位/骨架/边界双写、用户锁覆盖、已播历史变更拒绝。
- 状态：blocked（本轮在线登记值）；与 awz.CF.E3/hub.CF.C1/hub.CF.D1 作为同批 P0，不单以走路完成整批验收。

### awz.CF.E3 Face/Voice/Mouth 同步编译（阶段 2，同批 P0）

- 层级/needs/项目模块：二级实现；`code, math`（音频时钟/面部）；awz，主模块1.3.3；4.6只读关联。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、awz.CF.D2、awz.CF.D4、hub.P1.D1、hub.P1.D2、hub.P1.D6、awz.P3.D5、awz.P3.D10、awz.P3.D11、awz.P3.E3、awz.P3.E5、awz.P3.E6；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/performance/facial_compile.py`、`tests/performance/test_facial_compile.py`、`reports/CF-E3`；登记不创建产品文件。
- 交付：情绪/表情/口型/视线同步；唯一实际嘴部 blend owner；固定 audio digest/sample 映射；无对齐返回 unsupported，不生成或下载声音模型。
- 验证/正反例：awz.CF.E4（非作者，`code, math`）；合法定稿音频；错音频/重音/采样时钟、嘴型覆盖情绪、重复部位写者、偷偷变速拒绝。
- 状态：blocked（本轮在线登记值）；与awz.CF.E1同批 P0，改变音频须新版本重新定稿。

### hub.CF.C1 Hub 表演版本提交与回放消费者（阶段 2，同批 P0）

- 层级/needs/项目模块：二级实现；`code`（API/表演合同）；hub，主模块4.6。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、hub.P1.D1、hub.P1.D2、hub.P1.D6、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A2、awz.V9.A7；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`code/apps/ainer-core/app/production/performance_adapter.py`、`code/apps/ainer-core/app/api/v2/production.py`、`code/apps/ainer-core/tests/test_performance_adapter.py`、`reports/CF-C1`；登记不创建产品文件。
- 交付：编辑提案→版本/锁/时钟核对→AWZ adopt→批准曲线回读；新 take/receipt 与历史保留，错误不伪成功。
- 验证/正反例：hub.CF.C2（非作者，`code`）；合法版本提交/回放；stale revision、锁冲突、过去区间修改、候选直接当 approved 拒绝。
- 状态：blocked（本轮在线登记值）；不把 CPU 合同通过写为跨仓 E2E。

### hub.CF.D1 AinerStudio 可编辑表演曲线（阶段 2，同批 P0）

- 层级/needs/项目模块：二级实现；`code, vision`（前端编辑）；hub，主模块4.6。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、hub.CF.C2、hub.P1.D1、hub.P1.D2、hub.P1.D6；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`code/apps/ainer-studio/src/performance`、`code/apps/ainer-studio/src/Root.tsx`、`reports/CF-D1`；登记不创建产品文件。
- 交付：分轨/实际部位/锁/unsupported 展示，关键帧编辑、版本提交/冲突反馈、重新加载核准曲线与回放；UI 不直接写世界。
- 验证/正反例：hub.CF.D2（非作者，`code, vision`）；实际拖动后核准曲线与回放改变；UI 假保存、口型覆盖情绪、绕锁或丢单位必须失败。
- 状态：blocked（本轮在线登记值）；“工作台”新增 UI 只指此候选，不是本轮网站交付。

### awz.CF.F1 基础 ACIS/TACE 身份与真实通道（阶段 1 起持续）

- 层级/needs/项目模块：二级集成/QA；`code, vision`；awz，主模块1.4.2；1.5.3只读关联，NPR复用原awz.P3.D2/D3。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、awz.CF.D4、hub.CF.B2、awz.P3.A3、awz.P3.A4、awz.P3.D2、awz.P3.D3、awz.P3.D5、awz.P3.D10、awz.P3.D11；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`tools/character_qa/basic_identity.py`、`tests/character_qa/test_basic_identity.py`、`reports/CF-F1`；登记不创建产品文件。
- 交付：真实角色/rig/几何材质摘要、实际通道/unsupported 报告、基础身份/调色板/轮廓与编辑稳定；真实评分未接通则明示未验证。
- 验证/正反例：awz.CF.F2（非作者，`code, vision`）；固定身份对照；交换角色/网格、假 CCIP、代理球、缺 required 通道须被识别或拒绝。
- 状态：blocked（本轮在线登记值）；基础门随首个竖切启动，不等双人完成；渲染采集另登记预算。

### awz.CF.G1 根轨迹/接触计划与最终校验（阶段 3）

- 层级/needs/项目模块：二级实现；`code, math`（动作接触）；awz，主模块1.3.4。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.E2、awz.CF.E4、hub.CF.C2、hub.CF.D2、awz.CF.F2、awz.P3.I1、awz.P3.I2、awz.P3.I3、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A8、awz.V9.A9、awz.V9.A13、awz.V9.A12；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/choreography/contact_plan.py`、`python/animeworld/choreography/final_validate.py`、`tests/choreography/test_contact_plan.py`、`tests/choreography/test_final_validate.py`、`reports/CF-G1`；登记不创建产品文件。
- 交付：BeatGraph、根轨迹、手脚/道具计划接触；单物理域烘焙；风格化/重定时后再验真实接触/连续性并采用。
- 验证/正反例：awz.CF.G2（非作者，`code, math`）；合法接触；时序错位、删接触修正、夸张当真值、风格化后穿模必须失败。
- 状态：blocked（本轮在线登记值）；求解/真实仿真预算另冻结，不能从设计采用继承。

### awz.CF.G3 双人共享节拍与联合约束（阶段 3）

- 层级/needs/项目模块：二级实现；`code, math`（动作接触）；awz，主模块1.3.4。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.G2、awz.CF.D2、awz.CF.D4、awz.CF.F2、awz.P3.I1、awz.P3.I2、awz.P3.I3、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A8、awz.V9.A9、awz.V9.A13、awz.V9.A12；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`python/animeworld/choreography/multi_actor.py`、`tests/choreography/test_multi_actor.py`、`reports/CF-G3`；登记不创建产品文件。
- 交付：共享节拍/接触点/双方约束；一个有限联合 solve 后统一 adopt；冲突明确返回，不依赖多人生成模型。
- 验证/正反例：awz.CF.G4（非作者，`code, math`）；合法双人编排；双方错时、角色互换、互等 DAG 环、双方独立双写接触拒绝。
- 状态：blocked（本轮在线登记值）；不把两个单人片段拼接当互动验收。

### awz.CF.H1 跨镜头与完整 15 秒验收（阶段 4）

- 层级/needs/项目模块：二级QA/有界运行候选；`code, vision, multimodal`；awz，主模块4.8；Hub4.6/身份/渲染仅作关联输入。
- 前置（本轮在线登记值）：awz.V9.A10、awz.CF.B2、awz.CF.C2、awz.CF.D2、awz.CF.D4、hub.CF.B2、awz.CF.E2、awz.CF.E4、hub.CF.C2、hub.CF.D2、awz.CF.F2、awz.CF.G2、awz.CF.G4、awz.P3.A3、awz.P3.A4、awz.P3.D2、awz.P3.D3、awz.P3.D5、awz.P3.D10、awz.P3.D11、hub.P1.D1、hub.P1.D2、hub.P1.D6、awz.P3.I1、awz.P3.I2、awz.P3.I3、awz.P3.E3、awz.P3.E5、awz.P3.E6、awz.V9.A8、awz.V9.A9、awz.V9.A13、awz.V9.A12；原业务门与独立运行预算不由本卡替代。
- 文件范围（项目根相对，登记值；新路径仍为拟定实现）：`tools/character_qa/benchmark.py`、`tests/character_qa/test_benchmark.py`、`reports/CF-H1/<registered-fixed-run-id>`、`reports/CF-H1`；登记不创建产品文件。
- 交付：15 秒480p/24fps/360帧，真实场景/曲线/事件/身份/音频/帧/MP4、编辑后回放、接触/足滑/穿模/时序/内存与端到端成本；顺序vs随机访问对照。
- 验证/正反例：awz.CF.H2（非作者且非上述被验交付作者，`code, vision, multimodal`）；新鲜独立采集；身份互换、删修正、错音频、过期缓存、历史帧依赖均要变红。
- 状态：blocked/运行未授权（本轮在线登记值）；自然度/表情/接触/可编辑分项报告，题目不承诺商业成片质量。

### CF-X14 可选神经/REA 缺口研究（阶段 5）

- 层级/needs/项目模块：未来二级调研设计；`text, multimodal`；awz，主模块未登记；涉及REA仍沿原P3.R1；本轮不建卡。
- 前置：已复现缺口、参考输出、预算/次数/停止条件与独立适配接口；需要运行/下载再单独授权，训练暂停不变。
- 文件范围：拟新单项 `reports/CF-X14/<gap-id>/` 与独立设计说明；不修改已验生产路径、旧门或来源政策。
- 交付：确定性基线与候选同质量/同成本比较；HY-Motion 仅单人候选，Audio2Face 不假定 Mac 可跑；闭源研究只列未来，无本轮执行。
- 验证/正反例：CF-V14（非作者，`text, multimodal`）；核缺口、停止和回退；无预算循环、将外部论文当本机能力、把缓存当训练资格必须否决。
- 状态：draft/默认关闭/非阻塞；本轮没有模型/REA 调用。

## 5. 本轮live状态取样与文件所有权

主责本轮直接读取：awz.V9.A8r2/A12已登记accepted，只覆盖CPU合成契约层和R1–R4/F2/F4落纸，Event/snapshot仍未采用候选；T1r3/T18同样accepted而缓存仍未采用，真实加载/ModeGuard/Forge消费未实现。旧baseline§3是出版失败快照，保留不倒改。
E3/E8/E9 accepted不代表E5/E6实现/真实提交；A3/A4仍blocked。I2仍blocked依I1、V9.A8、A10；I3等I2。Hub D1/D4 accepted，D2 blocked依D1/D4/A10，D6 ready但等D2；旧D3不替代D6。
角色D5 reported，D10/D11 ready但D11等D9/D10，角色模块paused不动。NPR D2/D3 draft依D1/A4/D5，不能因draft绕A10。原A4没有新依赖字段，保持不变。
旧出版集合总数不作为live队列总数。本轮唯一有意原卡依赖增补为A3追加三份CF验证，其余旧卡字段与项目related_roots/模块paused保留，由A2独立比对。



原 D1/D2/D5/D10/D11、A3/A4、D2 NPR、I2/I3、E3/E5/E6 的文件继续由原卡负责人编辑；新卡只补缺口/连接，不开第二卡并行改同一文件。
登记顺序：先核原卡→补文案/依赖→只读设计卡→新实现 draft+对应验证卡；保留 A10 与全部业务前置，不能批量清空依赖。模块 paused 原样，不因登记而解冻。
工作台服务与在线任务由主责处理；本轮29卡和旧A3唯一增依赖已登记，精确状态、模块、前后依赖与来源见[registration-result](../../../AinerZero/reports/character-first-landing-20261017/workbench/registration-result.json)及live。本文只记录已落盘结果，不发起代码执行。
各阶段适配器默认关闭；旧合同/金样/资产/失败与旧 baseline JSON 原样保留。失败退回旧不可变引用，候选/缓存/拒绝与 take 谱系不删除。
数值和人工门、正负例/封存数据、环境/模型/资产身份、预算及停止条件先预登记；不依据首个候选放宽，不把 completed 当能力通过。
本轮只做文档整理和只读核对；没有产品代码/Schema/测试/模型/训练/渲染/下载/安装/付费/提交/推送。发布待character_inventory（awz.CF.A2）非作者核对与Codex（awz.CF.A3）追加决定。扩展manifest为AZ报告目录source-after.json中的extension字段，原baseline JSON不动。
