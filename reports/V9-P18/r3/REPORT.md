# ainerzero.V9.P18 r3：S1 评测调用量与 k 支持覆盖（冻结值不改的预算决策材料）

角色：executor（二级执行层）；本棒 ID：`deepseek-v41f-r3k9`（DeepSeek V4.1 Flash；skills=text/code/math）；日期：2026-10-22
任务状态：reported；实验状态：**未执行**（纯 CPU 工程统计与独立复算；无训练、无真实评测、无 MLX 导入、无数据生成、未读 final）
修订依据：`coord/P18-R3-DECISION.md`（sha `282cc0cd…`）、`coord/P20-EVIDENCE-ADDENDUM.md`（sha `a3b66ba0…`）、`reports/V9-P19/REPORT.md`（sha `f27b401b…`）、`reports/V9-P20/workbuddy-q7t2/REPORT.md`（sha `118abfac…`）
文件范围：只写 `reports/V9-P18/r3/`。r1 / r2 / P19 / P20 / 冻结 r5 快照 / 数据集 / 源码**全部只读、零覆盖**（§2 逐项 SHA 复核）。

---

## 0. 摘要（给一级取舍）

1. **D1 已闭**：对外数字仍是 **611 / 1,492 / 800 / 3,500 / 175 / D 1**。旧值 **612 / 1292 / 600** 的三个出处全部保留并给出**读文件得到的行号**：r1 `REPORT.md:275`（612/1292）与 `:243`（600）、r1 `metrics.json:447`（1292）与 `:449`（600）、r1 `analysis/build_metrics.py:197` / `:199`。r2「r1 的 metrics.json 本身是 611/1492/800」这句只对**结构化数值块**成立，对文件整体不成立——本卡按此更正。
2. **D2 已闭且撤回过度推断**：同一 dataset digest 在冻结文档里有两个 `generation_seconds`（`data_identity`=**45.739918708000005**，`timing.smoke`=**47.605202458999884**）。当前 `dataset_manifest.json` 的值是 **45.7399…**（等于 `data_identity`），清单 `created_unix`=1792576623.88（12:57:04），smoke 记录 1792572559.63（11:49:19），prereg 冻结 1792614732.81（23:32:12）——**两个值在冻结前已共存**。本卡**撤回** P19 F9 与 r2 的「冻结后被改写」断言：无 diff、无 git 历史（`artifacts/` 被 `.gitignore:15` 忽略），mtime 也不是不可篡改记录。**写入时刻与原因：未知。** `phase_wall` 取了较大的 47.605（保守），复算 delta 仍为 0.0。新数据成本**未知/未测**。
3. **D3 已闭**：611/1492/800/3500/175 全部绑定 **dataset digest `8234f2f3…83ad26`** + 旧 episode 形状（200 世界 / 950 packet / 每族 7·5·4·3 步 / `query_limit=8`）+ **P19 计数替身后端**。B1 任何新长 episode / 新 seed / 新 digest 都必须重算，旧值**不迁移**。D 候选（1 次 C0 forward / 32 槽）单列。新数据示意算式一律标 `illustration_arithmetic_only`、不实测、不登记为成本。
4. **D4 已闭并纠正 wall_seconds**：**300 s 标称**（`commands.py:42`）/ **350 s supervisor 超时**（`commands.py:200`，`+50`）/ **120 s 账本预留**（`worker.py:440`）三层分列，不再叫「300 s 硬墙钟」。**关键更正（P20 补充）**：phase 守卫读的是 `RunRecord.wall_seconds = max(0, effective_now − created_at)`（`lifecycle._record:392`），**不是** 120 s 的 `active_seconds`（另一个字段 `:391`）。所以 **9×120=1080 s 只是静态预留量，不是守卫实际读到的量、更不是已消耗墙钟**。4 h **本来就含评测**（守卫对同一 card-local 账本求和），「是否计入」不是待裁决项；守卫实际可见总量**未知**（依赖创建时刻与 P17 的 now 增长缺陷，该缺陷由 P15 r7 修，本卡不声称已修）。静态预留 / 监督上界 / 已发生账本 / MLX 实测四者分列，不宣称「够跑」或新的运行授权。
5. **D5 已闭**：M2 的 **11 / 42** 由脚本从 P19 已封存字段 `C_repaired_accounting_measured.component_split.m2_interference` **按 JSON 指针读取**，本卡**没有手写常数**，也不再宣称「nothing typed in by hand」。r1 确实在 `build_metrics.py:97` 硬编码了同一组值——值对、出处声明错。
6. **F1–F9 全部按 P19 关闭**，闭合方式见 §5；其中 F3 的伪问题已删除，F5 明确「选项 A 不是零变更」，F6 只保留 1003 / 2103 / 1492 三个自洽量。
7. **k 覆盖独立复现**（新实现，不 import 项目包）：k=0/1/2/4/8 → **200/200/150/50/0** 个世界，**750/550/350/100/0** 条 query；family 与 episode 长度 1:1 绑定（nav 7 步 300 transition、e3 5 步 200、time 4 步 150、relation 3 步 100）。与 P15 r5（`reports/V9-P9/r5/REPORT.md:111`）、P16（`0/200`、`50/200`）、P19 逐项一致。
8. **support/query 不跨 episode**：`split_support_query` 只在一个 episode 的 transition 区间内切分，`few_shot_report` 每个 sequence 从 `memory=None` 重建；每个 episode `round_index=0`、`rounds_per_world=1`。**但 held-out 只是时间续段**：k≥1 时大量 query 起点 cell 已在 support 记忆内（k=1 为 350/550=63.6%）。
9. **9 训练 / 9 评测 / 1 D 的预算算式全部复算，delta 全 0**：updates=3510、estimate=359.9312287726061、deadline=450、supervision=500、arm1=1.501679232227616（deadline 2、supervision 52）、phase_wall=4099.605202459、headroom=10300.394797541。
10. **`eval_batches=48` 仍是定义矛盾**：它是 window_probe 批上限（35<48 从不生效）、训练期探针成本项（1.670989920021384 s，相对真实 35 批超额 1.371 倍）、arm1 成本项（**240 倍**超额预留）；真实评测套件在冻结文档里**没有任何批数/秒数/额度登记**。
11. **负面证据全部保留**：k=1 崩溃、support 少写一条、`probe_graph` 真实后端 TypeError（r6 裁决第 3 条）、修复态计数来自替身、MLX 单位耗时未知、账本 card-local 未修。
12. **r3 新发现（不改任何数字）**：P19 封存件 `C_repaired_accounting_measured.per_k_calls` 与它自己的 `per_run_total` 矛盾（该子块仍是 as-coded 语义：k=1 崩、k=2/4 写 k−1 条）。结论：**repaired 列只能用 `per_run_total` 与 `component_split`，per-k 子块不得引用**；611/1492/800/3500 已由本卡从 dev 覆盖独立算出并完全对上。
13. **两个可审阅选项**：A（保留冻结数据/k/分区，只报有样本的结论，缺测不当通过，代价 0 训练 0 数据 0 GPU）与 B（未来另批长 episode 数据 + 登记评测预算，7 项逐条列需用户批准的精确项，成本未知）。
14. 本卡**不自我验收**，不写批准行，不改 k / 世界 / 分区 / 训练步数 / eval 额度 / 阈值 / 冻结参数；结论仅供一级取舍。P20 独审须在一级封 r3 `REPORT.md` SHA 后才 ready。

