# 非作者独立复核报告：S2 生产路径集成 W5（P171）

- **复核任务 ID：** `ainerzero.V9.P172`
- **被复核任务：** `ainerzero.V9.P171`（规划协议 r2.6 与批量化推演，设计稿附录 E）
- **被复核作者：** `gemini-7k2q`（会话 `sess-1b76bd83a8ad`）
- **复核 Agent：** `gemini-8f4b`（二级执行层，会话 `sess-4bc4b7ff4dc0`）
- **复核自证：** 本复核员非被验任务 `ainerzero.V9.P171` 的作者或同会话别名（排除名单 `gemini-7k2q`，本员为 `gemini-8f4b`），独立只读核查，无任何主观偏差。
- **复核结论：** **RECOMMEND_ACCEPT**（推荐验收）
- **复核日期：** 2026-11-07

---

## 一、复核综述与权威结论

本复核员对 S2 生产路径集成 W5（P171）进行了严格、独立的六项权威核查：
1. **范围审计（Scope Audit）**：严格限制在卡面允许的 7 个文件内，源码 `src/` 仅修改规划器与适配器批量扩展，`spec.py` 仅在末尾追加协议常量，无任何越权改动；
2. **回退清零审计（Fallback Audit）**：对改动模块逐行审查，所有缺数据路径严格报错或拒绝，零静默默认值，零业务回退；
3. **生产调用链审计（Production Chain Audit）**：从 `cli.main` 跟踪到 `commands.py` 与 `learned_planning.py`，确认规划器按 r2.6 协议严格使用实测量，`commands.py` 中尚未更新的调用点呈安全拒绝态（抛 `TypeError`）；
4. **隔离沙箱变异测试（Adversarial Bad Controls）**：在独立沙箱 `/tmp/s2_w5_sandbox` 中完成 5 处变异（4 处卡面坏对照 + 1 处自选变异），**100% 成功击杀（RED）**，还原后 SHA256 逐位一致；
5. **全量回归与资产零改动（Full Suite & Artifacts Audit）**：前台跑默认全量 pure-CPU 套件（SIG_DFL 配置），**3688 passed, 6 deselected**（0 failed）；前后对实盘 `artifacts/` 全部 **84,250 个条目**进行 `lstat`（含 ctime、mtime、size、ino）严格比对，**差异为 0**；
6. **逐字抽查（Verbatim Cross-Check）**：从交付报告中抽取 3 处核心声明，与盘上代码逐字比对，100% 真实吻合。

综上，W5 实现质量优异，协议与批量化完备可靠，**建议统筹予以验收通过（RECOMMEND_ACCEPT）**。

---

## 二、六项核验逐项证据

### 1. 范围审计（Scope & Git Status Audit）
核查卡面允许范围：
- `src/ainerzero/v9/experiments/s2/planner.py`
- `src/ainerzero/v9/experiments/s2/learned_planning.py`
- `src/ainerzero/v9/experiments/s2/adapters_mlx.py`（仅扩展批量输入，单元素行为不变）
- `src/ainerzero/v9/experiments/s2/spec.py`（仅在末尾追加协议常量）
- `tests/v9/experiments/test_s2_planner.py`
- `tests/v9/experiments/test_s2_learned_planning.py`
- `tests/v9/experiments/test_s2_learned_planning_native.py`
- `reports/V9-S2-W5/`

实盘 `git status` 确认：被改动的 tracked 文件仅为上述 7 个文件。
工作树中其他 untracked 文件均为前序历史实验记录与比对产物（如 `reports/V9-S2-W1/`、`reports/V9-S2-W2/` 等），无任何外部污染。

