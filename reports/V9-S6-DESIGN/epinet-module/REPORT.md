# S6 epinet 模块与测试复核报告

- 任务：`ainerzero.V9.P252`
- 阶段：S6
- 执行者：`gemini-m8k2`（二级执行 agent，非作者）
- 会话指纹：`sess-115f78f0640b`
- 日期：2026-11-14
- 目标：以 `reports/V9-S6-DESIGN/tier1-explore/explore_s6e.py` 原型为准，实现生产级 epinet 模块（`src/ainerzero/v9/experiments/s6/epinet_mlx.py`），提供原生 MLX 测试套件，满足解耦训练基座参数逐位一致、阻断梯度回流、不调用 `world.physics`，并在真实锁下通过测试与 ≥3 个变异击杀。

---

## 1. 交付文件清单与哈希

| 文件路径 | 状态 | SHA256 |
|---|---|---|
| `src/ainerzero/v9/experiments/s6/__init__.py` | 新增 | `1962963784164cc4e66c866345043e15b5c797459717a0f55acad34fbd394b3e` |
| `src/ainerzero/v9/experiments/s6/epinet_mlx.py` | 新增 | `22ff3fa46accd388b4eacda8d56a28631931e734c6a2df30f49af06041f0e1ac` |
| `tests/v9/experiments/test_s6_epinet_mlx.py` | 新增 | `1107ba0d1446a17cef947db65b4dca52dedb140430068016b7df36680747a6ee` |
| `tests/conftest.py` | 修改（仅登记1行） | `b2995117fdb5c688b0a2133f83fa335b75bf7721da64dc7448631136ea093218` |

`tests/conftest.py` 差异仅限于在 `NATIVE_MODULES` 中增加 1 行登记：
```diff
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -258,6 +258,8 @@ NATIVE_MODULES = {
     "test_s5_train_mlx.py": "module-level importorskip mlx.core/mlx.nn (S5 data reading and training loops in MLX)",
     "test_s5_runner_native.py": "runs the S5 pre-freeze runner smoke path (MLX) in a throwaway copy",
     "test_s5_final_native.py": "runs the S5 registered runner end to end on stand-in partitions (MLX) in a throwaway copy",
+    # S6: epinet module (MLX).
+    "test_s6_epinet_mlx.py": "module-level importorskip mlx.core/mlx.nn (S6 epinet MLX module)",
 }
```

---

## 2. 模块架构与解耦机制实现

### 2.1 架构超参数与网络定义
- 超参数对齐原型：`DZ = 8`, `KZ = 8`, `PRIOR = 1.0`, `EPI_HID = 32`。
- `Epi` 类：
  - 两层 MLP：输入为 `DZ + 32`，隐藏层 `EPI_HID`（带 `nn.relu`），输出层维度 `1`（无激活函数，纯线性输出）。
  - 权重初始化采用正态截断 `std=0.02`，偏置全 0。
- `EpiDynamics` 类：
  - 组合基座动力学 `self.base = Dynamics("L-int")`、`self.epi = Epi(...)`、以及 `self.prior = Epi(...)`。
  - 先验网络在初始化时调用 `self.prior.freeze()` 冻结参数。
  - `hidden_out(p, v)`：重用基座 `messages` 一次性得到 `(hid, o, logits)`，其中 `hid` 为拼接消息特征（形状 `[B, 32]`），`o` 为基座预测，`logits` 为未过 sigmoid 的预测。
  - `__call__(p, v)`：直接消费 `logits`，避免多次调用 `messages` 产生冗余计算图与数值漂移。
  - `epi_predict(p, v, z)`：
    - `hid, o, _ = self.hidden_out(p, v)`
    - `hs = mx.stop_gradient(hid)`：**彻底阻断梯度回流到基座网络**。
    - `pred = mx.stop_gradient(o) + self.epi(hs, z) + PRIOR * mx.stop_gradient(self.prior(hs, z))`
    - 返回 `pred`（形状 `[B, 1]`）与 `sigmoid(pred)`。

### 2.2 解耦训练与梯度隔离
- `epinet_step_loss(model, p, v, labels, z)`：
  - 二元交叉熵（带 logits 稳定性处理）：`mx.maximum(pred, 0) - pred * labels + mx.log1p(mx.exp(-mx.abs(pred)))`。
- `total_loss(model, pool, z_batch, weights)`：
  - 基座损失：`l_base, _ = rollout_loss(model.base, pool, mx.array(weights))`
  - epinet 损失：`l_epi = epinet_step_loss(model, p, v, labels, z_batch)`
  - 总损失：`loss = l_base + l_epi`
