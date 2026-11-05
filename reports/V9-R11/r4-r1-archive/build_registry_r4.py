#!/usr/bin/env python3
"""V9-R11 注册表 r4 构建器（只读网页核实后的落盘脚本，不联网）。

作用：
1. 读 r3 的 adapter_registry.json / ADAPTER_REGISTRY.md（r3 原字节已在 reports/V9-R11/r3-archive/ 归档）；
2. 追加 CMFL 调研（reports/frontier-integration-20261027/REPORT.md §1.2/§1.3）已核条目 45 条；
3. 给 lewm / equivariant-trust-horizons 追加更正说明（不改原字段结论）；
4. 重算 r4_summary、revision、access_date；
5. 同步重写 MD 的 §1 总表与 §4 机制汇总（老条目行原样保留，新条目按 id 归并排序），并追加 §5.4/§5.5/§7/§8。

本脚本不下载任何代码、权重或数据集；所有事实来自 2026-10-28 的只读网页访问。
用法：python3 reports/V9-R11/build_registry_r4.py [--root <项目根>]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ACCESS_DATE = "2026-10-28"

TIER_LABEL = {
    "protocol": "直接借协议",
    "self-implement": "算法自实现",
    "install-pending": "需用户批准安装",
    "s2s5": "S2/S5 阶段再看",
    "observe": "只观察",
    "excluded": "排除",
}


def E(**kw):
    return kw


# ---------------------------------------------------------------------------
# 45 条新条目。每条都在 2026-10-28 打开过一手来源（arXiv abs 页 / 期刊或 Crossref 记录 /
# GitHub 仓库页或 raw LICENSE）。报告里本轮未能复核的说法一律标「未复核」。
# ---------------------------------------------------------------------------
NEW_ENTRIES = [
    E(
        id="active-inference-value-profiles",
        name="Active inference with reusable state-dependent value profiles",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="Active inference with reusable state-dependent value profiles",
            authors=["Jacob Poschl"],
            date="2026-10-09",
            version="Biological Cybernetics 120(5-6), article 40；DOI 10.1007/s00422-026-01066-0",
            url="https://link.springer.com/article/10.1007/s00422-026-01066-0",
        ),
        repo=dict(url="无法核（Crossref 记录与期刊条目均未给出代码仓库；本轮只读未检索到）"),
        license=dict(
            license="论文：CC BY 4.0（Crossref 记录 license URL creativecommons.org/licenses/by/4.0）；代码许可：无法核（无公开代码仓库）",
            source="https://api.crossref.org/works/10.1007/s00422-026-01066-0（2026-10-28 只读）",
        ),
        mech=[
            "状态相关的可复用价值档案（state-dependent value profiles）：把价值函数按状态复用，减少每个环境重新学习价值的成本",
            "模型恢复/参数恢复作为评测协议：用已知生成模型拟合回来，报告恢复矩阵与不可分情形",
            "给 MSG 的『机制是否够用』提供一类可复用先验的组织方式（属设计参考，不属可直接运行的算法）",
        ],
        mlx=dict(
            rating="高（纯 CPU 可自写的统计流程；无官方代码，须自行实现）",
            deps=["无公开代码（依赖无法核）", "实现只需 NumPy/SciPy 级别的数值计算"],
            notes="单作者期刊论文，无代码；只能借协议与评测口径，不能借实现。",
        ),
        non=[
            "模型恢复不对称：报告核对指出 M1 与 M2 不可分，不能把『恢复成功』当作机制唯一",
            "单作者、无代码，复现风险高（未复核）",
            "价值档案的可复用性结论建立在作者自己的任务族上，不外推到 AWZ",
        ],
        ver=dict(
            opened=["https://api.crossref.org/works/10.1007/s00422-026-01066-0"],
            unverified=["模型恢复不对称的具体数字（取自 REPORT.md §1.2，本轮未复核正文）"],
        ),
    ),
    E(
        id="ai-newton",
        name="AI-Newton（概念驱动的物理定律发现系统）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="AI-Newton: A Concept-Driven Physical Law Discovery System without Prior Physical Knowledge",
            authors=["You-Le Fang", "Dong-Shan Jian", "Xiang Li", "Yan-Qing Ma"],
            date="2025-04-02",
            version="v2（2025-12-11）；6 页 3 图",
            url="https://arxiv.org/abs/2504.01538",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2504.01538（2026-10-28 只读）",
        ),
        mech=[
            "先从多实验原始数据提出可解释的物理概念，再用概念构造定律（而不是直接搜表达式）",
            "把已发现的定律逐步推广到更大定义域（渐进泛化）",
        ],
        mlx=dict(
            rating="低（报告称依赖商用 Maple 与 CUDA，本轮未复核实现依赖）",
            deps=["报告称需商用 Maple 与 CUDA（未复核）"],
            notes="与本机 M2 Max CPU-only 路线不匹配；仅作方法论观察。",
        ),
        non=[
            "依赖商用 Maple 与 CUDA、平均约 48 小时（未复核，取自 REPORT.md §1.2）",
            "重发现牛顿第二定律/能量守恒/万有引力属教科书级目标，不代表能发现 AWZ 的未知机制",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2504.01538"],
            unverified=["实现依赖（Maple/CUDA）与平均 48 小时"],
        ),
    ),
    E(
        id="alder",
        name="ALDER（Action-guided Law Discovery, Evaluation, and Revision）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.3",
        paper=dict(
            title="ALDER: Discovering the Laws of a World by Acting in It",
            authors=["Teng Cao", "Yu Deng", "Quentin Delfosse", "Kristian Kersting"],
            date="2026-09-27",
            version="v1（2026-09-27，唯一版本）",
            url="https://arxiv.org/abs/2609.33728",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2609.33728（2026-10-28 只读）",
        ),
        mech=[
            "参数方程提议 + 数值优化拟合系数 + 独立验证器在留出数据上检验，三段分离",
            "成本与安全感知的选择器主动查询干预，用反例更新证据账本并驱动下一次结构修订",
            "准入由提议方看不到的留出数据决定，阈值在发现前冻结，预算内无人通过就不返回任何模型",
            "负对照：候选库故意缺项或缺状态时，准入率应为 0（不为 0 说明晋升门在放行错误机制）",
        ],
        mlx=dict(
            rating="高（协议层，零下载；拟合与检验都是 CPU 数值计算）",
            deps=["无官方代码（协议需自实现）"],
            notes="本条目是 CMFL 单侧晋升门与 MSG STRUCTURAL 分支的主要协议来源之一。",
        ),
        non=[
            "判别实验打分含新颖性奖励与成本项，不只看候选间预测分歧（报告核对结论）",
            "仓库无代码许可（未发布），只能借协议不能借实现",
            "in-house benchmark 与 ODE 任务的结论不外推到 AWZ 接触/摩擦场景",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2609.33728"],
            unverified=["『新颖性奖励与成本项』的细节（取自 REPORT.md §1.3，本轮未读正文）"],
        ),
    ),
    E(
        id="code-as-world",
        name="Code-as-World（可执行世界表示）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Code as Worlds: Agentic Discovery of Executable World Representations for Physical Reasoning",
            authors=["Hanyang Wang", "Yimo Cai", "Weiliang Chen", "Jiawei Chi", "等（共 17 人）"],
            date="2026-08-27",
            version="v2（2026-10-26）",
            url="https://arxiv.org/abs/2608.27549",
        ),
        repo=dict(url="无法核（arXiv 只给项目页 https://mirros-lab.github.io/code-as-world ，未给代码仓库）"),
        license=dict(
            license="论文：CC BY-NC-SA（REPORT.md 核对结论，本轮未复核）；代码许可：无法核（核心发现循环与训练代码未发布）",
            source="https://arxiv.org/abs/2608.27549（2026-10-28 只读）",
        ),
        mech=[
            "把物理构成、动力学演化与外观都写成可执行代码，作为紧凑、可量化、可控的世界抽象",
            "提议—执行—渲染—验证—迭代的溯因式发现环",
            "用已验证的可执行世界给 VLM 生成定量物理推理的监督数据",
        ],
        mlx=dict(
            rating="低（核心循环与训练代码未发布；渲染链路依赖外部引擎）",
            deps=["无法核（代码未发布）"],
            notes="与本项目『确定性核心 + 残差』思路同源，但实现未开放，只能观察。",
        ),
        non=[
            "核心发现循环与训练代码未发布（报告核对结论，本轮 abs 页亦无代码链接）",
            "论文为 CC BY-NC-SA，正文与图不可商用转载",
            "QuantiPhy 上的 SOTA 不代表 AWZ 物理一致性",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2608.27549"],
            unverified=["论文许可 CC BY-NC-SA（取自 REPORT.md §1.2）"],
        ),
    ),
    E(
        id="cosr",
        name="CoSR（Chain of Symbolic Regression）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Data-driven Progressive Discovery of Physical Laws",
            authors=["Mingkun Xia", "Weiwei Zhang"],
            date="2026-03-14",
            version="v1（2026-03-14）；v2（2026-05-29）已 withdrawn",
            url="https://arxiv.org/abs/2603.13727",
        ),
        repo=dict(url="无法核（无代码仓库；报告核对称仓库无 LICENSE）"),
        license=dict(
            license="论文：arXiv abs 页显示已被作者撤回（withdrawn），许可未显示（无法核）；代码许可：无法核",
            source="https://arxiv.org/abs/2603.13727（2026-10-28 只读，页面明示 This paper has been withdrawn）",
        ),
        mech=[
            "把定律发现建模成『符号知识链』：多个有物理意义的知识单元沿逻辑逐步组合",
            "渐进式发现路径（从开普勒第三定律到万有引力）作为评测叙事",
        ],
        mlx=dict(
            rating="低（论文已撤回，实现不可采信）",
            deps=["无法核（无代码）"],
            notes="仅作为『渐进式发现』这一叙事的历史参照，不作方法依据。",
        ),
        non=[
            "arXiv v2 已撤回：comments 原文为『This paper needs to be retracted due to methodological flaws found in RBC case』",
            "撤回前结论不得引用为证据；仓库无 LICENSE，不能复制代码",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2603.13727"],
            unverified=[],
        ),
    ),
    E(
        id="dwc",
        name="DWC（Differentiable Weightless Controllers）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Differentiable Weightless Controllers: Learning Logic Circuits for Continuous Control",
            authors=["Fabian Kresse", "Christoph H. Lampert"],
            date="2025-12-01",
            version="v2（2026-06-08）；ICML 第 43 届",
            url="https://arxiv.org/abs/2512.01467",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2512.01467（2026-10-28 只读）",
        ),
        mech=[
            "可微符号架构：梯度端到端训练，但编译成 FPGA 兼容电路",
            "结构稀疏可读的连线模式，可直接检查哪些输入影响控制决策",
        ],
        mlx=dict(
            rating="低（训练依赖 CUDA；产物是 FPGA 电路，与本机 CPU/MLX 路线无交集）",
            deps=["报告称训练依赖 CUDA（未复核）"],
            notes="只作为『低功耗控制』的远期观察项。",
        ),
        non=[
            "主配置约 2 nJ 每动作，且是 Vivado 估计值，不是实测（未复核）",
            "训练依赖 CUDA；FPGA 编译产物与本机无关",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2512.01467"], unverified=["2 nJ/Vivado 估计与 CUDA 依赖"]),
    ),
    E(
        id="deepjepa",
        name="DeepJEPA（把转移深度当作测试时缩放轴）",
        status="verified-paper-only",
        tier="s2s5",
        src="REPORT.md §1.2",
        paper=dict(
            title="DeepJEPA: Scaling World Models from Within",
            authors=["Zijian Jin", "Yunbei Zhang", "Yuanzhe Liu", "Ming Liu", "等（共 8 人）"],
            date="2026-09-30",
            version="v1（2026-09-30）",
            url="https://arxiv.org/abs/2610.00368",
        ),
        repo=dict(url="无法核（arXiv comments 只给项目页 https://deepjepa.github.io/ ，未给代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.00368（2026-10-28 只读）",
        ),
        mech=[
            "权重共享的 JEPA 世界模型，把每个转移的递归深度当成内部测试时缩放轴",
            "学习『这次转移值不值得再算一次』的判据，额外计算集中在接触起始与持续交互处",
        ],
        mlx=dict(
            rating="中（架构思路可在 MLX 复现，但无代码）",
            deps=["无法核（无代码）"],
            notes="S2/S5 阶段的算力分配诊断项，不作为近期实现目标。",
        ),
        non=[
            "规划增益在种子标准差以内（报告核对结论，本轮未复核）",
            "命题 3.1 只能事后判断，不能当作跳过规则",
            "『接触起始处加深』是作者环境的观察，AWZ 需自行验证",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.00368"], unverified=["增益在种子标准差以内"]),
    ),
    E(
        id="empiric",
        name="EMPIRIC（在物理引擎上补残差机制）",
        status="verified",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="EMPIRIC: Experiment-Driven Learning of Residual World Models for Robot Planning",
            authors=["Yichao Liang", "Amber Li", "Dat Nguyen", "Emily Bunnapradist", "等（共 16 人）"],
            date="2026-09-28",
            version="v1（2026-09-28，唯一版本）；cs.RO",
            url="https://arxiv.org/abs/2609.35047",
        ),
        repo=dict(url="https://github.com/BasisResearch/predicators"),
        license=dict(
            license="代码：MIT（BasisResearch/predicators 的 LICENSE.md 原文核实，Copyright 2022 Rohan Chitnis and Tom Silver，fork 自 Learning-and-Intelligent-Systems/predicators）；网站源码仓库 BasisResearch/empiric 无 LICENSE；论文许可：abs 页未显示（无法核）",
            source="https://raw.githubusercontent.com/BasisResearch/predicators/master/LICENSE.md（2026-10-28 只读）",
        ),
        mech=[
            "残差世界模型＝基座物理引擎 + 缺失机制的代码（新力、新约束、隐藏状态 x_res）",
            "x_res 只从可观测特征按动作更新，不读特权状态（对应 r5 §8.6 学习侧信息边界）",
            "参数由回放损失的广义后验估计，温度 λ=max(1, E_min/N)；RMS 标准化误差 > 2 的段剔除并上报",
            "变点检测（BOCPD）识别规律切换；K 个联合抽样上 rehearsal 规划，按谓词互信息（BALD 式）选实验",
        ],
        mlx=dict(
            rating="中（协议层可自实现；原实现是 PyTorch + PyBullet，不在本机跑）",
            deps=["PyTorch", "PyBullet（原实现）；本项目只借协议，不安装"],
            notes="CMFL 的 MID 残差分支主参照。代码许可 MIT，但本卡不下载、不 clone。",
        ),
        non=[
            "全部代理用 Claude Opus 5（闭源绑定），换模型是否成立未知",
            "基线有三个（16/14/16）不是两个，且是按思路重实现的版本，不是原系统",
            "同一组抽样上反复修改过的候选，成功概率估计偏乐观——独立测试集不可省",
            "sim 五个域与单台真机的结果不外推到 AWZ 接触/摩擦场景",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2609.35047", "https://raw.githubusercontent.com/BasisResearch/predicators/master/LICENSE.md"],
            unverified=["论文许可（abs 页未显示）"],
        ),
    ),
    E(
        id="evidence-gated-research",
        name="Evidence-Gated Research（EGR，统计受控的模型采纳层）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.3",
        paper=dict(
            title="Evidence-Gated Research: Statistically Controlled Model Adoption in Adaptive Search",
            authors=["Yifan Guo"],
            date="2026-10-01",
            version="v1（2026-10-01）；预印本 17 页",
            url="https://arxiv.org/abs/2610.01751",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.01751（2026-10-28 只读）",
        ),
        mech=[
            "挑战者在看到决策证据前冻结（对应 test_id 必须预先登记）",
            "在预先声明的多个世界族上各建随时有效的 e-process，用交并检验合成 E_pers = min_e E^e",
            "在线 FDR 控制器（e-LOND：α_t = αγ_t(R_{t−1}+1)）管住整条晋升序列的错误接受率",
            "报告必须写明路径依赖：一次晋升会改变之后候选的生成起点",
        ],
        mlx=dict(
            rating="高（协议层，零下载；e-value 累乘是纯数值计算）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL 单侧晋升门 §3 第 3 条（多重比较与在线 FDR）的主来源。",
        ),
        non=[
            "结论依赖『条件有效性 + 可预测性』两个显式条件，不满足时 FDR 不受控",
            "证据积累慢的世界族会让交并检验偏保守，样本效率下降",
            "单作者预印本，未经同行评审（本轮只读 abs 页）",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.01751"], unverified=[]),
    ),
    E(
        id="fact",
        name="FACT（Failure-Aware Causal Training for World-Action Models）",
        status="verified",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="FACT: Failure-Aware Causal Training for World-Action Models",
            authors=["Quanquan Peng", "Yutong Liang", "Rui Yan", "Nicklas Hansen", "Xiaolong Wang"],
            date="2026-08-10",
            version="v2（2026-10-13）；CoRL 2026（仓库 README 与 citation 标注）",
            url="https://arxiv.org/abs/2608.10232",
        ),
        repo=dict(url="https://github.com/Bariona/FACT"),
        license=dict(
            license="代码：Apache-2.0（仓库 README 的 License 节明写 Apache 2.0 并指向 LICENSE）；论文许可：本轮未核",
            source="https://github.com/Bariona/FACT（2026-10-28 只读）",
        ),
        mech=[
            "失败轨迹不进动作模仿损失，但仍监督『失败后的观测』与更低的进度值（损失掩码）",
            "动作条件化的世界-动作模型：未来视频与进度值都以已执行动作为条件，方向单向",
            "推理时用进度值给候选动作排序（可选 best-of-N）",
            "报告时把 10 步位置误差与碰撞 F1 拆到失败子集上单列（CMFL 报告要求直接借用）",
        ],
        mlx=dict(
            rating="低（底座为 5B 视频扩散模型 Wan2.2-TI2V-5B，需 GPU）",
            deps=["PyTorch", "Wan2.2-TI2V-5B 权重", "RoboTwin（原实现）"],
            notes="只借『损失掩码 + 失败子集单列』的报告与训练协议，不安装、不下载权重。",
        ),
        non=[
            "标题里的 Causal 指注意力/条件方向，不是因果推断",
            "底座是 5B 视频扩散模型，与本机 CPU-only 路线不兼容",
            "bimanual 操作任务的成功率不外推到 AWZ 小房间",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2608.10232", "https://github.com/Bariona/FACT"], unverified=["论文许可"]),
    ),
    E(
        id="fcp-mpc",
        name="FCP-MPC（函数型共形距离场 + 采样 MPC）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="From Prediction Uncertainty to Conformalized Distance Fields for Safe Motion Planning",
            authors=["Jaeuk Shin", "Yoonseok Ra", "Insoon Yang"],
            date="2026-07-01",
            version="v1（2026-07-01）",
            url="https://arxiv.org/abs/2607.00776",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2607.00776（2026-10-28 只读）",
        ),
        mech=[
            "对整个预测距离场做函数型共形（FCP），得到场级下界，而不是把每障碍误差聚成一个标量分数",
            "残差距离场经验低秩且近似时不变 → 在系数空间分解：FPCA + 高斯混合归纳共形",
            "在线用低维向量的自适应函数型共形（AFCP）更新，保持分布偏移下的长期场覆盖",
            "把包络作为收紧的安全约束嵌入采样 MPC（FCP-MPC）",
        ],
        mlx=dict(
            rating="高（FPCA + 分位数计算是纯数值，CPU 可自实现）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL 的 D_valid 与共形包络直接借这一条，不借其 MPC 实现。",
        ),
        non=[
            "它是函数型共形安全规划，不是『适用域加弃权』；弃权分支要另立",
            "分布偏移下只有渐近长期平均覆盖，必须报告实测覆盖率，不能只引定理",
            "可交换性自检（时间切半比较残差统计）要自己做；越界检测靠包络不靠共形",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2607.00776"], unverified=[]),
    ),
    E(
        id="geo-conformal-abstention",
        name="Geometry-Calibrated Conformal Abstention（LLM 问答弃权）",
        status="verified-paper-only",
        tier="excluded",
        src="REPORT.md §1.2",
        paper=dict(
            title="Geometry-Calibrated Conformal Abstention for Language Models",
            authors=["Rui Xu", "Yi Chen", "Sihong Xie", "Hui Xiong"],
            date="2026-04-30",
            version="v1（2026-04-30）",
            url="https://arxiv.org/abs/2604.27914",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2604.27914（2026-10-28 只读）",
        ),
        mech=[
            "用表示几何做后验校准，决定是否弃权（post hoc，不改模型）",
            "以预测置信度而非不可交换性分数作弃权判据（开放式生成下不可交换性分数不可算）",
        ],
        mlx=dict(
            rating="低（对象是 LLM 问答，与本项目世界模型无关）",
            deps=["无法核（无代码）"],
            notes="**排除**：不作为本项目任何保证的依据。",
        ),
        non=[
            "对象是 LLM 问答弃权，不是世界模型适用域",
            "报告核对指出其第二个『保证』实际是点估计：**不作为依据**",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2604.27914"], unverified=["第二个『保证』为点估计的判断（取自 REPORT.md §1.2）"]),
    ),
    E(
        id="in-place-ttt",
        name="In-Place Test-Time Training",
        status="verified",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="In-Place Test-Time Training",
            authors=["Guhao Feng", "Shengjie Luo", "Kai Hua", "Ge Zhang", "等（共 7 人）"],
            date="2026-04-07",
            version="v1（2026-04-07）；ICLR 2026 Oral",
            url="https://arxiv.org/abs/2604.06169",
        ),
        repo=dict(url="https://github.com/ByteDance-Seed/In-Place-TTT"),
        license=dict(
            license="Apache-2.0（仓库根目录 LICENSE 原文核实，Apache License Version 2.0）",
            source="https://raw.githubusercontent.com/ByteDance-Seed/In-Place-TTT/main/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "把 MLP 最后一层投影矩阵当作可更新的快权重，测试时原地更新",
            "用与下一 token 预测对齐的目标替换 TTT 的重构目标；分块更新兼容上下文并行",
        ],
        mlx=dict(
            rating="低（LLM 方法，与本项目只有概念联系）",
            deps=["PyTorch（原实现）；本项目不安装"],
            notes="只作『快权重』概念参照，不进任何实现路线。",
        ),
        non=[
            "LLM 方法：与本项目的显式几何核心 + 残差路线只有概念联系",
            "128k 上下文与 4B 模型的结论不外推到 AWZ",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2604.06169", "https://raw.githubusercontent.com/ByteDance-Seed/In-Place-TTT/main/LICENSE"], unverified=[]),
    ),
    E(
        id="jepa-anything",
        name="JEPA-Anything（正交预测因子分解 OPF）",
        status="verified",
        tier="s2s5",
        src="REPORT.md §1.2",
        paper=dict(
            title="JEPA-Anything: Learning Predictive Models across Different Worlds",
            authors=["Taoyong Cui", "Zhongyao Wang", "Xinyue Xu", "Weiyang Liu", "等（共 13 人）"],
            date="2026-09-17",
            version="v1（2026-09-17）",
            url="https://arxiv.org/abs/2609.20800",
        ),
        repo=dict(url="https://github.com/Gen-Verse/JEPA-Anything"),
        license=dict(
            license="Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright 2026 JEPA Anything contributors）",
            source="https://raw.githubusercontent.com/Gen-Verse/JEPA-Anything/main/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "正交预测因子分解（OPF）：把潜目标拆成互补因子，各自专用通路，再在共享预测设计中重组",
            "跨视觉/生物/临床/控制/分子动力学/物理场/天气七个域共用一个学习原则",
        ],
        mlx=dict(
            rating="中（核心库是 PyTorch；概念可在 MLX 复现，但本项目不安装）",
            deps=["PyTorch（jepa-anything-core）；本项目不安装"],
            notes="仓库只含核心库、脚手架与校验器，不含数据集与权重，也不含领域训练代码。",
        ),
        non=[
            "领域训练代码没有发布：仓库只有 jepa-anything-core/skill/recipes，checkpoint 清单仅一个未训练示例、无任何性能声明",
            "OPF 要求因子子空间正交，不能拿来按物理机制拆残差",
            "七个域的指标改善不外推到 AWZ 观察",
        ],
        ver=dict(
            opened=["https://arxiv.org/abs/2609.20800", "https://github.com/Gen-Verse/JEPA-Anything", "https://raw.githubusercontent.com/Gen-Verse/JEPA-Anything/main/LICENSE"],
            unverified=[],
        ),
    ),
    E(
        id="lean-verified-qec",
        name="Lean 验证的 QEC 发现（Co-Designing Quantum Codes…）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="Co-Designing Quantum Codes with Transversal Diagonal Gates via Multi-Agent Systems",
            authors=["Xi He", "Sirui Lu", "Bei Zeng"],
            date="2025-10-23",
            version="v3（2026-04-06）；33 页 4 图",
            url="https://arxiv.org/abs/2510.20728",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2510.20728（2026-10-28 只读）",
        ),
        mech=[
            "候选构造必须转成精确对象并被独立检查：搜索、精确重构、形式证明三段分离",
            "以 Lean 4 编译作为二值硬门（『零错误、零警告、无 sorry』式），而不是让验证代理自己宣称",
            "被排除的候选要给出 no-go 证明，与接受项一起形式化",
        ],
        mlx=dict(
            rating="高（协议层；硬门思想与语言无关，Lean 本身不在本机跑）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL §3 第 7 条『二值硬门由隔离验证器给出』的直接参照。条目名沿用报告简称；arXiv 一手标题不含 Lean-verified。",
        ),
        non=[
            "一手标题是 Co-Designing Quantum Codes…，不含『Lean-verified』；报告中的名字是描述性简称（本轮已核：正文确有独立 Lean 4 验证层）",
            "流程是人工引导的，不是全自动发现",
            "真正的硬门是 Lean 编译器，不是任何评审模型；本项目对应的是独立仿真测试",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2510.20728"], unverified=[]),
    ),
    E(
        id="llm-idea",
        name="LLM-IDEA（可辨识性驱动的实验代理）",
        status="verified",
        tier="install-pending",
        src="REPORT.md §1.2",
        paper=dict(
            title="LLM-IDEA: Identifiability-Driven Experimental Agent for Autonomous Discovery of Mechanistic World Models",
            authors=["Surya Shetty", "Ulisses Braga-Neto"],
            date="2026-10-08",
            version="v1（2026-10-08）",
            url="https://arxiv.org/abs/2610.11253",
        ),
        repo=dict(url="https://github.com/Suraskey/llm-idea"),
        license=dict(
            license="Apache-2.0（仓库 README 明写 Licensed under Apache-2.0 并指向 LICENSE）",
            source="https://github.com/Suraskey/llm-idea（2026-10-28 只读）",
        ),
        mech=[
            "可辨识性引擎给出三态裁决：能力上限 / 设计类内可解 / 已证耗尽（certified exhausted）",
            "用灵敏度矩阵诊断 + 精确符号结构检查 + 设计排序器 + 耗尽证书（符号与数值两路）",
            "引擎内部不导入任何模型客户端（有测试强制），因此可以离线跑",
            "Alien Universe 双体测试台：力律在可证不可辨识与可辨识两种协议间切换",
        ],
        mlx=dict(
            rating="高（引擎只需 numpy/scipy/sympy；CPU 可跑）",
            deps=["numpy", "scipy", "sympy", "pysindy（仅基准包的 SINDy 基线需要）"],
            notes="属『需用户批准安装后再用』：安装前须用户逐项批准；本卡未安装、未 clone。",
        ),
        non=[
            "提议者（Agentic Council 及其知识图谱/编排器）未发布，只有引擎、测试台与运行记录",
            "2026-10-08 新出，未经同行评审",
            "引擎依赖 pysindy 作基线，安装会引入额外依赖",
            "ODEBench 与 DiscoverPhysics 的裁决结论不外推到 AWZ 的接触/摩擦机制",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.11253", "https://github.com/Suraskey/llm-idea"], unverified=[]),
    ),
    E(
        id="mad-physics",
        name="MaD Physics（受限信息获取评测）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="MaD Physics: Evaluating information seeking under constraints in physical environments",
            authors=["Moksh Jain", "Mehdi Bennani", "Johannes Bausch", "Yuri Chervonyi", "等（共 7 人）"],
            date="2026-05-11",
            version="v1（2026-05-11）；64 页 10 图",
            url="https://arxiv.org/abs/2605.10820",
        ),
        repo=dict(url="无法核（arXiv comments 只给项目页 https://mad-physics.github.io/ ，未给代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2605.10820（2026-10-28 只读）",
        ),
        mech=[
            "在测量质量与数量受限下评测『做信息量最大的测量再下结论』",
            "包含被改动的物理定律（altered physical laws）以降低记忆污染",
            "三个环境各基于一条不同物理定律；预算耗尽后必须推断定律并预测未来状态",
        ],
        mlx=dict(
            rating="高（评测设计可自实现；代码未发布）",
            deps=["无官方代码（设计需自实现）"],
            notes="CMFL 的『改动定律的世界』直接借这一条的设计，不借实现。",
        ),
        non=[
            "是被动测量选择，不是主动干预设计",
            "只评测 LLM 代理（Gemini 2.5/3 系列），不是 BOED 算法评测",
            "代码未发布",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2605.10820"], unverified=[]),
    ),
    E(
        id="mda",
        name="MDA（Model Discovery Agent）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="Model Discovery Agent: LLM-assisted Bayesian experiment design for data-efficient discovery of mechanistic world models",
            authors=["Kevin Murphy"],
            date="2026-08-10",
            version="v1（2026-08-10）→ v5（2026-09-27，大改：加 GlucoseBench、加 BIC 对照、弱化 SCMC3 叙事）",
            url="https://arxiv.org/abs/2608.09696",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库；报告核对称代理本身未发布）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2608.09696（2026-10-28 只读）",
        ),
        mech=[
            "M-open 模型发现：LLM 提出结构扩展（含初始化），不限于预定义候选集",
            "基于信息价值（VoI）的实验设计",
            "对模型结构、参数与随机潜轨迹做近似贝叶斯推断",
            "ChemBench 主实验用多起点最小二乘 + BIC 做边际似然比较",
        ],
        mlx=dict(
            rating="中（协议层可借；实现未发布）",
            deps=["无法核（代理未发布）"],
            notes="CMFL 的 M-open 扩展与『残差持续失配才扩假设池』的直接来源。",
        ),
        non=[
            "LLM 用于假设扩展，包括初始化——不是只在后期补丁",
            "93%/31% 出自 v1/v4，v5 已删除该表述；引用数字必须写明版本",
            "SMC 配置反而不如 BIC，不能把 SMC 当默认选择",
            "代理本身未发布，无法复现",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2608.09696"], unverified=[]),
    ),
    E(
        id="mechbench",
        name="MechBench（机制发现基准）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="MechBench: Can AI Scientific Agents Discover Mechanisms Beyond Phenomenal Laws?",
            authors=["Zihan Yu", "Jiadong Zhang", "Jialin Cheng", "Jingtao Ding", "Yong Li"],
            date="2026-09-28",
            version="v1（2026-09-28）",
            url="https://arxiv.org/abs/2609.35515",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2609.35515（2026-10-28 只读）",
        ),
        mech=[
            "把『恢复现象律』与『发现机制』显式分开评测，每个任务由一个机制模型定义",
            "机制探针（mechanism probes）：查询无法从现象律推出的内部科学后果",
            "对规范机制做可控、科学可解释的变异，构造不熟悉变体以降低记忆污染",
            "机制不可辨识筛查：排除存在相当竞争机制的歧义实例",
        ],
        mlx=dict(
            rating="高（基准设计可自实现；代码未发布）",
            deps=["无官方代码（设计需自实现）"],
            notes="CMFL 的 UNIDENTIFIABLE 分支（先筛查、再探针）直接借这一条的顺序。",
        ),
        non=[
            "不可辨识筛查是启发式的，不是可证证书",
            "没有评测 SRHarness（报告核对已澄清）",
            "35.00%/13.75% 是 Codex + GPT-5.6-sol 的成绩，换代理须重测",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2609.35515"], unverified=[]),
    ),
    E(
        id="mechanistic-world-models",
        name="Mechanistic World Models（立场论文）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="From Observation to Insight: Mechanistic World Models and the Quest for Autonomous Discovery",
            authors=["Ingmar Posner", "Anson Lei", "Bernhard Schölkopf"],
            date="2026-07-14",
            version="v2（2026-07-15）",
            url="https://arxiv.org/abs/2607.12474",
        ),
        repo=dict(url="无法核（立场论文，arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无代码）",
            source="https://arxiv.org/abs/2607.12474（2026-10-28 只读）",
        ),
        mech=[
            "把可复用机制放在表示、计算与学习的中心，而不是以预测映射为中心",
            "从科学哲学推导『发现』所需的计算能力，给出机制中心世界模型的解剖结构",
            "把机制可解释性、因果表示学习、方程发现、模块化架构视为互补成分",
        ],
        mlx=dict(
            rating="高（纯概念，无实现）",
            deps=["无代码"],
            notes="只作为立项与术语的参照，不提供任何可运行组件。",
        ),
        non=[
            "立场论文：没有实验、没有代码",
            "『可辨识性作为组织原则』是作者的主张，报告核对认为属夸大",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2607.12474"], unverified=[]),
    ),
    E(
        id="mlx-sim",
        name="mlx-sim（Apple-Silicon-first 机器人仿真平台）",
        status="verified",
        tier="excluded",
        src="REPORT.md §1.2",
        paper=dict(
            title="mlx-sim（软件项目，无同行评审论文）",
            authors=["novix-science（组织；个人作者信息无法核）"],
            date="无法核（无对应论文）",
            version="仓库 https://github.com/novix-science/mlx-sim（2026-10-28 只读）",
            url="https://github.com/novix-science/mlx-sim",
        ),
        repo=dict(url="https://github.com/novix-science/mlx-sim"),
        license=dict(
            license="无法核（仓库根目录没有 LICENSE 文件；README 与 pyproject 自称 MIT，但没有许可正文可核）",
            source="https://github.com/novix-science/mlx-sim（2026-10-28 只读）",
        ),
        mech=[
            "面向 Apple Silicon 的物理仿真器，宣称 Metal GPU 加速与强化学习工作流",
        ],
        mlx=dict(
            rating="低（无许可正文；是否 MLX 原生未证实）",
            deps=["无法核（无 LICENSE 正文）"],
            notes="**排除**：不作为依赖引入。",
        ),
        non=[
            "根目录无 LICENSE 文件，README 徽章/自述不能当许可依据",
            "README 的 clone 地址 github.com/mlx-sim/mlx-sim 与实际仓库不一致（文档笔误）",
            "强调 Metal 加速不等于 MLX 原生；本轮只读页面无法确认 CI 状态（仓库存在 .github/workflows）",
        ],
        ver=dict(opened=["https://github.com/novix-science/mlx-sim"], unverified=["CI 持续失败（REPORT.md 结论，本轮未复核）"]),
    ),
    E(
        id="mos-discrepancy",
        name="MOS-discrepancy（残差与参数灵敏度正交的标定框架）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.3",
        paper=dict(
            title="A Sensitivity-based Framework for Calibrating Coupled Ordinary Differential Equations under Model Discrepancy",
            authors=["Mitchel J. Colebank", "William Consagra"],
            date="2026-10-07",
            version="v1（2026-10-07）；33 页 13 图",
            url="https://arxiv.org/abs/2610.09261",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库，报告核对称无 LICENSE）",
            source="https://arxiv.org/abs/2610.09261（2026-10-28 只读）",
        ),
        mech=[
            "对多输出 ODE 的偏差项施加模型结构约束：偏差与参数灵敏度正交，防止残差吞掉参数效应",
            "灵敏度方程与 ODE 系统联立求解（耦合初值问题）得到前向梯度",
            "自适应 Metropolis-within-Gibbs 采样受约束的后验",
        ],
        mlx=dict(
            rating="高（协议层；灵敏度方程与采样都是 CPU 数值计算）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL §2 第 7 条（残差与参数正交）的直接来源。",
        ),
        non=[
            "恢复的是 L² 投影参数，不是物理真值；真实偏差沿灵敏度方向的分量按定义并入 φ̂，报告必须写明",
            "合成数据由 MOS 先验自己生成，『优于 KOH』不能外推",
            "无 LICENSE（报告核对结论），不得复制代码",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.09261"], unverified=["无 LICENSE（取自 REPORT.md §1.3）"]),
    ),
    E(
        id="mujoco",
        name="MuJoCo（含 MuJoCo Warp）",
        status="verified",
        tier="install-pending",
        src="REPORT.md §1.2",
        paper=dict(
            title="MuJoCo（Multi-Joint dynamics with Contact，软件项目；本轮未核对其经典论文条目）",
            authors=["google-deepmind（维护组织）"],
            date="无法核（本轮未核对论文条目日期）",
            version="仓库 https://github.com/google-deepmind/mujoco（2026-10-28 只读，15.9k stars）",
            url="https://github.com/google-deepmind/mujoco",
        ),
        repo=dict(url="https://github.com/google-deepmind/mujoco"),
        license=dict(
            license="Apache-2.0（仓库页许可标注；doc 目录文档另行采用 CC BY 4.0）",
            source="https://github.com/google-deepmind/mujoco（2026-10-28 只读）",
        ),
        mech=[
            "通用刚体接触仿真器，可作离线参考仿真器与线性化来源（mjd_transitionFD）",
            "预编译二进制含 macOS universal 版本（覆盖 Apple Silicon），未逐一实测 CPU 吞吐",
        ],
        mlx=dict(
            rating="中（macOS 预编译可用；MJWarp 需要 NVIDIA，与本机无关）",
            deps=["预编译 wheel / 源码编译；MJWarp 需 NVIDIA GPU"],
            notes="属『需用户批准安装后再用』：本卡未安装、未下载。",
        ),
        non=[
            "MJWarp 需要 NVIDIA GPU；MJWarp 可微仍在开发中",
            "mjd_transitionFD 不支持 RK4（报告核对结论，本轮未复核源码）",
            "不作为世界权威：只作离线参考仿真器与线性化对照",
            "macOS 预编译为 universal binary，arm64 CPU-only 的实际吞吐未实测",
        ],
        ver=dict(opened=["https://github.com/google-deepmind/mujoco"], unverified=["mjd_transitionFD 不支持 RK4", "MJWarp 可微进度"]),
    ),
    E(
        id="nesys",
        name="NeSyS（Neuro-Symbolic Synergy for World Modeling）",
        status="verified",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="Neuro-Symbolic Synergy for World Modeling",
            authors=["Hongyu Zhao", "Siyu Zhou", "Haolin Yang", "Zengyi Qin", "Tianyi Zhou"],
            date="2026-02-11",
            version="v4（2026-09-14）；COLM 2026（arXiv comments 标注 camera-ready）",
            url="https://arxiv.org/abs/2602.10480",
        ),
        repo=dict(url="https://github.com/tianyi-lab/NeSyS"),
        license=dict(
            license="MIT（仓库根目录 LICENSE 原文核实，Copyright (c) 2026 Tianyi Lab）",
            source="https://raw.githubusercontent.com/tianyi-lab/NeSyS/main/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "符号规则以 log-linear 重排给候选打分，不需要 LLM 去读规则文本",
            "规则引导采样：优先取符号规则覆盖弱的转移，用 35–60% 训练对超过全量 SFT",
            "两个模型交替训练：各自在对方解释不足的轨迹上更新",
        ],
        mlx=dict(
            rating="中（规则层是纯符号计算；神经侧是 LLM 微调，本机不跑）",
            deps=["PyTorch（原实现）；本项目只借协议"],
            notes="CMFL §2 第 5 条（按覆盖度降权采样 + 自适应缩放）的来源。",
        ),
        non=[
            "『数据减半且无损』被夸大：真正起作用的是按候选集自适应的缩放（γ = 1 + max log p − min log p）",
            "规则筛选与校准用同一开发集",
            "ScienceWorld/WebShop/PlanCraft 的文本环境结论不外推到 AWZ 视觉物理",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2602.10480", "https://raw.githubusercontent.com/tianyi-lab/NeSyS/main/LICENSE"], unverified=[]),
    ),
    E(
        id="osverify",
        name="OSVerify（有限专家评审下的单侧验证）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="One-Sided Verification Under Limited Expert Review",
            authors=["Fan Nie", "Haotian Ye", "Shurui Liu", "Zihao Wang", "Stefano Ermon", "James Zou"],
            date="2026-10-13",
            version="v2（2026-10-22）",
            url="https://arxiv.org/abs/2610.18089",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.18089（2026-10-28 只读）",
        ),
        mech=[
            "把『提出错误』与『验证错误』解耦：提议者按层次分解搜索错误，验证者区分实质错误与轻微/幻觉错误",
            "单侧目标：在约束误拒率（FNR）的前提下最大化无效解拒识率（TNR），把人工评审成本写进目标",
            "接受阈值在留出集上用次序统计量标定（附录 B.4 的 FactTest 做法）",
        ],
        mlx=dict(
            rating="高（协议层，零下载；标定是纯统计）",
            deps=["无官方代码（协议需自实现）"],
            notes="只借『留出集标定阈值』这一条；其单侧方向与本项目相反。",
        ),
        non=[
            "FNR 指误拒有效解，与我们要控制的错误接受方向相反，不能照搬其指标",
            "主表阈值在评测集上选，只有附录 B.4 在留出集上标定——引用的必须是附录 B.4",
            "竞赛/研究级基准结论不外推到物理机制晋升",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.18089"], unverified=[]),
    ),
    E(
        id="paper2agent",
        name="Paper2Agent（把论文转成 MCP 代理）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Paper2Agent: Reimagining Research Papers As Interactive and Reliable AI Agents",
            authors=["Jiacheng Miao", "Joe R. Davis", "Yaohui Zhang", "Jonathan K. Pritchard", "James Zou"],
            date="2025-09-08",
            version="v2（2025-10-16）；Nature 版标题不同",
            url="https://arxiv.org/abs/2509.06917",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；报告核对称 Nature 版为 CC BY-NC-ND；代码许可：无法核",
            source="https://arxiv.org/abs/2509.06917（2026-10-28 只读）",
        ),
        mech=[
            "自动分析论文与配套代码库，构建 MCP 服务器",
            "迭代生成并运行测试来稳健化生成的 MCP",
        ],
        mlx=dict(
            rating="低（依赖 LLM 代理与外部代码库；本项目不引入）",
            deps=["无法核（无代码链接）"],
            notes="只作为『论文→可调用工具』的工程参照。",
        ),
        non=[
            "74/100 依赖代理自生成的测试，可靠性有循环论证风险",
            "arXiv 标题与 Nature 版标题不同，引用须写清版本",
            "Nature 版为 CC BY-NC-ND（报告核对结论，本轮未复核）",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2509.06917"], unverified=["Nature 版标题与 CC BY-NC-ND"]),
    ),
    E(
        id="patchworld",
        name="PatchWorld（可执行代码世界模型的反例引导修补）",
        status="verified",
        tier="protocol",
        src="REPORT.md §1.2",
        paper=dict(
            title="PatchWorld: Gradient-Free Optimization of Executable World Models for Agent Environments",
            authors=["Jiaxin Bai", "Yue Guo", "Yifei Dong", "Jiaxuan Xiong", "等（共 16 人）"],
            date="2026-05-29",
            version="v4（2026-07-28）",
            url="https://arxiv.org/abs/2605.30880",
        ),
        repo=dict(url="https://github.com/HKBU-KnowComp/PatchWorld"),
        license=dict(
            license="MIT（仓库 README 的 License 节明写 MIT 并指向 LICENSE）",
            source="https://github.com/HKBU-KnowComp/PatchWorld（2026-10-28 只读）",
        ),
        mech=[
            "反例引导的代码修补（CEGIS 式）：把离线轨迹诱导成可检查、可回放、可局部修补的符号信念状态程序",
            "回放式验证与模型选择",
            "反例按类型与严重度分类（执行/接口 > 缺失隐变量 > 状态/读出不符）",
            "『保真度 vs 决策可用性』权衡的显式报告",
        ],
        mlx=dict(
            rating="中（代码是 Python，可读可借；本项目不安装）",
            deps=["Python 3", "AgentGym 客户端（仅 RQ3 需要）"],
            notes="CMFL §3 第 5 条（逐例不回归 + 反例分类）的来源。",
        ),
        non=[
            "『零回归』实际没有实现，只要求聚合分数下降，允许局部回归——这正是要改成逐例不回归的原因",
            "AgentGym 七个文本环境的结论不外推到 AWZ 视觉物理",
            "轨迹数据集在 HuggingFace 单独下载（MIT），本卡未下载",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2605.30880", "https://github.com/HKBU-KnowComp/PatchWorld"], unverified=[]),
    ),
    E(
        id="pg-sr",
        name="PG-SR（Prior-Guided Symbolic Regression）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Prior-Guided Symbolic Regression: Towards Scientific Consistency in Equation Discovery",
            authors=["Jing Xiao", "Xinhai Chen", "Jiaming Peng", "Qinglin Wang", "等（共 10 人）"],
            date="2026-02-13",
            version="v2（2026-02-16）",
            url="https://arxiv.org/abs/2602.13021",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2602.13021（2026-10-28 只读）",
        ),
        mech=[
            "把领域先验编码成可执行约束程序，作为先验约束检查器剪枝候选",
            "先验退火约束评估（PACE）：进化阶段逐步把搜索导向科学一致区域",
            "三阶段流水线：warm-up / evolution / refinement",
        ],
        mlx=dict(
            rating="中（『可执行先验检查器』思想可直接用 NumPy 自实现）",
            deps=["无官方代码（思想需自实现）"],
            notes="CMFL §2 第 1 条只借『可执行先验检查器』这一思想。",
        ),
        non=[
            "每次运行约 1785 万 token、约 10 小时（未复核，取自 REPORT.md §1.2）",
            "没有代码、没有同行评审",
            "『降低 Rademacher 复杂度』的表述被夸大",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2602.13021"], unverified=["token 与时长"]),
    ),
    E(
        id="ph-dreamer",
        name="PH-Dreamer（端口哈密顿生成动力学世界模型）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="PH-Dreamer: A Physics-Driven World Model via Port-Hamiltonian Generative Dynamics",
            authors=["Xueyu Luan", "Chenwei Shi"],
            date="2026-05-18",
            version="v1（2026-05-18）；12 页 3 图",
            url="https://arxiv.org/abs/2605.18303",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2605.18303（2026-10-28 只读）",
        ),
        mech=[
            "把循环转移建模成动作控制的能量路由（流动 + 耗散），把投影潜相空间压向更物理的结构",
            "从本体感觉观测估计哈密顿量与功率平衡，作为热力学推理的显式信号",
            "用能量梯度与拉格朗日乘子正则化 Actor-Critic",
        ],
        mlx=dict(
            rating="低（无代码；RSSM 类架构需 GPU）",
            deps=["无法核（无代码）"],
            notes="CMFL 的 E1 可选臂 ⑧（端口哈密顿）只把它当概念参照。",
        ),
        non=[
            "端口哈密顿只是并行的『影子』正则，不是主架构",
            "论文没有给出 J、R 的参数化形式",
            "没有代码；视觉控制基准结论不外推到 AWZ",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2605.18303"], unverified=[]),
    ),
    E(
        id="pi-adok",
        name="PI-ADoK（约束引导符号回归）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Constraint-Guided Symbolic Regression for Data-Efficient Kinetic Model Discovery",
            authors=[
                "Miguel Ángel de Carvalho Servia",
                "Ilya Orson Sandoval",
                "King Kuok (Mimi) Hii",
                "Klaus Hellgardt",
                "等（共 6 人）",
            ],
            date="2025-07-03",
            version="v1（2025-07-03）；27 页 8 图",
            url="https://arxiv.org/abs/2507.02730",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2507.02730（2026-10-28 只读）",
        ),
        mech=[
            "把物理约束直接注入符号回归，缩小搜索空间并减少所需实验数",
            "Metropolis-Hastings 传播参数不确定性，给出可信预测区间",
        ],
        mlx=dict(
            rating="中（思想可自实现；无代码）",
            deps=["无法核（无代码）"],
            notes="与本项目『可执行先验检查器』同源，但只作观察。",
        ),
        non=[
            "一手 arXiv 标题是 Constraint-Guided Symbolic Regression…，与 REPORT.md 所写标题（Physics-informed…）不同；以 arXiv 为准",
            "约束是有限时间点上的经验检查，不是全域保证",
            "约束来源必须与验证数据独立",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2507.02730"], unverified=["期刊版标题与出处"]),
    ),
    E(
        id="ptrm",
        name="PTRM（Probabilistic Tiny Recursive Model）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Probabilistic Tiny Recursive Model",
            authors=["Amin Sghaier", "Ali Parviz", "Alexia Jolicoeur-Martineau"],
            date="2026-05-19",
            version="v1（2026-05-19）",
            url="https://arxiv.org/abs/2605.19943",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出官方代码仓库；报告核对称只有第三方 GPL-3.0 实现）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无官方代码；第三方实现为 GPL-3.0）",
            source="https://arxiv.org/abs/2605.19943（2026-10-28 只读）",
        ),
        mech=[
            "在每次深层递归注入高斯噪声，让并行轨迹探索不同解域",
            "用模型已有的 Q 头在轨迹间选择，无需重训或任务特定增广",
        ],
        mlx=dict(
            rating="低（无官方代码；第三方 GPL-3.0 不得并入本项目）",
            deps=["无法核（无官方代码）"],
            notes="与 TRM 同源，只作观察。",
        ),
        non=[
            "只有第三方 GPL-3.0 实现，不得复制进本项目",
            "Sudoku-Extreme / Pencil Puzzle Bench 的准确率不外推到世界模型",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2605.19943"], unverified=["第三方 GPL-3.0 实现（取自 REPORT.md §1.2）"]),
    ),
    E(
        id="py-argos",
        name="py-ARGOS（统计严谨的 ODE 自动发现包）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.3",
        paper=dict(
            title="py-ARGOS: A Python package for automatic, statistically principled discovery of ordinary differential equations from data",
            authors=["Yuzheng Zhang", "Rui Carvalho"],
            date="2026-10-25",
            version="v1（2026-10-25）；17 页 4 图",
            url="https://arxiv.org/abs/2610.34458",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码链接；报告核对称仓库与 PyPI 复查为 404）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（仓库 404，无许可可核）",
            source="https://arxiv.org/abs/2610.34458（2026-10-28 只读）",
        ),
        mech=[
            "bootstrap ARGOS 与 Bayesian-ARGOS 两套算法统一接口",
            "每个系数给 bootstrap 置信区间或贝叶斯可信区间，区间不含零才保留项",
            "内置 VIF、Pareto-k、后验预测残差诊断，标记不可靠拟合",
        ],
        mlx=dict(
            rating="高（纯 Python 统计流程；但包本身不可得）",
            deps=["无法核（仓库与 PyPI 不可达）"],
            notes="等仓库公开后再核；本轮只读 abs 页，未见代码链接。",
        ),
        non=[
            "仓库与 PyPI 在报告复查时为 404，许可无法核（本轮 abs 页亦无代码链接）",
            "『改善 SINDy 家族识别性能』只在混沌基准上，不外推到 AWZ",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.34458"], unverified=["仓库/PyPI 404（取自 REPORT.md §1.3，本轮未复查）"]),
    ),
    E(
        id="pysindy",
        name="PySINDy",
        status="verified",
        tier="install-pending",
        src="REPORT.md §1.2",
        paper=dict(
            title="PySINDy: A comprehensive Python package for robust sparse system identification",
            authors=["Alan A. Kaptanoglu", "Brian M. de Silva", "Urban Fasel", "Kadierdan Kaheman", "等（共 12 人）"],
            date="2021-11-12",
            version="v2（2022-01-26）；JOSS，DOI 10.21105/joss.03994",
            url="https://arxiv.org/abs/2111.08481",
        ),
        repo=dict(url="https://github.com/dynamicslab/pysindy"),
        license=dict(
            license="MIT（仓库根目录 LICENSE 原文核实；MIOSR 的可选依赖 gurobipy 是商用求解器，需另行取得许可）",
            source="https://raw.githubusercontent.com/dynamicslab/pysindy/main/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "弱形式 SINDy（WeakPDELibrary）在含噪数据上做系统辨识",
            "SR3 / MIOSR / SBR 等多种稀疏回归优化器，含不等式约束与稳定性约束",
            "积分形式与集成（ensembling）提升真实数据上的稳健性",
        ],
        mlx=dict(
            rating="高（纯 NumPy/SciPy，CPU 可跑）",
            deps=["numpy", "scipy", "scikit-learn", "（可选）cvxpy / pysindy[miosr] 需 gurobipy"],
            notes="属『需用户批准安装后再用』：本卡未安装。核心 STLSQ 可先自实现，PySINDy 只作交叉核对。",
        ),
        non=[
            "弱形式靠已发布的 WeakPDELibrary，不是新方法",
            "包含概率要自己算，包不直接给",
            "『毫秒级』说法没有出处",
            "TrappingSR3 不保证有界",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2111.08481", "https://raw.githubusercontent.com/dynamicslab/pysindy/main/LICENSE"], unverified=[]),
    ),
    E(
        id="pysr",
        name="PySR（符号回归，Julia 后端）",
        status="verified",
        tier="install-pending",
        src="REPORT.md §1.2",
        paper=dict(
            title="PySR — Symbolic Regression in Python and Julia（软件项目；无单篇论文，以文档与 release 为准）",
            authors=["Miles Cranmer"],
            date="2026-10-19",
            version="v2.7.2（release 提交 2026-10-19）；后端 SymbolicRegression.jl",
            url="https://github.com/MilesCranmer/PySR/releases",
        ),
        repo=dict(url="https://github.com/MilesCranmer/PySR"),
        license=dict(
            license="Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright 2020 Miles Cranmer）",
            source="https://raw.githubusercontent.com/MilesCranmer/PySR/master/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "遗传编程式符号回归，带复杂度-精度 Pareto 前沿",
            "量纲约束（软罚项）与模板表达式（2023/2024 特性，不是 v2 新增）",
        ],
        mlx=dict(
            rating="中（Python 前端 + Julia 后端；首次 import 会隐式下载 Julia 依赖）",
            deps=["Python 3", "Julia（SymbolicRegression.jl）", "必须设 JULIA_DEPOT_PATH 隔离"],
            notes="属『需用户批准安装后再用』：本卡未安装、未联网下载 Julia 依赖。",
        ),
        non=[
            "量纲约束（2023）与模板表达式（2024）不是 v2 新特性",
            "量纲约束是软罚项，不是硬约束",
            "首次 import 会隐式联网下载 Julia 依赖到 ~/.julia，必须用 JULIA_DEPOT_PATH 隔离",
            "仓库已重定向到 astroautomata/PySR（原 MilesCranmer/PySR）",
        ],
        ver=dict(opened=["https://github.com/MilesCranmer/PySR", "https://raw.githubusercontent.com/MilesCranmer/PySR/master/LICENSE"], unverified=["量纲约束是软罚项（REPORT.md 结论，本轮未读源码）"]),
    ),
    E(
        id="psi-sindy",
        name="PSI-SINDy（后选择推断）",
        status="verified-paper-only",
        tier="protocol",
        src="REPORT.md §1.3",
        paper=dict(
            title="PSI-SINDy: Post-Selection Inference for Sparse Identification of Nonlinear Dynamics",
            authors=["Ashraful Islam", "Shuichi Nishino", "Tomohiro Shiraishi", "Ichiro Takeuchi"],
            date="2026-10-08",
            version="v1（2026-10-08）；47 页 3 图 16 表",
            url="https://arxiv.org/abs/2610.11486",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.11486（2026-10-28 只读）",
        ),
        mech=[
            "data thinning：把一条观测轨迹拆成四个互相独立、角色不同的视图，分别用于选元与推断",
            "后选择推断同时处理选择偏差、候选项的测量误差与响应/设计的共享噪声",
            "不可辨识的项不报告区间，视为弃权",
        ],
        mlx=dict(
            rating="高（协议层；data thinning 与区间计算是纯数值）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL §2 第 8 条（选结构与做检验分开取数据）的来源。",
        ),
        non=[
            "精确推断就是普通 z 区间，不需要多面体条件化（报告更正）",
            "理论只覆盖标量弱形式、固定多项式库、已知方差的 iid 高斯噪声；多状态情形只是扩展实验",
            "代码未发布",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.11486"], unverified=["『精确推断即普通 z 区间』的推导（取自 REPORT.md §1.3）"]),
    ),
    E(
        id="ref-free-sampling-mpc",
        name="Ref-free 采样 MPC（无参考轨迹的 MPPI）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Reference-Free Sampling-Based Model Predictive Control",
            authors=["Fabian Schramm", "Pierre Fabre", "Nicolas Perrin-Gilbert", "Justin Carpentier"],
            date="2025-11-24",
            version="v3（2026-04-16）；ICRA 2026",
            url="https://arxiv.org/abs/2511.19204",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库；报告核对称方法代码未公开）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2511.19204（2026-10-28 只读）",
        ),
        mech=[
            "在 MPPI 上用三次 Hermite 样条参数化（位置与速度控制点）",
            "不需要参考轨迹或离线预训练，接触/离地策略自动适配任务",
            "少样本采样即可在普通 CPU 上实时控制",
        ],
        mlx=dict(
            rating="高（CPU 实时采样控制，思路可自实现）",
            deps=["无官方代码（方法未公开）"],
            notes="CMFL 的 G9 低功耗控制远期观察项。",
        ),
        non=[
            "只有 30 条采样那一档有实时证据（报告核对结论）",
            "方法代码未公开",
            "Go2 四足与人形仿真结论不外推到 AWZ",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2511.19204"], unverified=["只有 30 条采样档有实时证据"]),
    ),
    E(
        id="sciexplorer",
        name="SciExplorer（Agentic Exploration of Physics Models）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Agentic Exploration of Physics Models",
            authors=["Maximilian Nägele", "Florian Marquardt"],
            date="2025-09-29",
            version="v6（2026-07-08）；期刊版 Phys. Rev. X 16, 031002 (2026)，DOI 10.1103/xnqc-q6nt",
            url="https://arxiv.org/abs/2509.24978",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2509.24978（2026-10-28 只读）",
        ),
        mech=[
            "只用代码执行等极简工具，在没有任何领域蓝图的条件下探索未知系统",
            "从观测动力学恢复运动方程、从期望值推断哈密顿量",
        ],
        mlx=dict(
            rating="低（依赖闭源 LLM；本项目不引入）",
            deps=["无法核（无代码链接）"],
            notes="CMFL 只把『LLM 留在外圈』当旁证。",
        ),
        non=[
            "依赖 GPT-5 一类闭源模型，开源模型失败（报告核对结论）",
            "没有『主动选实验 vs 随机选实验』的消融",
            "本轮只读 abs 页未见代码链接",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2509.24978"], unverified=["开源模型失败的具体实验"]),
    ),
    E(
        id="slim",
        name="SLIM（少动作帧下的 JEPA 可规划性）",
        status="verified-paper-only",
        tier="s2s5",
        src="REPORT.md §1.2",
        paper=dict(
            title="Keeping JEPA World Models Plannable When Little of the Frame Moves",
            authors=["Florian Strohm", "Patrick Wagner", "Jannik Schwab", "Marco Huber"],
            date="2026-10-02",
            version="v1（2026-10-02）",
            url="https://arxiv.org/abs/2610.03137",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库；报告核对称代码未发布）",
            source="https://arxiv.org/abs/2610.03137（2026-10-28 只读）",
        ),
        mech=[
            "动作敏感性探针（无需环境访问）作为经验必要条件：低于阈值的配置全部规划失败",
            "共享头的逆动力学辅助损失，同时作用于编码器潜与预测潜，测试时丢弃该头",
            "SLIM 推箱子基准：同一场景上成对的视觉目标与语言目标",
        ],
        mlx=dict(
            rating="中（探针与辅助损失都可在 MLX 复现；无代码）",
            deps=["无法核（无代码）"],
            notes="S2/S5 阶段的诊断项；阈值必须在 AWZ 上重新标定。",
        ),
        non=[
            "修复约 85% 来自编码器侧梯度，预测器侧 IDM 单独无效（p=0.13）",
            "LeWM 在 SLIM 上 <1% 的成功率是 SLIM 基准的结论，不代表 AWZ",
            "『动作敏感性阈值』是经验必要条件，不是充分条件",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.03137"], unverified=["85% 与 p=0.13 的具体消融"]),
    ),
    E(
        id="slice",
        name="SLICE（共形 e-value 的随时有效置信序列）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.3",
        paper=dict(
            title="SLICE: Sequential Likelihood-Free Inference via Conformal E-Values",
            authors=["Stefano Cortinovis", "Laura Battaglia", "François Caron"],
            date="2026-10-09",
            version="v2（2026-10-13）",
            url="https://arxiv.org/abs/2610.13855",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.13855（2026-10-28 只读）",
        ),
        mech=[
            "每次观测都从各候选零假设重新模拟，把可预测的正得分共形化成条件 e-value，连乘成检验鞅",
            "对参数反演得到随时有效的置信序列；集合变空可作为『现有机制不足』的信号（用法待验证）",
            "用摊销神经似然比估计逼近 oracle 的似然比得分",
        ],
        mlx=dict(
            rating="中（协议可自实现；前提是模拟器噪声模型正确）",
            deps=["无官方代码（协议需自实现）"],
            notes="CMFL 的 PARAMETRIC 分支可选置信集；确定性 F_prior 不能直接用。",
        ),
        non=[
            "要求带有设定正确噪声模型的随机模拟器；确定性模拟器不能直接用",
            "轨迹数据必须在同一段已观测历史上做条件模拟",
            "『集合变空即机制不足』这一用法需另行验证",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.13855"], unverified=[]),
    ),
    E(
        id="srharness",
        name="SRHarness（Agentic 符号回归运行时）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="SRHarness: A Harness for Agentic Symbolic Regression",
            authors=["Zihan Yu", "Shixuan Zhou", "Hao Huang", "Jingtao Ding", "Yong Li"],
            date="2026-09-28",
            version="v2（2026-10-24）",
            url="https://arxiv.org/abs/2609.35501",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2609.35501（2026-10-28 只读）",
        ),
        mech=[
            "可组合的科学动作接口：对原始量、变换量与候选导出量统一寻址",
            "持久科学状态：保留已评估假设并暴露紧凑的模型视图",
            "轨迹生命周期管理：继续、分支、重启、终止",
        ],
        mlx=dict(
            rating="中（工程模式可借鉴；实现依赖 LLM 代理）",
            deps=["无法核（无代码链接）"],
            notes="REPORT.md §4 未给它单独分级，本卡按 §1.2 结论归『只观察』。",
        ),
        non=[
            "分支与重启在消融里没有收益（报告核对结论）",
            "符号准确率由 LLM 评审给出，不是独立测试",
            "LLM-SRBench 数字绑定 DeepSeek-v4-flash-0731 等特定底座",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2609.35501"], unverified=["分支/重启无收益的消融"]),
    ),
    E(
        id="stochastic-phnn",
        name="SPH-NN（随机端口哈密顿神经网络）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="Stochastic Port-Hamiltonian Neural Networks: Universal Approximation with Passivity Guarantees",
            authors=["Luca Di Persio", "Matthias Ehrhardt", "Youness Outaleb"],
            date="2026-03-10",
            version="v1（2026-03-10）",
            url="https://arxiv.org/abs/2603.10078",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2603.10078（2026-10-28 只读）",
        ),
        mech=[
            "用前馈网参数化哈密顿量，强制互联矩阵反对称、耗散矩阵半正定",
            "Itô 动力学下给出期望意义、紧集停时的弱无源不等式",
            "紧集与有限时域上的通用逼近结果",
        ],
        mlx=dict(
            rating="中（结构约束可在 MLX 实现；无代码）",
            deps=["无法核（无代码）"],
            notes="E1 可选臂 ⑧ 的理论参照；只作观察。",
        ),
        non=[
            "弱无源界是逼近存在性推论，只在连续时间、期望意义、紧集停时下成立，不证明训练出的网络满足",
            "不得用连续时间定理代替离散积分器上的实测能量漂移",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2603.10078"], unverified=[]),
    ),
    E(
        id="supermimic",
        name="SuperMimic（单可微世界模型的人形全身控制）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="SuperMimic: Scaling Humanoid Whole-Body Control with One Differentiable World Model",
            authors=["Qiayuan Liao", "Yiyang Shao", "Junfeng Long", "Kevin Zakka", "等（共 7 人）"],
            date="2026-10-20",
            version="v1（2026-10-20）；CoRL 2026 Oral（arXiv comments）",
            url="https://arxiv.org/abs/2610.28480",
        ),
        repo=dict(url="无法核（arXiv comments 只给项目页 https://supermimic.github.io ，未给代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.28480（2026-10-28 只读）",
        ),
        mech=[
            "用共享动力学的单个可微世界模型摊销所有动作的学习，世界模型与跟踪策略同环训练",
            "短程想象 rollout 上做 BPTT 给策略解析梯度",
        ],
        mlx=dict(
            rating="低（人形全身控制 + GPU 训练，与本项目无关）",
            deps=["无法核（无代码）"],
            notes="只作『可微世界模型做摊销』的工程观察。",
        ),
        non=[
            "1000× 对比的是 SONIC 自报的 128×L40×7 天，不是同一硬件（报告核对结论）",
            "人形动作跟踪的结论不外推到 AWZ",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.28480"], unverified=["SONIC 对比细节"]),
    ),
    E(
        id="simulcost",
        name="SimulCost（成本敏感的物理仿真调参基准）",
        status="verified",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="SimulCost: A Cost-Aware Benchmark and Toolkit for Automating Physics Simulations with LLMs",
            authors=["Yadi Cao", "Sicheng Lai", "Jiahe Huang", "Yang Zhang", "等（共 15 人）"],
            date="2026-03-11",
            version="v4（2026-08-17）；v4 移除了 CGYRO 算例",
            url="https://arxiv.org/abs/2603.20253",
        ),
        repo=dict(url="https://github.com/Rose-STL-Lab/SimulCost-Bench"),
        license=dict(
            license="Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright [2026] [Sicheng Lai]）",
            source="https://raw.githubusercontent.com/Rose-STL-Lab/SimulCost-Bench/main/LICENSE（2026-10-28 只读）",
        ),
        mech=[
            "把工具使用成本（仿真时间、实验资源）写进评测，而不只算 token 成本",
            "成本解析定义、与平台无关；另有一个只能用墙钟计量的生产等离子体代码单列",
            "比较 LLM 调参与传统扫描的精度与成本",
        ],
        mlx=dict(
            rating="低（基准面向 LLM 代理与 11 个仿真器；本项目不安装）",
            deps=["Python（基准包）；具体仿真器依赖见仓库"],
            notes="只作为『LLM 不进内环』的旁证，不运行。",
        ),
        non=[
            "『1.5–2.7 倍』是成功样本上的解析 FLOP 成本，不是墙钟时间",
            "v4 已移除 CGYRO 算例（作者称因算例搜索有 bug，将加回）",
            "结论绑定具体闭源模型版本",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2603.20253", "https://raw.githubusercontent.com/Rose-STL-Lab/SimulCost-Bench/main/LICENSE"], unverified=[]),
    ),
    E(
        id="t2-z",
        name="T2-z（环境潜变量的测试时优化）",
        status="verified-paper-only",
        tier="observe",
        src="REPORT.md §1.2",
        paper=dict(
            title="T2-z: Test-Time Optimization of Environment Latents for Robotic World Models",
            authors=["Chenyuan Zhou", "Yining Hong", "Huang Huang", "Yunfan Jiang", "等（共 12 人）"],
            date="2026-10-15",
            version="v1（2026-10-15）",
            url="https://arxiv.org/abs/2610.22364",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2610.22364（2026-10-28 只读）",
        ),
        mech=[
            "给机器人世界模型加一个可学习的环境潜变量 z，用来条件化预测",
            "训练时两阶段交替：固定 z 学通用动力学 / 冻结模型只优化 z",
            "测试时冻结世界模型，只用一至多次交互优化新初始化的 z",
        ],
        mlx=dict(
            rating="低（底座是 5B 视频模型，需 GPU）",
            deps=["无法核（无代码）"],
            notes="与 MSG 的 PARAMETRIC 分支概念相近，但 z 不是信念分布。",
        ),
        non=[
            "z 是点估计，不是『信念』，不能当后验用",
            "底座为 5B 视频模型，训练需 2×24 H200 小时（报告核对结论）",
            "摘要的 15.20→7.00 是混合单位的加权平均，不能当单一指标",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2610.22364"], unverified=["训练资源 2×24 H200 小时"]),
    ),
    E(
        id="trm",
        name="TRM（Tiny Recursive Model）",
        status="verified-paper-only",
        tier="s2s5",
        src="REPORT.md §1.2",
        paper=dict(
            title="Less is More: Recursive Reasoning with Tiny Networks",
            authors=["Alexia Jolicoeur-Martineau"],
            date="2025-10-06",
            version="v1（2025-10-06）",
            url="https://arxiv.org/abs/2510.04871",
        ),
        repo=dict(url="无法核（arXiv 摘要与 comments 均未给出代码仓库）"),
        license=dict(
            license="论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）",
            source="https://arxiv.org/abs/2510.04871（2026-10-28 只读）",
        ),
        mech=[
            "单个 2 层小网络在不同频率上递归精化潜状态与答案",
            "以极少参数在小数据上超过 LLM 的 ARC-AGI 成绩",
        ],
        mlx=dict(
            rating="中（7M 参数小网络，MLX 可复现；无官方代码）",
            deps=["无法核（无官方代码）"],
            notes="S2/S5 阶段的自适应算力诊断项。",
        ),
        non=[
            "停机头只在训练时用，测试时固定跑满 16 步（报告核对结论）",
            "ARC-AGI 成绩不外推到世界模型规划",
        ],
        ver=dict(opened=["https://arxiv.org/abs/2510.04871"], unverified=["测试时固定 16 步"]),
    ),
]

# ---------------------------------------------------------------------------
# 已在册条目的更正说明（只追加，不改原字段结论）
# ---------------------------------------------------------------------------
CORRECTIONS = {
    "lewm": {
        "corrections_date": ACCESS_DATE,
        "corrections": [
            "SIGReg（Sketched Isotropic Gaussian Regularizer）出自 LeJEPA（arXiv 2511.08544，2025-11-12），不是 LeWM 本文的贡献；本条目『可借鉴机制』里列 SIGReg 时必须注明出处为 LeJEPA。",
            "仓库里没有任何 JEPA 或 SIGReg 实现可用于本项目；LeWM 仍只是 S2 的设计候选，不是『已采用』。",
        ],
        "corrections_source": "reports/frontier-integration-20261027/REPORT.md §1.1 与 §1.2（2026-10-28 核对）；https://arxiv.org/abs/2511.08544",
    },
    "equivariant-trust-horizons": {
        "corrections_date": ACCESS_DATE,
        "corrections": [
            "乘性共形因子 γ_α ≥ 1 由构造恒成立：校准只能把证书放宽，不能收紧。论文审计集上 γ_α=1.0 只说明『原始证书在该审计协议下已保守』，不是校准收紧了界。",
            "论文漏了有限样本修正：分位数应取 ⌈(1−α)(n+1)⌉/n；n 太小时证书为空，此时宁可拒绝晋升，不得用未修正分位数。",
            "本次只读复核 arXiv 2606.24946 v1 摘要，确认 γ_α=1.0 与『50 次稳定审计零反保守违例，精确二项 95% 上界 5.8%』两项表述。",
        ],
        "corrections_source": "https://arxiv.org/abs/2606.24946（2026-10-28 只读）；REPORT.md §1.2",
    },
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    args = ap.parse_args()
    root = Path(args.root).resolve()

    jp = root / "docs/research/adapter_registry.json"
    mp = root / "docs/research/ADAPTER_REGISTRY.md"
    data = json.loads(jp.read_text(encoding="utf-8"))
    md = mp.read_text(encoding="utf-8")

    old_entries = data["entries"]
    old_ids = [e["id"] for e in old_entries]
    new_ids = [e["id"] for e in NEW_ENTRIES]
    assert not (set(old_ids) & set(new_ids)), f"ID 冲突: {sorted(set(old_ids) & set(new_ids))}"

    # ---- 新条目转成 schema 形态 ----
    converted = []
    for e in NEW_ENTRIES:
        entry = {
            "id": e["id"],
            "name": e["name"],
            "status": e["status"],
            "access_date": ACCESS_DATE,
            "version_note": e["paper"]["version"],
            "source_ref": e["src"],
            "adoption_tier": e["tier"],
            "adoption_tier_label": TIER_LABEL[e["tier"]],
            "paper": e["paper"],
            "repo": e["repo"],
            "license": e["license"],
            "borrowable_mechanisms": e["mech"],
            "mlx_feasibility": e["mlx"],
            "non_inferables": e["non"],
            "verification": e["ver"],
        }
        converted.append(entry)

    # ---- 更正 ----
    for e in old_entries:
        if e["id"] in CORRECTIONS:
            e.update(CORRECTIONS[e["id"]])

    entries = sorted(old_entries + converted, key=lambda x: x["id"])

    tier_counts = {}
    for e in entries:
        t = e.get("adoption_tier")
        if t:
            tier_counts[t] = tier_counts.get(t, 0) + 1

    total = len(entries)
    data["entries"] = entries
    data["access_date"] = ACCESS_DATE
    data["access_date_note"] = (
        "r3（51 条）保留 2026-10-16 的访问记录（逐条 access_date 未改写）；r4 新增 45 条于 2026-10-28 只读核实。"
    )
    data["revision"] = (
        f"r4（{ACCESS_DATE}，ainerzero.V9.R11）：在 r3（51 条）基础上，按 reports/frontier-integration-20261027/REPORT.md "
        f"§1.2 与 §1.3 补登记 CMFL 调研已核条目 45 条，并给 lewm / equivariant-trust-horizons 追加更正说明，合计 {total} 条。"
        "每条新条目均于 2026-10-28 打开一手来源（arXiv abs 页、期刊/Crossref 记录、GitHub 仓库页或 raw LICENSE）核对；"
        "raw/ 只作线索不作依据。r3 原字节归档于 reports/V9-R11/r3-archive/。"
    )
    data["r4_summary"] = {
        "total_entries": total,
        "preserved_from_r3_count": len(old_ids),
        "preserved_from_r3_ids": sorted(old_ids),
        "r11_added_count": len(new_ids),
        "r11_added_ids": sorted(new_ids),
        "corrected_ids": sorted(CORRECTIONS),
        "tier_counts": dict(sorted(tier_counts.items())),
        "tier_labels": TIER_LABEL,
        "source_report": "reports/frontier-integration-20261027/REPORT.md（§1.2、§1.3、§4）",
        "verification_date": ACCESS_DATE,
    }
    # 历史快照不得被改写
    data["r5_summary"]["snapshot_note"] = (
        "r3 交付时快照（2026-10-16 ainerzero.V9.R5 共 51 条）；r4 之后仍保留，仅作历史对照"
    )
    data["r3_summary"]["snapshot_note"] = "R3 历史快照（2026-10-16 ainerzero.V9.R3 交付时共 28 条）"

    jp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    # MD 同步
    # ------------------------------------------------------------------
    # §1 表格：保留老行原文，按 id 归并排序
    row_re = re.compile(r"^\| ([a-z0-9\-]+) \| (.+)$")
    old_rows = {}
    for line in md.splitlines():
        m = row_re.match(line)
        if m and m.group(1) in old_ids:
            old_rows[m.group(1)] = line

    def md_row(e):
        p, r, lic = e["paper"], e["repo"], e["license"]
        tier = f"{e.get('adoption_tier_label', '—')}；{e.get('source_ref', '—')}"
        non = "；".join(e["non_inferables"])[:120]
        return (
            f"| {e['id']} | {e['name']} | R11 补登记（{tier}） | {p['url']} ，{p['date']} | {r['url']} | "
            f"{lic['license']} | {e['mlx_feasibility']['rating']} | {non} |"
        )

    table_rows = []
    for e in entries:
        table_rows.append(old_rows.get(e["id"]) or md_row(e))

    # §4 机制汇总
    mech_re = re.compile(r"^- \*\*([a-z0-9\-]+)\*\*：(.+)$")
    old_mech = {}
    for line in md.splitlines():
        m = mech_re.match(line)
        if m and m.group(1) in old_ids:
            old_mech[m.group(1)] = line

    mech_lines = []
    for e in entries:
        mech_lines.append(old_mech.get(e["id"]) or f"- **{e['id']}**：{'；'.join(e['borrowable_mechanisms'])}")

    # 切分原 MD（用下标切片，避免把标题里的『（51 条…）』后缀留在下一段里）
    i1 = md.index("## 1. 总表")
    i2 = md.index("## 2. 9.1 增补专项记录")
    i3 = md.index("## 3. R5 增补重点来源与未核项核实结论")
    i4 = md.index("## 4. 可借鉴机制汇总")
    i5 = md.index("## 5. 既有说明与无法核/非商业限制边界汇总")
    i6 = md.index("## 6. 访问日期与只读声明")
    head = md[:i1]
    sec2 = md[i2:i3]
    sec3 = md[i3:i4]
    sec5 = md[i5:i6]

    # head：改标题与新增 r4 修订说明
    head_lines = head.rstrip().splitlines()
    head_lines[0] = (
        "# Research Adapter Registry v0（ainerzero.V9.R1 r1 + V9.R3 r2 + V9.R5 r3 + V9.R11 r4 补登记，2026-10-28）"
    )
    head_text = "\n".join(head_lines)
    head_text += (
        f"\n- **r4 修订（V9.R11，二级 `deepseek-q7m2`，访问日期 `{ACCESS_DATE}`）**：保留 r3 全部 51 条"
        "（原字节先归档于 `reports/V9-R11/r3-archive/`，附 SHA256SUMS，未覆盖），按 "
        "`reports/frontier-integration-20261027/REPORT.md` §1.2 与 §1.3 补登记 CMFL 调研已核条目 "
        f"**{len(new_ids)} 条**，并对 `lewm`、`equivariant-trust-horizons` 追加更正说明（见 §8），合计 **{total} 条**。"
        "每条新条目均自行打开一手来源（arXiv abs 页、期刊/Crossref 记录、GitHub 仓库页或 raw LICENSE）核对；"
        "`raw/` 只作线索不作依据。分类沿用 REPORT.md §4 的六级（见 §7）。查不到的字段如实标 `无法核`，不猜、不外推。\n"
    )

    sec1 = (
        f"## 1. 总表（{total} 条，与 `adapter_registry.json` 严格同步）\n\n"
        "| ID | 条目 | 分类/来源状态 | 论文/日期（只读核实） | 仓库/代码来源 | 许可（代码 / 论文 / 数据集） | MLX 可行性 | 不可推断项（摘） |\n"
        "|---|---|---|---|---|---|---|---|\n" + "\n".join(table_rows) + "\n\n---\n\n"
    )

    sec4 = (
        f"## 4. 可借鉴机制汇总（全部 {total} 条）\n\n" + "\n".join(mech_lines) + "\n\n---\n\n"
    )

    # §5.4 / §5.5：由数据生成
    unver = [e for e in entries if "无法核" in e["license"]["license"]]
    nc = [
        e
        for e in entries
        if any(k in e["license"]["license"] for k in ("非商业", "Non-Commercial", "NC", "NC-SA", "NC-ND"))
        and e["id"] not in old_ids
    ]
    sec5_extra = (
        f"\n### 5.4 r4 新增条目中代码许可标『无法核』的（共 {len([e for e in unver if e['id'] not in old_ids])} 条）\n"
        + "\n".join(
            f"{i}. `{e['id']}`（{e['paper']['url']}）：{e['license']['license']}"
            for i, e in enumerate([e for e in unver if e["id"] not in old_ids], 1)
        )
        + f"\n\n### 5.5 r4 新增条目中带非商业限制的（共 {len(nc)} 条；含论文许可层面的限制，严禁商用复制代码或权重）\n"
        + ("\n".join(f"{i}. `{e['id']}`：{e['license']['license']}" for i, e in enumerate(nc, 1)) if nc else "（无）")
        + "\n"
    )

    # §7 采纳分级（REPORT.md §4）
    sec7 = "\n## 7. r4 采纳分级（按 REPORT.md §4；仅覆盖 r4 新增 45 条）\n\n"
    sec7 += "| 级别 | 条目 |\n|---|---|\n"
    for t in ("protocol", "self-implement", "install-pending", "s2s5", "observe", "excluded"):
        ids = [e["id"] for e in entries if e.get("adoption_tier") == t]
        if ids:
            sec7 += f"| **{TIER_LABEL[t]}**（{len(ids)}） | " + "、".join(f"`{i}`" for i in ids) + " |\n"
    sec7 += (
        "\n说明：『算法自实现』在 r4 里没有独立条目——弱形式 STLSQ、参数增广滤波/低维 SMC、BIC 模型比较、"
        "Fisher 信息与 EIG 属自实现清单，不指向外部来源；`pysindy` / `pysr` / `mujoco` / `llm-idea` 归『需用户批准安装』，"
        "本卡未安装、未 clone、未下载权重。\n"
    )

    # §8 更正记录
    sec8 = "\n## 8. r4 更正记录与与报告不一致处\n\n### 8.1 已在册条目的更正（只追加，不改原结论）\n"
    for eid, c in CORRECTIONS.items():
        sec8 += f"\n**`{eid}`**（{c['corrections_date']}）\n"
        for i, t in enumerate(c["corrections"], 1):
            sec8 += f"{i}. {t}\n"
        sec8 += f"- 依据：{c['corrections_source']}\n"
    sec8 += """
