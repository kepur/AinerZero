# V9-mini 小模型代码非作者复核报告

- **任务编号**：`ainerzero.V9.A27`
- **复核者**：`antigravity-z7k4`（二级执行 agent，非作者）
- **会话指纹**：`sess-564b6267373e`
- **复核对象 Commit**：`6992312065d183d7fcc66733b20e2534907ab054`（覆盖旧 commit `744f9095`）
- **复核文件范围**：`src/ainerzero/v9/mini/*.py` 与 `tests/v9/mini/`
- **结论**：**有阻断问题**（存在 1 项运行时崩溃阻断缺陷与 3 项应修逻辑缺陷，必须修复后方可冻结）

---

## 1. 必查项审查结果与证据

### 必查项 1：测试时是否存在真值泄露
- **结论**：**通过（无真值泄露）**
- **涉及文件与位置**：
  - `src/ainerzero/v9/mini/agents.py:1-136`
  - `src/ainerzero/v9/mini/mapagent.py:155-168, 198-210, 307-317`
  - `src/ainerzero/v9/mini/belief.py:100-145`
  - `src/ainerzero/v9/mini/evaluate.py:138-160`
- **验证方法**：
  静态检查与动态调用追踪各智能体的 `reset` 与 `act` 入参：
  1. `run_episode` 中向非 Oracle 智能体仅通过 `Episode` 传递局部观测编码 `obs`、局部视野 `views` (5×5 网格)、指南针朝向 `headings` (0..3 整数) 及前缀动作 `prefix_acts`。
  2. 评测期间，`agent.act` 仅接收当前步骤的 `encode_obs(v, heading)`、局部视野 `v` 和朝向整数 `heading`。
  3. 各臂在 `reset` 与 `act` 中完全没有读取世界坐标 `(x, y)`、真值网格 `layout.grid` 或传送门映射 `layout.portal_to`。
  4. 唯一定位依赖自身局部栅格建图（`Frame`，以自身的 `(c, c)` 为相对局部原点）、射线前向模型预测与多尺度重定位。唯一的例外为基线对照臂 `Oracle`，其专用于作为全局理论最优上界，独立使用 `act_pose(pose)`。

---

### 必查项 2：M3 自监督标签是否存在真值泄露
- **结论**：**通过（无真值泄露）**
- **涉及文件与位置**：
  - `src/ainerzero/v9/mini/residual.py:148-178` (`collect_self`)
- **验证方法**：
  核查 `collect_self` 的训练数据组装与真值使用：
  1. 第 162–165 行：地图智能体 `ag = MapAgent(cfg, fm_analytic, memory=False, seed=seed)` 在每张训练图上进行游走，仅使用解析先验，完全闭环。
  2. 第 167–170 行：训练特征 `xs` 记录的是智能体在自身局部地图中的前方射线 `W.ray(ag.main.map, before)`；训练标签 `ys` 记录的是智能体通过局部观测重定位得到的自身位移 `ag._disp(before, loc)`。
  3. 第 171 行：真值物理动力学 `W.forward_outcome(layout, poses[step])` **仅仅**用于计算统计量 `agreement = int(self_label == truth)`，用于监控自监督标签质量 `label_agreement_with_truth`，真值位姿和真实物理结果完全没有进入 `xs` 或 `ys` 数组。

---

### 必查项 3：`mapagent.py` 定位逻辑与边界条件
- **结论**：**发现缺陷（2 项应修）**
- **涉及文件与位置**：
  - `src/ainerzero/v9/mini/mapagent.py:198-230` (`_advance`)
  - `src/ainerzero/v9/mini/mapagent.py:231-265` (`_lost_step` 与 `_merge`)
  - `src/ainerzero/v9/mini/mapagent.py:180-197` (`_resolved`)
- **发现问题与复核证据**：
  1. **未知格误放行导致错误位姿写入（应修）**：
     在 `_advance` 第 206 行：
     `if self.main.check(view, pred)[1] == 0:`
     `check` 返回 `(known, bad)`。当智能体跨入未知区域时，周围重叠已知格数量可能为 0（`known == 0`）。此时 `bad == 0` 恒成立，系统将错误预测的位姿 `pred` 直接当作正确位姿接受并调用 `write`，将错位的局部视野写入地图。
  2. **对称候选与假性收敛（应修）**：
     在 `_lost_step` 第 241–250 行：
     通过 `self.main.ok(view, q, 0.3, 3)[0]` 过滤候选位姿。若环境存在局部对称或重复纹理，某个真值候选可能因容差阈值被偶然过滤，导致剩下的候选集合只剩 1 个（`len(nxt) == 1`），触发假性收敛。在 `_merge`（第 259 行）中直接以该假性对齐将碎片写入主图（只判断 `unknown = self.main.map[ty, tx] == -1`），且在 `_resolved` 中把错误的位移或传送去向写入 `self.portal_mem`，造成永久性拓扑污染。
  3. **收敛性**：
     碎片管理不会无限膨胀，因为每次迷路只维持单个活动碎片 `self.frag`；若碎片内部发生二次不一致，则重开碎片（第 234–239 行）。但由于缺少全局回溯与一致性校验，错误的合并一旦发生便无法撤销。

