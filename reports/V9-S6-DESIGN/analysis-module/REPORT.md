# P255 S6 指标、门与区间：交付

**执行者：一级 claude 接手。** 卡片放出后约 25 分钟无人领，当时没有二级在线，按用户 11-14 睡前指示由一级接手。**本交付尚未经非作者复核，不能当作已验收；复核卡是 P256。**

## 与卡片的出入

卡片按 DESIGN-r1 写的是「两层配对 bootstrap」：重复与世界都有放回抽样。实现之前，r1 的非作者复核（`reports/V9-S6-DESIGN/r1-review-sub/REPORT.md` 必修 1）指出：
- 只有 5 个重复时，有放回抽重复的 bootstrap 在 Bonferroni 水平上覆盖率只有 0.957，名义值是 0.9969；
- 这样算出的下界永远不会低于最差的那个重复。

一级采纳复核给出的公式，写进 DESIGN-r2 §4：

| 量 | 定义 |
|---|---|
| 点值 θ̂ | 全部重复 × 全部网络 × 全部世界 |
| θ_k | 第 k 个重复单独算出的值；s_rep = SD(θ_k)，ddof = 1 |
| se_w | 保留全部重复、各臂共用世界的配对 bootstrap，10000 次 |
| se | √(s_rep²/K + se_w²) |
| 区间 | θ̂ ∓ t(K−1, 1−α/(2m))·se，m = 8 |

比值类门在 log 尺度上算。K = 1 时没有重复层，s_rep 取 0，q 改用正态分位数。

卡片里的「`bootstrap(data)` 两层抽样」因此改成 `world_bootstrap(data)` 加 `interval(...)`。其余要求照卡片做：
- 输入形状，K 从数据读出；
- `GATES` 门表，以及严格、不严格的区分；
- GS 要求每个重复都 ≥ 0.03；
- NaN 判不过；
- `describe`，其中 D(E)−D(G) 只在 G 有的重复上配对。

## 文件

| 文件 | 说明 |
|---|---|
| `src/ainerzero/v9/experiments/s6/analysis.py`（新） | 纯 NumPy。没有 SciPy，所以 t 分布的 CDF 用整数自由度的闭式级数写，分位数用二分求 |
| `tests/v9/experiments/test_s6_analysis.py`（新） | 29 项，用合成数据 |

## 测试原始输出（`tests.log`）

```
.............................                                            [100%]
29 passed in 1.40s
```

测试覆盖：
- **t 分位数**：与 7 个教科书值对照，到 1e-5，包括 t(4, 0.996875) = 5.26106；另查正态分位数与大自由度的极限。
- **`stats` 的计算**：
  - 手算的小例子；
  - 重复、世界按重数计权；
  - 等于「对重复、网络、世界合并求和后之比」；
  - 与原型 `explore_s6a.evaluate` 的算术一致；
  - 分母为 0 时得 NaN。
- **世界 bootstrap**：
  - 抽样次序与种子都写死；
  - 配对：某臂等于另一臂乘一个常数时，比值门的每次抽样都等于这个常数；
  - 逐次抽样与 `stats` 在抽中世界上的值一致。
- **区间**：
  - t 区间与手算一致；
  - 比值门在 log 尺度上对称；
  - K = 1 时用正态分位数；
  - NaN 判不过。
- **门**：
  - 门表与设计稿逐项相等；
  - 严格与不严格的边界；
  - 合成效应下的判定，以及「Bonferroni 区间包住 95% 区间，95% 区间包住点值」；
  - GT 的公式；
  - GS 每个重复都要 ≥ 0.03；
  - GX 只读外推集；
  - G 不进入门；
  - 重复数和形状的检查；
  - K = 1、K = 2 也能跑；
  - 模块不导入 MLX 和 SciPy。

## 变异

脚本是 `reports/V9-S6-PHASE1/impl-evidence/mutate_pure.sh`，原始输出在 `mutate_pure.log`；与沙盒 r2、静态检查一起跑。

做法：
- 用 `git archive HEAD` 导出隔离副本，再拷入未提交的 S6 文件；
- `PYTHONPATH` 指向副本的 `src`，日志首行打印模块路径，确认从副本加载。

本模块的 11 个变异全部被杀死：

```
== baseline: 57 passed in 1.92s
== A1 Bonferroni with m = 6: 1 failed, 56 passed in 1.85s
== A2 GZ-W upper bound non-strict: 1 failed, 56 passed in 1.86s
== A3 GT counts the whole truth-curriculum gain: 3 failed, 54 passed in 1.96s
== A4 worlds redrawn for arm R (unpaired): 3 failed, 54 passed in 2.00s
== A5 ratios not on the log scale: 2 failed, 55 passed in 2.00s
== A6 replicate variance not divided by K: 2 failed, 55 passed in 2.02s
== A7 t with K degrees of freedom: 2 failed, 55 passed in 2.03s
== A8 per-replicate GS check dropped: 1 failed, 56 passed in 2.16s
== A9 GX on the main set: 3 failed, 54 passed in 2.07s
== A10 NaN passes: 1 failed, 56 passed in 1.95s
== A11 world draws not shared: extrap drawn first: 1 failed, 56 passed in 1.94s
== restored: 57 passed in 2.04s
```

## 留给复核（P256）

- 用独立代码，不 import 本模块，按复核公式重算 8 个门的点值与区间。
- 自己设计变异。
