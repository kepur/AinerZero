# E1/S1 测试封闭性报告（V9.A17 r2，2026-11-06）

- **一级打回三项整改**：
  - R1 模块化与根解耦：守卫抽成 `guard_snapshot(root)`、`guard_compare(before, after)`、`make_guarded_connect(root)`、`make_guarded_flock(root)`、`make_guarded_lockf(root)`。`conftest` 绑定登记根；严禁环境变量后门；守卫自测纳入默认套件 `tests/test_hermetic_guards.py`（4 项全绿，全在 tmp 伪造根运行）。
  - R2 交付变异脚本：新增 `reports/test-hermetic-20261106/run_mutations.py`，全流程在独立临时伪造根运行，零触碰实盘。
  - R3 实盘前后 stat 覆盖全量与变异两段：覆盖 84,248 项，**0 新增、0 删除、0 修改**（含 `-shm` 与 `-wal`）。
- **两级守卫实现**：
  1. 函数级：猴子补丁拦截 `fcntl.flock`、`fcntl.lockf`、`sqlite3.connect`，命中实盘抛 `RuntimeError`，白名单空。
  2. 会话级：`pytest_sessionstart` / `pytest_sessionfinish` 及 autouse fixture 对敏感路径前后 stat 对比（mtime_ns/size/inode），不读 `sealed_final`。
- **全量结果与计数**：3435 passed，0 failed，6 deselected（前台 231.72s）。节点清单仅增加 4 个新增的守卫自测用例，存量用例完全一致。
- **对抗变异（纯伪造实盘树）**：
  - 变异 1（直连伪造库）：函数级拦截变红（`RuntimeError: Hermetic test guard violation`）。
  - 变异 2（绕过函数级）：会话级 stat 捕捉伪造库 `control.sqlite3-shm` 变动变红（`AssertionError`）。
- **仅静态，未修（296 条原生 MLX 用例）**：
  - E1（19 模块 272 条）：`test_e1_contact_geometry.py` 引用实盘 `DEV_ROOT` 数据集；`test_e1_identity/prereg/eval_runner` 读取实盘 prereg/checkpoint。
  - S1（3 模块 24 条）：`test_s1_no_update.py` 经 smoke 引用实盘 root；`test_s1_r7_d_candidate` 与 timing 用例已使用临时 staged host。
  - 全部保留在 `--native-mlx` 选项目录下，按 A39 规范不裸跑，本次未修、未改断言。
