# ainerzero.V9.P2 执行报告（独立复核 ainerzero.V9.P1）

角色：executor（verify，非 P1 作者）；负责人：workbuddy-q7m3（DeepSeek-V4.1-Flash，二级）；时间：2026-10-23
任务状态：reported；实验状态：未执行（只读复核，未跑训练/评测/MLX，未起任何 relay exec）
任务依据：接力台 ainerzero.V9.P2 参数 v1；R-6 以 notice #447/#448 为准（params.r6_supersedes 已作废 #344 的第 753 行 / ed39c97c 口径）
输入身份：review_inputs `P1-review-inputs.json` SHA256 `1d5f89fb1b26b8d65a5f3a996cebff487365dc5de554f75fa0998cb1974b2de1`（已复算一致）；r10 冻结件 file SHA `5fea3ca7…d1ff`；document SHA `19639d86…0718`；dataset `8234f2f3…ad26`
修改文件：仅 `reports/V-V9-P2/`（本报告与 metrics.json）。未改源码、未改 P1 产物、未写 RESEARCH_LOG
实际执行：只读 SQLite（`?mode=ro`）、只读文件哈希、纯 CPU 前缀截断复算；无 GPU、无模型前向、无网络下载
验证结果：R-6 全通过（9/9 run 三字段一致，节内容经前缀法证明未改）；执行计数 20 次恰好 1/9/10；墙钟 4050.8 s；分区三重交集全 0；发现 6 项披露/记录缺陷（F1–F6），无未授权运行
产物：`reports/V-V9-P2/REPORT.md`、`reports/V-V9-P2/metrics.json`
失败与限制：样本效率曲线**无可复算对象**（P1 无任何 S1 指标）；driver.py 缺失无法审计；本会话沙箱禁 `ps`，故未做进程组核验（详见 F3）
交回统筹：需一级裁定 F1/F2 的记录更正方式，并裁定 eval_batches=48 与「eval48 仅身份字段」的口径冲突

## 摘要（≤30 行）

