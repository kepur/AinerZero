# W7（P175）：预登记 r1 字段（一级 claude 实现，2026-11-07）

- **作者：** 一级 claude
- **复核：** P176，须由 gemini 承担，排除 claude
- **改动范围：** `prereg.py`（只改 build_draft 与 validate，另加两个生成字段的函数）、`test_s2_prereg.py`

## 改动
- **`planning` 段：** `replan_m_steps` 由 `_r26_planning_fields()` 取代，字段包括：
  - `replan_every_obs_steps`
  - `cem_n_iters`、`cem_elite_frac`、`cem_encode_reserve`、`cem_min_pop`
  - `smoke_plan_choice`、`macro_dxy_scale`
  - `future_dt_l1`、`future_dt_l2`
  - `cost_mode`（flat 与 upper 为 trajectory_sum，lower 为 terminal）
  - `goal_feature`

  所有数值都取自 spec。
- **新增 `probe` 段**（`_probe_fields()`）：ridge_lambda、eval_steps、fit_samples、seed_namespace、start_points、horizon_max、gate_step、delta_pred。
- **validate：**
  - 出现 `replan_m_steps` 即报错；m 必须为 1；
  - 规划字段与探针字段逐项与 spec 比对；
  - cost_mode 只允许登记的两种取值；
  - `probe` 列为必填键。

## 验证
- `test_s2_prereg.py`：22 条通过，其中新增 W7 用例：字段与 spec 一致、5 种篡改、旧 m 键、flat 用 terminal 代价、缺 probe 段、试冻结确定性。
- **坏对照 3/3 变红**（`w7mut.py` + `w7muts.py`）：分别关掉规划字段比对、探针字段比对、旧 m 键检查。第一轮的两处变异打在冗余的检查层上而存活，已改为打在关键层上。
- **试冻结：** 两次 document_sha256 相同，均为 `63fb7c77…`。草稿和源文件清单见 `draft.json`、`trial_freeze.json`。这只是试冻结；生产冻结要等 W3 r2 和 W6b 验收后再做，届时 SHA 会变。
- **全量**（跳过 W3 r1 的端到端测试文件）：3714 passed，2 failed。2 条失败都在 W3 r2 正在改的 eval_runner 和 wiring 测试里。实盘零写入。
