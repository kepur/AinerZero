# ADR-0014 受限机制形成环（Constrained Mechanism Formation Loop, CMFL）

- 扩展 ID：**CMFL-r2-20261028**；日期：2026-10-28；状态：**proposed（r2 草案，响应 ainerzero.V9.A12 非作者审议，待 A13 复核）**。
- 起草：一级 claude-agy（Relay 卡 ainerzero.V9.A11 r2）；r1 审议人：deepseek-v41f-n4t8（`reports/V9-A12/报告.md`）；设计来源：一级 claude 的 [REPORT](../../../AinerZero/reports/frontier-integration-20261027/REPORT.md) 与 [DESIGN_CORE](../../../AinerZero/reports/frontier-integration-20261027/DESIGN_CORE.md)（2026-10-27/28，原字节保留，勘误以本文 §8 与 RESEARCH_LOG 补记为准）。r1 原字节封存于 `reports/frontier-integration-20261027/adr-0014-drafts/ADR-0014-r1-draft.md`（SHA256 `cceaa997…7a4b`）。
- 研究线主责统筹：claude（CMFL 线）。S1、T6、E0 等既有线主责不变。
- 用户授权口径：用户 2026-10-28「落地并入工作台」= 立项并登记卡片。**本 ADR 不授权**训练、MLX 运行、下载、安装第三方包（pysindy、PySR/Julia、MuJoCo 等）、付费、云 GPU，也不修改任何冻结参数、门槛、数据分区或已交付证据。
- 现行主基线：[V9-r5-20261016](../../../AinerZero/ARCHITECTURE_BASELINE.md) 与 [ARCHITECTURE_V9](../../../AinerZero/ARCHITECTURE_V9.md)；与 [ADR-0012](ADR-0012-v9-neurogeometry-hjepa.md)、[ADR-0013](ADR-0013-character-first-production.md) 兼容，不替换任何 accepted ADR。

## 0. 定位与一句话

CMFL 是 AinerZero **世界脑学习平面**的 S6/E1 扩展：在“学不学、学什么”之前，先用确定性层与参数辨识回答“现有机制够不够”；只有经过独立、可核验、单侧控制错误接受的检验，新机制才能从 MID 晋升到 SLOW。

- **不改** ADR-0013 角色优先主线：世界脑仍是旁路，不是出片前置，也不是 LLM 导演。
- **不建**第二套世界脑，不改 GeometryCore（零可学习参数），不改 AWZ 世界侧权威物理与 `mechanics_pack`；SLOW 机制库属于 AinerZero 学习侧，另立，不混进 AWZ 世界侧登记。
- 落点全部在 r5 已定义的组件与式子上：式 7（信息增益）、式 8（先验 φ̂ + 残差，机制 ID 与作用域）、式 6（学习保护）、式 13（配对 bootstrap 非劣/优越）、FAST/MID/SLOW、`SpatialMemory.consolidate/promote`、`PromotionEvidence`、`SkillProposal`、§2 Teacher Gateway、§7.2 教师=带噪传感器、§8.6 学习侧信息边界；其中 §3 的 C1–C7 是对这些接口的**收紧与承载定义**，不新增运行时。

## 1. 背景（现状缺口，只列承重项）

| 缺口 | 现状证据 |
|---|---|
| 无“机制是否充分”的判定，也无适用域/弃权/OOD | 全仓零命中；唯一的“域”检查是编码器版本不符即拒 |
| SLOW 晋升独立性未核验 | `interfaces/types.py` `PromotionEvidence` 只有 kind/report_ref/producer/test_id；`validation.py` `PRODUCER_REGISTRY` 中 `student → self` 可通过 `validate_producer`（学生自证）；producer 为自报字符串 |
| `Fragment` 缺 ARCH §2 要求的来源、对象、动作键 | `types.py` `Fragment` 只有 `fragment_id`/t_ticks/place/partition/encoder_version/metric/topology |
| 接口无撤销与降级 | `SpatialMemory` 只有 `consolidate`/`promote` |
| E1 缺“无网络参数辨识”对照 | E1 数据端随机化的是隐参数（AWZ `e0/hidden_params.py`），③ 的 ≥10% 门对手里无该组 |
| 式 8 的 F_prior 与 r_θ 只有文档 | ARCH §4 式 8；无代码 |
| E0 接触与速度真值不合格（E1 硬前置） | 包围球启发式接触、60 fps 后向差分速度；修复卡 awz.V9.B20，复核 awz.V9.B21 |

## 2. 决定

### D1 机制充分性门（Mechanism Sufficiency Gate, MSG）

**作用**：学习侧路由器，决定“怎么解释残差”。与 `UpdateScheduler`（决定“更新哪些信念节点”）正交，不替代它。

