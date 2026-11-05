# ainerzero.V9.P31 执行报告

角色：executor（二级 · 非作者复核）；负责人：`composer-71f7`；时间：2026-10-23
任务状态：reported；实验状态：未执行 MLX/训练/评测/批准行
任务依据：复核 `ainerzero.V9.P30`；`RESEARCH_LOG ## R20261023-S1-phase1-r11-budget`；参数 v1（T1–T5）
输入身份：封源 `P30-review-inputs.json` sha `05b8b62c…22af`（210 项）；P30 作者 `composer-m7k2`（前棒 `step5-ub8z`）
修改文件：仅 `reports/V9-P31/`（含 harness/evidence/logs）
**自证**：本复核者 `composer-71f7` **不在**排除名单（claude、codex、composer-6bf9、composer-m7k2、step5-ub8z）。

## 结论：建议通过

P30 的 r11 方案 A 重冻结在开工封源下成立：登记值、fail-closed、推导值、新实验作用域、入口三模式（隔离+真实 verify/train）、叶差异与 tests 对账均通过。T1 记为已知注记（非否决）。收尾 review_inputs 因**本复核按卡面跑真实 CLI eval**写入生产台账而不再 210/210——一级裁定（ask #480 / answer #483）记为规格引起的复核事件，**不作为 P30 否决理由**；生产台账未再改动。

## 摘要（30 行内）

1. **开工 review_inputs**：210/210 全等；pin sha 匹配；含 `control.sqlite3=a5fd11ff…63c3`。
2. **冻结值**：updates=3510、deadline=1200（`deadline_source=user_approved…`）、supervision=1250、eval_batches=175、seeds=[0,1,2]、experiment=`s1-phase1-20261023-r11`、phase_wall_max=14400；doc `b73b5589…fb4e` / file `aeb8a7a8…f105`；r10 file `5fea3ca7…d1ff` 未变；V9-S1 metrics 未变。
3. **fail-closed**：改 deadline≠1200、缩步数、慢 smoke 会缩步 → 均拒；隔离坏控（去掉 1200 守卫）对 1150 放行而真 validate 拒绝 → 变红。
4. **推导**：独立 `registered_budget` → derived=477、arm1_deadline=7、phase_wall≈10854.6；与冻结一致；477 **不**作运行截止；最坏 9×1250=11250≤14400。训练期探针成本 r10→r11 Δ≈+4.42 s（与「约多 4–5 s」一致）。
5. **新实验**：临时库探针 arm×seed attempt 从 0；旧实验 attempt/墙钟守卫仍生效；RunStore/lifecycle 相对 pin 未改。
6. **入口**：verify completed；train exit3 `preregistration_not_approved`；eval175 过预算门后 `EvalBindingError`；48 对照 `eval_call_budget_exceeded`。T2 隔离批准+哨兵：train 抵达 `_train` 前全部门通过（approval/source_binding/dataset/deadline=1200/新实验）。
7. **T1**：r11/r10 arms 逐字节相同；文档 arm1 缺两信任根键（r8–r10 既有）；运行时 `identity._identity`→`spec.ARM_SPECS`（含两键）；无其它路径要求文档 arm1 两键 → **已知注记，不否决**。
8. **T3**：`test_the_real_ledger_copy…` 当前与 before 树均以同一方式失败（conservative 5012 ≠ reserved 2214）；不密封既有测试，非 P30 回归。
9. **T5（开工）**：主库 pin 一致且无 r11 行。**收尾**：CLI eval 写入 1 experiment + 2 failed runs（见 `evidence/ledger_pollution_incident.json`）；另 `eval_report.json` 漂移；一级令不得恢复。
10. **测试**：r11 17 passed；experiments 325 passed / 1 failed（上记）；其余 tests/v9 378 passed。全量一次跑曾因 MLX 导入污染出现 geometry cpu-only 失败，隔离复跑 2 passed（非 P30）。

## 实际执行（要点）

- `reports/V9-P31/harness/{verify_core,t2_sentinel_dryrun,entry_modes}.py`
- 真实 CLI：verify（r11 root）；train（canonical phase1 + r11 prereg）；eval（误用 canonical——污染源）+ 隔离 `entry_eval_check.py`
- pytest：`test_s1_r11_registration` / `tests/v9/experiments` / `tests/v9 --ignore=experiments`；T3 before 对照

## 产物

- 本报告、`指标.json`
- `evidence/`：review_inputs_{start,end}.json、verify_core.json、t2_sentinel_dryrun.json、entry_modes.json、ledger_pollution_incident.json、derived_costs.json、t3_ledger_numbers.json
- `logs/`：入口与测试日志

## 失败与限制

- 收尾 review_inputs **未** 210/210（control.sqlite3 + eval_report.json）；原因见一级 #483，非 P30 缺陷。
- 未写批准行；未跑 MLX/真实训练；未改源码。
- 生产台账后续处置归一级。

## 交回统筹

- **建议通过** P30；可写 r11 批准行（仍须一级执行）。
- 请一级处理生产 `control.sqlite3` 中本复核写入的 r11 三行及 `eval_report.json` 漂移。
