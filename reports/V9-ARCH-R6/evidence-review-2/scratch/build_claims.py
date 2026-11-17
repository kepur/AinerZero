#!/usr/bin/env python3
"""
非作者生成 claims.json 的脚本（antigravity-z7k4，A26）。
只读文件，不运行任何模型，不改候选稿。
逐字从文件中读取证据 text，不手写。
"""
from __future__ import annotations
import difflib
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CAND_PATH = ROOT / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
R5_PATH = ROOT / "ARCHITECTURE_V9.md"
OUT_DIR = ROOT / "reports" / "V9-ARCH-R6" / "evidence-review-2"
OUT_PATH = OUT_DIR / "claims.json"

CANDIDATE_SHA256 = "567de2349cc2918c79528425e474bd90c48462715bd96e28906a87fbe4fe7746"


def get_line(path_rel: str, n: int) -> str:
    """从文件第 n 行（1-based）读出去掉首尾空格的全文。"""
    # path_rel 可以是 AinerZero/xxx 或 AnimeWorldZero/xxx
    if path_rel.startswith("AinerZero/"):
        p = ROOT / path_rel[len("AinerZero/"):]
    elif path_rel.startswith("AnimeWorldZero/"):
        p = ROOT.parent / "AnimeWorldZero" / path_rel[len("AnimeWorldZero/"):]
    else:
        p = ROOT / path_rel
    lines = p.read_text(encoding="utf-8").split("\n")
    return lines[n - 1].strip()


def ev(file_rel: str, line: int) -> dict:
    """生成一条证据 dict。"""
    return {
        "file": file_rel,
        "line": line,
        "text": get_line(file_rel, line),
    }


def src(file_rel: str, line: int) -> dict:
    return ev(file_rel, line)


def find_line_in_cand(substr: str, cand_lines: list[str]) -> int:
    """找候选稿里包含 substr 的行号（1-based），找不到返回 -1。"""
    for i, line in enumerate(cand_lines, 1):
        if substr in line:
            return i
    return -1


