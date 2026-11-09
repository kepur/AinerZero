# S3 第二阶段预登记后复查（6edc68d..95401b7）

复核者 `claude-s3rev-1109`（独立会话），2026-11-09。被审版本是 `95401b7`，复核结束时 HEAD 未变，冻结清单里的文件没有改动。没有训练，没有运行 MLX，没有读 dev 的结果，没有写 `artifacts/`，没有改被审文件。

## 结论：可以读 final

没有必修项。冻结是一致的，你要我确认的 5 点都成立。

**有一组条件我没法替你确认**，因为你让我不要读 dev 的结果。读 final 之前，请你自己核实：

| 条件 | 怎么看 |
|---|---|
| dev1 正常结束，没有触发 1.5 小时上限 | 退出码 0 |
| 合法性门通过 | `dev1.json` 的 `result.valid` 为 true |
| 运行中清单没变 | `dev1.json` 的 `late_violations` 为空 |
| 冻结文件不动 | 解读 dev 时不要改 `DESIGN-r2.md` 或清单里的其他文件，写到别处；改了 final 启动时会被拒，不扣次数，但要重新冻结 |

命令要点：`python -I -X pycache_prefix=<新建目录>`，`--stage final --approval <批准行>`，`--report` 用一个新路径。目前 `final-final` 目录和 `FINAL_READ_ONCE.json` 都不存在。

## 必修项

无。

## 应修项

都不阻塞读 final。

| # | 问题 | 位置 | 证据 |
|---|---|---|---|
| 1 | 账本里的条目不是字典时（比如 `[1]`）抛 `AttributeError`，不走 `GuardError` 的清理分支，会留下空目录和空报告。不扣次数，没有东西被误删。`run_guard.py` 已冻结，不必为此改动 | `run_guard.py` `consume_dev_use`；`run_phase2.py:261` | `stub_harness.txt` D6 |
| 2 | `test_dev_and_final_seeds_were_never_used_before_the_freeze` 只断言分区名，名字说得比实际测的多 | `test_s3p2_replay_analysis.py:473` | 读代码 |
| 3 | `use-id` 里的 `.` 只有 MLX 原生测试（`dev.1`）在拦，纯 CPU 的账本测试加一个用例，默认入口也能抓到 | `test_s3_run_guard.py` | `mutants_cpu.txt` n03 |

## 逐项

### 1. 分区替换

**彻底，没有漏网路径。**

- 运行器测试的每个假根目录都经过 `_make_root`（`test_s3p2_runner_guards_native.py:79`），7 处调用（含 `root` fixture）都走它；替换用 `assert count == 1`，源码改了会立刻报错。
- 进程内的 `run_module` 夹具只用自定义命名空间 `test-s3p2-runner` 调辅助函数，没有调 `main`。
- 全仓库（`src`、`tests`、运行器、`make_prereg`、`make_tables`）里，旧名字只剩 `analysis_p2.py` 的注释。
- 作者最近几轮测试留下的 `build_calls.jsonl` 里只有 `standin-*`（dev 4、final 4、train 8），没有 `s3p2b`。这是我在跑自己的测试之前收集的，之后 pytest 轮转把它们清掉了。

**改名没有破坏别的东西。** `check_stage_namespace` 四个分区互不相同，预登记的 `namespaces` 与代码一致，纯 CPU 测试 122 项全过（进程内未加载 MLX）。`s3p1-*`、`s3p2-*`（含作废的 dev、final）、`s3p2b-*` 共 21 组、14300 个种子零碰撞（`freeze_check.txt`，只算种子，没生成世界）。

**探针结果在新命名下仍然有效，我同意。** 探针只用 `s3p2-train` 和 `s3p2-probe`，两个名字没动；`probe_report_sha256` 与文件一致，选定容量 64 与预登记一致。训练路径自 r2 以来字节码不变：`run_phase2.py` 只有 `check_request` 和 `main` 变了，其余 22 个函数相同；`arms_p2_mlx.py`、`replay.py` 全同；`analysis_p2.py` 只有模块级的分区名。

你比我的建议多做的这一步（换成 `s3p2b-*`）我赞成：这样 final 确实是冻结后才首次生成，不需要靠「模型太弱」来辩护。

### 2. `valid_use_id` 与 `check_request`

- `valid_use_id` 用 `re.fullmatch(r"[A-Za-z0-9_-]+", ...)`，只接受 ASCII，尾部换行也会被拒（`run_guard.py:263`）。
- `check_request` 对所有阶段都校验 `use-id`（`run_phase2.py:209-212`），排在占报告之前。
- 用桩 `mlx` 跑真实运行器文本（见下）：8 种非法 id（首尾空白、`a/b`、`../x`、`dev.1`、空串、`dev1\n`、`é`）× 4 个阶段，**32 组全部被拒，什么都没有留下**（`stub_harness.txt`）。合法 id 在 smoke、probe 上正常通过。

### 3. 清理逻辑

**不会删到不该删的东西。** 只有本次运行自己刚建的目录和报告会被删：

