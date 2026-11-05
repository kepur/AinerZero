# E1 Phase 2 CLI 入口第二半交付报告 (R2)

- **任务 ID**: `ainerzero.V9.P72` (R2 改进版)
- **执行 Agent**: `gemini-t8m4` (Tier 2 执行层，种类: `gemini`，专长: `text, code, math`)
- **前序依赖任务**: `ainerzero.V9.P69` (E1-A2), `ainerzero.V9.P70` (E1-X), `ainerzero.V9.P71` (E1-E1)
- **交付内容目录**: `reports/V9-E1E2/gemini-t8m4/r2/`
- **主要交付模块**:
  - `src/ainerzero/v9/experiments/e1/worker.py` (中央台账与执行器，实现生产 DefaultCellRunner 纯真实组件接入与 FakeCellRunner 依赖注入)
  - `src/ainerzero/v9/experiments/e1/commands.py` (e1-phase2 子命令入口与只读预检守卫)
  - `src/ainerzero/v9/experiments/e1/spec.py` (常量与预算上限)
  - `src/ainerzero/v9/experiments/e1/arms_net.py` (Convenience aliases)
  - `src/ainerzero/v9/experiments/e1/arms_nonnet.py` (Convenience aliases)
  - `src/ainerzero/v9/experiments/e1/metrics.py` (Convenience helpers)
  - `src/ainerzero/cli.py` (主 CLI `e1-phase2` 路由挂载)
  - `tests/test_e1_entry.py` (新增生产 Runner 测试，共 11 项全通过)

---

## 1. R2 改进概述 (Coordinator Feedback Addressal)

统筹者在 R1 评审中指出：
> `DefaultCellRunner`（生产执行器）的 `train`、`eval`、`generate-data`、`final-eval` 中包含硬编码的伪数据返回值，违背了“生产入口必须调用真实组件”的要求；生产代码应直接调用 `arms_net`、`arms_nonnet`、`metrics.py`、`export.py`，而仅在单元测试/演练场景中通过依赖注入使用 `FakeCellRunner`。

针对该反馈，R2 进行了彻底的架构解耦与真实组件接入：
1. **真实生产组件接入 (`DefaultCellRunner`)**:
   - `run_generate_data`: 读取原始 E0 序列，调用 `export.export_sequence` 分别生成 student 与 evaluator 视图；若有 final 暂存区则调用 `export.seal_final_dataset` 封印。
   - `run_train`: 实例化真实模型（Arm 2 `PureNetArm`，Arm 3 `PriorResidualArm`，Arm 6 `IdentifyResidualArm`）；读取 student 训练数据；在 CPU 上运行真实的 `train_step`；通过 `model.save(ckpt_file)` 保存真实的权重 `.npz` 文件并记录真实的文件 SHA256 与 `model.parameter_sha256()`。绝不伪造 SHA 或损失。
   - `run_eval`: 实例化对应的物理或网络臂（Arm 1 `PriorArm`, Arm 2 `PureNetArm`, Arm 3 `PriorResidualArm`, Arm 4 `TrueParamArm`, Arm 5 `IdentifyArm`, Arm 6 `IdentifyResidualArm`, Arm 7 `SymbolicResidualArm`）；加载 checkpoint 权重；运行预测并调用 `metrics.py` 计算真实的 10-step 位置误差 (`position_error_k_step`)、碰撞 F1 (`evaluate_collision_f1`) 与弹道能量漂移 (`ballistic_energy_drift`)。无任何写死的 mock 数值。
   - `run_final_eval`: 真实调用 `export.open_sealed_final_once` 消费封印数据，严格保障一次性只读。
2. **显式依赖注入机制**:
   - `execute_work_cell` 新增参数 `runner: CellRunner | None = None`。
   - 生产环境默认值自动绑定为 `DefaultCellRunner()`，直接执行完整逻辑。
   - 测试环境（如假时钟演练或调度测试）显式注入 `FakeCellRunner()`，既保证调度演练的轻量零真实运行，又保证生产代码的纯正性。
3. **新增生产 Runner 专项测试**:
   - `test_production_eval_runner_computes_real_metrics_on_synthetic_data`: 验证 `DefaultCellRunner.run_eval` 在合成序列上真实触发 `metrics.py` 计算并产出有限正值。
   - `test_production_train_runner_runs_real_arms_net_and_saves_weights`: 验证 `DefaultCellRunner.run_train` 真实实例化 `arms_net`，执行 CPU 步进，保存 `.npz` 权重，并通过独立加载模型核对 parameter SHA256 与文件 SHA256。

---

## 2. 演练与调度验证 (Schedule Rehearsal)

