# r6-candidate 新勘误（B6-F1 / B6-F3 / B6-F8；只登记，不改旧报告/文档/原 r4）

范围：只在本文件登记勘误。`docs/v9/SKILL_PROPOSAL.md`、`reports/V9-B1/r4/SUMMARY.md`、B6/B8/B9 原报告、
Relay 历史记录与 r4 交付物一律只读、未改。来源：B6 复核报告 §11（B6-F1/F3/F8）+ 本轮 r6 复核实测（`_evidence-baton6/`）。

## B6-F1（证据完整性：陈旧哈希）
- 问题：`reports/V9-B1/metrics.json.artifacts` 与 Relay B4 report data 里核对器哈希为旧值 `9cf0d90b…`；
  原 r4 磁盘/清单实际为 `37d4308f34a64bad515a8ef44b0c9a12b8bf6f35c24a628730280c3ad50328da`。
- 勘误：以 `reports/V9-B1/SHA256SUMS.txt` 与原 r4 最终字节为准；旧报告数据不改。r6 新身份清单把原 r4 核对器
  `37d4308f…` 列为只读输入（RAW 列可逐行重算），不再依赖旧 metrics 自述。

## B6-F3（文档一致性与行数口径）
- 问题：`docs/v9/SKILL_PROPOSAL.md:139` 写「60 行全过」，实际为 184 行；`reports/V9-B1/r4/SUMMARY.md:12` 写「253 行」，实际 254。
- 勘误：正确数字为 **184** 与 **254**；两份文档只读未改，本勘误随 r6 交付。

## B6-F8（r3 archive 清单口径）
- 问题：r3 archive 自指清单行为占位（空哈希）；「124 文件」实际为 123 payload + 清单自身。
- 勘误：口径应为「123 payload 文件 ＋ 清单自身（自指行不记哈希）」；旧归档未改。

## 已修项（r5 继承；r6 本轮重新实测复核，非改旧报告）
- B6-F2：`check_schema_props_forbidden` 未定义 `here()` → r5 修；本轮非法登记属性名（含嵌套 `worldId`）rc=1 `forbidden_property` 干净、无 traceback；
  单关关键字层或单关递归层仍拒，两层全关后 accepted（真漏检证据在 `_evidence-baton6/gate/`）。
- B6-F4：`source_sha256` 改为 AWZ 固定 Observation 文件内容 SHA `01be45e0…`；旧路径哈希 `a2971c9a…` 保留为 `source_path_sha256`，
  迁移显式；漂移/缺失/旧路径 pin 一律拒绝（证据同上）。
- B6-F6：所有 JSON 入口 strict 重复键拒绝（proposal/context/reply/fixture/回归输入）；本轮修 suite 回归输入
  `reports/V-V9-B1/probe_variants.json` 重复键的干净 fail-closed（原为未捕获 ValueError traceback）：rc=1、all_ok=false、stderr 0B。
- 值级隐写通用证明：仍不提供，档位维持字段级（如实保留）。
