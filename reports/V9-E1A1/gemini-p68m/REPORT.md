# E1-A1 无网络臂实现与测试报告（ainerzero.V9.P68）

- **执行者**：gemini-p68m（二级执行 agent · CPU / NumPy）
- **任务 ID**：`ainerzero.V9.P68`
- **对应阶段**：AinerZero V9 落地 · 轨道 P S1–S2 实验 · 第 68 步（E1-A1 无网络臂）
- **依据协议**：
  - `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-A1
  - 预登记 r3 §2（臂表：①④⑤⑦）
  - 已验收依赖：`ainerzero.V9.P66`（`e1/metrics.py`）、`ainerzero.V9.P67`（`e1/prior.py`、`e1/jacobian.py`）
  - E0 隐藏参数范围：`AnimeWorldZero/python/animeworld/e0/hidden_params.py:18-24`
  - 符号发现复用：`src/ainerzero/v9/mechanism/discovery.py`（`WeakFormSTLSQ`、`BasisTermSpec`）
- **文件改动范围**：
  - 新增：`src/ainerzero/v9/experiments/e1/arms_nonnet.py`
  - 新增：`tests/test_e1_arms_nonnet.py`
  - 导出更新：`src/ainerzero/v9/experiments/e1/__init__.py`
  - 交付成果：`reports/V9-E1A1/gemini-p68m/`

---

## 1. 统一接口与各臂设计

全模块严格在 **纯 CPU / NumPy** 环境下运行，零训练、零网络权重，不依赖 GPU。
统一对外接口：
```python
predict(observed_prefix, static_env, n_future) -> ArmPrediction
```
返回值 `ArmPrediction` 为统一结果容器（兼容字典映射与属性访问）：
- `res.positions`: 字典映射物体名至未来 $n\_future$ 帧的三维位置 `(n_future, 3)`；
- `res.velocities`: 字典映射物体名至未来 $n\_future$ 帧的三维线速度 `(n_future, 3)`；
- `res.identifiable`: 布尔值，标明前缀信息是否足以支持参数辨识；
- `res.promoted`: 可选布尔值，标明符号残差项是否通过检验门晋升；
- `res.identified_params`: 辨识出的各物体 `PhysicalParameters`；
- `res.posterior_covariance`: 后验协方差矩阵近似 $(J^T W J + \Sigma_0^{-1})^{-1}$。

### 1.1 ① PriorArm（有偏物理先验）
- 从已观测前缀的最后一帧（$t = T_{prefix} - 1$）状态出发；
- 采用预先登记的 `prior.DEFAULT_BIASED_PRIOR` 进行 600 Hz 半隐式欧拉积分（每帧 10 个子步，与 `prior.py` 严格对齐），向后展开 $n\_future$ 帧。

### 1.2 ④ TrueParamArm（真参数诊断上界）
- 类属性与文档均明确标注 `diagnostic_only = True`，类 docstring 声明「只作上界诊断，只允许评测侧构造」；
- 构造时显式传入真实物理参数 $\phi^*$，从前缀最后一帧出发展开仿真，提供动力学结构上界基准。

### 1.3 ⑤ IdentifyArm（在线参数辨识）
- **优化方法**：带盒式边界约束（Box Bounds）的 Levenberg-Marquardt / Gauss-Newton；
- **雅可比矩阵**：复用 `jacobian.compute_prior_jacobian` 的中心差分（相对步长 $10^{-3}$）；
- **目标函数**：前缀上逐帧位置与线速度的加权残差平方和：
  $$C(\phi) = \frac{1}{2} \mathbf{r}(\phi)^T \mathbf{W} \mathbf{r}(\phi) + \frac{1}{2} (\phi - \hat{\phi}_0)^T \Sigma_0^{-1} (\phi - \hat{\phi}_0)$$
  其中量纲平衡权重 $w_{pos} = 10^4$（对应位置观测精度 $0.01$ m），$w_{vel} = 400$（对应速度精度 $0.05$ m/s）；
- **先验正则项**：均值 $\hat{\phi}_0$ 取 `DEFAULT_BIASED_PRIOR`，对角协方差 $\Sigma_0 = \text{diag}(\sigma_{0, i}^2)$，各参数标准差 $\sigma_{0, i}$ 取其可容许范围的 $1/2$；
- **边界约束**：E0 隐藏参数范围：
  - `friction`: $[0.05, 0.95]$
  - `restitution`: $[0.00, 0.90]$
  - `mass`: $[0.20, 5.00]$
  - `linear_damping`: $[0.00, 0.25]$
  - `angular_damping`: $[0.00, 0.25]$
- **可辨识性门控**：计算数据 Fisher 信息矩阵 $F = J^T W J$ 的最小特征值 $\lambda_{min}(F)$；
  若前缀过短（$< 4$ 帧）或 $\lambda_{min}(F) < \text{FISHER\_MIN\_EIGVAL\_THRESHOLD} (10^{-3})$（例如自由落体无接触帧，恢复系数敏感度为 0），退回先验均值 $\hat{\phi}_0$，并标记 `identifiable = False`；
- **后验协方差**：返回逆海森矩阵近似 $\Sigma_{post} = (J^T W J + \Sigma_0^{-1})^{-1}$。

### 1.4 ⑦ SymbolicResidualArm（STLSQ 符号残差臂）
- **二阶段辨识**：首先运行 ⑤ 辨识背景物理参数 $\hat{\phi}$；
- **前缀残差加速度**：
  $$\mathbf{a}_{obs}[t] = \frac{\mathbf{v}_{obs}[t+1] - \mathbf{v}_{obs}[t]}{\Delta t_{frame}}$$
  $$\mathbf{a}_{prior}[t] = \frac{\mathbf{v}_{sim}[t+1] - \mathbf{v}_{obs}[t]}{\Delta t_{frame}}$$
  $$\mathbf{a}_{res}[t] = \mathbf{a}_{obs}[t] - \mathbf{a}_{prior}[t]$$
- **符号候选库**：
  复用 `src/ainerzero/v9/mechanism/discovery.py` 的符号基项规范 `BasisTermSpec`，支持三维向量加速度：
  - `quadratic_drag`: $\mathbf{f}_2(\mathbf{v}) = -\|\mathbf{v}\| \mathbf{v}$（对应二次阻力 $-c \|\mathbf{v}\| \mathbf{v}$）；
  - `linear_drag`: $\mathbf{f}_1(\mathbf{v}) = -\mathbf{v}$（对应线性阻力 $-c \mathbf{v}$）。
- **STLSQ 稀疏回归**：求解符号系数，正号归一化截断阈值 `stlsq_threshold = 0.05`，自动滤除不相关基项；
- **前缀切分与检验门**：
  前缀按时间分为两段（切分比例 `split_ratio = 0.67`）：前段拟合，后段检验。
  计算验证段上 Arm ⑤ 误差 $E_5$ 与附加符号项后 Arm ⑦ 候选误差 $E_7$ 的相对增益：
  $$\text{gain} = \frac{E_5 - E_7}{\max(E_5, 10^{-9})}$$
  仅当 $\text{gain} \ge \text{PROMOTE\_MIN\_GAIN} (0.10)$ 时，晋升符号项（`promoted = True`），并在向后仿真中作为附加加速度注入；否则退回 Arm ⑤（`promoted = False`）；
- **外部附加加速度积分**：实现 `rollout_with_accel` 与 `step_substep_with_accel`，在每步 600 Hz 动力学子步的连续力更新中累加符号加速度回调，完全不修改 `prior.py` 原有结构。

---

## 2. 实验数据与指标验证

| 指标项 | 理论 / 阈值要求 | 实验测量值 | 判定 |
|---|---|---|---|
| ⑤ 30 帧辨识误差 vs 先验误差 | $< 50\%$ 先验误差 | **$21.98\%$**（误差下降 78.02%） | **PASSED** |
| ⑤ 3 帧前缀辨识状态 | 退回 $\hat{\phi}_0$, `identifiable=False` | `identifiable=False`, $\hat{\phi} = \hat{\phi}_0$ | **PASSED** |
| ④ vs ① 10 步位置误差 | ④ 误差接近 0 且明显低于 ① | ④ = **$0.0000$ m**, ① = **$0.0037$ m** | **PASSED** |
| ⑦ 二次阻力恢复系数 $c$ 相对误差 | $< 20\%$ | **$11.78\%$**（真值 0.3500，恢复 0.3088） | **PASSED** |
| ⑦ 晋升门控（有二次阻力） | `promoted = True` | `promoted = True` (gain = 98.10%) | **PASSED** |
| ⑦ 10 步位置误差 vs ⑤ | ⑦ 误差低于 ⑤ | ⑦ = **$0.0023$ m** vs ⑤ = **$0.0769$ m** | **PASSED** |
| ⑦ 晋升门控（无二次阻力） | `promoted = False` | `promoted = False` | **PASSED** |
| 只读前缀隔离性（未来填充 NaN） | 各臂不受影响，输出无 NaN | 输出完全位一致，无 NaN | **PASSED** |

---

## 3. 四项源码变异坏对照（Adversarial Mutations）

变异实验均在完全隔离的独立临时目录 `/tmp/isolated_mutations/` 下执行，通过 `sys.path.insert(0, ...)` 显式载入变异副本，并在运行前打印 `__file__`，证明测试真实变红。

### 3.1 变异 1：⑤ 改成直接返回先验 $\hat{\phi}_0$
- **变异代码**：`identify_body` 直接返回 `DEFAULT_BIASED_PRIOR.copy(), ...`，跳过优化。
- **模块路径**：`/tmp/isolated_mutations/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **目标测试**：`test_arm5_parameter_identification_restitution_and_friction`
- **运行结果**：**RED (FAILED)**
  ```
  AssertionError: Identified error 0.4610 is not < 0.5 * 0.4610
  assert 0.4609772228646443 < (0.5 * 0.4609772228646443)
  ```

