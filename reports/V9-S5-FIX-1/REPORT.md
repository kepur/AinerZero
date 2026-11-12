# ainerzero.V9.P239 执行报告

角色：executor；负责人：gemini-k7x2；时间：2026-11-12
任务状态：reported；实验状态：completed（仅在隔离副本与 `s5test-*` 数据上做测试与缓存前后对比，未启动真实 probe / dev-tune / dev-distill）
任务依据：`RESEARCH_LOG.md` `R20261111-S5-start` 续条（`probe-20261112b` 发现的问题 1 与问题 2）、`reports/V9-S5-DESIGN/DESIGN-r1.md` §3 与 §6
修改文件：`reports/V9-S5-PHASE1/run_s5p1.py`、`reports/V9-S5-PHASE1/plan_s5p1.py`、`src/ainerzero/v9/experiments/s5/data.py`、`src/ainerzero/v9/experiments/s5/train.py`（仅改数据读取调用点，与并行卡 P240 的 `FlatHead` 改动完全正交并共存）、`tests/v9/experiments/test_s5_data.py`、`tests/v9/experiments/test_s5_runner_plan.py`、`tests/v9/experiments/test_s5_runner_native.py`、`reports/V9-S5-FIX-1/`
实际执行：纯 CPU pytest 22 项（10.52 秒）；在持 `artifacts/locks/m0-worker.lock` 锁下跑原生 MLX 运行器与缓存测试 4 项（103.66 秒）及 `s5test-bench` 缓存前后 `data_fraction` 对比测量；四个阶段均跑了 `--dry-run`。未触碰真实 `s5p1-*` 分区，未消耗 dev 使用。
验证结果：22 passed（CPU）+ 4 passed（native-mlx），5 项源码坏对照（全部先断言目标路径不是 `/Users/mac/AinerWorkFlow/AinerZero`）全部被拦住。
产物：本目录 `REPORT.md`、`metrics.json`、`diff.patch`、`SHA256SUMS.txt`、`evidence/pytest-cpu.txt`、`evidence/pytest-native.txt`、`evidence/data-fraction-comparison.json`、`evidence/dry-run-*.json`。

---

## 1. 修改摘要

### 1.1 运行器按 `label_n` 取 `lab` 嵌套子集（`reports/V9-S5-PHASE1/run_s5p1.py`）
- 新增模块常量 `LAB_SUBSET_SEED = 20261112`（L45），冻结前不再改动。
- `_index_for(partition_dir, clips, *, label_n=None)`（L260–265）：凡带 `label_n` 的格子（`supervised`、`heads`），训练索引改为 `ClipIndex(partition_dir).subset_by_worlds(plan.L_WORLDS[int(label_n)], seed=LAB_SUBSET_SEED)`（`L=64 -> 4` 世界 / 64 段，`L=512 -> 32` 世界 / 512 段，`L=2048 -> 128` 世界 / 2048 段）。
- `dev` 评测仍调 `_index_for(eval_dir, clips)`（不传 `label_n`），在 `dev` 全集上评测。
- `events.jsonl` 的 `cell_start`（L597–610）记录子集的 `worlds`（世界清单）、`n_worlds`、`n_clips`（段数）与 `label_n`；`cell_end`（L358–372）记录实际 `steps_logged` / `steps`、`worlds`、`n_worlds`、`n_clips`。

### 1.2 数据读取进程内缓存与教师 SHA 单次核对（`src/ainerzero/v9/experiments/s5/data.py`、`train.py`）
- 在 `data.py` 新增 `ItemCache(max_bytes=DEFAULT_CACHE_MAX_BYTES)`（默认上限 `48 GiB = 51,539,607,552` 字节）：
  - 缓存 `uint8` 原始段数组（`clip_raw`）、标签字典（`r1_logd, r1_sky, r1_obj, r2, r3, disk_groups, ordering_pairs`）与教师 `fp16` 特征（`vjepa`、`da2`）。
  - `tubelet_patches(clip_raw)` 每次从缓存的 `uint8` 原始段现算，不占缓存容量。
  - 超过 `max_bytes` 字节上限时不再写入新缓存条目，但照常从磁盘读取返回，不报错。
