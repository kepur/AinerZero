# P193：训练在第 2 格被账本拒绝

- **臂 A 种子 42：** 完成，2757 步，390 s，最佳 rollout_error 为 2.177。
- **臂 B 种子 42：** 训练了 677 s 后，以 `Budget exhausted: wall_time_budget` 被拒，账本记为 failed，驱动脚本随即停止。
- **原因：** S2 worker 在完成时一次性扣减用时，同一段时间被算两次（代码缺陷），修复见 W12。
- 详见 RESEARCH_LOG `R20261109-S2-train-r3-refused`。
