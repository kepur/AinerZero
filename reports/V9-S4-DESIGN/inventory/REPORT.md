# S4（对象交互与持久身份）可行性盘点

只读盘点，2026-11-09。给 S4 设计提供事实基础，**不是设计稿，不授权任何运行**。

- 代码基线：AinerZero `0bfd749`（工作区有他人未提交改动，未触碰），AWZ `2b0d4f2`（只读）。
- 实测脚本：`reports/V9-S4-DESIGN/inventory/measure_inventory.py`，结果 `metrics.json`（同目录）。下文数字都能在 `metrics.json` 对应字段找到。
- 没做的事：训练、MLX/GPU、下载、改源码和测试、写 `artifacts/`、提交。没有运行 S1、E1 的 verify 或 worker。只读了 S1 和 E1 的 train 分区，没碰 `final-sealed`、`raw/*/final`、`sealed_final`。账本先复制到临时目录再打开。

## 结论摘要

1. **现有世界里，只有 GridLab-v1 能产生真正需要持久身份的重现**（物体移动、外观相同、隐藏多步）。但默认 16 步的样本太短，纯遮挡也很少，长回合里绝大多数是出视野。
2. **S1 的 E3 考题没有身份问题。** 每回合 5 步，只有 1 个对象可见（诱饵永远在视野外），间隔恒为 2 步。500 个重现事件，难例 0 个。
3. **E0 的 `occlusion_pass` 实际不遮挡。** 200 条序列 0 帧被完全遮挡，球在 45 帧内根本走不到墙（末帧 x 最大 −0.138，墙在 |x| ≤ 0.1）。场景名不能当证据。
4. **代码里没有任何对象槽、SSM、图网络实现**：`src/` 下 grep `EGNN`、`GNN`、`SSM`、`slot_attention` 零命中（S1 的 detection slots 只是观察排序）。`UpdateScheduler` 只有 fake。
5. **「Blender 合成场景」不存在**：E0 只算物理不渲染，T6 标定 fixture 明确写了 `NOT Blender`。T10 卡面的标定路径目前走不通。
6. **E2b 按卡面做不了。** S1 学生没有对象节点。100/1000 对象能生成（GridLab2D 1000 个物体 63 ms/步），但学生每步平均只看到 4–6 个，1000 个物体的世界里随机游走 48 步只见过 17–28 个。
7. **T10 的代码和权重其实已经下载并校验**（`ainerzero.V9.T49` 已验收，SHA 实测吻合），RESEARCH_LOG 第 2961 行说 T10/T12 依赖下载，这部分已过时。但没有可运行环境（缺 `hydra-core`、`iopath`）。

## 「重现」的定义

对象 k 在第 a 步可见，第 a+1 到 b−1 步全部不可见（`gap = b−a−1 ≥ 1`），第 b 步再次可见。

- **不算事件**：首次出现；一直可见的对象；消失后回合结束没回来的对象（单独记 `censored_at_end`）。
- **`cause`**：隐藏区间全是遮挡 = `occluded`，全是视野外 = `out_of_view`，否则 `mixed`。
- **`moved`**：对象在 a、b 两步的真值位置不同。
- **`agent_did_not_move`**：智能体在 a、b 两步位置相同。这一项对应 S3 的教训（原地转头不算回访）。
- **`ambiguous_appearance`**：第 b 步有另一个此前见过的同外观对象，只看外观分不出来。
- **`hard` = `moved` 且 `ambiguous_appearance`**：真正需要持久身份的子集。

可见性直接来自各世界自己的判定或观察内容（S3 从学生观察向量解码）。E1 没有可见性字段，用射线几何计算（见第 1 节末）。

**校验**：`analyze_episode` 有 6 个手工断言（脚本外）。GridLab-v1 的纯遮挡事件数与生成器自带的 `detect_events` 计数在 7 组配置里完全相等（如 `open_128`：54 = 54，`6balls`：119 = 119）。S1 的 500 个事件逐个核对句柄全部重发。

## 1. 哪些世界真有可追踪的多对象

