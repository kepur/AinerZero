# E1 修复（r3）：消除静默默认半径与强化异常阻断报告（ainerzero.V9.P79）

- **执行者**：gemini-b9f2（二级执行 agent · MLX CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P79`（第 3 轮修复 · r3）
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 79 步（E1 训练目标修复与物理一致性）
- **依据与打回意见响应**：
  - 一级统筹（Claude）r2 验收打回裁定：
    1. **消除静默默认半径**：
       - `arms_net.py` 的 `_prior_scene_step` 缺半径时退回 0.1；
       - `train_runner.py:150` 缺 `bounding_sphere_radius` 时退回 0.5；
       - 两处默认值不一致且静默掩盖数据缺陷，必须彻底消除，改为缺半径就抛出异常（`KeyError` 或 `ValueError`），并明确指明缺少哪个物体。
    2. **契约显式化**：
       - `training_target` 与 `predict` 的 `radii_by_body` 必须强制要求，缺失时必须抛出异常。
    3. **双路径异常测试**：
       - 新增测试用例：缺半径时训练路径（`training_target`）与预测路径（`predict`）均抛出异常。
    4. **坏对照变红验证**：
       - 在独立隔离副本中恢复默认 0.1，证明新测试严格变红（FAILED）。
- **文件改动范围**：
  - `src/ainerzero/v9/experiments/e1/arms_net.py`
  - `src/ainerzero/v9/experiments/e1/train_runner.py`
  - `tests/test_e1_arms_net.py`
  - `tests/test_e1_train_runner.py`
  - 交付目录：`reports/V9-E1TF/gemini-b9f2/r3/`（含 `before/` 原始备份）

---

## 1. 静默默认半径缺陷根因与修复实现

### 1.1 r2 静默默认半径缺陷分析
在 r2 中，虽然实现了场景级统一推进函数 `_prior_scene_step`，但存在两处隐蔽的 fallback 默认值：
1. `arms_net.py:184`（`_prior_scene_step`）：
   ```python
   r = float(radii_by_body[name]) if (radii_by_body is not None and name in radii_by_body) else 0.1
   ```
2. `train_runner.py:150`（`build_training_windows`）：
   ```python
   if b_name in active_bodies and "bounding_sphere_radius" in active_bodies[b_name]:
       radii_by_body[b_name] = float(active_bodies[b_name]["bounding_sphere_radius"])
   else:
       radii_by_body[b_name] = 0.5
   ```
**后果**：若输入序列或调用方漏传包围球半径，训练侧会静默使用 $r=0.5$，而预测/先验侧会静默使用 $r=0.1$。两处半径差异高达 5 倍，导致先验碰撞检测面出现严重分歧，破坏物理残差定义的严格自洽性。

### 1.2 修复方案与代码变更

#### A. `src/ainerzero/v9/experiments/e1/arms_net.py`
1. `_prior_scene_step`：
   - 检查 `radii_by_body` 是否为 `None`，若为 `None` 立即抛出 `ValueError(f"radii_by_body cannot be None in _prior_scene_step; missing radii for bodies: {body_names}")`；
   - 逐物体检查 `name not in radii_by_body or radii_by_body[name] is None`，若缺失立即抛出 `KeyError(f"Missing radius for body '{name}' in radii_by_body: ...")`。
2. `training_target` 与 `scene_training_targets`（Arm 3 与 Arm 6）：
   - 显式要求 `radii_by_body`，若未传入且实例未绑定合法半径，抛出 `ValueError`；
   - 若传入的字典缺少目标物体，抛出 `KeyError(f"Missing radius for body '{body_name}' in radii_by_body")`。
3. `predict`（Arm 3 与 Arm 6）：
   - 显式声明 `requires_physical_radii = True`；
   - 检查 `radii_by_body` / `radii` / 实例属性，若均缺失抛出 `ValueError`；若缺少某物体抛出 `KeyError`；
   - 支持从 `eval_runner` 的 `student_ep["active_bodies"]` 显式解包真实包围球半径，保证全流程一致。

#### B. `src/ainerzero/v9/experiments/e1/train_runner.py`
在 `build_training_windows` 中彻底移除 `else: radii_by_body[b_name] = 0.5`，改为：
```python
if (
    b_name in active_bodies
    and "bounding_sphere_radius" in active_bodies[b_name]
    and active_bodies[b_name]["bounding_sphere_radius"] is not None
):
    radii_by_body[b_name] = float(active_bodies[b_name]["bounding_sphere_radius"])
