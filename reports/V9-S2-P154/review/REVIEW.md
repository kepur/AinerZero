本人 gemini-b7x4 确系独立非作者复核者，与被验卡 ainerzero.V9.P154 作者 gemini-7k2q 非同一会话、非同一 ID，全程独立复核。

# S2 smoke 收口非作者复核报告（ainerzero.V9.P156）

- **复核任务**：`ainerzero.V9.P156`
- **被复核任务**：`ainerzero.V9.P154`（作者：`gemini-7k2q`）
- **复核代理**：`gemini-b7x4`（二级执行 Agent · text, code, math）
- **复核环境**：Apple Silicon (MacBook Pro), 纯 CPU 环境，零 MLX 导入/运行，零实盘写入
- **复核结论**：**RECOMMEND_ACCEPT**（建议验收）

---

## 一、独立性与交付范围审计

1. **执行者与会话独立性自证**：
   - 被验卡作者为 `gemini-7k2q`（会话与任务记录于 2026-11-07 00:05–00:26）；
   - 复核者为 `gemini-b7x4`（会话 `sess-bf83650114e6`，注册于 2026-11-07 00:35）；
   - 经 Relay 接力台登记校验，两者具备不同 Agent ID 与独立会话指纹，绝无同会话换 ID 自审。
2. **交付文件 SHA256 逐项核验**：
   - `src/ainerzero/v9/experiments/s2/smoke.py`: `41c07f3d9381d43d3b12928f08982aa638e3ef24df5b69ead93c0ac77ee4929e`（匹配）
   - `src/ainerzero/v9/experiments/s2/smoke_checks.py`: `13a03b7565be654191ffc8b2092a086fa7eabf0aa62893a8f1edfecebd8eb560`（匹配）
   - `src/ainerzero/v9/experiments/s2/spec.py`: `b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`（匹配）
   - `tests/v9/experiments/test_s2_wiring.py`: `c04b5cdb298b470a0d6e0c4ee9cbebb09277210dda4db15af0e91013100e0ec0`（匹配）
   - `tests/v9/experiments/test_s2_smoke_checks.py`: `d4ed6e933f83e26c45c6a13230299b583020d66ea4678ce4fe91e441802b6c3b`（匹配）
3. **源码范围与实盘纯净性**：
   - `src/ainerzero/v9/experiments/s2/` 下其他模块未受本次任务波及；
   - 实盘 `artifacts/` 目录 80,929 项 stat 审计结果为 **0 新增、0 修改、0 删除**。

---

## 二、反捏造与汇总逻辑核查

1. **AST 源码静态审计**：
   - 扫描 `smoke.py` 与 `smoke_checks.py`，确认无任何硬编码常量指标字典（如固定赋予成功率、假敏感性、假损失等）；
   - `run_smoke` 严格执行 fail-closed，缺失任何必须实测量（`arms_by_id`、`step_times` 等）时立即置 `passed=False`。
2. **多臂故障组合穿透测试**：
   复核者构造 4 组假臂及输入异常组合，验证汇总判定及错误归因精确性：
   - **Combo 1（Arm A 短训损失上升）**：判定 `passed=False`，reasons 精确点名 `Step 3 short-train sanity failed for arm_a`；
   - **Combo 2（Arm B 短训 SIGReg 激增 100x）**：判定 `passed=False`，reasons 精确点名 `Step 3 short-train sanity failed for arm_b`；
   - **Combo 3（三臂通过 Step 3，Step 4 Oracle 规划达成率 0.02 < 0.05）**：判定 `passed=False`，reasons 精确点名 `Step 4 oracle feasibility circuit breaker triggered`；
   - **Combo 4（缺失 step_times 耗时实测）**：判定 `passed=False`，reasons 精确点名 `Missing single-step timing measurements` 与预算分析失败。

---

## 三、Oracle 熔断门走 S2 规划器与新世界复跑

1. **调用链路核验**：
   - 核对 `smoke.py`（行 449 与行 615）确认熔断门统一路由至 `smoke_checks.oracle_feasibility_with_s2_planner`；
   - 深入 `oracle_feasibility_with_s2_planner` 确认核心规划器为 `s2/planner.flat_cem_plan`，受 `ForwardCounter(budget=n_fwd)` 严密监控；
   - 原 P152 `_default_oracle_mpc` 严格降级为对照参考（记录于 `default_oracle_comparison`），不参与主门限熔断决策。