| 世界 | 对象数（实测） | 遮挡 | 对象 ID 怎么来 | 学生能看到什么 |
|---|---|---|---|---|
| S1 检测槽（AWZ 考场，磁盘数据） | navigation 1、time 1、relation 4、e3 2；单步最多 3 个检测 | relation 有；其余无 | 世界侧写死字符串 `obj.chair`、`obj.target`（`AWZ python/animeworld/exams/scenarios.py:24,169-170`） | 每步检测的类别、相对位置、置信度和句柄 `h-n`；**不含实体 ID**（实测 800 个包的键集合 `packet_identity_keys = []`）。S1 模型特征丢弃句柄，只用位置、类别和置信度（`src/ainerzero/v9/experiments/s1/data.py:650-705`），槽位按 (x, z, 类别) 排序，槽号不带身份（`s1/spec.py:466,477`） |
| GridLab-S3 内容格 | 8 个，位置固定，只换 token | 3×3 视野内被挡的格记 UNSEEN；实测重现 100% 出视野 | 格子坐标本身（`s3/content.py:18-37`） | 视野内格子的 token one-hot，无坐标（`s3/world.py:224-298`） |
| GridLab-v1（S07） | 默认 3 个（2 球 + 1 箱）；`swap_lane` 2、`occlusion_walk` 1；可调到 72 个 | 有：墙、柱、闭门不透明（`environments/gridlab_v1.py:36,100`） | `uuid5(world_id, "object:i")`（`gridlab_v1.py:260`），只在私有状态（`:168-174`） | 5×5 自我中心视野、80×80 RGB、匿名检测（相对坐标 + 外观），外加**绝对 `agent_xy`**（`:152-166`）。同外观对象 RGB 无差别 |
| GridLab2D（S06） | 默认 3 个；可达 1000（80×80，实测） | 有：墙、柱（`environments/gridlab2d.py:80-93`） | 同上（`:193`） | 窗口内匿名检测（绝对坐标），无 ID（`:121-140`） |
| AWZ E0 刚体（E1 使用） | 活动体 1–3 个，静态体 0–1 个（实测 1000 条 train） | 名义上有；实测见下 | 体名字符串 `OccludedActor`、`BoxTop` 等（`AWZ e0/scenarios.py:291` 等） | **全部活动体的全状态，每帧都给，含体名**（实测学生文件的键含 8 个体名）；另含 `scenario_type`、`sequence_id` |
| AWZ E2a 稀疏世界 | 100 / 1000（实测） | 只有 `occlusion.change` 事件，无几何遮挡 | `o00000` 序号（`AWZ sparse_update/world.py:466`） | **看不到**：世界侧参考世界，没有传感出口 |
| Blender 合成场景 | **不存在** | — | — | E0「只算物理不渲染」（`AWZ e0/blender_worker.py:5`，架构 §8.3 E0）。T6 标定 fixture 的 `render_kind` 明写 `CPU analytical ray-box intersection; NOT Blender`（`reports/V9-T6/r2-calib-fixtures/manifest.json`，6 个解析房间，无对象 ID）。grep `pass_object_index`、`cryptomatte` 零命中 |

**实测（GridLab 系列 120 回合/配置）**：

| 配置 | 对象 | 可见占比 | 事件/回合 | 遮挡/视野外/混合 | 间隔中位（p90，最大） | moved | hard | hard 且 gap≥8 | last-seen 跟踪重现正确率（登记参数 / 不设门限和保留上限） |
|---|---|---|---|---|---|---|---|---|---|
| `open` 16 步 | 3 | 0.206 | 1.16 | 3 / 130 / 6 | 3（9，15） | 81 | 61 | 13 | 0.669 / 0.856 |
| `door_room` 16 步 | 3 | 0.141 | 0.73 | 1 / 80 / 7 | 2（7，11） | 43 | 10 | 1 | 0.807 / 0.909 |
| `swap_lane` 16 步 | 2 | 0.529 | 8.00 | 480 / 480 / 0 | 2（3，3） | 480 | 480 | 0 | 0.500 / 0.500 |
| `occlusion_walk` 16 步 | 1 | 0.706 | 2.00 | 240 / 0 / 0 | 2（3，3） | 0 | 0 | 0 | 1.000 / 1.000 |
| `open` 128 步（非登记） | 3 | 0.183 | 14.96 | 54 / 1618 / 123 | 7（18.6，107） | 1090 | 965 | 527 | 0.201 / 0.761 |
| `door_room` 128 步（非登记） | 3 | 0.133 | 9.20 | 26 / 986 / 92 | 3（11，103） | 485 | 216 | 55 | 0.359 / 0.867 |
| `open` 128 步、6 球（非登记） | 6 | 0.189 | 36.73 | 119 / 3938 / 350 | 7（20，119） | 3104 | 3098 | 1706 | 0.149 / 0.365 |
| GridLab-S3，360 步，100 回合 | 8 | 0.037 | 12.62 | 0 / 1262 / 0 | 78（159，350） | 0 | 0 | 0 | 不适用（格子不动） |

