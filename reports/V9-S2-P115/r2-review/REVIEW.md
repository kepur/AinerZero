# 非作者复核报告：V9.P115 r2 S2 世界 GridLab-S2（打回修订验收）

自证：复核者为 `gemini-m7k4`，与被验任务 ainerzero.V9.P115 作者 `composer-a7k2`（r2）及 `gemini-b9x2`（r1）为不同会话的独立 Agent，未参与 P115 任何版本的编写与提交；本次复核为只读核对，未修改任何源码与测试。

---

## 一、文件范围与他人文件未改动核实

1. **工作树状态**：
   - `src/` 下除已交付文件外与 `HEAD` 逐字节一致。
   - P115 r2 交付的 5 个核心文件 SHA256 与作者报告 **100% 吻合**：
     - `src/ainerzero/v9/experiments/s2/world.py`: `dbd923017bf7d158dbba8604a6c32aa57c74782234f1b05571fd4eeb8a25f591`
     - `src/ainerzero/v9/experiments/s2/data.py`: `8fd195af598fcc618392bbc694e164dfa7e79a88c503f408824bb402081cf3e8`
     - `tests/v9/experiments/test_s2_world.py`: `599881c1df1ce4af08298b49f58338325b7edabb122276110e1fe05532221f11`
     - `tests/v9/experiments/test_s2_data.py`: `f2838ea2dc7fac6792ca596acb08911b5c4dd3647b8626525a499060daed9ec4`
     - `reports/V9-S2-P115/r2/run_mutations.py`: `14e6ececb8408a99cabf67f45bfdc9cf00339e0e561f63ad58ac2fb56b83d3ec`
2. **他人文件零篡改核实**：
   - P111 的核心文件：
     - `src/ainerzero/v9/experiments/s2/core_math.py`: `3d0311e7edbc7f421bea662ab30e023f25a8c6eac7aa0756bcf6cd7f1ed7f972`（完全一致）
     - `tests/v9/experiments/test_s2_core_math.py`: `45381c98dd9bdda40379611ee6529ed8d4373c081e6c4d160b06365b936f3efb`（完全一致）
     - `tests/v9/experiments/test_s2_package_pure_cpu.py`: `75bcdd36913e1db4b84206359f8b22f082d0185a0c769454e3ae29f6f0da8398`（完全一致）
   - P112 / P118 的核心文件：
     - `src/ainerzero/v9/experiments/s2/planner.py`: `e3c73a9aea9eb497001c3c5b87946dbb7bc2e019424379a6b54e21dbf85441ab`（与当前登记完全一致）
     - `src/ainerzero/v9/experiments/s2/fwd_counter.py`: `2dbe4002805ae4dafb3a965a30c8f9127d00af526909eefeb3ed929845b31e20`（完全一致）
     - `tests/v9/experiments/test_s2_planner.py`: `c7770b6ce9d8348b8bf31070878e45ee7cec083db168a101970dc7119db596a9`（完全一致）
   - `src/ainerzero/v9/experiments/s2/__init__.py`: `d083f457255e140af89dc81afe06bc16a3663955f64b8e830bcb750d019d105d`（归属 P111，未修改）

---

## 二、参数对照（DESIGN-r1/r2 §2 ↔ 代码实现）

