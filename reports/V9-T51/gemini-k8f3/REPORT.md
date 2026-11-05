# 任务交付报告：DA3 视图数与墙钟上限从登记的 T28 提案派生

- **任务编号**：`ainerzero.V9.T51`
- **执行者**：`gemini-k8f3`（二级执行 agent，纯代码任务）
- **日期**：2026-10-28
- **任务目标**：根据用户 2026-10-28 批准的 DA3 配额（视图上限 131、累计墙钟 1290s、单次 120s，零模型零账本），将代码中写死的旧常量重构为**从已登记的 T28 提案动态派生**；Runs.db metadata views override 升级为按日期后缀取最新且校验同日冲突。

---

## 1. 核心设计与改动实现

### 1.1 新增模块 `src/ainerzero/v9/teachers/t28_registration.py`
- **只读检测与回退**：若 `reports/V9-T28/REGISTERED.json` 不存在（或由 `T28_REGISTERED_PATH` 指向不存在的路径），函数安全返回旧冻结默认值：
  - `calibration_views = 18`
  - `cumulative_wall_cap_s = 1200.0`
  - `run_wall_budget_s = None`
  保证登记之前所有旧逻辑与测试行为一字不差。
- **强校验门禁**：若 `REGISTERED.json` 存在：
  - 检查 `proposal_path` 与 `sha256` 必填且非空；
  - 逐字节读取提案文件并计算 SHA256，与登记项不一致时立即抛出 `ValueError("T28 proposal SHA256 mismatch")` 并拒绝；
  - 读取提案 `budget` 结构：
    - `calibration_views = budget.view_accounting.charge_per_complete_run`（必须为正整数）
    - `cumulative_wall_cap_s = budget.cumulative_wall_seconds_max`（必须为正数）
    - `run_wall_budget_s = budget.wall_accounting.approved_run_wall_budget_seconds`（必须为正数）
  - 任何字段缺失、为 `null` 或无效时，一律抛出 `ValueError` 大声失败。

### 1.2 `da3_worker.py` 与 `benchmark_protocol.py` 动态派生与向后兼容
- `da3_worker.py`：
  - 引入 `get_registered_calibration_views()` 动态获取标定视图口径；
  - 提供 `get_calibration_views() -> int`；
  - 实现模块级 `__getattr__("REGISTERED_CALIBRATION_VIEWS")`，保留原变量名访问与兼容旧 import；
  - 真实管线运行及拒绝提示均使用动态获取的口径。
- `benchmark_protocol.py`：
  - 引入 `get_registered_cumulative_wall_cap_s()` 动态获取累计墙钟上限；
  - 提供 `get_t6_max_cumulative_wall_seconds() -> float`；
  - 实现模块级 `__getattr__("T6_MAX_CUMULATIVE_WALL_SECONDS")` 保持向后兼容。

### 1.3 `da3_controlled.py` 单次 120s 上限与动态累计墙钟上限
- **单次墙钟预算门禁**：在 Step 2 添加检查，若已登记的 `run_wall_budget_s` 不为 None（如 120s），且用户请求的 `spec.wall_budget_seconds > run_wall_budget_s`，则直接抛出 `BenchmarkBudgetRefused` 拒绝（Exit 5），杜绝单次超出批准的 120s。
- **累计墙钟上限动态化**：在 `check_da3_benchmark_prerequisites`、Step 6（锁前核验）、Step 10（持锁双重核验与入库配置快照）均改为调用 `get_registered_cumulative_wall_cap_s()`。
- **真实管线标定视图动态核验**：在 Step 6b 视图口径先验门中，对比 `spec.views != get_registered_calibration_views()`，自动对齐登记口径（18 或 50）。

### 1.4 `get_effective_t6_max_views`：日期后缀最新覆盖与同日冲突拒绝
- 扫描 `metadata` 表中所有匹配 `^(t6|t35)_views_override_(\d{8})$` 的键；
- 提取 8 位日期字符串 `YYYYMMDD` 并按日期聚合；
- **同日冲突防护**：同一天内若出现多个覆盖键且指定值不同（例如 131 vs 135），抛出 `BenchmarkRefusalError` 拒绝并报错；
- **取最新日期**：排序日期后取最新一天的覆盖值返回（例如同时存在 20261027 的 82 和 20261028 的 131 时，返回 131）。

