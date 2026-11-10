# S4 第一阶段实现：非作者复核 第二轮

- 复核者：`claude-s4impl-rev2-1110`（非作者）
- 被审提交：`a767ac7`。隔离副本用 `git archive a767ac7` 取出。
- 工作树里有作者未提交的 `tests/v9/experiments/test_s4p1_runner_native.py` 改动，不在本轮被审范围。第 8 项「作者自己的变异」说明它补的是什么。
- 日期：2026-11-10。
- 执行范围：
  - 只在隔离副本里执行，没有改仓库里的源码、测试、设计稿或研究日志，没有提交。
  - 没有跑 `run_s4p1.py --stage probe|final`。
  - 没有碰 `artifacts/` 下的实盘目录，只在共享锁 `artifacts/locks/m0-worker.lock` 上取 flock（不写内容）。
  - 运行器测试与触发用例都在测试自建的假根目录里，用替身分区、MLX CPU 设备。
- 证据都在 `evidence/`：`harness/` 是我写的脚本，`out/` 是它们的输出。

## 总判定：建议通过（有条件）

没有发现必修项，也没有发现「缺数据默认通过」的路径。上一轮的必修和应修 2、3、4 已经修好，我在副本里构造了触发用例逐条验证过；应修 1 只修好了一半。

条件：

1. **探针之前要先改 `run_s4p1.py` 的学生视图判据**（下文应修 1），并经非作者复核。
   - 原因：运行器在冻结清单里，探针要用待冻结的代码跑。探针之后再改运行器，就得重跑探针。
2. **其余应修都只涉及测试**（应修 2–4），可以和探针并行，但必须在 `make_prereg.py` 冻结之前补齐。
   - 这些测试缺口对应的代码我逐行读过，是对的；缺的是能抓住回退的测试。

| 级别 | 编号 | 一句话 |
|---|---|---|
| 应修 | 1 | 未来帧变异的 `suffix_changed` 只因检测数少一个就恒为真：一个不读传入位置、只读长度的跟踪器也能通过学生视图门 |
| 应修 | 2 | 代码约束的两个静态测试抓不住不用被禁运算的解析碰撞规则：用 `mx.clip` 写的硬接触交换连整份 learned_mlx 测试都能通过 |
| 应修 | 3 | 监督与训练代码里 14 处分支没有测试能抓住回退：作者自己的 r2-runner 存活 4 个，我补的 learned_mlx 变异 4 个、运行器与重放变异 6 个；代码本身我逐行读过，是对的 |
| 应修 | 4 | `verify_labels.py` 的世界列表比对没有测试（变异存活）；它是唯一能发现「worlds.jsonl 少了一个世界」的检查 |
| 建议 | 5–10 | 见各项 |

## 1. 上一轮必修 1 与应修 1–4 是否真修了

| 上一轮 | 判定 | 触发用例与结果 |
|---|---|---|
| 必修 1-a：写标记之前不查剩余墙钟 | **通过** | 见下文 |
| 必修 1-b：训练单格上限没有强制 | **通过**（测试有缺口，见应修 3） | 见下文 |
| 必修 1-c：逐世界结果最后才落盘 | **通过** | 见下文 |
| 应修 1：学生视图检查近似恒真 | **只修了一半，转为本轮应修 1** | 见下文 |
| 应修 2：训练设备 | **通过** | 设计稿「实现补记」写明 GPU 训练、CPU 评测、校验和重放；预登记 `training.device` 与 `budget.device` 也记了（`make_prereg.py` 第 70、79 行） |
| 应修 3：批的构成 | **通过** | 实现补记逐项写了 `COLL_SHARE`、`NEAR_SHARE`、权重、裁剪、方向软化、非有限即停、单格时限、扰动细节、1/8 数据格、L-int-σ，并与 `learned_mlx.py` 的常数一致；预登记也把这些常数写进去了（第 63–70 行） |
| 应修 4：bootstrap 查不出分母变号 | **通过** | 见下文 |

**必修 1-a，剩余墙钟。**
- `run_s4p1.py` 第 303–309 行：写标记之前要求 `deadline.left() >= eval_reserve_s`。
- 测试 `test_final_with_too_little_time_left_does_not_spend_the_read` 把预留设成 1e9，运行在标记之前被拒，标记和 `worlds.partial.jsonl` 都不存在。我在副本里重跑这条测试，通过。
- 我另外把顺序换成「先写标记再查预留」（变异 `ru_marker_before_reserve`），结果见第 8 项。

**必修 1-b，单格上限。**
- `L.train` 新增 `time_limit`（`learned_mlx.py` 第 352–353 行），每步之后检查，超时抛 `TimeoutError`。
- 运行器给 18 格都传了 600 秒（第 160、162–163 行），并把超时转成 `GuardError`。
- 测试 `test_a_cell_over_its_limit_stops`（learned_mlx）与 `test_a_training_cell_over_its_limit_stops_the_run`（运行器）都通过。
- 缺口：L-int-σ 那一格不传 `time_limit` 的变异（作者的 `ru_cell_limit_not_passed`）在 a767ac7 上存活。作者工作树里未提交的 `TRAIN_SPY` 测试就是补这个的。

