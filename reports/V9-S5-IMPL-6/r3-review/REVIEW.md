# ainerzero.V9.P238 复核报告：一级给 P236 运行器改的测试非作者复核

- **任务**：`ainerzero.V9.P238`
- **复核者**：`gemini-h8q4`（二级执行 agent，非作者）
- **复核对象**：`ainerzero.V9.P236`（一级 claude 改动的测试路径、拒绝 final、输出 SHA 测试）及一级 11-12 对运行器的修正（教师特征按分区存放、真实阶段预检）
- **日期**：2026-11-12
- **复核结论**：**需补**（发现 5 处有效源码坏对照漏网；且发现 `test_final_partition_cell_is_refused_before_any_cell` 因引入预检而处于报错中断状态）

---

## 1. 逐条判断（声明核验与行号引用）

### 1.1 仓库路径改法
- **涉及文件**：
  - `tests/v9/experiments/test_s5_runner_native.py`（第 24、26、39、51、56、67、270 行）
  - `tests/v9/experiments/test_s5_runner_plan.py`（第 17、19、104 行）
  - `tests/v9/experiments/test_s5_evaluate.py`（第 23、25、144 行）
- **核心代码引用**：
  - `test_s5_runner_native.py` 第 24 行：
    ```python
    LIVE = Path(__file__).resolve().parents[3]
    ```
  - `test_s5_runner_native.py` 第 26 行：
    ```python
    REAL_REPO = Path("/Users/mac/AinerWorkFlow/AinerZero").resolve()
    ```
  - `test_s5_runner_native.py` 第 39 行：
    ```python
    assert tmp_path.resolve() not in (LIVE, REAL_REPO)
    ```
- **逐条判断结果**：
  1. **从副本里跑，是不是只测副本**：**是**。`LIVE` 由 `__file__` 向上推导 4 层目录。在隔离副本中运行 pytest 时，`LIVE` 解析为副本根目录；`_make_root` 从 `LIVE / "src/ainerzero"` 和 `LIVE / HERE` 复制源码至一次性运行目录 `root`，`run_s5p1.py` 内部的 `REPO` 亦推导为 `root`。因此副本中测试完全作用于副本自身。
  2. **从实盘跑，是不是测实盘**：**是**。在实盘执行 pytest 时，`LIVE` 解析为 `/Users/mac/AinerWorkFlow/AinerZero`，与实盘严格一致。
  3. **「不是一次性目录」的断言会不会被绕过**：**存在绕过盲区**。
     - 各测试文件中的断言均为 `assert path.resolve() not in (LIVE, REAL_REPO)`。
     - 该断言仅做**精确路径相等比较**，未做子目录判断。
     - 若 pytest 运行时指定 `--basetemp=./tmp`（在实盘仓库内部建立子目录），此时 `(REAL_REPO / "tmp").resolve() in (LIVE, REAL_REPO)` 为 `False`，断言被成功绕过，会在实盘仓库内改动和创建文件。
     - **修复建议**：应增强为 `not path.resolve().is_relative_to(REAL_REPO) and not path.resolve().is_relative_to(LIVE)`。

---

### 1.2 拒绝 final 测试 (`test_final_partition_cell_is_refused_before_any_cell`)
- **涉及文件**：`tests/v9/experiments/test_s5_runner_native.py`（第 284–297 行）
- **核心代码引用**：
  - 第 287–290 行：
    ```python
    _mutate_file(root, f"{HERE}/plan_s5p1.py",
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-pool",',
                 'n_clips=pool_clips, epochs=distill_epochs, partition="s5p1-final",')
    ran = _run(root, "--stage", "probe", "--use-id", "p-final", "--report", "reports/out.json")
    ```
  - 第 292–295 行：
    ```python
    events = _events(root)
    assert not [e for e in events if e["event"] == "cell_start"], events
    errors = " ".join(str(e.get("error", "")) for e in events)
    assert "final partition" in errors, events
    ```
