# v9 教师与特征缓存规范 r1（ainerzero.V9.T1）

- 状态：一级设计 **r1**（Claude，2026-10-16）· 待非作者复核
- r1 依据：Codex 2026-10-16 04:10 退回。逐项关闭见 §8：
  - §1.2 试锁后释放有竞态；
  - Train 与 World 互斥有缺口；
  - Core ML 共存说法矛盾；
  - 缓存键与来源身份混在同一条记录里；
  - sim_truth 只能是通道，partition 仍为四值。
- r0 原件逐字节归档在 `reports/V9-T1/r0-archive/`（含 SHA256SUMS），v0 schema 与示例原样保留为历史，不再用于新写入。
- 上位文档：`ARCHITECTURE_V9.md` r3 §7；AWZ ADR-0006 第 4、5 条、ADR-0008、ADR-0009；Forge `docs/APACK_FORMAT.md` v0
- 机器可读部分：
  - `contracts/v9/teacher_cache.v1.schema.json`（内容块、来源条目、噪声标定），正反例在 `contracts/v9/examples/teacher_cache_v1/`；
  - 锁协议的交错检查：`reports/V9-T1/r1/lock_model_check.py`。
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

| 模式 | 允许常驻 | 禁止 | 持有的锁（整段占用区间） | 内存上限（进程峰值，规划值） |
|---|---|---|---|---|
| **Teacher Mode** | 恰好一个教师 + 推理所需输入 | 任何学生训练；第二个教师 | `artifacts/locks/m0-worker.lock`，从开始到结束一直持有 | 32 GB |
| **Train Mode** | MLX 学生 + 只读缓存视图 | 加载任何教师（含 Core ML、PyTorch，**没有例外**）；写缓存 | 同一把 `m0-worker.lock`，从开始到结束一直持有 | 48 GB |
| **World Mode** | 轻量编码器（S5 后为多教师合一的学生编码器）+ 学生 + AWZ 后端；**按需**临时加载至多一个几何教师 | 训练；同时加载两个教师 | 同一把 `m0-worker.lock`，**整个 World Mode 运行期间**一直持有，教师的临时加载发生在这段区间之内 | 24 GB（给 Blender/Godot 渲染留空间） |

内存上限是规划值。T4 实测后由一级改写本节，未实测前一律用这些数作为停止线。

### 1.2 锁的规则（r1：三种模式用同一把排他锁，整段持有）

r0 的写法有竞态，Codex 退回时指出了两类：
- 先试一把锁、马上释放、再去取另一把锁，中间会被别的进程插进来（检查后使用竞态）；
- World 模式只拿教师锁，Train 只“试一下”教师锁而不持有，两者可以同时运行。

`reports/V9-T1/r1/lock_model_check.py` 穷举两进程的全部交错，复现了 r0 的三种违例：Teacher×Train、Train×World、Teacher×旧 M2 训练进程。r1 改为：

1. **只有一把锁**：`artifacts/locks/m0-worker.lock`。它原本就是 AinerZero 的计算租约（旧 M2 CLI 用 `fcntl.flock` 排他非阻塞持有，见 `src/ainerzero/cli.py` 的 `worker_lock`）。r1 把它的含义扩展为“任何 AinerZero 占用 GPU/统一内存的计算”，Teacher、Train、World 三种模式都用它。
2. **整段持有**：
   - 进程在开始占用计算**之前**非阻塞获取这把锁，失败就放弃，状态记 `skipped_lock_busy`，不等待、不重试；
   - 取到后**一直持有到占用结束**，模型卸载并核对内存回落后才释放；
   - 中途不释放、不换锁。
3. **不再有第二把锁**：r0 的 `teacher-mode.lock` 废弃。World 模式在整段运行期间持有这把锁，所以它内部临时加载教师不需要另取锁；同一进程里“至多一个教师”由 §1.4 的 `ModeGuard` 保证。
4. **崩溃语义**：`fcntl` 锁随进程结束由内核释放，不会留下僵尸锁。旁边写一份租约说明 `artifacts/locks/m0-worker.lease.json`（模式、pid、开始时间、任务 ID），**只用于观察**，互斥不依赖它；读到的 pid 已不存在，就视为过期说明。
5. **旧 M2 CLI 不改**：它本来就整段持有这把锁，因此自动与三种新模式互斥。
6. **AWZ 的重任务**：仍用自己的 `tools/locks/awz-heavy.lock`，AWZ 从不持有 AinerZero 的锁（ADR-0006 第 1 条原意）。World 模式与 AWZ 渲染并行是允许的，受 §1.3 内存保护线约束。
7. **接力台 GPU 档位**（ADR-0009 第 2 条）照旧，是外层调度：
   - 教师推理任务默认 `needs_gpu = 1`（轻量）；
   - 模型 ≥ 1B 参数，或 T4 类实测进程峰值 ≥ 16 GB 的教师，登记为 `needs_gpu = 2`（重型，全机串行）。
