# ainerzero.V9.B4 r4 交回摘要（二级执行层 ainercodex-p4x7）

状态：reported；纯 CPU；未训练、无 MLX/ORT、无下载、无付费、无 git 提交；未自行 accept。
依据：`reports/V9-B1/COORDINATOR_DECISIONS.md` 裁决 1–11 ＋ `B4-r4-DECISIONS.md` F1–F7（旧证据先归档）。

1. 归档：r3 全量 124 文件 + ARCHIVE_SHA256SUMS 在 `reports/V9-B1/archive/r3-20261016T2041/`。
2. F1/F3：11 族标识词规范化判定独立重写（复数/不规则复数/id/ids/idx/identifier 后缀、gt|raw|my|src 前缀、value|map|list|… 尾缀、id 前缀、hidden_contact/contact_id、裸键）；`param_schema` 明确拒 patternProperties/$ref/if-then/oneOf 等。B5 探针 **1131/1131** 被拒（两层各自全拒）；条文 56 条拼写反例；条目矩阵 13/13。
3. F2：夹具改 `NN_<case>.json` + `alias_key`；casefold 与 inode 碰撞扫描 **0/0**（236 文件）；EXPECTATIONS 计数与磁盘一致（112 提案/10 回执）。
4. F4：`safe_jcs_sha` + `jcs_fail_closed` + CLI 全路径兜底；超范围整数、孤立代理项两条反例各配隔离对照；**0 traceback**。
5. F6：quantity 双层允许表（schema 50 项封闭枚举 + 上下文 pin 可信表 + 条目 observable_names）；7 反例、10 条裸复数正例、三方一致性 2/2。
6. F5：`docs/v9/SKILL_PROPOSAL.md` §13 改三层矩阵（schema/参考门禁/真实消费者）；值级偷带与任意隐写如实列未实现。
7. F7：`SHA256SUMS.txt` 每轮重算，RAW/JCS/PATH 三列（253 行全部核对通过）；`--disable` 未知名退出码 2；`context_identity` 不可关闭。
8. 命令：`…/venv/bin/python reports/V9-B1/check_skill_proposal.py --suite`（作者另用过一次 `--regenerate`）；两次 `all_ok: true`，退出码 0。
9. 计数：112 用例（18 正 / 94 反）、17 规则、94 对照（41 真隔离，53 条层 1 已先拒故按设计不隔离）、回执 10（7 反例 7/7 隔离）、置信度扫描 184、no_rewrite 18、泄露扫描 112、JCS 自测 18/18、元校验 3/3。
10. 未验证：真实 AWZ 门禁/内核/WorldBrainAdapter、参数值级偷带与任意隐写、裁决 11 训练门、句柄解析、E3 编译。测试通过 ≠ 能力通过；本卡不构成运行授权。
11. 完整报告 `reports/V9-B1/REPORT.md`（r4 段）、指标 `reports/V9-B1/metrics.json`、清单 `reports/V9-B1/SHA256SUMS.txt`。
12. 请新的非作者 `ainerzero.V9.B6` 复核并重算新 SHA；B5 的负面证据保留为有效发现。
