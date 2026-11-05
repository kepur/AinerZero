# ainerzero.V9.P43 执行与独立补审报告

- **角色**：executor（二级执行者）
- **负责人**：`gemini-kzer`
- **时间**：2026-10-26 09:35 +0300
- **任务状态**：reported
- **实验状态**：completed（CPU 事实证据补审完成；零新增 train/eval/verify/MLX/Blender 运行；生产台账只做 hash 检验）
- **被审计任务**：`ainerzero.V9.P42`（作者 `gemini-w9k4`，报告于 2026-10-25 22:45 +0300，原验收人 `claude`）
- **依据与契约**：`ainerzero.V9.P43` 参数 v0；遵循 `AGENTS.md`、`RESEARCH_LOG.md`、`COORDINATION.md`
- **文件范围**：仅修改 `reports/V9-P43/`（`audit_p42_evidence.py`、`metrics.json`、`指标.json`、`REPORT.md`、`报告.md`）；零修改生产台账、零修改源码、零删除固定目录。

---

## 1. 核心审计摘要与边界保护声明

本任务针对已通过验收的 `ainerzero.V9.P42` 报告进行独立的 CPU 事实证据链与边界核验。依据工作契约，不能因前置任务状态为 `accepted` 而跳过证据链验证。

### 生产台账与环境安全保障
1. **生产台账 Hash-Only 保护**：
   - 生产数据库路径：`artifacts/v9/s1/phase1/control.sqlite3`
   - 审计初始 SHA-256：`fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`
   - 审计结束 SHA-256：`fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`（100% 保持锁定不变，WAL/SHM 均不存在）。
   - 绝不使用 SQLite/RunStore/CLI 直接连接打开生产库。
2. **唯一隔离临时目录查询**：
   - 查询通过 Python `tempfile.mkdtemp(prefix="p43_audit_")` 创建唯一动态目录，并在该隔离副本上使用 `URI mode=ro` 只读连接提取实验与运行事实；查询完成后安全清理临时目录，严禁执行原 P42 脚本中危险的固定 `/tmp` 目录删除逻辑。
3. **零模型加载**：
   - 严禁且未将任何 PyTorch/MLX/Safetensors 权重加载至内存；检查点仅做 SHA-256 哈希校验。
4. **P36 保持冻结**：
   - 未触碰亦未修改 P36 孤儿 recovery 状态。

---

## 2. P42 报告逐项成立 / 不成立 / 补证矩阵

