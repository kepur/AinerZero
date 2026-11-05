# ainerzero.V9.T30 r2 执行报告：【CPU修复】T26已验收入口缺真实父监督/worker及只读账本缺陷

- **任务 ID**：`ainerzero.V9.T30`
- **轮次**：`r2`（续修闭环）
- **执行者**：`antigravity-h4d8`
- **项目**：AinerZero · V9 落地：NeuroGeometry × H-JEPA 世界脑（P0 无训练） → 轨道 T 教师接入
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：implement · GPU：否（纯 CPU 真实子进程与工程守卫）
- **依据**：`reports/V9-T6/r3/CONTROLLED-ENTRY-TASK.md`、`reports/V-V9-T26/REPORT.md`、`COORDINATION.md`、`AGENTS.md`
- **受控文件范围**：
  - `src/ainerzero/cli.py`
  - `src/ainerzero/v9/teachers/benchmark.py`
  - `src/ainerzero/v9/teachers/benchmark_commands.py`
  - `src/ainerzero/v9/teachers/benchmark_protocol.py`
  - `src/ainerzero/v9/teachers/da3_controlled.py`
  - `src/ainerzero/v9/teachers/da3_worker.py`
  - `tests/test_teacher_da3_controlled.py`
  - `tests/test_da3_supervision.py`
  - `reports/V9-T30/`

---

## 一、r1 历史产物字节级归档与原证据保存

收到一级（统筹者）驳回意见后，已在修改前将 r1 全部 8 项源码/测试文件以及 r1 报告/指标逐字节完整封存至 `reports/V9-T30/archive/r1/`，并与驳回意见核对 SHA 完全一致：

- 封存清单见：[r1_manifest.txt](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T30/archive/r1/r1_manifest.txt)
- `da3_controlled.py` r1 SHA-256：`93016b3d5e6313db6aa82900cc598db59805ff2c1841da8c30c28646e08c7c18`（核验无误）
- `da3_worker.py` r1 SHA-256：`7046723dc08b1ac819b6a46e80959889602034fb2fee9f7ff94142cfb103d205`（核验无误）
- 历史 T26/T27 归档保持密封：[archive_manifest.txt](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T30/archive/archive_manifest.txt)

---

## 二、r2 关键缺陷闭环整改

针对统筹者指出的 8 项决定性缺陷，实施了全面彻底的重构：

### 1. 真实 Lazy Worker 路线与既有 pipeline 路由
- **缺陷**：原 r1 的 `real_pipeline` 只 `return 2`，无既有 `envs/teachers/.venv-t6` 及 `pipeline.py` 的调用路由。
- **整改**：
  - 在 `src/ainerzero/v9/teachers/da3_worker.py` 中实现真实 lazy pipeline 路由：动态定位 `envs/teachers/t6/pipeline.py` 与 `.venv-t6/bin/python`。
  - 调用 pipeline 官方 `source_identity()` 逐文件校验上游源码树 SHA-256（`upstream_files_sha256`），并调用 `inspect_weights()` 校验磁盘权重与配置。
  - 在未获得统筹者执行授权（无 `--allow-model-execution`）时，受控拦截模型前向推理，输出 `status: blocked`、`model_runs: 0`、`pipeline_verified: true`，给出清晰治理阻断理由并退出码 3。

### 2. 真实候选标明 `model_runs=0`
- **缺陷**：默认 mock 可返回 completed 候选却未标记 `model_runs=0`，易造成虚假执行证据。
- **整改**：
  - `da3_worker.py` 在执行 mock 测试替身时，输出 JSON 与 prediction_record 显式硬编码 `"model_runs": 0` 和 `"is_mock": true`。
  - `da3_controlled.py` 返回的顶层报告结构显式透传 `"model_runs": 0`，杜绝任何假性完成宣称。

