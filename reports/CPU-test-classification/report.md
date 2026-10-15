# ainerzero.M2.A39 执行报告
角色：executor；负责人：grokbot-r2t1；时间：2026-10-14
任务状态：reported；实验状态：未执行（仅 CPU 工程）
任务依据：AinerRelay ainerzero.M2.A39；承接 A37 报告；范围仅限任务列出测试文件与本目录。
修改文件：新增 tests/conftest.py（native_mlx 标记注册、9 模块默认不收集、5 节点默认 deselect、--native-mlx 显式 opt-in）、tests/test_cpu_collection.py（清单完备性 AST 校验、标记校验、哨兵子进程收集零 MLX）；9 个 MLX 模块各加一行 pytestmark；test_smoke.py 两个真实更新用例加 native_mlx 装饰器。无删除、无断言改动、无生产/科学门改动（diff.patch）。
实际执行：run_cpu.py 四模式（flock m0-worker.lock + 16GiB 内存守卫 + guard/sitecustomize MLX 阻断与写入审计）：original-collection(--noconftest)、native-collection-blocked、default-collection、default-cpu-run。
验证结果：
- 原收集：2292 收集（含新增 3，原等价 2289）+ 9 errors（MLX 被阻断）；默认纯 CPU：2287 选中 / 5 deselected / 9 模块忽略，0 error。
- 差异：原有 2289+258 隐藏实例；默认排除 258 实例（9 模块 141 函数）+5 节点，opt-in 恰为 263。
- 默认全量：2287 passed / 0 failed / 5 deselected，110.81 秒；43 进程 real MLX 模块 0、导入尝试 0；内存最低 46.0 GiB（保留 16）。
- 排除清单与原因：见 conftest.NATIVE_MODULES / NATIVE_TESTS 与 metrics.json；smoke 3 实例=真实 run_smoke 优化更新；GridLab 2 例=需真实 mlx.core 的正控/F3 控制。均未覆盖、未运行。
- 身份/来源/守卫反例（onestep 30 项、smoke 预算阻断、GridLab test_no_mlx 等）仍在默认 CPU 范围并通过。
- 预算：预留 0 / 实际更新 0 / 真实模型启动 0。
产物：本目录 */pytest.log、pytest.xml、command-result.json、process-*.json、metrics.json、diff.patch、git-before/after。
失败与限制：
- 原本无任何测试带 metal 标记，`-m "not metal"` 为空操作。
- 开发中一次未加哨兵的 `--native-mlx --collect-only` 导入了 mlx 模块（仅收集、零更新），不作证据。
- tests/test_gridlab.py 不存在；GridLab 节点在范围外 test_gridlab_s07_r2.py，仅由 conftest 按 nodeid 标记，未改该文件。
- 报告路径 reports/ 与项目约定 artifacts/reports/ 不一致，按任务给定使用。
- 会话期间 test_action_preservation_onestep.py 的 SHA 被他方改动，非 A39 所为。
交回统筹：--native-mlx 只是收集开关，不构成运行授权；目前没有已登记的 native pytest 运行器，原生用例须走 CLI/锁/RunStore/预算，需统筹决定是否登记。
