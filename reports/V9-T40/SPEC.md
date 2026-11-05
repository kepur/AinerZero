# V9.T40 规格：T37 后续收口（作者 claude-az；复核必须由他人，见 T41）

依据：T38（gemini-9e5a）对 T37 的复核，加上我对 T28 r2 驱动 runner 时的发现。纯 CPU，零模型，不碰锁与 `runs.db`。

## 要做的
1. **runner 读懂 r2**：`load_plan` 不再无条件解析 `negative_controls.intrinsics`（缺失时 `focal_scale=(1.0,1.0)`，仍要求 `required_red` 可解析）。最小补丁已在仓外验证（`reports/V9-T28/r2/check_r2.py` 第 4b 节）。
2. **`--proposal` 与 `T6_PROPOSAL_PATH`**：runner 的 T28 路径可由参数/环境变量指定；默认**仍指向 r1**，直到 r2 被登记后另行切换（不在本卡切）。证据里记录所用 proposal 的**路径和 SHA**。
3. **证据逐阶段落盘**：运行开始即原子写入 `status:"in_progress"` 的证据，每个阶段结束再原子更新（临时文件 + rename）。理由：MPS 上 fp16 的 dtype 错误是 Metal 断言导致的 SIGABRT（退出码 134），进程直接消失，旧实现只在最后写证据，会什么都不留。
4. **worker 未真跑即拒绝**：`allow_model_execution` 已授权但标定 runner 没有被执行时，返回非零（4）并写明原因，而不是 `status:completed`。T37 只把 `model_runs` 改成了如实的 0，没解决「账本预扣视图、worker 零前向、rc=0」的陷阱。同步修改 `tests/test_da3_supervision.py` 里固定了旧行为的断言——这是**语义更正**，不是放宽。
   不要把「是否运行」绑在魔数 `views == 18` 上以外的新魔数上；记账口径（数据集视图 18 vs 前向视图 56）尚待用户决定，所以本卡**不改**那个门的数值，只改「不运行时的结果」。
5. **补 T38 找到的 3 个存活变异的断言**：
   - NEW-5：`FakeFactory` 能分别扰动 `confidence` / `extrinsics` / `intrinsics`；每个字段单独越界都必须让对拍失败（并保留 `depth` 单独越界的用例）。
   - NEW-6：固定世界划分后断言 `fit.n_fit == 3`（及 4 个 fit 世界时 `rank_ceiling == 3`，且 `rank == min(n-1, 秩)`），去掉 `... or ...<= 2` 这种会被短路的断言；holdout 不得进入 fit 协方差。
   - NEW-8：`fit_statistics` 的协方差与 `np.cov(x.T, ddof=1)` 逐元素相等（容差 1e-12）。
6. **新增护栏测试**：①用**真实的 r2 `proposal.json`**（`reports/V9-T28/r2/`）驱动 runner（假 teacher、能力位=真实 DA3 的 False）整条跑通；②在子进程里让假 teacher 在某阶段 `os._exit(134)`，断言证据文件存在、`status=="in_progress"`、已完成阶段的结果仍在。
7. 修正报告里的笔误：T38 把 `EXIT_STAGE_FAILED` 写成 2，实际是 5（2 是 `EXIT_PREFLIGHT`）。无需改代码，只在 T40 报告里澄清。

## 不在本卡内（等用户决定，不要自行处理）
- `half_parity`（MPS/F16）在现有管线上必崩：CPU 抛 `RuntimeError: mat1 and mat2 must have the same dtype, but got Float and Half`，**MPS 是 Metal 断言 SIGABRT**。处理方式（删掉该阶段 / 改成 autocast-fp16）是协议与管线的决定。
- 配额记账口径与具体数字；T28 r2 的 SHA 登记。
- 任何对 `envs/teachers/t6/pipeline.py` 的改动（其 SHA 被缓存键绑定）。

## 红线
零模型加载；不跑 `teacher-da3 --mode run`；不碰 `artifacts/locks/m0-worker.lock` 与 `artifacts/v9/teachers/benchmark/runs.db`（SHA 前缀 `64b668050dfbab7a`，前后必须相同）；不改 `reports/V9-T28/` 下 r1/r2/reviewed-0e15033a 任何文件；不推送、不下载、不付费。
全量测试请**接 AC**，前台跑或用 `signal.signal(SIGINT, SIG_DFL)` 还原后 `execv`。

## 交回
`reports/V9-T40/REPORT.md` + `metrics.json`：每项的修复位置、新增测试清单、变异验证（把 T38 的 NEW-5/6/8 与新增的 3 个变异都注入一遍，必须全部被抓到）、`runs_db_sha_unchanged`、`no_model_loaded`。
