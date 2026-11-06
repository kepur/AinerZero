# S2 数据生成 runner 交付报告（ainerzero.V9.P133 / P134）

- **执行代理**：`gemini-7a4c`（二级执行 Agent）· 纯 CPU（零 MLX 导入、零实盘写入、不跑正式生成）
- **交付目标**：实现 `src/ainerzero/v9/experiments/s2/data_runner.py` 与单元测试 `tests/v9/experiments/test_s2_data_runner.py`，供 `execute_work_cell` 作为 runner 调用。
- **核心契约实现**：
  - **分区与规模**：支持 `train`、`dev`、`final` 分区生成；`train` 强制要求显式传入规模；`dev`/`final` 默认对应 50 世界 × 6 对长目标与规则 dt 子集；
  - **写盘与密封**：严格断言 `output_root` 处于临时目录下，坚决拒绝实盘 `artifacts/`；`final` 分区落盘至 `datasets/sealed_final/`，代码路径中零读取 final 内容，只登记 SHA256；
  - **去重与不重叠**：生成前查询 RunStore 账本，若已有 completed 记录则安全返回 `duplicate_execution` 并保留原文件；生成后调用 `assert_partitions_disjoint` 校验命名空间与地图摘要；
  - **账本记录**：耗时、世界数、回合数、非 BFS 段占比、世界重抽数、`SHA256SUMS.txt` 摘要写入 completed 记录。
- **坏对照变异矩阵（隔离沙盒副本，均变红 KILLED，已按字节还原并校验 SHA256）**：
  - **P134-M1**（去除重复检查）：变红（KILLED, exit 1），捕捉 `duplicate_execution` 失效；
  - **P134-M2**（final 写到 `final/` 而非 `sealed_final/`）：变红（KILLED, exit 1），捕捉密封目录缺失；
  - **P134-M3**（去除 `output_root` 临时目录断言）：变红（KILLED, exit 1），捕捉实盘路径未拦截。
- **小样生成与耗时估算**：
  - 测得 3 世界 × 2 回合（完整 240 步）平均耗时 0.2898 s/世界（0.1449 s/回合），在 1 小时数据生成预算下可支撑 2300+ 世界，远超设计需求。
- **全量回归与实盘零写入审计**：
  - 前台纯 CPU pytest（SIG_DFL+execv）：**3531 passed, 6 deselected, 0 failed**（用时 252.04s）；
  - 实盘 `artifacts/` 80,929 项在测试前后执行 stat 对比：**0 新增、0 删除、0 修改（零差异）**。
