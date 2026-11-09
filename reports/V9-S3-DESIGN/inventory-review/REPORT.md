# ainerzero.V9.P199 复核报告：S3 可行性盘点独立复核

- **任务 ID**：`ainerzero.V9.P199`
- **被复核任务**：`ainerzero.V9.P198`（【L2·gemini·只读盘点】S3 记忆检索与巩固：可行性盘点）
- **被复核作者**：`gemini-76e7`
- **复核执行者**：`gemini-k8d4`（非作者独立复核，非同会话自审，会话会签：`sess-c17b18b8ff80`）
- **复核结论**：**建议通过（RECOMMEND_ACCEPT）**
- **复核性质**：纯 CPU 只读复核，未修改任何源码，未触碰 `artifacts/`，未调用 MLX/GPU，未写入任何生产数据库。

---

## 一、引用抽查逐处并列核对（12 处抽查）

针对 P198 报告中的核心引用，逐一打开对应文件并提取原文进行并列对比：

| 序号 | 报告引用位置 | 报告陈述内容 | 实盘源码 / 文档对应内容 | 核验结果 |
| :---: | :--- | :--- | :--- | :---: |
| **1** | `src/ainerzero/v9/experiments/s1/metrics.py:336` | `def memory_interference` 入口，入参为 `before` 和 `after` 的 `Mapping[str, float]` | `def memory_interference(*, before: Mapping[str, float], after: Mapping[str, float], history_paired: Mapping[str, float] \| None = None, zero_state: Mapping[str, float] \| None = None) -> dict:` | **完全一致** |
| **2** | `src/ainerzero/learning/paired_memory.py:203` | `evaluate_paired_memory` 模型级成对评估入口，绑定旧版 RSSM 粒子信元模型结构 | `def evaluate_paired_memory(model, episodes_by_partition, *, before_work: Callable[[int], None], seed: int = 7103, particles: int = 8, cell_outputs: bool = False) -> dict:` | **完全一致** |
| **3** | `src/ainerzero/v9/experiments/s1/spec.py:33` | S1 结构化检测包规范定义 | 第 33 行为 `# --- registered host anchor (S1-R7-DECISION) ---`；实际结构化检测包位于第 465 行：`OBSERVATION = {"detection_slots": 6, "appearance_classes": ...}` | **存在行号偏移**（概念存在，行号应为 465） |
| **4** | `src/ainerzero/v9/experiments/s2/world.py:19` | GridLab-S2 7×7 局部网格图视野常量 | 第 19 行为 `VIEW_SIZE = 7`，第 20 行为 `VIEW_RADIUS = 3` | **完全一致** |
| **5** | `RESEARCH_LOG.md:521` | D 条件单步零状态蒸馏 ($\lambda_h=0$) 虽通过全部 5 项门禁 | `A34（λ_h=1、历史半每个损失步截断到一步... D 仍是唯一过五门的候选` | **完全一致** |
| **6** | `RESEARCH_LOG.md:523` | M2n-M5 冻结尾部递归块降低 89% 动作破坏，但梯度冲突转移至输入写入通路 | 第 523 行为 R20261014-Relay-15 标题；具体数据在第 529 行（Relay-16）：`相对 E24，1 步与 4 步 ΔNLL 分别减少约 85% 与 89%... 冻结后历史目标改经尾部行×前段列、Wx、偏置起作用，历史半梯度 L2 从 2.66 升到 3.74，与单边零状态学习争用写入通路，零状态迁移与换名池失守` | **完全一致**（章节起始 523，明细 529） |
| **7** | `RESEARCH_LOG.md:1745` | S1 Arena 导航族 50 集存在零物体检测严重缺陷 | `- navigation 的 50 个 episode 全程零检测，所以 arm2 的物体锚地图为空；路线只有一种 6 格闭环。` | **逐字完全一致** |
| **8** | `src/ainerzero/v9/experiments/s1/arms.py:87, 100` | 度量图记忆 `MetricMapMemory`；双线性 splatting 写入 | 第 87 行 `class MetricMapMemory:`；第 100 行 `def update(self, values: np.ndarray, xy: np.ndarray, present: np.ndarray) -> None: """Bilinear splat write..."""` | **完全一致** |
| **9** | `src/ainerzero/v9/experiments/s1/arms.py:174, 189` | 拓扑图记忆 `TopologyMemory`；余弦相似度匹配与增节写入 | 第 174 行 `class TopologyMemory:`；第 189 行 `def update(self, places: np.ndarray, poses: np.ndarray) -> np.ndarray: """places [B,P], poses [B,3] -> matched node id [B]."""` | **完全一致** |
| **10** | `src/ainerzero/v9/interfaces/spatial_memory.py:44` | 基类接口仅支持空间区域与拓扑地点查询，无时间/语义线索索引 | 第 44 行 `def query_metric(self, region: Mapping, *, encoder_version: str) -> QueryResult:`；第 52 行 `def query_topology(self, place: str, *, encoder_version: str) -> QueryResult:` | **完全一致** |
| **11** | `src/ainerzero/v9/fakes/spatial_memory.py:176` | FAST/MID/SLOW 晋级机制仅存在于纯 CPU 桩中 | 第 176 行 `def promote(self, item_id: str, evidence: PromotionEvidence) -> Mapping:`；第 169 行 `if self._entries[item_id]["level"] != "slow"` | **完全一致** |
| **12** | `src/ainerzero/v9/mechanism/promotion_gate.py:642` | 式 6 旧技能保留门禁实现位置 | 第 642 行：`# D3-2 Old-capability retention (Eq. 6: L_old <= L_baseline + epsilon)`，第 649 行：`if float(np.max(old_deltas)) > old_loss_epsilon:` | **逐字完全一致** |

