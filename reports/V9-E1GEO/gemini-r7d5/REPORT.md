# 任务报告 ainerzero.V9.P84：E1 修订 r1-3：export 静态几何与 E0 一致

- **任务 ID**：`ainerzero.V9.P84`
- **执行 Agent**：`gemini-r7d5`（二级执行 agent，code 类型）
- **所属阶段**：AinerZero · V9 v9 落地：NeuroGeometry × H-JEPA 世界脑 (E1 实验体系)
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **关联只读目录**：`/Users/mac/AinerWorkFlow/AnimeWorldZero`
- **交付状态**：COMPLETED
- **交付物目录**：`reports/V9-E1GEO/gemini-r7d5/`

---

## 1. 任务背景与核心修改

依据一级架构裁定修订 r1（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` 末尾）第 3 条，原有 `src/ainerzero/v9/experiments/e1/export.py`（约 170–250 行）在生成学生侧静态几何时存在四个几何错位与兜底缺陷：
1. **TableTop**：原有 `z_top = float(pos[2])` 取的是盒子中心，实际顶面应为 `pos[2] + thickness/2`（在中心 1.6m、厚度 0.2m 时，顶面为 1.7m）；x/y 边界原有 `±w/2`、`±l/2`，未叠加自身位置 `pos[0]` 与 `pos[1]`。
2. **Ramp**：原有 `point = pos` 取的是斜面盒中心，表面偏低了半个厚度；修正为 `pos + n * (thickness/2)`（n 取 `matrix_world` 第 2 列并单位化）；x 边界补上 `pos[0]`，y 边界通过本地 y 轴（`matrix_world` 第 1 列）单位化后乘以 `length/2` 投影到世界坐标系中得出 `y_bounds`。
3. **彻底清除静默兜底**：
   - 缺失 `dimensions` 时抛出 `ValueError(f"Missing dimensions for static object {name!r}")`；
   - Ramp 缺失 `matrix_world` 时抛出 `ValueError(f"Missing matrix_world for static object {name!r}")`，禁止使用写死的法向量硬编码；
   - 缺失 `position` 时抛出 `ValueError(f"Missing position for static object {name!r}")`。
4. **静态盒旋转检查**：
   - 对 `StaticBox`（如 `OccluderWall`）检查其四元数；若偏离单位四元数 `[1, 0, 0, 0]` 超过 `1e-6`，抛出 `NotImplementedError`，严格杜绝非轴对齐几何的静默穿模。

---

## 2. 修复前后学生视图字段对照 (Before vs After)

### 2.1 对照表

| 物体 | 字段 | 修复前 (Before) | 修复后 (After) | 说明 |
|---|---|---|---|---|
| **TableTop** | `z_top` | `1.6` | `1.700000` | 修复前为中心高度，偏低 0.1m；修复后为 `pos[2] + thick/2` |
| **TableTop** | `x_bounds` | `[-2.0, 2.0]` | `[pos[0] - 2.0, pos[0] + 2.0]` | 正确叠加 `pos[0]` |
| **TableTop** | `y_bounds` | `[-1.25, 1.25]` | `[pos[1] - 1.25, pos[1] + 1.25]` | 正确叠加 `pos[1]` |
| **TableTop** | `thickness` | `0.2` | `0.2` | 保持不变 |
| **Ramp** | `point` | `[0.0, 0.0, 1.135535]` | `[0.0, -0.090843, 1.313714]` | 修复前为盒中心；修复后为 `pos + n * (thickness/2)`，沿法向距离中心恰为 0.2m |
| **Ramp** | `normal` | `[0.0, -0.454214, 0.890893]` | `[0.0, -0.454214, 0.890893]` | 来自真实 `matrix_world` 单位法向量 |
| **Ramp** | `x_bounds` | `[-1.5, 1.5]` | `[pos[0] - 1.5, pos[0] + 1.5]` | 正确叠加 `pos[0]` |
| **Ramp** | `y_bounds` | *(缺失)* | `[-2.227232, 2.227232]` | 新增：本地 y 轴投影至世界 y 轴得出覆盖范围 |

### 2.2 JSON 序列化对照

#### Before (`reports/V9-E1GEO/gemini-r7d5/before/student_geo_before.json`):
```json
{
  "ground": null,
  "ramps": [
    {
      "point": [0.0, 0.0, 1.135535],
      "normal": [0.0, -0.45421384210507615, 0.8908926903057097],
      "x_bounds": [-1.5, 1.5]
    }
  ],
  "tables": [
    {
      "z_top": 1.6,
      "x_bounds": [-2.0, 2.0],
      "y_bounds": [-1.25, 1.25],
      "thickness": 0.2
    }
  ],
  "boxes": []
}
```

#### After (`reports/V9-E1GEO/gemini-r7d5/student_geo_after.json`):
```json
{
  "ground": null,
  "ramps": [
    {
      "point": [0.0, -0.09084276842101524, 1.313713538061142],
      "normal": [0.0, -0.45421384210507615, 0.8908926903057097],
      "x_bounds": [-1.5, 1.5],
      "y_bounds": [-2.227231725764274, 2.227231725764274]
    }
  ],
  "tables": [
    {
      "z_top": 1.7000000000000002,
      "x_bounds": [-2.0, 2.0],
      "y_bounds": [-1.25, 1.25],
      "thickness": 0.2
    }
  ],
  "boxes": []
}
```

---

## 3. 真实 E0 集成测试验证 (Blender Headless)

通过 `ScenarioBuilder` 分别构造 `table_slide` 与 `ramp_roll` 场景，调用 E0 无头 Blender Bullet 物理引擎真实渲染生成并完成 export 流程：

1. **`test_real_e0_integration_table_slide`**：
   - TableTop 测量中心位置 `pos = [0.0, 0.0, 1.6]`，厚度 `0.2`。
   - 学生视图 `tables[0].z_top = 1.700000`，与理论值 `1.6 + 0.1 = 1.7` 绝对误差为 `0.0`（门槛 `< 1e-6`，通过）。
   - 滑块（`TableSlider`，尺寸 `(0.7, 0.7, 0.6)`，半高 `0.3`）第 1 帧质心 `z = 2.0`。
   - 滑块底面 `2.0 - 0.3 = 1.7`，与桌顶 `z_top` 误差为 `0.0`（门槛 `< 1e-3`，通过），严格证明滑块真实贴合于桌面顶面。

2. **`test_real_e0_integration_ramp_roll`**：
   - 斜面厚度 `0.4`，半厚度 `0.2`。
   - 斜面平面点 `point` 与中心 `pos` 沿法向的点积距离为 `0.200000`，绝对误差 `1.3878e-16`（门槛 `< 1e-6`，通过）。
   - 世界坐标系投影范围 `x_bounds = [-1.5, 1.5]`，`y_bounds = [-2.227232, 2.227232]` 严格覆盖斜面本体顶点投影（通过）。

**耗时统计**：两个场景无头 Blender 执行合计 **2.45 秒**，远低于登记的上限预算 **120 秒**（余量 97.96%）。

---

## 4. 源码变异坏对照 (Bad Controls) 严格验证

在隔离副本目录 `/tmp/bad_controls_p84/` 中分别执行源码变异，确保相应测试准确变红（退出码 1）：

### 坏对照 (a)：恢复 `z_top = pos[2]`
- **变异文件**：`/tmp/bad_controls_p84/bad_a/src/ainerzero/v9/experiments/e1/export.py`
- **变异内容**：将 `z_top = float(pos[2]) + thick / 2.0` 恢复为 `z_top = float(pos[2])`
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_controls_p84/bad_a/src python3 -m pytest /tmp/bad_controls_p84/bad_a/tests/test_e1_export.py -k "test_real_e0_integration_table_slide or test_static_geometry_conversion_omits_friction_restitution" -v
  ```