### 8.2 一手来源与 REPORT.md 不一致、以一手来源为准的条目

| 条目 | 报告写法 | 一手来源（2026-10-28） | 处理 |
|---|---|---|---|
| `pi-adok` | 标题写作 *Physics-informed symbolic regression for data-efficient kinetic model discovery* | arXiv 2507.02730 标题为 *Constraint-Guided Symbolic Regression for Data-Efficient Kinetic Model Discovery* | 以 arXiv 标题登记，报告的期刊版标题标为未复核 |
| `lean-verified-qec` | 报告标『推断为 2510.20728』，简称带 Lean-verified | arXiv 2510.20728 标题为 *Co-Designing Quantum Codes with Transversal Diagonal Gates via Multi-Agent Systems*，正文确有独立 Lean 4 验证层 | 保留报告简称，但明确写出『一手标题不含 Lean-verified』 |
| `jepa-anything` | 『领域训练代码没有发布』 | 仓库已发布 `jepa-anything-core` 核心库与脚手架，但仍无领域数据集、无权重、无领域训练代码 | 表述改为『领域训练代码没有发布，仓库只含核心库/脚手架』 |
| `pysr` | Apache-2.0 | LICENSE 原文为 Apache License 2.0（Copyright 2020 Miles Cranmer），仓库已重定向到 `astroautomata/PySR` | 一致；补记重定向 |
| `mlx-sim` | 没有 LICENSE | 仓库 `novix-science/mlx-sim` 根目录确无 LICENSE 文件，README/pyproject 自称 MIT | 一致；补记『README 自述不能当许可依据』与 clone 地址笔误 |
| `sciexplorer` | 预印本 2509.24978 | 已出期刊版 Phys. Rev. X 16, 031002 (2026)，DOI 10.1103/xnqc-q6nt | 补记期刊版 |
| `cosr` | arXiv v2 曾因 RBC 算例缺陷撤回 | abs 页明示 withdrawn，comments 为『needs to be retracted due to methodological flaws found in RBC case』 | 一致，按已撤回登记 |
| `llm-idea` | 辨识引擎已发布、提议者未发布 | 仓库 README 明确『What is not released』只排除提议者（Agentic Council）与整数序列适配器 | 一致 |

