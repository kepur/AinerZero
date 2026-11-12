# P233 之后一级补测（2026-11-12）

P233（gemini-r7b2）复核一级补的测试，发现两处盲区，一级照此补测。

- **K1：** `test_r1_object_share_geometry` 的场景只有墙，`obj` 改成只算墙也照样通过。
  - 新增 `test_r1_object_share_counts_pillars_and_disks`：场景里有一根柱子、一个圆盘，逐块的 obj 必须等于编号图上编号 ≥ 0 的占比；
  - 并断言场景里确实有以柱子为主、以圆盘为主的块，这些块的 obj 都 > 0.5。
- **K2：** `disk_groups` 的遮挡比分母（单独渲染这一个圆盘时，它的局部编号是 100）没有测试，误用全局编号 100+i 也照样通过。
  - 新增 `test_disk_groups_occlusion_ratio_uses_single_disk_render`，三个圆盘：
    - 0 号在身后，看不见，不应出现；
    - 1 号一半被柱子挡住，遮挡比必须等于「可见像素 ÷ 单独渲染时的像素」，且落在 0 和 1 之间；
    - 2 号完全可见，遮挡比必须为 1。

**复验：** 一级在自己的隔离副本里用 `mutations-K.py` 跑，脚本会拒绝对实盘仓库操作。

| 改动 | 结果 | 拦住它的测试 |
|---|---|---|
| K1 | 拦住 | test_r1_object_share_counts_pillars_and_disks |
| K2 | 拦住 | test_disk_groups_occlusion_ratio_uses_single_disk_render |
| K4 | 拦住 | 物化端到端测试 |

K3 的原文在源码里出现两次（disk_disk、disk_pillar 各一行），本脚本只接受唯一匹配，所以跳过；复核者的脚本已单独验证 K3 被拦下。原始输出见 `mutations-K-output.txt`。
