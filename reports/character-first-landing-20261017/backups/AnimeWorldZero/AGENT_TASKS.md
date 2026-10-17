# AWZ 执行层任务清单

更新：2026-10-13 · R1 主责统筹：Claude（架构与 R1 任务设计）· 平级统筹：Codex（审议、算法与参数）
执行者领取前先读：[README](README.md)、[AGENTS.md](AGENTS.md)、[COORDINATION.md](COORDINATION.md)、[总体架构](docs/ARCHITECTURE.md)、相关 ADR 与契约。

**R1 范围（D-001 第 8 条）**：只做 T01–T05 和 W0，外加环境基线 T00 和独立验证 V01–V04。T04 的不确定性已接受。**R1 不训练任何神经网络**，不接 AinerZero，不做表情、口型、风格包。

## 任务总表

| ID | 任务 | 依赖 | 状态 / 负责人 | 交付 |
|---|---|---|---|---|
| C01 | R1 架构、ADR、契约、任务卡 | — | reported / Claude | 本仓库首个提交 |
| T00 | 环境、工具与锁 | C01 | open | `pyproject.toml`、`tools/check.sh`、`tools/locks.py`、`tools/env_report.py` |
| T01 | Godot 最小场景 + 身份包 v0 + 运行方式实测 | T00 | open | `godot/`、`assets/identities/heroine_001/v1/`、`docs/assets.md`、`reports/T01/` |
| T02 | 世界内核 + RNG 规范 + 状态日志 + Godot 回放 | T00 | open | `python/animeworld/kernel/`、`contracts/rng.md`、`godot/world_player/` |
| T03 | 云、水坑、波纹、踩水、水花 | T02 | open | 内核环境子系统 + Godot 视觉 |
| T04 | NPR 黑白线条 + 30 秒视频（Gate A） | T01、T02、T03 | reported / antigravity-f8x2 | `godot/render/`、`tools/render/`、`reports/T04/` |
| T05 | episode v1、录制、切分、隔离、来源（Gate D） | T02 | open | `python/animeworld/data/` |
| W0 | 非学习基线与评测器（Gate W0） | T05 | open | `python/worldbrain/baselines/`、`python/worldbrain/eval/` |
| V01 | 确定性独立复核 | T02、T03 | open（不能由 T02/T03 的作者领取） | `reports/V01/` |
| V02 | 数据契约与泄漏独立复核 | T05 | open（不能由 T05 的作者领取） | `reports/V02/` |
| V03 | Gate A 独立复核 | T04 | reported / antigravity-w4k7 | `reports/V03/` |
| V04 | W0 报告独立复算 | W0 | open（不能由 W0 的作者领取） | `reports/V04/` |
| C02 | R1 验收与 R2 方案 | 全部 | open / Claude + Codex | `RESEARCH_LOG.md`、R2 任务卡 |

**并行**：T00 完成后，T01（渲染 agent）和 T02（内核 agent）并行；T03、T05 在 T02 之后可以并行；T04 等 T01–T03；W0 等 T05。
**估时**（参考设计报告，单 agent 串行）：

| 任务 | 估时 |
|---|---|
| T00 | 0.5 天 |
| T01 | 0.5–1 天 |
| T02 | 2–3 天（含回放） |
| T03 | 2–3 天 |
| T04 | 4–7 天 |
| T05 | 2–3 天 |
| W0 | 1–2 天 |

## 通用约束（所有任务）

- **文件范围**：只改任务卡写明的文件范围。要改范围外的文件，先在任务表登记并取得统筹同意。
- **下载**：可以安装常见的小 Python 包（列出清单）；不下载模型、大资产、字体、贴图。CC0 资源的下载也要用户同意。
- **GPU**：按 ADR-0009 全力跑。轻量 GPU 任务直接跑；重型任务由接力台闸门串行；`tools/locks.py` 只保留内存、磁盘、电源这些保护线。
- **不改其他仓库**：不改 AinerZero、AinerHub_IDEA；不提交、不推送（推送由统筹做）。
- **数据不进 git**：数据集、渲染帧、视频不进 git，只提交报告、小型测试夹具和金样哈希。
- **报告**：用本文末尾的执行报告模板，存到 `reports/<task_id>/`。测试通过不等于能力达标。

---

## T00 环境、工具与锁

- **文件范围**：`pyproject.toml`、`uv.lock`、`tools/`、`tests/tools/`、`.python-version`
- **内容**：
  1. 用 uv 建立 Python 3.12 项目：
     - 基础依赖：numpy、pydantic≥2、jsonschema、pytest、ruff、pyarrow、zstandard；
     - MLX 作为可选组 `mlx`，R1 不需要；
     - 安装前列出清单。
  2. `tools/check.sh`：ruff 加 pytest（只跑 CPU 测试），返回码非 0 即失败。
  3. `tools/locks.py`：实现 ADR-0006 第 4、5 条和 ADR-0009（全力跑：只保留防崩溃的保护线和重型串行）。
     - `ainerzero_running()`：用 lsof 观察 `~/AinerWorkFlow/AinerZero/artifacts/locks/m0-worker.lock`，只用于信息展示（ADR-0009：不再挡 AWZ），**绝不取锁**；
     - `gateway_busy()`：用 `pgrep -f '[a]i-studio/scripts/ltx25_infer.py'`，只对重型 GPU 任务生效；
     - `awz_heavy_lock()`：上下文管理器；
     - `preflight()`：返回可读的原因：内存 ≥ 32GB、磁盘 ≥ 50GB、接电源。
     - 测试用临时锁文件模拟，**不碰真实的 AinerZero 锁**。
  4. `tools/env_report.py`：芯片、内存、macOS 版本，Godot 版本（读 `/Applications/Godot.app` 的 Info.plist），Blender 版本，Python 版本，输出 JSON。
- **验收**：
  - `tools/check.sh` 通过；
  - 锁的测试覆盖：网关忙时重型被挡、轻量不受影响、AinerZero 在跑不影响 AWZ、内存不足；
  - `reports/T00/env.json` 已生成。

## T01 Godot 最小场景 + 身份包 v0 + 运行方式实测

- **文件范围**：`godot/`（`godot/world_player/` 除外）、`assets/`、`docs/assets.md`、`reports/T01/`、`tests/assets/`
- **内容**：
  1. Godot 4.7.2 项目：
     - Forward+ 渲染，确认后端是 Metal；
     - 3D 物理引擎选 Jolt；
     - 物理频率 120，关闭 physics jitter fix（ADR-0002/0004）。
  2. 自制低模女主角 `heroine_001@v1`：
     - Blender 5.2.2 制作，5–10k 三角面；
     - `humanoid_v1` 骨骼，简单发束，贴图眼；
     - 走路循环（原地动画 + 根运动曲线）；
     - 材质槽按调色板槽命名（至少有 hair、eyes、skin、cloth_1、cloth_2、line）。
  3. Blender 脚本导出 `clip.json`：根运动采样（120Hz）、步长、左右脚着地相位、循环信息。导出设置和导入设置写进 `docs/assets.md`。
  4. 身份包：
     - `assets/identities/heroine_001/v1/identity.json` 能通过 `contracts/character_identity.v1.schema.json`；
     - `assets/identities/registry.json` 登记 `character_id@version → sha256`（规范 JSON 的 SHA-256）。
  5. 场景：平地、角色、相机；截图脚本。
  6. **运行方式实测**（报告必须包含）：
     - `--headless` 能不能截图。预期不能，要实测确认；
     - 窗口模式加 Movie Maker（`--write-movie`、`--fixed-fps 24`）；
     - SubViewport 回读；
     - 窗口被遮挡或最小化时会不会降频或停帧；
     - 每种方式的帧耗时。
- **验收**：
  - 身份包通过 schema 校验，注册表的 SHA 可以复算；
  - 同一机位跑两次，10 张截图逐像素差不超过 1 级；
  - 运行方式报告给出推荐方案，并说明理由。

## T02 世界内核 + RNG 规范 + 状态日志 + Godot 回放

