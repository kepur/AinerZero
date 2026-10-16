# ainerzero.V9.T17 非作者复核：T1 r2 / teacher_cache.v2

执行者 codex-v101-contract-audit-20261016，2026-10-16。只读被验文件，只写本任务报告目录。

**结论：r2 保留 upstream/derivation 的方向成立；暂不建议 T1 整体验收，request_changes。** 新证据表明来源组合、ADR 批准绑定和时间截止还可由条目自报绕过。需要修文档/契约/reference 反例，不要求实现生产消费者。

- r1 归档全部 SHA 与 SHA256SUMS 一致，原文档/schema 哈希与 T14 所审身份相同。
- 先检查作者脚本副作用：它会生成 contracts/v9/examples。复制 v2 schema 到 author-sandbox 后调用原脚本；返回 0，库级正例 1、资格例 4、结构反例 8、库级反例 6、11/11 破坏自检全部复现。
- 独立编写 validate/eligibility，不复用作者 store_problems/train_eligible。原全部 15 个 JSON 夹具结论一致；AWZ 拒、AinerZero 准、几何教师准、unverified 拒四例一致；五项交集各独立关闭一项都拒绝。
- 新 8 个常规不利反例由独立子进程真实返回 1；未来帧以 use=target 隔离、as_of 恰等末帧两个正例返回 0。
- 另写 5 个隔离语义探针，独立严格 oracle 均返回 1；作者 schema+库级检查全部返回 0。两项来源探针还使原五项资格计算为 True，见下文。
- 文档/schema/作者报告/脚本及原夹具前后 SHA 不变；无 MLX/GPU/训练/模型调用/预算、无下载安装、没有触碰真实锁。

## 逐条结论与必修项

### B1 来源保留：原阻断项只部分关闭

r2 能合法表示 AWZ external_derived、actor 和原输入身份，并将教师变换单列 derivation，修复了 v1 “忠实表示反而被 schema 拒绝”的问题。

但 upstream.system 与 origin 只是两个独立枚举。独立把合法 AWZ 条目的 origin 改成 observed，再复制另一条 AinerZero 的 eligibility（train=true、basis=admit_training），作者 schema/库级检查均通过，资格计算也为 True。actor 不变为 student，world_key 仍 awz:w1。

这是与 A2/ADR-0005 的直接不兼容：AWZ 渲染或模拟观察必须 external_derived，actor=student 不能把来源改成 observed。**应在定义上固定 AWZ → external_derived 组合，并声明 upstream 需与不可变输入来源清单核对、资格不能从同 blob 的其他来源复制。** 不接受只依赖条目自报 train=false 的“默认拒训”。

### B2 as_of：缺少与不可变输入时间的绑定

正常 input_after_as_of 反例可抓到；use=target 的未来帧和末帧等于 as_of 也按预期通过。

但作者检查只比较 entry.source.timestamps_s 与 entry.as_of_t_s，没有比较这些时间戳与 blob.key_material.input.timestamps_s。一条输入本来包含 0–0.625 秒帧，将条目 source.timestamps_s 改成 [0,0.1]、as_of 改成 0.2，保留原 blob/cache_key，作者检查仍通过。模型输入的真实片段仍有未来帧。

**应定义 source 时间列表与 blob 输入时间列表逐项相同，截止比较以不可变 blob 输入为准；明确时间域/epoch 与 ObservationPacket 的 episode-relative t_ticks/120 对齐。** 不能拿可编辑的条目副本或故事内 world_time 代替因果时间。补“回填更早时间仍拒绝”的契约例即可，不要求实现媒体加载器。

### B3 external_derived 修订：非空字符串不等于批准

空/缺 revision_ref 已被 schema 拒绝，普通 external_derived/default_deny 也拒训，局部关闭成立。

但把 basis 写 adr_0005_revision、revision_ref 写 not-an-approved-adr、train=true，作者 schema/库级检查通过，资格计算为 True。当前没有获批 ADR-0005 修订，不能因存在非空字符串自动获得资格。

文档已经写“登记且用户决定”这项政策，因此本项首先是**reference 检查漏了已声明规则**；契约还需要明确批准登记的权威/引用身份、解析失败与不存在时 fail closed，保证当前批准集合为空时所有 external_derived 仍拒训。将未来修订路径写入协议不构成本次批准。可以用冻结空批准清单作为 CPU 反例，不需要实现完整审批服务。

### B4 derivation 指纹：声明与内容块不一致仍能通过

单独把条目 derivation.weights_sha256 或 preprocess_spec_sha256 改为不同的合法 SHA，作者 schema 和 store_problems 都通过；它只比较 teacher_id。

本项不证明实际教师用了错误权重，而是权威来源条目与引用内容块的指纹可自相矛盾。**应明确 derivation.teacher_id / weights_sha256 / preprocess_spec_sha256 都必须与所引用块逐项一致**，并补独立反例。模型指纹已在 blob 键内，不需要新增模型或换计算框架。

## 已成立但不可外推的事项

- 同块 AWZ 与 AinerZero 两条真实来源可以并存，资格逐条计算；正确 upstream 下的四个资格结果与作者一致。该正例不能证明伪造 upstream/eligibility 也会被拒绝。
- 训练资格五项交集逻辑本身成立：上游资格、教师许可、条目许可、可复现等级、分区缺一即拒；但上游资格的可信性仍须 B1/B3 约束。
- 电源口径已按实际入口修正：AinerZero 取消交流电 guard 的记录与当前源码一致；AWZ 独立资源规则不受此改变。文档变化不授权任何 GPU 运行或恢复训练。本轮没有电源/模型实测。
- r1 单锁与两层缓存的证据保留；没有重新宣称真实双进程、ModeGuard、缓存消费者、Forge 映射或训练准入已实现。
- T2 等实现保持暂停；本报告只要求补清能冻结的协议定义及参考检查，主架构职责/信息边界可独立定版。

## 实际命令与身份

```text
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -I /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-T1-r2/codex-v101-20261016/independent_audit.py
```

独立脚本逐一用新解释器执行新例并记录真实返回码；sandbox 作者命令见 metrics.json 的 author_argv。原输入 SHA256：

```text
e750fec28476547e7c0d6a406682b08903602b6e2577a3d80b344a9db46b97e7  docs/v9/TEACHERS_AND_CACHE.md
7cba7daa5521d55e1c557bdb5f81b4ceb59c71f214c6d69336c00f459c4fae67  contracts/v9/teacher_cache.v2.schema.json
21735f757736beaa08d67ae4ee0c9cdf375a2639cd6bfda637eab6fac7aca70d  reports/V9-T1/r2/check_teacher_cache_v2.py
```

metrics.json 保存归档、原夹具、交集单门、正反例、五个语义 probe 和输入前后哈希。语义严格 oracle 是独立审计用候选规则，不是新增生产实现。没有自行 accept 报告，没有改动旧失败证据。
