# S4 第二阶段 final 非作者独立复算报告（修订版）

- **任务**：`ainerzero.V9.P221`（【L2·非作者独立复算】S4 二期 final（`89ef2c6` → `b97b6d6`）：合法性、门、标签、复放与报告）
- **复算执行者**：二级执行 agent `gemini-h8f2`（非代码作者；作者为一级 claude）
- **基线提交**：预登记提交 `89ef2c6`，final 运行结果提交 `b97b6d6`
- **核心结论**：**复算成立**（运行合法性核验全过、纯 NumPy 8 门重算逐位一致、标签纯内存重算 300 世界逐项一致、MLX 经锁复放 165 格无不符、报告表述与数字严格受控）
- **修订说明（针对一级审查意见）**：
  1. 纠正第 1 项预登记 SHA 比对来源：照实写清三方来源为 `PREREG-r1.json`（磁盘计算）、`FINAL_READ_ONCE.json`（只读标记文件）与 `final.json`，去除对不含 SHA 的 `launch-final.txt` 的误称。
  2. 纠正代码清单哈希：更新为四方严格比对 `PREREG-r1.json`、`final.json`、`probe-p2.json` 以及由 `run_guard.build_manifest` 在现场重算的真实哈希值 `38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1`，并附上 `legality_check.txt` 原始终端输出。
  3. 纠正第 2 项 GK2 门槛：修正 Bonferroni 下界门槛为预登记实际门限值 `0.65`（`gates.GK2.collision_low`），点估计门槛为 `0.75`。

---

## 逐项复算结论、命令与证据摘要

### 1. 运行合法性与哈希核验（Item 1）—— 通过
- **执行命令**：
  ```bash
  python3 reports/V9-S4-PHASE2/final-review/evidence/verify_legality.py | tee reports/V9-S4-PHASE2/final-review/evidence/legality_check.txt
  ```
- **原始输出摘要**：
  ```text
  === 1.1 预登记 SHA 三方比对 ===
  PREREG-r1.json on disk : cf02286e77ef480df71cde722b3d9af2ab658044635b5b8557090ce36320de30
  FINAL_READ_ONCE.json    : cf02286e77ef480df71cde722b3d9af2ab658044635b5b8557090ce36320de30
  final.json              : cf02286e77ef480df71cde722b3d9af2ab658044635b5b8557090ce36320de30
  -> 预登记 SHA 三方严格完全一致: MATCH

  === 1.2 标记写入时间 vs 89ef2c6 提交时间 ===
  Commit 89ef2c6 time : 1794418202 (2026-11-11T17:30:02Z)
  Marker mtime        : 1794418214.1033494 (float timestamp)
  Difference (marker - commit): 12.1 s
  -> 标记写入时间严格晚于 89ef2c6 提交时间 (+12.1s): PASS

  === 1.3 代码清单哈希在 final、预登记、探针三方一致性 ===
  PREREG-r1.json code_manifest_sha256 : 38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1
  final.json code_manifest_sha256     : 38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1
  probe-p2.json code_manifest_sha256  : 38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1
  run_guard recomputed manifest SHA   : 38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1
  -> code_manifest_sha256 四方比对完全一致 (38c07bbfd6cf1ad1b2bb9dfeab88dd619481cab43985966212bee6fccccd6ae1): MATCH
  code_dirty      : []
  late_violations : []
  -> code_dirty 与 late_violations 均为空: PASS

  === 1.4 预登记 manifest 42 个文件逐个重算 SHA ===
  Checked 42 files from manifest:
  -> 全部 42 个清单文件 SHA 逐个比对完全一致: 42/42 MATCH

  === 1.5 final.json 登记的文件 SHA 与权重 SHA 比对 ===
  Checking 4 final artifacts files:
    worlds.jsonl: 9380f487e324c781... OK
    worlds.partial.jsonl: f64e4cf684b785fa... OK
    labels.jsonl: 673e89929aaee0c5... OK
    replay.json: 099301f182ae96db... OK
  -> final.json 落盘文件 SHA 全部吻合: MATCH
  Checking 6 weight files:
    L-int#1: 88ea6c9b619098e0... OK
    L-int#2: c99bc0f709e36f67... OK
    L-int#3: 241659f14be2b29e... OK
    L-ind#1: a4905a8c79c5ab02... OK
    L-ind#2: 8447cee6a2920e85... OK
    L-ind#3: 191dcf99913f47e4... OK
  -> final.json 权重 SHA 全部吻合: MATCH

  === 1.6 final.log 异常核验 ===
  final.log lines: 14
  Lines containing warning/error/failed/exception: 0
  -> final.log 正常完成，无未处理异常: PASS
  ```
