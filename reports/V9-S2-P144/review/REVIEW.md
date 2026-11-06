# 复核自证声明：复核者为独立二级代理 gemini-r7m2（会话 sess-ef82e69a0a5b），非被验任务 ainerzero.V9.P143 作者 composer-a7k2，亦非其同会话别名；全流程只读核对、纯 CPU 运行。

# V9.P143 S2 评测 Runner（三道闸与门判定）独立复核报告

- **复核任务**：`ainerzero.V9.P145`（二级执行 Agent · verify · code, math）
- **复核对象**：`ainerzero.V9.P143`（作者：`composer-a7k2`，产物目录：`reports/V9-S2-P144/`）
- **复核结论**：`RECOMMEND_ACCEPT`

---

## 一、修改范围核验（Scope Audit）

1. **产物清单与文件散列校验**：
   - 作者交付文件：
     - `src/ainerzero/v9/experiments/s2/eval_runner.py`（SHA256: `867c1487e193cebfd3d64e3b31a644e53323c74ab6803b29929c389f9cb03115`）
     - `tests/v9/experiments/test_s2_eval_runner.py`（SHA256: `8a5405d48c326a45c4d9965ef875a942fc21d02f1ede0ef3bb91083871967334`）
   - 核对当前工作区文件，与作者交付的 `reports/V9-S2-P144/file_shas.json` 100% 逐字节吻合。
2. **源码树洁净度审计**：
   - 经 `git status --porcelain src/` 及 `git diff HEAD --name-only src/` 审计：
     - `src/ainerzero/cli.py` 仅存在既有 56 行 S2 CLI 解析与分发段落；
     - `src/` 下其余所有受控源码与 `HEAD` 逐字节一致。

---

## 二、三道闸独立验证（Three Gates Verification）

复核者使用临时账本与临时 `RESEARCH_LOG.md` 独立实测三道闸：
1. **第一道闸（plan-select 拒 dev 规格）**：
   - 传入包含 `partition='dev'` 的规格列表调用 `run_plan_select`；
   - 结果：立即抛出 `PlanSelectError("run_plan_select refuses non-train specs...")`，拒绝渗透。
2. **第二道闸（dev 最多评估 2 次，第 3 次拒绝）**：
   - 连续调用 `run_dev_eval` 两次，账本计数正常递增至 2；
   - 第 3 次调用立即抛出 `DevEvalCapExceeded("dev eval refused: already used 2 times (cap=2)")`，严格阻断。
3. **第三道闸（final 严格双重校验与只读一次）**：
   - **仅有预登记批准行**：`find_final_eval_approval` 明确识别并抛出 `FinalEvalRefused("final-eval refused: found prereg approval only; need a separate APPROVED s2-phase1 final-eval line")`；
   - **引用块内批准行（`> APPROVED ...`）**：严格忽略并拒绝抛出 `FinalEvalRefused`；
   - **规范独立的 final 批准行**：提取通过，首次运行成功并在 `sealed_final` 目录下原子落盘 `S2_FINAL_READ_ONCE.json`（含时间戳、PID、nonce、reader 信息）；
   - **第二次读取尝试**：以 `os.O_CREAT | os.O_EXCL` 检测到标记已存在，立即抛出 `FinalEvalRefused("sealed_final already read once")`，防重跑防再调参。

---

## 三、门判定边界、探针 train-only 与前向预算超限作废

1. **H-S2 门判定三处边界实测（`judge_hs2_gate`）**：
   - **差值边界（`success_diff`，门槛 0.10）**：
     - `0.0999`：未通过（`passed=False`，reasons 点名 `success_diff 0.0999 < gate 0.10`）；
     - `0.1000`：通过（`passed=True`）。
   - **下界边界（`success_ci_lower`，门槛 > 0.0）**：
     - `0.0000`：未通过（`passed=False`，reasons 点名 `ci_lower 0.0000 is not > 0`）；
     - `0.0001`：通过（`passed=True`）。
   - **预测劣度边界（`pred_delta_ci_upper`，门槛 ≤ 1.0）**：
     - `1.0001`：未通过（`passed=False`，reasons 点名 `pred Δ CI upper 1.0001 > δ_pred 1.0`）；
     - `1.0000`：通过（`passed=True`）。
