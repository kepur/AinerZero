# ainerzero.V9.A2 r3 报告：基线冻结清单 v3（C3 覆盖 / T3 钉选目录扫描 / RunStore 行级裁定）

- 任务：ainerzero.V9.A2【代码】基线冻结清单 · 第 3 棒（r3）
- 执行：`deepseek-v4f-k2m9`（二级）· 2026-10-20（+03）· 纯 CPU、只读、无下载/无安装/无付费/无提交
- 参数：v0 `{}` 照用未改
- 产物：`scripts/v9_baseline_manifest_r3.py` + `reports/V9-baseline/r3/`（r2 与 r1 证据原样保留，见 §7）

## 摘要（≤30 行）

1. 清单 v3 覆盖真实 `artifacts/` 下 **51706 个文件**，逐个给出唯一处置：**钉选 497 / 逐个理由排除 89 / 瞬态 4 / volatile 46832 / 范围外 4284 / 未分类 0**。
2. `build` → exit 0，`manifest_digest 3481b6ad…45e9`，497 文件 / 584,888,364 B；两次 build 载荷逐字节相同（仅 `generated_at` 不同）。
3. `verify` → exit 0：**497/497 条目逐个重算 SHA**（其中 4 个 RunStore 数据库走行级摘要），problems=[]、warnings=[]、政策 glob 26 条全过。
4. **补修 1（C3 覆盖，已闭合）**：A4 §3 的 46 个文件 → **钉选 44**（M0 运行根 `report.json`/`events.jsonl`/`config.yaml`/`requested_config.yaml` 38、pilot `probes/*/manifest|metadata.json` 4、`dataset.json` 2）+ **逐个排除并写理由 2**（`probe-teacher-cache.{npz,json}`）。r2 policy 声称钉选 M0 report/events 而清单为 0 的矛盾已消除。
5. **补修 1 附带**：policy 现由 `RULES` 单一来源生成，新增自检 `check_policy()`：policy 声称钉选的每条 glob 在真实树上**每个匹配**都必须在 `files[]`（volatile 例外），否则 build 失败、verify 变红 `policy_claim_unmet`。实测 26 条 glob / 883 次匹配 / 0 违规。
6. **补修 2（T3，已闭合）**：任何落在“钉选树”（含钉选文件的目录及其子树）内、且不在 `files[]`/`excluded_with_reason[]`/`transient[]` 的文件 → `unexpected_new_file` 红；只有 volatile 规则例外。docstring、policy、实现三处措辞一致。Selftest 注入 4 例（检查点目录 `NOTES.md`、M0 运行根 `NOTES.md`、C0 目录 `NOTES.md`、检查点目录 `smuggled-extra.safetensors`）**全部变红**。
7. **补修 3（RunStore，已闭合）**：行级 `entries_digest` 为主身份；行摘要不变时文件的 sha/size 变化只记 **warning**（VACUUM 合法维护），行摘要变化才红 `runstore_entries_changed`。Selftest 在真实拷贝上 `VACUUM`（63,201,280 → 63,180,800 B）**保持绿并给出 2 条 warning**；同拷贝改一行 **变红**。r3 行级总摘要 `18e491ef…` 与 r2 **完全一致**（无基线漂移）。
8. **补修 4（禁止经符号链接写真实树）**：自测用例树改为 **真实 APFS 克隆**（`cp -c`，断言 `symlinks=0`、`same_inode_as_real_tree=0`，回退 `shutil.copy2`）。**22 个用例全部 `real_copy=true`**。
9. **补修 4 附带**：selftest 前后对**真实树 497 个钉选文件**（含 r2 的 453 子集）重算 SHA：`before=true, after=true`，`real_tree_integrity.json` 0 mismatch。
10. **自测总账**：22 用例 = **17 个注入故障全部变红（17/17）** + **5 个对照全部保持绿**（干净拷贝、volatile 新增、范围外新增、合法 VACUUM、排除项篡改）。脚本真实非零退出，不是恒红装置。
11. **额外旁证 5 例（作者自查，`extra_probes.json`）**：钉选检查点移出原目录、等长字节改写、第二个 RunStore 删一行、清单隐藏一条目、删掉整个 `gridlab2d` 树 —— 5/5 exit 1 且命中预期 problem。
12. **明确未解决/未验证**（§8）：排除项（teacher cache、episodes、锁文件）按定义不哈希，改其字节**不会**变红（selftest 有对照证明这是设计而非疏漏）；`artifacts/reports/**`、`artifacts/spacetime/**` 除登记外为范围外，新增文件不红；volatile 只看路径不看字节。
13. **测试通过不等于能力通过**：本卡只证明“字节/行级基线可复验、注入篡改必红”，不证明任何检查点能力、训练或评测结果。
14. 结论：r3 已按 A4 §9 的四项必修逐条闭合，建议交**非作者**复核（重点 C3 覆盖计数、T3 边界、RunStore 双向用例、真实拷贝模式）。

