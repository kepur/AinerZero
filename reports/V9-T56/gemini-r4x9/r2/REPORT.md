# 任务执行报告：ainerzero.V9.T56（r2 修订）

## 一、概述（Executive Summary）
- **任务编号**：`ainerzero.V9.T56`（r2 修订）
- **执行者身份**：二级执行 agent `gemini-r4x9`（kind: `gemini`）
- **打回原因与必改项核销**：
  1. **按路径加载注册模块**：在 `da3_calibration_runner.py` 中移除 `from ainerzero.v9.teachers import t28_registration`，改用与 `_load_math()` 一致的 `importlib.util.spec_from_file_location` 按同级文件路径加载 `t28_registration.py`，彻底消除对 `ainerzero` 包安装及 `PYTHONPATH` 的依赖。
  2. **大声失败不静默退回**：`get_default_proposal_path` 移除 `except Exception: pass` 吞异常行为；当 `REGISTERED.json` 存在但无法读取、格式损坏或 proposal 路径缺失时，显式抛出 `PreflightError`，并在 `main()` 中被捕获返回非零退出码 `EXIT_PREFLIGHT = 2`。
  3. **真实环境集成测试**：在 `tests/test_da3_t56_features.py` 中新增 `test_real_venv_t6_runner_script_execution_without_pythonpath`，直接使用 `envs/teachers/.venv-t6/bin/python` 在无 `PYTHONPATH` 的真实 worker 脚本执行环境下测试：
     - 默认读取当前真实登记（r2）→ 退出码 0（预检通过）；
     - `T6_PROPOSAL_PATH` 指向 r1 → 退出码 2（SHA 不符预检拒绝）；
     - `--proposal` 指向 pre-E18 proposal → 退出码 2（SHA 不符预检拒绝）。
  4. **双坏对照（Adverse Controls）变红验证**：
     - Mutant 1（恢复成 `from ainerzero...`）：在 `.venv-t6` 真实环境下复现 `ModuleNotFoundError`，集成测试严格转红（RED / Exit 1）；
     - Mutant 2（移除登记 SHA 校验）：集成测试中传入 r1 与 pre-E18 时未被预检拦截，集成测试严格转红（RED / Exit 1）。
- **保留项**：`da3_controlled.py` 缺 model 拒绝抛 `BenchmarkRefusalError`、诊断查询函数 `query_t6_ledger_with_diagnostics`、config 中 `card` 记录保持不变。
- **验证结果**：全量 DA3 纯 CPU 测试套件共 105 项全部通过（105 passed in 78.90s）；全程 0 真实模型调用、0 GPU 占有、0 写入生产数据库 `runs.db`。

---

## 二、r2 代码修改与精确引用（Verbatim Citations）

### 1. `src/ainerzero/v9/teachers/da3_calibration_runner.py`
- **动态按路径加载登记模块**（行 51-70）：
  ```python
  def _load_registration():
      """按文件路径加载登记模块：worker 以脚本方式、不带 PYTHONPATH 启动本文件，且避开包 __init__ 的副作用。"""
      pkg_name = "ainerzero.v9.teachers.t28_registration"
      if pkg_name in sys.modules:
          return sys.modules[pkg_name]
      name = "t28_registration"
      if name in sys.modules:
          return sys.modules[name]
      reg_path = Path(__file__).with_name("t28_registration.py")
      spec = importlib.util.spec_from_file_location(pkg_name, reg_path)
      if spec is None or spec.loader is None:
          spec = importlib.util.spec_from_file_location(name, reg_path)
      if spec is None or spec.loader is None:
          raise ImportError(f"Cannot find t28_registration.py relative to {__file__}")
      mod = importlib.util.module_from_spec(spec)
      sys.modules[pkg_name] = mod
      sys.modules[name] = mod
      spec.loader.exec_module(mod)
      return mod
  ```
- **默认 proposal 路径选择（大声失败，不吞异常）**（行 79-97）：
  ```python
  def get_default_proposal_path() -> Path:
      if os.environ.get("T6_PROPOSAL_PATH"):
          return Path(os.environ["T6_PROPOSAL_PATH"]).resolve()
      reg = _load_registration()
      repo = getattr(reg, "REPO_ROOT", None) or REPO_ROOT
      reg_file = repo / "reports/V9-T28/REGISTERED.json"
      if reg_file.is_file():
          try:
              reg_info = reg.load_t28_registration(repo_root=repo)
          except Exception as exc:
              raise PreflightError(f"Failed to read T28 registration: {exc}") from exc
          if reg_info.is_registered and reg_info.proposal_path:
              candidate = Path(reg_info.proposal_path)
              if not candidate.is_file():
                  raise PreflightError(f"Registered proposal path not found: {candidate}")
              return candidate.resolve()
          raise PreflightError(f"REGISTERED.json exists at {reg_file} but has no valid registered proposal_path")
      return (REPO_ROOT / "reports/V9-T28/proposal.json").resolve()
  ```