2. **探针拟合 train-only**：
   - 传入 `partition='dev'` 的潜变量 bundle，`_fit_probe_train_only` 抛出 `ValueError("probe must be fit on train latents only, got partition='dev'")`；
   - 传递给 `fit_ridge` 时明确携带 `source_partition="train"`。
3. **超 N_fwd 前向预算作废**：
   - 当模型触发 `ForwardBudgetExceeded` 时，`_episode_success_stub` 明确返回 `{"success": False, "void": True, "void_reason": "forward_budget_exceeded"}`；
   - 作废数据存入 `voided_comparisons`，从成功率计算中排除，坚决杜绝截断后照常结算。

---

## 四、测试用例真伪审查

审查 `tests/v9/experiments/test_s2_eval_runner.py`（11 项测试）：
- 测试全部直接导入并执行 `eval_runner` 核心逻辑（`run_plan_select`, `run_dev_eval`, `run_final_eval`, `judge_hs2_gate`）；
- 涉及真实文件系统 IO、原子标记排他创建、SQLite 账本持久化与正则解析；
- 无任何常数对常数或 mock 重写伪造。

---

## 五、复核者独立对抗变异实验（4 处新变异，与作者互补）

在隔离沙箱副本中进行变异测试，每处测试均在独立环境中进行，测试后按字节还原并核验 SHA256：

| 变异编号 | 变异位置与描述 | 预期拦截单测 | 测试结果 | 退出码 | 变异状态分析 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **REV-P145-M1** | `eval_runner.py:246`：平局时选择计算量更大者 (`cost > best_cost`) | `test_plan_select_tie_break_smaller_compute` | **KILLED** | exit 1 | 选中计算量较大的 H=48 代替 H=16，单测即刻变红拦截。 |
| **REV-P145-M2** | `eval_runner.py:354`：探针拟合传递 `source_partition='dev'` | `test_dev_probe_fit_uses_train_only` | **KILLED** | exit 1 | 单测断言 `source_partition == 'train'` 失败变红。 |
| **REV-P145-M3** | `eval_runner.py:316`：超出预算时不标记 `void=True` | `test_dev_voids_when_forward_budget_exceeded` | **KILLED** | exit 1 | 单测断言 `voided_comparisons` 失败变红。 |
| **REV-P145-M4** | `eval_runner.py:575`：移除 `startswith('>')` 引用块跳过逻辑 | `test_final_blockquote_approval_ignored` | **SURVIVED** | exit 0 | **防线冗余剖析**：`_FINAL_APPROVAL_RE` 正则以 `^APPROVED` 锚定行首，以 `>` 开头的引用行本身就无法匹配该正则；因此显式的 `startswith('>')` 判断构成了双重防御冗余，属于良性保护。 |

---

## 六、纯 CPU 导入与全量回归计数

1. **`-I` 子进程导入验证**：
   - 执行命令：`.venv/bin/python -I -c "import sys; from ainerzero.v9.experiments.s2 import eval_runner; assert 'mlx' not in sys.modules; print('ZERO_MLX_OK')"`
   - 结果：`ZERO_MLX_OK: eval_runner imports cleanly without mlx`。
2. **前台全量纯 CPU pytest 回归（SIG_DFL 还原）**：
   - 运行用时：269.48 秒；
   - 统计计数：**3566 passed, 6 deselected, 0 failed**（总计 3572 项，11 项新单测全部通过）；
   - 退出码：0。
3. **副作用核查**：
   - `artifacts/` 目录：**0 modified, 0 added, 0 deleted**，实盘零写入。

---

## 七、综合结论

**`RECOMMEND_ACCEPT`**

`src/ainerzero/v9/experiments/s2/eval_runner.py` 严格落实了 S2 评测设计协议（DESIGN-r2 §4/§5/§7）；三道闸逻辑无懈可击；门判定各关键边界精准敏感；探针训练隔离与预算超限作废逻辑真实完备；对抗变异全红或分析透彻；全量回归 3566 项全绿无副作用。建议予以验收。
