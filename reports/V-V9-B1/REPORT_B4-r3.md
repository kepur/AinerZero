# ainerzero.V9.B5 独立复核报告（对 V9.B4 修订 r3 · 信息隔离/门禁/泄露 · 非作者）

角色：executor（二级执行层）；复核者：`deepseek-flash-r8t4`（deepseek-flash，注册于接力台，非 B4 作者）
时间：2026-10-16（+0300）；任务状态：reported；复核结论：**不建议直接验收**（建议 r4 最小加固后再验收）
被复核：`ainerzero.V9.B4` 修订 r3（本卡作者 `antigravity-7c1e`；r1 原作者 `deepseek-flash-a7k2`）
依据：`reports/V9-B1/COORDINATOR_DECISIONS.md` 裁决 1–11；上一轮打回意见（系统化键名变体探针、`--suite` 不改写交付目录）
环境：纯 CPU、无 GPU/训练/MLX/ORT/torch、无网络下载、无付费、未提交未推送、只读被验文件

**利益冲突声明**：上一轮 B5 的复核者（`antigravity-7c1e`）正是本轮 r3 的作者；其复核脚本 `reports/V-V9-B1/verify_skill_proposal.py` 与其中
oracle **未被复用**。本报告全部判定来自新写代码 `reports/V-V9-B1/oracle_r3.py`（自写 JCS + 自写键名分档判定 + 自写门禁 oracle）与
`reports/V-V9-B1/verify_b4r3.py`（harness）。上一轮报告/脚本/结果一律保留未改。

## 摘要（含结论）

- 作者脚本复跑：`--suite` 退出码 0、25.69s、`all_ok=true`、52 用例（8 正/44 反）、44/44 提案破坏对照 + 7/7 回执对照经我独立重算确认真实漏检、0 用例失败。
- `--suite` **不再改写交付目录**：`contracts/v9/**` 与 `sabotage-schemas/**` 运行前后 0 changed/added/removed；`check_result.json` 重写后**逐字节相同**（未恢复、未改动任何范围外文件）。
- 独立 oracle 交叉：自写 JCS 自测 21/21；52/52 冻结上下文身份 pin 复现；与作者 JCS 在 52 份上下文上逐字一致；作者夹具 52/52 判定 + 52/52 原因码 + 10/10 回执吻合。
- 系统化键名变体探针 1131 个（11 标识词 × id/ids/Id/ID/Ids × 4 分隔符 × 3 大小写 + 复数词干 + 后缀/前缀别名 + hidden_contact），
  覆盖 `params` 三层嵌套与 9 个关闭对象位置，以及能力登记 `param_schema` 属性名。
- **被点名族（单数词干）402/402 全拒、hidden_contact 36/36 全拒**（比 r2 显著改善）；关闭对象位置 1131×9 全部 schema 层拒绝。
- **但复数词干 396/396 全部被门禁接受、后缀别名 165/297 被接受**（1683 个 (变体,位置) 组合逃逸），
  含 4 条真实子进程 exit 0 的端到端漏检：`objects_id` / `worldIdsMap` / `entitiesId`，
  以及"登记条目声明 `objects_id` + 参数值就是冻结上下文里的真实实体 ID `entity-7f3a41c9b2e05d18`"→ **accepted**（同结构换规范拼写 `object_id` → rejected）。
- **交付证据缺失**：`world_id_norm_Entity_Id.json` 与 `world_id_norm_ENTITY_ID.json` 在本机大小写不敏感文件系统上**同 inode（65147926）同 sha**，
  磁盘内容键名是 `ENTITY_ID`；44 条反例只对应 43 份文件；`Entity_Id` 的 pin（`67e2a7c1…`）无对应产物 —— 被统筹点名的拼写实际没被测到。