- **文件范围**：`python/animeworld/kernel/`、`contracts/rng.md`、`godot/world_player/`、`tests/kernel/`、`reports/T02/`
- **内容**（按 ARCHITECTURE 第 3 节和 ADR-0003/0004/0008）：
  1. **时钟**：`sim_hz = 120`；`world_time` 分段映射；EDL（输出帧 → `(camera_id, tick)`）。
  2. **RNG**：
     - 计数式 `hash64(episode_seed, entity_id, subsystem_id, tick, draw_index)`，基于 SplitMix64 链；
     - `contracts/rng.md` 写明算法和 ≥ 20 条测试向量；
     - 内核里禁止使用全局 RNG：加一个静态检查测试，扫描 `random.`、`np.random.` 的直接调用。
  3. **行走**：
     - 路径按弧长参数化，速度曲线闭式（加速、匀速、减速）；
     - 朝向角速度有上限，闭式平滑；
     - `cadence = speed / stride_length`；着地事件由 `clip.json` 的相位给出。
  4. **碰撞**：编译期检查路径与障碍、人物与人物的相交（移动圆的首次接触时间用二次方程闭式求解）。相交就报错，错误里写明是哪两个实体、在哪个时刻。
  5. **状态日志**：
     - 逐 tick 记录，私有和公开分开；
     - 量化（1e-6）后算规范 JSON 的 SHA-256；
     - 提供 `state(t)` 任意时刻求值。
  6. **Godot WorldPlayer**：读日志，按输出帧设置变换、`AnimationPlayer.seek(phase)`、相机。不在 `_physics_process` 里改真值。坐标换算只在适配层做，并配往返测试。
- **验收**：
  1. 同一个种子跑两次，状态日志逐字节一致；
  2. 随机抽 100 个 tick 做 `state(t)` 任意时刻求值，结果和顺序计算相等；
  3. 着地期间脚的世界速度 ≤ 1 cm/s（不打滑）；
  4. Godot 回放导出的逐帧变换和内核相差 ≤ 1e-5 m；
  5. RNG 测试向量通过。

## T03 云、水坑、波纹、踩水、水花

- **文件范围**：`python/animeworld/kernel/environment/`、`godot/environment/`、`tests/environment/`、`reports/T03/`
- **内容**：
  1. 风场和云（闭式积分，形状用种子噪声）；
  2. 水坑（静态多边形）；
  3. 踩水事件：着地点落在水坑内时触发 `footstep_water`；
  4. 波纹：带波前条件 `r ≤ c·(t − t_i)` 的解析式（ARCHITECTURE 第 3.3 节）；
  5. 水花：参数取自计数 RNG，轨迹用抛物线闭式；
  6. Godot：波纹着色器读取事件列表（uniform 数组），水花用贴片，水坑做平面反射。
- **验收**：
  1. 事件序列跑两次完全一致；
  2. `t < t_i` 或位于波前之外时，`h = 0`；
  3. 水花位置可以闭式复算；
  4. 截图集。

## T04 NPR 黑白线条 + 30 秒视频（Gate A）

- **文件范围**：`godot/render/`、`tools/render/`、`docs/render.md`、`tests/render/`、`reports/T04/`
- **内容**（按 ARCHITECTURE 第 4、5 节和 ADR-0007）：
  1. 背面外扩轮廓：恒定像素宽度；逐顶点宽度系数；平滑法线放在 UV2。
  2. 结构线：五官用贴图线；深度、法线边缘作补充（用 CompositorEffect 或另一路 SubViewport）。
  3. 独立的 `line_alpha` 通道，单通道 8 位 PNG；R1 的风格就是纯线稿（`bands = 0`）。
  4. 2 倍超采样后下采样；禁用 TAA 和一切时序效果。
  5. 30 秒、720 帧、24fps 的场景：
     - 角色行走、转头（`look_at`）；
     - 云在移动；
     - 踩水触发水花和波纹；
     - 至少一个水坑倒影；
     - 跟拍镜头。
  6. 先输出 PNG 序列，再用 VideoToolbox 编码 MP4（`ffmpeg -c:v hevc_videotoolbox` 或 h264）。
- **指标**：
  - 静止镜头段的线条闪烁：相邻帧 `line_alpha` 的平均绝对差；
  - 线宽稳定性：用距离变换估计笔画宽度；
  - 渲染帧耗时的 p50、p95；
  - 10 个固定机位截图；5 段 3 秒回归片段；
  - 从任意帧号跳转渲染，和顺序渲染的同一帧比较（容差内一致）。
- **验收**：v1.0 的 Gate A 加上 ADR-0007 的确定性要求。性能目标写实测值，不写目标值。

## T05 episode v1、录制、切分、隔离、来源（Gate D）

- **文件范围**：`python/animeworld/data/`、`tests/data/`、`reports/T05/`
- **内容**（按 ADR-0005 和 `contracts/episode.v1.schema.json`）：
  1. **写入器**：`episode.json`、`frames.jsonl`、`private/states.jsonl`、各通道、`manifest.json`（每个文件的大小和 SHA-256）。已存在的 episode 不覆盖。
  2. **加载器**：
     - 公开加载器**只读公开文件**；
     - 私有读取是独立的接口，只给评测器用。
  3. **切分**：以「世界」为单位分配 `train`、`development`、`final`。同一世界跨分区的数量必须为 0；单帧内容重合只报告不拒绝。
  4. **隔离规则**（每条一个反例测试）：
     - 来源、操作者或策略未知；
     - 辅助类型含 `unknown`；
     - 许可不在白名单；
     - 哈希不符；
     - 帧缺失或 tick 不连续；
     - 公开字段里出现私有字段名（白名单检查）；
     - 同一世界出现在多个分区。
  5. `final` 封存：生成封存清单（SHA 和时间），读取一次后记录。
- **验收**：
  - schema 校验；
  - 篡改任何一个文件都会被拒绝；
  - 公开加载器在 monkeypatch 下不会打开 `private/`；
  - 隔离规则测试全部通过。

## W0 非学习基线与评测器（Gate W0）

- **文件范围**：`python/worldbrain/baselines/`、`python/worldbrain/eval/`、`tests/worldbrain/`、`reports/W0/`
- **内容**：
  1. 数据：用内核在 CPU 上生成固定的小数据集（20 train、10 development、10 final 个世界，每个 5–10 秒），记录数据清单的哈希。
  2. 基线：
     - 复制当前状态；
     - 恒速外推；
     - 解析规则基线（只用公开信息加已知规则，例如看到踩水事件就预测波纹）；
     - 简单的条件统计。
  3. 评测器：位置 MAE/RMSE，事件 P/R/F1，1/4/8 步开环；按原始分布评测。
- **验收**：报告可以复现，同一命令两次结果逐位相同；`final` 只评一次，并记录封存。

## V01–V04 独立验证（给执行层模型）

验证者**不能**是被验证任务的作者。只读核对，可以新建报告和 CPU 证据，不改源码。

- **V01（确定性）**：
  - 在干净的 checkout 上重跑 T02/T03 的验收；
  - 做变异测试：把内核里的 RNG 换成全局 `random`、把波纹的波前条件去掉、把 tick 改成 60Hz，确认测试都能抓到；
  - 记录捕获率。
- **V02（数据）**：
  - 独立实现一个最小的切分泄漏检查，和 T05 的结果对比；
  - 22 种篡改（改字节、删文件、改清单、改分区、改来源、改许可……）必须全部被拒绝。
- **V03（Gate A）**：
  - 重渲 5 段回归片段，和 T04 的金样做容差比较；
  - 独立计算闪烁和线宽指标；
  - 复测 p50/p95（和 T04 用同一台机器，记录负载）。
- **V04（W0）**：从数据清单开始独立复算 W0 报告的全部数字。

---

## 执行报告模板

```markdown
# <task_id> 执行报告
角色：executor / verifier；负责人：<agent>；时间：<日期>
任务状态：reported；依据：<任务卡、ADR、契约版本>
输入身份：<git commit、配置/资产/数据清单的哈希>
修改文件：<路径与目的；验证者写「无」>
实际执行：<准确命令、运行方式、锁检查结果>
验证结果：<测试数、失败/跳过、指标、和门槛对比>
产物：<报告、日志、金样哈希、截图路径>
失败与限制：<没做的、没验证的、不一致的、已知问题>
交回统筹：<需要统筹决定的问题；不擅自扩大范围>
```

