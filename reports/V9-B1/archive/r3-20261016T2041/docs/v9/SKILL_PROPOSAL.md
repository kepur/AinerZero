# SkillProposal/v1 规范（AinerZero V9 · 轨道 B 第 4 步）

状态：**草案 r1，reported，待非作者 ainerzero.V9.B5 复核**。本文件只描述契约、门禁语义与 CPU 参考核对；
AWZ 门禁的实际实现、内核求值与 `WorldBrainAdapter` 实现都不在本轮范围（归 V9.B2 与 AWZ 侧后续卡，按 D-019 在 awz.V9.A10 之后）。

- 依据：`reports/V9-B1/COORDINATOR_DECISIONS.md` 裁决 1–11 与「执行与证据」（本轮唯一的裁决来源，只读不改）。
- 上级依据：`ARCHITECTURE_V9.md` r5 §2/§3、ADR-0012 §26/§36、ADR-0005、Event/v1 r2 裁决 F2/F4、`ObservationPacket/v1.1`、`reports/P3-E3/r1/COORDINATOR_DECISIONS.md` 裁决 4/5/13、`docs/v9/TEACHERS_AND_CACHE.md` 时间域口径。
- 交付物：
  - `contracts/v9/skill_proposal.v1.schema.json`
  - `contracts/v9/skill_gate_reply.v1.schema.json`（门禁回执，世界脑可见版）
  - `contracts/v9/ability_registry_entry.v0.schema.json`（能力登记条目草案）
  - `contracts/v9/examples/skill_proposal_v1/`（正反例、冻结上下文、回执例、`EXPECTATIONS.json`）
  - `reports/V9-B1/check_skill_proposal.py`（参考核对）、`reports/V9-B1/check_result.json`、`REPORT.md`、`metrics.json`

## 0. 一句话

提案是学生在 AWZ 回合里**想做的一个动作计划**，用 `ability_id` 引用一条 AWZ 登记的能力，
目标只用观察句柄表达，证据绑定到所依据的观察包的 JCS 摘要；门禁要么原样接受、要么拒绝，
回给世界脑的只有白名单原因码，执行结果只能通过之后的观察获得。

## 1. 两条路线，v1 只开一条（裁决 1）

| 路线 | 触发条件 | 结果 | v1 状态 |
|---|---|---|---|
| 运行路线 | 登记条目 `effect_class = "run"` | 学生在运行中的 AWZ 回合里用自己的身体和能力做动作；门禁通过后由内核求值，结果只以 Event/v1 事件（`source` 为学生动作）和之后的观察体现。不产生 E3 信封，不改持久世界和场景源 | **开** |
| 编辑路线 | 登记条目 `effect_class = "edit"` | 门禁把提案编译成 E3 信封，`actor` 为世界脑，按 E3 裁决 5 只能预览，提交要用户确认或授权 | 只定义格式，**未开** |

- **路由不在提案里。** 提案不写 `route`、不写 `effect_class`；路由由 `ability_id` 指向的登记条目的
  `effect_class` 推导。这样世界脑无法自己声明走哪条路，门禁也不能被提案文本绕过。
- v1 已登记的编辑类能力集合**为空**（同 ADR-0005 例外集合为空的处理）。能力登记上下文里
  `ability_registry.registered_edit_abilities` 必须为空数组，否则参考核对直接 fail closed；
  任何引用 `effect_class = "edit"` 条目的提案一律 `effect_class_not_registered`。
- 合成正例**不得**冒充实际授权。示例目录里没有任何被接受的编辑类提案。

## 2. 目标只能用观察句柄，不用世界 ID（裁决 2，守 F2/F4）

`targets[]` 只有两种形态：

```json
{"kind": "handle", "handle": "h-3"}
{"kind": "ego_relative_pose", "rel_position_m": [0.5, 0.0, 0.0], "rel_yaw_deg": 0,
 "uncertainty": {"sigma": 0.1, "units": "m"}}
```

- 句柄形如 `h-<n>`，**必须**是提案所依据的那份 ObservationPacket 里出现过的检测句柄。
  门禁在世界侧把句柄解析成实体，**映射永远不回传给世界脑**。
