# ainerzero.V9.P20 非作者复核报告：P18 r2 的预算数值、来源标签与冻结指标边界

角色：executor（二级执行层，非 P18 作者）；本棒 ID：`workbuddy-q7t2`（DeepSeek V4.1 Flash，skills=text/code/math/longrun）；日期：2026-10-22（客户端）
任务状态：reported；实验状态：**未执行**（纯 CPU 只读复核、独立复算与隔离复现；无训练、无真实 eval、无 MLX 导入、无新数据）
复核对象：`ainerzero.V9.P18` r2（作者 `deepseek-v41f-p8k2`；`reports/V9-P18/r2/`，报告 sha `86a13488…bd7c`，metrics sha `ad32d483…b36a`）
复核依据：`reports/V9-P19/REPORT.md`（sha `f27b401b…7334`）的 F1–F9；`P18-r2-review-inputs.json`（38 项封存输入）；`P18-frozen-review-inputs.json`（r1 14 项冻结输入）；冻结 r5 快照与冻结 development truth
文件范围：只写 `reports/V9-P20/`；本棒产物全部放在 `reports/V9-P20/workbuddy-q7t2/`。原 r1/r2 报告、源码、数据、冻结快照全部只读，零覆盖。

---

## 0. 摘要（给一级取舍）

**结论：r2 的数值骨架可复算、脚本可隔离复现；但“F1–F9 全闭”不成立。** 发现 **5 项必须修订**（D1–D5）和 **5 项轻微问题**（M1–M5）。其中 D2（F9 的“冻结后被改写”）、D3（B2 未绑定数据摘要）、D4（300 s 硬墙钟）直接落在本卡要求的“预算数值、来源标签、冻结指标边界”上。**不建议按当前 r2 直接进入用户批准流程；建议先做文字/来源修订（无需新实验）再复核。**

**通过的部分（已独立核对）**

- **38 项封存输入 SHA 审前/审后全部一致**；**r1 的 14 项冻结输入审前/审后全部一致**（r2 没有覆盖 r1 证据）。
- r2 的两个分析脚本在**独立输出目录**复跑，`independent_truth_check.json` 与 `metrics.json` **字节级一致**（SHA 分别 `b8f55a8b…afea`、`ad32d483…b36a`）；`input_identity.json` 也字节一致。
- 预算重算全部与冻结值一致：`updates=3510`、`estimate=359.9312287726061`、`deadline=450`、`arm1=1.501679232227616`（deadline 2）、`phase_wall=4099.605202459`、`headroom=10300.394797541`。
- k 覆盖独立复算与 P19/r2 逐项相等：k=0/1/2/4/8 → **200/200/150/50/0** 世界，**750/550/350/100/0** query；family 1:1 绑定（nav 7、e3 5、time 4、relation 3 步）。
- 组件算式与 P19 实测相等：**611 / 1,492 / 800 / 3,500 / 175**；帧自洽量 **1003 / 2103 / 1492** 正确。
- 未导入 MLX；未跑 train/eval/smoke/data；未读 final；未下载/安装；未写批准行；未改参数/预算/种子。

**必须修订（按严重度）**

