# P260 S6 probe 纯 CPU 独立复算报告

结论：**建议打回**。
逐字段比较 601 项，不一致 0 项；产物完整性问题 0 项；final 预算外推符合上限：False。
运行证据核验与统计复算均符合本次可核验项目；final 评测预算超限，阻断冻结。
本报告不是 K=1 的科学能力结论，不自动放行 final、不晋升模型。
**预算必修项：原式预计评测 4212.69 秒，超出冻结上限 3600 秒达 612.69 秒；仅含 30% 余量的校验部分已为 3737.07 秒。当前预算可行性不成立，建议不得据此冻结或启动 final。算术复现与预算可行性分别判定；本执行者不修改公式、参数或上限。**

## 身份与边界

- 执行者：codex-s6probe-rv-1115，tier2 / kind codex / skills code,math；仅领取 P260，未参与被审实现或模型运行。
- 指定版本：a33d34b5cb8d06800f584a0abcfd788d16f80fcb；源码闭包以 final-01/source-manifest.json 的逐文件哈希绑定。
- 源码闭包 SHA256：`839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`（42 个文件）。
- 一级可读通知：消息 #816，2026-11-15T22:21:50+00:00；原文保存在 eval-release.json，收到后才读取 eval 报告。
- 所有写入仅 reports/V9-S6-PHASE1/probe-review-codex/；未改 src、tests、设计、旧产物；未回退他人改动、未提交、未推送。
- 仅标准库 + NumPy。审计钩子拒绝导入 mlx / ainerzero；final-01/environment.json 记录两者均未加载。没有生成世界、模拟标签、训练、推理或重新评测。
- 没有预留或消耗新的模型运行预算。下面的时间是已交付训练账本的实际量及未来规模的计算外推，不是运行授权或 RunStore 预留。

## 完整性与可复算证据

- 六臂 R/E/Z/T/P/G，各一个重复；每格三个网络 × 四轮，共 72 份 safetensors。逐文件 SHA、文件集合和 safetensors 头部数据区覆盖均检查。
- 每轮 3000 个编号、每条选择轨迹累计 12000 个不重复编号；P 的三个学习者各自一条轨迹。每轮 picks 与 reveal_log.ids 完全一致，call 顺序 0..3，revealed 顺序等于所有 picks 串联。
- 独立派生首轮、候选池和挑选种子；各臂首轮一致；R/T 四轮随机编号独立复算一致。E/Z/P 分数只核对摘要格式及已有重放记录，没有运行模型重新计算分数。
- main6 50 世界、extrap10 25 世界，分别为世界 0..49 的 6 盘和 1000..1024 的 10 盘。每世界 300 状态、299 个相邻转移；所有误差数组覆盖 1×3×4×世界数×4 类。
- 核对报告、cell.json、errors.npz、worlds.json、verify.json 与训练账本的身份及 SHA 链；输入完整哈希在 final-01/inputs-sha256.json。
- 既有 verify.json：六格全部重放记录为真，E-r0-n0、P-r0-n0 各四轮复训逐位一致记录为真，种子 1；与报告嵌入记录逐字段相同。这里只独立核对落盘证据与其绑定，不声称 CPU 重新执行了训练或重放。
- 候选状态与实际标签张量没有单独落盘，本次不能独立重算候选内容池 SHA 或物理标签内容。核对的是各格 pool_sha256 与 pools.json 一致、揭示链完整，并核对已保存跨进程复算记录；不将 SHA 当来源认证。

输入及源码审计后稳定性复核：84 个输入文件和 42 个源码文件均未变化，并与 a33d34b 逐文件身份一致；见 post-review-stability.json。

## 八门算术（K=1，仅流程检查）

| 门 | 独立点值 | Bonferroni 下界 | 上界 | 报告判定复现 |
|---|---:|---:|---:|---|
| GS | 0.0931821612 | 0.0794183355 | 0.1069459869 | True |
| GT | 0.0511892114 | 0.0406759109 | 0.0617025119 | True |
| GZ-D | -0.0041676918 | -0.0101974942 | 0.0018621107 | True |
| GZ-W | 0.9038695845 | 0.8889908328 | 0.9189973571 | True |
| GK-A | 0.9488068688 | 0.9307135855 | 0.9672518897 | True |
| GK-F | 1.0929338087 | 1.0232171179 | 1.1674006322 | True |
| GP | 0.0862931356 | 0.0704824887 | 0.1021037825 | True |
| GX | 0.0937568329 | 0.0817116555 | 0.1058020103 | True |

复算使用池化误差和/计数的比值；10000 次按世界配对抽样，种子 20261114，逐次先 main6 再 extrap10。比值门在 log 尺度构建区间；K=1 时重复层方差为 0、使用标准正态分位数。点值、逐重复值、95% 区间、Bonferroni 区间、方差分量、分位数、df、布尔判据及汇总字段逐一比较；另核对四轮描述量、臂间差和比值以及选样重合比例。
浮点容限：相对 2e-11、绝对 2e-12；键集合、长度、布尔类型和值均精确比较。final-01/comparison.json 保存全部比较项，final-01/recomputed.json 保存独立重算值。
工具自身验证：八门手算点值及常量样本的零方差区间；非零方差的解析标准误对照；自由运动代价负对照；点值/区间/判定三处篡改均被检出。见 tool-validation-r2.json。

