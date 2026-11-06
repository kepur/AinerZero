# S2 规划器目标编码缓存非作者独立复核报告（ainerzero.V9.P119）

自证声明：复核者 `gemini-w4x2`（独立二级执行 agent）自证非 `ainerzero.V9.P118` 作者 `gemini-f8a2`，亦非其同会话别名；本次复核执行只读审计与探针对账，绝不修改受测源码或测试。

结论：**RECOMMEND_ACCEPT_SCOPED**（限范围采纳，实现代码完全达标，指出分层多决策单测盲区供后续补齐）

---

## 1. 范围与受控工作树独立核实
- **受版本控制代码核对**：执行 `git diff HEAD -- src/` 输出完全为空，受版本控制的既有 `src/` 源码逐字节一致；
- **新文件范围**：`git status --porcelain src/` 仅出现卡面所属的 `src/ainerzero/v9/experiments/s2/` 目录；
- **P118 变更范围**：对比 P118 补丁（`git_diff.patch`），改动严格限制于：
  - `src/ainerzero/v9/experiments/s2/fwd_counter.py`
  - `src/ainerzero/v9/experiments/s2/planner.py`
  - `tests/v9/experiments/test_s2_planner.py`
  其他文件均未受任何非授权修改。

---

## 2. 缓存语义独立探针对账
复核者自行编写并运行探针脚本（`reports/V9-S2-P118/review/reconciliation_probe.py`），独立跑 2 个回合、每回合 3 次决策，对 Flat CEM 与 分层 CEM 分别进行了全流程逐项对账：

### (1) Flat CEM 对账表
| 回合 | 决策序号 | 观察编码计费 | 目标编码计费 | 目标缓存状态 | `encode` 总计 | `predict_l1` | 校验结果 |
|---|---|---|---|---|---|---|---|
| Ep 1 | 决策 1 | 1 | 1（首次求值） | Cache Miss | 2 | 4 | **对账完全一致** |
| Ep 1 | 决策 2 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | **对账完全一致** |
| Ep 1 | 决策 3 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | **对账完全一致** |
| Ep 2 | 决策 1 | 1 | 1（换回合清空首调） | Cache Miss | 2 | 4 | **对账完全一致** |
| Ep 2 | 决策 2 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | **对账完全一致** |
| Ep 2 | 决策 3 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | **对账完全一致** |

### (2) 分层 CEM 对账表
| 回合 | 决策序号 | 观察编码计费 | 目标编码计费 | 目标缓存状态 | `encode` 总计 | `encode_l2` | `predict_l1` | `predict_l2` | 校验结果 |
|---|---|---|---|---|---|---|---|---|---|
| Ep 1 | 决策 1 | 1 | 1（首次求值） | Cache Miss | 2 | 4 | 4 | 3 | **对账完全一致** |
| Ep 1 | 决策 2 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | 4 | 3 | **对账完全一致** |
| Ep 1 | 决策 3 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | 4 | 3 | **对账完全一致** |
| Ep 2 | 决策 1 | 1 | 1（换回合清空首调） | Cache Miss | 2 | 4 | 4 | 3 | **对账完全一致** |
| Ep 2 | 决策 2 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | 4 | 3 | **对账完全一致** |
| Ep 2 | 决策 3 | 1 | 0（缓存命中） | Cache Hit | 1 | 4 | 4 | 3 | **对账完全一致** |

### (3) 同回合换目标观察报错核实
- Flat CEM：同回合在第 2 次决策更换目标观察，正确抛出 `ValueError: goal observation changed within the same episode...`；
- 分层 CEM：同回合在第 2 次决策更换目标观察，正确抛出 `ValueError: goal observation changed within the same episode...`。

---

## 3. 原有测试没有被放宽
逐条审查 `tests/v9/experiments/test_s2_planner.py` 中的全部测试：
1. **原 8 项测试断言比对**：
   - `test_forward_count_closed_form_and_encoder_itemized`：闭式计数 `expected_encode = 2`、`expected_predict = 60`、`expected_total = 62`，断言逐项保持不变；
   - `test_budget_exceeded_by_one_raises`：硬预算超出 1 抛错逻辑完全保留；
   - `test_anti_cheat_encoder_nested_predict_is_visible`：内嵌调用计数防作弊断言一处没动；
   - `test_flat_near_goal_success_rate`：近目标成功率下限 `>= NEAR_SUCCESS_FLOOR`（0.80）保持不变；
   - `test_flat_reproducible_with_explicit_rng`：随机数生成器复现性断言保持不变；
   - `test_hierarchical_lower_cost_goes_through_e2`：经 $E_2$ 编码评价与调用计数断言保持不变；
   - `test_hierarchical_far_goal_vs_flat_same_budget`：远目标对比断言保持不变；
   - `test_no_mlx_import_in_s2_modules`：源码 MLX 导入检测保持不变。
2. **新增 2 项测试**：
   - `test_goal_embedding_cached_across_decisions_in_episode`：同回合首决策计 2、后续决策计 1，换回合重新计 2；
   - `test_goal_embedding_changed_goal_in_same_episode_raises`：同回合换目标捕获 `ValueError`。