8. **现有保护线不放宽**：§1.3 的内存、磁盘、电源保护线以及 ADR-0006/0009 照旧。r1 只改锁协议，不改任何门槛。

两进程交错检查（`lock_model_check.py`）结论：r1 的 16 种进程组合（Teacher、Train、World、旧 M2，含同类两进程）全部无违例。两种故意改坏都被抓出违例：取锁后马上释放，以及先占用再取锁。

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
- **r1 统一口径**：Core ML 教师**不能**与训练共存。Train Mode 不加载任何教师，三种模式又由同一把锁互斥，所以不存在“训练同时跑 Core ML”的情形。r0 里“与 MLX 训练同时运行时用 CPU_AND_NE”这句删去。
- 唯一允许的并行是 World Mode 里的教师与 AWZ 的 Blender/Godot 渲染同时运行，这时只能用 `CPU_AND_NE`，避免争用 GPU。
- Teacher Mode 独占时，用 T4 实测吞吐最高的一档。
- 选用的计算单元写进缓存条目的 `runtime.compute_units`。不同计算单元的输出不保证逐位一致，因此它也是缓存键的一部分。

## 2. 特征缓存

### 2.1 两层身份：内容块与来源条目（r1）

r0 的写法有问题：同一个缓存键不含世界与分区，而“唯一不可变的记录”里又写了世界与分区。同一段画面出现在两个来源里时，后写的会和先写的冲突，或者覆盖掉它的来源。r1 拆成两层：

```text
内容块  teacher_blob   cache_key = sha256( canonical_json( key_material ) )
        key_material = {teacher, preprocess, input{sha256, media_type, timestamps_s}}
        只由“对什么输入、用什么教师和预处理推理”决定；不含世界、分区、用途

来源条目 teacher_entry  entry_id = sha256( canonical_json( {cache_key, world_key, partition, input_sha256, use} ) )
        记录“这个内容块在哪个世界、哪个分区、以什么用途被引用”，以及许可交集、噪声模型、存放位置
```

- 规范 JSON 沿用 APACK §2：`sort_keys`、分隔符 `(',', ':')`、`ensure_ascii=False`、UTF-8。
- **输入用内容哈希，不用路径或帧序号**。时间用世界时钟秒（`timestamps_s`），与 ObservationPacket 的显式 `dt` 一致，不允许帧序号代替时间。
- 同一内容、不同来源：一个内容块，多个来源条目，互不覆盖。
- 改了任何一项（权重、预处理、RLT 阈值、计算单元、精度）就是新的内容块，不覆盖旧块。
- 条目的输入摘要必须等于所引用内容块的 `key_material.input.sha256`；`derived_by` 必须等于块的 `teacher_id`。

### 2.2 存放与不可变

```text
artifacts/teachers/cache/
├── blobs/<cache_key[0:2]>/<cache_key>/
│   ├── blob.json              # teacher_blob 记录
│   ├── output.safetensors     # 主输出（或 .npz）
│   └── confidence.safetensors # 可选
└── entries/<entry_id[0:2]>/<entry_id>.json   # teacher_entry 记录（store = shared）
封存评测库（final 用）：只在评测器进程与 eval_suite 包里，不在上面的共享目录
```

- 写入流程：
  1. 先写内容块：写到临时名，计算所有文件的 sha256 填进 `blob.json`，再原子改名；
  2. 再写来源条目：同样先写临时名，再原子改名。
- 内容块目录已存在：比较新算出的输出摘要。一致就复用；不一致就**拒绝写入**，记 `nondeterministic_output`，交一级处理。不覆盖。
- 来源条目已存在（`entry_id` 相同）：内容完全一致就跳过，否则拒绝。
- 读取时重算 sha256，不符就把块和引用它的条目都标为 `broken` 并拒绝读取。不重算、不修复（APACK §7 同一原则）。
- `artifacts/` 已被 .gitignore 忽略，缓存不进 git。

