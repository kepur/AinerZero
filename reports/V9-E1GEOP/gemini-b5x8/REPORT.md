# 任务执行报告：ainerzero.V9.P87 (r2 修复交付)

- **任务编号**：`ainerzero.V9.P87`
- **任务标题**：【L2·gemini·代码】E1 修订 r1-5/6：geometry_by_body 显式传递替换 radii_by_body＋④ 注入静态面真实材质
- **执行 Agent**：`gemini-b5x8`（二级执行层）
- **交付轮次**：r2
- **状态**：`completed`

---

## 1. 接手工作与 r2 针对性修复

### (1) 接手现状说明
在前序批次中（`gemini-r7d5` 与 `gemini-m8d2`）：
- 几何显式传递类型 `BodyGeometry` 与解析函数 `geometry_from_student_body` 已完成；
- E1 源码中 `radii_by_body` 已全部重构替换为 `geometry_by_body`，出现次数为 0；
- 球体回归 fixture 已移至 `tests/fixtures/e1_prior_sphere_regression.npz`（SHA256 以 `5eabd45b812c4248` 开头），完全脱离 `reports/` 依赖；
- 包装类 `SubspaceDimWrapper` 与 `SubspaceWeightWrapper` 已替换为纯字典；
- 尺寸表一致性测试与斜面数值边界测试已加上。

### (2) r2 修复落实（两处修改）
1. **彻底消除真值泄漏判断漏洞**（`src/ainerzero/v9/experiments/e1/eval_runner.py`）：
   - 在 `evaluate_episode` 中，删除了约 401 行的 `or arm_name == "Arm 4 (True Param Bias)"` 分支。
   - 评测中对静态面材质的注入严格受限于 `if is_arm_4(arm):`，仅允许真正的 `TrueParamArm`（`isinstance` / `issubclass`）获取评测端真值材质，杜绝通过传入同名字符串 `arm_name` 导致的意外提权与泄漏。
   - 同步将 `evaluate_series` 处的调用清理为 `if is_arm_4(actual_arm):`。
2. **新增七臂真材质不泄漏不变性测试**（`tests/test_e1_p87_geometry.py::test_truth_static_materials_no_leakage_to_other_arms`）：
   - 构造单一学生端滑动盒体 episode，分别配两份评测端 `truth_ep`（真实地面摩擦力分别为 0.2 与 0.9，其余参数完全相同）。
   - 分别经 `evaluate_episode` 运行：
     - **臂 ①②③⑤⑥⑦**：学生侧臂完全不受评测侧真值材质影响，预测轨迹在两份 truth_ep 下**逐位完全相同**（`np.array_equal` 严格为 True）；
     - **臂 ④ (TrueParamArm)**：注入各自的真实地面摩擦力，预测轨迹产生明显物理位移差异（`not np.array_equal`，最大偏差 > 0.10m）；
     - **防伪装测试**：向 `PriorArm` 显式传递 `arm_name="Arm 4 (True Param Bias)"`，断言仍然不触发材质注入，输出与基线严格逐位相同。

---

## 2. 坏对照验证（变异证明变红）

### (1) r2 专属坏对照：注入条件改成 `if True:`
- **变异逻辑**：强制所有臂均调用 `inject_truth_static_materials`，使真值材质泄漏给非 ④ 臂。
- **验证结果**：
  ```text
  FAILED tests/test_e1_p87_geometry.py::test_truth_static_materials_no_leakage_to_other_arms
  AssertionError: Arm 1 PriorArm predictions differ across truth episodes: truth material leaked!
  ```
- **机理分析**：Arm ① 在 `if True:` 下分别使用地面摩擦 0.2 和 0.9 进行 rollout，导致盒体预测位移产生 0.1006m 的差异，被新增的不变性断言准确捕获。

### (2) 坏对照 (a)：`geometry_from_student_body` 对 BOX 返回 `half_extents=None`
- **变异逻辑**：强制将 BOX 的 `half_extents` 置为 `None`，退化为包围球半径。
- **验证结果**：
  ```text
  AssertionError: Arm 1 PriorArm box z1=0.98486 != 0.5 (diff >= 1e-3)
  ```
- **机理**：中心 z=0.5 的盒子被当成球体处理，严重穿透地面并产生非物理反弹。

### (3) 坏对照 (b)：④ 不注入静态面材质
- **变异逻辑**：跳过 `inject_truth_static_materials`，Arm ④ 直接沿用学生侧默认地面摩擦 0.50。
- **验证结果**：
  ```text
  AssertionError: Arm 4 position error 0.04629093750000557 exceeds 1e-6
  ```
- **机理**：真实地面摩擦 0.2 未注入，计算减速度偏离真实物理。

### (4) 坏对照 (c)：⑥ 的辨识器收到的几何漏掉 `half_extents`
- **变异逻辑**：辨识器探针检验传入 `geometry_by_body` 是否保留半长轴。
- **验证结果**：
  ```text
  AssertionError: assert received_geos[0].half_extents is not None
  ```

---

## 3. 附加要求核验

1. **附加要求一：Fixture 独立性**
   - 文件位置：`tests/fixtures/e1_prior_sphere_regression.npz`
   - SHA-256：`5eabd45b812c424826ce99b9a83e7cf5dc6d9c70ec8b2f6c8430f66e66e08604`（以 `5eabd45b812c4248` 开头，核验一致）。
   - 在不包含 `reports/` 目录的隔离环境中，`test_e1_prior_box.py` 100% 独立通过。
2. **附加要求二：尺寸表与斜面边界**
   - `test_standard_dimensions_table_consistency_with_e0`：遍历 5 种场景类型、P/S 两族、各 3 个种子，验证所有物体 dimensions 严格逐项等于 `STANDARD_OBJECT_DIMENSIONS`。
   - `test_real_e0_integration_ramp_roll`：数值化精确校验 `y_bounds = pos.y ± (length/2)·|cos θ|` 与 `x_bounds = pos.x ± width/2`，误差 < 1e-6。
3. **附加要求三：纯字典子空间**
   - 彻底删除 `SubspaceDimWrapper` 和 `SubspaceWeightWrapper` 包装类；
   - `identified_subspace_dim` 与 `identified_weight` 均为纯原生 `dict`，按物体名索引，缺失键抛 `KeyError`。

---

## 4. 源码无残留验证

执行静态扫描：
```bash
grep -rn "radii_by_body" src/ainerzero/v9/experiments/e1/
# Exit code 1 (0 matches)
```
E1 源码中严格不存在任何旧接口 `radii_by_body`。

---

## 5. 全量测试汇总

- **测试命令**：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -q`
- **测试结果**：**184 passed in 17.13s (0 failed, 0 skipped)**
- **改动文件范围**：
  - `src/ainerzero/v9/experiments/e1/eval_runner.py`（仅移除 `or arm_name == ...`）
  - `tests/test_e1_p87_geometry.py`（增加 `test_truth_static_materials_no_leakage_to_other_arms`）
  - `reports/V9-E1GEOP/gemini-b5x8/`（交付产物）
- 未改动任何 spec 常量，未提交未推送。
