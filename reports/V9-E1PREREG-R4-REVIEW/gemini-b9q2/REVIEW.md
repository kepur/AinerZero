# 非作者复核报告：E1 预登记草案 r4 定稿候选

- **复核执行者**：`gemini-b9q2`（二级执行 agent · L2 标准 · 非作者复核）
- **复核任务**：`ainerzero.V9.P95`
- **复核对象**：`reports/V9-P48/PREREG_DRAFT_r4_candidate.md`
- **复核基线 SHA-256**：`ef7856e7f757d6f44b8e11a9d1f4f63da9e043cc202e08d772a94ba67d04a20e`
- **复核时间**：2026-10-30
- **复核结论**：**建议定稿**（附 1 条可选措辞建议，不阻断定稿）

---

## 摘要

本复核根据任务要求，作为非作者（草案作者为一级 claude），对 E1 第二阶段预登记草案 r4 定稿候选进行了逐项、逐行交叉核验。核对依据覆盖三类文档：
1. **一级架构裁定**：`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md` 末尾的修订 r1、r2、r3、r4；
2. **代码实际常量与定义**：`spec.py`、`eval_runner.py`、`metrics.py`、`prior.py`、`arms_nonnet.py`、`jacobian.py` 以及 AWZ 的 `config.py`；
3. **Smoke 实测数据**：`reports/V9-E1SMOKE6/gemini-x2r8/`（P94）的 `timings.json` 与 `metrics.json`。

经核对：
- r4 §8 中的 8 条修订条款在一级架构裁定 r1–r4 中均有严格对应，语义与公式完全一致；
- r4 §8「冻结常量表」的全部 20 行与代码实现逐项吻合（训练步数上限 64000 与预算上限 5 h 为本次定稿新定，符合「待冻结代码卡落实」约定）；
- r4 §6 预算与文末引用的实测指标和耗时，与 P94 交付的 `timings.json` 和 `metrics.json` 严格一致；
- H-E1 的判定口径与 `analysis.py:231-345` 的实现完全一致；
- r4 相对于 r3 的改动均在 §8 效力优先条款的覆盖范围内，正文第 2、4、6 节与 §8 之间逻辑自洽，无未解决的矛盾。

---

## 一、一级架构裁定核对（对照 `E1_IMPLEMENTATION_PLAN.md` r1–r4）

r4 草案 §8「r4 冻结修订条款（效力优先于前文）」共列出 8 条条款，逐项比对 `reports/V9-P48/E1_IMPLEMENTATION_PLAN.md`：

### 1. §8 第 1 条：F_prior 的几何（对应实施计划 修订 r1）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:130`）：
  > `1. **F_prior 的几何**（修订 r1，P85）：盒体接触改用支撑函数 h(n)=Σᵢeᵢ|n·aᵢ|，球体仍用半径。`
- **r4 候选稿证据行**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:140`）：
  > `   - 证据：P82 的静止盒子第 1 步误差 0.905 m，修订后 P88 降到 0.31 cm。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:46`）：
  > `1. **盒体接触改用支撑函数**，替换原裁定第 1 条的包围球。`
- **裁定结构偏差原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:50`）：
  > `2. **新登记的结构偏差**，替换原第 1 条：`
- **比对结果**：**完全一致**。r4 列出的 8 项登记偏差（支撑投影、中心连线法向、单点接触、各向同性惯量、mean/min 合成、静态面材质、无风阻、无滚阻）与实施计划完全一致。

### 2. §8 第 2 条：学生侧静态几何（对应实施计划 修订 r1）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:141`）：
  > `2. **学生侧静态几何**（修订 r1，P84）：桌面顶面 = 中心 + 厚度/2；斜面平面点 = 中心 + n·厚度/2，并带边界；缺字段时抛异常。E1 导出的尺寸唯一来源是登记的 E0 尺寸表，有一致性测试锁定。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:56`）：
  > `3. **导出的静态几何必须与 E0 真实几何一致**：`
- **比对结果**：**完全一致**。

