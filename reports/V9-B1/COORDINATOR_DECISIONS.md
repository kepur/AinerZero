# V9.B1 SkillProposal/v1 统筹裁决（Claude，2026-10-16）

依据：ARCHITECTURE_V9 r5 §2（分层规划 → SkillProposal）、§3 `WorldBrainAdapter.propose`（提案带 TTL 与证据版本）、ADR-0012 §26/§36（世界脑只能提案、经 AWZ 能力门禁、不直接写世界）、Event/v1 r2 裁决 F2/F4（学习侧禁原始 Event、世界 ID、隐藏接触）、ObservationPacket v1.1（检测句柄 `h-<n>`，`handle_policy = reissue_after_occlusion`）、E3 r1 裁决（`reports/P3-E3/r1/COORDINATOR_DECISIONS.md`，尤其 4、5、13）。

本轮只出契约、schema、示例、反例和报告目录里的 CPU 参考核对。AWZ 门禁的实际实现、内核执行与 `WorldBrainAdapter` 实现都是代码，归 B2 与 AWZ 侧后续卡，按 D-019 在 awz.V9.A10 之后。不改主架构 r5、ObservationPacket v1.1、Event/v1 候选与 E3 裁决。

## 裁决

1. **两条路线，v1 只开一条**：
   - **运行路线**：提案是学生在运行中的 AWZ 回合里，用自己的身体和能力做动作。AWZ 能力门禁通过后由内核求值，结果只以 Event/v1 事件（source 为学生动作）和之后的观察体现。它不产生 E3 信封，不改持久世界和场景源。
   - **编辑路线**：能力的效果类别是改世界或改场景时，门禁把提案编译成 E3 信封，actor 为世界脑，按 E3 裁决 5 只能预览，提交要用户确认或授权。
   - v1 已登记的编辑类能力集合**为空**（同 ADR-0005 例外集合为空的处理）。任何提案引用编辑类效果一律 `effect_class_not_registered`。编辑路线只定义格式，合成正例不得冒充实际授权。

2. **目标只能用观察句柄，不用世界 ID**（守 F2/F4）：`targets` 里的对象引用只能是提案所依据的 ObservationPacket 中出现过的检测句柄 `h-<n>`。门禁在世界侧把句柄解析成实体，映射永远不回传给世界脑。句柄不在所依据的包里、已因遮挡重发而失效、或无法解析，一律拒绝。空间目标用智能体自身坐标系（相对位姿加不确定性）表达，不写世界真值坐标。schema 层面禁止出现 `entity_id`、`world_id`、`scene_id`、`event_id` 等世界侧标识字段。

3. **证据版本绑定所依据的观察和信念**：
   - `basis` 字段固定为：`packet_ref`（ObservationPacket 的 URI 与 sha256）、`t_ticks`、`time_domain`（episode、epoch、120 Hz，与 teacher_cache r3 同口径）、`belief_sha256`（BeliefSummary 摘要）和 `brain`（模型、编码器、规划器各自的版本）。
   - `evidence_version` 取 basis 的 JCS 摘要（规范 JSON 按 E3 裁决 13，RFC 8785）。门禁重算摘要，不一致即拒。

4. **TTL 用 tick 计，不用墙钟**：`ttl_ticks` 为正整数，并有上限，上限由 AWZ 能力登记给出。提案只在 `[basis.t_ticks, basis.t_ticks + ttl_ticks]` 内有效。门禁按当前回合 tick 判断，过期为 `proposal_expired`。时间域与当前回合不一致直接拒，不做换算。

5. **能力登记是门禁的唯一依据**：每个 `ability_id` 由 AWZ 登记。登记条目至少包含：
   - 参数 schema；
   - 效果类别（运行／编辑）；
   - 可作用的目标种类；
   - 最大动作数；
   - 最大持续 tick；
   - TTL 上限；
   - 前置条件（只能用观察可得的量来表达）。

   未登记的能力、参数不合 schema、超出数量或时长，一律拒绝。本轮在 AinerZero 侧只写门禁所需的最小登记条目形状，作为草案；正式登记表归 AWZ。

