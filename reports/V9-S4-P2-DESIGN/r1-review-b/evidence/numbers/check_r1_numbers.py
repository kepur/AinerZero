#!/usr/bin/env python3
"""P215: check the numbers that DESIGN-r1.md adds or changes against the exploration outputs.

Sources are parsed, never typed in: tier1-explore/summary-p2g.txt (round G, registered code and seeds),
summary-p2f-main.txt (round F), phase-1 final.json (training seconds), run-p2b2.log (residual training),
and P213's evidence (surrogate table). Each value is formatted with the design's rounding and looked up as
a substring of the design line that should carry it. Pure CPU. Usage (repository root): python -I -B <this>
"""
from __future__ import annotations

import json
import re

T = "reports/V9-S4-P2-DESIGN/tier1-explore"
DES = open("reports/V9-S4-P2-DESIGN/DESIGN-r1.md", encoding="utf-8").read().split("\n")
G = open(f"{T}/summary-p2g.txt").read().split("\n")

# --- parse round G ---------------------------------------------------------------------------------------
stat = {}
for ln in G:
    m = re.match(r"^(\w+)\s+([-+]\d\.\d+) \[([-+]\d\.\d+), ([-+]\d\.\d+)\]$", ln)
    if m:
        stat[m.group(1)] = tuple(float(x) for x in m.group(2, 3, 4))
desc = {"main": {}, "extrap": {}}
lms = {}
part = None
for ln in G:
    m = re.match(r"^(main|extrap): arm", ln)
    if m:
        part = m.group(1); continue
    m = re.match(r"^(\S+)\s+([\d.]+) ([\d.]+) ([\d.]+) \| ([\d.]+)/([\d.]+) \| ([\d.]+)/([\d.]+) \| ([\d.]*) \| ([\d.e-]*)$", ln)
    if m and part:
        desc[part][m.group(1)] = dict(coll=m.group(2), non=m.group(3), all=m.group(4), os_all=m.group(5), os_coll=m.group(6),
                                     re_non=m.group(7), re_coll=m.group(8), C=m.group(9), share=m.group(10))
    m = re.match(r"^L-int-g − L-sc-g: (\{.*\})$", ln)
    if m and part:
        lms[part] = eval(m.group(1))     # a dict literal printed by explore_p2g.py
dyn = json.loads(next(ln for ln in G if ln.startswith("dynamics "))[len("dynamics "):])
elapsed = re.search(r"(\d+) worlds in (\d+)s", "\n".join(G)).group(0)
F = open(f"{T}/summary-p2f-main.txt").read()
f_gn = re.search(r"^L-int-g@0\.5 .*?\| ([-+]\d\.\d+) \[", F, re.M).group(1)
fin = json.load(open("reports/V9-S4-PHASE1/final/final.json"))
lint_s = fin["training"]["cells"]["L-int#1"]["seconds"] / fin["steps"]
r1_s = int(re.search(r"^R#1 (\d+)s", open(f"{T}/run-p2b2.log").read(), re.M).group(1)) / 20000


def u(x):                     # the design writes the minus sign as U+2212
    return x.replace("-", "−")


def s3(x):
    return u(f"{x:+.3f}")


def b(t, plain=False):        # value [low, high] as in the design's §5 table
    f = (lambda x: f"{x:.3f}") if plain else s3
    return f"{f(t[0])} [{f(t[1])}, {f(t[2])}]"


def line_of(prefix, after=None):
    start = 0
    if after:
        start = next(i for i, l in enumerate(DES) if l.startswith(after))
    hits = [i for i, l in enumerate(DES) if i >= start and l.startswith(prefix)]
    assert hits, prefix
    return hits[0]


rows = []


def chk(prefix, label, value, after=None):
    i = line_of(prefix, after)
    rows.append((i + 1, label, value, value in DES[i]))