领取任务时只改自己那一行的负责人、状态和交付位置。统筹审查后才标记 `accepted`。

---

## P3 v8 世界系统第一批（2026-10-15，Claude 起草）

依据：[ADR-0010](docs/adr/ADR-0010-v8-alignment.md)，用户决定 D-006、D-007（Blender 是主引擎）、D-008（AinerZero 训练暂停，资源转向世界系统）。接力台项目 `awz`，期 `P3`。任务编号对应：P3-A1 = `awz.P3.A1`，其余同理。

### P3 通用约束（在上面「通用约束」之外再加这些）

- **Blender**：
  - 用 `/Applications/Blender.app/Contents/MacOS/Blender`（5.2.2 LTS），只用后台模式（`-b`、`--background --python`），不开窗口；
  - 渲染引擎的 ID 先在本机实测（读 `bpy.types.RenderSettings.bl_rna.properties['engine'].enum_items`），不照搬网上的写法。
- **真值**：世界真值仍在 Python 内核（ADR-0003）。Blender 只读状态日志，不写真值。
- **生成代码**：流水线里跑的 bpy 都是仓库里经过评审的代码。运行时只传参数（数据），不在运行中现场生成代码再执行。
- **素材**：
  - 只用 Blender 程序化几何和程序化材质（节点）；
  - 不下载任何外部模型、贴图、HDRI，CC0 也不行（需要时另开任务请用户批准）；
  - 可以复用本仓库已登记的自产资产（`assets/identities/`）。
- **GPU**：
  - EEVEE 预览算轻量（needs_gpu=1）；Cycles 算重型（needs_gpu=2），要另行批准预算；
  - 渲染命令用 `relay exec` 包住，超过 10 分钟的用 `relay submit-run`；
  - 每个任务的渲染总墙钟不超过参数里的上限，超了就停，并在报告里写明。
- **评审**：视觉评审由领任务的 agent 自己看图完成（需要 vision 能力），不调用外部付费 API。打分是主观判断，报告里要写明不是独立评测。
- **产出**：
  - 代码；
  - CPU 测试（放 `tests/` 下，不依赖 GPU 和 bpy 的部分必须能单独跑）；
  - `reports/<任务ID>/` 报告；
  - 代表帧 PNG，单张小于 2MB，张数受参数限制。帧序列和视频不进 git。
- **报告**：边做边用 `relay_checkpoint`（或 `relay heartbeat --msg`）留接力点：已完成、下一步、改了哪些文件。额度用完时，下一棒靠它接着做。

### P3-A1 RenderBackend 契约与能力表（ADR-0010 B-1）

需要：code → 建议执行者：DeepSeek / Codex 类 · 依赖：无 · GPU：无

- **文件范围**：
  - `contracts/render_backend.v1.schema.json`
  - `contracts/backend_capabilities.v1.json`
  - `contracts/examples/render_job.blender.example.json`
  - `contracts/examples/render_report.example.json`
  - `python/animeworld/render_backend/__init__.py`
  - `python/animeworld/render_backend/contract.py`
  - `tests/render_backend/test_contract.py`
  - `reports/P3-A1/`
- **内容**：
  1. **RenderJob（输入）**：
     - 状态日志引用（路径 + sha256）；
     - EDL（输出帧 → `(camera_id, tick)`）；
     - 风格包引用、身份包引用；
     - 质量档：preview / draft / production；
     - 分辨率、帧区间；
     - 输出通道：rgb / line / depth / normal / object_id / motion；
     - 后端：blender / godot；
     - 随机种子、预算（`max_wall_s`）。
  2. **RenderReport（输出）**：
     - 每个通道的文件路径和 sha256、帧数、实际耗时；
     - 峰值内存（测不到就写 null 并说明原因）；
     - 后端版本、引擎、采样设置、失败列表。
  3. **Backend Capability Matrix**：至少 blender-eevee、blender-cycles、godot 三行，写清：
     - 每个通道是否支持；
     - 确定性等级：逐位 / 容差 / 不保证；
     - 是否需要窗口。
  4. **坐标与单位**：契约沿用 ADR-0008（Y 轴向上、米、右手系、yaw=0 面向 +Z）。Blender 是 Z 轴向上，转换规则写进契约说明，并给出测试向量。
  5. **以现有通道为准（D-012，2026-10-15 补充）**：渲染只有一条通道，以 AinerHub 现有的无头 Blender worker 为起点。只读参考：
     - `~/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/director/blender_worker/`：首帧、遮罩、可见性采样；
     - `app/worldmodel/blender_run.py`：world_multicam，clay、depth、pose 多机位；world_check。

     契约里另附一张对照表，写清每个字段被现有 worker 消费到什么程度（已消费 / 需适配 / 未支持），不另起一套不兼容的输入输出。不改 AinerHub 的文件。
- **验收**：
  - Schema 通过 Draft 2020-12 元校验；正例通过；
  - 反例至少覆盖以下 6 种，全部被拒：缺状态日志 sha、未知通道、分辨率不是正数、帧区间倒置、后端不在能力表里、缺坐标约定；
  - 坐标转换测试向量至少 6 个点、2 个朝向，往返误差 ≤ 1e-9；
  - 纯 CPU，不导入 bpy。

### P3-A2 独立复核 P3-A1

需要：code → 建议执行者：Grok 类（不能是 P3-A1 的作者）· 依赖：P3-A1

- **方式**：只读复核，不改源码。在干净环境重跑测试，另写至少 5 个作者没覆盖的反例。
- **核对内容**：坐标转换的数学；能力表有没有夸大（比如把"容差一致"写成"逐位一致"）。
- **交付**：`reports/V-P3-A1/`。

### P3-A3 Blender 主路径最小切片（ADR-0010 B-2）

需要：code → 建议执行者：DeepSeek / Codex 类 · 依赖：P3-A2 · GPU：轻量

- **文件范围**：
  - `python/animeworld/render_backend/blender_adapter.py`
  - `tools/blender/backend/`（只放在 Blender 里运行的脚本）
  - `tests/render_backend/test_blender_adapter.py`
  - `reports/P3-A3/`
- **内容**：
  1. 用 R1 已登记的雨中行走状态日志（按 `reports/T03/` 或 `reports/T04/` 里登记的路径和 sha256 取）构造 RenderJob。
  2. 后台启动 Blender，搭场景：地面、水坑、人物。
     - 人物优先导入 heroine_001 自产资产；导入不了就用代理几何，并在报告里说明。
  3. 用 EEVEE 渲染 854×480 的指定帧，输出 rgb、depth、normal、object_id 四个通道，并生成 RenderReport。
  4. **一致性检查**：
     - 对象 ID 通道里每个实体的像素质心，与内核真值按相机投影算出的屏幕位置比较，误差 ≤ 2 px（被遮挡的实体除外）；
     - 同一 RenderJob 跑两次：几何和 ID 通道要求逐位一致；RGB 报告实测差异。
- **参数**：
  ```json
  {"resolution":[854,480],"engine":"EEVEE","frames":"0–47 每 6 帧取 1，共 8 帧","max_frames":8,"repeat_runs":2,"max_render_wall_s":900}
  ```
- **验收**：
  - 8 帧 × 4 通道齐全，并记录 sha256；
  - 投影误差表；
  - 两次运行的一致性结论；
  - 说明怎么确认全程没有弹出窗口；
  - CPU 测试覆盖：RenderJob 构造、坐标转换的调用、RenderReport 校验；
  - 渲染总墙钟在上限内。
- **不得做**：不改内核；不用 Cycles；不下载资产。
- **D-012 补充（2026-10-15）**：渲染只有一条通道。本卡的 Blender 侧改为调用 AinerHub 现有 worker（`app/worldmodel/blender_run.py` 的 world_multicam，或 `app/director/blender_worker/`），作为只读的后端实现。
  - AWZ 这边只写适配层：把状态日志和 RenderJob 转成它的输入，把它的输出转成 RenderReport 和四通道。
  - 现有 worker 缺的能力（例如 normal、object_id 通道），在报告里列成缺口，交一级决定由谁补。
  - 不改 AinerHub 的文件。
  - `tools/blender/backend/` 只放现有 worker 做不到、又必须在 Blender 里跑的最小脚本。

