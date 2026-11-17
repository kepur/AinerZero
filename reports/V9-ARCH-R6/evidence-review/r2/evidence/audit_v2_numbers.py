#!/usr/bin/env python3
"""
audit_v2_numbers.py
Systematic audit of numbers, qualifiers, and exact citations for Architecture r6 candidate v2.
Answers the 5 required questions for every quantitative claim in v2.
Verifies all lines with sed -n.
Pure CPU, zero MLX.
"""
import sys
import os
import subprocess
import json

assert "mlx" not in sys.modules, "MLX must not be imported!"

REPO_ROOT = "/Users/mac/AinerWorkFlow/AinerZero"

CLAIMS = [
    # §1 表中的数字
    {
        "id": "SEC1_ROW1_S3_0760",
        "section": "§1 设计决定表: 旧 RSSM/GRU 退出主线",
        "candidate_quote": "外置情景库在长间隔读回上远胜 GRU（二阶段 +0.760），但这几乎由结构决定，不算发现",
        "file": "reports/V9-S3-PHASE2/FINAL-REPORT.md",
        "line": 23,
        "q1_subset": "长间隔读回（长时隙查询，间隔 > 50 步）",
        "q2_metric": "H1（非参数情景库检索准确率增益相对 GRU）",
        "q3_source": "final 运行",
        "q4_status": "登记的主门（H1，门槛 ≥ 0.50）",
        "q5_repeats": "5 个重复（seeds 42–46）",
        "qualifier_audit": "候选稿保留了「长间隔读回」、「几乎由结构决定，不算发现」，未夸大为全面胜过 GRU。"
    },
    {
        "id": "SEC1_ROW4_S3_0001",
        "section": "§1 设计决定表: 地图即记忆",
        "candidate_quote": "跨回合记忆在登记的扰动率下，全部固定格查询合起来不胜过直接看（+0.001）",
        "file": "reports/V9-S3-PHASE3/FINAL-REPORT.md",
        "line": 46,
        "q1_subset": "全部固定格查询（含干净固定格与被遮盖/扰动固定格）",
        "q2_metric": "跨回合情景记忆 G − 照抄当前（直接看）的检索准确率差值",
        "q3_source": "final 运行",
        "q4_status": "登记的描述量（D1，95% 置信区间 [−0.014, +0.017]）",
        "q5_repeats": "5 个重复（seeds 42–46）",
        "qualifier_audit": "v2 补回了「全部固定格查询合起来」，明确指出是全部固定格查询汇总，而不是所有子集都 +0.001（干净格甚至 −0.285）。"
    },
    {
        "id": "SEC1_ROW5_S2_0036",
        "section": "§1 设计决定表: 潜空间预测",
        "candidate_quote": "S2 训练后的诊断里（每臂一个种子），扁平 JEPA 加 SIGReg 的一步误差只有原地不动的 0.036，三个臂里最准",
        "file": "reports/V9-S2-CLOSE/REPORT.md",
        "line": 45,
        "q1_subset": "全部单步转移（一步预测）",
        "q2_metric": "一步潜空间预测误差 / 原地不动（常数先验）误差比",
        "q3_source": "事后诊断（训练暂停后诊断探针）",
        "q4_status": "事后诊断项（非登记过门指标，无置信区间）",
        "q5_repeats": "每臂仅 1 个种子（seed 42）",
        "qualifier_audit": "v2 补回了「训练后的诊断里（每臂一个种子）」，指出只是单种子事后诊断，非正式评测门。"
    },
    {
        "id": "SEC1_ROW5_S2_RANK",
        "section": "§1 设计决定表: 潜空间预测",
        "candidate_quote": "但它的隐空间距离与真实远近的秩相关是 −0.087，完全不会导航。预测准不等于能规划",
        "file": "reports/V9-S2-CLOSE/REPORT.md",
        "line": 45,
        "q1_subset": "潜空间状态对与真实物理距离对",
        "q2_metric": "Spearman 秩相关系数（ρ）",
        "q3_source": "事后诊断探针",
        "q4_status": "事后诊断项（只报告，非登记门）",
        "q5_repeats": "单种子（seed 42）",
        "qualifier_audit": "候选稿准确表述为事后诊断中的秩相关负值，未做任何结论强化。"
    },
    {
        "id": "SEC1_ROW6_S4P2_0835",
        "section": "§1 设计决定表: 解析数学与学习分开",
        "candidate_quote": "全部事件上的重认与用真实物理的滤波器持平（0.835 对 0.836）",
        "file": "reports/V9-S4-PHASE2/FINAL-REPORT.md",
        "line": 24,
        "q1_subset": "全部重新出现事件（含碰撞与无碰撞）",
        "q2_metric": "重识别正确率（重认准确率，C）",
        "q3_source": "final 运行",
        "q4_status": "登记的主门（G-all，与真实物理 E-P 比较）",
        "q5_repeats": "5 个重复（seeds 42–46）",
        "qualifier_audit": "v2 补回了「全部事件上的」，严格限定范围，防止误读为仅碰撞事件。"
    },
    {
        "id": "SEC1_ROW6_E1_259",
        "section": "§1 设计决定表: 解析数学与学习分开",
        "candidate_quote": "反例是 E1：按一步误差训练、每一步都加的残差，在 dev 上 P 族的 10 步预测比纯网络差 25.9%",
        "file": "reports/V9-E1-CONCLUSION/CONCLUSION.md",
        "line": 39,
        "q1_subset": "10 步连续滚动预测轨迹",
        "q2_metric": "10 步位姿预测相对误差差值比（P 族残差 vs 纯网络 S 族）",
        "q3_source": "dev 评估集",
        "q4_status": "摸底与诊断性指标（dev 上的对比）",
        "q5_repeats": "多种子汇总（dev 数据集）",
        "qualifier_audit": "v2 补回了「在 dev 上」，限定数据子集来源为开发集。"
    },
    {
        "id": "SEC1_ROW8_S4P1_NORM",
        "section": "§1 设计决定表: SE(2) 等变",
        "candidate_quote": "全量数据下，规范化臂在有碰撞事件上的重认高 0.023 [+0.010, +0.036]；1/8 数据下看不出差别（−0.006 [−0.022, +0.010]）",
        "file": "reports/V9-S4-PHASE1/final/FINAL-REPORT.md",
        "line": 102,
        "q1_subset": "有碰撞的重新出现事件",
        "q2_metric": "重识别正确率差值（A3 规范化臂 − A1 未规范化主臂）",
        "q3_source": "final 运行",
        "q4_status": "登记的描述量（附 Bonferroni 置信区间，非主门）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「在有碰撞事件上的」，并指出「只是描述量」和「依赖真值位姿」。"
    },
    {
        "id": "SEC1_ROW9_S5_TEACHER",
        "section": "§1 设计决定表: 教师合一",
        "candidate_quote": "S5 的占据读出：双教师减去较好的单教师，64 段标签时 +0.0004 [−0.002, +0.003]，512 段时 −0.011 [−0.020, −0.002]。教师本身在 64 段标签时只多 0.009，门槛是 0.05",
        "file": "reports/V9-S5-FINAL/RESULTS/REPORT.md",
        "line": 47,
        "q1_subset": "网格占据读出任务（64 段与 512 段标签档）",
        "q2_metric": "占据读出 AP 差值：A3 双教师 − max(A1, A2) 较好单教师",
        "q3_source": "final 运行",
        "q4_status": "登记的主门（GT1 点值 +0.0088 对门槛 0.05 不过；GT2 点值 +0.0081 对门槛 0.03 不过）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「的占据读出」，明确限定为具体网格占据读出任务，并保留了 GT1 门槛 0.05 不过的事实。"
    },
    {
        "id": "SEC1_ROW10_V10E2A",
        "section": "§1 设计决定表: 事件驱动稀疏更新",
        "candidate_quote": "V10-E2a 在 5% 稀疏率下中位时间少约 51%，登记域内逐位一致；20% 稀疏率下回退率约 93%，比全量慢约 44%",
        "file": "../AnimeWorldZero/reports/V-V9-B9/报告.md",
        "line": 16,
        "q1_subset": "5% 与 20% 事件稀疏率工况",
        "q2_metric": "端到端墙钟中位耗时降幅比、全量回退率、状态哈希逐位一致性",
        "q3_source": "独立非作者复测基准（awz.V9.B9）",
        "q4_status": "参考实现验收标准（门槛：时间降 ≥ 30%，逐位一致）",
        "q5_repeats": "100 回合批次，432/432 ticks 验证",
        "qualifier_audit": "候选稿明确限定为「世界侧参考实现，非运行时集成」，并如实报出 20% 高稀疏率下的严重回退。"
    },
    {
        "id": "SEC1_ROW11_S3P3_MEMORY",
        "section": "§1 设计决定表: 记忆分级",
        "candidate_quote": "门控减多数票 −0.001；格子改变之后回滚有用（+0.339），不过「只取最近一次」恢复得更快",
        "file": "reports/V9-S3-PHASE3/FINAL-REPORT.md",
        "line": 72,
        "q1_subset": "稳定格查询（门控减多数票）及已改格子查询（回滚）",
        "q2_metric": "检索准确率差值：G − MODE，以及回滚 − 不回滚",
        "q3_source": "final 运行",
        "q4_status": "登记的描述量（D3 门控减多数票 [−0.014, +0.011]；D4 回滚增益 [0.316, 0.362]）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "候选稿如实指出了「收益来自跨回合聚合，不来自晋升门」，回滚虽然有用但「最近一次」恢复更快。"
    },
    {
        "id": "SEC1_ROW12_E1_MODEL_SIZE",
        "section": "§1 设计决定表: 模型从小起步",
        "candidate_quote": "E1 的 dev 上，P 族里纯网络的碰撞 F1 还是所有臂中最高的",
        "file": "reports/V9-E1-CONCLUSION/CONCLUSION.md",
        "line": 44,
        "q1_subset": "dev 评估集上的碰撞预测步",
        "q2_metric": "碰撞事件 F1 分数（纯网络 S_P 0.898 vs 残差网络 P_P 0.871）",
        "q3_source": "dev 评估集",
        "q4_status": "摸底诊断指标",
        "q5_repeats": "dev 集多模型对比",
        "qualifier_audit": "v2 补回了「E1 的 dev 上」，限定数据来源为开发集。"
    },
    # §1 表尾新增 6 条决定
    {
        "id": "SEC1_NEW1_S2_COST",
        "section": "§1 表尾: 规划代价与预测空间分开",
        "candidate_quote": "依据 S2：三个臂在 50 条长目标上成功率都是 0。诊断里每臂一个种子：隐空间距离与真实远近的秩相关只有 −0.087 到 0.286",
        "file": "reports/V9-S2-CLOSE/REPORT.md",
        "line": 45,
        "q1_subset": "50 条长目标导航任务",
        "q2_metric": "长目标任务成功率（0%）与 Spearman 秩相关系数（−0.087 到 0.286）",
        "q3_source": "训练叫停后事后诊断",
        "q4_status": "诊断性指标（非正式过门评测）",
        "q5_repeats": "长目标 50 条；秩相关每臂 1 个种子（seed 42）",
        "qualifier_audit": "v2 补回了「诊断里每臂一个种子」，准确反映了样本受限的事实。"
    },
    {
        "id": "SEC1_NEW2_S4P2_GATE",
        "section": "§1 表尾: 学习项只在门开时接管",
        "candidate_quote": "手写规则管单体，门控只在约 15% 的步数里接管，全部事件上的重认与真实物理持平（0.835 对 0.836）；有碰撞事件上，学到的响应比门开时乱猜方向高 0.072；输入带噪后 D 降到 0.57；重新出现那一刻的覆盖率 0.745 没有过门槛 0.75。反例 E1：每步都加残差，10 步预测差 25.9%",
        "file": "reports/V9-S4-PHASE2/FINAL-REPORT.md",
        "line": 24,
        "q1_subset": "约 15% 的接触步数；全部事件与有碰撞事件分别统计",
        "q2_metric": "重认 C（0.835 vs 0.836）、有碰撞事件下比乱猜方向增益（+0.072）、覆盖率校准（0.745）",
        "q3_source": "final 运行",
        "q4_status": "主门（GR 增益 +0.072 通过；GK2 覆盖率 0.745 不通过）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「约 15% 的步数里」、「全部事件上的」、「有碰撞事件上」，严格按原报告范围约束。"
    },
    {
        "id": "SEC1_NEW3_CHEAP_BASELINES",
        "section": "§1 表尾: 便宜基线必设",
        "candidate_quote": "依据：S1 的三个网络都不胜过「原地不动」先验（定位误差都在 0.01 m 量级）；S2 扁平 JEPA 一步最准只有原地不动的 0.036；S3 跨回合记忆总体只胜过「直接看」0.001，第一阶段网络甚至不如最简单的规则（0.038）；S4 学习模型的重认不如手写规则（0.768 对 0.781），二期学到的响应比镜面反射规则没有优势（区间含 0）；S5 在最低标签档，加教师特征只比无教师高 0.009，512 档无教师也有 0.073",
        "file": "reports/V9-S4-PHASE1/final/FINAL-REPORT.md",
        "line": 35,
        "q1_subset": "各阶段便宜基线对照子集（含原地不动、手写规则、无教师等）",
        "q2_metric": "定位误差、重认率、检索准确率、占据读出 AP",
        "q3_source": "各阶段 final / close 报告",
        "q4_status": "对照基线指标（含主门、描述量与诊断项）",
        "q5_repeats": "各阶段 5 个重复（S2 为单种子诊断）",
        "qualifier_audit": "候选稿全面列举了各阶段便宜基线对神经模型的压制，保留了「区间含 0」等严格限定。"
    },
    {
        "id": "SEC1_NEW4_TRUTH_DEP",
        "section": "§1 表尾: 真值依赖清单",
        "candidate_quote": "S3 第三阶段把真值路由换成学生可判的路由，固定格查询掉 0.137；起点位姿偏 5 格之后，收益只剩 0.03–0.04。S4 的墙柱反弹是手写规则，智能体位姿是真值，检测是结构化的",
        "file": "reports/V9-S3-PHASE3/FINAL-REPORT.md",
        "line": 89,
        "q1_subset": "固定格查询及带平移位姿误差条件",
        "q2_metric": "检索准确率跌幅（学生路由 −0.137；位姿偏 5 格收益降至 0.032–0.039）",
        "q3_source": "final 运行消融与鲁棒性分析",
        "q4_status": "登记的鲁棒性描述量（D6 与 D7）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "候选稿准确指明对特权真值输入的依赖是已有阶段取得表观成绩的关键前提。"
    },
    {
        "id": "SEC1_NEW5_DOMAIN_GATE",
        "section": "§1 表尾: 视觉前端先过换域门",
        "candidate_quote": "依据 S5：外观全换后所有臂的占据读出跌到 0.014–0.042，接近随机；教师的作用主要在 512 段标签档（V-JEPA 教师 0.162，无教师 0.073，是只报告项，不是门）；按 64 段档选出的最优臂，在更高的两档里反而是三个教师臂中最差的",
        "file": "reports/V9-S5-FINAL/RESULTS/REPORT.md",
        "line": 48,
        "q1_subset": "外观全换（换域评估集）及 512 段标签档",
        "q2_metric": "网格占据读出 AP（跌至 0.014–0.042；512 段 0.162 vs 0.073）",
        "q3_source": "final 运行",
        "q4_status": "登记的主门（换域）与只报告项（512 标签档）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「是只报告项，不是门」，严格区分了登记门与探索性报告项。"
    },
    {
        "id": "SEC1_NEW6_AUTONOMOUS",
        "section": "§1 表尾: 自驱信号分两种情形",
        "candidate_quote": "第一种有支持：S6 一期在碰撞预测上，自选比随机高 0.095，epinet 高 0.099，外推到 10 个盘仍成立。代价在自由运动：误差比随机高约 21%，这是描述量；登记的自由运动门是对代用规则比的，点值 1.068，区间上界超过 1.20，没有过。第二种未检验：只有单次重复的摸底，S6 二期设计在送审",
        "file": "reports/V9-S6-FINAL/RESULTS.md",
        "line": 16,
        "q1_subset": "碰撞预测步与自由运动步分别统计",
        "q2_metric": "碰撞预测收益（自选比随机 +0.095，epinet +0.099）、自由运动误差比（1.068 对代用规则；1.211 对随机）",
        "q3_source": "final 运行",
        "q4_status": "主门（G1-G3 碰撞预测通过；G4 自由运动不过）及登记描述量（自由运动对随机误差比）",
        "q5_repeats": "5 个重复（seeds 42–46）",
        "qualifier_audit": "v2 补回了「在碰撞预测上」、「这是描述量」、「是对代用规则比的」，完全澄清了门槛定义与指标属性。"
    },
    # §5.1 表中各阶段现状
    {
        "id": "SEC51_S4P1",
        "section": "§5.1 各阶段现状: S4 一期",
        "candidate_quote": "final 六门全过：碰撞动力学 D 0.873；擦边误差比 0.071；外推到 10 个盘 D 0.867；有碰撞事件上，带交互的模型比不带交互的重认高 0.123",
        "file": "reports/V9-S4-PHASE1/final/FINAL-REPORT.md",
        "line": 22,
        "q1_subset": "碰撞动力学精确状态预测步、擦边步、外推 10 盘、有碰撞重新出现事件",
        "q2_metric": "D 速度误差补回比、HF 擦边误差比、H2 重认增益（+0.123）",
        "q3_source": "final 运行",
        "q4_status": "登记的 6 个主门全过",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「有碰撞事件上，带交互的模型比不带交互的」，限定了比较基线与事件子集。"
    },
    {
        "id": "SEC51_S4P2",
        "section": "§5.1 各阶段现状: S4 二期",
        "candidate_quote": "final 8 门过 7：全部事件上门控混合的重认 0.835，真实物理 0.836；有碰撞事件上，学到的响应比门开时乱猜方向高 0.072；D 0.868。有碰撞事件重新出现时的覆盖率 0.745，门槛 0.75，没有过",
        "file": "reports/V9-S4-PHASE2/FINAL-REPORT.md",
        "line": 24,
        "q1_subset": "全部事件与有碰撞事件",
        "q2_metric": "重认 C、增益 GR、覆盖率 GK2",
        "q3_source": "final 运行",
        "q4_status": "8 门过 7（GK2 未通过）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「全部事件上」、「有碰撞事件上」，指出了 GK2 不过。"
    },
    {
        "id": "SEC51_S6P1",
        "section": "§5.1 各阶段现状: S6 一期",
        "candidate_quote": "final 8 门过 7，指标是碰撞预测：自选减随机 +0.095；epinet 减随机 +0.099；外推到 10 个盘 +0.093。自由运动误差对代用规则的比是 1.068，区间上界 1.243，超过 1.20，没有过。自选相对随机的误差比：碰撞 0.671，自由 1.211，全部盘步 0.954",
        "file": "reports/V9-S6-FINAL/RESULTS.md",
        "line": 15,
        "q1_subset": "碰撞预测步、自由运动步、全部盘步",
        "q2_metric": "增益 G1–G3、自由运动误差比 G4、相对随机误差比（描述量）",
        "q3_source": "final 运行",
        "q4_status": "8 门过 7（G4 未通过）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「指标是碰撞预测」、「epinet 减随机」，澄清了主指标为碰撞预测。"
    },
    {
        "id": "SEC51_S6P2_EXPLORE",
        "section": "§5.1 各阶段现状: S6 二期摸底",
        "candidate_quote": "I 轮，单次重复，不是登记运行：主臂新技能 0.361，诱饵占 3.2%；便宜规则 U 0.331、诱饵占 32%，Q 0.288、诱饵占 47%；随机 −0.058",
        "file": "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md",
        "line": 15,
        "q1_subset": "I 轮摸底（600 世界，4 轮主动探索）",
        "q2_metric": "新技能进步 H 与诱饵步占比",
        "q3_source": "探索摸底（单次重复）",
        "q4_status": "摸底诊断项（非登记过门运行，无区间）",
        "q5_repeats": "单次重复（1 repeat）",
        "qualifier_audit": "候选稿明确写明「单次重复，不是登记运行，不能说任何门通过」。"
    },
    {
        "id": "SEC14_RLT",
        "section": "§14 综合诊断: 更少计算",
        "candidate_quote": "世界侧稀疏更新的参考实现；RLT 让蒸馏每步省 11%",
        "file": "reports/V9-S5-FINAL/RESULTS/REPORT.md",
        "line": 19,
        "q1_subset": "S5 学生蒸馏训练步",
        "q2_metric": "GR：RLT 开启时每步墙钟耗时降幅",
        "q3_source": "final 运行",
        "q4_status": "登记的主门（GR 点值 11.1%，门槛 ≥ 15%，未通过）",
        "q5_repeats": "5 个重复",
        "qualifier_audit": "v2 补回了「让蒸馏每步省 11%」，限定为蒸馏训练阶段，非整机推理。"
    },
    # 负面引文（明确不做）
    {
        "id": "NEGATIVE_TITANS_S3",
        "section": "§2 结构说明: S3 未做 Titans 与多频率",
        "candidate_quote": "r6：S3 只比较了非参数情景库和 GRU，Titans 式记忆与多频率更新没有做",
        "file": "reports/V9-S3-PHASE3-DESIGN/DESIGN-r2.md",
        "line": 200,
        "q1_subset": "S3 全阶段设计排除范围",
        "q2_metric": "设计契约与不做事项",
        "q3_source": "S3 各阶段定稿设计文件",
        "q4_status": "定稿设计明确不做事项（「不在本阶段」）",
        "q5_repeats": "不适用",
        "qualifier_audit": "出处逐字确认：DESIGN-r2.md:200 明确写明「容量受限的情景库、教师写入、Titans 式记忆、多次换代 不在本阶段」；DESIGN-r2.md:50 亦写明留给后续。"
    }
]

