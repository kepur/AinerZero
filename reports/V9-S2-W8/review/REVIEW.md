# P181 非作者复核 · S2 集成 W8（P180）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-k7m2`（二级执行层；非 P180 作者；作者为 `gemini-h8q3`）
- **被复核任务：** `ainerzero.V9.P180`（reported）
- **复核日期：** 2026-11-08
- **任务目标：** 统一 S2 训练批次接口，打通真实 MLX 训练，修复 smoke r1 根因；纯只读审查源码，亲手复现坏对照与自选变异，实盘 artifacts 零改动。

---

## 1. 范围（Scope）

- **P180 声明修改文件**（共 11 个模块）：
  - `src/ainerzero/v9/experiments/s2/spec.py`
  - `src/ainerzero/v9/experiments/s2/core_math.py`
  - `src/ainerzero/v9/experiments/s2/arms_mlx.py`
  - `src/ainerzero/v9/experiments/s2/train_runner.py`
  - `src/ainerzero/v9/experiments/s2/adapters_mlx.py`
  - `src/ainerzero/v9/experiments/s2/smoke.py`
  - `tests/conftest.py`
  - `tests/v9/experiments/test_s2_train_runner.py`
  - `tests/v9/experiments/test_s2_wiring.py`
  - `tests/v9/experiments/test_s2_production_e2e_native.py`
  - `tests/v9/experiments/test_s2_train_native.py`
- **核对结果**：
  - `git diff --name-only` 包含 10 个修改文件；
  - `tests/v9/experiments/test_s2_train_native.py` 为 P180 原生测试新增文件；
  - `reports/V9-S2-W8/` 为 P180 交付目录；
  - `git diff src/ tests/` 与 P180 交付的补丁 `reports/V9-S2-W8/diff`（SHA256: `31380638777611baf0aeaa75c8067357f86a4d12de33cc91e4da2d162c837fa0`）**逐字节 100% 完全一致**，无任何附加改动。
  - 工作树中其他未跟踪文件均为历史任务遗留（如 `reports/V9-B3-mlx-unitcost/`, `reports/V9-E1...`, `reports/V9-P44/` 等），不是本任务引入。
  - 未触碰任何受保护文件（`eval_runner.py`, `commands.py`, `learned_planning.py`, `planner.py`, `probe_eval.py`, `artifacts/` 等）。
- **`spec.py` 前缀指纹核验**：
  - `spec.py` 本次仅在文件最末尾（第 310 行起）追加了 21 行 `BATCH_*` 常量定义，前序字节无一处改动。
  - 实盘前 8721 字节 SHA256 为：`b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`。
  - 该哈希与 `tests/v9/experiments/test_s2_spec.py:208` 中的断言完全一致，且 `test_s2_spec.py` 11/11 严格全通。
  - **重要核对差异注记**：作者在 P180 `REPORT.md` 及 `metrics.json` 中写了 `spec_prefix_sha256 = 3e36e6ba6e680a6c02930438cf3878b31a5eb23b090e0b040e6c518bf9919d7b`。经核查，实盘代码未被篡改，前序 8721 字节完整保留且测试通过，作者汇报的哈希字符串系填写笔误/填错。

---

## 2. 回退清零（Zero Fallback Check）

对修改的 6 个核心源码模块全面 grep 目标模式，并核验在缺数据时的控制流：

