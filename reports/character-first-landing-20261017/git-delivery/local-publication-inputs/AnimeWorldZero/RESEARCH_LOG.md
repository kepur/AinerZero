# AWZ 决策与研究记录

## D-001（2026-10-13）用户决定

用户对设计报告第 5 节「待决定事项」的答复，原样记录：

1. 本地路径 `~/AinerWorkFlow/AnimeWorldZero`；GitHub 仓库叫 `kepur/AnimeWorldZero`，由统筹自己去建 → ADR-0001。
2. Godot 锁定 4.7.2，物理用 Jolt，人物移动和碰撞用解析方式处理，保证每次结果一样 → ADR-0002。
3. 人物资产先用自制低模，许可证只允许自产或 CC0 → ADR-0005。
4. 外部渲染出来的数据算「外部派生」（external_derived），不算「观测到的」，先不进训练准入 → ADR-0005。
5. `teacher_assistance` 从布尔值改成枚举，和 AinerZero 的辅助类型对齐 → ADR-0005、`contracts/episode.v1`。
6. AWZ 发现 AinerZero 的锁被占时直接放弃，不等待 → ADR-0006。
7. 测试分区统一叫 `final` → ADR-0005。
8. 第一轮只做 T01–T05 加 W0，接受 T04 的不确定性 → AGENT_TASKS。
9. 校验场需要的契约扩展（帧区域引用、想象分支的核对引用、多时钟），以后在 AinerZero 另开任务登记 → AINERZERO_BRIDGE 第 5 节。

同时采纳用户提出的 **ACIS（人物身份系统）**：身份由资产和参数锁定，不由网络逐帧决定；身份不可变、状态可变；调色板锁定；视角形变先用形态键；LineNet/ColorNet 放到后期，并带身份、关键点、时间、材质四类约束 → [docs/ACIS.md](docs/ACIS.md)。

## D-002（2026-10-13）统筹决定（Claude 起草，待 Codex 审议；用户可以推翻）

- **ADR-0003 真值内核放在 Python，Godot 只做回放渲染**。规则都是解析式的，Python 能逐字节重放、CPU 并行生成数据，也绕开 Godot 物理和粒子的复现风险。将来交互或 VR 时，移植成 GDExtension，并用黄金日志做一致性测试。
- **ADR-0004 120Hz**（v1.0 写的是 60Hz）。60Hz 和 24fps 不能整除，会造成半 tick 采样。
- **ADR-0007 禁用 TAA 和时序效果**，改用 2 倍超采样；Godot 无头模式不能渲染，T01 必须先实测运行方式。
- **ADR-0008 采用 `ainer.scene/v1` 的坐标约定，并直接吃它的场景 JSON**。台词、表情、语言版本、风格引用这几项缺口，到 AinerHub 另开任务提议 v1.1。
- **分工**：AWZ 的 W1、W2 定位为「有监督参照模型」；发育式学习者只放在 AinerZero（它的 M6 已经规划了 CNN 加 slots）。
- **对 AinerZero 的价值点**：「历史需求」课程（遮挡、延迟效果、出画、相似实例、相机和物体分别运动），每个查询带 `needs_history` 标注，直接对准它当前「不会用历史」的卡点。
- **产品方向**：口型属于角色资产（日漫 5 种口型、一拍二），时间线跟着配音伸缩，不走扩散对口型；LTX 只给重点镜头做可选精修，精修后必须过身份校验。

## D-003（2026-10-13）事实依据

- **本机**：M2 Max、96GB；Godot 4.7.2 和 Blender 5.2.2 已安装；本机 HF 缓存里有 CCIP（`deepghs/ccip_onnx`）和动漫人脸检测（`deepghs/anime_face_detection`）。
- **AinerZero**：HEAD `02f4e32`，另有其他 agent 未提交的改动；枚举 `AssistanceKind`、`OriginKind`、`ActorKind`、`DatasetPartition` 以 `src/ainerzero/core/experience.py` 为准。混合批两次超窗失败（85b844f5、0602dae2），原因是 Metal 争用，而它的等待脚本只看 CPU。
- **AinerHub**：`ainer.scene/v1` 在 `code/apps/ainer-core/app/director/protocol.py`。Director Core 已有无头 Blender 渲染深度、姿态、轮廓等通道，按单 GPU 顺序执行，卡死就换进程。
- **契约自测**：三份 JSON Schema 通过 Draft 2020-12 元校验；正例通过；关键反例全部被拒（来源 observed、操作者 student、unknown 辅助不在隔离区、隔离区没写原因、许可不在白名单、60Hz、分区叫 test、CC0 没有来源、缺调色板槽）。

## D-004（2026-10-13）替换远程仓库并借鉴旧内容

- 用户指示：`kepur/AnimeWorldZero` 原内容先看是否有可借鉴的，借鉴后清空远程，换成当前代码。
- 原内容是「AutoVideo Flow」：早期的小说转视频任务后端（FastAPI、Postgres/pgvector、Telegram），9 次提交，`master` 指向 ff9abf7。完整镜像已备份到 `~/AinerWorkFlow/_backups/AnimeWorldZero-remote-20261013.git`。
- 借鉴了六条设计，记录在 NOVEL_TO_WORLD 第 6 节；代码不复用。
- 旧历史里有明文口令（README、`.env.docker`）。新内容以全新历史推送到 `master`，旧提交不再出现在远程分支上。已提醒用户轮换口令。

## D-005（2026-10-13 晚）用户决定：取消空闲限制，全力跑

- 用户原话：「之前设计的是使用 cpu gpu 空闲跑，现在可以取消限制，全力跑，会更快。」
- 落实为 ADR-0009：
  - 不等空闲；
  - GPU 分轻量（并行）和重型（全机串行）两档；
  - AinerZero 的锁不再挡 AWZ（**取代 D-001 第 6 条**）；
  - 只保留防崩溃的保护线。
- 同步修改：
  - AinerRelay 的 GPU 闸门改为两档；
  - AinerZero 的占空比 0.25 → 1.0，不再等静默窗口（AinerZero RESEARCH_LOG M20261013-09，配置哈希 `0169cc73…`）；
  - 一级提示词改为：已登记、在预算内的有界运行可以直接发布（依据用户「取消限制直接跑」）。



## C20261013-Z1：Codex平级审议ADR-0003/0004/0007

同意三项作为R1设计基线，用户可推翻；不修改旧ADR。详见 [审议报告](reports/C01/codex-adr-review-20261013.md)。Python float64不自动保证跨硬件确定性，T02/V01固定顺序/RNG/规范日志并检验seek；120Hz使用整数tick与半开帧区间，30秒24fps输出720帧；禁时序效果和各轴2倍超采样并不自动保证逐像素≤1，T01/T04/V03实测冷启动/顺播/倒序同tick及线条质量。编码确定性、工具版本、速度均未实测，本次无渲染或模型工作。

接力台状态负责领取和验收，本仓库任务卡负责正文；本次只编辑RESEARCH_LOG与reports/C01，不抢T00作者文件。真实训练、下载、付费、推送、删除继续留给用户。


## C20261013-T00-review：环境工具回验与异常补修

独立P1.V01报告接受：9项CPU复现，未装MLX、AWZ临时锁互斥、32GiB启动检查成立；16GiB运行保护与swap仅常量/未实现。T00实现打回V-F1/V-F2：pgrep/lsof rc≥2不得称空闲，缺命令/超时转可读reason；heavy未知阻断，轻量按ADR9不因AinerZero忙等待。新V02回验独立于作者；不启动渲染/GPU或下载。


## C20261014-T02-review：避免验证前置死锁并区分真实消费者

Codex将relay C3改为立即独立审T02（C1），新增C4审T03（C2）；原C3等待C2而C2等待C1验收，形成循环，不能跳过复核放行。T02脚world_vel=0为自报值，当前world_pos随root移动；必须从支撑区间位置差分独立测≤1cm/s。test_godot_playback_transform_accuracy只调用Python bridge，不能声称真实原生Godot误差0。先交独立CPU证伪/支持报告，固定门不放宽。


## C20261014-T01-accept：固定资产消费与运行方式限范围验收

Codex接收B4独立支持并验收B1/T01：14个SHA与注册资产、6660三角/18关节/6材质/动画、窗口与SubViewport10帧及Movie48帧两次落盘字节一致。接受当前固定GLB字节消费，不宣称重新导出流程字节确定；原生成不一致证据保留，资产升级需新版本与身份清单，不能替换同版本。最小化未实际生效/AppNap未覆盖、原型美术非最终、屏幕1.5px线宽仅元数据由T04实现。这些不是放宽GateA，GateA仍未验收；T02门禁与真实foot/Godot消费者独立待补。


C20261014-T02独立性附注：C5提交者antigravity-m2c1也是C1第一版作者；即便grokg47补修，此复验不能关闭原有内核/RNG/bridge的整体独立验收。保留其支持脚差分/40项CPU/native72帧结果为作者复验，C5重排排除两位历史作者，等待非作者独立审。固定1cm/s/120Hz/1e-5m门不改。


### C20261014-T03-T05-review（Codex）

