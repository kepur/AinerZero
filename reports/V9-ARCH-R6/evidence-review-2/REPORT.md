# 架构 r6 候选稿 v2 证据核对报告（A26 独立复核）

数字与出处一致。59 条 claim 全部经验证器跑通，错误 0 条，候选稿 v2 的限定语与原报告一致，未见数字不符或比出处强。

- 复核者：`antigravity-z7k4`（二级执行 agent，非作者会话，非 A24 执行者）
- 审计对象：`reports/V9-ARCH-R6/ARCHITECTURE_V9.r6-candidate.md`
- 候选稿 sha256：`567de2349cc2918c79528425e474bd90c48462715bd96e28906a87fbe4fe7746`
- 现行基线 r5 sha256：`0f54a96ace5b9c6fad2f3a16f3e6417a2f521fe131a13400263a0f5d9920f2a4`
- 验证器：`reports/V9-ARCH-R6/tools/validate_review.py`（退出码 0，原始日志见 `validate.log`）

---

## 1. 逐句核对结果（claims.json 汇总）

本次复核共建立 59 条 claim，覆盖候选稿 r6 相对现行 r5 新增的 153 个带小数、百分号或分数的数字（claim 覆盖 151 个，2 个 V-JEPA 版本号 `2.1` 规范列入 `not_evidence`）。

- **verdict 为「一致」**：59 条
- **verdict 为「候选稿比出处强」**：0 条
- **verdict 为「数字不符」**：0 条
- **非一致条目列表**：无（全部条目均与出处一致）。

在候选稿 v2 中，作者补回了 13 处在 v1 中曾遗漏的限定语（包括所属事件子集、指标具体名称、dev 分区归属、单种子诊断性质以及只报告项状态）。在本次 59 条逐句核对中，候选稿中的所有表述均未超出原始出处报告的范围。

---

## 2. 否定说法核对

候选稿中出现的「未检验」「没有做」「没有跑」等否定陈述，每条在原报告和执行日志中均有明确出处，逐项核对如下：

### 2.1 §1 第三列中的「未检验」与限定
1. **网格编码只作诊断探针**（候选稿 L62）：
   - 候选稿：「未检验。没有新证据」
   - 出处：r5 原文保留项，自 r5 定版后无新的网格编码训练或实验。
2. **SE(2) 等变优先靠解析规范化获得**（候选稿 L63）：
   - 候选稿：「S4 用的是真值位姿，『估计位姿规范化』这条正式口径还没有检验」
   - 出处：`reports/V9-S4-PHASE1/final/FINAL-REPORT.md` 第 19 行（限定是有模拟器监督、真值位姿）。
3. **视觉前端先过换域门**（候选稿 L73）：
   - 候选稿：「换域训练或增强 未检验」
   - 出处：`reports/V9-S5-FINAL/RESULTS/REPORT.md` 第 48 行（换域 SHIFT_ALL 只报告了所有臂性能崩溃，未检验增强或换域微调）。
4. **自驱信号分两种情形**（候选稿 L74）：
   - 候选稿：「第二种 未检验：只有单次重复的摸底，S6 二期设计在送审」
   - 出处：`reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md` 第 27 行（单次摸底点值无重复层置信区间，不能称门已通过）。
5. **多时间尺度按 H-JEPA**（候选稿 L59）：
   - 候选稿：「未检验。S2 在 dev 之前被训练后门叫停，dev 和 final 都没有跑，对『分层是否更利于长程规划』没有结论」
   - 出处：`reports/V9-S2-CLOSE/REPORT.md` 第 8 行。
6. **规划代价与预测空间分开**（候选稿 L69）：
   - 候选稿：「四个候选本身 未检验」
   - 出处：`reports/V9-S2-CLOSE/REPORT.md` 第 53 行（两者都没有检验「训练后的隐空间能否充当代价」）。
7. **学习项只在门开时接管，训练目标对准评测步长**（候选稿 L70）：
   - 候选稿：「滚动训练本身 未检验」
   - 出处：`reports/V9-E1-CONCLUSION/CONCLUSION.md` 第 79 行（残差的训练目标要对准多步预测，S1/E1 均只按单步训练）。
8. **事件驱动的稀疏更新**（候选稿 L66）：
   - 候选稿：「学习侧（E2b）未检验」
   - 出处：`AnimeWorldZero/reports/V-V9-B9/报告.md` 第 19 行（只验收 E2a 世界侧参考实现，学习侧未做）。

