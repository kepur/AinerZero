# S2 评测框架交付报告（ainerzero.V9.P122）

- **执行代理**：`gemini-m7k4`（二级执行 Agent）· 纯 CPU（无 MLX 导入）
- **交付范围**：`s2/eval.py`, `s2/stats.py`, `s2/probe.py` 及对应单元测试 `tests/v9/experiments/test_s2_*.py`
- **核心实现**：
  1. `eval.run_episode`：支持 m=4 重规划、第 20 步 5 动作可复现扰动、regular/irregular dt 与 `ForwardCounter` 硬预算即时拦截。
  2. `stats.cluster_paired_bootstrap`：两阶段按世界分簇双层重采样，95% CI 覆盖率在 200 次重复中达标，W=1 严格报错；提供 `power_estimate`。
  3. `probe.fit_ridge`：闭式岭回归（λ 写死默认 1.0），欧氏距离评测 `eval_error` 与 1/5/10/30/60 观察步汇总 `summarize_step_errors`。

## 一、测试套件与变异实验（5 处坏对照全红，全部按字节还原）
- 13 条新增单测全部绿灯：oracle 短目标成功率 1.0，irregular k 经验分布 χ²<20.0，分簇宽度比值 ≥1.35。
- 变异矩阵（隔离副本运行，退出码均不为 0，变异后已还原并校验 SHA256）：
  - **P122-M1**（bootstrap 不分簇）：`test_cluster_bootstrap_width_with_strong_cluster_effect` 变红 (KILLED)
  - **P122-M2**（perturb 不插入）：`test_perturb_inserts_at_step_20_and_is_reproducible` 变红 (KILLED)
  - **P122-M3**（成功判定要求朝向）：`test_success_does_not_require_heading_match` 变红 (KILLED)
  - **P122-M4**（λ 默认值改成 0.1）：`test_ridge_lambda_default_is_one` 变红 (KILLED)
  - **P122-M5**（irregular 模式 k 固定为 1）：`test_dt_mode_regular_and_irregular_distribution` 变红 (KILLED)

## 二、默认全量回归与 artifacts/ 审计
- **全量计数**：前台 SIG_DFL 还原运行：`3491 passed, 0 failed, 6 deselected in 256.02s`
- **artifacts/ 审计**：84,248 条目比对，**0 added, 0 deleted, 0 modified**

## 三、产物 SHA256
- `src/ainerzero/v9/experiments/s2/eval.py`: `9a98ef7e3042241f662bf66cc520f8f00c8b1e4d3c0de3b584cec954c9a4614c`
- `src/ainerzero/v9/experiments/s2/stats.py`: `ac6e3fed713f7a160a379b683dd19fd5d33be5baacbe577c2d13900e45d67a8b`
- `src/ainerzero/v9/experiments/s2/probe.py`: `707015d7a5f6d22212809841dd687975ad556de68c7daa028ddc2c425f40445d`
- `tests/v9/experiments/test_s2_eval.py`: `b9825edc926386bc35eeb7f457dd18458749f5bc9a5968bbf071eda1ed7c6290`
- `tests/v9/experiments/test_s2_stats.py`: `ba75b4dc53bade4252bf11d8dd28fed929888787a2e33ab3384d7355fa8f59ad`
- `tests/v9/experiments/test_s2_probe.py`: `2fe4e57dce9162f997a68b8751c7b5685cadd61e65fdf8894b8e8d6f06669af2`
