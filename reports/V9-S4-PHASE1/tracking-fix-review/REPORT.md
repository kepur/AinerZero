# S4 一期非作者复核报告：L-int-σ 移出跟踪臂（提交 a95f196）

- **复核者**：`gemini-b8k2`（二级执行 agent，非作者独立复核，会话指纹 `sess-c23947e69a93`）
- **复核对象**：提交 `a95f196`（作者：一级 `claude`）
- **核对范围**：
  - 代码改动：`reports/V9-S4-PHASE1/run_s4p1.py`、`tests/v9/experiments/test_s4p1_runner_native.py`、`reports/V9-S4-DESIGN/DESIGN-r3.md`、`tests/v9/experiments/test_s4_analysis.py`
  - 诊断证据：`reports/V9-S4-PHASE1/probe-r1/run.log`、`reports/V9-S4-PHASE1/probe-r1/diag/diag12.json`、`diag_nonfinite.py`
  - 涉及模块：`src/ainerzero/v9/experiments/s4/analysis.py`、`worker_mlx.py`、`filter.py`、`metrics.py`、`reports/V9-S4-PHASE1/verify_replay.py`
- **复核结论**：**建议通过（RECOMMEND_ACCEPT）**，必修问题数：`0`。

---

## 核心核对结论概览

| 序号 | 核对项 | 结论 | 核心证据 |
|:---:|:---|:---:|:---|
| 1 | 诊断属实性 | **属实** | 从 `diag12.json` 独立复算：12 个世界共 18 个格报 `ValueError: cost must be finite`（种子 3 共 12 次、种子 2 共 5 次、种子 1 共 1 次），全部集中于 `L-int-s`；其他学习臂 0 报错；出事前 `maxV` 达 282–661。与 `probe-r1/run.log` 堆栈及设计稿补记完全一致。 |
| 2 | 改动干净度 | **干净** | 跟踪格、`filter_calibration`、重放（`replay.json`）均已彻底排除 `L-int-s`；学生视图检查原本即未调用；描述量中 `TRACKED` 规避了缺键风险，同时 `L-int-s` 的 1 步真值速度校准（`calibration`）被完整保留。 |
| 3 | 门与阈值完整性 | **无触碰** | 逐门排查（合法性 6 项、负对照、HD、HF、HD-x、H1、H2、H3）：无任何门使用 `L-int-s` 的跟踪或预测结果。门定义、阈值表及数据集分区严格未动。 |
| 4 | 裁决成立性 | **成立** | 不限幅而直接移出跟踪臂合理：任意截断方差属于变相人造过程噪声，偏离评测表征学习方差的初衷；探针发现「在滤波器中按学习方差自主抽样会发散」属于真实且有价值的描述性结论。 |
| 5 | 测试有效性 | **有效** | 冒烟测试断言（`test_smoke_runs_end_to_end_and_records_its_files`）对跟踪臂白名单、记录键、重放格数 2×(15+6) 进行了严密锁定；计时测试（`test_post_marker_timing_starts_before_eval_generation`）以 4s/世界休眠和 11.5s 阈值有效防御打点位置后移。 |
| 6 | 补记如实性 | **如实** | 「只来自探针数据」属实（仅使用 `s4p1-probe`，未碰 `s4p1-final`）；「门、阈值、分区都没有动」代码比对无误；各项速度与错误统计数字完全吻合。 |
| 7 | 独立变异测试 | **通过** | 设计并执行了 2 个作者未做过的变异（`an_calib_names_drops_lint_s` 与 `an_calib_rows_var_constant`），在隔离副本中测试全部被测试集成功击杀（Killed）。 |

---

## 一、诊断属实吗？

### 1.1 从 `diag12.json` 独立重算

