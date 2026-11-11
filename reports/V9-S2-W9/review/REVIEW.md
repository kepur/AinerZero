# P183 非作者复核 · S2 集成 W9（P182）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-k8d4`（二级执行层；非 P182 作者；P182 作者为一级 `claude`）
- **被复核任务：** `ainerzero.V9.P182`（reported）
- **复核日期：** 2026-11-08
- **任务目标：** 非作者只读审查 S2 集成 W9（臂 A 训练批次并行化、整数动作接口、规划空间 latents 口径、smoke 预算公式读取 spec，以及参数 v2 追加核对的 15 h 预算落地）。在隔离副本中亲手复现坏对照与自选变异，运行原生测试并在临时目录独立复跑 smoke 预演，执行全量回归并核对实盘 artifacts 零改动。

---

## 1. 范围（Scope）

- **W9 声明修改文件**（共 6 个模块）：
  - `src/ainerzero/v9/experiments/s2/arms_mlx.py`
  - `src/ainerzero/v9/experiments/s2/adapters_mlx.py`
  - `src/ainerzero/v9/experiments/s2/smoke.py`
  - `tests/conftest.py`
  - `tests/v9/experiments/test_s2_arm_a_batched_native.py`
  - `tests/v9/experiments/test_s2_train_native.py`
- **SHA256 逐一校验**：
  实盘盘上 6 个文件与 `reports/V9-S2-W9/sha256.txt` 逐字 100% 完全匹配：
  - `arms_mlx.py`: `be9ca941cb6bfa31906d40f203b307b57786942583e355ad73fb324443afe59f`
  - `adapters_mlx.py`: `60b02f091f5bcc275835c506c8dfd2af9fa0b0287b8314100b2ebfbe166a0dcc`
  - `smoke.py`: `575291db4926f723f7db060fc529ea1f92f1f3f260a763813e803679f6c7db9b`
  - `tests/conftest.py`: `6f2b3c70daf78d53c4ef89063769cc2b04967df5824f91e12e56bbdc63deac0a`
  - `test_s2_arm_a_batched_native.py`: `f31ed95c6c60ef288c07b7d57b7a87d9a8e8f4ef0db060d04931c2cd5d1abb05`
  - `test_s2_train_native.py`: `7c10bd3da252fb4405a6fc34770d5c7ff88e19de5e7b1668310a037300e2bfed`
- **补丁核对**：
  `git diff df6da45~1 df6da45 -- src/ tests/` 与作者报告提交的补丁 `reports/V9-S2-W9/git_diff.patch` 逐文件比对，差异为 0（补丁中文件顺序为 adapters, arms, smoke, conftest, train_native, arm_a_batched_native，各文件 hunk 逐字节一致）。
- **工作树中其他文件说明**：
  - `src/ainerzero/v9/experiments/s2/spec.py`: 由用户在 11-08 批准 S2 预算至 15 h（详见第 6 节）；
  - `reports/V9-S2-DESIGN/HANDOFF-20261107-0500.md`: 一级 11-08 03:2x 交接文档记录；
  - `reports/` 下的历史文件（`V9-B3-mlx-unitcost/`, `V9-E1...`, `V9-P44/` 等）：均属既往任务历史记录，非本任务改动；
  - 未触碰任何受保护文件（`commands.py`, `eval_runner.py`, `learned_planning.py`, `planner.py`, `probe_eval.py`, `artifacts/` 等）。

---

## 2. 回退清零（Zero Fallback Check）

在 W9 涉及的源码模块中全面 grep 目标模式，并核验缺数据时的控制流：

