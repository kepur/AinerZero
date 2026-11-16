# P262（代审）：P261 S6 预登记入口修复的非作者对抗复核

> 一级 claude 照子代理最终回复原文落盘（HTML 转义已还原）。

**结论：打回。必修 1 项（R1），应修 3 项（S1–S3），建议 6 项（I1–I6）。**

- **R1 必修**：报告里的 `verify_seconds` 只有报告自己写着，没有任何原始文件能对照。只改这一个字段（616.0 改成 515.0，仍是正的有限数，也和 `elapsed_s` 一致），构建器就在真实探针上写出了预登记，评测外推正好等于 3600。一级点名要确认的绕过方式里，"改报告里的耗时"能绕过；"删格""改 sets"已被拦住。
- **S1 应修**：作者的测试漏掉了 5 个非等价变异：T/R 共同挑选、final 的 6h/1h 字面钉、probe 账本上限、挑选编号范围、first_ok。这 5 个都能被我写的复核测试杀死（见 §5）。
- **S2 应修**：两条"等于上限"的边界测试实际没有取到相等值（3599.999999999999 和 21599.999999999996），所以把 `<=` 改成 `<` 的变异能存活。
- **S3 应修**：`source_sets` 的语法过滤允许任意属性链，而且它在源码身份核对之前就执行 `run_s6p1.py` 里的 SETS 表达式。实测 `().__class__.__base__.__subclasses__()` 被执行了。

P262 卡面的验收项全部满足：
- F1–F3 原反例全部拒绝；
- 真实探针 84 个文件的闭包通过，重算的门与报告逐值一致，按原式以评测 4212.693333 > 3600 拒绝，零写入；
- 合成正例能生成预登记，正式 manifest 冻结了构建器和 helper；
- 42 个数值文件的摘要仍是 `839063…d610d3`；
- 我设计的变异中有 7 个被作者测试杀死；
- 102 项测试通过；全程没有导入 MLX。

R1 是一级额外要求确认的项，修复很小（见 §R1）。如果一级认定"冻结评审时人工核对报告 SHA `4a79000a…`"就是接受的防线，R1 可降为应修，结论相应改为建议通过。

复核者：P262 代审子代理（Claude），没有参与 P261 实现，也没有参与构建器初版。纯 CPU，没有导入 MLX，没有训练、评测或生成任何 s6p1-* 世界。实盘只读，只在本目录写；没有 stash、checkout、reset、commit 或 push。隔离副本在 scratchpad 的 `.../scratchpad/p262sub/{base,live,cases,mut,rev}` 下。

---

## 1. 被审文件的精确身份

命令：`git --no-optional-locks rev-parse HEAD`，以及对工作树跑 `shasum -a 256`。原始输出见 `evidence/01-identity.txt`（开始时）和 `evidence/08-identity-end.txt`（结束时）。

```
a33d34b5cb8d06800f584a0abcfd788d16f80fcb   (HEAD，开始与结束一致)
0dd9d3be32fd49032b54df73fef3e895d9f3fff28349f3a41a21fb5087438731  reports/V9-S6-PHASE1/make_prereg.py      (工作树 M；HEAD 版 f2bd464f…)
208f6c4b5361f420b7c69c166319f2ab26d266239b709439f3471cee249f88b6  reports/V9-S6-PHASE1/prereg_evidence.py  (未跟踪)
795dc4c50bdf0406b0074119d068830fa2ff31ea9cc1fc528067468e667e1692  tests/v9/experiments/test_s6_prereg.py   (未跟踪)
10998013257f8c781f265b3a150cddc3a838f7fc565aa362d46fdf36fa10de0c  reports/V9-S6-PHASE1/run_s6p1.py        (= HEAD)
116f45ef23bcbf5e91cf64bb800db15eba9ff52da5a49a3dbcb3c5de4e1d0885  reports/V9-S6-PHASE1/verify_s6p1.py     (= HEAD)
08cc78493c865981583924a1bf217ae0be890ffc6478b446284f72e2ce1baa2e  src/ainerzero/v9/experiments/s6/cells.py (= HEAD)
4a79000a646e8a817bd2916dd0471fb9ca221b2dac9d30fd67d00bc01ac16e9e  reports/V9-S6-PHASE1/probe/EVAL-probe.json
```

