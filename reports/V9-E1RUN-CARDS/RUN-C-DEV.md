**E1 运行卡 C：dev 评测 26 格（可训练臂 ②③⑥ × P/S × 种子 42/43/44 共 18 格；非训练臂 ①④⑤⑦ × P/S 共 8 格），合计墙钟 ≤ 30 min。**

先读同目录 `COMMON.md`。前置：训练卡 B-P、B-S 都已交回。**只做 dev，绝不 final-eval。**

## 步骤
1. 跑 `e1-phase2 --mode verify`，贴出 JSON。
2. 逐格运行，每格一条命令：`relay exec <本卡> --agent <你> --wall-timeout 400 -- .venv/bin/python -m ainerzero.cli e1-phase2 --mode eval --arm <A> --family <F> [--seed <S>]`。
   - 可训练臂必须带 seed，非训练臂不带。
   - 顺序：先非训练臂 ①④⑤⑦（P 族再 S 族），再可训练臂 ②③⑥（每个臂内部按 P 族再 S 族、种子 42→44）。
3. 每格记录 stdout JSON 原文、退出码、e_1/e_5/e_10/e_30 及每个 k 的可用 episode 数、碰撞与弹道段指标（按 CLI 实际输出原样摘录）、active_seconds、账本行。
4. 汇总表：按臂 × 族给出三个种子的宏平均（只做算术汇总，不下判定结论）。
5. 任何一格被拒或失败：停下，不重试。

## 交回
`reports/V9-E1RUN-C/<你的ID>/`：报告（26 格表加汇总表）、`metrics.json`、命令原样输出。报告里不得写「H-E1 成立 / 不成立」之类的判定（判定在 final，dev 只做设定参考）。
