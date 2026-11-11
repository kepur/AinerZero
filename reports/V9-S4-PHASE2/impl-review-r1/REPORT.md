# S4 第二阶段 r1 代码差异非作者复核报告（c5387d8..50f9edf）

- **任务 ID**：`ainerzero.V9.P216`
- **复核者**：`gemini-f8a2`（二级执行 agent，非作者）
- **复核范围**：提交 `c5387d8..50f9edf` 对 `src/`、`tests/`、`reports/V9-S4-PHASE2/` 的全部代码差异
- **设计依据**：`reports/V9-S4-P2-DESIGN/DESIGN-r1.md`（§3、§5、§6 及变更表）
- **复核结论**：**建议通过**

---

## 0. 背景与代码差异概况

S4 第二阶段设计复核（P213，非作者报告 `r0-review/REPORT.md`）打回并指出：
1. 代用模型 SCATTER（知道何时碰撞，碰撞时打乱速度方向）拿到了较高的 C 值（0.738），负对照 `L-ind-geo` 无法排除「门打开并放宽不确定性」的伪收益；
2. 负对照使用了未校正的 95% 置信区间上界，应改为 Bonferroni 校正上界；
3. 随机门（2% 随机开启）应作为描述量臂纳入规范；
4. 有随机数的臂需要严格的独立种子派生与重设机制，确保确定性重放和测试复现。

一级作者据此修订了设计稿（`DESIGN-r1.md`），并在提交 `50f9edf` 中完成了代码更新。本复核只评估 `c5387d8..50f9edf` 的代码差异。

```
git diff --stat c5387d8 50f9edf -- src/ tests/ reports/V9-S4-PHASE2/
 reports/V9-S4-PHASE2/make_prereg.py             |   5 +-
 reports/V9-S4-PHASE2/verify_replay_p2.py        |   4 +-
 src/ainerzero/v9/experiments/s4/analysis_p2.py  |  65 ++++++++++----
 src/ainerzero/v9/experiments/s4/gated.py        | 115 +++++++++++++++++-------
 src/ainerzero/v9/experiments/s4/worker_p2.py    |  13 +--
 tests/v9/experiments/test_s4_analysis_p2.py     |  68 +++++++++++---
 tests/v9/experiments/test_s4_gated.py           |  63 ++++++++++++-
 tests/v9/experiments/test_s4p2_runner_native.py |   5 +-
 8 files changed, 264 insertions(+), 74 deletions(-)
```

---

## 1. 差异是否忠实实现 r1

### 1.1 散射响应（`scatter`）的定义与实现
- **规范要求**（`DESIGN-r1.md` §3, §5）：
  - 门与主臂 `L-int-g` 完全相同（接触头判定 $p > 0.5$）；
  - 门开时：位置取 E-B，速度取 E-B 的速度在 2D 平面旋转均匀随机角 $\theta \sim U(0, 2\pi)$，**速率严格不变**；
  - 门关时：预测与 E-B 逐位一致，不改变速度；
  - 门的判定不调用物理，不碰生成器的 `true_physics`。
- **代码实现**（`src/ainerzero/v9/experiments/s4/gated.py`）：
  - 函数 `scatter_velocity(v, theta)` 实现旋转：
    ```python
    c, s = np.cos(theta), np.sin(theta)
    return np.stack([c * v[..., 0] - s * v[..., 1], s * v[..., 0] + c * v[..., 1]], -1)
    ```
    几何恒等式 $(c v_x - s v_y)^2 + (s v_x + c v_y)^2 = (c^2 + s^2)(v_x^2 + v_y^2) = v_x^2 + v_y^2$，旋转前后速率严格不变。
  - 类 `GatedModel.__call__`：
    ```python
    if self.response == "scatter":
        theta = self._rng.uniform(0.0, 2 * math.pi, P.shape[:2])
        return pb, np.where(g[..., None], scatter_velocity(vb, theta), vb)
    ```
    位置直接返回 `pb`（即 `Mo.bounce` / E-B 位置）；速度仅在门开掩码 `g[..., None]` 上旋转，门关处严格返回 `vb`（E-B 速度）。完全符合规范。

### 1.2 随机门（`random`）
- **规范要求**（`DESIGN-r1.md` §3, §5）：
  - 描述臂 `L-int-rand`：门以 2% 的比例独立随机打开，开时取 `L-int` 预测，用于检验门的时机是否可被同比例随机开启替代。
- **代码实现**（`src/ainerzero/v9/experiments/s4/analysis_p2.py` 及 `gated.py`）：
  - `RAND_RATE = 0.02`，并在 `ARM_SPEC` 中登记 `"L-int-rand": ("L-int", ("random", RAND_RATE), "learned")`；
  - `GatedModel` 解析 `("random", rate)`，并在前向计算中调用 `g = self._rng.random(P.shape[:2]) < self.rate`；
  - 开时取网络输出 `p_, v_`，关时取 `pb, vb`。完全符合规范。

