# E1 诊断臂 ④ 按 episode 取真 φ* 修复报告

- **任务编号**：`ainerzero.V9.P81`
- **执行代理**：`gemini-w9k2`（二级执行层）
- **日期**：2026-10-29
- **工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`

---

## 1. 任务背景与核心缺陷

在一级验收 P79 时，在 `src/ainerzero/v9/experiments/e1/worker.py` 原有的 `_extract_true_phi_from_evaluator` 中发现缺陷：
1. 原实现遍历评测目录下所有 JSON，以物体名（如 `RollingActor`, `BoxBottom`）为键，使用 `if b_name not in param_map`，使得同名物体在所有 episode 上都锁定使用第一个 episode 的真参数，而 smoke 实际数据中同名物体的摩擦、质量、恢复系数在各 episode 中各不相同。
2. 五项物理参数均使用了静默默认值（如 `.get("friction", 0.5)`）。
3. 使用 `except Exception: continue` 吞掉了解析异常。
4. 一个物体都没提取到时使用 `{"default": ...}` 兜底。

此外，按一级 14:3x 追加要求清理：`worker.build_generate_data_argv` 指向不存在的旧脚本 `animeworld/e0/dataset_generator.py`，全仓除测试外无调用方，真正数据生成走 `data_runner`，需彻底删除并清理单测。

---

## 2. 修改范围与实现细节

改动严格限制在指定文件范围内：
- `src/ainerzero/v9/experiments/e1/worker.py`
- `src/ainerzero/v9/experiments/e1/eval_runner.py`
- `tests/test_e1_eval_runner.py`
- `tests/test_e1_wiring.py`
- `tests/test_e1_entry.py`
- `reports/V9-E1T4/gemini-w9k2/`

### 2.1 `eval_runner.py`
1. **真参数逐 episode 提取函数** `extract_true_phi_from_episode(truth_ep, fallback_map=None)`：
   - 严格要求五项参数（`friction`, `restitution`, `mass`, `linear_damping`, `angular_damping`），直接通过 `b_info[req_field]` 获取；
   - 缺失任何一项直接抛出 `KeyError`，并在异常消息中写明物体名和 `sequence_id`；
   - 过滤跳过静态物体与非活跃物体（`is_active` 为假）；
   - 无任何 `try ... except ... continue` 吞错逻辑，无 `"default"` 兜底。
2. **Arm ④ 判定与循环注入点**：
   - 实现 `is_arm_4(arm, arm_name)` 准确定位 Arm ④；
   - 在 `evaluate_cell`（dev 评测循环）与 `evaluate_final_once`（final 评测循环）逐 episode 调用 `evaluate_episode` 处，对 Arm ④ 按 episode 构造注入 `TrueParamArm(true_params=phi_map, radii=...)`，确保真参数仅从评测端进入，绝不经过学生视图与学生 `predict` 输入；
   - 其余所有臂（①②③⑤⑥⑦）行为保持完全不变。

### 2.2 `worker.py`
1. **删除废弃函数**：彻底删除了 `build_generate_data_argv`。
2. **改写 `_extract_true_phi_from_evaluator(evaluator_dir)`**：
   - 返回 `dict[str, dict[str, prior.PhysicalParameters]]`，按 `sequence_id` 字典映射，彻底废弃按物体名取首文件的缓存；
   - 委托 `eval_runner.extract_true_phi_from_episode` 进行参数提取，遇到缺失或损坏即刻抛出 `KeyError`。
3. **`build_arm_for_eval(arm=4, ...)`**：
   - 构造并返回带有 `arm_id=4` 的 `TrueParamArm` 实例，具体真参数在评测循环中按 episode 从评测视图动态注入。

### 2.3 测试套件更新与新增
1. **`tests/test_e1_eval_runner.py`**：
   - `test_arm4_eval_runner_uses_per_episode_true_phi`：构造两个同名物体（`ball`）但不同恢复系数（0.2 与 0.8）的 episode，经 `evaluate_cell` 和 `evaluate_final_once` 运行 Arm ④。断言每个 episode 的预测与自身真参数 rollout 一致到 1e-9，并且与另一 episode 的参数预测最大差值显著 > 0.05。
   - `test_arm4_missing_parameter_raises_key_error`：当评测视图缺少 `friction` 时，断言抛出 `KeyError`，且消息包含物体名和 `sequence_id`。
   - `test_arm4_student_view_has_no_hidden_parameters`：断言学生视图通过 `assert_no_leakage` 严格检查，绝不泄露任何隐藏参数。
2. **`tests/test_e1_entry.py`**：
   - 将 `test_generate_data_argv_and_refusal` 中对已删除 `build_generate_data_argv` 的测试移除，保留预审拒绝逻辑 `test_generate_data_refusal`。
   - 在测试夹具 `_make_args` 中补充生成器身份文件写入以适配新版数据门禁。
3. **`tests/test_e1_wiring.py`**：
   - 在测试夹具 `_make_args` 中补充生成器身份文件写入以适配新版数据门禁。

---

## 3. 隔离副本坏对照验证（打印 `__file__` 且变红）

在独立的隔离目录中（复制源码与测试，打印 `__file__`）分别复现并验证变红：

### 坏对照 (a)：恢复「按物体名取第一个文件」
- **运行命令**：
  ```bash
  cd /tmp/bad_control_a && PYTHONPATH=/tmp/bad_control_a/src python3 -m pytest -s /tmp/bad_control_a/tests/test_e1_eval_runner.py -k "test_arm4_eval_runner_uses_per_episode_true_phi"
  ```
- **输出证据**：
  ```text
  ../../../tmp/bad_control_a/tests/test_e1_eval_runner.py BAD_CONTROL_A running from file: /tmp/bad_control_a/src/ainerzero/v9/experiments/e1/eval_runner.py
  F
  =================================== FAILURES ===================================
  _______________ test_arm4_eval_runner_uses_per_episode_true_phi ________________
  >       np.testing.assert_allclose(ep1_actual, expected_pred1, atol=1e-9, rtol=1e-9)
  E       AssertionError: 
  E       Not equal to tolerance rtol=1e-09, atol=1e-09
  E       Mismatched elements: 10 / 75 (13.3%)
  E       Max absolute difference among violations: 0.06489315
  ======================= 1 failed, 10 deselected in 0.39s =======================
  ```
- **结论**：测试明确变红，证明同名物体按首文件缓存确实会导致后续 episode 预测失真。

### 坏对照 (b)：恢复 `.get("restitution", 0.3)` 默认值，让输入缺 restitution
- **运行命令**：
  ```bash
  cd /tmp/bad_control_b && PYTHONPATH=/tmp/bad_control_b/src python3 -m pytest -s /tmp/bad_control_b/tests/test_e1_eval_runner.py -k "test_arm4_missing_parameter_raises_key_error"
  ```
- **输出证据**：
  ```text
  ../../../tmp/bad_control_b/tests/test_e1_eval_runner.py BAD_CONTROL_B running from file: /tmp/bad_control_b/src/ainerzero/v9/experiments/e1/eval_runner.py
  F
  =================================== FAILURES ===================================
  _________________ test_arm4_missing_parameter_raises_key_error _________________
  >       with pytest.raises(KeyError) as exc_info:
  E       Failed: DID NOT RAISE <class 'KeyError'>
  ======================= 1 failed, 10 deselected in 0.36s =======================
  ```
- **结论**：测试明确变红，证明静默默认值会掩盖输入缺失错误。

---

## 4. 全量回归测试结果

在主工作目录运行全量测试：
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py
```

