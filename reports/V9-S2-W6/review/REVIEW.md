# W6（P173）非作者复核：一级 claude（P174，2026-11-07）

- **作者：** gemini-b7x4
- **复核者：** 一级 claude（非作者；用户 11-07「一级二级全做、不要卡住」）
- **结论：RECOMMEND_ACCEPT（附带后续卡 W6b，冻结前必须完成）**

## 核对
- **测试：**
  - `test_s2_probe_eval.py`、`test_s2_planner.py`、`test_s2_learned_planning.py` 合计 63 条通过。
  - `--native-mlx`（W6 的 probe native 加 learned planning native）3 条通过；单决策墙钟 A 0.053 s、B 0.045 s、C 0.032 s。
- **非劣：** 先在 3 个种子之间取均值，再算 Δ = e_C − min(e_A, e_B)；次数取 `BOOTSTRAP_RESAMPLES`，阈值取 `DELTA_PRED`。
- **子目标注入：** `hierarchical_cem_plan(z2_subgoal_override=...)` 已实现，参考实现与批量实现两处都有。
- **全量**（跳过已打回的 W3 r1 端到端测试文件）：3701 passed，4 failed。4 条失败都在 `test_s2_eval_runner.py` 和 `test_s2_wiring.py`，属于 W3 r2（P168）正在改的范围；W6 没有改动这两个文件或 eval_runner、commands。
- **实盘：** artifacts 前后 lstat 比对（含 ctime）差异为 0。

## 后续 W6b 必改（不阻塞 W3 r2 和 W7 并行，但冻结前必须完成）
1. **`fit_probe` 的留出集：** 不传 `holdout_worlds`，而且目录里没有 `HOLDOUT_WORLDS.json` 时，现在会静默用上全部世界。应改为调用 `train_runner.get_holdout_world_indices`（带篡改检查），文件缺失即报错。
2. **回合文件：** 删除回退去读任意 `*.json` 的平铺分支，只认 `world_XXXX/episode_*.json`，其他情况一律报错。`probe_errors` 把平铺文件统一记为世界 0 的分支也一并删除，否则分簇会失效。
3. **判门步数：** `prediction_noninferiority` 的 k 改为取自 spec 常量（例如 `PROBE_GATE_STEP = 30`），不再在默认参数里写死 30。
