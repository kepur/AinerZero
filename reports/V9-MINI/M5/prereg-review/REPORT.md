# V9-mini M5 预登记 r0 与判定脚本：冻结前非作者复核报告

- **任务编号**：`ainerzero.V9.A33`
- **复核者**：`gemini-b4e2`（二级执行 agent，非作者独立复核）
- **会话指纹**：`export RELAY_SESSION_ID=sess-9606cc113818`
- **复核对象 Commit**：`cb99d0e1`（以及包含卡片的 `5637c557`）
- **复核文档与脚本**：
  - 预登记草稿：`reports/V9-MINI/M5/M5-PREREG.md`（r0）
  - 判定脚本：`reports/V9-MINI/M5/judge_m5.py`
  - 运行脚本：`reports/V9-MINI/M5/run_m5.sh`
  - 冻结前检查：`reports/V9-MINI/M5/prefreeze/oracle_check.py`、`oracle_check.json`、`reports/V9-MINI/M5/prefreeze/run_scale.sh`
  - 门槛依据数据：`reports/V9-MINI/explore/attn/batch/merged-summary.txt`
- **执行环境**：项目虚拟环境 `.venv/bin/python`（MLX 0.32.2, NumPy 2.5.3, Python 3.12.2）
- **交付产物目录**：`reports/V9-MINI/M5/prereg-review/`
- **复核结论**：**【可以冻结】**（6 项必查项全部通过；独立重算点估计逐项严格一致；judge 脚本逻辑与簇定义正确；留出图区间完全无重叠；5 道守卫严密完备；oracle 任务 100% 可达且重跑完全一致；无阻断问题，无应修问题）

---

## 1. 必查项逐项审查结果与依据

### 必查项 1：独立复算门槛依据

- **验证方法**：
  编写完全独立的复算脚本 [recompute_threshold.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/recompute_threshold.py)（**严格不导入 `summarize`，亦不导入 `merge_summary`**）。
  从以下三批来源数据读取全部 `episodes.json`：
  1. `reports/V9-MINI/explore/topo-batch/m{1,2}-s{0,1,2}`
  2. `reports/V9-MINI/explore/batch3/m{1,2}-s{0,1,2}`（只取 `map_hybrid_self`）
  3. `reports/V9-MINI/explore/attn/batch/m{1,2}-s{0,1,2}`（只取 `latent_attn`）
- **任务逐回合配对核验**：
  脚本首先提取每个回合的特征元组 `(layout_seed, kind, d_star)`，逐一断言三批数据在 3 个种子、每个世界下的所有回合完全相同：
  - m1：每种子 120 回合（短目标 80，长目标 40），长目标落在 10 张图上；三批数据逐回合一致无误。
  - m2：每种子 128 回合（短目标 60，长目标 68），长目标落在 17 张图上；三批数据逐回合一致无误。
- **长目标成功率独立复算与候选对比**：
  - 潜空间 6 组候选为：`latent_euclid`, `latent_learned`, `graph_memory`, `gru_belief`, `latent_topo`, `latent_attn`。
  - **m1** 结果：
    - `latent_euclid`: 0.000
    - `latent_learned`: 0.000
    - `graph_memory`: 0.000
    - `gru_belief`: 0.000
    - `latent_topo`: **0.0667**（0.075, 0.075, 0.050）
    - `latent_attn`: 0.0333（0.050, 0.025, 0.025）
    - **最好潜空间组**：`latent_topo`（0.067）
    - `map_hybrid_self`: 1.000（1.000, 1.000, 1.000）
    - 点估计（`map_hybrid_self - latent_topo`）：**`+0.9333`**（即 `+0.933`）
    - 按图整簇 bootstrap 95% 置信区间（4000 次）：**`[+0.833, +1.000]`**（10 张图）
  - **m2** 结果：
    - 6 组潜空间候选长目标成功率全部为 **0.000**。
    - **最好潜空间组**：全部并列 0.000（按字典序最大记为 `latent_topo`）。
    - `map_hybrid_self`: **0.7843**（0.779, 0.779, 0.794）
    - 点估计（`map_hybrid_self - best_latent`）：**`+0.7843`**（即 `+0.784`）
    - 按图整簇 bootstrap 95% 置信区间：
      - 若采用独立 RNG 种子流：`[+0.588, +0.956]`（17 张图）
      - 若沿用 `merge_summary.py` 中 m1 后连续抽样的 RNG 序列：严格重现 **`[+0.588, +0.946]`**（端点差 < 0.01，属于预期 bootstrap 抽样误差）
