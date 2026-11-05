# E1 r2 非作者复核自动生成数据表格 (gemini-9f3k)

## 表 1：源码 Diff 与函数改动清单

| 文件路径 | 状态 | 变动行数 (diff) | 修改函数 | 新增函数 | 删除函数 |
|---|---|---|---|---|---|
| `analysis.py` | CHANGED | 13 | `load_cells` | 无 | 无 |
| `commands.py` | CHANGED | 178 | `_get_cell_budget`, `_resolve_paths`, `e1_phase2_command` | 无 | 无 |
| `contact_geometry.py` | **NEW** | +326 | - | 全部（移植自 AWZ E0） | 无 |
| `eval_runner.py` | CHANGED | 387 | `evaluate_episode`, `evaluate_final_once` | `_evaluate_arm_on_final`, `_predicted_pair_contact_series` | `_compute_active_static_pairwise` |
| `prereg.py` | CHANGED | 153 | `build_draft`, `scan_approval_log`, `validate` | `find_final_eval_approval` | 无 |
| `prior.py` | CHANGED | 265 | `step_substep` | `_box_interbody_contact`, `_obb_obb_contact`, `_sphere_obb_contact` | 无 |
| `spec.py` | CHANGED | 115 | `host_anchor_state` | 预算常数及路径修订 | 无 |
| `worker.py` | CHANGED | 249 | `execute_work_cell`, `run_eval`, `run_final_eval` | `build_cell_report`, `build_final_eval_arms`, `ensure_inherited_arm2`, `final_eval_cell_name`, `registered_final_cells`, `save_cell`, `verify_inherited_arm2` | 无 |

### prior.py 逐字核对
- **球-球分支**：逐字未变 (`verbatim: True`)
- **静态接触（地面、斜面、静态盒）**：逐字未变 (`verbatim: True`)
- **改动范围**：仅限于模块文档、新增 3 个几何函数（`_box_interbody_contact`, `_obb_obb_contact`, `_sphere_obb_contact`）及 `step_substep` 中含箱分支。

---

## 表 2：SAT 独立实现随机验证与边界姿态 (5000 对)

- **样本数**：5,000 随机姿态对
- **检出接触对数**：1400 对
- **判定不一致数**：0 对 (0.0%)
- **最大穿透深度差**：`1.47e-15` m (机内浮点精度极限)
- **最大法向方向差**：`0.00e+00`

### 边界姿态测试结果
| 边界姿态 | 描述 | 返回穿透深度 | 返回单位法向 | 结论 |
|---|---|---|---|---|
| **完全重合** | 相同位置 `[1, 2, 3]`，相同半跨与朝向 | `0.6000 m` | `[0.0, 0.0, 1.0]` | 正常检测出最小跨度法向分离 |
| **平行棱接触** | 相同朝向，Z轴间距 0.7m (半跨0.4+0.4=0.8m) | `0.1000 m` | `[0.0, 0.0, 1.0]` | 成功避开退化棱叉积，正确返回面法向 |
| **远离** | 空间间距 >30m | `None` | `None` | 无误报，分离判定完全正确 |

---

## 表 3：与 AnimeWorldZero E0 对齐测试 (5000 对)

- **参考源**：`/Users/mac/AinerWorkFlow/AnimeWorldZero/python/animeworld/e0/blender_worker.py`
- **比对函数**：`compute_exact_shape_distance` vs `contact_geometry.surface_distance`
- **阈值**：接触阈值 `0.004 m`
- **测试对数**：5,000 对 (涵盖 SPHERE-SPHERE, SPHERE-BOX, BOX-SPHERE, BOX-BOX)
- **接触对数**：633 对
- **接触判定不一致**：0 对 (一致率 100.0%)
- **接触状态下最大距离差**：`2.22e-16` m
- **接触状态下最大法向差**：`0.00e+00`

---

## 表 4：全量 Dev 完美预测 (Ground Truth as Prediction) 评测结果

涵盖两族（P 与 S）全部 400 集（各 200 集）开发集：

| 族别 | 场景类型 | 集数 | 真实事件数 | 预测 TP | 误报 FP | 漏报 FN | 碰撞 F1 |
|---|---|---|---|---|---|---|---|
| **P 族** | 全部 (ALL) | 200 | 281 | 281 | 0 | 0 | **1.0000** |
| P 族 | `bounce_collision` | 40 | 98 | 98 | 0 | 0 | **1.0000** |
| P 族 | `box_stack` | 40 | 114 | 114 | 0 | 0 | **1.0000** |
| P 族 | `occlusion_pass` | 40 | 40 | 40 | 0 | 0 | **1.0000** |
| P 族 | `ramp_roll` | 40 | 29 | 29 | 0 | 0 | **1.0000** |
| P 族 | `table_slide` | 40 | 0 | 0 | 0 | 0 | **1.0000** |
| **S 族** | 全部 (ALL) | 200 | 271 | 271 | 0 | 0 | **1.0000** |
| S 族 | `bounce_collision` | 40 | 97 | 97 | 0 | 0 | **1.0000** |
| S 族 | `box_stack` | 40 | 109 | 109 | 0 | 0 | **1.0000** |
| S 族 | `occlusion_pass` | 40 | 40 | 40 | 0 | 0 | **1.0000** |
| S 族 | `ramp_roll` | 40 | 25 | 25 | 0 | 0 | **1.0000** |
| S 族 | `table_slide` | 40 | 0 | 0 | 0 | 0 | **1.0000** |

**结论**：全部 400 集在两族所有 5 个场景下，F1 均为 1.0000，FP=0，FN=0。先验与几何预测修复彻底解决了完美预测无法拿满分的问题。

