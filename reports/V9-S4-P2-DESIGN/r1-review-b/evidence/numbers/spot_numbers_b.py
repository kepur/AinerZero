"""P215（复核者 b）：独立抽查 r1 新增或改动的数字。每条写明设计稿行号与它应含的原文片段、摸底文件与它应含的原文片段（或由文件算出的值），
两边都按整词（前后不是数字或小数点）精确匹配，并打印两边的原始行。纯 CPU。用法（仓库根目录）：python -I -B <this>"""
import json, re
D = "reports/V9-S4-P2-DESIGN/DESIGN-r1.md"; T = "reports/V9-S4-P2-DESIGN/tier1-explore"
des = open(D, encoding="utf-8").read().split("\n")
def word(tok, line):
    return re.search(r"(?<![\d.])" + re.escape(tok) + r"(?![\d])", line) is not None
def src_line(path, startswith):
    return next(l for l in open(path, encoding="utf-8").read().split("\n") if l.startswith(startswith))
G = lambda s: src_line(f"{T}/summary-p2g.txt", s)
gx = open(f"{T}/summary-p2g.txt").read().split("\n\nextrap")[1]
GX = lambda s: next(l for l in gx.split("\n") if l.startswith(s))
dyn = json.loads(G("dynamics ")[len("dynamics "):])
fin = json.load(open("reports/V9-S4-PHASE1/final/final.json"))
r1 = int(re.search(r"^R#1 (\d+)s", open(f"{T}/run-p2b2.log").read(), re.M).group(1))
checks = [  # (设计稿行, 设计稿片段, 来源说明, 来源原文行, 来源片段)
 (92, "0.612", "summary-p2g main L-sc-g", G("L-sc-g "), "0.612"), (92, "0.857", "同上", G("L-sc-g "), "0.857"), (92, "0.803", "同上", G("L-sc-g "), "0.803"),
 (92, "0.738", "同上 C", G("L-sc-g "), "0.738"), (92, "0.901 / 0.858", "同上 一步覆盖率", G("L-sc-g "), "0.901/0.858"), (92, "0.890 / 0.755", "同上 重新出现覆盖率", G("L-sc-g "), "0.890/0.755"),
 (92, "2.9%", "同上 门打开比例 0.0293", G("L-sc-g "), "0.02933"), (93, "0.034", "summary-p2g main L-int-rand C", G("L-int-rand "), "0.034"),
 (93, "0.880 / 0.529", "同上 重新出现覆盖率", G("L-int-rand "), "0.880/0.529"),
 (95, "+0.046 [+0.012, +0.083]", "summary-p2g main L-int-g − L-sc-g 有碰撞（95%）", G("L-int-g − L-sc-g"), "+0.046 [+0.012, +0.083]"),
 (95, "+0.022 [+0.005, +0.039]", "同上 没有碰撞", G("L-int-g − L-sc-g"), "+0.022 [+0.005, +0.039]"),
 (95, "+0.028 [+0.011, +0.044]", "同上 全部", G("L-int-g − L-sc-g"), "+0.028 [+0.011, +0.044]"),
 (96, "+0.066 [+0.022, +0.107]", "summary-p2g extrap L-int-g − L-sc-g 有碰撞", GX("L-int-g − L-sc-g"), "+0.066 [+0.022, +0.107]"),
 (97, "+0.046", "summary-p2g GR", G("GR "), "+0.046 [-0.003, +0.099]"), (97, "−0.003, +0.099", "同上 Bonferroni 区间", G("GR "), "[-0.003, +0.099]"),
 (97, "0.185", "summary-p2g neg_C 上界", G("neg_C "), "+0.185]"), (190, "0.011", "summary-p2g neg_D 上界", G("neg_D "), "+0.011]"),
 (98, "0.852", "dynamics main L-int-g D 0.8517", G("dynamics "), "0.8517"), (98, "0.026", "dynamics main L-int-g HF 0.0262", G("dynamics "), "0.0262"),
 (98, "0.855", "dynamics main L-int D 0.8547", G("dynamics "), "0.8547"), (98, "0.075", "dynamics main L-int HF 0.075", G("dynamics "), "0.075"),
 (107, "0.452", "summary-p2g extrap L-sc-g", GX("L-sc-g "), "0.452"), (107, "0.650", "同上 C", GX("L-sc-g "), "0.650"), (107, "0.864 / 0.686", "同上 重新出现覆盖率", GX("L-sc-g "), "0.864/0.686"),
 (187, "+0.089 [+0.047, +0.136]", "summary-p2g GX_diff", G("GX_diff "), "+0.089 [+0.047, +0.136]"), (187, "1.025 [0.782, 1.261]", "summary-p2g GX_C", G("GX_C "), "+1.025 [+0.782, +1.261]"),
 (75, "0.667", "summary-p2f-main L-int-g@0.3", src_line(f"{T}/summary-p2f-main.txt", "L-int-g@0.3       "), "0.667"),
 (75, "0.98", "同上 C", src_line(f"{T}/summary-p2f-main.txt", "L-int-g@0.3       "), "0.98 [0.88,1.07]"),
 (76, "0.94", "summary-p2f-main L-int-g@0.7 C", src_line(f"{T}/summary-p2f-main.txt", "L-int-g@0.7       "), "0.94 [0.84,1.04]"),
 (120, "0.0368", f"run-p2b2.log R#1 {r1} s / 20000 步 = {r1 / 20000:.4f}", f"{r1 / 20000:.4f}", "0.0368"),
 (120, "0.0176", f"phase-1 final.json L-int#1 秒数 / 20000", f"{fin['training']['cells']['L-int#1']['seconds'] / 20000:.4f}", "0.0176"),
 (120, "2.1", "两者之比", f"{(r1 / 20000) / (fin['training']['cells']['L-int#1']['seconds'] / 20000):.2f}", "2.09"),
 (120, "3502", "run-p2b2.log R#3 第 14000 步", src_line(f"{T}/run-p2b2.log", "  R#3 step 14000"), "3502.4878"),
 (255, "970", "summary-p2g 第 2 行", open(f"{T}/summary-p2g.txt").read().split("\n")[1], "970s"),
]
ok = 0
for ln, dtok, what, sline, stok in checks:
    a, b = word(dtok, des[ln - 1]), stok in sline
    ok += a and b
    print(f"{'OK ' if a and b else 'BAD'} DESIGN-r1.md:{ln} 含「{dtok}」={a} | {what} 含「{stok}」={b}\n     设计稿: {des[ln - 1].strip()[:150]}\n     来源:   {sline.strip()[:150]}")
print(f"\n{ok} / {len(checks)} 一致")
