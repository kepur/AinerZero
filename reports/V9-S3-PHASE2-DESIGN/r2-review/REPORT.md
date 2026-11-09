# S3 第二阶段 r2 复查（相对 59ed20d）

复核者 `claude-s3rev-1109`（独立会话），2026-11-09。被审版本是 `6edc68d`。没有跑 dev/final，没有写 `artifacts/`，没有改被审文件。

## 结论：打回

只有 1 项必修，而且**只改测试和日志，不碰冻结清单里的任何文件**。修完并记入日志后可以直接冻结，不需要我再审代码。

r1 的 2 个必修项都修好了，你问的 5 点结论如下：

| 问题 | 结论 |
|---|---|
| 1 校验前扣次数 | C1、C2 现在都在记账前被拒。另试了 13 条路径，没有新的扣次数路径 |
| 2 结束时核对清单 | 成立：`check_manifest` 和 `check_loaded_modules` 都查，不一致判无效并清空 `claims` |
| 3 改动是否引入新问题；探针不重跑是否成立 | 没有引入新的语义问题。**探针不重跑成立**（训练路径字节码相同，见第 3 节） |
| 4 §3 能否重写 | 能。逐位复现还差两点，可选 |
| 5 假根目录测试有没有意义 | 有意义，文本替换本身没有削弱它。但它用了真实分区，这是下面的必修项 |

## 必修项

| # | 问题 | 位置 | 复现证据 | 怎么修 |
|---|---|---|---|---|
| 1 | **假根目录跑通测试用的是真实的 `s3p2-dev`、`s3p2-final` 种子。** `_tiny` 只替换了 STAGES 和 `clamp`，没有替换分区名，所以测试会生成并评测 final 的前 6 个世界（两族，共 24 个回合），绕过 `FINAL_READ_ONCE` 的语义，也违反 §5「final 冻结后才生成，只读一次」。这和第一阶段 `test_final_partition_refusal_by_default` 是同一类问题。模型只训了 4+2 步，看不出有用的信息，但每跑一次这个测试就发生一次，冻结后也一样 | `test_s3p2_runner_guards_native.py:41-51`、`:203`、`:228`、`:238`；`analysis_p2.py:18`；DESIGN `:168` | 代码路径：`_tiny` 不动分区名，运行器读 `G.NAMESPACES`。复核开始时我还看到作者最近一次运行的残留：`pytest-557/test_final_runs_once0/fake/`（`FINAL_READ_ONCE.json`、`final-final`，22:04:43，比提交早 17 秒）和 `test_dev_runs_through_the_path0/fake/`；同批的 `pytest-555` 假根目录里 `analysis_p2.py:18` 是真实分区名。这些目录后来被 pytest 的临时目录轮转清掉了（由我的测试运行触发），现已不存在。我没有打开过其中的结果 | 在 `_make_root` 里把假根目录 `analysis_p2.py` 的分区名换成替身。我在隔离副本里这样换过，242 项测试全过，说明可行。`RESEARCH_LOG` 记一笔：冻结前测试生成过这 24+24 个回合，用的是 4 步模型，无人读取结果。不需要换 final 分区 |

## 应修项

都不阻塞冻结。第 1、6 条只动测试；第 2、3、4 条动的是冻结清单里的文件，要做就在 `make_prereg` 之前做，不做也不影响结论。

