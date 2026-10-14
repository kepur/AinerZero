# E13b：M2m-d 独立入口与训练路径接入规格

日期：2026-10-12 · 本规格主责统筹：Claude（M2m-d 协议总主责仍为 Codex） · 状态：**E13b 已 reported，统筹 reviewed、未 accepted；需完成文末 R1（paired 全复算＋C06a 探针入口）后交 E14b；不授权任何模型运行**。

依据：[M2m-d 固定协议](M2MD_ACTION_PRESERVATION.md)、[E13a-R2 边界](E13A_IDENTITY_BOUNDARY.md)、[E14a-R2 独立回验](artifacts/reports/E14a-R2-independent-review-20261012.md)、[Claude 复核](artifacts/reports/E13a-R2-claude-coordinator-review-20261012.md)。本文件只固定接入的文件、接口与 CPU 验收；科学参数、预算、门槛和保护线均以 M2m-d 协议为准，不在此改动。

## 文件范围

| 文件 | E13b 权限 | 说明 |
| --- | --- | --- |
| `src/ainerzero/learning/action_preservation_closure.py` | 新建 | 纯 CPU：生产输入闭包、固定比较值、M2l/M2m-c 复用闭包、缓存 expected binding、保持门判定；不得导入 MLX |
| `src/ainerzero/learning/action_preservation_mlx.py` | 新建 | MLX：教师缓存生产、单行保持损失；只在 worker 的 initialization 之后才被导入 |
| `src/ainerzero/runtime/memory_worker.py` | 修改 | 新增 `action_preservation_fit` 分支及其 plan；旧分支行为与 plan 不变 |
| `src/ainerzero/cli.py` | 修改 | 新子命令 `train-action-preserved-memory` 与分派、监督截止 |
| `tests/test_action_preservation_closure.py`、`tests/test_action_preservation_entry.py` | 新建 | 仅 CPU/静态测试 |
| `action_preservation.py`、其测试与 fixture、`tail_update.py`、`relabel_memory.py`、旧协议/报告、根目录文档 | **不改** | E13a 已验收的 CPU 层保持原字节；需要的常量和生产门放在 closure 模块 |

执行者先在 [任务表](AGENT_TASKS.md) 领取，只交自己的实现报告、XML/log；根目录结论由统筹整合。

## 接口固定

### 1. CPU 闭包（`action_preservation_closure.py`）

