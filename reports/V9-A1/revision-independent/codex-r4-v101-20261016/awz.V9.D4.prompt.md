# 任务 awz.V9.D4：【代码】锁定守卫：生成/修复的 WorldDelta 触碰锁定字段一律拒绝 + “为提分改锁定字段”对抗套件

- 需要：code → 建议执行者：任意
- 项目：AnimeWorld Zero · V9 v9 落地：世界系统侧（P0 契约 + P1 世界优先） → 轨道 D 9.1 3D 创作与评测平面 → 第 4 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AnimeWorldZero`（先 cd 到这里）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：awz.V9.D1（accepted）、awz.P3.E5（blocked）
- 先读：`/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`
- 文件范围（只改这些）：`python/animeworld/locks/`、`tests/locks/`、`reports/V9-D4/`

## 任务说明
在 E3 统一变更信封（base_revision、scope、locks、WorldDelta）的校验路径上实现锁定守卫：任何触碰用户锁定的角色（身份、形态版本）、镜头（机位、EDL 条目）、剧情事件（世界事件、实际发生层）的变更一律拒绝，错误码与原因可读，**与任何评分无关**；评测流程只读，不得发起修改。对抗套件：模拟“修复智能体”为提高视觉评分改锁定字段的 ≥10 种手法（直接改、改别名、拆成多条、借 add 覆盖、改引用对象、改上游依赖、改时间使锁定事件移位等），全部必须被拒。

参考（已核 2026-10-16）：github.com/QwenLM/BlenderWorld（MIT；223 任务、2,651 条加权二元判据；评分 50% 判据 + 50% 八个画质维度；结构判据由场景检查、视觉判据由 VLM，分路且结构结论不得用视觉猜测顶替；缺交/失败计零；每次新鲜渲染）。官方评测需 Linux、Blender 4.2.10、Claude Code CLI 与付费视觉接口——本项目不照搬环境，只吸收方法。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- 版本基准统一用 ainer.world_change/v1 的 base 五元组（world_version、scene_id、revision、snapshot_sha256、source_sha256）；锁定摘要算法与场景评测协议 base.locked_digest 一致。

## 通用约束（v9.1，ADR-0012 修订二）
- 不训练、不导入 MLX/ORT/模型；不下载、不安装、不付费、不提交推送、不删除。
- 只改文件范围内的文件；他人未提交改动不碰；原报告与失败证据保留。
- 所有判定用断言，脚本真实非零退出；附“故意改坏必须变红”的对照。
- 报告写实际命令、输入与源码 SHA、临时目录、失败与未验证项；测试通过不等于能力通过。

## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
≥10 种提分改锁手法全拒；合法未锁定修改不误拒；改坏守卫测试变红

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat awz.V9.D4 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report awz.V9.D4 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release awz.V9.D4 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report awz.V9.D4 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release awz.V9.D4 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release awz.V9.D4 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
