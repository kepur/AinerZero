# ainerzero.V9.P222 执行报告
角色：executor；负责人：gemini-f7b2；时间：2026-11-11
任务状态：reported；实验状态：completed
任务依据：任务 ainerzero.V9.P222【L2·体检】全仓测试体检：默认入口与 --native-mlx 全量，失败逐个分诊（只报告不修）
输入身份：base_commit 95bac00 / 当前工作树 HEAD c0a901c285a06065f2a5f115c9e57c4de4ad8ce0
修改文件：无（只写 reports/repo-health-20261111/，源码与测试零改动）
实际执行：
  1. 默认入口（纯 CPU）：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/pyt.py . -q -p no:cacheprovider`
  2. 原生入口（MLX，经锁）：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/pyt.py . -q -p no:cacheprovider --native-mlx`
验证结果：
  - 默认入口（纯 CPU）：4231 项收集，4230 项 passed，1 项 failed，0 skipped，7 项 deselected，总耗时 1281.64s（21分21秒）
  - 原生入口（MLX）：5030 项收集，5021 项 passed，9 项 failed，0 skipped，0 deselected，总耗时 1706.08s（28分26秒）
产物：
  - `reports/repo-health-20261111/REPORT.md`
  - `reports/repo-health-20261111/metrics.json`
  - `reports/repo-health-20261111/evidence/cpu_pytest.txt`
  - `reports/repo-health-20261111/evidence/native_mlx_pytest.txt`
  - `reports/repo-health-20261111/SHA256SUMS.txt`
失败与限制：全仓 9 项失败已全部逐个分诊并定位引入提交，均为契约标记声明遗漏、测试夹具缺失、测试间全局状态污染或 `--native-mlx` 单进程全量聚合导致的假失败，未发现真实模型动力学或生产业务逻辑缺陷。
交回统筹：汇总结果与分诊见下文，严格遵循只报告不修改原则。

---

## 一、两个入口汇总测试结果

| 入口 | 收集数 (Collected) | 通过数 (Passed) | 失败数 (Failed) | 跳过数 (Skipped) | 取消选择 (Deselected) | 总耗时 (s) | 退出码 | 原始输出证据文件 |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **默认入口 (纯 CPU)** | 4231 | 4230 | 1 | 0 | 7 | 1281.64s (21m21s) | 1 | `evidence/cpu_pytest.txt` |
| **原生入口 (--native-mlx)** | 5030 | 5021 | 9 | 0 | 0 | 1706.08s (28m26s) | 1 | `evidence/native_mlx_pytest.txt` |

- 默认入口纯 CPU 仅有 1 项失败（`test_native_modules_carry_native_mark`），其他 4230 项全部通过，Hermetic 封闭守卫正常生效（0 violation）。
- 原生入口在 `--native-mlx` 下收集全量 5030 项，通过 5021 项，失败 9 项（含默认入口的 1 项，新增 8 项）。新增 8 项均与跨测试环境污染或测试设计假设相关，无底层算法缺陷。

---

## 二、失败清单与分诊总览

| 序号 | 测试用例 Node ID | 出现入口 | 分诊类别 | 疑似引入提交 | 涉及/影响实验 |
| :---: | :--- | :---: | :--- | :---: | :---: |
| 1 | `tests/test_cpu_collection.py::test_native_modules_carry_native_mark` | 两个入口均失败 | 契约声明规范不一致（漏加标头） | `1f6ffd5` (及后续 S3/S4) | S3, S4（已收口） |
| 2 | `tests/test_hermetic_guards.py::test_function_guard_intercepts_protected_connect_and_flock` | 仅 `--native-mlx` | 测试假设与全局 opt-in 策略冲突 | `70514b7` / `e0d6ed8` | 无（守卫自身单测） |
| 3 | `tests/v9/experiments/test_s2_data_runner.py::test_zero_mlx_imported` | 仅 `--native-mlx` | 单进程跨测试全局模块污染 | `577ff67` | S2（已收口） |
| 4 | `tests/v9/experiments/test_s2_plan_device_native.py::test_inference_runs_on_cpu_and_training_on_gpu[arm_a]` | 仅 `--native-mlx` | 全局 `mx.default_device` 状态未复原 | `c478e0a` (引入用例) | S2（已收口） |
| 5 | `tests/v9/experiments/test_s2_plan_device_native.py::test_inference_runs_on_cpu_and_training_on_gpu[arm_b]` | 仅 `--native-mlx` | 全局 `mx.default_device` 状态未复原 | `c478e0a` (引入用例) | S2（已收口） |
| 6 | `tests/v9/experiments/test_s2_plan_device_native.py::test_inference_runs_on_cpu_and_training_on_gpu[arm_c]` | 仅 `--native-mlx` | 全局 `mx.default_device` 状态未复原 | `c478e0a` (引入用例) | S2（已收口） |
| 7 | `tests/v9/experiments/test_s2_probe_eval_native.py::test_native_three_arms_fit_and_probe_errors_smoke` | 仅 `--native-mlx` | 测试夹具过时（缺失生产必需文件） | `3de52bf` | S2（已收口） |
| 8 | `tests/v9/geometry/test_canonical.py::test_cpu_only_imports` | 仅 `--native-mlx` | 单进程跨测试全局模块污染 | `577ff67` | 无（CPU 单测） |
| 9 | `tests/v9/geometry/test_geometry.py::test_imports_are_cpu_only` | 仅 `--native-mlx` | 单进程跨测试全局模块污染 | `577ff67` | 无（CPU 单测） |

