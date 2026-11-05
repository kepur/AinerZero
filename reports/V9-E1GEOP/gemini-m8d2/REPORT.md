# 任务执行报告：ainerzero.V9.P87

## 1. 任务概述与目标
- **任务编号**：`ainerzero.V9.P87`
- **任务标题**：【L2·gemini·代码】E1 修订 r1-5/6：geometry_by_body 显式传递替换 radii_by_body ＋ ④ 注入静态面真实材质
- **执行 Agent**：`gemini-m8d2`（二级执行层）
- **核心目标**：
  1. 在 `prior.py` 定义严格的 `BodyGeometry(radius: float, half_extents: np.ndarray | None)`，以及 `geometry_from_student_body(info)`。
  2. 将 `src/ainerzero/v9/experiments/e1/` 下全部文件彻底清除 `radii_by_body`，全面重构为 `geometry_by_body: Mapping[str, BodyGeometry]`，且源码中出现次数严格为 0。
  3. 纯字典重构 `IdentifyResult`：彻底删除 `SubspaceDimWrapper` 与 `SubspaceWeightWrapper` 包装类隐式转换。
  4. 评测中对 Arm ④ 注入静态面真实材质（Ground, Ramp, TableTop, OccluderWall），缺材质字段严格报 KeyError。
  5. 完成 5 个专项测试与 3 个坏对照验证。
  6. 满足验收附加要求一（fixture 移至 `tests/fixtures/e1_prior_sphere_regression.npz`，核验 SHA-256）与附加要求二（尺寸表与 E0 一致性测试、收紧斜面边界断言）。

---

## 2. 代码实现与重构详情

### (1) 几何类型定义与解析 (`prior.py`)
- 定义不可变类 `@dataclass(frozen=True) class BodyGeometry`：
  - 校验 `radius >= 0`；
  - 若 `half_extents is not None`，校验 `shape == (3,)` 并转为只读 float64 ndarray。
- `geometry_from_student_body(info: Mapping[str, Any]) -> BodyGeometry`：
  - 严格要求 `shape`, `dimensions`, `bounding_sphere_radius`，缺失则抛出 `KeyError`；
  - `shape == "SPHERE"` 返回 `BodyGeometry(radius=radius, half_extents=None)`；
  - `shape == "BOX"` 返回 `BodyGeometry(radius=radius, half_extents=dimensions / 2.0)`；
  - 其他形状抛出 `NotImplementedError`。
- `make_active_body_from_state` 支持显式接收 `half_extents: np.ndarray | None`。
- 为 `GroundPlane`, `InclinedRamp`, `StaticBox`, `TableTop` 显式维护 `name: str` 字段。

### (2) 纯字典重构 (`arms_nonnet.py`)
- 彻底移除了 `SubspaceDimWrapper` 和 `SubspaceWeightWrapper`。
- `IdentifyResult` 定义：
  - `identified_subspace_dim: dict[str, int]`
  - `identified_weight: dict[str, dict[str, float]]`
- `PriorArm`, `TrueParamArm`, `IdentifyArm`, `SymbolicResidualArm` 全面接收 `geometry_by_body: Mapping[str, BodyGeometry]`。

### (3) 网络臂显式传递重构 (`arms_net.py`)
- `_prior_scene_step`, `_prepare_prefix`, `PureNetDynamicsArm`, `PriorResidualArm`, `SubspaceResidualArm`（及 `IdentifyResidualArm`）全面替换为 `geometry_by_body`。
- 当 `requires_physical_geometry` 为 True 且缺少几何映射时，严格抛出异常。
- 辨识器单体数组路径传 `{"body_0": geometry}`。

### (4) 训练与评测流水线 (`train_runner.py`, `eval_runner.py`)
- `train_runner.py`：`build_training_windows` 从 `active_bodies` 调用 `geometry_from_student_body` 构造 `geometry_by_body` 并传递。
- `eval_runner.py`：
  - 实现 `inject_truth_static_materials(static_env, truth_ep)`：深拷贝 StaticEnvironment 并从 `truth_ep` 的 `hidden_parameters` 提取 Ground、Ramp、TableTop、OccluderWall 的真实 friction 和 restitution，缺失任一必须字段立即抛出 `KeyError`。
  - 在 `evaluate_episode` 中，针对 Arm ④ 专用调用 `inject_truth_static_materials`，其余臂沿用默认材质。
  - 构造 `geometry_by_body` 传递给 `arm.predict`。

### (5) E1 源码中 `radii_by_body` 零残留保证
- 静态 AST 与文本搜索结果：
  ```bash
  grep -rn "radii_by_body" src/ainerzero/v9/experiments/e1/
  # Exit code 1, 0 matches.
  ```

