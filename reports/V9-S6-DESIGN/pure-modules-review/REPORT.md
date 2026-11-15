# P256 S6 一期纯 NumPy 模块（沙盒 r2 + 指标与区间）：非作者复核

> 复核者：claude 子代理（与作者同模型，无作者上下文），2026-11-15。harness 不允许子代理写 .md 报告文件，本文由一级照原文落盘。`SHA256SUMS.txt` 只覆盖 `evidence/` 的 30 个文件，REPORT.md 落盘后请补一行。

- **对象**：开始时 HEAD 是 `34a1753`；复核期间一级又提交了 `4cdbee9`，只改 RESEARCH_LOG。被审文件在两个提交里相同，工作树与 HEAD 无差异（`evidence/e01-live-tests.txt` 首部）：
  - `sandbox.py` efeabd08…
  - `analysis.py` baf00ede…
  - `cells.py` 0e40b941…
  - `test_s6_sandbox.py` abc9ad18…
  - `test_s6_analysis.py` b7fcb9ab…
  - `test_s6_cells_static.py` c3d1b5c4…
- **运行方式**：
  - 纯 NumPy，全程没有导入 MLX。需要 `learned_mlx.make_pool` 和 `cells.sealed` 的地方，用 ast 摘出源码原文，放进不含 MLX 的模块里执行。没有用锁。
  - 只写本目录。隔离副本和 bootstrap 中间数组放在会话 scratchpad；作者脚本自建的副本在 `$TMPDIR`。
  - 没有改源码、测试、设计稿和已有报告；没有 stash、checkout、reset；没有提交。
- **引文**：每处引文的 `sed -n` / `grep -n` 原始输出在 `evidence/citations.txt`，编号 C1–C30。

## 结论：打回（小修：代码不用改，只补测试）

**代码层面没有发现错误：**
- 沙盒 r2 的「挑之前没有标签」，从公开接口和私有路径都找不到漏洞。
- `sim_labels` 与 `make_pool` 在 1259 个状态上逐位相同。
- 用我独立写的 r1 公式重算 7 组合成数据，与 `decide()` 的 884 个量全部一致，最大差 3.2e-12。
- t 分位数正确；门表与 DESIGN-r2 §4 逐条相同；作者的变异日志属实。

**打回原因：**我设计了 13 个变异，8 个存活，全部是非等价变异。其中两处正对着 r1 必修 1（统计公式）和 r1 必修 3（标签不存在）。

### 必修

1. **`decide()` 有三处没有被测试钉住：Bonferroni 界、θ_k 的按重复配对、比值门的点值**（Q1、Q2、Q3 存活）。作者的 A1 之所以被杀，只是因为 `levels` 字段被检查了。
   - Q1：门的区间改用 95% 水平（`levels` 不变），57 项全过。在合成数据上，它会让一个本该不过的 GZ-W 判为过（`e08`）。
   - Q2：θ_k 不按重复配对（R、Z 改用重复 k+1），全过。在带重复效应的数据上，GZ-D、GZ-W 的判定翻转（`e08`）。
   - Q3：比值门的点值改为各重复比值的几何平均，全过。
   - 原因有两条：
     - `make_data` 没有重复层效应，各臂、各重复的噪声互相独立，配对与否看不出差别（`tests/v9/experiments/test_s6_analysis.py:28`）；
     - 断言只查 `levels` 字段和区间的包含次序（`:206`、`:211`），不查 `decide` 里实际用的 q 和界。
   - 建议：
     - 加一条端到端测试，数据里要有「同一重复内各臂共享」的效应；
     - 期望值在测试内用独立公式算：世界和之比，t(4, 0.996875) = 5.26106 写死；
     - 逐门核对 point、per_replicate、s_rep、se_w、q、bonferroni、ci95，误差 1e-9。`evidence/indep_gates.py` 可作参考；
     - 补完后 Q1、Q2、Q3、A1′ 应全部被杀死。

