# ainerzero.V9.A16 非作者复核报告：V9.A15 A2 基线清单 r4 终审

**自证声明**：我是二级执行代理 `gemini-b9x2`，独立承担本次复核任务。本人并非 V9.A15 的作者 `gemini-f8a2`，亦非其同会话别名。本次复核全程基于只读核查与 APFS 独立克隆测试，未修改任何源码、清单或实盘文件。

**最终审核结论**：**`RECOMMEND_ACCEPT`**（建议全量采纳，无阻断性缺陷）。

---

## 摘要（≤30 行）
1. **审核目标**：复核 V9.A15 r2 成果（位于 `reports/V9-baseline/r4/r2/`），该轮修复了 F1 漏洞（按方案 a 将 7,600 个 E1 数据文件以 `dataset.e1` 直接按字节钉选）。
2. **r3 零改动**：独立比对 `scripts/v9_baseline_manifest_r3.py` 及 `reports/V9-baseline/` 下全部 r1/r2/r3 历史文件（共 30 项），与 `git HEAD` 逐字节比对 SHA256，不符项为 **0**。
3. **N/M/D 准确性**：独立执行 r3 `verify`，确认其实盘只读保护机制生效（SQLite WAL 为空时使用 `mode=ro&immutable=1`，非空时克隆至临时目录）。核实 8,057 项问题全为合法新增（N=8,057，其中 8,027 `unexpected_new_file` + 30 `policy_claim_unmet`；M=0；D=0），抽查 5 项文件均属真实模型与协议交付物，无违规被吸收。
4. **sealed_final 纯字节审计**：审查 `scripts/v9_baseline_manifest_r4.py`，确认对 `sealed_final/**` 仅按 1MB 数据块做纯字节 SHA256，无任何 `np.load`、无 JSON 解析，未创建任何标记文件。
5. **门是真的门（自做变异）**：在 APFS 克隆副本（确认 inode 独立且非软链接）实施 5 处作者自测集外的独立变异：
   - 改动新钉选 E1 checkpoint_meta 1 字节 -> **RED** (`sha256_changed`, exit 1)；
   - 删除新钉选 E1 raw manifest.json -> **RED** (`missing`, exit 1)；
   - 篡改 E1 phase2 `control.sqlite3` runs 表 1 行 -> **RED** (`runstore_entries_changed`, exit 1)；
   - 改动排除项 `m0-worker.lock` -> **GREEN** (`ok`, exit 0)；
   - 改动新钉选 `dataset.e1` 轨迹 JSON 1 字节 -> **RED** (`sha256_changed`, exit 1)。
6. **确定性与零写入**：独立执行双次 `build`，产出 `manifest_digest` 严格确定为 `f9ec03cb42dbf1aa16e64e8005b60f88a166562506889540077a3675cc6de7a9`，载荷逐字节一致；前后扫描 `artifacts/` 59,744 个文件 stat，实盘变动严格为 **0**。
7. **一级预检疑点判定**：r2 报告中「排除 101（.DS_Store 95、locks 6）」系作者写报告摘要时的**措辞笔误**；清单与代码实现严格为 101 项（80 episode_data、12 os_metadata、8 teacher_cache、1 runtime_lock），实现与规则 100% 严谨一致。

---

## 1. r3 冻结基线未被改动核实

对 `scripts/v9_baseline_manifest_r3.py` 以及 `reports/V9-baseline/` 下全部历史产物（除 r4 外）逐文件计算 SHA256，并与 `git show HEAD:<path> | shasum -a 256` 进行比对。

- **检查文件总数**：30 项
- **SHA 失配数**：**0**（全部与 git HEAD 严格一致）

### 校验清单节选
| 路径 | 本地文件 SHA256 | Git HEAD SHA256 | 状态 |
|---|---|---|---|
| `scripts/v9_baseline_manifest_r3.py` | `f7160692854e6c659c4d17211338aa58002294324d791ba424cb1e8e0f8e3e41` | `f7160692854e6c659c4d17211338aa58002294324d791ba424cb1e8e0f8e3e41` | 一致 |
| `reports/V9-baseline/baseline_manifest.json` | `cca26b1b726ea3348e0ac9a1b784fa4ecee06a20989d67789ccbc87adcaa1c54` | `cca26b1b726ea3348e0ac9a1b784fa4ecee06a20989d67789ccbc87adcaa1c54` | 一致 |
| `reports/V9-baseline/r2/baseline_manifest.json` | `71e99efcc1ceb652df742396d3bbbfdbc72ac7cd5e46c980171e33065a2d674a` | `71e99efcc1ceb652df742396d3bbbfdbc72ac7cd5e46c980171e33065a2d674a` | 一致 |
| `reports/V9-baseline/r3/baseline_manifest.json` | `2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b` | `2c991f052f322112fa97c57f52585bd99779c3178b21108efdc494596184be5b` | 一致 |
| `reports/V9-baseline/r3/report.md` | `e8cd206e41cf679ea4867f66624b0ae4e1a7d956cc5a381ff3bc486b601c5ae3` | `e8cd206e41cf679ea4867f66624b0ae4e1a7d956cc5a381ff3bc486b601c5ae3` | 一致 |
| `reports/V9-baseline/r3/selftest.json` | `2ee1d4a052d4b23d6dcca234bb20e9cb2450e707a32b56db01746c3291e03c40` | `2ee1d4a052d4b23d6dcca234bb20e9cb2450e707a32b56db01746c3291e03c40` | 一致 |

