# P188：train 数据生成失败（冻结的重抽上限 5 次不可行）

- **运行：** 12:05:45–12:05:53 UTC，退出码 1；train 分区在第 11 个世界失败，dev 未启动。
- **报错：** `prepare_world_with_long_pairs failed after 5 redraws (seed=1707039238): rejection_rate 0.667 > 0.3`
- **全量模拟：** 上限 5 次时，train 有 113/1000 个世界失败，dev 10/50，final 10/50；上限 20 次时全部通过（`worldscan/`）。
- **结论：** 需要用户批准修改冻结参数 `max_redraw_retries`，详见 RESEARCH_LOG `R20261108-S2-data-r2-failed`。
