# P215 非作者复核：S4 第二阶段设计稿 r1（对照臂 L-sc-g 与新门 GR）

- 复核者：`claude-s4p2rev-b-1111`（非作者，没有参与 S4 二期的设计和代码）。
- 被审：`DESIGN-r1.md`，提交 `50f9edf`。当前 HEAD `6ee8aaa`；`src/`、设计稿、`tier1-explore/` 自 `50f9edf` 起没有改动（`git diff --stat 50f9edf HEAD` 为空）。
- 日期：2026-11-11。
- 接手说明：
  - 本卡前一持有者 `claude-s4p2rev-1111a` 停滞，按参数 v1 交到本目录。
  - 它在 `r1-review/evidence/` 留下的东西我只当输入，逐项核实过：读了脚本，确认只写自己的证据目录、只用 `s4x-p2a`、权重只读；能复跑的都复跑了。
  - 复用的脚本原样复制到本目录，原文件的 SHA 记在 `evidence/inputs-from-previous-holder.sha256`。
- 执行范围：
  - 没有改源码、测试、设计稿和已有报告，没有提交；
  - 没有写 `artifacts/`，没有生成 `s4p1-*`、`s4p2-*` 世界；
  - MLX 只在共享锁下用过一次（复跑 3 个世界）。

## 结论：建议通过

r1 处理了 P213 的全部必修、应修和建议；只有 S3 的一个小细节没写出来，不影响结论。

新对照臂 L-sc-g 的实现与设计描述一致，新门 GR 站得住：
- 我分析了四个粗糙响应：置零、反向、按两盘连线镜面反射、解析弹性交换。不懂碰撞的置零和反向比 L-sc-g 还差。
- 镜面反射也过不了 GR。
- 只有解析弹性交换（手写物理）能过 GR，下界 +0.005。所以 GR 既不是随手能过的门，也不是谁都过不了的门。

其余几项：
- 结论措辞已经收窄到位；
- G 轮门统计逐行复现；
- r1 新增或改动的数字，我独立精确比对了 34 个，全部一致。

有三条建议，见末尾，都不阻塞。

## 1. P213 的意见是否处理

依据见 `evidence/citations.txt`（每处引文的 `grep -n` 原始输出）。

| P213 | 判定 | 依据 |
|---|---|---|
| **M1** 负对照挡不住「知道什么时候、不知道怎样碰」 | **已处理** | 按 (a)：登记 L-sc-g（`analysis_p2.py` `ARM_SPEC["L-sc-g"] = ("L-int", 0.5, "scatter")`），加 GR（`THRESHOLDS["GR"]`、`gate_stats` 的 `"GR": acc_diff(main, a, SCATTER_ARM, "collision")`，m 改为 12）。GA、GC、GK 的结论改为「门控混合跟踪器」（DESIGN-r1.md:43、:197），归因只留给 GR 和 GD（:198） |
| **S1** 「没有盘间接触」应为「没有盘间重叠」 | **已处理** | DESIGN-r1.md:281 |
| **S2** 「持平」的范围；GK1 全部步主要由门关盘步决定 | **已处理** | :127（「它不说明学到的响应接近物理」）、:128、:269、:284 |
| **S3** 「谁过不了」与门槛理由 | **已处理（一处细节未写）** | §5 表新增「谁过不了」列（:179–188）；「每个门检验什么」（:194–198）写了 GN 是非劣门、SCATTER 只差 0.002–0.012、GX 靠 C 下界 0.287 挡住 SCATTER |
| **S4** 数字与表述 | **已处理** | 0.0368 秒与 0.0176 秒、2.1 倍（:120，见第 5 项）；门限 0.3、0.7 拆成两行（:75–76）；§0 的 0.60、0.86 注明没有碰撞的事件（:31）；§7 单世界耗时写了出处（:254–255） |
| **R1** 负对照用 Bonferroni 上界 | **已处理** | :190；代码里 `"neg_C": C_of(main, NEG_ARM)` 取默认 m = 12，`decide` 读 `bonf_high` |
| **R2** 随机门登记为描述量 | **已处理** | L-int-rand（:157，`ARM_SPEC["L-int-rand"]`） |
| **R3** 代码约束的写法 | **已处理** | :162；§0 :45 写明 E-B 是生成器同一函数去掉盘间碰撞 |
| **R4** 摸底对随机数敏感；探针在空闲时测耗时 | **已处理** | §5 改用 G 轮（登记种子）；:61 写了 F 轮 +0.018 对 G 轮 +0.003；:248 写了空闲时跑、预留按 × 4 × 1.5 算 |

