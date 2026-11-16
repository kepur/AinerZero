#!/usr/bin/env python3
"""Recompute values in DESIGN-r0.md §1 and §5 from results-p2*.json and run-p2*.log."""
import json
import re
from pathlib import Path

EXPLORE_DIR = Path("reports/V9-S6P2-DESIGN/tier1-explore")

def load_json(name):
    return json.loads((EXPLORE_DIR / name).read_text())

def parse_log_picks_ring(log_name):
    lines = (EXPLORE_DIR / log_name).read_text().splitlines()
    out = {}
    for line in lines:
        m = re.search(r"([A-Z][+-]) r(\d+) picks ring ([\d.]+)", line)
        if m:
            arm, r, ring = m.group(1), int(m.group(2)), float(m.group(3))
            out.setdefault(arm, {})[r] = ring
    return out

def main():
    p2a = load_json("results-p2a.json")
    p2b = load_json("results-p2b.json")
    p2c = load_json("results-p2c.json")
    p2d = load_json("results-p2d.json")
    p2e = load_json("results-p2e.json")
    p2f = load_json("results-p2f.json")
    p2g = load_json("results-p2g.json")
    p2h = load_json("results-p2h.json")
    
    p2c_log_rings = parse_log_picks_ring("run-p2c.log")

    checks = []

    # Section 1: Table A
    # baseline values from probe E-r0: D_A=0.821, all_A=0.0262
    v0_DA = 0.821
    v0_allA = 0.0262

    # A-round
    checks.append(("Round A: R+ H", p2a['arms']['R+'][3]['H'], 0.62, "%.2f"))
    checks.append(("Round A: R+ D_A", p2a['arms']['R+'][3]['D_A'], 0.827, "%.3f"))
    checks.append(("Round A: R+ all_A / v0", p2a['arms']['R+'][3]['all_A'] / v0_allA, 0.91, "%.2f"))

    checks.append(("Round A: E+ H", p2a['arms']['E+'][3]['H'], 0.55, "%.2f"))
    checks.append(("Round A: E+ D_A", p2a['arms']['E+'][3]['D_A'], 0.835, "%.3f"))
    checks.append(("Round A: E+ all_A / v0", p2a['arms']['E+'][3]['all_A'] / v0_allA, 0.91, "%.2f"))

    checks.append(("Round A: W+ H", p2a['arms']['W+'][3]['H'], 0.64, "%.2f"))
    checks.append(("Round A: W+ D_A", p2a['arms']['W+'][3]['D_A'], 0.823, "%.3f"))
    checks.append(("Round A: W+ all_A / v0", p2a['arms']['W+'][3]['all_A'] / v0_allA, 0.92, "%.2f"))

    checks.append(("Round A: E- H", p2a['arms']['E-'][3]['H'], 0.68, "%.2f"))
    checks.append(("Round A: E- D_A", p2a['arms']['E-'][3]['D_A'], 0.802, "%.3f"))
    checks.append(("Round A: E- all_A / v0", p2a['arms']['E-'][3]['all_A'] / v0_allA, 1.35, "%.2f"))

    # B-E round table
    checks.append(("Round B: R+ H", p2b['arms']['R+'][3]['H'], -0.06, "%.2f"))
    checks.append(("Round B: R+ D_A", p2b['arms']['R+'][3]['D_A'], 0.848, "%.3f"))

    checks.append(("Round B: E+ H", p2b['arms']['E+'][3]['H'], -0.03, "%.2f"))
    checks.append(("Round B: E+ D_A", p2b['arms']['E+'][3]['D_A'], 0.842, "%.3f"))
    checks.append(("Round B: E+ picks ring r1-r3", [p2b['arms']['E+'][r]['picks']['ring'] for r in (1,2,3)], [0.19, 0.11, 0.09], "list_round2"))

    checks.append(("Round B: V+ H", p2b['arms']['V+'][3]['H'], -0.03, "%.2f"))
    checks.append(("Round B: V+ D_A", p2b['arms']['V+'][3]['D_A'], 0.848, "%.3f"))
    checks.append(("Round B: V+ picks ring r1-r3", [p2b['arms']['V+'][r]['picks']['ring'] for r in (1,2,3)], [0.14, 0.12, 0.08], "list_round2"))

    checks.append(("Round B: Z+ H", p2b['arms']['Z+'][3]['H'], -0.07, "%.2f"))
    checks.append(("Round B: Z+ D_A", p2b['arms']['Z+'][3]['D_A'], 0.858, "%.3f"))

    checks.append(("Round C: X+ H", p2c['arms']['X+'][3]['H'], -0.03, "%.2f"))
    checks.append(("Round C: X+ D_A", p2c['arms']['X+'][3]['D_A'], 0.833, "%.3f"))
    checks.append(("Round C: X+ picks ring r1-r3", [p2c_log_rings['X+'][r] for r in (1,2,3)], [0.13, 0.09, 0.08], "list_round2"))

    checks.append(("Round C: Y+ H", p2c['arms']['Y+'][3]['H'], 0.02, "%.2f"))
    checks.append(("Round C: Y+ D_A", p2c['arms']['Y+'][3]['D_A'], 0.842, "%.3f"))
    checks.append(("Round C: Y+ picks ring r1-r3", [p2c_log_rings['Y+'][r] for r in (1,2,3)], [0.21, 0.35, 0.25], "list_round2"))

    checks.append(("Round D: M+ H", p2d['arms']['M+'][3]['H'], 0.28, "%.2f"))
    checks.append(("Round D: M+ D_A", p2d['arms']['M+'][3]['D_A'], 0.837, "%.3f"))
    checks.append(("Round D: M+ picks ring r1-r3", [p2d['arms']['M+'][r]['picks']['ring'] for r in (1,2,3)], [0.80, 0.15, 0.25], "list_round2"))

    checks.append(("Round E: N+ H", p2e['arms']['N+'][3]['H'], 0.31, "%.2f"))
    checks.append(("Round E: N+ D_A", p2e['arms']['N+'][3]['D_A'], 0.832, "%.3f"))
    checks.append(("Round E: N+ picks ring r1-r3", [p2e['arms']['N+'][r]['picks']['ring'] for r in (1,2,3)], [0.75, 0.79, 0.83], "list_round2"))

    checks.append(("Round E: N- H", p2e['arms']['N-'][3]['H'], 0.31, "%.2f"))
    checks.append(("Round E: N- D_A", p2e['arms']['N-'][3]['D_A'], 0.786, "%.3f"))

    checks.append(("Round B: W+ H", p2b['arms']['W+'][3]['H'], 0.33, "%.2f"))
    checks.append(("Round B: W+ D_A", p2b['arms']['W+'][3]['D_A'], 0.833, "%.3f"))

    # F, G, H rounds
    checks.append(("Round F: R+ H", p2f['arms']['R+'][3]['H'], 0.02, "%.2f"))
    checks.append(("Round F: Q+ H", p2f['arms']['Q+'][3]['H'], 0.20, "%.2f"))
    checks.append(("Round F: N+ H", p2f['arms']['N+'][3]['H'], 0.17, "%.2f"))
    checks.append(("Round F: W+ H", p2f['arms']['W+'][3]['H'], 0.24, "%.2f"))

    checks.append(("Round G: R+ H", p2g['arms']['R+'][3]['H'], -0.07, "%.2f"))
    checks.append(("Round G: Q+ H", p2g['arms']['Q+'][3]['H'], 0.17, "%.2f"))
    checks.append(("Round G: N+ H", p2g['arms']['N+'][3]['H'], 0.23, "%.2f"))
    checks.append(("Round G: W+ H", p2g['arms']['W+'][3]['H'], 0.37, "%.2f"))

    checks.append(("Round H: N+ (O+) H", p2h['arms']['O+'][3]['H'], 0.27, "%.2f"))
    checks.append(("Round H: N- (O-) H", p2h['arms']['O-'][3]['H'], 0.33, "%.2f"))

    # Section 5 gate values
    # GN: H(v*) - H(v0) = 0.27 - (-0.11) = 0.38
    checks.append(("GN explore: H(v*) - H(v0)", p2h['arms']['O+'][3]['H'] - (-0.11), 0.38, "%.2f"))
    # GF: H(c_3 N+) - H(c_3 R+) in G/H = 0.2745 - (-0.0679) = 0.3424
    checks.append(("GF explore: H(N+) - H(R+)", p2h['arms']['O+'][3]['H'] - p2g['arms']['R+'][3]['H'], 0.34, "%.2f"))
    # GE: H(c_3 N+) - H(c_3 E+) in B/E = 0.3091 - (-0.0299) = 0.339
    checks.append(("GE explore: H(N+) - H(E+)", p2e['arms']['N+'][3]['H'] - p2b['arms']['E+'][3]['H'], 0.34, "%.2f"))
    # GO: [H(N+) - H(R+)] - 0.5 * [H(W+) - H(R+)] = [0.2745 - (-0.0679)] - 0.5 * [0.3736 - (-0.0679)] = 0.3424 - 0.5 * 0.4415 = 0.1216
    go_val = (p2h['arms']['O+'][3]['H'] - p2g['arms']['R+'][3]['H']) - 0.5 * (p2g['arms']['W+'][3]['H'] - p2g['arms']['R+'][3]['H'])
    checks.append(("GO explore value", go_val, 0.12, "%.2f"))
    # GQ-H: H(N+) - H(Q+) = 0.2745 - 0.1709 = 0.1036
    checks.append(("GQ-H explore value", p2h['arms']['O+'][3]['H'] - p2g['arms']['Q+'][3]['H'], 0.10, "%.2f"))
    # GQ-W: tiny ratio for O+ across r1-r3
    tiny_o = [p2h['arms']['O+'][r]['picks']['tiny_world'] for r in (1,2,3)]
    checks.append(("GQ-W explore O+ tiny ratio", sum(tiny_o)/3, 0.02, "%.2f"))
    # GQ-W: tiny ratio for Q+ across r1-r3
    tiny_q = [p2g['arms']['Q+'][r]['picks']['tiny_world'] for r in (1,2,3)]
    checks.append(("GQ-W explore Q+ tiny ratio", sum(tiny_q)/3, 0.47, "%.2f"))
    # GR: D_A diff = 0.8422 - 0.821 = 0.0212
    checks.append(("GR D_A diff", p2h['arms']['O+'][3]['D_A'] - v0_DA, 0.02, "%.2f"))
    # GR: all_A ratio = 0.0234 / 0.0262 = 0.893
    checks.append(("GR all_A ratio", p2h['arms']['O+'][3]['all_A'] / v0_allA, 0.89, "%.2f"))
    # GU: N- 4-round D_A mean diff from v0
    da_h_n_minus = [p2h['arms']['O-'][r]['D_A'] for r in range(4)]
    checks.append(("GU H-round N- D_A mean diff", sum(da_h_n_minus)/4 - v0_DA, -0.040, "%.3f"))
    da_e_n_minus = [p2e['arms']['N-'][r]['D_A'] for r in range(4)]
    checks.append(("GU E-round N- D_A mean diff", sum(da_e_n_minus)/4 - v0_DA, -0.043, "%.3f"))

    passed = 0
    print(f"Total checks to verify: {len(checks)}")
    for name, actual, expected, fmt in checks:
        if fmt == "list_round2":
            act_str = [round(x, 2) for x in actual]
            ok = act_str == expected
            print(f"[{'OK' if ok else 'FAIL'}] {name}: actual={act_str}, design={expected}")
        else:
            act_fmt = float(fmt % actual)
            ok = abs(act_fmt - expected) < 1e-4
            print(f"[{'OK' if ok else 'FAIL'}] {name}: actual={actual} ({act_fmt}), design={expected}")
        if ok:
            passed += 1

    print(f"\nSummary: {passed} / {len(checks)} checks matched perfectly.")

if __name__ == "__main__":
    main()
