# E1-X 导出模块实现与测试报告（ainerzero.V9.P70）

- **执行者**：gemini-t8m4（二级执行 agent · 纯 CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P70`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 70 步（E1-X 导出）
- **依据协议**：
  - `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-X（数据导出与碰撞输入定义）
  - `reports/V9-P48/PREREG_DRAFT.md` §3（世界与数据分区）
  - AWZ 盘点 `awz.V9.B23` 与真值修正 `awz.V9.B20` / `awz.V9.B25`
  - `src/ainerzero/v9/experiments/e1/prior.py` 与 `metrics.py`
  - `src/ainerzero/v9/experiments/s1/data.py`（封存与只读一次通道）
- **文件改动范围**：
  - 新增：`src/ainerzero/v9/experiments/e1/export.py`
  - 新增：`tests/test_e1_export.py`
  - 导出更新：`src/ainerzero/v9/experiments/e1/__init__.py`
  - 交付成果：`reports/V9-E1X/gemini-t8m4/`

---

## 1. E0 字段溯源与 E1-X 映射对照表

本模块将 E0 单段仿真输出解耦导出为两份数据：**学生侧数据**（纯状态与无偏先验几何，严格脱敏）与**评测侧真值**（完整参数、配对与逐帧法向碰撞输入）。

### 1.1 字段映射与出处表

| 目标端 | E1 字段名 | E0 来源字段 | E0 源码定位 | 转换与处理逻辑 |
|---|---|---|---|---|
| 学生侧 | `sequence_id` | `world_key` | `dataset.py:95` | 加盐哈希成 16 位不透明 hex ID，盐仅存评测侧 |
| 学生侧 | `tick` | `frame` (60 fps) | `blender_worker.py:588` | `tick = 2 * frame`（常量 `TICKS_PER_FRAME = 2`） |
| 学生侧 | `position` | `objects[name].position` | `blender_worker.py:579` | 右手系 Z-up 恒等映射，入口断言锁定 |
| 学生侧 | `linear_velocity` | `objects[name].linear_velocity` | `blender_worker.py:681` | 中心差分真值瞬时速度（自由落体误差界 0.013 m/s） |
| 学生侧 | `orientation` | `objects[name].rotation_quaternion` | `blender_worker.py:576` | 四元数 $[q_w, q_x, q_y, q_z]$ 归一化保留 |
| 学生侧 | `angular_velocity` | `objects[name].angular_velocity` | `blender_worker.py:502` | 角速度 $[w_x, w_y, w_z]$（rad/s） |
| 学生侧 | `bounding_sphere_radius` | `dimensions` | `scenarios.py:45` | 球体取 $d/2$；盒体取外接球 $\frac{1}{2}\sqrt{dx^2+dy^2+dz^2}$ |
| 学生侧 | `static_environment` | `hidden_parameters` & `objects` | `scenarios.py:88-370` | 转换成 `prior.py` 类几何，**严格剥除静态面摩擦与恢复系数** |
| 评测侧 | `normal_speed` | `objects.linear_velocity` & `contacts.normal` | `blender_worker.py:726-736` | **计算 $(\mathbf{v}_b - \mathbf{v}_a) \cdot \mathbf{n}$**（非标量 `relative_speed`） |
| 评测侧 | `distance` | `contacts.distance` | `blender_worker.py:730` | 接触中取解析距离；无接触帧填入 `+inf` |
| 评测侧 | `hidden_parameters` | `metadata.hidden_parameters` | `blender_worker.py:753` | 包含所有物体的真实物理参数（mass, friction, damping） |
| 评测侧 | `mechanisms` | `metadata.mechanisms` | `blender_worker.py:506` | S 族特有机制（如二次空气阻力参数与作用域） |
| 评测侧 | `paired_p_opaque_id` | `metadata.paired_p_world_key` | `dataset.py:99-106` | S↔P 不透明序列 ID 跨族配对映射 |

---

## 2. 核心机制实现细节