**必修 1-c，逐世界落盘。** 触发用例是 `evidence/harness/kill_eval.py`，结果写在 `evidence/out/mlx/kill_eval.json`：
- 在假根目录里把 smoke 改成 10 个主世界加 2 个外推世界、1 个 worker；
- 等 `worlds.partial.jsonl` 写到 3 行就对整个进程组发 SIGKILL；
- 再用同一配置完整跑一遍，比较被杀那次已落盘的记录是否与完整运行的对应世界逐位相同。
- 结果见第 8 项后的「MLX 触发用例」。

**应修 4，bootstrap 分母变号。** 证据是 `evidence/out/item1_cpu.json`。
- 合成记录取 E-P 准确率 0.43、E-B 0.40，地板门照样通过，但 16% 的重采样里 p − b ≤ 0。
- 这时 `C_of` 给出点估计 0.882，`ci_low` 与 `ci_high` 都是 `None`，H1 判不过。
- 直接对 `metrics.bootstrap` 构造一个分母为 0 的重采样，结果整体无值、无区间。
- 规则在 `metrics.py` 第 88、107 行。

**应修 1，学生视图（本轮应修 1）。**

修好的一半：
- 跟踪器改为经 `A.student_detections` 读（`analysis.py` 第 121–126、134 行）。我给 `W.student_view` 加一个 `truth_ids` 字段，它报错拒绝。
- 截点前编号不变（`prefix_equal`）这一半是有效的。我写了一个会偷看下一步检测的跟踪器，它在 `prefix_equal` 上失败，门判不过（`evidence/out/item1_cpu.json` 的 `lookahead_tracker`）。

没修好的一半：
- `suffix_changed`（`run_s4p1.py` 第 207 行）比较的是两组长度不同的数组。变异把截点之后每步的检测去掉一个，`a[t]` 比 `b[t]` 长 1，`np.array_equal` 必为假。所以只要 `consumed` 成立，`suffix_changed` 就恒为真。
- 触发（`evidence/harness/item1_student2.py`，输出 `evidence/out/student_length_only.json`）：
  - 桩跟踪器按世界缓存第一次调用（未变异）的检测，之后只读传入列表的长度，从不读传入的位置；
  - 把它代入从 `run_s4p1.py` 原样抽出的 `student_check`，四行全部 `prefix_equal`、`consumed`、`suffix_changed` 为真，门判**通过**。
- 修法（已验证，`evidence/harness/item1_student3.py`、`evidence/out/student_aligned_rule.json`）：
  - 改为对齐前缀比较：`any(not np.array_equal(x[: len(y)], y) for x, y in zip(a[STUDENT_CUT + 1:], b[STUDENT_CUT + 1:]))`。
  - 新判据下，诚实的 E-P 跟踪器为真；「从不关联、编号只是新建计数」的跟踪器（作者说 3 步训练的模型就是这样）也为真；只读长度的桩为假。
  - 作者改成「丢一个再平移」的理由（只平移时小模型的编号不变）在新判据下仍然成立，不需要回到只平移。
- 现有的运行器测试 `test_student_check_needs_the_mutation_to_change_something` 要保留，再加一条：只读长度的桩必须让门判不过。

## 2. 代码约束（设计 §3：不得写解析的碰撞响应）

**逐行读：通过。**
- `node_features`（`learned_mlx.py`）只给自身位置、速度、四面墙的间隙、三根柱子的相对位置与间隙和半径，没有反射。
- `pair_geometry` 只算 dp、dv、距离和 `dist < MSG_RADIUS` 的消息截断掩码。
- `Dynamics.messages`：
  - 消息是 MLP 的输出；
  - `dist - 2 * RADIUS` 只作为特征；
  - L-int-c 的方向向量是软化的单位向量，消息再沿它转回；
  - 接触 logits 只返回，不进入更新。
- `Dynamics.__call__`：`v_next = v + o[..., 2:4]`，`p_next = p + v * DT + o[..., 0:2] * P_SCALE`，增量全部来自网络输出。L-int-σ 的方向差头读的是 `stop_gradient(z)`。

**两个测试能否抓住违例：抓不住 → 应修 2。**

我在副本里写了两个违例，都加在 `v_next = v + o[..., 2:4]` 之后（变异定义在 `evidence/harness/mut_mlx.py` 的 `V1`、`V2`）：
- `cc_smooth_elastic_exchange`：用 `mx.sigmoid((2R − dist) × 200)` 作软接触指示，加上沿盘心连线交换法向相对速度的解析冲量；
- `cc_hard_contact_via_clip`：用 `mx.clip((2R − dist) × 1e6, 0, 1)` 作硬接触指示、`mx.clip(−(dv·n) × 1e6, 0, 1)` 作相向指示，同样交换法向速度。这就是一条硬编码的弹性碰撞规则。

