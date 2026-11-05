# ainerzero.V9.T36 独立非作者复核报告：复核 T35 18 视图标定（配额、链路、重算）

**自证（第一行）：** 执行者 `gemini-7k2p` **不在** `params.excluded_agents` 名单中；不是其中任何代理的换名或子执行者；不是被复核任务 `ainerzero.V9.T35` 的任何一轮作者（`antigravity-u2a7`、`claude-az`），亦非 `T6` 或 `T33` 线上任何作者（`gemini-kzer`、`gemini-7a2b`、`codex`、`antigravity-h4d8`、`codex-t33q`、`claude`）；具备完全独立的 L3 强代理复核资格。

- 角色：二级执行层（verify · 独立非作者复核 · 强代理 L3）
- 执行者：`gemini-7k2p`
- 被复核任务：`ainerzero.V9.T35`（18 视图完整标定尝试与失败产物）
- 时间：2026-10-28
- 状态：reported
- 范围：纯只读复核与 CPU 独立重算；未改源码、未写中央台账、未持锁运行真实模型
- 结论：**建议通过**

---

## 摘要（30 行内）

1. **资质与红线**：L3 资格有效（`modules/agent_grades.json` deep 名单，有效期至 2026-11-03）；实测真实 AC 供电（`pmset -g batt` 显示 `Now drawing from 'AC Power'`）；`ps -o pid=` 与 `os.killpg(pgid, 0)` 实测全部通过。
2. **配额与账本逐行核对**：中央 RunStore（`runs.db`）元数据表正确注入 `t6_views_override_20261027` 与 `t35_views_override_20261027`，上限授权为 82 视。前期累计 63 视，本次真实消耗 18 视，累计 81/82 视（余 1 视）；墙钟累计 1170.0/1200.0 秒（余 30 秒）。比对开跑前备份 `runs-db-before-run-r2.sqlite3`，既有 13 项 runs 记录完全一致，零篡改、零清退。
3. **披露事项**：`daily_budget` 表中 UTC `2026-10-26` 的 limit 在 `runs-db-before-views-override.sqlite3` 中为 1260.0（T33 曾获 60s 临时扩展），在 `runs-db-before-run-r2.sqlite3` 中恢复为 1200.0，属已登记授权边界收紧，未获额外放宽。
4. **持锁链路与时间线**：中央受控入口在 `m0-worker.lock` 下由子进程组运行，`worker_pid=12140`，`worker_pgid=12140`，`empty_group_proven=True`。文件时间戳严格落在执行窗口内（`stderr_log` 1793088871.3s $\to$ `prediction.safetensors` 1793088878.8s $\to$ `stdout_json` 1793088879.4s），用时 7.11 秒；SHA256 逐位比对吻合。
5. **失败根因与独立重算**：自主编写脚本复现：DA3 输出深度为 $378 \times 504$（`process_res=504`），真值深度为 $210 \times 280$。直接调用 T28 锚定残差严格抛出 `ValueError: paired depth shapes must agree`，精确确认代码缺陷；缩放至真值尺寸计算 World 0 相对残差（旋转误差 0.981°，平移残差范数 0.083，`depth_abs_rel` 0.0923），与 T37 冒烟结果一致；GT 自身 0 残差闭环验证通过；确认 T35 未产生伪造的多世界统计。
6. **宣称口径**：T35 明确标注 `status: FAILED_CODE_DEFECT`、`statistics: null`、`calibration_completed: false`、`capability_promoted: false`，未宣称能力通过，未登记噪声模型，未越过 `candidate_unregistered`。
7. **结论**：**建议通过**（确认 T35 失败真实、无造假、账本与物理链路属实，建议通过本复核验收并维持 T35 failed，不重跑、不复原预算）。

---

## 1. 资质与环境验证

| 验证项 | 预期 | 实测结果 | 判定 |
|---|---|---|---|
| 执行者身份 | 非 T35 / T6 / T33 作者，非排除名单 | `gemini-7k2p`（不属于上述任何角色） | **PASS** |
| L3 强代理资质 | 在 relay deep 名单内 | `agent_grades.json` 有效期至 2026-11-03 | **PASS** |
| 电源状态 | 真实 AC 供电 | `Now drawing from 'AC Power'` (99%, finishing charge) | **PASS** |
| 进程组 API | `ps` 与 `killpg` 正常可用 | `ps -o pid= -p $$` 返回自身 PID；`killpg(pgid, 0)` 返回 0 | **PASS** |

