# 任务执行报告：ainerzero.V9.T56

## 一、概述（Executive Summary）
- **任务编号**：`ainerzero.V9.T56`
- **执行者身份**：二级执行 agent `gemini-r4x9`（kind: `gemini`）
- **工作目标**：
  1. `da3_calibration_runner.py`：当存在 T28 登记（`reports/V9-T28/REGISTERED.json`）时，核对加载的 proposal SHA256 与登记的 sha256 严格一致；任何不符（无论通过 `--proposal` 还是 `T6_PROPOSAL_PATH` 传入）均拒绝并返回非零退出码（`EXIT_PREFLIGHT = 2`）。默认 proposal 优先选择登记中的 `proposal_path`（当前为 `proposal.r2.json`），未登记时回退至 r1。
  2. `da3_controlled.py`：
     - `is_da3_ledger_run`：若 run 记录缺失或为 null 的 `model` 字段，一律视作损坏账本并抛出 `BenchmarkRefusalError`。
     - 诊断隔离：非 DA3 运行排除在配额累计之外，但新增 `query_t6_ledger_with_diagnostics(store_path)` 将非 DA3 记录全量收集至诊断字典返回，且保持只读函数 `query_t6_ledger_read_only` 签名不变。
     - 任务卡记录：新增运行配置记录 `card: os.environ.get("DA3_TASK_ID")`（未设置则为 None），纯记账且无预算/配额副作用。
- **验证结果**：
  - CPU 单元测试：`tests/test_da3_*.py`、`tests/test_t28_*.py`、`tests/test_teacher_da3_controlled.py` 共 103 项全部通过（103 passed in 78.58s）。
  - 坏对照（Adverse Controls）：构建并运行两个隔离变异体（Mutant 1 移除登记 SHA 核验；Mutant 2 允许缺失 model），两个变异体均严格转红（RED / Exit Code 1），日志已落盘。
  - 零模型与零账本守则：全程 0 真实模型调用、0 GPU 占有、0 写入中央 `runs.db`、0 触碰 `m0-worker.lock`。

---

## 二、代码修改与精确引用（Verbatim Citations）

### 1. `src/ainerzero/v9/teachers/da3_calibration_runner.py`
- **默认 proposal 路径选择**（行 106-123）：
  ```python
  def get_default_proposal_path() -> Path:
      env_prop = os.environ.get("T6_PROPOSAL_PATH")
      if env_prop:
          return Path(env_prop).resolve()
      from ainerzero.v9.teachers import t28_registration
      try:
          reg_info = t28_registration.load_t28_registration()
          if reg_info.is_registered and reg_info.proposal_path:
              candidate = Path(reg_info.proposal_path)
              if candidate.is_file():
                  return candidate.resolve()
      except Exception:
          pass
      return (REPO_ROOT / "reports/V9-T28/proposal.json").resolve()
  ```
- **登记 SHA 严格比对**（行 137-151）：
  ```python
  if verify_hashes:
      from ainerzero.v9.teachers import t28_registration
      try:
          reg_info = t28_registration.load_t28_registration()
      except Exception as exc:
          raise PreflightError(f"Failed to read T28 registration: {exc}") from exc
      if reg_info.is_registered:
          expected_reg_sha = (reg_info.sha256 or "").strip().lower()
          actual_prop_sha = shas["proposal"].strip().lower()
          if actual_prop_sha != expected_reg_sha:
              raise PreflightError(
                  f"T28 proposal SHA256 mismatch with registration: "
                  f"loaded proposal {proposal_path} ({actual_prop_sha}) != "
                  f"registered SHA256 ({expected_reg_sha})"
              )
  ```
- **Preflight 退出码拦截**（行 486-492 & 509-514）：
  ```python
  try:
      plan = load_plan(target_proposal)
  except PreflightError as exc:
      print(f"PREFLIGHT REFUSAL: {exc}", file=sys.stderr)
      return EXIT_PREFLIGHT
  ```

### 2. `src/ainerzero/v9/teachers/da3_controlled.py`
- **缺 model 字段拒绝**（行 425-436）：
  ```python
  if not isinstance(cfg, dict) or "model" not in cfg or cfg["model"] is None:
      raise BenchmarkRefusalError(
          "Damaged ledger run config: missing or null 'model' field in RunStore entry",
          details={"config": cfg},
      )

  model = cfg["model"]
  if not isinstance(model, str) or not model.strip():
      raise BenchmarkRefusalError(
          "Damaged ledger run config: invalid or non-string 'model' field in RunStore entry",
          details={"config": cfg},
      )
  ```
- **诊断视图查询与非 DA3 隔离**（行 489-534）：
  ```python
  def query_t6_ledger_with_diagnostics(store_path: Path) -> dict[str, Any]:
      ...
      da3_runs: list[dict[str, Any]] = []
      non_da3_runs: list[dict[str, Any]] = []
      for run_id in run_ids:
          run_record = store.get_run(run_id)
          ...
          if is_da3_ledger_run(cfg):
              da3_runs.append(entry)
              total_seconds += max(0.0, float(cfg.get("wall_budget_seconds", 0.0) or 0.0))
              total_views += max(0, int(cfg.get("views", 0) or 0))
          else:
              non_da3_runs.append(entry)
      return {
          "store_path": str(store_path),
          "total_runs_examined": len(run_ids),
          "da3_runs": da3_runs,
          "non_da3_runs": non_da3_runs,
          "cumulative_reserved_seconds": total_seconds,
          "cumulative_views": total_views,
      }
  ```