**输入边界（§8.6 硬约束，含 M8/M9）**：
- 只读自身信念、允许观察、学生已执行动作，以及登记配置（D_permit、阈值登记）。绝不读 Event/v1、世界 ID、对象真值 ID、sim_truth、生成器偏差标签、评测通道。
- **式 8 的 `event` 参数消歧（M9）**：r5 §4 式 8 `r_θ(local_graph, event, history)` 中的 `event` 严禁指向世界侧 `Event/v1`；在学习侧它只能是 §8.6 允许的两类事件——观察事件（如 `ObservationPacket` 的 `audio_events`）或世界脑内部自产的信念事件（如阈值跨越、预测残差突变）。
- 实现须在**实际加载路径**上测试，并通过 §8.6 的“同观察、异未来”反例：两个世界在 t 前观察相同时，MSG 在 t 的路由码与原因必须相同。
- **D_permit 来源审计（M8）**：因为 `D_permit` 在“同观察、异未来”对照中是同一常量，该反例结构上测不到 `D_permit` 夹带实验者知识。故规定：(a) `D_permit` 必须在实验登记**之前**冻结并记录 provenance（出具人、依据、所用数据身份，且不得触碰 T 或评测世界配置）；(b) 严禁在 `D_permit` 中编码“某区域/参数段没有未知机制”这类否定性世界知识，`D_permit` 只许表达执行器物理安全界与任务允许操作范围；(c) 评测侧必须跑一次“去掉 `D_permit`（即 `ABSTAIN` 恒不触发）重跑”的敏感性对照，报告路由分布变化。

**路由**（对每个上下文 c = 信念子图 × 预测窗 W，按序判定，首条命中即停；共 8 个路由码，含 M4 拆出的下尾路由）：

| 序 | 路由码 | 判据 | 动作 |
|---|---|---|---|
| 1 | `ABSTAIN` | c 超出边界教师登记的 D_permit | 不探索，记原因；可请求扩大范围（新登记，不在运行内改） |
| 2 | `OUT_OF_DOMAIN` | 不存在 m ∈ SLOW 使 c ∈ D_valid(m)（越界由包络判定，见 D3-4） | 退回通用残差预测并放大不确定性；记为 MID 候选 |
| 3 | `NUMERICAL` | ε_num = ‖F_m(dt) − F_m(dt/2∘dt/2)‖ ≥ κ‖r‖ | 换积分器或步长，**不学习** |
| 4a | `COVARIANCE_INCONSISTENT` | NIS 统计量 Σ_{k∈W} r_kᵀS_k⁻¹r_k < χ²_{W·d}(α_s/2)（**下尾**，S_k 系统性偏大/滤波器过度保守） | 重标定观测/过程噪声协方差 S 或 Q；**不学习、不作为 SUFFICIENT 缓存、不进入 D_valid 标定**（防过大 S 污染分位数，M4） |
| 4b | `SUFFICIENT` | NIS 统计量落在 [χ²_{W·d}(α_s/2), χ²_{W·d}(1−α_s/2)] 内 | 直接求解、缓存 |
| 5 | `PARAMETRIC` | 更新 p(φ\|D) 后，第 4b 条在**未参与拟合的留出窗**上通过（若落入 4a 则转 `COVARIANCE_INCONSISTENT`） | FAST 内在线辨识（参数增广滤波或低维 SMC，无网络） |
| 6 | `UNIDENTIFIABLE` | 在无量纲化参数上 λ_min(I_φ) < τ_id，或 H(p(m\|D)) > τ_H | 先做竞争机制筛查，只保留可区分可观测量；再在 D_permit 与预算内选探针（见 D4） |
| 7 | `STRUCTURAL` | 第 5 条后仍超出 χ²_{W·d}(1−α_s/2)（上尾）且在 ≥K 个**独立上下文**失败 | 开 MID 离线发现作业（D2） |

统计前提与可执行定义（实现与报告必须写明，不得省略）：

- 第 4a/4b 条的 χ² 分布只在“模型正确、残差为高斯、S_k 为正确的创新协方差、跨 k 条件独立”时成立（滤波创新满足；开环多步预测残差相关，必须改用联合协方差或降采样去相关）。
- 第 5 条若在拟合数据上复检，自由度应扣减拟合参数个数且不再是精确分布；故规定用留出窗。
- 第 6 条 I_φ = Σ J_kᵀS_k⁻¹J_k 是线性化高斯近似；λ_min 依赖参数尺度，τ_id 只对按先验尺度无量纲化后的 φ 有意义。
- **独立上下文的可判定定义（M5）**：两个上下文 c₁=(g₁, [t₁, t₁+W))、c₂=(g₂, [t₂, t₂+W)) 称为独立，当且仅当 (i) 属于不同世界实例（`world_instance_id` 不同），或 (ii) 在同一世界内时间窗间隔 ≥ τ_decorr（去相关步数，登记时冻结）且涉及的信念子图对象集合不相交（`objects(g₁) ∩ objects(g₂) = ∅`）。K 计数只对满足该谓词的最大独立子集计。
- 第 3 条先于学习：避免把积分误差学成假规律；第 5 条先于第 7 条：参数未辨识干净前不得宣称新结构。

