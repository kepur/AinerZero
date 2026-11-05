# E1 方案 A 实现报告（ainerzero.V9.P104）

- **任务**：`ainerzero.V9.P104`【L2·gemini/claude·代码】E1 方案 A：实验日历窗口 72 h 与 5 h 实际用时分开（新登记 r1，总上限/防重复跨 r0+r1）
- **执行者**：`gemini-k8m2`（二级执行 agent）
- **时间**：2026-11-03
- **状态**：全部完成，测试通过，坏对照全红，生产副本演练完全吻合

---

## 一、改动摘要

依据 `RESEARCH_LOG.md` 的 `R20261103-E1-calendar-window-stop`（停滞原因）与 `R20261103-E1-A-ruling`（用户裁定），在严格遵守文件边界（仅限指定 4 个源文件、tests 与 reports/V9-E1-A1/）的前提下，实现方案 A：
1. **解耦实验级日历窗口与累计实际用时**：
   - 实验级日历窗口设为 72 h（`experiment_calendar_window_seconds = 259200.0`），写入 `BUDGET_CAPS`；
   - `worker.get_experiment_manifest()` 中 `experiment_budget.max_wall_seconds` 改取该日历窗口，以允许各族格之间存在空档；
   - 运行级单次上限保持 18000.0 s 不变。
2. **谱系跨代合并约束**：
   - `spec.py` 新登记 `EXPERIMENT_ID = "e1-phase2-20261029-r1"`；
   - `spec.py` 声明 `LEDGER_EXPERIMENT_IDS: tuple[str, ...] = ("e1-phase2-20261029-r0", "e1-phase2-20261029-r1")`，并增加模块级断言 `LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID`；
   - `commands._check_phase_budget_ceiling` 在 SQLite 中通过参数化占位符 `WHERE experiment_id IN (?, ?)` 聚合谱系所有实验的实际用时与预留，确保 5 h（18000.0 s）绝对总上限对跨代总和生效；
   - `worker.check_cell_already_completed` 同样跨谱系参数化查询，防止 r0 已跑的 `generate-data` 与 P 族格在 r1 下重复执行。
3. **预登记校验增强**：
   - `prereg.build_draft()` 注入 `"ledger_experiment_ids": list(spec.LEDGER_EXPERIMENT_IDS)`；
   - `prereg.validate()` 增加谱系完全一致性、末项等于 `experiment_id`、以及 `experiment_calendar_window_seconds` 存在、正数且 `>= phase_total_wall_ceiling_seconds` 的校验。

---

## 二、4 个源文件 Unified Diff（对 `reports/V9-E1-A1/pre/`）

### 1. `src/ainerzero/v9/experiments/e1/spec.py`
```diff
--- reports/V9-E1-A1/pre/spec.py	2026-11-03 13:25:28
+++ src/ainerzero/v9/experiments/e1/spec.py	2026-11-03 13:39:09
@@ -45,7 +45,12 @@
 # --- Spec & Experiment Identity ---
 SPEC_NAME = "e1-phase2-v1"
 TASK_ID = "ainerzero.V9.P71"
-EXPERIMENT_ID = "e1-phase2-20261029-r0"
+EXPERIMENT_ID = "e1-phase2-20261029-r1"
+LEDGER_EXPERIMENT_IDS: tuple[str, ...] = (
+    "e1-phase2-20261029-r0",
+    "e1-phase2-20261029-r1",
+)
+assert LEDGER_EXPERIMENT_IDS[-1] == EXPERIMENT_ID
 
 PREREG_DRAFT_PATH = "reports/V9-P48/PREREG_DRAFT_r4_candidate.md"
 PREREG_DRAFT_SHA256 = (
@@ -295,6 +300,7 @@
     "dev_eval_total_max_seconds": 1800.0,  # 26 cells total <= 30 min
     "final_eval_max_seconds": 1800.0,  # <= 30 min
     "phase_total_wall_ceiling_seconds": 18000.0,  # 5.0 h total wall
+    "experiment_calendar_window_seconds": 259200.0,  # 72.0 h calendar window
 }
 
 RESOURCE_LIMITS: dict[str, float] = {
```

