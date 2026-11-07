# S2 训练后两道门（P155/P156）非作者复核报告

自证声明：复核者为 `gemini-7k2q`，非被复核任务 `ainerzero.V9.P155` 作者（`gemini-k4m9`），亦非其同会话别名；本次复核为纯 CPU 独立只读复核，未修改任何生产源码或测试用例。

## 结论：RECOMMEND_ACCEPT

被复核任务 `ainerzero.V9.P155`（交付标签 P156）代码质量优秀、接口严格符合设计附录 B 规范、逻辑完备且测试扎实。建议统筹与用户直接验收通过（ACCEPT）。

---

## 独立核实详情

### 1. 改动范围与文件完整性
- 核验 `git status` 与 SHA-256，作者仅修改卡面指定文件：
  - `src/ainerzero/v9/experiments/s2/eval_runner.py`（SHA256: `b19fa70c06269d53af16cf9a02f59a658a2d86732beaa45ba9d3d73ed553ddbc`）
  - `tests/v9/experiments/test_s2_eval_runner.py`（SHA256: `8124a22fd3b135f7e1e230b943cdd99f326c6470c4d269be21b8bede0581d1a0`）
- `src/` 下其余文件与基线逐字节一致，未见越权修改。

### 2. 两道门严格限定 train 分区与参数校验
- **分区校验**：`run_post_train_gates` 中遍历传入规格，通过 `_spec_partition(spec)` 严格校验，若分区非 `"train"` 立即抛出 `PostTrainGateError`（传入 dev/final 均已验证抛出异常）。
- **参数规格**：
  - 动作敏感性门：默认 64 个状态（`n_sensitivity_states=64`），4 个动作（`n_actions=4`），阈值 `ACTION_SENSITIVITY_FLOOR = 0.05`；
  - C 臂负对照门：默认 50 个训练回合（`c_shuffle_episodes=50`），阈值 `SUBGOAL_DROP_FLOOR = 0.10`；
  - 参数与阈值与 `DESIGN-r2.md` 附录 B 严格一致。
- **打乱有效性独立检验**：
  - 独立编写测试检验 `eval_runner.py` 中 permutation 逻辑：对 50 个 episode 进行 `default_rng(20261106).permutation` 并修正固定点 `perm = (perm + 1) % n_c_eps`；
  - 实测确认生成的置换阵与原始索引严格不重合，绝非恒等置换（非恒等排列断言通过）。

### 3. dev 前置检查与账本行为
- **独立账本拦截测试**：复核者使用临时独立账本分别验证了三种场景：
  1. 账本缺失 `post_train_gates` 记录 $\implies$ `run_dev_eval` 抛出 `PostTrainGateRefused("post_train_gates record missing")`；
  2. 账本中包含动作敏感性低于 0.05 记录（`passed=False`） $\implies$ `run_dev_eval` 抛出 `PostTrainGateRefused` 并指明「不可规划」；
  3. 账本中包含子目标降幅低于 0.10 记录（`passed=False`） $\implies$ `run_dev_eval` 抛出 `PostTrainGateRefused` 并指明「合谋」。
- **原有函数兼容性**：
  - `eval_runner` 的现有功能（`run_plan_select` 选取最小算力、`run_dev_eval` 上限 2 次决策调用、`run_final_eval` 单次读取销毁凭据等）行为完全未受影响，相关测试 16 条全部通过。

### 4. 测试真伪与门限合理性
- 检查 `tests/v9/experiments/test_s2_eval_runner.py`：测试均直接实例化 fake 模型调用真实 `er.run_post_train_gates` 与 `er.run_dev_eval`，无任何测试内逻辑重写或常数比常数。
- 门限直接引用常量 `ACTION_SENSITIVITY_FLOOR`（0.05）与 `SUBGOAL_DROP_FLOOR`（0.10），无迎合测试的下调。

### 5. 复核者独立变异测试（作者变异表之外，3/3 全部 KILLED）
在独立沙箱隔离副本中执行，断言 Python import 严格指向沙箱副本，测试完成后按字节复原：
- **REV-M1**（去除 post_train 分区校验，静默放行 dev/final）：`test_post_train_gates_rejects_dev_or_final_specs` 变红拦截（KILLED, exit 1）；
- **REV-M2**（禁用动作敏感性不可规划检查 `if False:`）：`test_unplannable_arm_fails_gate_and_dev_refused` 变红拦截（KILLED, exit 1）；
- **REV-M3**（`run_dev_eval` 中门失败时不抛出 `PostTrainGateRefused`）：`test_c_arm_collusion_detected_and_dev_refused` 变红拦截（KILLED, exit 1）。

### 6. 纯 CPU 隔离与全量回归
- **纯 CPU 隔离**：使用 `-I` 子进程导入 `s2.eval_runner`, `s2.commands`, `s2.smoke`, `s2.train_runner`，检查 `sys.modules`，确认**零 MLX 模块泄漏**。
- **全量回归（前台 SIG_DFL 还原）**：
  - 命令：`.venv/bin/python -m pytest`
  - 结果：**3607 passed, 6 deselected, 0 failed**（用时 340.01s）；
  - `artifacts/` stat 审计：80,929 个条目，diff 数为 **0**。

---

## 交付文件 SHA256 清单
- `src/ainerzero/v9/experiments/s2/eval_runner.py`: `b19fa70c06269d53af16cf9a02f59a658a2d86732beaa45ba9d3d73ed553ddbc`
- `tests/v9/experiments/test_s2_eval_runner.py`: `8124a22fd3b135f7e1e230b943cdd99f326c6470c4d269be21b8bede0581d1a0`
- `reports/V9-S2-P156/review/run_mutations.py`: `e19e01fcc83c60c39db45d949171cd1d1017e3c3a845c8248a6919da66719705`
- `reports/V9-S2-P156/review/run_full_regression.py`: `da92c058834c98749b668061177041f4a117927bf8d21ec02715181dcf23eef3`
- `reports/V9-S2-P156/review/mutation_summary.json`: `9b6879b244c8b8817c354ddb954b0ddae5f20f1671fb91be05eb08357d632359`