结果（`evidence/out/mlx/mut_mlx_cc.json`、`mut_mlx_cc_full.json`）：

| 违例 | `test_model_code_does_not_use_the_world_physics` + `test_forward_path_has_no_contact_rule` | 整份 `test_s4_learned_mlx.py`（31 项） |
|---|---|---|
| 平滑解析交换 | 存活（2 passed） | 被 `test_independent_arm_never_sees_other_disks` 抓到，只因为违例也作用在 L-ind 上 |
| `mx.clip` 硬接触 | 存活（2 passed） | **存活（31 passed）** |

另外跑了只对交互臂生效（`if self.interact:`，不引入比较节点）的版本（`evidence/harness/mut_mlx2.py`，输出 `mut_mlx_ccg_*.json`）：

| 违例（只作用于交互臂） | 两个专门测试 | 整份测试 |
|---|---|---|
| 平滑解析交换 | 存活 | 被 `test_recorded_divergence_case_has_a_finite_gradient` 抓到，只因为 `dp / dist` 在重合盘处梯度非有限 |
| `mx.clip` 硬接触 | 存活 | **存活（31 passed）** |

原因：
- 第二个测试只禁 `mx.where/abs/sign/maximum/minimum` 和 `np.*`，并要求比较节点恰好是三条；
- `mx.clip`、`mx.sigmoid`、`nn.relu`，以及不带比较的 `if self.interact:` 都不在禁列里。

修法：加一条行为测试，比静态禁列可靠。
- 把 `out` 层（以及 L-int-c 的 `msg_vec`）的权重和偏置置零；
- 输入里放重叠且相向的盘对、贴墙和贴柱的盘；
- 要求所有臂都满足 `v_next == v` 且 `p_next == p + v * DT`，逐位相同。
- 任何加在网络输出之外的解析项都会让它失败。静态测试可以保留，作为第一道绊线。

## 3. 训练

**通过。** 与实现补记逐项一致：

| 项 | 代码 |
|---|---|
| 样本池与扰动 | `make_pool` 只用 `train_eps`，标签由传入的 `W.physics` 算；`perturb` 先裁剪进场地，丢盘后至少保留两个盘（第 179–182 行） |
| 批的构成 | `batches`：桶按样本数加权抽，每批 `round(256 × 0.5)` 个取自第 1 步有盘—盘接触的样本，其余从同一桶均匀抽；`NEAR_SHARE = 0` |
| 损失 | 一步、五步、十步权重 10、1、1，接触头交叉熵 0.1 |
| 裁剪 | 全局范数 10 |
| 学习率 | 恒定 1e-3（`LR_END is None`） |
| 方向软化 | `EPS_DIR = 0.01` |
| 非有限即停 | 第 348–349 行：在 `opt.update` 之前检查损失和梯度范数 |
| 单格时限 | 第 352–353 行 |
| L-int-σ | `load_weights(strict=False)` 载入同种子 L-int → `freeze()` → 只 `unfreeze` `var1`、`var2`；损失是 `nll_loss`；批不做过采样 |
| 1/8 数据格 | `train_eps[: 400 // 8]`，即前 50 个世界；样本数为 `pool // 8`，步数相同 |

**训练只读训练池。**
- `train_all` 的三个池都由 `train_eps` 生成，`train_eps` 来自 `ns["train"]`；
- `fit_refs` 只用 `train_eps[:100]`；
- 评测分区在训练与标记之后才生成（第 312 行）。
- 没有读到 probe 或 final 数据进入训练的路径。

测试缺口见应修 3：裁剪的结果没被用上、两个种子源被固定、`mean_model.arm` 检查被删、「至少保留两个盘」改成一个，这些变异都存活。

## 4. 各门与缺数据路径

**通过。**
- `analysis.THRESHOLDS` 与设计 §5 一致：
  - HD：D ≥ 0.8，下界 > 0.7；
  - HF：比值 ≤ 0.10，上界 ≤ 0.15；
  - HD-x：D ≥ 0.7，下界 > 0.6，比值点估计 ≤ 0.15；
  - H1：C ≥ 0.5，下界 > 0.25；
  - H2：差 ≥ 0.05，下界 > 0；
  - H3：C ≥ 0.4，下界 > 0.2；
  - 负对照：L-ind 的 D 下界 < 0.5 且 C 下界 < 0.25，不满足则作废 HD、H1；
  - 合法性任何一项不过，全部门作废。
- 数据分区：HD、HF、H1、H2、负对照用 `main`，HD-x、H3 用 `extrap`（`analysis.py` 第 241–245 行）。
- Bonferroni：m = 7，各门的区间都按 m = 7 算。
- `ok()` 要求值不为 `None`。

缺数据路径用合成记录逐个试过（`evidence/harness/gates_probe.py`，输出 `evidence/out/gates_probe.json`），全部按不过处理或直接报错：

