# Research Adapter Registry v0（ainerzero.V9.R1 r1 + ainerzero.V9.R3 r2 + ainerzero.V9.R5 r3 补登记，2026-10-16）

只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。
机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。
- **r1 修订（V9.R1）**：回应 R2 独立复核，修正 THICK 官方代码结论、Stable WorldModel v1 日期、V-JEPA 2.1 直链；原 r0 字节归档于 `reports/V9-R1/r0-archive/`。
- **r2 修订（V9.R3）**：保留 R1 r1 全部 8 条，按 `docs/research/V9_RESEARCH_SURVEY.md` §8 补入已核与仅标题检索 9 条，逐条核对 §8 未核清单全部 12 项，并按 9.1 增补登记 `BlenderWorld`，合计 **28 条**；原字节归档于 `reports/V9-R3/r1-archive/`。
- **r3 修订（V9.R5，二级 `gemini-k7x2`，访问日期 `2026-10-16`）**：保留 R3 全部 28 条（原字节先归档于 `reports/V9-R5/r2-archive/`，未覆盖），按 `docs/research/V9_FRONTIER_COST_SURVEY.md` §7 补登记 14 篇前沿论文（DINO-WM、V-JEPA 2-AC、PLDM、LeJEPA、解析规范化、RLT、Theia、REPA、Pushforward、epinet、Titans、Nested Learning、CUT3R、SlotSSMs）与 7 个仓库（DA3、map-anything、dinov3、sam2、tapnet、genesis-world、kubric），并逐条核对 5 项未核清单（Muon/Moonlight 效率、tapnet 检查点许可、CUT3R 许可、Kubric 许可、AM-RADIO 许可），新增 23 条，合计 **51 条**。凡官方页面/API 未提供或未声明的代码仓库与许可证一律如实标注 `无法核`，绝不猜测或外推。

## 1. 总表（51 条，与 `adapter_registry.json` 严格同步）

