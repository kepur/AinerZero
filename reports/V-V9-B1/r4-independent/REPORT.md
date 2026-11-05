# ainerzero.V9.B6 执行报告：SkillProposal r4 最小加固与信息隔离（非作者复核）

角色：executor（二级执行层）；负责人：**deepseek-flash-emje**；时间：2026-10-17（+0300）
任务状态：**reported**；实验状态：未执行（纯 CPU 只读复核，无训练/MLX/ORT/下载/付费/git 提交）
任务依据：`reports/V9-B1/COORDINATOR_DECISIONS.md` 裁决 1–11、`AinerRelay/.../B4-r4-DECISIONS.md` F1–F7、B5 r3 独立负面（已按验收负面使用）、`docs/v9/SKILL_PROPOSAL_COORDINATION.md`（一级 B1）
验证对象：`ainerzero.V9.B1`（9593eccf5c092099…）与 `ainerzero.V9.B4` 修订 r4（最终交付字节，见 §2）
复核边界：只读被验文件；只写 `reports/V-V9-B1/r4-independent/`；不改源、不运行模型、不下载。

## 摘要（结论）

1. **非作者**：我 `deepseek-flash-emje` 不在 B1 历史作者（claude/codex）与 B4 历史作者（deepseek-flash-a7k2、grok-m4q8、antigravity-7c1e、ainercodex-p4x7）之中；未复用作者 oracle，自写 JCS + 自写键名判定 + 自建门禁 harness。
2. **B4 r4 已关闭 B5 r3 全部必修漏检**：B5 的 **1131** 条探针，自写判据、schema 正则层、门禁规范化层（`--disable schema`）、全门禁四层均 **1131/1131 拒绝**；3 层嵌套位置 L2 共 3393/3393 拒绝。此前真实 exit 0 的 `objects_id`/`worldIdsMap`/`entitiesId`/`worlds_id` 等现在真实子进程 rc=1 `schema_invalid`；关掉 schema 层仍由规范化层拒（world log `forbidden_world_id_key`）。
3. **大小写路径各自独立**：236 个夹具文件 0 个 casefold 碰撞、0 个同 inode、236 个不同 inode；5 组仅大小写不同的拼写（`world_id/World_Id/WORLD_ID`、`worldId/worldID`、`worldIds/worldids`、`entities_id/ENTITIES_ID`、`entitiesID/ENTITIESID`）各自独立路径/内容/原始哈希；B5-F2 的同 inode、44 vs 43 缺失在本轮不可复现。
4. **quantity**：50 项允许表三方（提案 schema enum / 能力登记 enum / 核对器表）逐项一致且逐项可追溯到 AWZ ObservationPacket/v1.1（0 项无出处）；7 条反例全拒，允许表内但条目未声明量（越权）拒且关掉绑定后放行（真实隔离），未知量在关掉 schema/允许表/绑定后才会被接受（逐层链完整），别名、上下文守卫（编辑集合非空、表含未派生/别名量、source 摘要不符）全 fail-closed。
5. **JCS fail-closed**：超范围整数（2⁵³）、孤立代理项两条点名字例均真实非零、`schema_invalid`、无 traceback、异常类型只进世界侧日志；独立构造的 NaN/Inf 字面量、无效 UTF-8 同样 fail-closed；两条对照关闭规则后真实 accepted（对照非异常退出）。
6. **清单实际 SHA**：`SHA256SUMS.txt` **254/254** 数据行逐行重算通过（含 236 夹具、11 交付物、7 只读输入），`check_result.json` 与清单自洽且与磁盘一致；`--suite` 在副本复跑两次 all_ok、夹具 0 改动、结果确定；archive 123 个 payload 哈希全对。
7. **改坏对照**：101 条对照（94 提案 + 7 回执）中 **48 条真实隔离**（41 提案 + 7 回执，与作者计数一致），**53 条非隔离由层 1 schema 正则先拒**逐条独立解释（用别名键名对 schema 正则做独立命中测试）；17 条规则每条都有 ≥1 真实隔离对照。
8. **无任意隐写通用证明**：确认 B4 文档 §13 第 3/4 行自述诚实——合法字符串参数承载真实实体 ID 被 accepted（值级偷带），字段名判定不能证明值内容；本轮按 r4 最小范围（字段级）判定，不构成阻断，但也**不能**把「已消除任意隐写」写成结论。
9. **一级 B1 裁决与文档**：Claude 原 **11/11** 条完整保留；B1 协调页 5 项重点主张与原裁决/AWZ 只读证据一致（运行路线沿用 Event `source=command` 且 Event schema 无 `student` 枚举、不走 E3 持久提交；编辑能力集合为空且有实现守卫；TTL 闭区间不变且实现两端接受/右端+1 过期；`external_derived` 按 ADR-0005 默认不进训练准入；confidence 184 行扫描 0 变化、非授权）。**一级裁决 11/11 成立；二级形式化 10/11 有独立证据，裁决 11 按原裁决只写文档未实现（如实登记）。**
10. **结论与建议**：建议统筹**验收 B1 + B4 r4（限本次证据范围）**。另有 3 项非阻断小缺陷（B6-F1 陈旧哈希、B6-F2 NameError、B6-F3 旧数字）与 6 项观察项（§11），建议随下一次修订补正；本复核不自行 accept。

