# S3-C1 r2 GridLab-S3 世界与生成器非作者复核报告

- **任务编号：** `ainerzero.V9.P205`
- **审查对象：** `ainerzero.V9.P203` (r2 返工提交)
- **依据文档：** `reports/V9-S3-DESIGN/DESIGN-r2.md`、`reports/V9-S3-C1/REPORT.md` (r2)、`reports/V9-S3-C1-review/REPORT.md` (r1 打回报告)
- **审查角色：** 二级执行 agent（`gemini-k8d4`，非 S3-C1 作者；纯 CPU，只读，零训练，零 MLX）
- **审查日期：** 2026-11-09
- **审查结论：`建议通过（RECOMMEND_ACCEPT）`**

---

## 执行摘要

1. **审查结论**：被检工作（`ainerzero.V9.P203` r2）严格、彻底地修复了 r1 审查打回指出的回合末端越界事件缺陷（$t=360$ 溢出），全量落实了一级统筹所立的 6 条必修项。在独立编写的 250 世界大规模暴力重算与边界断言测试中，**2431 个返回事件全部严格满足 $0 \le t < 360$ 与 $0 \le prev\_visit\_t < t$**，真值重算一致率达到 100.0%；跨版本比对证实**除 4 个越界事件被精确剔除外，底层步数据、特征观测与其余全部事件位级 100% 保持不变**；报告中所有数据均与落盘指标逐字吻合；3 项全新变异在隔离副本中均真实变红。本审查**建议通过（RECOMMEND_ACCEPT）**，S3 世界与生成器正式具备闭环入库条件。
2. **核心指标核实**：
   - 6 条必修项：逐条核验证据完整到位。
   - 250 世界（超额覆盖 200 世界要求）硬断言：违规次数为 **0**，越界事件彻底清零。
   - 行为不变性：对比 P204 审计的 60 个回合，步数据完全一致，无 $t=360$ 的 56 回合事件逐字一致，含 $t=360$ 的 4 个回合仅剔除该越界事件，无任何静默副作用。
   - 报告数字溯源：REPORT 与 `metrics.json` 之间 11 项统计标量与置信区间逐字逐数完全对齐。
   - 3 项自做全新变异：边界偏移、命名空间脱落、反向 BFS 逆向最大化，全量变红并落盘。

---

## 1. 六条必修项逐条核对

对照一级打回记录中的 6 条必修清单，逐条核查源码与实测证据：

| 必修项 | 要求 | 实现位置与核验实据 | 判定 |
|---|---|---|:---:|
| **① 根治 $t \ge \text{len(steps)}$** | `extract_readout_events` 严禁产生越界事件 | `src/ainerzero/v9/experiments/s3/tour.py:201-207`<br>`trajectory_positions` 严格取 `steps_data` 内坐标（长 360），`extract_readout_events` 输入严格对齐 `steps_data`；行 68 增加内部断言 `assert 0 <= prev_visit_t < t < n_steps` | **落实** |
| **② 增加硬断言与真值独立重算** | 全部事件 $0 \le t < \text{len(steps)}$、$0 \le prev\_visit\_t < t$（$\ge 100$ 世界）；用 steps 真值重算，不依赖轨迹数组 | `tests/v9/experiments/test_s3_events_bruteforce.py:71-139`<br>独立从 `steps[t]['truth']` 提取坐标重算，100 世界逐事件执行 `0 <= t < n_steps` 和 `0 <= prev_t < t` 硬断言 | **落实** |
| **③ 坏对照重新引入越界** | 重新引入越界并贴变红原始输出 | `reports/V9-S3-C1/mutations/m5_out_of_bounds_red.txt`<br>捕获 `AssertionError: Event count mismatch in world 11: actual 14 != expected 13`，真实变红 | **落实** |
| **④ 报告与指标数字一致性** | REPORT 与 `metrics.json` 事件数统一，由脚本生成 | `REPORT.md` 与 `metrics.json` 统一为 930 总事件、399 已换事件（比例 0.4290），消除手填冲突 | **落实** |
| **⑤ 500 世界规模复测与区间** | 在 $\ge 500$ 世界重测已换比例并报 95% 置信区间 | `REPORT.md` 与 `metrics.json` 汇报 500 世界、4803 个事件，已换比例 0.4220，95% CI 为 `[0.4081, 0.4361]`，全部处于 `[0.40, 0.60]` 门内 | **落实** |
| **⑥ 极短间隔事件分桶规约** | $\text{lag} < 8$ 事件 bucket 设为 None，文档写明不计入分桶 | `src/ainerzero/v9/experiments/s3/spec.py:67-72`<br>`get_bucket(lag)` 在 `lag < 8` 时返回 `None`；`REPORT.md` 与 `metrics.json` 详细记录 78 次极短事件并说明不参与分桶统计 | **落实** |