- 常量：`REGISTERED_KEY_MANIFEST_SHA256 = "71deb0f0b98be564f04227225ff5925108c479223910de3e1d3442b37542c1ca"`、`REGISTERED_KEYS_CONTENT_SHA256 = "5a6449008da160e7b32c3056d724c4fd954efba8008ce62478bd67411d6c4ad1"`、M2m-c 报告文件 SHA `47d1f1c8…3216`、M2m-c run `9169008d-348b-47b3-8519-8f87affcb60c`。窗口固定值复用 `ap.REGISTERED_WINDOWS_SHA256`，不得复制成第二份可漂移常量。
- `public_records_from_episodes(train_episodes)`：从 `load_pilot_dataset` 已按 dataset manifest 校验的 train episode 独立构造 public_records；身份算法与 `diverse_memory.select_diverse_memory_samples` 相同。transitions 的键与 `target_tick` 必须是 Python `int`，不能用 JSON 字符串或 `np.int64`（B2）。
- `production_windows(samples, schedule, public_records)`：调用 `ap.verify_registered_inputs(..., partition="train", public_records=...)`，然后**不读取任何标志**，独立要求 `registered_input` 存在、`ap.validate_windows` 通过、`ap.key_manifest(windows)` 的 `manifest_sha256` 与 `keys_sha256` 分别等于两个常量（B1）。返回窗口、键清单和逐更新学生单位表。降级成通用窗口、缺 records、键绑定不符都要拒绝。
- `student_units_per_update(windows)`：`[Σ_{r∈schedule[u]} (1 + feedback_r + 4)]`，必须共 200 项、总和 27,988；当前登记清单逐项在 137–144 之间。
- `m2l_reuse_closure(m2mc_report_path, relabel_binding, store)`：在任何模型工作之前只读核对：M2m-c 报告文件 SHA；其 `relabel.m2l` 引用与本次 `_prepare_relabel` 重建的 M2l 引用逐字段相同；`m2l_paired_reproduction.exact_match` 为 True；`cells.m2l`（2,560）与 `relabel_pool.m2l_cells` 的 shape/顺序/有限性；从逐格结果做 CPU 复算：换名池用 `summarize_relabel_pool` 对照 `relabel_pool.m2l`，配对部分按原 query/group/world 规则对照 M2l 报告的 paired 统计（`paired_memory` 只有私有计数函数，若不能直接复用，就在 closure 中实现并单独测试）；RunStore 中 M2m-c run 为 completed、role model、200 步、预留 264,480 单位，M2l run 沿用现有核对。返回复用的两组逐格结果及证据摘要。不加载或推理 M2l 权重。
- `expected_cache_binding(...)`：从上面已核对的值构造 `ap.validate_cache_binding` 要求的 14 个字段：`teacher_checkpoint_manifest_sha256` 为 M2d `manifest.json` 文件 SHA；`teacher_source_sha256` 为 `pilot_model.py`、`action_preservation.py`、`action_preservation_mlx.py` 三个文件字节 SHA 的规范摘要；`training_samples_sha256`/`schedule_sha256`/`windows_sha256` 用登记逻辑值；`key_manifest_sha256` 用 v2 绑定常量；`run_id` 为本次 run。不得从待验 cache 或 manifest 抄写 expected。
- `preservation_screen(before, after, paired, relabel_pool)`：按 `ap.PRESERVATION_GATES` 用整数计数和原始浮点判定（边界值算通过，不四舍五入）；动作 NLL 增幅相对本次 `before`（原 M2d）。只判定、不晋升。

### 2. MLX 保持分支（`action_preservation_mlx.py`）

- 唯一造键函数 `_key(seed_u32) = mx.random.key(int(seed_u32))`，seed 来自 `ap.key_manifest`；保持路径不使用全局 seed、`split`、`fold` 或其他 RNG。记忆分支原样沿用 `mx.random.key(2203)` 的固定 4 份 split。
- `build_teacher_cache(teacher, episodes, windows, keys, *, before_work)`：教师逐世界 **B=1**，从 `model.initial(1)` 开始按 `teacher_online` 键因果推进到 qmax，在 s 帧 observe 之前记录 incoming_h；每个池行在 q 的 posterior 状态上用 query 键做 4 步 imagine，取第 1、4 步 `logits["symbols"]`；查询展开不回写在线状态。mask 取 o_q 的公开 visible_mask。单位按协议精确调用 `before_work`，合计 2,254。返回 numpy float32/bool 数组，形状与 `ap.CACHE_ARRAYS` 相同。
- `keep_row_loss(model, cached_row, window, row_keys)`：供 `nn.value_and_grad` 调用。`h = mx.stop_gradient(mx.array(incoming_h[None]))`，observe(o_s)，执行恰好 q−s 条 imagine→observe，再做 4 步 imagine；教师 logits 以 `mx.stop_gradient` 常量参与稳定 log-softmax KL，按 q 可见格平均，再平均两个 horizon。后缀内部不 detach，不读 q 之后的观察。语义必须与 `ap.keep_loss_reference` 相同（逐行 R=1）。
- 教师是独立的 `SharedSymbolPredictor` 实例：从同一 M2d 张量精确加载并核对后 freeze，不传入 `value_and_grad` 或优化器，缓存写完后删除。

### 3. worker 分支（`memory_worker.run_memory`）