2. **「揭示前不模拟」只守住了注入的 labeller 这一条路**（R5 存活）。
   - R5：构造函数里直接调 `sim_labels`，把全部候选模拟一遍，存进新属性 `_cache`。57 项全过。
   - 探针：这样构造的池在任何揭示之前就持有全部标签，与之后 `reveal` 返回的逐位相同（`e07`）。
   - 原因：`test_pick_loop_never_simulates` 只断言 `spy.calls == []` 和 `cp._outcomes == {}`（`test_s6_sandbox.py:93-94`）。
   - 运行器里也拦不住：
     - 候选池在封印之外构造（`cells.py:318`、`:320`），封印和静态检查都管不到；
     - 按我对 `test_s6_cells_native.py` 的阅读（未运行，推断），也没有一条会失败。
   - 为什么这条必须有测试：DESIGN-r2 §6 ① 正是以「未选中样本的结果不存在」为由，取消了「偷读」负对照，所以「不存在」本身要有测试守住。
   - 建议：
     - 把 `s4.world.physics`（模块属性）换成计数或抛错的陷阱，覆盖构造、`states()`、`remaining()`、`log()`、`revealed_ids()`、`revealed_pool()`、三个挑选函数和 `geo_flags`，断言调用 0 次；
     - `reveal` 之后，断言调用次数 = 揭示样本数 × 10；
     - `evidence/leak_probe.py` 的 L1 就是这样做的。

### 应修

3. **R1b 存活：一次揭示跨两个盘数时，后一组失败会留下前一组的标签。**
   - 现码正确（`e02` L4）。
   - 但 `test_a_failed_simulation_registers_nothing` 只用单组 `[0, 1]`（`:109-111`）。
   - 建议加一条跨两组、第二组失败的用例。
4. **R4 存活：`sim_labels` 把撞墙、撞柱也记进盘间接触矩阵，纯 NumPy 测试不报错。**
   - 原因：测试用的 3 个状态第一步都没有墙或柱接触。
   - 影响：在类似候选的状态里约有 12% 第一步有墙或柱接触，T 臂的课程和接触头都读这个标签（`e07`）。
   - native 测试的 156 个状态里有 27 个这样的状态，逐位比较应能抓到（未运行，推断）。
   - 建议纯 NumPy 测试补一个第一步撞墙或撞柱的状态。
5. **Q5 存活：`t_cdf` 奇数自由度的级数循环体从 df = 5 才执行，测试只覆盖 df 1、2、3、4、10、30。**
   - 正式运行 K = 5（df = 4）不受影响。
   - 若 K = 6，变异后的 q 是 5.947，正确值是 4.526（`e08`）。
   - 建议在 `test_t_quantiles` 加 df 5 和 df 7。
6. **cells 的静态检查可以用别名绕过**（X1、X2 存活）。这两项属于 `cells.py` 与 `test_s6_cells_static.py`，可以并入运行器的复核。
   - X1：写 `pool = track.cp; pool._assemble(pool.revealed_ids().tolist())`，挑选时就能读到已揭示样本的标签。检查不出来有两个原因：
     - `pool_calls` 只认 `X.cp.method()` 这种写法（`test_s6_cells_static.py:42-44`）；
     - `_assemble` 不在 FORBIDDEN 里。
   - X2：模块级写 `_step = W.physics`，再在 `closest_pair` 里调用。
     - 静态检查只扫 SELECTION 列出的函数体，看不到模块级别名；
     - 我摘出 `cells.sealed()` 原文实测：封印期间 `W.physics` 抛 SealBreach，预存的别名却照常返回结果（`e07`）。r1 复核已指出过这一点。
   - 建议：
     - 把 `revealed_pool`、`_assemble` 也放进 `_SEALED`，挑选本来不需要任何标签；
     - 静态检查扩大到整个模块，禁止把 FORBIDDEN 里的属性绑定给别的名字，或者改成白名单。
7. **作者材料的措辞**：
   - `mutate_pure.log` 的 A11「world draws not shared」只是颠倒了两个测试集的抽取次序，世界照样各臂共用。杀死它的是抽取次序测试，不是配对测试（`e10`）。真正守住配对的是 A4 和我的 Q4。
   - A1 只因为 `levels` 字段被检查才死；把 m = 6 只写进界的 A1′ 存活（`e10`）。
   - `analysis-module/REPORT.md:81` 和 `DESIGN-r2.md:347` 都写「变异 11 个全部被杀死」，字面属实，但不说明 Bonferroni 界有测试守住。等必修 1 补完再写这句。

### 不阻塞，供参考

- `pool_type` 在模拟之后失败，揭示仍会被登记（L5）。docstring 只承诺「模拟失败不登记」（`sandbox.py:133`），不矛盾；`L.Pool` 也不会在这里失败。
- K = 2 时 q = t(1, 0.996875) = 101.86。冒烟运行每臂 2 个重复（`DESIGN-r2.md:299`），门必然全不过，只能查流程，跑不到「过」的分支。
- `decide(n=1)` 时 se_w 无定义，全部门判不过，并给出 RuntimeWarning（`e11`）。正式 n = 10000，没有影响。
- `copy.deepcopy(pool).reveal(...)` 能在副本上揭示（L9），这在模块管辖之外；cells 的封印打在类上，挑选期间副本同样被拦住。pickle 现在只带已揭示样本的标签，比 P253 好。

