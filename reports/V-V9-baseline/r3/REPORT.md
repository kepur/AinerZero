# ainerzero.V9.A10 独立复核报告：A2 r3 基线清单 C3/T3/RunStore 补修

角色：executor（二级执行层，独立复核者）；负责人：`deepseek-flash-a7k2`；时间：2026-10-20
任务状态：reported；实验状态：completed（纯 CPU、只读核对 + 独立案例实跑；**非**能力验收）
任务依据：relay 任务 `ainerzero.V9.A10`（前置 `ainerzero.V9.A2` reported）；被验 `hub`→`ainerzero.V9.A2` r3
（作者 `opencode-de3b`，**我不是 A2 作者**，也不是 A3 复核者 `musespark-7f3q` / A4 复核者 `deepseek-flash-r7c4`）；
参数 v0 照用未改（`{}`）；只读真实 `artifacts/` 与 A2/A3/A4 产物，只写 `reports/V-V9-baseline/r3/`
输入身份：r3 脚本 `f7160692…3e41`、r3 清单 `2c991f05…be5b`（`manifest_digest 3481b6ad…45e9`）、
r3 报告 `e8cd206e…c5ae3`；A4 复核 `reports/V-V9-baseline/r2/review-results.json`；A3 反例 `reports/V-V9-baseline/adversarial.py`
修改文件：仅新增 `reports/V-V9-baseline/r3/`（复核脚本、证据、本报告、指标、SHA256SUMS）；
**未改**任何被验源码/清单/报告/真实 artifacts
实际执行：`bash reports/V-V9-baseline/r3/run_all.sh`；独立复核 25 项断言 + 11 个自建案例；
真实树开始/结束各复算 497 钉选文件 SHA；作者 verify/selftest 只读复跑
验证结果：**建议通过（PASS）**：A2 r3 对 A4 四项必修的 5 项复核点全部闭合（见 §2）；11/11 自建案例符合预期
（8 个不利反例真实非零 + 3 个必须绿的对照）；真实树前后完整性 497/497、0 mismatch、指纹一致；
r2 产物 3 个身份 SHA 与 A4 记录一致；作者 selftest 22/22 real_copy、17/17 注入故障红、5/5 对照绿
产物：`reports/V-V9-baseline/r3/{REPORT.md,metrics.json,review_r3.py,run_all.sh,evidence/,SHA256SUMS.txt}`
失败与限制：未逐条重跑 A3/A4 的旧用例（A4 harness 针对 r2 脚本）；本文以 8 个新不利反例覆盖其关键类别 +
作者 selftest 17/17 复跑作为“不变松”证据；未验证任何模型能力/训练/评测（本卡只核字节与行级基线可复验性）
交回统筹：是否接受 A2 r3（建议 accept，5 项闭合）；无阻塞决定点

## 摘要（30 行内）

1. 复核对象：A2 r3 对 A4 §9 四项必修（C3 覆盖、policy 自检、T3 钉选树扫描、RunStore 行级裁定、真实拷贝自测）的补修。
2. **C3 闭合**：A4 列出的 46 个残留文件，当前 **44 个钉选 + 2 个带理由排除（`derived_artifact`）**、残留 **0**；
   M0 运行根 `report.json`/`events.jsonl` 等 38 个、pilot `probes/*/{manifest,metadata}.json` 4 个、`dataset.json` 2 个均已钉选。
3. **policy↔清单一致闭合**：独立重写 glob 匹配 + 首规则短路语义后再核算：**26 条 glob、883 次原始命中、
   过滤 volatile 后 497 次要求钉选、0 违规**；files[] 497 条全部能被 policy 规则解释（0 未覆盖）。
   policy 明文声称钉选的 M0 `report.json`/`events.jsonl` 清单实际 **24 个 > 0**，r2 的策略-实现矛盾已消除。
4. **T3 闭合**：我自建“钉选检查点目录内新增未登记 `NOTES.md`”案例 → verify **exit 1、`unexpected_new_file`**；
   文档 `policy.unregistered_file_rule`、实现 `verify()` 的 pinned-tree 扫描、docstring 三处措辞一致。
