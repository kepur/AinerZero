# S5 登记运行器与预登记非作者复核报告（P248）

- **复核执行者**：gemini-b8e4（AinerRelay 二级执行 agent）
- **复核对象**：
  - 代码提交：`43c9f1d`（包含 `e738322` 及其后续生产守卫 `check_production_frozen` 与 GPU 复位收窄）
  - 预登记文件：`reports/V9-S5-FINAL/PREREG.json`（提交 `4fe5b6f`，SHA256 `2de216957c759227f7b51b01aeafcffa647e22721d53fa4c8bf94419fcd38642`）
- **依据规范**：
  - 规格：`reports/V9-S5-FINAL/SPEC.md`（含补记 1）
  - 设计稿：`reports/V9-S5-DESIGN/DESIGN-r1.md` §3–§7 及实现阶段补记 1–6
  - 交付报告：`reports/V9-S5-FINAL/IMPL/REPORT.md`
- **复核结论**：**全部 8 项核对通过（PASS），准予进入冻结与生产登记运行。**

---

## 逐条核对结论与证据

### 1. 格清单（`build_final_cells`）与 SPEC 2.1 逐项一致：【通过】
- **核对项与结论**：
  - **C-sh**：生成 2 个蒸馏格（种子 0, 1），采用 $A^*$（A1）的教师配置，`perm_seed = 20261113`（取自 PREREG `csh_perm_seed`），池化无标签分区 `s5p1-pool`，学习率取自 `distill_lr`（0.0003）。
  - **R**：生成 2 个蒸馏格（种子 0, 1），采用 $A^*$ 教师配置，`tau = 0.02`，无置换。
  - **A0**：仅跑 $L \in \{512, 2048\}$ 各 3 个种子（共 6 格）。$L=64$ 不重训，复用 dev-distill 钉住的 3 个模型；$L=512$ 开启 `save_ckpts=True`（存 16 个检查点供 GA 使用）。
  - **A4**：仅跑 $L=512$ 3 个种子（共 3 格），`eta = 1.0`，存 16 个检查点供 GA 使用。
  - **A0-R**：仅跑 $L=512$ 3 个种子（共 3 格），`tau = 0.02`。
  - **FT**：全量微调跑 $L \in \{64, 512, 2048\}$ 各 3 个种子（共 9 格），从 $A^*$（A1）蒸馏种子 1 的学生（`distill-A1-s1-student.npz`）起训。
  - **读出头**：
    - C-sh：2 蒸馏种子 × 3 档 $L$ × 3 读出种子 = 18 格。
    - R：2 蒸馏种子 × $L=512$ × 3 读出种子 = 6 格。
  - **超参来源**：学习率（`distill_lr=0.0003`, `supervised_lr=0.001`）、轮数（`distill_epochs=15`, `super_epochs={64:300, 512:60, 2048:20}`）、种子、lab 子集抽样种子（`lab_subset_seed=20261112`）均取自 PREREG。
  - **总格数**：$2 + 2 + 6 + 3 + 3 + 9 + 18 + 6 = 49$ 格，与 SPEC 2.1 及交付报告完全一致。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L493–L657。
  - 单测 `test_final_cells_and_model_specs_match_prereg_without_touching_dev_or_final`（`tests/v9/experiments/test_s5_final_plan.py`）通过。

---

### 2. 训练格不碰 dev 和 final：【通过】
- **核对项与结论**：
  - 训练格的分区守卫：`run_s5p1_final.py` L513–L517 明确断言 `if "final" in p_name or "dev" in p_name: raise GD.GuardError(...)`，任何训练格直接拒入 dev 或 final 分区。
  - 启动阶段断言：`run_final_locked`（L753–L757）在启动新运行前检查 `data_root / final_part` 与 `data_root / shift_part`，若已存在则立即报错拒绝覆盖。
  - 执行时序：全部 49 个训练格运行完成并核对输出后，才调用 `_materialize_and_evaluate`。
  - 评测阶段物化：仅在 `_materialize_and_evaluate` 内部通过 `materialize_partition` 生成一次 `s5p1-final` 和 `s5p1-final-shift`，并把生成的 `manifest.json` SHA 写入事件。
  - 账本与记录隔离：运行开始前后对比 `DEV_LEDGER`（L701 与 L897），若 `dev-uses.json` 发生任何变动直接抛出 `GuardError`。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L701, L753–L757, L834–L849, L897–L899。
  - 原生测试 `test_registered_runner_end_to_end_on_standin_partitions`（`tests/v9/experiments/test_s5_final_native.py`）断言实盘 final 路径未被创建。

---

