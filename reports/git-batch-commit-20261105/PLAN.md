# AinerZero 工作树分批入库：方案与执行记录（2026-11-05 UTC / 11-06 北京时间）

- **执行**：Claude 会话 f037a730，接手前一会话 4d40e2fb 中断的工作。
- **授权**：用户在本会话原话「你自动完成所有操作全权处理 保证模型准确与质量」。
- **本任务只提交、不推送、不改写历史。**
- **范围**：起点 HEAD `296589c`。把 21,296 个未跟踪或已修改文件中应入库的 12,935 个分成 12 批提交，最后一批收尾提交本报告和 `.gitignore` 补充。其余文件按规则留在本机，见 §5。
- **约束**：
  - 冻结文件只读：`artifacts/v9/e1/phase2/prereg.json`（r1，`84f23f2c…`）、`prereg.r0.json`，以及 A2 基线；
  - 复跑不得改写已交付证据（COORDINATION 规则 8）；
  - 全量 pytest 前台跑，或还原 SIGINT 处理后再跑。

## 1. 结论

- 12 批全部完成隔离验证。
  - 每批的树 = `git archive HEAD` + 该批及之前各批的文件，并换上该批对应的 `cli.py` 分段。
  - 每批树里 `ainerzero.cli` 和全部 `ainerzero.v9.*` 模块都能导入，0 失败。
  - 各批自己的测试要么全部通过，要么只剩已逐条证实的既有失败或本机环境缺失。
- 最终树（全部 12 批）跑全量 `tests/`：
  - 结果 3613 passed / 70 failed / 5 errors / 20 skipped。
  - 叠加本机环境（只读链接到 DA3 权重、`.venv-t6`、旧证据库）后为 3685 passed / 7 failed。
  - 75 条失败/错误中有 69 条随环境叠加消失，剩下 6 条全是实盘既有问题或隔离树没有 `.git` 所致，见 §4。
  - 没有一条失败是分批入库造成的。
- 树里的 `src/`、`tests/` 与实盘逐字节一致（提交前由 `stage_batch.py` 按 SHA256 复核），所以这些结论对入库内容成立。

## 2. 分批清单（按提交顺序）

体积为原始字节数。报告类文件的去重压缩估计约 47 MB。逐文件 SHA256 见 `manifests/<批>.tsv`。

| # | 批 | 内容 | 文件 | 体积 | 依赖 |
|---|---|---|---:|---:|---|
| 1 | b1_contract | V9 契约层：interfaces、fakes、geometry r2（G5 F1/F2 修复）+ canonical、tokenization（RLT）、SkillProposal/v1 契约与文档、`reports/V9-B12/cmfl_registration.json` | 290 | 1.99 MB | HEAD |
| 2 | b2_cmfl | CMFL 机制发现原型（G7）及测试 | 10 | 0.20 MB | b1 |
| 3 | b3_e1code | E1 代码 `experiments/e1`、E1 测试与 fixture、P48 预登记草案、E1SMOKE3 冒烟 development 数据（测试读取）；`cli.py` 加 `WorkerLockBusy` 与 `e1-phase2` | 85 + cli | 2.05 MB | b1 |
| 4 | b4_s1code | S1 代码 `experiments/s1`、S1 测试、基线清单脚本 r2/r3、`reports/V9-baseline/r3`（测试读取）；`cli.py` 加 `s1-phase1` | 74 + cli | 1.28 MB | b3 的 cli 分段 |
| 5 | b5_teachers | 教师线代码（cache/mode/benchmark/DA3 受控入口）、teacher CLI、v2.1 缓存契约与文档；测试读取的证据 `reports/V9-T28`、`V9-T6/r2-calib-fixtures`、`V9-T30/r{2,3}/mutations`；教师环境胶水脚本 `envs/teachers/t4/*.py`、`t6/*.py`、`t6/tests`、t10/t12 许可来源 json；`cli.py` 加 `teacher-*`（定稿，等于工作树） | 243 + cli | 6.86 MB | b4 的 cli 分段 |
| 6 | r1_b | B 线报告：SkillProposal / 晋升证据（V9-B*、V-V9-B*） | 4,075 | 34.48 MB | — |
| 7 | r2_ga | G/A 线报告：几何 r2、CMFL ADR-0014 审议与原型（V9-G*、V-V9-G*、V9-A11–A14、frontier-integration） | 338 | 5.87 MB | — |
| 8 | r3_registry | R 线：V9-R5/R11–R13、V-V9-R5 报告；`docs/research/ADAPTER_REGISTRY.md` 与 `adapter_registry.json`（r4，96 条，md 表与 json 的 id 集合一致） | 97 | 1.66 MB | — |
| 9 | r4_s1 | S1 线报告：P1–P62 执行与复核、S1 r12–r15/final/审计、基线 A2/A3 | 2,314 | 37.23 MB | — |
| 10 | r5_e1 | E1 线报告：预登记、冒烟、运行 A/B/C/r2、复核、冻结（V9-E1*、V9-P48-REVIEW） | 1,954 | 125.72 MB | — |
| 11 | r6_teachers | 教师/DA3 线报告（V9-T*、V-V9-T*、安装下载、TPREP、P63） | 3,523 | 33.50 MB | — |
| 12 | r7_misc | CF-D1/CF-H1、`reports/coordination`、`CLAUDE.md`（授权现状 10-21）、`COORDINATION.md`（10-20 恢复、10-22 两条裁定、10-26 承接） | 32 | 5.58 MB | — |
| 13 | 收尾 | 本报告目录、`.gitignore` 补充（§5）、RESEARCH_LOG 一条记录 | — | — | 1–12 |

