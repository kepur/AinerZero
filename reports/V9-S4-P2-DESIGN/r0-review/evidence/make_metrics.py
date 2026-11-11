"""P213: compact metrics for `relay report --data-file` (all values read from evidence outputs). Usage: python -I -B <this>"""
import json, re
E = "reports/V9-S4-P2-DESIGN/r0-review/evidence"
g = json.load(open(f"{E}/surrogates/gates.json"))
nums = open(f"{E}/numbers/check_design_numbers.txt").read()
cmp3 = open(f"{E}/repro/compare_first3.txt").read()
summ = open(f"{E}/repro/summary-diff.txt").read()
m = re.search(r"(\d+) numbers checked, (\d+) found", nums)
c = re.search(r"cells compared (\d+); correct identical in (\d+)", cmp3)
out = {
    "verdict": "打回（1 必修 M1，4 应修，4 建议）",
    "design_numbers": {"checked": int(m.group(1)), "matched": int(m.group(2))},
    "repro_first3_cells": {"compared": int(c.group(1)), "correct_identical": int(c.group(2)), "all_fields_identical": "fields differing: none" in cmp3},
    "summaries_identical": summ.count("IDENTICAL"),
    "surrogate_worlds": {"main": g["n_main"], "extrap": g["n_extrap"]},
    "off_equals_EB_all_cells": g["off_equals_EB"],
    "gates_passed": {a: g["arms"][a]["passed"] for a in ("L-int-g", "L-int", "OFF", "RAND", "L-ind-g", "SCATTER", "L-ind-geo")},
    "SCATTER": {k: g["arms"]["SCATTER"]["stats"][k]["value"] for k in ("GN", "GA", "GC", "GK1_collision", "GK2_collision", "GD_D", "GX_diff", "GX_C")},
    "LintG_minus_SCATTER_collision": g["paired"]["L-int-g-SCATTER:collision"],
}
json.dump(out, open(f"{E}/metrics.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False)[:600])
