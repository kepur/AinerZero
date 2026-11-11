#!/usr/bin/env python3
"""P213: check the numbers of DESIGN-r0.md §0, §1 and the §5 gate table against the exploration outputs.

Every source value is parsed from the exploration summaries / results / logs (never typed in), formatted
with the design's rounding, and looked up as a substring of the design line that should carry it.
Prints one row per number: design line, label, source value, found or MISSING. Pure CPU.
Usage (repository root): python -I -B <this>
"""
from __future__ import annotations

import json
import re
import statistics

import numpy as np

T = "reports/V9-S4-P2-DESIGN/tier1-explore"
DESIGN = open("reports/V9-S4-P2-DESIGN/DESIGN-r0.md", encoding="utf-8").read().split("\n")
N = re.compile(r"[-+]?\d+\.\d+|nan")


def acc_table(path):
    """arm -> dict from the first table of a summarize_p2d output."""
    out = {}
    lines = open(path).read().split("\n")
    for ln in lines[1:]:
        if not ln.strip():
            break
        arm = ln.split()[0]
        x = N.findall(ln[len(arm):])
        out[arm] = dict(coll=x[0], non=x[1], all=x[2], dn=x[3], dn_lo=x[4], dn_hi=x[5], dl=x[6], dl_lo=x[7], dl_hi=x[8], C=x[9], C_lo=x[10], C_hi=x[11])
    for ln in lines:
        m = re.match(r"(\S+)\s+1-step ([\d.]+)/([\d.]+)/([\d.]+) \| reappear coll ([\d.]+) non ([\d.]+) .* err ([\d.]+) spread ([\d.]+)", ln)
        if m:
            out[m.group(1)].update(os_all=m.group(2), os_coll=m.group(3), re_coll=m.group(5), re_non=m.group(6), err=m.group(7), spread=m.group(8))
        m = re.match(r"(\S+)\s+diverged cells (\d+)", ln)
        if m:
            out.setdefault(m.group(1), {})["diverged"] = m.group(2)
    return out


def p2a_table(path):
    out = {}
    for ln in open(path).read().split("\n"):
        m = re.match(r"(\S+@q[\w.]+)\s+([\d.]+)\s+([\d.]+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+ \| ([\d.]+)/([\d.]+)/", ln)
        if m:
            out[m.group(1)] = dict(accC=m.group(2), accA=m.group(3), cov_all=m.group(4), cov_coll=m.group(5))
        m = re.match(r"(\S+@q1) (\{.*\})", ln)
        if m:
            out.setdefault(m.group(1), {}).update(json.loads(m.group(2)))
        m = re.match(r"(\S+@q1) diverged cells (\d+)", ln)
        if m:
            out.setdefault(m.group(1), {})["diverged"] = m.group(2)
    return out


def r2(x):
    return f"{float(x):.2f}"


def sgn(x):
    return f"{float(x):+.3f}".replace("-", "−")


def unsign(x):
    """design writes interval bounds with U+2212 for minus; summaries use '-'."""
    return x.replace("-", "−")


main = acc_table(f"{T}/summary-p2f-main.txt")
ext = acc_table(f"{T}/summary-p2f-extrap.txt")
p2d = acc_table(f"{T}/summary-p2d.txt")
p2e = acc_table(f"{T}/summary-p2e.txt")
p2a = p2a_table(f"{T}/summary-p2a.txt")
p2b = p2a_table(f"{T}/summary-p2b.txt")

# L-int at 3x process noise: non-collision accuracy is not printed by summarize_p2a; recompute it the
# way summarize_p2d does (events averaged over the three seeds, pooled over worlds).
ra = json.load(open(f"{T}/results-p2a.json"))
xs = ns = 0.0
for w in ra["per_world"]:
    if not w["events"]:
        continue
    per = np.mean([w["cells"][f"L-int#{s}@q3"]["correct"] for s in (1, 2, 3)], axis=0)
    non = np.array([e[3] == 0 for e in w["events"]])
    xs += per[non].sum(); ns += non.sum()
q3_non = f"{xs / ns:.3f}"

