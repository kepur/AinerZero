# ainerzero.V9.P116 执行报告（非作者复核 P115）

自证：执行者 `composer-1998`；被验卡作者 `gemini-b9x2`；非同会话别名；只读核对，未改 `src/` / `tests/` 交付物（变异仅在 `/tmp/p116-s2-final-snap` 隔离副本）。

角色：executor；时间：2026-11-06
任务状态：reported；实验状态：未训练（纯 CPU 复核）
被验：`ainerzero.V9.P115` → `reports/V9-S2-P115/REPORT.md`
依据：`DESIGN-r1.md` §2；卡面文件范围；参数 v0

## 结论

**`RECOMMEND_REJECT`**

阻断项见文末。核心实现多数与 §2 一致且作者声称哈希可复现，但 **`sample_goal(..., kind="long")` 在无 ≥40 无歧义候选时回退到更短距离，实际可返回 BFS≪40**；作者小样已出现 min=36，本复核 20 次独立起点中 **18 次 <40（min=20）**。该缺陷直接违反 DESIGN-r1 / 卡面 long 定义，测试未覆盖回退路径。

## 摘要

- 曾在工作树存在时跑通 `test_s2_world`+`test_s2_data` **11/11**；`tests/v9/experiments/` 当时 **400 passed**。复核中途 `s2/` 被其他卡改写（出现 `core_math.py`、文件短暂消失），后以作者哈希一致的快照在 `/tmp/p116-s2-final-snap` 完成其余核验。
- 参数对照：网格/房间/门洞/柱/视野/动作/k/噪声/240 步与代码一致（附行号）。
- 坐标同视野异位：自构 (5,5)/(15,15) 学生观察逐字节相同。
- 歧义：全图穷举计数下，抽中的已接受目标观察均为 count==1。
- 自做变异 4 处：R1/R2/R4 变红；**R3（强制 k≡3）存活** → k 分布无测试。
- SIGReg：本交付无 SIGReg，**不适用**（卡面套话）。

## 1. 范围

卡面允许：`s2/world.py`、`s2/data.py`、`s2/__init__.py`、`test_s2_world.py`、`test_s2_data.py`、`reports/V9-S2-P115/`。

| 检查 | 结果 |
|---|---|
| 作者四文件 SHA 与报告一致 | **成立**（快照核验，见 metrics） |
| 仅卡面新文件 | **有问题**：同目录另有 `fwd_counter.py`、`planner.py`、`core_math.py`；另有 `test_s2_planner.py`、`test_s2_package_pure_cpu.py`（多卡并行污染工作树） |
| `src/` 其他已跟踪文件 vs HEAD | 工作树另有 `tests/conftest.py`、`test_s1_r7_*` 等 **M**，与 P115 卡面禁止改 conftest 冲突；**无法判断是否 P115 作者所改**（更像并行脏树） |

快照内混入 `core_math` 后全量 `tests/v9/experiments/` 为 **5 failed / 394 passed**（不能用来否定作者当时的 400；作者范围 11/11 在干净快照复现）。

## 2. 参数对照（DESIGN-r1 §2 ↔ 代码）

| §2 项 | 代码位置 | 一致？ |
|---|---|---|
| 25×25 | `world.py:16` `SIZE = 25` | 是 |
| 3×3 / 9 房间，约 7×7 | `world.py:104-110` bounds `(1,7)(9,15)(17,23)` → 每间 7×7；`len(rooms)==9` | 是 |
| 相邻门洞 1–2 | `world.py:121,131` `rng.choice([1,2])` | 是 |
| 每房柱 0–3 | `world.py:140` | 是 |
| 7×7 视野 | `world.py:17` `VIEW_SIZE = 7` | 是 |
| 4 动作 | `world.py:41-46` | 是 |
| k~{1:0.5,2:0.3,3:0.2} | `data.py:125` | 是 |
| 回合 240 | `data.py:86` 默认 `max_steps=240` | 是 |
| 探索噪声 0.2 | `data.py:88` | 是 |
| long≥40 / short≤10 | `world.py:400-425` **候选**写 ≥40 / ≤10，但 long **有回退**到 `max_d_u-4` 等，**可 <40** | **否（语义违约）** |
| 不给绝对坐标 | `student_obs` 仅 view/heading/last_action/dt；默认无 x/y | 是（见 §3） |
| 分区单入口 + 不重叠 | `generate_partition` / `assert_partitions_disjoint` | 是（测试调用真函数） |

