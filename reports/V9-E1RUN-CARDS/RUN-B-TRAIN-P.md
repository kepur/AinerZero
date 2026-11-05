**E1 运行卡 B：训练 P 族 9 格（臂 ② ③ ⑥ × 种子 42/43/44），串行，每格墙钟 ≤ 1200 s（含占空比 0.25）。**

先读同目录 `COMMON.md`。前置：数据卡 A 已经非作者复核并验收。

## 步骤
1. 跑 `e1-phase2 --mode verify`，贴出 JSON。
2. 按以下顺序逐格运行，每格一条 `relay exec`：
   - 命令：`relay exec <本卡> --agent <你> --wall-timeout 1500 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode train --arm <A> --family P --seed <S>`
   - 顺序：(2,42) (2,43) (2,44) (3,42) (3,43) (3,44) (6,42) (6,43) (6,44)。
   - 一格跑完、确认锁已释放后再跑下一格。
3. 每格记录：
   - stdout JSON 原文和退出码；
   - checkpoint 路径与 SHA；
   - best_step、早停是否触发；
   - 本格 active_seconds 与墙钟；
   - 账本行。
4. 任何一格被拒（例如 `phase_budget_exceeded` 或 `lock_busy`）或失败：**停下**，不重试，交回已完成的格。

## 交回
`reports/V9-E1RUN-B-P/<你的ID>/`：报告（9 格表）、`metrics.json`、命令原样输出。
