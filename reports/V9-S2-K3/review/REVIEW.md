# S2 共用规划器非作者独立复核报告（ainerzero.V9.P114）

自证：复核者 gemini-8m4d（独立二级执行 agent），非 ainerzero.V9.P112 作者 composer-m7k2，亦非其同会话别名。

结论：**RECOMMEND_ACCEPT**

## 1. 范围与完整性核实
- `git diff --stat HEAD -- src/` 为空，现有受版本控制的 `src/` 代码未受任何修改；
- 新增文件严格限制在卡面声明的 `src/ainerzero/v9/experiments/s2/{fwd_counter.py, planner.py}`、单测 `tests/v9/experiments/test_s2_planner.py` 及报告目录 `reports/V9-S2-K3/`；
- 所有新增文件 SHA256 与作者交回的 `sha256.json` 完全一致。

## 2. 前向计数探针独立对账
复核者自行编写外部包裹探针 `IndependentProbe`，在 `ForwardCounter` 外层独立监听每一次底层函数调用与批大小推断：
- **Flat CEM 单次决策对账**：
  - 外部探针总数：152 次（`encode`: 2, `predict_l1`: 150）
  - ForwardCounter 报数：152 次（`encode`: 2, `predict_l1`: 150）
  - 两者总数及分项 100% 逐项吻合。目标编码与当前观测编码均被严格计入。
- **分层 CEM 单次决策对账**：
  - 外部探针总数：149 次（`encode`: 2, `encode_l2`: 18, `predict_l2`: 65, `predict_l1`: 64）
  - ForwardCounter 报数：149 次（`encode`: 2, `encode_l2`: 18, `predict_l2`: 65, `predict_l1`: 64）
  - 两者总数及分项 100% 逐项吻合。目标编码、当前观测编码、下层每步经 $E_2$（`encode_l2`）重编码均被真实计费，零逃逸。

## 3. 分层下层代价经 $E_2$ 与新迷宫自测
- **代码核实**：`planner.py` 第 410–413 行严格执行 `z1_T = rollout_l1(...)`、`z2_pred = encode_l2(z1_T)`、`costs[i] = squared_distance(z2_pred, z2_subgoal)`，下层代价确实走 $E_2$，符合 DESIGN-r0 §4；
- **预算比例**：`upper_budget` 与 `lower_budget` 属于 `HierCEMConfig` 的冻结配置属性，在规划循环内不随回合与步数动态改变；
- **新迷宫自测（L-Maze，最短路 44 步，作者未测过的布局）**：
  - 布局：25×28 网格，起点 (1, 2)，终点 (25, 22)，经拐角转折最短路 44 步（$\ge 40$ 步长时域）；
  - 参数：$N_{\text{fwd}} = 5000$，5 个随机种子 [10, 20, 30, 40, 50]，单回合上限 100 步；
  - 结果：
    - Flat CEM：成功率 5/5 (100.0%)，步数 [61, 68, 72, 68, 76]；
    - Hierarchical CEM（宏跨度 $s_2=8$）：成功率 5/5 (100.0%)，步数 [63, 88, 95, 63, 96]。
  - 证明分层 CEM 与 Flat CEM 在新迷宫上均具备稳定的闭环规划推进能力。

## 4. 测试真伪与地面真实性核查
- `tests/v9/experiments/test_s2_planner.py` 中的 8 项测试均直接调用被测包中真实类与函数，未在测试中重写算法，非恒真式比较；
- 近目标成功率门槛 0.80 留有充分裕量（实际近目标测试达成 10/10 = 100%），非调参至恰好通过；
- 嵌套调用防作弊测试（`test_anti_cheat_encoder_nested_predict_is_visible`）有效防止内嵌隐蔽调用。

## 5. 复核者自做 3 处对抗变异（均在作者变异表外）
通过隔离副本（`reports/V9-S2-K3/review/run_review_mutations.py`）测试并经字节还原校验：
| 变异 ID | 变异内容 | 目标测试 | 结果 | 还原校验 |
|---|---|---|---|---|
| REV-M1 | `ForwardCounter` 超预算不抛出 `ForwardBudgetExceeded`（静默放行） | `test_budget_exceeded_by_one_raises` | **RED**（exit 1） | SHA 一致 |
| REV-M2 | 分层规划子目标损坏：将 `z2_subgoal` 设为当前状态 $z^{(2)}_0$（不推进目标） | `test_hierarchical_far_goal_vs_flat_same_budget` | **RED**（exit 1） | SHA 一致 |
| REV-M3 | Flat CEM 精英选择反转：挑选代价最大的候选者（反向优化） | `test_flat_near_goal_success_rate` | **RED**（exit 1） | SHA 一致 |

三处自做变异均被对应单测精准捕获，测试无死代码且具有足够的防御敏感度。

## 6. 纯 CPU 验证与全量测试计数
- 子进程使用 `python3 -I` 导入 `ainerzero.v9.experiments.s2` 所有模块，断言 `mlx` 零导入通过；
- 默认全量测试套件收集计数：3469 项通过（6 deselected），无回归；
- 建议统筹接受（`RECOMMEND_ACCEPT`）该任务交付。
