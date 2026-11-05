# E1 修复（r5）：消除静默降级、辨识器半径串号修复与半径敏感行为测试报告（ainerzero.V9.P79）

- **执行者**：gemini-p7k9（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P79`（第 5 轮修复 · r5）
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 79 步（E1 训练目标修复与物理一致性）
- **依据与打回意见响应**：
  - 一级统筹（Claude）r4 验收裁定与 r5 修改要求：
    1. **删除四处 `except TypeError` 静默降级**：
       - `eval_runner.evaluate_episode`：移除降级重试逻辑，直接显式传递 `radii_by_body`；
       - `train_runner.build_training_windows`：⑥ 辨识移除异常降级，直接显式调用；
       - `arms_net.py` 两处（predict 内部与 `training_target` 构造路径）：移除降级，直接调用；
       - 新增源码静态断言单测：确保 `eval_runner.py`、`train_runner.py`、`arms_net.py` 中不出现 `except TypeError`。
    2. **纠正 `body_radii` 字典构造，杜绝 `body_0` 串号**：
       - 彻底删除 `{b_name: r, "body_0": r}; body_radii.update(radii_by_body)` 这一在物体命名为 `body_0` 时引起键覆盖串号的写法；
       - 单体数组辨识路径严格统一为 `{"body_0": float(radii_by_body[b_name])}`，不再额外调用 `update`。
    3. **探针测试（Spy Identifier）覆盖训练与评测全链路**：
       - 训练侧：`build_training_windows` 处理含球（r=0.4）与盒子（r≈0.985）的双物体序列，探针断言各物体辨识时准确收到对应半径；
       - 评测侧：经 `evaluate_episode` 调用 `IdentifyResidualArm.predict`，探针断言同样成立。
    4. **对半径敏感的物理行为测试（反弹球）**：
       - 利用 `prior` 积分器生成带真实触地反弹的轨迹（半径 0.4，restitution 0.6）；
       - 严谨验证前提条件：同一前缀在 r=0.4 与 r=0.5 下辨识出的 \(\hat{\phi}\) 显著不同（restitution 相差 0.1608）；
       - 物理行为断言：⑥ 网络权重清零后的多步轨迹预测（含接触阶段）与 ⑤（`IdentifyArm`）严格一致到 1e-9（实际最大差 0.0）。
    5. **彻底清理 `arms_nonnet` 中未使用的 `default_radius` 参数**：
       - 删除 `extract_prefix_records`、`PriorArm`、`TrueParamArm`、`IdentifyArm`、`SymbolicResidualArm` 中的 `default_radius` 构造与函数形参，避免后续维护产生误用。
    6. **隔离副本中的三项坏对照变红验证**：
       - 变异 (i)（数组路径写死 0.5）、变异 (ii)（训练侧写死 0.5）、变异 (iii)（predict 侧写死 0.5）均在隔离目录下执行并由新增测试精准抓红。
- **文件改动范围**：
  - `src/ainerzero/v9/experiments/e1/eval_runner.py`
  - `src/ainerzero/v9/experiments/e1/train_runner.py`
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `src/ainerzero/v9/experiments/e1/arms_nonnet.py`
  - `tests/test_e1_arms_net.py`
  - `tests/test_e1_eval_runner.py`
  - 产出目录：`reports/V9-E1TF/gemini-p7k9/r5/`（含 `before/` 备份）

---

## 1. 缺陷根因与 r5 针对性重构

### 1.1 r4 残留缺陷剖析
1. **静默类型降级隐患**：r4 为避免测试破坏，在四处位置添加了 `except TypeError`。这不仅违背了全臂显式接受半径的接口契约，更会将辨识器内部真实的类型错误误判为参数不匹配，退化为不传半径重新计算。
2. **字典更新覆盖导致别名串号**：`body_radii = {b_name: r, "body_0": r}; body_radii.update(radii_by_body)` 在物体列表包含 `body_0` 且有多物体时，`update` 会用其他物体的真实半径覆盖 `body_0` 的值，造成单体数组辨识时半径错配。
3. **测试对辨识半径不敏感**：r4 集成测试使用的是纯地面静止物体，静态支撑在接触判定通过后其辨识结果对几何微小变动不敏感，导致写死 0.5 的突变无法被原有行为测试抓到。

### 1.2 r5 修复实现
1. **彻底移除所有类型降级**：
   - 四处全部改为直接调用 `self.identifier_fn(prefix_data, env, radii_by_body=body_radii)`；
   - 在 `tests/test_e1_arms_net.py` 中添加 `test_r5_no_except_typeerror_in_eval_train_arms`，静态扫描代码文本。
2. **重写单体辨识的半径传参**：
   - 训练侧与网络预测侧统一改为 `body_radii = {"body_0": float(effective_radii[b_name])}`。
3. **新增探针与反弹球物理行为双重防线**：
   - 探针断言精确捕获每一个物体进入辨识器时的具体半径数值；
   - 反弹球物理测试利用滑移斜向碰撞激发恢复系数与摩擦力敏感性，并在未来步中包含二次反弹碰撞，使得辨识偏差被后续物理积分剧烈放大，彻底阻断任何写死 0.5 的企图。

---

## 2. 核心代码变动精要

### 2.1 消除 `except TypeError` 与规范 `body_radii`
```python
# train_runner.py build_training_windows:
prefix_data = states_by_body[b_name][:K, :6]
if arm_model.identifier_fn is not None:
    body_radii = {"body_0": float(radii_by_body[b_name])}
    phi_hat = arm_model.identifier_fn(
        prefix_data, env, radii_by_body=body_radii
    )
