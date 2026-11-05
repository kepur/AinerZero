# ainerzero.V9.T26 T6 DA3 接入既有 CLI / 中央 RunStore 及独立预算监督报告

- **任务 ID**：`ainerzero.V9.T26`
- **任务标题**：【CPU实现】T6 DA3接入既有CLI/中央RunStore及独立预算监督
- **执行者**：`gemini-kzer`
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：implement · GPU：否（纯 CPU 工程任务）
- **依据与约束**：
  - 用户 AGENTS 工作规则：所有真实模型工作复用现有 CLI、共享锁、中央 RunStore 和预算/资源守卫。
  - 本卡只补 CPU 工程，不执行模型、不写生产台账、不扩上限。
  - T4 账本/限制维持原样，不得借用 T4 1800s/600s 账或修改原 T4 冻结模型/审批。
  - 真实执行模型/标定仍在 T6，入口卡只交 CPU 工程候选，需经不同作者 T27 复核后方可考虑 T6 真实运行。
- **文件变更范围（完全合规，零溢出）**：
  - `src/ainerzero/cli.py`
  - `src/ainerzero/v9/teachers/benchmark.py`
  - `src/ainerzero/v9/teachers/benchmark_commands.py`
  - `src/ainerzero/v9/teachers/benchmark_protocol.py`
  - `src/ainerzero/v9/teachers/da3_controlled.py`
  - `tests/test_teacher_da3_controlled.py`
  - `reports/V9-T26/`

---

## 一、架构对齐与 T4 / T6 任务严格隔离

依据任务说明与 `reports/V9-T6/r3/CONTROLLED-ENTRY-TASK.md` 要求：
1. **任务身份独立**：
   - T6 使用中央 RunStore 独立身份 `task == "ainerzero.V9.T6"` 进行账本登记与过滤，与 T4（`ainerzero.V9.T4`）彻底分离。
   - 在 `calculate_t6_cumulative_reserved_seconds` 中，仅汇总 `task == "ainerzero.V9.T6"` 的保留活跃时间；同时在 T4 的 `calculate_cumulative_reserved_seconds` 中排除 T6 任务，保证二者预算互不混淆、互不借用、互不超订。
2. **CLI 双路由受控入口**：
   - 统一入口 `ainerzero teacher-benchmark`：增加 `--teacher {t4,t6,auto}`、`--views`、`--statistical-protocol` 参数；当指定 `--teacher t6` 或模型为 `da3-small` / `da3-base` / `da3-all` 时自动路由至 DA3 受控分支。
   - 独立便捷入口 `ainerzero teacher-da3`：专用于 T6 DA3 教师基准受控调用，完全对齐既有 CLI 调度习惯。
   - T4 既有命令及参数完全保持向前兼容，原 T4 测试套件（9/9）全部保持 100% 通过。

---

## 二、预算上限、资源守卫与白名单约束

T6 按照 params v1 登记要求实现严格收紧的工程限制：
1. **墙钟预算**：
   - 保守累计上限：**$\le 1200.0$ 秒**（20 分钟），严禁借用 T4 1800s 预算。
   - 单次运行上限：**$\le 1200.0$ 秒**，单次申请越界或累计越界立即触发 `BenchmarkBudgetRefused`（退出码 5）。
2. **内存资源线**：
   - 进程 RSS 保护上限收紧至 **$\le 8.0$ GiB**（`T6_MAX_PROCESS_RSS_GIB = 8.0`），越界立即触发 `BenchmarkResourceRefused`（退出码 2）。
3. **视图配额（Views Quota）**：
   - 同次派生作业共享视图配额：**$\le 64$ 视图**（`T6_MAX_VIEWS = 64`），请求超过 64 视图拒绝进入（退出码 2）。
4. **模型白名单（Strict Whitelist）**：
   - 仅允许 `DA3-SMALL` 与 `DA3-BASE`（及 `da3-all` 批处理）；
   - 请求非白名单模型（如 `da3-large`、`vit-giant` 等）在进入任何锁或账本前立即拒绝（退出码 1）。
5. **权重完整性审计**：
   - 严格比对已下载权重的文件大小与 SHA256 校验和（DA3-Small: 137,248,940 B / SHA `364492e3...`；DA3-Base: 541,518,028 B / SHA `e01067dc...`）。

---

## 三、双模式验证：只读检查（inspect）与受控运行（run）

详见 [inspect_stdout.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T26/inspect_stdout.json) 与 [run_stdout.json](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T26/run_stdout.json)。

### 1. 只读检查模式（inspect）
- **零副作用保证**：零模型导入、零排他锁争用、零 RunStore 生产台账写入。
- **缺项如实报告**：在当前仓库运行 `inspect` 时，明确诊断并报告缺少审批行与统计协议：
  ```json
  "missing_items": [
    "T6 approval section with '批准 T6' not registered in RESEARCH_LOG.md",
    "Frozen statistical evaluation protocol and paired calibration inputs not registered by coordinator"
  ]
  ```
- 返回状态码 **0**，`can_run: false`。

### 2. 受控运行模式（run）
- **全前置校验**：在任何模型 import 或执行之前，严格校验授权行与统计协议登记。
- **真机防御生效**：当前仓库中统筹尚未在 `RESEARCH_LOG.md` 登记 T6 批准与配对真值标定统计协议，直接执行 `run` 时真实验证到安全拒绝：
  - 退出码：**3**（`EXIT_REFUSED_APPROVAL`）
  - 错误信息：`T6 DA3 benchmark refused: approval or statistical protocol missing`
  - 拒绝假借授权：严格遵从“不替统筹编写已批准”原则。