- `action_preservation_memory_plan()` 基于 `relabel_memory_plan(0.003)`：protocol 改为 `ap.PROTOCOL`，`training_update` 3 秒，删除 `m2l_paired_cells`/`m2l_relabel_pool`，新增 `teacher_cache` 60 秒、`cache_protocol_checks` 10 秒；`expected_total_model_units` 208,546，`total_reserved_seconds_if_complete` 1,610，`supervised_deadline_seconds` 1,660；嵌入 `ap.action_preservation_plan()`，并用 `ap.verify_frozen_plan` 核对。构建时必须按实际阶段次数（200 次更新、10 次局部检查）把秒数复算为 1,610，不一致就报错。
- 顺序：CPU 闭包（`_prepare_relabel` → `production_windows` → `m2l_reuse_closure`，全部在 `create_experiment` 之前，失配不建 run）→ compatibility → initialization（学生）→ `teacher_cache` → `cache_protocol_checks`（重读 npz，用 `ap.verify_teacher_cache` 对 expected binding 和 q 可见 mask 核对，比较文件大小/SHA）→ before 评测（保留 `before_matches_m2l`）→ 局部检查 → 200 次更新 → after/paired/after_relabel_pool → 用复用的 M2l 逐格结果做 stratified/regression/transfer → `preservation_screen` → checkpoint → verification（加核对 M2m-c 报告与缓存文件前后字节不变）。
- 每次更新 `stage("training_update", updates=1, units=32 + student_units[u])`，然后：
  1. 记忆分支与 M2m-c 相同：换名批、micro4、可见目标加权求和、清单双射核对。
  2. 保持分支：按调度的 16 行逐行 B=1 求梯度，每 4 行 `mx.eval` 一次并 `guard()`；每行梯度物化为 numpy float64。
  3. `ap.combine_branch_gradients(np(memory_sum), target_count, keep_rows)` 生成**实际应用的组合梯度**（CPU 函数就是生产实现，不另写一份 MLX 组合；树键从 `gru.Wx` 等映射为 `ap.GRU_LEAVES` 的名称）；按 `ap.frozen_row_mask` 屏蔽冻结行；`ap.check_applied_front_gradient(raw=组合, applied=屏蔽后)`。
  4. 转为 float32 `mx.array` → `clip_grad_norm(1.0)` → AdamW → `project_gru_front` → `verify_tail_update`（282,128 元素逐位）；断言裁剪后冻结行恰为 0。
  5. 日志增加：memory_loss、keep_loss、每行 keep loss、两分支及前/尾范数（取自已计入预算的梯度，不重跑前向）、student_units、`keep_rows`。
- **首个更新不变量**：第 1 次更新时学生与教师权重相同，且共用每次调用的键，B=1 的同一计算使教师与学生 logits 逐位相同，因此 16 行 keep loss 都恰为 0。E13b 实现为停止条件（期望值精确 0.0），同时记录实际最大值；C06a 先实测确认。保持梯度只记录范数、不要求为 0：log-softmax 反向中 Σp 的 fp32 舍入可能留下极小残差。若实测非零，交回统筹定位，不得自行放宽成容差。这项检查专门暴露键、tick、offset 或窗口没对齐的问题。
- 产物：运行目录 `teacher-cache.npz`（`np.savez`，不压缩）与 `teacher-cache-manifest.json`（`ap.teacher_cache_manifest` 加文件大小/SHA）；均为新文件，不覆盖。report 与 checkpoint metadata 记录缓存身份、M2l 复用证据、`preservation_screen`，`promoted` 恒为 False。
- 现有 `reserve`/`stage`/`guard`、RunStore、AC 电源、内存/swap/磁盘保护与占空比空闲原样复用；最后仍要求实测单位等于预留，且等于 208,546。

### 4. CLI

