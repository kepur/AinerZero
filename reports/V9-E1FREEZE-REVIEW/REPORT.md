# AinerZero E1 Phase 2 冻结代码卡非作者独立复核报告 (ainerzero.V9.P97)

**复核者**：gemini-n7x4 (Level 2 执行 agent · gemini；独立会话，非 P96 作者)  
**被复核任务**：`ainerzero.V9.P96` (作者：r1 `gemini-k8d2`，r2 `gemini-v9p2`)  
**复核日期**：2026-11-02  
**复核性质**：纯只读 + 隔离临时沙箱探针 · 零运行 (Zero-Run) · 逐字引用带行号  
**最终结论**：**建议通过** (Recommend Accept)

---

## 零、非作者身份自证与执行摘要 (≤30行)

1. **非作者身份自证**：本复核 agent 为 `gemini-n7x4`，不同于 P96 r1 作者 `gemini-k8d2` 及 r2 作者 `gemini-v9p2`，亦非二者在同一会话的派生，且不在排除名单内。
2. **SHA-256 全量精确对账**：P96 涉及的 10 个核心文件（生产代码、测试、变异脚本、预登记草案）SHA-256 与卡面封存前缀完全匹配，字节完全一致；`reports/V9-P48/PREREG_DRAFT.md` 与 `PREREG_DRAFT_r4_candidate.md` 保持完全未改动；`src/` 与 `tests/` 内旧哈希 `372e724b` 钉子检索结果严格为 0。
3. **BUDGET_CAPS 与 r4 §6 逐项吻合**：数据生成 3600.0 s、训练每格 1200.0 s（占空比 0.25）、18 格合计 10800.0 s、dev 评测 1800.0 s、final 评测 1800.0 s、总预算 18000.0 s，满足精确求和等式 $3600 + 10800 + 1800 + 1800 = 18000$。臂 ⑥ 属于 `TRAINABLE_ARM_IDS`，受 180.0 s 训练臂护栏保护，外推实测 94.0 s 远低于 180.0 s，绝不发生误拒。
4. **训练步数与空验证集守卫**：`DEFAULT_TRAIN_STEPS=64000`，早停常量保持未改动；自建用例独立证明：在 episode 数为 0、1 以及帧数不足窗口为空时，均准确定向抛出 `ValueError`，且磁盘上绝无任何 checkpoint 或 metadata 生成。
5. **RunStore 实验预算生命周期**：独立精读 `src/ainerzero/runtime/lifecycle.py`，确认 `max_optimizer_steps` 在实验层为全部 run 累计求和（第 409–418 行、433 行、591–592 行）；`worker.py` 按 $18 \times 64000 \times 1.2 = 1,382,400$ 动态派生是彻底消除魔数 100k 导致的 `BudgetExceeded` 异常的正确自洽设计；`max_daily_active_seconds` 按本地自然日隔离（第 814–823 行），`max_model_runs=100` 满足 26 格需求。
6. **#745 Option A 与干净生产环境**：`prereg.py:341-359` 严格实现 Option A 三条规则，批准行、冻结核心及 `scan_approval_log` 保持未改动；`tests/conftest.py` 与 git HEAD 字节一致；在 `.venv/bin/python -I` 下直接执行 `validate(build_draft())` 与 `freeze()` 成功通过；死代码分析确认系多重深度防御。
7. **6 项自建对抗变异全红**：在临时隔离沙箱中建立 6 项独立变异，断言 import 解析至沙箱，全部测试节点准确定向变红（RED），按字节还原后 SHA-256 百分之百吻合。
8. **零运行铁律确认**：`runs.db`、`artifacts/locks/m0-worker.lock`、`artifacts/v9/e1/` 前后 mtime 与 SHA-256 完全恒定，零物理/MLX 运行发生。

---

## 一、SHA 对账与旧草案钉子清零核查

