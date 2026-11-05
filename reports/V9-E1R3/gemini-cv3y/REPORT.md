# ainerzero.V9.P75 执行报告（E1 入口 R3：数据生成 runner）

角色：executor；负责人：gemini-cv3y；时间：2026-10-29  
任务状态：reported；实验状态：completed  
任务依据：
- E1 实现计划 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` §E1 入口拆卡 R3
- AWZ E0 物理模拟生成入口（`animeworld/e0/dataset.py` 的 `E0DatasetGenerator` 与 `blender_runner.py`）
- 冻结规范 `src/ainerzero/v9/experiments/e1/export.py`（`export_sequence`、`assert_no_leakage`、`seal_final_dataset`）
- 防伪硬性规则：生产代码零写死指标、零假检查点、所有指标与 SHA 均由真实运行与真实文件产出

输入身份：
- AWZ 生成器入口：`/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/e0/dataset.py`
- AWZ 隐藏参数构建器：`/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/e0/_pure_hidden.py`（SHA-256: `bbf1f4ad7f9a87ec96c9847097c07c3d3e5fceae4c4e02c2fd2292b5d25fb9c7`）
- `src/ainerzero/v9/experiments/e1/export.py`

修改文件（严格在文件范围内）：
- 新建：`src/ainerzero/v9/experiments/e1/data_runner.py`
- 新建：`tests/test_e1_data_runner.py`
- 交付：`reports/V9-E1R3/gemini-cv3y/REPORT.md`
- 交付：`reports/V9-E1R3/gemini-cv3y/metrics.json`
- 交付：`reports/V9-E1R3/gemini-cv3y/run_bad_controls.py`
- 交付：`reports/V9-E1R3/gemini-cv3y/bad_controls_summary.json`
- 交付：`reports/V9-E1R3/gemini-cv3y/SHA256SUMS.txt`

实际执行：
- 契约单测：`.venv-ainerzero/bin/pytest tests/test_e1_data_runner.py -v`（4 项全过，Blender smoke 耗时 10.51s $\le 120$s）
- E1 模块全测：`.venv-ainerzero/bin/pytest tests/test_e1_*.py -k "not entry" -v`（90 项全过）
- 隔离变异坏对照：`python3 reports/V9-E1R3/gemini-cv3y/run_bad_controls.py`（3 项源码变异全部真实变红）
- 验证结果：纯 CPU + Blender 子进程 / 零 GPU / 零网络 / 零写死假指标。

---

## 1. 架构与流程设计

本模块彻底替换了早期草案中什么都不跑的伪 `generate-data`，构建了真实调用 AWZ 引擎、支持两族三分区配对生成、全流程脱敏防泄漏与双族密封的生成执行器：

### 1.1 `run_awz_generator_subprocess(...)`
- 驱动脚本调用：以子进程执行 AWZ 的 `.venv/bin/python`，工作目录设为 `/Users/mac/AinerWorkFlow/AnimeWorldZero`，并注入 `PYTHONPATH=python`；
- 内部调用 AWZ `E0DatasetGenerator` 的 `generate_sequence(partition, scenario_type, index, family)`；
- 原始 E0 序列落盘到指定的 `raw_dir/<family>/<partition>/<sequence_id>.json`。

### 1.2 `generate_and_export(...)`
- **Fail-Closed 预算与截止时间检查**：
  - 若 `wall_budget_s <= 0` 或 `clock() >= deadline`，立刻终止并返回 `status='stopped'`，绝对不调用任何子进程；
- **真实 E0 数据提取与 S 族适配（`adapt_s_sequence_for_export`）**：
  - 针对 AWZ 输出的 S 族原始序列，将其 `hidden_parameters` 中的机制字典（`mechanisms`）与配对键（`paired_p_world_key`）提升至 `metadata`，确保刚体提取时无非物体字段干扰；
  - 配对机制：建立 P 族序列的世界键与 `(partition, index)` 索引映射，在导出 S 族序列时通过 `paired_p_e0_data` 传入对应 P 序列；
- **训练与开发分区导出（`train` & `development`）**：
  - 逐序列执行 `export.export_sequence`；
  - 学生端写入 `data_dir/student/<family>/<partition>/<opaque_id>.json`，严格通过 `assert_no_leakage` 拦截所有禁止字段；
  - 评测端写入 `data_dir/evaluator/<family>/<partition>/<opaque_id>.json`，S 族正确记录 `mechanisms` 与配对的 P 族不透明 ID；
- **两族 Final 分区封存（`seal_final_dataset`）**：
  - P 族与 S 族的 final 分区在临时暂存目录中分别装配为 `student_final.jsonl`、`truth_final.jsonl`、`export_meta.json`；
  - 分别调用 `export.seal_final_dataset` 封存在 `data_dir/sealed_final/<family>/<digest>/` 下，设为只读；
  - 封存完成后立即递归清除暂存目录与学生/评测端未封存的 final 文件夹，确保无裸存 final 遗留。

---

## 2. 核心实验实测值

| 评测对象 / 指标项 | 规范契约 / 预期要求 | 真实测量值 | 判定 |
|---|---|---|---|
| Blender 真实 smoke 墙钟时间 | $\le 120.0\text{ s}$（6 段序列：P/S $\times$ 3 分区） | **10.51 s**（测试）/ **18.44 s**（基准） | **PASSED** |
| 导出序列数量（6 段） | P: 1/1/1, S: 1/1/1 | `P_train: 1, S_train: 1, P_dev: 1, S_dev: 1, P_final: 1, S_final: 1` | **PASSED** |
| Raw 序列 builder SHA 校验 | 等于 AWZ `_pure_hidden.py` SHA256 | `bbf1f4ad7f9a87ec96c9847097c07c3d3e5fceae4c4e02c2fd2292b5d25fb9c7` 完全一致 | **PASSED** |
| 学生端脱敏泄漏检查 | 拦截所有禁止关键词与隐藏字段 | 全部 6 段序列通过 `assert_no_leakage` | **PASSED** |
| 未封存 final 目录隔离 | 学生端与评测端不得有裸存 final | `student/*/final` 与 `evaluator/*/final` 均不存在 | **PASSED** |
| 两族 final 独立封存完整性 | P 与 S 两族均生成独立 digest 封存集 | P: `87c0381d...`, S: `6958f824...` | **PASSED** |
| 封存集单次读取通道 | 首次读取成功，二次读取拒绝 | 首次返回 `FinalReadToken`，二次抛出 `FinalPartitionSealed` | **PASSED** |
| S 族机制记录与 P 配对 | 评测端记录机制并匹配 P 族不透明 ID | `mechanisms: [{'id': 'quadratic_drag_v1', ...}]`，配对 ID 一致 | **PASSED** |
| 预算 $\le 0$ 防护 | 立即 stopped，不调用生成子进程 | `status='stopped'`, `reason='budget_exhausted_or_past_deadline'` | **PASSED** |
| 截止时间超限防护 | 立即 stopped，不调用生成子进程 | `status='stopped'`, `reason='budget_exhausted_or_past_deadline'` | **PASSED** |
| 子进程报错处理 | 抛出 `RuntimeError`，不写半成品数据 | 捕获子进程非零退出码，不创建输出目录 | **PASSED** |

---

## 3. 三项源码变异坏对照实验（隔离沙箱验证）

在独立临时沙箱中执行 `reports/V9-E1R3/gemini-cv3y/run_bad_controls.py`，证明 3 项变异在对应契约测试上全部真实变红（RED）：

```
======================================================================
RUNNING ISOLATED BAD CONTROLS FOR E1 DATA RUNNER (ainerzero.V9.P75)
======================================================================