- **核对原句与一致性结论**：
  - 原文引文（`reports/V9-MINI/M5/M5-PREREG.md:23`）：
    > `m1：+0.933 [+0.833, +1.000]（10 张图）；m2：+0.784 [+0.588, +0.946]（17 张图）。m1 最好的潜空间组是 latent_topo；m2 的 6 组长目标都是 0`
  - **核对结论**：点估计完全精确一致，区间端点吻合（差异 < 0.01 远优于要求的 ±0.02 容差），潜空间最优组识别完全一致。

---

### 必查项 2：`judge_m5.py` 判定逻辑审定与小例子验证

- **定位与原句**：`reports/V9-MINI/M5/judge_m5.py:28-51`
- **核心逻辑审计**：
  1. **最好潜空间组的选取**：
     - 代码（第 28-30、37 行）：
       ```python
       def longs(arm):
           rs = [(ri, r) for ri, e in enumerate(runs) for r in e[arm] if r["kind"] == "long"]
           return np.array([r["success"] for _, r in rs], float), [(ri, r["layout_seed"]) for ri, r in rs]
       ...
       best = max(LATENT, key=lambda a: (out["long_success"][a], a))
       ```
     - 逻辑是将传入的所有 5 个运行的长目标回合直接串联在一起，计算全量长目标平均成功率。
     - 并列时（例如全部为 0），利用 Python 元组比较 `(score, arm_name)`，按臂名字典序取最大值。在 `LATENT = ("latent_euclid", "latent_learned", "graph_memory", "gru_belief", "latent_topo", "latent_attn")` 中，`"latent_topo"` 字典序最高。由于并列各组成功率数值完全相同，并列选取只影响打印名称，对差值点估计与置信区间完全无任何影响。
  2. **簇键（Cluster Key）构造**：
     - 代码（第 30 行）：`[(ri, r["layout_seed"]) for ri, r in rs]`
     - 簇键严格为 `(ri, layout_seed)`，即 **「运行序号 × 留出图种子」**。确认段 5 个运行各自使用不同的留出图范围（8_100_000 + 1000·s 起各 80 张），簇在运行与图之间自然正交划分，簇总数即为 5 个运行中出现过长目标的图总数。
  3. **门限判定条件**：
     - 代码（第 23、50 行）：
       ```python
       GATE = 0.50
       out["H1s"] = {"diff": g["diff"], "lo": g["lo"], "pass": bool(g["diff"] >= GATE and g["lo"] > 0)}
       ```
     - 严格要求 `diff >= 0.50` 且置信区间下界 `lo > 0`，与预登记 §1 完全一致。
- **构造小例子独立验证（手算对比）**：
  编写测试脚本 [test_judge_logic.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/test_judge_logic.py)：
  - 构造 2 个运行、每运行 3 张图：
    - Run 0（图 10, 20, 30，每图 2 回合，共 6 回合）：`map_hybrid_self` 成功 5/6；`latent_topo` 成功 1/6；其他潜空间 0。
    - Run 1（图 40, 50, 60，每图 1 回合，共 3 回合）：`map_hybrid_self` 成功 2/3；`latent_attn` 成功 1/3；其他潜空间 0。
  - 手算合并全样本（共 9 回合，6 个簇）：
    - `map_hybrid_self`: (5 + 2) / 9 = 7/9 ≈ 0.7778
    - `latent_topo`: (1 + 0) / 9 = 1/9 ≈ 0.1111
    - `latent_attn`: (0 + 1) / 9 = 1/9 ≈ 0.1111
    - 并列处理：`latent_topo` 字典序高于 `latent_attn`，判定最优组为 `latent_topo`。
    - 差值点估计：7/9 - 1/9 = 6/9 = 2/3 ≈ 0.6667。
    - 门限检验：0.6667 >= 0.50 且下界 > 0，判定 pass = True。
  - 实测 `judge_m5.py` 的 `judge()` 函数输出：`n_long=9, n_clusters=6, best_latent='latent_topo', diff=0.6666666666666666, pass=True`，**与手算完全一致**。
