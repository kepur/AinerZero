# ainerzero.M2.A40 执行报告
角色：executor；负责人：gemini-f8a2；时间：2026-10-14
任务状态：reported；实验状态：未执行（仅 CPU 工程只读复核）
任务依据：AinerRelay 任务 ainerzero.M2.A40；对 ainerzero.M2.A39（grokbot-r2t1）执行独立第三方只读复核；严格遵守 AGENTS.md / README.md / COORDINATION.md 分工规则。
输入身份：
- `tests/conftest.py`：`95f1490c94d0909e39e8a5cabf37b474cf3e8a1593c677f28e97d9efc5973d3f`
- `tests/test_cpu_collection.py`：`9f6b333d4a2ba1f31ba2371c1b1b5ca8985c8e3ee7b5792a317ab041ab96f573`
- A39 补丁 `reports/CPU-test-classification/diff.patch` 与原始产物目录
- A37 失败与回归日志 `artifacts/reports/onestep-identity-tests/{A37-codex-test-f7ae,A37-r2-gemini-f7k2}/`
修改文件：
- 仅在指定范围 `reports/CPU-test-classification-review/` 目录下新增复核工具、哨兵、运行日志、XML 及报告文件；生产代码、配置、测试用例及身份基准零改动。
实际执行：
- 在共享排他锁 `artifacts/locks/m0-worker.lock` 与 16 GiB 内存安全守卫下，通过独立导入哨兵 `reports/CPU-test-classification-review/guard/sitecustomize.py` 执行 `run_review.py` 六模式验证：
  1. `collection-sentinel`：默认纯 CPU 收集（零 MLX 导入尝试，零实际 MLX 模块加载）；
  2. `test-cpu-collection`：AST 完整性校验、标记存在性及子进程哨兵测试（3 passed, 0 failed, 1.01s）；
  3. `onestep-identity`：一步截断测试套件（29 passed, 1 fail-closed 拦截工作树并发漂移, 9.08s）；
  4. `smoke-budget-failclosed`：预算耗尽阻断测试（1 passed, 0 failed, 1.01s）；
  5. `gridlab-cpu`：GridLab 隔离与防篡改测试（9 passed, 2 deselected, 0 failed, 2.02s）；
  6. `native-blocked-audit`：带 `--native-mlx -m native_mlx` 收集审计（哨兵成功拦截全部 9 个原生模块导入尝试，5 项测试被正确收集，符合预期）。
验证结果：
1. **默认纯 CPU 收集与运行零 MLX / 零模型更新**：
   - 默认入口下 `tests/conftest.py` 成功排除 9 个原生 MLX 模块，5 个真实模型/MLX 节点用例被正确 deselect；
   - 收集与执行期间 `sys.meta_path` 哨兵审计记录的 MLX 导入尝试数为 0，所有子进程加载真实 MLX 模块数为 0；模型实际更新数 0，预留数 0。
2. **Native 清单完备性与断言零改动**：
   - 经独立 AST 静态扫描所有 `tests/test_*.py`，顶层引入 `mlx` 的模块恰好为 `conftest.NATIVE_MODULES` 登记的 9 个文件；
   - 9 个模块共计 141 个测试函数，经参数化乘积展开计算恰好为 258 个测试实例；加上 `conftest.NATIVE_TESTS` 的 5 个测试节点（smoke 3 例 + gridlab 2 例），原生未覆盖总实例严格为 263 项；
   - 逐行校验 A39 `diff.patch` 与实际工作树：A39 仅在 9 个文件添加 `pytestmark = pytest.mark.native_mlx(...)`，在 `test_smoke.py` 2 处添加装饰器，零断言被删除或削弱，零科学门限被放宽。
3. **未覆盖原生用例边界明确，不宣传裸 pytest 路径**：
   - A39 报告及 `conftest.py` 明确将 263 项 native 实例标为未覆盖；
   - `conftest.py` 明确警示 `--native-mlx` 仅为收集开关，并不创建原生运行器，不构成运行授权；真实模型工作必须走 CLI / 共享锁 / RunStore / 预算。
4. **fail-closed 反例与安全防护依然生效**：
   - `test_smoke.py::test_exhausted_shared_daily_budget_blocks_before_loading_backend` 通过，验证预算耗尽在加载后端前 fail-closed 阻断；
   - `test_action_preservation_onestep.py` 中 3 组真实代码变异用例、源码漂移拒绝用例全部通过；其中 `test_identity_file_is_frozen_and_not_authorized` 失败正是因为当前工作树有其他并发任务（M2n-M5）修改了 `cli.py`/`closure.py`，身份门严格触发 fail-closed 拦截，符合设计安全预期；
   - `test_gridlab_s07_r2.py` 中路径篡改拒绝、分区防泄漏等 9 项纯 CPU 测试全部通过。
5. **A37 历史失败日志保留完好**：
   - `artifacts/reports/onestep-identity-tests/A37-codex-test-f7ae/` 与 `A37-r2-gemini-f7k2/` 原始产物与日志完整无缺。
产物：
- 复核报告：`reports/CPU-test-classification-review/report.md`
- 结构化指标：`reports/CPU-test-classification-review/metrics.json`
- 执行汇总：`reports/CPU-test-classification-review/all-runs-summary.json`
- 各模式日志与 XML：`reports/CPU-test-classification-review/runs/*/pytest.log`、`pytest.xml`、`command-result.json`
- 哨兵拦截记录：`reports/CPU-test-classification-review/runs/native-blocked-audit/mlx-import-attempts.jsonl`
失败与限制：
- 因只读复核限制，未运行任何真实 MLX / 模型更新（预算预留 0，实际 0）；
- 工作树存在他方并发任务增加的未暂存代码（`tailself_freeze.py` 等），导致 onestep 活身份比对失败，但其反例与变异拦截功能经验证完全有效。
交回统筹：
- ainerzero.M2.A39 的测试分类方案经独立只读复核成立，判定结果为 `supported`；
- 原生用例的运行入口登记仍需统筹按中央规约统一决议，本复核不授予任何运行权限。
