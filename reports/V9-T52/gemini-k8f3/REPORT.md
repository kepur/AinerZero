# ainerzero.V9.T52 任务报告：DA3 配额全线累计记账与 sitecustomize 任务 ID 改写退役

## 1. 任务基本信息
- **任务编号**: `ainerzero.V9.T52`
- **任务名称**: 【L2·gemini·代码】DA3 配额全线累计（不分 task）+ 退役 sitecustomize 的任务 ID 改写（零模型零账本写入）
- **执行 Agent**: `gemini-k8f3` (Tier 2 执行者)
- **执行时间**: 2026-10-28 / 2026-10-29
- **工作目录**: `/Users/mac/AinerWorkFlow/AinerZero`
- **变更文件范围**:
  - `src/ainerzero/v9/teachers/da3_controlled.py`
  - `src/ainerzero/v9/teachers/benchmark_protocol.py`
  - `envs/teachers/t6/sitecustomize.py`
  - `tests/test_da3_linewide_quota.py`
  - `reports/V9-T52/gemini-k8f3/`
- **零运行与零账本写入约束声明**:
  - 本任务严格执行零模型运行（未加载 PyTorch / MLX 教师模型）；
  - 生产账本 `artifacts/v9/teachers/benchmark/runs.db` 全程只读，前、后实测 SHA256 完全一致（均为 `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`）。

---

## 2. 背景与用户决策落实（E18）

### 2.1 漏洞根因
在历史任务中，`envs/teachers/t6/sitecustomize.py` 会读取环境变量 `DA3_TASK_ID`，并将 `T6_TASK_ID` 动态改写为 `ainerzero.V9.T33`。在原 `da3_controlled.py:query_t6_ledger_read_only` 中，账本查询硬编码了 `if cfg.get("task") == T6_TASK_ID:`，导致中央台账被按任务 ID 人为割裂为独立子池：
- `ainerzero.V9.T6`：81 视 / 1170.0 s
- `ainerzero.V9.T33`：82 视 / 140.0 s
- `ainerzero.V9.T33.r2`：36 视 / 10.0 s
恶意或异常调用只需更换任务 ID（如指定 `DA3_TASK_ID="ainerzero.V9.T_bypass"`），累计配额计数器即从 0 重新起算，构成逃逸漏洞。

### 2.2 用户决策（2026-10-28 E18）
用户裁定：「Whole line, 249/1440」：
1. DA3 配额按**全线合计记账**：中央 RunStore 中所有 DA3 标定运行均累计计入，不论其 `task` 字段记录为何；
2. 彻底退役 `sitecustomize.py` 动态改写任务 ID 的逻辑；
3. 全线历史已消耗基准：**199 视 / 1320.0 s**。

---

## 3. 核心代码变更实现

### 3.1 全线记账判定与提取 (`da3_controlled.py`)
在 `src/ainerzero/v9/teachers/da3_controlled.py` 中引入 `is_da3_ledger_run(cfg)` 函数，并在 `query_t6_ledger_read_only` 中以该函数替代原单任务比较 `cfg.get("task") == T6_TASK_ID`：

```python
def is_da3_ledger_run(cfg: dict[str, Any]) -> bool:
    """Determine whether a RunStore ledger record belongs to the DA3 teacher line.

    Per 2026-10-28 user decision (E18): DA3 quota uses line-wide accounting across all tasks
    in the central RunStore (whatever the task field). Every run whose model is an approved
    DA3 variant, or that belongs to the DA3 benchmark tasks (T6, T33, T33.r2), is accumulated.
    """
    model = cfg.get("model")
    if isinstance(model, str):
        m = model.strip().lower().replace("_", "-")
        if m in ("da3-small", "da3-base", "da3-all", "small", "base", "all") or m.startswith("da3"):
            return True

    task = cfg.get("task")
    if isinstance(task, str):
        t = task.strip()
        if t in ("ainerzero.V9.T6", "ainerzero.V9.T33", "ainerzero.V9.T33.r2") or t.startswith("ainerzero.V9.T6."):
            return True

    return False
```

在 `query_t6_ledger_read_only` 中：
```python
        for config_json, active_seconds in cur.fetchall():
            ...
            if is_da3_ledger_run(cfg):
                total_seconds += float(active_seconds or 0.0)
                total_views += int(cfg.get("views") or 0)
```

实测在生产账本 `artifacts/v9/teachers/benchmark/runs.db` 上运行结果：
- **累积视图**: $81 + 82 + 36 = \mathbf{199}$
- **累积墙钟**: $1170.0 + 140.0 + 10.0 = \mathbf{1320.0\text{ s}}$
- 与 E18 记录及账本真值 100% 吻合。