- **`load_plan` 中的哈希核验**（行 168-185）：
  ```python
  if verify_hashes:
      reg = _load_registration()
      repo = getattr(reg, "REPO_ROOT", None) or REPO_ROOT
      try:
          reg_info = reg.load_t28_registration(repo_root=repo)
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
- **`main()` 中捕获 preflight 异常**（行 528-545）：
  ```python
  try:
      target_proposal = a.proposal if a.proposal is not None else get_default_proposal_path()
      if a.preflight_only:
          plan = load_plan(target_proposal)
          ...
          return EXIT_OK
      ...
  except PreflightError as e:
      print(f"PREFLIGHT FAILED (no model work done): {e}", file=sys.stderr)
      return EXIT_PREFLIGHT
  ```

---

## 三、真实环境集成测试与单元测试覆盖

### 1. 真实运行环境集成测试（`envs/teachers/.venv-t6/bin/python` 无 PYTHONPATH）
测试用例：`tests/test_da3_t56_features.py::test_real_venv_t6_runner_script_execution_without_pythonpath`
- **默认执行（读取真实的 `REGISTERED.json` 指向 r2）**：
  - 命令：`envs/teachers/.venv-t6/bin/python src/ainerzero/v9/teachers/da3_calibration_runner.py --preflight-only ...`
  - 返回码：`0`（`{"preflight": "ok", "checks": ["t28_hashes_bound", ...]}`）。
- **`T6_PROPOSAL_PATH` 环境变量指定 r1 提案**：
  - 返回码：`2`（`PREFLIGHT FAILED (no model work done): T28 proposal SHA256 mismatch with registration...`）。
- **`--proposal` 参数指定 pre-E18 提案**：
  - 返回码：`2`（`PREFLIGHT FAILED (no model work done): T28 proposal SHA256 mismatch with registration...`）。

### 2. 全量测试结果（105/105 全部通过）
运行命令：
```bash
.venv/bin/pytest tests/test_da3_*.py tests/test_t28_*.py tests/test_teacher_da3_controlled.py
```
测试统计与耗时：
```text
tests/test_da3_calibration_runner.py ................................... [ 33%]
..                                                                       [ 35%]
tests/test_da3_linewide_quota.py ......                                  [ 40%]
tests/test_da3_supervision.py ..........                                 [ 50%]
tests/test_da3_t56_features.py .........                                 [ 59%]
tests/test_da3_views_82.py ..                                            [ 60%]
tests/test_t28_bad_controls_r2.py ....                                   [ 64%]
tests/test_t28_registration_and_quota.py ................                [ 80%]
tests/test_teacher_da3_controlled.py .....................               [100%]

======================== 105 passed in 78.90s (0:01:18) ========================
```

---

## 四、r2 坏对照（Adverse Controls）验证

执行验证脚本：`python3 reports/V9-T56/gemini-r4x9/r2/run_r2_adversarial_mutants.py`
针对真实环境集成测试 `test_real_venv_t6_runner_script_execution_without_pythonpath`：
- **Mutant 1（恢复成 `from ainerzero...` 包导入）**：
  - 变异副本：`reports/V9-T56/gemini-r4x9/r2/mutants/mutant_1_from_ainerzero_import/src/ainerzero/v9/teachers/da3_calibration_runner.py`
  - 结果：**RED（Returncode 1，`ModuleNotFoundError: No module named 'ainerzero'`）**
  - 详细日志：`reports/V9-T56/gemini-r4x9/r2/logs/mutant_1_import_failure.log`
- **Mutant 2（移除 proposal SHA 对比 REGISTERED.json）**：
  - 变异副本：`reports/V9-T56/gemini-r4x9/r2/mutants/mutant_2_no_sha_check/src/ainerzero/v9/teachers/da3_calibration_runner.py`
  - 结果：**RED（Returncode 1，`assert res2.returncode == 2` 失败，得到 6，未被预检拦截直接退回不可满足）**
  - 详细日志：`reports/V9-T56/gemini-r4x9/r2/logs/mutant_2_sha_failure.log`

---

## 五、零模型与零账本守则核验

1. **真实模型调用**：0。
2. **生产 central `runs.db`**：无写入，修改前后校验与测试全部在临时隔离的 `tmp_path` 库中进行。
3. **互斥锁 `m0-worker.lock`**：未触碰、未抢占。
4. **代码备份**：原始未修改文件与 r1 阶段备份完整归档于 `reports/V9-T56/gemini-r4x9/r2/before/`。
