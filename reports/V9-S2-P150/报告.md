# S2 静态测试补齐：A 臂总损失必须含 overshooting 项交付报告（ainerzero.V9.P150）

- **执行代理**：`gemini-f4b2`（二级执行 Agent）· 纯 CPU（只改测试，零 src 修改，零 MLX 导入）
- **修改文件**：
  - `tests/v9/experiments/test_s2_arms_static.py`：新增测试函数 `test_arm_a_loss_return_includes_overshooting_and_mean_from_losses`。
  - `reports/V9-S2-P150/`：交付物目录。
  - `src/`：**零修改（0 modified files in src/）**。

## 1. 静态 AST 断言实现
用 `ast` 语法树精确解析 `arm_a_loss_mlx`：
1. **Return 加法二元操作断言**：
   - 提取 `ast.Return` 节点表达式；
   - 验证其顶层为 `ast.BinOp(op=ast.Add())` 加法树；
   - 递归提取所有加法叶子项，断言三项必在其中：
     - 重建项（`mean_recon`）
     - 带 free bits 的 KL 项（`kl_penalized`）
     - 潜在过冲项（`mean_overshoot`）
2. **mean_overshoot 计算来源断言**：
   - 遍历函数体中的赋值节点，断言至少存在一处将 `overshoot_losses` 通过 `mean` 聚合赋值给 `mean_overshoot` 的操作；
   - 杜绝 `mean_overshoot` 恒为 0 或未从 `overshoot_losses` 计算的伪造逻辑。

## 2. 坏对照对抗变异（隔离沙盒执行，全数变红 KILLED，已按字节还原并核验 SHA256）
在隔离临时沙盒（复制 `src/`、`tests/`、`pyproject.toml`）中执行对抗变异测试：
- **P150-M1**（return 表达式中漏加 `mean_overshoot`）：
  - 目标单测：`test_arm_a_loss_return_includes_overshooting_and_mean_from_losses`
  - 结果：**变红拦截（KILLED，exit 1）**，抛出 `AssertionError: Overshooting term 'mean_overshoot' missing from arm_a_loss_mlx return addition: {'kl_penalized', 'mean_recon'}`。
- **P150-M2**（`mean_overshoot` 恒为 0，不取自 `overshoot_losses` 循环）：
  - 目标单测：`test_arm_a_loss_return_includes_overshooting_and_mean_from_losses`
  - 结果：**变红拦截（KILLED，exit 1）**，抛出 `AssertionError: mean_overshoot must be computed by averaging overshoot_losses (via mx.mean or equivalent)`。
- **P150-M3**（return 表达式非加法 BinOp，如改写为元组）：
  - 目标单测：`test_arm_a_loss_return_includes_overshooting_and_mean_from_losses`
  - 结果：**变红拦截（KILLED，exit 1）**，抛出 `AssertionError: Return value must be an addition BinOp (+), found: Tuple`。

## 3. 测试与回归计数
- `tests/v9/experiments/test_s2_arms_static.py`：**9 passed in 2.24s**（包含新增的第 9 项静态断言）。
- 默认全量纯 CPU 回归（SIG_DFL 还原信号）：
  - 总收集用例数：3573 项（3567 selected，6 deselected）；
  - 本卡新增用例运行通过（`test_arm_a_loss_return_includes_overshooting_and_mean_from_losses PASSED`）；
  - 实盘 `artifacts/` 80,929 项 stat 审计 **0 新增、0 删除、0 修改（零差异）**。
- **产物清单**：详见 `reports/V9-S2-P150/sha256.json`。