### 3.2 退役 sitecustomize 任务 ID 改写 (`sitecustomize.py`)
将 `envs/teachers/t6/sitecustomize.py` 内部所有基于 `DA3_TASK_ID` 及 `T33_DAILY_OVERRIDE_SECONDS` 的猴子补丁逻辑全部删除并标记退役，保留注释声明：
```python
"""Site customization for T6 DA3 teacher environment (retired).

Task ID rebinding and per-task budget splitting were retired per user decision on 2026-10-28 (E18):
DA3 quota is accounted line-wide across all tasks in the central RunStore ledger,
and T6_TASK_ID is not overridden by sitecustomize.
"""
# Retired: no task ID rewriting or monkeypatching of benchmark protocol constants.
```

### 3.3 协议规范注释对齐 (`benchmark_protocol.py`)
在 `src/ainerzero/v9/teachers/benchmark_protocol.py` 中更新规范注释，明确 `T6_TASK_ID = "ainerzero.V9.T6"` 为标定线统一任务身份，全线配额不论子任务统一累计。

---

## 4. 自动化测试与承重对照验证

新写专用测试套件 `tests/test_da3_linewide_quota.py`，覆盖 6 项核心用例：

1. **`test_is_da3_ledger_run_classification` (PASS)**:
   - 验证所有 DA3 模型变体（`da3-small`、`da3-base`、`da3-all`、大小写及下划线）无论附加何种任务 ID 均判为 True；
   - 验证非 DA3 任务及模型（如 `T4` V-JEPA、`T10` SAM 2.1、Tapir 等）严格判为 False。
2. **`test_linewide_aggregation_across_different_tasks` (PASS)**:
   - 构造混杂 `T6` (81视/1170s)、`T33` (82视/140s)、`T33.r2` (36视/10s) 及 `T4` (100视/1500s) 的隔离 RunStore；
   - 验证全线提取结果精确等于 199 视、1320.0 s，且 T4 非 DA3 记录被严格隔离未污染。
3. **`test_adversary_task_id_cannot_reset_or_evade_linewide_quota` (PASS)**:
   - 模拟对抗者构造全新任务 ID `ainerzero.V9.T99_bypass`；
   - 验证其消耗的 50 视与 100s 仍被全线合并计入（总计 131 视 / 1270s），无法重置计数器。
4. **`test_sitecustomize_retirement_no_rebinding` (PASS)**:
   - 模拟注入 `DA3_TASK_ID` 环境变量执行 `sitecustomize.py`；
   - 验证 `bp.T6_TASK_ID` 与 `dc.T6_TASK_ID` 均不受影响，恒保持 `"ainerzero.V9.T6"`。
5. **`test_dismantled_guard_load_bearing_control` (拆守卫承重对照，PASS)**:
   - **完好守卫（GREEN）**: 全线感知 199 视 / 1320s；
   - **阉割对照（RED/漏洞复现）**: 仅做 `cfg.get("task") == T6_TASK_ID` 单任务比较，仅看到 81 视 / 1170s，遗漏 T33 的 118 视与 150s；
   - 证明全线记账守卫具备实质承重能力，非冗余摆设。
6. **`test_linewide_budget_refusal_end_to_end` (PASS)**:
   - 端到端验证当历史 T33 运行消耗 1150s 时，新任务请求 100s 触发全线预算超限（$1150 + 100 = 1250 > 1200$s），被前置门禁坚决拒绝（`BenchmarkBudgetRefused`）。

### 全量回归测试输出
- 运行指令: `.venv/bin/pytest tests/test_teacher_da3_controlled.py tests/test_da3_calibration_runner.py tests/test_da3_views_82.py tests/test_da3_supervision.py tests/test_da3_linewide_quota.py tests/v9/teachers/`
- 结果: **118 passed in 93.26s (0:01:33)**，原有 112 项测试全部无损通过，无任何回归。

---

## 5. 生产账本只读审计证实

生产账本路径: `/Users/mac/AinerWorkFlow/AinerZero/artifacts/v9/teachers/benchmark/runs.db`
- 执行前 SHA256: `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`
- 执行后 SHA256: `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`
- 状态: **严格逐字节一致，零改动**。

---

## 6. 交付物清单

- 代码实现:
  - `src/ainerzero/v9/teachers/da3_controlled.py`
  - `src/ainerzero/v9/teachers/benchmark_protocol.py`
  - `envs/teachers/t6/sitecustomize.py`
- 测试套件:
  - `tests/test_da3_linewide_quota.py`
- 验收报告:
  - `reports/V9-T52/gemini-k8f3/REPORT.md`
  - `reports/V9-T52/gemini-k8f3/metrics.json`
  - `reports/V9-T52/gemini-k8f3/SHA256SUMS.txt`
