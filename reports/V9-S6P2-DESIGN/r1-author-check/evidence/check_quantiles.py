"""Pure-standard-library quantile verification, AST-selected math functions only; no repository import."""
import ast
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
REL = "src/ainerzero/v9/experiments/s6/analysis.py"
source = OUT / "evidence" / "inputs" / REL
text = source.read_text()
tree = ast.parse(text)
names = {"t_cdf", "_invert", "t_ppf"}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
assert {n.name for n in nodes} == names
ns = {"math": math}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), ns)


def independent_cdf(t, df, n=16384):
    # Composite Simpson of the normalized Student density, separate from source's trigonometric CDF.
    c = math.gamma((df + 1) / 2) / (math.sqrt(df * math.pi) * math.gamma(df / 2))
    step = t / n
    def density(x):
        return c * (1 + x*x / df) ** (-(df + 1) / 2)
    return 0.5 + step / 3 * math.fsum([density(0), density(t)] +
        [(4 if i % 2 else 2) * density(i * step) for i in range(1, n)])


rows = []
for revision, k, m in [("r1", 10, 10), ("r0", 5, 9)]:
    p = 1 - .025 / m
    q = ns["t_ppf"](p, k - 1)
    half = q / math.sqrt(k)
    ref = independent_cdf(q, k - 1)
    row = {"revision": revision, "K": k, "m": m, "df": k-1, "probability": p,
           "t_ppf": q, "repeat_layer_halfwidth_coefficient": half,
           "t_6dp": format(q, ".6f"), "halfwidth_6dp": format(half, ".6f"), "halfwidth_4dp": format(half, ".4f"),
           "source_cdf_residual": ns["t_cdf"](q, k-1)-p,
           "independent_simpson_cdf": ref, "independent_cdf_residual": ref-p,
           "pass": abs(ref-p) < 1e-12}
    rows.append(row)

# df=4 also has an independent closed form: F=.5+.75*s-.25*s^3, s=t/sqrt(4+t^2).
with localcontext() as ctx:
    ctx.prec = 70
    target = Decimal(1) - Decimal('0.025') / Decimal(9)
    lo, hi = Decimal(0), Decimal(1)
    for _ in range(260):
        s = (lo + hi) / 2
        cdf = Decimal('.5') + Decimal('.75') * s - Decimal('.25') * s**3
        if cdf < target:
            lo = s
        else:
            hi = s
    s = (lo + hi) / 2
    q = 2 * s / (1 - s*s).sqrt()
    decimal_r0 = {"t_exact_probability_high_precision": str(q),
                  "halfwidth_high_precision": str(q / Decimal(5).sqrt()),
                  "formula": "F4(t)=.5+.75*s-.25*s^3, s=t/sqrt(4+t^2)"}

result = {"source_path": REL, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
          "execution": "AST-selected t_cdf/_invert/t_ppf only, math namespace; no MLX/NumPy/model imports",
          "rows": rows, "independent_decimal_r0": decimal_r0,
          "repeat_halfwidth_formula": "q/sqrt(K) * s_rep; world layer is additional and unchanged",
          "relative_repeat_halfwidth_reduction": 1 - rows[0]["repeat_layer_halfwidth_coefficient"] / rows[1]["repeat_layer_halfwidth_coefficient"],
          "r1_1_166774_correct": rows[0]["halfwidth_6dp"] == '1.166774',
          "r0_2_4313_correct": rows[1]["halfwidth_4dp"] == '2.4313',
          "formal_design_user_stated": {"arms": ["N+", "R+", "E+", "Q+", "U+", "W+", "N−"],
                                       "cells": 70, "networks": 210, "round_weights": 840, "m": 10, "df": 9,
                                       "previous_gates_lowered": False}}
with (OUT / "evidence" / "quantiles.json").open('x') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(json.dumps(result, indent=2, ensure_ascii=False))
assert all(r['pass'] for r in rows)
assert result['r1_1_166774_correct'] and result['r0_2_4313_correct']
