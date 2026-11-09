# S3-C1 GridLab-S3 世界与生成器非作者独立审查报告

- **任务编号：** `ainerzero.V9.P204`
- **审查对象：** `ainerzero.V9.P203`（gemini-76e7 提交的 S3-C1 代码与报告）
- **依据文档：** `reports/V9-S3-DESIGN/DESIGN-r2.md`、`reports/V9-S3-C1/REPORT.md`
- **审查角色：** 二级执行 agent（`gemini-k8d4`，非 S3-C1 实现作者；纯 CPU，只读，零训练，零 MLX）
- **审查日期：** 2026-11-09
- **审查结论：`打回（REJECT / 建议修复末端边界并升版至 C2）`**

---

## 执行摘要

1. **审查结论**：S3-C1 整体架构设计优秀，完全摆脱了 S2 的寻路缺陷，成功实现了基于反向多源 BFS 的巡游生成器与 198 维无泄漏学生观察规范。但在独立暴力校验中，**发现了一个关键的越界缺陷（Off-by-One Boundary Defect）**：在约 6.7% 的回合中，生成器在 $t = 360$（回合终止后）记录了返回事件，而 `episode['steps']` 仅有 360 步（索引 $0 \dots 359$），下游训练或评测代码在索引 `steps[ev['t']]` 时将直接崩溃报 `IndexError: list index out of range`！作者现有的单元测试因直接复用 361 长的 `trajectory_positions` 进行核对而形成了测试盲区。故判定**打回（REJECT）**，须进行单点修复并补齐测试。
2. **核心核查事实**：
   - **禁忌与隔离核实**：零调用 `s2.data._find_path_step`、零调用 `run_episode`；未改动任何 S2 文件；反向多源 BFS 正确建立在逆向位姿图 $G^{rev}$ 上。
   - **100 世界独立重测**：寻路到达率 **500/500 (100.0%)**；不同格中位数 **112.0**（门槛 $\ge 60$）；最常停留格最大占比 **6.37%**（门槛 $\le 15\%$）；长间隔已换回合占比 **99.0%**（门槛 $\ge 90\%$）；已换比例 **42.14%**（门槛 $[40\%, 60\%]$）。指标全量达标并与作者报告吻合。
   - **4 项全新变异（抗伪对照验证）**：在隔离副本独立实施 4 项全新变异（允许相同 token、绕过 final 分区保护、答题 token 颠倒、缺失 NONE token 维度），全量真实变红，原始日志全部落盘。
   - **观察泄漏排查**：198 维观察经逐维审查，无绝对坐标、无真实朝向泄漏、无换 token 状态泄漏。
   - **DESIGN-r2 改动审查**：r2 采用 F1 与 F2 不相交 token 集彻底消除了 r1 中规则冲突导致的 H3 恒假陷阱；198 维算术完全正确。

---

## 1. 禁忌调用与文件隔离核查

| 核查项 | 规矩 / 要求 | 实测排查结果 | 判定 |
|---|---|---|:---:|
| `s2.data._find_path_step` | 严禁调用（S2 寻路缺陷函数） | 全局检索 `_find_path_step`，S3 源码及测试中为 **0 处** | **通过** |
| `s2.data.run_episode` | 严禁调用（S2 旧生成器入口） | 全局检索 `run_episode`，S3 源码及测试中为 **0 处** | **通过** |
| `s2.data` 模块导入 | 严禁依赖 | S3 仅从 `s2.world` 导入基础地图与模拟基语，无 `s2.data` 导入 | **通过** |
| 正向 BFS 当距离 | 严禁正向 BFS 贪心寻路 | `s3/world.py:82` 实现 `compute_reverse_bfs_distances`，为逆向边扩展 | **通过** |
| S2 源码修改排查 | 严禁修改任何 S2 文件 | `git status -- src/ainerzero/v9/experiments/s2/` 干净，mtime 无变动 | **通过** |

---

## 2. 100 世界独立重测结果并列

在独立编写的测试脚本 `reports/V9-S3-C1-review/independent_benchmark.py` 中，对 100 个全新独立世界（种子隔离）进行端到端重测，实测指标与作者报告对比如下：

| 指标 | 门槛要求 (DESIGN-r2 §5) | 作者报告值 (P203) | 复核独立实测值 (P204) | 判定 |
|---|---|:---:|:---:|:---:|
| **P-b 寻路到达率** | 100.00% (无噪声) | 175 / 175 (100.0%) | **500 / 500 (100.0%)** | **达标** |
| **P-a 不同格子中位数** | $\ge 60$ | 112.0 | **112.0** (min=67, max=154) | **达标** |
| **P-a 最常停留格占比最大** | $\le 0.15$ (15.0%) | 0.0526 (5.26%) | **0.0637** (6.37%) | **达标** |
| **P-a 长间隔已换回合比例** | $\ge 90.0\%$ | 98.0% | **99.0%** (99 / 100) | **达标** |
| **P-a 总体返回事件已换比例** | $0.40 - 0.60$ | 0.4274 | **0.4214** (418 / 992) | **达标** |
| **P-a 总返回事件数** | 保证充足统计量 | 557 次 (5.57/集) | **992 次** (9.92/集) | **达标** |

