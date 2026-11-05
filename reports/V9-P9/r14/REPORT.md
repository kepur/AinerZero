# ainerzero.V9.P49 报告：S1 r14——入口继承已验证 run、新身份、重冻结

- 作者：一级 `claude`（用户 10-28 指示「复杂的一级自己做」）。**需要非作者复核**，见 `ainerzero.V9.P50`。作者 claude 本人及同会话别名不得复核。
- 依据：RESEARCH_LOG `## R20261028-S1-phase1-r14-budget`（用户 10-28「批准 r14（A2补跑）」）。
- 没有跑 MLX、训练或评测；没有写批准行；没有改 `src/ainerzero/runtime/`；没有对生产 output-root 调用任何入口。
- 生产台账 `artifacts/v9/s1/phase1/control.sqlite3`：开工与收尾都是 `fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`（`evidence/production-ledger-{start,end}.txt`，shasum 只读）。

## 1. 结论（≤10 行）

1. **新身份**：`s1-phase1-20261028-r14`，设为当前身份，r11–r13 保留为已登记历史。
2. **继承三格**：arm2 s0/s1、arm3 s0，来源是 r13 已完成的 run。
   - 训练入口在第一次写台账之前拒绝这三格（`inherited_cell_not_trainable`）。
   - 评测用 r13 的预登记 SHA 绑定，并逐项核对源 run_id、源实验、`params.npz` SHA，任一不符即拒绝。
   - 非继承格的绑定与全部守卫保持原样。
3. **冻结**：`artifacts/v9/s1/phase1/r14/pre_registration.json`。
   - document SHA：`e28c49cd5652fb26b09d2555189269183093f550331ef54c1d1fe8b65ec3c7a2`
   - file SHA：`14e2aeda943f134c262b227ae8c5c2f08c5b794f8eb5c88ccfdf29d607185e54`
4. **r13→r14 逐叶差异**：共 29 叶，**白名单外为 0**。
   - 9 叶在 inheritance 节之外：experiment_id、created_unix、P47 已验收的 equivariant_source 表述，以及 6 个来源绑定字段。
   - 20 叶是新增的 inheritance 节。
   - arms、evaluation、metrics、stop_rules、training_protocol、data_identity、resource_limits 七节与 r13 全等。
5. **隔离副本入口检查 10/10 通过**（`logs/entry-checks.json`）。
6. **测试**：`tests/v9` 共 966 项，963 通过，3 项失败，正好是 P38 列过的已知集合；新增 r14 测试 27 项全部通过。

## 2. 改动

| 文件 | 改动 |
|---|---|
| `spec.py` | `R14_EXPERIMENT_ID`；`R14_INHERITANCE`（源实验 r13、源预登记 file/document SHA、三格的 run_id 与 `params.npz` SHA、批准总墙钟 9000 s 及其执行方）；`INHERITANCE_BY_EXPERIMENT`（只有 r14）；`REGISTERED_EXPERIMENT_IDS` 增至四个；`CURRENT_EXPERIMENT_ID = r14` |
| `prereg.py` | `build_draft` 只为登记了继承的身份附加 `inheritance`。`validate` 失败关闭：该节必须与 spec 逐字节相等，缺失或多出都拒绝；新增结构检查 `inheritance_structure_reasons`，覆盖源实验必须是另一个已登记身份、64 位十六进制 SHA、可训练臂×种子、无重复格、32 位十六进制 run_id |
| `worker.py` | `inherited_cell(document, …)`：只信任与 spec 相等的继承节，私改的节整体不信任。train 在 arm/seed 校验之后、attempt 守卫之前拒绝继承格。新增 `_bind_for_document`：非继承格原样调用 `_bind_completed_run`；继承格先用源预登记 SHA 走同一套检查，再核 run_id、`experiment_id` 和最终 SHA。`_eval_binding_precondition` 新增 `document` 关键字，`_evaluate_arm` 改走同一个包装；评测报告的 `run_binding.inherited` 记下来源 |
| `test_s1_r14_registration.py` | 新增 27 项：身份；只有 r14 冻结继承节；spec 自洽；篡改继承节被拒；缺失或外来的继承节被拒；9 种畸形字段；只信任登记的节；继承格训练被拒且台账字节不变，对照格照常走到下一道守卫；继承绑定正例；6 种绑定坏对照（错 run、错 SHA、错源实验、错源预登记、私改文档节、篡改检查点）；非继承格绑定不变 |
| `test_s1_r12_registration.py`、`test_s1_r13_registration.py` | 只把「当前身份」断言从 r13 改为 r14（与 P38 改 r12→r13 同类），共 4 行，见 `evidence/diff-test_*.patch` |
| `test_s1_r12_ordering.py` | 坏控的源码锚点同步到新调用（多了 `document=document,` 一行）；变异语义不变，仍是把顺序守卫整体替换成空操作 |