- **结论**：运行合法性核验 6 项全部通过，证据保存在 `evidence/legality_check.txt`。

---

### 2. 纯 NumPy 独立复算全部门（Item 2）—— 通过（8 门决策与区间逐位完全一致）
- **执行命令**：
  ```bash
  # 运行 P218 验收的纯 NumPy 独立复算工具
  python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
    artifacts/v9/s4/phase2/final-final/worlds.jsonl \
    reports/V9-S4-PHASE2/PREREG-r1.json \
    --out reports/V9-S4-PHASE2/final-review/evidence/recomputed_final.json

  # 逐位核验比对
  python3 reports/V9-S4-PHASE2/final-review/evidence/compare_gates.py | tee reports/V9-S4-PHASE2/final-review/evidence/gate_comparison.txt

  # GK2 细分事件统计与门限比对
  python3 reports/V9-S4-PHASE2/final-review/evidence/verify_gk2_details.py | tee reports/V9-S4-PHASE2/final-review/evidence/gk2_event_details.txt
  ```
- **原始输出摘要**：
  ```text
  === 2.1 统计量点估计逐位比对 ===
  GA                : final=+0.0491011984 | recomp=+0.0491011984 | equal=True
  GC                : final=+1.0204865557 | recomp=+1.0204865557 | equal=True
  GD_D              : final=+0.8675132629 | recomp=+0.8675132629 | equal=True
  GD_ratio          : final=+0.0233120314 | recomp=+0.0233120314 | equal=True
  GK1_all           : final=+0.9051071103 | recomp=+0.9051071103 | equal=True
  GK1_collision     : final=+0.8800479808 | recomp=+0.8800479808 | equal=True
  GK2_collision     : final=+0.7445855116 | recomp=+0.7445855116 | equal=True
  GK2_non_collision : final=+0.9231098736 | recomp=+0.9231098736 | equal=True
  GN                : final=+0.0062825730 | recomp=+0.0062825730 | equal=True
  GR                : final=+0.0721931790 | recomp=+0.0721931790 | equal=True
  GX_C              : final=+0.9749776586 | recomp=+0.9749776586 | equal=True
  GX_diff           : final=+0.0787443469 | recomp=+0.0787443469 | equal=True
  neg_C             : final=+0.0704225352 | recomp=+0.0704225352 | equal=True
  neg_D             : final=+0.0034045049 | recomp=+0.0034045049 | equal=True
  -> 全部 14 项点估计逐位完全相等 (diff=0.00e+00): MATCH

  === 2.2 95% CI 与 Bonferroni 区间比对 ===
  -> 全部 56 个区间上下界与 final.json 逐位完全相等 (diff=0.00e+00): MATCH

  === 2.3 门判定比对 ===
  Gate GN   : final=True  | recomp=True  | match=True
  Gate GA   : final=True  | recomp=True  | match=True
  Gate GC   : final=True  | recomp=True  | match=True
  Gate GK1  : final=True  | recomp=True  | match=True
  Gate GK2  : final=False | recomp=False | match=True
  Gate GD   : final=True  | recomp=True  | match=True
  Gate GX   : final=True  | recomp=True  | match=True
  Gate GR   : final=True  | recomp=True  | match=True
  Negative Control: final=True | recomp=True | match=True
  -> 8 个主门通过/未通过判定 100% 一致: MATCH (7 pass, GK2 fail)
  ```
