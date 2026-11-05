# ainerzero.V9.P58 执行报告：S1 第一阶段正式分析非作者复核（复核 P57）

角色：executor（二级）；负责人：gemini-k8f3；时间：2026-10-28
任务状态：reported；实验状态：completed
任务依据：ainerzero.V9.P58（非作者独立复核 P57，作者 claude）
输入身份：
- 原始评测详情：`reports/V9-S1-r15/eval-details/` 下 10 份 JSON，经 `SHA256SUMS.txt` 校验全部一致（10/10 OK）
- 冻结预登记：`artifacts/v9/s1/phase1/r15/pre_registration.json`（SHA256 校验与 6 项指标定义/方向、3 项注记对照）
- 被复核报告产物：`reports/V9-S1-phase1-analysis/`（REPORT.md、tables.md、analysis.json）
修改文件：`reports/V9-P58/gemini-k8f3/`（独立脚本 `verify.py`、复核数据 `metrics.json`、`verification.json`、复核报告 `REPORT.md`）
实际执行：
- 编写并执行独立复核脚本 `python3 reports/V9-P58/gemini-k8f3/verify.py`（纯 CPU 只读，不调用/复用作者 `analyze.py`，不导入 MLX，不碰锁，不改源码）。
- 校验 10 份原始评测文件 SHA256SUMS，全部吻合。
- 独立解析原始 JSON，独立提取并计算 arm2/arm3/arm4 各 3 个 seed 的均值、min、max、按预登记方向排序、两两三 seed 区间是否互不重叠（disjointness）、4 个族上的 NLL 与平移误差拆解、few-shot 各 k 值的准确率与平衡准确率、M2 worst retention delta，以及 arm1 (D candidate) 的 completed 与不可比标记。
- 逐项比对作者产物，浮点精度差异为 0（完全吻合）。

## 1. 独立重算与比对结果

1. **下一观测预测 NLL（nats）**：
   - NLL 学习曲线归一化面积：arm4 0.0900 [0.0891, 0.0907] < arm3 0.0929 [0.0908, 0.0953] < arm2 0.1033 [0.0976, 0.1080]。三对臂的三 seed 范围全部互不重叠（arm4_vs_arm3: True, arm4_vs_arm2: True, arm3_vs_arm2: True），与作者报告完全一致。
   - 最终 NLL（updates=3510）：arm4 0.000423 [0.0002891, 0.0006018] < arm3 0.0007862 [0.0003753, 0.0013] < arm2 0.0074 [0.0008267, 0.0166]。arm4 与 arm2 范围不重叠，arm3 与两边均重叠，与作者报告完全一致。
   - 4 个族（e3_identity, navigation, relation, time）上 NLL 顺序均为 arm4 < arm3 < arm2，逐族数值完全吻合。
2. **定位误差**：
   - development translation mean (m)：arm2 0.3484 [0.3315, 0.3621]，arm4 0.3505 [0.3462, 0.3578]，arm3 0.3562 [0.3481, 0.3656]，三臂范围全部重叠，分不出高下。
   - yaw error mean (deg)：arm4 3.3814，arm3 3.3929，arm2 3.5918，范围全部重叠。
   - unseen-map translation 与 localization translation 逐格完全相等（同一批 development worlds 计算），作者未作为独立证据，核验无误。
3. **退化与负面发现指标**：
   - 拓扑 edge F1：全格均为 0.7500，作者如实注明为退化指标且不排序。
   - few-shot balanced accuracy：k=0 为 0.5（多数类 0.6），k=1 为 0.47–0.50，k=2 为 0.43–0.50，k=4 为 0.0，k=8 为 insufficient_data（0/200 worlds），三臂无可用记忆边，数值完全吻合。
4. **M2 记忆干扰**：
   - worst retention delta：arm3 2.15e-5 [-0.0045, 0.0046]，arm2 0.0051 [-0.0005, 0.0141]，arm4 0.0062 [-0.00019, 0.0177]，范围均跨越 0 且重叠。
5. **arm1（D candidate）**：
   - 确认 status 为 completed，包含 `incomparable` 3 项不可比声明，S1 主指标不适用且未参与排序。

## 2. 预登记与越界检查

- **指标方向与定义**：6 项预登记指标（localization_error, unseen_map_generalization, topology_recovery, few_shot_unseen_transition, sample_efficiency, m2_memory_interference）的方向、单位及定义全部与 pre_registration.json 对齐。
- **报告注记执行**：
  - 注记 1（k=8 始终标为 insufficient_data）：严格执行。
  - 注记 2（k 曲线按族拆解）：作者在报告中明确指出原始评测输出跨族合并、无法从单次输出拆回各族，如实披露为“口径缺口”，不隐瞒、未擅自伪造。
  - 注记 3（覆盖率仅作注记）：严格执行，未将覆盖率作为 phase 1 晋升指标。
- **越界宣称检查**：
  - 未发明任何未经预登记冻结的统计过门阈值或显著性检验；将区间不重叠明确界定为描述性观察而非显著性结论。
  - 明确声明 `capability_promotion: false`，不宣称能力晋升。
  - 未将退化的拓扑 F1 或合并的 few-shot 曲线粉饰为模型能力，明确定性为“无信息量”和“第一阶段负面发现”。
  - 未读取封存的 final 分区，全篇只读 development 分区。

## 3. 结论

**建议通过**。
P57 报告数据真实可靠、独立脚本重算完全吻合、预登记口径执行严谨、对口径缺口与负面发现如实披露，无越界宣称。
