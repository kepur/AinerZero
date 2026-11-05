# ainerzero.V9.P18 执行报告：S1 评测调用量与 k 支持覆盖（冻结值不改的预算决策材料）

角色：executor（二级）；负责人：`deepseek-p18a`（DeepSeek-V4.1-Flash，tier 2）；时间：2026-10-22（客户端）
任务状态：reported；实验状态：**未执行**（纯 CPU 工程统计与调用计数；无真实训练/评测/MLX 前向）
任务依据：`ainerzero.V9.P18` 任务卡；`S1-R6-DECISION.md` 第 5 条（k=8 在冻结 dev 0/200、k=4 为 50/200、真实评测量超过 48 批是待决策缺口；本次不改 k/世界/分区/训练步数/eval 额度）
文件范围：只写 `reports/V9-P18/`。项目文档、冻结数据、旧报告、源码全部只读。

## 摘要（供一级取舍，不构成参数变更或运行授权）

1. **k 覆盖被 family 与 episode 长度 1:1 绑定**：dev 200 世界恰好 4 family × 50 世界，长度固定为 navigation=7 步、e3_identity=5 步、time=4 步、relation=3 步。因此 k 的可用世界数完全由 family 决定：k=0/1→200、k=2→150、k=4→50（**只剩 navigation**）、k=8→0。P16 的 0/200 与 50/200 独立复现。
2. **k 曲线不是 within-family 曲线**：k=2 丢掉 relation，k=4 丢掉 relation/time/e3_identity。任何跨 family 合并的"accuracy vs k"曲线都是**标签构成随 k 变化**的混杂曲线，不能读成"记忆越多越好"。
3. **冻结 few-shot 边存在性指标在两个方向上都没有类别平衡**：navigation 的 300 条 transition 全是相邻移动（标签全 True）；time/relation/e3_identity 的 450 条 transition 全是**原地不动**（标签全 False，且每 episode 只有 1 个 cell）。逐 family 永远不会同时出现正负类，`balanced_accuracy` 分支永不触发。该指标对 3/4 的 family 只能测"会不会瞎报边"。
4. **冻结评测路径在 k=1 必然崩溃**：`few_shot_report` 用 `step_sequence(stop=support[-1]+1)`，k=1 时 `stop=1` → `frames=1 < 2` → `BackendError`。这与数据无关、与 arm 无关，**9 次 arm×seed 的事后评测都会在同一处中断**，且崩溃点在 k=0 之后，所以连 k=0 的结果也不会落盘。
5. **support 少写一条**：`stop=support[-1]+1` 的 `stop` 是**排他帧界**，实际执行 `k-1` 条 transition（k=2 写 1 条、k=4 写 3 条）。即"写 k 条 support"实际是"写 k-1 条、跳过 1 条、再从第 k 条起 query"。
6. **调用量核算（精确、可复现）**：训练 run = 3510 次 optimizer + 175 个窗口 batch（5 检查点 × 35 批）；事后评测 run（按现状）= 175 窗口 batch + 212 次序列前向 + 792 次单步 forward + 1500 encode，然后在 k=1 中断；若修好 k=1 的完整评测 run = 175 + 611 序列前向 + 1492 单步 forward + 800 probe_graph + 3500 encode。
7. **`eval_batches=48` 有三种互不兼容的含义**：①`window_probe` 的批上限（实际 35，48 从不生效）；②训练 run 内的探针成本 `48×5×单批步时`=1.671 s；③arm1 成本 `48×5×D步时`=1.502 s，而 arm1 实际只做 **1 次** forward（240 倍超额预留）。**没有任何一处把事后评测套件计入预算**：`phase_wall=4099.605 s` 只有 9×450 + 1×2 + 47.605，事后评测 0 秒；真实评测只有 CLI 的 `PREP_BUDGET["eval"]=300 s` 硬墙钟（9 次 2700 s，也在 `phase_wall` 之外）。
8. 独立重算冻结预算逐项吻合：`updates=3510`、`estimate=359.9312287726061`、`deadline=450`、`arm1=1.501679232227616`、`phase_wall=4099.605202459`（delta=0.0）。
9. **GPU/MLX 实测耗时：未知/待测**。冻结 smoke 只测过 batch-16 前向（0.006962458 s/批）；事后评测是 611 次 batch-1 单步 forward + 3500 次 encode，从未测过。不把 CPU 替身或 batch-16 单批时长外推成 MLX 实测。
10. 交付两个可审阅选项：**A**（保留冻结数据/k/缺测，只报具备样本的科学结论）与 **B**（未来另批长 episode 数据与评测预算，不动现分区/原实验，需用户逐项批准）。**缺测一律不当通过**；k=8 与 k=4 之外的 family 记为 `insufficient_data`，不记 0、不记满分。

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero

