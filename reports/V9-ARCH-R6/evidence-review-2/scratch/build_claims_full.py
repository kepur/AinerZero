#!/usr/bin/env python3
"""生成 claims.json 并验证。"""
from __future__ import annotations
import json
import hashlib
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
CAND_PATH = ROOT / "reports" / "V9-ARCH-R6" / "ARCHITECTURE_V9.r6-candidate.md"
OUT_PATH = ROOT / "reports" / "V9-ARCH-R6" / "evidence-review-2" / "claims.json"

cand_text = CAND_PATH.read_text(encoding="utf-8")
cand_sha = hashlib.sha256(cand_text.encode("utf-8")).hexdigest()

def line_of(p_rel: str, n: int) -> str:
    p = (ROOT / p_rel).resolve()
    lines = p.read_text(encoding="utf-8").split("\n")
    return lines[n - 1].strip()

def make_ev(p_rel: str, n: int) -> dict:
    return {"file": p_rel, "line": n, "text": line_of(p_rel, n)}

claims = []

# ==================== §1 表决定的行 ====================

# Line 27: 旧 RSSM/GRU 退出新主线 (+0.760)
claims.append({
    "id": "s1_table_rssm_s3_0760",
    "candidate_quote": "外置情景库在长间隔读回上远胜 GRU（二阶段 +0.760）",
    "source": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23),
    "answers": {
        "subset": {"value": "长间隔读回（第二阶段 A2 − A1）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "metric": {"value": "F1 差值", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "status": {"value": "登记的门（H1，通过）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "replicates": {"value": "三种子", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 35)},
    },
    "verdict": "一致"
})