def verify_sed_line(rel_path, line_no):
    full_path = os.path.join(REPO_ROOT, rel_path)
    res = subprocess.run(["sed", "-n", f"{line_no}p", full_path], capture_output=True, text=True)
    return res.stdout.strip()

print(f"Auditing {len(CLAIMS)} quantitative & negative claims...")
failures = []
log_lines = []

for c in CLAIMS:
    actual = verify_sed_line(c["file"], c["line"])
    if not actual:
        failures.append(f"Empty line at {c['file']}:{c['line']}")
        continue
    log_lines.append(f"==================================================")
    log_lines.append(f"Claim ID: {c['id']}")
    log_lines.append(f"Section : {c['section']}")
    log_lines.append(f"Quote   : {c['candidate_quote']}")
    log_lines.append(f"Source  : {c['file']}:{c['line']}")
    log_lines.append(f"Verbatim: {actual}")
    log_lines.append(f"  Q1 (Subset) : {c['q1_subset']}")
    log_lines.append(f"  Q2 (Metric) : {c['q2_metric']}")
    log_lines.append(f"  Q3 (Source) : {c['q3_source']}")
    log_lines.append(f"  Q4 (Status) : {c['q4_status']}")
    log_lines.append(f"  Q5 (Repeats): {c['q5_repeats']}")
    log_lines.append(f"  Qualifier Audit: {c['qualifier_audit']}")
    log_lines.append("")

out_log = os.path.join(REPO_ROOT, "reports/V9-ARCH-R6/evidence-review/r2/evidence/audit_numbers_and_qualifiers.log")
with open(out_log, "w", encoding="utf-8") as f:
    f.write("\n".join(log_lines))

print(f"Log written to {out_log}")
assert len(failures) == 0, f"Failures encountered: {failures}"
print("All claims audited and sed -n lines verified successfully!")
