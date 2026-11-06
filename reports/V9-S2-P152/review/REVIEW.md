本人 gemini-r7m2 确系独立非作者复核者，与被验卡 ainerzero.V9.P152 作者 gemini-a5b8 非同一会话、非同一 ID，全程独立复核。

# S2 smoke 第 3/4 步非作者复核报告（ainerzero.V9.P153）

- **复核任务**：`ainerzero.V9.P153`
- **被复核任务**：`ainerzero.V9.P152`（作者：`gemini-a5b8`）
- **复核代理**：`gemini-r7m2`（二级执行 Agent）
- **复核环境**：Apple Silicon (MacBook Pro), 纯 CPU 环境，零 MLX 导入/运行，零实盘写入
- **复核结论**：**RECOMMEND_ACCEPT**（建议验收）

---

## 一、独立性与范围审计

1. **执行者与会话独立性**：
   - 被验卡作者为 `gemini-a5b8`；复核者为 `gemini-r7m2`；
   - 经 Relay 接力台登记校验，两者具备不同 Agent ID 与独立会话指纹，不属于同一会话别名。
2. **源码与测试范围**：
   - 作者仅新增两处文件，无多余改动：
     - `src/ainerzero/v9/experiments/s2/smoke_checks.py`（SHA256: `090a404e5dde55c5d59a105eb7f045c31ec83f930a4753653c521d5176c359d7`）
     - `tests/v9/experiments/test_s2_smoke_checks.py`（SHA256: `9f4eabbf935aca9d643a4ae1168c7ebb49a4990b949da9e7e567c2a7ea2bb04e`）
   - 经逐字节 SHA256 对比，与报告完全一致。
   - `artifacts/` 目录：80,929 项真实 artifact stat 审计结果 **0 新增、0 修改、0 删除**。

---

## 二、反捏造逐行核对

复核者逐行通读 `smoke_checks.py` 全文，确认：
1. **零常数指标与零假门**：
   - 代码中无任何硬编码指标、预设成功率或回退默认值；
   - 指标必须由传入的真实或假臂 step 输出、状态预测序列或世界推演实时计算。
2. **空输入/None 边界严格抛错**：
   - `short_train_sanity(None, ...)` 抛出 `ValueError: arm must implement train_step`；
   - `short_train_sanity(object(), None, ...)` 抛出 `ValueError: arm must implement train_step`；
   - `short_train_sanity(arm, batches, S=10)` 抛出 `ValueError: S must be an integer >= 20, got 10`；
   - `action_sensitivity(None, states)` 抛出 `ValueError: predict_fn must be a callable`；
   - `action_sensitivity(fn, [])` 抛出 `ValueError: states must be a non-empty sequence`；
   - `oracle_feasibility([])` 抛出 `ValueError: layout_specs must be a non-empty sequence`；
   - `oracle_feasibility([None])` 抛出 `TypeError: Invalid layout_spec format`。
   全部输入缺失均被 fail-closed 拦截。

---

## 三、算法与附录 B 独立复核

1. **短训健全性（short_train_sanity）**：
   - 包含附录 B 规定的三项严格断言：
     1. 所有步的损失严格有限（无 NaN/Inf）；
     2. 末 20 步均值严格小于首 20 步均值（`mean_last < mean_first`）；
     3. 若提供 `sigreg_probe`，SIGReg 末值不得超过初值的 1.1 倍（`final_sigreg <= 1.1 * initial_sigreg`）。
2. **动作敏感性公式（action_sensitivity）**：
   - 复核者构造独立 2 状态分析例：
     - $z_1 = [1, 0]$（norm=1.0），$z_2 = [0, 2]$（norm=2.0），均值 norm = 1.5；
     - 动作 0 与 1 给出两两距离为 2.0；
     - 理论解析归一化敏感性为 $2.0 / 1.5 = 1.333333333333$；
     - 代码运行计算结果与解析手算值差值为 `0.0e+00`，完全一致。
3. **Oracle 任务可行性独立复跑（GridLab-S2 新世界种子 200 与 201）**：
   - 复核者在作者测试所用种子（101, 102）之外，独立选取符合对称拒绝率约束的合法新世界种子 **200 与 201**；
   - 各生成 6 个长目标对（BFS 最短步数 ≥ 40，回合上限 $L = 3 \times \text{BFS}$），共 12 回合；
   - 在真实 GridLab 动力学推演与 CEM 规划器（$N_{\text{fwd}}=2000$）下复跑：
     - **总回合数**：12
     - **成功回合数**：11
     - **实际成功率**：**91.67%（11/12）**
     - **熔断判定**：`fuse_triggered=False`，`passed=True`；
   - 在极端预算耗尽（$N_{\text{fwd}}=8$）下复跑：成功率精确降至 **0.00%（0/12）**，`fuse_triggered=True`，熔断门有效触发。

---

## 四、测试真伪核查

- `tests/v9/experiments/test_s2_smoke_checks.py` 共包含 13 个独立测试；
- 逐项核实测试直接调用 `smoke_checks.py` 内部函数（`short_train_sanity`、`action_sensitivity`、`oracle_feasibility`），非测试重写逻辑，非硬编码断言。

---

## 五、自做 4 处变异测试（作者变异表之外，全数变红 KILLED）

复核者在隔离临时沙盒（独立复制 `src/`、`tests/`、`pyproject.toml`）中执行 4 处全新变异：

| 变异 ID | 变异描述 | 目标单测 | 退出码 | 变异状态 | 还原校验 |
|---|---|---|:---:|:---:|:---:|
| **REV-M1** | 颠倒损失下降判断条件（`mean_last < mean_first` 改为 `>=`） | `test_short_train_sanity_decreasing_loss_passes` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-M2** | 绕过 SIGReg 1.1x 稳定性上限（硬赋 `sigreg_stable = True`） | `test_short_train_sanity_sigreg_increase_fails` | 1 | **KILLED (RED)** | SHA 匹配 |
| **REV-M3** | 破坏动作敏感性归一化公式（`mean_pairwise / mean_norm` 改为 `* 1.5`） | `test_action_sensitivity_hand_calculated_analytic` | 5 | **KILLED (RED)** | SHA 匹配 |
| **REV-M4** | 截断 Oracle 最大推演步数（`bfs_dist * 3` 改为 1） | `test_oracle_feasibility_on_gridlab_two_worlds` | 1 | **KILLED (RED)** | SHA 匹配 |

4 项自做变异全部精准变红拦截，无存活，且还原后 SHA256 完全一致。

---

## 六、纯 CPU 隔离与全量回归计数

1. **子进程 -I 隔离导入验证**：
   - 运行 `/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python -I` 导入 `s2` 及 `smoke_checks`；
   - 验证 `sys.modules` 中不存在任何 `mlx` 相关模块，完全纯 CPU。
2. **全量纯 CPU 回归测试**（SIG_DFL 还原信号）：
   - 收集用例数：3601 项；
   - 排除原生模块（deselected）：6 项；
   - 实际运行用例数（selected）：3595 项；
   - 回归测试结果：**3595 passed, 0 failed in 268.92s**；
   - 实盘 `artifacts/` 80,929 项 stat 审计差异数：**0**。

---

## 七、复核判定

被验任务 `ainerzero.V9.P152` 算法严谨契合附录 B，无虚假硬编码常数，独立复跑与自做变异均稳固通过，全量回归 0 失败。

**复核结论：RECOMMEND_ACCEPT（建议验收）**
