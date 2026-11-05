# 任务 relay.P2.A20 / ainerzero.V9.P62 复核报告

**任务 ID**：`ainerzero.V9.P62`  
**被复核任务**：`ainerzero.V9.P61`（S1 final 运行与 final 分析）  
**被复核者**：`claude`（一级统筹）  
**复核执行者**：`gemini-b4e7`（二级执行）  
**结论**：**建议通过**  
**生产账本 SHA256**：`9daeacd35064d7f699b4e50f778219192d133da32493886395bea11102833426`（核验前后严格一致，零写入）

---

## 1. 复核概述与核心结论

本次复核针对 P61 阶段在 S1 密封最终数据集（Sealed Final Dataset）上执行的单次终评（final-eval）及其实验分析报告进行全量非作者独立复核。

所有复核严格遵循只读原则：
1. **零触碰密封最终数据**：未调用 `open_sealed_final_once`，未直接读取 `packets/final.jsonl` 或 `truth/final.jsonl` 内容。
2. **零篡改生产账本**：中央账本 `control.sqlite3` 仅执行 SHA256 计算，所有数据库查询均在本地独立副本上以 `mode=ro` 模式运行，生产账本哈希在复核全程未发生任何变动。
3. **独立重算与对照**：未导入作者的分析脚本 `analyze_final.py`，而是自主编写独立的重算代码直接解析原始评测日志 `final-eval-stdout.json`，在容差 `< 1e-12` 下全量复现全部 11 项标量指标、4 个族群的 NLL 与位移误差、以及 Few-shot 泛化曲线。
4. **两项反事实对抗控制**：验证了复核审计对数据变动与参数变动的高度敏感性。

**最终审核结论**：P61 的执行完全符合单次读取密封闸门规范、预登记继承协议及预算守卫约束，数据一致性与分析结论完备无误，**建议通过**。

---

## 2. 逐项核验结果清单

### 2.1 校验和核验（Item 1）
- **评测目录校验**：`reports/V9-S1-final/SHA256SUMS.txt` 涵盖的 15 个文件全部通过校验（`OK`）。
- **分析目录校验**：`reports/V9-S1-final/analysis/SHA256SUMS.txt` 涵盖的 3 个文件全部通过校验（`OK`）。
- **核验日志**：详见 `logs/01_sha256sums_final.txt` 与 `logs/01_sha256sums_analysis.txt`。

### 2.2 单作业审计与执行耗时（Item 2）
- **作业状态**：检查 `reports/V9-S1-final/job/state.json` 与 `run_ledger.json`，确认仅有单作业 `job-65f09030a3c4428d9d4d8b4994e606bd`，`max_attempts=1`，`status="completed"`，`returncode=0`。
- **执行耗时**：开始时间 19:10:46，结束时间 19:11:40，总用时 54.0 秒，严格处于 1800 秒（30分钟）硬性预算上限内（占比仅 3.0%）。
- **核验日志**：详见 `logs/02_job_and_ledger.txt`。

### 2.3 评测 stdout 10 单元格审计与参数哈希匹配（Item 3）
- **单元格完成度**：`final-eval-stdout.json` 包含全部 10 个单元格（arm1 baseline + arm2 3-seed + arm3 3-seed + arm4 3-seed），`error_cells` 为空列表。
- **分区验证**：全部 9 个可训练单元格显式标注 `partition="final"`。
- **参数哈希与预登记一致性**：提取全部 9 个单元格在 stdout 中的 `run_binding.inherited.params_sha256`，与 `artifacts/v9/s1/phase1/final/pre_registration.json` 中预登记的 `inheritance.cells` 完全匹配；同时核对磁盘上各 run 的 `params.npz` 实际 SHA256，全部 100% 逐位匹配。
- **核验日志**：详见 `logs/03_final_eval_stdout_and_params.txt`。

### 2.4 评测对象与 Episode 零重叠核验（Item 4）
- **密封评测集规模**：从评测结果 `few_shot_unseen_transition.curve["0"].by_world` 中提取出评测的 200 个 Episode UUID，与密封数据集 `export_meta.json` 记录的 200 个 Episode 100% 吻合。
- **开发集零重叠**：对比开发集（`8234f2f3...`）的 200 个 Episode，二者交集数量严格为 0（零数据泄漏）。
- **核验日志**：详见 `logs/04_eval_objects_episodes.txt`。

