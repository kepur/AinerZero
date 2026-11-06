自证：复核代理 gemini-h8c2 独立运行，会话指纹 sess-4f78a6d8c0bd，非被验任务 ainerzero.V9.P124 之实现作者（gemini-f8a2），未参与 P124 源码与测试实现，无利益冲突与自验。

# S2 冻结常量 spec、参数量公式与预登记草稿非作者独立复核报告（ainerzero.V9.P125）

- **复核结论**：`RECOMMEND_ACCEPT`
- **被验任务**：`ainerzero.V9.P124`（实现作者：`gemini-f8a2`，报告：`reports/V9-S2-P124/REPORT.md`）
- **核查范围**：`src/ainerzero/v9/experiments/s2/spec.py`、`param_count.py`、`prereg.py`、`tests/v9/experiments/test_s2_spec.py`、`tests/v9/experiments/test_s2_prereg.py` 与 `reports/V9-S2-P124/`
- **复核代理**：`gemini-h8c2`（二级执行 Agent）· 纯 CPU（无 MLX 导入、无 GPU 占用、未改动被测源码）

---

## 一、文件范围与代码树完整性核查（通过）

1. **变动文件范围与 SHA256 逐一哈希比对**：
   - 检查 `reports/V9-S2-P124/sha256.json` 中声明的全部 10 项产物文件，全部严格一致（SHA256 逐字节无漂移）：
     - `src/ainerzero/v9/experiments/s2/spec.py`: `f828816871c93b8c81f9b55d55b0ea1e05e62c4093bea9268d269f8de156af21` (MATCH)
     - `src/ainerzero/v9/experiments/s2/param_count.py`: `e09afde313ad09507e4ea0592b0baadf7f9c8904f42c23a73fbad1ee901ae5cc` (MATCH)
     - `src/ainerzero/v9/experiments/s2/prereg.py`: `f2f3c16b2a6e430a4b1d7bea04c343fe7e637bace445359a32a5a4fe9c0d6f75` (MATCH)
     - `tests/v9/experiments/test_s2_spec.py`: `53565937aded5fdd45878cab331e4a2f94b9ba66103d7e03fa57b3896c7b0094` (MATCH)
     - `tests/v9/experiments/test_s2_prereg.py`: `c2a4c8f44f969172a266b88ce446729b9b8d2f15814566b4a01561b477cfb6b2` (MATCH)
     - `reports/V9-S2-P124/prereg_draft_sample.json`: `627587f39a4bd3f7c6602e2b5a5c723a63fddf6dcfeb02a77432c1a03760cbc8` (MATCH)
     - `reports/V9-S2-P124/mutations.json`: `849b88856b21c507d35ccd526208be7873c014872783365fdae71490ef2c9ed8` (MATCH)
     - `reports/V9-S2-P124/metrics.json`: `ca3cb5dbd6cd9d7142fd20791de25bfdda2910329702ff32365a754816e8cfcc` (MATCH)
     - `reports/V9-S2-P124/REPORT.md`: `dec38c116b30e3317485b3f647d3a7bff61e38bb8889a712518f23b22c770341` (MATCH)
     - `reports/V9-S2-P124/run_mutations.py`: `e44e6cceac2fe0dd11a90a3bb4ae60b70189329229f498bf84a724ff328003ab` (MATCH)
2. **纯 CPU 环境隔离**：
   - 使用 `.venv/bin/python -I` 独立子进程导入 `spec`、`param_count`、`prereg`，断言 `mlx` 不在 `sys.modules`，验证通过。
   - 确认未引入任何 `artifacts/` 写入或冻结操作（符合不 freeze 要求）。

---

## 二、spec 与设计稿逐项对照（≥25 项对照表，全部一致）

从 `reports/V9-S2-DESIGN/DESIGN-r2.md` 全文（§2–§6、附录 A）中抽取 38 项关键常数，逐项比对 `src/ainerzero/v9/experiments/s2/spec.py`，带章节与行号核对：