这三个被审文件的 SHA 与 P261 `metrics.json` 登记的一致，复核开始和结束时都没变。

实盘 42 个文件的数值 manifest 我用 `python -B -I` 只读算过一遍（`evidence/03-live-numerical-manifest.txt`）：`LIVE_WORKTREE_NUMERICAL_MANIFEST 42 839063099cd798e73fa3e26cdaba3b859b2d63360f4ed8d3cc2ec54e25d610d3`。它和真实报告、训练账本里的 `code_manifest_sha256` 相同。

复核期间其他写者产生了几处改动，都不在本审范围内，被审构建器也没有引用它们：
- 新增 `reports/V9-S6-DESIGN/DESIGN-r3.md`（07:07）；
- 新增 `reports/V9-S6-PHASE1/prereg_identity.py`（07:09，sha256 `0029a207…`）；
- 修改 `tests/v9/experiments/test_s6_cells_native.py`（07:10）；
- 07:04:41 实盘出现 `reports/V9-S6-PHASE1/__pycache__/{make_prereg,prereg_evidence}.cpython-312.pyc`。不是我写的：我的每次运行都带 `-B`，而且都从副本加载（`ALL_FROM_COPY True`）。

另外，并行的 `prereg-fix-review/REPORT.md`（gemini-w9x4，07:06）结论是建议通过，但没有测"把耗时改小"这种篡改。我没有沿用它的结论。

隔离副本有两类：
- `base`：`git archive HEAD src tests pyproject.toml reports/V9-S6-PHASE1 reports/V9-S6-DESIGN | tar -x`，再拷入三个被审文件并核对 SHA。
- `live`：`git clone --depth 1 --no-local file://<repo>` 后做 sparse checkout，因此保留了真实提交 a33d34b；再拷入三个被审文件、真实报告和 `artifacts/v9/s6/phase1/probe`。87 个拷入文件全部通过 `shasum -c`。

每个用例都用 `cp -Rc` 单独克隆一份副本。每次运行都打印模块来源；所有运行的 `ALL_FROM_COPY` / `MODULES_FROM_CASE_ROOT` 都是 True，`MLX_IN_SYS_MODULES` 都是 False。

## 2. P259 的 F1–F3 原反例

脚本是我写的 `evidence/real_probe_sub.py`：阻断 MLX 导入；用 audit hook 记录所有写操作；在构建前后对整棵树（含 .git）做 SHA 比较。它在 live 克隆的副本里用 `runpy` 执行真实的 `make_prereg.py` 主入口。

### (a) 把 P259 的原始反例报告原样放到探针路径

12 个 P259 用例各跑三种模式：
- raw，且删掉全部原始产物；
- norm（只把 third_party 改成本环境版本），且删掉原始产物；
- norm，保留真实产物。

另加一种"补全"模式：用真实报告补齐 P259 缺的键，保留 P259 原来的缺陷字段和占位摘要。输出在 `evidence/p259-cases/*.out`（共 61 次运行），缺键清单在 `evidence/p259-cases/missing-keys.txt`。

结果：全部 `REFUSED`，`OUTPUT_EXISTS False`，`CHANGED_DURING_BUILDER []`。
- 原始报告都缺 `descriptive/elapsed_s/prereg_sha256/selection`，先被 `probe eval report is incomplete` 拒绝；
- 补全后被 `report sets: incorrect key set` 拒绝（P259 的 sets 里没有 smoke）；
- wrong_set 那一例被 `report set` 拒绝。

### (b) 把每个缺陷单独移植到完整的真实报告和闭包上

这样拒绝原因只能是这个缺陷，而不是缺键或预算。原始输出摘录如下（`evidence/p259-cases/F*.out`）：