rf = json.load(open(f"{T}/results-p2f.json"))
gaps = [e[4] for w in rf["per_world"] if w["kind"] == "main" for e in w["events"]]
gap_med = statistics.median(gaps)
share = rf["gated_share"]["L-int-g@0.5"]
dyn = rf["dyn"]
rb = json.load(open(f"{T}/results-p2b.json"))["dyn"]
lintr_D = np.mean([rb[f"L-int-r#{s}"]["D"] for s in (1, 2, 3)])
lint_HF = np.mean([rb[f"L-int#{s}"]["HF"] for s in (1, 2, 3)])
p2c = json.load(open(f"{T}/results-p2c.json"))
log = open(f"{T}/run-p2b2.log").read()
r1_s = re.search(r"^R#1 (\d+)s", log, re.M).group(1)
r3_peak = re.search(r"R#3 step 14000 loss ([\d.]+)", log).group(1)


SECTIONS = {"main": "**主评测 40 个世界", "extrap": "**外推 20 个世界", "gates": "**门（L-int-g，门限 0.5）：**"}


def line_of(prefix):
    """The design line starting with ``prefix``; table rows are looked up after their table's caption
    (prefix "main:| E-B |" = first "| E-B |" row after the main-table caption)."""
    start = 0
    if ":" in prefix.split("|")[0]:
        sec, prefix = prefix.split(":", 1)
        start = next(i for i, l in enumerate(DESIGN) if l.startswith(SECTIONS[sec]))
    hits = [i for i, l in enumerate(DESIGN) if i >= start and l.startswith(prefix)]
    assert hits, prefix
    if not start:
        assert len(hits) == 1, (prefix, hits)
    return hits[0]


rows = []


def chk(prefix, label, value):
    i = line_of(prefix)
    rows.append((i + 1, label, value, value in DESIGN[i]))


def row_main(prefix, a, src, extra=True):
    chk(prefix, f"{a} 有碰撞", src["coll"]); chk(prefix, f"{a} 没有碰撞", src["non"]); chk(prefix, f"{a} 全部", src["all"])
    if extra:
        chk(prefix, f"{a} 一步覆盖率 全部/碰撞步", f"{src['os_all']} / {src['os_coll']}")
        chk(prefix, f"{a} 重新出现覆盖率 有碰撞/没有碰撞", f"{src['re_coll']} / {src['re_non']}")


# --- §1 main table ---------------------------------------------------------------------------------------
row_main("main:| E-B |", "E-B", main["E-B"])
row_main("main:| E-P |", "E-P", main["E-P"])
chk("main:| E-P |", "E-P 没有碰撞−E-B [95%]", f"{sgn(main['E-P']['dn'])} [{unsign(main['E-P']['dn_lo'])}, {unsign(main['E-P']['dn_hi'])}]")
row_main("| 一期 L-int |", "一期 L-int (p2d)", p2d["L-int"])
chk("| 一期 L-int |", "一期 L-int 没有碰撞−E-B [95%]", f"{sgn(p2d['L-int']['dn'])} [{unsign(p2d['L-int']['dn_lo'])}, {unsign(p2d['L-int']['dn_hi'])}]")
chk("| 一期 L-int |", "一期 L-int C [95%]", f"{p2d['L-int']['C']} [{p2d['L-int']['C_lo']}, {p2d['L-int']['C_hi']}]")
chk("| L-int，过程噪声 3 倍 |", "L-int q3 有碰撞 (p2a)", p2a["L-int@q3"]["accC"])
chk("| L-int，过程噪声 3 倍 |", "L-int q3 没有碰撞 (recomputed from results-p2a.json)", q3_non)
chk("| L-int，过程噪声 3 倍 |", "L-int q3 全部 (p2a)", p2a["L-int@q3"]["accA"])
chk("| L-int，过程噪声 3 倍 |", "L-int q3 一步覆盖率 全部/碰撞 (p2a)", f"{p2a['L-int@q3']['cov_all']} / {p2a['L-int@q3']['cov_coll']}")
row_main("| L-int-r（残差） |", "L-int-r@x1 (p2d)", p2d["L-int-r@x1"])
chk("| L-int-r（残差） |", "L-int-r 没有碰撞−E-B [95%]", f"{sgn(p2d['L-int-r@x1']['dn'])} [{unsign(p2d['L-int-r@x1']['dn_lo'])}, {unsign(p2d['L-int-r@x1']['dn_hi'])}]")
chk("| L-int-r（残差） |", "L-int-r C", p2d["L-int-r@x1"]["C"])
row_main("| L-int + 误差方差（有上限） |", "L-int+Qcap (p2e)", p2e["L-int+Qcap"])
chk("| L-int + 误差方差（有上限） |", "L-int+Qcap 没有碰撞−E-B [95%]", f"{sgn(p2e['L-int+Qcap']['dn'])} [{unsign(p2e['L-int+Qcap']['dn_lo'])}, {unsign(p2e['L-int+Qcap']['dn_hi'])}]")
chk("| L-int + 误差方差（有上限） |", "L-int+Qcap C", p2e["L-int+Qcap"]["C"])
g = main["L-int-g@0.5"]
for k, lab in (("coll", "有碰撞"), ("non", "没有碰撞"), ("all", "全部")):
    chk("| **L-int-g（门限 0.5）** |", f"L-int-g 0.5 {lab}", f"**{g[k]}**")