S3 没写出来的细节：P213 说门永远开时「GC 对它并不稳」。r1 的 GC 行只写了一期 L-int 0.665，用的是 G 轮的值，已经低于 0.75 的门槛，所以不写也不误导。

## 2. 新门 GR 与对照臂 L-sc-g

### L-sc-g 是不是公平的对照：是

`gated.py` 第 56–70、116–127 行（`evidence/citations.txt`）：

| 方面 | 实现 |
|---|---|
| 门 | `head_gate(logits, P, 0.5)`，与 L-int-g 是同一个函数、同一个门限，只读成员状态 |
| 位置 | `pb`，即 E-B 的位置 |
| 速度 | `scatter_velocity(vb, theta)`，`theta ~ U(0, 2π)`，每个成员、每个盘独立；转角不改速率 |
| 随机数 | 自己的生成器；没 `reseed` 就报错 |

一点说明：规则相同，不等于实际打开的比例相同。L-sc-g 的门打开 2.9%，L-int-g 是 1.4%。打乱方向后成员更容易彼此靠近，门就开得更多。r1 :124 把 L-sc-g 在没有碰撞事件上的劣势（−0.022）归因于「在误报的门上打乱了速度方向」，与这个现象一致。

### GR 的判据：合理

- 判据：有碰撞事件上的差 ≥ 0，且 Bonferroni 下界 > 0（m = 12，GN、GA、GC、GK1×2、GK2×2、GD×2、GX×2、GR，与 :211 和 `N_COMPARISONS` 一致）。这是不设余量的优越性检验。
- 负对照失败时，`evaluate` 只作废 GA、GC、GX，不作废 GR。GR 的比较对象是 L-sc-g，不依赖负对照，这样处理是对的。

### 还有没有简单代用模型能过 GR，或让 GR 失去意义：没有

试了四个代用模型（`evidence/surrogates/`），门都与 L-int-g 相同，位置取 E-B，只有门开时的速度不同：

| 代用模型 | 门开时的速度 |
|---|---|
| H-zero | 置零 |
| H-rev | 反向 |
| H-mirror | 按到最近盘的连线做镜面反射 |
| H-elastic | 与最近盘做等质量弹性交换，相向时才交换；这是生成器自己的碰撞定律 |

数据来源与核实：
- 跟踪记录由前一持有者在 40 个 `s4x-p2a` 主世界上跑完（`track_heuristics.py`，用登记的 `analysis_p2.world_record` 和登记的滤波器种子）。
- 我在共享锁下复跑了前 3 个世界，36 格**逐字段相同**（`evidence/surrogates/run_rerun.log`）。
- 合并 G 轮记录时，逐世界核对了事件列表相同。分析用登记的统计函数（`analyze_heuristics.py`，输出 `heuristics-analysis.txt`、`heuristics-analysis.json`）。
- 命令：
  ```
  sh reports/V9-S4-P2-DESIGN/r1-review-b/evidence/surrogates/run_rerun.sh
  .venv/bin/python -I -B reports/V9-S4-P2-DESIGN/r1-review-b/evidence/surrogates/analyze_heuristics.py \
    reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json \
    reports/V9-S4-P2-DESIGN/r1-review/evidence/surrogates/records-heuristics.json \
    reports/V9-S4-P2-DESIGN/r1-review-b/evidence/surrogates/heuristics-analysis.json
  ```