`train-action-preserved-memory` 的必需参数为 `--dataset --checkpoint --comparison-report --m2l-report --m2l-checkpoint --m2mc-report --experiment-id`，**不接受学习率或其他科学参数**。分派到 memory_worker 的 `--action-preservation-fit --m2mc-report`；该标志与 `--relabel-learning-rate`、`--local-fit` 等手动组合互斥，由 worker 内部固定启用相应分支。监督超时 `min(1710, config.budget.max_wall_seconds)`。沿用 `worker_lock` 和失败清理；旧命令的参数、默认 lr 0.001 和 1,770 秒不变。

## CPU 验收测试

测试进程不得导入 MLX（沿用 `sys.modules` 断言），不创建 run，不写正式产物。

| 编号 | 必测内容 |
| --- | --- |
| T1 | B1：降级通用窗口、换 episode 后刷新摘要、键绑定或 keys 内容不符、缺 public_records，都被 `production_windows` 拒绝；登记 fixture 通过并给出 71deb0f0/5a644900 |
| T2 | B2：records 构造产出 int 键；`np.int64`、字符串键输入被规范化或明确拒绝；伪造的 True 标志不影响结果 |
| T3 | plan：秒数按阶段次数合计 1,610；单位 178,304+2,254+27,988=208,546；学生逐更新表 200 项、137–144、合计 27,988；工作/监督截止 1,660/1,710；嵌入计划 SHA cb1437ef… |
| T4 | 旧入口兼容：变更前记录 `memory_plan`/`micro`/`diverse`/`relabel_memory_plan(0.001/0.003)` 的规范摘要并断言不变；旧子命令参数与超时不变；新子命令无学习率参数；互斥组合被拒绝 |
| T5 | `ap.frozen_row_mask` 与 `tail_update` 的尾部行定义对四个 GRU 叶子逐行互补一致 |
| T6 | `preservation_screen` 的整数边界：3892/4096 过、3891 不过；115/127；1946/2048、126/140；377、359；NLL 增幅恰为 0.05/0.15 时通过，略大则不过；重建 544/544 |
| T7 | `expected_cache_binding` 由可信输入构造并通过 `ap.validate_cache_binding`；把 windows 或 key 字段换成通用窗口的值后，`ap.verify_teacher_cache` 拒绝 |
| T8 | 静态检查：closure 模块不导入 mlx；MLX 模块中保持路径只通过 `_key` 造键，不出现 `random.seed`、`random.split`，也不出现以 `fold` 开头的调用 |
| P1 | 单列本机只读探针（不是 skip 的测试）：用真实 dataset、16 个 train episode、M2m-c 报告、M2d/M2l checkpoint 与 RunStore 完成 `production_windows` 和 `m2l_reuse_closure`，记录所有输入文件前后 SHA，并确认未打开 private |

E14a 的 109 项和旧测试需继续通过；不跑含 MLX 的全量测试。

## 交付与后续

报告列出实际命令、源码/测试 SHA、XML/log、P1 输出，以及“已实现但未验证”的 MLX 项。E13b 交付后状态为 reported；随后 E14b 做独立静态/CPU 审查，C06a 再按实际调用图登记有限 MLX 验证。建议 C06a 至少覆盖：`mx.random.key(int)` 的 shape/dtype/值；完整教师缓存生产（探针缓存不得冒充生产缓存）；一次完整更新中的首更新零不变量、应用 front 梯度、AdamW 投影与逐位冻结；峰值内存以及每次更新耗时与 3 秒窗口的对比。

未验证（E13b 完成后依然如此）：MLX 键/噪声/KL/梯度与 CPU 参考等价、实际耗时与峰值、训练效果和任何能力门。代码合入只代表入口可用，不代表可以训练；训练仍须经 C06 登记，才能交给 E15。

## 交付后统筹决定（2026-10-12 22:20，Claude）

依据 [E13b 报告](artifacts/reports/E13b-grokbot-newbot-20261012T215628+0300.md)。Claude 核对改后源码/测试 SHA 与报告一致，E13a 三个文件未改；重跑新增 40＋原 109 项与旧入口 379 项，全过，测试进程未加载 MLX，控制库字节未被测试改变。E13b 状态记为 reviewed，**未 accepted**：需先完成下面的 R1，再交 E14b。

