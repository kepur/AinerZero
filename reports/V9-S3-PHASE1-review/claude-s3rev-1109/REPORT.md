# S3 第一阶段第二路非作者复核（ainerzero.V9.P208）

复核者 `claude-s3rev-1109`（独立会话），2026-11-09。依据 `reports/V9-S3-DESIGN/DESIGN-r2.md`。原始输出在同目录 `evidence/`，校验和在 `SHA256SUMS.txt`。

## 结论：打回

打回的是**运行器和证据链**，不是 dev1 的判定。

- **dev1 的判定不推翻。** H1 过、H2 未过、H3 未过，我没有发现会改变这三项判定的缺陷，不要求重跑 dev1。
- **没有发现真值泄漏。** A0、A1、A2、A3、N 都碰不到 `truth`、`oracle`、答案或「是否已换」，只有 O 用 `oracle`（`batching.py:80`、`arms_mlx.py:88`）。
- **统计单位正确。** bootstrap 按回合重采样，三个种子同一回合一起进出。
- **运行器不能原样再用。** 下面 5 个必修项，第 1、2、3、4 项在第二次 dev 或 final 之前必须修，第 5 项在下一次冻结之前必须修。其中第 2 项让 H1、H2 的置信区间至今无法被任何人复算。

因为这些文件的 SHA 已写入预登记，修改就要重新冻结，这正好和 DEV1-REPORT §5 计划的第二阶段新登记合并做。

## 必修项

| # | 问题 | 位置 | 实证 | 怎么修 |
|---|---|---|---|---|
| 1 | `--stage smoke` 用 `s3p1-dev` 评测，不记账本，也不校验 SHA，绕过 DESIGN §6「dev 至多两次」 | `run_phase1.py:88`（评测命名空间），`:67`、`:72`（只对非 smoke 校验、记账） | 守卫测试：smoke 不写账本；把 `analysis.py` 改掉后 smoke 仍通过 | smoke 改用 `s3p1-probe`。一级核实 16:03:31 那次运行（见下）并记入 RESEARCH_LOG |
| 2 | 逐事件结果没有落盘，主臂权重又是 F2 之后的，H1、H2 的置信区间无法复算 | `run_phase1.py:98`（只留在内存），`:103`（F2 之后才存权重），`:60`（只存汇总） | `dev1.json` 的 `cells` 只有 `primary`、`n_primary`、`unswapped` 三个汇总字段 | 每格每阶段写逐事件数组；保存 F1 结束时的权重 |
| 3 | 账本和 final 标记写在拿锁之前。锁被占时 dev 被扣一次，final 的唯一机会直接作废 | `run_phase1.py:75`、`:80` 早于 `:82` | 守卫测试：锁被占时 `BlockingIOError` 退出，账本已记 dev1，`FINAL_READ_ONCE.json` 已写 | 先拿锁，再记账和写标记。这把锁是全项目共用的 |
| 4 | 冻结清单漏了 S2 的依赖。`make_layout`、`step`、`compute_ego_view` 和世界常量在 `s2/world.py`，它又依赖 `s2/spec.py`，都不在 `code_sha256` 里；`design_sha256` 也不在运行时校验 | `PREREG-r1.json:7-20`；`run_phase1.py:68-69` | 守卫测试：改动 `s2/world.py` 后 dev 守卫照常通过 | 冻结清单改为传递闭包，运行时一并校验设计稿 |
| 5 | 项目测试保护不了真值隔离。我做的 12 个变异里 8 个项目测试抓不到，真值、泄漏、对照类 7 个漏了 6 个 | `tests/v9/experiments/test_s3_arms_mlx.py`、`test_s3_analysis.py` | 见第 5 节 | 把 `evidence/review_harness.py` 的 T2、T3、T3b、T4、T5、T7、T10、T11 收进项目测试 |

**关于 16:03:31 的运行：** `artifacts/v9/s3/phase1` 诞生于 16:03:31，dev 账本写于 16:05:21，运行器最后修改在 16:04:17。创建这个目录的只有 `ROOT.mkdir`（`run_phase1.py:70`），账本和 final 标记都没有更早的记录，所以那次很可能是 smoke，而且用的是冻结前的版本。这是推断，当时的代码和输出都没有留下，RESEARCH_LOG、DEV1-REPORT 也没提。如果确实读了 dev，按现行代码 smoke 只训练 4 步，不大可能带出有用的信息，但严格说它是一次未入账的 dev 使用。

## 逐项复核

### 1. 真值隔离