| 序号 | 变量名 / 关键常数 | DESIGN-r2.md 依据 | spec.py 行号与赋值 | 对照结果 |
|:---:|:---|:---|:---|:---:|
| 1 | `WORLD_SIZE` | §2 L16: "25×25 网格" | L37: `WORLD_SIZE = 25` | 一致 |
| 2 | `TOTAL_ROOMS` | §2 L16: "3×3 共 9 个房间" | L42: `TOTAL_ROOMS = 9` (L40-41: `ROOMS_X=3, ROOMS_Y=3`) | 一致 |
| 3 | `ROOM_INTERIOR_SIZE` | §2 L16: "每间约 7×7 内部空间" | L43: `ROOM_INTERIOR_SIZE = 7` | 一致 |
| 4 | `DOORS_MIN` / `MAX` | §2 L16: "相邻房间之间开 1–2 个门洞" | L77-78: `DOORS_MIN = 1, DOORS_MAX = 2` | 一致 |
| 5 | `ROOM_PILLARS_MIN` / `MAX` | §2 L17: "每个房间内随机放 0–3 根柱子" | L73-74: `ROOM_PILLARS_MIN = 0, MAX = 3` | 一致 |
| 6 | `FOV_SIZE` | §2 L20: "7×7 符号视野" | L46: `FOV_SIZE = 7` | 一致 |
| 7 | `NUM_TERRAIN_CLASSES` | 附录 A L160: "每格 4 类 one-hot" | L47: `NUM_TERRAIN_CLASSES = 4` | 一致 |
| 8 | `TERRAIN_ONE_HOT_DIM` | 附录 A L160: "共 196 维" | L48: `TERRAIN_ONE_HOT_DIM = 196` (7×7×4) | 一致 |
| 9 | `OBS_DIM` | 附录 A L160: "合计 205 维" | L52: `OBS_DIM = 205` (196+4+4+1) | 一致 |
| 10 | `NUM_ACTIONS` | §2 L23: "4 个离散动作" | L55: `NUM_ACTIONS = 4, ACTION_DIM = 4` | 一致 |
| 11 | `K_DISTRIBUTION` | §2 L24: `{1:0.5, 2:0.3, 3:0.2}` | L60: `K_DISTRIBUTION = {1: 0.5, 2: 0.3, 3: 0.2}` | 一致 |
| 12 | `LONG_GOAL_MIN_STEPS` | §2 L25: "最短路径 ≥ 40 步" | L71: `LONG_GOAL_MIN_STEPS = 40` | 一致 |
| 13 | `SHORT_GOAL_MAX_STEPS` | §2 L25: "短目标为 ≤ 10 步" | L72: `SHORT_GOAL_MAX_STEPS = 10` | 一致 |
| 14 | `MAX_REJECTION_RATE` | §2 L28: "某世界的拒绝率 > 30% 时整个世界重抽" | L75: `MAX_REJECTION_RATE = 0.30` | 一致 |
| 15 | `MAX_REDRAW_RETRIES` | §2 L27, L28: "登记上限 5 次" | L76: `MAX_REDRAW_RETRIES = 5` | 一致 |
| 16 | `EPISODE_L_FACTOR` | §2 L29: "在 L = 3 × 最短动作步数以内到达" | L90: `EPISODE_L_FACTOR = 3.0` | 一致 |
| 17 | `PERTURB_FRACTION` | §2 L30: "各有 1/3 的长目标回合" | L94: `PERTURB_FRACTION = 1.0 / 3.0` | 一致 |
| 18 | `PERTURB_INSERT_STEP` | §2 L30: "在第 20 步强制插入" | L95: `PERTURB_INSERT_STEP = 20` | 一致 |
| 19 | `PERTURB_ACTION_COUNT` | §2 L30: "插入 5 个随机动作" | L96: `PERTURB_ACTION_COUNT = 5` | 一致 |
| 20 | `NON_BFS_RATIO_MIN` | §2 L31: "非 BFS 段占比 ≥ 50%（登记下限）" | L64: `NON_BFS_RATIO_MIN = 0.5` | 一致 |
| 21 | `BFS_RANDOM_ACTION_PROB` | §2 L32: "每步以 0.2 的概率换成随机动作" | L67: `BFS_RANDOM_ACTION_PROB = 0.2` | 一致 |
| 22 | `RANDOM_WALK_REPEAT_PROB`| §2 L33: "以 0.7 的概率重复上一动作" | L68: `RANDOM_WALK_REPEAT_PROB = 0.7` | 一致 |
| 23 | `SEGMENT_LEN_MIN` / `MAX`| §2 L34: "每段长度在 [20, 60] 步内均匀抽" | L65-66: `SEGMENT_LEN_MIN = 20, MAX = 60` | 一致 |
| 24 | `EPISODE_STEPS` | §2 L34: "回合 240 步" | L63: `EPISODE_STEPS = 240` | 一致 |
| 25 | `N_FWD` | §4 L67: "N_fwd = 4096 次每决策" | L106: `N_FWD = 4096` | 一致 |
| 26 | `N_FWD_DEV_LEVELS` | §4 L67: "dev 上另报 2048 与 8192 两档" | L107: `N_FWD_DEV_LEVELS = (2048, 4096, 8192)` | 一致 |
| 27 | `S2_MACRO_STEPS` | §4 L68: "s₂ = 8 个观察步" | L108: `S2_MACRO_STEPS = 8` | 一致 |
| 28 | `REPLAN_M_STEPS` | §4 L69: "执行 m = 4 个观察步后重规划" | L109: `REPLAN_M_STEPS = 4` | 一致 |
| 29 | `FLAT_H_CANDIDATES` | §4 L71: "flat：H ∈ {16, 32, 48}" | L112: `FLAT_H_CANDIDATES = (16, 32, 48)` | 一致 |
| 30 | `HIERARCHICAL_HORIZON_CANDIDATES` | §4 L72: "分层：上层视野 ∈ {4, 6, 8} 个宏步" | L113: `HIERARCHICAL_HORIZON_CANDIDATES = (4, 6, 8)` | 一致 |
| 31 | `HIERARCHICAL_BUDGET_RATIO_CANDIDATES` | §4 L72: "上下层预算比 ∈ {0.25, 0.5}" | L114: `HIERARCHICAL_BUDGET_RATIO_CANDIDATES = (0.25, 0.5)` | 一致 |
| 32 | `DEV_LONG_GOAL_EPISODES` | §5 L81: "50 个世界 × 6 对 = 300 个长目标回合" | L81-83: `50 * 6 = 300` | 一致 |
| 33 | `FINAL_LONG_GOAL_EPISODES` | §5 L81: "final 各 50 个世界 × 6 对 = 300 回合"| L84-86: `50 * 6 = 300` | 一致 |
| 34 | `BOOTSTRAP_RESAMPLES` | §5 L82: "分簇的 bootstrap ... 10,000 次" | L120: `BOOTSTRAP_RESAMPLES = 10_000` | 一致 |
| 35 | `BOOTSTRAP_CONFIDENCE` | §5 L82: "给出 95% 区间" | L121: `BOOTSTRAP_CONFIDENCE = 0.95` | 一致 |
| 36 | `SUCCESS_RATE_DIFF_MIN` | §5 L85: "长目标成功率差 ≥ 10 个百分点" | L119: `SUCCESS_RATE_DIFF_MIN = 0.10` | 一致 |
| 37 | `DELTA_PRED` | §5 L86, L148: "δ_pred = 1.0 格" | L125: `DELTA_PRED = 1.0` | 一致 |
| 38 | `TOTAL_ACTUAL_WALLCLOCK_HOURS` / `CALENDAR_WINDOW_HOURS` | §6 L114: "总实际用时上限 ≤ 10 h，另设 72 h 日历窗口" | L178, L180: `10.0 h, 72.0 h` | 一致 |

