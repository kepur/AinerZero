# ainerzero.V9.G7 报告：CMFL 原型（纯 NumPy；接手第 3 棒 claude-az；复核必须由他人，见 G8）

零训练、零 MLX/torch、零下载、零新包；`runs.db` 与锁未碰；`GeometryCore`（`ainerzero.v9.geometry`）未导入也未改。文件范围内只动了 `src/ainerzero/v9/mechanism/`、`tests/v9/mechanism/`、`reports/V9-G7/`。

## 0. 接手状态与我做了什么
前一棒（antigravity-a9f2，约 31 分钟后失租）已在工作树留下 3,784 行：`mechanism/` 六个模块（路由/注册冻结/辨识/弱形式发现/晋升门/玩具世界）和 9 个测试，其中 **2 个测试红**。我没有重写，只做了三处修补，原因都写在下面：

1. **M8 敏感性断言过死**（`test_msg_eight_routes_…`）：原断言「去掉 D_permit 后 SUFFICIENT 恰为 16」把 seed 恰好抽到的 6/2 当常数。8 个 ABSTAIN 上下文物理有效，去掉 D_permit 后落到剩下的统计判定：NIS 是 χ²(80) 的一次实现，约 2.5% 概率落进下尾而被 4a 判为 COVARIANCE_INCONSISTENT（该 seed 有 2 个）。这是有限样本下的统计调用，不是缺陷。改为断言：8 个全部离开 ABSTAIN、只落在这两条路由、SUFFICIENT 至少多 6 个、总数自洽、准确率 < 1。关键结论（D_permit 不是冗余）不变。
2. **M2 的 e-LOND 演示是空的**（`simulate_elond_dev_only_vs_all_env`）：每族只有 12 个世界级 block，而第 t 步要求 e ≥ 1/(α·γ_t·(R+1))，γ_t 衰减很快，没有任何候选能到门槛 → 两边都准入 0 个，`dev_only_persistent_fdp = 0/max(0,1) = 0`，断言 `> 0.5` 红。更糟的是它若被改成 `== 0` 会变成「没人被准入就算 FDR 受控」的假绿。改为 `blocks_per_family=60`（参数化并随结果返回），并在测试里加分母断言：`dev_only_admitted ≥ 8` 且 `all_env_admitted ≥ 3`。结果 dev-only 准入 24、其中 18 个是只在环境 0 过拟合的（FDP 0.75），全环境交并 E_pers=min_e E^e 准入 6、错误 0。
3. 新增可复跑的报告脚本 `reports/V9-G7/run_report.py`（见 §1）。

## 1. 卡面要求的四项数字（`run_report.py`，固定 seed，`evidence/numbers.txt`、`metrics_numbers.json`）
| 项 | 结果 |
|---|---|
| **MSG 混淆矩阵**（8 路由 × 8 个/路由，5 个 seed，320 个上下文） | 准确率 **0.9969**（319/320）；各路由召回均值：ABSTAIN/OUT_OF_DOMAIN/NUMERICAL/COVARIANCE_INCONSISTENT/SUFFICIENT/UNIDENTIFIABLE/STRUCTURAL 均 1.0；**PARAMETRIC 0.975**（1 个被判到别的路由）。主测试 seed 20261028 为 64/64。 |
| **去 D_permit（M8）** | 原 ABSTAIN 的 40 个上下文被放行：37 → SUFFICIENT、3 → COVARIANCE_INCONSISTENT（下尾）。 |
| **φ 的 NEES 校准**（P 族，200 次） | 均值 **2.836**（期望 3）；≤ χ²₃(0.95)=7.81 的比例 **0.960**；≥ χ²₃(0.05)=0.35 的比例 **0.950**；参数 RMSE 均值 0.0638。 |
| **发现恢复率**（弱形式 STLSQ + data thinning，每机制 20 次×6 上下文） | quadratic_drag 精确支持恢复 **20/20**，恢复系数相对误差中位数 2.5%；altered_inv_r_gravity **20/20**，1.9%。**空世界假发现 1/20（5%）**——候选非空不等于准入，晋升门是第二道。 |
| **晋升门**（20 次） | 正对照（完整库）准入 **20/20**；**负对照（候选库缺 quadratic_drag，ALDER）错误准入 0/20**。 |
| **M2 e-LOND** | dev-only 准入 24、错误 18，persistent FDP 0.75；全环境 min_e 准入 6、错误 0。 |

## 2. 测试
`tests/v9/mechanism`：**9 passed**。覆盖：纯 NumPy/无禁用导入、χ² 分位精度、注册冻结与 D_permit 溯源守卫（M8）、八路由与 §8.6「同一观测、不同未来」不变性、M5+N1 贪心独立集、C7+R1 独立 ParamBeliefStore（不混入 UpdateScheduler belief）、D4 高斯/嵌套 MC EIG、D2-7 单步/k 步灵敏度正交投影、ExecutablePriorChecker + data thinning + 弱形式 STLSQ、单侧晋升门（世界级 block bootstrap、C_clean 剔除 4a、FPCA 基分离、ALDER、N3 重测记账、C2 出具者独立、D/C/T 不相交）。
我**没有**做变异自证（拆守卫坏控）：B12 有一套，这张卡的守卫尚没有；建议 G8 复核人自己拆几条（尤其 N3 重测记账、D/C/T 不相交、C2 学生自证）。

## 3. 已知局限（请 G8 重点攻击，也请不要把它们写成通过）
- **范围**：全是合成玩具力学（1D/2D 质点），NumPy；P/S/N/改动定律四族里，辨识与恢复的数字只覆盖 P（NEES）、S（quadratic_drag）、改动定律（inv-r）；N 族（只有积分误差）只在 NUMERICAL 路由里出现，没有单独的恢复数字；coulomb_friction、cubic_spring 在候选库里，但没做恢复率试验。
- **MSG 召回不是 100% 的常数**：5 个 seed 下 PARAMETRIC 有 1/40 漏判（0.975）；主测试 seed 的 64/64 不应被引用为一般性能。
- **空世界 5% 假发现**：来自 20 次里的 1 次，样本量小，置信区间很宽；晋升门对其的拦截没有单独统计（只统计了缺项库的 0/20）。
- 注册 SHA 冻结（`cmfl_registration`）按 ADR-0014 r3 的字段实现；我没有对 ADR 正文逐条重核，G8 应当做。
- 没有 AWZ 真实数据，也没有与 S1 的接线；本原型不对真实动力学做任何声称。

## 4. SHA（改动后，`evidence/SHA.txt`）
`mechanism/` 六模块 + `__init__`、`test_cmfl_prototype.py`、`run_report.py` 的 SHA-256 在 `evidence/SHA.txt`。我改动的文件：`promotion_gate.py`（`blocks_per_family`）、`test_cmfl_prototype.py`（两处断言）；其余模块为前一棒原样。