## 1. 输入身份（自行重算；未改）

| 对象 | SHA256 |
|---|---|
| B4 最终 `check_skill_proposal.py`（**评分/结论以本文件最终字节为准**） | `37d4308f34a64bad515a8ef44b0c9a12b8bf6f35c24a628730280c3ad50328da` |
| `skill_proposal.v1.schema.json` | `cdbed88a4fd4a7c13269781659f2700cf0124838f9d4f2706872effe7d2c76a1` |
| `skill_gate_reply.v1.schema.json` | `dc81852c0dc6341a033bcf9ed70c969091faae541e775c4682cb0ce6f1840f2c` |
| `ability_registry_entry.v0.schema.json` | `8b5d089b40a226bfd300a5b94af6399e321cd19da839d5ca88801aa90377489f` |
| `docs/v9/SKILL_PROPOSAL.md` | `148fcfed4c0a7e03cce804880f8f94e7ebb4fdc798c847a5518be15edd894adf` |
| `docs/v9/SKILL_PROPOSAL_COORDINATION.md`（B1） | `9593eccf5c092099d488e72c2c505deb0b116fe3cc52385793d2cc1d7e0495c1` |
| `reports/V9-B1/COORDINATOR_DECISIONS.md`（原 11 条） | `04504c33643c30b3116abe5cd8430fe2bc0e8f44fa70154b9c2f892f93a6d113` |
| `check_result.json` / `SHA256SUMS.txt` | `10e65404e476df67…` / `336afc61fdcdc73d…` |
| `EXPECTATIONS.json` | `6389216957ca5e5a…` |
| B5 `probe_variants.json`（回归输入） | `3f40299111ed0629…` |
| AWZ `observation_packet.v1_1.schema.json`（只读） | `01be45e0adfdac74…` |

> 时序事实：`REPORT.md`/`metrics.json` mtime 02:53，`check_skill_proposal.py` 02:55，`check_result.json`/`SHA256SUMS.txt` 02:56——最终编辑后 suite 已重跑，`SHA256SUMS.txt` 与磁盘/最终字节一致；`metrics.json.artifacts` 与 relay B4 report data 的核对器哈希仍是旧值 `9cf0d90b…`（B6-F1）。

## 2. 独立判据（不复用作者 oracle）

- **JCS**：自写 RFC 8785（UTF-16 码元键序、ES6 数字、最小转义、±(2⁵³−1)、拒 NaN/Inf/重复键/孤立代理项）；自测 16 向量通过；独立复现 **112/112** 个冻结上下文 pin，与作者夹具逐条一致。
- **键名判定**：按裁决 2 与 B4-r4 F1/F3 条文另写（11 族 + 规则/不规则复数 + id/ids/idx/identifier(s) 前后缀 + gt/raw/my/src 前缀 + value/map/list… 尾缀 + hidden_contact/contact_id + 裸键），不读探针文件、不按例子 ID 硬编码。
- **门禁 harness**：自建（112 用例 + 101 对照走真实子进程；探针/矩阵走被测 `gate_and_check` 作为被测对象）；期望来自权威文档与冻结 EXPECTATIONS，不来自 `check_result.json` 自述。

## 3. 1131 探针分层统计（逐族）

| 族 | 总 | L0 自写判据拒 | L1 schema 正则拒 | L2 规范化层拒（关 schema） | L3 全门禁拒 |
|---|---:|---:|---:|---:|---:|
| mandated | 402 | 402 | 402 | 402 | 402 |
| plural_stem | 396 | 396 | 396 | 396 | 396 |
| padded | 297 | 297 | 297 | 297 | 297 |
| hidden_contact | 36 | 36 | 36 | 36 | 36 |
| **合计** | **1131** | **1131** | **1131** | **1131** | **1131** |

