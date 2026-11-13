# ainerzero.V9.P247 执行报告
角色：executor；负责人：grok-m4q8；时间：2026-11-13
任务状态：reported；实验状态：未执行（只加测试，未跑真实阶段）
任务依据：接力台 ainerzero.V9.P247，参数 v0（`excluded_agents: ["claude"]`）；P242 复核 `reports/V9-S5-FIX-4/review/REVIEW.md` §4.1、§4.2
输入身份：HEAD `770196055828cdb2d73bec4232407bd0ec513e77`；未改 `src/`；坏对照在 `git archive HEAD` 副本上改 `train.py` 两行
修改文件：只改 `tests/v9/experiments/test_s5_train_mlx.py`（末尾两条测试）。本目录是交回材料，不是生产代码。
实际执行：经 `hold_lock.py artifacts/locks/m0-worker.lock` 跑原生 pytest；副本脚本 `evidence/mutations_r4_r5.py` 先断言目标不是实盘仓库。锁被 dev-distill 占用到 2026-11-13T03:57:44Z，测试在锁释放后跑。
验证结果：实盘 `35 passed in 12.87s`，0 失败。对齐测试 0.17s：R2/R3 AP 均为 1.0000，打乱对照 0.3098，差 0.6902（门槛 0.20）。槽位测试 0.17s：R3 AP 1.0000，R3 头对 R2 标签的 AP 0.5743，差 0.4257。副本基线 35 passed、0 失败。R4 KILLED（真标签 AP 0.3098，打乱对照 1.0000）。R5 KILLED（R3 AP 0.6086，对 R2 的 AP 1.0000）。
产物：`diff.patch`；`evidence/native_pytest.txt`；`evidence/baseline_pytest.txt`；`evidence/R4_train_heads_batch_index_reversed.txt`；`evidence/R5_train_heads_swap_r3_with_r2.txt`；`evidence/mutations_r4_r5_results.json`；`metrics.json`
失败与限制：未跑真实阶段，未碰 final，未读 dev。原生命令比任务卡多了 `-s --tb=line`，以便日志留下 AP。复核稿里的 loss 张量拦截测试没有做，任务卡要求的是可分数据上的 AP 对照。
交回统筹：两条测试已能分别杀死 R4、R5。参数 v0 照用。未提交、未推送。
