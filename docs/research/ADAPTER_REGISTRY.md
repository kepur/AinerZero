# Research Adapter Registry v0（ainerzero.V9.R1，二级 big-pickle-d98w，r1 修订 2026-10-16）

只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。
机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。
**r1 修订**：回应 R2 独立复核，修正 THICK 官方代码结论、Stable WorldModel v1 日期、V-JEPA 2.1 直链；
原 r0 字节先归档于 `reports/V9-R1/r0-archive/`（未覆盖）。未核实项保留，不下「可安装 / MLX 可用」结论。

| ID | 条目 | 论文/日期 | 仓库 | 许可 | MLX 可行性 | 不可推断（摘） |
|---|---|---|---|---|---|---|
| h-jepa | H-JEPA | arXiv:2610.06805，2026-10-05 | https://github.com/kevinghst/H-JEPA | MIT | 低（PyTorch+CUDA，需重写） | AntMaze 73.3%≠本机收益；CUDA 代码不即插即用 |
| lewm | LeWM | arXiv:2603.19312，2026-03-13（v3 06-03） | https://github.com/lucas-maes/le-wm | MIT | 低（PyTorch，需重写） | 48×加速是论文数；不保证 C0 分数 |
| vjepa2 | V-JEPA 2/2.1 | 2.1 论文 arXiv:2603.14482（v1 2026-03-15，v3 2026-06-11）；V-JEPA 2 论文 arXiv:2506.09985（2025）；仓库 2.1 发布 2026-03-16 | https://github.com/facebookresearch/vjepa2 | MIT（部分文件 Apache-2.0） | 低（decord 不支持 macOS；权重仅作教师） | 榜单成绩≠AWZ 收益；冻结特征≠已理解；无 Release 记录 |
| dreamerv3 | DreamerV3 | arXiv:2301.04104，2023-01-10（Nature 2025） | https://github.com/danijar/dreamerv3 | MIT | 低（JAX 栈；仅思想与基线） | 不把整套 RL 搬进世界脑 |
| stable-worldmodel | Stable WorldModel | arXiv:2605.21800，**2026-05-20**（v1） | https://github.com/galilai-group/stable-worldmodel | MIT | 中（评测 harness 思想；全栈太重） | 平台排名≠我方能力；各环境许可另查 |
| egnn | EGNN | arXiv:2102.09844，2021-02-19 | https://github.com/vgsatorras/egnn | MIT | 中（小而干净；需移植验证） | 真值位置输入会泄漏；不拿 Blender 真值冒充视觉 |
| slot-attention | Slot Attention | arXiv:2006.15055，2020-06-26（NeurIPS 2020） | https://github.com/google-research/google-research/tree/master/slot_attention | Apache-2.0（父仓库） | 低（TF 栈；仅思想） | CLEVR 成绩≠感知收益；ARI 不可比 |
| thick | THICK | ICLR 2024 spotlight（https://openreview.net/forum?id=TjCDNssXKU） | 官方两版：https://github.com/CognitiveModeling/THICK（TF2）与 https://github.com/CognitiveModeling/thix（JAX） | THICK=MIT；thix 未声明（未核） | 低（TF2/JAX 栈；机制参考，需重写） | 找到实现≠MLX 可安装；thix 许可未核 |

## 可借鉴机制（每条 ≥1，详见 JSON）
- H-JEPA：分层 action-conditioned JEPA、自顶向下子目标规划、慢速状态保留。
- LeWM：像素端到端 JEPA、SIGReg 防坍塌、CEM 潜滚动规划。
- V-JEPA 2.1：Dense Predictive Loss + Deep Self-Supervision、冻结特征教师基线。
- DreamerV3：RSSM 潜动态 + 想象轨迹（仅世界模型部分）、categorical 表征。
- Stable WorldModel：收集→训练→MPC 三段接口、CEM/MPPI 求解器、FoV 泛化评测。
- EGNN：E(n) 等变消息传递、对象图 `Δs_i = f(s_i, neighbors, action, dt)` 候选。
- Slot Attention：竞争注意力对象绑定、无监督对象发现。
- THICK：离散潜动态稀疏更新成不变上下文、高层只预测上下文切换。

