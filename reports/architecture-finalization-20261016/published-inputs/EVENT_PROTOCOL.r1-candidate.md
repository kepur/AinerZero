# Event/v1 与 WorldSnapshot v1.2：世界事件、真实性层与权威几何（awz.V9.A8）

- 状态：一级设计 v1 **r1**（Claude，2026-10-16）· 待非作者复核（awz.V9.A9）
- r1 依据：Codex 对架构 r4 的非作者审议 ainerzero.V9.A6，F2（学习侧不得经调度路径读世界真值）与 F4（稀疏更新缺持续动力学与依赖闭包）。在复核前由作者自行退回修订；r0 原件归档于 `reports/V9-A8/r0-archive/`。schema 未改，只改 §4 与新增 §4.1–§4.3。
- 依据：
  - AinerZero `ARCHITECTURE_V9.md` r4 §8.2（v10 的 Event 接口并入）、§4 式 12（稀疏更新的脏集合种子）；
  - ADR-0012 修订五 §5.2；
  - NORTH_STAR §4 第 7 项（事件真实性分层，P3-I1 第 6 项）；
  - `docs/design/WORLD_CHANGE_PROTOCOL.md` §1（base 五元组）；
  - `docs/design/OBSERVATION_PROTOCOL.md` r1（WorldSnapshot v1.1、泄露规则）。
- 机器可读部分：
  - `contracts/v9/event.v1.schema.json`；
  - `contracts/v9/world_snapshot.v1_2.schema.json`；
  - 正反例 `contracts/v9/examples/event_v1/`；
  - 核对脚本 `reports/V9-A8/check_event_v1.py`。
- 只定契约，不改内核；现有内核事件怎样迁移见 §6。

## 0. 一句话

事件是世界里发生的事的**权威记录**：
- 每条事件说明谁、何时、因为什么、改了什么；
- 也说明它属于哪个真实性层：实际发生、角色以为、回忆、蒙太奇，还是纯镜头夸张。

事件只给世界系统、渲染、评测、回放用，**永远不进学生的观察**。

## 1. 字段

| 字段 | 规则 |
|---|---|
| `schema_version` | `awz.event.v1` |
| `event_id` | `ev-<tick>-<k>`：`tick` 是发生时的绝对 `sim_tick`，`k` 是同一 tick 内按内核确定性顺序的序号。重放时必须得到同一组 ID |
| `chain_index` | 在事件日志哈希链里的位置，从 0 起逐一递增 |
| `tick` | 绝对 `sim_tick`（120 Hz，ADR-0004）；不用故事内时间 |
| `source` | 登记来源：`kernel`（解析运动）、`physics`（刚体与接触）、`command`（统一变更信封提交的修订）、`mechanics_pack`（机制包，如门、变形）、`character_runtime`（角色运行时）、`presentation`（剪辑与镜头层） |
| `layer` | 真实性层：`actual`、`believed`、`recall`、`montage`、`camera_exaggeration` |
| `event_type` | 登记词表中的类型，点分小写，例如 `contact.begin`、`contact.end`、`object.appear`、`object.disappear`、`object.morph`、`action.executed`、`footstep.water`、`camera.slew` |
| `affected_ids` | 受影响的世界实体 ID 列表，去重。`state_effect = true` 时至少一个 |
| `state_effect` | 这条事件是否改变权威世界状态 |
| `believer_id` | `layer = believed` 时必填：谁以为发生了，填角色实体 ID；其他层不得出现 |
| `cause_ids` | 因果父事件的 `event_id` 列表，只能指向更早的事件：tick 更小，或同 tick 且 `k` 更小 |
| `base` | 发生时的版本基准五元组（`world_version`、`scene_id`、`revision`、`snapshot_sha256`、`source_sha256`），与统一变更信封同义同序 |
| `payload` | 类型相关的内容。**不得**含置信度、概率、推断量 |
| `evidence_ref` | `null` 或 `{uri, sha256}`。`source = command` 时必填，指向变更回执；`mechanics_pack` 时指向机制包定义 |