else:
    phi_hat = DEFAULT_BIASED_PRIOR.copy()

# arms_net.py IdentifyResidualArm.predict:
prefix_states = clean_dict[b.name][:, 0:6]
body_radii = {"body_0": float(effective_radii[b.name])}
identified_params = self.identifier_fn(
    prefix_states, env, radii_by_body=body_radii
)
b.params = identified_params.copy()

# eval_runner.py evaluate_episode:
t0 = time.perf_counter()
pred_res = arm.predict(observed_prefix, static_env, n_future, radii_by_body=radii_by_body)
predict_wall_clock_s = time.perf_counter() - t0
```

### 2.2 清理 `arms_nonnet.py` 的废弃参数
移除了 `extract_prefix_records`、`PriorArm`、`TrueParamArm`、`IdentifyArm` 及 `SymbolicResidualArm` 的 `default_radius` 构造参数与属性。

---

## 3. 测试与验证结果

### 3.1 r5 新增与强化测试
1. `test_r5_no_except_typeerror_in_eval_train_arms`：
   - 检查 `eval_runner.py`、`train_runner.py`、`arms_net.py`，源码中均无 `except TypeError`。测试 **PASSED**。
2. `test_r5_spy_identifier_probes_radii_in_train_and_eval`：
   - 探针拦截器在训练（`build_training_windows`）和评测（`evaluate_episode`）中均记录到：
     - 球（x=0.0）：接收半径 `0.400000`；
     - 盒子（x=2.0）：接收半径 `0.984886`。测试 **PASSED**。
3. `test_r5_radius_sensitive_bouncing_ball_behavior`：
   - 反弹球物理前提验证：r=0.4 辨识恢复系数为 0.60008，r=0.5 辨识恢复系数为 0.43929，相差 0.1608 > 0.05，前提严格成立；
   - 臂 ⑥ 网络清零预测与 ⑤ 对比：位置最大差 0.0，速度最大差 0.0，严格满足 < 1e-9。测试 **PASSED**。

### 3.2 E1 全量测试回归
- 命令：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py`
- 结果：**133 passed in 14.33s**（全绿，0 失败）。

---

## 4. 坏对照变红验证（Bad Control Mutations）

在独立副本 `/tmp/e1_tf_r5_mutants/` 目录下复制 `src` 与 `tests`，打印 `__file__` 验证运行在隔离环境：

1. **变异 (i) - `make_arm6_identifier` 数组路径写死 `rad = 0.5`**：
   - 变异文件：`src/ainerzero/v9/experiments/e1/train_runner.py`
   - 运行：`PYTHONPATH=src python3 -m pytest tests/test_e1_arms_net.py -k "test_r5"`
   - 失败测试：`tests/test_e1_arms_net.py::test_r5_radius_sensitive_bouncing_ball_behavior`
   - 变红证据：
     ```text
     AssertionError: make_arm6_identifier restitution 0.4392898280670262 != 0.6000836890695838
     assert 0.16079386100255755 < 1e-06
     ```
   - 状态：**FAILED (Exit code 1)**（精准变红）。

2. **变异 (ii) - 训练侧 `body_radii` 写死 `0.5`**：
   - 变异文件：`src/ainerzero/v9/experiments/e1/train_runner.py`
   - 运行：`PYTHONPATH=src python3 -m pytest tests/test_e1_arms_net.py -k "test_r5"`
   - 失败测试：`tests/test_e1_arms_net.py::test_r5_spy_identifier_probes_radii_in_train_and_eval`
   - 变红证据：
     ```text
     AssertionError: Ball received radius 0.5 != 0.4
     assert 0.09999999999999998 < 1e-06
     ```
   - 状态：**FAILED (Exit code 1)**（精准变红）。

3. **变异 (iii) - `arms_net` 的 ⑥ predict 内传给辨识器的半径改成 `0.5`**：
   - 变异文件：`src/ainerzero/v9/experiments/e1/arms_net.py`
   - 运行：`PYTHONPATH=src python3 -m pytest tests/test_e1_arms_net.py -k "test_r5"`
   - 失败测试：
     - `test_r5_spy_identifier_probes_radii_in_train_and_eval`（评测探针拦截失败）
     - `test_r5_radius_sensitive_bouncing_ball_behavior`（物理行为不一致，多步二次碰撞偏差放大）
   - 变红证据：
     ```text
     AssertionError: Ball in eval received radius 0.5 != 0.4
     AssertionError: Arm 6 zeroed pos diff 0.012319184952907791 >= 1e-9
     ```
   - 状态：**FAILED (Exit code 1)**（双项精准变红）。

---

## 5. 产出目录与完整性

- 变动前原始备份：`reports/V9-E1TF/gemini-p7k9/r5/before/`
- 指标数据文件：`reports/V9-E1TF/gemini-p7k9/r5/data.json`
- 修复总结报告：`reports/V9-E1TF/gemini-p7k9/r5/REPORT.md`
- 校验和清单：`reports/V9-E1TF/gemini-p7k9/r5/SHA256SUMS.txt`