**完整冻结清单与单一权威（M5）**：
所有可调量写入一份带 SHA256 的 **CMFL 登记文件**（`cmfl_registration.json`），在运行/实验登记时冻结；运行内不得修改，改任一字段 = 新登记 ID + 新实验 ID，旧结果不覆盖：
1. **MSG 路由参数**：α_s、κ、τ_id、τ_H、K、W、τ_decorr、积分器/步长集合、D_permit 版本与 provenance SHA；
2. **发现与晋升参数（D2/D3/D4）**：优越性边际 δ_gain、序列级 FDR 水平 α_seq、e-LOND 权重序列 γ_t（显式公式或数组，满足 Σγ_t ≤ 1）、发现作业候选预算上限 N_max（实际尝试数 N 由发现作业只追加日志自动计数并带 SHA，不得手填）、D_valid 分位数水平 α_dom、FPCA 截断秩 r_fpca（或累计方差阈值）、审计置信水平 α_audit 与最小分母 n_min、e-process betting 网格 {λ_k} 与 K_bet、预先声明的世界族列表 `env_families`、bootstrap 重采样次数 B_boot 与 RNG seed、嵌套 MC 内外层样本数 (M_in, M_out)、FactTest 标定参数 (τ_cal, δ_cal, n_cal)；
3. **与 r5 已有冻结源的单一权威关系**：r5 式 6 的 (ε, θ_baseline)、式 10 的 τ、式 11 的 η、式 12b 的 (f_max, u_max) 仍以 r5 实验预登记为唯一权威；`cmfl_registration.json` **只通过 SHA 引用它们，不复制、不覆盖**。

**可观测性**：每次判定记录路由码与原因（`COVARIANCE_INCONSISTENT` 单独计类），风格同 `fallback_reason()`，进入运行报告与 MSG 混淆矩阵。

**评测（只在评测侧，封存，不进模型输入）**：生成器给出真实偏差类型（参数/结构/数值/协方差失准），算 MSG 混淆矩阵；模型恢复与参数恢复矩阵（报告不对称混淆）；改动定律世界检验非记忆；去掉 D_permit 的敏感性对照（M8）；负对照：候选库故意缺项或缺状态时，晋升准入率应为 0。

### D2 离线发现（MID；不占实时帧率，CPU 优先）

1. 连续残差：自实现弱形式稀疏回归（STLSQ，NumPy）→ 可执行先验检查器剪枝（量纲一致、重力对齐 SE(2) 对称、无输入时能量不增、已知渐近）→ 仍不足才考虑重型符号搜索（PySR 等，**安装需用户另批**）。
2. 离散规则（门锁、局部禁区、开关）：受限 DSL + 反例引导归纳合成（CEGIS），在全部历史轨迹上回放逐例零回归。
3. LLM/教师提出的补丁只进 MID，与其他候选同等受检；关掉 LLM 时 1–2 仍可运行（r5 §2）。
4. 每个候选记 Pareto（误差 × 复杂度）、出处（proposer 类别、数据身份）与本作业实际尝试候选总数 N（由发现日志自动累计，≤ N_max，供 D3-3）。
5. 网络残差只学确定性核心未覆盖部分：按覆盖度降权采样；分数层融合须带自适应缩放 γ = 1 + max log p − min log p。
6. **残差输入边界（S4）**：残差只读净化后的观测与动作，**不读引擎特权状态**；但它通过式 8 的 `⊕` 修正预测的下一状态是允许的。规律切换用变点检测；对同一抽样反复修改过的候选，成功率估计偏乐观，故 D3 独立测试集不可省。
7. **残差与参数灵敏度正交（S1/S5）**：把 r_θ **硬约束**在灵敏度子空间的正交补内（注：本 ADR 采用硬投影约束，强于 MOS-discrepancy `2610.09261` 的高斯过程软先验；MOS 论文许可为 CC BY-NC-SA 4.0、无代码发布，其理论结论只作机制启发，不作本实现的统计保证）。灵敏度口径分两档登记：(a) 单步灵敏度 ∂F_prior/∂φ；(b) k 步传播灵敏度 S_k^φ = ∂s_{t+k}/∂φ（由变分/灵敏度方程沿轨迹联立求得）。只用单步正交时，φ 误差在多步 rollout 上仍可能被残差部分吸收，必须作为已知限制写入报告。由正交性推出的后果须照写：此时 φ̂ 是 L² 投影参数，不是物理真值；真实偏差沿灵敏度方向的分量按定义并入 φ̂。
8. **选结构与做检验分开取数据**：data thinning 拆出独立视图（精确独立性只在已知方差高斯等可加性族成立；其余情形为近似，须写明），一份选项、一份检验；不可辨识项不报区间，视为弃权。
9. 失败轨迹只监督后果预测（下一状态、碰撞事件），不进入动作先验或技能模仿；10 步位置误差与碰撞 F1 在失败子集上单列。

### D3 单侧晋升门（MID → SLOW）与统一错误预算（M1/M2/M3）

候选 m′ 对现任 m₀，在独立世界集合 T 上检验。发现数据 D、标定数据 C、测试集 T 三者身份强制不相交，全部取自 development 分区；**final 不碰**。

**为什么只设“错误接受”硬门、不设“误拒”硬门（M1 更正）**：
OSVerify（`2610.18089`）的目标是最大化无效解拒绝率（TNR = 1 − 无效解错误接受率），这与本门控制错误接受是**同一方向**（r1 草案与 REPORT 写“方向相反”系事实错误，特此更正）；区别在于 OSVerify 还对有效解误拒率（FNR）设了硬约束（如 5%），因为拒掉稀有有效解不可恢复。而在 CMFL 中，误拒一个有效候选只是暂缓晋升——候选仍留在 MID、证据账本只追加、后续可补采证据重测（**误拒可恢复，错误接受写进 SLOW 会污染下游确定性层**）。因代价不对称，本门只对错误接受设硬门，误拒率只报告不作门；OSVerify 在 5% FNR 约束下报告的 46%/57% 等工作点数值在定义上不可移植到本门。

