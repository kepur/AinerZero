# Research Adapter Registry v0（ainerzero.V9.R1 r1 + V9.R3 r2 + V9.R5 r3 + V9.R11 r4 补登记，2026-10-28）

只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。
机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。
- **r1 修订（V9.R1）**：回应 R2 独立复核，修正 THICK 官方代码结论、Stable WorldModel v1 日期、V-JEPA 2.1 直链；原 r0 字节归档于 `reports/V9-R1/r0-archive/`。
- **r2 修订（V9.R3）**：保留 R1 r1 全部 8 条，按 `docs/research/V9_RESEARCH_SURVEY.md` §8 补入已核与仅标题检索 9 条，逐条核对 §8 未核清单全部 12 项，并按 9.1 增补登记 `BlenderWorld`，合计 **28 条**；原字节归档于 `reports/V9-R3/r1-archive/`。
- **r3 修订（V9.R5，二级 `gemini-k7x2`，访问日期 `2026-10-16`）**：保留 R3 全部 28 条（原字节先归档于 `reports/V9-R5/r2-archive/`，未覆盖），按 `docs/research/V9_FRONTIER_COST_SURVEY.md` §7 补登记 14 篇前沿论文（DINO-WM、V-JEPA 2-AC、PLDM、LeJEPA、解析规范化、RLT、Theia、REPA、Pushforward、epinet、Titans、Nested Learning、CUT3R、SlotSSMs）与 7 个仓库（DA3、map-anything、dinov3、sam2、tapnet、genesis-world、kubric），并逐条核对 5 项未核清单（Muon/Moonlight 效率、tapnet 检查点许可、CUT3R 许可、Kubric 许可、AM-RADIO 许可），新增 23 条，合计 **51 条**。凡官方页面/API 未提供或未声明的代码仓库与许可证一律如实标注 `无法核`，绝不猜测或外推。
- **r4 修订（V9.R11，二级 `deepseek-q7m2`，访问日期 `2026-10-28`）**：保留 r3 全部 51 条（原字节先归档于 `reports/V9-R11/r3-archive/`，附 SHA256SUMS，未覆盖），按 `reports/frontier-integration-20261027/REPORT.md` §1.2 与 §1.3 补登记 CMFL 调研已核条目 **45 条**，并对 `lewm`、`equivariant-trust-horizons` 追加更正说明（见 §8），合计 **96 条**。每条新条目均自行打开一手来源（arXiv abs 页、期刊/Crossref 记录、GitHub 仓库页或 raw LICENSE）核对；`raw/` 只作线索不作依据。分类沿用 REPORT.md §4 的六级（见 §7）。查不到的字段如实标 `无法核`，不猜、不外推。

## 1. 总表（96 条，与 `adapter_registry.json` 严格同步）

