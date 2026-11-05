# ainerzero.V9.P37 执行报告
角色：executor（非作者独立审计）；负责人：geminiflash-9a7c；时间：2026-10-24 22:15 +0300
任务状态：reported；实验状态：completed（审计本身完成；S1 r12 阶段维持 partial completed / 阶段墙钟耗尽停手，P36 recovery.pending 维持红态）
任务依据：ainerzero.V9.P37 参数 v0；统筹授权无运行授权（run_authorized=false, model_work=false, readonly_production=true）；只读核验 S1 r12 的 P32/P36 实际完成与阶段墙钟封存。
输入身份：
- prereg 文件 SHA：`fe539209179e3c59405526880dc1ea8dffe5416d34e393cd86b5f0373ece9658`（`artifacts/v9/s1/phase1/r12/pre_registration.json`）
- 批准 document SHA：`044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd`（`RESEARCH_LOG.md` 批准行）
- verify-copy-p36.json SHA：`2e7476795dba57e8254bb8b877a1aed3ca040f8707d6db652583de8516e9cc17`
- 生产台账当前 SHA：`6b604983b5d1c944bdfe814fd0d72cb7b768c8b8a23f422607f946ce341b3f44`（WAL 0 字节）
修改文件：仅限定范围 `reports/V9-S1-r12/P37-audit/`：
- `reports/V9-S1-r12/P37-audit/audit_script.py`（自动化核验与负对照测试脚本）
- `reports/V9-S1-r12/P37-audit/audit_metrics.json`（机读审计台账与负对照证据）
- `reports/V9-S1-r12/P37-audit/P37-AUDIT-REPORT.md`（本报告）
实际执行：
- 命令行：`python3 reports/V9-S1-r12/P37-audit/audit_script.py`
- 非作者排除执行者验证：本审计 agent（geminiflash-9a7c）未参与 P32/P36 任何阶段，严格排除 `deepseekv41f-h3t8`、`composer-x7k2`、`claude`、`codex`。
- 零运行、零 MLX、零生产 RunStore 写入：未调用任何训练/评测入口，未触碰锁文件 `m0-worker.lock`，未修改源码。

---

## 一、作业台账核验（5 个真实作业与 3 个网关拦截作业）

通过 `relay job-status` 与底层 runner `state.json` 逐一提取证据：

### 1. 5 个真实执行作业（全部组空确认）
| 标签 | Job ID | 任务卡 | 提交者 | 状态 | RC | Worker Exit | 检查点数 | 产物与步数 | 组空状态 (confirmed_empty) |
|---|---|---|---|---|---|---|---|---|---|
| arm2-s0 | `job-07e97f23098846538ced49a01a0b4519` | P32 | deepseekv41f-h3t8 | completed | 0 | 0 | 4 (0,439,878,1755) | 3510 updates, params.npz, completion.json | true (members_left=[]) |
| arm2-s1 | `job-796cf5cd72b84d46a96e62f0d6d8778c` | P32 | deepseekv41f-h3t8 | completed | 0 | 0 | 4 (0,439,878,1755) | 3510 updates, params.npz, completion.json | true (members_left=[]) |
| arm2-s2 | `job-60ff8abd76574c9c8bcdc020011fb575` | P32 | deepseekv41f-h3t8 | failed | 1 | 3 | 4 (0,439,878,1755) | 2556/3510 updates, budget_exhausted 1209.95s | true (members_left=[]) |
| arm3-s0 | `job-e03bcde3c47c4430982c3d095a0b1db5` | P36 | deepseekv41f-h3t8 | completed | 0 | 0 | 4 (0,439,878,1755) | 3510 updates, params.npz, completion.json | true (members_left=[]) |
| arm3-s1 | `job-a6b2004b9ef7457881bfff18d58b348c` | P36 | deepseekv41f-h3t8 | failed | 1 | 3 | 3 (0,439,878) | 1341/3510 updates, budget_exhausted 1609.75s | true (members_left=[]) |