- **基座参数逐位一致性（Bitwise Parity）**：
  - 由于 `hs` 与 `o` 均被 `mx.stop_gradient` 包裹，`l_epi` 关于 `model.base.parameters()` 的雅可比为零矩阵。
  - `prior` 处于冻结状态（`freeze()`），无梯度。
  - 经由 `nn.value_and_grad(model, total_loss_fn)` 计算得到的基座参数梯度，与单独在 `rollout_loss` 上计算的基座梯度差值为 `0.0`（逐位一致）。
  - 在完全相同的初始种子下，解耦训练后的 `EpiDynamics.base` 参数与普通 `Dynamics("L-int")` 训练后的参数最大绝对差严格为 `0.0`。

### 2.3 评估接口与物理隔离
- `spread(model, pool, seed=0)`：
  - 固定 MLX PRNG 种子抽样生成 `KZ=8` 个隐向量 $z_k \sim \mathcal{N}(0, I)$。
  - 对每个世界类型（`contact`、`wall`、`free`）分别评估 `KZ` 个预测并计算方差 `var = mean(preds^2) - mean(preds)^2`。
  - 纯模型前向计算，**AST 严格验证模块内未导入也未调用 `world.physics`**。

---

## 3. 原生测试记录（持锁运行）

运行命令：
```bash
.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -v --native-mlx tests/v9/experiments/test_s6_epinet_mlx.py
```

实测输出：
```text
lock held by 53990
============================= test session starts ==============================
platform darwin -- Python 3.12.2, pytest-9.1.1, pluggy-1.6.0 -- /Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python
cachedir: .pytest_cache
native-mlx OPT-IN: real MLX/model tests collected; must run under the project CLI lock/RunStore/budget, not bare pytest
rootdir: /Users/mac/AinerWorkFlow/AinerZero
configfile: pyproject.toml
collecting ... collected 8 items

tests/v9/experiments/test_s6_epinet_mlx.py::test_epinet_zero_or_none_bitwise_identical_to_base_network PASSED [ 12%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_decoupled_training_base_parameters_bitwise_identical_to_plain_rollout_loss PASSED [ 25%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_prior_network_remains_frozen_after_training PASSED [ 37%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_stop_gradient_blocks_gradients_into_base_network PASSED [ 50%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_spread_reproducible_with_same_seed_and_varies_with_different_seed PASSED [ 62%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_training_loss_decreases_and_reproducible_under_same_seed PASSED [ 75%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_non_finite_loss_raises_error PASSED [ 87%]
tests/v9/experiments/test_s6_epinet_mlx.py::test_epinet_module_does_not_call_world_physics_ast PASSED [100%]

============================== 8 passed in 1.33s ===============================
```

---

## 4. 变异测试（在隔离副本中测试击杀）

在独立临时工作区 `/tmp/epinet_mutation_dir` 下（配置 `PYTHONPATH=/tmp/epinet_mutation_dir/src`）执行基线与 3 处变异注入验证：

### 4.1 基线验证（BASELINE）
- 结果：`8 passed in 0.85s`，0 失败。

### 4.2 变异 1：去掉 `stop_gradient`
- 注入：在 `epi_predict` 中去掉 `hs = mx.stop_gradient(hid)`，直接使用 `hs = hid`。
- 预期：梯度回流进基座网络，解耦失效，基座参数不再与单独 `rollout_loss` 一致。
- 实测结果：**2 项测试失败（成功击杀）**
  - `FAILED tests/v9/experiments/test_s6_epinet_mlx.py::test_decoupled_training_base_parameters_bitwise_identical_to_plain_rollout_loss`
  - `FAILED tests/v9/experiments/test_s6_epinet_mlx.py::test_stop_gradient_blocks_gradients_into_base_network`

### 4.3 变异 2：先验网络不冻结
- 注入：在 `EpiDynamics.__init__` 中注释掉 `self.prior.freeze()`。
- 预期：先验网络参数被更新，违背固定随机特征假设。
- 实测结果：**1 项测试失败（成功击杀）**
  - `FAILED tests/v9/experiments/test_s6_epinet_mlx.py::test_prior_network_remains_frozen_after_training`

### 4.4 变异 3：`spread` 未固定 PRNG 种子
- 注入：在 `spread()` 中注释掉 `mx.random.seed(seed)`。
- 预期：相同种子重复调用无法确定性复现方差。
- 实测结果：**1 项测试失败（成功击杀）**
  - `FAILED tests/v9/experiments/test_s6_epinet_mlx.py::test_spread_reproducible_with_same_seed_and_varies_with_different_seed`

---

## 5. 规则与约束核对

1. **未跨越阶段或启动登记运行**：未写 `artifacts/v9/s5/runs/` 或 `artifacts/v9/s6/runs/`，未跑登记运行。
2. **纯持锁复用**：持 `artifacts/locks/m0-worker.lock` 排队，不抢锁，不绕过锁。
3. **隔离与文件范围**：仅修改 `tests/conftest.py` 1 行，其余修改严格在 `src/.../s6/` 与 `tests/.../test_s6_...` 中，未修改任何 `s4/` 文件。
4. **无未验证项**：8 项测试全部通过，3 个变异测试均已验证击杀。
