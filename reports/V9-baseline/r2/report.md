# ainerzero.V9.A2.r2 执行报告：基线冻结清单 v2（扩展覆盖版）

角色：executor；负责人：`opencode-de3b`（opencode，tier 2）· 时间：2026-10-20
任务状态：reported；依据：ADR-0012、`docs/design/V9_LANDING_PLAN.md` §3（P0 门槛「基线哈希可复验」）/§4、任务卡 ainerzero.V9.A2 v0、A3 复核意见
输入身份：AinerZero HEAD `5175259945b3`、`artifacts/control.sqlite3`（sha256 见清单）；被冻结的 453 个文件全部记录 sha256
修改文件：**新增** `scripts/v9_baseline_manifest_r2.py`、`reports/V9-baseline/r2/`（清单、台账、证据、本报告）。**未改任何既有文件**（`artifacts/` 与源码零改动）
实际执行：`python3 scripts/v9_baseline_manifest_r2.py build|verify|selftest|inventory`（纯 CPU，8.2 s / 5.1 s / 15.3 s / 3.8 s）
验证结果：**verify 453/453 全绿（exit 0）；篡改对照 8 类注入故障全部让 verify 真实非零退出；干净副本 exit 0；两次 build 除时间戳外逐字节相同**
产物：`reports/V9-baseline/r2/baseline_manifest.json`、`BASELINE_INVENTORY.md`、`selftest.json`、`selftest.stderr`、`verify_clean.json`、`metrics.json`、`scripts/v9_baseline_manifest_r2.py`
失败与限制：清单不覆盖源码与报告正文；`-wal/-shm` 与 test scratch、teacher cache、episodes/ 不入清单（理由见 §3 的 `excluded_with_reason`）；RunStore 字节级哈希在合法 VACUUM 后会变，以行级 `entries_digest` 为语义主键（已在 policy 说明）

## 1. 结论摘要

1. **扩展只读清单已建立并自洽**：453 个文件 / 584.8 MB，覆盖：
   - **41 个真实检查点**（119.9 MB，含 D 候选 run `96b72328-…`、C0/GridLab 实验运行、M0 基线）
   - **56 个 pilot 检查点元数据**（manifest.json/metadata.json，5.6 MB）——**A3 必补项 1、2**
   - **22 个 M0 检查点元数据**（manifest.json/metadata.json/report.json/events.jsonl，50 KB）
   - **133 个 pilot 运行级配置/报告**（report.json/updates.jsonl/fixed-batch.npz/training-pool.npz/training-schedule.npy，297.6 MB）——**A3 必补项 1、2**
   - **10 个 per-checkpoint 更新日志**（updates-*.jsonl，0.7 MB）
   - **C0 与 GridLab2D 两套 episode 数据集**（99 文件 / 13.7 MB）
   - **88 份登记/预登记文档**（78.9 MB，含 30 个 pilot `preregistration.json`、E20-d/C06/C06a/C07/S07 等登记与预登记）
   - **4 个 RunStore 数据库文件**（68.2 MB）
   - **86 个显式排除并记理由**（teacher cache、episodes/ 目录、volatile scratch）——**A3 必补项 2**

2. **可复验**：`verify` 重新哈希全部 453 个文件 + 重算 RunStore 行级摘要，`453/453` 匹配、`problems=[]`、**exit 0**，耗时 5.1 s。

3. **篡改必变红**：篡改对照把 8 类故障分别注入**临时符号链接副本**（真实文件从不被写）：
   - 检查点字节翻转（长度不变）→ `sha256_changed`
   - 基线互换（用另一检查点覆盖）→ `size_changed`
   - 检查点元数据截断 → `size_changed`
   - 运行级配置截断 → `size_changed`
   - 数据集文件删除 → `missing`
   - 偷偷塞入未登记检查点 → `unexpected_new_file`
   - RunStore 行被 UPDATE 伪造 → `sha256_changed` + `runstore_entries_changed`
   - 清单自身被改 → `manifest_digest` + `sha256_changed`
   **8/8 全部让 `verify` exit 1**，干净副本 exit 0。

4. **确定性**：连续两次 `build` 的清单除 `generated_at` 外逐字节相同，`manifest_digest` 一致；清单自带自摘要，改清单本身也会变红。

5. **零模型加载**：脚本只 import `argparse/hashlib/json/os/pathlib/shutil/sqlite3/subprocess/sys/tempfile`；检查点按字节哈希，从不反序列化；脚本入口有「若已导入 mlx/torch/onnxruntime 就拒绝运行」守卫（exit 2）。

