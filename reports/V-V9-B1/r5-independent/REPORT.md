# ainerzero.V9.B8 执行报告：B7 候选 r5-candidate 的非作者独立复核（含原 r4 不变性）

角色：非作者二级执行（verify）；执行者 **deepseek-h7m2**（tier2）；时间：2026-10-17 09:03 起，2026-10-18 08:5x 恢复补证
状态：**reported 证据针对 B7 候选 SHA `5b28818b…`；建议不采用该候选**（只交建议，未采用/未改旧 r4/未动模型/未下载）
文件范围：只写 `reports/V-V9-B1/r5-independent/` 与 `/tmp`；候选、原 r4、contracts、docs、真实 AWZ 全部只读（F 阶段逐字节复核）。
复核边界：纯 CPU 只读核对与工程测试；无训练/MLX/ORT/GPU/下载/付费/授权、不提交不推送、不改既有证据。

## 摘要（结论）

1. **原 r4 全字节不变：确认。** r4 自清单 254/254 行 raw 重算通过（JCS 列 241 通过 + 3 个 `jcs_error` 均为含 2⁵³/孤立代理项夹具的既定口径）；对 B6 已验收 baseline 448/448（11 交付物+7 输入+236 夹具+193 破坏 schema+AWZ）逐项一致；B6 采集后 0 个 r4 文件被改动；我的全部复核动作后 764 个 r4 文件、437 个候选文件、383 contracts、3 docs、2 回归输入、AWZ 来源逐字节不变（含 mtime/inode）。
2. **候选身份：确认。** 候选 check_skill_proposal.py = `5b28818b…`（与一级消息一致），r4 = `37d4308f…`，AWZ Observation 文件内容 = `01be45e0…`（= 候选 pin），旧路径哈希 `a2971c9a…` 可重算。
3. **重复键 fail-closed：proposal/context/reply 三入口确认。** 候选均 rc=1、`schema_invalid`、`*_unreadable:ValueError`、**无 traceback**；关掉 strict 的副本与 r4 对同一输入均真实 accepted（不是异常退出）——其中提案重复键把被禁 `world_id` 块藏在被丢弃的前值里，r4/关守卫副本会放过，证明该守卫承重。
4. **fixture/suite JSON 入口：部分成立、有缺陷。** 已提交夹具被篡改（含重复键/新增文件）由更早的逐字节比对干净拒绝（`FIXTURE MISMATCH`，rc=1，无 traceback）；但 suite 的回归输入 `reports/V-V9-B1/probe_variants.json` 含重复键时抛**未捕获 ValueError（rc=1 + traceback）**，不满足“干净 fail-closed”；关掉该入口 strict 的副本能完整跑完 `all_ok=true`，说明 strict 载入承重但失败形态不干净（F4）。
5. **非法登记属性名：确认干净拒绝。** 候选 rc=1、decision=null、`entry:…:forbidden_property:world_id`、无 traceback；`--disable world_id_normalization` 不绕过；r4 同输入退化为 `gate_internal_error:NameError`。隔离对照：只关 `check_schema_props_forbidden` 仍被 `param_schema_problems` 拒（冗余层）；**两处登记属性名检查全关后同一反例 decision=accepted（真实漏检，非异常退出）**（F5）。
6. **来源内容绑定：确认 fail-closed。** 真实 AWZ 文件 SHA 与候选内容 pin 一致；缺失/不可读/内容漂移（context 的 source 路径字符串不变）分别 rc=1 + `context_observable_source_unavailable/_unreadable/_content_drift`、无 traceback；旧路径哈希 pin 被拒（不静默迁移）；`source_path_sha256` 漂移、篡改 context 的 source_sha256 均被拒；全 `--disable` 组合不能绕过；关掉运行时校验的副本对同一缺失/漂移输入 accepted（真实漏检）；r4 旧 pin 在 `AWZ_OBSERVATION_PATH` 指向不存在文件时仍 accepted（复现 codex #166 的旧 fail-open），r5 已翻转。
7. **suite 实跑：默认只读确认；显式输出可复现但不是“新目录隔离”。** 默认 `--suite` rc=0、all_ok=true、候选/r4/contracts/docs 树 0 增删改、无 traceback（84.8s）；显式 `--output-dir` 两次运行确定性一致，`check_result.json` 与作者既有文件**逐字节一致**（`ef9a4bd1…`），counts 与 metrics 全等（112/18/94/17 规则/94 对照/41 真隔离/10 回执/184 扫描/236 夹具）。
8. **必修缺陷 F1（高）：显式 `--output-dir` 不拒绝与输入/旧交付目录重叠，会覆盖既有证据。** 在 /tmp 隔离副本实测：指向原 r4 交付目录、候选交付目录自身、输入 fixtures 目录三类均 **未拒绝**（rc=0/all_ok=true），并覆盖该目录下既有 `check_result.json`+`SHA256SUMS.txt`。这独立复现了 B9 的 F1 实证，直接回答 codex #167“会否覆盖需拒绝”：**会覆盖，且没有拒绝**。
9. **作者证据问题（F2/F3/F6/F7）：** 候选 `SHA256SUMS.txt` 的 REPORT.md 行陈旧（清单 `e128141f…` vs 磁盘 `dcd6fa8e…`，与 B6-F1 同类复发）、2 行继承标签变 MISSING（COORDINATOR_DECISIONS.md、r4/SUMMARY.md）；清单把候选自身交付物标成原 r4 物理路径但哈希是候选副本，按物理路径直核对会误判 r4 被改（F3）；候选目录无首版（被打回版）归档且报告未披露不可恢复（F6，B9 同结论）；`verification_logs/` 仅 duplicate_key/illegal_property 两条，无四入口/来源三反例/suite 实跑日志（F7）。
10. **建议（只建议）**：不采用当前 r5 候选；优先修 F1（输出目录/输入重叠在写前明确拒绝）与 F2/F3（清单自洽与路径口径），补 F4/F6/F7 的干净失败与证据；B7 v1 已改为 r6-candidate 修输出重叠，**r6 需另做非作者复核**，本报告不作为 r6 的预判。