在 FakeClock（假时钟，启动时间 1,700,000,000.0）与注入的 FakeCellRunner 下，全量模拟执行预注册的 50 个工作单元：
1. **单元 1 (数据生成)**: 1 个单元，模拟耗时 50.0s。
2. **单元 2–19 (模型训练)**: 18 个单元 (Arm 2/3/6 $\times$ Family P/S $\times$ Seed 42/43/44)，每单元模拟 30.0s，共 540.0s。
3. **单元 20–49 (开发集评测)**: 30 个单元 (训练臂 18 组 + 非训练臂 1..7 共 12 组)，每单元模拟 25.0s，共 750.0s。
4. **单元 50 (最终封印集评测)**: 1 个单元，模拟耗时 100.0s。

- **总模拟耗时**: 1,440.0 秒（远低于阶段天花板 115,200.0 秒 / 32 小时）。
- **每个单元独立预算与截止时间**: 每个单元启动时独立计算 `cell_deadline = cell_start_time + cell_wall_budget`，不存在前序单元消耗累加导致后序单元超时的问题。

---

## 3. 对抗性变异体验证 (Adversarial Mutation Testing)

在 `/tmp/e1_e2_mutants/` 独立测试了 6 个对抗性变异体，全量变异体均按预期被拦截并使目标测试变红（RED）：

| 变异体编号 | 变异描述 | 目标测试 | 结果 (RED) | 退出码 |
| :--- | :--- | :--- | :--- | :--- |
| **Mutant 1** | 绕过统筹者批准行验证 (`ok=True`) | `test_verify_mode` | **PASS (RED)** | 1 |
| **Mutant 2** | 使用全局未重置的截止时间 (共享截止时间) | `test_fake_clock_full_schedule_rehearsal` | **PASS (RED)** | 1 |
| **Mutant 3** | 移除台账防重复训练检查 (`if False:`) | `test_duplicate_training_rejected` | **PASS (RED)** | 1 |
| **Mutant 4** | 禁用 final 分区 `.read_once` 标记写入 | `test_final_eval_read_once` | **PASS (RED)** | 1 |
| **Mutant 5** | 预检拒绝前向台账注入垃圾数据 | `test_preflight_refusal_leaves_ledger_sha_unchanged` | **PASS (RED)** | 4 |
| **Mutant 6** (新) | 生产评测 Runner 返回写死的伪指标值 | `test_production_eval_runner_computes_real_metrics_on_synthetic_data` | **PASS (RED)** | 1 |

---

## 4. E1 与 S1 架构对比 (Comparison with S1)

| 维度 | S1 (Stage A/B 历史实现) | E1 (本项目 Phase 2 实现) |
| :--- | :--- | :--- |
| **入口组织** | 分散的独立脚本 (`train.py`, `eval.py`)，各自持有不同参数与文件操作 | 统一中央 CLI: `ainerzero e1-phase2 <mode>`，单一调度规范 |
| **中央台账** | 每次运行新建轻量 SQLite，缺乏跨单元防重状态查询 | 共享中央 SQLite RunStore (`spec.REGISTERED_HOST_LEDGER`)，完整记录各单元状态 |
| **只读预检** | 打开数据库写连接后再校验参数，校验失败可能残留 `aborted` 脏记录 | 纯只读预检（内存快照或 SHA 核对），未批准/参数错误**绝不打开或修改台账** |
| **预算重置** | 全局统一超时，多单元串行时后序任务易被前序时间拖垮 | 严格按单元独立设定截止时间与预算上限 (`cell_deadline = t0 + budget`) |
| **防重保障** | 依赖手工文件路径规避 | 台账原子检索 + 目录标记双重校验，严格拦截重复训练与二次访问 final |
| **硬件与电源守卫** | 无电源策略与盖子感知 | 遵循 `R20261028-battery-policy`，记录电源与盒盖状态但不因电池拒绝 |

---

## 5. 测试套件完整性

- `tests/test_e1_entry.py`: **11 passed in 2.33s**
- `tests/test_e1*.py` (全量 E1 套件): **82 passed in 5.06s**
  - `test_e1_arms_net.py`: 9 passed
  - `test_e1_arms_nonnet.py`: 11 passed
  - `test_e1_entry.py`: 11 passed
  - `test_e1_export.py`: 8 passed
  - `test_e1_metrics.py`: 16 passed
  - `test_e1_prereg.py`: 14 passed
  - `test_e1_prior.py`: 13 passed

---

## 6. 约束与承诺履行说明

- **零真实训练 (Zero Real Training)**: 本任务全程未启动任何真实 MLX 训练，未下载任何模型，未调用任何外部付费 API。
- **纯 CPU 执行 (Pure CPU Device)**: 所有单测均基于 NumPy 与 MLX CPU 后端执行，无任何 GPU 资源占用。
- **Git 完整性**: 未进行任何 `git commit` 或 `git push` 操作。
