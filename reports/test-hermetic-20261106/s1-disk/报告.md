# S1 测试封闭补洞报告：注入假 disk_probe（ainerzero.V9.A20）

- **执行代理**：`gemini-e4b2`（二级执行 Agent）· 纯 CPU（零 MLX 运行，零 GPU 使用，不改 `src/`）
- **依据**：任务 ainerzero.V9.A20 需求规格、`COORDINATION.md`、S1 冻结规范

## 1. 文件范围选择与理由
- **选中文件**：`tests/v9/experiments/conftest.py`（未改动 `tests/v9/experiments/s1_testkit.py`）
- **选择理由**：
  1. **全套件自动覆盖与零侵入**：`conftest.py` 是 pytest 官方作用域配置文件。采用 `autouse=True` 夹具可以天然覆盖 `tests/v9/experiments/` 下全部测试模块，包括 32 个未导入 `s1_testkit` 的测试文件（如 `test_s1_resource_gate.py`、`test_s1_pacer_duty.py`、`test_s1_ledger_budget_guard.py` 等）。若放在 `s1_testkit.py`，则必须逐个侵入性修改测试文件导入，违背测试最小改动原则。
  2. **延续既有架构规范**：`tests/v9/experiments/conftest.py` 中已有 A39 的 `_no_real_mlx_in_resource_probe`（autouse=True）用于纯 CPU 环境防污染。将 `_hermetic_s1_disk_probe` 并列置于此处，保持了测试环境封闭层的一致性。
  3. **遵守 S1 冻结与接口契约**：`resource_gate.py` 严格属于 S1 冻结源文件（`src/` 不得改动）。通过在测试夹具中对 `resource_gate.collect` 猴子补丁，在未显式提供 `disk_probe` 时默认注入 500 GiB 的假探针，彻底切断对宿主机 `psutil.disk_usage` 动态余量的依赖。

## 2. 补丁实现细节
在 `tests/v9/experiments/conftest.py` 增设 autouse 夹具 `_hermetic_s1_disk_probe`：
```python
@pytest.fixture(autouse=True)
def _hermetic_s1_disk_probe(monkeypatch):
    from ainerzero.v9.experiments.s1 import resource_gate

    _orig_collect = resource_gate.collect

    def _collect_with_fake_disk_probe(*args, disk_probe=None, **kwargs):
        if disk_probe is None:
            disk_probe = lambda: 500.0 * resource_gate.GIB
        return _orig_collect(*args, disk_probe=disk_probe, **kwargs)

    monkeypatch.setattr(resource_gate, "collect", _collect_with_fake_disk_probe)
```
- **默认注入**：测试用例调用 `commands.py` 或 `worker.py` 时未指定 `disk_probe`，夹具默认注入 `500.0 * GIB`，测试不再因宿主机物理磁盘低余量而误报。
- **显式注入保持**：若调用方显式注入了 `disk_probe`（非 None），夹具原样透传，不作覆盖。

## 3. 显式磁盘门限拒绝验证
针对专门测试磁盘门限的用例与边界逻辑进行显式验证：
1. `tests/v9/experiments/test_s1_resource_gate.py` 中 `test_each_protection_line_refuses_with_an_explicit_reason`（参数 `disk_free_bytes=10.0*GIB`）与 `test_loosened_limits_are_refused`（参数 `disk_min_free_gib=100.0`）全部通过。
2. 显式调用 `resource_gate.assert_start(limits, probes={'disk_probe': lambda: 10.0 * GIB})`，确认精准拒绝抛出 `ResourceGateRefused: disk_free_limit: free 10.00 GiB < 50.0 GiB`。
3. 显式调用 `resource_gate.RuntimeGuard(limits, probes={'disk_probe': lambda: 10.0 * GIB}).sample(force=True)`，确认运行时守卫同样精准拒绝。

## 4. 坏对照实验（Bad Control）与还原验证
在隔离沙盒 `/tmp/ainerzero_s1_disk_bad_control` 中运行对抗脚本 `run_bad_control.py`，模拟宿主机磁盘剩余 24.90 GiB 现状：
- **Case 1（夹具生效）**：在模拟 24.9 GiB 环境下，15 个受影响测试文件（181 项用例）**0 失败，181 passed**。
- **Case 2（去除夹具坏对照）**：移除 `conftest.py` 中的 `_hermetic_s1_disk_probe` 后重跑，立即出现 **38 条失败**（加上子进程测试共 39 条），全部因 `disk_free_limit: free 24.90 GiB < 50.0 GiB` 变红，精准复现 P148 r3 的环境性报错。
- **逐字节还原核验**：还原 `conftest.py`，前后 SHA256 为 `73a42123657fe3fd716c71677e9e07b01204eb58aaa5494e635de3d5e92def1b`，逐字节完全吻合（100% match）。

## 5. 全量纯 CPU 回归与 实盘 artifacts 零差异
前台还原信号（`SIG_DFL`）后运行全量纯 CPU 回归（`run_full_regression.py`）：
- **用例统计**：`collected 3602 items / 6 deselected / 3596 selected`
- **回归结果**：**3596 passed, 0 failed, 6 deselected**（耗时 330.09s）。
- **此前 40 项失败完全清零**。
- **实盘审计**：全量回归前后对实盘 `artifacts/` 全量 80,929 项条目（含 `-shm` 与 `-wal`）进行 `mtime_ns`、`size`、`inode` 对比：**0 新增、0 删除、0 修改**（`diff_count: 0`）。

## 6. 产物清单
- `reports/test-hermetic-20261106/s1-disk/`:
  - `REPORT.md` / `报告.md`：本交付报告。
  - `metrics.json` / `指标.json`：结构化指标与断言记录。
  - `git_diff.patch`：`tests/v9/experiments/conftest.py` 增改补丁（23 行）。
  - `bad_control_summary.json`：坏对照对比数据。
  - `run_bad_control.py`：坏对照自动化复现与还原核验脚本。
  - `run_full_regression.py`：全量前台回归与 stat 审计脚本。
  - `pytest_full.log`：3596 项全量回归完整标准输出日志。
  - `stat_comparison.json`：实盘 80,929 项零差异审计结果。
  - `sha256.json`：交付文件完整哈希表。