---

## 1. 沙盒 r2：挑之前是否真的没有标签

### 1a 泄漏探针

脚本 `evidence/leak_probe.py`，原始输出 `e02-leak-probe.txt`。做法：
- 把 `W.physics` 换成计数器，所以 `sim_labels` 以及任何直接调用都会被计数；
- labeller 也单独计数。

命令：

    $ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/leak_probe.py

原始输出（节选，逐字）：

    mlx imported: False
    L1 zero-arg callables invoked before any reveal: ['__dir__', '__hash__', '__len__', '__repr__', '__sizeof__', '__str__', 'log', 'remaining', 'revealed_ids', 'revealed_pool', 'states']
    L1 simulator calls: 0 | labeller calls: 0 | _outcomes keys: []
    L2 after reveal([13,2,8]), reveal([0]): _outcomes keys [0, 2, 8, 13] | revealed [13, 2, 8, 0] | labeller calls (rows per call) [1, 1, 1, 1] | simulator calls 40
    L3 _assemble([5]) on an unrevealed id: KeyError 5
    L4 labeller calls (n per call): [4, 6] | revealed [] | log [] | _outcomes keys [] | remaining has 0,1,8,9: True
    L5 afterwards: revealed [3] | log [{'call': 0, 'ids': [3]}] | _outcomes keys [3]
    L6 labeller calls caused by the bad inputs: 0 | revealed [1, 2] | log calls 1 | _outcomes keys [1, 2]
    L8 stored states unchanged after a scribbling labeller: True
    L9 pickle carries outcomes only for revealed ids: [0] | bytes 5328
    L10 W.physics on the float32 public state vs revealed p1, v1: max |diff| 9.5367431640625e-07 0.0
    L12 methods referring to _simulate (attribute or bare name): ['reveal']
    L12 methods referring to _labeller (attribute or bare name): ['__init__', '_simulate']
    L12 methods referring to _outcomes (attribute or bare name): ['__init__', '_assemble', 'reveal']

各条含义：
- **L1**：揭示之前，把所有不需要参数的可调用成员（含 dunder）都调一遍，模拟器调用 0 次。
- **L2**：每次揭示只模拟被选中的行；`_outcomes` 只有已揭示的编号。
- **L3**：`revealed_pool` 和 `_assemble` 在结构上无法混入未揭示样本，因为那个样本的结果根本不存在。
- **L4**：一次揭示跨两组、第二组失败时，什么都不登记。
- **L6**：11 种坏输入都在模拟之前报错：跨次重复、同次重复、越界、负数、空、二维、float、bool、object、uint64 超大、先合法后越界。
- **L10**：拿公开的 float32 状态加上模拟器，可以近似重算出标签。这是封印要管的事，不是候选池的事。

`reveal` 原文（`src/ainerzero/v9/experiments/s6/sandbox.py:134-140`）：

            ids = self._check_new(ids)
            outcomes = self._simulate(ids)
            self._revealed.extend(ids)
            self._revealed_set.update(ids)
            self._outcomes.update(outcomes)
            self._log.append({"call": len(self._log), "ids": list(ids)})
            return self._assemble(ids)

`_simulate` 只把选中的行交给 labeller（`sandbox.py:178`）：

                lab = self._labeller(e["p"][rows], e["v"][rows], e["pil"][rows])

**测试缺口**（详见 §4）：
- R5 存活 → 必修 2；
- R1b 存活 → 应修 3。

### 1b P253 复核意见在 r2 中的处理（`citations.txt` C21）

| 意见 | r2 的处理 | 验证 |
|---|---|---|
| N1 dunder 绕过 | `test_class_members_are_the_documented_ones` 断言类自身的可调用 dunder 只有 `__init__`、`__len__`；结构测试只允许 `reveal` 引用 `_simulate` | 作者 S6、我的 R1 都被杀死 |
| N2 第二次 reveal 的返回 | 测试断言第二次 `reveal([9, 3])` 只返回这两个 | 作者 S8 被杀死 |
| N3 同分规则的测试规模 | `test_pick_top_ties_at_scale`：200 个编号、三档分数，并断言原型的写法给出不同结果 | 作者 S4 被杀死 |
| N5 states 返回视图 | 断言 `owndata`，强制可写后改写返回数组，内部不变 | 作者 S7 被杀死 |
| `reveal([])` | 现在报 ValueError，不再占用 call 编号 | L6 和测试 |
| 负编号 | `reveal` 报 IndexError；挑选函数的 `_canon` 查下界，报 IndexError | L6；作者 S9 被杀死 |
| SHA256SUMS 路径基准混用 | `sandbox-module/r2` 和 `analysis-module` 都统一相对交付目录，进入目录后 `shasum -c` 全部 OK | 本次核对 |