T02经C5独立120Hz差分/原生Godot72帧核验，在内核与回放范围验收。T03的C4数学CPU反例得到支持并单独验收，但C2缺云/水花/倒影实际消费及截图，退回并登记C6视觉复核；Gate A未过。T05现有writer隔离工程证据不足以覆盖录制，D1退回补真实CPU内核对象观察episode，图像通道留T04。D2的22向量仅存结论JSON，退回补可执行独立探针及原始日志。保持120Hz、原schema、隔离与科学门不变，不训练。


### C20261014-T03-T05-T04（Claude 接任一级统筹）

T03（C2）经 C6 独立有界重跑（87/87 PNG 逐字节一致、CPU 10 项）与统筹目视（倒影开/关、波纹、水花、云均可见）验收；限制：倒影为镜像几何副本、脚部 IK 未验证。T05（D1）验收（Gate D）：契约/泄漏/22 种篡改经 D2，真实 120Hz 录制/公开加载零次打开 private/全部 121 观测/27 项实际身份重算经 D3 独立支持；contracts/rng.md 仍未跟踪，按字节计入身份。T04（B2）打回：gate-a2 的 line_alpha/frames/shots 只有人物且近乎实心剪影，云/地面/水坑/波纹/水花/倒影不在官方线稿输出，五官为几何短线而非贴图线；闪烁 0/跳转 0 在剪影上平凡成立，不能作 Gate A 证据。B3 指标复核在 V03 卡内正确，但“全部合格”越界，随 B2 重交带内容目视检查重新复核。Gate A 未过；gate-a、gate-a2 保留为不利证据。


### C20261014-W0（Claude）

W0（E1）验收（Gate W0）：40 世界、373 事件，两次生成与 development 报告逐位相同，final 只评一次并封存（seal 读记录 05:29:46Z）；E2 以不 import worldbrain 的 numpy 独立复算 588 项差异 0。dev/final h=1/4/8：恒速 MAE 0.00063/0.0063/0.0222、0.00053/0.0052/0.0184；analytic_rule micro F1 0.514/0.505/0.505、0.563/0.548/0.541（ripple_end 全对，footstep_water 召回约 0.22/0.15）。统筹决定：1 步=5 tick、事件按窗口判定确认；水坑不在公开对象观测中——R1 保持（final 已封存），R1 踩水数字是信息受限下的下限；学习模型将看到含水坑的渲染帧，公开观测是否含静态环境对象列为 R2 设计问题（需新 final 分区）。数据留 reports/W0/data 不入库，ruff 排除 reports/ 证据与 .gitignore 交 P1.A2 卫生任务及独立回验。


### C20261014-T04（Claude）

T04 Gate A 验收（gate-a4）：B3 独立复核 gate-a3 时发现两处缺陷——capture_gate.gd 用 get_parent()==cloud_root 判断，对 cloud_root→cloud_a→MeshInstance3D 这种二级结构恒为假，导致云被剔除（720 帧中 0 帧有云）；倒影为多阶灰度实心块，违背 bands=0。返工改为按祖先判断，倒影改为描边加结构线。B5 独立复核：云出现在 240/720 帧，倒影区中间灰度像素减少 77%（只剩抗锯齿），5 段金样与 12 帧重渲逐位一致，静止闪烁 0（jitter 对照非平凡），线宽 p50 1.0px，seek 误差 0，p50/p95 26.9/41.9ms。人物轮廓线、结构线、五官贴图线、水坑、波纹、水花都合格。gate-a、a2、a3 保留为不利证据。R1 的 T00–T05、W0、V01–V04 全部通过，Z2（R1 验收与 R2 方案）放行。


## C20261014-C02：R1 验收与 R2 方案（Claude）

R1 全部通过：T00–T05、W0，以及 Gate A（gate-a4）、Gate D、Gate W0，独立复核 V01–V04 及各补充复核；已提交 08fd35a、29eb186。决定：静态环境对象进入公开观测（episode v1.1，向后兼容），用新数据集和新 final 分区重算 W0（R1 final 保持封存）；R2 顺序为 H→A（T10 只导出加历史需求课程），I→S（ACIS/Gate ID→风格包/Gate S），C 并行；W1 的 T07/T08 与 CCIP 需用户批准，设为草稿。详见 reports/C02/R1-acceptance-R2-plan.md，接力台 awz.P2。


## C20261014-Codex-recovery：续领和验收依赖修正
Scene Compiler C1/C2按CPU编译子集通过（20独立探针、23场景测试、61真实场景2支持59可读拒绝、工作树SHA一致）；不宣称Godot消费或全SceneProtocol已完成。ACIS I1→I2→I3形成验收依赖环，补I5仅对I1做非作者独立实际视觉复核，I2/I3仍按原Gate ID四项及固定门执行。CCIP下载、W1安装和训练预算仍未授权。


## C20261014-I1-rejected：独立原生视觉反例
I5独立验证报告accepted，但结论reject I1：98图/151CPU，48作者图复现缺陷。统筹目视五官覆刘海/侧眼越轮廓与强度过渡不变；相机、LOD、跨端RNG和实际形变消费亦有原始反例。I1已打回原scope修复，I2/I3仍等待；正常episode→WorldPlayer接线另派I6/I7，保留R1缺省金样/T01资产/固定门，不下载。


## C20261014-Codex-Cycle1：ACIS v4 嘴部缺陷与独立量化修订（Codex，P1.Z3）

I1 v4 与 I9 独立成片放大图均显示六种表情嘴部被刘海截断：笑弧断裂，惊讶 O 环不完整，neutral/sad 口部相同。I1 退回，仅既有 ACIS 受控映射/嘴部位置与深度修订，保持 T01 身份几何、正常深度测试、透明背景、零外部穿透及原接缝门，不恢复深度豁免或矩形挖空窗。修订证据写 v5，另派 I10 不同作者独立真实 Godot 回验；Gate ID / WorldPlayer / 风格下游仍按原依赖阻挡。

I9 的拒绝实现建议在定性上成立，但其 analyze_mouth.py 使用 ~is_skin_unocc 作嘴笔画，混入头发/背景，分母与整块红底差异图不表示真正嘴笔画；报告 13.4% 与脚本旧判词 35–50% 不一致，故该数值不采纳。I9 退回只读原 v4、以 revision-1 追加真正笔画掩码与标注证据，不覆盖旧报告。CPU 172/27 通过不抵消嘴部缺陷，不放宽门。

T10 A1 保持 reported，A2 已由 grokbot-8w2n 领取。已通知核 needs_history 的真实 kernel/公开观察反例与身份信息泄漏，禁止只复现人为时间规则；保持 E0 只导出、final 封存与 AinerZero 只读。CCIP 下载、AWZ MLX 安装与训练预算草稿继续等待用户授权。本轮未渲染、未训练、未下载。


## C20261014-Codex-Cycle2：T10 独立反例通过、实现退回（Codex）

A2（grokbot-8w2n）独立复核报告已验收为有效失败证据，CPU 192/20 通过不能覆盖六项缺陷。一级源码核对确认 admit_training 意外放行后抛出的 AdapterIsolationError 是 ValueError 子类，被同一 except 当作成功拒绝；真实来源入口 build_synthetic_v11_stream 用零 kernel hash 与占位资产，sim_hz 声明120却按1/60递增时钟。课程标签来自调用方布尔/固定坐标，公开 prompt/hint 透露历史标签，同世界可跨分区，symbol8 报告摘要与实际规范不一致。

A1已退回六项明确修法，projection 现有定义不变，实际规范摘要0f5bfa0d6d5e25128793a01ad22b24be19c9a91cf029df0592e409c3a948f559为核对值，非能力登记。A3不同作者验证接在A1修订后，追加独立反例、真实kernel/120Hz/所有transition来源闭包、schema逐行核对与20向量独立手算。原final不得重开或重评，AinerZero只读。当前不能移交E1模型评测。原作者报告、A2失败报告与原artifact不覆盖。


## C20261014-Codex-Cycle3：真实课程来源重建路线（A4）

A3负面复核已验收，A1再次退回并暂停：课程不对应导出episode、公开loader读private、封存消费/分区仅局部保护，195项pytest通过仍有ruff失败。新来源设计见docs/design/T10-SOURCE-CLOSURE-20261014.md。新增CPU规则课程20世界/24000tick/120秒上界、development11801–11810/final11901–11910，未生成；A5来源实现→A6独立复核→A7一级实际身份登记与一次CPU生成→A1导出接入→A8独立复核。原source/final/失败/symbol8不变，无模型训练；不是能力通过。


## C20261014-Codex-Cycle4：v4嘴部归因纠正、v5轮廓复核退回

I9 revision-1（claude-opus-r7k2）纠正原非皮肤掩码，真实嘴筆画平均可见60.0%、墨量完整度58.0%；原13.4%无效。被藏笔画在成片中100%是肤色而非刘海色，故先前“刘海截断嘴”归因改为面部覆盖层落在皮肤之后；惊讶被截的是下沿，neutral/sad参考本来同形。原误报与失败全部保留。I9按有效纠错证据验收；其新建议98%门、眼区皮肤比例和近接触遮挡均未自动登记成新验收门，也不把原生T01刘海边缘等同新增cutout接缝。

I10 v5嘴部参考/成片逐像素比较支持嘴部修复，但轮廓脚本用同一像素line(R<45) AND background(R≈235)，交集必空，所谓12角度/180零溢出是恒真式。一级side_views_x3看到±45远侧眼眉有轮廓外灰影疑点，I10退回独立无face_card基线/对象ID或深度剪影、全近远五官及移出1cm必检的真实负对照；原报告保留，I1 v5待验收，GateID/WorldPlayer/Style尚不放行。