---

## 2. 源码改动对比（Unified Diffs）

### 2.1 `src/ainerzero/v9/teachers/benchmark_protocol.py`
```diff
--- reports/V9-T51/gemini-k8f3/before/benchmark_protocol.py
+++ src/ainerzero/v9/teachers/benchmark_protocol.py
@@ -28,7 +28,23 @@
 T6_APPROVAL_SECTION = "R20261026-T6"
 T6_APPROVAL_KEYWORD = "批准 T6"
 T6_APPROVAL_TARGET = "ainerzero.V9.T6"
-T6_MAX_CUMULATIVE_WALL_SECONDS = 1200.0
+# V9.T51: 累计墙钟上限动态从已登记的 T28 提案派生（默认 1200.0）
+from ainerzero.v9.teachers.t28_registration import (
+    get_registered_cumulative_wall_cap_s,
+)
+
+
+def get_t6_max_cumulative_wall_seconds() -> float:
+    """Return effective T6 max cumulative wall seconds (from registered T28 proposal, or default 1200.0)."""
+    return get_registered_cumulative_wall_cap_s()
+
+
+def __getattr__(name: str) -> Any:
+    if name == "T6_MAX_CUMULATIVE_WALL_SECONDS":
+        return get_registered_cumulative_wall_cap_s()
+    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
+
+
 T6_MAX_PER_RUN_WALL_SECONDS = 1200.0
 T6_MAX_RESIDENT_MODELS = 1
 T6_MAX_PROCESS_RSS_GIB = 8.0
```

### 2.2 `src/ainerzero/v9/teachers/da3_worker.py`
```diff
--- reports/V9-T51/gemini-k8f3/before/da3_worker.py
+++ src/ainerzero/v9/teachers/da3_worker.py
@@ -25,10 +25,24 @@
 
 # V9.T42: 统一登记的标定视图口径常量。worker 与中央 execute_guarded 共用同一来源，避免写死魔数与口径错位。
 # V9.T44 (N-1): 删除无人使用的别名 CALIBRATION_VIEWS_REQUIRED，只保留唯一来源 REGISTERED_CALIBRATION_VIEWS。
-REGISTERED_CALIBRATION_VIEWS: int = 18
+# V9.T51: 视图数与标定口径动态从登记的 T28 提案派生（默认 18）。保留 REGISTERED_CALIBRATION_VIEWS 兼容旧 import。
+from ainerzero.v9.teachers.t28_registration import (
+    get_registered_calibration_views,
+)
 
 
+def get_calibration_views() -> int:
+    """Return effective registered calibration views (from T28 proposal or default 18)."""
+    return get_registered_calibration_views()
 
+
+def __getattr__(name: str) -> Any:
+    if name == "REGISTERED_CALIBRATION_VIEWS":
+        return get_registered_calibration_views()
+    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
+
+
+
 def parse_args() -> argparse.Namespace:
     parser = argparse.ArgumentParser(description="T6 DA3 benchmark worker process")
     parser.add_argument("--spec-file", type=Path, required=True, help="Path to DA3 run spec JSON")
@@ -204,9 +218,10 @@
         # When authorized: real model execution via real_da3_worker / pipeline / calibration runner
         views = spec_data.get("views", 0)
         task_id = os.environ.get("DA3_TASK_ID", spec_data.get("task", "ainerzero.V9.T35"))
+        reg_views = get_registered_calibration_views()
 
         runner_executed = False
-        if views == REGISTERED_CALIBRATION_VIEWS and args.allow_model_execution:
+        if views == reg_views and args.allow_model_execution:
             runner_script = repo_root / "src/ainerzero/v9/teachers/da3_calibration_runner.py"
             # 每次运行一个新目录：管线拒绝已存在的输出目录，而已交付的 reports/V9-T35/ 证据不得被覆盖或占用。
             run_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-pid{pid}"
@@ -246,12 +261,12 @@
                 "real_forward_executed": False,
                 "is_mock": False,
                 "requested_views": views,
-                "reason": (f"authorized to execute, but no calibration was run: the calibration runner only starts for views == {REGISTERED_CALIBRATION_VIEWS}. "
+                "reason": (f"authorized to execute, but no calibration was run: the calibration runner only starts for views == {reg_views}. "
                            "Nothing was executed and nothing should be counted as a run."),
             }
             args.output_file.parent.mkdir(parents=True, exist_ok=True)
             args.output_file.write_text(json.dumps(refusal, indent=2), encoding="utf-8")
-            sys.stderr.write(f"Real DA3 execution refused: no calibration was run for views={views} (runner requires views == {REGISTERED_CALIBRATION_VIEWS}).\n")
+            sys.stderr.write(f"Real DA3 execution refused: no calibration was run for views={views} (runner requires views == {reg_views}).\n")
             return 4
 
         result = {
@@ -262,7 +277,7 @@
             "worker_pgid": pgid,
             "model_runs": 1 if runner_executed else 0,
             "real_forward_executed": runner_executed,
-            "note": None if runner_executed else f"no real calibration executed: the runner only runs for views == {REGISTERED_CALIBRATION_VIEWS}",
+            "note": None if runner_executed else f"no real calibration executed: the runner only runs for views == {reg_views}",
             "is_mock": False,
             "pipeline_verified": True,
             "source_identity_sha256": source_id.get("upstream_files_sha256"),
```