- **执行结果**：退出码 1，两项测试均变红失败：
  ```
  FAILED test_static_geometry_conversion_omits_friction_restitution: assert 1.6 == 1.7 ± 1.7e-06
  FAILED test_real_e0_integration_table_slide: AssertionError: z_top 1.6 != expected 1.7000000000000002
  ```

### 坏对照 (b)：恢复 `point = pos`
- **变异文件**：`/tmp/bad_controls_p84/bad_b/src/ainerzero/v9/experiments/e1/export.py`
- **变异内容**：将 `point = np.array(pos, dtype=np.float64) + normal * (thick / 2.0)` 恢复为 `point = np.array(pos, dtype=np.float64)`
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_controls_p84/bad_b/src python3 -m pytest /tmp/bad_controls_p84/bad_b/tests/test_e1_export.py -k "test_real_e0_integration_ramp_roll" -v
  ```
- **执行结果**：退出码 1，测试变红失败：
  ```
  FAILED test_real_e0_integration_ramp_roll: AssertionError: Distance along normal 0.0 != half thickness 0.2
  ```

### 坏对照 (c)：恢复 `dimensions` 兜底默认值
- **变异文件**：`/tmp/bad_controls_p84/bad_c/src/ainerzero/v9/experiments/e1/export.py`
- **变异内容**：将 `if dims is None: raise ValueError(...)` 恢复为静默兜底 `dims = obj_meta.get("dimensions") or STANDARD_OBJECT_DIMENSIONS.get(name, (1.0, 1.0, 1.0))`
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_controls_p84/bad_c/src python3 -m pytest /tmp/bad_controls_p84/bad_c/tests/test_e1_export.py -k "test_static_geometry_missing_dimensions_raises" -v
  ```
