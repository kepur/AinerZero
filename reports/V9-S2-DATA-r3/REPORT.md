# P191：r3 数据生成被合盖休眠打断

- **经过：** 11-08 13:06 UTC 启动；13:14 合盖休眠（用电池）；11-09 06:41 开盖后才跑完 train 分区。
- **结果：** 账本按墙钟（约 17.6 h）判为超出单格 3600 s，记为 failed；dev 分区未启动。
- **影响：** active_seconds 记为 0，15 h 额度没有被扣。
- **处理：** 产物移到 `artifacts/v9/s2/phase1/r3-data-interrupted/train_P191/`，由新卡重跑。详见 RESEARCH_LOG `R20261109-S2-data-r3-interrupted`。
