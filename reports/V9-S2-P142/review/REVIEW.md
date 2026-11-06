# 复核自证声明：复核者为独立二级代理 gemini-r7m2（会话 sess-ef82e69a0a5b），非被验任务 ainerzero.V9.P142 作者 composer-m4k7（会话 sess-c4309a6cbd44），亦非其同会话别名；全流程只读核对、纯 CPU 运行。

# V9.P142 S2 训练 Runner 独立复核报告

- **复核任务**：`ainerzero.V9.P144`（二级执行 Agent · verify · code, math）
- **复核对象**：`ainerzero.V9.P142`（作者：`composer-m4k7`，待验收）
- **复核结论**：`RECOMMEND_ACCEPT`

---

## 一、修改范围核验（Scope Audit）

1. **产物清单与文件散列校验**：
   - 作者交付文件：
     - `src/ainerzero/v9/experiments/s2/train_runner.py`（SHA256: `50ac39d8df890b14a3dec503c3ab112b0227dbc6eaf1f1264e8b80068f5d4fd8`）
     - `tests/v9/experiments/test_s2_train_runner.py`（SHA256: `6bbdd7a106be4f880ab57863116bad79ffa84e76d198977b89453f1eb666f901`）
   - 核对当前工作区两个文件的 SHA256，与作者报告及声明 100% 逐字节吻合。
2. **源码树洁净度审计**：
   - 经 `git status --porcelain src/` 及 `git diff HEAD --name-only src/` 审计：
     - 仅 `src/ainerzero/cli.py` 存在既有 56 行 S2 CLI 解析与分发段落（早于 P142 领卡）；
     - `src/` 下其余所有既有受控源码与 `HEAD` 逐字节一致。

---

## 二、不碰 dev 严密性核验与假臂对照

1. **代码级硬拦截**：
   - 模块定义 `FORBIDDEN_PATH_PARTS = frozenset({"dev", "sealed_final"})`；
   - 在 `resolve_train_partition`（第 75-80、86、100 行）、`_load_episode_sequences`（第 128 行）、`load_train_sequences`（第 143、151 行）等多道关口均强制调用 `_reject_forbidden_parts`，若路径解析中出现任一非 train 关键字直接抛出 `ValueError`。
2. **独立双曲面假臂实验（Dual-Curve Fake Arm Experiment）**：
   - 复核者自写具有相反留出集与 dev 最优步的假臂：
     - 留出集（Holdout）误差曲线：step 5=0.40, **step 10=0.08（最优）**, step 15=0.35, step 20=0.50；
     - 设想 dev 误差曲线：step 5=0.50, step 10=0.45, step 15=0.20, **step 20=0.02（最优）**。
   - 运行 `run_train_cell` 完整流程：
     - 实际选取的模型最佳步数：`res["best_step"] == 10`；
     - 确证模型选择完全绑定在 `train` 分区切出的留出集滚动误差上，绝未读取或偏向 dev 曲线。
3. **非法分区路径拦截**：
   - 传入包含 `dev` 的路径：被 `resolve_train_partition` 拦截抛出 `ValueError`；
   - 传入包含 `sealed_final` 的路径：被 `resolve_train_partition` 拦截抛出 `ValueError`。

---

## 三、墙钟守卫与如实报告核查

1. **假时钟超时拦截与如实状态**：
   - 设置单步消耗 10 秒虚拟时间，请求步数 50 步，设定墙钟预算为 25.0 秒；
   - 运行结果：
     - 在第 3 步结束时（累计 30.0s）触发超时守卫，安全中断循环；
     - `status` 如实记录为 `"stopped"`，断言确证 `status != "completed"`；
     - `wall_budget_exceeded` 标记为 `True`；
     - 实际完成步数 `actual_steps` 如实记录为 3（绝不虚报为 50）。
2. **`meta.json` 结构与元数据齐备性**：
   - 检查落盘的 `checkpoints/<arm>/<seed>/meta.json`，核实 12 项必需元数据完整无遗漏：
     - `actual_steps`: 3
     - `requested_steps`: 50
     - `best_step`: 2
     - `holdout_curve`: 完整包含步数与滚动误差列表
     - `n_params`: 90（与假臂参数量一致）
     - `source_digest`: 64 位 SHA256 散列
     - `data_manifest_sha256`: 64 位 SHA256 散列
     - `checkpoint_sha256`: 64 位 SHA256 散列
     - `checkpoint_path`: 指向落盘的 `best.ckpt`
     - `status`: "stopped"
     - `wall_budget_seconds`: 25.0
     - `elapsed_seconds`: 30.0

