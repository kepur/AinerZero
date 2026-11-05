# E1-M 指标模块实现与测试报告（ainerzero.V9.P66）

- **执行者**：gemini-k8f3（二级执行 agent，纯 CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P66`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · E1-M 指标卡
- **依据协议**：`reports/V9-P48/PREREG_DRAFT.md`（r2/r3）及 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md`
- **改动范围**：
  - 模块源码：`src/ainerzero/v9/experiments/e1/__init__.py`、`src/ainerzero/v9/experiments/e1/metrics.py`
  - 单元与坏对照测试：`tests/test_e1_metrics.py`
  - 产出交付件：`reports/V9-E1M/gemini-k8f3/`

---

## 1. 模块设计与指标实现

本模块严格执行纯 NumPy、零 GPU、无未授权外部依赖与零模型训练的原则，实现预登记 §4 与 §5 中冻结的全部指标：

### 1.1 k 步位置误差（$k \in \{1, 5, 10, 30\}$，主指标 $k=10$）
- **函数**：`compute_position_error`, `compute_k_step_position_errors`
- **窗口规则**：遵循真值与评测约定（`exclude_endpoints=True`），端点帧 $0$ 与 $T-1$ 排除在评测目标窗口之外（目标帧 $t+k \in [1+k, T-2]$）。
- **聚合**：计算各预测步长下的 Mean, Median, RMSE, Max 误差及有效目标帧数，返回主指标 $k=10$ 对应误差。

### 1.2 碰撞事件提取、去抖与 F1
- **函数**：`detect_collision_events`, `compute_collision_f1`
- **事件判定**：
  - 物体对从「无接触」（表面距离 $> 0.004$ m）变为「接触」（表面距离 $\le 0.004$ m），且法向相对闭合速度 $\ge 0.05$ m/s，触发一次碰撞。
  - **3 帧微弹跳去抖（Debounce）**：同一对物体分离（表面距离 $> 0.004$ m）后 $\le 3$ 帧内再次接触，合并为同一次事件，不重复触发新事件。当分离持续 $> 3$ 帧时，事件正式闭合。
- **匹配与 F1**：
  - 采用无偏 1 对 1 贪婪二分匹配，按开始帧时间差升序匹配；
  - 匹配容差 $\pm 1$ 帧且物体对一致（无向，对齐 canonical pair ID）；
  - 严格输出 Precision, Recall, F1 与混淆矩阵计数（TP, FP, FN）。

### 1.3 弹道段能量漂移（$|\Delta H| / H_0$）
- **函数**：`compute_ballistic_energy_drift`
- **公式**：机械能 $H(t) = \frac{1}{2} m \|\mathbf{v}(t)\|^2 + m g z(t)$，重力加速度 $g = 9.81$ m/s$^2$（Z 轴向上）。
- **弹道段筛选**：仅在连续 $\ge 5$ 帧无接触的飞行段上计算相对漂移 $\max_{t} \frac{|H(t) - H(t_0)|}{H(t_0)}$；$< 5$ 帧的瞬态分离自动丢弃。
- **定位**：纯物理与积分器诊断指标，不设通过门槛。

### 1.4 推理延迟汇总
- **函数**：`summarize_inference_latency`
- **统计**：输出各步耗时（ms）的 Median, p95, Mean, Min, Max 与步数。

### 1.5 种子聚合与配对 Bootstrap
- **函数**：`aggregate_seeds_macro`, `paired_bootstrap_ci`
- **种子宏平均**：每个训练种子独立计算其 episode 均值，随后对 3 个种子取宏平均。
- **配对 Bootstrap**：
  - 10,000 次重采样，冻结 RNG 种子 42（`BOOTSTRAP_SEED = 42`）；
  - 每次重采样严格复用同一组 episode 索引，对 Arm A 与 Arm B 以及各种子同步索引（全配对）；
  - 向量化高效重采样（200 个 episode 10,000 次重采样耗时 $< 0.2$ 秒）；
  - 输出点估计、宏平均、95% 置信区间分位数（2.5%, 97.5%）、区间宽度及是否包含 0。

### 1.6 失败子集单列
- **函数**：`stratify_failure_subset`
- **规则**：按 `DESIGN_CORE §2 第 9 条`，支持将指标在注册失败子集与非失败子集上单列并比对。

---

## 2. 单元测试与坏对照验证（tests/test_e1_metrics.py）

测试集包含 16 个测试用例，覆盖了解析真解、坏对照（变异预测强制沿劣化方向漂移）、去抖边界与抽样统计：

1. `test_frozen_constants_match_prereg`: 严格核对 11 项冻结参数（$k \in \{1, 5, 10, 30\}$, $k=10$, 0.004 m, 0.05 m/s, 去抖 3 帧, 容差 $\pm 1$ 帧, 弹道 $\ge 5$ 帧, $g=9.81$, 10000 次重采样, 种子 42, 95% 置信度）。
2. `test_position_error_known_answer_and_broken_control`: 零误差已知解、0.3 m 位移已知解及坏对照单调劣化检验。
3. `test_k_step_position_errors_sliding_window_and_endpoints`: 端点帧排除窗口检验与单 horizon 坏对照。
4. `test_position_error_rejects_invalid_inputs`: 形状错误、空数组与 NaN 严格拒绝。
5. `test_collision_detection_known_answer_and_velocity_threshold`: 碰撞速度阈值过滤（$0.12$ m/s 触发 vs $0.03$ m/s 抑制）。
6. `test_collision_debouncing_micro_bounce_vs_true_separation`: 微弹跳去抖（分离 2 帧合并为 1 次事件 vs 分离 4 帧形成 2 次独立事件）。
7. `test_collision_debouncing_exact_boundary`: 参数化验证 1, 2, 3 帧分离均合并，4 帧分离精确分裂。
8. `test_collision_f1_known_answer_and_match_tolerance`: 容差检验（$\pm 1$ 帧匹配成功 $F_1=1.0$ vs $+2$ 帧匹配失败 $F_1=0.0$、虚警导致精确率下降）。
9. `test_collision_f1_empty_cases`: 全空与单侧空事件边界情况处理。
10. `test_ballistic_energy_drift_analytical_free_fall`: 自由落体机械能守恒解析解（漂移 $< 10^{-12}$）。
11. `test_ballistic_segment_filtering_and_broken_control`: 4 帧过滤、5 帧计算及阻尼耗散坏对照检验。
12. `test_paired_bootstrap_full_resamples_performance_and_absolute_mode`: 200 episode × 10,000 次重采样绝对与相对模式全流程验证。
13. `test_summarize_inference_latency`: 延迟分位数统计与非有限值拒绝。
14. `test_aggregate_seeds_macro`: 3 种子分层宏平均已知解。
15. `test_paired_bootstrap_ci_coverage_and_broken_control`: 15% 优势置信区间不含 0、劣化坏对照及跨运行确定性重现。
16. `test_stratify_failure_subset`: 失败子集分组与均值单列验证。

### 测试执行结果：
```text
============================== 16 passed in 0.35s ==============================
```

---

## 3. 交付物完整性

- 模块：`src/ainerzero/v9/experiments/e1/metrics.py`
- 包入口：`src/ainerzero/v9/experiments/e1/__init__.py`
- 测试：`tests/test_e1_metrics.py`
- 交付与校验：`reports/V9-E1M/gemini-k8f3/`（含 REPORT.md, metrics.json, SHA256SUMS.txt）
- 纯 NumPy 运行，无未授权模型、无 GPU 负载。
