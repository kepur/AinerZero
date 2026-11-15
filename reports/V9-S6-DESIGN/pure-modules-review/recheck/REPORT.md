# P256 复核之复查（作者修补后）

> 一级照子代理最终回复原文落盘（HTML 转义已还原）。

打回（小修）：首轮必修 1–2、应修 3–6 都已落实，我首轮的 14 个变异全部被杀死；但针对新测试新加的 N1–N4 全部存活，其中 N2 改的是门的判定规则（必修）。
1. 实盘三个纯 NumPy 测试文件 67 passed（沙盒 26、指标 35、静态 6；`evidence/r01-live-tests.txt`）。隔离副本 = `git archive HEAD`（4cdbee9）+ 4 个改动文件，与工作树逐字节相同；基线 68 项（含一条来源断言）。
2. 我的 14 个旧变异（R1、R1b、R2–R5、Q1–Q6、X1、X2）全部被杀死，与作者的 `p256-reviewer-mutants-recheck.log` 一致（`r02-mutations.txt`）。作者的 `mutate_pure.sh` 原样复跑，去掉耗时后 31 行与新 `mutate_pure.log` 逐行相同，29/29 被杀死（`r04b`）。
3. 新测试的读法：
   - 端到端测试用合并求和与写死的 q（5.261057575066 / 2.776445105198），是独立重算，不是恒真式；
   - 它只借用了 `AN.world_draws` 和 `GATES` 的区间元组，两者分别由抽取次序测试、门表测试钉住；
   - 陷阱测试、两组失败测试、墙柱状态测试的断言都会咬。
4. 必修（N2）：把 `analysis.py:265` 改成 `point_ok = math.isfinite(x)`，即不看点值判据，68 项全过。
   - 原因：端到端测试只核对了 `interval_ok`（`test_s6_analysis.py:347`），没有核对 `point_ok`、`per_replicate_ok`、`passed`。
   - 实测（`r03`）：GZ-W 点值 0.970（> 0.95）、GP 点值 0.020（< 0.03）都由「不过」变成「过」。
   - 建议：在端到端测试里照设计稿写死点值门槛，逐门核对这三个字段。
5. 应修（N1）：sandbox.py 加模块级 `_phys = W.physics`，构造时用它算出全部候选的一步结果，68 项全过。
   - 原因：陷阱只替换了模块属性（`test_s6_sandbox.py:128`），拦不住预先存下的引用。实测构造时陷阱计 0 次，实例多出 `_cache`（`r03`）。
   - 建议：构造后、揭示后都断言 `set(vars(cp))` 恰为文档列出的 9 个属性。
6. 应修（N3、N4）：别名禁令只扫 cells.py 顶层的赋值和导入（`test_s6_cells_static.py:57-58`、`:7`），两种写法都能同时绕过静态检查和封印：
   - N3：把别名放进 cells.py 顶层的 `try` 块；
   - N4：别名放在 sandbox.py，由 `closest_pair` 经 `S._phys` 调用。
   - 建议：递归检查模块级语句（不进入函数和类体），并把同一禁令用到 sandbox.py 和 epinet_mlx.py。
7. 未运行：`test_s6_cells_native.py` 的改动（封印新增 `revealed_pool` 一条路）需要 MLX。证据在 `recheck/evidence/`（`mutate_recheck.sh`、`r01`–`r04b`、`survivor_probe_recheck.py`、`citations.txt` D1–D6）；纯 NumPy，只写本目录，未提交。