- **GK2 细分核查结果（证据 `evidence/gk2_event_details.txt`）**：
  - 主评测 200 个世界总事件数 6008，其中非碰撞 4669，碰撞事件数 1339。
  - 3 种子机会数：$1339 \times 3 = 4017$。
  - 3 种子命中数：Seed 1 = 1003，Seed 2 = 1002，Seed 3 = 986，合计 2991。
  - 点估计比例：$2991 / 4017 = 0.7445855116$（0.7446）。
  - **登记门槛要求**（`PREREG-r1.json`）：点估计 $\ge 0.75$，Bonferroni 下界 $> 0.65$。
  - **实际区间**：95% CI 为 `[0.7220, 0.7670]`，Bonferroni 区间为 `[0.7121, 0.7771]`。
  - **分析结论**：虽然 Bonferroni 下界 0.7121 越过 0.65，但点估计 0.7446 低于门槛 0.75（差 0.0054），判定严格为 False（FAIL），确认结论「**有碰撞重新出现时的校准不成立**」。

---

### 3. 纯内存从世界生成器独立重算标签（Item 3）—— 通过（300 世界逐项无歧义一致）
- **执行命令**：
  ```bash
  python3 reports/V9-S4-PHASE2/final-review/evidence/verify_labels_independent.py | tee reports/V9-S4-PHASE2/final-review/evidence/labels_independent_check.txt
  ```
- **原始输出摘要**：
  ```text
  === Item 3: Independent In-Memory Label Recomputation ===
  Reading recorded labels: .../labels.jsonl (300 records)
  Reading recorded worlds: .../worlds.jsonl (300 records)
  Generating 300 worlds in memory with allow_registered=True and recomputing...
    Processed 50/300 worlds...
    ...
    Processed 300/300 worlds...
  Recomputation completed in 35.07 s.
  Total mismatches: 0
  ALL 300 WORLDS MATCHED PERFECTLY (0 MISMATCHES).

  --- Event Count Distribution ---
  Main worlds (200):
    Total events: in-memory=6008, recorded=6008
    Mean events per world: 30.04
    Min / Median / Max: 18 / 30 / 42
  Extrap worlds (100):
    Total events: in-memory=5012, recorded=5012
    Mean events per world: 50.12
    Min / Median / Max: 34 / 50 / 76

  --- Collision vs Non-Collision Distribution ---
  Main worlds (200):
    Collision events: in-memory=1339, recorded=1339
    Non-collision events: in-memory=4669
    Collision event ratio: 0.2229
  Extrap worlds (100):
    Collision events: in-memory=1783
    Non-collision events: in-memory=3229
    Collision event ratio: 0.3557

  --- Hidden Length (Gap) Distribution ---
  Main worlds gap breakdown (in-memory vs recorded):
    Gap [ 1,   9]: in-memory=1171, recorded=1171, diff=0
    Gap [10,  24]: in-memory=1897, recorded=1897, diff=0
    Gap [25,  49]: in-memory=1816, recorded=1816, diff=0
    Gap [50, 999]: in-memory=1124, recorded=1124, diff=0
  Extrap worlds gap breakdown (in-memory vs recorded):
    Gap [ 1,   9]: in-memory= 863, recorded= 863, diff=0
    Gap [10,  24]: in-memory=1633, recorded=1633, diff=0
    Gap [25,  49]: in-memory=1600, recorded=1600, diff=0
    Gap [50, 999]: in-memory= 916, recorded= 916, diff=0

  >>> CONCLUSION: ITEM 3 VERIFICATION PASSED (逐项一致，无歧义).
  ```
- **结论**：内存重算 300 个世界（200 main + 100 extrap）与磁盘 `labels.jsonl` 及 `worlds.jsonl` 在事件数分布、碰撞与否分类、遮挡时长区间频数上 100% 逐项无歧义完全一致。

---