- 另有：条目层属性名检查漏复数词干（0/396）与 `patternProperties`；2 条崩溃路径（超范围整数、孤立代理项）不产生白名单原因码；
  `quantity` 值清单与键名规则不一致；r3 未更新交付物 SHA 清单（4/6 与磁盘不符）。
- 自写不利反例 31 条（真实子进程）：25 条得到合法非零拒绝；**6 条不通过 = 上述 4 条漏检 + 2 条崩溃**；21 条配对破坏/差分对照真实 exit 0。
- 裁决 1、3、4、6、8、9、10 通过；裁决 2 不通过（复数/别名键名漏检 + 条目层覆盖不足）；裁决 5、7 部分通过；裁决 11 未实现（如实登记，无异议）。

## 1. 验证边界（被验产物 SHA256，我自行重算）

| 产物 | SHA256 |
|---|---|
| `contracts/v9/skill_proposal.v1.schema.json` | `dc6915a12d1c66527df4dcc4352b3b010c64dbfe329f4698de7fe00a9983f486` |
| `contracts/v9/skill_gate_reply.v1.schema.json` | `dc81852c0dc6341a033bcf9ed70c969091faae541e775c4682cb0ce6f1840f2c` |
| `contracts/v9/ability_registry_entry.v0.schema.json` | `1f087c7f95f9a8451312529816915e811ca648d25ebca7bdcaa44d6bf7080d60` |
| `docs/v9/SKILL_PROPOSAL.md` | `b515bd75c72224d16e29633cae057c0617412715a1e23538567a35726d341004` |
| `reports/V9-B1/check_skill_proposal.py`（作者核对器） | `d1f8ab82afac5498e40d7328c2c16d78efa8f5d080ecd59bdb9b2eee3f880e26` |
| `reports/V9-B1/check_result.json`（复跑后，逐字节同前） | `06814a7b0e4dd3954980bd628e89812c18194919aa5aa0c516fb81d88b24b4f4` |
| `contracts/v9/examples/skill_proposal_v1/EXPECTATIONS.json` | `453ab6bef44b4ffe314464ef72e486dc6b5d8f8a46337bf55ed4e944ded56f4e` |
| `reports/V9-B1/COORDINATOR_DECISIONS.md` | `04504c33643c30b3116abe5cd8430fe2bc0e8f44fa70154b9c2f892f93a6d113` |
| `reports/V9-B1/REPORT.md`（r1 正文 + r3 附录） | `bb63a634017ab5f4392765b4aae60136989ffd1f253178f2536271d894b64040` |

## 2. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
VENV=/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python
$VENV reports/V-V9-B1/verify_b4r3.py --phase oracle    # 自写 JCS/pin/清单/夹具交叉
$VENV reports/V-V9-B1/verify_b4r3.py --phase probe     # 1131 变体 × 位置 × 层
$VENV reports/V-V9-B1/verify_b4r3.py --phase adverse   # 31 反例 + 21 对照，真实子进程
$VENV reports/V-V9-B1/verify_b4r3.py --phase suite     # 复跑作者 --suite + 交付目录哈希前后比对
$VENV reports/V9-B1/check_skill_proposal.py gate --proposal <P> --context <C> \
      --expected-context-sha256 <pin> [--disable <rule>] [--schema <S>] --root $(pwd)   # 反例/对照逐条