要点：

- `swap_lane`、`occlusion_walk` 几何写死，种子只命名世界（`gridlab_v1.py:205`），120 回合实际是 **1 个样本**。
- `open` 128 步的重现里纯遮挡只占 3.0%（54/1795），绝大多数是走出 5×5 视野。架构 E3 的表述是「出视野后重新出现」，门槛写的却是「遮挡后 ID 保持」，设计时要定清口径。
- S3 的 1262 个事件里 582 个（46%）智能体没挪位置，只是转头。S3 是「地点绑定内容」，对象不动，hard 为 0，不能当身份数据。
- **登记参数的 last-seen 基线成绩低，主要因为保留窗口只有 8 步**（`learning/gridlab_tracking.py:31`）。去掉门限和保留上限后，3 物体世界就到 0.76–0.87，说明这些世界对简单启发式并不难。6 球同外观时降到 0.365，这才接近持久身份的难度。

**S1 磁盘数据（2000 个 train 世界，实测）**：

| 族 | 步数 | 实体 | 永不可见的实体 | 重现事件 | 间隔 | hard |
|---|---|---|---|---|---|---|
| navigation | 7 | 1 | 500（全部） | 0 | — | 0 |
| time | 4 | 1 | 0（一直可见） | 0 | — | 0 |
| relation | 3 | 4 | 0 | 0（500 个对象消失后没回来） | — | 0 |
| e3_identity | 5 | 2 | **500（诱饵永远在视野外，方位 63° > 45°，`scenarios.py:170`）** | 500 | 恒为 2 步 | 0 |

e3 族全程只有 1 个可见对象，单步检测最多 1 个。AWZ 生成器重采 100 个世界结果相同，3 条流过了 A3 校验。

**E1 原始序列（P 族 train 1000 条，实测）**：

| 场景 | 活动体 | 完全遮挡帧 | 重现事件 | 备注 |
|---|---|---|---|---|
| `occlusion_pass` | 1 | **0 / 9000 帧** | 0 | 开头 927 帧在画外。末帧球 x 中位 −0.99、最大 −0.138，墙在 \|x\| ≤ 0.1（`e0/scenarios.py:277-295`），根本没走到。墙从相机看是侧面（厚 0.2 m），比球窄 |
| `box_stack` | 3 | 1143 / 27000 | 45（全部被挡，间隔 3–29 帧） | 外观按形状算，hard 为 0；另 28 个对象被挡后没回来 |
| `ramp_roll` / `table_slide` / `bounce_collision` | 1 / 1 / 2 | 0 | 0 | — |

E1 可见性是脚本算的：球面 9 个采样点，对静态非地面体和其他运动体做射线–OBB 测试，全部被挡才算遮挡。相机外参来自 raw metadata，尺寸由 `ScenarioBuilder` 重建，与 raw 位置 0 处不符。**盒子用内切半径，遮挡会略多算**，这只影响 `box_stack`，不影响 `occlusion_pass` 的结论。

## 2. 现有对象级表示