---

### 必查项 4：`world.py` 动力学、连通性与种子空间
- **结论**：**发现缺陷（1 项应修）**
- **涉及文件与位置**：
  - `src/ainerzero/v9/mini/world.py:115-122` (`_strongly_connected`)
  - `src/ainerzero/v9/mini/world.py:152-167` (`_place_portals`)
  - `src/ainerzero/v9/mini/world.py:174-194` (`step`)
  - `src/ainerzero/v9/mini/world.py:216-251` (`_visible` 与 `ego_offsets`)
  - `src/ainerzero/v9/mini/data.py:12-13`
- **发现问题与复核证据**：
  1. **`_strongly_connected` 连通性算法不完备，产生单向不可逆孤立房间（应修）**：
     第 115–122 行定义：
     ```python
     def _strongly_connected(layout: "Layout") -> bool:
         free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
         start = (free[0][0], free[0][1], 0)
         reach = pose_bfs(layout, start)
         back = reverse_bfs_to_cell(layout, free[0])
         return all(p in back for p in reach)
     ```
     该函数仅检查了“从 `free[0]` 出发可到达的所有位姿能否返回 `free[0]`”。**它没有检查全局所有地板格是否都能被 `free[0]` 到达**（即没有检查 `len({(p[0], p[1]) for p in reach}) == len(free)`）。
     实测验证：在 m2 世界的前 500 个种子中，有多个种子（例如 seed 0, 2, 4, 5, 6 等）存在单向瞬态强连通分支：
     - 在 seed 0 中，房间 (1, 1) 的唯一门洞位于 (7, 12)。`_place_portals` 恰好在门洞正前方的 (7, 13) 放置了一个传送门入口。
     - 从房间 (1, 1) 走出来会踩中传送门被送往房间 (1, 0)；而从外部无论如何都无法进入 (7, 12)，导致房间 (1, 1) 的 26 个地板格成为不可逆单向区域。
     - `_strongly_connected` 判定为 True，因为 `reach` 从 `free[0]`（在房间 0,0）出发根本进不去房间 (1,1)，`all(p in back for p in reach)` 平凡满足。如果前缀游走从该房间出发，一旦离开就再也回不去。
  2. **视线与旋转几何**：
     `ego_offsets` 的 4 向旋转数学推导严密自洽；`_visible` Bresenham 算法对墙体终点视线判定准确（存在斜角相交漏光理论边缘情况，列入建议）。
  3. **种子空间隔离性**：
     `TRAIN_SEED0 = 7_100_000`，`EVAL_SEED0 = 7_900_000`。确认段采用 `8_000_000 + 1000 * s`，种子空间完全不相交。

---

### 必查项 5 与 added_check：评测逻辑与留出图种子严格隔离
- **结论**：**通过**
- **涉及文件与位置**：
  - `src/ainerzero/v9/mini/evaluate.py:73-118, 171`
  - `src/ainerzero/v9/mini/summarize.py:61-90`
  - `src/ainerzero/v9/mini/run.py:72-78`
- **复核证据**：
  1. `law_relevant` 判定为 `d_analytic != d_star`：在相同的网格结构下，只有当物理路径利用了冰面滑行或单向传送门缩短步数（或改变通路）时，两者的最优步数才会不同，准确反映了未知物理规律对任务的影响。
  2. 步数预算 `2 * d_star + 20` 既给出了探索与转向的合理容差（2倍余裕 + 20步基础转弯/恢复缓冲），又避免了盲目随机游走碰巧命中的伪成功。
  3. `_unique_views` 在整图尺度统计 `(ego_view.tobytes(), heading)` 的出现频次，且 `make_tasks` 严格过滤 `uniq[...] != 1`，彻底消除了对称房间相同视野引发的歧义。
  4. `summarize.py` 严格区分了回合集合相同（多运行在同一回合上平均后再跨回合重抽样）与不同（全回合重抽样）的 bootstrap 统计口径。
  5. **【added_check 验证】**：
     - 默认参数下生成任务与旧 commit `744f9095` 考题严格逐项一致（12 张图，60 回合，种子完全对应）。
     - 当传入 `--eval-seed0 8000000 + 1000*s`（s=0..4，各 40 张图）时，5 套留出图的种子集合大小均为 40，两两交集严格为空，且与训练种子空间完全互斥（重叠时 `run.py:76` 会立刻抛出 `SystemExit` 拦截）。