### 2. `src/ainerzero/v9/experiments/e1/worker.py`
```diff
--- reports/V9-E1-A1/pre/worker.py	2026-11-03 13:25:28
+++ src/ainerzero/v9/experiments/e1/worker.py	2026-11-03 13:39:45
@@ -157,9 +157,10 @@
     with ledger_read_snapshot(ledger_path) as store:
         if store is None:
             return False
+        placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
         cursor = store._conn.execute(
-            "SELECT config_json, state FROM runs WHERE experiment_id = ?",
-            (EXPERIMENT_ID,),
+            f"SELECT config_json, state FROM runs WHERE experiment_id IN ({placeholders})",
+            spec.LEDGER_EXPERIMENT_IDS,
         )
         for row in cursor.fetchall():
             state = row["state"]
@@ -183,6 +184,7 @@
 def get_experiment_manifest() -> dict[str, Any]:
     """Construct the immutable experiment manifest for RunStore registration."""
     wall_ceiling = float(spec.BUDGET_CAPS["phase_total_wall_ceiling_seconds"])
+    calendar_window = float(spec.BUDGET_CAPS["experiment_calendar_window_seconds"])
     train_cells = int(spec.BUDGET_CAPS["train_cells_count"])
     max_steps_per_cell = int(spec.DEFAULT_TRAIN_STEPS)
     # Experiment-level optimizer step ceiling derived from spec:
@@ -199,6 +201,7 @@
         "prereg_draft_sha256": spec.PREREG_DRAFT_SHA256,
         "host_anchor": spec.host_anchor(),
         "created_at": datetime.now(timezone.utc).isoformat(),
+        # Run-level default budget: ceiling per run matches total phase compute ceiling (18000s)
         "budget": {
             "max_environment_steps": 10_000_000,
             "max_optimizer_steps": derived_run_optimizer_steps,
@@ -207,12 +210,18 @@
             "max_model_transitions": 0,
             "timezone": TIMEZONE,
         },
+        # Experiment-level budget:
+        # Runtime lifecycle calculates remaining experiment wall seconds as:
+        #   max_wall_seconds - max(time_since_registration, active_seconds)
+        # Therefore experiment_budget.max_wall_seconds functions as a calendar window (72h = 259200s),
+        # allowing idle intervals between cell families, whereas the 5.0h (18000s) active compute
+        # ceiling is aggregated and enforced in commands._check_phase_budget_ceiling across LEDGER_EXPERIMENT_IDS.
         "experiment_budget": {
             "max_model_runs": 100,
             "max_environment_steps": 10_000_000,
             "max_optimizer_steps": derived_experiment_optimizer_steps,
             "max_model_transitions": 1,
-            "max_wall_seconds": wall_ceiling,
+            "max_wall_seconds": calendar_window,
             "max_calibration_seconds": 3600.0,
         },
         "tags": ["v9", "e1", "phase2", "physics", "neurogeometry"],
```

### 3. `src/ainerzero/v9/experiments/e1/commands.py`
```diff
--- reports/V9-E1-A1/pre/commands.py	2026-11-03 13:25:28
+++ src/ainerzero/v9/experiments/e1/commands.py	2026-11-03 13:40:02
@@ -138,9 +138,10 @@
 
     with worker.ledger_read_snapshot(ledger_path) as store:
         if store is not None:
+            placeholders = ", ".join("?" for _ in spec.LEDGER_EXPERIMENT_IDS)
             cursor = store._conn.execute(
-                "SELECT active_seconds, config_json FROM runs WHERE experiment_id = ?",
-                (spec.EXPERIMENT_ID,),
+                f"SELECT active_seconds, config_json FROM runs WHERE experiment_id IN ({placeholders})",
+                spec.LEDGER_EXPERIMENT_IDS,
             )
             for row in cursor.fetchall():
                 val = row["active_seconds"]
```

