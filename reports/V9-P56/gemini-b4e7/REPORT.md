# ainerzero.V9.P56 非作者复核报告：S1 r15 运行与拓扑 F1 异常解构（复核 P55）

- **复核执行者**：二级执行代理 `gemini-b4e7`（非 P55 作者，独立复核）
- **被验证任务**：`ainerzero.V9.P55`（一级 `claude` 执笔）
- **复核结论**：**建议通过**
- **生产台账状态**：`7244149c2bb87096e0dacf75f7151f15c0253f4bd367b23d0ff456090a2d5f53`（只读，零写入，验证前后哈希完全一致）

---

## 1. 核心核验项汇总

| 核验项目 | 预登记/报告预期 | 实际复核结果 | 判定 |
|---|---|---|---|
| **生产台账保护** | 结束哈希 `7244149c…`，复核期间只读 | 起始与结束均为 `7244149c…`，0 写入 | **通过** |
| **arm4 s0 训练终态** | completed, 3510 updates, rc=0 | run_id `2efa2b13db03467097e081434eea168c`, updates 3510, rc=0 | **通过** |
| **arm4 s0 检查点 SHA** | `50550e3a…` | `shasum -a 256` 准确匹配 `50550e3a2355ef1c5219f5aab007e3282fc1161627c91e57144482bdc93770ee` | **通过** |
| **评测作业终态 (10 项)** | 全部 completed, rc=0, 进程组确认空 | 10/10 completed, rc=0, `group_empty=True`, `confirmed_empty=True` | **通过** |
| **8 个继承格绑定身份** | 严格与 `spec.R15_INHERITANCE` 一致 | 逐格核验 8 个单元格 source_run_id 与 source_experiment_id 完全匹配 | **通过** |
| **arm4 s0 评测绑定** | 绑定本轮新 run | 明确绑定 `2efa2b13…`，`inherited_from` 为 null | **通过** |
| **总墙钟时长** | ≤ 5400 s (cap) | 851.2 s（完全在批准预算内，未触发截断） | **通过** |
| **进程组残留检查** | 进程组全部清空 | 11/11 作业 `members_left=[]`, `group_empty=True` | **通过** |

---

## 2. 8 个继承格与新训练格绑定复核明细

所有 9 个可训练单元格的绑定情况与 `spec.R15_INHERITANCE` 严格对应：

1. **arm2 seed 0**：继承自 `s1-phase1-20261024-r13`，绑定 run `19f2d1eb4bf04da4909d87501348028d`（参数 SHA `9d155fbf…`）
2. **arm2 seed 1**：继承自 `s1-phase1-20261024-r13`，绑定 run `7d155060fecc4070a9a68e95fb3761fa`（参数 SHA `c4d16f6e…`）
3. **arm2 seed 2**：继承自 `s1-phase1-20261028-r14`，绑定 run `33d09a1266bd4d9eabc2e59050048658`（参数 SHA `f7f9a661…`）
4. **arm3 seed 0**：继承自 `s1-phase1-20261024-r13`，绑定 run `403ae816720c4ad9b4f75ecd86e7b109`（参数 SHA `577429aa…`）
5. **arm3 seed 1**：继承自 `s1-phase1-20261028-r14`，绑定 run `6d606a3e949f40e0a8077d70e7c02f77`（参数 SHA `d4036d8b…`）
6. **arm3 seed 2**：继承自 `s1-phase1-20261028-r14`，绑定 run `3cd7524870174be898382ce15edbaaec`（参数 SHA `3681887a…`）
7. **arm4 seed 0**：**本轮新训练**，绑定 run `2efa2b13db03467097e081434eea168c`（参数 SHA `50550e3a…`）
8. **arm4 seed 1**：继承自 `s1-phase1-20261028-r14`，绑定 run `bc0264a2f90d4a688bb0abe571fa90c7`（参数 SHA `dae8d526…`）
9. **arm4 seed 2**：继承自 `s1-phase1-20261028-r14`，绑定 run `a5c631f535354e628d8f38d25361bef3`（参数 SHA `3b1d9e03…`）

另外，arm1 D 诊断型复验作业 `job-433a4284…` 正常执行完成，结果正确标记 `incomparable`。

---

## 3. `topology_recovery.f1 == 0.75` 异常深度解构报告

P55 作者在报告中特别指出：*“9 个可训练格的拓扑 F1 全部恰好是 0.75，不随臂、也不随 seed 变化……在弄清楚之前，不能拿这一项来比较各臂”*。

本复核代理在隔离副本与纯读取环境下对评测数据流、真值图结构以及实现源码进行了全链路诊断，**得出确切结论：该指标不依赖模型权重，系评测设计中真值空图回退与单向转移边过滤共同导致的常数退化（0.7500）**。