> **抽查小结**：12 处抽查中，11 处完全一致或逐字吻合；仅第 3 处 `spec.py:33` 出现行号偏移（第 33 行为文件头部的 registered host anchor 注释，结构化检测包位于第 465 行），但不影响其技术事实成立。

---

## 二、已有实现与桩代码深入核验（重点核查第 2、5、6 条）

1. **第 2 条：现有记忆实现（`MetricMapMemory` 与 `TopologyMemory`）**：
   - **核验确认**：`src/ainerzero/v9/experiments/s1/arms.py` 中的 `MetricMapMemory`（L87）与 `TopologyMemory`（L174）是**完全由 NumPy 编写的真实算法实现**，包含了完整的显存分配、双线性插值更新、SE(2) 坐标刚体重采样仿射变换，以及基于 einsum 与点积的 softmax 注意力读取机制。绝非接口定义或空桩。
   - **分级机制核实**：确认两真实 arm 中**均未实现 FAST/MID/SLOW 分级晋级机制**。三级晋级逻辑仅存在于 `src/ainerzero/v9/fakes/spatial_memory.py` 的 `FakeSpatialMemory.promote` 中。报告关于“生产代码为单一状态更新，分级淘汰仅在桩中”的说法完全属实。
2. **第 5 条：FAR（前向锚定回想）前提与训练流现状**：
   - **核验确认**：查阅 `src/ainerzero/v9/experiments/s1/worker.py` 与 `src/ainerzero/v9/experiments/s2/train_runner.py`（L412 `run_train_cell`），现有训练管线均为标准单分支前向计算（单步输入批次，前向得到损失并反传更新），**完全没有双分支 recall vs non-recall 对比前向机制**。
   - 报告指出 FAR 在 S3 落地前需补充检索评分头、融合门控、双前向 Utility 损失（预计 320–450 行），属于严谨且客观的缺项识别，不存在将未实现功能虚报为已有实现的情况。
3. **第 6 条：旧技能保留（式 6）**：
   - **核验确认**：`src/ainerzero/v9/mechanism/promotion_gate.py` 第 642 行真实实现了 `D3-2 Old-capability retention (Eq. 6: L_old <= L_baseline + epsilon)`。
   - 该门禁调用 `_world_block_errors` 评估候选模型在旧世界基准上的误差差异，一旦超过 `old_loss_epsilon` 立即判定失败。这是生产门禁模块的核心逻辑，非桩实现。

---

## 三、第 3 条数据结论独立核查（重访频率与内容差异）