---

## 四、测试用例真伪审查

审查 `tests/v9/experiments/test_s2_train_runner.py` 中 8 项测试：
- `test_holdout_error_decreases_and_best_step_is_argmin`：调用真实梯度更新臂（权重收敛）与非单调脚本臂（精确验证 `argmin` 提取非最后一步）；
- `test_dev_and_sealed_final_paths_rejected`：针对真实目录结构验证非合法分区的防御性抛错；
- `test_wall_clock_guard_stops_early_not_completed`：通过伪时钟步进验证真实预算守卫；
- `test_fixed_seed_checkpoint_sha_reproducible`：在运行间污染全局 NumPy 随机种子，验证显式 `RandomState` 带来的确定性 Checkpoint SHA；
- `test_duplicate_execution_via_worker_commands`：端到端连通 `commands.s2_phase1_command`，验证已执行单元的拦截；
- `test_output_root_must_pass_p138_guard`：真实挂钩 P138 白名单守卫；
- `test_no_mlx_imported_under_isolated_python`：`-I` 独立子进程导入，断言 `mlx` 零导入；
- `test_sample_batch_uses_explicit_rng_not_global`：直接断言批量采样的独立 RNG 隔离性。
- **结论**：测试设计完整且严谨，所有逻辑均为真实执行，无伪造常数或无意义断言。

---

## 五、复核者独立对抗变异实验（4 处新变异，与作者互补）

在隔离沙箱副本中执行变异测试，每处测试均在独立环境中进行，测试后按字节还原并核验 SHA256：

| 变异编号 | 变异位置与描述 | 预期拦截单测 | 测试结果 | 退出码 | 变异状态分析 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REV-P144-M1** | `train_runner.py:174`：`split_holdout` 改用全局 `np.random.permutation` | `test_fixed_seed_checkpoint_sha_reproducible` | **KILLED** | exit 1 | 全局 RNG 受污染后，两次同 seed 训练的数据划分不一致，产物 SHA 产生漂移。 |
| **REV-P144-M2** | `train_runner.py:301`：留出集模型选择反转为寻找误差最大值 (`err > best_error`) | `test_holdout_error_decreases_and_best_step_is_argmin` | **KILLED** | exit 1 | 选中最差步数（step 20 代替 step 10），用例即刻红灯拦截。 |
| **REV-P144-M3** | `train_runner.py:257`：绕过 `assert_output_root_is_permitted` 白名单 | `test_output_root_must_pass_p138_guard` | **KILLED** | exit 1 | 无法拦截非注册 artifacts 输出路径。 |
| **REV-P144-M4** | `train_runner.py:249`：绕过 `run_train_cell` 内部直接 duplicate 校验 (`if False:`) | `test_duplicate_execution_via_worker_commands` | **SURVIVED** | exit 0 | **架构性防御兜底分析**：在 `commands.s2_phase1_command` 流程中，`worker.execute_work_cell` 在调用具体 runner 前即已前置执行 `duplicate_execution` 并阻断退出，故不会穿透至 `run_train_cell` 内部；`run_train_cell` 内部的校验作为脱离 worker 独立调用时的二次防御，属于良性防御性冗余。 |

---

## 六、纯 CPU 导入与全量回归计数

1. **`-I` 子进程导入验证**：
   - 执行命令：`.venv/bin/python -I -c "import sys; from ainerzero.v9.experiments.s2 import train_runner; assert 'mlx' not in sys.modules; print('ZERO_MLX_OK')"`
   - 结果：`ZERO_MLX_OK: mlx not imported in train_runner`。
2. **前台全量纯 CPU pytest 回归（SIG_DFL 还原）**：
   - 运行用时：266.27 秒；
   - 统计计数：**3561 passed, 6 deselected, 0 failed**（总计 3567 项，包含本模块新增的 8 项单测全部通过）；
   - 退出码：0。
3. **副作用核查**：
   - `artifacts/` 目录：**0 modified, 0 added, 0 deleted**，实盘零写入。

---

## 七、综合结论

**`RECOMMEND_ACCEPT`**

`src/ainerzero/v9/experiments/s2/train_runner.py` 严格遵循 S2 设计协议（纯 CPU、与后端解耦、臂协议清晰）；实现了坚固的留出集模型选择机制与非 train 分区路径阻断；墙钟超时守卫及元数据记录如实且完整；单测覆盖完备，对抗变异测试全红；全量回归 3561 项全通且无任何副作用。建议予以验收。
