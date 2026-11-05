export const meta = {
  name: 'ainerzero-frontier-verify-r2',
  description: 'Finish frontier paper verification (5 groups) and run grouped adversarial re-checks for all load-bearing groups',
  phases: [
    { title: 'Verify', detail: 'remaining paper groups verified against primary sources' },
    { title: 'Refute', detail: 'one skeptic per group re-checks identity, mechanism, license' },
  ],
}

const RAW = '/Users/mac/AinerWorkFlow/AinerZero/reports/frontier-integration-20261027/raw'

const COMMON = [
  '你是 AinerZero 研究统筹（一级 Claude）派出的只读调研子代理。今天是 2026-10-27。',
  '硬性规则：',
  '- 只读。不得编辑、创建、删除任何文件；不得运行测试、训练、MLX、Blender；不得 pip/uv/brew 安装、git clone、下载权重或数据集。阅读网页（WebSearch/WebFetch）可以。',
  '- 联网前先用 ToolSearch 加载：query "select:WebSearch,WebFetch"。',
  '- 2026 年的论文多在你的训练截止之后，必须以一手来源（arxiv.org/abs/<id>、期刊页、官方 GitHub 与 LICENSE 文件）为准；查不到就如实写 not_found / unverifiable，绝不猜测或外推。',
  '- 待核清单来自其他 AI 代理的调研，可能有张冠李戴、编造的 arXiv 号或夸大的数字（已发现的例子：SLIM 被误标为 Meta FAIR、jepa-wms 仓库被错配、PySR 版本过时、MDA 的 93%/31% 已在 v5 删除）。你的职责是核实而不是复述。',
  '- 文字字段用中文；标识符、论文标题、URL 保持原文。控制篇幅：每条 mechanism 不超过 4 句，evidence 给 URL 加要点。',
].join('\n')

const BACKGROUND = '背景：AinerZero 是一个在 M2 Max 96GB、无 CUDA 上研究的小型世界脑：确定性几何核心不训练（GeometryCore，纯 NumPy），网络只学残差与未知规律（式8：s_next = F_prior(s,a,dt;phi_hat) ⊕ r_theta，目前只有文档、无代码；V10-E1 门槛是 10 步位置误差 ≥10% 与碰撞 F1 不降，能量漂移只报告）。知识按 FAST/MID/SLOW 晋升，SLOW 只能由独立测试证据写入（PromotionEvidence 只有 kind/report_ref/producer/test_id），教师与 LLM 不能直接写 SLOW，主动行动走 SkillProposal 门禁（expected_outcomes 带 sigma>0）。用户新方向：确定性知识优先、教师限定泛化、反馈驱动的受限实验与知识晋升。'

const GAP_ENUM = ['G1_residual_structure', 'G2_sparse_change_action_sensitivity', 'G3_low_compute_law_distillation', 'G4_identifiability_active_experiment', 'G5_promotion_verification', 'G6_teacher_boundary', 'G7_mechanism_sufficiency', 'G8_failure_counterexample', 'G9_low_power_control', 'none']

const GAPS = [
  '缺口标签（fit_gaps 只能取这些值）：',
  'G1_residual_structure（残差的物理结构约束：守恒/耗散/无源性）',
  'G2_sparse_change_action_sensitivity（只有少部分变化时的动作敏感性、按事件分配内部算力）',
  'G3_low_compute_law_distillation（CPU/MLX 上把残差提炼成带量纲、带适用域的显式公式或程序补丁）',
  'G4_identifiability_active_experiment（参数/机制可辨识性、贝叶斯后验、主动实验/最优实验设计）',
  'G5_promotion_verification（MID→SLOW 晋升的独立验证、单侧门、错误接受率控制、出处与 Pareto 档案）',
  'G6_teacher_boundary（教师限定可探索范围、先验约束、允许变量白名单）',
  'G7_mechanism_sufficiency（判断已有机制是否足够、适用域/弃权/越界检测、何时不应探索）',
  'G8_failure_counterexample（失败轨迹、反例引导修复、离散规则补丁）',
  'G9_low_power_control（不靠大模型的低功耗决策/控制）',
  'none',
].join('\n')

