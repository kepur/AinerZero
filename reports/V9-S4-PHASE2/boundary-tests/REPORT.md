# P219 交付报告：S4 二期评测预留边界用例与几何门 τ = DT 边界用例

- 任务：`ainerzero.V9.P219`（层级 2 · 执行层 · 类型 test · GPU 需求：否）
- 执行者：`gemini-h8f2`（二级 执行层 · 模型 Gemini 3.8 Flash）
- 依据：P217 验收建议、P214 备注 B2（`reports/V9-S4-PHASE2/impl-review/REPORT.md`）
- 交付目录：`reports/V9-S4-PHASE2/boundary-tests/`

---

## 摘要（30 行内速览）

1. **补齐两条边界用例（仅改测试，不改 `src/` 与已有脚本）**：
   - **用例 1（评测预留边界，P217 验收建议）**：在 `tests/v9/experiments/test_s4p2_runner_native.py` 中将 `test_final_refuses_when_the_wall_clock_left_is_below_the_reserve` 参数化为 `[10**6, 1000]`。在测试副本 final 900 秒硬上限下，1000 秒仅比剩余墙钟（约 899 秒）略高，彻底阻断将预留检查放宽为 `deadline.left() < reserve / 10` 的漏洞（变异 `ru_reserve_tenth`）。
   - **用例 2（几何门接触时间 τ = DT 边界，P214 备注 B2）**：在 `tests/v9/experiments/test_s4_gated.py` 中新增 `test_geo_gate_boundary_at_tau_equals_dt`。构造正碰双盘状态使接触时间 τ 在 IEEE 754 float64 精度下与 `W.DT` 逐位相等（`3.2 / 32.0 == 0.1`，指数位精确右移 5 位，尾数全同）。断言其判定与一期登记基线 `analysis.cv_contact_pairs` 一致（门关闭）；同时检验微移点（τ < DT 门开启）。
2. **隔离副本变异消杀证明（git archive HEAD 副本，已确认模块源自副本）**：
   - 门控变异 `X09_geo_gate_tau_le_dt`（`<` 改 `<=`）：干净基线 12 passed，变异副本 **killed**（1 failed, 11 passed，准确挂在 `test_geo_gate_boundary_at_tau_equals_dt`）；
   - 运行器变异 `ru_reserve_tenth`（预留放宽 10 倍）：干净基线 2 passed，变异副本 **killed**（1 failed, 1 passed，准确挂在新参数 `[1000]`，原 `[1000000]` 仍然通过证实放宽漏洞被新参数精确捕获）。
3. **实盘改动文件持锁复跑全过**：
   - `tests/v9/experiments/test_s4_gated.py`（MLX 锁内）：**12 passed in 0.32s**；
   - `tests/v9/experiments/test_s4p2_runner_native.py`（MLX 锁内）：**20 passed in 128.77s (0:02:08)**。
4. **守卫核查**：未修改 `src/`，未修改原有 `reports/` 脚本，未向 `artifacts/` 写入新文件，未生成任何 `s4p1-*`、`s4p2-*` 世界。

---

## 1. 边界用例实现说明

### 1.1 评测预留边界（`test_s4p2_runner_native.py`）
- **背景**：原测试仅使用 `eval_reserve_s = 10**6` 秒，若运行器守卫代码将 `if deadline.left() < reserve:` 错误放宽为 `if deadline.left() < reserve / 10:`（如一期变异 `ru_reserve_tenth`），因 `899 < 100000` 依然成立，测试将无法拦截该放宽行为。
- **改动**：
  ```python
  @pytest.mark.parametrize("reserve", [10 ** 6, 1000])
  def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path, reserve) -> None:
      ...
      pre["budget"]["eval_reserve_s"] = reserve
      ...
  ```
  在测试副本中，final 阶段的时限为 900 秒（`TINY` 替换），启动到预留检查约耗时 1 秒，剩余墙钟约为 899 秒。当 `reserve = 1000` 时：
  - 干净代码：`899 < 1000` 为 True，正确拒绝并抛出 `the final read is not spent`；
  - 放宽变异：`899 < 100` 为 False，变异代码漏过检查并写入标记，从而被新参数测试直接击杀。

