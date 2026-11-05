# SkillProposal/v1 规范（AinerZero V9 · 轨道 B 第 4 步）

状态：**草案 r4，reported，待非作者 ainerzero.V9.B6 复核**（r3 的负面证据由 B5 提出并经统筹接受，
本修订按 `AinerRelay/reports/coordination/codex-20261017-cycle1/B4-r4-DECISIONS.md` 的 F1–F7 最小修订）。
本文件只描述契约、门禁语义与 CPU 参考核对；AWZ 门禁的实际实现、内核求值与 `WorldBrainAdapter` 实现
都不在本轮范围（归 V9.B2 与 AWZ 侧后续卡，按 D-019 在 awz.V9.A10 之后）。

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
- **两层防御禁止世界侧标识字段（裁决 2；r4 F1/F3 全面加固）。**
  1. **第一层（Schema 正则）**：所有对象默认 `additionalProperties: false`；`params` 与嵌套对象用
     `propertyNames` 正则禁止标识键名。该正则覆盖 11 族标识词（`world`/`entity`/`scene`/`event`/
     `instance`/`landmark`/`object`/`actor`/`agent`/`truth`/`hidden`）与复数（含不规则复数
     `entities`/`objects`/`actors`/`scenes`/`events`/`instances`/`landmarks`/`agents`/`truths`、
     `worlds`）、大小写与分隔符变体、`id`/`ids`/`idx`/`identifier(s)` 后缀、前缀别名
     （`gt`/`raw`/`my`/`src`）与尾缀（`value(s)`/`map(s)`/`list(s)`/`set(s)`/`ref(s)`/`table(s)`/
     `dict(s)`/`array(s)`/`vector(s)`）、`id` 前缀形式与 `hidden_contact`/`contact_id`。
     它只做**结构快拒**，不是完整防线。
  2. **第二层（核对器规范化判定，独立实现）**：键名转小写、去掉所有非字母数字后，命中
     `<族>+<id 后缀>`、`<id 后缀>+<族>`、`hidden_contact(s)`、`contact+<id 后缀>`，或本身就是
     `id`/`ids`/`idx`/`identifier(s)` 裸键，即判为世界侧标识键名，在提案**任意层级**生效
     （唯一例外是提案者自身固定身份字段 `actor.agent_id`）。
  3. **回归输入**：第二层独立复跑 B5 的 **1131 条探针**（`reports/V-V9-B1/probe_variants.json`，
     四档 `mandated` 402 / `plural_stem` 396 / `padded` 297 / `hidden_contact` 36），
     本修订 **1131/1131 全部拒绝**；第一层 schema 正则对同一批探针 **1131/1131 也全部拒绝**
     （B5 测得的 66/402 是 r3 状态）。检查不读探针文件、不按例子 ID 硬编码，探针只作回归输入。
  4. **界线（如实登记）**：**裸复数词干**（`entities`、`objects`、……）两层都不拒——统筹要求的是
     「族词 + 复数 + id 后缀」，不是「任何含复数的键都拒」；B5 的 oracle `classify_key` 同样不拒这些键。
     这些键有 10 条独立**正例**（`world_id_norm_accepted_*`）固定在套件里。
     反向的过度拒绝：`identity` 以 `entity`+`id` 结尾，schema 正则与第二层都会拒（保守方向，
     不在允许表内的量本来也会被 §7 拒）。
  `expected_outcomes[].quantity` 的值同样不得是这些标识或 `hidden_contact`（另有 §7 的允许表）。
