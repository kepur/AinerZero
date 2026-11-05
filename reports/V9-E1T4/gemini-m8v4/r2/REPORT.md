# E1 诊断臂 ④ 按 episode 取真 φ* 修复报告（r2）

- **任务编号**：`ainerzero.V9.P81`
- **轮次**：r2（根据一级统筹 Claude 2026-10-29 16:1x 审查要求：彻底删除静默降级与兜底）
- **执行代理**：`gemini-m8v4`（二级执行层）
- **日期**：2026-10-29
- **工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`

---

## 1. r2 审查意见与整改目标

一级统筹 Claude 在 r1 审查中确认按 episode 取 φ* 的主体已经成立，但指出了四处会让 ④ 静默退化成 ① 的静默降级逻辑：
1. **`fallback_map`**：物体缺少物理参数字段时，曾改用臂上的 `param_map`（有偏先验）；需彻底删除 `fallback_map` 参数及其所有逻辑，没有物理参数字段一律抛 `KeyError`。
2. **`is_arm_4` 的启发式判断**：曾按名字含 "arm4"、"trueparam" 或 `arm_id==4`、`diagnostic_only` 猜测，可能把别的臂误判定为 Arm ④；需严格限制为只保留 `isinstance(arm, TrueParamArm)` 和 `isinstance(arm, type) and issubclass(arm, TrueParamArm)`。
3. **占位实例本身能预测**：worker 原来构造的是 `TrueParamArm(true_params=DEFAULT_BIASED_PRIOR)`，绕过逐 episode 注入时会按有偏先验静默运行；需改为构造不可预测的占位 `TrueParamArm(true_params=None)`，未注入真参数时预测直接抛 `RuntimeError("④ requires per-episode φ* injection")`。
4. **`TrueParamArm` 查参数兜底**：`arms_nonnet.py:339–343` 在查不到物体名时退到 `"default"`，再查不到取首个物体参数；需改为只按名字查，查不到抛 `KeyError`；`extract_true_phi_from_episode` 遇到非 Mapping 的 `b_info` 抛 `TypeError`。
5. **死代码与共享状态清理**：删除评测循环中逐 episode 改写共享实例 `param_map` 的代码；彻底删除无人调用的 `worker._extract_true_phi_from_evaluator`。

---

## 2. 修改细节与实现说明

所有改动严格遵守文件范围限制：
- `src/ainerzero/v9/experiments/e1/eval_runner.py`
- `src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- `src/ainerzero/v9/experiments/e1/worker.py`
- `tests/test_e1_arms_net.py`
- `tests/test_e1_eval_runner.py`
- `tests/test_e1_analysis.py`（按指示补充包含仅 shape/dimensions 的 fixture 参数）
- `reports/V9-E1T4/gemini-m8v4/r2/`

### 2.1 `eval_runner.py`
- **签名与实现精简**：`extract_true_phi_from_episode(truth_ep)` 彻底移除 `fallback_map` 参数。若 `b_info` 缺少任何一项物理参数（`friction`, `restitution`, `mass`, `linear_damping`, `angular_damping`），严格抛出带有物体名和 sequence_id 的 `KeyError`。遇到非 Mapping 的 `b_info` 抛出 `TypeError`。
- **精确判定**：`is_arm_4(arm, arm_name=None)` 移除所有启发式字符串匹配与属性猜测，只严格判断 `isinstance(arm, TrueParamArm) or (isinstance(arm, type) and issubclass(arm, TrueParamArm))`。
- **纯粹函数式注入**：在 `evaluate_cell` 和 `evaluate_final_once` 循环中，仅构造局部的 `ep_arm = TrueParamArm(true_params=phi_map, radii=...)`，彻底删除了旧版原位修改共享实例 `arm.param_map` 的逻辑。

### 2.2 `arms_nonnet.py` (`TrueParamArm`)
- **不可预测占位**：`__init__` 支持 `true_params=None`。当 `param_map is None` 时，`predict()` 与 `_get_params()` 立即抛出 `RuntimeError("④ requires per-episode φ* injection")`。
- **删除按名查参数兜底**：`_get_params(name)` 彻底删除了退回到 `"default"` 或取 `next(iter(self.param_map.values()))` 的兜底代码；当参数为 Mapping 时，若物体名不存在，严格抛出 `KeyError(f"Missing true parameters for body '{name}' in TrueParamArm")`。

### 2.3 `worker.py`
- **删除死代码**：彻底删除了已无任何调用方的 `_extract_true_phi_from_evaluator`。
- **返回占位实例**：`build_arm_for_eval(arm=4, ...)` 返回 `TrueParamArm(true_params=None)`，确保任何绕过逐 episode 注入的直接预测路径均立刻抛错。

### 2.4 测试套件与 Fixture
- **`tests/test_e1_eval_runner.py`** 增补 4 项专门回归单测：
  1. `test_arm4_worker_placeholder_cannot_predict_directly`：验证直接对 worker 返回的 ④ 调用 `evaluate_episode` 抛出 `RuntimeError`。
  2. `test_arm4_param_map_missing_body_raises_key_error`：验证 φ* map 缺少物体名时抛出 `KeyError`。
  3. `test_extract_true_phi_non_mapping_body_raises_type_error`：验证 `b_info` 为非 Mapping 时抛出 `TypeError`。
  4. `test_is_arm_4_strict_instance_and_subclass_only`：验证 `arm4_x` 或 `diagnostic_only=True` 绝不被误判为 Arm ④。
  5. `test_arm4_missing_all_physical_params_raises_key_error`：验证评测视图缺少物理参数且无 fallback 时抛出 `KeyError`。