| 情形 | 结果 |
|---|---|
| 外推记录为空 | HD-x、H3 不过，其余照常 |
| 主评测缺 L-ind 的 reid | `KeyError`，运行中止，不出结果 |
| L-ind 的 dyn 为 NaN | 负对照不过 → HD、H1 作废 |
| E-P 与 E-B 准确率相同 | 地板门不过（严格小于）→ 全部作废 |
| 分母在部分重采样里变号 | 无区间 → H1 不过 |
| labels / determinism 为假 | 全部作废 |
| 少 20% 或 50% 的主世界（`n_main` 取登记值） | samples 门不过 → 全部作废 |
| 学习臂没有擦边步 | HF 无定义 → 不过 |
| 没有任何事件 | floor、samples 不过 |
| E-B 碰撞误差为 0 | D 无定义 → HD 不过、负对照不过 |
| 一个世界的误差为 inf | D 非有限 → HD 不过 |
| L-ind 和 L-int 一样好 | 负对照不过 → HD、H1 作废 |

`legality` 在 E-B 或 E-P 准确率为 `None` 时比较会抛 `TypeError`。这是失败即停，不是默认通过（建议 5 只是让它报得清楚些）。

## 5. 运行器守卫顺序

**通过。** 顺序与任务要求一致（`run_s4p1.py` 第 266–312 行）：
1. 拿锁；
2. `startup_checks`：final 才查 `-I`、新鲜 pycache、冻结清单与已载入模块、第三方版本、git 干净；
3. 分区检查；
4. 请求检查：final 的步数和批只取自预登记，并且要有审批行；
5. 运行目录已存在就拒绝，final 标记已存在就拒绝；
6. 认领报告，建目录；
7. 训练 18 格；
8. 拟合校准参照；
9. `deadline.check()`；
10. 查评测预留；
11. 写 final 只读一次标记；
12. 生成评测分区。

其余要求：
- 登记分区只在标记之后、只在主进程生成。`allow_registered` 全文只有一处（第 312 行），`world.generate_episode` 对登记分区不带它会拒绝。
- worker（`worker_mlx.py`）不调用 `generate_episode`，只用任务里传过去的 episode。
- 逐世界追加写 `worlds.partial.jsonl`（`"x"` 模式打开、每条 flush）。
- 记录 `files_sha256`：worlds、partial、labels、replay 和每个权重文件。
- 跑完再查一遍冻结清单与已载入模块，不符就把 `valid` 和全部门置为不过。
- 门从重新读回的 `worlds.jsonl` 计算（第 344–349 行）。

测试缺口（应修 3）：在 a767ac7 上，关掉最后那次清单复查、或忽略 replay 的结果，都没有测试能抓到（作者的 `ru_late_check_off`、`ru_replay_ignored` 存活）。我补的运行器变异见第 8 项。

## 6. 两个校验脚本

**`verify_labels.py`：通过，独立。**
- 只用标准库，测试 `test_verifier_is_independent` 检查它不导入 `ainerzero` 和 NumPy。
- 它从接触日志独立重算重新出现事件（b − a ≥ 2，两端可见且被检测到）、「有碰撞」（a ≤ s < b）和碰撞盘步数，并核对 reid 长度。
- 设计 §5 的「标签」门要求的正是这些。
- 作者的测试覆盖 7 种篡改，我的变异 `vl_gap_one`、`vl_no_dyn_check`、`vl_no_reid_len_check`、`vl_passed_always` 都被杀掉。
- 缺口：世界列表比对（第 41 行）去掉后存活（`vl_world_list_unchecked`）→ 应修 4。第 44 行用 `zip`，如果 `worlds.jsonl` 比 `labels.jsonl` 少一个世界，其余检查都不会发现，只剩第 41 行。
  - 修法：加一条「删掉最后一条记录」的篡改测试。

**`verify_replay.py`：确定性检查，不是代码独立的。**
- 它导入 `analysis`、`filter`、`learned_mlx`，在另一个进程里用 CPU 从落盘权重重放 5 个世界（主 3、外推 2）、全部 18 个学习格的基础变体，比对编号摘要。
- 这符合设计对「确定性」门的定义。
- 篡改试验（`kill_eval.py` 后半段，结果见「MLX 触发用例」）：改一个摘要、互换两个种子的权重、只改 reid 的对错标记。
- 作者的 `vr_skip_mismatch` 在 a767ac7 上存活，说明没有测试证明它能发现不一致 → 并入应修 3。

**两者合起来的盲区（建议 6）：**
- reid 的对错标记（直接决定 C、H1–H3）没有被任何一个校验脚本从编号重算：标签校验只看长度，重放只看摘要。
- `worlds.jsonl` 不存原始编号，事后也无法不重跑就复算。
- 运行器代码冻结、逐世界的 SHA 也落了盘，所以这不是可利用的漏洞，只是独立复算时要重跑跟踪。
- 重放只覆盖学习格。E-B、E-P 是 C 的分母，它们的格不在重放范围内；改它们的摘要不会被发现（「MLX 触发用例」）。
- 建议重放脚本在它重放的 5 个世界上顺带从重放的编号重算 reid，并与记录比对，同时把 E-B、E-P 的基础格也加进重放。

