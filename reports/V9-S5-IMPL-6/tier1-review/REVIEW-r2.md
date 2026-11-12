# P236 一级对抗验收（第 2 轮）：打回，补测试并修正测试的仓库路径

验收人：一级 claude，2026-11-12。

## 第 1 轮的三处修改：都改对了
- 训练与评测不再强制 CPU，用默认设备。
- 每个格子在 spawn 子进程里跑。时限取 `min(45 min, 阶段剩余)`，到点先 terminate，再 kill，记 `cell_fail`；父进程核对输出文件的 SHA；读出头格从权重文件载入学生。
- `S5_FAKE_CELL` 环境钩子已删，改由仅供测试的 `cells_override`、`cell_runner` 参数注入；`stage.json` 记录执行函数名。

## 新问题：测试写死了实盘仓库路径
`test_s5_runner_native.py`、`test_s5_runner_plan.py`、`test_s5_evaluate.py` 都写着 `LIVE = Path("/Users/mac/AinerWorkFlow/AinerZero")`，每次都从实盘复制运行器和源码来测。后果有两个：
- 在隔离副本里改坏源码，测试测的仍是实盘代码，坏对照全部失效；
- 在别处检出的副本里跑这些测试，也是在测实盘。

**改成：** `LIVE = Path(__file__).resolve().parents[3]`，即从测试文件位置推出仓库根。各处「不是实盘」的断言保留，改为与真实实盘路径常量比较。

## 改坏源码（一级在隔离副本里先把上面三处路径改成副本自身，再持锁跑 `mutations.py`；原始输出在 `mutations-r2-output.txt`）
基线 15 项全过。8 处改动拦住 6 处：R1 重新强制 CPU、R2 不终止子进程、R3 不扣阶段剩余、R4 smoke 扣 dev 使用、R5 跳过 tune SHA、R6 平局顺序反了。

| 改动 | 结果 |
|---|---|
| R7 `_refuse_final` 不再拒绝（`if False:`） | **漏网** |
| R8 不核对格子输出文件的 SHA | **漏网** |

## 必须补的测试（都调用生产代码）
1. **拒绝 final：**
   - 直接测 `_refuse_final("s5p1-final")` 和 `_refuse_final("s5p1-final-shift")` 都抛 `GuardError`；
   - 再测运行器整体：用 `cells_override` 注入一个 `partition` 为 `s5p1-final` 的格子（副本里），阶段在执行任何格子之前失败，`events.jsonl` 里没有 `cell_start`，也没有生成任何 final 数据。
2. **输出 SHA：**
   - 用 `cell_runner` 注入一个格子执行函数：写一个文件，但在结果里报一个错误的 SHA；
   - 断言阶段失败，`cell_fail` 的错误信息含 SHA mismatch，该格不计入 completed。
3. 路径改好后，用 `mutations.py` 在隔离副本里复验 8 处全部拦住。复验时副本里的测试不需要再手改路径。原始输出放进报告。
