# P214 非作者代码复核：S4 第二阶段实现（被审提交 c5387d8）

- 卡：`ainerzero.V9.P214`；复核者：`claude-s4p2rev-1111b`（二级，非作者；作者是一级 claude）；2026-11-11。
- 被审提交 `c5387d8`（含 `7400891`）；设计稿 `reports/V9-S4-P2-DESIGN/DESIGN-r0.md`。
- 开工时仓库 HEAD 是 `5698eef`，被审文件与 `c5387d8` 无差异：`evidence/tests-cpu-live.txt` 开头 10:35 UTC 的 `git diff --stat c5387d8 HEAD` 输出为空。
- **11:12 起，作者在实盘工作树上改了 8 个被审文件，11:43 提交为 `50f9edf`**（设计 r1、散射对照 L-sc-g、门 GR、代码增量），见 §0。所以 `citations.txt` 开头的 `git diff --stat c5387d8 HEAD` 现在不为空；那一段只记录收尾时的状态。
- 我没有改仓库里的源码、测试、设计稿和已有报告，只写本目录。变异与基线都在 `git archive c5387d8` 解出的隔离副本里做。
- 引文全部见 `evidence/citations.txt`，由 `evidence/make_citations.sh` 生成，每段是 `git show c5387d8:文件 | grep -n '' | sed -n 'X,Yp'` 的原始输出，与工作树当前状态无关。

## 结论：建议通过（范围：`c5387d8` 对照 DESIGN-r0）

`c5387d8` 忠实实现了设计稿 §3–§7。门控只读成员状态，门开、门关逐位等于学习模型、E-B；一步覆盖率和重新出现覆盖率的口径、种子平均、Bonferroni m = 11、门槛、负对照 95% 上界、作废规则都与设计一致；运行器的守卫次序与卡片要求逐项相同。复跑的测试全部通过；两项纯 CPU 独立复算和一项真实权重核对与实现逐项一致。

没有必修项。有 5 条应修，都是测试缺口：代码现在是对的，但下面这些写错了测试抓不到。19 个变异：12 个被杀，7 个存活。存活的 7 个里，6 个我用补充测试证明不等价（补充测试在干净副本上全过，在对应变异上失败）；另 1 个（X09）是实数上碰不到的边界，近似等价。卡片指定的 8 类变异中，除「先写标记、后核对权重」的权重文件那一种（M08b）外都被现有测试杀死。补充测试现成放在 `evidence/proposed_tests/`，可直接并入。

**冻结前的条件（不是对 c5387d8 的修改要求）**：作者在 `50f9edf`（11:43）里按设计 r1 改了代码。11:15 我在工作树上看到的改动包括：
- 新增 L-sc-g、L-int-rand 两个臂，新门 GR；
- `N_COMPARISONS = 12`，负对照改用 Bonferroni 上界；
- 带随机数的臂，以及按世界、种子、臂重设生成器；
- `verify_replay_p2.py`、`make_prereg.py` 也有改动。

本报告不覆盖这些改动，也不覆盖 DESIGN-r1。冻结前要对 `c5387d8..50f9edf` 的代码增量另做一次非作者复核。

| 类别 | 编号 | 内容 |
|---|---|---|
| 必修 | — | 无 |
| 应修 | S1 | 种子平均没有有效测试（X04 存活） |
| 应修 | S2 | 「门读 Bonferroni 区间、各统计 m = 11」只测了 GC 一项（X01、X02 存活） |
| 应修 | S3 | GX 读外推记录没有测试（X03 存活） |
| 应修 | S4 | final 下「权重文件 SHA 不符在写标记前拒绝」没有测试（M08b 存活） |
| 应修 | S5 | final「剩余墙钟不够评测预留就拒绝、不写标记」没有测试（X06 存活） |
| 冻结前条件 | F1 | `50f9edf` 的代码增量（按 DESIGN-r1）须另做非作者复核 |
| 备注 | B1–B6 | 见 §5 |

---

## 0. 评审期间工作树的并行改动

下面这些改动后来于 11:43 提交为 `50f9edf`。`evidence/worktree-changes-during-review.txt`（11:15 UTC，当时尚未提交）原始输出节选：

```
 M reports/V9-S4-PHASE2/make_prereg.py
 M reports/V9-S4-PHASE2/verify_replay_p2.py
 M src/ainerzero/v9/experiments/s4/analysis_p2.py
 M src/ainerzero/v9/experiments/s4/gated.py
 M src/ainerzero/v9/experiments/s4/worker_p2.py
 M tests/v9/experiments/test_s4_analysis_p2.py
 M tests/v9/experiments/test_s4_gated.py
 M tests/v9/experiments/test_s4p2_runner_native.py
...
2026-11-11T11:12:12 src/ainerzero/v9/experiments/s4/gated.py
2026-11-11T11:12:53 src/ainerzero/v9/experiments/s4/analysis_p2.py
```

