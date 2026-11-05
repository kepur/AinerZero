# ainerzero.V9.B5 独立复核报告（r2 修订重新独立核验）

- **复核任务**：`ainerzero.V9.B5`
- **被复核任务**：`ainerzero.V9.B4`（修订 r2，作者：`grok-m4q8`，承接 `deepseek-flash-a7k2` 原件，状态：reported）
- **复核者**：`antigravity-7c1e`（二级执行层，非作者，非 Claude 一级）
- **时间**：2026-10-16
- **复核结论**：**建议验收（Recommended for Acceptance）**
- **依据**：`reports/V9-B1/COORDINATOR_DECISIONS.md`（裁决 1–11）
- **执行环境**：纯 CPU，无 GPU，无训练，无 MLX/ORT，无网络下载，只读核验被验文件

---

## 1. 摘要与核心指标

针对统筹 Codex 对上一轮 B5 报告的打回意见（指出上一轮漏检 schema/门禁对 `quantity=world_id/hidden_contact` 与 camelCase `params.worldId/entityID` 的泄露通道，且未实际复跑作者脚本、未逐例证明真实非零退出），复核方对 B4 r2 修订成果展开了全新的、严格的重新独立复核。

复核方从零构建独立 JCS (RFC 8785) 序列化器与独立门禁判别 Oracle（`reports/V-V9-B1/verify_skill_proposal.py`），对 B4 r2 全部 40 份提案夹具、10 份回执夹具、32 份提案对照、7 份回执对照展开实跑交叉验证，并通过独立子进程对 15 个自写对抗不利反例进行了真实的逐例非零退出验证。

### 核心复核结果

| 复核项 | 期望 / 门槛 | 实际复核结果 | 判定 |
|---|---|---|---|
| **作者套件实际复跑 (check_skill_proposal.py)** | 返回码 0，all_ok=true | **实跑返回码 0**，用时 18.871s，40 用例全部通过，32+7 对照全部隔离漏检 | **通过** |
| **Schema 元校验 (Draft 2020-12)** | 3/3 份通过 | 3/3 通过（`skill_proposal.v1`、`skill_gate_reply.v1`、`ability_registry_entry.v0`） | **通过** |
| **独立 JCS (RFC 8785) 引擎自测** | 基础及 UTF-16 键序 | 6/6 通过（含字符串转义、控制字符、UTF-16 码元排序、ECMAScript 数字格式） | **通过** |
| **作者提案夹具交叉复验** | 40 份 100% 吻合 | 40/40 吻合（8 正例全部 accepted，32 反例原因码逐条精确匹配） | **通过** |
| **作者回执夹具交叉复验** | 10 份 100% 吻合 | 10/10 吻合（3 正例合规，7 反例均被 schema 封闭枚举与约束拦截） | **通过** |
| **打回项 1：quantity 值禁止泄露** | world_id 与 hidden_contact 拒 | `quantity="world_id"` 与 `"hidden_contact"` 均被 schema 严密拦截，退出码 1 | **通过** |
| **打回项 2：驼峰键名禁止泄露** | params.worldId / entityID 拒 | `params.worldId` 与 `params.entityID` 均被 `world_id_key` 模式拦截，退出码 1 | **通过** |
| **打回项 3：逐例真实非零退出** | 独立子进程真实非零退出 | **15 个不利反例全部在独立子进程中产生返回码 1 (exit 1)**，无布尔模拟 | **通过** |
| **打回项 4：配对破坏对照真实隔离** | 独立子进程真实退出 0 | **15/15 破坏对照在独立子进程中产生返回码 0 (exit 0)**，证明严格隔离 | **通过** |
| **统筹裁决 1–11 逐条闭合** | 逐条可查 | 11/11 条裁决在文档与 Schema 中逐条落实，证据链闭合 | **通过** |

---

## 2. 输入文件身份（只读核对，SHA256）