### 1.2 几何门 τ = DT 边界（`test_s4_gated.py`）
- **背景**：`gated.py` 中几何门与一期接触基线 `analysis.cv_contact_pairs` 要求接触时间 `0 <= tau < W.DT`（严格小于）。在连续实数随机采样下，碰撞时间极小概率落在精确边界 `tau == 0.1` 上，导致变异 X09（`tau <= W.DT`）未能被随机测试消杀。
- **数学构造**：
  双盘半径 $R = 0.3$，两盘半径和 $2R = 0.6$，$(2R)^2 = 0.36$。
  两盘中心距离 $D = 1.0$，正碰相对速度 $V = 4.0$：
  - $a = u \cdot u = 16.0$
  - $b = 2(d \cdot u) = 2 \times (1.0) \times (-4.0) = -8.0$
  - $c = d \cdot d - (2R)^2 = 1.0 - 0.36 = 0.64$
  - $\Delta = b^2 - 4ac = 64.0 - 4 \times 16.0 \times 0.64 = 64.0 \times (1 - 0.64) = 23.04$
  - $\sqrt{\Delta} = 4.8$
  - $\tau = \frac{-b - \sqrt{\Delta}}{2a} = \frac{8.0 - 4.8}{32.0} = \frac{3.2}{32.0} = 0.1$
  因为分母 $32.0 = 2^5$，在 IEEE 754 双精度浮点（float64）中除以 32 是无精度损失的指数位直接减 5，尾数与 `3.2` 完全同形，且 `0.1` 在 float64 中的十六进制表示恰为 `0x1.999999999999ap-4`，两者逐位完全相等（`tau_val.hex() == float(W.DT).hex()` 为 True）。
- **断言设计**：
  1. 断言解析计算出的 `tau == W.DT`，且十六进制与字节码逐位相等；
  2. 断言一期登记基线 `A.cv_contact_pairs(P[0], V[0]) == set()`（不登记接触）；
  3. 断言二期门控 `G.geo_gate(P, V)` 全为 False（门关闭，与一期基线一致）；
  4. 辅以微扰测试：距离缩短 $10^{-6}$ 使 $\tau < DT$，断言两方均开启门。
  在变异 `X09_geo_gate_tau_le_dt` 下，`tau <= W.DT` 被判定为 True，门错误开启，断言直接失败。

---

## 2. 隔离副本变异消杀证明（原始输出）

变异测试由 `evidence/mutate_boundary.py` 在解自 `git archive HEAD` 的隔离副本中运行。已核验 `importlib.util.find_spec` 确认所有被测模块均指向隔离副本路径。

### 2.1 门控边界变异输出（`evidence/mutants-gated.txt`）

```text
lock held by 6200
== clean_gated: 门控测试基线（不改源码）
   imported from copy: ['/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/clean_gated/src/ainerzero/v9/experiments/s4/gated.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/clean_gated/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/clean_gated/src/ainerzero/v9/experiments/s4/worker_p2.py']
   result: baseline-ok  exit=0  12 passed in 1.30s

== X09_geo_gate_tau_le_dt: 几何门：tau < DT 改成 tau <= DT（边界测试）
   imported from copy: ['/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/X09_geo_gate_tau_le_dt/src/ainerzero/v9/experiments/s4/gated.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/X09_geo_gate_tau_le_dt/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_gated_VBLAtD/X09_geo_gate_tau_le_dt/src/ainerzero/v9/experiments/s4/worker_p2.py']
   src/ainerzero/v9/experiments/s4/gated.py: -'(tau >= 0) & (tau < W.DT))'
                                             +'(tau >= 0) & (tau <= W.DT))'
   result: killed  exit=1  1 failed, 11 passed in 0.31s
   FAILED tests/v9/experiments/test_s4_gated.py::test_geo_gate_boundary_at_tau_equals_dt
```