| ID | 条目 | 分类/来源状态 | 论文/日期（只读核实） | 仓库/代码来源 | 许可（代码 / 论文 / 数据集） | MLX 可行性 | 不可推断项（摘） |
|---|---|---|---|---|---|---|---|
| active-inference-value-profiles | Active inference with reusable state-dependent value profiles | R11 补登记（直接借协议；REPORT.md §1.2） | https://link.springer.com/article/10.1007/s00422-026-01066-0 ，2026-10-09 | 无法核（Crossref 记录与期刊条目均未给出代码仓库；本轮只读未检索到） | 论文：CC BY 4.0（Crossref 记录 license URL creativecommons.org/licenses/by/4.0）；代码许可：无法核（无公开代码仓库） | 高（纯 CPU 可自写的统计流程；无官方代码，须自行实现） | 模型恢复不对称：报告核对指出 M1 与 M2 不可分，不能把『恢复成功』当作机制唯一；单作者、无代码，复现风险高（未复核）；价值档案的可复用性结论建立在作者自己的任务族上，不外推到 AWZ |
| ai-newton | AI-Newton（概念驱动的物理定律发现系统） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2504.01538 ，2025-04-02 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（报告称依赖商用 Maple 与 CUDA，本轮未复核实现依赖） | 依赖商用 Maple 与 CUDA、平均约 48 小时（未复核，取自 REPORT.md §1.2）；重发现牛顿第二定律/能量守恒/万有引力属教科书级目标，不代表能发现 AWZ 的未知机制 |
| alder | ALDER（Action-guided Law Discovery, Evaluation, and Revision） | R11 补登记（直接借协议；REPORT.md §1.3） | https://arxiv.org/abs/2609.33728 ，2026-09-27 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（协议层，零下载；拟合与检验都是 CPU 数值计算） | 判别实验打分含新颖性奖励与成本项，不只看候选间预测分歧（报告核对结论）；仓库无代码许可（未发布），只能借协议不能借实现；in-house benchmark 与 ODE 任务的结论不外推到 AWZ 接触/摩擦场景 |
| am-radio | AM-RADIO (All-in-One Model for Vision) | R5 前沿增补补登记 | https://arxiv.org/abs/2312.06709 ，2023-12-14 | https://github.com/NVlabs/RADIO | NVIDIA Source Code License（非商业限制，官方 LICENSE 原文第 3.3 节核实：The Work and any derivative works thereof only may be used or intended for use non-commercially... for research or evaluation purposes only） | 低 | NVIDIA 专有许可证明确限制仅限非商业研究或评估，衍生作品受到同等传染约束 |
| banino-2018 | Banino et al. 2018（Vector-based Navigation with Grid-like Representations） | R3 未核清单核实 | https://doi.org/10.1038/s41586-018-0102-6 ，2018-05-09（Nature 557, 429-433；PMCID PMC7619527） | https://github.com/google-deepmind/grid-cells | 代码仓库：Apache-2.0（google-deepmind/grid-cells，GitHub API license.key=apache-2.0）；论文：Springer Nature TDM（Crossref 记录）；论文中 RL 导航智能体代码未开源（无法核） | 低 | Schaeffer 等（2312.03954）已证明该文网格细胞涌现高度依赖特定人为超参，不能作为『训练路径积分必然涌现网格细胞』的依据 |
| barrau-bonnabel-2017 | Barrau & Bonnabel 2017（Invariant Extended Kalman Filter / IEKF） | R3 未核清单核实 | https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ，2014-10-06（arXiv 1410.1465 v1；v4 2015-10-19；IEEE Transactions on Automatic Control 62(4), 1797-1812, 2017-04） | 无法核（arXiv 1410.1465 与 IEEE TAC 10.1109/TAC.2016.2594085 均为控制论数学定理证明论文，未提供官方代码仓库） | 论文：arXiv non-exclusive distribution 1.0 / IEEE 出版许可（Crossref 记录 https://ieeexplore.ieee.org/Xplorehelp/downloads/license-information/IEEE.html）；代码许可：无法核（无官方代码仓库） | 高 | 官方代码与代码许可无法核 |
| blenderworld | BlenderWorld（3D 创作评测基准，非世界模型） | 9.1 增补评测基准 | https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf ，2026-10（GitHub pushed_at 2026-10-16） | https://github.com/QwenLM/BlenderWorld | 代码仓库：MIT（QwenLM/BlenderWorld，GitHub API license.key=mit）；数据集卡：MIT（HuggingFace API datasets/Qwen/BlenderWorld cardData.license=mit 与 README YAML header license: mit） | 低 | BlenderWorld 是 3D 场景创作智能体的评测基准，绝对不是世界模型（NOT a world model），不得混入世界脑预测模型基线 |
| canonicalization | Analytical Canonicalization (解析规范化) | R5 前沿增补补登记 | https://arxiv.org/abs/2211.06489 ，2022-11-12 | 无法核（论文摘要与作者主页均未发布独立公开开源代码仓库） | 无法核（论文 arXiv non-exclusive 1.0；代码许可无法核） | 高 | 几何点云与分子基准上的等变保证不代表在严重遮挡与噪点图像下的同等稳健性 |
| cls | CLS（Complementary Learning Systems 互补学习系统） | R3 未核清单核实 | https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ，1995-07（Psychological Review 102(3), 419-457）与 2016-07（Trends in Cognitive Sciences 20(7), 512-534） | 无法核（两篇均为认知神经科学理论/综述论文，无官方代码仓库） | 1995 论文开放许可：无法核（Crossref license=null，APA 传统出版版权）；2016 论文：Elsevier TDM user license 1.0（https://www.elsevier.com/tdm/userlicense/1.0/，非开源许可）；代码许可：无法核（无官方代码仓库） | 高 | CLS 是认知科学架构假设，不是本机模型不发生遗忘的成功证据（V9_RESEARCH_SURVEY §4 原话） |
| code-as-world | Code-as-World（可执行世界表示） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2608.27549 ，2026-08-27 | 无法核（arXiv 只给项目页 https://mirros-lab.github.io/code-as-world ，未给代码仓库） | 论文：CC BY-NC-SA（REPORT.md 核对结论，本轮未复核）；代码许可：无法核（核心发现循环与训练代码未发布） | 低（核心循环与训练代码未发布；渲染链路依赖外部引擎） | 核心发现循环与训练代码未发布（报告核对结论，本轮 abs 页亦无代码链接）；论文为 CC BY-NC-SA，正文与图不可商用转载；QuantiPhy 上的 SOTA 不代表 AWZ 物理一致性 |
| cosr | CoSR（Chain of Symbolic Regression） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2603.13727 ，2026-03-14 | 无法核（无代码仓库；报告核对称仓库无 LICENSE） | 论文：arXiv abs 页显示已被作者撤回（withdrawn），许可未显示（无法核）；代码许可：无法核 | 低（论文已撤回，实现不可采信） | arXiv v2 已撤回：comments 原文为『This paper needs to be retracted due to methodological flaws found in RBC case』；撤回前结论不得引用为证据；仓 |
| cscg | CSCG（Clone-Structured Graph Representations 原文） | R3 未核清单核实 | https://doi.org/10.1038/s41467-021-22559-5 ，2021-04-22（Nature Communications 12, 2392；PMCID PMC8062558） | https://github.com/vicariousinc/naturecomm_cscg | 代码仓库：MIT（vicariousinc/naturecomm_cscg，GitHub API license.key=mit）；论文：CC BY 4.0（Crossref vor 许可 creativecommons.org/licenses/by/4.0） | 高 | 离散符号房间迷宫拓扑恢复不等于高维视觉场景自动消歧 |
| cueva-wei-2018 | Cueva & Wei 2018（Emergence of Grid-like Representations in RNNs） | R3 未核清单核实 | https://arxiv.org/abs/1803.07770 ，2018-03-21（arXiv 1803.07770 v1；ICLR 2018） | 无法核（arXiv 1803.07770 摘要与 HTML 正文均未提供官方代码仓库链接；GitHub 仅见第三方复现且无许可声明） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开官方代码仓库） | 低 | 官方代码仓库与代码许可无法核；GitHub 第三方复现无许可声明，禁止使用 |
| cut3r | CUT3R (Continuous Updating Transformer for 3D Reconstruction) | R5 前沿增补补登记 | https://arxiv.org/abs/2501.12387 ，2025-01-21 | https://github.com/CUT3R/CUT3R | CC BY-NC-SA 4.0（非商业限制与相同方式共享，官方仓库 LICENSE 原文核实） | 低 | 室内外静态基准（ScanNet/Co3D）上的重建精度不代表在动漫剧烈形变下的几何鲁棒性 |
| deepjepa | DeepJEPA（把转移深度当作测试时缩放轴） | R11 补登记（S2/S5 阶段再看；REPORT.md §1.2） | https://arxiv.org/abs/2610.00368 ，2026-09-30 | 无法核（arXiv comments 只给项目页 https://deepjepa.github.io/ ，未给代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（架构思路可在 MLX 复现，但无代码） | 规划增益在种子标准差以内（报告核对结论，本轮未复核）；命题 3.1 只能事后判断，不能当作跳过规则；『接触起始处加深』是作者环境的观察，AWZ 需自行验证 |
| depth-anything-3 | Depth Anything 3 (DA3) | R5 前沿增补补登记 | https://github.com/ByteDance-Seed/Depth-Anything-3 ，2025-01-20 | https://github.com/ByteDance-Seed/Depth-Anything-3 | 代码 Apache-2.0；模型权重分级许可（Small/Base/Metric-Large/Mono-Large 为 Apache-2.0；Large/Giant/Nested 为 CC BY-NC 4.0） | 中 | 官方宣称 Large 优于 VGGT，但 Small/Base（0.08B/0.12B）小模型的位姿与深度精度是否满足高精几何需求须实测 |
| dino-wm | DINO-WM | R5 前沿增补补登记 | https://arxiv.org/abs/2411.04983 ，2024-11-07 | https://github.com/gaoyuezhou/dino_wm | MIT | 中 | 6 个简单机器人与多粒子推动环境规划成功不推出复杂日漫场景时空理解 |
| dinov3 | DINOv3 | R5 前沿增补补登记 | https://github.com/facebookresearch/dinov3 ，2025-08-19 | https://github.com/facebookresearch/dinov3 | DINOv3 License（自定义许可，非 OSI 开源！LICENSE.md 原文核实：免版税，允许衍生，但含出口管制、ITAR 限制及再分发同许可传染） | 中 | 自定义许可中的出口管制与传染性限制使其难以直接作为无限制资产嵌入商业交付物 |
| director | Director | R3 未核清单核实 | https://arxiv.org/abs/2206.04114 ，2022-06-08（arXiv 2206.04114 v1；NeurIPS 2022） | https://github.com/danijar/director | 代码仓库许可：无法核（danijar/director GitHub API license=null，仓库根目录无 LICENSE 文件）；论文：arXiv non-exclusive distribution 1.0 | 低 | danijar/director 代码许可无法核（license=null），不得假定与 dreamerv3 同为 MIT，禁止直接复制其代码 |
| dreamerv3 | DreamerV3 | R1 已核保留 | https://arxiv.org/abs/2301.04104 ，2023-01-10（v2 2024-04-17；Nature 2025） | https://github.com/danijar/dreamerv3 | MIT | 低 | 150+ 任务与 Minecraft 钻石成绩不代表 AWZ 任务收益 |
| dwc | DWC（Differentiable Weightless Controllers） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2512.01467 ，2025-12-01 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（训练依赖 CUDA；产物是 FPGA 电路，与本机 CPU/MLX 路线无交集） | 主配置约 2 nJ 每动作，且是 Vivado 估计值，不是实测（未复核）；训练依赖 CUDA；FPGA 编译产物与本机无关 |
| egnn | EGNN | R1 已核保留 | https://arxiv.org/abs/2102.09844 ，2021-02-19（v3 2022-02-16） | https://github.com/vgsatorras/egnn | MIT | 中 | N-body/QM9 成绩不代表 AWZ 对象动力学收益 |
| empiric | EMPIRIC（在物理引擎上补残差机制） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2609.35047 ，2026-09-28 | https://github.com/BasisResearch/predicators | 代码：MIT（BasisResearch/predicators 的 LICENSE.md 原文核实，Copyright 2022 Rohan Chitnis and Tom Silver，fork 自 Learning-and-Intelligent-Systems/predicators）；网站源码仓库 BasisResearch/empiric 无 LICENSE；论文许可：abs 页未显示（无法核） | 中（协议层可自实现；原实现是 PyTorch + PyBullet，不在本机跑） | 全部代理用 Claude Opus 5（闭源绑定），换模型是否成立未知；基线有三个（16/14/16）不是两个，且是按思路重实现的版本，不是原系统；同一组抽样上反复修改过的候选，成功概率估计偏乐观——独立测试集不可省；sim 五个域与单台真 |
| epinet | epinet (Epistemic Neural Networks) | R5 前沿增补补登记 | https://arxiv.org/abs/2107.08924 ，2021-07-16 | https://github.com/google-deepmind/enn | Apache-2.0 | 高 | 玩具与强化学习基准上的认知不确定性校准结论不代表在二次元复杂遮挡感知下的绝对可靠度 |
| equivariant-trust-horizons | Equivariant World Models Trust Horizons | R3 已核补入 | https://arxiv.org/abs/2606.24946 ，2026-06-23（arXiv 2606.24946 v1） | 无法核（arXiv 2606.24946 摘要与 HTML 正文均未提供官方代码仓库链接） | 论文：CC BY 4.0（arXiv 页许可链接 creativecommons.org/licenses/by/4.0/）；代码许可：无法核（无公开官方代码仓库） | 中 | 官方代码与实现许可无法核 |
| eswm | ESWM（Episodic Spatial World Model） | R3 已核补入 | https://arxiv.org/abs/2505.13696 ，2025-05-19（v1；v2 2026-02-03） | 无法核（arXiv 2505.13696 摘要、HTML 正文及作者实验室 BashivanLab GitHub 组织下均未提供官方代码仓库链接） | 论文：CC BY-NC-ND 4.0（arXiv 页许可链接）；代码许可：无法核（无公开官方代码仓库） | 中 | 官方代码仓库与代码许可无法核，不得臆测存在 MIT/Apache 实现 |
| evidence-gated-research | Evidence-Gated Research（EGR，统计受控的模型采纳层） | R11 补登记（直接借协议；REPORT.md §1.3） | https://arxiv.org/abs/2610.01751 ，2026-10-01 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（协议层，零下载；e-value 累乘是纯数值计算） | 结论依赖『条件有效性 + 可预测性』两个显式条件，不满足时 FDR 不受控；证据积累慢的世界族会让交并检验偏保守，样本效率下降；单作者预印本，未经同行评审（本轮只读 abs 页） |
| fact | FACT（Failure-Aware Causal Training for World-Action Models） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2608.10232 ，2026-08-10 | https://github.com/Bariona/FACT | 代码：Apache-2.0（仓库 README 的 License 节明写 Apache 2.0 并指向 LICENSE）；论文许可：本轮未核 | 低（底座为 5B 视频扩散模型 Wan2.2-TI2V-5B，需 GPU） | 标题里的 Causal 指注意力/条件方向，不是因果推断；底座是 5B 视频扩散模型，与本机 CPU-only 路线不兼容；bimanual 操作任务的成功率不外推到 AWZ 小房间 |
| far | FAR（Future-Aware Recall） | R3 已核补入 | https://arxiv.org/abs/2609.34677 ，2026-09-28（arXiv 2609.34677 v1） | https://github.com/sony/far | 代码仓库：CC BY-NC 4.0（Attribution-NonCommercial 4.0 International，非商业限制；GitHub API spdx_id=NOASSERTION，sony/far LICENSE 原文核实）；论文：CC BY 4.0（arXiv 页许可） | 低 | 官方仓库 sony/far 为 CC BY-NC 4.0 非商业许可，绝对不能当作 MIT/Apache 自由复制 |
| fcp-mpc | FCP-MPC（函数型共形距离场 + 采样 MPC） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2607.00776 ，2026-07-01 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（FPCA + 分位数计算是纯数值，CPU 可自实现） | 它是函数型共形安全规划，不是『适用域加弃权』；弃权分支要另立；分布偏移下只有渐近长期平均覆盖，必须报告实测覆盖率，不能只引定理；可交换性自检（时间切半比较残差统计）要自己做；越界检测靠包络不靠共形 |
| flow-equivariant-wm | Flow Equivariant World Models（FloWM） | R3 已核补入 | https://arxiv.org/abs/2601.01075 ，2026-01-03（v1；v2 2026-05-28，ICML 2026） | https://github.com/hlillemark/flowm | MIT（官方仓库 hlillemark/flowm，GitHub API license.key=mit）；论文：CC BY 4.0（arXiv 页许可） | 中 | MNIST World / Dynamic Block World 上的优势不等于 AWZ 小房间或 GridLab 实测通过 |
| genesis-world | Genesis (Genesis World) | R5 前沿增补补登记 | https://github.com/Genesis-Embodied-AI/genesis-world ，2024-12-01 | https://github.com/Genesis-Embodied-AI/genesis-world | Apache-2.0 | 高 | Metal 后端的真实速度与长时间数值稳定性未经本机实测验证 |
| geo-conformal-abstention | Geometry-Calibrated Conformal Abstention（LLM 问答弃权） | R11 补登记（排除；REPORT.md §1.2） | https://arxiv.org/abs/2604.27914 ，2026-04-30 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（对象是 LLM 问答，与本项目世界模型无关） | 对象是 LLM 问答弃权，不是世界模型适用域；报告核对指出其第二个『保证』实际是点估计：**不作为依据** |
| gradcscg | gradCSCG | R3 已核补入 | https://arxiv.org/abs/2607.12382 ，2026-07-14（arXiv 2607.12382 v1） | https://github.com/tristanstoeber/gradCSCG | MIT（官方仓库 tristanstoeber/gradCSCG，GitHub API license.key=mit）；论文：arXiv non-exclusive distribution 1.0 | 低 | 论文图像序列拓扑恢复结果不代表 AWZ/GridLab 观察收益 |
| h-jepa | H-JEPA | R1 已核保留 | https://arxiv.org/abs/2610.06805 ，2026-10-05 | https://github.com/kevinghst/H-JEPA | MIT | 低 | AntMaze 73.3% 不能推出小说世界/日漫场景收益 |
| in-place-ttt | In-Place Test-Time Training | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2604.06169 ，2026-04-07 | https://github.com/ByteDance-Seed/In-Place-TTT | Apache-2.0（仓库根目录 LICENSE 原文核实，Apache License Version 2.0） | 低（LLM 方法，与本项目只有概念联系） | LLM 方法：与本项目的显式几何核心 + 残差路线只有概念联系；128k 上下文与 4B 模型的结论不外推到 AWZ |
| jepa-anything | JEPA-Anything（正交预测因子分解 OPF） | R11 补登记（S2/S5 阶段再看；REPORT.md §1.2） | https://arxiv.org/abs/2609.20800 ，2026-09-17 | https://github.com/Gen-Verse/JEPA-Anything | Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright 2026 JEPA Anything contributors） | 中（核心库是 PyTorch；概念可在 MLX 复现，但本项目不安装） | 领域训练代码没有发布：仓库只有 jepa-anything-core/skill/recipes，checkpoint 清单仅一个未训练示例、无任何性能声明；OPF 要求因子子空间正交，不能拿来按物理机制拆残差；七个域的指标改善不外推到 A |
| kubric | Kubric | R5 前沿增补补登记 | https://arxiv.org/abs/2203.03570 ，2022-03-08 | https://github.com/google-research/kubric | Apache-2.0 | 低 | 玩具积木几何场景（Clever 风格）的物理与感知表现与日漫复杂角色场景存在显著语义鸿沟 |
| lean-verified-qec | Lean 验证的 QEC 发现（Co-Designing Quantum Codes…） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2510.20728 ，2025-10-23 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（协议层；硬门思想与语言无关，Lean 本身不在本机跑） | 一手标题是 Co-Designing Quantum Codes…，不含『Lean-verified』；报告中的名字是描述性简称（本轮已核：正文确有独立 Lean 4 验证层）；流程是人工引导的，不是全自动发现；真正的硬门是 Lean 编译 |
| lejepa | LeJEPA | R5 前沿增补补登记 | https://arxiv.org/abs/2511.08544 ，2025-11-12 | https://github.com/rbalestr-lab/lejepa | CC BY-NC 4.0（非商业限制，官方仓库 LICENSE 原文核实） | 高 | 静态图像线性探测成绩不保证视频动态时空预测精度 |
| lewm | LeWM / LeWorldModel | R1 已核保留 | https://arxiv.org/abs/2603.19312 ，2026-03-13 | https://github.com/lucas-maes/le-wm | MIT | 低 | 48× 规划加速是相对 DINO-WM 的论文数，非本机数 |
| llm-idea | LLM-IDEA（可辨识性驱动的实验代理） | R11 补登记（需用户批准安装；REPORT.md §1.2） | https://arxiv.org/abs/2610.11253 ，2026-10-08 | https://github.com/Suraskey/llm-idea | Apache-2.0（仓库 README 明写 Licensed under Apache-2.0 并指向 LICENSE） | 高（引擎只需 numpy/scipy/sympy；CPU 可跑） | 提议者（Agentic Council 及其知识图谱/编排器）未发布，只有引擎、测试台与运行记录；2026-10-08 新出，未经同行评审；引擎依赖 pysindy 作基线，安装会引入额外依赖；ODEBench 与 DiscoverPhys |
| mad-physics | MaD Physics（受限信息获取评测） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2605.10820 ，2026-05-11 | 无法核（arXiv comments 只给项目页 https://mad-physics.github.io/ ，未给代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（评测设计可自实现；代码未发布） | 是被动测量选择，不是主动干预设计；只评测 LLM 代理（Gemini 2.5/3 系列），不是 BOED 算法评测；代码未发布 |
| map-anything | MapAnything | R5 前沿增补补登记 | https://github.com/facebookresearch/map-anything ，2025-02-10 | https://github.com/facebookresearch/map-anything | 代码 Apache-2.0；HuggingFace 独立权重 facebook/map-anything-apache 为 Apache-2.0 | 低 | 自然场景上的米制重建能力不能直接外推至缺乏真实深度纹理的日漫场景 |
| mda | MDA（Model Discovery Agent） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2608.09696 ，2026-08-10 | 无法核（arXiv 摘要与 comments 均未给出代码仓库；报告核对称代理本身未发布） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（协议层可借；实现未发布） | LLM 用于假设扩展，包括初始化——不是只在后期补丁；93%/31% 出自 v1/v4，v5 已删除该表述；引用数字必须写明版本；SMC 配置反而不如 BIC，不能把 SMC 当默认选择；代理本身未发布，无法复现 |
| mechanistic-world-models | Mechanistic World Models（立场论文） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2607.12474 ，2026-07-14 | 无法核（立场论文，arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无代码） | 高（纯概念，无实现） | 立场论文：没有实验、没有代码；『可辨识性作为组织原则』是作者的主张，报告核对认为属夸大 |
| mechbench | MechBench（机制发现基准） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2609.35515 ，2026-09-28 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（基准设计可自实现；代码未发布） | 不可辨识筛查是启发式的，不是可证证书；没有评测 SRHarness（报告核对已澄清）；35.00%/13.75% 是 Codex + GPT-5.6-sol 的成绩，换代理须重测 |
| mlx-sim | mlx-sim（Apple-Silicon-first 机器人仿真平台） | R11 补登记（排除；REPORT.md §1.2） | https://github.com/novix-science/mlx-sim ，无法核（无对应论文） | https://github.com/novix-science/mlx-sim | 无法核（仓库根目录没有 LICENSE 文件；README 与 pyproject 自称 MIT，但没有许可正文可核） | 低（无许可正文；是否 MLX 原生未证实） | 根目录无 LICENSE 文件，README 徽章/自述不能当许可依据；README 的 clone 地址 github.com/mlx-sim/mlx-sim 与实际仓库不一致（文档笔误）；强调 Metal 加速不等于 MLX 原生；本轮 |
| mos-discrepancy | MOS-discrepancy（残差与参数灵敏度正交的标定框架） | R11 补登记（直接借协议；REPORT.md §1.3） | https://arxiv.org/abs/2610.09261 ，2026-10-07 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库，报告核对称无 LICENSE） | 高（协议层；灵敏度方程与采样都是 CPU 数值计算） | 恢复的是 L² 投影参数，不是物理真值；真实偏差沿灵敏度方向的分量按定义并入 φ̂，报告必须写明；合成数据由 MOS 先验自己生成，『优于 KOH』不能外推；无 LICENSE（报告核对结论），不得复制代码 |
| mujoco | MuJoCo（含 MuJoCo Warp） | R11 补登记（需用户批准安装；REPORT.md §1.2） | https://github.com/google-deepmind/mujoco ，无法核（本轮未核对论文条目日期） | https://github.com/google-deepmind/mujoco | Apache-2.0（仓库页许可标注；doc 目录文档另行采用 CC BY 4.0） | 中（macOS 预编译可用；MJWarp 需要 NVIDIA，与本机无关） | MJWarp 需要 NVIDIA GPU；MJWarp 可微仍在开发中；mjd_transitionFD 不支持 RK4（报告核对结论，本轮未复核源码）；不作为世界权威：只作离线参考仿真器与线性化对照；macOS 预编译为 universa |
| muon-moonlight | Muon Optimizer / Moonlight (Moonshot AI) | R5 前沿增补补登记 | https://github.com/MoonshotAI/Moonlight ，2025-02-15 | https://github.com/MoonshotAI/Moonlight | MIT | 极高 | 大语言模型（LLM/MoE）预训练上的 2 倍效率增益不能外推为在自回归时空世界模型上的必然加速 |
| nec | NEC（Neural Episodic Control） | R3 未核清单核实 | https://arxiv.org/abs/1703.01988 ，2017-03-06（arXiv 1703.01988 v1；ICML 2017） | 无法核（arXiv 1703.01988 摘要与 google-deepmind GitHub 组织下均未发布官方代码仓库） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开官方代码仓库） | 高 | 官方代码与代码许可无法核 |
| nested-learning | Nested Learning | R5 前沿增补补登记 | https://arxiv.org/abs/2512.24695 ，2025-12-30 | 无法核（Google 原文未发布官方开源仓库） | 无法核（论文 arXiv non-exclusive 1.0；官方代码未公开） | 高 | 理论形式化框架不等于现成工程提速结论，各层嵌套更新比例在具体任务中敏感 |
| nesys | NeSyS（Neuro-Symbolic Synergy for World Modeling） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2602.10480 ，2026-02-11 | https://github.com/tianyi-lab/NeSyS | MIT（仓库根目录 LICENSE 原文核实，Copyright (c) 2026 Tianyi Lab） | 中（规则层是纯符号计算；神经侧是 LLM 微调，本机不跑） | 『数据减半且无损』被夸大：真正起作用的是按候选集自适应的缩放（γ = 1 + max log p − min log p）；规则筛选与校准用同一开发集；ScienceWorld/WebShop/PlanCraft 的文本环境结论不外推到 A |
| osverify | OSVerify（有限专家评审下的单侧验证） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2610.18089 ，2026-10-13 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（协议层，零下载；标定是纯统计） | FNR 指误拒有效解，与我们要控制的错误接受方向相反，不能照搬其指标；主表阈值在评测集上选，只有附录 B.4 在留出集上标定——引用的必须是附录 B.4；竞赛/研究级基准结论不外推到物理机制晋升 |
| paper2agent | Paper2Agent（把论文转成 MCP 代理） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2509.06917 ，2025-09-08 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；报告核对称 Nature 版为 CC BY-NC-ND；代码许可：无法核 | 低（依赖 LLM 代理与外部代码库；本项目不引入） | 74/100 依赖代理自生成的测试，可靠性有循环论证风险；arXiv 标题与 Nature 版标题不同，引用须写清版本；Nature 版为 CC BY-NC-ND（报告核对结论，本轮未复核） |
| patchworld | PatchWorld（可执行代码世界模型的反例引导修补） | R11 补登记（直接借协议；REPORT.md §1.2） | https://arxiv.org/abs/2605.30880 ，2026-05-29 | https://github.com/HKBU-KnowComp/PatchWorld | MIT（仓库 README 的 License 节明写 MIT 并指向 LICENSE） | 中（代码是 Python，可读可借；本项目不安装） | 『零回归』实际没有实现，只要求聚合分数下降，允许局部回归——这正是要改成逐例不回归的原因；AgentGym 七个文本环境的结论不外推到 AWZ 视觉物理；轨迹数据集在 HuggingFace 单独下载（MIT），本卡未下载 |
| pg-sr | PG-SR（Prior-Guided Symbolic Regression） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2602.13021 ，2026-02-13 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（『可执行先验检查器』思想可直接用 NumPy 自实现） | 每次运行约 1785 万 token、约 10 小时（未复核，取自 REPORT.md §1.2）；没有代码、没有同行评审；『降低 Rademacher 复杂度』的表述被夸大 |
| ph-dreamer | PH-Dreamer（端口哈密顿生成动力学世界模型） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2605.18303 ，2026-05-18 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（无代码；RSSM 类架构需 GPU） | 端口哈密顿只是并行的『影子』正则，不是主架构；论文没有给出 J、R 的参数化形式；没有代码；视觉控制基准结论不外推到 AWZ |
| pi-adok | PI-ADoK（约束引导符号回归） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2507.02730 ，2025-07-03 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（思想可自实现；无代码） | 一手 arXiv 标题是 Constraint-Guided Symbolic Regression…，与 REPORT.md 所写标题（Physics-informed…）不同；以 arXiv 为准；约束是有限时间点上的经验检查，不是全域 |
| plan2explore | Plan2Explore | R3 未核清单核实 | https://arxiv.org/abs/2005.05960 ，2020-05-12（v1；v2 2020-06-30，ICML 2020） | https://github.com/ramanans1/plan2explore | Apache-2.0（官方仓库 ramanans1/plan2explore，GitHub API license.key=apache-2.0）；论文：arXiv non-exclusive distribution 1.0 | 低 | DMControl 连续控制零样本适应成绩不外推到 AWZ 场景探索 |
| pldm | PLDM (Planning with Latent Dynamics Models) | R5 前沿增补补登记 | https://arxiv.org/abs/2502.14819 ，2025-02-19 | https://github.com/vladisai/PLDM | MIT | 中 | 连续控制基准（Walker/Cheetah/Quadruped）上的离线规划表现不直接外推到影视分镜动作生成 |
| psi-sindy | PSI-SINDy（后选择推断） | R11 补登记（直接借协议；REPORT.md §1.3） | https://arxiv.org/abs/2610.11486 ，2026-10-08 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（协议层；data thinning 与区间计算是纯数值） | 精确推断就是普通 z 区间，不需要多面体条件化（报告更正）；理论只覆盖标量弱形式、固定多项式库、已知方差的 iid 高斯噪声；多状态情形只是扩展实验；代码未发布 |
| ptrm | PTRM（Probabilistic Tiny Recursive Model） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2605.19943 ，2026-05-19 | 无法核（arXiv 摘要与 comments 均未给出官方代码仓库；报告核对称只有第三方 GPL-3.0 实现） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无官方代码；第三方实现为 GPL-3.0） | 低（无官方代码；第三方 GPL-3.0 不得并入本项目） | 只有第三方 GPL-3.0 实现，不得复制进本项目；Sudoku-Extreme / Pencil Puzzle Bench 的准确率不外推到世界模型 |
| pushforward | Pushforward / Multi-step Rollout Training | R5 前沿增补补登记 | https://arxiv.org/abs/2202.03376 ，2022-02-06 | https://github.com/brandstetter-johannes/MP-Neural-PDE-Solvers | MIT | 高 | 偏微分方程（PDE）物理网格的累积误差抑制不代表多智能体复杂环境下的必然稳定 |
| py-argos | py-ARGOS（统计严谨的 ODE 自动发现包） | R11 补登记（只观察；REPORT.md §1.3） | https://arxiv.org/abs/2610.34458 ，2026-10-25 | 无法核（arXiv 摘要与 comments 均未给出代码链接；报告核对称仓库与 PyPI 复查为 404） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（仓库 404，无许可可核） | 高（纯 Python 统计流程；但包本身不可得） | 仓库与 PyPI 在报告复查时为 404，许可无法核（本轮 abs 页亦无代码链接）；『改善 SINDy 家族识别性能』只在混沌基准上，不外推到 AWZ |
| pysindy | PySINDy | R11 补登记（需用户批准安装；REPORT.md §1.2） | https://arxiv.org/abs/2111.08481 ，2021-11-12 | https://github.com/dynamicslab/pysindy | MIT（仓库根目录 LICENSE 原文核实；MIOSR 的可选依赖 gurobipy 是商用求解器，需另行取得许可） | 高（纯 NumPy/SciPy，CPU 可跑） | 弱形式靠已发布的 WeakPDELibrary，不是新方法；包含概率要自己算，包不直接给；『毫秒级』说法没有出处；TrappingSR3 不保证有界 |
| pysr | PySR（符号回归，Julia 后端） | R11 补登记（需用户批准安装；REPORT.md §1.2） | https://github.com/MilesCranmer/PySR/releases ，2026-10-19 | https://github.com/MilesCranmer/PySR | Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright 2020 Miles Cranmer） | 中（Python 前端 + Julia 后端；首次 import 会隐式下载 Julia 依赖） | 量纲约束（2023）与模板表达式（2024）不是 v2 新特性；量纲约束是软罚项，不是硬约束；首次 import 会隐式联网下载 Julia 依赖到 ~/.julia，必须用 JULIA_DEPOT_PATH 隔离；仓库已重定向到 astr |
| ref-free-sampling-mpc | Ref-free 采样 MPC（无参考轨迹的 MPPI） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2511.19204 ，2025-11-24 | 无法核（arXiv 摘要与 comments 均未给出代码仓库；报告核对称方法代码未公开） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 高（CPU 实时采样控制，思路可自实现） | 只有 30 条采样那一档有实时证据（报告核对结论）；方法代码未公开；Go2 四足与人形仿真结论不外推到 AWZ |
| repa | REPA (Representation Alignment for Generation) | R5 前沿增补补登记 | https://arxiv.org/abs/2410.06940 ，2024-10-09 | https://github.com/sihyun-yu/REPA | MIT | 高 | 图像生成扩散模型（SiT）上的 17.5 倍加速是图像生成领域的结论，在自回归潜在世界预测中收益为纯假设 |
| rlt | RLT (Run-Length Tokenization) | R5 前沿增补补登记 | https://arxiv.org/abs/2411.05222 ，2024-11-08 | https://github.com/rccchoudhury/rlt | MIT | 高 | 论文中 30%–80% token 缩减与 35% 吞吐提升来自自然视频评估，在日漫风格下收益须实测 |
| s5 | S5（Simplified State Space Layers） | R3 已核补入 | https://arxiv.org/abs/2208.04933 ，2022-08-09（v1；v2 2022-10-06；v3 2023-03-03，ICLR 2023 Oral） | https://github.com/lindermanlab/S5 | MIT（官方仓库 lindermanlab/S5，GitHub API license.key=mit）；论文：CC BY 4.0（arXiv 页许可） | 中 | Long Range Arena（LRA）成绩不代表世界模型动作条件预测收益 |
| sam2 | SAM 2.1 (Segment Anything in Images and Videos) | R5 前沿增补补登记 | https://arxiv.org/abs/2408.00714 ，2024-08-01 | https://github.com/facebookresearch/sam2 | Apache-2.0 | 低 | 自然视频中的对象跟踪能力不直接等价于动漫非真实感平涂线条场景下的边界识别率 |
| schaeffer-grid-cells | Schaeffer 等网格细胞反证 | R3 已核补入 | https://arxiv.org/abs/2312.03954 ，2023-12-06（v1；v2 2023-12-08；v3 2023-12-16） | https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction | 论文：CC BY-NC-ND 4.0（arXiv 页许可）；代码仓库许可：无法核（RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction GitHub API license=null，未提供 LICENSE 文件） | 高 | 代码仓库 FieteLab-Sorscher-2022-Reproduction 许可无法核（license=null），不得复制代码 |
| sciexplorer | SciExplorer（Agentic Exploration of Physics Models） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2509.24978 ，2025-09-29 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（依赖闭源 LLM；本项目不引入） | 依赖 GPT-5 一类闭源模型，开源模型失败（报告核对结论）；没有『主动选实验 vs 随机选实验』的消融；本轮只读 abs 页未见代码链接 |
| seq-jepa | seq-JEPA | R3 已核补入 | https://arxiv.org/abs/2505.03176 ，2025-05-06（v1；v2 2025-05-22；v3 2026-01-08，NeurIPS 2025） | https://github.com/hafezgh/seq-jepa | MIT（官方仓库 hafezgh/seq-jepa，GitHub API license.key=mit）；论文：arXiv non-exclusive distribution 1.0 | 低 | 3DIEBench/STL10 旋转与颜色等变分数不代表 AWZ 3D 场景理解 |
| simulcost | SimulCost（成本敏感的物理仿真调参基准） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2603.20253 ，2026-03-11 | https://github.com/Rose-STL-Lab/SimulCost-Bench | Apache-2.0（仓库根目录 LICENSE 原文核实，Copyright [2026] [Sicheng Lai]） | 低（基准面向 LLM 代理与 11 个仿真器；本项目不安装） | 『1.5–2.7 倍』是成功样本上的解析 FLOP 成本，不是墙钟时间；v4 已移除 CGYRO 算例（作者称因算例搜索有 bug，将加回）；结论绑定具体闭源模型版本 |
| slice | SLICE（共形 e-value 的随时有效置信序列） | R11 补登记（只观察；REPORT.md §1.3） | https://arxiv.org/abs/2610.13855 ，2026-10-09 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（协议可自实现；前提是模拟器噪声模型正确） | 要求带有设定正确噪声模型的随机模拟器；确定性模拟器不能直接用；轨迹数据必须在同一段已观测历史上做条件模拟；『集合变空即机制不足』这一用法需另行验证 |
| slim | SLIM（少动作帧下的 JEPA 可规划性） | R11 补登记（S2/S5 阶段再看；REPORT.md §1.2） | https://arxiv.org/abs/2610.03137 ，2026-10-02 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库；报告核对称代码未发布） | 中（探针与辅助损失都可在 MLX 复现；无代码） | 修复约 85% 来自编码器侧梯度，预测器侧 IDM 单独无效（p=0.13）；LeWM 在 SLIM 上 <1% 的成功率是 SLIM 基准的结论，不代表 AWZ；『动作敏感性阈值』是经验必要条件，不是充分条件 |
| slot-attention | Slot Attention | R1 已核保留 | https://arxiv.org/abs/2006.15055 ，2020-06-26（v2 2020-10-14；NeurIPS 2020） | https://github.com/google-research/google-research/tree/master/slot_attention | Apache-2.0（父仓库 google-research，API 核实） | 低 | CLEVR 对象发现成绩不代表 AWZ 感知收益 |
| slotssms | SlotSSMs (Slot State Space Models) | R5 前沿增补补登记 | https://arxiv.org/abs/2406.12272 ，2024-06-18 | https://github.com/JindongJiang/SlotSSMs | MIT | 中 | 在合成视频（Moving MNIST/OBJ3D）上的无监督对象发现不代表在二次元复杂场景下的免监督分割能力 |
| sola-2018 | Solà et al. 2018（A Micro Lie Theory for State Estimation in Robotics） | R3 未核清单核实 | https://arxiv.org/abs/1812.01537 ，2018-12-04（v1；当前 v9 2021-12-08） | https://github.com/artivis/manif | 代码仓库：MIT（artivis/manif，GitHub API license.key=mit）；论文：CC BY-NC-SA 4.0（arXiv 页许可链接 creativecommons.org/licenses/by-nc-sa/4.0/） | 高 | 解析李群与切空间一阶线性化在大角度/强非高斯多峰分布下会有截断误差，须报告条件数与退化回退 |
| srharness | SRHarness（Agentic 符号回归运行时） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2609.35501 ，2026-09-28 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（工程模式可借鉴；实现依赖 LLM 代理） | 分支与重启在消融里没有收益（报告核对结论）；符号准确率由 LLM 评审给出，不是独立测试；LLM-SRBench 数字绑定 DeepSeek-v4-flash-0731 等特定底座 |
| stable-worldmodel | Stable WorldModel | R1 已核保留 | https://arxiv.org/abs/2605.21800 ，2026-05-20（arXiv 2605.21800 v1） | https://github.com/galilai-group/stable-worldmodel | MIT | 中 | 平台上的基线排名不是 AinerZero 能力排名 |
| stochastic-phnn | SPH-NN（随机端口哈密顿神经网络） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2603.10078 ，2026-03-10 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（结构约束可在 MLX 实现；无代码） | 弱无源界是逼近存在性推论，只在连续时间、期望意义、紧集停时下成立，不证明训练出的网络满足；不得用连续时间定理代替离散积分器上的实测能量漂移 |
| supermimic | SuperMimic（单可微世界模型的人形全身控制） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2610.28480 ，2026-10-20 | 无法核（arXiv comments 只给项目页 https://supermimic.github.io ，未给代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（人形全身控制 + GPU 训练，与本项目无关） | 1000× 对比的是 SONIC 自报的 128×L40×7 天，不是同一硬件（报告核对结论）；人形动作跟踪的结论不外推到 AWZ |
| swap-equivariant-wm | SWAP（Symmetric Equivariant World-Model） | R3 已核补入 | https://arxiv.org/abs/2606.19928 ，2026-06-18（arXiv 2606.19928 v1） | 无法核（arXiv 2606.19928 HTML 正文链接项目页 https://swap-parkour.github.io/，但项目页与论文均未提供公开代码仓库链接） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开代码仓库） | 低 | 官方代码仓库与代码许可无法核 |
| t2-z | T2-z（环境潜变量的测试时优化） | R11 补登记（只观察；REPORT.md §1.2） | https://arxiv.org/abs/2610.22364 ，2026-10-15 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 低（底座是 5B 视频模型，需 GPU） | z 是点估计，不是『信念』，不能当后验用；底座为 5B 视频模型，训练需 2×24 H200 小时（报告核对结论）；摘要的 15.20→7.00 是混合单位的加权平均，不能当单一指标 |
| tapnet | TAPNet / TAPNext (Tracking Any Point) | R5 前沿增补补登记 | https://arxiv.org/abs/2306.08637 ，2023-06-15 | https://github.com/google-deepmind/tapnet | Apache-2.0（代码与全部预训练权重均在官方 README 明确声明为 Apache 2.0；数据集标注为 CC BY 4.0） | 中 | 点跟踪在丰富纹理的自然视频表现优越，在日漫大面积单色无纹理色块上易出现滑动失真 |
| tem | TEM（Tolman-Eichenbaum Machine） | R3 未核清单核实 | https://doi.org/10.1016/j.cell.2020.10.024 ，2020-11-25（线上 2020-10-22，Cell 183(5), 1249-1263.e23；PMCID PMC7707106） | https://github.com/djcrw/generalising-structural-knowledge 与 https://github.com/jbakermans/torch_tem | 论文：CC BY 4.0（Crossref vor 许可 http://creativecommons.org/licenses/by/4.0/）；官方代码仓库（djcrw/generalising-structural-knowledge 与 jbakermans/torch_tem）许可：无法核（GitHub API license=null，均未提供正式 LICENSE 文件） | 低 | djcrw/generalising-structural-knowledge 与 jbakermans/torch_tem 代码许可均为无法核（license=null），不得假定为 MIT |
| theia | Theia | R5 前沿增补补登记 | https://arxiv.org/abs/2407.20179 ，2024-07-31 | https://github.com/rai-opensource/theia | 非商业研究许可（RAI Institute License 条款 4 明文限制：The software may only be used for non-commercial research purposes） | 中 | 机器人操作任务上的表征优势不代表在三维场景几何重建与视点生成上具备同等优势 |
| thick | THICK | R1 已核保留 | https://openreview.net/forum?id=TjCDNssXKU ，ICLR 2024（spotlight） | 官方两版：https://github.com/CognitiveModeling/THICK（TF2）与 https://github.com/CognitiveModeling/thix（JAX） | MIT（CognitiveModeling/THICK）；CognitiveModeling/thix 未声明许可（未核） | 低 | ICLR 2024 spotlight ≠ 本机收益证据 |
| titans | Titans (Learning to Memorize at Test Time) | R5 前沿增补补登记 | https://arxiv.org/abs/2501.00663 ，2025-01-02 | 无法核（Google 原文未发布官方开源仓库；仅存在社区第三方实现如 lucidrains/titans-pytorch） | 无法核（论文 arXiv non-exclusive 1.0；官方代码未公开） | 中 | 长文本序列基准上的抗遗忘优势不自动外推为 3D 空间交互中的连续时空物理一致性 |
| trm | TRM（Tiny Recursive Model） | R11 补登记（S2/S5 阶段再看；REPORT.md §1.2） | https://arxiv.org/abs/2510.04871 ，2025-10-06 | 无法核（arXiv 摘要与 comments 均未给出代码仓库） | 论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库） | 中（7M 参数小网络，MLX 可复现；无官方代码） | 停机头只在训练时用，测试时固定跑满 16 步（报告核对结论）；ARC-AGI 成绩不外推到世界模型规划 |
| vjepa2 | V-JEPA 2 / 2.1 | R5 前沿增补补登记 | 2.1 论文 https://arxiv.org/abs/2603.14482 （v1 2026-03-15，v3 2026-06-11）；V-JEPA 2 https://arxiv.org/abs/2506.09985 ；仓库 2.1 发布 2026-03-16 | https://github.com/facebookresearch/vjepa2 | MIT（主体；randaugment/randerase/worker_init_fn 等文件 Apache-2.0） | 低 | EK100/SSv2 等榜单成绩不代表 AWZ 观察收益 |
| vjepa2-ac | V-JEPA 2-AC (Action-Conditioned World Model) | R5 前沿增补补登记 | https://arxiv.org/abs/2506.09985 ，2025-06-12 | https://github.com/facebookresearch/vjepa2 | MIT（部分文件 Apache-2.0） | 低 | Franka 机械臂抓放规划成功不等于日漫多角色复杂交互收益 |