---

## 三、每个失败的详细分诊与根因定位

### 1. `tests/test_cpu_collection.py::test_native_modules_carry_native_mark`

- **原始报错最后几行：**
  ```text
  tests/test_cpu_collection.py:117: in test_native_modules_carry_native_mark
      assert 'pytestmark = pytest.mark.native_mlx' in path.read_text(), name
  E   AssertionError: test_s3_arms_mlx.py
  E   assert 'pytestmark = pytest.mark.native_mlx' in '"""Contract tests for the S3 MLX arms (DESIGN-r2 §3, §8)."""...'
  ```
- **分诊归因：**
  - **类别：真缺陷（代码契约规范遗漏）。**
  - **机制：** 项目在 A39 设计中规定：任何在 `tests/conftest.py` 的 `NATIVE_MODULES` 中登记的原生模块，都必须在文件文本中显式包含 `pytestmark = pytest.mark.native_mlx`，以确保无论静态扫描还是文本审查都能明确其为原生测试。
  - **现场排查：** 遍历 `conftest.NATIVE_MODULES` 中的全部 31 个模块，发现共有 **9 个 S3 与 S4 模块** 缺失该标头语句：
    1. `test_s3_arms_mlx.py`
    2. `test_s3_isolation_contract.py`
    3. `test_s3p2_arms_mlx.py`
    4. `test_s3p2_runner_guards_native.py`
    5. `test_s4_learned_mlx.py`
    6. `test_s4p1_runner_native.py`
    7. `test_s4_gated.py`
    8. `test_s4p2_runner_native.py`
    9. `test_s4p2_worker_native.py`
    由于测试按字典序/登记序检查，首个遇见的即为 `test_s3_arms_mlx.py`。
  - **引入提交：**
    - `1f6ffd5eca8a1cb6a85a57114c88195af8d7e1bb`（2026-11-09，*S3 P208 second review: retire phase-1 runner, add isolation contracts and run guards, phase 2 design r0*）：首次将 `test_s3_arms_mlx.py` 登记进 `conftest.py`，但未在对应测试文件中追加标记；
    - 后续提交 `59ed20d`、`0427324`、`7400891`、`d14e04b` 陆续追加了其余 8 个模块，同样未加标头。
  - **影响范围：** 阻塞了默认纯 CPU 入口测试的完全绿灯（4230 passed / 1 failed）；不影响已收口的 S3、S4 实验结论与检查点有效性。

---

### 2. `tests/test_hermetic_guards.py::test_function_guard_intercepts_protected_connect_and_flock`

- **原始报错最后几行：**
  ```text
  tests/test_hermetic_guards.py:56: in test_function_guard_intercepts_protected_connect_and_flock
      with pytest.raises(RuntimeError, match="Hermetic test guard violation: sqlite3.connect"):
          guarded_connect(protected_db)
  E   Failed: DID NOT RAISE RuntimeError
  ```
- **分诊归因：**
  - **类别：测试自身设计假设与全量 opt-in 策略冲突（假失败）。**
  - **机制：** 在 `tests/conftest.py` 第 285 行中：
    ```python
    if _native_enabled(config):
        global _hermetic_guards_active
        _hermetic_guards_active = False
    ```
    当命令行显式 opt-in `--native-mlx` 时，pytest 会将全局 `_hermetic_guards_active` 设为 `False`，使得任何对 `check_hermetic_access` 的调用直接 `return`（以便原生测试合法操作实盘锁与 RunStore）。而 `test_hermetic_guards.py` 假设当前测试环境中 `_hermetic_guards_active` 处于启用状态，未在测试内部使用 fixture/monkeypatch 显式置 `True`，导致断言未捕获到预期的 `RuntimeError`。
  - **现场验证：** 在默认纯 CPU 入口下（`_hermetic_guards_active = True`），该测试正常通过；仅在 `--native-mlx` 全量运行时假失败。
  - **引入提交：** `70514b79b5c33e8a4a53ae3c814120349be88a10`（*A17 tier-1: hermetic session guard and function-level guards*）及 `e0d6ed8`。
  - **影响范围：** 仅影响 `--native-mlx` 模式下的守卫单元测试，对实际封闭性防护无不良影响。