chk("| **L-int-g（门限 0.5）** |", "L-int-g 0.5 没有碰撞−E-B [95%]", f"**{sgn(g['dn'])} [{unsign(g['dn_lo'])}, {unsign(g['dn_hi'])}]**")
chk("| **L-int-g（门限 0.5）** |", "L-int-g 0.5 C [95%]", f"**{g['C']} [{g['C_lo']}, {g['C_hi']}]**")
chk("| **L-int-g（门限 0.5）** |", "L-int-g 0.5 一步覆盖率", f"**{g['os_all']} / {g['os_coll']}**")
chk("| **L-int-g（门限 0.5）** |", "L-int-g 0.5 重新出现覆盖率", f"**{g['re_coll']} / {g['re_non']}**")
g3, g7 = main["L-int-g@0.3"], main["L-int-g@0.7"]
for k, lab in (("coll", "有碰撞"), ("non", "没有碰撞"), ("all", "全部")):
    chk("| L-int-g，门限 0.3 / 0.7 |", f"L-int-g 0.3/0.7 {lab}", f"{g3[k]} / {g7[k]}")
chk("| L-int-g，门限 0.3 / 0.7 |", "L-int-g 0.3/0.7 C", f"{g3['C']} / {g7['C']}")
chk("| L-int-g，门限 0.3 / 0.7 |", "L-int-g 0.3/0.7 一步覆盖率 *全部* (cell header says 全部/碰撞步)", f"{g3['os_all']} / {g7['os_all']}")
chk("| L-int-g，门限 0.3 / 0.7 |", "L-int-g 0.3/0.7 重新出现覆盖率 *有碰撞* (cell header says 有碰撞/没有碰撞)", f"{g3['re_coll']} / {g7['re_coll']}")
row_main("| L-int-geo（几何门控） |", "L-int-geo", main["L-int-geo"])
chk("| L-int-geo（几何门控） |", "L-int-geo 没有碰撞−E-B", sgn(main["L-int-geo"]["dn"]))
chk("| L-int-geo（几何门控） |", "L-int-geo C [95%]", f"{main['L-int-geo']['C']} [{main['L-int-geo']['C_lo']}, {main['L-int-geo']['C_hi']}]")
row_main("| L-ind-geo（负对照） |", "L-ind-geo", main["L-ind-geo"])
chk("| L-ind-geo（负对照） |", "L-ind-geo 没有碰撞−E-B", sgn(main["L-ind-geo"]["dn"]))
chk("| L-ind-geo（负对照） |", "L-ind-geo C [95%]", f"{main['L-ind-geo']['C']} [{main['L-ind-geo']['C_lo']}, {main['L-ind-geo']['C_hi']}]")
chk("全部事件上，L-int-g − E-B", "L-int-g 全部−E-B [95%]", f"{sgn(g['dl'])} [{sgn(g['dl_lo'])}, {sgn(g['dl_hi'])}]")
chk("全部事件上，L-int-g − E-B", "一期 L-int 全部−E-B", sgn(p2d["L-int"]["dl"]))

# --- §1 extrapolation table --------------------------------------------------------------------------------
for a, pre in (("E-B", "extrap:| E-B |"), ("E-P", "extrap:| E-P |"), ("L-int-g@0.5", "extrap:| L-int-g |"), ("L-ind-geo", "extrap:| L-ind-geo |")):
    s = ext[a]
    chk(pre, f"外推 {a} 有碰撞/没有碰撞/全部", f"{s['coll']} | {s['non']} | {s['all']}")
    chk(pre, f"外推 {a} 一步覆盖率", f"{s['os_all']} / {s['os_coll']}")
    chk(pre, f"外推 {a} 重新出现覆盖率", f"{s['re_coll']} / {s['re_non']}")
    if a != "E-B":
        chk(pre, f"外推 {a} 全部−E-B", sgn(s["dl"]))
