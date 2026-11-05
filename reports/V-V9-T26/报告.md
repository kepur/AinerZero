# ainerzero.V9.T27 非作者独立 CPU 复核报告：T26 DA3 中央账本/单锁/累计预算与进程监督

- **任务 ID**：`ainerzero.V9.T27`
- **复核目标**：`ainerzero.V9.T26`（【CPU实现】T6 DA3接入既有CLI/中央RunStore及独立预算监督）
- **复核执行者**：`gemini-7a2b`（非作者独立 Agent；已排除 `gemini-kzer` 与 `codex`）
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：verify · GPU：否（纯 CPU 独立复核工程）
- **核验依据**：`reports/V9-T6/r3/CONTROLLED-ENTRY-TASK.md`、`COORDINATION.md`、`AGENTS.md`
- **受控编辑范围**：仅限于 `reports/V-V9-T26/`（严格只读产品代码，零侵入、零污染）

---

## 一、交付源码完整性与 SHA-256 确切校验

独立复核程序自磁盘直接逐字节读取 T26 交付的 6 个源码与测试文件，计算 SHA-256 并与作者原报告比对，**6/6 完全匹配，无任何静默变动或偏差**：

| 文件路径 | 原报告 SHA-256 | 独立实测 SHA-256 | 校验结果 |
| :--- | :--- | :--- | :--- |
| `src/ainerzero/cli.py` | `aa1e42d6d426318db95be28068232859027d567541fd31dabf88cd72ae81db2b` | `aa1e42d6d426318db95be28068232859027d567541fd31dabf88cd72ae81db2b` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark.py` | `8d64e8865f1bea36216e31dbba30fd89b84ccef9ebda321d2977ee7f6929fc4c` | `8d64e8865f1bea36216e31dbba30fd89b84ccef9ebda321d2977ee7f6929fc4c` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark_commands.py` | `b8278b83acf1493e925955430064c6a14de24eddacde99bb94b8f513edb2cb5f` | `b8278b83acf1493e925955430064c6a14de24eddacde99bb94b8f513edb2cb5f` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark_protocol.py` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | **MATCH** |
| `src/ainerzero/v9/teachers/da3_controlled.py` | `25874199f496647ca2960b6204906c910a42b06adfed77172d1eb8a6a082baeb` | `25874199f496647ca2960b6204906c910a42b06adfed77172d1eb8a6a082baeb` | **MATCH** |
| `tests/test_teacher_da3_controlled.py` | `8e288b80ce5ea3d03d44d259a1e29a7d170a2030e35813c071f6c8ef18e81326` | `8e288b80ce5ea3d03d44d259a1e29a7d170a2030e35813c071f6c8ef18e81326` | **MATCH** |

---

## 二、独立 CPU Fixtures 与关键机制复核

复核代码独立构建在 [independent_test.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-T26/independent_test.py)，不导入作者自测文件，运行在隔离的临时目录环境中：

1. **零副作用 Inspect 模式**：
   - 验证 `inspect_da3_benchmark` 执行过程 `side_effects` 严格为 `{lock_acquired: False, ledger_written: False, models_loaded: 0}`；
   - 临时 DB 文件与锁文件均未被触碰或生成；内存中严格未加载 `torch`/`mlx`。
2. **中央 RunStore T4 与 T6 账本隔离**：
   - 在同一个 RunStore 实例中分别注入 T4（300.0s）与 T6（250.0s）保留任务；
   - `calculate_cumulative_reserved_seconds` 仅统计 T4 记录（300.0s，排除 T6）；
   - `calculate_t6_cumulative_reserved_seconds` 仅统计 T6 记录（250.0s，排除 T4）；
   - 证明 T4 的 1800s 预算与 T6 的 1200s 预算彻底物理隔离，互不混淆、不可借用。
3. **前置门禁拦截顺序与错误码**：
   - 非白名单模型（如 `da3-huge`）：立即抛出 `BenchmarkRefusalError`；
   - 视图超配额（`views = 65 > 64`）：抛出 `BenchmarkResourceRefused`，退出码 2；
   - 单次预算超标（`wall_budget_seconds = 1200.1 > 1200.0`）：抛出 `BenchmarkBudgetRefused`，退出码 5；
   - 缺失 `RESEARCH_LOG.md` 批准段落：抛出 `BenchmarkApprovalRefused`，退出码 3；
   - 批准段落存在但缺失统筹冻结统计协议：抛出 `BenchmarkApprovalRefused`，退出码 3。
4. **共享工作锁（m0-worker.lock）互斥性**：
   - 外部通过 `fcntl.flock(LOCK_EX | LOCK_NB)` 占用锁时，`worker_lock` 正确抛出 `WorkerLockBusy`，CLI 映射退出码 4。
5. **原子预留、失败不退款与累计 1200s 硬约束**：
   - 注入模拟执行异常的适配器，Run 状态转换为 `failed`，但已消耗/保留的 400.0s 活跃秒数保留在 RunStore 中，后续不可退款；
   - 再次追加执行 400.0s 成功后，累计记录精确累加至 800.0s；
   - 尝试发起 500.0s 请求（累计将达 1300.0s > 1200.0s），被累计预算门禁精确拒绝（退出码 5）。
6. **父进程监督与子进程组清理**：
   - 独立验证 `start_new_session=True` 子进程组生命周期，父进程触发 `os.killpg(pgid, signal.SIGTERM)` 能彻底回收子进程组，无孤儿进程残留。
7. **真实 CLI 子进程调用**：
   - `ainerzero teacher-da3 --mode inspect` -> rc=0；
   - `ainerzero teacher-benchmark --teacher t6 --mode inspect` -> rc=0；
   - `ainerzero teacher-da3 --mode run`（无批准）-> rc=3；
   - `ainerzero teacher-da3 --mode run --views 100` -> rc=2；
   - `ainerzero teacher-da3 --mode run --wall-budget-seconds 2000` -> rc=5。

---

## 三、四组源码单区域变异对照（Mutation Controls）

在独立复核脚本中构建了 4 组源码单区域变异对照组，每组均严格验证「合法双绿 / 目标坏输入基线红变异绿 / 无关坏输入双红」：

| 变异对照组 | 目标区域 | Case A 合法输入 (双绿) | Case B 目标坏输入 (基线红/变异绿) | Case C 无关坏输入 (双红) | 敏感性裁定 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Control 1: 审批与统计协议门** | `verify_t6_approval_and_protocol` | 合法批准+完整统计协议：基线 GREEN (True) / 变异 GREEN (True) | 仅有批准字样缺统计协议：基线 RED (False) / 变异放行 GREEN (True) | 文件不存在：基线 RED (Refused) / 变异 RED (Refused) | **SENSITIVE_VALID** |
| **Control 2: 视图配额门 (上限 64)** | `check_t6_views_quota` | views=32 (<=64)：基线 GREEN (ok) / 变异 GREEN (ok) | views=96 (>64, <=128)：基线 RED (ResourceRefused) / 变异 GREEN (ok) | views=-10 (<=0)：基线 RED (RefusalError) / 变异 RED (RefusalError) | **SENSITIVE_VALID** |
| **Control 3: 累计预算门 (上限 1200s)** | `execute_guarded_da3_benchmark` | 累计 800s <= 1200s：基线 GREEN (ok) / 变异 GREEN (ok) | 累计 1400s (>1200s, <=2400s)：基线 RED (BudgetRefused) / 变异 GREEN (ok) | 单次请求 1500s > 单次上限 1200s：基线 RED (BudgetRefused) / 变异 RED (BudgetRefused) | **SENSITIVE_VALID** |
| **Control 4: 内存资源保护门 (RSS 8.0 GiB)** | `check_t6_resource_limits` | RSS=4.0 GiB <= 8.0 GiB：基线 GREEN (ok) / 变异 GREEN (ok) | RSS=12.0 GiB (>8.0 GiB, <=64.0 GiB)：基线 RED (ResourceRefused) / 变异 GREEN (ok) | RSS=100.0 GiB > 64.0 GiB：基线 RED (ResourceRefused) / 变异 RED (ResourceRefused) | **SENSITIVE_VALID** |

---

## 四、未验证项与风险披露

1. **纯 CPU 工程复核结论**：
   - 本卡确认 T26 的 CLI 路由、RunStore 预留、预算门禁、互斥锁机制与进程监督完全就绪且逻辑严密。
   - **本复核不构成真实 T6 DA3 模型运行授权**。
2. **生产环境零变动**：
   - 生产数据库 `artifacts/v9/teachers/benchmark/runs.db` 与生产锁文件 `artifacts/locks/m0-worker.lock` 全程保持零占用与零污染。
3. **真实模型执行前置要求**：
   - 真实启动 DA3-Small / DA3-Base 标定推理前，统筹者须在 `RESEARCH_LOG.md` 登记正式批准段落，并提供经冻结校验的统计协议 JSON 文件；
   - 真实执行必须通过隔离虚拟环境 `.venv-t6` 并由主 CLI 监督进程组 RSS 与预算消耗。

---

## 五、复核裁定

**裁定结论：ACCEPTED（CPU工程与受控接入通过）**
所有 6 项源码 SHA-256 精确一致，9 项独立测试全绿，4 组变异对照充分展现门禁敏感性与严密性。
