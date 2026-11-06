# S2 数据生成 runner 独立非作者复核报告（ainerzero.V9.P135，被验卡 V9.P133）

- **自证**：复核者 `gemini-w4x2` 与被验卡作者 `gemini-7a4c` 具有完全独立之代理身份与会话，此前分别独立承担 P126/P130/P132/P136 等卡，非 P133/P134 作者，亦非同会话别名；严格执行只读非作者独立复核。
- **复核结论**：`RECOMMEND_ACCEPT`

## 1. 范围与源码独立核实
- 审查 `git status` 与 `src/` 代码：P133/P134 仅新增 `src/ainerzero/v9/experiments/s2/data_runner.py` 与 `tests/v9/experiments/test_s2_data_runner.py`；
- 本次复核全程只读，仅在 `reports/V9-S2-P134/review/` 下生成复核产物，未修改任何源码与测试。

## 2. sealed_final 只登记、不读回与规模契约
- **代码静态审计**：`run_generate_data` 将 `final` 分区落盘目录直接原子重命名至 `datasets/sealed_final/`；代码路径中无任何针对 `sealed_final/` 内容文件的读取（无 `open()`、`read_text()`、`json.load()`、`np.load()`），亦无 `read_once` 标记文件；仅以原始二进制字节读取 `SHA256SUMS.txt` 用于计算登记摘要并落库 `completed` 记录；
- **分区间重叠检查规避**：对已生成的候选分区进行 `assert_partitions_disjoint` 校验时，显式将 `sealed_final` 排除在读取 manifest 之外；
- **规模参数与 spec 严格一致**：
  - `dev` 分区默认：50 世界 × 6 对 = 300 回合（`DEV_WORLDS_COUNT=50`, `DEV_PAIRS_PER_WORLD=6`）；
  - `final` 分区默认：50 世界 × 6 对 = 300 回合（`FINAL_WORLDS_COUNT=50`, `FINAL_PAIRS_PER_WORLD=6`）；
  - `train` 分区严格断言必须显式提供 `n_worlds` 与 `episodes_per_world`，缺失时即刻抛出 `ValueError`。

## 3. 重复执行与不重叠自测（独立实测）
执行独立验证脚本 `verify_duplicate_and_disjoint.py`，确认：
- `assert_output_root_is_temporary` 严格拦截指向实盘 `artifacts/` 的路径（抛出 `ValueError`），且严格拦截非系统临时目录（如 `/opt`、桌面等）；
- 首次生成 `dev` 分区成功落库 `completed`；使用相同参数第二次调用时，准确定位已完成记录并返回 `status="duplicate_execution"`，实盘文件 `mtime` 与内容哈希字节级完全一致（零覆盖、零写入）；
- 跨分区故意复用相同 `seed_namespace` 时，`assert_partitions_disjoint` 准确识别命名空间冲突并抛出异常。

## 4. 测试真伪性核查
- 逐项审查 `tests/v9/experiments/test_s2_data_runner.py` 共 7 项单测：
  - 各测试直接通过公用接口调用被测函数 `run_generate_data` 与 `assert_output_root_is_temporary`；
  - 覆盖真实临时文件系统读写、真实 `S2Ledger` SQLite 状态变迁、动态 monkeypatch 拦截读取 `sealed_final`；
  - 无假断言、无常数比常数、无重复重写实现。

## 5. 独立坏对照变异矩阵（4 处作者变异表之外的全新变异，均在隔离沙盒执行）
在隔离沙盒副本中执行 4 处全新变异，全部精准变红（KILLED），并按字节还原及 SHA256 校验：
- **REV-M1**（去除 `train` 分区显式规模校验，允许默认规模）：`test_train_partition_requires_explicit_scale` 变红拦截（KILLED, exit 1）；
- **REV-M2**（去除跨分区 `assert_partitions_disjoint` 互斥核验）：`test_shared_seed_namespace_raises_error` 变红拦截（KILLED, exit 1）；
- **REV-M3**（去除 `assert_output_root_is_temporary` 非临时路径拦截规则）：`test_output_root_under_tmp_path_guard_and_refuses_production` 变红拦截（KILLED, exit 1）；
- **REV-M4**（篡改 `sha256sums_hash` 计算逻辑为常数）：`test_final_partition_written_to_sealed_final_and_never_read_back` 变红拦截（KILLED, exit 1）。

## 6. 纯 CPU 约束与全量回归
- `-I` 子进程纯环境导入 `ainerzero.v9.experiments.s2`，断言 `sys.modules` 中无任何 `mlx` 模块，纯 CPU 约束有效；
- 默认全量前台运行纯 CPU pytest（`SIG_DFL` 信号还原）：**3531 passed, 6 deselected, 0 failed**；
- 实盘 `artifacts/` 全量 80,929 项在测试前后执行 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
