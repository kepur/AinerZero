# ainerzero.V9.P118 执行报告：S2 规划器 r2 补充：本回合目标编码缓存只计 1 次

- **角色与状态**：二级执行 `gemini-f8a2`；任务 `ainerzero.V9.P118`；状态 `completed`（纯 CPU，无训练）。
- **任务依据**：`reports/V9-S2-DESIGN/DESIGN-r2.md` §4；参数 v0；遵守工作树隔离与共享锁约定。
- **核心实现**：
  1. `ForwardCounter`:
     - 增加 `begin_episode()`：清空回合级目标缓存与 SHA；
     - 增加 `goal_embedding(goal_obs, encode)`：首调计 1，后续命中计 0；
     - 缓存键采用 `hashlib.sha256(canonical_bytes(goal_obs))`；
     - 同一回合换目标观察抛出 `ValueError`，禁止静默复用旧编码；
     - `reset()` 保持只清决策级计数与明细，跨决策保留回合目标缓存；
  2. `planner.py`:
     - `flat_cem_plan` 与 `hierarchical_cem_plan` 统一改用 `counter.goal_embedding(goal_obs, encode)`；
  3. **当前潜状态缓存**：如实写**未实现**（留待后续阶段评估）。
- **测试结果（10/10 passed in 2.97s）**：
  - 保留并通过全部原 8 项测试；
  - 新增 `test_goal_embedding_cached_across_decisions_in_episode`（同回合首决策计 2，后续决策计 1；换回合再计 2）；
  - 新增 `test_goal_embedding_changed_goal_in_same_episode_raises`（同回合换目标抛 ValueError）；
  - 隔离副本全量回归：3477 项，3319 passed（较基线准确 +2），91 failed（既有基线），56 skipped，5 errors。
- **坏对照对抗变异（隔离副本内执行，3/3 全变红，SHA 原样还原）**：
  - P118-M1 (begin_episode 不清缓存) -> RED (`AssertionError`, 换回合用例被捕获)；
  - P118-M2 (缓存命中仍计数) -> RED (`AssertionError`, 首调计 1 命中计 0 用例被捕获)；
  - P118-M3 (同回合换目标静默复用) -> RED (`Failed: DID NOT RAISE ValueError`, 换目标用例被捕获)。
- **实盘零修改**：
  - 对实盘 `artifacts/` 80851 项 stat 前后全量比对：0 差异，0 -shm/-wal 变动，未碰实盘，未用 utime。
- **交付清单**：
  - `REPORT.md` / `报告.md`、`metrics.json` / `指标.json`、`sha256.json`、`git_diff.patch`；
  - `run_mutations.py`、`mutation_log.txt`、`mutation_summary.json`；
  - `run_full_replica.py`、`pytest_full.log`、`nodes_after.txt`、`stat_comparison.json`。
