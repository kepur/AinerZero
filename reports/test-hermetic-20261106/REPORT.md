# E1/S1 测试封闭性报告（V9.A17，2026-11-06）

- **守卫位置与理由**：置于 `tests/conftest.py`（根级 conftest）。覆盖全量测试子目录，保证跨套件会话级 stat 与即时函数拦截全局生效。
- **两级守卫实现**：
  1. 函数级：猴子补丁 `fcntl.flock`、`fcntl.lockf`、`sqlite3.connect`，命中实盘 `artifacts/` 抛 `RuntimeError`，白名单为空。
  2. 会话级：`pytest_sessionstart` / `pytest_sessionfinish` 及 autouse fixture 对 `artifacts/locks`、`artifacts/control.sqlite3*`、`artifacts/v9/**/control.sqlite3*`、`artifacts/v9/s1/**/*.sqlite3*`、`artifacts/v9/e1/**` 做前后 stat 对比（mtime_ns/size/inode），不读 `sealed_final`。
- **修复用例**：
  - `test_s1_r7_host_anchor.py::test_the_real_ledger_is_untouched_by_the_anchor_checks`：改用 `tmp_path` 拷贝并猴子补丁 `spec.REGISTERED_HOST_*`。
  - `test_s1_r7_lock.py::test_two_checkouts_cannot_hold_the_lock_at_the_same_time`：改用 staged host 锁文件。
  - `tests/probe_replay.py`：加 `-B` 选项并配置 `dont_write_bytecode`，彻底杜绝 `artifacts/` 写入 `__pycache__`。
- **全量结果与计数**：3431 passed，0 failed，6 deselected（前台 215.54s）。前后 node id 集合（3431 项）逐字完全一致，零增减。
- **实盘零写入**：全量运行前后，对实盘 `artifacts/` 全量 84,248 项做 stat 对比：**0 新增、0 删除、0 修改**（含 `-shm` 与 `-wal`）。
- **隔离变异对抗（/tmp 副本）**：
  - 变异 1（还原 un-staged 账本）：函数级拦截变红（`RuntimeError: Hermetic test guard violation`）。
  - 变异 2（移除 `sqlite3.connect` 拦截）：会话级 stat 捕捉 `control.sqlite3-shm` mtime 变化变红。
  - 副本 340 个源文件还原后 SHA256 逐字节吻合；实盘 `-shm` 纳秒精度还原。
- **仅静态，未修（296 条原生 MLX 用例）**：
  - E1（19 模块 272 条）：`test_e1_contact_geometry.py` 引用实盘 `DEV_ROOT` 数据集；`test_e1_identity/prereg/eval_runner` 读取实盘 prereg/checkpoint。
  - S1（3 模块 24 条）：`test_s1_no_update.py` 经 smoke 引用实盘 root；`test_s1_r7_d_candidate` 与 timing 用例已使用临时 staged host。
  - 全部保留在 `--native-mlx` 选项目录下，按 A39 规范不裸跑，本次未修、未改断言。
