"""Check the numbers in DRAFT.md against their sources.

1. Tables 3 and 5 (success rates) against make_tables.py output (tables.txt, last line JSON).
2. Every bracketed interval "+a [+b, +c]" in the draft must appear verbatim in a registered result report,
   an acceptance record or a judge output (M4/M5), after normalising signs and spacing.

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
print("ALL OK" if bad == 0 else f"{bad} problem(s)")
