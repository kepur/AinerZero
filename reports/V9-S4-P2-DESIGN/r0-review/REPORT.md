# P213 非作者复核：S4 第二阶段设计稿 r0（接触门控 L-int-g）

- 复核者：`claude-s4p2rev-1111a`（二级，非作者；设计稿作者是一级 claude）。2026-11-11。
- 复核对象：`reports/V9-S4-P2-DESIGN/DESIGN-r0.md`。卡片写的是提交 `ff1a162`；工作区 HEAD（`5698eef`）的版本比它多 15 行：负对照判据的修改和「复核前补记」。本复核以 HEAD 版为准（sha256 `46cf07c1…6369189`，见 `evidence/citations.txt` 第一块）。
- 只写了本目录。没有改源码、测试、设计稿和已有报告；没写 `artifacts/`；没生成 `s4p1-*`、`s4p2-*` 世界。代用模型只用 `s4x-p2a` 的世界；随机门的随机数用种子标签 `s4x-p2rev`，这个标签下没有生成任何世界。MLX 命令一律经 `hold_lock.py` 拿 `artifacts/locks/m0-worker.lock`。复跑摸底脚本时加 `-B`，没往 `tier1-explore/__pycache__` 写字节码。
- 复核者与作者同属 Claude 模型（设计稿 §9 已列为风险）。

## 结论

**打回：1 项必修、4 项应修、4 项建议。** 问题值得问；七个门合起来挡得住卡片要求的三个代用模型；摸底完全可复现；设计稿的数字 123 个里 122 个对得上。打回只因为一处解读：负对照挡不住「知道什么时候碰、不知道怎样碰」的代用模型，设计稿据此把重认上的收益归给「学到的交互」，证据不够。修起来不大（加一个对照臂或改写几句）。

**卡片要求的五项，一句话：**
1. 问题值得问，范围写清了。§9 第二条「不是把 E-P 拼回来」成立；但「收益来自学到的响应」只对一小截成立（见 M1）。前提要改成「没有盘间重叠」，「持平」要限定在这个滤波器的重认和校准上（§1）。
2. 门永远开、永远关、2% 随机门都过不了：各被七个门中的六个挡住（门永远开只过 GD，另两个只过 GN）。额外的 SCATTER 只被 GD 稳稳挡住：GA、GC、GK1、GN 只差 0.002–0.012，GX 只差 C 的下界（§2）。
3. 没有找到泄漏。一步覆盖率的步类、重新出现时取 a 步轨迹、门只读成员状态、bootstrap 与 Bonferroni、种子平均方式都与设计一致，也没有选择偏差（§3）。
4. 摸底可复现：两份摘要逐行一致；前 3 个世界复跑 63 格逐字段一致（§4）。
5. 数字：123 个核对，122 个对上；对不上的是一个描述性的训练耗时（§5）。

**必修**

- **M1 负对照与「收益来自学到的交互」。** SCATTER（几何门，门开时把 E-B 的速度方向均匀随机转一个角，速率不变）没有任何碰撞知识，D = −0.144，却拿到 C 0.738，GK2 过，GA、GC、GK1、GN 只差 0.002–0.012，外推上 GX 只差 C 的下界。有碰撞的事件上 L-int-g 只比它多 +0.046 [+0.008, +0.085]。登记负对照 L-ind-geo 只排除了「门开但预测照旧」，排除不了「门开、把不确定性放宽」。所以 `DESIGN-r0.md:85-86` 的「起作用的是学到的碰撞响应」「收益来自学到的交互，不是门本身」，以及 `:145` 负对照「否则说明门本身就能带来收益」的推理，都不成立。二选一：
  - (a) **推荐。** 登记一个「知道什么时候、不知道怎样碰」的对照臂（门同 L-int-g 或几何门；门开时 E-B 的位置、速度方向均匀随机、速率不变），加一条判据：有碰撞的事件上 L-int-g − 该臂 ≥ 0，Bonferroni 下界 > 0（m 相应加 1）。不过时，只能说「门控混合模型能补回重认」，不能把收益归给学到的响应。登记运行每个世界 27 个跟踪格（9 个臂 × 3 个种子），多 3 格，耗时约 +11%。
  - (b) 不加臂，就删去上述三处归因，把 GA、GC、GK 的结论写成「门控混合模型的重认与校准」。学到的响应好不好，只由 GD（以及 GN 的不误伤）回答，并在 §9 写明。

**应修**

- **S1 §9 的前提。** 「门关时 E-P 与 E-B 本来就相同（没有盘间接触时两者一样）」应为「没有盘间重叠时」。生成器对重叠、正在分开的一对也做推开，日志里却没有接触（§1b，`evidence/physics/ep_vs_eb_overlap.txt`）。
- **S2 「持平」的范围。** C 会饱和，L-int-g 的 D 只有 0.85。重认和校准上与 E-P 持平，说明的是剩下的误差在这个滤波器里不影响重认和校准，不说明学到的响应接近物理。§1 读法和 §9 结论句要补上这个限定。还要写明 GK1 全部步主要由门关的约 98% 盘步决定（§1b 第 2、3 条）。
- **S3 §5「谁过不了」与门槛理由。** 按本复核的代用模型结果补齐（§2 表）：
  - 门永远开挡在 GN、GA、GC、GK1、GK2、GX，GC 对它并不稳，GX 只靠差值半边；
  - 门永远关、随机门都只过 GN；
  - GN 会被什么都不做的 E-B 通过（非劣门的本性）；
  - GA、GC、GK1 碰撞步的门槛正落在 SCATTER 之上 0.002–0.012，GX 也只靠 C 的下界挡住它。
- **S4 数字与表述。**
  - `DESIGN-r0.md:84` 的「每步 0.033 秒」与日志 0.0368 秒不符，「2.6 倍」无出处；
  - `:59` 一行的斜杠与列头含义冲突；
  - `:15` 的 0.60 / 0.86 要注明是没有碰撞的事件；
  - `:196` 的单世界耗时（9 个臂，主评测 9 秒、外推 30 秒）找不到对应的摸底轮次（§5）。

