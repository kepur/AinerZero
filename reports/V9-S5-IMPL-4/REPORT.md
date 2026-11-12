# ainerzero.V9.P234 执行报告

角色：executor；负责人：grok47-q8w3；时间：2026-11-12
任务状态：reported；实验状态：completed（纯 CPU 契约，无训练）
任务依据：DESIGN-r1.md（b021db0）§4、§5 与末尾补记；labels.py（233ca72）；一级打回见 tier1-review/REVIEW.md
输入身份：metrics.py sha256 e37f119b15043ab9244067c3879d2da1e0b9ece12fc63cdccafa0595b6a4d901；test_s5_metrics.py sha256 ba8f759e321e238297b7a25647ed650215205fc03bf273614accc50071ddf620
修改文件：src/ainerzero/v9/experiments/s5/metrics.py（补 n_nan 与 nan 说明）；tests/v9/experiments/test_s5_metrics.py（补 4 条测试）；本目录报告与证据
实际执行：.venv/bin/python -m pytest -q -p no:cacheprovider tests/v9/experiments/test_s5_metrics.py；.venv/bin/python reports/V9-S5-IMPL-4/tier1-review/mutations.py /Users/mac/AinerWorkFlow/AinerZero
验证结果：18 passed / 0 failed，2.96 秒。tier1 的 14 处改坏源码全部 KILLED，0 漏网。变异后源码哈希与跑前一致。
产物：本 REPORT.md、metrics.json、diff.patch、evidence/pytest_metrics_r2.txt、evidence/tier1-mutations-r2.txt
失败与限制：本轮未重跑 tests/v9 全量（上一棒 1850 通过是补丁之前的结果）。未跑 MLX，未拿锁，未写 artifacts/，未读 artifacts/v9/s5/data/。
交回统筹：口径未改。新增返回字段只有 paired_world_bootstrap 的 n_nan。含 nan 的重抽不丢弃，区间仍走 np.percentile，因此 n_nan>0 时 ci 为 nan。

上一棒 gemini-k7x2 的实现口径保留。本棒只解决打回：补三条生产函数测试，并让自助法返回 n_nan。evidence/mutations.py 与 evidence/mutations-output.txt 是上一棒自己的 11 处变异，不是一级的 14 处；本轮以 tier1-review/mutations.py 的复验为准。

---

## 1. 本轮改了什么

`paired_world_bootstrap` 增加 `n_nan`：重抽结果为 nan 的次数。docstring 写明：不改用 `nanpercentile`，不丢掉这些重抽；只要有一次 nan，`np.percentile` 会让 `ci_lower` 和 `ci_upper` 都变成 nan。

测试新增四条，都调用生产函数：

1. `test_grid_ap_by_distance_mid_bin5_and_near_bin3`
2. `test_ordering_equal_prediction_wrong_for_both_truths`
3. `test_paired_world_bootstrap_equal_tail_percentiles`
4. `test_paired_world_bootstrap_counts_nan_replicates`

距离组断言里的切片下标写死为 `4:6` 和 `0:4`，不读 `DISTANCE_GRID_GROUPS`，避免和被改坏的常量一起漂移。

## 2. 接口与口径

名字、参数、返回值照任务卡。距离边界、保守并列、`>=` 阈值、预测相等算错、partial 只要有一个、线性插值与删失、0.95 倍中位数、有放回抽世界，都与打回前一级读过的实现相同。

- `grid_ap`：拉平后按分数降序，同分负例在前。AP 是每个正例所在名次处精度的平均。无正例返回 nan。
- `grid_ap_by_distance`：`DIST_BIN_EDGES = exp(linspace(log 0.5, log 7, 8))`。near 第 0–3 格，mid 第 4–5 格，far 第 6 格。设计稿「< 2、2–4、> 4 m」是圆盘级分组，网格按格边界取近似。
- `disk_recall`：`sigmoid(score) >= threshold` 记命中。按 `occlusion_group` 或 `distance_group` 返回 `(命中数, 总数, 召回)`。
- `logd_rmse`：target 为 nan 的块不计。object 为 `obj >= 0.5`，floor 为 `1 - sky - obj >= 0.5`，边界 0.5 算进组。
- `ordering_accuracy`：预测对数深度小的更近。预测相等算错。真值 `equal` 不计。对里任一圆盘遮挡组是 partial 就记 partial。圆盘编号 `id - 100` 对应 `disk_id`。返回 `(对数, 准确率)`。
- `steps_to_target`：首点达标返回 `steps[0]`；否则在相邻检查点间线性插值。从未达标返回 `(cap, True)`。`steps_to_target_stair` 取 `steps[j]`，不插值。
- `ga_decision`：达标线 = 0.95 × A0 三条末次 AP 的中位数。`passed = median(A4) <= 0.7 × median(A0)`。阶梯版一并返回。
- `expand_world_index`：同一世界被抽中多次时，段下标按次数重复。
- `paired_world_bootstrap`：点估计用全部世界。等尾区间下界分位是 `(1-level)/2`，上界是 `1-(1-level)/2`。Bonferroni 由调用方传 `level = 1 - 0.05/3`。另返回 `n_boot`、`seed`、`level`、`n_nan`。

