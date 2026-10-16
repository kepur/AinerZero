# 任务 awz.V9.A3：【代码】WorldSnapshot/ObservationPacket 纯 CPU 校验器与泄露检测器

- 需要：code → 建议执行者：任意
- 项目：AnimeWorld Zero · V9 v9 落地：世界系统侧（P0 契约 + P1 世界优先） → 轨道 A 契约冻结（P0） → 第 3 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AnimeWorldZero`（先 cd 到这里）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：awz.V9.A2（accepted）
- 先读：`/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/spec/AinerWorkFlow_v9_RFC.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`
- 文件范围（只改这些）：`python/animeworld/protocols/v9/`、`tests/protocols/v9/`、`reports/V9-A3/`

## 任务说明
按 awz.V9.A2 的契约实现校验器与泄露检测器（新目录 python/animeworld/protocols/v9/），对任意 ObservationPacket 流判定是否含禁止字段、未来信息、绝对真值或快照哈希；给出逐字段原因。
测试覆盖：合法包、每类泄露各至少 2 例、噪声与可见性边界、dt 非法值；不改内核与编译器现有文件。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- 实现 contracts/v9/{world_snapshot.v1_1,observation_packet.v1_1}.schema.json 与 observation_leak_rules.v1_1.json；v1 只作历史。
- 规则作用范围：L10 只查 $.payload；实现 time_whitelist_consistent（payload.time 四项且逐项等于信封）。
- 正反例用 contracts/v9/examples/{world_snapshot_v1_1,observation_packet_v1_1}/，并复现 reports/V9-A2/r1/check_contracts_v1_1.py 的全部结论。

【A7 复核新增缺口（2026-10-16）】ObservationPacket 中可被模型触及的 URI/内容摘要（如 rgb.image.uri）必须按“截至本包 t_ticks”的 as-of 规则解析：不得指向 private/、评测通道、未来 tick 的资产或任何真值文件；解析器要有权限分区。补负例：uri 指向 private/future_tick_*.png、指向快照或 eval 目录、摘要对不上实际文件，都必须被拒绝；并在实际加载路径上测试，不只测字段。参考 reports/V-V9-A2-r1/codex-v101-20261016/future-reference-probe.json。

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
每类泄露都被拦并给原因；合法包零误报；改坏检测器测试变红

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat awz.V9.A3 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report awz.V9.A3 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release awz.V9.A3 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report awz.V9.A3 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release awz.V9.A3 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release awz.V9.A3 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
