# S4 二期 final 非作者独立复算工具开发与 G 轮验证报告

- **任务卡**：`ainerzero.V9.P218`【L2·复算工具】S4 二期 final 的非作者独立复算脚本（纯 NumPy，不导入项目代码），先在摸底 G 轮记录上验证
- **执行 Agent**：`gemini-k7b2`（模型：Gemini 3.8 Flash；层级：二级执行层；非代码作者）
- **基线 Commit**：`b8e9614`
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **交付目录**：`reports/V9-S4-PHASE2/independent-recompute/`
- **交付文件清单**：
  - `recompute_p2.py`：纯 NumPy 独立复算脚本（零项目代码导入）
  - `README.md`：final 运行指南与外部合法性门核对说明
  - `REPORT.md`：本报告（G 轮逐位对照、对抗自检实验、验证结论）
  - `evidence/`：G 轮复算数据、参数配置、4 组对抗实验数据与原始执行日志
  - `SHA256SUMS.txt`：所有交付文件的哈希校验和

---

## 1. 独立复算脚本实现与技术特征

依据任务卡要求与 `reports/V9-S4-P2-DESIGN/DESIGN-r1.md` §5 设计规格，独立复算脚本 `recompute_p2.py` 具有以下核心特征：

1. **零项目依赖（Zero Project Code Import）**：
   - 仅依赖 Python 标准库（`json`, `argparse`, `math`, `pathlib`, `typing`）与 `numpy`。
   - **完全不导入** `ainerzero`、`mlx` 或本仓库中的任何模块。
2. **算法与统计量独立实现**：
   - 比值保护函数：分母非正时置为 `NaN`；
   - 统计量函数：准确率差值 `stat_diff`、差距补回比 `stat_C`、动力学相对精度 `stat_D`、高频误报比 `stat_HF` 均按设计定义独立编写；
   - 重采样实现：按世界配对的置换 bootstrap（默认 10,000 次，种子 20261111），双侧分位取 95% 置信区间及 Bonferroni 检验区间（$m=12$）；
   - 判定逻辑：依据设计稿门槛，对 8 项主门（GN, GA, GC, GK1, GK2, GD, GX, GR）及负对照进行布尔判定；
   - 记录级合法性检查：实现地板（floor）、样本量（samples）、完整性（complete）检查。
3. **输入输出解耦**：
   - 输入：支持 `.json`（如 `results-p2g.json`）及 `.jsonl`（如 final 的 `worlds.jsonl`）；
   - 参数：从 `--params` JSON 文件或命令行参数传入，不在脚本中硬编码；
   - 输出：生成结构化 JSON 文件（含点估计、95% CI、Bonferroni CI、门判定、合法性判定），并打印人读汇总表。

---

## 2. 摸底 G 轮落盘记录验证（逐项对照）