| ID | 条目 | 分类/来源状态 | 论文/日期（只读核实） | 仓库/代码来源 | 许可（代码 / 论文 / 数据集） | MLX 可行性 | 不可推断项（摘） |
|---|---|---|---|---|---|---|---|
| am-radio | AM-RADIO (All-in-One Model for Vision) | R5 前沿增补补登记 | https://arxiv.org/abs/2312.06709 ，2023-12-14 | https://github.com/NVlabs/RADIO | NVIDIA Source Code License（非商业限制，官方 LICENSE 原文第 3.3 节核实：The Work and any derivative works thereof only may be used or intended for use non-commercially... for research or evaluation purposes only） | 低 | NVIDIA 专有许可证明确限制仅限非商业研究或评估，衍生作品受到同等传染约束 |
| banino-2018 | Banino et al. 2018（Vector-based Navigation with Grid-like Representations） | R3 未核清单核实 | https://doi.org/10.1038/s41586-018-0102-6 ，2018-05-09（Nature 557, 429-433；PMCID PMC7619527） | https://github.com/google-deepmind/grid-cells | 代码仓库：Apache-2.0（google-deepmind/grid-cells，GitHub API license.key=apache-2.0）；论文：Springer Nature TDM（Crossref 记录）；论文中 RL 导航智能体代码未开源（无法核） | 低 | Schaeffer 等（2312.03954）已证明该文网格细胞涌现高度依赖特定人为超参，不能作为『训练路径积分必然涌现网格细胞』的依据 |
| barrau-bonnabel-2017 | Barrau & Bonnabel 2017（Invariant Extended Kalman Filter / IEKF） | R3 未核清单核实 | https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ，2014-10-06（arXiv 1410.1465 v1；v4 2015-10-19；IEEE Transactions on Automatic Control 62(4), 1797-1812, 2017-04） | 无法核（arXiv 1410.1465 与 IEEE TAC 10.1109/TAC.2016.2594085 均为控制论数学定理证明论文，未提供官方代码仓库） | 论文：arXiv non-exclusive distribution 1.0 / IEEE 出版许可（Crossref 记录 https://ieeexplore.ieee.org/Xplorehelp/downloads/license-information/IEEE.html）；代码许可：无法核（无官方代码仓库） | 高 | 官方代码与代码许可无法核 |
| blenderworld | BlenderWorld（3D 创作评测基准，非世界模型） | 9.1 增补评测基准 | https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf ，2026-10（GitHub pushed_at 2026-10-16） | https://github.com/QwenLM/BlenderWorld | 代码仓库：MIT（QwenLM/BlenderWorld，GitHub API license.key=mit）；数据集卡：MIT（HuggingFace API datasets/Qwen/BlenderWorld cardData.license=mit 与 README YAML header license: mit） | 低 | BlenderWorld 是 3D 场景创作智能体的评测基准，绝对不是世界模型（NOT a world model），不得混入世界脑预测模型基线 |
| canonicalization | Analytical Canonicalization (解析规范化) | R5 前沿增补补登记 | https://arxiv.org/abs/2211.06489 ，2022-11-12 | 无法核（论文摘要与作者主页均未发布独立公开开源代码仓库） | 无法核（论文 arXiv non-exclusive 1.0；代码许可无法核） | 高 | 几何点云与分子基准上的等变保证不代表在严重遮挡与噪点图像下的同等稳健性 |
| cls | CLS（Complementary Learning Systems 互补学习系统） | R3 未核清单核实 | https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ，1995-07（Psychological Review 102(3), 419-457）与 2016-07（Trends in Cognitive Sciences 20(7), 512-534） | 无法核（两篇均为认知神经科学理论/综述论文，无官方代码仓库） | 1995 论文开放许可：无法核（Crossref license=null，APA 传统出版版权）；2016 论文：Elsevier TDM user license 1.0（https://www.elsevier.com/tdm/userlicense/1.0/，非开源许可）；代码许可：无法核（无官方代码仓库） | 高 | CLS 是认知科学架构假设，不是本机模型不发生遗忘的成功证据（V9_RESEARCH_SURVEY §4 原话） |
| cscg | CSCG（Clone-Structured Graph Representations 原文） | R3 未核清单核实 | https://doi.org/10.1038/s41467-021-22559-5 ，2021-04-22（Nature Communications 12, 2392；PMCID PMC8062558） | https://github.com/vicariousinc/naturecomm_cscg | 代码仓库：MIT（vicariousinc/naturecomm_cscg，GitHub API license.key=mit）；论文：CC BY 4.0（Crossref vor 许可 creativecommons.org/licenses/by/4.0） | 高 | 离散符号房间迷宫拓扑恢复不等于高维视觉场景自动消歧 |
| cueva-wei-2018 | Cueva & Wei 2018（Emergence of Grid-like Representations in RNNs） | R3 未核清单核实 | https://arxiv.org/abs/1803.07770 ，2018-03-21（arXiv 1803.07770 v1；ICLR 2018） | 无法核（arXiv 1803.07770 摘要与 HTML 正文均未提供官方代码仓库链接；GitHub 仅见第三方复现且无许可声明） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开官方代码仓库） | 低 | 官方代码仓库与代码许可无法核；GitHub 第三方复现无许可声明，禁止使用 |
| cut3r | CUT3R (Continuous Updating Transformer for 3D Reconstruction) | R5 前沿增补补登记 | https://arxiv.org/abs/2501.12387 ，2025-01-21 | https://github.com/CUT3R/CUT3R | CC BY-NC-SA 4.0（非商业限制与相同方式共享，官方仓库 LICENSE 原文核实） | 低 | 室内外静态基准（ScanNet/Co3D）上的重建精度不代表在动漫剧烈形变下的几何鲁棒性 |
| depth-anything-3 | Depth Anything 3 (DA3) | R5 前沿增补补登记 | https://github.com/ByteDance-Seed/Depth-Anything-3 ，2025-01-20 | https://github.com/ByteDance-Seed/Depth-Anything-3 | 代码 Apache-2.0；模型权重分级许可（Small/Base/Metric-Large/Mono-Large 为 Apache-2.0；Large/Giant/Nested 为 CC BY-NC 4.0） | 中 | 官方宣称 Large 优于 VGGT，但 Small/Base（0.08B/0.12B）小模型的位姿与深度精度是否满足高精几何需求须实测 |
| dino-wm | DINO-WM | R5 前沿增补补登记 | https://arxiv.org/abs/2411.04983 ，2024-11-07 | https://github.com/gaoyuezhou/dino_wm | MIT | 中 | 6 个简单机器人与多粒子推动环境规划成功不推出复杂日漫场景时空理解 |
| dinov3 | DINOv3 | R5 前沿增补补登记 | https://github.com/facebookresearch/dinov3 ，2025-08-19 | https://github.com/facebookresearch/dinov3 | DINOv3 License（自定义许可，非 OSI 开源！LICENSE.md 原文核实：免版税，允许衍生，但含出口管制、ITAR 限制及再分发同许可传染） | 中 | 自定义许可中的出口管制与传染性限制使其难以直接作为无限制资产嵌入商业交付物 |
| director | Director | R3 未核清单核实 | https://arxiv.org/abs/2206.04114 ，2022-06-08（arXiv 2206.04114 v1；NeurIPS 2022） | https://github.com/danijar/director | 代码仓库许可：无法核（danijar/director GitHub API license=null，仓库根目录无 LICENSE 文件）；论文：arXiv non-exclusive distribution 1.0 | 低 | danijar/director 代码许可无法核（license=null），不得假定与 dreamerv3 同为 MIT，禁止直接复制其代码 |
| dreamerv3 | DreamerV3 | R1 已核保留 | https://arxiv.org/abs/2301.04104 ，2023-01-10（v2 2024-04-17；Nature 2025） | https://github.com/danijar/dreamerv3 | MIT | 低 | 150+ 任务与 Minecraft 钻石成绩不代表 AWZ 任务收益 |
| egnn | EGNN | R1 已核保留 | https://arxiv.org/abs/2102.09844 ，2021-02-19（v3 2022-02-16） | https://github.com/vgsatorras/egnn | MIT | 中 | N-body/QM9 成绩不代表 AWZ 对象动力学收益 |
| epinet | epinet (Epistemic Neural Networks) | R5 前沿增补补登记 | https://arxiv.org/abs/2107.08924 ，2021-07-16 | https://github.com/google-deepmind/enn | Apache-2.0 | 高 | 玩具与强化学习基准上的认知不确定性校准结论不代表在二次元复杂遮挡感知下的绝对可靠度 |
| equivariant-trust-horizons | Equivariant World Models Trust Horizons | R3 已核补入 | https://arxiv.org/abs/2606.24946 ，2026-06-23（arXiv 2606.24946 v1） | 无法核（arXiv 2606.24946 摘要与 HTML 正文均未提供官方代码仓库链接） | 论文：CC BY 4.0（arXiv 页许可链接 creativecommons.org/licenses/by/4.0/）；代码许可：无法核（无公开官方代码仓库） | 中 | 官方代码与实现许可无法核 |
| eswm | ESWM（Episodic Spatial World Model） | R3 已核补入 | https://arxiv.org/abs/2505.13696 ，2025-05-19（v1；v2 2026-02-03） | 无法核（arXiv 2505.13696 摘要、HTML 正文及作者实验室 BashivanLab GitHub 组织下均未提供官方代码仓库链接） | 论文：CC BY-NC-ND 4.0（arXiv 页许可链接）；代码许可：无法核（无公开官方代码仓库） | 中 | 官方代码仓库与代码许可无法核，不得臆测存在 MIT/Apache 实现 |
| far | FAR（Future-Aware Recall） | R3 已核补入 | https://arxiv.org/abs/2609.34677 ，2026-09-28（arXiv 2609.34677 v1） | https://github.com/sony/far | 代码仓库：CC BY-NC 4.0（Attribution-NonCommercial 4.0 International，非商业限制；GitHub API spdx_id=NOASSERTION，sony/far LICENSE 原文核实）；论文：CC BY 4.0（arXiv 页许可） | 低 | 官方仓库 sony/far 为 CC BY-NC 4.0 非商业许可，绝对不能当作 MIT/Apache 自由复制 |
| flow-equivariant-wm | Flow Equivariant World Models（FloWM） | R3 已核补入 | https://arxiv.org/abs/2601.01075 ，2026-01-03（v1；v2 2026-05-28，ICML 2026） | https://github.com/hlillemark/flowm | MIT（官方仓库 hlillemark/flowm，GitHub API license.key=mit）；论文：CC BY 4.0（arXiv 页许可） | 中 | MNIST World / Dynamic Block World 上的优势不等于 AWZ 小房间或 GridLab 实测通过 |
| genesis-world | Genesis (Genesis World) | R5 前沿增补补登记 | https://github.com/Genesis-Embodied-AI/genesis-world ，2024-12-01 | https://github.com/Genesis-Embodied-AI/genesis-world | Apache-2.0 | 高 | Metal 后端的真实速度与长时间数值稳定性未经本机实测验证 |
| gradcscg | gradCSCG | R3 已核补入 | https://arxiv.org/abs/2607.12382 ，2026-07-14（arXiv 2607.12382 v1） | https://github.com/tristanstoeber/gradCSCG | MIT（官方仓库 tristanstoeber/gradCSCG，GitHub API license.key=mit）；论文：arXiv non-exclusive distribution 1.0 | 低 | 论文图像序列拓扑恢复结果不代表 AWZ/GridLab 观察收益 |
| h-jepa | H-JEPA | R1 已核保留 | https://arxiv.org/abs/2610.06805 ，2026-10-05 | https://github.com/kevinghst/H-JEPA | MIT | 低 | AntMaze 73.3% 不能推出小说世界/日漫场景收益 |
| kubric | Kubric | R5 前沿增补补登记 | https://arxiv.org/abs/2203.03570 ，2022-03-08 | https://github.com/google-research/kubric | Apache-2.0 | 低 | 玩具积木几何场景（Clever 风格）的物理与感知表现与日漫复杂角色场景存在显著语义鸿沟 |
| lejepa | LeJEPA | R5 前沿增补补登记 | https://arxiv.org/abs/2511.08544 ，2025-11-12 | https://github.com/rbalestr-lab/lejepa | CC BY-NC 4.0（非商业限制，官方仓库 LICENSE 原文核实） | 高 | 静态图像线性探测成绩不保证视频动态时空预测精度 |
| lewm | LeWM / LeWorldModel | R1 已核保留 | https://arxiv.org/abs/2603.19312 ，2026-03-13 | https://github.com/lucas-maes/le-wm | MIT | 低 | 48× 规划加速是相对 DINO-WM 的论文数，非本机数 |
| map-anything | MapAnything | R5 前沿增补补登记 | https://github.com/facebookresearch/map-anything ，2025-02-10 | https://github.com/facebookresearch/map-anything | 代码 Apache-2.0；HuggingFace 独立权重 facebook/map-anything-apache 为 Apache-2.0 | 低 | 自然场景上的米制重建能力不能直接外推至缺乏真实深度纹理的日漫场景 |
| muon-moonlight | Muon Optimizer / Moonlight (Moonshot AI) | R5 前沿增补补登记 | https://github.com/MoonshotAI/Moonlight ，2025-02-15 | https://github.com/MoonshotAI/Moonlight | MIT | 极高 | 大语言模型（LLM/MoE）预训练上的 2 倍效率增益不能外推为在自回归时空世界模型上的必然加速 |
| nec | NEC（Neural Episodic Control） | R3 未核清单核实 | https://arxiv.org/abs/1703.01988 ，2017-03-06（arXiv 1703.01988 v1；ICML 2017） | 无法核（arXiv 1703.01988 摘要与 google-deepmind GitHub 组织下均未发布官方代码仓库） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开官方代码仓库） | 高 | 官方代码与代码许可无法核 |
| nested-learning | Nested Learning | R5 前沿增补补登记 | https://arxiv.org/abs/2512.24695 ，2025-12-30 | 无法核（Google 原文未发布官方开源仓库） | 无法核（论文 arXiv non-exclusive 1.0；官方代码未公开） | 高 | 理论形式化框架不等于现成工程提速结论，各层嵌套更新比例在具体任务中敏感 |
| plan2explore | Plan2Explore | R3 未核清单核实 | https://arxiv.org/abs/2005.05960 ，2020-05-12（v1；v2 2020-06-30，ICML 2020） | https://github.com/ramanans1/plan2explore | Apache-2.0（官方仓库 ramanans1/plan2explore，GitHub API license.key=apache-2.0）；论文：arXiv non-exclusive distribution 1.0 | 低 | DMControl 连续控制零样本适应成绩不外推到 AWZ 场景探索 |
| pldm | PLDM (Planning with Latent Dynamics Models) | R5 前沿增补补登记 | https://arxiv.org/abs/2502.14819 ，2025-02-19 | https://github.com/vladisai/PLDM | MIT | 中 | 连续控制基准（Walker/Cheetah/Quadruped）上的离线规划表现不直接外推到影视分镜动作生成 |
| pushforward | Pushforward / Multi-step Rollout Training | R5 前沿增补补登记 | https://arxiv.org/abs/2202.03376 ，2022-02-06 | https://github.com/brandstetter-johannes/MP-Neural-PDE-Solvers | MIT | 高 | 偏微分方程（PDE）物理网格的累积误差抑制不代表多智能体复杂环境下的必然稳定 |
| repa | REPA (Representation Alignment for Generation) | R5 前沿增补补登记 | https://arxiv.org/abs/2410.06940 ，2024-10-09 | https://github.com/sihyun-yu/REPA | MIT | 高 | 图像生成扩散模型（SiT）上的 17.5 倍加速是图像生成领域的结论，在自回归潜在世界预测中收益为纯假设 |
| rlt | RLT (Run-Length Tokenization) | R5 前沿增补补登记 | https://arxiv.org/abs/2411.05222 ，2024-11-08 | https://github.com/rccchoudhury/rlt | MIT | 高 | 论文中 30%–80% token 缩减与 35% 吞吐提升来自自然视频评估，在日漫风格下收益须实测 |
| s5 | S5（Simplified State Space Layers） | R3 已核补入 | https://arxiv.org/abs/2208.04933 ，2022-08-09（v1；v2 2022-10-06；v3 2023-03-03，ICLR 2023 Oral） | https://github.com/lindermanlab/S5 | MIT（官方仓库 lindermanlab/S5，GitHub API license.key=mit）；论文：CC BY 4.0（arXiv 页许可） | 中 | Long Range Arena（LRA）成绩不代表世界模型动作条件预测收益 |
| sam2 | SAM 2.1 (Segment Anything in Images and Videos) | R5 前沿增补补登记 | https://arxiv.org/abs/2408.00714 ，2024-08-01 | https://github.com/facebookresearch/sam2 | Apache-2.0 | 低 | 自然视频中的对象跟踪能力不直接等价于动漫非真实感平涂线条场景下的边界识别率 |
| schaeffer-grid-cells | Schaeffer 等网格细胞反证 | R3 已核补入 | https://arxiv.org/abs/2312.03954 ，2023-12-06（v1；v2 2023-12-08；v3 2023-12-16） | https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction | 论文：CC BY-NC-ND 4.0（arXiv 页许可）；代码仓库许可：无法核（RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction GitHub API license=null，未提供 LICENSE 文件） | 高 | 代码仓库 FieteLab-Sorscher-2022-Reproduction 许可无法核（license=null），不得复制代码 |
| seq-jepa | seq-JEPA | R3 已核补入 | https://arxiv.org/abs/2505.03176 ，2025-05-06（v1；v2 2025-05-22；v3 2026-01-08，NeurIPS 2025） | https://github.com/hafezgh/seq-jepa | MIT（官方仓库 hafezgh/seq-jepa，GitHub API license.key=mit）；论文：arXiv non-exclusive distribution 1.0 | 低 | 3DIEBench/STL10 旋转与颜色等变分数不代表 AWZ 3D 场景理解 |
| slot-attention | Slot Attention | R1 已核保留 | https://arxiv.org/abs/2006.15055 ，2020-06-26（v2 2020-10-14；NeurIPS 2020） | https://github.com/google-research/google-research/tree/master/slot_attention | Apache-2.0（父仓库 google-research，API 核实） | 低 | CLEVR 对象发现成绩不代表 AWZ 感知收益 |
| slotssms | SlotSSMs (Slot State Space Models) | R5 前沿增补补登记 | https://arxiv.org/abs/2406.12272 ，2024-06-18 | https://github.com/JindongJiang/SlotSSMs | MIT | 中 | 在合成视频（Moving MNIST/OBJ3D）上的无监督对象发现不代表在二次元复杂场景下的免监督分割能力 |
| sola-2018 | Solà et al. 2018（A Micro Lie Theory for State Estimation in Robotics） | R3 未核清单核实 | https://arxiv.org/abs/1812.01537 ，2018-12-04（v1；当前 v9 2021-12-08） | https://github.com/artivis/manif | 代码仓库：MIT（artivis/manif，GitHub API license.key=mit）；论文：CC BY-NC-SA 4.0（arXiv 页许可链接 creativecommons.org/licenses/by-nc-sa/4.0/） | 高 | 解析李群与切空间一阶线性化在大角度/强非高斯多峰分布下会有截断误差，须报告条件数与退化回退 |
| stable-worldmodel | Stable WorldModel | R1 已核保留 | https://arxiv.org/abs/2605.21800 ，2026-05-20（arXiv 2605.21800 v1） | https://github.com/galilai-group/stable-worldmodel | MIT | 中 | 平台上的基线排名不是 AinerZero 能力排名 |
| swap-equivariant-wm | SWAP（Symmetric Equivariant World-Model） | R3 已核补入 | https://arxiv.org/abs/2606.19928 ，2026-06-18（arXiv 2606.19928 v1） | 无法核（arXiv 2606.19928 HTML 正文链接项目页 https://swap-parkour.github.io/，但项目页与论文均未提供公开代码仓库链接） | 论文：arXiv non-exclusive distribution 1.0；代码许可：无法核（无公开代码仓库） | 低 | 官方代码仓库与代码许可无法核 |
| tapnet | TAPNet / TAPNext (Tracking Any Point) | R5 前沿增补补登记 | https://arxiv.org/abs/2306.08637 ，2023-06-15 | https://github.com/google-deepmind/tapnet | Apache-2.0（代码与全部预训练权重均在官方 README 明确声明为 Apache 2.0；数据集标注为 CC BY 4.0） | 中 | 点跟踪在丰富纹理的自然视频表现优越，在日漫大面积单色无纹理色块上易出现滑动失真 |
| tem | TEM（Tolman-Eichenbaum Machine） | R3 未核清单核实 | https://doi.org/10.1016/j.cell.2020.10.024 ，2020-11-25（线上 2020-10-22，Cell 183(5), 1249-1263.e23；PMCID PMC7707106） | https://github.com/djcrw/generalising-structural-knowledge 与 https://github.com/jbakermans/torch_tem | 论文：CC BY 4.0（Crossref vor 许可 http://creativecommons.org/licenses/by/4.0/）；官方代码仓库（djcrw/generalising-structural-knowledge 与 jbakermans/torch_tem）许可：无法核（GitHub API license=null，均未提供正式 LICENSE 文件） | 低 | djcrw/generalising-structural-knowledge 与 jbakermans/torch_tem 代码许可均为无法核（license=null），不得假定为 MIT |
| theia | Theia | R5 前沿增补补登记 | https://arxiv.org/abs/2407.20179 ，2024-07-31 | https://github.com/rai-opensource/theia | 非商业研究许可（RAI Institute License 条款 4 明文限制：The software may only be used for non-commercial research purposes） | 中 | 机器人操作任务上的表征优势不代表在三维场景几何重建与视点生成上具备同等优势 |
| thick | THICK | R1 已核保留 | https://openreview.net/forum?id=TjCDNssXKU ，ICLR 2024（spotlight） | 官方两版：https://github.com/CognitiveModeling/THICK（TF2）与 https://github.com/CognitiveModeling/thix（JAX） | MIT（CognitiveModeling/THICK）；CognitiveModeling/thix 未声明许可（未核） | 低 | ICLR 2024 spotlight ≠ 本机收益证据 |
| titans | Titans (Learning to Memorize at Test Time) | R5 前沿增补补登记 | https://arxiv.org/abs/2501.00663 ，2025-01-02 | 无法核（Google 原文未发布官方开源仓库；仅存在社区第三方实现如 lucidrains/titans-pytorch） | 无法核（论文 arXiv non-exclusive 1.0；官方代码未公开） | 中 | 长文本序列基准上的抗遗忘优势不自动外推为 3D 空间交互中的连续时空物理一致性 |
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