const PAPER_SCHEMA = {
  type: 'object',
  properties: {
    group: { type: 'string' },
    items: { type: 'array', items: { type: 'object', properties: {
      key: { type: 'string' },
      claimed_ref: { type: 'string' },
      exists: { type: 'string', enum: ['verified', 'partially_verified', 'not_found', 'conflicting'] },
      title: { type: 'string' },
      authors: { type: 'string' },
      date: { type: 'string' },
      venue: { type: 'string' },
      arxiv_id: { type: 'string' },
      primary_url: { type: 'string' },
      code_repo: { type: 'string' },
      code_license: { type: 'string' },
      code_status: { type: 'string', enum: ['released', 'announced', 'none', 'unknown'] },
      paper_license: { type: 'string' },
      mechanism: { type: 'string' },
      needs_llm: { type: 'string', enum: ['yes', 'no', 'optional', 'unknown'] },
      needs_gpu_training: { type: 'string', enum: ['yes', 'no', 'optional', 'unknown'] },
      cpu_or_mlx_feasible: { type: 'string', enum: ['likely', 'partial', 'unlikely', 'unknown'] },
      compute_notes: { type: 'string' },
      claims_checked: { type: 'array', items: { type: 'object', properties: {
        claim: { type: 'string' },
        verdict: { type: 'string', enum: ['supported', 'overstated', 'wrong', 'unverifiable'] },
        evidence: { type: 'string' },
      }, required: ['claim', 'verdict', 'evidence'] } },
      red_flags: { type: 'array', items: { type: 'string' } },
      fit_gaps: { type: 'array', items: { type: 'string', enum: GAP_ENUM } },
      how_to_borrow: { type: 'string' },
      access_log: { type: 'array', items: { type: 'string' } },
    }, required: ['key', 'exists', 'mechanism', 'claims_checked', 'fit_gaps', 'red_flags'] } },
  },
  required: ['group', 'items'],
}

const GROUP_SKEPTIC_SCHEMA = {
  type: 'object',
  properties: {
    group: { type: 'string' },
    verdicts: { type: 'array', items: { type: 'object', properties: {
      key: { type: 'string' },
      identity_confirmed: { type: 'boolean' },
      identity_note: { type: 'string' },
      mechanism_claim_holds: { type: 'string', enum: ['yes', 'partially', 'no', 'unclear'] },
      license_status: { type: 'string', enum: ['confirmed_as_reported', 'differs', 'unknown'] },
      compute_claim_holds: { type: 'string', enum: ['yes', 'partially', 'no', 'unclear'] },
      corrections: { type: 'array', items: { type: 'string' } },
      refuted: { type: 'boolean' },
      evidence: { type: 'array', items: { type: 'string' } },
    }, required: ['key', 'identity_confirmed', 'mechanism_claim_holds', 'refuted', 'corrections'] } },
  },
  required: ['group', 'verdicts'],
}

