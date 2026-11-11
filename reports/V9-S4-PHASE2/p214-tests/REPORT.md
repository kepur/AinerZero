# P217 交付报告：S4 二期按 DESIGN-r1 改写并入 P214 的 5 条补充测试并证明消杀变异

- 任务：`ainerzero.V9.P217`（层级 2 · 执行层 · 类型 test）
- 执行者：`gemini-e4c1`（二级 执行层 · 模型 Gemini 3.8 Flash）
- 依据：`reports/V9-S4-P2-DESIGN/DESIGN-r1.md`、`reports/V9-S4-PHASE2/impl-review/REPORT.md`（P214）
- 交付目录：`reports/V9-S4-PHASE2/p214-tests/`

---

## 摘要（30 行内速览）

1. **改写并入**：按 DESIGN-r1（m=12、新门 GR、负对照读 Bonferroni 上界、重设随机数等口径）将 P214 复核者提出的 5 条测试缺口完整改写并入仓库：
   - S1、S2、S3 并入 `tests/v9/experiments/test_s4_analysis_p2.py`（测试用例数由 52 项扩增至 68 项）；
   - S4、S5 并入 `tests/v9/experiments/test_s4p2_runner_native.py`（测试用例数由 17 项扩增至 19 项）。
2. **变异消杀证明**：在 `git archive HEAD` 解出的隔离副本中运行（PYTHONPATH 指向副本并已核验导入隔离），7 项核心变异全部被杀死，干净基线 100% 通过：
   - X01（GC 读 95% 界）：killed（`test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones[GC-GC-stat2]` 失败）；
   - X01b（GR 读 95% 界）：killed（`test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones[GR-GR-stat12]` 失败）；
   - X02（GD_D 设 m=1）：killed（`test_every_gate_statistic_is_bonferroni_corrected` 失败）；
   - X03（GX_C 误读主评测）：killed（`test_GX_reads_the_extrapolation_records` 失败）；
   - X04（只取种子 1）：killed（`test_event_values_are_averaged_over_the_three_seeds` 失败）；
   - X07（新，负对照读 95% 界）：killed（`test_negative_control_reads_the_bonferroni_upper_bound` 失败）；
   - M08b（final 权重检查移至写标记后）：killed（`test_final_refuses_a_changed_weight_file_before_the_marker` 失败）；
   - X06（删墙钟预留检查）：killed（`test_final_refuses_when_the_wall_clock_left_is_below_the_reserve` 失败）。
3. **二期三份测试持锁全过（实盘工作树）**：
   - `test_s4_gated.py`（经锁，`--native-mlx`）：**11 passed** in 1.20s；
   - `test_s4_analysis_p2.py`（纯 CPU）：**68 passed** in 50.29s；
   - `test_s4p2_runner_native.py`（经锁，`--native-mlx`）：**19 passed** in 481.33s。
4. **守卫核查**：未改动 `src/`，未改动原有报告，未修改 `artifacts/` 目录（未生成任何 `s4p1-*`、`s4p2-*` 世界）。

---

## 1. 5 条补充测试改写说明与对照 DESIGN-r1

P214 报告指出被审提交 `c5387d8` 存在 5 条应修测试缺口（S1–S5）。在合并至最新 HEAD 时，严格对照 `DESIGN-r1`（提交 `50f9edf` 引入）的规格调整如下：

### S1: 每个事件对错与重新出现覆盖率的三个种子平均（对应变异 X04）
- **问题与 r1 适配**：原测试中随机生成的数据在被选中的非碰撞事件上三个种子恰好均为 1，导致只取种子 1 也能通过。
- **改动**：在 `test_s4_analysis_p2.py` 中新增 `test_event_values_are_averaged_over_the_three_seeds`。显式构造 3 个种子取值不同（种子 1 为 1，种子 2 和 3 为 0），使得 3 种子均值为 1/3，在 4 个事件上总和严格为 4/3；同时对 `correct` 和 `reappear` 两个字段断言。若变异只取种子 1，均值将变为 1.0（总和 4.0），从而断言失败。

