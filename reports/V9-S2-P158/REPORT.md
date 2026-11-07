# S2 冻结准备交付报告：附录 C 参数写入 spec 与 prereg 校验（ainerzero.V9.P158）

- **执行代理**：`gemini-8f4b`（二级执行 Agent）· 纯 CPU（零 MLX 导入，零 GPU 运行，零生产文件冻结，零批准行写入）
- **依据**：`reports/V9-S2-DESIGN/DESIGN-r2.md` 附录 C（r2.4）、`spec.py`、`prereg.py`、`freeze.py`、`identity.py`

## 1. 规范遵守与文件范围审查
- **修改文件**：
  1. `src/ainerzero/v9/experiments/s2/spec.py`：严格仅在文件末尾追加附录 C 常量，前 8721 字节逐字节不变（SHA256: `b1992a6407453c68083c0236c188dd15877bde28d90a10fa69f6ac160f5d5522`）。
  2. `src/ainerzero/v9/experiments/s2/prereg.py`：严格仅在 `build_draft` 与 `validate` 中增补新常量的写入与校验，其他函数一字未动。
  3. `tests/v9/experiments/test_s2_spec.py`：追加附录 C 常量比对与 spec 前缀哈希测试。
  4. `tests/v9/experiments/test_s2_prereg.py`：追加命名空间重名、留出比例越界、数据规模超预算 3 项篡改测试及试冻结确定性测试。
  5. `reports/V9-S2-P158/`：存放全套交付凭据与实验产物。
- **禁止项遵守**：未冻结生产文件，未写 `RESEARCH_LOG.md`，未写入 `artifacts/`，零 MLX 导入，零 git commit / push。

## 2. 附录 C 登记参数追加
在 `s2/spec.py` 末尾追加如下常量（注释写明「附录 C」）：
- `TRAIN_N_WORLDS = 1000`
- `TRAIN_EPISODES_PER_WORLD = 8`
- `TRAIN_HOLDOUT_WORLD_FRACTION = 0.10`
- `SEED_NAMESPACES = {"train": "s2p1-train-v1", "dev": "s2p1-dev-v1", "final": "s2p1-final-v1", "smoke": "s2p1-smoke-v1"}`
- `MODEL_SELECTION_EVERY_STEPS = 200`
- `SMOKE_SHORT_TRAIN_STEPS = 200`
- `TRAIN_STEPS_RULE = "floor(1200*0.8/t_min_over_arms)"`（注释注明「具体步数由 smoke 实测后记账，不入预登记」）
- `DATA_ESTIMATED_SECONDS_PER_EPISODE = 0.145`（注释注明来源 P133）

## 3. prereg draft 写入与 validate 严格校验
- `build_draft()`：在 `training` 中写入步数与模型选择参数；新增 `data` 分区，写入 train 世界数、每世界回合数、留出比例、命名空间字典与耗时估算系数。
- `validate()`：严格校验以下三点：
  1. 四个命名空间（train, dev, final, smoke）两两互不相同（pairwise distinct）；
  2. 留出比例 `train_holdout_world_fraction` 严格在 (0, 0.5) 开区间内；
  3. 训练数据规模估算（1000 × 8 × 0.145 s = 1160.0 s）≤ 数据预算 3600 s。

## 4. 临时目录试冻结与确定性核验
- **试冻结执行**：在临时目录调用 `freeze.freeze(build_draft(), out_dir=tmp)` 成功生成 `prereg.json` 与 `prereg.json.sha256`。
- **身份核对**：调用 `identity.verify_frozen_identity` 校验通过（`status: "passed"`）。
- **确定性验证**：在两个独立临时目录各冻结一次，计算得到的 `document_sha256` 均为：
  `2a2ae4ba175471c5b9b54943f752f415e97f35aca70304dbb49d72a6c56ee749`
  （两者哈希 100% 相同，确定性成立）。
- **源码清单**：共计 24 项源码摘要（含 `cli.py:s2-phase1` 与 s2 下全部 23 个 Python 模块）。
- **草稿输出**：完整草稿已保存至 `reports/V9-S2-P158/draft.json`，未写入实盘 `artifacts/`。

## 5. 坏对照对抗实验（Bad Control）
在 `/tmp/ainerzero_p158_bad_control` 隔离沙盒中运行对抗脚本：
- **P158-M1（dev 与 final 命名空间相同）**：
  - 变异：`spec.SEED_NAMESPACES['final'] = 's2p1-dev-v1'`。
  - 拦截：`test_build_draft_and_validate_clean` 触发 `SpecValidationError: Seed namespaces must be pairwise distinct`，`test_appendix_c_constants_match_design_document` 触发 `AssertionError`。
  - 状态：**RED (CONFIRMED)**（exit code 1）。
- **P158-M2（validate 去掉数据预算估算）**：
  - 变异：移除 `estimated_data_seconds > data_budget_seconds` 检查。
  - 拦截：`test_tamper_train_scale_exceeds_data_budget_fails` 预期抛出异常但未抛出，测试失败。
  - 状态：**RED (CONFIRMED)**（exit code 1）。
- **还原核验**：变异后逐字节还原，SHA256 哈希 100% 吻合。

## 6. 全量纯 CPU 回归与实盘零差异审计
- 回归统计：全套纯 CPU 回归（前台还原信号 SIG_DFL）共 **3619 collected / 6 deselected / 3613 selected / 3613 passed / 0 failed**（耗时 297.00s，exit code 0）。
- 实盘审计：测试前后对实盘 `artifacts/` 80,929 项条目审计，增删改差异数严格为 **0**。

## 7. 交付产物清单
- `reports/V9-S2-P158/`:
  - `REPORT.md` / `报告.md`：本交付报告。
  - `metrics.json` / `指标.json`：结构化指标与断言记录。
  - `draft.json`：根据新常量生成的 prereg 草稿。
  - `freeze_evidence.json`：试冻结生成的 document_sha256 与 24 项源码摘要清单。
  - `bad_control_summary.json`：坏对照对比数据。
  - `run_bad_control.py`：坏对照自动化复现与还原核验脚本。
  - `run_full_regression.py`：全量前台回归与 stat 审计脚本。
  - `generate_trial_freeze.py`：试冻结生成与确定性核验脚本。
  - `pytest_full.log`：3613 项全量回归完整标准输出日志。
  - `stat_comparison.json`：实盘 80,929 项零差异审计结果。
  - `git_diff.patch`：4 个代码与测试文件的完整补丁。
  - `sha256.json`：交付文件完整哈希表。