逐路径读过 `tour.py`、`world.py`、`content.py`、`store.py`、`cues.py`、`batching.py`、`arms_mlx.py` 和 S2 的 `compute_ego_view`，并实测（`evidence/m00_unmutated_control.txt`）：

| 路径 | 结论 | 证据 |
|---|---|---|
| `obs` | 由局部 3×3 视野、朝向、上一动作、撞墙组成，无绝对坐标 | `world.py:224-302`；`compute_ego_view` 只算局部地形和视线 |
| `prepare_episode` 读取的字段 | 步只读 `t`、`obs`、`est_pose`；事件只读 `t`、`prev_visit_t`、`answer`、`swapped`、`bucket`；读 `truth`、`cell`、`lag`、`content_state` 会直接报错，实测没有触发 | T1 |
| 事件标签的去向 | 改 `prev_visit_t` 只动 `oracle`，改 `answer`、`swapped`、`bucket` 各只动自身，检索结果和特征不变（268 个事件） | T2 |
| 各臂输出 | 把 `oracle`、`answer`、`swapped`、`bucket` 换成随机值，A0、A1、A2、A3、N 的 logits 逐位不变（软、硬两种模式）；O 会变，说明测试有判别力 | T3 |
| 各臂只读自己的检索字段 | A0、A1 不读任何检索字段；A2 只读 `top1`；N 只读 `shuffled`；A3 只读候选 | T3b |
| `est_pose` 原点 | 起点取了真实坐标（`tour.py:122`），但只有相对量进入检索：整体平移后结果不变 | T6 |

### 2. 泄漏与未来信息

- **A0、A1：** A0 只看当前观察；A1 是单向 GRU，打乱事件之后的步骤，该事件输出不变，打乱之前的步骤会变。T3 同时确认两臂碰不到答案和「是否已换」。
- **候选与特征：** `get_pool` 要求 `r.t ≤ t−5`，打分只比较查询与候选，没有全局归一化。把回合截断到事件时刻，67 个事件的 `top1`、候选、特征、掩码都和完整回合一致（T5）。特征是位姿距离、地形相似度、时间差，都是学生可见量。
- **一处偏差（不必修）：** N 的 `shuffled` 是全回合下标打乱（`batching.py:55-56`、`:81`），样本里 25/67 个事件读到的是未来的记录。方向上只会抬高 N，N 在 dev1 上是 0.001，不影响门。下版建议只在 `t−5` 之前打乱。

### 3. 统计

- `paired_bootstrap_delta` 按回合聚合后重采样，和逐回合暴力实现逐位一致（T7）。
- 三个种子：回合 ID 不加偏移，同一回合三个种子一起进出。合成数据上，把种子当独立回合时区间从 0.134 收窄到 0.099，说明现在的写法是对的。
- 缺数据：全部事件为空时，合法性门全部判否、bootstrap 抛错、NaN 不能过任何门（T8）。这靠的是 NaN 比较恒假，不是 `G.accuracy`，见下面第 3 条应修项。
- 局限（登记口径允许）：区间不含训练种子方差；同一世界的 2 个回合共用布局，按回合重采样未考虑这一层。A2−A1 三个种子分别是 0.838、0.782、0.710，A3−A2 是 −0.047、−0.050、−0.059，方向都一致。

### 4. 预登记与守卫

- **SHA：** 12 个代码文件和 `design_sha256` 与盘上一致。`dev1.json` 记录的预登记 SHA（`4910a049…`）与文件一致。
- **参数：** 种子、步数（2000/1000/1500）、batch 16、lr 1e-3、λ 1.0、数据规模（400×4、50×2、100×2）、命名空间、门槛和 bootstrap 参数，预登记、`run_phase1.py`、`analysis.py` 三处一致（T10 另有自动对照）。
- **分区：** 种子集合互不相交（含 final，只计算种子，未生成世界）；train、dev、probe 的布局哈希无重叠，也没有内部重复。
- **守卫（`evidence/guard_test.txt`，在改写过 REPO 的假根目录里跑）：** dev 无 use-id、重复 use-id、第三次都被拒；final 缺批准行、错批准行、第二次都被拒；代码被改后 dev 被拒。实盘账本仍是 1 条（dev1），final 标记不存在。
- **能绕过的地方：** smoke（必修 1）；S2 依赖改动（必修 4）。删掉账本或标记后守卫复位，这属于本地文件守卫的固有限制，只对诚实执行者有效。批准行以明文写在预登记里。

### 5. 变异（隔离副本，源码级）

