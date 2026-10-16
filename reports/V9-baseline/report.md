# ainerzero.V9.A2 执行报告：基线冻结清单与复验脚本
角色：executor；负责人：`deepseek-q7m2`（deepseek-flash，tier 2）· 时间：2026-10-15 21:47–21:5x（+03:00）
任务状态：reported；依据：ADR-0012、`docs/design/V9_LANDING_PLAN.md` §3（P0 门槛「基线哈希可复验」）/§4、任务卡 ainerzero.V9.A2 v0
输入身份：AinerZero HEAD `5175259945b3`、`artifacts/control.sqlite3`（sha256 见清单）；被冻结的 232 个文件全部记录 sha256
修改文件：**新增** `scripts/v9_baseline_manifest.py`、`reports/V9-baseline/`（清单、台账、证据、本报告）。**未改任何既有文件**（`artifacts/` 与源码零改动，见 §6 的一处如实说明）
实际执行：`python3 scripts/v9_baseline_manifest.py build|verify|selftest|inventory`（纯 CPU，4.6 s / 4.6 s / 7.8 s）
验证结果：**verify 232/232 全绿（exit 0）；篡改对照 7 类注入故障全部让 verify 真实非零退出；干净副本 exit 0；两次 build 除时间戳外逐字节相同**
产物：`reports/V9-baseline/baseline_manifest.json`、`BASELINE_INVENTORY.md`、`selftest.json`、`verify_clean.json`、`scripts/v9_baseline_manifest.py`
失败与限制：清单不覆盖源码与报告正文；`-wal/-shm` 与 test scratch 不入清单（理由见 §3）；一次只读探索曾更新 `control.sqlite3-shm`（§6）
交回统筹：建议验收；P0「基线哈希可复验」这一条现在有可执行证据

## 1. 结论摘要

1. **只读清单已建立并自洽**：232 个文件 / 280.8 MB，覆盖 **41 个真实检查点（120.0 MB）**、**C0 与 GridLab2D 两套 episode 数据集（99 文件 / 13.7 MB）**、**88 份登记/预登记文档（78.9 MB）**、**4 个 RunStore 数据库文件（68.2 MB）**。
2. **可复验**：`verify` 重新哈希全部 232 个文件 + 重算 RunStore 行级摘要，`232/232` 匹配、`problems=[]`、**exit 0**，耗时 4.6 s。
3. **篡改必变红**：篡改对照把 7 类故障分别注入**临时符号链接副本**（真实文件从不被写）：字节翻转、基线互换、登记文档截断、数据集文件删除、偷偷塞入未登记检查点、RunStore 行被 UPDATE 伪造、清单自身被改 —— **7/7 全部让 `verify` exit 1**，干净副本 exit 0。
4. **确定性**：连续两次 `build` 的清单除 `generated_at` 外逐字节相同，`manifest_digest` 一致；清单自带自摘要，改清单本身也会变红。
5. **零模型加载**：脚本只 import `argparse/hashlib/json/os/pathlib/shutil/sqlite3/subprocess/sys/tempfile`；检查点按字节哈希，从不反序列化；脚本入口还有「若已导入 mlx/torch/onnxruntime 就拒绝运行」的守卫（exit 2）。
6. **RunStore 覆盖完整性有断言支撑**：RunStore 共 79 个 run，其中 32 个在磁盘上有检查点，**全部为 `completed`**，且**全部落在这 41 个已登记检查点里**（`runs_with_checkpoints_only_in_scratch = []`，即没有任何 run 的检查点只存在于易失 scratch）。
7. **明确的排除规则**（不是漏掉）：`artifacts/**` 下任何路径分量名为 `tmp` 或以 `tmp-` 开头的是 pytest 临时产物（**312 个 `*.safetensors`**），会被后续测试合法重写，因此**记录在清单的 `volatile_checkpoints` 里但不作为冻结对象**；`-wal`/`-shm` 同理。

## 2. 清单内容

| 类别 | 文件数 | 字节 | 说明 |
|---|---|---|---|
| `checkpoint` | 41 | 119,999,100 | `m0` 11 + `pilot` 30；含 D 候选（run `96b72328-…`，experiment `m2md-distill-20261013-r2`）与 C0/GridLab 实验运行 |
| `dataset.c0` | 8 | 492,682 | C0 episode（`manifest.json`/`private.json`/`public.jsonl`）|
| `dataset.gridlab2d` | 91 | 13,237,307 | GridLab2D 四个切片（s06-sample / s07-sample / s07-r2 / s07-closeout）|
| `registration` | 88 | 78,918,526 | 80 `.json` + 8 `.md`，含 30 个 pilot `preregistration.json`、E20-d/C06/C06a/C07/S07 等登记与预登记 |
| `runstore.file` | 4 | 68,161,536 | `control.sqlite3`(63.2 MB)、`.bak-20261011`(4.9 MB)、`m0/control.sqlite3`、`run_store.db`(0 B) |
| **合计** | **232** | **280,809,151** | `manifest_digest = f36594143a851580…` |

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

- **pin**：`artifacts/**/*.safetensors`（排除易失 scratch）、`artifacts/**` 下名字含 `registration` 或名为 `preregistration.json` 的 `.json/.md`、`artifacts/c0/**`、`artifacts/gridlab2d/**`、四个 RunStore 文件。
- **excluded_volatile_rule**：路径任一分量为 `tmp` 或以 `tmp-` 开头。实测排除 312 个 `*.safetensors`（`onestep-identity-tests`、`onestep-identity-tests-review`、`E29-halfproj/review/.../runs/default-cpu-run/tmp/` 等 pytest/runs 临时目录）。**它们被记入清单的 `volatile_checkpoints` 列表**，所以不是静默丢弃。
- **excluded_transient**：`*-wal`、`*-shm`（SQLite 侧文件，读写会更新 mtime；WAL 现为 0 字节）。
- **新增文件也算变更**：`verify` 会重新扫描受约束范围，任何未登记的新 `*.safetensors`/登记文档/数据集文件都会产生 `unexpected_new_file` 并变红（对照第 5 例）。
- **never_loaded**：检查点只被按字节哈希。

