# E1 位置误差指标修订 r2 实施报告（ainerzero.V9.P89）

- **任务编号**：`ainerzero.V9.P89`
- **任务标题**：【L2·gemini·代码】E1 修订 r2：位置误差改为单起点视野误差（替换拼接整轨迹的旧算法；不可用 k 不补值）
- **执行 Agent**：`gemini-w8f2`（二级执行 Agent）
- **依据规范**：`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` § 架构裁定修订 r2（一级 claude，2026-10-29，依据 P88 smoke）
- **工作目录**：`/Users/mac/AinerWorkFlow/AinerZero`
- **日期**：2026-10-29

---

## 一、背景与缺陷分析

### 1. 旧实现（拼接整轨迹 + 滑动窗口均值）的核心缺陷
在修订前，`src/ainerzero/v9/experiments/e1/eval_runner.py`（原 428–450 行）将观测前缀（$t \in [0, \text{PREFIX\_FRAMES}-1]$）与学生/臂的未来自回归预测拼接成一条长为 $T$ 的整长轨迹，并将其传递给 `metrics.compute_k_step_position_errors`。

`metrics.compute_k_step_position_errors` 内部采用滑动起点窗口算法：
对每个 $k \in \{1, 5, 10, 30\}$，取起点 $t \in [1, T - 2 - k]$，将预测帧 $t+k$ 与真值帧 $t+k$ 对齐后取均值。
这导致所谓「$k$ 步误差」实际上是**整段轨迹内部所有可能滑动窗口的平均误差**，且被前缀帧的 0 误差或不同滚动步数严重混淆，完全不是预登记 §4 所定义的「自观察前缀结束后的第 $k$ 步视野预测误差」。

**实测证明**：
在 `reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/` 的真实 `bounce_collision` episode（`276b0365f2e34c09.json`）上，Arm ④（已知全部真参数并注入静态面真材质的真理诊断臂）在第 10 帧（观测前缀末帧）后预测第 11 帧，实际首帧单步预测位置误差只有 $0.194\text{ mm}$（小于 $1\text{ mm}$），然而在旧拼接滑动算法下，却被报成 **$e_1 = 47.8\text{ mm}$（$0.0478\text{ m}$）**！这完全掩盖了模型的真实物理预测精度。

### 2. 一级架构裁定修订 r2 规范要求
1. **单起点视野误差**：以观测前缀结束帧 $t_0 = \text{PREFIX\_FRAMES} - 1 = 9$ 为单一预测起点；
2. **预测与真值帧对齐**：预测数组 `pred_future` 形状为 $(n\_future, \text{num\_objects}, 3)$，第 $j$ 项（0-indexed）对应真实环境的第 $\text{PREFIX\_FRAMES} + j$ 帧。因此对预测视野步数 $k$：
   - 目标真值帧为：$\text{target\_frame} = \text{prefix\_frames} - 1 + k = t_0 + k$；
   - 预测帧对应：`pred_future[k - 1]`；
   - 误差 $e_k = \frac{1}{N} \sum_{i=1}^N \|\hat{p}_{k-1}^{(i)} - p_{t_0+k}^{(i)}\|$；
3. **不可用 $k$ 策略**：
   - 当 $k > n\_future$，或者 `exclude_endpoints=True` 且目标帧等于（或大于等于）$T-1$ 时，该 $k$ 标为不可用；
   - 结果字典中**严禁包含该 $k$ 的键**，在 `unavailable_k` 列表中登记；
   - **绝对不补 0 或 NaN**；
   - 若 $k=10$ 不可用，`primary_error_m` 键不存在，下游聚合必须优雅处理；
4. **下游聚合**：`eval_runner.evaluate_cell`、`evaluate_final_once` 和 `analysis.py` 统计每个 $k$ 的实际可用 episode 数 `n_available`，只对有效 episode 计算均值；若某 $k$ 无任何有效 episode，则为 `None`，不报错、不填默认值。

---

## 二、代码改动实施

所有改动严格限制在指定文件范围内：

### 1. `src/ainerzero/v9/experiments/e1/metrics.py`
- 新增权威函数 `compute_horizon_position_errors(pred_future, truth_positions, prefix_frames=10, k_steps=(1, 5, 10, 30), exclude_endpoints=True, primary_k=10)`：
  - 检查输入维度与张量对齐；
  - 严格按 $\text{target\_frame} = \text{prefix\_frames} - 1 + k$ 计算目标帧；
  - 判定条件：`k > n_future`、`target_frame >= t_total` 或 `exclude_endpoints and target_frame >= t_total - 1` 时记录到 `unavailable_k` 并跳过；
  - 返回字典含可用 $k$ 的误差字典、`primary_k`、（若可用则含）`primary_error_m`，以及 `unavailable_k`。