## 3. 每条测试

| 测试 | 断言 | 源码坏对照 |
|---|---|---|
| `test_grid_ap_perfect_ranking` | 完美排序 AP = 1 | G2 名次从 2 起算，失败 |
| `test_grid_ap_completely_reversed` | 两正两负全反，手算 AP = 5/12 | G2 失败 |
| `test_grid_ap_conservative_tie_breaking` | 一正一负同分 AP = 0.5；[9,5,5,1] 对 [1,1,0,0] 手算 AP = 5/6 | G1 同分改为正例在前，失败 |
| `test_grid_ap_no_positives_returns_nan` | 无正例返回 nan | 无单独变异；与 G3 的空组 nan 同一口径 |
| `test_grid_ap_matches_naive_implementation` | 10 组随机与测试内纯 Python 参照一致 | 参照只在测试里，G2 也会让它和手算一起失败 |
| `test_grid_ap_by_distance_groups_and_nan_isolation` | 正例只在第 6 格时 near/mid 为 nan，far 等于 `6:7` 上的 AP；正例只在第 4 格时 near 为 nan | 拦不住 G3（第 4 格仍在缩窄后的 mid 里）。保留作 far 隔离 |
| `test_grid_ap_by_distance_mid_bin5_and_near_bin3` | 正例只在第 5 格时 mid 等于写死的 `4:6` 上的 AP，且第 4 格单独算是 nan；正例只在第 3 格时 mid 为 nan、near 等于 `0:4` 上的 AP | **G3 KILLED**（上一轮漏网） |
| `test_disk_recall_threshold_boundary_and_grouping` | sigmoid(0) = 0.5 在阈值 0.5 上算命中；遮挡组与距离组标签分对 | G4 改成 `>`，失败 |
| `test_logd_rmse_nan_filtering_and_split_boundaries` | nan 不计；object 与 floor 的 0.5 算进组。手算全量 RMSE = sqrt((1+4)/2) | G5 地面改成 `>`，失败 |
| `test_ordering_accuracy_rules` | equal 不计；任一圆盘 partial 则该对记 partial | G7 改成两边都 partial 才算，失败。拦不住 G6：相等那对真值是 a，去掉判等后预测落到 b，仍然算错 |
| `test_ordering_equal_prediction_wrong_for_both_truths` | 两对预测都相等，真值分别是 a 和 b，准确率都是 0 | **G6 KILLED**（上一轮漏网） |
| `test_steps_to_target_interpolation_and_censoring` | 首点 100；中间插值手算 250；阶梯 300；从未达标 (cap, True)；非单调首次达标手算 175 | G8 去掉插值、G14 删失旗标改 False，失败 |
| `test_ga_decision_p228_numerical_cases` | A0 末次 0.60、0.62、0.64，达标线 0.589。情形 1A passed；全部删失 passed=False；A4 与 A0 相同 passed=False；比值约 0.75 时 passed=False | G9 达标线改 0.90、G10 中位数改均值，失败 |
| `test_paired_world_bootstrap_properties` | 同一种子结果相同；常数统计量区间退化为 42；`expand_world_index([2,0,2])` 段重复 | G12 步长改错，失败。常数退化拦不住 G13 |
| `test_paired_world_bootstrap_single_positive_world_repetition` | 只有世界 0 有 5 个正例。抽中两次返回 10，全量点估计 5 | G11 无放回，失败 |
| `test_paired_world_bootstrap_equal_tail_percentiles` | 统计量是已知数组在所抽世界上的均值。同一 seed、同一 `rng.choice` 顺序独立算出 2000 个值。level 0.95 与 0.9833 的 `ci_lower`/`ci_upper` 分别等于 `(1-level)/2` 与 `1-(1-level)/2` 分位。0.9833 的区间比 0.95 宽。并断言该下界不等于未减半的 alpha 分位 | **G13 KILLED**（上一轮漏网） |
| `test_paired_world_bootstrap_counts_nan_replicates` | 抽不到世界 0 时 stat 为 nan。`0 < n_nan < 400`，且 ci 两端都是 nan | 覆盖 n_nan；不改 percentile 实现 |
| `test_metric_validation_and_error_handling` | 形状不符、缺 obj/sky、未知 split 抛 ValueError | 守卫，不在 14 处变异里 |