## 4. 篡改对照（`selftest`，全部在临时符号链接副本上）

| # | 注入的故障 | `verify` 结果 | 退出码 | 命中的判定 |
|---|---|---|---|---|
| 0 | 无（干净副本） | ok | **0** | — |
| 1 | 翻转某检查点一个字节（**长度不变**） | RED | **1** | `sha256_changed` |
| 2 | 用另一个已登记检查点的字节覆盖当前检查点（基线互换） | RED | **1** | `size_changed` |
| 3 | 把某登记文档截断成 `{}` | RED | **1** | `size_changed` |
| 4 | 删除某 C0 数据集文件 | RED | **1** | `missing` |
| 5 | 在某检查点旁塞入未登记的 `smuggled-extra.safetensors` | RED | **1** | `unexpected_new_file` |
| 6 | 对 RunStore 副本 `UPDATE runs SET state='completed_forged'`（1 行） | RED | **1** | `runstore_entries_changed` + `sha256_changed`（DB 文件本身也变了） |
| 7 | 手工改清单副本里 `files[0].sha256` | RED | **1** | `manifest_digest` + `sha256_changed` |

原样输出：`reports/V9-baseline/selftest.json`、`selftest.stderr`；脚本在这些都通过时打印
`selftest: clean copy green, all 7 injected faults detected` 并 **exit 0**，只要有任一故障没被抓到就 exit 1。

**为什么用符号链接副本**：真实 `artifacts/` 必须保持只读，对照只能改副本；副本里除四个数据库用 APFS `cp -c` 克隆外全是符号链接，校验的仍是真实文件的内容，所以「改坏→变红」测的是同一条代码路径。

## 5. 实际命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
python3 scripts/v9_baseline_manifest.py build      # 4.6 s，写 reports/V9-baseline/baseline_manifest.json
python3 scripts/v9_baseline_manifest.py verify     # 4.6 s，232/232，exit 0
python3 scripts/v9_baseline_manifest.py selftest   # 7.8 s，7/7 注入故障被抓，exit 0
python3 scripts/v9_baseline_manifest.py inventory  # 写 BASELINE_INVENTORY.md
python3 scripts/v9_baseline_manifest.py verify --json > reports/V9-baseline/verify_clean.json
```

二次 `build` 到临时路径与正式清单对比：除 `generated_at` 外**完全相同**（含 `manifest_digest`）。

## 6. 失败与限制（含一处如实说明）

1. **我的一次只读探索更新了 `artifacts/control.sqlite3-shm` 的 mtime**（32 KB 共享内存索引，21:48→21:49）。这是用 `sqlite3.connect(..., mode=ro)` 列 RunStore 表时的 SQLite 行为。主库 `control.sqlite3` mtime 仍是 Oct 14 23:00、`-wal` 仍是 Oct 14 23:17 且 0 字节，均未被写；`-shm` 是纯缓存/索引、不入清单。**此后工具改用 `immutable=1`（WAL 为空时）或临时克隆，不再触碰 artifact 树内的任何文件**。除此之外 `artifacts/` 与 `src/` 零改动（`verify` 232/232 全绿可证）。
2. **清单不覆盖源码、报告正文、非检查点数据**（如 `spacetime/`、`locks/`、测试与日志）。本卡范围是「检查点、登记、RunStore」，如果要冻结 `src/ainerzero/**` 的源码身份，建议另开一卡（或把 `src` 加进 pin 策略后重新 build —— 注意新模块会改变「新增文件」判定，需要同时放宽该类别）。
3. **`-wal/-shm` 不入清单**，因此若将来有进程把 WAL 里未 checkpoint 的内容写回主库，主库 sha 会变红（这是期望行为），但也说明「RunStore 文件级 sha」只在下一次写入前有效；语义身份以行级 `entries_digest` 为准。
4. **D 候选/GridLab 的“能力”未在本卡验证**：本卡只冻结身份，不评价任何检查点的能力或是否应晋升。清单里 32 个 run 全为 `completed` 只表示运行状态，不代表能力通过。
5. **未做**：不加载 MLX/不推理（脚本层面拒绝）、不训练、不下载、不安装、不付费、不提交推送、不删除；未改文件范围外的任何文件。
6. **8 个检查点不在 RunStore 里**（`interrupted-*` 与被中断运行的产物、`pilot-*/probes/*-probes/tensors.safetensors`）：它们仍被冻结（同属 `pilot` 树），台账里标为 `(not in RunStore)`，不是遗漏而是如实标注。

## 7. 交回统筹

- **建议验收 ainerzero.V9.A2**：P0 门槛「基线哈希可复验」现在有可执行证据（`verify` exit 0 / 篡改 exit 1）。
- **后续卡可直接复用**：`ainerzero.V9.A3`（独立复核 A2）应至少复跑 `verify` 与 `selftest`，并对清单策略本身做对抗（例如：把 scratch 里的检查点冒充基线、改动 `policy` 里的排除规则后再篡改、检查 `entries_digest` 是否真随 RunStore 行变化）。
- **需要统筹决定**：是否把 `src/ainerzero/**`（或 `ARCHITECTURE_V9.md` 等设计文档）也纳入冻结范围；本卡按文件范围未做。