| 序号 | 审计项 | P42 宣称与结论 | P43 实测证据与事实核查 | P43 裁定状态 | 精确证据指针与引用 |
|---|---|---|---|---|---|
| **01** | **第一道门：日历硬窗口关闭** | r13 于 14:42:26 启动，4 小时窗口于 18:42:26 永久关闭；拒绝新 run 进入 | 实测 DB `experiments` 记录 `created_at=1792928546.280`，截止时间 `1792942946.280`；当前耗时 >60,000s，余额 0.0s。硬窗口彻底关闭。 | **ESTABLISHED**<br>（完全成立） | `control.sqlite3::experiments`<br>`exp_id=s1-phase1-20261024-r13` |
| **02** | **第二道门：逐 Run 保守求和** | 5 个正式 Run 累计消耗 3819.31s，余额 10580.69s；判定 PASS | 累计 3819.31s 数值正确。但 P42 脚本使用 `cfg.get("reserved_active_seconds", r["active_seconds"])` 存在概念与机制缺陷：`config_json` 不含该运行时字段，实际有效预留账位于 `runs.active_seconds` 与 `daily_budget.reserved_seconds`。因 5 个 run 的 `terminal_elapsed > active_seconds`，`max(...)` 均取实际耗时，数值未受影响。 | **ESTABLISHED WITH METHODOLOGY CORRECTION**<br>（数值成立，方法纠偏） | `worker.py::phase_total_wall_seconds`<br>`lifecycle.py:391`<br>`daily_budget` (2026-10-25: 1057.32s) |
| **03** | **Runner 作业真实状态与组空** | 表格宣称全部 6 个 job 均 `confirmed_empty: true`，且指标标注 `all_jobs_group_empty: true` | 经逐一调用 `relay job-status <job_id> --json`：<br>1) 4 个 completed 作业与 1 个 failed 作业（`arm3-seed1` rc=2）均具备真实的 runner `supervision.confirmed_empty=true` 与 `exec_id` 绑定；<br>2) **但 `arm3-seed2` 实际在启动前被拒绝（canceled），从未派生进程组，无任何 supervision 记录，`exec_id=None`**。P42 将其硬编码为 `confirmed_empty: true` 属于虚构证据。 | **PARTIALLY UNESTABLISHED**<br>（部分不成立：5 项真实，1 项虚标） | Relay Runner 作业真实 JSON：<br>`job-b7ecc70f...` ~ `job-53bec0ed...`<br>`job-c35dfe45...`（supervision: {}） |
| **04** | **final 分区零接触断言** | 盘上 glob `artifacts/v9/s1/phase1/*final*` 无产物，推出「未生成亦未读取」 | **P42 原推导不成立**（输出目录没有产物无法证明训练数据加载没有读取输入）。<br>**经 P43 深度补审成立**：1) 数据集清单 `8234f2f3` 仅注册生成 `train` 与 `development`，盘上无 `final.jsonl`；2) `data.py::require_partition("final")` 显式抛出 `FinalPartitionSealed` 守卫异常；3) 训练 argv 显式只读 `--mode train`，runner stdout 日志证实仅加载 train 与 dev 探针。 | **UNESTABLISHED BY P42 / ESTABLISHED BY P43**<br>（P42 原证据不成立，P43 深度补证后成立） | `dataset_manifest.json`<br>`data.py:67-72`<br>`worker.py:2528` |
| **05** | **R6 批准行有效性** | 全文子串存在 `APPROVED s1-phase1 prereg document_sha256=1cb98a21...`，判定批准有效 | **P42 全文子串检索方法违背 R6 规范**（若出现在注释、引用或未授权节也会误判通过）。<br>**经 P43 R6 限定节算法补审成立**：严格解析 `## R20261021-P1-stageA-budget` 至下一二级标题区间，剔除代码块与缩进引用行，发现且仅发现第 798 行顶格有效批准行，document SHA 精确匹配 `1cb98a21...`。 | **UNESTABLISHED BY P42 / ESTABLISHED BY P43**<br>（P42 检索逻辑不成立，P43 R6 算法补证后成立） | `RESEARCH_LOG.md` L798<br>`pre_registration.json` L2-10 (R6 契约定义) |
| **06** | **产物、检查点与文件漂移** | 检查点 SHA 一致；未做评测；P36 保持冻结 | 实测 21 个代码包文件全部 100% 匹配冻结 SHA（0 文件漂移）；5 个数据集文件全部 100% 匹配；5 个 run 的 `params.npz` 与全部 checkpoints `.npz` SHA-256 均与盘上记录一致；零模型加载。 | **ESTABLISHED**<br>（完全成立） | `pre_registration.json::source_identity`<br>`artifacts/v9/s1/phase1/runs/*/` |

---

## 3. 详细审计事实分析

### 3.1 真实 Runner 作业状态与 Exec 绑定审计
P42 在其报告表格中将 6 个作业全部标为 `confirmed_empty: true`。P43 通过 Relay CLI 提取各作业底层存储的真实审计元数据：

1. **`arm2-seed0` (`job-b7ecc70f…`)**:
   - `status`: `completed`, `returncode`: 0, `reason`: "return code 0"
   - `supervision`: `{'kind': 'exited', 'confirmed_empty': True, 'members_left': [], 'leader_returncode': 0, 'empty_confirm_s': 2.0}`
   - `exec_id`: `eb7d7d66e74d41ff85b90a5fda3fc6c0` (`exec_finish.state`: "finished")
   - stdout log: 2,062,936 bytes, SHA `a15dd26c…e4d7`（盘上文件实测存在且哈希校验一致）