# 注册与领取（摘要）
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay register --agent deepseek-p18a --tier 2 \
  --kind DeepSeek-V4.1-Flash --profile-file /tmp/v9p18_profile.json
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay claim ainerzero.V9.P18 \
  --agent deepseek-p18a --token <任务卡令牌>

# (1) 调用计数：在 /tmp 隔离副本上跑生产 evaluation/metrics 函数，替身后端只计数
.venv/bin/python reports/V9-P18/analysis/count_calls.py \
  > reports/V9-P18/logs/count_calls.out 2> reports/V9-P18/logs/count_calls.err

# (2) 纯真值统计（无模型、无后端）
.venv/bin/python reports/V9-P18/analysis/truth_stats.py \
  > reports/V9-P18/logs/truth_stats.out 2> reports/V9-P18/logs/truth_stats.err

# (3) 汇总 metrics.json（预算算式在脚本内重算，不手抄）
.venv/bin/python reports/V9-P18/analysis/build_metrics.py \
  > reports/V9-P18/logs/build_metrics.out 2> reports/V9-P18/logs/build_metrics.err
```

运行顺序：`count_calls.py` 会重建 `/tmp/v9p18_iso`（快照源码的**字节副本**，不用符号链接，避免污染仓库），另两个脚本复用该副本。
未执行：任何 `--mode train` / `--mode eval`、MLX 前向或梯度、数据生成、final 读取、模型下载/安装、资源基线重设、git commit/push、批准行写入。

## 2. 输入与身份（独立重算）

| 项 | 值 |
| --- | --- |
| 源码快照根 | `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot`（一级已钉 r5，未用 r6 并行现场源） |
| `data.py` | `c354fdd5bacf054f02cc601c9362c334d7a732e6ba4aa1c8b1a310aff13958fc` |
| `evaluation.py` | `92d8de4a6551b8538f38a54b17b550a88aa80c4135d05c0e29b8be2f8bf72aa3` |
| `metrics.py` | `e1c36b657794d5ba3ac2c59b2994ea71c5bc66eb032d4f4b08a9f91ef5a643e1` |
| `runtime.py` | `a99346522f294bf195438efb8e9af72db391abd517ab4d80533330ad6ee506c7` |
| `spec.py` / `worker.py` / `prereg.py` / `commands.py` | `beedc948…e2b774` / `41741874…1beb7ba` / `d441b84e…29666db` / `48b3fb48…0fd616` |
| r5 冻结文档落盘 SHA | `895bb3676cd3db6ad7995814ee940e23b1bff55747e8dea665f5fe426386075b` |
| 数据集目录 | `artifacts/v9/s1/datasets/8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26` |
| `truth/development.jsonl` | `76b986495229de893fb50e0740296f6414225a06b1b444fa4f20eb43911e26e6`（与冻结 `data_identity.files` 一致） |
| `packets/development.jsonl` | `b9420ef5e26a00a29f022f75390cf39ffd36fac1be8b723767fa71250d7a4aa7`（一致） |
| MLX 是否被导入 | **否**（脚本内断言 `"mlx" not in sys.modules`，结果 `mlx_imported: false`） |

`data.py` 的 `load_truth_view` / `load_training_episodes` 是生产函数本体，未改写；`metrics.split_support_query`、`metrics.few_shot_transition_metrics`、`evaluation.few_shot_report`、`evaluation.topology_report`、`evaluation.m2_interference` 均为**生产函数本体**。只替换了数值后端（`CountingBackend`，无 MLX、不写检查点、不训练）。

## 3. k 支持覆盖（真实 dev 200 世界）

世界数/长度是**离散且与 family 一一对应**的（不是平均分布）：

| family | 世界 | 每 episode 步数 | transitions | 可用 k |
| --- | --- | --- | --- | --- |
| navigation | 50 | 7 | 6 | 0,1,2,4 |
| e3_identity | 50 | 5 | 4 | 0,1,2 |
| time | 50 | 4 | 3 | 0,1,2 |
| relation | 50 | 3 | 2 | 0,1 |

| k | 有 support+query 的世界 | query transition 数 | family 构成 | 落在 support 记忆内的 query 目标 cell |
| --- | --- | --- | --- | --- |
| 0 | 200 | 750 | 4 family 各 50 | 0（0.0%，空图） |
| 1 | 200 | 550 | 4 family 各 50 | 350（63.6%） |
| 2 | 150 | 350 | navigation/e3_identity/time（**丢 relation**） | 200（57.1%） |
| 4 | 50 | 100 | **只有 navigation** | 50（50.0%） |
| 8 | **0** | 0 | — | — |

- 与 P16 的 `k=8=0/200`、`k=4=50/200` 精确吻合（我另加：k=2=150/200、k=1=200/200）。
- `query_limit=8` 是代码里的**上限**，冻结指标正文只写"held-out transitions"，未登记这个上限；当前数据下 k=0 的 navigation 世界最多也只有 6 条 query，未触顶。
- 结论：**k=4 这一点不是"少量样本"，而是单一 family 的单点**；k=8 是**零样本**。两者都不能当作 k 曲线的端点来读。

## 4. support/query 是否跨 episode

- **代码层**：`few_shot_report` 对每条 `sequence`（= 一个 episode = 一个 world，`rounds_per_world=1`）独立调用 `metrics.split_support_query(transitions, k)`，support 与 query 都取自**同一个 episode 的连续前缀/后缀**，`by_world` 也是按 episode 记账。**不存在跨 episode 或跨 world 的 support/query 混用**，也不会把别的世界写进记忆。
- **但"held-out"只是时间上的**：query 是 support 前缀的**直接续段**，不是空间上未访问的区域。证据：query 目标 cell 落在 support 记忆内的比例只有 50%–64%（见上表）。也就是说，至少一半的 query 目标 cell 在写记忆时**物理上还没被访问过**，模型不可能从记忆里取到它 —— 这部分真阳在结构上不可达。
- **且 support 少写一条**（见 §6.2）：k=4 实际只写 3 条，第 4 条 support 与第 1 条 query 之间的那条 transition 既没写也没评。

## 5. 标签平衡：这个指标在两个方向上都没有负类/正类

按 family 统计 cell 级 transition 类型（真值旁路，无模型）：

| family | stay（原地不动） | adjacent（相邻移动） | non_adjacent | 每 episode distinct cell |
| --- | --- | --- | --- | --- |
| navigation | 0 | **300** | 0 | 6 |
| e3_identity | **200** | 0 | 0 | 1 |
| time | **150** | 0 | 0 | 1 |
| relation | **100** | 0 | 0 | 1 |

对应的 query 标签（`true_edge = 边在 relative_free_adjacency 中`）：

| k | 合并 true_edge 率 | navigation | e3_identity | time | relation |
| --- | --- | --- | --- | --- | --- |
| 0 | 0.400 | 300/300 | 0/200 | 0/150 | 0/100 |
| 1 | 0.455 | 250/250 | 0/150 | 0/100 | 0/50 |
| 2 | 0.571 | 200/200 | 0/100 | 0/50 | — |
| 4 | **1.000** | 100/100 | — | — | — |

后果（必须在读数前说清）：

1. **navigation 全是正类**：k=4 的 `accuracy` 等于"预测为真"的比例，一个恒定输出"有边"的预测器直接得 1.0；`balanced_accuracy` 因无负类退化为 `accuracy`。
2. **另外 3 个 family 全是负类**：`accuracy` 等于"预测为假"的比例，一个从不报边的记忆直接得 1.0；同样没有区分度。
3. **合并后 k=0 的 0.60 是纯标签伪影**：450 条"永远为假"的 query 被"永远预测假"拿满，300 条 navigation 全丢。任何把它读成"零样本基线 0.6"的说法都不成立。
4. 因此该指标当前只能拆成两个可解释量分别报：**覆盖率**（query 目标 cell 是否已在记忆内，见 §3 末列）与**误报率**（3 个静止 family 上的假边），不能报单一 accuracy 曲线。

## 6. 冻结评测路径的两个执行缺陷（与数据无关）

### 6.1 k=1 必然崩溃（阻断整个事后评测）

```python
# evaluation.py:331
run = backend.step_sequence(model, sequence, stop=support[-1] + 1)
# k=1 -> support=[0] -> stop=1
# runtime.py:128-130
frames = len(sequence["obs"]) if stop is None else int(stop)
if frames < 2: raise BackendError("a sequence probe needs at least two frames")
```

实测（隔离副本，真实数据，生产函数本体）：`RuntimeError: a sequence probe needs at least two frames`，在第 1 个世界、k=1 处抛出。`k_values` 顺序是 `(0,1,2,4,8)`，所以 **k=0 已算完但整个 `_evaluate_arm` 抛错、结果不落盘**；k=2/4/8 根本不会被执行到。9 次 arm×seed 评测都会在同一处中断。

### 6.2 support 少写一条

`stop` 是**排他帧界**：`stop=k` → 循环 `t in range(k-1)` → 只执行 `k-1` 条 transition。

| k（请求 support） | stop | 实际执行 transition | 写进记忆的 support |
| --- | --- | --- | --- |
| 1 | 1 | 0（崩溃） | 0 |
| 2 | 2 | 1 | 1 |
| 4 | 4 | 3 | 3 |
| 8 | 8 | 7 | 7（但无世界可用） |

要写 k 条 support 应为 `stop=k+1`（此时 k=1 也自然满足 `frames=2`）。这属于**代码修复**，会改变 `evaluation.py` 的源码身份，必须走新的冻结/复核流程，不在本卡范围；本卡只据实上报。

## 7. 调用量核算（精确，来自插桩计数）

### 7.1 训练 run（arm2/3/4 × seed 各一次，共 9 次）

| 项 | 数量 |
| --- | --- |
| optimizer update | 3510（每次 1 次 forward+backward，batch 16×3 帧） |
| 检查点探针 | 5（updates 0/439/878/1755/3510） |
| 每探针窗口 batch | 35（550 window / batch 16，末批 6） |
| 探针窗口 batch 合计 | **175** |
| 探针帧槽 | 8250（550 window × 3 帧 × 5） |
| 前向 batch 当量（训练+探针） | 3685 |
| 冻结 estimate / deadline / supervision | 359.931 s / 450 s / 500 s |

### 7.2 事后评测 run（arm2/3/4 × seed 各一次，共 9 次）

| 组件 | 按现状（k=1 崩溃） | 若修好 k=1 的完整路径 |
| --- | --- | --- |
| 窗口 forward_loss（5 探针，末检查点复用） | 175 | 175 |
| 窗口帧槽 | 8250 | 8250 |
| `step_sequence` 调用 | 212（topology 200 + M2 11 + few-shot 1 崩溃） | **611**（200 + 400 + 11） |
| 单步 forward | 792（750 + 42） | **1492**（750 + 700 + 42） |
| `probe_graph` | 400（topology 200 + k=0 的 200） | **800**（+k=1 200、k=2 150、k=4 50） |
| `encode` | 1500（只有 k=0 的 750 query × 2） | **3500**（1750 query × 2） |
| few-shot query | 750（只到 k=0） | **1750**（750+550+350+100） |
| 终止 | k=1 `BackendError`，结果不落盘 | 完整 |

注：修复态 `step_sequence` **611** 与 P16 的"~611 次序列前向"完全一致（修复后 k=1/2/4 各写 1/2/4 条 transition，故单步 forward 为 200×1 + 150×2 + 50×4 = 700）；P16 的"1703 帧"我用三种口径都算不出来（崩溃态 1503、修复态 1903、单步 forward 1492），**该数字不可复现，建议一级以本表的逐组件计数为准**。

M2 探针的选点也要说明：`probe_sequences = sequences[:3]`、`history=sequences[3]`、`new_world=sequences[4]`，`sequences` 按 **episode_id（UUID）字典序**排。实测前 5 个世界步数为 4/4/7/3/5，family 为 time/time/navigation/relation/e3_identity —— 这是**按 UUID 排序取前 5**，既不是随机也不是分层，且未在冻结文档中登记为固定选择。

### 7.3 D 候选（1 次）

1 次模型加载 + **1 次** forward_loss（固定批 `symbols (16,2,8)`，32 个 C0 帧槽），S1 六项指标全部 `not_applicable`，只报 `symbol_nll_t0/t1`。

### 7.4 阶段合计（9 训练 + 9 评测 + 1 D）

| 项 | 合计 |
| --- | --- |
| optimizer update | 31,590 |
| 训练期探针窗口 batch | 1,575 |
| 评测窗口 batch | 1,575 |
| 评测 `step_sequence` | 5,499 |
| 评测单步 forward | 13,428 |
| 评测 `probe_graph` | 7,200 |
| 评测 `encode` | 31,500 |
| 冻结 `phase_wall` / 上限 | 4,099.605 s / 14,400 s |
| 事后评测的已登记墙钟 | **0 s** |
| 单次 eval 硬墙钟（CLI `PREP_BUDGET`） | 300 s/次，9 次共 2,700 s（**不在** `phase_wall` 内） |
| GPU/MLX 实测评测墙钟 | **未知/待测** |

## 8. `eval_batches=48` 的定义矛盾

同一个常量在三个位置被当成三件不同的事，而且**都不覆盖真实评测套件**：

1. `runtime.window_probe`：`limit = protocol["eval_batches"]`，`batch_count = min(35, 48) = 35` → **48 是上限，从不生效**。副作用：若将来 dev 窗口数 > 768（`48×16`），探针会**静默只评前 768 个窗口**，覆盖率被悄悄截断，日志里只有 `batches=48` 看不出来。
2. `prereg.estimate_budget`：`eval_cost = 48 × 单批步时 × 5 检查点 = 1.671 s`，被算进**训练 run 的 estimate**（359.931 s）。这是"训练期探针"成本，且相对实际 35 批**超额预留 48/35 = 1.371 倍**。
3. 同一个 `48×5` 又被用于 arm1：`arm1_active = 48 × d_step × 5`（1.502 s），而 arm1 实际只有 **1 次 forward** → **240 倍**超额预留。

而真正的 `--mode eval` 套件（5 探针 + topology + few-shot + M2，611 次序列前向 / 1492 单步 forward / 3500 encode）在冻结文档里**没有任何批数、秒数或额度登记**；`phase_wall = 4099.605 s` 只由 `9×450 + 1×2 + 47.605` 构成（`47.605` 是 `timing.smoke.data_generation_seconds`，与 `data_identity.generation_seconds=45.740` 是两次不同的记录，差 1.865 s，属可解释差异）。

第四条更紧、也更容易被忽略：CLI 的 `PREP_BUDGET["eval"] = 300 s` 是**每次 eval 调用的硬墙钟**（worker 子进程 `timeout`），9 次共 2,700 s，**完全在 `phase_wall` 之外**，账本只按 `0.5×budget` 做墙钟预留。于是真实评测处在"有 300 s/次硬上限、却没有任何调用量登记"的状态：要么 300 s 够（未知，未测），要么在 300 s 被杀。这比 `48 批` 更接近真实约束，但同样不是调用量定义。

结论：**"48 批"从来不是评测调用量的定义**，它只是训练期探针的批上限兼成本参数。要用它当"真实评测量"的批准依据，等于用训练期探针的额度去授权一套 6 倍规模的评测（单步 forward 1492 vs 240）。

## 9. 预算算式（可直接审阅）

```
# 冻结参数（未改）
step = 0.0069624580000891 s   # smoke 实测 batch-16 forward+loss
d_step = 0.0013035410001975833 s
duty = 0.25, overhead = 1.20, update_cost = 3*step = 0.0208873740002673

