"""Tier-1 self-check mutations on the phase-2 code, in the isolated copy. Each mutant: apply one text
substitution, run the relevant tests, restore. Prints killed / SURVIVED per mutant."""
import subprocess, sys
from pathlib import Path
ROOT = Path(sys.argv[1])
PY = "/Users/mac/AinerWorkFlow/AinerZero/.venv/bin/python"
G = "src/ainerzero/v9/experiments/s4/gated.py"
P = "src/ainerzero/v9/experiments/s4/analysis_p2.py"
TG, TA = "tests/v9/experiments/test_s4_gated.py", "tests/v9/experiments/test_s4_analysis_p2.py"
MUTANTS = [
    ("swap_open_closed", G, "np.where(g, np.array(p_, dtype=np.float64), pb), np.where(g, np.array(v_, dtype=np.float64), vb)",
     "np.where(g, pb, np.array(p_, dtype=np.float64)), np.where(g, vb, np.array(v_, dtype=np.float64))", TG),
    ("head_ge", G, "> math.log(p / (1 - p)))", ">= math.log(p / (1 - p)))", TG),
    ("head_self_pairs", G, "near = (dist < L.MSG_RADIUS) & ~np.eye(n, dtype=bool)[None]", "near = (dist < L.MSG_RADIUS)", TG),
    ("geo_no_overlap_rule", G, "hit = ((c <= 0) & (b < 0)) | (", "hit = (", TG),
    ("onestep_contacts_of_t", P, "for kind, i, j in self.ep.steps[t - 1].contacts if kind == \"disk\"} | {j for kind, i, j in self.ep.steps[t - 1].contacts",
     "for kind, i, j in self.ep.steps[t].contacts if kind == \"disk\"} | {j for kind, i, j in self.ep.steps[t].contacts", TA),
    ("reappear_track_at_b", P, "trk = at[e[\"a\"]][e[\"k\"]]", "trk = at[e[\"b\"]][e[\"k\"]]", TA),
    ("GN_low_to_high", P, "_gt(st[\"GN\"], \"bonf_low\", T[\"GN\"][\"diff_low\"])", "_gt(st[\"GN\"], \"bonf_high\", T[\"GN\"][\"diff_low\"])", TA),
    ("GK1_no_interval", P, "and _ge(k1a, \"bonf_low\", lo1i) and _le(k1a, \"bonf_high\", hi1i)", "", TA),
    ("neg_low", P, "_lt(st[\"neg_C\"], \"ci_high\", T[\"negative_control\"][\"C_high_below\"])", "_lt(st[\"neg_C\"], \"ci_low\", T[\"negative_control\"][\"C_high_below\"])", TA),
    ("neg_bonf", P, "_lt(st[\"neg_C\"], \"ci_high\",", "_lt(st[\"neg_C\"], \"bonf_high\",", TA),
    ("GA_strict", P, "_gt(st[\"GA\"], \"bonf_low\"", "_ge(st[\"GA\"], \"bonf_low\"", TA),
    ("no_legality_void", P, "    if not valid:\n        for k in g:\n            g[k] = dict(g[k], passed=False, void=\"legality failed\")\n", "", TA),
    ("m_not_11", P, "N_COMPARISONS = 11 ", "N_COMPARISONS = 7 ", TA),
    ("onestep_skip_last_check", P, "            if last[k] != t - 1:\n                continue\n", "", TA),
]
for name, f, old, new, test in MUTANTS:
    p = ROOT / f
    src = p.read_text()
    if src.count(old) != 1:
        print(f"{name}: STALE pattern (count {src.count(old)})", flush=True); continue
    p.write_text(src.replace(old, new))
    try:
        r = subprocess.run([PY, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "--native-mlx", test], cwd=ROOT,
                           env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=900)
        print(f"{name}: {'killed' if r.returncode != 0 else 'SURVIVED'}  {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-200:]}", flush=True)
    finally:
        p.write_text(src)
r = subprocess.run([PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--native-mlx", TG, TA], cwd=ROOT,
                   env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=900)
print("unmutated:", r.stdout.strip().splitlines()[-1])