| # | 严重度 | 问题 | 位置 |
| --- | --- | --- | --- |
| D1 | 中 | F1 数值对，但**历史被部分抹掉/错归属**：r1 `metrics.json:447` 与 `build_metrics.py:197` 也含 `1292`，r2 却说“r1 metrics.json 本身是 611/1492/800”“错只发生在 REPORT 正文与其 unmeasured 文案” | r2 `REPORT.md:13,125`；r2 `metrics.json → call_counts…r1_registration_values_superseded.note` |
| D2 | 中高 | F9 断言“清单字段在预注册冻结后被改写”，**无历史 diff 支撑，且与当前清单字节矛盾**：当前 `generation_seconds=45.739918708`（= `data_identity`），清单 mtime 12:57 早于 prereg 23:32；47.605 是 11:49 smoke 记录 | r2 `REPORT.md:21`；r2 `metrics.json → data_cost.frozen_document_inconsistency`、`f_closures[8]` |
| D3 | 高 | **B2 的 611/1492/800/3500/175 未绑定 dataset digest**；B1 的新长 episode 数据（200 世界 × ≥10 packet、每世界 ≥9 transition）会改变这些计数，不能直接沿用 | r2 `REPORT.md:269–270`；r2 `metrics.json → option_B.items[B1,B2]` |
| D4 | 高 | **300 s 不是“硬墙钟”**：300 是 `PREP_BUDGET["eval"]` 标称预算；实际 supervisor 超时是 `300+50=350 s`；账本只预留/记账 `120 s`；eval 分支不复查 phase cap。r2 多处称“子进程硬超时 300 s”“每次 300 s 硬约束” | r2 `REPORT.md:15,181,202,204,272`；r2 `metrics.json → phase.eval_wall_nominal…`、`unmeasured[3]` |
| D5 | 中 | F7 声称“不再手写 M2 的 11/42”，但 `build_r2_metrics.py` 仍**字面硬编码** 11/42（并写 `not_hand_typed_in_r2: true`）；值正确，出处声明为假 | r2 `REPORT.md:19`；`build_r2_metrics.py:258,262,329,330`；r2 `metrics.json → call_counts.m2_constants` |

**对 2026-10-22 上午四条审查要求的直接回答**

| 要求 | P20 结论 |
| --- | --- |
| ① r1 metrics 未错但 P19 指出 build 脚本/metrics 文案亦有 1292，不能抹历史 | **未满足**：D1。r2 只保留了 612/1292/600 的“superseded”数值，未记录 `metrics.json:447` 与 `build_metrics.py:197` 这两个出处，且把错误归到 REPORT 正文。 |
| ② generation_seconds 两字段不一致只是当前字节事实，不能无历史 diff 就断言“冻结后被改写” | **未满足**：D2。r2 复述并强化了 P19 的“冻结后被改写”；当前清单值是 45.7399，且清单创建早于 prereg，不能支持该断言。 |
| ③ B1 新长 episode 的调用量不可直接沿旧短 episode 611/1492，各选项与计数必须绑定数据摘要 | **未满足**：D3。B2 没有 `dataset_digest` 绑定；B1 的新数据会改变 611/1492/800/3500/175。 |
| ④ 单次 eval 300 标称/350 监督/实际 stage 账本不同，不能称 300 绝对硬墙；4 h 已含 eval，不扩大登记 | **部分满足**：“4 h 已含 eval”正确；但 **300 硬墙钟错误**（D4）。350 监督、120 账本预留未写；静态余量用 350 仍为 7249.605 s < 14400 s，结论不变，但数字/标签必须改。 |

---

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# 领取 / 心跳
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent workbuddy-q7t2 --tier 2 \
  --kind deepseek-v4.1-flash --profile-file profile.json
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.P20 \
  --agent workbuddy-q7t2 --token 6971b51ed720b590cd2480a60da3bb2700c5
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay heartbeat ainerzero.V9.P20 \
  --agent workbuddy-q7t2 --msg "…"

# 独立复核：38 项封存 SHA + 14 项 r1 冻结 SHA、k 覆盖复算、预算复算、源码常量核对
/Users/mac/.workbuddy-ai/binaries/python/versions/3.13.12/bin/python3 \
  reports/V9-P20/workbuddy-q7t2/analysis/verify_p18r2.py \
  > reports/V9-P20/workbuddy-q7t2/logs/verify_p18r2.out \
  2> reports/V9-P20/workbuddy-q7t2/logs/verify_p18r2.err