---

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# 注册 / 领卡 / 心跳（摘要）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent deepseek-v41f-r3k9 --tier 2 \
  --kind "DeepSeek V4.1 Flash" --profile-file <profile.json>        # benchmarks=[]
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.P18 \
  --agent deepseek-v41f-r3k9 --token <预留令牌>                      # RC=0
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay heartbeat ainerzero.V9.P18 --agent deepseek-v41f-r3k9 --msg "…"

# 两个新脚本；输出根必须显式给出，不写 /tmp、不写 r1/r2
BASE=/private/var/folders/zv/…/T/opencode/v9p18_r3_iso
env -i PATH=/usr/bin:/bin:/usr/local/bin HOME="$BASE/home" TMPDIR="$BASE/tmp" \
    PYTHONDONTWRITEBYTECODE=1 V9P18R3_OUT="$BASE/run_5" \
    .venv/bin/python reports/V9-P18/r3/analysis/r3_dev_coverage.py \
    > reports/V9-P18/r3/logs/r3_dev_coverage_run5.out 2> …/r3_dev_coverage_run5.err
env -i … V9P18R3_OUT="$BASE/run_5" V9P18R3_COVERAGE="$BASE/run_5/dev_coverage.json" \
    .venv/bin/python reports/V9-P18/r3/analysis/build_r3_metrics.py \
    > reports/V9-P18/r3/logs/build_r3_metrics_run5.out 2> …/build_r3_metrics_run5.err
# 交付目录与第二个新目录各跑一遍（同一脚本、不同输出根），比对字节
env -i … V9P18R3_OUT="$PWD/reports/V9-P18/r3/products" …
env -i … V9P18R3_OUT="$PWD/reports/V9-P18/r3/products" V9P18R3_COVERAGE=…/dev_coverage.json …