else:
    raise KeyError(
        f"Missing bounding_sphere_radius for body '{b_name}' in sequence '{seq_id}' "
        f"(active_bodies keys: {list(active_bodies.keys())})"
    )
```

---

## 2. 数学定义与物理自洽性（严格共用物理先验）

在所有网络臂中严格贯彻一级统筹的数学定义：
- **② PureNetArm**：
  $$\text{predict}(s_t) \rightarrow s_{t+1} = s_t + f_\theta(h_t)$$
  $$\text{training\_target}(s_t, s_{t+1}) = s_{t+1} - s_t$$
- **③ PriorResidualArm**：
  $$\text{predict}(s_t) \rightarrow s_{t+1} = F_{\text{prior}}(s_t; \phi_0, \text{statics}, R) + f_\theta(h_t)$$
  $$\text{training\_target}(s_t, s_{t+1}) = s_{t+1} - F_{\text{prior}}(s_t; \phi_0, \text{statics}, R)$$
- **⑥ IdentifyResidualArm**：
  $$\text{predict}(s_t) \rightarrow s_{t+1} = F_{\text{prior}}(s_t; \hat{\phi}, \text{statics}, R) + P_{\perp}(\hat{\phi}) \cdot f_\theta(h_t)$$
  $$\text{training\_target}(s_t, s_{t+1}) = P_{\perp}(\hat{\phi}) \cdot (s_{t+1} - F_{\text{prior}}(s_t; \hat{\phi}, \text{statics}, R))$$

所有物理推进和正交补投影严格调用同一私有实现 `_prior_scene_step` 与 `_apply_correction`。

---

## 3. 往返一致性与异常阻断测试结果

### 3.1 往返一致性（多物体、地面、对心碰撞、半径 $r_a=0.25, r_b=0.30$）
| 臂 ID | 评测项 | 评测物体 | 往返 L2 误差 | 阈值门槛 | 判定 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **②** PureNetArm | 纯状态增量往返 | `body_a` | $2.00 \times 10^{-8}$ | $< 10^{-6}$ | **PASS** |
| **②** PureNetArm | 纯状态增量往返 | `body_b` | $5.27 \times 10^{-8}$ | $< 10^{-6}$ | **PASS** |
| **③** PriorResidualArm | 先验多体碰撞残差往返 | `body_a` | $0.0$ | $< 10^{-6}$ | **PASS** |
| **③** PriorResidualArm | 先验多体碰撞残差往返 | `body_b` | $0.0$ | $< 10^{-6}$ | **PASS** |
| **⑥** IdentifyResidualArm | 辨识投影多体残差往返 | `body_a` | $0.0$ | $< 10^{-6}$ | **PASS** |
| **⑥** IdentifyResidualArm | 辨识投影多体残差往返 | `body_b` | $0.0$ | $< 10^{-6}$ | **PASS** |
| **⑥** IdentifyResidualArm | 雅可比正交性 $|J^T y|_\infty$ | `body_a` / `body_b` | $0.0$ | $< 10^{-8}$ | **PASS** |

### 3.2 新增异常测试验证（r3）
- `tests/test_e1_arms_net.py::test_residual_arms_missing_radius_raises_exception`：
  - `_prior_scene_step` 缺 `radii_by_body` 抛出 `ValueError`；
  - `_prior_scene_step` 缺指定物体抛出 `KeyError("Missing radius for body 'body_a'")`；
  - 臂 ③⑥ `training_target` 缺半径抛出 `ValueError`/`KeyError`；
  - 臂 ③⑥ `scene_training_targets` 缺半径抛出 `ValueError`/`KeyError`；
  - 臂 ③⑥ `predict` 缺半径抛出 `ValueError`/`KeyError`。
- `tests/test_e1_train_runner.py::test_build_training_windows_missing_bounding_radius_raises_key_error`：
  - `build_training_windows` 当输入数据缺少 `bounding_sphere_radius` 时立即抛出 `KeyError("Missing bounding_sphere_radius for body 'ball'")`。

---

## 4. 20 步训练后参数差异性验证（seed=42）

网络结构严格冻结为 6150 个参数。在相同数据与种子下训练 20 步后，网络权重哈希严格两两互异：
- **Arm 2 (PureNet)**: `ce4d185c06f7332355d404b4be794d02c661b8ffcfb46a1d50a1ae7ea75ce2c7`
- **Arm 3 (PriorResidual)**: `66b6adbcbeba75d0bbaddba21d06802277f48f6d1d38d08cce84a6ab3f65e4e5`
- **Arm 6 (IdentifyResidual)**: `8d0502cfbb51219a1affd7e5dc52cecd942e7cd20404fc8d7e621e911055b89a`
- **两两互异检验**: `len({sha2, sha3, sha6}) == 3`（通过）。

---

## 5. 5 组隔离坏对照实验证明（证明测试变红）

在独立临时隔离目录 `/tmp/e1_tf_r3_mutants/` 中执行独立变异测试，每个变异均在隔离副本中打印实际执行文件 `__file__`，并捕获断言失败：

| 坏对照 ID | 变异描述 | 目标文件路径 (`__file__`) | 失败测试用例 | 返回码 | 变红证据 / 失败信息 |
| :--- | :--- | :--- | :--- | :---: | :--- |
| `mutant_1_restore_default_01_in_prior_scene_step` | 恢复 `_prior_scene_step` 缺半径时默认 0.1（**r3 核心坏对照**） | `/tmp/e1_tf_r3_mutants/mutant_1_restore_default_01_in_prior_scene_step/src/ainerzero/v9/experiments/e1/arms_net.py` | `test_residual_arms_missing_radius_raises_exception` | **1 (RED)** | `Failed: DID NOT RAISE <class 'ValueError'>` |
| `mutant_2_restore_default_05_in_train_runner` | 恢复 `train_runner` 缺 `bounding_sphere_radius` 时默认 0.5 | `/tmp/e1_tf_r3_mutants/mutant_2_restore_default_05_in_train_runner/src/ainerzero/v9/experiments/e1/train_runner.py` | `test_build_training_windows_missing_bounding_radius_raises_key_error` | **1 (RED)** | `Failed: DID NOT RAISE <class 'KeyError'>` |
| `mutant_3_arm3_target_reverted_to_delta` | ③ 的目标改回 $s_{t+1} - s_t$ | `/tmp/e1_tf_r3_mutants/mutant_3_arm3_target_reverted_to_delta/src/ainerzero/v9/experiments/e1/arms_net.py` | `test_arms_training_target_predict_roundtrip_consistency` | **1 (RED)** | `AssertionError: Arm 3 body_a roundtrip error 1.333141 >= 1e-6` |
| `mutant_4_arm6_no_projection` | ⑥ 去掉正交补投影（直接返回未投影残差） | `/tmp/e1_tf_r3_mutants/mutant_4_arm6_no_projection/src/ainerzero/v9/experiments/e1/arms_net.py` | `test_arms_training_target_predict_roundtrip_consistency` | **1 (RED)** | `AssertionError: Arm 6 body_a orthogonality violated: 0.010749 >= 1e-8` |
| `mutant_5_train_runner_bypasses_arm_target` | `train_runner` 绕开 `training_target` 强制用增量 | `/tmp/e1_tf_r3_mutants/mutant_5_train_runner_bypasses_arm_target/src/ainerzero/v9/experiments/e1/train_runner.py` | `test_training_20_steps_arms_parameter_sha_pairwise_different` | **1 (RED)** | `AssertionError: Arm 2 and Arm 3 parameter SHA match unexpectedly` |

---

## 6. 测试全集验证

执行命令：
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_arms_net.py tests/test_e1_train_runner.py -v
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -v
```
- **核心模块测试**：20/20 PASSED（用时 0.74s）；
- **E1 全量测试集**：126/126 PASSED（用时 16.07s，无回归）。