- **逐条判断结果**：
  1. **测试是否真的检查了它声称检查的东西**：**否（当前处于崩溃状态）**。
     - 事实证据：在 `e83cfd5` 引入输入预检 `_preflight_real_inputs()` 后，直接运行该测试会失败：
       `FileNotFoundError: [Errno 2] No such file or directory: '.../artifacts/v9/s5/runs'`。
     - 根因：`_make_root(tmp_path)` 未生成真实数据与教师特征；`run_s5p1.py` 在第 504 行（创建 `RUNS` 目录和 `events.jsonl` 之前）调用 `_preflight_real_inputs()` 直接抛出 `GuardError: preflight: missing real inputs...` 并异常退出。因此 `root / RUNS` 根本不存在，第 292 行 `_events(root)` 抛出 `FileNotFoundError`。该测试并未执行到“拒绝 final”，声明失效。
  2. **除 probe 蒸馏格外的缺口**：
     - **缺口 A（变体漏网）**：只断言了 `s5p1-final`，未断言 `s5p1-final-shift`。若生产代码改为 `if str(name) == "s5p1-final":`，该测试无法拦截。
     - **缺口 B（`cells_override` 绕过生产代码守卫）**：
       看 `run_s5p1.py` 第 542–572 行：
       ```python
       if cells_override is not None:
           cells = cells_override
           ... # 没有任何 _refuse_final 检查！
       else:
           cells = plan.stage_cells(...)
           for cell in cells:
               _refuse_final(cell["partition"])
       ```
       当调用方通过 `cells_override` 注入自定义格子时，运行器完全漏掉了 `_refuse_final` 检查！
     - **缺口 C（预算消耗时序隐患）**：
       在 `run_s5p1.py` 中，第 505 行 `GD.consume_dev_use(...)` 在第 571 行 `_refuse_final(cell["partition"])` 之前执行。若格子配置了非法的 final 分区，系统会**先消耗 1 次 dev 使用预算**，然后才报错崩溃，违背零代价防御原则。

---

### 1.3 输出 SHA 测试 (`test_cell_output_sha_mismatch_fails_the_cell`)
- **涉及文件**：`tests/v9/experiments/test_s5_runner_native.py`（第 299–314 行）
- **核心代码引用**：
  - 第 304–305 行：
    ```python
    result = json.loads(result_path.read_text(encoding="utf-8"))\n
    result["files"] = {k: "0" * 64 for k in result.get("files", {})}\n
    ```
- **逐条判断结果**：
  1. **测试是否真的检查了它声称检查的东西**：**是**，检查了结果字典中所有文件 SHA 被篡改时的拦截。
  2. **盘上文件被改或被删的覆盖情况**：
     - **盘上文件被改**：与篡改结果字典在 SHA 核对逻辑上等价。
     - **盘上文件被删（漏网）**：生产代码第 659–660 行 `if not fpath.is_file(): raise GD.GuardError(f"cell output file missing: {fname}")` 没有任何测试覆盖。若文件未落盘且缺少该守卫，第 661 行 `sha256_file(fpath)` 会抛出未经处理的原生 `FileNotFoundError`，使进程异常崩溃而无法记录结构化事件。
     - **多文件遍历漏检（重大漏网）**：现有测试将 `result["files"]` 中所有文件统一改写为 `"0" * 64`。若生产代码核对循环被篡改为只核对第一个文件（`[:1]`），首个文件依然匹配错误，测试依然通过。现有测试无法证明第二个及后续文件的 SHA 被核验！

---

### 1.4 一级 11-12 修正（教师按分区读取与预检）
- **涉及文件**：
  - `reports/V9-S5-PHASE1/run_s5p1.py`（第 63–66、69–82、504 行）
  - `tests/v9/experiments/test_s5_runner_native.py`（第 319–364 行）
- **逐条判断结果**：
  - `test_probe_without_real_inputs_fails_before_spending_a_dev_use` 验证了预检在 `consume_dev_use` 之前阻止了无输入运行，不消耗 dev 次数。
  - **漏网缺口 1**：`test_preflight_requires_teacher_features_stored_per_partition` 仅能发现 pool 教师未分区。若 `_preflight_real_inputs()` 完全漏掉 `REAL_TEACHERS["lab"]`，现有单测依然通过。
  - **漏网缺口 2**：若预检只检查 `manifest.json` 存在性而不检查是否有实际 `clip_*.npy` 样本文件，现有测试均无法拦截。

---

## 2. 自做源码坏对照（5 个新坏对照）

在隔离副本（`/tmp/s5_p238_copy`）中进行对抗变异测试。所有坏对照脚本均断言目标非实盘路径。原始执行日志见 `evidence/mutations_r3_output.txt`。

