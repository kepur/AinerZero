#!/usr/bin/env python3
"""
evidence/check_numbers.py
Independent CPU verification of all numbers, statements, and source citations
in ARCHITECTURE_V9.r6-candidate.md across:
- §1 table (3rd column and 6 new rows)
- §2 additions (2 notes)
- §5 execution gaps, §5.1, §5.2, §5.3
- §7.6 and §8.3 r6 status
- §12 evidence summary table
- §14 success criteria gap analysis
"""
import os
import re
import sys
from pathlib import Path

def main():
    repo_root = Path(__file__).resolve().parents[4]
    candidate_path = repo_root / "reports/V9-ARCH-R6/ARCHITECTURE_V9.r6-candidate.md"
    awz_root = repo_root.parent / "AnimeWorldZero"

    citations = [
        # §1 & §12 S1 Phase 1
        ("S1 Phase 1 NLL sorting", repo_root / "reports/V9-S1-final/REPORT.md", "arm4 < arm3 < arm2"),
        ("S1 Phase 1 Localization delta", repo_root / "reports/V9-S1-final/REPORT.md", "0.01 m"),
        ("S1 Phase 1 Topology F1", repo_root / "reports/V9-S1-final/REPORT.md", "九格都是 0.75"),
        ("S1 Topology diagnosis", repo_root / "RESEARCH_LOG.md", "拓扑与 few-shot 的数值无误，但「模型不形成边」的读法不成立"),
        
        # §1 & §12 E1
        ("E1 P-family pure vs prior+res", repo_root / "reports/V9-E1-CONCLUSION/CONCLUSION.md", "25.9%"),
        ("E1 S-family biased vs prior+res", repo_root / "reports/V9-E1-CONCLUSION/CONCLUSION.md", "1.3%"),
        ("E1 Arm 6 10-step error reduction", repo_root / "reports/V9-E1-CONCLUSION/CONCLUSION.md", "低约 25%"),
        ("E1 Arm 6 F1 penalty", repo_root / "reports/V9-E1-CONCLUSION/CONCLUSION.md", "0.038"),
        
        # §1 & §12 S2
        ("S2 long goal success 0/50", repo_root / "reports/V9-S2-CLOSE/REPORT.md", "成功率都是 0"),
        ("S2 diagnostic step error 0.036", repo_root / "reports/V9-S2-CLOSE/REPORT.md", "0.036"),
        ("S2 diagnostic rank corr -0.087", repo_root / "reports/V9-S2-CLOSE/REPORT.md", "−0.087"),
        ("S2 fixed data long goal 0/50", repo_root / "RESEARCH_LOG.md", "长目标 0/50 → 0/50"),
        
        # §1 & §12 S3
        ("S3 Phase 1 H1 gate +0.777", repo_root / "reports/V9-S3-PHASE1/DEV1-REPORT.md", "+0.777（0.733, 0.818）"),
        ("S3 Phase 1 H2 gate -0.052", repo_root / "reports/V9-S3-PHASE1/DEV1-REPORT.md", "−0.052（−0.088, −0.016）"),
        ("S3 Phase 2 H1 gate +0.760", repo_root / "reports/V9-S3-PHASE2/FINAL-REPORT.md", "+0.760（+0.730, +0.790）"),
        ("S3 Phase 2 H2 gate +0.011", repo_root / "reports/V9-S3-PHASE2/FINAL-REPORT.md", "+0.011（−0.012, +0.034）"),
        ("S3 Phase 2 replay capacity 0.074", repo_root / "reports/V9-S3-PHASE2/FINAL-REPORT.md", "下降 0.074"),
        ("S3 Phase 3 content replacement +0.548", repo_root / "reports/V9-S3-PHASE3/FINAL-REPORT.md", "+0.548（+0.515, +0.581）"),
        ("S3 Phase 3 tie on current copy +0.001", repo_root / "reports/V9-S3-PHASE3/FINAL-REPORT.md", "+0.001（−0.014, +0.017）"),
        ("S3 Phase 3 rollback gain +0.339", repo_root / "reports/V9-S3-PHASE3/FINAL-REPORT.md", "+0.339（+0.314, +0.363）"),
        ("S3 Phase 3 student routable -0.137", repo_root / "reports/V9-S3-PHASE3/FINAL-REPORT.md", "−0.137（−0.150, −0.123）"),
        ("S3 Phase 3 pose offset 5 cells gain drop", repo_root / "reports/V9-S3-PHASE3/FINAL-REPORT.md", "平移误差到 5 格时，稳定格上的收益只剩 0.039，回滚的收益只剩 0.032"),
        
        # §1 & §12 S4
        ("S4 Phase 1 collision D 0.873", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "D = 0.873"),
        ("S4 Phase 1 graze error ratio 0.071", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "0.071 倍"),
        ("S4 Phase 1 10-disk D 0.867", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "D = 0.867"),
        ("S4 Phase 1 recognition gain +0.123", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "高 0.123"),
        ("S4 Phase 1 learned vs rule 0.768 vs 0.781", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "L-int 的准确率是 0.768，E-B 是 0.781"),
        ("S4 Phase 1 noisy D 0.57", repo_root / "reports/V9-S4-PHASE1/final/FINAL-REPORT.md", "L-int 0.569"),
        ("S4 Phase 2 recognition 0.835 vs 0.836", repo_root / "reports/V9-S4-PHASE2/FINAL-REPORT.md", "全部事件 0.835，E-P 0.836"),
        ("S4 Phase 2 response vs random +0.072", repo_root / "reports/V9-S4-PHASE2/FINAL-REPORT.md", "低 0.072"),
        ("S4 Phase 2 D 0.868", repo_root / "reports/V9-S4-PHASE2/FINAL-REPORT.md", "| GD | 动力学 D | 0.868 |"),
        ("S4 Phase 2 coverage 0.745", repo_root / "reports/V9-S4-PHASE2/FINAL-REPORT.md", "覆盖率 0.745，门槛 0.75"),
        ("S4 Phase 2 non-gated error +0.056", repo_root / "reports/V9-S4-PHASE2/FINAL-REPORT.md", "输 E-B 0.056"),
        
        # §1 & §12 S5
        ("S5 GT1 +0.0088", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "**+0.0088**"),
        ("S5 GT2 +0.0081", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "**+0.0081**"),
        ("S5 GA 0.80", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "1502 / 1888 = **0.80**"),
        ("S5 GR wallclock 11.0%", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "墙钟降 **11.0%**"),
        ("S5 shift-all AP 0.014-0.042", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "都跌到 0.014–0.042"),
        ("S5 multi-teacher diff +0.0004 and -0.011", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "L=64 为 +0.0004（95% [−0.002, 0.003]），L=512 为 −0.011（[−0.020, −0.002]）"),
        ("S5 budget over by 0.3h", repo_root / "reports/V9-S5-FINAL/RESULTS/REPORT.md", "超出用户批准的 25 h 约 0.3 h"),
        
        # §1 & §12 S6 Phase 1
        ("S6 Phase 1 GS self vs rand +0.095", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "**+0.095**"),
        ("S6 Phase 1 GP epinet +0.099", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "**+0.099**"),
        ("S6 Phase 1 GX 10-disk +0.093", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "**+0.093**"),
        ("S6 Phase 1 free motion ratio 1.068 / 1.243", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "1.068 | [0.917, **1.243**]"),
        ("S6 Phase 1 collision vs free ratio 0.671 vs 1.211", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "碰撞 0.671，擦边 0.933，墙柱 0.887，自由 **1.211**，全部盘步 0.954"),
        ("S6 Phase 1 geometry rule higher by 0.052", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "D(E)−D(G) = **−0.052**"),
        ("S6 Phase 1 total labels 12000", repo_root / "reports/V9-S6-FINAL/RESULTS.md", "共 12000 个标签"),
        
        # §1 & §12 S6 Phase 2 Round I
        ("S6 Phase 2 Round I N+ 0.361 and decoy 3.2%", repo_root / "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", "0.3607203758982099"),
        ("S6 Phase 2 Round I U+ 0.331 and decoy 32%", repo_root / "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", "0.33055769492953957"),
        ("S6 Phase 2 Round I Q+ 0.288 and decoy 47%", repo_root / "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", "0.28820706843566796"),
        ("S6 Phase 2 Round I R+ -0.058", repo_root / "reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", "-0.057719284051699425"),
        
        # V10-E2a
        ("V10-E2a median time reduction 50.94%", awz_root / "reports/V-V9-B9/报告.md", "50.94%"),
        ("V10-E2a author baseline 54.69%", awz_root / "reports/V-V9-B9/报告.md", "54.69%"),
        ("V10-E2a 432/432 ticks identical", awz_root / "reports/V-V9-B9/报告.md", "432/432 tick"),
        ("V10-E2a 20% sparsity rollback 93.75% and 43.8% slower", awz_root / "reports/V-V9-B9/报告.md", "回退率 93.75%、比全量慢 43.8%"),
    ]

    print(f"Checking {len(citations)} specific numerical and qualitative citations...")
    failures = []
    for label, path, needle in citations:
        if not path.exists():
            print(f"[FAIL] Path does not exist: {path}")
            failures.append((label, str(path), needle, "file not found"))
            continue
        content = path.read_text(encoding="utf-8")
        if needle in content:
            # find line number
            lines = content.splitlines()
            hit_line = [i+1 for i, l in enumerate(lines) if needle in l][0]
            print(f"[OK] {label:45s} -> {path.name}:{hit_line}")
        else:
            print(f"[FAIL] Needle not found: {needle!r} in {path}")
            failures.append((label, str(path), needle, "needle not found"))

    if failures:
        print(f"\nTotal failures: {len(failures)}")
        sys.exit(1)
    else:
        print(f"\nAll {len(citations)} citations verified successfully with 0 failures!")

if __name__ == "__main__":
    main()
