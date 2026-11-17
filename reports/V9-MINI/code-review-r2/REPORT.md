# V9-mini A27 修复（强连通判据、并图前整块碎片验证）非作者增量复核报告

- **任务编号**：`ainerzero.V9.A28`
- **复核者**：`antigravity-z7k4`（二级执行 agent，非作者）
- **会话指纹**：`sess-564b6267373e`
- **复核对象 Commit**：`c92c0abd5f855b00b7848d8a87cc0f9a561f56b6`
- **对比基线 Commit**：`6992312065d183d7fcc66733b20e2534907ab054`
- **复核文件范围**：`src/ainerzero/v9/mini` 与 `tests/v9/mini`
- **执行环境**：项目虚拟环境 `.venv/bin/python`（Python 3.12.2, MLX 0.32.2, pytest 9.1.1）
- **复核结论**：**可以冻结**（A27 发现的 F-01 切片类型阻断、F-02 强连通判据漏洞、F-04 假性并图错误均已彻底修复，全量 1230 图独立连通性审计 0 错误，实测复算指标与一代表格 100% 精确复现，变异测试全部按预期拦截）

---

## 1. 必查项审查结果与依据

### 必查项 1：强连通判据（`world.py` `_strongly_connected`）
- **定位**：`src/ainerzero/v9/mini/world.py:115-128`
- **数学等价性分析**：
  新判据代码如下：
  ```python
  free = [c for c in layout.free_cells() if layout.grid[c[1], c[0]] >= FLOOR0]
  start = (free[0][0], free[0][1], 0)
  reach = pose_bfs(layout, start)
  cells = {(p[0], p[1]) for p in reach}
  if not all(c in cells for c in free):
      return False
  back = reverse_bfs_to_cell(layout, free[0])
  return all(p in back for p in reach)
  ```
  1. **条件 1 (`all(c in cells for c in free)`)**：确保从 `start` 出发，全图每个自由地板格 $c \in \text{free}$ 都至少存在一个可达位姿 $(c_x, c_y, h) \in \text{reach}$。由于智能体原地转向（左转/右转）在任何位置均可行，因此从 $(c_x, c_y, h)$ 原地转向即可遍历该格的全部 4 个朝向。这证明全图所有自由地板格上的全部 $4 \times |\text{free}|$ 个位姿均在 `reach` 内（全局前向完全覆盖）。
  2. **条件 2 (`all(p in back for p in reach)`)**：确保 `reach` 中的每一个位姿都能通过反向 BFS 回到 `free[0]`。
  3. **传递性**：任意两个地板位姿 $p_1, p_2$ 均属于 `reach`。$p_1$ 可回到 `free[0]`，在 `free[0]` 原地转向调整至朝向 0 即可到达 `start`；从 `start` 出发又可到达 $p_2$。因此 $p_1 \to \text{start} \to p_2$ 恒成立。
  **结论**：该判据在数学上严格等价于“所有自由地板格两两强连通互达”。

- **独立全量 BFS 验证（不复用 `_strongly_connected`，从每个地板格逐格做 BFS）**：
  我们编写了独立校验脚本，遍历如下全部 1230 张地图：
  - 训练图：`7_100_000 + 1000 * s` 起各 200 张（$s=0..4$，共 1000 张）
  - 探索留出图：`7_900_000` 起 30 张
  - 确认段留出图：`8_000_000 + 1000 * s` 起各 40 张（$s=0..4$，共 200 张）
  *（严格遵守规则约束：对确认段留出图仅生成地图网格做连通拓扑校验，未在其上运行任何智能体、模型或评测任务）*
  - **实测结果**：
    - 检查地图总数：**1230 张**
    - `make_layout` 抛出 `RuntimeError` 次数：**0 次**
    - 独立双向连通性失败次数：**0 次**
    - 耗时：222.5 秒
  这证实新判据完全消除了 A27 中发现的单向死角房间（如传送门堵门），且生成树加门与重试机制十分充足，不会误拒合法布局。

---