对证据的影响：

- 11:12 之前在实盘仓库跑的有：纯 CPU 测试（10:35）、门控测试（11:05）、真实权重门控核对（11:05）。这几项当时工作树与 `c5387d8` 相同。
- 实盘运行器测试从 11:06 跑到 11:13，与改动时间重叠。这次运行**不作为** c5387d8 的证据（17 项全过，留档于 `tests-mlx-live-runner.txt`）。
- 所以全部基线、两项 CPU 独立复算、真实权重核对又在 `git archive c5387d8` 的干净副本上重跑了一遍，结论以干净副本为准。

---

## 1. 逐条对照设计稿 §3–§7

### 1.1 §3 过程模型与门

| 设计要求 | 代码（`c5387d8`） | 判定 |
|---|---|---|
| L-int-g：门是 L-int 接触头，半径 1.5 内任一盘接触概率 > 0.5 | `gated.py:52` `near = (dist < L.MSG_RADIUS) & ~np.eye(n, dtype=bool)[None]`；`gated.py:53` `return ((np.asarray(logits, dtype=np.float64) > math.log(p / (1 - p))) & near).any(-1)`。logit > log(p/(1−p)) 与 sigmoid(logit) > p 等价；严格大于；不含自身；对盘 i 的所有 j 取「任一」 | 一致 |
| 门限 0.3、0.7 与几何门两臂 | `analysis_p2.py:36` `GATES = {"L-int-g": 0.5, "L-int-g3": 0.3, "L-int-g7": 0.7, "L-int-geo": "geo", "L-ind-geo": "geo"}`；`analysis_p2.py:37` `BASE_MODEL` 中 `"L-ind-geo": "L-ind"` | 一致 |
| 几何门 = 一期接触基线（一步内相接，或已重叠且相向） | `gated.py:41` `hit = ((c <= 0) & (b < 0)) \| ((a > 0) & (disc >= 0) & (b < 0) & (tau >= 0) & (tau < W.DT))`，与 `analysis.py:329-335` 的 `cv_contact_pairs` 逐项相同；`test_s4_gated.py:47-59` 在 300 组随机状态上比对两者 | 一致 |
| 门只读成员状态，不读真值 | `gated.py:69` `def step(P, V, pillars):`——输入只有滤波器传入的成员状态与柱子；门只用 `P, V` 和同一次前向的 `logits`（`gated.py:76-78`） | 一致 |
| 门逐成员、逐盘 | `g` 形状 `[M, n]`，`gated.py:82` `g = g[..., None]` 后逐元素 `np.where` | 一致 |
| 门关逐位等于 E-B，门开逐位等于学习模型 | `gated.py:70` `pb, vb = Mo.bounce(P, V, pillars)`（与 E-B 臂同一函数、同一输入）；`gated.py:83` `return (np.where(g, np.array(p_, dtype=np.float64), pb), np.where(g, np.array(v_, dtype=np.float64), vb))`，学习侧与 `as_process_model` 一样 float32 前向再转 float64 | 一致；§1.6 用真实权重再核一次 |
| 门控代码不得调用世界模块的物理 | E-B 本身就是 `models.py:22` `p, v, _ = W.physics(P, V, pillars, disks=False)`，门关时必然经由它。`gated.py` 不直接引用 `W.physics`、`Mo.true_physics`，`test_s4_gated.py:151-158` 用 AST 检查 | 代码合理；设计措辞宜改（B1） |
| 权重：一期 final 的 L-int#1–3、L-ind#1–3，预登记写 SHA，启动逐个核对 | `run_s4p2.py:50-57` 的 6 个 SHA 与盘上文件、与 `reports/V9-S4-PHASE1/final/final.json` 的 `files_sha256` 逐个相同（§4.5）；`check_weights`（`run_s4p2.py:102-114`）不符即拒绝；final 另比对预登记（`run_s4p2.py:94-95`） | 一致 |
| 不训练 | 运行器、工作进程无训练调用；`make_prereg.py:85` 写 `"training": False` | 一致 |

摸底脚本 `tier1-explore/explore_p2e.py:39-42` 用 `prob = 1 / (1 + np.exp(-np.array(lg, dtype=np.float64)))`、`g = ((prob > gate_p) & (d < L.MSG_RADIUS)).any(-1)[..., None]`，自身距离加 99 排除（第 40 行 `+ np.eye(P.shape[1])[None] * 99`）。实现与摸底是同一个门，只是把 sigmoid 比较换成了 logit 比较，所以摸底定的门槛可以沿用。

### 1.2 §4 跟踪器

所有臂共用 `F.FilterConfig()`（`analysis_p2.py:125`）。默认 32 成员、位置 0.01、速度 0.05、门限 0.6 + 1.5、观测噪声 `W.SIGMA` = 0.05（`filter.py:35-43`）。滤波器种子沿用一期 `A.filter_seed(ns, w, seed, "base")`（`analysis_p2.py:66-67`），各臂共用随机数。一致。