### 3. 彻底消除同步 Adapter 绕开父监督的后门
- **缺陷**：原代码存在 `if adapter is not None:` 分支直接在父进程内同步调用，并硬编码 `empty_group_proven=True`，彻底破坏了父监督隔离。
- **整改**：
  - 彻底移除同步调用逻辑。**所有执行路径必须无条件通过 `run_supervised_da3_worker`**，在独立子进程组（`start_new_session=True`）中执行。
  - Adapter 仅作为测试替身配置注入，父进程始终对子进程组进行轮询周期监督，通过真实 POSIX 语义与进程遍历给出 `empty_group_proven` 证明。

### 4. 严格复用既有硬件与资源守卫（不得放宽保护线）
- **缺陷**：原代码仅自设 `available < 256MiB`，未复用既有电源、可用内存与 swap 守卫。
- **整改**：
  - 集成 `ainerzero.runtime.hardware.collect_hardware` 与 `resource_gate.py` 注册保护线：
    1. **电源门**：`power_source == "battery"` 立即拒止（必须为 AC 供电）。
    2. **物理可用内存门**：`system_available_bytes >= 16.0 GiB`（保持 `system_reserve_gib = 16.0` 严格保护线，绝不放宽）。
    3. **交换空间增长门**：`swap_growth <= 1.0 GiB`（基线对齐，运行中增长超标立即熔断强杀）。
    4. **进程组 RSS 门**：整组 RSS 超过 8.0 GiB 立即强杀。

### 5. 锁定中央路径与锁内重查双重校验（Double-Checked Locking）
- **缺陷**：原 store/lock 路径允许随 spec 随意变动；累计预算在锁外检查，锁内未重查，存在并发竞态与绕开账本风险。
- **整改**：
  - 在正式运行模式下（非显式 `test_substitute`），强制断言 `store_path == DEFAULT_STORE_PATH` 且 `lock_path == DEFAULT_LOCK_PATH`，禁止改动路径绕开全局账本。
  - 实施锁外早检查 + 独占互斥锁内**二次重查（Double-Checked Locking）**：进入 `with worker_lock(...)` 后再次执行 `query_t6_ledger_read_only`，核对累计 views 与累计秒数，超标在原子预留前拒绝。

### 6. 生产 CLI 预留前拒绝（Reject-Before-Reservation）
- **缺陷**：生产 CLI 不得默认 fake 成功或注入无监督 adapter。
- **整改**：
  - 在 `execute_guarded_da3_benchmark` 中，若为正式运行且未经统筹者正式放行（`not test_substitute`），在 `store.create_run` 和 `store.consume` 之前立即抛出 `BenchmarkRefusalError`：
    > `"T6 DA3 real model execution is blocked: coordinator execution release authorization not granted. Pre-work reservation refused."`
  - 确保生产账本零污染、零坏账、零不可退还扣费。

---

## 三、四组完整源码单区域变异三方向证据（3-Direction Proof）

在 `reports/V9-T30/r2/mutations/` 下生成了 4 组独立的物理源码单区域变异文件，并在 `tests/test_da3_supervision.py` 中严格执行了三方向验证：

1. **Direction 1 (Clean Pass)**：原版源码 + 正常输入 $\rightarrow$ 顺利通过（`rc=0`, 预期 stdout, 空 stderr）。
2. **Direction 2 (Clean Catch)**：原版源码 + 目标违规输入 $\rightarrow$ 精确阻断/强杀（捕获超时/超 RSS/泄漏/异常，给出空组证明）。
3. **Direction 3 (Mutated Proof)**：单区域变异源码 + 目标违规输入 $\rightarrow$ **变异代码无法检测违规/静默放行**，决定性证明该区域源码的不可或缺性与高敏感性。

