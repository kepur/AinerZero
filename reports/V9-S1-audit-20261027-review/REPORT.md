# ainerzero.V9.P46 执行报告

角色：executor（非作者复核）；负责人：composer-k7m2；时间：2026-10-27  
任务状态：reported；实验状态：未执行（零运行复核）  
任务依据：ainerzero.V9.P46；前置 ainerzero.V9.P45（accepted，作者 antigravity-66bc）；参数 v0 `{}`  
输入身份：只读 `artifacts/v9/s1/phase1/control.sqlite3`（`file:…?mode=ro` + `shasum`）；RunStore `experiments`/`runs`/`run_transitions`；`artifacts/v9/s1/phase1/runs/*` 产物 SHA  
修改文件：仅 `reports/V9-S1-audit-20261027-review/`（本目录）  
实际执行：无 train/eval/verify/submit-job/exec；无模型加载；未写生产 `artifacts/v9/s1/phase1/`  
验证结果：见下文；指标见同目录 `metrics.json`  
产物：本报告、`metrics.json`  
失败与限制：P45 两处「可续 checkpoint」SHA 串标（见 §4）；不构成假成功，但足以拒绝整卡照单签收  
交回统筹：建议 **reject** P45 证据身份细节后开补正（或由后续卡订正 SHA），主建议仍采纳 **new_r14**；是否开 r14/新预算仍须用户批准

---

## 摘要（≤30 行）

1. **独立性**：本 agent `composer-k7m2` ≠ P45 作者 `antigravity-66bc`；上一棒 antigravity-r8ia 因非独立已释放，本卡从零独立重算。
2. **台账三方 SHA**：自算 `fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`，与一级基准及 P45 报值 **全等**（`sha_three_way_match=true`）。`control.sqlite3` mtime 仍为 2026-10-25 15:46:42；`-wal` 0 字节。
3. **抽样 9 条**（成功 3 / 失败·停止 3 / 未启动 3，均 ≥2）：终态、run_id、optimizer_steps、证据路径与 P45 表 **一致**；未发现「标 completed 却无合理 params」的假成功（全量 completed 扫过 7/7 均有 ≥641526B 的 `params.npz` + 正常 `training→completed` 转移）。
4. **关键分歧（拒绝理由）**：
   - r13 arm3 seed1：P45 写 `last_checkpoint=updates-1755.npz` 且 SHA=`8f9afba5…`；自算该文件 SHA=`1ee093a9…`。`8f9afba5…` 实际是同目录 **updates-878.npz**。
   - r12 arm2 seed2：P45 写 `last_checkpoint=updates-1755.npz` 且 SHA=`660f8353…`；自算 1755=`74ac2dce…`。`660f8353…` 实际是 **updates-878.npz**。
   - 一级已指出：arm2 seed2 **无**跨轮 params 全等（r12 无 `params.npz`，仅 r13 完成）；P45 把其与 s0/s1 一并说成跨轮可继承强度，过冲。本复核确认该修正。
5. **14400s 窗口**：自读 r13 `created_at=1792928546.279864`（2026-10-25 14:42:26），到期 `1792942946.279864`（18:42:26）；r12 同步过期。**own_window_verdict=expired_block_valid**——codex 10-25 阻塞续跑理由成立；resume_r12 / resume_r13 均不可行。
6. **建议**：同意 P45 的三选一结论 **new_r14**（`agrees_with_p45_recommendation=true`）；但因可续 ckpt 身份 SHA 串标 + arm2s2 继承表述过冲，对 P45 卡本身 **recommendation=reject**（须订正后再当 r14 预登记输入）。
7. **零运行**：P45 报告时段（约 01:33–01:37）生产目录无写入（排除只读打开产生的 `-shm`）；最新 run 产物 mtime 停在 2026-10-25 15:44。`p45_zero_run_respected=true`。

---

## 1. 台账三方比对

| 来源 | SHA256 |
|---|---|
| 一级基准 | `fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60` |
| P45 报告 | 同上 |
| 本卡自算 `shasum -a 256` | 同上 |

影响：台账身份可信；P45 此项通过。

---

## 2. 抽样重算（≥6；本卡 9）

| 抽样 | P45 终态 | 自核 RunStore | 证据 | 一致？ |
|---|---|---|---|---|
| r13 arm2 s0 `19f2d1eb…` | completed 3510 | completed 3510 | params 833782B SHA `9d155fbf…`；completion SHA `937ef0d4…`；转移正常 completed | 是 |
| r13 arm2 s2 `1678cc1c…` | completed 3510 | completed 3510 | params 833782B SHA `f7f9a661…`；completion 存在 | 是 |
| r13 arm3 s0 `403ae816…` | completed 3510 | completed 3510 | params 641526B SHA `577429aa…` | 是 |
| r13 arm3 s1 `92b694d3…` | failed resource_gate 2566 | failed / reason 前缀 `resource_gate_refused` / 2566 | 有 updates-1755.npz（641526B），**但 P45 所报 SHA 错** | 终态是；SHA 否 |
| r12 arm2 s2 `69dae83a…` | stopped budget_exhausted 2556 | 同 | 无 params；有 1755 ckpt，**P45 SHA 错（实为 878）** | 终态是；SHA 否 |
| r12 arm3 s1 `01561a10…` | stopped 1341 / ckpt 878 | 同 | updates-878 SHA `8f9afba5…` 与 P45 **一致** | 是 |
| r13 arm3 s2 | not_started | 无 run 行 | — | 是 |
| r13 arm4 s0 | not_started | 无 run 行 | — | 是 |
| r12 arm4 s1 | not_started | 无 run 行 | — | 是 |

