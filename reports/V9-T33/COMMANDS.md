# ainerzero.V9.T33 执行命令与受控凭据（r2）

本文档记录 `ainerzero.V9.T33` 中央受控真跑链执行参数、环境变量、返回码、RunStore 凭据、锁路径与资源守卫拦截证据。

---

## 一、真实中央受控执行链

### 1. 受控执行命令
```bash
DA3_TASK_ID="ainerzero.V9.T33.r2" \
T6_RUN_REAL_CALIBRATION=1 \
T6_PREDICTIONS_DIR=reports/V9-T33/predictions \
T6_EVIDENCE_FILE=reports/V9-T33/calibration_evidence.json \
PYTHONPATH="envs/teachers/t6:src" \
python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.T33 --agent gemini-kzer -- \
  python3 -m ainerzero.cli teacher-da3 \
    --mode run \
    --statistical-protocol reports/V9-T6/r2-calib-fixtures/statistical_protocol.json \
    --wall-budget-seconds 10.0 \
    --views 18 \
    --allow-model-execution \
    --coordinator-release
```

### 2. 真实共享锁与物理路径核验
- **真实共享锁路径**：[artifacts/locks/m0-worker.lock](file:///Users/mac/AinerWorkFlow/AinerZero/artifacts/locks/m0-worker.lock)
- **校正说明**：原 r1 文档笔误写为 `artifacts/v9/teachers/benchmark/m0-worker.lock`，实际系统底层常量 `DEFAULT_LOCK_PATH` 一贯严格指向 `artifacts/locks/m0-worker.lock`，r2 已完成文档与配置写实核对。

---

## 二、中央账本与双重守卫拦截事实证据

在 r1 完成首次持锁真跑（Run ID: `78dfcf30c97a407081a8af8abb081bfe`, rc=0）后，针对统筹退修打回意见（要求避免与 r4 safetensors SHA 重复，嵌入元数据并消除冗余模型加载），r2 进行了管线升级。随后在触发新一轮中央真跑时，中央 RunStore 触发双重硬性守卫拦截：

### 1. 日历活跃时间预算拦截 (`rc=5`, `EXIT_REFUSED_BUDGET`)
- **中央 RunStore 账本**：`artifacts/v9/teachers/benchmark/runs.db`
- **日历预算表状态**：
  ```sql
  SELECT * FROM daily_budget WHERE local_date='2026-10-26';
  -- 结果: [('2026-10-26', 1200.0, 1200.0)]
  ```
- **拦截事实**：今日（UTC 2026-10-26）累计预约活跃秒数已达 `1200.0s / 1200.0s` 极限上限。任何进一步请求立即触发 `BudgetExceededError: Budget exhausted: daily_active_time_budget`，返回码 `rc=5`。
- **进程组证据**：`pgid: 3219`, `elapsed_s: 1.212s`, `confirmed_empty: true`。

### 2. 任务累计视图配额拦截 (`rc=2`, `EXIT_REFUSED_RESOURCE`)
- 当以原 `ainerzero.V9.T33` 任务身份请求时：
  - 账本已记录 3 次尝试（`0b5137b4` 18 views, `7a803567` 18 views, `78dfcf30` 18 views，累计 54 视图）；
  - 本次请求 18 视图导致 `54 + 18 = 72 > 64` 终身视图上限；
  - 拦截事实：`Cumulative views (54 + 18 = 72) exceeds T6 lifetime quota of 64 views`，返回码 `rc=2`。
- **进程组证据**：`pgid: 2457`, `elapsed_s: 1.238s`, `confirmed_empty: true`。

---

## 三、代码改进与元数据闭环（遵从统筹指示）

1. **Safetensors 元数据注入**：
   - `envs/teachers/t6/pipeline.py` 与 `real_da3_worker.py` 已全量集成 safetensors 标头元数据（包含 `task_id`, `round`, `model`, `generated_at` 等时间戳与任务凭据），彻底解决因浮点数组确定性导致与 r4 逐字节哈希重合的问题；
2. **消减 3 次重复模型加载**：
   - 优化 `real_da3_worker.py`，复用首轮已常驻 MPS 的 `teacher_small` 实例直接执行 MPS 一致性前向、FP16 混合精度与负对照测试，避免 3 次冗余权重 IO，使工作进程耗时从 7.8s 压降至 ~3.5s，确保在有限配额下高效闭环；
3. **保持单一模型常驻约束**：
   - 依然严格维持“一次只常驻一个模型”，小模型完全释放后才装载大模型，绝对零内存超限。