---

## 表 5：Arm ② (PureNetArm) 预测不变量检验

在内存中加载 r1 检查点并在 dev 分区重算，与 `artifacts/v9/e1/phase2/eval/eval_arm2_*.json` 逐点比对：

| 检查点单元 | 族别 | 种子 | 评测集数 | 比对坐标点数 | 最大绝对偏差 (m) | 结论 |
|---|---|---|---|---|---|---|
| `arm2_P_42` | P | 42 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| `arm2_P_43` | P | 43 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| `arm2_P_44` | P | 44 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| `arm2_S_42` | S | 42 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| `arm2_S_43` | S | 43 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| `arm2_S_44` | S | 44 | 200 | 28,800 | `0.00e+00` | 完全一致，允许沿用 |
| **全局合计** | P / S | 全部 | **1,200** | **172,800** | **`0.00e+00`** | **全部 bitwise 相同** |

---

## 表 6：预算核算与历史墙钟比对

### 1. 预算总表 (秒)
| 预算类别 | 登记限额 (`BUDGET_CAPS`) | 用户批准上限 (3.2 小时) | 差额 / 余量 |
|---|---|---|---|
| 训练合计 (`train_total_wall_max_seconds`) | 9,900.0 s | - | - |
| 开发评测合计 (`dev_eval_total_max_seconds`) | 1,500.0 s | - | - |
| **训练 + 开发合计** | **11,400.0 s** | **11,520.0 s** | **+120.0 s (达标)** |
| 终验单族限额 (`final_eval_cell_max_seconds`) | 900.0 s | - | - |
| 阶段总硬性上限 (`phase_total_wall_ceiling_seconds`) | 13,200.0 s | - | - |

### 2. 重训臂单单元限额 vs r0/r1 实际墙钟耗时
| 臂代号 | 族 / 种子 | r0/r1 实际墙钟 (s) | r2 登记单单元上限 (s) | 余量 (s) | 余量比例 |
|---|---|---|---|---|---|
| **Arm ③** | P / 42 | 136.33 s | 500.0 s | +363.67 s | +266.8% |
| Arm ③ | P / 43 | 209.76 s | 500.0 s | +290.24 s | +138.4% |
| Arm ③ | P / 44 | 205.20 s | 500.0 s | +294.80 s | +143.7% |
| Arm ③ | S / 42 | 223.50 s | 500.0 s | +276.50 s | +123.7% |
| Arm ③ | S / 43 | 224.07 s | 500.0 s | +275.93 s | +123.1% |
| Arm ③ | S / 44 | 298.16 s | 500.0 s | +201.84 s | +67.7% |
| **Arm ③ 综合** | **最大值** | **298.16 s** | **500.0 s** | **+201.84 s** | **+67.7% (充裕)** |
| **Arm ⑥** | P / 42 | 841.69 s | 1150.0 s | +308.31 s | +36.6% |
| Arm ⑥ | P / 43 | 964.76 s | 1150.0 s | +185.24 s | +19.2% |
| Arm ⑥ | P / 44 | 961.47 s | 1150.0 s | +188.53 s | +19.6% |
| Arm ⑥ | S / 42 | 691.69 s | 1150.0 s | +458.31 s | +66.3% |
| Arm ⑥ | S / 43 | 693.76 s | 1150.0 s | +456.24 s | +65.8% |
| Arm ⑥ | S / 44 | 673.40 s | 1150.0 s | +476.60 s | +70.8% |
| **Arm ⑥ 综合** | **最大值** | **964.76 s** | **1150.0 s** | **+185.24 s** | **+19.2% (安全但需留意负载)** |

---

## 表 7：变异测试 (Mutation Testing) 结果

在隔离副本工作区中执行改动变异：

| 变异 ID | 变异文件 | 变异操作描述 | 单元测试是否抓到 | 测试输出与表现 | 结论 |
|---|---|---|---|---|---|
| **MUT_1** | `contact_geometry.py` | 静态斜面重建中转置旋转矩阵 `rot` | **抓到 (CAUGHT)** | `3 failed, 8 passed in 1.25s` | 斜面几何重建有强断言保护 |
| **MUT_2** | `eval_runner.py` | 接触序列预测帧下标偏移：`PREFIX_FRAMES + t` -> `t` | **抓到 (CAUGHT)** | `test_e1_eval_runner.py` 未抓到；全量套件 `test_e1_contact_geometry.py` 抓到 (2 failed) | 单元测试缺乏带旋转箱子合成用例，端到端测试有效兜底 |
| **MUT_3** | `prior.py` | 球-盒接触法向反向：`-R @ (diff / dist)` | **抓到 (CAUGHT)** | `3 failed, 16 passed in 2.26s` | 球盒接触法向有强断言保护 |
| **MUT_4** | `analysis.py` | 移除 `load_cells` 中的分区过滤 | **抓到 (CAUGHT)** | `1 failed, 16 passed in 1.17s` | 分区混淆有强断言保护 |
| **MUT_5** | `prior.py` | 将 `EDGE_AXIS_PREFERENCE_M` 改为 0.0 | **未抓到 (ESCAPED)** | `19 passed in 1.82s` | **测试盲区**：测试直接 import 模块常量，缺少特定临界微小深度决胜用例 |

---

## 表 8：全量单测套件运行结果

- **命令**：`.venv/bin/python -m pytest tests/test_e1_*.py -q`
- **运行时间**：40.57 s
- **结果**：**250 passed, 0 failed** (100% 通过)