---

## 2. 9.1 增补专项记录：`BlenderWorld`（评测基准，非世界模型）

- **明确定位**：`BlenderWorld` 是面向 3D 场景创作智能体的**评测基准（evaluation benchmark），不是世界模型（NOT a world model）**，严禁将其混作世界脑的预测/动力学模型基线。
- **官方来源链接（2026-10-16 只读访问）**：
  - 代码仓库：https://github.com/QwenLM/BlenderWorld （`pushed_at: 2026-10-16T09:29:13Z`）
  - 技术报告：https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf
  - HuggingFace 数据集卡：https://huggingface.co/datasets/Qwen/BlenderWorld （API：`https://huggingface.co/api/datasets/Qwen/BlenderWorld`）
  - 项目主页：https://blenderworld.github.io/
- **任务规模（核实自仓库 README 与 HF 数据集卡原文）**：
  - 总任务数：**223 个任务**（中性 ID `bw_0001` 至 `bw_0223`，跨 9 大类、22 子类）
  - 加权二元判据总数：**2,651 条二元判据**（每条判据重要性权重为 `1`、`2` 或 `3`）
  - 按输入模态分布：**纯文（Text）78** / **图文（Image + text）130** / **视频文（Video + text）15**（合计 `78 + 130 + 15 = 223`）
  - 附加规格文件：其中 **59 个任务**附带尺寸、材质或相机设置等结构化规格附件
