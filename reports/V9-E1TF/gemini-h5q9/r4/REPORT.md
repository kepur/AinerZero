# E1 修复（r4）：几何半径全程显式传递与调用栈耦合消除报告（ainerzero.V9.P79）

- **执行者**：gemini-h5q9（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P79`（第 4 轮修复 · r4）
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 79 步（E1 训练目标修复与物理一致性）
- **依据与打回意见响应**：
  - 一级统筹（Claude）r3 验收裁定与 r4 修改要求：
    1. **彻底删除翻调用栈取半径代码**：
       - 删除 `arms_net.py` 中的 `import inspect`、`inspect.currentframe()` 和 `caller_frame.f_locals`；
       - 添加静态源码检查单测，严防 `currentframe`、`f_locals` 与 `import inspect` 再次进入代码库。
    2. **`evaluate_episode` 显式提取真实半径并全程传递**：
       - 从 `active_bodies[name]["bounding_sphere_radius"]` 显式提取浮点半径，缺失立即抛出 `KeyError`；
       - 前缀提取时移除默认值兜底，缺失字段或物体时抛出 `KeyError`；
       - 调用各臂改为显式传递：`arm.predict(observed_prefix, static_env, n_future, radii_by_body=radii_by_body)`。
    3. **七个臂的 `predict` 统一显式接收 `radii_by_body`**：
       - 所有基于先验物理引擎的臂（①③④⑤⑥⑦）在未提供半径或缺失物体时，统一抛出 `KeyError`；
       - 彻底消除 `arms_nonnet` 在 predict / identify 路径上所有 `default_radius` 兜底（包括 `self.radii.get(name, self.default_radius)`）；
       - 构造函数传入的 `radii` 仅供直接调用场景，调用时传入的参数优先，两边都没有直接抛 `KeyError`；
       - ②（PureNetArm）接受 `radii_by_body` 参数但不使用，其输出在不同半径输入下逐位相同。
    4. **⑥ 的辨识器显式接收真实半径**：
       - `make_arm6_identifier()` 移除默认参数 `default_radius`，辨识器闭包签名改为 `(prefix_data, env, radii_by_body)`，并将半径转交 `IdentifyArm.identify`；
       - 训练路径通过 `train_runner` 传递训练窗口提取的真实半径，评测路径由 `IdentifyResidualArm.predict` 把 `radii_by_body` 转交给辨识器；
       - 数组输入路径下未提供有效半径时抛出 `KeyError`。
    5. **集成测试与物理几何一致性验证**：
       - 静止球（r=0.4）与盒子（1.2×1.2×1.0，r≈0.985）经 `evaluate_episode` 评测，①④⑤⑦ 预测的第 1 帧高度与真实静止高度误差严格 < 1e-3（实际误差为 0.0）；
       - ③⑥ 网络权重清零后，预测轨迹与 ① / ⑤ 的预测结果最大绝对差异 < 1e-9（实际为 0.0），证明先验部分几何完全统一；
       - 各执行路径缺失半径均阻断并抛出 `KeyError`；
       - ② 的输出在半径为 0.1 与 0.9 时逐位完全相同。
    6. **坏对照变红验证（隔离环境）**：
       - 在独立副本中执行 3 项突变，验证新测试严格变红，并打印 `__file__` 证明加载自隔离副本。
- **文件改动范围**：
  - `src/ainerzero/v9/experiments/e1/eval_runner.py`
  - `src/ainerzero/v9/experiments/e1/arms_nonnet.py`
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `src/ainerzero/v9/experiments/e1/train_runner.py`
  - `tests/test_e1_arms_net.py`
  - 交付目录：`reports/V9-E1TF/gemini-h5q9/r4/`（含 `before/` 原始备份）

---

## 1. 缺陷根因与 r4 架构重构

### 1.1 旧缺陷剖析
1. **隐式调用栈耦合**：r3 在 `PriorResidualArm.predict` 与 `IdentifyResidualArm.predict` 中引入了 `inspect.currentframe().f_back.f_locals["student_ep"]`，试图从调用帧变量中窃取半径。该方式在调用栈层级变化、重构函数或外部直接调用时会导致静默获取失败。
2. **评测侧默认半径 0.5 导致的系统性几何偏置**：
   - 旧代码在评测时，`worker.build_arm_for_eval` 未传半径，`eval_runner.evaluate_episode` 调用 `arm.predict` 亦未传半径；
   - 导致 `arms_nonnet` 中所有物体均按默认半径 0.5 计算，静止在 z=0 地面的 r=0.4 球在第 1 帧就被强行跳变到 z=0.5，盒子（r≈0.985）陷进地面 0.49 m；
   - ⑥ 的辨识器写死 0.5，导致其辨识与残差目标几何失配，系统性偏置了 H-E1 对照结论。

### 1.2 r4 显式传递解决方案
1. **显式协议**：
   - `evaluate_episode` 从 `student_ep["active_bodies"]` 提取真实包围球半径 `radii_by_body`，在调用 `arm.predict(observed_prefix, static_env, n_future, radii_by_body=radii_by_body)` 时全程下传。
2. **防御性阻断**：
   - 移除了 `arms_nonnet` 中所有 `self.radii.get(name, self.default_radius)` 兜底。
   - 所有用先验的臂在未提供半径字典或缺失特定物体时，统一抛出 `KeyError`。
3. **辨识器显式传参**：
   - `make_arm6_identifier()` 移除默认参数，辨识器闭包在训练时接收来自 sequence 的真实半径，在评测时由 `IdentifyResidualArm.predict` 接收 `radii_by_body`。

---

## 2. 核心代码改动对比

### 2.1 消除翻栈代码（`arms_net.py`）
- 彻底移除了 `import inspect`，并在两处预测入口中删除了 `inspect.currentframe()` 与 `f_locals` 探测逻辑。
- 缺失半径时直接抛出 `KeyError("radii_by_body is required for ...predict; none provided")`。
- 调用 `self.identifier_fn` 时显式传入 `radii_by_body=body_radii`。

### 2.2 `eval_runner.py` 显式提取与严格校验
- 在 `evaluate_episode` 中：
  ```python
  radii_by_body: dict[str, float] = {}
  for name in body_names:
      b_info = active_bodies[name]
      if not isinstance(b_info, dict) or "bounding_sphere_radius" not in b_info or b_info["bounding_sphere_radius"] is None:
          raise KeyError(f"Missing bounding_sphere_radius for body '{name}'")
      radii_by_body[name] = float(b_info["bounding_sphere_radius"])
  ```
- 前缀提取过程中，严禁对缺失字段（`position`, `linear_velocity`, `orientation`, `angular_velocity`）做默认值兜底，发现缺失直接抛出 `KeyError`。

### 2.3 `arms_nonnet.py` 消除所有默认兜底
- `PriorArm`、`TrueParamArm`、`IdentifyArm`、`SymbolicResidualArm` 的 `predict` 与 `identify` 均改为检查 `effective_radii`，缺失任何物体的半径均抛出 `KeyError`。

### 2.4 `train_runner.py` 辨识器重构
- `make_arm6_identifier()` 去掉 `default_radius`，签名更新为 `(prefix_data, env, radii_by_body=None)`；
- 数组输入路径下未提供有效半径时抛出 `KeyError`；
- `build_training_windows` 在执行第 ⑥ 臂辨识时，传入训练序列的真实半径。

---

## 3. 测试与验证结果

### 3.1 r4 新增测试用例（`tests/test_e1_arms_net.py`）
1. `test_arms_net_no_inspect_or_frame_inspection`：
   - 静态检查 `arms_net.py` 源码，断言不包含 `currentframe`、`f_locals` 及 `import inspect`。测试 **PASSED**。
2. `test_r4_resting_ball_and_box_integration_evaluate_episode`：
   - 经 `evaluate_episode` 走包含 r=0.4 静止球和 1.2×1.2×1.0 静止盒子的完整 episode。
   - ①④⑤⑦ 预测第 1 帧高度与真实静止高度误差严格小于 1e-3（实际误差为 0.0）。
   - ③⑥ 权重清零后，预测位置与 ① / ⑤ 的预测结果最大绝对差异严格小于 1e-9（实际为 0.0）。测试 **PASSED**。
3. `test_r4_missing_radii_loud_exceptions_across_all_paths`：
   - 验证缺少 `bounding_sphere_radius` 时 `evaluate_episode` 抛出 `KeyError`；
   - 验证缺少半径时，①③④⑤⑥⑦ 的 `predict` 统一抛出 `KeyError`；
   - 验证 ⑥ 的辨识器未提供半径时抛出 `KeyError`。测试 **PASSED**。
4. `test_r4_arm2_pure_net_invariant_to_radii`：
   - 验证 PureNetArm 分别接收 `radii_by_body={"body_0": 0.1}` 和 `radii_by_body={"body_0": 0.9}` 时，预测结果逐位相同。测试 **PASSED**。

### 3.2 E1 全量测试回归
- 命令：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py`
- 结果：**130 passed in 13.14s**（0 failed，全绿）。

