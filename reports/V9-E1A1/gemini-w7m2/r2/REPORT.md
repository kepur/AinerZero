# ainerzero.V9.P68 执行报告（r2 交付）

角色：executor；负责人：gemini-w7m2；时间：2026-10-29
任务状态：reported；实验状态：completed
任务依据：E1 实现计划 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1-A1、预登记 r3 §2、一级 Claude 对抗验收打回意见（r2 必改）
输入身份：
- `src/ainerzero/v9/experiments/e1/prior.py`
- `src/ainerzero/v9/experiments/e1/jacobian.py`
- `src/ainerzero/v9/experiments/e1/metrics.py`
- `src/ainerzero/v9/mechanism/discovery.py`
修改文件：
- `src/ainerzero/v9/experiments/e1/prior.py`（按选项 (a) 新增可选参数 `extra_accel_fn=None`，实现单一来源积分器，默认行为逐位不变）
- `src/ainerzero/v9/experiments/e1/arms_nonnet.py`（删除重复积分器副本、删除旁路开关、删除样本内晋升、实现多物体检验门）
- `tests/test_e1_arms_nonnet.py`（新增瞬态外力拒绝门测例、短前缀样本内拒绝测例、多物体检验拒绝测例、单一来源等价测例）
- `reports/V9-E1A1/gemini-w7m2/r2/REPORT.md`
- `reports/V9-E1A1/gemini-w7m2/r2/data.json`
- `reports/V9-E1A1/gemini-w7m2/r2/SHA256SUMS.txt`
实际执行：
- 契约单测：`PYTHONPATH=src python3 -m pytest tests/test_e1_arms_nonnet.py -v`（11 项全过）
- 回归全测：`PYTHONPATH=src python3 -m pytest tests/test_e1_*.py -v`（49 项全过）
- 隔离变异坏对照：`python3 /tmp/run_all_mutations.py`（6 项源码变异全部变红）
验证结果：49 passed in 3.72s，零 GPU/零网络/纯 CPU NumPy。

---

## 1. r2 必改项逐条解决说明

针对一级 Claude 打回提出的 5 项问题与必改要求，本棒（`gemini-w7m2`）进行了彻底重构与强化：

1. **删除生产旁路开关**：
   - 彻底移除了 `IdentifyArm.__init__` 中的 `enforce_bounds` 参数，优化步中一律执行盒式边界截断 `np.clip(phi_cand, self.lower_bounds, self.upper_bounds)`；
   - 彻底移除了 `SymbolicResidualArm.__init__` 中的 `force_promote_always` 参数，晋升检验门一律强制执行。

2. **删除样本内 var_gain 晋升路径**：
   - 删除了原代码 `val_len < 3` 时按训练集方差解释度 `var_gain` 晋升的漏洞路径；
   - 规范为：当验证段不足（`val_len < 3`）或未发现候选基项时，`promoted` 强制为 `False`（零样本内宣布有效）。

3. **检验门扩展为全部活动物体多体平均**：
   - 多物体场景下，在前缀训练段收集全部活动物体的速度与残差加速度进行联合 STLSQ 稀疏回归；
   - 在验证段（$t_{split}$ 至 $T_{prefix}-1$），同时对全部物体进行多体仿真推进；
   - 误差 $E_5$ 与 $E_7$ 取全部活动物体的宏平均：$E = \frac{1}{N_{bodies}} \sum_{b} E_b$；只有宏平均增益 $\ge \text{PROMOTE\_MIN\_GAIN} (0.1)$ 时方可晋升。

4. **新增测试锁死「门恒真」变异**：
   - 新增 `test_arm7_transient_force_rejected_by_validation_gate`：构造前缀 0..20 帧存在二次阻力（STLSQ 成功选出 `quadratic_drag`），但在 20..30 帧阻力消失的瞬态外力场景；
   - 验证段上 Arm ⑤ 误差极小，而候选 Arm ⑦ 因强行施加阻力导致误差激增，增益为负（$\text{gain} < 0 < 0.1$）；
   - 门必须拒绝（`promoted = False`）。若变异为 `if True:`，测试立即爆红。

