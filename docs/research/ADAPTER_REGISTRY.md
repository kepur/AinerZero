# Research Adapter Registry v0（ainerzero.V9.R1 r1 + ainerzero.V9.R3 r2 补登记，2026-10-16）

只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。
机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。
- **r1 修订（V9.R1）**：回应 R2 独立复核，修正 THICK 官方代码结论、Stable WorldModel v1 日期、V-JEPA 2.1 直链；原 r0 字节归档于 `reports/V9-R1/r0-archive/`。
- **r2 修订（V9.R3，二级 `antigravity-7c1e`，访问日期 `2026-10-16`）**：保留 R1 r1 全部 8 条（原字节先归档于 `reports/V9-R3/r1-archive/`，未覆盖），按 `docs/research/V9_RESEARCH_SURVEY.md` §8 补入已核与仅标题检索来源（`gradCSCG`、`ESWM`、`FAR`、`Flow Equivariant WM`、`Schaeffer 等网格细胞反证`、`seq-JEPA`、`Equivariant WM Trust Horizons`、`S5`、`SWAP` 共 9 条），逐条核对 §8 未核清单全部 12 项（新增 `CSCG 原文`、`TEM`、`CLS`、`NEC`、`Banino 2018`、`Cueva & Wei 2018`、`Plan2Explore`、`Director`、`Solà 2018`、`Barrau & Bonnabel 2017` 共 10 条，连同已核保留的 `THICK`、`Slot Attention` 共 12 条），并按 **9.1 增补**登记 `BlenderWorld`（评测基准，非世界模型），合计 **28 条**。凡官方页面/API 未提供或未声明的代码仓库与许可证一律如实标注 `无法核`，绝不猜测或外推。

## 1. 总表（28 条，与 `adapter_registry.json` 严格同步）