### S2: 各门读 Bonferroni 区间且各统计按 m=12 校正（对应变异 X01, X02, X07）
- **问题与 r1 适配**：
  1. DESIGN-r1 将对比数由 11 改为 12（`N_COMPARISONS = 12`），新增门 GR；
  2. 负对照改为读 Bonferroni 上界（`bonf_high`），亦按 m=12 进行校正，因此原 P214 测试断言「负对照 Bonferroni 区间与 95% 区间相同」在 r1 下是过时的，必须改为断言其 Bonferroni 区间同样严格更宽；
  3. 原边界测试中 `_st` 辅助函数默认 `ci_low/ci_high` 等于 `bonf_low/bonf_high`，分不出读的是哪一个界。
- **改动**：
  1. 新增 `test_every_gate_statistic_is_bonferroni_corrected`：断言 `gate_keys` 长度恰为 `P2.N_COMPARISONS == 12`，遍历全部 12 个门统计项断言 `bonf_low < ci_low` 且 `bonf_high > ci_high`；遍历负对照 `neg_C` 与 `neg_D` 断言两者 Bonferroni 区间同样严格更宽。
  2. 新增参数化测试 `test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones`：构造 13 组测试用例，覆盖 GN, GA, GC, GK1（全部步下界与上界、碰撞步）、GK2（非碰撞、碰撞）、GD（D 与比值）、GX（差值与 C）以及 r1 新增的 **GR**（下界要求严格大于 0.0）。每组数据均构造为「95% 置信界能通过，但 Bonferroni 置信界不满足门限」，断言对应门判定失败。
  3. 补齐 `test_negative_control_reads_the_bonferroni_upper_bound`：同时覆盖 `neg_C` 与 `neg_D` 在 `bonf_high >= 0.5` 但 `ci_high < 0.5` 时判定不过。

### S3: GX 的 C 读外推记录（对应变异 X03）
- **问题与 r1 适配**：原测试中外推与主评测使用同一组臂参数，GX 的 C 误读主评测无法察觉。
- **改动**：在 `test_s4_analysis_p2.py` 中新增 `test_GX_reads_the_extrapolation_records`，构造外推数据中 `L-int-g` 仅在非碰撞事件上准确（使得 `GX_diff` 能过），而在碰撞事件上退化为 E-B 水平（`C < 0.3`），主评测正常；断言 GC 通过、`GX_diff` 通过，而 GX 门因 `GX_C` 未达到门限而失败。

### S4: final 下权重文件 SHA 不符在写标记前拒绝（对应变异 M08b）
- **问题与 r1 适配**：原 `test_changed_or_missing_weights_are_refused_before_anything` 仅在 `smoke` 阶段测试，缺少在 `final` 阶段核对权重文件并在写入只读一次标记 `FINAL_READ_ONCE.json` 之前拒绝的测试。
- **改动**：在 `test_s4p2_runner_native.py` 中新增 `test_final_refuses_a_changed_weight_file_before_the_marker`。完成探针与预登记冻结后，修改 `artifacts/` 下的一期权重文件单字节，以 `--stage final` 运行，断言报错包含 `weights missing or changed`，且断言 `FINAL_READ_ONCE.json` 和 `reports/final.json` 均未被生成。

### S5: final 剩余墙钟不够评测预留时拒绝且不写标记（对应变异 X06）
- **问题与 r1 适配**：原测试未覆盖 `run_s4p2.py` 中的 `if deadline.left() < reserve:` 分支。
- **改动**：在 `test_s4p2_runner_native.py` 中新增 `test_final_refuses_when_the_wall_clock_left_is_below_the_reserve`。完成探针冻结后，将预登记里的 `eval_reserve_s` 修改为极大值（`10**6` 秒），以 `--stage final` 运行，断言报错包含 `the final read is not spent`，且断言 `FINAL_READ_ONCE.json` 未被生成。

---

## 2. 隔离副本变异消杀证明（原始输出）

变异测试由 `evidence/mutate_p217.py` 在隔离副本（解自 `git archive HEAD` 并并入新测试）中执行，每个变异均在运行前经 `importlib.util.find_spec` 确认被测模块来自隔离副本路径而非实盘工作树。

### 2.1 CPU 分析组变异（`evidence/mutants-cpu.txt`）