5. **积分器单一来源（采用一级倾向的选项 a）**：
   - 在 `src/ainerzero/v9/experiments/e1/prior.py` 的 `step_substep`、`simulate_frame` 与 `rollout` 中新增可选参数 `extra_accel_fn: Callable[[ActiveBody], np.ndarray] | None = None`；
   - 默认行为与原有物理积分逐位一致，原有 13 项 prior 测试完全通过；
   - 彻底删除 `arms_nonnet.py` 中 115 行重复的物理与接触模拟代码，使 `prior.py` 成为全系统动力学积分的单一权威来源。

---

## 2. 核心实验指标与验收比对

| 指标项 | 预登记 / 理论阈值要求 | r2 实验测量值 | 判定 |
|---|---|---|---|
| ⑤ 30 帧辨识误差 vs 先验误差 | $< 50\%$ 先验误差 | **$21.98\%$**（先验误差 0.4610，辨识误差 0.1013） | **PASSED** |
| ⑤ 3 帧短前缀信息不足降级 | 退回 $\hat{\phi}_0$, `identifiable=False` | `identifiable=False`, $\hat{\phi} = [0.5, 0.45]$ | **PASSED** |
| ④ vs ① 10 步位置误差 | ④ 误差接近 0 且明显低于 ① | ④ = **$0.0000$ m**, ① = **$0.0037$ m** | **PASSED** |
| ⑦ 二次阻力恢复系数 $c$ 相对误差 | $< 20\%$ | **$11.78\%$**（真值 0.3500，恢复 0.3088） | **PASSED** |
| ⑦ 晋升门控（真实阻力场景） | `promoted = True` | `promoted = True` (gain = 98.10%) | **PASSED** |
| ⑦ 10 步位置误差 vs ⑤ | ⑦ 误差低于 ⑤ | ⑦ = **$0.0023$ m** vs ⑤ = **$0.0769$ m** | **PASSED** |
| ⑦ 晋升门控（无阻力纯净数据） | `promoted = False` | `promoted = False` (active_terms = []) | **PASSED** |
| ⑦ 瞬态阻力（训练有/验证无） | `promoted = False`, active_terms 非空 | `promoted = False` (gain = -9.19, terms=['quadratic_drag']) | **PASSED** |
| ⑦ 短前缀（验证段不足 3 帧） | `promoted = False`（禁止样本内晋升） | `promoted = False` (val_len = 1 < 3) | **PASSED** |
| ⑦ 多体检验不一致（单体好/整体差） | `promoted = False` | `promoted = False` (ball1 alone gain=1.0, multi gain < 0.1) | **PASSED** |
| 未来 NaN 前缀读取隔离性 | 输出完全无 NaN 且位一致 | 位一致（atol=1e-12） | **PASSED** |
| 积分器单一来源等价性 | extra_accel_fn=None 与默认逐位一致 | 逐位一致（np.testing.assert_array_equal） | **PASSED** |

---

## 3. 六项源码变异坏对照实验（全部在隔离副本中验证）

执行脚本 `/tmp/run_all_mutations.py` 在独立临时目录中复制 `src/`，修改变异代码，通过显式载入变异模块并打印 `__file__` 验证路径，确认 6 项变异在目标测试上全部变红（FAILED）：

```
======================================================================
MUTATION TEST SUMMARY:
[RED (FAILED as expected)] arm5_return_phi0: ⑤ 改成直接返回 φ̂₀
[RED (FAILED as expected)] gate_always_true: ⑦ 的晋升门改成恒真 (if True: 代替 if gain >= self.promote_min_gain:)
[RED (FAILED as expected)] restore_sample_in_path: 恢复样本内路径 (val_len < 3 时按训练方差解释率 var_gain 晋升)
[RED (FAILED as expected)] verify_primary_only: 只验证 primary 物体 (忽略其他物体的验证误差)
[RED (FAILED as expected)] read_future_frame: 让某个臂读前缀之后的帧 (越界访问未来帧)
[RED (FAILED as expected)] remove_bounds: 去掉 ⑤ 的边界约束 (取消参数边界截断)
======================================================================
```