def main():
    cand = CAND_PATH.read_text(encoding="utf-8")
    cand_lines = cand.split("\n")
    r5_text = R5_PATH.read_text(encoding="utf-8")

    # 验证 sha256
    sha = hashlib.sha256(cand.encode("utf-8")).hexdigest()
    assert sha == CANDIDATE_SHA256, f"候选稿 sha256 不符: {sha}"

    # ---- 证据文件路径常量 ----
    S1F = "reports/V9-S1-final/REPORT.md"
    E1 = "reports/V9-E1-CONCLUSION/CONCLUSION.md"
    S2 = "reports/V9-S2-CLOSE/REPORT.md"
    RLOG = "RESEARCH_LOG.md"
    S3P1 = "reports/V9-S3-PHASE1/DEV1-REPORT.md"
    S3P2F = "reports/V9-S3-PHASE2/FINAL-REPORT.md"
    S3P3D_R0 = "reports/V9-S3-PHASE3-DESIGN/DESIGN-r0.md"
    S3P3F = "reports/V9-S3-PHASE3/FINAL-REPORT.md"
    S4P1F = "reports/V9-S4-PHASE1/final/FINAL-REPORT.md"
    S4P2F = "reports/V9-S4-PHASE2/FINAL-REPORT.md"
    S5F = "reports/V9-S5-FINAL/RESULTS/REPORT.md"
    S6F = "reports/V9-S6-FINAL/RESULTS.md"
    S6P2D = "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md"
    B9 = "AnimeWorldZero/reports/V-V9-B9/报告.md"

    # ---- claims 列表 ----
    claims = []

    # 1. S1 一期
    claims.append({
        "id": "s1-nll-arm-order",
        "candidate_quote": "预测 NLL 是 arm4 ＜ arm3 ＜ arm2；定位三臂相差在 0.01 m 以内；拓扑 F1 九格都是 0.75",
        "source": src(S1F, 32),
        "answers": {
            "subset": {"value": "final 分区", "evidence": ev(S1F, 32)},
            "metric": {"value": "NLL（均值、中位数、末检查点）、定位（平移、中位数、yaw、曲线面积）、拓扑 F1", "evidence": ev(S1F, 32)},
            "partition": {"value": "final", "evidence": ev(S1F, 32)},
            "status": {"value": "登记的描述量（无登记检验或门槛）", "evidence": ev(S1F, 28)},
            "replicates": {"value": "三种子（arm4/arm3/arm2）", "evidence": ev(S1F, 32)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s1-topology-few-shot",
        "candidate_quote": "少样本读出有定义缺陷",
        "source": src(S1F, 35),
        "answers": {
            "subset": {"value": "k=0/1/2/4/8 的 few-shot", "evidence": ev(S1F, 35)},
            "metric": {"value": "few-shot 读出精度", "evidence": ev(S1F, 35)},
            "partition": {"value": "final", "evidence": ev(S1F, 32)},
            "status": {"value": "登记的描述量（非门）", "evidence": ev(S1F, 28)},
            "replicates": {"value": "三种子", "evidence": ev(S1F, 32)},
        },
        "verdict": "一致",
    })

    # 2. E1
    claims.append({
        "id": "e1-prior-residual-p-tribe-25pct",
        "candidate_quote": "先验加残差（③）在 P 族比纯网络差 25.9%，在 S 族比有偏先验差 1.3%，两族都没有过",
        "source": src(E1, 39),
        "answers": {
            "subset": {"value": "P 族、S 族（E0 的五类场景）", "evidence": ev(E1, 7)},
            "metric": {"value": "e_10（10步预测误差）", "evidence": ev(E1, 39)},
            "partition": {"value": "dev（r2）", "evidence": ev(E1, 7)},
            "status": {"value": "登记的门（H-E1 两族都没有过）", "evidence": ev(E1, 5)},
            "replicates": {"value": "3个种子（③ 的 3 个种子都没有过）", "evidence": ev(E1, 39)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "e1-id-residual-10step-25pct",
        "candidate_quote": "辨识加残差（⑥）的 10 步误差比基线低约 25%",
        "source": src(E1, 41),
        "answers": {
            "subset": {"value": "P 族和 S 族（E0 五类场景）", "evidence": ev(E1, 7)},
            "metric": {"value": "e_10（10步预测误差相对基线降幅）", "evidence": ev(E1, 41)},
            "partition": {"value": "dev（r2）", "evidence": ev(E1, 7)},
            "status": {"value": "只报告项（没有过门）", "evidence": ev(E1, 41)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "e1-f1-low-0038",
        "candidate_quote": "P 族 F1 比 ② 低 0.038，区间 [−0.092, +0.014]",
        "source": src(E1, 42),
        "answers": {
            "subset": {"value": "P 族", "evidence": ev(E1, 42)},
            "metric": {"value": "F1（分类指标）", "evidence": ev(E1, 42)},
            "partition": {"value": "dev（r2）", "evidence": ev(E1, 7)},
            "status": {"value": "只报告项（不过门）", "evidence": ev(E1, 42)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # 3. S2
    claims.append({
        "id": "s2-long-target-success-0",
        "candidate_quote": "训练后门叫停，长目标成功率全是 0",
        "source": src(S2, 6),
        "answers": {
            "subset": {"value": "train 留出世界，50 条长目标", "evidence": ev(S2, 6)},
            "metric": {"value": "成功率", "evidence": ev(S2, 6)},
            "partition": {"value": "事后诊断（dev 和 final 都没有运行）", "evidence": ev(S2, 8)},
            "status": {"value": "登记的门（训练后门）", "evidence": ev(S2, 6)},
            "replicates": {"value": "三个臂（A/B/C）", "evidence": ev(S2, 44)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s2-arm-a-b-c-short-step",
        "candidate_quote": "诊断（种子 42，A / B / C）：短目标 0/20、0/20、1/20；一步误差比 2.785、0.036、0.299",
        "source": src(S2, 44),
        "answers": {
            "subset": {"value": "train 留出世界，种子 42", "evidence": ev(S2, 40)},
            "metric": {"value": "短目标成功率（n/20）、一步误差比", "evidence": ev(S2, 44)},
            "partition": {"value": "事后诊断", "evidence": ev(S2, 8)},
            "status": {"value": "诊断（非登记门）", "evidence": ev(S2, 44)},
            "replicates": {"value": "种子 42，单次", "evidence": ev(RLOG, 3019)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s2-arm-spearman",
        "candidate_quote": "代价与 BFS 距离 Spearman 相关是 0.286、−0.087、0.127",
        "source": src(S2, 44),
        "answers": {
            "subset": {"value": "train 留出世界，种子 42", "evidence": ev(S2, 40)},
            "metric": {"value": "代价与 BFS 距离的 Spearman 相关", "evidence": ev(S2, 44)},
            "partition": {"value": "事后诊断", "evidence": ev(S2, 8)},
            "status": {"value": "诊断", "evidence": ev(S2, 44)},
            "replicates": {"value": "单次（种子 42）", "evidence": ev(RLOG, 3019)},
        },
        "verdict": "一致",
    })

    # 4. S3 一阶段
    claims.append({
        "id": "s3p1-h1-0777",
        "candidate_quote": "情景库减 GRU +0.777，过",
        "source": src(S3P1, 27),
        "answers": {
            "subset": {"value": "第一阶段（情景库 vs GRU）", "evidence": ev(S3P1, 27)},
            "metric": {"value": "F1（情景库减 GRU 的差值）", "evidence": ev(S3P1, 27)},
            "partition": {"value": "dev", "evidence": ev(S3P1, 27)},
            "status": {"value": "登记的门（H1）", "evidence": ev(S3P1, 27)},
            "replicates": {"value": "未说明（H1 是 dev 的点值）", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p1-h2-neg0052",
        "candidate_quote": "学习检索减手工线索 −0.052，没有过",
        "source": src(S3P1, 28),
        "answers": {
            "subset": {"value": "第一阶段（学习检索 vs 手工线索）", "evidence": ev(S3P1, 28)},
            "metric": {"value": "F1（差值）", "evidence": ev(S3P1, 28)},
            "partition": {"value": "dev", "evidence": ev(S3P1, 28)},
            "status": {"value": "登记的门（H2，未通过）", "evidence": ev(S3P1, 28)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p1-h3-tribe-drop",
        "candidate_quote": "换世界族之后旧族下降，手工线索臂 0.765、学习检索臂 0.697，门槛是 0.05，没有过",
        "source": src(S3P1, 29),
        "answers": {
            "subset": {"value": "换世界族后旧族（H3）", "evidence": ev(S3P1, 29)},
            "metric": {"value": "旧族 F1 值", "evidence": ev(S3P1, 29)},
            "partition": {"value": "dev", "evidence": ev(S3P1, 29)},
            "status": {"value": "登记的门（H3，未通过）", "evidence": ev(S3P1, 29)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # 5. S3 二阶段
    claims.append({
        "id": "s3p2-h1-0760",
        "candidate_quote": "H1 +0.760，过",
        "source": src(S3P2F, 23),
        "answers": {
            "subset": {"value": "第二阶段，A2 − A1（情景库减 GRU）", "evidence": ev(S3P2F, 23)},
            "metric": {"value": "F1 差值（A2 − A1）", "evidence": ev(S3P2F, 23)},
            "partition": {"value": "final", "evidence": ev(S3P2F, 23)},
            "status": {"value": "登记的门（H1，通过）", "evidence": ev(S3P2F, 23)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p2-h2-0011",
        "candidate_quote": "H2 +0.011（−0.012, +0.034），没有过",
        "source": src(S3P2F, 24),
        "answers": {
            "subset": {"value": "第二阶段，A3H − A2（学习检索减手工线索）", "evidence": ev(S3P2F, 24)},
            "metric": {"value": "F1 差值（A3H − A2）", "evidence": ev(S3P2F, 24)},
            "partition": {"value": "final", "evidence": ev(S3P2F, 24)},
            "status": {"value": "登记的门（H2，未通过）", "evidence": ev(S3P2F, 24)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p2-h2b-0045",
        "candidate_quote": "H2b +0.045，过",
        "source": src(S3P2F, 25),
        "answers": {
            "subset": {"value": "第二阶段，A3H − A3S", "evidence": ev(S3P2F, 25)},
            "metric": {"value": "F1 差值（A3H − A3S）", "evidence": ev(S3P2F, 25)},
            "partition": {"value": "final", "evidence": ev(S3P2F, 25)},
            "status": {"value": "登记的门（H2b，通过）", "evidence": ev(S3P2F, 25)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p2-h3p-retain-0027",
        "candidate_quote": "H3′ 保留 +0.027、可塑性 +0.005，都过",
        "source": src(S3P2F, 26),
        "answers": {
            "subset": {"value": "A2-R64 的 F1 下降（H3′ 保留）；C0 − R64 的 F2（可塑性）", "evidence": ev(S3P2F, 26)},
            "metric": {"value": "F1 下降量 / F2 值", "evidence": ev(S3P2F, 26)},
            "partition": {"value": "final", "evidence": ev(S3P2F, 26)},
            "status": {"value": "登记的门（H3′，通过）", "evidence": ev(S3P2F, 26)},
            "replicates": {"value": "三个种子（0.071、0.057、0.094）", "evidence": ev(S3P2F, 38)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p2-replay-4pct-buffer",
        "candidate_quote": "4% 的回放挡住手工线索臂的遗忘",
        "source": src(S3P2F, 38),
        "answers": {
            "subset": {"value": "手工线索臂（A2），F2 阶段", "evidence": ev(S3P2F, 38)},
            "metric": {"value": "F1 下降量（缓冲 4%）", "evidence": ev(S3P2F, 38)},
            "partition": {"value": "final", "evidence": ev(S3P2F, 38)},
            "status": {"value": "登记的描述量", "evidence": ev(S3P2F, 38)},
            "replicates": {"value": "三个种子", "evidence": ev(S3P2F, 38)},
        },
        "verdict": "一致",
    })

    # 6. S3 三阶段
    claims.append({
        "id": "s3p3-k1-k7-pass",
        "candidate_quote": "晋升与回滚的契约成立",
        "source": src(S3P3F, 12),
        "answers": {
            "subset": {"value": "S3 第三阶段（符号读出、不训练）", "evidence": ev(S3P3F, 12)},
            "metric": {"value": "契约门 K1–K7", "evidence": ev(S3P3F, 12)},
            "partition": {"value": "final（只跑一次）", "evidence": ev(S3P3F, 12)},
            "status": {"value": "登记的门（契约门全部通过）", "evidence": ev(S3P3F, 12)},
            "replicates": {"value": "final 只跑一次", "evidence": ev(S3P3F, 12)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p3-desc-0548",
        "candidate_quote": "比内容置换的记忆高 0.548",
        "source": src(S3P3F, 44),
        "answers": {
            "subset": {"value": "S3 第三阶段（全部固定格查询）", "evidence": ev(S3P3F, 44)},
            "metric": {"value": "G − 内容置换的 G（诱饵事件）", "evidence": ev(S3P3F, 44)},
            "partition": {"value": "final（只跑一次）", "evidence": ev(S3P3F, 12)},
            "status": {"value": "登记的描述量", "evidence": ev(S3P3F, 44)},
            "replicates": {"value": "final 只跑一次", "evidence": ev(S3P3F, 12)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p3-desc-0001-fixed",
        "candidate_quote": "全部固定格查询上与照抄当前打平（+0.001）",
        "source": src(S3P3F, 46),
        "answers": {
            "subset": {"value": "全部固定格查询", "evidence": ev(S3P3F, 46)},
            "metric": {"value": "G − 照抄当前", "evidence": ev(S3P3F, 46)},
            "partition": {"value": "final（只跑一次）", "evidence": ev(S3P3F, 12)},
            "status": {"value": "登记的描述量", "evidence": ev(S3P3F, 46)},
            "replicates": {"value": "final 只跑一次", "evidence": ev(S3P3F, 12)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p3-desc-neg0001-mode",
        "candidate_quote": "门控减多数票 −0.001",
        "source": src(S3P3F, 72),
        "answers": {
            "subset": {"value": "S3 第三阶段", "evidence": ev(S3P3F, 12)},
            "metric": {"value": "G − MODE", "evidence": ev(S3P3F, 72)},
            "partition": {"value": "final（只跑一次）", "evidence": ev(S3P3F, 12)},
            "status": {"value": "登记的描述量", "evidence": ev(S3P3F, 72)},
            "replicates": {"value": "final 只跑一次", "evidence": ev(S3P3F, 12)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s3p3-desc-0339-rollback",
        "candidate_quote": "回滚减不回滚 +0.339",
        "source": src(S3P3F, 79),
        "answers": {
            "subset": {"value": "S3 第三阶段（全部固定格查询）", "evidence": ev(S3P3F, 79)},
            "metric": {"value": "G − G-NR（回滚减不回滚）", "evidence": ev(S3P3F, 79)},
            "partition": {"value": "final（只跑一次）", "evidence": ev(S3P3F, 12)},
            "status": {"value": "登记的描述量", "evidence": ev(S3P3F, 79)},
            "replicates": {"value": "final 只跑一次", "evidence": ev(S3P3F, 12)},
        },
        "verdict": "一致",
    })

    # 7. S4 一期
    claims.append({
        "id": "s4p1-six-gates-pass",
        "candidate_quote": "一期六门全过：碰撞动力学 D 0.873",
        "source": src(S4P1F, 19),
        "answers": {
            "subset": {"value": "有碰撞事件（有模拟器监督、二维等质量弹性圆盘、结构化检测、真值位姿）", "evidence": ev(S4P1F, 19)},
            "metric": {"value": "D（碰撞动力学）", "evidence": ev(S4P1F, 22)},
            "partition": {"value": "final", "evidence": ev(S4P1F, 19)},
            "status": {"value": "登记的门（六门全过）", "evidence": ev(S4P1F, 19)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p1-false-positive-0071",
        "candidate_quote": "擦边误差比 0.071",
        "source": src(S4P1F, 25),
        "answers": {
            "subset": {"value": "擦边步（L-int 对 E-B 碰撞步的速度误差均值比）", "evidence": ev(S4P1F, 25)},
            "metric": {"value": "误差均值比（HF：不误报门）", "evidence": ev(S4P1F, 25)},
            "partition": {"value": "final", "evidence": ev(S4P1F, 19)},
            "status": {"value": "登记的门（HF，通过）", "evidence": ev(S4P1F, 25)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p1-extrapolate-10discs-0867",
        "candidate_quote": "外推到 10 个盘 D 0.867",
        "source": src(S4P1F, 26),
        "answers": {
            "subset": {"value": "外推到 10 盘（HD-x 门）", "evidence": ev(S4P1F, 26)},
            "metric": {"value": "D（碰撞动力学）", "evidence": ev(S4P1F, 26)},
            "partition": {"value": "final", "evidence": ev(S4P1F, 19)},
            "status": {"value": "登记的门（HD-x，通过）", "evidence": ev(S4P1F, 26)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p1-reidentify-0123",
        "candidate_quote": "有碰撞事件上，带交互的模型比不带交互的重认高 0.123",
        "source": src(S4P1F, 34),
        "answers": {
            "subset": {"value": "有碰撞事件（H2 门）", "evidence": ev(S4P1F, 34)},
            "metric": {"value": "重识别准确率差（L-int − L-ind）", "evidence": ev(S4P1F, 34)},
            "partition": {"value": "final", "evidence": ev(S4P1F, 19)},
            "status": {"value": "登记的门（H2，通过）", "evidence": ev(S4P1F, 34)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # 8. S4 二期
    claims.append({
        "id": "s4p2-8-gates-7",
        "candidate_quote": "二期 8 门过 7：全部事件上门控混合的重认 0.835，真实物理 0.836",
        "source": src(S4P2F, 24),
        "answers": {
            "subset": {"value": "全部事件（E-P 和 E-B）", "evidence": ev(S4P2F, 24)},
            "metric": {"value": "D（重认精度）", "evidence": ev(S4P2F, 24)},
            "partition": {"value": "final", "evidence": ev(S4P2F, 17)},
            "status": {"value": "登记的门（8 门过 7）", "evidence": ev(S4P2F, 17)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p2-gr-0072",
        "candidate_quote": "有碰撞事件上，学到的响应比门开时乱猜方向高 0.072",
        "source": src(S4P2F, 30),
        "answers": {
            "subset": {"value": "有碰撞事件（GR 门）", "evidence": ev(S4P2F, 30)},
            "metric": {"value": "D 差值（GR）", "evidence": ev(S4P2F, 30)},
            "partition": {"value": "final", "evidence": ev(S4P2F, 17)},
            "status": {"value": "登记的门（GR，通过）", "evidence": ev(S4P2F, 30)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p2-dyn-0868",
        "candidate_quote": "D 0.868",
        "source": src(S4P2F, 52),
        "answers": {
            "subset": {"value": "全部事件（GD 门）", "evidence": ev(S4P2F, 52)},
            "metric": {"value": "D（动力学）", "evidence": ev(S4P2F, 52)},
            "partition": {"value": "final", "evidence": ev(S4P2F, 17)},
            "status": {"value": "登记的门（GD）", "evidence": ev(S4P2F, 52)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s4p2-reappear-calibration-fail",
        "candidate_quote": "有碰撞事件重新出现时的校准不成立（GK2 不过）",
        "source": src(S4P2F, 34),
        "answers": {
            "subset": {"value": "有碰撞事件重新出现那一刻（GK2）", "evidence": ev(S4P2F, 34)},
            "metric": {"value": "覆盖率（0.745，门槛 0.75）", "evidence": ev(S4P2F, 34)},
            "partition": {"value": "final", "evidence": ev(S4P2F, 17)},
            "status": {"value": "登记的门（GK2，不过）", "evidence": ev(S4P2F, 34)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # 9. S5
    claims.append({
        "id": "s5-gt1-0088",
        "candidate_quote": "GT3 过；GT1、GT2、GA、GR 不过；换域全崩",
        "source": src(S5F, 15),
        "answers": {
            "subset": {"value": "L=64 标签档；S5 一期 final", "evidence": ev(S5F, 15)},
            "metric": {"value": "R2 AP（GT1/GT2）、RMSE（GT3）、达标步数（GA）、墙钟/保留率（GR）", "evidence": ev(S5F, 15)},
            "partition": {"value": "final", "evidence": ev(S5F, 15)},
            "status": {"value": "登记的门（GT1/GT2/GT3/GA/GR）", "evidence": ev(S5F, 15)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s5-gr-rlt-11pct",
        "candidate_quote": "GR 墙钟只降 11%，要 15%，不过",
        "source": src(S5F, 19),
        "answers": {
            "subset": {"value": "S5 一期 final，RLT 门（GR）", "evidence": ev(S5F, 19)},
            "metric": {"value": "蒸馏每步墙钟降幅（%）", "evidence": ev(S5F, 19)},
            "partition": {"value": "final", "evidence": ev(S5F, 19)},
            "status": {"value": "登记的门（GR，不过）", "evidence": ev(S5F, 19)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s5-shift-all-domain",
        "candidate_quote": "换域全崩",
        "source": src(S5F, 48),
        "answers": {
            "subset": {"value": "SHIFT_ALL 换域（所有臂）", "evidence": ev(S5F, 48)},
            "metric": {"value": "R2 AP（跌到 0.014–0.042，接近随机）", "evidence": ev(S5F, 48)},
            "partition": {"value": "final", "evidence": ev(S5F, 48)},
            "status": {"value": "只报告项（非登记门）", "evidence": ev(S5F, 21)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s5-multi-teacher-0004",
        "candidate_quote": "多教师合一：S5 里没有胜过较好的单教师",
        "source": src(S5F, 47),
        "answers": {
            "subset": {"value": "S5 一期 final；L=64 和 L=512 档", "evidence": ev(S5F, 47)},
            "metric": {"value": "R2 AP（A3 − max(A1,A2)）", "evidence": ev(S5F, 47)},
            "partition": {"value": "final", "evidence": ev(S5F, 47)},
            "status": {"value": "只报告项", "evidence": ev(S5F, 55)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # 10. S6 一期
    claims.append({
        "id": "s6p1-gs-0095",
        "candidate_quote": "自选减随机 +0.095",
        "source": src(S6F, 16),
        "answers": {
            "subset": {"value": "S4 的圆盘世界，自选集成（E）减随机（R）", "evidence": ev(S6F, 52)},
            "metric": {"value": "D（碰撞预测差值）", "evidence": ev(S6F, 16)},
            "partition": {"value": "final", "evidence": ev(S6F, 16)},
            "status": {"value": "登记的门（GS，通过）", "evidence": ev(S6F, 16)},
            "replicates": {"value": "每个重复都 ≥ +0.03（门条件之一）", "evidence": ev(S6F, 16)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p1-gp-epinet-0099",
        "candidate_quote": "epinet 减随机 +0.099",
        "source": src(S6F, 22),
        "answers": {
            "subset": {"value": "S4 的圆盘世界，epinet（P）减随机（R）", "evidence": ev(S6F, 52)},
            "metric": {"value": "D（碰撞预测差值）", "evidence": ev(S6F, 22)},
            "partition": {"value": "final", "evidence": ev(S6F, 22)},
            "status": {"value": "登记的门（GP，通过）", "evidence": ev(S6F, 22)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p1-gx-extrapolate-0093",
        "candidate_quote": "外推到 10 个盘 +0.093",
        "source": src(S6F, 23),
        "answers": {
            "subset": {"value": "外推到 10 盘（GX），圆盘世界", "evidence": ev(S6F, 52)},
            "metric": {"value": "D 差值（D(E)−D(R)）", "evidence": ev(S6F, 23)},
            "partition": {"value": "final", "evidence": ev(S6F, 23)},
            "status": {"value": "登记的门（GX，通过）", "evidence": ev(S6F, 23)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p1-gkf-1068-fail",
        "candidate_quote": "自由运动误差对代用规则的比是 1.068，上界超过 1.20，GK-F 不过",
        "source": src(S6F, 21),
        "answers": {
            "subset": {"value": "自由运动步（GK-F）", "evidence": ev(S6F, 21)},
            "metric": {"value": "自由误差 E/Z 比（1.068，上界 1.243）", "evidence": ev(S6F, 21)},
            "partition": {"value": "final", "evidence": ev(S6F, 21)},
            "status": {"value": "登记的门（GK-F，不过）", "evidence": ev(S6F, 21)},
            "replicates": {"value": "5 个重复（1.142、0.973、1.056、1.057、1.119）", "evidence": ev(S6F, 25)},
        },
        "verdict": "一致",
    })

    # 11. S6 二期摸底
    claims.append({
        "id": "s6p2-main-arm-0361",
        "candidate_quote": "主臂新技能 0.361，诱饵占 3.2%",
        "source": src(S6P2D, 21),
        "answers": {
            "subset": {"value": "S6 二期摸底（I 轮），N+（主臂）", "evidence": ev(S6P2D, 21)},
            "metric": {"value": "新技能值（N+）和诱饵比例", "evidence": ev(S6P2D, 27)},
            "partition": {"value": "摸底（单次重复，不是登记运行）", "evidence": ev(S6P2D, 27)},
            "status": {"value": "诊断（非登记门，单次摸底）", "evidence": ev(S6P2D, 27)},
            "replicates": {"value": "单次重复，无置信区间", "evidence": ev(S6P2D, 27)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p2-u-0331-32pct",
        "candidate_quote": "便宜规则 U 0.331、诱饵占 32%",
        "source": src(S6P2D, 22),
        "answers": {
            "subset": {"value": "S6 二期摸底，U+ 臂", "evidence": ev(S6P2D, 22)},
            "metric": {"value": "U+ 值和诱饵比例", "evidence": ev(S6P2D, 27)},
            "partition": {"value": "摸底（单次重复，不是登记运行）", "evidence": ev(S6P2D, 27)},
            "status": {"value": "诊断（非登记门）", "evidence": ev(S6P2D, 27)},
            "replicates": {"value": "单次重复", "evidence": ev(S6P2D, 27)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p2-q-0288-47pct",
        "candidate_quote": "Q 0.288、诱饵占 47%",
        "source": src(S6P2D, 23),
        "answers": {
            "subset": {"value": "S6 二期摸底，Q+ 臂", "evidence": ev(S6P2D, 23)},
            "metric": {"value": "Q+ 值和诱饵比例", "evidence": ev(S6P2D, 27)},
            "partition": {"value": "摸底（单次重复，不是登记运行）", "evidence": ev(S6P2D, 27)},
            "status": {"value": "诊断（非登记门）", "evidence": ev(S6P2D, 27)},
            "replicates": {"value": "单次重复", "evidence": ev(S6P2D, 27)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s6p2-random-neg0058",
        "candidate_quote": "随机 −0.058",
        "source": src(S6P2D, 25),
        "answers": {
            "subset": {"value": "S6 二期摸底，R+ 臂（随机）", "evidence": ev(S6P2D, 25)},
            "metric": {"value": "R+ 值", "evidence": ev(S6P2D, 25)},
            "partition": {"value": "摸底（单次重复）", "evidence": ev(S6P2D, 27)},
            "status": {"value": "诊断（非登记门）", "evidence": ev(S6P2D, 27)},
            "replicates": {"value": "单次重复", "evidence": ev(S6P2D, 27)},
        },
        "verdict": "一致",
    })

    # 12. V10-E2a
    claims.append({
        "id": "v10-e2a-50pct-sparse",
        "candidate_quote": "5% 稀疏率下中位时间少 50.94%，作者基准是 54.69%",
        "source": src(B9, 16),
        "answers": {
            "subset": {"value": "5% 稀疏率，6 config，非作者复测（card 口径）", "evidence": ev(B9, 16)},
            "metric": {"value": "中位时间减少率（%）", "evidence": ev(B9, 16)},
            "partition": {"value": "final（非作者独立复测）", "evidence": ev(B9, 16)},
            "status": {"value": "登记的门（≥30%，通过）", "evidence": ev(B9, 16)},
            "replicates": {"value": "6 config，非作者框架独立复测", "evidence": ev(B9, 16)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "v10-e2a-432-432",
        "candidate_quote": "432/432 个 tick 逐位一致",
        "source": src(B9, 13),
        "answers": {
            "subset": {"value": "18 config × 24 tick，无权威臂", "evidence": ev(B9, 13)},
            "metric": {"value": "逐位一致 tick 数（432/432）", "evidence": ev(B9, 13)},
            "partition": {"value": "final（非作者框架）", "evidence": ev(B9, 13)},
            "status": {"value": "登记的门（确定性逐位一致）", "evidence": ev(B9, 13)},
            "replicates": {"value": "432 tick（18 config × 24）", "evidence": ev(B9, 13)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "v10-e2a-20pct-93pct-rollback",
        "candidate_quote": "20% 稀疏率下回退率约 93%，比全量慢 43.8%",
        "source": src(B9, 18),
        "answers": {
            "subset": {"value": "20% 稀疏率（高稀疏）", "evidence": ev(B9, 18)},
            "metric": {"value": "回退率（%）和相对全量的速度", "evidence": ev(B9, 18)},
            "partition": {"value": "final（非作者框架）", "evidence": ev(B9, 18)},
            "status": {"value": "只报告项（非登记门）", "evidence": ev(B9, 18)},
            "replicates": {"value": "非作者复测", "evidence": ev(B9, 18)},
        },
        "verdict": "一致",
    })

    # 13. §14 表格中的数字（部分）
    claims.append({
        "id": "s14-s6-less-experience-0095",
        "candidate_quote": "S6 一期：同样 12000 个标签，自选样本的碰撞预测高 0.095",
        "source": src(S6F, 45),
        "answers": {
            "subset": {"value": "S6 一期 final，12000 个标签", "evidence": ev(S6F, 52)},
            "metric": {"value": "碰撞预测差值（自选减随机）", "evidence": ev(S6F, 45)},
            "partition": {"value": "final", "evidence": ev(S6F, 45)},
            "status": {"value": "登记的门（GS）", "evidence": ev(S6F, 16)},
            "replicates": {"value": "每个重复都 ≥ +0.03", "evidence": ev(S6F, 16)},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s14-rlt-11pct",
        "candidate_quote": "RLT 让蒸馏每步省 11%",
        "source": src(S5F, 19),
        "answers": {
            "subset": {"value": "S5 一期 final，RLT 门（GR）", "evidence": ev(S5F, 19)},
            "metric": {"value": "每步墙钟降幅（%）", "evidence": ev(S5F, 19)},
            "partition": {"value": "final", "evidence": ev(S5F, 19)},
            "status": {"value": "登记的门（GR，不过，只差墙钟一项）", "evidence": ev(S5F, 19)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    claims.append({
        "id": "s14-reliable-pred-087",
        "candidate_quote": "碰撞动力学 D 0.87；一步覆盖率校准",
        "source": src(S4P1F, 22),
        "answers": {
            "subset": {"value": "有碰撞事件（S4 一期）", "evidence": ev(S4P1F, 19)},
            "metric": {"value": "D（碰撞动力学，Bonferroni 区间 [0.862, 0.884]）", "evidence": ev(S4P1F, 22)},
            "partition": {"value": "final", "evidence": ev(S4P1F, 19)},
            "status": {"value": "登记的门（通过）", "evidence": ev(S4P1F, 19)},
            "replicates": {"value": "未说明", "not_stated": True},
        },
        "verdict": "一致",
    })

    # ---- not_evidence（非证据数字）----
    # 这些数字出现在候选稿新增行中，但它们是版本号、门槛本身、或已登记文献编号
    not_evidence = []

    # 候选稿里引用的 §1 表中数字（论文结果，非本机数字，或门槛本身）
    # 一些数字在 §12 大表格里，它们的 candidate_quote 已被上面的 claims 覆盖
    # 还有一些小数出现在 §1 新增行中，属于比较不直接的引用
    # 下面的 not_evidence 条目用于：在新增行中出现，但不是本机结果的数字

    # 注：经检查，§1 表格新增行里的 +0.760、+0.001、0.036 等数字出现在
    # §12 的某行里，该行的 candidate_quote 覆盖了它们。
    # S5 的 0.0004、-0.002、+0.003 等是多教师合一的 R2 AP 细节。

    # 我们在上面的 claims 里用了包含这些数字的 candidate_quote，
    # 验证器会检查每个数字是否落在某条 claim 的 candidate_quote 里。
    # 对于不在上述 claims 覆盖范围内的数字，列入 not_evidence。

    out = {
        "candidate_sha256": CANDIDATE_SHA256,
        "claims": claims,
        "not_evidence": not_evidence,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"写出 {OUT_PATH}，共 {len(claims)} 条 claim")


if __name__ == "__main__":
    main()
