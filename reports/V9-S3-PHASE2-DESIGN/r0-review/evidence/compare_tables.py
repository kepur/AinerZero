"""§1 表格逐格对照 results.json 与 run.log。"""
import json, re
from pathlib import Path
D = Path("/Users/mac/AinerWorkFlow/AinerZero/reports/V9-S3-PHASE2-DESIGN")
R = json.loads((D / "tier1-probe/results.json").read_text()); md = (D / "DESIGN-r0.md").read_text()
log = (D / "tier1-probe/run.log").read_text()
rows = {r.split("|")[1].strip(): [c.strip() for c in r.strip().strip("|").split("|")[1:]] for r in md.splitlines() if r.startswith("|")}
mean = lambda xs: sum(xs) / len(xs)
bad = []; n = 0
def cmp(cell, value, label, logmean=None):
    global n; n += 1
    want = float(cell); rounded = round(value + 1e-12, 3)
    if abs(want - rounded) > 1e-9:
        bad.append({"cell": label, "design": want, "results_json_mean": round(value, 5), "mean_of_rounded_log": None if logmean is None else round(logmean, 5)})
# 天花板
c = R["ceiling"]["F1"]["long_swapped"]
for row, keys in (("记录的视野里能看到答案", ("oracle_any", "top1_any", "pool_any")), ("答案就在记录的中心格", ("oracle_center", "top1_center", "pool_center"))):
    for cell, k in zip(rows[row], keys): cmp(cell, c[k], f"ceiling/{row}/{k}")
# 收敛曲线
for row, name in (("A2 手工线索", "A2"), ("A3 软混合（第一阶段写法）", "A3soft"), ("A3 硬采样（读出头每次只看一条）", "A3hard")):
    for cell, ck in zip(rows[row], ("1000", "2000", "4000", "8000")):
        cmp(cell, mean([R["curves"][f"{name}/{s}"][ck]["primary"] for s in (1, 2)]), f"curve/{name}/{ck}")
# 保护
LOG = {}
for m in re.finditer(r"prot (\S+) (\S+) (\d) before (\S+) after (\S+) masked (\S+) f2 (\S+)", log):
    LOG[m[1], m[2], int(m[3])] = (float(m[5]), float(m[6]), float(m[7]))
P = {"A2 不保护": ("A2", "none"), "A2 回放 16 回合（1%）": ("A2", "R16"), "A2 回放 64 回合（4%）": ("A2", "R64"), "A2 回放 256 回合（16%）": ("A2", "R256"), "A2 联合训练": ("A2", "joint"), "A2 参数锚定 λ=1": ("A2", "L2-1"), "A2 参数锚定 λ=10": ("A2", "L2-10"), "A3H 不保护": ("A3hard", "none"), "A3H 回放 64": ("A3hard", "R64"), "A3H 回放 256": ("A3hard", "R256"), "A3H 联合训练": ("A3hard", "joint")}
for row, (arm, how) in P.items():
    pr = [R["protection"][f"{arm}/{how}/{s}"] for s in (1, 2)]
    vals = (mean([p["after"]["primary"] for p in pr]), mean([p["after"]["primary_masked"] for p in pr]), mean([p["f2"]["primary"] for p in pr]))
    lm = [mean([LOG[arm, how, s][i] for s in (1, 2)]) for i in range(3)]
    for cell, v, name, l in zip(rows[row], vals, ("F1_open", "F1_masked", "F2"), lm): cmp(cell, v, f"prot/{arm}/{how}/{name}", l)
print("cells_checked", n, "mismatches", len(bad))
for b in bad: print(b)
drop = lambda arm, how, key="primary": mean([R["protection"][f"{arm}/{how}/{s}"]["before"][key] - R["protection"][f"{arm}/{how}/{s}"]["after"][key] for s in (1, 2)])
F2 = lambda arm, how: mean([R["protection"][f"{arm}/{how}/{s}"]["f2"]["primary"] for s in (1, 2)])
print("before A2", round(mean([R["protection"][f"A2/none/{s}"]["before"]["primary"] for s in (1, 2)]), 4), "A3H", round(mean([R["protection"][f"A3hard/none/{s}"]["before"]["primary"] for s in (1, 2)]), 4))
print("A2 open drop", {h: round(drop("A2", h), 4) for h in ("none", "R16", "R64", "R256")})
print("A2 masked drop", {h: round(drop("A2", h, "primary_masked"), 4) for h in ("none", "R16", "R64", "R256")})
print("A2 R64 per-seed open drop", [round(R["protection"][f"A2/R64/{s}"]["before"]["primary"] - R["protection"][f"A2/R64/{s}"]["after"]["primary"], 4) for s in (1, 2)])
print("A2 plasticity C0-R", {h: round(F2("A2", "none") - F2("A2", h), 4) for h in ("R16", "R64", "R256")})
print("A3H open drop", {h: round(drop("A3hard", h), 4) for h in ("none", "R64", "R256")}, "A3H F2 none-R", {h: round(F2("A3hard", "none") - F2("A3hard", h), 4) for h in ("R64", "R256")})
print("A3H-A2 by steps", {ck: round(mean([R["curves"][f"A3hard/{s}"][ck]["primary"] - R["curves"][f"A2/{s}"][ck]["primary"] for s in (1, 2)]), 4) for ck in ("1000", "2000", "4000", "8000")})
print("A3H-A3S by steps", {ck: round(mean([R["curves"][f"A3hard/{s}"][ck]["primary"] - R["curves"][f"A3soft/{s}"][ck]["primary"] for s in (1, 2)]), 4) for ck in ("1000", "2000", "4000", "8000")})
print("determinism before identical", {arm: {s: len({round(R["protection"][k]["before"]["primary"], 12) for k in R["protection"] if k.startswith(arm + "/") and k.endswith(f"/{s}") and R["protection"][k]["before"]}) for s in (1, 2)} for arm in ("A2", "A3hard")})