**`cli.py` 分段**：`src/ainerzero/cli.py` 被 E1、S1、教师三条线共同修改。

- `tooling/cli_variants.py` 从工作树文件中按块剥离，生成 b3、b4 两个中间版本，b5 用定稿版。
- 脚本断言两件事：全部剥离后逐字节等于 HEAD；全部保留时逐字节等于工作树。
- 提交时用 `git update-index --cacheinfo` 暂存各段内容，不改工作树。

**报告纳入规则**：满足以下全部条件的文件入库，否则不入库、只登记 SHA256（§5）：

- 普通文件，不是符号链接；
- 不大于 1 MB；
- 路径不含 `datasets/`、`checkpoints/`，不是 `.npz`/`.npy`；
- 本来就不被 `.gitignore` 忽略（`*.sqlite*`、`*.safetensors`、`*.pyc` 等原规则不变）。

例外：代码批里测试实际读取的证据（E1SMOKE3 development 数据、T6 r2 标定夹具 `.npy`）随代码批入库。

## 3. 隔离验证方法与结果

- **工具**：`tooling/`。
  - `build_tree.py <批>` 在 scratchpad 建树，运行该批测试；`final` 跑全量；`--env` 叠加本机环境。
  - `hook_pytest.py` 是带审计钩子的 pytest 包装。
  - `import_check.py` 做全模块导入检查。
  - `stage_batch.py` 负责按 SHA 复核后精确暂存。
- **实盘写入审计**：每轮记录三类信息。
  1. 进程内打开的实盘路径：解析符号链接，单列写模式打开和 sqlite 连接。
  2. 跑前跑后对实盘 artifacts、reports、src、tests 等做 stat 对比，子进程的写入也能发现。
  3. 继承的 SIGINT 处理：各轮都是 `default_int_handler`，没有被忽略。
- **前会话 b5「跑到一半中断」的真因**：前会话包装脚本没有 `__main__` 守卫，教师测试用 multiprocessing spawn 起子进程，子进程会重跑包装脚本，父进程永久等待（CPU 0%）。已加守卫。

| 运行 | 测试结果 | 导入（模块数） | 实盘写入 |
|---|---|---|---|
| b1_contract | 508 passed | 28，0 失败 | 无 |
| b2_cmfl | 41 passed | 35，0 失败 | 无 |
| b3_e1code | 364 passed | 53，0 失败 | 无（只读 200 个 `artifacts/v9` 文件） |
| b4_s1code | 403 passed / 2 skipped / 1 failed | 70，0 失败 | 锁文件以 `a+` 加锁、不写内容；sqlite 以 `mode=ro` 读；只变了 `-shm` 索引 mtime |
| b5_teachers | 130 passed / 15 failed / 2 skipped | 82，0 失败 | 无 |
| b5_teachers --env | **147 passed** | — | 无 |
| final（全部 12 批，全量） | 3613 passed / 70 failed / 5 errors / 20 skipped / 5 deselected | 82，0 失败 | 同 b4 |
| final --env | 3685 passed / 7 failed / 16 skipped / 5 deselected | — | **见 §3.1** |

各批跳过与失败的原因：

- **b4**：2 条跳过是 `artifacts/v9/s1/phase1/r11`、`r12` 不在树中（gitignore 产物）；1 条失败见 §4①。
- **b5**：15 条失败、2 条跳过全部是本机环境缺失，叠加后全绿。缺的是 DA3 权重 `artifacts/teachers/da3`、`envs/teachers/.venv-t6`、第三方检出 `t6/Depth-Anything-3`、T35 预测 `.safetensors`。
- **5 deselected**：conftest 中需显式 `--native-mlx` 的原生用例。