**统一错误预算表（M3）**：
第 t 次晋升检验只测 **1 个冻结候选 m′**（若同一发现作业向 T 送检 N>1 个候选，则该次检验的预算先替换为 α_t / N）。同一个 T 上跑的三类决策检验共用当次预算 α_t（由 e-LOND 给出：α_t = α_seq · γ_t · (R_{t−1}+1)，其中 R_{t−1} 为此前已晋升次数，默认基准 α_seq = 0.05，在 `cmfl_registration.json` 冻结）：

| 装置 | 作用对象 | 误差语义与预算归属 |
|---|---|---|
| e-LOND 序列预算 α_t | 第 t 次晋升决策（总闸门） | 控制整条晋升序列的 persistent-target FDR ≤ α_seq；单次晋升满足 E_pers ≥ 1/α_t（或等价 p ≤ α_t） |
| D3-1 优越性检验 | T 上 m′ 对 m₀ 的损失差 Δ | 不再硬编码 95%；配对 bootstrap 单侧置信上界水平取 **1 − α_t / (2N)**（与 D3-2 各分 α_t/2 的 union bound，N 为本次送检候选数，默认 N=1） |
| D3-2 式 6 旧能力保持 | 旧任务/基准上的回归损失 | 沿用 r5 式 6 硬阈值 `L_old ≤ L_baseline + ε`；若用 bootstrap 上界检验，则分担另一半 **α_t / (2N)** |
| D3-5 逐例不回归 | T 与历史反例库上的每一条确定性回放 | **零容忍硬门**（0 违规，不消耗概率预算 α_t） |
| D3-4 适用域分位数 α_dom | C 上的残差包络宽度 | 预测覆盖参数（如 α_dom = 0.05 即 95% 边际覆盖），决定 D_valid 大小，不是假设检验 p 值 |
| D3-8 FactTest 次序统计量 (τ_cal, δ_cal, n_cal) | 在留出集 C 上标定固定评分器的拒绝阈值 | 以 C 中**已知无效/退化对照候选**为 null 类，选最小次序统计量 k 使“无效候选越过阈值的比例 > τ_cal”的二项尾部概率 ≤ δ_cal（把 OSVerify B.4 的单侧次序统计量过程反转到“无效候选为 null”以匹配错误接受控制） |
| D3-6 审计上界 α_audit | 晋升后在 T 上的零违规审计报告 | 报告量 `1 − α_audit^{1/n}`（默认 α_audit=0.05），用于披露小样本保守上界 |

具体条款：
1. **优越性**：以**世界实例（world-level block/cluster）**为独立重采样单元做配对 bootstrap，Δ = e(m′) − e(m₀) 的 (1 − α_t/(2N)) 单侧上界 U < −δ_gain（式 13 的优越性镜像）；δ_gain 登记时冻结。
2. **旧能力保持**：式 6，原样适用。
3. **多重比较与序列控制（含 M2 的 EGR 三条件与 0.621 警示）**：
   - 单次发现作业：推荐在 D 上只选 N=1 个候选送 T；若送 N>1，按登记的 N 做 α_t/N 校正。
   - 连续多次晋升采用 Evidence-Gated Research（`2610.01751`，Yifan Guo）的 all-environment 合成 + e-LOND，**必须同时满足其定理 2 的三项前提**：
     - **(i) 贷前冻结**：挑战者 m′、过滤规则与 `test_id` 在打开候选 t 的任何决策证据（T）之前冻结；
     - **(ii) 证据单元为世界级 block/cluster（联合历史条件均值）**：同一世界内的多回合、多步轨迹强相关，边际均值条件不足以保证有效 e-process；输入 e-process 的每个观测单元必须是**独立采样的世界实例（或经证明条件独立的块）**，严禁把轨迹步或同世界回合当独立行喂入；
     - **(iii) 可预测的预算分配与停时**：样本分配与停止规则只依赖截至上一单元的过滤历史 F_{t−1}，不得事后挑停时。
   - 在预先声明的每个世界族 e ∈ `env_families` 上各建一条满足 (i)–(iii) 的 e-process，用交并检验合成 `E_pers = min_e E^e`（无需跨族独立，代价是被证据最慢的一族拖保守），再把 `E_pers` 喂给 e-LOND（`E_pers ≥ 1/α_t` 才采纳）。
   - **已知失效警示（M2）**：在 EGR 的 5,000 轨迹闭环基准中，只喂开发集 e-value 的 **dev-only e-LOND 的 persistent FDR 高达 0.621**，而喂审计后 all-environment `E_pers` 的变体未观察到持续错误采纳。故**严禁对单一开发集 e-value 单独跑 e-LOND 宣称控制了晋升 FDR**；只有目标显式声明为“在每一声明世界族都优于现任”且喂入 `E_pers` 时，序列保证才成立。
   - 晋升会改变现任者 m₀，从而影响后续候选（路径依赖），必须在报告里写明。
   - 准入（ALDER 式）：文法、预算、准入阈值在发现前冻结；准入由提议方看不到的留出数据决定；预算内无人通过即不返回候选；失败提案不删，证据账本只追加。
