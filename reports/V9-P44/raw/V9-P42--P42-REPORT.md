# ainerzero.V9.P42 执行报告
角色：executor；负责人：gemini-w9k4；时间：2026-10-25 22:45 +0300
任务状态：reported；实验状态：completed（CPU 事实审计完成；不代表模型能力验收）
任务依据：ainerzero.V9.P42 参数 v0；遵循 `AGENTS.md`、`RESEARCH_LOG.md`（R20261025-P40-window-correction 纠正授权）及两级协作契约
输入身份：
- 被验证任务：ainerzero.V9.P40（作者 antigravity-v7k2，报告于 2026-10-25 15:55 +0300）
- prereg 文件 SHA256：`9868b913d3cea59acc860e17b6362afcbbb746990e0ddb4962bc6b78123e0f0d`
- prereg document SHA256：`1cb98a21052c6db9b8ce4d8ff0ddcaecd996407e26d00143a62bd1e522ff5b30`
- 生产台账路径：`artifacts/v9/s1/phase1/control.sqlite3`，审计全程 SHA256 锁定为 `fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`（WAL/SHM 均不存在）
- 审计副本路径：`/tmp/ainerzero_p42_audit_copy/control.sqlite3`（查询前后 SHA 均为 `fe31fee6c47b47b70b42fd04c5ddabbcca26483cc191deaa7a65b00a8ef2ed60`）
修改文件：仅 `reports/V9-P42/`（`audit_dual_ledger.py`、`audit_execution.log`、`P42-metrics.json`、`P42-REPORT.md`）；零修改源码，零修改生产台账
实际执行：
- 生产台账仅做 `shasum -a 256`，严禁且未以 RunStore/SQLite/CLI 连接打开生产库；
- 建立隔离副本 `/tmp/ainerzero_p42_audit_copy/`，以 URI `mode=ro` 只读连接提取实验与运行事实；
- 执行 `python3 reports/V9-P42/audit_dual_ledger.py`，完整复核双账门禁、6 个 runner 作业、5 个 run 产物目录、检查点 SHA 与白名单。

---

## 阶段墙钟双账核验事实

S1 阶段运行受两道独立且并发的墙钟安全门约束：

| 门禁机制 | 规范定义与实现源 | 预算上限 | 计费基准 / 起点 | 精确截止时间 / 耗时 | 当前余额 | 状态与核验裁定 |
|---|---|---|---|---|---|---|
| **第一道门：RunStore 实验日历硬窗口** | `runtime/lifecycle.py::_experiment_record`<br>`max(0, max_wall - max(0, now - exp.created_at, active_s))` | 14,400.0 s<br>(4.00 h) | 实验 `created_at`：<br>`2026-10-25T14:42:26.280+0300`<br>(1792928546.280) | 截止：`2026-10-25T18:42:26.280+0300`<br>实测已过：28,770.66 s (7.99 h) | **0.00 s**<br>(已超期 14,370.66 s / 3.99 h) | **HARD EXPIRED**<br>实验硬窗口已彻底关闭，拒绝任何新运行进入 |
| **第二道门：S1 逐 Run 保守求和** | `v9/experiments/s1/worker.py::phase_total_wall_seconds`<br>`sum(max(reserved_active, updated_at - created_at))` | 14,400.0 s<br>(4.00 h) | 5 个正式 Run 逐行保守耗时求和：<br>881.21 + 892.04 + 859.52 + 726.77 + 459.77 s | 累计消耗：<br>3,819.31 s<br>(1.06 h) | **10,580.69 s**<br>(2.94 h) | **PASS**<br>已执行 run 累计实际用时未超 14400s 额度 |

### 双账综合结论
两道门同时生效且缺一不可。虽然第二道门（各 run 运行耗时累计）尚余 10,580.69 秒，但第一道门（日历硬窗口自 14:42 起算 4 小时）已于 18:42:26 永久关闭。**因此，P40 不能以“等待 swap 降低后继续执行”为由直接续跑**，原实验 ID 下启动任何新 run 均会被 RunStore 拒绝。必须关闭 P40，并另行新登记实验（如 r14）。

