# ainerzero.V9.P74 执行报告（E1 入口 R2：训练 runner）

角色：executor；负责人：gemini-w7m2；时间：2026-10-29
任务状态：reported；实验状态：completed
任务依据：
- E1 实现计划 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1 入口拆卡 R2
- 预登记 r3 §2（臂表：② PureNetArm、③ PriorResidualArm、⑥ IdentifyResidualArm）
- 冻结规范 `src/ainerzero/v9/experiments/e1/spec.py`（TRAINABLE_ARM_IDS、TRAINING_SEEDS、BUDGET_CAPS）
- 防伪硬性规则：生产代码零写死指标、零假检查点、所有指标与 SHA 均由真实运行与真实文件产出
输入身份：
- `src/ainerzero/v9/experiments/e1/arms_net.py`
- `src/ainerzero/v9/experiments/e1/arms_nonnet.py`
- `src/ainerzero/v9/experiments/e1/prior.py`
- `src/ainerzero/v9/experiments/e1/spec.py`
修改文件（只改文件范围内）：
- 新建：`src/ainerzero/v9/experiments/e1/train_runner.py`
- 新建：`tests/test_e1_train_runner.py`
- 交付：`reports/V9-E1R2/gemini-w7m2/REPORT.md`
- 交付：`reports/V9-E1R2/gemini-w7m2/data.json`
- 交付：`reports/V9-E1R2/gemini-w7m2/SHA256SUMS.txt`
实际执行：
- 契约单测：`PYTHONPATH=src python3 -m pytest tests/test_e1_train_runner.py -v`（7 项全过）
- 回归全测：`PYTHONPATH=src python3 -m pytest tests/test_e1_prior.py tests/test_e1_metrics.py tests/test_e1_arms_nonnet.py tests/test_e1_arms_net.py tests/test_e1_train_runner.py -v`（56 项全过）
- 隔离变异坏对照：`python3 /tmp/run_p74_mutations.py`（4 项源码变异全部变红）
验证结果：56 passed in 3.03s，零 GPU/零网络/纯 MLX CPU。

---

## 1. 架构与实现设计

本模块彻底替换了早期草案中写假检查点的行为，构建了完全真实、确定性、受预算与占空比约束的 MLX CPU 训练执行器：

### 1.1 `build_training_windows(student_dir, K=4)`
- 严格只从学生侧序列 JSON 文件读取公开字段：`frames[t]["objects"][body_name]["position"]` 与 `["linear_velocity"]`；
- 绝不触碰任何隐藏参数（`hidden_parameters`、`family`、`world_key` 等）；
- 对每个活动物体提取长为 $K$ 帧的状态历史 $[s_{t-K+1}, \dots, s_t] \in \mathbb{R}^{K \times 6}$ 展平为 24 维输入向量；
- 目标为向后 1 帧的状态增量 $\Delta s = s_{t+1} - s_t \in \mathbb{R}^6$；
- 返回封装容器 `TrainingWindows`，同时支持字典映射（`windows["inputs"]`、`windows["targets"]`）与属性访问（`windows.inputs`、`windows.targets`）。

### 1.2 `train_cell(...)`
- **模型分派**：
  - Arm ②: `arms_net.PureNetArm(seed=seed, learning_rate=lr)`
  - Arm ③: `arms_net.PriorResidualArm(seed=seed, learning_rate=lr)`
  - Arm ⑥: `arms_net.IdentifyResidualArm(seed=seed, learning_rate=lr, identifier_fn=...)`，其中辨识回调使用 `arms_nonnet.IdentifyArm` 在前缀上执行雅可比敏感度 Levenberg-Marquardt 在线辨识；
- **白名单校验**：
  - 臂 ID 严格限制在 `spec.TRAINABLE_ARM_IDS = (2, 3, 6)`，拒绝臂 1/4/5/7；
  - 随机种子严格限制在登记种子 `spec.TRAINING_SEEDS = (42, 43, 44)`；
  - 族系严格限制在 `spec.FAMILIES = ("P", "S")`；
- **预算与截止时间防护（Fail-Closed）**：
  - 若传入计算预算 $\le 0$ 或当前时钟已过截止时间，立即返回 `status='stopped'`，绝对不调用 `model.save()`，不写任何伪文件；
  - 循环调用 `model.train_step(batch)`，每步后累计计算时长并核对预算与截止时间，一旦超额立即中断退出；
- **0.25 占空比休眠**：
  - 每次优化步计算耗时 $t_{calc}$ 后，休眠时长严格按公式计算：$t_{sleep} = (\frac{1}{0.25} - 1) \times t_{calc} = 3 \times t_{calc}$；
  - 通过可注入的 `sleep_fn` 执行，便于生产环境 pacing 与测试精确捕获；
- **真实权重持久化与 SHA 校验**：
  - 仅在正常完成全部步骤后调用 `model.save(ckpt_file)`；
  - 读取落盘权重文件的真实二进制字节流计算文件 SHA-256，与内存中 `model.parameter_sha256()` 双重返回。

---

## 2. 核心实验测量值