扩大抽样：因 SHA 分歧，已扫全部 r12/r13 completed（7 条）假成功，并核 r13 arm2 s1 / r12 arm2 s0/s1 的跨轮 params 全等（s0/s1/arm3s0 全等属实；arm2s2 仅 r13 有 params）。

---

## 3. 假成功专查

- 全部 `state=completed` 的 r12/r13 run：均存在合理大小 `params.npz`，且 `run_transitions` 为 `training→completed`（reason 前缀 `s1_train_completed`），未见 killed/半截冒充完成。
- `fake_success_found=false`。

---

## 4. Checkpoint SHA 串标（拒绝主因）

| 条目 | P45 声称 | 自算 |
|---|---|---|
| r13 arm3s1 `updates-1755.npz` | `8f9afba557365397ede1a354458e0ac3d2976f319a6e9c65ff853d3cafdeec73` | `1ee093a94517bf7dacee1bfcd9fb5d6b156c5330e602c210d87e99a854a24f4d` |
| 同目录 `updates-878.npz` | （未单独报为 last） | `8f9afba5…`（=P45 误贴到 1755 的值） |
| r12 arm2s2 `updates-1755.npz` | `660f83539c9b95cfd9447a202399383a090677910f57ad6b5bdd1f9e963ad024` | `74ac2dce7cd2cb2af981169625f0d66837a50d83ad59462bdf75be9d9d00b4d3` |
| 同目录 `updates-878.npz` | — | `660f8353…`（=P45 误贴到 1755 的值） |

模式：把 **878** 的哈希写进 **1755** 的 `last_checkpoint_sha256`。文件确实存在且大小合理，故不是「假成功」，但若 r14 按错误哈希绑定续训身份会失败或绑错步。`entries_disagreeing` 列此两条。

跨轮继承：arm2 s0/s1、arm3 s0 的 params SHA 跨 r12/r13 全等（自算确认）。arm2 s2 **仅 r13 完成**，不得与前三者同档「跨轮复现继承」。

---

## 5. 14400s 窗口（独立）

- `own_r13_created_at`：`1792928546.279864`（2026-10-25T14:42:26.279864 本地）
- 到期：`created_at + 14400 = 1792942946.279864`（2026-10-25T18:42:26）
- r12：`1792821031.316144` → 到期 12:50:31 同日
- **own_window_verdict**：`expired_block_valid`（续跑 r12/r13 会被硬窗口拒绝；codex 理由成立）

---

## 6. 对 P45 三选一的独立表态

| 选项 | 本卡 |
|---|---|
| resume_r12 | 否（窗口过期；且 r13 已推进更远） |
| resume_r13 | 否（窗口过期；改窗/改戳违纪） |
| new_r14 | **是**（唯一合规路径） |

`agrees_with_p45_recommendation=true`；`own_recommendation=new_r14`。  
补充：r14 预登记应 (1) 用本卡订正后的 1755 SHA 绑定 arm3s1 续点；(2) arm2s2 单列「仅 r13 单次完成」，或补复现后再按跨轮强度继承；(3) 未完成部分（arm3s1 续/重跑、arm3s2、arm4×3、arm1 eval）另要用户预算——本卡不构成放行。

未为省事倾向「全部作废重开」：已完成且哈希互证的臂应继承；也未硬说能在 r12/r13 续。

---

## 7. P45 零运行核查

- 生产 `control.sqlite3` mtime 未在 P45 时段变化；P45 窗口内 walk 生产树（排除 `-shm`）**无文件 touch**。
- 最新 run 内文件 mtime ≤ 2026-10-25 15:44。
- 本卡只读打开会刷新 `-shm`（2026-10-27），不计入 P45 写入。
- `p45_zero_run_respected=true`。

---

## 8. 验收对照与结论

| 验收项 | 结果 |
|---|---|
| 三方台账 SHA | 通过 |
| ≥6 条独立重算（成/败/未启各≥2） | 通过（9 条） |
| 假成功专查 | 未发现 |
| 自算 r13 窗口 | 通过；阻塞成立 |
| 三选一独立表态 | new_r14（同意 P45） |
| 零运行核实 | 通过 |
| **recommendation** | **reject**（ckpt SHA 串标 + arm2s2 继承过冲须订正） |

上一棒：无半成品（`reports/V9-S1-audit-20261027-review/` 原不存在）；本卡新建。