| 检查模式 | 命中位置 | 缺数据时的流向与处理 | 判定 |
|---|---|---|:---:|
| `or []` | `train_runner.py:127` | `steps = payload.get("steps") or []`。若 steps 为空或长度小于 17，直接返回空窗口列表 `[]`；下游 `sample_batch` 遇到空列表抛出 `ValueError("cannot sample from empty sequence list")`，`load_train_sequences` 抛出 `FileNotFoundError`，严格 fail-closed。 | **通过** |
| `or {}` | 无命中 | — | **通过** |
| `getattr(..., default)` | `adapters_mlx.py:44,51,58,65`<br>`adapters_mlx.py:727,739`<br>`smoke.py:155,842,912` | 仅用于 `_LazyModule` 属性代理、SQLite 账本对象路径解析及 smoke 测试中的能力反射检查，无任何数据兜底或偷跑行为。 | **通过** |
| `if ... is None else` | `train_runner.py:232` | `frac = float(spec.TRAIN_HOLDOUT_WORLD_FRACTION) if holdout_fraction is None else float(holdout_fraction)`。未传时取冻结规范常量 0.10，无随机/越权假数据。 | **通过** |
| `default_` | `core_math.py:86,88`<br>`core_math.py:601`<br>`smoke.py:19,602,721...` | `np.random.default_rng`、`default_mse` 损失函数及 smoke 中默认 Oracle MPC 基准对比对照组，非缺数据兜底。 | **通过** |
| `0.5` | `spec.py:60,64,114,283`<br>`core_math.py`<br>`arms_mlx.py` | 仅为环境转移步长分布权重（k=1 占 0.5）、数学公式系数（高斯核 `exp(-0.5*t^2)`、高斯 NLL、梯形积分 0.5、KL 散度 `-0.5`），无随机成功率或伪造通过逻辑。 | **通过** |
| `base_success_rate` | 无命中 | — | **通过** |
| `preferred_` | 无命中 | — | **通过** |
| `eval_episode` | 无命中 | — | **通过** |
| **批次强校验** | `FakeLinearArm`<br>`MLXArmAAdapter`<br>`MLXArmBAdapter`<br>`MLXArmCAdapter` | 所有臂模型均显式循环检查 `spec.BATCH_REQUIRED_KEYS`（`observations`, `actions`, `dts`），任何一个键缺失均立即抛出 `ValueError`。 | **通过** |
| **步长维度校验** | `arms_mlx.py:527-528` | 显式校验 `if dts.ndim != 1: raise ValueError(...)`，杜绝 2D/3D 步长格式渗入。 | **通过** |

结论：所有修改模块控制流严格遵循 fail-closed 规矩，缺失必要键或维度失配时一律拒绝并报错。

---

## 3. 生产调用点（Production Call Sites）

从入口 `ainerzero.cli:main` 一路排查至执行链路：
- **CLI 生产入口**：`s2-phase1` 子命令映射至 `commands.s2_phase1_command`。
- **模式解析**：`_resolve_default_runner` 统筹各阶段 Runner：
  - `mode == "train"`：使用 `_default_arm_factory`（真实 `adapters_mlx.make_mlx_arm(arm_id)`），调用 `train_runner.run_train_cell`。从真实数据集目录提取长度为 17 的观察、动作与步长，使用 `sample_batch` 组合标准批次进行模型更新，并调用 `adapters_mlx.checkpoint_path` 将真实检查点保存至磁盘。
  - `mode == "plan-select"`：通过 `adapters_mlx.load_trained_model(out_root, a, 42, ledger=ledger)` 真实加载磁盘保存的种子 42 检查点；缺失则立即报错 `RuntimeError("plan-select missing seed 42 checkpoint...")`。后置门槛阶段必须加载全量 9 个真实检查点（3 臂 × 3 种子），缺失即拒。
  - `mode == "dev-eval"` / `mode == "final-eval"`：校验 `dev_ledger.json` 与 `plan_config.json`，同样经由 `adapters_mlx.load_trained_model` 从真实检查点载入模型，真实执行规划评估。
  - `mode == "smoke"`：`smoke.run_smoke(execute_real=True)` 完整执行真实 MLX 原生检查。
- **结论**：生产路径真实加载了检查点，真实传递了实测量与完整数据，不存在仅测试环境注入的情况。

---

## 4. 亲手变异（Isolated Copy Mutations）

变异在隔离副本目录 `/tmp/relay-p181/iso/` 中亲手执行（复制 `src`, `tests`, `pyproject.toml`，并断言 `import ainerzero` 指向 `/tmp/relay-p181/iso/src/ainerzero`）：