- 位置：`params.tags[0]`、`params.root[0]`、`params.root[0].level2[0]` 三层；L2 合计 3393/3393 拒绝。
- L2-only（schema 未命中、只靠规范化层）在 B5 探针集中为 **0**；规范化层隔离性由专门夹具（`idx`、`identifiers` 等 2 条真实隔离对照）证明，避免把两层的重叠覆盖算成层 2 单独覆盖。
- 未超出文档界线：裸复数词干 `entities/objects/…/worlds` 10 条两层都不拒，实测 accepted（与文档 §2.4 一致）；`identity` 的过度拒绝已知。
- 子进程实证（真实退出码）：12 个代表性拼写全部 rc=1 `schema_invalid`；`--disable schema` 后仍 rc=1 且 world log `forbidden_world_id_key`；基线（同上下文、无探针键）rc=0 accepted。

## 4. 大小写路径独立（F2）

236 文件（113 contexts + 18 valid + 94 invalid + 10 replies + EXPECTATIONS）全部唯一 inode、0 casefold 碰撞；122 条 case（112 提案 + 10 回执）的 proposal/reply 原始哈希与 context JCS 哈希全部重算一致；65 条 alias 拼写均出现在内容里、5 组大小写变体各自独立文件/内容（B5-F2 的「同 inode 同 sha、Entity_Id 无产物」不可复现）。`contexts/baseline.json` 是文档声明的「1 基线」，非多余文件。

## 5. quantity 允许表（F6）

- 三层一致：提案 schema 50 项 enum == 能力登记 `observable_ref` 50 项 == 核对器 `OBSERVABLE_QUANTITIES` 50 项，无重复。
- 逐项可追溯：50/50 能在 AWZ ObservationPacket/v1.1 的通道/字段（含 detection.*、audio_events.*、ego_motion.delta.*、pose_sensor.*、sensor_noise.*、payload 字段）找到出处，0 项无出处；允许表内 0 项命中标识键名判定（作者/自写两套判据均为空）。
- 反例链：7 条 quantity 反例全拒；允许表内但条目未声明（`audio_events.type`）→ `quantity_not_declared_by_ability`，关掉绑定后 accepted；未知量在关 schema 后 `quantity_not_allowed`、再关允许表后 `quantity_not_declared_by_ability`、三关后 accepted（明确逐层责任）；`world.id/hidden_contact/contact_id/entityId/entities_id/worlds_id/ids` 全拒；上下文守卫 5/5 命中；从可信表移除已声明量 → 拒。
- 观察项：`quantity_forbidden_alias` 分支按构造不可达（B6-F5）。另：`observable_registry.source_sha256` 实际是**路径字符串**的 sha256（`a2971c9a…`），不是 AWZ 文件内容哈希（`01be45e0…`）——允许表仍被整份上下文 JCS pin，但「取自 AWZ 契约」不能由核对器密码学证明（B6-F4）。

## 6. JCS 异常 fail-closed（F4）

| 输入 | rc | 原因码 | 异常是否只在世界侧日志 | traceback |
|---|---:|---|---|---|
| 夹具 `jcs_int_out_of_range`（t_ticks=2⁵³） | 1 | schema_invalid | `jcs_canonicalization_failed:ValueError` | 无 |
| 夹具 `jcs_lone_surrogate`（\ud800） | 1 | schema_invalid | `jcs_canonicalization_failed:UnicodeEncodeError` | 无 |
| 自造 2⁵³ / 2⁵³ 参数 / NaN / Infinity | 1 | schema_invalid | `jcs_canonicalization_failed` / `proposal_unreadable` | 无 |
| 自造无效 UTF-8 字节 | 1 | schema_invalid | `proposal_unreadable:UnicodeDecodeError` | 无 |

两条点名反例的破坏对照（关 `jcs_fail_closed` 等）真实 rc=0 accepted，说明对照不是异常退出。建议项：重复键输入当前**不**fail-closed（最后值获胜，实测 rc=0；RFC 8259 允许但 JCS 要求唯一）——不在 F4 点名范围，列为残留风险 B6-F6。

## 7. 清单实际 SHA（F7）