## 1. 被验对象与身份（自行重算）

| 对象 | SHA256 |
|---|---|
| 候选 `reports/V9-B1/r5-candidate/check_skill_proposal.py` | `5b28818b02f5a380355e673eda66fd73911f054284369079aa1cf6668ab87b9f` |
| 原 r4 `reports/V9-B1/check_skill_proposal.py`（验收基线） | `37d4308f34a64bad515a8ef44b0c9a12b8bf6f35c24a628730280c3ad50328da` |
| AWZ `contracts/v9/observation_packet.v1_1.schema.json` | `01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb` |
| 候选 REPORT.md / metrics.json / check_result.json | `dcd6fa8e…` / `4caec020…` / `ef9a4bd1…` |
| r4 REPORT.md / metrics.json / check_result.json / SHA256SUMS.txt | `4ad05236…` / `3bca7f7e…` / `10e65404…` / `336afc61…` |
| 解释器 | `/usr/local/bin/python3` 3.12.2，jsonschema 4.21.1（本机唯一带 jsonschema 的解释器；作者 pyc 为 cp312 一致） |

候选 vs r4 差异：checker +54/−22 行；236 个夹具中 114 个字节不同（113 contexts/EXPECTATIONS 的 source 内容 SHA 迁移 + EXPECTATIONS 本身；valid/invalid/replies 未变）；193 个破坏 schema 逐字节相同。作者清单另有 251/254 raw 对、REPORT 行陈旧、2 MISSING（见 F2/F3）。

## 2. 独立方法（不复用作者 oracle/日志）

- 自写 JCS（RFC 8785：UTF-16 码元键排序 + ES6 Number::toString）重算 context pin，与作者 112 个 `context_identity_pins` 交叉核对 **112/112 一致**；自写文本手术构造重复键字节；自建 /tmp 隔离副本做守卫关闭对照与输出覆盖实验。
- 三态对照：候选原脚本（守卫在）→ 期望拒绝；同一候选关守卫副本 → 期望真实漏检；原 r4 → 记录其真实旧行为。**全部对照来自真实子进程 rc，不采信作者硬编码结论。**
- 原始记录：`results/logs/*.jsonl`（每次运行 argv/env/cwd/rc/stdout/stderr/时长）、`COMMANDS.md`（170 条原始运行记录与 rc 汇总，含脚本迭代重跑；最终有效为 38 条 CLI 探针 + C 阶段 7 次 suite + D 阶段 4 次 suite）、`identity.json`、`results/original-author-logs/`（作者两条原始日志副本+哈希）。

## 3. 逐项取证（数字均来自原始运行记录）

- r4 不变：`results/A-identity-summary.json`、`F-final-identity-summary.json`；默认只读前后树差：`C-suite-summary.json c1_default_readonly.tree_diff`。
- 重复键：`B-entries-source-summary.json runs[]` 的 `dup-proposal-* / dup-context-* / dup-reply-*`（含 r4 与 strict-off 对照）。
- 非法登记属性名：`registry-illegal-* / registry-illegal-nested-*`（含 disable、propguard-off、双关、r4 NameError 对照）。
- 来源三反例：`source-missing/unreadable/drift*`、`source-old-pin-*`、`source-path-sha-drift`、`source-adv-ctx-sha`、`source-missing-all-disable`。
- fixture/suite 入口：`D-fixture-suite-summary.json`（D1/D3 干净 `FIXTURE MISMATCH`；D2 traceback；D2b strict-off all_ok）。
- suite 输出与覆盖：`C-suite-summary.json`（c1/c2/c3）；作者 check_result 与我重跑逐字节一致见 c2.vs_author。
- 作者原日志：`results/original-author-logs/`（duplicate_key.log、illegal_property.log 及 SHA256；内容与我复现一致）。

## 4. 未验证 / 限制

- 只读核对与 CPU 工程测试；值级隐写通用证明仍未提供（维持字段级），TTL/来源资格/冻结政策未改、未扩范围。
- 未验证真实 AWZ 门禁/内核/WorldBrainAdapter/句柄解析/E3 编译；候选是参考核对器，不是生产实现；测试通过≠能力通过，不构成采用或运行授权。
- F1 覆盖实验只在 /tmp 隔离副本做；真实旧交付字节由 F 阶段确认不变。
- 时间线：本任务 2026-10-17 09:03 领取，A/B/C 完成后 D 中断；2026-10-17 20:59 租约到期被回收（非失败），2026-10-18 08:45 会话恢复后补交“exec 组空”归档、补齐 D/F 与证据。B8 目前因前置 B7（进行中）不可重领；若一级把 r6 复核另派，本报告仅覆盖 r5 候选 `5b28818b…`。
- 首版（被打回版）字节不可恢复：候选目录无归档，relay 历史仅报告文本；如实披露，不重建冒充。

## 5. 产物

`REPORT.md`、`metrics.json`、`identity.json`、`COMMANDS.md`、`SHA256SUMS.txt`、`tests/`（indep_lib + A/B/C/D/F 五个复核脚本，均可复跑）、`results/`（A/B/C/D/F summary、logs、suite run1/run2、baseline before/after、candidate-vs-r4.diff、original-author-logs）。