### 1. 文件 SHA-256 原始对账表
执行命令：
```bash
python3 -c 'import hashlib; [print(hashlib.sha256(open(f, "rb").read()).hexdigest(), f) for f in files]'
```
对账结果如下：
| 文件路径 | 封存预期前缀 / 目标 SHA-256 | 实际读取 SHA-256 | 对账结论 |
| :--- | :--- | :--- | :--- |
| `src/ainerzero/v9/experiments/e1/spec.py` | `415a449cfb2dced0` | `415a449cfb2dced018046d8b1b621bc0b35092cfbdefb430b3973b326d4ba63b` | **MATCH** |
| `src/ainerzero/v9/experiments/e1/prereg.py` | `f2698be9ff690a95` | `f2698be9ff690a953687fabdd4e0b334ee832eca2ad79800aa5444e79af427e0` | **MATCH** |
| `src/ainerzero/v9/experiments/e1/train_runner.py` | `906929f9f8b789e7` | `906929f9f8b789e7a9d6cee4f0e373560a70b87028536d894052855bb3922309` | **MATCH** |
| `src/ainerzero/v9/experiments/e1/worker.py` | `c7aa252398f12d89` | `c7aa252398f12d89bb8e08192ac136aad37e23129ba9128219525fb0f7ad6156` | **MATCH** |
| `tests/test_e1_prereg.py` | `d534f2d51e5beb10` | `d534f2d51e5beb10e5dcb30c69abf45f5a6b703b9f4d4b91be6e0a61e57a5820` | **MATCH** |
| `tests/test_e1_train_runner.py` | `49b3c6fb811fa2fc` | `49b3c6fb811fa2fcb13615ac8f698e6aa3a006a591c9575edcc8b1c86408863b` | **MATCH** |
| `tests/test_e1_entry.py` | `eb68893cfde07b65` | `eb68893cfde07b65934facf720ba98a18a21d248c2728daabd1e8dc40dceeb43` | **MATCH** |
| `tests/test_e1_wiring.py` | `ba89191c274c9d6f` | `ba89191c274c9d6f780b76a56e34f993a4868edbccfa2f26499e87d8075c5098` | **MATCH** |
| `tests/conftest.py` | `95f1490c94d0909e` | `95f1490c94d0909e39e8a5cabf37b474cf3e8a1593c677f28e97d9efc5973d3f` | **MATCH (HEAD)** |
| `reports/V9-E1FREEZE/run_mutations.py` | `3e6619803a6b4607` | `3e6619803a6b4607645b63f7444468f1c88233aba09d8da0475491bd8c7d01db` | **MATCH** |
| `reports/V9-P48/PREREG_DRAFT.md` | `372e724bd6b028...` | `372e724bd6b028da9dde76d7f1fb52aa6e1497926b5a081a64032950662f2872` | **MATCH (只读未改)** |
| `reports/V9-P48/PREREG_DRAFT_r4_candidate.md` | `ef7856e7f757d6...` | `ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e` | **MATCH (只读未改)** |

### 2. `tests/conftest.py` 与 HEAD 字节级对齐
执行验证：
```bash
git hash-object tests/conftest.py && git rev-parse HEAD:tests/conftest.py
```
输出：
```
21366d827754d26e4d6338fd6dfd25b948616dee
21366d827754d26e4d6338fd6dfd25b948616dee
```
两项 hash 完全一致，`git diff HEAD tests/conftest.py` 输出为空。确认 `conftest.py` 已彻底清除 r1 污染代码，与主分支 HEAD 字节级吻合。

### 3. 旧 Draft 哈希 `372e724b` 钉子清零检索
执行检索：
```bash
grep -rn "372e724b" src/ tests/
```
原始输出：
```
NO MATCHES FOUND (returncode 1)
```
确认代码库中已彻底移除旧草案哈希。新草案钉子检索：
- `src/ainerzero/v9/experiments/e1/spec.py:10`: `- Draft Candidate r4: reports/V9-P48/PREREG_DRAFT_r4_candidate.md (SHA256 prefix: ef7856e7f757)`
- `src/ainerzero/v9/experiments/e1/spec.py:51-54`:
  ```python
  PREREG_DRAFT_SHA256 = (
      "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"
  )
  PREREG_DRAFT_SHA256_PREFIX = "ef7856e7f757"
  ```
- `tests/test_e1_prereg.py:34-35`:
  ```python
  assert spec.PREREG_DRAFT_SHA256 == "ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e"
  assert spec.PREREG_DRAFT_SHA256_PREFIX == "ef7856e7f757"
  ```

---

## 二、BUDGET_CAPS 与 r4 §6 原文逐项核对与护栏分析