### 2.1 法向碰撞相对速度计算与约定
E0 的 `contacts[i]['relative_speed']`（`blender_worker.py:736`）直接取自 `rel_vel.length`，即相对线速度标量幅值 $\|\mathbf{v}_b - \mathbf{v}_a\|$。若直接用于碰撞判定，会将切向滑动速度计入法向碰撞冲量，导致虚假触发。
- **方向约定**：接触法向量 $\mathbf{n}$ 约定为由 $object\_a$ 指向 $object\_b$ 的单位向量。
- **法向投影速度**：$\text{normal\_speed} = (\mathbf{v}_b - \mathbf{v}_a) \cdot \mathbf{n}$。当两物体相互靠近（闭合碰撞）时，$\text{normal\_speed} < 0$；闭合相对速率为 $-(\mathbf{v}_b - \mathbf{v}_a) \cdot \mathbf{n} > 0$。
- **无接触处理**：当物体对在当帧未发生接触时，`distance` 记为 `float('inf')`，`normal_speed` 记为 `0.0`。

### 2.2 静态几何转换与隐藏参数隔离
- `Ground` $\to$ `GroundPlane(z_plane=0.0)`。
- `TableTop` $\to$ `TableTop(z_top=1.6, x_bounds=(-2.0, 2.0), y_bounds=(-1.25, 1.25), thickness=0.2)`。
- `Ramp` $\to$ `InclinedRamp(point=..., normal=..., x_bounds=(-1.5, 1.5))`。
- `OccluderWall` $\to$ `StaticBox(min_point=..., max_point=...)`。
- **严格隔离**：静态物体的真实摩擦系数与恢复系数属于隐藏参数，只进入评测侧 `hidden_parameters`，在学生侧静态几何中严格剔除。

### 2.3 泄漏守卫（Leakage Guard）
函数 `assert_no_leakage(student_dict)` 递归遍历学生侧字典的所有键与字符串值：
- 严格拦截禁止键：`family`, `world_key`, `hidden_parameters`, `mechanisms`, `paired_p_world_key`, `contacts`, `contact_specification`, `paired_p_opaque_id`；
- 严格拦截禁止前缀与值：`s_`, `seq_s_`, 族标识字符串；
- 命中任何一项立即抛出 `LeakageError`。

### 2.4 final 分区封存与只读一次通道
- `seal_final_dataset(staging_dir, sealed_root=..., sealed_by=...)`：核验文件清单 `("student_final.jsonl", "truth_final.jsonl", "export_meta.json")`，计算规范 JSON 签名，写入只读权限目录（`0o555` / `0o444`）与 `SEALED.json`。
- `open_sealed_final_once(sealed_dir, ...)`：互斥创建 `.READ_ONCE.json` 标记并签发 `FinalReadToken`；若标记已存在，则抛出 `FinalPartitionSealed` 拒绝重复读取。

---

## 3. 单元测试验证（tests/test_e1_export.py）

全部 8 项单元测试通过，总执行耗时 0.16 秒：

| 测试项 | 耗时 | 验证内容 |
|---|---|---|
| `test_tick_and_coordinate_mapping` | 0.001s | `tick = 2 * frame` 映射锁定与 3D 坐标恒等性断言 |
| `test_bounding_sphere_radius_calculation` | 0.001s | 球体 $d/2$ 与立方体 $\frac{\sqrt{3}}{2}L$ 外接球半径计算 |
| `test_static_geometry_conversion_omits_friction_restitution` | 0.002s | 地面/桌面/斜面几何转换正确，无任何摩擦/恢复系数泄露 |
| `test_hand_crafted_normal_velocity_vs_scalar_relative_speed` | 0.002s | 手算对照：$(\mathbf{v}_b - \mathbf{v}_a) \cdot \mathbf{n} = 3.6$ m/s $\ne$ 标量幅值 $3.741657$ m/s；无接触帧填 `+inf` |
| `test_leakage_guard_intercepts_all_prohibited_items` | 0.002s | 逐项构造泄漏（禁止键、`s_` 前缀、隐参数），守卫全数拦截 |
| `test_s_and_p_pairing_and_decoupling` | 0.003s | S 序列脱敏为不透明 ID，S↔P 配对关系仅存留在评测侧 |
| `test_final_partition_sealed_read_once` | 0.004s | final 首次读取成功签发 Token，二次读取触发 `FinalPartitionSealed` 拒绝 |
| `test_read_only_integration_on_awz_pilot` | 0.042s | **只读集成检验**：读取 AWZ pilot 样本小样的 train 与 dev（共 12 段），导出并通过全部守卫；**未打开 final** |

