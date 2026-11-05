# ainerzero.V9.T44 r2 报告：打回后的修复（作者 claude-az；复核必须由他人，见 T45）

零模型、零真实运行；`runs.db` SHA 前缀 `64b668050dfbab7a`、`m0-worker.lock` mtime `1790110663` 前后不变。`da3_worker.py`、`da3_calibration_runner.py`、`pipeline.py`、T28 全部文件未动。

## 1. 为什么打回（我自己复现的）
T44 初版（deepseek-q7m2）把 CLI 的 real 分支收紧为「只认显式 `--coordinator-release`」。但 `coordinator_release` 仍把 `--allow-model-execution` 折算进去，所以「只给 allow」时 CLI 传给 `execute_guarded` 的是
`test_substitute=False, coordinator_release=True, allow_model_execution=True, worker_action="mock_run"`（用 spy 截获，替掉 `execute_guarded`，零账本；见 `evidence/` 里的描述，脚本在本卡会话草稿目录）。
`execute_guarded` 里 `is_released=True`、非替身，Step 7 放行 → 预扣视图/墙钟 → 启动 mock worker → 记 completed、`model_runs=0`。即「授权被消耗、跑的是 mock」，正是 T37/T40 关掉的那个陷阱，被 CLI 选路这一层重新打开。
初版报告把它称作「收紧」，方向是反的；它的测试 `test_cli_real_branch_honours_only_the_explicit_coordinator_release` 把这个行为写成了正确断言。

## 2. 改了什么（`evidence/t44-to-r2.diff`，144 行）
1. `benchmark_commands.py`：run 分支里，`not test_substitute and allow_model_execution and not explicit_coordinator_release` → `BenchmarkRefusalError`（在调用 `execute_guarded` 之前，零预扣）。
2. `da3_controlled.py` Step 6a 之后：`not test_substitute and is_released and action != "real_pipeline"` → `BenchmarkRefusalError`（纵深防御；在视图预检与配额检查之前，零台账读写、零锁、零 worker）。
3. `tests/test_teacher_da3_controlled.py`：删掉把缺陷写进断言的那条，换成
   - `test_cli_allow_model_execution_alone_is_refused_before_any_reservation`：allow-only → `status=refused` 且 `execute_guarded` 探针**从未被调用**；allow + `--test-substitute` 仍允许并选 `mock_run`；
   - `test_released_non_substitute_run_must_use_the_real_pipeline_before_any_reservation`：`mock_run` / `simulate_timeout` / `simulate_high_rss` / `simulate_grandchild_leak` 四种动作都被拒，worker 探针未调用，tmp 的 `runs.db` 与锁文件都没有被创建。
   保留 T44 的正对照 `test_cli_real_branch_still_selects_real_pipeline_with_explicit_release`。

## 3. 验证
- 接 AC：`tests/test_teacher_da3_controlled.py tests/test_da3_supervision.py tests/test_da3_calibration_runner.py` **68 passed**（67 − 1 替换 + 2 新增）。`test_da3_supervision.py` 里 `worker_action="mock_run"/"simulate_*"` 的既有调用均未被新守卫误伤（它们走替身路径）。
- 变异自证（`mutations_r2.py`，仓外镜像，不污染工作树；输出 `evidence/03-mutations-r2.txt`）：**4/4 被抓**。
  - M-A（T43 F-1，派生路径不过视图门）RED；M-C（T43 F-2，临时文件写到系统 /tmp）RED；
  - M-D 拆 CLI 守卫 RED；M-E 拆纵深防御 RED。
- **M-B 在修复后仍是等价变异**：守卫在选路之前，「非替身 + 只给 allow」到不了选路表达式，往表达式里加 `or allow_model_execution` 不改变任何可观察行为。T43 §0 当初描述的前提（CLI 忽略 allow）与代码不符，T44 初版 §5 已指出；现在由守卫而非选路表达式承担这条安全属性，真正有鉴别力的变异是 M-D/M-E。验收口径因此应是「M-A/M-C/M-D/M-E 全红 + M-B 记为等价」。

## 4. 没做、需要别人做
- T45（非作者复核）应攻击：守卫放置的先后（6a 在配额检查之前）、`approval` 里的 `coordinator_release` 是否会让 `is_released` 在非预期情况下为真、`test_substitute` 与 `adapter` 的关系、有没有别的入口（Python API 直接调 `execute_guarded` 且 `worker_action=None`）绕过 CLI 守卫。
- `REGISTERED_CALIBRATION_VIEWS=18` 没动：用户 2026-10-28 定配额口径＝前向视图（每次记 50），这个常量要随登记的口径变为 50，最好改为从被哈希绑定的 proposal 派生；等 T28 r2 最终 SHA 登记与用户给出配额数字之后另起一卡，**本卡不做**。