**建议**

- **R1** 负对照用未校正的 95% 上界（`analysis_p2.py:273`），对「上界 < 0.5」是宽松的一侧。改用 Bonferroni 上界，或写明理由（§3d）。
- **R2** 把随机门（RAND）登记为描述量：它直接证明「门的时机不可替代」（C 0.063）。成本是每个世界 3 格。
- **R3** `DESIGN-r0.md:119`「门控代码不得调用世界模块的物理」改为「门的判定不调用物理；门控模型只调用 E-B（即 `world.physics(disks=False)`），不调用 E-P」，与测试一致。§0 或 §9 写明 E-B 就是生成器同一函数去掉盘间碰撞（§1a、§3c）。
- **R4** 摸底点估计对滤波器随机数敏感：换成登记种子，L-int-g 的 GN 从 +0.018 变为 +0.003（§2 第 5 条）。§5 的「摸底值」要注明种子标签。另外，探针的耗时最好在机器空闲时测，评测预留按它的 6 倍算（§5 第 4 条）。

**复核者自己没做的：**
- 没有核对一期 L-int 的每步训练耗时（「2.6 倍」）。
- 没有审运行器 `run_s4p2.py`、`verify_*_p2.py`、`make_prereg.py` 和二期测试的实现：那是实现复核（P214）的范围。只读了 `gated.py`、`analysis_p2.py`、`worker_p2.py` 里与设计定义有关的部分。
- 代用模型只在 `s4x-p2a` 的 40 + 20 个世界上跑过一次。SCATTER 离门槛的余量很小，换世界会怎样只能推断。

---

## 1. 问题值不值得问

结论：**值得问，范围写清了。§9 第二条「不是把 E-P 拼回来」成立；但它的一个前提写得不精确，「收益来自学到的响应」只部分成立，结论句要收窄。**

**1a 结论范围。** `DESIGN-r0.md:30`：

> 结论的范围：单体运动（直线、撞墙、撞柱）用的是手写规则，属于声明的真值输入（§9）；学到的只有「什么时候碰」和「碰了以后怎样」。

§9（`DESIGN-r0.md:216-220`）把墙柱规则与几何列为比一期多出的真值输入。范围是清楚的。可以再写得更直白一点：E-B 不是另写的一套规则，而是生成器的同一个函数去掉盘间碰撞（`models.py:22`：`    p, v, _ = W.physics(P, V, pillars, disks=False)`）。门关着的约 98% 盘步上，L-int-g 用的就是生成器的代码。建议在 §0 或 §9 写明这一点，读者才不会把「手写规则」理解成一个独立的近似模型。

**1b「L-int-g 与 E-P 持平」是不是把 E-P 拼回来。** `DESIGN-r0.md:221-225`：

> - **L-int-g 与 E-P 持平，可能被读成「门控只是把 E-P 拼回来」。** 不是：
>   - 门开时的预测来自学习模型，负对照 L-ind-geo 说明换成不懂交互的模型就没有收益；
>   - 门关时 E-P 与 E-B 本来就相同（没有盘间接触时两者一样）。
>
>   所以这一阶段说明的是：一期学到的碰撞响应已经够用，一期的代价全部来自它在不该用的地方被用上。

「不是把 E-P 拼回来」这一层成立：门开时用的确实不是 E-P，而是学习模型。§2 的代用模型还说明，门的时机替代不了：同样约 2% 的比例随机打开，就没有收益（RAND，C 0.063）。

但「换成不懂交互的模型就没有收益」只对 L-ind 这种门开时仍给自信直行预测的模型成立。§2 的 SCATTER 门开时也不懂交互，只把速度方向随机化、放宽集合，就拿到 C 0.738，L-int-g 是 0.917。所以 L-int-g 的收益大部分来自「在接触时刻放宽不确定性」，学到的响应在这之上只多出有碰撞事件 +0.046 和近失时不误伤。这一点是必修 M1。

此外三处需要改：

1. **前提不精确。** 「没有盘间接触时两者一样」不对，应是「没有盘间重叠时两者一样」。生成器对所有重叠的盘对都做位置推开，不管是否相向（`world.py:105-106`、`:112-113`）：

   > `            ok = upper & (dist < 2 * RADIUS) & (dist > 1e-9)`
   > `            approach = ok & (rel > 0)`
   > `            push = np.where(ok, 2 * RADIUS - dist, 0.0)[..., None] * nrm / 2`
   > `            p = p - push.sum(2) + push.sum(1)`

   接触日志只记速度反向的子步（`world.py:64`：`    normal velocity was reversed.`）。所以重叠但正在分开的一对，日志里没有接触，E-P 与 E-B 的位置却不同。`evidence/physics/ep_vs_eb_overlap.py` 的原始输出：

   ```
   logged contacts: []
   E-P positions: [[4.94625, 5.0], [5.55375, 5.0]] velocities: [[-0.05, 0.0], [0.05, 0.0]]
   E-B positions: [[4.995, 5.0], [5.505, 5.0]] velocities: [[-0.05, 0.0], [0.05, 0.0]]
   positions identical: False  velocities identical: True
   ```

   在真值世界里重叠很少；但滤波器的成员状态是带噪的估计，两条轨迹的成员互相重叠并不少见。这不影响论证的方向，但前提要写对。

2. **「持平」不等于「学到的响应等于物理」。** C 会饱和。一期设计 `DESIGN-r3.md:204` 写过：

   > C 会饱和，只懂一半碰撞的代用模型也有 0.72

   L-int-g 的 C 是 0.96（摸底；登记种子下 0.917），但从精确真值出发 D 只有 0.85，即碰撞步上 E-B 速度误差还剩 15%。所以重认和校准上的持平说明的是：剩下的误差在这个滤波器里不影响重认和校准。它不说明学到的响应接近物理；后者由 GD 回答。§1 读法（`DESIGN-r0.md:85`「结果与 E-P 在三类事件和校准上都持平」）和 §9 的结论句（「一期学到的碰撞响应已经够用」）建议都补上「对这个滤波器的重认和校准够用」。「一期的代价全部来自……」的「全部」也只在这个意义上成立：GN 的非劣界是 0.03。

