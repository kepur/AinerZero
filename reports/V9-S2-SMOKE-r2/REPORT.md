# P186：r2 smoke 启动即被账本拒绝（未执行任何步骤）

- **启动与退出：** 11:58:48 UTC 启动，0.26 s 后退出，退出码 1。
- **输出：** `{"status":"failed","mode":"smoke","stage":"execution","message":"run budget exceeds experiment run limits"}`
- **原因：** 沿用的 r1 账本中，实验清单的运行级上限是 10 h（36,000 s）；r2 按 15 h 申请 54,000 s，被账本拒绝。
- **处理：** r1 账本已归档到 `artifacts/v9/s2/phase1/r1-smoke/`，r2 改用新账本，由新的运行卡 P187 运行，命令相同。详见 RESEARCH_LOG `R20261108-S2-smoke-r2-refused`。