- **记录 card 环境变量字段**（行 1079-1082）：
  ```python
  "calibration_views": int(spec.calibration_views),
  "wall_budget_seconds": float(spec.wall_budget_seconds),
  "card": os.environ.get("DA3_TASK_ID"),
  ```

---

## 三、测试套件执行情况

### 1. 全量纯 CPU 测试汇总（103 通过）
运行命令：
```bash
.venv/bin/pytest tests/test_da3_*.py tests/test_t28_*.py tests/test_teacher_da3_controlled.py
```
结果输出：
```text
tests/test_da3_calibration_runner.py ................................... [ 33%]
..                                                                       [ 35%]
tests/test_da3_linewide_quota.py ......                                  [ 41%]
tests/test_da3_supervision.py ..........                                 [ 51%]
tests/test_da3_t56_features.py .......                                   [ 58%]
tests/test_da3_views_82.py ..                                            [ 60%]
tests/test_t28_bad_controls_r2.py ....                                   [ 64%]
tests/test_t28_registration_and_quota.py ................                [ 79%]
tests/test_teacher_da3_controlled.py .....................               [100%]

======================== 103 passed in 78.58s (0:01:18) ========================
```

### 2. 专用特性测试（`tests/test_da3_t56_features.py`，7/7 全部通过）
- `test_runner_registered_sha_match_passes`: 默认与登记 SHA 一致时预检通过（退出码 0）。
- `test_runner_registered_sha_mismatch_refused_via_proposal_flag`: `--proposal` 传入篡改/不同 SHA 的 proposal 时拒绝并退出 2（`EXIT_PREFLIGHT`）。
- `test_runner_registered_sha_mismatch_refused_via_env_var`: `T6_PROPOSAL_PATH` 环境变量指定不同 SHA 的 proposal 时拒绝并退出 2。
- `test_runner_no_registration_defaults_to_r1`: 无登记时回退至 r1（因固有控制不可满足安全拒绝退出 6）。
- `test_is_da3_ledger_run_missing_model_refuses`: 缺 `model`、null `model`、空字符串 `model` 均拒绝并抛出 `BenchmarkRefusalError`。
- `test_non_da3_runs_in_diagnostics_and_excluded_from_accounting`: 混杂非 DA3 run 记录时，非 DA3 run 不计入 DA3 秒数与视数配额，但完整包含在 `non_da3_runs` 诊断列表中；只读接口返回正确统计。
- `test_new_run_config_records_card_field`: `execute_guarded_da3_benchmark` 执行时，`DA3_TASK_ID` 环境变量被正确存入 config 快照中的 `card` 字段。

---

## 四、坏对照验证（Adverse Controls）

运行隔离脚本 `reports/V9-T56/gemini-r4x9/run_adversarial_mutants.py`：
- **Mutant 1（移除登记 SHA 核验）**：
  - 变异文件：`reports/V9-T56/gemini-r4x9/mutants/mutant_1_no_sha_check/src/ainerzero/v9/teachers/da3_calibration_runner.py`
  - 目标测试：`tests/test_da3_t56_features.py::test_runner_registered_sha_mismatch_refused_via_proposal_flag`
  - 结果：**RED（Returncode 1，断言退出码 6 != 2 失败）**，日志存储在 `reports/V9-T56/gemini-r4x9/logs/mutant_1_test.log`。
- **Mutant 2（允许缺少 model 字段）**：
  - 变异文件：`reports/V9-T56/gemini-r4x9/mutants/mutant_2_missing_model_allowed/src/ainerzero/v9/teachers/da3_controlled.py`
  - 目标测试：`tests/test_da3_t56_features.py::test_is_da3_ledger_run_missing_model_refuses`
  - 结果：**RED（Returncode 1，`DID NOT RAISE BenchmarkRefusalError`）**，日志存储在 `reports/V9-T56/gemini-r4x9/logs/mutant_2_test.log`。

---

## 五、零模型与零账本守则自查

1. **零模型**：没有调用任何 PyTorch / MLX 权重前向推断，无真实模型计算，全套逻辑均在纯 CPU 环境及合成 fixture / mock 隔离测试。
2. **零账本**：没有修改中央生产数据库 `/Users/mac/AinerWorkFlow/AinerZero/runs.db`，所有测试在独立的 `tmp_path` 临时数据库中执行。
3. **零锁**：未获取或触碰 `/Users/mac/AinerWorkFlow/AinerZero/m0-worker.lock`。
4. **范围隔离**：修改严格限制在指定文件及测试文件，原始未修改备份保存在 `reports/V9-T56/gemini-r4x9/before/`。