3. **GK1「全部步」的信息量主要来自 E-B 部分。** 门开的盘步只占约 2%，其余是生成器物理加登记噪声。所以 GK1 全部步接近 E-P 几乎是构造决定的。真正检验学习部分的是碰撞步那一半，以及 GK2 的有碰撞那一半。§2 中 `OFF`（等于 E-B）在 GK1 全部步上也只有 0.83，没过；可见 E-B 在碰撞后恢复的那几步也会拉低全部步的覆盖率，这一项并非毫无鉴别力。建议在 §5 读法里写明各半边各自检验什么。

**1c 值不值得问。** 答案在摸底里已经大致看到了（60 个世界，三类事件、两种覆盖率都与 E-P 持平）。所以二期主要是一次在新世界上、带预登记门槛的确认，外加第一次对校准（架构 S4 第三条）下判定。用户选的是「补短板小二期」，这个规模与问题匹配。确认的结论范围窄（单体运动是生成器代码），但干净：它回答「一期学到的交互能不能只在该用的地方用，并且不带来校准损失」。值得问。

## 2. 门能不能被简单的代用模型钻空子（§5）

**做法。** `evidence/surrogates/track_surrogates.py` 用登记的二期评测代码 `analysis_p2.world_record`（同一滤波器、同一「base」滤波器种子、同一校准钩子、同一动力学和）在 `s4x-p2a` 的主评测 0–39 号（6 盘）和外推 1000–1019 号（10 盘）上跟踪下列臂，每臂 3 个种子：

| 臂 | 门 | 门开时 | 角色 |
|---|---|---|---|
| E-CV、E-B、E-P | — | — | 参照（`models.HAND_MODELS`） |
| L-int-g | L-int 接触头，p = 0.5 | L-int | 登记主臂（`gated.gated_model`），作对照 |
| L-ind-geo | 几何 | L-ind | 登记负对照（`decide()` 需要它） |
| **L-int（门永远开）** | 永远开 | L-int | 卡片要求 1：就是一期 L-int，按 worker 的写法 `learned_mlx.as_process_model` |
| **OFF（门永远关）** | 永远关 | — | 卡片要求 2：走门控代码，门恒为假；应与 E-B 逐位相同 |
| **RAND（随机门）** | 每个成员、每个盘、每一步独立以 2.0% 打开 | L-int | 卡片要求 3：比例取设计稿的门打开比例 2.0% |
| L-ind-g（额外） | L-int 接触头，p = 0.5 | L-ind | 「知道什么时候」但模型不懂交互；补登记负对照（几何门）的另一半 |
| **SCATTER（额外）** | 几何 | E-B 的位置；E-B 的速度转一个均匀随机角（速率不变） | 「知道什么时候碰，不知道怎样碰」，只把集合放宽 |

代用模型的单步函数逐行照抄 `gated.gated_model`，只换门的判定和门开时的输出。RAND、SCATTER 的随机数各用自己的生成器，按（世界、种子、用途）以标签 `s4x-p2rev` 派生，不碰滤波器的随机数。

判门用 `evidence/surrogates/gates_surrogates.py`：对每个臂调用与 `analysis_p2.gate_stats` 相同的统计（只把主臂名换成该臂），再交给登记的 `analysis_p2.decide`。脚本先断言换名函数在 L-int-g 上与 `gate_stats` 的输出逐字节相同。Bonferroni m = 11，bootstrap 10000 次，种子 20261111，都是登记值。

命令（MLX 部分各自经锁）：

```
sh reports/V9-S4-P2-DESIGN/r0-review/evidence/surrogates/run_surrogates.sh main     # 40 个世界，日志 run-main.log
sh reports/V9-S4-P2-DESIGN/r0-review/evidence/surrogates/run_surrogates.sh extrap   # 20 个世界，日志 run-extrap.log
.venv/bin/python -I -B $S/gates_surrogates.py $S/records-main.json $S/records-extrap.json $S/gates.json > $S/gates.txt
.venv/bin/python -I -B $S/table_surrogates.py $S/gates.json > $S/table.md
```

**结果**（`evidence/surrogates/table.md` 原样粘贴；完整数值和判门在 `gates.txt`）：

main 40 worlds, extrap 20 worlds; OFF identical to E-B in every cell: True

| 臂 | 门打开比例（主评测） | GN | GA | GC | GK1 | GK2 | GD | GX |
|---|---|---|---|---|---|---|---|---|
| L-int-g | 0.0145 | **过** | **过** | **过** | **过** | **过** | **过** | **过** |
| L-int | — | 不过 | 不过 | 不过 | 不过 | 不过 | **过** | 不过 |
| OFF | 0.0000 | **过** | 不过 | 不过 | 不过 | 不过 | 不过 | 不过 |
| RAND | 0.0199 | **过** | 不过 | 不过 | 不过 | 不过 | 不过 | 不过 |
| L-ind-g | 0.0541 | **过** | 不过 | 不过 | 不过 | 不过 | 不过 | 不过 |
| SCATTER | 0.0228 | 不过 | 不过 | 不过 | 不过 | **过** | 不过 | 不过 |
| L-ind-geo | 0.0438 | **过** | 不过 | 不过 | 不过 | 不过 | 不过 | 不过 |
| E-B | — | **过** | 不过 | 不过 | 不过 | 不过 | 不过 | 不过 |
| E-P | — | **过** | **过** | **过** | **过** | **过** | 不过 | **过** |

数值：点估计 [Bonferroni m = 11 下界, 上界]（GN、GA、GX 差值是相对 E-B）