| 检查模式 | 命中位置 | 缺数据时的流向与处理 | 判定 |
|---|---|---|:---:|
| `or []` | 无命中 | — | **通过** |
| `or {}` | 无命中 | — | **通过** |
| `getattr(..., default)` | `adapters_mlx.py:729,741`<br>`smoke.py:155,848,918`<br>`conftest.py:287,298` | 仅用于 SQLite 账本路径探测（未找到则后续校验报错）、ForwardCounter 反射检查及测试清理 session 状态字典，无任何数据兜底或偷跑行为。 | **通过** |
| `if ... is None else` | `conftest.py:95` | 仅用于测试框架白名单切换，无生产数据回退。 | **通过** |
| `default_` | `smoke.py`<br>`test_s2_arm_a_batched_native.py:18,83` | `smoke.py` 中用于记录 default Oracle MPC 对照组结果；测试文件中为 `np.random.default_rng` 标准 PRNG，非缺数据兜底。 | **通过** |
| `0.5` | `arms_mlx.py:415,418,460,559,662` | 均为数学公式常量：核函数权重、MSE 损失系数 `0.5`，以及高斯 KL 散度闭式解常数项 `- 0.5`，无随机伪造成功率。 | **通过** |
| `base_success_rate` | 无命中 | — | **通过** |
| `preferred_` | 无命中 | — | **通过** |
| `eval_episode` | 无命中 | — | **通过** |
| **维度与输入强校验** | `arms_mlx.py:637-641`<br>`adapters_mlx.py:35-38` | `arm_a_loss_mlx_batched` 显式校验 `if obs_seq.ndim != 3 or actions_onehot.ndim != 3 or dts.ndim != 2: raise ValueError(...)`，严格 fail-closed。`_as_action` 仅规范标量维度，不产生缺省数据。 | **通过** |

---

## 3. 生产调用点（Production Invocation Points）

从 CLI 入口一路追踪至 MLX 执行器与检查点：
1. `ainerzero.cli.main` 解析 `s2-phase1` 模式，分发给 `s2_phase1_command`；
2. `commands.py`:
   - `_smoke_runner` 真实调用 `smoke.run_smoke(..., execute_real=True)`；
   - `_train_runner` 调用 `adapters_mlx.make_mlx_arm(arm_id)` 实例化模型，读取账本分配步数并调用 `train_runner.run_train_cell`；
   - `_dev_eval_runner` 与 `_final_eval_runner` 严格调用 `adapters_mlx.load_trained_model(out_root, a, s, ledger=ledger)`；
3. `adapters_mlx.load_trained_model`:
   - 计算实盘检查点哈希 `_sha256_file(ckpt)`；
   - 对比 SQLite 账本登记的 SHA `ledger_checkpoint_sha(lp, arm, seed)`，若不一致直接抛出 `ValueError("checkpoint sha mismatch...")`；
   - 模型加载检查点 `model.load(ckpt)` 并验证不挂接外部计数器；
4. `predict_l1` 调用链路：
   - 生产环境规划器与 smoke 测试均通过 `predict_l1(z, a, dt)` 交互；
   - W9 的 `_as_action(a)` 在单样本路径将 Python int / numpy scalar 规整为 `shape (1,)`，使得单步 CEM 能够顺利对整数动作计算后验/前向残差，不再报 `AttributeError: 'int' object has no attribute 'ndim'`；
5. `latents` 口径：
   - `MLXArmAAdapter.latents` 改为在 `h0 = zeros` 条件下提取后验均值，输出空间维度与 `spec.ARM_DIMS["arm_a"]["latent_dim"]`（32 维）一致，且与 `encode` 处于同一规划潜空间，支持后续批量操作。

---

## 4. 亲手变异（Manual Mutations in Isolated Environment）

在隔离目录 `/tmp/s2_w9_mutation_env` 中完整复制 `src/`、`tests/` 与 `pyproject.toml`，并断言 `import ainerzero` 解析到副本目录：
`assert "/tmp/s2_w9_mutation_env/src" in ainerzero.__file__`（断言通过）。

逐一进行 5 处变异测试（4 处卡面坏对照 + 1 处自选变异），每处均变红失败，还原后核验 SHA256 100% 恢复：