### 2.3 `src/ainerzero/v9/teachers/da3_controlled.py`
```diff
--- reports/V9-T51/gemini-k8f3/before/da3_controlled.py
+++ src/ainerzero/v9/teachers/da3_controlled.py
@@ -64,5 +64,10 @@
 )
 from ainerzero.v9.teachers.da3_worker import REGISTERED_CALIBRATION_VIEWS
+from ainerzero.v9.teachers.t28_registration import (
+    get_registered_calibration_views,
+    get_registered_cumulative_wall_cap_s,
+    get_registered_run_wall_budget_s,
+)
 
@@ -226,7 +231,7 @@
         "missing_items": missing_items,
-        "max_cumulative_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
+        "max_cumulative_wall_seconds": get_registered_cumulative_wall_cap_s(),
         "max_per_run_wall_seconds": T6_MAX_PER_RUN_WALL_SECONDS,
@@ -300,22 +305,67 @@
 def get_effective_t6_max_views(store_path: Path | None = None) -> int:
-    """Return effective T6 max views, checking RunStore metadata for authorized override."""
-    if store_path is not None and Path(store_path).is_file():
-        try:
-            import sqlite3
-            conn = sqlite3.connect(f"file:{Path(store_path).resolve()}?mode=ro", uri=True)
-            try:
-                cur = conn.cursor()
-                cur.execute(
-                    "SELECT value FROM metadata WHERE key IN ('t6_views_override_20261027', 't35_views_override_20261027')"
-                )
-                row = cur.fetchone()
-                if row:
-                    data = json.loads(row[0])
-                    override_val = data.get("new_max_views")
-                    if isinstance(override_val, int) and override_val > 0:
-                        return override_val
-            finally:
-                conn.close()
-        except Exception:
-            pass
-    return T6_MAX_VIEWS
+    """Return effective T6 max views, checking RunStore metadata for authorized override.
+
+    Reads all `t6_views_override_YYYYMMDD` and `t35_views_override_YYYYMMDD` keys.
+    Selects the latest by date suffix (YYYYMMDD).
+    If two keys on the same day have different values, raises BenchmarkRefusalError (conflict).
+    """
+    if store_path is None:
+        return T6_MAX_VIEWS
+
+    p = Path(store_path)
+    if not p.is_file():
+        return T6_MAX_VIEWS
+
+    import re
+    import sqlite3
+
+    try:
+        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
+    except Exception:
+        return T6_MAX_VIEWS
+
+    try:
+        cur = conn.cursor()
+        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='metadata'")
+        if not cur.fetchone():
+            return T6_MAX_VIEWS
+        cur.execute("SELECT key, value FROM metadata")
+        rows = cur.fetchall()
+    except Exception:
+        return T6_MAX_VIEWS
+    finally:
+        conn.close()
+
+    pattern = re.compile(r"^(?:t6|t35)_views_override_(\d{8})$")
+    overrides_by_date: dict[str, dict[str, int]] = {}
+
+    for key, val_raw in rows:
+        m = pattern.match(key)
+        if not m:
+            continue
+        date_str = m.group(1)
+        try:
+            parsed = json.loads(val_raw)
+            if isinstance(parsed, dict):
+                views_val = parsed.get("new_max_views")
+            elif isinstance(parsed, int):
+                views_val = parsed
+            else:
+                views_val = None
+        except Exception as exc:
+            raise BenchmarkRefusalError(
+                f"Failed to parse metadata override JSON for key {key}: {exc}"
+            ) from exc
+
+        if not isinstance(views_val, int) or views_val <= 0:
+            raise BenchmarkRefusalError(
+                f"Invalid new_max_views in metadata override for key {key}: {views_val}"
+            )
+
+        if date_str not in overrides_by_date:
+            overrides_by_date[date_str] = {}
+        overrides_by_date[date_str][key] = views_val
+
+    if not overrides_by_date:
+        return T6_MAX_VIEWS
+
+    # Check for conflicts on each day
+    for date_str, keys_dict in overrides_by_date.items():
+        unique_vals = set(keys_dict.values())
+        if len(unique_vals) > 1:
+            raise BenchmarkRefusalError(
+                f"Conflicting views override values on {date_str}: {keys_dict}"
+            )
+
+    latest_date = max(overrides_by_date.keys())
+    latest_val = next(iter(overrides_by_date[latest_date].values()))
+    return latest_val
@@ -865,5 +925,15 @@
     if spec.wall_budget_seconds > T6_MAX_PER_RUN_WALL_SECONDS:
         raise BenchmarkBudgetRefused(
             f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
             f"per-run limit {T6_MAX_PER_RUN_WALL_SECONDS:.1f}s"
         )
+    run_wall_budget_s = get_registered_run_wall_budget_s()
+    if run_wall_budget_s is not None and spec.wall_budget_seconds > run_wall_budget_s:
+        raise BenchmarkBudgetRefused(
+            f"Requested wall budget {spec.wall_budget_seconds:.1f}s exceeds "
+            f"registered single-run budget limit {run_wall_budget_s:.1f}s",
+            details={
+                "requested_wall_budget_seconds": spec.wall_budget_seconds,
+                "approved_run_wall_budget_seconds": run_wall_budget_s,
+            },
+        )
@@ -927,6 +997,7 @@
-    if action == "real_pipeline" and spec.views != REGISTERED_CALIBRATION_VIEWS:
+    reg_views = get_registered_calibration_views()
+    if action == "real_pipeline" and spec.views != reg_views:
         raise BenchmarkRefusalError(
-            f"Real DA3 pipeline execution requires views == {REGISTERED_CALIBRATION_VIEWS} "
+            f"Real DA3 pipeline execution requires views == {reg_views} "
@@ -944,3 +1015,4 @@
-    if cumulative_reserved + spec.wall_budget_seconds > T6_MAX_CUMULATIVE_WALL_SECONDS:
+    cum_wall_cap = get_registered_cumulative_wall_cap_s()
+    if cumulative_reserved + spec.wall_budget_seconds > cum_wall_cap:
@@ -982,3 +1054,4 @@
-                if cum_sec_locked + spec.wall_budget_seconds > T6_MAX_CUMULATIVE_WALL_SECONDS:
+                cum_wall_cap = get_registered_cumulative_wall_cap_s()
+                if cum_sec_locked + spec.wall_budget_seconds > cum_wall_cap:
@@ -996,2 +1069,2 @@
-                        "max_wall_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
-                        "max_daily_active_seconds": T6_MAX_CUMULATIVE_WALL_SECONDS,
+                        "max_wall_seconds": cum_wall_cap,
+                        "max_daily_active_seconds": cum_wall_cap,
```

