# ainerzero.V9.P236 执行报告（第 2 轮修订）

角色：executor；负责人：gemini-k7x2（前序第 1 轮：grok47-q8w3）；时间：2026-11-12
任务状态：reported；实验状态：completed（只跑了副本里的 smoke，没有真实 probe / dev-tune / dev-distill）
任务依据：`reports/V9-S5-DESIGN/DESIGN-r1.md`（b021db0）§3–§7 与末尾补记；`reports/V9-S5-IMPL-6/tier1-review/REVIEW.md` 四项打回要求；权威模块 `s5.data`、`s5.train`、`s5.metrics`、`s5.tokens`、`s3.run_guard`
输入身份：新文件与改动见 `diff.patch`。未改已有冻结模块（`data.py`、`train.py`、`metrics.py`、`tokens.py`、`run_guard.py`）。`tests/conftest.py` 只登记了原生测试文件名。
修改文件：`src/ainerzero/v9/experiments/s5/evaluate.py`；`reports/V9-S5-PHASE1/plan_s5p1.py`；`reports/V9-S5-PHASE1/run_s5p1.py`；`tests/v9/experiments/test_s5_evaluate.py`；`tests/v9/experiments/test_s5_runner_plan.py`；`tests/v9/experiments/test_s5_runner_native.py`；`tests/conftest.py`；`reports/V9-S5-IMPL-6/`
实际执行：CPU pytest 12 项（1.63 秒）；在 `hold_lock.py artifacts/locks/m0-worker.lock` 持锁下跑 `--native-mlx` 副本 smoke 与锁/单格真实超时终止/GPU 设备/禁用环境变量后门/SHA 测试 8 项（180.86 秒）。四个阶段都跑了 `--dry-run`。没有读真实 `s5p1` 分区，没有启动真实 probe / dev-tune / dev-distill。
验证结果：12 passed（CPU）+ 8 passed（native-mlx）。忙锁退出码 75 且不写目录。改一个字节的 `dev-tune` 文件在写运行目录之前被拒绝。单格在运行中卡死超时（`min(单格上限, 阶段剩余)`）会被父进程立即 `terminate/kill`，以退出码 2 结束并保留已完成格。每格均跑在默认 GPU 设备上。
产物：本目录 `REPORT.md`、`metrics.json`、`diff.patch`、`SHA256SUMS.txt`、`evidence/dry-run-*.json`、`evidence/pytest-cpu.txt`、`evidence/pytest-native.txt`
失败与限制：无测试失败。读出头在 `--dry-run` 中已改为按「缓存一次学生特征 + 只训读出头」估算（单头约 25–89 s，54 个头合计约 0.81 h，对照设计 §6 的 0.75 h；`dev-distill` 整段估算 2.96 h，对照设计 §6 的 3.22 h），并注明待 `probe` 实测后用实测速度校准覆盖。
交回统筹：`probe` 的学习率设计稿没写，调参之前暂用 `1e-3`。`1/10` 和蒸馏调参的 `1/4` 是按轮数四舍五入，不是精确步数。真实教师目录按 `artifacts/v9/s5/teachers/{vjepa,da2}`、数据按 `artifacts/v9/s5/data/<分区>` 接。

## 第 2 轮针对一级复核（`tier1-review/REVIEW.md`）的四项修订

1. **去掉强制 CPU，恢复默认 GPU 设备（`run_s5p1.py` L230–232、L321）：**
   - 删除了第 1 轮在 `run_s5p1.py` 顶层写的 `mx.set_default_device(mx.cpu)`。
   - 每个格在子进程内执行时记录 `"device": str(mx.default_device())` 到 `cell_end` 事件与 `stage.json` 的 `cells` 列表。
   - 正例测试 `test_smoke_end_to_end_does_not_touch_dev_uses` 断言全部 9 个格的 `device` 均含 `"gpu"` 且不含 `"cpu"`；坏对照 `test_cpu_device_mutation_is_rejected` 在临时副本中注入 `mx.set_default_device(mx.cpu)` 并证明被该断言检出。
2. **单格真正中断正在跑的格（`run_s5p1.py` L495–612）：**
   - 每个格通过 `multiprocessing.get_context("spawn")` 在独立子进程（`_cell_worker_target`）中运行，父进程持有 `artifacts/locks/m0-worker.lock`（子进程不重复抢锁）。
   - 父进程对每个子进程等待 `timeout_s = min(cell_limit_seconds(index), stage_deadline.left())`。若子进程超时仍在运行，父进程立即调用 `p.terminate()` / `p.kill()` 杀掉子进程，记录 `cell_fail`（`error: "timeout"` 及实际 `wall_s`），写出 `stage.json`（`failed: "timeout: cell ... timed out after ..."`），以退出码 `2` 退出，且保留此前已完成格的权重与记录。
   - 每个子进程落盘权重与输出后返回文件路径与 SHA256，父进程在主进程内复核所有产出文件存在且 SHA256 一致后才记 `cell_end`。各 `heads` 格直接从磁盘加载对应蒸馏格保存的 `${distill_cell_id}-student.npz`，不依赖跨格内存态。
   - 正例测试 `test_cell_timeout_keeps_the_finished_cell`：第 0 格正常完成并落盘 `c0.ok`，第 1 格设为 `sleep(25.0)` 而单格时限设为 `1.0s`；验证父进程在约 1 秒内终止第 1 格（远小于 25 秒），退出码为 2，`c0.ok` 完整保留且 `c1.ok` 未写出。
