# ainerzero.V9.P10 执行报告：V9.P10 独立对抗复核 P9（S1 运行入口、资源门与预登记）

角色：reviewer（非 P9 作者）；负责人：workbuddy-t7m2（二级）；时间：2026-10-21（+03:00）
任务状态：reported；实验状态：未执行训练、未更新任何模型参数；被复核对象：ainerzero.V9.P9（reported）
任务依据：接力台 ainerzero.V9.P10 任务卡（参数 v0 `{}` 照用未改）+ 一级 11:53 notice（复核重点 a–e）

## 摘要（≤30 行）

1. 结论：**6 项卡面验收全部通过**，预登记身份、预算数学、封存、四臂预算、指标正确性均独立复现；建议一级**批准冻结预登记并进入 V9.P1**，但 P1 真正开跑前必须先修 F1–F4 四项（见「发现」）。
2. 预登记身份逐字节复现：document SHA256 `32c30f50…4de6`、file SHA256 `2602e42c…76a0`、sidecar 与 document 一致、两者都出现在 P9 报告里（C16）。
3. 预算数学独立重算：`estimate 359.93 s` → `deadline ceil(1.25×)=450 s` → `supervision 500 s`；`phase = 9×450 + 1×2 + 47.605 = 4099.605 s ≤ 14400 s`，单次 450 ≤ 1200 s。**360 s 估计确实已含占空比**：含 duty 359.93 s，不含 duty 仅 89.98 s（C17）。
4. 资源门 6 条线逐条构造不满足：进程内存/系统余量/MLX/占空比四条经**真实 CLI** exit 2 且原因正确；交换区增长与磁盘余量两条在启动门**不可由配置触发**（增长恒 0、磁盘线只能收紧），改用真实 `RuntimeGuard`/`assert_start` 注入探针 exit 2 触发（C1–C6b）。
5. 截止与监督超时只从冻结文件读：CLI `--wall-budget-seconds 99999` → exit 1「只能收紧」；9 个环境变量（含伪造 `PREREG_STATUS=approved`）全部无效；train 的 budget/supervision 恒为 450/500，即使传 `--wall-budget-seconds 5`（C7/C8/C10b）。
6. 共享锁：跨进程两进程同时启动，第二个 exit 1「A worker is already running」（C11）。RunStore 记录完整：全部终态、role=auxiliary、0 optimizer steps（C12b）。
7. final 分区：`require_partition`/`load_training_episodes`/`load_truth_view` 全部抛 `FinalPartitionSealed`；数据集内无 final 文件；AST 级扫描 S1 包**无任何**封存通道调用；AWZ artifacts 下无 final 产物（C13a/C13b）。
8. 三训练臂更新预算 3510/3510/3510、种子 0/1/2 完全一致；把 arm3 改成 3511 后 `validate()` 打回（C14）。指标已知答案精确（定位 0.0 / 位移 3.0 m，拓扑 P/R 1.0），改坏后变 0.0（C15）。
9. 冒烟无更新：沙箱内**独立重跑真实 smoke**（exit 0，4.94 s），四臂参数 SHA 前后一致、`gradients_computed=false`、`updated_parameters=false`，与 P9 记录同向（C12c）。
10. **对抗变异矩阵 12 项，测试只捕获 8 项**。未被捕获的 4 项是真缺口：删掉占空比 pacer（M1）、禁用 `evaluate()` 的 duty 分支（M2）、禁用 worker 侧 train 批准门（M11）、把 `parameters_unchanged` 改成恒 True（M12），67 项测试仍全绿。
11. **F1（最高）**：批准标志可自证伪造——把 `status` 改成 `approved`、重算 canonical SHA、重写 sidecar，`verify_frozen_file()` 与 `mode_train` 都会放行（C10a 实测进入训练分支）。环境变量/命令行伪造不了，但文件能。P9 今天仍然拒绝（C9 exit 3），所以不影响本次通过，但 P1 前必须加独立批准凭据。
12. 未碰真实锁与中央 RunStore：全部用例在 `src/` 的逐字节副本上跑（`spec.REPO_ROOT` 指向 `/tmp`）；真实 `artifacts/locks/m0-worker.lock` mtime 仍是 2026-09-22、`artifacts/control.sqlite3` 仍是 2026-10-14。
13. 只写了 `reports/V-V9-P9/`；未改源码、未提交/推送、未下载模型、未调用付费服务、未停用户服务。