### 1.3 §5 指标

| 设计要求 | 代码 | 判定 |
|---|---|---|
| 一步覆盖率：t−1 和 t 都分到检测的轨迹；t 步更新前的预测集合；均值、样本协方差、90% 椭圆 | 钩子在预测、关联之后、更新之前调用，拿到副本（`filter.py:107-110`）。`analysis_p2.py:102` `if last[k] != t - 1:` 跳过；`_gauss_inside` 用 `np.cov` 与 `CHI2_2_90 = -2 * np.log(0.1)`（`analysis.py:311`） | 一致 |
| 步类按被检测盘在 t−1 → t 的盘间接触 | `analysis_p2.py:100` `touched = {i for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"} \| {j for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"}`；`world.py:127` `contacts: ... # contacts during t -> t+1, truth`，所以 `steps[t-1].contacts` 正是 t−1 → t；被检测盘取 `truth = int(s.truth_ids[r])`（第 104 行） | 一致；M03 被杀 |
| 一步覆盖率三个种子的行合在一起数 | `analysis_p2.py:175-180` `one_step_sums` 对 `SEEDS` 与类别求和再成比 | 一致 |
| 重新出现：a 步持有该盘的轨迹，b 步更新前的集合 | `analysis_p2.py:116` `trk = at[e["a"]][e["k"]]`；`analysis_p2.py:117` 用 `snaps[e["b"]][:, trk]`，`snaps` 在钩子里按 `want = {b}` 记下（更新前） | 一致；M04 被杀 |
| 准确率、重新出现覆盖率每个事件三个种子取平均 | `analysis_p2.py:158` `return np.mean([np.asarray(r["cells"][cell_key(arm, s)][field], dtype=np.float64) for s in SEEDS], axis=0) if r["events"] else np.zeros(0)`，再按世界求和 | 一致；测试分不出（X04 存活 → S1） |
| 独立复算 | 我自己写钩子与椭圆判定，在非登记命名空间 `p214-indep` 的 3 个 6 盘世界上，对 E-P、E-B、E-CV × 3 种子共 27 格重算一步覆盖率（行数、步类、落入数）、重新出现覆盖率、对错和分配摘要，与 `track_cell` 逐项一致：`totals {'rows': 14765, 'coll_rows': 108, 'events': 94, 'coll_events': 16}`、`mismatches []`、`PASSED`（`evidence/indep_coverage_check.txt`，干净副本） | 一致 |

### 1.4 §5 门与统计

门槛（`analysis_p2.py:46-55`）与设计逐项相同：GN −0.01 / −0.03；GA 0.03 / 0；GC 0.75 / 0.5；GK1 全部步点估计 [0.87, 0.93]、区间 [0.85, 0.95]，碰撞步 0.85 / 0.80；GK2 0.85 / 0.80、0.75 / 0.65；GD D 0.8 / 0.7、HF 0.10 / 0.15；GX 0.03 / 0、C 0.6 / 0.4；负对照 C、D 上界 0.5。

比较方向（`analysis_p2.py:284-298`）：点估计用 `_ge`、`_le`（含等号）；下界用 `_gt`（严格）；上界用 `_le`；GK1 全部步区间用 `_ge(k1a, "bonf_low", lo1i)`、`_le(k1a, "bonf_high", hi1i)`；负对照用 `neg = (_lt(st["neg_C"], "ci_high", T["negative_control"]["C_high_below"])`（第 297 行，D 同理在第 298 行）。与设计的「≥」「下界 >」「上界 ≤」「区间在…内」「95% 上界 <」一一对应。

- **Bonferroni m = 11**：`analysis_p2.py:39` `N_COMPARISONS = 11`。我把 `metrics.bootstrap` 换成记录器，记下 `gate_stats` 的 13 次调用：11 个门统计都是 `m=11`，`neg_C`、`neg_D` 是 `m=1`，种子都是 `20261111`。又在合成记录上从头重算 GC 的 10000 次重采样：Bonferroni 区间等于 (0.025/11, 1−0.025/11) 分位，95% 区间等于 (0.025, 0.975) 分位（`evidence/indep_bonferroni_check.txt`，`PASSED`）。代码正确，但测试只核对了 GC 一项（X01、X02 存活 → S2）。
- **负对照用 95% 上界**：`analysis_p2.py:297-298`，统计用 `m=1`（`analysis_p2.py:273`）。一致；M07a、M07b 被杀。
- **作废**：`analysis_p2.py:314-319`。负对照不过时，GA、GC、GX 置 `passed=False, void="negative control failed"`；合法性不过时，所有门 `void="legality failed"`。`valid` 只看合法性（`analysis_p2.py:309`）。一致。
- **无定义按不过**：点值或任一重采样的分母不为正时，`metrics.bootstrap` 不给区间（`metrics.py:89-94`）；`_ge/_gt/_le/_lt` 遇 `None` 返回 False（`analysis_p2.py:245-262`）。一致。
- **按世界配对 bootstrap**：同一统计的分子、分母用同一组世界抽样（`metrics.py:84-85`）。一致。

