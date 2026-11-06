# 既有测试问题四项修复（2026-11-06）

- **执行**：Claude 会话（由分批入库会话 f037a730 派出）。按 CLAUDE.md，Claude 是一级统筹；问题 1 的修复路线由本会话按一级职责裁定，理由见 §1.2。
- **来源**：`reports/git-batch-commit-20261105/PLAN.md` §4、§6 第 1–4 项。§6 第 5、6 项不在本任务范围内。
- **性质**：只改测试代码，另新增一个测试辅助模块。`src/`、`configs/`、冻结件和交付证据都没有改动。没有训练，没有真实模型运行，预算预留与实际都是 0。
- **提交**：只提交，不推送。

## 结论

- 前台跑全量 `tests/`：**3431 passed，0 failed，6 deselected**，退出码 0，用时 217.6 s（`logs/pytest_full_final.txt`）。
  - PLAN §4 的 7 条失败都消失了。其中 `test_preflight` 在实盘 git 工作副本里本来就能通过。
  - 没有新增失败。
- 全量运行前后，对实盘 `artifacts/ reports/ configs/ contracts/ docs/ scripts/ data/` 共 116,401 项做了 stat 对比：没有新增、删除，也没有内容或大小变化。
  - 唯一变化是 `artifacts/v9/s1/phase1/control.sqlite3-shm` 的 mtime/ctime，大小没变，主库和 `-wal` 都没动。
  - 这处变化来自 SQLite 只读连接，读者会在 WAL 共享内存索引里登记读标记。触发它的是 S1 用例 `test_s1_r7_host_anchor.py::test_the_real_ledger_is_untouched_by_the_anchor_checks`：该用例调用冻结源码 `worker.canonical_ledger_state()`，以 `mode=ro` 打开实盘账本。这属于 PLAN §6 第 5 项（E1/S1 测试不封闭），不在这四项里，见 §6。
  - `artifacts/reports` 下 3 个曾被重写的文件和 `artifacts/control.sqlite3*`，现在 stat 完全不变。
- 冻结件没有改动：
  - `artifacts/v9/e1/phase2/prereg.json` 的 SHA256 是 `84f23f2c…`，`prereg.r0.json` 是 `db75d096…`，都与各自的 `.sha256` 一致。
  - A2 基线复验：497 个钉住条目 497 个完好。RED 原因与 11-05 的记录逐项相同：8,027 个 `unexpected_new_file`、30 条 `policy_claim_unmet`。复验前后 stat 无变化（`logs/baseline_verify_summary.json`、`logs/statdiff_baseline_verify.txt`）。

## 1. E1/S1 的 MLX 导入（PLAN §6 第 1 项）

### 1.1 现场

| 位置 | 情况 |
|---|---|
| `src/ainerzero/v9/experiments/e1/__init__.py` | 包初始化时 `from . import arms_net, …`；`arms_net.py` 在模块级导入 `mlx.core/nn/optimizers/utils`，还在模块级定义 `nn.Module` 子类。`train_runner.py` 也在模块级导入 mlx。所以导入任何 `ainerzero.v9.experiments.e1.*` 都会载入真实 MLX。 |
| `src/ainerzero/v9/experiments/s1/arms.py` | 模块级 `import mlx.core as mx; import mlx.nn as nn`。`smoke.py` 在模块级导入 `arms`。 |
| 默认入口在收集阶段导入 MLX 的测试模块 | 共 22 个：E1 19 个，含 272 条用例；S1 3 个（`test_s1_no_update`、`test_s1_pacer_duty`、`test_s1_r7_d_candidate`），含 24 条。其中只有 4 个 E1 模块自己在模块级 `import mlx`，其余都是经 e1 包初始化或 `s1.arms` 传递导入。 |
| 运行期（本次新查明） | 默认入口里另有 38 条 S1 用例在运行时导入真实 MLX。路径全部相同：`commands.mode_*` → `resource_gate.assert_start` → `collect` → `mlx_memory_probe()`，这里尽力 `import mlx.core`。另有 1 条用例 `test_s1_timing_sequence.py::test_worker_train_resets_deadline_across_sequential_runs` 在函数体里导入 `test_s1_pacer_duty` 的夹具，从而导入 `s1.arms`。几何的两条 `sys.modules` 检查之所以在全量时失败，是这两类来源共同造成的。 |

### 1.2 两种路线的影响面与裁定

