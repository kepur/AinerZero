# E1-AN 阶段二分析与判定模块修复报告（Round 2 / r2）

- **任务 ID**: `ainerzero.V9.P80`
- **执行 Agent**: `gemini-w7m2`（二级执行 agent，模型：gemini）
- **状态**: 修复完成（Ready for Review）
- **交付范围**:
  - 核心实现：`src/ainerzero/v9/experiments/e1/analysis.py`
  - 测试套件：`tests/test_e1_analysis.py`
  - 交付产物：`reports/V9-E1AN/gemini-w7m2/r2/REPORT.md`、`reports/V9-E1AN/gemini-w7m2/r2/data.json`、`reports/V9-E1AN/gemini-w7m2/r2/SHA256SUMS.txt`
  - 历史留存：`reports/V9-E1AN/gemini-w7m2/before/`（r1 原始实现与测试备份）

---

## 1. r1 审查驳回点与 r2 针对性修复

在 r1 审查中，统筹 Lead（Claude）指出以下关键隐患：
1. **静默默认值隐患**：代码中存在 4 处 `.get("collision_f1", 0.0)`。若评测单元因故障丢失 `collision_f1`，基线 F1 会静默降为 $0.0$，导致 Arm 3 的碰撞保护门槛被虚假绕过（恒满足 $F_1 \ge 0.0$）。
2. **误差提取结构不纯**：`_extract_10_step_error_from_summary` 包含 `position_error_10_step` 和 `primary_error_m` 等旧假跑脚本的 fallback 字段；`_extract_episode_10_step_errors` 在缺失误差时降级为 `0.0`，污染配对自举置信区间。
3. **缺乏真实集成测试**：缺少真实 `eval_runner.evaluate_cell` 输出与 `analysis.py` 之间端到端数据加载与解析测试。

### r2 实施的具体修复：
1. **彻底清除静默默认值**：
   - 彻底移除了全部 4 处 `.get("collision_f1", 0.0)`。
   - 新增专职提取函数 `_extract_collision_f1_from_summary(summary)`：严格要求 `summary` 中存在 `"collision_f1"` 且不能为 `None`，缺失时立即抛出响亮异常（`KeyError` 或 `ValueError`），拒绝任何静默默认。
2. **对齐真实 `eval_runner` 严格数据协议**：
   - 更新 `_extract_10_step_error_from_summary`：只接受 `summary["k_step_errors"]["10"]`（或整数键 `10`）。彻底删除所有 fallback keys（`primary_error_m`, `position_error_10_step`）。缺失时立即抛出 `KeyError`。
   - 更新 `_extract_episode_10_step_errors`：严格要求每集数据包含 `position_errors["10"]["mean_error_m"]`，彻底删除回退为 `0.0` 的逻辑。空列表或非法格式响亮抛出 `ValueError` / `KeyError`。
3. **新增真实 `eval_runner` 集成测试**：
   - 在 `tests/test_e1_analysis.py` 中新增 `test_real_eval_runner_integration_with_analysis`：
     - 用物理真实先验构造包含弹跳与自由落体的 3 条数据，使用真实 `export_sequence` 导出学生端和真值端。
     - 真正调用 `eval_runner.evaluate_cell` 评测 Arm 1（`PriorArm`）和 Arm 4（`TrueParamArm`）。
     - 生成评测单元文件并落盘，调用 `analysis.load_cells(..., allow_partial=True)` 加载。
     - 验证 `_extract_10_step_error_from_summary`、`_extract_collision_f1_from_summary`、`_extract_episode_10_step_errors` 完全无缝、精准提取出真实数值。
4. **新增缺失字段防御性测试**：
   - 新增 `test_missing_collision_f1_loudly_raises_exception`：验证缺失 `collision_f1` 或为 `None` 时响亮抛出异常；验证磁盘文件中 Arm 1 缺少 F1 时 `decide_h_e1` 响亮失败，杜绝静默放行。
   - 新增 `test_missing_10_step_error_or_episodes_loudly_raises_exception`：验证缺失 10 步误差、非法结构或空 episodes 均响亮拒绝。

---

## 2. 关键代码 Diff 对比（r1 vs r2）