未变异对照：项目 42 项通过，校验器 12/12 通过。基线 SHA 跑后不变。

| 变异 | 文件 | 项目测试 | 校验器 |
|---|---|---|---|
| m01 A0 读 oracle | `arms_mlx.py` | **漏掉** | 抓到 |
| m02 A3 评测用答案选候选 | `arms_mlx.py` | **漏掉** | 抓到 |
| m03 A1 看到未来 | `arms_mlx.py` | **漏掉** | 抓到 |
| m04 A2 用真值检索 | `batching.py` | **漏掉** | 抓到 |
| m05 N 退化成 A2 | `batching.py` | **漏掉** | 抓到 |
| m06 候选特征泄漏「是否已换」 | `batching.py` | **漏掉** | 抓到 |
| m07 候选池读未来 | `batching.py` | 抓到 | 抓到 |
| m08 bootstrap 按事件重采样 | `analysis.py` | 抓到 | 抓到 |
| m09 区间符号翻转 | `analysis.py` | **漏掉** | 抓到 |
| m10 H2 门槛改成 −0.10 | `analysis.py` | **漏掉** | 抓到 |
| m11 地板门恒真 | `analysis.py` | 抓到 | 抓到 |
| m12 差异门 and 改 or | `analysis.py` | 抓到 | 抓到 |

原始输出节选（全文见 `evidence/`）：

```
## m01_a0_reads_oracle
42 passed, 1 deselected in 13.52s
FAIL T3_logits_ignore_oracle_and_labels :: {"leaks": {"A0/hard=True": "logits 依赖 oracle/answer/swapped/bucket", ...
FAIL T3b_arms_read_only_their_own_retrieval_field :: {"bad": {"A0": ["oracle", "top1", "shuffled", "candidates"]}, ...
SUMMARY pass=9 fail=3
## m02_a3_eval_uses_answer_target
42 passed, 1 deselected in 13.52s
FAIL T3_logits_ignore_oracle_and_labels :: {"leaks": {"A3/hard=True": "logits 依赖 oracle/answer/swapped/bucket"}, ...
SUMMARY pass=11 fail=1
## m04_a2_top1_is_oracle
42 passed, 1 deselected in 13.46s
FAIL T2_event_labels_reach_only_their_slot :: {"leaks": {"prev_visit_t": ["shuffled", "top1"]}, "n_events_checked": 268}
FAIL T5_retrieval_ignores_future_steps :: {"events_checked": 67, "bad": [], "gap_ge_5": false}
SUMMARY pass=10 fail=2
## m06_cand_feat_leaks_swapped
42 passed, 1 deselected in 13.73s
FAIL T2_event_labels_reach_only_their_slot :: {"leaks": {"swapped": ["cand_feats"]}, "n_events_checked": 268}
SUMMARY pass=11 fail=1
## m09_ci_sign_flip
42 passed, 1 deselected in 13.54s
FAIL T7_bootstrap_cluster_unit_and_seed_pooling :: {"exact_match_bruteforce": "False", ...
SUMMARY pass=11 fail=1
## m08_bootstrap_event_unit
2 failed, 40 passed, 1 deselected in 13.49s
FAILED tests/v9/experiments/test_s3_analysis.py::test_point_delta_is_exact_difference
FAILED tests/v9/experiments/test_s3_analysis.py::test_interval_widens_when_resampling_episodes_not_events
```

被漏掉的变异说明测试有缺口，**不说明现有代码有这些问题**：现有代码在同一校验器上全部通过。

### 6. dev1.json

- **汇总数字可复算：** 主指标、未换事件、H1/H2 的 Δ、H3 下降、合法性、`valid` 都能由 `cells` 重新算出，差异不超过 1e-12（`evidence/recompute_dev1.txt`）。
- **数字不像编造的：** 每个准确率乘以事件数都是整数。事件数我单独重新生成 dev 数据核对：F1 主指标 321、未换 260、98 个回合有主指标事件，F2 为 355、253，全部吻合。
- **判定不依赖未验证的部分：** H2 单凭 Δ < 0.05 就不过；H3 只看点估计；H1 的 Δ 是 0.777，三个种子都在 0.71 以上。
- **H3 诊断可复现：** 用 dev1 的权重在 probe 分区重跑，8 个主指标数字和 `diagnosis/h3_class_bias.json` 一致到四位小数。

## 未验证