| 设计项 | 设计规格要求 | 代码行号与实现 | 一致性 |
|---|---|---|---|
| **网格尺寸** | 25×25 离散格子 | `world.py:16` `SIZE = 25` | **一致** |
| **房间布局** | 3×3 共 9 个房间，内部约 7×7 | `world.py:119-129` `room_bounds_1d = [(1, 7), (9, 15), (17, 23)]`，9 间房内部全部 7×7 | **一致** |
| **门洞数量** | 相邻房间垂直/水平隔墙打通 1–2 个门洞 | `world.py:136, 146` `n_doors = rng.choice([1, 2])` | **一致** |
| **柱子障碍** | 每间房内部随机分布 0–3 个柱子 | `world.py:155` `n_pillars = rng.choice([0, 1, 2, 3])` | **一致** |
| **智能体视野** | 7×7 局部自我中心视野，视线光线投射遮挡 | `world.py:17` `VIEW_SIZE = 7`，`world.py:89-106` `line_of_sight` | **一致** |
| **动作空间** | 4 动作：FORWARD=0, TURN_LEFT=1, TURN_RIGHT=2, WAIT=3 | `world.py:41-46` `ACTIONS = (0, 1, 2, 3)` | **一致** |
| **k 分布** | 离散 $k \in \{1, 2, 3\}$，概率权重 $0.5 : 0.3 : 0.2$ | `data.py:38-39` `K_VALUES = (1, 2, 3)`, `K_WEIGHTS = (0.5, 0.3, 0.2)` | **一致** |
| **回合长度** | 单回合最大环境步长 240 步 | `data.py:44` `EPISODE_STEPS = 240`，`data.py:194` `max_steps = 240` | **一致** |
| **探索噪声** | 0.2 随机动作噪声注入 | `data.py:197` `exploration_noise = 0.2` | **一致** |
| **目标距离** | `long` 目标 $\ge 40$ 动作步，`short` 目标 $\le 10$ 动作步 | `world.py:50-51` `LONG_GOAL_MIN_DIST = 40`, `SHORT_GOAL_MAX_DIST = 10` | **一致** |
| **坐标隐私** | 学生端观察绝不提供绝对坐标 $(x, y)$ | `world.py:311-316` `student_obs` 仅含 view, heading, last_action, dt | **一致** |

---

## 三、坐标泄露、歧义与独立 BFS 复算

1. **同视野异坐标独立构造**：
   - 在真实生成的地图中枚举全部朝向视野，检索出 109 组在不同坐标但呈现完全相同局部视野的位姿。
   - 提取其中两个不同坐标位姿 $(9, 1, \text{heading}=0)$ 与 $(17, 1, \text{heading}=0)$，生成 `student_obs`。
   - 经 JSON 序列化逐字节比对，两者的观察数据 **完全一致（零坐标泄漏）**。
2. **独立位姿图动作 BFS 复算 20 个 long 目标**：
   - 独立编写位姿图 BFS（仅使用前进/左转/右转 3 个动作，转弯与前进各计 1 步）。
   - 对 20 对随机抽取的 long 目标进行复算：
     - 复算距离与作者 `stats["bfs_distance"]` **完全吻合**。
     - 距离统计：$\min=40, \max=45, \text{mean}=41.05$。
     - **全部严格 $\ge 40$ 动作步**，零回退，零违约。
3. **全图穷举验证目标唯一性**：
   - 遍历全图所有可通行格子与 4 个朝向（共 1400+ 个位姿），建立完整视野出现频率直方图。
   - 对所有被接受的 long/short 目标观察进行频数核对：**出现次数严格等于 1**，确认歧义拒绝逻辑在全局严格生效。

---

## 四、r2 打回专项深度复核

1. **彻底消除长目标距离回退**：
   - 源码核验：`world.py` 第 511–524 行，`_ALLOW_LONG_DISTANCE_FALLBACK = False`。当某起点无法找到 $\ge 40$ 动作步的目标时，直接抛出 `RuntimeError: No long-goal pose with pose-BFS >= 40 ... no fallback permitted`，绝不放宽距离。
   - 随机起点抽样：测试 35 个支持 long 目标的随机起点，抽样结果最小距离为 40，无任何回退；测试不支持 40 距离的极端起点，确认百分之百触发 `RuntimeError`，严格 fail-closed。
2. **成对抽取与世界重抽门**：
   - `sample_start_goal_pair` 采用起点与目标的联合随机抽样；
   - `prepare_world_with_long_pairs` 在无法凑齐 6 对目标或拒绝率 $>30\%$ 时，自动重新生成世界（上限 5 次）；
   - 复核者注入模拟失败用例，验证在 5 次重抽耗尽后准确抛出 RuntimeError 并在日志中记明原因。