- **Fixture 修复**：在 `tests/test_e1_arms_net.py` 和 `tests/test_e1_analysis.py` 仅含 shape/dimensions 的 fixture 中填齐五项真实物理参数。

---

## 3. 隔离副本坏对照验证（打印 `__file__` 且变红）

在独立的隔离目录（复制源码与测试，打印 `__file__`）分别注入变异逻辑，确认对应的保护测试变红：

### 坏对照 (a)：恢复「按物体名取首文件缓存」
- **命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_a/src python3 -m pytest -s /tmp/bad_control_a/tests/test_e1_eval_runner.py -k "test_arm4_eval_runner_uses_per_episode_true_phi"
  ```
- **输出**：
  ```text
  BAD_CONTROL_A running from file: /tmp/bad_control_a/src/ainerzero/v9/experiments/e1/eval_runner.py
  FAILED ../../../../tmp/bad_control_a/tests/test_e1_eval_runner.py::test_arm4_eval_runner_uses_per_episode_true_phi - AssertionError: Not equal to tolerance rtol=1e-09, atol=1e-09 (Max absolute difference: 0.06489)
  ```
- **结论**：测试明确变红。

### 坏对照 (b)：恢复 `.get("restitution", 0.3)` 默认值，且输入缺 restitution
- **命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_b/src python3 -m pytest -s /tmp/bad_control_b/tests/test_e1_eval_runner.py -k "test_arm4_missing_parameter_raises_key_error"
  ```
- **输出**：
  ```text
  BAD_CONTROL_B running from file: /tmp/bad_control_b/src/ainerzero/v9/experiments/e1/eval_runner.py
  FAILED ../../../../tmp/bad_control_b/tests/test_e1_eval_runner.py::test_arm4_missing_parameter_raises_key_error - Failed: DID NOT RAISE <class 'KeyError'>
  ```
- **结论**：测试明确变红。

### 坏对照 (c)：恢复 `fallback_map`，让 fixture 缺少物理参数
- **命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_c/src python3 -m pytest -s /tmp/bad_control_c/tests/test_e1_eval_runner.py -k "test_arm4_missing_all_physical_params_raises_key_error"
  ```
- **输出**：
  ```text
  BAD_CONTROL_C running from file: /tmp/bad_control_c/src/ainerzero/v9/experiments/e1/eval_runner.py
  FAILED ../../../../tmp/bad_control_c/tests/test_e1_eval_runner.py::test_arm4_missing_all_physical_params_raises_key_error - Failed: DID NOT RAISE <class 'KeyError'>
  ```
- **结论**：测试明确变红，证明移除 `fallback_map` 后不再掩盖 fixture 缺失物理参数的缺陷。

### 坏对照 (d)：恢复按名字匹配 "arm4"，构造名为 `arm4_x` 的非 ④ 臂
- **命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_d/src python3 -m pytest -s /tmp/bad_control_d/tests/test_e1_eval_runner.py -k "test_is_arm_4_strict_instance_and_subclass_only"
  ```
- **输出**：
  ```text
  BAD_CONTROL_D running from file: /tmp/bad_control_d/src/ainerzero/v9/experiments/e1/eval_runner.py
  FAILED ../../../../tmp/bad_control_d/tests/test_e1_eval_runner.py::test_is_arm_4_strict_instance_and_subclass_only - AssertionError: assert True is False (+ where True = is_arm_4(PriorArm(), arm_name='arm4'))
  ```
- **结论**：测试明确变红，证明启发式匹配被彻底排除。

### 坏对照 (e)：恢复 `"default"` 兜底，让 φ* map 缺少某个物体
- **命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_e/src python3 -m pytest -s /tmp/bad_control_e/tests/test_e1_eval_runner.py -k "test_arm4_param_map_missing_body_raises_key_error"
  ```
- **输出**：
  ```text
  BAD_CONTROL_E running from file: /tmp/bad_control_e/src/ainerzero/v9/experiments/e1/arms_nonnet.py
  FAILED ../../../../tmp/bad_control_e/tests/test_e1_eval_runner.py::test_arm4_param_map_missing_body_raises_key_error - Failed: DID NOT RAISE <class 'KeyError'>
  ```
- **结论**：测试明确变红，证明物体级参数缺失时绝不借用其他物体的参数。

---

## 4. 全量回归测试

运行全量 E1 测试套件：
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py
```

**测试结果**：
```text
============================= test session starts ==============================
platform darwin -- Python 3.12.4, pytest-7.4.4, pluggy-1.6.0
default pure-CPU entry: native_mlx tests not collected/covered (see tests/conftest.py)
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
plugins: asyncio-0.23.5, anyio-4.15.1
asyncio: mode=Mode.STRICT
collected 157 items

tests/test_e1_analysis.py ...........                                    [  7%]
tests/test_e1_arms_net.py ..................                             [ 18%]
tests/test_e1_arms_nonnet.py ...........                                 [ 25%]
tests/test_e1_data_runner.py ..........                                  [ 31%]
tests/test_e1_entry.py ...........                                       [ 38%]
tests/test_e1_eval_runner.py ...............                             [ 48%]
tests/test_e1_export.py ..........                                       [ 54%]
tests/test_e1_identity.py .......                                        [ 59%]
tests/test_e1_metrics.py ................                                [ 69%]
tests/test_e1_prereg.py ..................                               [ 80%]
tests/test_e1_prior.py .............                                     [ 89%]
tests/test_e1_train_runner.py .........                                  [ 94%]
tests/test_e1_wiring.py ........                                         [100%]

============================= 157 passed in 17.54s =============================
```
157 项单测全部通过（0 失败，0 告警）。

---

## 5. 文件 SHA256 清单

详见同目录下 `SHA256SUMS.txt` 与改动前副本目录 `before/`。