### 2.1 验证命令与输入文件
- **记录文件**：`reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json`（60 个世界：40 主评测，20 外推）
- **参数文件**：`reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json`
- **运行命令**：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --assert-stored \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/recomputed-p2g.json
```

### 2.2 门统计量逐项对照表（Bit-for-Bit 对照）

下表为脚本复算输出与 `results-p2g.json` 原始登记数据的逐位比对：

| 门 / 统计量 | 统计量含义 | 原始登记值 (results-p2g.json) | 独立复算值 (recompute_p2.py) | 95% 区间一致 | Bonferroni 区间 ($m=12$) | 判定 (Pass/Fail) | 逐位相同? |
|---|---|---|---|---|---|---|:---:|
| **GN** | 没有碰撞相对 E-B 差值 | `+0.003161222339304531` | `+0.003161222339304531` | `[-0.013222, +0.019048]` | `[-0.020430, +0.026114]` | **PASS** | **BIT IDENTICAL** |
| **GA** | 全部事件相对 E-B 差值 | `+0.05427616641655163` | `+0.05427616641655163` | `[+0.032338, +0.076041]` | `[+0.022074, +0.084949]` | **PASS** | **BIT IDENTICAL** |
| **GC** | 碰撞事件差距补回比 C | `+0.9174757281553398` | `+0.9174757281553398` | `[+0.796380, +1.050562]` | `[+0.740545, +1.124551]` | **PASS** | **BIT IDENTICAL** |
| **GK1_all** | 1 步预测全部步覆盖率 | `+0.9032172778103386` | `+0.9032172778103386` | `[+0.895991, +0.910359]` | `[+0.892917, +0.912900]` | **PASS** | **BIT IDENTICAL** |
| **GK1_collision** | 1 步预测碰撞步覆盖率 | `+0.8916666666666667` | `+0.8916666666666667` | `[+0.845455, +0.934307]` | `[+0.820781, +0.949142]` | **PASS** | **BIT IDENTICAL** |
| **GK2_non_collision** | 重新出现无碰撞覆盖率 | `+0.910432033719705` | `+0.910432033719705` | `[+0.886364, +0.932971]` | `[+0.875529, +0.940914]` | **PASS** | **BIT IDENTICAL** |
| **GK2_collision** | 重新出现有碰撞覆盖率 | `+0.8177278401997503` | `+0.8177278401997503` | `[+0.767857, +0.862454]` | `[+0.744705, +0.880187]` | **PASS** | **BIT IDENTICAL** |
| **GD_D** | 动力学碰撞步精度 D | `+0.851684347746467` | `+0.851684347746467` | `[+0.824874, +0.874836]` | `[+0.809326, +0.884405]` | **PASS** | **BIT IDENTICAL** |
| **GD_ratio** | 动力学掠过误差比 HF | `+0.026168864700788607` | `+0.026168864700788607` | `[+0.019999, +0.032649]` | `[+0.018123, +0.036133]` | **PASS** | **BIT IDENTICAL** |
| **GX_diff** | 外推全部事件相对 E-B 差值 | `+0.08922093557975878` | `+0.08922093557975878` | `[+0.060161, +0.120614]` | `[+0.047314, +0.135544]` | **PASS** | **BIT IDENTICAL** |
| **GX_C** | 外推差距补回比 C | `+1.0246305418719213` | `+1.0246305418719213` | `[+0.865482, +1.180851]` | `[+0.781985, +1.260593]` | **PASS** | **BIT IDENTICAL** |
| **GR** | 有碰撞事件相对 L-sc-g 差值 | `+0.046192259675405745` | `+0.046192259675405745` | `[+0.012346, +0.083333]` | `[-0.002628, +0.098849]` | **FAIL** | **BIT IDENTICAL** |
| **neg_C** | 负对照 L-ind-geo 补回比 C | `+0.038834951456310676` | `+0.038834951456310676` | `[-0.036082, +0.126582]` | `[-0.072055, +0.185477]` | **PASS** | **BIT IDENTICAL** |
| **neg_D** | 负对照 L-ind-geo 动力学 D | `+0.0004953934372990606` | `+0.0004953934372990606` | `[-0.008436, +0.008309]` | `[-0.011822, +0.010964]` | **PASS** | **BIT IDENTICAL** |

- **点估计**：14/14 项全部精确到双精度浮点最后一位，**逐位完全一致**。
- **95% 置信区间**：14/14 项全部精确到双精度浮点最后一位，**逐位完全一致**。
- **Bonferroni 区间**：14/14 项全部精确到双精度浮点最后一位，**逐位完全一致**。
- **门判定**：
  - 主门：GN=Pass, GA=Pass, GC=Pass, GK1=Pass, GK2=Pass, GD=Pass, GX=Pass, **GR=Fail**（下界 -0.002628 $\le 0.0$）。与 `results-p2g.json` 及 `summary-p2g.txt` 判定**完全一致**。
  - 负对照：`neg_C` 上界 0.185477 $< 0.5$, `neg_D` 上界 0.010964 $< 0.5$，**PASS**。与原始记录**完全一致**。

### 2.3 记录级合法性检查（Legality Checks）对照
- **地板门（floor）**：
  - 碰撞事件重认准确率：$E\text{-CV} = 0.364544 < E\text{-B} = 0.421973 < E\text{-P} = 0.679151$；
  - 严格单调递增，**PASS**。
- **样本数门（samples）**：
  - 主评测碰撞事件数：267（预期 $267.0 \times 40 / 40 = 267.0$，在 $\pm 25\%$ 容差内）；
  - 碰撞盘步数：655（下限为 $552.0 \times 75\% = 414.0$）；
  - 均满足要求，**PASS**。
- **完整性门（complete）**：
  - 主评测 40，外推评测 20，与注册规模匹配，**PASS**。

---

## 3. 对抗自检实验（Adversarial Self-Checks）

为证明独立复算脚本具有真正的计算响应能力，而非写死常数或简单复制，设计并执行了 4 组对抗性篡改测试：

### 3.1 篡改 1：少一个世界（Drop World 0 of Main）
- **操作**：将输入主评测世界由 40 个删去 1 个（删除 `world: 0`），仅剩 39 个主世界。
- **运行命令**：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_1_drop_world.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_1_out.json
```
- **门统计量与合法性响应**：
  - 完整性合法性门立即触发失败：`Completeness: FAIL (main=39/40, extrap=20/20)`；
  - 碰撞事件样本数由 267 变为 263；碰撞动力学步数由 655 变为 639；
  - GN 统计量由 `+0.003` (`+0.003161`) 变为 `+0.002` (`+0.002237`)；
  - GC 统计量由 `0.917` (`0.917476`) 变为 `0.913` (`0.912759`)；
  - GR 统计量由 `+0.046` 变为 `+0.048`，Bonferroni 区间移为 `[-0.002, +0.103]`；
  - 地板准确率由 `(0.365, 0.422, 0.679)` 移为 `(0.362, 0.414, 0.677)`。

