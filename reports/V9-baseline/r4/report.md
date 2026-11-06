# ainerzero.V9.A15 r4 报告：A2 基线清单 r4（核实 r3 红项并纳入 10-20 后的合法新增）

**【无违规】** 经逐条核实，r3 报错的 8057 项全部为 10-20 之后的合法新增文件（N=8057, M=0, D=0），无任何内容篡改或丢失违规。

## 摘要（≤30 行）
1. **r3 核实结论**：`r3-verify-before.json` 中 8057 个 problem 均为新文件（N 类：8027 `unexpected_new_file` + 30 `policy_claim_unmet` 新增匹配），M（内容变化）为 0，D（文件缺失）为 0。原 497 个钉选文件 497/497 逐字节完好，无基线漂移。
2. **r4 脚本设计**：新写 `scripts/v9_baseline_manifest_r4.py`，r3 脚本与 `reports/V9-baseline/r1|r2|r3/` 字节零修改。
3. **覆盖范围**：全面纳入 E1 phase2/phase2-r2（检查点、eval、prereg、datasets 清单、sealed_final）、S1 phase1/datasets/final-sealed、教师权重（t4-approved、da3）、RunStore 库（8 处 SQLite 行级 entries_digest）。
4. **排除与未分类**：macOS `.DS_Store` 与 E1 中间序列 JSON（raw/evaluator/student 共 7600 件）逐类写明理由排除；范围外 4284 件；未分类文件严格为 **0**。
5. **两次构建一致性**：`build` exit 0，`manifest_digest bb396582c682f000…`，两次构建载荷逐字节相同（`generated_at` 除外）。
6. **基线验证**：`verify` exit 0，919/919 钉选文件全部通过，0 problem，0 warning，55 条 policy globs 全绿。
7. **自测试验（24 例全过）**：保留 r3 全部 22 用例，新增两例故障注入（E1 phase2 检查点目录注入 NOTES.md -> `unexpected_new_file`；sealed_final 改一字节 -> `sha256_changed`），19 例注入全部变红（19/19），5 例对照全部保持绿。
8. **实盘零写入**：运行前后对 `artifacts/` 范围内全量 **63064 个文件** 做 stat（mtime_ns/size/inode，含 `-wal`/`-shm`）与 497 个原始钉选文件 SHA 对比，0 mismatch，实盘零改动。
9. **交付候选状态**：r4 是候选清单；在一级统筹验收签字前，r3 仍为现行冻结门。

---

## 1. r3 红项逐条核查与 N/M/D 分类统计

| 类别 | 判定标准 | 计数 | 处置说明 | 是否违规 |
|---|---|---:|---|---|
| **N (New)** | 10-20 后的合法新增（`unexpected_new_file` 或新增匹配 `policy_claim_unmet`） | **8057** | 纳入 r4 清单：根据交付属性钉选、排除或瞬态处理 | **否（合法新增）** |
| **M (Modified)** | 钉选文件内容/大小变化或 `runstore_entries_changed` | **0** | 无任何文件发生变动 | **无** |
| **D (Disappeared)** | 钉选文件缺失（`missing`） | **0** | 497 个基线文件全部完好存在 | **无** |

### N 类分布来源明细
- `artifacts/v9/e1/phase2/`：7696 个新文件（54 检查点、26 eval、5 prereg/control、11 清单/sealed_final，7600 中间轨迹 JSON）；
- `artifacts/v9/e1/phase2-r2/`：83 个新文件（54 检查点、26 eval、3 prereg/control）；
- `artifacts/v9/s1/`：228 个新文件（217 phase1 产物、6 datasets、5 final-sealed）；
- `artifacts/teachers/`：16 个新文件（12 t4-approved、4 da3）；
- `artifacts/v9/teachers/`：3 个新文件（benchmark runs.db 及 -shm/-wal）；
- `artifacts/.DS_Store`：1 个系统元数据文件；
- 原始输出已完整归档于 `reports/V9-baseline/r4/r3-verify-before.json`。

---

## 2. r4 基线统计与分类处置表

| 处置类别 | 数量 | 规则说明与涵盖内容 |
|---|---:|---|
| **钉选文件 (`files[]`)** | **919** | 钉选 919 个交付文件 / 2,965,780,952 字节：<br>• `checkpoint` (396): safe-tensors/npz 检查点权重及元数据<br>• `registration` (146): 预登记、登记与校验和文件<br>• `eval.report` (116): 评测结果与执行报告<br>• `m0.run` (38), `dataset.c0` (80), `dataset.gridlab2d` (76)<br>• `dataset.sealed_final` (19): sealed_final 封存集与清单（仅按字节哈希，不解析、不触发 read_once）<br>• `runstore.file` (8): 8 个 RunStore 数据库（行级 entries_digest） |
| **逐个写理由排除 (`excluded_with_reason[]`)** | **7701** | • `e1_dataset_intermediates` (7600): E1 中间轨迹 JSON 与分割数据，由 SHA256SUMS 与 manifest 承载<br>• `derived_artifact` (10): 派生 teacher 缓存<br>• `episode_data` (80): 原始 episode 轨迹数据<br>• `runtime_lock` (1): 运行时锁文件 `m0-worker.lock`<br>• `os_metadata` (10): 系统 `.DS_Store` 元数据 |
| **瞬态文件 (`transient[]`)** | **8** | SQLite `-wal` 与 `-shm` 辅助文件 |
| **Volatile 临时检查点 (`volatile_checkpoints[]`)** | **312** | 测试 scratch 中的临时 checkpoint，仅记录路径与前缀 |
| **范围外文件 (`out_of_scope`)** | **4284** | `artifacts/reports/**` 与 `artifacts/spacetime/**` 下的非登记文件 |
| **未分类文件 (`unclassified`)** | **0** | **严格为 0，规则全覆盖无遗漏** |