---

## 4. 坏对照（源码变异攻击验证）

在独立副本目录（`/tmp/e1_x_mutants/`）下实施源码变异，指定 `PYTHONPATH` 并打印 `__file__`，逐项证明对应测试变红：

1. **变异 1：用 relative_speed 代替法向速度**
   - 变异操作：在 `compute_pairwise_collisions` 中将 `normal_speed` 替换为标量速度 `scalar_speed`；
   - 指向源：`/tmp/e1_x_mutants/mutant_1_relative_speed_for_normal_speed/ainerzero/v9/experiments/e1/export.py`；
   - 目标测试：`tests/test_e1_export.py::test_hand_crafted_normal_velocity_vs_scalar_relative_speed`；
   - 变红结果：`FAILED: AssertionError: assert 3.741657 == 3.6`（Exit Code 1）。
2. **变异 2：学生侧漏出族标签**
   - 变异操作：在 `student_view` 构造时漏入 `"family": family`；
   - 指向源：`/tmp/e1_x_mutants/mutant_2_leak_family_tag/ainerzero/v9/experiments/e1/export.py`；
   - 目标测试：`tests/test_e1_export.py::test_s_and_p_pairing_and_decoupling`；
   - 变红结果：`FAILED: ainerzero.v9.experiments.e1.export.LeakageError: Forbidden key 'family' found at $`（Exit Code 1）。
3. **变异 3：tick 改成 1×frame**
   - 变异操作：将 `TICKS_PER_FRAME: int = 2` 改为 `TICKS_PER_FRAME: int = 1`；
   - 指向源：`/tmp/e1_x_mutants/mutant_3_tick_1x_frame/ainerzero/v9/experiments/e1/export.py`；
   - 目标测试：`tests/test_e1_export.py::test_tick_and_coordinate_mapping`；
   - 变红结果：`FAILED: AssertionError: assert 1 == 2`（Exit Code 1）。
4. **变异 4：去掉泄漏守卫**
   - 变异操作：将 `assert_no_leakage` 函数实现修改为直接 `return`；
   - 指向源：`/tmp/e1_x_mutants/mutant_4_remove_leakage_guard/ainerzero/v9/experiments/e1/export.py`；
   - 目标测试：`tests/test_e1_export.py::test_leakage_guard_intercepts_all_prohibited_items`；
   - 变红结果：`FAILED: Failed: DID NOT RAISE <class 'ainerzero.v9.experiments.e1.export.LeakageError'>`（Exit Code 1）。

四组坏对照全数变红，变异监督测试无虚假放行。

---

## 5. 规范与完整性声明

- **零模型训练、零 GPU**：全部操作均在纯 CPU / NumPy 环境下执行，未生成正式大数据，未消耗任何训练或 GPU 预算。
- **AWZ 保持只读**：未对 `AnimeWorldZero` 仓库进行任何写操作；未访问 `AnimeWorldZero/reports/V9-B20/r1/pilot_raw/final` 分区。
- **交付物**：
  - `src/ainerzero/v9/experiments/e1/export.py`
  - `tests/test_e1_export.py`
  - `reports/V9-E1X/gemini-t8m4/REPORT.md`
  - `reports/V9-E1X/gemini-t8m4/data.json`
  - `reports/V9-E1X/gemini-t8m4/SHA256SUMS.txt`