| 统计量 | L-int-g | L-int | OFF | RAND | L-ind-g | SCATTER | L-ind-geo | E-B | E-P |
|---|---|---|---|---|---|---|---|---|---|
| GN | +0.003 [-0.020, +0.026] | -0.052 [-0.088, -0.017] | +0.000 [+0.000, +0.000] | +0.009 [-0.006, +0.024] | -0.002 [-0.012, +0.008] | -0.018 [-0.039, +0.004] | -0.003 [-0.013, +0.007] | +0.000 [+0.000, +0.000] | +0.009 [-0.015, +0.034] |
| GA | +0.054 [+0.022, +0.085] | -0.003 [-0.044, +0.038] | +0.000 [+0.000, +0.000] | +0.011 [-0.003, +0.026] | +0.003 [-0.008, +0.014] | +0.028 [-0.001, +0.058] | -0.000 [-0.011, +0.010] | +0.000 [+0.000, +0.000] | +0.064 [+0.029, +0.099] |
| GC | +0.917 [+0.742, +1.122] | +0.665 [+0.368, +0.984] | +0.000 [+0.000, +0.000] | +0.063 [-0.034, +0.176] | +0.078 [-0.045, +0.259] | +0.738 [+0.502, +0.992] | +0.039 [-0.071, +0.183] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |
| GK1 全部步 | +0.903 [+0.893, +0.913] | +0.745 [+0.725, +0.765] | +0.830 [+0.810, +0.850] | +0.853 [+0.836, +0.869] | +0.827 [+0.807, +0.847] | +0.900 [+0.890, +0.908] | +0.828 [+0.808, +0.847] | +0.830 [+0.810, +0.850] | +0.907 [+0.897, +0.916] |
| GK1 碰撞步 | +0.892 [+0.821, +0.949] | +0.697 [+0.617, +0.785] | +0.592 [+0.509, +0.678] | +0.658 [+0.576, +0.739] | +0.590 [+0.515, +0.670] | +0.840 [+0.787, +0.893] | +0.592 [+0.518, +0.673] | +0.592 [+0.509, +0.678] | +0.907 [+0.841, +0.959] |
| GK2 没有碰撞 | +0.910 [+0.876, +0.941] | +0.591 [+0.548, +0.637] | +0.856 [+0.808, +0.896] | +0.876 [+0.832, +0.914] | +0.852 [+0.806, +0.891] | +0.897 [+0.861, +0.928] | +0.855 [+0.811, +0.892] | +0.856 [+0.808, +0.896] | +0.913 [+0.878, +0.944] |
| GK2 有碰撞 | +0.818 [+0.745, +0.880] | +0.538 [+0.431, +0.642] | +0.474 [+0.399, +0.553] | +0.511 [+0.438, +0.590] | +0.459 [+0.386, +0.536] | +0.752 [+0.686, +0.816] | +0.459 [+0.387, +0.534] | +0.474 [+0.399, +0.553] | +0.830 [+0.759, +0.895] |
| GD D | +0.852 [+0.810, +0.884] | +0.855 [+0.811, +0.887] | +0.000 [-0.000, +0.000] | +0.012 [+0.005, +0.019] | +0.003 [-0.009, +0.012] | -0.144 [-0.231, -0.061] | +0.000 [-0.012, +0.011] | +0.000 [+0.000, +0.000] | — |
| GD HF 比 | +0.026 [+0.018, +0.036] | +0.075 [+0.061, +0.092] | +0.000 [+0.000, +0.000] | +0.001 [+0.001, +0.002] | +0.003 [+0.002, +0.005] | +0.001 [+0.000, +0.004] | +0.000 [+0.000, +0.001] | +0.000 [+0.000, +0.000] | — |
| GX 全部−E-B | +0.089 [+0.048, +0.135] | +0.027 [-0.031, +0.077] | +0.000 [+0.000, +0.000] | +0.018 [+0.003, +0.032] | +0.005 [-0.012, +0.022] | +0.045 [+0.004, +0.082] | +0.008 [-0.009, +0.024] | +0.000 [+0.000, +0.000] | +0.084 [+0.046, +0.123] |
| GX C | +1.025 [+0.785, +1.258] | +0.690 [+0.443, +0.918] | +0.000 [+0.000, +0.000] | +0.069 [-0.132, +0.187] | +0.064 [-0.197, +0.241] | +0.645 [+0.287, +0.888] | +0.049 [-0.123, +0.203] | +0.000 [+0.000, +0.000] | +1.000 [+1.000, +1.000] |

配对差（L-int-g − X，主评测，95% 按世界 bootstrap，m = 1）

| X | 有碰撞 | 没有碰撞 | 全部 |
|---|---|---|---|
| SCATTER | +0.046 [+0.008, +0.085] | +0.021 [+0.007, +0.035] | +0.026 [+0.012, +0.041] |
| RAND | +0.220 [+0.157, +0.284] | -0.006 [-0.021, +0.008] | +0.044 [+0.023, +0.064] |
| L-int | +0.065 [+0.018, +0.111] | +0.055 [+0.035, +0.075] | +0.058 [+0.037, +0.078] |
| L-ind-geo | +0.226 [+0.156, +0.296] | +0.006 [-0.009, +0.021] | +0.055 [+0.033, +0.076] |

E-P 的 GD 一格「不过」只因 D(E-P) 按定义为 1、没有计算动力学和，不是结果。

**读法：**

1. **卡片要求的三个代用模型都过不了，每个都被七个门中的六个挡住。**
   - 门永远开（一期 L-int）：挡在 GN、GA、GC、GK1、GK2、GX，只过 GD。与设计稿「谁过不了」一列一致。它的 C 在登记种子下是 0.665，比摸底种子的 0.72 更低。但两者都离 0.75 不远，GC 单独并不能稳定挡住它，真正稳的是 GN（−0.052）、GK1、GK2。
   - 门永远关（OFF）：与 E-B 的轨迹分配在全部格上逐位相同（门控代码「门关等于 E-B」的约束在真实跟踪里成立）。只过 GN。
   - 随机门（RAND，2.0%，比 L-int-g 在主评测上的 1.45% 还多开一些）：只过 GN。C 只有 0.063，GD 的 D 只有 0.012。**门的时机不可替代**：学到的模型用在同样多、但随机的盘步上，没有收益。
   - 「GN 被什么都不做的模型通过」是非劣门的本性，不是漏洞：GN 只挡一期那种 −0.05 的代价，单独不说明任何收益。建议在 §5 写明。