## 输入身份

| 对象 | 身份 |
|---|---|
| 被复核源码 | `src/ainerzero/v9/experiments/s1/` 11 文件 + `src/ainerzero/cli.py` 的 `s1-phase1` 分支；副本 `src/` 逐字节同源（rsync），未修改原树 |
| 冻结预登记 | document `32c30f5005a438f759e14641f5ea77b635eb4020af7fa9ba823b7ad05bb74de6`；file `2602e42cad7bf39e5b6ac788d19e393dc22f9d0b07cca6c4ef525e0fcb0d76a0`；状态 `awaiting_coordinator_approval` |
| 数据集 | `dataset_digest 8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26`（沙箱副本，未重生成） |
| 沙箱 | `/private/tmp/vp9rev/sandbox`（`spec.REPO_ROOT` 解析到此）；锁 `…/artifacts/locks/m0-worker.lock` |
| 生产锁 / 中央账本 | `artifacts/locks/m0-worker.lock` mtime 2026-09-22T23:57:43；`artifacts/control.sqlite3` mtime 2026-10-14T23:00:59（均未写） |

## 修改文件

- 新增 `reports/V-V9-P9/`：`REPORT.md`、`metrics.json`、`evidence/{p1-resource-gate,p2-entry-lock-ledger,p3-final-metrics-sha,mutation-matrix}.json`、`harness/{p1_gate,p2_entry,p3_data,mutation}.py`。
- **未改任何源码、测试、配置或 P9 产物。**

## 实际执行（命令与退出码）

```sh
# 0) 作者测试复跑（只读）
PYTHONPATH=src .venv-ainerzero/bin/python -m pytest tests/v9/experiments -q
# -> 67 passed in 1.40s

# 1) 沙箱（逐字节副本，REPO_ROOT 指向 /tmp）
rsync -a src/ /tmp/vp9rev/sandbox/src/
# -> spec.REPO_ROOT = /private/tmp/vp9rev/sandbox

# 2) 资源门 / 3) 入口·锁·账本 / 4) final·预算·指标·SHA  （详见 harness/）
PYTHONPATH=/tmp/vp9rev/sandbox/src .venv-ainerzero/bin/python p1_gate.py     # 7/7
PYTHONPATH=/tmp/vp9rev/sandbox/src .venv-ainerzero/bin/python p2_entry.py    # 11/11
PYTHONPATH=/tmp/vp9rev/sandbox/src .venv-ainerzero/bin/python p3_data.py     # 7/7
PYTHONPATH=/tmp/vp9rev/sandbox/src .venv-ainerzero/bin/python mutation.py    # caught 8/12
```

## 验证结果（卡面 6 项逐条）

