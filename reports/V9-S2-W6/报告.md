# S2 集成 W6 实验报告：§5 探针模块＋C 臂子目标注入（附录 D5.1）

- **任务 ID**：`ainerzero.V9.P173`
- **执行 Agent**：`gemini-b7x4`（二级执行代理，会话 `sess-bf83650114e6`）
- **依据**：`reports/V9-S2-DESIGN/DESIGN-r2.md` §5、附录 D5.1、附录 E，以及卡模板 `card-templates/W6.md`
- **执行时间**：2026-11-07

---

## 1. 范围与文件清单

严格遵守卡面文件范围，未修改 `eval_runner.py`、`commands.py` 或 `world.py`，未改动 `artifacts/`：

1. **`src/ainerzero/v9/experiments/s2/probe_eval.py`**（新增）：
   - `fit_probe(model, train_root, holdout_worlds=None, *, n_samples=spec.PROBE_FIT_SAMPLES, seed_namespace=spec.PROBE_SEED_NAMESPACE, lam=spec.PROBE_RIDGE_LAMBDA)`
   - `probe_errors(model, probe_model, partition_root, *, steps=spec.PROBE_EVAL_STEPS, start_points=spec.PROBE_START_POINTS, max_horizon=spec.PROBE_HORIZON_MAX)`
   - `prediction_noninferiority(errors_by_arm_seed, *, k=30, delta_pred=spec.DELTA_PRED, n_boot=spec.BOOTSTRAP_RESAMPLES, alpha=0.05, rng=None)`
   - 权威模块绑定：岭回归调用 `probe.fit_ridge` / `eval_error`，分簇 bootstrap 调用 `stats.cluster_paired_bootstrap`，特征提取调用 `learned_planning.featurize_obs`。
   - 严禁读取模型上的 `dev_Z`、`dev_XY` 等属性（遇之直接抛出 `ValueError`），缺失回合文件或观察一律 fail-closed。
2. **`src/ainerzero/v9/experiments/s2/planner.py`**：
   - 为 `hierarchical_cem_plan` 与 `hierarchical_cem_plan_reference` 增加 `z2_subgoal_override` 参数；
   - 给出时完全跳过上层 CEM，上层计数（`upper_forwards`）为 0；
   - `PlanResult.info` 中始终记录 `z2_subgoal`。
3. **`src/ainerzero/v9/experiments/s2/learned_planning.py`**：
   - 为 `make_plan_fn` 增加 `subgoal_source: Callable[[int], Any] | None = None` 关键字参数；
   - 非分层臂（flat）传入时抛出 `ValueError`；
   - 分层臂在每个决策步按 `decision_index` 调用 `subgoal_source(t)`，并将产出的子目标传入 `hierarchical_cem_plan(..., z2_subgoal_override=...)`。
4. **`src/ainerzero/v9/experiments/s2/spec.py`**：
   - 末尾追加探针评估与拟合参数（`PROBE_FIT_SAMPLES=2000`, `PROBE_FIT_STEPS=2000`, `PROBE_SEED_NAMESPACE="s2p1-train-v1|probe"`, `PROBE_START_POINTS=(0, 60, 120)`, `PROBE_HORIZON_MAX=60`）。
5. **`tests/v9/experiments/test_s2_probe_eval.py`**（新增）：默认纯 CPU 套件，7 个单测用例全部通过，零 MLX 导入。
6. **`tests/v9/experiments/test_s2_probe_eval_native.py`**（新增）：带 `--native-mlx` 的实测推演用例，总耗时 0.274s（$\le 30$s）。
7. **`reports/V9-S2-W6/`**：交付报告、diff patch、变异汇总表及指标数据。

---

## 2. 测试与验证结果

### 2.1 默认纯 CPU 套件 (`test_s2_probe_eval.py`)
运行命令：
```bash
.venv/bin/pytest tests/v9/experiments/test_s2_probe_eval.py -v
```
输出：**7 passed in 1.03s**

- `test_linear_vs_random_arm_probe_errors`:
  - 线性假臂 $k=1$ 步探针位置误差：**0.0011 格**（远低于 $< 0.1$ 格阈值）；
  - 随机假臂 $k=1$ 步探针位置误差：**5.9269 格**（远高于 $> 3.0$ 格阈值）。