### 1.5 §5 合法性门与描述量

| 门 | 代码 | 判定 |
|---|---|---|
| 标签 | `verify_labels_p2.py` 与一期 `verify_labels.py` 逐行 diff，只多了隐藏长度一列、逐格 `correct`/`reappear` 长度检查和「空记录不过」 | 一致 |
| 学生视图 | `run_s4p2.py:149-163`：字段白名单＋未来帧变异，用 `E-P` 与 `L-int-g#1` | 一致 |
| 地板 | `analysis_p2.py:227` `floor = not missing and acc["E-CV"] < acc["E-B"] < acc["E-P"]`（有碰撞事件） | 一致 |
| 样本数 | `analysis_p2.py:229-238`：`267 * n_main / 40` 的 ±25%；`analysis.py:37` `EXPECTED_COLL_DISK_STEPS_PER_40 = 552`，552 × 200 / 40 = 2760，下限 75% | 一致 |
| 完整 | `len(main) == n_main and len(extrap) == n_extrap` | 一致 |
| 权重 | 运行结束时再算一次 SHA（`run_s4p2.py:300`） | 一致 |
| 确定性 | `run_s4p2.py:59` `REPLAY_WORLDS = {"main": 3, "extrap": 2}`；`verify_replay_p2.py:37-48` 在另一个 `python -I` 进程里重建全部 27 格，核对分配摘要与逐事件对错 | 一致 |

描述量（一期 L-int、门限 0.3/0.7、几何门、门打开比例、IDF1、轨迹数、1/5/10/30 步误差、外推、按隐藏长度分组）都在 `summarize_descriptive` 与 `kstep_summary` 里。分组边界 `GAP_BINS = (0, 10, 25, 50)` 左闭右开，与设计的「< 10、10–25、25–50、≥ 50」一致。

### 1.6 真实权重上的门控核对（MLX，经锁，干净副本）

`evidence/indep_gate_realweights.py`：用一期 final 的 `L-int#1`、`L-ind#1`（只读），在 `p214-indep` 的一个 6 盘世界和一个 10 盘世界上，让滤波器跑 120 步，记下它实际传给过程模型的成员状态。在这些状态上：

- 我自己按「sigmoid(logit) > p、另一盘在 1.5 内、不含自身」逐元素循环算头门；
- 逐成员调用一期 `cv_contact_pairs` 算几何门；
- 检查 `gated_model` 的输出是否逐位等于「我的门开处取原学习模型、关处取 E-B」，计数器是否与我的计数相同。

干净副本上（锁内）原始输出（`evidence/indep_gate_realweights.txt`，`sources:` 一行确认模块来自干净副本）：

```
L-int-g w0 (6 disks) {'predict_calls': 113, 'open': 155, 'all': 13920, 'share': 0.0111}
L-int-g3 w0 (6 disks) {'predict_calls': 113, 'open': 183, 'all': 13920, 'share': 0.0131}
L-int-g7 w0 (6 disks) {'predict_calls': 113, 'open': 139, 'all': 13920, 'share': 0.01}
L-int-geo w0 (6 disks) {'predict_calls': 113, 'open': 134, 'all': 13920, 'share': 0.0096}
L-ind-geo w0 (6 disks) {'predict_calls': 113, 'open': 134, 'all': 13920, 'share': 0.0096}
L-int-g w1000 (10 disks) {'predict_calls': 119, 'open': 1216, 'all': 35168, 'share': 0.0346}
L-int-g3 w1000 (10 disks) {'predict_calls': 119, 'open': 1708, 'all': 35168, 'share': 0.0486}
L-int-g7 w1000 (10 disks) {'predict_calls': 119, 'open': 932, 'all': 35168, 'share': 0.0265}
L-int-geo w1000 (10 disks) {'predict_calls': 119, 'open': 879, 'all': 35168, 'share': 0.025}
L-ind-geo w1000 (10 disks) {'predict_calls': 119, 'open': 879, 'all': 35168, 'share': 0.025}
mismatches []
PASSED
exit=0
```

结论：真实权重、真实成员状态下，两种门都与我独立实现的门逐元素相同，门控输出逐位等于「门开取学习模型、门关取 E-B」，计数器也对。

门打开比例在 6 盘时约 1%，10 盘时约 2.5–4.9%，量级与设计 §1 的「门打开的盘步占 2.0%」相符。这里只有单个世界、120 步、滤波器成员状态，只作合理性参照。

