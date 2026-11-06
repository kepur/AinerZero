# S2 小修合卡验收报告（ainerzero.V9.P120）

- **执行代理**：`gemini-m7k4`（二级执行 Agent）
- **任务目标**：修复 `world.py` 出处 docstring 解决 `test_gridlab_s06/s07` 2 条守卫失败；补齐 `s2` 模块零导入 GridLab 断言；补齐分层规划器目标编码跨决策缓存测试；保持纯 CPU 与全套件零失败。

---

## 一、改动范围与 diff 证明

1. **`src/ainerzero/v9/experiments/s2/world.py`**：
   - **严格只修改第 90 行 docstring 一处**，全文不再出现任何小写 `gridlab`。
   - `world.py` 相对改动前仅相差 1 行，统一补丁见 `reports/V9-S2-P120/world.patch`：
     ```diff
     --- src/ainerzero/v9/experiments/s2/world.py (before P120)
     +++ src/ainerzero/v9/experiments/s2/world.py (after P120)
     @@ -87,7 +87,7 @@
      
      
      def line_of_sight(terrain: list[list[int]], ax: int, ay: int, bx: int, by: int) -> bool:
     -    """Ray casting line of sight check, derived from gridlab_v1.py line_of_sight."""
     +    """算法参照 GridLab-v1 的 line_of_sight（ainerzero.environments 中的 GridLab-v1 模块）。"""
          if ax == bx and ay == by:
              return True
          n = max(abs(bx - ax), abs(by - ay))
     ```
   - 未修改 `tests/test_gridlab_s06.py` 或 `tests/test_gridlab_s07.py`。
   - 修复后，`test_gridlab_s06.py::test_not_wired_into_training` 与 `test_gridlab_s07.py::test_not_wired_into_training` **全部绿灯通过**。

2. **`tests/v9/experiments/test_s2_world.py`**：
   - 新增 `test_no_gridlab_module_imported()`：使用 `.venv/bin/python -I` 隔离子进程导入 `ainerzero.v9.experiments.s2.world` 与 `data`，严密断言 `sys.modules` 中不存在任何含 `gridlab` 的模块。

3. **`tests/v9/experiments/test_s2_planner.py`**：
   - 新增 `test_hierarchical_goal_embedding_cached_across_decisions_in_episode()`：
     测试同一回合内 3 次 `hierarchical_cem_plan` 决策中，目标编码 `encode(goal_obs)` 合计只计 1 次，其余决策直接命中缓存（`encode` 计数为 1）；在 `counter.begin_episode()` 开启新回合后重新计 1 次。

---

## 二、坏对照实验（3 处隔离变异，全部变红，按字节还原）

在临时隔离副本（`/var/folders/.../p120_mutation_sandbox_*`）中执行：

| 变异编号 | 变异部位与内容 | 目标测试 | 变异前 | 变异后退出码 | 失败特征 | 还原 SHA 吻合 |
|---|---|---|---|---|---|---|
| **P120-M1** | 分层规划器第 317 行绕过缓存：`z1_goal = encode(goal_obs)` | `test_s2_planner.py::test_hierarchical_goal_embedding_cached_across_decisions_in_episode` | PASS | 1 (变红) | `assert snap2["by_name"]["encode"] == 1`（实测为 2） | 是 |
| **P120-M2** | `world.py` 首部注入 `import ainerzero.environments.gridlab_v1` | `test_s2_world.py::test_no_gridlab_module_imported` | PASS | 1 (变红) | `AssertionError: GridLab modules imported: [...]` | 是 |
| **P120-M3** | `world.py` 第 90 行改回小写 `gridlab` | `test_gridlab_s06.py::test_not_wired_into_training` | PASS | 1 (变红) | `assert users == []`（捕捉到 `world.py`） | 是 |

---

## 三、全量测试套件与实盘 artifacts 零改动审计

1. **默认全量回归运行**：
   - 信号模式：前台子进程设置 `SIG_DFL` 信号还原。
   - 运行结果：**3478 passed, 0 failed, 6 deselected**（耗时 250.35s）。
2. **实盘 artifacts/ stat 审计**：
   - 测试前快照条目数：80,851。
   - 测试后快照条目数：80,851。
   - 前后 mtime_ns / size / inode 差异数：**0 差异（0 新增、0 修改、0 删除）**。

---

## 四、交付产物 SHA256

- `src/ainerzero/v9/experiments/s2/world.py`: `f4d4ff246a5f078ec1500fe11c8a06ffe1221d47fb4d78d103eaba645b7abbdd`
- `tests/v9/experiments/test_s2_world.py`: `ac121337898ae107f95c35e66e88dd544453a1a67225a03a0c6942b81b62bb5d`
- `tests/v9/experiments/test_s2_planner.py`: `899d47c69c42aea91dd3a84854e1ea3b0613f10685c62602fa59d1f37ed790d1`
- `reports/V9-S2-P120/world.patch`: `e5bfa780d32bb4c4c2357a829dd8ce1eb71109a9c2401f80ec9a47385a86a605`