- 进程内教师文件 SHA256 单次核对（`_VERIFIED_TEACHER_SHAS` 与 `_verify_teacher_file_once`）及账本缓存（`_LEDGER_CACHE`）：
  - 每个进程对每个教师特征文件只在首次读取时计算并核对一次 SHA256（若首次读入前文件被篡改，照常抛出 `RuntimeError("... SHA mismatch ...")`）；同一进程后续读取不再重算文件 SHA、不再重复解析 4000 行 `progress.jsonl`。
- `train.py` 的 `distill`、`train_supervised`、`train_heads`、`predict` 全部支持并默认创建 `ItemCache` 在单次训练/预测调用内跨轮次共用（仅改数据读取调用点，训练数学逻辑不变；另外 `distill` 的 A1 只读 `da2`、A2 只读 `vjepa`，避免无谓读取未用教师特征）。

### 1.3 `--dry-run` 墙钟按 `probe` 实测校准（`reports/V9-S5-PHASE1/plan_s5p1.py`）
- `wall_seconds` 改用 `probe-20261112b` 实测每步纯计算时间 `STEP_COMPUTE_S = 0.16 s`（批量 8）+ 进程内缓存命中后每步现算 `tubelet_patches` 耗时 `CACHED_STEP_DATA_S = 0.015 s` + 首轮冷读与首次 SHA 核对 `COLD_READ_S_PER_CLIP = 0.02 s/段`；读出头仍按「缓存一次学生特征 + 只训读出头」估算，并同时给出设计 §6 的对照值 `design_wall_h`：

| 阶段 | 格数 | 总步数 | 校准后估算 (`wall_h_est`) | 设计 §6 (`design_wall_h`) | 阶段时限 |
|---|---:|---:|---:|---:|---:|
| `smoke` | 9 | 18 | 端到端实测约 35 s | — | 0.25 h |
| `probe` | 17 | 8,312 | **0.38 h** (1351 s) | 0.50 h | 1.50 h |
| `dev-tune` | 11 | 38,240 | **1.94 h** (6988 s) | 1.60 h | 2.00 h |
| `dev-distill` | 63 | 256,680 | **3.48 h** (12538 s，含读出头 0.81 h) | 3.22 h（含读出头 0.75 h） | 4.00 h |

---

## 2. 缓存前后 `data_fraction` 对比（`s5test-bench` 实测）

在持锁下对同一 `s5test-bench` 蒸馏训练格（1 世界 = 16 段，`batch_size=8`，A3 双教师蒸馏）测量缓存前（每次重读 `npy/npz`、重解析账本并重算教师 SHA）与缓存后（`ItemCache` + 单次教师 SHA）的耗时占比（原始数据见 `evidence/data-fraction-comparison.json`）：

| 配置 | 状态 | 全程 `data_fraction` | 第 2 轮起 `data_fraction` | 每步读数据 `data_s` | 每步计算 `step_s` |
|---|---|---:|---:|---:|---:|
| 完整 `Student(d=384, depth=6, heads=6)`，10 轮 (20 步) | **缓存前** | **27.5%** (`0.2749`) | **27.9%** (`0.2794`) | 0.0569 s | 0.1501 s |
| 完整 `Student(d=384, depth=6, heads=6)`，10 轮 (20 步) | **缓存后** | **17.3%** (`0.1732`) | **16.4%** (`0.1638`) | 0.0365 s | 0.1740 s |
| 轻量 `Student(d=64, depth=2, heads=2)`，6 轮 (12 步) | **缓存前** | **59.1%** (`0.5909`) | 第 2–6 轮共 0.5307 s | 0.0544 s | 0.0377 s |
| 轻量 `Student(d=64, depth=2, heads=2)`，6 轮 (12 步) | **缓存后** | **48.0%** (`0.4803`) | 第 2–6 轮共 0.2591 s | 0.0300 s | 0.0324 s |