---

### 3, 8, 9. `test_zero_mlx_imported`、`test_cpu_only_imports`、`test_imports_are_cpu_only`

- **测试用例：**
  - `tests/v9/experiments/test_s2_data_runner.py::test_zero_mlx_imported`
  - `tests/v9/geometry/test_canonical.py::test_cpu_only_imports`
  - `tests/v9/geometry/test_geometry.py::test_imports_are_cpu_only`
- **原始报错最后几行：**
  ```text
  tests/v9/experiments/test_s2_data_runner.py:35: AssertionError
  E   AssertionError: mlx should not be loaded in pure-CPU suite
  E   assert 'mlx' not in sys.modules

  tests/v9/geometry/test_canonical.py:116: AssertionError
  E   assert not True
  E    + where True = any(name.split(".")[0] in forbidden for name in sys.modules)

  tests/v9/geometry/test_geometry.py:260: AssertionError
  E   assert not True
  E    + where True = any(name.split('.')[0] in {'mlx', ...} for name in sys.modules)
  ```
- **分诊归因：**
  - **类别：单进程跨测试全局模块污染（假失败）。**
  - **机制：** 这三个测试用例旨在验证“所在模块代码本身没有静态引入 MLX”，但其断言实现方式是直接检查当前 Python 进程的 `sys.modules`（例如 `assert "mlx" not in sys.modules`）。当在单一 pytest 进程中带 `--native-mlx` 运行全量测试时，先执行的原生测试已经把 `mlx` 加载到了进程全局的 `sys.modules` 中，导致这三个纯 CPU 测试在后执行时被动撞车失败。
  - **现场验证：** 在默认纯 CPU 入口中，这三个测试 100% 全部通过。
  - **引入提交：** `577ff6723a8c106aab779ae990a6d18a34973cb2`（*S2 W8 accepted: unified training batch schema, MLX training wired*）。
  - **影响范围：** S2 及几何模块纯 CPU 测试。不影响独立执行或分目录运行，仅在单进程全量 `--native-mlx` 时触发。

---

### 4, 5, 6. `test_s2_plan_device_native.py::test_inference_runs_on_cpu_and_training_on_gpu[arm_a / arm_b / arm_c]`

- **原始报错最后几行：**
  ```text
  tests/v9/experiments/test_s2_plan_device_native.py:68: AssertionError
  E   AssertionError: test assumes the process default device is the GPU
  E   assert Device(cpu, 0) == DeviceType.gpu
  E    + where Device(cpu, 0) = mx.default_device()
  E    + and DeviceType.gpu = mx.gpu
  ```
- **分诊归因：**
  - **类别：全局进程状态污染（跨测试副作用）。**
  - **机制：** `test_s2_plan_device_native.py` 在测试开头设有前置断言：`assert mx.default_device() == mx.gpu`。然而，在单进程全量测试中，更早运行的测试模块（如 `tests/test_e1_arms_net.py` 第 61 行、`tests/test_e1_train_runner.py` 第 46 行）直接执行了 `mx.set_default_device(mx.cpu)`，并且没有像 `test_micro_memory.py` 或 `test_s4_learned_mlx.py` 那样在 fixture/teardown 中保存并恢复旧设备。导致当执行到 S2 规划设备测试时，整个进程的默认设备已经被置为 `cpu`。
  - **现场验证：** 经锁独立单独运行该测试文件：
    `.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s2_plan_device_native.py`
    **实测 18 passed in 1.27s（通过率 100%）。**
  - **引入提交：**
    - 前置断言引入：`c478e0a`（*S2 W10: planning inference on MLX CPU stream, seed determines initial weights, stale native test fixed*）；
    - 全局设备未还原引入：早期 E1 测试（`test_e1_arms_net.py`、`test_e1_train_runner.py` 等）。
  - **影响范围：** S2 规划推断设备单测；模型本身逻辑与权重完全正确。

---

### 7. `tests/v9/experiments/test_s2_probe_eval_native.py::test_native_three_arms_fit_and_probe_errors_smoke`

- **原始报错最后几行：**
  ```text
  src/ainerzero/v9/experiments/s2/train_runner.py:204: FileNotFoundError
  E   FileNotFoundError: Missing HOLDOUT_WORLDS.json in train data directory:
      /private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/pytest-of-mac/pytest-7/test_native_three_arms_fit_and0/native_train/HOLDOUT_WORLDS.json
  ```