| 变异项 / 坏对照 | 变异操作与受测代码 | 预期反应 | 实际结果 | 状态 | 还原后 SHA 比对 |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **坏对照 1：批次缺失 `actions` 键** | 构造缺失 actions 的批次输入 `FakeLinearArm.train_step`；并在隔离副本中移除保护代码使测试变红。 | 正常阻断报错；若移除保护则测试变红 | `FakeLinearArm` 强校验立即阻断抛出 `ValueError: FakeLinearArm.train_step missing required batch key 'actions'`；移除保护后测试 `code=1` 变红。 | **PASSED** | 一致（MATCH） |
| **坏对照 2：`dts` 变为 3D `(B, L, 1)`** | 构造 3D `dts` 输入 `MLXArmAAdapter.train_step`；并在隔离副本中移除 `arms_mlx.py` 保护代码。 | 正常阻断报错；若移除保护则测试变红 | `arm_a_loss_mlx` 强校验立即阻断抛出 `ValueError: arm_a_loss_mlx requires 1-D dts array of shape (L,), got (17, 1)`；移除保护后原生测试变红。 | **PASSED** | 一致（MATCH） |
| **自选变异 3：`adapters_mlx` 缺失 `dts` 键** | 构造缺失 `dts` 批次输入 `MLXArmAAdapter.train_step`；移除 `BATCH_REQUIRED_KEYS` 校验。 | 强校验规范报错；若移除则退化为未捕获 `KeyError` | 原代码抛出 `ValueError: MLXArmAAdapter.train_step missing required batch key 'dts'`；移除保护后退化为未捕获 `KeyError`。 | **PASSED** | 一致（MATCH） |
| **自选变异 5：`arms_mlx` 中 SIGReg 投影方向种子失配** | 修改 `arms_mlx.compute_sigreg_mlx` 中的 RNG 种子为 `9999`，使其与 NumPy 对照脱节。 | SIGReg 对齐误差超出 `1e-4`，测试变红 | `test_native_smoke_self_check_path` 报 `AssertionError: assert 0.003815927276709735 <= 0.0001`，测试彻底变红（FAILED）。 | **PASSED** | 一致（MATCH） |

所有变异项测试完毕后均恢复原文件，SHA256 与修改前严格一致（见 `reports/V9-S2-W8/review/mutation_results.json`）。

---

## 5. 原生 MLX 测试执行原文（Verbatim Native Tests）

依据任务要求与参数 v2 授权，亲自在主工作区执行原生测试：

### 5.1 执行命令
```bash
PYTHONPATH=src .venv/bin/pytest tests/v9/experiments/test_s2_train_native.py tests/v9/experiments/test_s2_production_e2e_native.py --native-mlx -v -s
```

### 5.2 输出原文
```
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0 -- /Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python3
cachedir: .pytest_cache
native-mlx OPT-IN: real MLX/model tests collected; must run under the project CLI lock/RunStore/budget, not bare pytest
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
collecting ... collected 4 items                                                              

tests/v9/experiments/test_s2_train_native.py::test_native_train_steps_and_rollout_error_finite PASSED
tests/v9/experiments/test_s2_train_native.py::test_native_smoke_self_check_path PASSED
tests/v9/experiments/test_s2_train_native.py::test_native_bad_control_dts_3d_fails_arm_a PASSED
tests/v9/experiments/test_s2_production_e2e_native.py::test_native_e2e_train_and_checkpoint_load PASSED

============================== 4 passed in 6.06s ===============================
```

### 5.3 补充验证：原生三套件合计执行
```bash
PYTHONPATH=src .venv/bin/pytest tests/v9/experiments/test_s2_train_native.py tests/v9/experiments/test_s2_learned_planning_native.py tests/v9/experiments/test_s2_production_e2e_native.py --native-mlx -v -s
```
输出：`6 passed in 13.31s`。