*注：独立重测寻路样本扩充至 100 世界 × 5 目标 = 500 个目标，到达率保持坚挺的 100.0%。*

---

## 3. 暴力校验标签与越界缺陷发现

在独立脚本 `reports/V9-S3-C1-review/bruteforce_label_audit.py` 中，抽取 60 个随机回合（跨 F1 与 F2 族）对 566 个事件进行自底向上的第一性原理重算：

### 3.1 正常步内事件计算一致性
对所有处于有效步范围（$t \in [1, 359]$）的 562 个事件：
- `prev_visit_t`：重算一致率 **100%**
- `lag`：重算一致率 **100%**
- `swapped`：重算一致率 **100%**
- `answer`：重算一致率 **100%**
- `bucket`：重算一致率 **100%**
- 对应坐标 `cell` 与 `steps[t]['truth']`：重算一致率 **100%**

### 3.2 发现的关键缺陷：回合末端越界事件（Off-by-One Boundary Defect）
- **现象**：在 60 个回合中，有 **4 个回合（约 6.7%）** 记录了 `t = 360` 的返回事件！
  - 示例（`ep_2`）：`{'t': 360, 'cell': [3, 3], 'prev_visit_t': 280, 'lag': 80, 'bucket': 'long', 'swapped': False, 'answer': 6}`
- **崩溃复现**：
  在生成的数据集字典中，`len(episode['steps']) == 360`（即步索引仅到 359）。
  当执行模型标准读回循环：
  ```python
  for ev in episode["events"]:
      obs = episode["steps"][ev["t"]]["obs"]  # 当 ev['t'] == 360 时崩溃！
  ```
  直接抛出异常：
  ```text
  IndexError: list index out of range
  ```
- **成因分析**：
  在 `src/ainerzero/v9/experiments/s3/tour.py` 中：
  1. `trajectory_positions` 初始包含 0 步坐标，经过 360 步环境交互后，列表长度为 **361**（包含第 359 步动作执行后到达的终态坐标）；
  2. 第 189 行调用 `extract_readout_events(trajectory_positions, content_state)` 时，循环范围为 `range(1, len(trajectory_positions))`，包含了索引 `t = 360`；
  3. 若智能体在第 359 步的动作正好移动到内容格，则会被当作事件记录为 `t = 360`；
  4. 但 `steps_data` 在循环结束时只有 360 条记录（$t = 0 \dots 359$），并未记录第 360 步的观察；
  5. 作者原测试 `test_s3_events_bruteforce.py` 同样直接拿 361 长的 `trajectory_positions` 去复算，形成了测试闭环假象，未对 `ev['t'] < len(steps)` 做硬断言。

---

## 4. 隔离副本 4 项全新变异（拒绝伪坏对照）

为防止被测代码存在针对作者预设坏对照的特异性防御，本审查在隔离副本 `/tmp/s3_p204_mutations/` 中实施了 **4 项全新的自做变异**，执行真实测试并录制原始日志（保存在 `reports/V9-S3-C1-review/mutations/`）：

### 4.1 MUT1：允许新 Token 与初始 Token 相同（`content.py:126`）
- **改动**：将 `candidate_news = [tok for tok in family_tokens if tok != t_init]` 改为 `t_new = rng.choice(family_tokens)`。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_content_independence.py::test_content_invariants_and_token_families
  AssertionError: new_token 8 equals initial_token 8 at (2, 18)
  assert 8 != 8
  ```
- **日志**：`reports/V9-S3-C1-review/mutations/mut1_allow_same_token_red.txt`

### 4.2 MUT2：移除 final 分区默认拒绝守卫（`data.py:131`）
- **改动**：注释掉 `if namespace == spec.NAMESPACE_FINAL and not allow_final: raise PermissionError`。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_partition_determinism.py::test_final_partition_refusal_by_default
  Failed: DID NOT RAISE <class 'PermissionError'>
  ```
- **日志**：`reports/V9-S3-C1-review/mutations/mut2_remove_final_protection_red.txt`

