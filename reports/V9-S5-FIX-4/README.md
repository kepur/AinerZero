# 一级修正（2026-11-12）：读出头训练一次组装标签；运行器逐格核对冻结清单

**1. `train.train_heads` 一次组装标签。**
- probe-20261112c 里，读出头训练的读数据占比约 0.79：每步对每段调用 `load_item`，只为取标签，却要现算一遍 tubelet。
- 现在每次调用开头把全部段的 r1_logd、r1_sky、r2、r3 叠成数组，每步按下标取。
- 训练数学不变。学生 token 缓存照旧，仍由 `stop_gradient` 冻结。
- 新测试 `test_train_heads_assembles_labels_once_per_call`：一次调用里 `load_item` 至多调用 2N 次（N 为段数），不随步数增长。

**2. `run_s5p1.py` 每格启动前核对冻结清单。**
- 每个格子是新起的子进程，从工作树导入代码。阶段开始时核对过一次清单，但如果阶段跑到一半有人改了冻结文件，后面的格子会悄悄用上改过的代码。
- 现在每格启动前调用 `GD.check_manifest`，不一致就记 `cell_fail`（code changed during stage），阶段失败。
- 新测试 `test_code_change_during_a_stage_stops_the_next_cell`：一次性副本里，第一个格子运行时改动 `train.py`，第二个格子必须以 code changed 失败，完成数为 1。

**复验**（`git archive HEAD` 导出，再盖上本次 4 个文件；持锁；`mutations.py`）：
- 全部 S5 相关测试基线 114 passed。
- 两处源码坏对照都拦住：
  - Q1 去掉逐格核对；
  - Q2 读出头训练改回每步重读。

**复核：** 放非作者复核卡。