2. **`arm2-seed1` (`job-31a550d8…`)**:
   - `status`: `completed`, `returncode`: 0, `reason`: "return code 0"
   - `supervision`: `{'kind': 'exited', 'confirmed_empty': True, 'members_left': [], 'leader_returncode': 0, 'empty_confirm_s': 2.0}`
   - `exec_id`: `924c69529b524813a0cba6ea292ac42d` (`exec_finish.state`: "finished")
3. **`arm2-seed2` (`job-fb2c4adc…`)**:
   - `status`: `completed`, `returncode`: 0, `reason`: "return code 0"
   - `supervision`: `{'kind': 'exited', 'confirmed_empty': True, 'members_left': [], 'leader_returncode': 0, 'empty_confirm_s': 2.0}`
   - `exec_id`: `9a410cc1b2304b16bdb778200de6d910` (`exec_finish.state`: "finished")
4. **`arm3-seed0` (`job-f3a2b32b…`)**:
   - `status`: `completed`, `returncode`: 0, `reason`: "return code 0"
   - `supervision`: `{'kind': 'exited', 'confirmed_empty': True, 'members_left': [], 'leader_returncode': 0, 'empty_confirm_s': 2.0}`
   - `exec_id`: `fbf6ea460ce8441f98e5f242d552f9c7` (`exec_finish.state`: "finished")
5. **`arm3-seed1` (`job-53bec0ed…`)**:
   - `status`: `failed`, `returncode`: 2, `reason`: "return code 2"（触发系统资源门：swap 增长 1.01G > 1G）
   - `supervision`: `{'kind': 'exited', 'confirmed_empty': True, 'members_left': [], 'leader_returncode': 2, 'empty_confirm_s': 2.0}`
   - `exec_id`: `2ec212f89b0f435d8e7fd5cc035cff49` (`exec_finish.state`: "lost" -> 归档标记丢失后依真实退出的确证更新)
6. **`arm3-seed2` (`job-c35dfe45…`)**:
   - `status`: `canceled`, `returncode`: None, `reason`: "resource lease not granted"
   - `supervision`: `{}`（**无监督记录**）
   - `exec_id`: `None`
   - **核验结论**：该作业在启动前即被调度仲裁拒绝，从未派生进程组，亦不存在组空确认。P42 宣称其 `confirmed_empty: true` 属于事实错误，应纠正为 `canceled_before_launch (no_process_group)`。

---

### 3.2 Final 分区零接触深度证明
P42 仅核对了 `artifacts/v9/s1/phase1/` 目录下 `glob('*final*')` 为空，这仅能证明没有写出带有 final 名称的输出产物，存在严重的证据盲区。

P43 进行了全链路代码与数据输入上界核查：
1. **数据源物理不存在**：预登记绑定的数据集 `8234f2f382281f355b662f05f0bb576d5efac4853f732ddf2e1cdfeee083ad26` 下，`packets/` 与 `truth/` 仅生成了 `train.jsonl` 与 `development.jsonl`，根本不存在 `final.jsonl`。任何针对 final 分区的读取都会直接引发 `FileNotFoundError`。
2. **代码级硬阻断守卫**：`src/ainerzero/v9/experiments/s1/data.py` 中 `require_partition(partition)` 函数明确定义：
   ```python
   if partition == "final":
       raise FinalPartitionSealed(
           "final partition is sealed and must be read once through the sealed channel "
           "only after all phase-1 training; S1 phase 1 does not read it"
       )
   ```
3. **训练工作流执行流**：各 runner 实际执行参数为 `--mode train`，经代码调用链路：
   `ainerzero.cli` -> `commands.py` -> `worker.train_step` -> `data.load_training_windows` -> `data.load_training_episodes(dataset_dir, "train")`。
   全程仅传入常量 `"train"` 与探针中的常量 `"development"`。
4. **结论**：证实 S1 阶段 1 的 5 次实际运行确实零读取、零接触 final 分区。

