# ainerzero.V9.T30 执行报告：【CPU修复】T26已验收入口缺真实父监督/worker及只读账本缺陷

- **任务 ID**：`ainerzero.V9.T30`
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

## 一、原始历史产物字节级归档与完整性核对

开工前已将 T26/T27 历史交付的 6 项源码/测试文件以及 2 份历史报告逐字节完整归档至 `reports/V9-T30/archive/`，清单见 `reports/V9-T30/archive/archive_manifest.txt`：

| 归档相对路径 | 原始 SHA-256 | 状态 |
| :--- | :--- | :--- |
| `reports/V9-T30/archive/source/src/ainerzero/cli.py` | `aa1e42d6d426318db95be28068232859027d567541fd31dabf88cd72ae81db2b` | **SEALED** |
| `reports/V9-T30/archive/source/src/ainerzero/v9/teachers/benchmark.py` | `8d64e8865f1bea36216e31dbba30fd89b84ccef9ebda321d2977ee7f6929fc4c` | **SEALED** |
| `reports/V9-T30/archive/source/src/ainerzero/v9/teachers/benchmark_commands.py` | `b8278b83acf1493e925955430064c6a14de24eddacde99bb94b8f513edb2cb5f` | **SEALED** |
| `reports/V9-T30/archive/source/src/ainerzero/v9/teachers/benchmark_protocol.py` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | **SEALED** |
| `reports/V9-T30/archive/source/src/ainerzero/v9/teachers/da3_controlled.py` | `25874199f496647ca2960b6204906c910a42b06adfed77172d1eb8a6a082baeb` | **SEALED** |
| `reports/V9-T30/archive/source/tests/test_teacher_da3_controlled.py` | `8e288b80ce5ea3d03d44d259a1e29a7d170a2030e35813c071f6c8ef18e81326` | **SEALED** |
| `reports/V9-T30/archive/reports/V9-T26/REPORT.md` | `3108cbffc61790418898c009705b07a79dd6493773d993e93915ac234a287896` | **SEALED** |
| `reports/V9-T30/archive/reports/V-V9-T26/REPORT.md` | `c11f00282ea4a6d840d93c190666d8d5d6267ba79b75080726b5c9cbd90010d6` | **SEALED** |

---

## 二、决定性缺陷分析与系统性修复

统筹者与独立审计指出的原代码缺陷均已彻底修复：

### 1. 真实子进程 Worker 架构与父进程周期监督
- **原缺陷**：`da3_controlled.py` 第 548 行仅为父进程内同步调用 `adapter.run_benchmark(spec)`，整文件无 `Popen`、无独立进程组、无 `killpg`，所谓父监督无法防御真实子进程失控。
- **修复实现**：
  - 新增专用受控子进程入口 `src/ainerzero/v9/teachers/da3_worker.py`，负责独立进程中的作业加载、基准模拟/真实执行及结构化 JSON 产出。
  - 父进程通过 `subprocess.Popen([python, "-m", "ainerzero.v9.teachers.da3_worker", ...], start_new_session=True)` 启动子进程组，使子进程成为独立 Session/Process Group 组长（`pgid == proc.pid`）。
  - 父进程进入周期监督轮询循环（50ms 间隔）：
    1. **墙钟硬超时监控**：单次超过预算上限立刻触发整组强杀。
    2. **整组进程 RSS 监控**：遍历 `psutil` 关联至该 `pgid` 的全部进程内存之和，超过 8.0 GiB 立刻触发整组强杀。
    3. **系统内存守卫**：系统可用内存低于 256 MiB 时立刻熔断。
    4. **组长早退/孙进程残留侦测（`grandchild_leak`）**：组长退出后若进程组内仍有残留孤儿孙进程，立刻判定违规并对整组执行清洗。
  - 终止协议采用 `os.killpg(pgid, signal.SIGTERM)` 配合宽限期，超时升级为 `SIGKILL`，随后通过 POSIX 语义与进程表遍历给出**整组空证明（Empty Group Proven）**。

### 2. 预留前全前置完备性门禁（Fail-Before-Reserve）
- **原缺陷**：`adapter=None` 检查位于 `store.consume` 之后且不在内部 try 块中，抛错后留下 `validating` 非终态且导致不可退还的预留坏账。
- **修复实现**：
  - 在进入 `store.create_run` 和 `store.consume` 之前，强制完成全部前置校验：模型白名单、审批记录与统计协议 JSON 物理文件、权重哈希、累计视图额度、累计预算额度以及 Worker 执行路由。
  - 缺失执行适配器或缺失前置时，直接抛出 `BenchmarkRefusalError` / `BenchmarkApprovalRefused`，绝不触碰生产账本。
  - 预留后的所有执行环节均严格包裹在事务 try 块中，任何故障均原子转换为终态 `failed`，绝不遗留半挂起记录。