| 输入文件 | SHA256 | 说明 |
|---|---|---|
| `reports/V9-B1/COORDINATOR_DECISIONS.md` | `04504c33643c30b3116abe5cd8430fe2bc0e8f44fa70154b9c2f892f93a6d113` | 统筹裁决（冻结未改） |
| `contracts/v9/skill_proposal.v1.schema.json` | `dc6915a12d1c66527df4dcc4352b3b010c64dbfe329f4698de7fe00a9983f486` | B4 r2 修订 Schema |
| `contracts/v9/skill_gate_reply.v1.schema.json` | `dc81852c0dc6341a033bcf9ed70c969091faae541e775c4682cb0ce6f1840f2c` | 回执 Schema |
| `contracts/v9/ability_registry_entry.v0.schema.json` | `1f087c7f95f9a8451312529816915e811ca648d25ebca7bdcaa44d6bf7080d60` | 能力登记 Schema |
| `docs/v9/SKILL_PROPOSAL.md` | `207ac1e00e8f00e27ce8bccd835ac0aeb787efae5991492cdf9ee0c480166e98` | B4 r2 规范文档 |
| `reports/V9-B1/r2/REPORT.md` | `8e4bd50020760eaf05c47c0171a3113782d07375ad20d8d24c6cc723eddad88b` | B4 r2 修订报告 |
| `reports/V9-B1/r2/metrics.json` | `8aa75fca8077d287ab7939f4cdd5c6bba9c85de8e78b59d43c24152b039254db` | B4 r2 指标数据 |
| `reports/V9-B1/check_skill_proposal.py` | `d7b928f33ee4be2e50019340e02c2791e3c883bb84f754418229ba386e56a33b` | B4 r2 核对脚本 |
| `reports/V9-B1/check_result.json` | `7fffbe30bd27d3a663d7448a2b9c8a752073a707a57bcdfb5e7d80ea1214e99f` | B4 r2 核对结果 |

---

## 3. 打回项专项对抗审查与证明

### 3.1 `expected_outcomes.quantity` 值防泄露通道
- **漏洞机理**：裁决 2 与 7 禁止通过预测量名称夹带世界侧实体/世界 ID 或隐藏接触信息。上一轮仅检查键名，未校验 `quantity` 的字符串值本身。
- **B4 r2 修订**：在 `expected_outcome.properties.quantity` 中增加 `allOf.not.pattern`:
  `(^|\.)(world_id|entity_id|scene_id|event_id|instance_id|hidden_contact)($|\.)`。
- **独立复核验证**：
  1. `ADV-04`（`adv_quantity_value_world_id`）：子进程实测返回码 `1`（`schema_invalid`）；关掉正则检查后子进程实测返回码 `0`（漏检接受）。
  2. `ADV-05`（`adv_quantity_value_hidden_contact`）：子进程实测返回码 `1`（`schema_invalid`）；关掉正则检查后子进程实测返回码 `0`（漏检接受）。
  3. 作者夹具 `quantity_value_world_id` 与 `quantity_value_hidden_contact` 经独立 Oracle 交叉核对均判 `schema_invalid`，吻合度 100%。

### 3.2 `params` 中驼峰命名世界 ID 防泄露通道
- **漏洞机理**：上一轮 `world_id_key` 模式仅覆盖全小写蛇形命名（如 `world_id`），若调用方构造驼峰命名的 `worldId` 或 `entityID`，则能越过 `propertyNames` 检查。
- **B4 r2 修订**：将 `world_id_key` 模式拓展为包含驼峰模式：
  `([Ww]orld|[Ee]ntity|[Ss]cene|[Ee]vent)[Ii][Dd]s?$|[Hh]idden_?[Cc]ontact$`。
- **独立复核验证**：
  1. `ADV-02`（`adv_camel_case_world_id_in_params`）：子进程实测返回码 `1`（`schema_invalid`）；关掉检查后返回码 `0`。
  2. `ADV-03`（`adv_camel_case_entity_id_in_params`）：子进程实测返回码 `1`（`schema_invalid`）；关掉检查后返回码 `0`。
  3. 作者夹具 `world_id_camel_in_params` 经独立 Oracle 交叉核对判定为 `schema_invalid`。

### 3.3 实跑证据与逐例真实非零退出证明
- **作者脚本实跑**：通过 Python `subprocess.run` 现场调用 `/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V9-B1/check_skill_proposal.py --suite`，获得返回码 0，用时 18.871s，实时获取作者 40 例提案校验与 32+7 例破坏对照真实隔离数据。
- **15 例对抗反例逐例实跑**：复核脚本通过 CLI 选项 `--run-case <id>` 与 `--run-control <id>` 在独立 OS 进程中唤起，逐例捕获子进程真实退出状态：
  - 全部 15 例反例基线均在子进程退出 `exit 1`（真实非零退出）；
  - 全部 15 例配对对照均在子进程退出 `exit 0`（真实隔离漏检）。

---

## 4. 15 个独立对抗不利反例与真实非零退出清单

