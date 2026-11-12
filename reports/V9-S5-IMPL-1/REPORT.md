# S5 实现 1 验收交付报告（r1 修订版）：渲染、分区与标签模块（纯 CPU）

- **任务编号**：`ainerzero.V9.P229`
- **执行者**：`gemini-k7x2`（二级执行 agent，会话 `sess-7350d561b3fc`）
- **类型**：实现交付（纯 CPU / NumPy，无 GPU / MLX 依赖，不拿锁，未生成实际 `s5p1-*` 数据，未修改 `artifacts/`）
- **依据**：`reports/V9-S5-DESIGN/DESIGN-r1.md`、`reports/V9-S5-IMPL-1/tier1-review/REVIEW.md`

---

## 1. 针对一级对抗验收意见（Tier-1 Review）的逐条整改与回应

针对一级对抗验收在第 1 轮中提出的 5 项整改要求，本版（r1）进行了全面重构与严密加固，测试集从 36 项扩充至 43 项，**11 个对抗性突变全部直接杀死（0 漏网）**：

### 1.1 要求 1：测试必须直接调用生产函数，拦下全部 11 个对抗突变
- **问题分析**：第 1 轮打回指出，旧测试中的部分「坏对照」是在测试文件内部写了另一套逻辑来做比较，而没有直接对真实生产函数施加边界约束与精确断言，导致当生产代码被恶意破坏时测试仍然漏网（如同格多圆盘被遮挡、可见像素门槛等）。
- **整改落实**：
  - **M2（`da2_frames` 不传 `f=DA2_F`）**：新增 `test_da2_frames_contract`，直接调用 `world.da2_frames(ep, 0)`，并与显式按 `f=DA2_F=196.0` 渲染的同一帧进行逐像素比对（`assert np.array_equal(d_frames[0], ref_f196)`）。当 M2 破坏时（变为 $f=259$），逐像素比对立即报错，**M2 被杀死**。
  - **M3（R2 记计数 `+= 1`）**：重构 `test_contract5_r2_multi_disk_same_cell_stays_one`。精准计算几何坐标，在方位 6 格（$[0^\circ, 7.5^\circ]$）与距离 4 格（$[2.259, 3.293]\text{m}$）内放置两个侧向微小错开（$1^\circ$ 与 $6^\circ$）的圆盘（$(2.4\cos 1^\circ, 2.4\sin 1^\circ)$ 与 $(2.8\cos 6^\circ, 2.8\sin 6^\circ)$）。两者均清晰可见（像素数分别为 872 与 207，均 $\ge 4$）且互不遮挡。直接调用生产函数 `labels.r2(mock_ep, 0)`，断言 `np.max(grid) == 1`。当 M3 变为累加时，该格值为 2，`assert max == 1` 立即失败，**M3 被杀死**。
  - **M4（R2 取段内第 14 帧而不是第 15 帧）**：新增 `test_r2_exact_step_15`。构造一个在第 14 步完全不可见（位于远端 $(20, 20)$）、而在第 15 步出现在正前方 $(3, 0)$ 的圆盘。调用生产函数 `labels.r2(mock_ep, 0)`。当第 15 帧正确被取用时，圆盘落在占据网格；若被 M4 改为取第 14 帧，网格全为 0，断言失败，**M4 被杀死**。
  - **M6（`student_clip` 帧号整体偏 1）**：新增 `test_student_clip_exact_step_indexing`。构造智能体在第 0 步位于原点 $(0,0)$、第 1 步产生位移 $(1,0)$ 的情境。调用生产函数 `world.student_clip(ep, 0)` 并提取首帧 `clip[0]`，与直接以全局第 0 步状态渲染的参考帧进行逐像素校验（`assert np.array_equal(clip[0], ref_step0)`）。若整体偏 1，第 0 帧变成了第 1 步的图像，比对立即失败，**M6 被杀死**。
  - **M9（可见像素门槛 4 → 1）**：新增 `test_r2_visible_threshold_strict_four_pixels`。通过生成精准掩码图像输入预渲染模式，分别构造可见像素为严格 3 个像素和严格 4 个像素的圆盘。调用生产函数 `labels.r2(mock_ep, 0, precomputed_frames=...)`。断言 3 像素时网格为 0，4 像素时网格为 1。当 M9 将阈值下调为 1 时，3 像素情况产生误报（输出 1），断言失败，**M9 被杀死**。
  - **M10（方位左右颠倒）**：新增 `test_r2_azimuth_polarity_left_positive`。分别在左侧（$y=+1.0$）和右侧（$y=-1.0$）放置圆盘。调用生产函数 `labels.r2(mock_ep, 0)`。严格断言左侧圆盘落入方位格 $\ge 6$（正角区），右侧圆盘落入方位格 $\le 5$（负角区）。当 M10 对相对角取反时，方位格完全倒置，断言失败，**M10 被杀死**。
  - **M11（纹理默认关）**：新增 `test_contract3_default_texture_enabled`。调用不显式指定 `texture` 参数的生产函数 `render.render(agent, [], [])`，将其输出与 `texture=True` 和 `texture=False` 进行逐像素比对。断言默认渲染与 `texture=True` 完全一致（`max_abs_diff == 0`），而与 `texture=False` 存在显著差异（`max_abs_diff > 0.05`）。当 M11 将默认参数改为 `False` 时，断言失败，**M11 被杀死**。