---

## 3. 测试覆盖与输出

### 3.1 完整测试集运行结果
执行命令：
```bash
.venv/bin/pytest tests/test_t28_registration_and_quota.py tests/test_da3_supervision.py tests/test_teacher_da3_controlled.py tests/test_da3_views_82.py tests/test_da3_calibration_runner.py
```
测试输出：
```text
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
collecting ... collected 81 items

tests/test_t28_registration_and_quota.py ...........                     [ 13%]
tests/test_da3_supervision.py ..........                                 [ 25%]
tests/test_teacher_da3_controlled.py .....................               [ 51%]
tests/test_da3_views_82.py ..                                            [ 54%]
tests/test_da3_calibration_runner.py ................................... [ 97%]
..                                                                       [100%]

======================== 81 passed in 77.84s (0:01:17) =========================
```

### 3.2 针对本卡新增的 11 项测试细则（`tests/test_t28_registration_and_quota.py`）
1. `test_no_registration_returns_frozen_defaults`: 无登记文件时返回 18 / 1200.0 / None，模块级属性保持 18 和 1200.0。
2. `test_valid_registration_and_sha_match`: 注册文件存在且 SHA 吻合时，得到 50 / 1290 / 120。
3. `test_sha_mismatch_refused`: SHA 不一致时拒绝并报错 `ValueError`。
4. `test_null_or_missing_fields_refused`: 提案 `budget`、`charge_per_complete_run`、`cumulative_wall_seconds_max`、`approved_run_wall_budget_seconds` 为空/缺失时大声失败。
5. `test_wall_budget_gate_single_run_120_vs_121`: `--wall-budget-seconds 121` 被拒（Exit 5），120 通过。
6. `test_metadata_views_override_by_date`:
   - 只有 20261027 时得 82；
   - 增加 20261028 (131) 时按日期取最新，得 131；
   - 同一天值冲突（如 131 vs 135）时抛出 `BenchmarkRefusalError` 拒绝。