5. **RunStore 行级裁定闭合**：真实拷贝上 `UPDATE runs` 改一行 → verify **exit 1、`runstore_entries_changed`**；
   合法 `VACUUM`（行不变、文件 size/sha 变化）→ verify **exit 0** + `runstore_file_size_changed` /
   `runstore_file_sha_changed` 两条 warning，与 policy“行级摘要为主、文件级只 warning”自述一致。
6. **真实拷贝自测闭合**：作者 selftest 复跑 **22/22 用例 `real_copy=true`**（`copy_mode=APFS clone (cp -c) / copy2, never a symlink`），
   注入故障 **17/17 变红**、对照 **5/5 保持绿**；我的案例 harness 同样“写入前先 unlink 符号链接/用 `cp -c` 真拷贝”。
7. **r2 产物原样保留**：r2 脚本 `2709475c…`、r2 清单 `71e99efc…`、r2 报告 `d39e5c75…` 与 A4 §1 记录逐一相符；
   r2 `manifest_digest` 仍为 `ee6fc9c9…b2cd3`，无基线漂移；r3 一律新写，未覆盖 r2 目录。
8. **A3/A4 反例未变松**：自建 8 个不利反例覆盖清单 digest/size 篡改、隐藏钉选条目、钉选目录塞入未登记文件、
   等长内容翻转、钉选文件被目录替换、删文件、RunStore 改行——全部真实非零退出并命中预期 problem；
   作者 selftest 17/17 复跑一致，说明检查装置不是恒红也不是放宽。
9. **真实树零写入**：复核开始/结束各复算 **497 个钉选文件**：0 mismatch、584,888,364 B、
   `files_digest=5560de51…b64b0` 前后完全一致；案例全部在 `/tmp` 沙盒。
10. 未做/不声明：不加载任何模型/检查点、不训练、不评测；本卡只证明“字节/行级基线可复验 + 注入篡改必红”，
    不代表任何能力或科学结论。
11. 结论：**建议通过（PASS）**；与 A4 的“不建议验收 r2”相反，r3 已逐项闭合其 4 项必修，可交一级接受。
12. 限制：未逐条重跑 A3/A4 的旧用例（其 harness 绑定 r2 脚本），以关键类别新反例 + 作者 selftest 全量复跑替代；
    作者 verify/selftest 属被验脚本自身的复跑，我另用独立枚举/匹配/案例树作交叉证据（见 §3/§4）。

## 1. 输入身份（本次实测 SHA256）

| 输入 | 路径（相对 AinerZero） | SHA256 |
|---|---|---|
| r3 清单脚本 | `scripts/v9_baseline_manifest_r3.py` | `f7160692854e6c659c4d17211338aa58002294324d791ba424cb1e8e0f8e3e41` |
| r3 清单 | `reports/V9-baseline/r3/baseline_manifest.json` | `2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b` |
| 清单自摘要 `manifest_digest` | 清单字段 | `3481b6ad70991478c658fa2de87d5621208fe69fc50369705cbaaa7492eb45e9` |
| r3 报告 | `reports/V9-baseline/r3/report.md` | `e8cd206e41cf679ea4867f66624b0ae4e1a7d956cc5a381ff3bc486b601c5ae3` |
| A4 复核（打回依据） | `reports/V-V9-baseline/r2/review-results.json` |（只读引用；A4 报告 SHA 见其报告） |
| r2 脚本 / 清单 / 报告（应原样保留） | `scripts/v9_baseline_manifest_r2.py` 等 | `2709475c…e529c` / `71e99efc…674a` / `d39e5c75…bb5d`（与 A4 §1 一致） |
| 真实树钉选集合 | 清单 `files[]` | 497 文件 / 584,888,364 B；指纹 `5560de51…b64b0`（开始=结束） |

## 2. A4 四项必修 → 5 项复核点逐条判定