| | A：登记为原生模块（测试侧） | B：改成延迟导入（源码侧） |
|---|---|---|
| 需要改的文件 | `tests/conftest.py` 的登记表，22 个测试文件各加一行 `pytestmark`，A39 清单测试 | `e1/__init__.py`、`e1/arms_net.py`（模块级定义了 `nn.Module` 子类，要重构成工厂或延迟定义，不是挪几行 import 就行）、`e1/train_runner.py`、`s1/arms.py` |
| 冻结身份 | 不受影响 | **会破坏**。E1 冻结预登记 `prereg.json` 的 `source_digests` 绑定了 E1 全部 16 个源文件，这 3 个文件目前与登记一致；`identity.py` 会把当前摘要与登记逐项比较。`s1/arms.py` 的当前摘要 `28f9f326…` 被 `artifacts/v9/s1/phase1/final/pre_registration.json` 和 r15 绑定。E1 已于 11-06 收口，重启须新登记。 |
| 默认入口的覆盖 | 少 296 条（E1 272、S1 24），另有 1 条 S1 用例按节点登记。它们仍可用 `--native-mlx` 收集，但 A39 规定没有登记的原生运行器、不得裸跑，所以实际上不再常规运行。先例：A39 以同样方式排除了 258 个实例。 | 覆盖全部保留 |
| 风险 | 已收口和已冻结代码失去常规回归。代码本身被摘要冻结，改动会被身份门拦下，所以回归风险低。 | 改动冻结源码；E1 必须新登记 |

**裁定：A。** B 要改冻结身份所绑定的源码，超出本任务的授权（CLAUDE.md：改冻结参数或门槛须用户逐项批准；E1 重启须新登记），所以不选。

运行期的 38 条不适用路线 A：它们不需要 MLX，整条按节点登记会白白减少覆盖。处理见 §1.3 第 4 点。

### 1.3 改动

1. `tests/conftest.py`
   - `NATIVE_MODULES` 增加 22 个模块，逐条写明是直接导入还是传递导入，并说明不能改成延迟导入的原因。
   - `NATIVE_TESTS` 增加上面那条 timing 用例。
2. 22 个测试文件各加一行 `pytestmark = pytest.mark.native_mlx(reason=…)`，沿用 A39 写法。diff 每个文件都是 +2 行，其余内容没动。
3. `tests/test_cpu_collection.py`
   - 原清单检查只扫描 `tests/` 顶层、只认模块级直接导入，并要求与登记表相等。登记了传递导入的模块后它必然失败。
   - 改为两层检查：
     - 静态：`tests/**` 中直接导入 MLX 的模块 ⊆ 登记表；
     - 动态：子进程用 `--native-mlx` 收集，哨兵按调用栈把每次 MLX 导入记到最外层的测试模块，要求「命中集合 = 登记集合」，两个方向都核对。
   - 另外两条检查改为按路径解析，覆盖 `tests/v9/experiments` 下的嵌套模块。
4. `tests/v9/experiments/conftest.py` 新增 autouse 夹具（跳过 `native_mlx` 用例）：把 `resource_gate.mlx_memory_probe` 换成该函数源码里自带的降级返回（`available: False`）。
   - `resource_gate.py` 被 S1 final 预登记绑定，不改源码。
   - 依据：用审计插件在运行期阻断 MLX、跑一遍全量，结果 3431 条全部通过，且只有这 38 条尝试过导入，都经同一处（`logs/mlx_runtime_audit_full_before_fixture.json`）。加夹具后，`tests/v9/experiments` 运行期导入尝试为 0（`logs/mlx_runtime_audit_experiments_after_fixture.json`）。

### 1.4 对抗验证（隔离副本，scratchpad）

- 删掉 `test_e1_prereg.py` 的登记：清单检查报 `unregistered: ['test_e1_prereg.py']`，默认收集检查也失败。
- 把纯 CPU 的 `test_spacetime_s03.py` 误登记：清单检查报 `registered_but_cpu: ['test_spacetime_s03.py']`。
- 未改动的副本：3 条都通过。
- 几何两条在全量时通过，说明运行期也没有 MLX 进入进程。

## 2. M2 测试往交付目录写输出（PLAN §6 第 2 项，规则 8）

- 交付的 `artifacts/reports/E25-weighted|E27-onestep/source-full-chain/probe.py` **没有改动**。它们只在 `__main__` 块里写 `probe-log.json`。
- 新增 `tests/probe_replay.py`：
  - 起一个新解释器，所以 `mlx_loaded` 只反映 probe 本身；
  - 以非 `__main__` 名义加载 probe，它自己的写出块因此不会执行；
  - 把 probe 的只读账本 `artifacts/control.sqlite3`（-wal 为 0 字节）字节拷贝到临时目录再打开，连 `-shm` 也不触碰；
  - 调用 `run_chain()`，按 probe 自己的格式把日志写进 `tmp_path`。
- `test_action_preservation_source_compat.py`：
  - `duty-migration.json` 改为在 `tmp_path` 里生成，再与交付文件逐字节比对；
  - E25 probe 改用上面的回放，再与交付的 `probe-log.json` 逐字节比对。