### 3.2 篡改 2：把一个臂某个种子的对错全翻（Invert Correctness of L-int-g#1）
- **操作**：在全部 60 个世界中，将主臂 `L-int-g` 种子 1 的所有重现事件对错按位取反（`correct = [1 - x for x in correct]`）。
- **运行命令**：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_2_flip_seed.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_2_out.json
```
- **门统计量与合法性响应**：
  - **GN 暴跌**：点估计由 `+0.003` 跌至 `-0.249`，判门由 PASS 转为 **FAIL**；
  - **GA 暴跌**：点估计由 `+0.054` 跌至 `-0.167`，判门由 PASS 转为 **FAIL**；
  - **GC 严重缩水**：点估计由 `0.917` 跌至 `0.485`（Bonferroni 下界由 0.741 跌至 0.251，低于 0.5 门槛），判门由 PASS 转为 **FAIL**；
  - **GX 暴跌**：点估计由 `+0.089` 跌至 `-0.070`，判门由 PASS 转为 **FAIL**；
  - **GR 恶化**：点估计由 `+0.046` 跌至 `-0.065`；
  - 未被篡改的 1 步预测（GK1）、重新出现预测（GK2）及动力学误差（GD）点估计完全保持不变，精准反映了局部扰动的影响范围。

### 3.3 篡改 3：只保留一个种子（Single Seed: --seeds 1）
- **操作**：复算时不进行 3 种子的平滑平均，仅使用种子 1 进行单种子复算。
- **运行命令**：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-P2-DESIGN/tier1-explore/results-p2g.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --seeds 1 \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_3_out.json
```
- **门统计量与合法性响应**：
  - 失去了跨种子平滑，统计量的方差与区间宽度发生明显变化；
  - GA 由 `+0.054` 变为 `+0.063`；
  - GC 由 `0.917` 变为 `0.986`；
  - GR 由 `+0.046` 变为 `+0.045`，Bonferroni 区间拓宽为 `[-0.020, +0.107]`（原为 `[-0.003, +0.099]`）；
  - GK1_all 由 `0.903` 变为 `0.901`；GK1_collision 由 `0.892` 变为 `0.910`；
  - 地板准确率移为 $E\text{-CV}=0.333, E\text{-B}=0.393, E\text{-P}=0.670$。

### 3.4 篡改 4：外推记录换成主评测（Replace Extrapolation with Main）
- **操作**：将外推数据全部替换为主评测的 6 盘世界记录。
- **运行命令**：
```bash
python3 reports/V9-S4-PHASE2/independent-recompute/recompute_p2.py \
  --records reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_4_extrap_replaced.json \
  --params reports/V9-S4-PHASE2/independent-recompute/evidence/params_p2g.json \
  --out reports/V9-S4-PHASE2/independent-recompute/evidence/adversarial_4_out.json
```
- **门统计量与合法性响应**：
  - 完整性门立即检出数量异常：`Completeness: FAIL (main=40/40, extrap=40/20)`；
  - 外推主差值指标 `GX_diff`（原为 10 盘上的 `+0.089`）**精准蜕变为与主评测指标 GA 完全相同的值**：点估计 `+0.054`，区间 `[+0.022, +0.085]`；
  - 外推主差距补回比 `GX_C`（原为 10 盘上的 `+1.025`）**精准蜕变为与主评测指标 GC 完全相同的值**：点估计 `+0.917`，区间 `[+0.741, +1.125]`；
  - 其余主评测门（GN, GA, GC, GK1, GK2, GD, GR）完全不受影响。

