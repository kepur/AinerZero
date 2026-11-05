# ainerzero.V9.B4 执行报告

角色：executor（二级执行层）；负责人：`deepseek-flash-a7k2`（deepseek-flash）；时间：2026-10-16 14:52 +0300
任务状态：**reported**；实验状态：**未执行真实运行**（纯 CPU 契约与参考核对，无训练、无 MLX/ORT、无下载、无付费）
任务依据：`reports/V9-B1/COORDINATOR_DECISIONS.md`（裁决 1–11 与「执行与证据」）＋ `ARCHITECTURE_V9.md` r5 §2/§3、ADR-0012 §26/§36、ADR-0005、Event/v1 r2 F2/F4、`ObservationPacket/v1.1`、`reports/P3-E3/r1/COORDINATOR_DECISIONS.md` 裁决 4/5/13、`docs/v9/TEACHERS_AND_CACHE.md` 时间域口径
参数：v0 `{}`（照用未改）

## 摘要

按裁决 1–11 出齐三份 schema（提案、门禁可见回执、能力登记条目草案）、规范、正反例与 CPU 参考核对。
参考核对在**明确标 `synthetic: true` 的冻结上下文**里判定，上下文与待验提案分离成文件，预期身份由调用方用
`--expected-context-sha256` **固定**（同 T1 r3 裁决 5 的做法）。

**结论：37 条用例全过（8 正例 accepted / 29 反例 rejected）；15 条规则各配独立反例与「关掉该检查后本反例漏检」的破坏对照，
29/29 提案对照与 7/7 回执对照全部真实非零且隔离；18/18 JCS 自测通过；63/63 独立世界 ID 探针被 schema 拒绝。**
测试通过不等于能力通过：本轮没有真实 AWZ 回合、没有门禁实现、没有内核求值，也没有任何模型参与。

## 输入身份（全部只读，未改）

| 文件 | SHA256 |
|---|---|
| `reports/V9-B1/COORDINATOR_DECISIONS.md` | `04504c33643c30b3116abe5cd8430fe2bc0e8f44fa70154b9c2f892f93a6d113` |
| `ARCHITECTURE_V9.md` | `0f54a96ace5b9c6fad2f3a16f3e6417a2f521fe131a13400263a0f5d9920f2a4` |
| `docs/v9/TEACHERS_AND_CACHE.md` | `a5b5d07556e899905add48158e6252a206e0b19daddf4b7ffa8e96125f36e636` |
| `contracts/v9/teacher_cache.v2.schema.json` | `e8ca43e9e1359a6d8315c3c72e642de476e1495d19a2bb713f665cec81fe9f76` |
| `AnimeWorldZero/contracts/v9/observation_packet.v1_1.schema.json` | `01be45e0adfdac74d00d3f4affd2dce52ce5596f23c3def974b14998bd0830eb` |
| `AnimeWorldZero/contracts/v9/observation_leak_rules.v1_1.json` | `5a53affd4ee437ba130d9ebddc066f71d50a30598caa6b2d1ffedf392fbe931d` |
| `AnimeWorldZero/docs/design/EVENT_PROTOCOL.md` | `cb105a4edabcafb9c65e56a38fc33658d90b02c73c0e7ddd97f5f1092d0ee130` |
| `AnimeWorldZero/reports/P3-E3/r1/COORDINATOR_DECISIONS.md` | `3043ed0e2f2cd6991c1c92feaabd519414b3ef9de213136114c88a81e962acfb` |
| `AnimeWorldZero/reports/V9-A8/r2/COORDINATOR_DECISIONS.md` | `da74328f8ea38fe4d0012abcaf0a5f71b783abfe3ac5dd1eec0a372f9c8ecde0` |

`reports/V9-B1/COORDINATOR_DECISIONS.md` 逐字节未改（`git diff` 为空）。

## 修改文件（全部为新建，无覆盖、无删除）