| 东西 | 位置 | 性质 |
|---|---|---|
| 对象槽 / Slot Attention、SSM（S5 类）、EGNN、任何图网络 | grep `slot_attention`、`EGNN`、`GNN`、`SSM` 零命中；S5/EGNN 只在 `docs/research/V9_RESEARCH_SURVEY.md:20,47` 调研中 | **不存在** |
| S1 检测槽 K = 6 | `s1/spec.py:466`、`s1/data.py:51,650-705` | 真实的数据特征，但只是观察编码，无跨帧身份 |
| S1 度量图、拓扑图记忆 | `s1/arms.py:87,174,483` | 真实实现，但是隐空间栅格 + 地点图，**不是对象节点**（P7 卡面搁置原因） |
| E1 多体物理先验 + 残差网络 | `e1/prior.py`，`e1/arms_net.py:25,65` | 真实实现。多体耦合来自解析先验，网络是按体的 MLP（`DEFAULT_NUM_BODIES = 1`），靠体名对应，全状态输入，无部分观察 |
| GridLab 跟踪基线 | `learning/gridlab_tracking.py:105-169`，`gridlab_tracking_eval.py:49-115` | 真实的**非学习**基线和评测器；测试明确未接入训练或运行时（`tests/test_gridlab_tracking.py:244`） |
| `EntityTrack` / `TrackState` / `IdentityHypothesis` | `core/spacetime_records.py:254-316` | 真实的数据契约，无模型 |
| `Fragment.object_keys` | `v9/interfaces/types.py:422-430` | 接口字段；只有 fake 存储检查（`v9/fakes/spatial_memory.py:181`） |
| `UpdateScheduler` | `v9/interfaces/scheduler.py:30-51` | 接口 |
| `FakeUpdateScheduler` | `v9/fakes/scheduler.py:58-160` | **桩**：更新就是 `belief[node] + 1`（`:144`） |
| `WorldBrainAdapter` | 接口 `v9/interfaces/world_brain.py:28`；`v9/fakes/world_brain.py:15` | 接口 + 桩，只传播位姿信念，无对象 |
| `PoseBelief`、GeometryCore、规范化 | `v9/interfaces/types.py:190`，`v9/geometry/{canonical,lie,pose_graph,belief}.py` | 真实数学库（SE(2)/SE(3)、规范化），只到位姿层，对象向量可规范化（`canonical.py`），无对象网络 |
| 考场 IDF1 | `AWZ exams/metrics.py:19-58` | 真实，但 README 写明是实体 ID oracle 参照，不是学生 track-ID 评测器（`AWZ exams/README.md:19-20`） |

ID 切换指标在架构 §5 列为 S1 指标（`ARCHITECTURE_V9.md:192`），但 `s1/metrics.py`、`s1/evaluation.py` grep 零命中，未实现。

## 3. E3（遮挡后持久身份）需要的数据

**有没有现成场景产生消失再出现：** 有，见第 1 节。可直接用的只有 GridLab-v1 的 `open`、`door_room`（16 步太短，要拉长），`swap_lane` 是固定脚本。AWZ E3 考题只考「句柄是否重发」，不考身份（`AWZ exams/generator.py:68-70`），题库 2 个 e3 世界（`:77,81`）。E1 数据不可用。

**真值 ID 从哪来：** GridLab 是 `object_id`（私有状态）。AWZ 考场是 `truth_packets[].handle_to_entity`（`AWZ exams/packets.py:211`），只进封存通道。

**防止学生接触真值 ID（已有）：**

- 字段黑名单：`entity_id`、`object_id`、`track_id`、`instance_mask` 等（`v9/interfaces/validation.py:76-82`，`AWZ docs/design/OBSERVATION_PROTOCOL.md:198`）。
- 句柄重发：`AWZ sensing/handles.py:28-41`，流上检查 `AWZ protocols/v9/cross_checks.py:216-287`，协议 `OBSERVATION_PROTOCOL.md:99-102`。
- 真值分离：AWZ `packets.py:191-215`，S1 只有 `load_truth_view` 读真值（`s1/data.py:14`），GridLab 用公开键白名单（`gridlab_tracking.py:29,35-40`），有私有状态篡改不影响输出的测试（`tests/test_gridlab_tracking.py:92`）。

**缺口：**

- E1 学生文件含体名（8 个，语义上就是身份）。
- GridLab-v1 公开观察有绝对 `agent_xy`（`gridlab_v1.py:13,162`）。这不是 ID，但和相对坐标相加就得到绝对位置，比 S1、S3 的自我运动口径宽松，要先定观察口径。
- 新世界要写自己的「无泄漏」测试和未来帧变异测试。S3 的教训是 `get_token_map_at_step(t+1)` 这种偷看未来的改动，11 项测试全过（`RESEARCH_LOG.md:3002`）。

## 4. E2b（学习侧稀疏更新）要什么才能跑

