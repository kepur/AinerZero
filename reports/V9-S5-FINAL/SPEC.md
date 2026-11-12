# S5 登记运行：运行器、预登记与独立复算规格（一级 claude，2026-11-12）

依据：设计稿 `reports/V9-S5-DESIGN/DESIGN-r1.md` 的 §3–§7、r1 复核后补记，以及实现阶段补记 1–6；研究日志 R20261111-S5-start。
本规格只定接口和行为。A*、final 世界数、预算上限这三项的取值，等 dev-distill 跑完后写进 PREREG。

## 0. 总则

- 只新建文件：
  - `reports/V9-S5-PHASE1/make_prereg_s5p1.py`
  - `reports/V9-S5-PHASE1/run_s5p1_final.py`
  - `reports/V9-S5-PHASE1/recompute_s5p1_final.py`
  - 对应的测试文件
- dev-distill 运行期间，不改 `src/`、`run_s5p1.py`、`plan_s5p1.py`。运行器的辅助函数可以 import 复用，不复制。
- **final 两个分区只能由登记运行器生成和读取。** 测试一律用替身命名空间，不得用真名做「允许后生成」的正例，也不得在 monkeypatch `REGISTERED` 之后去查真实分区。见项目记忆「登记分区正例陷阱」。
- **守卫：** 先拿锁再记账；PREREG 的 SHA 不符、代码清单不符、任一钉住的权重 SHA 不符，都在建运行目录之前报错。逐事件落盘；中间权重、检查点、逐段预测都落盘。
- 每格在 spawn 子进程里跑，单格时限、阶段时限、GPU 复位重跑一次，都沿用 `run_s5p1.py` 的现有做法，直接调用那里的函数。

## 1. 预登记 `make_prereg_s5p1.py`（CPU，不拿锁）

输入：
- dev-distill 运行目录（含 `stage.json` 的 `selection`：A* 与功效）；
- tune 文件 `reports/V9-S5-PHASE1/tune-devtune-20261112.json`；
- `--n-final` 可选；不给就取 `max(48, selection.power.n_capped)`，上限 96；
- `--budget-h`：冻结后锁内上限，由一级填。

输出 `reports/V9-S5-FINAL/PREREG.json` 与它的 SHA256。内容：
1. **冻结值：**
   - `a_star`
   - `distill_lr`、`supervised_lr`、`eta`：取自 tune 文件
   - `tau = 0.02`
   - `DISTILL_EPOCHS = 15`；`SUPER_EPOCHS = {64: 300, 512: 60, 2048: 20}`；读出头轮数同 `SUPER_EPOCHS`
   - `batch = 8`；`ckpt_every_frac = 1/16`
   - 种子：蒸馏 (0, 1)；读出 (0, 1, 2)；A0、A4、A0-R、FT 均为 (0, 1, 2)
   - `lab_subset_seed = 20261112`
   - `csh_perm_seed = 20261113`
   - `boot_seed = 20261114`，`n_boot = 2000`
   - `n_final`：`s5p1-final` 与 `s5p1-final-shift` 各取这么多个世界
2. **门与阈值：** 照设计稿 §4 和 r1 补记 3，逐字写进 JSON。
   - GT1、GT2、GT3：L=64，Bonferroni m=3，区间 98.33%；
   - GA：0.95 × A0 末次检查点中位数，线性插值，删失记为总步数，比值 ≤ 0.7；
   - GR：保留率 ≤ 0.8；蒸馏每步墙钟降 ≥ 15%；R2 AP 下降的 95% 上界 ≤ 0.03。
   - GR 的墙钟对照：同一次登记运行里 C-sh 两次蒸馏的每步墙钟中位数。C-sh 与 A* 蒸馏算量相同。另报与 dev-distill 里 A* 蒸馏的对比，只作描述。
3. **钉住的产物（SHA256）：**
   - dev-distill 的 6 个蒸馏学生和 54 个读出头；
   - dev-distill 的 `A0-L64-s{0,1,2}`：学生和头。冻结后不重训，直接在 final 上评，配置与登记 A0 L=64 完全相同；
   - tune 文件。
4. **代码清单：** `run_s5p1_final.py` 的传递闭包，用 `GD.build_manifest`。
5. **预算：** `budget_h`、单格 45 min，以及 dry-run 按实测每步时间给出的逐格估计。

## 2. 登记运行器 `run_s5p1_final.py`

CLI：`--prereg PATH --prereg-sha SHA --run-id ID --report PATH [--dry-run]`。

不消耗 dev 使用：登记运行不读 dev。它写自己的登记账本 `artifacts/v9/s5/registered-runs.json`，同一 PREREG 只许成功跑一次；中途失败后续跑见第 5 条。