### P3-A4 独立复核 P3-A3

需要：code、vision → 建议执行者：Gemini / Antigravity 类（不能是 P3-A3 的作者）· 依赖：P3-A3 · GPU：轻量

- **方式**：用同一个 RenderJob 独立重跑一次，预算和参数都与 P3-A3 相同。
- **核对内容**：sha256、投影误差、两次运行的一致性；看图检查有没有明显错误，比如穿模、对象 ID 错位、深度反了。
- **交付**：`reports/V-P3-A3/`。

### P3-A5 Cycles 光影实测（ADR-0010 B-4）——预算已批准（D-015）

需要：code → GPU：重型 · 依赖：P3-A4、P3-B2

- **内容**：用 P3-B1 街道（种子 1）测以下各组合：
  - 两种分辨率：854×480 和 1280×720；
  - 两种采样数：32 和 128；
  - 降噪前和降噪后；
  - 同场景的 EEVEE 对照。
- **记录**：每帧耗时、峰值内存，以及画面差异的主观评价。
- **目标**：判断写实光影在本机 M2 Max（没有硬件光追）上能用到哪一档。
- **参数**：用户 2026-10-15 20:42 批准（RESEARCH_LOG D-015）：每组 1 帧、计时 2 遍；总墙钟 ≤40 分钟（含首次 Metal 内核编译），单次渲染硬超时 5 分钟；重型 GPU 全机串行。超出即停下交回一级，不得自行加跑。

### P3-A6 独立复核 P3-A5——预算已批准（D-015）

需要：code → GPU：重型 · 依赖：P3-A5 · 非 P3-A5 作者

- **内容**：只重渲最低档（854×480、32 采样）与最高档（1280×720、128 采样）各 1 次，核对 A5 报告的耗时、峰值内存与画面；总墙钟 ≤15 分钟，单次 ≤5 分钟。超出即停下交回一级。

### P3-B1 日式街道生成器 v0（工具库第一个生成器）

需要：code、vision → 建议执行者：Gemini / Antigravity 类 · 依赖：无（和 A 轨并行，文件不重叠）· GPU：轻量

- **文件范围**：
  - `tools/blender/generators/jp_street/`
  - `tools/blender/generators/README.md`
  - `tests/generators/test_jp_street_params.py`
  - `reports/P3-B1/`
- **内容**：用参数生成一条日式住宅街，全部结果只由参数 JSON 和种子决定。
  - 道路：宽度、标线、路面限速数字；
  - 两侧 2–3 层的住宅和店铺：层数、阳台、空调外机、招牌、窗格；
  - 电线杆和电线；
  - 樱花树：树冠用程序化几何加粉色材质；
  - 可选：鸟居、自行车停车架；
  - 材质：全部用程序化节点；
  - 天空和日光：Blender 自带的天空纹理加太阳光；
  - 渲染：EEVEE，3 个固定机位，854×480 预览。
  - **语义清单**（2026-10-15 补充，ADR-0011 决定 5）：另输出 `semantics.json`，内容包括：
    - 建筑和道具的障碍轮廓（俯视二维多边形）；
    - 道路和人行道的可走区域；
    - 每栋建筑的门口位置和朝向。

    它同样只由参数和种子决定，计入确定性哈希。不做导航。
- **风格参考**：用户给的第一张截图（樱花住宅街），路径是 `/Users/mac/.claude/uploads/8ebb1d1e-e5b7-47c9-9a78-d8047dfcafda/ff5e477a-image.png`。**只作内部参考**，不复制进仓库，不进训练。
- **参数**：
  ```json
  {"seeds":[1,2,3],"cameras":3,"resolution":[854,480],"engine":"EEVEE","max_images":12,"max_render_wall_s":1200}
  ```
- **验收**：
  1. **确定性**：
     - 对象清单包括名称、类型、变换（变换四舍五入到 1e-6）。同一参数加同一种子生成两次，清单哈希必须一致；换种子必须不同；
     - 生成逻辑要和 bpy 分层，不启动 Blender 也能算出对象清单，CPU 测试覆盖参数校验和清单生成。
  2. **预览**：3 个种子 × 3 个机位，共 9 张，附参数和对象数量统计。
  3. **自评表**：对照参考图逐项写"有 / 部分 / 没有"，诚实标出差距。项目包括：建筑、电线杆和电线、樱花、路面、天空光照、整体密度。
  4. **生成器 manifest**：名称、版本、参数 schema、代码 sha256，供以后登记成资产。
  5. **语义清单**：`semantics.json` 不启动 Blender 也能算出；同参数加同种子两次哈希一致。CPU 测试检查两件事：每个障碍多边形闭合且不自交；每个门口都落在可走区域的边界上。
- **不得做**：不下载外部模型或贴图；不写只对一个种子好看的特例；不改 A 轨的文件。

### P3-B2 独立复核 P3-B1

需要：vision → 建议执行者：Grok / Gemini 类（不能是 P3-B1 的作者）· 依赖：P3-B1 · GPU：轻量

- **方式**：独立重跑一个种子，核对确定性。
- **语义清单**：重算 `semantics.json` 并核对哈希；抽一张预览图，目视核对障碍轮廓和门口位置是否对得上画面里的建筑（2026-10-15 补充）。
- **评价**：用同一张自评表对照参考图独立打分，并指出最影响观感的 3 个差距，作为 P3-C1 的输入。
- **交付**：`reports/V-P3-B1/`。

### P3-B3 动漫发型生成器 v0（D-013）

需要：code、vision → 建议执行者：Gemini / Antigravity 类 · 依赖：无（和 B1 文件不重叠）· GPU：轻量

- **依据**：`docs/research/ANIME_HAIR_MODELING_20261015.md`，以及 `docs/research/DILLONGOO_TEARDOWN_20261015.md` 第 9.1 节（二次运动作用在骨骼链上）。
- **文件范围**：
  - `tools/blender/generators/anime_hair/`
  - `tests/generators/test_anime_hair_params.py`
  - `reports/P3-B3/`
- **内容**：用参数生成动漫发型，结果只由参数 JSON 和种子决定。
  1. **外壳**：贴合头型的低多边形体积，决定轮廓。
  2. **发束**：沿引导曲线生成带状或管状发束，可调宽度和厚度渐变、发梢收尖、发束之间的缝隙；每条发束有编号、所属分组、根部、发梢和引导线。
  3. **麻花辫与抽绳模块**：一个单元沿曲线重复排列，可调单元形状、个数、扭转、粗细渐变。
  4. **输出清单** `hair_manifest.json`，内容包括：
     - 发束列表：编号、分组、引导线点列、根部和发梢；
     - 外壳的包围盒；
     - 每组发束建议的骨骼链节点数，供以后做二次运动。
- **预设**：三种发型，例如齐刘海短发、侧分中长发、双麻花辫。每种 3 个种子，各出 3 个机位的预览（854×480，EEVEE，卡通着色加描边即可）。
- **验收**：
  1. 生成逻辑和 bpy 分层：不启动 Blender 也能算出发束清单；同参数加同种子两次，清单哈希一致；换种子必须不同。
  2. CPU 测试检查：引导线点数、发梢收尖单调、麻花辫单元个数符合参数、发束编号唯一。
  3. 自评表：对照笔记里的四点，写“有 / 部分 / 没有”。
  4. 生成器清单：名称、版本、参数 schema、代码 sha256。
- **参数**：
  ```json
  {"presets":3,"seeds":[1,2,3],"cameras":3,"resolution":[854,480],"engine":"EEVEE","max_images":27,"max_render_wall_s":1500}
  ```
- **不得做**：不下载外部模型或贴图；不复刻任何现有角色的发型设计；不改 B1 的文件。

### P3-B4 独立复核 P3-B3

需要：code、vision → 建议执行者：不能是 P3-B3 的作者 · 依赖：P3-B3 · GPU：轻量