原始输出：

```
arm        coll   non    all    C      1step all/coll   reappear non/coll   D       HF
E-B        0.422 0.876 0.776 0  0.830/0.592      0.856/0.474        —      —
E-P        0.679 0.885 0.840 1  0.907/0.907      0.912/0.830        —      —
L-int-g    0.658 0.879 0.831 0.917  0.903/0.892      0.910/0.818      0.852  0.026
L-sc-g     0.612 0.857 0.803 0.738  0.901/0.858      0.890/0.755      -0.129  0.058
H-zero     0.559 0.851 0.787 0.534  0.826/0.653      0.839/0.486      0.182  0.045
H-rev      0.601 0.841 0.788 0.694  0.867/0.717      0.864/0.627      -0.249  0.091
H-mirror   0.628 0.862 0.811 0.801  0.893/0.825      0.896/0.763      0.346  0.061
H-elastic  0.678 0.875 0.832 0.995  0.903/0.893      0.908/0.825      0.833  0.048

as main arm (registered decide; no extrapolation run, so GX fails by construction):
L-int-g    {'GN': 1, 'GA': 1, 'GC': 1, 'GK1': 1, 'GK2': 1, 'GD': 1, 'GX': 0, 'GR': 0}
L-sc-g     {'GN': 0, 'GA': 0, 'GC': 0, 'GK1': 0, 'GK2': 1, 'GD': 0, 'GX': 0, 'GR': 0}
H-zero     {'GN': 0, 'GA': 0, 'GC': 0, 'GK1': 0, 'GK2': 0, 'GD': 0, 'GX': 0, 'GR': 0}
H-rev      {'GN': 0, 'GA': 0, 'GC': 0, 'GK1': 0, 'GK2': 0, 'GD': 0, 'GX': 0, 'GR': 0}
H-mirror   {'GN': 0, 'GA': 1, 'GC': 1, 'GK1': 0, 'GK2': 1, 'GD': 0, 'GX': 0, 'GR': 0}
H-elastic  {'GN': 1, 'GA': 1, 'GC': 1, 'GK1': 1, 'GK2': 1, 'GD': 1, 'GX': 0, 'GR': 1}

GR comparisons on collision events, value [Bonferroni m=12]:
H-zero                   {'arm_minus_L-sc-g': [-0.0524, -0.1173, 0.0152], 'L-int-g_minus_arm': [0.0986, 0.0345, 0.1695], 'arm_minus_L-sc-g_non_collision': [-0.006, -0.0254, 0.0123]}
H-rev                    {'arm_minus_L-sc-g': [-0.0112, -0.0788, 0.0577], 'L-int-g_minus_arm': [0.0574, -0.0152, 0.1326], 'arm_minus_L-sc-g_non_collision': [-0.0155, -0.0356, 0.0037]}
H-mirror                 {'arm_minus_L-sc-g': [0.0162, -0.0393, 0.0753], 'L-int-g_minus_arm': [0.03, -0.0358, 0.1001], 'arm_minus_L-sc-g_non_collision': [0.0056, -0.0093, 0.0208]}
H-elastic                {'arm_minus_L-sc-g': [0.0662, 0.0046, 0.1331], 'L-int-g_minus_arm': [-0.02, -0.0661, 0.0179], 'arm_minus_L-sc-g_non_collision': [0.0186, -0.0061, 0.0428]}
L-int-g (registered GR)  {'arm_minus_L-sc-g': [0.0462, -0.0026, 0.0988]}
```

每项是 [点估计, Bonferroni 下界, Bonferroni 上界]。

读法：
- **L-sc-g 是比「不懂碰撞的简单做法」更强的对照。**
  - 置零、反向都比它差，C 只有 0.534、0.694，每个门都不过。
  - 所以 GR 的比较对象不是一个随手就能超过的稻草人。
  - 「放宽集合」本身就有价值：它比把速度清零或反向都好。