- **计分方式（50% 判据 + 50% 八维质量）**：
  - `Rubric score = 100 × Σ(weight × pass) / Σ(weight)`（场景结构检查判据交 Agent-as-Judge，视觉判据交 VLM）
  - `Dimension score = 10 × mean(eight ratings from 1 to 10)`（8 个整体视觉质量维度，每项 1–10 分，由 VLM 评定）
  - `Final score = 0.5 × rubric score + 0.5 × dimension score`
  - 渲染与失败规则：评测器用 Cycles（`1024 × 1024`，`64 samples`）渲染 **8 个自适应视角**，每视角最多允许 **2 次修正重渲染**；缺失或失败的提交计 **0 分**并保留在所选任务分母中。
- **官方评测环境要求**：
  - 操作系统：**Linux**（Harbor 模式需支持 GPU 的 Linux 沙盒，如 Modal）
  - Python：Python 3.10+（Harbor 0.23.0 需 Python 3.12+）
  - 3D 引擎：**Blender 4.2.10**
  - 运行时与多媒体工具：Node.js 22.17.0、`ffmpeg` / `ffprobe`
  - 智能体 CLI：**Claude Code CLI 2.1.220**（捆绑生成环境另含 Codex CLI 0.147.0）
  - **付费 VLM 接口**：需配置 `BW_AGENT_JUDGE_ENDPOINT` 与 `BW_VISION_JUDGE_ENDPOINT` 等外部多模态评测接口（官方论文使用 `GPT-5.6-terra` 担任三个评测角色）。