**信念节点怎么定义：** 目前没有定义。接口只要求节点是字符串（`scheduler.py:71-75`），`bn-` 前缀只在 fake 里（`fakes/scheduler.py:35`）。合理定义是「学生自己维护的轨迹/对象假设」，它依赖第 3 节的数据关联，所以 **E2b 依赖 E3 的关联能力先成立**。

**`scheduler.py` 接口缺什么：**

1. 节点生命周期：没有新建或退役节点的方法，而对象消失和新检测是常态。
2. 信号到节点的映射：`observation_change` 的 `node` 由谁算？这正是数据关联（`types.py:919-920`）。
3. 依赖图的来源：`dirty_set(belief_graph)` 只接收现成的图（`scheduler.py:38`），没有规定谁按信念生成，也没有防止用世界图的硬约束（fake 只查键名，`fakes/scheduler.py:84-89`）。
4. `update` 的合同：`belief: Mapping` 返回 `Any`（`scheduler.py:42`），对可微模型的部分更新没有定义（哪些节点过网络、批处理、梯度）。
5. 不确定性：`belief_uncertainty` 要每节点数值（`fakes/scheduler.py:90-97`），现有学生都没有对象级不确定性。
6. **`f_max` 口径不一致**：式 12b 是「扩展比例」（`ARCHITECTURE_V9.md:162`），AWZ 世界侧也是比例 0.35（`AWZ sparse_update/scheduler.py:46`），fake 却是绝对节点数（`fakes/scheduler.py:62,119-122`）。
7. 成本记账：式 13 和 E2 要求报端到端时间、回退率，接口无此项。
8. 配对执行与「同观察、异未来」反例（§8.6，`ARCHITECTURE_V9.md:363`）没有 harness。非劣检验可复用 `s3/analysis.py:29` 和 `s2/stats.py:90` 的配对 bootstrap。

**E2 登记的 100/1000 对象（`ARCHITECTURE_V9.md:326`）现有世界能否达到（实测）：**

| 世界 | 100 | 1000 | 说明 |
|---|---|---|---|
| S1 / AWZ 考场 | 否 | 否 | 最多 4 个实体，K = 6 |
| GridLab-v1 | 否 | 否 | `SIZE = 11` 写死，70 可以，100 报 `too many entities`（`gridlab_v1.py:243`） |
| GridLab-S3 | 能（100 个内容格） | 否（只有 443 个连通格） | 对象不动 |
| GridLab2D | 能 | 能，63 ms/步 | 学生每步平均看 3.6–5.5 个，最多 11 个；变化率可用 balls/boxes 调（N = 100 实测 5.09%、19.98%，N = 1000 为 4.78%、19.39%）。**学生覆盖**：随机游走 128 步见过 25–28/100；48 步只见过 17–28/1000 |
| AWZ E2a 世界 | 能 | 能 | 世界侧，无传感出口，学生接触不到 |

现有跟踪基线的关联是穷举（`gridlab_tracking.py:92`），组合数 (k+1)^k，k = 6 实测 52 ms，大规模不可用。

**结论：** P7 卡面写的「在 S1 的学生上」不可执行。要跑 E2b，至少要有：对象级学生、重新定义「对象数」的口径（世界对象总数还是学生见过的节点数）、一个学生能覆盖足够多对象的世界。

## 5. 依赖