- 句柄命中下列任一条，一律拒绝为 `handle_unknown`：
  1. 不在所依据的包里；
  2. 已因遮挡重发而失效（`handle_policy = reissue_after_occlusion`，旧句柄进 `retired_handles`）；
  3. 在包里但世界侧无法解析。
- 空间目标用**智能体自身坐标系**（相对位姿加不确定性）表达，不写世界真值坐标。
  不确定性 `sigma` 必须**严格为正**：0 等于声称知道真值。
- **两层防御禁止世界侧标识字段（裁决 2）。**
  1. **第一层（Schema 正则）**：所有对象默认 `additionalProperties: false`；`params` 与嵌套对象用 `propertyNames` 正则禁止常见蛇形与驼峰键名。
  2. **第二层（核对器规范化判定）**：键名转小写、去除所有非字母数字后，若命中 `(world|entity|scene|event|instance|landmark|object|actor|agent|truth|hidden)+id(s)` 或 `hiddencontact` 即拒。全面覆盖 12 种拼写变形（`OBJECT_ID`、`Entity_Id`、`ENTITY_ID`、`entity-id`、`world.id`、`objectId`、`actorIds`、`instanceId`、`landmarkId`、`agentId`、`truthId`、`gtObjectId`），在提案任意层级（除提案者自身固定身份字段 `actor.agent_id` 外）生效。
  `expected_outcomes[].quantity` 的值同样不得是这些标识或 `hidden_contact`。
- **能力登记条目 param_schema 封闭与属性名防御**：条目必须包含 `additionalProperties: false`，且其属性名必须通过上述规范化判定。

## 3. 证据版本绑定所依据的观察和信念（裁决 3）

`basis` 固定五个字段：

| 字段 | 含义 |
|---|---|
| `packet_ref.uri` + `packet_ref.sha256` | 所依据的 ObservationPacket 的 URI 与内容摘要；URI 只许允许的命名空间，`private/`、`truth/`、`eval/`、`future/` 一律不许（§8.6，F2） |
| `t_ticks` | 该包的 episode-relative tick |
| `time_domain` | `{clock: "episode_relative", episode_id, epoch_id, tick_hz: 120}`，与 `teacher_cache r3` 的 `observation_time_domain` 同口径 |
| `belief_sha256` | BeliefSummary 摘要 |
| `brain` | 模型、编码器、规划器各自的版本 |

- **`evidence_version` = `basis` 的 JCS 摘要（RFC 8785）**，小写十六进制 64 位。
- 门禁**重算**摘要，不一致即 `evidence_mismatch`；`basis.packet_ref` 与 `basis.t_ticks`
  必须等于世界侧可信的当前包，否则同样 `evidence_mismatch`。
- 参考核对用自实现的 JCS（`check_skill_proposal.py`）：键按 **UTF-16 码元**排序、最小转义、
  数字按 ECMAScript `Number::toString` 序列化、整数限 ±(2⁵³−1)、拒绝 NaN/Inf 与重复键。
  18 条自测向量全部通过（含 RFC 8785 §3.2.2 的引例与超出 BMP 的键序）。
  **仓库既有的 `canon` 写法与 JCS 不等价**（本轮语料 8 处差异，只报告，不改任何既有契约；
  RFC 8785 迁移由一级另行决定，同 E3 裁决 13）。

## 4. TTL 用 tick 计，不用墙钟（裁决 4）

- `ttl_ticks` 是正整数；上限由能力登记条目的 `max_ttl_ticks` 给出，超出即 `budget_exceeded`。
- 有效窗是**闭区间** `[basis.t_ticks, basis.t_ticks + ttl_ticks]`。
  门禁按当前回合 tick 判断：`current_tick > basis.t_ticks + ttl_ticks` 才是 `proposal_expired`。
  两个端点都算有效，**都在正例里**（`valid_ttl_lower_boundary`、`valid_ttl_upper_boundary`）；
  `ttl_expired` 恰好在右端 +1。