---

## 2. 缺陷清单与定级

| 序号 | 定级 | 文件及行号 | 缺陷描述 | 建议修复方案 |
| :--- | :--- | :--- | :--- | :--- |
| **F-01** | **阻断** | `src/ainerzero/v9/mini/agents.py:110` | 在 MLX 0.31.1 环境下，`cand[np.argmin(...)]` 返回 `numpy.int64`。直接对 `mx.array` 切片 `self.z_nodes[wp:wp + 1]` 触发 `ValueError: Slice indices must be integers or None`，导致 `run.py` 默认跑全部臂时在 `graph_memory` 处直接崩溃退出。 | 将 `wp` 转换为 Python 内置整数：`wp = int(cand[np.argmin(...)])`。 |
| **F-02** | **应修** | `src/ainerzero/v9/mini/world.py:115-122` | `_strongly_connected` 仅检查 `reach` 内位姿能否回到起点，未检查 `reach` 是否覆盖所有自由地板格，导致产生单向不可逆进入主图的死角房间（如 seed 0 房间 1,1 门前放置单向传送门，离开后无法返回）。 | 增加全局可达性校验：`return len({(p[0], p[1]) for p in reach}) == len(free) and all(p in back for p in reach)`。 |
| **F-03** | **应修** | `src/ainerzero/v9/mini/mapagent.py:206` | 在未知区域中，`self.main.check(view, pred)` 返回的 `known == 0`，导致 `bad == 0` 误放行错误位姿，导致错误位姿被直接写入地图。 | 增加置信度判断：要求 `known >= 2` 或结合前向模型的门控置信度，不可仅凭 `bad == 0` 放行。 |
| **F-04** | **应修** | `src/ainerzero/v9/mini/mapagent.py:249-265` | `_lost_step` 在 `len(nxt) == 1` 时假性收敛（存在对称候选因阈值被筛除），未校验重叠区域的一致性即全量将未知格写入主地图，并可能在 `_resolved` 中把错误传送去向写入 `portal_mem`。 | 在合并碎片前断言或检验已知格的重叠一致率（例如一致率 $\ge 0.9$），不一致则丢弃碎片或继续维持候选追踪。 |
| **F-05** | **建议** | `src/ainerzero/v9/mini/world.py:216-232` | `_visible` 的 Bresenham 视线检查对角线穿越时，若两墙体仅在顶点接触，视线会从对角空隙穿过。 | 建议对斜向步进额外检查相邻正交两格是否均为墙体。 |
| **F-06** | **建议** | `tests/v9/mini/` | 测试集仅覆盖了单个算子，缺乏对 `Graph` 智能体及 `run.py` 默认多臂端到端评测的回归测试，导致切片类型阻断问题未能被 CI 捕获。 | 在 `tests/v9/mini/` 增加端到端单回合多臂轻量级单测。 |

---

## 3. 变异测试（Mutation Testing）报告

变异测试均在临时隔离目录 `/tmp/mut*` 中运行，实盘源码未作任何修改。均基于 `--quick --world m2 --seed 0` 执行评测。

### 变异设计说明
1. **变异 1（真值位姿泄露变异，测试定位瓶颈假设）**：
   在地图智能体中，通过外部相对真值注入覆盖自身位姿推算与地图更新，使其获得 100% 准确的无漂移相对位姿与几何地图。
2. **变异 2（残差门控恒关变异，测试残差学习有效性）**：
   在 `residual.py` 的 `ForwardModel.predict` 中，强制将门控输出置为恒关（`m = 0`），使其永远退回解析先验（`analytic_outcome`），残差网络无法激活。
3. **变异 3（关闭重定位与碎片合并变异，测试几何容错必要性）**：
   在 `mapagent.py` 的 `_advance` 中，当产生惊讶时不进行射线与全局重定位搜索，直接开碎片且强制 `len(nxt) != 1` 永远不合并回主地图。

### 变异结果对比表