### 1c `sim_labels` 与 `make_pool` 是否同一算法

**逐行对照。**

`sim_labels`（`sandbox.py:48-59`）：

        for b in range(S_):
            pillars = tuple(map(tuple, PIL[b]))
            p, v, c = W.physics(P[b:b + 1], V[b:b + 1], pillars, log=True)
            for kind, i, j in c:
                if kind == "disk":
                    contact[b, i, j] = contact[b, j, i] = 1.0
            for k in range(1, max(ROLLOUT) + 1):
                if k > 1:
                    p, v, _ = W.physics(p, v, pillars)
                if k in ROLLOUT:
                    out[f"p{k}"][b], out[f"v{k}"][b] = p[0], v[0]
        return {"contact": contact, **{k: a.astype(np.float32) for k, a in out.items()}}

`make_pool`（`src/ainerzero/v9/experiments/s4/learned_mlx.py:209-226`，节选）：

            contact = np.zeros((len(idx), n, n), dtype=np.float32)
            p1, v1 = np.empty_like(P), np.empty_like(V)
            for b in range(len(idx)):
                pb, vb, c = physics(P[b:b + 1], V[b:b + 1], pillars, log=True)
                p1[b], v1[b] = pb[0], vb[0]
                for kind, i, j in c:
                    if kind == "disk":
                        contact[b, i, j] = contact[b, j, i] = 1.0
            ...
            p, v = p1, v1
            for k in range(1, max(ROLLOUT) + 1):
                if k > 1:
                    p, v, _ = physics(p, v, pillars)
                if k in ROLLOUT:

两者的对应：
- 相同的部分：
  - 第 1 步逐样本、`log=True`，盘间接触对称写入，只认 `"disk"`；
  - 步数循环 1..10，在 `ROLLOUT = (1, 5, 10)` 时记录；
  - 用 float64 计算，最后转成 float32。
- 唯一的区别：`make_pool` 的第 2–10 步按 (盘数, 世界) 成批计算，`sim_labels` 逐个样本计算。
  - `W.physics` 对批维逐份独立运算，理论上与成批无关；
  - 下面的实测确认逐位相同。

**实测。**脚本 `evidence/makepool_equiv.py`，原始输出 `e03-makepool-equiv.txt`。做法：
- 用 ast 从 `learned_mlx.py` 摘出 `Pool`、`perturb`、`make_pool` 和它们用到的常量，原文执行；
- 按 native 测试的 ScriptedDraws 驱动 `make_pool`，让它抽到指定的精确状态。

命令与输出：

    $ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/makepool_equiv.py
    mlx imported: False
    ROLLOUT (1, 5, 10) == sandbox.ROLLOUT (1, 5, 10) True
    states: 1259 from 10 worlds; disk counts [4, 5, 6, 7, 8, 10]
    samples with a disk contact at step 1 (make_pool labels): 104
    dtypes make_pool: {'p': 'float32', 'v': 'float32', 'pil': 'float32', 'contact': 'float32', 'p1': 'float32', 'v1': 'float32', 'p5': 'float32', 'v5': 'float32', 'p10': 'float32', 'v10': 'float32'}
    dtypes reveal   : {'p': 'float32', 'v': 'float32', 'pil': 'float32', 'contact': 'float32', 'p1': 'float32', 'v1': 'float32', 'p5': 'float32', 'v5': 'float32', 'p10': 'float32', 'v10': 'float32'}
    bit-for-bit mismatches (make_pool vs sim_labels, make_pool vs CandidatePool.reveal): none
    batched (126 samples) vs one-at-a-time, 10 steps, float64: identical p True, v True
    control: states rounded to float32 before simulating -> fields differing from make_pool: ['p1', 'v1', 'p5', 'v5', 'p10', 'v10']
    control: make_pool p5 vs sim_labels p10 equal: False

最后两行是负对照：比较对微小差异也敏感，不是恒真的。

## 2. 统计实现是否就是 r1 复核写的公式

r1 复核必修 1 的原文（`reports/V9-S6-DESIGN/r1-review-sub/REPORT.md:23-27`）：

     - θ_k：只用重复 k、全部测试世界，按同一公式算出的值；s_rep = SD(θ_k)，ddof = 1。
     - se_w：5 个重复全部保留，只对测试世界做配对 bootstrap，10000 次。各臂、各重复共用同一组抽中的世界，取 θ* 的标准差。
     - se = √(s_rep²/5 + se_w²)。
     - Bonferroni 界 = θ̂ ∓ t₍₄, 1−0.025/8₎ · se，t₍₄, 0.996875₎ = 5.261。
     - 比值类门（GZ-W、GK-A、GK-F）在 log 尺度上做，再取指数。