2. **L-ind-g（接触头当门、L-ind 预测）与登记负对照 L-ind-geo 一样什么都不过**（除 GN）。负对照换成学到的门也成立。
3. **SCATTER（知道什么时候碰、不知道怎样碰）是这组门的薄弱处。** 它门开时只把速度方向随机转一下，没有任何碰撞知识，D 是负的（−0.144）。但在重认和校准上它拿到了 L-int-g 收益的大部分：
   - C 0.738（L-int-g 0.917），GA +0.028（门槛 0.03），GK1 碰撞步 0.840（门槛 0.85），GN −0.018（门槛 −0.01）。四个门都只差 0.002–0.012；GK2 已经过了。
   - 有碰撞的事件上，L-int-g 只比它多 +0.046 [+0.008, +0.085]（95%）。
   - 所以 40 个世界上它没过，靠的是这几个门槛刚好落在它上面一点。final 换 200 个新世界，GA、GC、GK1 中任何一个被它过掉都不奇怪；外推上的 GX 也挡不稳它（第 7 条）。**唯一稳稳挡住它的是 GD。**
   - 这不会让整个实验被钻空子：L-int-g 要全过七个门，GD 必在其中。但它推翻了设计稿对负对照的解读。`DESIGN-r0.md:85-86`：

     > - **门控把学习模型限制在它擅长的地方。** 只有约 2% 的盘步用到它，其余都是精确的 E-B。结果与 E-P 在三类事件和校准上都持平。门限从 0.3 到 0.7 几乎不变；换成几何规则当门也一样。所以起作用的是学到的碰撞响应，接触头只是一个够用的「什么时候」。
     > - **负对照成立。** 门打开但换成 L-ind 时，C 只有 0.10–0.11。收益来自学到的交互，不是门本身。

     L-ind 在门开时给的仍是一个自信的「直行」预测，集合不放宽，所以 C 接近 0。它只排除了「门开但预测照旧」，没有排除「门开、预测不知道、但把不确定性放宽」。后者在重认上就能补回 E-B 到 E-P 差距的约 3/4。「收益来自学到的交互」只对 SCATTER 之上的那一截成立：有碰撞的事件上 +0.046，以及没有碰撞的事件上不误伤（L-int-g − SCATTER = +0.021 [+0.007, +0.035]，95%。原因我没有单独验证，推测是：几何门在带噪的成员状态上遇到近失也会打开，SCATTER 在这些盘步上打乱速度方向；同一个门配 L-ind 时，GN 只有 −0.003）。
   - 同理，§5 的负对照判据（`DESIGN-r0.md:145`「否则说明门本身就能带来收益，GA、GC、GX 作废」）挡不住「门加放宽」带来的收益。
4. **门槛与参照。**
   - GK 以 E-P 为参照是对的：真实物理放进同一个滤波器、用同一套登记噪声，就是能达到的上限。在登记种子下 E-P 过 GK1、GK2（0.907 / 0.907，0.913 / 0.830），门槛可达。名义的 0.90 在重新出现、有碰撞的事件上连 E-P 也达不到（0.830），所以不该用名义值作参照。
   - GN、GK2 没有碰撞那一半，E-B 本身就过，它们只用来挡一期的代价。真正有鉴别力的是 GA、GC、GK1 碰撞步、GK2 有碰撞、GD。前四个在 SCATTER 面前的余量只有 0.002–0.012，见第 3 条。
5. **登记种子下的 L-int-g 与摸底数的差别。** 登记代码的滤波器种子与摸底不同（§4c）。同样 40 个世界上，L-int-g 的 GN 从摸底的 +0.018 变成 +0.003 [−0.020, +0.026]，GA 从 +0.067 变成 +0.054。仍全过，但说明 40 个世界上的点估计对随机数相当敏感，§5 表里的「摸底值」不宜当作 final 的预期值来读。
6. **选择偏差的检查在代用模型上也做了**（`evidence/metrics/one_step_rows-surrogates-main.txt`、`-extrap.txt`）：主评测所有臂（含 E-CV）的碰撞行都是 600 行，全部行相差 < 0.2%；外推的碰撞行在 827–831 之间。
7. **GX（外推 20 个世界，10 盘）。**
   - L-int-g 过：+0.089，C 1.025。
   - 三个卡片要求的代用模型都不过。门永远开的 C 半边是过的（0.690，下界 0.443），挡住它的是差值半边（+0.027，门槛 0.03）。
   - SCATTER 的差值半边已经过了（+0.045，下界 +0.004），C 点估计 0.645 也过了 0.6，只差 C 的 Bonferroni 下界（0.287，门槛 0.4）。final 外推是 100 个世界，按世界数开方粗估，区间宽度约为现在的 0.45 倍，这个下界会到 0.48 左右，很可能也过（推断，未实测）。所以 GX 同样挡不稳 SCATTER（`gates.txt` 第 92–94 行）。

## 3. 指标定义有没有漏洞或泄漏

结论：**没有找到泄漏。** 设计稿的定义与随稿的实现 `analysis_p2.py` 一致。有一处写法不精确（R3）、一处统计口径不一致（R1），都列为建议。另有一处解读上的提醒（3b）。

**3a 一步覆盖率的步类。** 设计稿 `DESIGN-r0.md:129`：

> 按被检测盘在 t−1 → t 这一步的类型分类：碰撞（接触日志有盘间接触）、其余。三个种子的行合在一起数。