### 4. 确定性与复放（Item 4）—— 通过（持有 MLX 锁复放 165 格 0 不符）
- **检查 `final.json` 的 `checks.replay`**：
  - 抽样 33 个跟踪格（Hand 3 + Learned 8，各 3 种子，跨主世界 0..2 与外推世界 0..1 共 5 个世界），共核验 165 个跟踪格。
  - 记录内容：`{"passed": true, "checked": 165, "cells_per_world": 33, "mismatches": []}`。
- **持锁复跑命令**：
  ```bash
  .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock \
    .venv/bin/python -I reports/V9-S4-PHASE2/verify_replay_p2.py \
    artifacts/v9/s4/phase2/final-final/replay.json artifacts/v9/s4/phase2/final-final/worlds.jsonl \
    | tee reports/V9-S4-PHASE2/final-review/evidence/verify_replay.txt
  ```
- **原始输出**：
  ```text
  lock held by 39378
  {"passed": true, "checked": 165, "cells_per_world": 33, "mismatches": []}
  ```
- **结论**：复放脚本在 MLX 锁保护下复跑全过，165 个格子的轨迹摘要与重认判定与落盘记录完全一致，0 mismatches。

---

### 5. 审查报告与措辞边界（Item 5）—— 通过
- **对照文件**：`reports/V9-S4-PHASE2/FINAL-REPORT.md` vs `final.json`，映射生成于 `citations.txt`。
- **数字真实性核实**：
  - 运行耗时（973 秒）、预留（1761 秒）来自 `final.json["elapsed_s"]` 与 `PREREG-r1.json`。
  - 表 1 门控统计量：GN (+0.006), GA (+0.049), GC (1.020), GK1 (0.905 / 0.880), GK2 (0.923 / 0.745), GD (0.868 / 0.023), GX (0.079 / 0.975), GR (+0.072) 及各区间界限均与 `final.json["result"]["gates"]` 完全吻合。
  - 表 2 描述量：E-B (0.405/0.896/0.786/0.440), E-P (0.599/0.904/0.836/0.755), L-int (0.553/0.840/0.776/0.506), L-int-g (0.603/0.902/0.835/0.745, 门开 1.4%) 等 10 臂数值均与 `final.json["descriptive"]["main"]` 严格对应。
- **措辞与归因边界核实**：
  - **混合跟踪器界限**：第 23 行明确限定 GA/GC/GK 为「门控混合跟踪器」，不宣称端到端或单模型全包。
  - **收益归因界限**：第 29–31 行仅将收益归因于「学到的碰撞响应」，且以消融臂 L-sc-g（同门乱猜方向，低 0.072，GR）与动力学补回 87% 误差且误报仅 2.3%（GD）为依据。
  - **GK2 失败直陈**：第 17 行、第 34 行明确直陈「有碰撞事件重新出现那一刻的预测分布校准不成立：覆盖率 0.745，门槛 0.75，GK2 不过」，第 60 行明确表示不改门槛、不放宽结论。

---

### 6. 描述统计抽样独立复算（Item 6）—— 通过（误差在浮点机度量以内）
- **执行命令**：
  ```bash
  python3 reports/V9-S4-PHASE2/final-review/evidence/verify_descriptive.py | tee reports/V9-S4-PHASE2/final-review/evidence/descriptive_check.txt
  ```
