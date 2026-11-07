# P176 非作者复核 · S2 冻结准备 W7（P175）

- **结论：`RECOMMEND_ACCEPT`**
- **复核者：** `composer-de00`（二级；非 P175 作者；作者为 `claude`）
- **被复核：** `ainerzero.V9.P175`（reported）
- **日期：** 2026-11-07

## 1. 范围

- W7 交回补丁 `reports/V9-S2-W7/git_diff.patch` **只改**卡面列出的：
  - `src/ainerzero/v9/experiments/s2/prereg.py`（`build_draft` / `validate` + 两个字段生成函数）
  - `tests/v9/experiments/test_s2_prereg.py`
- 工作树相对 HEAD：`prereg.py` / `test_s2_prereg.py` **无未提交差异**（已在 `3de52bf`）。
- **同提交混入 W6b（P177）文件**（`probe_eval.py` / `spec.py` / `test_s2_probe_eval.py` / `reports/V9-S2-W6b/`）。这是一级打包方式，不属于 W7 补丁内容；W7 的 `git_diff.patch` 本身干净。
- **工作树其他已改文件**（未提交）来自并行的 **W3 / P168** 生产路径集成：`adapters_mlx.py`、`commands.py`、`eval_runner.py`、`train_runner.py`、`worker.py`、`tests/conftest.py`、`test_s2_eval_runner.py`、`test_s2_wiring.py`，以及大量历史 `reports/` 未跟踪产物。**不是 P175 引入。**

## 2. 回退清零（改过的模块 `prereg.py`）

| 模式 | 命中 | 缺数据时走向 | 判定 |
|---|---|---|---|
| W7 新增 `_r26_planning_fields` / `_probe_fields` | 无数字字面量；全部取自 `spec` | N/A | 通过 |
| W7 `validate` 规划/探针循环 | `planning.get` / `probe_doc.get` 与 expected 比对 | 不等 → `SpecValidationError` | 通过 |
| 缺 `probe` | `required_keys` 含 `probe`；另有 Mapping 检查 | 拒绝 | 通过 |
| `replan_m_steps` | 出现即报错；`replan_every_obs_steps` 必须为 1 | 拒绝 | 通过 |
| `or []` / `or {}` / `getattr(..., 默认)` / `default_` / `base_success_rate` / `preferred_` / `eval_episode` | **无** | — | 通过 |
| `0.5` | 仅 holdout 上界 `(0, 0.5)`；`holdout is None` 亦拒绝 | 拒绝 | 通过（既有） |
| `planning.get("cost_mode", {})` | 空默认 | 字段循环已先比对完整 `cost_mode`；空 `{}` 到不了放行篡改 | 冗余层，不构成放行 |
| `data_estimated_seconds_per_episode` 缺键默认 `spec.…`；`data`→`partitions` 回退；设计文档缺失写 `"missing_design_doc"` | 既有路径 | 软回退 | **非 W7 引入**；未因此 REJECT |

## 3. 生产调用点

- `cli.py`：`s2-phase1` → `s2.commands.s2_phase1_command`。
- **冻结路径**：`s2.freeze.freeze()` 对草稿与冻结文档各调用一次 `prereg.validate()` → **生产冻结会执行 W7 新校验**。
- **运行路径**：`smoke` / `learned_planning` / `eval_runner` / `probe_eval` 直接读 `spec.PLAN_REPLAN_EVERY_OBS_STEPS`、`PROBE_*`、`PLAN_COST_*` 等常量（与预登记写入值同源），不是只在测试里传入。
- 本卡职责是把登记参数写入预登记文档并校验；运行时读 spec、冻结时校验文档，二者一致。未跑生产 `s2-phase1`、未跑 MLX（遵禁止项）。

## 4. 亲手变异（隔离副本）

- 副本：`/tmp/relay-p176/iso`（复制 `src`、`tests`、`pyproject.toml`，`symlinks=True` 不跟随环）。
- `import ainerzero.v9.experiments.s2.prereg` → `/tmp/relay-p176/iso/src/.../prereg.py`（断言通过）。
- 基线：`22 passed`；每处还原后 SHA 一致。

| 变异 | 结果 |
|---|---|
| **卡面·关键层** 取消 m 相关闸（旧键拒绝 + m=1 硬查 + 跳过 `replan_every_obs_steps` 字段比对） | **变红**（2 failed） |
| **卡面·关键层** 从 `required_keys` 去掉 `probe` 且探针段改为可选 | **变红**（1 failed） |
| 作者 W7-M1 规划字段循环关掉 | **变红** |
| 作者 W7-M2 探针字段循环关掉 | **变红** |
| 作者 W7-M3 允许旧 `replan_m_steps` | **变红** |
| **自选** 跳过 `future_dt_*` 字段比对 | **变红** |
| 仅关 m=1 硬查 / 仅关 probe Mapping 检查 / 仅关 cost_mode 允许集 | 存活（冗余层；关键层仍在）— 与作者自述「第一轮打在冗余层存活」一致 |

证据：`review/mutation_results_v2.json`。

## 5. 全量

- 前台 `SIG_DFL+execv` 默认全量（`relay exec` 监督）。
- 结果：**3713 passed，6 failed，7 deselected**（约 641 s）。
- 失败均非 W7：`test_s2_production_e2e*`、`test_s2_wiring`（并行 W3 未完成接线）、两条 geometry `cpu_only_imports`（同进程已加载 `mlx` 污染）。`test_s2_prereg.py` 全过。
- 作者报告「跳过 W3 r1 e2e → 3714 passed / 2 failed」与当前脏树并存现象相容。
- **artifacts lstat 比对**：before/after 各 63064 条；added/removed/changed = **0**。见 `artifacts_diff.json`。

## 6. 逐字抽查（报告 vs 盘）

| # | 报告声明 | 盘上 | 结果 |
|---|---|---|---|
| 1 | 试冻结两次 SHA 相同，均为 `63fb7c77…` | `trial_freeze.json`：`sha_a==sha_b==63fb7c77d9f7…`，`equal: true` | 一致 |
| 2 | cost_mode flat/upper=`trajectory_sum`，lower=`terminal` | `draft.json` + `spec.PLAN_COST_*` | 一致 |
| 3 | `test_s2_prereg.py` 22 条通过 | 隔离基线 `22 passed in 1.01s` | 一致 |

另核：`draft.json` 的 `planning`/`probe` 与固定 `created_utc` 的 live `build_draft` 一致；草稿无 `replan_m_steps`。见 `spot_checks.json`。

## 备注（非必改）

1. `3de52bf` 把 W6b+W7 打成一次提交；复核以 W7 补丁为准，建议后续任务分开提交。
2. 冗余校验层（单独关掉仍全绿）可保留作纵深，但坏对照应以关键层为准——作者已改到关键层。
3. 全量 6 红属于 W3/环境污染，不构成对本卡 REJECT 的依据。

## 结论

P175 按卡面把 r2.6/D3.1/D5.1 登记进预登记，数值来自 spec，校验缺数据即拒，冻结路径会跑到新 validate；隔离坏对照与自选变异均变红；实盘 artifacts 零写入。**RECOMMEND_ACCEPT。**
