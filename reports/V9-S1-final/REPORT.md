# ainerzero.V9.P61 报告：S1 final 一次性评测（正式运行）与 final 分析增补

- **作者**：一级 `claude`。**需要非作者复核**：`ainerzero.V9.P62`（gemini）。
- **依据**：
  - RESEARCH_LOG `## R20261028-S1-phase1-final-eval`（用户 10-28「批准 final 评测」）；
  - 唯一有效批准行 `RESEARCH_LOG.md:854`，document SHA `ad21071ec11d3006b9d31e9ac3c0e9a48aa6a94c2efd80807549ca1681e9b60c`。
- **一次性**：只运行了这一次，没有重跑。READ_ONCE 标记已建立；在隔离副本上调用第二次，以 `final_already_read` 被拒。

## 1. 运行（≤10 行）

1. 一个 relay 作业：`job-65f09030a3c4428d9d4d8b4994e606bd`（`--max-attempts 1`，idempotency `s1-final-eval-once`）。
   - 时间：19:10:46–19:11:40，墙钟 54 s，登记预算 1800 s；返回码 0。
   - 环境：接电、开盖、在 `caffeinate -i -s` 下运行。
2. 台账 run：`a59075e2aa8f4d2abd71696cbedd7539`，实验 `s1-phase1-20261028-final`，经 `created → initializing → validating → completed` 到达 completed，reason 为 `s1_final_eval_completed`。
   - 生产台账里 final 实验下只有这一个 run（在台账隔离副本上查询，见 `ledger-final-run.json`）。
3. 十格（arm1 D 加九个继承格）全部 completed，没有出错的格。
   - 窗口数 550，对应 175 个探针批次，正好等于登记的 175。
4. **绑定**：九格的 run_id、来源实验、params SHA 与 final 节登记一致。params SHA 又与盘上 `runs/<id>/params.npz` 的实算 SHA 一致。每格的 `partition` 都是 `final`。
5. **评测对象**：few-shot `by_world` 的 200 个 episode_id 与封存 `export_meta.json` 列出的 200 个完全相同，与 development 的 episode_id 没有重叠。
6. **封存**：运行后 `verify_sealed_final` 结果为 passed，`already_read=true`。标记由 pid 71937、run `a59075e2…` 创建（副本见 `READ_ONCE.copy.json`）。
7. **生产台账**：运行前为 `7244149c…5f53`，运行后为 `9daeacd3…3426`。变化只来自上面这一个 run 的写入；运行前后均只做 shasum，查询都在隔离副本上做。

## 2. final 分析增补

方法与 P57 相同，脚本是 `analysis/analyze_final.py`，结果在 `analysis/tables-final.md` 和 `analysis-final.json`。

- 输入 SHA 先与 `SHA256SUMS.txt` 核对一致，再开始计算。
- 未登记统计检验或门槛，所以按三种子均值排序；「不重叠」只是描述性的，不构成显著性结论，也不晋升任何能力。

**结论：**

1. **NLL**（均值、中位数、末检查点）：final 上排序为 arm4 < arm3 < arm2，与 dev 相同。种子范围只有 arm4 与 arm2 之间不重叠。
   - dev 上 NLL 曲线面积三对都不重叠，final 上也是三对都不重叠。
2. **定位**（平移、中位数、yaw、曲线面积）：排序与 dev 相同，三臂相差在 0.01 m 以内，种子范围全部重叠，仍分不开。
3. **拓扑 F1** 九格都是 0.75，**few-shot** 在 k=0/1/2 处于随机水平、k=4 为 0、k=8 数据不足，与 dev 一致，属于结构性退化（P48 第二阶段待重定义）。
4. **M2 记忆干扰（worst retention delta）是唯一与 dev 排序不同的一行**：
   - final 上 arm2 三个种子为 0.259、0.108、0.015，arm3、arm4 接近 0，因此 arm4 与 arm2、arm3 与 arm2 的范围不重叠；
   - dev 上三臂都接近 0，分不开；
   - 只有三个种子，arm2 seed0 一格占了大部分差距；这里只如实记录，不据此下结论。
5. **arm1 D**：C0 诊断与 dev 逐项相等（它不读 S1 数据），仍标为不可比。
6. 11 行标量里有 10 行的排序与 dev 相同。

## 3. 需要说明的事项

- 每格详情里的 `dataset_digest` 字段是 train/dev 数据身份 `8234f2f3…`，指检查点训练所用的数据，不是本次评测的分区。被评分区由三处确定：每格的 `partition: final`、顶层的 `sealed_dataset_digest` `057ea6c2…`、上文第 5 点的 episode_id 集合核对。
- 台账 run 的 `active_seconds` 记为 600，这是入口预留的额度，按预留记账；实际用时约 50 s。
- 运行前把封存的 `packets/final.jsonl`、`truth/final.jsonl` 由 000 改为 0444，运行后保持 0444：复核要实算 SHA，需要读权限；而标记已经阻止再次读取。
- few-shot 曲线仍按族合并输出，与 P57 已披露的报告缺口相同。

## 4. 证据

- **运行**：`final-eval-stdout.json`（作业 stdout 的完整报告）、`final-eval-stderr.log`（为空）、`job/launch.json`、`job/state.json`、`run_final.py`、`driver.log`、`run_ledger.json`。
- **前后状态**：`pre_run_state.txt`、`production-ledger-after-run.txt`、`post_run_checks.json`、`READ_ONCE.copy.json`、`ledger-final-run.json`。
- **二次调用被拒**：`harness/second_call_refusal.py` → `second-call-refusal.json`（隔离副本；读取入口装有绊线；副本台账与生产台账都没有变化）。
- 上述文件的 SHA 列在 `SHA256SUMS.txt`；分析目录的 SHA 列在 `analysis/SHA256SUMS.txt`。
