# 探针 p1 失败（2026-11-11 15:06–15:10 UTC）

- 运行：`run_s4p2.py --stage probe --use-id p1`，代码 `3b05266`，电脑重启后约 6 分钟启动，1 分钟负载 3.3。
- 失败：评测阶段一个工作进程报
  `RuntimeError: [Compile::eval_cpu] Failed to compile function Cf4IBroadcastABDf4IBroadcastBAEf4OMaximumCD_VC_f4_..._contiguous`，
  链接器 `ld: open() failed, errno=17 (File exists)`。原始文件 `reports/V9-S4-PHASE2/probe-p1.json`、`probe-p1.log` 与运行目录 `artifacts/v9/s4/phase2/probe-p1/` 原样保留。
- 原因：`nn.relu` 是 `mx.compile` 的函数，MLX 把融合的 CPU 内核编译成共享库，存进 `$TMPDIR/mlx/<版本>/cpu/`。重启清空了这个缓存，6 个评测工作进程同时首次编译同一个内核，写同一个文件，互相撞上。
- 复现（`race_repro.py`，输出 `race_repro.txt`）：每轮一个新的空缓存目录、一个新的广播形状，6 个进程同时算。
  - 共用一个目录：8 轮 48 次里失败 23 次，其中有与探针完全相同的内核名；
  - 每个进程各用一个目录：48 次全部成功。
- 修法：`worker_p2.private_compile_dir()`，在工作进程初始化最先执行，把 `TMPDIR` 设为每进程一个目录 `<系统临时目录>/ainerzero-mlx-cpu/<pid>`。新测试 `tests/v9/experiments/test_s4p2_worker_native.py` 在新进程里验证 MLX 确实把内核写进这个目录（去掉设置 `TMPDIR` 的一行，测试失败）。
- 对 final 的意义：final 在评测之前写只读一次标记。如果评测时出这种撞车，那一次读取就白花了，所以必须在冻结前修。