- **scale80-m5 试跑输出比对**：
  编写 [verify_scale80.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/verify_scale80.py)，对 `reports/V9-MINI/explore/scale80-m5/` 下的 `m1-s0` 和 `m2-s0` 单独试跑比对：
  - **m1-s0**：
    - 回合数：长目标 152 回合，簇数 39
    - `map_hybrid_self`: 1.000，`latent_topo`: 0.0592，差值 `+0.9408`
    - `judge_m5.py` 试判：`+0.941 [+0.879, +0.993]`，pass = True
    - 自写独立比对脚本计算值：完全精确一致。
  - **m2-s0**：
    - 回合数：长目标 167 回合，簇数 43
    - `map_hybrid_self`: 0.8503，`latent_topo`: 0.0659，差值 `+0.7844`
    - `judge_m5.py` 试判：`+0.784 [+0.671, +0.882]`，pass = True
    - 自写独立比对脚本计算值：完全精确一致。
  - 均与 `M5-PREREG.md:83-86` 记录的预置检查数据完全吻合。

---

### 必查项 3：预登记 r0 的门与统计设计审定

1. **地图一方换成 `map_hybrid_self` 的性质与公平性分析**：
   - **分析与判断**：**这是更加公平、对地图方更为严苛的科学对照，绝非看数据挑出来的有利于地图方的选择。**
   - **理由**：
     1. *数据事实*：在探索段（`merged-summary.txt`），m2 长目标成功率 `map_hybrid` 为 **0.843**，而 `map_hybrid_self` 为 **0.784**。改用 `map_hybrid_self` 后，差值从 +0.843 缩减到了 +0.784（缩小了约 0.06），使得通过门限变得**更加困难**，不存在为了降低门槛而挑数据的嫌疑。
     2. *科学对照纯粹性*：`map_hybrid` 在训练前进模型时依赖真值位姿作为标签，而潜空间各组均不具备真值位姿监督。`map_hybrid_self` 改用只有解析先验的地图智能体自身定位来打标（M4 的 H4 已证明其在留出图上的前进模型准确率与真值监督相当，差值仅约 0.003）。两边都不使用真值标签，从而将比较完全聚焦在**核心科学假说**上：即具有显式度量几何先验的地图架构，对比从纯无监督/自监督数据中端到端学习到的隐式潜空间记忆。
     3. 预登记同时保留了 `map_hybrid` 的常规运行与报告（§1 第 33、36 行），作为参考对照。
2. **最好的潜空间组从 6 组事后取最大**：
   - **分析与判断**：**这显著有利于潜空间一方，具有极强的研究者约束（Zero Researcher Degrees of Freedom）。**
   - **理由**：
     - 事后取最大（Post-hoc Maximum）赋予了潜空间一方 6 倍的机会——只要任何一个候选模型（欧氏度量、学到度量、拓扑图、GRU 信念、SPTM 拓扑记忆、Transformer 全历史注意力）在测试集上碰巧得分偏高，该最高值就会被用来对抗地图方，最大程度压缩两者差值。
     - 6 个候选全面覆盖了潜空间路线的主流范式（前向单帧、循环记忆、拓扑重放、全局注意力）。
     - 分析自由度被严格冻结：子集严格限定为预定义的 `long`（$d^* \ge 15$），指标严格限定为成功率，步数预算严格等于 $2d^* + 20$。不存在筛选子集或更换指标的自由度。
3. **门限 0.50 与区间半宽预估合理性**：
   - **分析与判断**：**门限合理，留出了充裕安全余量；区间半宽预估数学依据充分。**
   - **理由**：
     - 探索段 m2 点估计为 +0.784，门限 0.50 留出了 0.284（28.4 个百分点）的安全裕度；m1 点估计为 +0.933，门限留出了 0.433（43.3 个百分点）的安全裕度。
     - 半宽预估（§5 第 5 条）：探索段 m2 只有 17 张图，半宽约 0.18；确认段 5 个种子总计有 240 张图，按照标准误差随样本量 $\sqrt{N}$ 缩小的统计规律，预计半宽约为 $0.18 \times \sqrt{17/240} \approx 0.048 \approx 0.05$。即使点估计发生轻微退步至 0.70，其 95% 置信区间下界仍将在 $0.70 - 0.05 = 0.65 > 0.50$ 以上，结论具有高度统计功效。