## 2. 真实性层与来源、状态影响的约束

| `layer` | 允许的 `source` | `state_effect` | 说明 |
|---|---|---|---|
| `actual` | `kernel`、`physics`、`command`、`mechanics_pack`、`character_runtime` | 可以为 `true` | 世界里真的发生；只有这一层能改权威状态 |
| `believed` | `character_runtime` | 必须 `false` | 幻觉、误解、梦；记在信念者名下，不改世界 |
| `recall` | `presentation`、`character_runtime` | 必须 `false` | 回忆或闪回 |
| `montage` | `presentation` | 必须 `false` | 蒙太奇、时间压缩 |
| `camera_exaggeration` | `presentation` | 必须 `false` | 速度线、变形镜头等纯呈现效果 |

推论：
- **呈现层事件永远不改世界状态**，美术层修改不改世界状态（NORTH_STAR §4 第 6 项）；
- 世界脑考的正是能不能分清这几层，所以层标签只在事件日志与评测通道里出现（ObservationPacket 泄露规则 L5）；
- 世界侧稀疏更新只用 `layer = actual` 且 `state_effect = true` 的事件作为种子。

## 3. 事件日志哈希链

与 WorldSnapshot 的 `event_log_hash` 定义一致：
- `h_0 = "0" × 64`；
- `h_k = sha256( h_{k−1} ‖ canonical(event_k) )`，其中 `‖` 是把 64 位十六进制字符串与规范 JSON 字节直接拼接；
- `canonical` 用 `sort_keys`、分隔符 `(',', ':')`、`ensure_ascii=False`、UTF-8。

快照的 `event_log_len = n` 时，`event_log_hash = h_n`。确定性重放必须得到同一条哈希链（v10 E3 的工程门）。

## 4. 与稀疏更新的关系（r1 改写）

稀疏更新有两个，读的东西完全不同，不能混用：

| | 世界侧（AWZ 运行时，awz.V9.B9） | 学习侧（AinerZero 信念更新，ainerzero.V9.P7） |
|---|---|---|
| 可以读 | 权威事件（Event/v1）、权威状态、碰撞体与关系 | 截至当前包的**允许观察**（ObservationPacket/v1.1 的 payload）、学生自己已执行的动作、自身信念 |
| 不得读 | — | Event/v1、世界实体 ID、隐藏接触、依赖图里的真值边、世界侧的脏集合与回退标志 |
| 正确性标准 | 与全量更新**状态哈希逐位一致**（在登记的确定性域内，§4.3） | 与全量信念更新**非劣**（ARCHITECTURE_V9 式 13） |

**为什么要分开**：如果学习侧调度直接用 `affected_ids` 或隐藏接触决定更新哪些对象，世界真值就会以“哪些对象被更新了”的形式间接进入模型，即使 ObservationPacket 本身干净。
- 世界事件只在世界侧使用；
- 学习侧只能从观察里推断“哪里可能变了”。

必要反例：两个世界在 `t` 以前给学生的观察完全相同、隐藏的未来不同，学习侧在 `t` 时刻的
- 模型输入；
- 调度出的更新集合；
- 能解析到的资产

都必须相同。

### 4.1 世界侧：哪些对象这一步必须更新

r0 只列了事件种子，漏了没有新事件但仍在演化的对象。r1 规定每一步的更新集合 `U_t` 由四部分组成：

1. **活跃集合 `A_t`**：本步状态会变的对象，包括：
   - 速度非零；
   - 受持续外力（未被支撑时的重力、风、推力等）；
   - 有计时器或脚本运动；
   - 处在未结束的接触或约束中。
2. **事件种子 `S_t`**：本 tick `layer = actual` 且 `state_effect = true` 的事件的 `affected_ids`，以及接触类事件的双方。
3. **新接触**：对 `A_t ∪ S_t` 做宽相碰撞检测，与全部对象比较，不只是邻居，找出本步可能新产生的接触。
4. **依赖闭包**：在约束图（接触、附着、支撑、包含）上，对以上集合取**传递闭包**，不是固定的 `k` 跳。长链约束（一排多米诺、叠放的箱子）必须整条进入。