- 独立重跑一种预设、一个种子，核对清单哈希。
- 抽查发束编号、引导线和发梢收尖是否和画面对得上。
- 按笔记四点独立判断，指出最影响观感的 3 个差距。
- 只读复核，不改源码。报告放 `reports/V-P3-B3/`。

### P3-C1 美术迭代闭环 v0

需要：vision、code → 建议执行者：Gemini / Grok 类 · 依赖：P3-B2 · GPU：轻量

- **文件范围**：`tools/art_loop/`、`tests/art_loop/`、`reports/P3-C1/`
- **输入**：生成器参数、风格目标文字、参考图。
- **每一轮的流程**：
  1. 渲染；
  2. 执行 agent 自己看图，按固定评分表打分，每项 1–5 分并写理由。评分项：构图、色彩、光照、建筑细节、密度、整体相似度；
  3. 只在登记的参数空间内提出修改，例如光照角度、色温、樱花密度、建筑层数分布、相机高度和焦距；
  4. 重新渲染。
- **轮数和记录**：
  - 最多 5 轮，保留最好的一版；
  - 每一轮写一条经验记录 JSON，内容包括：参数、图像 sha256、各项分数、理由、改了什么、critic（即 agent ID）。
- **参数**：
  ```json
  {"max_iterations":5,"param_space":"tools/art_loop/param_space.json（本任务定义，统筹验收）","resolution":[854,480],"critic":"self_vision_no_paid_api","max_render_wall_s":1500}
  ```
- **验收**：
  - 完整记录 5 轮，或提前达标的轮数；
  - 第 0 版和最好一版的对比图；
  - 分数曲线；
  - 经验记录 JSON 能通过 schema 校验；
  - 报告里写明：打分是同一个 agent 的主观判断，不是独立评测。
- **不得做**：不调用付费 API；不改生成器代码，只改参数。生成器缺什么能力，就在报告里列成需求。

### P3-C2 独立复核 P3-C1（盲评）

需要：vision → 建议执行者：不能是 P3-C1 的作者 · 依赖：P3-C1

- **盲评**：把第 0 版和最好一版的顺序打乱，不告诉评审哪张是哪张，独立判断改进是否成立。
- **核对**：经验记录是否完整、是否可复现。
- **交付**：`reports/V-P3-C1/`。

### P3-D1 风格包 v2 规格（一级）

一级（Claude / Codex）· 依赖：P3-A2

- **交付**：`docs/design/STYLE_PACKAGE_V2.md` 和 schema 草案。
- **内容**：
  - 按 v8 §9.3 的结构；
  - 一份风格描述能同时编译到 Blender（主）和 Godot（可选）；
  - 与 v1 三套风格的映射；
  - 作为 `.apack` 的 style_pack 类型登记；
  - 类 LoRA 的神经适配器只放规则写不出来的部分。
  - **美术控制接口（2026-10-15 补充，依据 `docs/research/DILLONGOO_TEARDOWN_20261015.md`）**：用统一字段表达以下内容，并写清各后端怎样实现（Goo Engine 级 / 原生 Blender / Godot），原生做不到的写退化方案：
    - 线宽、收尖、随距离变细；
    - 外轮廓、内线、脸部线分层；
    - 阴影分界与分档，投影和自身阴影分开；
    - 灯光分组与灯光、阴影链接；
    - 自定义法线挂点；
    - 五官深度层次；
    - 特效拖尾。

    这些都属于美术层，修改它们只能改变 style、presentation 类摘要，不改世界状态（WORLD_COMMAND §2.3）。依赖增加 P3-D4。

### P3-D4 DillonGoo / Goo Engine 公开资料深度拆解（视觉研究）

需要：vision、multimodal → 建议执行者：Gemini / Grok 类（要能看视频和图） · 依赖：无 · GPU：无

- **起点**：`docs/research/DILLONGOO_TEARDOWN_20261015.md`，里面列了九个层面和已读的来源。
- **要看的公开资料**：
  - Professor Goo 和 DillonGoo 的 YouTube 教程；遇到 cookie 同意页时选“拒绝非必要”，不登录；
  - dillongoostudios.com 的作品集；
  - Goo Engine 公开源码（GitHub goo-engine，四个自定义节点和 light group 相关代码，只读）；
  - Blender 5.2 手册的相关章节。
- **交付** `reports/P3-D4/teardown.md`。九个层面逐一写清：
  1. 他们具体怎么做：步骤、节点或修改器、驱动方式，注明出自哪个视频的哪个时间点或哪个源码文件；
  2. 原生 Blender 5.2.2 的等价做法和退化程度；
  3. 可以检查的效果标准，例如脸转 30° 时阴影形状是否保持设计、眉毛透过刘海是否稳定、线宽随距离变化是否平滑；
  4. 对应我们哪个规格：角色包 v2（P3-D5）、风格包 v2（P3-D1）、表现效果层。
- 另选 3 段公开视频的关键画面截图，标注每处控制手法，放在 `reports/P3-D4/frames/`，单张小于 1MB，仅作内部研究引用，不进训练。
- **不得做**：不下载或安装 Goo Engine，不购买或下载付费角色和插件，不复制他们的资产、贴图或工程文件，不登录任何账号。
- **补充材料（2026-10-15）**：
  - 用户提供的 16 张视频截图在 `~/AinerWorkFlow/_refs/dillongoo_20261015/`，内部研究用，不进 git；拆解文档第 9 节已有逐项分析，以此为起点。
  - 截图侧栏里出现的 ARP、BNPR Abnormal、Lineworks、Quad Remesh 等工具，只看公开说明，核实它们的用途、对应哪个层面、许可是什么，不下载。

### P3-C3 角色技法对标闭环 v0：参考图 → Blender 逼近 → 分项比较

需要：vision、code → 建议执行者：Gemini / Grok 类 · 依赖：P3-D4 · GPU：轻量

- **做法依据**：`docs/research/DILLONGOO_TEARDOWN_20261015.md` 第 10 节。对标的是技法，不是角色；用自己的场景和非 DillonGoo 的模型。
- **文件范围**：
  - `tools/art_loop/ref_match/`
  - `tests/art_loop/test_ref_match_metrics.py`
  - `reports/P3-C3/`
- **试验台**：AinerHub 路线 B（`~/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/scripts/anime_npr_poc.py --style inked_key`，Grease Pencil 线稿加卡通着色，VRoid 样例模型）。
  - 只读参考；输出写到 `reports/P3-C3/`，不写 AinerHub 目录。
  - 脚本不支持指定输出位置时，把必要的场景搭建逻辑复制到 `tools/art_loop/ref_match/`，并注明来源。
- **参考图**：
  - 从 `~/AinerWorkFlow/_refs/dillongoo_20261015/` 选 A 组 3 张用来调参，B 组 3 张（不同角度或表情）用来验收；
  - 先遮掉截图里的 UI、文字和播放按钮；
  - 每张先写技法清单和可测目标值，交一级确认后再开始调参。
- **分项指标**（纯 CPU，要有单元测试）：
  - 线宽分布、线色；
  - 皮肤区域色阶数、阴影面积比例、阴影色相；
  - 脸部亮度方差；
  - 轮廓光圈宽度；
  - 背景模糊程度；
  - 整体风格相似度只作弱信号：本机已有 CLIP 才用（AinerHub 环境），不下载新模型。
- **闭环**：
  - 每张 A 组参考最多 5 轮；
  - 只改登记的参数空间（`tools/art_loop/ref_match/param_space.json`，本任务定义，一级验收）：线条、明暗、灯光、相机、后期；
  - 缺能力时，写候选技能放 `tools/art_loop/ref_match/candidate_skills/`，不进正式库。
- **记录**：每一轮写一条经验 JSON，内容包括：参数、图像 sha256、各项指标、视觉审片问题条目（角色、部位、证据、建议改哪个参数）、改了什么、critic 的 ID。
- **参数**：
  ```json
  {"max_iterations_per_ref":5,"refs_A":3,"refs_B":3,"resolution":[1280,720],"engine":"EEVEE","max_render_wall_s":2400}
  ```
- **验收**：
  - A 组调参前后，各分项指标的变化和对比图；
  - B 组只评一次，用最终参数；
  - 报告写明：相似度指标是代理指标，最终由人判断；同一 agent 的视觉自评不算独立评测。