独立朴素 AP 只作参照，手算例子仍是 `test_grid_ap_perfect_ranking`、`test_grid_ap_completely_reversed`、`test_grid_ap_conservative_tie_breaking`。

## 4. 源码坏对照原始结果

命令：

```text
.venv/bin/python reports/V9-S5-IMPL-4/tier1-review/mutations.py /Users/mac/AinerWorkFlow/AinerZero
```

脚本在仓库副本上逐处改 `metrics.py`、跑同一测试文件、再写回原文。跑前与跑后 `metrics.py` 的 sha256 都是 `e37f119b15043ab9244067c3879d2da1e0b9ece12fc63cdccafa0595b6a4d901`。脚本把失败测试名截到 50 字，G6 的全名是 `test_ordering_equal_prediction_wrong_for_both_truths`。

```text
imports from /Users/mac/AinerWorkFlow/AinerZero/src/ainerzero/__init__.py
BASELINE 0 [] ['18 passed in 2.08s']
G1_ties_positive_first: KILLED ['test_grid_ap_conservative_tie_breaking'] ['1 failed, 17 passed in 1.98s']
G2_rank_off_by_one: KILLED ['test_grid_ap_perfect_ranking', 'test_grid_ap_completely_reversed'] ['4 failed, 14 passed in 3.09s']
G3_mid_group_narrow: KILLED ['test_grid_ap_by_distance_mid_bin5_and_near_bin3'] ['1 failed, 17 passed in 1.61s']
G4_recall_strict: KILLED ['test_disk_recall_threshold_boundary_and_grouping'] ['1 failed, 17 passed in 1.48s']
G5_floor_strict: KILLED ['test_logd_rmse_nan_filtering_and_split_boundaries'] ['1 failed, 17 passed in 1.44s']
G6_equal_pred_correct: KILLED ['test_ordering_equal_prediction_wrong_for_both_trut'] ['1 failed, 17 passed in 2.11s']
G7_partial_and: KILLED ['test_ordering_accuracy_rules'] ['1 failed, 17 passed in 2.01s']
G8_no_interp: KILLED ['test_steps_to_target_interpolation_and_censoring', 'test_ga_decision_p228_numerical_cases'] ['2 failed, 16 passed in 2.51s']
G9_target_090: KILLED ['test_ga_decision_p228_numerical_cases'] ['1 failed, 17 passed in 2.03s']
G10_mean_not_median: KILLED ['test_ga_decision_p228_numerical_cases'] ['1 failed, 17 passed in 2.05s']
G11_no_replacement: KILLED ['test_paired_world_bootstrap_single_positive_world_', 'test_paired_world_bootstrap_equal_tail_percentiles'] ['3 failed, 15 passed in 1.86s']
G12_expand_wrong_stride: KILLED ['test_paired_world_bootstrap_properties'] ['1 failed, 17 passed in 1.88s']
G13_alpha_not_halved: KILLED ['test_paired_world_bootstrap_equal_tail_percentiles'] ['1 failed, 17 passed in 1.86s']
G14_ga_censor_flag_dropped: KILLED ['test_steps_to_target_interpolation_and_censoring'] ['1 failed, 17 passed in 1.96s']
```

14/14 拦住。原文在 `evidence/tier1-mutations-r2.txt`。契约测试原文在 `evidence/pytest_metrics_r2.txt`（18 passed in 2.96s）。

## 5. 未做

未改设计稿、labels、已有报告和 tier1-review 脚本。未提交、未推送。未下载模型，未调用付费服务。