## 4. 可借鉴机制汇总（全部 51 条）

- **am-radio**：多模型特征凝聚多任务蒸馏：通过可微重加权将 CLIP、DINOv2、SAM 的互补特征无损压缩凝聚为一个全能特征空间；多教师多模态能力统一表征思想；为制作脑多视觉感知教师聚合提供学术设计参照
- **banino-2018**：利用平移与角速度输入做路径积分（path integration）并输出位置/朝向估计的任务形式化；结合 Schaeffer et al.（arXiv:2312.03954）反证审视：其网格样表征依赖特定线性层 + Dropout + L2 正则设置，因此只把路径积分误差与向量导航作指标，不把网格样激活当作架构目标
- **barrau-bonnabel-2017**：群仿射系统（group-affine systems）上的不变误差（left/right-invariant error）具有状态轨迹无关的自主误差动力学；消除了传统 EKF 因在错误状态点线性化导致的虚假可观测性与发散，保证任意轨迹附近的局部渐近稳定性；直接支撑 ARCHITECTURE_V9 S0 不变 EKF（IEKF）解析参考滤波器与已知运动学定位上界
- **blenderworld**：3D 创作交付物的『场景结构检查（对象/层级/尺寸/材质/相机/动画）+ 多视角新鲜渲染视觉评分』双路评测框架（对应 awz.V9.D1/D2）；加权二元判据（权重 1/2/3）与『缺失/失败提交计 0 分且保留在分母中』的反刷分统计规则；输入与评测 rubric 跟模型输出目录隔离（防评测标准泄露）的打包规范
- **canonicalization**：通过规范化函数将输入投影到规范坐标框架，使后续非等变任意主干网络天然保持严格群等变性；结合 NeuroGeometry 自主估计的位姿，直接将观测和地图变到重力对齐的智能体坐标系（解析 SE(2) 等变）；免除昂贵等变卷积/图网络的大量冗余参数与计算开销
- **cls**：快速非参数/稀疏情景记忆（海马体，避免灾难性干扰）与慢速结构化参数统计整合（新皮层）的双系统分工；交错回放（interleaved replay）：把情景记忆中的高价值片段渐进巩固到慢速参数模型，同时受学习保护门约束；作为 ARCHITECTURE_V9 FAST/MID/SLOW 三层记忆职责划分与 M2 记忆干扰治理的高层理论框架
- **cscg**：动作条件克隆隐马尔可夫模型（Action-augmented Cloned HMM）：同一观察符号绑定多个潜克隆节点以区分不同空间/上下文位置；高阶序列消歧与虚构评估（vicarious evaluation）：在不改发射矩阵前提下通过转移拓扑做捷径与回环规划；作为 S1 拓扑地图处理『相同房间/街景观察出现在不同位置（perceptual aliasing）』的理论与基线原型
- **cueva-wei-2018**：2D 竞技场内基于速度输入的循环网络空间定位基准任务与边界/网格单元响应分析方法；同受 Schaeffer et al.（arXiv:2312.03954）反证约束：网格调谐仅作事后表征探针，不作优化目标
- **cut3r**：有状态的循环持续感知范式：每接收一帧输入便增量更新持久隐状态，在统一世界坐标系下在线输出米制稠密点图；“隐状态即地图记忆”理念：支持向未观察到的虚拟视点发送探针以推断未见区域几何；自然适应无序照片集与连续视频流，提供 S1 度量地图层设计的直观参照
- **depth-anything-3**：多视角任意图像输入的相对深度、相机位姿（内外参）与位姿条件深度的统一多任务估计；推荐使用 Apache-2.0 许可的 DA3-Small (0.08B) 与 DA3-Base (0.12B) 彻底替代非商用限制的 VGGT-1B（CC BY-NC 4.0）；单模型同时充当 T6 阶段的位姿估计教师与多视角深度教师，简化管线依赖
- **dino-wm**：在冻结 DINOv2 局部图块特征空间上直接训练自回归潜预测器；无专家示范、无显式奖励模型、无逆动力学模型下的离线轨迹零样本视觉规划；特征空间目标距离驱动的 CEM 滚动规划方法
- **dinov3**：高质量多尺度稠密图像特征表示：蒸馏 ViT-S/16 (21M)、ViT-B/16 (86M) 等轻量主干；作为特征抽取教师基线，为后续多教师特征融合提供高质量局部语义与边缘线索；相比 DINOv2 进一步提升了密集预测（Dense Prediction）任务的下游对齐质量
- **director**：在世界模型潜空间中用目标自编码器（goal autoencoder）把历史潜态压缩量化为离散可行子目标集合；Manager 在长步幅上选潜空间子目标、Worker 在短步幅上最大化朝子目标的余弦相似度进展；作为 S2 H-JEPA 自顶向下子目标规划的层级 RL 对照参考（仅参考论文公开机制，不复制代码）
- **dreamerv3**：RSSM 式潜动态 + 想象轨迹内训练策略（只借鉴世界模型部分）；categorical 表征与跨域固定超参的鲁棒配方；action-conditioned rollout 作为现有神经预测基线对照
- **egnn**：E(n) 等变消息传递：旋转/平移/反射/置换等变；无高阶表示的轻量等变层（相对 TFN/SE(3)-Transformer）；对象图动力学：Delta s_i = f(s_i, neighbors, action, dt) 的等变候选
- **epinet**：认知神经网络（epinet）结构：在主干网络之外挂载极轻量认知索引网络与不可训练的高斯随机先验；仅消耗极低增量算力（<5%）即可获得匹敌大规模 Deep Ensemble 的不确定性估计能力；为 S6 主动探索（取代 Plan2Explore 昂贵集成）与带噪教师输入置信度加权提供低成本度量
- **equivariant-trust-horizons**：利用一步潜空间残差与有限时间膨胀估计构造共形校准的可信预测时域（conformal orbit-valid trust horizon）；在群对称轨道上评估世界模型 rollout 何时失真，为规划步数上限提供不确定性截断准则；可作为 S2 层级规划与想象展开步数（rollout horizon）的诊断参考
- **eswm**：从稀疏、不连续的情景转移片段（sparse transitional episodic memories）拼接空间认知地图；把认知地图视为情景记忆上的图推断而非单独训练的大网络，支持少经验预测未见转移；支撑 ARCHITECTURE_V9『一个情景记忆同时服务拓扑地图与历史检索』的设计取舍
- **far**：用回忆内容对未来预测的真实效用（future prediction utility）训练多线索自适应检索权重；在时间、位姿、视觉等多检索线索间动态分配信任度，而非固定启发式规则；作为 S3 阶段相对于手工检索线索基线的学习式检索对照机制（仅借鉴论文公开算法思想）
- **flow-equivariant-wm**：以智能体为中心的潜在空间记忆随自运动（self-motion）与估计流做李群/流等变变换（flow equivariance）；视野外（out-of-view）区域在自身运动期间保持几何对齐，缓解部分可观测下的记忆漂移；支撑 ARCHITECTURE_V9 S1 度量层（重力对齐 SE(2) 自运动等变潜在网格记忆）与 G3 规范化算子
- **genesis-world**：统一多物理耦合求解：原生集成刚体、有限元（FEM）、物质点法（MPM）、光滑粒子流体（SPH）等多物理机制；Quadrants 编译器支持将 Python 内核直编至 Apple Metal，具备 Apple Silicon 原生硬件加速与自动微分能力；作为 B5 仿真数据的物理真值与可微残差来源，让 Blender 专注于高质量渲染
- **gradcscg**：可微克隆结构因果图（differentiable CSCG）接 VQ-VAE 感知前端，从连续图像序列端到端恢复认知地图拓扑；在高度混淆观察（同外观出现在不同位置）下消歧位置身份；给 S1 情景拓扑地图提供混淆观察下的拓扑消歧候选机制
- **h-jepa**：多层 action-conditioned JEPA，每层自有潜空间与时间跨度；顶层优化朝目标进展，下层把上层预测当子目标（自顶向下规划）；高层丢弃快变不可预测细节、保留慢速任务相关状态
- **kubric**：Blender + PyBullet 的自动化多对象视频生成流水线，带全套相机机位、深度、光流、表面法线与分割真值导出机制；MOVi（Multi-Object Video）任务设计范式：无监督对象发现与几何动力学评测的标准考题构型；可直接移植其场景参数采样与真值烘焙逻辑到 B5 的现代化 Blender 4.x 生成器中
- **lejepa**：数学证明 JEPA 潜表征的最优无塌缩目标分布是各向同性高斯分布；SIGReg（Sketched Isotropic Gaussian Regularizer）解析正则化，无需负样本、超参数或梯度截断技巧；为自监督时空潜表征提供严格的防塌缩数学基石
- **lewm**：端到端像素 JEPA：编码器 + 动作条件预测器；SIGReg（Sketched Isotropic Gaussian Regularizer）防坍塌：潜分布贴各向同性高斯；CEM 潜空间滚动规划（192 维单 token 梗）
- **map-anything**：前馈通用米制 3D 重建：支持图像与已知相机内参/位姿/粗深度作为输入直接输出对齐的米制点云；高度契合 Blender 合成场景完全可知真实内外参的几何真值对齐评估；可作为离线几何对照台与米制重建辅助教师基线
- **muon-moonlight**：基于牛顿-舒尔茨矩阵正交化迭代的神经网络隐藏层参数优化器；Moonlight 技术报告实验严格证实：在计算最优训练设定下，Muon 相对 AdamW 实现约 2 倍计算效率（∼2× computational efficiency）；MLX 0.32.4 官方已原生内置 mlx.optimizers.Muon，可直接零依赖作为 S1/S2 训练对照臂
- **nec**：可微分神经字典（Differentiable Neural Dictionary, DND）：用按键检索的半表格非参数缓存存储慢变状态键与快速更新的值；新经历直接写入非参数缓冲区并立即可供 kNN 核加权读出，无需立刻反向传播修改主干网络权重；支撑『情景库作为非参数存储，写入不直接破坏动力学主干参数』的隔离设计
- **nested-learning**：将深度神经网络形式化为多层级嵌套优化问题，每一级拥有独立的上下文信息流与更新时间尺度；为快权重高频更新适应局部环境、慢权重低频固化跨世界常识提供严格的数学优化统一视角；从优化理论层面直接指导 S2 快速动力学层与 S3 慢速拓扑记忆层的更新解耦
- **plan2explore**：利用一步潜预测器集成的分歧度（ensemble disagreement）度量认知不确定性（epistemic uncertainty）；在世界模型想象轨迹中规划以主动最大化未来预期信息增益（先规划后探索，而非事后计算新奇度）；支撑 ARCHITECTURE_V9 S6 自驱成长与 HierarchicalPlanner / LearningProgress 接口中的主动探索信号设计
- **pldm**：无奖励离线数据上的潜在动力学模型与无模型强化学习系统对比框架；在低质量、非专家及高噪声离线轨迹下，潜在动力学模型展现出超越强化学习的分布外泛化稳健性；支持用 Blender/执行智能体生成的不完美合成轨迹训练世界模型
- **pushforward**：多步推前（pushforward）训练技巧：在自回归时间演化中让模型循环消费自身先前的预测值作为输入计算多步损失；显式对抗长时滚动预测中的累积误差扩散与协变量偏移（covariate shift）；为 S1/S2 的 1/5/10/30 步滚动评测提供配套训练对齐基线
- **repa**：表示对齐辅助监督：将网络中间隐藏状态线性映射后与外部冻结强教师（如 DINOv2）干净特征强制对齐；大幅加速扩散模型与生成模型的潜在收敛速度（论文报告 17.5 倍以上训练提速）；用外源感知语义锚定潜在状态空间，防止生成模型在早期陷入虚假局部解
- **rlt**：在送入视频网络前识别跨时间步完全重复的图像 patch，将其合并为单个带时序长度嵌入的 token；无需根据不同视频数据集手动微调参数，预处理开销微秒级可忽略；深度契合动漫动画（一拍二、一拍三及静止帧）多停帧特性的计算大幅降本
- **s5**：多输入多输出（MIMO）连续时间线性状态空间模型，按样本步长 Δt 离散化（ZOH/双线性）；并行关联扫描（parallel associative scan）加速长序列训练，同时天然支持显式可变步长 dt；支撑 ARCHITECTURE_V9 S2 快速层『带显式 dt 的连续时间 SSM + JEPA 目标』候选
- **sam2**：统一图像与连续视频分割架构，引入基于记忆注意力的流式记忆模块（Streaming Memory Attention）；能够在长视频中跨遮挡维持恒定对象 ID，为 S4 对象层提供天然的对象掩码与时空关联监督；支持轻量级交互提示（点、框）用于精准分割目标标注
- **schaeffer-grid-cells**：方法论反证约束：训练路径积分的深网络几乎从不自发学出六边形网格细胞，除非人为注入特定读出/带通/非负超参；把网格评分（gridness score）严格限定为事后诊断探针，绝不作为训练损失或晋升门槛；防止在 S1 空间记忆实验中用『出现网格样激活』冒充空间定位或导航能力通过
- **seq-jepa**：自回归序列 JEPA：把变换不变（invariant）与变换等变（equivariant）表征分离，无需显式群正则；通过动作/视角变换序列预测同时保留对象类别不变性与位姿等变性；为 S1/S2 潜空间提供『不变语义 + 等变几何』分离表征的架构参考
- **slot-attention**：竞争注意力做对象绑定（slots 可交换、绑定任意对象）；无监督对象发现 + 有监督属性预测两用；感知侧对象表征（非世界模型）：给 NeuroGeometry 感知/绑定参考
- **slotssms**：对象槽注意力（Slot Attention）与结构化状态空间模型（SSM）深度融合；将视频解构为多个解耦的对象槽，每个对象槽内部维护独立的时间 SSM 状态演化；在数学上阻断对象间的信息串扰，天然符合 S4 对象层与 S2 快速动力学层的模块化隔离原则
- **sola-2018**：SO(2)/SE(2)/SO(3)/SE(3) 流形上的 Exp/Log 映射、右扰动（right-plus / right-minus）、伴随矩阵 Ad 与左右雅可比 J_r / J_l 解析公式；切空间高斯不确定性传播：协方差在李代数切空间通过雅可比做一阶合法推演，不破坏群流形约束；直接支撑 ARCHITECTURE_V9 S0 NeuroGeometry 数学核心库（G1/G2 已实现并独立复核）
- **stable-worldmodel**：数据收集→训练→MPC 评测三段统一接口；CEM/iCEM/MPPI 等采样规划器与 JEPA 基线实现；环境因子 variation（FoV）做零样本泛化评测
- **swap-equivariant-wm**：把机器人左右反射对称性直接嵌入潜世界模型以减少对称交互的冗余编码；印证『按世界真实物理对称性（而非过度追求完整群不变）约束潜空间』的样本效率思路
- **tapnet**：长序列任意点跟踪：TAPNext 逐帧在线跟踪，TAPNext++ 具备跨越遮挡追踪与重新检出能力；为物理运动连续性、遮挡前后的刚体时空连续性提供细粒度点对齐监督；在 S4 对象层用于检验对象移动与变形过程中的点对应一致性
- **tem**：将抽象关系结构（内嗅皮层路径积分 g）与具体感官内容（x）解耦，用 Hebbian 外积自联想记忆（海马体 p）绑定并检索；跨世界共享转移规律、仅在新环境中快速重绑定感官观察，实现零/少样本结构泛化；支撑『古代/现代/未来等不同风格世界共用底层空间几何与关系结构』的架构解耦思想
- **theia**：多视觉基础模型联合特征蒸馏：将 DINOv2、CLIP、SAM、ViT 等异构特征同时蒸馏到一个小模型中；单一紧凑视觉编码器在机器人多任务策略学习中的少样本泛化表征；在 World Mode 仅常驻一个小型编码器，降低显存与推理并发开销
- **thick**：离散潜动态 + 稀疏时域更新形成不变上下文（invariant contexts）；高层只预测上下文切换事件（自适应时间抽象）；层级预测无缝接入 MBRL/规划（论文结论，待本机验证）
- **titans**：在核心注意力架构之外独立设计长时记忆模块，在推理测试时依据惊喜度梯度（surprise gradients）自主记忆历史；情景历史的增量写入不直接改写动态主干权重，有效对准 M2 诊断提出的“长时记忆不挤占动作执行能力”；动量遗忘机制防止测试时记忆模块容量饱和
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

## 6. 访问日期与只读声明
- 统一只读核验日期：`2026-10-16`。
- 全程通过 HTTP 协议只读访问公共元数据、arXiv 摘要/HTML、GitHub API 与 raw 协议文件。
- **严格遵守执行层纪律**：纯 CPU 环境，未调用 GPU/MLX/torch 训练；未 clone、未下载任何模型权重、未下载任何数据集（含 BlenderWorld/Kubric）；未安装依赖、未产生任何付费调用。
