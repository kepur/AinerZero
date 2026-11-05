# ainerzero.V9.T40 执行报告：T37 后续收口（作者 claude-az；复核必须由他人，见 T41）

纯 CPU，零模型，未碰 `m0-worker.lock` 与 `runs.db`（SHA 前缀 `64b668050dfbab7a`、锁 mtime `1790110663`，前后均不变）。`pipeline.py` 未动。T28 的 r1/r2/`reviewed-0e15033a` 未动。
变更行数 229，逐文件 diff 见 `evidence/t37-to-t40.diff`；基线在 `evidence/t37-accepted/`（`da3_controlled.py` 与 `test_teacher_da3_controlled.py` 两个基线是我动手前没存、事后用反向还原重建的，见 `BASELINE_NOTE.txt`；其余三个是真实拷贝）。

## 做了什么
| # | 内容 | 位置 |
|---|---|---|
| 1 | **runner 读懂 r2**：`load_plan` 不再无条件解析 `negative_controls.intrinsics`（缺失 → `focal_scale=(1.0,1.0)`，`required_red` 仍必须可解析） | `da3_calibration_runner.py` |
| 2 | **`--proposal` 与 `T6_PROPOSAL_PATH`**；默认**仍是 r1**（r2 登记前不切换）；`--preflight-only` 也用它；证据记录 proposal 的**路径与 SHA** | 同上 |
| 3 | **证据逐阶段原子落盘**：开始即写 `status:"in_progress"`，每个阶段结束再写（临时文件 + `os.replace`）。理由：MPS fp16 的 dtype 错误是 Metal 断言 SIGABRT（退出码 134），进程直接消失，旧实现只在最后写证据，会什么都不留 | 同上 |
| 4 | **worker 未真跑就拒绝**：已授权但标定 runner 没启动 → 退出码 4、`status:"refused_no_calibration"`，不再 `completed`。同步订正 `test_da3_supervision` 里固定了旧行为的断言（语义更正，不是放宽） | `da3_worker.py`、`test_da3_supervision.py` |
| 5 | **测试替身绝不触达真实管线**（本卡新发现，见下） | `da3_controlled.py` |
| 6 | 补 T38 的 3 个存活变异（NEW-5/6/8）；去掉会被 `or` 短路的断言；给假 teacher 加「只扰动某字段」与「每世界不同的位姿噪声」 | `test_da3_calibration_runner.py` |
| 7 | 修旧测试：「修订协议可运行性」那条原来只删了阶段、没删 `negative_controls.intrinsics`，所以没抓到 r2 上的 `KeyError`。现已与真实 r2 一致 | 同上 |

## 本卡新发现：测试替身会走真实管线
`execute_guarded_da3_benchmark` 里 `action = worker_action or ("real_pipeline" if is_released else "mock_run")` 完全不看 `test_substitute`；`is_released = coordinator_release or allow_model_execution or …`。
所以「放行 + 授权 + `test_substitute=True`」会把 CPU 测试替身也送进 `real_pipeline`。`test_coordinator_release_gate_and_cli` 之所以没真跑模型，**纯粹因为它的 `views=4` 被 worker 的 `views == 18` 魔数挡住**——这是我改 worker（第 4 项）后那条测试变红时才看出来的。
若有人把它的 views 改成 18，**单元测试会在机器上启动一次真实 DA3 前向**。已修：`test_substitute` 恒走 `mock_run`，显式要求 `real_pipeline` 则抛 `BenchmarkRefusalError`。
新测试 `test_test_substitute_never_selects_the_real_pipeline_even_when_released` 用探针截获 action，**不调用任何真实 worker**，并且走不到探针就失败（我第一版用了带默认值的 `.get`，空转了，已重写）。

## 测试
- `test_da3_calibration_runner.py`：23 → 34 条；全套 DA3 teacher 测试 **60 passed**（接 AC，74.9 s）。
- 新增：真实 r2 驱动整条流程；`--proposal`/环境变量/预检退出码（默认 r1 → 6，r2 → 0）；硬中止（最后阶段、第一个阶段之前）后证据仍在；原子写；对拍四个字段各自单独越界必须失败（参数化）；fit 统计只来自 fit 世界且协方差等于 `np.cov(ddof=1)`；`fit_statistics` 单元对 numpy。
- **反向验证**（仓外镜像，`evidence/mutate_t40.py`、`evidence/mutation-results.txt`）：T38 的 3 个存活变异 + 本卡 6 个，共 **9/9 被抓到**。首轮 `T40-c`（去掉开始时的 in_progress 落盘）没被抓到——因为每阶段落盘已经把文件写出来了——所以补了「第一次 `make()` 就硬中止」的测试，重跑 9/9。
- worker 拒绝逻辑与 `da3_controlled` 的修复各自在仓外镜像里注入还原，对应测试变红（`rc 0 != 4`；`seen["action"]` 为 real_pipeline）。

## 如实交代
- T38 报告 §1.1 的文件 SHA 表 6 个值全部与磁盘不符却标「一致」（已向 gemini-9e5a 发 notice #694 要求解释）；磁盘文件自 T37 交卷起未被改动，其实质结论我独立复现过，T37 验收不撤销。
- T38 把 `EXIT_STAGE_FAILED` 写成 2，实际是 5（2 是 `EXIT_PREFLIGHT`）。
- 我首轮在 `test_da3_supervision` 里加了一行 `.replace("nothing","")` 的别扭断言，已删。

## 未做 / 等用户（不在本卡内）
1. **`half_parity`（MPS/F16）在现有管线上必崩**：CPU 抛 `RuntimeError: mat1 and mat2 must have the same dtype, but got Float and Half`；**MPS 是 Metal 断言，进程 SIGABRT（退出码 134），无 Python 异常**。根因：`pipeline.py` 的 `ExplicitPrecisionDA3` 关 autocast + `model.to(float16)`，而上游 `CameraDec.forward` 写死 `self.fc_t(feat.float())`（`DualDPT` 位置编码同样写死 fp32）。是删掉该阶段还是改管线为 autocast-fp16，是协议与管线的决定。第 3 项只保证它崩的时候证据还在，不保证它不崩。
2. worker 的 `views == 18` 门的**数值**：账本口径（数据集视图 18 vs 前向视图 56）等用户定；本卡只改了「不运行时的结果」。
3. 默认 `PROPOSAL_PATH` 仍是 r1；r2 登记后另行切换。
4. T28 r2 的 SHA 登记；配额数字。

## 给复核人（T41）
- 比 diff：`evidence/t37-to-t40.diff`；自己再想 ≥3 个变异，重点：原子写的失败路径、`in_progress` 被误当成功、`--proposal` 指向不存在文件时的行为、环境变量与参数同时给出时谁优先（现为参数优先）。
- 重点审第 5 项：确认 `test_substitute` 在**所有**调用路径（CLI `--test-substitute`、Python API）都到不了 `real_pipeline`；找有没有别的地方也靠 `views == 18` 这种魔数在「碰巧」保护。
- 测试请**接 AC**，前台跑，或还原 SIGINT 后 `execv`。