---

## 三、参数量公式与逐层算式手算比对（通过）

### 1. 标准 Linear 与 GRU 参数公式
- **Linear(in, out, bias=True)**：
  $$P_{\text{Linear}} = (\text{in} + 1) \times \text{out}$$
- **GRUCell(in, h, bias=True)**（MLX / 本库规范：Wx, Wh, b, bhn）：
  $$P_{\text{GRU}} = 3 \times h \times (\text{in} + h) + 4 \times h$$

### 2. 三臂逐层算式手算推导

#### 【Arm A：flat RSSM】
1. **共享编码器 E₁**（205 $\to$ 256 $\to$ 128）：
   - Linear 1: $(205 + 1) \times 256 = 52,736$
   - Linear 2: $(256 + 1) \times 128 = 32,896$
   - 小计：$85,632$
2. **GRU 循环核**（输入 37 $[z_{t-1}(32) + a(4) + dt(1)]$，隐藏 160）：
   - 权重：$3 \times 160 \times (37 + 160) = 480 \times 197 = 94,560$
   - 偏置：$4 \times 160 = 640$
   - 小计：$95,200$
3. **先验网络 Prior**（160 $\to$ 128 $\to$ 64）：
   - Linear 1: $(160 + 1) \times 128 = 20,608$
   - Linear 2: $(128 + 1) \times 64 = 8,256$
   - 小计：$28,864$