## C20261014-Codex-Cycle5：v5真实剪影阴性，转I11/I12定点修复

I10 revision-1重做13角度no-face-card基线、with-face及1.5cm负对照，±45平视/仰视远侧眼眉68/140/58/132px浮出，合398px；负对照有效，原恒零脚本失效结论保持。嘴部100%与闭环70px孔/笑弧连通等修复仍成立。一级目视标注图一致，I10按有效阴性证据验收，I1 v5退回并blocked归档，未放宽原次数或视觉门。新增I11只修远侧剪影并保留v5达标项，I12不同作者完整回验；Gate ID/I3/CCIP/WorldPlayer依赖改到I11/I12，下载草稿仍未授权。

I10旧root报告被修订覆盖的原报文已从Relay拒绝事件previous_result/previous_data只读恢复到reports/coordination/codex-cycle-20261014/retained-relay-rejections/，注明事件来源，不伪称旧文件原字节SHA。原假指标脚本、原截图和新revision全部保留。


### C20261014-GateID（Claude）

I2（Gate ID 工具，claude-opus-r7k2）与 I3（独立复核，gemini-f8a2）都已验收，但 Gate ID 本身没有通过。转身回归 IoU 1.0、时间稳定都通过；调色板 ΔE 不过（皮肤 3.58、cloth_1 3.32、眼睛 27.58、脸部笔画 19.80，门槛 ≤2）；比例因为没有设定稿范围而不作判定；CCIP 等待用户批准下载。决定：一、golden（233 个文件）登记为 ACIS v6 的自身回归基线，转身 IoU=1.0 只表示可以复现，不代表符合设定稿；二、调色板交 I13/I14 修复：face_tex 采样器补 source_color 消除双重伽马，受光材质改用按调色板锁定的 toon 明暗，不靠调光照、不改门、不改 T01 资产；三、脸部区域线条 IoU 只作为信息指标，新增门需要用户批准；四、比例范围要等设定稿输入。风格包 S1 改为排在 I14 之后。


### C20261014-T10-source（Claude）

A5（真实五类课程 kernel 来源，opencode-a1b2）经 A6（opencode-7k2m，不是 A5 四位历任执行者之一）独立复核，167/0 验收。此前伪造的 similar_objects 与 viewpoint_body 两类已整类重写：逐 query 的 public_evidence 与 observations[qt] 逐字节相同，视位由 kernel 逐 tick 独立复算一致，旋钮真实生效，篡改会被拒绝。遗留 A4 设计缺口（history_needed 硬编码、metadata 承载、knobs 双定义、schema entity_id）交 A1 revision-2 和 A8 处理。仓库没有正式生成驱动，A7 无法冻结命令身份，因此先派 A11（固定计划驱动：20 世界的种子、子集、A/B 写死，单世界 1200 tick，总量 ≤24000 tick / 120 秒，final 只进 pending_seal）和 A12 独立复核，A7 改为排在 A12 之后。


### C20261014-W1-MLX（Claude）

用户 2026-10-14 批准在 AWZ 安装 MLX 并同意做 T07。统筹按 uv.lock 执行 `uv sync --extra mlx --frozen --inexact`：从 PyPI 装 mlx 0.32.3（0.65 MB）和 mlx-metal 0.32.3（67.7 MB，macosx_26_0 arm64），哈希由 lock 锁定，uv.lock 与 pyproject 未改，Device(gpu,0) 可用。W1（T07 模型与 smoke test，不做正式训练）已发布，配独立复核 W3；T08 训练预算等 T07 通过后由统筹给出具体步数与时长，再请用户批准。CCIP：用户同意先查。deepghs/ccip_onnx（HuggingFace，openrail，未加门禁）推荐变体 ccip-caformer-24-randaug-pruned（imgutils 默认，F1 0.917，阈值 0.178475），推理只需 model_feat.onnx 150,248,245 B、model_metrics.onnx 1,649 B、metrics.json、cluster.json，约 150.25 MB，另需 onnxruntime 1.31.0（PyPI，20.9 MB）。是否下载等用户再次确认。


### C20261014-GateID-palette（Claude）

I13（antigravity-g9b2）的调色板修复经 I14（antigravity-g7p3，不是 I2/I3/I11/I12/I13 的作者）独立复核，验收通过。face_tex 加 source_color 消除双重伽马；皮肤、cloth 等受光材质在 godot/acis 里以运行时覆盖的方式按调色板锁定为两阶 toon（T01 的 14 个资产哈希不变）。调色板各槽中位数 3.58/3.32/27.58/19.80 全部降到 0；转身回归对原金样与新候选金样都是 1.0；时间稳定不劣于基线；232 张截图逐像素复现。决定：reports/R2-Palette/golden-candidate-v6-palette 登记为新的自身回归基线（原 golden 保留，仍是自身基线，不是设定稿）。Gate ID 现状：转身、调色板、时间稳定通过；比例要等用户给出设定稿范围（模板 docs/design/heroine_001-proportions-TEMPLATE.md）；CCIP 要等用户确认下载。风格包 S1 解锁。


## 2026-10-14 Codex：T10来源A7登记完成，等待一次CPU生成

A11主动墙钟隔离修复及A13独立13反例/13桥接测试通过，当前驱动ade83c6d…；具体身份与argv冻结于reports/T10/registered-source-v1/{source-identity.json,generation-params.json,registration.md}。20世界固定种子11801..11810/11901..11910，每世界1200tick、总24000tick、120秒CPU、至多8实体，一次正式尝试，不重跑、不MLX/模型/GPU。A9执行，A10独立核验，A1之后packing/seal；新final仍pending_seal，原final不读。登记本身未生成正式数据，也不是能力通过。


## 2026-10-15 I22：CCIP 比对登记阻断于第二身份（Claude）
I4（grokbot-k7q2）与 I21（relay-runner-verifier，30/30 探针、285 回归）验收：名单化预算 64 图/60 秒不可放宽、先核 SHA 后解码、fail-closed 无旁路、原门方向与分位冻结纪律、预处理常数与上游一致。I22 一级冻结模型、源码、heroine_001 42 张金样、门（Q0.95 同身份差异 < Q0.05 异身份差异）、预算与入口（relay exec + BudgetGuard；AWZ 不写 AinerZero RunStore，纯 CPU 不取 awz_heavy_lock）。但注册表只有 heroine_001@v1，异身份分布不存在，门不可判，不伪造负例、不建运行，用户授权未消耗。RGBA 白底分支不可达（I21 缺口 1）另派 I23。第二身份来源（自生成 heroine_002 / 用户提供 / 暂缓）交用户。见 reports/R2-CCIP-registration/。


## 2026-10-15 Codex A14：T10 A1/A8 的封存历史与反例有效性打回

A7/A9/A10来源工程验收保持；A1/A8未通过。A1自报当前final/occlusion-A一次读取后删包重导出使reads=[]，不能以此证明未消费；A8 G3/G4直接读取当前R2全部包（含10 sealed final）而G8e只核空reads，须补记真实工程曝光，不混称未读R1旧final。一级本轮只读源码/报告，不读正式final正文。A8 G9b正常与异常分支全置True，G6同进程调用冒称跨进程，G1c用git未跟踪代替原定义/20向量实值核验，27项绿色不成立。已拒收并要求保留旧报告/包、在包外持久追踪同源身份消费/曝光、跨根/重封存不能洗白、临时fixture精确异常与真子进程/并发反例。不得删包、重生成正式源或换seed来清历史；新的正式评测集若需新预算先报用户。证据与决定：reports/coordination/codex-cycle-20261014/T10-A1-A8-rejection-20261015/。不做能力评测/模型运行，不晋升。


## 2026-10-15 S1 风格包 v1 限范围验收；Gate S：day/ink 过、dusk 不过（Claude）
S1 经四轮（r4 换实现者 grokbot-k7q2），由 S2 r3（grok47-w8n3）、S3（grok47-q8n4）独立重采、S4（render-check-20261015）独立重渲核验：
- 实现：≥3 风格加载与切换；身体线宽按烘焙外壳 4 mm 成比例外扩（acis_line.gdshader，width_scale=1 时跳过），ink 实测 1.319/1.313×、dusk 0.838/0.855×（名义±0.05 内）；无 style 时 Gate ID 默认采集与干净 HEAD 232/232 逐位相同；T04 Gate A 五段 clip 当前/HEAD/登记三方 SHA 逐位相同，hold 与 seek 差值 0（S4），Gate A 路径不加载 acis_line。
- Gate S（对登记金样）：day_cel 全过；ink_bold 全过（剪影 IoU 0.98373，离 0.98 仅 0.0037）；**dusk_soft 时间门不过**（orbit 闪烁 0.102245 > 默认 0.086236）。S5 诊断：差距 99.73% 来自 0.85× 线宽、0.29% 来自 face 节拍 2；line_flicker = XOR/并集、容差 0，线变细时并集变小，比率天然升高（dusk 翻转像素 10736 反少于默认 10794）。门不改（改门需用户批准）。
- 反例：broken_red 被转身与调色板门判出；2× 线宽反例被转身门判出（line 0.639）。2× 实测比 1.88–1.90，一级将该反例的要求从“±0.05”改为“被参与判定的门判出”（原要求过严，粗线遮挡/与剪影重叠可解释），已在 S1 留言记录。
- 登记限制（Gate ID 采集未接入）：收尖（身体与脸部）、色阶第二阈值/bands=3、色彩 saturation/temperature_shift；body/effects 节拍不适用（采集不播身体动画与特效）。
- 金样漂移：Gate ID 登记金样（248fcda）与 I13（82c9330）后渲染有 82 张 final/noface 不同，id/facetex/landmarks 相同；金样未改，重登记交 I 线。
- 不晋升为“Gate S 通过”：dusk_soft v1 判不过。dusk_soft v1.1（线宽 1.0×、face 节拍 1，其余不变，一次评测不再调）已登记为 S6→S7；v1.1 放弃细线特色。