- **能力登记条目 param_schema 的封闭性与动态分支（r4 F1 的具体化）**：
  - 条目根必须是**封闭对象 schema**：`type: "object"` 且 `additionalProperties` 恰为 `false`；属性名必须通过上述规范化判定。
  - v0 **明确拒绝动态分支与未支持关键字**：`patternProperties`、`additionalProperties` 为 schema、
    `unevaluatedProperties`、`propertyNames`、`$ref`/`$dynamicRef`/`$recursiveRef`、`$defs` 动态锚点、
    `if`/`then`/`else`、`dependentSchemas`、`oneOf`/`anyOf`/`allOf`/`not`、`contains` 等一律视为未支持，
    条目直接拒收（`entry:...:unsupported_keyword:<kw>`）。本草案**不承诺**判定任意 JSON Schema 的静态语义。
  - 数组元素里允许 `additionalProperties: {…}`（表达字符串值映射）与 `items`；数组位置的关键字单独放行。
  - 拒绝清单与参考核对的 `UNSUPPORTED_PARAM_SCHEMA_KEYWORDS` 逐项一致；13 条正反例矩阵
    （`registry_entry_matrix`）逐条断言 schema 层与核对器层各拒什么。

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
`max_actions`、`max_duration_ticks`、`max_ttl_ticks`、`preconditions`、`observable_names`（r4 F6 新增，必填）。

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

不得写世界真值字段、事件类型或隐藏接触。

**`quantity` 是有限允许表（r4 F6）。** 两层：

1. **schema 层**：`$defs/observable_quantity` 是 **50 项封闭枚举**，逐项取自 AnimeWorldZero
   `contracts/v9/observation_packet.v1_1.schema.json` 的 `$defs/ch_*` 与 payload 字段名
   （通道、时间、可见性、`detection.*`、`audio_events.*`、`ego_motion.delta.*`、`semantic_mask.*`、
   `symbol8.*`、图像尺寸/内参、`pose_sensor.*`、`last_action_result.*`、`task_instruction.*`、
   `sensor_noise.model`）。表外的名字（含 `world.id`、`entityIds` 这类标识别名）**结构上就写不进去**。
   同一枚举也用作能力登记条目的 `$defs/observable_ref`（两份 schema 与核对器的
   `OBSERVABLE_QUANTITIES` 由套件逐项断言一致）。
2. **门禁层（参考核对）**：调用方在冻结上下文里固定一份**可信可观察量表**
   （`ability_registry.observable_registry`：`registry_id`、`source`、`source_sha256`、`derivation`、
   `quantities`，随上下文一起被 JCS 摘要 pin 住，与待验提案分离）。核对器断言：
   - `quantity` 必须在可信表内（否则 `schema_invalid` / 世界侧 `quantity_not_allowed`）；
   - 上下文自带的表必须是允许表的子集、且不得含标识与隐藏接触键名；
   - `quantity` 还必须落在**被引用能力登记条目的 `observable_names`** 里（否则 `schema_invalid` /
     世界侧 `quantity_not_declared_by_ability`）。

   学生自填的新名字不是授权：`observable_names` 是登记侧写的，提案改不动它。
   `quantity` 命中世界标识规范化别名时另有第二层判定兜底（`quantity_forbidden_alias`）。
   反例：`quantity_value_world_id`、`quantity_value_hidden_contact`、`quantity_value_contact_id`、
   `quantity_value_world_dot_id`、`quantity_value_entityid`、`quantity_not_in_allowlist`、
   `quantity_not_declared_by_ability`，各配「关掉对应检查后漏检」的破坏对照。
   `uncertainty.units` 同样不得写成 `entity_id` 这类标识别名（schema `not.pattern`）。

它只用于事后比对学习进展与好奇心。时间窗越界在 schema 里表达不了（跨字段），由门禁核对，映射到 `schema_invalid`。

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
- 参考核对逐条断言：112 条提案回执全部合 schema、原因码全在白名单内、
  且**不含任何世界侧标识**（实体 ID、隐藏状态标记）；7/7 回执反例各配破坏对照。
  回执本身不可规范化时（例如 `evidence_version` 含孤立代理项）泄露扫描退化为不可判定，
  由 schema 的不合规与 `jcs_unavailable` 摘要如实标出，不假装通过。

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
- **夹具文件名带序号前缀**（`NN_<case>.json`、小写）（r4 F2）：只在大小写上不同的拼写别名
  （`Entity_Id` 与 `ENTITY_ID`）在大小写不敏感文件系统上会同名碰撞，不能当文件名。
  别名只出现在内容里，并以 `alias_key` 记入 `EXPECTATIONS.json`；套件另做文件名 casefold 与
  inode 双重碰撞扫描（`fixture_name_collision_scan`，0 碰撞才通过）。
