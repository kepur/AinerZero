# ainerzero.V9.T41 执行报告

角色：executor；负责人：composer-vyz0；时间：2026-10-28
任务状态：reported；实验状态：未执行（零模型复核）
任务依据：V9.T41 非作者复核 V9.T40；参数 v0；前置 T37 accepted
输入身份：见下方命令原始 SHA；被复核任务作者 claude-az（本人非排除名单）
修改文件：仅 `reports/V9-T41/`（本报告、metrics、evidence）
实际执行：只读核对 + 仓外/临时探针 + 自有变异注入（还原）+ AC 前台 pytest；未跑 `teacher-da3 --mode run`；未碰锁与 `runs.db`
验证结果：60 passed（74.82s，接 AC）；自有变异 3/3 被抓 + 1 盲区确认；runs.db SHA 前缀不变
产物：`reports/V9-T41/REPORT.md`、`metrics.json`、`evidence/`
失败与限制：未真跑模型；未验证 half_parity 在 MPS 上的实际 SIGABRT（只读代码与 T40 陈述）
交回统筹：recommendation=`accept_with_changes`；见两问与 required_changes

## 摘要

独立复核 T40：磁盘 SHA 与作者表完全一致；`test_substitute` 在所有经 `execute_guarded` 的路径到不了 `real_pipeline`（CLI 在 substitute+release 时仍会**选出** real_pipeline，但守卫在进 worker 前拒绝）；`views==18` 魔数仍是标定启动与「碰巧挡住旧测试」的双重门；证据原子落盘对抗探针通过，但「放行覆盖 in_progress」现有测试抓不到；自有 3 变异被抓。下一次真跑在 half_parity 上仍会按已知原因崩；T40 落盘能保住崩前阶段证据，但不能阻止崩。配额批准前还需协议/账本口径决定与 CLI 预检。

## 1. SHA 对账（命令原始输出，非手填）

```text
$ shasum -a 256 <七源文件 + runs.db>
9a80aa736a5de2e6116b6f0f92bedc200fd57b1bec35b33ab3036d1df3e1ec2b  src/ainerzero/v9/teachers/da3_calibration_math.py
d6d2416eb15d75e30542f174698da823cb7f5f74f130f6b33c7f3a6bec67410d  src/ainerzero/v9/teachers/da3_calibration_runner.py
0062a707164a0facb42c9f2a3a21b9dd1cf485c3b6f82c953d123690a4fde6ce  src/ainerzero/v9/teachers/da3_worker.py
006d9005b15f9b4bf25859ef99f6b617394075df88d1ebb9639ffc1667ded5bc  src/ainerzero/v9/teachers/da3_controlled.py
6a82fc17af3278428b7ca24edd9d50ed245d26958693ad152acd914a4384827b  tests/test_da3_calibration_runner.py
a62ab2d819a1acda0ef549880fcb83436c1de9ffa7a2ba8323ae159bf6909043  tests/test_teacher_da3_controlled.py
fb9ac1bbe763403c2b5ceb1c33febcc14d97e6950886604444631d91e13f4c49  tests/test_da3_supervision.py
64b668050dfbab7ae1e5b9fe5280f44cecb12643fb820b6a752a6a693723107f  artifacts/v9/teachers/benchmark/runs.db
```

与 `reports/V9-T40/evidence/SHA.txt` / `metrics.json` 七文件逐字节一致；`runs.db` 前缀 `64b668050dfbab7a` 复核前后不变。锁 mtime `1790110663` 不变。完整落盘：`evidence/sha_and_paths.txt`。

### 重建基线可信度

`evidence/t37-accepted/da3_controlled.py` 与 `test_teacher_da3_controlled.py` 为事后重建：与当前文件的唯一差即 T40 声称的守卫与新测试（diff 仅该块）。其余五个基线文件为真实拷贝且 SHA 可对。判断：**重建可信**，可用于 diff 审阅。`diff_reviewed_lines`（unified `+/-` 合计）= **271**。

## 2. 第 5 项：test_substitute → real_pipeline

### 可达路径追踪

| 路径 | 在 test_substitute 下能否进 real_pipeline |
|---|---|
| `execute_guarded(..., test_substitute=True, worker_action=None)` | 否 → `mock_run` |
| `execute_guarded(..., test_substitute=True, worker_action="real_pipeline")` | 否 → `BenchmarkRefusalError`（进 worker 前） |
| CLI `teacher-da3`/`teacher-benchmark --test-substitute`（无 release） | 否 → CLI 选 `mock_run` |
| CLI `--test-substitute --coordinator-release` | **CLI 仍选 `real_pipeline`**，但 `execute_guarded` 拒绝；到不了 `run_supervised` |
| 正式 CLI/API（无 substitute + 已放行） | 是（预期） |
| 直接 `run_supervised_da3_worker()` 默认参数 | 默认即 `real_pipeline`；**无 test_substitute 参数**（绕过中央入口） |
| `python -m ...da3_worker --action real_pipeline` | worker 内真实路径；靠 `views==18` 等门 |