| P259 项 | 移植的缺陷 | 构建器原始结果 |
|---|---|---|
| F1 无产物 | 删除 artifacts/ | `REFUSED builtins.FileNotFoundError ...`，零写入 |
| F1 空门＋只给汇总 | result={"valid":false,"gates":{}}，verify={"passed":true} | `report/raw verification: incorrect key set` |
| F1 汇总通过、单格失败 | 只改报告 | `report/raw verification/replay/E-r0/passed: value/type differs` |
| 同上，连原始 verify.json 一起改并重绑哈希 | | `replay passed: value/type differs` |
| F1 passed="false" | 改原始文件并重绑哈希 | `verify passed: value/type differs` |
| F1 缺 schema | | `probe eval report is incomplete` |
| F1 git_head=null | | `invalid report git_head` |
| F1 git_head 指向不存在的提交 | | `cannot read committed source tree 1111…` |
| F1 mlx 版本 0.32.2 | | `report third-party versions/mlx: value/type differs` |
| F2 账本是旧代码 | 账本 code_manifest_sha256=0…0 | `training/evaluation/current code identity: value/type differs` |
| F2 账本多一行旧代码 | 新增一行：已关闭、0 格、代码 f…f | 同上 |
| F2 账本 git_head 指向不存在的提交 | | `cannot read committed source tree 1111…` |
| F2 报告代码 SHA 不同 | | `report code SHA: value/type differs` |
| F3 负耗时 | 训练 −500 ×6，verify/eval −100 | `report training seconds: expected finite positive number` |
| F3 零耗时 | | 同上 |
| F3 伪增 6 个 *-r999 格 | train_seconds 和 cells_sha256 都加 | `report cells: incorrect key set` |
| F3 NaN / Inf | JSON 字面量 NaN、Infinity | `verification seconds` / `evaluation seconds: expected finite positive number` |

以上全部 `OUTPUT_EXISTS False`、`CHANGED_DURING_BUILDER []`。**F1–F3 原反例全部被拒绝。**

## 3. 真实探针（live 克隆副本，报告 SHA `4a79000a…`）

命令：`PYTHONPATH=<case>/src python -B evidence/real_probe_sub.py <case> none`。原始输出（`evidence/real-probe/none.out`）：

```
BUILDER_OUTCOME REFUSED prereg_evidence.EvidenceError: 预计超出上限：训练 18072.250000 秒（上限 21600.0），评测 4212.693333 秒（上限 3600）
OUTPUT_EXISTS False
WRITE_EVENTS [只有三次 git 子进程：rev-parse / status --porcelain(42 个路径) / archive a33d34b…；没有任何写模式的 open]
TREE_FILES 908 CHANGED_DURING_BUILDER []
MLX_IN_SYS_MODULES False
```

完整性核验确实先通过了（`evidence/real-probe/closure.out`，只读脚本 `real_closure_sub.py`）：
- `CLOSURE_FILES 84`（json 11、npz 1、safetensors 72）；
- `SCIENCE_ALL_PASS True`，`LEDGER_S 3275.28`；
- `GATES_RECOMPUTED_EQUAL_REPORT True`、`DESCRIPTIVE_EQUAL True`：这是我自己写的循环，从原始 errors.npz 独立重算；
- 手算 `HAND_BUDGET train 18072.25 eval 4212.693333333334`；
- `REPORT_TIMES verify 616.0 eval 19.6 elapsed 645.0 gap 9.4`。

**按原式拒绝、零写入，确认成立。**

### 绕过尝试

每个用例用独立副本，原始输出在 `evidence/real-probe/<名>.out`：