1. **R-6 批准行：通过。** 9 个训练 run 的 `config_snapshot.approval` 行文、行号 776、document SHA 与 #447 逐字一致；`preregistration_sha256` 独立复算等于 `19639d86…0718`；r10 文件 SHA 等于 `5fea3ca7…d1ff`。
2. **批准节唯一性与未改动：通过。** 全文件严格 APPROVED 行仅 1 条（第 776 行）；753 行是明示作废的 ed39c97c 记述、749 行是格式说明，均不匹配 64 位十六进制。节 SHA（731–777）复算 = `a4390f13…6c70`，与 `r6_reference.approval_section_sha256_now` 一致。
3. **日志 SHA 漂移已证伪为「纯末尾追加」。** 运行期出现的 3 个日志 SHA（19e0e450 / b039c67b95 / 66302fc3a5）与 #447 声称的 1c12f855，全部是当前文件的**精确字节前缀**（1116 / 1126 / 1134 / 1139 行）。故批准节在运行前后逐字节未变，不存在事后改写。
4. **作业计数：执行层面通过，提交层面不符字面要求（F1）。** 实际执行恰为 verify 1 + train 9（arm2/3/4 × seed0/1/2 各一次）+ eval 10 = 20 次，20 条 exec 严格串行无重叠。但 jobs-v1 有 **21 条作业记录**：arm2-seed1 被重复提交一次（job-c5d1fd14，09:13:17 提交，09:13:23 以 409「该任务已有 exec」拒绝，未 launch、无 worker、无 RunStore run）。
5. **另有 8 次无记录提交。** `serial_driver.log` 记 09:12:41–42 连发 8 个 submit，relay 侧无 job、无 exec、无 event，属 job 创建前即被拒；执行者未披露。
6. **截止与预算：通过。** 9 次训练墙钟 449.99–450.19 s（冻结 450 s），8 次 DeadlineExceeded + arm4-seed0 BudgetExceeded（run state=stopped/reason=budget_exhausted）；`reserved_optimizer_steps` 与 RunStore `optimizer_steps` 逐次精确相等（2309/2322/2230/2676/2075/2564/2076/1889/1591），均 < 3510。
7. **检查点：与报告一致。** 8 个臂有 0/439/878/1755，arm4-seed2 仅 0/439/878；文件实体存在（arm2 0.83 MB、arm3 0.64 MB、arm4 1.10 MB，与参数量序一致）。同臂三种子 `updates-0` 互不相同，种子未塌缩。
8. **eval 拒绝：fail-closed 已读码确认。** `worker.py:1445` `if registered_batches <= 0 or window_batches > registered_batches:` → 48 < 175（5 检查点 × ceil(550/16)=35），在装载模型前 `return`，`refused_stage=eval_call_budget_exceeded`，exit 3 / worker_exit 2 / ~0.92–0.97 s，且已写 start_gate。非崩溃。
9. **资源门：通过。** 20 次执行中 19 次 `resource_gate.status=passed`（verify 为扁平门无 status 字段）；rss ≤0.05 GiB、MLX 0、系统可用 ≥47.4 GiB、交换区增长 0、磁盘 ≥3134 GiB。第 20 条（被拒重复提交）从未启动，无门记录属正确。
10. **final：通过。** 0 次读取；`artifacts/v9/s1/phase1/final` 与数据集内均无 final 文件；prereg `final: not_generated_not_read`。
11. **分区与泄露：通过。** 数据集 5 文件 SHA 全对；train 2000 / development 200；`episode_id`、`scene_id`、`world_fingerprint` 三重交集均为 0；scene 前缀分别为 `s1-train-*` / `s1-development-*`；packet 分区标注一致；family 500×4 / 50×4。
12. **同预算公平性：配置层面通过，实得步数不等。** 9 个 model run 的 budget 只有 1 种组合（3510/450 s/1 env/0 transition/14400）。但同一墙钟截断导致实得步数 1591–2676，故「同更新预算」经验上未达成；报告已明确不做任何能力比较（`capability_claim: none`），判断正确。
13. **常设对照：原样报告。** arm1 D 候选 9 项身份全 match、C0 指标照报、5 个 S1 指标全 `not_applicable`（incomparable input layout）、M2 附原因与 C0 symbol_nll；`d_candidate_attempts=1/1`。网格样诊断未运行且全文未提及（prereg 定位为诊断，可接受但应显式写「未跑」）。
14. **lost exec：结论成立但证据只覆盖 1/20（F3）。** 首条 exec 的 detail 写明 `supervision confirmed_empty`；其余 19 条由 `serial_run.py:archive_blocking_execs()` 自动写 `after confirmed job end`，该函数**只查作业终态、代码内无进程组空校验**。409 发生在首条 exec 归档前（09:13:17 vs 09:14:46），随后 09:15:38 重提才成功，时间线自洽且如实。
15. **样本效率曲线：本阶段无可复算对象（未验证，非失败）。** arm1 全 N/A、arm2–4 eval 被拒，metrics 无 sample_efficiency 行，train stdout 无 checkpoint 探针行（无 development_nll）。重算必须跑一次 eval，超出本卡「不跑评测」边界。

## 一、复核边界与方法

- 只读：`control.sqlite3` 用 `file:…?mode=ro`；`relay.db` 同样只读；数据集与日志只做哈希/解析。
- 未执行 `relay exec`/`submit-job`；未跑 `s1-phase1` 任何模式；未调用 MLX。
- 本会话沙箱禁止 `ps`（`operation not permitted`），因此**不能**用 killpg/ps 复核进程组空——这一点已如实反映在 F3，而不是用其他证据替代后宣称已核。
- 未验证项：driver.py 的提交行为（文件缺失）；eval 指标数值正确性（无成功 eval）；样本效率曲线可复算性（无数据）。

## 二、R-6 逐项比对（对 #447）