`SHA256SUMS.txt` 254 数据行全部重算通过（11 交付物 + 7 只读输入 + 236 夹具；RAW/JCS/PATH 三列；`jcs_error:ValueError` 只用于含 2⁵³ 夹具的 check_result 自身，符合注释口径）。`check_result.json` 的计数 == 我按 EXPECTATIONS 重算（112/18/94/17 规则/94 对照/10 回执），failures 与 control_failures 均为空；replies 10/10、112 条回执 schema+白名单+0 泄露；no_rewrite 18/18；置信度扫描 184 行 0 变化。**唯一哈希失配**：`metrics.json.artifacts` 与 relay B4 报告 data 的 `check_skill_proposal.py` 记旧值（B6-F1）；`SHA256SUMS.txt` 自身与最终字节一致。r3 归档：123 payload 哈希全对，清单自指行占位 + 「124 文件」口径见 B6-F8。

## 8. `--suite` 只读与每条改坏对照

- 在 `/tmp/v9b6-suite-copy` 副本（不写真实交付目录）复跑 `--suite` 两次：均 rc=0、`all_ok=true`、53.7s/54.2s、stderr 空；`contracts/**`+`docs/**`+`reports/V-V9-B1/**` 运行前后 **0 changed/added/removed**；只重写 `reports/V9-B1/check_result.json` 与 `SHA256SUMS.txt`；两次结果字节确定；副本 `check_result`（归一 inode 后）与提交版完全一致、`SHA256SUMS` 除自身行外逐行一致（自身行差异仅因副本 inode 不同）。真实仓库在复核前后所有交付物与 236 夹具逐字节/mtime 不变。
- 101 条对照：48 条真实隔离（41 提案：schema 16、world_id_normalization 2、jcs 2、其余 15 规则各 1–3；回执 7/7）；53 条为 `world_id_norm` 拼写反例，**独立验证其别名键名被层 1 schema 正则命中**（因此关掉层 2 仍被 schema 拒，按设计不隔离）；17/17 规则均有至少 1 条真实隔离对照；`--disable` 未名规则 rc=2、`context_identity` 不可关闭、已知规则可关。

## 9. 无任意隐写通用证明

字段名检查（两层）只能证明「键名形态」被拒，不能证明合法键的值不承载外部真值：实测把冻结上下文的真实实体 ID `entity-7f3a41c9b2e05d18` 放进合法字符串参数值 → **accepted**。B4 文档 §13 第 3/4 行已如实写「不能/未实现，也不在本轮承诺」，本复核确认该自述诚实；因此**不存在**「任意隐写已消除」的通用证明，也不应把本卡通过写成该证明。裁决 2 只要求字段级禁止，故不阻断 r4。

## 10. 一级 B1 文档 vs Claude 原 11 条（裁决/形式化分开）

| 重点主张（B1 协调页） | 一级裁决层 | 二级形式化层（B4 r4） |
|---|---|---|
| 运行命令沿用既有 Event `source=command`；不新增 `student` 枚举；不产生 E3 持久提交 | 成立：AWZ `event.v1.schema.json` source enum 含 `command`、全文无 `student`；E3 裁决 5「非用户只能预览、提交须用户确认/授权」 | 成立（定义层）：交付物无 E3 写入实现；运行路线仅门禁判定 + 后续观察 |
| 编辑能力集合为空 | 成立（原裁决 1） | 成立：112 份上下文 `registered_edit_abilities == []`；非空即上下文 fail-closed；编辑类提案 `effect_class_not_registered`，关规则放行 |
| TTL 闭区间不变、不因控制租约改变 | 成立（原裁决 4 原文即闭区间） | 成立：两端点正例 accepted、右端+1 `proposal_expired`；代码 `decided_at > valid_until`；核对器无 lease 逻辑 |
| AWZ 经历 `external_derived` 默认不可训练 | 成立（ADR-0005 原文） | 未实现（原裁决 11 同口径，只在文档写明） |
| confidence/学生自填量不能成为权限来源 | 成立（原裁决 6） | 成立：184 行扫描 0 变化 + 专用反例；造假接线仅在 `confidence=1.0` 且关闭专用规则时生效 |

逐条裁决映射：**一级裁决 11/11 成立**（未改 TTL/来源政策/观察契约/冻结参数/权限）；**二级形式化 10/11 有独立证据**（裁决 1–10；裁决 11 如实未实现）。B1 文档 SHA 与其报告声明一致；原 11 条 SHA 与 B4 输入声明一致。

## 11. 发现（均非阻断）

