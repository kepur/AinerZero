#!/usr/bin/env python3
"""
find_exact_lines.py
Find exact lines in source files for all quantitative claims.
"""
import subprocess
import os

REPO_ROOT = "/Users/mac/AinerWorkFlow/AinerZero"

def test_line(rel_path, line_no, expected_substring):
    full_path = os.path.join(REPO_ROOT, rel_path)
    res = subprocess.run(["sed", "-n", f"{line_no}p", full_path], capture_output=True, text=True)
    actual_line = res.stdout.strip()
    assert expected_substring in actual_line, f"FAILED on {rel_path}:{line_no}!\nExpected substring: {expected_substring}\nActual line: {actual_line}"
    return actual_line

print("Testing known line numbers...")
# S4 Phase 1
l19 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 19, "六个门全部通过，运行合法")
l22 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 22, "D = 0.873")
l25 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 25, "0.071")
l28 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 28, "D = 0.867")
l31 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 31, "增益 +0.123")
l35 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 35, "0.768，不如手写规则 E-B 的 0.781")
l38 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 38, "D 降到 0.57")
l102 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 102, "+0.023 [+0.010, +0.036]")
l103 = test_line("reports/V9-S4-PHASE1/final/FINAL-REPORT.md", 103, "−0.006 [−0.022, +0.010]")

# S4 Phase 2
l24 = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24, "门控混合的重认 0.835")
l24_phys = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 24, "真实物理 0.836")
l25_sc = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 25, "低 0.072")
l26_gd = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 26, "D = 0.868")
l29_cov = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 29, "覆盖率 0.745，门槛 0.75")
l36_refl = test_line("reports/V9-S4-PHASE2/FINAL-REPORT.md", 36, "按两盘连线做镜面反射，L-int-g 相对它的差，区间含 0")

# S3 Phase 2
l23_s3p2 = test_line("reports/V9-S3-PHASE2/FINAL-REPORT.md", 23, "+0.760（+0.730, +0.790）")

# S3 Phase 3
l46_g_curr = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 46, "+0.001（−0.014, +0.017）")
l47_clean = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 47, "+0.285（+0.270, +0.301）")
l53_unif = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 53, "+0.178（+0.166, +0.191）")
l72_mode = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 72, "−0.001（−0.014, +0.011）")
l80_roll = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 80, "+0.339（+0.316, +0.362）")
l89_route = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 89, "−0.137（−0.155, −0.119）")
l140_recent = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 140, "但「最近一次」比 G 高 0.132")
l144_pose5 = test_line("reports/V9-S3-PHASE3/FINAL-REPORT.md", 144, "平移误差到 5 格时，稳定格上的收益只剩 0.039，回滚的收益只剩 0.032")

# S3 Phase 1
l12_s3p1 = test_line("reports/V9-S3-FINAL/FINAL-REPORT.md", 12, "0.038")

# S2 Close
l8_s2_stop = test_line("reports/V9-S2-CLOSE/REPORT.md", 8, "在进入 dev/final 之前被训练后门叫停")
l45_s2_err = test_line("reports/V9-S2-CLOSE/REPORT.md", 45, "0.036")
l45_s2_rank = test_line("reports/V9-S2-CLOSE/REPORT.md", 45, "Spearman 秩相关是 −0.087")
l49_s2_rssm = test_line("reports/V9-S2-CLOSE/REPORT.md", 49, "每一步都从零状态起步")
l51_s2_long = test_line("reports/V9-S2-CLOSE/REPORT.md", 51, "长目标成功率都是 0")

# S5 Final
l15_gt1 = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 15, "GT1（64 段增益 ≥ 0.05）：0.0088，不过")
l16_gt2 = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 16, "GT2（512 段增益 ≥ 0.03）：0.0081，不过")
l17_gt3 = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 17, "GT3（64 相对 512 增益差 ≥ 0.01）：0.0007，过")
l18_ga = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 18, "GA（占据读出 ≥ 0.70）：0.80，过")
l19_gr = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 19, "GR（RLT 墙钟降 ≥ 15%）：11.1%，不过")
l47_s5_a3 = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 47, "A3 − max(A1, A2)")
l48_s5_t = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 48, "max(A1, A2) − A0")
l51_s5_out = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 51, "0.014–0.042")
l53_s5_vj = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 53, "0.162")
l53_s5_no = test_line("reports/V9-S5-FINAL/RESULTS/REPORT.md", 53, "0.073")

# S6 Final
l13_s6_8 = test_line("reports/V9-S6-FINAL/RESULTS.md", 13, "8 门过 7")
l16_s6_g1 = test_line("reports/V9-S6-FINAL/RESULTS.md", 16, "+0.095")
l17_s6_g2 = test_line("reports/V9-S6-FINAL/RESULTS.md", 17, "+0.099")
l18_s6_g3 = test_line("reports/V9-S6-FINAL/RESULTS.md", 18, "+0.093")
l19_s6_g4 = test_line("reports/V9-S6-FINAL/RESULTS.md", 19, "1.068 [0.893, 1.243]")
l24_s6_col = test_line("reports/V9-S6-FINAL/RESULTS.md", 24, "碰撞步：0.671")
l25_s6_free = test_line("reports/V9-S6-FINAL/RESULTS.md", 25, "自由运动步：1.211")
l26_s6_all = test_line("reports/V9-S6-FINAL/RESULTS.md", 26, "全部盘步：0.954")
l35_s6_d = test_line("reports/V9-S6-FINAL/RESULTS.md", 35, "0.856")
l35_s6_a0 = test_line("reports/V9-S6-FINAL/RESULTS.md", 35, "0.805")

# S6 Phase 2 I round
l15_s6p2 = test_line("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 15, "0.361")
l16_s6p2_u = test_line("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 16, "0.331")
l17_s6p2_q = test_line("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 17, "0.288")
l18_s6p2_r = test_line("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 18, "−0.058")
l24_s6p2_decoy = test_line("reports/V9-S6P2-DESIGN/r1-handoff/REPORT.md", 24, "3.2%")

# E1 Conclusion
l39_e1_10step = test_line("reports/V9-E1-CONCLUSION/CONCLUSION.md", 39, "差 25.9%")
l44_e1_f1 = test_line("reports/V9-E1-CONCLUSION/CONCLUSION.md", 44, "0.871")
l44_e1_p = test_line("reports/V9-E1-CONCLUSION/CONCLUSION.md", 44, "0.898")

# AWZ B9
l8_b9 = test_line("../AnimeWorldZero/reports/V-V9-B9/报告.md", 8, "50.94%")
l11_b9 = test_line("../AnimeWorldZero/reports/V-V9-B9/报告.md", 11, "432/432")
l14_b9 = test_line("../AnimeWorldZero/reports/V-V9-B9/报告.md", 14, "93.47%")

# Negative citations / Design doc non-implementation
l200_titans = test_line("reports/V9-S3-PHASE3-DESIGN/DESIGN-r2.md", 200, "Titans 式记忆")
l50_s3p1_titans = test_line("reports/V9-S3-DESIGN/DESIGN-r2.md", 50, "Titans、Nested Learning，留给第二阶段")
l203_s3p2_titans = test_line("reports/V9-S3-PHASE2-DESIGN/DESIGN-r2.md", 203, "Titans 式记忆")

print("All known line numbers verified successfully with sed -n!")