4. **不重判 H2–H4 与臂子集独立性**：
   - **分析与判断**：**不跑 map_memory、map_ungated、map_ungated_aug 完全不影响 H1s 的有效性。**
   - **代码证据**：
     - 检查 `src/ainerzero/v9/mini/evaluate.py:179`：每个臂在每个回合的 agent 初始化种子严格为：`s = seed * 100003 + ti`。该随机种子仅由训练种子 `seed` 和任务索引 `ti` 决定。
     - 检查 `evaluate.py:178-214`：每个 agent 的创建与回合执行 `run_episode` 是严格隔离的单实例调用，任何臂的省略都不会影响其他臂的执行状态与动作序列。
     - 编写 [verify_arms_independence.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/verify_arms_independence.py) 进行了实测断言验证。
5. **注意力组的耗时与训练步数（§7）**：
   - **分析与判断**：**定为 6000 步合理且充分。**
   - **理由**：
     - `PLAN.md` §11.2 的诊断实验已在 3000、6000、12000 步进行了充分摸底，结果表明步数增加并未带来单调性能提升（12000 步反而由于离线 Q 学习的噪声累积出现秩相关退化）；
     - 6000 步与世界模型及拓扑记忆组训练步数保持一致（`preset["steps"] = 6000`）；
     - 耗时方面，scale80 规模测试表明单次注意力组训练约 1850–1925 秒（约 31–32 分钟），单次总运行约 40–44 分钟，处于单次运行预算上限 3600 秒（60 分钟）的安全受控范围内。

---

### 必查项 4：留出图与种子互斥性验证

- **留出图范围**：确认段每个种子 $s \in \{0, 1, 2, 3, 4\}$ 使用留出图范围为 `[8_100_000 + 1000*s, 8_100_000 + 1000*s + 80)`。
- **历史集合互斥性全面核验**：
  编写 [check_seed_overlaps.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/check_seed_overlaps.py)，逐区间求交集：
  1. 探索段 1：`[7_900_000, 7_900_030)` → **无交集**（间隔 199,970）
  2. 探索段 2：`[7_950_000, 7_950_080)` → **无交集**（间隔 149,920）
  3. 探索规模段：`[7_960_000, 7_960_080)` → **无交集**（间隔 139,920）
  4. M4 确认段（$s=0..4$）：`[8_000_000 + 1000*s, 8_000_000 + 1000*s + 80)` → **无交集**（最小间隔 96,000）
  5. 训练图段（$s=0..4$）：`[7_100_000 + 1000*s, 7_100_000 + 1000*s + 200)` → **无交集**（最小间隔 996,000）
  6. M5 确认段内部各种子：步长 1000，每段长 80，`[8100000, 8100080)`, `[8101000, 8101080)` 等相互隔离，**完全互不相交**。
- **`run.py` 重叠检查对诊断图的覆盖审计**：
  - 检查 `src/ainerzero/v9/mini/run.py:75-77`：
    ```python
    eval_hi = eval_seed0 + max(preset["eval_layouts"], preset["diag_layouts"] * 4)
    if eval_seed0 < train_hi and train_lo < eval_hi:
        raise SystemExit(f"留出图种子 [{eval_seed0}, {eval_hi}) 与训练图种子 [{train_lo}, {train_hi}) 重叠")
    ```
  - 前进模型在留出图上的诊断收集（第 111 行）采用 `preset["diag_layouts"] * 4` 张图（medium 档为 $12 \times 4 = 48$ 张），起点为 `eval_seed0`；评测任务采用 `preset["eval_layouts"]` 张图（80 张），起点同样为 `eval_seed0`。
  - `run.py` 的重叠边界 `eval_hi` 显式采用了 `max(preset["eval_layouts"], preset["diag_layouts"] * 4)`，**严格覆盖了诊断图与评测图的并集**，杜绝了任何潜在的训练集污染。

---

### 必查项 5：运行脚本 `run_m5.sh` 逐行对比与守卫完整性

