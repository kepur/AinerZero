# ainerzero.V9.P20 非作者复核报告：P18 r2（修正预算数值、来源标签与冻结指标边界）

角色：复核者（tier 2，非作者）；ID：`workbuddy-c2n7`；日期：2026-10-22
被审任务：`ainerzero.V9.P18` r2（作者 `deepseek-v41f-p8k2`）
依据：`P18-r2-review-inputs.json`（38 个钉住文件 SHA，审前全部一致）；`reports/V9-P19/REPORT.md`（F1–F9）；`S1-R6-DECISION.md`
本卡只写 `reports/V9-P20/`；被审报告/脚本/冻结数据/冻结文档零改动（38 项钉住 SHA 复核一致）。
**状态说明：本棒因心跳超时（20.4 分钟无心跳）于 09:11 被接力台收回，任务已由 `workbuddy-q7t2` 重领。本报告为被收回一棒的完整复核成果，文件名加 `-c2n7-reclaimed` 以避免与当前持卡者交付物冲突；relay report 未提交（任务不在本人手上）。**

---

## 0. 结论摘要

**F1–F9 中 8 条闭合成立且经独立复算证实；F9 的"冻结后被改写"断言无历史 diff 证据、属过度断言（部分成立）。另发现 2 条缺陷（D1 中 / D2 轻）与 1 条证据链瑕疵（O1）。**

1. **可复现性（最强证据）**：r2 的 `independent_truth_check.json` 用作者原脚本在我目录复跑**字节级一致**（sha `b8f55a8b…afea`）；r2 的 `metrics.json` 用仅改输出目录的脚本副本复跑**字节级一致**（sha `ad32d483…b36a`，与一级钉住值相同）→ r2 交付物是其脚本从钉住输入原样产出，无生成后手改。
2. **独立复算（不复用作者代码路径）**：我用冻结 r5 **生产函数本体**（`metrics.split_support_query`、`data.load_truth_view`、`data.load_development_windows`，字节副本导入、MLX 未导入）独立重算：k 覆盖 200/200/150/50/0 世界、750/550/350/100/0 query；族统计（nav 50×7 步/300 迁移/300 相邻/0 原地；e3 50×5/200/0/200；time 50×4/150/0/150；relation 50×3/100/0/100）；550 窗口→35 批→**175 窗口 batch**；组件算式 **611/1492/800/3500**、帧 **1003/2103/792/1492**、混合数 1703/1503/1903 算术全部复现；预算 7 项（updates 3510、estimate 359.9312287726061、deadline 450、arm1 1.501679232227616、arm1_deadline 2、phase_wall 4099.605202459、headroom 10300.394797541）与冻结登记值 **delta 全 0**。
3. **F1（历史保留，符合答复 380 要求）**：r1 `metrics.json` 计算值本就是 611/1492/800/3500/1750（sha `71bc8c38…`，未改）；错误只在 r1 `REPORT.md` §10 选项B 第 3 条（612/1292）、§9 文案（600 次 probe_graph）与 r1 `metrics.json` 的 unmeasured 散文（"611 eval calls, 1292 forwards"、"600 calls"）。r2 把 612/1292/600 留作 `r1_registration_values_superseded` 审计块并给出差值（−1/+200），未抹历史、未谎称"r1 metrics 全错"。✓
4. **F9（唯一天然缺陷）**：两个 `generation_seconds`（data_identity 45.739918708 / timing.smoke 47.605202459）是当前字节事实，phase_wall 取保守 47.605、delta=0 不受影响——这部分对。但"**清单字段在预注册冻结后被改写**"是无历史 diff 的因果断言：现存四份 pre_registration.json（冻结 r5 快照、仓库 r5、r6、顶层）**都同时含两个值**；数据集清单只含 45.739918708（与 data_identity 一致）；仓库与协调快照中不存在只含单一值的更早副本。按审查要求应降级为"冻结文档内部不一致 + 改写假设无证据"。
5. **D1（中）单次 eval 墙钟三数被混为一谈**：`PREP_BUDGET["eval"]=300 s` 是名义 worker 预算；真正的子进程硬杀是 `supervision_seconds = budget + spec.TIMING["supervision_extra_seconds"] = 350 s`（commands.py:813）；账本预留 120 s（worker.py:440）。r2 称"300 s 是每次 eval 的硬墙钟/子进程硬超时"不准确，"9×300 是上界写法"也不成立（350 才是每次上界）。静态检查改用 9×350=3150：4099.605+3150=7249.605 ≤ 14400 仍通过，结论不变但标签须改。
6. **D2（轻）选项 B2 未绑定数据摘要**：611/1492/800/3500 是在**现有冻结 dev 集**（200 世界、750/550/350/100 query）上的实测；B1 的新长 episode 数据集（≥10 packet、每 family ≥9 transition）会改变 query 数与每世界 transition 数，其调用量在实测前未知。r2 选项 B 未写明这一定绑定（B1 成本写 unknown 是对的，但计数绑定缺失）。
7. **O1（证据链瑕疵，不影响 r2 数字）**：P19 `independent_checks.json` 的 `C_repaired_accounting_measured.per_k_calls` 疑似从 as-coded（B）块 stale 复制：修复树下 k=1 应不崩、k=2/k=4 应执行 2/4 条 transition，但该块显示 k=1 崩溃、k=2=150、k=4=150（as-coded 口径），与 C 自己的 per_run_total（611/1492）矛盾。r2 引用的是 per_run_total 与 component_split（自洽的载体），数字不受影响；r2 未指出这处瑕疵。