### 3.1 理论与代码根因

评测数据集共 200 个 episode，划分 4 个子族（各 50 个）：

1. **静态子族（`e3_identity`、`relation`、`time` 共 150 个 episode，占 75%）**：
   - 智能体在整个序列中静止在单格（`visited_cells=1`），真值邻接边集为空（`true_edges = set()`，长度 0）。
   - 查看 `metrics.py` 的计算公式：
     ```python
     true_positive = len(predicted & truth_edges)
     precision = true_positive / len(predicted) if predicted else (1.0 if not truth_edges else 0.0)
     recall = true_positive / len(truth_edges) if truth_edges else (1.0 if not predicted else 0.0)
     f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
     ```
   - 当 `truth_edges` 为空且模型没有预测边时，代码回退保护返回 `precision = 1.0`, `recall = 1.0`, `f1 = 1.0`。
   - **因此，无论何种模型，在 75% 的样本上 F1 恒等于 1.0**。

2. **移动子族（`navigation` 共 50 个 episode，占 25%）**：
   - 智能体沿轨迹跨越 7 个格子，真值边 `true_edges` 严格有 7 条。
   - **Arm 2（度量图）**：数据集中 `navigation` 序列的 `det_present` 字段全部为 0（无相对地标检测）。`MetricMapMemory.update` 中的写权重乘以 `(present > 0)` 导致更新值恒为 0，地图零写入（`norm = 0.0`）。`probe_graph` 提取到 0 个节点与 0 条边。
   - **Arm 3 与 Arm 4（拓扑图）**：智能体在 episode 中单向顺次移动（如节点 0→1→2→3→4），发生单向前向转移（`adjacency[i, j] > 0`）。然而，`runtime.py:195` 的边探测提取逻辑为：
     ```python
     edges = {
         (int(i), int(j))
         for i in range(count)
         for j in range(i + 1, count)
         if adjacency[i, j] > 0 and adjacency[j, i] > 0
     }
     ```
     它**硬性要求双向往返移动**（`adjacency[i, j] > 0` 且 `adjacency[j, i] > 0`）。由于单向导航轨迹从不反向折返，`adjacency[j, i]` 恒为 0，因此 `probe_graph` 导出的 `edges` 恒为空集！
   - **判定**：预测边为 0，真值边为 7，`true_positive = 0`，故 `precision = 0.0`, `recall = 0.0`, `f1 = 0.0`。
   - **因此，无论何种模型，在 25% 的移动样本上 F1 恒等于 0.0**。

3. **宏平均数学公式**：
   $$\text{Macro F1} = 0.75 \times 1.0 + 0.25 \times 0.0 = 0.7500$$

### 3.2 实验验证证据

在隔离测试脚本 `check_topology_anomaly.py` 中，对多种完全不同的模型配置运行了完整的拓扑评测：

```
untrained_arm2_seed0 : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
untrained_arm3_seed0 : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
untrained_arm4_seed0 : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
untrained_arm3_seed99: f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
trained_arm4_seed0   : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
trained_arm2_seed0   : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
trained_arm3_seed0   : f1=0.7500 (e3=1.0, nav=0.0, rel=1.0, time=1.0)
```

**实验结论**：随机初始化的模型、不同种子的模型、以及训练好的检查点，输出的拓扑 F1 分数在数值与子族分布上**完全一致**。
P55 作者发现的异常得到了完备的因果证明：该指标当前**不具备区分模型能力的有效性**，不得作为臂间优劣判定的有效依据。

---

## 4. 交付文件清单

本复核代理仅在 `reports/V9-P56/gemini-b4e7/` 下写入复核产物：
1. `reports/V9-P56/gemini-b4e7/REPORT.md`：本报告文本
2. `reports/V9-P56/gemini-b4e7/metrics.json`：结构化复核审计指标
3. `reports/V9-P56/gemini-b4e7/verify_p55.py`：11 个作业及继承关系自动化核验脚本
4. `reports/V9-P56/gemini-b4e7/verification_results.json`：自动化核验输出明细
5. `reports/V9-P56/gemini-b4e7/check_topology_anomaly.py`：拓扑 F1 退化根因实验复现脚本
6. `reports/V9-P56/gemini-b4e7/topology_anomaly_evidence.json`：拓扑 F1 退化实验详细数据

生产账本 SHA 维持原值 `7244149c2bb87096e0dacf75f7151f15c0253f4bd367b23d0ff456090a2d5f53`，未做任何修改。
综上，建议统筹者对 `ainerzero.V9.P55` 予以通过。