```text
== clean_analysis: 纯 CPU 分析测试基线（不改源码）
   imported from copy: ['/private/tmp/p217_mutants_cpu/clean_analysis/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/clean_analysis/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/clean_analysis/src/ainerzero/v9/experiments/s4/worker_p2.py']
   result: baseline-ok  exit=0  68 passed in 13.89s

== X01_GC_uses_95_not_bonferroni: GC 的下界改用 95% 区间 ci_low 而非 Bonferroni 区间 bonf_low
   imported from copy: ['/private/tmp/p217_mutants_cpu/X01_GC_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X01_GC_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X01_GC_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'_gt(st["GC"], "bonf_low", T["GC"]["C_low"])'
                                                   +'_gt(st["GC"], "ci_low", T["GC"]["C_low"])'
   result: killed  exit=1  1 failed, 67 passed in 17.75s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones[GC-GC-stat2]

== X01_GR_uses_95_not_bonferroni: GR 的下界改用 95% 区间 ci_low 而非 Bonferroni 区间 bonf_low
   imported from copy: ['/private/tmp/p217_mutants_cpu/X01_GR_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X01_GR_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X01_GR_uses_95_not_bonferroni/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'_gt(st["GR"], "bonf_low", T["GR"]["diff_low"])'
                                                   +'_gt(st["GR"], "ci_low", T["GR"]["diff_low"])'
   result: killed  exit=1  1 failed, 67 passed in 30.36s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones[GR-GR-stat12]

== X02_GD_D_bonferroni_m1: GD 的 D 统计用 m=1（退化为 95% 区间）
   imported from copy: ['/private/tmp/p217_mutants_cpu/X02_GD_D_bonferroni_m1/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X02_GD_D_bonferroni_m1/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X02_GD_D_bonferroni_m1/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'"GD_D": D_of(main, a),'
                                                   +'"GD_D": D_of(main, a, m=1),'
   result: killed  exit=1  1 failed, 67 passed in 34.85s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_every_gate_statistic_is_bonferroni_corrected

== X03_GX_C_from_main_records: GX 的 C 误读主评测而非外推
   imported from copy: ['/private/tmp/p217_mutants_cpu/X03_GX_C_from_main_records/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X03_GX_C_from_main_records/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X03_GX_C_from_main_records/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'"GX_C": C_of(extrap, a)'
                                                   +'"GX_C": C_of(main, a)'
   result: killed  exit=1  1 failed, 67 passed in 43.79s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_GX_reads_the_extrapolation_records

== X04_seed_average_seed1_only: 每个事件的对错与重新出现覆盖率只取种子 1
   imported from copy: ['/private/tmp/p217_mutants_cpu/X04_seed_average_seed1_only/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X04_seed_average_seed1_only/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X04_seed_average_seed1_only/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'for s in SEEDS], axis=0) if r["events"] else np.zeros(0)'
                                                   +'for s in SEEDS[:1]], axis=0) if r["events"] else np.zeros(0)'
   result: killed  exit=1  3 failed, 65 passed in 50.30s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_a_gated_model_like_the_exploration_passes_every_gate
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_seed_averaging_per_event
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_event_values_are_averaged_over_the_three_seeds

== X07_neg_control_uses_95_high: 负对照 neg_C 与 neg_D 改回读 95% 上界 ci_high（退回 r0 口径）
   imported from copy: ['/private/tmp/p217_mutants_cpu/X07_neg_control_uses_95_high/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_cpu/X07_neg_control_uses_95_high/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_cpu/X07_neg_control_uses_95_high/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'_lt(st["neg_C"], "bonf_high", T["negative_control"]["C_high_below"])'
                                                   +'_lt(st["neg_C"], "ci_high", T["negative_control"]["C_high_below"])'
   src/ainerzero/v9/experiments/s4/analysis_p2.py: -'_lt(st["neg_D"], "bonf_high", T["negative_control"]["D_high_below"])'
                                                   +'_lt(st["neg_D"], "ci_high", T["negative_control"]["D_high_below"])'
   result: killed  exit=1  1 failed, 67 passed in 53.00s
   FAILED tests/v9/experiments/test_s4_analysis_p2.py::test_negative_control_reads_the_bonferroni_upper_bound
```

### 2.2 MLX 运行器组变异（经锁运行，`evidence/mutants-runner.txt`）

