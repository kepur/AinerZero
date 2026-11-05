# ainerzero.V9.P63 执行报告：取消 DA3 基准与 AWZ Blender 渲染的接电守卫

角色：executor（二级）；负责人：gemini-k8f3；时间：2026-10-28
任务状态：reported；实验状态：completed
任务依据：ainerzero.V9.P63（用户 10-28 指示「取消各种电池保护，用电池也不影响训练」）
输入身份：
- 备份原文件：`reports/V9-P63/gemini-k8f3/before/`（见 `before/SHA256SUMS.txt`）
修改文件：
1. `src/ainerzero/v9/teachers/da3_controlled.py`
2. `tests/test_da3_supervision.py`
3. `/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/render_backend/blender_npr.py`
4. `reports/V9-P63/gemini-k8f3/`

## 1. 改动前后 Diff

### 1.1 `src/ainerzero/v9/teachers/da3_controlled.py`
```diff
--- reports/V9-P63/gemini-k8f3/before/da3_controlled.py
+++ src/ainerzero/v9/teachers/da3_controlled.py
@@ -243,7 +243,7 @@
 
     Guards:
     1. Process RSS <= 8.0 GiB (T6_MAX_PROCESS_RSS_GIB)
-    2. Power source must be AC Power (fails if on battery)
+    2. 电源来源只记录、不拦截（用户 10-28）
     3. System available memory >= system_reserve_bytes (default 16 GiB)
     4. Swap growth from baseline <= 1.0 GiB
     """
@@ -262,14 +262,7 @@
     power_source = power_source_override or hw.get("power_source", "unknown")
 
     if check_system_guards:
-        # Check 1: Power source
-        if power_source == "battery":
-            raise BenchmarkResourceRefused(
-                "Power source is battery; AC power required for benchmark execution (running on battery refused)",
-                details={"power_source": power_source},
-            )
-
-        # Check 2: System available memory
+        # Check 1: System available memory
         vm = psutil.virtual_memory()
         if vm.available < system_reserve_bytes:
             raise BenchmarkResourceRefused(
```

### 1.2 `tests/test_da3_supervision.py`
```diff
--- reports/V9-P63/gemini-k8f3/before/test_da3_supervision.py
+++ tests/test_da3_supervision.py
@@ -198,15 +198,13 @@
 
 def test_hardware_resource_guards():
     """Verify hardware protection lines: AC power, system RAM reserve, swap growth."""
-    # 1. AC Power / Battery Guard
-    # If battery power is reported, it must raise BenchmarkResourceRefused
-    with pytest.raises(BenchmarkResourceRefused) as exc_p:
-        check_t6_resource_limits(
-            check_system_guards=True,
-            system_reserve_bytes=1024,
-            power_source_override="battery",
-        )
-    assert "battery" in str(exc_p.value).lower()
+    # 1. AC Power / Battery Guard (电源来源只记录、不拦截；用户 10-28)
+    res_battery = check_t6_resource_limits(
+        check_system_guards=True,
+        system_reserve_bytes=1024,
+        power_source_override="battery",
+    )
+    assert res_battery["power_source"] == "battery"
 
     # 2. Available RAM Reserve Guard (16 GiB registered protection line)
     # Requesting system reserve larger than host RAM must raise BenchmarkResourceRefused
```

### 1.3 `AnimeWorldZero/python/animeworld/render_backend/blender_npr.py`
```diff
--- reports/V9-P63/gemini-k8f3/before/blender_npr.py
+++ python/animeworld/render_backend/blender_npr.py
@@ -92,7 +92,7 @@
 
 
 def check_power_and_blender_guards() -> dict[str, Any]:
-    """环境守护：AC 供电、Blender 版本、/tmp/ainer_blender.lock 状态。"""
+    """环境守护：电源状态记录（不拦截，用户 10-28）、Blender 版本、/tmp/ainer_blender.lock 状态。"""
     # 1. 检查电源
     res_ps = subprocess.run(
         ["pmset", "-g", "ps"],
@@ -100,8 +100,12 @@
         text=True,
         check=False,
     )
-    if "AC Power" not in res_ps.stdout and "AC" not in res_ps.stdout:
-        raise RuntimeError(f"非 AC 供电环境，依规停手: {res_ps.stdout.strip()}")
+    if "AC Power" in res_ps.stdout:
+        power = "AC Power"
+    elif "Battery Power" in res_ps.stdout:
+        power = "Battery Power"
+    else:
+        power = "unknown"
 
     # 2. 检查 Blender 版本
     if not BLENDER_BIN.is_file():
@@ -121,7 +125,7 @@
         raise RuntimeError(f"全局锁被占: {lock_file}")
 
     return {
-        "power": "AC Power",
+        "power": power,
         "blender_version": "5.2.2",
         "lock_free": True,
     }
```

