# 任务 awz.P3.E5：【代码】统一变更v1纯CPU合同校验（不提交世界）

- 需要：code, math → 建议执行者：任意（缺 math 的模型不要领）
- 项目：AnimeWorld Zero · P3 三期：v8 世界系统第一批（Blender 主路径、工具库、美术闭环） → 轨道 E 世界指令与 .aworld（一级） → 第 5 步
- 主工作目录：`/Users/mac/AinerWorkFlow/AnimeWorldZero`（先 cd 到这里）
- 层级：二级（执行层） · 类型：implement · 需要 GPU：否
- 前置：awz.P3.E3（ready）
- 先读：`/Users/mac/AinerWorkFlow/AnimeWorldZero/AGENTS.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/README.md`、`/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/WORLD_CHANGE_PROTOCOL.md`
- 文件范围（只改这些）：`python/animeworld/world_change/contract.py`、`python/animeworld/world_change/__init__.py`、`tests/world_change/test_contract.py`、`reports/P3-E5/`

## 任务说明
先读本项目规则与前置设计，先领取再改。只做纯CPU工程，不导入MLX/ORT/模型，不渲染、不下载/安装/付费、不重启服务、不提交推送/删除，不改冻结参数和门。所有测试使用新临时根，记录实际命令、输入/源码SHA、失败和未验证项；不写生产库、RunStore或关联项目。没有依赖不得自行安装。摘要30行内，完整证据另存，容量足够report --next，否则capacity-exhausted交接。

先读：/Users/mac/AinerWorkFlow/AnimeWorldZero/docs/design/WORLD_CHANGE_PROTOCOL.md，以及同目录草案schema。
实现提议协议的结构与纯函数语义校验：schema、精确输入摘要（重复键/非有限数拒绝，算法与数值编码明确）、完整base向量、单族/四类、test与move/copy路径/父路径越界、有效tick与外部提供的能力/版本前置。持久ops逐一对照只读Hub service.py真实字段，缺参数和未知引用拒绝；不调用Hub propose/apply，不建第二份持久世界库。只校验并产出candidate/errors/unsupported，不实现真实提交/预览token签发/数据库CAS/回滚，不声称黄金并发已验证。固定fixture覆盖小于1e-6精确源变化、不完整快照、未知持久逆操作、路径逃逸等；尚无权威依赖就未验证，不能用fixture通过冒充跨仓E2E。


## 参数 v0（统筹登记，照用不改；觉得不对就在报告里提）
```json
{}
```

## 验收标准
原设计范围内纯CPU合同与不利反例通过；未实现/未验证边界明确；完整身份与临时数据证据；后接非作者复核

## 怎么交回
1. 心跳（每 10 分钟）：`relay heartbeat awz.P3.E5 --agent <你的ID> --msg "做到哪了"`
2. 完成：`relay report awz.P3.E5 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next`
3. 失败也要交：加 `--failed`；环境或资源问题再加 `--retryable`
4. 中途要停：`relay release awz.P3.E5 --agent <你的ID> --reason "做到哪了"`；还要接着领就加 `--next`
5. 交完或释放后：立刻回到 `relay next --agent <你的ID> --wait 3600` 继续领下一个（也可选 `--wait-forever`）；exit 3 表示 1 小时超时/暂时没活，立刻重跑同一条命令继续等，不结束会话。任务说明或报告里的“交完本任务就停/只做这一个”只约束该任务本身，交完仍回到 relay next，除非用户叫停或额度/上下文快用完。
续领命令：`relay report awz.P3.E5 --agent <你的ID> --result-file 报告.md --data-file 指标.json --next` 或 `relay release awz.P3.E5 --agent <你的ID> --next`。先用不超过 5 行说明进度，再在同一进程进入 next 长轮询，不要只写提醒就结束。容量不够则 `relay release awz.P3.E5 --agent <你的ID> --capacity-exhausted`，不要加 `--next`，也不要 `--failed`。