---

## 2. 250 世界独立边界断言与暴力重算

编写完全独立的审计脚本 `reports/V9-S3-C1-review-r2/independent_200_worlds_audit.py`，脱离生成器任何内部缓存，纯粹根据 `episode['steps'][:]['truth']['x', 'y']` 独立扫描重构 250 个全新世界（跨 F1 与 F2 族）：

### 2.1 实测统计数据
- **审计世界数：** 250 个独立世界（种子空间：`audit-p205`）
- **核验事件总数：** **2431 次**
- **最大时间步观察值：** **$t = 359$**（严格满足 $t \le 359 < 360$）
- **越界事件数（$t \ge 360$）：** **0 次**（彻底清零）
- **前次访问时序违规数（$prev\_visit\_t \ge t$ 或 $< 0$）：** **0 次**
- **暴力重算字段一致率（$t$, $cell$, $prev\_visit\_t$, $lag$, $bucket$, $swapped$, $answer$）：** **100.0%**（零误差）
- **极短间隔事件数（$\text{lag} < 8$）：** 35 次，全部严格满足 `bucket is None`
- **分桶事件分布：**
  - `short` (8–29): 164 次
  - `mid` (30–79): 807 次
  - `long` ($\ge 80$): 1425 次
- **总体已换比例：** **41.18%** (1001 / 2431)，稳居 $[40\%, 60\%]$ 合法区间

*审计结果落盘至：* `reports/V9-S3-C1-review-r2/audit_200_worlds.json`。

---

## 3. 行为不变性核查（Behavioral Invariance）

审查核心关切：**消除末端越界缺陷是否悄悄影响了环境动力学、RNG 序列或已有有效事件？**

编写 `reports/V9-S3-C1-review-r2/behavioral_invariance_check.py`，采用 P204 审计的 60 个随机种子回合进行逐字节比对：
- **步骤数据一致性：** 60/60 回合（100.0%）的全部 360 步 `obs`、`action`、`est_pose` 与 `truth` 位级**完全恒等**。
- **无 $t=360$ 回合的事件一致性：** 56 个在 r1 中未产生越界事件的回合，其产出的所有事件列表与 r1 **逐字逐数完全一致**。
- **曾发生 $t=360$ 的 4 个回合比对：**
  - `ep_2`：r1 包含 8 个事件，r2 包含 7 个事件，前 7 个事件逐字节一致，仅末尾非法事件（`t=360, cell=[3, 3]`）被精确切除。
  - `ep_24`：r1 包含 18 个事件，r2 包含 17 个事件，前 17 个事件完全一致，仅末尾非法事件（`t=360, cell=[23, 22]`）被精确切除。
  - `ep_27`：r1 包含 8 个事件，r2 包含 7 个事件，前 7 个事件完全一致，仅末尾非法事件（`t=360, cell=[23, 9]`）被精确切除。
  - `ep_40`：r1 包含 16 个事件，r2 包含 15 个事件，前 15 个事件完全一致，仅末尾非法事件（`t=360, cell=[9, 7]`）被精确切除。

*核验结论：修复手法干净利落，属于纯粹的区间端点规范化，无任何隐蔽动力学侧漏或随机数漂移。*
*核验记录落盘至：* `reports/V9-S3-C1-review-r2/invariance_check.json`。

---

## 4. 报告数字与落盘指标逐一溯源并列

对 `reports/V9-S3-C1/REPORT.md` 与 `reports/V9-S3-C1/metrics.json` 进行全指标逐项并列核对：