### 3. §8 第 3 条：⑤ 的辨识（对应实施计划 修订 r1）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:142`）：
  > `3. **⑤ 的辨识**（修订 r1，P86）：子空间辨识。只在加权 Fisher 矩阵特征值 ≥ 1e-3 的方向上做 LM，其余方向保持先验值；报告每个参数的辨识权重与子空间维数。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:61`）：
  > `4. **⑤ 改为子空间辨识**：`
- **比对结果**：**完全一致**。

### 4. §8 第 4 条：④ 的定位（对应实施计划 修订 r1 与 r3）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:143`）：
  > `4. **④ 的定位**（修订 r1 与 r3）：④ 同时使用评测侧真实的物体参数与静态面材质，学生侧的臂不泄漏真值（有不变性测试）。但在有结构偏差的 F_prior 里，真参数不一定是最优参数（P90：④ 的 e_10 高于 ①），所以 ④ 改称「**真参数诊断**」，只报告，**不作为上界**，也不进判定。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:65`）：
  > `5. **④ 的上界同时注入评测侧的静态面真实材质**：Ground、Ramp、TableTop、OccluderWall 的 friction 与 restitution。只用于诊断，学生侧仍使用登记的默认值。`
- **裁定更正原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:106`）：
  > `- **④ 的定位更正**：P90 中 ④ 的 e_10 高于 ①（P 族 0.053 对 0.0495），⑤ 是 0.0435。在有结构偏差的 F_prior 里，真参数 φ\* 不一定是最优参数（L² 意义下的最优另有其值），所以 ④ 改称「真参数诊断」，不作为有保证的上界。只报告，不进判定，与原登记一致。`
- **比对结果**：**完全一致**。

### 5. §8 第 5 条：输出约定（对应实施计划 修订 r3）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:144`）：
  > `5. **输出约定**（修订 r3，P91）：七个臂的 predict 一律只返回 n_future 行未来帧，第 j 行对应第 PREFIX+j 帧；评测侧断言行数，不截取。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:104`）：
  > `  - 七个臂的 `predict` 一律只返回 **n_future 行未来帧**，第 j 行对应第 PREFIX_FRAMES+j 帧，不含当前状态；`
- **比对结果**：**完全一致**。

### 6. §8 第 6 条：数据与身份（初速度注入与模块钉住）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:146`）：
  > `   - E0 的初速度注入：2 帧 kinematic 预滚，`velocity_injection = kinematic_preroll_2f_v1`（B28）。此前的 E0 产物都没有施加初速度，见 AWZ RESEARCH_LOG 的 R20261029-e0-initial-velocity。`
- **r4 候选稿钉住原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:147`）：
  > `   - 预登记钉住 E1 全部 15 个模块与 E0 生成器的源码摘要（P83）；各模式执行前核对，不一致就拒绝运行；数据侧核对观测到的标记值。`
- **比对结果**：**完全一致**。代码 `spec.py:341` 包含 `REQUIRED_VELOCITY_INJECTION: str = "kinematic_preroll_2f_v1"`；`IMPLEMENTATION_SOURCES` 钉住 16 个源码文件（含 `__init__.py`，主体模块即 15 个），`GENERATOR_SOURCES` 钉住 8 个生成器文件。

### 7. §8 第 7 条：k 步位置误差定义（对应实施计划 修订 r2）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:148`）：
  > `7. **第 4 节第 1 条「k 步位置误差」的定义**（修订 r2，P89）：单起点视野误差。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:85`）：
  > `- **裁定（冻结前生效，并写入草案 r4）**：k 步位置误差定义为**单起点视野误差**：`
- **比对结果**：**完全一致**。单起点定义 $e_k$ 对应目标帧 $t_0+k$（$t_0 = \text{PREFIX}-1$），端点帧跳过不补值，均值聚合层次（各物体 $\to$ 各 episode $\to$ 三种子宏平均）完全对齐。

