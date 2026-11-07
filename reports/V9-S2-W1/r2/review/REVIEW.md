# 【非作者复核报告】S2 生产路径集成 W1（P163 r2）

- **复核者自证：** 本复核由执行 agent `gemini-b7x4`（Session `sess-bf83650114e6`）独立完成。自证非被验任务 `ainerzero.V9.P163` 及其相关阶段的作者（排除作者 `claude`、`gemini-8f4b`、`gemini-k4m9` 及其同会话别名），独立只读核查，未修改任何生产或测试源码。
- **复核目标：** 任务 `ainerzero.V9.P163`（r2：数据与训练接线，附录 D1/D2 及 F1–F8 打回项整改）。
- **核查基准 Commit：** `1da13e3fd799c2ba1ca6088c8b719de655697ed2` on `main`。
- **结论：** **`RECOMMEND_ACCEPT`**

---

## 1. 范围与只读状态核验

1. **工作树审计：**
   - 目标相关生产文件：
     - `src/ainerzero/cli.py`：仅添加 `--partition`，无 `--repo-root` / `--lock` 别名。
     - `src/ainerzero/v9/experiments/s2/commands.py`：实现 F1/F3/F4/F6/F7 及训练接线逻辑。
     - `src/ainerzero/v9/experiments/s2/data_runner.py`：仅认 `--partition`，移除三层回退。
     - `src/ainerzero/v9/experiments/s2/train_runner.py`：F5 留出集防篡改重算与验证，`eval_every=200`。
     - `src/ainerzero/v9/experiments/s2/worker.py`：`record_metrics` / `get_run_metrics` 读写 metadata 表，失败记录 `failed` 状态。
   - 专用测试文件：`tests/v9/experiments/test_s2_w1_wiring.py`（23 条用例全部通过）。
   - 本次复核全程只读，对 `src/` 与 `tests/` 无任何修改。

2. **默认/回退扫描：**
   - 针对 `or []`、`or {}`、`getattr(..., default)`、`base_success_rate`、`preferred_`、`eval_episode` 等进行逐行审查。
   - `data.py` 中的 `0.5` 为泊松混合权重注册常数 (`K_WEIGHTS = (0.5, 0.3, 0.2)`)，无业务回退。
   - `data_runner.py` 中的 `REGISTERED_HOST_ROOT` 回退为 P138 兼容过渡项。
   - 生产训练入口无任意常数回退。

---

## 2. F1–F8 打回项逐项核验

| 打回项 | 代码落点 | 核验结果与机制 |
|---|---|---|
| **F1 smoke 步数** | `commands._resolve_smoke_train_steps` | 严格经 `worker.ledger_read_snapshot` 只读事务读取最近一次 smoke；必须同时满足 `r.state == "completed"` 与 `metrics.get("passed") is True`（已彻底清除 `or status == "completed"` 漏洞）；步数仅从完成 metrics 中提取，不读 config_json。覆盖 5 组边界用例。 |
| **F2 smoke 包装** | `worker.execute_work_cell` | runner 仅返回运行状态字典，不直接写坏 config；遇到 `passed is False` 时 worker 自动将状态置为 `failed`，并通过 `record_metrics` 将结果持久化至 metadata 表。 |
| **F3 arm / seed 校验** | `commands.s2_phase1_command` | `train` 模式强制校验 `--arm` 与 `--seed`；不在注册集合即刻抛出 `argument_validation` 错误；在执行前通过 `adapters_mlx.canonical_arm` 规范化为统一格式，避免检查点路径歧义。 |
| **F4 partition** | `commands.py` / `data_runner.py` | `generate-data` 仅认 `--partition`（限 `train`, `dev`, `final`）；传入 `--arm` 立即拒绝；种子命名空间严格且仅自 `spec.SEED_NAMESPACES` 读取，已彻底移除三层回退。 |
| **F5 留出集** | `train_runner.py` | `HOLDOUT_WORLDS.json` 为强制存在；使用 `s2p1-train-v1\|holdout\|{w}` 的 SHA256 排序动态重算留出集，与记录不符立即抛出篡改异常；空列表或无效目录名均被严格拦截。 |
| **F6 步数覆盖** | `commands.py` | `train` 模式显式传入 `--steps` 被直接判定为非法，返回 `STEPS_OVERRIDE_FORBIDDEN`，强制从账本 smoke 记录解析。 |
| **F7 代码身份** | `commands.py` / `cli.py` | CLI 彻底移除 `--repo-root` 与 `--lock`；`repo_root` 经 `Path(__file__).resolve().parents[5]` 从当前包文件物理路径推出，并断言其下正包含正在执行的 `commands.py`。 |
| **D2 训练接线** | `commands.py` / `train_runner.py` | 数据目录严格绑定 `datasets/train`；模型选择评估间隔严格绑定注册常数 `MODEL_SELECTION_EVERY_STEPS = 200`。 |

