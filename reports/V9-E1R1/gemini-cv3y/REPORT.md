# ainerzero.V9.P73 执行报告（E1 入口 R1：评测 runner）

角色：executor；负责人：gemini-cv3y；时间：2026-10-29  
任务状态：reported；实验状态：completed  
任务依据：
- E1 实现计划 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1 入口拆卡 R1
- 预登记 r3 §4（评测指标：位置误差 $k \in \{1, 5, 10, 30\}$ 且内部帧不含端点、碰撞 F1、弹道机械能漂移、推理延迟）
- 冻结规范 `src/ainerzero/v9/experiments/e1/spec.py` 与 `metrics.py`
- 防伪硬性规则：生产代码零写死指标、零假检查点、所有指标与 SHA 均由真实运行与真实文件产出

输入身份：
- `src/ainerzero/v9/experiments/e1/metrics.py`
- `src/ainerzero/v9/experiments/e1/export.py`
- `src/ainerzero/v9/experiments/e1/prior.py`
- `src/ainerzero/v9/experiments/e1/spec.py`

修改文件（严格在文件范围内）：
- 新建：`src/ainerzero/v9/experiments/e1/eval_runner.py`
- 新建：`tests/test_e1_eval_runner.py`
- 交付：`reports/V9-E1R1/gemini-cv3y/REPORT.md`
- 交付：`reports/V9-E1R1/gemini-cv3y/metrics.json`
- 交付：`reports/V9-E1R1/gemini-cv3y/run_bad_controls.py`
- 交付：`reports/V9-E1R1/gemini-cv3y/bad_controls_summary.json`
- 交付：`reports/V9-E1R1/gemini-cv3y/SHA256SUMS.txt`

实际执行：
- 契约单测：`.venv-ainerzero/bin/pytest tests/test_e1_eval_runner.py -v`（7 项全过）
- 模块全测：`.venv-ainerzero/bin/pytest tests/test_e1_eval_runner.py tests/test_e1_train_runner.py tests/test_e1_export.py tests/test_e1_metrics.py tests/test_e1_prior.py tests/test_e1_arms_net.py tests/test_e1_arms_nonnet.py tests/test_e1_prereg.py -v`（84 项全过）
- 隔离变异坏对照：`python3 reports/V9-E1R1/gemini-cv3y/run_bad_controls.py`（4 项源码变异全部真实变红）
- 验证结果：纯 CPU / 零 GPU / 零网络 / 零假写死指标。

---

## 1. 架构与算法实现设计

本模块彻底消除了早期草案中写死伪指标的问题，为 E1 基准构建了完整、真实、无泄漏的评估执行器 `eval_runner.py`：

### 1.1 `evaluate_episode(arm, student_ep, truth_ep) -> dict`
- **输入隔离**：
  - `student_ep` 仅向臂输入脱敏观测前缀 `observed_prefix`（前 $T_{prefix} = 10$ 帧的状态历史，包含位置、线速度、四元数、角速度）及静态几何环境 `static_environment`（地面、斜坡、桌面、障碍盒）；
  - `truth_ep` 保留评估方真值（包含 `pairwise_collisions`、未脱敏轨迹）；
- **预测窗口**：
  - 臂向后预测未来的步数：$n_{future} = \min(30, T_{total} - PREFIX\_FRAMES)$；
- **位置误差评测（`compute_k_step_position_errors`）**：
  - 评测视界 $k \in (1, 5, 10, 30)$，主判定视界为 $PRIMARY\_K = 10$；
  - 构造拼接轨迹并严格配置 `exclude_endpoints=True`，完全遵循预登记 §4「评测窗口不含端点帧」契约，对有效内部帧计算欧氏距离误差；
- **独立碰撞事件与 F1 评测（`compute_collision_f1`）**：
  - **预测侧碰撞事件**：基于臂预测的位置与线速度，结合学生侧物体外接球半径 $R_{sphere}$ 以及静态几何体，计算活动-活动与活动-静态对的表面距离与法向相对速度；通过 `detect_collision_events` 独立提取预测侧碰撞事件；
  - **真值侧碰撞事件**：从评测端 `truth_ep["pairwise_collisions"]` 截取未来评测窗口 $[PREFIX\_FRAMES, PREFIX\_FRAMES + n_{future})$ 的真实法向接触距离与法向速度，独立提取真值侧碰撞事件；
  - 两个事件列表由 `compute_collision_f1` 在 `match_tolerance_frames=1` 下严格匹配，计算准确率（precision）、召回率（recall）与 $F_1$ 值；
