# S4 一期 final 非作者独立复算报告（提交 04ba1c0）

- **复算执行者**：`gemini-b8k2`（二级执行 agent，非作者独立复算，会话指纹 `sess-c23947e69a93`）
- **复算对象**：S4 第一阶段 final 运行结果与报告（提交 `04ba1c0`，作者：一级 `claude`）
- **核对依据**：
  - 设计文档：`reports/V9-S4-DESIGN/DESIGN-r3.md`
  - 预登记冻结：`reports/V9-S4-PHASE1/PREREG-r1.json`（提交 `2812686`）
  - 探针对比：`reports/V9-S4-PHASE1/probe-r2/probe.json`
  - final 落盘结果：`artifacts/v9/s4/phase1/final-final/`（`worlds.jsonl`、`labels.jsonl`、`replay.json`、`weights/`）
  - 一次性标记：`artifacts/v9/s4/phase1/FINAL_READ_ONCE.json`
  - 运行报告与日志：`reports/V9-S4-PHASE1/final/final.json`、`run.log`、`FINAL-REPORT.md`
- **复算结论**：**结果成立（RECOMMEND_ACCEPT）**。
  - 必修项（Must-fix）：`0`
  - 应修项（Should-fix）：`0`
  - 所有 6 个假设门、1 个负对照、6 个合法性门全部通过；全部点估计与置信区间与 `final.json` 逐位完全一致。

---

## 核心复算结果概览

| 核对大项 | 核对要求 | 复算结论 | 核心证据与数据 |
|:---|:---|:---:|:---|
| **1. 运行合法性** | 预登记 SHA、标记时序、代码清单 SHA、代码干净、40 个清单文件与 22 个产物 SHA 校验、run.log 完整性 | **合法成立** | 三处预登记 SHA 均为 `f570c2ff…`；标记 mtime 比冻结提交晚 5650s；代码清单哈希四处严格一致（`e00655ef…`）；40 个清单文件与 22 个产物哈希逐一核对 0 不符；`code_dirty` 为空；`run.log` 共 33 行无异常退出。所有引用命令与精准行号见 `evidence/citations.txt`。 |
| **2. 纯 NumPy 重算** | 不导入任何项目代码，按预登记参数（10000 次 Bootstrap、种子 20261110、按世界、m=7）重算全部门与合法性 | **逐位一致，全部通过** | 6 个假设门（HD、HF、HD-x、H1、H2、H3）、负对照（D、C）、合法性（地板单调性、样本数、完整性 200/100）的点估计、95% CI 与 Bonferroni CI 与 `final.json` **逐位 100% 相同**。 |
| **3. 标签独立重算** | 仅导入 `world.py`，内存重新生成 300 个世界（不落盘），重算重新出现与碰撞事件 | **完全吻合** | 重新计算 300 个世界事件总数 11114 个，其中有碰撞事件 3188 个；逐世界可见性、检测编号、接触日志与 `labels.jsonl` 比对 0 不符；逐世界事件列表与 `worlds.jsonl` 比对 0 不符；总数与 `final.json` checks.labels 完全一致。 |
| **4. 复放与确定性** | 验证 `replay.json` 组成（5 臂×3 种子=15，加基线 6 格，共 21 格，不含 L-int-s）；经锁复跑 `verify_replay.py` | **105 格全过** | `replay.json` 精确包含 15 份权重（无 L-int-s），5 个世界×21 格=105 格。独立经共享锁执行 `verify_replay.py` 输出 `{"passed": true, "checked": 105, "mismatches": []}`。 |
| **5. 报告核对** | 核对 `FINAL-REPORT.md` 数字与陈述范围（H1/H3 只答够不够用、移出跟踪臂、描述量不设门） | **如实准确** | 报告中所有数值与 `final.json` 严格对齐；三处结论严格受控，无过度外推。 |
| **6. 描述量抽查** | 从 `worlds.jsonl` 重算速度校准、规范化坐标系增益、1/5/10/30 步预测误差 | **逐位一致** | 3 项描述量重算结果与 `final.json["descriptive"]` 逐位浮点完全吻合。 |

---

## 一、运行合法性逐项检验

### 1.1 校验脚本与执行命令
编写并执行独立校验脚本 `reports/V9-S4-PHASE1/final-review/evidence/check_legality.py`：
```bash
python3 reports/V9-S4-PHASE1/final-review/evidence/check_legality.py
```
全部行号引用与精确终端输出命令已归档在 `evidence/citations.txt`。