# 隔离复现 r2 两个脚本（原脚本只读；build 的 OUT 在内存中重绑，不改原文件）
/Users/mac/.workbuddy-ai/binaries/python/versions/3.13.12/bin/python3 \
  reports/V9-P20/workbuddy-q7t2/analysis/repro_p18r2.py \
  > reports/V9-P20/workbuddy-q7t2/logs/repro_p18r2.out \
  2> reports/V9-P20/workbuddy-q7t2/logs/repro_p18r2.err
```

- 两个脚本 RC=0，stderr 均 **0 字节**。
- **没有**运行：`--mode train/eval/smoke/data`、任何 MLX 前向/梯度/优化器、final 分区读取、数据生成、模型下载/安装、资源基线重设、git commit/push、批准行写入、RESEARCH_LOG 改写。
- 没有原地复跑 P18/P19 套件；没有覆盖 r1/r2 任何报告/指标/日志。所有输出在 `reports/V9-P20/workbuddy-q7t2/`。
- **并发观察**：`reports/V9-P20/analysis/p20_independent_check.{py,json}`、`reports/V9-P20/analysis/test_write.txt`、`reports/V9-P20/analysis/iso/` 不是本棒产物（本棒未创建/未使用/未删除）；按一级 09:16 留言，本棒只在独立子目录产出。上一棒残留报告不作为本棒独立证据。

## 2. 输入与身份

| 项 | 值 / 结果 |
| --- | --- |
| 38 项封存输入 | 审前 **38/38 一致**；审后再次核对 **38/38 一致** |
| r1 14 项冻结输入 | 审前/审后 **14/14 一致**（r2 未覆盖 r1） |
| 冻结 r5 快照根 | `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot` |
| `evaluation.py` | `92d8de4a…72aa3`（与 r2 `identity.source_sha256` 一致） |
| `runtime.py` | `a9934652…06c7` |
| `metrics.py` | `e1c36b65…643e1` |
| 预注册 `pre_registration.json` | `895bb367…075b` |
| 数据集 | `artifacts/v9/s1/datasets/8234f2f3…ad26` |
| `dataset_manifest.json` | `5cbd6522…594`；当前 `generation_seconds=45.739918708000005` |
| `truth/development.jsonl` | `76b98649…26e6` |
| r2 `REPORT.md` | `86a13488…bd7c` |
| r2 `metrics.json` | `ad32d483…b36a` |
| P19 `REPORT.md` / `metrics.json` | `f27b401b…7334` / `4dd5a018…a3b7` |
| P19 实测载体 | `independent_checks.json` `d6f741d4…b744`；`logs/independent_checks.out` `e9e33eaf…c82d` |
| P19 修复副本 | `…/v9p19/iso_check_repaired/ainerzero/…/evaluation.py` sha `9d0ae913…d4ded`；临时树仍在 |
| P20 draft | `P18-r2-review-task.json` sha `7a5dec16…627c`（draft） |
| MLX 是否导入 | **否**（本棒脚本只 import 标准库；r2 `metrics.json → no_real_execution.mlx_imported=false`） |

**隔离复现结果**

| 产物 | 原 SHA | 复现 SHA | 字节一致 |
| --- | --- | --- | --- |
| `analysis/independent_truth_check.json` | `b8f55a8b…afea` | `b8f55a8b…afea` | ✅ |
| `metrics.json` | `ad32d483…b36a` | `ad32d483…b36a` | ✅ |
| `analysis/input_identity.json` | `542c7c09…2ee8` | 同 | ✅ |

说明：`build_r2_metrics.py` 的 `OUT` 是**硬编码绝对路径**，不读 `V9P18R2_OUT`（见 M1）；复现时只在内存中把 `OUT` 重绑到本棒目录，原脚本未改、原 r2 产物未覆盖。复现字节一致说明 r2 的产物可由封存输入与其脚本重现；**不**说明其结论文字正确。

## 3. F1–F9 逐条核

| F | P19 的问题 | r2 的声明 | P20 结论 | 关键证据 |
| --- | --- | --- | --- | --- |
| F1 | 612/1292 与实测 611/1492 矛盾；metrics 文案混写 | 已闭；对外 611/1492/800/3500/175；612/1292/600 标 superseded | **部分成立（D1）**：数值对；历史出处不完整/错归属 | r1 `metrics.json:447`、`build_metrics.py:197` 仍含 1292；r2 `REPORT.md:13,125` |
| F2 | 修复态是外推，phase_totals 混列 | 已闭；每块 provenance；投影只作审计 | **成立（轻微）**：as_coded / repaired / projection 已分块；`totals` 只有一条 `provenance_mix` 字符串，不是逐字段 provenance | r2 `call_counts`、`per_run`、`totals` |
| F3 | 4 h 已含 eval，选项 B-4 是伪问题 | 已闭；4 h 含 eval；守卫只在 train 路径；300 s 硬墙钟 | **部分成立（D4）**：包含关系与守卫位置正确；**300 s 不是硬墙** | `commands.py:42,200`；`spec.py:77`；`worker.py:440`；r2 `REPORT.md:15,181,202` |
| F4 | 47.6 s 是旧计划、不是 smoke 计时 | 已闭；新数据成本未知；47.605 旧计划；9.111 仅 packet 下界 | **成立**（但“清单字段”措辞应与当前清单值区分，见 D2） | r2 `data_cost`；当前 manifest 45.7399 |
| F5 | 选项 A 不是零变更 | 已闭；原值/n/缺测保留；family/constant 仅诊断 | **基本成立（M2）**：n/缺测/诊断正确；`original_..._values_retained: true` 易被读成“已有数值” | r2 `option_A`、`frozen_metric_reporting` |
| F6 | 1703 是混合口径；1503/1903 也混合 | 已闭；1003/2103/1492 自洽 | **成立** | P19 `per_run_total`：1003/2103/1492 |
| F7 | M2 11/42 是手写常数 | 已闭；从 P19 实测读取，不再手写 | **不成立（D5）**：脚本仍硬编码 11/42，并写 `not_hand_typed_in_r2: true` | `build_r2_metrics.py:258,262,329,330` |
| F8 | 600 vs 800 口径不一 | 已闭；800=200 topology+600 few-shot | **成立** | r2 `probe_graph_calls=800`；P19 实测 800 |
| F9 | 同一 digest 两个 generation_seconds | 已闭；清单字段冻结后被改写；取保守 47.605 | **不成立（D2）**：无历史 diff；当前清单=45.7399=data_identity；清单创建早于 prereg | 当前 manifest、prereg `created_unix` |

### 3.1 D1（F1，中）数值对，但历史记录不完整

r2 的对外数字 **611 / 1,492 / 800 / 3,500 / 175** 与 P19 实测、与本次独立算式一致；612/1292/600 也确实标为 superseded。问题在**历史归属**：

- r1 `reports/V9-P18/metrics.json:447` 的 `unmeasured` 数组原文是 `"MLX batch-1 single-step forward cost (611 eval calls, 1292 forwards) is not measured by the frozen smoke"`；同文件 `:449` 还有 `"MLX probe_graph cost (600 calls)"`。
- r1 `reports/V9-P18/analysis/build_metrics.py:197` 是同一句 `611 eval calls, 1292 forwards`；`:199` 是 `600 calls`。
- r1 `REPORT.md:275` 有 612/1292；`:243` 有 600。
- r2 `REPORT.md:13` 说“r1 报告正文里的 612/1292/600 是文字错误：r1 自己的 `metrics.json` 早已存的是 611/1492/800”。这句话对**结构化数值字段**（r1 metrics `:392–394` = 611/1492/800）成立，但会让读者以为 **metrics.json 文件本身没有 1292**。
- r2 `REPORT.md:125` 说“r1 `metrics.json` 本身是 611/1492/800，错只发生在 r1 `REPORT.md` §10 选项B 第 3 条（612/1292）与其 `unmeasured` 文案”。`unmeasured` 文案并不在 `REPORT.md` 里，而是在 `metrics.json:447` 与 `build_metrics.py:197`；这里把出处错归到 REPORT。
- r2 `metrics.json → call_counts…r1_registration_values_superseded.note` 只说“only the REPORT prose and the unmeasured text drifted”，没有给出 `metrics.json:447` / `build_metrics.py:197` 两个确切位置。

**改法**：保留 612/1292/600 的 superseded 值，同时加两个字段：`r1_metrics_unmeasured_text`（`metrics.json:447`，含 1292/600）与 `r1_build_metrics_line_197`；把 `REPORT.md:13/125` 改为“结构化数值字段 611/1492/800 正确；正文与 metrics/build 脚本文案也含 1292/600，全部保留为历史”。这不改变任何数字，只补历史。

### 3.2 D2（F9，中高）“冻结后被改写”没有证据，且与当前字节矛盾

r2 `REPORT.md:21` 与 `metrics.json → data_cost.frozen_document_inconsistency` 都写：同一 digest 的两个 `generation_seconds` 说明“**清单字段在预注册冻结后被改写**”。本次核对：

| 事实 | 值 |
| --- | --- |
| 当前 `dataset_manifest.json → generation_seconds` | **45.739918708000005** |
| 当前 manifest `created_unix` / mtime | 1792576623.88 → **2026-10-21 12:57:04** |
| prereg `data_identity.generation_seconds` | **45.739918708000005**（与当前 manifest 相等） |
| prereg `timing.smoke.data_generation_seconds` | 47.605202458999884 |
| smoke `created_unix` | 1792572559.63 → **2026-10-21 11:49:19.63** |
| prereg `created_unix` / mtime | 1792614732.81 → **2026-10-21 23:32:12** |
| `artifacts/` 是否有 git 历史 | **无**（`.gitignore:15` 忽略 `artifacts/`） |

时间线是：smoke 在 11:49 记录 47.605 → 当前清单在 12:57 记录 45.7399 → prereg 在 23:32 冻结，同时写入 `data_identity=45.7399` 与 `timing.smoke=47.605`。**两个值在冻结前就已共存**；当前清单并不是 47.605，也没有任何 diff/历史能证明它在冻结后被改写成 47.605。r2 的“被改写”是**无依据的因果断言**，且与当前清单字节相反。P19 F9 已经做了同样的过度推断；r2 应当纠正，而不是复述。

**可核实的正确说法**：同一 dataset digest 在冻结文档里有两个 `generation_seconds`（45.7399 与 47.605）；当前清单字段是 45.7399（与 `data_identity` 一致）；无历史 diff，**不能确定**两个值各自的写入时刻与原因；`phase_wall` 取了较大的 47.605（对墙钟是保守值），delta=0.0 不受影响。建议把字段名从 `frozen_document_inconsistency` 改为 `two_generation_seconds_values`，并附 `manifest_value`、`manifest_created_unix`、`prereg_created_unix`、`smoke_created_unix`。

### 3.3 D3（高）B2 的调用量没有绑定 dataset digest，B1 的新数据会改变计数

r2 `REPORT.md:269–270` 的 B1/B2：

- B1：新数据集批，**新 plan/新 seed → 新 dataset_digest**；200 世界 × ≥10 packet；按 family 分层，保证每 family 每世界 ≥9 transition（k=8 需要 8 support + 1 query）。
- B2：登记**实测**评测调用量：**175 窗口 batch、611 序列前向、1492 单步 forward、800 probe_graph、3500 encode、D 1 次 C0 forward**；来源 `measured_non_author`（P19）。

问题：B2 的这组数是**当前 digest `8234f2f3…` 的 200 个 dev 世界、950 packet、episode 长度 7/5/4/3、`query_limit=8`** 上测得的。B1 明确要换新 digest、每世界 ≥10 packet、每 family ≥9 transition；这会把 k=8 从“0 个世界”变成“有样本”，并改变 query 数、`step_sequence`、单步 forward、`probe_graph`、`encode`。B2 没有任何 `dataset_digest` 字段，读者会把它当成 B1 新数据的预算。

**示意性重算（不是实测，只说明不可沿用）**：若新数据是 200 世界、每世界恰好 9 transitions、family 构成不变、`query_limit=8`，同一组公式给出：

| 组件 | 当前 digest（P19 实测） | B1 下限示意（200 世界 × 9 transitions） |
| --- | --- | --- |
| `step_sequence` | 611 | **1,011**（topology 200 + few-shot 4×200 + m2 11） |
| 单步 forward | 1,492 | **3,792**（750 + 200×(1+2+4+8) + 42） |
| `probe_graph` | 800 | **1,200**（200 + 5×200） |
| `encode` | 3,500 | **11,600**（2×5,800 query） |
| 窗口 batch | 175 | **未知**（取决于新数据的窗口数） |

这些示意数**不是**对 B1 的预算估计，只是证明 611/1,492/800/3,500 不能直接搬过去。B2 还混入了“D 1 次 C0 forward”（D 候选，不是 eval 调用），应拆开。

**改法**：B2 加 `dataset_digest: 8234f2f3…` 与 `applies_to: current development partition only`；B1 加“新 digest 上必须按同一公式重算调用量，B2 的数值不随 B1 迁移”；D 候选单独一行。

### 3.4 D4（高）300 s 不是“硬墙钟”：300 标称 / 350 监督 / 120 账本

r2 多处写“单次 eval 的硬墙钟是 CLI `PREP_BUDGET["eval"]=300 s`”“子进程硬超时 300 s”“评测时的硬约束仍是每次 300 s”“每次 300 s 硬墙钟”（`REPORT.md:15,181,202,204,272`）。冻结源码的事实是：

| 层 | 值 | 源码 |
| --- | --- | --- |
| CLI 标称预算 | **300 s** | `commands.py:42`：`PREP_BUDGET = {"data": 600.0, "smoke": 300.0, "verify": 120.0, "eval": 300.0}` |
| supervisor 超时 | **350 s** | `spec.py:77`：`"supervision_extra_seconds": 50.0`；`commands.py:200`：`supervision_seconds = budget + spec.TIMING["supervision_extra_seconds"]`；`subprocess.run(..., timeout=supervision_seconds)` |
| 账本预留/记账 | **120 s** | `worker.py:440`：`ledger.reserve(active_run, active_seconds=min(120.0, max(10.0, 0.5 * budget)))` |
| eval 分支 phase 复查 | **无** | `worker.py` 的 eval 分支没有 `phase_budget_exceeded`；phase 守卫只在 `_train` / `mode_train` |
| phase 守卫看到的 eval 墙钟 | **120 s/次**（账本记账值，不是实际耗时） | `RunStore.consume` 按 `active_seconds` 记账；`wall_seconds` 字段即预留值 |

所以：**300 s 是标称预算，不是硬墙；真正的进程级硬超时是 350 s；账本只记 120 s；eval 自己不复查 phase cap。** 这三层不能混写。r2 的静态余量检查用 1080 s（9×120）作为“账本预留”，这是对的；但它同时把 300 s 叫“硬墙钟”，并说“评测时的硬约束仍是 300 s”，这是错的。用 350 s 重算静态余量：`4099.605202459 + 9×350 = 7249.605202459 < 14400`，**结论仍然成立**，但应写成“350 s 监督超时下静态仍放得进 4 h；实际 MLX 墙钟未知”。

**改法**：把 `eval_wall_nominal_per_invocation_seconds: 300` 保留为 nominal；新增 `eval_supervision_timeout_seconds: 350`、`eval_ledger_reserve_seconds: 120`、`eval_phase_guard: false`；把“300 s 硬墙钟”全部改为“300 s 标称 / 350 s supervisor 超时 / 120 s 账本预留”；静态检查同时给 350 s 版本。

### 3.5 D5（F7，中）F7 的“不再手写 11/42”为假

r2 `REPORT.md:19` 说“r2 不再手写 M2 的 11/42，直接取 P19 实测组件拆分”；`metrics.json → call_counts.m2_constants` 也写 `not_hand_typed_in_r2: true`。但 `build_r2_metrics.py`：

- `:258` `"value": 200 + few_shot_step_sequence + 11`
- `:262` `"value": 750 + few_shot_transitions + 42`
- `:329–330` `"step_sequence_calls": 11, "single_step_forwards": 42`（字面常数，旁边只加了一个 `source` 字符串）
- `:348` `"few_shot_repaired_stop_frames": 1100`（也是字面常数）

11/42 的值与 P19 `component_split.m2_interference` 一致，所以**数字没错**；但“直接取 P19”“not hand-typed”是假的，这正是 F7 原先指出的“注释与代码不一致”问题在 r2 重演。**改法**：从 `as_coded_split["m2_interference"]["step_sequence_calls"]` 与 `["step_sequence_transitions"]` 读取；若坚持字面常数，就把 `not_hand_typed_in_r2` 改为 `false` 并注明“手写常数，已与 P19 核对”。

### 3.6 F2/F5/F6/F8 的通过说明

- **F2**：`as_coded`（measured）、`repaired_k1`（measured_non_author）、`r1_analytic_projection`（projected_superseded）三块已分开；`per_run.eval.provenance=measured_non_author`；`totals.provenance_mix` 说明了训练/评测/D 的来源。严格说 `totals` 没有逐字段 provenance，但该块只有两类来源，暂不构成错误。
- **F5**：`option_A.is_zero_change=false`；`sample_sizes` 为 200/750、200/550、150/350、50/100、0/0；k=8 与 k=4 缺失 family 记 `insufficient_data`；family/constant 均 `diagnostic_only`。**M2**：`original_accuracy_and_displacement_values_retained: true` 易被读成“已有数值”；实际没有 accuracy/displacement 数值（被 k=1 阻断），应改为“定义、n、缺测保留；数值待真实 eval”。
- **F6**：P19 `per_run_total` 的 as-coded `stop_frames=1003`、`transitions=792`；repaired `2103`、`1492`；r2 的 `frames.self_consistent` 与之一致；1703/1503/1903 均标 hybrid。
- **F8**：`probe_graph=800`（200 topology + 600 few-shot）；600 只作 few-shot 半。正确。

## 4. 复核通过的关键数字（独立复算）

| 项 | 复算值 | 与冻结/P19 一致 |
| --- | --- | --- |
| `raw_updates` | 3510 | ✅ |
| `estimate_seconds` | 359.9312287726061 | ✅ |
| `deadline_seconds` | 450 | ✅ |
| `arm1_estimate_seconds` | 1.501679232227616 | ✅ |
| `arm1_deadline_seconds` | 2 | ✅ |
| `phase_wall_seconds` | 4099.605202459 | ✅ |
| `headroom_seconds` | 10300.394797541 | ✅ |
| k=0/1/2/4/8 世界 | 200/200/150/50/0 | ✅ P19/r2 |
| k=0/1/2/4/8 query | 750/550/350/100/0 | ✅ P19/r2 |
| `step_sequence` | 611 | ✅ P19 实测 |
| 单步 forward | 1492 | ✅ P19 实测 |
| `probe_graph` | 800 | ✅ P19 实测 |
| `encode` | 3500 | ✅ P19 实测 |
| 窗口 batch | 175（5×35） | ✅ P19 实测 |
| 9 run 合计 | 5499 / 13428 / 7200 / 31500 / 1575 | ✅ 算术 |
| 训练合计 | 31590 updates / 1575 探针 batch / 74250 帧槽 | ✅ 算术 |
| 帧自洽 | 1003 / 2103 / 1492 | ✅ P19 |

## 5. 保留的负面证据与未验证项（不当作通过）

1. **k=1 崩溃**：`evaluation.py` 的 `stop=support[-1]+1` 使 k=1 只有 1 帧，`step_sequence` 抛 `BackendError("a sequence probe needs at least two frames")`；k=0 结果也不落盘。r2 保留，正确。
2. **support 少写一条**：排他帧界使 k=2 只写 1 条、k=4 只写 3 条；修复应为 `stop=support[-1]+2`，需新冻结 + 非作者复核。r2 保留，正确。
3. **真实 `probe_graph` 的 TypeError**：r6 裁决指出非空 metric map 上 numpy flat index 被当 `(r,c)` 解包；r2 保留其阻断性，未修。
4. **修复态计数来自计数替身**：611/1492/800 是调用边界计数，不是生产 `MlxBackend` 能跑完的证明，也不是能力结果。r2 保留，正确。
5. **MLX 单位耗时未知**：batch-1 单步 forward / encode / probe_graph 均未测；不把 CPU 替身或 batch-16 时长外推为 MLX 实测。r2 保留，正确。
6. **新数据成本未知**：47.605 s 只覆盖旧计划；新计划每世界建图成本未测。r2 保留，正确。
7. **账本边界未修**：phase 守卫读 card-local `output_root/control.sqlite3`；跨 output-root 唯一性属 r6，r5 不声称解决。r2 保留，正确。
8. **本棒未验证**：没有重跑 P18/P19 的评测套件；没有执行真实 `MlxBackend`；没有验证 `_evaluate_arm` 的 RunStore 绑定、checkpoint 重载、参数 SHA 校验；没有验证 `arms.py` 的 MLX 数值路径；没有做 M2 选点稳健性。本报告只对**报告/指标/脚本/来源**做只读核对与纯 Python 复算。
9. **本卡不自我验收**；`reported` 与报告通过均不代表能力通过。

## 6. 交回统筹（需一级决定）

1. 是否接受 **D1–D5 为必须修订**（全部是文字/来源/口径修订，不需要新训练、新数据、新 GPU、新 eval）。
2. 是否同意 **当前 r2 不宜直接进入用户批准流程**；建议先出 r3 文字修订，重点补：r1 metrics/build 的 1292 出处、generation_seconds 的无历史 diff 表述、B2 的 dataset_digest 绑定、300/350/120 三层口径、F7 的 11/42 出处。
3. 是否接受 **B2 只适用于当前 digest `8234f2f3…`**；若 B1 进入批准流程，调用量必须在新 digest 上重算，不能沿用 611/1492/800/3500/175。
4. 是否接受 **4 h 已含 eval** 的结论不变，但静态余量需同时给 350 s 版本（7249.605 s < 14400 s）；不扩大登记、不改 phase_wall。
5. 本卡**不写批准行、不改 k/世界/分区/训练步数/eval 额度/预算**，不构成任何运行授权。

## 7. 产物清单（均在 `reports/V9-P20/workbuddy-q7t2/`）

- `REPORT.md`：本报告。
- `metrics.json`：结构化复核结果（SHA、复现、预算、k 覆盖、F1–F9 判定、D1–D5、M1–M5、未执行项）。
- `analysis/verify_p18r2.py` / `analysis/verification.json`：独立复核脚本与结果（38+14 SHA、k 覆盖复算、预算复算、源码常量、generation_seconds 时间线、脚本静态事实）。
- `analysis/repro_p18r2.py` / `analysis/repro/repro_summary.json`：r2 两脚本的隔离复现（字节一致）。
- `logs/verify_p18r2.{out,err}`、`logs/repro_p18r2.{out,err}`：完整日志；err 均 0 字节。
- 说明：`reports/V9-P20/analysis/p20_independent_check.*` 等文件不是本棒产物，未使用、未修改、未删除。