### 4. `src/ainerzero/v9/experiments/e1/prereg.py`
```diff
--- reports/V9-E1-A1/pre/prereg.py	2026-11-03 13:25:28
+++ src/ainerzero/v9/experiments/e1/prereg.py	2026-11-03 13:40:46
@@ -112,6 +112,7 @@
         "schema": SCHEMA,
         "spec_name": spec.SPEC_NAME,
         "experiment_id": spec.EXPERIMENT_ID,
+        "ledger_experiment_ids": list(spec.LEDGER_EXPERIMENT_IDS),
         "task_id": spec.TASK_ID,
         "prereg_draft_ref": {
             "path": spec.PREREG_DRAFT_PATH,
@@ -202,6 +203,20 @@
             f"Invalid experiment_id: expected {spec.EXPERIMENT_ID}, got {document.get('experiment_id')}"
         )
 
+    # Lineage validation
+    ledger_ids = document.get("ledger_experiment_ids")
+    if not isinstance(ledger_ids, (list, tuple)):
+        raise SpecValidationError("Missing or invalid ledger_experiment_ids list")
+    if tuple(ledger_ids) != spec.LEDGER_EXPERIMENT_IDS:
+        raise SpecValidationError(
+            f"ledger_experiment_ids mismatch: expected {spec.LEDGER_EXPERIMENT_IDS}, got {tuple(ledger_ids)}"
+        )
+    if not ledger_ids or ledger_ids[-1] != document.get("experiment_id"):
+        raise SpecValidationError(
+            f"Last element of ledger_experiment_ids ({ledger_ids[-1] if ledger_ids else None}) "
+            f"must match experiment_id ({document.get('experiment_id')})"
+        )
+
     # Draft reference check
     draft_ref = document.get("prereg_draft_ref")
     if not isinstance(draft_ref, Mapping):
@@ -319,6 +334,7 @@
         "dev_eval_total_max_seconds",
         "final_eval_max_seconds",
         "phase_total_wall_ceiling_seconds",
+        "experiment_calendar_window_seconds",
     )
     for key in required_budget_keys:
         val = budget.get(key)
@@ -331,7 +347,14 @@
     dev_eval = float(budget["dev_eval_total_max_seconds"])
     final_eval = float(budget["final_eval_max_seconds"])
     total_ceiling = float(budget["phase_total_wall_ceiling_seconds"])
+    cal_window = float(budget["experiment_calendar_window_seconds"])
 
+    if cal_window < total_ceiling:
+        raise SpecValidationError(
+            f"experiment_calendar_window_seconds ({cal_window:.1f} s) must be >= "
+            f"phase_total_wall_ceiling_seconds ({total_ceiling:.1f} s)"
+        )
+
     cell_wall = float(budget["train_cell_wall_max_seconds"])
     cell_compute = float(budget["train_cell_compute_max_seconds"])
     duty = float(budget["training_duty_cycle"])
```

---

## 三、修改与新增测试文件 Diff

### 1. `tests/test_e1_prereg.py`
```diff
--- reports/V9-E1-A1/pre/tests/test_e1_prereg.py	2026-11-02 21:49:58
+++ tests/test_e1_prereg.py	2026-11-03 13:41:04
@@ -29,7 +29,8 @@
     """Verify frozen spec constants align with PREREG_DRAFT r4 candidate."""
     assert spec.SPEC_NAME == "e1-phase2-v1"
     assert spec.TASK_ID == "ainerzero.V9.P71"
-    assert spec.EXPERIMENT_ID == "e1-phase2-20261029-r0"
+    assert spec.EXPERIMENT_ID == "e1-phase2-20261029-r1"
+    assert spec.LEDGER_EXPERIMENT_IDS == ("e1-phase2-20261029-r0", "e1-phase2-20261029-r1")
     assert spec.PREREG_DRAFT_PATH == "reports/V9-P48/PREREG_DRAFT_r4_candidate.md"
     assert spec.PREREG_DRAFT_SHA256 == "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"
     assert spec.PREREG_DRAFT_SHA256_PREFIX == "ef7856e7f757"
@@ -87,6 +88,7 @@
     assert caps["dev_eval_total_max_seconds"] == 1800.0
     assert caps["final_eval_max_seconds"] == 1800.0
     assert caps["phase_total_wall_ceiling_seconds"] == 18000.0  # 5 h
+    assert caps["experiment_calendar_window_seconds"] == 259200.0  # 72 h
 
     # Budget components sum equality assertion (3600 + 10800 + 1800 + 1800 == 18000)
     assert (
```