### 2. 回退清零审计（Fallback Audit）
在改动模块中全文 grep 敏感模式：
- `or []`、`or {}`：改动模块中零新增。
- `getattr(..., 默认值)`：
  - `planner.py` 行 210、315：`mode = cost_mode if cost_mode is not None else getattr(config, "cost_mode", "trajectory_sum")`（从冻结配置对象读取字段）。
  - `learned_planning.py` 行 212、216：`if not callable(getattr(model, name, None)): raise TypeError(...)`（严格类型与能力校验，缺失报错）。
  - `adapters_mlx.py`：惰性模块代理及计数器检测，无业务兜底。
- `if ... is None else`：
  - `learned_planning.py` 行 48：`dist = spec.K_DISTRIBUTION if distribution is None else distribution`（使用冻结 spec 常量）。
- `0.5`：
  - `planner.py`：`mean = 0.5 * (low + high)`（CEM 区间中点数学定义）。
  - `spec.py`：`K_DISTRIBUTION` 泊松混合权重、`NON_BFS_RATIO_MIN` 等规格常量，非未决回退。
- `base_success_rate`、`preferred_`、`eval_episode`：0 处命中。
审计结果：完全符合 fail-closed 规范，无静默兜底。

### 3. 生产调用链审计（Production Chain Audit）
- 从 `cli.py:main` 调度至 `commands.py`：
  - `commands.py` 内部 `_plan_select_runner`、`_dev_eval_runner`、`_final_eval_runner`（第 395、412、432 行）以旧签名调用 `load_trained_models_for_planning(output_root)`，未传 `seed`，若触发会直接抛出 `TypeError`，属于安全失败态（这部分调用点归 W3/P168 改装，W5 遵守禁碰范围未做改动）。
  - 规划器核心 `learned_planning.make_plan_fn`：已严格集成 r2.6 协议：
    - `dts[0] = float(k)` 使用实际观测步宣告的真实 $k$；
    - 后续步使用整数众数 `spec.PLAN_FUTURE_DT_L1 = 1`；
    - 宏步后续步使用 `spec.PLAN_FUTURE_DT_L2 = 14`；
    - Flat 臂与上层 CEM 采用 `trajectory_sum`（潜空间全轨迹累积代价），下层保持终点代价；
    - 决策执行步数 `n_exec` 由 `spec.PLAN_REPLAN_EVERY_OBS_STEPS = 1` 派生，实现严格单步 MPC 重规划。

### 4. 亲手变异测试（Adversarial Bad Controls in Sandbox）
在独立沙箱目录 `/tmp/s2_w5_sandbox` 中完整复制源码并断言 import 解析至沙箱。逐一实施 5 处变异，验证测试红绿切换与 SHA 还原：

| 变异编号 | 变异目标与内容 | 关联测试用例 | 实测结果 | 击杀判定 | SHA 还原 |
|---|---|---|---|---|---|
| **W5-M1** | Flat 臂回退至终点代价 `PLAN_COST_TERMINAL` | `test_r26_closed_loop_geopose_success_rate` | 成功率 6/12，断言 `geo_ok >= 10` 失败 (exit code 1) | **KILLED** | 100% 一致 |
| **W5-M2** | 后续步 dt 回退至非整数 $E[k]=1.7$ | `test_r26_closed_loop_geopose_success_rate` | 成功率 6/12，断言 `geo_ok >= 10` 失败 (exit code 1) | **KILLED** | 100% 一致 |
| **W5-M3** | 执行步数 $n_{\text{exec}}$ 回退至 4 步开环重规划 | `test_r26_closed_loop_geopose_success_rate` | 成功率 2/12，断言 `geo_ok >= 10` 失败 (exit code 1) | **KILLED** | 100% 一致 |
| **W5-M4** | 批量推演漏计（传 `batch_size=1`） | `test_batched_vs_unbatched_consistency_flat` | `c_batched.total=26` vs `c_ref.total=290` (exit code 1) | **KILLED** | 100% 一致 |
| **W5-M5** (自选) | 后续步 dt 错误设置为 2 (`spec.PLAN_FUTURE_DT_L1 = 2`) | `test_r26_closed_loop_geopose_success_rate` | 成功率 6/12，断言 `geo_ok >= 10` 失败 (exit code 1) | **KILLED** | 100% 一致 |