### 1.2 原始执行输出（Raw Output）
```text
=== S4 Phase 1 Final: Legality Verification ===
1. PREREG-r1.json on disk:    f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d
   FINAL_READ_ONCE.json:      f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d
   final.json prereg_sha256:  f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d
   -> PREREG SHA256 matches in all 3 places exactly.
2. Commit 2812686 timestamp:   1794365424 (02:50:24 UTC)
   Marker file mtime:          1794371074 (04:24:34 UTC)
   Time difference (mtime-commit): 5650s (> 0)
   -> Marker write time is strictly after preregistration commit.
3. Computed code manifest SHA: e00655ef4d8fd0a96c636ca0c91d10d82963085ed6cee09edb7298fcfe8dffa0
   PREREG code_manifest_sha:   e00655ef4d8fd0a96c636ca0c91d10d82963085ed6cee09edb7298fcfe8dffa0
   final.json code_manifest:   e00655ef4d8fd0a96c636ca0c91d10d82963085ed6cee09edb7298fcfe8dffa0
   probe-r2 code_manifest:     e00655ef4d8fd0a96c636ca0c91d10d82963085ed6cee09edb7298fcfe8dffa0
   final code_dirty:           []
   -> Code manifest hash identical across prereg, final, probe; code_dirty is empty.
4. Checking 40 manifest files on disk:
   -> All 40 manifest files match disk exactly.
5. Checking 22 final artifact files on disk in /Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s4/phase1/final-final:
   -> All 22 final files match disk exactly.
6. run.log cleanly terminated with valid True, 0 exceptions, 0 errors.
=== ALL LEGALITY CHECKS PASSED ===
```

