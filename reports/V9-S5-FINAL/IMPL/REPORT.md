# P245 登记运行器与预登记生成器：交付报告

- 初稿：gemini-k7x2（11-12 23:10–23:43，之后无心跳）。
- 续写：一级 claude（11-13 05:10 起），提交 e738322。
- 依据：`reports/V9-S5-FINAL/SPEC.md` 第 0–2、4 节及补记 1。

## 改动
- `reports/V9-S5-PHASE1/run_s5p1_final.py`：登记运行器。
  - 49 个训练格：C-sh 2、R 2、A0 6、A4 3、A0-R 3、FT 9、读出头 24；
  - 训练格全部完成后，生成一次 final 与 final-shift，评测 102 个模型和 96 个 GA 检查点，写 `gates.json`；
  - 支持 `--resume` 与 `--dry-run`；记登记账本，同一 PREREG 只许成功跑一次；
  - 沿用 `run_s5p1.py` 的 GPU 复位重跑和逐格冻结清单核对。
- `reports/V9-S5-PHASE1/make_prereg_s5p1.py`：钉住 72 个冻结前产物（6 学生、6 投影头、54 读出头、A0-L64 的 3 个学生和 3 个头）、tune 文件和代码清单，并附 dry-run 预算。
- 一级在初稿上修了三处：
  1. 老师特征路径改为 `teachers/<teacher>/<partition>`。初稿是 `<partition>/<teacher>`，实盘启动检查会报错；
  2. 分区清单 SHA 改为对写出的 `manifest.json` 求。`materialize_partition` 返回的是清单内容，不含 SHA；
  3. `_manifest(repo)` 的每一项都从 `repo` 取，仓库副本因此能钉住自己的文件。
- `tests/v9/experiments/test_s5_final_native.py`（新，原生）：
  - 用 s5test 替身分区和极小学生，端到端跑完 49 格、评测和门；
  - 核对命名约定、登记账本、同一 PREREG 拒绝第二次运行、钉住权重被改动时在任何输出之前拒绝；
  - 断言替身名不在 `REGISTERED` 里，真实 final 目录从未出现。

## 验证
- 原生：`test_s5_final_native.py` 3 passed（经锁）。
- CPU：`test_s5_final_plan.py`、`test_s5_runner_plan.py`、`test_s5_recompute.py` 共 32 passed。
- 交叉核对：在替身运行上，用 P246 复算脚本独立重算（初稿，返工中；临时副本里把分区名换成替身名）。GT1、GT2、GT3、GA、GR 五个门的点估计、区间和判定与 `gates.json` 完全一致，差异 0 项。
- 用真实 dev 产物生成 PREREG 草稿（不入库）：A\*=A1，η=1.0，n_final=48。dry-run 估计训练 9.48 h、评测 0.42 h，合计 9.9 h，不含每格的启动开销。

## 未做与风险
- 门的计算没有逐项手工复核，依赖 P246 独立复算交叉核对。
- dry-run 没计每格的启动开销，按约 0.5 h 估。
- 初稿约 2500 行，一级只通读了守卫、格清单、格主体、预检和物化部分。