### 1.2 要求 2：`materialize.py` 的 manifest 写入代码身份
- 在 `src/ainerzero/v9/experiments/s5/materialize.py` 中实现了 `_get_code_identity()`：
  - 自动读取当前仓库的 `git rev-parse HEAD`；
  - 自动遍历并计算 `src/ainerzero/v9/experiments/s5/*.py`（所有 10 个 S5 模块）以及核心依赖 `src/ainerzero/v9/experiments/s4/world.py` 的 SHA256 摘要；
  - 物化生成的 `manifest.json` 中完整持久化 `code_identity` 字典，确保数据包具有不可篡改的代码溯源身份。

### 1.3 要求 3：登记分区的权限硬防御
- **CLI 层防御**：在 `materialize.py` 的 `main()` 入口中，严格增加检查：若 `--partition` 属于 `REGISTERED`（即 `s5p1-final` 或 `s5p1-final-shift`），CLI 立即抛出 `PermissionError` 并退出，**严禁通过常规 CLI 物化登记测试集**。
- **函数层防御**：在 `world.py` 的 `episode()` 以及 `materialize.py` 的 `materialize_partition()` 中，严格强制双重校验：必须同时满足 `allow_registered=True` **且** `registered_run_id` 给出有效非空字符串。缺少任何一项直接抛出 `PermissionError`。

### 1.4 要求 4：分区命名空间与索引范围检查
- **命名空间白名单校验**：在 `world.py` 和 `materialize.py` 中，凡是以 `s5p1-` 开头的分区名称，必须严格存在于 `PARTITIONS` 白名单中；若拼写错误（例如 `s5p1-devel`），立即抛出 `ValueError` 并拒绝执行。
- **索引范围校验**：在 `materialize.py` 与 `world.py` 中，严格校验 `world_index` 或 `--worlds` 必须落在区间 $[0, \text{PARTITIONS}[\text{partition}])$ 内，防止越界或生成不合法数据。
- 在 `tests/v9/experiments/test_s5_world.py` 中新增 `test_partition_name_and_world_range_validation` 对此进行全覆盖测试。

### 1.5 要求 5：单次渲染帧复用加速与逐元素一致性测试
- **性能瓶颈整改**：旧版在物化一个剪辑时，学生帧、R1、R2、R3、disk_groups、ordering_pairs 会多次重复调用 `render()`，造成高达 2.3 倍的渲染冗余。
- **帧复用接口扩展**：在 `src/ainerzero/v9/experiments/s5/labels.py` 中，为 `r1`, `r2`, `r3`, `disk_groups`, `ordering_pairs` 均扩展了可选参数 `precomputed_frames: list[tuple[np.ndarray, np.ndarray, np.ndarray]] | None = None`，无缝支持传入预渲染的 `(rgb, depth, ids)` 三元组；同时完全保留原有的按需渲染签名，100% 向后兼容。
- **物化性能大幅提升**：`materialize.py` 在物化每个剪辑时，仅对 16 帧学生图像渲染一次，随后将预渲染的深度与编号图共享传递给全部标签生成函数（仅对 R3 的未来第 23 帧补充单次渲染）。实测物化单个完整世界（16 段剪辑，32 个文件）的时间从原先的 >8s 大幅缩短至 **3.51s**！
- **逐元素一致性测试**：在 `tests/v9/experiments/test_s5_labels.py` 中新增 `test_labels_precomputed_frames_parity`，将预渲染路径生成的 `r1_logd`, `r1_sky`, `r2_grid`, `r3_grid`, `groups`, `pairs` 与原生直接渲染路径的输出进行严格逐元素比对（`np.array_equal` 与结构一致性），断言两者完全等价。

