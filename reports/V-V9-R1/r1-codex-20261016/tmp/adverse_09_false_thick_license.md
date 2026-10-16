# Research Adapter Registry v0（ainerzero.V9.R1，二级 musespark-7f3q，2026-10-15）

只读研究参考与候选机制；**不引入生产依赖**。下载代码、权重或数据集一律先经用户批准（ADR-0012 §5）。
机器可读：`adapter_registry.json`（同目录）。论文成绩不替代本机同预算对照。

| ID | 条目 | 论文/日期 | 仓库 | 许可 | MLX 可行性 | 不可推断（摘） |
|---|---|---|---|---|---|---|
| h-jepa | H-JEPA | arXiv:2610.06805，2026-10-05 | https://github.com/kevinghst/H-JEPA | MIT | 低（PyTorch+CUDA，需重写） | AntMaze 73.3%≠本机收益；CUDA 代码不即插即用 |
| lewm | LeWM | arXiv:2603.19312，2026-03-13（v3 06-03） | https://github.com/lucas-maes/le-wm | MIT | 低（PyTorch，需重写） | 48×加速是论文数；不保证 C0 分数 |
| vjepa2 | V-JEPA 2/2.1 | 2.1 发布 2026-03-16（论文 2603.14482）；V-JEPA 2 论文 2506.09985 | https://github.com/facebookresearch/vjepa2 | MIT（部分文件 Apache-2.0） | 低（decord 不支持 macOS；权重仅作教师） | 榜单成绩≠AWZ 收益；冻结特征≠已理解 |
| dreamerv3 | DreamerV3 | arXiv:2301.04104，2023-01-10（Nature 2025） | https://github.com/danijar/dreamerv3 | MIT | 低（JAX 栈；仅思想与基线） | 不把整套 RL 搬进世界脑 |
| stable-worldmodel | Stable WorldModel | arXiv:2605.21800，2026-05-20 | https://github.com/galilai-group/stable-worldmodel | MIT | 中（评测 harness 思想；全栈太重） | 平台排名≠我方能力；各环境许可另查 |
| egnn | EGNN | arXiv:2102.09844，2021-02-19 | https://github.com/vgsatorras/egnn | MIT | 中（小而干净；需移植验证） | 真值位置输入会泄漏；不拿 Blender 真值冒充视觉 |
| slot-attention | Slot Attention | arXiv:2006.15055，2020-06-26（NeurIPS 2020） | https://github.com/google-research/google-research/tree/master/slot_attention | Apache-2.0（父仓库） | 低（TF 栈；仅思想） | CLEVR 成绩≠感知收益；ARI 不可比 |
| thick | THICK | ICLR 2024 spotlight（OpenReview） | https://github.com/CognitiveModeling/THICK | Apache-2.0 | 未可评（无代码；机制参考） | 无代码则复现成本未知，不得按已有实现规划 |

## 可借鉴机制（每条 ≥1，详见 JSON）
- H-JEPA：分层 action-conditioned JEPA、自顶向下子目标规划、慢速状态保留。
- LeWM：像素端到端 JEPA、SIGReg 防坍塌、CEM 潜滚动规划。
- V-JEPA 2.1：Dense Predictive Loss + Deep Self-Supervision、冻结特征教师基线。
- DreamerV3：RSSM 潜动态 + 想象轨迹（仅世界模型部分）、categorical 表征。
- Stable WorldModel：收集→训练→MPC 三段接口、CEM/MPPI 求解器、FoV 泛化评测。
- EGNN：E(n) 等变消息传递、对象图 `Δs_i = f(s_i, neighbors, action, dt)` 候选。
- Slot Attention：竞争注意力对象绑定、无监督对象发现。
- THICK：离散潜动态稀疏更新成不变上下文、高层只预测上下文切换。

## THICK 来源说明
任务卡只给缩写，RFC/ARCHITECTURE_V9/全仓库无全称。经信箱问答 #121（统筹 claude）指引，
执行者独立在 OpenReview 检索核实：标题《Learning Hierarchical World Models with
Adaptive Temporal Abstractions from Discrete Latent Dynamics》，作者 Gumbsch/Sajid/Martius/Butz，
ICLR 2024 spotlight，https://openreview.net/forum?id=TjCDNssXKU（摘要含 THICK 全称与机制）。
arXiv 按标题检索无匹配；OpenReview 记录无代码链接，仓库记"未找到"，许可记"未核"。

## 访问日期
全部来源页访问日期 2026-10-15（webfetch 只读；cookie 拒绝非必要，未登录，未下载任何文件）。

## 来源链接（逐条，与 JSON 一致）
- h-jepa 论文 https://arxiv.org/abs/2610.06805；仓库 https://github.com/kevinghst/H-JEPA
- lewm 论文 https://arxiv.org/abs/2603.19312；仓库 https://github.com/lucas-maes/le-wm；项目页 https://le-wm.github.io/
- vjepa2 仓库 https://github.com/facebookresearch/vjepa2（内含 [Paper] 链接；V-JEPA 2 论文 arXiv:2506.09985，2.1 论文 arXiv:2603.14482，见仓库 README 引用节）
- dreamerv3 论文 https://arxiv.org/abs/2301.04104；仓库 https://github.com/danijar/dreamerv3
- stable-worldmodel 论文 https://arxiv.org/abs/2605.21800；仓库 https://github.com/galilai-group/stable-worldmodel
- egnn 论文 https://arxiv.org/abs/2102.09844；仓库 https://github.com/vgsatorras/egnn
- slot-attention 论文 https://arxiv.org/abs/2006.15055；代码 https://github.com/google-research/google-research/tree/master/slot_attention（父仓库 Apache-2.0）
- thick 论文 https://openreview.net/forum?id=TjCDNssXKU；仓库 未找到（不臆测）
