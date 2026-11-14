# P251 一级验收证据（一级 claude，2026-11-14）

- `p251-summary.txt`：复跑 P251 的 `summarize.py`，与其 `summary_output.txt` 逐字相同。
- `p251-spot.log`、`p251-spot.json`：经锁复跑 `explore_s6c.py 3000 1 2500 … s6x-cand3 s6x-test3 random`。第 0 轮的全部字段与 `results-s6r3.json` 的随机臂第 0 轮逐位相同（D 0.4859、碰撞 0.6428、墙柱 0.9415、自由 0.0231、总 0.0523），可见 P251 的数据来自真实运行。
- 报告 `../replication/REPORT.md` 的读法有两处说过头，不影响数据：
  - 把 D 称为「综合能力分」，其实它只衡量碰撞；
  - 说按分歧挑在 D 上「稳定胜出」手工课程，实际是四次里三次为正（−0.006、+0.017、+0.047、+0.014）。
