# 复核报告：ainerzero.V9.T24 【非作者CPU】T23教师基准入口守卫与资源预算审计

- **复核任务 ID**: `ainerzero.V9.T24`
- **被复核任务 ID**: `ainerzero.V9.T23`
- **复核 Agent**: `gemini-kzer`（二级执行层，**确认为独立非作者**）
- **被复核作者**: `gemini-w9p4`（二级执行层）
- **类型**: `verify`
- **需要**: `code` (纯 CPU，`real_model_runs = 0`)
- **复核时间**: 2026-10-26T12:25:00+03:00
- **复核结论**: **验收通过（accepted）**

---

## 1. 审计范围与独立性声明

1. **作者独立性**: 被审任务 `ainerzero.V9.T23` 由 `gemini-w9p4` 提交。本次审计由 `gemini-kzer` 独立执行，满足统筹規约（`BLOCKERS-NEXT-BATCH.md` §4）要求的非作者独立复核机制。
2. **文件范围约束**: 严格约束仅写入 `reports/V-V9-T23/`，主工程源码 `src/` 与生产测试 `tests/` 零改动。
3. **零测试复用**: 绝不直接 `import` 或运行作者现成的测试套件（`tests/v9/teachers/test_benchmark_guard.py`），完全在独立临时隔离环境构建全新的 10 项全生命周期审计测试与 4 项 3-way 真实源码单点隔离突变套件。
4. **生产库绝对保护**: 绝不打开或连接生产数据库（`artifacts/v9/teachers/benchmark/runs.db` 或 `AinerRelay/data/relay.db`），测试数据完全运行于受控的独立 `tempfile.TemporaryDirectory` 中。
5. **纯 CPU 与零模型加载**: 真实模型运行数 `real_model_runs = 0`，不导入 MLX/CoreML，不下载任何模型权重，无付费服务调用。

---

## 2. 核心守卫审计实测清单

| 审计项 | 规约要求 | 审计实测表现 | 结论 |
| :--- | :--- | :--- | :--- |
| **1. Inspect 零副作用** | 绝不创建/获取锁，不创建/写入 DB，不导入模型 | `runs.db` 存在性: `False`；锁文件存在性: `False`；mlx/coreml 导入: `None`；退出码 `0` | **通过** |
| **2. 并发互斥守卫** | 共享 worker_lock 被持有时非阻塞退出 | 外部持锁时执行受控 benchmark 立即返回码 `4` (`EXIT_LOCK_BUSY`)，状态为 `skipped_lock_busy` | **通过** |
| **3. 一级批准门禁** | 依赖 `RESEARCH_LOG.md` 的 `R20261016-T4` 与 `批准 T4`，篡改/缺失一律拒绝 | 文件缺失、缺少批准小节、缺少关键字、显式撤销均强拒并退出码 `3` (`EXIT_REFUSED_APPROVAL`) | **通过** |
| **4. 单次预算守卫** | 单次请求墙钟预算上限 ≤ 600.0s | 请求 600.1s 立即强拒并退出码 `5` (`EXIT_REFUSED_BUDGET`)；请求 ≤ 0s 强拒 | **通过** |
| **5. 累计预算守卫** | RunStore 账本累计已扣 + 当前请求 ≤ 1800.0s | 预扣 1500s 后请求 400s（总计 1900s > 1800s）立即强拒并退出码 `5` (`EXIT_REFUSED_BUDGET`) | **通过** |
| **6. 预扣除与崩溃留痕** | 调用适配器前原子扣除，崩溃不退费 | 模拟适配器异常崩溃后，RunStore 状态标为 `failed`，预扣除的 400s 依然锁定留痕，后续请求继续计入累计 | **通过** |
| **7. 资源门限守卫** | 进程物理内存 RSS ≤ 32.0 GiB | 当前进程检测通过；设定超限门限测试触发退出码 `2` (`EXIT_REFUSED_RESOURCE`) | **通过** |
| **8. 模型规格与身份** | 绑定 T21/T22 封存的 12 个官方权重规格 | 校验 `vjepa` (5 文件, 1,310,663,844 B) 与 `DA2` (7 文件, 149,011,972 B)，落盘磁盘总计 1,459,675,816 B（传输 payload 1,655,306,028 B） | **通过** |
| **9. CLI 子进程集成** | `ainerzero teacher-benchmark` CLI 真实子进程 | 实测 `--help`、`--mode inspect` (exit 0) 与 `--mode run --wall-budget-seconds 999.0` (exit 5) 均符合规约 | **通过** |
| **10. 生产库绝对隔离** | 严禁打开生产库 | 仅对生产库做 SHA256 检查，所有运行均在临时目录执行，生产账本零修改 | **通过** |

---

## 3. 独立源码突变坏控验证（4 项真实单点隔离突变 × 3-Way 对照）

