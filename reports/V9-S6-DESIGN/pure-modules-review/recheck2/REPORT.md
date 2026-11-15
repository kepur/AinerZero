# P256 末轮复查

> 一级照子代理最终回复原文落盘（HTML 转义已还原）。

建议通过。N1–N4 的修补成立；新增和改动的三组测试没有发现恒真或偏弱的断言。剩一条可选应修，不阻塞。
1. 实盘三个纯 NumPy 测试文件 71 passed（沙盒 26、指标 36、静态 9；`evidence/f01-live-tests.txt`）。sandbox.py、analysis.py、epinet_mlx.py 自 HEAD 4cdbee9 以来未改。
2. 18 个变异全部由我自己复现杀死：`recheck/evidence/mutate_recheck.sh` 原样复跑，副本为 HEAD 加 4 个改动文件，与工作树逐字节相同，基线 72（`f02-mutations.txt`）。作者的 `mutate_pure.sh` 未改，复跑 31 行与新 `mutate_pure.log` 去掉耗时后逐行相同，29/29 被杀死（`f04b`）。
3. 端到端测试：POINT、INTERVAL 照 DESIGN-r2 §4 写死（`test_s6_analysis.py:318-321`），逐门核对 point_ok、interval_ok、per_replicate_ok、passed。near_miss 断言 GZ-W 和 GP 都是（点值不过，区间过，总判不过）（`:368`），这条断言真的会咬。
4. 陷阱测试：构造后、揭示后都断言 `set(vars(cp)) == POOL_ATTRS`（`test_s6_sandbox.py:140`、`:143`），并要求揭示后模拟器恰好被调用 30 次。
5. 静态检查：模块级扫描覆盖 if/try/with 嵌套块，用到 cells.py、sandbox.py、epinet_mlx.py 三个模块，并有 try 块别名的自测。
6. 可选应修（F1，`f03`）：存活 72 passed。把 `W.physics` 写成 `CandidatePool.__init__` 的默认参数 `_p=W.physics`，再把预算的一步结果存进模块级字典 `_SEEN`，能同时绕过陷阱、`vars` 检查和模块级扫描。原因是 `_module_level_names` 跳过了类体与函数默认参数（`test_s6_cells_static.py:66`），而这两样在导入时都会执行，与它自称「导入时运行的代码」（`:61`）不符。这是故意的两层规避，不是自然回归，所以不阻塞；扫描可以顺手加上类体、默认参数和装饰器。
7. 证据：`recheck2/evidence/`（`f01`–`f04b`、`extra_mutant.sh`、`citations.txt`），`SHA256SUMS.txt` 覆盖全部证据文件。纯 NumPy，未跑 MLX；只写本目录，未提交；需 MLX 的 `test_s6_cells_native.py` 改动未运行。
