# S2 训练后两道门：动作敏感性门与 C 臂打乱子目标负对照（P156）

## 1. 任务背景与依据
依据 `reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 B（smoke 程序修订，一级 claude，2026-11-06）：
- **完整训练之后、dev 之前（在 plan-select 阶段，只用 train 分区）**：
  1. **动作敏感性门**：对 64 个状态，比较 4 个动作分别给出的下一潜状态，算两两 L2 距离的平均值，再除以潜状态范数的平均值。任何臂低于 0.05，记为「不可规划」，停下，不进 dev。
  2. **C 臂打乱子目标负对照**：在 train 分区的 50 个规划回合上，分别用真子目标和打乱后的子目标规划。成功率降幅 < 0.10 时，标记「E₂ 合谋/下层没用子目标」，停下，不进 dev。
- **一律禁止**：缺任何实测量时，只能判失败。不得用常数、示例值或默认值顶替。

## 2. 代码实现
在 `src/ainerzero/v9/experiments/s2/eval_runner.py` 中实现了：
1. **常量与异常定义**：
   - `ACTION_SENSITIVITY_FLOOR = 0.05`
   - `SUBGOAL_DROP_FLOOR = 0.10`
   - `PostTrainGateError(ValueError)`：非法参数或非 train 分区传给门控时抛出。
   - `PostTrainGateRefused(RuntimeError)`：门控未通过或未登记时拒绝进入 dev 评测。
2. **`run_post_train_gates` 入口**：
   - 强约束分区：对传入的所有 episode specs 检查 partition，若非 `"train"` 立即抛出 `PostTrainGateError`。
   - 动作敏感性：调用 `smoke_checks.action_sensitivity`，计算各臂 4 动作两两 L2 距离均值归一化状态模长均值。任一臂低于 0.05 标记为 `不可规划`。
   - C 臂负对照：对分层臂（C 臂）在 50 个训练回合上分别用真子目标与打乱子目标（基于已登记 seed 打乱并消除不动点）进行规划评测。成功率降幅低于 0.10 判定为 `E₂ 合谋/下层没用子目标`。
   - 结果写入：支持自动写入 `ledger_path` 的 `post_train_gates` 字段，以及保存为独立 JSON。
3. **`run_dev_eval` 前置检查**：
   - 在进入 dev 评测主循环前，检查 ledger 中是否存在 `post_train_gates` 记录且 `passed == True`。
   - 若缺失记录或任一门失败，抛出 `PostTrainGateRefused` 并附带明确拒绝原因（不可规划或合谋）。

## 3. 测试覆盖
在 `tests/v9/experiments/test_s2_eval_runner.py` 中新增并验证：
- `test_post_train_gates_rejects_dev_or_final_specs`：非 train 分区立即拒绝。
- `test_unplannable_arm_fails_gate_and_dev_refused`：动作敏感性低于 0.05 判定不可规划并阻止 dev。
- `test_c_arm_collusion_detected_and_dev_refused`：子目标打乱后降幅低于 0.10 判定合谋并阻止 dev。
- `test_normal_model_passes_post_train_gates_and_enters_dev`：正常模型两道门全过，顺利进入 dev 并完成评测。
- `test_dev_eval_refused_without_post_train_gates`：未跑 post_train_gates 直接调用 dev 评测被拒。
- `test_s2_eval_runner.py` 套件 16 条全过（1.04s）。

## 4. 坏对照变异测试（M1, M2, M3）
在隔离沙箱环境中执行坏对照变异：
- **P156-M1**（跳过 dev 前置检查）：`test_dev_eval_refused_without_post_train_gates` 报红（KILLED）。
- **P156-M2**（放宽合谋降幅阈值至 -1.0）：`test_c_arm_collusion_detected_and_dev_refused` 报红（KILLED）。
- **P156-M3**（C 臂打乱退化为恒等排列未真正打乱）：`test_normal_model_passes_post_train_gates_and_enters_dev` 报红（KILLED）。
- 变异测试恢复后验证源码 SHA256 严格一致。

## 5. 全量 Pure-CPU 回归
- 恢复默认信号处理器 `SIG_DFL`。
- 测试命令：`.venv/bin/python -m pytest`
- 结果：**3607 passed, 6 deselected, 0 failed**（用时 360.98s）。
- Artifacts stat audit：80,929 个条目，diff = 0。

## 6. 文件与 SHA256 清单
- `src/ainerzero/v9/experiments/s2/eval_runner.py`: `b19fa70c06269d53af16cf9a02f59a658a2d86732beaa45ba9d3d73ed553ddbc`
- `tests/v9/experiments/test_s2_eval_runner.py`: `8124a22fd3b135f7e1e230b943cdd99f326c6470c4d269be21b8bede0581d1a0`