| 比对项 | 要求（#447） | 实测 | 结论 |
|---|---|---|---|
| 批准行原文 | `APPROVED s1-phase1 prereg document_sha256=19639d86…0718` | 9/9 run 逐字相等 | 通过 |
| 行号 | 776 | 9/9 = 776 | 通过 |
| document SHA | `19639d86b8f14ce0873ba367ae8d233fd371495a4c055af2b7344aa50b850718` | 9/9 相等；且独立按 `sha256(canonical_json(doc))` 复算相等 | 通过 |
| 冻结文件 file SHA | `5fea3ca7…d1ff` | 实测相等 | 通过 |
| 节内唯一批准行 | 只有一条 | 严格正则命中 1 条（776）；753/749 为作废记述与格式说明 | 通过 |
| 节内容 SHA | `a4390f13…6c70` | 复算相等（731–777，逐行 rstrip("\n") 后 `\n` 连接） | 通过 |
| 日志 SHA | #448 称写入后 `1c12f855…e22c` | 运行期记录为 19e0e450（run1–2）、b039c67b95（run3）、66302fc3a5（run4–9） | **不等，但已证明无害（见 §2.1、F2）** |

### 2.1 日志 SHA 漂移的前缀证明

对当前 `RESEARCH_LOG.md`（1166 行，SHA `c30075d5…91f4`）逐行做前缀哈希，命中：

| 记录值 | 来源 | 命中行数 |
|---|---|---|
| `1c12f855…e22c` | #447「写入后」 | 1116 |
| `19e0e450…72e2` | arm2-seed0/1、verify | 1126 |
| `b039c67b95…a6f0` | arm2-seed2 | 1134 |
| `66302fc3a5…6884` | arm3×3、arm4×3 | 1139 |
| `c30075d5…91f4` | 当前 | 1166 |

四个历史值都是当前文件的**精确字节前缀**，说明窗口内所有改动都发生在第 1116 行之后（文件末尾追加轮次记录），第 731–777 行批准节在所有版本中逐字节相同。这是比「整体 SHA 相等」更强的证据，也解释了 #448 要求「日志 SHA 一致」在设计上不可满足。

## 三、作业清单（jobs-v1 × RunStore × exec）

| 类别 | 作业记录 | 实际执行 | exec 记录 |
|---|---|---|---|
| verify | 1（job-d1ed6a05） | 1，rc 0 | 1 |
| train | **10**（含 1 条被拒重复） | 9 | 9 |
| eval | 10 | 10（arm1 rc 0；9 条 rc 3 refused） | 10 |
| 合计 | **21** | **20** | **20**（另有 10-21 遗留 1 条，非本轮） |

- 串行性：20 条 exec 的 `[started_at, ended_at]` 两两不重叠；09:02:56 起、10:20:09 止，墙钟 4633 s。
- 重复项：`job-c5d1fd14`（arm2-seed1，idem 无后缀）submitted 09:13:17 → failed 09:13:23，reason `ApiError('409 该任务已有 exec；不能并行启动或静默接管')`，无 `launch_intent`/`running` 事件、无 attempt `launch.json`、无 RunStore run。随后 `job-21f1d058`（idem `…-a`）09:15:38 才真正开跑。
- 无记录提交：`serial_driver.log` 09:12:41–42 连发 arm2s1/arm2s2/arm3s0-2/arm4s0-2 共 8 条，relay `events` 与 `task_execs` 在该时段均为空 → 提交在 job 创建前即被拒。
- 种子未换：每臂 3 个种子各 1 次；同臂三种子 `updates-0.npz` SHA 互异。

## 四、预算与资源

- 单次：`max_wall_seconds=450`、`max_optimizer_steps=3510`、`max_environment_steps=1`、`max_model_transitions=0`、`max_daily_active_seconds=14400`；9 个 run 仅 1 种组合。
- 实测：墙钟 4050.8 s（训练）+ ~9 s（eval）+ 0.33 s（verify）≈ 4060 s ≪ 14400 s；占空比 0.25 由 `RuntimeGuard` 记录。
- 资源门：rss ≤0.05 GiB（限 8）、MLX active 0（限 4）、系统可用 ≥47.4 GiB（余量线 16）、swap 增长 0（限 1）、磁盘 ≥3134 GiB（限 50）。

## 五、发现（按严重度）