### 2.2 运行器预留边界变异输出（`evidence/mutants-runner.txt`）

```text
lock held by 6260
== clean_runner_reserve: 运行器预留检查基线（不改源码）
   imported from copy: ['/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/clean_runner_reserve/src/ainerzero/v9/experiments/s4/gated.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/clean_runner_reserve/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/clean_runner_reserve/src/ainerzero/v9/experiments/s4/worker_p2.py']
   result: baseline-ok  exit=0  2 passed, 18 deselected in 25.15s

== ru_reserve_tenth: 运行器：写标记前预留检查放宽十倍（ru_reserve_tenth）
   imported from copy: ['/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/ru_reserve_tenth/src/ainerzero/v9/experiments/s4/gated.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/ru_reserve_tenth/src/ainerzero/v9/experiments/s4/analysis_p2.py', '/private/var/folders/zv/vypfm1y977x338zzyccqx3br0000gn/T/p219_run_zgANCw/ru_reserve_tenth/src/ainerzero/v9/experiments/s4/worker_p2.py']
   reports/V9-S4-PHASE2/run_s4p2.py: -'if deadline.left() < reserve:'
                                     +'if deadline.left() < reserve / 10:'
   result: killed  exit=1  1 failed, 1 passed, 18 deselected in 34.31s
   FAILED tests/v9/experiments/test_s4p2_runner_native.py::test_final_refuses_when_the_wall_clock_left_is_below_the_reserve[1000]
```

---

## 3. 实盘改动测试复跑原始输出

在实盘工作树中，经共享锁 `artifacts/locks/m0-worker.lock` 复跑改动的两份测试文件：

### 3.1 门控单元测试 `tests/v9/experiments/test_s4_gated.py`（12 项全量）
- 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4_gated.py`
- 结果（`evidence/tests-live-gated.txt`）：
  ```text
  lock held by 6684
  ............                                                             [100%]
  12 passed in 0.32s
  ```

### 3.2 运行器全流程测试 `tests/v9/experiments/test_s4p2_runner_native.py`（20 项全量）
- 命令：`.venv/bin/python reports/V9-S4-PHASE1/impl-review-r2-recheck/evidence/harness/hold_lock.py artifacts/locks/m0-worker.lock .venv/bin/python -m pytest -q -p no:cacheprovider --native-mlx tests/v9/experiments/test_s4p2_runner_native.py`
- 结果（`evidence/tests-live-runner.txt`）：
  ```text
  lock held by 6756
  ....................                                                     [100%]
  20 passed in 128.77s (0:02:08)
  ```

---

## 4. Git Diff（两份测试文件改动）

```diff
diff --git a/tests/v9/experiments/test_s4_gated.py b/tests/v9/experiments/test_s4_gated.py
index f24f455..e5dc9d3 100644
--- a/tests/v9/experiments/test_s4_gated.py
+++ b/tests/v9/experiments/test_s4_gated.py
@@ -139,6 +139,40 @@ def test_real_contact_opens_the_geo_gate_only_for_the_pair() -> None:
     assert not G.geo_gate(P, V2).any()
 
 
