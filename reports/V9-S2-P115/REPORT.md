# ainerzero.V9.P115 执行报告：GridLab-S2 多房间世界与分区数据入口

- **角色与状态**：二级执行 `gemini-b9x2`；状态 `completed`；依据 `reports/V9-S2-DESIGN/DESIGN-r1.md` §2。
- **纯 CPU 与零违规**：纯 NumPy/标准库，未导入 MLX，未写 `artifacts/`，未改动 `gridlab_v1`。
- **核心实现**：
  1. 布局：25×25 3×3 9 房间，相邻门洞 1–2 个，房间内 0–3 柱子，BFS 连通校验 + 规范 SHA256；
  2. 步进：前进/左转/右转/等待 4 动作，k 重复与撞墙计数纯函数；
  3. 观察：7×7 自我中心旋转视野（UNSEEN 遮挡），朝向 one-hot、动作与 dt，**零坐标泄露**；
  4. 目标：long（BFS ≥ 40）与 short（≤ 10），全图对称歧义检测与拒绝统计；
  5. 分区：单分区生成（含 dev/final k≡1 规则集），`assert_partitions_disjoint` 校验无重叠。
- **测试结果（11/11 全过）**：
  - `test_s2_world.py` (7/7)：确定性、连通门洞、3 视线闭式用例、零坐标泄露、k 步等价、目标歧义、纯 CPU `-I`；
  - `test_s2_data.py` (4/4)：轨迹确定性、k1 规则 dt、分区隔离与互斥断言、纯 CPU `-I`；
  - `tests/v9/experiments/` 全量计数：389 项 -> 400 项（+11 passed，0 failed）。
- **坏对照对抗变异（5/5 全部变红）**：
  - P115-M1 (泄露坐标) -> RED (`AssertionError: Forbidden coordinate term found in key: 'x'`)；
  - P115-M2 (去连通校验) -> RED (`AssertionError: All floor cells must be mutually connected`)；
  - P115-M3 (视线恒可见) -> RED (`assert 1 == -1` 闭式未过)；
  - P115-M4 (去歧义拒绝) -> RED (`Failed: DID NOT RAISE RuntimeError`)；
  - P115-M5 (共享命名空间) -> RED (`ValueError: Shared seed namespace detected`)。
- **dev 小样统计 (2 世界 × 2 回合，耗时 0.61 s，0.31 s/世界)**：
  - 每回合步数：[240, 240, 240, 240]；
  - long 目标 BFS 距离：min 36, median 40, max 43, mean 39.32；
  - 歧义拒绝率：0.00；视野 UNSEEN 占比：24.03%。
- **产物哈希**：
  - `world.py`: `c5f76cb11dd995ef55ba4118f0dc8a42544f0c26f69a26e8742c1a814433725f`
  - `data.py`: `c011f189e722473d9592ecf9084b6de6057dfe7d357651583652ed361cd6475c`
  - `run_mutations.py`: `e604420fd5f8de68fba7a97ccc54b6109f164977a42d99198217d01eaefa49bb`
