# ainerzero.V9.P51 报告：S1 r14 正式运行（部分完成）

- **执行**：一级 `claude`。驱动 `serial_run.py` 以 `caffeinate -i -s` 包裹，经 relay-runner 串行运行，幂等键前缀 `s1-r14-`。
- **依据**：RESEARCH_LOG `## R20261028-S1-phase1-r14-budget`；批准行在 stageA 节第 818 行（document `e28c49cd…`）。
- **需要非作者复核**：`ainerzero.V9.P52`（gemini）。
- **结论**：训练段 6 次中 5 次完成，1 次因主机睡眠环境失败；评测段只有 arm1 完成，另有 5 格因评测代码缺陷失败、4 格未启动。没有重跑任何一格。

## 训练（每次 3510 步，单次截止 1200 s）

| 格 | 作业 | run | 终态 | 起止 | params.npz SHA |
|---|---|---|---|---|---|
| arm2 s2（A2） | job-5fed34f5… | `33d09a1266bd4d9eabc2e59050048658` | completed | 13:00:19–13:11:48 | `f7f9a661…cf01`，**与 r13 逐位相同，A2 复现成立** |
| arm3 s1 | job-5455ba0b… | `6d606a3e949f40e0a8077d70e7c02f77` | completed | 13:11:59–13:21:10 | `d4036d8b…fe1b` |
| arm3 s2 | job-1a3e11a5… | `3cd7524870174be898382ce15edbaaec` | completed | 13:21:17–13:30:24 | `3681887a…2b97` |
| arm4 s0 | job-96e8175c… | `1c051659ff504acdb76e77f830a279a9` | **failed**（环境失败） | 13:30:31–13:51:14 | —（`BudgetExceeded: wall_time_budget`，3006/3510 步） |
| arm4 s1 | job-afc407d4… | `bc0264a2f90d4a688bb0abe571fa90c7` | completed | 14:22:41–14:35:10 | `dae8d526…17d2` |
| arm4 s2 | job-92364f4c… | `a5c631f535354e628d8f38d25361bef3` | completed | 14:35:18–14:48:55 | `3b1d9e03…c604` |

**arm4 s0 失败原因**：13:41 前后电源被拔、随后合盖，`pmset -g log` 记录「13:41:41 Entering Sleep state due to 'Clamshell Sleep' … Using Batt」。睡眠期间墙钟照常推进，13:51:11 维护性唤醒时，该 run 的单次墙钟已经耗尽；进程组确认已空。

**驱动停止与续跑**：
- 13:51 驱动在启动 arm4 s1 之前检测到 `not on AC power`，随即停止。
- 14:22:35 一级检测到交流电恢复后续跑，此时盖子已打开（`AppleClamshellState = No`）。
- 14:18 系统还合盖睡过一次，当时驱动已停，没有作业在跑。

## 评测

| 格 | 终态 | 说明 |
|---|---|---|
| arm1 D | completed（11 s） | |
| arm2 s0 / s1 / s2，arm3 s0 / s1 | **failed**，各约 6 s | `ValueError: matmul … (size 192 is different from 32)`（arm2 对应的尺寸不同）。arm3 s1 是 `job-87ce8bbf…`：一级停驱动时它已跑完并失败，驱动账本里没有这一项，以本表为准 |
| arm3 s2，arm4 s0 / s1 / s2 | 未启动 | 一级 14:50 停驱动；arm4 s0 本来就没有可评测的完成训练 |

- **继承绑定正常**：生产 stdout 显示 arm2 s0 绑定到 r13 `19f2d1eb…`，arm3 s0 绑定到 `403ae816…`，`run_binding.inherited` 记录完整。
- **根因**（一级在隔离副本上复现，证据在 `eval-defect/`）：
  - `evaluation.few_shot_report` 用完整编码 `h` 去匹配位置图节点，而节点写入时只存了 `h` 的一个切片：arm3 是 `h[:32]`，arm4 是 `h[channels:channels+place_dim]`，arm2 是 `h[:memory_channels]`。
  - 只把查询改成同一切片后，三个臂的评测在副本上全部跑通。
  - 训练不走这段代码，所以训练结果不受影响。
- **处理**：r14 的这 5 格评测已记为尝试过，不能在 r14 下再评。用户已批准 r15：修复后继承 8 个已完成训练、补训 arm4 s0、重跑全部评测（见 RESEARCH_LOG `## R20261028-S1-phase1-r15-budget`）。

## 墙钟与台账

- 首次启动 13:00:14；最后一个作业在 14:50 结束，约 6600 s，没有超过 9000 s 的上限。
- 生产台账：开跑时 `fe31fee6…`（`production-ledger-at-launch.txt`），停止后见 `production-ledger-at-stop.txt`。台账由本轮正式运行写入，一级的诊断只在副本上做。
