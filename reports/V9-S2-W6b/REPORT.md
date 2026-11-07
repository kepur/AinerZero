# W6b（P177）：清除 probe_eval 的三处回退（一级 claude 实现，2026-11-07）

- **作者：** 一级 claude
- **复核：** P178，须由 gemini 承担，排除 claude
- **改动范围：** `probe_eval.py`、spec 末尾追加的 `PROBE_GATE_STEP = 30`、`test_s2_probe_eval.py`

## 改动
1. **留出集：** `fit_probe` 改为调用 `train_runner.get_holdout_world_indices`（文件必须存在，带篡改检查）；传入的 `holdout_worlds` 与文件不一致时报错（`_world_index` 做严格解析）。
2. **目录结构：** 新增 `_episode_files_by_world`，只认 `world_NNNN/episode_*.json`。没有世界目录、世界目录名无法解析、某个世界下没有回合文件，一律报错。`fit_probe` 与 `probe_errors` 共用这个函数，原来平铺目录记为世界 0 的分支已删除。
3. **判门步数：** `prediction_noninferiority` 的 k 默认值改为 `spec.PROBE_GATE_STEP`。

## 测试
- 夹具改为按登记规则写 `HOLDOUT_WORLDS.json`；被投毒的世界改为按规则选出的那个留出世界。
- 新增用例：
  - 传入的留出集与文件不一致时报错；
  - 留出文件缺失时报错；
  - 平铺目录被拒绝；
  - k 的默认值等于登记值。
- `test_s2_probe_eval.py`：10 条通过。
- 坏对照 3/3 变红（`w6bmut.py` + `w6bmuts.py`）：留出集变为可选、恢复平铺回退、k 写死为 1。
- 全量（跳过 W3 r1 的端到端测试文件）：3705 passed，3 failed。3 条失败都在 `test_s2_eval_runner.py` 和 `test_s2_wiring.py`，属于 W3 r2（P168）正在改的范围。实盘零写入。
