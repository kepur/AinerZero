# 【L2·非作者代码复核报告】V9-mini 新潜空间对照组 latent_topo（SPTM 式拓扑记忆）

- 复核目标提交：`7c617f7e5b5c2f164d49b9c3a7b48219a73e0948`
- 复核代理：`gemini-k7a4`（二级执行代理，自报能力：code, math）
- 报告日期：2026-11-18
- 文件范围：`reports/V9-MINI/topo-review/`（只读复核，不改动 `src/`、`tests/` 及已有报告）

---

## 1. 必查项逐条核验

### 1.1 不用真值（Pass）

逐个调用点全面核查：
1. **训练阶段（`sample_reach`、`sample_loc`、`train_topo`）**：
   - `sample_reach`（`topo.py:89-110`）只读取 `ds.horizon`、`ds.n_traj` 生成时间索引 `t1`、`t2` 与二值标签 `y`，完全不触碰 `ds.pose`。
   - `sample_loc`（`topo.py:113-120`）只读取 `ds.horizon`、`ds.n_traj` 和智能体自身历史动作 `ds.act[i, t]`，完全不触碰 `ds.pose`。
   - `train_topo`（`topo.py:123-156`）仅对 `ds.obs` 和 `ds.act` 计算损失与反向传播，对 `ds.pose` 零引用。全文件搜索 `pose` 仅出现在注释与函数说明中。
2. **测试与评估阶段（`TopoAgent`）**：
   - `TopoAgent.reset(ep)`（`topo.py:267-286`）仅使用 `ep.prefix_obs`、`ep.prefix_acts`、`ep.goal_obs`，未读取 `ep.prefix_poses`、`ep.prefix_views` 或 `ep.prefix_heads`。
   - `TopoAgent.act(obs, view, head)`（`topo.py:337-343`）仅将传感器原始编码 `obs` 传入 `decide(obs)`，入参 `view` 与 `head` 被显式忽略。
3. **观察指纹与指南针朝向（`obs_keys`）**：
   - `obs_keys`（`topo.py:164-166`）直接对传感器原始输入向量 `obs` 做内存字节哈希（`tobytes()`）。
   - 由 `world.py:280-286`（`encode_obs`）可知，`obs` 由展平的局部视野 one-hot 与指南针朝向 one-hot 拼接而成。指南针朝向属于标准观测输入（所有 Baseline 均可获得）。
   - 若环境不同位置呈现完全一致的视野与朝向（感知混淆 / perceptual aliasing），`obs_keys` 会将其视为同一处。因此这是严格的传感器空间比对，绝非利用全局坐标或真值位姿。
4. **探索脚本诊断隔离（`topo_explore.py`）**：
   - 探索脚本中的真值位姿仅用于计算离线诊断指标（`loc_err`、`shortcuts_bad`、`goal_ok`）；
   - 特权控制（`--oracle-ctrl`）通过显式命令行标志控制，未侵入 `TopoAgent` 的默认路径（`ag.act(...)`）；在真实评测入口 `run.py` / `evaluate.py` 中完全没有真值特权。

---

### 1.2 正确性（Pass）

逐分支对抗审查：
1. **`sample_reach` 时间负例采样**（`topo.py:89-110`）：
   - 正例在 `[-k_pos, k_pos]` 内偏移并截断至 `[0, T]`，距离严格满足 $\le k_{pos}$；
   - 负例计算左右有效区间：左侧有效起点个数 `left = max(t1 - k_neg + 1, 0)`（对应 $[0, t1 - k_{neg}]$），右侧有效起点个数 `right = max(T - t1 - k_neg + 1, 0)`（对应 $[t1 + k_{neg}, T]$）；
   - 在总数 `tot = left + right` 内均匀随机生成离散索引 `u`，并分段映射回绝对时间步 `t2n`。区间无缝覆盖且严格满足 $|t1 - t2| \ge k_{neg}$，没有越界、截断偏置或采样不均。