| 文件 | 目的 | SHA256 |
|---|---|---|
| `contracts/v9/skill_proposal.v1.schema.json` | SkillProposal/v1 | `09d90541faeb8aa6015ea157824394e4e2964f43207e0b6224b9b110248bcb4a` |
| `contracts/v9/skill_gate_reply.v1.schema.json` | 门禁可见回执（世界脑可见版） | `dc81852c0dc6341a033bcf9ed70c969091faae541e775c4682cb0ce6f1840f2c` |
| `contracts/v9/ability_registry_entry.v0.schema.json` | 能力登记条目草案 | `1f087c7f95f9a8451312529816915e811ca648d25ebca7bdcaa44d6bf7080d60` |
| `contracts/v9/examples/skill_proposal_v1/` | 冻结上下文 38、正例 8、反例 29、回执例 10、`EXPECTATIONS.json`、`contexts/expected-identity pins` | `EXPECTATIONS.json` `38de15370aafff1a07b1f1b2f6cfcab98fbf5d364309e0b89f9a4dd837c038c7`；`contexts/baseline.json` `01c3c2eeab2df151201aedd3fb72dd88e29e58aad434e02c7d967b3966f9dcbf` |
| `docs/v9/SKILL_PROPOSAL.md` | 规范（§13 裁决 1–11 闭合表） | `097231af00ce0b68164723fe68e17e6f204d20e5815781e11c68b1ac11fc04a5` |
| `reports/V9-B1/check_skill_proposal.py` | 参考核对（JCS + 门禁 + 破坏对照） | `d6210c4b8fd94c210f4f198febf2f8b1313fd01a81b0cf276f8b6eb3bdc32ef3` |
| `reports/V9-B1/check_result.json` | 逐条结果 | `1d8545bd89e40b108d64347c08f68d6024b23d5dc0bcc392b99383e4e7de0619` |
| `reports/V9-B1/metrics.json` | 指标 | 见文件 |
| `reports/V9-B1/sabotage-schemas/` | 8 份变异 schema + 54 份置信度扫描变体（**仅供破坏测试**） | — |

范围外只新增了一个接力台用的隐藏资料文件 `.relay_profile_deepseek-flash-a7k2.json`（注册 profile，任务要求先写）。
未碰 `reports/V-V9-T1-r3/**` 等其他 agent 的未提交改动。

## 实际执行

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
# 1) schema 元校验（三份，独立于套件）
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -c "import json;from jsonschema import Draft202012Validator as V;\
[V.check_schema(json.load(open(p))) for p in ['contracts/v9/skill_proposal.v1.schema.json',\
'contracts/v9/skill_gate_reply.v1.schema.json','contracts/v9/ability_registry_entry.v0.schema.json']]"

# 2) 参考核对套件（生成全部夹具 + 逐条子进程核对 + 破坏对照 + 置信度扫描 + JCS 自测）
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite
# → {"all_ok": true, "failures": [], "control_failures": []}  exit 0

# 3) 确定性复跑（第二次 byte-identical）
cp reports/V9-B1/check_result.json /tmp/cr1.json
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite
diff -q /tmp/cr1.json reports/V9-B1/check_result.json   # → 无差异

# 4) 单条核对（非零即拒）
… check_skill_proposal.py gate --proposal contracts/v9/examples/skill_proposal_v1/valid/valid_minimal_handle_target.json \
  --context contracts/v9/examples/skill_proposal_v1/contexts/valid_minimal_handle_target.json \
  --expected-context-sha256 <EXPECTATIONS.json 的 context_identity_pins 值>          # exit 0