| 变异对照组 | 物理变异文件路径 | 单区域变异点 | Dir 1: 正常基准 | Dir 2: 目标拦截 (Clean) | Dir 3: 变异失效 (Mutated) | 敏感性裁定 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Control 1: 墙钟超时父监督** | `r2/mutations/mutation_1_timeout/da3_controlled.py` | 禁用超时比较：`if False and elapsed > effective_timeout:` | `rc=0`, `violation=None` | 主动强杀整组，`violation=timeout`, `empty_group=True` | 变异代码未强杀，休眠超标放行，`violation=None` | **SENSITIVE_VALID** |
| **Control 2: 进程组 RSS 保护** | `r2/mutations/mutation_2_rss/da3_controlled.py` | 禁用 RSS 比较：`if False and current_group_rss > max_rss_bytes:` | `rc=0`, 5 MiB 正常通过 | 主动强杀整组，`violation=rss_limit`, `empty_group=True` | 变异代码未强杀，200 MiB 内存超标放行，`violation=None` | **SENSITIVE_VALID** |
| **Control 3: 孤儿孙进程泄漏** | `r2/mutations/mutation_3_leak/da3_controlled.py` | 禁用泄漏检测：`if False and surviving_pids:` | `rc=0`, 正常无孤儿 | 侦测到孤儿，强杀整组，`violation=grandchild_leak`, `empty_group=True` | 变异代码未检测泄漏，残留进程逃逸，`violation=None` | **SENSITIVE_VALID** |
| **Control 4: 损坏账本 Fail-Closed** | `r2/mutations/mutation_4_ledger/da3_controlled.py` | 异常时返回零：`return 0.0, 0` | 正常 DB 正确计算 15 views | 损坏 DB 抛 `BenchmarkRefusalError` 阻断 | 变异代码吞异常静默返回 `0.0, 0`，破坏预算屏障 | **SENSITIVE_VALID** |

---

## 四、自动化测试套件执行证据

运行 `.venv/bin/pytest tests/test_teacher_da3_controlled.py tests/test_da3_supervision.py -v`（**22 项测试全部通过**）：

```text
tests/test_teacher_da3_controlled.py::test_inspect_zero_side_effects PASSED [  4%]
tests/test_teacher_da3_controlled.py::test_model_whitelist_enforcement PASSED [  9%]
tests/test_teacher_da3_controlled.py::test_views_quota_gate PASSED       [ 13%]
tests/test_teacher_da3_controlled.py::test_run_mode_refuses_when_approval_or_protocol_missing PASSED [ 18%]
tests/test_teacher_da3_controlled.py::test_per_run_budget_gate PASSED    [ 22%]
tests/test_teacher_da3_controlled.py::test_cumulative_budget_and_non_refundable_reservation PASSED [ 27%]
tests/test_teacher_da3_controlled.py::test_t4_and_t6_runstore_task_segregation PASSED [ 31%]
tests/test_teacher_da3_controlled.py::test_worker_lock_mutual_exclusion PASSED [ 36%]
tests/test_teacher_da3_controlled.py::test_process_group_termination_and_cleanup PASSED [ 40%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_inspect PASSED [ 45%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_run_refused PASSED [ 50%]
tests/test_teacher_da3_controlled.py::test_four_source_mutation_controls PASSED [ 54%]
tests/test_da3_supervision.py::test_supervision_clean_run PASSED         [ 59%]
tests/test_da3_supervision.py::test_supervision_timeout_terminates_group PASSED [ 63%]
tests/test_da3_supervision.py::test_supervision_rss_limit_terminates_group PASSED [ 68%]
tests/test_da3_supervision.py::test_supervision_grandchild_leak_detected_and_killed PASSED [ 72%]
tests/test_da3_supervision.py::test_hardware_resource_guards PASSED      [ 77%]
tests/test_da3_supervision.py::test_cumulative_views_quota_and_double_checked_locking PASSED [ 81%]
tests/test_da3_supervision.py::test_ledger_readonly_inspect_never_writes PASSED [ 86%]
tests/test_da3_supervision.py::test_corrupt_ledger_fails_closed PASSED   [ 90%]
tests/test_da3_supervision.py::test_lazy_worker_real_pipeline_routing PASSED [ 95%]
tests/test_da3_supervision.py::test_four_source_mutation_controls PASSED [100%]

======================== 22 passed in 69.86s (0:01:09) =========================
```

---