### 2.3 可复现性等级

GPU 浮点计算不一定逐位可复现，所以每个教师在 T4 类基准里实测并登记等级，写入内容块的 `reproducibility`：

| 等级 | 判定 | 读取侧规则 |
|---|---|---|
| `bitwise` | 同键重跑，输出 sha256 相同 | 直接按 sha 核对 |
| `numeric` | 不逐位相同，但满足登记的容差（特征余弦 ≥ 0.9999、或最大绝对误差 ≤ 登记值） | 同键重跑结果以首次写入为准；重跑只用于审计 |
| `unverified` | 尚未做重跑对照 | 只能用于探针与基准，**不能挂进训练** |

### 2.4 分区与泄漏（r1：partition 仍为四值）

- 来源条目的 `partition` 取 APACK 的四个值：`train`、`development`、`final`、`quarantine`。
- `final` 条目只能 `store = "sealed_eval"`：只在评测器进程里现算，或写进封存的 `eval_suite` 包，按 `read_sealed_once` 读取。其余三个分区只能 `store = "shared"`。schema 层强制。
- **同一内容块不得被不同分区引用**：一个 `cache_key` 若同时被 `train`、`development`、`final` 中两个以上分区的条目引用，就判 `cross_partition_blob`。原因是同样的输入画面同时出现在训练和考试里，即使世界键不同也是泄漏。新条目拒绝写入，已有条目移入 `quarantine` 等一级处理。`quarantine` 只供审计，不计入这条判断。
- 同一 `world_key` 不得在两个分区出现：以 Forge 全局世界索引为准，挂载时检查（APACK §5、§6 第 7 步）。
- 噪声标定（§4）只用 `development` 分区的世界，且这些世界与考场世界不相交。

### 2.5 来源与训练准入

- 来源条目的来源记为 `source_type = "teacher_feature"`。这是 v9 新增的来源类型，由 forge.V9.A1 加入 APACK 词表。
- 原系统枚举照 APACK §3 保留在 `origin_native`：
  `{"system": "ainerzero", "origin": "observed", "derived_by": "<teacher_id>", "use": "input" | "target"}`。
- 含义：输入画面本身是学生的实际观察（`observed`），教师只是对它做了确定性的冻结变换。它不是教师的断言（`teacher_claim`），也不是示范（`teacher_demo`）。
- 旧的 `admit_training`（`src/ainerzero/core/experience.py`）**不改**。v9 训练器另加一道准入 `admit_teacher_feature`，按白名单逐项匹配 `teacher_id`、权重 sha256、预处理 sha256、许可范围含 `train`、可复现等级不是 `unverified`、分区是 `train`。
- 能力报告自动标注：
  - `use = "input"`：标“借外部预训练感知”；
  - `use = "target"`（蒸馏、REPA 式对齐）：标“借外部教师监督”。
- 仿真真值不走教师缓存。它只以 **`sim_truth` 通道**出现（Forge ExperienceEpisode §2.2），来源类型沿用 APACK 的 `simulator_truth`；它**不是**分区，分区仍是四值。它只能作标签，用了它的模型要在能力声明中注明“借仿真特权信息训练”（ARCHITECTURE_V9 §7.4）。

### 2.6 作为 APACK 包

- 内容块与来源条目按（教师、权重、预处理）分组，登记成托管包：`pack_id = az-teacher-<teacher>-<variant>`。包内每个分片对应一个来源条目所在的分区，同一内容块不跨分区（§2.4）。
- `kind` 用 v9 新增的 `teacher_features`，同样由 forge.V9.A1 加入。
- 包 manifest 的 `shards` 列出内容块文件与条目文件；`provenance.source_type = "teacher_feature"`；`license` 取教师许可与输入许可的**交集**（任一方不许 `train`，整包就不许 `train`）。
- APACK 包登记之前，缓存只能用于探针与基准，不能挂进训练。

### 2.7 RLT 的记录

