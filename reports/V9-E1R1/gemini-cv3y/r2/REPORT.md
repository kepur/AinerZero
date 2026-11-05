# ainerzero.V9.P73 执行报告（E1 入口 R1：评测 runner · r2 修正版）

角色：executor；负责人：gemini-cv3y；时间：2026-10-29  
任务状态：reported；实验状态：completed  
任务依据：
- 一级统筹（claude）验收意见：其余各项全部成立（预测/真值碰撞分离、全对覆盖防误报、预测轨迹算漂移、空数据报异常、final 经令牌单次读取、4 项坏对照全红），**r2 仅改一处：消除 8 个常量的重复定义，统一从 `metrics.py` 导入**。
- 冻结规范 `src/ainerzero/v9/experiments/e1/metrics.py` 与 `spec.py`
- 防伪硬性规则：生产代码零写死指标、零假检查点、所有指标与 SHA 均由真实运行与真实文件产出

输入身份：
- `src/ainerzero/v9/experiments/e1/metrics.py`
- `src/ainerzero/v9/experiments/e1/export.py`
- `src/ainerzero/v9/experiments/e1/prior.py`
- `src/ainerzero/v9/experiments/e1/spec.py`

修改文件（严格在文件范围内）：
- 修改：`src/ainerzero/v9/experiments/e1/eval_runner.py`
- 修改：`tests/test_e1_eval_runner.py`
- 交付：`reports/V9-E1R1/gemini-cv3y/r2/REPORT.md`
- 交付：`reports/V9-E1R1/gemini-cv3y/r2/metrics.json`
- 交付：`reports/V9-E1R1/gemini-cv3y/r2/run_bad_controls.py`
- 交付：`reports/V9-E1R1/gemini-cv3y/r2/bad_controls_summary.json`
- 交付：`reports/V9-E1R1/gemini-cv3y/r2/SHA256SUMS.txt`

实际执行：
- 契约单测：`.venv-ainerzero/bin/pytest tests/test_e1_eval_runner.py -v`（8 项全过）
- 模块全测：`.venv-ainerzero/bin/pytest tests/test_e1_eval_runner.py tests/test_e1_train_runner.py tests/test_e1_export.py tests/test_e1_metrics.py tests/test_e1_prior.py tests/test_e1_arms_net.py tests/test_e1_arms_nonnet.py tests/test_e1_prereg.py -v`（85 项全过）
- 隔离变异坏对照：`python3 reports/V9-E1R1/gemini-cv3y/r2/run_bad_controls.py`（5 项源码变异全部真实变红）
- 验证结果：纯 CPU / 零 GPU / 零网络 / 零写死假指标。

---

## 1. r2 修正说明

针对一级统筹指出的「eval_runner 重复定义 8 个已有冻结常量」问题，r2 执行了完全彻底的统一化治理：

1. **直接从 `metrics.py` 导入 8 个已有冻结常量**：
   ```python
   from ainerzero.v9.experiments.e1.metrics import (
       BALLISTIC_MIN_FRAMES,
       COLLISION_DEBOUNCE_FRAMES,
       COLLISION_MATCH_TOLERANCE_FRAMES,
       COLLISION_VELOCITY_THRESHOLD_MPS,
       CONTACT_TOLERANCE_M,
       DEFAULT_K_STEPS,
       DEFAULT_K_STEPS as DEFAULT_EVAL_K_STEPS,
       GRAVITY_ACCEL,
       PRIMARY_K,
       ...
   )
   ```
2. **本模块仅保留真正的新常量**：
   ```python
   PREFIX_FRAMES: int = 10      # 待一级冻结: number of prefix observation frames
   MAX_FUTURE_FRAMES: int = 30  # 待一级冻结: maximum rollout horizon
   ```
   杜绝任何因局部硬编码导致未来 metrics/spec 修改时评测悄悄沿用旧值的风险。
3. **增加单测 `test_constants_imported_directly_from_metrics`**：
   断言 `eval_runner` 中的 8 个常量与 `metrics` 模块的对象完全同源（使用 `is` 判定内存对象一致性）。
4. **增加坏对照 `bad_control_0_local_threshold_override`**：
   在隔离沙箱中将 `CONTACT_TOLERANCE_M` 本地重定义为 `0.03`，断言直接失败（`AssertionError: assert 0.03 is 0.004`），证明该单测具备有效拦截能力。

---

## 2. 核心实验实测值

| 评测对象 / 指标项 | 规范契约 / 预期要求 | 真实测量值 | 判定 |
|---|---|---|---|
| 常量对象同源性（8 项） | 与 `metrics.*` 完全同一对象（`is`） | `assert runner.CONST is metrics.CONST` 全数通过 | **PASSED** |
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