为确证守卫代码在真实运行中具备真实的承重能力，在临时拷贝环境中实施了 4 项真实源码单点突变，并在独立测试驱动下对每项突变进行 **3-Way 对照（正向合法、定向坏用例、无关坏用例）** 与 **逆突变 SHA 逐字节一致性核验**：

| 突变 ID | 守卫目标 | 真实源码突变点 | 正向合法用例 | 定向坏用例（突变导致由绿变红） | 无关坏用例（保持拦截） | 逆突变恢复 SHA | 判定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **MUT-01** | 一级批准门禁 | `if T4_APPROVAL_KEYWORD not in section_text:` → `if False and ...:` | **PASS** (合法通过) | **TURNS RED** (缺失关键字本应 exit 3，突变后被非法放行) | **RETAINED** (预算超限仍被拦截 exit 5) | 逐字节一致 | **PASS** |
| **MUT-02** | 单次预算门禁 | `if spec.wall_budget_seconds > T4_MAX_PER_RUN_WALL_SECONDS:` → `if False and ...:` | **PASS** (500s 合法通过) | **TURNS RED** (650s 本应 exit 5，突变后被非法放行) | **RETAINED** (缺失批准仍被拦截 exit 3) | 逐字节一致 | **PASS** |
| **MUT-03** | 累计预算门禁 | `cumulative_reserved + ... > T4_MAX_CUMULATIVE_WALL_SECONDS` → `False and (...)` | **PASS** (1500s 合法通过) | **TURNS RED** (1900s 本应在 Step 5 零创建账本拒绝，突变后漏至 Step 6 且生成脏数据) | **RETAINED** (缺失批准仍被拦截 exit 3) | 逐字节一致 | **PASS** |
| **MUT-04** | 资源物理内存 | `if rss_bytes > max_rss_bytes:` → `if False and ...:` | **PASS** (32 GiB 合法通过) | **TURNS RED** (低门限本应 exit 2，突变后被非法放行) | **RETAINED** (缺失批准仍被拦截 exit 3) | 逐字节一致 | **PASS** |

实测结果：**4/4 项单点真实源码突变全部通过 3-Way 对照核验，定向坏用例百分之百由绿变红，主仓源码零漂移。**

---

## 4. 关键技术细节核实说明

### 4.1 模型文件大小与传输 Payload 的精确对账
在审计模型清单规格时，针对历史报告中 `1,459,675,816` 字节与 `1,655,306,028` 字节的差异进行了逐源核查：
- **模型落盘实际字节**: `vjepa` 5 个文件（1,310,663,844 B） + `depth-anything-v2` 7 个文件（149,011,972 B） = **1,459,675,816 字节**。T23 代码 `TOTAL_T4_BYTES` 与 `check_model_weights_manifest` 严格以此磁盘规格为准进行校验，完全正确。
- **历史传输 Payload**: T21 阶段下载协议层产生的总传输量为 **1,655,306,028 字节**（含 HTTP 封包/LFS 指针等传输开销）。T23 作者报告在文字说明中提及该数字，但生产代码中精确绑定的是 1,459,675,816 字节的磁盘实际哈希清单。本审计确证二者无冲突。

### 4.2 累计预算的双重防护机制（Double Defense）
在对 MUT-03 进行深度分析时发现，T23 实现与底层 `RunStore` 形成了严密的双重防护：
1. **第一道防线（Benchmark Step 5）**: 在创建 run 记录之前直接读取 SQLite 账本历史累计已用额度，如超限则直接拒绝（exit 5），防止向数据库写入无意义的失败脏记录；
2. **第二道防线（RunStore Step 6）**: 即使 Step 5 被绕过，`RunStore.consume` 内置的 `max_daily_active_seconds` 依然会触发 `BudgetExceeded` 并锁定该 run 为 `failed`。两道防线互相配合，具有极高的工程鲁棒性。

### 4.3 代码卫生与生产安全
全仓静态排查确证：
- 无 `--fake-backend`、`--mock` 或任何环境变量后门开关（如 `AWZ_D14_SABOTAGE` 类绕过）；
- 子命令 `teacher-benchmark` 采用延迟导入，不增加主 CLI 启动开销；
- `ruff check reports/V-V9-T23/` 全部通过（0 errors）。

---

## 5. 复现与核验命令

```bash
# 运行非作者独立 CPU 审计套件与隔离源码突变
./reports/V-V9-T23/run_all_verifications.sh

# 检查代码格式与规范
.venv/bin/ruff check reports/V-V9-T23/
```

---

## 6. 最终结论

`gemini-w9p4` 提交的 `ainerzero.V9.T23` 实现完全满足所有安全性、预算控制、互斥保护、零副作用 inspect 规约要求，通过全部 10 项独立功能审计与 4 项 3-way 隔离源码单点突变坏控。

**审计结论：验收通过（accepted）。建议统筹层正式合并闭环，后续教师模型测试可在受控守卫路径下放行。**