3. **k 采样经验分布卡方检验**：
   - 复核者在 10,000 步的独立抽样中统计：$k=1$ 出现 4981 次（$49.81\%$），$k=2$ 出现 3038 次（$30.38\%$），$k=3$ 出现 1981 次（$19.81\%$）。
   - 计算 Pearson 卡方统计量 $\chi^2 = 0.7340$，远低于事先冻结的门限 $20.0$（$p \approx 0.69$）。
   - 变异检验：将 $k$ 强制固定为 3 时，$\chi^2 = 40000 \gg 20.0$，作者的测试 `test_k_distribution_chi_square` 立即变红拦截。
4. **r2 四项改动复核**：
   - **非 BFS 段占比**：单回合轨迹与数据集中实测非 BFS 步数占比为 $58.9\% \ge 50\%$。
   - **世界重抽**：拒绝率阈值 `WORLD_REJECTION_RATE_THRESHOLD = 0.30`，超过 0.30 强制重抽。
   - **扰动比例**：dev/final 数据集的 long 目标规格中，每 6 对恰有 2 对（占比 $1/3$）设置 `perturb = True`。
   - **成功判定手算**：
     - `is_success`：$(10, 10, 0)$ 到目标 $(10, 10, 2)$，耗时 110 步 $\le 3 \times 40$ 判定 `True`；耗时 121 步 $> 120$ 判定 `False`。
     - `is_success_strict`：朝向不同但到位判定 `False`；朝向一致且到位判定 `True`。手算与代码行为完全一致。

---

## 五、复核者独立变异实验（4 处作者表外变异）

在隔离副本中执行，所有变异前先通过基线，变异后验证转红，并在测试后按字节还原校验 SHA256。

| 变异编号 | 变异部位与内容 | 目标测试 | 变异后状态 | 拦截断言特征 | 还原 SHA 吻合 |
|---|---|---|---|---|---|
| **REV-P115-M1** | `is_success` 步数预算放宽至 $10\times$（允许 121 步判定成功） | `test_is_success_rules` | 变红 (exit 1) | `assert is_success(..., steps_used=31, bfs_dist=10) is False` | 是 |
| **REV-P115-M2** | `compute_ego_view` EAST 朝向颠倒 $du$ 与 $dv$ 偏移 | `test_line_of_sight_closed_form` | 变红 (exit 1) | `assert view_east[3][2] == PILLAR` | 是 |
| **REV-P115-M3** | `make_goal_episode_specs` 将 `PERTURB_LONG_FRACTION` 改为 0.0 | `test_generate_partition_isolation_and_disjointness` | 变红 (exit 1) | `assert sum(1 for s in specs if s["perturb"]) == 2` | 是 |
| **REV-P115-M4** | `assert_k_distribution` 判定条件反转为 `chi2 < threshold` | `test_k_distribution_chi_square` | 变红 (exit 1) | `chi2 = assert_k_distribution(...)` 抛出 AssertionError | 是 |

4 处复核者自做变异全部精准变红。

---

## 六、纯 CPU 与全量测试套件

- **纯 CPU 断言**：子进程隔离模式下导入 `world` 与 `data`，`mlx` 未载入 `sys.modules`。
- **单元测试**：`tests/v9/experiments/test_s2_world.py` 与 `test_s2_data.py` 共 16 项测试全部通过（耗时 5.14s）。

---

## 七、复核结论

**`RECOMMEND_ACCEPT`（推荐验收通过）**

- P115 r2 彻底消除了 r1 暴露的 long 目标静默回退缺陷，完整实现了基于位姿图动作 BFS 的最短路径计算；
- 成对抽取、世界重抽、非 BFS 探索混合、k 卡方门控、扰动规格与双重成功判定全部符合设计规范；
- 变异敏感度极高，代码纯净独立，他人文件零污染，准予通过验收。