---

## 3. 隔离副本变异测试（7/7 全部击杀）

在独立临时隔离目录（`/var/folders/.../p165_mut_*`）中复制 `src/`、`tests/`、`pyproject.toml`，并断言模块 import 严格指向沙箱环境。基线通过 23/23。针对作者 6 处坏对照 + 复核者自做 1 处变异进行逐项注入、测试、还原与基线复验：

| 变异 ID | 变异描述 | 目标文件 | 预期击杀用例 | 实际表现 | 状态 |
|---|---|---|---|---|---|
| **M1** | 允许已完成但 `passed=False` 的 smoke 记录提供步数 | `commands.py` | `test_completed_smoke_with_passed_false_is_not_usable` | 变红，用例捕获 | **RED (killed)** |
| **M2** | 绕过 `train_runner` 中留出集篡改重算比对 | `train_runner.py` | `test_holdout_file_is_mandatory_and_tamper_checked` | 变红，用例捕获 | **RED (killed)** |
| **M3** | 将模型评估选择间隔从 200 改为 5 | `train_runner.py` | `test_model_selection_cadence_is_registered` | 变红，用例捕获 | **RED (killed)** |
| **M4** | 将训练默认数据目录从 `datasets/train` 改为 `data` | `commands.py` | `test_production_train_runner_reads_registered_data_dir_and_smoke_steps` | 变红，用例捕获 | **RED (killed)** |
| **M5** | 移除 arm 参数的 canonical 规范化 | `commands.py` | `test_train_arm_is_canonicalized_before_execution` | 变红，用例捕获 | **RED (killed)** |
| **M6** | 将 repo_root 获取方式回退为 `Path.cwd()` | `commands.py` | `test_default_repo_root_is_the_package_checkout_not_cwd` | 变红，用例捕获 | **RED (killed)** |
| **M7** (自做) | 绕过 `train` 参数中禁止 `--steps` 覆盖的校验 | `commands.py` | `test_train_refuses_steps_override` | 变红，用例捕获 | **RED (killed)** |

- **变异击杀率：** 7 / 7 (100.0%)，无存活变异，无测试漏洞。
- 详细结果落盘：`reports/V9-S2-W1/r2/review/mutation_summary.json`。

---

## 4. 纯 CPU 回归与文件系统无副作用核验

1. **纯 CPU 约束：**
   - 严禁加载 MLX 原生硬件，纯 CPU 模式运行。
   - `python3 -m pytest -q tests/v9/experiments/test_s2_w1_wiring.py`：23 条全部通过（耗时 0.9s）。
   - 默认全量 pure-CPU 验证：3683 passed, 6 deselected（耗时 294.15s）。
2. **实盘 artifacts/ 状态比对：**
   - 运行前递归扫描 `artifacts/`（84,250 个条目），记录 `st_size`、`st_mtime_ns`、`st_ctime_ns`、`st_ino`。
   - 运行 `test_s2_w1_wiring.py` 后比对：**差异为 0（size, mtime, ctime, inode 完全不变）**。
   - Git status 显示工作区干净，无任何未经授权的伪造或残留写入。

---

## 5. 作者报告陈述抽验

1. **陈述 1：** `commands._resolve_smoke_train_steps` 经 `ledger_read_snapshot` 读取，只看最近一次 smoke，需 completed 且 passed 为 True。
   - **核实：** 源码第 288–323 行严格实现此逻辑，完全属实。
2. **陈述 2：** `HOLDOUT_WORLDS.json` 必须存在，按规则重算后比对，不一致即判为篡改。
   - **核实：** `train_runner.py` 内部计算 SHA256 排序前 N 个 world 并与文件反序列化集合对比，属实。
3. **陈述 3：** 在 `worker.py` 中增加了 `record_metrics` 与 `get_run_metrics`；CLI 仅新增 `--partition`。
   - **核实：** `worker.py` 包含类方法与独立函数，`cli.py` 仅增加 `--partition` 参数，无多余接口泄漏，属实。

---

## 6. 最终建议

被验任务 `ainerzero.V9.P163`（r2）彻底解决了上一轮的全部打回项（F1–F8），接线严密，断言完备，反捏造与防篡改逻辑完好，7 项变异对照全部变红，且完全满足纯 CPU 运行及工作区只读无损要求。

建议验收：**`RECOMMEND_ACCEPT`**