逐文件补丁见 `evidence/diff-*.patch`，前值归档在 `before/`，前后 SHA 见 `evidence/{before,after}-sha256sums.txt`。

## 3. 必须如实说明的几件事

1. **arm3 s1 改为从头完整跑，不按提案从 1755 步续跑**（已写入 RESEARCH_LOG 落实细则第 5 条）。
   - `_train` 的检查点只存模型参数（`save_params`），没有优化器动量，也没有数据迭代器位置。续跑等于优化器热重启，和冻结协议下的连续训练不是同一轨迹，入口本身也不支持续跑。
   - 单次截止不变；总墙钟 ≤9000 s 不变。
2. **总墙钟 9000 s 不写进 `timing`**。冻结文件里的 `phase_wall_max_seconds` 仍是原登记的 14400 s，以免触动登记值的校验；9000 s 写在 `inheritance.approved_total_wall_seconds`，由 P51 的运行驱动在每次启动前强制执行。这比原登记更严。
3. **`src/ainerzero/cli.py` 的来源 SHA 也变了，但不是本卡改的**（mtime 10-26 19:55，早于本卡）。
   - 对照 r13 冻结时的版本（`816531f3…`，副本在 `reports/V9-P9/r6/evidence/pre-work-source/`），只有一个改动块：新增 teacher-benchmark / teacher-da3 两个子命令及其分发。
   - `s1-phase1` 的参数和分发没有变化，补丁见 `evidence/cli-r13-to-r14.diff`。
4. **已知失败三条，与 P38 相同**：
   - `test_s1_r7_phase_accounting.py::test_the_real_ledger_copy…`：读实时台账的旧预期；
   - 两条 geometry 的仅 CPU 导入用例：同进程导入顺序问题，单独运行时 2 passed（`evidence/pytest-tests-v9-after.txt`）。
5. **入口检查第 5 步的批准行只写在副本里**：在副本的日志中把 r13 那一行替换成 r14 的。该节只允许一行合格行，所以不能追加。仓库 RESEARCH_LOG.md 在运行前后 SHA 不变，脚本里也断言了副本路径不等于仓库路径。

## 4. 隔离副本入口检查（`harness/entry_checks.py` → `logs/entry-checks.json`）

| 检查 | 结果 |
|---|---|
| CLI verify（副本） | completed；source_binding=passed；approval=false；SHA `e28c49cd…` |
| CLI train / eval（副本，arm2 s2） | 退出码 3，`output_root_not_canonical` |
| worker train arm2 s2（副本作为宿主，未批准） | `preregistration_not_approved` |
| worker eval arm2 s2 | `eval_binding_unavailable`（写台账前拒绝） |
| worker train arm2 s0、arm2 s1、arm3 s0（副本日志临时批准 r14） | 三格都是 `inherited_cell_not_trainable` |
| 只读绑定前置（真实 r14 文档、副本台账） | arm2 s0 → `19f2d1eb…`、arm2 s1 → `7d155060…`、arm3 s0 → `403ae816…`，均为 ok；arm2 s2 与 arm4 s0 被拒 |
| 副本台账 | CLI 和 worker 每一步前后 SHA 都不变 |
| 生产台账与 eval_report | 前后不变 |

继承格不经过 eval worker：它的前置检查会通过，随后就会真的开跑评测，而本卡不允许评测。

## 5. 复跑

```
env -u PYTHONPATH .venv/bin/python -m pytest tests/v9/experiments -q -p no:cacheprovider
env -u PYTHONPATH .venv/bin/python reports/V9-P9/r14/harness/prereg_leaf_diff.py      # 写 logs/prereg-leaf-diff.json
env -u PYTHONPATH .venv/bin/python reports/V9-P9/r14/harness/entry_checks.py          # 写 logs/entry-checks.json；只在自建临时目录里跑
```

复核者复跑时，请先把 harness 复制到 `reports/V9-P50/<你的ID>/`，并把其中的 `OUT` 改到那里，否则会覆盖本卡的 logs（COORDINATION 规则 8）。