---

## 2. 11 个对抗性突变杀伤结果全景表（直接对标 `tier1-review/mutations.py`）

使用 Tier-1 验收人提供的对抗测试脚本 `reports/V9-S5-IMPL-1/tier1-review/mutations.py` 在隔离副本中对生产代码逐项注入改动，实测结果如下：

| 突变编号与名称 | 注入破坏代码 | 状态 | 杀死它的测试用例（直接调用生产函数） |
| :--- | :--- | :---: | :--- |
| **M1_no_registered_guard** | `world.py`: 去掉 REGISTERED 检查 | **KILLED** | `test_contract6_registered_partition_permission` |
| **M2_da2_frames_no_f** | `world.py`: `da2_frames` 不传 `f=DA2_F`（导致默认使用 259 焦距） | **KILLED** | `test_da2_frames_contract`（与显式 $f=196.0$ 渲染逐像素校验） |
| **M3_r2_counts** | `labels.py`: R2 记计数（`grid += 1`） | **KILLED** | `test_contract5_r2_multi_disk_same_cell_stays_one`（两圆盘同格无遮挡） |
| **M4_r2_wrong_frame** | `labels.py`: R2 取段内第 14 帧而不是第 15 帧 | **KILLED** | `test_r2_exact_step_15`（第 14 步在远端、第 15 步在正前方） |
| **M5_ray_distance_depth** | `render.py`: 深度用射线长度而非光轴正交深度 $z = t \times 1.0$ | **KILLED** | `test_contract1_wall_orthogonal_depth`, `test_contract4_explore_render_pixel_exact` |
| **M6_student_clip_offset** | `world.py`: `student_clip` 帧号整体偏 1 步 | **KILLED** | `test_student_clip_exact_step_indexing`（第 0 步静止 vs 第 1 步位移） |
| **M7_r1_sky_zero** | `labels.py`: R1 全天空块记 0 而不是 NaN | **KILLED** | `test_r1_labels_contract` |
| **M8_r3_no_offset** | `labels.py`: R3 不加 8 步偏移 | **KILLED** | `test_r3_step_offset` |
| **M9_min_visible_1** | `labels.py`: 可见像素门槛从 4 降低为 1 | **KILLED** | `test_r2_visible_threshold_strict_four_pixels`（3 像素拒判，4 像素判入） |
| **M10_azimuth_flip** | `labels.py`: 方位角计算左右正负颠倒 | **KILLED** | `test_r2_azimuth_polarity_left_positive`（左侧圆盘 $\ge 6$，右侧圆盘 $\le 5$） |
| **M11_texture_off_default**| `render.py`: 地面纹理默认参数改为 `texture=False` | **KILLED** | `test_contract3_default_texture_enabled`（默认调用与 `texture=True` 等价） |

**突变杀伤率统计：11 / 11 全部杀死（100% 杀伤率，0 漏网）**。

---

## 3. 交付文件清单与补丁结构