- **代码与数据集许可（分别独立核实）**：
  - 代码仓库许可：**MIT**（`https://api.github.com/repos/QwenLM/BlenderWorld` 返回 `license.key="mit"`, `spdx_id="MIT"`）
  - 数据集许可：**MIT**（单独只读查询 `https://huggingface.co/api/datasets/Qwen/BlenderWorld` 返回 `cardData.license="mit"`、`tags` 含 `"license:mit"`，且 `https://huggingface.co/datasets/Qwen/BlenderWorld/raw/main/README.md` YAML 头部明写 `license: mit`）。
  - **严格边界**：本任务**未下载** `Qwen/BlenderWorld` 数据集、未运行 `bw download`。尽管数据集卡元数据标为 MIT，任务内具体参考图像/视频素材的使用及任何外部对标运行（`awz.V9.D6`）仍须用户单独批准。

---

## 3. R5 增补重点来源与未核项核实结论（2026-10-16 只读核实）

### 3.1 未核清单 5 项逐条核实结论
1. **Muon / Moonlight 效率数字（已核）**：
   - 来源：Moonshot AI Moonlight 技术报告与开源仓库 https://github.com/MoonshotAI/Moonlight （MIT 许可）。
   - 结论：Scaling Law 实验明确报告：在计算最优训练下，**Muon 相对 AdamW 达到约 2 倍计算效率（∼2× computational efficiency）**；MLX 0.32.4 原生内置 `mlx.optimizers.Muon`。
2. **tapnet 各检查点许可（已核）**：
   - 来源：`google-deepmind/tapnet` 官方仓库 README.md `## License and Disclaimer` 章节。
   - 结论：官方明确声明：**“All pre-trained model checkpoints released in this repository and linked from this README (including TAP-Net, TAPIR, BootsTAPIR, TAPNext, TAPNext++, and TRAJAN weights) are also licensed under Apache 2.0.”** 全部预训练模型检查点均为 **Apache 2.0** 开源。
3. **CUT3R 代码仓库与许可（已核）**：
   - 来源：arXiv 2501.12387 论文项目主页 https://cut3r.github.io/ 链接的官方仓库 https://github.com/CUT3R/CUT3R 。
   - 结论：官方仓库根目录 LICENSE 原文明确为 **Creative Commons Attribution-NonCommercial-ShareAlike 4.0 License (CC BY-NC-SA 4.0)**，具有严格的非商业与相同方式共享限制，严禁直接商用复制代码或权重。
4. **Kubric 代码与许可（已核）**：
   - 来源：官方代码仓库 https://github.com/google-research/kubric 与 GitHub API。
   - 结论：明确核实为 **Apache-2.0** 许可。
5. **AM-RADIO 许可（已核）**：
   - 来源：官方代码仓库 https://github.com/NVlabs/RADIO 根目录 LICENSE 文件。
   - 结论：明确核实为 **NVIDIA Source Code License**，第 3.3 节明文规定 **“The Work and any derivative works thereof only may be used or intended for use non-commercially ... for research or evaluation purposes only”**，带有严格的非商业限制，不可商用。

### 3.2 重点仓库许可与模型分级对照
- **Depth Anything 3（DA3）逐模型许可表（已核）**：
  - 官方仓库：https://github.com/ByteDance-Seed/Depth-Anything-3 （代码 Apache-2.0）
  - `DA3-SMALL (0.08B)` / `DA3-BASE (0.12B)`：**Apache 2.0**（强烈推荐替代非商用的 VGGT 作为 T6 位姿+深度教师）
  - `DA3METRIC-LARGE (0.35B)` / `DA3MONO-LARGE (0.35B)`：**Apache 2.0**
  - `DA3-LARGE (0.35B)` / `DA3-GIANT (1.15B)` / `DA3NESTED (1.40B)`：**CC BY-NC 4.0**（非商用限制）
- **MapAnything 权重许可（已核）**：
  - 官方代码：https://github.com/facebookresearch/map-anything （Apache-2.0）
  - 独立官方权重：HuggingFace `facebook/map-anything-apache` 明确标注 `license:apache-2.0`。
- **DINOv3 自定义许可（已核）**：
  - 官方仓库：https://github.com/facebookresearch/dinov3 （LICENSE.md）
  - 许可类型：**DINOv3 License（自定义许可，非 OSI 开源）**；免版税、允许衍生，但附加出口管制、ITAR 限制及再分发同许可传染条款；需用户单独审议。
- **SAM 2.1 许可（已核）**：
  - 官方代码与全部预训练权重均在 README 与 LICENSE 明确声明为 **Apache-2.0**。
- **Genesis World 硬件与许可（已核）**：
  - 官方仓库：https://github.com/Genesis-Embodied-AI/genesis-world （Apache-2.0）
  - 硬件支持：Quadrants 编译器支持编译至 **Apple Metal**，支持 Apple Silicon 原生 GPU 加速与自动微分。

---

## 4. 可借鉴机制汇总（全部 96 条）

