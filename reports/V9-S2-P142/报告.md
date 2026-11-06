# REPORT · ainerzero.V9.P142 S2 训练 runner（臂协议 / 纯 CPU）

- **任务**：`ainerzero.V9.P142`
- **执行者**：`composer-m4k7`（skills: text, code, math）
- **会话指纹**：`sess-c4309a6cbd44`
- **上一棒**：`gemini-h8c2` context_full，范围内无半成品；本棒从零实现

## 摘要

1. 新增 `src/ainerzero/v9/experiments/s2/train_runner.py`：后端无关臂协议（`init` / `train_step` / `rollout_error` / `save` / `n_params`）；`run_train_cell` 只读 `datasets/train/`，拒绝路径中的 `dev`/`sealed_final`；按种子切 train 留出集；显式 `RandomState` 采样；按留出集 H 步滚动误差选最优 checkpoint；墙钟守卫提前停止时 `status=stopped` 并如实记录 `actual_steps`；写出 `checkpoints/<arm>/<seed>/{best.ckpt,meta.json}`。
2. `make_worker_train_runner` 接通 `execute_work_cell` / `s2_phase1_command`；重复 (臂,种子) 由 worker/commands 既有 `duplicate_execution` 拦截，测试已覆盖。
3. 测试 `tests/v9/experiments/test_s2_train_runner.py`（合成数据 + FakeLinearArm / ScriptedArm）：留出误差下降与最优步 argmin；dev/sealed_final 拒绝；墙钟守卫；可复现 SHA；duplicate；P138 output_root；`-I` 无 MLX。
4. 坏对照 P142-M1..M4 均在隔离副本变红并按字节还原（见 `mutations_evidence.json`）。
5. 全量前台 pytest（`.venv`，SIG_DFL）：**3561 passed, 6 deselected, 0 failed**，273.33s。未改范围外文件，未写 `artifacts/`，未导入 MLX，未提交推送。

## 测试清单

| 用例 | 结果 |
|---|---|
| holdout 误差下降 + best_step=argmin（含非单调脚本臂） | PASS |
| dev / sealed_final 路径立即报错 | PASS |
| 墙钟守卫 → stopped，非 completed | PASS |
| 同种子两次 checkpoint SHA 相同 | PASS |
| 同 (臂,种子) 第二次 → duplicate_execution | PASS |
| P138 output_root 守卫 | PASS |
| `-I` 导入后 mlx ∉ sys.modules | PASS |
| 显式 rng 不受全局污染 | PASS |

## 变异表

| ID | 变异 | 结果 |
|---|---|---|
| P142-M1 | 允许 `dev` 路径 | **变红** |
| P142-M2 | 墙钟超限仍标 completed | **变红** |
| P142-M3 | 最优步取最后一步 | **变红** |
| P142-M4 | 采样器用全局 `np.random` | **变红** |

## 新文件 SHA256

见 `sha256.json`。
