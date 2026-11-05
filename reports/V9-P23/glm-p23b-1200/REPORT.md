# ainerzero.V9.P23 独立复核报告（ reviewer glm-p23b-1200，非任何 P18 历史作者/同会话）

角色：tier-2 reviewer；对象：报告 ainerzero.V9.P18 r4（作者 step5-9f2k）；时间：2026-10-22。
性质：**只读材料复核**（CPU/stdlib；无 MLX、无训练/eval/data/final、无下载/安装/预算/批准行；未验证任务非本人任何身份所做）。
仅写 `reports/V9-P23/glm-p23b-1200/`；被审目录 `reports/V9-P18/r4/` 全程零写入（34 个文件运行前后 SHA 逐一相同）。

## 结论

**材料可受理，无封源阻断缺陷。** P22 的 D1–D7 七项在本轮 r4 材料全部闭合，且我对每项都做了独立复验（含两新输出根字节复现、5 项守卫负例、真实拆守卫承重对照）。发现 2 项不阻断级报告瑕疵（F-A/F-B），由一级裁量，无需重跑：科学值、调用量、预算、k 覆盖、负面证据与 r3 完全一致为真，5,653 数字错误已按裁决移除而非原地改数。

## 逐项验证（证据见 metrics.json 与 output/step1_verification.json）

- **V1 输入身份**：一级钉扎的 67 项 review 输入（含 r4 全部 33 件交付物）SHA256/字节数 100% 匹配；`SHA256SUMS.txt` 33/33 全对，目录除去清单本身共 34 个文件全覆盖、无多余文件。
- **V2 D1 时间因果**：r3 原有因果句（"manifest was created before the pre-registration was frozen, and both values already coexist"）在 r4 metrics/json 指针级对比中确已删除；r4 仅余"冻结文档同含两 generation_seconds 字段 + phase_wall 取大值"事实，created_unix/mtime 照录可变字段；全文残留命中均为"已撤回声明"的引用/否定语境（claims_that_are_NOT_made、r4_corrections.D1）。未发现任何残余时间因果断言。
- **V3 D2 示意合计**：r4 产物中 1,011/4,842/5,653（及 5853）不含任何数值型 leaf，仅在 `totals_omitted_on_purpose` / `r3_error_acknowledged` 引用字符串中出现；new_data_illustration 各分量 topolog 200/1800/2000帧、few-shot 800/3000/3800、query 5,800、probe 1,200、encode 11,600 与假设 200×9、4×50、query_limit=8 的纯代数一致，逐项标注 status=illustration_arithmetic_only、measured=False、非成本非预算；无合计；migration_rule 与"新 digest 必须重测"齐全；旧 M2 11/42/53 未入选新示意。
- **V4 D3 双阶段元数据**：三个根（products、run_a、run_b + 我的 out1/out2）均同时存在 `coverage_run_meta.json`（stage1 argv/起止）与 `build_run_meta.json`（stage2 + coverage_input），内容不同互不覆盖；stage2 对 `coverage_run_meta` 不写不碰（代码与复现一致）。r3 缺口如实记录：r3/products 确只有 build 阶段 run_meta.json（内容指向 build_r3_metrics.py），未伪造补写。
- **V5 守卫负例（我的 5 项独立复跑）**：stage1 非空目录 / stage2 已有 metrics.json / stage2 外来文件 / stage1 无输出根 / stage2 无 coverage 输入，5/5 按设计拒绝（各自明确报文），拒绝后 out1 四文件 SHA 不变。
- **V6 真实拆守卫承重对照（仅隔离副本）**：stage1 去守卫副本 → 向我自建的含标记产物目录运行，标记 `dev_coverage.json` 被静默覆写为真产物（c9c4a046…→e8018818…，标记销毁）；stage2 需同时移除显式 metrics 存在分支与外来文件分支（metrics.json 也按外来文件被拒，双保险）才会覆写（233dfde0…→ef53e69a…）。证明：不做普通拒绝≠拆守卫；本守卫确为承重。

## 逐项验证（续）