---

## 四、中央 RunStore 不可退款预留与重入安全

1. **先预留后工作**：
   - 在独占获取 `artifacts/locks/m0-worker.lock` 后，先在中央 RunStore 中完成状态转换 `created` $\rightarrow$ `initializing` $\rightarrow$ `validating`，并调用 `store.consume(run_id, active_seconds=budget)` 扣除本次申请预算。
2. **失败与重入不退款（Non-refundable Re-entry）**：
   - 单测验证：首个任务消费 700s 成功；后续任务消费 400s 并在执行中抛出异常失败（状态置为 `failed`）；
   - RunStore 中累计消耗维持 1100s 不扣减；后续再次请求 200s 时（$1100 + 200 = 1300 > 1200$），正确被拒（`BenchmarkBudgetRefused`，退出码 5）。
3. **互斥锁争用保护**：
   - 锁被持有时，竞争进程非阻塞立即返回，给出退出码 **4**（`EXIT_LOCK_BUSY`），杜绝死锁与重入破坏。

---

## 五、进程组监督与受控清空

- 父进程通过设置 `start_new_session=True` 或独立进程组监督自有子进程。
- 当子进程组发生超时或内存峰值越界（RSS > 8.0 GiB）时，父进程通过 `os.killpg(pgid, signal.SIGTERM/SIGKILL)` 精确清空自有子进程组，不影响用户系统其他服务与主流程。
- 测试验证进程终止后无僵尸进程残留。

---

## 六、测试套件与变异对照证据

测试套件位于 [tests/test_teacher_da3_controlled.py](file:///Users/mac/AinerWorkFlow/AinerZero/tests/test_teacher_da3_controlled.py)。
测试执行日志见 [test_suite.log](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-T26/test_suite.log)。

### 1. 单测结果汇总（12/12 全部通过）
1. `test_inspect_zero_side_effects`：验证 inspect 零锁、零 DB 写入、零模型加载与缺项报告（PASSED）
2. `test_model_whitelist_enforcement`：验证非法模型被严格拦截（PASSED）
3. `test_views_quota_gate`：验证 64 视图配额硬约束（PASSED）
4. `test_run_mode_refuses_when_approval_or_protocol_missing`：验证无审批时退出码 3 拒绝（PASSED）
5. `test_per_run_budget_gate`：验证单次运行 1200s 预算限制（PASSED）
6. `test_cumulative_budget_and_non_refundable_reservation`：验证累计 1200s 与失败不退款（PASSED）
7. `test_t4_and_t6_runstore_task_segregation`：验证 T4/T6 在同一 DB 中任务账目完全隔离（PASSED）
8. `test_worker_lock_mutual_exclusion`：验证竞争锁立即返回退出码 4（PASSED）
9. `test_process_group_termination_and_cleanup`：验证进程组越界清理机制（PASSED）
10. `test_cli_subprocess_inspect`：实际 CLI 子进程执行 inspect（rc=0）（PASSED）
11. `test_cli_subprocess_run_refused`：实际 CLI 子进程执行 run 触发安全拒绝（rc=3）（PASSED）
12. `test_four_source_mutation_controls`：源码单区域变异对照（PASSED）

### 2. 源码单区域变异对照（Four Mutation Controls）
- **变异 1（审批门变异）**：正常状态对缺失审批日志拒绝；变异注入放行空日志，单测成功检出基准敏感性。
- **变异 2（视图配额变异）**：正常状态 65 视图触发 `BenchmarkResourceRefused`；变异放宽至 128 视图时通过，单测敏感有效。
- **变异 3（累计预算变异）**：正常状态 1300s 累计被拒；变异放宽至 2400s 时通过，敏感性确认。
- **变异 4（内存保护变异）**：正常状态 9.0 GiB RSS 被拒（上限 8.0 GiB）；变异放宽至 64.0 GiB 时通过，敏感性确认。

---

## 七、源码文件哈希清单与未验证项披露

### 1. 核心源码 SHA256 清单
```
src/ainerzero/cli.py: aa1e42d6d426318db95be28068232859027d567541fd31dabf88cd72ae81db2b
src/ainerzero/v9/teachers/benchmark.py: 8d64e8865f1bea36216e31dbba30fd89b84ccef9ebda321d2977ee7f6929fc4c
src/ainerzero/v9/teachers/benchmark_commands.py: b8278b83acf1493e925955430064c6a14de24eddacde99bb94b8f513edb2cb5f
src/ainerzero/v9/teachers/benchmark_protocol.py: 6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4
src/ainerzero/v9/teachers/da3_controlled.py: 25874199f496647ca2960b6204906c910a42b06adfed77172d1eb8a6a082baeb
tests/test_teacher_da3_controlled.py: 8e288b80ce5ea3d03d44d259a1e29a7d170a2030e35813c071f6c8ef18e81326
```

### 2. 未验证项与下游前置依赖披露
1. **本任务为纯 CPU 工程实现**：未在此卡启动 DA3/MPS/MLX 或 Blender 渲染；
2. **生产台账未写入**：测试均在独立隔离临时库及路径中完成，生产 RunStore 保持零变动；
3. **真实 T6 运行前置条件**：须由统筹在 `RESEARCH_LOG.md` 补齐明确的 T6 批准段落与冻结统计协议，并通过不同作者独立复核卡（T27）验收后方可发布执行。