编写独立重算脚本解析 `reports/V9-S4-PHASE1/probe-r1/diag/diag12.json`，统计结果如下：
- **评估世界总数**：12 个（索引 0 至 11，涵盖 main 与 extrapolation）。
- **异常总条目**：41 条（`findings` 列表长度）。
  - `E-CV`：22 条。全部为 `error: null`，`n_nonfinite: 0`，最大输入速度 `maxV` 约 3.0，仅因无边界反射漂出边界（`pos > 50`）被触发记录，从未抛出异常。
  - `L-int-s`：19 条。其中 **18 条抛出异常 `ValueError: cost must be finite`**，1 条（种子 1，世界 2）未崩溃但 `maxV` 达到 319.71。
- **报错按臂与种子分布**：
  - `L-int-s#3`：12 个世界全部报错（12/12 = 100%）。
  - `L-int-s#2`：5 个世界报错（世界 0、2、6、10、11）。
  - `L-int-s#1`：1 个世界报错（世界 5）。
  - 合计报错格数：$12 + 5 + 1 = 18$ 个。
- **其他学习臂排查**：
  - `L-ind`、`L-int`、`L-int-c`、`L-int-e8`、`L-int-c-e8` 在 `diag12.json` 中的异常记录数均为 **0**。
- **出事前物理量**：
  - 出事格的输入最大速度 `maxV` 介于 **282.38 至 661.32**（生成器正常速度仅 0.6–1.4），证实了方差发散导致速度抽样爆炸的机理。

### 1.2 对照 `probe-r1/run.log` 报错栈

`reports/V9-S4-PHASE1/probe-r1/run.log` 关键行号与逐字记录：
- `reports/V9-S4-PHASE1/probe-r1/run.log:20`：
  ```
  [  5452.0s] evaluation worlds 75
  ```
- `reports/V9-S4-PHASE1/probe-r1/run.log:27-44`：
  ```python
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/worker_mlx.py", line 58, in evaluate_world
      rec = A.world_record(ep, kind, ns, cells, _MODELS)
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py", line 173, in world_record
      ids, n_tracks = track_cell(ep, cell, model, ns)
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py", line 152, in track_cell
      return F.track(student_detections(ep), ep.pillars, model, rng, cfg)
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/filter.py", line 108, in track
      assign = _associate(P, z, last, t, cfg)
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/filter.py", line 64, in _associate
      for r, c in hungarian(dist):
    File "/Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/assign.py", line 20, in hungarian
      raise ValueError("cost must be finite")
  ValueError: cost must be finite
  ```
崩溃点发生在多进程评测世界的卡尔曼滤波关联步，匈牙利算法输入矩阵因非有限数值（inf/nan）而直接拒绝。

### 1.3 对照设计稿与研究日志

- `reports/V9-S4-DESIGN/DESIGN-r3.md:358-360` 声明：
  > “出事的只有 L-int-σ：12 个世界里共 18 个格报错，种子 3 有 12 个、种子 2 有 5 个、种子 1 有 1 个；L-ind、L-int、L-int-c 和两个 1/8 数据臂一个都没有出事；出事前，那条轨迹的成员速度已经到了几百（生成器的速度是 0.6–1.4）。”
- `RESEARCH_LOG.md:3406-3413` 记录：
  > “12 个世界里共 18 个格非有限（种子 3 有 12 个、种子 2 有 5 个、种子 1 有 1 个）。L-ind、L-int、L-int-c 和两个 1/8 数据臂一个都没出事。出事前那条轨迹的成员速度已到几百（生成器速度 0.6–1.4）。”

对照结论：重算数字、日志、设计稿文本与实际执行堆栈 100% 吻合，诊断完全属实。

---

## 二、改干净了吗？

### 2.1 逐个调用点正向排查：`L-int-s` 是否彻底脱离跟踪系统

1. **跟踪格定义（`TRACKED`）**：
   - [run_s4p1.py:54](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L54)：
     ```python
     TRACKED = tuple(a for a in LEARNED if a != "L-int-s")
     ```
   - [run_s4p1.py:317](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L317)：
     ```python
     main_cells = [(c.arm, c.seed, c.variant) for c in A.plan_cells(TRACKED)]
     ```
   `L-int-s` 不再进入 `main_cells`，评测任务 `tasks` 中的每个世界都不会规划 `L-int-s` 的跟踪格。
