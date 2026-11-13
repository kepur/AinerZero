# S5 冻结代码修复（k_max 分档，307465d）与 PREREG v2 非作者独立复核报告

- **复核执行者**：gemini-m8k2（二级执行层，非作者，独立会话）
- **修复作者**：一级 claude（提交 `307465d`，变异证据 `3336690`，PREREG v2 `cb667ff`）
- **核验结论**：**通过（PASS）**。语义不变性、边界保护、稠密分支隔离、形状收敛性与性能平稳性均已完全证实；改坏源码变异测试 3/3 成功杀掉；PREREG v2 相比 v1 仅存在预期的 3 处差异（代码清单、清单哈希、预算），其余所有冻结项逐位一致。

---

## 一、背景与问题核对

- 登记运行 `s5p1-final-20261113a` 在执行 distill-R-s0 时撞上 45 min 单格上限中断。
- 根因定位清晰：`Student` 稀疏分支原代码中 `k_max = max(1, int(mx.max(counts).item()))`，每批次实际保留的 token 数动态波动，导致编译生成的 MLX 图形状频繁变化，触发反复重新编译，单步蒸馏耗时在单轮内从 0.38s 攀升至 0.63s。
- 修复方案：引入 `bucket_k` 将 `k_max` 向上对齐到 `K_BUCKET = 64` 的整数倍（上限 `num_tokens = 1568`）。补齐的无效位置通过 `valid_compact` 与 `-1e9` 加性注意力掩码严格隔离，还原输出（ungather）时映射至 `zero_pad`，不参与任何有效 token 的计算或输出。
- 用户授权：用户已明确批准「批准修复重跑」（2026-11-13），锁内总额追加至 25h，登记运行整段重跑。

---

## 二、逐项核对结论与证据

### 1. 语义不变（Semantics Invariance）
- **核对结论**：**通过**。
- **机制核查**：
  - 在 `src/ainerzero/v9/experiments/s5/student.py` 中，`order = mx.argsort(sort_key, axis=1)` 保证保留 token 排在前 `counts[b]` 个位置；
  - `valid_compact = arange(k_max) < counts` 将超出实际保留数的补齐槽位标识为无效；
  - `attn_mask` 在补齐槽位上置为 `-1e9`，Softmax 权重严格归零，阻断补齐槽位对保留 token 的注意力渗透；
  - `ungather_idx` 将未保留位置映射到 `zero_pad`（索引 `k_max`），补齐槽位（`counts[b]` 到 `k_max - 1`）永远不会被 ungather 索引读取。
- **证据**：
  - 测试 `test_bucketed_sparse_path_matches_the_unbucketed_path` 确实调用了生产代码 `Student`；
  - 对比 `K_BUCKET=64` 与 `K_BUCKET=1`（等价于未分档的原逻辑），输出 token 与全部 6 层中间特征逐元素差值最大值 `< 1e-4`（测试全通）。

### 2. 边界检查（Boundaries & Edge Cases）
- **核对结论**：**通过**。
- **机制与测试**：
  - `bucket_k(k, num_tokens)` 对任意整数 `k`（包括负数、0、超大值）的返回值严格落在 `[1, num_tokens]` 范围内，且为 64 的倍数或等于 `num_tokens`（1568）；
  - 全保留（`keep = ones`）：直接由 `is_all_kept` 调度至稠密分支，输出正常；
  - 只保留首个管长（196 tokens）：分档对齐至 256，未保留位置输出严格为 0；
  - 批内极大跨度（如样本 0 保留 1 token，样本 1 保留 1567 tokens）：`k_max` 向上取整至 1568，两样本各自的非保留位置输出均严格为 0，互不干扰。
- **证据**：详见 `evidence/verify_boundary.log`。

### 3. 形状数量（Shape Diversity <= 25）
- **核对结论**：**通过**。
- **机制与测试**：
  - 序列最大长度为 1568，对齐步长为 64。有效形状集合为 `ceil(1568 / 64) = 25` 种（`{64, 128, ..., 1536, 1568}`）；
  - 测试 `test_sparse_path_sees_at_most_25_shapes` 模拟 60 个批次随机不同保留长度，记录的紧凑序列长度严格不超过 25 种，且全落在分档点；
  - 在去掉分档的变异测试中，该测试被立即杀掉（FAILED）。

### 4. 稠密分支隔离（Dense Path Isolation）
- **核对结论**：**通过**。
- **机制与代码核查**：
  - `Student.__call__` 第 113-135 行：当 `keep is None` 时，`is_all_kept = True`；代码直接在 `if is_all_kept:` 块内循环执行 block 自注意力并返回，完全不调用 `bucket_k`，不产生 `valid_compact`、`attn_mask` 或 `ungather_idx`；
  - C-sh、A0、A4、FT 均走稠密分支（`keep=None`），计算流程与修复前逐位一致（bitwise identical）。