| # | 变异名称与操作 | 目标文件 | 变异后测试表现 (RED) | 还原 SHA 校验 |
|---|---|---|---|:---:|
| 1 | **卡面坏对照 1：3D dts 报错匹配回退**<br>将 `test_s2_train_native.py` 的 match 正则回退为仅匹配 W8 的 `"1-D dts array of shape"` | `tests/v9/experiments/test_s2_train_native.py` | **FAILED (RED)**: AssertionError: Pattern `'1-D dts array of shape'` does not match `'batched Arm A loss needs obs (B,T,D), actions (B,T,A), dts (B,T); got ...'` | **恢复 (MATCH)** |
| 2 | **卡面坏对照 2：批次并行损失逻辑损坏**<br>在 `arm_a_loss_mlx_batched` 中移除 `mean_over` 过冲项 | `src/ainerzero/v9/experiments/s2/arms_mlx.py` | **FAILED (RED)**: AssertionError: `abs(float(l_ref.item()) - float(l_bat.item())) <= 1e-4` 失败 | **恢复 (MATCH)** |
| 3 | **卡面坏对照 3：整数动作接口回退**<br>将 `_as_action(a)` 回退为预演 bug 状态（直接返回 raw int，不转 array） | `src/ainerzero/v9/experiments/s2/adapters_mlx.py` | **FAILED (RED)**: AttributeError: `'int' object has no attribute 'ndim'` | **恢复 (MATCH)** |
| 4 | **卡面坏对照 4：臂 A 潜空间回退为 E1 特征**<br>将 `MLXArmAAdapter.latents` 回退为 `self.model.encode(arr)` | `src/ainerzero/v9/experiments/s2/adapters_mlx.py` | **FAILED (RED)**: AssertionError: `lat.shape == (5, 32)` 失败（实际返回 (5, 128)） | **恢复 (MATCH)** |
| 5 | **自选变异 5：批量损失漏加 Free Bits**<br>在 `arm_a_loss_mlx_batched` 中直接取 KL 均值，不施加 `maximum(..., float(spec.ARM_A_FREE_BITS))` | `src/ainerzero/v9/experiments/s2/arms_mlx.py` | **FAILED (RED)**: AssertionError: 与逐条参考实现的损失差 `abs(l_ref - l_bat) <= 1e-4` 失败 | **恢复 (MATCH)** |

详细变异记录见 `reports/V9-S2-W9/review/mutations_summary.json`。

---

## 5. 原生测试与临时目录 smoke 预演（Native Tests & Rehearsal）

### 5.1 原生用例执行
以 `--native-mlx` 运行 W9 全部原生用例：
```bash
.venv/bin/pytest tests/v9/experiments/test_s2_arm_a_batched_native.py tests/v9/experiments/test_s2_train_native.py tests/v9/experiments/test_s2_learned_planning_native.py --native-mlx -v
```
- **结果：11 passed in 14.06s**（`test_s2_arm_a_batched_native.py` 6 条全通，3.12s）。

### 5.2 临时目录 smoke 预演复跑
在临时目录调用 `smoke.measure_real_smoke` 进行全流程预演：
- **总耗时：** `191.6 s`（严格低于 1200 s 上限，比作者第三次预演的 208 s 更快）；
- **reasons：** `[]`（完全为空，零报警）；
- **单步耗时（并行批量化效果显著）：**
  - **Arm A:** `0.1125 s`（pre-W9 逐条版本为 `5.76 s`，**加速比达 51.2 倍**，且已快于 B 臂与 C 臂）；
  - **Arm B:** `0.1899 s`；
  - **Arm C:** `0.2479 s`；
- **规划回合中位数：** Arm A 5.38 s，Arm B 4.35 s，Arm C 2.63 s；
- **Step 3 短训自检：** 全部通过（`all_passed: True`）；
- **Step 4 Oracle 熔断：** `passed: True, success_rate: 1.0, fuse_triggered: False`；
- **输出原文：** 详见 `reports/V9-S2-W9/review/smoke_rehearsal_review_out.txt`。

---

## 6. 参数 v2 追加审核（15 h 预算落地）

参数 v2 明确要求复核用户 11-08 批准 S2 预算至 15 h 后的改动：
1. **用户授权凭证**：
   `RESEARCH_LOG.md` 包含条目 `R20261108-S2-budget-15h`，明确记录用户审批「批到 15 小时」。
2. **`spec.py` 只追加核验**：
   - 原 10 h 常量（第 167-179 行）原样保留，字节零改动；
   - 第 330-338 行末尾追加新常量覆盖原值：
     - `TOTAL_ACTUAL_WALLCLOCK_HOURS = 15.0`
     - `TOTAL_ACTUAL_WALLCLOCK_SECONDS = 54_000`
     - `BUDGET_HYPERPARAM_SELECTION_SECONDS = 2_400`
     - `BUDGET_DEV_EVAL_SECONDS = 36_000`
     - `BUDGET_FINAL_EVAL_SECONDS = 9_000`
   - `test_s2_spec.py::test_spec_existing_prefix_byte_for_byte_unchanged` 测试通过（断言前序字节完全一致）。