- **哈希口径分栏**（r4 F7）：`proposal_sha256`/`reply_sha256` 是**原始字节** sha256；
  `context_sha256` 是**JCS 上下文身份**的 sha256（另有同值列 `context_sha256_jcs` 明确口径），
  两者不得混用。`EXPECTATIONS.json` 的 `hash_semantics` 逐字段写明；`SHA256SUMS.txt`
  由套件每次运行**重算**，并按 `RAW_SHA256 / JCS_SHA256 / PATH` 三列分栏。
- **JCS 异常 fail-closed**（r4 F4）：超范围整数（> ±(2⁵³−1)）、孤立代理项、编解码与重复键异常
  一律返回白名单原因码（无效输入 `schema_invalid`），绝不用 traceback 代替拒绝；
  异常类型只进世界侧日志（`jcs_canonicalization_failed:<Type>`）。孤立代理项经 UTF-8 写盘时按
  `\udXXX` 转义，读取端仍得到同一代理项，作为 `jcs_lone_surrogate` 反例。
- **`--disable` 规则名卫生**（r4 F7）：未列名的规则必须显式失败（退出码 2），不做静默 no-op；
  `context_identity` **不可**被关闭（调用方固定的上下文身份不是破坏对照对象）。
  多条规则可以写成 `--disable a --disable b`，或 `--disable a,b`。
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

## 13. 闭合矩阵（r4 F5）：schema 能拒什么、参考门禁能拒什么、真实消费者尚未实现什么）

**不要把参考门禁的覆盖说成 schema 单独覆盖，也不要说已消除任意隐写或非法外部真值访问。**

| # | 检查 | schema 能拒吗 | 参考核对（本仓库脚本）能拒吗 | 真实消费者（AWZ 门禁/内核） |
|---|---|---|---|---|
| 1 | 世界 ID 键名（11 族 + 复数 + 前后缀别名） | 能，但只到正则能表达的形态；JSON Schema 无回溯断言 | 能：规范化判定独立实现，1131/1131 探针拒绝 | **未实现**（V9.B2 / AWZ）；本卡不放行实际门禁 |
| 2 | 世界 ID / 隐藏接触作为 `quantity` 或 `units` 值 | 能（封闭枚举 + `not.pattern`） | 能（可信允许表 + 条目 `observable_names` + 规范化别名兜底） | **未实现** |
| 3 | `params` 值级偷带（合法键里塞世界 ID 字符串） | **不能**（值是无约束 `param_value`） | **不能**：本轮只按字段名与允许表判定，值语义留给可信能力 schema/句柄解析 | **未实现**：需要门禁按登记 schema 与句柄解析在可信侧校验 |
| 4 | 任意隐写（编码、分片、隐写通道） | 不能 | 不能 | **未实现**，也不在本轮承诺 |
| 5 | 句柄不在包内/遮挡后失效/世界侧不可解析 | 不能（需世界侧解析） | 能（`handle_unknown`） | **未实现** |
| 6 | 证据摘要/包引用/tick 不符 | 结构能拒，语义不能 | 能（JCS 重算，`evidence_mismatch`） | **未实现** |
| 7 | TTL 过期、超登记上限、动作数/时长超限 | 结构能拒（正整数），语义不能 | 能（`proposal_expired` / `budget_exceeded`） | **未实现** |
| 8 | 时间域不符（不换算） | 结构能拒（封闭枚举/常量） | 能（`time_domain_mismatch`） | **未实现** |
| 9 | 能力未登记、参数不合登记 schema、目标种类、前置条件、编辑类效果 | 不能（要登记表） | 能（`ability_unknown`/`params_invalid`/`rejected_other`/`effect_class_not_registered`） | **未实现** |
| 10 | 幂等（同 ID 同摘要重放、同 ID 换载荷） | 不能（要决定历史） | 能（`duplicate_proposal`，身份摘要取整份提案 JCS） | **未实现** |
| 11 | 回执原因码白名单与不回传世界侧标识 | 能（封闭枚举 + `additionalProperties:false`） | 能（逐条泄露扫描） | **未实现** |
| 12 | 置信度与判定无关 | 不能（是行为） | 能（扫描 184 行 + 专用反例） | **未实现** |
| 13 | `final` 分区不得训练（裁决 11） | 不能 | 不能（只在文档写明） | **未实现** |