### 3. 只读 Inspect 路径与零副作用保障
- **原缺陷**：调用 `calculate_cumulative_reserved_seconds` 时使用了 `RunStore(path)`，其 `__init__` 会执行 `PRAGMA user_version`、创建表、迁移模式并写 metadata 表，破坏 inspect 的零副作用要求。
- **修复实现**：
  - 改造为 `query_t6_ledger_read_only`，直接以 SQLite URI `file:{path}?mode=ro` 只读打开。
  - 绝不执行任何 DDL、不创建日志/WAL 文件、不触碰 metadata 表。实测多次 inspect 前后文件 SHA-256 及大小逐字节绝对一致。

### 4. 账本查询列名修复与损坏账本 Fail-Closed
- **原缺陷**：原代码在异常 fallback 路径中执行了 `SELECT config_json, reserved_active_seconds FROM runs`，而实际数据库列名为 `active_seconds`，导致产生 `no such column` 异常；原代码直接捕获异常并返回 0.0，使损坏账本静默归零绕过预算。
- **修复实现**：
  - 修正 SQL 查询列为真实列 `active_seconds`。
  - 严禁任何 fallback 归零逻辑：数据库不存在时返回 0，若文件存在但无法只读打开、缺少 `runs` 表、格式损坏或包含畸形 JSON，立即抛出 `BenchmarkRefusalError` 阻断执行（Fail-Closed）。

### 5. T4 与 T6 身份隔离及累计 64 视图硬配额
- **原缺陷**：视图配额仅检查单 job `views <= 64`，缺乏跨 job 的累计物理台账；T6 视图容易在多次派生工作中突破 64 限制。
- **修复实现**：
  - 实现 `calculate_t6_cumulative_views` 与 `check_t6_views_quota`，将 64 视图锁定为同次派生工作的全生命周期上限。
  - 校验公式：`cumulative_views + requested_views <= 64`；超标立即阻断（退出码 2）。
  - T4（1800s）与 T6（1200s，64 视图）按 `task == "ainerzero.V9.T6"` 在 RunStore 中物理隔离，互不干扰。

---

## 三、四组源码单区域变异对照（Mutation Controls）

在 `tests/test_da3_supervision.py` 中构建了 4 组完全基于实际子进程、捕获真实 `returncode`、`stdout`、`stderr` 的单区域变异对照：

| 变异对照组 | 目标机制 | Case A 正常基准 | Case B 注入变异 / 坏输入 | 裁定结果 |
| :--- | :--- | :--- | :--- | :--- |
| **Control 1: 墙钟超时父监督** | `run_supervised_da3_worker` | 任务耗时 0.02s <= 1.0s 预算：`rc=0`，`violation=None`，顺利完成 | 任务休眠 5.0s > 0.2s 预算：父进程主动强杀整组，`violation=timeout`，`empty_group_proven=True` | **SENSITIVE_VALID** |
| **Control 2: 进程组 RSS 保护** | `run_supervised_da3_worker` | 内存占用 5 MiB <= 50 MiB 限制：`rc=0`，顺利完成 | 内存占用 100 MiB > 30 MiB 限制：父进程主动强杀整组，`violation=rss_limit`，`empty_group_proven=True` | **SENSITIVE_VALID** |
| **Control 3: 孤儿孙进程泄漏** | `run_supervised_da3_worker` | 正常子进程退出且无残留：`rc=0`，`empty_group_proven=True` | 组长提前退出遗留休眠孙进程：父进程侦测到残留孙进程，强杀全组，`violation=grandchild_leak`，`empty_group_proven=True` | **SENSITIVE_VALID** |
| **Control 4: 损坏账本 Fail-Closed** | `query_t6_ledger_read_only` | 正常合法 SQLite 账本：准确返回实际预留秒数与 12 views | 损坏/非 SQLite 文件：立即抛出 `BenchmarkRefusalError` 阻断，拒绝归零放行 | **SENSITIVE_VALID** |

---

## 四、自动化测试套件执行证据

运行 `.venv/bin/pytest tests/test_teacher_da3_controlled.py tests/test_da3_supervision.py -v`：

