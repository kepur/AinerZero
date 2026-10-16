# v9 教师与特征缓存规范 v0（ainerzero.V9.T1）

- 状态：一级设计 v0（Claude 起草，2026-10-16）· 待非 claude 一级审议
- 上位文档：`ARCHITECTURE_V9.md` r3 §7；AWZ ADR-0006 第 4、5 条、ADR-0008、ADR-0009；Forge `docs/APACK_FORMAT.md` v0
- 机器可读部分：`contracts/v9/teacher_cache.v0.schema.json`（JSON Schema 2020-12），正反例在 `contracts/v9/examples/teacher_cache/`
- **本文只写设计，不授权任何下载、安装、训练或 GPU 运行。** 已批准的只有 T4 的范围（RESEARCH_LOG `R20261016-T4`）。训练暂停（R20261015-pause）不变。

## 0. 术语

| 词 | 含义 |
|---|---|
| 教师 | 冻结的外部预训练模型，只做推理，从不更新参数 |
| 特征教师 | 输出潜在特征（V-JEPA 2.1、DINOv3 等）；不是传感器，没有噪声模型 |
| 几何教师 | 输出深度、相机位姿、点跟踪、对象掩码等物理量（DA2、DA3、MapAnything、SAM 2.1、TAPNext）；按 §4 当作带噪声的传感器 |
| 缓存条目 | 一个教师对一个输入片段的一次推理结果，加完整元数据；内容寻址，写入后不可变 |
| 学生 | AinerZero 自己的 MLX 网络 |

## 1. 三种运行模式

### 1.1 常驻集与互斥

| 模式 | 允许常驻 | 禁止 | 持有的锁 | 内存上限（进程峰值，规划值） |
|---|---|---|---|---|
| **Teacher Mode** | 恰好一个教师 + 推理所需输入 | 任何学生训练；第二个教师 | `artifacts/locks/teacher-mode.lock`（独占） | 32 GB |
| **Train Mode** | MLX 学生 + 只读缓存视图 | 加载任何教师（含 Core ML、PyTorch）；写缓存 | `artifacts/locks/m0-worker.lock`（v9 训练器沿用） | 48 GB |
| **World Mode** | 轻量编码器（S5 后为多教师合一的学生编码器）+ 学生 + AWZ 后端；**按需**临时加载至多一个几何教师 | 训练；同时加载两个教师 | 加载教师期间持有 `teacher-mode.lock` | 24 GB（给 Blender/Godot 渲染留空间） |

内存上限是规划值。T4 实测后由一级改写本节，未实测前一律用这些数作为停止线。

### 1.2 锁的规则（沿用 ADR-0006 第 1 条“非阻塞、被占就放弃”的写法）

1. **Teacher Mode 开始前**：
   - 非阻塞试锁 `m0-worker.lock`，被占就直接放弃，状态记为 `skipped_lock_busy`；试完立即释放。
   - 然后非阻塞获取 `teacher-mode.lock`，被占同样记 `skipped_lock_busy`。
   - 不等待，不重试。
2. **v9 训练器（Train Mode）开始前**：
   - 获取 `m0-worker.lock`；
   - 再非阻塞试锁 `teacher-mode.lock`，被占就放弃并释放 `m0-worker.lock`。
   - 旧 M2 CLI 不改：训练暂停期间不运行它；恢复训练时由一级另行决定是否给它加这条检查。
3. **World Mode 按需加载教师**：
   - 非阻塞获取 `teacher-mode.lock`，失败就**降级**：这一帧的该教师观测记为缺失，写 `teacher_unavailable` 事件，不阻塞世界运行；
   - 用完立即卸载并释放锁。
4. **AWZ 的重任务**：仍用自己的 `tools/locks/awz-heavy.lock`，AWZ 从不持有 AinerZero 的锁（ADR-0006 第 1 条原意）。
5. **接力台 GPU 档位**（ADR-0009 第 2 条）：
   - 教师推理任务默认 `needs_gpu = 1`（轻量）；
   - 模型 ≥ 1B 参数，或 T4 类实测进程峰值 ≥ 16 GB 的教师，登记为 `needs_gpu = 2`（重型，全机串行）。

### 1.3 内存与电源保护线（ADR-0006 第 5 条、ADR-0009 第 4 条）

- 启动前要求系统可用内存 ≥ 32 GB，磁盘剩余 ≥ 50 GB；
- 运行中可用内存低于 16 GB，或 swap 持续增长，就在下一个安全点停止并归档，状态记为 `stopped_memory_guard`；
- 用电池时不跑教师批处理，也不训练。

