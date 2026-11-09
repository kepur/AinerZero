# S3 记忆检索与巩固：可行性盘点报告

## 1. M2 记忆干扰诊断
- **入口函数与入参**：纯指标计算入口为 [`metrics.py:336`](src/ainerzero/v9/experiments/s1/metrics.py#L336)（`def memory_interference`），入参为 `before` 和 `after` 的 `Mapping[str, float]`，可直接对比 S1 或 S2 评测指标变化；模型级成对评估入口为 [`paired_memory.py:203`](src/ainerzero/learning/paired_memory.py#L203)（`evaluate_paired_memory`），入参绑定旧版 RSSM 粒子信元模型结构，无法直接摄入 S1 结构化检测包 ([`spec.py:33`](src/ainerzero/v9/experiments/s1/spec.py#L33)) 或 GridLab-S2 7×7 局部网格图 ([`world.py:19`](src/ainerzero/v9/experiments/s2/world.py#L19))，接入须编写专用观测适配层。
- **M2 实验结论与教训**：
  - D 条件单步零状态蒸馏 ($\lambda_h=0$) 虽通过全部 5 项门禁 ([`RESEARCH_LOG.md:521`](RESEARCH_LOG.md#L521))，但完全丧失多步历史利用能力；
  - M2n-M5 冻结尾部递归块虽降低 89% 动作破坏，但梯度冲突转移至输入写入路径导致池化失败 ([`RESEARCH_LOG.md:523`](RESEARCH_LOG.md#L523))；
  - M2n-M6（半投影）与 M2n-M7（全梯度投影）消除破坏的同时使历史留存率降至 0.062 并失败迁移 ([`RESEARCH_LOG.md:557`](RESEARCH_LOG.md#L557))。
- **对 S3 的核心指导**：循环隐藏状态内嵌多步历史必然引发跨任务梯度干扰；S3 必须转向非参数、只读键值检索与外置巩固机制。

## 2. 现有记忆实现
- **代码位置**：度量图记忆 `MetricMapMemory` 位于 [`arms.py:87`](src/ainerzero/v9/experiments/s1/arms.py#L87)；拓扑图记忆 `TopologyMemory` 位于 [`arms.py:174`](src/ainerzero/v9/experiments/s1/arms.py#L174)。
- **读写与变换机制**：
  - `MetricMapMemory`：双线性 splatting 写入 ([`arms.py:100`](src/ainerzero/v9/experiments/s1/arms.py#L100))，SE(2) 双线性 warp 姿态变换 ([`arms.py:126`](src/ainerzero/v9/experiments/s1/arms.py#L126))，点积 softmax 注意力读取 ([`arms.py:157`](src/ainerzero/v9/experiments/s1/arms.py#L157))；
  - `TopologyMemory`：余弦相似度匹配与增节写入 ([`arms.py:189`](src/ainerzero/v9/experiments/s1/arms.py#L189))，余弦 softmax 节点加权读取 ([`arms.py:216`](src/ainerzero/v9/experiments/s1/arms.py#L216))。
- **线索检索支持**：现有两实现及基类接口 [`spatial_memory.py:44`](src/ainerzero/v9/interfaces/spatial_memory.py#L44) 仅支持空间区域与拓扑地点查询，无按时间或语义对象线索索引。
- **FAST/MID/SLOW 晋级机制**：在真实训练 arm 中**未实现**（生产代码为单一状态更新），分级淘汰与晋级仅存在于纯 CPU 桩 [`spatial_memory.py:176`](src/ainerzero/v9/fakes/spatial_memory.py#L176)（`FakeSpatialMemory`）。

## 3. 历史读回任务的数据
- **S1 vs GridLab-S2 重访与内容差异**：S1 Arena 导航族 50 集存在零物体检测严重缺陷 ([`RESEARCH_LOG.md:1745`](RESEARCH_LOG.md#L1745))，缺乏读回内容载体；GridLab-S2 单集长达 240 步 ([`spec.py:63`](src/ainerzero/v9/experiments/s2/spec.py#L63))，在 25×25 迷宫中重访频率高，但当前网格环境仅有墙/门/柱，缺少丰富语义实体 token。
- **任务构造与 Ground Truth**：可直接从 GridLab-S2 仿真底层 `State(x, y, heading)` 及拓扑距离图 ([`world.py:37`](src/ainerzero/v9/experiments/s2/world.py#L37)) 构造位置记忆回溯任务，具备严格仿真 Ground Truth。

## 4. 可复用的已训练模型
- **检查点位置与规格**：S1 模型为 `.npz` 格式（100KB–1.5MB，位于 `artifacts/v9/s1/phase1/runs/`）；S2 共有 9 个训练检查点（`arm_{a,b,c}` 各 3 种子，每个 `best.ckpt` 1.2MB + `meta.json`，位于 `artifacts/v9/s2/phase1/checkpoints/`）。
- **CPU 加载与潜空间提取**：S2 模型可通过 [`adapters_mlx.py:768`](src/ainerzero/v9/experiments/s2/adapters_mlx.py#L768)（`load_trained_model`）在纯 CPU 环境加载；调用 `model.encode(obs)` 与 `model.latents(obs_seq)` 即可直接提取潜向量作为检索 Key/Value ([`adapters_mlx.py:272,434,695`](src/ainerzero/v9/experiments/s2/adapters_mlx.py#L272))；S1 则通过 [`arms.py:615`](src/ainerzero/v9/experiments/s1/arms.py#L615)（`load_d_candidate`）在 CPU 加载。

## 5. FAR 的前提
- **预测误差双向对比现状**：当前训练流 [`worker.py`](src/ainerzero/v9/experiments/s1/worker.py) 与 [`train_runner.py:100`](src/ainerzero/v9/experiments/s2/train_runner.py#L100) 仅有单分支前向与损失计算，无法单步直接获取「有 recall vs 无 recall」的对比。
- **所需新增模块与代码量**：需新增检索评分头（~100 行）、记忆融合门控（~70 行）、双前向 Utility 损失与门禁（~120 行）、带索引重放池适配器（~90 行），预估累计新增约 320–450 行代码。

## 6. 旧技能保留（式 6）
- **实现位置与数据支撑**：代码位于 [`promotion_gate.py:642`](src/ainerzero/v9/mechanism/promotion_gate.py#L642)（`# D3-2 Old-capability retention (Eq. 6: L_old <= L_baseline + epsilon)`）；评测基于预登记基线对比，核心数据源自 [`action_preservation.py:81`](src/ainerzero/learning/action_preservation.py#L81) 维护的动作保留探针样本集。

## 7. 成本估算
- **单步耗时（只读副本统计）**：S2 训练步 `arm_a` 0.1451 s/步，`arm_b` 0.2414 s/步，`arm_c` 0.3213 s/步；S1 训练步约 0.054–0.073 s/步。S2 CEM 规划单集耗时 ~7.4 s。
- **S3 建议预算**：训练轮数上限推荐 3000 步（单种子 CPU 约 450–900s），评测集推荐每分区 ≤50 集。

## 8. 小样实测
- **CPU 实测与零 GPU 验证**：调用 [`data.py:191`](src/ainerzero/v9/experiments/s2/data.py#L191)（`run_episode`）在纯 CPU 执行单集生成，耗时 0.0963s（远低于 120s 限制），生成 147 步（240 环境步）。
- **隔离断言验证**：输出写入 [`reports/V9-S3-DESIGN/inventory/sample_episode.json`](reports/V9-S3-DESIGN/inventory/sample_episode.json)（220,795 字节），严格断言路径不包含 `artifacts/`。

## 对 S3 设计的影响
1. **记忆结构转向非参数外脑**：摒弃循环状态历史内嵌路线，采用只读外部 Key-Value 缓冲池，从根本上隔离多任务梯度干扰。
2. **检索接口升级**：`SpatialMemory` 与具体实现须扩展时间/语义联合线索查询接口（`query_by_cue`），并将 `FakeSpatialMemory` 中的 FAST/MID/SLOW 晋级逻辑实装到生产管道。
3. **环境与任务构造**：基于 GridLab-S2 位姿重访差异构建历史读回基准，同时需扩充轻量对象语义标签以规避 S1 零检测问题。
4. **双前向与式 6 约束**：FAR 训练循环须引入轻量双前向（+380 行），且晋级判定必须强制满足 [`promotion_gate.py:642`](src/ainerzero/v9/mechanism/promotion_gate.py#L642) 的旧能力保留约束。