## 2026-10-15 I25 r2/I33：现有资产无可登记第二身份（Claude 代 Codex 验收）
I25 r2（relay-runner-verifier）与 I33（render-check-20261015）独立复核一致：授权只读根 12475 路径中，有生成记录且文本含单人线索的 230 行（116 个唯一 sha）全部没有身份锚点，不能直接登记第二身份；22 个候选只作为短名单。一级不采用这些候选：多为本机 ComfyUI 写实人像（majicmixRealistic）或 256px 小图，许可未确认，部分含需标注内容；CCIP 门检验同风格动漫角色身份，拿写实人像当异身份会人为放大分离，使门过松。第二身份仍交用户（A 自生成同风格 heroine_002 / B 用户提供 / C 暂缓）；64 图/60 秒授权未消耗。
- 补注（06:5x，采纳 Codex #67/#83）：S1 的限范围验收只记录已实现的事实和 day_cel/ink_bold 部分通过，不代表原 S1 卡片或完整 Gate S 已满足；原卡片的完整 Gate S 终审由 Codex 新建的 S8 跟踪（blocked）。S5 只测了 0.85× 一个线宽，“线变细会使闪烁比率升高”是在这一点上实测到的机制，不推广为所有细线在理论上都过不了。dusk_soft 新参数的 version 记为 v2（schema ^v[0-9]+$；原登记写的“v1.1”不合契约，按 v2 执行）。


## D-006（2026-10-15）用户决定：v8 目标架构对齐（Claude 记录）
- 用户原话：「按你的推荐起草：v8 对齐 ADR（Godot 保持主渲染、Blender 作第二适配器、M2 Max、W 命名改 G0–G7、Brain-0 实情）、.apack 素材包格式和 AinerForge 训练系统设计稿、Relay 升级任务卡；只写文档，不改代码、不搬文件。」
- 落实为 [ADR-0010](docs/adr/ADR-0010-v8-alignment.md)：
  - v8 是目标架构，AWZ v1.1 加 ADR-0001–0010 是实施基线，不为 v8 目录建空壳；
  - Godot 4.7.2 保持主渲染，Blender 5.2.2 作第二适配器（资产建造、离线渲染），只读状态日志、不写真值；
  - 本机 M2 Max；
  - v8 的 AinerZero 课程段 W0–W7 改称 G0–G7，本仓库的 W0–W3 仍指参照模型；
  - Brain-0 只是 AinerZero 的配置名，没有训练过的成长脑；
  - WorldCommand 落为「改世界源再重新编译」；
  - 学习资产一律原地，用旁注清单引用；
  - 训练平面独立为 AinerForge。
- v8 原文逐字节存档：[docs/spec/AnimeWorld_Zero_v8.0.md](docs/spec/AnimeWorld_Zero_v8.0.md)，sha256 `018060702b4115a60ef4f6f8fb8189ef29b36ad1fd91730dd0223eb2c08d8229`。
- 同批文档：
  - `~/AinerWorkFlow/AinerForge/docs/DESIGN.md`（训练系统设计稿 v0）；
  - `~/AinerWorkFlow/AinerForge/docs/APACK_FORMAT.md`（素材包格式 v0）；
  - `~/AinerWorkFlow/AinerRelay/reports/coordination/v8-upgrade-task-cards-20261015.md`（relay.P2 升级卡，未导入）。
- 本次没做的：未改代码，未搬文件，未建 AinerForge 的 git 仓库，未在 Relay 建任务，未训练。D-001 的来源和许可规则不变。Codex 平级审议待补。


## D-007（2026-10-15）用户决定：Blender 为当前主引擎（Claude 记录）
- 用户在确认架构时明确写出：「Blender Worker：当前主引擎，后台建模、动画、渲染、训练数据」；「Godot / Metal：未来可选后端，实时交互、VR、低延迟渲染」。
- 用户同时澄清了两条路径的定位：
  - AinerZero 相当于一个默认空白的大脑，进入这个多维世界，去理解物理常识、光影等各种信息；
  - 生产路径（Creative Brain → AnimeWorld Core → Anime Art Layer → Blender → 作品）和成长路径（AnimeWorld Core → 观察/经验 → AinerZero → 预测/行动 → 世界反馈 → 学习）同时存在，互不阻塞。
- 落实：
  - 改写 [ADR-0010](docs/adr/ADR-0010-v8-alignment.md) 第 2 条：Blender 是主引擎，Godot 现有工作保留为证据和实时预览，Blender 路径要重新过 Gate A/ID/S 的同类门；
  - G2 段明确包含光照与阴影关系；
  - 后续任务增加 B-3、B-4、ST-2；
  - AinerForge 设计稿 §3.6 的反馈来源改为 Blender。
- **取代** D-006 中「Godot 保持主渲染、Blender 作第二适配器」一项，D-006 其余内容不变。ADR-0002 只在 Godot 后端内有效。
- 待决定（未实施）：是否允许 LLM 在隔离的「资产工坊」里写 bpy 建模。
- 本次只改文档，没有改代码，没有运行 Blender。


## D-008（2026-10-15）用户决定：暂停 AinerZero 训练，资源转向世界系统（Claude 记录）
- 用户原话：「A：暂停 AinerZero 训练，资源全部转到世界系统。它的检查点和证据原样保留，以后随时接着做」。
- 含义：近期训练和进化的对象是 AWZ 世界系统，具体包括：
  - Blender 主路径和工具库；
  - 素材与知识库；
  - 风格体系；
  - 美术迭代闭环；
  - 以后由积累数据训练的小模型（画面评分器、美术策略、布局模型、风格适配器）。
- 世界系统先由现有 LLM 驱动，不等 AinerZero。
- 分层原则（用户确认）：
  - 各层通过带版本号的契约连接，可以单独进化、单独替换；
  - 渲染底座可以换（Blender → UE/Unity/Godot/高斯），训练底座可以换（MLX → CUDA/ROCm），当前按 MLX 优化。
- AinerZero 侧的记录见 AinerZero RESEARCH_LOG R20261015-pause。AWZ 继续通过 Bridge 为将来恢复的 AinerZero 准备考场，但不再为它安排训练。
- 本条只记录决定，没有登记新的运行或任务。


## D-009（2026-10-15）用户决定：二期 Godot 线和 T10 先挂起，执行层优先做 P3（Claude 记录）
- 用户原话：「把 AWZ 二期还在排队的 Godot 线（I29、I37、S7）和 T10（A1、A8）先挂起，执行层优先做 P3 世界系统任务；已经交回待验收的照常验收。」
- 已执行：接力台 `awz.P2.I29`、`I37`、`S7`、`A1`、`A8` 改为 blocked，备注写明依据和恢复方式（一级重新发布）。挂起前五个任务都没人领取，没有中断在途工作；原任务卡、报告和产物保留。
- 挂起后 AWZ 可领的二级任务：P3-A1（RenderBackend 契约）、P3-B1（日式街道生成器）、I35（CCIP 预处理 r2 复核，没在挂起名单里，保持可领）。一级可做：P3-E1、P3-F1。
- 待验收的照常处理：
  - I31：独立复核 I35 仍可领，复核结果出来后照常验收；
  - S6：它的独立复核 S7 被挂起，S6 暂时只能停在待验收。按"作者不能验证自己的任务"的规矩，不跳过复核直接通过；
  - I17：它的独立消费者验收 I18 原本就是 blocked，同样暂时停在待验收。
- 挂起不是取消：恢复时由一级用 `relay ready <ID>` 重新发布，参数和依赖不变。


## D-010（2026-10-15）用户决定：按「系统 → 模块 → 子模块」分层，并按模块看进度（Claude 记录）
- 用户要求把两个大系统再分层，按模块查看每个子模块的进度。用户确认方案后说「动手」。
- 模块编号用纯数字大纲，因为 A1、P2、W3、S6、T10 这些字母组合在现有任务里都有含义了。顶层分为：
  - 0 全局；
  - 1 世界系统（1.1 世界核心 … 1.11 世界脑考场）；
  - 2 世界脑（暂停）；
  - 3 共享平台（3.1 创作智能接入 … 3.8 Relay）。
- 成熟度分 Lv0 到 Lv5，只凭已验收的证据上调。接力台的期和轨道继续表示批次和并行车道，模块编号是永久地址。
- 已落地：
  - 登记表 `AinerRelay/modules/modules.v1.json`：69 个模块，当前 65 个未完成任务全部归档；
  - 只读看板 `AinerRelay/bin/relay-modules`，生成 `modules/BOARD.md`。核对结果：没有未归档的任务，也没有登记了但接力台找不到的任务。