| 篡改 | 结果 |
|---|---|
| 报告删掉 G-r0（cells_sha256 和 train_seconds 都删） | `report cells: incorrect key set` |
| 删除原始 cells/G-r0 目录 | `raw cell directory set` |
| 加 6 个 *-r999 格 | `training times: incorrect key set` |
| 报告里 P-r0 的训练秒数改小 | `cell/report time: value differs` |
| sets.final 的 G 重复数 3→1 / eval_limit 改 9999 / worlds 减半 | `report sets/final/...: value differs` |
| config 和 sets.probe 的 worlds 一起翻倍 | `report sets/probe/worlds/0: value differs` |
| 协同改写 6 个 cell.json、账本和报告绑定（训练时长 ×0.5） | 闭包通过，但评测仍超限：训练 9294.3、评测 4212.69 → 拒绝 |
| verify_seconds 改成 0、负数、字符串，或删掉该键 | 拒绝（正有限数检查 / incomplete） |
| elapsed_s 改成 3600.5 | `inconsistent/excessive eval wall clock` |
| eval_seconds 19.6→1.0 | 拒绝（评测 3761.33） |
| **verify_seconds 616.0→515.0（只改这一个字段）** | **`BUILDER_OUTCOME WRITTEN`，`OUTPUT_BUDGET {... "estimated_eval_s": 3600 ...}`，写出 `PREREG-candidate.json`** |
| verify_seconds 616.0→516.0 | 拒绝（3606.03） |
| **verify_seconds→400.0 且 elapsed_s→430.0** | **`WRITTEN`，estimated_eval_s 2902** |

两个被接受的预登记里，`probe_report_sha256` 分别是篡改后的 `495e2982…` 和 `1868f3c3…`，不是 `4a79000a…`。合成夹具上也复现了同样的情况（`test_c1`：3033→2433）。原因和修复见 §R1。

## 4. 合成正例：用的是 `test_s6_prereg.py` 自己的合法夹具（预算内）

命令：`P262_DUMP=evidence/04-synthetic-positive-prereg.json python -B evidence/run_tests_sub.py <rev 副本> <basetemp> <副本>/tests/v9/experiments/test_p262_sub_review.py -rA -k "test_p262_sub_review or test_complete_probe"`。原始输出 `evidence/04-reviewer-tests.out`：`19 passed, 101 deselected`。

作者的 `test_complete_probe_with_failed_science_accepted` 通过：科学门失败也被接受，预算外推为 16618 / 3033。生成的预登记已落盘为 `evidence/04-synthetic-positive-prereg.json`，摘要在 `04-synthetic-positive-summary.txt`：

- `manifest` 共 45 个文件：42 个数值文件，加上 `DESIGN-r2.md` `ef0ea63f…`、`make_prereg.py` `0dd9d3be…`、`prereg_evidence.py` `208f6c4b…`。**构建器和 helper 已被冻结。**
- `code_manifest_sha256 = 839063…`；42 个条目在正式 manifest 里逐值相同；数值 manifest 不含构建器和 helper（由 `test_r0` 断言；真实克隆里 `FORMAL_MINUS_NUMERICAL` 也正好是这 3 个文件）。
- final 启动时会对整个 `pre["manifest"]` 做 check_manifest 和 git 干净检查（`run_s6p1.py:92`、`:99`）。所以以后改动构建器或 helper 会让这份预登记失效。这是预期行为。

我另外加的用例都在 `test_p262_sub_review.py` 里。每条都在作者夹具已被接受的基线上只注入一个缺陷，并断言具体的拒绝消息：
- 合法情况，应接受：r1 两行已关闭的账本（续跑）；r2 账本的 git_head 等于 HEAD。
- 应拒绝：
  - r2 账本里记录的提交的代码与当前不同；
  - r3 账本总时长超过 probe 上限；
  - r4 T 和 R 的挑选不同；
  - r5 挑选编号越界；
  - r6 存在 `*.aborted-1` 目录；
  - r7 证据文件是指向仓库外的符号链接；
  - r8 counts 是浮点类型；
  - r9 contact share 大于 1；
  - r10 pools 多出一个键；
  - r11 eval 墙钟 3600 接受、3600.01 拒绝；
  - r12 已提交的 runner 把 final cap 改成 12h；
  - r13 first_ok=False 但 passed=True。

以上全部符合预期。c1–c3 只是记录现有行为，不是要求，见 I6。

## 5. 复核者变异（只在隔离副本里改生产 validator）

命令：`python -B evidence/mutate_sub.py <base> <work> evidence/mutations`。做法：每个变异先 APFS 克隆一份 base，做一次精确的单次字符串替换，然后跑**作者原封不动的测试文件**。原始输出 `evidence/05-mutations.out`，汇总在 `mutations/results.json`；每个变异的源码、diff 和 pytest.log 在 `mutations/<名>/`。