11:05 在实盘（当时与 c5387d8 相同）跑过同一核对，结果逐行相同（`evidence/indep_gate_realweights-live-1105.txt`）。两项 CPU 核对的早先实盘运行与干净副本运行也逐行相同，用 `diff` 比对过（`-live-1048`、`-live-1050`）。

---

## 2. 守卫与次序（`run_s4p2.py`、`make_prereg.py`）

实际次序（`run_s4p2.py:222-266`）：

1. 第 222 行 `with GD.RunLock(LOCK) as lock:`：拿锁，非阻塞，锁忙即 `GuardError`；
2. 第 223 行 `startup_checks`（函数体 `run_s4p2.py:80-99`）：final 依次查 `python -I`、新字节码目录、冻结清单与已加载模块、第三方版本、**预登记的权重 SHA 与运行器一致**（第 94–95 行）、git 干净；
3. 第 224 行 `weights = check_weights()`：6 个权重文件的 SHA；
4. 第 225 行 `ns = namespace(a.stage)`：smoke 不得读登记分区，probe 不得读 final，final 必须是登记分区；
5. 第 226 行 `check_request(a, pre)`：use id、批准行；
6. 第 230 行运行目录已存在、第 232 行 final 标记已存在，都拒绝；
7. 第 234–235 行 `GD.claim_report(report)`、`out.mkdir(parents=True)`；
8. final：第 259 行 `if deadline.left() < reserve:`，下一行抛 `GuardError`；然后第 262 行 `GD.consume_final_read(lock, FINAL_MARKER, a.approval, pre["final_approval_line"], prereg_sha256=pre_sha, expected_lock=LOCK)`；
9. 第 266 行生成第一个世界，`allow_registered=registered` 只在 final 时为真。

这与卡片要求的「拿锁 → 启动检查 → 权重 SHA → 分区 → 请求 → 标记是否已存在 → 运行目录与报告」逐项相同。只读一次标记写在剩余墙钟检查之后、第一个登记世界之前。预登记权重与运行器不一致时，在第 2 步就拒绝，标记还没写。`consume_final_read` 自己还会核对：持有的是登记锁、批准行一致、标记不存在，并用 `open("x")` 独占创建。

`make_prereg.py:53-57`：

```
53:    # Wall clock: the final evaluates 4x the probe's worlds; 1.5x margin on everything after the marker.
54:    scale = sum(P2.SIZES["final"]) / sum(P2.SIZES["probe"])
55:    eval_reserve = math.ceil(1.5 * scale * pr["post_marker_seconds"])
56:    if 1.2 * pr["pre_eval_seconds"] + eval_reserve > HARD_LIMIT_S:
57:        raise SystemExit(f"预计超出硬上限：评测预留 {eval_reserve} 秒")
```

代入得 scale = (200 + 100) / (50 + 25) = 4，评测预留 = ceil(1.5 × 4 × 探针标记后耗时)，与设计的「探针耗时 × 4 × 1.5」一致。probe 的 `post_marker_seconds` 也从同一位置开始计（`run_s4p2.py:265` `t_post`），覆盖生成世界、评测、写文件、三项核对和分析。硬上限 2 小时（`HARD_LIMIT_S = 2 * 3600`，final 的 `limit` 也是 `2 * 3600`）。

测试覆盖：
- 锁忙、坏请求、smoke 读登记分区、smoke 下权重文件改动或缺失、报告或运行目录已存在、final 缺预登记、未提交、批准行错、缺字节码目录、非 `-I`、预登记权重与运行器不一致、二次 final，都有拒绝测试。
- 缺两条：**final 下权重文件改动在写标记前拒绝**（M08b 存活 → S4）；**剩余墙钟不够评测预留时拒绝且不写标记**（X06 存活 → S5）。两条守卫的代码本身是对的（第 224 行在第 262 行之前；第 259–260 行在第 262 行之前）。

---

## 3. 变异测试

做法（`evidence/mutate_p214.py`，复核者自己编写）：

关于独立性的如实说明：写脚本前，我看过 `tier1-mutants/` 的结果文件和作者脚本 `mutate_p2.py` 的前 50 行。卡片指定的 8 类变异必然与作者自查重合（M01–M07a），这些替换串是我自己写的，有的写法不同：M01 改门而不是交换 `np.where` 的两支，M05 把方向反过来，M07a 同时改 C 和 D。另外 11 个是作者没有做的：M07b、M08a、M08b、X01–X09。

- 每个变异一份全新副本，`git archive c5387d8 src tests pyproject.toml reports/V9-S4-PHASE2` 解出；运行器测试另从实盘只读复制 6 个权重文件进副本。
- 逐字替换，替换前断言原文恰好出现 1 次。
- `PYTHONPATH` 指向副本的 `src`，并用 `importlib.util.find_spec` 确认 `gated`、`analysis_p2`、`worker_p2` 都来自副本。
- pytest 退出码 1 才算 killed，0 为 SURVIVED，其他为 ERROR。
- 门控、运行器变异在共享锁内跑；运行器变异加 `-x`。

