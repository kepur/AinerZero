**E1 运行卡 A：正式数据生成（P/S 两族 × train 1000 / dev 200 / final 200，共 2800 段；墙钟 ≤ 1 h）。**

先读同目录 `COMMON.md`，那里的规则全部适用。

## 步骤
1. 跑 `e1-phase2 --mode verify`，贴出完整 JSON。
2. `relay exec <本卡> --agent <你> --wall-timeout 3900 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode generate-data`。CLI 内部的预算上限是 3600 s，wall-timeout 只是外层兜底。
3. 产出核对，只读：
   - `datasets/` 下各族、各分区的序列数（应为每族 train 1000、dev 200、final 200）；
   - 学生视图与评测视图分离；
   - `sealed_final/` 下只有封存数据，**没有任何 read_once 标记**（列目录、算 SHA 即可，不打开文件内容）；
   - 抽 5 个序列核对 `velocity_injection = kinematic_preroll_2f_v1` 标记；
   - 给 datasets 生成 `SHA256SUMS.txt`。
4. 账本：本次运行行的状态、active_seconds、退出码。

## 交回
`reports/V9-E1RUN-A/<你的ID>/`：报告、`metrics.json`（含序列计数、用时、账本行、SHA 清单路径）、命令原样输出。