chk("extrap:| L-int-g |", "外推 L-int-g 全部−E-B [95%]", f"{sgn(ext['L-int-g@0.5']['dl'])} [{sgn(ext['L-int-g@0.5']['dl_lo'])}, {sgn(ext['L-int-g@0.5']['dl_hi'])}]")
chk("extrap:| L-int-g |", "外推 L-int-g C [95%]", f"{ext['L-int-g@0.5']['C']} [{ext['L-int-g@0.5']['C_lo']}, {ext['L-int-g@0.5']['C_hi']}]")
chk("extrap:| L-ind-geo |", "外推 L-ind-geo C [95%]", f"{ext['L-ind-geo']['C']} [{unsign(ext['L-ind-geo']['C_lo'])}, {ext['L-ind-geo']['C_hi']}]")

# --- §1 dynamics line and reading notes ----------------------------------------------------------------------
chk("**从精确真值出发的动力学：**", "L-int-g D 主评测", r2(dyn["main:L-int-g@0.5"]["D"]))
chk("**从精确真值出发的动力学：**", "L-int-g D 外推", r2(dyn["extrap:L-int-g@0.5"]["D"]))
chk("**从精确真值出发的动力学：**", "L-int-g HF 比 (main)", f"{dyn['main:L-int-g@0.5']['HF']:.3f}")
chk("**从精确真值出发的动力学：**", "一期 L-int HF (results-p2b dyn, seed mean)", r2(lint_HF))
chk("**从精确真值出发的动力学：**", "门打开的盘步 (gated_share L-int-g@0.5, main+extrap)", f"{100 * share:.1f}%")
chk("  - 在滤波器的成员状态上", "p2c far_open", f"{p2c['L-int']['far_open']['mean_vel_err']:.3f}")
chk("  - 在滤波器的成员状态上", "p2c near", f"{p2c['L-int']['near']['mean_vel_err']:.3f}")
chk("  - 在滤波器的成员状态上", "p2c far_wall", f"{p2c['L-int']['far_wall']['mean_vel_err']:.3f}")
chk("  - 到重新出现时", "L-int err", f"{float(p2d['L-int']['err']):.2f}")
chk("  - 到重新出现时", "E-B err", f"{float(p2d['E-B']['err']):.2f}")
chk("  - 到重新出现时", "L-int spread", f"{float(p2d['L-int']['spread']):.2f}")
chk("  - 到重新出现时", "E-B spread", f"{float(p2d['E-B']['spread']):.2f}")
chk("  - 放大到 3 倍", "L-int q3 一步覆盖率 全部", r2(p2a["L-int@q3"]["cov_all"]))
chk("  - 学到的误差方差", "L-int+Q diverged (p2b)", p2b["L-int+Q@q1"]["diverged"])
chk("  - 学到的误差方差", "L-int-r+Q diverged (p2d)", p2d["L-int-r+Q"]["diverged"])
chk("  - 学到的误差方差", "Qcap 没有碰撞−E-B", f"{abs(float(p2e['L-int+Qcap']['dn'])):.3f}")
chk("- **残差模型没有用。**", "L-int-r D (results-p2b dyn, seed mean)", f"{lintr_D:.3f}")
chk("- **残差模型没有用。**", "L-int-r 没有碰撞−E-B", f"{abs(float(p2d['L-int-r@x1']['dn'])):.3f}")
chk("- **残差模型没有用。**", "R#1 seconds per training step (736 s / 20000; run-p2b2.log)", f"{int(r1_s) / 20000:.3f}")
chk("- **残差模型没有用。**", "R#3 loss at step 14000", r3_peak.split(".")[0])
chk("- **负对照成立。**", "L-ind-geo C main / extrap", f"{ext['L-ind-geo']['C']}–{main['L-ind-geo']['C']}")
# --- §0 -----------------------------------------------------------------------------------------------------
chk("- **学习模型在不碰撞时也有误差。**", "p2c far_open (2 d.p.)", r2(p2c["L-int"]["far_open"]["mean_vel_err"]))
chk("- **学习模型在不碰撞时也有误差。**", "p2c far_wall (2 d.p.)", r2(p2c["L-int"]["far_wall"]["mean_vel_err"]))
chk("- **误差在隐藏期里累积，集合又盖不住。**", "hidden gap median, main events of results-p2f (steps)", f"{gap_med:g}")
chk("- **误差在隐藏期里累积，集合又盖不住。**", "L-int reappear coverage non-collision", r2(p2d["L-int"]["re_non"]))
chk("- **误差在隐藏期里累积，集合又盖不住。**", "E-B reappear coverage non-collision", r2(p2d["E-B"]["re_non"]))
chk("- **代价落在没有碰撞的事件上。**", "L-int 没有碰撞−E-B", f"{abs(float(p2d['L-int']['dn'])):.3f}")
chk("- 「带噪输入 D 约 0.57」", "D_filter L-int@q1 (summary-p2a)", r2(p2a["L-int@q1"]["D_filter"]))
# --- §5 gate table, exploration column ------------------------------------------------------------------------
chk("| **GN 没有碰撞不输** |", "GN 摸底值", f"{sgn(g['dn'])} [{unsign(g['dn_lo'])}, {unsign(g['dn_hi'])}]")
chk("| **GN 没有碰撞不输** |", "GN 一期 L-int", sgn(p2d["L-int"]["dn"]))
chk("| **GA 全部事件胜过 E-B** |", "GA 摸底值", f"{sgn(g['dl'])} [{sgn(g['dl_lo'])}, {sgn(g['dl_hi'])}]")
chk("| **GA 全部事件胜过 E-B** |", "GA L-ind-geo", sgn(main["L-ind-geo"]["dl"]))
chk("| **GC 碰撞差距的补回** |", "GC 摸底值", f"{g['C']} [{g['C_lo']}, {g['C_hi']}]")
chk("| **GK1 一步预测校准** |", "GK1 摸底值", f"{g['os_all']}；{g['os_coll']}")
chk("| **GK1 一步预测校准** |", "GK1 E-B 碰撞步", main["E-B"]["os_coll"])
chk("| **GK2 重新出现时校准** |", "GK2 摸底值", f"{g['re_non']}；{g['re_coll']}")
chk("| **GK2 重新出现时校准** |", "GK2 一期 L-int", f"{p2d['L-int']['re_non']}、{p2d['L-int']['re_coll']}")
chk("| **GX 外推到 10 盘** |", "GX 摸底值", f"{sgn(ext['L-int-g@0.5']['dl'])}；{ext['L-int-g@0.5']['C']}")
chk("**负对照：**", "负对照 C [95%]", f"{main['L-ind-geo']['C']} [{main['L-ind-geo']['C_lo']}, {main['L-ind-geo']['C_hi']}]")
chk("**负对照：**", "负对照 D", f"{dyn['main:L-ind-geo']['D']:.4f}")