| 依赖 | 状态 | 证据 | S4 第一阶段是否必需 |
|---|---|---|---|
| SAM 2.1 tiny（代码 + 权重） | **已下载**，SHA 实测吻合，155,908,064 字节 | `envs/teachers/t10/LICENSE.provenance.json`，relay `T49` accepted，`metrics.json:t10_assets` | 否。受限结构观察不用 |
| BootsTAPIR v2 | **已下载**，SHA 吻合，218,886,140 字节 | 同上 | 否 |
| TAPNext / TAPNext++ | **未下载**（T47 列为 2.36 GB 备选） | 磁盘无 | 否 |
| SAM 2.1 运行环境 | **未就绪**：`.venv-t6` 有 torch、torchvision、omegaconf，缺 `hydra-core`、`iopath`（`sam2/setup.py:29-30`）。`sam2` 和 `tapnet` 未安装进任何 venv | 本机 `find_spec` 检查 | — |
| SAM 2.1 权重格式 | **未确认能否直接加载**：盘上是 safetensors（469 键，前缀 `mask_decoder.`），官方 `build_sam.py:166` 用 `torch.load(...)["model"]`，模型属性是 `sam_mask_decoder`（`sam2_base.py:223`），`.venv-t6` 也没有 `transformers` | safetensors 头部读取 | — |
| RGB 输入与带 ID 的合成视频 | **不存在**。教师需要视频；GridLab-v1 有 80×80 RGB，但这个分辨率对 SAM 2 是否有意义未确认 | 第 1 节 | 视觉臂才需要 |
| Blender | 已安装 5.2.2 LTS（`/Applications/Blender.app`），和 E0 用的一致 | `--version` | 只有走渲染路线才需要 |
| Genesis | 未安装（awz.V9.B7） | 架构 §7.4 | 否 |
| MLX | `.venv`、`.venv-ainerzero` 已有 | `find_spec` | 是（学生模型） |
| scipy / 匈牙利算法 | `.venv` **没有 scipy**，`.venv-t6` 有。EGNN 不需要 torch_geometric | `find_spec` | 自写约 50 行，或用 `.venv` 的 networkx（`.venv-ainerzero` 没有） |
| motmetrics / TrackEval | 未安装 | `find_spec` | 否，IDF1 自写 |

授权：10-20 的授权覆盖「既有任务的下载与隔离安装」（`AinerRelay/reports/coordination/codex-20261019-parallel/resume-20261020-downloads/AUTHORIZATION.md:3-4`）。T10 卡面仍是草稿，运行要按卡登记预算。**本盘点没有安装任何东西。**

## 6. 成本（账本副本与研究日志）

| 阶段 | 项目 | 墙钟 | 备注 |
|---|---|---|---|
| S1 第一阶段 | 13 个完成的训练 run，45630 优化步 | 活动 2936 s，墙钟 9543 s | **64 ms/步**；当时有 0.25 占空比，墙钟约 3.25 倍。数据生成 46 s（2200 世界） |
| S2 第一阶段 | 9 个训练 run，24813 优化步 | 5854 s 活动、5959 s 墙钟 | **236 ms/步，662 s/格**。数据 883 s，plan-select 1110 s，smoke 212 s。另有 2 次生成失败挂了 63319 s 墙钟（活动 0） |
| S3 dev1 | 18 个训练格 | 2033 s（含数据和评测） | **约 113 s/格**（`reports/V9-S3-PHASE1/DEV1-REPORT.md:7-9`）；步耗时 A0 1.9、A1 195、A2 3.7、A3 6.8 ms（`RESEARCH_LOG.md:3027`） |
| E1 第二阶段 | 18 个训练 run；r2 12 个 | 7602 s（422 s/格）；6373 s（531 s/格） | Blender 数据生成 3364 s / 2800 条 = 1.2 s/条。**E1 账本的 `active_seconds` 是预留量，不是实测**（active 12300 > wall 7602），只能用墙钟 |

本次实测的生成成本：GridLab-v1 含 RGB 0.23 ms/步，GridLab-S3 0.11 ms/步。5000 回合 × 128 步约 150 s，CPU。

**S4 第一阶段粗估（估计，未实测）：** 对象模型按 12 格（如 4 臂 × 3 种子），每格落在 S3（113 s）到 S2（662 s）之间：训练 0.4–2.2 小时，加探针、smoke 约 15 分钟，数据 ≤ 5 分钟，合计约 **0.7–2.5 小时**。对象数 N 增大时图网络每步按 N² 增长，**未实测**，设计时要先测步耗时再定预算（S3 的 P-g 探针做法）。

E2b：未确认，取决于设计（稀疏是否只在推理侧，要不要按规模和稀疏率分格）。上下界约 0.2–6.6 小时（6 格 × 113 s 到 36 格 × 662 s）。

## 对 S4 设计的影响

### 已满足，可直接复用

- **世界与匿名观察的范式**：GridLab-v1 的公开/私有分离、遮挡判定、`detect_events`。
- **跟踪基线和评测器**：`gridlab_tracking.py`、`gridlab_tracking_eval.py`（重现正确率、ID 切换、隐藏预测）。外观要转整数，本脚本的适配约 10 行。
- **防泄漏手段**：L2 字段黑名单、句柄重发语义、公开键白名单、私有状态篡改测试。
- **统计**：配对 bootstrap（`s3/analysis.py:29`，`s2/stats.py:90`）。
- **运行基础设施**：账本、共享锁、预登记结构（S3 共 2030 行源码 + 1675 行测试可作模板）。
- **几何**：SE(2)/SE(3)、规范化。
- **世界侧 E2a** 已验收（awz.V9.B9），不用重做。
- **E0 的接触真值**（`blender_worker.py` 每帧 `contacts`）可用于接触预测，但只有 1–3 个体、全状态。