### 2. `tests/test_e1_wiring.py`
```diff
--- reports/V9-E1-A1/pre/tests/test_e1_wiring.py	2026-11-02 12:52:23
+++ tests/test_e1_wiring.py	2026-11-03 13:41:12
@@ -765,7 +765,9 @@
     assert wall_ceiling == 18000.0
     assert manifest["budget"]["max_wall_seconds"] == wall_ceiling
     assert manifest["budget"]["max_daily_active_seconds"] == wall_ceiling
-    assert manifest["experiment_budget"]["max_wall_seconds"] == wall_ceiling
+    assert manifest["experiment_budget"]["max_wall_seconds"] == float(
+        spec.BUDGET_CAPS["experiment_calendar_window_seconds"]
+    )
 
     # 2. Optimizer steps derived from spec with 20% margin
     train_cells = int(spec.BUDGET_CAPS["train_cells_count"])
```

### 3. 新增 `tests/test_e1_calendar_window.py`
包含 (a)–(e) 全部五项针对性测试，全绿（5 passed in 2.22s）。

---

## 四、测试清单与执行结果

1. **测试 (a) 空档不再拒绝** (`test_case_a_gap_does_not_reject`)：
   - 模拟 r0 登记在 t0，写入已完成运行累计 9600 s；
   - 登记 r1 在 t0；假时钟推移 36010 s（> 18000 s）；
   - 在 t0+36010 s 准入 r1 的 `train(6, S, 42)`，准入成功（exit 0，status completed）。
2. **测试 (b) 合并总上限** (`test_case_b_combined_phase_ceiling`)：
   - r0 记 9600 s，r1 填满 7200 s，总计 16800 s；
   - 边界测试：申请 1200 s（恰好 16800 + 1200 == 18000 s），成功准入；
   - 超限测试：在 18000 s 满额后再申请 60 s，准入被拒（exit 2，stage `phase_budget_exceeded`）。
3. **测试 (c) 跨谱系防重复** (`test_case_c_cross_lineage_anti_duplicate`)：
   - r0 已完成的 `generate-data` 与 `train(6, P, 42)` 在 r1 下准入被拒（exit 1，stage `duplicate_execution`）；
   - r0 未执行过的 `train(6, S, 42)` 顺利通过。
4. **测试 (d) prereg 校验** (`test_case_d_prereg_validation_and_subprocess`)：
   - 缺 `ledger_experiment_ids`、顺序颠倒、末项非当前 id、日历窗口缺失、日历窗口小于 18000 s，各自准确抛出 `SpecValidationError`；
   - 使用 `.venv/bin/python -I` 子进程（完全独立无 conftest 猴子补丁）验证 `validate(build_draft())` 通过。
5. **测试 (e) 全程演练** (`test_case_e_full_schedule_rehearsal_with_7_5h_gap`)：
   - 完整双族演练：数据生成 → P 族 9 格训练 → **插入 7.5 h（27,000 s）空档** → S 族 9 格训练 → dev 26 格评测 → final 评测，全程成功。

---

## 五、生产账本副本上的演练（`reports/V9-E1-A1/rehearse_on_copy.py`）