| # | 复核点（来自任务卡/A4 §9） | 判定 | 独立证据 |
|---|---|---|---|
| 1 | **C3 覆盖**：A4 的 46 个文件逐个钉选或带理由排除；policy 声称钉选与清单一致 | **闭合** | 46/46 有唯一处置：44 钉选（M0 运行根 38、probes 元数据 4、`dataset.json` 2）+ 2 以 `derived_artifact` 排除；残留 0；M0 report/events 清单实际 24 个 >0（§3.1） |
| 2 | **policy 与清单/真实树一致**（新增 policy 自检） | **闭合** | 独立 glob 匹配器：26 glob / 883 原始命中 / 过滤 volatile 后 497 要求钉选 / 0 违规；497 files 全部可解释（§3.2） |
| 3 | **T3**：钉选目录内未登记文件变红 | **闭合** | 自建 N4：钉选检查点目录塞 `NOTES.md` → exit 1 `unexpected_new_file`；policy/docstring 与 `verify()` 扫描一致（§3.3） |
| 4 | **RunStore 行级摘要为准**：VACUUM 不红、改行红 | **闭合** | N8 改一行 → exit 1 `runstore_entries_changed`；N9 合法 VACUUM → exit 0 + size/sha warning；与 policy 自述一致（§3.4） |
| 5 | **写入类自测不经符号链接写真实树** | **闭合** | selftest 22/22 `real_copy=true`、`copy_mode=“never a symlink”`；17/17 故障红、5/5 对照绿；真实树前后完整性 0 mismatch（§4） |
| 6 | r2 产物原样保留（任务卡附加） | **闭合** | r2 三个身份 SHA 与 A4 §1 一致；r2 `manifest_digest=ee6fc9c9…` 不变（§5） |

## 3. 独立复核证据

### 3.1 C3 覆盖（不依赖作者脚本，独立读 A4 清单 + r3 清单 + 真实树）

- 从 `reports/V-V9-baseline/r2/review-results.json` 读出 A4 列出的 46 个残留路径（4 个列表），逐个在真实树确认存在。
- 对每个路径查 r3 清单：`files[]`（钉选）或 `excluded_with_reason[]`（带理由排除）：
  **44 钉选 + 2 排除 + 0 残留**；排除项为 `probe-teacher-cache.npz` / `probe-teacher-cache-manifest.json`（reason=`derived_artifact`）。
- 抽查 policy 声称：`artifacts/m0/*/report.json`、`events.jsonl` 相关钉选条目 **24 个**（r2 为 0，矛盾已消除）。

### 3.2 policy ↔ 清单 ↔ 真实树（独立实现 glob 匹配，不复用作者 `glob_match`）

- 枚举真实 `artifacts/` **51,706** 个文件；按 manifest.policy.pinned 的 10 条规则/26 个 glob 重新匹配，
  模拟首规则短路（volatile 排除、`-wal/-shm` transient、排除清单）：
  **883 次原始命中 → 497 次要求钉选 → 0 违规**；每条命中都在 files[] 且 category 一致。
- 反向：files[] 497 条全部能被 policy 规则解释（0 未覆盖）；作者报告“26 glob / 883 匹配 / 0 违规”被独立复算一致。

### 3.3 T3：钉选目录内未登记文件必须变红（自建 N4）

- 在案例树（只读符号链接 + 写入前 unlink 真实拷贝）里，向一个钉选 `checkpoint.meta` 目录新增 `NOTES.md`，
  用作者 `verify` 子进程实跑：**exit 1，problems 含 `unexpected_new_file`**（`inside_pinned_tree=true` 路径）。
- policy 文本 `unregistered_file_rule`、脚本 docstring、`verify()` 的 pinned-tree 扫描三处措辞一致；
  volatile 规则命中仍按设计豁免（我的 N 案例未改 volatile 规则）。

### 3.4 RunStore 行级裁定（自建 N8/N9，真实 APFS 拷贝上执行 SQL）