- 时间域与当前回合不一致**直接拒**（`time_domain_mismatch`），**不做换算**。

## 5. 能力登记是门禁的唯一依据（裁决 5）

`ability_registry_entry.v0` 是 AinerZero 侧写出的**最小条目形状草案**，正式登记表归 AWZ，本轮不实现。
条目字段：`ability_id`、`ability_version`、`effect_class`、`param_schema`、`target_kinds`、
`max_actions`、`max_duration_ticks`、`max_ttl_ticks`、`preconditions`。

- `param_schema` 必须是**封闭的对象 schema**（`additionalProperties: false`），本身做 Draft 2020-12 元校验。
- `preconditions` 的 `observable` 是**封闭枚举**，只能写 `ObservationPacket/v1.1` payload 里模型可见的量
  （通道、`visibility.*`、`episode_start`、`time.*`、`detection.*`、`audio_events.*`、`ego_motion.*`、
  `semantic_mask.labels`、`last_action_result.*`、`task_instruction.goal`、`pose_sensor_if_allowed`）。
  写不进世界真值、隐藏接触或世界实体。参考核对**核验不了**的 observable 一律保守判为不成立。
- 未登记的能力 → `ability_unknown`；参数不合 `param_schema` → `params_invalid`；
  目标种类不在 `target_kinds` → `rejected_other`；前置条件不成立 → `rejected_other`；
  超出动作数、持续时长或 TTL 上限 → `budget_exceeded`。

## 6. 置信度只作参考，不作门禁依据（裁决 6）

- `confidence ∈ [0,1]`，可选；出现就必须同时声明 `calibration`（登记的校准引用对象，或 `"uncalibrated"`）。
- 能力、目标、预算、锁、权限的判定**与置信度无关**。参考核对做两件事：
  1. 专用反例 `confidence_one_ability_unknown`（`confidence = 1.0` 且能力未登记）仍被拒为 `ability_unknown`；
  2. **置信度扫描**：把反例逐个改成 `confidence = 1.0` 和 `0.0`，判定与原因码必须逐条不变，
     且 `evidence_version` 不变（`confidence` 不在 `basis` 里，本来就不进证据摘要）。本修订为 60 行全过。

## 7. 预期结果用观察量表达（裁决 7）

`expected_outcomes[]` 每项：`channel`（只能是 `ObservationPacket/v1.1` `observation.channels` 已有的 8 个通道；
`pose_sensor_if_allowed` 是 payload 字段不是通道，不在其列）、`quantity`（被预测的可观察量名）、
`predicted_value`、`uncertainty`（`sigma > 0`）、`window`（相对 `basis.t_ticks` 的 tick 闭区间，
要求 `0 ≤ start ≤ end ≤ ttl_ticks`）。

不得写世界真值字段、事件类型或隐藏接触。`quantity` 的值命中 `world_id`、`entity_id`、`scene_id`、`event_id`、`instance_id` 或 `hidden_contact` 时，schema 直接判无效。它只用于事后比对学习进展与好奇心。
时间窗越界在 schema 里表达不了（跨字段），由门禁核对，映射到 `schema_invalid`。

## 8. 门禁回执分两层，防止泄露（裁决 8）

| 层 | 内容 | 去向 |
|---|---|---|
| 世界侧完整决定 | accepted/rejected 加详细原因，含解析到的实体、命中哪一条隐藏状态 | **只写世界侧日志** |
| 世界脑可见回执 | `skill_gate_reply.v1`：`proposal_id`、`evidence_version`、`decision`、`reason_code`、`decided_at_tick`、`valid_until_tick` | 回给世界脑 |

白名单原因码（封闭枚举，任何其他值都必须被 schema 拒）：

```
accepted
schema_invalid  ability_unknown  params_invalid  budget_exceeded  proposal_expired
time_domain_mismatch  evidence_mismatch  handle_unknown
effect_class_not_registered  duplicate_proposal  rejected_other
```