- **active-inference-value-profiles**：状态相关的可复用价值档案（state-dependent value profiles）：把价值函数按状态复用，减少每个环境重新学习价值的成本；模型恢复/参数恢复作为评测协议：用已知生成模型拟合回来，报告恢复矩阵与不可分情形；给 MSG 的『机制是否够用』提供一类可复用先验的组织方式（属设计参考，不属可直接运行的算法）
- **ai-newton**：先从多实验原始数据提出可解释的物理概念，再用概念构造定律（而不是直接搜表达式）；把已发现的定律逐步推广到更大定义域（渐进泛化）
- **alder**：参数方程提议 + 数值优化拟合系数 + 独立验证器在留出数据上检验，三段分离；成本与安全感知的选择器主动查询干预，用反例更新证据账本并驱动下一次结构修订；准入由提议方看不到的留出数据决定，阈值在发现前冻结，预算内无人通过就不返回任何模型；负对照：候选库故意缺项或缺状态时，准入率应为 0（不为 0 说明晋升门在放行错误机制）
- **am-radio**：多模型特征凝聚多任务蒸馏：通过可微重加权将 CLIP、DINOv2、SAM 的互补特征无损压缩凝聚为一个全能特征空间；多教师多模态能力统一表征思想；为制作脑多视觉感知教师聚合提供学术设计参照
- **banino-2018**：利用平移与角速度输入做路径积分（path integration）并输出位置/朝向估计的任务形式化；结合 Schaeffer et al.（arXiv:2312.03954）反证审视：其网格样表征依赖特定线性层 + Dropout + L2 正则设置，因此只把路径积分误差与向量导航作指标，不把网格样激活当作架构目标
- **barrau-bonnabel-2017**：群仿射系统（group-affine systems）上的不变误差（left/right-invariant error）具有状态轨迹无关的自主误差动力学；消除了传统 EKF 因在错误状态点线性化导致的虚假可观测性与发散，保证任意轨迹附近的局部渐近稳定性；直接支撑 ARCHITECTURE_V9 S0 不变 EKF（IEKF）解析参考滤波器与已知运动学定位上界
- **blenderworld**：3D 创作交付物的『场景结构检查（对象/层级/尺寸/材质/相机/动画）+ 多视角新鲜渲染视觉评分』双路评测框架（对应 awz.V9.D1/D2）；加权二元判据（权重 1/2/3）与『缺失/失败提交计 0 分且保留在分母中』的反刷分统计规则；输入与评测 rubric 跟模型输出目录隔离（防评测标准泄露）的打包规范
- **canonicalization**：通过规范化函数将输入投影到规范坐标框架，使后续非等变任意主干网络天然保持严格群等变性；结合 NeuroGeometry 自主估计的位姿，直接将观测和地图变到重力对齐的智能体坐标系（解析 SE(2) 等变）；免除昂贵等变卷积/图网络的大量冗余参数与计算开销
- **cls**：快速非参数/稀疏情景记忆（海马体，避免灾难性干扰）与慢速结构化参数统计整合（新皮层）的双系统分工；交错回放（interleaved replay）：把情景记忆中的高价值片段渐进巩固到慢速参数模型，同时受学习保护门约束；作为 ARCHITECTURE_V9 FAST/MID/SLOW 三层记忆职责划分与 M2 记忆干扰治理的高层理论框架
- **code-as-world**：把物理构成、动力学演化与外观都写成可执行代码，作为紧凑、可量化、可控的世界抽象；提议—执行—渲染—验证—迭代的溯因式发现环；用已验证的可执行世界给 VLM 生成定量物理推理的监督数据
- **cosr**：把定律发现建模成『符号知识链』：多个有物理意义的知识单元沿逻辑逐步组合；渐进式发现路径（从开普勒第三定律到万有引力）作为评测叙事
- **cscg**：动作条件克隆隐马尔可夫模型（Action-augmented Cloned HMM）：同一观察符号绑定多个潜克隆节点以区分不同空间/上下文位置；高阶序列消歧与虚构评估（vicarious evaluation）：在不改发射矩阵前提下通过转移拓扑做捷径与回环规划；作为 S1 拓扑地图处理『相同房间/街景观察出现在不同位置（perceptual aliasing）』的理论与基线原型
- **cueva-wei-2018**：2D 竞技场内基于速度输入的循环网络空间定位基准任务与边界/网格单元响应分析方法；同受 Schaeffer et al.（arXiv:2312.03954）反证约束：网格调谐仅作事后表征探针，不作优化目标
- **cut3r**：有状态的循环持续感知范式：每接收一帧输入便增量更新持久隐状态，在统一世界坐标系下在线输出米制稠密点图；“隐状态即地图记忆”理念：支持向未观察到的虚拟视点发送探针以推断未见区域几何；自然适应无序照片集与连续视频流，提供 S1 度量地图层设计的直观参照
- **deepjepa**：权重共享的 JEPA 世界模型，把每个转移的递归深度当成内部测试时缩放轴；学习『这次转移值不值得再算一次』的判据，额外计算集中在接触起始与持续交互处
- **depth-anything-3**：多视角任意图像输入的相对深度、相机位姿（内外参）与位姿条件深度的统一多任务估计；推荐使用 Apache-2.0 许可的 DA3-Small (0.08B) 与 DA3-Base (0.12B) 彻底替代非商用限制的 VGGT-1B（CC BY-NC 4.0）；单模型同时充当 T6 阶段的位姿估计教师与多视角深度教师，简化管线依赖
- **dino-wm**：在冻结 DINOv2 局部图块特征空间上直接训练自回归潜预测器；无专家示范、无显式奖励模型、无逆动力学模型下的离线轨迹零样本视觉规划；特征空间目标距离驱动的 CEM 滚动规划方法
- **dinov3**：高质量多尺度稠密图像特征表示：蒸馏 ViT-S/16 (21M)、ViT-B/16 (86M) 等轻量主干；作为特征抽取教师基线，为后续多教师特征融合提供高质量局部语义与边缘线索；相比 DINOv2 进一步提升了密集预测（Dense Prediction）任务的下游对齐质量
- **director**：在世界模型潜空间中用目标自编码器（goal autoencoder）把历史潜态压缩量化为离散可行子目标集合；Manager 在长步幅上选潜空间子目标、Worker 在短步幅上最大化朝子目标的余弦相似度进展；作为 S2 H-JEPA 自顶向下子目标规划的层级 RL 对照参考（仅参考论文公开机制，不复制代码）
- **dreamerv3**：RSSM 式潜动态 + 想象轨迹内训练策略（只借鉴世界模型部分）；categorical 表征与跨域固定超参的鲁棒配方；action-conditioned rollout 作为现有神经预测基线对照
- **dwc**：可微符号架构：梯度端到端训练，但编译成 FPGA 兼容电路；结构稀疏可读的连线模式，可直接检查哪些输入影响控制决策
- **egnn**：E(n) 等变消息传递：旋转/平移/反射/置换等变；无高阶表示的轻量等变层（相对 TFN/SE(3)-Transformer）；对象图动力学：Delta s_i = f(s_i, neighbors, action, dt) 的等变候选
- **empiric**：残差世界模型＝基座物理引擎 + 缺失机制的代码（新力、新约束、隐藏状态 x_res）；x_res 只从可观测特征按动作更新，不读特权状态（对应 r5 §8.6 学习侧信息边界）；参数由回放损失的广义后验估计，温度 λ=max(1, E_min/N)；RMS 标准化误差 > 2 的段剔除并上报；变点检测（BOCPD）识别规律切换；K 个联合抽样上 rehearsal 规划，按谓词互信息（BALD 式）选实验
- **epinet**：认知神经网络（epinet）结构：在主干网络之外挂载极轻量认知索引网络与不可训练的高斯随机先验；仅消耗极低增量算力（<5%）即可获得匹敌大规模 Deep Ensemble 的不确定性估计能力；为 S6 主动探索（取代 Plan2Explore 昂贵集成）与带噪教师输入置信度加权提供低成本度量
- **equivariant-trust-horizons**：利用一步潜空间残差与有限时间膨胀估计构造共形校准的可信预测时域（conformal orbit-valid trust horizon）；在群对称轨道上评估世界模型 rollout 何时失真，为规划步数上限提供不确定性截断准则；可作为 S2 层级规划与想象展开步数（rollout horizon）的诊断参考
- **eswm**：从稀疏、不连续的情景转移片段（sparse transitional episodic memories）拼接空间认知地图；把认知地图视为情景记忆上的图推断而非单独训练的大网络，支持少经验预测未见转移；支撑 ARCHITECTURE_V9『一个情景记忆同时服务拓扑地图与历史检索』的设计取舍
- **evidence-gated-research**：挑战者在看到决策证据前冻结（对应 test_id 必须预先登记）；在预先声明的多个世界族上各建随时有效的 e-process，用交并检验合成 E_pers = min_e E^e；在线 FDR 控制器（e-LOND：α_t = αγ_t(R_{t−1}+1)）管住整条晋升序列的错误接受率；报告必须写明路径依赖：一次晋升会改变之后候选的生成起点
- **fact**：失败轨迹不进动作模仿损失，但仍监督『失败后的观测』与更低的进度值（损失掩码）；动作条件化的世界-动作模型：未来视频与进度值都以已执行动作为条件，方向单向；推理时用进度值给候选动作排序（可选 best-of-N）；报告时把 10 步位置误差与碰撞 F1 拆到失败子集上单列（CMFL 报告要求直接借用）
- **far**：用回忆内容对未来预测的真实效用（future prediction utility）训练多线索自适应检索权重；在时间、位姿、视觉等多检索线索间动态分配信任度，而非固定启发式规则；作为 S3 阶段相对于手工检索线索基线的学习式检索对照机制（仅借鉴论文公开算法思想）
- **fcp-mpc**：对整个预测距离场做函数型共形（FCP），得到场级下界，而不是把每障碍误差聚成一个标量分数；残差距离场经验低秩且近似时不变 → 在系数空间分解：FPCA + 高斯混合归纳共形；在线用低维向量的自适应函数型共形（AFCP）更新，保持分布偏移下的长期场覆盖；把包络作为收紧的安全约束嵌入采样 MPC（FCP-MPC）
- **flow-equivariant-wm**：以智能体为中心的潜在空间记忆随自运动（self-motion）与估计流做李群/流等变变换（flow equivariance）；视野外（out-of-view）区域在自身运动期间保持几何对齐，缓解部分可观测下的记忆漂移；支撑 ARCHITECTURE_V9 S1 度量层（重力对齐 SE(2) 自运动等变潜在网格记忆）与 G3 规范化算子
- **genesis-world**：统一多物理耦合求解：原生集成刚体、有限元（FEM）、物质点法（MPM）、光滑粒子流体（SPH）等多物理机制；Quadrants 编译器支持将 Python 内核直编至 Apple Metal，具备 Apple Silicon 原生硬件加速与自动微分能力；作为 B5 仿真数据的物理真值与可微残差来源，让 Blender 专注于高质量渲染
- **geo-conformal-abstention**：用表示几何做后验校准，决定是否弃权（post hoc，不改模型）；以预测置信度而非不可交换性分数作弃权判据（开放式生成下不可交换性分数不可算）
- **gradcscg**：可微克隆结构因果图（differentiable CSCG）接 VQ-VAE 感知前端，从连续图像序列端到端恢复认知地图拓扑；在高度混淆观察（同外观出现在不同位置）下消歧位置身份；给 S1 情景拓扑地图提供混淆观察下的拓扑消歧候选机制
- **h-jepa**：多层 action-conditioned JEPA，每层自有潜空间与时间跨度；顶层优化朝目标进展，下层把上层预测当子目标（自顶向下规划）；高层丢弃快变不可预测细节、保留慢速任务相关状态
- **in-place-ttt**：把 MLP 最后一层投影矩阵当作可更新的快权重，测试时原地更新；用与下一 token 预测对齐的目标替换 TTT 的重构目标；分块更新兼容上下文并行
- **jepa-anything**：正交预测因子分解（OPF）：把潜目标拆成互补因子，各自专用通路，再在共享预测设计中重组；跨视觉/生物/临床/控制/分子动力学/物理场/天气七个域共用一个学习原则
- **kubric**：Blender + PyBullet 的自动化多对象视频生成流水线，带全套相机机位、深度、光流、表面法线与分割真值导出机制；MOVi（Multi-Object Video）任务设计范式：无监督对象发现与几何动力学评测的标准考题构型；可直接移植其场景参数采样与真值烘焙逻辑到 B5 的现代化 Blender 4.x 生成器中
- **lean-verified-qec**：候选构造必须转成精确对象并被独立检查：搜索、精确重构、形式证明三段分离；以 Lean 4 编译作为二值硬门（『零错误、零警告、无 sorry』式），而不是让验证代理自己宣称；被排除的候选要给出 no-go 证明，与接受项一起形式化
- **lejepa**：数学证明 JEPA 潜表征的最优无塌缩目标分布是各向同性高斯分布；SIGReg（Sketched Isotropic Gaussian Regularizer）解析正则化，无需负样本、超参数或梯度截断技巧；为自监督时空潜表征提供严格的防塌缩数学基石
- **lewm**：端到端像素 JEPA：编码器 + 动作条件预测器；SIGReg（Sketched Isotropic Gaussian Regularizer）防坍塌：潜分布贴各向同性高斯；CEM 潜空间滚动规划（192 维单 token 梗）
- **llm-idea**：可辨识性引擎给出三态裁决：能力上限 / 设计类内可解 / 已证耗尽（certified exhausted）；用灵敏度矩阵诊断 + 精确符号结构检查 + 设计排序器 + 耗尽证书（符号与数值两路）；引擎内部不导入任何模型客户端（有测试强制），因此可以离线跑；Alien Universe 双体测试台：力律在可证不可辨识与可辨识两种协议间切换
- **mad-physics**：在测量质量与数量受限下评测『做信息量最大的测量再下结论』；包含被改动的物理定律（altered physical laws）以降低记忆污染；三个环境各基于一条不同物理定律；预算耗尽后必须推断定律并预测未来状态
- **map-anything**：前馈通用米制 3D 重建：支持图像与已知相机内参/位姿/粗深度作为输入直接输出对齐的米制点云；高度契合 Blender 合成场景完全可知真实内外参的几何真值对齐评估；可作为离线几何对照台与米制重建辅助教师基线
- **mda**：M-open 模型发现：LLM 提出结构扩展（含初始化），不限于预定义候选集；基于信息价值（VoI）的实验设计；对模型结构、参数与随机潜轨迹做近似贝叶斯推断；ChemBench 主实验用多起点最小二乘 + BIC 做边际似然比较
- **mechanistic-world-models**：把可复用机制放在表示、计算与学习的中心，而不是以预测映射为中心；从科学哲学推导『发现』所需的计算能力，给出机制中心世界模型的解剖结构；把机制可解释性、因果表示学习、方程发现、模块化架构视为互补成分
- **mechbench**：把『恢复现象律』与『发现机制』显式分开评测，每个任务由一个机制模型定义；机制探针（mechanism probes）：查询无法从现象律推出的内部科学后果；对规范机制做可控、科学可解释的变异，构造不熟悉变体以降低记忆污染；机制不可辨识筛查：排除存在相当竞争机制的歧义实例
- **mlx-sim**：面向 Apple Silicon 的物理仿真器，宣称 Metal GPU 加速与强化学习工作流
- **mos-discrepancy**：对多输出 ODE 的偏差项施加模型结构约束：偏差与参数灵敏度正交，防止残差吞掉参数效应；灵敏度方程与 ODE 系统联立求解（耦合初值问题）得到前向梯度；自适应 Metropolis-within-Gibbs 采样受约束的后验
- **mujoco**：通用刚体接触仿真器，可作离线参考仿真器与线性化来源（mjd_transitionFD）；预编译二进制含 macOS universal 版本（覆盖 Apple Silicon），未逐一实测 CPU 吞吐
- **muon-moonlight**：基于牛顿-舒尔茨矩阵正交化迭代的神经网络隐藏层参数优化器；Moonlight 技术报告实验严格证实：在计算最优训练设定下，Muon 相对 AdamW 实现约 2 倍计算效率（∼2× computational efficiency）；MLX 0.32.4 官方已原生内置 mlx.optimizers.Muon，可直接零依赖作为 S1/S2 训练对照臂
- **nec**：可微分神经字典（Differentiable Neural Dictionary, DND）：用按键检索的半表格非参数缓存存储慢变状态键与快速更新的值；新经历直接写入非参数缓冲区并立即可供 kNN 核加权读出，无需立刻反向传播修改主干网络权重；支撑『情景库作为非参数存储，写入不直接破坏动力学主干参数』的隔离设计
- **nested-learning**：将深度神经网络形式化为多层级嵌套优化问题，每一级拥有独立的上下文信息流与更新时间尺度；为快权重高频更新适应局部环境、慢权重低频固化跨世界常识提供严格的数学优化统一视角；从优化理论层面直接指导 S2 快速动力学层与 S3 慢速拓扑记忆层的更新解耦
- **nesys**：符号规则以 log-linear 重排给候选打分，不需要 LLM 去读规则文本；规则引导采样：优先取符号规则覆盖弱的转移，用 35–60% 训练对超过全量 SFT；两个模型交替训练：各自在对方解释不足的轨迹上更新
- **osverify**：把『提出错误』与『验证错误』解耦：提议者按层次分解搜索错误，验证者区分实质错误与轻微/幻觉错误；单侧目标：在约束误拒率（FNR）的前提下最大化无效解拒识率（TNR），把人工评审成本写进目标；接受阈值在留出集上用次序统计量标定（附录 B.4 的 FactTest 做法）
- **paper2agent**：自动分析论文与配套代码库，构建 MCP 服务器；迭代生成并运行测试来稳健化生成的 MCP
- **patchworld**：反例引导的代码修补（CEGIS 式）：把离线轨迹诱导成可检查、可回放、可局部修补的符号信念状态程序；回放式验证与模型选择；反例按类型与严重度分类（执行/接口 > 缺失隐变量 > 状态/读出不符）；『保真度 vs 决策可用性』权衡的显式报告
- **pg-sr**：把领域先验编码成可执行约束程序，作为先验约束检查器剪枝候选；先验退火约束评估（PACE）：进化阶段逐步把搜索导向科学一致区域；三阶段流水线：warm-up / evolution / refinement
- **ph-dreamer**：把循环转移建模成动作控制的能量路由（流动 + 耗散），把投影潜相空间压向更物理的结构；从本体感觉观测估计哈密顿量与功率平衡，作为热力学推理的显式信号；用能量梯度与拉格朗日乘子正则化 Actor-Critic
- **pi-adok**：把物理约束直接注入符号回归，缩小搜索空间并减少所需实验数；Metropolis-Hastings 传播参数不确定性，给出可信预测区间
- **plan2explore**：利用一步潜预测器集成的分歧度（ensemble disagreement）度量认知不确定性（epistemic uncertainty）；在世界模型想象轨迹中规划以主动最大化未来预期信息增益（先规划后探索，而非事后计算新奇度）；支撑 ARCHITECTURE_V9 S6 自驱成长与 HierarchicalPlanner / LearningProgress 接口中的主动探索信号设计
- **pldm**：无奖励离线数据上的潜在动力学模型与无模型强化学习系统对比框架；在低质量、非专家及高噪声离线轨迹下，潜在动力学模型展现出超越强化学习的分布外泛化稳健性；支持用 Blender/执行智能体生成的不完美合成轨迹训练世界模型
- **psi-sindy**：data thinning：把一条观测轨迹拆成四个互相独立、角色不同的视图，分别用于选元与推断；后选择推断同时处理选择偏差、候选项的测量误差与响应/设计的共享噪声；不可辨识的项不报告区间，视为弃权
- **ptrm**：在每次深层递归注入高斯噪声，让并行轨迹探索不同解域；用模型已有的 Q 头在轨迹间选择，无需重训或任务特定增广
- **pushforward**：多步推前（pushforward）训练技巧：在自回归时间演化中让模型循环消费自身先前的预测值作为输入计算多步损失；显式对抗长时滚动预测中的累积误差扩散与协变量偏移（covariate shift）；为 S1/S2 的 1/5/10/30 步滚动评测提供配套训练对齐基线
- **py-argos**：bootstrap ARGOS 与 Bayesian-ARGOS 两套算法统一接口；每个系数给 bootstrap 置信区间或贝叶斯可信区间，区间不含零才保留项；内置 VIF、Pareto-k、后验预测残差诊断，标记不可靠拟合
- **pysindy**：弱形式 SINDy（WeakPDELibrary）在含噪数据上做系统辨识；SR3 / MIOSR / SBR 等多种稀疏回归优化器，含不等式约束与稳定性约束；积分形式与集成（ensembling）提升真实数据上的稳健性
- **pysr**：遗传编程式符号回归，带复杂度-精度 Pareto 前沿；量纲约束（软罚项）与模板表达式（2023/2024 特性，不是 v2 新增）
- **ref-free-sampling-mpc**：在 MPPI 上用三次 Hermite 样条参数化（位置与速度控制点）；不需要参考轨迹或离线预训练，接触/离地策略自动适配任务；少样本采样即可在普通 CPU 上实时控制
- **repa**：表示对齐辅助监督：将网络中间隐藏状态线性映射后与外部冻结强教师（如 DINOv2）干净特征强制对齐；大幅加速扩散模型与生成模型的潜在收敛速度（论文报告 17.5 倍以上训练提速）；用外源感知语义锚定潜在状态空间，防止生成模型在早期陷入虚假局部解
- **rlt**：在送入视频网络前识别跨时间步完全重复的图像 patch，将其合并为单个带时序长度嵌入的 token；无需根据不同视频数据集手动微调参数，预处理开销微秒级可忽略；深度契合动漫动画（一拍二、一拍三及静止帧）多停帧特性的计算大幅降本
- **s5**：多输入多输出（MIMO）连续时间线性状态空间模型，按样本步长 Δt 离散化（ZOH/双线性）；并行关联扫描（parallel associative scan）加速长序列训练，同时天然支持显式可变步长 dt；支撑 ARCHITECTURE_V9 S2 快速层『带显式 dt 的连续时间 SSM + JEPA 目标』候选
- **sam2**：统一图像与连续视频分割架构，引入基于记忆注意力的流式记忆模块（Streaming Memory Attention）；能够在长视频中跨遮挡维持恒定对象 ID，为 S4 对象层提供天然的对象掩码与时空关联监督；支持轻量级交互提示（点、框）用于精准分割目标标注
- **schaeffer-grid-cells**：方法论反证约束：训练路径积分的深网络几乎从不自发学出六边形网格细胞，除非人为注入特定读出/带通/非负超参；把网格评分（gridness score）严格限定为事后诊断探针，绝不作为训练损失或晋升门槛；防止在 S1 空间记忆实验中用『出现网格样激活』冒充空间定位或导航能力通过
- **sciexplorer**：只用代码执行等极简工具，在没有任何领域蓝图的条件下探索未知系统；从观测动力学恢复运动方程、从期望值推断哈密顿量
- **seq-jepa**：自回归序列 JEPA：把变换不变（invariant）与变换等变（equivariant）表征分离，无需显式群正则；通过动作/视角变换序列预测同时保留对象类别不变性与位姿等变性；为 S1/S2 潜空间提供『不变语义 + 等变几何』分离表征的架构参考
- **simulcost**：把工具使用成本（仿真时间、实验资源）写进评测，而不只算 token 成本；成本解析定义、与平台无关；另有一个只能用墙钟计量的生产等离子体代码单列；比较 LLM 调参与传统扫描的精度与成本
- **slice**：每次观测都从各候选零假设重新模拟，把可预测的正得分共形化成条件 e-value，连乘成检验鞅；对参数反演得到随时有效的置信序列；集合变空可作为『现有机制不足』的信号（用法待验证）；用摊销神经似然比估计逼近 oracle 的似然比得分
- **slim**：动作敏感性探针（无需环境访问）作为经验必要条件：低于阈值的配置全部规划失败；共享头的逆动力学辅助损失，同时作用于编码器潜与预测潜，测试时丢弃该头；SLIM 推箱子基准：同一场景上成对的视觉目标与语言目标
- **slot-attention**：竞争注意力做对象绑定（slots 可交换、绑定任意对象）；无监督对象发现 + 有监督属性预测两用；感知侧对象表征（非世界模型）：给 NeuroGeometry 感知/绑定参考
- **slotssms**：对象槽注意力（Slot Attention）与结构化状态空间模型（SSM）深度融合；将视频解构为多个解耦的对象槽，每个对象槽内部维护独立的时间 SSM 状态演化；在数学上阻断对象间的信息串扰，天然符合 S4 对象层与 S2 快速动力学层的模块化隔离原则
- **sola-2018**：SO(2)/SE(2)/SO(3)/SE(3) 流形上的 Exp/Log 映射、右扰动（right-plus / right-minus）、伴随矩阵 Ad 与左右雅可比 J_r / J_l 解析公式；切空间高斯不确定性传播：协方差在李代数切空间通过雅可比做一阶合法推演，不破坏群流形约束；直接支撑 ARCHITECTURE_V9 S0 NeuroGeometry 数学核心库（G1/G2 已实现并独立复核）
- **srharness**：可组合的科学动作接口：对原始量、变换量与候选导出量统一寻址；持久科学状态：保留已评估假设并暴露紧凑的模型视图；轨迹生命周期管理：继续、分支、重启、终止
- **stable-worldmodel**：数据收集→训练→MPC 评测三段统一接口；CEM/iCEM/MPPI 等采样规划器与 JEPA 基线实现；环境因子 variation（FoV）做零样本泛化评测
- **stochastic-phnn**：用前馈网参数化哈密顿量，强制互联矩阵反对称、耗散矩阵半正定；Itô 动力学下给出期望意义、紧集停时的弱无源不等式；紧集与有限时域上的通用逼近结果
- **supermimic**：用共享动力学的单个可微世界模型摊销所有动作的学习，世界模型与跟踪策略同环训练；短程想象 rollout 上做 BPTT 给策略解析梯度
- **swap-equivariant-wm**：把机器人左右反射对称性直接嵌入潜世界模型以减少对称交互的冗余编码；印证『按世界真实物理对称性（而非过度追求完整群不变）约束潜空间』的样本效率思路
- **t2-z**：给机器人世界模型加一个可学习的环境潜变量 z，用来条件化预测；训练时两阶段交替：固定 z 学通用动力学 / 冻结模型只优化 z；测试时冻结世界模型，只用一至多次交互优化新初始化的 z
- **tapnet**：长序列任意点跟踪：TAPNext 逐帧在线跟踪，TAPNext++ 具备跨越遮挡追踪与重新检出能力；为物理运动连续性、遮挡前后的刚体时空连续性提供细粒度点对齐监督；在 S4 对象层用于检验对象移动与变形过程中的点对应一致性
- **tem**：将抽象关系结构（内嗅皮层路径积分 g）与具体感官内容（x）解耦，用 Hebbian 外积自联想记忆（海马体 p）绑定并检索；跨世界共享转移规律、仅在新环境中快速重绑定感官观察，实现零/少样本结构泛化；支撑『古代/现代/未来等不同风格世界共用底层空间几何与关系结构』的架构解耦思想
- **theia**：多视觉基础模型联合特征蒸馏：将 DINOv2、CLIP、SAM、ViT 等异构特征同时蒸馏到一个小模型中；单一紧凑视觉编码器在机器人多任务策略学习中的少样本泛化表征；在 World Mode 仅常驻一个小型编码器，降低显存与推理并发开销
- **thick**：离散潜动态 + 稀疏时域更新形成不变上下文（invariant contexts）；高层只预测上下文切换事件（自适应时间抽象）；层级预测无缝接入 MBRL/规划（论文结论，待本机验证）
- **titans**：在核心注意力架构之外独立设计长时记忆模块，在推理测试时依据惊喜度梯度（surprise gradients）自主记忆历史；情景历史的增量写入不直接改写动态主干权重，有效对准 M2 诊断提出的“长时记忆不挤占动作执行能力”；动量遗忘机制防止测试时记忆模块容量饱和
- **trm**：单个 2 层小网络在不同频率上递归精化潜状态与答案；以极少参数在小数据上超过 LLM 的 ARC-AGI 成绩
- **vjepa2**：掩码潜特征预测的自监督视频编码器；Dense Predictive Loss + Deep Self-Supervision（2.1 配方）；冻结特征作教师/感知基线（蒸馏须声明外部来源）
- **vjepa2-ac**：在冻结 V-JEPA 2 视觉表征上，用极低数据量（<62 小时无标注视频）后训练动作条件预测头；分层潜在动力学架构中动作信号注入潜状态的时空交叉注意力机制；零样本跨实验室与跨机械臂形态的具身动作规划迁移