```diff
--- reports/V9-E1AN/gemini-w7m2/before/analysis.py
+++ src/ainerzero/v9/experiments/e1/analysis.py
@@ -73,31 +73,43 @@
 def _extract_10_step_error_from_summary(summary: Mapping[str, Any]) -> float:
-    """Extract 10-step mean position error from summary dict."""
-    k_step_errors = summary.get("k_step_errors", {})
-    if "10" in k_step_errors:
+    """Extract 10-step mean position error strictly from summary dict."""
+    if "k_step_errors" not in summary:
+        raise KeyError("Missing 'k_step_errors' mapping in evaluation summary")
+    k_step_errors = summary["k_step_errors"]
+    if not isinstance(k_step_errors, Mapping):
+        raise ValueError(f"Summary 'k_step_errors' must be a mapping, got {type(k_step_errors)}")
+    if "10" in k_step_errors and k_step_errors["10"] is not None:
         return float(k_step_errors["10"])
-    if 10 in k_step_errors:
+    if 10 in k_step_errors and k_step_errors[10] is not None:
         return float(k_step_errors[10])
-    if "primary_error_m" in summary and summary["primary_error_m"] is not None:
-        return float(summary["primary_error_m"])
-    if "position_error_10_step" in summary:
-        return float(summary["position_error_10_step"])
-    raise KeyError("Could not locate 10-step position error in summary")
+    raise KeyError("Could not locate 10-step position error in summary['k_step_errors']")

+def _extract_collision_f1_from_summary(summary: Mapping[str, Any]) -> float:
+    """Extract collision F1 score strictly from summary dict (no silent default)."""
+    if "collision_f1" not in summary:
+        raise KeyError("Missing 'collision_f1' in cell evaluation summary")
+    val = summary["collision_f1"]
+    if val is None:
+        raise ValueError("'collision_f1' in summary cannot be None")
+    return float(val)

@@ -208,3 +220,3 @@
-    f1_1 = float(cell_1.get("summary", cell_1.get("metrics", {})).get("collision_f1", 0.0))
+    f1_1 = _extract_collision_f1_from_summary(sum_1)
```

---

## 3. 测试验证与全套回归

### 3.1 单元测试（11 项全过，耗时 0.73 秒）
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_analysis.py -v
```
输出：
- `test_h_e1_boundary_10_percent_pass_and_9_99_percent_fail` PASSED
- `test_h_e1_f1_non_decreasing_condition` PASSED
- `test_h_e1_baseline_selection_takes_min_of_arm1_and_arm2` PASSED
- `test_missing_cells_loudly_raises_exception` PASSED
- `test_h_p_similarity_approx_boundary_conditions` PASSED
- `test_h_e1_families_are_evaluated_independently_never_pooled` PASSED
- `test_diagnostic_arm4_does_not_affect_h_e1_decision` PASSED
- `test_full_pipeline_write_report` PASSED
- `test_missing_collision_f1_loudly_raises_exception` PASSED
- `test_missing_10_step_error_or_episodes_loudly_raises_exception` PASSED
- `test_real_eval_runner_integration_with_analysis` PASSED
**结果**：11 passed in 0.73s。

### 3.2 E1 全套回归测试（124 项全过，耗时 13.37 秒）
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -v
```
覆盖 `test_e1_analysis.py`、`test_e1_arms_net.py`、`test_e1_arms_nonnet.py`、`test_e1_data_runner.py`、`test_e1_entry.py`、`test_e1_eval_runner.py`、`test_e1_export.py`、`test_e1_metrics.py`、`test_e1_prereg.py`、`test_e1_prior.py`、`test_e1_train_runner.py`、`test_e1_wiring.py`。
**结果**：124 passed in 13.37s，零警告，零回归。

---

## 4. 破坏性对照实验（Bad Controls / Mutation Testing）

在隔离目录 `/tmp/e1_an_r2_mutants/` 下构建了 5 个变异体，并在独立环境运行对应的测试项，全部证实转红（Exit Code 1，断言触发）：

| 编号 | 变异体描述 | 对应破坏点 | 目标拦截测试 | 退出码 | 变异结果 |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **Mutant 1** | 恢复静默默认值 | `f1_1 = float(sum_1.get("collision_f1", 0.0))` | `test_missing_collision_f1_loudly_raises_exception` | 1 | **RED**（DID NOT RAISE KeyError） |
| **Mutant 2** | 放宽减误门槛 | 阈值由 $0.10$ 改为 $0.05$ | `test_h_e1_boundary_10_percent_pass_and_9_99_percent_fail` | 1 | **RED**（9.99% 错误通过） |
| **Mutant 3** | 删除碰撞保护 | `f1_passed = True`（忽略 F1 跌落） | `test_h_e1_f1_non_decreasing_condition` | 1 | **RED**（F1 跌落却误判通过） |
| **Mutant 4** | 偏见固定对照 | 固定对照臂为 Arm 1（忽略 Arm 2 较优） | `test_h_e1_baseline_selection_takes_min_of_arm1_and_arm2` | 1 | **RED**（未选出更优的 Arm 2） |
| **Mutant 5** | 掩盖单族失败 | 将两族判定合并平均，而非双独立门禁 | `test_h_e1_families_are_evaluated_independently_never_pooled` | 1 | **RED**（S 族未达标被掩盖） |

**证明**：5 个破坏性对照全部以 exit code 1 失败，严格证明了分析判定逻辑与测试套件的双向锁定，杜绝了静默默认值漏洞与判定标准虚晃。

---

## 5. 文件 SHA256 校验和

```
ddb4599a62e6b58fc24857819009ffa3431f432ce6e88e1c5300505f8df82b03  src/ainerzero/v9/experiments/e1/analysis.py
ac622c246b9399582332edae7c3707d4c148a53a984e50c64511aff2af434511  tests/test_e1_analysis.py
```
