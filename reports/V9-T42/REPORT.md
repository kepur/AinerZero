# ainerzero.V9.T42 执行报告

角色：executor；负责人：gemini-f8a2；时间：2026-10-28
任务状态：reported；实验状态：未执行（零模型运行，纯 CPU 收口）
任务依据：ainerzero.V9.T42（依据 V9.T41 非作者复核意见与 T40 accepted 结论；参数 v0）
输入身份：开工前 7 文件及 runs.db SHA 与 T41 §1 基线 100% 逐字节一致
修改文件：
  - `src/ainerzero/v9/teachers/da3_worker.py`
  - `src/ainerzero/v9/teachers/da3_controlled.py`
  - `src/ainerzero/v9/teachers/da3_calibration_runner.py`
  - `src/ainerzero/v9/teachers/benchmark_commands.py`（Item 3 CLI 选 mock 逻辑所在处）
  - `tests/test_teacher_da3_controlled.py`
  - `tests/test_da3_calibration_runner.py`
  - `reports/V9-T42/`（本报告、metrics.json、evidence/）
实际执行：零模型加载；未触碰 `m0-worker.lock`（mtime 1790110663 不变）；未触碰 `runs.db`（SHA 64b668050dfbab7a... 前后不变）；AC 供电下通过 `relay exec` 前台运行全套 DA3 测试；4 项反向变异自证 4/4 变红落盘。
验证结果：62 passed（77.02s，接 AC，pytest-da3-suite.txt）；变异自证 4/4 全部变红。
产物：`reports/V9-T42/REPORT.md`、`metrics.json`、`evidence/`

## 摘要（30 行内）
本卡完成 T40/T41 后续 4 项 CPU 收口：
1. **consume 前预检**：在 `da3_worker.py` 定义具名常量 `REGISTERED_CALIBRATION_VIEWS = 18`，两处引用（worker 与 `da3_controlled.py`）；在 `execute_guarded_da3_benchmark` 进入 `worker_lock` 与 `store.consume` 之前，对 `action == "real_pipeline"` 请求校验 `views == REGISTERED_CALIBRATION_VIEWS`，不符抛 `BenchmarkRefusalError`，实现零扣账、零锁竞争、零 worker 启动。
2. **补测 in_progress 覆盖拒绝**：在 `test_da3_calibration_runner.py` 补充用例，断言已存在 `status="in_progress"` 证据时 `preflight` 必拒绝；同时验证残留 `.tmp` 不被误判为证据已存在。成功抓出 T41-4 变异盲区。
3. **substitute+release 直接选 mock**：在 `benchmark_commands.py` 修复 CLI 动作选择：`test_substitute` 下恒选 `mock_run`（即使带有 `coordinator_release`）；`execute_guarded` 保留纵深防御守卫；补充两层测试（CLI 成功完成且 `model_runs=0`；直接传 `real_pipeline` 仍被守卫拒）。
4. **临时文件名唯一**：`_write_atomic` 改为同目录 `.tmp.<pid>.<uuid>` 唯一临时文件，防止并发写者互踩，并确保异常时清理；补充并发双写者互不踩踏与残留 `.tmp` 忽略用例。

## 1. SHA 与基线对账

开工前与结束后的关键文件 SHA：
```text
$ shasum -a 256 <files>
9a80aa736a5de2e6116b6f0f92bedc200fd57b1bec35b33ab3036d1df3e1ec2b  src/ainerzero/v9/teachers/da3_calibration_math.py
5c12b934789dae36f5f98f0342a2897cfc0d935a1297d4cce56eb48d64bee85c  src/ainerzero/v9/teachers/da3_calibration_runner.py
307a32fcf2531126750496e0423ca1c5f36a2e164229a332f4cdc8197b8f5c7f  src/ainerzero/v9/teachers/da3_worker.py
d5d776672ea898a2c177346e75313023613eb128ee5d189a579459adc2369ba4  src/ainerzero/v9/teachers/da3_controlled.py
1a43c4c2b0f5d3ead7ed2e52b8b51b04b90b533fbcaad6d093816292671b6c9d  src/ainerzero/v9/teachers/benchmark_commands.py
70ef1d95567b2c6bf82b76599f44f62b839cb9d84a8aa76a1c32bfdcc1a0097c  tests/test_da3_calibration_runner.py
7b99b83c4d17d4780eee3ba616d52b75f43f1fa8066741ccb4d46dd3c69181a9  tests/test_teacher_da3_controlled.py
fb9ac1bbe763403c2b5ceb1c33febcc14d97e6950886604444631d91e13f4c49  tests/test_da3_supervision.py
64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f  artifacts/v9/teachers/benchmark/runs.db
```

- `artifacts/locks/m0-worker.lock` mtime：执行前 `1790110663`，执行后 `1790110663`（完全不变）。
- `runs.db` SHA：执行前 `64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f`，执行后完全一致。
- 完整 SHA 对账见 `evidence/sha_and_paths.txt`、`runs_db_before.txt` 与 `runs_db_after.txt`。

## 2. 四项改动实现说明