| 编号 | 反例名称 | 对抗攻击向量 | 预期原因码 | 基线进程退出码 | 关守卫进程退出码 | 隔离漏检判定 |
|---|---|---|---|---|---|---|
| **ADV-01** | `adv_nested_world_id_in_deep_params` | 深层嵌套 params 夹带 `target_entity_id` 键 | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-02** | `adv_camel_case_world_id_in_params` | params 中夹带驼峰 `worldId` 键（B4 r2 封堵） | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-03** | `adv_camel_case_entity_id_in_params` | params 中夹带驼峰 `entityID` 键（B4 r2 封堵） | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-04** | `adv_quantity_value_world_id` | `expected_outcomes.quantity` 设为 `world_id`（B4 r2 封堵） | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-05** | `adv_quantity_value_hidden_contact` | `expected_outcomes.quantity` 设为 `hidden_contact`（B4 r2 封堵） | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-06** | `adv_foreign_cross_packet_handle` | targets 使用跨包/未观测到的 `h-999` 伪造句柄 | `handle_unknown` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-07** | `adv_stale_handle_retired_post_occlusion` | targets 使用遮挡失效后已进入 `retired_handles` 的 `h-7` | `handle_unknown` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-08** | `adv_forged_basis_self_computed_evidence` | 伪造 observation 包引用，自算 JCS 哈希作为 evidence_version | `evidence_mismatch` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-09** | `adv_ttl_boundary_plus_one_tick` | 评估时刻严格超过 TTL 截止边界 1 tick (1231 > 1230) | `proposal_expired` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-10** | `adv_cross_episode_time_domain` | basis 夹带外来 episode_id 跨回合冒充时间域 | `time_domain_mismatch` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-11** | `adv_confidence_one_override_budget` | 置信度设为 1.0 试图越过 max_actions 预算上限 | `budget_exceeded` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-12** | `adv_edit_effect_masquerading_run` | 引用 effect_class 为 edit 的能力伪装成运行技能 | `effect_class_not_registered` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-13** | `adv_expected_outcome_event_type_truth` | expected_outcomes 中偷带 `truth_event_type` 真值字段 | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-14** | `adv_gate_reply_leaks_hidden_state` | 门禁回执尝试暴露非白名单的 `hidden_target_behind_wall` | `schema_invalid` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |
| **ADV-15** | `adv_duplicate_proposal_id_payload_mutation` | 复用已决策提案 ID 但篡改其预算载荷 | `duplicate_proposal` | **1 (exit 1)** | **0 (exit 0)** | **有效隔离** |

---

## 5. 统筹裁决 1–11 逐条判定矩阵