2. **`build_graph` 记忆图拓扑构建与去重**（`topo.py:169-194`）：
   - 相邻帧：若观察相同（撞墙）连双向 `SAME` 边（代价 `w_same=0.01`）；观察不同连正向 `FWD`（代价 `1.0`）与逆向 `REV`（代价 `w_rev=3.0`）；
   - 跨步相同观察：按 `keys` 分组后，仅当 `abs(a - b) > 1` 时添加双向 `SAME` 边，避免与相邻撞墙边重复；
   - 学到的捷径边（`NEAR`）：严格检查 `gap >= cfg.min_gap`（默认 4）且 `keys[i] != keys[j]`，彻底排除了与相邻边（gap=1）和同一处边（SAME）重叠的可能，无重复边或冲突权重。
3. **图算法（`dist_to`、`hops`、`path_ahead`）**：
   - `dist_to`（`topo.py:197-219`）：在反向图 `rev` 上运行标准多源 Dijkstra，正确计算全图各节点到目标集合的单向最短距离；
   - `hops`（`topo.py:222-236`）：严格实现 0-1 BFS，`SAME` 边代价 0（`appendleft`），非 `SAME` 边代价 1（`append`），准确保证同一处跳跃不消耗步数邻域；
   - `path_ahead`（`topo.py:239-254`）：沿最短路前进最多 `h` 步，严格保持 `c <= d[v] + 1e-9` 贪心推进；并列时通过 `(c, -u) < (best[0], -best[1])` 优先选取较大编号节点，确定性地沿探索前缀向后延伸。
4. **定位逻辑（`_localize`）**（`topo.py:288-311`）：
   - 第一步：已知从前缀末帧出发，重置首帧标记后返回；
   - 相同观察帧：若有匹配帧落在 4 跳邻域内，取最小跳数（并列取大编号）；若均不在邻域，记为全图重定位并选用匹配帧；
   - 相似度定位：在 4 跳邻域内取 $R$ 最大节点，$\ge s_{loc}$ 即采纳；未达到则触发全图重定位，全图最大值仍不足则维持原估计。各分支逻辑闭环，无未处理异常。
5. **决策与期望更新（`decide`）**（`topo.py:313-335`）：
   - $\epsilon$-贪心输出随机动作；
   - 当前观察到目标画面 $R \ge s_{reach}$ 时直接发起 `goto None`（直奔目标）；
   - 沿最短路扫描：遇 `SAME` 边更新当前起点 `v = u` 并不消耗步数；遇 `FWD` 边更新 `self.expect = u` 并重放记下的动作 `acts[v]`（由于 `SAME` 跳过时已更新 `v = u`，重放动作帧索引完全精确）；遇 `REV` 或 `NEAR` 边交给运动网络并将期望锚定在当前节点 `self.expect = v`。

---

### 1.3 测试有效性与变异分析（Pass）

在完全隔离副本（`git archive 7c617f7e` 导出至临时目录，`PYTHONPATH=/tmp/topo_mutation_copy/src`）中执行了 4 处关键语义变异，全部成功导致测试失败：

1. **变异 1（破坏负例采样）**：将 `sample_reach` 中 `y` 强行置 1（无负例）。
   - 失败用例：`test_sample_reach_labels_follow_time_gap`
   - 捕获断言：`assert np.float32(1.0) < 0.6`
2. **变异 2（漏掉同一处边）**：移除 `build_graph` 中对跨步相同观察的 `SAME` 边构造。
   - 失败用例：`test_build_graph_edge_kinds_and_costs`、`test_dist_path_and_hops`、`test_agent_replays_prefix_to_goal`
   - 捕获异常：`KeyError: (0, 5)`、最短路断言失败、桩网络端到端重放异常
3. **变异 3（破坏 0-1 BFS）**：将 `hops` 中的 `0 if kind == SAME else 1` 改为普通 BFS `+ 1`。
   - 失败用例：`test_dist_path_and_hops`
   - 捕获断言：`assert (1 == 0)`（同一处边被错误计入跳数）