| ID | 条目 | 分类/来源状态 | 论文/日期（只读核实） | 仓库/代码来源 | 许可（代码 / 论文 / 数据集） | MLX 可行性 | 不可推断项（摘） |
|---|---|---|---|---|---|---|---|
| h-jepa | H-JEPA | R1 已核 | https://arxiv.org/abs/2610.06805 ，2026-10-05（v1） | https://github.com/kevinghst/H-JEPA | MIT | 低（PyTorch+CUDA，需重写） | AntMaze 73.3%≠本机收益；CUDA 代码不即插即用 |
| lewm | LeWM | R1 已核 | https://arxiv.org/abs/2603.19312 ，2026-03-13（v3 06-03） | https://github.com/lucas-maes/le-wm | MIT | 低（PyTorch，需重写） | 48×加速是论文数；不保证 C0 分数 |
| vjepa2 | V-JEPA 2/2.1 | R1 已核 | 2.1 论文 https://arxiv.org/abs/2603.14482 （v1 2026-03-15，v3 2026-06-11）；V-JEPA 2 https://arxiv.org/abs/2506.09985 ；仓库 2.1 发布 2026-03-16 | https://github.com/facebookresearch/vjepa2 | MIT（部分文件 Apache-2.0） | 低（decord 不支持 macOS；权重仅作教师） | 榜单成绩≠AWZ 收益；冻结特征≠已理解；无 Release 记录 |
| dreamerv3 | DreamerV3 | R1 已核 | https://arxiv.org/abs/2301.04104 ，2023-01-10（Nature 2025） | https://github.com/danijar/dreamerv3 | MIT | 低（JAX 栈；仅思想与基线） | 不把整套 RL 搬进世界脑 |
| stable-worldmodel | Stable WorldModel | R1 已核 | https://arxiv.org/abs/2605.21800 ，**2026-05-20**（v1） | https://github.com/galilai-group/stable-worldmodel | MIT | 中（评测 harness 思想；全栈太重） | 平台排名≠我方能力；各环境许可另查 |
| egnn | EGNN | R1 已核 | https://arxiv.org/abs/2102.09844 ，2021-02-19（v3） | https://github.com/vgsatorras/egnn | MIT | 中（小而干净；需移植验证） | 真值位置输入会泄漏；不拿 Blender 真值冒充视觉 |
| slot-attention | Slot Attention | §8 未核→已核（R1） | https://arxiv.org/abs/2006.15055 ，2020-06-26（NeurIPS 2020） | https://github.com/google-research/google-research/tree/master/slot_attention | Apache-2.0（父仓库） | 低（TF 栈；仅思想） | CLEVR 成绩≠感知收益；ARI 不可比 |
| thick | THICK | §8 未核→已核（R1 r1） | ICLR 2024 spotlight（https://openreview.net/forum?id=TjCDNssXKU） | 官方两版：https://github.com/CognitiveModeling/THICK（TF2）与 https://github.com/CognitiveModeling/thix（JAX） | THICK=MIT；thix 未声明（未核/无法核） | 低（TF2/JAX 栈；机制参考，需重写） | 找到实现≠MLX 可安装；thix 许可未核 |
| gradcscg | gradCSCG | §8 已核（R3 新增） | https://arxiv.org/abs/2607.12382 ，2026-07-14（v1） | https://github.com/tristanstoeber/gradCSCG （另含 https://github.com/SynapticSage/cscg_toolkit ） | 代码 MIT（API 核实）；论文 arXiv non-exclusive 1.0 | 低（PyTorch，需 MLX 重写） | 图像拓扑恢复≠AWZ 收益；VQ-VAE 前端不替代受限观察契约 |
| eswm | ESWM | §8 已核（R3 新增） | https://arxiv.org/abs/2505.13696 ，2025-05-19（v1；v2 2026-02-03） | 无法核（arXiv 2505.13696 摘要、HTML 正文及作者实验室 BashivanLab GitHub 组织下均未提供官方代码仓库链接） | 论文 CC BY-NC-ND 4.0；代码许可：无法核 | 中（图推断思想轻量，需自写） | 官方代码与代码许可无法核；CC BY-NC-ND 4.0 不得直接抄图表原文 |
| far | FAR（Future-Aware Recall） | §8 已核（R3 新增） | https://arxiv.org/abs/2609.34677 ，2026-09-28（v1） | https://github.com/sony/far （项目页 https://1202kbs.github.io/FAR-Project-Page/ ） | **代码 CC BY-NC 4.0（非商业限制，LICENSE 原文）**；论文 CC BY 4.0 | 低（PyTorch 且代码带非商业限制，禁复制代码） | sony/far 为 CC BY-NC 4.0 非商业许可，严禁当作 MIT 复制代码或权重 |
| flow-equivariant-wm | Flow Equivariant World Models（FloWM） | §8 已核（R3 新增） | https://arxiv.org/abs/2601.01075 ，2026-01-03（v1；v2 2026-05-28，ICML 2026） | https://github.com/hlillemark/flowm （项目页 https://flowequivariantworldmodels.github.io/ ） | 代码 MIT（API 核实）；论文 CC BY 4.0 | 中（PyTorch；SE(2) 伴随重采样可在 CPU/MLX 自写） | MNIST/Block World 成绩≠AWZ 通过；网格重采样有插值耗散与边界误差 |
| schaeffer-grid-cells | Schaeffer 等网格细胞反证 | §8 已核（R3 新增） | https://arxiv.org/abs/2312.03954 ，2023-12-06（v1；v3 2023-12-16） | https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction （作者部分复现仓库） | 论文 CC BY-NC-ND 4.0；代码仓库许可：**无法核**（GitHub API `license=null`） | 高（作为方法论反证与诊断约束，零代码依赖） | 仓库许可无法核，禁复制代码；网格调谐只作事后探针、绝不作目标 |
| seq-jepa | seq-JEPA | §8 标题→R3 已核 | https://arxiv.org/abs/2505.03176 ，2025-05-06（v1；v3 2026-01-08，NeurIPS 2025） | https://github.com/hafezgh/seq-jepa （项目页 https://hafezgh.github.io/seq-jepa/ ） | 代码 MIT（API 核实）；论文 arXiv non-exclusive 1.0 | 低（PyTorch；机制可借鉴，需重写） | 3DIEBench/STL10 成绩≠AWZ 3D 理解；代码 MIT 不外推到衍生数据集 |
| equivariant-trust-horizons | Equivariant WM Trust Horizons | §8 标题→R3 已核 | https://arxiv.org/abs/2606.24946 ，2026-06-23（v1） | 无法核（arXiv 2606.24946 摘要与 HTML 正文均未提供官方代码仓库链接） | 论文 CC BY 4.0；代码许可：无法核 | 中（共形校准公式轻量，可自写） | 官方代码与许可无法核；理想群对称审计集结论不外推到非对称接触环境 |
| s5 | S5（Simplified State Space Layers） | §3 / §8 已核（R3 补入） | https://arxiv.org/abs/2208.04933 ，2022-08-09（v1；v3 2023-03-03，ICLR 2023 Oral） | https://github.com/lindermanlab/S5 | 代码 MIT（API 核实）；论文 CC BY 4.0 | 中（JAX 栈；对角 MIMO SSM + 显式 `dt` 可在 MLX 重写） | LRA 成绩≠世界模型收益；不规则 `dt` 下的历史干扰仍须同表对照 |
| swap-equivariant-wm | SWAP | §8 标题→R3 已核 | https://arxiv.org/abs/2606.19928 ，2026-06-18（v1） | 无法核（arXiv 2606.19928 HTML 正文链接项目页 https://swap-parkour.github.io/ ，但项目页与论文均未提供公开代码仓库链接） | 论文 arXiv non-exclusive 1.0；代码许可：无法核 | 低（无公开代码，四足跑酷控制） | 官方代码与许可无法核；机器人跑酷成绩与 AWZ 无关 |
| cscg | CSCG 原文（George et al. 2021） | §8 未核→R3 已核 | https://doi.org/10.1038/s41467-021-22559-5 ，2021-04-22（Nature Comms 12, 2392；PMC8062558） | https://github.com/vicariousinc/naturecomm_cscg | 代码 MIT（API 核实）；论文 CC BY 4.0 | 高（Python/NumPy/Cython 稀疏矩阵 EM，易自写） | 离散符号拓扑恢复≠高维视觉消歧；离线 EM 不自动解决在线记忆干扰 |
| tem | TEM（Whittington et al. 2020） | §8 未核→R3 已核 | https://doi.org/10.1016/j.cell.2020.10.024 ，2020-11-25（线上 2020-10-22，Cell；PMC7707106） | 官方 TF：https://github.com/djcrw/generalising-structural-knowledge ；PyTorch：https://github.com/jbakermans/torch_tem | 论文 CC BY 4.0；**两个官方关联代码仓库许可均：无法核（GitHub API `license=null`，无 LICENSE 文件）** | 低（TF/PyTorch 且代码许可无法核，禁复制代码） | 两个代码仓库均无 LICENSE 文件（无法核），严禁假定 MIT 或复制代码 |
| cls | CLS（McClelland 1995; Kumaran 2016） | §8 未核→R3 已核 | https://doi.org/10.1037/0033-295X.102.3.419 （1995-07）与 https://doi.org/10.1016/j.tics.2016.05.004 （2016-07） | 无法核（两篇均为认知神经科学理论/综述论文，无官方代码仓库） | 1995 开放许可：无法核（APA 传统版权）；2016：Elsevier TDM 1.0；代码许可：无法核 | 高（纯架构分工假设，无第三方代码依赖） | CLS 是架构假设而非成功证据；1995 开放许可与代码均无法核 |
| nec | NEC（Pritzel et al. 2017） | §8 未核→R3 已核 | https://arxiv.org/abs/1703.01988 ，2017-03-06（v1，ICML 2017） | 无法核（arXiv 1703.01988 摘要与 google-deepmind GitHub 组织下均未发布官方代码仓库） | 论文 arXiv non-exclusive 1.0；代码许可：无法核 | 高（DND 键值核检索极易在 CPU/MLX 独立实现） | 官方代码与许可无法核；Atari 早期得分≠世界模型历史读回通过 |
| banino-2018 | Banino et al. 2018 | §8 未核→R3 已核 | https://doi.org/10.1038/s41586-018-0102-6 ，2018-05-09（Nature 557, 429-433；PMC7619527） | https://github.com/google-deepmind/grid-cells （仅含监督路径积分部分） | 监督代码 Apache-2.0（API 核实）；论文 Springer TDM；**RL 导航代码未开源（无法核）** | 低（TF 1.x + Sonnet 旧栈；本仓用李群解析核心） | 受 Schaeffer 2023 反证约束（网格涌现依赖特定超参）；RL 导航部分代码无法核 |
| cueva-wei-2018 | Cueva & Wei 2018 | §8 未核→R3 已核 | https://arxiv.org/abs/1803.07770 ，2018-03-21（v1，ICLR 2018） | 无法核（arXiv 1803.07770 摘要与 HTML 正文均未提供官方代码仓库链接；GitHub 仅见第三方复现且无许可声明） | 论文 arXiv non-exclusive 1.0；代码许可：无法核 | 低（无官方代码；本仓不用盲 RNN 做路径积分） | 官方代码与许可无法核；第三方复现无许可禁碰；受 Schaeffer 2023 反证约束 |
| plan2explore | Plan2Explore（Sekar et al. 2020） | §8 未核→R3 已核 | https://arxiv.org/abs/2005.05960 ，2020-05-12（v1；v2 2020-06-30，ICML 2020） | https://github.com/ramanans1/plan2explore （项目页 https://ramanans1.github.io/plan2explore/ ） | 代码 Apache-2.0（API 核实）；论文 arXiv non-exclusive 1.0 | 低（TF 栈；潜预测集成分歧度留 S6 用 MLX 自写） | DMControl 探索成绩≠AWZ 收益；分歧度须配学习进展以防白噪陷阱 |
| director | Director（Hafner et al. 2022） | §8 未核→R3 已核 | https://arxiv.org/abs/2206.04114 ，2022-06-08（v1，NeurIPS 2022） | https://github.com/danijar/director （项目页 https://danijar.com/director/ ） | **代码仓库许可：无法核（GitHub API `license=null`，无 LICENSE 文件）**；论文 arXiv non-exclusive 1.0 | 低（TF2 栈且代码许可无法核，禁复制代码） | danijar/director 无 LICENSE 文件（无法核），不得从 dreamerv3 外推假定 MIT |
| sola-2018 | Solà et al. 2018（Micro Lie Theory） | §8 未核→R3 已核 | https://arxiv.org/abs/1812.01537 ，2018-12-04（v1；v9 2021-12-08） | https://github.com/artivis/manif （论文 HTML 直接链接的配套李群库） | 配套代码 MIT（API 核实）；论文 CC BY-NC-SA 4.0 | 高（本仓 S0 已纯 Python 独立实现并通过 G1/G2 复核） | 一阶切空间线性化在大角度/多峰下有截断误差；论文 CC BY-NC-SA 不抄原图 |
| barrau-bonnabel-2017 | Barrau & Bonnabel 2017（IEKF） | §8 未核→R3 已核 | https://arxiv.org/abs/1410.1465 （v1 2014-10-06；v4 2015-10-19；IEEE TAC 2017 https://doi.org/10.1109/TAC.2016.2594085 ） | 无法核（arXiv 1410.1465 与 IEEE TAC 10.1109/TAC.2016.2594085 均为控制论数学定理证明论文，未提供官方代码仓库） | 论文 arXiv non-exclusive 1.0 / IEEE 许可；代码许可：无法核 | 高（解析滤波方程已由本仓 S0 独立实现） | 官方代码与许可无法核；群仿射稳定定理不解决数据关联混淆（需配 S1 拓扑层） |
| blenderworld | BlenderWorld | **9.1 增补**（评测基准，**非世界模型**） | 技术报告 https://github.com/QwenLM/BlenderWorld/blob/main/docs/BlenderWorld__Benchmarking_Visual_Agents_for_3D_Creation_from_Real_World_References.pdf （2026-10） | https://github.com/QwenLM/BlenderWorld ；数据集 https://huggingface.co/datasets/Qwen/BlenderWorld | **代码仓库 MIT（API 核实）；HuggingFace 数据集卡 MIT（`cardData.license=mit` 核实）** | 低（非世界模型；官方评测需 Linux + Blender 4.2.10 + Claude Code CLI + 付费 VLM） | **评测基准而非世界模型**；未下载数据集；本机不跑官方付费 VLM 评测 |

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