接触日志的时间约定是 `world.py:127`：

> `    contacts: tuple[tuple[str, int, int], ...]  # contacts during t -> t+1, truth`

实现取的正是 t−1 步的日志，`analysis_p2.py:100`：

> `        touched = {i for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"} | {j for kind, i, j in self.ep.steps[t - 1].contacts if kind == "disk"}`

所以步类与设计一致。真值只在 `on_predict` 钩子里用来打分，钩子拿到的是副本（`filter.py:110`：`            on_predict(t, P.copy(), V.copy(), dict(assign), list(last))`），改不了跟踪。

**一步覆盖率有没有选择偏差。** 一行只在轨迹 t−1、t 都分到检测时才有（`analysis_p2.py:101-102`：`        for r, k in assign.items():` / `            if last[k] != t - 1:`）。预测差的模型如果因此丢掉关联，就会少掉难的行，覆盖率被抬高。我按臂数了摸底 F 轮的行数（`evidence/metrics/one_step_rows.py`，原始输出 `evidence/metrics/one_step_rows-p2f-main.txt`）：

```
$ .venv/bin/python -I -B reports/V9-S4-P2-DESIGN/r0-review/evidence/metrics/one_step_rows.py reports/V9-S4-P2-DESIGN/tier1-explore/results-p2f.json main
main: 40 worlds
arm             rows all rows coll inside coll cov coll | coll events
E-B                59807       600         349    0.582 |         267
E-P                59830       600         530    0.883 |         267
L-ind-geo          59789       600         354    0.590 |         267
L-int-g@0.3        59829       600         520    0.867 |         267
L-int-g@0.5        59832       600         530    0.883 |         267
L-int-g@0.7        59829       600         529    0.882 |         267
L-int-geo          59817       600         524    0.873 |         267
```

碰撞行每个臂都是 600，全部行相差不到 0.1%。所以没有选择偏差：碰撞那一步的预测误差远小于关联门限（0.6 + 1.5 × 0.1），E-B 也不会丢关联。代用模型上的同一检查见 §2。

**3b 重新出现时取哪条轨迹。** 设计稿 `DESIGN-r0.md:131` 要求取「a 步时持有这个盘的那条轨迹」。实现 `analysis_p2.py:116-117`：

> `        trk = at[e["a"]][e["k"]]`
> `        out.append(int(_gauss_inside(snaps[e["b"]][:, trk], ep.steps[e["b"]].positions[e["k"]])))`

`snaps` 是 b 步关联之后、观测更新之前的集合（钩子在 `filter.py:108-110`，更新在其后）。与设计一致。轨迹在滤波器里不删，所以 b 步一定有这条轨迹。

一个解读上的提醒（不算漏洞）：如果 a 步的轨迹在隐藏期里被别的盘的检测接走，它在 b 步跟的是别的盘，这个事件按「不覆盖」计。所以 GK2 的有碰撞一半同时反映身份保持，与 GC 相关，不是纯粹的校准量。

**3c 门只读成员状态。** `gated.py:69-83` 的 `step(P, V, pillars)` 只拿滤波器传入的成员状态和柱子。门的判定只用 `geo_gate(P, V)` 或 `head_gate(np.array(logits), P, float(gate))`（`gated.py:78`），logits 来自网络在成员状态上的输出。测试 `tests/v9/experiments/test_s4_gated.py:151` `def test_gates_never_read_the_world_or_its_physics() -> None:` 用名字检查卡住了这一点。没有读真值。

写法上不精确：`DESIGN-r0.md:119` 写

> - **代码约束：** 门控代码不得调用世界模块的物理。门关时，预测必须与 E-B 逐位相同；门开时，必须与 L-int 逐位相同。有测试。

但门关的分支就是 `Mo.bounce`（`gated.py:70`：`        pb, vb = Mo.bounce(P, V, pillars)`），而 `models.py:20-22` 的 E-B 就是生成器的物理去掉盘间碰撞：

> `def bounce(P: np.ndarray, V: np.ndarray, pillars: Sequence[W.Pillar]):`
> `    """E-B: constant velocity with wall and pillar reflections; no disk-disk collisions."""`
> `    p, v, _ = W.physics(P, V, pillars, disks=False)`

实际约束是「门的判定不调用物理；门控模型只调用 E-B，不调用 E-P」，测试检查的也是这个。建议改写这一句。

**门关时与 E-B 逐位相同：** 我在 60 个世界、180 个格上直接验证了（§2 的 `OFF` 臂，轨迹分配摘要与 E-B 全部相同）。

**3d 统计。**
- 按世界配对 bootstrap、10000 次、种子 20261111、Bonferroni m = 11。实现 `analysis_p2.py:38-39`：`BOOT_SEED = 20261111` / `N_COMPARISONS = 11                 # GN, GA, GC, GK1 (2), GK2 (2), GD (2), GX (2)`。m 的计数与 `DESIGN-r0.md:157` 的列举一致（1+1+1+2+2+2+2 = 11）。
- 种子平均方式：准确率和重新出现覆盖率每个事件三个种子先平均，一步覆盖率三个种子的行合在一起数。实现的说明在 `analysis_p2.py:12-13`：`share their random numbers. An event's correctness and its reappearance coverage are averaged over` / `the three seeds before summing per world; one-step rows of the three seeds are pooled.` 与设计 `DESIGN-r0.md:129`、`:131` 一致。同一世界三个种子的行高度相关，合在一起数只影响点估计的权重，区间按世界重采样，不会因此变窄。
- 无定义按不过算：`metrics.py:89-94` 在点值或任何一次重采样无定义时不给区间，需要区间的门都判不过。与设计 `DESIGN-r0.md:158` 一致。
- **口径不一致（建议）：** 门的区间用 Bonferroni，负对照用未校正的 95% 区间，`analysis_p2.py:273`：`            "neg_C": C_of(main, NEG_ARM, m=1), "neg_D": D_of(main, NEG_ARM, m=1)}`。负对照要求「上界 < 0.5」，区间越窄越容易过，所以用未校正区间是对负对照更宽松的一侧。这与设计原文 `DESIGN-r0.md:145`「95% 上界」一致，不是实现错误；但设计稿自己的理由（`DESIGN-r0.md:147`）是「有把握地说门本身带来的不到一半」，按同样的逻辑应当用 Bonferroni 上界或写明为什么不用。摸底值 C 0.11 [0.00, 0.22]、D 0.0005 离 0.5 很远，改了也不影响结论。