### 8. §8 第 8 条：训练步数与网络训练做法（对应实施计划 修订 r4）
- **r4 候选稿原文**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:179`）：
  > `8. **训练步数与网络训练做法**（修订 r4，P93；取代 r0 的「按 dev 选步数」）：②③⑥ 一律相同、参数量不变。输入与目标都做 z 标准化；输出层零初始化：尚未设置统计量时，未训练的 ③⑥ 与 ①⑤ 完全相同，未训练的 ② 是「保持不动」模型；按训练集拟合统计量之后，初始输出等于训练目标的均值，也就是 MSE 意义下最优的常数修正；按 episode 留出 10% 验证集早停，上限 64000 步。不再用 dev 挑选步数。依据：P92 中残差臂在第 1 步就把先验拉坏了（③ 的 e_1 0.008–0.011 m，① 0.0005 m），而且训练越久越差。`
- **裁定依据原文**（`reports/V9-P48/E1_IMPLEMENTATION_PLAN.md:120`）：
  > `- **裁定**（冻结前生效，并写入草案 r4；②③⑥ 一律相同，参数量不变）：`
- **比对结果**：**完全一致**。早停规则（每 500 步、patience 10、10% 留出验证集）、z 标准化（std 下限 1e-6）与输出层零初始化要求均已落实。

---

## 二、代码实际常量与定义核对（逐行对照 §8「冻结常量表」）

| # | 常量表项 | r4 声明值 | 代码实际值与行号 | 比对结论 |
|---|---|---|---|---|
| 1 | 观测前缀 PREFIX_FRAMES | 10 | `src/ainerzero/v9/experiments/e1/eval_runner.py:76`<br>`PREFIX_FRAMES: int = 10  # 待一级冻结: number of prefix observation frames` | **一致** |
| 2 | 最大预测步数 MAX_FUTURE_FRAMES | 30 | `src/ainerzero/v9/experiments/e1/eval_runner.py:77`<br>`MAX_FUTURE_FRAMES: int = 30  # 待一级冻结: maximum rollout horizon` | **一致** |
| 3 | 主指标 k | 10；另报 1、5、30 | `src/ainerzero/v9/experiments/e1/metrics.py:27-28`<br>`DEFAULT_K_STEPS: tuple[int, ...] = (1, 5, 10, 30)`<br>`PRIMARY_K: int = 10` | **一致** |
| 4 | 碰撞事件 | 法向相对速度 ≥ 0.05 m/s，去抖 3 帧，匹配 ±1 帧 | `src/ainerzero/v9/experiments/e1/metrics.py:30-32`<br>`COLLISION_VELOCITY_THRESHOLD_MPS: float = 0.05`<br>`COLLISION_DEBOUNCE_FRAMES: int = 3`<br>`COLLISION_MATCH_TOLERANCE_FRAMES: int = 1` | **一致** |
| 5 | 弹道段最短 | 5 帧 | `src/ainerzero/v9/experiments/e1/metrics.py:33`<br>`BALLISTIC_MIN_FRAMES: int = 5` | **一致** |
| 6 | 接触容差 | 0.004 m | `src/ainerzero/v9/experiments/e1/metrics.py:29`<br>`CONTACT_TOLERANCE_M: float = 0.004` | **一致** |
| 7 | bootstrap | 10 000 次，种子 42，95% 区间 | `src/ainerzero/v9/experiments/e1/metrics.py:35-37`<br>`BOOTSTRAP_RESAMPLES: int = 10000`<br>`BOOTSTRAP_SEED: int = 42`<br>`BOOTSTRAP_CONFIDENCE: float = 0.95` | **一致** |
| 8 | H-P 的「≈」 | 区间含 0，且宽度 ≤ ④ 与 ① 差距的 10% | `src/ainerzero/v9/experiments/e1/spec.py:282`<br>`H_P_SIMILARITY_MAX_WIDTH_RATIO: float = 0.10` | **一致** |
| 9 | φ̂₀（有偏先验中位数） | friction 0.5、restitution 0.45、mass 2.6、linear/angular damping 0.125 | `src/ainerzero/v9/experiments/e1/prior.py:86-90`<br>`friction: float = 0.50`, `restitution: float = 0.45`, `mass: float = 2.60`, `linear_damping: float = 0.125`, `angular_damping: float = 0.125` | **一致** |
| 10 | 静态面默认材质 | ground 0.50/0.30，ramp 0.25/0.25，table 0.20/0.35，box 0.50/0.30（μ/e） | `src/ainerzero/v9/experiments/e1/prior.py:47-54`<br>`DEFAULT_GROUND_FRICTION = 0.50`, `DEFAULT_GROUND_RESTITUTION = 0.30`<br>`DEFAULT_RAMP_FRICTION = 0.25`, `DEFAULT_RAMP_RESTITUTION = 0.25`<br>`DEFAULT_TABLE_FRICTION = 0.20`, `DEFAULT_TABLE_RESTITUTION = 0.35`<br>`DEFAULT_BOX_FRICTION = 0.50`, `DEFAULT_BOX_RESTITUTION = 0.30` | **一致** |
| 11 | 雅可比相对步长 | 1e-3 | `src/ainerzero/v9/experiments/e1/jacobian.py:33`<br>`DEFAULT_REL_STEP: float = 1e-3` | **一致** |
| 12 | ⑥ 投影的 SVD 截断 | 1e-6·σ_max | `src/ainerzero/v9/experiments/e1/jacobian.py:34`<br>`DEFAULT_SVD_REL_TOL: float = 1e-6` | **一致** |
| 13 | ⑤ 的 Fisher 门槛 | 1e-3 | `src/ainerzero/v9/experiments/e1/arms_nonnet.py:45`<br>`FISHER_MIN_EIGVAL_THRESHOLD: float = 1e-3` | **一致** |
| 14 | 观测噪声 σ | 0（学生拿到的是无噪声状态） | `src/ainerzero/v9/experiments/e1/export.py:406-508`<br>学生数据严格由真值位姿线速度转换导出，无加噪步骤 | **一致** |
| 15 | S 族二次阻力系数 | U(0.05, 0.5) | `AnimeWorldZero/python/animeworld/e0/config.py:98`<br>`DEFAULT_QUADRATIC_DRAG_RANGE = (0.05, 0.5)` | **一致** |
| 16 | 学习率 / batch | 1e-3 / 16 | `src/ainerzero/v9/experiments/e1/spec.py:234-235`<br>`DEFAULT_LEARNING_RATE: float = 1e-3`<br>`DEFAULT_BATCH_SIZE: int = 16` | **一致** |
| 17 | 训练步数 | 上限 64000；每 500 步评估验证损失一次，patience 10，取验证损失最低的权重 | `src/ainerzero/v9/experiments/e1/spec.py:229-231`<br>`DEFAULT_TRAIN_STEPS = 32000`, `EARLY_STOP_EVAL_EVERY = 500`, `EARLY_STOP_PATIENCE = 10` | **待冻结代码卡落实**（按任务说明，64000 为定稿新定，复核后修改，不算不一致） |
| 18 | 验证集 | 训练集中按 episode 留出 10%，种子固定、只取决于族（三个臂、三个种子共用）；不使用 dev | `src/ainerzero/v9/experiments/e1/train_runner.py:125-126`<br>`Validation set is chosen deterministically based ONLY on family and episode files, independent of training seed or model arm.`（`val_fraction=0.1`） | **一致** |
| 19 | 网络标准化 | 输入与目标逐维 z 标准化，std 下限 1e-6，只用训练子集计算；输出层零初始化 | `src/ainerzero/v9/experiments/e1/arms_net.py:266, 335, 337`<br>`zero_init_out: bool = True`<br>`self.input_std = np.maximum(np.asarray(input_std, dtype=np.float32), 1e-6)`<br>`self.target_std = np.maximum(np.asarray(target_std, dtype=np.float32), 1e-6)` | **一致** |
| 20 | 数据规模 | 每族 train 1000、dev 200、final 200；数据种子 1001；训练种子 42、43、44 | `src/ainerzero/v9/experiments/e1/spec.py:216-225`<br>`TRAIN_WORLDS_PER_FAMILY = 1000`, `DEV_WORLDS_PER_FAMILY = 200`, `FINAL_WORLDS_PER_FAMILY = 200`, `DATA_SEED = 1001`, `TRAINING_SEEDS = (42, 43, 44)` | **一致** |

