# ainerzero.V9.T31 非作者独立 CPU 复核报告：T30 真实 worker / 父监督 / 只读账本缺陷修复重验

- **任务 ID**：`ainerzero.V9.T31`
- **复核目标**：`ainerzero.V9.T30`（【CPU修复】T26已验收入口缺真实父监督/worker及只读账本缺陷，作者 `antigravity-h4d8`）
- **复核执行者**：`gemini-7a2b`（依统筹指令 notice #625 与 params v1 授权领取）
- **主工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **层级**：二级（执行层）· 类型：verify · GPU：否（纯 CPU 独立复核工程）
- **依据与约束**：`reports/V9-T6/r3/CONTROLLED-ENTRY-TASK.md`、`reports/V9-T30/REPORT.md`、`AGENTS.md`
- **受控编辑范围**：仅修改 `reports/V-V9-T30/`（只读产品代码，不导入作者自测，零生产污染）

---

## 一、交付源码完整性与 SHA-256 确切校验

独立复核程序直接从磁盘逐字节读取 T30 交付的全部 8 个源码与测试文件，计算 SHA-256 并与作者报告比对，**8/8 全部完全匹配，无任何静默变动或偏差**：

| 文件路径 | 原报告 SHA-256 | 独立实测 SHA-256 | 校验结果 |
| :--- | :--- | :--- | :--- |
| `src/ainerzero/cli.py` | `60a6c7f099649212c1fc35ff27cbe74dcb48f3b5cb1d3ad3199ce6020082afc3` | `60a6c7f099649212c1fc35ff27cbe74dcb48f3b5cb1d3ad3199ce6020082afc3` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark.py` | `aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb` | `aa83e7db9fb4a57b7ed20dddff450b67c5c25a9350f2cace23606bd29e97a5eb` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark_commands.py` | `d9a711fca64fa7944fade8f2256079737fdaa3ccf63dec50161614fefe793383` | `d9a711fca64fa7944fade8f2256079737fdaa3ccf63dec50161614fefe793383` | **MATCH** |
| `src/ainerzero/v9/teachers/benchmark_protocol.py` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | `6e27c41cd54bc0977ac7d087f603fd983af1f225d32b3945e7580634f62f1bd4` | **MATCH** |
| `src/ainerzero/v9/teachers/da3_controlled.py` | `93016b3d5e6313db6aa82900cc598db59805ff2c1841da8c30c28646e08c7c18` | `93016b3d5e6313db6aa82900cc598db59805ff2c1841da8c30c28646e08c7c18` | **MATCH** |
| `src/ainerzero/v9/teachers/da3_worker.py` | `7046723dc08b1ac819b6a46e80959889602034fb2fee9f7ff94142cfb103d205` | `7046723dc08b1ac819b6a46e80959889602034fb2fee9f7ff94142cfb103d205` | **MATCH** |
| `tests/test_teacher_da3_controlled.py` | `f8f863a6a1e04cfc0df80f64a5b4aa361a43b3ebca1a14798af821ba40c69ef7` | `f8f863a6a1e04cfc0df80f64a5b4aa361a43b3ebca1a14798af821ba40c69ef7` | **MATCH** |
| `tests/test_da3_supervision.py` | `63b3d92193c605d400f0432a5f52a51f6e2f8ecc243355fbd310c68abd419383` | `63b3d92193c605d400f0432a5f52a51f6e2f8ecc243355fbd310c68abd419383` | **MATCH** |

---

## 二、产品父监督实际路径与关键缺陷修复独立验证

复核套件独立实现于 [independent_test.py](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V-V9-T30/independent_test.py)，不导入作者测试代码，在隔离临时目录中执行集成测试：

1. **真实产品父监督路径集成验证（`run_supervised_da3_worker`）**：
   - **Case 2.1 正常执行**：子进程组通过 `subprocess.Popen(start_new_session=True)` 运行，监督循环正常轮询，完成后通过 `psutil` 验证子进程及子孙进程组彻底为空（`empty_group_proven=True`）。
   - **Case 2.2 墙钟超时硬杀**：设置 0.2s 预算，子进程触发 5.0s 模拟阻塞；父监督循环精确检测到超时，触发 `os.killpg(child_pgid, signal.SIGTERM)`，并在超时后确认整组彻底回收，抛出 `BenchmarkBudgetRefused`（退出码 5），附带 `empty_group_proven=True`。
   - **Case 2.3 进程组 RSS 越界硬杀**：设置 30 MiB 上限，子进程申请并持有 100 MiB 内存；父监督循环精确捕获 RSS 超标，触发 `os.killpg` 回收整组，抛出 `BenchmarkResourceRefused`（退出码 2），附带 `empty_group_proven=True`。
   - **Case 2.4 组长退出但孙进程泄漏检测**：子进程生成后台无限睡眠的孙进程后自行退出；父监督循环检测到非空组（残余孤儿孙进程），触发 `os.killpg` 杀灭孤儿进程，确认整组回收后抛出 `BenchmarkRefusalError`，附带 `empty_group_proven=True`。