| 指标项 | REPORT.md 声明 | metrics.json 落盘数值 | 溯源校验结论 |
|---|---|---|:---:|
| 寻路到达率 | 175 / 175 (100.00%) | `probe_p_b_reachability.reachability: 1.0` (175/175) | **完全一致** |
| 100 世界唯一格中位数 | 112.0 | `probe_p_a_100_worlds.unique_cells_median: 112.0` | **完全一致** |
| 100 世界最常停留格最大占比 | 0.0528 (5.28%) | `probe_p_a_100_worlds.top_cell_fraction_max: 0.05277777777777778` | **完全一致** |
| 100 世界长间隔已换回合占比 | 98.0% (98/100) | `probe_p_a_100_worlds.long_swapped_episodes_fraction: 0.98` | **完全一致** |
| 100 世界总返回事件数 | 930 次 | `probe_p_a_100_worlds.total_events: 930` | **完全一致** |
| 100 世界已换事件数与比例 | 399 次, 0.4290 (399/930) | `swapped_events: 399`, `swapped_ratio: 0.4290322580645161` | **完全一致** |
| 500 世界规模总事件数 | 4803 次 | `scale_swap_test_500_worlds.total_return_events: 4803` | **完全一致** |
| 500 世界已换事件数与比例 | 2027 次, 0.4220 | `swapped_events: 2027`, `swapped_ratio_mean: 0.4220278992296481` | **完全一致** |
| 500 世界 95% 置信区间 | [0.4081, 0.4361] | `swapped_ratio_95_ci: [0.408127993018064, 0.43605243514499425]` | **完全一致** |
| lag < 8 极短事件计数 | 78 次 | `scale_swap_test_500_worlds.lag_less_than_8_events_count: 78` | **完全一致** |
| 事件步最大观察值 | 359 | `event_bounds_invariants.max_t_observed: 359` | **完全一致** |

---

## 5. 隔离副本 3 项自做全新变异测试

在独立沙盒 `/tmp/s3_p205_mutations/` 中实施 3 项**全新的独立对抗变异**，执行测试并录制原始错误日志：

### 5.1 MUT-A：在读回事件中故意偏移时间步（`tour.py:75`）
- **改动**：在记录事件时将 `t` 篡改为 `t + 1`，破坏端点约束。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_events_bruteforce.py::test_events_match_brute_force_and_hard_bounds_100_worlds
  AssertionError: Event 0 step t mismatch
  assert 78 == 77
  ```
- **日志**：`reports/V9-S3-C1-review-r2/mutations/mut_a_t_boundary_violation_red.txt`

### 5.2 MUT-B：种子派生脱落命名空间隔离（`data.py:24`）
- **改动**：将 `raw = f"{namespace}:" + ...` 改为固定前缀 `raw = "shared:" + ...`，破坏各分区互斥。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_partition_determinism.py::test_seed_namespaces_disjointness
  AssertionError: Cross-namespace seed collision between s3p1-train and s3p1-dev: {19389001, 22083818, ...}
  assert not {19389001, 22083818, 25099494, ...}
  ```
- **日志**：`reports/V9-S3-C1-review-r2/mutations/mut_b_cross_namespace_collision_red.txt`

### 5.3 MUT-C：反向 BFS 寻路决策颠倒为距离最大化（`world.py:140`）
- **改动**：在 `step_to_goal` 中将动作选取由最小化距离改为最大化距离（背离目标）。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_pathfinding.py::test_reverse_bfs_reachability_100_percent
  AssertionError: Pathfinding reachability failed: 0/175 (0.00%), required 100%
  assert 0.0 == 1.0
  ```
- **日志**：`reports/V9-S3-C1-review-r2/mutations/mut_c_maximize_distance_red.txt`

---

## 6. 最终审查结论

**结论：`建议通过（RECOMMEND_ACCEPT）`**。
S3-C1 r2 返工质量扎实，必修项全部闭环落实，边界硬断言坚实有效，行为不变性严密成立。各项指标与代码实现均完全达到进入后续拆卡（情景库参考实现与各臂开发）的标准。