### 3. 钉住产物守卫顺序：【通过】
- **核对项与结论**：
  - `run_final_locked` 在拿锁（`GD._require_held`）与 `require_fresh_pycache` 之后，在创建任何运行目录（`out.mkdir`）或写登记账本（`begin_registered_run`）之前，立即调用 `verify_prereg_and_Save_Check(prereg_path, args.prereg_sha, repo=REPO)`。
  - 该检查逐项核验：
    1. PREREG 文件 SHA 与 CLI 入参严格相等；
    2. JSON Schema 为 `s5.phase1.prereg.v1`，包含所有必要字典段落；
    3. `check_production_frozen` 拦截任何测试专用字段与常量偏移；
    4. 代码清单 SHA 与仓库文件完全一致（`GD.check_manifest`）；
    5. 当前导入闭包不超出清单；
    6. Git 仓库处于清洁已提交状态（`GD.check_git_clean`）；
    7. 钉住权重文件及其 SHA 校验（`verify_pinned_artifacts`），任一缺失或篡改立即报错。
  - 训练完成后、评测开始前（L835–L840），再次核对冻结代码清单与钉住产物；全部评测结束后（L850–L853）第三次核对代码清单，闭合「最后一格」篡改缺口。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L702–L708, L727–L745, L835–L854。
  - 原生测试 `test_tampered_pinned_weight_is_refused_before_any_output`（`tests/v9/experiments/test_s5_final_native.py`）通过，证实权重篡改在输出前被拒。

---

### 4. 评测配置、模型配对与命名约定：【通过】
- **核对项与结论**：
  - **102 个模型规格**（`build_model_specs`）：
    - A1–A3 读出头：3 臂 × 2 蒸馏种子 × 3 档 $L$ × 3 读出种子 = 54 个（来自 dev-distill 钉住权重）。
    - C-sh 读出头：1 臂 × 2 蒸馏种子 × 3 档 $L$ × 3 读出种子 = 18 个（配对本次运行的 `distill-C-sh-s{d}-student.npz`）。
    - R 读出头：1 臂 × 2 蒸馏种子 × 1 档 $L(512)$ × 3 读出种子 = 6 个（配对本次运行的 `distill-R-s{d}-student.npz`，带 `tau=0.02`）。
    - A0 端到端：9 个（$L=64$ 的 3 个来自 dev-distill 钉住权重；$L=512, 2048$ 的 6 个来自本次运行）。
    - A4 端到端：3 个（$L=512$，本次运行）。
    - A0-R 端到端：3 个（$L=512$，带 `tau=0.02`，本次运行）。
    - FT 全量微调：9 个（$L \in \{64, 512, 2048\}$，本次运行）。
    - 合计：$54 + 18 + 6 + 9 + 3 + 3 + 9 = 102$ 个模型，配对完全正确。
  - **产物落盘与命名**（SPEC 补记 1）：
    - 每个模型在两个分区评测，落盘为 `metrics/{model_id}.{partition}.npz`。
    - 包含完整数组：`r1_logd r2_logit r3_logit r1_target r1_sky r1_obj r2 r3 world_ids clips_per_world`，RLT 模型带 `keep_rate_per_clip`。
    - 旁文件：`metrics/{model_id}.{partition}.disk_groups.json`、`metrics/{model_id}.{partition}.ordering_pairs.json` 及标量指标 JSON。
  - **A4 权重加载兼容**：`_load_student_and_heads` 包含 `has_align = any(k.startswith("align_proj.") for k in npz.files)`，自动挂载 `VJEPAProjHead(d=student.d, out_dim=1024)`，无权重键缺失报错。
  - **GA 检查点评测**：A0 $L=512$（3 种子 × 16 检查点 = 48）与 A4 $L=512$（3 种子 × 16 检查点 = 48）共 96 个检查点，仅在 `s5p1-final` 分区评测，写出 `ckpt-{arm}-L512-s{s}.json` 曲线及 `ga_checkpoints.json`。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L316–L454, L944–L1120。
  - CPU 单测 `test_final_cells_and_model_specs_match_prereg_without_touching_dev_or_final` 通过。

---