| 变异 | 作者测试 | 失败用例（全部是 DID NOT RAISE 或断言失败） | 判断 |
|---|---|---|---|
| X1 `value > 0` 改成 `>= 0` | **杀死**（4 个失败） | zero-eval、timing-round-zero、duration[0-*] | |
| X2 不核对报告里的提交 | **杀死** | git-head | |
| X3 去掉 cell 到 pool 的摘要链接 | **杀死** | raw[pool] | |
| X10 int 位置接受 float | **杀死** | replicate-float ×2 | |
| X12 helper 不进冻结 manifest | **杀死** | complete_probe（断言 helper 在 manifest 里） | |
| X13 去掉 verify+eval≤elapsed | **杀死** | report[clock] | |
| X14 closed 改成真值判断 | **杀死** | raw[truthy-closed] | |
| X4 去掉 T/R 共同挑选检查 | 存活 | — | **非等价**，被复核测试 r4 杀死 |
| X5 去掉 final 6h/1h 字面钉 | 存活 | — | **非等价**，被 r12 杀死 |
| X6 去掉 probe 账本上限 | 存活 | — | **非等价**，被 r3 杀死 |
| X7 去掉挑选编号范围检查 | 存活 | — | **非等价**，被 r5 杀死 |
| X11 去掉 first_ok 检查 | 存活 | — | **非等价**，被 r13 杀死 |
| X8 去掉写前的证据复查 | 存活 | — | 只在并发竞态下才有差别，单进程下等价 |
| X9 评测预算 `<=` 改成 `<` | 存活 | — | 只在浮点恰好相等时有差别；但作者的 "equal" 用例实际并不相等（见 S2） |
| X15 去掉 git status 干净检查 | 存活 | — | 字节上等价：HEAD 归档已逐字节核对过，差别只在暂存区或文件模式位 |

作者测试杀死了我 15 个变异中的 7 个，满足"至少 4 个"的要求；作者自己的 M1–M6 也都被杀死（见 P261 记录）。5 个非等价的存活者，我把复核测试分别跑在对应的变异副本上（`mutations/<名>/reviewer-tests.log`），结果都是 `DID NOT RAISE EvidenceError`，说明它们确实非等价。

有一处要说明：r4、r5 的第一版没有同步改报告里的 selection 统计，结果变异体仍被 `selection statistics` 拒绝。改成"一致的伪造者"写法（同时重算 selection）之后，变异体才被接受。

## 6. 复跑 test_s6_prereg.py

在 base 隔离副本里运行，用项目默认的 conftest，阻断 MLX 导入。命令：`PYTHONPATH=<base>/src python -B evidence/run_tests_sub.py <base> <basetemp>`。原始输出 `evidence/06-tests-baseline.out`：

```
102 passed in 62.02s (0:01:02)
ALL_FROM_COPY True
MLX_IN_SYS_MODULES False
PYTEST_RC 0
```

---

## R1（必修）：报告里的 verify/eval 计时没有锚点，改一个数就能绕过预算闸

```
reports/V9-S6-PHASE1/prereg_evidence.py:352:     verify_s = number(pr['verify_seconds'], 'verification seconds')
reports/V9-S6-PHASE1/prereg_evidence.py:353:     eval_s = number(pr['eval_seconds'], 'evaluation seconds')
reports/V9-S6-PHASE1/prereg_evidence.py:354:     elapsed = number(pr['elapsed_s'], 'report elapsed seconds')
reports/V9-S6-PHASE1/prereg_evidence.py:355:     require(verify_s + eval_s <= elapsed + .15 and elapsed <= cfg['eval_limit_s'], 'inconsistent/excessive eval wall clock')
reports/V9-S6-PHASE1/prereg_evidence.py:366:     est_eval = 1.30 * (pr['verify_seconds'] * n_final / 6
```