## 7. `make_prereg.py`

**通过。**

冻结清单：
- `GD.build_manifest(REPO, [RUNNER], src_root=src, extra=[design, *VERIFY])`，覆盖运行器在 `src/` 下的传递闭包（含 `s3/run_guard.py`、`worker_mlx.py`）、两个校验脚本和设计稿。
- 运行器测试 `test_final_path_after_a_frozen_probe` 检查了这四类文件都在清单里。
- 运行器自己的 `code_manifest()` 与预登记里的 `code_sha` 用同一组入口，探针的 `code_manifest_sha256` 能对上。

探针报告的条件：`stage == "probe"`、评测分区是 `s4p1-probe`、`result.valid` 为真、`code_manifest_sha256` 等于待冻结代码、`code_dirty == []`。

评测预留：
- `ceil(1.5 × 4 × (eval_seconds + check_seconds))`，4 = (200 + 100) / (50 + 25)；
- `1.2 × 训练耗时 + 预留 > 4 小时` 就拒绝冻结。

估得不准的后果是安全的：
- 预留不够，会在标记之前被拒，读取不会被花掉；
- 只有评测本身比探针的 4 × 1.5 倍还慢，才会在标记之后超时。

建议 7：
- `eval_seconds` 只包住 `evaluate_parallel`，`check_seconds` 只包住三项检查。
- 评测世界的生成（我实测 300 个世界约 36 秒）、写文件、`A.evaluate` 与描述统计都不在计时里，只靠 1.5 倍余量兜着。
- 另外 `fit_refs` 不在 `train_s` 里。
- 建议计时改为从标记之后一直到报告写完。

## 8. 变异自测

### 作者声称等价的两个变异

证据：`evidence/harness/equiv.py`、`evidence/out/equiv.json`。

- **`as_pad_small`：等价，判定成立。**
  - 矩形代价矩阵只在一个维度上补行或补列，补上的整行（整列）是常数。常数加在整行（整列）上，每个完整分配的总代价都平移同一个量，所以最优的真实配对不变。
  - 实测 20000 个随机连续矩阵（1–8 × 1–8，三种量级）：两版选出的配对全部相同；其中 3000 个与穷举最优一致。
  - 只有在平局时选出的配对可能不同（整数矩阵 5000 个里有 516 个不同），但跟踪里的距离是连续值，不会出现平局。
- **`fi_gate_strict`：在可达输入上等价，判定基本成立，建议补一条边界测试（建议 8）。**
  - 构造一个距离恰好等于门限 1.05 的检测：原版关联上了，变异版没有。所以这个变异可以被杀掉。
  - 但在 20 个世界、11341 次「配对—门限」比较里，没有一次恰好相等，也没有一次差在 1e-9 以内。

### 作者自己的变异

| 轮次 | 杀掉 / 总数 | 存活 |
|---|---|---|
| r1-cpu | 36 / 42 | 两个等价变异，另 4 个在 r1-cpu-b 补测试后杀掉 |
| r1-lm | 28 / 34 | 6 个在 r1-lm-b 补测试后杀掉 |
| r1-lm-c、r2-cpu、r2-lm | 全部杀掉 | |
| r2-runner | 7 / 11 | `ru_cell_limit_not_passed`、`ru_replay_ignored`、`ru_late_check_off`、`vr_skip_mismatch` |

r2-runner 的存活在 a767ac7 上成立。作者工作树里未提交的测试改动（`TRAIN_SPY`、`test_failing_independent_check_invalidates` 加 determinism 参数、`test_every_training_cell_gets_the_cell_limit`）对应前两个。后两个还没有对应的测试。

### 我补的变异

一共 48 个，分四组（纯 CPU 20、learned_mlx 10、运行器与重放 14、代码约束 4）。都在隔离副本里跑：
- 复制 `src/`、`tests/`、`reports/V9-S4-PHASE1/`（不含 mutants）、`pyproject.toml`；
- `PYTHONPATH` 指向副本，并确认副本导入的是它自己；
- 每个变异的改动恰好出现一次、改完能过语法检查。

**纯 CPU，20 个，杀掉 19 个**（`evidence/harness/mut_cpu.py`、`evidence/out/mut_cpu.json`；跑默认入口的 4 个 CPU 测试文件，未变异时 72 passed）：

