# V9-S5-FIX-3（ainerzero.V9.P241）执行报告：让 RLT 真的省时间

- **任务 ID**：`ainerzero.V9.P241`
- **执行者**：`gemini-k7x2`（二级执行层）
- **基线提交**：`b971380`
- **文件范围**：
  - `src/ainerzero/v9/experiments/s5/tokens.py`
  - `src/ainerzero/v9/experiments/s5/data.py`
  - `src/ainerzero/v9/experiments/s5/train.py`
  - `src/ainerzero/v9/experiments/s5/student.py`
  - `tests/v9/experiments/test_s5_tokens.py`
  - `tests/v9/experiments/test_s5_data.py`
  - `tests/v9/experiments/test_s5_student_mlx.py`
  - `tests/v9/experiments/test_s5_train_mlx.py`
  - `reports/V9-S5-FIX-3/`

---

## 1. 改动说明

### 1.1 `src/ainerzero/v9/experiments/s5/tokens.py`：纯 NumPy 向量化 `rlt_keep_fast`
- 保留原 `rlt_keep(patches, tau)` 不变（继续调用权威 `ainerzero.v9.tokenization.rlt.rlt_frame_dropping`）。
- 新增 `rlt_keep_fast(patches, tau)`（第 153–187 行），支持 4D `[8, 14, 14, 1536]` 与 5D `[B, 8, 14, 14, 1536]` 输入，无任何 Python 循环：
  - 照式 10 计算相邻管长无穷范数：`keep[:, 0] = True`；`diff_max = np.max(np.abs(arr[:, 1:] - arr[:, :-1]), axis=-1)`；`keep[:, 1:] = diff_max >= tau`。
  - 利用反向后缀最小值 `np.minimum.accumulate(kept_t[:, :0:-1], axis=1)[:, ::-1]` 一次性求出每个位置到下一个保留管长（或末尾 `T=8`）的距离，并在被并掉位置置 0：`run_len = np.where(keep, next_kept - t_idx, 0)`。
  - 单段 CPU 实测中位耗时从 `rlt_keep` 的 **4.57 ms** 降至 **0.70 ms**（提速 **6.53×**）。

### 1.2 `src/ainerzero/v9/experiments/s5/data.py` 与 `train.py`：`ItemCache` 按 `(clip, tau)` 缓存 `(keep, run_len)`
- `data.load_item` 新增可选参数 `tau: float | None = None`（第 204–307 行）：
  - 当 `tau is not None` 时，构造带 `tau` 的缓存键 `rlt:{clip_file.resolve()}:tau={float(tau)!r}` 查询 `ItemCache`。
  - 未命中时调用 `rlt_keep_fast(patches, float(tau))` 计算 `(keep, run_len)` 并按 `keep.nbytes + run_len.nbytes` 存入 `ItemCache`，命中时直接返回缓存结果。
- `train.py` 的 `distill`（第 264–286 行）、`train_supervised`（第 431–451 行）、`train_heads`（第 568–577 行）与 `predict`（第 702–712 行）全部改为通过 `load_item(..., tau=..., cache=active_cache)` 获取缓存的 `item["keep"]` 与 `item["run_len"]`，不再每步重复调用 `rlt_keep`。

### 1.3 `src/ainerzero/v9/experiments/s5/student.py`：稀疏分支纯 MLX 向量化（零按样本 Python 循环）
- 重写 `Student.__call__` 的稀疏保留分支（第 121–164 行），彻底移除 `np.array(mask)` 同步与所有 `for b in range(B):` 循环及下标切片赋值：
  - **紧凑序列 gather**：用严格无并列排序键 `sort_key = (1 - mask_int) * self.num_tokens + idx_range` 执行 `order = mx.argsort(sort_key, axis=1)`，将每个样本保留的 token 稳定排在最前，并用一次 `mx.take_along_axis(x, order[:, :k_max, None], axis=1)` 取出 `[B, k_max, d]`。
  - **补齐掩码**：按 `valid_compact = mx.arange(k_max, dtype=mx.int32)[None, :] < counts[:, None]` 构造 `[B, 1, 1, k_max]` 加性注意力掩码（有效位置 `0.0`，补齐位置 `-1e9`）。
  - **单次 gather 映射回 `[B, 1568, d]`**：预先计算 `ungather_idx = mx.where(mask, mx.cumsum(mask_int, axis=1) - 1, k_max)[:, :, None]`；每层结束后及最终 `self.norm` 后，在紧凑序列末尾拼入一个零向量 `zero_pad`（形状 `[B, 1, d]`，位于索引 `k_max`），用一次 `mx.take_along_axis(padded, ungather_idx, axis=1)` 还原回 `[B, 1568, d]`。
  - `features(layer=k)` 语义与形状完全不变。

---

## 2. 计时对比（全保留 vs `keep ≈ 0.73`）

在锁 `artifacts/locks/m0-worker.lock` 下，使用真实大小学生 `Student(d=192, depth=6, heads=3)`、`batch_size=8`，预热后测量单步前向 + 反向（`nn.value_and_grad` + `mx.eval`）中位墙钟耗时：