- 保留 `compute_k_step_position_errors`，并在其 docstring 中显著注明：*This function uses a sliding window definition across the entire rollout. E1 evaluation does not use this function (it uses compute_horizon_position_errors instead).*

### 2. `src/ainerzero/v9/experiments/e1/eval_runner.py`
- 在 `evaluate_episode` 中彻底删除构造拼接整长轨迹 `pred_trajectories_by_k` 与调用 `compute_k_step_position_errors` 的代码；
- 直接从 `pred_positions` 提取 `pred_future_arr`（形状 $(n\_future, \text{num\_objects}, 3)$），调用 `compute_horizon_position_errors(pred_future_arr, true_positions_all, prefix_frames=PREFIX_FRAMES, ...)`；
- 在 `evaluate_cell` 与 `evaluate_final_once` 中更新单元聚合逻辑：
  - 统计每个 $k$ 的有效 episode 数 `k_step_n_available`；
  - 仅对包含该 $k$ 的 episode 求平均；若某 $k$ 可用数为 0，则从 `k_step_errors` 中剔除；
  - 报告 `k_step_n_available` 字典。

### 3. `src/ainerzero/v9/experiments/e1/analysis.py`
- 更新 `_extract_episode_10_step_errors`：遍历 `episodes` 时跳过未提供 `10` 步误差的 episode，不填充默认值；仅当所有 episode 均无有效 10 步误差时才抛出 `KeyError`；
- 更新 `build_analysis_summary` 与 `generate_tables_markdown`：
  - 若 $k \in \{1, 5, 30\}$ 在 cell 中不存在或为 `None`，格式化为 `"-"`，避免类型异常。

---

## 三、真实 Dev Episode 对比与回归（Arm ④ 诊断）

在 `reports/V9-E1SMOKE3/gemini-k7a4/smoke_env/datasets/` 的 20 个开发集真实 episode 上，对 Arm ④（TrueParamArm）分别使用修改前的旧算法与修改后的 r2 算法进行评估。

### 1. 20 个 Dev Episode 逐例对比表

| Sequence ID | 场景类型 | 旧 $e_1$ (m) | 新 $e_1$ (m) | 旧 $e_{10}$ (m) | 新 $e_{10}$ (m) | 新算法 $e_1$ 判定 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `19e28d87b0bd...` | box_stack | 0.1473 | 0.0037 | 0.1874 | 0.0966 | 3.7 mm |
| `276b0365f2e3...` | bounce_collision | 0.0478 | 0.0002 | 0.0632 | 0.0114 | **0.194 mm (< 1 mm)** |
| `299e7139bcc5...` | occlusion_pass | 0.0289 | 0.0002 | 0.0367 | 0.0539 | **0.196 mm (< 1 mm)** |
| `325681829a6e...` | table_slide | 0.0833 | 0.0006 | 0.1031 | 0.0560 | **0.578 mm (< 1 mm)** |
| `392191aed746...` | table_slide | 0.0799 | 0.0007 | 0.0988 | 0.0678 | **0.672 mm (< 1 mm)** |
| `3a238027f1db...` | occlusion_pass | 0.0681 | 0.0002 | 0.0867 | 0.0785 | **0.196 mm (< 1 mm)** |
| `4de5bbadca9b...` | box_stack | 0.2813 | 0.0010 | 0.3579 | 0.3557 | **1.012 mm** |
| `52440caaccb6...` | occlusion_pass | 0.0060 | 0.0002 | 0.0076 | 0.0129 | **0.197 mm (< 1 mm)** |
| `65ad852af94d...` | table_slide | 0.0360 | 0.0002 | 0.0446 | 0.0188 | **0.244 mm (< 1 mm)** |
| `6c1bdfafaae8...` | bounce_collision | 0.0431 | 0.0001 | 0.0569 | 0.0048 | **0.134 mm (< 1 mm)** |
| `7ad87e96ce65...` | ramp_roll | 0.0240 | 0.0002 | 0.0306 | 0.0088 | **0.158 mm (< 1 mm)** |
| `87ce8efee659...` | bounce_collision | 0.0491 | 0.0002 | 0.0649 | 0.0058 | **0.207 mm (< 1 mm)** |
| `87ff3cf6a763...` | bounce_collision | 0.0467 | 0.0002 | 0.0618 | 0.0076 | **0.208 mm (< 1 mm)** |
| `95799622e678...` | box_stack | 0.0488 | 0.0009 | 0.0621 | 0.0373 | **0.916 mm (< 1 mm)** |
| `992f4817097b...` | table_slide | 0.0740 | 0.0005 | 0.0915 | 0.0509 | **0.505 mm (< 1 mm)** |
| `9def4ad8391b...` | ramp_roll | 0.0056 | 0.0001 | 0.0072 | 0.0024 | **0.118 mm (< 1 mm)** |
| `9fd811e1fc6b...` | ramp_roll | 0.0097 | 0.0001 | 0.0124 | 0.0029 | **0.126 mm (< 1 mm)** |
| `d2c6da406b83...` | occlusion_pass | 0.1301 | 0.0002 | 0.1656 | 0.0965 | **0.198 mm (< 1 mm)** |
| `e902d199ffb3...` | ramp_roll | 0.0034 | 0.0001 | 0.0044 | 0.0020 | **0.125 mm (< 1 mm)** |
| `ff9525a0eb7f...` | box_stack | 0.0268 | 0.0037 | 0.0340 | 0.0087 | 3.7 mm |