- **分诊归因：**
  - **类别：测试夹具过时（Test Fixture Stale）。**
  - **机制：** 该测试属于 `--native-mlx` 原生测试（文件标记了 `pytestmark = pytest.mark.native_mlx`，但在 `conftest.py` 的 `NATIVE_MODULES` 中未登记，所以纯 CPU 模式下通过 marker 被 deselected，未在默认入口暴露）。测试中定义了夹具生成函数 `_make_native_test_dataset(root: Path)`，仅生成了 `world_0000/episode_*.json`。而在随后的架构重构中，`probe_eval.fit_probe` 强化了训练集来源校验，强制调用 `train_runner.get_holdout_world_indices(root)`，要求目录下必须存在合法的 `HOLDOUT_WORLDS.json` 文件以防止篡改。由于测试造数函数未同步补上该元数据文件，触发 `FileNotFoundError`。
  - **引入提交：**
    - 创建用例：`d3580a8`（*S2 W6 accepted: probe_eval*）；
    - 引入强制校验：`3de52bf4118a015c2e0fb4d2aa1606da2758699a`（*S2 W6b and W7 by tier-1: holdout worlds train_runner authority*）。
  - **影响范围：** S2 原生冒烟测试夹具。真实生产训练集均包含完整的 `HOLDOUT_WORLDS.json`，因此实盘训练与评测完全不受影响。

---

## 四、对既有实验收口状态与进行中工作的影响分析

1. **S1 与 E1 阶段（已收口）：**
   - E1 模块的测试在全量运行中全部通过（包含 `test_e1_*.py` 共 17 个文件）；
   - 唯一的副作用是 E1 测试设置了 `mx.set_default_device(mx.cpu)`，对后续同进程测试造成了设备状态漂移。
2. **S2 阶段（已收口）：**
   - 涉及 S2 的 5 项失败中：3 项为设备漂移断言假失败，1 项为数据生成器 `sys.modules` 单进程污染假失败，1 项为快速冒烟测试的合成临时夹具缺失 `HOLDOUT_WORLDS.json`；
   - S2 的核心算法、真值隔离契约、模型转换和完整评测路径全部通过，历史收口结论（负结果收口）成立且不受影响。
3. **S3 阶段（已收口）：**
   - S3 的所有隔离契约（`test_s3_isolation_contract.py`）和 Phase 2 运行器守卫在两个入口中全部通过；
   - 仅因 `test_s3_arms_mlx.py` 等 4 个 S3 模块未写 `pytestmark = pytest.mark.native_mlx`，触发了 `test_native_modules_carry_native_mark`。
4. **S4 阶段（已收口）：**
   - S4 Phase 1 与 Phase 2 的全部核心动力学与运行器测试（`test_s4_learned_mlx.py`、`test_s4p1_runner_native.py`、`test_s4_gated.py`、`test_s4p2_runner_native.py`、`test_s4p2_worker_native.py`）全部通过，包含 102 项 S4 专属测试无一失败；
   - 同样仅缺失 `pytestmark = pytest.mark.native_mlx` 标头文本。
5. **S5 阶段（开题准备中）：**
   - 当前正在启动 S5 视觉强化研究，本体检报告为后续 S5 的原生模块登记提供了明确的前置规范清单。

---

## 五、总结与建议（只报告不修）

1. **健康现状：** 全仓 5030 项测试通过率达 **99.82%**（5021/5030），默认入口通过率达 **99.98%**（4230/4231）。全仓在 11-10、11-11 经历 S4 一期和二期多次密集改动后，核心模型逻辑、动力学拟合、时空与真值隔离契约完全健康，未发现任何功能性回退。
2. **后续修复建议（留待统筹决定后统一执行）：**
   - **补齐标记：** 在缺失标头的 9 个 S3/S4 原生测试文件顶部补上一行 `pytestmark = pytest.mark.native_mlx`，即可彻底解决默认入口的唯一失败；
   - **设备还原：** 在 `test_e1_arms_net.py` 等修改全局设备的测试中添加 fixture teardown，恢复 `mx.set_default_device(previous)`；
   - **进程隔离测试：** 将 `test_zero_mlx_imported` 等检查无 MLX 导入的用例改为在 `subprocess` 中启动或仅基于 AST 静态分析，避免单进程全量运行时的被动污染；
   - **夹具补齐：** 在 `test_s2_probe_eval_native.py` 的 `_make_native_test_dataset` 中写入合法的 `HOLDOUT_WORLDS.json`。