- 接力台原生的模块视图派成 relay.P2.E1–E3。同时把要改同一批文件的 Relay 实现任务改成串行：M3 → E1 → C1 → A2 → B1 → C3。


## D-011（2026-10-15）用户决定：三个系统加共享底座，制作脑放 AinerHub，AnimeWorld 改称世界系统（Claude 记录）
- 用户原话：「好的按照你的123执行」。三项是 Claude 同日提出的：
  1. 采纳“三系统加共享底座”作为顶层架构：制作脑（影视创作与控制）、世界系统（AnimeWorld）、世界脑（AinerZero），共享知识与资产、风格、渲染底座、训练底座和治理；
  2. 制作脑的代码放进 AinerHub；世界系统负责把制作计划翻译成世界命令并逐条校验；
  3. AnimeWorld 叫世界系统，“世界模型”只指 AinerZero。
- 背景：
  - 用户要求「AnimeWorld 必须自己具备运行世界的能力，AinerZero 负责学习这些规律。两者的职责需要分清」；
  - 用户提出影视团队式的独立层，要能「完全控制世界模型类似 世界模型的controlnet」；
  - Codex 审议稿 R2–R5（`AinerZero/reports/codex-v8-requirements-review-20261015/`）给出世界运行职责、多世界抽象、统一参考架构和影视创作与控制层。
- 落实：
  - [ADR-0011](docs/adr/ADR-0011-three-systems.md)：三个系统、名称约定、代码归属、制作计划契约（在 `ainer.scene/v1` 上分层扩展）、世界系统要补的六项运行能力、呈现方式分别编排；
  - [NORTH_STAR](docs/NORTH_STAR.md)（P3-G1）：总目标文档，每条可追溯，未实现的都写明；
  - 模块树新增顶层「4 制作脑」，世界系统下补交互运行、机制包、场景语义、角色运行、持续身份与多形态、表现效果；
  - 新任务卡 P3-I1–I3（世界运行契约与小房间切片）、P3-J1（制作计划契约 v0）；P3-B1 补语义输出。
- 同日用户还问：影视团队要学拍摄、导演、剪辑手法，做反转、幽默、冷笑点、细节镜头、动画手法、非写实镜头和架空世界，能不能胜任。记录的回答：
  - 手法归制作脑，放进技法库；执行归世界系统，非写实效果记为表现效果、不改世界真值；
  - 学习路线是无训练基线 → 完整制作记录 → 用户选择和修改作为品味数据 → 专项小模型胜过基线才接入；
  - 架构保证手法有地方放、能执行、能评测，不保证每部作品都精彩。
- 本条只改文档：没有改代码，没有训练、渲染、下载或付费调用，没有改 AinerHub 或 AinerZero 的源码。Codex 平级审议待补。


## C20261015-E1：世界指令协议 v0 草案（Claude，awz.P3.E1）
- 交付：
  - [docs/design/WORLD_COMMAND.md](docs/design/WORLD_COMMAND.md)；
  - schema 草案 `contracts/drafts/world_command.v0/`：指令、预览结果、revision 记录，另有 6 个示例；
  - 校验证据 `reports/P3-E1/`。
- 要点：
  - 世界源 = `ainer.scene/v1` 加 `awz.performance/v0`，打包成 `awz.world_source/v0`；
  - 世界指令 = 带 `test` 前置的 RFC 6902 补丁，加类别和 `expected_revision`；
  - 流程是预览 → 确认 → 原子提交；撤销、重做、回滚都产生新 revision，历史只追加；
  - 编译结果切成世界状态、表演、呈现、风格四个派生摘要，每类修改只允许改自己那一份，从而把 ADR-0011“改镜头不改世界”变成可测试的规则；
  - `effective_from_tick` 为交互运行预留“只改未来”的检查。
- 设计核验，用现有代码跑，不新增实现：
  - 用 AinerHub `app/director/patch.py` 打补丁，用 AWZ `compile_scene` 编译雨中行走示例；
  - 只改切镜时，只有呈现摘要变；改人物目标位置，只有世界状态摘要变；撤销后世界源摘要还原；
  - 三份 schema 通过 Draft 2020-12 元校验，6 个示例通过，7 个反例全部被拒。
- 未实现：协议的正式实现和 11 个错误码的测试，待本稿审议后另开实现任务和复核任务。AinerHub v1.1 给时间线条目加 `id` 要到 AinerHub 那边提议。
- 没有改内核、编译器或 AinerHub 的代码。


## D-012（2026-10-15）用户决定：两半世界系统合成一个，按状态类型统一权威，代码不搬（Claude 记录）
- 背景：hub.P1.A1（AinerHub `docs/v2/10_PRODUCTION_BRAIN.md`）发现 AinerHub `app/worldmodel` 已有持久世界库（区域、地标、通路、实例、事实、版本增量、一场一演、take、Blender world_check 与 world_multicam），和 AWZ 的世界系统职责重叠。如果不处理，会出现两套世界真值、两套变更协议、两条 Blender 通道。
- 用户在三个选项中选了甲：「甲：统一权威，代码不搬（推荐）」。
- 落实（ADR-0011 修订一）：
  - **持久世界**（区域、地标、通路、实例、事实、版本）：以 AinerHub 持久世界库为唯一权威，它也是 `.aworld` 存储的实现候选。AWZ 从指定版本的快照导出世界源再编译，不另存一份。
  - **运行与确定性求值**（时间、事件、规则、交互运行、快照重算）：以 AWZ 内核为唯一权威。AinerHub 的 `state_at` 和表演求值，逐步改为调用 AWZ 的编译结果，或用黄金日志做一致性测试。
  - **身份与风格**：以 AWZ 的 ACIS 身份包和风格包为唯一权威，AinerHub 的 WorldEntity 用 ID 引用。
  - **变更协议**：只有一个信封，awz.P3.E1 世界指令草案和 AinerHub WorldDelta 合并（新任务 awz.P3.E3）。
  - **Blender 渲染**：只有一条通道，以 AinerHub 现有 worker 为起点；AWZ 的 P3-A1、A3 改为在它上面做契约和适配。
  - 制作脑仍在 AinerHub（D-011 不变）。
- 本条只改文档、任务卡和模块登记表，没有改任何代码，也没有搬文件。


## D-013（2026-10-15）用户决定：人物技术和 REA 纳入未来规划与研发工具链（Claude 记录）
- 用户原话：「你先把上述学习到的人物技术还有rea纳入工具链都纳入未来规划 写入任务列表里面 然后接下来就可以开始框架实现了」。
- **人物技术**，依据：
  - `docs/research/DILLONGOO_TEARDOWN_20261015.md`：九个控制层面、16 张截图分析、对标闭环；
  - `docs/research/ANIME_HAIR_MODELING_20261015.md`：发型流程。

  路线：P3-D4 公开资料拆解 → P3-D5 角色包 v2 规格 → P3-D2 Blender 实现；P3-B3 发型生成器；P3-C3/C4 技法对标闭环；hub.P1.D1 表演接口。
- **REA**（逆向调查代理）纳入研发工具链。工作边界按 Claude 同日的建议执行，用户可以推翻：
  1. **许可审查是第一关**：选定要研究的功能后，先核对目标软件的许可协议和适用法律。
  2. 调查方式按风险从低到高：有开源实现的直接读源码；对有正版授权的软件做黑盒观测；反编译只用于明确允许逆向的软件、我们自己的程序，或经过法律确认的互通场景（例如文件格式）。**商业软件（如 Maya、iClone）不反编译。**
  3. **净室实现**：写行为规格的人和写实现的人分开，实现者不看反汇编材料。
  4. 目标是行为和画面一致，**不追求、也不引入逐字节一致的代码**。
  5. 用 GPL 等开源代码，要遵守它的许可：可以学原理，直接拷贝代码会带来开源义务。
  6. **REA 本身**先用有源码作标准答案的开源目标试点（P3-R1，草稿）。下载和安装 REA 要用户另行批准，并提供来源地址。
- 落实：P3-R2 净室流程与许可审查规范（一级）；P3-R1 REA 试点（草稿）；模块树新增 3.9 研发工具链。


## C20261015-J1：制作计划契约 v0 草案（Claude，awz.P3.J1）
- 交付：
  - [docs/design/PRODUCTION_PLAN.md](docs/design/PRODUCTION_PLAN.md)；
  - schema 草案 `contracts/drafts/production_plan.v0/production_plan.schema.json`；
  - 示例：“书包变大象”悬疑版和喜剧版；
  - 核验脚本和输出：`reports/P3-J1/`。
- 要点：
  - `ainer.production_plan/v0` 是包在现有谱系外面的信封，谱系是 ScriptDoc → NarrativeIR → SceneStage / 表演轨 → CoverageShot / `ainer.scene/v1`，引用而不复制；
  - 分层：创作要求、世界版本、叙事（事件含真实性五类和“谁从哪一拍知道”，节拍含目的和技法引用）、表演（意图加时间曲线）、镜头（必须写目的，转场拆成三个字段）、美术覆盖（只能是 style 或 presentation 层）、呈现方式、锁定、执行回填；
  - 控制编译要把不支持的能力逐条写进 `execution.unsupported`。两份示例都如实写了“世界系统还没有变形机制”。
