# P44 原始证据与可复核引用

生成：2026-10-26T09:48:50.542445+03:00。摘要见 P44-REPORT.md；所有相对证据路径以 /Users/mac/AinerWorkFlow/AinerZero/reports/V9-P44 为根。

## 命令和原始响应

commands.json、interpret-commands.json、finalize-commands.json 保存每条审计 Relay 子进程的 argv、身份、cwd、时间、返回码和 stdout/stderr 文件。raw/*.command.json 为逐命令记录。六份 job-status stdout 字节原样保存，未把投影摘要当原始响应。
本次 Python 入口实际命令：python3 reports/V9-P44/collect_evidence.py（rc=0）、python3 reports/V9-P44/interpret_evidence.py（rc=0；两次，第二次修正投影字段并复用首次原始响应）、python3 reports/V9-P44/finalize_report.py（rc=0）。入口控制台摘要见 execution-record.json。交回命令的原始返回保存在 submission/。

| 作业 | 状态 / rc | exec ID | 监督 / 归档 | raw stdout SHA256 |
| --- | --- | --- | --- | --- |
| arm2-seed0 | completed / 0 | eb7d7d66e74d41ff85b90a5fda3fc6c0 | confirmed_empty=True; exec_state=finished | ff87ae5749f152bc777b361974f7cecaf09ad677cee4d48917bbcc0ca4f519bd |
| arm2-seed1 | completed / 0 | 924c69529b524813a0cba6ea292ac42d | confirmed_empty=True; exec_state=finished | 3a31c0ff1042875f016f8d4fc0a48c0e2b3f2da9322168ffa4cd333f58c6bcbd |
| arm2-seed2 | completed / 0 | 9a410cc1b2304b16bdb778200de6d910 | confirmed_empty=True; exec_state=finished | aafc4188077e1cf65a33575547431f3f6525adc82091f2ee55796a4de6208008 |
| arm3-seed0 | completed / 0 | fbf6ea460ce8441f98e5f242d552f9c7 | confirmed_empty=True; exec_state=finished | cb21d5222164fb8fcedf896f74bd9b8b6c21f66768d3b4b1bac5585e46083261 |
| arm3-seed1 | failed / 2 | 2ec212f89b0f435d8e7fd5cc035cff49 | confirmed_empty=True; exec_state=lost | 9b699dc9d9fba385a432af869fc908937679789e95b90be29aafacc74ac76724 |
| arm3-seed2 | canceled / None | None | confirmed_empty=None; exec_state=None | 4a1eab7b8d820e6c610b942fd2f2bacf887cebf6b7759758a8294573dc303c56 |

raw/job-arm2-seed0.stdout、raw/job-arm2-seed1.stdout、raw/job-arm2-seed2.stdout、raw/job-arm3-seed0.stdout、raw/job-arm3-seed1.stdout、raw/job-arm3-seed2.stdout 是六份完整 JSON。每份实际请求均使用 cpu-review-p43-20261025，命令证据见同名前缀 .command.json。
jobs-focused-summary.json 保留 exec_finish、supervision、authorization_ref、actual_argv、日志元数据。runner-receipt-bindings.json 由归档 stdout JSON 解析，实际五条 mode=train；顶层 run_id、配置快照及 reserved_active_seconds 与副本原始行逐项一致。日志实际 SHA 全与响应 logs.*.sha256 相同。
raw/log-*-stdout.log 与 stderr.log 是实际归档内容。已执行 5 个作业各有完整日志；取消作业没有日志/exec/supervision，不虚构 confirmed_empty。失效或丢失执行归档不是 finished；arm3-seed1 的 lost 与真实组空两项并存。

## 只读台账副本

生产路径：/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s1/phase1/control.sqlite3
唯一副本目录：/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/ainerzero-p44-rf604yfe
打开 URI：file:///var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/ainerzero-p44-rf604yfe/control.sqlite3?mode=ro
生产及副本 DB SHA256：fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60
源 WAL/SHM 在采样前后均不存在；没有漏拷贝已存在侧文件。副本 mode=ro 查询后由 SQLite 新建了0字节 -wal 和32768字节 -shm，因此“整个副本文件集合不变”为 false；副本 DB 主体哈希始终不变。未删除副本侧文件、未重建副本、未重跑查询。db-snapshot.json 与 final-safety.json 记录完整源/副本路径、前后 SHA、存在性及复制策略。副本保留至用户另行处理，本任务没有删除动作。
raw/db-experiment.json、raw/db-runs.json、raw/db-daily-budget.json 包含实际 SQL、参数、mode=ro URI 和完整原始行（含 config_json/manifest_json/reason）。生产从未被 SQLite 或 RunStore 打开。final-safety.json 再次记录生产、保留副本 DB 主体和原 P42/P43 所有文件哈希不变，并单列新建副本侧文件。

| Run | 状态 / optimizer steps | 真实 reserved（runs.active_seconds） | terminal elapsed | conservative max |
| --- | --- | ---: | ---: | ---: |
| 19f2d1eb4bf04da4909d87501348028d | completed / 3510 | 267.344375040 | 881.211957216 | 881.211957216 |
| 7d155060fecc4070a9a68e95fb3761fa | completed / 3510 | 236.448813080 | 892.038365126 | 892.038365126 |
| 1678cc1cc5d1468dabb3e86a16a45e97 | completed / 3510 | 227.455351194 | 859.520867109 | 859.520867109 |
| 403ae816720c4ad9b4f75ecd86e7b109 | completed / 3510 | 187.165275004 | 726.769338846 | 726.769338846 |
| 92b694d35a324af083fc27183bb08f8c | failed / 2566 | 138.907656158 | 459.770121098 | 459.770121098 |

真实预留和 1057.321470476050s；保守和 3819.310649394989s；sum 门相对14400s余量 10580.689350605011s。
精确映射：src/ainerzero/runtime/lifecycle.py L391，reserve_work L817–832；raw/lifecycle-excerpts.txt 保存行号原文。worker.py L441–495 为终态 max(reserved, updated-created) 和逐 run 求和，raw/worker-excerpts.txt 保存原文。daily_budget 是跨实验全局日账，不能无条件用日总额替代 r13 预留和。
实验创建 1792928546.279864；实际 experiments.manifest_json.experiment_budget.max_wall_seconds=14400.0；截止 2026-10-25T18:42:26.279864+03:00。lifecycle.py L434–440 同时按创建时间扣减日历窗。参见 experiment-manifest-interpretation.json。
初始 ledger-arithmetic.json 中 actual_experiment_config_budget=null 只因 experiments 实际字段为 manifest_json；真正 manifest 与上限已在后续 interpretation 文件解析，原始行完整保留。

## R6 与 frozen 身份

当前 RESEARCH_LOG SHA 6afc06445982bab61185fd7a2073e49a03277a1de69d45fc70237b5bf02a4d9f。限定节 L731–799，一条顶格批准行在 L798；逐节/栅栏/引用/缩进过滤后只剩该行。原文 raw/R6-current-section-verbatim.txt、带行号 raw/R6-current-section.txt；算法原文 prereg.py L101–180 见 raw/approval-parser-excerpts.txt。
prereg 文件 SHA 9868b913d3cea59acc860e17b6362afcbbb746990e0ddb4962bc6b78123e0f0d；canonical document SHA 1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30；包映射 canonical SHA 09be5e826483ea2b62df93cd429a0c38af59f14b79138b4f2ee2615a85d0e803。
五条 runs.config_json.approval 都记录同一 line=APPROVED…、line_number=798、document_sha256=1cb98a21…5b30、research_log_sha256=cc1a9db00fea295310ddc1d54081c95439af1a9e91a03fa67d2fa82b1048d349。五份归档 stdout approval 同样绑定，核对结果见 approval-binding.json 和 runner-receipt-bindings.json。
当前整份研究日志已有追加，因此当前整文件 SHA 与历史 snapshot SHA 不相同。本次只确认凭证记录之间一致、当前限定节有效；未获得历史整份日志的独立认证副本，不以快照 SHA 反推所有历史文字。P40 卡原始状态/事件见 raw/p40-task.stdout；没有从 accepted 状态倒推运行权限。
21 个 current source package 和 5 个 train/development/export_meta 数据文件匹配 frozen expected SHA，详见 source-data-binding.json。manifest 的正确摘要投影（去掉 episodes 明细、file sizes、完整 source map 等）与 prereg.data_identity 一致，详见 dataset-identity-interpretation.json。初始整对象等式为 false 是摘要和完整 manifest 的结构差异，不是字节完整性失败。
AWZ frozen source_map_digest=35c529b9d77d2b8485a0a8927bdd9929cab9089abd135987d9c792bb9f1f3310；重新计算冻结24文件摘要图一致。现有 AWZ 的 protocols/v9/__init__.py、contracts.py 两项与生成时绑定不同，其完整 expected/current SHA 已单列；不擅自重生成数据，不把后续源码漂移当作历史数据被替换。

## final 历史访问上界

实际字段是 dataset_manifest.plan.partitions=[train, development]，并有 plan.final_partition=not_generated_not_read；顶层 partitions 字段不存在。当前 named packets/final.jsonl、truth/final.jsonl 的检查仅 stat/exists，没有读其内容。raw/data-excerpts.txt 保存 require_partition final 封闭守卫，raw/worker-excerpts.txt 保存受限消费路径。
五份实际 actual_argv 和归档 JSON mode=train。日志中 final training/checkpoint 词语不等于 final 分区；absence of log mentions 也不是完整访问审计。日志是程序自身输出，源码守卫是意图/当前机制；两者都不能覆盖任何历史旁路、其他读取器、曾存在后移走文件等情形。历史 final 零读明确 UNVERIFIED，本任务也不以读取 final 数据来证明未读。

## params 和中间检查点

checkpoint-inventory.json 是初始当前盘存，仅哈希未加载权重。其历史字段最初是未取得期望值的占位；随后从已保存的 runner 冻结 stdout details.checkpoints[*].sha256 和副本 runs.reason 内的完成 receipt 找到历史记录。最终逐文件结论以 checkpoint-historical-comparisons.json 为准，不能继续把全部20个 checkpoint 一概称无历史记录，也不能称全部20个都已证明。
4 个 completed run：4 个 params.npz 与 sidecar/P40 ledger/runner stdout/DB receipt SHA 均一致；16 个中间 checkpoint 与 runner stdout 和 DB receipt 记录值均一致。runner stdout 的整文件 SHA 与作业终态 metadata 相同；该证据支持“与运行记录哈希一致”，不提供密码学认证、模型行为正确性或完整历史访问审计。
failed run 92b694d35a324af083fc27183bb08f8c：无 params.npz；4 个中间 checkpoint 仅有本轮当前 SHA，本轮没有获得预存期望 SHA，所以历史一致性 UNVERIFIED。初始比较表里该 run 的缺失 params 行也标 UNVERIFIED，含义是不能进行不存在文件的哈希比较，不能写成第5个 params 通过。

## 不利事实与授权边界

原 P42/P43 脚本与报告逐文件 before/after SHA 一致，未执行/覆盖。P43 之“深审后 final 零读成立”“所有5个 params 及全部 checkpoint 匹配”不能原样保留。P43 删除唯一副本导致证据不可复现的问题已以本轮 retained clone 修复，本任务不追溯改写原文件或 accepted 事件。
首次 finalize_report.py 因“整个副本文件集合完全不变”的过严断言失败（SQLite只读副本侧文件新建），原失败 stderr、initial-final-safety.json 和 initial-verification.json 保留。修正核查口径为主体不变并披露侧文件，未修改原始数据或删除证据；早先 verifier 的 passed 仅覆盖当时5组检查，不作为该失败已关闭的证据。
建议收窄至本报告 matrix 支持的事实；P40 仍是未完成实验，r13 窗口已关。本报告零新增运行、零预算调整，不签发 r14 或余量复用授权。P36 未触碰。

## SHA 索引与复核

evidence-index.json 列出本目录所有已交付文件的绝对路径、大小和 SHA（索引自身除外；避免自引用）。submission 中的 report 返回发生于索引形成之后，交回后单列 submission/receipt.json，不用于改写已提交结论。verify_evidence.py 仅检查已保存摘要、SHA 索引和集合关系，不运行产品或源变异。