| 编号 | 变异 | 改哪里 | 结果 | 杀死它的测试 / 存活原因 |
|---|---|---|---|---|
| M01 | 门开、门关互换（`g = ~g[..., None]`） | `gated.py:82` | killed（3 failed, 5 passed） | `test_closed_gate_is_eb_and_open_gate_is_the_learned_model_bit_for_bit` 等 3 项 |
| M02 | 头门比较改成 `>=` | `gated.py:53` | killed（1 failed, 7 passed） | `test_head_gate_threshold_and_neighbourhood` |
| M03 | 一步覆盖率步类改用 `steps[t].contacts` | `analysis_p2.py:100` | killed（1 failed, 47 passed） | `test_one_step_rows_classify_by_the_contact_in_the_previous_step` |
| M04 | 重新出现改用 b 步持有该盘的轨迹 | `analysis_p2.py:116` | killed（1 failed, 47 passed） | `test_reappearance_uses_the_track_held_at_a_and_the_ensemble_at_b` |
| M05 | GN 下界判据方向反了（`_gt` → `_lt`） | `analysis_p2.py:285` | killed（32 failed, 16 passed） | `test_decide_fails_each_gate_at_its_boundary[GN-stat0-GN]` 等 |
| M06 | GK1 去掉区间条件 | `analysis_p2.py:288` | killed（3 failed, 45 passed） | `test_decide_fails_each_gate_at_its_boundary[GK1_all-stat7/8/25-GK1]` |
| M07a | 负对照改用 95% 下界 < 0.5 | `analysis_p2.py:297-298` | killed（4 failed, 44 passed） | `test_negative_control_needs_a_small_upper_bound[...]`、`test_negative_control_reads_the_95_percent_upper_bound` |
| M07b | 负对照完全改回一期写法（95% 下界 < 0.25） | `analysis_p2.py:54, 297-298` | killed（4 failed, 44 passed） | 同上 |
| M08a | 运行器：预登记权重比对挪到写标记之后 | `run_s4p2.py:94-95 → 262 后` | killed（1 failed, 15 passed，`-x`） | `test_final_refuses_weights_that_differ_from_the_preregistration` |
| M08b | 运行器：final 时权重文件 SHA 核对挪到写标记之后（smoke、probe 不变） | `run_s4p2.py:224 → 262 后` | **SURVIVED**（17 passed） | **测试漏了**：权重文件改动只在 smoke 上测（`test_changed_or_missing_weights_are_refused_before_anything`），final 路径没有。补充测试在 M08b 上失败 → S4 |
| X01 | GC 下界改读 95% 区间 | `analysis_p2.py:287` | **SURVIVED**（48 passed） | **测试漏了**：边界测试的 `_st`（`test_s4_analysis_p2.py:234-236`）让 `ci_low`/`ci_high` 默认等于 Bonferroni 界，分不出读的是哪一个 → S2 |
| X02 | GD 的 D 统计用 m = 1 | `analysis_p2.py:271` | **SURVIVED**（48 passed） | **测试漏了**：`test_bonferroni_is_eleven_comparisons` 只核对 GC → S2 |
| X03 | GX 的 C 误读主评测 | `analysis_p2.py:272` | **SURVIVED**（48 passed） | **测试漏了**：合成外推记录与主评测用同一组臂参数，C 相近 → S3 |
| X04 | 种子平均只取种子 1 | `analysis_p2.py:158` | **SURVIVED**（48 passed） | **测试漏了**：`test_seed_averaging_per_event` 用 5 个事件、非碰撞正确率 0.89，这一抽样下所选事件三个种子全是 1。我在副本里打印过：`[[1, 1, 0, 1, 1], [1, 1, 1, 1, 1], [1, 1, 0, 1, 1]] [0, 0, 1, 1, 0]`，选中的非碰撞事件（0、1、4）三种子都是 1 → S1 |
| X05 | GK2 有碰撞改用全部事件 | `analysis_p2.py:270` | killed（2 failed, 46 passed） | `test_collision_reappearance_coverage_below_threshold_fails` 等 |
| X06 | 运行器：删掉写标记前的剩余墙钟检查 | `run_s4p2.py:259-260` | **SURVIVED**（17 passed） | **测试漏了**：没有测试让剩余墙钟小于评测预留。补充测试在 X06 上失败 → S5 |
| X07 | 运行器：请求检查挪到占报告、建目录之后 | `run_s4p2.py:226 → 235 后` | killed（1 failed, 3 passed，`-x`） | `test_bad_requests_claim_nothing[args0-needs a use id]` |
| X08 | `make_prereg`：评测预留去掉 1.5 倍余量 | `make_prereg.py:55` | killed（1 failed, 14 passed，`-x`） | `test_final_path_after_a_frozen_probe` |
| X09 | 几何门 `tau < DT` 改 `tau <= DT` | `gated.py:41` | **SURVIVED**（8 passed） | **近似等价**：只在 τ 恰好等于 0.1 时不同；成员状态是连续实数，这个边界碰不到。若要钉死与一期基线一致，可加一条构造 τ = DT 的边界测试（备注 B2） |