bad = 0
for ln, lab, v, ok in rows:
    bad += not ok
    print(f"DESIGN-r0.md:{ln:<4} {'found  ' if ok else 'MISSING'}  {lab}: {v}")
print(f"\n{len(rows)} numbers checked, {len(rows) - bad} found in the expected design line, {bad} missing")

# --- extra facts quoted in the review (printed, not matched) ---------------------------------------------------
print("\nextra facts:")
lf = open(f"{T}/run-p2f.log").read()
m_end = int(re.search(r"^main 39 (\d+)s", lf, re.M).group(1))
x_end = int(re.search(r"^extrap 1019 (\d+)s", lf, re.M).group(1))
print(f"run-p2f.log (E-B, E-P + 5 gated arms = 7 arms x 3 seeds): main {m_end} s / 40 worlds = {m_end / 40:.1f} s per world; extrap {x_end - m_end} s / 20 = {(x_end - m_end) / 20:.1f} s per world")
le = open(f"{T}/run-p2e.log").read()
e_end = int(re.search(r"^world 39 (\d+)s", le, re.M).group(1))
print(f"run-p2e.log (6 arms x 3 seeds, main): {e_end} s / 40 = {e_end / 40:.1f} s per world")
print(f"R#1 residual training: {r1_s} s for 20000 steps = {int(r1_s) / 20000:.4f} s per step (design §1: 0.033)")
print(f"hidden gap (b - a - 1) over the {len(gaps)} main events of results-p2f: median {gap_med:g}, mean {np.mean(gaps):.1f}")
print(f"gated share L-int-g@0.5 (results-p2f, tracking, main + extrap pooled): {share:.4f}")
