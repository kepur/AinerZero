# S3-C1 GridLab-S3 世界、内容层、巡游生成器与分区报告 (r2 复核)

## 1. 实际执行命令
- 单元测试套件全量执行：
  ```bash
  PYTHONPATH=src python3 -m pytest -v tests/v9/experiments/test_s3_*.py
  ```
- 500 世界规模验证与指标落盘脚本：
  ```bash
  PYTHONPATH=src python3 -c "<scale_swap_test_and_metrics_emitter>"
  ```
- 坏对照运行命令（均在 `/tmp/s3_mutations/` 隔离副本中真改源码执行）：
  ```bash
  PYTHONPATH=src python3 -m pytest -v tests/v9/experiments/test_s3_pathfinding.py
  PYTHONPATH=src python3 -m pytest -v tests/v9/experiments/test_s3_content_independence.py
  PYTHONPATH=src python3 -m pytest -v tests/v9/experiments/test_s3_events_bruteforce.py
  PYTHONPATH=src python3 -m pytest -v tests/v9/experiments/test_s3_obs_spec.py
  ```

## 2. 测试结果概览
11 项单元测试全量通过（耗时 7.65s，纯 CPU，零 MLX）：
1. `test_reverse_bfs_reachability_100_percent`：PASSED（反向多源 BFS 到达率 100%）
2. `test_probe_p_a_coverage_and_swap_ratio`：PASSED（探针 P-a 覆盖门与比例门）
3. `test_content_invariants_and_token_families`：PASSED（内容不变量、新旧不同与族隔离）
4. `test_content_layer_independence_across_episodes`：PASSED（位置、Token、换时独立随机）
5. `test_events_match_brute_force_and_hard_bounds_100_worlds`：PASSED（100 世界步真值暴力重构比对，硬边界校验）
6. `test_student_observation_dimension_and_no_leakage`：PASSED（198 维且严格无坐标泄漏）
7. `test_episode_generation_determinism`：PASSED（相同种子位级确定重现）
8. `test_seed_namespaces_disjointness`：PASSED（各分区种子命名空间严格互斥）
9. `test_final_partition_refusal_by_default`：PASSED（final 分区默认强拒绝机制）
10. `test_artifacts_path_write_refusal`：PASSED（严格拦截 artifacts/ 写入）
11. `test_s3_package_pure_cpu_no_mlx_imported`：PASSED（独立进程包纯净隔离，无 MLX 导入）

## 3. P-a、P-b 与 500 世界规模实测数字

| 探针 / 实验项 | 实测数值 | 门槛要求 | 判定 |
|---|---|---|---|
| **P-b 寻路到达率**（35 世界 × 5 长目标） | **175 / 175 (100.00%)** | 100.00% | **通过 (PASS)** |
| **P-a 不同格子中位数**（100 世界） | **112.0** | ≥ 60 | **通过 (PASS)** |
| **P-a 最常停留格占比最大值**（100 世界） | **0.0528** (5.28%) | ≤ 0.15 (15.0%) | **通过 (PASS)** |
| **P-a 长间隔已换 token 事件回合比例** | **98.0%** (98/100) | ≥ 90.0% | **通过 (PASS)** |
| **P-a 总体返回事件已换比例** | **0.4290** (399/930) | 0.40 – 0.60 | **通过 (PASS)** |
| **P-a 总返回事件数** | **930 次**（已换 399，未换 531） | — | 自动脚本生成 |
| **500 世界规模复测总事件数** | **4803 次**（均 9.6 次/集） | ≥ 500 世界 | 统计量充分 |
| **500 世界总体已换比例** | **0.4220** (2027/4803) | 0.40 – 0.60 | **通过 (PASS)** |
| **500 世界已换比例 95% 置信区间** | **[0.4081, 0.4361]** | 全区间处于 [0.40, 0.60] | **置信过线** |
| **极短间隔事件（lag < 8）** | **78 次**（占 1.62%） | bucket = None | 记为 None，不进分桶统计 |

> [!NOTE]
> `lag < 8` 的事件（极短间隔原地转向或回踏）其 `bucket` 字段严格设为 `None`，不计入 short / mid / long 任何时间分桶，主基准主指标仅统计有效分桶事件。

## 4. 硬断言与边界修复（针对 r1 必修项 ①、②）
- **边界缺陷消除**：原生成器 `trajectory_positions` 长度为 361（导致步数 360 时可能产生 `t=360` 的越界事件）。现将轨迹提取严格绑定于 `steps[:]["truth"]`，长度固定为 360。
- **全量硬断言验证**：在 `test_s3_events_bruteforce.py` 中对 100 个世界（共 930 个事件）及 500 世界测试（4803 个事件）逐条断言 `0 <= t < len(steps)` 与 `0 <= prev_visit_t < t`，全部满足，越界事件彻底清零。
- **非自证独立重算**：测试重构完全丢弃生成器内部轨迹数组，纯粹由 `steps[t]["truth"]["x", "y"]` 独立扫描重构，对比实际产出完全一致。

## 5. 坏对照原始测试变红实据（针对 r1 必修项 ③）
5 组坏对照均在隔离副本中真实修改源码后执行 pytest，全量变红，原始日志位于 [`reports/V9-S3-C1/mutations/`](reports/V9-S3-C1/mutations/)：
1. **反向 BFS 换成正向（`m1_forward_bfs`）**：
   - 报错：`AssertionError: Pathfinding reachability failed: 0/175 (0.00%), required 100%`。
   - 日志：[`reports/V9-S3-C1/mutations/m1_forward_bfs_red.txt`](reports/V9-S3-C1/mutations/m1_forward_bfs_red.txt)。
2. **固定内容位置与 Token（`m2_fixed_content`）**：
   - 报错：`AssertionError: Positions lack diversity: 1/25, assert 1 >= 20`。
   - 日志：[`reports/V9-S3-C1/mutations/m2_fixed_content_red.txt`](reports/V9-S3-C1/mutations/m2_fixed_content_red.txt)。
3. **标签漏算路过（`m3_skip_pass_through`）**：
   - 报错：`AssertionError: Event count mismatch in episode 0: actual 3 != expected 9`。
   - 日志：[`reports/V9-S3-C1/mutations/m3_skip_pass_through_red.txt`](reports/V9-S3-C1/mutations/m3_skip_pass_through_red.txt)。
4. **真值坐标泄漏进学生观察（`m4_leak_coordinates`）**：
   - 报错：`AssertionError: set_data.keys().issubset(allowed_keys)`（学生步字典泄漏 `'x', 'y'` 顶层键）。
   - 日志：[`reports/V9-S3-C1/mutations/m4_leak_coordinates_red.txt`](reports/V9-S3-C1/mutations/m4_leak_coordinates_red.txt)。
5. **越界回归断言变红（`m5_out_of_bounds`）**：
   - 报错：`AssertionError: Event count mismatch in world 11: actual 14 != expected 13`（第 14 个事件发生在非法第 361 步 `t=360`）。
   - 日志：[`reports/V9-S3-C1/mutations/m5_out_of_bounds_red.txt`](reports/V9-S3-C1/mutations/m5_out_of_bounds_red.txt)。

## 6. 未验证项
- 本任务限定于世界、内容层、巡游生成器与分区（纯 CPU，零训练）。
- 神经网络编码器、读出头与 FAR 学习检索打分头（A0–A3 臂）尚未实现，将在后续任务中推进。
- 未使用 GPU / MLX，未向 `artifacts/` 写入任何数据，未触碰生产账本与锁文件。