- **原始输出摘要**：
  ```text
  === Item 6: Descriptive Statistics Independent Recomputation ===

  1. Recomputing Accuracies for Main Worlds (200 worlds):
    E-B          acc_collision     : recomputed=0.4045307443, recorded=0.4045307443, diff=1.11e-16 -> OK
    E-B          acc_non_collision : recomputed=0.8958377954, recorded=0.8958377954, diff=4.44e-16 -> OK
    E-B          acc_all           : recomputed=0.7863404350, recorded=0.7863404350, diff=2.22e-16 -> OK
    ... (10 臂全部 30 项准确率比对完全吻合，最大 diff 6.66e-16)

  2. Recomputing Gate Open Share (gate_share):
    L-int-g      gate_share: recomputed=0.0135566695 (466231/34391264), recorded=0.0135566695, diff=0.00e+00 -> OK
    L-int-g3     gate_share: recomputed=0.0171826794 (590266/34352384), recorded=0.0171826794, diff=0.00e+00 -> OK
    L-int-g7     gate_share: recomputed=0.0113383575 (390345/34426944), recorded=0.0113383575, diff=0.00e+00 -> OK
    L-int-geo    gate_share: recomputed=0.0116172612 (399094/34353536), recorded=0.0116172612, diff=0.00e+00 -> OK
    L-sc-g       gate_share: recomputed=0.0284534537 (988310/34734272), recorded=0.0284534537, diff=0.00e+00 -> OK
    L-int-rand   gate_share: recomputed=0.0199539149 (691399/34649792), recorded=0.0199539149, diff=0.00e+00 -> OK
    L-ind-geo    gate_share: recomputed=0.0427903545 (1492633/34882464), recorded=0.0427903545, diff=0.00e+00 -> OK

  3. Recomputing Learned Minus Scatter Difference:
    L-int-g vs L-sc-g (collision     ): recomputed=0.0721931790, recorded=0.0721931790, diff=0.00e+00 -> OK
    L-int-g vs L-sc-g (non_collision ): recomputed=0.0182765760, recorded=0.0182765760, diff=1.28e-16 -> OK
    L-int-g vs L-sc-g (all           ): recomputed=0.0302929427, recorded=0.0302929427, diff=3.47e-18 -> OK

  4. K-step Position Error Summary:
    E-B        step 1 : recomputed=0.0004625920, recorded=0.0004625920, diff=0.00e+00 -> OK
    E-B        step 5 : recomputed=0.0128074525, recorded=0.0128074525, diff=0.00e+00 -> OK
    E-B        step 10: recomputed=0.0491218502, recorded=0.0491218502, diff=0.00e+00 -> OK
    E-B        step 30: recomputed=0.3744690983, recorded=0.3744690983, diff=0.00e+00 -> OK
    L-int-g    step 1 : recomputed=0.0002290491, recorded=0.0002290491, diff=0.00e+00 -> OK
    L-int-g    step 5 : recomputed=0.0023311685, recorded=0.0023311685, diff=0.00e+00 -> OK
    L-int-g    step 10: recomputed=0.0088488622, recorded=0.0088488622, diff=0.00e+00 -> OK
    L-int-g    step 30: recomputed=0.0904156482, recorded=0.0904156482, diff=0.00e+00 -> OK

  >>> CONCLUSION: ITEM 6 RECOMPUTATION ALL MATCHED.
  ```
- **结论**：全部 48 项抽样描述统计量由原始 `worlds.jsonl` 独立重算后与 `final.json["descriptive"]` 完全吻合。

---

## 交付文件清单

交付目录：`reports/V9-S4-PHASE2/final-review/`
- `REPORT.md`：本复算报告
- `citations.txt`：报告与 `final.json` 逐项映射对照
- `metrics.json`：六项结构化复算指标
- `SHA256SUMS.txt`：交付产物哈希清单
- `evidence/`：
  - `verify_legality.py` & `legality_check.txt`（合法性检查脚本与原始输出）
  - `recomputed_final.json`（纯 NumPy 门重算全量数据）
  - `compare_gates.py` & `gate_comparison.txt`（门统计量逐位对比脚本与原始输出）
  - `verify_gk2_details.py` & `gk2_event_details.txt`（GK2 碰撞事件细分统计脚本与原始输出）
  - `verify_labels_independent.py` & `labels_independent_check.txt`（纯内存 300 世界标签重算脚本与原始输出）
  - `verify_replay.txt`（持有 MLX 锁的复放验证原始终端输出）
  - `verify_descriptive.py` & `descriptive_check.txt`（描述统计抽样独立重算脚本与原始输出）