| # | 卡面要求 | 判定 | 关键命令（沙箱） | 退出码 / 证据 |
|---|---|---|---|---|
| 1 | 资源门每一项构造不满足 → CLI 真实拒绝且原因正确；截止/监督只从预登记读，CLI/环境变量不能放宽 | **通过** | `s1-phase1 --mode data --limits-file …`（逐线收紧/放宽）；`--wall-budget-seconds 99999`；9 个环境变量注入后 `--mode verify` | C1 exit 2 `process_memory_limit`；C2 exit 2 `system_reserve_limit`；C3 exit 2 `disk_free_limit`（注入）+ 放宽被拒；C4 exit 2 `training_duty_cycle … loosening refused`；C5 exit 2 `mlx_memory_limit`（MLX 实占 0.0625 GiB）；C6 `RuntimeGuard` 抛 `swap_growth_limit`；C7 exit 1「只能收紧」；C8a verify SHA 不变；C10b budget=450/supervision=500 |
| 2 | 共享锁：两进程同时启动只有一个能运行；RunStore 记录完整 | **通过** | 进程 A 持沙箱锁 5 s，进程 B 同时 `--mode smoke` | C11 exit 1 `RuntimeError: A worker is already running in this project`；C12b 1 个 run、全终态、role=auxiliary、0 optimizer steps |
| 3 | final 分区本阶段任何路径读不到（封存通道 read-once 计数不变） | **通过** | `require_partition("final")`、两个分区参数化 loader；AST 扫描封存通道调用；`find AWZ/artifacts -name '*final*'` | C13a 全部 `FinalPartitionSealed`、数据集无 final 文件、固定分区 loader 源码无 final 引用；C13b AST 命中 0、AWZ final 产物 0 |
| 4 | 三训练臂更新预算相同；指标脚本已知答案正确、改坏变红 | **通过** | 读冻结文件；`validate()` 篡改对照；`metrics.localization_error` / `topology_edge_metrics` | C14 3510/3510/3510、种子一致、arm3→3511 被 `validate()` 打回；C15 定位 0.0 / 3.0 m、拓扑 P/R 1.0→0.0；M7/M8 变异被测试捕获 |
| 5 | 预登记 SHA 与报告一致；冒烟未更新参数 | **通过** | 逐字节重算 document/file SHA；沙箱内独立重跑 `--mode smoke` | C16 两个 SHA 与报告一致、sidecar 一致；C12c exit 0、四臂参数 SHA 前后一致、`gradients_computed=false` |
| 6 | 总墙钟估算 ≤4 h、单次 ≤20 分钟 | **通过** | 重算 `9×deadline + arm1_deadline + 数据生成` | C17 4099.605 s ≤ 14400 s；单次 450 s ≤ 1200 s；估计含 duty（359.93 vs 不含 duty 89.98） |

## 一级复核重点（a–e）逐条回答

**(a) 占空比 0.25 是否在 worker 运行期真实执行？360 s 估计是否含占空比？**
- 估计**含**占空比：`estimate = (updates×3×step + eval) / 0.25 × 1.20 = 359.93 s`；同式不除 duty 只有 89.98 s（C17）。
- 运行期执行**只有一处**：`worker._train` 里的 pacer `rest = previous × (1/duty − 1)`，数学上得到 duty=0.25，但——
  - 它在 `_train` 内，而 `_train` 在本卡从未被执行（train 被拒），所以本卡**没有任何一次真实运行**能证明占空比被执行；
  - `evaluate()` 里那条 duty 检查是**死分支**：`validate_limits` 已保证 `0 < duty ≤ 0.25`，构造不出能到达它的输入（C6b 对 10 个 duty 值穷举，可达集为空）；
  - 你要的「把 pacer 关掉后测试必须变红」的对照**不存在**：删掉 pacer 后 67 项仍全绿（M1），禁用 `evaluate()` duty 分支后也全绿（M2）。
- 结论：占空比目前是**代码阅读级**保证，不是回归级保证。P1 前必须补一个能测出 pacer 的用例（见 F2）。

**(b) 测试与证据运行是否碰过真实 `artifacts/locks/m0-worker.lock`？**
- 单元测试：**没有**。全部用 `tmp_path`，`_lock_path()` 只在 CLI 子进程里被调用，而三条 CLI 用例都在取锁前就被拒绝。
- 证据运行：**短暂独占过真实锁**。`evidence/refusal-lock-busy.json` 的存在本身就要求有一个进程持有真实锁、另一个被拒；`refusal-budget-guard.json` 是真实 `--mode smoke --wall-budget-seconds 2`，会先取真实锁再在 worker 里被预算守卫拦下。
- 影响面：真实锁文件**内容与 mtime 未变**（2026-09-22T23:57:43），中央 `artifacts/control.sqlite3` **未被写**（mtime 2026-10-14T23:00:59），账本落在卡内 `reports/V9-P9/control.sqlite3`。结论：可接受，但正式运行必须由 relay-runner 串行化，不要再让证据运行去争生产锁。