- **脚本路径**：`reports/V9-E1-A1/rehearse_on_copy.py`
- **输出文件**：`reports/V9-E1-A1/rehearsal.json`
- **执行命令**：`.venv/bin/python reports/V9-E1-A1/rehearse_on_copy.py`
- **输出结果**：
```
Production ledger SHA256 before copy: 508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244
Production ledger SHA256 after copy:  508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244
Initial on copy: ok=True, consumed=9600.0s, ceiling=18000.0s
Consumed after S-family (9 cells): 15900.0s (expected 15900.0)
Consumed after dev (26 cells): 17640.0s (expected 17640.0)
Excess cell admission result: code=2, stage=phase_budget_exceeded
Rehearsal successfully written to /Users/mac/AinerWorkFlow/AinerZero/reports/V9-E1-A1/rehearsal.json
```
- **核心数据**：
  - 生产账本拷贝前后 SHA 严格一致（`508ae242dbe6dd524573be52720052ae1d95e90c6c6b7c7206039b8eb18ef244`）；
  - r0 初始已消耗：9600.0 s；数据生成与 P 族 9 格标记为已完成，S 族 9 格标记为未完成；
  - 准入 S 族 9 格（⑥ 1200 s，②③ 450 s）：增加 6300 s，累计 15900.0 s；
  - 准入 dev 26 格（⑥ 150 s，②③ 40 s，非训练臂 45 s）：增加 1740 s，累计 17640.0 s；
  - 再尝试申请一格 1200 s：被中央守卫以 `phase_budget_exceeded` 拒绝（exit 2），完全符合总上限 18000 s。

---

## 六、变异坏对照表（`reports/V9-E1-A1/run_mutations.py`）

所有变异均在隔离临时工作树中执行，import 路径严格断言为临时副本，测试后以字节级还原并校验 SHA256。

| 变异 ID | 变异操作 | 预期变红项 | 实际退出码 | 结果 |
| :--- | :--- | :--- | :--- | :--- |
| **M1** | `worker.py` 实验级 `max_wall_seconds` 改回 `phase_total_wall_ceiling_seconds` | (a), (e) | (a) code=1, (e) code=1 | **RED（通过）** |
| **M2** | `commands.py` `_check_phase_budget_ceiling` 只查 `spec.EXPERIMENT_ID` | (b) | (b) code=1 | **RED（通过）** |
| **M3** | `worker.py` `check_cell_already_completed` 只查当前 id | (c) | (c) code=1 | **RED（通过）** |
| **M4** | `prereg.py` 删掉 `validate` 里的谱系检查 | (d) | (d) code=1 | **RED（通过）** |
| **M5** | `spec.py` `LEDGER_EXPERIMENT_IDS` 去掉 `r0` | (b), (c) | (b) code=1, (c) code=1 | **RED（通过）** |

---

## 七、全量回归计数（SIG_DFL + execv 前台运行）

- **E1 专属回归测试**（`tests/test_e1_*.py`）：
  - 修改前基线：207 passed in 30.85s
  - 修改后计数：**212 passed in 39.14s**（包含新增的 5 项日历窗口与谱系合并测试）
- **全仓库 pytest 回归测试**：
  - 修改前基线：6 failed, 3657 passed, 5 deselected in 238.21s
  - 修改后计数：**6 failed, 3662 passed, 5 deselected in 307.16s**
  - **增量分析**：净增 +5 passed，失败用例集合完全相同（均为预存无关用例，如 MLX 哨兵与阶段记账测试），全仓 0 回归。

---

## 八、红线与文件封存校验

1. **未修改任何未经授权的文件**：
   - 其余 12 个 E1 实现源文件、`lifecycle.py`、`conftest.py`、`control.sqlite3`、`checkpoints/` 等共计 59 个文件与 `reports/V9-E1-A1/PRE-SEAL.sha256` 逐字逐字节比对，0 差异。
2. **纯 CPU 约束**：
   - 零真实训练、零 GPU / MLX 运算、零模型权重下载、零网络请求。
3. **输出物清单**：
   - `reports/V9-E1-A1/POST-SEAL.sha256`：涵盖全部 16 个源文件、E1 测试套件、运行时与生产资产校验和；
   - `reports/V9-E1-A1/rehearsal.json`：副本演练完整结构化输出；
   - `reports/V9-E1-A1/mutations.json`：5 项变异测试完整记录；
   - `reports/V9-E1-A1/metrics.json`：结构化运行指标；
   - `reports/V9-E1-A1/REPORT.md`：本报告。