### 8.3 本轮未能复核、仍沿用报告结论的说法（均已在新条目 `verification.unverified` 标注）

- `ai-newton` 的 Maple/CUDA 依赖与约 48 小时；`dwc` 的 2 nJ/Vivado 估计；`mujoco` 的 `mjd_transitionFD` 不支持 RK4 与 MJWarp 可微进度；
- `pg-sr` 的约 1785 万 token/10 小时；`slim` 的 85% 与 p=0.13；`deepjepa` 的『增益在种子标准差以内』；`t2-z` 的 2×24 H200 小时；
- `py-argos` 的仓库/PyPI 404（本轮只核 abs 页无代码链接）；`paper2agent` 的 Nature 版标题与 CC BY-NC-ND。
- 论文自身的许可（arXiv 页面不显示许可声明）对绝大多数条目记 `无法核`；只有 `active-inference-value-profiles` 走 Crossref 拿到 CC BY 4.0。
"""

    sec6 = (
        "## 6. 访问日期与只读声明\n"
        f"- r3 条目统一只读核验日期：`2026-10-16`（逐条 `access_date` 未改写）；r4 新增 45 条：`{ACCESS_DATE}`。\n"
        "- 全程通过 HTTP 协议只读访问公共元数据、arXiv abs 页、Crossref 记录、GitHub 仓库页与 raw 协议文件。\n"
        "- **严格遵守执行层纪律**：纯 CPU 环境，未调用 GPU/MLX/torch 训练；未 clone、未下载任何模型权重、未下载任何数据集；"
        "未安装依赖、未产生任何付费调用。\n"
    )

    new_md = head_text + "\n" + sec1 + sec2 + sec3 + sec4 + sec5.rstrip() + "\n" + sec5_extra + "\n---\n\n" + sec6 + sec7 + sec8
    mp.write_text(new_md, encoding="utf-8")
    print(f"写入 {jp} 与 {mp}：共 {total} 条（保留 {len(old_ids)}，新增 {len(new_ids)}）")
    print(f"分级统计：{tier_counts}")


if __name__ == "__main__":
    main()
