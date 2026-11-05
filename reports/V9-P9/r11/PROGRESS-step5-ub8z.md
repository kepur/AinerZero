# P30 交接：r11 重冻结（执行者 step5-ub8z，因租约过期被 composer-m7k2 接手）

时间：2026-10-23 14:4x（GMT+3）。本文件只记录**已完成**与**剩余**，避免重复劳动。
所有改动都在工作树里（未提交），路径均在卡面 file_scope 内。

## 一、已完成（可直接续做，不要重写）

### 1. 前值归档
`reports/V9-P9/r11/before/`：file_scope 全部 47 个 .py 前值 + `SHA256SUMS.txt`。
（注意：`tests/v9/experiments/` 在 git 中**未跟踪**，`git stash -u` 会把整个测试目录清走——别用 stash 做对照。）

### 2. spec.py（SHA `c42413c8…`）
- `TIMING["eval_batches"]` 48 → **175**。
- 新增 r11 登记块：`R11_EXPERIMENT_ID="s1-phase1-20261023-r11"`、`R11_BUDGET_REGISTRATION`、
  `R11_DEADLINE_SOURCE="user_approved R20261023-S1-phase1-r11-budget"`、
  `R11_REGISTERED_UPDATES=3510`、`R11_REGISTERED_DEADLINE_SECONDS=1200`、`R11_SUPERVISION_SECONDS=1250`、
  `R11_MEASURED_THROUGHPUT`（P1 实测：中位 0.20182、最慢 0.2829 s/步、3510×0.2829=992.98 s、
  1200/992.98=1.2085 约 21% 余量；来源 `reports/V9-S1/metrics.json`，SHA `8b5017c2…`）。

### 3. prereg.py（SHA `d3a60291…`）
- `build_draft(..., experiment_id=None, budget_registration=None)`：r11 登记时写入新实验 ID、
  登记值字段、`timing.rule`/`training_protocol.update_rule`。
- 新增 `registered_budget(smoke)`：登记值路径，fail-closed（登记截止≠1200、超单次上限、
  推导会触发缩步数循环、阶段超 4h 都拒）。
- `build_frozen` 按 `budget_registration` 分支；draft 边界 fail-closed（draft 声明的登记
  updates≠3510 / deadline≠1200 / 实验 ID 不是 r11 → 拒）。
- `validate()`：登记路径下 deadline 必须 =1200、supervision=1250、updates=3510、
  `measured_throughput` 必须与登记测量完全一致、`derived_deadline_seconds`=ceil(1.25×estimate)；
  新增 `training_protocol.eval_batches` 必须等于 `spec.TIMING["eval_batches"]`（175）的 fail-closed。

### 4. worker.py（SHA `23768026…`）+ commands.py（SHA `c66e02c3…`）
- 新增 `document_experiment_id()`（运行登记用的实验 ID，缺省 None）与
  `document_experiment_scope()`（**只有** `spec.R11_EXPERIMENT_ID` 才返回作用域，其余一律 None=全台账）。
- `train_attempts` / `phase_total_wall_seconds` / `phase_ledger_breakdown` / `d_candidate_attempt_state`
  增加 `experiment_id=None` 参数；`_open_train_run`、eval 的 `open_aux_run`/report 用文档实验 ID。
- `commands.mode_train` 双校验入口同步用 `document_experiment_scope`。
- 未改通用 RunStore。

### 5. 测试
- 新增 `tests/v9/experiments/test_s1_r11_registration.py`（17 条，SHA `290d88de…`）：
  登记值冻结、与推导路径对比（推导得 3299/450，登记 3510/1200）、失败关闭（慢 smoke 会触发缩步数、
  登记截止超上限、draft 改值、旧实验 ID）、validate 篡改检测（deadline/updates/throughput/supervision/eval_batches）、
  新实验 attempt=0 且旧实验仍拒、phase wall 作用域、D 守卫作用域、坏控（无作用域时旧行会挡住新实验）。
- 因 `eval_batches` 48→175，4 个既有测试的**夹具**需要跟随（已改）：
  - `test_s1_prereg.py`：`eval_cost` 用 `spec.TIMING["eval_batches"]`；缩步数测试改为
    `monkeypatch.setitem(spec.TRAIN_COMMON, "target_estimate_seconds", 5000)` 才真正进入缩步数循环。
  - `test_s1_r8_d_budget.py`：`TRAIN_STEP=0.006575`、`D_STEP=0.0003`（解出 3510 步/450 s/arm1 2 s 形状）。
  - `test_s1_r8_completion.py`：`REGISTERED_STEP_SECONDS=0.006575`。