## 五、真实 CLI 子进程调用实测

| 调用命令 | 实测返回码 | 实际控制台输出特征 | 治理与安全断言 |
| :--- | :--- | :--- | :--- |
| `python3 -m ainerzero.cli teacher-da3 --mode inspect` | `0` | `side_effects: {lock_acquired: false, ledger_written: false, models_loaded: 0}` | 零副作用只读检查通过 |
| `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode inspect` | `0` | 自动路由至 T6 DA3 只读检查 | 路由正确，零生产库污染 |
| `python3 -m ainerzero.cli teacher-da3 --mode run` (缺协议) | `3` | `status: refused_approval, error: Frozen statistical evaluation protocol JSON file missing` | 预留前被统计协议门阻断 |
| `python3 -m ainerzero.cli teacher-da3 --mode run --views 100` | `2` | `status: refused_resource, error: Requested 100 views exceeds T6 registered quota` | 预留前被视图额度门阻断 |
| `python3 -m ainerzero.cli teacher-da3 --mode run` (有协议无授权) | `1` | `status: refused, error: T6 DA3 real model execution is blocked: coordinator execution release authorization not granted.` | 预留前被治理门阻断，拒绝虚假执行，零扣费 |
| `python3 -m ainerzero.cli teacher-da3 --mode run --test-substitute ...` | `0` | `status: completed, model_runs: 0, is_mock: true, supervision: {empty_group_proven: true}` | 显式 CPU 替身受控通过，准确标明 model_runs=0 |

---

## 六、交付文件 SHA-256 清单

```text
60a6c7f099649212c1fc35ff27cbe74dcb48f3b5cb1d3ad3199ce6020082afc3  src/ainerzero/cli.py
aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb  src/ainerzero/v9/teachers/benchmark.py
fcd84832f6d46cf48910dd589a1b523ffb87ee669abe334d819877e711b1c760  src/ainerzero/v9/teachers/benchmark_commands.py
6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4  src/ainerzero/v9/teachers/benchmark_protocol.py
754d5f92a00a855c7731f82944a33ba2d965e8e7932f70e8253d100e43cfeb55  src/ainerzero/v9/teachers/da3_controlled.py
25e323c546988bb00d190c789c701b1c018cc7a48883aa9b2a0234962c13b28d  src/ainerzero/v9/teachers/da3_worker.py
f8f863a6a1e04cfc0df80f64a5b4aa361a43b3ebca1a14798af821ba40c69ef7  tests/test_teacher_da3_controlled.py
994db3c43866c774f4a87876138644c3cd8a2c579c601bb3d744eab16b68a421  tests/test_da3_supervision.py
b9ec92b85b21db07c1e52500518f7e9e9ffb27e062402c08b47f753859c32925  reports/V9-T30/r2/mutations/mutation_1_timeout/da3_controlled.py
8aced6388071cf5b07acd82cc33844cb36df214e8d5d752d2ddd947caf8fb9ff  reports/V9-T30/r2/mutations/mutation_2_rss/da3_controlled.py
2b970e2aee1c31681864a74dc3b545a71ce0939b8f6629b5b4435c7fb5cee5e8  reports/V9-T30/r2/mutations/mutation_3_leak/da3_controlled.py
dbbb291196b98a184aabedfa3e5925b3967bf158b2d86af2d2beb295dd5467ed  reports/V9-T30/r2/mutations/mutation_4_ledger/da3_controlled.py
```

---

## 七、合规性与约束说明

1. **纯 CPU 实现**：全过程无真实 DA3 / MLX / MPS / Blender 运行，无模型权重下载，无 pip 依赖安装。
2. **生产环境零变动**：生产锁 `artifacts/locks/m0-worker.lock` 与生产数据库 `artifacts/v9/teachers/benchmark/runs.db` 零污染。
3. **保留全部证据**：T26/T27 原报告、r1 源码与报告均已完整归档至 `archive/`。
4. **T6 状态维持**：T6 保持 blocked，任何正式已有预留未退款、未重置。