不在 `U_t` 里的对象处于**休眠**：
- 状态必须**严格不变**；
- 或者能用登记的解析规则延迟求值，而且延迟求值与逐步更新逐位等价，例如匀速直线可以用闭式公式补算。
- 两者都做不到，就把它放进 `U_t`。

**回退**：出现以下任一情形就全量更新，并记录原因：
- 闭包占比超过 `f_max`；
- 宽相检测无法给出确定的上界；
- 校验时发现与全量不一致。

### 4.2 计时口径

稀疏路径的端到端时间必须包含：
- 活跃集合与种子的发现；
- 依赖图维护；
- 宽相与窄相碰撞检测；
- 回退；
- 输出与校验。

对照的全量基线要用**优化过的**全量实现，不能拿未优化的版本衬托。“5% 稀疏率下提速 ≥ 30%”是研究目标，不是承诺。

### 4.3 确定性域

“状态哈希逐位一致”只在登记的确定性域内承诺：
- Blender 版本与构建；
- Bullet 求解器设置；
- 步长；
- 平台（CPU 架构、操作系统）；
- 输入。

跨平台、跨构建的逐位一致在实测前不承诺。重放校验结果要写明所在的域。

## 5. WorldSnapshot v1.2

在 v1.1 之上，内嵌状态（`state.entities` 形式）可以带：
- 每个实体可选 `geometry_ref`（`{uri, sha256}`，几何资产）与 `collider_ref`（`{uri, sha256, kind}`，`kind` 取 `box`、`sphere`、`capsule`、`convex`、`mesh`）；
- 状态层级的 `relations`：权威结构关系 `{kind, a, b, since_tick}`，`kind` 取 `contact`、`attached`、`supports`、`contains`。

仍然**只放权威真值**：
- 不放置信度、证据评分或推断量；
- “看起来靠近”之类的推断关系不进快照，归世界脑信念。

`schema_version` 为 `awz.world_snapshot.v1.2`；v1.1 文件照旧有效。

## 6. 现有内核事件的迁移

现有内核只产生 `{"type": ...}` 形式的事件，例如 `footstep_water`、`camera_slew`、`body_accel`，见 `python/animeworld/kernel/curriculum_scenes.py`。迁移规则：

| 现有 | Event/v1 |
|---|---|
| `footstep_water` | `event_type = footstep.water`，`source = kernel`，`layer = actual`，`state_effect = true`，`affected_ids` 为踩水的角色与水洼 |
| `camera_slew` | `event_type = camera.slew`，`source = presentation`，`layer = camera_exaggeration`，`state_effect = false` |
| `body_accel` | `event_type = body.accel`，`source = kernel`，`layer = actual` |

迁移由 awz.P3.I2 改写后的卡执行，本稿不改内核。

## 7. 给后续卡

- **awz.P3.I2**：事件日志按本契约输出，并能导出全量与稀疏两种运行轨迹。
- **awz.V9.B9**：按 §4.1 的活跃集合、事件种子、宽相新接触与依赖闭包实现世界侧稀疏更新；按 §4.2 计时，按 §4.3 声明确定性域，以状态哈希逐位一致检验。
- **ainerzero.V9.P7**（学习侧，草稿）：只用 §4 表中学习侧允许的输入；补“同观察、异未来”反例。
- **awz.V9.A3 / B1**：Event 永不进 ObservationPacket；检测器对 `event_id`、`layer`、`affected_ids`、`cause_ids` 字段名报泄露（L2/L5 已覆盖 `layer` 与实体 ID）。

## 8. 未决

1. `event_type` 词表的登记位置：倾向放进机制包与内核的公共登记表，由 P3-I1 决定。
2. `believed` 层事件由角色运行时产生，依赖 P3-I1 第 5 项（角色运行），v1 只定格式。
3. 同 tick 内的序号 `k` 依赖内核的确定性遍历顺序。实现时要把遍历顺序写成登记规则，否则重放的 `event_id` 会漂移。