---

## 3. 5 个新增专项测试用例 (`tests/test_e1_p87_geometry.py`)

1. **`test_resting_box_physics`**：
   - 盒体 1.2 x 1.2 x 1.0，z=0.5 静置于地面；初速度 0。
   - 臂 ①④⑤⑦ rollout 30 步后：
     - 最大 z 误差：0.000000e+00 < 1e-3
     - 最大水平位移：0.000000e+00 < 1e-6
   - 臂 ③⑥ 权重清零后与 ①/⑤ 的最大 diff 为 0.000000e+00 < 1e-9。通过。
2. **`test_probe_body_geometry_routing`**：
   - 同一场景内存在 Box 与 Sphere。
   - 探针验证 Box 提取 `half_extents = [0.6, 0.4, 0.3]`，Sphere 提取 `half_extents = None` 且 `radius = 0.3`。通过。
3. **`test_arm4_static_material_injection`**：
   - 盒体在地面滑动，真实地面 friction 分别为 0.2 与 0.9。
   - 臂 ④ 减速度相对误差为 0.0% < 5%；臂 ① 减速度偏离真实值（分别为 -5.4547 vs -2.9626 与 -5.3546 vs -5.9274），符合默认 0.50 摩擦力特性。通过。
4. **`test_subspace_dim_two_bodies_dict`**：
   - 双 body（垂直弹跳 vs 自由飞行）下，`identified_subspace_dim` 为纯字典 `type is dict`，分别得到 `ball_bounce >= 1`，`ball_flight == 0`，无交叉污染。通过。
5. **`test_no_radii_by_body_in_src`**：
   - 遍历 `src/ainerzero/v9/experiments/e1/` 下所有 `.py` 文件，断言 0 处 `radii_by_body`。通过。

---

## 4. 三项坏对照验证（证明变红）

### (a) `geometry_from_student_body` 对 BOX 返回 `half_extents=None`
- **变异逻辑**：强制将 BOX 的 `half_extents` 置为 `None`（退化为球体包围核）。
- **变红结果**：
  ```text
  CONFIRMED RED (a) resting integration:
  AssertionError: Arm 1 PriorArm box z1=0.98486 != 0.5 (diff >= 1e-3)
  ```
- **机理**：盒体中心 z=0.5，退化为包围球半径 0.985 时陷入地面，产生剧烈法向穿透反弹。

### (b) ④ 不注入静态面材质
- **变异逻辑**：跳过 `inject_truth_static_materials`，Arm ④ 直接使用学生端默认地面摩擦 0.50。
- **变红结果**：
  ```text
  CONFIRMED RED (b):
  AssertionError: Arm 4 position error 0.04629093750000557 exceeds 1e-6
  ```
- **机理**：真实地面摩擦为 0.2，缺失注入后按 0.5 计算产生严重速度与位移偏离。

### (c) ⑥ 的辨识器收到的几何漏掉 `half_extents`
- **变异逻辑**：Arm ⑥ 预测分支在调用 `identifier_fn` 时将 `half_extents` 抹去。
- **变红结果**：
  ```text
  CONFIRMED RED (c):
  AssertionError: assert received_geos[0].half_extents is not None
  ```
- **机理**：辨识器探针严格检验接收到的几何属性包含半长轴数组。

---

## 5. 附加要求落实

### 附加要求一：球体回归 Fixture 独立性
- 复制 `sphere_regression_fixtures.npz` 至 `tests/fixtures/e1_prior_sphere_regression.npz`。
- SHA-256 校验：`5eabd45b812c424826ce99b9a83e7cf5dc6d9c70ec8b2f6c8430f66e66e08604`（以 `5eabd45b812c4248` 开头，严格相符）。
- `tests/test_e1_prior_box.py` 已更新为从 `tests/fixtures/` 加载，脱离 `reports/` 依赖。

### 附加要求二：尺寸表与斜面边界
- `test_standard_dimensions_table_consistency_with_e0`：覆盖 5 种场景、P/S 两族、各 3 个种子，验证所有物体的 dimensions 逐项严格等于 `STANDARD_OBJECT_DIMENSIONS`。
- `test_real_e0_integration_ramp_roll`：严格断言斜面数值边界：
  `y_bounds = pos.y ± (length/2)·|cos θ|`，`x_bounds = pos.x ± width/2`。
- 两项新增/收紧测试均 100% 通过。

---

## 6. 全量测试汇总
- 运行命令：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -q`
- 测试统计：**183 passed in 18.76s (0 failed, 0 skipped)**
