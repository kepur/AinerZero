# ainerzero.V9.T30 执行报告（r3）：【CPU修复】T26已验收入口缺真实父监督/worker及只读账本缺陷

- **任务 ID**：`ainerzero.V9.T30`（第 3 轮交付，r3）
- **执行者**：`antigravity-h4d8`
- **项目**：AinerZero · V9 落地：NeuroGeometry × H-JEPA 世界脑（P0 无训练） → 轨道 T 教师接入
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：implement · GPU：否（纯 CPU 真实子进程与工程守卫）
- **依据**：统筹打回裁决（r2 针对未提供统筹放行开关的审查意见）、`reports/V9-T6/r3/CONTROLLED-ENTRY-TASK.md`、`reports/V-V9-T26/REPORT.md`、`COORDINATION.md`、`AGENTS.md`
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

## 一、r2 交付字节级归档与完整性核对

开工前已将 r2 交付的 8 项源码/测试文件以及 2 份报告逐字节完整归档至 `reports/V9-T30/archive/r2/`，清单见 `reports/V9-T30/archive/r2/r2_manifest.txt`：

| 归档相对路径 | 原始 r2 SHA-256 | 状态 |
| :--- | :--- | :--- |
| `reports/V9-T30/archive/r2/source/src/ainerzero/cli.py` | `60a6c7f099649212c1fc35ff27cbe74dcb48f3b5cb1d3ad3199ce6020082afc3` | **SEALED** |
| `reports/V9-T30/archive/r2/source/src/ainerzero/v9/teachers/benchmark.py` | `aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb` | **SEALED** |
| `reports/V9-T30/archive/r2/source/src/ainerzero/v9/teachers/benchmark_commands.py` | `fcd84832f6d46cf48910dd589a1b523ffb87ee669abe334d819877e711b1c760` | **SEALED** |
| `reports/V9-T30/archive/r2/source/src/ainerzero/v9/teachers/benchmark_protocol.py` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | **SEALED** |
| `reports/V9-T30/archive/r2/source/src/ainerzero/v9/teachers/da3_controlled.py` | `754d5f92a00a855c7731f82944a33ba2d965e8e7932f70e8253d100e43cfeb55` | **SEALED** |
| `reports/V9-T30/archive/r2/source/src/ainerzero/v9/teachers/da3_worker.py` | `25e323c546988bb00d190c789c701b1c018cc7a48883aa9b2a0234962c13b28d` | **SEALED** |
| `reports/V9-T30/archive/r2/source/tests/test_teacher_da3_controlled.py` | `f8f863a6a1e04cfc0df80f64a5b4aa361a43b3ebca1a14798af821ba40c69ef7` | **SEALED** |
| `reports/V9-T30/archive/r2/source/tests/test_da3_supervision.py` | `994db3c43866c774f4a87876138644c3cd8a2c579c601bb3d744eab16b68a421` | **SEALED** |
| `reports/V9-T30/archive/r2/reports/REPORT.md` | `0e711763eec7a44a7e31356a3d470440f7135c1133e544e14cf41950ee01b88d` | **SEALED** |
| `reports/V9-T30/archive/r2/reports/metrics.json` | `b0f98b5c80dd76051419799c248750cd7e0b529392ab276dfc20c637c8223cbc` | **SEALED** |

历史归档文件（T26/T27 原始字节封存、r1 缺陷字节封存、r2 封存）均完整保留，路径为：
- `reports/V9-T30/archive/archive_manifest.txt`
- `reports/V9-T30/archive/r1/r1_manifest.txt`
- `reports/V9-T30/archive/r2/r2_manifest.txt`

---

## 二、r3 核心修复：统筹放行开关与真实执行通道打通

### 1. 问题根因分析
在 r2 中，`execute_guarded_da3_benchmark` 在未指定 `test_substitute` 时无条件抛出 `BenchmarkRefusalError("T6 DA3 real model execution is blocked: coordinator execution release authorization not granted")`。
虽然实现了“在碰 RunStore 前拒绝”（Fail-Before-Reserve），但由于未暴露显式放行开关，且 `allow_model_execution` 仅在 worker 内部存在而未与中央入口接通，导致未来统筹者无法通过中央入口执行正式 T6 标定。

### 2. r3 解决方案与多层闭环

1. **CLI 参数显式支持**：
   在 `teacher-benchmark` 与 `teacher-da3` 两个命令中增加：
   - `--coordinator-release`：统筹者显式放行开关（默认 False，fail-closed）；
   - `--allow-model-execution`：显式允许模型实际执行（默认 False，fail-closed）。
2. **调度层与协议对象接通**：
   - `benchmark_protocol.py` 中的 `DA3RunSpec` 新增 `coordinator_release: bool = False` 与 `allow_model_execution: bool = False` 字段，并在 `to_dict()` 序列化中完整传递；
   - `benchmark_commands.py` 解析 CLI 参数并注入 `spec` 与 `execute_guarded_da3_benchmark`。
