自证：本复核者为 gemini-7k2q（会话 sess-1b76bd83a8ad），被验任务 ainerzero.V9.P163 作者为 gemini-k4m9。本复核者非被验卡作者，无血缘或会话重叠，只读核对，未运行 MLX。

# ainerzero.V9.P165 复核报告：S2 集成 W1（P163）非作者独立复核

## 1. 复核结论：RECOMMEND_ACCEPT

经过非作者全量复核、静态代码审查、回退清零审计、生产调用链逐行追踪、隔离沙箱 6 组变异（5 组作者变异 + 1 组复核者独立自做变异）全红全还原测试，以及全量纯 CPU 回归与 `artifacts/` 目录 80,933 项条目的 lstat（mtime、ctime、size、ino）零改动审计，确认 ainerzero.V9.P163 满足 S2 集成 W1 的所有设计规范与质量门槛。

建议统筹予以通过（**RECOMMEND_ACCEPT**）。

---

## 2. 变更范围与工作区审计

### 2.1 P163 提交范围
根据 P163 卡面要求与提交历史，涉及文件共 8 个：
- 核心源码：
  - `src/ainerzero/cli.py`
  - `src/ainerzero/v9/experiments/s2/data.py`
  - `src/ainerzero/v9/experiments/s2/data_runner.py`
  - `src/ainerzero/v9/experiments/s2/commands.py`
  - `src/ainerzero/v9/experiments/s2/train_runner.py`
- 测试用例：
  - `tests/v9/experiments/test_s2_w1_integration.py`
  - `tests/v9/experiments/test_s2_data.py`
  - `tests/v9/experiments/test_s2_wiring.py`

### 2.2 工作区其他修改归属说明
- `src/ainerzero/v9/experiments/s2/learned_planning.py` & `tests/v9/experiments/test_s2_learned_planning.py`：由并行执行卡 ainerzero.V9.P164（执行者 `gemini-b7x4`）创建与编辑，不属于 P163，未发生命名或符号冲突。
- `tests/_hermetic_site/` & `conftest.py`：由已验收卡 A22/A23 引入的沙箱封闭性支持结构，测试运行平稳兼容。
- 确认除卡面列出文件外，`src/` 核心架构与协议逐字节一致，无私自扩展。

---

## 3. 回退清零审计（Fallback Audit）

复核者针对 S2 训练核心链路进行了全量回退与写死常量审查，排查 `or []`、`or {}`、`getattr(..., 默认值)`、`if ... is None else`、`default_`、`0.5`、`base_success_rate`、`preferred_`、`eval_episode` 等风险模式：

| 检查项 | 代码定位 | 审计结论 |
|---|---|---|
| `0.5` 常量审计 | `spec.MIN_NON_BFS_RATIO = 0.5`, `spec.K_WEIGHTS` | 纯注册规范常数，无业务写死判断逻辑 |
| `base_success_rate` / `preferred_` / `eval_episode` | `s2/` 全目录 grep | 0 匹配，无任何前代假指标遗留 |
| `smoke_train_steps` 回退 | `commands.py:519-526` | 缺失或未 passed 严格拒绝，报 `stage="smoke_steps_missing"`, `status="refused"`, `EXIT_FAILED`，绝不回退到默认步数 |
| 训练数据目录兜底 | `commands.py:350` | 严格绑定为 `output_root / "datasets" / "train"`，已彻底剔除旧版 `output_root / "data"` 兜底 |
| 模型评估频率默认值 | `train_runner.py:320` | 严格绑定 `spec.MODEL_SELECTION_EVERY_STEPS` (200)，已彻底剔除 `EVAL_EVERY_STEPS=5` |
| 留出比例默认值 | `train_runner.py:321` | 严格绑定 `spec.TRAIN_HOLDOUT_WORLD_FRACTION` (0.1)，已彻底剔除私有常量 `HOLDOUT_FRACTION` |

---

## 4. 生产调用链逐行追踪（Production Call Points Trace）

追踪从命令行入口 `cli.py` 到底层执行器 `train_runner.py` 的完整真实链路：

1. **CLI 参数解析与预检（`src/ainerzero/cli.py:1621-1639`）**：
   - 模式为 `generate-data` 时，要求 `--partition` 必须在 `{train, dev, final}` 中。
   - 若传入 `--arm`，直接拦截返回状态 `refused`，`stage="argument_validation"`，进程退出码 1。
2. **命令调度与台账解析（`src/ainerzero/v9/experiments/s2/commands.py:280-356, 519-526`）**：
   - `s2_phase1_command` 严格按只读模式打开 `S2Ledger`，检索最近一条 `completed` 且 `passed=True` 的 smoke 运行记录提取 `shared_train_steps`。
   - 提取失败则拒绝执行，不产生任何脏数据。
   - 数据目录固定组装为 `output_root / "datasets" / "train"`。
