# P236 第 3 轮：一级修测试路径、补两条守卫测试后验收

执行：一级 claude，2026-11-12。第 2 轮打回后，卡的能力要求升到 deep，二级领不了，由一级接手。gemini-k7x2 写的运行器源码（`run_s5p1.py`、`plan_s5p1.py`、`evaluate.py`）一行未改。

## 改动（只改测试）
- **三个测试文件的仓库路径：** `test_s5_runner_native.py`、`test_s5_runner_plan.py`、`test_s5_evaluate.py` 把 `LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero")` 改为 `Path(__file__).resolve().parents[3]`，让副本测试自己的代码。另设 `REAL_REPO` 常量，所有「这是一次性目录」的断言都同时排除 `LIVE` 与 `REAL_REPO`。
- **新增 `test_final_partition_cell_is_refused_before_any_cell`：**
  - 在一次性副本里，把 probe 蒸馏格的分区注入成 `s5p1-final` 并提交，跑 probe；
  - 断言：阶段失败，一个 `cell_start` 都没有，错误信息含「final partition」，副本里没有任何名字带 `s5p1-final` 的文件或目录。
- **新增 `test_cell_output_sha_mismatch_fails_the_cell`：**
  - 在一次性副本里，把父进程收到的格子结果 SHA 全部改成 0，跑 smoke；
  - 断言：退出码为 2，第一个格子 `cell_fail` 的错误信息含「SHA mismatch」，没有 `cell_end`，`n_completed` 为 0。

## 复验
新隔离副本，持锁，`mutations.py`。副本里的测试不再需要手改路径。
- 基线：17 passed。
- 8 处改动全部拦住，原始输出在 `mutations-r3-output.txt`：
  - R1 强制 CPU；
  - R2 不终止子进程；
  - R3 不扣阶段剩余时间；
  - R4 smoke 扣 dev 使用次数；
  - R5 跳过 tune 文件的 SHA；
  - R6 平局顺序反了；
  - R7 不拒绝 final；
  - R8 不核对输出 SHA。

## 待办
一级补的测试还要非作者复核，与一级在 P229、P230、P235 补的测试一并放下一张复核卡。