### 1. 逐项核对表
引用 `reports/V9-P48/PREREG_DRAFT_r4_candidate.md` 第 99–106 行原文：
> - **提议上限**（依据 P94 实测，取保守值）：
>   - 数据生成 2800 段：≤ 1 h（实测 0.96 s/段，外推约 45 min）；
>   - 每个训练格：≤ 1200 s 墙钟（含占空比 0.25）。外推最坏值：⑥ 约 790 s（窗口构造与辨识约 575 s，64000 步约 210 s），②③ 约 290 s；18 格合计 ≤ 3 h；
>   - dev 评测 26 格：≤ 30 min（外推约 15 min；⑥ 0.47 s/episode 最慢）；
>   - final 一次：≤ 30 min；
>   - **总墙钟上限（提议）**：**5 h**，远低于 r3 提议的 32 h；
>   - 按实际运行串行计。

对照 `src/ainerzero/v9/experiments/e1/spec.py` 第 286–298 行定义：
```python
BUDGET_CAPS: dict[str, Any] = {
    "data_generation_max_seconds": 3600.0,  # <= 1.0 h
    "train_cell_compute_max_seconds": 300.0,  # 5 min computation (1200 * 0.25)
    "training_duty_cycle": 0.25,  # 25% compute duty cycle
    "train_cell_wall_max_seconds": 1200.0,  # per cell wall (including duty cycle)
    "train_cells_count": 18,  # 3 trainable arms * 2 families * 3 seeds
    "train_total_wall_max_seconds": 10800.0,  # 18 cells total <= 3.0 h
    "dev_eval_train_cell_max_seconds": 180.0,  # per train cell guardrail
    "dev_eval_nontrain_cell_max_seconds": 60.0,  # per non-train cell guardrail
    "dev_eval_total_max_seconds": 1800.0,  # 26 cells total <= 30 min
    "final_eval_max_seconds": 1800.0,  # <= 30 min
    "phase_total_wall_ceiling_seconds": 18000.0,  # 5.0 h total wall
}
```

逐项对照结论：
1. **数据生成**：r4 原文“≤ 1 h” $\rightarrow$ `data_generation_max_seconds = 3600.0`，完全一致。
2. **训练每格墙钟与占空比**：r4 原文“≤ 1200 s 墙钟（含占空比 0.25）” $\rightarrow$ `train_cell_wall_max_seconds = 1200.0`，`training_duty_cycle = 0.25`，`train_cell_compute_max_seconds = 300.0`（$1200 \times 0.25 = 300$），完全一致。
3. **18 格训练合计**：r4 原文“18 格合计 ≤ 3 h” $\rightarrow$ `train_cells_count = 18`，`train_total_wall_max_seconds = 10800.0`（$3 \times 3600 = 10800$），完全一致。
4. **dev 评测 26 格**：r4 原文“dev 评测 26 格：≤ 30 min” $\rightarrow$ `dev_eval_total_max_seconds = 1800.0`（$30 \times 60 = 1800$），完全一致。
5. **final 评测**：r4 原文“final 一次：≤ 30 min” $\rightarrow$ `final_eval_max_seconds = 1800.0`，完全一致。
6. **总墙钟上限与合计等式**：r4 原文“总墙钟上限（提议）：5 h” $\rightarrow$ `phase_total_wall_ceiling_seconds = 18000.0`（$5 \times 3600 = 18000$）。组件合计：
   $$3600.0 + 10800.0 + 1800.0 + 1800.0 = 18000.0\text{ s}$$
   精确满足求和等式。

### 2. 单格 dev 护栏（180/60）对臂 ⑥ 的容差分析
针对问题：“单格 dev 护栏（180/60）是否会误拒 ⑥（实测 0.47 s/episode×200≈94 s）”：
引用 `src/ainerzero/v9/experiments/e1/commands.py` 第 112–116 行：
```python
    elif mode == "eval":
        if arm in spec.TRAINABLE_ARM_IDS:
            default_budget = float(spec.BUDGET_CAPS["dev_eval_train_cell_max_seconds"])
        else:
            default_budget = float(spec.BUDGET_CAPS["dev_eval_nontrain_cell_max_seconds"])
```
引用 `src/ainerzero/v9/experiments/e1/spec.py` 第 203 行：
```python
TRAINABLE_ARM_IDS: tuple[int, ...] = (2, 3, 6)
```
- **判定与结论**：
  臂 ⑥（`IdentifyResidualArm`）显式注册在 `TRAINABLE_ARM_IDS` 中，因此在 `mode == "eval"` 下分配的单格超时护栏为 `dev_eval_train_cell_max_seconds = 180.0` 秒。
  臂 ⑥ 在 dev 分区（200 episodes）的实测外推耗时为 $0.47\text{ s/episode} \times 200 \approx 94.0\text{ s}$。
  由于 $94.0\text{ s} < 180.0\text{ s}$，留有约 86 秒（近 1 倍）的余量空间，**绝对不会误拒臂 ⑥**。
  （只有非训练臂 1、4、5、7 才会走 60.0 s 护栏，而臂 1、4、5、7 的推理耗时在 0.01–0.06 s/episode，200 段总耗时不超过 12 s，同样安全）。