## 3. 可借鉴机制汇总（全部 28 条，每条 ≥1，详见 JSON）

- **h-jepa**：分层 action-conditioned JEPA、自顶向下子目标规划、慢速状态保留。
- **lewm**：像素端到端 JEPA、SIGReg 防坍塌、CEM 潜滚动规划。
- **vjepa2**：Dense Predictive Loss + Deep Self-Supervision、冻结特征教师基线。
- **dreamerv3**：RSSM 潜动态 + 想象轨迹（仅世界模型部分）、categorical 表征。
- **stable-worldmodel**：收集→训练→MPC 三段接口、CEM/MPPI 求解器、FoV 泛化评测。
- **egnn**：E(n) 等变消息传递、对象图 `Δs_i = f(s_i, neighbors, action, dt)` 候选。
- **slot-attention**：竞争注意力对象绑定、无监督对象发现。
- **thick**：离散潜动态稀疏更新成不变上下文、高层只预测上下文切换。
- **gradcscg**：可微克隆结构因果图接 VQ-VAE 前端，从连续图像序列端到端恢复混淆观察下的认知地图拓扑。
- **eswm**：从稀疏不连续的情景转移片段拼出空间地图，让同一情景记忆同时服务拓扑推断与历史检索。
- **far**：用回忆内容对未来预测的真实效用训练多线索（时间、位姿、视觉）自适应检索权重（仅借鉴论文公式思想，不碰 CC BY-NC 代码）。
- **flow-equivariant-wm**：以智能体为中心的潜在网格记忆随自运动做流等变变换，保持视野外区域几何对齐。
- **schaeffer-grid-cells**：科学证伪边界——深网路径积分几乎不自发产生网格细胞，网格评分只作事后探针、绝不作训练目标或晋升门。
- **seq-jepa**：自回归序列 JEPA 分离变换不变（语义）与变换等变（位姿/几何）潜表征。
- **equivariant-trust-horizons**：基于一步潜残差与有限时间膨胀估计构造共形校准的可信预测时域（rollout 步数截断参考）。
- **s5**：多输入多输出（MIMO）对角连续时间线性状态空间层，支持按样本步长 `dt` 离散化与并行关联扫描。
- **swap-equivariant-wm**：将物理反射对称性直接嵌入潜世界模型以消除对称交互的冗余编码。
- **cscg**：动作条件克隆隐马尔可夫模型（Cloned HMM），用同一观察符号的多个克隆节点消歧位置混淆并做虚构评估规划。
- **tem**：将抽象关系结构（路径积分）与具体感官内容解耦，通过外积自联想记忆快速跨世界重绑定。
- **cls**：海马体快速非参数情景存储与新皮层慢速参数规律整合的双系统分工与交错回放框架。
- **nec**：可微神经字典（DND）非参数键值缓冲，写入新经历不直接改写主干网络权重。
- **banino-2018**：平移与角速度路径积分任务形式化（受 Schaeffer 2023 反证约束，不以网格激活为目标）。
- **cueva-wei-2018**：2D 竞技场速度积分空间定位与边界/网格响应探针分析（同样受 Schaeffer 2023 反证约束）。
- **plan2explore**：利用一步潜预测器集成分歧度度量认知不确定性，在想象轨迹中规划主动探索（留 S6 接口）。
- **director**：目标自编码器离散量化潜空间可行子目标，Manager/Worker 双层跨步幅规划（仅参考论文机制，不碰无许可代码）。
- **sola-2018**：李群 SO(2)/SE(2)/SO(3)/SE(3) 的 Exp/Log、右扰动、伴随矩阵、左右雅可比与切空间高斯不确定性传播（S0 核心）。
- **barrau-bonnabel-2017**：群仿射系统上的不变扩展卡尔曼滤波（IEKF）自主误差动力学与轨迹无关局部稳定性定理（S0 参考滤波上界）。
- **blenderworld**：3D 创作交付物的确定性场景结构检查 + 多视角新鲜渲染评分双路评测协议，以及缺失/失败计 0 分保留分母的反刷分规则（对应 `awz.V9.D1/D2`）。