### 1.3 独立随机数生成器与种子派生规则
- **规范要求**（`DESIGN-r1.md` §3）：
  - 有随机数的臂（`L-sc-g`、`L-int-rand`）使用独立的随机数生成器，**不碰滤波器的随机数**；
  - 每次跟踪（`track`）和动力学评估（`dyn`）开始前，按规则派生种子并重设生成器：`derive_seed(ns, "arm-rng", world, seed, arm, "track" | "dyn")`；
  - 未重设种子就拒绝运行（fail-fast）。
- **代码实现**：
  - `gated.py` 中 `self.stochastic = self.kind == "random" or response == "scatter"`；
  - `__call__` 开头设防：`if self.stochastic and self._rng is None: raise RuntimeError(...)`；
  - `analysis_p2.py` 实现 `rng_seed(ns, w, seed, arm, use)` 调用 `W.derive_seed(ns, "arm-rng", w, seed, arm, use)`；
  - `track_cell` 在跟踪前调用 `reseed_if_stochastic(model, rng_seed(ns, ep.world_index, seed, arm, "track"))`，滤波器 rng 使用 `filter_seed(ns, ep.world_index, seed)`（`"filter"` 命名空间），二者完全隔离；
  - `world_record` 遍历 `dyn_models` 时，使用 `use="dyn"` 重设动力学模型种子。完全符合规范。

### 1.4 重放确定性核验
- **规范要求**（`DESIGN-r1.md` §5, §6）：
  - 独立进程从权重重放时，有随机数的臂必须按登记规则重设种子，保证重放与落盘摘要逐位一致。
- **代码实现**（`reports/V9-S4-PHASE2/verify_replay_p2.py`）：
  - 遍历跟踪格时，重放跟踪前执行：
    ```python
    P2.reseed_if_stochastic(m, P2.rng_seed(rep["ns"], w["world"], s, arm, "track"))
    ```
  - `test_s4p2_runner_native.py` 端到端核验了 `R["checks"]["replay"]["passed"]`，且重放检查了全部 $2 \times 33 = 66$ 个格（包含所有随机臂），逐位一致。

### 1.5 新增门 GR 的判据与比较数 $m = 12$
- **规范要求**（`DESIGN-r1.md` §5）：
  - GR：有碰撞的事件上 $L\text{-int-g} - L\text{-sc-g} \ge 0$，Bonferroni 下界 $> 0$；
  - 多重比较次数由 $m = 11$ 调整为 $m = 12$（增加 GR）。
- **代码实现**（`analysis_p2.py`）：
  - `N_COMPARISONS = 12`；
  - `THRESHOLDS["GR"] = {"diff": 0.0, "diff_low": 0.0}`；
  - `gate_stats` 中计算 `"GR": acc_diff(main, a, SCATTER_ARM, "collision")`；
  - `decide` 中判定：
    ```python
    "GR": _ge(st["GR"], "value", T["GR"]["diff"]) and _gt(st["GR"], "bonf_low", T["GR"]["diff_low"])
    ```
    严格要求点估计 $\ge 0.0$ 且 Bonferroni 下界 $> 0.0$。完全符合规范。

### 1.6 负对照读 Bonferroni 上界
- **规范要求**（`DESIGN-r1.md` §5, P213 R1 建议）：
  - 负对照 `L-ind-geo` 的 C 和 D 必须使用 Bonferroni 上界（$m = 12$）$< 0.5$，避免使用未校正的 95% 上界导致误判。
- **代码实现**（`analysis_p2.py`）：
  - `gate_stats` 中 `neg_C` 与 `neg_D` 取消了 `m=1` 传参，默认采用全局 `m = N_COMPARISONS = 12`；
  - `decide` 中将原先的 `_lt(st["neg_C"], "ci_high", ...)` 改为：
    ```python
    neg = (_lt(st["neg_C"], "bonf_high", T["negative_control"]["C_high_below"])
           and _lt(st["neg_D"], "bonf_high", T["negative_control"]["D_high_below"]))
    ```
    严格检查 Bonferroni 上界。完全符合规范。

### 1.7 描述量扩展
- `ARM_SPEC` 统一管理 7 个门控臂规格；
- `summarize_descriptive` 增加了 `learned_minus_scatter`，分 `collision`、`non_collision`、`all` 报告与散射对照臂的差异。

---

## 2. 隔离副本变异测试（10 个变异）

根据要求，变异测试全部在独立隔离目录（`/tmp/s4p2_r1_isolated`，拷贝了 `src/`、`tests/`、`pyproject.toml`、`reports/` 及相关权重）中执行，绝不污染实盘工作区。
共执行 **10 个变异**（包含 6 个必选变异和 4 个补充边界变异），测试脚本为 `evidence/mutate_r1.py`。

### 变异结果汇总表

