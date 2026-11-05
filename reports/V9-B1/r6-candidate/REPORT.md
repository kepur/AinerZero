# ainerzero.V9.B7 交付报告（第 6 棒 deepseek-flash-b7r6，2026-10-18，参数 v1）

角色：二级执行层；纯 CPU；未训练/未下载/未调付费；只改 `reports/V9-B1/r6-candidate/`；不提交、不采用、不改旧证据。
base 核对（开工前）：`r5-candidate/check_skill_proposal.py` = **`5b28818b02f5a380355e673eda66fd73911f054284369079aa1cf6668ab87b9f`**（与 v1 `base_candidate_sha256` 逐字一致）；承接 r6 = `d902876a8e5aa1af58d1e3a974c099d847cadae2b79f1956037b2186eafa8c0b`；**新候选 checker = `9f88993a5aab97dfb2326e7a71ff556ffbe6fdab54850a0bde5e73aacd6944bc`**；原 r4 = `37d4308f34a64bad515a8ef44b0c9a12b8bf6f35c24a628730280c3ad50328da`（未改）。
1. **打回项 1（证据身份）已修**：旧 r5 时代 `SHA256SUMS.txt`/`check_result.json` 原字节移入 `_identity-r5-stale/`（显式标旧）；r5 时代聚合清单 `R6_SHA256SUMS.txt` 也移入同目录标旧。B9 守卫拒绝向候选目录自身写入输出证据，因此当前 r6 身份**不**写根目录，以 `_evidence-baton6/staging-run1/check_result.json`（sha256 4fb8d5c3…，inode 差异除外）与同目录 `SHA256SUMS.txt` 为准；checker 行=`9f88993a…`，原 r4 核对器 `37d4308f…` 为只读输入。
2. **打回项 2（B8-F4）已修**：suite 回归输入 `reports/V-V9-B1/probe_variants.json` 重复键 → **rc=1、all_ok=false、`failures=['probe:b5_probe_variants_unreadable']`、stderr 0B、无 traceback**；关 strict 对照副本 → rc=0/all_ok=true（证明是解析拒绝而非异常退出）。
3. **输出路径守卫不回退**（隔离 staging 复测）：输出=输入同路径/祖先/后代/符号链接别名/普通文件/已含证据/`AWZ_OBSERVATION_PATH` 来源被覆盖 共 **11 负例 rc=2、stderr 0B、写文件前拒绝**；已含证据时两文件 SHA 前后不变；合法全新隔离输出 rc=0/all_ok、恰写 2 文件。
4. **入口 fail-closed**（gate/reply 实测）：proposal/context/reply 重复键 rc=1 干净（`proposal_unreadable`/`context_unreadable`/`reply_unreadable:ValueError`，无 traceback）；非法登记属性名（含嵌套 `worldId`）rc=1 `forbidden_property` 干净；单关一层仍拒、两层全关 accepted（真实漏检）；fixture 字节篡改 → 干净 `FIXTURE MISMATCH` rc=1。
5. **来源绑定真实内容**：AWZ 文件内容 SHA=`01be45e0…`=核对器常量；旧路径哈希 `a2971c9a…` 保留为 `source_path_sha256`+迁移说明（不静默重 pin）；旧路径 pin 拒 `context_observable_source_sha256`；内容漂移/缺失拒 `context_observable_source_content_drift`/`_unavailable`；关来源守卫对照 accepted（真实漏检）。
6. **默认只读（真实候选）**：`--suite` rc=0/all_ok=`true`/`cases_total=112`(18 正/94 反)/stderr 空；运行前后 **r6 候选树、r4、r5-candidate、旧 B8 目录、B9 目录 5 份 SHA 清单逐条 diff 为空**。
7. **原 r4/旧证据不变**：r4 目录 1 文件与 r4 核对器 `37d4308f…` 未改；r5-candidate 437 文件全字节只读未动；旧 B8/B9 证据未动；旧 r5 候选保持全字节只读。
8. **F1/F3/F8 仅新勘误**（见 `ERRATA.md`），旧报告/文档/原 r4 一律不改；F2/F4/F6 修正由 r5 继承，本轮以 4/5 实测复核。
9. **诚实披露**：r5 第 1 棒首版（0 分钟）字节无存档 → **不可恢复，未重建、未冒充**；r6 旧版 `d902876a` 存 `_evidence-baton6/baseline/`；Relay 历史负面原样保留。
10. **未验证/限制**：未做非作者复核（须另派，本卡不自证通过/NOT adopted）；值级隐写无通用证明（档位仍字段级）；未改 TTL/来源资格/冻结政策；未验证真实 AWZ 门禁/内核/WorldBrainAdapter；`--regenerate` 未用（复核禁用）；测试通过 ≠ 能力通过，不构成采用或运行授权。
11. **交付物**：`check_skill_proposal.py`、重生成 `check_result.json`+`SHA256SUMS.txt`、`REPORT.md`、`metrics.json`、`ERRATA.md`、`_identity-r5-stale/`（含 r5 时代 `SHA256SUMS.txt`/`check_result.json` 与标旧的 `R6_SHA256SUMS.stale.txt`）、`_evidence-baton6/`（基线/守卫/重复键/gate/真实只读/staging 输出+rc+哈希）。
建议：新 SHA 交回，由**非 B7 历史作者**复核后再决定采用；本轮不发布 B10，无训练或采用授权。
