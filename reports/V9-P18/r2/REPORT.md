# ainerzero.V9.P18 r2 修订报告：S1 评测调用量与 k 支持覆盖（冻结值不改的预算决策材料）

角色：executor（二级，执行层）；本棒 ID：`deepseek-v41f-p8k2`（DeepSeek V4.1 Flash Free，skills=text/code/math）；日期：2026-10-22（客户端）
任务状态：reported；实验状态：**未执行**（纯 CPU 工程统计、独立真值复算与调用量来源修订；无训练、无真实评测、无 MLX 导入）
修订依据：`reports/V9-P19/REPORT.md`（非作者复核 F1–F9，sha256 `f27b401b…7334`）；`S1-R6-DECISION.md`；`P18-r2-review-task.json`（P20 draft）
文件范围：只写 `reports/V9-P18/r2/`。`reports/V9-P18/` 下 r1 的 `REPORT.md`、`metrics.json`、`analysis/**`、`logs/**` 全部**只读、零覆盖**（14 个冻结输入 SHA 审后仍全部一致，见 §3）。
本卡结论**仅供一级取舍**，不是科学参数变更，也不构成任何运行授权。

---

## 0. 摘要（给一级取舍）

1. **F1 已闭**：进入用户批准流程的调用量应为 **611 序列前向 / 1492 单步 forward / 800 probe_graph / 3500 encode / 175 窗口 batch（35×5）/ D 1 次 C0 forward**。r1 报告正文里的 **612 / 1292 / 600** 是文字错误：r1 自己的 `metrics.json` 早已存的是 611/1492/800（`reports/V9-P18/metrics.json` sha `71bc8c38…af836`）。本轮不靠猜：611/1492 的“实测”出处是 P19 在冻结快照字节副本上做 1 行修复后测得（`reports/V9-P19/analysis/independent_checks.json` sha `d6f741d4…b744`，临时树 `/private/var/folders/…/opencode/v9p19/iso_check_repaired`，修复行 sha `9d0ae913…d4ded`）。**我没有把 P19 的实测冒称成自己的实测。**
2. **F2 已闭**：r2 的每一块计数都带 `provenance`。`as_coded`（现状路径）= **实测（作者 r1 插桩 + P19 字节级复现）**；`repaired_k1`（修好 k=1）= **实测（非作者 P19）**；r1 的修复态外推只作 `projected_superseded` 审计保留，不再当实测引用。阶段合计拆成两块，不再混列。
3. **F3 已闭且删去伪问题**：4 h 阶段上限**本来就包含评测**——`commands.py:737-757` 与 `worker.py:368-385` 明确把 auxiliary eval/verify 计入 `total_wall`，eval 分支在同一个 card-local 账本 `output_root/control.sqlite3` 里开 aux run 并预留 `min(120, max(10, 0.5×300)) = 120 s`（`worker.py:435-440`）。所以“评测墙钟是否计入 4 h 上限”不是待裁决项。**真正的边界**是：①phase 守卫只在 **train 路径**检查（`worker.py:368`、`commands.py:737`），eval 分支自己不复查；②单次 eval 的硬墙钟是 CLI `PREP_BUDGET["eval"]=300 s`；③账本唯一性/跨 output-root 重置是 **r6 的未修缺陷**，r5 不声称已解决。
4. **F4 已闭**：新长 episode 数据生成成本 **未知/未测**。47.605202459 s 是**旧计划**（2200 世界 / 10450 packet）的清单字段，且 `smoke.py` 只是抄 `manifest["generation_seconds"]`，并不计时生成；不再写“47.6 s 实测”。只保留一条不算成本估计的 packet 速率下界（≈9.111 s，仅 packet 成本、不含每世界建图）。
5. **F5 已闭**：选项 A **不再自称“零变更”**。冻结指标 `few_shot_unseen_transition` 的 accuracy / displacement error 原值、样本量 n、缺测照存；`insufficient_data` 不填 0、不填满分。family 拆分与 constant 基线**只作诊断**；coverage/误报率若要替代冻结定义，必须登记为新 metric id，不能塞进“零变更”。
6. **F6 已闭**：1703 / 1503 / 1903 都是混合口径（混用 stop_frames 与 transitions），不对应任何真实或自洽运行。自洽只有两行：**as-coded = 212 calls / 1003 stop_frames / 792 transitions（实测）**；**repaired = 611 / 2103 / 1492（P19 实测）**。
7. **F7 已闭**：r2 不再手写 M2 的 11/42，直接取 P19 实测组件拆分；每世界规则改写为“修复后 stop=k+1 → 每世界执行 k 条 transition”。
8. **F8 已闭**：`probe_graph` 总数是 **800**（topology 200 + few-shot 600）；600 只是 few-shot 那一半。
9. **F9 已闭**：同一 dataset digest 的 `generation_seconds` 在冻结文档里有 45.739918708 与 47.605202459 两个值 → 清单字段在预注册冻结后被改写；`phase_wall` 取了保守的 47.605，记为“冻结文档内部不一致（已取保守值）”。
10. **k 覆盖与 P15/P16 原证据一致**：k=0/1/2/4/8 → 200/200/150/50/**0** 个世界，750/550/350/100/0 条 query；family 与 episode 长度 1:1 绑定（nav 7 步、e3 5 步、time 4 步、relation 3 步）。P16 的 `0/200`、`50/200` 与 P15 的 `611 calls` 独立复现。
11. **负面证据全部保留**：k=1 的 `BackendError`（`frames<2`）、support 少写一条、以及 r6 裁决指出的 `runtime.MlxBackend.probe_graph` 在非空 metric map 上 `TypeError`——三条都仍然阻断“真实评测可完整执行”。本卡不修源码，不把 CPU 计数当能力或 MLX 耗时。
12. **全部调用量都有算式**（§5）：9 训练 = 31,590 optimizer + 1,575 探针窗口 batch；9 评测 = 1,575 窗口 batch + 5,499 序列前向 + 13,428 单步 forward + 7,200 probe_graph + 31,500 encode；D = 1 次 forward / 32 个 C0 槽。
13. 交付 **A / B 两个可审阅选项**（§8/§9）。B 的 7 项逐条列出“需要用户批准”的精确项与“未知”项；本卡不写批准行、不扩额度。
14. P20 非作者复核卡（`P18-r2-review-task.json`，sha `7a5dec16…627c`）仍是 **draft**；必须在 r2 正式交报并由一级封新报告 SHA 后才 ready。本卡**不自我验收**。

---

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# 注册 / 领卡 / 心跳（摘要）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent deepseek-v41f-p8k2 --tier 2 \
  --kind "DeepSeek V4.1 Flash Free" --profile-file <profile.json>     # benchmarks=[]
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.P18 \
  --agent deepseek-v41f-p8k2 --token <任务卡令牌>
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay heartbeat ainerzero.V9.P18 --agent deepseek-v41f-p8k2 --msg "…"

# r2 新计算（两个脚本，均为新实现；不重跑 P18/P19 套件）
BASE=/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p18_r2
env -i PATH=/usr/bin:/bin:/usr/local/bin HOME="$BASE/home" TMPDIR="$BASE/tmp" \
    PYTHONDONTWRITEBYTECODE=1 V9P18R2_OUT=reports/V9-P18/r2 \
    .venv/bin/python reports/V9-P18/r2/analysis/independent_truth_check.py \
    > reports/V9-P18/r2/logs/independent_truth_check.out 2> …/independent_truth_check.err
env -i … .venv/bin/python reports/V9-P18/r2/analysis/build_r2_metrics.py \
    > reports/V9-P18/r2/logs/build_r2_metrics.out 2> …/build_r2_metrics.err

# 只读审计：r1 冻结输入 14 项 SHA、P19 实测产物 SHA、P18-r2/P20 draft SHA（脚本内完成）
```

- 两个脚本 **RC=0，stderr 均为 0 字节**。
- 本轮**没有**运行：`--mode train/eval/smoke/data`、任何 MLX 前向/梯度/优化器、final 分区读取、数据生成、模型下载/安装、资源基线重设、git commit/push、批准行写入、RESEARCH_LOG 改写。
- 本轮**没有**重跑 P18 的 `count_calls.py` / `truth_stats.py` / `build_metrics.py`，也**没有**重跑 P19 的 `independent_checks.py`；没有复用 `/tmp/v9p18_iso`，没有覆盖 r1 任何产物。
- 隔离：`HOME` / `TMPDIR` / `PYTHONDONTWRITEBYTECODE` 指向私有临时根；输出目录由 `V9P18R2_OUT` 显式指定为 `reports/V9-P18/r2`。

## 2. 身份、来源与 SHA（独立配 source）

| 项 | 值 / SHA256 |
| --- | --- |
| 冻结 r5 快照根 | `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot` |
| `evaluation.py` | `92d8de4a6551b8538f38a54b17b550a88aa80c4135d05c0e29b8be2f8bf72aa3` |
| `runtime.py` | `a99346522f294bf195438efb8e9af72db391abd517ab4d80533330ad6ee506c7` |
| `metrics.py` | `e1c36b657794d5ba3ac2c59b2994ea71c5bc66eb032d4f4b08a9f91ef5a643e1` |
| 预注册 `pre_registration.json` | `895bb3676cd3db6ad7995814ee940e23b1bff55747e8dea665f5fe426386075b` |
| 数据集 | `artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26` |
| `truth/development.jsonl` | `76b986495229de893fb50e0740296f6414225a06b1b444fa4f20eb43911e26e6` |
| **P18 r1 报告** | `0b33e29fbd2e5ab68f7f5338f120d596798a44f1af8c1393c3056b6ccbf09908`（**未改**） |
| **P18 r1 metrics.json** | `71bc8c38eb276ea9755336817fe1ea4bebf7bdfef2fb15c842703a6f6faaf836`（**未改**） |
| **P19 复核报告** | `f27b401bcf9ad2c79c3de47592eefd299e58d9c8c139e0c398dcd66bd7dc7334` |
| **P19 复核 metrics.json** | `4dd5a018b39c0cb08aa993b39fe16bd1b79f237d66fa129742a1db14e965a3b7` |
| **P19 实测载体** | `reports/V9-P19/analysis/independent_checks.json` sha `d6f741d4ec8368d655e9150cfbf3eb40434ac12b11f48f98cbc3fce0e01bb744`；`logs/independent_checks.out` sha `e9e33eaf8aaf01c786fbcc15421695a9b4b7304411b827e5d0e0b4f2a2e4c82d` |
| P19 修复临时树 | `/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19/iso_check_repaired`（仍在）；修复后 `evaluation.py` sha `9d0ae9133e6e3ce761b430ef2fc3aea22fd85b2da37e2967c63953c5b57d4ded`，仅 1 行 `stop=support[-1]+1 → +2` |
| P18-r2 独审 draft（P20） | `P18-r2-review-task.json` sha `7a5dec166abf5bd365f8d1074a4431c91d2622532ff0f1d9e9a69d9a6b1f627c`（status=draft） |
| r2 metrics.json | `ad32d483508af845e10927ae0a7379db5905e7a30adde0753465d1b25922b36a` |
| r2 独立真值结果 | `b8f55a8b0ea9136b22383224a1ef67a2f4b0d5ee3d86f51f77cbd784df08afea` |
| r2 脚本 | `independent_truth_check.py` sha `ce0b9185…ea7be`；`build_r2_metrics.py` sha `1e9c0a3f…71757` |
| MLX 是否被导入 | **否**（两个脚本都不 import mlx；`metrics.json → no_real_execution.mlx_imported=false`） |

**r1 证据保持完整**：`P18-frozen-review-inputs.json` 里 14 个 r1 文件（报告、3 个脚本、4 个 JSON/日志、6 个 log）审前/审后 SHA 全部一致（`metrics.json → identity.p18_r1_frozen_inputs_all_unchanged=true`）。r2 只新增目录，不改旧证据。

## 3. F1–F9 逐条闭合（含改法）

| # | 状态 | r2 的修订 | 证据 |
| --- | --- | --- | --- |
| F1 | **已闭** | 对外数字统一为 **611 / 1492 / 800 / 3500 / 175 / D 1**；612/1292/600 标为 r1 文字错误并给出差值（−1 / +200） | `metrics.json → call_counts.per_arm_seed_eval.r1_registration_values_superseded` |
| F2 | **已闭** | 每块带 `provenance`：`measured`（as-coded，作者 r1 + P19 复现）、`measured_non_author`（修复态，P19）、`arithmetic_r2`、`projected_superseded`（r1 外推，仅审计）；阶段合计拆块 | `call_counts`、`totals.provenance_mix`、`per_run` |
| F3 | **已闭** | 删去“评测是否计入 4 h”伪问题；给出 4 h 已含 eval 的源码证据、9×300 nominal 与 9×120 账本预留、静态余量检查；单列“守卫只在 train 路径复查”与“账本唯一性属 r6 未修” | `phase` |
| F4 | **已闭** | 新计划成本写 `unknown_not_measured`；47.605 s 明确是旧计划清单字段；packet 速率 9.111 s 标为“非成本估计的下界” | `data_cost` |
| F5 | **已闭** | 选项 A 改为“**不是**零变更”；冻结指标原值/n/缺测保留；coverage/FPR 走新 metric id 或登记；family/constant 标 `diagnostic_only` | `frozen_metric_reporting`、`diagnostic_baselines`、`option_A` |
| F6 | **已闭** | 1703/1503/1903 标 `hybrid_numbers_not_a_real_run`；只保留 1003（as-coded）与 2103（repaired）两行自洽 stop_frames | `frames` |
| F7 | **已闭** | M2 11/42 从 P19 实测组件拆分读取（`provenance=measured_non_author`），不再手写；transition 规则改成 `k transitions per world` | `call_counts.m2_constants`、`component_arithmetic_r2` |
| F8 | **已闭** | `probe_graph=800`（200 topology + 600 few-shot）；600 仅指 few-shot 半 | `call_counts.…repaired_k1.probe_graph_calls` |
| F9 | **已闭** | 记为“冻结文档内部不一致（同一 digest 两个 generation_seconds，清单字段在冻结后被改写；已取保守 47.605）”，不再称“可解释差异” | `data_cost.frozen_document_inconsistency` |

## 4. 调用量：实测 / 非作者实测 / 外推（分开计）

### 4.1 每 arm×seed 的**事后评测**（一次）

| 组件 | 现状（k=1 崩溃） | 修好 k=1 后 | 来源 |
| --- | --- | --- | --- |
| 窗口 forward_loss（5 探针） | 175 | 175 | 实测（r1+P19） |
| 窗口帧槽 | 8,250 | 8,250 | 算术 |
| `step_sequence` 调用 | 212 | **611** | 212 实测；611 = P19 实测 |
| 单步 forward | 792 | **1,492** | 792 实测；1492 = P19 实测 |
| `probe_graph` | 400 | **800** | 400 实测；800 = P19 实测 |
| `encode` | 1,500 | **3,500** | 1500 实测；3500 = P19 实测 |
| few-shot query | 750（只到 k=0） | 1,750 | 算术（750+550+350+100） |
| 终止 | k=1 `BackendError`，k=0 结果也不落盘 | 完整 | P19 真实 runtime 方法核实 |

**组件算式（r2 新算，全部对上 P19 实测）**：

```
step_sequence  = topology 200 + few-shot (200+150+50) + m2 11          = 611
single-step    = topology 750 + few-shot (200×1 + 150×2 + 50×4) + 42   = 1492
probe_graph    = topology 200 + few-shot (200+200+150+50)              = 800
encode         = 2 × (750+550+350+100)                                  = 3500
窗口 batch      = 5 检查点 × ceil(550/16 = 35)                          = 175
```

`metrics.json → call_counts.component_arithmetic_r2.arithmetic_matches_measurement=true`。

**r1 的 612 / 1292 / 600 错在哪里**：r1 `metrics.json` 本身是 611/1492/800，错只发生在 r1 `REPORT.md` §10 选项B 第 3 条（612/1292）与其 `unmeasured` 文案（611 calls / 1292 forwards / 600 probe_graph）。r2 把正文与 JSON 一起校正，并把 612/1292 留在 `superseded` 块里供审计，不删除历史。

### 4.2 训练期检查点探针与事后评测**分开计**

| 项 | 每 run | 9 run 合计 |
| --- | --- | --- |
| 训练 optimizer update | 3,510 | 31,590 |
| 训练期探针窗口 batch | 5 × 35 = 175 | 1,575 |
| 训练期探针帧槽 | 8,250 | 74,250 |
| 训练 forward batch 当量 | 3,510 + 175 = 3,685 | 33,165 |
| 评测窗口 batch | 175 | 1,575 |
| 评测 `step_sequence` | 611 | 5,499 |
| 评测单步 forward | 1,492 | 13,428 |
| 评测 `probe_graph` | 800 | 7,200 |
| 评测 `encode` | 3,500 | 31,500 |
| D 候选（arm1） | 1 次 forward / 32 C0 槽 | 1 / 32 |

训练期 5 检查点探针与 9 次事后评测**是两笔不同开销**，本表不再混列。

### 4.3 现状（as-coded）与修复态（repaired）的 provenance

| 块 | 来源标签 | 说明 |
| --- | --- | --- |
| as-coded 212 / 792 / 400 / 1500 / 175 | `measured` | 作者 r1 插桩后端；P19 用同一脚本字节级复现（7 个产物 SHA 全同） |
| repaired 611 / 1492 / 800 / 3500 / 175 | `measured_non_author` | P19 在冻结快照字节副本上改 1 行后实测；**不是本卡实测**，链接见 §2 |
| r1 “修复态” | `projected_superseded` | r1 用公式外推，数值恰好与实测相同；r2 不把它当实测引用 |
| M2 11 / 42 | `measured_non_author` | 取 P19 组件拆分，不由 r2 手写 |

**保留的限制**：P19 的修复态计数跑在**计数替身后端**上（`encode` 固定宽度 1-D、`probe_graph` 为替身），不是生产 `MlxBackend.probe_graph`。r6 裁决另指出真实 `probe_graph` 在非空 metric map 上会 `TypeError`（`S1-metric-map-direct-probe.json`，`runtime.py` sha `a9934652…6c7`）。因此 611/1492/800 是**调用边界的计数**，不是“真实评测已能跑完”的证明。

## 5. 预算算式（9 训练 + 9 评测 + 1 D；冻结值不改）

```
# 冻结输入（未改）
step    = 0.0069624580000891 s      # smoke batch-16 forward+loss
d_step  = 0.0013035410001975833 s
duty    = 0.25 ; overhead = 1.20 ; update_cost = 3*step = 0.0208873740002673
eval_batches = 48

# 训练 run（每 arm×seed；arm2/3/4 × seed 0/1/2 = 9 次）
raw_updates = floor((360*0.25/1.20 − 48*step*5) / update_cost) = 3510
eval_cost   = 48*step*5 = 1.670989920021384 s        # 训练期探针成本项
estimate    = (3510*update_cost + eval_cost)/0.25*1.20 = 359.9312287726061 s
deadline    = ceil(1.25*estimate) = 450 s ; supervision = 500 s

# D 候选（arm1，1 次）
arm1_active = 48*d_step*5 = 0.312849840047420 s
arm1        = (arm1_active/0.25)*1.20 = 1.501679232227616 s ; deadline = 2 s ; supervision = 52 s
# 实际工作：1 次 forward（16×2 固定批，32 个 C0 槽）→ 相对 48×5 的预留超额 240 倍

# 阶段（冻结口径）
phase_wall = 9*450 + 1*2 + 47.605202459 = 4099.605202459 s
phase_cap  = 14400 s → headroom = 10300.394797541 s
# 重算 delta：updates 0 / estimate 0.0 / deadline 0 / arm1 0.0 / arm1_deadline 0 / phase_wall 0.0

# 事后评测的墙钟（未登记为调用量；只有 CLI 硬墙钟）
每 run  nominal = PREP_BUDGET["eval"] = 300 s      # 子进程硬超时
每 run  账本预留 = min(120, max(10, 0.5*300)) = 120 s   # worker.py:440
9 run   nominal = 2700 s ; 9 run 账本预留 = 1080 s
静态检查：4099.605 + 1080 = 5179.605 ≤ 14400
          4099.605 + 2700 = 6799.605 ≤ 14400
```

**运行账（预算预留 vs 实际完成）**

| 项 | 预留 / 冻结值 | 实际完成 |
| --- | --- | --- |
| 9 次训练 run | estimate 359.931 s、deadline 450 s、supervision 500 s，各 run 合计按冻结 deadline 4,050 s 计 | **0 次**（本卡不训练，无真账本写入） |
| 1 次 D 候选 | estimate 1.501679 s、deadline 2 s、supervision 52 s | **0 次** |
| 9 次事后评测 | 每 run CLI 硬墙钟 300 s、账本预留 120 s；调用量 611/1492/800/3500 为 P19 实测 | **0 次**（未跑真实 eval） |
| 检查点身份 | 冻结 5 个 update 点 0/439/878/1755/3510 | **未产生**（无训练）；仅作计数 |
| 本卡 CPU 脚本 | 2 个脚本、2 次运行 | 各 1 次，RC=0，stderr 0 字节 |

**4 h 与评测的关系（F3 的正确口径）**

- **定义上已包含**：两处 phase 守卫都把 `store.list_runs()` / `ledger.store.list_runs()` 的全部 run 求和，注释明确写 “Include auxiliary eval/verify reservations / including auxiliary eval/verify runs”。
- **eval 自己会进同一账本**：`worker.py:435-440` 在 eval 分支 `open_aux_run(mode="eval", wall_budget_seconds=budget)` 并 `reserve(..., min(120, max(10, 0.5*budget)))`。
- **但执行边界要写清**：phase 守卫只在 **train** 路径（`worker.py:368`、`commands.py:737`）复查；eval 分支不复查 phase cap。因此“4 h 已含评测”是**账本/定义层面**成立，评测时的硬约束仍是**每次 300 s**。
- **账本边界仍是 r6 缺陷**：守卫读的是 `output_root/control.sqlite3` 这个 card-local 账本；换 output root 是否重置预算，r5 没有解决，`S1-R6-DECISION.md` 第 1 条要求锚到中央 RunStore。r2 **不声称**已修。
- 9×300 nominal 是“每次硬墙钟 × 9”的上界写法，不是已测耗时；实际 MLX 评测墙钟 **未知/待测**。9 次 300 s 静态上放得进 4 h 余量，但“放得进”不等于“跑得完”。

## 6. 帧分解（F6）

| 数 | 分解 | 是否自洽 |
| --- | --- | --- |
| 1703 | 950 topology stop_frames + 700 few-shot **transitions** + 53 m2 stop_frames | ❌ 混合口径（k=1 崩溃假设不崩） |
| 1503 | 750 topology **transitions** + 700 few-shot transitions + 53 m2 stop_frames | ❌ 混合 |
| 1903 | 1100 repaired few-shot stop_frames + 750 topology transitions + 53 m2 stop_frames | ❌ 混合 |
| **1003** | 950 + 0 + 53 | ✅ as-coded 实测 |
| **2103** | 950 + 1100 + 53 | ✅ repaired 实测（P19） |
| **1492** | 750 + 700 + 42 | ✅ repaired 单步 forward（P19） |

P15 的 “611 次 / 1703 帧” 中，**611 次与实测一致**；**1703 帧是混合数**，不能作为“帧数”引用。r1 试图用 1503/1903 替代 1703 也不成立（同样混合）。r2 统一为 1003 / 2103 / 1492 三个自洽量。

## 7. k 覆盖、support/query 与标签平衡（诊断）

### 7.1 覆盖（r2 独立纯 Python 复算，与 P15/P16/P19 一致）

| k | 有 support+query 的世界 | query 数 | family 构成 | query 目标 cell 已在记忆内 | 恒定“报真”基线 | 恒定“报假”基线 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 200 | 750 | 4×50 | 0（0.0%） | 0.400 | 0.600 |
| 1 | 200 | 550 | 4×50 | 350（63.6%） | 0.454545 | 0.545455 |
| 2 | 150 | 350 | nav/e3/time（丢 relation） | 200（57.1%） | 0.571429 | 0.428571 |
| 4 | 50 | 100 | **只有 navigation** | 50（50.0%） | **1.000** | 0.000 |
| 8 | **0** | 0 | — | — | 无样本 | 无样本 |

`reports/V9-P18/r2/analysis/independent_truth_check.json` 与 P19 的 `k_coverage_reproduced` 逐项相等（`metrics.json → diagnostic_baselines.cross_check_vs_p19.matches=true`）。**constant 基线只作诊断**，不替代冻结 accuracy。

### 7.2 support/query 是否跨 episode

- **不跨**：`few_shot_report` 对每个 sequence（= 一个 episode = 一个 world，`rounds_per_world=1`）独立调用 `metrics.split_support_query`，support/query 都取自同一 episode 的连续前缀/后缀；`by_world` 也按 episode 记账。
- **但“held-out”只是时间续段**：query 是 support 前缀的直接续段，目标 cell 只有 50%–63.6% 在 support 记忆内；一半左右的 query 目标在写记忆时**物理上尚未访问**，真阳在结构上不可达。
- **且 support 少写一条**：`stop=support[-1]+1` 是排他帧界，现状 k=2 只写 1 条、k=4 只写 3 条；k=1 直接崩。修法为 `stop=support[-1]+2`（即 k+1），此时执行 k 条 transition、query 起点不变、support 与 query 不重叠。该修复会改变 `evaluation.py` 源码身份，必须新冻结 + 非作者复核，**不在本卡范围**。

### 7.3 标签平衡（family 分解，仅诊断）

| family | 世界 | 每 episode 步数 | transitions | stay | adjacent | 每 episode distinct cell |
| --- | --- | --- | --- | --- | --- | --- |
| navigation | 50 | 7 | 300 | 0 | **300** | 6 |
| e3_identity | 50 | 5 | 200 | **200** | 0 | 1 |
| time | 50 | 4 | 150 | **150** | 0 | 1 |
| relation | 50 | 3 | 100 | **100** | 0 | 1 |

- navigation 全正类、其余三族全负类 → 逐 family 永远没有两类，`balanced_accuracy` 分支不触发。
- 合并 k 曲线的类别构成随 k 变（k=4 只剩 navigation），**不能读成“记忆越多越好”**。
- 因此 fusion accuracy 只能作“原始值 + n + 缺测”保留；有解释力的报法是**分 family 的覆盖率 / 误报率**，且必须登记为新 metric id 或正文定义（F5）。

## 8. 冻结指标与选项 A（不是零变更）

冻结指标（prereg `metrics[3]`）：`few_shot_unseen_transition` = 写 k∈{0,1,2,4,8} 条 support transition（不更新参数）后预测 held-out transitions，报 **accuracy and displacement error vs k**。

**选项 A：保留冻结数据 / k / 分区，只报有样本的结论；缺测保持缺测**

- **A 不是零变更**：把报出量从 accuracy 换成 coverage/FPR 就是改冻结定义。正确形态是：
  1. **原值照算照存**：accuracy / displacement error 按 k 逐个记，带 n；k=8 与 k=4 的缺失 family 记 `insufficient_data`（不填 0、不填满分）。这些值需要**真实 eval**，而真实 eval 当前被 k=1 崩溃（以及 `probe_graph` TypeError）阻断 → 必须先修代码、新冻结、非作者复核。
  2. **另附（不替代）**：family 拆分（§7.3）、constant 基线（§7.1）——只作诊断。
  3. **coverage / FPR**：作为**新 metric id** 或登记过的报告说明；不得替换 `few_shot_unseen_transition`。
- **前置条件**：k=1 stop 边界修复并重冻结；`query_limit=8` 登记或从代码路径移除；`probe_graph` 的真实后端修复（r6 裁决第 3 条）。
- **代价**：0 新训练、0 新数据、0 新 GPU；CPU 修复 + 重冻结 + 非作者复核。

## 9. 选项 B（未来另一条证据线；逐项需用户批准）

| # | 精确项 | 代价 / 状态 |
| --- | --- | --- |
| B1 | 新数据集批：新 plan / 新 seed → **新 dataset_digest = 新实验身份**；200 世界 × ≥10 packet；按 family 分层，保证每 family 每世界 ≥9 transition（k=8 需要 8 support + 1 query） | 生成成本 **未知/未测**；登记上限 spec 300 s / CLI 600 s |
| B2 | 登记**实测**评测调用量：175 窗口 batch、611 序列前向、1492 单步 forward、800 probe_graph、3500 encode、D 1 次 C0 forward | 来源 `measured_non_author`（P19） |
| B3 | 在换算墙钟前，先测 MLX batch-1 单步 forward / encode / probe_graph 的单位耗时 | **未知/未测**；不得用 CPU 替身或 batch-16 单步时长外推 |
| B4 | 评测墙钟的**余量分配**（4 h 已含 eval，不是“是否计入”的问题） | 静态上 1080/2700 s 均 < 10,300.395 s 余量；实际墙钟未知；每次 300 s 硬墙钟 |
| B5 | 修订 `held-out` 语义：时间续段 vs 空间未访问 cell，二者是不同科学主张，不能共用一个 id | 需决策 |
| B6 | 登记 `query_limit=8`（当前只在代码）；决定 checkpoint 0（训练前）在曲线中的地位 | 需决策 |
| B7 | M2 探针选点固定化：当前按 episode_id（UUID）字典序取前 5（time/time/navigation/relation/e3_identity，步数 4/4/7/3/5），既非随机也非分层 | 需决策 |

**B 的代价**：新数据生成成本 **未知**；MLX 评测墙钟 **未知**；训练是否重跑需单独批准（本卡不申请）。B 不动现分区、不改 k 与训练步数、不改原实验，只是并行开一条能支撑 k=8 的新证据线。

## 10. `eval_batches=48` 的定义矛盾（保留）

| 位置 | 48 的含义 | 是否覆盖真实评测 |
| --- | --- | --- |
| `runtime.window_probe` | 批上限 `min(35,48)=35`，**从不生效** | 否 |
| `prereg.estimate_budget` | 训练期探针成本 `48×5×step = 1.670989920021384 s`，计入 359.931 s 训练 estimate；相对实际 35 批超额 48/35=1.371 倍 | 否（只覆盖训练期探针） |
| arm1 成本 | `48×5×d_step = 1.501679232227616 s`，而 arm1 实际 1 次 forward → **240 倍**超额预留 | 否 |
| 真实 eval 套件 | 冻结文档**没有任何**批数/秒数/额度登记 | — |

真实评测是 **175 窗口 batch + 611 + 1492 + 800 + 3500**（P19 实测），比 `48` 大一个量级。`48` 只能当训练期探针的批上限兼成本参数，**不能当评测调用量的批准依据**。另有静默截断风险：若 dev 窗口数 > 48×16 = 768，`window_probe` 只评前 768 个窗口，日志仍只显示 `batches=48`。

## 11. 保留的负面证据与未验证项（不当作通过）

1. **k=1 崩溃**：`evaluation.py:331` `step_sequence(stop=support[-1]+1)` → `frames=1 < 2` → `BackendError("a sequence probe needs at least two frames")`。k=0 已算完但整个 `_evaluate_arm` 抛错、结果不落盘；9 次 arm×seed 评测都会在同一处中断。
2. **support 少写一条**：`stop` 是排他帧界，k=2 写 1 条、k=4 写 3 条。
3. **`probe_graph` 真实后端缺陷（r6 裁决第 3 条，一级只读 CPU 探针发现）**：非空 metric map 上把 numpy flat index 当 `(r,c)` 解包 → `TypeError: cannot unpack non-iterable numpy.int64 object`；未导入 MLX。本卡未复现、未修，只保留其阻断性。
4. **修复态计数来自计数替身**：611/1492/800 是调用边界计数，不等于生产 `MlxBackend` 能跑完，也不等于能力结果。
5. **MLX 单位耗时未知**：batch-1 单步 forward / encode / probe_graph 都未测；不把 CPU 替身或 batch-16 时长外推为 MLX 实测。
6. **新数据成本未知**：47.605 s 只覆盖旧计划；新计划每世界建图成本未测。
7. **账本边界未修**：phase 守卫读 card-local `output_root/control.sqlite3`；跨 root 重置预算属 r6，r5 不声称解决。
8. **未验证**：`_evaluate_arm` 的 RunStore 绑定段/checkpoint 重载/参数 SHA 校验；`arms.py` 的 MLX 数值路径；M2 选点稳健性；`query_limit=8` 与 held-out 语义的登记状态。
9. **本卡不自我验收**；`completed` 与报告通过均不代表能力通过。

## 12. 交回统筹（需一级决定）

1. 是否接受 F1–F9 的**闭合方式**（对外数字 611/1492/800/3500/175；provenance 标签；4 h 已含 eval 的口径；新数据成本未知）。
2. 是否接受 **k=1 stop 修复 + `probe_graph` 真实后端修复** 为阻断级代码修复，开新代码卡并走新冻结 + 非作者复核（本卡不申请）。
3. 是否接受 **选项 A** 的报出形态：冻结指标原值 + n + `insufficient_data`；family/constant 仅诊断；coverage/FPR 另立 metric id。
4. 是否把 **选项 B 的 7 项**放入用户批准流程；其中 B1 是“新 dataset_digest = 新实验身份”，不是参数微调；B3/B1 的成本只能写“未知/待测”。
5. P20 独审 draft 是否在 r2 正式交报、一级封 r2 `REPORT.md` SHA 后转 ready。**本卡不写批准行、不改 k/世界/分区/训练步数/eval 额度，不构成运行授权。**

## 13. 产物清单（全部在 `reports/V9-P18/r2/`）

- `REPORT.md`：本报告。
- `metrics.json`：r2 结构化结果（身份/SHA、预算重算、provenance 计数、帧分解、9+9+1 合计、phase 边界、48 批矛盾、数据成本、冻结指标、诊断基线、A/B、F1–F9 闭合表、未测项）。
- `analysis/independent_truth_check.py` / `analysis/independent_truth_check.json`：**新实现**的纯真值复算（不 import s1 包），用于交叉核对 k 覆盖/标签平衡/constant 基线。
- `analysis/build_r2_metrics.py`：r2 `metrics.json` 生成脚本（预算与合计全部程序计算）。
- `analysis/input_identity.json`：r1 14 项冻结输入 + P19 实测产物 + P20 draft 的 SHA 审计。
- `logs/independent_truth_check.{out,err}`、`logs/build_r2_metrics.{out,err}`：两次运行的完整 stdout/stderr（err 均 0 字节）。