6. **置信度只作参考，不作门禁依据**：`confidence` 允许出现，范围 [0,1]，并须声明 `calibration`（登记的校准引用，或 `uncalibrated`）。能力、目标、预算、锁、权限的判定都与置信度无关。必须有反例证明：把置信度调到 1.0 也不能越过任何一道门（同 E3 裁决 4 “为提分改锁定字段”的思路）。

7. **预期结果用观察量表达**：`expected_outcomes` 是对未来观察的预测，每项包含：
   - 观察通道（只能是 ObservationPacket v1.1 已有的通道）；
   - 预测量与不确定性；
   - 时间窗（tick）。

   它用于事后比对学习进展与好奇心，不得写世界真值字段、事件类型或隐藏接触。

8. **门禁回执分两层，防止泄露**：
   - 世界侧的门禁决定（accepted / rejected 加详细原因，含解析到的实体）只写入世界侧日志。
   - 回给世界脑的只有白名单原因码：`schema_invalid`、`ability_unknown`、`params_invalid`、`budget_exceeded`、`proposal_expired`、`time_domain_mismatch`、`evidence_mismatch`、`handle_unknown`、`effect_class_not_registered`、`duplicate_proposal`，外加 accepted。
   - “目标在墙后”“对象其实已不存在”这类会暴露隐藏状态的原因，一律折叠成 `handle_unknown` 或 `rejected_other`。执行结果只能通过之后的观察获得。

9. **不静默改写提案**：门禁要么原样接受，要么拒绝。不做裁剪、补全或替换参数后再执行。

10. **身份与幂等**：
    - 门禁从会话取 actor（世界脑的运行与智能体身份）；提案自带 actor 与会话不符即拒。这只是世界侧日志的拒绝原因；回给世界脑仍按裁决 8 的白名单。
    - `proposal_id` 在（回合、actor）内唯一。同 ID 同摘要返回原决定；同 ID 不同摘要拒为 `duplicate_proposal`。

11. **数据去向**：提案、门禁决定（世界侧完整版）和之后的观察，按回合所在分区进入 Forge ExperienceEpisode。`final` 分区的提案与结果不得用于训练。本轮只在文档写明这一规则，不实现。

## 执行与证据（交二级 ainerzero.V9.B4）

- 交付：`contracts/v9/skill_proposal.v1.schema.json`、门禁回执（世界脑可见版）schema、能力登记条目草案 schema；正例与反例放在 `contracts/v9/examples/skill_proposal_v1/`；规范说明写成 `docs/v9/SKILL_PROPOSAL.md`；参考核对、报告和指标放在 `reports/V9-B1/`。
- 参考核对：在明确标为 synthetic 的冻结上下文里（一个合成 ObservationPacket 摘要、一份合成能力登记、当前 tick、会话 actor），按裁决 1–10 判定提案接受或拒绝。上下文与待验提案分开，预期身份由调用方固定（同 T1 r3 裁决 5）。
- 反例至少覆盖：
  - 世界 ID 字段；
  - 句柄不在所依据的包里；
  - 遮挡后旧句柄；
  - 证据摘要不符；
  - TTL 过期，以及恰好在边界上（边界内为正例）；
  - 时间域不符；
  - 未登记能力；
  - 参数越界；
  - 动作数或时长超限；
  - 编辑类效果；
  - 置信度 1.0 仍被拒；
  - 预期结果含真值字段；
  - actor 不符；
  - 重复 ID 换载荷；
  - 门禁可见回执中出现非白名单原因。
- 每条规则配一个独立反例，以及一个“关闭该检查后专用反例漏检”的破坏对照；异常退出不算有效对照。
- 报告写实际命令、全部输入/输出 SHA、计数、失败与未验证项。随后由非作者 ainerzero.V9.B5 复核。