| 变异 | 结果 | 抓到它的测试 |
|---|---|---|
| `an_neg_C_ignored`：负对照不看 C | 杀掉 | `test_negative_control_voids_HD_and_H1` |
| `an_neg_voids_HD_only`：负对照只作废 HD | 杀掉 | 同上 |
| `an_neg_uses_extrap`：负对照用外推数据 | 杀掉 | 同上 |
| `an_samples_dyn_ignored`：samples 门不看碰撞盘步 | 杀掉 | `test_legality_voids_everything` |
| `an_samples_no_upper`：samples 门只查下限 | 杀掉 | 同上 |
| `an_floor_ecv_ignored`：地板门不看 E-CV | 杀掉 | 同上 |
| `an_student_ignored`：学生视图恒过 | 杀掉 | 同上 |
| `an_determinism_ignored`：确定性恒过 | 杀掉 | 同上 |
| `an_H2_vs_EB`：H2 和 E-B 比 | 杀掉 | `test_each_gate_can_fail` |
| `an_HF_uses_extrap`：HF 用外推数据 | 杀掉 | 同上 |
| `an_samples_all_events`：samples 门数全部事件 | 杀掉 | `test_gates_pass_on_a_good_synthetic_result` |
| `an_extrap_offset_zero`：外推世界编号从 0 开始 | 杀掉 | `test_partitions` |
| `an_train_disks_fixed`：训练盘数固定为 6 | 杀掉 | 同上 |
| `an_seed_sum_not_mean`：三种子求和而非平均 | 杀掉 | `test_seed_average_per_event` |
| `me_dyn_skip_graze_only`：只有擦边步的步被跳过 | 杀掉 | `test_dynamics_errors_definitions` |
| `vl_no_dyn_check`：标签校验不比碰撞盘步 | 杀掉 | `test_tampering_is_caught[n_coll]` |
| `vl_no_reid_len_check`：不比 reid 长度 | 杀掉 | `test_tampering_is_caught[short_reid]` |
| `vl_gap_one`：b − a ≥ 1 | 杀掉 | `test_honest_records_pass` |
| `vl_passed_always`：校验恒过 | 杀掉 | `test_tampering_is_caught[flip_collision]` |
| `vl_world_list_unchecked`：不比世界列表 | **存活** | → 应修 4 |

**learned_mlx，10 个，杀掉 4 个**（`evidence/out/mlx/mut_mlx_lm.json`；`--native-mlx` 跑 `test_s4_learned_mlx.py`，未变异时 31 passed）：

| 变异 | 结果 | 抓到它的测试 |
|---|---|---|
| `lm_sigma_mean_not_loaded`：L-int-σ 不载入均值 | 杀掉 | `test_sigma_arm_keeps_the_frozen_mean` |
| `lm_sigma_var1_frozen`：方差头第一层被冻结 | 杀掉 | 同上 |
| `lm_bucket_unweighted`：桶不按样本数加权 | 杀掉 | `test_near_miss_sampling` |
| `lm_contact_share_halved`：碰撞份额减半 | 杀掉 | `test_collision_oversampling` |
| `lm_clip_result_unused`：算了裁剪但用未裁剪的梯度更新 | **存活** | → 应修 3 |
| `lm_batch_rng_seed_fixed`：抽批的随机数种子固定为 0 | **存活** | → 应修 3 |
| `lm_init_seed_fixed`：初始化种子固定为 0 | **存活** | → 应修 3 |
| `lm_mean_arm_unchecked`：L-int-σ 接受非 L-int 的均值 | **存活** | → 应修 3 |
| `lm_keep_one_disk`：丢盘后只保留一个 | **存活** | → 建议 9 |
| `lm_time_limit_doubled`：时限放宽一倍 | **存活** | → 建议 9 |

关于最后两个：测试用 `time_limit=0.0`，放宽一倍照样超时。「至少两个盘」是实现补记声明的细节，但 4 盘时触发概率约 0.4%，影响小，所以只列为建议。

**运行器与重放校验，14 个**：跑 `test_s4_verify_labels.py` 与 `test_s4p1_runner_native.py`，`--native-mlx`，未变异时 30 passed（运行器 21、标签校验 9）。结果见下表（`evidence/out/mlx/mut_mlx_ru.json`）。

杀掉 6 个，存活 8 个：

| 变异 | 结果 | 抓到它的测试，或存活的含义 |
|---|---|---|
| `ru_generate_before_marker`：标记之前先生成评测分区 | 杀掉 | `test_registered_worlds_are_generated_only_after_the_marker` |
| `ru_marker_before_reserve`：先写标记再查预留 | 杀掉 | `test_final_with_too_little_time_left_does_not_spend_the_read` |
| `ru_student_ok_true`：学生视图结果不进合法性 | 杀掉 | `test_student_check_needs_the_mutation_to_change_something` |
| `ru_final_accepts_cli_steps`：final 接受命令行的步数 | 杀掉 | `test_final_path_after_a_frozen_probe` |
| `ru_fresh_pycache_unchecked`：不查新鲜 pycache | 杀掉 | 同上 |
| `ru_git_dirty_unchecked`：不查 git 干净 | 杀掉 | 同上 |
| `ru_reserve_tenth`：预留检查放宽到 1/10 | **存活** | 测试的预留是 1e9，放宽十倍照样被拒，测试对边界不敏感 → 应修 3 |
| `ru_late_modules_skipped`：跑完只复查清单、不复查已载入模块 | **存活** | 与作者的 `ru_late_check_off` 同一缺口 → 应修 3 |
| `ru_marker_exists_unchecked`：开头不查 final 标记是否已存在 | **存活** | 第二次 final 要等 18 格训练全部跑完，才在 `consume_final_read` 被拒；测试只看拒绝信息，分不出早拒还是晚拒 → 应修 3 |
| `ru_isolated_unchecked`：final 不查 `-I` | **存活** | 没有测试不带 `-I` 跑 final → 应修 3 |
| `ru_versions_unchecked`：不比对第三方版本 | **存活** | 没有测试改版本 → 应修 3 |
| `vr_passes_with_nothing_checked`：重放一个世界都没核对也判通过 | **存活** | `checked > 0` 这一条没有测试；如果 `replay.json` 里没有世界，确定性门会空过 → 应修 3 |
| `ru_n_main_from_records`：`n_main` 取记录条数而不是登记值 | 存活 | 诚实运行里两者相等；只有少世界时才不同，第 4 项的合成试验已说明登记值能挡住少世界 → 建议 10 |
| `ru_partial_not_hashed`：不给 `worlds.partial.jsonl` 记 SHA | 存活 | 影响小 → 建议 10 |

