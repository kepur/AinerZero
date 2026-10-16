# 任务 awz.P3.I2：【代码·数学】P3-I2 小房间世界运行切片（纯 CPU，不渲染）

- 需要：code, math → 建议执行者：任意（缺 math 的模型不要领）
- 项目：AnimeWorld Zero · P3 三期：v8 世界系统第一批（Blender 主路径、工具库、美术闭环） → 轨道 I 世界运行：交互运行、场景语义、机制包、多形态、角色运行（D-011） → 第 2 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AnimeWorldZero`（先 cd 到这里）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：awz.P3.I1（ready）、awz.V9.A8（claimed）
- 先读：`/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENT_TASKS.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0011-three-systems.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/NORTH_STAR.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`
- 文件范围（只改这些）：`python/animeworld/runtime/`、`tests/runtime/`、`reports/P3-I2/`

## 任务说明
按 `/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENT_TASKS.md` 的 P3-I2 任务卡执行（交付、内容、验收以任务卡为准）。先读任务卡上方的「P3 通用约束」和「P3 补充：世界运行与制作计划」两段，以及 docs/adr/ADR-0011-three-systems.md 和 docs/NORTH_STAR.md。报告用 AGENT_TASKS.md 中的执行报告模板，放到 reports/P3-I2/。不得改 python/animeworld/kernel/ 下的现有文件。边做边留接力点（relay_checkpoint 或 relay heartbeat --msg）。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- 事件日志按 Event/v1（awz.V9.A8，验收后）输出：event_id、tick、source、affected_ids、event_type、payload、evidence_ref、真实性层、因果父事件、所在修订。
- 为 E2a/E3 预留：同一运行可导出全量更新与稀疏更新两种轨迹，用于逐位比较状态哈希（比较本身归 awz.V9.B9）。

## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
七项逐项报成立/不成立/未验证且有证据；同源同日志哈希一致、改一条命令哈希变；快照重算与从头算一致；被拒命令不改状态；kernel 现有文件 sha 不变

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat awz.P3.I2 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report awz.P3.I2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release awz.P3.I2 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report awz.P3.I2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release awz.P3.I2 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release awz.P3.I2 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