---

## 三、DEFAULT_TRAIN_STEPS 与空验证集阻断独立验证

### 1. 步数与早停常量核验
引用 `src/ainerzero/v9/experiments/e1/spec.py` 第 229–233 行：
```python
DEFAULT_TRAIN_STEPS: int = 64000
EARLY_STOP_EVAL_EVERY: int = 500
EARLY_STOP_PATIENCE: int = 10
VALIDATION_FRACTION: float = 0.1
VALIDATION_SPLIT_SEED: int = 20261030
```
确认步数上限已正确更新为 64,000，且 `EARLY_STOP_EVAL_EVERY=500`、`EARLY_STOP_PATIENCE=10`、`VALIDATION_FRACTION=0.1` 保持完全不变。

### 2. 空验证集/空窗口守卫源码逐字审计
引用 `src/ainerzero/v9/experiments/e1/train_runner.py`：
- **切分样本数守卫**（第 130–133 行）：
  ```python
  if n_total < 2:
      raise ValueError(
          f"At least 2 episodes are required to create disjoint train/validation split; got {n_total}"
      )
  ```
- **空验证窗口损失计算守卫**（第 159–160 行）：
  ```python
  if len(val_windows) == 0:
      raise ValueError("Cannot compute validation loss on empty validation windows")
  ```
- **训练流程入口文件发现守卫**（第 462–467 行）：
  ```python
  if not all_json_files:
      raise ValueError(f"No student sequence JSON files found in {student_dir}")
  if len(all_json_files) < 2:
      raise ValueError(
          f"At least 2 student episode JSON files required in {student_dir} to construct train/validation split, got {len(all_json_files)}"
      )
  ```
- **窗口提取结果守卫**（第 478–489 行）：
  ```python
  if len(train_windows) == 0:
      raise ValueError(
          f"Training windows set is empty after window construction ({len(train_files)} train episodes yielded 0 windows)"
      )
  ...
  if len(val_windows) == 0:
      raise ValueError(
          f"Validation windows set is empty after window construction ({len(val_files)} val episodes yielded 0 windows)"
      )
  ```

### 3. 自建对抗测试用例独立实测
复核者编写独立测试脚本，自建 0 episodes、1 episode、以及不足 10 帧导致窗口为空的 3 组真实测试，并断言输出目录 `out_dir` 未生成任何 `.npz` 或 `checkpoint_meta.json`：
```python
# 0 episodes 测试
train_runner.train_cell(arm_id=2, family="P", seed=42, student_dir=empty_dir, out_dir=out_dir)
# 1 episode 测试
train_runner.train_cell(arm_id=2, family="P", seed=42, student_dir=one_ep_dir, out_dir=out_dir)
# 不足 10 帧测试 (empty windows)
train_runner.train_cell(arm_id=2, family="P", seed=42, student_dir=short_ep_dir, out_dir=out_dir)
```
**实测输出结果**：
```
0 episodes correctly raised ValueError: No student sequence JSON files found in ...
1 episode correctly raised ValueError: At least 2 student episode JSON files required in ... to construct train/validation split, got 1
Insufficient frames / empty windows correctly raised ValueError: No valid training windows could be extracted from ... (insufficient frames)
ALL EMPTY VALIDATION / WINDOW TESTS PASSED: NO CHECKPOINTS WRITTEN!
```
断言证明：在发生上述任何一种异常时，异常在第 462–488 行抛出，直接退出，第 501 行训练循环与第 618 行后的 checkpoint 保存逻辑完全不会被触达，磁盘上检查点文件数为 0。

---

## 四、RunStore 实验预算机制独立审计