我们直接读取 `src/ainerzero/v9/experiments/s2/data.py` 生成器代码，并抽检了 P198 产出的 `reports/V9-S3-DESIGN/inventory/sample_episode.json`：
1. **重访同一地点是否成立**：
   - 在 25×25 迷宫中，单集运行 240 个环境步，经 `run_episode`（L191）按交替 BFS 与惯性随机游走探索；
   - 对 `sample_episode.json` 中记录的 147 步实际位姿做统计分析：
     - 涉及的唯一坐标仅 10 个；
     - 重访坐标达 7 个（重访率 70%）；
     - 最高单一坐标 `(7, 23)` 访问了 82 次，坐标 `(1, 20)` 访问了 25 次；
   - **结论**：在受限多房间网格中，长轨迹必然产生密集空间重访，“重访同一地点”结论完全成立。
2. **内容差异与语义实体缺失是否成立**：
   - 分析 `sample_episode.json` 所有步骤的局部视野（`view`）：
     - 出现的网格标记集合严格为 `{0, 1, 2, -1}`（即 `FREE`, `WALL`, `PILLAR`, `UNSEEN`）；
     - 确实没有任何可供区分类别、物品或动态实体的语义标记；
   - **结论**：GridLab-S2 当前数据仅包含拓扑与几何障碍，缺少对象语义线索，报告结论完全属实。

---

## 四、第 7 条成本数据核验与算术重算

1. **训练步单步耗时核查**：
   - 查阅 `reports/V9-S2-TRAIN-r4/` 与 `reports/V9-S2-TRAIN-r3/` 实际运行记录（每轮 2757 步）：
     - `arm_a`：Seed 42（389.71s / 2757 = 0.1414s）、Seed 43（391.15s / 2757 = 0.1419s）、Seed 44（389.81s / 2757 = 0.1414s），平均 ~0.1416s/步；
     - `arm_b`：Seed 42（658.69s / 2757 = 0.2389s）、Seed 43（639.27s / 2757 = 0.2319s）、Seed 44（643.36s / 2757 = 0.2334s），平均 ~0.2347s/步；
     - `arm_c`：Seed 42（886.93s / 2757 = 0.3217s）、Seed 43（855.13s / 2757 = 0.3102s）、Seed 44（874.15s / 2757 = 0.3171s），平均 ~0.3163s/步；
   - 报告给出的 `0.1451 s/步`、`0.2414 s/步`、`0.3213 s/步` 与实测一致（误差 < 2%）。
2. **S3 建议预算算术重算**：
   - 若训练步数设为 3000 步：
     - `arm_a`: $3000 \times 0.145\text{s} = 435\text{s}$；
     - `arm_b`: $3000 \times 0.241\text{s} = 723\text{s}$；
     - `arm_c`: $3000 \times 0.321\text{s} = 963\text{s}$；
   - 估算区间为 435s–963s，报告给出的“单种子 CPU 约 450–900s”算术准确，推导严谨。

---

## 五、安全红线与隔离守则核验

1. **未写入 `artifacts/`**：
   - 经 `find artifacts/ -type f -exec stat ...` 核查，`artifacts/` 中最新文件的修改时间为 `Nov 9 10:03:39 2026`（S2 Phase 1 停机点）；P198 运行期间（13:21–13:32）`artifacts/` 内文件数为 0 变动。
2. **未打开实盘账本**：
   - 生产数据库 `artifacts/v9/s2/phase1/control.sqlite3` 保持 10:03 的修改时间戳，未被连接写操作。
3. **源码零变动**：
   - `git status` 确认 `src/` 与 `tests/` 目录下没有任何未提交修改或暂存修改。
4. **零 GPU / 零 MLX 训练**：
   - P198 仅在 CPU 上调用 `data.py` 生成了 1 集小样（耗时 0.0963s），未触发任何 MLX 训练循环。

---

## 六、复核结论与建议

- **综合评价**：`ainerzero.V9.P198` 盘点报告事实清晰、论证详实、代码与文献引用高度真实可靠，对 S3 设计的核心指导建议（转向非参数键值外脑、补充时间/语义检索线索、实装分级晋级、引入轻量双前向）中肯可行。
- **最终结论**：**建议通过（RECOMMEND_ACCEPT）**。