### 1.3 逐字代码与文件对应比对
1. **预登记 SHA 三处一致性**：
   - 盘上文件：`f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d`
   - [FINAL_READ_ONCE.json:1](file:///Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/s4/phase1/FINAL_READ_ONCE.json#L1)（见 `evidence/citations.txt`）：
     ```json
     {"at": 1794371074.673634, "prereg_sha256": "f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d"}
     ```
   - [final.json:15](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L15)：
     ```json
     "prereg_sha256": "f570c2ff5d6e2664553b8c697c725e2d6c6ab2106e48465097516a99aac6be6d",
     ```
2. **时序因果性**：
   - 预登记冻结提交 `2812686` 提交时间为 `1794365424`（2026-11-11 02:50:24 UTC）。
   - `FINAL_READ_ONCE.json` 写入时间 `at` 为 `1794371074.673634`（2026-11-11 04:24:34 UTC），晚于预登记提交 5650 秒（即恰在 18 个训练格全部完成、评测世界生成开始前写入），完全符合两段式时序要求。
3. **代码清单哈希与工作区状态**：
   - `code_manifest_sha256` 在 [final.json:17](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L17)、[PREREG-r1.json:260](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/PREREG-r1.json#L260)、[probe.json:17](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/probe-r2/probe.json#L17) 中均为 `e00655ef4d8fd0a96c636ca0c91d10d82963085ed6cee09edb7298fcfe8dffa0`。
   - [final.json:18](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L18)：`"code_dirty": []`，无任何未提交代码改动。
4. **40 个清单文件与 22 个产物文件**：
   - 清单中 40 个文件（含 `DESIGN-r3.md`、`run_s4p1.py`、`verify_*.py` 及 `src/` 下 36 个源码文件）重算 SHA256 与磁盘文件 100% 吻合，0 不符。
   - `final.json["files_sha256"]` 登记的 22 个文件（`worlds.jsonl`、`worlds.partial.jsonl`、`labels.jsonl`、`replay.json` 及 `weights/` 下 18 个 safetensors）与磁盘逐一核对 0 不符。
5. **日志无异常**：
   - `reports/V9-S4-PHASE1/final/run.log` 全长 33 行，末行 [run.log:33](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/run.log#L33)：
     ```text
     [  7447.7s] valid True {'HD': True, 'HF': True, 'HD-x': True, 'H1': True, 'H2': True, 'H3': True}
     ```
     无任何 Traceback、Error 或重试异常。

---

## 二、纯 NumPy 重算全部门与合法性

### 2.1 重算说明与命令
严格遵守规则：**不导入 `ainerzero`、运行器或任何项目代码**，仅依赖 Python 标准库与 `numpy`。参数从 `PREREG-r1.json` 严格读取：
- Bootstrap 次数：`10000`
- 随机数种子：`20261110`（`np.random.default_rng(20261110)`）
- 重采样单元：`world`（按世界整行重抽样）
- 置信水平：`95%`
- Bonferroni 比较数：$m = 7$（HD、HF、HD-x D、HD-x ratio、H1、H2、H3）
- 种子平均方式：每事件按种子 1、2、3 均值聚合

执行命令：
```bash
python3 reports/V9-S4-PHASE1/final-review/evidence/recompute_numpy.py
```

### 2.2 重算结果对照表

| 门 / 统计量 | 评价对象 | 预登记门槛 | final.json 记录值 | NumPy 独立重算值 | 95% 区间 | Bonferroni 区间 ($m=7$) | 判定 | 逐位吻合 |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| **HD** | $D(\text{L-int})$（主评测） | $\ge 0.8$，下界 $> 0.7$ | 0.8733433440607872 | **0.8733433440607872** | [0.864987, 0.880967] | [0.861664, 0.883535] | **通过** | **完全相同** |
| **HF** | 擦边误差比 | $\le 0.1$，上界 $\le 0.15$ | 0.07110156718461932 | **0.07110156718461932** | [0.066911, 0.075331] | [0.065503, 0.076775] | **通过** | **完全相同** |
| **HD-x (D)** | $D(\text{L-int})$（外推 10 盘） | $\ge 0.7$，下界 $> 0.6$ | 0.8672277066606167 | **0.8672277066606167** | [0.860607, 0.873548] | [0.857760, 0.875649] | **通过** | **完全相同** |
| **HD-x (HF)** | 擦边误差比（外推 10 盘） | $\le 0.15$ | 0.07131900464713013 | **0.07131900464713013** | [0.067354, 0.075213] | [0.066027, 0.076897] | **通过** | **完全相同** |
| **H1** | $C(\text{L-int})$（主评测） | $\ge 0.5$，下界 $> 0.25$ | 0.7261613691931541 | **0.7261613691931541** | [0.614789, 0.832895] | [0.569014, 0.876227] | **通过** | **完全相同** |
| **H2** | 增量 $\Delta\text{acc} = \text{L-int} - \text{L-ind}$ | $\ge 0.05$，下界 $> 0.0$ | 0.12276893391220459 | **0.12276893391220459** | [0.100075, 0.144786] | [0.091276, 0.153129] | **通过** | **完全相同** |
| **H3** | $C(\text{L-int})$（外推 10 盘） | $\ge 0.4$，下界 $> 0.2$ | 0.7047970479704795 | **0.7047970479704795** | [0.602941, 0.801655] | [0.564118, 0.836607] | **通过** | **完全相同** |
| **负对照 D** | $D(\text{L-ind})$ | 下界 $< 0.5$ | 0.0020310736256325956 | **0.0020310736256325956** | [-0.001726, 0.005742] | [-0.003208, 0.007109] | **通过** | **完全相同** |
| **负对照 C** | $C(\text{L-ind})$ | 下界 $< 0.25$ | 0.10391198044009754 | **0.10391198044009754** | [-0.042162, 0.232794] | [-0.104947, 0.282197] | **通过** | **完全相同** |

### 2.3 合法性门重算对照

| 合法性检查项 | 指标要求 | final.json 记录 | NumPy 独立重算值 | 状态 | 逐位吻合 |
|:---|:---|:---:|:---:|:---:|:---:|
| **地板门（单调性）** | $\text{acc(E-CV)} < \text{acc(E-B)} < \text{acc(E-P)}$ | $0.317414 < 0.391462 < 0.588760$ | $0.317414375301 < 0.391461649783 < 0.588760250844$ | **通过** | **完全相同** |
| **碰撞事件样本数** | 预期 $1305.0 \pm 25\%$（$[978.75, 1631.25]$） | 1382 | **1382** | **通过** | **完全相同** |
| **碰撞动力学盘步数** | $\ge 0.75 \times 2760.0 = 2070$ | 3157 | **3157** | **通过** | **完全相同** |
| **完整性（世界数）** | 主评测 200，外推 100 | main: 200, extrap: 100 | main: 200, extrap: 100 | **通过** | **完全相同** |

**结论**：重算不仅点估计严格相等，而且在 10000 次重抽样下的 95% 置信区间以及 Bonferroni 多重比对调整区间均达到**逐位浮点严格相等（Bit-for-bit MATCH）**。六个假设门、一个负对照门与全部合法性指标全部通过。

---

## 三、标签独立重算

### 3.1 重算说明与命令
严格遵照要求：**仅导入世界生成器 `s4/world.py`，全部在内存中按种子生成 300 个世界（主评测 200 个、外推 100 个），不产生任何落盘文件**。
自主实现事件提取与验证：
1. 遍历每个世界每步的可见掩码与检测编号；
2. 识别重新出现事件：$t_1$ 步可见且被检测到，$t_1+1 \dots t_2-1$ 步不可见，$t_2$ 步可见且被检测到（$t_2 - t_1 \ge 2$）；
3. 判定「有碰撞」：在 $[t_1, t_2)$ 步区间的盘—盘真实接触日志中存在该盘的接触记录；
4. 逐世界验证：
   - 与 `labels.jsonl` 比对逐世界、逐步的 `visible` 掩码、`detected` 识别编号和 `disk_contacts`；
   - 与 `worlds.jsonl` 比对逐世界的所有重新出现事件元组 `[disk_id, t1, t2, has_coll]`；
   - 与 `final.json` 的 `checks.labels` 比对全量事件总数与碰撞事件总数。

执行命令：
```bash
python3 reports/V9-S4-PHASE1/final-review/evidence/recompute_labels.py
```

### 3.2 原始执行输出（Raw Output）
```text
=== S4 Phase 1 Final: In-Memory Labels Recomputation ===
Total evaluated worlds:      300
Total recomputed events:     11114 (recorded in final.json: 11114)
Total collision events:      3188 (recorded in final.json: 3188)
labels.jsonl mismatches:     0
worlds.jsonl mismatches:     0
=== IN-MEMORY LABELS RECOMPUTATION PASSED 100% ===
```

### 3.3 对照结论
- 重新计算的世界数：300 个。
- 重新计算的重新出现事件总数：`11114`，与 [final.json:14734](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L14734) 的 `"events": 11114` 完全相同。
- 重新计算的碰撞事件总数：`3188`，与 [final.json:14735](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L14735) 的 `"collision_events": 3188` 完全相同。
- 300 个世界逐步可见性、检测编号与接触日志与 `artifacts/v9/s4/phase1/final-final/labels.jsonl` 比对，不符数（mismatches）为 **0**。
- 300 个世界逐世界事件列表与 `artifacts/v9/s4/phase1/final-final/worlds.jsonl` 中记录的 `events` 比对，不符数（mismatches）为 **0**。

---

## 四、复放与确定性验证

### 4.1 `replay.json` 结构核对
查看 `artifacts/v9/s4/phase1/final-final/replay.json`：
- **世界数**：5 个世界（主评测世界 0、1、2，外推世界 1000、1001）。
- **包含权重模型**：
  - 5 个跟踪学习臂：`L-ind`、`L-int`、`L-int-c`、`L-int-e8`、`L-int-c-e8`。
  - 每个臂 3 个种子（#1、#2、#3），共 $5 \times 3 = 15$ 份权重。
  - 加上 `HAND` 基线 `E-B` 与 `E-P`（各 3 个种子，共 6 格）。
  - 每个世界重放 $15 + 6 = 21$ 格。
  - **确认彻底不含发散的 `L-int-s`**。
- **总重放格数**：$5 \text{ worlds} \times 21 \text{ cells} = 105 \text{ cells}$。对应 [final.json:14740](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/final.json#L14740) 的 `"checked": 105`。

### 4.2 经共享锁执行 `verify_replay.py`
按照规范使用 `hold_lock.py` 保护 MLX 执行，命令如下：
```bash
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -I reports/V9-S4-PHASE1/verify_replay.py artifacts/v9/s4/phase1/final-final/replay.json artifacts/v9/s4/phase1/final-final/worlds.jsonl artifacts/v9/s4/phase1/final-final
```

### 4.3 原始执行输出（Raw Output）
```text
lock held by 32615
{"passed": true, "checked": 105, "mismatches": []}
```

核对结论：`verify_replay.py` 独立进程重放了全部 105 个格的轨迹跟踪与分配，逐位重算的事件对错与落盘记录完全相同，`checked == 105` 且 `mismatches` 为空，确定性门完全通过。

---

## 五、核对 `FINAL-REPORT.md`

逐项对照 `reports/V9-S4-PHASE1/final/FINAL-REPORT.md` 中的数据与陈述：

### 5.1 数据核对表
- [FINAL-REPORT.md:16](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L16)：`D = 0.873, [0.862, 0.884]` $\rightarrow$ 对应 `final.json` `0.87334... [0.86166..., 0.88353...]`（一致）。
- [FINAL-REPORT.md:19](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L19)：`0.071, [0.066, 0.077]` $\rightarrow$ 对应 `final.json` `0.07110... [0.06550..., 0.07677...]`（一致）。
- [FINAL-REPORT.md:20](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L20)：`HD-x: D = 0.867 [0.858, 0.876], 误报比 0.071 [0.066, 0.077]` $\rightarrow$ 对应 `final.json`（一致）。
- [FINAL-REPORT.md:24-25](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L24-L25)：`H1: C = 0.726 [0.569, 0.876], H3: C = 0.705 [0.564, 0.837]` $\rightarrow$ 对应 `final.json`（一致）。
- [FINAL-REPORT.md:28](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L28)：`H2: 0.123 [0.091, 0.153]` $\rightarrow$ 对应 `final.json` `0.12276... [0.09127..., 0.15312...]`（一致）。
- [FINAL-REPORT.md:29](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L29)：负对照 `D = 0.002 [-0.003, 0.007], C = 0.104 [-0.105, 0.282]` $\rightarrow$ 对应 `final.json`（一致）。
- [FINAL-REPORT.md:46](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L46)：总耗时 7447.7s、训练段 5607.4s、标记后 1840.3s、预留 2870s $\rightarrow$ 对应 `final.json`（一致）。
- [FINAL-REPORT.md:53-58](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L53-L58)：标签 11114/3188、地板单调性 0.317 < 0.391 < 0.589、样本数 1382 (1305)、盘步 3157 (2760)、重放 105 格 $\rightarrow$ 对应 `final.json`（一致）。
- 描述量表格（lines 80-86 准确率矩阵、lines 94-97 规范化增益、lines 110-115 多步误差、lines 145-149 速度校准）均与 `final.json` 逐字对齐。

### 5.2 结论边界审视（特别关注三处要求）
1. **H1 与 H3 的解释范围**：
   - [FINAL-REPORT.md:26](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L26)：
     > “按设计，C 会饱和，所以 H1、H3 只回答「够不够用」，不回答「学到了多少交互」。后者由 HD 回答。”
   - [FINAL-REPORT.md:135](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L135)：
     > “所以 C 的大小在很大程度上取决于登记的过程噪声。H1「够用」只对登记的那组噪声成立。”
   - 审查结论：严格遵照 DESIGN-r3 §5 要求，未将 C 夸大为学到了完全物理，界限清晰。
2. **L-int-σ 移出跟踪臂**：
   - [FINAL-REPORT.md:58](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L58)：
     > “权重只含 5 个跟踪臂 × 3 个种子，没有 L-int-s”
   - [FINAL-REPORT.md:154](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L154)：
     > “「L-int-σ 在滤波器里的重识别」已取消：探针 r1 中，在滤波器里按方差头抽样会发散，见设计稿实现补记的「L-int-σ 移出跟踪臂」。”
   - 审查结论：如实陈述移出原因与范围，无隐瞒或过头表述。
3. **描述量不设门**：
   - [FINAL-REPORT.md:76](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L76)：
     > “## 描述量（登记，不设门；区间都是 95%，不做 Bonferroni）”
   - [FINAL-REPORT.md:32-34](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/final/FINAL-REPORT.md#L32-L34) 明确指出整体跟踪没有显著改善、方差欠校准与过度自信、接触头不能单用等阴性事实，诚实客观。

---

## 六、描述量抽查重算

### 6.1 校验脚本与执行命令
编写并执行独立校验脚本 `reports/V9-S4-PHASE1/final-review/evidence/recompute_descriptive.py`：
```bash
python3 reports/V9-S4-PHASE1/final-review/evidence/recompute_descriptive.py
```

### 6.2 原始执行输出（Raw Output）
```text
=== S4 Phase 1 Final: Descriptive Metrics Recomputation ===
1. Calibration: 100% bit-for-bit identical with final.json.
   Main collision:     L-int-s NLL = 2.3554, cov90 = 0.8333 (n=4830)
   Main graze:         L-int-s NLL = -0.1165, cov90 = 0.9036 (n=35112)
   Main free:          L-int-s NLL = -0.2483, cov90 = 0.9027 (n=500058)

2. kstep_position_error: 100% bit-for-bit identical with final.json.
   E-B     : 1-step=0.000442, 5-step=0.013292, 10-step=0.051311, 30-step=0.381309
   L-int   : 1-step=0.006532, 5-step=0.028125, 10-step=0.071163, 30-step=0.566386
   L-int-c : 1-step=0.006680, 5-step=0.027588, 10-step=0.069385, 30-step=0.551819
   L-ind   : 1-step=0.011941, 5-step=0.080418, 10-step=0.207156, 30-step=1.084064

3. canonical_minus_plain: 100% bit-for-bit identical with final.json.
   Full data: ΔD = 0.012746, Δacc_collision = 0.022914 [0.009762, 0.036426]
   1/8 data:  ΔD = 0.030302, Δacc_collision = -0.006271 [-0.022315, 0.009943]

=== ALL DESCRIPTIVE SPOT-CHECKS PASSED 100% ===
```

### 6.3 抽查比对说明
1. **校准 NLL 与覆盖率（`calibration`）**：
   - 主评测碰撞步 $n=4830$：L-int-s NLL = 2.355409, 90% 覆盖率 = 0.833333（过度自信）。
   - 主评测擦边步 $n=35112$：L-int-s NLL = -0.116508, 90% 覆盖率 = 0.903623（高度校准）。
   - 主评测自由步 $n=500058$：L-int-s NLL = -0.248275, 90% 覆盖率 = 0.902681（高度校准）。
   - 重算结果与 `final.json["descriptive"]["calibration"]` 浮点数逐位一致。
2. **多步预测位置误差（`kstep_position_error`）**：
   - 1、5、10、30 步各臂误差均与落盘数据精确对齐；如预期，由于自由步占多数，无碰撞的 E-B 累计位置误差最小，学习模型误差在碰撞事件上收敛但在长多步上略有累积。
3. **规范化坐标系增益（`canonical_minus_plain`）**：
   - 全量数据：$\Delta D = +0.012746$，$\Delta\text{acc} = +0.022914$ [0.009762, 0.036426]；
   - 1/8 数据：$\Delta D = +0.030302$，$\Delta\text{acc} = -0.006271$ [-0.022315, 0.009943]；
   - 与 `final.json["descriptive"]["canonical_minus_plain"]` 逐位浮点严格吻合。

---

## 七、复算证据清单与校验和（`SHA256SUMS.txt`）

证据目录下所有复算脚本均可独立原样复跑，哈希清单见 [SHA256SUMS.txt](SHA256SUMS.txt)：
```text
6b9d85edd4ed4d83f8e24acc1ae89010b5127e88596f74550db97373244a509e  evidence/check_legality.py
f44c5985a7b6e26bef89a4d1c7ab0750f037395194cb672903f4c9ce1b1f2b68  evidence/citations.txt
93c0aaac4e5281b89bd7cb58d64c3307a45579a729aef71af1bdd2a15756379c  evidence/legality.txt
cf3d4bffef0ffbc013cd223ef2943bb1900578834e2b88ce767ab4b3dac84516  evidence/recompute_descriptive.py
15c9f89faa6647d77a6314bcbe0d86a89324067cb6f919fed91229d36f6330fe  evidence/recompute_descriptive.txt
85920a72235ec3f0b4ee596915d0f1abca932fda1aef869548a08e9558d3d7ed  evidence/recompute_labels.py
5d18ac8195580ce376ca84d5cbdd7207e01176c4cf0daf06af707e440314f1fc  evidence/recompute_labels.txt
b399c048f129daa210d77b4b2f5804663d68be1f933a9b8999624c2706e43a38  evidence/recompute_numpy.py
4aa90cd7aeb8e49f359062ccfd436ff39cc3aacd92ef811a48b97656f7f838ed  evidence/recompute_numpy.txt
fb842d47cd3ad09638e4655de1367b823f571eb10fb7faff75579e9a5827e3a0  evidence/verify_replay_raw.txt
```

---

## 八、验收结论

本次独立复算严格核查了 S4 一期 final 运行的所有环节：
1. 运行流程完全合法合规，时序严格满足因果性，工作区与代码身份完全冻结；
2. 纯 NumPy 独立重算的所有门、负对照、合法性指标点估计与置信区间与官方报告**逐位完全一致**，六个门全部绿灯；
3. 内存中 300 世界标签重算（含逐世界可见性、检测编号、接触与事件元组比对）与确定性 105 格重放 100% 通过；
4. 报告结论受控、界限清晰，描述量无夸大。

**最终裁决：结果成立（RECOMMEND_ACCEPT），建议统筹通过并验收。**