# 5) 独立世界 ID 探针（不在套件内，另跑一遍）
#   63 个键名 × 位置（root/target/basis/expected_outcome/params/action_budget/time_domain/brain/packet_ref/actor）
#   → 全部被 schema 拒；valid 基线仍被接受；params 任意嵌套层级的 entity_id 也被拒
# 6) py_compile + 依赖面检查：仅 argparse/copy/hashlib/json/math/shutil/subprocess/sys/decimal/pathlib/jsonschema
#    mlx|onnxruntime|torch|requests|urllib|socket 命中 0 次
```

`jsonschema` 4.26.0（来自 AnimeWorldZero 的 venv，只读复用）；**没有 rfc8785 包，JCS 由本卡自实现**。

## 验证结果

| 指标 | 值 |
|---|---|
| 用例总数 | 37（正例 8 / 反例 29） |
| 有独立反例的规则数 | 15 |
| 提案破坏对照 | 29，**29 条全部隔离漏检**（关掉该检查后专用反例被接受，且不异常退出） |
| 回执用例 | 10（正例 3 / 反例 7）；破坏对照 7，**7 条全部隔离漏检** |
| 置信度扫描 | 54 行（27 个反例 × confidence 1.0 与 0.0），判定与原因码**逐条不变**，`evidence_version` 不变 |
| 不静默改写断言 | 8 条正例，回执回显值 = 提交值 = 重算值 |
| 回执泄露扫描 | 37 条，**0 条含世界侧标识** |
| JCS 自测 | 18/18 |
| schema 元校验 | 3/3 |
| 登记条目草案核验 | 6/6 合 `ability_registry_entry.v0` |
| 独立世界 ID 探针 | 63/63 被拒（0 漏） |
| 既有 `canon` 写法 vs JCS | 8 处差异（**只报告**，不改任何既有契约） |

### 逐条：反例 → 期望原因码 → 破坏对照

| 用例 | 类型 | 规则 | 期望/实际原因码 | 破坏对照（关掉后本反例漏检） |
|---|---|---|---|---|
| valid_minimal_handle_target | 正例 | - | accepted | - |
| valid_ttl_upper_boundary | 正例 | ttl | accepted | - |
| valid_ttl_lower_boundary | 正例 | ttl | accepted | - |
| valid_budget_at_cap | 正例 | budget | accepted | - |
| valid_confidence_at_zero | 正例 | - | accepted | - |
| valid_ego_relative_target | 正例 | - | accepted | - |
| valid_no_target_audio_ping | 正例 | - | accepted | - |
| replay_same_id_same_digest | 正例 | duplicate | accepted（重放原决定） | - |
| world_id_field_world_id | 反例 | schema | schema_invalid | `mutation:proposal_no_additional_properties` |
| world_id_field_entity_id | 反例 | schema | schema_invalid | 同上 |
| world_id_field_scene_id | 反例 | schema | schema_invalid | 同上 |
| world_id_field_event_id | 反例 | schema | schema_invalid | 同上 |
| world_id_in_target | 反例 | schema | schema_invalid | 同上 |
| world_id_in_params | 反例 | schema | schema_invalid | `mutation:proposal_no_world_id_key` |
| expected_outcome_truth_field | 反例 | schema | schema_invalid | `mutation:proposal_no_additional_properties` |
| confidence_without_calibration | 反例 | schema | schema_invalid | `mutation:proposal_drop_dependent_required` |
| outcome_window_reversed | 反例 | outcome_window | schema_invalid | `disable:outcome_window` |
| handle_not_in_packet | 反例 | handle | handle_unknown | `disable:handle` |
| handle_retired_after_occlusion | 反例 | handle | handle_unknown | `disable:handle` |
| handle_unresolvable_world_side | 反例 | handle | handle_unknown | `disable:handle` |
| evidence_digest_mismatch | 反例 | evidence | evidence_mismatch | `disable:evidence` |
| evidence_packet_ref_mismatch | 反例 | evidence | evidence_mismatch | `disable:evidence` |
| time_domain_mismatch | 反例 | time_domain | time_domain_mismatch | `disable:time_domain` |
| ttl_expired | 反例 | ttl | proposal_expired | `disable:ttl` |
| ttl_over_registry_cap | 反例 | budget | budget_exceeded | `disable:budget` |
| actions_over_cap | 反例 | budget | budget_exceeded | `disable:budget` |
| duration_over_cap | 反例 | budget | budget_exceeded | `disable:budget` |
| ability_unknown | 反例 | ability | ability_unknown | `disable:ability` |
| params_out_of_range | 反例 | params | params_invalid | `disable:params` |
| params_missing_required | 反例 | params | params_invalid | `disable:params` |
| edit_effect_class | 反例 | effect_class | effect_class_not_registered | `disable:effect_class` |
| precondition_not_met | 反例 | precondition | rejected_other | `disable:precondition` |
| target_kind_not_registered | 反例 | target_kind | rejected_other | `disable:target_kind` |
| actor_mismatch | 反例 | actor | rejected_other | `disable:actor` |
| duplicate_id_changed_evidence | 反例 | duplicate | duplicate_proposal | `disable:duplicate` |
| duplicate_id_same_evidence_changed_params | 反例 | duplicate | duplicate_proposal | `disable:duplicate` |
| confidence_one_ability_unknown | 反例 | confidence_independence | ability_unknown | `disable:confidence_independence` |

回执反例（`replies/invalid/`，全部被 `skill_gate_reply.v1` 拒）：
`reply_reason_not_whitelisted`、`reply_reason_hidden_state_leak`（→ `reply_enum_widened`）、
`reply_carries_resolved_entity`（→ `reply_no_additional_properties`）、
`reply_accepted_with_rejected_code`、`reply_rejected_with_accepted_code`（→ `reply_drop_consistency`）、
`reply_uppercase_sha`（→ `reply_sha_pattern`）、`reply_ttl_window_negative`（→ `reply_drop_minimum`）。

## 验收标准对照

| 验收项 | 结果 | 证据 |
|---|---|---|
| 裁决 1–11 在规范与 schema 中逐条可查 | 通过 | `docs/v9/SKILL_PROPOSAL.md` §13 闭合表；schema 内每条裁决写在对应字段的 `description` |
| schema 元校验通过 | 通过 | 3/3 `Draft202012Validator.check_schema` |
| 裁决列出的反例全部真实非零且各配破坏对照漏检 | 通过 | 29/29 + 7/7 隔离；`check_result.json.controls` / `reply_controls` |
| TTL 边界内正例通过 | 通过 | `valid_ttl_lower_boundary`（tick = t_ticks）、`valid_ttl_upper_boundary`（tick = t_ticks + ttl_ticks）；`ttl_expired` 在右端 +1 |
| 门禁可见回执只含白名单原因码 | 通过 | 回执 schema 封闭枚举 + `allOf` 一致性；37 条回执扫描 0 违规 |
| 无世界 ID 字段可通过 schema | 通过 | 套件 6 条世界 ID 反例 + 独立 63/63 探针（含 params 任意嵌套层级） |

## 失败与限制（如实登记）

1. **未实现的**：AWZ 门禁与内核的真实实现、`WorldBrainAdapter`/`BeliefSummary` 的真实产出、
   裁决 11 的 Forge 写入与 `final` 分区训练门、编辑路线的授权/预览/提交。本轮**全部夹具都是 synthetic**，
   只在冻结上下文里按裁决判定，**不是真实 AWZ 回合**，不构成任何运行授权或能力声明。
2. **裁决 10 的口径（本卡的解释，请复核者/统筹裁决）**：裁决只写「同 ID 同摘要」，没说哪个摘要。
   只比 `evidence_version` 会漏掉「同一份 basis 下改 params/targets」这一路。本实现把身份摘要取为
   **整份提案的 JCS 摘要**（加强读法），并留了两条反例：改 basis 与只改 params 都判 `duplicate_proposal`。
   若统筹要改回弱读法，只需改核对器 `gate()` 的 duplicate 分支，schema 不受影响。
3. **裁决 8 的 `rejected_other`**：白名单里原文列了 10 个被拒码加 `accepted`，但同一条裁决又要求把
   「目标在墙后」「对象其实已不存在」这类原因折叠成 `handle_unknown` **或 `rejected_other`**。
   因此 `rejected_other` 被收进封闭枚举（否则折叠桶无处可去），并在 schema 的 `description` 里写明它是折叠桶、不是自由文本。
4. **JCS 没有官方 testdata**：无下载授权，未取 RFC 8785 的 `testdata`。自实现只做了 §3.2.2 引例、
   §3.2.3 的 UTF-16 键序（含超出 BMP 的键）、ES6 数字格式边界（1e20/1e21/1e-6/1e-7/−0）与
   拒绝 NaN/Inf/重复键/超范围整数共 18 条自测。**未与官方语料逐条比对**。
   另：既有 `canon` 写法与 JCS 在本轮语料有 8 处差异，只报告；迁移属一级决定（E3 裁决 13）。
5. **`--disable` / 变异 schema 不是开关**：它们只在 `reports/V9-B1/` 的破坏测试里用，
   不改变任何交付契约，也不构成授权。变异 schema 都落在 `reports/V9-B1/sabotage-schemas/`。
6. **置信度扫描排除了 2 条 duplicate 反例**：它们的 `decisions_seen` 依赖摘要身份，改 confidence 会同时改摘要，
   扫描没有意义；这两条仍各有 `disable:duplicate` 破坏对照。
7. **回执安全阀**：若提案本身取不出合法的 `proposal_id`/`evidence_version`（只在 `schema_invalid` 下发生），
   回执只能如实留空，核对器对此放宽回执 schema 检查。本套件没有任何用例走到这条路径。
8. 本卡未运行 pytest 全量、未跑真实训练、未提交/推送 git。

## 交回统筹（需要决定的问题）

1. 裁决 10 的摘要口径按上面的加强读法固定，还是改回只比 `evidence_version`？
2. `rejected_other` 作为折叠桶进白名单是否认可（若不认可，请给出「目标在墙后」类原因的落点）？
3. `expected_outcomes` 的 `channel` 只列 `observation.channels` 的 8 个通道；
   `pose_sensor_if_allowed` 作为 payload 字段被排除。是否要把它也作为可预测通道？
4. JCS 是否要在后续卡里做一次与官方 `testdata` 的逐条比对（本卡无下载授权）？

随后由非作者 `ainerzero.V9.B5` 复核。原作者未对任何结果声明 accepted 或能力通过。

---

# ainerzero.V9.B4 修订 r3

角色：二级执行层 `antigravity-7c1e`；时间：2026-10-16 20:41 +0300  
任务状态：**reported**；纯 CPU 契约整理与参考核对，无训练、无 MLX/ORT/torch、无下载、无付费。  
未改裁决文件，保留原报告与 r2 记录。不自行 accept。

## 打回项整改

统筹打回两项全部闭环：

### 1. 世界 ID 键名拦截完整性（裁决 2）
- **要求 a（两层防御架构）**：
  - **第一层**：保留 `skill_proposal.v1.schema.json` 中 `$defs/world_id_key` 正则，在 `params` 属性名及嵌套对象属性名生效。
  - **第二层（核对器规范化判定）**：核对器增加规范化判定函数 `has_forbidden_world_id_key()`。键名转小写、去除所有非字母数字后，若命中 `(world|entity|scene|event|instance|landmark|object|actor|agent|truth|hidden)+id(s)` 或 `hiddencontact` 即拒（`schema_invalid`，世界侧日志 `forbidden_world_id_key`）。作用于提案任意层级键名（除提案者自身固定身份字段 `actor.agent_id` 外），以及能力登记条目 `param_schema` 属性名。
- **要求 b（能力登记条目核对要求）**：能力登记条目的 `param_schema` 必须封闭（`additionalProperties: false`），且所有属性名通过规范化判定。若存在未封闭或命中禁止词，直接拒绝受理（`entry_param_schema_not_closed` / `entry_param_schema_forbidden_property`）。
- **要求 c（12 种拼写独立反例与破坏对照）**：
  为 12 种拼写变形各配置一个独立反例（`world_id_norm_<suffix>`），并配置关闭规范化判定后的破坏对照（`disable:world_id_normalization`），全部达成 `isolated_miss = true`：
  1. `OBJECT_ID` → `world_id_norm_OBJECT_ID`
  2. `Entity_Id` → `world_id_norm_Entity_Id`
  3. `ENTITY_ID` → `world_id_norm_ENTITY_ID`
  4. `entity-id` → `world_id_norm_entity_hyphen_id`
  5. `world.id` → `world_id_norm_world_dot_id`
  6. `objectId` → `world_id_norm_objectId`
  7. `actorIds` → `world_id_norm_actorIds`
  8. `instanceId` → `world_id_norm_instanceId`
  9. `landmarkId` → `world_id_norm_landmarkId`
  10. `agentId` → `world_id_norm_agentId`
  11. `truthId` → `world_id_norm_truthId`
  12. `gtObjectId` → `world_id_norm_gtObjectId`

### 2. 证据卫生（并发竞争与路径写死修复）
- `check_skill_proposal.py --suite` 默认只在临时目录（`tempfile.TemporaryDirectory`）生成夹具，再与提交的夹具目录（`contracts/v9/examples/skill_proposal_v1/` 和 `reports/V9-B1/sabotage-schemas/`）逐字节精确比对；若发现缺少文件、多余文件或字节不匹配，立即报错退出（退出码 1）；比对一致后在只读方式下运行全套核对，不改动、不覆盖、不删除提交夹具。
- 原地重写夹具必须显式传入 `--regenerate` 参数；复核流程不得使用。
- 增加 `--root` CLI 参数，自动配置所有相对路径，彻底避免写死仓库绝对路径。

## 验证证据与结果

命令：`/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite`  
退出码 0，`all_ok: true`，`failures: []`，`control_failures: []`。

| 指标 | r2 基准 | r3 结果 | 变化与说明 |
|---|---|---|---|
| 用例总数 | 40 | **52** | 新增 12 种拼写规范化判定反例 |
| 正例数 | 8 | **8** | 保持不变，全部 accepted |
| 反例数 | 32 | **44** | 全部 rejected |
| 规则数 | 15 | **16** | 新增 `world_id_normalization` 规则 |
| 提案破坏对照 | 32 | **44** | **44/44 全部 isolated_miss = true** |
| 回执用例 / 对照 | 10 / 7 | **10 / 7** | 7/7 全部 isolated_miss = true |
| 置信度扫描 | 60 行 | **84 行** | 1.0 与 0.0 扫描，判定与原因码逐条不变 |
| 不静默改写断言 | 8 条 | **8 条** | 回显一致 |
| 回执泄露扫描 | 40 条 | **52 条** | 0 条泄露世界侧标识 |
| JCS 自测 | 18/18 | **18/18** | 全部通过 |
| schema 元校验 | 3/3 | **3/3** | 全部通过 |
| 登记条目草案 | 6/6 | **6/6** | 全部通过，且 param_schema 封闭与属性名规范化判定全部合规 |
| 临时目录逐字节比对 | 无（原地生成） | **通过** | 临时生成与提交夹具 100% 逐字节一致 |

