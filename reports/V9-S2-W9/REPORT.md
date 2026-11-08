# W9（P182）：臂 A 训练批量化、整数动作、latents 口径与预算推算（一级 claude 实现，2026-11-08）

- **作者：** 一级 claude（卡放出 25 分钟无人领取，按用户「不要卡住」的授权由一级直接做）
- **复核：** P183，须由 gemini 承担，排除 claude

## 改动
1. **`arms_mlx.arm_a_loss_mlx_batched`：批次维度并行**
   - B 条序列同时推进 GRU、先验、后验，时间维仍逐步循环；
   - 每条序列先在时间上取均值，再各自施加 free bits，最后取批次均值，与「逐条序列调用 `arm_a_loss_mlx` 再平均」在语义上等价；
   - 原逐条函数保留，作为参考实现和单序列入口。
2. **适配器：** `MLXArmAAdapter.train_step` 与 `rollout_error` 改用批量版。
3. **`_as_action`：** 三个臂 `predict_l1` 的单样本路径把 Python int 或 numpy 标量转成 (1,) 数组；one-hot 和索引数组保持原样。
4. **`MLXArmAAdapter.latents`：** 改为在零 GRU 状态下取后验均值，与 `encode` 处于同一规划潜空间，支持批量；原先返回 128 维的 E1 特征，导致 smoke 动作敏感性检查维度报错。
5. **`smoke.check_smoke_budget`：dev 与 final 推算改读 spec**
   - 曲线倍数原本写死为「1 + 2.5」，现按 `N_FWD_DEV_LEVELS` 相对主档 `N_FWD` 计算，主档只计一次；
   - 回合数取 `DEV_LONG_GOAL_EPISODES` 与 `FINAL_LONG_GOAL_EPISODES`，种子数取 `TRAINING_SEEDS`；
   - 短目标回合数 100 在 spec 中没有登记常量，暂时保留并在代码中注明。
6. **测试：**
   - 新增 `test_s2_arm_a_batched_native.py`，共 6 条：批量版与参考实现的损失差 ≤ 1e-4、梯度范数一致（两边的随机采样都固定为零）；单步耗时；三个臂接受整数动作；A 的 latents 与 encode 一致。
   - W8 那条 3 维 dts 坏对照的报错匹配改为同时接受两种报错文字。

## 实测（--native-mlx）
- **单步训练：** A 0.146–0.149 s（原 5.76 s，约快 39 倍），B 0.24–0.25 s，C 0.31–0.32 s。
- **native 用例：** `test_s2_arm_a_batched_native`、`test_s2_train_native`、`test_s2_learned_planning_native` 共 10 条通过，加上 W9 新增的 latents 用例，`test_s2_arm_a_batched_native` 为 6 条。
- **临时目录 smoke 预演（第 3 次）：** 208 s，reasons 为空；第 3 步三个臂全部通过；oracle 熔断成功率 1.0；单步 A 0.149、B 0.249、C 0.316 s；规划回合中位数 A 4.18、B 3.48、C 1.63 s；训练步数 3038。原样输出见 `smoke_rehearsal3_out.txt`。
- **预算推算（最坏情况：未训练的模型永远到不了目标）：**

  | dev 档位 | 全程 |
  |---|---|
  | (2048, 4096, 8192) | 53,844 s，约 15.0 h |
  | (2048, 4096) | 37,127 s，约 10.3 h |
  | 仅 (4096,) | 32,948 s，约 9.2 h |

  超出已登记的 10 h，已交用户决定。

## 全量
不跳过任何文件，前台 SIG_DFL+execv：3725 passed，7 deselected，0 failed（1025 s）。实盘 artifacts 前后 lstat 比对差异为 0。