| 序号 | 变异名称 | 变异位置与改动 | 针对测试 | 预期结果 | 实际结果 | 杀灭原因 |
|---|---|---|---|---|---|---|
| **M1** | 散射不保速率 | `gated.py:scatter_velocity` 返回乘以 1.5 | `test_s4_gated.py` | KILLED | **KILLED** (code=1) | `test_scatter_response_turns_eb_velocity_keeps_speed_and_eb_position` 断言速率模长 `np.allclose` 失败 |
| **M2** | 散射门关也改速 | `gated.py:__call__` 门关处也应用散射速度 | `test_s4_gated.py` | KILLED | **KILLED** (code=1) | `test_scatter_response_turns_eb_velocity_keeps_speed_and_eb_position` 断言门关处速度一致 `np.array_equal(out[1][~mask], vb[~mask])` 失败 |
| **M3** | 跟踪动力学共用种子 | `analysis_p2.py:world_record` 动力学重设改为 `"track"` | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_stochastic_arms_are_reseeded_per_world_seed_arm_and_pass` 断言 `dy.seeds == [rng_seed(..., "dyn")]` 失败 |
| **M4** | 重放不重设种子 | `verify_replay_p2.py` 注释掉 `P2.reseed_if_stochastic` | `test_s4p2_runner_native.py` | KILLED | **KILLED** (code=1) | `test_smoke_runs_end_to_end_and_records_its_files` 中重放核验失败，断言 `R["checks"]["replay"]["passed"]` 为 False |
| **M5** | GR 下界改成 $\ge$ | `analysis_p2.py:decide` GR 下界 `_gt` 改为 `_ge` | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_decide_fails_each_gate_at_its_boundary` 在 `bonf_low == 0.0` 边界上误判通过，断言 `assert not passed['GR']` 失败 |
| **M6** | 负对照改回 95% 上界 | `analysis_p2.py:decide` 判定改回 `ci_high` | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_negative_control_reads_the_bonferroni_upper_bound` 中 `ci_high < 0.5` 但 `bonf_high >= 0.5` 时误判通过，断言失败 |
| **M7** | 随机门比例非 2% | `analysis_p2.py:RAND_RATE` 改为 0.05 | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_registered_constants` 断言常量与规格不符失败 |
| **M8** | 比较数 $m \ne 12$ | `analysis_p2.py:N_COMPARISONS` 改为 11 | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_bonferroni_is_twelve_comparisons` 断言 $m=12$ 校正统计量一致失败 |
| **M9** | 散射臂门不匹配 | `analysis_p2.py:ARM_SPEC` 将 `L-sc-g` 门改为 `"geo"` | `test_s4_analysis_p2.py` | KILLED | **KILLED** (code=1) | `test_registered_constants` 断言 `ARM_SPEC[SCATTER_ARM][1] == ARM_SPEC[MAIN_ARM][1]` 失败 |
| **M10** | 随机臂未重设不报错 | `gated.py` 移除未重设种子抛 `RuntimeError` 检查 | `test_s4_gated.py` | KILLED | **KILLED** (code=1) | `test_stochastic_arms_need_a_seed_and_repeat_with_it` 断言 `pytest.raises(RuntimeError)` 失败（未抛出异常） |

**结果**：10/10 全部被杀灭，存活 0 个。测试套件具有完全的判决敏锐度和防御力。
详细变异日志与 JSON 总结见 `evidence/mutants_summary.json` 及 `evidence/mutants_output.txt`。

---

## 3. 测试复跑与原始输出

所有测试均在共享排他锁 `artifacts/locks/m0-worker.lock` 下由 `hold_lock.py` 调度执行，未放到后台，完整真实输出已归档于 `evidence/`。

### 3.1 `test_s4_gated.py`
```
lock held by 54011
...........                                                              [100%]
11 passed in 0.30s
```

### 3.2 `test_s4_analysis_p2.py`
```
lock held by 54076
....................................................                     [100%]
52 passed in 11.86s
```

### 3.3 `test_s4p2_runner_native.py`
```
lock held by 54280
.................                                                        [100%]
17 passed in 126.35s (0:02:06)
```

**测试结论**：80 项测试全部通过（11 + 52 + 17 = 80），零失败、零跳过、零警告。

---

## 4. 边界与工作区防污染核查

1. **实盘 `artifacts/v9/s4/` 未被写入**：
   - 复核前快照：`evidence/artifacts-s4-before.txt`（140 行）
   - 复核后快照：`evidence/artifacts-s4-after.txt`（140 行）
   - `diff -u artifacts-s4-before.txt artifacts-s4-after.txt` 差异严格为 0，核对报告见 `evidence/artifacts-check.txt`。
2. **代码修改范围**：
   - 仅在本任务分配的 `reports/V9-S4-PHASE2/impl-review-r1/` 目录下交付；
   - 未改动任何非范围文件，未修改 `src/` 或 `tests/`，未提交或推送 git。

---

## 5. 总结与建议

提交 `50f9edf` 对 S4 第二阶段设计修订（r1）的实现完整、严密且忠实：
1. 散射响应 `L-sc-g` 严格保持速率并锁定 E-B 位置，有效构成了对「仅放宽碰撞不确定性」的代用控制；
2. 随机门 `L-int-rand` 正确登记 2% 开启率作为时机描述量；
3. 随机数生成与种子派生机制彻底解耦于滤波器主干，确保了独立性和可重放性；
4. 判定统计严格实现了 GR 门与 $m=12$ 的 Bonferroni 校正，负对照严格核验 Bonferroni 上界；
5. 变异测试 10/10 全部杀灭，契约测试完备。

**评审结论：建议通过。**