3. **4 条用例更新审查**：
   - `test_s2_spec.py`：测试严格匹配 15 h 与新预算常数；
   - `test_s2_lifecycle.py` 用例 (c)：基于 `TOTAL_ACTUAL_WALLCLOCK_SECONDS` 动态构造边界与溢出条件，测试严格保留了对边界接纳与超出拒绝的强判定，**未被削弱成恒真（No Tautology）**；
   - `test_s2_smoke_budget.py` dev 超额用例：`plan_times` 更新至 4.0 s（推算 dev 45,000 s > 36,000 s 上限），严格测试超额失败并命名 dev；
   - 上述用例在内的 47 条测试 `47 passed in 34.42s` 全通。

---

## 7. 全量默认套件与实盘 artifacts 零改动审计

- **执行方式**：前台 `SIG_DFL+execv` 执行（通过 `relay exec --every 120` 维持心跳与墙钟监督）：
  ```bash
  python3 /Users/mac/AinerWorkFlow/AinerRelay/bin/relay exec ainerzero.V9.P183 --agent gemini-k8d4 --every 120 -- python3 /tmp/run_pytest_full.py
  ```
- **测试结果**：
  - 用时：`1095.31 s (0:18:15)`
  - 统计：`3725 passed, 7 deselected, 0 failed`（通过率 100%）。
  - 日志存入 `reports/V9-S2-W9/review/pytest_full_tail.txt`。
- **实盘 artifacts 审计（lstat 前后比对）**：
  - 测试前扫描：84,283 项（`reports/V9-S2-W9/review/artifacts_stat_before.json`）
  - 测试后扫描：84,283 项（`reports/V9-S2-W9/review/artifacts_stat_after.json`）
  - 比对维度：`ctime`、`mtime`、`size`、`ino`、`mode`
  - 差异汇总（`reports/V9-S2-W9/review/artifacts_diff.json`）：
    - `added`: 0
    - `removed`: 0
    - `changed`: 0
    - **实盘差异严格为 0（零写入）**。

---

## 8. 逐字抽查（Spot Checks）

从作者 `reports/V9-S2-W9/REPORT.md` 中随机抽取 4 处声明与实盘代码逐字比对（详见 `reports/V9-S2-W9/review/spot_checks.json`）：

| # | 报告声明 | 盘上实际位置 | 核查结果 |
|---|---|---|:---:|
| 1 | `arms_mlx.arm_a_loss_mlx_batched`：批次维度并行推进 GRU/prior/posterior，时间求均值后各施加 free bits，取批次均值；原函数保留作为参考。 | `src/ainerzero/v9/experiments/s2/arms_mlx.py:514-606, 627-681` | **一致 (MATCH)** |
| 2 | `_as_action`：三个臂 `predict_l1` 单样本路径把 Python int 或 numpy 标量转成 (1,) 数组；one-hot 和索引数组保持原样。 | `src/ainerzero/v9/experiments/s2/adapters_mlx.py:35-38, 211, 370, 592` | **一致 (MATCH)** |
| 3 | `MLXArmAAdapter.latents`：改为在零 GRU 状态下取后验均值，与 `encode` 处于同一规划潜空间，支持批量；原先返回 128 维 E1 特征。 | `src/ainerzero/v9/experiments/s2/adapters_mlx.py:236-244` | **一致 (MATCH)** |
| 4 | `smoke.check_smoke_budget`：dev 与 final 推算改读 spec；曲线倍数按 `N_FWD_DEV_LEVELS` 计算，回合数读 spec 常量。 | `src/ainerzero/v9/experiments/s2/smoke.py:365-389` | **一致 (MATCH)** |

---

## 9. 结论与建议

W9 补丁在保证数学语义一致性的前提下，成功实现了臂 A 训练的批次并行化（单步训练耗时从 5.76 s 骤降至 0.11 s，加速超 50 倍），修复了整数动作传参缺陷与潜空间维度不合规问题，并在 spec 中合规追加了用户批准的 15 h 预算常数。
所有卡面坏对照与自选变异均在隔离副本中验证变红并恢复，原生测试全通，临时目录 smoke 预演 191.6 s 零报警通过，全量测试 0 failed，实盘 artifacts 零改动。

**复核结论：`RECOMMEND_ACCEPT`**。
建议统筹予以接收，并推进后续 S2 r2 冻结与 smoke 运行。