**(c) 一级裁定的 `artifacts/v9/s1/phase1/`（账本）+ `artifacts/v9/s1/datasets/<digest>/`（数据）双根布局，能否不改冻结参数就支持？**
- **不能，需要加参数（但不改冻结值）**。`commands.py` 把账本写死为 `output_root/control.sqlite3`，数据集写死为 `output_root/dataset`，只有一个 `--output-root`。
- 实测：`--mode verify --output-root <新目录>` → `status=refused, stage=prereg_missing`，exit 2（C19）；数据集不在 `output_root/dataset` 时 `--mode smoke` → `stage=dataset_missing`，exit 2（C19b）。
- 因此裁定布局目前只能退化成 `artifacts/v9/s1/datasets/<digest>/dataset/` + `…/control.sqlite3`（同根）。建议加 `--dataset-root` / `--control-db` 两个参数；`pre_registration.json` 不记录这两个路径（只有 `commands` 块里的示例命令字符串），所以**不需要改任何冻结值**，只是若想让记录的命令与实际一致才需要重新 freeze（那会换 SHA）。

**(d) 正式运行经 launchd 托管的 relay-runner 时，能否确认进程组为空？**
- **不能靠「换成 launchd」解决**。本会话独立复现了同一限制：`ps -o pid=,pgid= -p $$` → `operation not permitted`，exit 127。
- 根因不在托管方式，而在 `ps` 被沙箱拒绝：`AinerRelay/deploy/snapshots/…/relay/cli.py:544` 用 `ps -ax -o pid=,pgid=,stat=` 枚举进程组，`relay/runner.py:91` 与 `bin/relay-runner` 的存活检查也用 `ps`。同一策略下 launchd 子进程同样被拒。
- 建议：组枚举改用 `os.killpg(pgid, 0)`（`ProcessLookupError` 即组空）+ `os.waitpid(pid, WNOHANG)`，不再依赖 `ps`。P9 的 `exit_unconfirmed` 与手动补归档因此是**环境限制的如实记录**，不是掩盖；但它也说明「正式运行能被监督确认」这条目前**未验证**。

**(e) train 未获批准必须拒绝；批准标志不能由环境变量或命令行伪造？**
- 拒绝成立：`--mode train` → exit 3、`stage=preregistration_not_approved`、`preregistration_status=awaiting_coordinator_approval`（C9）；worker 侧还有第二道同样的检查。
- 环境变量/命令行**伪造不了**：S1 包内 `os.environ` 只有一处，是给 AWZ 生产者子进程**写** env（`data.py:158 generation_environment`），没有任何读入冻结参数的路径（C8b）；注入 9 个变量（含 `PREREG_STATUS=approved`、`AINERZERO_APPROVED=1`）后 verify 的 SHA 不变（C8a）；`--wall-budget-seconds 5` 也改不动 train 的 450/500（C10b）。
- **但文件能伪造**（F1）：`verify_frozen_file()` 只把 document SHA 与旁边的 `.sha256` 比对，批准状态就是文档里的一个字符串。把 `status` 改 `approved`、重算 canonical SHA、重写 sidecar 后，`verify_frozen_file()` 通过、`mode_train` 直接进入训练分支（C10a 用 monkeypatch 截获，未真的训练）。唯一的外部锚点是你们手里钉住的 `32c30f50…`（伪造后 SHA 变成 `22434db9…`，可被人工发现），但代码不校验这个钉。

## 对抗变异矩阵（12 项）

| 变异 | 位置 | 结果 |
|---|---|---|
| M1 删除占空比 pacer 睡眠 | `worker._train` | **MISSED** 67 passed |
| M2 禁用 `evaluate()` duty 检查 | `resource_gate` | **MISSED** 67 passed |
| M3 删除交换区增长线 | `resource_gate` | CAUGHT 1 failed |
| M4 删除系统余量线 | `resource_gate` | CAUGHT 1 failed |
| M5 删除进程内存线 | `resource_gate` | CAUGHT 4 failed |
| M6 删除 MLX 峰值线 | `resource_gate` | CAUGHT 1 failed |
| M7 定位误差恒为 0 | `metrics` | CAUGHT 1 failed |
| M8 arm3 预算 +1 | `prereg` | CAUGHT 14 failed |
| M9 final 不再抛 `FinalPartitionSealed` | `data` | CAUGHT 1 failed |
| M10 禁用 CLI 侧 train 批准检查 | `commands` | CAUGHT 1 failed |
| M11 禁用 worker 侧 train 批准检查 | `worker` | **MISSED** 67 passed |
| M12 `parameters_unchanged` 恒 True | `smoke` | **MISSED** 67 passed |