## 4. 摸底能不能复现

**4a 从 `results-p2f.json` 重算两份摘要，逐行一致。** 命令与原始输出（`evidence/repro/summary-diff.txt`）：

```
$ for k in main extrap; do .venv/bin/python -I -B $T/summarize_p2d.py $T/results-p2f.json $k > $E/summary-p2f-$k.recomputed.txt; diff $T/summary-p2f-$k.txt $E/summary-p2f-$k.recomputed.txt && echo IDENTICAL; done
== main: diff (empty = identical)
IDENTICAL
== extrap: diff (empty = identical)
IDENTICAL
35467b8d62640439abd31749fa6c49fe917ce8baa7cf450c844dbe7cea363e9e  reports/V9-S4-P2-DESIGN/tier1-explore/results-p2f.json
6ed285b6baef66ec96b7979f87a8fd21be2ebd401b6b96c3f7899d765ad0bee7  reports/V9-S4-P2-DESIGN/tier1-explore/summary-p2f-extrap.txt
a27986b653bbbf45d7bbb5be7d9e13ae0bad8cfbc11d35892bc42ba9333fd2fe  reports/V9-S4-P2-DESIGN/tier1-explore/summary-p2f-main.txt
6ed285b6baef66ec96b7979f87a8fd21be2ebd401b6b96c3f7899d765ad0bee7  reports/V9-S4-P2-DESIGN/r0-review/evidence/repro/summary-p2f-extrap.recomputed.txt
a27986b653bbbf45d7bbb5be7d9e13ae0bad8cfbc11d35892bc42ba9333fd2fe  reports/V9-S4-P2-DESIGN/r0-review/evidence/repro/summary-p2f-main.recomputed.txt
```

（`$T` = `reports/V9-S4-P2-DESIGN/tier1-explore`，`$E` = `reports/V9-S4-P2-DESIGN/r0-review/evidence/repro`。）设计稿 §1 表里还有几行来自 D、E、A 轮，我也重算了：`summary-p2d.txt`、`summary-p2e.txt`（`summarize_p2d.py`）和 `summary-p2a.txt`（`summarize_p2a.py`），三个都逐行一致（同一文件后半段：`== p2d` / `IDENTICAL`，`== p2e` / `IDENTICAL`，`== p2a` / `IDENTICAL`）。

**4b 经锁复跑 `explore_p2f.py` 的前 3 个主评测世界，逐格比对。** 脚本 `evidence/repro/run_repro_p2f.sh`（`hold_lock.py … .venv/bin/python -B reports/V9-S4-P2-DESIGN/tier1-explore/explore_p2f.py 3 0 $OUT/results-p2f-first3.json`），日志 `run_repro_p2f.log`。比对脚本 `compare_first3.py` 比对每个格的全部字段（`correct`、`n_tracks`、`reappear`、`one_step`），原始输出 `compare_first3.txt` 的末尾：

```
cells compared 63; correct identical in 63
fields differing: none
```

3 个世界 × 7 个臂 × 3 个种子 = 63 格，`correct` 全部逐位相同，其余字段也全部相同；3 个世界的事件列表也相同（`events identical: True`）。复跑时间 48.6 秒。

**4c 摸底与登记实现的随机数不同（提醒，不是问题）。** 摸底的滤波器种子带标签 `"q1"`（`explore_p2f.py:95`：`                rng = np.random.default_rng(W.derive_seed(XA.NS, "filter", w, s, "q1"))`），登记实现带 `"base"`（`analysis_p2.py:66-67`：`def filter_seed(ns: str, w: int, seed: int) -> int:` / `    return A.filter_seed(ns, w, seed, "base")`）。所以登记代码在同一批世界上算出的数不会与摸底逐位相同。§2 用登记代码在 `s4x-p2a` 上重算了 L-int-g，可以看作摸底数对滤波器随机数的稳健性检查。

## 5. 设计稿里的数字

用 `evidence/numbers/check_design_numbers.py` 核对。脚本从摸底的摘要、结果 JSON 和日志里解析出每个数，按设计稿的位数格式化，再到设计稿里应该写着它的那一行里找。数都由脚本解析，没有手抄。共核对 123 个数，覆盖 §0、§1 两张表的每一格、读法里的数，以及 §5 门表的「摸底值」列。原始输出 `evidence/numbers/check_design_numbers.txt`，末尾：

```
DESIGN-r0.md:84   MISSING  R#1 seconds per training step (736 s / 20000; run-p2b2.log): 0.037
...
123 numbers checked, 122 found in the expected design line, 1 missing

extra facts:
run-p2f.log (E-B, E-P + 5 gated arms = 7 arms x 3 seeds): main 616 s / 40 worlds = 15.4 s per world; extrap 764 s / 20 = 38.2 s per world
run-p2e.log (6 arms x 3 seeds, main): 331 s / 40 = 8.3 s per world
R#1 residual training: 736 s for 20000 steps = 0.0368 s per step (design §1: 0.033)
hidden gap (b - a - 1) over the 1216 main events of results-p2f: median 25, mean 30.3
gated share L-int-g@0.5 (results-p2f, tracking, main + extrap pooled): 0.0197
```

两张表各抽 10 个以上（主评测表第 52–63 行 65 个、外推表第 69–72 行 18 个），全部对上。例如主评测表 L-int-g 一行：