- **弹道机械能漂移与质量不变性（`compute_ballistic_energy_drift`）**：
  - 仅在真值确定的自由弹道飞行区间（全物体连续 $\ge 5$ 帧无接触）上评估预测轨迹的机械能守恒性；
  - **数学证明（质量因子抵消）**：
    $$\mathcal{H}(t) = \frac{1}{2} m \|\mathbf{v}(t)\|^2 + m g z(t) = m \left( \frac{1}{2} \|\mathbf{v}(t)\|^2 + g z(t) \right) = m \tilde{\mathcal{H}}(t)$$
    相对机械能漂移公式为：
    $$\frac{|\mathcal{H}(t) - \mathcal{H}(0)|}{\mathcal{H}(0)} = \frac{|m \tilde{\mathcal{H}}(t) - m \tilde{\mathcal{H}}(0)|}{m \tilde{\mathcal{H}}(0)} = \frac{|\tilde{\mathcal{H}}(t) - \tilde{\mathcal{H}}(0)|}{\tilde{\mathcal{H}}(0)}$$
    由此，物体质量 $m$ 在相对机械能漂移计算中严格被分子分母消去。直接设置 `mass=1.0` 即可完全无损评估预测动能与重力势能的能量守恒率，彻底杜绝向学生侧或评测管道泄漏真实隐藏质量参数的风险；
- **推理延迟**：
  - 测量 `arm.predict` 的 CPU 墙上钟时间，除以 $n_{future}$ 得到单步平均延迟。

### 1.2 `evaluate_cell(arm, student_dir, evaluator_dir) -> dict`
- 遍历并配对学生端与评测端的序列文件（支持 JSON 与 JSONL 格式）；
- **Fail-Closed 防御**：若目录为空或未发现有效配对序列，**严禁返回默认值或占位假指标，必须抛出 `ValueError`**；
- 聚合多序列的宏观均值（位置误差、碰撞准确率/召回率/F1、机械能漂移、平均推理延迟）。

### 1.3 `evaluate_final_once(arm_factory, sealed_dir, expected_digest) -> dict`
- 严格通过 `export.open_sealed_final_once` 申请单次读取令牌 `FinalReadToken`；
- 验证封闭分区的 SHA-256 摘要与 expected_digest 严格匹配；
- 一旦读取，立即写入 `.READ_ONCE.json` 标记；后续任何再次读取或绕过令牌的读取均直接抛出 `FinalPartitionSealed`。

---

## 2. 核心实验实测值

| 评测对象 / 指标项 | 规范契约 / 预期要求 | 真实测量值 | 判定 |
|---|---|---|---|
| `PerfectArm` 10 步主位置误差 | 理论精确值 $0.0\text{ m}$ | `0.000000 m`（浮点 $0.0$） | **PASSED** |
| `PerfectArm` 碰撞 $F_1$ 值 | 完美匹配 $1.0$ | `precision=1.0`, `recall=1.0`, `f1=1.0` | **PASSED** |
| `PerfectArm` 弹道机械能漂移 | 接近能量守恒（$\approx 0.0$） | `mean_drift = 0.002851` | **PASSED** |
| `ErrorArm` 10 步主位置误差 | 显著大于 0 | `1.000000 m` | **PASSED** |
| `ErrorArm` 碰撞召回与 $F_1$ | 漏检碰撞，召回为 0 | `recall=0.0`, `f1=0.0` | **PASSED** |
| 预测碰撞 vs 真值碰撞独立性 | 幽灵碰撞：真值 0 次，预测 1 次 | `num_pred=1, num_true=0, f1=0.0` | **PASSED** |
| 预测碰撞 vs 真值碰撞独立性 | 漏检碰撞：真值 2 次，预测 0 次 | `num_pred=0, num_true=2, f1=0.0` | **PASSED** |
| `evaluate_cell` 空数据集防御 | 严禁返回默认字典，抛出 `ValueError` | `ValueError("No valid paired episodes...")` | **PASSED** |
| 封闭最终集 digest 校验失败 | 拒绝读取并抛出异常 | `FinalPartitionSealed("differs from expected...")` | **PASSED** |
| 封闭最终集二次读取防御 | 严禁重复读取，抛出 `FinalPartitionSealed` | `FinalPartitionSealed("already read...")` | **PASSED** |

---

## 3. 四项源码变异坏对照实验（隔离沙箱验证）