| ID | 严重度 | 内容 | 建议 |
|---|---|---|---|
| B6-F1 | minor·证据完整性 | `metrics.json.artifacts` 与 relay B4 report data 的核对器哈希陈旧（`9cf0d90b…`，磁盘/清单 `37d4308f…`） | 统筹验收以 `SHA256SUMS.txt` 为准；作者补一行勘误 |
| B6-F2 | minor·代码缺陷（fail-closed） | `check_schema_props_forbidden` 对 forbidden 属性名调用未定义的 `here()` → `NameError`；CLI 兜底 `schema_invalid`（已验证无 traceback、真实非零），但干净拒绝路径退化为内部错误；作者矩阵用 `lite_problems` 未覆盖 | r5 修一行，并把该路径纳入矩阵端到端断言 |
| B6-F3 | minor·文档一致性 | `SKILL_PROPOSAL.md:139`「60 行全过」vs 实际 184；`r4/SUMMARY.md:12`「253 行」vs 实际 254 | 改数字 |
| B6-F4 | 观察 | `observable_registry.source_sha256` 是路径字符串哈希，不是 AWZ 文件内容哈希 | 未来绑定内容 SHA 或改字段名 |
| B6-F5 | 观察 | `quantity_forbidden_alias` 分支按构造不可达 | 不必计为额外覆盖 |
| B6-F6 | 观察 | 输入 JSON 重复键不 fail-closed（最后值获胜） | 所有输入 `load_json(strict=True)` |
| B6-F7 | 观察 | 值级偷带可接受；无任意隐写通用证明 | 如实保留，档位维持「字段级」 |
| B6-F8 | 观察 | r3 archive 自指清单行占位（空哈希）；「124 文件」含清单自身（payload 123） | 措辞改「123 文件＋清单」 |
| B6-F9 | 观察 | B5 两个汇总文件当前哈希与其报告 data 记录不同（自指类）；关键回归输入哈希一致 | B5 负面发现可按原样使用 |

## 12. 产物与命令

- 报告：本文件；指标：`metrics.json`；产物哈希：`SHA256SUMS.txt`；明细 JSON：`results/*.json`（probe/fixture/gate/jcs/suite/awz_quantity/b1_doc/baseline）。
- 脚本：`tests/indep_lib.py`（自写 JCS/分类器）、`verify_probe.py`、`verify_fixtures.py`、`verify_gate_checks.py`、`verify_jcs_cli.py`、`verify_suite_copy.py`、`verify_awz_quantity.py`、`verify_b1_doc.py`、`collect_metrics.py`。
- 运行环境：`/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python`（含 jsonschema）；纯 CPU。
- 实际命令（全部在 `reports/V-V9-B1/r4-independent/tests/` 下、`cd /Users/mac/AinerWorkFlow/AinerZero` 后）：`indep_lib.py selftest` → `verify_probe.py` → `verify_fixtures.py` → `verify_gate_checks.py` → `verify_jcs_cli.py` → `verify_suite_copy.py`（副本 `--suite` ×2）→ `verify_awz_quantity.py` → `verify_b1_doc.py` → `collect_metrics.py`；各脚本 `*_VERDICT PASS`（`GATE/JCS/FIXTURE/SUITE/AWZ_QUANTITY/B1DOC/PROBE`）。

## 13. 失败、限制与未验证

- 未验证：真实 AWZ 门禁/内核/`WorldBrainAdapter`、参数值语义与任意隐写、裁决 11 `final` 训练门、句柄实体解析、E3 编译与编辑授权（均为交付自述未实现）。
- 未在大小写敏感文件系统（Linux CI）复跑；casefold/inode 结论限本机 APFS。
- 复核过程中发现、但**未**作为 r4 判据的历史观察：B5 两个汇总文件哈希与其报告 data 记录不同（B6-F9，关键输入一致）。
- 复跑路径说明：`--suite` 在 `/tmp` 仓库副本运行以保持真实交付目录只读；真实目录在本轮前后逐字节不变（`results/baseline_manifest.json` 可重算验证）。
- 测试通过 ≠ 能力通过；本报告不构成运行授权，不自行 accept。

## 14. 交回统筹（需要决定）

1. 是否按本次证据**验收 B1 + B4 r4**（建议验收；B6-F1/F2/F3 建议随下一次修订补正，不阻断）。
2. B6-F2（NameError）是否要求 r5 修一行并把登记条目 forbidden 属性名路径纳入端到端矩阵。
3. B6-F6（输入重复键）是否列为下一张代码卡的必须项；B6-F4（source_sha256 语义）是否要求在对接真实 AWZ 前改为内容哈希。
4. B1/B4 的最终验收由一级统筹办理；本卡只提供独立证据与区分（一级裁决 vs 二级形式化）。