### 2. 均值对比与改善分析

- **$e_1$ 均值**：旧算法 $62.01\text{ mm}$ $\rightarrow$ **新算法 $0.66\text{ mm}$**（相对降幅 **$98.94\%$**）
- **$e_5$ 均值**：旧算法 $68.52\text{ mm}$ $\rightarrow$ **新算法 $13.83\text{ mm}$**
- **$e_{10}$ 均值**：旧算法 $78.86\text{ mm}$ $\rightarrow$ **新算法 $48.96\text{ mm}$**

在所有 `bounce_collision`、`occlusion_pass`、`ramp_roll` 以及大部分 `table_slide` 序列中，真参数首步预测误差全部降至 $0.12 \sim 0.67\text{ mm}$（均远低于 $1\text{ mm}$ 物理上界）。
原旧算法报出的几十毫米误差纯粹是全轨迹滑动拼接引入的伪缺陷，r2 架构裁定完全被实测证实。

---

## 四、隔离坏对照实验（Bad Controls）

在独立隔离目录 `/tmp/bad_controls_p89` 中建立工作副本（完整复制 `src` 与 `tests`，打印隔离 `__file__`），对三个坏对照逐一验证其变红（Fail-Closed）：

```
=== Isolation Check ===
Metrics module __file__: /tmp/bad_controls_p89/src/ainerzero/v9/experiments/e1/metrics.py
Eval module __file__: /private/tmp/bad_controls_p89/src/ainerzero/v9/experiments/e1/eval_runner.py
```

### 坏对照 (a)：恢复拼接整条轨迹的旧路径
- **实施**：在 `eval_runner.py` 中恢复旧代码，将 `full_positions` 与 `compute_k_step_position_errors` 重新连接。
- **验证**：运行 `test_arm4_real_bounce_collision_dev_episode_regression`。
- **结果**：**变红（Exit Code 1, FAILED）**。
- **失败证据**：
  ```
  FAILED tests/test_e1_eval_runner.py::test_arm4_real_bounce_collision_dev_episode_regression
  ValueError: pred_trajectories_by_k[1] length 2 matches neither total length 40 nor target window length 37
  ```

### 坏对照 (b)：目标帧错一帧（用 `prefix_frames + k` 代替 `prefix_frames - 1 + k`）
- **实施**：在 `metrics.py` 中故意修改公式：`target_frame = prefix_frames + k_int`。
- **验证**：运行 `test_compute_horizon_position_errors_analytic_increments`。
- **结果**：**变红（Exit Code 1, FAILED）**。
- **失败证据**：
  ```
  FAILED tests/test_e1_metrics.py::test_compute_horizon_position_errors_analytic_increments
  assert 0.002 == approx(0.001 ± 1.0e-12)
  ```

### 坏对照 (c)：不可用的 $k$ 补 0
- **实施**：在 `metrics.py` 中，当 `is_unavailable` 为真时，将 `{"mean_error_m": 0.0, ...}` 强制填入 `results[str(k_int)]`。
- **验证**：运行 `test_compute_horizon_position_errors_endpoint_and_unavailable_handling`。
- **结果**：**变红（Exit Code 1, FAILED）**。
- **失败证据**：
  ```
  FAILED tests/test_e1_metrics.py::test_compute_horizon_position_errors_endpoint_and_unavailable_handling
  AssertionError: assert '30' not in {'1': ..., '5': ..., '10': ..., '30': {'mean_error_m': 0.0, ...}}
  ```