| # | 问题 | 位置 | 证据 |
|---|---|---|---|
| 1 | 运行器还有 23 个变异漏网。分三类：**常量**（种子数、步数、批大小、裁剪、F2 批次种子、随机键、N 种子、初始化种子：p21、p22、p52–p57）；**数据流**（评测用软模式 p19、评测用训练分区 p30、F2 评测用 F1 世界 p62、F2 训练用 F1 令牌 p63、优化器被重置 p32、联合训练只用 F1 p24）；**守卫**（版本 p04、已加载模块 p03、分区校验 p07/p08、`max_uses` p09、最小样本 p25、Deadline p23、先校验后拿锁 p28；p29 基本等价）。这些都只影响以后改代码时的回归保护，现有代码我逐条读过，训练路径也与探针版本字节码相同 | `test_s3p2_runner_guards_native.py` | `mutations_runner.json`。低成本补法：在 `_tiny` 里加钩子记录 `build` 的（分区、标签、族）；`per_event` 上断言 `hard=True`；断言运行器常量；E2E 断言 `legality` 含 `min_sample_F1`；预置账本测 `max_uses` |
| 2 | `--use-id` 不限字符。`a/b` 建嵌套目录，`../../../../../escaped` 建到 `artifacts/escaped`，都通过校验并记账 | `run_guard.py:262`；`run_phase2.py:248-253` | `runner_order2_part2.txt` C12、C13。限定 `[A-Za-z0-9_-]+` 即可 |
| 3 | 在 `consume_*` 处被拒（次数用完、重复 id、账本损坏、final 已读）时已经建了运行目录、占了报告，不扣次数，但留下空壳。账本损坏修好后，同一个 id 重试会被「目录已存在」拦住 | `run_phase2.py:250-257` | C7、C8、C9、C11 |
| 4 | §3 逐位复现还差：模型初始化 `mx.random.seed(seed)`、批次生成器 `np.random.default_rng`、F1 批次不放回；§3 第 131 行写 `mx.random.key(seed)`，F2 实际是 `seed + 1000`（预登记写成「批次种子」，是对的） | DESIGN `:131`、`:138` | `make_prereg_check.txt` |
| 5 | `require_fresh_pycache` 的 10 秒容差内，篡改过的字节码仍能通过，运行时门槛读到 0.5。这是容差的固有窗口，属于诚实执行者模型之外，记一笔即可 | `run_guard.py:178-188` | C15（C14：更旧的字节码被拒） |
| 6 | 两个描述量的读出口径没有测试：`capacity_curve` 的 `drop`（g36）、`replay_minus_cn` 用 8 类（c05） | `analysis_p2.py:136` | `mutations_core.json` |
| 7 | 日志里「变异 100 个全部被抓到」只对你自己的变异集成立，建议注明。我这边 167 个漏 26 个（第 5 节） | `RESEARCH_LOG.md` `R20261109-S3-p2-r2` | — |

## 逐项

### 1. 必修 1：运行目录

`run_phase2.py:250` 的检查排在 `:252` 占报告、`:253` 建目录、`:255-257` 记账之前。

假根目录重跑（替身分区，记账后立即退出的桩，`runner_order2*.txt`）：

| 用例 | 结果 |
|---|---|
| C0 对照：dev、final 正常 | 走到记账，账本 `dev1` / 标记写入 |
| C1 `dev-dev1` 已存在 | 拒绝，账本空，无报告 |
| C2 `final-final` 已存在 | 拒绝，无标记，无报告 |
| C3 缺用途、C4 报告已存在、C5 报告路径是目录、C6 报告不可写、C10 根路径是文件 | 全部拒绝，不扣次数 |
| C7 次数用完、C8 重复 id、C9 账本损坏、C11 final 已读 | 拒绝，不多扣（留空壳，应修 3） |

记账是启动序列的最后一步，之后的失败都是真正的运行时错误，这个顺序现在是对的。变异 p01、p33、p39、p66 都被抓到。

### 2. 必修 2：结束时核对

`:332` 同时查清单和已加载模块，`:335` 调用 `invalidated`，`valid` 置否，`claims` 全部置否，`late_violations` 进报告。`test_a_frozen_file_changed_during_the_run_invalidates_it` 用钩子在结束前改文件，变异 p17、p34、p35 都被抓到。

### 3. 新改动

**探针不重跑成立。** 函数级字节码对比（`diff_bytecode.txt`）：

| 文件 | 相同 | 改动 |
|---|---|---|
| `run_phase2.py` | 19 个函数，含 `train`、`per_event`、`build`、`conditions`、`pick`、`mixed`、`zero_state_penalty`、`summary` | `main`、`startup_checks`；新增 `check_request`、`f2_sampler` |
| `arms_p2_mlx.py`、`replay.py` | 全部（只改了文档字符串） | 无 |
| `analysis_p2.py` | 12 个函数 | `_stack`、`paired`、`h3_prime`、`evaluate`；新增 `invalidated` |

- `f2_sampler` 与 `59ed20d` 的内联逻辑：5 种条件 × 3 种子 × 3 阶段 × 25 个生成器，1125 批的回合和答案**完全相同**（`equivalence.txt`）。唯一差别是 C0 的 `buffer_episodes` 记 0，原来没有这个字段。
- HEAD 的 `evaluate` 跑探针的逐事件数据，与 `probe-p1.json` **零差异**。新增的 `claims` 为 H2 否、H2b 否、H3′ 是，`replay_minus_cn_8class` 为 0.708（0.678, 0.737）。
- 探针的作用是定容量和校准，结论只由 final 下，所以这些改动不影响探针的用途。

