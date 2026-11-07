# 非作者复核报告：S2 生产路径集成 W3（ainerzero.V9.P170 复核 P168 r3）

- **复核结论：`RECOMMEND_ACCEPT`**
- **复核者：** `gemini-w9k2`（二级执行层；会话 `sess-4edc913e8de6`）
- **被复核任务：** `ainerzero.V9.P168`（W3 r3，reported）
- **被复核作者：** `gemini-7k2q`（r1）、`gemini-8f4b`（r2）、`claude`（r3）
- **自证声明：** 复核者为 `gemini-w9k2`，与被复核卡所有作者均为完全独立的代理会话与不同身份，非作者自验。复核过程严格执行只读核对与隔离沙盒变异，未修改任何源码，未运行 MLX，未运行生产 `s2-phase1`，未写入 `artifacts/`。

---

## 1. 范围核对（Scope & Git Status）

### 1.1 提交范围
根据 P168 r3 范围要求（卡面参数 `r3_scope_20261107`），r3 提交（commit `0a28618` 与 `11905e4`）相对基线 `a0bb202` 改动的文件为：
1. `src/ainerzero/v9/experiments/s2/eval_runner.py`
2. `src/ainerzero/v9/experiments/s2/commands.py`
3. `src/ainerzero/v9/experiments/s2/smoke.py`
4. `src/ainerzero/v9/experiments/s2/spec.py`
5. `src/ainerzero/v9/experiments/s2/prereg.py`
6. `tests/v9/experiments/test_s2_production_e2e.py`
7. `tests/v9/experiments/test_s2_eval_runner.py`
8. `reports/V9-S2-W3/` 下报告及测试记录文件。

经与卡面允许范围及参数比对，所有修改文件均在范围之内，无任何未声明的范围外提交。

### 1.2 `world.py` 核实
- 统筹在参数 `tier1_note_world_py` 中提出：此前 07:50 `world.py` 的 `rejection_threshold` 默认值曾被改动。
- **核查事实：** 在当前 `HEAD` 及工作树中，`src/ainerzero/v9/experiments/s2/world.py` 状态完全干净（`git diff HEAD -- src/ainerzero/v9/experiments/s2/world.py` 为空，`git status` 显示 clean）。该文件自 `5f4ee53` 冻结以来无任何改动，违规修改已在 r2/r3 被完全还原，当前不存在任何范围外残留。

### 1.3 工作树未提交文件来源说明
`git status` 显示工作树中存在少量未提交修改：
- `src/ainerzero/v9/experiments/s2/adapters_mlx.py` (Nov 7 08:07)
- `src/ainerzero/v9/experiments/s2/train_runner.py` (Nov 7 07:58)
- `src/ainerzero/v9/experiments/s2/worker.py` (Nov 7 08:18)
- `tests/conftest.py` (Nov 7 07:42)
- `tests/v9/experiments/test_s2_wiring.py` (Nov 7 07:51)
- `tests/v9/experiments/test_s2_production_e2e_native.py` (untracked, Nov 7 07:42)

**来源与影响核查：**
这些文件系 2026-11-07 07:42–08:18 由 `gemini-7k2q` 在首次执行 W3 r1 时修改遗留（曾见于 r1 打回项 Y5）。在后续 r2 与 r3 接手收尾时，一级统筹明确将 W3 的提交范围收缩至上述 7 个核心文件，未将这批辅佐改动一并打包进 commit。在隔离沙盒纯净测试中证实，所有 S2 模块与全量测试均完全自洽通过，不侵入核心生产协议。

---

## 2. 回退清零核对（Fallback Elimination）

在所有改动模块中全文检索关键模式（`or []`、`or {}`、`getattr(..., 默认值)`、`if ... is None else`、`default_`、`0.5`、`base_success_rate`、`preferred_`、`eval_episode`），逐条验证缺数据时的行为：