4. **变异 4（重放动作索引错误）**：在 `decide` 的 `FWD` 分支中取 `acts[u]` 代替 `acts[v]`。
   - 失败用例：`test_agent_replays_prefix_to_goal`
   - 捕获断言：`assert (0 == 1)`（未能在 3 步内重放到目标）

完整变异 Diff 与测试堆栈已归档至 [mutations.txt](mutations.txt)。

---

### 1.4 接线核查（Pass）

1. **种子与回合配对隔离**（`evaluate.py:160-184`）：
   - `evaluate.ARMS` 在元组中添加 `"latent_topo"`；
   - 在任务评估循环中，随机种子由 `s = seed * 100003 + ti` 严格由主种子与任务编号决定，与 `arms` 列表顺序及是否包含 `latent_topo` 没有任何偶联；
   - 各臂独立实例化、独立调用 `run_episode`，对既有基线组的任务序列、布局生成和评价结果零干扰。
2. **条件训练与预算开销**（`run.py:146-150`）：
   - 仅当 `"latent_topo" in arms` 时才触发 `train_topo`，若未指定该组则保持 `topo = None`，不额外消耗训练步数与运行时间。
3. **结果持久化**（`run.py:163`）：
   - `result.json` 正确新增 `"topo": tpinfo` 字段，记录拓扑网络参数量、训练配置与训练耗时。
4. **对比组配置**（`summarize.py:19`）：
   - `PAIRS` 新增 `("latent_topo", "latent_learned")` 与 `("map_hybrid", "latent_topo")`，实现了最佳拓扑潜空间 vs 原有最佳潜空间，以及度量几何地图 vs 拓扑潜空间的直接对照。

---

### 1.5 公平性评估（Pass）

`latent_topo` 是否给予潜空间一方充分合理的胜出机会：
1. **独立网络容量**：拓扑网络拥有专属独立编码器（MLP 64维嵌入），不与世界模型共享权重，避免了世界模型多任务压力对潜空间表征的潜在干扰（"给潜空间一方最好的机会"）。
2. **混合重放与学习**：沿探索前缀走过的正向边直接重放当时智能体自身的动作，只有在逆向或跨步捷径时才调用学习的运动网络 $L$。这极大降低了复合误差，赋予了潜空间拓扑记忆最强的执行保证。
3. **合理参数选择**：
   - 捷径边置信门槛 $s_{near}=0.95$、步长惩罚 $w_{near}=2.0$ 有效抑制了“虫洞”误连；
   - 逆向边惩罚 $w_{rev}=3.0$ 反映了转向后退的代价；
   - 局部邻域 $loc\_hops=4$ 配合 0-1 BFS，既保证了转身状态下的稳定定位，又避免了全图搜索漂移。
4. **结构性限制而非参数压制**：
   - 依据 `bounds.py` / `bounds2.py` 的真值上界诊断（见 §10.4），即便赋予完美的双向局部控制（$U_{both}$），以帧为节点的记忆图在 m1 上的长目标成功上限也只有 0.45，m2 仅为 0.10；而在实际前缀重放（$U_{fwd}$）下 m1 上限仅 0.20，m2 为 0.00。
   - 即便在特权控制（`--oracle-ctrl` 使用真值最短路代行局部控制）下，长目标成功率在 m1 仅达 0.125，m2 为 0。
   - 相对地，在短目标任务上 `latent_topo` 成功率从先前潜空间组的 ~0.10 显著提升至 ~0.50（m1: 0.533, m2: 0.483）。
   - 结论：`latent_topo` 绝非刻意削弱的“稻草人”，其长目标瓶颈源于拓扑记忆图无法外推未探索几何转移的固有数学局限，实现完全公平合理。

---

### 1.6 PLAN §10 数据独立复算与对账（Pass）

运行自主编写的重算脚本 [recheck.py](recheck.py)，输出结果见 [recheck.txt](recheck.txt)：