5 项变异 100% 击杀，无一存活。

### 5. 全量回归与实盘资产零改动（Full Regression & Artifacts Audit）
- **前台纯 CPU 回归测试**：
  - 命令行：`python3 -m pytest tests/`（配置 SIG_DFL + execv）
  - 测试统计：**3688 passed, 6 deselected in 298.58s**（0 失败）。
- **实盘 `artifacts/` 目录审计**：
  - 测试前后对实盘 `artifacts/` 目录下全部 **84,250 个条目**进行深度递归 `lstat`（校验 mtime、ctime、size、ino）；
  - 比对差异条目数：**严格为 0**（完全只读，零写入）。

### 6. 逐字抽查（Verbatim Cross-Check）

#### 抽查点 1：协议常量登记
- **报告声明**：
  > 在 `spec.py` 追加登记常数：
  > - `PLAN_REPLAN_EVERY_OBS_STEPS = 1`
  > - `PLAN_FUTURE_DT_L1 = 1`
  > - `PLAN_FUTURE_DT_L2 = 14`
  > - `PLAN_COST_TRAJECTORY_SUM = "trajectory_sum"` 与 `PLAN_COST_TERMINAL = "terminal"`
- **盘上核对**：
  `src/ainerzero/v9/experiments/s2/spec.py` 行 292–297 源码逐字一致。
- **核验结论**：**VERIFIED (完全吻合)**。

#### 抽查点 2：规划器 dt 计算
- **报告声明**：
  > 在 `learned_planning.make_plan_fn` 中：
  > - Flat 臂预测 dts：第一步为宣告的真实 `float(k)`，后续步为 `float(spec.PLAN_FUTURE_DT_L1) = 1.0`；
  > - Hierarchical 宏步 dts：第一步为 `float(k) + float(round((s2 - 1) * E[k])) = k + 12.0`，后续步为 `float(spec.PLAN_FUTURE_DT_L2) = 14.0`；下层微步 dts 第一步为 `float(k)`，后续步为 1.0。
- **盘上核对**：
  `src/ainerzero/v9/experiments/s2/learned_planning.py` 行 243–245 及行 265–268 源码逐行比对，完全逐字实现上述公式。
- **核验结论**：**VERIFIED (完全吻合)**。

#### 抽查点 3：参考实现与一致性对照
- **报告声明**：
  > `planner.py` 保留非批量参考实现 `flat_cem_plan_reference` 与 `hierarchical_cem_plan_reference`，供测试验证行为逐位一致。
- **盘上核对**：
  `src/ainerzero/v9/experiments/s2/planner.py` 行 23 导出两函数，行 185 定义 `flat_cem_plan_reference`，行 395 定义 `hierarchical_cem_plan_reference`。测试用例 `test_batched_vs_unbatched_consistency_flat` 与 `test_batched_vs_unbatched_consistency_hierarchical` 对其进行全量逐位验证。
- **核验结论**：**VERIFIED (完全吻合)**。

---

## 三、交回产物清单

以下产物已生成并保存在 `reports/V9-S2-W5/review/`：
- `reports/V9-S2-W5/review/REVIEW.md`（本复核报告）
- `reports/V9-S2-W5/review/报告.md`（中文报告副本）
- `reports/V9-S2-W5/review/metrics.json`（机器可读指标）
- `reports/V9-S2-W5/review/指标.json`（中文指标副本）
- `reports/V9-S2-W5/review/mutation_summary.json`（5 处变异测试详细记录）
- `reports/V9-S2-W5/review/stat_comparison.json`（实盘 artifacts 84,250 项比对记录）
- `reports/V9-S2-W5/review/pytest_full.log`（3688 条全量回归日志）

**推荐结论：** **RECOMMEND_ACCEPT**。