GT = "**G 轮：登记代码与登记种子"
XT = "**外推 20 个世界（10 盘），G 轮"
for arm, pre in (("E-B", "| E-B |"), ("E-P", "| E-P |"), ("L-int", "| 一期 L-int |"), ("L-int-g", "| **L-int-g** |"), ("L-int-g3", "| L-int-g3 |"),
                 ("L-int-g7", "| L-int-g7 |"), ("L-int-geo", "| L-int-geo |"), ("L-ind-geo", "| L-ind-geo |"), ("L-sc-g", "| **L-sc-g"), ("L-int-rand", "| L-int-rand")):
    x = desc["main"][arm]
    bold = "**" if arm in ("L-int-g", "L-sc-g") else ""
    for k, lab in (("coll", "有碰撞"), ("non", "没有碰撞"), ("all", "全部")):
        chk(pre, f"G 主评测 {arm} {lab}", f"{bold}{x[k]}{bold}", GT)
    if x["C"]:
        chk(pre, f"G 主评测 {arm} C", f"{bold}{x['C']}{bold}", GT)
    chk(pre, f"G 主评测 {arm} 一步覆盖率 全部/碰撞步", f"{bold}{x['os_all']} / {x['os_coll']}{bold}", GT)
    chk(pre, f"G 主评测 {arm} 重新出现 没有碰撞/有碰撞", f"{bold}{x['re_non']} / {x['re_coll']}{bold}", GT)
    if x["share"]:
        chk(pre, f"G 主评测 {arm} 门打开比例", f"{100 * float(x['share']):.1f}%", GT)
for arm, pre in (("E-B", "| E-B |"), ("E-P", "| E-P |"), ("L-int-g", "| L-int-g |"), ("L-sc-g", "| L-sc-g |"), ("L-ind-geo", "| L-ind-geo |")):
    x = desc["extrap"][arm]
    chk(pre, f"G 外推 {arm} 有碰撞/没有碰撞/全部", f"{x['coll']} | {x['non']} | {x['all']}", XT)
    if x["C"]:
        chk(pre, f"G 外推 {arm} C", x["C"], XT)
    chk(pre, f"G 外推 {arm} 一步覆盖率", f"{x['os_all']} / {x['os_coll']}", XT)
    chk(pre, f"G 外推 {arm} 重新出现 没有碰撞/有碰撞", f"{x['re_non']} / {x['re_coll']}", XT)
for w, lab in (("collision", "有碰撞"), ("non_collision", "没有碰撞"), ("all", "全部")):
    chk("- L-int-g − L-sc-g（按世界，95%）", f"主评测 L-int-g − L-sc-g {lab}（95%，m = 1）", u(lms["main"][w].replace("[", "[").replace(",", ",")))