**测试结果输出**：
```text
============================= test session starts ==============================
platform darwin -- Python 3.12.4, pytest-7.4.4, pluggy-1.6.0
default pure-CPU entry: native_mlx tests not collected/covered (see tests/conftest.py)
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
plugins: asyncio-0.23.5, anyio-4.15.1
asyncio: mode=Mode.STRICT
collected 150 items

tests/test_e1_analysis.py ...........                                    [  7%]
tests/test_e1_arms_net.py ..................                             [ 19%]
tests/test_e1_arms_nonnet.py ...........                                 [ 26%]
tests/test_e1_data_runner.py .......                                     [ 31%]
tests/test_e1_entry.py ...........                                       [ 38%]
tests/test_e1_eval_runner.py ...........                                 [ 46%]
tests/test_e1_export.py ..........                                       [ 52%]
tests/test_e1_identity.py .......                                        [ 57%]
tests/test_e1_metrics.py ................                                [ 68%]
tests/test_e1_prereg.py ..................                               [ 80%]
tests/test_e1_prior.py .............                                     [ 88%]
tests/test_e1_train_runner.py .........                                  [ 94%]
tests/test_e1_wiring.py ........                                         [100%]

============================= 150 passed in 14.02s =============================
```
全部 150 项测试 100% 通过。

---

## 5. 文件 SHA256 清单

详见同目录下 `SHA256SUMS.txt` 与改动前副本目录 `before/`。