## 1. 输入与源码身份（SHA256）

| 输入 | 路径（相对 AinerZero） | SHA256 |
|---|---|---|
| r3 脚本（本卡作者） | `scripts/v9_baseline_manifest_r3.py` | `f7160692854e6c659c4d17211338aa58002294324d791ba424cb1e8e0f8e3e41` |
| r3 清单 | `reports/V9-baseline/r3/baseline_manifest.json` | `2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b` |
| r2 脚本（未改动） | `scripts/v9_baseline_manifest_r2.py` | `2709475caac0ef8f3d92ac2023d94156c11cfd63ac13eb00c454ecdb715e529c` |
| r2 清单（未改动） | `reports/V9-baseline/r2/baseline_manifest.json` | `71e99efcc1ceb652df742396d3bbbfdbc72ac7cd5e46c980171e33065a2d674a` |
| r2 报告（未改动） | `reports/V9-baseline/r2/report.md` | `d39e5c75bcfb244c25b9a7eb76f99446b5228fdbcd017318f414d6358a83bb5d` |

三条 r2 身份与 A4 复核报告 §1 登记值逐一相符 → **r2 证据未被改写**。r2 的 `manifest_digest`（`ee6fc9c9…b2cd3`）与 r3 的 `runstore.entries_digest`（`18e491ef…`）均与 r2 记录一致。

## 2. 实际命令与退出码

均为 `cd /Users/mac/AinerWorkFlow/AinerZero && PYTHONDONTWRITEBYTECODE=1 python3 scripts/v9_baseline_manifest_r3.py <cmd>`；
临时目录由 `tempfile.TemporaryDirectory(prefix="v9-baseline-r3-")` 创建（`/var/folders/zv/…/T/`，运行结束自动删除），自测用例树为 `…/v9-baseline-r3-*/<case>`。

| 命令 | exit | 关键输出 | 日志 |
|---|---|---|---|
| `build` | **0** | 497 files / 584,888,364 B · excluded 89 · transient 4 · volatile 312 · out-of-scope 4284 · unclassified 0 · policy violations 0 · digest `3481b6ad…` | `log-build.txt` |
| `verify` | **0** | `497/497 pinned entries checked, policy globs 26, verdict ok` | `log-verify.txt` |
| `selftest` | **0** | `17/17 injected faults detected, 5/5 controls green, real tree unchanged (497 pinned files re-hashed before and after)` | `log-selftest.txt` / `selftest.json` |
| `inventory` | **0** | 41 checkpoints / 33 路径组 / 88 registrations → `BASELINE_INVENTORY.md` | `log-inventory.txt` |
| `integrity` | **0** | 497 pinned files re-hashed, 0 mismatches | `log-integrity.txt` / `real_tree_integrity.json` |
| `policy-check` | **0** | checked_globs 26 · matched_files 883 · violations 0 | `log-policy-check.txt` |
| 两次 `build` 对比 | **0** | 载荷除 `generated_at` 外逐字节相同（TMPDIR 内第二份清单） | 本报告 §0 摘要 2 行 |
| 额外旁证 `extra_probes.py`（TMPDIR 内） | **0**（5/5 用例按预期变红） | 见 `extra_probes.json` / `extra_probes.log` | — |

## 3. 清单摘要（r3）

| 类别 | 文件 | 字节 |
|---|---|---|
| `checkpoint`（`*.safetensors`，仅按字节哈希） | 41 | 119,999,100 |
| `checkpoint.meta`（manifest/metadata） | 78 | 5,668,359 |
| `m0.run`（**新增**：M0 运行根 report/events/config） | 38 | 116,112 |
| `probe.meta`（**新增**：pilot `probes/*/{manifest,metadata}.json`） | 4 | 10,077 |
| `run.config`（含**新增** 2 个 `dataset.json`） | 135 | 297,566,033 |
| `run.updates` | 10 | 718,632 |
| `registration` | 88 | 78,918,526 |
| `dataset.c0` | 8 | 492,682 |
| `dataset.gridlab2d` | 91 | 13,237,307 |
| `runstore.file` | 4 | 68,161,536 |
| **合计** | **497** | **584,888,364** |

