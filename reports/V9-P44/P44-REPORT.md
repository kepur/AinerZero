# ainerzero.V9.P44 非作者 CPU 证据修订报告
角色 executor；负责人 cpu-review-p43-20261025（tier 2 / codex）；2026-10-26；交回统筹裁决。
仅写 reports/V9-P44/；未执行 P42/P43 脚本；无新增 verify/train/eval/MLX/Blender、final 数据读取或删除。
P43 的 accepted 事件保留；建议仅按下表收窄引用，不作为全面通过、能力晋升或 r14 授权。

| 核查项 | 结论与范围 |
| --- | --- |
| 六份原始作业响应 | 已保存本人身份命令、rc、stdout/stderr；5 个执行作业真实 exec+confirmed_empty=true；1 个启动前取消，无 exec/监督记录。 |
| 不利执行事实 | arm3-seed1 rc=2，资源守卫失败；其 exec_finish.state=lost 保留，不改称 finished。 |
| final 历史零读 | **UNVERIFIED**；当前清单/文件、源码守卫、train argv 与日志只界定所见和预期路径，无独立历史访问审计。 |
| 台账与双墙钟 | 唯一副本以 mode=ro 查询；生产及副本 DB 主体 SHA 不变；副本新建空 WAL/SHM 已披露保留。真实预留和 1057.321470s，保守和 3819.310649s。 |
| 日历窗口 | 实验实际 manifest 上限 14400s；2026-10-25 18:42:26.279864+03:00 已过期，逐 run 余量不能重开窗口。 |
| R6 | L731–799 限定节仅 L798 一条有效行；5 run 冻结配置及 runner 日志绑定同一 document、批准行、行号与历史 log SHA。历史整份日志未重新认证。 |
| source/data | 当前 21 个 package 文件、5 个冻结数据文件均匹配；manifest 正确投影匹配 prereg。AWZ 当前生成器 24 文件中 2 漂移，单列，不能倒推原数据失败。 |
| params | 仅 4 个存在，均与邻接 SHA、P40 记录、归档 runner/DB receipt 对上；失败 run 无 params。 |
| 中间 checkpoint | 16 个完成 run 检查点与 runner 冻结 stdout 及 DB 终态 receipt 记录的 SHA 对上；失败 run 的 4 个只有当前哈希，历史一致性 **UNVERIFIED**。 |

原始证据、精确字段与 SHA 索引：P44-DETAILS.md、evidence-index.json；正式指标：P44-metrics.json。
保留副本：/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/ainerzero-p44-rf604yfe/control.sqlite3。
未验证：final 历史零读、失败 run 4 个中间检查点历史一致性、历史整份 RESEARCH_LOG 的重建认证；哈希一致不证明模型正确性。
P36 未触碰；不接受/拒绝任何任务；本报告没有新增运行、r14、预算、下载或发布授权。
