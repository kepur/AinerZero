# ainerzero.V9.T37 执行报告：DA3 标定 runner 重写（r1 缺陷 11 处，其中 2 处使整份证据作废）

执行：claude-az（一级托管，用户 2026-10-27 指示亲自执行）。**所以 T38 复核不得由 claude-az、antigravity-66bc、antigravity-r8ia、antigravity-u2a7 做。**
范围：纯 CPU。**未加载任何模型，未运行 `teacher-da3 --mode run`，未碰 `m0-worker.lock` 与 RunStore**
（生产台账 `artifacts/v9/teachers/benchmark/runs.db` SHA 前后均为 `64b668050dfbab7a…`，锁文件 mtime 不变）。

## 结论
卡里写的是"修两处调用 + 补测试"。核对 runner 对着冻结的 T28 预登记之后，**范围大得多**：这是一段从未被执行过的代码，
即使只修尺寸让它跑通，也会用错误的约定算出一份协方差，并标成"诊断候选"。已整体重写，并发现一处**协议本身不可满足**（见 AMENDMENT_PROPOSAL.md，需用户批准）。

## r1 runner 缺陷清单（状态）
| # | 缺陷 | 严重度 | 状态 |
|---|---|---|---|
| D1 | `compute_depth_metrics(pred 378×504, gt 210×280)` 尺寸不等 → 崩溃（T35 r2 的直接原因）。根因是 `process_res=504`，T28 规定 **280**（输出 210×280，天然同形） | 崩溃 | 已修：按 T28 用 280；尺寸不等变**硬错误**，不做任何静默缩放 |
| D2 | **约定错误**：管线 `extrinsics` 是 world→camera，runner 当 camera→world 喂 T28 公式 | **数值全错、无报错** | 已修：`w2c_to_c2w` 取逆；world 0 平移残差 1.04 → 0.083 |
| D3 | 用**绝对**位姿比较旋转/平移（DA3 参考系 vs 房间系，且 DA3 自选参考视图 `saddle_balanced`） | **数值全错、无报错**；也是"180°偏移"被写死的由来 | 已修：全部走 T28 锚点相对量 |
| D4 | 深度指标用 `compute_depth_metrics`，对**目标视图自拟合**中位数；T28 明令"不对目标视图再拟合" | 违反预登记 | 已修：s_depth 取自锚点视图 0 |
| D5 | **编造的证据**：逆向控制 3、4 没执行却无条件写 `"verified": True`；`rotation_offset_deg: 180`、"基线共线"说明、`full_calibration_completed: True`、`views_consumed: 18` 都是读到数据之前的常量 | 证据会撒谎 | 已删：证据字段只由测量值产生；静态护栏测试防止复活 |
| D6 | 缺 T28 阶段（first_frame / 真实逆序 / 内参逆向）；对拍只比 depth、单帧对三帧、阈值写死 0.1；T28 要 4 个字段、CPU atol/rtol=1e-3、半精度 1e-2、"结果出来后不得放宽" | 违反预登记 | 已修：阶段、容差、阈值、`required_red` 公式全部从 T28 JSON 读取 |
| D7 | 对拍/控制失败仍退出 0；worker 照样报 `completed` | 违反 T28 失败策略 | 已修：退出码 5；runner 返回码经 worker 透传 |
| D8 | **T28 的"已知 K + 内参逆向控制"在这版 DA3 上不可满足**（`da3.py:126` 无外参则忽略内参） | **协议级** | 未改协议（需用户批准）；runner 加了模型加载前的可满足性预检，当前对真实 DA3 拒绝（退出码 6） |
| D9 | worker 默认把输出写进已交付的 `reports/V9-T35/predictions`，而管线**拒绝已存在目录** → 下一次真跑在第一个世界就崩 | 白烧授权 | 已修：每次运行唯一目录 `reports/V9-T6/calibration-runs/<UTC>-pid<pid>/`；runner 预检拒绝非空输出目录 |
| D10 | worker 在 `views != 18` 时一次前向都不做，却返回 `status:completed, model_runs:1` | 失败开放 | 已修（兼容）：`model_runs` 如实为 0，新增 `real_forward_executed`；保持返回码以免破坏已验收测试，建议后续改为拒绝 |
| D11 | fit/holdout 世界名单、`round:"r1"`、协方差秩上限 2 均写死 | 低 | 已修：世界划分来自 T28 并与 manifest 交叉校验；秩上限由样本数计算 |
另有：**账本按 CLI `--views` 记账，而 T28 计划每模型 31/合计 62 个前向视图**（见 AMENDMENT_PROPOSAL.md）——未改，需用户定口径。