### 2.1 训练格（不碰 final）
| 组 | 格 | 说明 |
|---|---|---|
| C-sh | 蒸馏 × 种子 (0, 1) | 教师配置与 A* 相同，`perm_seed = csh_perm_seed`，pool，`distill_lr` |
| R | 蒸馏 × 种子 (0, 1) | A* 加 `tau=0.02` |
| A0 | L ∈ {512, 2048} × 种子 (0, 1, 2) | L=64 复用钉住的三个；L=512 存 16 个检查点，给 GA 用 |
| A4 | L=512 × 种子 (0, 1, 2) | `eta`，存 16 个检查点 |
| A0-R | L=512 × 种子 (0, 1, 2) | `tau=0.02` |
| FT | L ∈ {64, 512, 2048} × 种子 (0, 1, 2) | `train_supervised(init_student=A* 蒸馏种子 1 的学生)` |
| 读出头 | C-sh：2 × 3 档 × 3 种子 = 18；R：2 × L=512 × 3 种子 = 6 | 学生冻结，学习率 `supervised_lr` |

### 2.2 评测（全部训练格完成后，只进行一次）
1. 用 `materialize_partition(name, out, world_range=(0, n_final), registered_run_id=run_id)` 生成 `s5p1-final` 与 `s5p1-final-shift`，写清单与 SHA。目标目录已存在就报错，不覆盖。
2. 在两个分区上评下列模型：
   - A1–A3 的 54 个头、C-sh 的 18 个头、R 的 6 个头；
   - A0 的 9 个、A4 的 3 个、A0-R 的 3 个、FT 的 9 个。
   - 每个模型 × 分区保存 `metrics/<model_id>.<partition>.npz`，内容是 `evaluate()` 返回的全部数组：`r1_logd r2_logit r3_logit r1_target r1_sky r1_obj r2 r3 world_ids keep_rate_per_clip`（有就存）、`clips_per_world`。`disk_groups` 和 `ordering_pairs` 另存为 JSON。同时存一份标量指标 JSON。
3. GA：A0 L=512 与 A4 的 2 × 3 × 16 = 96 个检查点，只在 `s5p1-final` 上评，存每个检查点的 R2 AP 和步数。
4. 按 PREREG 算门，写 `gates.json`，含点估计、区间、判定和种子间标准差。种子平均顺序照设计稿：先在蒸馏种子内平均读出种子，再在蒸馏种子间平均；之后才按世界重抽。
5. 训练格全部完成后、评测开始前，再核对一次冻结清单。全部结束后再核对一次，补上 P242 复核指出的「最后一格」缺口。

### 2.3 续跑
- `--resume <运行目录>`：只重跑没有 `cell_end` 或输出 SHA 不符的训练格。每次续跑记 `resume` 事件。
- 评测阶段一旦开始，就不许用续跑跳过。评测失败就整段重评；重评仍是同一批模型，事件里记明重评次数。

### 2.4 dry-run
列出全部格，并按 dev-tune 与 dev-distill 的实测每步时间估算墙钟：蒸馏 0.285 s/步，监督 0.27–0.40 s/步，读出头每格约 27 s，评测按每段实测。和 `budget_h` 对比，超出就在输出里标出来。

## 3. 独立复算 `recompute_s5p1_final.py`（另一名二级写，非 2 的作者）

- 只读登记运行目录里的 `metrics/*.npz`、JSON 和 PREREG，不 import `run_s5p1_final.py`。
- 指标函数可以调用 `ainerzero.v9.experiments.s5.metrics` 的生产实现。另须对 R2 AP 与 R1 RMSE 各写一份最小的独立实现，在合成数据上与生产实现逐值核对。
- 重算全部门：GT1–GT3、GA、GR，以及「只报告」的各项。输出 `recompute.json`，与 `gates.json` 逐项比对，差异超过 1e-9 就列出来。
- 测试：
  - 合成的逐段预测，构造门必过、门必不过、恰在阈值上三种情形；
  - 自助法重抽用同一种子时结果可复现；
  - 坏对照：在副本里把种子平均顺序改反、把 Bonferroni 换成 95%，测试必须失败。

## 4. 测试要求（第 1、2 部分）

- **默认入口（CPU）：** PREREG 生成与校验；格清单与 PREREG 一致；守卫顺序；dry-run 不拿锁。
- **原生（经锁）：** 替身分区的端到端冒烟。用 `s5test-*` 世界、极小学生，把「登记分区」换成替身名字，跑完训练、评测、门。不得触及真实 final 名称。
- 每条测试都写明一个源码坏对照，改源码的脚本先断言目标不是实盘仓库；副本用 `git archive HEAD` 导出，基线须 0 失败。