- **不得做**：
  - 不用 B 组调参；
  - 不下载新模型或素材，不调用付费 API；
  - 不把参考截图复制进 git 或训练数据；
  - 不复刻 DillonGoo 角色的外形设计。

### P3-C4 独立复核 P3-C3（B 组盲评）

需要：vision → 建议执行者：不能是 P3-C3 的作者 · 依赖：P3-C3 · GPU：轻量

- 把 B 组的参考图、第 0 版和最终版打乱顺序，复核者在不知道哪张是调参后版本的情况下，逐项判断：哪个更接近参考图的技法清单，以及哪里仍然不像。
- 重算 P3-C3 的分项指标，核对它们和报告一致。
- 核对没有用 B 组调参，没有下载新模型，参考截图没有进 git。
- 只读复核，不改源码。报告放 `reports/V-P3-C3/`。

### P3-D5 角色包 v2 规格：ACIS v2（一级）

一级 · 依赖：P3-D4

- **交付**：`docs/design/CHARACTER_PACKAGE_V2.md` 和 schema 草案，放在 `contracts/drafts/character_package.v2/`。在 `docs/ACIS.md` v0.1 和 `contracts/character_identity.v1.schema.json` 的基础上升级，不推翻 v1 的金样和验收范围。
- **内容**：
  1. **分区光影**：脸、头发、身体、眼睛的灯光组和阴影链接规则。
  2. **阴影分量**：投影和自身背光面分开阈值、分开上色。
  3. **脸部法线方案**：代理形体、迁移方式、随头部转动的驱动、SDF 阴影图的接口。
  4. **五官层次规则**：哪些部件可以透过头发显示，在什么镜头距离下启用。
  5. **表演控制面**：表情集（精简 FACS）、口型、视线、手势宏、二次运动，每个都有命名的控制器、取值范围和默认值，供制作脑的表演接口（hub.P1.D1）调用。
  6. **线条分层**：外轮廓、内线、脸部线。
  7. **二次运动**：头发、裙子、配饰的模拟怎样烘焙成可修改的关键帧。
  8. **数据分层**：世界层（几何、碰撞、骨骼姿态）和美术层（法线、深度偏移、线条、灯光分组、二次运动修正）分开存，美术层的修改不改世界状态。
  9. **验收**：怎样证明角色包合格，包括多角度、多光照、多表情的金样，以及自由视角和全景下的表现。
- **不做**：不写实现，不建模。

### P3-D2 Blender 版线稿、卡通着色与 ACIS（ADR-0010 B-3）——草稿，等 P3-D1

### P3-D3 独立复核 P3-D2——草稿

### P3-E1 WorldCommand、revision、预览与撤销协议草案（一级，ADR-0010 WC-1）

- **交付**：`docs/design/WORLD_COMMAND.md` 和 schema 草案。
- **范围**：
  - 只覆盖"改世界源 → 重新编译时间线"；
  - 用 `expected_revision` 做冲突控制；
  - 先预览，确认后提交；
  - 撤销和重做。

### P3-E2 `.aworld` 清单与现有资产映射（一级，ADR-0010 AW-1）

依赖：P3-E1

- **内容**：说明 scene/v1、表演轨、身份包、风格包分别怎样被 `.aworld` 清单引用，引用方式用 `.apack`。
- **D-012 补充（2026-10-15）**：持久世界以 AinerHub 持久世界库（`app/worldmodel`，表前缀 `world_`）为唯一权威。要写清以下映射：
  - 它的区域、地标、通路、实例、事实、版本，分别怎样映射成 `.aworld` 的 `geography/`、`entities/`、`knowledge/`、`editing/`；
  - 指定版本的快照怎样导出成 AWZ 的世界源。

  依赖增加 P3-E3（统一变更协议）。

### P3-F1 Visual Knowledge & Asset Hub v0 设计（一级）

- **交付**：`docs/design/ASSET_HUB_V0.md`。
- **内容**：
  - 检索 → 授权核验 → 分析 → 拆成结构化规则和模板 → 入库；
  - 参考、训练、商用三种用途分开记录；
  - 一份放宽许可的提案，比如加入 CC-BY 和付费授权资产，**交给用户决定**；
  - 自动检索和付费 API 都不在本任务里实施。

### P3-G1 总体愿景与分层架构（北极星，一级）

一级（Claude / Codex）· 依赖：无

- **交付**：`docs/NORTH_STAR.md`。AinerZero 的 README 和 COORDINATION 只引用它，不复制内容。
- **把用户 2026-10-15 确认过的要求固定下来**：
  1. **两条线**：
     - AinerZero 是独立的世界脑：从空白开始，自驱成长，对齐杨立昆的世界模型思路——在抽象表示里预测和想象，不预测像素；
     - AnimeWorld 是世界系统，先由任意 LLM 驱动建世界、出动漫，不等世界脑。
  2. **分层**：各层只通过带版本号的契约连接，每层都能单独进化、替换，关掉任何一层，其余照常运转。层次如下：
     - 驱动智能：LLM / AinerZero / 教师；
     - 世界核心；
     - 素材与知识；
     - 风格（类 LoRA 适配器）；
     - 渲染底座：Blender / UE / Unity / Godot / 高斯；
     - 训练底座：MLX / CUDA / ROCm；
     - 治理。
  3. **世界脑学什么**：只学世界规则——光影、线条、时空、物理、运动、外观规律。它要懂画面应该是什么样，但像素交给工具画。三种能力是看懂、预判、指挥，都要设计成不靠画图的考题。
  4. **三类能力分开**：空间与时间、视觉美术、场景构建。三者可以共享数据，但训练目标和评测必须分开。
  5. **小说世界**：一本小说对应一个可挂载的 `.aworld`，随剧情逐步展开，可以用对话编辑，可以当模板复刻。
  6. **编辑数据怎么变成训练数据**：tag 只用于检索和约束；真正的训练数据是完整的编辑过程（描述 → 初稿 → 修改 → 定稿）。原著、用户改编、AI 补全三种来源分开记录。
  7. **远期路线**：只写方向，不排工期，包括：小说解释器和懒加载区域、多模态输入（参考图、首尾帧、动作视频）、神经适配器（LineNet / ColorNet / LoRA）、自优化控制器、实时与 VR。
- **验收**：每一条都能追溯到用户原话，或追溯到 D-006 至 D-009；凡是还没实现的能力，一律写明"未实现"。

### P3-H1 渲染底座中立交换格式与引擎适配规划（一级）

一级 · 依赖：P3-A2（RenderBackend 契约已复核）

- **交付**：`docs/design/SCENE_INTERCHANGE.md`。
- **内容**：
  1. 世界的中立保存格式：场景用 OpenUSD，材质用 MaterialX，资产用 glTF。分别写清在 Blender、UE、Unity、Godot 中的支持程度和已知损失（按各引擎当前版本核对，不凭印象写）。
  2. 每种引擎适配器的职责：坐标和单位转换、材质和灯光映射、能力表。
  3. 高斯泼溅这类神经渲染器怎样作为一种底座接入。
  4. 换底座的验收办法：每个底座各自通过画质门，不承诺逐像素一致。
- **不做**：不写代码，不装引擎，不下载任何东西。

## P3 补充：世界运行与制作计划（2026-10-15，D-011 / ADR-0011，Claude 起草）

依据 [ADR-0011](docs/adr/ADR-0011-three-systems.md)（三个系统加共享底座）和 [NORTH_STAR](docs/NORTH_STAR.md)。世界系统必须自己会运行世界，制作脑通过制作计划控制它。参考 Codex 审议稿 R2–R5（`~/AinerWorkFlow/AinerZero/reports/codex-v8-requirements-review-20261015/`）。上方「P3 通用约束」同样适用。

### P3-I1 世界运行契约草案（一级，ADR-0011 决定 5）

一级 · 依赖：P3-E1（世界指令协议）