4. **适用域 D_valid（含 S3）**：= (D ∪ C) 协变量覆盖包络 ∩ 标定残差分位数。
   - 共形覆盖只在可交换前提下、且只在 D_valid 内是**边际**覆盖；越界检测靠包络，不靠共形。
   - 先做可交换性自检（时间二分比较残差统计，必要时降采样去相关）。
   - 分位数用有限样本修正：在 C（样本数 n_cal）上取第 `k = ⌈(1−α_dom)(n_cal+1)⌉` 个次序统计量；若 `k > n_cal`，证书为空，拒绝晋升（注：本条依据标准 split conformal 有限样本引理；REPORT 中关于他文漏修正的评述移交 R11/R12 文献核实，不作本条判据）。
   - **FPCA 基与标定集严格分离（S3）**：若对残差曲线先做 FPCA 降维再做 split conformal，**FPCA 基函数必须在发现集 D（或 C 的独立前半 split C₁）上估计并冻结**，共形次序统计量只能在未参与估基的标定集 C（或后半 C₂）上取；严禁在同一批数据上既估基又取分位数。漂移下可用 ACI 在线更新，但只有长期平均覆盖，须报实测覆盖率。
5. **反例与逐例不回归**：T 上失败上下文全部留档；带已知反例的晋升须先收窄 D_valid 再重测。回放门是**逐例**不回归，不是聚合分数改善（这是本项目的工程硬要求，不依赖外部论文作依据）。反例分类：执行/接口 > 缺失隐变量 > 状态/读出不符。
6. **审计统计与稳定过滤器定义（M5）**：
   - **可复现与稳定过滤器的可执行定义**：候选机制在同一输入、同一确定性域下两次独立运行的预测与路由码一致率必须 = 100%，且数值积分步长减半（dt vs dt/2∘dt/2）时轨迹差异不触发 `NUMERICAL`；未过此过滤器的候选直接判违规，不进入后续统计。
   - 过滤后在 T 上计违规；零失败时报精确二项上界 `1 − α_audit^{1/n}`（n 为独立世界实例数，n < n_min 时标为样本不足不予晋升）；按世界族分别报告；曲线级（步/帧）与审计级（独立世界实例）分母分开报告，严禁混用虚增样本量。
7. **出处与独立性**：记录知识起源类别（sindy/symbolic/llm/teacher/human）；证据出具者必须是与生成过程隔离的独立测试身份，**不得是学生自身**；producer 由可信上下文绑定，不是自报字符串。判定是二值硬门，由独立仿真测试给出，不由任何评审模型给出。
8. **阈值标定**：见统一错误预算表 D3-8，在留出集上用次序统计量标定，不得在评测集上扫阈值。
9. **回滚**：SLOW 条目版本化，带 supersede 指针；编码器、F_prior 或 GeometryCore 版本变化触发重验，重验完成前该条目不被确定性层使用（fail-closed）。

### D4 受限主动实验（含 S2/S7）

- **与 r5 式 7 的关系（S2）**：r5 §4 式 7 `a* = argmax_a I(S; O_next | a)` 的信息增益对象是**状态信念 S**；本节在 `UNIDENTIFIABLE` 分支下选 `a* = argmax_a EIG_φ(a)`，用的是式 7 的**同一 argmax 形式**，但目标换成**物理参数 φ（或机制指标 m）**的后验信息增益，**不修改式 7 原定义**。
- 只在 D_permit 与登记预算内选探针。线性高斯近似 `EIG_φ = ½ log det(I + S⁻¹JΣ_φJᵀ)`；非高斯用嵌套 MC，须在 `cmfl_registration.json` 登记内外层样本数 (M_in, M_out) 并说明其估计偏高（内层对数边际似然的 Jensen 偏差）。
- `EIG_φ` 是学生自报量，**不进门禁**（同 SkillProposal 裁决 6）；执行仍经 SkillProposal 门禁与 AWZ 准入。
- **与 SkillProposal v1 的边界（S7）**：SkillProposal v1 已有单次提案的 `action_budget` 与 `expected_outcomes`（`sigma>0`），探针实验先只用 v1 内已登记的探针能力；若需携带假设/机制 ID 引用、`EIG_φ` 字段、**跨多次 proposal 的累计实验级预算**或显式干预变量白名单，须另行升版 v1.1（独立合同修订 + 非作者复核），本 ADR 不改 v1 schema（`additionalProperties:false` 原样）。

### D5 教师三职责

| 职责 | 落点 | 约束 |
|---|---|---|
| 知识教师 | φ 的先验、候选机制（带出处；§7.2 带噪传感器） | 永不直写 SLOW；只进先验或 MID |
| 边界教师 | 登记的 D_permit：可操作变量白名单、范围、安全边界、允许泛化包络 | 运行内冻结、带 provenance 审计与去 D_permit 敏感性对照（见 D1 M8）；是登记配置而非自由 LLM 输出；由 MSG 第 1 条与 SkillProposal 门禁共同执行 |
| 评估教师 | 反例与质疑，进入 MID 测试池 | 提出错误 ≠ 确认错误；判定只由独立仿真测试给出 |

