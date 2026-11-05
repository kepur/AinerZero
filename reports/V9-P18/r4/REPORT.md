# ainerzero.V9.P18 r4 执行报告

角色：executor（二级执行层）；负责人：`step5-9f2k`（Step-5-Preview；skills=text/code/math；无成绩、不编分）；时间：2026-10-22
任务状态：reported；实验状态：**未执行**（纯 CPU 材料修订；无 MLX 导入、无训练、无真实评测、无数据生成、未读 final、无下载/安装、无新预算）
任务依据：`coord/P18-R4-DECISION.md`、`coord/P22-EVIDENCE-ADDENDUM.md`、`reports/V9-P22/step5-9f2k/报告.md`（P22 非作者独审，D1–D7 缺陷）、r3 交付（已被 P22 打回，本卡不覆盖）
输入身份：见 `products/metrics.json → identity`（全部输入带 SHA256 与字节数）；冻结 r5 源码 7 项来自一级钉扎的快照 `s1-r5-input-snapshot`（`SOURCE_MANIFEST.json` 为依据）；live 工作树 s1 源码已有 5/7 漂移（r7 并行修改），**被审材料不绑定 live**；通用 `lifecycle.py`（`22ded55ce136…`）单独钉当前 SHA，未在 r5 快照内，身份缺口继续保留。
修改文件：仅写 `reports/V9-P18/r4/`。r1/r2/r3/P19/P20/P22、冻结快照、数据集、源码、prereg、真实账本**全部只读零修改**（r3 产物 SHA 复验：`551d9b954736…`/`0ba67a8e9d9a…` 未变）。

## 0. 摘要