- **镜面反射（H-mirror）过不了 GR。**
  - 它用两盘连线的几何把速度反射回去，是一条半懂碰撞的解析规则。GA、GC、GK2 都过了，但 D 只有 0.346，GD 挡住它。
  - L-int-g 相对它是 +0.030，区间含 0。所以 GR 过了，说明的是「胜过乱猜方向」，**不说明胜过一条粗糙的几何规则**。r1 的措辞（:205「胜过『知道什么时候、碰时乱猜方向』」，:207「比乱猜方向强」）正是这个范围，没有说过头。
- **H-elastic 是这个门下的「正确响应」参照。**
  - 它过 GR（下界 +0.005）和除 GX 以外的全部门（GX 没跑外推，按构造不过）。
  - L-int-g 相对它是 −0.020 [−0.066, +0.018]，区间含 0。
  - 这说明两点：
    - GR 原则上可过；
    - 40 个世界上，即使响应正确，GR 的下界也只比 0 高一点，GR 在这个规模上功效有限。
  - 这支持 :206 的推断：final 有 200 个世界，区间宽度约为现在的 √(40/200) ≈ 0.45 倍。
- **镜面反射和弹性交换为什么不能是登记臂。**
  - 它们是解析碰撞响应，违反 §3 的代码约束：门控模型只调用 E-B，不调用 E-P；门开时的响应来自学习模型。
  - 弹性交换就是生成器自己的碰撞定律，等于在门开时把 E-P 拼回来。
  - 它们只能作参照，见建议 B。

## 3. 结论的措辞是否收窄到位：是

- §0 :43：「(1)–(3) 说的是**门控混合跟踪器**……只有 (4) 把收益归给学到的响应；学到的响应本身准不准，由 GD 回答」。
- §1 读法：
  - :121「门控混合跟踪器在这个滤波器里与 E-P 持平」；
  - :122–126 把持平的大部分归给「知道什么时候碰」加「碰时放宽集合」；
  - :127 明说「它不说明学到的响应接近物理」。
- §5「每个门检验什么」：
  - :197「这几个门的结论只说『门控混合跟踪器』，不把收益归给学到的响应」；
  - :198「能把收益归给学到的响应的，只有 GR（重认上）和 GD（动力学上）」。
- §9 :284：
  - 「门控混合跟踪器在这个滤波器里的重认与校准与 E-P 持平」；
  - 「学到的响应在动力学上补回 E-B 碰撞误差的 85%（GD），在重认上是否胜过乱猜方向由 GR 判定」。

没有找到把 GA、GC、GK 的收益归给学到的响应的句子。§0 :35 的「与真实物理 E-P 持平」前面有「在这个滤波器里」，范围是清楚的。

## 4. G 轮能否复现：能

- **重算：**
  - 用登记的 `analysis_p2.gate_stats`、`decide`、`summarize_descriptive`，从 `results-p2g.json`（SHA `af81910b…`）重算。打印格式照搬 `explore_p2g.py`。
  - 命令：`.venv/bin/python -I -B reports/V9-S4-P2-DESIGN/r1-review-b/evidence/repro/recompute_p2g.py reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json`
  - 与 `summary-p2g.txt`（去掉锁和耗时那两行）逐行 `diff`，结果 `IDENTICAL`（`evidence/repro/summary-p2g-diff.txt`）。
  - 另外和 JSON 里存的统计逐字段比对：`stored stats identical to recomputed: True; stored passed identical: True; stored negative control identical: True`。
- **复放：**
  - 前一持有者用登记的 `worker_p2` 复放了主评测前 2 个、外推第 1 个世界，99/99 格逐字段一致（`r1-review/evidence/repro/replay_p2g.txt`）。我读了脚本，它只打印、不写文件。
  - 我没有重复这次复放。我复跑的是另一批（代用模型的 3 个世界，见第 2 项），同样逐字段一致。
  - 复放输出里，主世界 1 的 `L-sc-g#2` 与 `#3` 分配摘要相同。我查过：这种跨种子摘要相同在 60 个世界里常见（E-B 12 次、L-int-g 15 次、L-sc-g 11 次），因为关联没有歧义时分配与滤波器种子无关。这不是随机数没生效。