- `rejected_other` 是裁决 8 明确要求的**折叠桶**：同一条裁决说「目标在墙后」「对象其实已不存在」
  这类会暴露隐藏状态的原因一律折叠成 `handle_unknown` 或 `rejected_other`。
  本实现里它也承载 `target_kind_not_registered`、`precondition_not_met`、`actor_mismatch`
  这三类不暴露隐藏状态的拒绝。**白名单里没有自由文本。**
- `decision` 与 `reason_code` 必须一致：`accepted` 只能配 `accepted`，`rejected` 只能配被拒码。
- `valid_until_tick` 是 `basis.t_ticks + ttl_ticks`，即提案自带的公开量，不泄露世界侧状态；
  提案结构本身不可用时为 `null`。
- **回执里没有执行结果。** 执行结果只能通过之后的观察获得。
- 参考核对逐条断言：37 条提案回执全部合 schema、原因码全在白名单内、
  且**不含任何世界侧标识**（实体 ID、隐藏状态标记）；7/7 回执反例各配破坏对照。

## 9. 不静默改写提案（裁决 9）

门禁要么原样接受，要么拒绝，不做裁剪、补全或替换参数后再执行。
可核验的推论：`evidence_version` 是 `basis` 的 JCS 摘要，门禁从**提交的那份 basis** 重算并要求逐字节相等，
所以任何改写都会被 `evidence_mismatch` 抓住；被接受的 8 个正例里，回执回显的 `evidence_version`
与提交值、与重算值三者相同（`no_rewrite` 断言全过）。

## 10. 身份与幂等（裁决 10）

- 门禁**从会话取 actor**（世界脑的运行与智能体身份：`kind = "world_brain"`、`run_id`、`agent_id`、`policy_revision`）；
  提案自带 actor 与会话不符即拒。这只是**世界侧日志**的拒绝原因（`actor_mismatch`），
  回给世界脑仍按裁决 8 的白名单，折叠成 `rejected_other`。
- `proposal_id` 在（回合、actor）内唯一。
  - 同 ID **同摘要** → 返回原决定（重放，不重新执行）；
  - 同 ID **不同摘要** → `duplicate_proposal`。
- **口径说明（本卡的实现选择，请复核者与统筹确认）：** 裁决 10 只说「同摘要」，没说是哪个摘要。
  只比 `evidence_version`（`basis` 的摘要）会留下一个洞——同一份 basis 下改 `params` 或 `targets`，
  摘要不变，就能绕过幂等。因此本实现把**身份摘要取为整份提案的 JCS 摘要**（含 `evidence_version` 与 `params`），
  并在 `decisions_seen` 里同时留 `proposal_digest` 与 `evidence_version`。
  这是对裁决 10 的**加强**读法：原命题（同 ID 同摘要返回原决定）依然成立，只是「不同摘要」的判定更严。
  反例两条：改 basis（`duplicate_id_changed_evidence`）与不改 basis 只改 params
  （`duplicate_id_same_evidence_changed_params`）都判 `duplicate_proposal`；后者正是弱读法会漏掉的那条。
  若统筹要改回弱读法，改 `check_skill_proposal.py` 的 `gate()` duplicate 分支即可，schema 不受影响。

## 11. 数据去向（裁决 11）

提案、门禁决定（世界侧完整版）和之后的观察，按回合所在分区进入 Forge ExperienceEpisode。
**`final` 分区的提案与结果不得用于训练。** 本轮只在文档写明这一规则，**不实现**。

## 12. 参考核对怎么跑

```bash
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite
```

- 全部夹具都是**明确标 `synthetic: true` 的冻结上下文**；上下文与待验提案**分开成文件**，
  预期身份由**调用方通过 `--expected-context-sha256` 固定**（同 T1 r3 裁决 5 的做法）。
  核对器从不信任上下文自述身份：pin 不符直接 fail closed，不产生任何提案判定。
- 单条核对（非零即拒）：

```bash
… --python reports/V9-B1/check_skill_proposal.py gate \
   --proposal contracts/v9/examples/skill_proposal_v1/valid/valid_minimal_handle_target.json \
   --context  contracts/v9/examples/skill_proposal_v1/contexts/valid_minimal_handle_target.json \
   --expected-context-sha256 <EXPECTATIONS.json 里 context_identity_pins 的值>
```

