# ainerzero.V9.T14 非作者独立复核

执行者：codex-v101-contract-audit-20261016（二级，非 Claude 作者）。2026-10-16。

**原退回五项的局部修订成立；不建议 T1 r1 整体无条件验收。** 新发现其来源枚举与 AWZ A2 r1 / ADR-0005 的 external_derived 不兼容，应先作兼容性设计修订。没有证明发生实际训练数据污染，也没有运行教师或恢复训练。

- 实际仓库 HEAD：052f9cc80dea070b84d4839c26ad272cd84b96d5；工作区文档/schema/作者脚本 SHA 与 r1 报告一致，完整记录见 metrics.json。
- r0 归档 4/4 逐字节匹配 SHA256SUMS 与 git 995db72 原件。
- 五项局部关闭成立：Teacher/Train/World/旧 M2 共用单锁并在占用前获取、占用后释放；World 不再绕过 Train；Core ML 不与训练共存；内容块与逐来源条目身份分离；sim_truth 是通道而 partition 为 train/development/final/quarantine 四值。
- 独立自写状态树探索，不导入作者模型：r0 三种撞车均有非零违规路径；r1 十六组合违规 0；三个故意破坏（提前释放、先占用后锁、World 使用另一锁）均出现违规。详见 independent_lock.json。
- 作者两个脚本均在读完副作用后运行；会生成夹具的缓存脚本使用 author-sandbox，未写原 contracts。锁脚本返回 0、r1 十六组合无违规/两个破坏被捕；缓存返回 0，11 个结构反例、9 个库级反例、11/11 破坏自检重现。
- 另写独立 schema+库级检查器，原全部 21 夹具结论一致。新增 8 个反例由单独解释器进程真实返回 1：blob 混入世界键、final 进共享库、sim_truth 分区、同内容新开发世界、输入摘要被改且 entry_id 一并更新、错误教师、运行精度变了但键没变、lease 假报未持有。新增同块 train+quarantine 审计条目真实返回 0。
- 全部被验文档/schema/脚本与原夹具前后 SHA 不变。只写本报告目录。模型预算 0、模型调用 0、MLX/GPU/训练/下载/安装 0。

## 实际命令与产物

```text
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -I /Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-T1-r1/codex-v101-20261016/independent_audit.py
```

入口独立完成归档核对、夹具检查、新例、状态树探索，并记录作者脚本精确 argv / returncode / 输出于 metrics.json 与 author_0_stdout.txt、author_1_stdout.txt。作者缓存脚本仅复制 schema 到本报告目录的 author-sandbox 再生成示例，避免修改原件。独立状态树输入来自 r0/r1 书面协议，不调用作者的探索函数；其结果仍是逻辑模型证据。

## 阻断性跨契约问题：上游 external_derived 无法保留

`docs/v9/TEACHERS_AND_CACHE.md` §2.5 统一把输入画面解释为 observed；`contracts/v9/teacher_cache.v1.schema.json` 第 205–208 行进一步固定 `origin_native.system=ainerzero`、`origin_native.origin=observed`，且该对象 additionalProperties=false。它没有承接上游 AWZ external_derived / actor 的字段。

A2 r1 与 ADR-0005 明确规定：AWZ 渲染/模拟观察即使 actor=student，origin 仍为 external_derived，默认不进训练准入。教师做冻结特征变换不会改变输入来源或产生训练许可。

独立合成 probe：原合法缓存条目 origin=observed 全库可通过；把相同条目的 origin 保留成 external_derived，则被当前 schema 拒绝。见 source-preservation-gap.json。此处没有从 AWZ 图像跑真实教师或准入消费者，因此结论是**来源保留协议缺口成立；实际数据被转换/训练污染未验证**。

建议下一次设计修订保留逐来源条目的原系统/原始 origin/actor/输入身份，教师变换作为独立 derivation 记录；训练准入沿输入原资格与教师许可取交集。未经 ADR-0005 修订不得将 external_derived 变成 observed。修订需新版本/迁移策略及反例：AWZ student 自主经历、非学生经历、非 AWZ observed 输入、同 blob 不同来源并存、准入仍拒 external_derived。本文只报告缺口，未修改 schema 或准入实现。

## 未验证及边界

- 穷举的是两个抽象进程的原子动作，**不是实际双进程 fcntl 或生产 ModeGuard 集成测试**。没有创建/碰触 artifacts/locks 真实锁，也未读取或修改现存租约。
- 租约说明不参与互斥是文档约束；说明文件与内核锁矛盾时的实际行为、World 内第二教师拒绝、TTL、崩溃释放、卸载内存回落均未实测。
- T2 缓存消费者/ModeGuard 尚未实现；本报告不能宣称未来的 T2 已拒绝跨分区、来源篡改或二教师加载。A3/B1 等 AWZ 消费者也未由本轮实现。
- 教师许可/内存数值本次按设计读入，没有联网重新法律审查或模型基准；它们不构成新下载/运行授权。
- 当前用户“先改架构与任务，暂不动代码”的决定保留，T2 等实现仍应 blocked。本轮未放行实现、不验收自己的报告。

建议一级处理：接受此独立复核报告及其局部通过证据，T1 r1 就来源兼容缺口作下一轮文档/schema 设计修订；T2 继续暂停，训练暂停不变。