---

## 4. 坏对照变红验证（Bad Control Mutations）

在完全隔离的 `/tmp/e1_tf_r4_mutants/` 目录下复制 `src` 与 `tests`，并在每个突变前打印 `__file__` 证实加载自隔离副本，执行定向测试：

1. **坏对照 (a) - 恢复 `PriorArm` 的 `default_radius` 兜底（默认0.5）**：
   - 突变目标：`arms_nonnet.py`
   - 运行结果：`tests/test_e1_arms_net.py::test_r4_missing_radii_loud_exceptions_across_all_paths` **FAILED** (Exit code 1)
   - 变红证据：`Failed: DID NOT RAISE <class 'KeyError'>`。
2. **坏对照 (b) - 让 `evaluate_episode` 不再传 `radii_by_body`**：
   - 突变目标：`eval_runner.py`
   - 运行结果：`tests/test_e1_arms_net.py::test_r4_resting_ball_and_box_integration_evaluate_episode` **FAILED** (Exit code 1)
   - 变红证据：`KeyError: 'radii_by_body is required for PriorArm.predict; none provided'`。
3. **坏对照 (c) - 让 `make_arm6_identifier` 恢复写死 0.5**：
   - 突变目标：`train_runner.py`
   - 运行结果：`tests/test_e1_arms_net.py::test_r4_missing_radii_loud_exceptions_across_all_paths` **FAILED** (Exit code 1)
   - 变红证据：`Failed: DID NOT RAISE <class 'KeyError'>`。

---

## 5. 交付产物与完整性校验

- 改动前源码备份：`reports/V9-E1TF/gemini-h5q9/r4/before/`
- 指标数据文件：`reports/V9-E1TF/gemini-h5q9/r4/data.json`
- 报告文档：`reports/V9-E1TF/gemini-h5q9/r4/REPORT.md`
- 完整性校验和：`reports/V9-E1TF/gemini-h5q9/r4/SHA256SUMS.txt`