| 案例 | 操作（在 `cp -c` 真实拷贝上） | verify 结果 |
|---|---|---|
| N8 | `UPDATE runs SET state=...` 改一行并 commit（断言 rowcount=1） | **exit 1，`runstore_entries_changed`（run-level digest 变化）** |
| N9 | 合法 `VACUUM`（行内容不变；文件大小/sha 变化） | **exit 0**，warning `runstore_file_size_changed` + `runstore_file_sha_changed`，无 `runstore_entries_changed` |

### 3.5 自建案例总表（11 个：8 红 + 3 绿对照，全部符合预期）

| ID | 注入 | 期望 | 实测 |
|---|---|---|---|
| C0 | 干净案例树（无注入） | 绿 | exit 0，problems=[] |
| N1 | 清单副本 `files[].size +1` | 红 | exit 1：`manifest_digest` + `size_changed` |
| N2 | 清单副本 `runstore.entries_digest` + 数据库级 digest 篡改 | 红 | exit 1：`manifest_digest` + `runstore_entries_changed` |
| N3 | 清单副本隐藏一条钉选条目 | 红 | exit 1：`manifest_digest` + `policy_claim_unmet` + `unexpected_new_file` |
| N4 | 钉选 checkpoint 目录新增未登记 `NOTES.md` | 红 | exit 1：`unexpected_new_file` |
| N5 | 钉选文件等长内容翻转（unlink 后写真实拷贝） | 红 | exit 1：`sha256_changed` |
| N6 | 钉选文件被替换为目录 | 红 | exit 1：`missing` |
| N7 | 删除钉选文件 | 红 | exit 1：`missing` |
| N8 | RunStore 改一行 | 红 | exit 1：`runstore_entries_changed` |
| N9 | RunStore 合法 VACUUM | 绿（+warning） | exit 0 + size/sha warning |
| N10 | 排除项（teacher cache npz）追加 1 字节 | 按设计不红 | exit 0（§4 文档边界，非缺陷） |

## 4. 真实树完整性（开始/结束各复算 497 个钉选文件）

| 项 | 开始 | 结束 |
|---|---|---|
| 复算文件数 | 497 | 497 |
| 字节数 | 584,888,364 | 584,888,364 |
| mismatch | 0 | 0 |
| 钉选文件 path+sha 指纹 | `5560de5161ff99d946c4c72e9480434af1ed6e3a3d2c85043b62ca30429b64b0` | 同左 |

- 案例树位于系统临时目录沙盒（macOS `TMPDIR`；本次 run_all 的实际路径见 `evidence/review.json` 的 `case_sandbox`，每次重跑新建）；镜像用只读符号链接，
  **任何破坏性写入前先 `unlink` 断开链接再写真实拷贝**（RunStore 用 `cp -c` 克隆后再执行 SQL），
  代码内有 `assert not target.is_symlink()` 保护；真实树前后指纹一致证明未经符号链接写入。
- 写入面：仅 `reports/V-V9-baseline/r3/`（证据/报告/清单）+ `/tmp` 沙盒；未写 `artifacts/`、未写 r2/A2 r3 目录。

## 5. 作者 verify/selftest 只读复跑（交叉证据，不替代独立核对）

```text
python -B scripts/v9_baseline_manifest_r3.py verify --json
→ exit 0：497/497 pinned ok、problems=[]、policy globs 26、verdict ok
python -B scripts/v9_baseline_manifest_r3.py selftest --selftest-out reports/V-V9-baseline/r3/evidence/author-selftest-replay.json --json
→ exit 0：22 cases / 22 real_copy=true / 17 injected detected / 5 controls green / copy_mode never a symlink
→ 内置真实树完整性 before/after：497 检查、0 mismatch
```

r2 保全：`2709475c…`（r2 脚本）、`71e99efc…`（r2 清单）、`d39e5c75…`（r2 报告）与 A4 §1 逐一相符；
r2 `manifest_digest=ee6fc9c9…b2cd3` 未变。

## 6. 实际命令与退出码（cwd=`/Users/mac/AinerWorkFlow/AinerZero`）

