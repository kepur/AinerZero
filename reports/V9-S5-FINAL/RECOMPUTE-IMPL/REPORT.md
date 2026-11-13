# ainerzero.V9.P246 执行报告

角色：executor；负责人：grok-q8n4；时间：2026-11-13
任务状态：reported；实验状态：未执行（纯 CPU 复算脚本与测试，无登记运行、无 GPU）
任务依据：AinerRelay `ainerzero.V9.P246` 参数 v4；`reports/V9-S5-FINAL/SPEC.md` §2.2 / §3 / 补记 1；`reports/V9-S5-DESIGN/DESIGN-r1.md` §4 与 r1 补记第 3 条
输入身份：上一棒 `composer-m7k2` 的复算脚本与测试；设计常量与 `reports/V9-S5-FINAL/PREREG.json` 逐项核对
修改文件：`reports/V9-S5-PHASE1/recompute_s5p1_final.py`（分区、换域只报告、阈值标红）；`tests/v9/experiments/test_s5_recompute.py`（子条件翻转，删掉重言式突变测试）；本目录报告与 evidence
实际执行：`.venv/bin/python -m pytest -q tests/v9/experiments/test_s5_recompute.py`；`.venv/bin/python reports/V9-S5-FINAL/RECOMPUTE-IMPL/evidence/mutation_controls.py /tmp/p246-rc-mut`
验证结果：正式测试 18 passed / 0 failed。git archive 副本上基线 18 passed；8 处源码改动全部被正式测试拦住（见 evidence）
产物：`reports/V9-S5-PHASE1/recompute_s5p1_final.py`、`tests/v9/experiments/test_s5_recompute.py`、`reports/V9-S5-FINAL/RECOMPUTE-IMPL/`
失败与限制：未对实盘登记目录复算；未改 `src/`、`run_s5p1.py`、`plan_s5p1.py`、已有其它测试；未碰 final / dev / `artifacts/v9/s5/runs/`；未提交、未推送
交回统筹：五个门的判定式未改，便于与已做过的替身交叉核对对齐。PREREG 与设计 r1 不一致时脚本写 `threshold_audit.status=red` 并以退出码 2 结束

## 相对上一棒改了什么

上一棒的 `test_mutation_*` 先改副本，再在 `pytest.raises` 里写一条必然失败的断言。一级用正式测试（排除 mutation）复核时，6 处源码改动只拦住种子平均顺序。本次删掉这类测试，改为正式测试本身失败。

正式测试现在单独翻转：GT1/GT2 点估计达标但下界 ≤ 0、下界 > 0 但点估计低于阈值；GT3 下界 ≤ 边际 < 上界；GA 插值与阶梯判定不同、删失步数等于 `ga_cap`；GR 保留率、墙钟、AP 下降各自单独不达标。PREREG 不写区间水平时，复算用 `1-0.05/3`，并与 95% 下界不同。

分区名从 `PREREG.frozen.partitions` 读取（缺省才用 `s5p1-final` / `s5p1-final-shift`）。换域只报告项纳入 `{final_shift}.shift_bg` 与 `.shift_all`。文件名约定 `metrics_filename_contract.txt` 未改。

## 坏对照（evidence/mutation_controls.py）

副本用 `git archive HEAD` 导出后只改 `recompute_s5p1_final.py`，再跑本任务正式测试。结果：

| 改动 | 结果 |
|---|---|
| 基线 | 18 passed |
| 种子平均顺序对调 | KILLED |
| GT1 去掉 `ci_lower>0` | KILLED |
| GT3 改用 `ci_lower` | KILLED |
| GR 跳过 `keep_ok` | KILLED |
| GR 跳过 `ap_ok` | KILLED |
| GT1 效应阈值改为 0 | KILLED |
| Bonferroni 改为 95% | KILLED |
| GA 改用阶梯步数 | KILLED |