+def test_geo_gate_boundary_at_tau_equals_dt() -> None:
+    # Pair of disks where contact time tau is exactly equal to W.DT bit for bit:
+    # D = 1.0 (between centers (4.0, 5.0) and (5.0, 5.0)), approach velocity V = 4.0.
+    # Gap = D - 2 * W.RADIUS = 1.0 - 0.6 = 0.4.
+    # a = 16, b = -8, c = 0.64, disc = 64 - 40.96 = 23.04. sqrt(disc) = 4.8.
+    # tau = (-(-8) - 4.8) / 32 = 3.2 / 32 = 0.1 == W.DT (exact exponent shift in binary float64).
+    P = np.array([[[4.0, 5.0], [5.0, 5.0]]], dtype=np.float64)
+    V = np.array([[[0.0, 0.0], [-4.0, 0.0]]], dtype=np.float64)
+
+    d = P[:, None, :, :] - P[:, :, None, :]
+    u = V[:, None, :, :] - V[:, :, None, :]
+    a = (u * u).sum(-1)
+    b = 2 * (d * u).sum(-1)
+    c = (d * d).sum(-1) - (2 * W.RADIUS) ** 2
+    disc = b * b - 4 * a * c
+    tau = (-b - np.sqrt(np.maximum(disc, 0.0))) / (2 * np.where(a > 0, a, 1.0))
+    tau_val = float(tau[0, 0, 1])
+
+    # Assert constructed tau is bitwise identical to W.DT:
+    assert tau_val == W.DT
+    assert tau_val.hex() == float(W.DT).hex()
+    assert np.asarray(tau_val).tobytes() == np.asarray(W.DT).tobytes()
+
+    # Assert gate decision matches registered Phase 1 baseline (cv_contact_pairs):
+    assert A.cv_contact_pairs(P[0], V[0]) == set()
+    g = G.geo_gate(P, V)
+    assert not g.any()
+
+    # Point just inside the boundary (tau < W.DT): both baseline and geo_gate flag contact
+    P_inside = np.array([[[4.0, 5.0], [5.0 - 1e-6, 5.0]]], dtype=np.float64)
+    assert A.cv_contact_pairs(P_inside[0], V[0]) == {(0, 1)}
+    assert G.geo_gate(P_inside, V)[0].all()
+
+
 def _names(fn) -> set[str]:
     tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
     out = set()
diff --git a/tests/v9/experiments/test_s4p2_runner_native.py b/tests/v9/experiments/test_s4p2_runner_native.py
index 376720f..4a713f7 100644
--- a/tests/v9/experiments/test_s4p2_runner_native.py
+++ b/tests/v9/experiments/test_s4p2_runner_native.py
@@ -317,11 +317,12 @@ def test_final_refuses_a_changed_weight_file_before_the_marker(tmp_path) -> None
     assert not (root / "reports/final.json").exists()
 
 
-def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path) -> None:
+@pytest.mark.parametrize("reserve", [10 ** 6, 1000])
+def test_final_refuses_when_the_wall_clock_left_is_below_the_reserve(tmp_path, reserve) -> None:
     root = _make_root(tmp_path)
     _frozen(root)
     pre = json.loads((root / PREREG).read_text())
-    pre["budget"]["eval_reserve_s"] = 10 ** 6
+    pre["budget"]["eval_reserve_s"] = reserve
     (root / PREREG).write_text(json.dumps(pre))
     _git(root, "add", ".")
     _git(root, "commit", "-qm", "freeze with a reserve above the limit")
```

---

## 5. 验收标准与交付物核验清单

- [x] **两条新测试在干净副本通过**：
  - `test_geo_gate_boundary_at_tau_equals_dt` 通过（`clean_gated`：12 passed）；
  - `test_final_refuses_when_the_wall_clock_left_is_below_the_reserve[1000]` 通过（`clean_runner_reserve`：2 passed）。
- [x] **两条新测试在对应变异上失败**：
  - 变异 `X09_geo_gate_tau_le_dt` 触发 `test_geo_gate_boundary_at_tau_equals_dt` 失败（killed）；
  - 变异 `ru_reserve_tenth` 触发 `test_final_refuses_when_the_wall_clock_left_is_below_the_reserve[1000]` 失败（killed）。
- [x] **改过的测试文件持锁全过**：
  - `test_s4_gated.py`（12 passed in 0.32s）；
  - `test_s4p2_runner_native.py`（20 passed in 128.77s）。
- [x] **文件与权限守卫核验**：
  - 未修改 `src/` 源码；
  - 未修改 `reports/` 目录下已有报告与运行器脚本；
  - 未触碰 `artifacts/` 目录，无世界生成；
  - 未执行 git commit / push。