## 3. 五项源码变异坏对照实验（隔离沙箱验证）

在独立临时沙箱中执行 `reports/V9-E1R1/gemini-cv3y/r2/run_bad_controls.py`，证明 5 项变异在对应契约测试上全部真实变红（RED）：

```
======================================================================
RUNNING ISOLATED BAD CONTROLS FOR E1 EVAL RUNNER R2 (ainerzero.V9.P73)
======================================================================

[MUTATION] bad_control_0_local_threshold_override: Redefine CONTACT_TOLERANCE_M locally to 0.03 instead of importing from metrics.py
Status: RED (FAILED as expected) (exit code 1)

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
[RED (FAILED as expected)] bad_control_0_local_threshold_override: Redefine CONTACT_TOLERANCE_M locally to 0.03 instead of importing from metrics.py
[RED (FAILED as expected)] bad_control_1_f1_truth_vs_truth: Collision F1 evaluated as truth vs truth instead of pred vs truth
[RED (FAILED as expected)] bad_control_2_drift_truth_trajectory: Ballistic energy drift evaluated on truth trajectory instead of arm prediction
[RED (FAILED as expected)] bad_control_3_empty_dataset_default: Empty dataset returns default dict instead of loudly raising ValueError
[RED (FAILED as expected)] bad_control_4_final_bypasses_token: Final partition evaluation bypasses open_sealed_final_once token
======================================================================
Summary written to reports/V9-E1R1/gemini-cv3y/r2/bad_controls_summary.json
ALL 5 BAD CONTROLS VERIFIED RED.
```

### 3.1 变异 0：本地重定义阈值 `CONTACT_TOLERANCE_M = 0.03`
- **变异文件**：沙箱中 `eval_runner.py`
- **变异内容**：局部添加 `CONTACT_TOLERANCE_M: float = 0.03`
- **目标测试**：`tests/test_e1_eval_runner.py::test_constants_imported_directly_from_metrics`
- **结果**：**RED (FAILED)**；`AssertionError: assert 0.03 is 0.004`。

### 3.2 变异 1：F1 篡改为真值对真值（`all_true_events` vs `all_true_events`）
- **变异文件**：沙箱中 `eval_runner.py`
- **变异内容**：将 `compute_collision_f1(all_pred_events, ...)` 篡改为 `compute_collision_f1(all_true_events, ...)`
- **目标测试**：`tests/test_e1_eval_runner.py::test_error_arm_nonzero_position_error_and_missed_collision`
- **结果**：**RED (FAILED)**；`assert f1_dict["f1"] < 1.0` 失败，实际算出 F1 为 1.0。

### 3.3 变异 2：机械能漂移篡改为在真值轨迹上计算
- **变异文件**：沙箱中 `eval_runner.py`
- **变异内容**：将预测位置与速度替换为真值未来窗口的位置与速度
- **目标测试**：`tests/test_e1_eval_runner.py::test_energy_drift_evaluated_on_prediction_not_truth`
- **结果**：**RED (FAILED)**；`assert mean_drift > 0.5` 失败，因真值机械能守恒漂移仅为 0.0028。

### 3.4 变异 3：空数据集返回默认字典而非抛出异常
- **变异文件**：沙箱中 `eval_runner.py`
- **变异内容**：将 `raise ValueError(...)` 替换为 `return {"episodes": [], "summary": {}}`
- **目标测试**：`tests/test_e1_eval_runner.py::test_evaluate_cell_rejects_empty_dataset`
- **结果**：**RED (FAILED)**；`pytest.raises(ValueError)` 未捕获到异常而失败。

### 3.5 变异 4：最终集评测绕过单次读取令牌
- **变异文件**：沙箱中 `eval_runner.py`
- **变异内容**：直接构造假 Token 绕过 `open_sealed_final_once`
- **目标测试**：`tests/test_e1_eval_runner.py::test_evaluate_final_once_enforces_token_and_rejects_second_read`
- **结果**：**RED (FAILED)**；二次读取未触发 `FinalPartitionSealed` 异常，测试失败。

---

## 4. 结论与交付清单

1. `src/ainerzero/v9/experiments/e1/eval_runner.py` 中的 8 个冻结常量现已严格从 `metrics.py` 导入，消除重复定义；
2. `tests/test_e1_eval_runner.py` 增加常量同源性单测，8 项单测全部通过；
3. E1 核心测试集 85 项全过；
4. 5 项坏对照在隔离沙箱中全部实测验证变红。