在独立临时沙箱中执行 `reports/V9-E1R1/gemini-cv3y/run_bad_controls.py`，证明 4 项变异在对应契约测试上全部真实变红（RED）：

```
======================================================================
RUNNING ISOLATED BAD CONTROLS FOR E1 EVAL RUNNER (ainerzero.V9.P73)
======================================================================

[MUTATION] bad_control_1_f1_truth_vs_truth: Collision F1 evaluated as truth vs truth instead of pred vs truth
Status: RED (FAILED as expected) (exit code 1)

[MUTATION] bad_control_2_drift_truth_trajectory: Ballistic energy drift evaluated on truth trajectory instead of arm prediction
Status: RED (FAILED as expected) (exit code 1)

[MUTATION] bad_control_3_empty_dataset_default: Empty dataset returns default dict instead of loudly raising ValueError
Status: RED (FAILED as expected) (exit code 1)

[MUTATION] bad_control_4_final_bypasses_token: Final partition evaluation bypasses open_sealed_final_once token
Status: RED (FAILED as expected) (exit code 1)

======================================================================
BAD CONTROLS SUMMARY:
[RED (FAILED as expected)] bad_control_1_f1_truth_vs_truth: Collision F1 evaluated as truth vs truth instead of pred vs truth
[RED (FAILED as expected)] bad_control_2_drift_truth_trajectory: Ballistic energy drift evaluated on truth trajectory instead of arm prediction
[RED (FAILED as expected)] bad_control_3_empty_dataset_default: Empty dataset returns default dict instead of loudly raising ValueError
[RED (FAILED as expected)] bad_control_4_final_bypasses_token: Final partition evaluation bypasses open_sealed_final_once token
======================================================================
Summary written to reports/V9-E1R1/gemini-cv3y/bad_controls_summary.json
ALL 4 BAD CONTROLS VERIFIED RED.
```

### 3.1 变异 1：F1 篡改为真值对真值（`all_true_events` vs `all_true_events`）
- **变异文件**：沙箱中 `eval_runner.py` 第 366 行
- **变异内容**：将 `compute_collision_f1(all_pred_events, all_true_events)` 篡改为 `compute_collision_f1(all_true_events, all_true_events)`
- **目标测试**：`tests/test_e1_eval_runner.py::test_error_arm_nonzero_position_error_and_missed_collision`
- **结果**：**RED (FAILED)**；`assert f1_dict["f1"] < 1.0` 失败，实际算出 F1 为 1.0。

### 3.2 变异 2：机械能漂移篡改为在真值轨迹上计算
- **变异文件**：沙箱中 `eval_runner.py` 第 388 行
- **变异内容**：将预测位置与速度替换为真值未来窗口的位置与速度
- **目标测试**：`tests/test_e1_eval_runner.py::test_energy_drift_evaluated_on_prediction_not_truth`
- **结果**：**RED (FAILED)**；`assert mean_drift > 0.5` 失败，因真值机械能守恒漂移仅为 0.0028。

### 3.3 变异 3：空数据集返回默认字典而非抛出异常
- **变异文件**：沙箱中 `eval_runner.py` 第 492 行
- **变异内容**：将 `raise ValueError(...)` 替换为 `return {"episodes": [], "summary": {}}`
- **目标测试**：`tests/test_e1_eval_runner.py::test_evaluate_cell_rejects_empty_dataset`
- **结果**：**RED (FAILED)**；`pytest.raises(ValueError)` 未捕获到异常而失败。

### 3.4 变异 4：最终集评测绕过单次读取令牌
- **变异文件**：沙箱中 `eval_runner.py` 第 567 行
- **变异内容**：直接构造假 Token 绕过 `open_sealed_final_once`
- **目标测试**：`tests/test_e1_eval_runner.py::test_evaluate_final_once_enforces_token_and_rejects_second_read`
- **结果**：**RED (FAILED)**；二次读取未触发 `FinalPartitionSealed` 异常，测试失败。

---

## 4. 结论与交付清单

1. `src/ainerzero/v9/experiments/e1/eval_runner.py` 完整实现，数学逻辑严谨（机械能漂移质量消去证明无泄漏），几何计算精确，端点帧排除符合预登记；
2. `tests/test_e1_eval_runner.py` 覆盖单集、多集聚合、空集报错、封闭集令牌与坏对照 7 项核心单测，全部通过；
3. E1 核心测试集 84 项全过；
4. 4 项坏对照在隔离沙箱中全部实测验证变红。