工程先验（GeometryCore、F_prior）是版本化代码，按式 8 登记偏差来源，不走 SLOW 晋升；只有学到或发现的机制走 MID → SLOW。

### D6 E1 增补候选（S1 第二阶段预登记时再定；本 ADR 不授权训练）

现有四组 ①有偏先验 ②纯 MLX ③先验 + MLX 残差 ④真参数（上界诊断）**不改**；原门槛（③ 比 ①② 较好者好 ≥10%、碰撞 F1 不降）**不改**。候选增补臂只增加对照与诊断：

| 臂 | 内容 | 回答的问题 |
|---|---|---|
| ⑤ | 有偏先验 + 在线 φ 辨识（无网络，训练参数 0） | 参数类偏差是否根本不需要网络 |
| ⑥ | ⑤ + MLX 残差（辨识之后学，与灵敏度子空间正交，分单步 ∂F_prior/∂φ 与 k 步 S_k^φ 两档报告，见 D2-7）；另报有/无正交约束 | 网络在参数辨识之外的贡献 |
| ⑦ | ⑤ + 符号残差（弱形式稀疏回归，过 D3 才用） | 低算力规律提炼能否替代网络残差 |
| ⑧（可选） | ⑥ 的端口哈密顿约束版 | 能量漂移是否改善（只报告；须在实际离散积分器上实测，不得以连续时间存在性定理代替） |

两族世界：P 族（只有参数偏差，即现 E1）与 S 族（先验缺一项机制，按式 8 带机制 ID 与作用域）。研究假说：P 族 ⑤≈④ 且不劣于 ③；S 族 ⑥/⑦ 优于 ⑤。

**原门槛独立性声明（M10，必须同步写入 P48 验收条款）**：
**新臂 ⑤–⑧ 不参与 E1 原门槛判定。即使实验结果在 P 族出现 ⑤≈④（即仅靠参数辨识已接近真参数上界），臂 ③ 相对 ①② 的过门结论仍按 r5 原门槛（10 步位置误差优于 ①② 较好者 ≥10% 且碰撞 F1 不降）单独成立，不得以 ⑤ 的表现否决 ③ 过门；⑤–⑧ 仅用于诊断和解释 ③ 的增益中有多少来自隐参数推断、多少来自未知结构补偿。**

前置（全部满足才可放出 P48 执行卡）：本 ADR 定稿；E0 真值修复 awz.V9.B20 通过且 B21 非作者复核通过；60 fps 对 120 Hz 对齐与 Z-up→重力坐标映射登记；S1 第一阶段过门；用户批准第二阶段训练预算；逐臂预登记数据、预算、种子、指标。

## 3. 契约变更清单、迁移与回滚（含 M6/M7）

现状：`SpatialMemory` 只有 fake 实现，没有生产 SLOW 条目；`validate_producer` 在全仓 `src/` 中只有一个调用点（`types.py:476-477`，`PromotionEvidence.__post_init__`）。因此迁移只涉及接口、fake 与合同测试。所有未入 git 的接口文件开工前先记 SHA（REPORT §2 治理问题）。

| 变更 | 内容 | 迁移 | 回滚 |
|---|---|---|---|
| C1 `PromotionEvidence` v2 | 新增：`schema_version`、适用域引用、校准（方法、α_dom、n_cal、可交换性自检引用、FPCA 基数据身份）、错误接受控制（e-LOND 状态引用、α_t、尝试数 N、test_id 贷前冻结引用、世界级 block 单元声明）、反例引用、知识起源类别、发现 D / 标定 C / 测试 T 数据身份（构造时强制两两不相交）、式 6 回归引用、条目摘要与编码器版本 | v1 对象仍可构造与读取，但 `promote` 只接受 `schema_version=="v2"`；v1 证据在 `promote` 时一律拒绝（fail-closed）并给明确错误 | v2 字段带默认或子类化；回滚 = 恢复接受 v1 的 `promote`，不影响已有数据 |
| C2 SLOW 独立出具者守卫（M7） | **选定方案 (b)**：`PRODUCER_REGISTRY` 与 `validation.validate_producer(producer)` 的现有签名和登记表权威保持不变；在 `validation.py` 新增专用于 SLOW 晋升的 `require_independent_slow_producer(producer, *, trusted_context)`，在调用 `validate_producer` 的基础上**额外拦截类别 `"self"`**（即 `producer="student"` 不得出具 SLOW 证据），并要求 `trusted_context` 绑定（照 `teachers/cache.py` 的 `trusted_context` / `admission_bindings` 做法，拒绝无绑定上下文的裸自报字符串）。`PromotionEvidence`（v2）与 `SpatialMemory.promote` 调用该函数 | 不改 `PRODUCER_REGISTRY` 本身、不建第二套登记表；原依赖 `producer="student"` 可晋升的测试改写为负例（验证 `self` 被拒） | 切回仅调用 `validate_producer` 即可 |
| C3 `Fragment` 扩展（含 S6） | 在现有 `fragment_id`/t_ticks/place/partition/encoder_version/metric/topology 基础上，新增来源（`provenance_ref`：观察/动作/教师/发现作业 ID）、`object_keys`、`action_keys`（ARCH §2）；字段只引用学习侧可见标识，不得携带世界真值 ID（§8.6） | 旧 Fragment 可读、可查询，但缺新字段者**不可晋升到 SLOW** | 新字段带默认值，回滚即忽略 |
| C4 撤销与降级 | `SpatialMemory` 增 `revoke(item_id, reason, evidence_ref)` 与 `demote(item_id, to_level, reason)`；supersede 指针；编码器/先验版本变化触发重验 | 新方法，fake 与合同测试同步 | 新方法可整体移除，不影响 `promote` |
| C5 CMFL 登记文件（M5） | 新文件类型 `cmfl_registration.json`（含 D1 完整冻结清单 1–3，带 SHA256，只引用不覆盖 r5 已有冻结值） | 新增，无旧数据 | 删除引用即可，不影响既有实验 |
| C6 SkillProposal | **本 ADR 不改**；探针用 v1 已登记能力（含单次 `action_budget`）；v1.1 另立 | — | — |
| C7 参数信念与 MSG 路由记录的承载（M6） | **(i) φ 后验承载**：不改 `BeliefSummary` dataclass（保持位姿语义不变）；在线参数信念 `p(φ\|D)` 作为键 `"physics_param_belief"` 挂在 `UpdateScheduler.update(belief=...)` 已有的通用 `Mapping` 上，并在 `fakes/` 与 CMFL 原型中提供类型化结构 `ParamBelief(mean, cov, dimensionless_scale, updated_at_ticks)`。**(ii) MSG 路由记录 schema**：定义冻结 dataclass `MSGRouteRecord(context_id, t_ticks, route_code, reason, nis_stat, dof, registration_sha)`，每次路由必产出一条，汇总写入运行报告 JSON（`msg_routes.json`），不改中央 `RunStore` 表结构 | 不改 `BeliefSummary` 与 `RunStore` 公共契约；G7 与 B12 共用同一 `MSGRouteRecord` 定义 | 移除附加键与报告文件即可 |