**总判：F1–F8 闭合成立（可提交一级）；F9 需按第 4 条改写表述；D1/D2 建议在 r3 或一级整合时修正。本卡不自我验收，不构成参数变更或运行授权。**

---

## 1. 实际执行的命令（全部只读冻结输入；唯一写入在 reports/V9-P20/）

```bash
# 0) 钉住输入 SHA 复核（38/38 一致）
python3 -  # sha256 逐项比对 P18-r2-review-inputs.json

# 1) 独立复算脚本（新建实现；字节副本导入冻结 s1 包；无 MLX）
cd /Users/mac/AinerWorkFlow/AinerZero
env -i PATH=/usr/bin:/bin:/usr/local/bin HOME=/tmp/p20home TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 \
    .venv/bin/python reports/V9-P20/analysis/p20_independent_check.py

# 2) r2 产物字节级可再生性（作者原脚本，输出改到我目录；scaffold diff 留档）
env -i … V9P18R2_OUT=reports/V9-P20 .venv/bin/python reports/V9-P18/r2/analysis/independent_truth_check.py
env -i … .venv/bin/python reports/V9-P20/analysis/build_r2_metrics_p20copy.py   # 仅 OUT 一行不同
```

- 隔离：`HOME`/`TMPDIR`/`PYTHONDONTWRITEBYTECODE` 指向私有临时环境；ISO 字节副本在 `reports/V9-P20/analysis/iso/`，8 个源文件 SHA 与冻结快照逐一比对一致。
- **未执行**：任何 `--mode train/eval/smoke/data`、MLX 前向/梯度/优化器、数据生成、final 分区读取、下载/安装、git commit/push、批准行写入。未原地复跑任何 P18/P19 脚本（作者脚本均改输出目录后运行）。未修改 `reports/V9-P18/**`、`reports/V9-P19/**`、冻结数据与冻结文档。

## 2. F1–F9 逐条核验

| # | 严重度 | r2 声明 | P20 核验 | 判定 |
|---|---|---|---|---|
| F1 | 严重 | 对外数字统一 611/1492/800/3500/175；612/1292/600 留作 superseded | r1 metrics 原值 611/1492/800/3500/1750 确认；错误位置（r1 报告 §10 B-3 的 612/1292、§9 的 600、r1 metrics unmeasured 散文的 1292/600）逐一定位确认；P19 实测值核对一致 | **闭合成立** |
| F2 | 严重 | 每块带 provenance，实测/非作者实测/算术/外推分开 | r2 metrics 四类标签齐全；as-coded 212/792/400/1500 与 P19 B 块、repaired 611/1492/800/3500 与 P19 C 块逐一相等；r1 外推仅存审计块 | **闭合成立** |
| F3 | 严重 | 4 h 已含 eval；删去伪问题；守卫只在 train 路径 | 源码三处证据核实（commands.py:737-757、worker.py:368-385 注释、worker.py:435-440 预留 120 s）；`mode_eval` 函数体内无 phase 守卫（脚本断言）；**但"300 s 硬墙钟"标签错误（见 D1）** | **基本成立，标签须修** |
| F4 | 严重 | 新数据成本未知；47.605 s 是旧计划清单抄录值 | smoke.py:103/110 确认抄 `manifest["generation_seconds"]`；清单 counts 确认 2000+200 世界、9500+950=10450 packet；9.111 s 明确标注"非成本估计下界" | **闭合成立** |
| F5 | 中 | 选项 A 不再自称零变更；冻结指标原值/n/缺测保留 | 预注册文档 metrics[3]=few_shot_unseen_transition、定义含 "accuracy and displacement error vs k" 确认；r2 `option_A.is_zero_change=false`、missing 记 insufficient_data、family/constant 标 diagnostic_only | **闭合成立** |
| F6 | 中 | 1703/1503/1903 标混合；只留 1003/2103/1492 | 三个混合数算术复现（950+700+53 / 750+700+53 / 1100+750+53）；自洽量与 P19 实测一致 | **闭合成立** |
| F7 | 中 | M2 11/42 取自 P19 实测组件拆分，非手写 | build_r2_metrics.py 从 `p19_checks[...].component_split.m2_interference` 读取确认；per-world 规则改为 k transitions（stop=k+1） | **闭合成立** |
| F8 | 轻 | probe_graph=800（200+600）；600 仅是 few-shot 半 | 算术复现 200+200+150+50=600 few-shot、总计 800 | **闭合成立** |
| F9 | 轻 | 同一 digest 两个 generation_seconds；"清单字段在冻结后被改写"；取保守 47.605 | 字节事实确认；**"被改写"无历史 diff 证据**：四份 prereg 皆含两值、清单只含 45.740、无更早单值副本 | **部分成立（表述过度）** |