---

## 2. N/M/D 分类与写行为核实

### 2.1 SQLite 写行为审计
核查 `scripts/v9_baseline_manifest_r3.py`（第 400–415 行）及 `scripts/v9_baseline_manifest_r4.py`（第 445–460 行）：
```python
def open_runstore(path: Path, tmp: Path) -> tuple[sqlite3.Connection, str]:
    wal = Path(str(path) + "-wal")
    wal_size = wal.stat().st_size if wal.exists() else 0
    if wal_size == 0:
        return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True), \
            "immutable=1 (empty WAL, no -shm/-wal write)"
    clone = tmp / ("rs-" + path.name)
    ...
    shutil.copy2(path, clone_path)
    shutil.copy2(wal, Path(str(clone_path) + "-wal"))
    return sqlite3.connect(f"file:{clone_path}?mode=ro", uri=True), "temporary clone (WAL not empty)"
```
- **实测结果**：实盘 8 处 RunStore 数据库当前 WAL 均为 0 字节，全部使用 `mode=ro&immutable=1` 只读连接，SQLite 驱动被强行禁止写入 `-shm` 或 `-wal`；即使非空亦克隆至外部临时目录，实盘零写入保护成立。

### 2.2 独立运行 r3 `verify` 结果
- 退出码：`1`（判为 `RED`，由于 10-20 后新增文件未在 r3 登记）；
- `problems` 总数：**8,057 项**；
  - `unexpected_new_file`: 8,027 项；
  - `policy_claim_unmet`: 30 项（均为 S1 Phase 1 的预登记 JSON，因命中 registration glob 但不在 r3 清单中）；
- `missing` (D): **0 项**（原 497 项基线文件无一丢失）；
- `sha256_changed` / `size_changed` / `runstore_entries_changed` (M): **0 项**（原基线文件无任何内容篡改）；
- **结论**：N = 8,057, M = 0, D = 0。无任何 M/D 违规被吸收进 r4。

### 2.3 抽查 5 项 N 类真实文件
| 序号 | 抽查文件路径 | 字节大小 | 交付物性质核查 | 是否合法交付 |
|---|---|---:|---|---|
| 1 | `artifacts/teachers/t4-approved/b0674736bad10eb16bd765942a9065e7e2ee9a54/config.json` | 861 | VJEPA2 Vit-L-RoPE 教师模型冻结配置 | 是（T4 审定教师） |
| 2 | `artifacts/teachers/da3/DA3-BASE/config.json` | 1,205 | DepthAnything3 Base 深度教师网络配置 | 是（DA3 审定教师） |
| 3 | `artifacts/v9/e1/phase2-r2/checkpoints/arm2_P_seed42/checkpoint_meta.json` | 7,704 | E1 Phase 2-r2 训练 checkpoint 验证损失曲线与元数据 | 是（E1 正式检查点） |
| 4 | `artifacts/v9/s1/phase1/pre_registration.json` | 22,297 | S1 Phase 1 预登记协议与约束文档 | 是（S1 预登记证据） |
| 5 | `artifacts/v9/e1/phase2/datasets/raw/manifest.json` | 349,007 | E1 Phase 2 原始轨迹切分与数据索引清单 | 是（E1 交付数据集） |

---

## 3. sealed_final 纯字节处理审计

审查 `scripts/v9_baseline_manifest_r4.py`：
1. **规则定义**（第 226–238 行）：
   ```python
   {
       "rule": "dataset.sealed_final",
       "action": "pin",
       "category": "dataset.sealed_final",
       "globs": [
           "artifacts/v9/e1/phase2/datasets/generator_identity.json",
           "artifacts/v9/e1/phase2/datasets/SHA256SUMS.txt",
           "artifacts/v9/e1/phase2/datasets/raw/manifest.json",
           "artifacts/v9/e1/phase2/datasets/sealed_final/**",
           "artifacts/v9/s1/datasets/**",
           "artifacts/v9/s1/final-sealed/**",
       ],
       "in_exempt": False,
       "detail": "Sealed final datasets and dataset manifest deliverables. Hashed strictly as raw bytes.",
   }
   ```
2. **纯字节哈希实现**（第 323–328 行）：
   ```python
   def sha256_file(path: Path) -> str:
       h = hashlib.sha256()
       with path.open("rb") as fh:
           for chunk in iter(lambda: fh.read(CHUNK), b""):
               h.update(chunk)
       return h.hexdigest()
   ```
3. **零动态解析与零副作用**：
   - 检索全文无任何 `import numpy`、`np.load`、`torch`、`mlx`；
   - 对 `sealed_final` 文件未执行 `json.load` 或内容解析；
   - 未在 `sealed_final` 目录下创建任何 `.read`、`.accessed` 等标记文件；
   - 第 8、559 行明确写入架构契约约束。