启用 RLT 停帧去重（ARCHITECTURE_V9 式 10，ainerzero.V9.T8）时：
- `preprocess.token_policy` 写 `{"kind": "rlt", "tau": <冻结值>, "norm": "linf", "patch": <块大小>}`；
- 内容块的 `output.token_stats` 写保留 token 数、原 token 数和游程长度分布摘要；
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
  - 按 §2 实现内容块与来源条目两层的写入、原子改名、读时核验、`broken` 标记，以及 `cross_partition_blob` 拒绝；
  - 按 §1.2 实现“整段持有 `m0-worker.lock`”的租约（非阻塞取锁、失败即 `skipped_lock_busy`、崩溃由内核释放），并按 §1.4 实现 `ModeGuard`；
  - 用实际双进程测试复现 `lock_model_check.py` 的结论：r1 的组合不得同时占用，改回 r0 写法必须能观察到同时占用；
  - 用 `contracts/v9/teacher_cache.v1.schema.json` 校验每条记录，并实现 `reports/V9-T1/r1/check_teacher_cache_v1.py` 里 `store_problems` 的全部库级规则；
  - 正反例用 `contracts/v9/examples/teacher_cache_v1/`。v0 示例只作历史，不再作为合格输入。
- **ainerzero.V9.T4** 的基准结果回填 §1.1 内存上限、§1.5 计算单元、§2.3 可复现等级、§5 内存列。
- **ainerzero.V9.T6 / T10 / T12** 输出的几何量按 §3 记坐标与尺度，并按 §4 出 `noise_calibration` 记录。
- **forge.V9.A1** 在 APACK 词表加入：`source_type = teacher_feature`、`kind = teacher_features`，以及 `origin_native.use` 字段。
- **ainerzero.V9.B2** 的 `PerceptionEncoder.describe()` 输出教师键族，`token_policy()` 输出 §2.7 的结构。

## 7. 未决

1. 缓存是否需要压缩，例如 V-JEPA 特征用 F16 存储或 PCA 降维。降维会改变内容，按新键处理。等 T4 实测体积后再定。
2. `numeric` 可复现等级的容差，按教师逐个登记。T4 先给 V-JEPA 2.1 与 DA2 的数。
3. 多教师合一学生（S5）的缓存是否也走本规范：倾向是，学生编码器冻结后按“教师”登记。
4. World Mode 教师句柄 TTL 的默认值，等 AWZ 运行时接入时定。

## 8. r1 关闭表（回应 Codex 2026-10-16 04:10 退回）

| 退回项 | r1 处理 | 证据 |
|---|---|---|
| §1.2 试 m0 锁立即释放再取 teacher 锁存在检查后使用竞态 | 只用一把 `m0-worker.lock`，三种模式在整段占用区间持有；不再试锁后释放 | §1.2；`lock_model_check.py`：r0 的 Teacher×Train 违例被复现，r1 无违例 |
| Train 只试 teacher 锁而不持有，World 加载教师只持 teacher 锁，可与 Train 并发 | World 整段持有同一把锁；Train 整段持有同一把锁；两者天然互斥 | 同上：r0 的 Train×World 违例被复现，r1 16 种组合全部无违例 |
| 须给出完整持有区间与双进程交错反例 | §1.2 第 2 条写明持有区间；交错穷举脚本给出 r0 违例轨迹与 r1 无违例，另有两个故意改坏变红 | `reports/V9-T1/r1/lock_model_check.json` |
| 不放宽现有 guard | §1.2 第 8 条；保护线与 ADR-0006/0009 不变 | — |
| §1.5 Core ML 与训练共存，和 §1.1 Train 禁止所有教师矛盾 | 选“Train 不允许任何教师，没有例外”；只保留 World 教师与 AWZ 渲染并行时用 `CPU_AND_NE` | §1.1、§1.5 |
| §2.1 同键不含世界/分区，而唯一不可变记录含二者 | 拆成内容块（`cache_key`，不含来源）与来源条目（`entry_id`，含世界、分区、输入、用途） | §2.1–§2.2；`teacher_cache.v1.schema.json` |
| 检验同内容不同来源/分区 | 同内容同分区不同世界：合法，一个块两个条目；同内容跨分区：`cross_partition_blob`，拒绝 | `check_teacher_cache_v1.py`：库级正例 1 个、库级反例 9 个，含两条跨分区反例 |
| sim_truth 只能是通道，partition 仍四值 | §2.4 条目分区为四值，final 只能进封存库；§2.5 写明 sim_truth 只是通道，来源为 `simulator_truth` | schema 反例 `entry_partition_sim_truth` 被拒 |
| 原 v0 与失败先归档；T2 待修订复核 | r0 文档、v0 schema、r0 报告与核对结果已归档并记 SHA；T2 等 r1 非作者复核通过 | `reports/V9-T1/r0-archive/SHA256SUMS.txt` |