6. **RunStore 覆盖完整性有断言支撑**：RunStore 共 79 个 run，其中 32 个在磁盘上有检查点，**全部为 `completed`**，且**全部落在这 41 个已登记检查点里**（`runs_with_checkpoints_only_in_scratch = []`，即没有任何 run 的检查点只存在于易失 scratch）。

7. **明确的排除规则与理由**（写入 `manifest.policy.excluded_with_reason`，不是静默遗漏）：
   - **volatile scratch**：路径任一分量为 `tmp` 或以 `tmp-` 开头（312 个 `*.safetensors`），pytest 临时产物，会被后续测试合法重写 → 记入 `volatile_checkpoints` 列表但不冻结
   - **teacher cache**：`teacher-cache.npz`、`teacher-cache-manifest.json`（86 个文件中的一部分），派生产物，身份由上游 run 登记锚定
   - **episodes/ 目录**：逐 episode 数据，不属于基线冻结范围
   - **`-wal`/`-shm`**：SQLite 侧文件，读写会更新 mtime；WAL 现为 0 字节
   - **新增文件也算变更**：`verify` 会重新扫描受约束范围，任何未登记的新 `*.safetensors`/登记文档/数据集文件/元数据/运行级配置都会产生 `unexpected_new_file` 并变红

## 2. 清单内容（r2 扩展版）

| 类别 | 文件数 | 字节 | 说明 |
|---|---|---|---|
| `checkpoint` | 41 | 119,999,100 | m0 11 + pilot 30；含 D 候选（run `96b72328-…`，experiment `m2md-distill-20261013-r2`）与 C0/GridLab 实验运行 |
| `checkpoint.meta` | 56 | 5,617,847 | pilot 检查点目录下的 `manifest.json`/`metadata.json`（**A3 必补**） |
| `m0.checkpoint.meta` | 22 | 50,512 | M0 检查点目录下的 `manifest.json`/`metadata.json`/`report.json`/`events.jsonl` |
| `run.config` | 133 | 297,555,707 | pilot 运行根目录下的 `report.json`/`updates.jsonl`/`fixed-batch.npz`/`training-pool.npz`/`training-schedule.npy`（**A3 必补**） |
| `run.updates` | 10 | 718,632 | per-checkpoint 更新日志 `updates-*.jsonl` |
| `dataset.c0` | 8 | 492,682 | C0 episode（`manifest.json`/`private.json`/`public.jsonl`）|
| `dataset.gridlab2d` | 91 | 13,237,307 | GridLab2D 四个切片（s06-sample / s07-sample / s07-r2 / s07-closeout）|
| `registration` | 88 | 78,918,526 | 80 `.json` + 8 `.md`，含 30 个 pilot `preregistration.json`、E20-d/C06/C06a/C07/S07 等登记与预登记 |
| `runstore.file` | 4 | 68,161,536 | `control.sqlite3`(63.2 MB)、`.bak-20261011`(4.9 MB)、`m0/control.sqlite3`、`run_store.db`(0 B) |
| **合计** | **453** | **584,751,849** | `manifest_digest = ee6fc9c9bbd3177c…` |

**RunStore 条目（行级，跨 VACUUM/WAL checkpoint 稳定）**

| 库 | 打开方式 | 表行数 | entries_digest |
|---|---|---|---|
| `artifacts/control.sqlite3` | `immutable=1`（WAL 为空） | runs 79 / experiments 44 / run_transitions 417 / daily_budget 13 / metadata 2 | `9f2bfac5f5bb192f…` |
| `.bak-20261011` | `immutable=1` | runs 56 / experiments 21 / run_transitions 291 / daily_budget 9 / metadata 2 | `0087b2779b44b5c8…` |
| `artifacts/m0/control.sqlite3` | `immutable=1` | runs 4 / run_transitions 27 / daily_budget 1 / metadata 2 | `de00db1c66bf475b…` |
| `artifacts/run_store.db` | `immutable=1` | 无表（0 字节） | `4f53cda18c2baa0c…` |

汇总 `runstore.entries_digest = 18e491ef60fbb91a…`；另有 `runs_with_checkpoints`（32 个 run → 其检查点路径）与 `runs_with_checkpoints_only_in_scratch = []`。

逐检查点台账（run_id → run state → experiment、大小与 sha256 前缀）在 **[BASELINE_INVENTORY.md](BASELINE_INVENTORY.md)**。

## 3. 冻结口径（写入 `manifest.policy`，不写在注释里）