合计：19 个变异，12 个被杀，7 个存活（M08b、X01、X02、X03、X04、X06、X09），没有 ERROR。基线（未变异的副本）：分析测试 `48 passed`，门控测试 `8 passed`，运行器测试 `17 passed`。原始输出：`evidence/mutants-cpu-batch1.txt`、`mutants-cpu-batch2.txt`、`mutants-cpu-baseline.txt`、`mutants-mlx-gated.txt`、`mutants-mlx-runner-batchA.txt`、`mutants-mlx-runner-batchB.txt`。

说明：
- 纯 CPU 的 11 个变异是用 `mutate_p214.py` 加 `--jobs` 选项之前的版本跑的，副本做法、替换和 pytest 命令都相同；加 `--jobs` 后我用新版在两个 CPU 条目（X05、`unmutated_cpu`）上自检，结果相同。
- `mutants-mlx-runner-batchA.txt` 里基线与 M08b 两份耗时都是 271.30 s。两份副本各自独立：M08b 副本的 `run_s4p2.py` 含变异串，基线副本不含，两份 `pytest-output.txt` 也各自独立。两者同时起跑、工作量相同，所以耗时一样。M08b 是真变异，由 §3.1 补充测试在它上面失败印证。

### 3.1 存活变异的补充测试（证明不等价）

`evidence/proposed_tests/` 里两份测试：`test_p214_analysis_gaps.py`（纯 CPU，15 项）和 `test_p214_runner_gaps.py`（MLX，2 项）。由 `evidence/run_proposed_tests.py` 复制进新副本运行。期望：干净副本全过，对应变异失败。

分析组原始输出（`evidence/proposed-tests-analysis.txt`）：

```
== analysis on clean: exit=0 (should pass) -> as expected  15 passed in 28.29s
== analysis on X01_GC_uses_95_not_bonferroni: exit=1 (should fail) -> as expected  1 failed, 14 passed in 29.06s
   FAILED tests/v9/experiments/test_p214_analysis_gaps.py::test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones[GC-GC-stat2]
== analysis on X02_GD_D_bonferroni_m1: exit=1 (should fail) -> as expected  1 failed, 14 passed in 28.14s
   FAILED tests/v9/experiments/test_p214_analysis_gaps.py::test_every_gate_statistic_is_bonferroni_corrected_and_the_control_is_not
== analysis on X03_GX_C_from_main_records: exit=1 (should fail) -> as expected  1 failed, 14 passed in 29.26s
   FAILED tests/v9/experiments/test_p214_analysis_gaps.py::test_GX_reads_the_extrapolation_records
== analysis on X04_seed_average_seed1_only: exit=1 (should fail) -> as expected  1 failed, 14 passed in 30.47s
   FAILED tests/v9/experiments/test_p214_analysis_gaps.py::test_event_values_are_averaged_over_the_three_seeds
```

运行器组原始输出（锁内，`evidence/proposed-tests-runner.txt`）：

```
== runner on clean: exit=0 (should pass) -> as expected  2 passed in 61.25s (0:01:01)
== runner on M08b_weight_files_checked_after_marker_in_final: exit=1 (should fail) -> as expected  1 failed, 1 passed in 61.21s (0:01:01)
   FAILED tests/v9/experiments/test_p214_runner_gaps.py::test_final_refuses_a_changed_weight_file_before_the_marker
== runner on X06_reserve_check_removed: exit=1 (should fail) -> as expected  1 failed, 1 passed in 93.29s (0:01:33)
   FAILED tests/v9/experiments/test_p214_runner_gaps.py::test_final_refuses_when_the_wall_clock_left_is_below_the_reserve
```

---

## 4. 复跑测试（原始输出）

### 4.1 实盘仓库，10:35（工作树 = c5387d8），纯 CPU

```
$ .venv/bin/python -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s4_analysis_p2.py tests/v9/experiments/test_s4_world.py tests/v9/experiments/test_s4_analysis.py
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 41.92s
```

### 4.2 实盘仓库，11:05（工作树 = c5387d8），门控测试经锁

```
$ .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4_gated.py
lock held by 28738
........                                                                 [100%]
8 passed in 0.37s
exit=0
```

### 4.3 干净副本（git archive c5387d8）基线

```
== unmutated_cpu: 不改，纯 CPU 分析测试基线（可不经锁）
   result: baseline-ok  exit=0  48 passed in 33.09s
== unmutated_runner: 不改，运行器测试基线（MLX，经锁）
   result: baseline-ok  exit=0  17 passed in 271.30s (0:04:31)
== unmutated_gated: 不改，门控测试基线（MLX，经锁）
   result: baseline-ok  exit=0  8 passed in 1.33s
```