- `test_fit_probe_strictly_excludes_holdout_worlds`:
  - 留出世界污染测试：将 `world_0001` 坐标篡改为 `99999.0`；
  - 传入 `holdout_worlds={1}` 或读取 `HOLDOUT_WORLDS.json` 时，探针推断值与干净真值一致（差值 $< 0.001$），严格证明留出世界未被拟合使用。
- `test_prediction_noninferiority_matches_hand_calc`:
  - 手算校验 1：$\Delta = 0.4$，95% bootstrap 上界 $= 0.4000 \le 1.0 \implies passed = True$；
  - 手算校验 2：$\Delta = 1.5$，95% bootstrap 上界 $= 1.5000 > 1.0 \implies passed = False$。
- `test_subgoal_override_skips_upper_cem_and_records_info`:
  - 给出 `z2_subgoal_override` 时，`upper_forwards == 0`，下层朝注入的子目标规划，`info["z2_subgoal"]` 严格一致。
- `test_make_plan_fn_subgoal_source`:
  - 验证 `subgoal_source(t)` 决策索引自增调用；flat 臂传入时被拒绝抛错。
- `test_fail_closed_on_prohibited_attributes`:
  - 模型暴露 `dev_Z` 或 `dev_XY` 时直接抛出 `ValueError`。
- `test_pure_cpu_no_mlx_in_sys_modules`:
  - `-I` 独立子进程导入 `probe_eval`，断言 `mlx` 与 `mlx.core` 绝不在 `sys.modules` 中。

### 2.2 Native MLX 真实三臂推演 (`test_s2_probe_eval_native.py`)
运行命令：
```bash
.venv/bin/pytest tests/v9/experiments/test_s2_probe_eval_native.py --native-mlx -s -v
```
实测输出：
```
[NATIVE MLX W6 PROBE TIMINGS] total=0.274s per_arm={'arm_a': 0.197s, 'arm_b': 0.034s, 'arm_c': 0.043s}
[NATIVE MLX W6 ERRORS] {'arm_a': {1: 4.755, 5: 2.160}, 'arm_b': {1: 4.755, 5: 2.160}, 'arm_c': {1: 4.755, 5: 2.160}}
1 passed in 0.33s
```
- 总耗时：**0.274 秒**（远低于 $\le 30$ 秒上限）；
- 各臂随机初始化后均正常完成特征化、MLX 编码、岭回归拟合、多步前向 rollout 及探针误差计算。

---

## 3. 坏对照变异实验（隔离副本 `/tmp/isolated_w6_mutation/`）

在隔离目录复制源码与用例并验证 import 解析后，分别进行 3 处变异，均变红（RED）：

| 变异编号 | 变异部位 | 变异操作 | 预期 | 实测结果 | 判定 |
|---|---|---|---|---|---|
| **W6-M1** | `probe_eval.fit_probe` | 移除留出世界跳过逻辑（`continue` 改为 `pass`），使留出世界被误用于探针拟合 | 变红 (RED) | `test_fit_probe_strictly_excludes_holdout_worlds` 失败 (exit 1) | **KILLED** |
| **W6-M2** | `probe_eval.probe_errors` | 将步数时域 $k = j + 1$ 篡改为固定常数 $k = 1$ | 变红 (RED) | `test_linear_vs_random_arm_probe_errors` 失败 (exit 1) | **KILLED** |
| **W6-M3** | `planner.hierarchical_cem_plan` | 忽略 `z2_subgoal_override` 保持上层 CEM 正常运行 | 变红 (RED) | `test_subgoal_override_skips_upper_cem_and_records_info` 失败 (exit 1) | **KILLED** |

变异后恢复原状，全套用例恢复 7/7 通过。

---

## 4. 交付文件状态

- `reports/V9-S2-W6/REPORT.md`（本报告）
- `reports/V9-S2-W6/git_diff.patch`（包含修改与新增文件的标准补丁，共 1391 行）
- `reports/V9-S2-W6/mutation_summary.json`（变异表 JSON）
- `reports/V9-S2-W6/metrics.json`（指标数据 JSON）