### 1. P1 与控制库字节变化

- 原因已定位：`RunStore.get_run`/`get_experiment` 在 `BEGIN IMMEDIATE` 事务中调用 `_effective_now`，会 upsert `metadata.clock_high_water`（防时钟回拨的单调高水位）。经 RunStore 的任何查询都是一次真实的逻辑写入，不只是 WAL 回写。Claude 以 SQLite `immutable=1` 只读核对：高水位为 21:53:08，正是 P1 运行时刻；runs/experiments/run_transitions 的最新记录仍是 09:02 的 M2m-c，没有新增。
- **决定：接受 P1 的闭包结论，但改正措辞。** 写成“run/experiment/状态转换/预算记录未改，RunStore 查询推进了时钟高水位”，不能称“只读”或“逻辑只读”。RunStore 是共享安全机制，不改。生产 worker 仍在 CLI 锁内经 RunStore 核对；独立审查若需要零写入，在没有运行进行时用 `immutable=1` 快照读取，不经 RunStore。
- R1 后重跑 P1 时，前后对 runs、experiments、run_transitions、daily_budget 以及 metadata 中除 `clock_high_water` 外的键分别做逻辑摘要（immutable 读取），并单列高水位的变化。

### 2. `m2l_reuse_closure` 的两处偏差

- **接受 `episodes=`**：它与 `_prepare_relabel` 中已按 dataset manifest 和 query manifest 校验过的是同一对象。R1 在函数内部增加自查：`query_frames(episodes)` 的 `query_manifest_sha256` 必须等于 M2l 报告 `paired.query_manifest_sha256`，不依赖调用顺序。
- **不接受只复算 methods。** 两支各自的边际统计查不出同一 query 内 history/zero 的重新配对。例如两格标签相同，一格只有 history 正确，另一格只有 zero 正确；交换这两格的 history argmax/NLL 后，两支的正确数和 NLL 均值都不变，但 both/neither/history_only/zero_only 全变。规格要求对照 paired 统计，M2MD 的闭包下限也是“匹配原统计”。R1 逐 query、逐世界、逐组复算 `paired` 的全部字段：count、四类正确数、prediction_disagreements 及其 `changed_` 版本，以及 `history_minus_zero_*` 四个差值。整数要求相等，浮点沿用同一 `_close`；同时加入上述交换反例测试。纯 CPU，无模型调用。

### 3. 首更新不变量与 C06a 探针入口

生产入口的精确 0.0 停止条件不变。现有入口只能跑完整 200 次更新（那就是 E15 训练），无法表达有界的数值/资源验证。按 M2MD“机制不能表达就先修入口”，R1 同时加入独立探针入口；C06a 只能使用它。

| 项 | 固定值 |
| --- | --- |
| 入口 | 子命令 `probe-action-preserved-memory`，worker `--action-preservation-probe`，与训练分支及其他标志互斥；输入与训练入口相同的 6 个路径＋experiment ID；无科学参数 |
| 阶段与单位 | CPU 闭包 → compatibility 15 秒 → initialization 15 → `teacher_cache` 60 秒/2,254 → `cache_protocol_checks` 10 → `teacher_repeat` 60 秒/2,254（在内存中第二次完整生产教师缓存，三个数组逐位比较）→ 3 次完整更新，每次 3 秒窗口、单位 32＋139/138/144 → verification 10 |
| 合计 | **5,025 单位、179 秒预付**；工作/监督截止 **229/279 秒**（沿用 +50/+50）；role model，预留 3 次优化更新 |
| 不做 | before/after 评测、局部检查、配对与换名池评测；不保存模型或优化器 checkpoint，只记录参数 SHA；探针权重不得作为任何起点 |
| 缓存 | 文件名 `probe-teacher-cache.npz`/`probe-teacher-cache-manifest.json`；binding 的 run_id 为探针 run，因此生产核对必然拒绝，不能冒充生产缓存 |
| 必须记录 | `mx.random.key` 前 3 个调用的 shape/dtype/值；更新 0 逐行 keep loss 和学生/教师 logits 最大绝对差；同 16 行 KL(缓存‖重复)；每次更新 front/尾部范数、裁剪后冻结行恰为 0、AdamW 投影后 282,128 元素逐位不变、优化器树只含学生 GRU 叶子；各阶段与每次更新的实际秒数；MLX 峰值内存 |
| 停止规则 | 首更新不变量在探针中只记录、不停止，以便测完后续两次；资源、阶段窗口、front、逐位冻结等其他保护照常停止 |