| 测量场景 | `keep` 率 | 全保留中位每步墙钟 | RLT (`keep≈0.73`) 中位每步墙钟 | 比值 (`RLT / 全保留`) | 相对全保留降幅 |
|---|---:|---:|---:|---:|---:|
| `pytest` 内置测试 (`test_s5_student_mlx.py`) | `0.7249` | `0.189806 s` | `0.130428 s` | `0.6872` (`< 0.90`) | **−31.28%** |
| 独立基准脚本 (`evidence/timing_benchmark.json`) | `0.7345` | `0.131210 s` | `0.094222 s` | `0.7181` (`< 0.90`) | **−28.19%** |

此外，在 CPU 端单段 `rlt_keep` vs `rlt_keep_fast` 对比（15 次中位数）：
- `rlt_keep`（调 `rlt_frame_dropping`）：`4.569 ms / 段`
- `rlt_keep_fast`（纯 NumPy 向量化）：`0.699 ms / 段`（提速 `6.53×`），且经 `ItemCache` 缓存后第 2 轮起耗时为 `0 ms`。

---

## 3. 测试与隔离副本源码坏对照

所有坏对照均由 `reports/V9-S5-FIX-3/evidence/run_mutations.py` 执行：脚本首先断言目标目录不是实盘仓库 `/Users/mac/AinerWorkFlow/AinerZero`，再用 `git archive HEAD` 导出干净临时副本并覆盖本卡改动文件，逐项注入源码突变并运行生产测试验证变红（10/10 全部拦截，`evidence/mutations_results.json`）：

| 突变编号 | 目标文件与源码改动 | 拦截的生产测试 | 退出码 | 结果 |
|---|---|---|---:|---|
| `M1_rlt_keep_fast_l1_instead_of_linf` | `tokens.py`: 将 `np.max(np.abs(...))` 改为 `np.mean(np.abs(...))` | `test_s5_tokens.py::test_rlt_keep_fast_matches_rlt_keep_elementwise` | `1` | 已拦截 |
| `M2_rlt_keep_fast_run_len_always_one` | `tokens.py`: 将 `next_kept - t_idx` 改为常数 `1` | `test_s5_tokens.py::test_rlt_keep_fast_matches_rlt_keep_elementwise` | `1` | 已拦截 |
| `M3_student_sparse_sort_key_inverted` | `student.py`: 将 `(1 - mask_int)` 改为 `mask_int`（被并掉位置排前面） | `test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise` | `1` | 已拦截 |
| `M4_student_sparse_attn_mask_unmasked_padding` | `student.py`: 将补齐掩码 `-1e9` 改为 `0.0`（不屏蔽补齐位） | `test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise` | `1` | 已拦截 |
| `M5_student_sparse_ungather_dropped_to_zero_index` | `student.py`: 将 `ungather_idx` 被并掉位置从 `k_max` 改为 `0` | `test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise` | `1` | 已拦截 |
| `M6_student_sparse_layer_features_wrong_layer` | `student.py`: 将 `_layer_features.append(...)` 改为 `append(x)` | `test_s5_student_mlx.py::test_vectorized_sparse_branch_matches_legacy_reference_elementwise` | `1` | 已拦截 |
| `M7_data_rlt_cache_key_missing_tau` | `data.py`: 去掉 `rlt_key` 中的 `:tau={tau_val!r}` | `test_s5_data.py::test_rlt_keep_cached_by_clip_and_tau` | `1` | 已拦截 |
| `M8_data_rlt_cache_put_disabled` | `data.py`: 去掉 `cache.put(rlt_key, ...)` | `test_s5_data.py::test_rlt_keep_cached_by_clip_and_tau` | `1` | 已拦截 |
| `M9_train_distill_recomputes_rlt_every_step` | `train.py`: 在 `distill` 中每步直接调 `rlt_keep_fast` 绕过缓存 | `test_s5_train_mlx.py::test_train_and_predict_cache_rlt_keep_by_tau` | `1` | 已拦截 |
| `M10_train_supervised_bypasses_active_cache` | `train.py`: 在 `train_supervised` 中传 `cache=None` 绕过缓存 | `test_s5_train_mlx.py::test_train_and_predict_cache_rlt_keep_by_tau` | `1` | 已拦截 |

---

## 4. 验证命令与结果

1. **S5 纯 CPU 单元与缓存测试**：
   - 命令：`.venv/bin/python -m pytest -q -s -p no:cacheprovider tests/v9/experiments/test_s5_tokens.py tests/v9/experiments/test_s5_data.py`
   - 结果：`23 passed in 10.67s`（日志见 `evidence/pytest_s5_cpu.txt`）。
2. **S5 原生 MLX 测试（持锁）**：
   - 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -s -p no:cacheprovider --native-mlx tests/v9/experiments/test_s5_student_mlx.py tests/v9/experiments/test_s5_train_mlx.py tests/v9/experiments/test_s5_tokens.py`
   - 结果：`64 passed in 55.33s`（日志见 `evidence/pytest_s5_native_mlx.txt`）。
3. **隔离副本 10 项源码坏对照（持锁）**：
   - 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python reports/V9-S5-FIX-3/evidence/run_mutations.py`
   - 结果：`ALL 10 MUTATIONS KILLED.`（日志见 `evidence/mutations_stdout.txt` 与 `evidence/mutations_results.json`）。
4. **默认入口全量纯 CPU 测试**：
   - 命令：`.venv/bin/python -m pytest -q -p no:cacheprovider`
   - 结果：`4349 passed, 7 deselected in 1276.85s`（尾行日志见 `evidence/pytest_default_full_tail.txt`）。
