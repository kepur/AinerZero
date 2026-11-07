本人 gemini-7k2q 自证非 ainerzero.V9.P148 之作者（原作者 gemini-w4x2 / gemini-r7m2 / gemini-m8d2），亦非作者之同会话别名，且非排除代理 gemini-a5b8，全程独立纯 CPU 核验证据。

# S2 接线收尾非作者独立复核报告（ainerzero.V9.P149）

- **复核代理**：`gemini-7k2q`（二级执行 Agent）· 纯 CPU（零 MLX 运行，零 GPU 占用）
- **复核对象**：`ainerzero.V9.P148` r3（作者：`gemini-m8d2`）
- **复核依据**：`reports/V9-S2-DESIGN/DESIGN-r2.md` §5、§6、附录 A、附录 B（r2.3）以及任务参数 v1、一级 Claude 通知（#775、#778）
- **最终结论**：**`RECOMMEND_ACCEPT`**

---

## 1. 独立核实摘要与 r2_review_focus 五点对照

| # | 核验项 / 关注点 | 规定标准 | 独立复核实测结论 | 状态 |
|---|---|---|---|:---:|
| 1 | **无写死/常数指标** | `smoke.py` 及调用链无写死耗时、指标或通过值；缺实测只判失败并说明缺项 | 源码静态 AST 与执行审计：`measure_real_smoke` 中彻底移除所有常数指标；第 3/4 步标记 `status="not_implemented"`，smoke 必定判 `failed` 并提示「短训健全性与可行性熔断待 P152 实现」；未注入实测时 fail-closed 逐项点名缺项 | **PASS** |
| 2 | **真实 Runner 接线** | `commands.py` 的 smoke runner 真实组装传入实测，MLX 模块在函数内懒加载 | `_resolve_default_runner` 延迟引入 `smoke.run_smoke(execute_real=True)`；顶层无任何 MLX 导入；`-I` 子进程导入 `s2`、`commands`、`smoke` 后 `mlx` 不在 `sys.modules` | **PASS** |
| 3 | **预算实测核算** | `budget_analysis.sufficient` 由实测数字核算，超预算判 False 并使 smoke 失败 | 手写独立假臂，在超预算场景下（实测总用时 29640s > 设定预算上限 25000s）实测：`sufficient` 严格判定为 `False`，smoke 判 `failed` 并点名超额原因 | **PASS** |
| 4 | **P148-M5 变异红** | 恢复默认数字用例精准变红 | 隔离沙盒中将 `measure_real_smoke` 塞回常数指标，`test_smoke_step3_step4_unimplemented_must_fail` 精准报错红（exit code 1, KILLED），还原后 SHA-256 逐字节一致 | **PASS** |
| 5 | **纯 CPU 全量回归** | 不运行 MLX，默认全量纯 CPU 运行，0 failed | 全量回归 3596 passed / 0 failed / 6 deselected（355.42s），退出码 0；80929 处 artifacts stat 审计 0 差异；S2 纯 CPU 单测 162 项全部 0 失败通过 | **PASS** |

---

## 2. 详细独立验证记录

### 2.1 范围与代码一致性
- `git status` 与 `git diff --name-only HEAD src/` 核对：
  - `src/` 目录下仅 `src/ainerzero/cli.py` 补充了 `s2-phase1` 子命令接入（包含 verify/smoke/generate-data/train/plan-select/dev-eval/final-eval 等必要参数）；
  - `src/` 下其余文件与 HEAD 逐字节一致，无任何未登记代码变动；
  - P148 卡面登记的新增/修改文件（`adapters_mlx.py`, `smoke.py`, `commands.py`, `test_s2_wiring.py`, `test_s2_adapters_mlx_native.py`, `tests/conftest.py`）SHA-256 均已校验并记录。

### 2.2 接线、verify 模式与 ForwardCounter
- **模式调度**：
  - `verify`：只读核验，无任何写操作。
  - `generate-data`, `train`, `plan-select`, `dev-eval`, `final-eval`, `smoke`：统一在 `s2_phase1_command` 中执行，前置依次通过：
    1. 协调员批准行扫描预检（`_check_approval_preflight`，匹配 `APPROVAL_SECTION`）；
    2. 防重入防重复执行校验（`worker.check_cell_already_completed`）；
    3. 单格预算及 10 小时总预算上限校验（`_check_phase_budget_ceiling`）；
    4. 获取中央共享锁 `worker_lock(paths["lock"])` 后，在 `worker.execute_work_cell` 内调用对应 runner。
- **verify 篡改自测（临时伪造仓库）**：
  - 在临时隔离目录生成冻结 `prereg.json` 与对应 `prereg.json.sha256`；
  - 篡改 `src/ainerzero/v9/experiments/s2/spec.py` 的 digest 为全零并更新文档哈希；
  - 执行 `s2_phase1_command(mode='verify')`：返回退出码 1，`stage="identity_mismatch"`，并明确点名差异文件 `src/ainerzero/v9/experiments/s2/spec.py`。