守卫类变更（C1–C4）的实现卡（ainerzero.V9.B12）必须附“拆守卫坏控”：逐条移除守卫后对应负例测试必须变红。

## 4. 明确不改

- r5 冻结基线、`baseline.v1.json` 原字节与冻结身份；E1 原四组与原门槛（⑤–⑧ 不参与原门槛判定）；S1 r13 冻结件（不往已冻结的 S1 加臂）；§8.6 信息边界；“教师与 LLM 不能写 SLOW”。
- ADR-0013 三系统职责与角色优先主线；AWZ 世界侧权威物理与确定性域。
- 训练暂停/解除口径（D-021）、预算、锁、RunStore、数据分区与 final 封存。

## 5. 后果与风险

- 正面：把“何时不该学/不该探索”变成可审计 8 路由（含协方差失准下尾拦截）；晋升独立性、世界级 block e-process 与统一错误预算可核验；E1 能区分“学到未知规律”与“只做参数推断”且不漂移原门槛。
- 风险：可调量若漏进登记文件会变成调参自由度（以 D1 `cmfl_registration.json` 全量冻结约束）；合成玩具世界结论不得外推到 E0/Bullet，更不得外推到真实视频；新研究线与角色优先主线争夺统筹精力（世界脑仍为旁路，不成为出片前置）。
- 文献依据只作协议来源，不把任何论文数字当本机收益；条目最终采信以研究注册表 R11 补登记及其非作者复核（R12）为准。

## 6. 落地顺序（Relay 卡）

| 序 | 卡 | 内容 | 前置/授权 |
|---|---|---|---|
| 1 | ainerzero.V9.A11 → A12 → A13 | 本 ADR r1 → A12 非作者审议（已完成，request_changes）→ 本 r2 修订 → A13 非作者复核关闭 M1–M10 | 无运行 |
| 2 | awz.V9.B20 → B21 | E0 接触与速度真值修复与复核 | E1 硬前置，与本 ADR 并行 |
| 3 | ainerzero.V9.G7 → G8 | CMFL CPU 原型（纯 NumPy 合成玩具力学，含 8 路由、去 D_permit 对照、世界级 block 检验）与对抗复核 | A13 通过后放出 |
| 4 | ainerzero.V9.B12 → B13 | 按 §3 C1–C5、C7 修补晋升证据与复核 | A13 通过、ADR 定稿 |
| 5 | ainerzero.V9.R11 → R12 | 研究注册表补登记（含 §8 的文献勘误） | 无 |
| 6 | ainerzero.V9.P48 | S1 第二阶段预登记草案（含 D6 M10 原门槛独立性条款） | D6 全部前置 + 用户批准预算 |
| — | 安装申请 | pysindy、PySR+Julia（隔离）、MuJoCo | 用户逐项批准；第一阶段无需安装 |

## 7. 状态变更规则

- 本 ADR 由 `proposed` 转 `accepted` 的条件：A12 提出的 M1–M10 必修项经非作者复核卡 ainerzero.V9.A13 确认全部关闭并给出 accept，由研究线主责统筹登记定稿 SHA。
- 历次草案在 `reports/frontier-integration-20261027/adr-0014-drafts/` 封存（`ADR-0014-r1-draft.md`、`ADR-0014-r2-draft.md`），不覆盖。