问题在于三个计时都只有报告自己写着：
- `verify_seconds`、`eval_seconds`、`elapsed_s` 只存在于被审报告里。运行器只在进程内测量（`run_s6p1.py:282-284`），没有落盘的原始对应物。
- 构建器对它们只做了三者之间的不等式检查，所以把其中一个改小总能通过。
- 对比训练耗时：训练耗时同时写在 cell.json、账本和报告里，要伪造得协同改 8 个文件；评测这边只需改一个数。
- final 启动时不会再读探针报告：正式 manifest 只有 42+3 个文件，`probe_evidence` 只是记录。
- 实测把 616.0 改成 515.0 就写出了预登记（§3）。

helper 的文档写明它不防恶意作者（`prereg_evidence.py:3-4`），P261 报告也写了"原报告没有单独落盘的verify/eval原始开始结束时间"。但预算是目前唯一挡住 final 的闸门，只改一个数就能通过，代价太低。

**最小修复**（不改运行器、门、上限或公式）：
- 构建器必须带一个外部锚点：可以是必填参数 `--probe-sha256`，也可以是写在构建器里的探针报告 SHA 常量（随构建器一起冻结、一起复核）。
- 在读取任何内容之前，先用报告字节和锚点比较，不一致就拒绝。
- 锚点的来源必须是 eval 完成时、由非构建器运行者落下的记录。本次探针的值是 `4a79000a646e8a817bd2916dd0471fb9ca221b2dac9d30fd67d00bc01ac16e9e`，已出现在 P261 `metrics.json` 和 relay 报告里。
- 补一条测试：只把报告里的 `verify_seconds` 改小，应拒绝且零写入。

同一个锚点也顺带堵住了"协同改写 cell、账本和报告"这一类（§3 里训练 ×0.5 那一例）。

## 应修

**S1 测试缺口。** X4、X5、X6、X7、X11 五个非等价存活者需要被作者测试覆盖。可以直接采用 `evidence/test_p262_sub_review.py` 里的 r3、r4、r5、r12、r13：它们复用作者的夹具，并断言具体消息。

其中 X5 最要紧，因为构建器里只有下面两行把 6h/1h 钉死：
```
reports/V9-S6-PHASE1/prereg_evidence.py:120:     same(sets['final']['train_cap_s'], 21600.0, 'final training cap')
reports/V9-S6-PHASE1/prereg_evidence.py:121:     same(sets['final']['eval_limit_s'], 3600, 'final eval cap')
```
作者的 `final-cap` 用例只改了报告，在"报告与源码比较"那一步就被拒，从来没走到这两行。

另外，作者用 `pytest.raises((ValueError, KeyError, OSError, SystemExit))`（`test_s6_prereg.py:230`）笼统接住异常，用例可能因为无关原因通过。建议每个用例断言具体的拒绝消息。

**S2 边界测试名不副实。**
```
tests/v9/experiments/test_s6_prereg.py:334:         verify = 3600 / (1.30 * (28 / 6)) - 4 * 100
```
这样算出的评测估计是 `3599.999999999999`，训练估计是 `21599.999999999996`（`evidence/05-boundary-float.txt`），都没取到上限本身，所以 X9 能存活。应改用能精确等于上限的输入，或者把用例名改成"略低于上限"。

**S3 `source_sets` 能执行的范围太宽，而且执行早于源码身份核对。**
```
reports/V9-S6-PHASE1/prereg_evidence.py:100:     allowed = (ast.Expression, ast.Dict, ast.Constant, ast.Name, ast.Load, ast.Attribute,
reports/V9-S6-PHASE1/prereg_evidence.py:101:                ast.Call, ast.keyword, ast.Tuple, ast.List, ast.BinOp, ast.Mult,
reports/V9-S6-PHASE1/prereg_evidence.py:111:             env[name] = eval(compile(expression, '<S6 config only>', 'eval'), env)
reports/V9-S6-PHASE1/prereg_evidence.py:265:     sets = source_sets(repo)
reports/V9-S6-PHASE1/prereg_evidence.py:274:     head = committed_identity(repo, code, pr['git_head'])
```
`evidence/07-source-sets-dunder.out` 里实测输出 `EVALUATED_DUNDER_CHAIN_RESULT 436`：工作树里未提交的 runner 改动，会在身份核对之前被执行。