- **ForwardCounter 前向计数审计**：
  - `MLXArmAAdapter`：`encode`（charge "encode", 1）、`predict_l1`（charge "predict_l1", 1）、`cost_fn`（charge "decode", 1）；
  - `MLXArmBAdapter`：`encode`（charge "encode", 1）、`predict_l1`（charge "predict_l1", 1）；
  - `MLXArmCAdapter`：`encode`（charge "encode", 1）、`predict_l1`（charge "predict_l1", 1）、`encode_l2`（charge "encode_l2", 1）、`predict_l2`（charge "predict_l2", 1）；
  - 决策期所有网络函数求值均严格接入 `ForwardCounter`，代码审计确认无遗漏，且纯 CPU 复核未执行任何 MLX。

### 2.3 Smoke 判定、手算与种子隔离
- **4 种失败情形 + 1 种正常情形判定**（复核者独立手写假臂数据测试）：
  1. 正常情形：`delta_sigreg = -0.05 < 0`，`action_sensitivity = 0.12 >= 0.05`，`subgoal_shuffle_drop = 0.18 >= 0.10`，成功率均 `>= 0.05` $\implies$ `passed = True`。
  2. 失败情形 1（SIGReg 不降）：`delta_sigreg = 0.01 >= 0` $\implies$ 判定失败，原因准确记录。
  3. 失败情形 2（动作不敏感）：`action_sensitivity = 0.02 < 0.05` $\implies$ 判定失败，原因准确记录。
  4. 失败情形 3（子目标打乱降幅不足）：`subgoal_shuffle_drop = 0.04 < 0.10` $\implies$ 判定失败，原因准确记录。
  5. 失败情形 4（熔断触发）：所有臂长目标成功率均 `< 0.05` $\implies$ `circuit_breaker = True`，判定失败。
- **手算训练步数规则**：
  - 设定各臂单步耗时：A 臂 0.02s，B 臂 0.03s，C 臂 0.05s；有效预算 $1200 \times 0.8 = 960$s；
  - 手算：A 臂 $\lfloor 960 / 0.02 \rfloor = 48000$ 步，B 臂 $\lfloor 960 / 0.03 \rfloor = 32000$ 步，C 臂 $\lfloor 960 / 0.05 \rfloor = 19200$ 步；
  - 三臂取最小值共用：$\min(48000, 32000, 19200) = 19200$ 步；
  - `smoke.compute_training_steps` 代码实算结果与手算完全一致（19200）。
- **种子命名空间无重叠**：
  - 传入含 `train`、`dev`、`final`、`sealed_final` 的命名空间均被 `check_smoke_seed_namespace` 拦截并抛出 `ValueError`。

### 2.4 测试真伪核查
- 对 `tests/v9/experiments/test_s2_wiring.py` 中全部 16 项单测进行 AST 调用树与内容核查：
  - 均真实调用被测模块（`commands.s2_phase1_command`、`smoke.run_smoke`、`smoke.check_smoke_preconditions`、`smoke.compute_training_steps` 等）；
  - 无在单测中重写实现逻辑或常数自比断言。

### 2.5 复核者独立变异测试（5/5 全部红杀）
在隔离沙盒中（断言 `ainerzero` 模块导入路径指向沙盒，每处变异跑完按字节恢复并校验 SHA-256）：
1. **P148-M5**（恢复常数默认）：将 `measure_real_smoke` 中 `not_implemented` 替换回常数指标 $\implies$ `test_smoke_step3_step4_unimplemented_must_fail` 变红失败（exit code 1，KILLED）。
2. **REV-M1**（放宽种子命名空间检查）：将 `check_smoke_seed_namespace` 中的 `raise ValueError` 改为 `pass` $\implies$ `test_smoke_seed_namespace_rejects_overlapping` 变红失败（exit code 1，KILLED）。
3. **REV-M2**（篡改计时批次尺寸）：将 `make_smoke_timing_batch` 的 `batch_size` 默认值 32 改为 16 $\implies$ `test_smoke_batch_shape_registered` 变红失败（exit code 1，KILLED）。
4. **REV-M3**（破坏 smoke runner 调度）：将 `_resolve_default_runner` 在 smoke 模式下的返回值篡改为 `None` $\implies$ `test_commands_dispatch_to_runners` 变红失败（exit code 1，KILLED）。
5. **REV-M4**（破坏预算判定）：将 `check_smoke_budget` 的 `sufficient` 强制设为 `True` $\implies$ `test_smoke_over_budget_fails` 变红失败（exit code 1，KILLED）。

全部 5 处变异全部变红（KILLED），还原后哈希校验 100% 一致。

### 2.6 纯 CPU 与环境全量回归
- `-I` 子进程导入验证：`python3 -I -c "from ainerzero.v9.experiments.s2 import commands, smoke; import sys; assert 'mlx' not in sys.modules"` 执行通过，无 MLX 导入泄漏。
- S2 纯 CPU 专属测试：162 项全部通过（162 passed, 0 failed）。
- 全量回归测试：全量 3602 collected / 3596 selected / 6 deselected，实跑结果 3596 passed / 0 failed（用时 355.42s），退出码 0；80929 项真实 artifact stat 审计差异数严格为 0。

---

## 3. 验收建议与后续说明

基于以上逐项实测，确认 P148 r3 已彻底清除之前 r1、r2 的硬编码与常数伪造问题，严格落实了 DESIGN-r2.md 附录 B（r2.3）的设计收敛，五项关注点全部实测闭环。

**建议统筹与一级协调员：`RECOMMEND_ACCEPT`。**
