# S2 生命周期收紧：ledger_read_snapshot 隔离快照读取交付报告（ainerzero.V9.P136）

- **执行代理**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（零 MLX 导入、零实盘改动）
- **修改文件（严格单一函数变更）**：
  - `src/ainerzero/v9/experiments/s2/worker.py`：仅改动 `ledger_read_snapshot` 函数。使用 `tempfile.mkdtemp(prefix="s2_ledger_read_")` 创建系统级独立临时目录，严格复制主库 `control.sqlite3` 以及伴生 `-wal` 与 `-shm`（存在时一并复制），在副本上打开并读取 `RunStore`，退出时在 `finally` 中严格清理临时目录与连接。
  - **同目录 vs 系统临时目录决策理由**：E1 曾将 `.tmp_read_*` 存放在实盘同目录下，异常中断时会在实盘留下临时文件残留；S2 采用系统临时目录彻底杜绝了实盘目录产生任何残留文件的风险。
  - 除该函数外，`worker.py` 其余全部代码字节级未改动（详见 `reports/V9-S2-P136/worker.diff`）。
- **新增单测（`tests/v9/experiments/test_s2_lifecycle.py` 新增 2 项）**：
  - `test_g_ledger_read_snapshot_leaves_real_ledger_completely_untouched`：读取前后对实盘主库、-wal、-shm 逐项比对 `mtime_ns`、`size`、`inode` 以及 SHA256，断言完全一致，且账本所在目录新增文件数为 0；
  - `test_h_ledger_read_snapshot_reads_completed_run_residing_only_in_wal`：在 `wal_autocheckpoint=0` 且仅在 WAL 中存在 completed 记录时，断言 `ledger_read_snapshot` 与 `check_cell_already_completed` 能够准确读取。
- **坏对照对抗变异（全隔离沙盒执行，均变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P136-M1**（回退为直接打开实盘账本）：`test_g` 变红拦截（KILLED，exit 1，检测到 SHM 状态篡改）；
  - **P136-M2**（拷贝时漏拷 WAL 文件）：`test_h` 变红拦截（KILLED，exit 1，断言 completed 记录缺失）。
- **全量纯 CPU 回归与实盘零写入审计**：
  - 前台纯 CPU pytest 配合 `SIG_DFL` 信号还原：**3531 passed, 6 deselected, 0 failed**（总计 3537 项）；
  - 实盘 `artifacts/` 全量 80,929 项在测试前后执行逐项 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
- **产物清单**：详见 `reports/V9-S2-P136/sha256.json`。