---

## 5. 既有说明与无法核/非商业限制边界汇总

### 5.1 THICK 来源说明（r1 修正保留）
任务卡只给缩写，RFC/ARCHITECTURE_V9/全仓库无全称。经信箱问答 #121（统筹 claude）指引，原执行者独立在 OpenReview 检索核实：标题《Learning Hierarchical World Models with Adaptive Temporal Abstractions from Discrete Latent Dynamics》，作者 Gumbsch/Sajid/Martius/Butz，ICLR 2024 spotlight，https://openreview.net/forum?id=TjCDNssXKU （摘要含 THICK 全称与机制）。
**R2 复核指出「无官方代码」结论有误**：作者主页 https://cgumbsch.github.io/ 的 THICK 条目直接列出 [Code (TF2)](https://github.com/CognitiveModeling/THICK) 与 [Code (JAX)](https://github.com/CognitiveModeling/thix)，并给出项目页 https://sites.google.com/view/thick-world-models。`CognitiveModeling/THICK` README 自述为 ICLR 2024 论文的 **TensorFlow 2** 实现，GitHub API `license.key=mit`；`CognitiveModeling/thix` 描述「THICK in JAX」，GitHub API `license=null`（**未声明许可，未核**）。OpenReview 记录本身仍无代码链接。**不据此推断任一仓库在 MLX 上可安装或可运行。**