- **pin**（显式列出的所有模式）：
  - `artifacts/**/*.safetensors`（排除易失 scratch）
  - `artifacts/**/*registration*.{json,md}` 和 `preregistration.json`
  - `artifacts/pilot/**/checkpoints/*/manifest.json`、`artifacts/pilot/**/checkpoints/*/metadata.json`
  - `artifacts/m0/**/checkpoints/midpoint/manifest.json`、`artifacts/m0/**/checkpoints/midpoint/metadata.json`/`report.json`/`events.jsonl`
  - `artifacts/pilot/**/report.json`、`artifacts/pilot/**/updates.jsonl`、`artifacts/pilot/**/fixed-batch.npz`、`artifacts/pilot/**/training-pool.npz`、`artifacts/pilot/**/training-schedule.npy`
  - `artifacts/pilot/**/updates-*.jsonl`（per-checkpoint 更新日志）
  - `artifacts/m0/**/report.json`、`artifacts/m0/**/events.jsonl`
  - `artifacts/c0/**`、`artifacts/gridlab2d/**`
  - 四个 RunStore 文件

- **excluded_volatile_rule**：路径任一分量为 `tmp` 或以 `tmp-` 开头。实测排除 312 个 `*.safetensors`（`onestep-identity-tests`、`onestep-identity-tests-review`、`E29-halfproj/review/.../runs/default-cpu-run/tmp/` 等 pytest/runs 临时目录）。**它们被记入清单的 `volatile_checkpoints` 列表**，所以不是静默丢弃。

- **excluded_transient**：`*-wal`、`*-shm`（SQLite 侧文件，读写会更新 mtime；WAL 现为 0 字节）。

- **excluded_with_reason**（逐文件记录，共 86 个）：
  - `teacher_cache`：`artifacts/pilot/**/teacher-cache.npz`、`teacher-cache-manifest.json` —— 派生产物，身份由上游 run 登记锚定
  - `episode_data`：`artifacts/pilot/**/episodes/**` —— 逐 episode 数据，不属于基线冻结范围

- **新增文件也算变更**：`verify` 会重新扫描受约束范围，任何未登记的新文件都会产生 `unexpected_new_file` 并变红（对照第 6 例）。

- **never_loaded**：检查点只被按字节哈希。

- **runstore_note**：RunStore 身份以行级 `entries_digest` 为**主键**（跨 VACUUM/WAL checkpoint 稳定）；文件级 sha256 为**辅助**，合法 VACUUM 或 WAL checkpoint 后文件字节会变，这是已知限制，不视为基线被篡改。语义身份以 `entries_digest` 为准。

## 4. 篡改对照（`selftest`，全部在临时符号链接副本上）

| # | 注入的故障 | `verify` 结果 | 退出码 | 命中的判定 |
|---|---|---|---|---|
| 0 | 无（干净副本） | ok | **0** | — |
| 1 | 翻转某检查点一个字节（**长度不变**） | RED | **1** | `sha256_changed` |
| 2 | 用另一个已登记检查点的字节覆盖当前检查点（基线互换） | RED | **1** | `size_changed` |
| 3 | 把某检查点元数据截断成 `{}` | RED | **1** | `size_changed` |
| 4 | 把某运行级配置文件截断成 `{}` | RED | **1** | `size_changed` |
| 5 | 删除某 C0 数据集文件 | RED | **1** | `missing` |
| 6 | 在某检查点旁塞入未登记的 `smuggled-extra.safetensors` | RED | **1** | `unexpected_new_file` |
| 7 | 对 RunStore 副本 `UPDATE runs SET state='completed_forged'`（1 行） | RED | **1** | `runstore_entries_changed` + `sha256_changed`（DB 文件本身也变了） |
| 8 | 手工改清单副本里 `files[0].sha256` | RED | **1** | `manifest_digest` + `sha256_changed` |

原样输出：`reports/V9-baseline/r2/selftest.json`、`selftest.stderr`；脚本在这些都通过时打印
`selftest: clean copy green, all 8 injected faults detected` 并 **exit 0**，只要有任一故障没被抓到就 exit 1。

**为什么用符号链接副本**：真实 `artifacts/` 必须保持只读，对照只能改副本；副本里除四个数据库用 APFS `cp -c` 克隆外全是符号链接，校验的仍是真实文件的内容，所以「改坏→变红」测的是同一条代码路径。