## 发现（按严重度）

| ID | 级别 | 问题 | 证据 | P1 前 |
|---|---|---|---|---|
| F1 | **高** | 批准标志自证：改 `status`+重算 SHA+重写 sidecar 即被 `mode_train` 接受；无独立批准凭据，代码不校验一级钉住的 SHA | C10a | 必修 |
| F2 | 中 | 占空比只有代码阅读级保证：pacer 无测试（M1）、`evaluate()` duty 分支不可达且无测试（C6b/M2） | M1, M2, C6b | 必修 |
| F3 | 中 | worker 侧 train 批准门（纵深防御）删掉后测试仍全绿 | M11 | 必修 |
| F4 | 中 | `parameters_unchanged` 改成恒 True 后测试仍全绿；无更新只靠产物自述（本次已独立重跑确认一次） | M12, C12c | 必修 |
| F5 | 低 | `EXIT_LOCK_BUSY=4` 从未返回，锁忙实际 exit 1；`worker.PER_RUN_BUDGET` 定义后未使用 | C11 | 建议 |
| F6 | 低 | `prereg_missing` / `dataset_missing` 也返回 exit 2（=资源拒绝码），自动化会误判为资源门拒绝 | C19, C19b | 建议 |
| F7 | 低 | 交换区增长线与磁盘余量线在启动门**不可由配置触发**（增长恒 0；磁盘线只能收紧→更易通过），只能靠运行期守卫或真实低余量 | C3, C6 | 记录 |
| F8 | 信息 | `phase_wall` 用 deadline 而非 supervision 计；9 次监督全触发的最坏值 4599.6 s，仍 ≤4 h | C17 | — |
| F9 | 信息 | pacer 的 `min(rest, 2.0)` 使单步 >0.667 s 时 duty>0.25；且 pacer 不计 checkpoint eval 时间。当前 6 ms 步长无影响，但不是结构性保证 | 代码 + 数学 | 记录 |
| F10 | 信息 | 账本与数据集绑在同一个 `--output-root`，裁定双根布局需加 `--dataset-root/--control-db` | C19 | 见 (c) |
| F11 | 信息 | `ps` 被沙箱拒绝，relay 的组枚举（`relay/cli.py:544`）依赖 `ps`，launchd 托管不能修复 | 本会话 exit 127 | 见 (d) |
| F12 | 信息 | P9 的单元测试未碰真实锁；两条证据运行短暂独占过真实锁（产生锁忙证据的必要条件），未写内容、未写中央账本 | 锁/账本 mtime | 记录 |

## 失败与限制

- 未执行真实训练（本卡不需要，也不允许）：`train` 分支只在 F1 的 monkeypatch 场景下被截获参数，**没有跑过一步优化**。
- 未重新生成数据集（17 MB，直接用 P9 产物的副本）；数据集身份按 P9 的 manifest/digest 复核，未逐 packet 重算 9500 条的语义正确性（超出本卡「运行监督代码」范围）。
- 未验证 launchd 托管下的 relay-runner（不能起系统服务，也不该起）；(d) 只给到根因与建议。
- 未验证 `artifacts/v9/s1/...` 双根布局的实际落盘（需要改代码），只证明了当前不支持。
- 沙箱内 smoke 的 `arm2` 单步 6.00 ms vs P9 记录 6.96 ms：同机不同进程的测量抖动，方向一致，不构成不一致。

## 交回统筹

1. **建议：通过，批准冻结预登记 `32c30f50…4de6`，发布 V9.P1**；同时把 F1–F4 作为 P1 开跑的前置条件（都不需要改冻结参数，只改测试与批准流程）。
2. 需要一级裁定：F1 的批准凭据形式（建议 `approval.json` 记录 `approved_document_sha256` + 批准人/时间，代码同时校验该 SHA 与侧车一致）。
3. 需要一级确认 (c) 的双根布局是否要加 `--dataset-root`/`--control-db`；若要，建议放在 P1 之前一次性改完并重新 freeze（会换 SHA，需重新钉）。
4. (d) 建议把 relay 的进程组确认从 `ps` 改成 `killpg(0)`/`waitpid`，这是接力台侧改动，不在本项目文件范围内。