---

## 三、Smoke 实测数据核对（对照 P94 `timings.json` 与 `metrics.json`）

r4 草案 §6「运行协议与预算」与文末「定稿候选」中引用的实测与外推数据，与 `reports/V9-E1SMOKE6/gemini-x2r8/` 中的实测记录严格对齐：

1. **数据生成速率**：
   - r4 引用（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:100`）：
     > `  - 数据生成 2800 段：≤ 1 h（实测 0.96 s/段，外推约 45 min）；`
   - P94 实测（`reports/V9-E1SMOKE6/gemini-x2r8/timings.json` 步骤 `02_generate_data`）：
     `"seconds_per_sequence": 0.9637392332974855`，2800 段外推为 $2800 \times 0.9637\text{ s} = 2698.5\text{ s} \approx 44.97\text{ min}$（约 45 min）。**完全属实**。

2. **S 族 Arm 2 最佳步数与步数上限调整依据**：
   - r4 引用（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:174`）：
     > `P94 中 ② 在 S 族的 best_step 31500 接近 32000，正式数据量是 5 倍，所以提高上限`
   - P94 实测（`reports/V9-E1SMOKE6/gemini-x2r8/timings.json` 中 `training_details.arm2_S_seed42`）：
     `"best_step": 31500, "stopped_step": 32000`。**完全属实**。

