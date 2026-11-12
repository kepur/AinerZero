# P229 第 3 轮：一级补物化端到端测试后验收

执行：一级 claude，2026-11-12。gemini 不在线，由一级补齐第 2 轮要求的测试。gemini-k7x2 写的源码一行未改。

## 补的测试（`tests/v9/experiments/test_s5_world.py` 末尾）
- `test_materialize_end_to_end_matches_direct_calls[0, 15]`：
  - 模块级夹具物化 `s5test-pool-e2e` 的世界 0；
  - 第 0、15 段的 clip、da2、`r1_logd`、`r1_sky`、`r2`、`r3`、`disk_groups`、`ordering_pairs`，逐项等于直接调用 `student_clip`、`da2_frames`、`labels.*`（不传预渲染帧）的结果。
- `test_materialize_end_to_end_clips_cover_disjoint_steps`：
  - 普通测试分区第 1、7 段等于 `student_clip`；
  - 非 pool 分区不写 DA2 帧。
- `test_materialize_end_to_end_shift_appearances`：
  - `s5test-final-shift-e2e` 两套外观的段，各自等于对应外观的 `student_clip`；
  - 两套外观的画面确实不同；
  - R2 标签等于直接调用。
- `test_episode_registered_needs_both_flag_and_run_id[两个登记分区]`：只给 run id、只给允许标志、run id 为空白，三种情况都要抛 `PermissionError`。

## 复验（新隔离副本，纯 CPU）
- 基线：49 项全过。
- `mutations.py`（11 处）加 `mutations-materialize.py`（5 处），16 处全部拦住，原始输出在 `mutations-r3-output.txt`。
- 不够理想的一处：P1（物化时 R2 取第 14 帧）只被换域测试拦住。pool 测试的第 0、15 段里，第 14、15 帧的占据网格碰巧相同。

## 留给后续的意见（不阻塞）
- `materialize_partition()` 对登记分区只要求非空 run id，没有单独的允许标志；`episode()` 则两样都要。好在 CLI 一律拒绝登记分区，final 数据将来只由登记运行器生成。登记运行器实现时，要在调用处显式核对预登记身份。
- 一级补的这几条测试还要非作者复核，并进下一张 S5 复核卡。

## 验收后补正（同日）
全量 CPU 测试时，全仓守卫 `test_no_test_generates_a_registered_partition` 拦下了测试里的字面写法 `allow_registered=True`。顺着查下去，发现两处测试在内存里生成过 final 世界：
- gemini 原版 `test_contract6_registered_partition_permission` 用真实 final 分区做「允许后成功生成」的正例；
- 一级补的测试先替换 REGISTERED，再检查真实分区。

两处都改成在替身命名空间上测正例，真实 final 分区只测拒绝。改完后新副本复验，16 处改动全部拦住（基线 48 passed，见 `mutations-r3b-output.txt`）。研究日志已如实记录。
