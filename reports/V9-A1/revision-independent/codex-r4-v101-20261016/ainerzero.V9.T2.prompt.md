# 任务 ainerzero.V9.T2：【代码】教师特征缓存与运行模式守卫（纯 CPU，假教师）

- 需要：code → 建议执行者：任意
- 项目：AinerZero · V9 v9 落地：NeuroGeometry × H-JEPA 世界脑（P0 无训练） → 轨道 T 教师接入（M2 Max，无 CUDA） → 第 2 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AinerZero`（先 cd 到这里）
- 关联目录（只读）：`/Users/mac/AinerWorkFlow/AnimeWorldZero`——AWZ 评测包（E-0/E-1 起使用，只读）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：ainerzero.V9.T1（reported）
- 先读：`/Users/mac/AinerWorkFlow/AinerZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AinerZero/README.md`、`/Users/mac/AinerWorkFlow/AinerZero/ARCHITECTURE_V9.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/adr/ADR-0012-v9-neurogeometry-hjepa.md`、`/Users/mac/AinerWorkFlow/AinerZero/docs/research/M2Max_NoCUDA_Integration_Plan.source.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/V9_LANDING_PLAN.md`
- 文件范围（只改这些）：`src/ainerzero/v9/teachers/`、`tests/v9/teachers/`、`reports/V9-T2/`

## 任务说明
按 T1 实现缓存读写（内容寻址、元数据完整、重跑哈希可复现）与运行模式守卫（Train Mode 下加载任何教师即拒绝；Teacher Mode 一次只常驻一个教师；模式切换卸载检查）；用假教师（确定性随机特征）测试，不下载任何模型、不导入 MLX/torch。

【r4 改写（D-019，2026-10-16）】本卡暂停中，放行条件见 AWZ docs/design/V9_LANDING_PLAN.md §11.1。放行后按以下 r4 要求执行，与上文冲突时以本段为准：
- 以 docs/v9/TEACHERS_AND_CACHE.md r1 与 contracts/v9/teacher_cache.v1.schema.json 为准；v0 只作历史。
- 单锁 `artifacts/locks/m0-worker.lock` 整段持有、非阻塞取锁失败即 skipped_lock_busy、崩溃由内核释放；租约说明文件只用于观察。
- 内容块与来源条目两层写入、原子改名、读时核验、broken 标记、`cross_partition_blob` 拒绝；实现 reports/V9-T1/r1/check_teacher_cache_v1.py 的全部库级规则。
- 用真实双进程测试复现 lock_model_check.py 的结论（在临时目录用临时锁文件，不碰真实 artifacts/locks）。

## 通用约束（v9，ADR-0012 修订三）
- 不训练；未获批准不下载、不安装、不付费；不提交推送、不删除。
- 只改文件范围内的文件；他人未提交改动不碰；原报告与失败证据保留。
- 所有判定用断言，脚本真实非零退出；附“故意改坏必须变红”的对照。
- 报告写实际命令、输入与源码/权重 SHA、临时目录、内存峰值与耗时、失败与未验证项。

## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
缓存可复现；元数据缺失拒写；模式违规必拒；改坏守卫测试变红

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat ainerzero.V9.T2 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report ainerzero.V9.T2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release ainerzero.V9.T2 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report ainerzero.V9.T2 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release ainerzero.V9.T2 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release ainerzero.V9.T2 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