# 写路径守卫的负向测试（故意重跑，应当被拒绝）
env -i … V9P18R3_OUT="$PWD/reports/V9-P18/r3/products" … r3_dev_coverage.py   # 拒绝
env -i … V9P18R3_OUT="$PWD/reports/V9-P18/r3/products" … build_r3_metrics.py  # 拒绝
```

- 两次运行 **RC=0、stderr 全 0 字节**（`logs/*.err`；唯一的 220 字节来自上面两条**故意的**守卫负向测试）。
- 本轮**没有**运行：`--mode train/eval/smoke/data`、任何 MLX 前向/梯度/优化器、final 分区读取、数据生成、模型下载/安装、资源基线重设、git commit/push、批准行写入、RESEARCH_LOG 改写。
- 本轮**没有**重跑 r1 的 `count_calls.py` / `truth_stats.py` / `build_metrics.py`，也**没有**重跑 P19 的 `independent_checks.py`；没有复用 `/tmp/v9p18_iso`；r1 / r2 / P19 / P20 任何产物**零覆盖**。
- 隔离：`HOME` / `TMPDIR` / `PYTHONDONTWRITEBYTECODE` 指向私有临时根；两个脚本的**唯一**输出根来自 `--out` 或 `V9P18R3_OUT`。

## 2. 身份、SHA 与源漂移核对

| 项 | SHA256（前 12） | 与既有记录是否一致 |
| --- | --- | --- |
| 冻结 r5 `evaluation.py` | `92d8de4a6551` | ✅ 与 P19/r2 一致 |
| 冻结 r5 `runtime.py` | `a99346522f29` | ✅ |
| 冻结 r5 `metrics.py` | `e1c36b657794` | ✅ |
| 冻结 r5 `worker.py` | `4174187473cd` | — |
| 冻结 r5 `commands.py` | `48b3fb48cf4b` | — |
| 冻结 r5 `spec.py` | `beedc9482b8d` | — |
| 冻结 r5 `prereg.py` | `d441b84e1c52` | — |
| 预注册 `pre_registration.json` | `895bb3676cd3` | ✅ |
| 数据集 `dataset_manifest.json` | `5cbd65225c84` | ✅ 当前 `generation_seconds=45.739918708000005` |
| `truth/development.jsonl` | `76b986495229` | ✅ |
| r1 `REPORT.md` / `metrics.json` | `0b33e29fbd2e` / `71bc8c38eb27` | ✅ **未改** |
| r2 `REPORT.md` / `metrics.json` | `86a13488b1f7` / `ad32d483508a` | ✅ **未改** |
| P19 `REPORT.md` / `metrics.json` | `f27b401bcf9a` / `4dd5a018b39c` | ✅ **未改** |
| P19 实测载体 `independent_checks.json` | `d6f741d4ec83` | ✅ **未改** |
| P20 `REPORT.md` | `118abfac9a5e` | ✅ 与 `coord/P20-result.md` 同字节 |
| 当前 `src/ainerzero/runtime/lifecycle.py` | `22ded55ce136` | ⚠️ 见下 |

**源漂移结论：未发现漂移。** 开工先核当前 SHA，全部与 P19/P20 记录一致，故继续写。

**一处必须声明的身份缺口**：`lifecycle.py` **不在** r5 快照内（快照只含 `experiments/s1/**` 与 `cli.py`）。本卡引用的 `RunRecord.wall_seconds` 语义来自**当前工作树**的 `src/ainerzero/runtime/lifecycle.py`（sha `22ded55ce136`），它是 r5 worker 实际调用的通用模块，但**不是被 r5 冻结钉住的那一份**。因此 D4 的「守卫读 now−created」是按当前通用模块语义 + P20 补充裁决表述的；若该通用模块在 r5 冻结时点不同，这条需要一级再核。本卡不用它改变任何数字。

## 3. 写路径审查（决策 M1）

先审写路径，再运行：

| 脚本 | 写入点 | 规则 |
| --- | --- | --- |
| `r3_dev_coverage.py` | `$OUT/dev_coverage.json`、`$OUT/run_meta.json` | `$OUT` 必须由 `--out` 或 `V9P18R3_OUT` 给出；**目录存在且非空即拒绝** |
| `build_r3_metrics.py` | `$OUT/metrics.json`、`$OUT/run_meta.json` | 同上，但允许复用同一 run family 上一阶段的两个文件；**`metrics.json` 已存在即拒绝**，目录含其它文件即拒绝 |

- 两个脚本都**没有**硬编码输出根、**没有** `/tmp` 默认值、**没有**指向 `reports/V9-P18` 或 `reports/V9-P18/r2` 的路径。
- 负向测试留档：`logs/guard_test_coverage.err`（`refusing to run: output directory is not empty`）、`logs/guard_test_metrics.err`（`refusing to run: metrics.json already exists`）；两次拒绝后 `products/*.json` 的 SHA **未变**（`551d9b95…` / `0ba67a8e…`）。
- **可重现性**：`dev_coverage.json` 与 `metrics.json` 是**字节确定**的（无时间戳、无输出根路径）。两个不同新目录（`$BASE/run_5` 与 `reports/V9-P18/r3/products`）产出：

  | 产物 | run_5 | products | 一致 |
  | --- | --- | --- | --- |
  | `dev_coverage.json` | `551d9b954736…` | `551d9b954736…` | ✅ |
  | `metrics.json` | `0ba67a8e9d9a…` | `0ba67a8e9d9a…` | ✅ |

  另外 `dev_coverage.json` 在 4 个独立目录（run_1/2/4/5）全部同 SHA。
- `run_meta.json` 记录真实输出根、argv、时间与解释器版本，**明确排除**在字节一致声明之外（审计用）。
- 数据形状与输出根元数据：`dev_coverage.json → shape`（episodes/steps_total/transitions_total/`steps_total_equals_manifest_packets=true`、每族步数直方图、`max_transitions_per_world=6`）与 `run_meta.json`（output_root）。

## 4. D1–D5 逐条

### D1（F1，中）数值对，历史出处必须完整

对外数字：**611 序列前向 / 1,492 单步 forward / 800 probe_graph / 3,500 encode / 175 窗口 batch（35×5）/ D 1 次 C0 forward**。

旧值 612 / 1292 / 600 的三处出处（行号由脚本读文件得到，非手写）：

| 出处 | 行 | 原文要点 |
| --- | --- | --- |
| r1 `REPORT.md` | 275 | 「窗口 batch 35×5、序列前向 **612**、单步 forward **1292**、encode 3500、probe_graph 800、D 1」 |
| r1 `REPORT.md` | 243 | 「3500 次 `encode` 与 **600** 次 `probe_graph` 从未被测过」 |
| r1 `metrics.json` | 447 / 449 | `unmeasured`：「611 eval calls, **1292** forwards」/「probe_graph cost (**600** calls)」 |
| r1 `analysis/build_metrics.py` | 197 / 199 | 同一句 1292 / 600 |
| r1 `metrics.json` → `/eval_run_accounting_if_k1_repaired` | — | **结构块本身早已是 611 / 1492 / 800 / 3500** |

**更正**：r2 的「r1 自己的 metrics.json 早已存的是 611/1492/800」只对**结构化数值块**成立；同一个文件的 `unmeasured` 文案里就有 1292 与 600，`build_metrics.py` 也有。本卡把三处全留档，不改原文、不删历史。差值：612−611=**+1**、1292−1492=**−200**（200 恰好是 k=1 的 200 个世界，像是漏了一项）。

### D2（F9，中高）两个 generation_seconds：只报事实

| 事实 | 值 |
| --- | --- |
| 当前 `dataset_manifest.json → generation_seconds` | **45.739918708000005** |
| 清单 `created_unix` / mtime | 1792576623.88 → **2026-10-21 12:57:04** |
| prereg `data_identity.generation_seconds` | **45.739918708000005**（与当前清单相等） |
| prereg `timing.smoke.data_generation_seconds` | **47.605202458999884** |
| smoke `created_unix` | 1792572559.63 → **11:49:19** |
| prereg `created_unix` / mtime | 1792614732.81 → **23:32:12** |
| `artifacts/` 是否有 git 历史 | **无**（`.gitignore:15` 忽略 `artifacts/`） |

时间线：smoke 11:49 记录 47.605 → 清单 12:57 记录 45.7399 → prereg 23:32 冻结并同时写入两个值。**两个值在冻结前就已共存**。

**明确不做的主张**：①不说「清单字段在冻结后被改写」（无 diff、无历史，且当前清单根本不是 47.605）；②不用 mtime / `created_unix` 倒推写入时刻；③不说 47.605 是 smoke 计时（`smoke.py` 只是抄 `manifest["generation_seconds"]`）。

**保留的结论**：冻结文档对同一 digest 内部不一致（两个值），`phase_wall` 取较大的 47.605（保守），复算 delta=0.0。P19 F9 与 r2 的因果断言在此**撤回**。

**新数据成本**：`unknown_not_measured`。旧计划 10,450 packet / 47.605 s → **4.555522 ms/packet**；2000 packet 的 packet 速率下界 **9.111044 s**（只含 packet 成本，不含每世界建图，**不是成本估计**）。登记上限：`spec` 300 s / CLI `PREP_BUDGET["data"]` 600 s。

### D3（高）调用量必须绑 digest；旧值不迁移

绑定信息（`metrics.json → d3_call_counts.binding`）：`dataset_digest=8234f2f3…83ad26`；200 世界 / 950 packet / 750 transition；每族步数 nav 7、e3 5、time 4、relation 3；`max_transitions_per_world=6`；`query_limit=8`（**未在 prereg 登记**）；后端为 **P19 计数替身 + 1 行 stop 修复**。

| 组件 | as-coded（实测） | 修复 k=1 后（P19 实测，非作者） | r3 独立算式 |
| --- | --- | --- | --- |
| 窗口 forward_loss | 175 | 175 | 5 检查点 × ceil(550/16)=35 |
| `step_sequence` 调用 | 212 | **611** | 200 + (200+150+50) + 11 = 611 |
| 单步 forward | 792 | **1,492** | 750 + (200×1+150×2+50×4) + 42 = 1,492 |
| `probe_graph` | 400 | **800** | 200 + (200+200+150+50) = 800 |
| `encode` | 1,500 | **3,500** | 2×(750+550+350+100) = 3,500 |

**四项独立算式与 P19 实测完全相等**（`matches_p19_measurement` 全 true）。注意 400→800 的差不是修复带来的：在**同一次** `few_shot_report` 顺序执行里（k 顺序 0,1,2,4,8），k=1 一崩，k=2/k=4 根本没跑到——as-coded 的 212 = 200 topology + 1 次崩溃调用 + 11 m2 就是证据；封存件里的 as-coded `per_k_calls` 是逐 k 单独测的，不能相加。

**B1 示意算式（非实测、不登记为成本）**：若 200 世界 × 9 transition、family 不变、`query_limit=8`，则 topology 200 调用 / 1,800 transition、few-shot 800 调用 / 3,000 transition、query 5,800、probe_graph 1,200、encode 11,600、`step_sequence` 合计 **1,011**、单步 forward 合计 **4,842**、stop_frames 合计 **5,653**、窗口 batch **未知**。P20 早前那版示意把 few-shot 换成新形状却保留旧的 750 topology 项，混了两个数据集，本卡已按同一假设重算全部项。

**D 候选单列**：1 次 forward / 固定批 `(16,2,8)` = 32 个 C0 槽，**不并入**评测总量。

### D4（高）三层墙钟 + wall_seconds 更正

| 层 | 值 | 源码 |
| --- | --- | --- |
| CLI 标称预算 | **300 s** | `commands.py:42` `PREP_BUDGET["eval"]` |
| supervisor 超时（进程级硬超时） | **350 s** | `commands.py:200`（`budget + spec.TIMING["supervision_extra_seconds"]`=50）；`commands.py:227 subprocess.run(timeout=…)` |
| 账本预留 / 记账 | **120 s** | `worker.py:440` `active_seconds=min(120, max(10, 0.5*budget))` |
| phase 守卫可见墙钟 | **未知** | `worker.py:370-376` / `commands.py:743` 求和 `r.wall_seconds` |
| eval 分支复查 phase cap | **无** | `worker.py:425-453` 无 `phase_budget_exceeded` |

**核心更正（P20 补充）**：`RunRecord.wall_seconds` 由通用 lifecycle `_record` 给出 `max(0, effective_now − created_at)`，而 120 s 是**另一个字段** `reserved_active_seconds=row["active_seconds"]`。两处都由正则核对通过（`metrics.json → d4_eval_wall_layers.layers.phase_guard_visible_wall.source_semantics_verified_by_regex`，三项全 true）。

因此：

- **9×120 = 1,080 s 只是静态预留量**，不是守卫实际读到的量，也不是已消耗墙钟；
- 守卫实际可见总量依赖每个 run 的 `created_at` 与时钟，**未知**；P17 的 now 增长缺陷使该数不可靠，修复属 P15 r7，本卡**不声称已修**；
- 「4 h 是否包含评测」**不是问题**：两处守卫都对同一 card-local 账本的全部 run 求和，注释明写包含 auxiliary eval/verify；
- 评测时真正的进程级硬约束是**每次 350 s**，不是 300 s，也不是 120 s。

**静态检查（只作算术，不是承诺）**：

```
phase_wall (冻结)                     = 4,099.605202459 s
+ 9 × 300 (标称)                      = 6,799.605202459 s  ≤ 14,400
+ 9 × 350 (监督超时)                  = 7,249.605202459 s  ≤ 14,400
+ 9 × 120 (账本预留)                  = 5,179.605202459 s  ≤ 14,400
最坏静态上界 9×450 + 9×350 + 2        = 7,202 s            ≤ 14,400
```

四条都在 4 h 内，但「放得进」**不等于**「跑得完」：MLX 单位耗时未知，账本 card-local（换 output root 即空库）属 r6 未修。

### D5（中）M2 11 / 42 从封存件读取

- 来源：`reports/V9-P19/analysis/independent_checks.json`（sha `d6f741d4ec83…`）→
  `C_repaired_accounting_measured.component_split.m2_interference`：
  `step_sequence_calls=11`、`single_step_forward_calls=42`、`step_sequence_transitions=42`、`step_sequence_frames=53`。
- 本卡脚本按上述 JSON 指针**读取**，`hand_typed_in_r3=false`；as-coded 块同值（`same_values_in_as_coded_block=true`）。
- r1 `build_metrics.py:97` 确实硬编码了同一组 11/42 → 值对、出处声明错；本卡不再出现「nothing typed in by hand」这类声明。
- **r3 新发现**：该封存件的 `C_repaired_accounting_measured.per_k_calls` 子块仍是 as-coded 语义（k=1 `crashed_at_world=1`、`step_sequence_calls=1`；k=2/k=4 的 transitions 仍是 150/150 = 每世界 k−1 条），与它自己的 `per_run_total`（611/1492，要求 k=1 贡献 200 次调用）矛盾。**处置**：repaired 列只引用 `per_run_total` 与 `component_split`；per-k 子块不引用。这**不改变任何数字**，611/1492/800/3500 已由本卡从 dev 覆盖独立算出并完全对上。此项留档给一级与下一棒复核，**不静默修补**。

## 5. F1–F9 逐条闭合

| # | P19 严重度 | r3 状态 | 怎么闭的 |
| --- | --- | --- | --- |
| F1 | 严重 | 已闭 | 对外 611/1492/800/3500/175；612/1292/600 三处出处全留档（§4 D1） |
| F2 | 严重 | 已闭 | `as_coded`（作者 r1 插桩 + P19 字节复现）/ `repaired_k1`（**P19 非作者实测**）/ `projected`（已作废，仅审计）分块，每块带 provenance |
| F3 | 严重 | 已闭 | 删去「评测是否计入 4 h」伪问题；300/350/120 三层分列；守卫真实输入写明（§4 D4） |
| F4 | 严重 | 已闭 | 新数据成本 `unknown_not_measured`；47.605 s 是旧计划清单字段，不再称实测（§4 D2） |
| F5 | 中 | 已闭 | 选项 A 明写**不是零变更**；冻结指标定义/n/缺测保留，**数值 pending_real_eval**（r2 的 `original_..._values_retained=true` 易读成「已有数值」，已改） |
| F6 | 中 | 已闭 | 1703/1503/1903 标 hybrid；只留 **1003**（as-coded stop_frames）、**2103**（repaired stop_frames）、**1492**（transitions）三个自洽量 |
| F7 | 中 | 已闭 | M2 11/42 由 JSON 指针读取（§4 D5） |
| F8 | 轻 | 已闭 | `probe_graph=800`（200 topology + 600 few-shot）；600 只是 few-shot 一半 |
| F9 | 轻 | 已闭（含撤回） | 「冻结后被改写」撤回；只报字节与时间戳事实 + 原因未知（§4 D2） |

**帧分解（F6）**：

| 数 | 分解 | 自洽 |
| --- | --- | --- |
| **1003** | 950 topology stop_frames + 0（k=0 无 support；k=1 崩在写帧前）+ 53 m2 | ✅ as-coded 实测 |
| **2103** | 950 + 1,100（few-shot stop_frames，`stop=k+1`）+ 53 | ✅ repaired 实测（r3 算术亦得 2,103） |
| **1492** | 750 + 700 + 42 | ✅ 单步 forward |
| 1703 | 950 + 700（few-shot **transitions**）+ 53 | ❌ 混合（P15 `reports/V9-P9/r5/REPORT.md:124` 的「611 次 / 1703 帧」中，611 对、1703 是杂交数） |
| 1503 / 1903 | 见 `metrics.json → frames` | ❌ 混合 |

## 6. 训练期探针与事后评测分开计

| 项 | 每 run | 9 run 合计 |
| --- | --- | --- |
| 训练 optimizer update | 3,510 | 31,590 |
| 训练期探针窗口 batch（5 检查点 × 35） | 175 | 1,575 |
| 训练期探针帧槽 | 8,250 | 74,250 |
| 训练 forward batch 当量 | 3,685 | 33,165 |
| 评测窗口 batch | 175 | 1,575 |
| 评测 `step_sequence` | 611 | 5,499 |
| 评测单步 forward | 1,492 | 13,428 |
| 评测 `probe_graph` | 800 | 7,200 |
| 评测 `encode` | 3,500 | 31,500 |
| D 候选（arm1） | 1 forward / 32 C0 槽 | 1 / 32 |

训练期 5 检查点探针与 9 次事后评测是**两笔不同开销**，本表不混列；D 候选单列。

## 7. 预算算式（9 训练 + 9 评测 + 1 D；冻结值不改）

```
# 冻结输入（全部由脚本从 prereg / spec.py / commands.py / worker.py 解析，未手写）
step     = 0.0069624580000891 s      # smoke batch-16 forward+loss
d_step   = 0.0013035410001975833 s   # arm1 forward_loss step
duty     = 0.25 ; overhead = 1.20 ; checkpoints = 5
update_cost = 3*step = 0.0208873740002673 s
eval_batches = 48

# 训练 run（arm2/3/4 × seed 0/1/2 = 9 次）
raw_updates = floor((360*0.25/1.20 − 48*step*5) / update_cost) = 3510
eval_cost   = 48*step*5 = 1.670989920021384 s        # 训练期探针成本项
estimate    = (3510*update_cost + eval_cost)/0.25*1.20 = 359.9312287726061 s
deadline    = ceil(1.25*estimate) = 450 s ; supervision = 500 s

# D 候选（arm1，1 次）
arm1_active = 48*d_step*5 = 0.31284984004742 s
arm1        = (arm1_active/0.25)*1.20 = 1.501679232227616 s ; deadline = 2 s ; supervision = 52 s
# 实际工作只有 1 次 forward（32 个 C0 槽）→ 相对 48×5 的预留超额 240 倍

# 阶段（冻结口径）
phase_wall = 9*450 + 1*2 + 47.605202459 = 4099.605202459 s
phase_cap  = 14400 s → headroom = 10300.394797541 s

# 重算 delta（全部 0）
updates 0 / estimate 0.0 / deadline 0 / arm1 0.0 / phase_wall 0.0 / headroom 0.0

# 事后评测的墙钟（未登记为调用量；三层不同）
每 run  标称       = 300 s      # commands.py:42
每 run  监督超时   = 350 s      # commands.py:200（+50）
每 run  账本预留   = 120 s      # worker.py:440（active_seconds，非 wall_seconds）
9 run   300/350/120 = 2700 / 3150 / 1080 s
守卫实际可见量 = 未知（= Σ(effective_now − created_at)，非 120×9）
```

**运行账（预算预留 vs 实际完成）**

| 项 | 预留 / 冻结值 | 实际完成 |
| --- | --- | --- |
| 9 次训练 run | estimate 359.931 s、deadline 450 s、supervision 500 s | **0 次** |
| 1 次 D 候选 | estimate 1.501679 s、deadline 2 s、supervision 52 s | **0 次** |
| 9 次事后评测 | 标称 300 s / 监督 350 s / 账本 120 s；调用量 611/1492/800/3500 | **0 次**（未跑真实 eval） |
| 检查点身份 | 0 / 439 / 878 / 1755 / 3510 | **未产生**（无训练） |
| 本卡 CPU 脚本 | 2 个脚本 × 2 个输出根 + 2 次守卫负向测试 | 各 RC=0（负向测试按设计被拒） |

## 8. k 覆盖、support/query 范围与标签（诊断）

### 8.1 覆盖（r3 新实现，不 import 项目包）

| k | 有 support+query 的世界 | query | family 构成 | query 起点 cell 已在 support 记忆内 | 恒报真基线 | 恒报假基线 |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | 200 | 750 | 4×50 | 0（0.0%） | 0.400 | 0.600 |
| 1 | 200 | 550 | 4×50 | **350（63.6%）** | 0.454545 | 0.545455 |
| 2 | 150 | 350 | nav/e3/time（丢 relation） | 200（57.1%） | 0.571429 | 0.428571 |
| 4 | 50 | 100 | **只有 navigation** | 50（50.0%） | **1.000** | 0.000 |
| 8 | **0** | 0 | — | — | 无样本 | 无样本 |

与 P15 r5（`750/550/350/100/0`）、P16（`0/200`、`50/200`）、P19 逐项相等。**constant 基线只作诊断**，不替代冻结 accuracy。

### 8.2 support/query 是否跨 episode

- **不跨**。`metrics.split_support_query` 只返回**同一 episode** 的 transition 下标区间；`evaluation.few_shot_report` 每个 sequence 都从 `memory=None` 重建记忆，世界之间不携带；200 个 episode 的 `round_index` 全为 0、`rounds_per_world=1`，一个 episode 就是一个 world。脚本核对：`no_index_outside_episode=true`、`one_episode_per_world=true`。
- **但 held-out 只是时间续段，不是空间未访问**：k=1 时 350/550（63.6%）的 query 起点 cell 已在 support 记忆里；k=4 时 50/100。预测还要求**两端**都匹配上，`query_end_cell_in_support` 的计数也一并给出（k=1 为 350）。
- **as-coded 的 stop 少写一条**还会让记忆更小：`stop=k` 只写 k−1 条 support，此时能命中的起点更少（k=1: 300、k=2: 150、k=4: 0）——只用于量化缺陷规模，不作指标。

### 8.3 标签平衡（仅诊断）

| family | 世界 | 每 episode 步数 | transition | stay | adjacent | 每 episode distinct cell |
| --- | --- | --- | --- | --- | --- | --- |
| navigation | 50 | 7 | 300 | 0 | **300** | 6 |
| e3_identity | 50 | 5 | 200 | **200** | 0 | 1 |
| time | 50 | 4 | 150 | **150** | 0 | 1 |
| relation | 50 | 3 | 100 | **100** | 0 | 1 |

navigation 全正类、其余三族全负类 → 逐 family 永远没有两类，`balanced_accuracy` 分支不触发；合并 k 曲线的类别构成随 k 变（k=4 只剩 navigation），**不能读成「记忆越多越好」**。

## 9. 两个可审阅选项

### 选项 A：保留冻结数据 / k / 分区，只报有样本的结论，缺测保持缺测

**A 不是零变更**。把报出量从 accuracy 换成 coverage/FPR 就是改冻结定义（prereg `metrics[3]`）。零变更的正确形态：

1. **冻结指标原值照算照存**：`few_shot_unseen_transition` 的 accuracy / displacement error 按 k 逐个记，带 n；k=8 与 k=4 缺失 family 记 `insufficient_data`（不填 0、不填满分）。**这些数值目前不存在**——冻结 r5 评测路径在 k=1 崩溃，必须先修代码、重冻结、非作者复核。r3 只保留**定义、n、缺测标记**，`values_status=pending_real_eval`。
2. **另附（不替代）**：family 拆分（§8.3）与 constant 基线（§8.1），标 `diagnostic_only`。
3. **coverage / FPR** 必须作为**新 metric id** 或登记过的报告说明，不得替换原 id。

前置条件：k=1 stop 边界修复（`stop=support[-1]+2`）+ 重冻结 + 非作者复核；`probe_graph` 真实后端 TypeError 修复（r6 裁决第 3 条）；`query_limit=8` 登记或从代码路径移除。
代价：**0 新训练 / 0 新数据 / 0 新 GPU**；CPU 修复 + 重冻结 + 非作者复核。
**缺测不当通过**：k=8 永远 `insufficient_data`，不能记成 0 或满分。

### 选项 B：未来另批长 episode 数据 / 评测预算（逐项需用户批准）

不动现分区、不改 k、不改训练步数、不改原实验、不改冻结参数。

| # | 精确项 | 需批准 | 代价 / 状态 |
| --- | --- | --- | --- |
| B1 | 新数据集批：新 plan / 新 seed → **新 dataset_digest = 新实验身份**；200 世界 × ≥10 packet；按 family 分层，每 world ≥9 transition（k=8 需 8 support + 1 query） | 是 | 生成成本 **未知/未测**；登记上限 spec 300 s / CLI 600 s |
| B2 | 登记**实测**评测调用量：175 窗口 batch、611 序列前向、1492 单步 forward、800 probe_graph、3500 encode | 是 | **仅适用 digest `8234f2f3…`**；**不迁移到 B1** |
| B3 | 先测 MLX batch-1 单步 forward / encode / probe_graph 的单位耗时，再换算墙钟 | 是 | **未知/未测**；不得用 CPU 替身或 batch-16 时长外推 |
| B4 | 评测墙钟的**余量分配**（4 h 已含 eval，不是「是否计入」） | 是 | 静态 9×350=3,150 s、9×120=1,080 s 均在 10,300.395 s 余量内；实际未知；每次硬约束 350 s |
| B5 | 修订 `held-out` 语义：时间续段 vs 空间未访问 cell 是两个不同科学主张，不能共用一个 id | 是 | 需决策 |
| B6 | 登记 `query_limit=8`（当前只在代码）；决定 checkpoint 0（训练前）在曲线中的地位 | 是 | 需决策 |
| B7 | M2 探针选点固定化：当前按 episode_id（UUID）字典序取前 5（time/time/navigation/relation/e3_identity，步数 4/4/7/3/5），既非随机也非分层 | 是 | 需决策 |

**B 的代价**：新数据生成 **未知**；MLX 评测墙钟 **未知**；训练是否重跑需单独批准（本卡不申请）。B1 的新数据会把 k=8 从「0 个世界」变成「有样本」，并改变 query 数、`step_sequence`、单步 forward、`probe_graph`、`encode`——所以 B2 的数字**绝不能**当作 B1 的预算（§4 D3 已给非实测示意）。

## 10. `eval_batches=48` 的定义矛盾（保留）

| 位置 | 48 的含义 | 覆盖真实评测 |
| --- | --- | --- |
| `runtime.window_probe` | 批上限 `min(35,48)=35`，**从不生效** | 否 |
| `prereg.estimate_budget` | 训练期探针成本 `48×5×step = 1.670989920021384 s`，占 359.931 s 的一部分；相对真实 35 批超额 **1.371 倍** | 否（只覆盖训练期探针） |
| arm1 成本 | `48×5×d_step = 0.31284984004742 s`，而 arm1 实际 1 次 forward → **240 倍**超额预留 | 否 |
| 真实 eval 套件 | 冻结文档**没有任何**批数/秒数/额度登记 | — |

真实评测是 **175 窗口 batch + 611 + 1,492 + 800 + 3,500**（P19 实测），比 `48` 大一个量级。另有静默截断风险：若 dev 窗口数 > 48×16 = 768，`window_probe` 只评前 768 个窗口而日志仍写 `batches=48`；当前 dev 窗口 550，未触顶。

## 11. 保留的负面证据与未验证项（不当作通过）

**负面证据**

1. **k=1 崩溃**：`evaluation.py:331` `step_sequence(stop=support[-1]+1)` → `frames=1 < 2` → `BackendError("a sequence probe needs at least two frames")`；k=0 已算完但 `_evaluate_arm` 抛错，结果不落盘；9 次 arm×seed 评测都会在同一处中断。冻结 r5 **未修**。
2. **support 少写一条**：`stop` 是排他帧界，k=2 只写 1 条、k=4 只写 3 条。冻结 r5 **未修**。
3. **`probe_graph` 真实后端 TypeError**：非空 metric map 上把 numpy flat index 当 `(r,c)` 解包（r6 裁决第 3 条）；本卡未复现、未修、未导入 MLX。
4. **修复态计数来自计数替身**：611/1492/800/3500 是调用边界计数，不是「生产 `MlxBackend` 能跑完评测」的证明。
5. **P19 封存件 repaired 列 per-k 子块自相矛盾**（§4 D5），已留档。
6. **账本 card-local**：换 output root 得到空 `control.sqlite3`；锚到中央 RunStore 属 r6，r5 不声称解决。

**未验证项（明确声明）**

1. 未验证任何**真实 MLX 数值路径**（MLX 从未导入）；调用量不是能力结果。
2. 未测 batch-1 单步 forward / `encode` / `probe_graph` 的 MLX 单位耗时 → 评测墙钟**未知**。
3. 未验证 `_evaluate_arm` 的 RunStore 绑定段、checkpoint 重载与参数 SHA 校验。
4. 未验证 `arms.py` 的 MLX 数值路径与 arm1 的实际 C0 forward（只核了固定批形状 `(16,2,8)`=32 槽与源码分支）。
5. M2 选点的稳健性（多种子/多选点）未做。
6. 新数据计划（≥10 packet/世界）的**生成成本未测**，per-world 建图成本未知。
7. `query_limit=8` 是否登记、`held-out` 语义如何修订，属一级/用户决策。
8. **`lifecycle.py` 不在 r5 快照内**（§2），`wall_seconds` 语义按当前工作树 + P20 补充表述。
9. 本卡**不自我验收**；`completed` 与报告通过均**不代表**能力通过。

## 12. 交回统筹（需一级决定，本卡不扩额度、不写批准行）

1. 是否接受 **F1–F9 + D1–D5 的闭合方式**（对外 611/1492/800/3500/175；三处历史出处留档；两个 `generation_seconds` 只报事实；调用量绑 digest；300/350/120 三层 + wall_seconds 非 120；M2 按指针读取）。
2. 是否接受 **k=1 stop 修复 + `probe_graph` 真实后端修复** 为阻断级代码修复，开新代码卡并走新冻结 + 非作者复核（本卡不申请、不动源码）。
3. 是否接受 **选项 A** 的报出形态：冻结指标定义 + n + `insufficient_data`，数值 `pending_real_eval`；family/constant 仅诊断；coverage/FPR 另立 metric id。
4. 是否把 **选项 B 的 7 项**放入用户批准流程；其中 B1 是「新 dataset_digest = 新实验身份」，B2 的数字**只对当前 digest 有效**；B1/B3 的成本只能写「未知/待测」。
5. 是否接受 **`eval_batches=48` 不能作为评测调用量的批准依据**。
6. 是否采纳 r3 对 P19 封存件 per-k 子块的发现（§4 D5），并决定是否需要 P19 侧勘误——本卡不修改 P19 任何文件。
7. P20 独审须在本卡正式交报、一级封 r3 `REPORT.md` SHA 后才转 ready。**本卡不自我验收。**

## 13. 产物清单（全部在 `reports/V9-P18/r3/`）

| 文件 | SHA256 | 说明 |
| --- | --- | --- |
| `REPORT.md` | 见 `SHA256SUMS.txt`（封源后由一级固定） | 本报告 |
| `analysis/r3_dev_coverage.py` | `254cb1e7ce22…` | 独立纯 Python 覆盖复算（不 import 项目包） |
| `analysis/build_r3_metrics.py` | `839522fea444…` | r3 `metrics.json` 生成脚本（预算全部程序计算、常量全部从冻结源解析） |
| `products/dev_coverage.json` | `551d9b954736…` | 覆盖/形状/support-query 范围（字节确定，4 个目录同 SHA） |
| `products/metrics.json` | `0ba67a8e9d9a…` | r3 结构化结果（身份/SHA、D1–D5、F1–F9、预算、帧、48 批、A/B、负面证据、未测项） |
| `products/run_meta.json` | 见 `SHA256SUMS.txt` | 审计元数据（输出根、argv、时间）；**不参与**字节一致声明 |
| `logs/*.out` / `logs/*.err` | — | 全部运行日志；`guard_test_*` 是**故意的**写路径守卫负向测试 |
| `SHA256SUMS.txt` | — | 本目录全部产物的 SHA256 |

**为什么没有在报告里写死 `REPORT.md` 自身的 SHA**：报告无法包含自己的哈希。`SHA256SUMS.txt` 在报告写完后生成，一级封源时以该文件为准。