- `out` 在 `:252` 确认不存在、`:255` 新建，`:262` 的 `rmdir` 只能删空目录。
- `report` 由 `claim_report` 以独占方式创建，已存在的路径（含符号链接）在那一步就被拒，轮不到 `:263` 的 `unlink`。
- `GuardError` 都发生在账本或标记写入之前，所以被拒时什么都没记。

实测（真实运行器文本，桩 `mlx`，假根目录）：

| 用例 | 结果 |
|---|---|
| 次数用完、重复 id、账本损坏、final 已读 | 目录和报告都清掉，账本、标记内容不变 |
| 账本损坏修好后重试 | 正常通过（上轮的空壳问题解决了） |
| 已有报告 | 被拒，内容保留 |
| 已有运行目录（含文件） | 被拒，文件保留 |
| 报告路径是指向重要文件的符号链接 | 被拒，链接和目标都保留 |
| 悬空符号链接 | 被拒，链接保留 |
| 报告在新建的嵌套目录里 | 报告删除，父目录留下（无害） |

桩的做法：一个只有版本号、`nn.Module` 和 `set_default_device` 的 `mlx` 包，放在仓库外，运行器到记账后的第一条 MLX 语句就退出。这样运行器文本一字未改，启动序列全部真实执行，不占 CPU，也碰不到 dev/final 数据。

### 4. `PREREG-r1.json`

| 项 | 结果 |
|---|---|
| 文件数 | 37（s3 15、s2 4、其他 src 16、运行器、DESIGN-r2） |
| SHA 与提交 `95401b7`、工作区 | 全部一致 |
| 用 `build_manifest` 从提交重建 | 与预登记**完全相同**，没有多也没有少 |
| 冻结后清单文件的改动 | 无 |
| 种子、步数、批大小、回放比例、学习率、裁剪、批次种子、随机键、`perm_seed`、种子偏移、温度、λ、dev 上限、分区、时限、设计稿路径 | 14 项全部与运行器一致 |
| 12 项门槛 | 与 `analysis_p2.py` 全部一致 |
| 第三方版本 | numpy 2.5.3、mlx 0.32.2，与当前环境一致（mlx 版本从包元数据读，未导入） |
| 探针报告 SHA、容量 | 一致，64 |
| 批准行 | 存在 |

§3 也补齐了初始化种子、`default_rng` 和批次种子，逐位复现的信息够了。

### 5. dev 启动合法

只读了账本、启动参数和报告头字段，**没有读 `cells`、`retrieval`、`result` 或日志里的结果数字**（`dev_start_check.txt`）。

| 项 | 结果 |
|---|---|
| 账本 | 1 条，`dev1`，用途「第二阶段预登记后的首次 dev：彩排全部门与证据链」，22:57:53 |
| 时序 | 预登记提交 22:57:36，dev 启动 22:57:53，在冻结之后 |
| 启动参数 | `python -I -X pycache_prefix=<新目录>`，`--stage dev --use-id dev1 --purpose …` |
| 锁 | 由运行进程 48547 持有 |
| 报告头 | `stage: dev`，`git_head: 95401b7`，`prereg_sha256` 与文件一致，第三方版本一致，容量 64，种子 1–3 |
| 数据规模 | 训练 1600/1600，评测 100/100，符合登记 |
| 日志 | 复查时 33 行，无 `Traceback`、无 `GuardError` |
| final | 未读：标记和运行目录都不存在 |

## 纯 CPU 变异

新代码上 10 个，抓到 9 个（`mutants_cpu.txt`）。漏掉的 n03（允许 `.`）由原生测试的 `dev.1` 用例覆盖，这轮没跑（应修 3）。

## 未验证

| 项 | 原因 |
|---|---|
| dev1 的结果、是否正常结束、合法性门 | 你要求不读。见结论里的条件 |
| 含 MLX 的测试（`test_s3p2_runner_guards_native.py` 等） | 这轮不跑 MLX。启动和清理路径我用桩实测了；替身分区靠静态分析和残留日志。我判断不需要等 dev 结束再跑 |
| `s3p2b-*` 在冻结前从未生成 | 只能确认代码路径和现存残留。更早的 pytest 临时目录已轮转，无从审计 |

## 复现

证据在 `evidence/`。隔离副本是 `git archive 95401b7`，脚本都不导入 MLX。

| 脚本 | 内容 |
|---|---|
| `freeze_check.py` | 清单、字段、门槛、种子、字节码差异 |
| `stub_harness.py`、`launch.py`、`stubs/mlx/` | 真实运行器 + 桩 `mlx` 的拒绝和清理路径 |
| `mutants_cpu.py` | 10 个纯 CPU 变异 |
| `dev_start_check.txt` | dev 启动元数据 |

## 说明

- 我和作者同模型，盲点可能相关（§10 已提到）。
- 我的纯 CPU 测试让 pytest 临时目录再次轮转，作者那几轮的 `build_calls.jsonl` 已清掉，上面的统计是轮转前收集的。