- 核验：
  - schema 通过 Draft 2020-12 元校验，两份示例通过，引用完整；
  - 两份的世界版本和叙事事件逐字节相同，差异只在创作要求、节拍、表演、镜头、美术、锁定；
  - 6 个反例全部被拦下：镜头没写目的、美术覆盖指向世界层、未知真实性类别、转场缺字段、镜头指向不存在的节拍、锁定路径解析不到。
- 未实现：控制编译器、和 AinerHub NarrativeIR 的对齐（由 AinerHub 实现）、技法编号（等 hub.P1.B1）。

## C20261015-J1-r2：制作计划契约 v0 修订 2（Claude，回应 Codex 打回）
- 打回原因：缺与现有协议的逐字段对照；修改记录、take 版本、自动确认权限没有落进 schema；检查脚本只打印布尔值不断言。
- 交付：设计文档第 2.1 节（五张对照表）、3.5 节（修改要素的 schema 位置）、3.6 节（自动确认权限）、第 8 节（修订记录）；schema 和示例 r2；`reports/P3-J1/r2/`。r1 全部归档未覆写。
- 决定：
  - v0 只允许 `presentation` 类世界指令自动确认，必须用户授权、预览通过；`world`、`performance`、`style` 一律用户确认。
  - 计划时间单位为秒，镜头和节拍必须落在整数帧上（对齐 AinerHub `Coverage.frame_clock`）。
- 自查出的 r1 错误：景别 `ews` 应为 `els`；喜剧版 5.2 秒不在 24 fps 整数帧上。均已改正并加反例。
- 核验：2 份示例通过；21 个反例全部按预期规则被拦；4 个故意出错的夹具都让脚本非零退出。
- 已知缺口：计划 v0 没有声音和台词层；AinerHub 两套转场枚举之间已有损；轴线检查两边都没有。


## C20261015-Codex-设计审议与P3接口提议

Codex按原卡设计范围验收P3-G1、P3-E1与hub.P1.A1；仅接受目标/架构与源码盘点，不升级本机效果或性能。D-012统一权威优先，E1仅作为E3输入，不能部署第二份持久世界HEAD。J1首次交付缺逐字段复用/缺口表、修改记录/自动确认权限承载与检查退出断言，已打回补r2（原证据保留）。

已领取并交付待审议：P3-E3 WORLD_CHANGE_PROTOCOL（单族提交、双版本、精确来源摘要、旧快照缺口、take失效与逆操作限制）、P3-F1 ASSET_HUB_V0、P3-R2 CLEAN_ROOM_AND_LICENSE及两个模板。只有设计/schema，无执行器；新schema与hub表演schema共13项结构核对通过，不含语义或模型E2E。实现须另登记并接非作者复核。

交叉提议：Relay P2-A1参数登记，Forge F1-C1底座规格，hub P1-C1审片与D1表演接口均待平级审议。完整产物/来源SHA和未验证边界见AinerRelay/reports/coordination/codex-lead-20261015-172550/。AinerZero训练暂停、自产/CC0素材门、下载/付费/超预算等用户授权边界不变。

### E1验收状态勘误（Codex，同轮）

发现E1已配套独立复核awz.P3.E4，前条提前accept不符合“有验证任务等结果一起看”。已用ready撤回E1绿灯，并通知原作者仅行政领取/原报告重交（服务不支持直接恢复reported），不改源、不重跑；E4完整交回后再终审。E3只为待审设计，I1/E2仍等E3终审。G1与hub A1设计验收不变。

## 2026-10-15 Codex 统筹续轮：独立结果与返工边界

资产库F1、净室许可R2经relay.P2.S3非作者审议按设计范围通过；J1 r2字段/失败控制闭合已通过。E1已撤销过早绿灯并行政恢复原Claude报告，等E4；E3因golden数量/base/receipt缺口退回，待E1后修。RenderBackend A1因能力表与报告不一致退回；街道B1/发型B3在独立B4发现(x,z,y)镜像，原要求(x,-z,y)，退回CPU修正和原预算核算，禁止隐形追加渲染。原图与失败必须保留。

Hub表演D1 r3由D4非作者独立完成原94结构、精确差异与Pointer32/32补核，限设计合同通过；语义与真实表演未验证。跨仓内容不构成AZ训练恢复、Godot/T10恢复或新预算授权。

## D-014（2026-10-15 晚）用户决定：付费插件不买；P3-A5 准备开始（Claude 记录）
- 用户原话：「不买呢 W1 训练预算 / P3.A5 Cycles 实测预算开始 P3.R1 下载」。
- **付费插件不买**：Lineworks、Auto-Rig Pro、Goo Physics 等均不采购。P3-D4 r2 及后续 P3-D2/D5 只写 Blender 5.2.2 原生等价做法与退化程度，不再列采购选项。
- **P3-A5 Cycles 实测**：用户同意开始；卡上原无具体墙钟数字，Claude 提出上限后待用户确认数值再改参数发布（见下一条记录）。仍依赖 P3-A4 与 B1 返工后的 P3-B2，前置未满足前不会实跑。
- **W1 训练（awz.P2.W2）与 P3-R1 REA 下载**：原话未明确是否批准，Claude 已向用户确认；R1 还缺 REA 来源地址（D-013 要求）。确认前两项保持草稿。

## C20261014-T08-budget / D-015（2026-10-15 20:42 +03:00）用户批准 W1 训练与 P3-A5/A6 Cycles 预算（Claude 记录）
- 用户原话：「按你列的上限开始：P3.A5 总墙钟 40 分钟、A6 复核 15 分钟；W1 按卡里申请（最多 14 次训练、GPU 总 60 分钟）。」
- **W1（awz.P2.W2，T08 Gate B）**按卡内 2026-10-14 申请批准，数字即上限：数据生成 CPU ≤15 分钟（train 100 / development 20 / final 20，新种子段，final 生成即封存）；训练 ≤14 次（选参 2：lr∈{1e-3,3e-3}、seed 0；主结果 3 种子；消融 a/b/c 各 3 种子），每次 ≤6000 步且 ≤5 分钟；GPU 总墙钟 ≤60 分钟（含评测）；final 只读一次。MLX 经 tools/locks.py 串行，不与其他 MLX 运行重叠。超出任何一项即停下交回一级，不得自行加跑或改种子。
- **P3-A5 Cycles 实测**：8 组 Cycles（854×480 / 1280×720 × 32 / 128 采样 × 降噪前后）+ 两种分辨率 EEVEE 对照，每组 1 帧、计时 2 遍；总墙钟 ≤40 分钟（含首次 Metal 内核编译），单次渲染硬超时 5 分钟，重型 GPU 全机串行。
- **P3-A6 独立复核**：只重渲最低档（854×480/32）与最高档（1280×720/128）各 1 次，总墙钟 ≤15 分钟，单次 ≤5 分钟。
- 前置不变：A5 仍等 P3-A4 与 B1 返工后的 P3-B2；A6 等 A5。本批准不含新增渲染批次、Godot/T10 恢复或 AinerZero 训练恢复。

## C20261015-H1：渲染底座中立交换格式与引擎适配规划（Claude，awz.P3.H1）
- 交付 `docs/design/SCENE_INTERCHANGE.md`（sha256 426ea544d2e776cd…）。权威仍在世界内核；OpenUSD 管场景组装、MaterialX 管真实感材质且必带 UsdPreviewSurface 保底、glTF 管资产与 Godot 通道；卡通/NPR 风格不进中立格式，只带 style_ref。
- 按当前版本核对：Blender 5.2.2（本机实测）、Godot 4.7.2（本机实测，无 USD/MaterialX）、UE 5.8（USD Beta，MaterialX 1.39.4 实验性）、Unity 6.6（USD 导入 1.0.0-pre.2、无 MaterialX、glTFast 6.20.0）、OpenUSD 26.08（26.03 起有 ParticleField3DGaussianSplat）、glTF KHR_gaussian_splatting 已批准。
- 坐标硬规则：换手只在适配器做一次，禁止负缩放镜像，断言行列式符号并做往返测试；高斯数据换手须逐点变换。
- 换底座验收：各底座各自过画质门，跨底座只比结构一致性，阈值在接入任务里预登记。仍为设计，待 Codex 平级审议与非作者核对。

## C20261015-E1-r2：世界指令协议 v0 修订 2（Claude，回应 E4 独立复核）
- 作者据非作者 E4 的实测结论自行退回并修订，不自验收；r1 归档 `reports/P3-E1/r1-archive/`。
- 主要变化：令牌改为服务端不透明随机句柄（绑定提出者、基础 revision、指令与候选源摘要，一次性，提交复查）；undo/redo/revert 不再接受客户端补丁，服务端从记录取正逆补丁并检查归属；单写者锁与落盘顺序、record_sha256、恢复自检 6 步；时间线补丁身份前置改为服务端强制并按条目类型定义身份字段；编译摘要全覆盖规则（schema/warnings 归 world_state）+ 源摘要与 compiled_effect；编译产物校验 compiled_invalid；“只改未来”写死 [0,t) 半开与取值域。错误码 11→16。
- 核验 92/92 断言通过；改坏契约副本对照下 24 个负例被放过、核验非零。
- 待 Codex 平级裁决：§3.3 判据甲/乙；交新非作者补核。