---

## 4. 门是真的门：APFS 独立克隆变异测试

在独立 APFS 克隆副本（确认非软链接且 `st_ino` 完全独立）上运行 5 项变异测试（涵盖所要求的 3 项自做变异及对照）：

| 测试用例 | 目标路径与变异操作 | 预期 | 实际结果 | 抓获错误类型 |
|---|---|---|---|---|
| `mut_1_e1_checkpoint_meta_byte_flip` | 改动 `artifacts/v9/e1/phase2/checkpoints/arm2_P_seed42/checkpoint_meta.json` 1 字节 | RED | **EXIT 1 (RED)** | `sha256_changed` |
| `mut_2_e1_raw_manifest_deleted` | 删除 `artifacts/v9/e1/phase2/datasets/raw/manifest.json` | RED | **EXIT 1 (RED)** | `missing` |
| `mut_3_e1_phase2_sqlite_forged` | 篡改 `artifacts/v9/e1/phase2/control.sqlite3` runs 表首行 state | RED | **EXIT 1 (RED)** | `runstore_entries_changed` |
| `mut_4_excluded_lock_modified` | 修改排除项 `artifacts/locks/m0-worker.lock` 内容 | GREEN | **EXIT 0 (ok)** | 无（符合排除契约） |
| `mut_5_dataset_e1_raw_byte_flip` | 翻转 `artifacts/v9/e1/phase2/datasets/raw/P/train/seq_train_ramp_roll_000.json` 1 字节 | RED | **EXIT 1 (RED)** | `sha256_changed` |

- **结论**：所有 4 项故障注入均被精确抓获变红，排除项变异保持绿，证实 r4 门控具备完全的敏感性与真实防篡改拦截能力。

---

## 5. 确定性与实盘零写入

1. **双次构建确定性**：
   - Build 1 摘要：`f9ec03cb42dbf1aa16e64e8005b60f88a166562506889540077a3675cc6de7a9`
   - Build 2 摘要：`f9ec03cb42dbf1aa16e64e8005b60f88a166562506889540077a3675cc6de7a9`
   - 除 `generated_at` 时间戳外，两次构建产出的 JSON 结构体逐字节完全相同。
2. **实盘零写入**：
   - 运行前后对 `artifacts/` 目录下全部 59,744 个文件（含 `-wal`/`-shm`）记录 `(mtime_ns, size, inode)` 快照比对；
   - 比对差异数：**0**（无任何文件被创建、删除、截断或修改元数据）。

---

## 6. 覆盖面与排除/范围外目录评估

1. **10-20 后新增统计**：
   - 钉选新增：8,023 文件（含 7,600 个 E1 数据集文件、Phase 2/Phase 2-r2 检查点与评估、S1 产物、教师模型权重）；
   - 排除新增：12 文件（全部为 macOS 生成的 `.DS_Store` 系统元数据）；
   - 范围外新增：3 文件（位于 `artifacts/reports/E25-weighted/` 与 `artifacts/reports/E27-onestep/`）。
2. **范围外与排除理由有效性**：
   - `artifacts/reports/**`：属于实验运行过程中的讨论、记录、审查等过程性文本，非模型资产（其内的正式 `registration.json` 仍被显式穿透钉选），判为范围外理由充分；
   - `artifacts/spacetime/**`：属于可视化轨迹中间临时导出，由上游种子与环境重现，判为范围外理由充分；
   - 运行时锁 `m0-worker.lock`：属并发守护标记，排除理由充分；
   - 未分类文件数严格为 **0**。

---

## 7. 一级预检疑点核对结论

- **疑点**：r2 报告写「排除 101（.DS_Store 95、locks 6）」，而清单 `by_rule` 显示为 `os_metadata: 12`、`runtime_lock: 1`、`episode_data: 80`、`teacher_cache: 8`。
- **核查事实**：
  1. `baseline_manifest.json` 与 `BASELINE_INVENTORY.md` 中的 `excluded_with_reason` 数组长度严格为 **101**。
  2. 规则明细：`episode_data` (80) + `os_metadata` (12) + `teacher_cache` (8) + `runtime_lock` (1) = **101**。
  3. r1 清单原排除 7,701 项；r2 将 7,600 个 `e1_dataset_intermediates` 移入钉选 `dataset.e1`，剩余恰好为 101 项。
  4. 所谓 `（.DS_Store 95、locks 6）` 是作者在撰写报告 markdown 摘要时随手写下的笔误（95 + 6 = 101），并非底层代码、清单或 inventory 的实现差异。
- **裁定**：此为**报告文本措辞笔误**，不构成代码实现或清单数据缺陷，不影响基线有效性。

---

## 8. 验收建议与操作指引

- **建议**：一级统筹采纳 V9.A15 r2 交付（`reports/V9-baseline/r4/r2/`），并将其晋升为正式 A2 r4 基线清单。
- **产物文件**：
  - 复核报告：`reports/V9-baseline/r4-review/REVIEW.md`
  - 复核指标：`reports/V9-baseline/r4-review/metrics.json`