---

## 4. R1/R2 既有说明与 R3 未核/无法核边界汇总

### 4.1 THICK 来源说明（r1 修正保留）
任务卡只给缩写，RFC/ARCHITECTURE_V9/全仓库无全称。经信箱问答 #121（统筹 claude）指引，
原执行者独立在 OpenReview 检索核实：标题《Learning Hierarchical World Models with
Adaptive Temporal Abstractions from Discrete Latent Dynamics》，作者 Gumbsch/Sajid/Martius/Butz，
ICLR 2024 spotlight，https://openreview.net/forum?id=TjCDNssXKU（摘要含 THICK 全称与机制）。
**R2 复核指出「无官方代码」结论有误**：作者主页 https://cgumbsch.github.io/ 的 THICK 条目直接列出
[Code (TF2)](https://github.com/CognitiveModeling/THICK) 与 [Code (JAX)](https://github.com/CognitiveModeling/thix)，
并给出项目页 https://sites.google.com/view/thick-world-models。
`CognitiveModeling/THICK` README 自述为 ICLR 2024 论文的 **TensorFlow 2** 实现，
GitHub API `license.key=mit`；`CognitiveModeling/thix` 描述「THICK in JAX」，GitHub API `license=null`
（**未声明许可，未核**）。OpenReview 记录本身仍无代码链接。**不据此推断任一仓库在 MLX 上可安装或可运行。**

### 4.2 V9-R3 明确标注「无法核」或非商业限制的条目汇总（严禁猜测或外推）
1. **无公开官方代码仓库（代码链接与代码许可均标 `无法核`）**：
   - `eswm`（https://arxiv.org/abs/2505.13696 ）：摘要、HTML 正文与 `BashivanLab` GitHub 组织均无该文代码仓库；论文许可为 `CC BY-NC-ND 4.0`。
   - `equivariant-trust-horizons`（https://arxiv.org/abs/2606.24946 ）：摘要与 HTML 正文均无代码仓库链接；论文许可为 `CC BY 4.0`。
   - `swap-equivariant-wm`（https://arxiv.org/abs/2606.19928 ）：项目页 https://swap-parkour.github.io/ 与论文均未放出代码仓库链接。
   - `cls`（https://doi.org/10.1037/0033-295X.102.3.419 与 https://doi.org/10.1016/j.tics.2016.05.004 ）：理论综述论文，无代码仓库；1995 年 APA 论文在 Crossref 中 `license=null`（开放许可 `无法核`）。
   - `nec`（https://arxiv.org/abs/1703.01988 ）：论文与 `google-deepmind` 组织下均无官方 NEC 仓库。
   - `cueva-wei-2018`（https://arxiv.org/abs/1803.07770 ）：论文摘要与 HTML 正文无官方代码链接；GitHub 上第三方复现均无许可声明。
   - `barrau-bonnabel-2017`（https://arxiv.org/abs/1410.1465 / https://doi.org/10.1109/TAC.2016.2594085 ）：纯数学控制论论文，无官方代码仓库。
2. **有官方/关联代码仓库，但仓库未声明开源许可证（代码许可标 `无法核`）**：
   - `tem`（https://doi.org/10.1016/j.cell.2020.10.024 ）：PMC7707106 Data and Code Availability 指向 https://github.com/djcrw/generalising-structural-knowledge （TF），其 README 另指向 https://github.com/jbakermans/torch_tem （PyTorch）；经 GitHub API 核实两仓库 `license` 均为 `null`（无 `LICENSE` 文件），代码许可标 `无法核`。
   - `director`（https://arxiv.org/abs/2206.04114 ）：官方仓库 https://github.com/danijar/director 的 GitHub API `license=null` 且无 `LICENSE` 文件，代码许可标 `无法核`（不得从 `dreamerv3` 的 MIT 外推）。
   - `schaeffer-grid-cells`（https://arxiv.org/abs/2312.03954 ）：作者部分复现仓库 https://github.com/RylanSchaeffer/FieteLab-Sorscher-2022-Reproduction 的 GitHub API `license=null`，代码许可标 `无法核`。
   - `banino-2018`（https://doi.org/10.1038/s41586-018-0102-6 ）：官方仓库 https://github.com/google-deepmind/grid-cells （Apache-2.0）仅含监督路径积分实验，论文中的 RL 导航智能体代码未开源（标 `无法核`）。
3. **官方代码仓库为非商业限制许可（禁止直接复制代码或权重）**：
   - `far`（https://arxiv.org/abs/2609.34677 ）：官方仓库 https://github.com/sony/far 的 `LICENSE` 原文为 `Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)`。

## 5. 访问日期与只读声明
- 访问日期：`2026-10-16`（R1 保留条目原于 2026-10-15/16 访问，R3 全部 28 条于 2026-10-16 统一只读复核）。
- 全部通过 HTTP 只读访问（arXiv abs/HTML、Crossref API、EuropePMC API、GitHub API 与 raw README/LICENSE、HuggingFace datasets API 与 raw README）；**未登录、未下载任何数据集/权重、未 clone、未安装、未运行 MLX**。