2. **新世界独立复跑（新种子 301 与 302）**：
   - 复核者在作者测试种子（101, 102）之外，独立选取符合对称拒绝率约束的合法新世界种子 **301 与 302**；
   - 生成 12 个长目标回合规格（BFS 最短距离 ≥ 40，步数上限 $L = 3 \times \text{BFS}$）；
   - 在 $N_{\text{fwd}} = \text{spec.N\_FWD} = 4096$ 下复跑实测：
     - **总回合数**：12
     - **成功回合数**：12
     - **实际成功率**：**100.0%（12/12）**
     - **熔断判定**：`fuse_triggered=False`，`passed=True`；
   - 在极端预算耗尽（$N_{\text{fwd}}=8$）下复跑：
     - **成功率**：**0.00%（0/12）**
     - **熔断判定**：`fuse_triggered=True`，熔断门即刻生效。
3. **数据分区隔离**：
   - `generate_smoke_partition` 严格定位在 `datasets/smoke/` 目录下；
   - `check_smoke_seed_namespace` 拦截任何包含 `train`、`dev`、`final`、`sealed_final` 的命名空间，有效杜绝数据穿透。

---

## 四、测试真伪与门限合理性审计

1. **测试逻辑真伪**：
   - `tests/v9/experiments/test_s2_smoke_checks.py`（14 个测试）与 `test_s2_wiring.py`（21 个测试）均直接导入生产函数；
   - 零测试端重写业务逻辑，零常数比对常数虚假单测。
2. **门限依据与解析校核**：
   - 熔断阈值 0.05 契合附录 B 规范；
   - SIGReg 稳定性门限 1.1x 契合附录 B 防表示坍塌标准；
   - 动作敏感性单测包含手算解析例（$z=[1,0]$，4 动作基准向量），实测输出精确匹配理论闭式解 $\frac{2\sqrt{2}+2}{3}$（相对误差 $< 10^{-9}$）。

---

## 五、自做 4 处独立变异测试（作者变异表之外，4/4 全部 KILLED）

复核者在独立临时沙箱副本（断言 import 解析至 replica）中执行 4 处全新变异测试，每项变异在测试后均按字节完全还原：

| 变异 ID | 变异描述 | 目标单测 | 退出码 | 变异状态 | 还原校验 |
|---|---|---|:---:|:---:|:---:|
| **REV-M1** | 篡改 `oracle_feasibility_with_s2_planner` 返回规划器身份标识为 `default_oracle` | `test_oracle_feasibility_with_s2_planner_two_worlds` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-M2** | 破坏训练步数最差臂约束（改 `min(...)` 为 `max(...)`） | `test_smoke_timing_and_training_steps_minimum_rule` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-M3** | 破坏反捏造兜底，在 `run_smoke` 结尾无条件赋 `passed=True` | `test_smoke_no_injected_measurements_fails_with_named_reasons` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-M4** | 压制 S2 规划器熔断门（默认 threshold 设为 -1.0 使低预算不熔断） | `test_oracle_feasibility_with_s2_planner_two_worlds` | 1 | **KILLED (RED)** | SHA 匹配 |

4/4 处独立自做变异全部精准变红拦截，无一存活，还原后 SHA256 逐字节一致。

---

## 六、纯 CPU 导入与默认全量回归计数

1. **子进程 `-I` 隔离导入验证**：
   - 运行 `.venv/bin/python -I` 导入 `s2.smoke`, `s2.smoke_checks`, `s2.spec`；
   - 检查 `sys.modules`，`mlx` 相关模块计数为 **0**。
2. **前台默认全量纯 CPU 回归测试**（SIG_DFL 还原信号，未加 `--native-mlx`）：
   - 收集用例数：3613 项；
   - 排除原生模块（deselected）：6 项；
   - 实际运行用例数（selected）：3607 项；
   - 回归测试结果：**3607 passed, 0 failed in 340.69s (0:05:40)**；
   - 实盘 `artifacts/` 80,929 项 stat 审计差异数严格为 **0**。

---

## 七、复核结论

被复核任务 `ainerzero.V9.P154` 代码实现严格契合设计附录 B（r2.3）规范：S2 规划器真实驱动 Oracle 熔断门，反捏造机制完备严密，新世界复跑达成率扎实（100%），自做变异全数被杀，全量回归 3607 项纯 CPU 测试 100% 通过且零实盘改动。

**复核结论：RECOMMEND_ACCEPT（建议验收）**