### 要新写（估行数，含测试）

| 项 | 源码 | 测试 |
|---|---|---|
| GridLab-S4 世界：多个同外观移动体、可控遮挡体、可调变化率、足够长的回合、覆盖策略、事件标注 | 300 | 200 |
| 匿名检测观察编码（可选句柄重发）与批处理 | 120 | 80 |
| 对象槽 × SSM（显式 `dt`，跨帧关联） | 250–350 | 120 |
| 等变与非等变交互块（MLX） | 150–200 | 80 |
| 关联（可微训练项 + 匈牙利评测，无 scipy） | 100 | 50 |
| 指标：学生 track 的 IDF1、重识别、概率校准（ECE/NLL） | 150 | 100 |
| 预登记、运行器、探针（步耗时、oracle、无记忆、打乱负对照） | 300–400 | 150 |
| 真实 `UpdateScheduler`、节点定义、非劣 harness、同观察异未来反例（E2b，后做） | 300–400 | 200 |
| **合计** | **约 1700–2200** | **约 1000** |

### 做不到，以及原因

1. **在现有 S1 数据或 AWZ 考场上做 E3**：e3 族只有 1 个可见对象、5 步、间隔 2，没有身份问题可考。
2. **用 E0/E1 数据做遮挡重现**：`occlusion_pass` 实测不遮挡，序列只有 40–50 帧，学生文件还含体名。要用就得改场景重跑 Blender，而 E1 已收口。
3. **E2b 按卡面在 S1 学生上跑**：没有对象节点。要改卡、重新定义口径和预算。
4. **100/1000 对象的真实学生信念**（现有世界）：能生成的世界学生看不到大部分对象，看得到的世界达不到规模。要新世界加覆盖策略，或把「对象数」重定义为学生节点数。
5. **按 T10 卡面在「Blender 合成场景」上标定**：这种带实例 ID 的渲染数据不存在，要新建渲染任务（需渲染预算）。环境也还没装。
6. **同一个现有世界同时满足 S4 三道门**（未见对象组合与接触、遮挡后 ID、概率校准）：GridLab 是离散 2D，只有 C4 对称、2 种物体、无接触事件；E0 有接触和 3D，但无遮挡、无部分观察、无不确定观察。**等变图网络的连续对称性在 GridLab 上测不了**，要么分两条线，要么做一个连续位置的新世界。

## 实测与校验记录

- 复现（仓库根目录，账本副本放临时目录）：

```bash
PYTHONDONTWRITEBYTECODE=1 timeout 120 .venv/bin/python reports/V9-S4-DESIGN/inventory/measure_inventory.py --limit 90 --ledger-copies <含 s1/s2/e1p2/e1r2 副本的目录>
```

- 用时：完整一次 29.4 s，纯 CPU，主线程。调试 4 次 quick 共约 7 s，另一次完整运行 28.9 s，合计约 66 s，低于 120 s。脚本屏蔽了 `mlx`、`torch`、`jax` 导入（`imports_blocked` 全 false）。
- 写入核查：运行后在 AWZ `python/`、`contracts/`、`artifacts/v9/s1`、`artifacts/v9/e1`、`artifacts/locks` 下按修改时间查找，无新文件或改动。
- 复现注意：脚本依赖本机路径和磁盘数据。AinerZero 的 `tests/conftest.py` 等是他人会话的未提交改动，不是本次产生。

**未确认：**

- 对象图网络的每步耗时。
- SAM 2 / BootsTAPIR 的实际加载和吞吐。
- 80×80 RGB 对教师是否有用。
- E2b 的成本。
- `T47` 报告里的体积等数字来自二级报告，只核了 T49 的两个权重 SHA。
- `swap_lane` 与 `occlusion_walk` 各种子相同的结论来自源码注释（`gridlab_v1.py:205`）和计数恒定，未逐回合比对。