### 1.4 模式切换

- 切换前必须卸载当前教师：
  - MLX：释放引用、`mx.clear_cache()`；
  - Core ML：丢弃模型对象；
  - PyTorch：释放引用，并清空 MPS 缓存。
- 切换前后各记一次内存（MLX `get_active_memory`/`get_peak_memory` 与进程 RSS）。若卸载后 RSS 回落不到加载前 +2 GB 以内，就拒绝切换，记 `unload_incomplete`，并要求重启进程。
- 进程内的模式守卫（`ModeGuard`，由 ainerzero.V9.T2 实现）：
  - Train Mode 下，任何教师类的构造或权重加载都抛错；
  - Teacher Mode 下，第二个教师的构造抛错；
  - World Mode 下，教师句柄带 TTL，超时自动卸载。
- **跨进程互斥靠 §1.2 的文件锁，进程内互斥靠 `ModeGuard`，两者都要有**：只有文件锁挡不住同进程误加载，只有守卫挡不住另一个进程。

### 1.5 Core ML 计算单元

- Core ML 教师有三档计算单元：`CPU_AND_NE`、`CPU_AND_GPU`、`ALL`。
- 与 MLX 训练或 Blender/Godot 渲染同时运行时，只能用 `CPU_AND_NE`，避免争用 GPU。
- 独占时用 T4 实测吞吐最高的一档。
- 选用的计算单元写进缓存条目的 `runtime.compute_units`。不同计算单元的输出不保证逐位一致，因此它也是缓存键的一部分。

## 2. 特征缓存

### 2.1 内容寻址键

```text
cache_key = sha256( canonical_json( key_material ) )
key_material = {
  "teacher":    {teacher_id, variant, weights[{file, sha256}], code_revision,
                 runtime{framework, framework_version, compute_units, dtype}},
  "preprocess": {spec_sha256, resolution, frames, normalization, token_policy},
  "input":      {sha256, media_type, timestamps_s}
}
```

- 规范 JSON 沿用 APACK §2：`sort_keys`、分隔符 `(',', ':')`、`ensure_ascii=False`、UTF-8。
- **输入用内容哈希，不用路径或帧序号**。时间用世界时钟秒（`timestamps_s`），与 ObservationPacket 的显式 `dt` 一致，不允许帧序号代替时间。
- 输入的世界键（`world_key`）和分区（`partition`）**不进键**，记在条目里：同一段画面在不同世界里属于同一个推理结果，但分区守卫按条目逐个检查。
- 改了任何一项（权重、预处理、RLT 阈值、计算单元、精度）就是新键，不覆盖旧条目。

### 2.2 存放与不可变

```text
artifacts/teachers/cache/<cache_key[0:2]>/<cache_key>/
├── record.json          # 符合 teacher_cache.v0 的 cache_entry 记录
├── output.safetensors   # 主输出（或 .npz）
└── confidence.safetensors   # 可选：逐像素/逐 token 置信度
```

- 写入流程：
  1. 写到同目录下的临时名；
  2. 计算所有文件的 sha256，写进 `record.json`；
  3. 原子改名为最终目录。
- 目标目录已存在时：比较新算出的输出摘要。一致就什么也不做；不一致就**拒绝写入**，记 `nondeterministic_output`，交一级处理。不覆盖。
- 读取时重算 sha256，不符就把条目标为 `broken` 并拒绝读取。不重算、不修复（APACK §7 同一原则）。
- `artifacts/` 已被 .gitignore 忽略，缓存不进 git。

### 2.3 可复现性等级

GPU 浮点计算不一定逐位可复现，所以每个教师在 T4 类基准里实测并登记等级，写入条目的 `reproducibility`：

| 等级 | 判定 | 读取侧规则 |
|---|---|---|
| `bitwise` | 同键重跑，输出 sha256 相同 | 直接按 sha 核对 |
| `numeric` | 不逐位相同，但满足登记的容差（特征余弦 ≥ 0.9999、或最大绝对误差 ≤ 登记值） | 同键重跑结果以首次写入为准；重跑只用于审计 |
| `unverified` | 尚未做重跑对照 | 只能用于探针与基准，**不能挂进训练** |

### 2.4 分区与泄漏