3. **预留前放行门禁判定**：
   在 `da3_controlled.py` 的 Step 7 中，综合判定：
   ```python
   is_released = (
       coordinator_release
       or allow_model_execution
       or getattr(spec, "coordinator_release", False)
       or getattr(spec, "allow_model_execution", False)
       or bool(approval.get("coordinator_release", False))
       or bool(approval.get("protocol_details", {}).get("coordinator_release", False))
   )
   if not test_substitute and not is_released:
       raise BenchmarkRefusalError(
           "T6 DA3 real model execution is blocked: coordinator execution release authorization not granted. "
           "Formal model execution requires explicit coordinator authorization flag (--coordinator-release or --allow-model-execution). "
           "Pre-work reservation refused."
       )
   ```
   **行为特性**：
   - 默认生产运行（无 `--coordinator-release` 且无 `--test-substitute`）：在接触 RunStore 之前立即拒绝（Exit 1 / `BenchmarkRefusalError`），绝不产生脏 Run 或扣除不可退还预算；
   - 统筹者显式放行（带 `--coordinator-release` 或 `--allow-model-execution`）：放行通过，依次完成硬件资源门检查、获取共享锁、双重重查账本配额、RunStore 预留、并进入真实子进程组受控监督；
   - 测试替身模式（`--test-substitute`）：允许在隔离数据库/锁中执行 mock_run。
4. **监督层参数传递与子进程组隔离**：
   - `execute_guarded_da3_benchmark` 将 `allow_model_execution=effective_allow_model` 传递至 `run_supervised_da3_worker`；
   - `run_supervised_da3_worker` 在启动子进程组时添加 `--allow-model-execution`，并在环境字典中注入 `KMP_DUPLICATE_LIB_OK="TRUE"`，消除 macOS 平台 OpenMP 双重初始化导致的 SIGABRT 134 闪退风险；
   - 子进程 `da3_worker.py` 在接收到 `--allow-model-execution` 时，验证 upstream source identity 与权重无误后，返回 `completed` 与 `coordinator_released: true`。

---

## 三、物理源码单区域变异三方向严密验证

保留并更新 `reports/V9-T30/r3/mutations/` 下 4 组完整物理源码文件，并在 `tests/test_da3_supervision.py` 中通过真实子进程执行验证三方向（正常通过、变异前拦截、变异后放过）：

| 变异文件相对路径 | SHA-256 | 变异区域 | 三方向证据 |
| :--- | :--- | :--- | :--- |
| `reports/V9-T30/r3/mutations/mutation_1_timeout/da3_controlled.py` | `b9ec92b85b21db07c1e52500518f7e9e9ffb27e062402c08b47f753859c32925` | 移除超时判定 `if elapsed > timeout` | 基线正常 0.02s 退出 rc=0；基线超时 3.0s 产生 timeout 违规并杀组（empty_group_proven=True）；变异代码忽略 50ms 超时完整 sleep 300ms（violation=None） |
| `reports/V9-T30/r3/mutations/mutation_2_rss/da3_controlled.py` | `8aced6388071cf5b07acd82cc33844cb36df214e8d5d752d2ddd947caf8fb9ff` | 移除 RSS 判定 `if total_rss > max_rss_bytes` | 基线分配 5 MiB 正常退出 rc=0；基线分配 200 MiB 超 80 MiB 门槛产生 rss_limit 违规并杀组；变异代码分配 200 MiB 不拦截正常退出（violation=None） |
| `reports/V9-T30/r3/mutations/mutation_3_leak/da3_controlled.py` | `2b970e2aee1c31681864a74dc3b545a71ce0939b8f6629b5b4435c7fb5cee5e8` | 移除孤儿孙进程存活检测与清理逻辑 | 基线干净子进程退出 rc=0；基线组长早退残留孤儿孙进程被父进程探测到 grandchild_leak 违规并 SIGKILL 清空；变异代码放过残留孤儿进程 |
| `reports/V9-T30/r3/mutations/mutation_4_ledger/da3_controlled.py` | `dbbb291196b98a184aabedfa3e5925b3967bf158b2d86af2d2beb295dd5467ed` | 将损坏账本异常吞掉并 fallback 返回 0.0 | 基线正常 SQLite 查询返回真实秒数与视图；基线损坏/非 SQLite 文件 fail-closed 抛出 `BenchmarkRefusalError`；变异代码吞掉异常返回 0.0 |

---

## 四、全量测试与 CLI 实测验证

运行测试：`.venv/bin/pytest tests/test_teacher_da3_controlled.py tests/test_da3_supervision.py -v`
**结果：23 / 23 passed in 72.27s (100% 通过)**：