### 3.1 核心源码与测试清单
| 文件路径 | 职责说明 | 代码行数 / 测试数 |
| :--- | :--- | :--- |
| [`src/.../s5/__init__.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/__init__.py) | S5 顶层导出符号与常量定义。 | 50 行 |
| [`src/.../s5/render.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/render.py) | 纯 CPU 光线投射与光栅化渲染器（正交深度、世界锚定纹理、遮挡排序、DA2 显式焦距 $f=196.0$、默认纹理开启）。 | 269 行 |
| [`src/.../s5/world.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/world.py) | 世界物理权威委托至 `s4.world`；白名单校验；预登记双重权限防线；纯像素 `student_clip`；`da2_frames` 焦距绑定。 | 179 行 |
| [`src/.../s5/labels.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/labels.py) | 读出头标签生成：R1（对数深度+全天空 NaN）、R2（二值占据+4像素门槛）、R3（+8步偏移）、disk_groups、ordering_pairs，支持预渲染帧复用加速。 | 284 行 |
| [`src/.../s5/materialize.py`](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s5/materialize.py) | 数据落盘 CLI 与调度：CLI 拒绝 REGISTERED 分区；写入完整 `code_identity`；每剪辑单次渲染帧复用。 | 261 行 |
| [`tests/.../test_s5_render.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s5_render.py) | 渲染模块契约与对抗测试（包含 M5, M11 杀死用例及几何对齐断言）。 | 14 passed |
| [`tests/.../test_s5_world.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s5_world.py) | 世界接口契约与权限测试（包含 M1, M2, M6 杀死用例、CLI 拒绝测试集、白名单与范围校验）。 | 15 passed |
| [`tests/.../test_s5_labels.py`](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s5_labels.py) | 标签契约与对抗测试（包含 M3, M4, M7, M8, M9, M10 杀死用例及双路径一致性比对）。 | 14 passed |
| **测试套件总计** | 全套 43 项测试全部通过（耗时 9.53 秒）。 | **43 passed** |

### 3.2 证据文件清单
| 证据文件 | 说明 |
| :--- | :--- |
| [`reports/V9-S5-IMPL-1/diff.patch`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-1/diff.patch) | S5-IMPL-1 全部源码与测试的完整 unified diff 补丁。 |
| [`reports/V9-S5-IMPL-1/evidence/metrics.json`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-1/evidence/metrics.json) | 包含 9 项契约、11 项突变杀伤率、单世界物化耗时与代码身份的完整 JSON 结构化度量。 |
| [`reports/V9-S5-IMPL-1/evidence/contracts_and_bad_controls.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-1/evidence/contracts_and_bad_controls.txt) | `run_evidence.py` 执行全过程的纯文本日志，详细记录各项契约数值与突变杀死过程。 |
| [`reports/V9-S5-IMPL-1/evidence/pytest_s5_tests.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-1/evidence/pytest_s5_tests.txt) | `pytest -v` 运行 43 项测试用例的完整输出实录。 |
| [`reports/V9-S5-IMPL-1/SHA256SUMS.txt`](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S5-IMPL-1/SHA256SUMS.txt) | 本交付目录内全部文件的 SHA256 校验列表。 |

---

## 4. 9 项核心契约验证与度量实测数据

所有 9 项核心契约均在 `run_evidence.py` 中完成了独立复核与坏对照证伪：

1. **契约 1（几何正交与深度遮挡）**：正东墙体（$x=10$）中心深度实测严格等于 $5.0000\text{ m}$（误差 $<10^{-5}$）；边缘列若按坏对照欧氏距离计算产生 $1.1837\text{ m} > 0.5\text{ m}$ 桶形扭曲；前圆盘 100 严格遮挡后圆盘 101。
2. **契约 2（DA2 焦距与裁切对齐）**：传入 $f=196.0$ 时，中心裁切 392 列缩放后与 224 学生帧中心误差仅 $0.4579\text{ px} < 1.0\text{ px}$；坏对照 $f=\text{None}$（按 90° FOV 默认 $f=259$）中心误差达 $8.7716\text{ px} > 5.0\text{ px}$。
3. **契约 3（纹理世界锚定）**：智能体原地旋转时，地面同一世界坐标点纹理颜色最大绝对差仅 $0.0013 < 0.02$；坏对照屏幕空间纹理在旋转时产生 1.0 阶跃突变。
4. **契约 4（摸底渲染逐像素等价性）**：`render.py` 输出与 `tier1-explore/render.py` 逐像素绝对差为 $0.00\times 10^0 < 10^{-6}$，完全一致。
5. **契约 5（R2 纯二值占据）**：网格取值集合严格为 $\{0, 1\}$；人为构造两个圆盘落入同一单元格且互不遮挡时，单元格数值严格保持为 1（非累加 2）。
6. **契约 6（学生端纯净度与权限）**：`student_clip` 严格输出形状为 `(16, 224, 224, 3)` 的 uint8 像素数组，无任何几何/状态泄漏；试图访问登记分区 `s5p1-final` 严格抛出 `PermissionError`。
7. **契约 7（切片无缝覆盖与 R3 边界）**：16 段各 16 步严格覆盖 0–255 步无重叠；R3 所需最大访问步数为 $15\times 16 + 15 + 8 = 263 < 272$，安全余量 9 步。
8. **契约 8（确定性重现）**：相同分区与种子生成的数据逐字节绝对差严格为 0。
9. **契约 9（纯 CPU 渲染性能）**：$224\times 224$ 单帧渲染耗时中位数为 $10.16\text{ ms}$（P95 为 $10.87\text{ ms}$），大幅优于 $25.0\text{ ms}$ 的考核阈值。