7. `test_real_pipeline_calibration_views_gate_dynamic`: 登记后 `real_pipeline` 要求视图数与新登记口径（50）完全一致。

---

## 4. 坏对照证明（Bad Controls Verification）

在源码隔离副本中（通过 `PYTHONPATH` 独立载入副本）分别做三处破坏性改动，证明相关测试均准确翻红（变红）：

### 坏对照 1：让 SHA 校验恒真
- **改动位置**：`t28_registration.py` 中将 SHA 比较条件置为 `False and ...`。
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_1_sha/src .venv/bin/pytest tests/test_t28_registration_and_quota.py -k test_sha_mismatch_refused
  ```
- **测试结果（变红）**：
  ```text
  FAILED tests/test_t28_registration_and_quota.py::test_sha_mismatch_refused
  E       Failed: DID NOT RAISE ValueError
  ======================= 1 failed, 10 deselected in 0.21s =======================
  ```

### 坏对照 2：把 override 改回 fetchone
- **改动位置**：`da3_controlled.py:get_effective_t6_max_views` 还原为原旧版的固定键 fetchone 实现。
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_2_fetchone/src .venv/bin/pytest tests/test_t28_registration_and_quota.py -k test_metadata_views_override_by_date
  ```
- **测试结果（变红）**：
  ```text
  FAILED tests/test_t28_registration_and_quota.py::test_metadata_views_override_by_date
  E       AssertionError: assert 82 == 131
  ======================= 1 failed, 10 deselected in 0.27s =======================
  ```

### 坏对照 3：去掉单次 120s 的检查
- **改动位置**：`da3_controlled.py:execute_guarded_da3_benchmark` 中将 `spec.wall_budget_seconds > run_wall_budget_s` 检查置为 `pass`。
- **运行命令**：
  ```bash
  PYTHONPATH=/tmp/bad_control_3_no_run_wall_check/src .venv/bin/pytest tests/test_t28_registration_and_quota.py -k test_wall_budget_gate_single_run_120_vs_121
  ```
- **测试结果（变红）**：
  ```text
  FAILED tests/test_t28_registration_and_quota.py::test_wall_budget_gate_single_run_120_vs_121
  E       Failed: DID NOT RAISE BenchmarkBudgetRefused
  ======================= 1 failed, 10 deselected in 2.18s =======================
  ```

---

## 5. 执行纪律与红线遵循

1. **未碰模型与硬件**：未下载、未加载任何大模型（`model_runs=0`）；
2. **未动中央账本**：零写入 `runs.db`，未 touch `m0-worker.lock`；
3. **未改动白名单外文件**：`envs/teachers/t6/pipeline.py`、`reports/V9-T28/` 全部原封不动；
4. **备份归档与校验清单**：
   - 改动前原文件备份存放在 `reports/V9-T51/gemini-k8f3/before/`；
   - 包含完整的 `metrics.json`、`REPORT.md` 与 `SHA256SUMS.txt`。