### 2a 独立重算（不 import `analysis.py`）

| 文件 | 作用 |
|---|---|
| `indep_data.py` | 重写 `make_data`；另加 `paired_data`，含「同一重复各臂共享」的效应 |
| `indep_gates.py` | 门表照设计稿手敲；统计量写成「对重复、网络、世界合并求和后之比」，不是模块里的「各（重复, 网络）之比再平均」；t 分位数用 mpmath 的正则不完全 beta 求 |
| `author_decide.py` | 调 `analysis.decide`，并核对 `my_make_data` 与测试里的 `make_data` 逐位相同 |
| `compare_gates.py` | 逐门比对 |

命令与原始输出（`e04a`、`e04b`、`e04c`）：

    $ .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/indep_gates.py ...e04a-indep-gates.json <scratchpad>/boot
    ainerzero modules loaded by this script: []
    $ .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/author_decide.py ...e04b-author-decide.json <scratchpad>/boot
    C1 make_data() K=5: my_make_data == test make_data (bit for bit): True
    $ .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/compare_gates.py ...e04a ...e04b <scratchpad>/boot
    == C1 make_data() K=5: K=5 replicates (author 5); q_bonf indep 5.261057575066; all_pass indep True author True
       GS    point +0.166465896 | bonf [+0.151637562, +0.181294230] vs [+0.151637562, +0.181294230] | passed True/True
       GZ-W  point +0.900291433 | bonf [+0.883770146, +0.917121570] vs [+0.883770146, +0.917121570] | passed True/True
       bootstrap draws: 10000 per gate; max |indep - author| per gate {'GS': 4.996003610813204e-16, ... 'GZ-W': 8.881784197001252e-16, ...}; NaN pattern identical True
    compared 884 quantities; largest |diff| among finite values 3.197e-12; mismatches: none

覆盖的数据：
- C1–C5：`make_data` 的几种参数，包括 K = 1、2、3、5，以及 final 规模的 200/100 个世界；
- C6：带重复效应的配对数据；
- C7：墙柱盘步数为 0，用来测 NaN。

比对的量：8 门 × 7 组的 point、每个 θ_k、Bonferroni 与 95% 上下界、se、s_rep、se_w、q、point_ok、interval_ok、per_replicate_ok、passed。全部一致，最大差 3.2e-12。

### 2b t 分位数（`e05-tquantiles.txt`）

    $ PYTHONDONTWRITEBYTECODE=1 .venv/bin/python reports/V9-S6-DESIGN/pure-modules-review/evidence/tquant_check.py
    t( 4, 0.975000) analysis 2.776445  table 2.776  |diff| 4.45e-04
    t( 1, 0.995000) analysis 63.656741  table 63.657  |diff| 2.59e-04
    t( 4, 0.999500) analysis 8.610302  table 8.610  |diff| 3.02e-04
    t( 4, 0.996875) analysis 5.261058  table 5.261  |diff| 5.76e-05
    textbook: 19 values, worst |diff| 4.46e-04 (tables round to 5e-4)
    mpmath, df 1..60 x 10 levels: worst relative error of t_ppf 6.01e-12 at (df, p) = (1, 0.99999)
    mpmath, df 1..60 x 12 points (negative x included): worst |error| of t_cdf 4.44e-16 at (df, x) = (56, 2.5)
    odd df >= 5 (the odd-series loop body runs only from df = 5): [(5, 2.570581836, 2.570581836), (7, 2.364624252, 2.364624252), (9, 2.262157163, 2.262157163), (11, 2.20098516, 2.20098516)]

结论：
- 19 个教科书值都在表的舍入范围内；与 mpmath 相比，df 1–60 的相对误差不超过 6e-12。
- 公式本身正确，奇数自由度的级数也对；只是测试没有覆盖 df ≥ 5 的奇数（应修 5）。

