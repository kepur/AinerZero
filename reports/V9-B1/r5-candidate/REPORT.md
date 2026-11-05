# ainerzero.V9.B7 执行报告：B6 残留加固与证据勘误候选（r5-candidate）

角色：executor（二级执行层）；负责人：deepseek-flash-b7r5（注册 ID 见 relay）；时间：2026-10-17
任务状态：reported；实验状态：未执行（纯 CPU，无训练/MLX/ORT/下载/付费/git 提交）
文件范围：仅 `reports/V9-B1/r5-candidate/`；未改 src、contracts、docs、已验 r4 字节。

## 1. 输入与原 r4 保持

- 原 `reports/V9-B1/check_skill_proposal.py`（r4）字节未改；本候选为独立副本 `reports/V9-B1/r5-candidate/check_skill_proposal.py`。
- 原夹具 `contracts/v9/examples/skill_proposal_v1/` 与 `reports/V9-B1/sabotage-schemas/` 只读；候选生成自己的夹具到 `reports/V9-B1/r5-candidate/fixtures/` 与 `sabotage-schemas/`，不原位覆盖。
- B6 发现 B6-F1/B6-F2/B6-F3/B6-F4/B6-F6/B6-F8 作为新勘误处理，不改旧报告。

## 2. 本候选修改点

1. B6-F2：`check_schema_props_forbidden` 未定义 `here()` → 干净拒绝（无 traceback、真实非零），现在使用局部尾缀拼接，输出 `forbidden_property:<name>`。
2. B6-F6：所有 JSON 入口 strict=True（proposal/context/reply/fixture/suite），重复键 → `ValueError` → fail-closed `schema_invalid`，无 traceback。
3. B6-F4：`source_sha256` 改为 AWZ 固定 Observation 文件内容 SHA `01be45e0...`；旧路径字符串哈希 `a2971c9a...` 保留为 `source_path_sha256`（迁移证据）；AWZ 文件缺失/不可读/内容漂移一律 fail-closed（`context_observable_source_unavailable` / `_unreadable` / `_content_drift`）；支持 `AWZ_OBSERVATION_PATH` 隔离测试，不改真实 AWZ 文件。迁移明确，不静默重 pin。
4. 原 r4 的 `context_observable_source_sha256` 检查改为内容 SHA；新增 `source_path_sha256_drift` / `source_content_drift` / `source_unavailable` / `source_unreadable`。
5. suite 默认只读：不写 `check_result.json` / `SHA256SUMS.txt`；仅 `--output-dir` 显式输出目录写入，输入与输出分离。

## 3. 验证

- `--suite`（只读对比）两次：`all_ok=true`，112 用例（18 正/94 反）、94 对照（41 真隔离）、10 回执、184 置信度扫描、18 JCS 自测、236 夹具 0 大小写/inode 碰撞。
- 重复键反例：构造含重复键的提案 → rc=1、`proposal_unreadable:ValueError`、无 traceback。
- 非法属性名反例：上下文登记含 `world_id` 属性 → rc=1、`forbidden_property:world_id`，干净拒绝；关闭 `world_id_normalization` 仍由注册/上下文门拒绝（不静默放行）。
- 来源绑定：`source_sha256` 现为 AWZ 内容 SHA；旧路径哈希保留；漂移拒绝。

## 4. 新勘误（不改旧报告）

- B6-F1：`metrics.json.artifacts` 核对器哈希陈旧（`9cf0d90b…`），以 `SHA256SUMS.txt` 为准。
- B6-F3：`SKILL_PROPOSAL.md:139`「60 行」vs 实际 184；`r4/SUMMARY.md:12`「253 行」vs 实际 254。
- B6-F8：r3 archive 自指清单行占位；「124 文件」应为「123 文件+清单」。

## 5. 未验证 / 限制

- 值级隐写通用证明仍未提供，维持「字段级」档位。
- TTL/来源资格/冻结政策未改。
- 真实 AWZ 门禁/内核/WorldBrainAdapter、句柄解析、E3 编译未验证。
- 测试通过 ≠ 能力通过；不构成运行授权；待独立复核后再决定采用。

## 6. 产物

- `reports/V9-B1/r5-candidate/check_skill_proposal.py`
- `reports/V9-B1/r5-candidate/fixtures/`、`sabotage-schemas/`
- `reports/V9-B1/r5-candidate/check_result.json`、`SHA256SUMS.txt`、`metrics.json`
- 本报告 `reports/V9-B1/r5-candidate/REPORT.md`