### C20261015-H1 勘误（作者 Claude 据非作者 H2 记录，正文 SHA 426ea544… 不改，保持 H2 核对有效）
H2（musespark-7f3q，reports/V-P3-H1/）建议通过，另列 6 处不阻断问题，作者认可，带入后续适配器任务：
1. Blender 的 `import_point_as_pointcloud` 只是通用 POINTS 导入开关，未证明能识别 `KHR_gaussian_splatting`；“可退化为点云”对 Blender 属未实测。
2. Godot“经 GLTFDocumentExtension 读 KHR 数据”为推测，未实测扩展能否拦截未知扩展属性。
3. §3 需在适配器任务里给出 UE（翻转轴与 ×100 的复合顺序）、Unity（翻转轴）、Godot（yaw 180° 公式）的显式矩阵，再执行“断言行列式符号”。
4. USD 侧高斯路径依赖 OpenUSD ≥ 26.03；UE/Unity 内置 USD 子版本未核，接入前须核，未满足时只走 glTF `KHR_gaussian_splatting`。
5. 模式全名为 `UsdVolParticleField3DGaussianSplat`（正文写了短名）。
6. MaterialX 版本错位（OpenUSD 26.08 绑 1.39.5、UE 5.8 认 1.39.4、Blender 导出版本未核）：适配器须在导出物里记录 MaterialX 版本，并按目标引擎钉选或显式降级、写进渲染报告。

## D-016（2026-10-15 晚）用户决定：采用 v9 架构，先放下旧框架任务、按 v9 重构落地（Claude 记录）
- 用户原话：「现在你首要任务是之前框架任务先放下 不适应的重新可能要推翻 架构要调整最新架构 架构一定要最优后面才不会走弯路 … 理解并实现完整落地v9架构 落地实现 重构 方案 写入任务库」。
- 落实：RFC 原样存档 `docs/spec/AinerWorkFlow_v9_RFC.md`；决定见 `docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`；方案与逐项处置见 `docs/design/V9_LANDING_PLAN.md`；世界脑架构见 `AinerZero/ARCHITECTURE_V9.md`。
- 关键处置：三系统分工与 D-012 不变；四个协议定归属（WorldSnapshot、ObservationPacket 归 AWZ，SkillProposal 归 AinerZero，ExperienceEpisode 归 Forge 并建在 APACK 上）；世界变更只有 E3 一个信封（E1 不出 r3）；AWZ 的 W 轨在 W6 复核完成后结案，W1 转为考场与对照基线；P3 世界系统任务全部保留并优先。
- 不变：训练暂停、下载/付费需批准、素材许可、D-014/D-015 授权。

## D-017（2026-10-16 凌晨）用户决定：前沿技术增补全部写入架构与任务库（Claude 记录）
- 用户原话：「全部写入」。依据：`AinerZero/docs/research/V9_FRONTIER_COST_SURVEY.md`。
- 落实：
  - `AinerZero/ARCHITECTURE_V9.md` 升 r3；
  - ADR-0012 修订四；
  - `docs/design/V9_LANDING_PLAN.md` §9；
  - 详细记录见 AinerZero RESEARCH_LOG `R20261016-frontier`。
- 世界系统侧：
  - awz.V9.B5 借鉴 Kubric/MOVi 的任务设计；
  - 新增 Genesis World（Apache-2.0，可编译到 Apple Metal）物理真值草稿卡，安装需批准。
- 不变：训练暂停、下载/安装/付费需批准、D-014/D-015/D-016 授权。

## C20261016-W-closeout：W 轨结案与迁移（Claude，awz.V9.C1）
- 依据：
  - ADR-0012 决定 3（W 轨收束）；V9_LANDING_PLAN §2、§4；
  - awz.P2.W2（T08 执行）与 awz.P2.W6（独立复核）均已验收；
  - 预算批准见 D-015（原话「…W1 按卡里申请（最多 14 次训练、GPU 总 60 分钟）」）。
- 结案结论：
  1. **预算合规**：训练 14/14 次，全部 6000 步、无超时；GPU 合计 631 s（上限 3600 s，含评测）；数据生成 220.3 s（上限 900 s）；final 只读 1 次（20/20 世界各 1 条读记录）。
  2. **Gate B 未过**：
     - final：MAE@8 0.0897 m，规则基线 0.0196 m（劣 4.6 倍）；事件 F1 0.000，规则基线 0.644/1.000；
     - 单步推理 0.5822 ms，规则基线 0.0033 ms（约 175 倍），没有换来任何收益；
     - W6 复核确认这一能力结论成立。
  3. **研究候选不进生产**（规格第 256 行）；不得因 loss 下降或消融方向合理宣称学会物理。
- 迁移（只登记引用与 SHA，不移动、不改原代码，不训练）：
  - 清单 `reports/V9-C1/w_track_registry.json`，共 38 项；生成脚本 `reports/V9-C1/build_registry.py`。
  - W1 数据生成器（`dataset_v11.py`、`dataset.py`）与评测器（`eval/run.py`）登记为**考场素材**，供 awz.V9.B3 引用。
  - 规则基线（`baselines/`）与 W1 检查点登记为 **AinerZero 对照基线**，v9 各阶段可同表报告，不训练、不晋升。
  - **W1-data-v11 的 final 已在 T08 用掉**：20 个世界各读过一次。它不得再作任何新考试的 final；train/development 只能当 development 素材。
- 处置：
  - **W1 停训**；
  - **W3（潜在动力学/RSSM，规格 §3.4）停**，不开工；
  - **W2（线稿编码器，规格 §3.3 / T09）划归美术专项**：它服务画面与线稿，不作为世界模型。世界模型只在 AinerZero（D-011、D-016）。
- 待用户决定（不在本卡）：T08 的部分报告与 3 个消融检查点尚未提交 git（见清单的 `git_tracked`、`uncommitted_change` 字段）。提交与否由用户定。
- 同步：AGENT_TASKS「W 轨结案」节；ADR-0010 追加修订段，原文不改。

## D-018（2026-10-16 04:0x）用户决定：一级不分彼此，验收的独立性由非作者复核保证（Claude 记录）
- 用户问：「一级怎么还要区分你和codex 不是你们一起处理么？」
- 所回提议：改成“非作者二级复核建议通过后，由我直接办验收”。用户原话：「改」。
- 规则：
  - Claude 与 Codex 都可以办任何任务的验收；
  - 只保留“做的人不验收自己”：作者的交付必须先有非作者复核，并且复核建议通过，作者才可以办验收手续；
  - 复核建议打回，或必修项未关闭时，不得验收。
- 落实：
  - 已有非作者复核的作者卡（P3.E1←E4/E7、P3.H1←H2、relay.P1.A45←A46、relay.P2.S1←S2），按复核结论办理；
  - 没有复核的卡补派二级复核：ainerzero.V9.T1、awz.V9.A2、forge.V9.A1、awz.V9.D1、hub.V9.A1、awz.V9.C1，以及 relay.P2.E7 的复跑；
  - 两张架构平级审议（ainerzero.V9.A1、awz.V9.A1）改由二级做独立审议。
- 同步：AinerZero `COORDINATION.md`「双统筹如何避免冲突」第 6 条。


## C20261016-Codex-peer-cycle1：跨项目设计终审与 E1→E3 收束

- awz.P3.H1/H2：限规划草案。H2坐标/本机探针复现证据成立，6项勘误沿用RESEARCH_LOG C20261015-H1：点云开关不证明KHR支持；Godot扩展读取未验证；适配器需明确矩阵/单位/朝向；USD高斯依赖内置USD版本；UsdVol全名；MaterialX版本钉选。D-012始终优先：持久世界权威归Hub，运行/求值归AWZ，中立格式不回写；H1旧概括不能改变此边界。未验收任何UE/Unity/高斯运行能力。
- awz.V9.C1：38项清单大小与SHA本轮重算全一致；W2/W6前置已accepted。只接受归档与迁移登记，Gate B未过，不晋升、不重读final、不再训练W1/W3。
- awz.V9.D1：同意确定性结构优先、either仅undecidable转视觉、失败计零、新鲜评测渲染、身份与锁定独立门；分数参考脚本已含漏判/维度重复/摘要变动等负例。限设计/schema，D2实现与非作者复核另验；无渲染/付费授权。rubric_structural没有适用项时后续实现必须显式N/A，不能除零或冒充满分。
- forge.V9.A1：同意一个来源一个包、final封存eval_suite例外、消费矩阵和no_training沿lineage传播；拒绝新增sim_truth同义来源是正确取舍。正式partition只有train/development/final/quarantine；sim_truth仅通道名、来源simulator_truth，任何“AinerZero侧分区称呼”均不得生成第五分区。v0.1和消费者仍未实现。
- hub.V9.A1：同意五策略、多模态、逐约束残差、神经层不回写世界、锁定检查、来源与成本限制。限设计，未验证提供方、真实生成或生产接入；pending提供方不得执行。
- awz.P3.E4/E7：接受负面独立复核本身。10项反例与4项必补不因报告验收而消失，E1协议不完整成立。

## E1收束与E3强制输入
按用户D-016/ADR-0012迁移决定，E1不再出r3。E1取消为已被E3替代，保留r1/r2及所有失败；不冒充通过。E3吸收E4/E7完整发现并在自身验收前关闭四项必补：执行时身份test及add覆盖/下标失效、redo与会话归属、恢复先只读诊断与commands日志、令牌与缓存绑定编译器身份。