| 项 | 原因 |
|---|---|
| H1、H2 置信区间的具体数值 | 逐事件结果没落盘（必修 2）；复算需要重新训练，本次禁止 |
| 主臂 F2 之前的逐事件结果 | 同上 |
| 16:03:31 那次运行的内容 | 代码和输出都没留下 |
| 探针 P-d 至 P-g 的数值 | 需要训练，未重跑；只核对了门的算术和判定代码 |

## 应修（不阻塞）

1. **H3 登记口径混入了读出头类别偏置。** 换族后 A0 的未换事件从 1.00 掉到 0.00，A1 接近 0，这不是记忆受损。作者已如实诊断。r2 用不相交 token 集是为了避免「恒假」，但从 dev1 看，这个门仍被类别偏置主导，不能当作保护能力的度量。下版要写明哪些臂必须满足，并排除 A0 这类平凡通过。DEV1-REPORT §4 的「仍低 0.26–0.37」是拿 probe 和 dev 跨分区比较。
2. **A3 训练和评测不一致。** 训练时读出头看软加权混合，评测时看硬选的单条（`arms_mlx.py:110-114`）。`ce_0` 对同一事件所有候选相同，在 softmax 里被消掉（T9），「带与不带的差」实际只剩 `ce_c`。H2 按登记判未通过不变，但解读时要考虑这一点。
3. **`G.accuracy` 不在生产路径上**，只有测试调用。运行器用 `.mean()`（`run_phase1.py:60`、`:114-115`），空数据得到 NaN，靠比较恒假才失败封闭。建议走同一入口。
4. **DESIGN §4 的常设报告缺 5 项：** M2 干扰诊断、分桶曲线、平衡准确率、precision@1 与候选池召回率、峰值内存，只有训练耗时。`dev1.json` 没有检索指标，DEV1-REPORT 的 0.654 与 C2 复核在 probe 分区的 0.6545 一致，并不是 dev 上算的。
5. `test_final_partition_refusal_by_default` 每次都用 `allow_final=True` 生成 final 的 0 号世界（`test_s3_partition_determinism.py:68-73`），只在内存里，但违背「冻结后才生成」。我跑测试时排除了这一项。
6. `test_s3_arms_mlx.py` 不在 `tests/conftest.py` 的 `NATIVE_MODULES` 里，默认「纯 CPU」入口会导入真实 MLX。
7. 其余小项：无最小样本门，单回合也能形式上过差异门（T8）；3 小时上限只在格子之间检查，最多超出约 275 秒（A1 一格约 575 秒，`:95`）；账本不记用途（DESIGN §6 要求写明）；账本读改写无锁；`--report` 可覆盖旧报告；读出头 17 类而设计写 16 类（0 类永远不是目标，无影响）；合法性门恒查 A2、A3，比设计「被判阳性的臂」更严。

## 对第一路复核（gemini-b8k2）的核对

建议一级不要单独采信那份「建议通过、必修 0」。它的 SHA、参数、统计单位结论我复核后成立，但有四处证据和结论不对应：

- 「破坏 truth 后输出差异 0.0」是空测试：`obs` 在生成时已算好，事后改 `truth` 不可能有影响。结论正确，证据无效。
- 它称所有汇总数字与 `cells` 的逐事件计算逐位吻合，这不可能成立：`cells` 里没有逐事件数据，CI 无从复算。
- 「守卫已落实」漏了 smoke、先记账后拿锁和 S2 依赖。
- `mut3` 变异的 `G.accuracy` 不在生产路径上，没有验证到运行器的行为。

## 操作与独立性说明

- **卡状态：** 简报写的是待领取，实际 P208 已由 gemini-b8k2 交回、处于「待验收」，`relay claim` 返回 409。我没有用 `--force`，也**没有执行 `relay report`**（代码要求状态为 claimed 且执行者是本人）。需要一级决定如何入卡。
- **文件：** gemini 的 `REPORT.md` 等已交付并登记 SHA，所以本报告放在子目录，未改动它们。在 relay 上注册了 `claude-s3rev-1109`（二级），未持有任何卡。
- **过时前提：** 简报说 dev 正在运行并持锁。实际 dev1 在 16:39 已结束，复核时没有进程持有这把锁。我没有碰锁。
- **dev 分区：** 只重新生成事件数据来核对计数，**没有在 dev 上评估任何模型**。final 只计算了种子。
- **MLX：** 只在隔离副本里用 CPU 做单元测试和前向，H3 诊断只读权重，没有训练，没有写 `artifacts/`。
- **独立性局限：** 我和作者都是 Claude，卡的参数备注写着「排除 claude 系列作者」。本会话与作者没有共享上下文，也没参与编写，但是否足够算非作者，由一级判断。