### 2.2 §5.1 状态列中的否定说法
1. **V0**：`参考实现限范围验收，没有接入运行时`（出处：`AnimeWorldZero/reports/V-V9-B9/报告.md` 第 19 行结论第 9 条）。
2. **S1 一期**：`final 已读，没有晋升`（出处：`reports/V9-S1-final/REPORT.md` 第 28 行，未登记检验，不构成显著性结论，不晋升任何能力）。
3. **S1 二期（E1）**：`11-06 收口，final 没有读`（出处：`reports/V9-E1-CONCLUSION/CONCLUSION.md` 第 5 行，主门在 dev 没过，封存 final 从未读过；`RESEARCH_LOG.md` 条目 `R20261106-E1-closed`）。
4. **S2**：`11-09 收口为阴性，dev、final 没有跑`（出处：`reports/V9-S2-CLOSE/REPORT.md` 第 8 行，dev 与 final 都没有运行，final 分区从未生成；`RESEARCH_LOG.md` 条目 `R20261109-S2-closed`）。
5. **S3**：`三阶段之后转入 S4；学习组件与参数化 SLOW 没有做`（出处：`reports/V9-S3-PHASE3/FINAL-REPORT.md` 第 12 行与第 170 行，读出是符号的，没有学习组件；参数化 SLOW 本阶段没有测）。
6. **T**：`DA3 标定线（T6）的现状本稿没有核对`（出处：候选稿 §13.4 本稿没有核对的内容第 1 条）。
7. **S6 二期**：`二期等一级验收，没有实现，没有运行`（出处：`reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md` 第 27 行，设计 r1 送审，未实现未运行）。

### 2.3 §7.6 和 §8.3 的「r6 现状」中的否定说法
1. **多教师合一**（§7.6）：`S5 里没有胜过较好的单教师。`（出处：`reports/V9-S5-FINAL/RESULTS/REPORT.md` 第 47 行）。
2. **稀疏更新**（§7.6）：`世界侧的参考实现在 5% 稀疏率下达到了目标，学习侧没有做。`（出处：`AnimeWorldZero/reports/V-V9-B9/报告.md` 第 19 行）。
3. **Muon、多步滚动训练**（§7.6）：`没有登记的对照。`（出处：S1 预登记 AdamW 单步，E1 仅单步训练）。
4. **E1**（§8.3）：`已收口，主门在 dev 上没有过，封存的 final 没有读。`（出处：`reports/V9-E1-CONCLUSION/CONCLUSION.md` 第 5 行）。
5. **E2a/E2b**（§8.3）：`参考实现限范围验收；E2b 没有做。`（出处：`AnimeWorldZero/reports/V-V9-B9/报告.md` 第 19 行）。
6. **E3**（§8.3）：`回放部分本稿没有核对。`（出处：候选稿 §13.4）。
7. **E4**（§8.3）：`没有按 §8.4 算过完整成本。`（出处：`reports/V9-S5-FINAL/RESULTS/REPORT.md`）。
8. **E5、E6**（§8.3）：`没有做。S5 的换域是合成的外观替换，不是真实视频。`（出处：`reports/V9-S5-FINAL/RESULTS/REPORT.md` 第 48 行）。

---

## 3. 「没有改」章节核对与重跑生成检验

复核者编写了独立检验脚本 `verify_unchanged_and_rebuild.py`（不导入作者任何脚本），执行比对与重跑：

1. **未改章节逐字比对**：
   - `### 1.1 三系统与三平面`：相同
   - `## 3. P0 接口`：相同
   - `### 7.1 运行模式`：相同
   - `### 7.2 教师 = 带噪声的传感器`：相同
   - `### 7.3 教师清单`：相同
   - `### 7.4 数据与监督`：相同
   - `### 7.5 成本验收`：相同
   - `### 8.1 模块对应`：相同
   - `### 8.2 接口对应`：相同
   - `### 8.4 成本模型`：相同
   - `### 8.5 不做事项`：相同
   - `### 8.6 学习侧的信息边界`：相同
   - `## 9. r4 关闭表`：相同
   - `## 10. v10 吸收与改正`：相同
   - `## 11. r5 关闭表`：相同
   - `## 4. 数学定义`（式 1–13 与前言约定）：相同
   - `## 5. 研究顺序与门槛`（原表与共同口径）：相同
   比对结果表明：候选稿 §13.1 声明没有改的章节与现行 r5 逐字完全相同。

2. **隔离副本重跑构建脚本**：
   在临时隔离目录中运行 `reports/V9-ARCH-R6/build/build_r6.py`，产物 sha256 如下：
   - 重新生成产物 sha256：`567de2349cc2918c79528425e474bd90c48462715bd96e28906a87fbe4fe7746`
   - 与提交里的候选稿 sha256 逐字节完全一致。
   原始执行日志见 `verify_unchanged_and_rebuild.log`。