1. **成功率与回合数（独立读取 `episodes.json` 重算）**：
   - `m1-s0`（短目标 60 回合，长目标 40 回合）：
     - 短目标：$32 / 60 = 0.5333$（§10.3 记录：`0.533`，完全吻合）
     - 长目标：$3 / 40 = 0.0750$（§10.3 记录：`0.075`，完全吻合）
   - `m1-s0-nonear`（无捷径边）：
     - 短目标：$34 / 60 = 0.5667$（§10.3 记录：`0.567`，完全吻合）
     - 长目标：$1 / 40 = 0.0250$（§10.3 记录：`0.025`，完全吻合）
   - `m2-s0`（短目标 60 回合，长目标 68 回合）：
     - 短目标：$29 / 60 = 0.4833$（§10.3 记录：`0.483`，完全吻合）
     - 长目标：$0 / 68 = 0.0000$（§10.3 记录：`0`，完全吻合）
   - `m2-s0-nonear`（无捷径边）：
     - 短目标：$30 / 60 = 0.5000$（§10.3 记录：`0.500`，完全吻合）
     - 长目标：$0 / 68 = 0.0000$（§10.3 记录：`0`，完全吻合）
2. **$R$ 网络校准数据校验**（`m1-s0/result.json` 中 `calib` 字段）：
   - 同一位姿（0-0）：$p_{mean} = 0.9595$（PLAN：`0.96`）
   - 1–3 步（1-3）：$p_{mean} = 0.6637$（PLAN：`0.66`）
   - 4–6 步（4-6）：$p_{mean} = 0.1885$（PLAN：`0.19`）
   - 7 步以上（7-12 及 13-999）：$0.0156$ 与 $0.0027$（PLAN：`≤ 0.03`）
   - 全部统计数字与描述完全一致。
3. **上界诊断文件逐字比对**：
   - 重新执行 `bounds.py m1`、`bounds2.py m1`、`bounds.py m2`、`bounds2.py m2`，输出文本与 `reports/V9-MINI/explore/topo/bounds.txt` 进行 `diff -u`，结果差异为 0，逐字完全一致。
4. **批次探索抽查（`explore/topo-batch/`）**：
   - 抽查已完成的 `m1-s0` 与 `m1-s1`：
     - `m1-s0`: short=0.5333, long=0.0750
     - `m1-s1`: short=0.4833, long=0.0750
     - 批次实验显示拓扑潜空间短目标稳定在 ~0.50，长目标稳定在 $\le 0.08$ 水平。

---

## 2. 问题清单与严重程度评估

| 序号 | 模块 / 位置 | 问题与观察 | 严重程度 | 说明 / 处置建议 |
|---|---|---|---|---|
| 1 | `src/ainerzero/v9/mini/evaluate.py:153` | `run_episode` 中未提取 `agent.relocalizations` | **建议** | `TopoAgent` 维护了 `self.relocalizations`，但在统一 `run_episode` 仅收集了 `surprises` / `lost`。不影响功能与指标计算，建议若后续需对比定位稳定性时加入字典。 |
| 2 | `src/ainerzero/v9/mini/topo.py:301` | `_localize` 中相同画面不在邻域时回退取 `same[0]` | **建议** | 当存在多个相同观察帧且均不在 4 跳邻域时，默认取列表中第 0 个。在迷路全图重定位场景下虽属启发式兜底，但若按与 `expect` 的距离或 $R$ 排序更平滑。当前实现不构成阻断。 |

**阻断性缺陷数**：0 处。

---

## 3. 原始证据索引

所有行号与原句引用已完整收录于 [evidence/citations.txt](evidence/citations.txt)：
- 数据流隔离与无真值证据：`evidence/citations.txt:L1-L40`
- 图算法与决策分支源码证据：`evidence/citations.txt:L41-L95`
- 评估入口与接线证据：`evidence/citations.txt:L96-L130`
- PLAN §10 与 bounds.txt 原始文档证据：`evidence/citations.txt:L131-L240`

---

## 4. 复核结论

依据验收标准，结论为：

**1. 可以进确认段。**

（实现严格自监督不用真值，数学与图算法严密无误，变异测试全部有效拦截，各组接线完全隔离无副作用，且 §10 所有探索数据均经独立验证完全准确。）