| 裁决项 | 统筹要求核心 | B4 r2 落实情况与证据 | 独立复核判定 |
|---|---|---|---|
| **裁决 1 两条路线，v1 只开一条** | 运行走 run，编辑走 edit；v1 编辑集合为空；编辑类一律拒为 `effect_class_not_registered`；提案不自声明路由 | `docs/v9/SKILL_PROPOSAL.md` §1；提案无 route 字段；`ability_registry_entry.v0` 推导；反例 `edit_effect_class` 命中；对抗用例 `ADV-12` 证明编辑能力被拒且关检查后漏检 | **通过** |
| **裁决 2 目标只能用句柄，不用世界 ID** | 目标限 `h-<n>` 或自身坐标相对位姿；全对象禁世界 ID（含驼峰与 quantity 值）；旧句柄/跨包句柄拒 `handle_unknown` | 提案 Schema `propertyNames` 在任意嵌套层级拦截蛇形/驼峰世界标识；`quantity` 正则拦截实体标识；对抗用例 `ADV-01` 至 `ADV-07` 全量复证 | **通过** |
| **裁决 3 证据版本绑定观察和信念** | `basis` 固定 5 字段；`evidence_version` 取 basis JCS (RFC 8785) 摘要；门禁重算比对 | Schema 强制 5 字段；门禁重算 JCS SHA256；反例 `evidence_digest_mismatch`、`evidence_packet_ref_mismatch` 命中；对抗用例 `ADV-08` 复证 | **通过** |
| **裁决 4 TTL 用 tick，时间域不换算** | `ttl_ticks` 正整数有上限；闭区间 `[t_ticks, t_ticks + ttl]`; 超期 `proposal_expired`；时间域不符 `time_domain_mismatch` | 边界正例 `valid_ttl_lower_boundary` 与 `valid_ttl_upper_boundary` 通过；反例 `ttl_expired` 在右端 +1 拒；对抗用例 `ADV-09`, `ADV-10` 复证 | **通过** |
| **裁决 5 能力登记是唯一依据** | 每个 ability 由登记给出参数 schema、动作数、持续 tick、TTL 上限、前置条件；超限/未知一律拒 | `ability_registry_entry.v0` 元校验通过；反例 `ability_unknown`、`params_*`、`budget_exceeded`、`target_kind_*`、`precondition_*` 覆盖完整 | **通过** |
| **裁决 6 置信度不作门禁依据** | 置信度选填需声明校准引用；置信度 1.0 不能越门 | 反例 `confidence_one_ability_unknown` 证明 1.0 仍被拒；置信度扫描 60 行判定逐条不变；对抗用例 `ADV-11` 证明 1.0 无法越过预算门 | **通过** |
| **裁决 7 预期结果用观察量表达** | 仅限 8 个通道；时间窗在 TTL 闭区间内；禁写世界真值、事件类型或隐藏接触（含 quantity 值） | Schema 通道封闭枚举；时间窗判定 `0 <= start <= end <= ttl`；反例覆盖真值与逆序时间窗；对抗用例 `ADV-04`, `ADV-05`, `ADV-13` 复证 | **通过** |
| **裁决 8 回执分两层，防止泄露** | 世界侧日志留实体与真实原因；世界脑回执仅 12 个白名单原因码封闭枚举；折叠隐藏状态 | `skill_gate_reply.v1` 封闭枚举与 `allOf` 一致性；回执扫描世界 ID 泄露为 0；回执反例 7 条全过；对抗用例 `ADV-14` 证明非白名单原因被拒 | **通过** |
| **裁决 9 不静默改写提案** | 原样接受或拒绝；回显 evidence_version 与提交值逐字节相等 | 正例 8 条断言回显值 = 提交值 = 重算值；任何篡改均被 `evidence_mismatch` 拦截 | **通过** |
| **裁决 10 身份与幂等** | 从 session 取 actor，自带不符拒 rejected_other；同 ID 同摘要返回原决定；同 ID 换载荷拒 duplicate_proposal | 门禁以会话为准；同 ID 同摘要幂等重放；同 ID 换载荷被拒；对抗用例 `ADV-15` 证明换载荷拦截有效 | **通过** |
| **裁决 11 数据去向与 final 门禁** | 规范明确 final 分区数据不得用于训练；契约层已作说明，本轮不实现代码符合 ADR-0012 | 规范文档明确分区约束；纯只读工程复核，未调用模型，未进行训练 | **通过** |

---

## 6. 产物、校验和与复现命令

- 独立复核脚本：`reports/V-V9-B1/verify_skill_proposal.py`
- 详细复核数据：`reports/V-V9-B1/verification_result.json`
- 核心指标数据：`reports/V-V9-B1/metrics.json`
- 校验清单：`reports/V-V9-B1/SHA256SUMS.txt`

### 一键复现命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python reports/V-V9-B1/verify_skill_proposal.py
# Independent Verification Complete:
#   All Checks Passed: True
#   Author Suite Live Run: returncode=0, elapsed=18.871s, all_ok=True
#   Meta Schema Checks: 3/3 passed
#   JCS Self Tests: 6/6 passed
#   Author Proposals Cross-Checked: 40/40
#   Author Replies Cross-Checked: 10/10
#   Adverse Cases Real Nonzero & Control Zero Exits: 15/15
# exit 0
```

---

## 7. 限制与未验证项（如实声明）

1. 本复核为基于真实上下文与夹具的静态契约和逻辑验证，未挂接真实 AWZ 在线世界环境（符合 ADR-0012 范围划分）。
2. 未启动 GPU，未进行任何 MLX/ORT 推理，未触碰 `m0-worker.lock`。
3. 测试通过表明契约与参考门禁严密无泄露，不代表技能已在物理引擎中完成动作闭环。

---

## 8. 交回统筹结论

B4 r2 修订完全修复了上一轮打回指出的所有泄露通道：
- 严格封堵了 `quantity=world_id` 与 `quantity=hidden_contact`；
- 严格封堵了 `params` 中的驼峰命名世界标识；
- 现场实跑作者套件（40 提案 + 32 对照 + 7 回执对照）全部真实通过；
- 现场子进程逐例实跑 15 组自写不利反例与对照，全部产生真实非零退出与真实隔离退出。

本复核判定 B4 r2 **完全达到验收标准，建议统筹予以验收通过**。