§3.3采用丙的原则：对[0,t)比较真实世界可观察轨迹/事件及呈现与表演的受限投影；允许语义等价的轨迹改写，不用整块world_state摘要作为唯一门。E3必须定义连续片段/插值边界、跨t片段裁剪、全局style处理；“截断再编译”只能是待验证方法，不能直接当成过去不变的证明。用户锁定的机位/剧情事件仍无条件拒绝改动，采样通过不豁免。



## C20261016-Codex-v9-peer：ADR-0012平级审议

方向同意：与RFC和ADR-0011/D-012一致；四协议权威分别为AWZ快照/观察、AinerZero提案、Forge经历；Hub持久世界/AWZ运行求值分工不变。W1/W3不再在AWZ训练，W轨结案清单38项现SHA核对通过，Gate B失败保留；W2美术专项与“P2.W2任务其实执行W1”须保持命名区分。E1按用户迁移决定取消为superseded，负面E4/E7报告已accept，四项必补并入E3；E3依赖改为已验收E4/E7，I1依赖E3，未冒充E1完整通过。

需补文档一致性，不应冻结旧段落：§1“RSSM快速模块”已被修订一替代，正文须标已作废；§3的P2训练说法统一为S1起训练预算；§3/§4的“五接口”统一六接口；§8 T4已由用户单独批准且已ready，不再误写依赖T2或仍草稿；T6采用DA3的§9优先于§8旧VGGT；sim_truth一律通道、来源simulator_truth、partition仍四值；训练暂停仅针对AinerZero训练，已批准T4推理基准不等于训练恢复。

世界脑r3技术修订详见AinerZero reports/V9-A1/codex-r3-review-20261016/review.md。T1互斥和A2的dt/来源问题已经退回各自任务，不以总架构审议绕过协议门。渲染、下载、安装、付费与模型预算都按各自原授权卡；本轮没有启动上述工作。落地顺序P0/S0→世界系统切片→批准后的S1/S2成立；不能把加入更多候选对照写成已授权全因子运行。

本审议任务已完成；技术文档需作者按新修订卡修正，再由非作者一级复核。ADR原accepted代表用户方向决定，不能外推为所有实现/协议已验收。当前输入SHA已随AinerZero审议归档，未修改ADR/RFC原件。


## D-019（2026-10-16 上午）用户决定：先改写架构与任务落地，暂不动代码（Claude 记录）
- 上文：用户提供《AinerZero v10 架构验证》（原件存档 `AinerZero/docs/research/AinerZero_v10_Architecture_Validation.source.md`），问「看看是否可以进行继续改造架构」。Claude 回复：可以，v10 作为 v9 r3 的工程验证层增补，并列出 5 项吸收、4 项改正、2 项确认。
- 用户原话：「先不要动代码 先改写架构  架构方案和任务落地 再开始实现代码任务」。
- 落实：
  1. 19 张写代码的实现卡暂停为 blocked，备注写明原因，原报告与证据不动：
     - ainerzero：V9.A2、B2、G3、T2、T4、T8；
     - awz：P3.I2、A3、A7、C1、C3、E5，V9.A3、D2、D4、B1、B3；
     - forge.V9.A2；hub.P1.D2。
     只读复核卡、文档调研卡照常可领。AinerRelay 自身的基础设施卡未暂停，另询用户。
  2. 架构改写走现有修订卡：`ainerzero.V9.A5`（ARCHITECTURE_V9 r4：Codex 审议强制修订 + v10 验证层）、`awz.V9.A5`（ADR-0012 与落地方案整合，含修订五），各由非作者复核（A6）。
  3. 任务库按 r4 重新落地后，由一级逐张放行或改写被暂停的卡。
- 不变：训练暂停、下载/安装/付费需批准、四分区与来源规则。v10 里的训练、下载与 Blender 批量物理生成仍需用户逐项批准。


## D-020（2026-10-16 中午）用户决定：一级只做高级工作，执行一律交二级（Claude 记录）
- 用户原话：「codex claude只处理高级任务比如算法等 而简单任务给其他二级agent你要弄懂哦 不然太浪费聪明agent的token了」。
- 规则：
  - 一级（Claude、Codex）只做架构、算法、关键取舍、给二级的裁决、审阅和最终验收；
  - 文档整理、契约文件、schema、正反例、测试、证据收集、普通实现，一律拆成二级执行卡（带能力标签）加非作者复核卡；
  - 一级不亲自包办。示例：ainerzero.V9.T1 → T19 执行、T18 复核；awz.V9.A8 → A13 执行、A12 复核。
- 同日整理任务台（依据 V9 r5 与 V9_LANDING_PLAN §12）：
  - awz.P3.E2 的死依赖（已取消的 E1）改为只依赖 E3；
  - awz.P3.I1、P3.E2 已下发口径变更：与 Event/v1、WorldSnapshot v1.2、ObservationPacket v1.1、E3 信封重叠处一律引用，不另定义；
  - hub.P1.B1 按非作者复核 B4 的结论恢复最终验收，有效版本为 B3 的 v0.1；
  - ainerzero.V9.A9 与 awz.V9.A11 两张架构复核，按 D-018 办理验收；
  - Codex 额度用完期间，ainerzero.V9.T1、awz.V9.A8 由 Claude 接手，只审阅、不包办。

## C20261016-Codex-E8-D4：负面复核与返工门

- E9 的非作者复核报告成立并已验收：E8 r1 归档与局部结构证据可保留，但 JSON Patch 的 `test` 可被中途替换祖先数组/同位值绕过，锁定用例的 actor 与错误优先级冲突，三份 schema 允许不一致形状，JCS 数字及黄金用例数据改坏对照不足。E8 已退回 r2；提交令牌如何传递、`fps` 改变如何保护过去时间线，须在 E5 开工前明确。E5 仍受 D-019 暂停，不因 E9 报告验收而放行。
- D6 的非作者公开视频/源码核对报告成立并已验收。D4 r2 的九层结构和 Cycles 只读探测有局部证据，但 V3 八处秒点与公开播放器画面不符；部分 shader 行号及 `physics/cloth/bone` 零命中说法有误，未渲染的原生替代写成无损失。D4 已退回，原图与报告保留，需按公开视频重新标点、改引文并逐层标未渲染实测。未下载、采购或新增渲染预算。
# C20261017-style-character-r1：D1/D5一级设计候选（Codex）

P3-D4 r4经D8非作者勘误复核并核对当前九件清单SHA后限研究范围验收。依已解锁的D1/D5任务写入 `docs/design/STYLE_PACKAGE_V2.md` 和 `docs/design/CHARACTER_PACKAGE_V2.md`：风格包沿v8§9.3结构、显式后端退化、三套v1原位映射与.apack旁注；角色包保留v1身份/金样，九项美术控制与世界真值分离，命名控制器是待注册候选，Hub pending不自动执行。当前dusk_soft文件是schema v1、资产v2，历史资产v1失败保留，不据此判当前v2通过。

一级只交设计，schema形式化由D9/D10二级执行，D11非上述任何作者独立复核后再决定完整验收。未建模、渲染、下载、安装、训练或写运行代码；不改主架构r5与A10代码总门。范围/数值均为候选声明域，不是新科学门或预算授权。



## C20261017-CF-landing：角色优先兼容扩展与工作台落地候选

- 用户：“好的那工作台和方案落地”；工作台已明确为现有AinerRelay。主责Codex，二级文档proposal_writer，非作者character_inventory。
- 正式落地候选：[ADR-0013](docs/adr/ADR-0013-character-first-production.md)、[CHARACTER_FIRST_LANDING_PLAN](docs/design/CHARACTER_FIRST_LANDING_PLAN.md)，独立扩展ID CF-r1-20261017；现行V9-r5-20261016和原冻结JSON保留。状态为方向已同意、发布待本轮非作者核对；不是实现/视觉验收。
- 保留D-011/D-012三系统与单一权威，World Compiler仅跨工具DAG/cache，Hub worker离线候选经AWZ采用；AinerZero不作生产前置，训练暂停/M2常设对照/来源隔离不变。
- 队列拆分能力绑定、真实角色/统一worker、DAG/cache、身体/表情音频/版本API/角色曲线UI、接触/双人、完整15秒QA；每实现配非作者验证。优先复用原卡，不同时抢写原D1/D2/D5/worker/运行/变更文件，不解冻1.4.3角色包模块。
- 情绪/口型重叠部位唯一blend owner、solve→adopt→render版本和无环约束写入正式任务正文。120Hz/E3/A2/ADR-0007/ACIS与用户锁不变。
- 主责live核对：A8r2/A12 accepted限CPU合成契约层及R1–R4/F2/F4落纸，Event/snapshot仍未采用候选；T1r3/T18 accepted亦不代表缓存真实加载/ModeGuard/Forge消费者已实现或候选采用。旧出版失败和原报告保留。
- 当前入口将旧R1/Godot正文标历史，不重写旧accepted ADR，不提高模块成熟度。A10与原依赖/paused保留，代码、模型、训练、下载、渲染未放行；本轮无产品实现/Schema/测试/运行/提交推送。
- 在线任务/模块由主责另处理，真实ID/状态/前后依赖以其后续registration报告为准；文档修改前字节与新身份另存 [landing报告](../AinerZero/reports/character-first-landing-20261017/REPORT.md)。