**核心实测结论**：
1. `arm3-s1`（`job-a6b2004b9ef7457881bfff18d58b348c`）：状态确为 `failed`，`returncode=1`，`worker_exit_code=3`，`supervision.confirmed_empty=true`，`supervision.members_left=[]`，`group_empty=true`，租约状态 `lease_released=true`。其对应 exec 为 `0ff85252eeb04015b6ad6d2bba915d3a`，state 保持 `lost`。
2. 5 个作业全部完成进程组退出，无任何残留孤儿进程。

### 2. 3 个一级托管阶段网关拦截作业（claude 提交）
- `job-9677f3a17bb24d9d866f4535cae4a86f`（arm3-s0）：409 拒绝，`launch_intent=false`，`exec_finished=false`，`group_empty=true`。
- `job-808e7b7436e640379adc28383e608aea`（arm3-s1）：409 拒绝，`launch_intent=false`，`exec_finished=false`，`group_empty=true`。
- `job-9a3f27024dce4902817295c7c01d0077`（arm3-s2）：409 拒绝，`launch_intent=false`，`exec_finished=false`，`group_empty=true`。
- 原因：P32 当时因原持有者失租进入回收等待，Relay 网关严格 fail-closed 拦截，未产生任何实际计算与台账写入。

---

## 二、只读 Run 产物与检查点核验

在 `artifacts/v9/s1/phase1/runs/` 下对 5 个对应 run 进行纯只读审计：
1. **成功 run**：
   - `6632a9f050254774ba361d996c1c47d6`（arm2-s0）：完整存在 `completion.json` 与 `params.npz`（833,782 字节），完成 3510 updates，终态 loss 0.019298。
   - `ba45a3aa2b1d4d79a36134c8985828bc`（arm2-s1）：完整存在 `completion.json` 与 `params.npz`（833,782 字节），完成 3510 updates，终态 loss 0.000484。
   - `ba42ba65374244e6b1ce2d50df85f28f`（arm3-s0）：完整存在 `completion.json` 与 `params.npz`（641,526 字节），完成 3510 updates，终态 loss 0.000793。
2. **失败 run**：
   - `69dae83ad5874a7d85b4102a20f5f256`（arm2-s2）：无 `completion.json`，无 `params.npz`。保留 4 个 checkpoint（updates-0, 439, 878, 1755）；因单次墙钟 1209.95s 超标在 2556 步中断。
   - `01561a1059f14b89accde30d12c69278`（arm3-s1）：无 `completion.json`，无 `params.npz`。仅保留 3 个 checkpoint（updates-0, 439, 878，未达 1755）；因单次墙钟 1609.75s 超标在 1341 步中断。

---

## 三、阶段墙钟与 composer-x7k2 零新作业证明

1. **阶段窗口核定**：
   - r12 阶段窗口起始：`2026-10-24T08:50:00+03:00`
   - 上限预算：`max_s = 14400`（4 小时）
   - 窗口合法关闭时刻：`2026-10-24T12:50:00+03:00`
   - composer-x7k2 领取 P36 时刻：`2026-10-24T21:03:16+03:00`
   - 超时量：超出关闭时间约 `29620` 秒（约 8.2 小时）。
   - 处置判定：**阶段墙钟已关闭，按冻结规则坚决停手，禁止开启任何新作业**。
2. **composer-x7k2 零作业证明**：
   - 检索 `AinerRelay/data/runs/jobs-v1/**/job.json` 全量文件，匹配 `composer-x7k2` 提交者计数结果为 **0**。
   - P36 下唯一存在的两个作业均为前任 `deepseekv41f-h3t8` 提交。证明 composer-x7k2 领卡后未发起任何计算作业。

---

## 四、未执行集合、失败不重跑与解读边界

1. **失败不重跑**：
   - `arm2-s2` 与 `arm3-s1` 均属环境超窗失败；依据 S1 r12 协议与用户裁决，**严禁在本阶段窗口内重跑**。
2. **未执行集合**：
   - 训练未执行：`arm3-s2`、`arm4-s0`、`arm4-s1`、`arm4-s2`（共 4 项训练完全未提交）。
   - 评测全部未执行：`eval-arm1`（D 复验）、`eval-arm2`、`eval-arm3`、`eval-arm4`（全部 4 项开发评测完全未提交）。