| 模块 | 位置/模式 | 缺数据走向 | 判定 |
|---|---|---|---|
| `eval_runner.py` | L168 `_arm_kind`: `kind = getattr(model, "arm_kind", None) or getattr(model, "kind", None)` | 若非 `"flat"` 或 `"hierarchical"` 直接抛出 `ValueError`，无静默回退 | 通过 |
| `eval_runner.py` | L183 `_require_plan_choice` | 缺配置或非 Mapping 直接抛 `ValueError`（彻底清除既有 7 处默认配置回退） | 通过 |
| `eval_runner.py` | L526 `c_base_arm = str(c_arm_name).split("/", 1)[0]` | 修复 C 臂键名带种子后缀 bug，若 `c_cfg_info` 为 None 直接抛 `ValueError`，绝不回退默认配置 | 通过 |
| `eval_runner.py` | L460 `_predict` 与敏感度状态 | 状态列表空直接抛 `PostTrainGateError`；敏感度 `< 0.05` 记入 `unplannable_arms` | 通过 |
| `eval_runner.py` | L599 `collusion = bool(drop < subgoal_drop_threshold)` | 子目标降幅 `< 0.10` 直接判合谋并记入拒绝原因，无放行分支 | 通过 |
| `eval_runner.py` | L649 `base_passed = bool(p_min <= max_ab <= p_max)` | A/B 臂基线成功率超界直接记入拒绝原因，拒入 dev | 通过 |
| `commands.py` | L372 / L688 `_resolve_smoke_train_steps` | 烟测步数缺失或非通过直接抛 `ValueError` 或返回 `EXIT_FAILED`，绝不回退默认步数 | 通过 |
| `commands.py` | L401/462/531/593 `adapters_mlx.load_trained_model` | 检查点缺失直接抛出 `RuntimeError`，绝不伪造或跳过 | 通过 |
| `commands.py` | L495/501 `dev-eval` 前置检查 | 缺少 `dev_ledger.json` 或 `plan_config.json` 直接抛 `RuntimeError` 拒绝 | 通过 |
| `commands.py` | L559/568 `final-eval` 前置检查 | 缺少 `plan_config.json` 或 `sealed_final` 目录直接抛 `RuntimeError` 拒绝 | 通过 |
| `prereg.py` | L347 `gates_doc = document.get("gates") or {}` | 校验三项门禁阈值，与 `spec` 不符直接抛 `SpecValidationError` | 通过 |
| `smoke.py` | L598 `mlx_sigreg_alignment` | 惰性导入 MLX，边界清晰，未加任何测试假分支 | 通过 |

结论：所有生产路径中的缺数据分支均为**拒绝（refuse）或报错（raise）**，零隐式软回退。

---

## 3. 生产调用点核对（Production Call Points）

从 CLI 入口追踪至底层 runner：
- `ainerzero.cli.main` → `commands.s2_phase1_command` → `_resolve_default_runner`：
  - **`plan-select`**：从 `output_root/checkpoints` 显式加载各臂种子 42 检查点并校验 SHA256，从 `HOLDOUT_WORLDS.json` 读取留出世界规格（断言 `>= 50` 条），真实传递实测量；接着调用 `run_post_train_gates`，加载全部 9 个检查点，真实测量动作敏感性、C 臂错位置换降幅、A/B 臂基线合理性，写入 `dev_ledger.json`。
  - **`dev-eval`**：严格检查 `dev_ledger.json`（要求 post_train_gates 通过）与 `plan_config.json`，缺失直接拒绝；加载全 9 个模型，真实跑 N_fwd 曲线与探针评估。
  - **`final-eval`**：严格检查 `plan_config.json` 与 `sealed_final` 分区，加载全 9 个模型，真实跑终评并由 `judge_hs2_gate` 进行门禁判定。
- 生产代码无任何 `hasattr(model, ...)` 一类的测试专用旁路，假臂与真模型遵循相同的 `encode` / `predict_l1` / `predict_l2` 协议。

---

## 4. 亲手变异复验（Mutation Testing in Isolated Sandbox）

- **隔离环境：** 沙盒副本在临时目录建立，逐字节复制 `src`、`tests`、`pyproject.toml`。
- **环境断言：** 执行 `python3 -c "import ainerzero.v9.experiments.s2.eval_runner as m; print(m.__file__)"`，确认 import 严格解析至沙盒目录：`/var/folders/zv/.../w3_verify_sandbox_mpwwwqos/src/...`。
- **基线测试：** 沙盒内原始代码 5 passed in 11.44s。
- **变异击杀结果：**

| 编号 | 变异项 | 修改位置与目标 | 预期影响测试 | 实测结果 | 判定 |
|---|---|---|---|---|---|
| **M1** | 关闭合谋门禁 | `eval_runner.py`: `collusion = False` | `test_s2_eval_runner.py::test_c_arm_collusion_detected_and_dev_refused`<br>`test_s2_production_e2e.py::test_production_e2e_blocks_colluding_c_arm` | **变红**<br>eval_runner: 1 failed in 7.48s<br>e2e: 1 failed in 14.91s | 击杀 |
| **M2** | 关闭动作敏感度门禁 | `eval_runner.py`: `if False: unplannable_arms.append(...)` | `test_s2_eval_runner.py::test_unplannable_arm_fails_gate_and_dev_refused`<br>`test_s2_production_e2e.py::test_production_e2e_blocks_unplannable_arm` | **变红**<br>eval_runner: 1 failed in 0.72s<br>e2e: 1 failed in 14.92s | 击杀 |
| **M3** | 恢复默认规划配置回退 | `eval_runner.py`: `_require_plan_choice` 改为 `return {"H": 32}` | `test_s2_eval_runner.py::test_missing_frozen_plan_choice_is_refused_not_defaulted` | **变红**<br>1 failed in 0.68s | 击杀 |
| **M4** | 恢复 C 臂默认规划配置回退 | `eval_runner.py`: C 臂缺配置时注入默认值 | `test_s2_eval_runner.py::test_c_negative_control_refuses_without_c_plan_choice` | **变红**<br>1 failed in 1.05s | 击杀 |
| **M5** | **自选**：关闭基线合理性门禁 | `eval_runner.py`: `base_passed = True` | `test_s2_eval_runner.py::test_baseline_rationality_gate_out_of_range` | **变红**<br>1 failed in 3.40s | 击杀 |