## 改动文件（SHA 见 `evidence/SHA.txt`；r1 原件留存 `evidence/da3_calibration_runner.r1-original.py`，SHA `73e3418c…`）
- 新增 `src/ainerzero/v9/teachers/da3_calibration_math.py`：纯 numpy 数学（约定转换、T28 锚点残差、对拍、`required_red`、协方差统计）。
- 重写 `src/ainerzero/v9/teachers/da3_calibration_runner.py`：计划来自 T28 并核对 proposal / manifest / 协议 / 生成器 SHA；teacher 工厂可注入；
  `--preflight-only`（零模型零账本）；退出码 0/1/2/5/6；证据只含测量值。
- 修改 `da3_worker.py`（D9、D10）。
- 未改：`pipeline.py`、`noise_calibration.py`、任何冻结协议/夹具/已交付证据。（`pipeline.py` 没动是有意的：它的 SHA 被缓存键绑定。）
- 测试隔离修复：`tests/test_teacher_da3_controlled.py` 里 3 条 CLI 测试此前直接读**生产** RunStore——T35 真跑把累计视图推到 81 后，
  默认 views=4 的投影越界，2 条因生产配额状态而红，与被测代码无关。改为在临时工作目录里跑（默认台账/锁是相对路径；
  只读链入真实 RESEARCH_LOG 与权重，**不能**改用 `--store-path`，因为正式 run 模式禁止自定义台账，那会改变被测行为）。
- `tests/test_da3_supervision.py` 加 2 句断言固定 D10 的诚实化。

## 测试
- 新增 `tests/test_da3_calibration_runner.py`：**23 条**，全绿（0.95 s）。含：原始崩溃的回归、约定回归、锚点相对不变性、不自拟合、π 分支拒绝、对拍规则、
  可满足性预检（不可满足时 `make` 调用次数为 0 且不创建任何文件）、上游漂移探测、预检拒绝旧目录、篡改 proposal 被拒、
  整条流程（假 teacher，T28 的 11 次前向/31 视图、单模型常驻、逆向控制真的变红、对拍通过）、对拍失败退非零并保留输出、
  控制不变红算失败、输出尺寸不对大声失败、静态护栏、真实 world-0 冒烟、修订协议后的可运行性。
- 与既有 DA3 teacher 测试合跑共 48 条（`test_da3_calibration_runner` 23 + supervision 10 + controlled + views_82）。**如实说明跑法：**接 AC 时一次跑了前 47 条（含新增 22 条）全过；第 23 条（修订协议可运行性）是之后追加并单独跑过 23/23。交卷前我再合跑时机器已经切到电池：**44 passed / 4 failed，4 条都是既有的电源守卫测试**（`BenchmarkResourceRefused: Power source is battery; AC power required`，`test_cumulative_budget…`、`test_worker_lock_mutual_exclusion`、`test_coordinator_release_gate_and_cli` 等），守卫按设计在拒绝。台账 SHA 与锁 mtime 未变。**复核请在接 AC 时跑。**
- **反向验证（10 个注入缺陷，仓外副本）**：全部被抓到，结果见 `evidence/mutation-results.txt`、脚本 `evidence/mutate_t37.py`：
  约定错误(3 红)、静默缩放(1)、目标视图自拟合(1)、写死 verified(1)、真实工厂谎称能用 K(1)、对拍失败被吞(1)、控制不变红也过(2)、
  失败退出 0(3)、预检放过旧目录(1)、写死结论字段(2)。

## 真实数据冒烟（T35 r2 真跑留下的 world-0 / DA3-SMALL，process_res=504 的历史原件；**不是标定结论**）
锚点相对口径（正确）：`rotation_deg=0.981`、平移残差范数 `0.0830`、`depth_abs_rel=0.0924`、`depth_delta1=0.9974`，
`residual_7d=[0.00559, -0.01614, -0.00124, -0.03632, 0.03308, 0.06695, -0.01801]`。
错误约定（r1）：平移残差范数 `1.04`。卡里给的 `0.0926/0.0904/0.0905` 是目标视图自拟合的 abs_rel（口径不同），量级吻合。
（504→280 的双线性缩放只用于这份历史原件的冒烟；runner 本身不缩放。）

## 剩余风险 / 需要别人做
1. **T28 修订需用户批准**（`AMENDMENT_PROPOSAL.md`），之后要新预登记 + 独立数学复核 + 一级登记 SHA。
2. **配额记账口径需用户定**（数据集视图 vs 前向视图）。
3. DA3 真实输出在 CPU/MPS-fp16 上能否满足 atol/rtol=1e-3/1e-2 **未知**（按 T28 不得放宽；失败即失败）。
4. `DA3GeometryTeacher` 的 `extrinsics`/`confidence` 形状、dtype 只靠 `checked_predictions` 与我对 world-0 真实输出的观察，假 teacher 是按此造的。
5. 本卡改了 `da3_worker.py`（D9/D10），T38 需一并复核。
6. 下一次真跑前必须先跑 `da3_calibration_runner.py --preflight-only`（零模型、零账本）——中央 CLI 在启动 worker 前就会预留视图与墙钟，
   worker 内的拒绝已经来不及保住配额。