- 条目的 `partition` 只能取 `train`、`development`、`quarantine`（APACK §3 同规则）。
- **`final`（考场）画面的教师特征不写进共享缓存。** 考场运行时由评测器进程现算，或写进封存的 `eval_suite` 包，按 `read_sealed_once` 读取。
- 同一 `world_key` 不得在两个分区出现：以 Forge 全局世界索引为准，挂载时检查（APACK §5、§6 第 7 步）。
- 噪声标定（§4）只用 `development` 分区的世界，且这些世界与考场世界不相交。

### 2.5 来源与训练准入

- 条目的来源记为 `source_type = "teacher_feature"`。这是 v9 新增的来源类型，由 forge.V9.A1 加入 APACK 词表。
- 原系统枚举照 APACK §3 保留在 `origin_native`：
  `{"system": "ainerzero", "origin": "observed", "derived_by": "<teacher_id>", "use": "input" | "target"}`。
- 含义：输入画面本身是学生的实际观察（`observed`），教师只是对它做了确定性的冻结变换。它不是教师的断言（`teacher_claim`），也不是示范（`teacher_demo`）。
- 旧的 `admit_training`（`src/ainerzero/core/experience.py`）**不改**。v9 训练器另加一道准入 `admit_teacher_feature`，按白名单逐项匹配 `teacher_id`、权重 sha256、预处理 sha256、许可范围含 `train`、可复现等级不是 `unverified`、分区是 `train`。
- 能力报告自动标注：
  - `use = "input"`：标“借外部预训练感知”；
  - `use = "target"`（蒸馏、REPA 式对齐）：标“借外部教师监督”。
- 仿真真值（AWZ `simulator_truth` / v9 `sim_truth` 分区）不走教师缓存。它只能作标签，用了它的模型要在能力声明中注明“借仿真特权信息训练”（ARCHITECTURE_V9 §7.4）。

### 2.6 作为 APACK 包

- 缓存条目按（教师、权重、预处理）分组，登记成托管包：`pack_id = az-teacher-<teacher>-<variant>`。
- `kind` 用 v9 新增的 `teacher_features`，同样由 forge.V9.A1 加入。
- 包 manifest 的 `shards` 列出每个条目目录下的文件；`provenance.source_type = "teacher_feature"`；`license` 取教师许可与输入许可的**交集**（任一方不许 `train`，整包就不许 `train`）。
- APACK 包登记之前，缓存只能用于探针与基准，不能挂进训练。

### 2.7 RLT 的记录

启用 RLT 停帧去重（ARCHITECTURE_V9 式 10，ainerzero.V9.T8）时：
- `preprocess.token_policy` 写 `{"kind": "rlt", "tau": <冻结值>, "norm": "linf", "patch": <块大小>}`；
- 条目的 `output.token_stats` 写保留 token 数、原 token 数和游程长度分布摘要；
- `token_policy.kind = "none"` 与 `"rlt"` 是不同的键，两者可以并存，用来做开/关对照。

## 3. 坐标与时间

- 世界坐标沿用 ADR-0008：Y 轴向上、单位米、右手系。
- 相机坐标统一记为 OpenCV 约定（x 右、y 下、z 前）。DA3 的外参原样是 OpenCV w2c，按此记录。
- 转到世界坐标的变换写进 `output.coordinate_frame.to_world`，并断言行列式符号。
  - Blender 侧坐标映射 `(x, −z, y)` 的行列式为 +1，见 awz.V9.B5；
  - 换算只在适配层做，配往返测试（ADR-0008）。
- `output.scale` 必填，取值：
  - `relative`：仿射不确定，如 DA2 的视差；
  - `up_to_scale`：差一个全局尺度，如多视角位姿；
  - `metric`：米制。
- 学生和 GeometryCore 不得把 `relative` 或 `up_to_scale` 的量当米制使用。
- 时间：`timestamps_s` 记世界时钟秒，多帧输出逐帧对应；输出的时间分辨率与输入不同时（如 V-JEPA 的时间块），写 `output.time_stride_s`。

## 4. 几何教师 = 带噪声的传感器：噪声标定方法

**目的**：给 GeometryCore 的观测更新（ARCHITECTURE_V9 式 2）提供观测噪声 `R`，并给出“什么时候不该信教师”的门控规则。

### 4.1 数据

- AWZ 合成场景（awz.V9.B5；物理后端以后可换 Genesis，见 awz.V9.B7），真值已知。
- 只用 `development` 分区的世界，与考场世界不相交。
- 按场景类型分层，每层至少 30 个世界、每个世界至少 20 个关键帧对（不足就标 `insufficient`，不出噪声模型）。分层维度：
  - 室内/室外；
  - 光照；
  - 卡通着色 vs 写实；
  - 相机静止/运动；
  - 停帧比例；
  - 遮挡程度。