| 坏对照 ID | 源码改动描述 | 针对组件 | 现有测试集表现 | 结论 |
|---|---|---|---|---|
| **M1_refuse_final_exact_only** | 将 `if str(name).startswith("s5p1-final"):` 改为 `if str(name) == "s5p1-final":` | 拒绝 final 变体（如 `s5p1-final-shift`） | `test_final_partition_cell_is_refused_before_any_cell` 仅测 `s5p1-final`，无法拦截（且现有测试因预检直接崩溃） | **SURVIVED (漏网)** |
| **M2_sha_only_checks_first_file** | 将 `for fname, expected_sha in result.get("files", {}).items():` 改为 `...items())[:1]:` | 多输出文件 SHA 核对完整性 | `test_cell_output_sha_mismatch_fails_the_cell` 保持通过（`base_rc=0, mut_rc=0`） | **SURVIVED (漏网)** |
| **M3_ignore_child_exit_code** | 将 `if p.exitcode != 0:` 改为 `if False and p.exitcode != 0:` | 子进程异常退出（非超时退出）守卫 | `timeout_exit_mutation` 与 `output_sha_mismatch` 均保持通过（`base_rc=0, mut_rc=0`） | **SURVIVED (漏网)** |
| **M4_preflight_skips_lab_teacher** | 将 `for group in REAL_TEACHERS.values():` 改为 `for group in [REAL_TEACHERS["pool"]]:` | 预检教师特征按分区读取完整性 | `without_real_inputs` 与 `teacher_features_stored_per_partition` 均保持通过（`base_rc=0, mut_rc=0`） | **SURVIVED (漏网)** |
| **M5_preflight_skips_data_clip_check** | 预检去掉 `or not any(d.glob("world_*/clip_*.npy"))`，只检查 `manifest.json` | 预检空数据分区拦截能力 | 现有预检测试均保持通过（`base_rc=0, mut_rc=0`） | **SURVIVED (漏网)** |

---

## 3. 需补测试与生产代码修复建议

在 `evidence/verify_proposed_tests.py` 中已实现并验证了针对上述漏网的修复方案，验证日志见 `evidence/verify_proposed_tests_output.txt`。

### 3.1 修复 `test_final_partition_cell_is_refused_before_any_cell`
在调用 `_run(root, "--stage", "probe", ...)` 前，必须先调用 `_write_inputs(root, partitioned_teachers=True)`，使输入预检通过，才能真正测试到运行器对 `s5p1-final` 的拒绝。

### 3.2 补测拒绝 final 所有命名变体
在测试中增加对 `_refuse_final` 的直接契约测试：
```python
def test_refuse_final_rejects_all_final_variants():
    from ainerzero.v9.experiments.s3 import run_guard as GD
    for part in ("s5p1-final", "s5p1-final-shift", "s5p1-final-eval"):
        with pytest.raises(GD.GuardError, match="must not touch a final partition"):
            _refuse_final(part)
```
*验证结果*：M1 变异在此测试下立即报错退出（`rc=1`，**KILLED**，用时 0.33s）。

### 3.3 补测多文件 SHA 篡改与文件缺失
在 `test_s5_runner_native.py` 中增加：
1. 保持首个文件 SHA 正确，仅篡改第二个文件（如 `heads.npz`）SHA，断言阶段失败且记录 `cell_fail`。
2. 删除盘上生成的第二个权重文件，断言抛出 `cell output file missing` 且记录 `cell_fail`。
*验证结果*：M2 变异在此测试下立即报错退出（**KILLED**）。

### 3.4 补测预检漏项（Lab 教师与空数据分区）
在 `test_s5_runner_native.py` 中增加：
```python
def test_preflight_fails_when_lab_teacher_unpartitioned(tmp_path: Path):
    wrong_lab = _make_root(tmp_path / "wrong_lab")
    _write_inputs(wrong_lab, partitioned_teachers=True)
    shutil.rmtree(wrong_lab / "artifacts/v9/s5/teachers/vjepa/s5p1-lab")
    r = _preflight(wrong_lab)
    assert r.returncode != 0 and "missing real inputs" in r.stderr and "s5p1-lab" in r.stderr

def test_preflight_fails_when_data_partition_has_manifest_but_no_clips(tmp_path: Path):
    empty_data = _make_root(tmp_path / "empty_data")
    _write_inputs(empty_data, partitioned_teachers=True)
    for p in (empty_data / "artifacts/v9/s5/data/s5p1-pool").glob("world_*"):
        shutil.rmtree(p)
    r = _preflight(empty_data)
    assert r.returncode != 0 and "missing real inputs" in r.stderr and "s5p1-pool" in r.stderr
```
*验证结果*：M4 与 M5 变异在此两项测试下立即报错退出（`rc=1`，**KILLED**，分别用时 1.24s、1.41s）。

### 3.5 生产代码安全加固建议
1. **`cells_override` 守卫**：在 `run_s5p1.py` 第 542 行的 `if cells_override is not None:` 分支中，补上 `for cell in cells: _refuse_final(cell["partition"])`。
2. **预算消耗顺序调整**：在 `run_s5p1.py` 中，将计划格子的生成与 `_refuse_final(cell["partition"])` 检查移至 `GD.consume_dev_use(...)` 之前，确保非法配置不会白白烧掉有限的 dev 次数。