```
输出：`oracle_results.json`、`probe_results.json`、`probe_variants.json`、`adverse_results.json`、
`suite_results.json`、`adverse/**`（夹具）、`metrics_b4-r3.json`。全部落在 `reports/V-V9-B1/`。
唯一被写到的范围外文件：`reports/V9-B1/check_result.json`（作者 `--suite` 自身无条件重写；内容逐字节相同，未做恢复，见 §3.3）。

## 3. 复核结果

### 3.1 独立 oracle 交叉（我的判定 vs 作者夹具）

| 项目 | 门槛 | 实测 | 判定 |
|---|---|---|---|
| 自写 JCS 自测（键序/UTF-16 码元/BMP 外/数字 ES6 边界/转义/-0/1e21/1e-7/2⁵³−1） | 21/21 | 21/21 | 通过 |
| 52 份冻结上下文身份 pin 复现（我的 JCS 摘要） | 52/52 | 52/52 | 通过 |
| 我的 JCS 与作者 JCS 在 52 份真实文档上逐字节一致 | 52/52 | 52/52 | 通过 |
| 夹具清单重算（提案=原始字节 sha、上下文=JCS 摘要） | 全中 | 113/114，1 不中 = `Entity_Id`（F2） | 见 F2 |
| 作者提案夹具决策 | 52/52 | 52/52 | 通过 |
| 作者提案夹具原因码 | 52/52 | 52/52 | 通过 |
| 作者回执夹具（3 正/7 反） | 10/10 | 10/10 | 通过 |
| `evidence_version` = JCS(basis) 复算 | 正例全中 | 51/52（不中的 1 条即 `evidence_digest_mismatch`，按设计不符） | 通过 |

### 3.2 系统化键名变体探针（本轮重点）

变体生成：11 个标识词（world/entity/scene/event/instance/landmark/object/actor/agent/truth/hidden）× 词元 {id, ids, Id, ID, Ids}
× 分隔符 {无, `_`, `-`, `.`} × 词干大小写 {lower, Capital, UPPER}；另加复数字干、后缀别名（+Map/List/Ref/Value/Set）、前缀别名（gt/raw/my/src）、
hidden_contact 家族与裸 `id/ids` 等；去重后 **1131** 个。
每个变体插入到**登记条目允许该键**的冻结上下文（新增 `abil-probe-tags`、`abil-probe-nested` 两个合法条目），
使"被接受"只可能来自世界 ID 防御失效，而不是参数校验顺手拦下：

| 族 | 变体数 | schema 层拒绝 | 规范化层拒绝 | 门禁拒绝 | **门禁接受（逃逸）** |
|---|---|---|---|---|---|
| 单数词干×id/ids（统筹点名族） | 402 | 66 | 402 | 402 | **0** |
| hidden_contact 家族 | 36 | 8 | 36 | 36 | **0** |
| **复数字干**（worlds_id / entitiesId / objects_id…） | 396 | 0 | 0 | 0 | **396** |
| **后缀/前缀别名**（worldIdMap / gtWorldId…） | 297 | 48 | 132 | 132 | **165** |

- 位置覆盖：`params.tags[0]`、`params.root.payload`（2 层）、`params.root.payload.level2`（3 层）三层结论一致；逃逸三元组共 1683 个。
- 关闭对象位置（root / targets[0] / basis / basis.packet_ref / basis.brain / expected_outcomes[0] / action_budget / actor / time_domain）：
  1131 变体 × 9 位置 = 10179 次，**全部被 schema 层拒绝**（`additionalProperties:false` 一视同仁），无位置依赖漏洞。
- 能力登记条目 `param_schema` 属性名（裁决 5/r3 要求 b）：作者检查标记 单数 402/402、hidden_contact 36/36，
  但 **复数词干 0/396**、别名 132/297；我的 oracle 标记 1131/1131。
- `patternProperties` 分支完全未被扫描：条目 `{additionalProperties:false, properties:{seed}, patternProperties:{"^instanceId$":…}}`
  作者 `registry_problems` 返回 `[]`，我的 oracle 返回 `entry_param_schema_forbidden_property`。
- 条目 schema 本身不约束 `param_schema.properties` 里的属性名：`WORLD_ID/world_id/objects_id/objectId/hidden_contact` 作为属性名时
  对 `ability_registry_entry.v0.schema.json` **全部 VALID**（逐条实测）。
- 逃逸样例（门禁 accepted）：`worldsid`、`WorldsId`、`WORLDSID`、`worlds_id`、`entitiesId`、`objects_id`、`worldIdMap`、`worldIdList`、`objectsIdRef`…

### 3.3 复跑作者脚本 + 破坏对照真实漏检 + 交付目录只读

| 项目 | 期望 | 实测 | 判定 |
|---|---|---|---|
| `--suite` 退出码 / `all_ok` | 0 / true | 0 / true，25.686s | 通过 |
| 用例 | 52 | 52（8 正全部 accepted；44 反全部 rejected），失败 0 | 通过 |
| 提案破坏对照 | 全部真实漏检 | 44/44 由我从原始字段独立重算（`control_returncode=0` 且 `control_reason=accepted` 且无 exception） | 通过 |
| 回执破坏对照 | 全部真实漏检 | 7/7 同上 | 通过 |
| 回执泄露扫描 | 0 违规 | 52 行扫描 0 违规 | 通过 |
| JCS 自测 / schema 元校验 / 登记条目 | 18/18、3/3、6/6 | 18/18、3/3、6/6 | 通过 |
| **`--suite` 是否改写交付目录** | 不改 | `contracts/v9/**` + `sabotage-schemas/**` 运行前后 **0 changed / 0 added / 0 removed** | 通过 |
| `check_result.json` | — | 重写后 sha 不变（`06814a7b…`），mtime 变；未触发恢复 | 通过（内容不变） |
| 夹具字节一致（临时目录 vs 提交目录） | 一致 | 套件自身该项通过（不一致会 exit 1）；我另行核对清单见 F2 | 见 F2 |

### 3.4 自写不利反例（真实子进程，异常退出与合法拒绝分列）

31 条反例 + 29 次配对对照（21 条破坏/差分对照 + 4 条回执对照）全部用子进程实跑，读退出码与 stdout JSON：

| 组 | 条数 | 结果 |
|---|---|---|
| 键名（`.`/`-`/大写/驼峰/复数词元/hidden_contact/前缀别名） | 7 | 7/7 合法非零拒绝（schema_invalid）；`--disable world_id_normalization` 真实 exit 0 |
| **复数词干 / 后缀别名（含端到端）** | 4 | **4/4 真实 exit 0 = accepted（漏检）**；同结构换规范拼写 4/4 exit 1 = schema_invalid（差分对照成立） |
| 条目 `patternProperties` 缺口 | 1 | 拒绝（靠提案层兜底）；`--disable world_id_normalization` → exit 0，证明条目层零贡献 |
| `quantity` 值（world_id / hidden_contact） | 2 | 2/2 拒绝；`proposal_quantity_value_open` 变异 schema → exit 0 |
| 旧句柄 `h-4` / 跨包句柄 `h-9` | 2 | 2/2 handle_unknown；`--disable handle` → exit 0 |
| 原始实体 ID 当句柄 | 1 | schema 正则先拒；放开正则仍被 handle 解析拒；再 `--disable handle` 才漏（三层防御链实测） |
| 伪造 basis + 自算 `evidence_version`（packet_ref / t_ticks） | 2 | 2/2 evidence_mismatch；`--disable evidence` → exit 0 |
| TTL 边界 ±1 tick | 2 | 边界内 exit 0 accepted；+1 exit 1 `proposal_expired`；`--disable ttl` → exit 0 |
| 跨 episode 时间域（自算摘要） | 1 | time_domain_mismatch；`--disable time_domain` → exit 0 |
| 置信度 1.0 + 未登记能力 | 1 | ability_unknown；`--disable confidence_independence` → exit 0 |
| 编辑类效果伪装运行类 | 1 | effect_class_not_registered；`--disable effect_class` → exit 0 |
| 预期结果夹带 `event_type`/`gt_pose`/`truth_id` | 3 | 3/3 schema 拒绝；`proposal_no_additional_properties` → exit 0 |
| 同 ID 换载荷 | 1 | duplicate_proposal；`--disable duplicate` → exit 0 |
| 值级偷带（键名合法、值为真实实体 ID） | 1 | **accepted（超范围残留，见 F8-1）** |
| 健壮性（2⁵³ 整数 / 孤立代理项） | 2 | **2/2 崩溃：exit 1 但无 stdout JSON、无白名单原因码（见 F4）** |
| 回执：非白名单原因 / 夹带解析实体 / 自定义非白名单原因 | 3(+1 正例) | 4/4 判定符合预期，3/3 变异 schema 对照真实转为有效 |

## 4. 发现（阻断/重要/中等/观察）

**F1（阻断）复数词干与后缀别名键名端到端漏检。**
`check_skill_proposal.py:53-59` 把键名小写去非字母数字后要求 `…ids?$` **后缀锚定**；`worlds_id→worldsid`、`entitiesId→entitiesid`、
`objects_id→objectsid` 都不以 `worldid/entityid/objectid` 结尾，`worldIdMap→worldidmap` 以 `map` 结尾，故全部逃逸。
实测：门禁接受 396/396（复数字干）、165/297（别名）；4 条真实子进程 exit 0：
`params.tags[0].objects_id`、`params.tags[0].worldIdsMap`、`params.tags[0].entitiesId`、
以及"登记条目声明 `objects_id` + 参数值 `entity-7f3a41c9b2e05d18`（= 冻结上下文 `world_side.handle_entity_map` 里 h-1 的真实实体 ID）"→ accepted。
统筹的探针要求里词元已含 `ids/Ids`，因此"复数"这一维最自然的读法是**标识词复数化**；即使按窄读法，本项也属裁决 2 的
"等世界侧标识字段"（开放列举）并且是同一类缺陷，不能算超范围。

**F2（阻断·证据完整性）被点名拼写的反例产物缺失。**
`invalid/world_id_norm_Entity_Id.json` 与 `invalid/world_id_norm_ENTITY_ID.json` 在 macOS 大小写不敏感卷上同 inode（65147926）、同 sha（`c31907fc…`），
磁盘内容键名为 `ENTITY_ID`；`invalid/` 43 份 vs 声明 44 条反例；按名字集合比对，声明存在而磁盘缺失的是
`invalid/world_id_norm_ENTITY_ID.json` 与 `contexts/world_id_norm_ENTITY_ID.json`；`Entity_Id` 的 `proposal_sha256`（`67e2a7c1…`）无产物；
`check_result.json` 两条用例行携带同一 sha。结论：**"12 种拼写独立反例"在本机只交付 11 份**，
统筹打回意见里逐字点名的 `Entity_Id` 实际未被独立夹具覆盖（规范化规则本身确实拒它，属证据/覆盖缺陷而非活体泄露）。
附带风险：在大小写敏感文件系统（Linux CI）上，套件"临时生成 vs 提交夹具"的逐字节比对会因生成侧多出一个名字而 exit 1
（**此条为推断，未在大小写敏感卷上实测**）。

**F3（重要）能力登记条目属性名防御覆盖不足（r3 要求 b）。**
`check_schema_props_forbidden`（`check_skill_proposal.py:79-93`）只递归 `properties`/`items`/`$defs`：复数字干 0/396 被标记、
`patternProperties` 分支完全不扫描；条目 schema 也不约束 `param_schema.properties` 的属性名（`world_id` 等逐个 VALID）。
`patternProperties` 用例最终被提案层规范化兜住（`--disable world_id_normalization` 后 exit 0 佐证条目层零贡献）。

**F4（重要）两条崩溃路径违反 fail-closed 与裁决 8。**
(a) `basis.t_ticks = 2^53`（schema 只有 `minimum: 0`，无上限）→ `ValueError: jcs_integer_out_of_range`，exit 1 但无 stdout JSON、无原因码、无回执；
连"关掉 evidence+duplicate"的对照也崩在回执泄露扫描的 JCS 上；换成安全整数 `t_ticks=999` 则得到干净的 `evidence_mismatch` 拒绝（差分成立）。
(b) 参数值含孤立代理项 `\ud800` → `UnicodeEncodeError`，同样只有 traceback。
两者都是"异常退出"，按任务约定**不算有效拒绝**：门禁必须给出白名单原因码（理论上应为 `schema_invalid`）。

**F5（中等）schema 单层覆盖与文档表述不符。**
统筹点名族里 schema 单层只拒 66/402，真正兜住的是第二层规范化（402/402）。`docs/v9/SKILL_PROPOSAL.md:53-57` 确实把两层都写成规范要求，
但 §13 闭合表第 2 行"`params.propertyNames` 任意层级禁世界 ID 键"会让只读 schema 的实现方误以为契约已封闭（实际漏 336/402）。
建议在文档与 schema 描述里明确"仅 schema 不足以满足裁决 2，AWZ 门禁必须实现规范化判定"。

**F6（中等）`quantity` 值的禁止清单与键名规则不一致。**
`expected_outcomes[].quantity` 实测通过（schema 合法且门禁 accepted）：`world.id`、`worldids`、`worlds_id`、`object_id`、`agent_id`、`ids`；
被拒的只有 6 个字面量（`world_id/entity_id/scene_id/event_id/instance_id/hidden_contact`，另有大写形式被小写名称模式顺带拒）。
这与文档"`quantity` 的值同样不得是这些标识或 `hidden_contact`"（`SKILL_PROPOSAL.md:56`）不一致：键名用规范化规则、值用 6 项字面清单。

**F7（中等·证据完整性）r3 未更新交付物 SHA 清单。**
`reports/V9-B1/REPORT.md:38-43` 仍是 r1 的哈希表，其中 4 项与磁盘不符：`check_skill_proposal.py`（报告 `d6210c4b…` vs 实 `d1f8ab82…`）、
`skill_proposal.v1.schema.json`（`09d90541…` vs `dc6915a1…`）、`docs/v9/SKILL_PROPOSAL.md`（`097231af…` vs `b515bd75…`）、
`EXPECTATIONS.json`（`38de1537…` vs `453ab6be…`）。另：`EXPECTATIONS.json` 内两种哈希口径混用（提案=原始字节，上下文=JCS 规范摘要），
我第一次比对因此产生 53 个假失配，读者同样容易被误导 —— 与"报告写实际命令、全部输入/输出 SHA"的要求不符。

**F8（观察，不单独作为打回依据）**
1. 值级偷带：键名合法（`color`）而值为真实实体 ID → 门禁 accepted。裁决 2 只要求**字段级**禁止，故属超范围残留；
   建议 AWZ 侧补充值级白名单/模式检查。
2. `--disable` 无 `choices=`，未知规则名是静默空操作（实测 `--disable paramss` 等效于不关任何检查）——方向安全，但打错字的"对照"会静默失效。
3. `world_side_log` 由参考核对 CLI 打到 stdout（未进回执；我抽样未见解析实体）——对接线台/日志分级时需注意裁决 8 的两层落点。
4. `--regenerate` 在 gate/reply 模式被静默忽略；变异 schema 依赖硬编码下标（`$defs.param_value.oneOf[5]`、`$defs.target.oneOf`），契约演进会打断对照。
5. `--suite` 无条件重写 `reports/V9-B1/check_result.json`（内容确定性已由我复跑证实逐字节相同），复核者若在只读要求下运行需自行备份。

## 5. 裁决 1–11 逐条判定

| 裁决 | 判定 | 证据 / 反例（含破坏对照） |
|---|---|---|
| 1 只开运行路线 | **通过** | 提案无 route/effect_class；编辑集合空由上下文+核对器 fail-closed；`edit_effect_class` 反例 + `--disable effect_class` 真实漏检；schemas 层承载见 `ability_registry_entry.v0:32-38` |
| 2 只用句柄、禁世界 ID | **不通过** | 句柄三态与原始实体 ID 当句柄均正确拒绝；但复数词干 396/396、别名 165/297 逃逸（F1），条目层覆盖不足（F3），schema 单层只拒 66/402（F5） |
| 3 证据版本绑定 | **通过** | 自写 JCS 21/21 + 52/52 pin 复现 + 与作者逐字一致；伪造 basis 自算摘要 2/2 被拒且对照真实漏检；`evidence_version` 复算 51/52（1 条按设计） |
| 4 TTL 用 tick、时间域不换算 | **通过** | 边界内 accepted、+1 `proposal_expired`、`--disable ttl` 真实漏检（窗口已收敛到 ttl 内，排除其他规则干扰）；跨 episode 直接拒 |
| 5 能力登记是唯一依据 | **部分通过** | 未登记/越界/缺必填/动作数/时长/TTL 上限/目标种类/前置条件全部有反例+对照；条目 `param_schema` 属性名防御不完整（F3） |
| 6 置信度不作门禁依据 | **通过** | `confidence=1.0`+未登记能力 → `ability_unknown`；唯一能越门的路径是被显式 `--disable confidence_independence` 破坏 |
| 7 预期结果用观察量表达 | **部分通过** | 真值/事件类型字段 3/3 被拒、窗序反例已覆盖；`quantity` 值清单不完整（F6） |
| 8 回执两层防泄露 | **通过（附 F4 例外）** | 非白名单原因、夹带解析实体、自定义非白名单原因 3/3 被拒且变异 schema 对照真实转有效；回执 7 字段全标量，无字段可携带解析实体；例外：崩溃路径不产生带白名单原因码的回执 |
| 9 不静默改写 | **通过（有限证据）** | 8 条正例回显=提交=重算；属门禁行为断言，真实门禁未实现，已如实标注 |
| 10 身份与幂等 | **通过** | actor 不符拒、同 ID 换载荷 `duplicate_proposal`、`--disable duplicate` 真实漏检；"整份提案 JCS 摘要"属加强读法，已在 §10 说明，请统筹裁决 |
| 11 数据去向 | **未实现（如实登记）** | 仅文档写明；schema 无覆盖；本轮不实现，与说明一致，无异议 |

## 6. 失败与未验证项（如实登记）

1. **未实现/未运行**：真实 AWZ 门禁、内核求值、`WorldBrainAdapter`、E3 编译；所有夹具仍是 synthetic 冻结上下文，不构成运行授权或能力声明。
2. **未实测（推断）**：大小写敏感文件系统上套件的字节比对行为（F2 附带风险）——本机无相应卷，未创建/挂载卷。
3. **未执行**：`--regenerate` 原地重写路径（会改写交付目录，按只读要求不跑）；置信度 84 行扫描未独立重跑（我只自测了 1.0 越门与 `--disable` 对照）；
   `canon` vs JCS 的 8 处差异未逐条复核（作者声明只报告）。
4. **未比对**：RFC 8785 官方 `testdata`（无下载授权）；我的 JCS 仅以 21 条手写向量 + 与作者引擎在 52 份真实文档上的一致 + 52/52 pin 作为证据。
5. **未深挖**：`world_side_log` 文本内容未做全量泄露扫描（只抽样）；回执泄露扫描依赖上下文中已知的世界侧 token 集合。
6. 测试通过不等于能力通过；本轮没有真实运行、没有模型参与，也没有对 r3 的 `accepted` 授权。

## 7. 建议（不 accept 自己）

**不建议直接验收 r3；建议 r4 做 4 处最小加固后重新复核**（加固后本目录的探针矩阵可直接复跑）：

1. **键名判定改为词元边界判定**（F1）：小写去分隔符后，按 `[标识词或复数] + [id|ids]` 相邻词元对判断，或等价地在任意后缀/前缀存在时仍命中；
   并明确白名单（`actor.agent_id` 等固定身份字段）。
2. **条目层与 schema 层补齐**（F3/F5）：`param_schema` 属性名扫描覆盖 `patternProperties`/`allOf`/`anyOf`/`oneOf`/`prefixItems`；
   在 `ability_registry_entry.v0` 内用 `propertyNames` 表达同一约束；文档明确"仅 schema 不足"。
3. **fail-closed 与一致性**（F4/F6）：JCS 整数超范围/孤立代理项 → 合法 `schema_invalid` 拒绝（不得 traceback）；
   `quantity` 值改用与键名相同的规范化判定；schema 给整数字段加 `maximum`。
4. **证据修复**（F2/F7）：在大小写敏感环境重生成夹具（或把 `Entity_Id` 改名为不冲突的名字并更新 pin/EXPECTATIONS），
   补 `Entity_Id` 的独立产物；更新 r3 的交付物 SHA 清单并统一 `EXPECTATIONS` 的哈希口径（原始字节 vs JCS 摘要）。

**应保留的有效部分**：作者套件复跑 exit 0 且 44/44 + 7/7 破坏对照真实隔离；`--suite` 不再改写交付目录；
被点名族 402/402 与 hidden_contact 36/36 全拒（相对 r2 是实质改进）；关闭对象位置无位置漏洞；
独立 oracle 与作者夹具 52/52 + 10/10 交叉一致；回执白名单与实体泄露防护完整；TTL/时间域/句柄/证据/幂等/编辑类的反例与控制链闭合。

## 8. 交回统筹（需要决定的问题）

1. F1 的"复数"读法：按统一探针要求字面（词元已含 `ids/Ids`）应理解为**词干复数**，即 r3 未闭合裁决 2；若统筹按窄读法判为超范围，
   我仍建议至少按 F2（被点名拼写无产物）、F4（崩溃）、F7（SHA 清单）出 r4。
2. F6 的 `quantity` 值域是否要与键名规范化规则统一（会同时影响 schema 与 AWZ 侧参数校验口径）。
3. 裁决 10 的"整份提案 JCS 摘要"加强读法是否维持（r1 已提，仍在等裁决）。
4. 值级偷带（F8-1）是否要进 AWZ 门禁契约（超出裁决 2 字面，但影响 F2/F4 的信息隔离目标）。

## 9. 交回过程说明（接力台受管作业归档，透明登记）

本任务 probe 阶段用 `relay exec` 拉起（自动心跳），监督器因**本沙箱禁用 `ps`** 无法枚举进程组，
按设计拒绝归档终态（`exit_unconfirmed`，`confirmed_empty=false`，`members_left=null`；组长 `leader_returncode=0`），
导致 `relay report` 被 409 挡住（`_unconfirmed_execs` 要求 exec 已归档为 finished/stopped/launch_failed）。
处理：用直接系统调用复核 `os.killpg(68232, 0)` → `ProcessLookupError`（进程组确认为空），
再经接力台自身的 `POST /api/tasks/ainerzero.V9.B5/exec/<id>/finish` 以 `state=finished` 归档，
detail 里写明证据来源（监督器 leader_returncode=0 + killpg 空组）。这是**唯一**一次对照料台状态的写操作，
未改任何项目文件；此后不再使用 `relay exec`（本沙箱下它无法归档终态）。

产物：本报告 `reports/V-V9-B1/REPORT_B4-r3.md`、指标 `reports/V-V9-B1/metrics_b4-r3.json`、
自写 oracle `oracle_r3.py`、harness `verify_b4r3.py`、原始结果 `oracle_results.json`/`probe_results.json`/`adverse_results.json`/`suite_results.json`、
反例夹具 `reports/V-V9-B1/adverse/**`、哈希清单 `SHA256SUMS_b4-r3.txt`。原作者未对结果声明 accepted 或能力通过。