**隔离的局限，如实记录**：E1/S1 代码把 `REGISTERED_HOST_ROOT` 写死为实盘根目录。部分 S1 测试因此会：

- 读实盘账本、对实盘 `m0-worker.lock` 加锁；
- 经 `tests/v9/experiments/s1_testkit.py:175` 拷贝实盘 `src/ainerzero`；
- 让子进程用实盘 `src` 作 PYTHONPATH。

这部分用例实际跑的是实盘源码，b4 报的 13 个「GAP」就是这类读取，不是导入缺口。实盘源码与入库内容逐字节一致，结论成立，但不算严格隔离。

### 3.1 final --env 对实盘的改动（如实交代）

为区分「环境缺失」与「真缺陷」，final --env 把 `artifacts/reports`、`artifacts/pilot` 以**符号链接**叠加进隔离树。已跟踪的 M2 测试会在这两个目录里写输出，于是改写了 3 个实盘文件：

- `test_action_preservation_source_compat.py:64` 写 `duty-migration.json`；
- 同目录下的 `probe.py` 写 `probe-log.json`。

| 文件 | 跑前 → 跑后 | 核对 |
|---|---|---|
| `artifacts/reports/E27-onestep/source-full-chain/probe-log.json` | 508 B → 508 B | SHA256 `7c9a8fe4…cb42` 与 10-14 登记（`A29-independent/metrics.json`、`review-r2/verification.json`）一致，**逐字节未变** |
| `artifacts/reports/E25-weighted/source-full-chain/probe-log.json` | 429 B → 429 B | 没有登记过整份 SHA。内容全部是由冻结输入推出的确定值（`condition_sha256 6e98…`、`windows_sha256 60e8…`、duty 1.0/0.25、`mlx_loaded false`），与 10-13 `A13-metrics.json` 逐项一致；生成脚本自 10-13 未改 |
| `artifacts/reports/E25-weighted/source-compat/duty-migration.json` | 552 B → 552 B | 没有登记过整份 SHA。内容是冻结检查点 metadata 的 SHA、配置 SHA 和常量，属于确定值 |

另外两点：

- `artifacts/control.sqlite3-shm`（A2 钉住库的 WAL 共享内存索引）的 mtime 变了，主库与 `-wal` 的大小、mtime 都没变。
- 这 3 个文件跑前的 mtime 是 11-03：之前有人在实盘跑过全量测试，也重写过它们。它们是测试每次运行都会重写的输出，不是一次性冻结件。但这仍违背规则 8 的精神，已列入 §6。

**A2 冻结基线复验**：`scripts/v9_baseline_manifest_r3.py verify --root .`，跑前跑后实盘 stat 无变化，摘要见 `logs/baseline_verify_summary.json`。

- **被钉住的 497 个文件 497 个完好**，含 4 个 RunStore 库的行摘要，0 条警告。
- 判 RED 的原因只有两类，都是冻结之后的合法新增，与本次无关：
  - 8,027 个 `unexpected_new_file`：E1 7,779、S1 228、教师权重等；
  - 30 个 `policy_claim_unmet`：S1 各轮预登记、教师 safetensors。

E25/E27 文件不在基线范围内（基线扫描范围不含 `artifacts/reports`）。此后 `build_tree.py` 只在 `final` 时叠加旧证据库，b5 只叠加教师环境。

## 4. 失败归类（final 与 final --env 对比，`logs/failure_classification.json`）

- **随环境叠加消失的 69 条**：
  - 53 条依赖 gitignore 的旧证据库 `artifacts/reports/relay-*`、`E25/E27`、`artifacts/pilot/...`，都是 action_preservation 测试；
  - 16 条依赖教师环境。
- **叠加后仍剩 6 条，加上 1 条只在叠加时出现，共 7 条，全部是既有问题**：
  1. `tests/v9/experiments/test_s1_r7_phase_accounting.py::test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original`：读实盘 S1 账本，账本在 r7 之后新增 r8–r15 运行，断言 21361 ≈ 8040 不再成立。实盘直接跑同样失败，数值相同。
  2. `tests/test_cpu_collection.py::test_native_module_inventory_is_complete`、`::test_default_collection_imports_no_mlx`：E1 测试（如 `test_e1_p87_geometry.py`）和 `s1/arms.py` 在模块级 `import mlx.core`，但没有登记进 `tests/conftest.py` 的 `NATIVE_MODULES`，默认纯 CPU 入口因此导入了真实 MLX。实盘直接跑同样 2 条失败。
  3. `tests/v9/geometry/test_canonical.py::test_cpu_only_imports`、`test_geometry.py::test_imports_are_cpu_only`：②的连带后果，同进程 `sys.modules` 已被 E1/S1 用例载入 MLX。在 b1 单独跑时通过。
  4. `tests/test_preflight.py::test_run_when_quiet_preflight_integration`：需要在 git 工作副本里执行 `git status`，隔离树由 `git archive` 解出、没有 `.git`，属隔离环境所致。
  5. `tests/test_action_preservation_fullproj.py::test_identity_file_is_not_frozen_by_the_implementation`（只在叠加时出现）：断言身份文件里没有 `registered_by`，但实盘该文件后来已由一级冻结、写入 `registered_by`，属测试断言过时。