**新守卫的边界：**

| 项 | 结论 |
|---|---|
| `check_request` | 在占报告之前拒绝缺用途、id 带空白、错批准行。C3 不再留壳。p38、p39、p69、p70 都被抓到 |
| `require_fresh_pycache` | 比启动早 10 秒以上的 `.pyc` 被拒（C14），容差窗口内仍可通过（C15，应修 5） |
| `python -I` | dev/final 必需，p36 被抓到 |
| `valid_use_id` | 拒绝空串和首尾空白，不限路径字符（应修 2） |
| `claims`、`invalidated` | 语义正确。`claims` 只有整体有效才可能为真，H3′ 还需要自身两项检查。c01–c04 都被抓到 |
| `make_prereg.py` | 实跑：`--capacity 16`、`256` 被拒，64 通过；37 个文件进清单，含 DESIGN-r2；预登记里 14 项字段与运行器代码逐项一致（`make_prereg_check.txt`） |

应修 19（删锁文件再建）不改，我同意：需要持有者定期复查，超出诚实执行者模型，§10 已写明。

### 4. §3

能让别人写出功能等价的实现：优化器、裁剪、批大小、批次种子、回放、CN、N、联合训练、`perm_seed`、温度、λ 都有了。逐位复现还差应修 4 里的两三点，属于可选。

### 5. 假根目录测试与变异

**文本替换没有削弱测试。** `_tiny` 只改 dev/final 的规模和时限，以及 `clamp`，并断言每处恰好匹配一次，运行器代码改了会立刻报错。`CAPACITY = 16` 特意和默认的 64 不同，所以能抓到「忽略预登记容量」。它丢掉的只有真实规模的配置值（这部分由 SHA 钉住，见应修 1）。`clamp=True` 使 E2E 走不到真实分支，但 `f2_sampler` 的单元测试覆盖了 `clamp=False`。

**变异（先解析语法，无假击杀；基线 242 项连跑两次全绿）：**

| 组 | 变异数 | 抓到 | 漏掉 |
|---|---|---|---|
| 核心（`arms_p2_mlx`、`replay`、`analysis_p2`、`run_guard`） | 113 | 110 | 3（h26 等价变异；g36、c05 是描述量） |
| 运行器 | 54 | 31 | 23（应修 1） |

对照上一轮：核心组漏网从 18 个降到 3 个。运行器组上轮漏掉的 26 个里，**11 个现在能抓到**（p10–p18、p20、p31），包括 N 只读过去、CN 打乱、缓冲来源、8 类读出、容量取自预登记、A1 进实验、A3H 损失分发；剩下 15 个仍漏（p03、p04、p07–p09、p19、p21–p25、p28–p30、p32）。

## 未验证

| 项 | 原因 |
|---|---|
| 假根目录之外的真实 dev/final 运行 | 要等冻结后 |
| 真实规模下 `Deadline` 的触发 | 无训练，未测 |

## 复现

证据在 `evidence/`，隔离副本是 `6edc68d` 的 `src/`、`tests/v9/experiments/test_s3*.py`、`pyproject.toml`，加运行器、`make_prereg.py`、`probe-p1.json`、`DESIGN-r2.md`。**副本里的 `analysis_p2.py` 分区名已换成 `rv-*`**，所以我的运行不接触 `s3p2-*`。

| 脚本 | 内容 |
|---|---|
| `diff_bytecode.py` | 59ed20d 与 HEAD 的函数级差异 |
| `equivalence.py` | `f2_sampler` 行为对比，`evaluate` 对探针回归 |
| `runner_order2.py`、`runner_order2_part2.py` | 启动顺序对抗 C0–C15 |
| `mut_lib2.py`、`mutants_core.py`、`mutants_runner.py` | 167 个变异 |

## 说明

- **「零训练」的一点例外。** 第 5 点要求抽查这个测试，它本身会跑 4+2 步极小训练。我在隔离副本里、替身分区上跑了（含变异），没有训练真实分区或正式模型，权重也不落到 `artifacts/`。
- 读取探针 npz 是只读的。
- 作者运行的 final、dev 残留，我只确认过文件存在和分区名，没有打开其中的结果；我的测试运行后，pytest 轮转把它们清掉了，无法再复查。
- 我和作者同模型，盲点可能相关（§10 已提到）。
