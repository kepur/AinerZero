# V9.A20 非作者复核报告（S1 测试注入假 disk_probe）

**复核者自证**：复核 Agent 为 `gemini-8f4b`（二级执行层，会话指纹 `sess-4bc4b7ff4dc0`），独立非作者复核（被复核任务 `ainerzero.V9.A20` 作者为 `gemini-e4b2`，非同会话别名，无自审冲突）。

---

## 1. 结论建议

**RECOMMEND_ACCEPT**（建议无条件接纳）

改动范围严格受限在测试配置文件内，零改动 S1 冻结源码；在低磁盘余量模拟下成功阻断了对物理磁盘的依赖，坏对照准确变红；显式门限测试未受影响；前台全量纯 CPU 回归 3602 项全过，实盘 `artifacts/` 80,929 项条目前后零差异。

---

## 2. 独立核查要项

### 2.1 改动范围与代码冻结审查
- **实际改动文件**：仅 `tests/v9/experiments/conftest.py`（新增 `_hermetic_s1_disk_probe` 夹具，共 23 行代码）。
- **S1 冻结源码一致性**：
  - `git diff HEAD -- src/ainerzero/v9/experiments/s1/`：输出为空（0 字节改动）。
  - `src/` 中 S1 全部代码与基线逐字节一致，未发生任何非授权漂移或放宽。
- **补丁吻合度**：
  - `tests/v9/experiments/conftest.py` 的 git diff 与 A20 交付物 `reports/test-hermetic-20261106/s1-disk/git_diff.patch` 逐字节比对 100% 吻合。

### 2.2 隔离副本依赖切断验证（模拟低余量全过 vs 去夹具变红）
依据 `reports/V9-S2-P148/r3/pytest_full.log` 提取的测试清单进行验证：
- **模拟低余量环境**：打补丁使 `psutil.disk_usage` 报告物理可用空间为 `10.0 GiB`（低于 S1 门限 `50.0 GiB`）。
- **Case 1（夹具生效）**：
  - 运行 S1 测试集（39 条测试）：**39 passed in 8.00s**，全部通过，未发生任何因物理磁盘不足引发的误拦截。
- **Case 2（去夹具坏对照）**：
  - 从 `tests/v9/experiments/conftest.py` 中移除 `_hermetic_s1_disk_probe` 夹具后重跑同一批测试：
  - 结果：**38 failed, 1 passed in 4.26s**。
  - 失败原因：全部因 `ResourceGateRefused: disk_free_limit: free 10.00 GiB < 50.0 GiB` 立即变红报错，精准复现宿主机磁盘余量受限时的故障表象。
  - （注：唯独 `test_the_ordering_guard_is_load_bearing_bad_control` 因拉起子进程执行，且当前宿主机真实磁盘 >2TB，因此在仅 mock 父进程时不报错）。
- **还原核验**：坏对照结束后恢复 `conftest.py`，SHA256 哈希完全一致。

### 2.3 门限测试有效性审查（未削弱）
核查夹具实现：
```python
def _collect_with_fake_disk_probe(*args, disk_probe=None, **kwargs):
    if disk_probe is None:
        disk_probe = lambda: 500.0 * resource_gate.GIB
    return _orig_collect(*args, disk_probe=disk_probe, **kwargs)
```
夹具仅在 `disk_probe is None` 时注入假探针；当测试显式注入 `disk_probe` 或测试配置门限时，原有防护与拒签行为完全不受干扰。

**显式测试磁盘门限的用例清单与独立核验结果**：
1. `tests/v9/experiments/test_s1_resource_gate.py::test_each_protection_line_refuses_with_an_explicit_reason[overrides5-disk_free_limit]`
   - 测试逻辑：传入 `disk_free_bytes = 10.0 * GIB`（< 50.0 GiB 门限）。
   - 验证结果：**PASSED**（精准触发 `disk_free_limit` 拒绝并断言成功）。
2. `tests/v9/experiments/test_s1_resource_gate.py::test_loosened_limits_are_refused[overrides5-disk_min_free_gib]`
   - 测试逻辑：传入宽松配置 `disk_min_free_gib = 100.0`。
   - 验证结果：**PASSED**（非标准门限配置被拒）。
3. `tests/v9/experiments/test_s1_resource_gate.py::test_assert_start_with_injected_probes`
   - 测试逻辑：显式注入 probes 验证启动防护。
   - 验证结果：**PASSED**。
4. **编程式接口显式拒绝断言（直接调用验证）**：
   - `resource_gate.assert_start(limits, probes={'disk_probe': lambda: 10.0 * GIB})` 抛出 `ResourceGateRefused: disk_free_limit: free 10.00 GiB < 50.0 GiB`。
   - `resource_gate.RuntimeGuard(limits, probes={'disk_probe': lambda: 10.0 * GIB}).sample(force=True)` 抛出 `ResourceGateRefused: disk_free_limit: free 10.00 GiB < 50.0 GiB`。
   - `resource_gate.evaluate(snapshot_10gib, limits)` 返回 `['disk_free_limit: free 10.00 GiB < 50.0 GiB']`。

结论：显式门限测试全部保持严格拒绝，安全防线毫无削弱。

### 2.4 全量纯 CPU 回归与实盘零差异审计
通过 `relay exec ainerzero.V9.A21` 在前台运行（已通过 `signal.signal(..., signal.SIG_DFL)` 还原系统信号）：
- **用例统计**：`collected 3608 items / 6 deselected / 3602 selected`
- **回归结果**：**3602 passed, 6 deselected, 0 failed**（耗时 335.35s，exit code 0）。
- **实盘 `artifacts/` 审计**：
  - 测试前扫描条目数：`80,929`
  - 测试后扫描条目数：`80,929`
  - 增删改差异计数（`diff_count`）：**0**
  - 实盘无任何文件变更，测试封闭性（hermeticity）100% 成立。

---

## 3. 产物记录
- `reports/test-hermetic-20261106/s1-disk/review/`:
  - `REVIEW.md`：本非作者复核报告。
  - `review_metrics.json`：结构化复核指标。
  - `run_review_regression.py`：全量回归与 stat 审计复核执行脚本。
  - `pytest_full.log`：3602 项全量回归完整标准输出日志。
  - `stat_comparison.json`：实盘 80,929 项零差异审计结果。