3. **解读边界与无能力宣称**：
   - held-out 为时间续段；checkpoint 0 为未训练基线；M2 选点为字典序前 5；k=8 记为 `insufficient_data`。
   - final 分区严格未触碰。
   - S1 r12 整体实验状态为 **failed（部分完成 / 阶段耗尽停手）**，**不构成任何模型能力结论**。

---

## 五、P36 状态核验：回收阻塞与证据解耦

1. **P36 仍为 recovery.pending**：
   - 前任执行者 `deepseekv41f-h3t8` 的 exec `0ff85252eeb04015b6ad6d2bba915d3a` 处于 `lost` 状态。
   - Relay 机制要求仅原 exec 持有者可将其归档为 `finished/stopped`；换由 composer-x7k2 持有后，两者 ID 不匹配，导致 `_finish_recovery` 无法自清。
   - composer-x7k2 报告时遭 409 拦截，释放时 CLI 返回成功但实为 no-op。
2. **解耦原则**：
   - **基础设施通信通道 409 回收阻塞** 与 **作业科学证据已物理落盘且组空** 严格分开。
   - 明确判定：**P36 当前不能标记为 accepted 或 complete；本卡（P37）的通过仅代表审计完成，绝不代表 P36 验收通过或获得续跑授权**。

---

## 六、封存文件 SHA 与 18 秒时钟漂移注记

1. **完全匹配项**：
   - `artifacts/v9/s1/phase1/r12/pre_registration.json` SHA256：`fe539209179e3c59405526880dc1ea8dffe5416d34e393cd86b5f0373ece9658`（完全一致）
   - `reports/V9-S1-r12/verify-copy-p36.json` SHA256：`2e7476795dba57e8254bb8b877a1aed3ca040f8707d6db652583de8516e9cc17`（完全一致）
   - 批准行 document SHA256：`044d5599ecd7c88600257488866462f666eebde25454ad4e4494f355ccd418dd`（完全一致）
2. **18 秒时钟漂移核定（非作者复核特别发现）**：
   - Codex 于 `21:08:03 +03:00` 创建 P37 任务卡并登记了当时磁盘上的 `P36-REPORT.md`（771e4340…）、`P36-metrics.json`（4f1a39ec…）、`PROGRESS.md`（dff82132…）。
   - 随后在 `21:08:21 +03:00`（相隔 18 秒），composer-x7k2 收到 codex 裁决 #516 后尝试执行 release，并将 release 失败细节与 #516 注记追加到这三个文件中。
   - 经逐行对比，追加内容纯属协作事件与 409 状态记录，底层所有 5 个作业指标、完成状态、步数及物理产物没有任何变动。

---

## 七、不利反控（Adversarial Negative Controls）实测

在 `audit_script.py` 中构建对抗变异注入，验证断言防线：
1. **测试 1（未提交项错算完成）**：将未提交的 `arm3-s2` 设为 `completed` → **变红，AssertionError 拦截成功**。
2. **测试 2（失败项错算完成）**：将超窗失败的 `arm2-s2` 设为 `completed` → **变红，AssertionError 拦截成功**。
3. **测试 3（非法授权重跑）**：对失败项 `arm3-s1` 标记 `rerun_authorized=true` → **变红，AssertionError 拦截成功**。
4. **测试 4（虚构阶段窗口）**：将领取时刻判定为窗口未关闭（`is_closed_at_claim=false`） → **变红，AssertionError 拦截成功**。
5. **测试 5（虚报 P36 状态）**：将 P36 recovery 标记为已解决（`p36_recovery_resolved=true`） → **变红，AssertionError 拦截成功**。
- **真实基线**：在真实盘点数据下，所有规则断言顺利通过（GREEN）。

---

## 产物与交付清单
1. 审计脚本：`reports/V9-S1-r12/P37-audit/audit_script.py`
2. 审计指标：`reports/V9-S1-r12/P37-audit/audit_metrics.json`
3. 审计报告：`reports/V9-S1-r12/P37-audit/P37-AUDIT-REPORT.md`

## 交回统筹
- P32/P36 盘点完成，S1 r12 阶段窗口已合法封存。
- 确认全流程零新计算、零重跑、零能力宣称。
- P36 的 Relay 回收锁（409）属调度系统已知限制，留待一级统筹在基础设施层处理。