**代码约束违例 2 个，另加 2 个只作用于交互臂的版本**：见第 2 项。四组合计 48 个。

### MLX 触发用例

都在共享锁下、在测试自建的假根目录里跑，用替身分区、MLX CPU 设备。

**评测中途被杀**（`evidence/harness/kill_eval.py`，输出 `evidence/out/mlx/kill_eval.json`）：
- smoke 改成 10 个主世界加 2 个外推世界、1 个 worker。
- `worlds.partial.jsonl` 写到 3 行时，对进程组发 SIGKILL（启动后 22.8 秒）。
- 被杀后：
  - partial 文件 3 行全部可解析，编号 0、1、2；
  - `worlds.jsonl` 不存在，报告里没有 `result`；
  - 同配置完整运行一遍（12 个世界），被杀那次的 3 条记录与完整运行的对应世界**逐位相同**。
- 上一轮必修第三部分「超时后已算完的部分可以复算」成立。

**重放校验的篡改试验**（`kill_eval.py` 后半段、`evidence/harness/replay_tamper.py`；输出 `kill_eval.json`、`replay_tamper.json`）：

| 篡改 | `verify_replay.py` 的结果 |
|---|---|
| 不篡改 | 通过，核对 36 格 |
| 把种子 1 的 L-int 权重换成种子 2 的 | **发现**：`main 0 L-int#1@base`、`extrap 1000 L-int#1@base` 不一致 |
| 改学习格 `L-int#1@base` 的编号摘要 | **发现**：`main 0 L-int#1@base` 不一致 |
| 改手工格 `E-B#1@base` 的编号摘要 | 通过：重放只覆盖学习格，手工格不在范围内（建议 6） |
| 只翻转 reid 的对错标记，摘要不动 | 通过：这就是第 6 项说的盲区（建议 6） |

`kill_eval.py` 第一次改摘要时改到的是记录里的第一个键，那是手工格，不在重放范围内，所以那次「通过」不能算作重放没发现篡改。`replay_tamper.py` 改正了这一点。

## 9. 测试复跑与数量

证据：`evidence/out/mlx/counts.json`。在 a767ac7 的隔离副本里持锁复跑：

| 范围 | 结果 |
|---|---|
| 默认入口（纯 CPU，4 个 S4 CPU 文件） | 72 passed，52 deselected |
| `--native-mlx` 的 `test_s4_learned_mlx.py` | 31 passed |
| `--native-mlx` 的 `test_s4p1_runner_native.py` | 21 passed |
| `--native-mlx` 下全部 S4 测试一起跑 | 124 passed（= 72 + 31 + 21） |

与研究日志「CPU 72、MLX 31、运行器 21 项全过」一致。

## 10. 研究日志数字抽查（第五至第十轮）

**通过。** 抽查 25 处，全部与文件一致（四舍五入到日志的位数）。证据：`evidence/harness/spot10.py`、`evidence/out/spot10.json`。

| 轮次 | 抽查的数字 | 来源文件 |
|---|---|---|
| 第五轮 | L-int 的 D 0.444（0.397）、HF 0.027；L-ind 的 HF 上界 0.069 | `run5-20000-crashed.log` |
| 第六轮 | L-int 的 D 0.823、HF 上界 0.135；L-int-c 的 D 下界 0.845；宽 128 的 HF 0.097；重识别参照 E-B 22、E-P 33 | `results6` |
| 第七轮 | 0.25、0.25 配置的 HF 0.102（6 盘）、0.099（10 盘） | `results7` |
| 第八轮 | 衰减、宽 128 的 D 0.862；衰减的 HF 上界 0.139 | `results8` |
| 第九轮 | 0.5、10、10 配置的 D 0.837、HF 0.078、自由步误差 0.061、重识别 36；不裁剪的自由步误差 0.113 | `results9`、`run9-ablation.log` |
| 第十轮 | L-int-c 的 HF 上界 0.078；不裁剪的 HF 0.094；L-ind 的 D 下界 0.002 | `results9-w1-confirm`、`run10-w1-confirm.log` |
| 擦边分解 | 无墙柱接触的自由步误差 0.118、0.099；E-B 碰撞误差 1.269 | `diag8-*.json` |