```
DESIGN-r0.md:58   found    L-int-g 0.5 没有碰撞−E-B [95%]: **+0.018 [−0.000, +0.035]**
DESIGN-r0.md:58   found    L-int-g 0.5 C [95%]: **0.96 [0.86, 1.05]**
DESIGN-r0.md:58   found    L-int-g 0.5 一步覆盖率: **0.904 / 0.883**
DESIGN-r0.md:58   found    L-int-g 0.5 重新出现覆盖率: **0.825 / 0.909**
```

外推表 L-int-g 一行：

```
DESIGN-r0.md:71   found    外推 L-int-g 全部−E-B [95%]: +0.088 [+0.064, +0.111]
DESIGN-r0.md:71   found    外推 L-int-g C [95%]: 1.01 [0.89, 1.20]
```

对不上或需要改写的地方：

1. **残差模型训练耗时。** `DESIGN-r0.md:84` 写「残差模型训练每步 0.033 秒，是 L-int 的 2.6 倍」。`run-p2b2.log:13` 是 `R#1 736s loss 4.824716567993164`，20000 步合每步 0.0368 秒。「2.6 倍」需要一期 L-int 的每步耗时，摸底目录里没有，我没有核。只是描述，不影响任何门。
2. **表格的斜杠有两种意思。** `DESIGN-r0.md:59` 一行「L-int-g，门限 0.3 / 0.7」里，斜杠表示 0.3 / 0.7 两个门限。但最后两列的列头是「全部 / 碰撞步」「有碰撞 / 没有碰撞」。这一行这两列里的 `0.901 / 0.904` 实际是两个门限的「全部」，`0.829 / 0.825` 是两个门限的「有碰撞」（脚本按这个读法找到，见输出里标 `*全部*`、`*有碰撞*` 的两行）。数没错，但容易被读成「全部 / 碰撞步」。
3. **§0 的覆盖率没说是哪类事件。** `DESIGN-r0.md:15` 的「0.60」「0.86」是没有碰撞事件上的重新出现覆盖率（一期 L-int 有碰撞的是 0.539，E-B 有碰撞的是 0.464）。建议写明。
4. **§7 预算里的单世界耗时出处不清。** `DESIGN-r0.md:196` 写「摸底中单进程每个主评测世界约 9 秒、外推约 30 秒（9 个臂 × 3 个种子）」。摸底 F 轮是 7 个臂，主评测平均 15.4 秒、外推 38.2 秒；E 轮是 6 个臂、8.3 秒；补记里冒烟的 27 格是主评测约 9 秒、外推约 11 秒。没有一轮是 9 个臂、主评测 9 秒、外推 30 秒。评测预留按探针实测算（§7），这里只是出处问题。另外今天上午本机负载一度到 200，我的复跑单世界从 22 秒拖到 13 分钟。硬上限 2 小时比按冒烟估的 15–30 分钟宽 4–8 倍，应该够，但探针最好别在机器很忙的时候测耗时，否则预留会被抬高。

## 证据清单

全部在 `reports/V9-S4-P2-DESIGN/r0-review/evidence/`。每个文件的 SHA-256 在 `../SHA256SUMS.txt`。脚本都从仓库根目录运行；MLX 部分自带锁。

| 文件 | 内容 | 复跑 |
|---|---|---|
| `repro/run_repro_p2f.sh`、`run_repro_p2f.log`、`results-p2f-first3.json` | 经锁复跑摸底 F 轮前 3 个主评测世界 | `sh evidence/repro/run_repro_p2f.sh` |
| `repro/compare_first3.py`、`compare_first3.txt` | 与 `results-p2f.json` 逐格逐字段比对 | `.venv/bin/python -I evidence/repro/compare_first3.py <原> <复跑>` |
| `repro/summary-*.recomputed.txt`、`summary-diff.txt`（及 `.stderr`） | 用摸底自己的摘要脚本重算的 p2f 主评测、外推和 p2d、p2e、p2a 摘要，以及与原件的 diff | 见 §4a 命令 |
| `numbers/check_design_numbers.py`、`.txt` | 设计稿 123 个数的核对 | `.venv/bin/python -I -B evidence/numbers/check_design_numbers.py` |
| `metrics/one_step_rows.py`、`one_step_rows-*.txt` | 一步覆盖率的行数（选择偏差检查） | 见 §3a |
| `physics/ep_vs_eb_overlap.py`、`.txt` | 重叠、正在分开的一对：E-P 与 E-B 不同、日志无接触 | `.venv/bin/python -I -B evidence/physics/ep_vs_eb_overlap.py` |
| `surrogates/track_surrogates.py`、`run_surrogates.sh`、`run_both.sh`、`run-main.log`、`run-extrap.log`、`records-main.json`、`records-extrap.json` | 代用模型跟踪（登记评测代码），逐世界记录 | `sh evidence/surrogates/run_surrogates.sh main`（再 `extrap`） |
| `surrogates/gates_surrogates.py`、`gates.json`、`gates.txt`、`table_surrogates.py`、`table.md` | 按登记的 `analysis_p2.decide` 判门，配对差 | 见 §2 命令 |
| `make_citations.sh`、`citations.txt` | 报告里每处引文的 `sed -n` / `grep -n` 原始输出 | `sh evidence/make_citations.sh` |
| `make_metrics.py`、`metrics.json` | 交卡用的简要指标（从上面各输出读取） | `.venv/bin/python -I -B evidence/make_metrics.py` |
| `weights-used.sha256` | 用到的六个一期权重的 SHA-256 | — |
| `make_sums.sh` | 生成 `../SHA256SUMS.txt` 并自检 | `sh evidence/make_sums.sh` |

运行环境：仓库 HEAD `5698eef`，`.venv` Python 3.12.2，MLX 0.32.2（CPU）。用到的一期权重是 `artifacts/v9/s4/phase1/final-final/weights/` 下的 `L-int#1–3`、`L-ind#1–3`（只读），SHA-256 记在 `evidence/weights-used.sha256`。