### 5.4 参数 v2 `tier1_note_native` 特别说明
- `test_s2_production_e2e_native.py` **只验证检查点存取与极短迭代契约**，不是完整的生产级全量流水线。
- 一级统筹已在临时目录中预演了真实 `measure_real_smoke`，确认了 W8 对批次统一与 MLX 走通的有效性，并已针对预演中发现的臂 A 步速偏慢与动作整数接口开启了后续 W9 优化卡。

---

## 6. 全量默认套件与实盘 artifacts 零改动审计

- **执行方式**：前台 `SIG_DFL+execv` 执行 `PYTHONPATH=.:src .venv/bin/pytest tests/ -ra -v`。
- **执行时间与结果**：
  - 耗时：`1084.82s (0:18:04)`
  - 结果：`3725 passed, 7 deselected, 0 failed`（通过率 100%）。
  - 日志存入 `reports/V9-S2-W8/review/pytest_full.out`。
- **实盘 artifacts 审计（lstat 比对）**：
  - 运行前扫描条目：84,283 项（`artifacts_stat_before.json`）
  - 运行后扫描条目：84,283 项（`artifacts_stat_after.json`）
  - 比对维度：`ctime`、`mtime`、`size`、`ino`、`mode`。
  - `artifacts_diff.json` 结果：
    - `added`: 0
    - `removed`: 0
    - `changed`: 0
    - **差异总数：0**（严格为 0，零写入实盘 artifacts）。

---

## 7. 逐字抽查（Spot Checks）

从作者提交的 `reports/V9-S2-W8/REPORT.md` 中抽取声明与实盘逐字核验（记录于 `spot_checks.json`）：

| # | 报告声明 | 盘上实际位置与内容 | 核查结果 |
|---|---|---|:---:|
| 1 | `arms_mlx.py` Line 527-528：`if dts.ndim != 1: raise ValueError(f"arm_a_loss_mlx requires 1-D dts array of shape (L,), got {dts.shape}")` | `src/ainerzero/v9/experiments/s2/arms_mlx.py:527-528` 逐字一致 | **一致 (MATCH)** |
| 2 | `core_math.py` 新增 `generate_sigreg_directions` 使用 `float32` 生成标准正态投影方向并归一化 | `src/ainerzero/v9/experiments/s2/core_math.py:79-100` 函数定义与 `astype(np.float32)` 逐字一致 | **一致 (MATCH)** |
| 3 | `spec.py` 末尾定义 `BATCH_OBSERVATIONS_KEY = "observations"`, `BATCH_ACTIONS_KEY = "actions"`, `BATCH_DTS_KEY = "dts"`, `BATCH_REQUIRED_KEYS` | `src/ainerzero/v9/experiments/s2/spec.py:321-330` 逐字一致 | **一致 (MATCH)** |
| 4 | `spec.py` 前缀 8721 字节 SHA256 为 `3e36e6ba6e680a6c02930438cf3878b31a5eb23b090e0b040e6c518bf9919d7b` | 实盘真实前缀 SHA256 为 `b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`，严格匹配 `test_s2_spec.py:208`。代码未受损，作者报告文字有误。 | **不符 (REPORT TYPO)** |

---

## 8. 结论与建议

P180 针对 smoke r1 发现的训练批次接口脱节、步长维度失配及 SIGReg 投影对齐问题进行了精准且合规的修复：
1. 统一在 `spec.py` 确立批次标准，`train_runner` 全面接入统一批次并保留 fail-closed 强校验；
2. 三个 MLX 适配器完整接收规范批次，Arm C 宏动作聚合与层级损失计算正确驱动；
3. 坏对照与自选变异均在隔离副本中亲手变红并完美恢复 SHA；
4. 原生 MLX 测试 `4 passed in 6.06s`（三套件 `6 passed in 13.31s`）；
5. 实盘 artifacts 零改动（diff=0）；
6. 发现并纠正作者在报告中对 `spec.py` 前缀哈希的笔误记录（实盘代码指纹严格合规通过 `test_s2_spec.py`）。

**复核结论：`RECOMMEND_ACCEPT`**。
建议统筹予以接收，并推进后续 W9 优化卡。
