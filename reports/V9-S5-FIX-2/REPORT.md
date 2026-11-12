# ainerzero.V9.P240 执行报告
角色：executor；负责人：grok47-m4p8；时间：2026-11-12
任务状态：reported；实验状态：未执行
任务依据：V9 S5 修复 2；DESIGN-r1 实现阶段补记第 5 条（a60dc2c）；参数 v0 照用
输入身份：HEAD `6d3bd7af117cd697fe186bb044827247c0f32932`。源码哈希见 `SHA256SUMS.txt`。
修改文件：`heads.py` 新增 `FlatHead`（LayerNorm → 每 token k=4 分 → 展平 → 按位置线性映射到 12×7；BCE with_logits、mean、无正例权重），`GridHead` 保留。`train.py` 的 R2/R3 默认改为 `FlatHead(d=student.d, k=4)`；`train_supervised` / `train_heads` / `predict` 开 RLT 时与 R1 共用 `restore_runs` 的结果，不再传注意力掩码；调用方传入的 r2、r3 照用。`tests/v9/experiments/test_s5_train_mlx.py` 把「GridHead 用 mask」改成「FlatHead 读还原后的最后一个管长」，并加了下面的测试。`train.py` 里的 `ItemCache` 是并行卡 P239 的改动，本卡没有回退。未改 student、losses、tokens、metrics、labels、world、render、materialize、extract、data、运行器、设计稿和已有报告；未写 `artifacts/v9/s5/runs/`，未碰 final。
实际执行：持锁跑原生 pytest（见下）；坏对照脚本先把源码拷到临时目录并断言目标不是实盘仓库，再改副本。默认入口全量不带 `--native-mlx`。
验证结果：原生 `53 passed in 59.49s`。默认入口 `4347 passed, 7 deselected in 1334.20s`。冒烟：s5test 2 世界 × 2 段，冻结随机学生，只训 FlatHead 40 轮，训练集 R2 AP = 1.000000，正例率 = 0.011905。门槛只有「明显高于正例率」（实现为 AP > 正例率 + 0.05）。
产物：本目录 `REPORT.md`、`metrics.json`、`diff.patch`、`SHA256SUMS.txt`、`evidence/`。
失败与限制：没有跑真实阶段，没有读 dev，没有实盘训练。`diff.patch` 里 `train.py` 的 `ItemCache` 段落属于 P239，不是本卡的行为改动。坏对照 M3 第一版替换把缩进写坏了（pytest rc=2），改正锚点后由数值断言杀掉。
交回统筹：参数 v0 没有异议。读出头在冻结前更换，本卡没有用 dev 做选择。

## 坏对照（副本，不是实盘仓库）
1. 只读最后管长：`[:, 7]` 改成 `[:, 0]`。`test_flat_head_reads_only_the_last_tube` KILLED。
2. 按位置：展平前对 196 个位置平均再广播。测试内对照互换后输出差 < 1e-5；源码 M2 的差约 3e-8，不大于 1e-3。KILLED。
3. RLT：`predict` 改送未还原 token，`train_heads` 改送 `b_tokens`。计数包装要求送进 FlatHead 的整段等于 `restore_runs` 的输出，两处都 KILLED。另：被并掉位置填 0 与 1e3 时 r2/r3 logits 相同。
4. 小规模可学：头恒输出 0 时训练集 R2 AP = 0.007463，低于正例率 0.011905。KILLED。
5. 损失：BCE 加正例权重后得到 4.573，手写无权重 mean 是 0.882。KILLED。
原有 restore_runs、A4、C-sh 测试在上述 53 项里通过。
