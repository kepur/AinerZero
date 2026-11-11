#!/usr/bin/env python3
"""P213: markdown tables of the surrogate gate results (from gates_surrogates.py's JSON), pasted into REPORT.md.
Usage: python -I -B <this> gates.json"""
import json
import sys

r = json.load(open(sys.argv[1]))
A = r["arms"]
ORDER = ("L-int-g", "L-int", "OFF", "RAND", "L-ind-g", "SCATTER", "L-ind-geo", "E-B", "E-P")
GATES = ("GN", "GA", "GC", "GK1", "GK2", "GD", "GX")


def v(st, k, lo="bonf_low", hi="bonf_high"):
    s = st[k]
    if s["value"] is None:
        return "—"
    f = lambda x: "—" if x is None else f"{x:+.3f}"
    return f"{s['value']:+.3f} [{f(s.get(lo))}, {f(s.get(hi))}]"


print(f"main {r['n_main']} worlds, extrap {r['n_extrap']} worlds; OFF identical to E-B in every cell: {r['off_equals_EB']}\n")
print("| 臂 | 门打开比例（主评测） | " + " | ".join(GATES) + " |")
print("|---|---|" + "---|" * len(GATES))
for a in ORDER:
    x = A[a]
    sh = x["gate_share_main"]
    print(f"| {a} | {'—' if sh is None else f'{sh:.4f}'} | " + " | ".join("**过**" if x["passed"][g] else "不过" for g in GATES) + " |")
print("\n数值：点估计 [Bonferroni m = 11 下界, 上界]（GN、GA、GX 差值是相对 E-B）\n")
KEYS = (("GN", "GN"), ("GA", "GA"), ("GC", "GC"), ("GK1_all", "GK1 全部步"), ("GK1_collision", "GK1 碰撞步"),
        ("GK2_non_collision", "GK2 没有碰撞"), ("GK2_collision", "GK2 有碰撞"), ("GD_D", "GD D"), ("GD_ratio", "GD HF 比"),
        ("GX_diff", "GX 全部−E-B"), ("GX_C", "GX C"))
print("| 统计量 | " + " | ".join(ORDER) + " |")
print("|---|" + "---|" * len(ORDER))
for k, name in KEYS:
    print(f"| {name} | " + " | ".join(v(A[a]["stats"], k) for a in ORDER) + " |")
print("\n配对差（L-int-g − X，主评测，95% 按世界 bootstrap，m = 1）\n")
print("| X | 有碰撞 | 没有碰撞 | 全部 |")
print("|---|---|---|---|")
P = r["paired"]
for x in ("SCATTER", "RAND", "L-int", "L-ind-geo"):
    print(f"| {x} | " + " | ".join(v({"s": P[f'L-int-g-{x}:{w}']}, "s", "ci_low", "ci_high") for w in ("collision", "non_collision", "all")) + " |")