3. **去掉正式运行器里的 `S5_FAKE_CELL` 环境变量入口（`run_s5p1.py` L472–479）：**
   - 从 `run_s5p1.py` 完全移除 `S5_FAKE_CELL` 环境变量分支；正式 CLI 路径只运行真实格处理函数 `_run_cell`。
   - 超时与注入测试统一通过非 CLI 的纯测试参数 `run_locked(args, lock, *, cells_override=None, cell_runner=None)` 传入，且 `stage.json` 显式记录 `"cell_runner_name"`（正式运行恒为 `"_run_cell"`）。
   - 新增测试 `test_s5_fake_cell_env_is_ignored`：验证即使外部设置了 `S5_FAKE_CELL=1`，源码与运行器也完全忽略该环境变量。
4. **`--dry-run` 读出头墙钟按缓存特征路径估算（`plan_s5p1.py` L84–106、L237–266）：**
   - `wall_seconds` 对 `kind == "heads"` 的格按「先过一遍学生网络缓存特征（`n_clips / 54.0` 秒）+ 冻结骨干只训读出头（`steps / 100.0` 秒）」分开估算：单头 L=64 约 25.2 s、L=512 约 47.9 s、L=2048 约 89.1 s。
   - `dev-distill` 的 54 个读出头合计估算 `0.81 h`（对照设计稿 §6 的 `0.75 h`），`dev-distill` 整段估算 `2.96 h`（对照设计稿 §6 的 `3.22 h`，在 4 小时上限内），并在 `heads_note` 注明待 `probe` 实测后校准覆盖。新增 `test_dry_run_dev_distill_heads_wall_clock_estimation` 校验该估算。

## 接口

`evaluate(student, heads, index, *, tau=None, threshold=0.5)` 先调 `train.predict`，再算 R2/R3 的 `grid_ap` 和 `grid_ap_by_distance`、遮挡组与距离组的 `disk_recall`、R1 的全部/object/floor `logd_rmse`、`ordering_accuracy`。开了 `tau` 时另给 keep 率。预测和标签按世界排成连续段，并带 `world_ids`、`clips_per_world`。

`per_world_stat(eval_a, eval_b, metric)` 把抽到的世界交给 `metrics.expand_world_index`。重复的世界会重复计段，然后重算同一指标，返回 A 减 B。`paired_group_stat` 先对一组评测取平均，再相减，给多种子的 A* − A0 用。

## 阶段格与预计墙钟

`--dry-run` 不拿锁。原文在 `evidence/dry-run-*.json`。

| 阶段 | 格 | 步数 | 估算墙钟 (`wall_h_est`) | 读出头估算 (`heads_wall_est_h`) | 设计 §6 (`design_wall_h`) | 时限 |
|---|---:|---:|---:|---:|---:|---:|
| smoke | 9 | 18 | 副本里端到端约 100 秒（含 5 世界渲染与 9 子进程 GPU 训练评测） | — | — | 15 分钟 |
| probe | 17 | 8312 | 0.25 小时 | 0.05 小时（9 头） | 0.50 小时 | 1.5 小时 |
| dev-tune | 11 | 38240 | 1.57 小时 | — | 1.60 小时 | 2.0 小时 |
| dev-distill | 63（6 蒸馏 + 54 读出头 + 3 A0） | 256680 | 2.96 小时 | 0.81 小时（对照设计 0.75 小时） | 3.22 小时 | 4.0 小时 |

## 测试与坏对照

- **CPU 测试（12 项，1.63s）：**
  - `test_s5_evaluate.py`（5 项）：世界子集 AP 差、重复世界展开、floor 子集 RMSE 差、多种子先平均再相减、`per_world_stat` 减法变加法的坏对照。
  - `test_s5_runner_plan.py`（7 项）：四阶段格数核对、`select_a_star` 平局取序、调参平局取小值、GT1 功效等尾分位与 96 封顶、`ARM_ORDER` 反转坏对照、`--dry-run` 无锁输出、`dev-distill` 读出头墙钟估算（0.81 h 对照 0.75 h）。
- **原生 MLX 测试（8 项，持 `m0-worker.lock` 锁运行，180.86s）：**
  - `test_smoke_end_to_end_does_not_touch_dev_uses`：端到端跑通 9 格 smoke，验证默认 GPU 设备、产物权重落盘、账本未触碰、无 `s5p1-final`。
  - `test_busy_lock_writes_nothing`：锁被占时退出码 75，不写运行目录与账本。
  - `test_cell_timeout_keeps_the_finished_cell`：第 1 格运行中 `sleep(25s)` 被 1 秒单格超时立即终止（`wall_s < 5s`），退出码 2，第 0 格成果保留，第 1 格无残留。
  - `test_changed_tune_file_is_refused_before_any_output`：篡改 `dev-tune` 1 字节在写目录和记账前被 SHA 守卫拒绝。
  - `test_writing_before_the_lock_is_caught`：坏对照，拿锁前写目录被检出。
  - `test_timeout_exit_mutation_is_caught`：坏对照，超时退出码改成 0 被检出。
  - `test_cpu_device_mutation_is_rejected`：坏对照，把默认设备改成 CPU 被 GPU 断言检出。
  - `test_s5_fake_cell_env_is_ignored`：验证 `S5_FAKE_CELL` 已移除且被忽略。
