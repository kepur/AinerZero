# P230 第 3 轮：一级补两条测试后验收

执行：一级 claude，2026-11-12。gemini 不在线（半小时无人领卡），由一级补齐第 2 轮要求的两条测试。gemini-k7x2 写的源码一行未改。

## 补的测试（`tests/v9/experiments/test_s5_student_mlx.py` 末尾）
- `test_features_layer_index_matches_manual_blocks`：
  - 手动跑嵌入，加位置嵌入，再过前 k 个 block（k = 1、3、6）；
  - `features(layer=k)` 必须与手动结果逐元素一致；`layer=-1` 等于最后一层；
  - 还断言第 3、4 层确实不同，免得层号偏一位碰巧通过。
- `test_features_layer_index_with_partial_keep`：每 3 个保留 1 个，保留位置的特征与手动只跑保留 token 的结果一致。
- `test_distill_losses_average_only_inside_the_mask`：
  - mask 外的学生 token 与教师完全反向，mask 内完全相同；
  - `cosine_distill_loss` 和 `align_loss` 带 mask 时都等于 0；
  - 不带 mask 的对照大于 0.5。

## 复验（新隔离副本，持锁，`mutations.py` 加 `mutations-extra.py`）
- 基线：29 项全过。
- 14 处改动全部拦住，原始输出在 `mutations-r3-output.txt`。其中 E1（层号偏一位）由两条新测试拦住，E3（蒸馏损失忽略 mask）由 `test_distill_losses_average_only_inside_the_mask` 拦住。

## 待办
一级补的这三条测试还要非作者复核，并进下一张 S5 复核卡。