```text
tests/test_teacher_da3_controlled.py::test_inspect_zero_side_effects PASSED [  4%]
tests/test_teacher_da3_controlled.py::test_model_whitelist_enforcement PASSED [  8%]
tests/test_teacher_da3_controlled.py::test_views_quota_gate PASSED       [ 13%]
tests/test_teacher_da3_controlled.py::test_run_mode_refuses_when_approval_or_protocol_missing PASSED [ 17%]
tests/test_teacher_da3_controlled.py::test_per_run_budget_gate PASSED    [ 21%]
tests/test_teacher_da3_controlled.py::test_cumulative_budget_and_non_refundable_reservation PASSED [ 26%]
tests/test_teacher_da3_controlled.py::test_t4_and_t6_runstore_task_segregation PASSED [ 30%]
tests/test_teacher_da3_controlled.py::test_worker_lock_mutual_exclusion PASSED [ 34%]
tests/test_teacher_da3_controlled.py::test_process_group_termination_and_cleanup PASSED [ 39%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_inspect PASSED [ 43%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_run_refused PASSED [ 47%]
tests/test_teacher_da3_controlled.py::test_coordinator_release_gate_and_cli PASSED [ 52%]
tests/test_teacher_da3_controlled.py::test_four_source_mutation_controls PASSED [ 56%]
tests/test_da3_supervision.py::test_supervision_clean_run PASSED         [ 60%]
tests/test_da3_supervision.py::test_supervision_timeout_terminates_group PASSED [ 65%]
tests/test_da3_supervision.py::test_supervision_rss_limit_terminates_group PASSED [ 69%]
tests/test_da3_supervision.py::test_supervision_grandchild_leak_detected_and_killed PASSED [ 73%]
tests/test_da3_supervision.py::test_hardware_resource_guards PASSED      [ 78%]
tests/test_da3_supervision.py::test_cumulative_views_quota_and_double_checked_locking PASSED [ 82%]
tests/test_da3_supervision.py::test_ledger_readonly_inspect_never_writes PASSED [ 86%]
tests/test_da3_supervision.py::test_corrupt_ledger_fails_closed PASSED   [ 91%]
tests/test_da3_supervision.py::test_lazy_worker_real_pipeline_routing PASSED [ 95%]
tests/test_da3_supervision.py::test_four_source_mutation_controls PASSED [100%]
```

### 生产 CLI 实测命令与返回码核验

1. **只读检查（inspect）**：
   - 命令：`.venv/bin/python -m ainerzero.cli teacher-da3 --mode inspect`
   - 结果：`exit_code: 0`，`lock_acquired: false`，`ledger_written: false`，`models_loaded: 0`，零副作用。
2. **缺协议运行（run without protocol）**：
   - 命令：`.venv/bin/python -m ainerzero.cli teacher-da3 --mode run`
   - 结果：`exit_code: 3`（`refused_approval`），明确指出协议缺失。
3. **视图超限运行（views=100 > 64）**：
   - 命令：`.venv/bin/python -m ainerzero.cli teacher-da3 --mode run --views 100`
   - 结果：`exit_code: 2`（`refused_resource`），资源门禁拦截。
4. **无统筹放行运行（run with protocol, no coordinator release）**：
   - 结果：`exit_code: 1`（`refused_approval` / `BenchmarkRefusalError`），预留前拒绝，未污染中央 RunStore。
5. **测试替身运行（run --test-substitute）**：
   - 结果：`exit_code: 0`（`completed`，`model_runs: 0`，`empty_group_proven: true`）。

---

## 五、交付物 SHA-256 清单（8 项源码与测试）

| 文件相对路径 | SHA-256 |
| :--- | :--- |
| `src/ainerzero/cli.py` | `19765ba486d016b1794cf3b45429817da901d56f9ca6b66bcd03bf3d73321c0e` |
| `src/ainerzero/v9/teachers/benchmark.py` | `aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb` |
| `src/ainerzero/v9/teachers/benchmark_commands.py` | `ccabc73d0f38cf95f06c3796b0d0e45c4d61ca7decb60327bea675fb7b4ed3ae` |
| `src/ainerzero/v9/teachers/benchmark_protocol.py` | `d7d3c35bfc82af406da9af51d275da467499a9bac96b8e4de6ccc5fad6bf49d7` |
| `src/ainerzero/v9/teachers/da3_controlled.py` | `17c7c5f9cca46b823c30eca8acf612c4ab2fd0a301b782ff09a4b117ce4cd927` |
| `src/ainerzero/v9/teachers/da3_worker.py` | `eec5fd03c1fe54f485eb2dff466cfd04939dbc895a00f33ecfb42e6672bd5e43` |
| `tests/test_teacher_da3_controlled.py` | `88450e662b61439983ae2c5b6848233673bde88b3add9170307f974efa6e4ab6` |
| `tests/test_da3_supervision.py` | `d8c3b08121cf7717a7b74924677fbd2ac9f885c1ef983724456fb97082357a55` |

---

## 六、交接与复核指引

1. **复核任务**：`ainerzero.V9.T31`（要求非作者独立 CPU 复核，继续排除旧污染作者链）。
2. **复核验证点**：
   - 验证 `execute_guarded_da3_benchmark` 在未授权时在碰 RunStore 前拒绝（exit 1），而在接收到 `--coordinator-release` 或 `--allow-model-execution` 时放行进入受控流程；
   - 验证 23 项 pytest 测试全绿通过；
   - 验证 `reports/V9-T30/r3/mutations/` 下 4 组物理源码变异的三方向拦截表现；
   - 验证中央 RunStore 与 `m0-worker.lock` 未受测试污染。