### 5. 门计算（`compute_gates_from_metrics`）与对抗变异：【通过】
- **核对项与结论**：
  - **两阶段种子平均顺序**：`nested_seed_mean_on_clips`（L1338–L1349）先遍历每个蒸馏种子内部的 3 个读出种子求平均，再在 2 个蒸馏种子间求平均；之后 `nested_seed_group_stat` 才按 final 世界单位做成对重抽。与设计稿 §4 完全一致。
  - **Bonferroni 98.33% 区间**：GT1、GT2、GT3 采用 `GT_LEVEL = 1.0 - 0.05 / 3.0`（≈ 0.983333）。
  - **GT3 判定**：判定条件为 `gt3_boot["ci_upper"] <= gt3_margin + 1e-12`，其中 `gt3_margin = 0.05 * A0_rmse`，区间上界非劣。
  - **GA 插值与删失**：`ga_decision` 在最后未达标点与首个达标点之间做 AP 线性插值；未达标种子记为总步数上限 `ga_cap`（3840 步）删失；判定比值中位数 $\le 0.7$。
  - **GR 三项判定**：保留率 $\le 0.8$；墙钟下降 $\ge 15\%$（以同一次登记运行内 C-sh 两次蒸馏的每步墙钟中位数为基准）；R2 AP 下降 95% 区间上界 $\le 0.03$。三项必须全部通过。
  - **独立复算一致性**：在合成数据上，运行器 `compute_gates_from_metrics` 与独立复算脚本 `recompute_s5p1_final.py` 计算结果 0 差异。
  - **5 处对抗变异注入复验（在副本中测试，全部成功拦住）**：
    1. *变异 1（种子平均权重倾斜/顺序改变）*：被独立复算比对捕获，报出 GT1、GT2、GT3、GR 共 12 处点估计与区间差异。
    2. *变异 2（Bonferroni 换成 95%）*：被捕获，GT1、GT2、GT3 的 `level` 及区间边界产生 9 处不符。
    3. *变异 3（GT3 判定改用区间下界）*：被捕获，GT3 `ci_upper` 差异被拦住。
    4. *变异 4（GA 达标比值/判定篡改）*：被捕获，GA `point_estimate` 与 `passed` 不符被拦住。
    5. *变异 5（GR 墙钟阈值与通过标记篡改）*：被捕获，GR `passed` 状态不符被拦住。
- **证据**：
  - `evidence/adversarial_gates_test.py` 与运行输出 `evidence/gate_mutations.txt`。
  - CPU 测试 `test_compute_gates_matches_independent_recompute_and_seed_order` 通过。

---

### 6. stand-in 机制不能被生产误用：【通过】
- **核对项与结论**：
  - 提交 `43c9f1d` 新增了专属生产守卫 `check_production_frozen(frozen)`：
    - 若未显式设置 `standin_test: True`，PREREG 若包含任何 `STANDIN_ONLY_KEYS`（`data_root`, `teachers_root`, `student_kwargs`, `clips`, `l_worlds_map`, `pool_n_clips`, `effective_l_clips`），立即抛出 `GuardError`。
    - 检查分区字典必须严格等于 `REAL_FINAL_PARTITIONS`（`s5p1-pool`, `s5p1-lab`, `s5p1-final`, `s5p1-final-shift`）。
    - 检查生产设计常量（`distill_epochs=15`, `batch_size=8`, `tau=0.02`, `ckpt_every_frac=1/16`, `super_epochs`, `readout_epochs`），有任何偏差立即抛出 `GuardError`。
    - `_materialize_and_evaluate` 限制非 stand-in 模式下只接受真名 `s5p1-final` 和 `s5p1-final-shift`，且 $48 \le n\_final \le 96$。
  - 实盘 PREREG `reports/V9-S5-FINAL/PREREG.json` 已通过 `check_production_frozen` 验证，0 包含 stand-in 测试字段，分区与设计常量完全匹配。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L671–L700。
  - 测试 `test_production_prereg_refuses_stand_in_fields_and_off_design_constants`（`tests/v9/experiments/test_s5_final_plan.py`）覆盖了全部 9 种非法注入与篡改情况。

---

### 7. 续跑与登记账本（`--resume` 与整段重评）：【通过】
- **核对项与结论**：
  - **`--resume` 训练格跳过规则**：`_verify_completed_cell_outputs` 严格核实前序 `cell_end` 事件登记的所有输出文件必须在磁盘存在，且其实际 SHA256 与登记值逐字相等；对于保存检查点的格，还验证检查点目录及 `step_*.npz` 文件完整。只有完全相符的格才跳过并计入 `skipped_on_resume`。
  - **评测阶段整段重评**：评测一旦失败，不许单模型续跑。重跑时先删除旧 `metrics/` 目录，重新计算全部 102 个模型与 96 个 GA 检查点；事件账本记录递增的 `eval_attempt`。物化分区仅在前序 `materialize_end` 事件 SHA 校验一致时予以复用，否则整段重新物化。
  - **同一 PREREG 只许成功一次**：`begin_registered_run` 强持锁检查 `artifacts/v9/s5/registered-runs.json`：
    - 若已有相同 `prereg_sha256` 且状态为 `completed`，立即抛出 `GuardError`；
    - 若已有相同 `prereg_sha256` 处于未完成状态，强制必须使用 `--resume` 并保持相同 `run_id`，禁止用新 `run_id` 覆盖；
    - 运行结束后 `finish_registered_run` 将状态更新为 `completed` 或 `failed`。