另外核对了日志里的一句话：「第六轮写法重训的数与第六轮在四位小数上相同」。`results9` 的 recipe6 与 `results6` 的 L-int，在 6 盘和 10 盘的 D、D 下界、HF、HF 上界上逐位相同。

两处说明：
- 自由步误差只在日志文件里（`free_error6`），JSON 里没有。
- 擦边分解的自由步取的是 `free_by_hard_contact.none`（本步也没有墙、柱接触），这与日志「本步没有任何接触」的说法一致。

## 应修项（修法）

**应修 1：学生视图的 `suffix_changed` 恒真。**
- 位置：`reports/V9-S4-PHASE1/run_s4p1.py` 第 207 行。
- 复现：`evidence/harness/item1_student2.py`。
- 修法：改为 `any(not np.array_equal(x[: len(y)], y) for x, y in zip(a[STUDENT_CUT + 1:], b[STUDENT_CUT + 1:]))`，并加一条运行器测试：只读长度的跟踪器必须让门判不过。
- 这是运行器代码，要在探针之前改。

**应修 2：代码约束测试可以被绕过。**
- 位置：`tests/v9/experiments/test_s4_learned_mlx.py` 第 63–91 行。
- 复现：`mut_mlx.py` 的 `V2`。
- 修法：加第 2 项描述的「输出层置零、所有输入都退化成匀速直线」的行为测试。

**应修 3：守卫与训练分支的测试缺口。** 下列变异都没有测试能抓住，每条补一个能让它失败的测试。代码本身我逐行读过，都是对的。
- 作者 r2-runner 的 4 个存活：
  - `ru_cell_limit_not_passed`：L-int-σ 格不传时限（作者工作树里已有未提交的补测）；
  - `ru_replay_ignored`：replay 失败不作废（作者工作树里已有未提交的补测）；
  - `ru_late_check_off`：跑完不复查清单；
  - `vr_skip_mismatch`：重放不比摘要。
- 我的 learned_mlx 存活：
  - `lm_clip_result_unused`：测试应检查更新用的是裁剪后的梯度，例如构造大梯度，比较一步后参数的变化范数；
  - `lm_batch_rng_seed_fixed` 与 `lm_init_seed_fixed`：不同种子的初始参数与批序列都应不同。两者同时出错时，三种子会训出同一个模型，种子平均就没有意义了；
  - `lm_mean_arm_unchecked`：传 L-int-c 作均值应报错。
- 我的运行器存活：
  - `ru_reserve_tenth`：加一条预留只略大于剩余时间的测试，例如上限 900 秒、预留 850 秒；
  - `ru_late_modules_skipped`：与 `ru_late_check_off` 一起，在运行途中改一个冻结文件或模块，期望全部门作废；
  - `ru_marker_exists_unchecked`：标记已存在时，第二次 final 应在训练之前被拒、不建运行目录；
  - `ru_isolated_unchecked`：不带 `-I` 跑 final 应被拒；
  - `ru_versions_unchecked`：预登记里改一个版本号应被拒；
  - `vr_passes_with_nothing_checked`：`replay.json` 的世界为空时应判不过。

**应修 4：`verify_labels.py` 第 41 行的世界列表比对没有测试。**
- 修法：在 `test_tampering_is_caught` 加一种篡改：`recs.pop()`，期望不通过。

## 建议项

5. `analysis.legality`（第 221 行）：E-B 或 E-P 准确率为 `None` 时会抛 `TypeError`。行为是对的，只是报错难读。建议显式判 `None`，并在报告里写明原因。
6. 重放脚本在它重放的 5 个世界上，顺带从重放的编号重算 reid 对错并与记录比对（第 6 项）。再把 E-B、E-P 的基础格也加进重放：C 的分母就来自这两个手工臂，现在改它们的摘要不会被发现。
7. 评测预留的计时改为从标记之后一直到报告写完（第 7 项）。`fit_refs` 的耗时也计入 `train_s`。
8. 给 `fi_gate_strict` 加一条门限边界测试：距离恰好等于门限时应该关联。
9. 给 `perturb` 的「至少保留两个盘」加一条测试。时限测试另加一条接近边界的情形，例如时限略大于 1 步、小于 3 步，让 `lm_time_limit_doubled` 失败。
10. `analysis.evaluate` 或运行器显式检查主、外推记录条数等于登记的世界数；`files_sha256` 里 `worlds.partial.jsonl` 那一项也加测试。

## 没有做的部分

- 没有在 GPU 上训练或重放，所有 MLX 执行都在 CPU 设备上，按运行器测试的做法。
- 上一轮未做的 `filter.py` 的 `on_predict` 钩子：作者已有测试 `test_filter_hook_reads_and_does_not_change_tracking`，我没有另做对抗。

复核完成
