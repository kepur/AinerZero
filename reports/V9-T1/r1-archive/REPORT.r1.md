# ainerzero.V9.T1 r1 报告：回应 Codex 2026-10-16 退回

- 作者：Claude（一级），2026-10-16 09:2x。纯 CPU；只改设计、schema、示例与核对脚本；没有训练、下载、运行任何模型。

## 先归档

r0 原件逐字节复制到 `reports/V9-T1/r0-archive/` 并记 SHA256SUMS：
- 文档 `c386bb37…`、v0 schema `55c899b7…`，与 r0 报告记录一致；
- r0 报告与核对结果。

v0 schema 与 v0 示例原地保留为历史，不再作为合格输入。

## 改了什么（逐项关闭表见规范 §8）

1. **锁**：只用一把 `artifacts/locks/m0-worker.lock`，Teacher、Train、World 三种模式在整段占用区间持有，废弃 `teacher-mode.lock`；崩溃时由内核释放；旁边的租约说明文件只用于观察。
2. **Core ML**：Train 不允许任何教师，没有例外；只保留 World 教师与 AWZ 渲染并行时用 `CPU_AND_NE`。
3. **缓存身份**：拆成内容块 `teacher_blob`（`cache_key` 只由推理内容决定）与来源条目 `teacher_entry`（`entry_id` 含世界、分区、输入、用途）。
   - 同内容同分区不同世界：一个块、多个条目；
   - 同内容跨分区：判 `cross_partition_blob`，拒绝。
4. **分区与 sim_truth**：条目分区为四值；`final` 只能进封存评测库，其余三值只能进共享库，schema 层强制。sim_truth 只是通道，来源为 `simulator_truth`。
5. **新 schema**：`contracts/v9/teacher_cache.v1.schema.json`（内容块、来源条目、噪声标定）。

## 实际命令与结果

```bash
python3 -I reports/V9-T1/r1/lock_model_check.py reports/V9-T1/r1/lock_model_check.json
/Users/mac/AinerWorkFlow/AnimeWorldZero/.venv/bin/python -I reports/V9-T1/r1/check_teacher_cache_v1.py /Users/mac/AinerWorkFlow/AinerZero reports/V9-T1/r1/check_result_v1.json
```

- **锁交错穷举**，返回码 0：
  - r0 复现三种违例：Teacher×Train（180 种交错里找到违例轨迹）、Train×World、Teacher×旧 M2；
  - r1 的 16 种进程组合（含同类两进程）全部无违例；
  - 两种故意改坏都被抓到：取锁后马上释放，以及先占用再取锁。
- **缓存 v1**，返回码 0：
  - 库级正例 1 个，含“同内容不同世界”；
  - 结构反例 11 个，都在预期字段上以预期关键字被拒；
  - 库级反例 9 个，都按预期理由被拒：两条跨分区、输入摘要不一致、条目身份错、块键错、孤儿条目、特征教师带噪声模型、derived_by 错、未批准教师；
  - 11 个破坏自检全部变红，每个都被对应反例抓到。
- 中途发现一处自检写得不对：`final_store_unchecked` 一开始是因为改坏后 schema 不合法才变红，不算数。已改为“保留合法 schema、只删这条规则”，现在由反例 `entry_final_in_shared_store` 抓到。

## 摘要

| 文件 | sha256 |
|---|---|
| docs/v9/TEACHERS_AND_CACHE.md（r1） | 3d98bb161cee711bb57fbc8c39c0b503b527c664fb0952d46da2bd4a386e8a0a |
| contracts/v9/teacher_cache.v1.schema.json | 67d779d60d50e61f68c34ba531a37a1ec1976559fb7b0198c6b7e8f374bf4f90 |
| reports/V9-T1/r1/lock_model_check.py | 188e7eccf3e70fdcd28177f44ccea8902a26c47a0d2136740b8686ab89b30bb6 |
| reports/V9-T1/r1/check_teacher_cache_v1.py | 64cef71afb607ee573447a4a411156dc55342d3e2165298a32660d50a4235068 |

## 未验证与限制

- 锁交错检查是协议级模型：用原子步抽象 `fcntl` 的非阻塞取锁，不是真实双进程测试。真实双进程复现留给 T2，规范 §6 已写明。
- 内存上限、计算单元、可复现等级仍是规划值，等 T4 实测。
- 本 r1 需要非作者复核（按 AWZ D-018），复核通过后才能验收；T2 仍等 T1 验收。