4. **后验网络 Posterior**（$(160 + 128 = 288) \to 128 \to 64$）：
   - Linear 1: $(288 + 1) \times 128 = 36,992$
   - Linear 2: $(128 + 1) \times 64 = 8,256$
   - 小计：$45,248$
5. **观测解码器 Decoder**（$(160 + 32 = 192) \to 128 \to 205$）：
   - Linear 1: $(192 + 1) \times 128 = 24,704$
   - Linear 2: $(128 + 1) \times 205 = 26,445$
   - 小计：$51,149$
- **Arm A 总参数量**：
  $$85,632 + 95,200 + 28,864 + 45,248 + 51,149 = 306,093$$
  - `param_count.count_arm_a_closed_form()`：**306,093**（差值 0）
  - 与 300,000 目标相对差：$+2.03\%$，落在 $[270,000, 330,000]$ 范围。

#### 【Arm B：flat JEPA（LeWM 式）】
1. **共享编码器 E₁**：$85,632$
2. **残差预测器 P₁**（输入 133 $[z(128) + a(4) + dt(1)] \to 320 \to 320 \to 128$）：
   - Linear 1: $(133 + 1) \times 320 = 42,880$
   - Linear 2: $(320 + 1) \times 320 = 102,720$
   - Linear 3: $(320 + 1) \times 128 = 41,088$
   - 小计：$186,688$
3. **逆动力学模型 IDM**（$256 \to 128 \to 4$）：
   - Linear 1: $(256 + 1) \times 128 = 32,896$
   - Linear 2: $(128 + 1) \times 4 = 516$
   - 小计：$33,412$
- **Arm B 总参数量**：
  $$85,632 + 186,688 + 33,412 = 305,732$$
  - `param_count.count_arm_b_closed_form()`：**305,732**（差值 0）
  - 与 300,000 目标相对差：$+1.91\%$，落在 $[270,000, 330,000]$ 范围。

#### 【Arm C：两层分层 H-JEPA 式】
1. **Layer 1**（与 Arm B 结构相同，P1 隐藏宽度定为 256）：
   - E1: $85,632$
   - P1 ($133 \to 256 \to 256 \to 128$):
     - Linear 1: $(133 + 1) \times 256 = 34,304$
     - Linear 2: $(256 + 1) \times 256 = 65,792$
     - Linear 3: $(256 + 1) \times 128 = 32,896$
     - 小计：$132,992$
   - IDM1: $33,412$
   - Layer 1 合计：$85,632 + 132,992 + 33,412 = 252,036$
2. **Layer 2**（宏观动力学）：
   - E2 ($128 \to 128 \to 64$):
     - Linear 1: $(128 + 1) \times 128 = 16,512$
     - Linear 2: $(128 + 1) \times 64 = 8,256$
     - 小计：$24,768$
   - P2 ($72 \to 128 \to 64$):
     - Linear 1: $(72 + 1) \times 128 = 9,344$
     - Linear 2: $(128 + 1) \times 64 = 8,256$
     - 小计：$17,600$
   - IDM2 ($128 \to 64 \to 7$):
     - Linear 1: $(128 + 1) \times 64 = 8,256$
     - Linear 2: $(64 + 1) \times 7 = 455$
     - 小计：$8,711$
   - Layer 2 合计：$24,768 + 17,600 + 8,711 = 51,079$
- **Arm C 总参数量**：
  $$252,036 + 51,079 = 303,115$$
  - `param_count.count_arm_c_closed_form()`：**303,115**（差值 0）
  - 与 300,000 目标相对差：$+1.04\%$，落在 $[270,000, 330,000]$ 范围。