### 必查项 2：并图校验（`mapagent.py` `_lost_step`、`_overlap`、`MERGE_MIN_OVERLAP`）
- **定位**：`src/ainerzero/v9/mini/mapagent.py:33, 164, 214-273`
- **审查与验证结论**：
  1. **`_overlap` 计数与越界处理**（第 275–285 行）：
     - `_overlap(fr, ox, oy)` 使用 `np.nonzero(fr.map != -1)` 提取碎片已知格，平移至 `(tx, ty)`。
     - 越界检查 `inb = (tx >= 0) & (tx < self.n) & (ty >= 0) & (ty < self.n)`：若 `not inb.all()`，立刻返回 `(0, 1)`（即 `bad = 1` 判定为严重冲突），彻底杜绝数组越界异常。
     - 重叠已知格 `both = mv != -1` 计算准确，冲突格计数 `(mv[both] != fr.map[ys, xs][both]).sum()` 精确无误。
  2. **`rejected` 集合生命周期闭环**：
     - 在 `reset()` 时初始化 `self.rejected = set()`（第 164 行）；
     - 在产生惊讶开新碎片时清空 `self.rejected = set()`（第 227 行）；
     - 在碎片内部发生自相矛盾重开新碎片时清空 `self.rejected = set()`（第 242 行）；
     - 在碎片成功合并至主地图时清空 `self.rejected = set()`（第 273 行）。
     生命周期转换无泄漏、无残留。
  3. **误判与作废路径分析**：
     - 若主地图先前由于某种极端原因写错了某个格，当新碎片探索到该格且颜色冲突时，该平移偏移会被记录至 `rejected`。但这属于防御性机制，防止主地图拓扑被二次错误污染。
     - 若智能体在碎片中遇到矛盾，会触发重开碎片并清空 `rejected`，赋予其重新纠错的机会。
  4. **取消整图唯一候选直接采用对 m1 的影响**：
     - 在 m1 世界中，所有物理动力学已知且为标准单步移动，解析先验预测 100% 精确，智能体每一步的 `check(view, pred)[1]` 恒为 0，**在 m1 下永远不会产生惊讶，永远不会触发开碎片或并图分支**。
     - 实测复算与单元测试证实，m1 下两臂长目标成功率均为 1.000，错误位姿步数为 0，完全无副作用。

---

### 必查项 3：复算一级报告数字（`pose_audit.py`）
使用项目虚拟环境 `.venv/bin/python`，遵守共享锁机制，对三组配置进行了完整复算：
- 产物目录：
  - `reports/V9-MINI/code-review-r2/audit_m2_s0_k12`
  - `reports/V9-MINI/code-review-r2/audit_m2_s0_k20`
  - `reports/V9-MINI/code-review-r2/audit_m1_s0_k20`

实测比对表：

| world | seed | min_overlap | arm | 一级报告 long_success | 实测 long_success | 一级 merges | 实测 merges | 一级 merges_wrong | 实测 merges_wrong | 一级 wrong_pose_steps | 实测 wrong_pose_steps | 吻合判定 |
| :---: | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **m2** | 0 | 12 | `map_analytic` | 0.544 | 0.544 (37/68) | 36 | 36 | 18 | 18 | 306 | 306 | **完全一致** |
| **m2** | 0 | 12 | `map_hybrid` | 0.838 | 0.838 (57/68) | 46 | 46 | 18 | 18 | 357 | 357 | **完全一致** |
| **m2** | 0 | 20 | `map_analytic` | 0.603 | 0.603 (41/68) | 36 | 36 | 0 | 0 | 30 | 30 | **完全一致** |
| **m2** | 0 | 20 | `map_hybrid` | 0.838 | 0.838 (57/68) | 34 | 34 | 0 | 0 | 65 | 65 | **完全一致** |
| **m1** | 0 | 20 | `map_analytic` | 1.000 | 1.000 (68/68) | 0 | 0 | 0 | 0 | 0 | 0 | **完全一致** |
| **m1** | 0 | 20 | `map_hybrid` | 1.000 | 1.000 (68/68) | 0 | 0 | 0 | 0 | 0 | 0 | **完全一致** |

