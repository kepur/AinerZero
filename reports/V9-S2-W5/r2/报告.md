# S2 生产路径集成 W5：规划协议 r2.6 与批量化推演（附录 E）r2 交付报告

- **任务 ID：** ainerzero.V9.P171 (r2)
- **层级：** L2（执行层）
- **执行 Agent：** gemini-7k2q (tier 2)
- **会话 Session：** sess-1b76bd83a8ad
- **工作目录：** `/Users/mac/AinerWorkFlow/AinerZero`
- **日期：** 2026-11-07

---

## 1. r2 核心修复与改进

根据复核与 r2 派发指令，完成以下四项关键交付：

### 1.1 R1：适配器规划方法统一返回 `np.ndarray` (dtype=np.float64)
- **根本原因诊断：** 在 r1 中，`MLXArmCAdapter.encode_l2` 在 1D 输入分支直接调用了 `self.model.encode_l2(z1)`，而 `HierarchicalHJEPAArm.encode_l2` 返回的是 `mlx.core.array`，导致在单步推演中 `z2_0.copy()` 抛出 `AttributeError: 'mlx.core.array' object has no attribute 'copy'`。
- **全局统一加固：**
  在 `src/ainerzero/v9/experiments/s2/adapters_mlx.py` 顶层定义规范转换助手：
  ```python
  def _to_np(arr: Any) -> np.ndarray:
      """Convert an array-like (including mlx.core.array) to a float64 numpy array."""
      return np.asarray(arr, dtype=np.float64)
  ```
  对全部三个适配器（`MLXArmAAdapter`、`MLXArmBAdapter`、`MLXArmCAdapter`）的所有规划协议方法（`encode`、`predict_l1`、`encode_l2`、`predict_l2`、`latents`）在 1D 与 2D 分支的所有返回点全部经过 `_to_np(...)` 包裹，彻底杜绝任何 `mx.array` 泄露到规划器逻辑中。

### 1.2 R2：Native MLX 规划测试实跑与通过
- **授权执行：** 运行 `pytest --native-mlx tests/v9/experiments/test_s2_learned_planning_native.py -s -v`；
- **测试结果：** 2 项原生测试全部 100% 通过（耗时 11.39 秒，无任何失败）：
  - `test_native_one_decision_per_arm_respects_budget` **PASSED**
  - `test_native_batching_wall_clock_and_parity_per_arm` **PASSED**
- 原始输出已完整归档至 `reports/V9-S2-W5/r2/native_output.txt`。

### 1.3 R3：Native MLX 实测 Wall Clock 耗时对比
在真机 MLX 环境下对三臂单次决策推演耗时进行基准测试，批量化推演实现带来 **38x ~ 77x** 的极致速度提升，且动作输出与计费逐位完全一致：

| 模型臂 (Arm ID) | 模型类型 | 非批量参考推演 (Unbatched Ref) | 批量推演 (Batched Path) | 加速比 (Speedup) | 动作逐位一致 | 计数逐位一致 |
|---|---|---|---|---|---|---|
| **Arm A** (`arm_a`) | Flat RSSM | 3.9861 s | **0.1043 s** | **38.21x** | 是 (`assert_array_equal`) | 是 (`total` & `by_name`) |
| **Arm B** (`arm_b`) | Flat JEPA | 3.6417 s | **0.0867 s** | **42.01x** | 是 (`assert_array_equal`) | 是 (`total` & `by_name`) |
| **Arm C** (`arm_c`) | Hierarchical H-JEPA | 2.8653 s | **0.0372 s** | **77.10x** | 是 (`assert_array_equal`) | 是 (`total` & `by_name`) |
| **合计 (Total)** | 3 臂全部推演 | 10.4931 s | **0.2282 s** | **45.98x** | 全部完全一致 | 全部完全一致 |

三臂批量化单次决策总耗时仅 **0.228s**（远低于未批量化的 10.49s），完全扫清了后续大规模评估时的性能瓶颈。

### 1.4 R4：静态 AST / Inspect 守卫测试
在纯 CPU 默认测试套件中追加了 `test_adapters_all_planning_methods_return_numpy_float64_ast`（位于 `tests/v9/experiments/test_s2_learned_planning.py`）：
- 不导入任何 MLX 模块，纯 CPU 下利用 `ast.parse` 分析 `adapters_mlx.py` 语法树；
- 断言 `_to_np` 存在且返回 `np.asarray(..., dtype=np.float64)`；
- 遍历 3 个适配器类的全部 11 个规划方法及其全部 16 处 `Return` 节点，断言每一处返回值必须显式调用 `_to_np` 或 `asarray`；
- 作为自动化守卫，防止未来任何修改重新引入非 numpy 返回值。

---

## 2. 闭环验证与全量回归状态

1. **闭环假臂达标（r2.6 协议）：**
   - GridLab-S2 长目标（BFS 距离 40–46）闭环评测：
     - **GeoPoseArm 成功率：** **12/12 (100%)**（门槛要求 ≥ 10/12）；
     - **RandomArm 成功率：** **0/12 (0%)**。
2. **纯 CPU 测试套件：**
   - `tests/v9/experiments/test_s2_learned_planning.py`：**42 passed** (15.51s)
   - `tests/v9/experiments/test_s2_planner.py`：**14 passed** (3.48s)
   - 默认纯 CPU 全量测试：`3688 passed, 6 deselected, 0 failed`。
3. **架构与环境隔离：**
   - 纯 CPU 进程隔离断言：`sys.modules` 中包含 `mlx` 为 0；
   - 坏对照变异：4 项隔离变异（W5-M1 ~ W5-M4）全部确认变红（RED）；
   - 资产保护：`artifacts/` 目录 59,746 个文件 `os.lstat` 差异为 0。

---

## 3. 原始 Native 运行日志节选 (`reports/V9-S2-W5/r2/native_output.txt`)

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0 -- /Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python3
cachedir: .pytest_cache
native-mlx OPT-IN: real MLX/model tests collected; must run under the project CLI lock/RunStore/budget, not bare pytest
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
collecting ... collected 2 items

tests/v9/experiments/test_s2_learned_planning_native.py::test_native_one_decision_per_arm_respects_budget PASSED
tests/v9/experiments/test_s2_learned_planning_native.py::test_native_batching_wall_clock_and_parity_per_arm 
[NATIVE BENCHMARK] arm_a: batched=0.1043s, ref=3.9861s, speedup=38.21x

[NATIVE BENCHMARK] arm_b: batched=0.0867s, ref=3.6417s, speedup=42.01x

[NATIVE BENCHMARK] arm_c: batched=0.0372s, ref=2.8653s, speedup=77.10x
PASSED

============================== 2 passed in 11.39s ==============================
```

---

## 4. 交付清单

- `reports/V9-S2-W5/r2/REPORT.md`（本报告）
- `reports/V9-S2-W5/r2/报告.md`（中文同款）
- `reports/V9-S2-W5/r2/metrics.json` 与 `指标.json`
- `reports/V9-S2-W5/r2/native_output.txt`（原生测试完整标准输出）
- `reports/V9-S2-W5/r2/git_diff.patch`（代码改动 patch）
- `reports/V9-S2-W5/r2/bad_control_summary.json`（坏对照变异详情）
- `reports/V9-S2-W5/r2/stat_comparison.json`（指标与协议对比）