### 3.2 变异 2：⑦ 的晋升门改成恒真
- **变异代码**：将 `SymbolicResidualArm.predict` 中的 `promoted = False` 改为 `promoted = True`，无条件晋升。
- **模块路径**：`/tmp/isolated_mutations/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **目标测试**：`test_arm7_no_drag_rejected_promotion`
- **运行结果**：**RED (FAILED)**
  ```
  AssertionError: assert True is False
  where True = res7.promoted
  ```

### 3.3 变异 3：让某个臂读前缀之后的帧
- **变异代码**：在 `PriorArm.predict` 中将 `traj[prefix_len - 1]` 篡改为 `observed_prefix[name][prefix_len]`，越界读取未来帧。
- **模块路径**：`/tmp/isolated_mutations/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **目标测试**：`test_arms_read_only_prefix_nan_isolation`
- **运行结果**：**RED (FAILED)**
  ```
  IndexError: index 30 is out of bounds for axis 0 with size 30
  ```

### 3.4 变异 4：去掉 ⑤ 的边界约束
- **变异代码**：在 `IdentifyArm.__init__` 中将 `enforce_bounds` 设为 `False`，移除优化中的参数盒式裁剪。
- **模块路径**：`/tmp/isolated_mutations/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **目标测试**：`test_arm5_parameter_identification_restitution_and_friction`
- **运行结果**：**RED (FAILED)**
  ```
  AssertionError: assert 0.05 <= 0.027623784877248248
  where 0.027623784877248248 = PhysicalParameters(friction=0.0276...).friction
  ```

---

## 4. 交付文件与 SHA-256

```
src/ainerzero/v9/experiments/e1/arms_nonnet.py
tests/test_e1_arms_nonnet.py
reports/V9-E1A1/gemini-p68m/REPORT.md
reports/V9-E1A1/gemini-p68m/data.json
reports/V9-E1A1/gemini-p68m/SHA256SUMS.txt
```

全套测试用例回归验证命令：
```bash
PYTHONPATH=src python3 -m pytest tests/test_e1_arms_nonnet.py -v
PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -v
```
运行结果：44 个单测全部通过（`44 passed in 2.80s`）。