### 3. 臂间约束与隐藏层核对
- 最大臂间差：$|306,093 - 303,115| = 2,978$ 参，相对差仅 $0.97\% \ll 10\%$（满足 §3 臂间差 $\le 10\%$）。
- 核对 `spec.ARM_DIMS`：输入输出及潜状态维度严格按照附录 A 保持固定（观测 205，潜空间 128/64，动作 4/7），仅根据附录 A 明确授权调整各臂内部隐藏层（Arm A 收窄 GRU 至 160，Arm B 拓宽 P1 至 320，Arm C 保持 256/128），未越权篡改接口维度。

---

## 四、测试真伪核查（通过）

1. **真实函数调用**：
   - `test_s2_spec.py` 动态加载 `DESIGN-r2.md` 源码文件，比对文档字符串与 `spec` 模块导出变量；
   - `test_s2_prereg.py` 直接调用 `param_count.count_all_arms_closed_form()` 与 `param_count.count_all_arms_numpy_reference()` 进行交叉校验；
   - `test_build_draft_and_validate_clean` 真实调用 `prereg.build_draft()` 并将产物交由 `prereg.validate()` 执行严格契约校验；
   - 子进程用例 `test_direct_python_isolated_subprocess` 在干净 Python `-I` 隔离环境下拉起验证；
   - 5 种篡改用例各自真实触发 `SpecValidationError`。
   - 测试没有自比自、常数比常数或重写被测逻辑的情况。

---

## 五、独立新增坏对照变异核查（4 项变异全部变红，通过）

复核者在 `/tmp/s2_p125_review_replica` 隔离副本环境（包含 `src`、`tests`、`pyproject.toml`）中，实施了作者报告变异表（P124-M1 至 M3）之外的 **4 处独立新变异**，逐处运行定向测试并校验字节级无残留还原：

| 变异编号 | 变异部位与目标文件 | 变异描述 | 预期目标测试 | 实测退出码 | 变异状态 |
|:---:|:---|:---|:---|:---:|:---:|
| **Review-M1** | `src/.../s2/prereg.py` L323 | 去掉日历窗口小于用时校验 (`if False:`) | `test_tamper_calendar_window_smaller_than_wallclock_fails` | 1 | **KILLED** |
| **Review-M2** | `src/.../s2/param_count.py` L49 | GRU 闭式公式遗漏 Wh 循环权重 | `test_closed_form_matches_numpy_reference_per_arm` | 1 | **KILLED** |
| **Review-M3** | `src/.../s2/prereg.py` L276 | 去掉 planning.n_fwd 校验 (`if False:`) | `test_tamper_n_fwd_modified_fails` | 1 | **KILLED** |
| **Review-M4** | `src/.../s2/spec.py` L119 | 门限 `SUCCESS_RATE_DIFF_MIN` 改为 0.05 | `test_gates_and_stopping_constants` | 1 | **KILLED** |

- **结果**：4 项变异全部变红（KILLED，退出码 1），测试杀伤率 100%，无变异存活；每处还原后 SHA256 均与初始文件严格一致。

---

## 六、全量回归计数与信号恢复

- **仓库全量回归计数**：`pytest -q --ignore=tests/native_mlx`，耗时 278.44s（4m38s），**3536 PASSED, 0 FAILED, 6 DESELECTED**（详细执行日志见 `reports/V9-S2-P124/review/pytest_full.log`）。
- **S2 套件全量计数**：`tests/v9/experiments/test_s2_*.py` 包含 100 项测试，耗时 11.68s，**100 PASSED, 0 FAILED**。
- **P124 直接单测计数**：`tests/v9/experiments/test_s2_spec.py` 与 `test_s2_prereg.py` 共 19 项测试全部通过（0.95s）。
- **信号恢复**：所有测试与子进程均遵循纯 CPU 规范与 SIG_DFL 退出保护。

---

## 七、复核总评与建议

P124 的 spec 常量、参数量闭式与 NumPy 形状核算、预登记草稿生成与五重校验器逻辑严密、做工扎实，各项数值与 `DESIGN-r2.md` 逐行严格对应，三臂参数量均稳定收敛在 300k ± 2% 黄金区间内，测试与坏对照具备真实约束力，且严格遵守只读无副作用规范。

**明确给出：`RECOMMEND_ACCEPT`。**