- **交付**：`docs/design/WORLD_RUNTIME.md`，schema 草案放 `contracts/drafts/world_runtime.v0/`。
- **内容**：
  1. **交互运行**：临时命令等于世界源在第 t 个 tick 的一次修订。写清：
     - 从最近快照重算之后的时间线；
     - 命令日志的格式；
     - 实时运行和离线重拍怎样读同一份日志；
     - 重算时延的预算口径（数字等 P3-I2 实测后再定）。
  2. **场景语义**：可走区域、障碍轮廓、出入口、坐点（位置、朝向、接近方向）、门（轴、开合状态、开门方向）、可拿取点。由资产和生成器产出；导航由世界核心统一计算，渲染后端不各算一套。
  3. **机制包**：作用对象、区域、触发、效果、代价、结束、与其他机制冲突时的处理、版本。包括地球近似物理基础包；冲突没定义时必须报错，不让系统临时猜。
  4. **持续身份与多形态**：身份 ID、形态版本、变形事件的字段；和 ACIS 身份包 v1 的关系（已有金样和验收范围不改）。
  5. **角色运行状态**：观察、记忆、目标、关系、情绪、身体、当前行为；控制者和控制范围（同一范围同一时刻只有一个生效的控制者）。
  6. **表现效果**：非写实镜头和动画手法（夸张形变、拖影、速度线、漫画符号）怎样记录，怎样和世界真值分开。同时定义**事件的真实性类别**，至少五类：
     - 世界里实际发生（例如真的变形）；
     - 角色以为发生（幻觉、误解、梦）；
     - 回忆或闪回；
     - 蒙太奇或时间压缩；
     - 纯镜头夸张。

     每类写清：会不会改世界状态、哪些角色会知道、世界脑将来能不能拿它当训练标签。
  7. 每一项写清 v8 §22 第 4 条的六项：输入契约、输出契约、状态所有权、可测试的错误边界、性能预算、回滚路径。
  8. **D-012 补充（2026-10-15）**：持久世界以 AinerHub 持久世界库为唯一权威。
     - 场景语义要在它已有的模型上扩展，不另起一套：地标 `world_landmarks`（kind 含 door / wall / spot 等）、通路 `world_portals`、带碰撞的实例 `world_instances`、事实 `world_facts`。例如坐点和开门方向，写成地标或实例的扩展字段。
     - 运行和确定性求值以 AWZ 内核为权威，要写清：内核怎样消费持久世界快照，交互运行产生的事件怎样回写（经统一变更协议 P3-E3），哪些只留在运行日志里。
     - 依赖增加 P3-E3。
- **不做**：不写实现代码，不运行仿真或渲染。

### P3-I2 小房间世界运行切片（纯 CPU，不渲染）

需要：code、math → 建议执行者：DeepSeek / Grok 类代码执行者 · 依赖：P3-I1 · GPU：无

- **文件范围**：
  - `python/animeworld/runtime/`（新目录）
  - `tests/runtime/`
  - `reports/P3-I2/`
- **场景**：一间房，内有一张桌子作障碍、一扇门、一把椅子、一盏灯和一个角色。到椅子有两条路：短路要穿过门，长路要绕开桌子。
- **场景的描述格式（D-012）**：按 P3-I1 定下的扩展，用 AinerHub 持久世界库的结构（区域、地标、通路、实例）写成一份 JSON 快照。不需要连数据库，也不改 AinerHub。运行和求值在 AWZ 新目录里做。
- **逐项验证**，每项报告“成立 / 不成立 / 未验证”：
  1. 命令“走过去坐下”：查到椅子的坐点 → 规划路线并绕开桌子 → 分段执行解析行走 → 记录坐下事件，之后角色和椅子的接触关系保持。
  2. 在中途某个 tick 关门：之后的可达性改变，角色改走长路，或明确报告不可达。
  3. 移灯：世界里的光源状态改变并记录事件。阴影在画面上的变化留给渲染切片，这里只验证状态。
  4. 三个机位：只改相机参数，世界状态哈希逐 tick 不变。
  5. 说一句话：对白事件带开始和结束时间，并绑定说话人。音频文件可选，不下载任何配音模型。
  6. 存档重开：用世界源加命令日志重放，状态哈希逐 tick 一致；从中途快照重算和从头算出的结果一致。
  7. 反例：穿墙命令被拒、坐别人占着的椅子被拒、未定义的机制冲突报错。被拒的命令不改变任何状态。
- **确定性**：同一份世界源加同一份命令日志，两次运行哈希一致；改一条命令，哈希必须变。
- **不得做**：
  - 不改 `python/animeworld/kernel/` 下的现有文件（T10 等登记绑定了它们的 sha256），需要的功能在新目录里组合调用；
  - 不渲染，不下载，不训练。

### P3-I3 独立复核 P3-I2

依赖：P3-I2 · 复核者不得是 P3-I2 作者

- **对抗用例**：
  - 中途改命令后，从快照重算和从头算是否一致；
  - 关门后的路线是否真的没有穿门；
  - 快照恢复后的状态哈希；
  - 被拒的命令是否真的没有改状态；
  - 核对 `python/animeworld/kernel/` 下现有文件的 sha256 没变。
- 重跑 P3-I2 全部测试，逐项判断它报告的“成立”是否有证据；没有证据的改判为“未验证”。
- 只读复核，不改源码。报告放 `reports/P3-I3/`。

### P3-J1 制作计划契约 v0（一级，ADR-0011 决定 4）

一级 · 依赖：无

- **交付**：`docs/design/PRODUCTION_PLAN.md`（AWZ 侧提议稿），schema 草案放 `contracts/drafts/production_plan.v0/`。AinerHub 侧的实现等 Relay 登记 AinerHub 项目后另开任务。
- **内容**：
  1. 只读 AinerHub 的 `ainer.scene/v1`（`~/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/director/protocol.py`），列出能复用的字段和缺口。不改 AinerHub。同时读 AinerHub v2 的 `docs/v2/01_DATA_MODEL.md`、`03_CAPABILITY_API_SPEC.md`、`planA.review.md`（NarrativeIR 和 R0 契约修订）与共享舞台（StageContent、Coverage）的设计。**制作计划要和 NarrativeIR、StageContent 走同一条谱系，不另起一套并行格式**；如果 hub.P1.A1（制作脑落位）已有结论，以它为准。
  2. 分层：创作要求、叙事（节拍、谁知道什么、何时揭示）、世界、表演、镜头（服务哪个节拍、目的）、美术（覆盖）、体验（模式、观众权限）、执行与反馈。
  3. 修改语义：范围、基础 revision、依赖、锁定字段、take 版本；改镜头、改表演、改世界、改风格四类修改各自能动什么。
  4. 技法引用：计划里怎样引用技法库条目（例如“冷笑点：停顿加反应镜头”），让审片能核对手法是否真的执行了。
  5. 一个完整例子：书包变大象这一段，写悬疑版和喜剧版两份计划，标出差异。
  6. 控制编译：哪些字段由世界系统翻译成世界命令；缺能力时怎样报告“未支持”，不能把未知动作写成成功。
- **不做**：不改 AinerHub 代码，不写执行器。

### P3-E3 统一变更协议 v1：世界指令并入 WorldDelta（一级，D-012）

一级 · 依赖：P3-E1

- **交付**：`docs/design/WORLD_CHANGE_PROTOCOL.md`，schema 草案放 `contracts/drafts/world_change.v1/`。AinerHub 那一侧的实现另开 hub 任务。
- **输入**：
  - AWZ 世界指令草案 [WORLD_COMMAND.md](docs/design/WORLD_COMMAND.md)；
  - 只读的 AinerHub 持久世界库：`~/AinerWorkFlow/AinerHub_IDEA/code/apps/ainer-core/app/worldmodel/service.py`，以及 `app/models` 里 `world_` 前缀的表，包括 `WorldDelta` 的 `base_version`、`ops`、`status`、`evidence`。
- **内容**：
  1. **一个信封**：版本号、操作者、来源与证据、状态（proposed / applied / rejected / conflict）、预览与提交、撤销与回滚、逆操作。
  2. **两族操作**：
     - 持久世界操作沿用 AinerHub 的 `add_region`、`add_landmark`、`add_portal`、`add_asset`、`add_instance`、`move_instance`、`remove_instance`、`add_fact`、`lock_region`；
     - 场景和表演用带 `test` 前置的 JSON Patch。
  3. **版本**：持久世界版本和 AWZ revision 的对应关系；一条变更同时动两族时怎样原子提交，或者禁止。
  4. **类别不变量**：保留四类修改的派生摘要规则；持久世界操作一律归 `world` 类。
  5. **take 失效**：沿用 AinerHub 的做法，依赖被改的 take 标为“过期”，和 AWZ 编译结果的对应关系。
  6. **一致性测试**：两边实现同一 schema 时的黄金用例。