```text
lock held by 81012
== clean_runner: MLX 运行器测试基线（不改源码）
   imported from copy: ['/private/tmp/p217_mutants_runner/clean_runner/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_runner/clean_runner/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_runner/clean_runner/src/ainerzero/v9/experiments/s4/worker_p2.py']
   result: baseline-ok  exit=0  19 passed in 336.35s (0:05:36)

== M08b_weight_files_checked_after_marker_in_final: 运行器：final 时权重文件 SHA 核对挪到写标记之后（smoke/probe 不变）
   imported from copy: ['/private/tmp/p217_mutants_runner/M08b_weight_files_checked_after_marker_in_final/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_runner/M08b_weight_files_checked_after_marker_in_final/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_runner/M08b_weight_files_checked_after_marker_in_final/src/ainerzero/v9/experiments/s4/worker_p2.py']
   reports/V9-S4-PHASE2/run_s4p2.py: -'weights = check_weights()\n        ns = namespace(a.stage)'
                                     +'weights = check_weights() if a.stage != "final" else None\n        ns = namespace(a.stage)'
   reports/V9-S4-PHASE2/run_s4p2.py: -'R["final_read_marker_sha256"] = sha(FINAL_MARKER)'
                                     +'weights = check_weights()\n            R["weights_sha256"] = {n: sha(p) for n, p in weights.items()}\n            R["final_read_marker_sha256"'
   reports/V9-S4-PHASE2/run_s4p2.py: -'"weights_sha256": {n: sha(p) for n, p in weights.items()}, "workers": WORKERS}'
                                     +'"weights_sha256": {n: sha(p) for n, p in (weights or {}).items()}, "workers": WORKERS}'
   result: killed  exit=1  1 failed, 17 passed in 331.17s (0:05:31)
   FAILED tests/v9/experiments/test_s4p2_runner_native.py::test_final_refuses_a_changed_weight_file_before_the_marker

== X06_reserve_check_removed: 运行器：删掉写标记前的剩余墙钟 >= 评测预留检查
   imported from copy: ['/private/tmp/p217_mutants_runner/X06_reserve_check_removed/src/ainerzero/v9/experiments/s4/gated.py', '/private/tmp/p217_mutants_runner/X06_reserve_check_removed/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/tmp/p217_mutants_runner/X06_reserve_check_removed/src/ainerzero/v9/experiments/s4/worker_p2.py']
   reports/V9-S4-PHASE2/run_s4p2.py: -'if deadline.left() < reserve:\n                raise GD.GuardError(f"only {deadline.left():.0f} s left, the evaluation needs {reserve:.0f} s:'
                                     +''
   result: killed  exit=1  1 failed, 18 passed in 447.44s (0:07:27)
   FAILED tests/v9/experiments/test_s4p2_runner_native.py::test_final_refuses_when_the_wall_clock_left_is_below_the_reserve
```

---

## 3. 实盘工作树三份测试复跑结果

在实盘工作树中，经共享锁 `artifacts/locks/m0-worker.lock` 复跑全部三份二期测试：

### 3.1 门控单元测试 `test_s4_gated.py`（MLX，经锁）
- 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4_gated.py`
- 结果：**11 passed in 1.20s**（`evidence/tests-live-gated.txt`）

### 3.2 分析与指标测试 `test_s4_analysis_p2.py`（纯 CPU）
- 命令：`.venv/bin/python -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s4_analysis_p2.py`
- 结果：**68 passed in 50.29s**（`evidence/tests-live-analysis.txt`）

### 3.3 运行器全流程测试 `test_s4p2_runner_native.py`（MLX，经锁）
- 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4p2_runner_native.py`
- 结果：**19 passed in 481.33s**（`evidence/tests-live-runner.txt`）

---

## 4. 两个测试文件的 Git Diff