- `--disable <rule>` / `--schema <变异 schema>` / `--reply-schema <变异 schema>` **只供报告目录的破坏测试**，
  不是生产开关、不是授权、不改任何契约。
- 判据见 `contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json` 与 `reports/V9-B1/check_result.json`。

## 13. 裁决 1–11 逐条落点（闭合表）

| 裁决 | 规范落点 | schema 落点 | 反例 / 证据 |
|---|---|---|---|
| 1 两条路线，v1 只开一条 | §1 | 提案无 `route`/`effect_class`；`ability_registry_entry.v0.effect_class` | `edit_effect_class` + 破坏对照 `--disable effect_class` |
| 2 只用句柄、禁世界 ID | §2 | 全对象 `additionalProperties:false`；`params.propertyNames` 任意层级禁世界 ID 键；`targets` 只两种 kind | `world_id_field_*`×4、`world_id_in_target`、`world_id_in_params`、`expected_outcome_truth_field`、`handle_not_in_packet`、`handle_retired_after_occlusion`、`handle_unresolvable_world_side`；另有 63/63 独立探针 |
| 3 证据版本绑定观察与信念 | §3 | `$defs/basis`、`$defs/observation_ref`、`$defs/time_domain`、`$defs/brain_versions`、`evidence_version` | `evidence_digest_mismatch`、`evidence_packet_ref_mismatch` |
| 4 TTL 用 tick、时间域不换算 | §4 | `ttl_ticks`（正整数）、`$defs/time_domain` | `valid_ttl_lower_boundary`、`valid_ttl_upper_boundary`（正例）、`ttl_expired`、`time_domain_mismatch` |
| 5 能力登记是唯一依据 | §5 | `ability_registry_entry.v0` 全部字段；`$defs/observable_ref` 封闭枚举 | `ability_unknown`、`params_out_of_range`、`params_missing_required`、`actions_over_cap`、`duration_over_cap`、`ttl_over_registry_cap`、`target_kind_not_registered`、`precondition_not_met` |
| 6 置信度不作门禁依据 | §6 | `confidence` + `calibration` + `dependentRequired` | `confidence_one_ability_unknown` + 破坏对照 `--disable confidence_independence`；置信度扫描 54 行 |
| 7 预期结果用观察量表达 | §7 | `$defs/expected_outcome`、`$defs/outcome_window`、通道封闭枚举 | `expected_outcome_truth_field`、`outcome_window_reversed` |
| 8 回执分两层、白名单原因码 | §8 | `skill_gate_reply.v1`：`$defs/visible_reason_code`、`$defs/rejected_reason_code`、`allOf` 一致性 | `reply_reason_not_whitelisted`、`reply_reason_hidden_state_leak`、`reply_carries_resolved_entity`、`reply_accepted_with_rejected_code`、`reply_rejected_with_accepted_code`、`reply_uppercase_sha`、`reply_ttl_window_negative`；37 条回执泄露扫描 |
| 9 不静默改写 | §9 | 无（是门禁行为） | `no_rewrite` 8 条断言 + 裁决 3 的摘要重算 |
| 10 身份与幂等 | §10 | `$defs/actor`、`proposal_id` | `actor_mismatch`、`replay_same_id_same_digest`（正例）、`duplicate_id_changed_evidence`、`duplicate_id_same_evidence_changed_params` |
| 11 数据去向 | §11 | 无（只在文档写明，本轮不实现） | 无（未实现，如实登记） |

## 14. 明确不在此列（本轮不做）

- AWZ 门禁的实际实现、内核求值、E3 编译器和 `WorldBrainAdapter`（V9.B2 / AWZ 侧）。
- 正式能力登记表（归 AWZ）；本轮只出最小条目形状草案。
- 编辑路线的授权、提交、预览令牌（E3 裁决 5）。
- Forge ExperienceEpisode 的写入与 `final` 分区训练门（裁决 11，只在文档写明）。
- 任何真实运行、训练、下载、模型导入。本轮纯 CPU、无 MLX/ORT。
