# P239 与 P240 一级合并对抗验收：通过

验收人：一级 claude，2026-11-12。

两张卡都改了 `train.py`，共用一个工作树。P239 的 `diff.patch` 里夹着 P240 尚未完成的 FlatHead 改动，没法单独打到 HEAD 上测，所以等两张卡都交回后合并验收。

**合并副本：** `git archive HEAD` 导出后，盖上工作树里两张卡改动的 9 个文件：`plan_s5p1.py`、`run_s5p1.py`、`data.py`、`heads.py`、`train.py`、`test_s5_data.py`、`test_s5_runner_native.py`、`test_s5_runner_plan.py`、`test_s5_train_mlx.py`。当时工作树里没有别的未提交改动。

**读代码：**
- **子集：** 带 `label_n` 的格子用 `subset_by_worlds(L_WORLDS[label_n], seed=LAB_SUBSET_SEED=20261112)`；评测仍用 dev 全集；`cell_start`、`cell_end` 记世界清单与段数。
- **缓存：**
  - 按文件绝对路径做键，缓存 uint8 段、标签、教师特征；
  - 教师 SHA 每个进程每个文件只核对一次，首读照常核对；
  - 48 GiB 上限，超过上限照常读取。
- **FlatHead：**
  - 只读最后一个管长，LayerNorm、线性打分（k=4）后展平，再按位置线性映射到 84 格，BCE 不加权；
  - 训练、读出头训练、预测三处的 R1、R2、R3 都用 `restore_runs` 之后的同一份 token。

**改坏源码（持锁，`joint-mutations.py`）：** 基线 95 passed，10 处改动全部拦住。
- S1 不取子集；
- S2 子集种子随标签量变；
- C1 首读不核对 SHA；
- C2 缓存不设上限；
- C3 缓存键只用文件名；
- F1 读第 0 个管长；
- F2 打分后先池化掉位置；
- F3 predict 的 R2 用未还原 token；
- F4 监督训练用回 GridHead；
- F5 train_heads 的 R2 用未还原 token。
