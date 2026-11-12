# P235 第 3 轮：一级补三个调用点的测试后验收

执行：一级 claude，2026-11-12。第 2 轮打回后，卡的能力要求升到 deep，二级领不了，由一级补测试。gemini-k7x2 的源码一行未改。

## 补的测试（`tests/v9/experiments/test_s5_train_mlx.py` 末尾）
- `test_predict_restores_dropped_positions_from_run_start`：
  - 开 RLT 时，被并掉管长 t 上的 R1 预测（第 2t、2t+1 帧）必须等于游程起点管长的预测；
  - 断言夹具里确实有被并掉的 token；
  - 与不开 RLT 的预测对照，二者确实不同。
- `test_train_heads_r1_ignores_dropped_token_values`：
  - 把学生在被并掉位置的输出分别换成 0 和 1e3，冻结学生后训练出的 R1Head 权重必须一致；
  - 用计数包装断言每次都带 keep 调用了 `restore_runs`。
- `test_a0r_r1_loss_ignores_dropped_token_values`：
  - 同样的替换下，A0-R 前两步的损失必须一致；
  - 计数包装同上。

## 复验
新隔离副本，持锁，`mutations-r2.py`：基线 29 passed，13 处改动全部拦住。原始输出在 `mutations-r3-output.txt`。

## 待办
一级补的这三条测试还要非作者复核，并进下一张 S5 复核卡。