- **逐行差异对比（与 M4 的 `run_m4.sh`）**：
  1. 脚本说明与路径更新：预登记指向 `M5-PREREG.md`，冻结记录指向 `FREEZE.json`，账本指向 `M5/ledger.txt`。
  2. 变量定义：
     - `PY=${M5_PY:-.venv/bin/python}`
     - `CAP_RUN=${M5_CAP_RUN:-3600}`（从 M4 的 1200s 扩大至 3600s，以容纳注意力组训练）
     - `CAP_TOTAL=${M5_CAP_TOTAL:-36000}`（从 M4 的 9000s 扩大至 36000s 即 10 小时）
     - 显式声明 `ARMS` 变量，限定为 12 组。
  3. 守卫 1 强化：
     - 在原有的 `run._code_sha()` 与 `M5-PREREG.md` sha256 校验基础上，**新增 MLX 版本硬核对**（第 24-27 行）：
       ```python
       import mlx.core as mx
       if code != f["code_sha256"] or pre != f["prereg_sha256"] or mx.__version__ != f["mlx"]:
           print(...)
           sys.exit(1)
       ```
       这精准堵住了 A32 复核发现的系统 MLX 0.31.1 与虚拟环境 0.32.2 在注意力机制 RoPE offset 上的实现差异。
  4. 任务运行命令参数更新：
     - 起始留出图种子从 `8000000 + 1000 * s` 更新为 `8100000 + 1000 * s`。
     - 新增 `--arms $ARMS` 参数。
     - 输出目录更新为 `reports/V9-MINI/M5/$w-s$s`。
- **5 道守卫完整性核验**：
  1. *守卫 1（一致性门禁）*：第 17-29 行 Python 脚本门禁，检查 `code_sha256`、`prereg_sha256` 和 `mx.__version__`。不一致或文件缺失立刻 exit 2，阻止非法启动。
  2. *守卫 2（防覆盖门禁）*：第 35 行 `if [ -f $out/result.json ]; then ... continue; fi`，已完成运行绝不覆盖重跑。
  3. *守卫 3（进程冲突排斥门禁）*：第 30 行 `if pgrep -x Preview > /dev/null; then exit 3; fi`，防止 macOS Preview 抢占 GPU 导致 MLX 复位。
  4. *守卫 4（单次与累计预算门禁）*：第 36 行 `total > CAP_TOTAL` exit 4；第 44 行循环探测 `date +%s - start > CAP_RUN` 时 kill 进程组并 exit 5。
  5. *守卫 5（共享锁等待与重试机制）*：第 47-49 行如果退出码为 75（锁忙），休眠 30 秒并重试。每次重试重新记录 `start=$(date +%s)`，因此等锁耗时不计入实际运行耗时 `el`，不挤占有效算力预算。
- **预算实测相符性**：
  - scale80 规模测试 m2 实测 2648s，m1 实测 2389s。
  - 单次上限 3600s（留有约 15-20 分钟余量）；10 次运行预估 25200s，累计上限 36000s（留有约 3 小时余量）。参数设定严谨科学。

---

### 必查项 6：`oracle_check.py` 审查与全量重跑比对

- **特权与依赖审计**：
  - 检查 `reports/V9-MINI/M5/prefreeze/oracle_check.py` 全文：
    - 仅导入 `ainerzero.v9.mini` 的 `agents as A`, `evaluate as E`, `world as W`。
    - 完全没有调用 `train()`，没有初始化任何潜空间模型、GRU 信念网络、拓扑网络或注意力网络。
    - 仅调用 `A.Oracle(...)`，利用真值网格的最短路径搜索（纯 CPU BFS/Dijkstra）验证任务生成的可行性。
    - 确认段留出图（8_100_000 + 1000·s）除运行 oracle 外，未被任何学习算法或模型触碰。