**核心发现与分析**：
1. 当 `min_overlap=12` 时，analytic 和 hybrid 各发生 18 次错误并图，造成 306~357 步位姿错误；
2. 当 `min_overlap=20` 时，整块碎片一致性校验与重叠门槛发挥关键防御作用，**错误并图彻底降为 0**！位姿错误步数骤降至 30~65 步（仅为滑冰漂移期间尚未定位的短暂步数）；
3. 在 m1（确定性世界）下，analytic 先验解析零误差，merges 为 0，wrong_pose_steps 为 0，成功率保持 100%。

---

### 必查项 4：变异测试（Mutation Testing）
变异测试均在 `git archive c92c0abd` 导出的隔离副本目录（`/tmp/mini_mutation_r2`）中进行，执行环境为 `.venv/bin/python`，已通过检查 `__file__` 确认加载的是隔离副本源码。

| 变异代号 | 变异设计说明 | 预期效果 | 实测运行输出与断言捕获 |
| :--- | :--- | :--- | :--- |
| **Mut-A** (反向变异 1) | 将并图门槛改为 0：`MERGE_MIN_OVERLAP = 0` | 只有 5 格可见重叠即被放行，破坏整块碎片一致性防护 | `test_merge_waits_for_enough_overlap` 立即失败：`AssertionError: 重叠只有可见的 5 格，不够门槛，继续跟踪 (assert None is not None)` |
| **Mut-B** (反向变异 2) | 去除整块碎片冲突检查：忽略 `bad`，不将冲突偏移加入 `rejected` | 允许带冲突的碎片强行合并，破坏主地图一致性 | `test_merge_rejects_conflicting_offset` 立即失败：`AssertionError: 碎片与主地图冲突时不能并图 (assert None is not None)` |
| **Mut-C** (反向变异 3) | 连通性判据还原为旧版：删除 `all(c in cells for c in free)` 全局可达性检查 | 在存在单向死角的地图上误判通过 | `test_no_traps_with_ice_and_portals` 立即失败：`AssertionError: (0, (1, 1), 26)`，捕获到 seed 0 存在 26 格无法到达的孤立房间 |
| **Mut-D** (自主设计) | 越界检查失活：`_overlap` 中越界返回 `(0, 0)` 而非 `(0, 1)` | 越界偏移未被标记为冲突，可能引发越界访问或误判 | `test_overlap_counts_and_conflicts` 立即失败：`assert ag._overlap(fr, -1, 0)[1] == 1` 捕获 `assert 0 == 1` |

全部 4 项变异均精准触发预期断言失败，证实防护机制完备可靠。

---

### 必查项 5：测试覆盖与有效性（`test_mapagent.py`）
- `test_merge_rejects_conflicting_offset`：显式构造 5×5 重叠中包含 1 格墙体冲突，断言 `ag.frag is not None`、偏移进入 `rejected`、主地图未被篡改。
- `test_merge_waits_for_enough_overlap`：显式构造仅有 5 格视野重叠（无冲突），断言即使唯一候选也不提前并图，维持跟踪。
- `test_merge_when_consistent_and_enough_overlap`：显式构造 25 格重叠且 0 冲突，断言顺利完成并图且智能体位姿精准更新。
- 3 个测试分别覆盖了冲突拒绝、充分性门槛等待、一致性并图三大互斥分支，逻辑完备，无巧合通过情况。

---

## 2. 问题清单（缺陷评级）

- **阻断问题（Blocker）**：0 项。
- **应修问题（Should Fix）**：0 项。
- **建议项（Suggestion）**：0 项。

---

## 3. 最终复核结论

**结论**：**【可以冻结】**。

**结论依据**：
1. A27 发现的 3 个主要问题（F-01 切片类型隐患、F-02 强连通判据漏洞、F-04 假性并图错误）在提交 `c92c0abd` 中得到高质量且彻底的修复；
2. 数学证明与 1230 张全量地图的独立 BFS 检验双重证实强连通判据的完备性与正确性；
3. 实测复算与一级报告指标 100% 精确一致，证实门槛 20 下错误并图完全为 0；
4. 4 项针对性变异测试均按预期触发断言失败，测试套件防御能力坚实；
5. 主工作树 `src/` 与 `tests/` 无任何未提交改动，所有验证均在隔离副本或独立结果目录中完成，符合无破坏复核规范。