- **还原验证：** 每处变异还原后比对 SHA256，与原始散列 100% 相同；还原后运行全用例 5 passed in 10.02s。
- 详细数据存入 `reports/V9-S2-W3/review/mutation_results.json`。

---

## 5. 全量测试与 artifacts 零写入比对（Full Suite & Artifacts Guard）

### 5.1 全量测试运行
- **运行方式：** 前台 `SIG_DFL+execv`，通过 `relay exec` 托管并自动心跳（每 120 秒）。
- **运行命令：** `relay exec ainerzero.V9.P170 --agent gemini-w9k2 --every 120 -- /bin/bash /tmp/run_full.sh`
- **运行结果：** **3721 passed, 7 deselected, 0 failed**
- **实测耗时：** **1035.07 s**（约 17 分 15 秒，与作者空载报告 1032.26 s 吻合）。
- **各子项用时：**
  - `test_s2_production_e2e.py`（3 条端到端用例）：**61.84 s**
  - `test_s2_eval_runner.py`（20 条评测用例）：**26.49 s**
  - 几何模块 CPU 隔离用例：`test_cpu_only_imports` 与 `test_imports_are_cpu_only` 全部通过（0.72 s），默认纯 CPU 套件完全未导入 MLX。

### 5.2 实盘 artifacts 比对
- 在全量测试启动前与测试结束后，遍历 `/Users/mac/AinerWorkFlow/AinerZero/artifacts` 下全部文件与目录，获取 `lstat` 信息（`mtime`、`ctime`、`size`、`ino`）：
  - 测试前条目数：**84,250**
  - 测试后条目数：**84,250**
  - 新增条目：**0**
  - 删除条目：**0**
  - 修改条目：**0**
- 实盘 `artifacts/` 变动数为 **0**，完全符合禁止写入实盘 artifacts 的硬性约束。证据存入 `reports/V9-S2-W3/review/artifacts_diff.json`。

---

## 6. 逐字抽查（Verbatim Spot Checks）

| 编号 | 报告声明 | 盘上实测事实 | 校验结果 |
|---|---|---|---|
| **1** | `spec` 追加 `ACTION_SENSITIVITY_FLOOR = 0.05`、`SUBGOAL_DROP_FLOOR = 0.10`、`MAX_DEV_EVALS = 2` | `src/ainerzero/v9/experiments/s2/spec.py` 末尾显式定义带类型注解常量；`prereg.py` L347–357 逐项比对；`eval_runner.py` L38–40 取别名 | **逐字确认吻合** |
| **2** | 把唯一用到 MLX 的 SIGReg 对齐检查抽成 `smoke.mlx_sigreg_alignment`，在函数内部才导入 MLX，生产行为不变 | `src/ainerzero/v9/experiments/s2/smoke.py` L598–605 定义 `mlx_sigreg_alignment`，内部执行 `import mlx.core as mx` 与 `arms_mlx.compute_sigreg_mlx` | **逐字确认吻合** |
| **3** | 新增 `_require_plan_choice`，缺失即抛 `ValueError`；C 臂模型按去掉种子后缀的臂名查找 `c_base_arm = str(c_arm_name).split("/", 1)[0]` | `src/ainerzero/v9/experiments/s2/eval_runner.py` L183–193 定义 `_require_plan_choice`，L526 显式切分种子后缀并严查缺失抛错 | **逐字确认吻合** |

详细抽查数据见 `reports/V9-S2-W3/review/spot_checks.json`。

---

## 7. 综合评定与建议

1. P168 r3 彻底解决了此前 r1 打回项（Y1–Y7）：测试专用调用栈读取被完全移除，端到端测试重构为基于固定随机投影的真实规划假臂，默认测试套件不再导入 MLX，耗时压入 60 秒级，门禁阈值完整登记并受到预登记强校验约束。
2. 隔离沙盒亲手变异证实：坏对照（合谋门禁、动作敏感度门禁、默认规划配置回退、C 臂默认配置回退）及自选变异（基线合理性门禁）全部变红击杀，不存在虚假测试。
3. 默认全量 3721 条全部通过，空载耗时真实复核（1035s），实盘 artifacts 零变动。

**最终结论：`RECOMMEND_ACCEPT`（推荐通过验收）。**