---

## 4. 原始执行日志截取

### 4.1 G 轮完整复算原始控制台输出
```text
=== S4 Phase 2 Independent Recomputation (pure NumPy) ===
Records loaded: 40 main worlds, 20 extrapolation worlds
Bootstrap settings: n=10000, seed=20261111, level=0.95, Bonferroni m=12
Arms: main=L-int-g, scatter=L-sc-g, negative=L-ind-geo, seeds=[1, 2, 3]

Statistic            Point [Bonferroni CI]      95% CI                  
------------------------------------------------------------------------
GN                   +0.003 [-0.020, +0.026]    [-0.013, +0.019]        
GA                   +0.054 [+0.022, +0.085]    [+0.032, +0.076]        
GC                   +0.917 [+0.741, +1.125]    [+0.796, +1.051]        
GK1_all              +0.903 [+0.893, +0.913]    [+0.896, +0.910]        
GK1_collision        +0.892 [+0.821, +0.949]    [+0.845, +0.934]        
GK2_non_collision    +0.910 [+0.876, +0.941]    [+0.886, +0.933]        
GK2_collision        +0.818 [+0.745, +0.880]    [+0.768, +0.862]        
GD_D                 +0.852 [+0.809, +0.884]    [+0.825, +0.875]        
GD_ratio             +0.026 [+0.018, +0.036]    [+0.020, +0.033]        
GX_diff              +0.089 [+0.047, +0.136]    [+0.060, +0.121]        
GX_C                 +1.025 [+0.782, +1.261]    [+0.865, +1.181]        
GR                   +0.046 [-0.003, +0.099]    [+0.012, +0.083]        
neg_C                +0.039 [-0.072, +0.185]    [-0.036, +0.127]        
neg_D                +0.000 [-0.012, +0.011]    [-0.008, +0.008]        

Gate Decisions:
  GN   : PASS
  GA   : PASS
  GC   : PASS
  GK1  : PASS
  GK2  : PASS
  GD   : PASS
  GX   : PASS
  GR   : FAIL
  Negative Control: PASS

Legality Checks (from records):
  Floor:        PASS ({'E-CV': 0.3645443196004994, 'E-B': 0.42197253433208487, 'E-P': 0.6791510611735331})
  Samples:      PASS (events=267/267.0, dyn_steps=655/552.0)
  Completeness: PASS (main=40/40, extrap=20/20)

Wrote full recomputation output to reports/V9-S4-PHASE2/independent-recompute/evidence/recomputed-p2g.json

[VERIFICATION SUCCESS] All recomputed stats are 100% BIT-FOR-BIT IDENTICAL to stored values!
[VERIFICATION SUCCESS] All gate decisions match stored decisions exactly!
[VERIFICATION SUCCESS] Negative control decision matches stored value!
```

---

## 5. 验收标准逐条对照

| 验收标准要求 | 达成情况 | 证据支撑 |
|---|:---:|---|
| **脚本不导入 ainerzero** | **达成** | 源码仅依赖 Python 标准库与 `numpy`，不含任何 `ainerzero` 导入语句 |
| **G 轮点估计逐位一致** | **达成** | 全部 14 项点估计与原始落盘浮点数 100% 逐位相同 |
| **G 轮门判定全部一致** | **达成** | 8 个主门及负对照判定完全匹配（含唯一的 GR 失败项） |
| **G 轮区间逐位一致** | **达成** | 95% 置信区间与 Bonferroni 校正区间全部 100% 逐位相同 |
| **四种改坏输入随之变化** | **达成** | 删世界（报完备性FAIL）、翻对错（多门暴跌报FAIL）、减种子（方差拓宽）、换外推（GX精准蜕变并报数量FAIL） |
| **一级验收复跑准备就绪** | **达成** | 提供自包含单命令行与清晰 `README.md`，可随时直接在 G 轮或 future final 上复跑 |

---

## 6. 结论

`recompute_p2.py` 已完全满足 S4 第二阶段非作者独立复算工具的设计与实现要求。
在摸底 G 轮落盘数据上的验证证明：点估计、区间与判定逻辑均达到 100% 双精度浮点逐位一致；4 组对抗测试证明工具具备严格、灵敏的逻辑计算能力与异常检测能力。当 Phase 2 final 完成落盘后，即可直接调用本工具完成权威独立复算。