### 4.3 MUT3：读回事件答案颠倒为当前观察（`tour.py:77`）
- **改动**：将 `events.append({"answer": tok_prev, ...})` 改为 `"answer": tok_now`。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_events_bruteforce.py::test_events_match_brute_force_identical
  AssertionError: Event 1 answer mismatch
  assert 3 == 8
  ```
- **日志**：`reports/V9-S3-C1-review/mutations/mut3_corrupt_answer_token_red.txt`

### 4.4 MUT4：观察中遗漏 NONE_TOKEN 维度（`world.py:269`）
- **改动**：将 token one-hot 长度改为 `spec.NUM_TOKEN_CLASSES - 1`，导致总维度从 198 缩水为 189。
- **实测结果**：**变红 (RED)**。
- **报错输出**：
  ```text
  FAILED tests/v9/experiments/test_s3_obs_spec.py::test_student_observation_dimension_and_no_leakage
  AssertionError: Observation dim mismatch: expected 198, got (189,)
  ```
- **日志**：`reports/V9-S3-C1-review/mutations/mut4_drop_token_dim_red.txt`

---

## 5. 测试套件质量审查

1. **写死的通过值**：未发现。覆盖测试、独立性测试与寻路测试均真实调用生成器或模拟器，门槛均引用 `spec.py` 中的冻结常数。
2. **恒真断言**：未发现诸如 `assert True` 或恒成立数学等式。
3. **缺数据默认通过**：未发现。各测试均有保底数量断言（如 `assert total_events_count > 0`、`assert len(seeds) == n_keys`）。
4. **测试盲区指正**：
   `test_s3_events_bruteforce.py` 缺乏对事件有效步索引范围的约束，即未断言：
   ```python
   assert all(0 <= ev["t"] < len(episode["steps"]) for ev in episode["events"])
   ```
   导致第 3 节发现的 `t = 360` 边界越界事件漏网。

---

## 6. 学生观察泄漏深度排查

对 `src/ainerzero/v9/experiments/s3/world.py:224-302` 的 `compute_student_obs` 进行信息流审计：
1. **绝对坐标泄漏检查**：
   - 观察向量仅由 3×3 局部自我中心视野（189 维）+ 朝向 one-hot（4 维）+ 上一动作 one-hot（4 维）+ 撞墙 bit（1 维）拼接而成。
   - 绝对坐标 $(x, y)$ 完全未参与特征拼接，未在全局步数据学生可见层泄漏。
2. **Token 是否已换（swapped）泄漏检查**：
   - 局部视野中的 token one-hot 仅显示当前该格子上的 token 类别编号。
   - 初始 token 与新 token 均均匀采样自同一个 8 类别族中（F1: 1–8，F2: 9–16），单从当前 token 编号上无法获得先验判断其是否发生过置换。
   - 步数据 `obs`、`action`、`est_pose` 中无任何置换标志位或置换倒计时。
- **排查结论：无坐标泄漏，无置换状态泄漏。**

---

## 7. DESIGN-r2 改动审查

1. **F1 / F2 不相交 Token 集（核心修复）**：
   - r1 中原设定 F1 与 F2 共享 token 1–8 但改变映射，这会导致神经网络在 F2 训练时强行重写分类头权重，形成无解的规则冲突（恒假）；
   - r2 改为 F1 用 1–8、F2 用 9–16，两族语义空间正交，既允许读出头在不冲突的前提下容纳 16 类，又真实测出了特征编码器与打分头在跨世界族微调时的表征漂移（Catastrophic Forgetting）。该改动逻辑极其严密自洽。
2. **观察维度 198 维核算**：
   - 视野 9 个格 × (4 地形 + 17 Token 类别) = $9 \times 21 = 189$ 维；
   - 朝向 4 + 上一动作 4 + 撞墙 1 = 9 维；
   - 总和 $189 + 9 = 198$ 维。算术完全正确。
3. **恒真 / 恒假排查**：
   - 不相交 token 使 H3 的检验聚焦于跨族持续微调下的权重漂移，既非恒真，亦非恒假。
   - 未发现新的漏洞或恒真恒假。

---

## 8. 必修项与建议项

### 8.1 必修项（打回必修，修复后方可验收并进入 C2）
1. **[必修 1 - 修复末端边界越界事件]**：
   - 在 `src/ainerzero/v9/experiments/s3/tour.py` 中，截断末端多余事件，确保返回事件的时间步 $t$ 严格满足 $t < t_{\text{max}}$（即 $t \in [1, 359]$），严禁产生 $t = 360$ 的无对应 step 观察事件。
   - 修改方法建议：在 `extract_readout_events` 传入轨迹时截断至有效步长度 `trajectory_positions[:t_max]`，或在事件记录处增加 `if t < t_max:` 过滤。
2. **[必修 2 - 补齐测试边界断言]**：
   - 在 `tests/v9/experiments/test_s3_events_bruteforce.py` 与 `test_s3_obs_spec.py` 中，显式增加断言：
     ```python
     assert all(0 <= ev["t"] < len(episode["steps"]) for ev in episode["events"])
     ```
     确保修复后该越界问题永久绝迹。

### 8.2 建议项
1. **[建议 1]**：在 `generate_episode` 返回的 `summary` 中，可显式加入 `valid_events_count` 与 `oob_events_count` 校验，增强数据产出的防御性审计。

---

## 9. 最终审查结论

**结论：`打回（REJECT）`**。
S3-C1 总体完成质量极高，但在数据与步引用的边界对齐上存在单点破绽（$t=360$ 越界导致 `IndexError`）。请作者按上述必修项 1 与 2 进行单点修复并重新提交复核。