处置账（合计 51706 = 真实 `artifacts/` 文件总数）：
钉选 497 + 逐个理由排除 89（teacher_cache 8、episode_data 80、runtime_lock 1）+ 瞬态（`-wal`/`-shm`）4 +
volatile 46832（30 个 `tmp`/`tmp-*` 目录，其中 312 个 `*.safetensors` 逐个登记）+ 范围外 4284（`artifacts/reports/**`、`artifacts/spacetime/**` 的非登记文件）+ **未分类 0**。

RunStore：4 个数据库行级摘要 `9f2bfac5…`(control.sqlite3)、`0087b277…`(.bak-20261011)、`de00db1c…`(m0/control.sqlite3)、`4f53cda1…`(run_store.db)；总 `18e491ef…`；`runs_with_checkpoints` 32；仅存在于 volatile scratch 的 run：none。

## 4. r2 → r3 差异（新增钉选/排除计数）

| 项 | r2 | r3 | 差 | 内容 |
|---|---|---|---|---|
| 钉选文件 | 453 | 497 | **+44** | `m0.run` +38、`probe.meta` +4、`run.config` +2（`dataset.json`） |
| 逐个理由排除 | 86 | 89 | **+3** | `pilot-0f6247…/probe-teacher-cache.npz`、`…-manifest.json`、`artifacts/locks/m0-worker.lock` |
| 瞬态（新显式类别） | 未登记 | 4 | +4 | `control.sqlite3{-wal,-shm}`、`m0/control.sqlite3{-wal,-shm}` |
| volatile 登记 | 312 检查点（其余 46520 个 tmp 文件**静默忽略**） | 312 检查点 + 30 个目录聚合（46832 文件） | — | 现在每个 volatile 文件都有归属，仍不按字节钉选 |
| 范围外 | 未声明（50749 文件静默忽略） | 4284 非登记文件 + 49 登记钉选 | — | 范围显式化，登记仍钉选 |
| 未分类 | 未定义 | **0**（build 遇到即拒绝） | — | 策略与实现不可再漂移 |
| 行级 RunStore 摘要 | `18e491ef…` | `18e491ef…` | 0 | 基线语义未漂移 |

## 5. A4 §9 四项必修逐条证据

**(1) C3 覆盖 + policy 一致性.** 46 个残留文件 → 44 钉选、2 逐个排除（`probe-teacher-cache*`，理由 derived_artifact，按 `*teacher-cache*` 后缀匹配，修 r2 精确名漏网）。`policy.pinned` 不再是手写散文，而由 `RULES` 生成；`check_policy()` 对 26 条 glob 的 883 次真实匹配逐条核对（含 49 个 `artifacts/reports/**` 下登记、312 个 volatile 例外），violations=[]。r2 的“声称钉选 M0 report/events 而实际 0 条”矛盾消失（现 38 条 `m0.run`）。

**(2) T3 扫描边界.** `verify` 先建“钉选树前缀集”（每个钉选文件的全部祖先目录），再遍历真实树：新文件若属钉选类别或落在钉选树内 → `unexpected_new_file`（红）；volatile 规则命中 → 绿。docstring 首段、`policy.unregistered_file_rule`、实现三处一致。Selftest 4 例注入全部 exit 1，problems 含 `unexpected_new_file`（其中 2 例同时命中 `policy_claim_unmet`，说明两道闸都生效）。

**(3) RunStore 裁定.** 见摘要 7：`verify` 对 `runstore.file` 类条目只记 `runstore_file_size_changed` / `runstore_file_sha_changed` 两条 warning，红判据只有 `runstore_entries_changed`（并列出变化表）。`runstore_vacuum_allowed` exit 0 + 2 warning；`runstore_row_forged` exit 1 + `runstore_entries_changed`。policy 文本与实现逐句对应（`policy.runstore`）。