第 3、4 行的结论按 r4 F8 如实保留：**合法键的任意值偷带不能仅靠字段名证明不存在**；
参数值语义由可信能力 schema 与句柄解析保证，本轮列为未验证/未来消费者边界。

## 13b. 裁决 1–11 逐条落点（闭合表）

| 裁决 | 规范落点 | schema 落点 | 反例 / 证据 |
|---|---|---|---|
| 1 两条路线，v1 只开一条 | §1 | 提案无 `route`/`effect_class`；`ability_registry_entry.v0.effect_class` | `edit_effect_class` + 破坏对照 `--disable effect_class` |
| 2 只用句柄、禁世界 ID | §2 | 全对象 `additionalProperties:false`；`params.propertyNames` 任意层级禁世界 ID 键；`targets` 只两种 kind | `world_id_field_*`×4、`world_id_in_target`、`world_id_in_params`、`expected_outcome_truth_field`、`handle_not_in_packet`、`handle_retired_after_occlusion`、`handle_unresolvable_world_side`；另有 56 条拼写反例 + 1131/1131 独立探针 |
| 3 证据版本绑定观察与信念 | §3 | `$defs/basis`、`$defs/observation_ref`、`$defs/time_domain`、`$defs/brain_versions`、`evidence_version` | `evidence_digest_mismatch`、`evidence_packet_ref_mismatch` |
| 4 TTL 用 tick、时间域不换算 | §4 | `ttl_ticks`（正整数）、`$defs/time_domain` | `valid_ttl_lower_boundary`、`valid_ttl_upper_boundary`（正例）、`ttl_expired`、`time_domain_mismatch` |
| 5 能力登记是唯一依据 | §5 | `ability_registry_entry.v0` 全部字段；`$defs/observable_ref` 封闭枚举 | `ability_unknown`、`params_out_of_range`、`params_missing_required`、`actions_over_cap`、`duration_over_cap`、`ttl_over_registry_cap`、`target_kind_not_registered`、`precondition_not_met` |
| 6 置信度不作门禁依据 | §6 | `confidence` + `calibration` + `dependentRequired` | `confidence_one_ability_unknown` + 破坏对照 `--disable confidence_independence`；置信度扫描 184 行 |
| 7 预期结果用观察量表达 | §7 | `$defs/expected_outcome`、`$defs/outcome_window`、通道封闭枚举 | `expected_outcome_truth_field`、`outcome_window_reversed` |
| 8 回执分两层、白名单原因码 | §8 | `skill_gate_reply.v1`：`$defs/visible_reason_code`、`$defs/rejected_reason_code`、`allOf` 一致性 | `reply_reason_not_whitelisted`、`reply_reason_hidden_state_leak`、`reply_carries_resolved_entity`、`reply_accepted_with_rejected_code`、`reply_rejected_with_accepted_code`、`reply_uppercase_sha`、`reply_ttl_window_negative`；112 条回执泄露扫描 |
| 9 不静默改写 | §9 | 无（是门禁行为） | `no_rewrite` 18 条断言 + 裁决 3 的摘要重算 |
| 10 身份与幂等 | §10 | `$defs/actor`、`proposal_id` | `actor_mismatch`、`replay_same_id_same_digest`（正例）、`duplicate_id_changed_evidence`、`duplicate_id_same_evidence_changed_params` |
| 11 数据去向 | §11 | 无（只在文档写明，本轮不实现） | 无（未实现，如实登记） |