## 8. r2 修订关闭表（回应 ainerzero.V9.A12 非作者审议 `deepseek-v41f-n4t8`）

| 编号 | A12 审议意见 | r2 处理与位置 |
|---|---|---|
| **M1** | OSVerify 目标是最大化 TNR（拒绝无效解），与控制错误接受**同向**，FNR 只是其约束；r1 与 REPORT 写“方向相反”系事实错误 | 已改写 §2 D3 开头并在 RESEARCH_LOG 补勘误（不改已封存 REPORT 原字节）：删“方向相反”，改以**误拒可恢复 vs 错误接受污染 SLOW 的代价不对称**论证不设误拒门，并写明 OSVerify 在 5% FNR 下的数字定义上不可移植 |
| **M2** | e-LOND 缺 EGR 定理 2 的三条件，尤其 (ii) 证据单元须为世界级 block/cluster；且未提 dev-only e-LOND 在 EGR 基准上 persistent FDR = 0.621 | §2 D3-3 补齐 (i) 贷前冻结、(ii) 世界级 block/cluster 联合历史条件均值、(iii) 可预测分配与停时；写明 0.621 警示，严禁对 dev-only e-value 单独用 e-LOND |
| **M3** | bootstrap 95%、α/N、e-LOND α_t、FactTest 标定四套误差装置无统一错误预算，“T 上只测一次”不准 | §2 D3 新增**统一错误预算表**：删硬编码 95%，bootstrap 与式 6 共用当次 α_t/(2N)，逐例不回归为 0 违规硬门，α_dom 为覆盖参数，FactTest 以无效对照候选为 null 类标定 (τ_cal, δ_cal, n_cal) |
| **M4** | 双侧 χ² 的下尾（S_k 偏大/过度保守）被并入 `SUFFICIENT`，会污染缓存与 D_valid 分位数 | §2 D1 路由表拆出 `4a COVARIANCE_INCONSISTENT`（下尾 < χ²(α_s/2)），动作=重标定 S/Q、不学习、不缓存、不进 D_valid 标定 |
| **M5** | D2/D3/D4 的 12 个可调量未进冻结清单；“独立上下文”“稳定过滤器”无定义；与 r5 `f_max`/`u_max` 权威关系未定 | §2 D1 新增 `cmfl_registration.json` 完整冻结清单（含 12 项）、独立上下文可判定谓词、D3-6 稳定过滤器可执行定义，并声明只通过 SHA 引用 r5 已有冻结值 |
| **M6** | §3 缺 φ 后验承载与 MSG 路由记录 schema；§0“全部是已有接口”措辞过强 | §0 改为“落点在 r5 已定义组件与式子上，C1–C7 为收紧与承载定义”；§3 新增 **C7**（`"physics_param_belief"` 挂通用 belief Mapping + `MSGRouteRecord` 写 `msg_routes.json`） |
| **M7** | C2“只读调用…并在其上扩展”自相矛盾 | §3 **C2** 选定方案 (b)：保持 `validate_producer` 不变，新增 `require_independent_slow_producer(producer, *, trusted_context)` 拦截 `"self"` 并強制可信上下文绑定 |
| **M8** | `D_permit` 在“同观察、异未来”中是常量，反例测不到其夹带否定性世界知识 | §2 D1 输入边界与 D5 新增 `D_permit` 来源审计：实验前冻结 + provenance + 禁编码“某处无机制” + 评测侧去 `D_permit` 敏感性对照 |
| **M9** | r5 式 8 的 `event` 参数与 §8.6 冲突未消解 | §2 D1 输入边界写明：式 8 的 `event` 只能是观察事件或世界脑内部信念事件，严禁传 `Event/v1` |
| **M10** | D6 假说可能被当作隐式新门槛，在 ⑤≈④ 时否决 ③ | §2 D6 新增**原门槛独立性声明**：⑤–⑧ 不参与原门槛判定，即使 ⑤≈④，③ 仍按原门槛单独成立；并同步写入 P48 卡面 |
| **S1** | 灵敏度 ∂F_prior/∂φ 是单步还是 k 步传播 | §2 D2-7 与 D6-⑥ 写明分单步与 k 步传播 S_k^φ 两档，单步正交的残余混淆列为已知限制 |
| **S2** | 式 7（状态信息增益）与 D4 EIG（参数信息增益）不同 | §2 D4 开头写明：沿用式 7 的 argmax 形式而目标换为参数 φ，不修改式 7 |
| **S3** | FPCA 基与共形标定集必须分开 | §2 D3-4 写明：FPCA 基只能在 D（或独立前半 split）上估计并冻结，分位数在未参与估基的 C 上取 |
| **S4** | EMPIRIC“不碰引擎内部”应为“不读引擎特权状态” | §2 D2-6 已改准 |
| **S5** | MOS 论文许可为 CC BY-NC-SA 4.0，且本 ADR 用硬约束强于其软先验 | §2 D2-7 与 RESEARCH_LOG 补记已写明（同时供 R11 登记） |
| **S6** | `Fragment` 主键字段名为 `fragment_id` | §1 表与 §3 C3 已改准 |
| **S7** | `SkillProposal v1` 已有单次 `action_budget`，需 v1.1 的是跨多次累计预算 | §2 D4 与 §3 C6 已改准 |