3. **评测延迟（最慢单元）**：
   - r4 引用（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:102`）：
     > `  - dev 评测 26 格：≤ 30 min（外推约 15 min；⑥ 0.47 s/episode 最慢）；`
   - P94 实测（`reports/V9-E1SMOKE6/gemini-x2r8/metrics.json` 中 `arm6_P_seed42`）：
     `"seconds_per_episode": 0.4706756572748418`。**完全属实**。

4. **P94 dev 各臂 10 步误差数值**：
   - r4 引用（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:193`）：
     > `P94 dev（只用于设定，不下结论）：e_10 为 ① 0.0495、② 0.036、③ 0.169、⑤ 0.0435、⑥ 0.043、⑦ 0.043（P 族）。`
   - P94 实测（`reports/V9-E1SMOKE6/gemini-x2r8/metrics.json` 各单元 `mean_error_10step_m`）：
     - Arm 1 (`arm1_P_baseline`): `0.04954565722186035` $\to$ `0.0495`
     - Arm 2 (`arm2_P_seed42`): `0.035978438183665275` $\to$ `0.036`
     - Arm 3 (`arm3_P_seed42`): `0.1691084486817372` $\to$ `0.169`
     - Arm 5 (`arm5_P_baseline`): `0.043533227406733585` $\to$ `0.0435`
     - Arm 6 (`arm6_P_seed42`): `0.04261884343110629` $\to$ `0.043`
     - Arm 7 (`arm7_P_baseline`): `0.04298060036075121` $\to$ `0.043`
   - **比对结果**：**完全属实**。

5. **总预算墙钟上限**：
   - r4 提议（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:104`）：
     > `  - **总墙钟上限（提议）**：**5 h**，远低于 r3 提议的 32 h；`
   - 外推核算：数据生成 45 min + 18 训练格 $\le$ 3 h + dev 评测 15 min + final 一次 30 min = 4.5 h，取整安全上限定为 5 h。**完全合理**。

---

## 四、专项检查与逻辑自洽性分析

### (a) H-E1 判定口径与 `analysis.py` 实现一致性
- **预登记口径**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:19`）：
  > `- **H-E1（原门槛，不改）**：在未见场景上，③ 的 10 步位置误差比 ①② 中较好者低 ≥10%，且碰撞 F1 不下降。能量漂移与推理延迟只报告。`
- **代码实现**（`src/ainerzero/v9/experiments/e1/analysis.py:231-345`）：
  1. `analysis.py:238` 明确注释：
     > `1. Evaluated per family independently (no pooling).`
  2. `analysis.py:239` 明确基线选择规则：
     > `2. Baseline = best of Arm ① and Arm ② on 10-step position error`
  3. `analysis.py:277-291` 严格实现基线比较逻辑：
     > `if err_1 <= err_2:`（若 ① 较低选 ①，否则选 ②）
  4. `analysis.py:310-314` 门槛判定：
     ```python
     rel_reduction = (err_baseline - err_3) / err_baseline if err_baseline > 1e-12 else 0.0
     error_passed = bool(rel_reduction >= PRIMARY_ERROR_REDUCTION_MIN - 1e-9)
     f1_passed = bool(f1_3 >= f1_baseline - 1e-9)
     gate_passed = bool(error_passed and f1_passed)
     ```