### 3.1 变异 1：⑤ 改成直接返回先验均值 $\hat{\phi}_0$
- **变异文件**：`/tmp/iso_arm5_return_phi0_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：`identify_body` 直接返回 `DEFAULT_BIASED_PRIOR.copy(), post_cov, True`
- **目标测试**：`test_arm5_parameter_identification_restitution_and_friction`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: Identified error 0.4610 is not < 0.5 * 0.4610
  assert 0.4609772228646443 < (0.5 * 0.4609772228646443)
  ```

### 3.2 变异 2：⑦ 晋升门改成恒真（`if True:`）
- **变异文件**：`/tmp/iso_gate_always_true_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：将 `if gain >= self.promote_min_gain:` 替换为 `if True:`
- **目标测试**：`test_arm7_transient_force_rejected_by_validation_gate`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: Promotion gate failed to reject transient force!
  assert True is False
  ```

### 3.3 变异 3：恢复样本内路径（`val_len < 3` 样本内方差增益）
- **变异文件**：`/tmp/iso_restore_sample_in_path_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：在 `val_len < 3` 时追加计算训练集 `var_gain` 并设置 `promoted = True`
- **目标测试**：`test_arm7_short_prefix_no_sample_in_promotion`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: Short prefix promoted without sufficient validation frames!
  assert True is False
  ```

### 3.4 变异 4：只验证 primary 单个物体
- **变异文件**：`/tmp/iso_verify_primary_only_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：将多体检验平均误差改为仅计算 `primary_name` 物体的误差与 gain
- **目标测试**：`test_arm7_multi_body_validation_rejection`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: assert 0.9810042387328147 < 0.1
  where 0.9810042387328147 is the gain of ball1 alone
  ```

### 3.5 变异 5：让某个臂越界读前缀之后帧
- **变异文件**：`/tmp/iso_read_future_frame_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：将 `clean_prefix[name][prefix_len - 1]` 篡改为 `observed_prefix[name][prefix_len]`
- **目标测试**：`test_arms_read_only_prefix_nan_isolation`
- **结果**：**RED (FAILED)**
  ```
  IndexError: index 30 is out of bounds for axis 0 with size 30
  ```

### 3.6 变异 6：去掉 ⑤ 的盒式边界约束
- **变异文件**：`/tmp/iso_remove_bounds_*/src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- **变异内容**：注释掉 `phi_cand = np.clip(phi_cand, self.lower_bounds, self.upper_bounds)`
- **目标测试**：`test_arm5_parameter_identification_restitution_and_friction`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: assert 0.05 <= 0.027623784877248248
  where 0.027623784877248248 = PhysicalParameters(friction=0.0276...).friction
  ```

---

## 4. 交付文件清单

```
src/ainerzero/v9/experiments/e1/prior.py
src/ainerzero/v9/experiments/e1/arms_nonnet.py
tests/test_e1_arms_nonnet.py
reports/V9-E1A1/gemini-w7m2/r2/REPORT.md
reports/V9-E1A1/gemini-w7m2/r2/data.json
reports/V9-E1A1/gemini-w7m2/r2/SHA256SUMS.txt
```

---

## 5. 交回统筹说明

- 全部 5 项 r2 必改要求与 6 项变异坏对照均已彻底解决，证据确凿闭环；
- 所有代码在纯 CPU / NumPy 环境下执行，未修改或导入任何 GPU/MLX 相关组件；
- 遵循工作规则，未提交、未推送 git。请统筹予以 r2 终审验收。
