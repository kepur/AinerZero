"""P215（复核者 b）：分析前一持有者跑完的四个粗糙响应臂（H-zero、H-rev、H-mirror、H-elastic），回答卡片第 2 项：
还有没有简单代用模型能过 GR，或者让 GR 失去意义。纯 CPU，只用登记的 analysis_p2 统计函数（m = 12 的 Bonferroni 区间）。
- 把它们的格与 G 轮 results-p2g.json 的 40 个主世界合并（逐世界核对事件列表相同）；
- 每个臂：三类准确率、C、两种覆盖率、D、HF；
- 「代用模型当主臂」：把 analysis_p2.MAIN_ARM 换成它，用登记的 gate_stats / decide 判门（没跑外推，GX 无定义按不过）；
- GR 的两个方向：代用模型 − L-sc-g（它能不能过 GR）、L-int-g − 代用模型（学到的响应能不能胜过它）。
用法：python -I -B analyze_heuristics.py <results-p2g.json> <records-heuristics.json> <输出 json>"""
import json, sys
from ainerzero.v9.experiments.s4 import analysis_p2 as P2

g = json.load(open(sys.argv[1])); h = json.load(open(sys.argv[2]))
main = [r for r in g["records"] if r["kind"] == "main"]
assert h["namespace"] == "s4x-p2a" and len(h["records"]) == len(main) == 40
merged = []
for r, x in zip(main, h["records"]):
    assert (r["kind"], r["world"]) == (x["kind"], x["world"]) and r["events"] == x["events"], (r["world"], x["world"])
    merged.append(dict(r, cells={**r["cells"], **x["cells"]}, dyn={**r["dyn"], **x["dyn"]}))
ARMS = ["E-B", "E-P", "L-int-g", "L-sc-g", *h["arms"]]
v = lambda d: None if d is None or d.get("value") is None else round(d["value"], 4)
iv = lambda d: None if d is None or d.get("value") is None else [round(d["value"], 4), round(d["bonf_low"], 4), round(d["bonf_high"], 4)]
out = {"worlds": len(merged), "arms": {}, "as_main_arm": {}, "GR": {}}
for a in ARMS:
    out["arms"][a] = {"acc_collision": v(P2.acc_of(merged, a, "collision")), "acc_non_collision": v(P2.acc_of(merged, a, "non_collision")),
                      "acc_all": v(P2.acc_of(merged, a, "all")),
                      "C": v(P2.C_of(merged, a)) if a not in ("E-B", "E-P") else (0 if a == "E-B" else 1),
                      "one_step_all": v(P2.coverage_one_step(merged, a, "all")), "one_step_collision": v(P2.coverage_one_step(merged, a, "collision")),
                      "reappear_non_collision": v(P2.coverage_reappear(merged, a, "non_collision")), "reappear_collision": v(P2.coverage_reappear(merged, a, "collision")),
                      "D": v(P2.D_of(merged, a)) if a not in ("E-B", "E-P") else None, "HF": v(P2.HF_of(merged, a)) if a not in ("E-B", "E-P") else None}
for a in ["L-int-g", "L-sc-g", *h["arms"]]:
    P2.MAIN_ARM = a
    st = P2.gate_stats(merged, [])
    passed, neg = P2.decide(st)
    out["as_main_arm"][a] = {"passed": passed, "stats": {k: iv(s) for k, s in st.items() if not k.startswith("neg")}}
P2.MAIN_ARM = "L-int-g"
for a in h["arms"]:
    out["GR"][a] = {"arm_minus_L-sc-g": iv(P2.acc_diff(merged, a, "L-sc-g", "collision")), "L-int-g_minus_arm": iv(P2.acc_diff(merged, "L-int-g", a, "collision")),
                    "arm_minus_L-sc-g_non_collision": iv(P2.acc_diff(merged, a, "L-sc-g", "non_collision"))}
out["GR"]["L-int-g (registered GR)"] = {"arm_minus_L-sc-g": iv(P2.acc_diff(merged, "L-int-g", "L-sc-g", "collision"))}
json.dump(out, open(sys.argv[3], "w"), ensure_ascii=False, indent=1)
print("arm        coll   non    all    C      1step all/coll   reappear non/coll   D       HF")
for a, r in out["arms"].items():
    f = lambda x: "  —  " if x is None else f"{x:.3f}" if isinstance(x, float) else str(x)
    print(f"{a:10} {f(r['acc_collision'])} {f(r['acc_non_collision'])} {f(r['acc_all'])} {f(r['C'])}  {f(r['one_step_all'])}/{f(r['one_step_collision'])}      {f(r['reappear_non_collision'])}/{f(r['reappear_collision'])}      {f(r['D'])}  {f(r['HF'])}")
print("\nas main arm (registered decide; no extrapolation run, so GX fails by construction):")
for a, r in out["as_main_arm"].items():
    print(f"{a:10}", {k: int(p) for k, p in r["passed"].items()})
print("\nGR comparisons on collision events, value [Bonferroni m=12]:")
for a, r in out["GR"].items():
    print(f"{a:24}", r)
