# P235 一级对抗验收（第 1 轮）：打回

验收人：一级 claude，2026-11-12。

## 已核实，没问题
- C-sh 按错排取别段的教师目标。
- R 臂的 DA2 有效区域：keep 按 4×4 放大到 56×56 后作为 valid；V-JEPA 损失只在保留 token 上算。
- 种子在学生初始化之前设置。
- 读教师特征时逐文件核对 `progress.jsonl` 的 SHA。
- 冻结学生的读出头训练：先用 `stop_gradient` 抽取学生 token 并缓存，只更新读出头。
- 检查点按 `ckpt_every_frac` 存，最后一步必存。

## 必须改（设计口径；已写进设计稿 r1 末尾「实现阶段补记」第 3、4 条）
1. **RLT 下 R1 读出的取法。**
   - 现状：A0-R 训练、`train_heads`、`predict` 里，被并掉位置的学生输出是零向量，被直接送进 `R1Head`，而且算进 R1 损失。这会把 R1Head 的偏置拉向「从零向量猜深度」。
   - 改成：被并掉的位置，取同一空间位置上、所在游程起点（最近一个保留的管长）那个 token 的输出，作为 R1Head 的输入。三处都照此改。
   - 写一个辅助函数，例如 `restore_runs(tokens, keep) -> tokens`，三处共用。
   - 加测试：全保留时 `restore_runs` 是恒等；部分保留时，被并掉位置的 token 等于其游程起点的 token；在 A0-R 里把被并掉位置的学生输出改成极端值，R1 损失不变。
2. **A4 对齐特征必须取自同一次前向。**
   - 现状：`loss_fn` 里先 `model.student(...)` 前向一次，再调 `model.student.features(patches_mx, ...)`，又跑了一遍完整前向，A4 每步的计算量约翻倍，与设计 §6 的预算（约 +10%）不符。
   - 改成：前向后直接取本次前向缓存的第 `align_layer` 层特征，即 `model.student.features(layer=...)` 不传 patches。这在同一个计算图里，梯度一样。
   - 加测试：A4 一步里 `Student.__call__` 只被调用一次（例如包一层计数）。
3. **教师特征只读一次。**
   - 现状：不开 C-sh 时，`distill` 对每段调两次 `load_item`。第二次只为取教师特征，却重读学生帧、重算 tubelet 和全部标签，数据读取耗时约翻倍。
   - 改成：加一个只读教师特征的函数，例如 `load_teacher(index, i, teachers)`，仍然核对 SHA；C-sh 用它读 `perm[i]` 的教师特征。

## 改坏源码（隔离副本，持锁，`mutations.py`，原始输出在 `mutations-output.txt`）
基线 20 项全过。8 处改动拦住 5 处，漏网 3 处：

| 改动 | 结果 |
|---|---|
| T3 A4 对齐层用 `align_layer + 1` | **漏网**：`test_a4_alignment_gradients` 只检查梯度存不存在，没检查是哪一层 |
| T5 `train_supervised` 不设 `mx.random.seed` | **漏网**：确定性测试没覆盖 `train_supervised` |
| T8 A2 蒸馏的余弦损失不传 mask | **漏网**：没有「R 臂里 V-JEPA 损失只算保留 token」的测试 |

## 必须补的测试（都调用生产代码）
- **T3：** 构造只有第 `align_layer` 层特征与教师完全对齐的情形（或者直接比对喂给 `align_proj` 的张量），断言喂进去的就是该层的输出；`align_layer` 加一则失败。
- **T5：** `train_supervised` 同一配置跑两次，权重逐元素相同。两次之间先用别的种子扰乱全局随机状态，例如 `mx.random.seed(999)`，确认确定性来自 `cfg.seed` 本身。
- **T8：** R 臂加 A2 时，把被并掉 token 对应的 V-JEPA 教师特征改成极端值，损失不变。
- 加上第 1、2 条的新测试。
- 修完用 `mutations.py` 复验 8 处全部拦住，原始输出放进报告。改源码脚本只能在隔离副本里跑。