### 2.5 密封完整性与单次读取标记（Item 5）
- **密封状态**：调用 `data.verify_sealed_final` 返回 `status="passed"`，`already_read=True`。
- **单次读取标记文件**：`057ea6c20f7ec9cadad2e774b21f4b561407cc324114ae8c0e17fc57f82ef887.READ_ONCE.json` 存在且仅此一份，内容包含：
  - `reader.document_sha256`: `ad21071e65c58bb03b9fb7ae48f06516315ef749e75ae0d0577b2195f00e9ec1`
  - `reader.run_id`: `a59075e2aa8f4d2abd71696cbedd7539`
  - 与 `reports/V9-S1-final/READ_ONCE.copy.json` 严格一致。
- **核验日志**：详见 `logs/05_seal_and_marker.txt`。

### 2.6 SQLite 账本只读查询（Item 6）
- **隔离查询**：复制中央账本至 `harness/control.sqlite3`，以 `file:...mode=ro` 模式查询。
- **查询结果**：
  ```sql
  SELECT run_id, experiment_id, state, reason FROM runs WHERE experiment_id = 's1-phase1-20261028-final';
  ```
  查询结果严格为 1 条记录：
  - `run_id`: `a59075e2aa8f4d2abd71696cbedd7539`
  - `state`: `completed`
  - `reason`: `s1_final_eval_completed`
- **账本哈希不变性**：查询前后 `artifacts/v9/s1/phase1/control.sqlite3` 哈希均为 `9daeacd35064d7f699b4e50f778219192d133da32493886395bea11102833426`。
- **核验日志**：详见 `logs/06_control_sqlite_query.txt`。

### 2.7 二次调用拒绝防护验证（Item 7）
- **隔离测试**：通过独立脚本 `harness/second_call_refusal.py` 在沙箱副本中重新发起 final-eval 请求，`open_sealed_final_once` 挂载 tripwire。
- **测试结果**：
  - `status`: `"refused"`
  - `refused_stage`: `"final_already_read"`
  - `copy_ledger_unchanged`: `True`
  - `production_unchanged`: `True`
- **核验日志**：详见 `logs/07_second_call_refusal.json`。

### 2.8 独立全量指标重算与对照（Item 8）
- **独立脚本实现**：编写独立重算脚本 `harness/recompute_final_analysis.py`，不依赖 `analyze_final.py`。
- **11 项标量指标**：逐项重算各臂 3-seed 均值、极值、排名及区间不相交性，所有数值与 `analysis-final.json` 的误差均 `< 1e-12`。
- **4 大族群细分指标**：`e3_identity`、`navigation`、`relation`、`time` 的预测 NLL 与位移误差均值完全吻合。
- **Few-shot 泛化曲线**：k=0, 1, 2, 4 准确率与平衡准确率全量复现；k=8 正确识别为数据不足（`insufficient_data`）。
- **与开发集排名稳定性对比**：
  - 11 项标量指标中有 10 项排名顺序与开发集**完全一致**。
  - 仅有第 10 项标量 `worst_retention_delta`（M2 记忆干扰）发生倒序（开发集为 arm3 > arm2 > arm4；final 为 arm4 > arm3 > arm2）。这是因为 arm3 与 arm4 的干扰量均极低（~1e-5 级别），在不同 episode 采样下存在微小扰动，而 arm2 的干扰量显著高于前两者（~0.127），arm2 垫底的根本结论未变。
- **Arm1 C0 基线指标**：四项指标（`observation_loss_t0/t1`, `symbol_nll_t0/t1`）与开发集 100% 完全相同。
- **核验日志**：详见 `logs/08_independent_recomputation.txt`。

### 2.9 对抗负控制实验（Item 9）
- **对抗控制 1（浮点突变）**：人为修改 `final-eval-stdout.json` 临时副本中 arm2-seed0 的平移误差（+0.05），独立重算断言立刻捕获均值不匹配异常（0.365994 != 0.349328）。
- **对抗控制 2（参数哈希突变）**：人为篡改预登记副本中 arm2-seed0 的参数 SHA256，审计逻辑立刻触发哈希不匹配断言。
- **核验日志**：详见 `logs/09_adversarial_controls.txt`。

---

## 3. 产出物清单与校验

| 路径 | 说明 |
|---|---|
| `reports/V9-P62/gemini-b4e7/REPORT.md` | 本复核报告主文件 |
| `reports/V9-P62/gemini-b4e7/metrics.json` | 结构化复核元数据 |
| `reports/V9-P62/gemini-b4e7/SHA256SUMS.txt` | 目录文件完整性校验和 |
| `reports/V9-P62/gemini-b4e7/harness/` | 独立复核脚本与测试工具 |
| `reports/V9-P62/gemini-b4e7/logs/` | 9 项验证步骤生成的完整原始日志 |

---

## 4. 总结与建议

任务 `ainerzero.V9.P61` 在 S1 final 运行与分析中，严格遵守了各项工程、资源与科学规约，数据完备，论证严密，结果真实可靠。

**综合复核意见**：**建议通过**。