## 2. 测试输出

### 2.1 AinerZero 主环境（`.venv`）
命令：`.venv/bin/python -m pytest tests/test_da3_supervision.py tests/test_teacher_da3_controlled.py tests/test_da3_views_82.py -q`
结果：
```
.................................                                        [100%]
33 passed in 73.55s (0:01:13)
```

### 2.2 DA3 真实环境（`envs/teachers/.venv-t6`）
命令：`envs/teachers/.venv-t6/bin/python -m pytest tests/test_da3_supervision.py tests/test_teacher_da3_controlled.py tests/test_da3_views_82.py -q`
结果：
```
/Users/mac/AinerWorkFlow/AinerZero/envs/teachers/.venv-t6/bin/python: No module named pytest
```
注记：`.venv-t6` 为真实模型专用独立运行时，未安装 pytest 测试工具链，收集阶段即报告无模块（按任务规范如实记录）。

### 2.3 AWZ 渲染测试（`.venv`）
命令 1：`cd /Users/mac/AinerWorkFlow/AnimeWorldZero && .venv/bin/python -m pytest tests/render_backend/test_blender_npr.py -q`
结果：
```
.....................                                                    [100%]
21 passed in 7.67s
```

命令 2（全量 render_backend）：`cd /Users/mac/AinerWorkFlow/AnimeWorldZero && .venv/bin/python -m pytest tests/render_backend/ -q`
结果：
```
........................................................................ [ 55%]
..........................................................               [100%]
130 passed in 12.46s
```

## 3. 坏对照验证（证明变红）

### 3.1 DA3 坏对照
在临时目录 `/tmp/bad_control_da3` 放置包含原电池拒绝逻辑的 `da3_controlled.py`，并将 `PYTHONPATH` 指向该临时目录：
命令：`PYTHONPATH=/tmp/bad_control_da3/src .venv/bin/python -m pytest tests/test_da3_supervision.py -k test_hardware_resource_guards -v`
输出（变红，抛出原异常）：
```
tests/test_da3_supervision.py::test_hardware_resource_guards FAILED      [100%]

=================================== FAILURES ===================================
________________________ test_hardware_resource_guards _________________________
    ...
>   raise BenchmarkResourceRefused(
        "Power source is battery; AC power required for benchmark execution (running on battery refused)",
        details={"power_source": power_source},
    )
E   ainerzero.v9.teachers.benchmark_protocol.BenchmarkResourceRefused: Power source is battery; AC power required for benchmark execution (running on battery refused)
```

### 3.2 AWZ 坏对照
在临时目录 `/tmp/bad_control_awz` 放置包含原 AC 供电硬校验的 `blender_npr.py`：
测试在 mock 电池供电（`Now drawing from 'Battery Power'`）下调用 `check_power_and_blender_guards`：
- 当前修改后的 AWZ：测试通过（PASSED），返回 `{'power': 'Battery Power', 'blender_version': '5.2.2', 'lock_free': True}`。
- `PYTHONPATH=/tmp/bad_control_awz` 坏对照代码：测试变红（FAILED，抛出原 RuntimeError）：
```
FAILED test_battery_power_guard_does_not_raise
RuntimeError: 非 AC 供电环境，依规停手: Now drawing from 'Battery Power'
 -InternalBattery-0 95%; discharging
```

## 4. 守卫保留与未变项核验
- 内存（RSS/系统预留）、swap 增长、磁盘空闲保护守卫完全保留。
- Blender 5.2.2 版本校验与全局排他锁完全保留。
- `src/ainerzero/runtime/*`、`configs/*.yaml`、已交付报告及预注册均未变动。
- 系统 `pmset` 电源设置无任何写入操作。