- **V7 字节复现（D7 条件）**：以两份字节同源独立副本（copyA/copyB，`parents[4]` 保持原深度）在两个新输出根 `out1`/`out2` 全隔离复现两管线：RC=0、stderr=0；`dev_coverage.json`=`e8018818dacf70b8…`、`metrics.json`=`ef53e69af5d4c2b4…`，与作者 products 三方字节一致；stage 元数据各根不同、正确排除在一致性声明外；`dev_coverage.json` 本体无时间戳/绝对路径（0 命中），`metrics.json` 如声明含输入 mtime 与绝对快照路径——口径与 P18-R4-DECISION 第 7 条一致。
- **V8 D6 350s**：冻结快照逐行核实：`commands.py:42 PREP_BUDGET['eval']=300.0`；`commands.py:200 supervision=budget+spec.TIMING['supervision_extra_seconds']`（spec.py:77=50 → 350）；`commands.py:227 subprocess.run(timeout=…)` 仅作用于 worker 子进程；锁等待在其外（先 `worker_lock` 后 run）、账本收尾在其后；`worker.py:440 reserve=min(120, max(10, 0.5*300))=120`。r4 表述（"worker 子进程超时配置，不含锁等待/清理/账本收尾"）与源码一致。
- **V9 D4 身份表**：identity 带完整绝对快照路径 + 字节 + SHA；`SOURCE_MANIFEST.json` 实际覆盖 14 个 s1 源文件且 7 钉扎项 SHA 逐个匹配；快照确包含 prereg JSON、P9/P16 报告等（r3 不准括注已在 r4 弃用）；通用 `lifecycle.py` 不在快照的身份缺口如实保留（单独钉 22ded55ce136…，未改任何数字）；被审材料全部绑定冻结快照，未以 live r8/r7 替代。
- **V10 零科学变化**：r3→r4 `metrics.json` 以数组原子叶口径 = **664 叶中 45 叶不同**（与作者口径一致且可复现：628 公共叶中 9 处溯源/措辞字符串修订 + 36 处新增，0 删除）；数值型 leaf 就地零变化；`/k_coverage`、`/shape`、全部 budget 块逐块相等；`dev_coverage.json` 仅 schema/revision/executor/revision_basis 7 叶变化。科学值"与 r3 完全一致"成立。
- **V11 旧卡号与范围**：独审指向 **P23**，P20/P22 为已 accepted 历史证据（REPORT.md:5/15/80、metrics r4_corrections.D5）；P19 per-k 子块矛盾（NEG5）与 lifecycle 缺口、k=1 崩溃/少写一条/probe_graph TypeError/计数替身/账本 card-local 等负面证据全部保留；A/B 材料未写批准行，k=8 insufficient_data 维持。

## 缺陷（不阻断，一级裁量）

1. **F-A（中，报告证据声称略大于归档）**：REPORT §3 称"守卫负测 5/5（logs/guard_*.err）"，但 `logs/guard_coverage.err`/`guard_metrics.err` 各只归档 **1** 条拒绝（非空目录、已有 metrics.json），外来文件/无输出根两类无对应归档日志。守卫行为本身经我 5 项独立复跑证实为真，产品 SHA 前后一致也有钉扎背书；仅"5/5 均归档于 guard_*.err"这一点与实际归档不符。建议一级在验收注记，无需重跑。
2. **F-B（轻，live 观察已过时）**：REPORT 称 live s1 已"5/7 文件与冻结版不同"；本次复核实测 6/7（evaluation/runtime/commands/spec/prereg/worker 漂移，metrics.py 仍同快照）。材料本身不绑定 live（正确），该数字只是时点观察过期，不构成材料缺陷。
3. **观察（极轻）**：stage2 拒绝文案残留 "produced by r3_dev_coverage.py" 字样（应为 r4），纯文案。

## 未验证项 / 边界

- 未验证任何真实 MLX 数值路径、评测完成性、A/B 选项取舍、k=1 修复效果、新数据成本——本报告只判材料；A/B 科学与运行仍未批准。
- 作者负例的"每次拒绝后 SHA 不变"按钉扎交付态背书，非逐次日志背书（见 F-A）。
- 我的复现使用 AinerZero `.venv/bin/python`（3.12.2；作者同版本，见其 run_meta）；两脚本纯 stdlib、不 import ainerzero/MLX。

## 交付物

- 报告：`reports/V9-P23/glm-p23b-1200/REPORT.md`（本文件）
- 结构化数据：`reports/V9-P23/glm-p23b-1200/metrics.json`
- 逐项证据：`reports/V9-P23/glm-p23b-1200/output/step1_verification.json`（67 输入匹配、33 manifest 匹配、基线 SHA、叶级 diff 全文）
- 复现目录：`out1`/`out2`（新独立输出根，含两套四件）；负例日志 `neg1..neg5.*`；拆守卫对照 `analysis/guardoff_*.py` + `guardoff_prepop1/2`；一致性脚本 `analysis/verify_inputs_diff.py`、`analysis/copy{A,B}_{dev_coverage,build_metrics}.py`
- 心跳/交接：全部同步单次执行；未留任何后台心跳。
