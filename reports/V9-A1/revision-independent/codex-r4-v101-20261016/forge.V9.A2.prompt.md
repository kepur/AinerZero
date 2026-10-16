# 任务 forge.V9.A2：【代码】ExperienceEpisode 校验器与 APACK 挂载集成（纯 CPU）

- 需要：code → 建议执行者：任意
- 项目：AinerForge · V9 v9 落地：经验平台 → 轨道 A ExperienceEpisode → 第 2 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AinerForge`（先 cd 到这里）
- 关联目录（只读）：`/Users/mac/AinerWorkFlow/AinerZero`——检查点、数据、登记只读；训练已暂停
- 关联目录（只读）：`/Users/mac/AinerWorkFlow/AnimeWorldZero`——episode、身份包、风格包、T10 课程只读
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：forge.V9.A1（accepted）、forge.V9.B3（reported）、forge.V9.B5（ready）、awz.V9.A2（accepted）
- 先读：`/Users/mac/AinerWorkFlow/AinerForge/AGENTS.md`、`/Users/mac/AinerWorkFlow/AinerForge/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/spec/AinerWorkFlow_v9_RFC.md`、`/Users/mac/AinerWorkFlow/AinerForge/docs/EXPERIENCE_EPISODE.md`、`/Users/mac/AinerWorkFlow/AinerForge/reports/V-V9-B3/r1-20261016-codex/report.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`
- 文件范围（只改这些）：`forge/episode/`、`forge/apack/schema.py`、`forge/registry/db.py`、`forge/mount/verifier.py`、`forge/mount/policy.py`、`schemas/apack_manifest.v0.1.schema.json`、`schemas/examples/apack_v0.1/`、`tests/test_episode.py`、`tests/test_apack_v01.py`、`reports/V9-A2/`

## 任务说明
实现 Episode 校验器，并接入现有十步挂载校验器：教师数据不得进 final、自观察与教师分区、哈希齐全、世界键不跨分区。不改 F1 已通过的行为，只新增。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- `observation` 通道除 self_observation、baseline_rollout、teacher_demo 外，接受 `external_derived`（AWZ 实时出口，ObservationPacket r1 §3.11），并在 origin_native 保留 actor；这类通道默认不准 AinerZero 训练挂载，直到登记 ADR-0005 修订。
- 其余按 docs/EXPERIENCE_EPISODE.md（已验收）实现。

## 通用约束（v9，ADR-0012）
- 纯 CPU；不训练、不导入 MLX/ORT/模型；不下载、不安装、不付费、不提交推送、不删除。
- 只改文件范围内的文件；他人未提交改动不碰；原报告与失败证据保留。
- 所有判定用断言，脚本真实非零退出；附“故意改坏必须变红”的对照。
- 报告写实际命令、输入与源码 SHA、临时目录、失败与未验证项；测试通过不等于能力通过。

## 一级2026-10-16补齐文件范围与前置
原卡只有episode新目录，不能实现已接受A1的完整APACK集成，本次明确扩到登记scope。必须等B3修复和B5非作者复核均通过再改core，修改前归档当前原文件及SHA。
按docs/EXPERIENCE_EPISODE.md全部规则实现：版本化新增APACK v0.1，不覆盖v0 schema/示例；schema版本路由，v0注册/十步挂载行为保持；v0.1注册与挂载时验证no_training沿lineage传播、source/kind新增词表、consumer用途、跨包通道声明、world_key与sealed_once政策。consumer本机自报字段不是已认证账号。
仿真真值source_type只能simulator_truth、sim_truth仅通道，partition仍四值。无来源/许可/白名单等必须拒绝；future available_at与target/input分开，内嵌/引用Observation同样不让快照进入模型；不把hashes_complete自报当作来源真实性证明。v0训练DenyAll默认不变，不能为了示例通过添加全局准入或重写已封存final。
本卡只实现CPU合同/合成包，测试全用明确临时Registry路径，不接触生产素材、训练、RunStore或考场真实final。不得改reader.py（B3已修并冻结）；现有测试不删不放宽，新增有意义的各规则正负例+至少6变异非零。独立A3已配，报告精确哈希/新旧版本回归/未验证。超出本scope需先问一级，不自行扩写。


## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
每条规则有反例；原 82 项测试仍全过

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat forge.V9.A2 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report forge.V9.A2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release forge.V9.A2 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report forge.V9.A2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release forge.V9.A2 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release forge.V9.A2 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