## 5. 数字抽查

**我的独立抽查：34 / 34 一致**（`evidence/numbers/spot_numbers_b.py`、`spot_numbers_b.txt`）。
- 每条写明设计稿的行号和它应含的原文片段，以及来源文件和它应含的原文片段。
- 两边按整词精确匹配（前后不能接数字或小数点），并打印两边的原始行。
- 覆盖的数字：
  - L-sc-g 主评测一行的 7 个数，外推一行的 3 个数；
  - L-int-rand 的 C 与重新出现覆盖率；
  - L-int-g − L-sc-g 的三个 95% 区间与外推的有碰撞区间；
  - GR 的点估计与 Bonferroni 区间；
  - 负对照 C、D 的上界；
  - G 轮动力学的 4 个数；
  - GX 的两个区间；
  - F 轮门限 0.3、0.7 的 3 个数；
  - 残差训练 0.0368 秒（`run-p2b2.log` 的 R#1 736 秒 / 20000 步）、一期 0.0176 秒（`final.json` 的 L-int#1 352.3 秒 / 20000 步）、比值 2.09；
  - R#3 第 14000 步的损失 3502；
  - G 轮 970 秒。

**前一持有者的核对脚本**（`check_r1_numbers.py`）：我原样复跑，`117 numbers checked, 117 found`，与它的输出逐行相同。

它判「对上」的方式是在设计稿那一行里做子串查找，偏宽松：例如 `0.03` 会匹配上 `0.034`。所以我不把它的 117 当作独立证据，只当作佐证。

## 建议（都不阻塞）

- **A.** §5 GR 行的「谁过不了」可以补上本复核的代用模型结果，并写明 GR 过了只说明「胜过乱猜方向」，不说明胜过粗糙的几何规则：
  - 置零 −0.052、反向 −0.011（相对 L-sc-g）；
  - 镜面反射 +0.016，下界 −0.039。
- **B.** 可以考虑把 H-elastic（同一个门，门开时用解析弹性交换）登记为**描述用参照**，不设门、明确标为手写物理。
  - 它衡量的是：在同一个门下，学到的响应离正确响应还差多少。G 轮是 −0.020 [−0.066, +0.018]。
  - 代价是每个世界多 3 格，约 +9%。
- **C.** S3 的「GC 对一期 L-int 并不稳」没写出。G 轮 0.665 已低于门槛，可以不补。

## 证据清单

| 路径（相对 `evidence/`） | 内容 |
|---|---|
| `inputs-from-previous-holder.sha256` | 复用的前一持有者文件的 SHA |
| `repro/recompute_p2g.py`、`summary-p2g.recomputed.txt`、`recompute_p2g.stderr`、`summary-p2g-diff.txt` | 第 4 项 |
| `surrogates/track_heuristics.py`（原样复制）、`check_responses.py`（原样复制）、`run_rerun.sh`、`rerun-3-worlds.json`、`compare_rerun.py`、`run_rerun.log` | 第 2 项的复跑 |
| `surrogates/analyze_heuristics.py`、`heuristics-analysis.txt`、`heuristics-analysis.json` | 第 2 项的分析 |
| `numbers/spot_numbers_b.py`、`spot_numbers_b.txt` | 第 5 项的独立抽查 |
| `numbers/check_r1_numbers.py`（原样复制）、`check_r1_numbers.txt` | 第 5 项的佐证 |
| `citations.txt` | 每处引文的 `grep -n`、`sed -n` 原始输出 |

## 没有做的

- 没有重复前一持有者的 99 格复放。我复跑的是代用模型的 3 个世界。
- 代用模型只跑了主评测 40 个世界，没有跑外推，所以 GX 按构造不过。
- 复核者与作者同属 Claude 模型。