**F1（披露缺陷，中）**：jobs-v1 有 21 条作业记录，P1 报告与 `run_ledger.json` 只记 20 条（train 9）。被拒的 arm2-seed1 重复提交、以及 09:12:41 的 8 次无记录提交均未披露。执行层面无重跑（同一 arm×seed 未被执行两次），但「不得有重复提交」按字面未满足，应补记为「1 次重复提交被 409 fail-closed 拒绝，0 次重跑」。

**F2（记录不一致，中）**：#447 于 08:56:42 发出，正文却称「一级已在 09:1x 用只读 verify 核对」；放行核定节头也写「2026-10-23 09:1x」。但执行者 verify 的 exec 始于 09:02:56，且其记录的日志 SHA（19e0e450 = 1126 行前缀）已包含 757–775 行放行核定块。故该块在 09:02:56 前即已存在，「09:1x」为前向/不精确标注。**不构成未授权运行**（批准行在全部 run 之前存在，见 §2.1），但记录应更正为实际时刻。

**F3（证据覆盖不足，中）**：`serial_run.py:61-88 archive_blocking_execs()` 对 `state NOT IN (finished, stopped, launch_failed, abandoned_unknown)` 的 exec 直接 POST finish，detail 固定写 `archive <state>→finished after confirmed job end`。该函数**只读作业终态，不做进程组空校验**；docstring 所称「组空后归档」在代码里没有对应实现。20 条 exec 中仅首条（f3e0）有 `supervision confirmed_empty` 的人工记录，其余 19 条只有作业级证据。结论「lost exec 手动 finish 发生在组空之后」仅对 1/20 有直接证据；本会话禁 `ps`，无法补验。

**F4（验收项在本阶段为空，低）**：「样本效率曲线可复算」无可复算对象——无任何 S1 指标产出。前提条件（检查点、冻结 checkpoint_updates、确定性探针代码）具备，但重算需一次 eval，本卡禁止。

**F5（产物降级，中）**：`run_ledger.json` 的 `trains[1..8]` 为残桩（`run_id`/`wall_s` 为 null、`reason="return code 1"`），仅 `trains[0]` 完整；报告却把该文件列为产物。完整逐 run 证据在 `metrics.json`（9/9 有 run_id、reserved 与实耗相等），应以 metrics.json 为准并标注 ledger 降级原因。

**F6（不可审计，低）**：卡面提到的 `driver.py` 在仓库内不存在（仅 `driver.log`/`driver.err`/`driver.pid`），其提交行为无法审计；`driver.log` 只有两行租约信息，与报告「后台驱动曾被会话回收」一致。

## 六、报告越界检查

- `REPORT.md`：明确「不宣称能力晋升」「无能力结论」「9/9 未跑完 3510 步」；未做任何臂间优劣比较。
- `metrics.capability_claim = "none — 不宣称能力晋升；9/9 训练未完成 3510 步"`。
- `metrics.interpretation_bound` 如实写明 held-out=时间续段（非空间未见 cell）、checkpoint0=未训练基线、M2 选点=字典序前 5（既非随机也非分层）、eval48=身份字段。
- 与放行核定 B4–B7 口径一致，未见越界结论。

## 七、交回统筹（需裁定，不自行处置）

1. **F1/F5**：要求执行者补记 21 条提交、1 次 409 拒绝、8 次无记录提交，并修正 run_ledger 或声明以 metrics.json 为准。
2. **F2**：请一级把 #447 正文与放行核定节头的「09:1x」更正为实际时刻，并把 R-6 的日志 SHA 判据改为「节内容 SHA + 前缀单调追加」，否则该条永远不可能通过。
3. **eval_batches=48 口径**：放行核定称 eval48「只作身份字段」，而 `worker.py:1445` 把它当硬上限，导致 9 次 eval 全拒。二者需一级统一；在此之前 arm2–4 无任何指标。
4. **F3**：若要「组空」成为可核事实，`archive_blocking_execs()` 需在 finish 前做 killpg(0)/ESRCH 核验并把结果写进 detail；现版本不应被引用为组空证据。
5. 本复核**不构成**对 P1 的 accept；P1 的实验状态仍为 failed，且不存在能力结论。