```text
tests/test_teacher_da3_controlled.py::test_inspect_zero_side_effects PASSED [  5%]
tests/test_teacher_da3_controlled.py::test_model_whitelist_enforcement PASSED [ 10%]
tests/test_teacher_da3_controlled.py::test_views_quota_gate PASSED       [ 15%]
tests/test_teacher_da3_controlled.py::test_run_mode_refuses_when_approval_or_protocol_missing PASSED [ 20%]
tests/test_teacher_da3_controlled.py::test_per_run_budget_gate PASSED    [ 25%]
tests/test_teacher_da3_controlled.py::test_cumulative_budget_and_non_refundable_reservation PASSED [ 30%]
tests/test_teacher_da3_controlled.py::test_t4_and_t6_runstore_task_segregation PASSED [ 35%]
tests/test_teacher_da3_controlled.py::test_worker_lock_mutual_exclusion PASSED [ 40%]
tests/test_teacher_da3_controlled.py::test_process_group_termination_and_cleanup PASSED [ 45%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_inspect PASSED [ 50%]
tests/test_teacher_da3_controlled.py::test_cli_subprocess_run_refused PASSED [ 55%]
tests/test_teacher_da3_controlled.py::test_four_source_mutation_controls PASSED [ 60%]
tests/test_da3_supervision.py::test_supervision_clean_run PASSED         [ 65%]
tests/test_da3_supervision.py::test_supervision_timeout_terminates_group PASSED [ 70%]
tests/test_da3_supervision.py::test_supervision_rss_limit_terminates_group PASSED [ 75%]
tests/test_da3_supervision.py::test_supervision_grandchild_leak_detected_and_killed PASSED [ 80%]
tests/test_da3_supervision.py::test_cumulative_views_quota_enforced PASSED [ 85%]
tests/test_da3_supervision.py::test_ledger_readonly_inspect_never_writes PASSED [ 90%]
tests/test_da3_supervision.py::test_corrupt_ledger_fails_closed PASSED   [ 95%]
tests/test_da3_supervision.py::test_four_source_mutation_controls PASSED [100%]

============================== 20 passed in 4.50s ==============================
```

---

## 五、真实 CLI 子进程调用实测

| 调用命令 | 实测返回码 | 预期返回码 | 核心输出特征 |
| :--- | :--- | :--- | :--- |
| `python3 -m ainerzero.cli teacher-da3 --mode inspect` | `0` | `0` | `side_effects: {lock_acquired: false, ledger_written: false, models_loaded: 0}` |
| `python3 -m ainerzero.cli teacher-benchmark --teacher t6 --mode inspect` | `0` | `0` | 正确路由至 T6 DA3 只读检查，无生产库写入 |
| `python3 -m ainerzero.cli teacher-da3 --mode run` | `3` | `3` | 缺失统计协议 JSON 文件，在预留前准确拒绝（`status: refused_approval`） |
| `python3 -m ainerzero.cli teacher-da3 --mode run --views 100` | `2` | `2` | 超过单次 64 视图上限，在预留前准确拒绝（`status: refused_resource`） |

---

## 六、交付文件 SHA-256 清单

```text
60a6c7f099649212c1fc35ff27cbe74dcb48f3b5cb1d3ad3199ce6020082afc3  src/ainerzero/cli.py
aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb  src/ainerzero/v9/teachers/benchmark.py
d9a711fca64fa7944fade8f2256079737fdaa3ccf63dec50161614fefe793383  src/ainerzero/v9/teachers/benchmark_commands.py
6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4  src/ainerzero/v9/teachers/benchmark_protocol.py
93016b3d5e6313db6aa82900cc598db59805ff2c1841da8c30c28646e08c7c18  src/ainerzero/v9/teachers/da3_controlled.py
7046723dc08b1ac819b6a46e80959889602034fb2fee9f7ff94142cfb103d205  src/ainerzero/v9/teachers/da3_worker.py
f8f863a6a1e04cfc0df80f64a5b4aa361a43b3ebca1a14798af821ba40c69ef7  tests/test_teacher_da3_controlled.py
63b3d92193c605d400f0432a5f52a51f6e2f8ecc243355fbd310c68abd419383  tests/test_da3_supervision.py
```

---

## 七、合规性与约束确认

1. **纯 CPU 工程实现**：零真实 DA3 / MLX / MPS / Blender 运行，零模型权重下载，零 pip 依赖安装。
2. **生产环境零污染**：生产锁 `artifacts/locks/m0-worker.lock` 与生产数据库 `artifacts/v9/teachers/benchmark/runs.db` 未产生任何非预期修改。
3. **历史记录完整保留**：原 T26/T27 历史验收记录及两份报告已完好封存于 `archive/`。
4. **代码范围严格受限**：改动完全限制于任务声明的文件范围之内。