修复方法：
- `Name` 只允许 dict 和 C；
- `Attribute` 只允许 `C.<大写名>`，禁止以下划线开头的属性；
- 把 `source_sets` 挪到 `committed_identity` 之后。

影响面不大：能改 runner 的人，到 final 时这份代码本来也会被执行。但它与文档里"不执行模块体"的说法不符。

## 建议与说明（不阻塞）

- **I1** 运行器续跑时会把未完成的格保留为 `cells/*.aborted-N`，构建器会以 `raw cell directory set` 拒绝这种探针（r6）。这是偏保守的拒绝；当前探针没有这类目录。将来若有续跑过的探针，需要一级裁决。
- **I2** MLX 版本记录为 `"unknown"`，这是运行器原有的语义（`run_guard.py:163-176`）。final 启动时比较的是 `"unknown" == "unknown"`，等于 MLX 版本实际上没被钉住。这不是 P261 的问题；复核期间新出现的 `prereg_identity.py` 似乎在处理它，我没审。
- **I3** 给一级的信息：评测外推把整个 `verify_seconds` 按 28/6 线性放大，但其中的复训固定只有 2 个（`verify_s6p1.py:29: RETRAIN = (("E", 0, 0), ("P", 0, 0))`），不随格数增加，所以这个外推偏保守。本复核不建议改公式，是否改由一级或用户决定。
- **I4** `errors.npz` 由 `np.load` 从路径重新读了一次（`prereg_evidence.py:335`），没有用已经算过哈希的那份字节；`cell.json` 的 SHA 比较（`:289`）也是二次读取。末尾的 `closure.unchanged()` 挡住了大部分情况，只剩理论上的竞态窗口。建议改为 `np.load(io.BytesIO(closure.read(...)))`。
- **I5** `--design` 只要求在仓库内，没有钉死为 `DESIGN-r2.md`。
- **I6** 没有检查多余的键：cell.json 的多余键（c2）和报告顶层的多余键（c3，例如 `late_violations`）都会被接受。对 probe 无害，记录在此。

## 规则遵守

- 每次运行都阻断 MLX 导入，并打印 `MLX_IN_SYS_MODULES False`。
- 没有训练、评测或生成世界。git 只做只读操作：rev-parse、`status --no-optional-locks`、clone 到 scratch。
- 所有篡改都只发生在 scratch 副本里。实盘只写了本目录，没有改动或挪动其他会话的文件。
- pytest 的临时目录用 `--basetemp` 指到 scratch。

## 总结（≤15 行）

1. 被审 SHA：make_prereg `0dd9d3be…`、prereg_evidence `208f6c4b…`、test `795dc4c5…`；HEAD `a33d34b`；开始和结束时一致。
2. P259 F1–F3：12 个原始反例共 61 次运行，再加 17 个单独移植到真实完整闭包上的缺陷，全部拒绝，零写入。
3. 真实探针：84 个文件的闭包通过，门的重算一致，按原式以评测 4212.693333 > 3600 拒绝，整棵树（含 .git）没有变化。
4. 删格、改 sets、伪增格、零/负/NaN/Inf、协同改训练耗时都被拒绝；但**只把报告里的 verify_seconds 改成 515.0 就能写出预登记**。这是 R1 必修，修法是用外部记录钉住报告 SHA `4a79000a…`。
5. 合成正例能生成预登记；正式 manifest 有 45 个文件，冻结了构建器和 helper；42 个文件的数值摘要 `839063…` 未变。
6. 我设计了 15 个变异，作者测试杀死 7 个；5 个非等价存活者能被我的复核测试杀死（S1，其中 6h/1h 字面钉没有测试覆盖）；另有 3 个等价或近似等价。
7. 作者的 102 项测试全部通过，模块都从副本加载，没有导入 MLX。
8. 应修 S1–S3（补测试、边界值、source_sets 的执行范围与顺序）；建议 I1–I6 不阻塞。
9. 若一级认定"人工核对报告 SHA"就足够，R1 可降为应修，结论改为建议通过。
