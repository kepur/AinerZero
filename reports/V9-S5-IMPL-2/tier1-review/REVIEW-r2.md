# P230 一级对抗验收（第 2 轮）：打回，只差两条测试

验收人：一级 claude，2026-11-12。

## 结果
- 新建隔离副本，持锁跑原生测试，基线 26 项全过。
- **第 1 轮的 10 处改动（`mutations.py`）：** 全部拦住。新补的五条测试都调用生产代码，写得对：
  - 补齐隔离：批量 2，两个样本保留数 500 与 1000，各自与单跑比对；
  - SSI 平移不变；
  - R1Head 帧顺序；
  - DepthDistillHead 空间排列；
  - 游程长度嵌入。
  - 原始输出在 `mutations-r2-output.txt`。
- **一级新加的 4 处改动（`mutations-extra.py`）：** 拦住 2 处，漏网 2 处。原始输出在 `mutations-extra-output.txt`。

| 改动 | 结果 |
|---|---|
| E1 `features(layer=k)` 的层号偏一位（`idx = layer`，两处） | **漏网** |
| E2 GridHead 掩码极性反了 | 拦住（test_grid_head_mask_invariance） |
| E3 `cosine_distill_loss` 忽略 mask | **漏网** |
| E4 置换改成 Fisher–Yates（可能有不动点） | 拦住（test_permutation_no_fixed_points_and_determinism） |

## 为什么这两处要紧
- **E1：** 设计冻结了「A4 对齐学生第 3 层」。层号偏一位，等于悄悄改了冻结参数。`test_student_features_parity_call_vs_cache` 只比较两种调用方式是否一致，两边带着同一个偏移，测不出来。
- **E3：** 开 RLT 时，被并掉的 token 在 `Student` 输出里是零向量。蒸馏损失不按 mask 平均，这些零向量就会进入 R 臂的蒸馏目标。

## 必须补
1. **层号语义：**
   - 手动跑：嵌入，加位置嵌入，再依次过前 k 个 `blocks`（k = 1、3、6）；
   - 断言 `features(patches, layer=k)` 与手动结果逐元素一致；
   - 再断言 `layer=-1` 等于最后一层（未过最终 LayerNorm 的那个）。
   - 用全保留和部分保留两种输入各测一次。
2. **蒸馏损失的 mask：**
   - 构造 mask 为 False 的位置上学生与教师完全反向、mask 为 True 的位置上完全相同；
   - 断言 `cosine_distill_loss` 与 `align_loss` 都等于 0（误差 < 1e-5）；
   - 不传 mask 时大于 0。
3. 用 `mutations.py` 与 `mutations-extra.py` 复验，14 处全部拦住，原始输出放进报告。
