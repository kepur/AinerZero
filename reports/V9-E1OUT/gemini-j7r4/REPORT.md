# ainerzero.V9.P91 执行报告

- **角色**：executor（二级 执行层）
- **负责人**：gemini-j7r4
- **时间**：2026-10-30（+03）
- **任务状态**：reported
- **实验状态**：completed（纯 CPU，无 GPU，无 MLX 训练）
- **任务依据**：AinerRelay 任务 `ainerzero.V9.P91`；参数 v2
- **输出目录**：`reports/V9-E1OUT/gemini-j7r4/`

---

## 1. 任务背景与核心修改

依据一级架构裁定修订 r3（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md`）：
- **历史缺陷**：`arms_net.py` 中三个网络臂（PureNetArm、PriorResidualArm、IdentifyResidualArm）在 `predict()` 中分配了 `(n_future + 1, 13)` 数组并在第 0 行写入初始状态；而 `eval_runner.evaluate_episode` 对 Mapping 输出悄悄做 `arr[:n_future]` 截取，导致初始状态被当成第一个预测帧，使网络臂预测整体错后一帧（P90 中 ②③⑥ 的 e_1 均出现假性 5 cm 误差）。
- **修订裁定**：
  1. 三个网络臂 `predict()` 统一只返回 `n_future` 行未来帧（第 j 行对应第 PREFIX_FRAMES + j 帧，不含初始状态）。返回结构保持与输入对应的 dict/ndarray 形式，行数严格为 `n_future`。
  2. `evaluate_episode` 彻底取消 `[:n_future]` 截取修补；对 Mapping 和 ArmPrediction 两条分支均严格断言 position 和 velocity 的行数恰好等于 `n_future`，否则抛出包含臂名、物体名、实际行数与期望行数的 `ValueError`。
  3. 全仓检索所有 `.predict(` 调用方，按新约定修改索引与切片（不再在调用方使用 `[1:]` 或 `[:n]` 规避）。
  4. 编写运动中物体（自由飞行球 + 地面滑动盒，50 帧）严格集成测试；保留 P79 静止测试。
  5. 隔离环境验证两项坏对照（Bad Controls）均红。
  6. E1 全量测试 100% 通过。

---

## 2. 修改文件清单

| 修改文件 | 修改内容摘要 |
|---|---|
| `src/ainerzero/v9/experiments/e1/arms_net.py` | PureNetArm、PriorResidualArm、IdentifyResidualArm 分配 `(n_future, 13)` 数组，移除第 0 行初始状态写入，循环迭代 `range(n_future)`，输出纯未来 `n_future` 行 |
| `src/ainerzero/v9/experiments/e1/eval_runner.py` | `evaluate_episode` 中移除 `pos_arr[:n_future]` 截取；针对 Mapping 与 ArmPrediction 严格断言行数 `== n_future`，否则抛出详细 `ValueError` |
| `tests/test_e1_arms_net.py` | 修正 10 步单测索引（`[10]` -> `[9]`）、1 步单测索引（`[1]` -> `[0]`）、去除 `[1:, ...]` 切片修补 |
| `tests/test_e1_p87_geometry.py` | 移除 `res3["box"][1:, 0:3]` 与 `res6["box"][1:, 0:3]` 中的 `1:` 切片修补，改用 `[:, 0:3]` |
| `tests/test_e1_eval_runner.py` | 增加 `synthesize_motion_sequence_ball_and_sliding_box` 与 `test_motion_ball_and_box_seven_arms_predictions_and_assertions` |
| `reports/V9-E1OUT/gemini-j7r4/` | 产出 `before/` 备份、`evidence/` 坏对照日志、`metrics.json`、`SHA256SUMS.txt`、`REPORT.md` |

---

## 3. 返回结构选定说明

- **选定方案**：网络臂 `predict()` 保持返回 `dict[str, np.ndarray]`（单物体 array 输入时返回 `np.ndarray`），形状为 `(n_future, 13)`。
- **选择理由**：
  1. 避免在 `arms_net` 与 `arms_nonnet` 之间引入额外的类循环依赖或紧耦合；
  2. `eval_runner.evaluate_episode` 本身已原生支持 Mapping 和 ArmPrediction 两种容器；
  3. 完全兼容既有保存加载测试（`np.array_equal`）、NaN 隔离测试及场景级多物体输出接口。

---

## 4. 运动中 Episode 测试验证结果

测试函数：`test_motion_ball_and_box_seven_arms_predictions_and_assertions`
场景设置：50 帧，无 Blender，由本仓 prior 物理引擎生成，包含在空中自由飞行的球（半径 0.2 m，初始速度 [1.5, 0.0, 1.0]）以及在地面摩擦滑动的盒（半尺寸 [0.3, 0.3, 0.2]，初始速度 [2.5, 0.0, 0.0]）。

1. **① 与 ④ 的 e_1 < 1e-3 m**：
   - Arm 1 (PriorArm) e_1: `0.000183 m`（0.18 mm < 1 mm，通过）
   - Arm 4 (TrueParamArm) e_1: `2.57e-10 m`（通过）
2. **③ 权重清零与 ① 逐位相同**：
   - ball 最大差值：`0.0`
   - box 最大差值：`0.0`
   - `np.array_equal` 逐位一致断言：通过
3. **⑥ 权重清零与 ⑤ 逐位相同**：
   - ball 最大差值：`0.0`
   - box 最大差值：`0.0`
   - `np.array_equal` 逐位一致断言：通过
4. **七个臂预测行数**：
   - Arm 1 ~ Arm 7 对 ball 与 box 的 `pred_positions` 行数严格为 30（等于 `n_future`）。
5. **异常断言**：
   - 构造返回 31 行（n_future+1）的 Mapping 伪臂：抛出 `ValueError: Arm 'FakeMappingArmExtraRow' body 'ball' predicted 31 trajectory rows, expected exactly n_future=30`
   - 构造返回 31 行的 ArmPrediction 伪臂：抛出 `ValueError: Arm 'FakeArmPredictionExtraRow' body 'ball' predicted 31 position rows, expected exactly n_future=30`
6. **P79 静止测试保留**：
   - `test_stationary_box_geometry_routing_and_zero_weight_equivalence` 保持完整并通过。

---

## 5. 坏对照（Bad Controls）在隔离副本中验证

在隔离环境（`/tmp/e1_bad_controls_gemini_j7r4/`，打印 `__file__` 证明独立加载）执行：

- **坏对照 (a)：恢复网络臂 n_future+1 行输出及 eval_runner `[:n_future]` 截取**
  - 执行命令输出见 `evidence/bad_control_a.log`
  - 结果：**测试变红（FAIL）**
  - 报错：`AssertionError: Arm 3 zero-weight pred for ball is not bitwise identical to Arm 1!`
  - 原因：运动物体在错后一帧后，第 0 步错取前缀初始帧 `[0.225, 0, 3.038]`，与 Arm 1 真正第一步 `[0.24997, 0, 3.029]` 不一致，被测试立即捕获。
- **坏对照 (b)：只恢复 evaluate_episode 截取、去掉行数断言，让伪臂返回 n_future+1 行**
  - 执行命令输出见 `evidence/bad_control_b.log`
  - 结果：**测试变红（FAIL）**
  - 报错：`Failed: DID NOT RAISE <class 'ValueError'>`
  - 原因：由于缺少严格行数断言，多出的一行被截取悄悄吞没，无法发现上游臂的输出契约违反。

---

## 6. 全量 E1 测试集运行结果

执行命令：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py`
- 测试模块：14 个测试文件
  - `test_e1_analysis.py` (13 passed)
  - `test_e1_arms_net.py` (18 passed)
  - `test_e1_arms_nonnet.py` (14 passed)
  - `test_e1_data_runner.py` (10 passed)
  - `test_e1_entry.py` (12 passed)
  - `test_e1_eval_runner.py` (19 passed, 含新增运动集成测试)
  - `test_e1_export.py` (17 passed)
  - `test_e1_identity.py` (7 passed)
  - `test_e1_metrics.py` (20 passed)
  - `test_e1_p87_geometry.py` (7 passed)
  - `test_e1_prereg.py` (18 passed)
  - `test_e1_prior.py` (13 passed)
  - `test_e1_prior_box.py` (9 passed)
  - `test_e1_train_runner.py` (9 passed)
  - `test_e1_wiring.py` (8 passed)
- **总通过数**：**194 passed in 17.87s**（通过率 100%，0 failed）。

---

## 7. 交付 SHA256SUMS

完整哈希见 `reports/V9-E1OUT/gemini-j7r4/SHA256SUMS.txt`。
所有修改均在任务授权文件范围内，未改动任何训练目标与先验定义，未 git commit/push，无外部网络请求。
