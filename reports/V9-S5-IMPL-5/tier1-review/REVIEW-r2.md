# P235 一级对抗验收（第 2 轮）：打回，补三个调用点的测试

验收人：一级 claude，2026-11-12。

## 已改对
- `restore_runs`：逐管长往后传。保留的位置用自己的 token，被并掉的位置沿用最近一个保留的 token。
- 训练、读出头、预测三处都调用了 `restore_runs`。
- A4 改成取同一次前向缓存的那一层特征。
- 教师特征改由 `load_teacher` 单独读取，仍核对 SHA。

## 改坏源码（隔离副本，持锁，`mutations-r2.py`，原始输出在 `mutations-r2-output.txt`）
- 基线 26 项全过。
- 第 1 轮的 8 处改动全部拦住。
- 新加的 5 处里拦住 2 处：U1（还原不往后传）、U4（把第二次前向加回来）。
- 漏网 3 处：

| 改动 | 结果 |
|---|---|
| U2 `predict` 去掉 `restore_runs` | **漏网** |
| U3 `train_heads` 去掉 `restore_runs` | **漏网** |
| U5 A0-R 训练（`train_supervised` 开 tau）去掉 `restore_runs` | **漏网** |

现有测试只测 `restore_runs` 函数本身。`test_a0_r_dropped_tokens_r1_loss_invariance` 也没走 `train_supervised` 的损失路径：U1 让它失败，U5 却没有。所以三个调用点有没有真的用上还原，没有测试检查。

## 必须补（都调用生产代码）
1. **predict（U2）：**
   - 开 tau 且确实有 token 被并掉时，被并掉的管长 t 上该位置的 `r1_logd`（第 2t、2t+1 帧）必须等于其游程起点管长同位置的预测；
   - 不开 tau 时两者不必相等，用作对照。
2. **train_heads（U3）：**
   - 用一个计数包装替换 `train` 模块里的 `restore_runs`（monkeypatch），开 tau 时断言 R1 的每次损失计算都调用了它，且传入的 keep 不为 None；
   - 再加一条语义检查：被并掉位置缓存 token 的值改成极端值，训练出的 R1Head 权重不变。
3. **A0-R（U5）：**
   - 在 `train_supervised`（cfg.tau 不为 None）里，同样用计数包装断言每步都调用了 `restore_runs`；
   - 或者给出语义测试：被并掉位置的学生输出不影响 R1 损失。
4. 修完用 `mutations-r2.py` 在隔离副本里复验 13 处全部拦住，原始输出放进报告。