- **证据**：
  - `reports/V9-S5-PHASE1/run_s5p1_final.py` L236–L305, L772–L833, L1125–L1170。
  - 原生测试 `test_registered_runner_end_to_end_on_standin_partitions` 验证了重复运行同一 PREREG 时的拒绝逻辑。

---

### 8. 冻结前确认 PREREG（`reports/V9-S5-FINAL/PREREG.json`）：【通过】
- **文件基线**：提交 `4fe5b6f`，文件 SHA256 为 `2de216957c759227f7b51b01aeafcffa647e22721d53fa4c8bf94419fcd38642`。
- **逐项核验结果**：
  1. **$A^*$ 选择**：dev-distill 运行（`artifacts/v9/s5/runs/dev-distill-distill-20261112b-20261112T230813Z/stage.json`）中 `selection.a_star.arm` 为 `A1`（score=0.03036，优于 A2 的 0.02679 和 A3 的 0.02946）。PREREG 中的 `a_star` 准确记为 `A1`。
  2. **学习率与 $\eta$**：`reports/V9-S5-PHASE1/tune-devtune-20261112.json` 中选定 `distill_lr=0.0003`, `supervised_lr=0.001`, `eta=1.0`。PREREG 中这三个数值逐字一致。
  3. **final 世界数**：`n_final = 48`，位于 $[48, 96]$ 范围内。
  4. **门与阈值**：GT1 效应 $\ge 0.05$、GT2 效应 $\ge 0.03$、GT3 边际 $0.05 \times A0$（Bonferroni 98.33%）；GA 达标线 $0.95 \times A0$、比值 $\le 0.7$、删失 3840 步；GR 保留率 $\le 0.8$、墙钟降 $\ge 15\%$（基准为本次登记运行 C-sh 中位数）、AP 降 95% 上界 $\le 0.03$。门定义与阈值逐字符合设计稿 §4 与 r1 补记 3。
  5. **72 个钉住权重 SHA**：核对 dev-distill 运行中的全部权重文件（6 个蒸馏学生、6 个投影头、54 个读出头、3 个 A0-L64 学生、3 个 A0-L64 头，共 72 个 `.npz`）。每个文件在磁盘上均实际存在，且其实际 SHA256 与 dev-distill `events.jsonl` 中 `cell_end` 登记的 SHA256、PREREG `pinned_artifacts` 中的 SHA256 三方完全一致（0 差异）。
  6. **代码清单与提交 `43c9f1d`**：PREREG 中登记的 46 个文件代码清单，与 git 提交 `43c9f1d` 树中的对应文件 SHA256 逐项比对，0 缺失、0 差异。
  7. **预算上限**：PREREG 中 `budget_h = 11.8`。用户 2026-11-13 批准总预算为 24.0 h；冻结前阶段已消耗约 12.2 h，余 11.8 h 准确填入 PREREG。
- **证据**：
  - `evidence/verify_all.py` 与生成的 `evidence/prereg_check.json`。

---

## 测试复验汇总

| 测试集 | 运行环境 | 测试用例数 | 结果 | 耗时 | 证据文件 |
|---|---|---|---|---|---|
| `test_s5_final_plan.py` | CPU (.venv) | 7 | 全部 PASS | 281.61s | `evidence/cpu_tests.txt` |
| `test_s5_recompute.py` + `test_s5_runner_plan.py` | CPU (.venv) | 27 | 全部 PASS | 4.42s | `evidence/cpu_tests.txt` |
| `test_s5_final_native.py` | 原生 MLX（持锁 `m0-worker.lock`） | 3 | 全部 PASS | 96.21s | `evidence/native_tests.txt` |
| 门对抗变异测试（5 处破坏注入） | 独立副本 CPU | 5 | 全部拦截 | 114s | `evidence/gate_mutations.txt` |
| PREREG 全量三方一致性校验 | 独立脚本 | 6 组 72 项权重 + 46 代码文件 | 全部 PASS | < 1s | `evidence/prereg_check.json` |

---

## 建议与后续操作

1. **复核通过**：代码提交 `43c9f1d` 逻辑健全、守卫严密；预登记草案 `reports/V9-S5-FINAL/PREREG.json`（`4fe5b6f`）数据与来源完全吻合。
2. **冻结确认**：依据设计稿 §7 第 3 步关于「预登记由作者以外的人确认后冻结」的要求，本复核人（二级 agent gemini-b8e4）在此正式给出**确认批准意见**。
3. **下一步**：统筹者可执行冻结登记，随后即可调度启动约 10 小时的正式登记运行（`run_s5p1_final.py`）。