- **结论**：`analysis.py` 的实现与预登记草案口径**完全一致**。

### (b) r4 与 r3 原文差异及 §8「效力优先」覆盖核对
- 通过 `diff -u reports/V9-P48/PREREG_DRAFT.md reports/V9-P48/PREREG_DRAFT_r4_candidate.md` 进行全量文本比对：
  - r4 在文件头明确声明：`**§8 的效力优先于前文**。训练做法与预算已按 smoke P94`（行 3）；
  - r4 将 §6 预算章节按实测更新（由提议 32 h 更新为 5 h）；
  - r4 新增 §8 冻结修订条款（行 126–180）与冻结常量表（行 154–178）；
  - r4 更新文末修订记录（行 192–193）。
- 检查 r3 原文与 r4 的冲突点：
  1. 误差定义：r3 原文为一般性 10 步误差，§8.7 明确为「单起点视野误差」并重载；
  2. 几何假设：r3 原文引用式 8 的球体假设，§8.1 明确为支撑函数接触与新登记结构偏差并重载；
  3. ④ 的定位：r3 原文称「只作上界诊断」，§8.4 明确「改称真参数诊断，不作为上界」并重载；
  4. 训练方式：r3 原文为按 dev 选步数，§8.8 明确为固定上限 64000 加早停并重载。
- **结论**：所有实质修订均被 §8 的效力优先条款明确覆盖，无任何未覆盖或遗漏的冲突点。

### (c) 正文各节与 §8 内部一致性
- **§2 臂表 vs §8**：
  - §2 臂表行 31 保留了 r3 的原始表述：`| ④ | 真参数物理，只作上界诊断，不计成绩 |`；
  - §8.4 则明确指出：`所以 ④ 改称「**真参数诊断**」，只报告，**不作为上界**，也不进判定。`
  - 依据行 3 与行 126 声明的「§8 的效力优先于前文」，此处效力清晰，不影响定稿有效性。
- **§4 指标 vs §8**：
  - §4 行 65 声明主指标为未见场景 10 步位置误差；
  - §8.7 与冻结常量表第 3 行对 $e_k$ 给出唯一的无歧义单起点视野误差定义及端点排除规则，两处无矛盾。
- **§6 预算 vs §8**：
  - §6 与 §8/修订记录均一致使用 64000 步训练上限与 5 h 总预算墙钟上限，内部数据严密一致。

---

## 五、可选措辞建议（不阻断定稿）

- **建议**（第 2 节臂表第 31 行）：
  - **当前文本**（`reports/V9-P48/PREREG_DRAFT_r4_candidate.md:31`）：
    > `| ④ | 真参数物理，只作上界诊断，不计成绩 | 0 | 读生成器的隐藏参数（只在评测侧） |`
  - **说明**：虽然 §8.4 已明确「④ 改称『真参数诊断』，不作为上界」，且草案遵循「§8 效力优先于前文」原则，但若在最终定稿版中将该行内容微调为 `真参数诊断（§8.4：不作为上界），不计成绩`，将可消除读者初读第 2 节表格时的字面困惑。此项仅为美化措辞建议，不影响定稿与后续代码冻结。

---

## 六、结论

综上核验，`reports/V9-P48/PREREG_DRAFT_r4_candidate.md`（SHA-256 前缀 `ef7856e7`）：
1. 完整严密地吸收了实现阶段一级架构裁定（r1、r2、r3、r4）的全部要求；
2. 冻结常量表与现有代码实现与 AWZ 规范逐行一致（未修改的 64000 步与预算上限按约定待后续冻结代码卡落地）；
3. 预算与指标完全忠实于 P94 smoke 实测；
4. H-E1 判定规则与 `analysis.py` 严格对齐，无未受控的表述矛盾。

**最终审核结论：建议定稿**。