- **不做**：不改 AinerHub 代码，不写实现。

### P3-R2 净室流程与许可审查规范（一级，D-013）

一级 · 依赖：无

- **交付**：`docs/design/CLEAN_ROOM_AND_LICENSE.md`，外加可直接套用的审查模板 `docs/design/templates/license_review.md` 和 `behavior_spec.md`。
- **内容**：
  1. **许可审查**：
     - 每个研究目标先登记软件或资料名称、版本、许可证、是否允许逆向、我们的使用方式；
     - 判断结论分三档：可以、有条件、不可以；
     - 谁有权批准：涉及法律风险的，一律由用户决定。
  2. **调查方式与证据**：源码阅读、黑盒观测、反编译，三种方式各自保存什么证据，怎样标注来源。
  3. **净室角色**：调查者产出行为规格（只写输入输出、数值行为、界面和画面的描述，不含对方代码）；实现者只看规格；复核者对照原程序或观测记录。三者不能是同一个 agent。
  4. **行为对照**：怎样设计输入输出对照集；界面、功能、数值行为、画面、性能、文件兼容各自的验收方式。
  5. **开源许可**：GPL、MIT、Apache 等在“学原理”“调用”“拷贝代码”三种用法下各自的义务。
  6. **禁止事项**：商业软件不反编译；不引入逐字节一致的代码；不绕过技术保护措施。
- **不做**：不安装 REA，不做任何逆向。

### P3-R1 REA 试点：在有源码的开源目标上验证能力——草稿，下载待批准

需要：code → 依赖：P3-R2 · GPU：无

- **前提**：用户批准下载和安装 REA，并提供来源地址。批准前保持草稿。
- **目标**：
  - 选一个有源码作标准答案的开源函数，例如 Goo Engine 的 `node_shader_shader_info.cc` 着色分量计算，或 Blender 的一个插值函数；
  - 让 REA 只看编译后的程序去还原它；
  - 再拿源码和运行结果对照。
- **记录**：REA 的产出、和源码的差异、对照测试的通过率、耗时，以及出错的方式。
- **按 P3-R2 的流程执行**；产出只用于评估工具，不进产品代码。

### P3-A7 本机渲染性能基线：EEVEE 每帧耗时与“能不能实时”

需要：code → 建议执行者：DeepSeek / Codex 类 · 依赖：P3-A4、P3-B2 · GPU：轻量

目的：用本机实测代替估计，回答“M2 Max 上动漫风格能不能实时、成片要多久”。Cycles 归 P3-A5，本卡不用。

- **文件范围**：
  - `tools/blender/bench/`
  - `tests/render_backend/test_bench_params.py`
  - `reports/P3-A7/`
- **场景**：
  1. P3-A3 的雨中行走场景（地面、水坑、人物）；
  2. P3-B1 街道，种子 1。
- **测量**：
  - EEVEE 在 854×480、1280×720、1920×1080 三种分辨率下，各测两档质量（最低采样档，和 P3-A3 的默认档）；
  - 每组先热身 2 帧，再取至少 10 帧的单帧耗时，报中位数和最大值；
  - 进程峰值内存。
- **全景**：试一帧等距柱状投影的全景相机。EEVEE 不支持就如实写“不支持”，不改用 Cycles。
- **线稿**：线稿管线已经存在就测开和关两种；不存在就写“暂无，待 P3-D2”。
- **换算**：
  - 单帧耗时 ≤ 33 ms 记为“可能实时 30 fps”，≤ 16 ms 记为“可能实时 60 fps”；
  - 并写明这只是后台单帧渲染的近似，不等于视口或实时引擎的真实帧率；
  - 再换算每分钟 24 fps 成片需要多少分钟。
- **参数**：
  ```json
  {"engine":"EEVEE","resolutions":[[854,480],[1280,720],[1920,1080]],"warmup_frames":2,"measured_frames_min":10,"max_frames_total":300,"max_render_wall_s":1800}
  ```
- **不得做**：不用 Cycles，不跑 Godot（D-009 挂起中），不下载资产，不和 MLX 训练同时跑。

### P3-A8 独立复核 P3-A7

需要：code → 建议执行者：不能是 P3-A7 的作者 · 依赖：P3-A7 · GPU：轻量

- 用相同参数独立重跑 854×480 和 1920×1080 两档，覆盖两个场景。中位数和 P3-A7 相差超过 25% 的，要找出原因（热身方式、后台负载、设置不同）。
- 核对：确实没用 Cycles；热身和取样方法和卡上一致；换算公式正确。
- 只读复核，不改源码。报告放 `reports/V-P3-A7/`。

### P3-E4 独立复核 P3-E1（世界指令协议 v0）

需要：code、math → 建议执行者：不能是 P3-E1 的作者（claude） · 依赖：P3-E1 · GPU：无

- **重跑**：执行 `reports/P3-E1/check_world_command_v0.py contracts/drafts/world_command.v0 <AWZ 根目录>`，核对输出和 `reports/P3-E1/check-output.txt` 一致。
- **对抗审查**，逐条找协议漏洞：
  - 时间线下标漂移时，`test` 前置能不能拦住；
  - 两个指令基于同一 revision 并发提交；
  - 预览令牌被篡改或过期；
  - 提交写到一半崩溃，HEAD 是否仍指向上一个有效 revision；
  - 撤销一条之后又被别人改过的指令；
  - `presentation` 类指令通过编译副作用改到世界状态摘要；
  - `effective_from_tick` 边界恰好落在一个事件上。

  每条写“协议已覆盖 / 需要补充 / 无法判断”，并给出理由。
- **核对**：四个派生摘要的切分（WORLD_COMMAND §2.3）和编译器实际输出的键是否完全对应，有没有漏掉的键。
- 只读复核，不改源码。报告放 `reports/V-P3-E1/`。


### P3-E5 / P3-E6 统一变更v1纯CPU合同校验（Codex，2026-10-15）

- E5：依赖P3-E3已验收；只在python/animeworld/world_change/contract.py、__init__.py、tests/world_change/test_contract.py、reports/P3-E5/实现结构/精确来源摘要/单族/类别路径/外部版本前置等纯函数校验。持久op参数逐一对照Hub实际service.py，关联仓库只读。不做真实提交、DB、令牌签发或第二份持久世界权威。
- E6：verifies awz.P3.E5，非历任作者，只写reports/V-world-change-v1-contract/，独立重建合同并至少5个新不利反例，不能仅复跑作者自测。
- 完整提示与验收：AinerRelay/reports/coordination/codex-lead-20261015-172550/worldchange-implement-prompt.md、worldchange-verify-prompt.md；设计依据docs/design/WORLD_CHANGE_PROTOCOL.md。两项只CPU、不导入MLX/ORT/模型、不渲染/下载/安装/付费/提交推送/删除。不能把fixture通过当真实世界提交或跨仓E2E成立。

## W 轨结案（awz.V9.C1，2026-10-16，Claude）

- **W1（T07/T08）**：已结案。
  - 预算合规；Gate B 未过；研究候选不进生产；停训。
  - 证据：`reports/T08/report.md`、`reports/V-T08/report.md`。
- **W2（T09，线稿编码器）**：不开工，划归美术专项。以后若做，按美术工具卡登记，不再挂在 W 轨或 Gate C 名下。
- **W3（RSSM）**：停，不开工。
- **迁移登记**：`reports/V9-C1/w_track_registry.json`，只记引用与 SHA，原文件不动：
  - 生成器与评测器 → 考场素材（awz.V9.B3）；
  - 规则基线与 W1 检查点 → AinerZero 对照基线；
  - W1-data-v11 的 final 已用掉，不得再当 final。
- 总表中 W0 及其复核 V04 的状态不在本卡处理。