const NEW_GROUPS = [
  { key: 'H-structure-preserving-backends', items: [
    '1. PH-Dreamer（端口哈密顿生成动力学）— 声称 arXiv 2605.18303（2026-05）。待核：标题、作者、是否把潜空间写成 port-Hamiltonian 结构 dx/dt=(J−R)∇H+Gu；有无代码。',
    '2. Stochastic Port-Hamiltonian Neural Networks — 声称 2026-03，无源性/耗散保证。找到 arXiv 号；核实其保证是连续时间还是离散积分也成立（连续时间耗散不等于离散积分器无能量漂移）。',
    '3. mlx-sim — 声称 GitHub novix-science/mlx-sim，MIT；Apple Silicon 原生 MLX+Metal 刚体/关节动力学（冲量求解器、GJK/EPA、Featherstone ABA、RNEA）。待核：仓库是否存在、成熟度（star、提交数、测试、最后更新）、许可。',
    '4. MuJoCo（CPU）与 MuJoCo Warp — 待核：MuJoCo 许可、macOS arm64 是否有官方 wheel；MuJoCo Warp 是否需要 NVIDIA GPU；“MuJoCo Warp 不可微”的说法；MJX 与 Apple Silicon 关系。',
  ].join('\n') },
  { key: 'J-conformal-validity-bo', items: [
    '1. 共形有效域/弃权 — 声称 arXiv 2607.00776 与 arXiv 2604.27914（2026）。待核：两篇各是什么、是否为“为学到的规律/模型给出有限样本保证的适用域并在越界时弃权”；保证依赖的前提（可交换性等），对分布外输入是否有效。',
    '2. Equivariant Trust Horizons — 声称 arXiv 2606.24946（已在 AinerZero 注册表）。仅确认身份与“共形校准的可信预测时域”说法。',
    '3. MaD Physics — 声称 arXiv 2605.10820（2026-05）。待核：预算受限下的最优测量规划/贝叶斯最优实验设计（BOED）评测；代码与许可。',
  ].join('\n') },
  { key: 'K-failure-rules-nesy', items: [
    '1. FACT（Failure-Aware Causal Training）— 声称 arXiv 2608.10232，CoRL 2026，仓库 Bariona/FACT。待核：只训成功轨迹会让世界模型丧失对失败动作后果的因果判断；方法是什么；许可。',
    '2. PatchWorld — 声称 arXiv 2605.30880（2026-05），仓库 HKBU-KnowComp/PatchWorld，MIT。待核：CEGIS（反例引导归纳合成）补丁；是否用 LLM 生成补丁；在历史轨迹上回放验证零回归。',
    '3. NeSyS — 声称 arXiv 2602.10480，COLM 2026，仓库 tianyi-lab/NeSyS，MIT。待核：可执行符号规则对 LLM 候选状态转移做 log-linear 重排序；“训练数据减少约 50% 同时保持准确率”。',
  ].join('\n') },
  { key: 'GI-recursion-control-misc', items: [
    '1. Tiny Recursive Models（SamsungSAILMontreal/TinyRecursiveModels）与 PTRM（声称 2026-05）。待核：TRM 约 7M 参数、用递归深度替代参数量；许可；PTRM 是什么、arXiv 号。',
    '2. In-Place Test-Time Training — 声称 arXiv 2604.06169，ICLR 2026 Oral。待核：把 MLP 块末层投影矩阵当作测试时在线更新的快权重；是否 Oral；代码与许可。',
    '3. LeWM — 仅确认 arXiv 2603.19312 是否为 LeWorldModel（小型 JEPA 世界模型、SIGReg）。',
    '4. Reference-Free Sampling-Based Model Predictive Control — 声称 ICRA 2026。待核：仅用标准 CPU 实现四足机器人实时控制、无需离线预训练或 GPU；arXiv 号。',
    '5. DWC（Differentiable Weightless Controllers）— 声称 ICML 2026，proceedings.mlr.press/v306/kresse26a.html。待核：可编译为逻辑电路的控制策略；5 个 MuJoCo 基准有竞争力；FPGA 纳焦耳级每动作能耗。',
    '6. 可复用状态价值模型（Active Inference）— 声称 Biological Cybernetics 2026-10-09（link.springer.com/article/10.1007/s00422-026-01066-0）。只核标题与核心机制。',
    '7. Lean 验证的 AI 数学发现（量子纠错码）— 声称 PRX Intelligence 2026-10-06 接收。只核标题与“生成候选与证明正确性分离”的做法。',
  ].join('\n') },
  { key: 'Z-gap-sweep', items: [
    '这是查漏组。已覆盖：EMPIRIC、MDA、T2-z、SuperMimic、Code-as-World、SimulCost、OSVerify、SRHarness、MechBench、Paper2Agent、sciexplorer、CoSR、PG-SR、PI-ADoK、PySR、PySINDy、Mechanistic World Models、LLM-IDEA、AI-Newton、SLIM（2610.03137）、DeepJEPA、JEPA-Anything、TRM/PTRM、In-Place TTT、LeWM、PH-Dreamer、Stochastic PHNN、mlx-sim、MuJoCo/Warp、Reference-free sampling MPC、DWC、Active inference 价值复用、Lean QEC、共形有效域、Equivariant Trust Horizons、MaD Physics、FACT、PatchWorld、NeSyS。',
    '任务：在 arXiv、GitHub、官方博客与 X 上检索 2026-08 至 2026-10 的工作，找出不在上表、但对 G1/G3/G4/G5/G7 有直接价值、CPU 或 Apple Silicon/MLX 上可行、许可宽松的研究或开源项目（例如：残差物理+系统辨识、可微物理在 Apple Silicon 上的实现、程序/符号世界模型、贝叶斯模型选择与主动学习、“何时信任已有模型”的模型充分性检验、科学知识库的出处与版本管理）。',
    '最多返回 6 条，每条都必须核实一手来源；查不到一手来源的不要返回。key 用简短英文名。',
  ].join('\n') },
]