```diff
diff --git a/tests/v9/experiments/test_s4_analysis_p2.py b/tests/v9/experiments/test_s4_analysis_p2.py
index 7f94652..902bc40 100644
--- a/tests/v9/experiments/test_s4_analysis_p2.py
+++ b/tests/v9/experiments/test_s4_analysis_p2.py
@@ -161,6 +161,18 @@ def test_bonferroni_is_twelve_comparisons(good) -> None:
     assert alt == c
 
 
+def test_every_gate_statistic_is_bonferroni_corrected() -> None:
+    st = P2.gate_stats(records(), records(100, "extrap", seed=1, coll_share=0.38))
+    gate_keys = [k for keys in P2.GATE_STATS.values() for k in keys]
+    assert len(gate_keys) == P2.N_COMPARISONS == 12
+    for k in gate_keys:
+        s = st[k]
+        assert s["bonf_low"] < s["ci_low"] and s["bonf_high"] > s["ci_high"], k
+    for k in ("neg_C", "neg_D"):
+        s = st[k]
+        assert s["bonf_low"] < s["ci_low"] and s["bonf_high"] > s["ci_high"], k
+
+
 def test_phase1_like_model_fails_the_non_collision_gate() -> None:
     r = _eval(records(spec={"L-int-g": BASE["L-int"]}))
     g = r["gates"]
@@ -187,6 +199,16 @@ def test_collision_reappearance_coverage_below_threshold_fails() -> None:
     assert not g["GK2"]["passed"] and g["GK1"]["passed"]
 
 
+def test_GX_reads_the_extrapolation_records() -> None:
+    ext = records(100, "extrap", seed=1, coll_share=0.38,
+                  spec={"L-int-g": (0.42, 0.97, 0.90, 0.88, 0.91, 0.83)})
+    r = _eval(extrap=ext)
+    g = r["gates"]
+    assert g["GC"]["passed"]
+    assert g["GX"]["GX_diff"]["value"] >= 0.03          # the diff half passes
+    assert not g["GX"]["passed"] and g["GX"]["GX_C"]["value"] < 0.3
+
+
 def test_a_scatter_control_as_good_as_the_learned_response_fails_GR() -> None:
     r = _eval(records(spec={"L-sc-g": BASE["L-int-g"]}))
     assert not r["gates"]["GR"]["passed"]
@@ -236,6 +258,16 @@ def test_seed_averaging_per_event() -> None:
     assert np.array_equal(n_all, [3 * 440.0] * 3) and (ins_all >= ins).all()
 
 
+def test_event_values_are_averaged_over_the_three_seeds() -> None:
+    recs = records(2, n_events=4)
+    for r in recs:
+        for s, val in zip(P2.SEEDS, (1, 0, 0)):
+            r["cells"][P2.cell_key("L-int-g", s)]["correct"] = [val] * 4
+            r["cells"][P2.cell_key("L-int-g", s)]["reappear"] = [val] * 4
+    np.testing.assert_allclose(P2.event_sums(recs, "L-int-g", "all"), [4 / 3, 4 / 3])
+    np.testing.assert_allclose(P2.event_sums(recs, "L-int-g", "all", "reappear"), [4 / 3, 4 / 3])
+
+
 def test_descriptive_summary_runs_on_both_partitions() -> None:
     d = P2.summarize_descriptive(records(20), records(10, "extrap", seed=3), P2.HAND + P2.LEARNED)
     assert set(d["main"]) == set(P2.HAND + P2.LEARNED)
@@ -316,12 +348,39 @@ def test_negative_control_needs_a_small_upper_bound(key, stat) -> None:
     assert not neg and all(passed.values())
 
 
+@pytest.mark.parametrize("key,gate,stat", [
+    ("GN", "GN", _st(0.0, -0.031, 0.03, ci_low=-0.02, ci_high=0.02)),
+    ("GA", "GA", _st(0.06, -0.001, 0.10, ci_low=0.01, ci_high=0.09)),
+    ("GC", "GC", _st(0.95, 0.50, 1.20, ci_low=0.60, ci_high=1.10)),
+    ("GK1_all", "GK1", _st(0.90, 0.849, 0.95, ci_low=0.86, ci_high=0.94)),
+    ("GK1_all", "GK1", _st(0.90, 0.85, 0.951, ci_low=0.86, ci_high=0.94)),
+    ("GK1_collision", "GK1", _st(0.88, 0.80, 0.92, ci_low=0.82, ci_high=0.91)),
+    ("GK2_non_collision", "GK2", _st(0.90, 0.80, 0.95, ci_low=0.82, ci_high=0.93)),
+    ("GK2_collision", "GK2", _st(0.82, 0.65, 0.90, ci_low=0.70, ci_high=0.88)),
+    ("GD_D", "GD", _st(0.85, 0.70, 0.92, ci_low=0.75, ci_high=0.90)),
+    ("GD_ratio", "GD", _st(0.03, 0.01, 0.151, ci_low=0.02, ci_high=0.14)),
+    ("GX_diff", "GX", _st(0.08, 0.0, 0.12, ci_low=0.02, ci_high=0.11)),
+    ("GX_C", "GX", _st(1.0, 0.40, 1.30, ci_low=0.50, ci_high=1.20)),
+    ("GR", "GR", _st(0.05, 0.0, 0.10, ci_low=0.02, ci_high=0.09)),
+])
+def test_gates_read_the_bonferroni_bounds_not_the_95_percent_ones(key, gate, stat) -> None:
+    st = _passing()
+    st[key] = stat
+    passed, neg = P2.decide(st)
+    assert not passed[gate] and neg
+
+
 def test_negative_control_reads_the_bonferroni_upper_bound() -> None:
     st = _passing()
     st["neg_C"] = _st(0.2, -0.1, 0.7, ci_low=0.0, ci_high=0.45)       # 95% below 0.5, Bonferroni not: fails
     assert not P2.decide(st)[1]
     st["neg_C"] = _st(0.2, -0.1, 0.45, ci_low=0.0, ci_high=0.55)
     assert P2.decide(st)[1]
+    st = _passing()
+    st["neg_D"] = _st(0.2, -0.1, 0.7, ci_low=0.0, ci_high=0.45)       # 95% below 0.5, Bonferroni not: fails
+    assert not P2.decide(st)[1]
+    st["neg_D"] = _st(0.2, -0.1, 0.45, ci_low=0.0, ci_high=0.55)
+    assert P2.decide(st)[1]
 
 
 class _Stoch:
diff --git a/tests/v9/experiments/test_s4p2_runner_native.py b/tests/v9/experiments/test_s4p2_runner_native.py
index 7c92922..376720f 100644
--- a/tests/v9/experiments/test_s4p2_runner_native.py
+++ b/tests/v9/experiments/test_s4p2_runner_native.py
@@ -301,3 +301,29 @@ def test_make_prereg_refuses_a_probe_with_other_weights(tmp_path) -> None:
     m = subprocess.run([sys.executable, "-I", str(root / MAKE), "--design", str(root / "reports/DESIGN.md"), "--probe", str(root / HERE / "probe.json"),
                         "--out", str(root / PREREG)], cwd=root, env=env, capture_output=True, text=True, timeout=120)
     assert m.returncode != 0 and "权重" in m.stderr + m.stdout and not (root / PREREG).exists()
+
+
+def test_final_refuses_a_changed_weight_file_before_the_marker(tmp_path) -> None:
+    root = _make_root(tmp_path)
+    _frozen(root)
+    _git(root, "add", ".")
+    _git(root, "commit", "-qm", "freeze")
+    w = root / WEIGHTS / "L-int#2.safetensors"           # artifacts/ is not tracked by git, editing it keeps git clean
+    b = bytearray(w.read_bytes())
+    b[-1] ^= 1
+    w.write_bytes(bytes(b))
+    _refused(_run(root, *FINAL, report="reports/final.json"), "weights missing or changed")
+    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
+    assert not (root / "reports/final.json").exists()
+
+
+def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path) -> None:
+    root = _make_root(tmp_path)
+    _frozen(root)
+    pre = json.loads((root / PREREG).read_text())
+    pre["budget"]["eval_reserve_s"] = 10 ** 6
+    (root / PREREG).write_text(json.dumps(pre))
+    _git(root, "add", ".")
+    _git(root, "commit", "-qm", "freeze with a reserve above the limit")
+    _refused(_run(root, *FINAL, report="reports/final.json"), "the final read is not spent")
+    assert not (root / ARTS / "FINAL_READ_ONCE.json").exists()
```

---

## 5. 交付清单与复现指南

交付目录：`reports/V9-S4-PHASE2/p214-tests/`
- `REPORT.md`：本报告
- `metrics.json`：测试通过项与变异杀死汇总指标
- `SHA256SUMS.txt`：文件 SHA256 校验清单
- `evidence/`：
  - `mutate_p217.py`：隔离副本创建与变异消杀脚本
  - `run_all.sh`：一键原样复跑脚本
  - `mutants-cpu.txt`：纯 CPU 组变异消杀原始日志
  - `mutants-runner.txt`：MLX 运行器组变异消杀原始日志
  - `tests-live-gated.txt`：实盘门控测试原始日志
  - `tests-live-analysis.txt`：实盘分析测试原始日志
  - `tests-live-runner.txt`：实盘运行器测试原始日志
  - `git-diff.patch`：测试文件差异补丁
  - `artifacts-check.txt`：artifacts 目录零污染检查记录