## final 预算独立外推

- 探针训练账本累计计费 3275.281 秒，所有 invocation closed；六格秒数与账本、评测报告一致。

| 臂 | 探针实际秒数 | final 重复数 | 外推格训练秒数 |
|---|---:|---:|---:|
| R | 539.2 | 5 | 2696.0 |
| E | 551.3 | 5 | 2756.5 |
| Z | 550.3 | 5 | 2751.5 |
| T | 530.6 | 5 | 2653.0 |
| P | 590.6 | 5 | 2953.0 |
| G | 485.0 | 3 | 1455.0 |

28 格、84 网络、336 权重文件。加权训练 15265.0 秒，加 5×90=450 秒候选池余量后乘 1.15，得到 **18072.25 秒**；上限 21600 秒，符合：True。
训练账本相对六格秒数的实际额外耗时 28.281 秒，按五组外推为 141.406 秒；与保守候选池额度分开报告。
评测按格数 28/6、测试世界数 300/75 外推：校验 2874.67 秒，纯评测 365.87 秒，合计乘 1.30 为 **4212.69 秒**；上限 3600 秒，符合：False。
外推公式对应 a33d34b 的原 make_prereg.py，原文快照在 baseline-source/；P261 对 builder/helper/tests 的修订不改变本次原公式/6h+1h基准。数值输入由 train-ledger.json / cell.json 独立获取并对评测报告交叉检查。假设同规模格性能不变；只是一点计时外推，不能保证后续运行耗时。没有更改门槛或预算。

## 原文 citations

以下为实际源码逐字引文，完整带行号输出及文件 SHA 在 citations.txt。

`reports/V9-S6-DESIGN/DESIGN-r2.md:288`（a33d34b 原文，baseline-source/ 同路径快照）
> - K = 1（只用于探针）时没有重复层：s_rep 取 0，q 用正态分位数。探针的区间只用来检查流程，不作结论。

`reports/V9-S6-DESIGN/DESIGN-r2.md:334`（a33d34b 原文，baseline-source/ 同路径快照）
>    - 本稿的臂、配方、门槛、预算在探针前冻结。探针结果只允许修实现错误。任何别的改动都要写成 r3 送复核，并在研究日志里写明「看过探针」。

`reports/V9-S6-PHASE1/make_prereg.py:50`（a33d34b 原文，baseline-source/ 同路径快照）
>     est_train = 1.15 * (sum(max(per_arm[arm]) * k for arm, k in reps_final.items()) + 5 * 90)

`reports/V9-S6-PHASE1/make_prereg.py:52`（a33d34b 原文，baseline-source/ 同路径快照）
>     est_eval = 1.30 * (pr["verify_seconds"] * n_cells_final / n_cells_probe

`src/ainerzero/v9/experiments/s6/cells.py:373`（a33d34b 原文，baseline-source/ 同路径快照）
>         if [e["ids"] for e in log] != picks or [e["call"] for e in log] != list(range(sizes.rounds)):

`src/ainerzero/v9/experiments/s6/cells.py:416`（a33d34b 原文，baseline-source/ 同路径快照）
>     T = len(ep.steps) - 1

`reports/V9-S6-PHASE1/verify_s6p1.py:29`（a33d34b 原文，baseline-source/ 同路径快照）
> RETRAIN = (("E", 0, 0), ("P", 0, 0))      # (arm, replicate, learner): seed 1 of replicate 0

最终复算命令退出码 1 是预算超限的预期失败，不是脚本异常；stderr 为空，比较不一致为 0。

## 实际命令与复跑

注册、claim、prompt、心跳、消息 received/applied 均通过现有 Relay CLI 完成；完整卡面在 task-prompt.txt，消息和心跳在 heartbeat-inbox.jsonl。

```sh
cd /Users/mac/AinerWorkFlow/AinerZero
.venv/bin/python -I -B reports/V9-S6-PHASE1/probe-review-codex/validate_tool.py
.venv/bin/python -I -B reports/V9-S6-PHASE1/probe-review-codex/recompute.py --out reports/V9-S6-PHASE1/probe-review-codex/replay-NEW --report reports/V9-S6-PHASE1/probe/EVAL-probe.json
```

复跑必须给新的输出目录，不覆盖本次复核。实际最终命令、退出码、标准输出和标准错误在 final-command.json / final-run.stdout / final-run.stderr。原有 preliminary-01/02 留存训练中的快照，READY.md 的“未完成”仅描述当时状态。

## 失败、发现和未验证项

逐字段不一致：[]。
完整性问题：[]。
实际模型重放、复训和标签物理真值未由本执行者重跑；没有再次读 final；K=5 重复层统计不在本次 K=1 探针复算中验证。
记录的第三方版本：{"numpy": "2.5.3", "mlx": "unknown"}。MLX 若记为 unknown，则该报告未提供确切发行版本，复核者没有通过导入 MLX 补查。
共享仓库中他人的 COORDINATION.md / RESEARCH_LOG.md 等改动保持原状。工具准备时错误尝试了不存在的 src/ainerzero/s6 路径，立即更正为 src/ainerzero/v9/experiments/s6；没有执行或更改目标代码。
最终建议只涵盖本次探针产物、算术和预算可行性。具体启动/冻结/接受由一级负责。交回 P260 后不领取下一卡。

生成时间：2026-11-15T22:22:30.825944+00:00