## 3. 四个重点审查项的专项结论

1. **（r1 metrics 未错 vs build 脚本/metrics 文案 1292）**：两者都对且不矛盾——r1 `metrics.json` 的**计算值**没错（611/1492/800），错在 `build_metrics.py:197` 生成进 `metrics.json` 的 unmeasured **文案**（611 calls + 1292 forwards 同句）与报告正文。r2 的表述（"r1 metrics.json 早已存的是 611/1492/800；错只发生在 REPORT 正文与 unmeasured 文案"）与字节事实一致，**没有抹历史**。✓
2. **（generation_seconds 不能无历史 diff 断言"冻结后被改写"）**：确认无任何历史 diff 证据。正确表述："冻结文档内部不一致——同一 dataset digest 在 data_identity.generation_seconds=45.739918708（与数据集清单一致）与 timing.smoke.data_generation_seconds=47.605202459 两个值；按 smoke.py 的抄录语义，smoke 记录暗示清单曾读作 47.605，但哪个字段、何时被改无法从现存字节确定；phase_wall 取保守值 47.605，复算 delta=0.0 不受影响。" r2（沿 P19）断言"被改写"应降级为假设。✗→需改写
3. **（B1 新长 episode 调用量不可沿旧 611/1492）**：确认 611/1492/800/3500 与现有 dev 集（200 世界、1750 query、family 长度 7/5/4/3）绑定；新集（≥10 packet、≥9 transition/family）的 query 数与每世界 transition 数都会变，调用量实测前未知。r2 选项 B 的 B1/B2 未写明这一定绑定。✗→需补（D2）
4. **（单次 eval 300 标称/350 监督/账本不同，不能称 300 绝对硬墙；4 h 已含 eval 不扩大登记）**：源码确认三数并存（300 名义 / 350 监督超时 / 120 账本预留）；r2 把 300 称"硬墙钟/子进程硬超时"不准确（D1）；"4 h 已含 eval"结论本身正确且未扩大登记（`approval_line_written=false`）。✗→标签须修

## 4. 负面证据与未验证项（保留，不当通过）

1. k=1 崩溃、support 少写一条、`probe_graph` 真实后端 TypeError（S1-R6-DECISION 第 3 条引用核实）——三条阻断性证据 r2 均保留，未声称已修。
2. 修复态计数跑在计数替身上（P19 亦声明），不等于生产 MlxBackend 能跑完；MLX 单位耗时与新数据成本仍为"未知/未测"——r2 保留。
3. 账本跨 output-root 唯一性属 r6 未修缺陷——r2 明确不声称已解决。
4. **本卡未验证**：真实 MLX 数值路径（全程未导入 MLX）；`_evaluate_arm` 的 RunStore 绑定段/checkpoint 重载；`arms.py` 数值路径（D 候选 1 次 forward/32 C0 槽仅核源码分支 worker.py:1019-1026 与 r1 记账，未执行）；M2 选点稳健性；B1 新数据生成成本。
5. 本卡不自我验收；`completed` 与报告通过不代表能力通过。

## 5. 交回统筹（需一级决定）

1. 是否接受 F1–F8 闭合（附本卡独立复算与字节级可再生证据）。
2. F9 表述是否按 §3.2 改写为"内部不一致 + 改写假设无证据"，保留"已取保守值 47.605、delta=0"。
3. D1（300/350/120 三数标签）与 D2（B2 计数绑定数据摘要）是否在 r3 或一级整合层修正；静态检查按 9×350 重算仍通过（7249.605 ≤ 14400）。
4. P19 C 块 per_k_calls stale 瑕疵是否需 P19 侧更正或仅作记录。
5. 本卡结论仅供取舍：不改 k/世界/分区/训练步数/eval 额度，不写批准行，不构成运行授权。

## 6. 产物清单（均在 reports/V9-P20/）

- `REPORT-c2n7-reclaimed.md`：本报告。
- `analysis/p20_independent_check.py` / `analysis/p20_independent_check.json`：独立复算脚本与结果（生产函数路径）。
- `analysis/build_r2_metrics_p20copy.py` / `analysis/scaffold_diff_build_r2_metrics.txt`：r2 metrics 脚本副本（仅 OUT 一行不同）与 diff。
- `analysis/independent_truth_check.json`：作者真值脚本在我目录的复跑输出（与 r2 钉住值字节一致）。
- `metrics.json` / `analysis/input_identity.json`：上述复跑产生（与 r2 钉住值字节一致，仅作证据）。
- `logs/*.out|err`：全部运行日志（RC=0，stderr 空）。
- `iso/`：冻结 s1 包字节副本（8 源文件 SHA 与快照一致）。

**审后复核**：本棒工作结束后再次核对 38 项钉住输入 SHA，全部一致（38/38）；r1 14 项冻结输入未动。本棒对 `reports/V9-P18/**`、`reports/V9-P19/**`、冻结数据、冻结文档、仓库源码零写入。
