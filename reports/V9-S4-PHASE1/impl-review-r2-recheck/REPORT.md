# S4 第一阶段实现第二轮复核：修订确认

- 复核者：`claude-s4impl-rev2-1110`（非作者）
- 被审提交：`4c88f62`。它在 `a767ac7` 之上，中间还有 `16588f4`、`31c1e3d`。
- 隔离副本用 `git archive 4c88f62` 取出。
- 只在隔离副本里执行：没有改仓库、没有提交，也没有跑登记运行。
- MLX 部分在共享锁下进行，测试都在假根目录里跑，用替身分区、MLX CPU 设备。
- 证据在 `evidence/`。

## 总判定：可以进入探针

上一轮的条件 1（应修 1）已修好，探针之前要改的只有这一项。应修 2、4 和采纳的建议我都已复核，结论是通过。

运行器与重放的变异也已跑完：任务点名的 10 个全部杀掉。存活的 6 个里，有 2 个说明 `make_prereg.py` 的评测预留公式没有测试（见第 3 项）。

冻结之前还缺三件事：
1. 给 `make_prereg.py` 的评测预留与超时预估补数值测试（见第 3 项）。
2. 设计稿「实现补记」按新代码更新（见第 5 项）。设计稿在冻结清单里，但不在探针的代码清单里，所以可以在探针之后、冻结之前改。
3. 可选：建议 A。

## 逐项结论

**1. 应修 1，学生视图判据：通过。**
- 比较移进了 `analysis.mutation_row`，`suffix_changed` 改为对齐前缀比较。
- 我的只读长度桩（`item1_student2.py`）在新代码上重跑：四行的 `suffix_changed` 全部为假，门判**不过**（`evidence/out/student_length_only.json`）。
- 诚实跟踪器在三种变异下仍为真。
- CPU 变异 `an_mut_row_unaligned`、`an_mut_row_prefix_short`、`an_future_mutation_no_shift` 都被 `test_future_mutation_comparison` 杀掉。
- `an_mut_row_consumed_steps_only` 存活：去掉 `len(b) == len(mut)` 后，只有跟踪器返回的步数比输入少时才会有区别。列为建议 A，不影响通过。

**2. 应修 2，零输出层行为测试：通过。**

在新代码上跑整份 `test_s4_learned_mlx.py`（40 项），我的四个违例全部被杀掉（`evidence/out/mlx/mut_mlx_cc_full.json`、`mut_mlx_ccg_fullfile.json`）：

| 违例 | 结果 |
|---|---|
| V1：平滑解析交换 | 杀掉 |
| V2：`mx.clip` 硬接触 | 被 `test_with_a_zero_output_layer_every_arm_is_constant_velocity[L-ind]` 杀掉 |
| V1 只作用于交互臂 | 杀掉 |
| V2 只作用于交互臂 | 被同一测试的 `[L-int]` 杀掉 |

残余风险：如果解析规则乘在网络输出上，输出层置零时它也为零，这条测试看不出来。这种写法仍然要靠逐行审读。

**3. 应修 3，补测试：通过。冻结之前补一条预登记测试。**
- learned_mlx：我的 10 个变异全部杀掉（`evidence/out/mlx/mut_mlx_lm.json`）。
- 运行器与重放：22 个变异杀掉 16 个（`evidence/out/mlx/mut_mlx_ru.json`）。任务点名的 10 个**全部杀掉**：`lm_clip_result_unused`、`lm_batch_rng_seed_fixed`、`lm_init_seed_fixed`、`lm_mean_arm_unchecked`、`ru_reserve_tenth`、`ru_late_modules_skipped`、`ru_marker_exists_unchecked`、`ru_isolated_unchecked`、`ru_versions_unchecked`、`vr_passes_with_nothing_checked`。
- 存活 6 个：
  - `mp_reserve_eval_only`：`make_prereg.py` 把预留改回只算评测耗时。
  - `mp_budget_ignores_reserve`：超时预估不加预留。
  - 上面两个说明 `make_prereg.py` 的评测预留和超时预估没有数值测试。**冻结前要补**：用一份给定 `post_marker_seconds` 与 `pre_eval_seconds` 的探针报告，断言 `eval_reserve_s == ceil(1.5 × 4 × post)`；并断言 `1.2 × pre + 预留` 超过 4 小时时拒绝冻结。
  - `vr_partial_check_passes`：只要核对过一个格就判通过。没有测试检查少核对一部分格的情形，列为建议 B。
  - `ru_post_marker_after_generation`：计时起点挪到世界生成之后，现在没有测试，列为建议 C。
  - `ru_n_main_from_records`、`ru_extrap_count_wrong`：诚实运行里两种写法等价，列为建议 D。

**4. 应修 4，标签校验少一个世界：通过。**
- `vl_world_list_unchecked` 被 `test_tampering_is_caught[missing_world]` 杀掉。
- CPU 变异合计 27 个，杀掉 26 个（`evidence/out/mut_cpu.json`）。

**5. 采纳的建议：通过，附一条文档要求。**
- **合法性门只会更严。**
  - 代码层面：只加了一个合取项 `complete`；地板门原来在 E-B 或 E-P 为 `None` 时抛 `TypeError`，现在判不过；各门的计算没有动。
  - 合成试验（`evidence/out/gates_probe.json`）：
    - 外推记录为空但登记 20 个、外推少 1 个、主评测少 1 个，都判 `complete` 不过，全部门作废；
    - E-B 准确率无定义时判地板门不过，不再报错；
    - 上一轮的 12 种缺数据情形结论不变；
    - 好的合成结果照样全过。
  - 没有新的放行路径。
- **重放：** 现在也覆盖 E-B、E-P，用 `truth_ids` 重算每个事件的对错，并要求 `checked == expected`。读代码与 Me.reid 的定义一致；`truth_ids` 只写进 `replay.json`，学生读不到。
- **计时：** `pre_eval_seconds` 从脚本开始算到标记之前；`post_marker_seconds` 从标记之后算到复查之后，覆盖世界生成、评测、写文件、检查和门。`make_prereg.py` 的预留是 `ceil(1.5 × 4 × post_marker_seconds)`，超时预估是 `1.2 × pre_eval_seconds + 预留`。都合理，而且偏保守。
- **文档要求：** `DESIGN-r3.md` 的「实现补记」仍然写着旧规则（「评测与校验耗时 × 4 × 1.5」），也没有声明新的 `complete` 合法性项和重放范围的扩大。冻结之前要改。
- **建议 8、9、10 的测试：** 门限边界测试、至少两个盘、假时钟时限，都已读过并确认有效。前两项的变异也被杀掉了。

**6. 测试数：通过。** 在 `--native-mlx` 下复跑（`evidence/out/mlx/counts.json`）：

| 范围 | 结果 |
|---|---|
| CPU 默认入口 | 76 passed |
| MLX（`test_s4_learned_mlx.py`） | 40 passed |
| 运行器 | 29 passed |
| 合计 | 145 passed |

与作者报的一致。

## 建议

- A. `mutation_row` 的 `consumed` 里 `len(b) == len(mut)` 这一条补一个测试，例如跟踪器少返回一步。
- B. 重放校验补一条测试：只核对了部分格时判不过。
- C. 补一条测试，确认 `post_marker_seconds` 从生成评测世界之前开始计时。
- D. 两种写法在诚实运行里等价，补不补都可以。

## 未完成

- 用量到限，没有做更多对抗检查。

复核完成