1. **本卡是材料修订，不是新实验**：科学值、调用量、预算数字、k 覆盖、负面证据与 r3 完全一致（逐叶对比 r3/r4 `metrics.json`：664 叶中 45 叶不同，全部为溯源字段与 7 项缺陷更正，**零科学数字变化**）。
2. **D1（时间因果）已删净**：全文不再出现「两值在冻结前已共存」及任何以 created_unix/mtime 倒推写入时刻的判断；只保留「当前冻结文档同时含两个 `generation_seconds` 字段」这一事实，created_unix/mtime 列为可变字段内容，写入时刻与原因未知。
3. **D2（错误示意合计）已移除**：r3 的 B1 新 shape 合计 1,011/4,842/**5,653** 全部删除——**承认 5,653 是数字错误**（混用 transitions 与 frames 口径并折叠旧 digest 的 M2 常量 11/42/53）。保留的各分量纯代数（topology 200/1800、few-shot 800/3000、query 5,800、probe_graph 1,200、encode 11,600）逐项标注「假设口径、非实测、非预算、不迁移」；任何合计须按新 digest 重测。
4. **D3（元数据覆盖）已修**：两阶段各写 `coverage_run_meta.json` / `build_run_meta.json`，不再互相覆盖；r3 交付目录只剩 build 阶段元数据这一缺口如实记录，不伪造补写。
5. **D4–D7 一并闭合**：身份表带完整冻结快照路径与 SOURCE_MANIFEST 依据、分清 live r7 与被审 r5；旧卡号清零（后续独审为 **P23**，P20/P22 为已 accepted 历史证据）；350 s 明确为 worker 子进程超时配置（不含锁等待/清理/账本收尾）；字节复现口径改为「固定输入字节下、两个不同输出根、核心产物相同」，不再宣称无时间戳/无路径。
6. **复现**：三个输出根（`products` + `work/run_a` + `work/run_b`）两阶段各 RC=0、stderr 全 0；核心产物三方字节一致（`dev_coverage.json` `e8018818…`、`metrics.json` `ef53e69a…`）。守卫负测 5/5 按设计拒绝，前后 SHA 不变。

## 1. 实际执行的命令

```bash
cd /Users/mac/AinerWorkFlow/AinerZero
for d in products work/run_a work/run_b; do
  env -i PATH=/usr/bin:/bin HOME=<r4/work/home> TMPDIR=<r4/work/tmp> PYTHONDONTWRITEBYTECODE=1 \
      V9P18R4_OUT=reports/V9-P18/r4/$d \
      .venv/bin/python reports/V9-P18/r4/analysis/r4_dev_coverage.py      # stage 1
  env -i ... V9P18R4_OUT=reports/V9-P18/r4/$d V9P18R4_COVERAGE=reports/V9-P18/r4/$d/dev_coverage.json \
      .venv/bin/python reports/V9-P18/r4/analysis/r4_build_metrics.py     # stage 2
done
# 守卫负向测试 5 项（拒绝后 SHA 不变）：见 logs/guard_*.err
```

日志：`reports/V9-P18/r4/logs/`（6 个 .out + 6 个 .err + guard_*）。隔离：私有 HOME/TMPDIR、`PYTHONDONTWRITEBYTECODE=1`、显式输出根、无 `/tmp` 默认、不复用 r1/r2/r3 路径。本轮**没有**运行任何 train/eval/smoke/data 模式、MLX 前向、final 读取、数据生成、下载/安装、git 写、批准行。

## 2. 身份与源漂移（D4）

- 冻结 r5 源码 7 项（evaluation `92d8de4a6551`、runtime `a99346522f29`、metrics `e1c36b657794`、worker `4174187473cd`、commands `48b3fb48cf4b`、spec `beedc9482b8d`、prereg `d441b84e1c52`）：路径为 `/Users/mac/AinerWorkFlow/AinerRelay/reports/coordination/codex-20261022-cycle/s1-r5-input-snapshot/src/ainerzero/v9/experiments/s1/`，与该目录 `SOURCE_MANIFEST.json` 一致；该快照还含 prereg、P9/P16 报告与其余 s1 源文件（r3「快照只含 experiments/s1/** 与 cli.py」的括注不准，已弃用）。
- **live 工作树 ≠ 被审旧 r5**：live `src/ainerzero/v9/experiments/s1/` 已有 5/7 文件与冻结版不同（r7 并行修改中）；本卡全部结论只绑定冻结快照，不依赖漂移现场源。live r7 的改动不等于被审旧材料漂移。
- 通用 `src/ainerzero/runtime/lifecycle.py`（`22ded55ce136…`，与 r3 记录一致）不在 r5 快照内：`wall_seconds=max(0.0, instant − created_at)`（:392）与 `reserved_active_seconds=row["active_seconds"]`（:391）按当前工作树钉住；若 r5 冻结时点不同需一级再核——**此身份缺口继续保留，本卡不用它改变任何数字**。

## 3. 写路径、双阶段元数据与字节复现口径（D3/D7）

| 阶段 | 写入 | 规则 |
| --- | --- | --- |
| stage 1 `r4_dev_coverage.py` | `$OUT/dev_coverage.json`、`$OUT/coverage_run_meta.json` | `$OUT` 必须显式（`--out` 或 `V9P18R4_OUT`）；目录非空即拒绝 |
| stage 2 `r4_build_metrics.py` | `$OUT/metrics.json`、`$OUT/build_run_meta.json` | 允许上一阶段两个文件；`metrics.json` 已存在即拒绝；含其它文件即拒绝；**不写、不覆盖 `coverage_run_meta.json`** |

- 双阶段元数据分立已验证：`products/coverage_run_meta.json`（stage 1 argv/起止）与 `products/build_run_meta.json`（stage 2，含 coverage_input）同时存在且内容不同。
- r3 缺口如实记录：r3 交付目录的 `run_meta.json` 实为 stage 2 所写（stage 1 元数据被覆盖丢失），本卡**不补写**旧 coverage 时间。
- 字节复现口径（D7）：**固定输入字节与元数据下，两个不同输出根的核心产物（`dev_coverage.json`、`metrics.json`）相同**；`metrics.json` 含输入文件 mtime 与绝对快照路径，**不宣称**跨机器/输入变动后仍同字节；两阶段元数据不参与核心产物字节一致比较。
- 守卫负测 5/5（`logs/guard_*.err`）：拒绝非空目录 / 已有 metrics.json / 外来文件 / 无输出根；每次拒绝后 `products/` 四个文件 SHA 不变。

## 4. D1–D5 逐条（相对 r3 的变更；实质经 P22 独立复现，未改）

- **D1**：对外数字与旧值三处出处（r1 REPORT.md:243/:275、metrics.json:447/:449、build_metrics.py:97/197/199）不变；P22 已独立核实行号。
- **D2（本卡修订）**：删除任何时间因果表述。保留事实：当前 `dataset_manifest.json → generation_seconds = 45.739918708000005`（等于 prereg `data_identity`）；prereg `timing.smoke.data_generation_seconds = 47.605202458999884`；冻结文档对同一 digest 内部不一致；`phase_wall` 取较大值（保守），复算 delta=0.0。created_unix/mtime 仅作可变字段内容照录。**P19 F9 与 r2 的「冻结后被改写」断言维持撤回**（无 diff、无 git 历史、`artifacts/` 被 `.gitignore:15` 忽略）。
- **D3**：调用量绑 digest `8234f2f3…83ad26` 不变（611/1492/800/3500/175、as-coded 212/792/400/1500、M2 11/42、frames 1003/2103、hybrid 1703/1503/1903 的混合性质）；B1 新 shape 示意见 §5（本卡修订）。
- **D4**：300 标称 / 350 监督超时 / 120 账本预留三层与 `wall_seconds=now−created`（非 120）不变；9×120 只是静态预留；4h 含 eval；P17 now 缺陷属 P15 r7，不声称已修。**350 的范围表述修订见 §6（D6）**。
- **D5**：M2 11/42 按 JSON 指针从 P19 封存件读取不变；P19 `per_k_calls` 子块自相矛盾（as-coded 语义）的发现与「repaired 列只用 `per_run_total`/`component_split`」的处置不变（P22 已独立确认）。

## 5. B1 新 shape 示意（D2： totals 已移除）

假设：200 世界 × 9 transition、family 不变（4×50）、`query_limit=8`。**纯代数分量**（逐项标注假设、非实测、非预算、不迁移）：topology 200 调用 / 1,800 transition（按本卡口径 frames=transitions+1/世界，对应 2,000 帧）；few-shot 800 调用 / 3,000 transition /  repaired stop 帧 3,800（假设 stop=k+1）；query 5,800；probe_graph 1,200；encode 11,600；窗口 batch 未知。

**不给出合计**：r3 的合计 1,011/4,842/5,653 折叠了旧 digest 实测 M2 常量（11/42/53），新 9-transition episode 集可能改变 M2 成本；其中 5,653 还混用口径，**是数字错误**。新 digest 的任何合计与成本必须重新测量；本卡不把「改对加法」当作完成新数据成本测量。旧 digest `8234f2f3…` 的 611/1492/800/3500/175/2103 等实测/算式保持原值与来源。

## 6. 350 s 的范围（D6）

350 s = `commands.py:200`（`budget + spec.TIMING["supervision_extra_seconds"]`=50）经 `commands.py:227` `subprocess.run(timeout=…)` 作用于 **worker 子进程的超时配置**。它**不自动包含**锁等待、进程清理与账本收尾，未知清理耗时在其外；不得把该配置值说成整个调用的绝对硬墙。300 标称 / 120 active 预留 / 真实墙钟未知 / 4h 含 eval 均维持。

## 7. 保留的负面证据与未验证项（不当通过）

1. **r3 数字错误的承认**：B1 新 shape 的 stop_frames 合计 5,653 为数字错（口径混用 + 旧常量），本卡移除而非原地改对；r3 其余数字经 P22 独立复现无误。
2. k=1 崩溃（`evaluation.py:331`，`stop=support[-1]+1` → frames=1<2 → BackendError）、support 少写一条、`probe_graph` 真实后端 TypeError（r6 裁决第 3 条，未复现）、修复态计数来自 P19 计数替身、P19 per-k 子块矛盾、账本 card-local——全部保留。
3. 未验证：任何真实 MLX 数值路径；batch-1 forward/encode/probe_graph 的 MLX 单位耗时（评测墙钟未知）；`_evaluate_arm` 的 RunStore 绑定/检查点重载/参数 SHA；arms.py 数值路径；M2 选点稳健性；新数据生成成本；`lifecycle.py` 快照缺口；P17 now 缺陷修复状态（P15 r7，另一棒）。
4. 选项 A/B 仅为可审阅材料：**不构成运行批准或科学选项批准**；k=8 永远 insufficient_data，不能记 0 或满分；`eval_batches=48` 不能作为评测调用量批准依据。
5. 本卡不自我验收；P22 已 accepted 为历史负面证据，不重新 ready。

## 8. 交回统筹

1. 一级封源 `reports/V9-P18/r4/REPORT.md` 与 `SHA256SUMS.txt` 后，发布 **P23 非作者独审**（P20/P22 为历史卡，不重新 ready）。
2. 是否接受本轮 7 项缺陷闭合方式（尤其 D2 移除合计而非原地改数）。
3. 选项 A/B 取舍、k=1 修复 + 重冻结 + 非作者复核开卡、`query_limit=8` 登记、held-out 语义修订——维持 r3 提交的问题清单，本卡不扩大范围、不写批准行。

## 9. 产物清单（全部在 `reports/V9-P18/r4/`）

| 文件 | 说明 |
| --- | --- |
| `REPORT.md` | 本报告 |
| `products/metrics.json` | r4 结构化结果（身份/D1–D5/F1–F9/预算/帧/48批/A/B/负面/未测/r4_corrections/determinism_scope） |
| `products/dev_coverage.json` | 覆盖/形状/support-query 范围（三输出根字节一致） |
| `products/coverage_run_meta.json`、`products/build_run_meta.json` | 两阶段审计元数据（不参与字节一致声明） |
| `analysis/r4_dev_coverage.py`、`analysis/r4_build_metrics.py` | 两阶段脚本 |
| `logs/` | 全部运行日志（含 5 项守卫负测） |
| `work/run_a/`、`work/run_b/` | 两个独立新目录复现 |
| `SHA256SUMS.txt` | 本目录全部产物 SHA256 |
