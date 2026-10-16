# 任务 ainerzero.V9.B2：【代码】六个可替换接口与假实现 + 合同测试（新目录 src/ainerzero/v9/）

- 需要：code → 建议执行者：任意
- 项目：AinerZero · V9 v9 落地：NeuroGeometry × H-JEPA 世界脑（P0 无训练） → 轨道 B 协议与可替换接口（P0） → 第 2 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AinerZero`（先 cd 到这里）
- 关联目录（只读）：`/Users/mac/AinerWorkFlow/AnimeWorldZero`——AWZ 评测包（E-0/E-1 起使用，只读）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：ainerzero.V9.A1（accepted）、ainerzero.V9.A5（reported）
- 先读：`/Users/mac/AinerWorkFlow/AinerZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AinerZero/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/spec/AinerWorkFlow_v9_RFC.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`
- 文件范围（只改这些）：`src/ainerzero/v9/`、`tests/v9/`、`reports/V9-B2/`

## 任务说明
按 ARCHITECTURE_V9 r3 §3 实现 WorldBrainAdapter、GeometryCore、TimeScaleAdapter、SpatialMemory、PerceptionEncoder、HierarchicalPlanner 的接口与假实现，以及合同测试：只接受 ObservationPacket（遇快照或真值字段拒绝）；GeometryCore 的群运算满足结合律、逆元、exp∘log 恒等、协方差对称正定、重力方向显式；显式 dt 与层级对齐；SpatialMemory 写入不改任何网络参数、度量层随自运动等变变换、final 分区不可写；外部预训练编码器必须声明来源与许可；规划每级有预算与回退。GeometryCore 的真实实现由 ainerzero.V9.G1 负责，本卡只做接口与假实现。不改现有 learning/runtime 代码，不导入 MLX。

研究原则：生物启发只是架构假设，数学是可检验的计算描述，神经网络是实现工具，三者不能互相替代；唯一成功标准是受限观察下用更少经验、更少计算在更多陌生世界里做出可靠时空预测与行动。

r3 增补：GeometryCore 接口加 `canonicalize(x, belief)` / `decanonicalize(y, belief)`，合同：二者复合为恒等，且 `canonicalize(g·x, g·belief) = canonicalize(x, belief)`（真实实现归 ainerzero.V9.G3，本卡只做接口与假实现）；PerceptionEncoder 接口加 `token_policy()`，声明是否启用 RLT 及阈值，启用时报告 token 保留率（实现归 ainerzero.V9.T8）。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- 按 ARCHITECTURE_V9 r4 §3 实现**七个**接口（r3 六个 + `UpdateScheduler`：mark_dirty/dirty_set/update/fallback_reason）。
- `WorldBrainAdapter.step(payload)` 只吃 ObservationPacket/v1.1 的 payload（含 time 白名单），拒绝整个信封与快照。
- GeometryCore 按 r4 §4 约定段：T_AB 方向、右扰动、Adjoint 协方差、规范与锚点；canonicalize 只接受点/对象向量/地图坐标。
- SpatialMemory：每条记忆带编码器版本，版本不符拒绝解释；`promote` 到 SLOW 必须附独立测试证据。
- TimeScaleAdapter：`macro_action(level, actions)` 按 r4 §4 式 3 的登记聚合规则。

## 通用约束（v9，ADR-0012）
- 纯 CPU；不训练、不导入 MLX/ORT/模型；不下载、不安装、不付费、不提交推送、不删除。
- 只改文件范围内的文件；他人未提交改动不碰；原报告与失败证据保留。
- 所有判定用断言，脚本真实非零退出；附“故意改坏必须变红”的对照。
- 报告写实际命令、输入与源码 SHA、临时目录、失败与未验证项；测试通过不等于能力通过。

## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
合同测试全过；每条合同有反例；改坏接口测试变红

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat ainerzero.V9.B2 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report ainerzero.V9.B2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release ainerzero.V9.B2 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report ainerzero.V9.B2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release ainerzero.V9.B2 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release ainerzero.V9.B2 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
