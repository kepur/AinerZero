# 非作者复核报告：V9.P136 S2 账本读取先拷贝再读（ainerzero.V9.P137）

- **自证声明**：复核者为 `gemini-f4b2`（二级执行 Agent，会话 `sess-c96b728f5618`），非被复核任务 `ainerzero.V9.P136` 的作者（`gemini-w4x2`），亦非作者的同会话别名。本次复核全过程只读、纯 CPU，未修改任何源码与测试代码。
- **复核结论**：`RECOMMEND_ACCEPT`

## 1. 改动范围核验（逐字节与 AST 对照）
- **交付代码 SHA256**：
  - `src/ainerzero/v9/experiments/s2/worker.py`：`b283f0fa2ef3354601c360faf814e0f94b44952d9c27a4610cc2a9c4270359ef`（与 P136 交付一致）
- **逆向补丁比对**：
  - 使用 `reports/V9-S2-P136/worker.diff` 对当前 `worker.py` 执行反向打补丁（`patch -R`），生成的源码 SHA256 为 `f439840c2d8ccdf72196babdbb50304ddc8fc8d7ab366f067cd23005eda4f0dd`，与 P126 交付时的官方 SHA256 **逐字节 100% 吻合**。
- **函数定义粒度比对**：
  - 未改动（逐字节一致）：`get_experiment_manifest`, `check_cell_already_completed`, `S2Ledger`, `default_stub_runner`, `execute_work_cell`
  - 唯一改动函数：`ledger_read_snapshot`
  - 范围符合严格单一函数修改要求。

## 2. 实盘零改动独立自测
- 独立编写测试 `reports/V9-S2-P136/review/test_independent_zero_modification_and_wal.py`：
  - 在隔离目录构建活跃 WAL 与 SHM 的账本，持活跃连接模拟并发 worker；
  - 记录读取前主库、`-wal`、`-shm` 的 `st_mtime_ns`、`st_size`、`st_ino` 与 SHA256，记录账本目录文件名列表；
  - 依次调用 `worker.ledger_read_snapshot` 与 `worker.check_cell_already_completed`；
  - 核实结果：
    - 主库 stat 与 SHA256：**100% 完全一致**
    - `-wal` stat 与 SHA256：**100% 完全一致**
    - `-shm` stat 与 SHA256：**100% 完全一致**
    - 账本所在目录新增文件数：**0（无任何临时文件残留）**

## 3. 副本完整状态读取（WAL 可见性）
- 在 `wal_autocheckpoint=0` 条件下，向账本写入 completed 状态的 run，确保其仅驻留在 WAL（未 checkpoint 到主库，WAL 尺寸 156,592 字节）；
- 调用 `ledger_read_snapshot` 与 `check_cell_already_completed`：
  - 快照内准确遍历到 WAL 中的 completed run（seed=202）；
  - `check_cell_already_completed` 返回 `True`；
  - 证明 WAL 文件与 SHM 一同被正确复制，副本具备完整状态可见性。

## 4. 复核者自做变异（3 处自做变异，全数变红 / KILLED）
在隔离沙盒内执行对抗变异测试（`run_reviewer_mutations.py`），每次变异运行后均恢复原始文件并校验 SHA256：
1. **REV-M1（副本未清理）**：
   - 变异：在 `ledger_read_snapshot` 的 `finally` 块中省略 `shutil.rmtree(tmp_dir, ignore_errors=True)`。
   - 目标测试：`test_replica_directory_cleaned_up`
   - 结果：**变红拦截（KILLED，exit 1）**，抛出 `AssertionError: Replica directory ... was NOT cleaned up!`。
2. **REV-M2（主库只读直接打开不拷贝）**：
   - 变异：回退为直接打开实盘主库 `store = RunStore(p)`。
   - 目标测试：`test_independent_zero_modification`
   - 结果：**变红拦截（KILLED，exit 1）**，检测到 WAL/SHM 被篡改（`AssertionError: WAL file modified`）。
3. **REV-M3（快照漏拷 WAL 文件）**：
   - 变异：拷贝快照时跳过 WAL 文件。
   - 目标测试：`test_independent_wal_visibility`
   - 结果：**变红拦截（KILLED，exit 1）**，断言未 checkpoint 的 completed 记录缺失（`AssertionError: Expected 1 completed run with seed 202, found: 0`）。

## 5. 全量纯 CPU 回归与实盘零改动审计
- 前台纯 CPU pytest（配置 `SIG_DFL` 信号还原，`relay exec` 监督）：
  - **3536 passed, 6 deselected, 0 failed**（总计 3542 项，耗时 276.75s）；
  - 实盘 `artifacts/` 目录 80,929 项在测试前后执行逐项 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
