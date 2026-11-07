# S2 生产路径集成 W1 实施与测试报告：数据与训练接线（附录 D1/D2）

- **任务 ID**: `ainerzero.V9.P163`
- **执行者**: 二级执行 agent `gemini-k4m9`
- **会话指纹**: `sess-4f742d12ff65`
- **日期**: 2026-11-07
- **状态**: 完成（纯 CPU 工程实现与严密测试，无 MLX 导入，零 artifacts 副作用）

---

## 1. 任务背景与目标

依据 `reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 D（生产路径串联规范）第 D1 节与第 D2 节，完成第一批生产接线工作：
1. **顶层 CLI（附录 D1）**：`cli.py` 增加 `--partition {train,dev,final}`；`generate-data` 模式只认 `--partition`，缺失或传 `--arm` 均拒跑（`argument_validation`）；顶层不提供步数覆盖参数。
2. **数据留出集与长目标配对（附录 D1）**：在 `data.py` 与 `data_runner.py` 中，train 分区按 `sha256("s2p1-train-v1|holdout|" + str(w_idx))` 字典序升序前 10% 确定 holdout 世界；写出 `HOLDOUT_WORLDS.json` 并记录于 manifest；仅对 holdout 世界生成长目标配对规范 `goal_episode_specs.json`（每世界 6 对）。
3. **训练接线与模型选择（附录 D2）**：在 `commands.py` 与 `train_runner.py` 中，固定数据目录为 `output_root/datasets/train`，删去兜底 `steps or spec.H_TRAIN` 和 `output_root/"data"`；训练 batch 只取非 holdout 世界，模型选择只取 holdout 世界（按世界切，独立于种子）；模型选择间隔固定为 `spec.MODEL_SELECTION_EVERY_STEPS`（200 步），删去私有常量；步数从 SQLite 台账动态解析最近一条 pass 的 smoke 记录，缺失则拒跑（`stage="smoke_steps_missing"`）；检查点目录固定为 `checkpoints/<arm>/seed<k>/`，best checkpoint SHA 记入台账。

---

## 2. 详细实现清单与映射表

| 规范出处 | 设计要求 | 源码实现位置 | 验收测试用例 |
| :--- | :--- | :--- | :--- |
| **附录 D1** | `s2-phase1` 增加 `--partition {train,dev,final}` | `src/ainerzero/cli.py:1393-1397` | `test_w1_cli_generate_data_argument_validation` |
| **附录 D1** | `generate-data` 缺失 `--partition` 拒跑 | `src/ainerzero/cli.py:1621-1632`, `commands.py:488-498` | `test_w1_cli_generate_data_argument_validation` |
| **附录 D1** | `generate-data` 传 `--arm` 拒跑 | `src/ainerzero/cli.py:1633-1644`, `commands.py:480-486` | `test_w1_cli_generate_data_argument_validation` |
| **附录 D1** | 不提供步数覆盖参数 | `src/ainerzero/cli.py`（未对 `s2-phase1` 暴露 `--steps`） | CLI 参数解析核验 |
| **附录 D1** | train 分区散列排序选 10% holdout 世界 | `src/ainerzero/v9/experiments/s2/data.py:397-418` | `test_w1_data_holdout_worlds_generation` |
| **附录 D1** | 输出 `HOLDOUT_WORLDS.json` 与清单记录 | `src/ainerzero/v9/experiments/s2/data.py:406-417` | `test_w1_data_holdout_worlds_generation` |
| **附录 D1** | holdout 世界生成 6 对长目标 specs | `src/ainerzero/v9/experiments/s2/data.py:439-446, 471-482` | `test_w1_data_holdout_worlds_generation` |
| **附录 D1** | 非 holdout 世界不生成 goal specs | `src/ainerzero/v9/experiments/s2/data.py:471` | `test_w1_data_holdout_worlds_generation` |
| **附录 D2** | 数据目录固定为 `output_root/datasets/train` | `src/ainerzero/v9/experiments/s2/commands.py:348` | `test_w1_train_resolves_steps_from_passed_smoke_and_executes` |
| **附录 D2** | 删去兜底 `output_root/"data"` | `src/ainerzero/v9/experiments/s2/commands.py:348` | `test_no_data_dir_fallback` (W1-M4) |
| **附录 D2** | 训练 batch 只取非 holdout 世界 | `src/ainerzero/v9/experiments/s2/train_runner.py:204-266` | `test_w1_train_runner_holdout_separation_and_checkpoint_path` |
| **附录 D2** | 模型选择只取 holdout 世界（按世界切，独立于种子） | `src/ainerzero/v9/experiments/s2/train_runner.py:204-266` | `test_w1_train_runner_holdout_separation_and_checkpoint_path` |
| **附录 D2** | 模型选择间隔固定为 `spec.MODEL_SELECTION_EVERY_STEPS` (200) | `src/ainerzero/v9/experiments/s2/train_runner.py:317` | `test_w1_model_selection_interval_defaults_to_spec` |
| **附录 D2** | 删去私有常量 `EVAL_EVERY_STEPS=5` 和 `HOLDOUT_FRACTION` | `src/ainerzero/v9/experiments/s2/train_runner.py`（完全移除） | `test_w1_model_selection_interval_defaults_to_spec` |
| **附录 D2** | 训练步数从 SQLite 台账动态解析（最近一条 completed + passed） | `src/ainerzero/v9/experiments/s2/commands.py:280-316` | `test_w1_train_resolves_steps_from_passed_smoke_and_executes` |
| **附录 D2** | 缺失或未 pass smoke 拒跑（`stage="smoke_steps_missing"`） | `src/ainerzero/v9/experiments/s2/commands.py:503-512` | `test_w1_train_rejects_missing_or_failed_smoke` |
| **附录 D2** | 检查点目录固定为 `checkpoints/<arm>/seed<k>/` | `src/ainerzero/v9/experiments/s2/train_runner.py:348` | `test_w1_train_runner_holdout_separation_and_checkpoint_path` |
| **附录 D2** | best checkpoint SHA 记入台账结果与 meta | `src/ainerzero/v9/experiments/s2/train_runner.py:430, 455` | `test_w1_train_runner_holdout_separation_and_checkpoint_path` |
| **附录 D2** | 删去兜底 `steps or spec.H_TRAIN` | `src/ainerzero/v9/experiments/s2/commands.py:349-354` | `test_w1_train_rejects_missing_or_failed_smoke` (W1-M1) |

---

## 3. 负对照变异测试（5 组全部转红并 100% 恢复）

在沙盒中对 5 处关键逻辑进行反向破坏性突变，验证测试套件的拦截有效性：

```json
{
  "mutations": [
    {
      "id": "W1-M1",
      "description": "Fallback step count to spec.H_TRAIN (16) if smoke steps missing",
      "file": "src/ainerzero/v9/experiments/s2/commands.py",
      "target_test": "test_w1_train_rejects_missing_or_failed_smoke",
      "turned_red": true,
      "exit_code": 1,
      "failure_summary": "assert code == commands.EXIT_FAILED"
    },
    {
      "id": "W1-M2",
      "description": "Holdout set cut by random sequence permutation instead of world-cut",
      "file": "src/ainerzero/v9/experiments/s2/train_runner.py",
      "target_test": "test_w1_train_runner_holdout_separation_and_checkpoint_path",
      "turned_red": true,
      "exit_code": 1,
      "failure_summary": "assert len(train_seqs) > 0"
    },
    {
      "id": "W1-M3",
      "description": "Model selection interval defaults to 5 instead of spec.MODEL_SELECTION_EVERY_STEPS",
      "file": "src/ainerzero/v9/experiments/s2/train_runner.py",
      "target_test": "test_w1_model_selection_interval_defaults_to_spec",
      "turned_red": true,
      "exit_code": 1,
      "failure_summary": "assert spec.MODEL_SELECTION_EVERY_STEPS == 200"
    },
    {
      "id": "W1-M4",
      "description": "Training data directory defaults to output_root / 'data' instead of datasets/train",
      "file": "src/ainerzero/v9/experiments/s2/commands.py",
      "target_test": "test_w1_train_resolves_steps_from_passed_smoke_and_executes",
      "turned_red": true,
      "exit_code": 1,
      "failure_summary": "assert steps == 400"
    },
    {
      "id": "W1-M5",
      "description": "Commands generate-data allows passing --arm without rejection",
      "file": "src/ainerzero/v9/experiments/s2/commands.py",
      "target_test": "test_w1_cli_generate_data_argument_validation",
      "turned_red": true,
      "exit_code": 1,
      "failure_summary": "assert ret == 1"
    }
  ],
  "all_turned_red": true
}
```

变异测试完成后，工作区所有文件散列值经 SHA-256 对比 100% 恢复。

---

## 4. 回归测试与环境完整性

1. **测试结果**：
   - 执行命令：`.venv/bin/pytest tests/v9/experiments/test_s2_data.py tests/v9/experiments/test_s2_data_runner.py tests/v9/experiments/test_s2_train_runner.py tests/v9/experiments/test_s2_w1_integration.py tests/v9/experiments/test_s2_wiring.py -v`
   - 结果：**56 passed in 38.92s**（无跳过、无失败）。详见 `pytest_full.log`。
2. **纯 CPU 保障**：
   - 严格无 MLX 导入，无真实模型权重下载或运行。
3. **Artifacts 守卫**：
   - 执行前后比对：`artifacts/` 目录下 59,746 个文件零修改，无任何临时写入。详见 `stat_comparison.json`。
4. **Git 差异补丁**：
   - 见 `git_diff.patch`。

---

## 5. 交付物汇总

- `reports/V9-S2-W1/REPORT.md` / `reports/V9-S2-W1/报告.md`: 完整总结报告与问题映射表
- `reports/V9-S2-W1/metrics.json` / `reports/V9-S2-W1/指标.json`: 结构化交付指标
- `reports/V9-S2-W1/mutation_summary.json`: 5 组变异转红与恢复证明
- `reports/V9-S2-W1/stat_comparison.json`: Artifacts 零副作用对比证明
- `reports/V9-S2-W1/git_diff.patch`: 完整 git diff 补丁
- `reports/V9-S2-W1/pytest_full.log`: 完整回归测试日志