2. **预留前前置门禁拦截（0 DB 写入）**：
   - 当无可用真实 worker/adapter 时（如 `worker_action="real_pipeline"` 且 `adapter=None`），系统在第 7 步直接抛出 `BenchmarkRefusalError`，**彻底拦截在 RunStore 账本预留（第 8/9 步）之前**；
   - 实测临时 RunStore 数据库条目数严格为 0，彻底根除了 T26 中遗留 validating 状态的缺陷。
3. **跨作业累计 64 视图硬配额**：
   - 依次提交派生任务：Job 1（30 views，累计 30）、Job 2（30 views，累计 60）；
   - 提交 Job 3（10 views，累计将达 70 views > 64 views 上限）；
   - 系统精确在第 6 步拦截并抛出 `BenchmarkResourceRefused`，有效防止通过切分多作业超额调用。
4. **只读 Inspect 与损坏台账 Fail-Closed**：
   - `inspect_da3_benchmark` 执行使用 URI `file:{path}?mode=ro`，对于不存在的数据库严格不创建新文件，`ledger_written=False`；
   - 对于非 SQLite 或损坏的文件，`query_t6_ledger_read_only` 严格抛出 `BenchmarkRefusalError`（Fail-Closed），坚决不静默回退为 0.0。
5. **CLI 子进程真实退出码**：
   - `teacher-da3 --mode inspect` -> rc=0；
   - `teacher-da3 --mode run`（无批准）-> rc=3；
   - `teacher-da3 --mode run --views 100` -> rc=2；
   - `teacher-da3 --mode run --wall-budget-seconds 2000` -> rc=5。

---

## 三、四组源码单区域变异对照（Mutation Controls）

在独立复核脚本中构建了 4 组完全单区域变异对照组，每组均严格验证「合法双绿 / 目标坏输入基线红变异绿 / 无关坏输入双红」：

| 变异对照组 | 目标源码区域 | Case A 合法输入 (双绿) | Case B 目标坏输入 (基线红/变异绿) | Case C 无关坏输入 (双红) | 敏感性裁定 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Control 1: 超时父监督门** | `run_supervised_da3_worker` 超时检查 | elapsed=0.1s <= 1.0s：基线 GREEN / 变异 GREEN | elapsed=1.5s > 1.0s：基线 RED (BudgetRefused) / 变异放宽 GREEN | budget <= 0：基线 RED (BudgetRefused) / 变异 RED (BudgetRefused) | **SENSITIVE_VALID** |
| **Control 2: 进程组 RSS 门** | `run_supervised_da3_worker` 内存阈值 | RSS=4 GiB <= 8 GiB：基线 GREEN / 变异 GREEN | RSS=12 GiB > 8 GiB：基线 RED (ResourceRefused) / 变异放宽 GREEN | RSS=100 GiB > 64 GiB：基线 RED (ResourceRefused) / 变异 RED (ResourceRefused) | **SENSITIVE_VALID** |
| **Control 3: 预留前 Worker 检查门** | `execute_guarded_da3_benchmark` 第 7 步检查 | 配置有效 adapter：基线 GREEN / 变异 GREEN | adapter 为空且请求 real runner：基线 RED (RefusalError) / 变异放行 GREEN | 非白名单模型 `da3-huge`：基线 RED (RefusalError) / 变异 RED (RefusalError) | **SENSITIVE_VALID** |
| **Control 4: 累计视图配额门** | `check_t6_views_quota` 累计检查 | 累计 30 <= 64：基线 GREEN / 变异 GREEN | 累计 70 > 64：基线 RED (ResourceRefused) / 变异放宽 GREEN | 请求 views=-5 <= 0：基线 RED (RefusalError) / 变异 RED (RefusalError) | **SENSITIVE_VALID** |

---

## 四、未验证项与风险披露

1. **纯 CPU 工程复核结论**：
   - 本卡确认 T30 对 T26 遗留的所有硬缺陷（父监督进程组、预留前拦截、只读 inspect、损坏账本 fail-closed、累计 64 视图）均已彻底修复，真实子进程监督机制严密有效。
   - **本复核不构成真实 T6 DA3 模型运行授权**。
2. **生产环境零变动**：
   - 生产数据库 `artifacts/v9/teachers/benchmark/runs.db` 与生产锁文件 `artifacts/locks/m0-worker.lock` 全程保持零变动与零占用。
3. **真实 T6 恢复前置**：
   - T6 恢复运行需由一级统筹在接力台正式解除 `[阻塞]` 并将状态置为就绪后，方可申请启动。

---

## 五、复核裁定

**裁定结论：ACCEPTED（CPU修复与父监督闭环通过）**
所有 8 项源码 SHA-256 精确一致，7 项独立集成维度全部通过，4 组变异对照充分证明修复的敏锐性与严密性。