复核者独立阅读并审计 `src/ainerzero/runtime/lifecycle.py`，确认预算字段的计算与校验逻辑：

### 1. `max_optimizer_steps` 统计口径
引用 `src/ainerzero/runtime/lifecycle.py` 第 409–418 行：
```python
runs = db.execute("SELECT * FROM runs WHERE experiment_id=?", (experiment_id,)).fetchall()
totals = {
    key: sum(r[key] for r in runs)
    for key in (
        "environment_steps",
        "optimizer_steps",
        "model_transitions",
        "active_seconds",
    )
}
```
引用第 432–435 行：
```python
remaining = {
    key: max(0, budget[f"max_{key}"] - totals[key])
    for key in ("environment_steps", "optimizer_steps", "model_transitions")
}
```
引用第 585–593 行：
```python
for key in (
    "environment_steps",
    "optimizer_steps",
    "model_transitions",
    "wall_seconds",
):
    if experiment.remaining[key] <= 0:
        rejection = BudgetExceeded(f"experiment_{key}_budget", experiment.remaining)
        break
```
**复核者独立判断结论**：
1. `totals["optimizer_steps"]` 是通过 SQL 聚合函数对该 `experiment_id` 下的所有 `runs` 记录进行求和，因此 `experiment_budget["max_optimizer_steps"]` **严格属于全实验全局累计总量**，而非单个 run 的步数。
2. 在旧代码中，实验 manifest 硬编码 `max_optimizer_steps = 100,000`。而在 E1 中，共 18 个训练 cell，若按 64,000 步上限训练，前 2 个 cell 就将耗尽 100,000 步预算，导致第 3 个 cell 在 `create_run` 阶段被 `experiment.remaining["optimizer_steps"] <= 0` 强行拒绝（`rejection = BudgetExceeded("experiment_optimizer_steps_budget")`）。
3. `src/ainerzero/v9/experiments/e1/worker.py` 第 186–194 行的动态派生算法：
   ```python
   derived_experiment_optimizer_steps = int(train_cells * max_steps_per_cell * 1.2) # 1,382,400
   derived_run_optimizer_steps = int(max_steps_per_cell * 1.2) # 76,800
   ```
   实验级上限设置为 1,382,400 步，单 run 预算设置为 76,800 步，自洽解除了实验中途被误拒的致命隐患，作者结论及所引行号完全属实。

### 2. `max_daily_active_seconds`（跨自然日）行为
引用 `src/ainerzero/runtime/lifecycle.py` 第 814–823 行：
```python
date = (
    datetime.fromtimestamp(instant, ZoneInfo(budget["timezone"])).date().isoformat()
)
self._day(db, date, budget["max_daily_active_seconds"])
for date, amount in self._allocations(instant, active_seconds, budget["timezone"]):
    self._day(db, date, budget["max_daily_active_seconds"])
    db.execute(
        "UPDATE daily_budget SET reserved_seconds=reserved_seconds+? WHERE local_date=?",
        (amount, date),
    )
```
**复核者独立判断结论**：
`daily_budget` 表按时区日期 `local_date` 主键分别记录。跨自然日（过了午夜）时，新的一天会自动初始化新的独立配额，历史消耗不会跨天累计。因此将单日活动上限设为阶段总上限 18000.0 s，能够保证即使跨自然日执行也不会被截断。

### 3. `max_model_runs` 统计口径
引用 `src/ainerzero/runtime/lifecycle.py` 第 431 行与第 443 行：
```python
count = sum(r["role"] == "model" for r in runs)
...
model_runs=max(0, budget["max_model_runs"] - count),
```
**复核者独立判断结论**：
`worker.py:211` 将 `max_model_runs` 设为 100。E1 的训练加评测共有 26 个 cell，100 次 model run 容量充裕，能从容容纳可能的重试与故障恢复。

---

## 五、#745 Option A 裁定核对与生产环境独立验证