### 2.1 consume 前预检与具名常量
- 在 `da3_worker.py` 中定义 `REGISTERED_CALIBRATION_VIEWS = 18`（并别名 `CALIBRATION_VIEWS_REQUIRED`），消除原本分散在 `views == 18`、错误消息、注释中的魔数。
- 在 `da3_controlled.py` 中引入该常量。在 `execute_guarded_da3_benchmark` 解析得到 `action == "real_pipeline"` 时，立即校验 `spec.views == REGISTERED_CALIBRATION_VIEWS`。
- 若不相等，直接抛出 `BenchmarkRefusalError`。该异常发生在获取 `worker_lock` 与调用 `store.create_run`/`store.consume` 之前，保证了零扣账、零锁等待、零 worker 进程启动，并在 CLI 下统一映射为退出码 1（refused）。
- worker 内部原有的 `views == REGISTERED_CALIBRATION_VIEWS` 门完全保留不动。

### 2.2 补测 in_progress 覆盖拒绝
- 在 `tests/test_da3_calibration_runner.py` 新增 `test_preflight_rejects_existing_in_progress_evidence_and_ignores_tmp_residue`。
- 验证当证据文件内容为 `{"status": "in_progress"}` 时，`preflight` 依然坚决抛出 `PreflightError`，防止未完成的崩溃残留被静默放行或覆盖。
- 同时验证当目录下存在遗留的 `.tmp` 文件但正式证据文件不存在时，预检放行（不会将 `.tmp` 错误识别为已存在的证据）。

### 2.3 substitute+release 直接选 mock
- 修改 `src/ainerzero/v9/teachers/benchmark_commands.py:109`：
  ```python
  worker_action = "mock_run" if test_substitute else ("real_pipeline" if coordinator_release else "mock_run")
  ```
  在 `test_substitute` 为 True 时直接选 `mock_run`，解决了此前即使带 `test_substitute`，只要给了 `coordinator_release` 就会先选 `real_pipeline` 再被守卫抛错拒绝的逻辑矛盾。
- `execute_guarded_da3_benchmark` 中 `if test_substitute and worker_action == "real_pipeline": raise BenchmarkRefusalError` 作为第二层纵深防御完全保留。
- 在 `tests/test_teacher_da3_controlled.py` 新增 `test_cli_substitute_with_release_selects_mock_run_and_defense_in_depth`，分别覆盖 CLI 成功完成 mock_run 与底层守卫拦截显式 `real_pipeline` 的两层逻辑。

### 2.4 临时文件名唯一
- `src/ainerzero/v9/teachers/da3_calibration_runner.py` 中的 `_write_atomic` 改用：
  `unique_suffix = f".tmp.{os.getpid()}.{uuid.uuid4().hex}"`
  与目标文件同目录原子写 + `os.replace`。
- 在 `tests/test_da3_calibration_runner.py` 新增 `test_write_atomic_uses_unique_tmp_and_concurrent_writers_do_not_clobber`，验证临时文件名正则符合预期，且双线程高频并发写入同一目标文件时不互踩、文件可被完整反序列化且零 `.tmp` 遗留。

## 3. 反向变异自证结果

运行 `reports/V9-T42/evidence/mutate_t42.py`，对 4 项改动分别注入反向变异（还原），确认对应测试变红：
```text
=== T42 反向变异自证开始 ===
T42-1 consume 前预检：移除 execute_guarded 中对 views 的预检拦截
    -> 成功抓出变异 (1 条变红): test_pre_consume_calibration_views_check_rejects_n
T42-2 补测 in_progress 覆盖拒绝：注入 T41-4 放行 status=in_progress 证据文件
    -> 成功抓出变异 (1 条变红): test_preflight_rejects_existing_in_progress_eviden
T42-3 substitute+release 直接选 mock：还原 CLI 在 test_substitute+coordinator_release 下选 real_pipeline
    -> 成功抓出变异 (1 条变红): test_cli_substitute_with_release_selects_mock_run_
T42-4 临时文件名唯一：还原 _write_atomic 为固定 .tmp 文件名
    -> 成功抓出变异 (1 条变红): test_write_atomic_uses_unique_tmp_and_concurrent_w
=== 自证完成，结果已写入 reports/V9-T42/evidence/mutation-results.txt (全部捕获: True) ===
```
自证结果 4/4 全部变红，变异捕获率 100%。

## 4. 全套测试执行

接 AC 电源（Drawing from 'AC Power'），使用 `relay exec` 前台执行全套 DA3 测试：
```text
$ relay exec ainerzero.V9.T42 --agent gemini-f8a2 -- .venv/bin/pytest tests/test_da3_calibration_runner.py tests/test_teacher_da3_controlled.py tests/test_da3_supervision.py -q
..............................................................           [100%]
62 passed in 77.02s (0:01:17)
[relay exec] 墙钟监督证据：{"elapsed_s": 77.244, "kind": "exited", "confirmed_empty": true, "leader_returncode": 0}
```
完整输出落盘在 `reports/V9-T42/evidence/pytest-da3-suite.txt`。

## 5. 未做与如实交代
1. **真实模型运行与 GPU**：本卡限 CPU 工程收口，未加载任何真实权重，未进行前向计算，未动用 MPS/GPU。
2. **half_parity 决定**：仍保持原样，等待用户或统筹做出最终协议决定。
3. **文件范围说明**：第 3 项 CLI 选择 mock_run 位于 `src/ainerzero/v9/teachers/benchmark_commands.py:109`（此前 T40 未改该文件导致 CLI 与守卫行为冲突）。已通过接力台向统筹提出 question #696 登记说明。