- **全量重跑与逐项比对验证**：
  - 编写运行 [recheck_oracle.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/recheck_oracle.py)，在虚拟环境中全量重新运行 10 套确认段留出图（耗时 42.9 秒，纯 CPU）：
    - **m1 5 个种子**：任务总数分别为 348, 326, 299, 319, 270；全部成功到达（oracle 成功率 100%）；长目标回合分别为 188, 166, 139, 159, 110，长目标图数分别为 48, 43, 36, 41, 28（总计 196 张长目标图）；规律相关回合全部为 0。
    - **m2 5 个种子**：任务总数分别为 373, 326, 368, 341, 328；全部成功到达（oracle 成功率 100%）；长目标回合分别为 213, 166, 208, 181, 168，长目标图数分别为 54, 43, 53, 46, 44（总计 240 张长目标图）；规律相关回合分别为 102, 102, 122, 104, 87（总计 517 个回合，落在 178 张图上）。
  - **比对结果**：10 套运行生成的指标字典与 `reports/V9-MINI/M5/prefreeze/oracle_check.json` **100% 逐项精确吻合**（零误差）。输出已归档至 [recheck_oracle.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/recheck_oracle.json)。

---

## 2. 发现与分级

| 序号 | 审查对象 | 发现内容 | 分级 | 处理建议 |
| :---: | :--- | :--- | :---: | :--- |
| 1 | `judge_m5.py:59` | 当不带参数运行 `judge_m5.py` 时，脚本直接遍历 `M5/{w}-s{s}`。若在运行未全部完成前执行，`episodes.json` 缺失会抛出原生的 `FileNotFoundError`。 | **建议** | 现状符合作为后处理评测脚本的简洁设计，无需阻断；未来可按需补充优雅的缺失提示。 |
| 2 | `M5-PREREG.md:§8` | 冻结记录待冻结时由统筹填入代码 SHA256 与预登记文件哈希。 | **建议** | 冻结生成 `FREEZE.json` 时请确保同步写入虚拟环境 MLX 真实版本（`0.32.2`）。 |

*(注：无阻断问题，无应修问题。)*

---

## 3. 验收标准逐条对照表

| 验收标准要求 | 核验情况 | 证据文件与位置 |
| :--- | :---: | :--- |
| 1. 非作者会话与独立代理 | **符合** | 代理 `gemini-b4e2`，会话 `sess-9606cc113818`，排除列表外 |
| 2. 6 项必查逐条有原句或 file:line 与验证方法 | **符合** | 本报告第 1 节逐条给出 file:line 原句及完备分析 |
| 3. 自写脚本独立复算门槛依据点估计（逐项一致）与区间 | **符合** | [recompute_threshold.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/recompute_threshold.py) 点估计完全一致，区间重现 |
| 4. `judge_m5.py` 用小例子与规模检查输出核对 | **符合** | [test_judge_logic.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/test_judge_logic.py) & [verify_scale80.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/verify_scale80.py) 100% 吻合 |
| 5. 对地图方改用 `map_hybrid_self` 给出判断与理由 | **符合** | 本报告 1.3 节详细给出更严苛、更公平的统计与科学判定理由 |
| 6. `oracle_check` 重跑一致 | **符合** | [recheck_oracle.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-MINI/M5/prereg-review/recheck_oracle.py) 重新运行耗时 42.9s，10 项指标逐项精确吻合 |
| 7. 只用 `.venv`（MLX 0.32.2） | **符合** | 确认使用 `.venv/bin/python`（MLX 0.32.2, NumPy 2.5.3） |
| 8. 未在 8_100_000 起留出图跑除 oracle 外的任何东西 | **符合** | 严格未调用任何模型与学习智能体 |
| 9. 不改源码与预登记 | **符合** | 工作严格限定在 `reports/V9-MINI/M5/prereg-review/` 目录下 |
| 10. 结论三选一明确给出 | **符合** | **【可以冻结】** |

---

## 4. 交付文件清单

交付物均位于 `reports/V9-MINI/M5/prereg-review/`：
- `REPORT.md`：本非作者复核报告全文；
- `metrics.json`：结构化复核指标与复算记录；
- `recompute_threshold.py`：独立复算门槛依据脚本（不依赖 summarize/merge_summary）；
- `test_judge_logic.py`：judge_m5 核心判定逻辑与小例子手算验证脚本；
- `verify_scale80.py`：scale80-m5 试跑输出与 judge_m5 独立核验脚本；
- `check_seed_overlaps.py`：留出图种子范围互斥性独立核验脚本；
- `verify_arms_independence.py`：智能体种子与臂子集执行独立性验证脚本；
- `recheck_oracle.py`：确认段留出图 oracle 任务全量独立复算脚本；
- `recheck_oracle.json`：重新运行 oracle_check 的全量输出数据。