---

## P40 作业盘点与产物审计明细

对 Relay Runner 作业、RunStore 记录以及盘上产物进行三方独立核验，结果完全吻合：

| 作业 / 臂标签 | Relay Job ID | Run ID | 最终状态 | 退出码 | 更新步数 | 盘上产物与 Checkpoint SHA256 | 进程组清空 |
|---|---|---|---|---|---|---|---|
| **arm2-seed0** | `job-b7ecc70f…` | `19f2d1eb…` | **completed** | 0 | 3510 / 3510 | `params.npz` SHA `9d155fbf…1702` (一致)<br>ckpts: 0, 439, 878, 1755 | `confirmed_empty: true` |
| **arm2-seed1** | `job-31a550d8…` | `7d155060…` | **completed** | 0 | 3510 / 3510 | `params.npz` SHA `c4d16f6e…f643` (一致)<br>ckpts: 0, 439, 878, 1755 | `confirmed_empty: true` |
| **arm2-seed2** | `job-fb2c4adc…` | `1678cc1c…` | **completed** | 0 | 3510 / 3510 | `params.npz` SHA `f7f9a661…cf01` (一致)<br>ckpts: 0, 439, 878, 1755 | `confirmed_empty: true` |
| **arm3-seed0** | `job-f3a2b32b…` | `403ae816…` | **completed** | 0 | 3510 / 3510 | `params.npz` SHA `577429aa…f51e` (一致)<br>ckpts: 0, 439, 878, 1755 | `confirmed_empty: true` |
| **arm3-seed1** | `job-53bec0ed…` | `92b694d3…` | **failed** | 2 | 2566 / 3510 | 中途终止：无 `completion.json` 与 `params.npz`<br>仅存 ckpts: 0, 439, 878, 1755<br>触发 `resource_gate`（avail 15.98G < 16G, swap+1.01G > 1G） | `confirmed_empty: true` |
| **arm3-seed2** | `job-c35dfe45…` | 无 | **canceled**<br>(未启动) | — | 0 / 3510 | 未启动：relay arbiter 拒租（swap 增长 2.45G > 1.0G）<br>按 `launch_refusal_rule` 停手 | `confirmed_empty: true` |
| **arm4-s0/1/2** | 未提交 | — | **未执行** | — | — | 零作业、零写入 | — |
| **评测阶段** | 未提交 | — | **未执行** | — | — | 零作业、零写入 | — |

---

## 边界与科学诚实性声明

1. **Loss 不能代替能力验收**：4 个成功训练的 run 虽收敛至极低 training loss（0.019 ~ 0.00048），但训练 loss 仅为内部工程遥测，绝不构成世界模型时空理解、因果推理或动作保持的能力通过证据。评测集与 AWZ 基准完全未执行。
2. **final 分区零接触断言**：经盘上与代码核对，`artifacts/v9/s1/phase1/` 目录下零 final 分区产物，未生成亦未读取 final 分区。
3. **P36 孤儿 recovery 保持冻结**：未对其执行任何恢复或改动操作。
4. **失败原状保留**：`arm3-seed1` 的失败（rc=2）与 `arm3-seed2` 的启动被拒记录全量如实保留，不抹除、不覆盖。

---

## 交回统筹裁决建议

1. **建议裁定**：建议统筹者（一级）将 **ainerzero.V9.P40** 按 **未完成结案（incomplete closeout）** 验收/关闭。本审计为非作者 CPU 事实核验，不替代统筹者对 P40 的最终 accept/reject 裁定。
2. **后续需求**：方案 A 剩余运行（`arm3-seed2`、`arm4` 3 个种子及阶段评测）已无法复用过期 r13 实验窗口，必须由统筹者在宿主机环境（重启释放 swap、重型 GPU 闸门空闲）就绪后，以新实验标识（如 r14）发起新一轮预登记与批准。
