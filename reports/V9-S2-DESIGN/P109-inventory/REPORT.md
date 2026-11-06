# S2 可行性盘点报告（ainerzero.V9.P109）

## 1. 逐条盘点结论与证据

1. **闭环步进**：**否（当前仅支持静态重放）**。
   - 证据：AWZ `python/animeworld/exams/scenarios.py#L18-L44` 硬编码 7 步轨迹 `[(0,0)..(0,0)]`；`python/animeworld/exams/packets.py#L58-L83` 的 `emit_stream` 仅遍历静态 `world.frames`。
   - 改动：无需修改 AWZ 源码，在 AinerZero 编写交互封装 `step(action)`，结合 `visibility_from` 与 `HandleAllocator`，约 90–120 行。
   - 隐藏随机性：**无**。`python/animeworld/sensing/noise.py#L19-L48`（CounterNoise）与 `scenarios.py#L207-L208` 均为独立派生 RNG，完全可复现。
2. **长回合**：**不可行**。
   - 证据：最大步数受限于静态帧数（当前固定 7 步）；场地尺寸仅 `5x4` 经 `scenarios.py#L215-L216` 随机微调为 `6x4`~`8x6`（仅 24~48 格），全图直径 ≤ 12 步，无法开展非重复绕圈的 ≥ 120 步长回合。
   - 房间数：**无多房间概念**。`python/animeworld/exams/world.py#L65-L76` 仅为单一平面网格与局部障碍点，无隔断墙或门拓扑。
   - 最短路径：`world.py#L94-L116`（`shortest_path`）支持 BFS 计算，但受限于超小尺寸，最远路径仅 ~10 步，**做不到 ≥ 40 步最短路径**。
3. **目标规格**：**能**。
   - 证据：`world.py#L186-L228`（`visibility_from`）与 `packets.py#L35-L41`（`_agent_frame`）均为纯函数，输入任意目标位姿 `(tx, tz, tyaw)` 即可计算可见实体与相对坐标，生成符合 ObservationPacket/v1.1 的目标观测。
4. **不规则 dt**：**生成器参数不支持，但底层机制已满足**。
   - 证据：`scenarios.py#L26` 硬编码固定 12 ticks；但 `packets.py#L84-L85`、`L103-L109` 按帧间差计算 `dt_ticks`、`dt_s` 及 `ego_motion`，真值按实际时长与位姿增量给出，可按步改变。
5. **分区**：**入口不支持单分区生成；final 需独立脚本**。
   - 证据：`src/ainerzero/v9/experiments/s1/awz_export.py#L44,L86` 绑定 `train` 和 `development` 一起生成；S1 第一阶段在 `src/ainerzero/v9/experiments/s1/awz_final_export.py#L1-L9,L30-L53` 独立生成 `final`（namespace 3）并断言与 train/dev 元数据互不重叠。S2 需修改入口参数解耦单分区。
6. **复用**：
   - RSSM：`src/ainerzero/learning/pilot_model.py#L74-L160`（`PilotPredictor`），接口为 `observe/imagine/decode`；但硬编码 8-byte 离散输入与 4 离散动作，**无法直接接** S1 的 3D 相对观测。
   - M2 记忆干扰：S1 封装的 `src/ainerzero/v9/experiments/s1/evaluation.py#L500-L565`（`evaluate_memory_probe`）输入模型与探测序列，可直接复用产出 `zero_state` / `history_paired` 对比。
   - 生命周期与预算：`src/ainerzero/v9/experiments/e1/commands.py#L1-L60` 与 `src/ainerzero/v9/experiments/e1/worker.py#L1-L60` 中的 `worker_lock` 排他锁、预检防重复执行（`EntryRefusal`）、`RunStore` 状态机与预算打断机制可完全复用到 S2。

## 2. 对设计稿 §2 的影响

- **已满足**：受限观察协议与纯函数渲染、不规则 dt 真值与时间戳处理、M2 干扰评测协议、生命周期锁与 RunStore。
- **需新写代码（约 350–470 行）**：
  1. 闭环步进环境封装器（约 100 行）；
  2. 单分区按需独立导出脚本（约 40 行）；
  3. 适配连续 3D 相对观测与动作的 S2 版 RSSM / JEPA 模块（约 250 行）。
- **做不到（改用 GridLab 的理由）**：
  S1 场地仅为 `6x4`~`8x6` 单间网格，**完全没有多房间布局拓扑**，几何上**绝对无法生成 ≥ 40 步的最短路径**，亦无法承载 ≥ 120 步的长回合。强制在单间微型场地内绕圈无法检验分层 H-JEPA 的长时域跨房间规划优势。**强烈建议依据 §2 第 18 行改用 GridLab（M2.B 轨道）的多房间格子世界**。