### 单世界物化基准（性能优化实测）
- **物化规模**：单个完整世界（16 段剪辑，每段 1 个 student npz 与 1 个 labels npz，共 32 个数据文件）；
- **物化耗时**：**3.51 秒**（基于帧复用优化，单剪辑仅需 17 次渲染而非旧版的 39 次）；
- **Manifest 追踪**：自动记录 `git_head`（`68dccca964...`）以及 11 个核心源文件（S5 模块与 `s4/world.py`）的 SHA256 摘要。

---

## 5. 关键度量快照（`metrics.json` 全文字段）

```json
{
  "contract_1_geometry": {
    "status": "PASSED",
    "wall_center_depth": 5.0,
    "bad_control_hypot_diff": 1.1836803428790015,
    "occlusion_respected": true
  },
  "contract_2_da2_alignment": {
    "status": "PASSED",
    "scaled_pixel_error": 0.45793412747137674,
    "bad_control_f_none_error": 8.771641641771751
  },
  "contract_3_texture_anchored": {
    "status": "PASSED",
    "world_tex_diff": 0.0013020678930751317,
    "bad_control_screen_diff": 1
  },
  "contract_4_explore_equivalence": {
    "status": "PASSED",
    "max_abs_diff": 0.0
  },
  "contract_5_r2_binary": {
    "status": "PASSED",
    "unique_values": [0, 1],
    "multi_disk_same_cell_max": 1
  },
  "contract_6_student_purity_and_permissions": {
    "status": "PASSED",
    "clip_shape": [16, 224, 224, 3],
    "clip_dtype": "uint8",
    "registered_partition_blocked": true
  },
  "contract_7_clip_slicing_and_r3_boundary": {
    "status": "PASSED",
    "total_steps": 272,
    "r3_max_step": 263
  },
  "contract_8_determinism": {
    "status": "PASSED",
    "seed_difference": 0
  },
  "contract_9_performance": {
    "status": "PASSED",
    "median_latency_ms": 10.158979497646214,
    "mean_latency_ms": 10.225048340507783,
    "p95_latency_ms": 10.871387501174468,
    "threshold_ms": 25.0
  },
  "materialization_benchmark": {
    "status": "PASSED",
    "single_world_seconds": 3.51,
    "num_files": 32,
    "git_head": "68dccca964ed3f62cd542f54ed3d810fb7cab8b2",
    "files_tracked_in_manifest": 11
  },
  "mutations_kill_rate": {
    "status": "PASSED",
    "total": 11,
    "killed": 11,
    "leaked": 0,
    "details": {
      "M1_no_registered_guard": "KILLED",
      "M2_da2_frames_no_f": "KILLED",
      "M3_r2_counts": "KILLED",
      "M4_r2_wrong_frame": "KILLED",
      "M5_ray_distance_depth": "KILLED",
      "M6_student_clip_offset": "KILLED",
      "M7_r1_sky_zero": "KILLED",
      "M8_r3_no_offset": "KILLED",
      "M9_min_visible_1": "KILLED",
      "M10_azimuth_flip": "KILLED",
      "M11_texture_off_default": "KILLED"
    }
  }
}
```

---

## 6. 结论

本阶段 S5 实现 1（r1 修订版）已彻底解决 Tier-1 对抗验收提出的全部 5 项打回问题：
1. **11 个对抗突变 100% 杀死（0 漏网）**，所有测试均直接调用真实生产函数进行真实证伪；
2. **代码身份与血统追踪机制已集成至 Manifest**；
3. **CLI 与函数层对预登记分区构筑了坚固的硬防御**；
4. **分区白名单与索引范围限制全面生效**；
5. **帧复用优化将单世界物化时间缩短至 3.51 秒**，并通过了双路径逐元素一致性测试。

交付物已就绪，所有约束与协议均严格遵守，请求一级验收。
