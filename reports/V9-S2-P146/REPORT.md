# S2 三臂补齐交付报告（ainerzero.V9.P146）

- **执行者**：`gemini-w4x2`（二级执行 Agent）· 纯 CPU（未运行 MLX、无 GPU 占用、零 artifacts 变更）
- **补齐 1（臂 A 潜在过冲）**：`arms_mlx.py:arm_a_loss_mlx` 从各后验状态用先验滚动至多 $H_{\text{train}}=16$ 步并解码计损失，均值计入总损失（权重 1.0）。
- **补齐 2（规划器 cost_fn 钩子）**：`planner.py:flat_cem_plan` 增加可选 `cost_fn`，缺省严格保持 `squared_distance(z_T, z_goal)`；提供 `make_arm_a_cost_fn` 并接通 `ForwardCounter`。
- **补齐 3（IDM 显式 stop_gradient）**：`arms_mlx.py` 中 `continuous_gaussian_nll_mlx`、`soft_cross_entropy_mlx`、`idm_loss_mlx` 与 `idm2_loss_mlx` 显式包裹 `mx.stop_gradient(target)`。
- **补齐 4（静态 AST 激活与 free bits 防护）**：`test_s2_arms_static.py` 新增 4 个静态检查：强制 GELU 且禁止 ReLU、强制 free bits 地板、强制 overshooting 循环与 $H_{\text{train}}$、强制 IDM 显式 stop_gradient。
- **补齐 5（原生测试清理）**：`test_s2_arms_mlx_native.py` 直接断言 `sigreg_mx_val` 与 `core_math.sigreg(..., rng=42)` 一致（$<10^{-5}$），消除死代码。
- **对抗变异（5/5 全红变绿已复原）**：
  1. M1: GELU $\to$ ReLU $\to$ `test_activations_use_gelu_and_no_relu` 失败（exit 1，已复原，SHA 一致）
  2. M2: 去除 free bits 地板 $\to$ `test_arm_a_loss_free_bits_floor` 失败（exit 1，已复原，SHA 一致）
  3. M3: 去除 overshooting 循环 $\to$ `test_arm_a_loss_overshooting_loop_and_horizon_bound` 失败（exit 1，已复原，SHA 一致）
  4. M4: 去除 IDM targets 的 stop_gradient $\to$ `test_idm_targets_explicit_stop_gradient` 失败（exit 1，已复原，SHA 一致）
  5. M5: 规划器 cost_fn 绕过 ForwardCounter $\to$ `test_flat_cem_cost_fn_forward_counter_and_custom_cost` 失败（exit 1，已复原，SHA 一致）
- **全量回归与审计**：3566 passed, 6 deselected, 0 failed（273.53s）；80,929 处 artifacts 文件 stat 差异数严格为 0。
- **产物文件**：`diff`、`metrics.json`、`mutation_summary.json`、`mutation_log.txt`、`pytest_full.log`、`stat_comparison.json`、`sha256.json`。
