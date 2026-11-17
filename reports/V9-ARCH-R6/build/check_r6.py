#!/usr/bin/env python3
"""r6 候选稿的作者侧自查（纯 CPU，只读）。

用法（仓库根目录）：
    python3 reports/V9-ARCH-R6/build/check_r6.py

做两件事，结果写到 reports/V9-ARCH-R6/evidence/：
1. unchanged-sections.txt：声明「没有改」的章节，是否与 r5 逐字相同。
2. citations.txt：候选稿引用的每个数字，在出处报告里逐字找到的行（文件:行号:原文）。
任何一项找不到就以非零码退出。这是作者自查，不能代替非作者复核。
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "reports" / "V9-ARCH-R6"
R5 = (ROOT / "ARCHITECTURE_V9.md").read_text(encoding="utf-8")
R6 = (PKG / "ARCHITECTURE_V9.r6-candidate.md").read_text(encoding="utf-8")
EVID = PKG / "evidence"
EVID.mkdir(exist_ok=True)
failures: list[str] = []


def section(text: str, heading: str, level: int) -> str:
    """取一个标题到下一个同级或更高级标题之间的正文。"""
    start = text.index("\n" + heading)
    pat = re.compile(r"\n#{1,%d} " % level)
    m = pat.search(text, start + 1)
    return text[start : m.start() if m else len(text)]


# ------------------------------------------------------------ 1. 未改章节
lines = [
    f"r5  sha256 {hashlib.sha256(R5.encode()).hexdigest()}",
    f"r6  sha256 {hashlib.sha256(R6.encode()).hexdigest()}",
    "",
]
WHOLE = [
    ("### 1.1 三系统与三平面（r5，F1）", 3),
    ("## 3. P0 接口", 2),
    ("### 7.1 运行模式", 3),
    ("### 7.2 教师 = 带噪声的传感器", 3),
    ("### 7.3 教师清单", 3),
    ("### 7.4 数据与监督", 3),
    ("### 7.5 成本验收", 3),
    ("### 8.1 模块对应", 3),
    ("### 8.2 接口对应", 3),
    ("### 8.4 成本模型", 3),
    ("### 8.5 不做事项", 3),
    ("### 8.6 学习侧的信息边界（r5，F2）", 3),
    ("## 9. r4 关闭表", 2),
    ("## 10. v10 吸收与改正", 2),
]
for heading, level in WHOLE:
    same = section(R5, heading, level) == section(R6, heading, level)
    lines.append(f"{'相同' if same else '不同'}  {heading}")
    if not same:
        failures.append(f"章节不同：{heading}")

# §11 在 r5 里是最后一节；r6 在它后面追加了 §12–§14
s11_r5 = R5[R5.index("\n## 11. r5 关闭表") :].rstrip("\n")
s11_r6 = section(R6, "## 11. r5 关闭表", 2).rstrip("\n")
lines.append(f"{'相同' if s11_r5 == s11_r6 else '不同'}  ## 11. r5 关闭表")
if s11_r5 != s11_r6:
    failures.append("章节不同：§11")

# §4 的约定段与式 1–13：r6 只在式 13 后面追加
m4_r5 = section(R5, "## 4. 数学定义", 2).rstrip("\n")
m4_r6 = section(R6, "## 4. 数学定义", 2)
ok = m4_r6.startswith(m4_r5 + "\n14. 规划代价（r6）")
lines.append(f"{'相同' if ok else '不同'}  ## 4. 约定段与式 1–13（r6 只在其后追加式 14–17）")
if not ok:
    failures.append("§4 式 1–13 被改动")

# §5 的预登记规则、原表、S1 共同口径、常设对照的原有三条
s5_r5 = section(R5, "## 5. 研究顺序与门槛", 2).rstrip("\n")
s5_r6 = section(R6, "## 5. 研究顺序与门槛", 2)
ok = s5_r6.startswith(s5_r5 + "\n- **r6 记录的执行缺口**")
lines.append(f"{'相同' if ok else '不同'}  ## 5. r5 原文（r6 只在其后追加执行缺口与 §5.1–§5.3）")
if not ok:
    failures.append("§5 原文被改动")

# §6 原有各行
s6_r5 = section(R5, "## 6. 验收维度", 2).rstrip("\n")
s6_r6 = section(R6, "## 6. 验收维度", 2)
ok = s6_r6.startswith(s6_r5 + "\n| 学习组件的净收益（r6）")
lines.append(f"{'相同' if ok else '不同'}  ## 6. r5 原有各行（r6 只追加两行）")
if not ok:
    failures.append("§6 原有行被改动")

# §1 表：r5 每一行的两格原样保留（教师合一只加了括注）
t5 = [l for l in section(R5, "## 1. 设计决定", 2).split("\n") if l.startswith("| **")]
t6 = [l for l in section(R6, "## 1. 设计决定", 2).split("\n") if l.startswith("| **")]
kept = 0
for row in t5:
    probe = row.replace("| **教师合一**：", "| **教师合一**（r6：从默认选择降为待证候选）：", 1)
    if any(x.startswith(probe + " ") for x in t6):
        kept += 1
lines.append(f"§1 表：r5 的 {len(t5)} 行里有 {kept} 行的前两格原样保留；r6 共 {len(t6)} 行")
if kept != len(t5) or len(t6) != len(t5) + 6:
    failures.append("§1 表行数或原文不符")

(EVID / "unchanged-sections.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------ 2. 引文
AWZ = ROOT.parent / "AnimeWorldZero"
CITES: list[tuple[str, Path, list[str]]] = [
    ("S1 一期", ROOT / "reports/V9-S1-final/REPORT.md", [
        "final 上排序为 arm4 < arm3 < arm2", "三臂相差在 0.01 m 以内", "九格都是 0.75", "未登记统计检验或门槛"]),
    ("S1 拓扑诊断", ROOT / "RESEARCH_LOG.md", [
        "「模型不形成边」的读法不成立"]),
    ("E1", ROOT / "reports/V9-E1-CONCLUSION/CONCLUSION.md", [
        "③ 比它差 25.9%", "③ 比它差 1.3%", "e_10 比基线低约 25%", "P 族 F1 比 ② 低 0.038",
        "封存 final 从未读过", "dev 已被三轮设计决定用过", "F1 在所有臂中最好", "一步 MSE 与 10 步指标错配"]),
    ("S2", ROOT / "reports/V9-S2-CLOSE/REPORT.md", [
        "成功率都是 0", "dev 与 final 都没有运行", "| A | 0/20 | 2.785 | 0.286 |",
        "| B | 0/20 | 0.036 | −0.087 |", "| C | 1/20 | 0.299 | 0.127 |",
        "它每一步都从零 GRU 状态起步", "两者都没有检验「训练后的隐空间能否充当代价」"]),
    ("S2 修数据诊断与协议", ROOT / "RESEARCH_LOG.md", [
        "长目标 0/50 → 0/50", "原因是原协议连 oracle 都无法到达长目标", "完美假臂按 r2.6 协议闭环成功 12/12"]),
    ("S3 一阶段", ROOT / "reports/V9-S3-PHASE1/DEV1-REPORT.md", [
        "+0.777（0.733, 0.818），通过", "−0.052（−0.088, −0.016），**未通过**",
        "A1 0.109、A2 0.765、A3 0.697，**未通过**", "有读出头类别偏置"]),
    ("S3 二阶段", ROOT / "reports/V9-S3-PHASE2/FINAL-REPORT.md", [
        "+0.760（+0.730, +0.790）", "+0.011（−0.012, +0.034）", "+0.045（+0.029, +0.061）",
        "+0.027（+0.015, +0.039）", "+0.005（−0.001, +0.012）", "下降 0.074（上界 0.095）",
        "这几乎由结构决定", "情景库每回合清空"]),
    ("S3 二阶段设计（M2 对照）", ROOT / "reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md", [
        "S3 每回合清空，没有这条路径，**不报**"]),
    ("S3 三阶段设计 r0（M2 对照）", ROOT / "reports/V9-S3-PHASE3-DESIGN/DESIGN-r0.md", [
        "M2 零状态对照不适用：没有学习模型，**不可比，阻断相应的能力结论**"]),
    ("S3 三阶段", ROOT / "reports/V9-S3-PHASE3/FINAL-REPORT.md", [
        "不检验科学假设", "+0.548（+0.515, +0.581）", "+0.001（−0.014, +0.017）",
        "+0.178（+0.166, +0.191）", "| G − MODE | −0.001（−0.014, +0.011） |",
        "| G − G-NR | +0.339（+0.314, +0.363） |", "−0.137（−0.150, −0.123）",
        "平移误差到 5 格时，稳定格上的收益只剩 0.039，回滚的收益只剩 0.032",
        "但「最近一次」比 G 高 0.132", "参数化的 SLOW 本阶段没有测"]),
    ("S4 一期", ROOT / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", [
        "六个门全部通过", "D = 0.873", "0.071 倍", "D = 0.867", "高 0.123",
        "L-int 的准确率是 0.768，E-B 是 0.781", "L-int 0.569",
        "有模拟器监督、二维、等质量弹性圆盘、结构化检测、智能体位姿为真值",
        "| 全量数据 | +0.013 | +0.023 [+0.010, +0.036] |", "| 1/8 数据 | +0.030 | −0.006 [−0.022, +0.010] |"]),
    ("S4 二期", ROOT / "reports/V9-S4-PHASE2/FINAL-REPORT.md", [
        "8 个门过 7 个", "全部事件 0.835，E-P 0.836", "低 0.072", "| GD | 动力学 D | 0.868 |",
        "覆盖率 0.745，门槛 0.75", "区间含 0", "单体运动（墙、柱）用的是手写规则 E-B",
        "输 E-B 0.056", "随机开门几乎没有收益"]),
    ("S5", ROOT / "reports/V9-S5-FINAL/RESULTS/REPORT.md", [
        "**+0.0088**", "**+0.0081**", "**通过**（A\\* 更好）", "1502 / 1888 = **0.80**",
        "墙钟降 **11.0%**", "保留率 0.727", "都跌到 0.014–0.042", "| A0 无教师 | 0.024 | 0.073 | 0.418 |",
        "| A2 V-JEPA | 0.030 | 0.162 | 0.420 |", "L=64 为 +0.0004（95% [−0.002, 0.003]），L=512 为 −0.011（[−0.020, −0.002]）",
        "A1 在 L=512、L=2048 是三者中最差的", "超出用户批准的 25 h 约 0.3 h", "撞上单格上限而失败",
        "A4 在 L=512 的最终 AP（0.067）也没有超过 A0（0.073）"]),
    ("S6 一期", ROOT / "reports/V9-S6-FINAL/RESULTS.md", [
        "| GS 自选胜随机 |", "**+0.095**", "**+0.099**", "**+0.093**",
        "| GK-F 自由运动代价 | 自由误差 E/Z ≤ 1.10，上界 ≤ 1.20 | 1.068 | [0.917, **1.243**] | **不过** |",
        "碰撞 0.671，擦边 0.933，墙柱 0.887，自由 **1.211**，全部盘步 0.954",
        "D(E)−D(G) = **−0.052**", "共 12000 个标签", "s_rep 为 0.062"]),
    ("S6 二期摸底", ROOT / "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", [
        "| N+（日志O+） | 0.3607203758982099 | 0.03155555555555555 |",
        "| U+ | 0.33055769492953957 | 0.3244444444444445 |",
        "| Q+ | 0.28820706843566796 | 0.4673333333333334 |",
        "| R+ | -0.057719284051699425 |", "不能称门已通过"]),
    ("V10-E2a", AWZ / "reports/V-V9-B9/报告.md", [
        "**50.94%**", "作者报 54.69%", "432/432 tick", "回退率 93.75%、比全量慢 43.8%",
        "建议限范围验收 `awz.V9.B9`"]),
    ("r5 出版副本", ROOT / "docs/architecture/baseline.v1.json", [
        "0f54a96ace5b9c6fad2f3a16f3e6417a2f521fe131a13400263a0f5d9920f2a4"]),
    ("训练暂停解除", ROOT / "CLAUDE.md", [
        "2026-10-15 的训练暂停（R20261015-pause）已解除"]),
]
out: list[str] = []
for label, path, needles in CITES:
    out.append(f"== {label}：{path.relative_to(ROOT.parent)}")
    src = path.read_text(encoding="utf-8").split("\n")
    for needle in needles:
        hits = [(i + 1, l) for i, l in enumerate(src) if needle in l]
        if not hits:
            failures.append(f"找不到引文：{label}：{needle}")
            out.append(f"  未找到  {needle}")
            continue
        i, l = hits[0]
        out.append(f"  {i}: {l.strip()[:300]}")
    out.append("")
(EVID / "citations.txt").write_text("\n".join(out), encoding="utf-8")

print("\n".join(lines))
print(f"引文 {sum(len(n) for _, _, n in CITES)} 条，失败 {len(failures)} 条")
for f in failures:
    print("失败：", f)
sys.exit(1 if failures else 0)