全套 10 项单测在前台 100% 通过（10 passed in 3.13s）。

---

## 4. 测试真伪与 SIGReg 阈值来源核查
- **真实调用**：单测直接调用 `fwd_counter.py` 与 `planner.py` 中的类与函数，不存在测试内重写算法或常数对比常数的虚假用例；
- **SIGReg 阈值来源说明**：
  - 本交付（P118）属于 S2 规划器与计数器补充，代码与测试内**不包含 SIGReg**（卡面通用核查项在当前卡不适用）；
  - 经独立核对 S2 基础数理包 `src/ainerzero/v9/experiments/s2/core_math.py`：SIGReg 期望通过样本量 $N$ 由各向同性标准高斯解析积分闭式推导：
    $$\mathbb{E}[\text{SIGReg}(Z_{\text{iso}})] = \frac{1}{N} \sum_k W_k (1 - e^{-t_k^2}) = \frac{C_{\text{theory}}}{N}$$
    测试阈值严格设定为理论期望的 3 倍（`3.0 * E[SIGReg(Z_iso)]`），非人工经验调参。

---

## 5. 复核者自做 5 处对抗变异（均在作者变异表外）
在完全隔离的副本目录（`reports/V9-S2-P118/review/run_review_mutations.py`）中执行变异，断言 import 解析至副本，每处测试完成后严格以 SHA256 逐字节还原验证：

| 变异 ID | 变异位置与内容 | 目标测试 | 实测结果 | 变异分析与定性 |
|---|---|---|---|---|
| **REV-M1** | **分层 CEM 绕过缓存**：`planner.py:317` 分层规划将 `z1_goal = counter.goal_embedding(...)` 改为直接调用 `encode(goal_obs)` | `test_goal_embedding_cached_across_decisions_in_episode` | **SURVIVED (exit 0)** | **单测覆盖盲区（测试漏洞）**：作者新增的缓存测试仅针对 `flat_cem_plan` 调用，未对 `hierarchical_cem_plan` 执行跨决策多步断言；虽然生产源码已正确实现并被复核探针验证，但原测试未能阻击该变异。 |
| **REV-M2** | **`reset()` 错误清空回合缓存**：`fwd_counter.py` 在 `reset()` 时清空 `_goal_cache` 与 `_goal_sha` | `test_goal_embedding_cached_across_decisions_in_episode` | **RED (exit 1)** | **有效捕获**（决策 2 重算目标导致 `encode` 次数为 2，断言失败）。 |
| **REV-M3** | **目标 SHA 硬编码常数**：`fwd_counter.py` 将 `sha` 固定为硬编码常数，不随输入变化 | `test_goal_embedding_changed_goal_in_same_episode_raises` | **RED (exit 1)** | **有效捕获**（换目标后 SHA 命中，未抛出 `ValueError`，用例失败）。 |
| **REV-M4** | **Flat CEM 绕过缓存**：`planner.py:203` 将 `z_goal = counter.goal_embedding(...)` 改为直接调用 `encode(goal_obs)` | `test_goal_embedding_cached_across_decisions_in_episode` | **RED (exit 1)** | **有效捕获**（决策 2 重复调用 `encode`，断言失败）。 |
| **REV-M5** | **首次调用脱壳偷漏计数**：`fwd_counter.py` 首调使用 `encode.__wrapped__` 绕过计数包装 | `test_goal_embedding_cached_across_decisions_in_episode` | **RED (exit 1)** | **有效捕获**（首决策 `encode` 少记 1 次，断言失败）。 |

---

## 6. 纯 CPU 与全量回归测试计数
1. **纯 CPU 零导入验证**：
   在 `-I` 隔离子进程中导入 `ainerzero.v9.experiments.s2` 所有模块（`fwd_counter`、`planner`、`core_math`、`data`、`world`），断言 `sys.modules` 中不包含任何 `mlx` 相关模块，验证通过；
2. **全量前台回归测试（SIG_DFL）**：
   - 收集总数：3482 项（6 deselected，3476 selected）；
   - 测试通过：**3474 passed**；
   - 失败：2 项（`test_gridlab_s06.py::test_not_wired_into_training` 与 `test_gridlab_s07.py::test_not_wired_into_training`，原因是既有未跟踪的 S2 world 实现包含 `gridlab` 关键字，属于 P111/P117 世界环境范围，与 P118 规划器改动完全无关）；
   - S2 规划器套件：`tests/v9/experiments/test_s2_planner.py` **10 passed in 3.13s**（100% 通过）。

---

## 7. 采纳范围与统筹建议（SCOPED 说明）
- **采纳范围**：
  - `ForwardCounter` 回合缓存设计与实现完全正确；
  - `flat_cem_plan` 与 `hierarchical_cem_plan` 目标编码接入完全达标；
  - 探针对账 100% 吻合，无超支、无泄露；
- **后续优化建议**：
  建议统筹在后续 S2 集成或单测重构任务中，在 `test_s2_planner.py` 中为 `hierarchical_cem_plan` 补充显式的多决策缓存单测（类似于已实现的 Flat 测试），以闭合本次 REV-M1 揭示的单测覆盖盲区。