```bash
bash reports/V-V9-baseline/r3/run_all.sh                                    # exit 0（3 步）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V-V9-baseline/r3/review_r3.py \
  --json-out reports/V-V9-baseline/r3/evidence/review.json                  # exit 0（25 断言/11 案例 PASS）
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V-V9-baseline/r3/build_metrics.py  # exit 0
PYTHONDONTWRITEBYTECODE=1 .venv-ainerzero/bin/python -B reports/V-V9-baseline/r3/build_shasums.py  # exit 0
# 复核脚本内部以真实子进程调用被验脚本：（均只读或仅写 /tmp/证据）
#   scripts/v9_baseline_manifest_r3.py verify --json        → exit 0
#   scripts/v9_baseline_manifest_r3.py selftest --selftest-out ... → exit 0
#   每个案例：scripts/v9_baseline_manifest_r3.py verify --root <case> --manifest <case manifest> --json
```

## 7. 发现、限制与未验证

- **未逐条重跑 A3/A4 的旧用例**：A4 harness 绑定 r2 脚本，A3 的 14 例反例面向更早版本；本轮以 8 个新不利反例
  覆盖其关键类别（清单 digest/size、隐藏条目、missing、unexpected_new_file、sha 变化、RunStore 行改动）+
  作者 selftest 17/17 复跑，判定“未变松”。这是证据强度的限制，不是失败。
- **N10（排除项字节改动不红）是设计边界**：A2 r3 §8 已声明排除项/volatile 不哈希；我的复核确认行为与声明一致，
  不作为缺陷。
- 清单登记为“篡改清单自身”只能靠 `manifest_digest` 抓住（RunStore 语义层无独立签名）；这是自摘要方案的固有边界，
  A2 r3 已如实登记，未发现新的可绕过路径（篡改任一登记字段都会触发 `manifest_digest`）。
- 未加载任何模型/检查点；不训练、不评测、不渲染；本卡不构成能力晋升或科学验收。
- 作者 verify/selftest 是“被验脚本的复跑”，我以独立枚举、独立 glob 匹配、独立案例树作交叉证据；
  但二者仍共享同一被验脚本作为判定器，无法证明作者脚本之外不存在其它问题（本卡范围仅限 5 项复核点）。

## 8. 建议（交一级决定）

**建议通过（PASS）ainerzero.V9.A2 r3**：A4 §9 的四项必修（C3、T3、RunStore 大小豁免/行级裁定、真实拷贝自测）
及“policy 声称与清单一致”“r2 原样保留”均闭合，且真实树零写入、r2 无漂移。
无阻塞决定点；若一级接受，建议把 C3/T3/RunStore 三类新反例（本目录证据）作为后续变更的常驻回归参考。

## 9. 产物与证据

| 文件（`reports/V-V9-baseline/r3/`） | 内容 |
|---|---|
| `REPORT.md` | 本报告 |
| `metrics.json` | 指标汇总（由 `build_metrics.py` 从 `evidence/review.json` 生成，不手抄） |
| `review_r3.py` | 独立复核脚本（25 断言 / 11 自建案例 / 前后完整性） |
| `run_all.sh` | 3 步一键重跑 |
| `build_metrics.py` / `build_shasums.py` | 指标聚合 / 证据 SHA256SUMS |
| `evidence/review.json` / `.log` | 复核明细（C3/policy/selftest/案例/完整性） |
| `evidence/author-verify.log` | 作者 verify 只读复跑（exit 0，497/497，policy 26） |
| `evidence/author-selftest-replay.json` / `.log` | 作者 selftest 复跑（22 real_copy、17/17 红、5/5 绿） |
| `SHA256SUMS.txt` | 本目录全部产物（除自身）的 SHA256 清单，路径相对仓库根 |

- 临时沙盒：系统 `TMPDIR` 下的 `v9-a10-r3-cases-<随机>/`（每次重跑新建，未删除；实际路径见 `evidence/review.json` 的 `case_sandbox`）。
- 模型/训练/下载/安装/付费/提交推送/删除：0；未启动服务；真实 `artifacts/` 前后指纹一致（§4）。