奇数分支原文（`src/ainerzero/v9/experiments/s6/analysis.py:78-85`）：

        if df % 2 == 1:
            acc, term = 0.0, math.cos(th)
            if df > 1:
                acc = term
                for j in range(1, (df - 3) // 2 + 1):
                    term *= c2 * (2 * j) / (2 * j + 1)
                    acc += term
            return 0.5 + (th + s * acc) / math.pi if df > 1 else 0.5 + th / math.pi

### 2c 配对：世界只抽一次，各臂、各重复共用

代码（`analysis.py:221-228`）：

            Mw = _multiplicity(draws[t], n_worlds[t])                         # [n, W]
            C = Mw @ np.asarray(d["counts"], float)                           # [n, 4]
            B = Mw @ np.asarray(d["eb"], float)                               # [n]
            arm_stats[t] = {}
            for arm in GATE_ARMS:
                S = np.einsum("bw,knwc->bknc", Mw, np.asarray(d["sums"][arm], float))   # [n, K, N, 4]
                per = _per_rep_net(S, C[:, None, None, :], B[:, None, None])           # [n, K, N]
                arm_stats[t][arm] = {k: v.mean((1, 2)) for k, v in per.items()}

- 每个测试集只算一次 `Mw`，对所有臂、所有 K 个重复使用同一份。
- 我按「共用」独立重算，每一次抽样都与作者一致，差不超过 1.8e-15（2a）。
- 这个比对能分辨不同的设计：在 C6 上，若改为不共用，se_w 明显不同。

      sensitivity (se_w if the worlds were not shared): {'per-arm draws (unpaired)': {'GS': 0.027773349451196874, 'GZ-W': 0.03800690888010393}, 'per-replicate draws (nested)': {'GS': 0.003285714984035623, 'GZ-W': 0.0025694839376077232}}; shared (design): GS 0.0062876524126845934, GZ-W 0.0027097843472514488

- 「世界不共用」的变异被测试杀死：作者 A4（各臂分别抽）和我的 Q4（各重复分别抽）都死了。
- 但「θ_k 按重复配对」这一层没有被守住（Q2，见必修 1）。

### 2d K = 1、K = 2 的退化（`e11-edge-probe.txt`）

    K=1: q 2.7344 df None s_rep 0.0 | GS per_replicate [0.1655029267840425] point 0.165503 | passed ['GS', 'GT', 'GZ-D', 'GZ-W', 'GK-A', 'GK-F', 'GP', 'GX']
    K=2: q 101.8559 df 1 s_rep 0.006743226407229735 | GS per_replicate [0.16421137908571326, 0.17374774132496995] point 0.168980 | passed []
    K=0: ValueError no replicates

- K = 1：s_rep 取 0，q 用正态分位数，与 `DESIGN-r2.md:252` 一致。
- K = 2：t(1) 分位数是 101.86，所有门都不过（见「不阻塞」第 2 条）。
- 独立重算对 K = 1、2 也逐门一致（2a 中的 C3、C4）。

## 3. 门表与设计稿逐条对照

设计稿：`DESIGN-r2.md:218-227`。r1 的 `DESIGN-r1.md:191-198` 判据列与 r2 相同，只有 GT 的摸底值不同。代码：`analysis.py:49-64`。

| 门 | 设计稿判据 | `GATES` | 测试集 | 一致 |
|---|---|---|---|---|
| GS | D(E) − D(R) ≥ +0.03，下界 > 0，每个重复 ≥ +0.03 | diff E−R，`(">=", 0.03)`，`("lower", ">", 0.0)`，`per_replicate` 0.03 | main6 | 是 |
| GT | [D(E) − D(R)] − 0.5[D(T) − D(R)] 下界 > 0，无点值判据 | half_gain，`(a−b) − 0.5(c−b)`，point None，`("lower", ">", 0.0)` | main6 | 是 |
| GZ-D | D(E) − D(Z) ≥ −0.02，下界 > −0.04 | `(">=", -0.02)`，`("lower", ">", -0.04)` | main6 | 是 |
| GZ-W | 墙柱 E/Z ≤ 0.95，上界 < 1.0（严格） | ratio，`("<=", 0.95)`，`("upper", "<", 1.0)` | main6 | 是 |
| GK-A | 全部盘步 E/R ≤ 1.10，上界 ≤ 1.20（不严格） | ratio，`("<=", 1.10)`，`("upper", "<=", 1.20)` | main6 | 是 |
| GK-F | 自由 E/Z ≤ 1.10，上界 ≤ 1.20 | ratio，`("<=", 1.10)`，`("upper", "<=", 1.20)` | main6 | 是 |
| GP | D(P) − D(R) ≥ +0.03，下界 > 0 | `(">=", 0.03)`，`("lower", ">", 0.0)` | main6 | 是 |
| GX | D(E) − D(R) ≥ +0.02，下界 > 0 | `(">=", 0.02)`，`("lower", ">", 0.0)` | extrap10 | 是 |

其余对照：
- 「上界、下界一律用 Bonferroni 区间」：`interval_ok` 用的就是 Bonferroni 界（`analysis.py:264`、`:267`）：

      lo, hi, parts = interval(spec, x, tk, boot[g], p_bonf)
      interval_ok = _holds(op, lo if end == "lower" else hi, v)

- m = 8，p = 1 − 0.05/16（`:258`）。
- NaN 判不过（`_holds` 先查 `isfinite`）。
- 我手敲的门表与独立实现 8 门全部一致（2a）。

## 4. 测试能否抓错：我的 13 个变异

脚本 `evidence/mutate_review.sh`，原始输出 `e06-my-mutations.txt`。
- 隔离副本：`git archive HEAD src tests pyproject.toml` 解到 scratchpad；HEAD `4cdbee9` 已含全部被审文件，副本与工作树逐字节相同。
- 确认从副本加载：`PYTHONPATH=<副本>/src`，并加了 `test_zz_review_origin.py`，在 pytest 进程内断言 `sandbox`、`analysis`、`world` 都从副本加载。所以基线是 58 项（57 + 1）。
- 每个锚点要求恰好出现一次。

| 变异 | 结果 | 判断 |
|---|---|---|
| R1 `_simulate` 直接写 `_outcomes` | 杀死（`test_only_reveal_reaches_the_labeller`） | — |
| R1b `reveal` 按组边模拟边存 | **存活** | 非等价：后一组失败时，前一组的标签留在进程里（`e07`）→ 应修 3 |
| R2 整个盘数组都模拟，只取选中的行 | 杀死 | — |
| R3 状态按 float32 精度存储 | 杀死（3 项） | — |
| R4 墙、柱接触也记进接触矩阵 | **存活**（纯 NumPy） | 非等价：约 12% 的状态标签变化；native 测试应能抓到（推断）→ 应修 4 |
| R5 构造时直接用 `sim_labels` 预先模拟全部候选 | **存活** | 非等价：全部标签在挑选前就存在（`e07`）→ 必修 2 |
| Q1 门区间用 95% 水平 | **存活** | 非等价，能翻转 GZ-W 的判定 → 必修 1 |
| Q2 θ_k 不按重复配对 | **存活** | 非等价，能翻转 GZ-D、GZ-W 的判定 → 必修 1 |
| Q3 比值门点值取几何平均 | **存活** | 非等价，C6 上 GZ-W 0.9015290 → 0.9017554 → 必修 1 |
| Q4 世界按重复分别抽（嵌套） | 杀死（`test_bootstrap_draws_equal_stats_on_the_drawn_worlds`） | — |
| Q5 t_cdf 奇数级数用了偶数的因子 | **存活** | 非等价，但 K = 5 时不起作用 → 应修 5 |
| Q6 s_rep 用 ddof 0 | 杀死（2 项） | — |
| X1 `select` 经别名读已揭示样本的标签 | **存活** | 静态检查的漏洞 → 应修 6 |
| X2 模块级 `W.physics` 别名在 `closest_pair` 里调用 | **存活** | 同时绕过静态检查和封印（`e07`）→ 应修 6 |

`e06` 原始输出节选：

    == baseline:
    58 passed in 2.23s
    == R1b reveal stores each disk-count group's outcomes as it simulates it (a later failing group leaves the earlier ones)
    58 passed in 1.89s
    == R5 the constructor simulates every candidate straight through sim_labels and keeps the result (not via the labeller)
    58 passed in 2.35s
    == Q1 gate intervals at the 95% level (levels dict unchanged)
    58 passed in 1.85s
    == Q2 theta_k not paired by replicate: R and Z use replicate k+1 (point value unchanged)
    58 passed in 1.84s
    == Q4 world bootstrap nested: replicate k gets its own draw (shared across arms only)
    FAILED tests/v9/experiments/test_s6_analysis.py::test_bootstrap_draws_equal_stats_on_the_drawn_worlds
    1 failed, 57 passed in 1.86s
    == restored:
    58 passed in 1.86s

存活变异的非等价证据。

`e08-survivors-analysis.txt`（Q1–Q5，与原模块比较 `decide()`）：

    flip: make_data(seed=7, noise=0.15) with E wall-pillar factor 0.93: gates whose decision changes ['GZ-W']
    flip GZ-W  point +0.932883 -> +0.932883 | s_rep 0.01936 -> 0.01936 | bonferroni [+0.86933, +1.00108] -> [+0.89879, +0.96828] | passed False -> True
    flip: paired_data(seed=3, rep_sd=0.03): gates whose decision changes ['GZ-D', 'GZ-W']
    flip GZ-W  point +0.899336 -> +0.899336 | s_rep 0.00868 -> 0.06424 | bonferroni [+0.87766, +0.92154] -> [+0.77272, +1.04670] | passed True -> False
       C6: GZ-W 0.9015290 -> 0.9017554; GK-A 0.9820183 -> 0.9821524; GK-F 1.0159208 -> 1.0160096
       t_ppf(0.996875, 5): original 4.525716  mutant 5.947091
       K=5 (the registered run): decide() identical: True

`e07-survivors-sandbox.txt`（R1b、R4、R5、X2）：

    R4 pure test states [42, 43, 0] -> wall/pillar contacts at step 1: [[], [], []]
    R4 native test states: 156; with a wall/pillar contact at step 1: 27 (make_pool marks disk contacts only, so the native comparison would differ on these)
    R4 candidate-like states (20 worlds x 300 steps): 726/6000 = 0.121 have a wall/pillar contact at step 1, i.e. would get a wrong contact label under R4
    R1b R1b          : after reveal([0, 1, 4]) failed on n=6 -> revealed [], log [], outcome store keys [0, 1]
    X2 W.physics inside the seal: SealBreach: a pick rule reached ainerzero.v9.experiments.s4.world.physics while selection was sealed
    X2 the saved alias inside the seal: returned an outcome, v1[0, 0] = [-1.0210034240029628, -0.9148686762162527]
    R5 R5           : simulator calls during construction + states() + remaining(): 80; labeller calls 0; _outcomes []; labels of id 5 held before its reveal equal what reveal returns: True

相关测试的原文：
- `tests/v9/experiments/test_s6_sandbox.py:93-94`：

      assert spy.calls == []
      assert cp._outcomes == {}

- `tests/v9/experiments/test_s6_analysis.py:206`：

      assert res["m"] == 8 and res["replicates"] == 5 and res["levels"]["bonferroni"] == pytest.approx(1 - 0.025 / 8)

- `tests/v9/experiments/test_s6_cells_static.py:42-44`：

      pool_calls = {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "cp"}
      assert pool_calls == {"states", "remaining"}

## 5. 作者变异日志是否属实

**原样复跑** `reports/V9-S6-PHASE1/impl-evidence/mutate_pure.sh`（sha256 fa272563…，未作改动），原始输出 `e09-author-mutations-rerun.txt`。去掉耗时后逐行比对：

    $ diff <(sed -E 's/ in [0-9.]+s//' reports/V9-S6-PHASE1/impl-evidence/mutate_pure.log | grep '^==') <(sed -E 's/ in [0-9.]+s//' .../e09-author-mutations-rerun.txt | grep '^==')
    (no difference: same 27 lines, timings stripped)

- 结果：基线 57 项；S1–S12、A1–A11、C1–C2 共 25 个变异全部被杀死，失败项数与日志一致；还原后 57 项。日志属实。

**杀死作者变异的具体测试**（`author_killers.sh`，原始输出 `e10`）：

    == A1 Bonferroni with m = 6
    FAILED tests/v9/experiments/test_s6_analysis.py::test_decide_on_synthetic_effects
    == A1' m = 6 in the bound only (levels dict keeps M)
    30 passed in 1.24s
    == A11 world draws not shared: extrap drawn first
    FAILED tests/v9/experiments/test_s6_analysis.py::test_world_draws_order_and_reproducibility

见应修 7。

## 附：`evidence/`

| 文件 | 内容 |
|---|---|
| `e01-live-tests.txt` | 被审文件的 SHA、与 HEAD 的 diff，三个测试文件在实盘逐项运行（57 passed：24 + 29 + 4） |
| `leak_probe.py`、`e02` | 泄漏探针 L1–L12 |
| `makepool_equiv.py`、`e03` | `sim_labels`、`reveal` 与 `make_pool` 原文的逐位比较 |
| `indep_data.py`、`indep_gates.py`、`author_decide.py`、`compare_gates.py`、`e04a/b/c`（txt 与 json） | 独立重算与逐门比对 |
| `tquant_check.py`、`e05` | t 分位数 |
| `mutate_review.sh`、`e06` | 我的 13 个变异 |
| `survivor_probe_sandbox.py`、`e07`；`survivor_probe_analysis.py`、`e08` | 存活变异是否等价 |
| `e09`、`e09b` | 作者变异的复跑与逐行比对 |
| `author_killers.sh`、`e10` | 哪些测试杀死作者的 A1、A4、A7、A11 |
| `edge_probe.py`、`e11` | K = 0、1、2，无 G 臂，n = 1 |
| `make_citations.sh`、`citations.txt` | 引文原始输出 C1–C30 |