---

## 4. 常设 M2 对照的执行缺口核对

候选稿 §5 指出：“S3 第三阶段的设计 r0 写了不适用，定稿 r2 没有保留；S4、S5、S6 的设计稿既没有报，也没有写不可比”。

经通读五份定稿设计与对应的 final 报告，核对结论如下：
1. **S3 第三阶段**（`reports/V9-S3-PHASE3-DESIGN/DESIGN-r2.md`）：
   - 初稿 `DESIGN-r0.md` 第 163 行明确记录：“M2 零状态对照不适用：没有学习模型，不可比，阻断相应的能力结论（架构 §5 常设对照的规则）”。
   - 定稿 `DESIGN-r2.md` 转向纯机制与契约验证（符号读出，不训练），删去了这一段文字，定稿中未保留 M2 对照声明。
2. **S4 阶段**（`reports/V9-S4-DESIGN/DESIGN-r3.md`、`reports/V9-S4-P2-DESIGN/DESIGN-r1.md` 及对应 final 报告）：
   - 仅设计了无交互模型负对照 L-ind、门控对照 L-int-g、乱猜方向对照 L-sc-g，通篇未设置常设 M2 记忆干扰对照，未报告 M2 诊断，亦未声明不可比。
3. **S5 阶段**（`reports/V9-S5-DESIGN/DESIGN-r1.md` 及对应 final 报告）：
   - 设置了无教师 A0、打乱教师 C-sh、全量微调对照，未设置常设 M2 对照，未报告亦未声明不可比。
4. **S6 阶段**（`reports/V9-S6-DESIGN/DESIGN-r3.md` 及对应 final 报告）：
   - 设置了随机采样 R、epinet P、代用规则 Z、手写几何规则 G 对照，未设置常设 M2 对照，未报告亦未声明不可比。

**结论**：完全确认候选稿 §5 的判断属实，自 S4 起各阶段确实存在常设 M2 对照未执行且未声明不可比的缺口。

---

## 5. §5.1 状态列与外部文献核对

### 5.1 Relay 与 RESEARCH_LOG 状态核对
通过 Relay 命令行及 `RESEARCH_LOG.md` 实际查询：
- `ainerzero.V9.G1`：Relay 状态为 `accepted`，工程完成。
- `ainerzero.V9.G3`：Relay 状态为 `accepted`，工程完成。
- `ainerzero.V9.B2`：Relay 状态为 `accepted`，工程完成。
- `awz.V9.B9`（V10-E2a）：Relay 状态为 `accepted`，参考实现限范围验收。
- `awz.V9.B11`（V10-E0）：Relay 状态为 `accepted`，小样已交付。

各阶段收口日期核对：
- S1 二期（E1）：2026-11-06 收口（`RESEARCH_LOG.md` 条目 `R20261106-E1-closed`）
- S2：2026-11-09 收口（`RESEARCH_LOG.md` 条目 `R20261109-S2-closed`）
- S4：2026-11-11 收口（`RESEARCH_LOG.md` 条目 `R20261111-S4-closed`）
- S5：2026-11-13 收口（`RESEARCH_LOG.md` 条目 `R20261113-S5-closed`）
- S6 一期：2026-11-16 收口（`RESEARCH_LOG.md` 条目 `R20261116-S6-closed`）
候选稿 §5.1 所列各阶段状态与收口日期全部属实。

### 5.2 式 14 外部文献核对
候选稿式 14 引用的三篇外部文献：
1. `2304.01203`：Optimal Goal-Reaching Reinforcement Learning via Quasimetric Learning
2. `2402.15567`：Foundation Policies with Hilbert Representations
3. `2406.17098`：Learning Temporal Distances: Contrastive Successor Features Can Provide a Metric Structure for Decision-Making
核对情况：依据仓库已核对的 `reports/V9-ARCH-R6/evidence/external-citations.txt` 元数据记录，三篇文献的编号、标题与作者完全一致。因运行环境无外部网络连接权限，本次复核未发起外部网络访问。

---

## 6. 产物与校验清单

本次复核交付物均位于 `reports/V9-ARCH-R6/evidence-review-2/` 目录下：
- `claims.json`：59 条事实核对与 2 条非证据声明
- `validate.log`：验证器运行日志，退出码 0，错误 0 条
- `REPORT.md`：本报告文件
- `verify_unchanged_and_rebuild.py`：未改章节逐字比对与构建隔离重跑脚本
- `verify_unchanged_and_rebuild.log`：独立比对与重跑执行日志
- `SHA256SUMS.txt`：本目录下各交付文件的 sha256 校验和清单