# Line 30: 地图即记忆 (+0.001)
claims.append({
    "id": "s1_table_map_s3_0001",
    "candidate_quote": "全部固定格查询合起来不胜过直接看（+0.001）",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46),
    "answers": {
        "subset": {"value": "全部固定格查询", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "metric": {"value": "G − 照抄当前", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

# Line 32: 目标函数用潜空间预测 (0.036, −0.087)
claims.append({
    "id": "s1_table_lewm_s2_0036_neg0087",
    "candidate_quote": "扁平 JEPA 加 SIGReg 的一步误差只有原地不动的 0.036，三个臂里最准；但它的隐空间距离与真实远近的秩相关是 −0.087，完全不会导航",
    "source": make_ev("reports/V9-S2-CLOSE/REPORT.md", 45),
    "answers": {
        "subset": {"value": "train 留出世界，种子 42（臂 B）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "metric": {"value": "一步误差比与代价与真实远近的秩相关（Spearman）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 45)},
        "partition": {"value": "事后诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 8)},
        "status": {"value": "诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "replicates": {"value": "单次（种子 42）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
    },
    "verdict": "一致"
})

# Line 33: 解析数学与学习分开 (0.835, 0.836, 25.9%)
claims.append({
    "id": "s1_table_math_s4_0835_0836",
    "candidate_quote": "全部事件上的重认与用真实物理的滤波器持平（0.835 对 0.836）",
    "source": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24),
    "answers": {
        "subset": {"value": "全部事件", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24)},
        "metric": {"value": "重认准确率（全部事件 0.835，E-P 0.836）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "status": {"value": "登记的门", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_math_e1_259pct",
    "candidate_quote": "在 dev 上 P 族的 10 步预测比纯网络差 25.9%",
    "source": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39),
    "answers": {
        "subset": {"value": "P 族（E0 五类场景）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "metric": {"value": "e_10（10 步预测误差相对纯网络 ② 的差距）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39)},
        "partition": {"value": "dev", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "status": {"value": "登记的门（未通过）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 5)},
        "replicates": {"value": "3 个种子", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39)},
    },
    "verdict": "一致"
})

# Line 35: SE(2) 等变优先靠解析规范化获得 (0.023, +0.010, +0.036, 1/8, −0.006, −0.022, +0.010)
claims.append({
    "id": "s1_table_se2_s4_full",
    "candidate_quote": "规范化臂在有碰撞事件上的重认高 0.023 [+0.010, +0.036]",
    "source": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 102),
    "answers": {
        "subset": {"value": "全量数据，有碰撞事件", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 102)},
        "metric": {"value": "Δ有碰撞准确率", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 100)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "status": {"value": "描述量", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_se2_s4_eighth",
    "candidate_quote": "1/8 数据下看不出差别（−0.006 [−0.022, +0.010]）",
    "source": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 103),
    "answers": {
        "subset": {"value": "1/8 数据，有碰撞事件", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 103)},
        "metric": {"value": "Δ有碰撞准确率", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 100)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "status": {"value": "描述量", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 36: 教师合一 (+0.0004, −0.002, +0.003, −0.011, −0.020, −0.002, 0.009, 0.05)
claims.append({
    "id": "s1_table_teacher_s5_multi",
    "candidate_quote": "64 段标签时 +0.0004 [−0.002, +0.003]，512 段时 −0.011 [−0.020, −0.002]",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 47),
    "answers": {
        "subset": {"value": "L=64 与 L=512 段标签", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 47)},
        "metric": {"value": "R2 AP（多教师合一 A3 − max(A1, A2)）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 47)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 55)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_teacher_s5_gate",
    "candidate_quote": "教师本身在 64 段标签时只多 0.009，门槛是 0.05",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15),
    "answers": {
        "subset": {"value": "L=64 标签档", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "metric": {"value": "R2 AP（A* − A0）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "登记的门（GT1，不过）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 38: 事件驱动的稀疏更新 (5%, 51%, 20%, 93%, 44%)
claims.append({
    "id": "s1_table_sparse_e2a_5pct",
    "candidate_quote": "V10-E2a 在 5% 稀疏率下中位时间少约 51%，登记域内逐位一致",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16),
    "answers": {
        "subset": {"value": "5% 稀疏率，6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "metric": {"value": "中位时间减少（50.94% 约 51%）与逐位一致", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "status": {"value": "登记的门（通过）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "replicates": {"value": "6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_sparse_e2a_20pct",
    "candidate_quote": "20% 稀疏率下回退率约 93%，比全量慢约 44%",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18),
    "answers": {
        "subset": {"value": "20% 稀疏率", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "metric": {"value": "回退率（93.75% 约 93%）与比全量慢（43.8% 约 44%）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "status": {"value": "只报告项", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "replicates": {"value": "非作者复测", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
    },
    "verdict": "一致"
})

# Line 39: 记忆按晋升等级分 FAST/MID/SLOW (−0.001, +0.339)
claims.append({
    "id": "s1_table_mem_s3_gate_mode",
    "candidate_quote": "门控减多数票 −0.001",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 72),
    "answers": {
        "subset": {"value": "全部固定格查询", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "metric": {"value": "G − MODE", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 72)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 72)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_mem_s3_rollback",
    "candidate_quote": "格子改变之后回滚有用（+0.339）",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 79),
    "answers": {
        "subset": {"value": "全部固定格查询", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "metric": {"value": "G − G-NR（回滚减不回滚）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 79)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 79)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

# Line 41: 规划代价与预测空间分开 (−0.087, 0.286, 0/50)
claims.append({
    "id": "s1_table_plan_s2",
    "candidate_quote": "隐空间距离与真实远近的秩相关只有 −0.087 到 0.286；修好训练数据的寻路缺陷之后仍是 0/50",
    "source": make_ev("reports/V9-S2-CLOSE/REPORT.md", 45),
    "answers": {
        "subset": {"value": "train 留出世界，50 条长目标（种子 42）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 6)},
        "metric": {"value": "秩相关与长目标成功率", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 45)},
        "partition": {"value": "事后诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 8)},
        "status": {"value": "诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "replicates": {"value": "单次（种子 42）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
    },
    "verdict": "一致"
})

# Line 42: 学习项只在门开时接管 (0.056)
claims.append({
    "id": "s1_table_learn_s4_gate_cost",
    "candidate_quote": "不门控时，没有碰撞的事件上输给手写规则 0.056；门控之后这块代价消失，碰撞上的收益还在",
    "source": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 79),
    "answers": {
        "subset": {"value": "没有碰撞的事件", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 79)},
        "metric": {"value": "输 E-B 的重认差距（0.056）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 79)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 79)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 43: 便宜基线必设 (0.052, 0.29, 0.33, 0.36)
claims.append({
    "id": "s1_table_cheap_s6_0052",
    "candidate_quote": "S6 一期手写的几何判据在碰撞上高 0.052（描述量）",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40),
    "answers": {
        "subset": {"value": "S4 的圆盘世界", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 52)},
        "metric": {"value": "D 差值（D(E)−D(G) = −0.052，即 G 比 E 高 0.052）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "只报告项（描述量）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
        "replicates": {"value": "3 个重复", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_cheap_s6p2_029_033_036",
    "candidate_quote": "S6 二期摸底里便宜规则的新技能是 0.29 和 0.33，主臂是 0.36",
    "source": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27),
    "answers": {
        "subset": {"value": "I 轮摸底（圆盘世界）", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 21)},
        "metric": {"value": "新技能点值（N+ 0.361 约 0.36，U+ 0.331 约 0.33，Q+ 0.288 约 0.29）", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 21)},
        "partition": {"value": "摸底", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
        "status": {"value": "诊断", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
        "replicates": {"value": "单次重复", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
    },
    "verdict": "一致"
})

# Line 44: 真值依赖清单 (0.137, 0.03, 0.04)
claims.append({
    "id": "s1_table_dep_s3_0137",
    "candidate_quote": "固定格查询掉 0.137",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 95),
    "answers": {
        "subset": {"value": "全部固定格查询", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 95)},
        "metric": {"value": "G-SR − G（换成学生可判路由的差值）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 95)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 95)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_dep_s3_pose_003_004",
    "candidate_quote": "起点位姿偏 5 格之后，收益只剩 0.03–0.04",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 143),
    "answers": {
        "subset": {"value": "稳定格与回滚（起点位姿平移误差到 5 格时）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 143)},
        "metric": {"value": "稳定格上的收益（0.039）与回滚收益（0.032）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 143)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 143)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

# Line 45: 视觉前端先过换域门 (0.014, 0.042, 0.162, 0.073)
claims.append({
    "id": "s1_table_vision_s5_shift",
    "candidate_quote": "外观全换后所有臂的占据读出跌到 0.014–0.042，接近随机",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48),
    "answers": {
        "subset": {"value": "SHIFT_ALL 换域（所有臂）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48)},
        "metric": {"value": "R2 AP", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 21)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_vision_s5_512",
    "candidate_quote": "教师的作用主要在 512 段标签档（V-JEPA 教师 0.162，无教师 0.073，是只报告项，不是门）",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 55),
    "answers": {
        "subset": {"value": "L=512 段标签", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 55)},
        "metric": {"value": "R2 AP（A2 0.162，A0 0.073）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 27)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 55)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 46: 自驱信号分两种情形 (0.095, 0.099, 21%, 1.068, 1.20)
claims.append({
    "id": "s1_table_curiosity_s6_gain",
    "candidate_quote": "自选比随机高 0.095，epinet 高 0.099，外推到 10 个盘仍成立",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16),
    "answers": {
        "subset": {"value": "S4 的圆盘世界（碰撞预测）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 52)},
        "metric": {"value": "D 差值（自选减随机 +0.095、epinet 减随机 +0.099、外推 +0.093）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "登记的门（GS、GP、GX，全过）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "replicates": {"value": "每个重复都 ≥ +0.03", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s1_table_curiosity_s6_free_cost",
    "candidate_quote": "误差比随机高约 21%，这是描述量；登记的自由运动门是对代用规则比的，点值 1.068，区间上界超过 1.20，没有过",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 50),
    "answers": {
        "subset": {"value": "自由运动步", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 50)},
        "metric": {"value": "自由误差相对随机（约高 21%）与代用规则比（点值 1.068，上界 1.243 超过 1.20）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "登记的门（GK-F，不过）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21)},
        "replicates": {"value": "5 个重复", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 25)},
    },
    "verdict": "一致"
})

# ==================== §2 结构的说明行 ====================

# Line 54: S3 第二阶段学习检索持平 (+0.011, +0.05, 0.178)
claims.append({
    "id": "s2_desc_s3_learn_0011_005",
    "candidate_quote": "学习检索与手工线索持平（+0.011，没有过 +0.05 的门）",
    "source": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 24),
    "answers": {
        "subset": {"value": "第二阶段（A3H − A2）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 24)},
        "metric": {"value": "F1 差值", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 24)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "status": {"value": "登记的门（H2，未通过）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 24)},
        "replicates": {"value": "三种子", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s2_desc_s3_time_0178",
    "candidate_quote": "不看时间的统一池，让回合内读回低 0.178",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 53),
    "answers": {
        "subset": {"value": "S3 第三阶段（全部固定格查询）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "metric": {"value": "不看时间（0）与看时间的差异（+0.178）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 53)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 53)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

# ==================== §5.1 / §5.3 / §7.6 行 ====================

# Line 74: V0 (5%, 51%, 20%, 93%)
claims.append({
    "id": "s51_v0_e2a",
    "candidate_quote": "E2a：5% 稀疏率下中位时间少约 51%，逐位一致；20% 时回退率约 93%",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16),
    "answers": {
        "subset": {"value": "5% 与 20% 稀疏率", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "metric": {"value": "中位时间减少与回退率", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "status": {"value": "登记的门（通过）与只报告项", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "replicates": {"value": "6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
    },
    "verdict": "一致"
})

# Line 76: S3 (4%)
claims.append({
    "id": "s51_s3_4pct",
    "candidate_quote": "4% 的回放挡住手工线索臂的遗忘",
    "source": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38),
    "answers": {
        "subset": {"value": "手工线索臂（A2）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
        "metric": {"value": "F1 下降（0.027）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "status": {"value": "登记的门（H3′，通过）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 26)},
        "replicates": {"value": "3 个种子", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
    },
    "verdict": "一致"
})

# Line 113: §5.3 前置检查 (0.3)
claims.append({
    "id": "s53_over_budget_03h",
    "candidate_quote": "超出批准预算约 0.3 小时",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67),
    "answers": {
        "subset": {"value": "S5 运行评测与算门阶段", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "metric": {"value": "锁内耗时超出量（约 0.3 h）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "replicates": {"value": "单次运行", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
    },
    "verdict": "一致"
})

# Line 123: §7.6 RLT (73%, 11%, 15%)
claims.append({
    "id": "s76_rlt_73_11_15",
    "candidate_quote": "保留 73% 的 token，读出不降；蒸馏每步只快 11%，门槛是 15%",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19),
    "answers": {
        "subset": {"value": "S5 一期 final，RLT 门（GR）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "metric": {"value": "保留率（0.727 约 73%）与每步墙钟降幅（11.0% 对门槛 15%）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "登记的门（GR，不过）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 124: §7.6 教师对齐 (0.80, 0.7)
claims.append({
    "id": "s76_teacher_align_080_07",
    "candidate_quote": "达标步数比 0.80，门槛是 0.7；最终读出没有超过不加对齐的臂",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 18),
    "answers": {
        "subset": {"value": "L=512 标签档（GA 门）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 18)},
        "metric": {"value": "达标步数中位比（0.80 对门槛 0.7）与最终 AP（0.067 对 0.073）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 61)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "登记的门（GA，不过）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 18)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 126: §7.6 稀疏更新 (5%)
claims.append({
    "id": "s76_sparse_5pct",
    "candidate_quote": "世界侧的参考实现在 5% 稀疏率下达到了目标",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16),
    "answers": {
        "subset": {"value": "5% 稀疏率", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "metric": {"value": "中位时间减少 50.94%（≥30% 目标）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "status": {"value": "登记的门（通过）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "replicates": {"value": "6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
    },
    "verdict": "一致"
})

# ==================== §12 证据回写大表格的行 ====================

# Line 144: S1 一期 (0.01, 0.75)
claims.append({
    "id": "s12_s1_001_075",
    "candidate_quote": "定位三臂相差在 0.01 m 以内；拓扑 F1 九格都是 0.75，少样本处在随机水平",
    "source": make_ev("reports/V9-S1-final/REPORT.md", 34),
    "answers": {
        "subset": {"value": "final 分区，定位与拓扑少样本", "evidence": make_ev("reports/V9-S1-final/REPORT.md", 34)},
        "metric": {"value": "定位差距（0.01 m）与拓扑 F1（0.75）", "evidence": make_ev("reports/V9-S1-final/REPORT.md", 35)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S1-final/REPORT.md", 32)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S1-final/REPORT.md", 28)},
        "replicates": {"value": "三种子", "evidence": make_ev("reports/V9-S1-final/REPORT.md", 32)},
    },
    "verdict": "一致"
})

# Line 145: S1 二期 E1 (25.9%, 1.3%, 25%, 0.038)
claims.append({
    "id": "s12_e1_p_s_tribe",
    "candidate_quote": "先验加残差（③）在 P 族比纯网络差 25.9%，在 S 族比有偏先验差 1.3%，两族都没有过",
    "source": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39),
    "answers": {
        "subset": {"value": "P 族与 S 族（E0 五类场景）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "metric": {"value": "e_10 差距", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39)},
        "partition": {"value": "dev", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "status": {"value": "登记的门（H-E1，未通过）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 5)},
        "replicates": {"value": "3 个种子", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_e1_id_25_0038",
    "candidate_quote": "辨识加残差（⑥）的 10 步误差比基线低约 25%，但 P 族碰撞 F1 低 0.038",
    "source": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 41),
    "answers": {
        "subset": {"value": "P 族（E0 五类场景）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "metric": {"value": "e_10（降约 25%）与碰撞 F1（低 0.038）", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 42)},
        "partition": {"value": "dev", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 7)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-E1-CONCLUSION/CONCLUSION.md", 42)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 146: S2 (0/20, 0/20, 1/20, 2.785, 0.036, 0.299, 0.286, −0.087, 0.127, 0/50)
claims.append({
    "id": "s12_s2_long_target_050",
    "candidate_quote": "50 条长目标上，三个臂的所有规划配置成功率都是 0",
    "source": make_ev("reports/V9-S2-CLOSE/REPORT.md", 6),
    "answers": {
        "subset": {"value": "train 留出世界，50 条长目标", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 6)},
        "metric": {"value": "成功率", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 6)},
        "partition": {"value": "事后诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 8)},
        "status": {"value": "登记的门（训练后门）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 6)},
        "replicates": {"value": "三个臂（A/B/C）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 44)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s2_fixed_data_050",
    "candidate_quote": "修好寻路数据之后长目标仍是 0/50",
    "source": make_ev("RESEARCH_LOG.md", 3019),
    "answers": {
        "subset": {"value": "修好寻路数据后的 50 条长目标", "evidence": make_ev("RESEARCH_LOG.md", 3019)},
        "metric": {"value": "长目标成功率（0/50）", "evidence": make_ev("RESEARCH_LOG.md", 3019)},
        "partition": {"value": "事后诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 8)},
        "status": {"value": "诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "replicates": {"value": "单次（臂 A/B/C）", "evidence": make_ev("RESEARCH_LOG.md", 3019)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s2_diag_short_step_rank",
    "candidate_quote": "诊断（种子 42，A / B / C）：短目标 0/20、0/20、1/20；一步误差比 2.785、0.036、0.299；秩相关 0.286、−0.087、0.127",
    "source": make_ev("reports/V9-S2-CLOSE/REPORT.md", 44),
    "answers": {
        "subset": {"value": "train 留出世界，种子 42（臂 A/B/C）", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "metric": {"value": "短目标成功率、一步误差比、代价与 BFS 距离秩相关", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 44)},
        "partition": {"value": "事后诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 8)},
        "status": {"value": "诊断", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
        "replicates": {"value": "种子 42，单次", "evidence": make_ev("reports/V9-S2-CLOSE/REPORT.md", 40)},
    },
    "verdict": "一致"
})

# Line 147: S3 一阶段 (+0.777, −0.052, 0.765, 0.697, 0.05)
claims.append({
    "id": "s12_s3p1_h1_h2",
    "candidate_quote": "情景库减 GRU +0.777，过；学习检索减手工线索 −0.052，没有过",
    "source": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27),
    "answers": {
        "subset": {"value": "第一阶段（情景库 vs GRU，学习检索 vs 手工线索）", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27)},
        "metric": {"value": "F1 差值（H1、H2）", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27)},
        "partition": {"value": "dev", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27)},
        "status": {"value": "登记的门（H1 通过，H2 未通过）", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s3p1_h3_drop",
    "candidate_quote": "换世界族之后旧族下降，手工线索臂 0.765、学习检索臂 0.697，门槛是 0.05，没有过",
    "source": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 29),
    "answers": {
        "subset": {"value": "换世界族后旧族（H3 门）", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 29)},
        "metric": {"value": "旧族 F1 与下降门槛", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 29)},
        "partition": {"value": "dev", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 27)},
        "status": {"value": "登记的门（H3，未通过）", "evidence": make_ev("reports/V9-S3-PHASE1/DEV1-REPORT.md", 29)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 148: S3 二阶段 (+0.760, +0.011, −0.012, +0.034, +0.045, +0.027, +0.005, 0.074, 0.05)
claims.append({
    "id": "s12_s3p2_gates",
    "candidate_quote": "H1 +0.760，过；H2 +0.011（−0.012, +0.034），没有过；H2b +0.045，过；H3′ 保留 +0.027、可塑性 +0.005，都过",
    "source": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23),
    "answers": {
        "subset": {"value": "第二阶段主门（H1、H2、H2b、H3′）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "metric": {"value": "F1 差值与下降量", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "status": {"value": "登记的门（H1/H2b/H3′ 通过，H2 未通过）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s3p2_a3h_drop",
    "candidate_quote": "学习检索臂在同样的回放容量下下降 0.074，没有满足 0.05",
    "source": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38),
    "answers": {
        "subset": {"value": "学习检索臂（A3H），4% 回放容量", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
        "metric": {"value": "F1 下降量（0.074 对门槛 0.05）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
        "replicates": {"value": "三个种子（0.071、0.057、0.094）", "evidence": make_ev("reports/V9-S3-PHASE2/FINAL-REPORT.md", 38)},
    },
    "verdict": "一致"
})

# Line 149: S3 三阶段 (0.548, +0.001, −0.001, +0.339, −0.137)
claims.append({
    "id": "s12_s3p3_descs",
    "candidate_quote": "比内容置换的记忆高 0.548；全部固定格查询上与照抄当前打平（+0.001）；门控减多数票 −0.001；回滚减不回滚 +0.339；换成学生可判的路由 −0.137",
    "source": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 44),
    "answers": {
        "subset": {"value": "全部固定格查询", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46)},
        "metric": {"value": "各项相对基准的差值（置换、照抄、多数票、不回滚、学生路由）", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 44)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
        "status": {"value": "登记的描述量", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 44)},
        "replicates": {"value": "final 只跑一次", "evidence": make_ev("reports/V9-S3-PHASE3/FINAL-REPORT.md", 12)},
    },
    "verdict": "一致"
})

# Line 150: S4 一期 (0.873, 0.071, 0.867, 0.123, 0.768, 0.781, 0.57)
claims.append({
    "id": "s12_s4p1_gates",
    "candidate_quote": "碰撞动力学 D 0.873；擦边误差比 0.071；外推到 10 个盘 D 0.867；有碰撞事件上，带交互的模型比不带交互的重认高 0.123",
    "source": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19),
    "answers": {
        "subset": {"value": "有碰撞事件与擦边步（S4 一期）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "metric": {"value": "动力学 D、误报比、外推 D、重认差", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 22)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "status": {"value": "登记的门（六门全过）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s4p1_descs",
    "candidate_quote": "全部事件上学习模型的重认低于手写规则（0.768 对 0.781）；输入带上滤波器量级的噪声后 D 降到 0.57",
    "source": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38),
    "answers": {
        "subset": {"value": "全部重新出现事件与扰动输入", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38)},
        "metric": {"value": "准确率（0.768 对 0.781）与噪声下的 D（0.569 约 0.57）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 113)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "status": {"value": "描述量", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 151: S4 二期 (0.835, 0.836, 0.072, 0.868, 0.745, 0.75)
claims.append({
    "id": "s12_s4p2_pass_gates",
    "candidate_quote": "全部事件上门控混合的重认 0.835，真实物理 0.836；有碰撞事件上，学到的响应比门开时乱猜方向高 0.072；D 0.868",
    "source": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24),
    "answers": {
        "subset": {"value": "全部事件与有碰撞事件（S4 二期）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24)},
        "metric": {"value": "重认精度与动力学 D（GD 0.868）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 52)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "status": {"value": "登记的门（8 门过 7）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s4p2_gk2_fail",
    "candidate_quote": "有碰撞事件重新出现时的覆盖率 0.745，门槛 0.75，没有过",
    "source": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 34),
    "answers": {
        "subset": {"value": "有碰撞事件重新出现那一刻", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 34)},
        "metric": {"value": "覆盖率（0.745 对门槛 0.75）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 34)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 17)},
        "status": {"value": "登记的门（GK2，不过）", "evidence": make_ev("reports/V9-S4-PHASE2/FINAL-REPORT.md", 34)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 152: S5 (+0.0088, 0.05, +0.0081, 0.03, 0.80, 0.7, 11%, 15%, 0.014, 0.042, 0.3)
claims.append({
    "id": "s12_s5_gates",
    "candidate_quote": "GT1 +0.0088，要 0.05，不过；GT2 +0.0081，要 0.03，不过；GT3 过；GA 0.80，要 0.7，不过；GR 墙钟只降 11%，要 15%，不过",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15),
    "answers": {
        "subset": {"value": "L=64 与 L=512 档（S5 一期）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "metric": {"value": "AP、RMSE、达标步数、墙钟降幅", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "登记的门（GT3 过；GT1/GT2/GA/GR 不过）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s5_shift_all",
    "candidate_quote": "外观全换后占据读出 0.014–0.042",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48),
    "answers": {
        "subset": {"value": "SHIFT_ALL 换域", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48)},
        "metric": {"value": "R2 AP", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 21)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s5_budget_03h",
    "candidate_quote": "超出批准预算约 0.3 小时",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67),
    "answers": {
        "subset": {"value": "S5 运行评测与算门阶段", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "metric": {"value": "超支耗时（约 0.3 h）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
        "replicates": {"value": "单次运行", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 67)},
    },
    "verdict": "一致"
})

# Line 153: S6 一期 (+0.095, +0.099, +0.093, 1.068, 1.243, 1.20, 0.671, 1.211, 0.954, 0.856, 0.805)
claims.append({
    "id": "s12_s6_pass_gates",
    "candidate_quote": "自选减随机 +0.095；epinet 减随机 +0.099；外推到 10 个盘 +0.093",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16),
    "answers": {
        "subset": {"value": "S4 的圆盘世界（碰撞预测）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 52)},
        "metric": {"value": "D 差值（GS、GP、GX）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "登记的门（全过）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "replicates": {"value": "每个重复都 ≥ +0.03", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s6_gkf_fail",
    "candidate_quote": "自由运动误差对代用规则的比是 1.068，区间上界 1.243，超过 1.20，没有过",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21),
    "answers": {
        "subset": {"value": "自由运动步（GK-F）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21)},
        "metric": {"value": "自由误差 E/Z 比（1.068，上界 1.243 对门槛 1.20）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "登记的门（GK-F，不过）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 21)},
        "replicates": {"value": "5 个重复", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 25)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s6_error_ratios",
    "candidate_quote": "自选相对随机的误差比：碰撞 0.671，自由 1.211，全部盘步 0.954",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 39),
    "answers": {
        "subset": {"value": "碰撞、自由与全部盘步", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 39)},
        "metric": {"value": "E 相对 R 的误差比", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 39)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "只报告项", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 39)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_s6_geom_0856_0805",
    "candidate_quote": "几何判据的 D 是 0.856，高于主臂的 0.805",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40),
    "answers": {
        "subset": {"value": "S4 的圆盘世界（碰撞动力学）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 52)},
        "metric": {"value": "动力学 D（G 0.856 对主臂 E 0.805，差值 −0.052）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "只报告项（描述量）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
        "replicates": {"value": "3 个重复", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 40)},
    },
    "verdict": "一致"
})

# Line 154: S6 二期摸底 (0.361, 3.2%, 0.331, 32%, 0.288, 47%, −0.058)
claims.append({
    "id": "s12_s6p2_pilot",
    "candidate_quote": "主臂新技能 0.361，诱饵占 3.2%；便宜规则 U 0.331、诱饵占 32%，Q 0.288、诱饵占 47%；随机 −0.058",
    "source": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27),
    "answers": {
        "subset": {"value": "I 轮摸底", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 21)},
        "metric": {"value": "新技能得分与诱饵比例（N+、U+、Q+、R+）", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 21)},
        "partition": {"value": "摸底", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
        "status": {"value": "诊断（单次摸底，非门）", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
        "replicates": {"value": "单次重复", "evidence": make_ev("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 27)},
    },
    "verdict": "一致"
})

# Line 155: V10-E2a (5%, 50.94%, 54.69%, 432/432, 20%, 93%, 43.8%)
claims.append({
    "id": "s12_v10_e2a_5pct_author_vs_indep",
    "candidate_quote": "5% 稀疏率下中位时间少 50.94%，作者基准是 54.69%；回退率 0；432/432 个 tick 逐位一致",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16),
    "answers": {
        "subset": {"value": "5% 稀疏率，6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "metric": {"value": "中位时间减少率（独立 50.94%，作者 54.69%）与 432/432 tick 逐位一致", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "status": {"value": "登记的门（通过）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
        "replicates": {"value": "6 config", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 16)},
    },
    "verdict": "一致"
})

claims.append({
    "id": "s12_v10_e2a_20pct_rollback",
    "candidate_quote": "20% 稀疏率下回退率约 93%，比全量慢 43.8%",
    "source": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18),
    "answers": {
        "subset": {"value": "20% 稀疏率", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "metric": {"value": "回退率与比全量慢的比例（43.8%）", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "partition": {"value": "final", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "status": {"value": "只报告项", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
        "replicates": {"value": "非作者复测", "evidence": make_ev("../AnimeWorldZero/reports/V-V9-B9/报告.md", 18)},
    },
    "verdict": "一致"
})

# ==================== §14 表格的行 ====================

# Line 214: S6 一期碰撞预测 (0.095)
claims.append({
    "id": "s14_s6_0095",
    "candidate_quote": "S6 一期：同样 12000 个标签，自选样本的碰撞预测高 0.095",
    "source": make_ev("reports/V9-S6-FINAL/RESULTS.md", 45),
    "answers": {
        "subset": {"value": "S4 的圆盘世界，12000 个标签", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 52)},
        "metric": {"value": "碰撞预测差值（+0.095）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 45)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "status": {"value": "登记的门（GS，通过）", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
        "replicates": {"value": "每个重复都 ≥ +0.03", "evidence": make_ev("reports/V9-S6-FINAL/RESULTS.md", 16)},
    },
    "verdict": "一致"
})

# Line 215: 更少计算 (11%)
claims.append({
    "id": "s14_rlt_11pct",
    "candidate_quote": "世界侧稀疏更新的参考实现；RLT 让蒸馏每步省 11%",
    "source": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19),
    "answers": {
        "subset": {"value": "S5 一期 final，RLT 门（GR）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "metric": {"value": "蒸馏每步墙钟降幅（11.0% 约 11%）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15)},
        "status": {"value": "登记的门（GR，不过）", "evidence": make_ev("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# Line 217: 可靠的预测 (0.87)
claims.append({
    "id": "s14_reliable_087",
    "candidate_quote": "碰撞动力学 D 0.87；一步覆盖率校准",
    "source": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 22),
    "answers": {
        "subset": {"value": "有碰撞事件（S4 一期）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "metric": {"value": "碰撞动力学 D（0.873 约 0.87）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 22)},
        "partition": {"value": "final", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "status": {"value": "登记的门（通过）", "evidence": make_ev("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19)},
        "replicates": {"value": "未说明", "not_stated": True},
    },
    "verdict": "一致"
})

# ==================== not_evidence ====================
not_evidence = [
    {"line_contains": "DA2、V-JEPA 2.1 教师接入", "token": "2.1", "reason": "V-JEPA 的版本号，非实验数值"},
    {"line_contains": "教师是 DA2 和 V-JEPA 2.1", "token": "2.1", "reason": "V-JEPA 的版本号，非实验数值"},
]

out = {
    "candidate_sha256": cand_sha,
    "claims": claims,
    "not_evidence": not_evidence
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Generated {len(claims)} claims, {len(not_evidence)} not_evidence entries to {OUT_PATH}")