### 4.4 实盘运行器测试（不计入，见 §0）

`tests-mlx-live-runner.txt`：`17 passed in 421.86s`，11:06–11:13，与作者改动时间重叠。

### 4.5 权重 SHA

`evidence/weights-sha.txt` 里依次是：盘上 6 个文件的 `shasum -a 256` 输出、`c5387d8` 的 `run_s4p2.py:50-57` 常量、一期 `final.json` 的 `files_sha256`，以及三方比对。比对的原始输出：

```
$ 三方逐个比对
disk == runner: True | runner == phase-1 final.json: True
```

### 4.6 实盘 `artifacts/v9/s4/` 没有新文件

开工时（10:26:46 UTC）记下 `artifacts/v9/s4/` 的文件清单（77 个文件），收尾时（11:46 UTC）再记一次。原始输出（`evidence/artifacts-check.txt`）：

```
$ find artifacts/v9/s4 -type f | sort > artifacts-s4-after.txt; diff artifacts-s4-before.txt artifacts-s4-after.txt
diff exit=0
$ find artifacts/v9/s4 -newer <开工时间戳 10:26:46 UTC> -print
(end)
$ find artifacts -newer <开工时间戳> -name "*s4p1-*" -o -newer <开工时间戳> -name "*s4p2-*"
(end)
```

没有新增或改动的文件，也没有生成任何 `s4p1-*`、`s4p2-*` 世界。我的世界只用了非登记命名空间 `p214-indep`、`test-s4p2-hook`（仓库测试自带）和运行器测试的替身命名空间，都只在内存或临时副本里。其他运行都在 `$TMPDIR` 下的副本里：变异、基线、补充测试，以及运行器测试的假仓库。

---

## 5. 应修与备注

**应修**（都是测试，不在冻结清单里，可与探针并行补；现成测试见 `evidence/proposed_tests/`）：

- **S1 种子平均。** 现有测试的抽样让三个种子在所选事件上取值相同。改成三个种子取值不同的构造，例如种子 1 全对、种子 2、3 全错，期望每事件 1/3。见 `test_event_values_are_averaged_over_the_three_seeds`。
- **S2 Bonferroni。** 有两件事要测：
  - 边界测试要让 95% 界与 Bonferroni 界不同，取「95% 能过、Bonferroni 不过」的组合，逐门断言不过；
  - 断言 11 个门统计的 Bonferroni 区间都严格宽于 95% 区间，负对照两项两者相同。
  
  见 `test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones`、`test_every_gate_statistic_is_bonferroni_corrected_and_the_control_is_not`。作者在 `50f9edf` 里已把负对照改为读 Bonferroni 上界、m 改为 12，补测试时要按 DESIGN-r1 调整。
- **S3 GX 读外推。** 构造外推上差值能过、C 不过，主评测正常，断言 GC 过、GX 不过。见 `test_GX_reads_the_extrapolation_records`。
- **S4 final 下的权重文件。** 冻结预登记后改一个权重文件再跑 final，断言拒绝、没有标记、没有报告。见 `test_final_refuses_a_changed_weight_file_before_the_marker`。
- **S5 final 的剩余墙钟检查。** 把预登记的 `eval_reserve_s` 设得大于硬上限，再跑 final，断言以「the final read is not spent」拒绝、没有标记。见 `test_final_refuses_when_the_wall_clock_left_is_below_the_reserve`。

**备注：**

- **B1** 设计 §3「门控代码不得调用世界模块的物理」与 E-B 的定义冲突：E-B 就是 `W.physics(disks=False)`，门关时一定经由它。实现与测试都按「不得直接调用 `W.physics`、不得调用 `true_physics`」理解，这是唯一合理的读法。建议设计改为「不得调用带盘间碰撞的物理（E-P）」。
- **B2** X09（`tau <= DT`）近似等价。如要与一期基线逐位一致，可加一条 τ 恰为 DT 的构造测试。
- **B3** 实盘运行器测试与作者改动重叠，不计入（§0）。
- **B4** 卡片标题写 `7400891`，参数是 `c5387d8`。本复核按参数审 `c5387d8`（它包含 `7400891`）。
- **B5** `world.py` 的登记分区改动会改变一期冻结清单里的文件。一期 final 已读、已复算，没有影响；只是一期运行器的 final 不能再在当前代码上原样启动，这本来就不允许。
- **B6** 确定性门只重放分配摘要与对错，不重放两种覆盖率。设计只要求这两样；覆盖率与跟踪同一遍算，钩子只读副本，§1.3 的独立复算在手写臂上逐项一致。如要更稳，可让 `verify_replay_p2.py` 也比对 `one_step` 与 `reappear`。