### 4.2 位姿类教师（DA3、MapAnything）

1. 规范对齐：教师位姿与真值之间存在全局规范自由度（`up_to_scale` 时是 Sim(3)，`metric` 时是 SE(3)）。用首帧固定加 Umeyama 对齐，对齐参数单独记录，不计入误差。
2. 误差在切空间里算：`ξ = log( T_true⁻¹ · T_est ) ∈ se(3)`，对相邻关键帧的相对位姿计算，避免累积漂移混进单帧误差。
3. 拟合：
   - 每层拟合 `ξ ~ N(b, Σ)`。偏置 `b` 显著（95% 置信区间不含 0）时记录并在使用时减去。
   - 同时报告离群率（马氏距离 > χ²₆ 的 99% 分位）。离群率 > 5% 时改用 Student-t（自由度一并拟合），并在条目中标 `heavy_tailed`。
4. 异方差：教师自带置信度时，按置信度分 5 档分别拟合 `Σ`，检验 `Σ` 是否随置信度单调变化。不单调就不用教师置信度，只用分层常数。
5. 验证：
   - 在留出的同层世界上算 NEES（归一化估计误差平方），报告落在 χ²₆ 95% 区间内的比例；
   - 要求在 [0.90, 0.99] 之间，否则判定校准失败，不登记。

### 4.3 深度类教师（DA2、DA3、DA3Mono/Metric）

1. `relative` 输出：每张图用最小二乘拟合仿射 `(s, t)`（在视差或逆深度空间，按教师输出的物理意义选，并写明），对齐到真值后再算误差。`metric` 输出：不做对齐，直接算。
2. 指标：AbsRel、δ1（`max(d/d*, d*/d) < 1.25` 的比例）、对数深度残差。
3. 噪声模型：对数深度残差的方差表示为深度区间 × 置信度档位的查表，外加边缘（深度梯度大）区域单独一档。
4. 验证：同 §4.2 第 5 步，用一维 χ²₁ 的覆盖率。

### 4.4 点跟踪与对象掩码教师（TAPNext、SAM 2.1）

- 点跟踪：位置误差随遮挡时长的曲线；遮挡后的重新检出率；可见性判定的 F1。
- 对象掩码：IoU；对象 ID 切换次数（每百帧）；遮挡后的 ID 保持率。
- 这两类不进高斯观测模型。它们作为对象层的候选关联，由数据关联门控（马氏距离 + ID 保持概率）决定是否采纳。

### 4.5 登记与使用

- 每个噪声模型是一条 `noise_calibration` 记录（schema 同文件），记录：
  - 教师键族（teacher_id、权重 sha、预处理 sha）；
  - 场景层、样本量、拟合参数、验证覆盖率；
  - 标定数据的世界清单摘要。
- 记录登记后冻结；改了任何一项就发新版本。
- GeometryCore 使用规则：
  - 有对应层的已登记模型：用其 `Σ`（并减去偏置）；
  - 场景层没有登记模型：用所有层里最大的 `Σ` 乘以登记的膨胀系数（v0 定为 4），并标 `uncalibrated_layer`；
  - 单次观测的马氏距离超过 χ² 99% 分位：拒绝这次观测，记 `gated_out`，不更新信念。
- **特征教师（V-JEPA 2.1、DINOv3）没有噪声模型。** 它们只作感知特征与预测目标的对照，不进信念更新。只记录稳定性：对停帧、压缩、轻微裁剪等扰动的特征余弦相似度。

## 5. 授权清单与内存预算

状态取值：**已批准**（有原话记录）/ **待批准** / **待审** / **不用**。