2. **滤波器校准（`filter_calibration`）**：
   - [worker_mlx.py:63-65](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/worker_mlx.py#L63-L65)：
     ```python
     for c in cells:
         if c.variant != "base" or c.arm == "S-P":
             continue
     ```
   此处 `cells` 来自 `task["cells"]`（即由 `TRACKED` 生成）。由于 `L-int-s` 不在 `cells` 中，`filter_calibration` 不会对其运行 `F.track`。
3. **独立重放校验（`replay.json`）**：
   - [run_s4p1.py:336](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L336)：
     ```python
     replay.write_text(json.dumps({"ns": ns["eval"], "weights": {n: str(Path(p).relative_to(out)) for n, p in weights.items() if n.split("#")[0] in TRACKED},
     ```
   `replay.json` 显式添加了过滤条件 `if n.split("#")[0] in TRACKED`，`L-int-s` 的检查点路径不写入 `replay.json`，独立重放进程不会对其进行重跟踪。
4. **学生视图检查（`student_check`）**：
   - [run_s4p1.py:200](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L200)：
     ```python
     models = {"E-P": Mo.true_physics, "L-int#1": L.as_process_model(nets["L-int#1"])}
     ```
   学生视图未来变异检测固定使用 `E-P` 与 `L-int#1`，原本便不涉及 `L-int-s`。
5. **描述量汇总（`summarize_descriptive`）**：
   - [run_s4p1.py:354](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L354)：
     ```python
     R["descriptive"] = A.summarize_descriptive(main_r, ext_r, TRACKED)
     ```
   - [analysis.py:494](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L494)：
     ```python
     mean_arms = [a for a in learned_arms if a != "L-int-s"]
     ```
   汇总逻辑双重防御，`TRACKED` 确保跟踪描述量不会访问缺失的 `L-int-s` 跟踪记录键。

### 2.2 反向排查：是否有漏算、报错或静默丢失？

1. **`descriptive_tracking`**：
   - [analysis.py:301-302](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L301-L302)：
     ```python
     out["idf1"][part] = {a: float(np.mean([np.mean([r["idf1"][Cell(a, s).key] for s in SEEDS]) for r in recs])) for a in arms}
     out["n_tracks"][part] = {a: float(np.mean([np.mean([r["n_tracks"][Cell(a, s).key] for s in SEEDS]) for r in recs])) for a in arms}
     ```
   由于传递的是 `TRACKED`，`arms` 中不包含 `L-int-s`，避免了查询未运行跟踪格引发的 `KeyError`。
2. **`canonical_minus_plain`**：
   - [analysis.py:501-503](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L501-L503)：
     ```python
     out["canonical_minus_plain"] = {
         tag: {"D": _gap(out["dynamics"]["main"], f"L-int-c{tag}", f"L-int{tag}"), "acc_collision": diff_of(main, f"L-int-c{tag}", f"L-int{tag}", m=1)}
         for tag in ("", "-e8") if f"L-int-c{tag}" in learned_arms and f"L-int{tag}" in learned_arms}
     ```
   该项指标仅关注正则化模型对比（`L-int-c` 对比 `L-int`），不涉及方差臂。
3. **`calibration`（单步真值校准描述量）**：
   - [run_s4p1.py:158-164](file:///Users/mac/AinerWorkFlow/AinerZero/reports/V9-S4-PHASE1/run_s4p1.py#L158-L164)：训练阶段保留 `L-int-s` 3 个种子的训练并保存权重。
   - [worker_mlx.py:81-86](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/worker_mlx.py#L81-L86)：
     ```python
     sig = [f"L-int-s#{s}" for s in seeds if f"L-int-s#{s}" in _MODELS]
     desc["calibration"] = {}
     for n in sig:
         s = int(n.split("#")[1])
         rows = A.calib_rows(ep, _MODELS[n], np.random.default_rng(W.derive_seed(ns, "calib", ep.world_index, s)), every=CALIB_EVERY)
         desc["calibration"][n] = A.calibration_sums(rows, _REFS[s])
     ```
   - [analysis.py:533-534](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L533-L534)：
     ```python
     out["calibration"] = {part: calibration_from_sums([p for r in recs for p in r["descriptive"]["calibration"].values()])
                           for part, recs in (("main", main), ("extrap", extrap)) if any(r["descriptive"]["calibration"] for r in recs)}
     ```
   `L-int-s` 的预测方差针对真值单步加噪样本的 NLL 与 90% 覆盖率指标被完整保留并正确输出，没有静默少算。

---

## 三、有没有动到门？

逐一核对 `src/ainerzero/v9/experiments/s4/analysis.py:237-291` 中的门定义及所使用的模型臂：

| 门类别 | 门名称 | 代码实现引用 | 所使用的模型臂 | 是否涉及 `L-int-s` |
|:---|:---|:---|:---|:---:|
| 合法性门 | `labels` | [analysis.py:247](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L247) | 无模型依赖（校验事件对与标注） | 否 |
| 合法性门 | `student_view` | [analysis.py:248](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L248) | `E-P`、`L-int#1`（未来变异消费检查） | 否 |
| 合法性门 | `floor` | [analysis.py:239-241](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L239-L241) | `E-CV`、`E-B`、`E-P`（人工基线单调性） | 否 |
| 合法性门 | `complete` | [analysis.py:249-251](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L249-L251) | 无模型依赖（核对落盘记录数） | 否 |
| 合法性门 | `samples` | [analysis.py:252-254](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L252-L254) | `E-B`（碰撞事件数与步数下限） | 否 |
| 合法性门 | `determinism` | [analysis.py:255](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L255) | `TRACKED` 学习臂 + `E-B`、`E-P` | 否 |
| 对照门 | `negative_control` | [analysis.py:273-275](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L273-L275) | `L-ind`（分母使用 `E-B`、`E-P`） | 否 |
| 假设门 | `HD` | [analysis.py:277](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L277) | `L-int`（主任务动力学相对碰撞改善率） | 否 |
| 假设门 | `HF` | [analysis.py:278](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L278) | `L-int`（擦碰虚报比例） | 否 |
| 假设门 | `HD-x` | [analysis.py:279-280](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L279-L280) | `L-int`（外推任务动力学改善与虚报） | 否 |
| 假设门 | `H1` | [analysis.py:281](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L281) | `L-int`（主任务跟踪能力归一化指标 $C$） | 否 |
| 假设门 | `H2` | [analysis.py:282](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L282) | `L-int` 减 `L-ind`（交互归纳偏置增益） | 否 |
| 假设门 | `H3` | [analysis.py:283](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L283) | `L-int`（外推任务跟踪能力归一化指标 $C_x$） | 否 |

**结论**：全部 13 个门（6 个合法性、1 个负对照、6 个假设检验）无一依赖 `L-int-s`，门阈值（`THRESHOLDS`）与数据分区（`NAMESPACES`、`SIZES`）保持完全冻结状态，分毫未动。

---

## 四、裁决站得住吗？

### 4.1 裁决合理性评估

1. **科学目标一致性**：
   `L-int-s` 在设计之初即明确为**描述性探索臂**（DESIGN-r3 §4 预判“放进滤波器预计会变差”），并不承担证明主假说（HD、H1–H3）的使命。探针实验证实其在开环滤波器中按学习到的方差采样会导致无界正反馈发散，这一现象本身正是探针所揭示的宝贵实证科学结论。
2. **拒绝限幅（Clamping）的合理性**：
   若人为强行截断方差（例如强制将预测方差夹取在 $\le 0.05^2$），本质上是将该模型退化为“人工调整过程噪声的固定滤波模型”，失去了评测自适应不确定性表征的真实性，且截断上界无法在冻结期内获得非任意性论据。
3. **隔离解耦的清晰性**：
   将 `L-int-s` 移出跟踪闭环，但保留其训练（18 个完整格）与单步速度真值校准（`A.calib_rows` 的 NLL 与覆盖率），实现了“表征质量评估”与“闭环滤波数值发散”的准确解耦，处置干净、合规。

### 4.2 改进建议（仅供后续阶段参考，不改动本期代码）

1. **后续阶段（如 S4 二期或 S5）**：若需探索基于学习方差的闭环跟踪，可引入**未观测衰减先验（Epistemic Decay Prior）**：当轨迹连续多步未匹配到观测时，方差自适应向名义先验收缩，阻断发散回路。
2. **训练目标正则化**：在方差头损失中引入分布外惩罚或多步 rollout 正则化，避免边界外对数方差无限制饱和至上限。

---

## 五、测试有效吗？

### 5.1 冒烟测试断言有效性

在 [tests/v9/experiments/test_s4p1_runner_native.py:150-160](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s4p1_runner_native.py#L150-L160) 中新增了严格针对该改动的断言：
```python
    # L-int-s is trained (above) and described (calibration, below) but neither tracked nor replayed
    assert R["tracked_arms"] == ["L-ind", "L-int", "L-int-c", "L-int-e8", "L-int-c-e8"]
    assert not any(k.startswith("L-int-s") for r in recs for k in r["reid"])
    assert {c.key for c in A.plan_cells(R["tracked_arms"])} == main_keys
    assert {k for k in recs[2]["reid"]} == {c.key for c in A.plan_cells(R["tracked_arms"]) if c.variant == "base"}
    assert all(set(r["descriptive"]["calibration"]) == {"L-int-s#1", "L-int-s#2", "L-int-s#3"} for r in recs)
    rep = json.loads((out / "replay.json").read_text())
    assert set(rep["weights"]) == {f"{a}#{s}" for a in R["tracked_arms"] for s in (1, 2, 3)}
    assert R["checks"]["labels"]["passed"] and R["checks"]["replay"]["passed"] and R["checks"]["student_view"]["passed"]
    assert R["checks"]["replay"]["checked"] == 2 * (15 + 6)                  # tracked learned cells plus E-B and E-P
```
- **测试覆盖点**：
  1. `R["tracked_arms"]` 显式校验排除 `L-int-s`；
  2. `recs[*]["reid"]` 校验无任何以 `L-int-s` 起头的键；
  3. `rep["weights"]` 校验仅包含 15 个被跟踪学习格；
  4. 校验 `r["descriptive"]["calibration"]` 依然包含 3 个种子的校准结果；
  5. 校验重放格数精确为 $2 \times (15 + 6) = 42$。
- **有效性结论**：任何将 `L-int-s` 错误混入跟踪、遗漏重放过滤、或错误抹除校准描述量的变动，都会立即导致冒烟测试断言失败。

### 5.2 计时测试有效性

在 [tests/v9/experiments/test_s4p1_runner_native.py:408-433](file:///Users/mac/AinerWorkFlow/AinerZero/tests/v9/experiments/test_s4p1_runner_native.py#L408-L433)：
```python
def test_post_marker_timing_starts_before_eval_generation(tmp_path) -> None:
    ...
    # The probe evaluates 2 main + 1 extrapolation worlds, sleeping 4 s each: 12 s that only the
    # generation of evaluation worlds accounts for. A timer started after the generation leaves
    # only the other post-marker work (files, gates, description, the late check) in the difference.
    diff = R["post_marker_seconds"] - R["eval_seconds"] - R["check_seconds"]
    assert diff >= 11.5, f"post_marker_seconds must include eval world generation: {diff=}"
```
- **原理与边界**：测试在探针世界生成函数（`generate_episode`）中对每个世界注入 4.0 秒休眠，3 个评测世界共耗时 12.0 秒。
- **有效性**：若 `t_post` 打点错误移至评测世界生成之后，`diff` 将骤降至约 0.1–0.3 秒，必然跌破 11.5 秒硬性下限。设置 11.5 秒阈值（预留 0.5 秒抖动余量）既杜绝了系统级微小时间抖动的假阳性，又能 100% 捕获计时后移缺陷（已在变异测试中验证杀灭 `ru_post_marker_after_generation`）。

---

## 六、补记说过头了吗？

逐句对照 `reports/V9-S4-DESIGN/DESIGN-r3.md:353-380`：
1. **“只来自探针数据”**：
   - 核对事实：探针实验阶段仅读取 `s4p1-probe` 与 `s4p1-train` 分区，代码中 `s4p1-final` 未被生成或读取，结论纯粹源于 `probe-r1` 的 12 个世界重放分析，声明完全真实。
2. **“门、阈值、分区都没有动”**：
   - 核对事实：`git diff c1a91fb a95f196` 证实未对 `analysis.py` 中的 `THRESHOLDS`、`NAMESPACES`、`SIZES` 或门计算函数进行任何修改，声明完全真实。
3. **“出事的只有 L-int-σ：12 个世界里共 18 个格报错 ...”**：
   - 核对事实：已由 `diag12.json` 脚本复算 100% 验证，数字精准无夸大。

---

## 七、非作者独立变异测试（全新 2 处）

按照 `reports/V9-S4-PHASE1/tracking-fix/mut_tracking_fix.py` 的测试隔离机制（独立临时目录复制、独立 `PYTHONPATH`、纯净环境执行），针对未被作者测试覆盖的环节设计并执行了 2 处全新变异：

### 7.1 变异定义

```python
MUTS = [
    # 变异 1：去掉校准参考名称中的 L-int-s，检验校准结果对方差臂标识的强制依赖
    (
        "an_calib_names_drops_lint_s",
        "src/ainerzero/v9/experiments/s4/analysis.py",
        'CALIB_NAMES = ("L-int-s", "constant", "binned", "oracle")',
        'CALIB_NAMES = ("constant", "binned", "oracle")',
        CPU_T
    ),
    # 变异 2：将 L-int-s 的计算方差篡改为常量基准，检验方差覆盖率检验是否真正约束模型输出
    (
        "an_calib_rows_var_constant",
        "src/ainerzero/v9/experiments/s4/analysis.py",
        '    var = {"L-int-s": rows["var"], "constant": np.full((n, 2), ref["constant"]),',
        '    var = {"L-int-s": np.full((n, 2), ref["constant"]), "constant": np.full((n, 2), ref["constant"]),',
        CPU_T
    )
]
```

### 7.2 变异执行汇总

| 变异名称 | 修改文件与修改行 | 预期捕获测试 | 状态 | 耗时 |
|:---|:---|:---|:---:|:---:|
| `an_calib_names_drops_lint_s` | [analysis.py:427](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L427)：移除 `"L-int-s"` | `test_calibration_rows_and_references` 触发 `KeyError: 'L-int-s'` | **KILLED** | 15.32s |
| `an_calib_rows_var_constant` | [analysis.py:436](file:///Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/v9/experiments/s4/analysis.py#L436)：用常量替代 `rows["var"]` | `test_calibration_rows_and_references` 触发 `AssertionError: assert 0.98695 < 0.97` | **KILLED** | 15.30s |

### 7.3 变异测试真实原始输出（Raw Output）

#### 变异 1 原始测试输出：`an_calib_names_drops_lint_s`
```text
=================================== FAILURES ===================================
____________________ test_calibration_rows_and_references _____________________

ep = <ainerzero.v9.experiments.s4.world.Episode object at 0x1034f5970>

    def test_calibration_rows_and_references(ep) -> None:
        rows = A.calib_rows(ep, _mean_var(0.05, 0.3), np.random.default_rng(1))
        n = 299 * 6
        assert len(rows["kind"]) == n and rows["err"].shape == (n, 2) and rows["var"].shape == (n, 2)
        assert set(np.unique(rows["kind"])) == {0, 1, 2}
        ref = A.fit_references(rows)
        cg = rows["kind"] <= 1
        assert ref["constant"] == pytest.approx(float((rows["err"][cg] ** 2).mean()))
        assert ref["oracle"][1] == pytest.approx(float((rows["err"][~cg] ** 2).mean()))
        assert len(ref["bins"]) == len(A.CALIB_BINS) - 1
        cal = A.calibration(rows, ref)
        assert set(cal) == {"collision", "graze", "free", "collision+graze"}
        assert cal["collision"]["n"] + cal["graze"]["n"] + cal["free"]["n"] == n
        # fitted on these rows, the oracle is the best of the references on collision+graze
        cgv = cal["collision+graze"]
        assert cgv["oracle"]["nll"] <= cgv["constant"]["nll"] + 1e-9
        # a variance matching the free-step error covers about 90% of free steps
        free_sd = float(np.sqrt((rows["err"][rows["kind"] == 2] ** 2).mean()))
        rows2 = A.calib_rows(ep, _mean_var(0.05, free_sd), np.random.default_rng(1))
>       assert 0.8 < A.calibration(rows2, ref)["free"]["L-int-s"]["cov90"] < 0.97
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'L-int-s'

tests/v9/experiments/test_s4_analysis.py:361: KeyError
=========================== short test summary info ============================
FAILED tests/v9/experiments/test_s4_analysis.py::test_calibration_rows_and_references
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 61 passed in 14.63s
```

#### 变异 2 原始测试输出：`an_calib_rows_var_constant`
```text
=================================== FAILURES ===================================
____________________ test_calibration_rows_and_references _____________________

ep = <ainerzero.v9.experiments.s4.world.Episode object at 0x1034f5970>

    def test_calibration_rows_and_references(ep) -> None:
        rows = A.calib_rows(ep, _mean_var(0.05, 0.3), np.random.default_rng(1))
        n = 299 * 6
        assert len(rows["kind"]) == n and rows["err"].shape == (n, 2) and rows["var"].shape == (n, 2)
        assert set(np.unique(rows["kind"])) == {0, 1, 2}
        ref = A.fit_references(rows)
        cg = rows["kind"] <= 1
        assert ref["constant"] == pytest.approx(float((rows["err"][cg] ** 2).mean()))
        assert ref["oracle"][1] == pytest.approx(float((rows["err"][~cg] ** 2).mean()))
        assert len(ref["bins"]) == len(A.CALIB_BINS) - 1
        cal = A.calibration(rows, ref)
        assert set(cal) == {"collision", "graze", "free", "collision+graze"}
        assert cal["collision"]["n"] + cal["graze"]["n"] + cal["free"]["n"] == n
        # fitted on these rows, the oracle is the best of the references on collision+graze
        cgv = cal["collision+graze"]
        assert cgv["oracle"]["nll"] <= cgv["constant"]["nll"] + 1e-9
        # a variance matching the free-step error covers about 90% of free steps
        free_sd = float(np.sqrt((rows["err"][rows["kind"] == 2] ** 2).mean()))
        rows2 = A.calib_rows(ep, _mean_var(0.05, free_sd), np.random.default_rng(1))
>       assert 0.8 < A.calibration(rows2, ref)["free"]["L-int-s"]["cov90"] < 0.97
E       assert 0.9869513641755635 < 0.97

tests/v9/experiments/test_s4_analysis.py:361: AssertionError
=========================== short test summary info ============================
FAILED tests/v9/experiments/test_s4_analysis.py::test_calibration_rows_and_references
!!!!!!!!!!!!!!!!!!!!!!!!!! stopping after 1 failures !!!!!!!!!!!!!!!!!!!!!!!!!!!
1 failed, 61 passed in 14.59s
```

---

## 八、验收建议

提交 `a95f196` 的改动原因明确、诊断数据完全复核属实、代码调用清理彻底、未动及任何假设门与合法性门、测试防护严密。作者自测 8 个变异及本次独立执行的 2 个全新变异均 100% 击杀。

**建议统筹亮绿灯验收通过（RECOMMEND_ACCEPT）。**