## 5. 不入库的内容

- **报告中按规则排除的 5,772 个文件**：逐个登记 SHA256（符号链接登记指向）于 `excluded/<线>.tsv`，本体留在本机。
  - datasets 5,403 个（409 MB）
  - checkpoints 191 个（83 MB）
  - 大于 1 MB 的 56 个（133 MB，原始日志、progress、pypi 元数据、数据集 jsonl）
  - 数组 86 个（14 MB）
  - 符号链接 36 个（pytest 临时目录里指向本机绝对路径的 `*current` 等）
- **`envs/`（约 7.7 GB）**：只入库胶水脚本（b5）。venv、wheelhouse、uv-cache、权重、第三方检出 `Depth-Anything-3`、`vjepa2-mlx`、`sam2`、`tapnet`、`map-anything` 留在本机。
- **`.tmp/`（93 MB pytest 临时目录）、`.workbuddy-ai/`（其他工具的私有记忆）**：不入库。
- **根目录代理残留**：
  - `.relay_profile_*.json` ×12、`profile.json`、`profile-v7k2.json`（relay 代理自述）；
  - `metrics.json`（T8 副本）；
  - `报告.md`、`指标.json`：与 `reports/V9-E1R2-RUN-T/gemini-w7k4/` 下的两份逐字节相同，RESEARCH_LOG 已记；
  - `probe.py`：某代理的一次性探针，留在工作树、未忽略，待一级决定去留。
- **`.gitignore` 补充**（`tooling/gitignore_append.txt`）：`.tmp/`、`.workbuddy-ai/`、根目录 relay 运行时文件、教师环境的大件目录，以及 `reports/**/{datasets,checkpoints}/`、`reports/**/*.np[yz]`。
  - 已入库的同类文件不受影响；
  - 以后新增测试夹具需 `git add -f`；
  - 规则排除的大于 1 MB 文件和符号链接（共 92 个）不加忽略规则，继续显示为未跟踪，以免被藏起来。

## 6. 发现的问题（后续，非本任务修复）

1. **E1/S1 的 MLX 导入未登记为原生模块**：违反 A39 纯 CPU 默认入口约定，见 §4②③。需一级二选一：把相关测试模块登记进 `NATIVE_MODULES`，或把 `mlx` 改成延迟导入。
2. **M2 测试在 `artifacts/reports/E25-weighted`、`E27-onestep` 写输出**：任何实盘全量运行都会重写，应改写到 `tmp_path`。
3. **S1 r7 账本测试绑定实盘账本当前状态**：应改用冻结的账本副本。
4. **`test_identity_file_is_not_frozen_by_the_implementation` 断言过时**：与一级冻结后的身份文件冲突。
5. **E1/S1 测试不封闭**：写死 `REGISTERED_HOST_ROOT`，会读实盘账本、对实盘共享锁加锁、拷贝实盘源码；若有 worker 持锁，测试会受影响。
6. **A2 基线清单需要刷新才能继续当门用**：r3 清单只覆盖 10-20 之前的状态，复验 RED 全部来自之后的合法新增。

## 7. 复现

```bash
cp -R reports/git-batch-commit-20261105/tooling /path/to/scratch/gb && cd /path/to/scratch/gb
python3 cli_variants.py .            # 生成 cli_e1.py / cli_e1s1.py / cli_all.py，并断言 HEAD 与工作树往返
python3 build_tree.py b1_contract    # b2_cmfl / b3_e1code / b4_s1code / b5_teachers [--env] / final [--env]
python3 import_check.py b1_contract  # 每个已建的树
python3 stage_batch.py b1_contract   # 按 manifests 复核 SHA 后精确暂存（需从入库前的工作树状态运行）
```

注意：`final --env` 会把旧证据库以符号链接叠加进树，见 §3.1；需要时改用拷贝。

## 8. 提交记录

见本目录 `COMMITS.md`（收尾提交前生成）。
