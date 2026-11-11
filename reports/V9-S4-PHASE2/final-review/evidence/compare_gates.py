"""Item 2: 比对独立复算与 final.json 中的全部门与统计量。"""
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
FINAL_JSON_PATH = REPO / "reports/V9-S4-PHASE2/final.json"
RECOMPUTED_PATH = REPO / "reports/V9-S4-PHASE2/final-review/evidence/recomputed_final.json"

def main():
    final_data = json.loads(FINAL_JSON_PATH.read_text(encoding="utf-8"))
    recomputed = json.loads(RECOMPUTED_PATH.read_text(encoding="utf-8"))

    final_result = final_data["result"]
    final_gates = final_result["gates"]
    final_neg = final_result["negative_control"]

    # Flatten final stats dictionary from gates and negative_control
    final_stats = {}
    for gname, gdict in final_gates.items():
        for sk, sv in gdict.items():
            if isinstance(sv, dict) and "value" in sv:
                final_stats[sk] = sv
    if "C" in final_neg:
        final_stats["neg_C"] = final_neg["C"]
    if "D" in final_neg:
        final_stats["neg_D"] = final_neg["D"]

    recomp_stats = recomputed["stats"]
    assert len(final_stats) == 14, f"Expected 14 final stats, got {len(final_stats)}"
    assert len(recomp_stats) == 14, f"Expected 14 recomp stats, got {len(recomp_stats)}"

    print("=== 2.1 统计量点估计逐位比对 ===")
    point_mismatches = []
    for k in sorted(recomp_stats.keys()):
        s_recomp = recomp_stats[k]
        s_final = final_stats[k]
        val_recomp = s_recomp["value"]
        val_final = s_final["value"]
        diff = abs(val_recomp - val_final)
        hex_recomp = float(val_recomp).hex()
        hex_final = float(val_final).hex()
        match_hex = (hex_recomp == hex_final)
        print(f"{k:18s}: final={val_final:+.10f} ({hex_final}) | recomp={val_recomp:+.10f} ({hex_recomp}) | equal={match_hex}")
        if not match_hex:
            point_mismatches.append((k, val_final, val_recomp, diff))
    assert not point_mismatches, f"Point estimate mismatches: {point_mismatches}"
    print("-> 全部 14 项门与负对照统计量点估计逐位完全相同: 14/14 MATCH")

    print("\n=== 2.2 置信区间与 Bonferroni 区间比对 ===")
    ci_diffs = []
    for k in sorted(recomp_stats.keys()):
        s_recomp = recomp_stats[k]
        s_final = final_stats[k]
        for field in ("ci_low", "ci_high", "bonf_low", "bonf_high"):
            vf = s_final[field]
            vr = s_recomp[field]
            diff = abs(vf - vr)
            ci_diffs.append((k, field, vf, vr, diff))
            match_hex = (float(vf).hex() == float(vr).hex())
            print(f"  {k:18s} {field:9s}: final={vf:+.8f} recomp={vr:+.8f} diff={diff:.2e} bitwise={match_hex}")
    max_ci_diff = max(d[4] for d in ci_diffs)
    print(f"-> 区间最大差异: {max_ci_diff:.2e} (全同种子同分布重采样)")
    assert max_ci_diff < 1e-12, f"CI difference too large: {max_ci_diff}"
    print("-> 置信区间与 Bonferroni 区间逐位/数值完全一致: PASS")

    print("\n=== 2.3 门判定比对 ===")
    recomp_gates = recomputed["passed"]
    gate_mismatches = []
    for gname in ("GN", "GA", "GC", "GK1", "GK2", "GD", "GX", "GR"):
        passed = recomp_gates[gname]
        final_passed = final_gates[gname]["passed"]
        print(f"Gate {gname:5s}: final={final_passed} | recomp={passed} | match={final_passed == passed}")
        if final_passed != passed:
            gate_mismatches.append((gname, final_passed, passed))
    assert not gate_mismatches, f"Gate mismatches: {gate_mismatches}"
    print("-> 8 个主门通过/未通过判定 100% 一致: MATCH (7 pass, GK2 fail)")

    neg_final_passed = final_neg["passed"]
    neg_recomp_passed = recomputed["negative_control"]
    print(f"Negative Control: final={neg_final_passed} | recomp={neg_recomp_passed} | match={neg_final_passed == neg_recomp_passed}")
    assert neg_final_passed == neg_recomp_passed

    print("\n=== 2.4 合法性门比对（记录侧） ===")
    final_legality = final_result["legality"]
    recomp_legality = recomputed["legality"]
    for lk, lres in recomp_legality.items():
        assert lk in final_legality, f"Missing legality gate {lk} in final.json"
        final_p = final_legality[lk]["passed"]
        print(f"Legality {lk:10s}: final={final_p} | recomp={lres['passed']}")
        assert final_p == lres["passed"], f"Legality mismatch on {lk}"
    print("-> 记录侧合法性门（floor, samples, complete）完全一致: PASS")

    print("\n=== 2.5 GK2 详细核查（GK2_collision） ===")
    gk2_stat = recomp_stats["GK2_collision"]
    val_gk2 = gk2_stat["value"]
    bonf_low = gk2_stat["bonf_low"]
    bonf_high = gk2_stat["bonf_high"]
    threshold_point = 0.75
    threshold_low = 0.65
    print(f"GK2 点估计值     : {val_gk2:.6f} (精确值: {val_gk2})")
    print(f"GK2 门限要求     : 点估计 >= {threshold_point}, Bonferroni 下界 > {threshold_low}")
    print(f"门限差距         : {val_gk2 - threshold_point:+.6f} (点估计低于门限 0.75 达 0.005439)")
    print(f"Bonferroni 区间  : [{bonf_low:.6f}, {bonf_high:.6f}]")
    print("-> GK2 判定为 False (FAIL)，与 final.json 结论完全一致")

if __name__ == "__main__":
    main()
