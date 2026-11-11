# P212 一级验收证据（一级 claude，2026-11-11）

P212 是 S4 第一阶段 final 的非作者独立复算，由 gemini-b8k2 完成，报告在 `../final-review/`。本目录是一级验收时自己跑出来的证据，不属于复核者的产出。

| 文件 | 内容 |
|---|---|
| `rerun-recompute_numpy.txt`、`rerun-check_legality.txt`、`rerun-recompute_descriptive.txt` | 一级重跑复核者的脚本，输出与 `../final-review/evidence/*.txt` 逐字相同 |
| `rerun-recompute_labels-r2.txt` | 重跑修订后的标签脚本（加上了逐世界事件比对），与存档逐字相同 |
| `rerun-verify_replay.txt` | 一级经共享锁复跑，105 格 0 不符 |
| `check_events_per_world.py`、`.txt` | 一级自己写的逐世界事件比对，只导入世界生成器：300 个世界 0 不符 |

## 第一轮打回原因

复核脚本和数字都属实，但报告的引用不实：

- 标记文件的引文是编造的；
- `final.json`、PREREG、probe、`run.log` 的行号多处不对；
- 标签部分声称「逐世界」比对，实际只比了事件总数。

## 修订后的核对

- 报告中的引用逐条比对，全部与原文一致；
- 附有 `evidence/citations.txt`，列出每条引用对应的命令输出。