结论：`real_pipeline_reachable_from_test_substitute` = **false**（经中央 `execute_guarded` / CLI 进 supervised worker 的路径）。探针测试去掉守卫后变红（自有变异 T41-2），确认测试本身走不到探针会失败。

### 魔数守卫

- **`views == 18`**（`da3_worker.py`）：唯一启动标定 runner 的条件；非 18 → `refused_no_calibration` rc=4。旧 `test_coordinator_release_gate_and_cli` 的 views=4 曾「碰巧」挡住真实前向。
- 无第二套与 18 无关的「碰巧」数值门替代 test_substitute 守卫；资源/配额门不区分 substitute。

## 3. 证据落盘对抗

见 `evidence/adversarial-probes.json`（14/14）：

- 证据路径是目录 / 父目录只读 → 抛错（不静默成功）
- 残留 `.tmp` **不**被预检当成「证据已存在」；杀在 `os.replace` 前可重试写成功
- `status=in_progress` 同路径重跑被预检拒绝（永不覆盖）
- 代码中无消费者把 `in_progress` 当成功；worker 每次新 `run_stamp` 目录，崩溃残留不挡新跑
- **风险**：固定名 `ev.json.tmp` 并发写同路径可互踩；未加文件锁

## 4. `--proposal` / `T6_PROPOSAL_PATH`

- 缺失文件 → `EXIT_PREFLIGHT=2`
- sidecar 不符 → `PreflightError`
- 同时给出时：**`--proposal` 优先**（`a.proposal or PROPOSAL_PATH`）；`PROPOSAL_PATH` 在 import 时读环境变量
- 默认仍 r1：`--preflight-only` → **6**；`--proposal` 指向 r2 → **0**

## 5. worker 拒绝（rc 4）

- mock/真路径：`views=4` + allow → rc=4、`refused_no_calibration`（探针实测）
- 上游 `run_supervised`：`returncode != 0` → `BenchmarkRefusalError`，不会当成功；`execute_guarded` 转 `failed`（**不退账**，因 `consume` 在 worker 前）
- **CLI 预检判断**：应在 CLI/`execute_guarded` 于 `store.consume` **之前**拒绝非标定视图（或约定 views 口径后校验），否则每次误配 views 都会不可逆烧配额。仅靠 worker rc=4 不够。`views==18` 真实启动路径代码仍在，未改坏。

## 6. 自有变异（≥3）

`evidence/mutate_t41_own.py` / `own-mutation-results.txt`：

| 变异 | 结果 |
|---|---|
| T41-1 `_write_atomic` 不做 replace | 3 红（hard_abort×2 + atomic） |
| T41-2 去掉 substitute 显式拒绝 | 1 红（never_selects 探针） |
| T41-3 refusal 仍 rc=0 | 1 红（lazy_worker） |
| T41-4 放行覆盖 in_progress | **现有 suite 未抓到**；自定义探针 `GAP_CONFIRMED` |

## 7. 测试

接 AC（`pmset`：Drawing from AC Power）；`relay exec` 前台：

`60 passed in 74.82s` — `evidence/pytest-da3-suite.txt`

## 两问

### 下一次真跑还会死在已知同类问题上吗？

**是（`next_run_would_die_on_known_issue=yes`）**，若协议仍含 `half_parity` 且管线仍为 ExplicitPrecisionDA3 关 autocast + `model.to(float16)`，而 `CameraDec`/`DualDPT` 写死 fp32：CPU `RuntimeError` dtype；MPS Metal 断言 **SIGABRT 134**。T40 不修管线/不删阶段。

**half_parity 单列 — 证据完整性：** 逐阶段 `checkpoint` + 开始即 `in_progress` 能在崩前已完成阶段留下完整 JSON；崩在阶段中途则该阶段可能未写入，但更早阶段仍在。SIGABRT 无 Python 收尾，最终 status 多半停在 `in_progress`（不是假 completed）。**不能**保证捕获 Metal 断言细节，也不能保证半写 `.tmp` 被提升为正式证据。相对「旧实现最后才写、崩了什么都不留」已够用。

### T40 还欠什么才能放心批配额？

1. 用户决定：删 `half_parity` 或改管线 autocast-fp16（且不动被缓存键绑定的 `pipeline.py` 身份策略要先定）
2. 登记 r2 SHA；默认 proposal 切 r2 的时机
3. 账本口径：views 18 vs 前向 56；CLI 在 `consume` 前预检
4. 补测：in_progress 覆盖拒绝；CLI substitute+release 应直接选 mock 而非先选再拒
5. 配额数字本身的用户批准

## recommendation

**accept_with_changes** — T40 声称项属实、测试与 SHA 站得住；放配额前需上列 changes（尤其 half_parity 协议决定与 CLI 预扣前预检）。