[MUTATION] bad_control_1_only_seal_p_family: Only seal P family final partition, leaving S unsealed
Status: RED (FAILED as expected) (exit code 1)

[MUTATION] bad_control_2_skip_generator_invocation: Do not invoke generator subprocess, only attempt to export existing files
Status: RED (FAILED as expected) (exit code 1)

[MUTATION] bad_control_3_remove_budget_checks: Remove budget and deadline fail-closed checks
Status: RED (FAILED as expected) (exit code 1)

======================================================================
BAD CONTROLS SUMMARY:
[RED (FAILED as expected)] bad_control_1_only_seal_p_family: Only seal P family final partition, leaving S unsealed
[RED (FAILED as expected)] bad_control_2_skip_generator_invocation: Do not invoke generator subprocess, only attempt to export existing files
[RED (FAILED as expected)] bad_control_3_remove_budget_checks: Remove budget and deadline fail-closed checks
======================================================================
Summary written to reports/V9-E1R3/gemini-cv3y/bad_controls_summary.json
ALL 3 BAD CONTROLS VERIFIED RED.
```

### 3.1 变异 1：只封存 P 族 final，遗留 S 族未封存
- **变异文件**：沙箱中 `data_runner.py`
- **变异内容**：将 final 循环范围从 `DEFAULT_FAMILIES` 改为 `("P",)`
- **目标测试**：`tests/test_e1_data_runner.py::test_blender_smoke_generation_and_export`
- **结果**：**RED (FAILED)**；`assert "S" in sealed_info, "S family final partition must be sealed"` 失败。

### 3.2 变异 2：跳过生成器子进程，仅导出已有文件
- **变异文件**：沙箱中 `data_runner.py`
- **变异内容**：将子进程与 runner 调用替换为 `pass`
- **目标测试**：`tests/test_e1_data_runner.py::test_blender_smoke_generation_and_export`
- **结果**：**RED (FAILED)**；`assert exp_counts["P_train"] == 1` 失败（未产生原始文件，导出数为 0）。

### 3.3 变异 3：移除预算与截止时间检查
- **变异文件**：沙箱中 `data_runner.py`
- **变异内容**：将入口处的预算与截止时间判断替换为 `if False:`
- **目标测试**：`tests/test_e1_data_runner.py::test_zero_budget_immediately_stopped_without_calling_subprocess`
- **结果**：**RED (FAILED)**；在预算为 0 时依然调用生成器，触发 `pytest.fail`。

---

## 4. 结论与交付清单

1. `src/ainerzero/v9/experiments/e1/data_runner.py` 完整实现，规范驱动 AWZ 子进程，两族数据配对导出与 final 封存严密闭环；
2. `tests/test_e1_data_runner.py` 涵盖 Blender 真实 smoke 及预算/异常单测，全数通过；
3. E1 核心单测 90 项全数通过；
4. 3 项源码变异坏对照在隔离沙箱中全部实测变红。