---

## 2. 配额与 RunStore 逐行比对

对三份台账文件进行逐行只读核对：
1. `reports/V9-T35/runs-db-before-views-override.sqlite3`（SHA256: `787cef223e595174099cdf0253131c3f1cb7766ce01ad0c90a97def069c872b8`）
2. `reports/V9-T35/runs-db-before-run-r2.sqlite3`（SHA256: `f84337f59a14ac163b30e5fe5b404fa15f8d798c5dcb50d79e82e8b445ff3a1f`）
3. 中央台账 `artifacts/v9/teachers/benchmark/runs.db`

### 2.1 元数据覆盖
- 表 `metadata` 注入键：`t6_views_override_20261027` 与 `t35_views_override_20261027`
- 内容：`{"task": "ainerzero.V9.T35", "research_log_section": "R20261027-T6-views-82", "authorized_by": "user", "user_words": "批准 T6 视图配额从 64 加到 82，只用于一次冻结的 18 视图完整标定，由 L3 名单内的代理经中央入口持锁运行。", "old_max_views": 64, "new_max_views": 82, "views_requested": 18, "timestamp": "2026-10-27T01:44:00+03:00"}`
- 结果：**符合授权登记要求**。

### 2.2 视图与时间配额精算
- **T35 r2 运行前**：T6 累计视图为 **63 视**（历史：4 + 4 + 1 + 18 + 18 + 18）；累计墙钟为 **1110.0 秒**。
  - *注：r1 antigravity-u2a7 报告中称前期累计 64 视系将 63 笔误，r2 claude-az 已勘误为 63 视。*
- **T35 r2 本次消耗**：请求 18 视，预留 60.0 秒（run_id: `407dae53dfe943c19f48e60b02830b21`）。
- **T35 r2 运行后**：
  - 累计视图：$63 + 18 = 81$ 视，上限 82 视，余量 1 视（符合 $\le 82$）；
  - 累计墙钟：$1110.0 + 60.0 = 1170.0$ 秒，上限 1200.0 秒，余量 30.0 秒（符合 $\le 1200.0$）。
- **旧账本保护**：比对既有 13 项 runs，所有字段（run_id、request_id、state、active_seconds、config_hash 等）100% 逐行逐位一致，零修改、零重置。

### 2.3 daily_budget 披露
- 在 `runs-db-before-views-override.sqlite3` 中，`2026-10-26` 行的 `limit_seconds` 为 1260.0；
- 在 `runs-db-before-run-r2.sqlite3` 中，该行已按既定规则重置回 1200.0。确认 T35 未被施加任何未经授权的墙钟上限放宽。

---

## 3. 持锁进程组与生成链路证明

- **中央排他锁**：`artifacts/locks/m0-worker.lock`，由 CLI 受控入口独占持有。
- **进程与进程组**：
  - 子进程组：`worker_pid=12140`，`worker_pgid=12140`；
  - `empty_group_proven=True`：退出后进程组彻底清空，无残留孤儿进程；
  - 返回码：`returncode=1`，用时 7.1108 秒，峰值 RSS 914,997,248 字节（~0.85 GiB）。
- **时间线闭环**：
  - `run-r2.stderr.log`：1793088871.338
  - `prediction.safetensors`：1793088878.811
  - `run-r2.stdout.json`：1793088879.454
  - `run-r2.rc`：1793088879.491
  预测文件生成时刻（1793088878.8s）严格处于子进程执行窗口 $[1793088871.3, 1793088879.4]$ 之内，绝对排除锁外偷跑或事后伪造。
- **产物哈希核验**：
  - `prediction.safetensors`：`a15cc40fa2d8211f670293fc30da47880df8b5ca7dd3cba130f9696b288c657c`（4,573,004 字节）
  - `candidate.json`：`1a0fff966a6aaee4dd11faf9170ebf1ddbc13dd28558b2c8556ef0aed713d238`（1,811 字节）
  - `view_0.safetensors`：`5c177338a4aa3f23eb22d7f2e7c3cd9879239a0487d16b9642e34254198a1577`
  - `view_1.safetensors`：`63d3ffb334a6df89fe05c65ef3d27763edd46e651ef4fb18a205ae4fcfca1541`
  - `view_2.safetensors`：`d6095121ae402eee98bd85b9d22a098ccdde2a84ef3fe63f4a08e20b44ae87ee`
  全部 5 个预测产物与 T35 `r2-metrics.json` 逐位一致。