| 测试场景 / 指标项 | 理论 / 规范要求 | 实际测量值 | 判定 |
|---|---|---|---|
| `build_training_windows` 形状 | 输入 24 维，目标 6 维 | `inputs: (22, 24)`, `targets: (22, 6)` | **PASSED** |
| Arm ② 3 步训练完成状态 | `status='completed'`, `steps=3` | `status='completed'`, `steps_completed=3` | **PASSED** |
| Arm ② 真实权重持久化 | 文件存在且 SHA-256 与字节一致 | 文件存在，`a0d4b1ff...` 逐位匹配 | **PASSED** |
| 跨实例参数 SHA256 恢复 | 新实例 load 后 SHA 严格一致 | `7d985e0f...` 严格一致 | **PASSED** |
| 训练损失有效性 | 有限实数（`math.isfinite`） | `loss = 0.005497`（有限值） | **PASSED** |
| Arm ③ 与 Arm ⑥ 训练支持 | 均能正常完成 3 步并输出有效损失 | Arm 3 loss=0.005497, Arm 6 loss=0.005497 | **PASSED** |
| 计算预算为 0 | 立即 `stopped`，不写任何权重 | `status='stopped'`, `checkpoint_path=None` | **PASSED** |
| 截止时间已过期 | 立即 `stopped`，不写任何权重 | `status='stopped'`, `checkpoint_path=None` | **PASSED** |
| 0.25 占空比休眠比例 | 休眠时长 $\approx 3.0 \times$ 计算时长 | `sleep_time / calc_time = 3.000` | **PASSED** |
| 非训练臂 1 拒绝 | 抛出 `ValueError` | `ValueError("Arm 1 is not trainable")` | **PASSED** |
| 未登记种子 999 拒绝 | 抛出 `ValueError` | `ValueError("Seed 999 is not in registered")` | **PASSED** |

---

## 3. 四项源码变异坏对照实验（隔离副本验证）

通过 `/tmp/run_p74_mutations.py` 在独立临时目录中复制 `src/`，修改变异代码，打印加载的 `__file__`，证明 4 项变异在对应测试上全部真实变红（FAILED）：

```
======================================================================
P74 MUTATION TEST SUMMARY:
[RED (FAILED as expected)] skip_save: 去掉 save (不保存真实权重)
[RED (FAILED as expected)] skip_budget: 去掉预算检查
[RED (FAILED as expected)] skip_duty_sleep: 去掉占空比休眠
[RED (FAILED as expected)] allow_arm1: 允许臂 1 (绕过可训练臂白名单)
======================================================================
```

### 3.1 变异 1：去掉 save（不写真实权重文件）
- **变异文件**：`/tmp/iso_skip_save_*/src/ainerzero/v9/experiments/e1/train_runner.py`
- **变异内容**：将 `model.save(ckpt_file)` 注释跳过
- **目标测试**：`test_train_3_steps_saves_weights_and_loads_identical_sha[2-PureNetArm]`
- **结果**：**RED (FAILED)**
  ```
  FileNotFoundError: [Errno 2] No such file or directory: '.../model_weights.npz'
  ```

### 3.2 变异 2：去掉预算检查
- **变异文件**：`/tmp/iso_skip_budget_*/src/ainerzero/v9/experiments/e1/train_runner.py`
- **变异内容**：将 `if compute_budget_s is not None and compute_budget_s <= 0.0:` 改为 `if False and ...`
- **目标测试**：`test_train_zero_budget_or_past_deadline_stops_without_writing_weights`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: assert 1 == 0
  where 1 is res_budget["steps_completed"]
  ```

### 3.3 变异 3：去掉占空比休眠
- **变异文件**：`/tmp/iso_skip_duty_sleep_*/src/ainerzero/v9/experiments/e1/train_runner.py`
- **变异内容**：将 `actual_sleep_fn(sleep_dur)` 注释跳过
- **目标测试**：`test_duty_cycle_sleep_injection_approx_3x_compute`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: assert 0 == 4
  where 0 is len(recorded_sleeps)
  ```

### 3.4 变异 4：允许臂 1
- **变异文件**：`/tmp/iso_allow_arm1_*/src/ainerzero/v9/experiments/e1/train_runner.py`
- **变异内容**：将白名单检查 `if arm_id not in spec.TRAINABLE_ARM_IDS:` 放宽为包含臂 1
- **目标测试**：`test_rejection_of_nontrainable_arm_and_unregistered_seed`
- **结果**：**RED (FAILED)**
  ```
  AssertionError: Regex pattern 'not trainable' did not match.
  ```

---

## 4. 交付文件清单

```
src/ainerzero/v9/experiments/e1/train_runner.py
tests/test_e1_train_runner.py
reports/V9-E1R2/gemini-w7m2/REPORT.md
reports/V9-E1R2/gemini-w7m2/data.json
reports/V9-E1R2/gemini-w7m2/SHA256SUMS.txt
```

---

## 5. 交回统筹说明

- 本任务严格按拆卡 R2 规范实现真实训练 runner，所有指标由实际 MLX CPU 训练与落盘校验产生；
- 零硬编码、零假检查点；未修改已有已验收模块；未提交、未推送 git。
