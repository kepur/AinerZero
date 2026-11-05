# ainerzero.V9.B4 修订 r2

角色：二级 grok-m4q8。未改裁决文件，未覆盖 `reports/V9-B1/REPORT.md`。不自行 accept。

## 打回项

上一轮正例把 `expected_outcomes[0].quantity` 改成 `world_id` 或 `hidden_contact` 时，schema 和参考门禁都接受；`params` 里的 `worldId`、`entityID` 也被 schema 接受。

## 封堵

- 键名禁令加上驼峰 `worldId` / `entityID` / `sceneId` / `eventId`，以及 `hidden_contact` / `hiddenContact`。
- `quantity` 的值不得是 `world_id`、`entity_id`、`scene_id`、`event_id`、`instance_id`、`hidden_contact`（含作为点分路径的一段）。

## 证据

命令：`/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite`  
经 `relay exec ainerzero.V9.B4` 运行，退出码 0，用时 19.5 秒。`all_ok=true`。

| 新增反例 | 基线 | 关掉对应检查 |
| --- | --- | --- |
| `quantity_value_world_id` | `schema_invalid`，退出码 1 | 漏检为 accepted |
| `quantity_value_hidden_contact` | `schema_invalid`，退出码 1 | 漏检为 accepted |
| `world_id_camel_in_params` | `schema_invalid`，退出码 1 | 漏检为 accepted |

整套：40 条提案用例（8 正 / 32 反），32/32 破坏对照隔离漏检；回执 7/7；置信度扫描 60/60；JCS 自测 18/18。

SHA256：

- `docs/v9/SKILL_PROPOSAL.md` `207ac1e00e8f00e27ce8bccd835ac0aeb787efae5991492cdf9ee0c480166e98`
- `contracts/v9/skill_proposal.v1.schema.json` `dc6915a12d1c66527df4dcc4352b3b010c64dbfe329f4698de7fe00a9983f486`
- `reports/V9-B1/check_skill_proposal.py` `d7b928f33ee4be2e50019340e02c2791e3c883bb84f754418229ba386e56a33b`
- `reports/V9-B1/COORDINATOR_DECISIONS.md` `04504c33643c30b3116abe5cd8430fe2bc0e8f44fa70154b9c2f892f93a6d113`（未改）

原 `REPORT.md` 里的旧哈希对应当时文件，本修订改过 schema、核对脚本和夹具后不再相等。

未验证：没有真实 AWZ 门禁，没有训练。测试通过不等于能力通过。