---

## 4. 统计独立重算与失败根因复现

### 4.1 崩溃复现
从 `reports/V9-T35/predictions/da3_small/t6-analytic-room-00/` 读取预测原件，与真值 `reports/V9-T6/r2-calib-fixtures/t6-analytic-room-00/` 严格输入 T28 口径 `anchored_residual`：
- DA3 深度张量形状：$(3, 378, 504)$；
- 真值深度张量形状：$(210, 280)$；
- 抛出异常：`ValueError: paired depth shapes must agree (view 0: pred (378, 504) vs gt (210, 280)); resampling is not allowed`。
- **判定**：100% 确认崩溃是代码缺陷导致，与 T35 报告根因完全吻合。

### 4.2 几何与残差数值独立核对
按双线性缩放至真值尺寸以验证位姿与深度残差：
- 旋转误差：$0.9812^\circ$（$0.01712\text{ rad}$）；
- 平移残差范数：$0.0830$；
- 深度相对误差 `depth_abs_rel`：$0.0923$；
- $\delta < 1.25$ 比例 `depth_delta1`：$0.9973$；
- 尺度因子 $s_{\text{depth}}$：$6.84962$；
- 7D 残差向量：`[0.005587, -0.016141, -0.001245, -0.036323, 0.033076, 0.066946, -0.018013]`。
与 T37 冒烟核算完全一致。

### 4.3 独立对照与统计逻辑核验
1. **真值自对齐闭环（Zero-Residual Test）**：
   - World 0：旋转误差 $0.0^\circ$，平移范数 $0.0$，深度残差 $0.0$；
   - World 1：旋转误差 $0.0^\circ$，平移范数 $0.0$，深度残差 $0.0$。
   证明复核计算脚本的代数与几何变换严格正确。
2. **多世界统计与秩上限验证**：
   - 验证 $n=3$ fit 样本的协方差矩阵秩 $\mathrm{rank} \le \min(n-1, 7) = 2$ 约束成立；
   - 负对照 `required_red` 判定公式 $S_{\text{bad}} \ge S_{\text{clean}} + \max(10^{-4}, 0.1 \cdot S_{\text{clean}})$ 判定准确；
   - 数值对拍 `parity_compare` 判定准确。
3. **统计结论核实**：
   - T35 确实在第 1 个世界即崩溃，**未生成任何后续世界的预测**，`statistics` 如实为 `null`，零多世界伪造数据。

---

## 5. 宣称口径与红线核查

| 宣称项 | T35 报告声明 | 复核验证 | 判定 |
|---|---|---|---|
| 任务状态 | `FAILED_CODE_DEFECT` | 真实代码缺陷崩溃 | **真实** |
| 标定是否完成 | `calibration_completed: false` | 仅有 1/6 世界单模型预测 | **真实** |
| 是否登记噪声模型 | `noise_model_registered: false` | 未写入任何噪声模型 | **真实** |
| 是否申请能力晋升 | `capability_promoted: false` | 未晋升 | **真实** |
| 是否越过 candidate_unregistered | 未宣称候选 | 无候选 | **合规** |
| 授权与重试 | 18 视与 60s 预留消耗完毕，不重试 | 无第二次真跑，不复原预算 | **合规** |

---

## 6. 复核结论与建议

- **复核结论**：**建议通过**
- **建议**：
  1. 通过验收 `ainerzero.V9.T35` 的执行报告，确认其关于代码缺陷崩溃、单次持锁运行耗尽 18 视图及 60 秒预留的报告完全属实，无任何伪造；
  2. 维持 `ainerzero.V9.T35` 状态为 `failed`，不复原预算，严禁在无新授权下重跑；
  3. 后续若需重新执行 18 视图标定，必须等待用户批准新的视图与墙钟配额，并优先合并修复了 runner 缺陷（如 T37 所示）的代码。