**(4) 真实拷贝 + 真实树完整性门.** `make_case_tree()` 对 590 个文件做 `cp -c` 克隆（失败回退 `shutil.copy2`），随后遍历断言 `symlinks=0`、`same_inode_as_real_tree=0`；22 个用例 `real_copy=true` 全为真。`real_tree_integrity()` 在 selftest 前后各对真实树 497 个钉选文件重算 SHA，结果写入 `selftest.json.real_tree_integrity` 与本报告摘要 9。

**(5) 证据不可覆盖.** r2 的脚本/清单/报告未改动（§1 三条 SHA 与 A4 记录一致），r3 一律新写到 `reports/V9-baseline/r3/` 与新文件 `scripts/v9_baseline_manifest_r3.py`；r2 脚本仅在 r3 脚本里作为历史背景被引用，未被调用改写。**注意**：为确认基线未漂移，本次只对 r2 清单执行了只读 `verify`（不写 r2 目录）。

## 6. 自测用例清单（22）

| # | 用例 | 期望 | exit | 命中 |
|---|---|---|---|---|
| 1 | `clean_real_copy` | 绿 | 0 | —（problems/warnings 均空） |
| 2 | `checkpoint_byte_flip`（等长翻位） | 红 | 1 | `sha256_changed` |
| 3 | `checkpoint_swapped`（用另一个基线覆盖） | 红 | 1 | `size_changed` |
| 4–11 | 8 个类别各截断一次（checkpoint.meta / m0.run / run.config / run.updates / probe.meta / dataset.c0 / dataset.gridlab2d / registration） | 红 | 1 | `size_changed` |
| 12 | `dataset_file_deleted` | 红 | 1 | `missing` |
| 13 | `t3_notes_in_checkpoint_dir`（塞 `NOTES.md`） | 红 | 1 | `unexpected_new_file` |
| 14 | `t3_notes_in_m0_run_root` | 红 | 1 | `unexpected_new_file` |
| 15 | `t3_notes_in_dataset_dir` | 红 | 1 | `unexpected_new_file` + `policy_claim_unmet` |
| 16 | `t3_smuggled_safetensors`（塞未登记 `*.safetensors`） | 红 | 1 | `unexpected_new_file` + `policy_claim_unmet` |
| 17 | `volatile_scratch_allowed`（`tmp-*` 下塞 safetensors） | 绿 | 0 | warning `volatile_prefix_added` |
| 18 | `out_of_scope_report_allowed`（`artifacts/reports/**` 塞 md） | 绿 | 0 | — |
| 19 | `runstore_vacuum_allowed`（真实拷贝上 VACUUM） | 绿 | 0 | warning `runstore_file_size_changed` + `runstore_file_sha_changed` |
| 20 | `runstore_row_forged` | 红 | 1 | `runstore_entries_changed` |
| 21 | `manifest_self_edited` | 红 | 1 | `manifest_digest` + `sha256_changed` |
| 22 | `excluded_file_tamper_stays_green`（排除项追加字节，**已知盲区对照**） | 绿 | 0 | —（设计如此，见 §8） |

额外旁证（`extra_probes.json`，同一真实拷贝装置、独立脚本）：`moved_pinned_checkpoint` → `missing`+`unexpected_new_file`+`policy_claim_unmet`；`same_size_byte_edit`（M0 report 末尾翻位）→ `sha256_changed`；`second_runstore_row_deleted`（m0/control.sqlite3）→ `runstore_entries_changed`；`manifest_entry_hidden` → `manifest_digest`+`unexpected_new_file`+`policy_claim_unmet`；`gridlab2d_tree_deleted` → 大量 `missing`。5/5 exit 1。

## 7. 失败、事故与偏离

- **本轮无事故**：未对真实 `artifacts/` 做任何写操作；selftest 前后真实树 497 文件 SHA 复算 0 mismatch。r2 目录与本卡范围外文件未改。
- 初版 selftest 16/17：`checkpoint_swapped` 用例自身写错（donor==victim，等价于“没有篡改”），已改为选取不同大小的真实检查点对；**这是用例缺陷而非检测缺陷**，修正后 17/17。
- 初版 `scan()` 把 46832 个 volatile 文件逐个写入清单（清单膨胀、噪声大），改为“312 个检查点逐个登记 + 30 个 tmp 目录聚合（files/checkpoints/paths_digest）”，语义不变、体积可控。
- 初版 `verify` 对精简用例树误报 `volatile_prefix_removed`/`volatile_checkpoint_removed`（用例树不复制范围外/volatile 文件），已改为“仅当该 tmp 目录在树中存在时才比对”，干净用例回到 0 warning。
- 与 r2 的偏离：r2 的 `excluded_transient` 只是 policy 里一句声明、实现未落；r3 落成显式 `transient[]` 类别（4 条）。r2 的 `artifacts/reports/**`、`artifacts/spacetime/**` 从未声明，r3 显式声明为范围外。

