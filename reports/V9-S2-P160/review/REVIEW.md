本人 gemini-b7x4 确系独立非作者复核者，与被验卡 ainerzero.V9.P160 作者 gemini-8f4b 非同一会话、非同一 ID，全程独立复核。

# S2 冻结前清理非作者复核报告（ainerzero.V9.P161）

- **复核任务**：`ainerzero.V9.P161`
- **被复核任务**：`ainerzero.V9.P160`（作者：`gemini-8f4b`）
- **复核代理**：`gemini-b7x4`（二级执行 Agent · text, code, math）
- **复核环境**：Apple Silicon (MacBook Pro), 纯 CPU 环境，零 MLX 导入/运行，零实盘写入
- **复核结论**：**RECOMMEND_ACCEPT**（建议验收）

---

## 一、独立性与交付范围审计

1. **执行者与会话独立性自证**：
   - 被验卡作者为 `gemini-8f4b`（任务会话记录于 2026-11-07 01:09–01:19）；
   - 复核者为 `gemini-b7x4`（会话 `sess-bf83650114e6`，注册于 2026-11-07 00:35）；
   - 经 Relay 接力台校验，两者具备不同 Agent ID 与独立会话指纹，绝无同会话换 ID 自审。
2. **交付文件 SHA256 逐项核验**：
   - `src/ainerzero/v9/experiments/s2/smoke.py`: `c5be1859a3d14ad801c540abcad2c483e03f578f6cd4cc1f17a2f9b4f549a7fa`（匹配）
   - `src/ainerzero/v9/experiments/s2/smoke_checks.py`: `8749e22002b56f69db7def4b5bf7f3f2140d711450a084364516979c1957a226`（匹配）
   - `tests/v9/experiments/test_s2_smoke_checks.py`: `23c96b62a689f8d724e3b0a89e4fe285ef678d38aad1dbb3d7c64e2356a5d0f7`（匹配）
   - `tests/v9/experiments/test_s2_wiring.py`: `5d7631c803b602e3bbceaef2c35b650daef7a697597c281e87ca332f89f6cb9d`（匹配）
3. **源码与实盘范围纯净性**：
   - `src/ainerzero/v9/experiments/s2/` 目录下其他文件与前一卡逐字节一致，无多余未登记改动；
   - 实盘 `artifacts/` 80,929 项 stat 审计差异数严格为 **0**。

---

## 二、S2 包全仓 AST 扫描与默认值清理核验

1. **AST 全仓遍历**：
   - 复核者编写独立脚本遍历 `src/ainerzero/v9/experiments/s2/*.py` 所有抽象语法树中的 `getattr(spec, ...)` 节点；
   - 全仓仅发现 3 处带有默认值的调用，且全部位于 `data_runner.py`（针对 `REGISTERED_HOST_ROOT` 和 `REGISTERED_OUTPUT_ROOT`，系 P138 约定的过渡回退白名单）；
   - `smoke.py`、`smoke_checks.py` 等核心流程中 **零 `getattr(spec, ..., 默认值)`**。
2. **步数常量来源统一与预登记一致性**：
   - `smoke.py` 中 4 处步数引用（模块级常量、数据生成、Step 3 真实执行分支、Step 3 模拟分支）全部统一定点读取 `spec.SMOKE_SHORT_TRAIN_STEPS`；
   - 经与 `spec.py` 核对，`SMOKE_SHORT_TRAIN_STEPS = 200`，与附录 B 及预登记规格完全一致；
   - 原 `SMOKE_SHORT_STEPS` 在 `spec.py` 中仅按单调追加历史规范保留，在 `smoke.py` 中已无任何引用。

---

## 三、回合规格缺字段严厉报错核验

复核者构造缺失关键字段的非法回合规格，直接调用两处 Oracle 规划入口函数进行穿透测试：
1. **缺失 `bfs_distance`**：
   - `smoke_checks.oracle_feasibility`: 精准抛出 `ValueError: Missing bfs_distance in episode spec 0`；
   - `smoke_checks.oracle_feasibility_with_s2_planner`: 精准抛出 `ValueError: Missing bfs_distance in episode spec 0`；
   - 彻底消除了原先静默回退默认值 `40` 的漏洞。
2. **缺失 `goal`**：
   - `smoke_checks.oracle_feasibility`: 精准抛出 `ValueError: Missing goal in episode spec 0`；
   - `smoke_checks.oracle_feasibility_with_s2_planner`: 精准抛出 `ValueError: Missing goal in episode spec 0`。
3. **缺失 `start`**：
   - `smoke_checks.oracle_feasibility`: 精准抛出 `ValueError: Missing start in episode spec 0`；
   - `smoke_checks.oracle_feasibility_with_s2_planner`: 精准抛出 `ValueError: Missing start in episode spec 0`。

---

## 四、自做 3 处独立变异测试（作者变异表之外，3/3 全部 KILLED）

复核者在独立临时沙箱副本（断言 import 解析至 replica）中执行 3 处全新变异测试，每项变异在测试后均按字节完全还原：

| 变异 ID | 变异描述 | 目标单测 | 退出码 | 变异状态 | 还原校验 |
|---|---|---|:---:|:---:|:---:|
| **REV-P160-M1** | 缺 goal 时回退至 start_raw 而不抛错 | `test_oracle_feasibility_missing_start_or_goal_raises` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-P160-M2** | `generate_smoke_partition` 硬编码 200 而不读 `spec.SMOKE_SHORT_TRAIN_STEPS` | `test_smoke_fails_when_smoke_short_train_steps_missing` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-P160-M3** | 缺 start 时回退至 fake origin 而不抛错 | `test_oracle_feasibility_missing_start_or_goal_raises` | 1 | **KILLED (RED)** | SHA 匹配 |

3/3 处独立自做变异全部精准变红拦截，无一存活，还原后 SHA256 逐字节一致。

---

## 五、纯 CPU 导入与默认全量回归计数

1. **子进程 `-I` 隔离导入验证**：
   - 运行 `.venv/bin/python -I` 导入 `s2.smoke`, `s2.smoke_checks`, `s2.spec`；
   - 检查 `sys.modules`，`mlx` 相关模块计数为 **0**。
2. **前台默认全量纯 CPU 回归测试**（SIG_DFL 还原信号，未加 `--native-mlx`）：
   - 收集用例数：3627 项；
   - 排除原生模块（deselected）：6 项；
   - 实际运行用例数（selected）：3621 项；
   - 回归测试结果：**3621 passed, 0 failed in 297.43s (0:04:57)**；
   - 实盘 `artifacts/` 80,929 项 stat 审计差异数严格为 **0**。

---

## 六、复核结论

被复核任务 `ainerzero.V9.P160` 清理工作严谨完备：成功移除全部 `getattr(spec, ..., 默认值)`（除白名单），统一使用预登记的 `SMOKE_SHORT_TRAIN_STEPS`，回合规格缺少 `bfs_distance`、`goal` 或 `start` 时均精准 fail-closed 抛错，自做变异 100% 拦截，全量回归 3621 项纯 CPU 测试 100% 通过且零实盘改动。

**复核结论：RECOMMEND_ACCEPT（建议验收）**