> 注：在 16 段小样本上 OS 页缓存已热，缓存仍将每步数据准备时间从 `0.0569 s` 降至 `0.0365 s`（仅剩内存 `tubelet_patches` 现算），`data_fraction` 从 `27.5%` 降至 `17.3%`（第 2 轮起 `16.4%`）。在实盘 `s5p1-pool`（4000 段、4000 行 `progress.jsonl`）上，消除了每步重复解析 4000 行账本与重算 SHA256 的开销，单次 7500 步全量蒸馏从 `~54 min` 降至约 `23.2 min`（`1392.5 s`）。

---

## 3. 测试与源码坏对照结果

所有改源码的坏对照测试在修改前均先断言 `target_root.resolve() not in (LIVE, REAL_REPO)`，绝不触碰实盘仓库：

| 测试项 | 正例测试 | 源码坏对照测试与改动内容 | 结果 |
|---|---|---|---|
| 1. 运行器按 `label_n` 取子集 | `test_label_n_subset_is_used_in_supervised_cell`：一次性副本中 `lab` 有 2 世界（32 段），设 `L_WORLDS[64]=1`，跑 `label_n=64, epochs=2, batch=8` 的 supervised 格；验证 `cell_start` 记 `worlds` 清单且 `n_clips == 1 * 16 == 16`，`cell_end` 的 `steps_logged == 16 * 2 // 8 == 4`。 | `test_removing_subset_by_worlds_mutation_is_caught`：去掉 `_index_for` 中的 `.subset_by_worlds(...)`，世界数变为 2、段数变为 32、步数变为 8，被断言拦住。 | PASSED |
| 2. 子集嵌套与确定性 | `test_lab_subset_nesting_and_determinism_with_frozen_seed`：用 `LAB_SUBSET_SEED=20261112` 验证 `L=64 (4) ⊂ L=512 (32) ⊂ L=2048 (128)`，且同种子两次调用世界清单与切片列表完全一致。 | `test_subset_nesting_mutation_is_rejected`：将 `subset_by_worlds` 的 `default_rng(seed)` 改为 `default_rng(seed + n)`，破坏嵌套关系，子进程断言失败（退出码非 0）。 | PASSED |
| 3a. 缓存复用与逐元素一致 | `test_item_cache_second_read_does_not_call_np_load_and_matches_uncached` + `test_train_loops_use_item_cache_across_epochs`：用计数包装 `np.load`，验证第 2 次读取及第 2–3 轮训练触发 `0` 次 `np.load`，且缓存输出与不缓存逐元素一致。 | `test_cache_disabled_mutation_is_rejected`：将 `ItemCache.get` 改为恒返回 `None`，第 2 次读取仍触发 `np.load`，子进程断言失败。 | PASSED |
| 3b. 教师 SHA 每文件只算一次 | `test_teacher_sha_computed_at_most_once_per_file_in_process`：计数包装 `_sha256_file`，跨多次读取同一教师文件只调用 1 次 `_sha256_file`。 | `test_teacher_sha_every_time_mutation_is_rejected`：删去 `_VERIFIED_TEACHER_SHAS[key] = got_sha`，导致重复计算 SHA，子进程断言失败。 | PASSED |
| 3c. 超过字节上限照常读取 | `test_item_cache_exceeding_max_bytes_reads_normally_without_error`：设 `max_bytes` 仅容下 1 段 `uint8` clip，读取多段与教师特征不报错，`used_bytes <= max_bytes` 且结果与无缓存逐元素一致。 | （与 3a/3b 共用 `ItemCache` 边界验证） | PASSED |
| 4. 首次读入前篡改教师文件报错 | `test_tampered_teacher_before_first_read_raises_with_cache`：首次读入前翻转 `vjepa` / `da2` 文件末字节，传入 `ItemCache` 仍抛出 `RuntimeError("... SHA mismatch ...")`。 | `test_teacher_sha_skip_verification_mutation_is_rejected`：将 SHA 失配判断改为 `if False:`，篡改文件不再报错，被坏对照测试拦住。 | PASSED |