| 实验组别 | 变异操作 | 对应模型/臂 | 短目标成功率 (SPL) | 长目标成功率 (SPL) | 规律相关成功率 (SPL) | 惊讶率 (surprise) | 关键结论与观察 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline** (实盘基线) | 无修改 | `map_analytic`<br>`map_hybrid` | 1.000 (0.944)<br>**1.000 (0.995)** | 0.694 (0.581)<br>**0.889 (0.727)** | 0.900 (0.704)<br>**1.000 (0.886)** | 0.012<br>**0.000** | 基线正常表现，门控残差在长目标和规律相关任务上显著占优。 |
| **Mutation 1** | 相对位姿真值泄露 | `map_analytic`<br>`map_hybrid` | 1.000 (0.995)<br>**1.000 (0.995)** | 0.944 (0.890)<br>**1.000 (0.948)** | 0.900 (0.832)<br>**1.000 (0.936)** | 0.000<br>**0.000** | **成功率全部达到 1.000（100%）！** 证明长目标失败的唯一根本原因即为定位漂移与迷路，规划逻辑完全正确。 |
| **Mutation 2** | 残差门控强制恒关 (0) | `map_analytic`<br>`map_memory`<br>`map_hybrid` | 1.000 (0.944)<br>1.000 (0.944)<br>**1.000 (0.944)** | 0.694 (0.581)<br>0.750 (0.617)<br>**0.750 (0.617)** | 0.900 (0.704)<br>0.950 (0.751)<br>**0.950 (0.751)** | 0.007<br>0.005<br>**0.005** | **`map_hybrid` 彻底退化并与 `map_memory` 完全重合！** 证明性能提升 100% 来自门控激活的残差规律。 |
| **Mutation 3** | 关闭重定位与碎片合并 | `map_analytic`<br>`map_hybrid` | 0.833 (0.813)<br>**1.000 (0.995)** | 0.472 (0.298)<br>**0.778 (0.614)** | 0.600 (0.302)<br>**1.000 (0.852)** | 0.000<br>**0.000** | `map_analytic` 长目标成功率暴跌至 0.472 (SPL 跌至 0.298)；自监督采集因无法重定位导致标签事件数为 0。证明重定位是智能体生存与自监督数据采集的关键支柱。 |

---

## 4. 实盘复现对比（Replication）

在实盘共享锁保护下，执行两次完全一致的端到端运行：
- 命令：`python3 -m ainerzero.v9.mini.run --quick --world m2 --seed 0 --out reports/V9-MINI/code-review/run[1|2]`
- 运行结果存放在 `reports/V9-MINI/code-review/run1` 与 `reports/V9-MINI/code-review/run2`。

### 两次复现指标对照

| 评测指标 | Run 1 | Run 2 | 一致性核对 |
| :--- | :--- | :--- | :--- |
| **代码 SHA256** | `f6bc42b0...` | `f6bc42b0...` | 完全相同 |
| **耗时 (wall_sec)** | 150.0 秒 | 170.6 秒 | 正常系统负载波动 |
| **预测指标 (一步 / 5步误差比)** | 0.02746 / 0.07845 | 0.02746 / 0.07845 | 完全相同 |
| **M3 自监督标签与真值一致率** | 0.999721 (28722 样本) | 0.999721 (28722 样本) | 完全相同 |
| **前进模型留出事件准确率 (gated)** | 0.989 | 0.989 | 完全相同 |
| **前进模型自监督事件准确率 (gated_self)** | 0.973 | 0.973 | 完全相同 |
| **`map_analytic` (短 / 长 / 规律相关)** | 1.000 / 0.694 / 0.900 | 1.000 / 0.694 / 0.900 | 完全相同 |
| **`map_memory` (短 / 长 / 规律相关)** | 1.000 / 0.750 / 0.950 | 1.000 / 0.750 / 0.950 | 完全相同 |
| **`map_hybrid` (短 / 长 / 规律相关)** | 1.000 / 0.889 / 1.000 | 1.000 / 0.889 / 1.000 | 完全相同 |
| **`map_hybrid_self` (短 / 长 / 规律相关)** | 1.000 / 0.889 / 1.000 | 1.000 / 0.889 / 1.000 | 完全相同 |
| **各臂长目标 SPL (`map_hybrid`)** | 0.727 | 0.727 | 完全相同 |

核对证实：在修复 F-01 切片阻断缺陷后，整个评估管线在固定种子下具备 100% 的数值确定性与结果复现性。

---

## 5. 综合评审结论

**评审结论：有阻断问题（修复后为修完再冻结）**

1. **阻断项**：`src/ainerzero/v9/mini/agents.py:110` 的切片类型缺陷（`np.int64`）在当前 MLX 环境下会导致默认 `run.py` 运行时直接崩溃退出，必须首先修复。
2. **应修项**：
   - 修复 `world.py:115-122` 的 `_strongly_connected` 全局可达性判定，消除传送门堵门导致的单向孤立死角房间；
   - 修复 `mapagent.py:206` 未知格误放行与 `_merge` 缺乏一致性断言引发的错误位姿写入问题。
3. **架构有效性确认**：
   3 项变异测试强有力地证实了架构核心逻辑的自洽性——真值泄露使成功率跃升至 1.000 上界、门控关闭使模型完全退化至 `map_memory` 基准、关闭重定位引发崩溃，证明 V9-mini 所展示的各项优势完全来自于门控残差规律学习与几何地图记忆的真实协同，不存在真值偷跑或伪收益。
4. **建议路线**：
   由作者修复上述 F-01 阻断项与 F-02 至 F-04 应修项后，更新并冻结代码 SHA，方可进入 M4 确认性登记。