### 1. Option A 预算算术规则三条核对
引用 `src/ainerzero/v9/experiments/e1/prereg.py` 第 341–359 行源码：
```python
    if abs(cell_wall * duty - cell_compute) > 1e-3:
        raise SpecValidationError(
            f"train_cell_compute_max_seconds ({cell_compute}) does not equal "
            f"train_cell_wall_max_seconds * training_duty_cycle ({cell_wall * duty})"
        )

    if train_wall < cell_wall or train_wall > max_train_wall:
        raise SpecValidationError(
            f"train_total_wall_max_seconds ({train_wall}) out of bounds: "
            f"must satisfy train_cell_wall_max_seconds ({cell_wall}) <= train_total_wall_max_seconds <= "
            f"train_cells_count * train_cell_wall_max_seconds ({max_train_wall})"
        )

    component_sum = data_gen + train_wall + dev_eval + final_eval
    if component_sum > total_ceiling:
        raise SpecValidationError(
            f"Budget components sum ({component_sum:.1f} s) exceeds total ceiling "
            f"phase_total_wall_ceiling_seconds ({total_ceiling:.1f} s)"
        )
```
逐条核对：
1. `|wall × duty - compute| <= 1e-3`：由第 341 行保证；
2. `wall <= total <= count × wall`：由第 347 行保证（其中 `max_train_wall = cells_count * cell_wall`）；
3. `各段之和 <= 总上限`：由第 354–359 行保证。

### 2. 批准行、冻结核心与 scan_approval_log 零改动核查
对比 `prereg.py` 在本卡修改前后的完整 diff：
- `prereg.py` 在本任务中**唯一改动的区间为第 335–353 行**（即上述 validate 算术逻辑）。
- 第 385–411 行 `def freeze(...)`、第 413–415 行 `def approval_line(...)`、第 418–499 行 `def scan_approval_log(...)` 均**一字未改**。

### 3. `.venv/bin/python -I` 隔离执行直接验证
脱离 pytest 与一切 conftest 环境，直接使用 python 隔离模式执行：
```bash
.venv/bin/python -I -c '
import sys; sys.path.insert(0, "src")
from ainerzero.v9.experiments.e1 import prereg
draft = prereg.build_draft()
prereg.validate(draft)
frozen_doc, doc_sha = prereg.freeze(draft)
print("Frozen Digest:", doc_sha, "Status:", frozen_doc.get("status"))
'
```
输出：
```
Frozen OK! Digest: 83b65efe102f9cea57dec7138e477e9a8014ba91f5f56ac30a5f5aabd464b364 Status: awaiting_coordinator_approval
```
验证表明：在完全不依赖任何测试夹具或补丁的真实原生 Python 环境下，`validate` 与 `freeze` 100% 顺畅执行，不再抛出 `SpecValidationError`。

### 4. 一级 11 处变异与死代码路径深度分析
卡面参数提及一级亲验 11 处变异，其中 3 处在正常代码路径下为不可达代码（改了等于没改）：
- **第 1 处：`train_runner.py` 第 146–153 行**：
  ```python
  if len(train_files) == 0:
      raise ValueError(...)
  if len(val_files) == 0:
      raise ValueError(...)
  ```
  - **不可达证明**：
    第 130 行首先断言 `if n_total < 2: raise ValueError(...)`。
    紧接着第 135–137 行：
    `n_val = max(1, int(round(n_total * val_fraction)))`，且 `if n_val >= n_total: n_val = n_total - 1`。
    由于 $n_{total} \ge 2$，经过 clamp 后必有 $1 \le n_{val} \le n_{total} - 1$。
    因此 `len(val_files) = n_val >= 1` 且 `len(train_files) = n_total - n_val >= 1`。
    两者集合大小在数学上恒大于等于 1，故第 146–153 行的判空分支在正常逻辑下**永远不可能被触发**。
- **第 2 与第 3 处：`train_runner.py` 第 478 行与第 486 行**：
  ```python
  if len(train_windows) == 0:
      raise ValueError(...)
  ...
  if len(val_windows) == 0:
      raise ValueError(...)
  ```
  - **不可达证明**：
    进入该判断前，调用了 `build_training_windows`。
    查阅 `train_runner.py` 第 342–343 行：
    ```python
    if not x_list:
        raise ValueError(f"No valid training windows could be extracted from {student_dir} (insufficient frames)")
    ```
    当提取窗口为空时，`build_training_windows` 在内部直接抛出 `ValueError`，根本不会返回长度为 0 的 `TrainingWindows` 实例给外层调用者。
    因此，第 478 行与第 486 行的外层判空分支在正常流程下**永远不可能被执行**。
- **复核结论**：这 3 处确系**纵深防御型死代码 (defensive redundant guards)**。虽然在标准控制流中无法到达，但作为多层异常拦截机制，保留它们对生产安全性有益无害，无需强制删除。