3. **训练执行与检查点持久化（`src/ainerzero/v9/experiments/s2/train_runner.py:194-250, 348, 430-455`）**：
   - `load_train_and_holdout_sequences` 按 `HOLDOUT_WORLDS.json` 严格划分训练世界与留出评估世界，断言留出集与训练集非空。
   - 检查点持久化路径统一为 `checkpoints/<arm>/seed<k>/best.ckpt`。
   - 训练完成后计算 `best_checkpoint_sha` 并同时记入 `meta.json` 与 RunStore 台账。

---

## 5. 独立隔离沙箱变异测试（6 组全红全还原）

复核者构建独立临时沙箱，将源码与测试完整复制，断言 import 解析至沙箱。运行全部 5 组作者变异及 1 组复核者独立自做变异（REV-M6），每组运行前后核对 SHA256。

| 变异编号 | 变异名称 | 注入位置 | 目标测试用例 | 转红状态 | 退出码 | 失败断言特征 | SHA 还原验证 |
|---|---|---|---|---|---|---|---|
| **W1-M1** | fallback_steps_to_h_train | `commands.py:519` | `test_w1_train_rejects_missing_or_failed_smoke` | **RED** | 1 | `assert code == commands.EXIT_FAILED` | 一致 (100%) |
| **W1-M2** | holdout_by_sequence_permutation | `train_runner.py:245` | `test_w1_train_runner_holdout_separation_and_checkpoint_path` | **RED** | 1 | `assert len(train_seqs) > 0` | 一致 (100%) |
| **W1-M3** | model_selection_interval_default_5 | `train_runner.py:320` | `test_w1_model_selection_interval_defaults_to_spec` | **RED** | 1 | `assert spec.MODEL_SELECTION_EVERY_STEPS == 200` | 一致 (100%) |
| **W1-M4** | data_dir_default_output_root_data | `commands.py:350` | `test_w1_train_resolves_steps_from_passed_smoke_and_executes` | **RED** | 1 | `assert steps == 400` | 一致 (100%) |
| **W1-M5** | generate_data_allows_arm_flag | `commands.py:496` | `test_w1_cli_generate_data_argument_validation` | **RED** | 1 | `self.error(msg % ' '.join(argv))` | 一致 (100%) |
| **REV-M6** (自选) | omit_holdout_worlds_json_generation | `data.py:406` | `test_w1_data_holdout_worlds_generation` | **RED** | 1 | `assert holdout_file.is_file()` | 一致 (100%) |

**变异测试结论**：6/6 全部变红，变异存活率 0%，测试防护严密无死角。沙箱文件在每组变异后均 100% 逐字节恢复原始 SHA。

---

## 6. 关键论断对盘抽检（Spot-checks）

对 P163 报告及代码中的 3 项核心论断进行对盘抽查核验：

1. **论断 1（CLI 参数拦截）**：
   - *论断*：`cli.py` 在 `s2-phase1` 中添加 `--partition` 选项，且在 `generate-data` 下禁止 `--arm` 传入。
   - *核验*：`src/ainerzero/cli.py` 第 1393-1397 行注册 `--partition`；第 1621-1639 行实现严格拦截，实测调用均返回 1。核验属实。
2. **论断 2（留出世界哈希排序算法）**：
   - *论断*：train 分区留出世界依据 `sha256("s2p1-train-v1|holdout|" + str(w_idx))` 升序选出前 10% 并持久化至 `HOLDOUT_WORLDS.json`。
   - *核验*：`src/ainerzero/v9/experiments/s2/data.py` 第 398-417 行完全匹配该哈希命名空间及输出逻辑。核验属实。
3. **论断 3（训练步数解析与防呆）**：
   - *论断*：train 模式未传 steps 时，必须从台账解析已通过的 smoke 记录，缺失时判拒跑。
   - *核验*：`src/ainerzero/v9/experiments/s2/commands.py` 第 519-526 行严格执行此逻辑，测试用例 `test_w1_train_rejects_missing_or_failed_smoke` 覆盖有效。核验属实。

---

## 7. 纯 CPU 全量回归测试与 Artifacts 目录零改动审计

- **纯 CPU 环境确认**：子进程采用标准纯 CPU 环境启动，未设置 `--native-mlx`，顶层无 mlx 侵入。
- **信号处理重置**：前台进程重置为 `SIG_DFL`。
- **回归测试结果**：
  - 测试用例总数：3,649 项
  - 8 项 native_mlx 用例按规则正常 deselected
  - 3,641 项纯 CPU 用例全部通过（0 failed, 3641 passed）
- **Artifacts 目录 lstat 审计（mtime, ctime, size, ino）**：
  - 测试前扫描条目数：80,933
  - 测试后扫描条目数：80,933
  - 属性变更数（diff_count）：**0**
  - 确认测试过程中无任何测试用例对 `artifacts/` 目录进行写入或修改，完全符合沙箱封闭性规范。