const OLD_GROUPS = [
  { key: 'A-residual-discovery', file: 'verify__A-residual-discovery.json' },
  { key: 'C-science-harness-verify', file: 'verify__C-science-harness-verify.json' },
  { key: 'D-symbolic-regression', file: 'verify__D-symbolic-regression.json' },
  { key: 'E-sindy-pysr-mechanistic', file: 'verify__E-sindy-pysr-mechanistic.json' },
  { key: 'F-jepa-sparse-change', file: 'verify__F-jepa-sparse-change.json' },
]

function verifyPrompt(g) {
  return [
    COMMON,
    '你负责论文核实组 ' + g.key + '。对每一条：找到一手来源，核对身份（arXiv 号↔标题↔作者↔日期↔会议），读摘要与方法部分，核对每条“待核”说法（supported / overstated / wrong / unverifiable，附证据），查代码仓库与 LICENSE 文件，判断算力画像（是否依赖 LLM、是否需要 GPU 训练、在 M2 Max 无 CUDA 的 CPU/MLX 上是否可行），列出红旗。',
    BACKGROUND,
    GAPS,
    'how_to_borrow 写清楚若纳入只借什么（数学形式/协议/评测设计），不借什么（如非商用代码、高频回路里的 LLM）。',
    '待核清单：',
    g.items,
  ].join('\n')
}

const SKEPTIC_RULES = [
  '你是对抗复核员。另一个子代理已对下面这组论文/项目给出核实记录。逐条尝试推翻，而不是附和：',
  '1. 独立重新打开一手来源（arxiv abs 页/期刊页/GitHub 与 LICENSE），确认 arXiv 号↔标题↔作者↔日期是否一致；',
  '2. 检验 mechanism 与 how_to_borrow 所依赖的那一条性质是否真的出自原文、有无夸大（例如把连续时间保证说成离散保证、把特定基准结果说成通用、把 LLM 依赖说成纯 CPU、把立场论文说成有实验）；',
  '3. 检验许可与算力画像。',
  '只复核 exists 为 verified/partially_verified 且 fit_gaps 不全是 none 的条目；其余在 verdicts 里给 refuted=true、corrections 写“未进入复核：<原因>”。',
  '无法从一手来源确认身份则 refuted=true；身份成立但机制被夸大到不能作设计依据也 refuted=true，并在 corrections 写正确说法；都成立则 refuted=false，可补充更正。',
].join('\n')

function skepticFromFile(g) {
  return [
    COMMON,
    SKEPTIC_RULES,
    '待复核记录：用 Read 工具读取 ' + RAW + '/' + g.file + '（JSON，items 数组）。组名 ' + g.key + '。',
  ].join('\n')
}

function skepticFromItems(res, g) {
  return [
    COMMON,
    SKEPTIC_RULES,
    '组名 ' + g.key + '。待复核记录（JSON）：',
    JSON.stringify(res.items, null, 1),
  ].join('\n')
}

phase('Refute')
const oldSkeptics = parallel(OLD_GROUPS.map(g => () =>
  agent(skepticFromFile(g), { label: 'refute:' + g.key, phase: 'Refute', schema: GROUP_SKEPTIC_SCHEMA })))

const newChains = pipeline(
  NEW_GROUPS,
  (g) => agent(verifyPrompt(g), { label: 'verify:' + g.key, phase: 'Verify', schema: PAPER_SCHEMA }),
  (res, g) => {
    if (!res || !res.items || !res.items.length) return { group: g.key, verify: res, skeptic: null }
    return agent(skepticFromItems(res, g), { label: 'refute:' + g.key, phase: 'Refute', schema: GROUP_SKEPTIC_SCHEMA })
      .then(sk => ({ group: g.key, verify: res, skeptic: sk }))
  },
)

const both = await Promise.all([oldSkeptics, newChains])
return { old_skeptics: both[0].filter(Boolean), new_groups: both[1].filter(Boolean) }
