# S2 冻结前清理交付报告（ainerzero.V9.P160）

- **执行代理**：`gemini-8f4b`（二级执行 Agent）· 纯 CPU（零 MLX 导入，零 GPU 运行，零生产文件冻结，零批准行写入）
- **依据**：任务 ainerzero.V9.P160 需求、`reports/V9-S2-DESIGN/DESIGN-r2.md`、S2 反捏造与防脆弱回退规范

## 1. 规范遵守与文件范围审查
- **修改文件**：
  1. `src/ainerzero/v9/experiments/s2/smoke.py`：清理所有 `getattr(spec, "X", default)`，统一引用 `spec.SMOKE_SHORT_TRAIN_STEPS`，完全停用 `SMOKE_SHORT_STEPS`。
  2. `src/ainerzero/v9/experiments/s2/smoke_checks.py`：仅改动第 390–392 行附近回合规格读取逻辑，当缺少 `bfs_distance`、`start` 或 `goal` 时直接抛出 `ValueError` 并明确指示缺失字段，严禁使用 40 作为默认值。
  3. `tests/v9/experiments/test_s2_wiring.py`：追加 AST 扫描与缺少 `SMOKE_SHORT_TRAIN_STEPS` 时的拒绝测试。
  4. `tests/v9/experiments/test_s2_smoke_checks.py`：追加缺少 `bfs_distance` 与 `start`/`goal` 时的显式拒绝单测。
  5. `reports/V9-S2-P160/`：存放全套交付凭据与实验产物。
- **禁止项遵守**：未改其他文件，未导入 MLX，未冻结生产文件，未写 `artifacts/`，零 git commit / push。

## 2. smoke.py 常量读取清理与统一
- **去掉全部 getattr 默认值**：
  - 第 42 行：`SMOKE_SHORT_TRAIN_STEPS = spec.SMOKE_SHORT_TRAIN_STEPS`
  - 第 247–249 行：`n_worlds = spec.SMOKE_N_WORLDS`, `episodes_per_world = spec.SMOKE_EPISODES_PER_WORLD`, `total_short_steps = spec.SMOKE_SHORT_TRAIN_STEPS`
  - 第 418 行：`S_steps = spec.SMOKE_SHORT_TRAIN_STEPS`
  - 第 570 行：`S_steps = spec.SMOKE_SHORT_TRAIN_STEPS`
- **常量来源统一与旧常量说明**：
  - 短训步数统一读取预登记中的 `spec.SMOKE_SHORT_TRAIN_STEPS`；
  - `smoke.py` 内部彻底停用 `SMOKE_SHORT_STEPS` 标识；
  - 根据 spec 规范（只增不删原则），`spec.py` 中的旧常量 `SMOKE_SHORT_STEPS` 维持原样保留，但在生产 smoke 流程中已无任何引用。

## 3. smoke_checks.py 回合规格缺字段严厉报错
- 回合规格字段解析段移除 `bfs_distance` 的默认值 `40`；
- 当 `bfs_distance`、`start` 或 `goal` 缺失时，精准抛出 `ValueError`：
  - `Missing start in episode spec {idx}`
  - `Missing goal in episode spec {idx}`
  - `Missing bfs_distance in episode spec {idx}`
- 杜绝因缺数据而静默回退默认距离，彻底遵守「缺数据只能判失败」的原则。

## 4. 全套 AST 扫描与单测加固
- **AST 扫描**：对 `src/ainerzero/v9/experiments/s2/` 下所有 `.py` 文件进行抽象语法树遍历，确认除 `data_runner.py`（P138 约定的过渡回退白名单）外，不存在任何 `getattr(spec, ..., <default>)` 调用。
- **删除常量拒绝测试**：`monkeypatch.delattr(spec, "SMOKE_SHORT_TRAIN_STEPS")` 情况下，`smoke.generate_smoke_partition` 与 `smoke.run_smoke` 均准确触发 `AttributeError` 阻断执行。
- **缺失字段拒绝测试**：`oracle_feasibility` 与 `oracle_feasibility_with_s2_planner` 在缺少 `bfs_distance` 时精准拦截并抛出指定错误。

## 5. 坏对照对抗实验（Bad Control）
在 `/tmp/ainerzero_p160_bad_control` 隔离沙盒中运行对抗实验：
- **P160-M1（恢复一处 getattr 默认值）**：
  - 变异：将 `smoke.py` 中的常量读取恢复为 `getattr(spec, "SMOKE_SHORT_STEPS", 200)`。
  - 拦截：`test_no_getattr_spec_with_default_in_s2_package` AST 扫描测试变红拦截（`exit_code: 1, KILLED`）。
- **P160-M2（恢复 bfs_distance 默认 40）**：
  - 变异：将 `smoke_checks.py` 中的 `bfs_dist` 读取恢复为 `int(spec_data.get("bfs_distance", 40)...)`。
  - 拦截：`test_oracle_feasibility_missing_bfs_distance_raises` 变红拦截（`exit_code: 1, KILLED`）。
- **逐字节还原核验**：变异前后 SHA256 哈希 100% 吻合。

## 6. 全量纯 CPU 回归与实盘零差异审计
- 回归用例：全套纯 CPU 回归（前台还原信号 SIG_DFL）共 **3623 collected / 6 deselected / 3617 selected / 3617 passed / 0 failed**（耗时 298.32s，exit code 0）。
- 实盘审计：测试前后对实盘 `artifacts/` 80,929 项条目 stat 审计，差异数严格为 **0**。

## 7. 交付清单
- `reports/V9-S2-P160/`:
  - `REPORT.md` / `报告.md`：本交付报告。
  - `metrics.json` / `指标.json`：结构化指标与执行记录。
  - `bad_control_summary.json`：坏对照对比数据。
  - `run_bad_control.py`：坏对照自动化复现与还原核验脚本。
  - `run_full_regression.py`：全量前台回归与 stat 审计脚本。
  - `git_diff.patch`：4 个代码与测试文件的完整补丁。
  - `pytest_full.log`：3617 项全量回归完整日志。
  - `stat_comparison.json`：实盘 80,929 项零差异审计结果。
  - `sha256.json`：交付文件完整哈希表。
