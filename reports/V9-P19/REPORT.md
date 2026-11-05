# ainerzero.V9.P19 独立复核报告：S1 评测预算材料与 k 覆盖算式（复核 ainerzero.V9.P18）

角色：复核者（tier 2，非作者）；ID：`minimax-s1p19-1022`（kind=minimax，skills=text,code,math）；日期：2026-10-22
被审任务：`ainerzero.V9.P18`（作者 `deepseek-p18a`）；本卡只写 `reports/V9-P19/`
结论口径：**复算通过的部分**（可重算的数值）+ **9 条必须修正的问题**（4 条严重 / 3 条中 / 2 条轻）。
本卡**不自我验收**，不构成参数变更、批准行或任何运行授权。

---

## 0. 摘要（给一级取舍）

**可独立复现、同意的部分（占 P18 结论主体）**

- P18 报告的 **14 个冻结输入 SHA256 审前/审后各核一次，全部一致**（`reports/V9-P19/metrics.json` → `frozen_input_sha256_audit`）。
- P18 的三个脚本的**复核副本**（只改 `ISO`/`OUT` 两行脚手架路径，diff 全程留档）在**隔离目录**里重跑，**7 个产物字节级一致**（3 个 log + `cpu_coverage.json` / `truth_stats.json` / `per_world.json` / `metrics.json`）。被审脚本本体未被改动，也未原地复跑。P18 的**已测**数字全部复现。
- **k 覆盖算式复现**：k=0/1/2/4/8 → 200/200/150/50/**0** 个世界，750/550/350/100/0 条 query，family 构成 1:1 绑定（dev 200 世界 = 4 family × 50，长度固定 7/5/4/3 步）。与 P16 的 0/200、50/200 吻合。
- **k=1 崩溃**与**support 少写一条**：我**直接调用冻结的 `runtime.MlxBackend.step_sequence` 本身**核实（只替换会 import MLX 的 `eval`），得到 `BackendError`（RuntimeError 子类）、`stop=1`、第 1 个世界即抛；k=2 实际只写 **1** 条（请求 2），k=4 实际只写 **3** 条（请求 4）。P18 的结论成立。
- **预算算式全部复算一致**：`updates=3510`、`estimate=359.9312287726061`、`deadline=450`、`arm1=1.501679232227616`（deadline 2）、`phase_wall=4099.605202459`（delta=0.0）、`headroom=10300.394797541`。
- `eval_batches=48` 的三义、`48>35` 从不生效、768 窗口静默截断阈值、arm1 240 倍超额预留、D 候选固定批 `symbols (16,2,8)`=32 槽、M2 选点（UUID 字典序前 5：time/time/navigation/relation/e3_identity，步数 4/4/7/3/5）——**全部与源码一致**。
- P18 **没有**把替身 accuracy/NLL 当能力结论，MLX 墙钟写"未知/待测"，缺测写 `insufficient_data` —— 合规。

**必须修正的问题（按严重度）**

| # | 严重度 | 问题 | 位置 |
|---|--------|------|------|
| F1 | 严重 | 提请用户批准的调用量数字 **612 / 1292** 与实测 **611 / 1492** 矛盾（1292 少 200，-13.4%）；`metrics.json` 的 unmeasured 文案也把 611 与 1292 混在一句 | `REPORT.md` §10 选项B-3；`analysis/build_metrics.py:197`；`metrics.json:447` |
| F2 | 严重 | "修复态"计数是**解析外推**、不是实测；§7.4 阶段合计与 `phase_totals` 把外推值与实测值**混列且无逐行来源标记** | `REPORT.md` §7.4/§9；`metrics.json` → `phase_totals` |
| F3 | 严重 | 4 小时阶段上限**早已包含评测**（冻结源码的守卫 + 注释 + 同一账本）；选项B 第 4 条"是否把评测墙钟计入 4h 上限需用户裁决"是**伪问题** | `REPORT.md` §10 选项B-4 |
| F4 | 严重 | 选项B "新数据生成约 47.6 s（冻结 smoke 实测）"**沿用旧计划**实测值，且该值本身是清单字段的抄写、不是 smoke 的计时 | `REPORT.md` §10 选项B 代价 |
| F5 | 中 | 选项A 自称"不改任何冻结值"，其核心动作（用覆盖率/误报率替换 accuracy）**属于改冻结定义**，不能当零变更 | `REPORT.md` §5/§10 选项A |
| F6 | 中 | "1703 帧不可复现"这句不准确（1703 可算 = 950+700+53）；P18 给的 1503/1903 同样是混合口径 | `REPORT.md` §7.2 注、§11 |
| F7 | 中 | `build_metrics.py` 自称"nothing is typed in by hand"，但 M2 的 11/42 是**手写常数**（值正确、出处是硬编码）；注释与代码不一致 | `analysis/build_metrics.py:77,97` |
| F8 | 轻 | `metrics.json` 里 "probe_graph cost (600 calls)" 与别处 800（200 topology + 600 few-shot）口径不一 | `analysis/build_metrics.py:199` |
| F9 | 轻 | 冻结文档内同一 dataset digest 有两个 `generation_seconds`（45.740 / 47.605），P18 称"属可解释差异"过轻 | `REPORT.md` §8 |

---

## 1. 实际执行的命令

```bash
# 0) 领取（RC 直接检查，未用管道遮蔽）
cd /Users/mac/AinerWorkFlow/AinerRelay
python3 bin/relay register --agent minimax-s1p19-1022 --tier 2 --kind minimax --skills text,code,math
python3 bin/relay --agent minimax-s1p19-1022 claim ainerzero.V9.P19     # RC=0
python3 bin/relay --agent minimax-s1p19-1022 heartbeat ainerzero.V9.P19 --msg "…"

# 1) 冻结输入 SHA 审计（审前 + 审后各一次）
python3 - <<'PY'   # 逐项 sha256 比对 P18-frozen-review-inputs.json
PY

# 2) 隔离复跑 P18 的三个脚本（只改脚手架路径；diff 见 analysis/scaffold_diff.txt）
BASE=/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/opencode/v9p19
cp <P18>/analysis/{count_calls,truth_stats,build_metrics}.py <P19>/analysis/   # 再改 ISO/OUT 两行
diff -u <P18>/analysis/count_calls.py <P19>/analysis/count_calls.py            # 仅 ISO/OUT 两行
cd /Users/mac/AinerWorkFlow/AinerZero
env -i PATH=/usr/bin:/bin:/usr/local/bin HOME="$BASE/home" \
    TMPDIR=/private/var/folders/.../opencode PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python reports/V9-P19/analysis/count_calls.py  > reports/V9-P19/logs/count_calls.out  2> …err
env -i … .venv/bin/python reports/V9-P19/analysis/truth_stats.py   > …/truth_stats.out    2> …err
env -i … .venv/bin/python reports/V9-P19/analysis/build_metrics.py > …/build_metrics.out  2> …err

# 3) 独立复核脚本（自带替身 + 冻结 r5 字节副本 + 1 行修复副本）
env -i … .venv/bin/python reports/V9-P19/analysis/independent_checks.py > …/independent_checks.out 2> …err
env -i … .venv/bin/python reports/V9-P19/analysis/build_review_metrics.py > …/build_review_metrics.out 2> …err
```

- 三个 P18 脚本 RC=0、stderr 全空（`logs/*.err` 0 字节）。
- `independent_checks.py` 第 1、2 次尝试因**我自己替身**的形状问题失败，日志保留为 `logs/independent_checks_attempt{1,2}_*.out`（见 §5 F2 说明），第 3 次 RC=0、stderr 空。
- **没有**执行：`--mode train/eval/smoke/data`、任何 MLX 前向/梯度/优化器、final 分区读取、下载/安装、git commit/push、批准行写入、RESEARCH_LOG 改写、生产 Relay/8790 操作。
- 隔离：`HOME`、`TMPDIR`、`PYTHONDONTWRITEBYTECODE` 全部指向私有临时根；P18 脚本的 `ISO=/tmp/v9p18_iso`（会 `rmtree` 重建）与 `OUT=reports/V9-P18`（会覆盖被审产物）**两处都改到我的目录**，diff 全文在 `analysis/scaffold_diff.txt`（每个文件只改 2 行）。

## 2. 输入与身份

| 项 | 值 |
| --- | --- |
| 冻结输入清单 | `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/P18-frozen-review-inputs.json` |
| 14 个文件 SHA256 | **审前全部一致**；审后（复跑+独立脚本之后）**再次全部一致**（`metrics.json` → `frozen_input_sha256_audit`） |
| 被审报告 | `reports/V9-P18/REPORT.md` sha256 `0b33e29fbd2e5ab68f7f5338f120d596798a44f1af8c1393c3056b6ccbf09908`（26,321 B） |
| 冻结 r5 源码快照 | `…/s1-r5-input-snapshot`（`evaluation.py` `92d8de4a…72aa3`、`runtime.py` `a9934652…06c7`、`metrics.py` `e1c36b65…643e1`） |
| 冻结开发集 | `artifacts/v9/s1/datasets/8234f2f3…83ad26`（只读；`truth/development.jsonl` `76b98649…26e6`） |
| MLX 是否被导入 | **否**（`metrics.json` → `no_real_execution.mlx_imported=false`；`independent_checks.json` 每次导入后断言 `"mlx" not in sys.modules`） |
| 修复副本 | `…/v9p19/iso_check_repaired`（`evaluation.py` 仅 1 行：`stop=support[-1] + 1` → `+ 2`；补丁前后 SHA 记录在 `independent_checks.json` → `identity.repaired_tree`） |

**并发观察（不是我的写入）**：复核期间仓库根出现未跟踪目录 `.tmp/pytest-of-{root,unknown}/…`（时间戳 00:49），内容是 S1 r6 卡（`test_production_train_3510…`、`train_refuses_when_a_bound…`）的 pytest 临时目录。我的脚本从未使用 pytest、从未写过 `.tmp/`，**未触碰、未删除**这些文件。

## 3. 写路径审查（先做，且不原地复跑）

P18 三个脚本的写路径（源码定位）：

| 脚本 | 危险写点 | 我做了什么 |
| --- | --- | --- |
| `count_calls.py:28,38-39,464-466` | `ISO=/tmp/v9p18_iso` 且 `build_iso()` **先 `shutil.rmtree` 再重建**；`OUT=reports/V9-P18` → **覆盖** `cpu_coverage.json` / `per_world.json` | ISO→`…/v9p19/iso`，OUT→`reports/V9-P19` |
| `truth_stats.py:22-23,128` | 同上，覆盖 `truth_stats.json` | 同上 |
| `build_metrics.py:17-18,205` | 同上，覆盖 `metrics.json` | 同上 |

- 三个脚本都**只写** `OUT`（无其它落盘点），未发现隐藏的硬编码输出路径；`build_metrics.py` 里唯一的其它写是 `ISO` 读取。
- **原地复跑被明令禁止**，已遵守：被审的 `reports/V9-P18/**` 14 个文件在复跑前后 SHA 全部不变。
- 复核产物全部落在**新目录** `reports/V9-P19/{analysis,logs}/`。

## 4. 独立复算结果

### 4.1 字节级复现（P18 的已测部分）

7 个产物**完全一致**（`metrics.json` → `independent_reproduction.all_identical=true`）：

| 产物 | P18 sha256 前 12 | P19 sha256 前 12 | 一致 |
| --- | --- | --- | --- |
| `logs/count_calls.out` | `45b1d988d168` | `45b1d988d168` | ✅ |
| `logs/truth_stats.out` | `f6751b7b8424` | `f6751b7b8424` | ✅ |
| `logs/build_metrics.out` | `a24ed58fd70e` | `a24ed58fd70e` | ✅ |
| `analysis/cpu_coverage.json` | `def368fe01cf` | `def368fe01cf` | ✅ |
| `analysis/truth_stats.json` | `04cc9b0e4e05` | `04cc9b0e4e05` | ✅ |
| `analysis/per_world.json` | `862ce5f5a6f5` | `862ce5f5a6f5` | ✅ |
| `metrics.json` | `71bc8c38eb27` | `71bc8c38eb27` | ✅ |

### 4.2 k 覆盖（复现 + 独立解释）

| k | 有 support+query 的世界 | query 数 | family 构成 | query 目标 cell 已在记忆内 | 恒定"预测有边"基线（true_edge_rate） |
| --- | --- | --- | --- | --- | --- |
| 0 | 200 | 750 | 4×50 | 0（0.0%） | 0.400 |
| 1 | 200 | 550 | 4×50 | 350（63.6%） | 0.454545 |
| 2 | 150 | 350 | navigation/e3_identity/time（丢 relation） | 200（57.1%） | 0.571429 |
| 4 | 50 | 100 | **只有 navigation** | 50（50.0%） | **1.000** |
| 8 | **0** | 0 | — | — | 无样本 |

复算确认 P18 的结构判断：k 与 episode 长度 1:1 绑定 → k 曲线是"标签构成随 k 变"的混杂曲线；`query_limit=8` **只存在于 `metrics.split_support_query` 的默认参数**，冻结 prereg 全文**没有** `query_limit`（我 grep 过），因此它确实未登记；当前数据下 `query_limit` 未触顶（navigation 最多 6 条 query）。

### 4.3 直接用**真实 runtime 方法**核实 k=1 崩溃与 support 少写一条

我用 `runtime.MlxBackend.step_sequence`（**冻结源码本体**）跑，只把会 `import mlx` 的 `eval` 换成记录桩（`mlx` 未被 import，已断言）：

| k | stop | 真实方法结果 | 请求写入 support | 实际写入 |
| --- | --- | --- | --- | --- |
| 1 | 1 | **抛 `BackendError`**（MRO: BackendError→RuntimeError），信息 `a sequence probe needs at least two frames`，第 1 个世界 | 1 | 0（未写入即崩） |
| 2 | 2 | 正常 | 2 | **1** |
| 4 | 4 | 正常 | 4 | **3** |
| 8 | — | 无任何世界有 query | 8 | — |

**P18 的两个核心缺陷判断成立**（§6.1 崩溃、§6.2 少写一条），且崩溃点在 k=0 之后 → k=0 的结果同样不落盘。

补一条 P18 没写清的技术细节：修复应取 `stop=support[-1] + 2`（= k+1），此时 `frames=k+1` → 执行 `k` 条 transition，**恰好写满请求的 k 条 support**，且 query 起点是 transition `k`（`split_support_query` 给的 `query=range(k, …)`），support 与 query 仍然不重叠、不断档；k=1 时 `frames=2` 自然满足 `frames>=2` 守卫。P18 §10 选项A-1 给的修法方向正确。

## 5. 发现的问题（逐条给证据与改法）

### F1（严重）提请批准的调用量数字 612 / 1292 是错的

- P18 `REPORT.md` §10 选项B 第 3 条建议**显式登记**："窗口 batch 35×5、序列前向 **612**、单步 forward **1292**、encode 3500、probe_graph 800、D 1"。
- 但同一份报告 §7.2/§9 与 `metrics.json` 的计算结果是 **611 / 1492**；`build_metrics.py:197` 的 unmeasured 文案还把 `611 eval calls` 与 `1292 forwards` 拼在一句里（`metrics.json:447` 同样）。
- **我的独立实测**（见 F2 方法）：修复态 `step_sequence_calls = 611`、`single_step_forward_calls = 1492`。
- 差值：`612−611 = +1`；`1292−1492 = −200`（**相对误差 −13.4%**，且 200 恰好是 k=1 的 200 个世界的 support 写入量，像是漏算了一项）。
- **改法**：选项B 第 3 条的登记数字必须改成 **611 / 1492 / 800 / 3500 / 35×5**（我的 `metrics.json` 已给出实测值与差值）；`build_metrics.py:197` 的文案同步改。**这批数字是要进用户批准流程的，不能带着两个错值进。**

### F2（严重）"修复态"是外推而非实测，且阶段合计把外推与实测混列

- P18 的 `count_calls.py` 全部使用**崩溃语义** `stop=support[-1] + 1`；`build_metrics.py:79-90` 用公式 `worlds * k` 直接算出"修复态"的 700 次单步 forward。**没有任何一次运行产生过修复态的数字**。
- 更强的一条证据：**用 P18 自己的替身根本跑不出修复态**。生产 `runtime.MlxBackend.encode` 返回固定宽度、**1-D**（`np.asarray(...)[0]`）的模型嵌入；而 P18 替身的 `encode`（`count_calls.py:108-113`）返回**宽度随观测行长度变化**、**2-D `(1,dim)`** 的向量。于是只要记忆图非空（k≥1），`evaluation._cosine_match` 的 `nodes @ query` 必抛 `ValueError: matmul ... (size 1 is different from 8)`。我的第 1、2 次尝试就是撞上这个（`logs/independent_checks_attempt{1,2}_*.out`），把替身改成"固定宽度 + 1-D"后才跑通——**只改我的替身，未改被审源**。
- 结果：修复态数字**实测 = 611 调用 / 1492 单步 forward / 800 probe_graph / 3500 encode / 175 窗口 batch**，与 P18 外推值**一致** → **数字对、出处错**。
- **但是**：P18 §7.4「阶段合计」表和 `metrics.json` 的 `phase_totals` 把这些**外推值**（9×611=5,499、9×1492=13,428、9×800=7,200、9×3500=31,500）与**实测值**（9×175=1,575 窗口 batch）**混列**，且 JSON 里**没有任何逐行来源标记**。读者容易把 13,428 当成冻结路径的实测调用量；而按现状（k=1 崩）9 次评测根本跑不完、结果不落盘。
- **改法**：`metrics.json` 每行加 `provenance: measured | projected`，`phase_totals` 显式拆成 `as_coded` 与 `projected_repaired` 两块；`REPORT.md` §7.4 表头加注"（修复态投影，非实测）"。

### F3（严重）4 小时阶段上限**本来就包含评测**；选项B 第 4 条是伪问题

冻结源码（r5 快照）里的三处证据：

1. `commands.py`（`mode_train` 阶段守卫）：
   `total_wall = sum(float(r.wall_seconds) for r in store.list_runs())  # Include auxiliary eval/verify reservations; the phase cap is not a training-experiment-only allowance.`
2. `worker.py`（`_train` 阶段守卫）：
   `total_wall = sum(float(r.wall_seconds) for r in ledger.store.list_runs())  # The phase cap covers every registered run in this card-local ledger, including auxiliary eval/verify runs. Counting only the training experiment would hide those costs.`
3. eval 侧：`worker.py` eval 分支 `ledger = PrepLedger(output_root / "control.sqlite3")` → `active_run = ledger.open_aux_run(mode="eval", wall_budget_seconds=budget)` → `ledger.finish(active_run, "completed", "s1_eval_completed")`；与 train 守卫读的是**同一个** `output_root/control.sqlite3`。

结论：**上限口径早已定为"阶段总墙钟"，评测自然在内**。P18 §10 选项B 第 4 条"评测墙钟纳入 phase_wall…需用户裁决（会改变已登记的 phase_wall_headroom）"把一个已定事实当成待裁决项，且暗示要改已登记参数——按一级口径这属于"为通过而放宽/改动冻结登记"，**不能作为入口**。

真正剩下的问题只有两个（都不需要新的批准口径）：
- **评测墙钟的估计值未测**（batch-1 单步 forward、encode、probe_graph 的 MLX 单位耗时都没有）→ 现在只能写"未知"；
- **余量分配**：`phase_cap=14,400`，冻结 `phase_wall=4,099.605`（= 9×450 + 1×2 + 47.605），余量 `10,300.395`；CLI 对每次 eval 的硬墙钟是 `PREP_BUDGET["eval"]=300 s`（`commands.py:42`），9 次共 2,700 s，在余量之内。风险点是**每次 eval 的 300 s 硬杀**，不是 4 h 上限。

### F4（严重）选项B 的"新数据生成约 47.6 s"是旧计划成本，且该值本身不是 smoke 的计时

- P18 §10 选项B「B 的代价」："新数据生成约 47.6 s CPU（**冻结 smoke 实测**）"。
- 事实 1：**47.605 s 不是 smoke 测出来的**。`smoke.py` 里是 `"data_generation_seconds": float(manifest.get("generation_seconds") or 0.0)` —— 从**数据集清单字段抄来**，smoke 本身不计时生成过程。
- 事实 2：冻结文档里**同一个 dataset digest** 有两个 `generation_seconds`：`data_identity.generation_seconds = 45.739918708000005` 与 `timing.smoke.data_generation_seconds = 47.605202458999884`（差 1.865 s）→ 清单字段在预注册冻结**之后**被改写过（phase_wall 用的是较保守的 47.605）。
- 事实 3：47.605 s 覆盖的是**旧计划**：2,200 世界 / 10,450 packet（train 9,500 + dev 950）→ ≈ **4.555 ms/packet**。
- 事实 4：选项B 的新计划是 **200 世界 × ≥10 packet = ≥2,000 packet**（= 旧计划的 19.1%），但**每世界的 episode 更长、场景更大**，per-world 建图成本**从未测过**。
- 结论：**47.6 s 不能当作新计划的成本**。按 packet 速率外推是 ≈ **9.1 s**（只含 packet 成本，不含未知的世界建图成本），二者差 ~5 倍；而且新计划必须落在已登记的生成预算内：`spec.TIMING["data_generation_budget_seconds"] = 300 s`、CLI `PREP_BUDGET["data"] = 600 s`。
- **改法**：选项B 的代价行改成"新计划生成成本**未知**，须在新 plan 上重测（旧计划实测 47.605 s / 10,450 packet ≈ 4.56 ms/packet；新计划 ≥2,000 packet，per-world 建图成本未测；登记上限 300 s / 600 s）"，**不得**再写"47.6 s 实测"。

### F5（中）选项A 不是"零变更"

- P18 §10 选项A 标题写"**不改任何冻结值**"，但 §5 结论第 4 条写"该指标当前**只能**拆成两个可解释量分别报：**覆盖率**、**误报率**……不能报单一 accuracy 曲线"，选项A 的可报项表里也只列覆盖率/误报率。
- 冻结指标 `few_shot_unseen_transition` 的定义是 **"accuracy and displacement error vs k"**（prereg `metrics[3]`）。把报出量从 accuracy 换成覆盖率/误报率，就是**改冻结定义**，不能自称零变更。
- **零变更的正确形态**（可全部用已冻结数据与已算出的数）：
  1. 冻结指标**原值照算照存**：`few_shot_unseen_transition` 的 accuracy / displacement error 按 k 逐个记，带样本量；k=8 与 k=4 的缺失 family 记 `insufficient_data`（不填 0、不填满分）；这些值要等真实 eval（当前被 k=1 崩溃阻断）才有，故**必须先修 k=1**。
  2. **另附**（不替代原值）：family 拆分（nav 全正 / 其余三族全负，证据见 `truth_stats.json` → `transition_kind_by_family`）、**恒定预测基线**（P18 自己已经算出来：合并 true_edge_rate 0.400 / 0.454545 / 0.571429 / **1.000**，其补数 0.600 / 0.545455 / 0.428571 / 0.000 即"恒报假/恒报真"两端的可达分数；`by_family.true_edges` 给出逐 family 拆分）。这一步**不改**冻结指标，只是把"该指标在当前数据上退化"这件事变成可核对的数字。
  3. 指标口径修订（coverage/FPR 作为**新** metric id 或作为报告说明）**必须走登记**，不能塞进"零变更"里。
- P18 方向判断（k=8 零样本、k=4 单 family、跨 family 合并曲线不可解释）**我同意**；需要改的只是"零变更"的措辞与报出形态。

### F6（中）"1703 帧不可复现"这句不准确；P18 自己的替代数也是混合口径

我把三个数都**算**出来了（`metrics.json` → `frames_decomposition`）：

| 数 | 分解 | 口径 |
| --- | --- | --- |
| **1703** | 950（topology stop_frames）+ 700（few-shot **transitions**）+ 53（M2 stop_frames） | 混合：用**崩溃版**的 `stop=k` 计数，却假设 k=1 **不崩**——没有任何一个代码版本能产生这个组合 |
| **1503** | 750（topology **transitions**）+ 700（few-shot transitions）+ 53（M2 stop_frames） | 混合 |
| **1903** | 1100（few-shot stop_frames，修复版 `stop=k+1`）+ 750（topology transitions）+ 53（M2 stop_frames） | 混合 |
| **1003** | 950 + 0 + 53 | **单一自洽**：as-coded 的 stop_frames 合计 |
| **2103** | 950 + 1100 + 53 | **单一自洽**：修复态的 stop_frames 合计 |
| **1492** | 750 + 700 + 42 | **单一自洽**：单步 forward（= transitions）合计 |

- 所以 P18 §7.2 注"1703 帧我用三种口径都算不出来"**不成立**（1703 能算出来，只是口径是"崩溃 stop + 不崩 k=1"的杂交）；而 P18 给的 1503/1903 同样是杂交口径，**不能作为"以本表逐组件计数为准"的替代口径**。
- **改法**：统一用两行自洽口径：**as-coded = 212 次调用 / 1,003 stop_frames / 792 次单步 forward**；**修复态 = 611 / 2,103 / 1,492**，并注明 1703 的来源是"旧 stop 约定 + 假设不崩"的杂交数，不是任何真实或自洽运行的量。

### F7（中）`build_metrics.py` 的"nothing is typed in by hand"与实际不符

- 文件头写"All arithmetic is computed here from the frozen pre-registration and the instrumented call counts; **nothing is typed in by hand**"，但第 97 行 `m2_calls = {"step_sequence_calls": 11, "single_step_forwards": 42}` 是**手写常数**。
- 我**实测**这组数（对 M2 单独计数）：`step_sequence_calls=11`、`transitions=42` → **值正确**，但出处是硬编码，与"插桩计数"的说法不一致。
- 同一段注释与代码也矛盾：第 77-78 行注释写 "k frames are executed per world, so **k-1** single-step forwards per world"，第 90 行代码却是 `worlds * k`；实测修复态 few-shot 写入 = 700 = 200×1 + 150×2 + 50×4，**即 k 条**（注释错、代码对）。
- **改法**：M2 两项改为实测来源（或注明"手写常数 + 已复核"），注释改成"k transitions per world"。

### F8（轻）`probe_graph` 口径不一

`build_metrics.py:199` 写 "MLX probe_graph cost (600 calls) is not measured"，而 §7.2/§9 与计算值是 **800**（200 topology + 600 few-shot）。600 只是 few-shot 那一半。改文案。

### F9（轻）冻结文档内部不一致的定性

P18 §8 说 45.740 与 47.605 "是两次不同的记录，差 1.865 s，属**可解释差异**"。更准确的说法是：**同一 dataset digest 的清单 `generation_seconds` 字段在预注册冻结后被改写**，冻结文档因此内部含两个值（phase_wall 用了较保守的 47.605）。这不影响 phase_wall 的复算（delta=0.0），但应记为"冻结文档内部不一致（已取保守值）"，而不是"可解释差异"。

## 6. 我同意 P18 的判断（未发现问题）

- **k 覆盖结构**：k 与 episode 长度 1:1 绑定；k=4 只剩 navigation 单 family、k=8 零样本；跨 family 合并的 k 曲线是标签构成随 k 变的混杂曲线，不可解释。
- **k=1 崩溃 + support 少写一条**是冻结 r5 评测路径的**阻断级缺陷**（9 次 arm×seed 事后评测都会在同一处中断，且 k=0 结果也不落盘）。
- **`eval_batches=48` 不是真实评测量**：它同时是 window_probe 的批上限（35<48，从不生效）、训练 run 的探针成本项（1.671 s）、arm1 的成本项（1.502 s，而 arm1 实际只做 1 次 forward → 240 倍超额预留）；真实 eval 套件在冻结文档里**没有任何批数/秒数/额度登记**。
- **GPU/MLX 评测墙钟应写"未知/待测"**：冻结 smoke 只测过 batch-16 前向，611 次调用是 batch-1 单步 forward（延迟受限，与 batch-16 吞吐不可换算），3500 次 encode 与 800 次 probe_graph 从未测过。
- **缺测不得当通过**：k=8 记 `insufficient_data`、k=4 缺 family 记 `insufficient_data`，不填 0、不填满分。
- **M2 选点未登记**：按 episode_id（UUID）字典序取前 5，不是随机也不是分层，冻结文档未登记为固定选择。
- **未把替身 accuracy/NLL 当能力结论**；本卡的实测同样只作调用量证据，不构成任何能力/科学结论。

## 7. 边界与未验证项

**边界（我做了什么/没做什么）**

- 只写 `reports/V9-P19/`；被审源码、冻结数据、冻结文档、P18 全部报告/脚本**零改动**（14 个 SHA 审后仍一致）。
- 未跑真实模型/训练/评测；未 import MLX（每次导入后断言）；未 GPU/渲染；未下载/安装；未改种子/参数/阈值/预算；未写批准行；未改 `RESEARCH_LOG.md`；未读 final 分区；未 git commit/push；未动生产 Relay/8790/生产库；未触碰他人（r6 卡）的 `.tmp/` 与 `reports/V9-P18/`。
- 未使用 `--force` / `--takeover` / 冒充他人身份；正常 claim（RC=0）后单一持卡作业。
- 临时 `HOME`/`TMPDIR` 隔离；P18 脚本的 `ISO`/`OUT` 两处脚手架路径改到我的目录，diff 全程留档。

**未验证项（明确声明）**

1. 未验证任何**真实 MLX 数值路径**（MLX 从未导入）；修复态计数是"我的替身 + 1 行修复"上的**调用量**测量，**不等于**生产耗时或能力。
2. 未测 batch-1 单步 forward / `encode` / `probe_graph` 的 MLX 单位耗时 → 评测墙钟仍为"未知"。
3. 未验证 `_evaluate_arm` 的 RunStore 绑定段、checkpoint 重载与参数 SHA 校验（我复刻的是**调用序列**，不是绑定流程）。
4. 未验证 `arms.py` 的 MLX 数值路径与 arm1 的实际 C0 前向（P18 的"D 候选 1 次 forward"我只核了固定批形状 `(16,2,8)`=32 槽与源码分支，未执行）。
5. M2 选点的稳健性（多种子/多选点）未做。
6. 新数据计划（≥10 packet/世界）的**生成成本未测**，per-world 建图成本未知。
7. `query_limit=8` 是否登记、以及"held-out"语义（时间续段 vs 空间未访问）如何修订，属一级/用户决策，本卡只提供证据。
8. 本卡**不自我验收**；`completed` 与本报告通过均**不代表**能力通过。

## 8. 产物清单（均在 `reports/V9-P19/`）

- `REPORT.md`：本报告。
- `metrics.json`：结构化复核结果（SHA 审计、字节级复现、k 覆盖、真实 runtime 核实、实测/外推调用量、frames 分解、612/1292 差值、阶段预算、数据成本归属）。
- `analysis/scaffold_diff.txt`：P18 三脚本 → 复核副本的**唯一**改动（每文件 2 行：ISO、OUT）。
- `analysis/{count_calls,truth_stats,build_metrics}.py`：P18 脚本的复核副本（仅脚手架路径改动）。
- `analysis/independent_checks.py` / `analysis/independent_checks.json`：独立复核脚本与结果（真实 runtime 方法核实 + 冻结副本 + 1 行修复副本的实测计数 + 组件拆分 + frames 分解）。
- `analysis/build_review_metrics.py`：本卡 metrics.json 的生成脚本（数字全部程序计算）。
- `analysis/{cpu_coverage,truth_stats,per_world}.json`：复核副本的原始输出（与 P18 字节一致）。
- `logs/*.out` / `logs/*.err`：全部运行日志；`independent_checks_attempt{1,2}_*` 为我替身形状问题导致的两次失败尝试（保留，不删除）。

## 9. 交回统筹（需一级决定，我不擅自扩额度或改参数）

1. 是否接受 F1–F4 为**必须修正**（其中 F1 的 612/1292 是要进用户批准流程的数字、F3 会把一个已定口径重新抛给用户）。
2. 是否接受 **k=1 崩溃 + support 少写一条** 为冻结 r5 评测路径的阻断级缺陷，并开一张**代码修复卡**（`stop=support[-1]+1` → `+2`，须新冻结 + 非作者复核；我已实测该 1 行修复可使冻结评测套件跑完，且 support 恰好写满 k 条、query 不重叠）。
3. 是否接受 **k 曲线按 family 拆开报**、k=8 与 k=4 缺失 family 一律 `insufficient_data`；并按 F5 把"覆盖率/误报率"从"零变更"里拿出来单独登记。
4. 是否接受 **`eval_batches=48` 不能作为评测调用量的批准依据**，并选择：①先测 batch-1 单步 forward / encode 的 MLX 单位耗时再登记评测预算；②或把评测套件拆成独立预算行（不占训练 run 的 estimate）。
5. 选项 B 的 7 项若进入用户批准流程，请**先按 F1/F4 修正数字**（611/1492；生成成本写"未知/待在新 plan 上重测"），并按 F3 **删去**"是否把评测墙钟计入 4h 上限"这一条（口径已定，剩下的是余量分配与未测的墙钟估计）。
6. 本卡结论**仅供取舍**：不改 k、世界、分区、训练步数、eval 额度，不写批准行，不构成任何运行授权。