## 5. 实际命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
python3 scripts/v9_baseline_manifest_r2.py build      # 8.2 s，写 reports/V9-baseline/r2/baseline_manifest.json
python3 scripts/v9_baseline_manifest_r2.py verify     # 5.1 s，453/453，exit 0
python3 scripts/v9_baseline_manifest_r2.py selftest   # 15.3 s，8/8 注入故障被抓，exit 0
python3 scripts/v9_baseline_manifest_r2.py inventory  # 写 BASELINE_INVENTORY.md
python3 scripts/v9_baseline_manifest_r2.py verify --json > reports/V9-baseline/r2/verify_clean.json
```

二次 `build` 到临时路径与正式清单对比：除 `generated_at` 外**完全相同**（含 `manifest_digest`）。

## 6. 与 r1 的差异（回应 A3 复核意见）

| A3 指出的缺口 | r2 的解决 |
|---|---|
| 1) D 候选运行 `pilot-b4e75e…/96b72328-…` 的 `manifest.json`/`metadata.json`/`fixed-batch.npz`/`training-pool.npz`/`training-schedule.npy`/`report.json`/`updates.jsonl` 未钉选 | **已钉选**：归入 `checkpoint.meta`（2 个）、`run.config`（5 个） |
| 2) 全部检查点目录的 manifest/metadata（78 个）与运行级数据/报告/配置（157 个）要么钉选，要么写进排除清单并逐类给理由 | **已全部钉选**：56 个 pilot 检查点元数据 + 22 个 M0 元数据 + 133 个运行级配置 + 10 个 per-checkpoint 更新日志；86 个排除文件逐个记录理由（`teacher_cache`、`episode_data`） |
| 3) 钉选目录内出现未登记文件必须变红，或修正注释与行为一致 | **已满足**：`verify` 重新扫描受约束范围，`unexpected_new_file` 判定覆盖所有新增文件类别（检查点、元数据、运行级配置、数据集、登记文档、RunStore） |
| 4) RunStore 字节级钉选遇合法 VACUUM 会误判 | **已登记为限制**：policy 明确写明「行级摘要为主、字节为辅」；`verify` 对 RunStore 文件级 sha 变化只发 `warning` 不判 `RED`，语义身份以 `entries_digest` 为准 |

## 7. 失败与限制（含如实说明）

1. **清单不覆盖源码、报告正文、非检查点数据**（如 `spacetime/`、`locks/`、测试与日志）。本卡范围是「检查点、登记、RunStore、运行级配置/报告/元数据」，如果要冻结 `src/ainerzero/**` 的源码身份，建议另开一卡（或把 `src` 加进 pin 策略后重新 build）。
2. **`-wal/-shm` 不入清单**，因此若将来有进程把 WAL 里未 checkpoint 的内容写回主库，主库 sha 会变红（这是期望行为），但也说明「RunStore 文件级 sha」只在下一次写入前有效；语义身份以行级 `entries_digest` 为准。
3. **D 候选/GridLab 的“能力”未在本卡验证**：本卡只冻结身份，不评价任何检查点的能力或是否应晋升。清单里 32 个 run 全为 `completed` 只表示运行状态，不代表能力通过。
4. **未做**：不加载 MLX/不推理（脚本层面拒绝）、不训练、不下载、不安装、不付费、不提交推送、不删除；未改文件范围外的任何文件。
5. **8 个检查点不在 RunStore 里**（`interrupted-*` 与被中断运行的产物、`pilot-*/probes/*-probes/tensors.safetensors`）：它们仍被冻结（同属 `pilot` 树），台账里标为 `(not in RunStore)`，不是遗漏而是如实标注。
6. **teacher cache 与 episodes/ 显式排除**：这些文件在扫描时被识别并记入 `excluded_with_reason`，不参与冻结；如需冻结需另行决策。

## 8. 交回统筹

- **建议验收 ainerzero.V9.A2.r2**：P0 门槛「基线哈希可复验」现在有更完整的可执行证据（`verify` exit 0 / 篡改 exit 1），且回应了 A3 复核的全部四项必补要求。
- **后续卡可直接复用**：`ainerzero.V9.A4`（非作者复核 r2）应至少复跑 `verify` 与 `selftest`，并对清单策略本身做对抗（例如：把 scratch 里的检查点冒充基线、改动 `policy` 里的排除规则后再篡改、检查 `entries_digest` 是否真随 RunStore 行变化、验证 `unexpected_new_file` 能否捕获各类别新文件）。
- **需要统筹决定**：是否把 `src/ainerzero/**`（或 `ARCHITECTURE_V9.md` 等设计文档）也纳入冻结范围；本卡按文件范围未做。