# 训练 run（每 arm×seed）
updates   = floor((360*0.25/1.20 - 48*step*5) / update_cost) = 3510
estimate  = (3510*update_cost + 48*step*5)/0.25*1.20 = 359.9312287726061 s
deadline  = ceil(1.25*estimate) = 450 s ; supervision = 500 s
# 实际工作：3510 次 optimizer + 175 次探针 batch = 3685 前向 batch 当量

# D 候选
arm1 = (48*d_step*5)/0.25*1.20 = 1.501679232227616 s ; deadline = 2 s
# 实际工作：1 次 forward（16×2 固定批）

# 阶段（冻结口径）
phase_wall = 9*450 + 1*2 + 47.605202459 = 4099.605202459 s  （重算 delta = 0.0）
phase_cap  = 14400 s ; headroom = 10300.394797541 s
# 事后评测在 phase_wall 中占 0 s

# 事后评测（本卡计数，未登记）
per_eval_run = 175 窗口 batch + 611 序列前向 + 1492 单步 forward + 800 probe_graph + 3500 encode
9 次合计     = 1575 窗口 batch + 5499 序列前向 + 13428 单步 forward + 7200 probe_graph + 31500 encode
```

**GPU/MLX 耗时：未知/待测**。理由不是"没算"，而是口径不成立：冻结 smoke 只测 batch-16 前向，而事后评测的 611 次调用是 **batch=1 的单步 forward**（延迟受限，与 batch-16 吞吐不可换算），3500 次 `encode` 与 600 次 `probe_graph` 从未被测过。任何用 0.006962458 s 乘次数的数字都会系统性低估，故不写。

## 10. 两个可审阅选项

### 选项 A：保留冻结数据与 k，只做具备样本的科学结论（不改任何冻结值）

**现在就能报的**（每个数字都带样本量，缺测不填 0、不当通过）：

| 可报项 | 范围 | 状态 |
| --- | --- | --- |
| navigation 的 k∈{0,1,2} 覆盖率 | 50 世界 / 300→250→200 query | 有样本，可报"覆盖率" |
| navigation 的 k=4 | 50 世界 / 100 query | 有样本但**标签 100% 正类**，只能报"预测为真的比例"，不能报 accuracy/balanced |
| time / e3_identity 的 k∈{0,1,2} 误报率 | 各 50 世界 | 有样本，只能报假边率 |
| relation 的 k∈{0,1} | 50 世界 | 有样本，只能报假边率 |
| k=8 全部 family | 0/200 | **insufficient_data**（不是 0 分，也不是通过） |
| k=4 的 relation/time/e3_identity | 0 世界 | **insufficient_data** |
| 跨 family 合并的 k 曲线 | — | **不可报**（k 变则 family 构成变） |

**前置条件（必须先解决，否则 A 也报不出来）**：

1. k=1 崩溃修复（`stop=support[-1]+1` → `+2`，或改 `step_sequence` 语义），并补 k=1 写 1 条、k=4 写 4 条的定向测试；这改变 `evaluation.py` 源码身份，须新冻结 + 非作者复核。
2. 指标口径登记：边存在性指标在 3 个静止 family 上无正类、在 navigation 上无负类，须在指标正文里明确"分 family 分别报覆盖率/误报率"，否则合并 accuracy 无解释力。
3. `query_limit=8` 是否登记为冻结参数（当前只在代码里）。

**A 的代价**：0 新增训练、0 新增数据、0 新增 GPU；只需要一次代码修复 + 重冻结 + 一次非作者复核（CPU）。**A 能回答"这 200 个世界上我们到底能说什么"，不能回答"k=8 会怎样"。**

### 选项 B：未来另批长 episode 数据与评测预算（不改现分区/原实验，需用户逐项批准）

需要用户批准的**精确项**（未批准前一律不启动）：

1. **新数据批（新 digest，不改现有 200 dev / 2000 train）**：为让 k∈{0,1,2,4,8} 都有世界，每世界需 ≥9 条 transition（≥10 个 packet）。当前 dev 是 3–7 packet。建议新批 `200 worlds × ≥10 packets`，用同一个 `awz.V9.B3 r2` 生成器但**新 plan/新 seed**，发布为**新 dataset_digest**，旧数据与其摘要不动。注意：改 `data_identity.plan` 必然改 `dataset_digest`，因此这是**新实验身份**，不是参数微调。
2. **按 family 分层**：新批必须让每个 family 都有 ≥9 transition 的世界，否则 k=4/8 又会退化成单 family / 零样本（当前问题会原样复现）。
3. **评测预算登记（替代 `eval_batches=48`）**：显式登记 `窗口 batch 35×5、序列前向 612、单步 forward 1292、encode 3500、probe_graph 800、D 1`，并**先测** batch-1 单步 forward 与 encode 的 MLX 单位耗时，再换算墙钟；在此之前评测墙钟只能写"未知"。
4. **评测墙钟纳入 `phase_wall`**：现在事后评测占 0 s，`phase_wall` 只覆盖 9 次训练。是否把评测墙钟计入 4 h 阶段上限，需用户裁决（这会改变已登记的 `phase_wall_headroom`）。
5. **`held-out` 语义修订**：现在 query 是 support 前缀的**时间续段**，目标 cell 只有 50%–64% 在记忆内。若目标是"外推/未见区域"，须把 query 限定为**空间上未访问的 cell**；若目标是"下一步预测"，须在指标名与正文里写明。二者是不同的科学主张，不能共用一个 id。
6. **`query_limit=8` 与 `checkpoint_fractions` 的登记**：`query_limit` 目前只是代码常量；5 个检查点里 0 号是"训练前测量"，与其余 4 个不同性质，是否在曲线里同等对待需裁决。
7. **M2 探针选点固定化**：现在按 UUID 字典序取前 5，应改为登记过的固定选择（分层或预注册列表）。

**B 的代价**：新数据生成约 47.6 s CPU（冻结 smoke 实测），**GPU 评测墙钟未知**，训练是否重跑需单独批准（本卡不申请）。**B 不动现分区、不改原实验、不改 k 与训练步数**，只是并行开一条能支撑 k=8 的新证据线。

## 11. 失败与限制（如实写，不当作通过）

- 无任何真实训练/评测；所有计数来自生产函数本体 + 计数替身后端，**替身产生的 accuracy/NLL 全部是插桩副产物，不构成能力或科学结论**，不晋升任何模型。
- `few_shot_report` 在 k=1 抛错，因此**冻结评测路径本身不可完整执行**；本卡不修源码（不在文件范围），只上报。
- k=8 在冻结 dev 上 0/200，k=4 只有 navigation 50/200；**缺测不是通过**，本卡未把任何缺测写成 0 或满分。
- 边存在性指标在 4 个 family 上都没有类别平衡（3 个全负、1 个全正），合并 accuracy 不可解释；本卡未据此给出任何分数。
- 未验证 `arms.py` 的 MLX 数值路径（未导入 MLX）；未验证真实 `_evaluate_arm` 的 RunStore 绑定（本卡只复现其**评测函数调用序列**，绑定段被跳过，未写账本）。
- M2 探针按 UUID 排序取前 5，未做多种子/多选点稳健性检查。
- GPU/MLX 评测墙钟、batch-1 前向与 encode 的单位耗时：**未知/待测**。
- P16 的"1703 帧"不可复现（我三种口径都算不出），已在 §7.2 标注，请一级以逐组件计数为准。
- 未做 git 提交/推送，未写批准行，未改 `RESEARCH_LOG.md`，未读 final 分区，未下载/安装任何东西。

## 12. 交回统筹（需决定，不擅自扩额度或改参数）

1. 是否接受 **k=1 崩溃 + support 少写一条** 为冻结 r5 评测路径的**阻断级缺陷**（它使 9 次事后评测全部无法完成，且 k=0 结果也不落盘）。若接受，需要一张新的代码修复卡（改 `evaluation.py` 的 `stop` 语义 + 定向测试），本卡不申请。
2. 是否接受 **k 曲线按 family 拆开报**、k=8 与 k=4 的缺失 family 一律 `insufficient_data`（选项 A 的核心）。
3. 是否接受 **`eval_batches=48` 不能作为评测调用量的批准依据**，并选择：①先测 batch-1 单步 forward / encode 的单位耗时再登记评测预算；②或直接把评测套件拆成独立预算行（不占用训练 run 的 estimate）。
4. 选项 B 的 7 个精确项是否进入用户批准流程（尤其是"新数据批 = 新 dataset_digest = 新实验身份"这一条，它不是参数微调）。
5. 本卡结论**仅供取舍**：不改 k、世界、分区、训练步数、eval 额度，不写批准行，不构成任何运行授权。

## 13. 产物清单（均在 `reports/V9-P18/`）

- `REPORT.md`：本报告。
- `metrics.json`：结构化指标（身份、k 覆盖、标签平衡、调用核算、预算矛盾、phase 合计）。
- `analysis/count_calls.py`：隔离副本 + 计数后端，跑生产 `evaluation` 函数统计调用量（可重跑）。
- `analysis/truth_stats.py`：纯真值统计（无模型、无后端）。
- `analysis/build_metrics.py`：从冻结文档 + 两个探针结果**重算**预算与合计，生成 `metrics.json`（不手抄数字）。
- `analysis/cpu_coverage.json`、`analysis/truth_stats.json`、`analysis/per_world.json`：逐世界与逐 k 的原始结果。
- `logs/*.out`、`logs/*.err`：三次运行的完整 stdout/stderr。