---

### 3.3 逐 Run 保守求和与预留账本机制纠正
P42 脚本中计算每 run 消耗时使用了如下代码：
```python
cfg = json.loads(r["config_json"])
reserved_active = float(cfg.get("reserved_active_seconds", r["active_seconds"]))
```
经核查 `control.sqlite3` 中 `runs` 表与 RunStore 实现：
- `runs.config_json` 仅保存静态配置快照（包含 `budget.max_wall_seconds: 1200.0` 等），**从未包含 `reserved_active_seconds` 这一键名**。
- RunStore 中 `RunRecord.reserved_active_seconds` 的真实现实映射是数据库表列 `runs.active_seconds`（在 `reserve_work()` 时累加并同步更新 `daily_budget.reserved_seconds`）。
- 5 个 Run 的实际数值对比：
  - `19f2d1eb`: `active_seconds` = 267.34s, `terminal_elapsed` = 881.21s -> `max` = 881.21s
  - `7d155060`: `active_seconds` = 236.45s, `terminal_elapsed` = 892.04s -> `max` = 892.04s
  - `1678cc1c`: `active_seconds` = 227.46s, `terminal_elapsed` = 859.52s -> `max` = 859.52s
  - `403ae816`: `active_seconds` = 187.17s, `terminal_elapsed` = 726.77s -> `max` = 726.77s
  - `92b694d3`: `active_seconds` = 138.91s, `terminal_elapsed` = 459.77s -> `max` = 459.77s
- 累计保守耗时总和：`881.21 + 892.04 + 859.52 + 726.77 + 459.77 = 3819.31s`（余额 10580.69s）。
- **核验结论**：数字计算正确，但 P42 报告对账本来源的解释存在概念性偏差。

---

### 3.4 R6 批准行限定节与凭证核验
P42 仅使用 `expected_approval in res_log_text`，属于全文本模糊子串检索，无法防御无效伪造或失效批准行。

P43 实施符合 R6 契约的限定节算法核验：
1. **作用域定位**：起于 `## R20261021-P1-stageA-budget`（L731），终于下一个二级标题 `## R20261021-push-delete-authorized`（L800）。
2. **过滤条件**：剔除代码块（```）、块引用（>）、列表项内已作废声明（以括号开头并说明原批准行已失效的内容）。
3. **凭证匹配**：严格正则匹配 `^APPROVED s1-phase1 prereg document_sha256=1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30$`。
4. **核查结果**：在作用域内**精确存在且仅存在 1 行顶格有效批准行**（第 798 行）。因此该批准行在 R6 契约下严格有效。

---

## 4. 交回统筹裁决与验收收窄建议

建议统筹者（一级）对 **ainerzero.V9.P42** 的验收范围进行如下收窄与纠正：

1. **维持核心事实结论**：
   - 维持第一道门（日历硬窗口）已永久过期的结论；
   - 维持 4 次训练成功（arm2 种子 0/1/2、arm3 种子 0）、1 次训练失败（arm3-seed1 rc=2 触发资源门）、1 次启动被拒（arm3-seed2 资源租约未批）的既成事实；
   - 维持严禁在 r13 实验 ID 下复跑或续跑的裁定。
2. **收窄与更正证据范围**：
   - **更正作业组空范围**：更正为「5 个已执行作业组空确认成立；`arm3-seed2` 未启动即取消，无进程组监督」；
   - **收回 P42 glob 证据**：以 P43 数据集 manifest 及源码 `FinalPartitionSealed` 守卫作为 final 分区零读取的正式判定依据；
   - **更正预留台账机制说明**：明确 `runs.active_seconds` 与 `daily_budget` 为真实预留账本，修正 P42 报告中关于 config fallback 的不严谨描述。
3. **后续推进建议**：
   - 当前主机环境 swap 状态与显存资源就绪后，由统筹者发起新实验登记（如 r14）；
   - 新登记应覆盖未完成的 `arm3-seed2`、`arm4`（3 个种子）及阶段基准评测。