结果判读在看结果前固定：

- (a) 重复教师逐位一致，且 16 行 loss 全为 0.0 → 生产停止条件保持精确 0.0。
- (b) 重复教师逐位一致，但有行非零 → 实现错位（键、tick、offset、窗口或状态），交回修复后重跑探针，不引入容差。
- (c) 重复教师本身不逐位一致 → MLX 非确定性，精确 0 不可用。替换阈值取探针中同 16 行 KL(缓存‖重复) 的最大值，由统筹在 C06 前登记；执行者不得自定。
- 若第 1 次更新（含图编译）超出 3 秒窗口，探针按原守卫失败并留档。这意味着生产计时需要统筹重新登记，不能在运行中放宽。

探针仍须经 E14b 审查，再由 C06a 登记具体 experiment ID 和中央预留后才能运行；本节不授权运行。

### R1 文件范围

只改 `action_preservation_closure.py`、`memory_worker.py`、`cli.py` 和两个 E13b 测试文件（可新建一个探针入口测试文件）。CPU 测试需覆盖：paired 字段全复算与交换反例、query manifest 自查、探针计划合计 5,025/179/229/279、互斥与参数、不保存 checkpoint、探针缓存被生产 expected binding 拒绝。原 40/109/379 项继续通过，重跑 P1 并按第 1 点报告控制库。E13a 文件、旧协议与 E13b 原报告不改；R1 另交报告。

## 附录：C06a 修订（2026-10-13，统筹决定）

C06a 唯一登记探针（run `6ac8b328-e4a5-433e-8ba0-da6c0945ddac`，experiment `c06a-action-preserved-probe-20261013`）实测：教师缓存重复逐位一致（3 数组 max diff 0.0、KL 0.0），但首更新 16 行 keep loss ∈ [−7.74e-8, +1.21e-7]，**不是精确 0.0**。判读为预登记的 **(b)** 分支。证据（学生/教师 logits 仅差 7e-7–1.4e-6 ≈ 1 ULP、KL 正负各半、更新 2/3 升至 4.4e-5/2.5e-3）指向 float32 舍入，而非键/tick/offset/窗口/状态错位：教师缓存与学生会话后缀是两份独立编译的 MLX 图，逐位相等在 GPU 上不可保证。

**修订（用户 2026-10-13 批准）：** 生产停止条件由「16 行 keep loss 精确 0.0」改为登记绝对界 **`FIRST_UPDATE_KEEP_LOSS_MAX = 1e-5`**（`action_preservation_closure.check_first_update_keep_loss`）：

- 非有限值一律停止；`max|row loss| ≤ 1e-5` 通过，超出即停止并留档；
- 记录 `max_abs` / `max` / `all_exact_zero` / `within_registered_bound`；
- **能力门、科学参数、λ/温度、窗口、seed、数据分区、预算与冻结保护全部不变**；
- 「教师重复逐位一致」仍是探针中的硬条件；探针继续保持「只记录、不停止」。

依据：[C06a 执行报告](artifacts/reports/C06a-probe-execution-20261013.md)、[预登记](artifacts/reports/C06a-probe-registration-20261013.md)。