## 14. 明确不在此列（本轮不做）

- AWZ 门禁的实际实现、内核求值、E3 编译器和 `WorldBrainAdapter`（V9.B2 / AWZ 侧）。
- 正式能力登记表（归 AWZ）；本轮只出最小条目形状草案。
- 编辑路线的授权、提交、预览令牌（E3 裁决 5）。
- Forge ExperienceEpisode 的写入与 `final` 分区训练门（裁决 11，只在文档写明）。
- 任何真实运行、训练、下载、模型导入。本轮纯 CPU、无 MLX/ORT。

## 15. r4 修订记录（对照 B4-r4-DECISIONS.md 的 F1–F7）

| 条目 | 统筹要求 | 本轮落点 | 证据 |
|---|---|---|---|
| F1/F3 | 复数字干/前后缀别名端到端不漏；递归覆盖参数字段与能力登记 `param_schema`；动态键名分支明确拒绝 | §2 两层规则重写 + `UNSUPPORTED_PARAM_SCHEMA_KEYWORDS` + `param_schema_problems()`；schema 正则同步扩到 11 族全变体 | 1131/1131 探针（规范化层与 schema 层各自全拒）；56 条拼写反例；13 条登记条目正反例矩阵全过 |
| F2 | 大小写文件名碰撞要真正不同的路径、inode 与内容；不得声称 44 份而磁盘只有 43 份 | 夹具名改成 `NN_<case>.json`；别名进内容与 `alias_key`；套件做 casefold + inode 碰撞扫描 | `fixture_name_collision_scan`：236 文件、0 碰撞；`EXPECTATIONS.json` 计数与磁盘一致（112 提案 + 10 回执 + 1 基线 + 1 清单） |
| F4 | JCS 超范围整数、孤立代理项、编解码异常必须 fail-closed 返回白名单原因码，无 traceback | `safe_jcs_sha()`、`jcs_fail_closed` 检查、CLI 全路径 try/except、`_print_json` 编码退化 | `jcs_int_out_of_range`、`jcs_lone_surrogate` 两条反例 + 隔离破坏对照；`gate_internal_error` 计数 0 |
| F6 | `quantity` 必须是明确允许的可观察量，出自可信登记，不得由学生自填授权 | §7 的两层允许表（schema 封闭枚举 50 项 + 上下文 pin 的可信表 + 条目 `observable_names`） | 7 条反例（含 `world.id`、`contact_id`、表外名、未声明量）+ 10 条裸复数正例 + 允许表三方一致性断言 |
| F5 | 文档闭合矩阵分别列 schema / 参考门禁 / 真实消费者 | §13 三层矩阵（13 行） | 文档声明与本套件计数一致；第 3/4 行如实列未实现 |
| F7 | 重算全部 SHA，原始字节与 JCS 分栏；`--disable` 未知名必须失败；只读复跑不重写夹具 | `SHA256SUMS.txt` 由套件每次生成（三列）；`KNOWN_DISABLE_RULES` + 退出码 2；`--regenerate` 之外的运行只在临时目录生成并逐字节比对 | `disable_rule_hygiene` 2/2；复跑前后夹具字节一致（套件内含比对，失败即退出 1） |

**K 保留：** B5 的 r3 负面报告与全部旧证据保留在 `reports/V-V9-B1/` 与本目录 `archive/r3-20261016T2041/`
（124 个文件 + `ARCHIVE_SHA256SUMS.txt`），本修订不覆盖、不删除。