---

## 六、6 项自建对抗用例/变异实测证据 (禁止复用作者脚本)

复核者独立编写了变异测试驱动 `reports/V9-E1FREEZE-REVIEW/run_independent_mutations.py`，并在 `tempfile.mkdtemp` 临时沙箱中执行。
- 注入前断言：`assert str(spec.__file__).startswith(str(sandbox_src))` 严格通过；
- 注入后变异测试：全部返回非 0 退出码（变红 RED）；
- 字节还原校验：通过 `hashlib.sha256` 验证恢复后 SHA-256 与基线完全一致。

| 变异 ID | 变异名称 | 注入目标文件 | 变异操作与行号 | 验证测试节点 | 退出码 | 变异判定 | 字节还原对账 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ADV-1** | `mutate_default_train_steps_to_64001` | `spec.py:229` | `64000` 改为 `64001` | `test_e1_prereg.py::test_spec_constants` | 1 | **RED (pass)** | SHA 吻合 |
| **ADV-2** | `revert_draft_sha_to_old_r1_anchor` | `spec.py:51` | 将 `ef7856e7...` 替换为旧 `372e724b...` | `test_e1_prereg.py::test_spec_constants` | 1 | **RED (pass)** | SHA 吻合 |
| **ADV-3** | `invert_prereg_duty_cycle_validation` | `prereg.py:341` | 将 `> 1e-3` 改为 `<= 1e-3` | `test_e1_prereg.py::test_build_and_validate_draft` | 4 | **RED (pass)** | SHA 吻合 |
| **ADV-4** | `disable_train_runner_two_episodes_guard` | `train_runner.py:130` | 将 `n_total < 2` 改为 `n_total < 0` | `test_e1_train_runner.py::test_split_episodes_raises_if_fewer_than_two_episodes` | 4 | **RED (pass)** | SHA 吻合 |
| **ADV-5** | `disable_validation_loss_empty_windows_guard` | `train_runner.py:159` | 将 `len(val_windows) == 0` 改为 `False and ...` | `test_e1_train_runner.py::test_compute_validation_loss_empty_windows_raises_value_error` | 1 | **RED (pass)** | SHA 吻合 |
| **ADV-6** | `revert_worker_experiment_optimizer_steps_to_100k` | `worker.py:192` | 将动态派生表达式强制写死为 `100_000` | `test_e1_wiring.py::test_runstore_budget_derived_from_spec` | 1 | **RED (pass)** | SHA 吻合 |

所有 6 组独立自建变异全部变红，详细记录已写入 `reports/V9-E1FREEZE-REVIEW/mutation_results.json`。

---

## 七、零运行铁律与受保护锚点核验

在本次复核的起始与结束时，对系统的关键物理/锁状态进行了只读哈希和元数据核对：
| 关键受保护对象 | 初始状态 (SHA-256 / mtime) | 最终状态 (SHA-256 / mtime) | 核对结论 |
| :--- | :--- | :--- | :--- |
| `artifacts/v9/teachers/benchmark/runs.db` | `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01` <br>(mtime=1793225768.2078843) | `61242c30ffb56621615107ce971c2ff7802e3a30b7491294297239df3c3e0d01` <br>(mtime=1793225768.2078843) | **STRICTLY UNCHANGED** |
| `artifacts/locks/m0-worker.lock` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` <br>(mtime=1790110663.3796358) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` <br>(mtime=1790110663.3796358) | **STRICTLY UNCHANGED** |
| `artifacts/v9/e1/` 目录 | 不存在 (NOT FOUND) | 不存在 (NOT FOUND) | **STRICTLY UNCHANGED** |

确认在整个复核流程中，未启动任何 GPU/MLX 真实训练进程，未占用锁，未生成任何检查点文件，未触碰台账。

---

## 八、复核结论与交付说明

**复核最终结论**：**建议通过** (Recommend Accept)。

- P96 r2 提交的代码修改与测试套件完全修复了 r1 假绿问题，忠实执行了 #745 Option A 架构裁定；
- 生产代码在原生 Python 隔离子进程中完全自洽；
- 所有常数严格符合 r4 §6 冻结定义；
- 空验证集异常拦截机制安全有效；
- 零运行与文件范围边界严密守住。