## 3. 坐标泄露与歧义（独立）

1. **同视野异坐标**：合成地形在 (5,5) 与 (15,15) 放相同局部墙；`student_obs` JSON 逐字节相同（sha 前缀 `148bbae32d568c05`）。
2. **20 个 long 目标、自写 BFS**：与作者 `stats["bfs_distance"]` 全部一致；**`ge40` 仅 2/20**，min=20，max=40。
3. **全图穷举歧义**：对 layout seed 777 枚举全部 FREE×4 朝向视野；随后接受的 short/long 目标观察均为 `counts[v]==1`（抽 40 次无失败）。**歧义拒绝逻辑对「已接受目标」成立**；与 long 距离违约相互独立。

## 4. 测试真伪

- `test_s2_world.py` / `test_s2_data.py` **import 并调用** `make_layout` / `step` / `student_obs` / `sample_goal` / `generate_partition` / `run_episode`，不是常数对常数。
- 视线三例调用 `compute_ego_view`；连通性自写 BFS 对 `layout.terrain` 断言。
- **缺口**：`test_goal_sampling_and_ambiguity_rejection` 仅从 `(1,1)` 抽 long——该角点直径常 ≥40，**测不到回退分支**；故作者测试全绿与生产违约可并存。
- **SIGReg 阈值**：交付内无 SIGReg → 记 **不适用**。

## 5. 自做变异（作者表外；隔离副本；逐字节还原）

工作目录：`/tmp/p116-s2-final-snap/repo`；import 解析到该副本；每次还原后 SHA 与作者哈希一致。

| ID | 变异 | 结果 | 判断 |
|---|---|---|---|
| P116-R1 | long 候选阈值 40→20 | **变红** | 测试能抓住「抽到 <40」 |
| P116-R2 | `student_obs` 强制 `dt=0` | **变红** | 有覆盖 |
| P116-R3 | `run_episode` 强制 `k=3` | **存活（11 passed）** | **测试漏洞**：未断言 k 分布 / 经验频率 |
| P116-R4 | `VIEW_SIZE` 7→5 | **变红** | 有覆盖 |

## 6. 纯 CPU

- 快照上 `python3 -I` 导入 `world`+`data` 后 `mlx not in sys.modules` → OK。
- 作者范围 11/11：`11 passed in 1.85s`（快照）。
- 全量 `tests/v9/experiments/`：作者当时报告 400；本快照因并行 `core_math` 等变为 394 passed / 5 failed——**不归因于 P115 四文件本身**。

## 阻断项（REJECT）

1. **`sample_goal` long 必须硬失败或重布局，禁止返回 BFS<40**（删除 `world.py` 约 409–423 的放宽回退；或回退时 `raise`）。补测试：随机起点多次 + 故意构造「最大距离 <40」布局应报错而非静默缩短。
2. **补 k 分布测试**（回应 P116-R3 存活）；至少对 `run_episode` 大样本频率做松弛断言或固定 RNG 序列断言。
3. **交回前清理/隔离卡外文件**：`planner.py` / `fwd_counter.py` 等不得混进「P115 已交付」叙述；工作树与卡面范围对齐后再验收。

## 非阻断建议

- 生产 API 上的 `leak_coordinates` / `force_all_visible` / `enforce_connected` 钩子宜仅测试可见或移出默认路径。
- 作者小样 long min=36 已暴露问题却仍报完成——复核侧据此坚持 REJECT。

## 证据路径

- 隔离快照：`/tmp/p116-s2-final-snap/`（含 `p115/` 四文件与 `independent_mutations.json`）
- 本报告目录：`reports/V9-S2-P115/review/`

交回统筹：是否打回 P115 修 long 契约与 k 测试；并行卡对 `s2/` 的文件争用需一级协调。