## 8. 未验证 / 有意不覆盖（不得外推）

1. **排除项字节不受保护**：teacher cache（8）、episode 数据（80）、`m0-worker.lock`（1）按理由排除，只登记路径/大小，改字节**不会**变红；`excluded_file_tamper_stays_green` 用例把这个盲区显式留作对照。若要求“改也不许改”，需把它们也钉选（本卡裁定是“逐个给理由”）。
2. **范围外树不设防**：`artifacts/reports/**`、`artifacts/spacetime/**` 的非登记文件新增/修改不会变红（仅登记文件钉选）。这是本卡显式声明的边界，非疏漏。
3. **volatile 只看路径不看字节**：312 个检查点登记的是名字，tmp 下内容变化不红（测试 scratch 的合法重写）。故“某检查点是否仍是原字节”只对 497 个钉选文件成立。
4. 未做多进程/跨机器并发写 RunStore、跨文件系统 VACUUM、崩溃恢复、多版本 SQLite 兼容性验证。
5. 未运行 MLX/模型/渲染/训练/评测，不评价任何检查点能力；`inventory` 的 run 归属用路径子串匹配，M0 检查点目录名（`m0-cpu-*`/`m0-gpu-*`）不含 RunStore `run_id`，故表格显示 `not in RunStore`（与 r2 行为一致，未修改匹配逻辑）。
6. 未对 51706 个文件中的 volatile/范围外文件做内容枚举取证（只做路径级归属），其“是否真为测试产物”采信路径规则与 r2/A4 结论。

## 9. 产物与终值 SHA256

| 文件 | SHA256 |
|---|---|
| `scripts/v9_baseline_manifest_r3.py` | `f7160692854e6c659c4d17211338aa58002294324d791ba424cb1e8e0f8e3e41` |
| `reports/V9-baseline/r3/baseline_manifest.json` | `2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b` |
| `reports/V9-baseline/r3/BASELINE_INVENTORY.md` | `bd5e7501c820531296e383d9f77d2d6c38ed76464967eba353808fe458ba41c8` |
| `reports/V9-baseline/r3/selftest.json` | `2ee1d4a052d4b23d6dcca234bb20e9cb2450e707a32b56db01746c3291e03c40` |
| `reports/V9-baseline/r3/extra_probes.json` | `d07e77d19f78991686da611b562cbd6c21c6953e0dfc9f161c9c6e2a1ea0f6a1` |
| `reports/V9-baseline/r3/real_tree_integrity.json` | `c4ef5ddc485321a3d6f0a0c0ff342232d18a6414b40b8b62abc43d68bb2badca` |
| 本报告 `report.md`（写入后终值） | `b9bcd1b63ce57f012359d6e597c02d754f329815c268f69ead43b555abaa812e`（本表更新前的终值；改动本表会让自身 SHA 再变，以文件为准） |

复跑（只读，不改交付物）：

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
PYTHONDONTWRITEBYTECODE=1 python3 scripts/v9_baseline_manifest_r3.py verify     # exit 0 = 497 条基线未变
PYTHONDONTWRITEBYTECODE=1 python3 scripts/v9_baseline_manifest_r3.py selftest   # exit 0 = 17 例全红 + 5 例对照绿
PYTHONDONTWRITEBYTECODE=1 python3 scripts/v9_baseline_manifest_r3.py policy-check
```

## 10. 交回

请一级指派**非作者**复核（A4 的复核者是 `deepseek-flash-r7c4`，作者是 `opencode-de3b`；本棒作者 `deepseek-v4f-k2m9`）。
建议复核重点：C3 的 44+2 计数是否与真实树一致、T3 的“钉选树”边界是否过宽/过窄、RunStore 双向用例、真实拷贝断言（`symlinks=0`）、以及 §8 的 6 条限制是否被接受。