| 教师或依赖 | 许可（核对日期） | 下载 | 安装 | 许可审查 | 状态 | 任务 | 预计常驻内存 |
|---|---|---|---|---|---|---|---|
| V-JEPA 2.1 ViT-L（`dgrauet/vjepa-2.1-vitl-mlx`） | 代码 MIT；权重 HF mit（2026-10-16） | 1.31 GB | 隔离 venv：vjepa2-core-mlx | 已核 | **已批准**（R20261016-T4） | T4 | 权重约 1.3 GB（F32）+ 激活，T4 实测 |
| Depth Anything V2 Small Core ML（`apple/coreml-depth-anything-v2-small`，F16/F32） | Apache-2.0（2026-10-16） | 两个 mlpackage | 同上 venv：coremltools | 已核 | **已批准**（R20261016-T4） | T4 | < 1 GB |
| coremltools | BSD-3（Apple 官方） | — | 同上 venv | — | **已批准**（作为 T4 运行时） | T4 | — |
| DA3-Small 0.08B / DA3-Base 0.12B | Apache 2.0（2026-10-16） | 待定 | PyTorch（MPS）隔离 venv | 已核 | 待批准 | T6 | 约 1–3 GB |
| DA3Mono-Large / DA3Metric-Large 0.35B | Apache 2.0（2026-10-16） | 待定 | 同 T6 环境 | 已核 | 待批准（尚无卡，T6 批准后视需要扩展） | — | 约 3–6 GB |
| SAM 2.1（小号检查点） | Apache 2.0（2026-10-16） | 待定 | PyTorch 隔离 venv | 已核 | 待批准 | T10 | 约 1–4 GB |
| TAPNext / BootsTAPIR | 代码 Apache 2.0；**权重许可待核** | 待定 | 优先 PyTorch 检查点，免装 JAX | 待核 | 待批准 | T10 | 约 1–3 GB |
| MapAnything（`facebook/map-anything-apache`） | Apache 2.0（2026-10-16） | 待定 | PyTorch 隔离 venv | 已核 | 待批准 | T12 | 约 4–8 GB；超过 16 GB 就登记为重型 |
| DINOv3 蒸馏小模型 | **DINOv3 自定义许可**：免版税、可衍生；出口管制/ITAR 条款；再分发沿用同许可 | 待定 | PyTorch | **待用户审阅** | 待审 | — | < 1 GB |
| V-JEPA2-AC（`mlx-community/V-JEPA2-AC-vitg`） | 页面未显示许可 | — | — | 待核 | 待核 | — | ViT-g，预计 > 8 GB，按重型 |
| PyTorch | BSD-3 | — | 只装在各教师隔离 venv | — | 待批准（T6/T10/T12 共用一次批准，或逐卡批准） | — | — |
| VGGT-1B | 权重 CC-BY-NC-4.0 | — | — | — | **不用**（被 DA3 取代） | — | — |
| DA3-Large / Giant / Nested | CC BY-NC 4.0 | — | — | — | **不用** | — | — |

预计常驻内存是按参数量估的规划值，不是实测，T4 类基准实测后回填。

**96 GB 统一内存的分账**（规划，跨模式不叠加，因为同一时刻只有一个模式）：

| 项 | 预留 |
|---|---|
| 系统与常驻应用 | 16 GB（ADR-0006 第 5 条） |
| 当前模式上限 | Teacher 32 GB / Train 48 GB / World 24 GB |
| AWZ 渲染（与 World Mode 同时） | 剩余部分，受 awz-heavy.lock 约束 |
| 安全余量 | 启动时可用内存 ≥ 32 GB 才开跑 |

## 6. 给后续卡的接口要求

- **ainerzero.V9.T2**（缓存读写 + 模式守卫，纯 CPU，假教师）：
  - 按 §2 实现内容寻址写入、原子改名、读时核验、`broken` 标记；
  - 按 §1.2–§1.4 实现文件锁加 `ModeGuard`；
  - 用 `contracts/v9/teacher_cache.v0.schema.json` 校验每条记录；
  - 正反例沿用 `contracts/v9/examples/teacher_cache/`。
- **ainerzero.V9.T4** 的基准结果回填 §1.1 内存上限、§1.5 计算单元、§2.3 可复现等级、§5 内存列。
- **ainerzero.V9.T6 / T10 / T12** 输出的几何量按 §3 记坐标与尺度，并按 §4 出 `noise_calibration` 记录。
- **forge.V9.A1** 在 APACK 词表加入：`source_type = teacher_feature`、`kind = teacher_features`，以及 `origin_native.use` 字段。
- **ainerzero.V9.B2** 的 `PerceptionEncoder.describe()` 输出教师键族，`token_policy()` 输出 §2.7 的结构。

## 7. 未决

1. 缓存是否需要压缩，例如 V-JEPA 特征用 F16 存储或 PCA 降维。降维会改变内容，按新键处理。等 T4 实测体积后再定。
2. `numeric` 可复现等级的容差，按教师逐个登记。T4 先给 V-JEPA 2.1 与 DA2 的数。
3. 多教师合一学生（S5）的缓存是否也走本规范：倾向是，学生编码器冻结后按“教师”登记。
4. World Mode 教师句柄 TTL 的默认值，等 AWZ 运行时接入时定。