## THICK 来源说明（r1 修正）
任务卡只给缩写，RFC/ARCHITECTURE_V9/全仓库无全称。经信箱问答 #121（统筹 claude）指引，
原执行者独立在 OpenReview 检索核实：标题《Learning Hierarchical World Models with
Adaptive Temporal Abstractions from Discrete Latent Dynamics》，作者 Gumbsch/Sajid/Martius/Butz，
ICLR 2024 spotlight，https://openreview.net/forum?id=TjCDNssXKU（摘要含 THICK 全称与机制）。
**R2 复核指出「无官方代码」结论有误**：作者主页 https://cgumbsch.github.io/ 的 THICK 条目直接列出
[Code (TF2)](https://github.com/CognitiveModeling/THICK) 与 [Code (JAX)](https://github.com/CognitiveModeling/thix)，
并给出项目页 https://sites.google.com/view/thick-world-models。
本轮（2026-10-16）只读核实：`CognitiveModeling/THICK` README 自述为 ICLR 2024 论文的 **TensorFlow 2** 实现，
GitHub API `license.key=mit`；`CognitiveModeling/thix` 描述「THICK in JAX」，GitHub API `license=null`
（**未声明许可，未核**）。OpenReview 记录本身仍无代码链接。**不据此推断任一仓库在 MLX 上可安装或可运行。**

## 访问日期
- 修正条目 vjepa2 / stable-worldmodel / thick：2026-10-16 重新只读访问（arXiv、GitHub 页与 GitHub API）。
- 其余条目沿用 2026-10-15 首次只读访问记录。
- 全部为 webfetch 只读；未登录、未下载任何文件、未 clone、未安装。

## 来源链接（逐条，与 JSON 一致）
- h-jepa 论文 https://arxiv.org/abs/2610.06805；仓库 https://github.com/kevinghst/H-JEPA
- lewm 论文 https://arxiv.org/abs/2603.19312；仓库 https://github.com/lucas-maes/le-wm；项目页 https://le-wm.github.io/
- vjepa2 论文（2.1 直链）https://arxiv.org/abs/2603.14482；V-JEPA 2 论文 https://arxiv.org/abs/2506.09985；仓库 https://github.com/facebookresearch/vjepa2（2.1 发布见 README News，2026-03-16）
- dreamerv3 论文 https://arxiv.org/abs/2301.04104；仓库 https://github.com/danijar/dreamerv3
- stable-worldmodel 论文 https://arxiv.org/abs/2605.21800（v1 提交 2026-05-20）；仓库 https://github.com/galilai-group/stable-worldmodel
- egnn 论文 https://arxiv.org/abs/2102.09844；仓库 https://github.com/vgsatorras/egnn
- slot-attention 论文 https://arxiv.org/abs/2006.15055；代码 https://github.com/google-research/google-research/tree/master/slot_attention（父仓库 Apache-2.0）
- thick 论文 https://openreview.net/forum?id=TjCDNssXKU；官方代码 https://github.com/CognitiveModeling/THICK（TF2，MIT）与 https://github.com/CognitiveModeling/thix（JAX，许可未核）；作者页 https://cgumbsch.github.io/；项目页 https://sites.google.com/view/thick-world-models

## r1 修订对照（R2 → 本次）
| R2 指出的问题 | r0 | r1 |
|---|---|---|
| THICK「无官方代码」错误 | 仓库记「未找到」，许可「未核」 | 补 CognitiveModeling/THICK（TF2，MIT，API 核实）与 thix（JAX，许可未声明未核）；保留不可推断项 |
| Stable WorldModel v1 日期 | 2026-05-26 | 2026-05-20（arXiv 提交历史，仅 v1） |
| V-JEPA 2.1 缺直链 | 只写「见仓库 README 引用节」 | 补直链 arXiv:2603.14482（v1 03-15 / v3 06-11）；03-16 仓库发布日期保留 |