chk("- 外推 20 个世界上", "外推 L-int-g − L-sc-g 有碰撞（95%）", u(lms["extrap"]["collision"]))
chk("- 外推 20 个世界上", "外推 L-int-g − L-sc-g 没有碰撞（点）", s3(float(lms["extrap"]["non_collision"].split()[0])))
chk("- 外推 20 个世界上", "外推 L-int-g − L-sc-g 全部（点）", s3(float(lms["extrap"]["all"].split()[0])))
chk("- 登记判门（m = 12）", "GR 值与 Bonferroni 区间", f"{s3(stat['GR'][0])}，Bonferroni 区间 [{s3(stat['GR'][1])}, {s3(stat['GR'][2])}]")
chk("- 登记判门（m = 12）", "负对照 C", f"C {stat['neg_C'][0]:.3f}")
chk("- 登记判门（m = 12）", "负对照 C 的 Bonferroni 上界", f"Bonferroni 上界 {stat['neg_C'][2]:.3f}")
chk("- **从精确真值出发的动力学：**", "L-int-g D（G 主评测）", f"{dyn['main']['L-int-g']['D']:.3f}")
chk("- **从精确真值出发的动力学：**", "L-int-g HF（G 主评测）", f"{dyn['main']['L-int-g']['HF']:.3f}")
chk("- **从精确真值出发的动力学：**", "一期 L-int D、HF（G 主评测）", f"{dyn['main']['L-int']['D']:.3f}、{dyn['main']['L-int']['HF']:.3f}")
chk("- A–F 轮的滤波器种子带标签", "GN 在 F 轮", u(f_gn))
chk("- A–F 轮的滤波器种子带标签", "GN 在 G 轮", s3(stat["GN"][0]))
# §5 gate table, exploration column (round G, Bonferroni m = 12)
chk("| **GN 没有碰撞不输** |", "GN", b(stat["GN"]))
chk("| **GA 全部事件胜过 E-B** |", "GA", b(stat["GA"]))
chk("| **GC 碰撞差距的补回** |", "GC", b(stat["GC"], True))
chk("| **GK1 一步预测校准** |", "GK1 全部步；碰撞步", f"{b(stat['GK1_all'], True)}；{b(stat['GK1_collision'], True)}")
chk("| **GK2 重新出现时校准** |", "GK2 没有碰撞；有碰撞", f"{b(stat['GK2_non_collision'], True)}；{b(stat['GK2_collision'], True)}")
chk("| **GD 动力学** |", "GD D、HF", f"D {b(stat['GD_D'], True)}，HF {b(stat['GD_ratio'], True)}")
chk("| **GX 外推到 10 盘** |", "GX 差值；C", f"{b(stat['GX_diff'])}；{b(stat['GX_C'], True)}")
chk("| **GR 学到的响应胜过只放宽** |", "GR", b(stat["GR"]))
chk("**负对照：**", "负对照 C、上界", f"C 是 {stat['neg_C'][0]:.3f}（上界 {stat['neg_C'][2]:.3f}）")
chk("**负对照：**", "负对照 D、上界", f"D 是 {stat['neg_D'][0]:.3f}（上界 {stat['neg_D'][2]:.3f}）")
chk("- GK1、GK2 的参照是 E-P", "E-P 一步覆盖率 全部 / 碰撞步（G）", f"{desc['main']['E-P']['os_all']} / {desc['main']['E-P']['os_coll']}")
chk("- GK1、GK2 的参照是 E-P", "E-P 重新出现 没有碰撞 / 有碰撞（G）", f"{desc['main']['E-P']['re_non']} / {desc['main']['E-P']['re_coll']}")
chk("  - G 轮 40 个世界上下界是", "GR 下界", s3(stat["GR"][1]))
chk("- **残差模型没有用。**", "残差 R#1 每步秒数（run-p2b2.log）", f"{r1_s:.4f}")
chk("- **残差模型没有用。**", "一期 L-int#1 每步秒数（final.json）", f"{lint_s:.4f}")
chk("- **残差模型没有用。**", "倍数", f"{r1_s / lint_s:.1f} 倍")
chk("  - 门的时机不可替代", "L-int-rand C（G）", f"C 只有 {desc['main']['L-int-rand']['C']}")
chk("  - 门开但模型不懂交互", "L-ind-geo C（G）", f"C 只有 {desc['main']['L-ind-geo']['C']}")
chk("  - L-sc-g 不懂碰撞", "L-sc-g C（G）", f"C 也有 {desc['main']['L-sc-g']['C']}")
chk("  - G 轮（33 格", "G 轮耗时", elapsed.split(" in ")[1].rstrip("s") + " 秒")

bad = 0
for ln, lab, v, ok in rows:
    bad += not ok
    print(f"DESIGN-r1.md:{ln:<4} {'found  ' if ok else 'MISSING'}  {lab}: {v}")
print(f"\n{len(rows)} numbers checked, {len(rows) - bad} found in the expected design line, {bad} missing")
print(f"\nextra: L-int#1 training {fin['training']['cells']['L-int#1']['seconds']} s / {fin['steps']} steps; R#1 {r1_s * 20000:.0f} s / 20000 steps; "
      f"gate shares main (G): " + ", ".join(f"{a} {float(x['share']):.4f}" for a, x in desc['main'].items() if x['share']))