- `test_action_preservation_onestep.py`：E27 probe 同样处理，并补上 `protocol_is_onestep` 断言（probe 自己的退出条件里本来就有这一项）。
- 结果：生成内容与交付文件逐字节一致。目标用例 8 条通过，前后 stat 不变。
- **跑全量时发现并修复的连带问题**：`test_action_preservation_onestep.py` 的变异套件只把被测文件复制进临时仓库，副本里没有 `probe_replay.py`，导入就失败。后果是所有变异都会被误判为「已抓到」，属于假通过；未变异副本那条对照用例因此失败，暴露了这个问题。修法是在 `_copy_tree` 里一并复制该辅助模块。fullproj、halfproj、tailself 套件复制整个 `tests/`，不受影响。

## 3. S1 r7 账本测试绑定实盘账本当前状态（PLAN §6 第 3 项）

- 失败原因：r8–r15 和 final 往同一实盘账本追加了 46 行，其中不少行的终态区间大于预留，于是 21361 ≠ 8040。
- 固定集合：r7 当时账本里只有 `s1-phase1-prereg-prep-20261021` 的 3 行，终态区间合计 59.53 s，预留合计 720.27 s，与测试模块文档串里 P17 增补的实测值逐位吻合。
- 改动：
  - 测试只读出这 3 个 `run_id`，并断言每行的 `(state, created_at, updated_at, active_seconds)` 与钉住的存储值完全相等；
  - 新增 59.53/720.27 两个断言；
  - 原有断言（年龄规则超出 4 h 上限、r7 规则等于预留且低于上限、副本和原件 SHA 不变）全部保留。
- 对抗验证（隔离副本）：把终态行改回按日历年龄计费（r6 缺陷），得到 4,112,440 ≠ 720.27；把逐行求和改成全局取最大，得到 350.58 ≠ 720.27。两种都被抓到。

## 4. fullproj 身份文件断言过时（PLAN §6 第 4 项）

- 背景：
  - A57 r1 实现者自签过冻结（`registered_by: gemini-b7x2 … (A57 implementation)`）。r2 按打回意见删除了它，草稿存档为 `fullproj-identity.r1-implementer-draft.archived.json`，标记 `not_valid_for_identity_gate: true`。
  - 此后一级（claude，A57 r2/A58 r2 验收后）正式冻结，写入 `registered_by` 和 `identity_frozen_r1_run_not_authorized`。
  - 原断言要求「不得含 `registered_by`」，与一级的冻结冲突。
- 按一级意图改写为：
  1. 身份绑定的实现文件（`cli.FULLPROJ_REQUIRED_FILES` 中的 `.py`）不得写 `registered_by` 键；
  2. 文件未签署时不得自称冻结；已签署时，签署者必须是一级（`claude`/`codex`），状态为冻结，且 `run_authorized is False`；
  3. 存档的实现者草稿保持 `not_valid_for_identity_gate`，签署者不得与草稿相同。
- 对抗验证（隔离副本，替换身份文件）：
  - 一级冻结：通过；
  - 实现者草稿：失败；
  - 未签署却称冻结：失败；
  - 未签署且未冻结：通过；
  - `run_authorized: true`：失败。

## 5. 其他核对

- ruff：逐文件对比 HEAD 与工作区，没有新增任何告警，只有 3 个文件的存量告警减少。新文件 `tests/probe_replay.py` 无告警。存量告警不在本任务范围内。
- 第一次全量（修复 §1.3 第 4 点和 §2 连带问题之前）：3 failed / 3428 passed（`logs/pytest_full_run1_summary.txt`）。stat 另有 `m0-worker.lock` 和 S1 `-wal` 两处只变 ctime，mtime 和大小不变（`logs/statdiff_full_run1.txt`）；最终那次全量没有再出现。
- 诊断插件和 stat 快照脚本放在 `tooling/`，路径按当前目录推导，只读。

## 6. 限制与后续

- **E1/S1 的 296 条用例改动后没有运行**：它们会导入真实 MLX，按 A39 不得裸跑。这些文件的唯一改动是新增的 `pytestmark` 行。
- **残留的实盘元数据变动**：S1 账本 `-shm` 的 mtime 变化来自冻结源码的只读打开（§结论）。要消除它，需要把 E1/S1 测试从写死的 `REGISTERED_HOST_ROOT` 中解耦，也就是 PLAN §6 第 5 项，由一级另行决定。
- E1 若重启（新登记），应同时把 `e1/__init__.py` 改为延迟导入，让 15 个本身不在模块级导入 MLX 的 E1 测试模块回到默认入口。其中个别用例仍会在函数内导入 MLX（如 `test_e1_eval_runner.py:851`），届时要按节点登记。
- PLAN §6 第 6 项（A2 基线清单刷新）和根目录 `probe.py` 的去留不在本任务范围内。