### 6. 回归结果（tests/v9 全量，`.venv/bin/python -m pytest tests/v9 -q`）
- 改后：**701 passed / 3 failed**。
- before 归档对照：**684 passed / 3 failed**（同一失败集合）。
- 3 条失败均为既有环境性/数据性，与本卡无关：
  1. `test_s1_r7_phase_accounting::test_the_real_ledger_copy_reproduces_the_old_bug_without_touching_the_original`
     （真实台账已被 r10 运行改写，断言不成立）
  2. `geometry/test_canonical.py::test_cpu_only_imports`、3. `geometry/test_geometry.py::test_imports_are_cpu_only`
     （会话内已有 mlx 进入 sys.modules，顺序相关）

### 7. 已核算的 r11 数值（r1-archive smoke 为测量记录，eval_batches=175）
updates=3510，checkpoint_updates=[0,439,878,1755,3510]，
estimate=381.1528007568777 s，derived_deadline=477 s（推导值，仅登记为对照），
**deadline=1200 s，supervision=1250 s**，arm1 estimate=5.47487220082985 s → arm1_deadline=**7 s**
（卡面说“约 6 s”，公式如实给 7 s，勿手改），arm1_supervision=57 s，
phase_wall=**10854.605202458999 s**（9×1200+7+47.605），余量 3545.39 s ≤ 14400。

## 二、剩余（尚未做）

1. 建 `artifacts/v9/s1/phase1/r11/`，拷入 `dataset_ref.json`（指向真实数据集 8234f2f3…）。
2. 生成 r11 draft（**不要用** `--mode preregister`，它会 import arms→MLX；用程序化重建）：
   ```python
   from ainerzero.v9.experiments.s1 import prereg, spec
   old = json.load(open('artifacts/v9/s1/phase1/draft_preregistration.json'))
   counts = {a: old['arms'][a]['parameter_count'] for a in ('arm1','arm2','arm3','arm4')}
   draft = prereg.build_draft(data_identity=old['data_identity'], parameter_counts=counts,
                              experiment_id=spec.R11_EXPERIMENT_ID,
                              budget_registration=spec.R11_BUDGET_REGISTRATION)
   ```
   写到 `artifacts/v9/s1/phase1/r11/draft_preregistration.json`。
3. 冻结（真实入口）：
   `.venv/bin/python -m ainerzero.cli s1-phase1 --mode freeze --output-root artifacts/v9/s1/phase1/r11 --smoke-metrics reports/V9-P9/r1-archive/smoke_metrics.json`
4. `--mode verify --output-root artifacts/v9/s1/phase1/r11`（真实入口，只读）。
5. train 入口（真实入口，不写台账，无批准行 → 应在 approval 阶段被拒）：
   `--mode train --arm arm2 --seed 0 --prereg artifacts/v9/s1/phase1/r11/pre_registration.json`
6. eval 入口 175 对 175（**必须**用临时主机锚点 + 临时台账，禁止写中央台账）：
   `s1_testkit.install_test_host` + 拷 `dataset_ref.json` 到临时 root + 写 r11 冻结件 + 临时台账建 prep 实验，
   然后 `worker.run_worker("eval", arm="arm2", ...)`（stub backend）。预期：不再 `eval_call_budget_exceeded`，
   而是在 `_bind_completed_run` 处因 r11 尚无完成训练而报 `EvalBindingError`（说明已过 175 检查）。
   对照：同一套用 eval_batches=48 的文档应被 `eval_call_budget_exceeded` 拒（复现 r10 失败）。
7. 报告 `reports/V9-P9/r11/REPORT.md` + 指标 json，SHA 由脚本输出直贴；
   r10→r11 逐叶差异核对（只允许第 2–5 项字段 + 衍生字段）。
8. 交回：`relay report ainerzero.V9.P30 --agent <你的ID> --result-file … --data-file … --next`。

## 三、踩坑记录（别再踩）

- 租约 1200 s：本地连续工作超过 20 分钟必丢任务。**每 ≤10 分钟 heartbeat**，长命令用 relay exec。
- `git stash -u -- tests/v9/experiments` 会清空整个未跟踪测试目录（本卡期间发生过一次，已 pop 还原）。
  做 before/after 对照请用 `reports/V9-P9/r11/before/` 的归档。
- `monkeypatch.setattr(dict_obj, key, v)` 会 AttributeError，dict 用 `monkeypatch.setitem`。
- `dict(spec.R11_MEASURED_THROUGHPUT)` 是浅拷贝，嵌套 dict 会与 spec 常量共享（已改 deepcopy）。