---

## 3. 自测（Selftest）24 例全量矩阵

| 序号 | 用例名称 | 类别 | 注入操作 | 预期 | 实际结果 |
|---|---|---|---|---|---|
| 1 | `clean_real_copy` | 对照 | 干净 APFS 克隆副本 | 绿 | EXIT 0 绿 |
| 2 | `checkpoint_byte_flip` | 故障 | 检查点翻转 1 字节 | 红 | EXIT 1 红 (`sha256_changed`) |
| 3 | `checkpoint_swapped` | 故障 | 检查点文件互换 | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 4 | `tamper_checkpoint_meta` | 故障 | 截断 checkpoint metadata | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 5 | `tamper_m0_run` | 故障 | 截断 M0 report.json | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 6 | `tamper_run_config` | 故障 | 截断 pilot report.json | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 7 | `tamper_run_updates` | 故障 | 截断 updates-*.jsonl | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 8 | `tamper_probe_meta` | 故障 | 截断 probe manifest.json | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 9 | `tamper_dataset_c0` | 故障 | 截断 C0 数据集文件 | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 10 | `tamper_dataset_gridlab2d` | 故障 | 截断 GridLab2D 数据集文件 | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 11 | `tamper_registration` | 故障 | 截断 registration.json | 红 | EXIT 1 红 (`sha256_changed`, `size_changed`) |
| 12 | `dataset_file_deleted` | 故障 | 删除 GridLab2D 文件 | 红 | EXIT 1 红 (`missing`) |
| 13 | `t3_notes_in_checkpoint_dir` | 故障 | 检查点目录注入 NOTES.md | 红 | EXIT 1 红 (`unexpected_new_file`) |
| 14 | `t3_notes_in_m0_run_root` | 故障 | M0 运行根注入 NOTES.md | 红 | EXIT 1 红 (`unexpected_new_file`) |
| 15 | `t3_notes_in_dataset_dir` | 故障 | C0 目录注入 NOTES.md | 红 | EXIT 1 红 (`unexpected_new_file`) |
| 16 | `t3_smuggled_safetensors` | 故障 | 偷运 safetensors | 红 | EXIT 1 红 (`unexpected_new_file`) |
| 17 | **`t3_e1_notes_in_checkpoint_dir`** | **新增故障** | **E1 phase2 检查点目录注入 NOTES.md** | **红** | **EXIT 1 红 (`unexpected_new_file`)** |
| 18 | **`sealed_final_byte_flip`** | **新增故障** | **E1 phase2 sealed_final 翻转 1 字节** | **红** | **EXIT 1 红 (`sha256_changed`)** |
| 19 | `volatile_scratch_allowed` | 对照 | tmp 目录下新增 safetensors | 绿 | EXIT 0 绿 |
| 20 | `out_of_scope_report_allowed` | 对照 | reports 目录下新增文档 | 绿 | EXIT 0 绿 |
| 21 | `runstore_vacuum_allowed` | 对照 | 对 control.sqlite3 执行 VACUUM | 绿 | EXIT 0 绿（带 warning） |
| 22 | `runstore_row_forged` | 故障 | control.sqlite3 篡改 1 行 | 红 | EXIT 1 红 (`runstore_entries_changed`) |
| 23 | `manifest_self_edited` | 故障 | 修改清单自身哈希 | 红 | EXIT 1 红 (`sha256_changed`) |
| 24 | `excluded_file_tamper_stays_green` | 对照 | 修改排除项文件内容 | 绿 | EXIT 0 绿（符合排除契约） |

- **总计**：19/19 故障注入全部变红，5/5 对照保持绿，`all_detected: true`。

---

## 4. 实盘零写入证据

- **扫描基数**：`artifacts/` 下全量 63,064 个文件；
- **校验维度**：每个文件的 `st_mtime_ns`、`st_size`、`st_ino` 以及 497 个原始钉选文件 SHA256；
- **对比结果**：`stat_comparison.json` 记录 0 mismatches，`artifacts_tree_strictly_unchanged = true`。

---

## 5. 产物 SHA256 校验清单

```
097090d974f8c111c36e7e1460e3e2b230caf056454cb9b2bda8d34a6ae3aed1  scripts/v9_baseline_manifest_r4.py
ce11aff128ab8235d4e9a2fd88e4ff9f39b662bf1cb1c6c7009c49a949bf2dcd  reports/V9-baseline/r4/baseline_manifest.json
f2a5c367208c941449c27811197b75c1cc6c2934695bf8e46d94611943e08499  reports/V9-baseline/r4/BASELINE_INVENTORY.md
b969af3b23ffbc73198d1a818f438994fd0cd14fd9f4b64cc34efaaa57f57e25  reports/V9-baseline/r4/selftest.json
4a3eea3b6e7e6c5fc67f87f87acb5d7f8483687048a325dc1b65df0e9962125e  reports/V9-baseline/r4/verify_clean.json
931d4adfeaa69b148b9a397ab7ab09f82e4e69920e8f814eec6ac7a5a606fd90  reports/V9-baseline/r4/r3-verify-before.json
7f0ba3b1ae573a9dbe11d671cd65e1930e78afe26881402f00738163c36413e6  reports/V9-baseline/r4/stat_comparison.json
```