### 5. 性能实测（Performance Stability）
- **核对结论**：**通过**。
- **一审查验**：作者实测全量 pool 上 A1 蒸馏（500 步，batch=8）四分位时间分别为 `[0.118, 0.123, 0.128, 0.134]` s，500 步用时 88 s；相比修复前从 0.384 升至 0.632 s（323 s），平稳无退化。
- **独立复测**：在持有 `artifacts/locks/m0-worker.lock` 下独立运行 `bench_rlt_full.py 0.02`：
  - 步数：500 步；总墙钟耗时：96.4 s；
  - 各四分位每步耗时中位数：`[0.1460, 0.1451, 0.1446, 0.1413]` s；
  - 数据加载每步耗时中位数：`[0.0465, 0.0445, 0.0468, 0.0477]` s；
  - 各四分位步耗时呈现单调平稳态势，彻底消除了形状反复抖动导致的编译耗时累积。
- **证据**：详见 `evidence/bench_rlt_full.json`。

### 6. PREREG v2 与 v1 差异核对（PREREG Diff Verification）
- **核对结论**：**通过**。
- **逐键比对结果**：
  - v1 SHA256（`4fe5b6f:reports/V9-S5-FINAL/PREREG.json`）：`2de216957c759227f7b51b01aeafcffa647e22721d53fa4c8bf94419fcd38642`
  - v2 SHA256（HEAD）：`1b0c86807c7ec5c83be51f450c8dc88f5097c78af12643ae4fb1db4e6400e24c`
  - 全量逐键对比仅存在以下 4 处字段变动（实质 3 处）：
    1. `manifest.src/ainerzero/v9/experiments/s5/student.py`: `5f939880...` -> `440a77ae...`（对应 student.py 修复）
    2. `manifest_sha256`: `3670af41...` -> `0eda9655...`（清单重新计算哈希）
    3. `budget.budget_h`: `11.8` -> `10.95`
    4. `budget.budget_s`: `42480.0` -> `39420.0`
  - 其余所有 71 个钉住代码文件哈希、A*（A1）、学习率、η、τ、种子、n_final（48）、门与阈值参数逐位一致，没有任何隐蔽修改。
- **证据**：详见 `evidence/prereg_diff.json` 与 `evidence/prereg_check.log`。

### 7. 改坏源码复验（Mutation Testing on Git Archive Copy）
- **核对结论**：**通过**。
- **执行方式**：在独立解压的 `git archive 307465d` 副本目录 `/tmp/review_kbucket_archive` 下进行，通过 `PYTHONPATH=/tmp/review_kbucket_archive/src` 隔离加载，实盘代码完全只读未改动。
- **测试结果**：
  - **BASELINE**：rc=0，27 条原生单测全部通过（用时 43.88s）；
  - **MUTATION 1（去掉分档）**：rc=1，**2 failed**, 25 passed；
    - 失败单测：
      - `test_bucket_k_rounds_up_to_multiples_of_64_within_bounds`
      - `test_sparse_path_sees_at_most_25_shapes`
  - **MUTATION 2（去掉 1568 上限）**：rc=1，**3 failed**, 24 passed；
    - 失败单测：
      - `test_bucket_k_rounds_up_to_multiples_of_64_within_bounds`
      - `test_bucketed_sparse_path_matches_the_unbucketed_path`
      - `test_sparse_path_sees_at_most_25_shapes`
  - **MUTATION 3（补齐位置不加掩码）**：rc=1，**4 failed**, 23 passed；
    - 失败单测：
      - `test_student_sparse_batch_padding_isolation`
      - `test_features_layer_index_with_partial_keep`
      - `test_vectorized_sparse_branch_matches_legacy_reference_elementwise`
      - `test_bucketed_sparse_path_matches_the_unbucketed_path`
- **证据**：详见 `evidence/mutations.txt` 与 `evidence/mutations_detailed.log`。

---

## 三、总评与放行建议

作者一级 claude 对 `student.py` 的修复精确且完备，补齐掩码与逆变换映射阻断了任何信息泄露，完全保持了数学语义不变；分档机制将 MLX 编译形状数严格压缩在 25 种以内，实测彻底根除了性能抖动问题；PREREG v2 严格只更新了必要项。

**非作者复核结论：全部指标通过，建议放行并按 PREREG v2 启动 S5 最终登记运行重跑。**