### 5.2 官方代码仓库或代码许可标注「无法核」的条目
1. `eswm`（https://arxiv.org/abs/2505.13696 ）：摘要、HTML 正文与 `BashivanLab` GitHub 组织均无该文代码仓库；论文许可为 `CC BY-NC-ND 4.0`，代码许可标 `无法核`。
2. `equivariant-trust-horizons`（https://arxiv.org/abs/2606.24946 ）：摘要与 HTML 正文均无代码仓库链接；论文许可为 `CC BY 4.0`，代码许可标 `无法核`。
3. `swap-equivariant-wm`（https://arxiv.org/abs/2606.19928 ）：项目页 https://swap-parkour.github.io/ 与论文均未放出代码仓库链接，代码许可标 `无法核`。
4. `cls`（https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ）：理论综述论文，无代码仓库；1995 年 APA 论文在 Crossref 中 `license=null`，开放许可与代码许可均标 `无法核`。
5. `nec`（https://arxiv.org/abs/1703.01988 ）：论文与 `google-deepmind` 组织下均无官方 NEC 仓库，代码许可标 `无法核`。
6. `cueva-wei-2018`（https://arxiv.org/abs/1803.07770 ）：论文摘要与 HTML 正文无官方代码链接；GitHub 上第三方复现均无许可声明，代码许可标 `无法核`。
7. `barrau-bonnabel-2017`（https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ）：纯数学控制论论文，无官方代码仓库，代码许可标 `无法核`。
8. `tem`（https://doi.org/10.1016/j.cell.2020.10.024 ）：PMC7707106 Data and Code Availability 指向 https://github.com/djcrw/generalising-structural-knowledge （TF），其 README 另指向 https://github.com/jbakermans/torch_tem （PyTorch）；经 GitHub API 核实两仓库 `license` 均为 `null`（无 `LICENSE` 文件），代码许可标 `无法核`。
9. `director`（https://arxiv.org/abs/2206.04114 ）：官方仓库 https://github.com/danijar/director 的 GitHub API `license=null` 且无 `LICENSE` 文件，代码许可标 `无法核`（不得从 `dreamerv3` 的 MIT 外推）。
10. `schaeffer-grid-cells`（https://arxiv.org/abs/2312.03954 ）：作者部分复现仓库 https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction 的 GitHub API `license=null`，代码许可标 `无法核`。
11. `banino-2018`（https://doi.org/10.1038/s41586-018-0102-6 ）：官方仓库 https://github.com/google-deepmind/grid-cells （Apache-2.0）仅含监督路径积分实验，论文中的 RL 导航智能体代码未开源（标 `无法核`）。
12. `thick`：配套 JAX 版 `thix`（https://github.com/CognitiveModeling/thix ）仓库未声明许可，标 `无法核`。
13. `canonicalization`（https://arxiv.org/abs/2211.06489 ）：论文与作者主页未发布独立开源代码仓库，代码许可标 `无法核`。
14. `titans`（https://arxiv.org/abs/2501.00663 ）：Google 原文未发布官方开源仓库，官方代码许可标 `无法核`。
15. `nested-learning`（https://arxiv.org/abs/2512.24695 ）：Google 原文未发布官方开源仓库，官方代码许可标 `无法核`。

### 5.3 官方代码仓库带有非商业限制（Non-Commercial）的条目（严禁商用复制代码或权重）
1. `far`（https://arxiv.org/abs/2609.34677 ）：`sony/far` 官方仓库 LICENSE 原文为 **CC BY-NC 4.0**。
2. `lejepa`（https://arxiv.org/abs/2511.08544 ）：`rbalestr-lab/lejepa` 官方仓库 LICENSE 原文为 **CC BY-NC 4.0**。
3. `theia`（https://arxiv.org/abs/2407.20179 ）：`rai-opensource/theia` 官方仓库 LICENSE 原文条款 4 明确限制 **Non-commercial research purposes only**。
4. `cut3r`（https://arxiv.org/abs/2501.12387 ）：`CUT3R/CUT3R` 官方仓库 LICENSE 原文为 **CC BY-NC-SA 4.0**。
5. `am-radio`（https://arxiv.org/abs/2312.06709 ）：`NVlabs/RADIO` 官方仓库 LICENSE 原文条款 3.3 明确限制 **Non-commercial use only**。
6. `depth-anything-3`：大型与嵌套模型（DA3-Large / DA3-Giant / DA3Nested）明确为 **CC BY-NC 4.0**。

---

### 5.4 r4 新增条目中代码许可标『无法核』的（共 35 条）
1. `active-inference-value-profiles`（https://link.springer.com/article/10.1007/s00422-026-01066-0）：论文：CC BY 4.0（Crossref 记录 license URL creativecommons.org/licenses/by/4.0）；代码许可：无法核（无公开代码仓库）
2. `ai-newton`（https://arxiv.org/abs/2504.01538）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
3. `alder`（https://arxiv.org/abs/2609.33728）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
4. `code-as-world`（https://arxiv.org/abs/2608.27549）：论文：CC BY-NC-SA（REPORT.md 核对结论，本轮未复核）；代码许可：无法核（核心发现循环与训练代码未发布）
5. `cosr`（https://arxiv.org/abs/2603.13727）：论文：arXiv abs 页显示已被作者撤回（withdrawn），许可未显示（无法核）；代码许可：无法核
6. `deepjepa`（https://arxiv.org/abs/2610.00368）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
7. `dwc`（https://arxiv.org/abs/2512.01467）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
8. `empiric`（https://arxiv.org/abs/2609.35047）：代码：MIT（BasisResearch/predicators 的 LICENSE.md 原文核实，Copyright 2022 Rohan Chitnis and Tom Silver，fork 自 Learning-and-Intelligent-Systems/predicators）；网站源码仓库 BasisResearch/empiric 无 LICENSE；论文许可：abs 页未显示（无法核）
9. `evidence-gated-research`（https://arxiv.org/abs/2610.01751）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
10. `fcp-mpc`（https://arxiv.org/abs/2607.00776）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
11. `geo-conformal-abstention`（https://arxiv.org/abs/2604.27914）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
12. `lean-verified-qec`（https://arxiv.org/abs/2510.20728）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
13. `mad-physics`（https://arxiv.org/abs/2605.10820）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
14. `mda`（https://arxiv.org/abs/2608.09696）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
15. `mechanistic-world-models`（https://arxiv.org/abs/2607.12474）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无代码）
16. `mechbench`（https://arxiv.org/abs/2609.35515）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
17. `mlx-sim`（https://github.com/novix-science/mlx-sim）：无法核（仓库根目录没有 LICENSE 文件；README 与 pyproject 自称 MIT，但没有许可正文可核）
18. `mos-discrepancy`（https://arxiv.org/abs/2610.09261）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库，报告核对称无 LICENSE）
19. `osverify`（https://arxiv.org/abs/2610.18089）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
20. `paper2agent`（https://arxiv.org/abs/2509.06917）：论文：arXiv abs 页未显示许可声明（无法核）；报告核对称 Nature 版为 CC BY-NC-ND；代码许可：无法核
21. `pg-sr`（https://arxiv.org/abs/2602.13021）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
22. `ph-dreamer`（https://arxiv.org/abs/2605.18303）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
23. `pi-adok`（https://arxiv.org/abs/2507.02730）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
24. `psi-sindy`（https://arxiv.org/abs/2610.11486）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
25. `ptrm`（https://arxiv.org/abs/2605.19943）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无官方代码；第三方实现为 GPL-3.0）
26. `py-argos`（https://arxiv.org/abs/2610.34458）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（仓库 404，无许可可核）
27. `ref-free-sampling-mpc`（https://arxiv.org/abs/2511.19204）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
28. `sciexplorer`（https://arxiv.org/abs/2509.24978）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
29. `slice`（https://arxiv.org/abs/2610.13855）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
30. `slim`（https://arxiv.org/abs/2610.03137）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库；报告核对称代码未发布）
31. `srharness`（https://arxiv.org/abs/2609.35501）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
32. `stochastic-phnn`（https://arxiv.org/abs/2603.10078）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
33. `supermimic`（https://arxiv.org/abs/2610.28480）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
34. `t2-z`（https://arxiv.org/abs/2610.22364）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）
35. `trm`（https://arxiv.org/abs/2510.04871）：论文：arXiv abs 页未显示许可声明（无法核）；代码许可：无法核（无公开代码仓库）

### 5.5 r4 新增条目中带非商业限制的（共 2 条；含论文许可层面的限制，严禁商用复制代码或权重）
1. `code-as-world`：论文：CC BY-NC-SA（REPORT.md 核对结论，本轮未复核）；代码许可：无法核（核心发现循环与训练代码未发布）
2. `paper2agent`：论文：arXiv abs 页未显示许可声明（无法核）；报告核对称 Nature 版为 CC BY-NC-ND；代码许可：无法核

---

## 6. 访问日期与只读声明
- r3 条目统一只读核验日期：`2026-10-16`（逐条 `access_date` 未改写）；r4 新增 45 条：`2026-10-28`。
- 全程通过 HTTP 协议只读访问公共元数据、arXiv abs 页、Crossref 记录、GitHub 仓库页与 raw 协议文件。
- **严格遵守执行层纪律**：纯 CPU 环境，未调用 GPU/MLX/torch 训练；未 clone、未下载任何模型权重、未下载任何数据集；未安装依赖、未产生任何付费调用。

## 7. r4 采纳分级（按 REPORT.md §4；仅覆盖 r4 新增 45 条）

| 级别 | 条目 |
|---|---|
| **直接借协议**（15） | `active-inference-value-profiles`、`alder`、`empiric`、`evidence-gated-research`、`fact`、`fcp-mpc`、`lean-verified-qec`、`mad-physics`、`mda`、`mechbench`、`mos-discrepancy`、`nesys`、`osverify`、`patchworld`、`psi-sindy` |
| **需用户批准安装**（4） | `llm-idea`、`mujoco`、`pysindy`、`pysr` |
| **S2/S5 阶段再看**（4） | `deepjepa`、`jepa-anything`、`slim`、`trm` |
| **只观察**（20） | `ai-newton`、`code-as-world`、`cosr`、`dwc`、`in-place-ttt`、`mechanistic-world-models`、`paper2agent`、`pg-sr`、`ph-dreamer`、`pi-adok`、`ptrm`、`py-argos`、`ref-free-sampling-mpc`、`sciexplorer`、`simulcost`、`slice`、`srharness`、`stochastic-phnn`、`supermimic`、`t2-z` |
| **排除**（2） | `geo-conformal-abstention`、`mlx-sim` |

说明：『算法自实现』在 r4 里没有独立条目——弱形式 STLSQ、参数增广滤波/低维 SMC、BIC 模型比较、Fisher 信息与 EIG 属自实现清单，不指向外部来源；`pysindy` / `pysr` / `mujoco` / `llm-idea` 归『需用户批准安装』，本卡未安装、未 clone、未下载权重。

## 8. r4 更正记录与与报告不一致处

### 8.1 已在册条目的更正（只追加，不改原结论）

**`lewm`**（2026-10-28）
1. SIGReg（Sketched Isotropic Gaussian Regularizer）出自 LeJEPA（arXiv 2511.08544，2025-11-12），不是 LeWM 本文的贡献；本条目『可借鉴机制』里列 SIGReg 时必须注明出处为 LeJEPA。
2. 仓库里没有任何 JEPA 或 SIGReg 实现可用于本项目；LeWM 仍只是 S2 的设计候选，不是『已采用』。
- 依据：reports/frontier-integration-20261027/REPORT.md §1.1 与 §1.2（2026-10-28 核对）；https://arxiv.org/abs/2511.08544

**`equivariant-trust-horizons`**（2026-10-28）
1. 乘性共形因子 γ_α ≥ 1 由构造恒成立：校准只能把证书放宽，不能收紧。论文审计集上 γ_α=1.0 只说明『原始证书在该审计协议下已保守』，不是校准收紧了界。
2. 论文漏了有限样本修正：分位数应取 ⌈(1−α)(n+1)⌉/n；n 太小时证书为空，此时宁可拒绝晋升，不得用未修正分位数。
3. 本次只读复核 arXiv 2606.24946 v1 摘要，确认 γ_α=1.0 与『50 次稳定审计零反保守违例，精确二项 95% 上界 5.8%』两项表述。
- 依据：https://arxiv.org/abs/2606.24946（2026-10-28 只读）；REPORT.md §1.2

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
