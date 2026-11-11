# P229 一级对抗验收（第 1 轮）：打回

验收人：一级 claude，2026-11-11。

## 方法
- 在隔离副本里改坏源码：src、tests、pyproject 一起复制，再加上摸底版 `reports/V9-S5-DESIGN/tier1-explore/render.py`，PYTHONPATH 指向副本，并先确认副本导入的是自己。
- 副本基线：36 项全过。
- 然后逐条改坏源码，跑 `tests/v9/experiments/test_s5_*.py`。脚本是 `mutations.py`。

## 结果：11 个改动只拦住 4 个

| 改动 | 结果 | 拦住它的测试 |
|---|---|---|
| M1 `episode` 去掉 REGISTERED 检查 | 拦住 | test_contract6_registered_partition_permission |
| M2 `da2_frames` 不传 `f=DA2_F`（等于 f=259） | **漏网** | — |
| M3 R2 记计数（`+= 1`） | **漏网** | — |
| M4 R2 取段内第 14 帧而不是第 15 帧 | **漏网** | — |
| M5 深度用射线长度而不是光轴 z | 拦住 | contract1 墙深度、contract4 |
| M6 `student_clip` 帧号整体偏 1 | **漏网** | — |
| M7 R1 全天空块记 0 而不是 nan | 拦住 | test_r1_labels_contract |
| M8 R3 不加 8 步 | 拦住 | test_r3_step_offset |
| M9 可见像素门槛 4 → 1 | **漏网** | — |
| M10 方位左右颠倒 | **漏网** | — |
| M11 纹理默认关 | **漏网** | — |

**为什么漏网：** 各个 `*_bad_control*` 测试改坏的是测试文件里另写的一份实现，生产代码没被测到。

**例子：** `test_contract5_r2_multi_disk_same_cell_stays_one` 把两个圆盘放在 (2.0, 0) 和 (2.1, 0)，智能体在 (0, 0) 朝 +x。后一个圆盘被前一个完全挡住，不计入网格，所以永远测不到「同格两个」。

## 必须改
1. **测试必须调用生产函数，每个漏网改动都要有测试拦下。**
   - 删掉或改写那些只测测试内部重写实现的「坏对照」测试。坏对照的正确做法是：在隔离副本里改源码，证明测试会失败，把结果写进报告。
   - 至少要覆盖：
     - **M2：** 用 `da2_frames()` 的输出，与按 `f=196` 直接 `render()` 的同一帧逐像素比对；
     - **M3：** 两个圆盘都看得见、且落在同一格；
     - **M4、M6：** `student_clip` 的帧和 `r2` 用的步，与按全局步直接 `render()` 的结果比对；
     - **M9：** 构造只露出 2–3 个像素的圆盘；
     - **M10：** 左侧圆盘落在方位格 ≥ 6，右侧圆盘落在 ≤ 5；
     - **M11：** 默认调用带纹理，与 `texture=True` 一致、与 `texture=False` 不同。
2. **`materialize.py` 的 manifest 要写代码身份：**
   - git HEAD；
   - `src/ainerzero/v9/experiments/s5/*.py` 与 `s4/world.py` 的 SHA256。
3. **登记分区的守卫：**
   - CLI 一律拒绝 REGISTERED 分区；final 数据只由将来的登记运行器生成。
   - 函数层要求 `allow_registered=True` 且给出非空 `registered_run_id`，两者缺一就拒绝。
4. **范围检查：**
   - `s5p1-` 开头的命名空间必须在 `PARTITIONS` 里，拼错的名字要拒绝；
   - `world_index` 与 `--worlds` 必须落在 `[0, PARTITIONS[分区])` 内。
5. **性能：** 标签每帧重渲一遍，物化的渲染量约是 2.3 倍。改成每帧只渲染一次，学生帧、深度、编号图一起用。可以给 `labels` 加一个接受预渲染深度与编号图的入口，原接口保留。
   - 改完后加一条测试：两条路径产生的标签逐元素一致。
   - 报告里给出单个世界的物化耗时。
