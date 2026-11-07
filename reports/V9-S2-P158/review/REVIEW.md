# 非作者复核报告：V9.P158 S2 冻结准备（spec 只追加、validate、试冻结复算）

自证声明：复核者为 `gemini-k4m9`，被复核任务 ainerzero.V9.P158 的作者为 `gemini-8f4b`；二者分属不同独立 Agent 实例，无同会话别名或自审行为，本次复核完全独立、只读进行。

结论：**RECOMMEND_ACCEPT**

## 1. 复核目标与依据
- 被复核任务：`ainerzero.V9.P158`（S2 冻结准备：附录 C 参数写入 spec、prereg 校验、临时目录试冻结）
- 依据：`reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 C（r2.4）、`AGENTS.md`、`README.md`
- 规范约束：只读核对，纯 CPU，不运行 MLX，不修改源码和现有测试，不冻结实盘文件。

## 2. 独立核查项结果

### (1) spec 只追加性与附录 C 一致性核查
- **前缀字节完整性**：
  - `src/ainerzero/v9/experiments/s2/spec.py` 前 8721 字节 SHA256 为：`b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`。
  - 与作者报告及原有文件前缀 100% 逐字节吻合，前缀无任何篡改或修改。
- **附录 C 常量核对**：
  新增常量严格放置在文件末尾，逐项核对值：
  - `TRAIN_N_WORLDS = 1000`（符合 1000 个世界）
  - `TRAIN_EPISODES_PER_WORLD = 8`（符合每世界 8 回合，共 8000 回合）
  - `TRAIN_HOLDOUT_WORLD_FRACTION = 0.10`（符合 10% 世界留出）
  - `SEED_NAMESPACES = {"train": "s2p1-train-v1", "dev": "s2p1-dev-v1", "final": "s2p1-final-v1", "smoke": "s2p1-smoke-v1"}`（四分区命名空间互不重合）
  - `MODEL_SELECTION_EVERY_STEPS = 200`（每 200 步滚动误差）
  - `SMOKE_SHORT_TRAIN_STEPS = 200`（S = 200）
  - `TRAIN_STEPS_RULE = "floor(1200*0.8/t_min_over_arms)"`（规则正确，具体步数由 smoke 实测记账）
  - `DATA_ESTIMATED_SECONDS_PER_EPISODE = 0.145`（P133 实测耗时，8000 × 0.145 s = 1160 s ≤ 1 h 预算）
  所有常量均与附录 C 完全一致。

### (2) validate 独立篡改构造与验证
在独立沙箱中构造 4 种超出作者常规测试的篡改：
1. **Tamper 1（smoke 命名空间与 train 重叠）**：
   `draft["data"]["seed_namespaces"]["smoke"] = "s2p1-train-v1"`
   结果：捕获 `SpecValidationError: Seed namespaces must be pairwise distinct`。
2. **Tamper 2（训练规模篡改至 50000 世界，耗时 58000 s 远超 3600 s 预算）**：
   `draft["data"]["train_n_worlds"] = 50000`
   结果：捕获 `SpecValidationError: Estimated train data generation time (58000.0 s) exceeds data budget (3600 s)`。
3. **Tamper 3（留出集比例设为下边界 0.0）**：
   `draft["data"]["train_holdout_world_fraction"] = 0.0`
   结果：捕获 `SpecValidationError: train_holdout_world_fraction must be strictly in (0, 0.5), got 0.0`。
4. **Tamper 4（留出集比例设为越界值 0.55）**：
   `draft["data"]["train_holdout_world_fraction"] = 0.55`
   结果：捕获 `SpecValidationError: train_holdout_world_fraction must be strictly in (0, 0.5), got 0.55`。

### (3) 临时目录独立试冻结复算
- 在两个全新临时目录使用作者时间戳 `draft_time_utc="2026-11-07T00:52:32Z"` 各自执行 `freeze.freeze()`：
  - 目录 1 document_sha256: `2a2ae4ba175471c5b9b54943f752f415e97f35aca70304dbb49d72a6c56ee749`
  - 目录 2 document_sha256: `2a2ae4ba175471c5b9b54943f752f415e97f35aca70304dbb49d72a6c56ee749`
  - 两次冻结 100% 确定一致，且与作者报告哈希**完全一致**。
  - 身份验证调用 `identity.verify_frozen_identity()` 返回状态均为 `passed`。
- **源码清单完整性核验**：
  `source_digests` 严格覆盖 24 项源码：
  1. `src/ainerzero/cli.py:s2-phase1`
  2. `src/ainerzero/v9/experiments/s2/__init__.py`
  3. `src/ainerzero/v9/experiments/s2/adapters_mlx.py`
  4. `src/ainerzero/v9/experiments/s2/arms_mlx.py`
  5. `src/ainerzero/v9/experiments/s2/commands.py`
  6. `src/ainerzero/v9/experiments/s2/core_math.py`
  7. `src/ainerzero/v9/experiments/s2/data.py`
  8. `src/ainerzero/v9/experiments/s2/data_runner.py`
  9. `src/ainerzero/v9/experiments/s2/eval.py`
  10. `src/ainerzero/v9/experiments/s2/eval_runner.py`
  11. `src/ainerzero/v9/experiments/s2/freeze.py`
  12. `src/ainerzero/v9/experiments/s2/fwd_counter.py`
  13. `src/ainerzero/v9/experiments/s2/identity.py`
  14. `src/ainerzero/v9/experiments/s2/param_count.py`
  15. `src/ainerzero/v9/experiments/s2/planner.py`
  16. `src/ainerzero/v9/experiments/s2/prereg.py`
  17. `src/ainerzero/v9/experiments/s2/probe.py`
  18. `src/ainerzero/v9/experiments/s2/smoke.py`
  19. `src/ainerzero/v9/experiments/s2/smoke_checks.py`
  20. `src/ainerzero/v9/experiments/s2/spec.py`
  21. `src/ainerzero/v9/experiments/s2/stats.py`
  22. `src/ainerzero/v9/experiments/s2/train_runner.py`
  23. `src/ainerzero/v9/experiments/s2/worker.py`
  24. `src/ainerzero/v9/experiments/s2/world.py`
  24 项摘要无一遗漏。

### (4) 自做变异测试（3 处独立变异）
在作者给出的 P158-M1/M2 之外独立设计并执行：
- **REV-M1**（放宽留出集比例上限至 0.8）：
  - 变异：`if holdout is None or not (0.0 < float(holdout) < 0.8):`
  - 拦截测试：`test_tamper_holdout_fraction_out_of_range_fails`
  - 结果：**RED / KILLED**（exit code 1）。
- **REV-M2**（篡改模型选择步数从 200 至 500）：
  - 变异：`spec.MODEL_SELECTION_EVERY_STEPS = 500`
  - 拦截测试：`test_appendix_c_constants_match_design_document`
  - 结果：**RED / KILLED**（exit code 1）。
- **REV-M3**（篡改数据估算单步耗时从 0.145 至 0.001）：
  - 变异：`spec.DATA_ESTIMATED_SECONDS_PER_EPISODE = 0.001`
  - 拦截测试：`test_appendix_c_constants_match_design_document`
  - 结果：**RED / KILLED**（exit code 1）。
- 变异后恢复并核对文件 SHA256 100% 吻合。

### (5) 全量前台 Pure-CPU 回归
- 恢复默认信号处理器 `SIG_DFL`。
- 测试命令：`.venv/bin/python -m pytest`
- 结果：**3613 passed, 6 deselected, 0 failed**（耗时 288.75s，exit code 0）。
- Artifacts stat audit：80,929 项，diff = 0。

## 3. 验收建议
V9.P158 提交的 spec 追加修改、附录 C 常量配置、prereg draft 及 validate 校验、试冻结及源码摘要覆盖全面严密，坏对照与全量回归完全通过，特此推荐正式验收：**RECOMMEND_ACCEPT**。