- **执行结果**：退出码 1，测试变红失败：
  ```
  FAILED test_static_geometry_missing_dimensions_raises: Failed: DID NOT RAISE <class 'ValueError'>
  ```

---

## 5. 全量测试通过与 Fixture 调整记录

### 5.1 全量测试结果
执行 `PYTHONPATH=src python3 -m pytest tests/test_e1_*.py`：
- **总测试数**：176 项
- **通过测试数**：176 项
- **失败测试数**：0 项
- **总耗时**：15.79 秒

### 5.2 Fixture 调整记录（均在 `tests/test_e1_export.py` 文件范围内）
1. **`test_static_geometry_conversion_omits_friction_restitution`**（约第 142 行）：
   - 原测试断言依据旧几何预期 `z_top == 1.6`。
   - 现调整为严格断言真实顶面 `z_top == pytest.approx(1.7)` 与 `env.tables[0].z_top == pytest.approx(1.7)`。
2. **`test_real_b25_s_family_hidden_parameters_export`**（约第 380 行）：
   - 原测试 mock 序列的第 1 帧中仅包含 `RollingActor`，未填入静态物体 `Ramp` 的初始位姿与 `matrix_world`。在彻底清除静默兜底后，该 fixture 触发 `ValueError: Missing first-frame pose for static object 'Ramp'`。
   - 现向该 fixture 的帧数据中注入由 `ScenarioBuilder` 规范确定的 `Ramp` 初始位置 `[0.0, 0.0, 1.135535]` 与 `matrix_world`。

---

## 6. 交付文件清单与校验和

交付物位于 `reports/V9-E1GEO/gemini-r7d5/`，清单如下：
- `REPORT.md`（本报告）
- `metrics.json`（量化指标汇总）
- `student_geo_after.json`（修复后静态几何示例）
- `before/export.py`（修改前备份）
- `before/test_e1_export.py`（修改前备份）
- `before/test_e1_data_runner.py`（修改前备份）
- `before/student_geo_before.json`（修复前静态几何示例）
- `SHA256SUMS.txt`（交付物完整哈希）