三个坏对照在隔离副本下均稳定变红，证明测试用例严密有效。

---

## 五、测试套件回归结果

### 1. 本卡直接相关测试集（全部通过，100% PASS）
- `tests/test_e1_metrics.py`：**20 passed** in 0.67s
  - 含 4 项新增测试：
    1. `test_compute_horizon_position_errors_analytic_increments`（解析误差 $(j+1)\text{ mm}$ 验证）
    2. `test_compute_horizon_position_errors_perfect_prediction`（完美预测 $e_k=0$）
    3. `test_compute_horizon_position_errors_off_by_one_frame_constant_velocity`（整体错位一帧 $e_k = |v|\cdot dt$）
    4. `test_compute_horizon_position_errors_endpoint_and_unavailable_handling`（40 帧序列中 $k=30$ 端点排除及不可用 $k$ 拒绝补 0/NaN 验证）
- `tests/test_e1_eval_runner.py`：**18 passed** in 0.93s
  - 含 2 项新增测试：
    1. `test_arm4_real_bounce_collision_dev_episode_regression`（真实 dev episode 验证 $e_1 < 1\text{ mm}$）
    2. `test_evaluate_cell_aggregates_available_k_and_reports_n_available`（单元聚合可用数与只聚合有效序列验证）
- `tests/test_e1_analysis.py`：**13 passed** in 0.84s
  - 含 2 项新增测试：
    1. `test_extract_episode_10_step_errors_skips_unavailable_without_padding`（跳过不可用 episode 且拒绝填充）
    2. `test_build_analysis_summary_and_markdown_with_unavailable_k`（下游报告对不可用 $k$ 的容忍与 `-` 显示）

**直接范围合计：51 passed, 0 failed**。

### 2. 全量 E1 测试回归
运行 `PYTHONPATH=src .venv/bin/pytest tests/test_e1_*.py`：
- **191 passed**, 1 failed。
- **未通过说明**：失败的单个测试为 `tests/test_e1_entry.py::test_production_eval_runner_computes_real_metrics_on_synthetic_data`。
  - **原因定位**：该测试属于此前由其他 Agent 编写的单元测试（非本卡责任文件范围，且未纳入 git 跟踪）。该测试用例内部使用 `_create_synthetic_e0_sequence(..., num_frames=20)` 构造了仅 20 帧的极短合成序列。在修订 r2 的单起点视野定义下，观测前缀为 10 帧，目标帧为 $9 + 10 = 19$，而 20 帧序列的最后一帧恰为索引 19（即 $T-1$）。根据预登记 §4 与 r2 裁定中「`exclude_endpoints=True` 时目标帧等于 $T-1$ 必须排除并标记为不可用」的铁律，该 20 帧序列在 $k=10$ 处的视野正巧落在被排除的边界帧上，因此按规范正确判定为不可用。
  - 本任务严格遵守协作规则，**不越权修改文件范围外的 `tests/test_e1_entry.py`**，保持其权威独立性，特此如实记录。

---

## 六、交付物与 SHA256 校验

### 1. 修改与产出文件清单
- `src/ainerzero/v9/experiments/e1/metrics.py`
- `src/ainerzero/v9/experiments/e1/eval_runner.py`
- `src/ainerzero/v9/experiments/e1/analysis.py`
- `tests/test_e1_metrics.py`
- `tests/test_e1_eval_runner.py`
- `tests/test_e1_analysis.py`
- `reports/V9-E1MET/gemini-w8f2/before/`（修改前的原始备份）
- `reports/V9-E1MET/gemini-w8f2/before_dev_records.json`
- `reports/V9-E1MET/gemini-w8f2/after_dev_records.json`
- `reports/V9-E1MET/gemini-w8f2/指标.json`
- `reports/V9-E1MET/gemini-w8f2/REPORT.md`
- `reports/V9-E1MET/gemini-w8f2/SHA256SUMS.txt`

### 2. 规则与权限合规声明
- [x] 未改动碰撞 F1、能量漂移等其他指标计算
- [x] 未改动 spec 常量
- [x] 纯 CPU 操作，未调用 GPU/MLX，未启动新训练与渲染
- [x] 未执行 `git commit` 或 `git push`
- [x] 坏对照均在 `/tmp/bad_controls_p89` 独立隔离环境内执行并验证变红
