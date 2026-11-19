"""Check the numbers in DRAFT.md against their sources.

1. Tables 3 and 5 (success rates) against make_tables.py output (tables.txt, last line JSON).
2. Every bracketed interval "+a [+b, +c]" in the draft must appear verbatim in a registered result report,
   an acceptance record or a judge output (M4/M5), after normalising signs and spacing.
3. Numbers in the text and captions that come from the figure data must match figures/fig_data.json.

Usage: .venv/bin/python reports/V9-MINI/paper/check_draft.py
"""
from __future__ import annotations

import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
draft = (HERE / "DRAFT.md").read_text()
tables = json.loads((HERE / "tables.txt").read_text().strip().splitlines()[-1])
COLS = [("m1", "short"), ("m1", "long"), ("m2", "short"), ("m2", "long"), ("m2", "law_relevant")]


def table_rows(title: str) -> list[list[str]]:
    i = draft.index(title)
    rows = []
    for line in draft[i:].splitlines()[1:]:
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip("|").split("|")])
        elif rows:
            break
    return rows


def fmt(v: float) -> str:
    return "0" if v == 0 else f"{v:.3f}"


bad = 0
for title, m in (("**Table 3.", "M4"), ("**Table 5.", "M5")):
    rows = table_rows(title)
    for r in rows[2:]:
        arm = r[0].replace(" (privileged)", "")
        cells = r[1:]
        if arm == "episodes":
            exp = [str(tables[f"{m}-{w}"]["success"][sub]["_n"]) for w, sub in COLS]
        else:
            exp = [fmt(tables[f"{m}-{w}"]["success"][sub][arm]) for w, sub in COLS]
        for c, e, (w, sub) in zip(cells, exp, COLS):
            ok = c == e or (e == "0" and c in ("0", "0.000"))
            if not ok:
                bad += 1
                print(f"MISMATCH {m} {arm} {w}/{sub}: draft {c} source {e}")
    print(f"{title.strip('*')} checked {len(rows) - 2} rows")

sources = "\n".join(p.read_text() for p in [
    ROOT / "reports/V9-MINI/M4/M4-RESULT.md", ROOT / "reports/V9-MINI/M5/M5-RESULT.md",
    ROOT / "reports/V9-MINI/M4/analysis/judge.txt", ROOT / "reports/V9-MINI/M5/analysis/judge.txt",
    ROOT / "reports/V9-MINI/M5/analysis/summary-m2.txt", ROOT / "reports/V9-MINI/M5/analysis/summary-m1.txt",
    ROOT / "reports/V9-MINI/M4/analysis/summary-m2.txt"])


def norm(t: str) -> str:
    return t.replace("−", "-").replace(" ", "")


src = norm(sources)
pat = re.compile(r"[+−-]?\d\.\d{3} \[[+−-]?\d\.\d{3}, [+−-]?\d\.\d{3}\]")
found = set(pat.findall(draft))
for f in sorted(found):
    if norm(f) not in src:
        # the abstract drops "+" signs inside brackets; accept that form if the signed form exists
        g = re.sub(r"\[(\d)", r"[+\1", f).replace(", 0.", ", +0.")
        if norm(g) not in src:
            bad += 1
            print(f"NOT FOUND in sources: {f}")
print(f"intervals checked: {len(found)}")

# 3. Numbers in the text and figure captions that come from figures/fig_data.json (fig_data.py).
fd = json.loads((HERE / "figures" / "fig_data.json").read_text())
f4 = {w: fd["fig4"][w] for w in ("m1", "m2")}
f5 = fd["fig5"]
lt = {w: [b["rate"]["latent_topo"] for b in f4[w] if b["bin"][0] >= 20] for w in ("m1", "m2")}
expect = {
    "about 0.6 at d* = 4–5": all(abs(f4[w][0]["rate"]["latent_topo"] - 0.6) < 0.05 for w in ("m1", "m2")),
    f"at most {max(lt['m1']):.3f} (m1) and {max(lt['m2']):.3f} (m2) at d* ≥ 20": True,
    "largest at d* ≥ 30 ({:.3f} vs {:.3f}) and smallest at d* = 21–22 ({:.3f} vs {:.3f})".format(
        f4["m2"][-1]["rate"]["map_hybrid_self"], f4["m2"][-1]["rate"]["map_analytic"],
        f4["m2"][4]["rate"]["map_hybrid_self"], f4["m2"][4]["rate"]["map_analytic"]):
        # the bins named in the sentence must really hold the largest and smallest long-goal gap
        [f4["m2"][k]["bin"] for k in (4, 7)] == [[21, 22], [30, 99]] and
        (lambda g: g.index(max(g)) == 4 and g.index(min(g)) == 1)(
            [b["rate"]["map_hybrid_self"] - b["rate"]["map_analytic"] for b in f4["m2"][3:]]),
    "({} of the {} maps of that run have such a goal)".format(fd["fig1"]["n_satisfying_rule"], fd["fig1"]["n_layouts"]): True,
    "the first of {} qualifying maps among {}".format(fd["fig1"]["n_satisfying_rule"], fd["fig1"]["n_layouts"]): True,
    "no goals between 11 and 19": fd["fig4"]["m1_n_between_short_and_long"] == 0 and fd["fig4"]["m2_n_between_short_and_long"] == 0,
    "m1 {}–{}, except {} (26–29) and {} (≥ 30); m2 {}–{}".format(
        min(b["n"] for b in f4["m1"][:-2]), max(b["n"] for b in f4["m1"]), f4["m1"][-2]["n"], f4["m1"][-1]["n"],
        min(b["n"] for b in f4["m2"]), max(b["n"] for b in f4["m2"])): True,
    "{} of {} ({:.0%})".format(f5["lost"]["n"], f5["lost"]["n"] + f5["localized"]["n"], f5["share_lost_among_long"]): True,
    "lost: {} episodes on {} map clusters; localized: {} on {}".format(
        f5["lost"]["n"], f5["lost"]["clusters"], f5["localized"]["n"], f5["localized"]["clusters"]): True,
    "map_hybrid succeeds on {:.3f} vs {:.3f}, map_analytic on {:.3f} vs {:.3f}".format(
        f5["lost"]["rate"]["map_hybrid"], f5["localized"]["rate"]["map_hybrid"],
        f5["lost"]["rate"]["map_analytic"], f5["localized"]["rate"]["map_analytic"]): True,
    "These account for {:.0f}% of map_hybrid's long-goal failures".format(100 * f5["share_lost_among_map_hybrid_long_failures"]): True,
    "coincide on long goals ({:.3f})".format(fd["fig3"]["m1"]["map_hybrid_self"]["long"]["rate"]): True,
}
for k, cond in expect.items():
    ok = cond and k in draft
    if not ok:
        bad += 1
        print(f"FIGURE NUMBER NOT FOUND OR WRONG: {k}")
print(f"figure-derived numbers checked: {len(expect)}")
print("ALL OK" if bad == 0 else f"{bad} problem(s)")
